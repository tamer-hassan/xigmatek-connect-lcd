#!/usr/bin/env python3
"""blob_probe.py - ask the panel, in one minute, what it makes of a `STATE all 1` body it has not seen.

Two decisions in this tree are waiting on a fact nobody has measured, and both are about the
metrics blob:

1. **May a layout carry a temperature per drive?**  `disk.temperature` is one scalar in the
   vendor's schema (PROTOCOL.md §8), and "how hot is each drive" needs an extra section in that
   body.  What the logs show is a bare `200` for every `STATE all 1` frame - 34 of them, and
   `STATE all` is sent twice per session, not once a frame.  "it answered 200 to the bodies we
   sent" is not the same statement as "it answers 200 to a body with a key it has never seen",
   and the difference is what per-drive rows hinge on.
2. **What does it make of `"type":"Pump"`?**  Every captured `fans[]` entry spells `"Fan"` or
   `"Chassis"`.  Since 2026-11-13 this program sends a third value, for a channel pinned as a
   pump by measurement.  The row is not new: the installed build already sends it, under the
   name `nct6687 fan2` and typed `Fan`.  So the question is exactly as narrow as the string.

Method: open the port, read the panel's own state, send five `STATE all 1` bodies - a control,
the pump-typed one, the extra-section one, both together, and the control again - printing the
panel's answer to each, then upload one ordinary frame as the control that says the link still
behaves, and read the state again.  The control at the end matters: a `200` that arrives for all
five bodies means nothing if the next upload is refused.

Safety, stated as the boundary the checks hold:

* it never touches a destructive or firmware topic: `recovery`, `config`, `logo`, `mode`,
  `presetThemeId`, `firmware`, `mediaDelete` (`FORBIDDEN_TOPICS` below);
* it does not open the port without `--yes`, and prints what it would send instead;
* it refuses while the display service is running, because one process can hold the port
  (PROTOCOL.md §1) and a probe that silently takes over someone's loop is not a measurement;
* it never prints the panel's serial: only `PRINTED_KEYS` are echoed, and that list is gated.

This is a bench instrument, not a fixture: its transcript belongs in `data/glass/` (which this
repository does not publish, for the serial's sake) and the verdict it reaches belongs in
PROTOCOL.md §8.

    tools/blob_probe.py                                  # dry run: nothing is opened
    tools/blob_probe.py --yes                            # the five bodies and one frame
    tools/blob_probe.py --yes --skip-frame               # acks only
    tools/blob_probe.py --yes --device /dev/ttyACM0 -v
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xigmalcd import protocol, render, sensors                      # noqa: E402

#: Topics this tool must never send.  A check reads this name out of the source and asserts
#: none of them appears anywhere in this file's request calls.
FORBIDDEN_TOPICS = ("recovery", "config", "logo", "mode", "presetThemeId", "firmware",
                    "mediaDelete", "factory", "update")

#: What is echoed from `device_info()`.  `sn` is deliberately absent: the panel's serial number
#: does not go into a transcript, and a tool that dumps the whole dict would put it there.
PRINTED_KEYS = ("mode", "logo", "osdState", "brightness", "timeout", "degree", "space",
                "ver", "productID")

DEFAULT_DEVICE = "/dev/xigmatek-lcd"


def service_active(unit: str = "xigmalcd") -> bool:
    """True when the display loop is holding the port.

    Asked of systemd rather than by trying to open the port: a failed open says something holds
    it, not that taking it over is safe.  A missing systemctl (a container, a runner) answers
    False, and the probe then still refuses anything but an explicit --yes.
    """
    try:
        got = subprocess.run(["systemctl", "--user", "is-active", f"{unit}.service"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return (got.stdout or "").strip() == "active"


def drive_rows() -> list:
    """Per-drive temperatures, the section whose tolerance is being asked about."""
    out = []
    for _chip, dev, rows in sensors._disk_channels():
        comp = [v for label, v in rows if label.lower() == "composite"]
        out.append({"name": dev,
                    "temperature": round((max(comp) if comp else max(v for _l, v in rows))
                                         / 1000),
                    "sensors": sorted(round(v / 1000, 1) for _l, v in rows)})
    return out


def bodies() -> list:
    """The payloads to send, each named for the question it answers.

    Each entry is `(label, body, delta)` and the delta says what changed against the control,
    stated rather than derived at print time - so the dry run can name exactly what the panel
    has never been sent without reading the machine three more times.

    The control is **stripped of the Pump type on purpose.**  On this box `sensors.collect()`
    already puts a `Pump` row in `fans[]` - the channel pinned on 2026-11-13 - so the first
    version of this tool sent a control that carried the very value the experiment was meant to
    isolate, and the pair proved nothing: both bodies answered `200` because both contained it.
    The control now normalises every fan row's `type` to the two values the vendor's 34 captured
    bodies actually spell, and the Pump body is the same rows with one `type` string changed.
    That is the difference being asked about, and nothing else.
    """
    raw = sensors.collect()
    base = dict(raw)
    base["fans"] = [dict(f, type=("Fan" if f.get("type") == "Pump" else f.get("type")))
                    for f in (raw.get("fans") or [])]
    rows = drive_rows()
    pump = dict(base)
    pump["fans"] = list(base["fans"]) + [{"onBoard": True, "type": "Pump",
                                          "name": "PROBE PUMP", "value": 2453}]
    drives = dict(base)
    drives["drives"] = rows
    both = dict(drives)
    both["fans"] = pump["fans"]
    return [
        ("control - the vendor's shape: fan rows typed Fan/Chassis only", base,
         "nothing: this is the body the captures show"),
        ("a fan row typed Pump", pump,
         "one extra row whose `type` is 'Pump' - a value no captured body spells; no other "
         "key differs from the control"),
        ("an extra section, `drives`", drives,
         f"a new top-level key 'drives' with {len(rows)} row(s) - the vendor's schema has no "
         f"such key"),
        ("both together", both, "both of the above in one frame"),
        ("control again - the answer should not have changed", base,
         "nothing: the control, sent last"),
    ]


def show_state(link, tag: str) -> dict:
    info = link.device_info()
    echo = {k: info.get(k) for k in PRINTED_KEYS if k in info}
    print(f"  {tag}: " + " ".join(f"{k}={echo[k]}" for k in sorted(echo)))
    return info


def probe(link, label: str, body: dict, verbose: bool) -> str:
    """One `STATE all 1`, with the panel's own answer read back.

    The verdict recorded is the **code** the panel answered with, not the whole frame: an ack
    carries a rising `AckNumber`, so comparing the raw messages made every body look different
    and the summary line "all bodies answered alike" came out False for a run where all five
    answered `200`.  The frame is still printed, in full, above it.
    """
    ack = link.state_all(body, wait=True)
    if ack is None:
        verdict, full = "no answer", "None"
    else:
        full = str(ack)
        verdict = getattr(ack, "code", None) or (full.split(" ")[2] if len(full.split(" ")) > 2
                                                 else full)
    print(f"  {label}\n    keys sent: {sorted(body)}\n    answer:    {full}\n    code:      {verdict}")
    if verbose:
        print("    body: " + json.dumps(body, default=str)[:500])
    return verdict


def upload_a_frame(link, verbose: bool) -> str:
    """The end control: can the panel still take a picture after the odd bodies?

    Built and sent through the same doors the loop uses - `render.draw` for the frame,
    `render.to_png` for the 256-colour file the panel is fed by default, `Link.send_media`
    for the announcement-bytes-ack sequence measured in §6.
    """
    img = render.draw(sensors.collect(), "alpha")
    png = render.to_png(img, palette=True)
    name = render.frame_name()
    if verbose:
        print(f"    frame: {name} {len(png)} B")
    link.send_media(name, png, wait=True)
    return f"frame {name} ({len(png)} B) accepted"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device", default=DEFAULT_DEVICE,
                    help=f"serial port to use (default {DEFAULT_DEVICE})")
    ap.add_argument("--yes", action="store_true",
                    help="actually talk to the panel; without it, nothing is opened")
    ap.add_argument("--skip-frame", action="store_true",
                    help="send only the metrics bodies, no uploads")
    ap.add_argument("--pump-only", action="store_true",
                    help="just the control and the Pump-typed body")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    print("this tool sends `STATE all 1` bodies and reads the panel's answer to each one.")
    print("topics it will never send: " + ", ".join(FORBIDDEN_TOPICS))
    print(f"keys it will echo from the panel's state: {', '.join(PRINTED_KEYS)}  "
          f"(the serial is not among them)")

    planned = bodies()
    if a.pump_only:
        planned = [planned[0], planned[1], planned[4]]

    if not a.yes:
        print("\nno --yes, so nothing was opened.  What it would send:")
        for label, body, delta in planned:
            print(f"  {label}\n    keys: {sorted(body)}\n    change: {delta}")
        print("\nand the frame control it would send afterwards (unless --skip-frame), because")
        print("five `200`s mean nothing if the next picture is refused:")
        print("  render.draw -> render.to_png -> Link.send_media (one ordinary `alpha` frame)")
        print("\nand the port would be taken from the display service if it is running:")
        print("  systemctl --user stop xigmalcd && tools/blob_probe.py --yes && "
              "systemctl --user start xigmalcd")
        return 2
    if not os.path.exists(a.device):
        print(f"\nno device at {a.device}.  Nothing was opened.", file=sys.stderr)
        return 2
    if service_active():
        print("\nthe display service is active and holds the port - exactly one opener "
              "(PROTOCOL.md §1).  Stop it first and restart it after:\n"
              "  systemctl --user stop xigmalcd\n  tools/blob_probe.py --yes\n"
              "  systemctl --user start xigmalcd\nNothing was opened.", file=sys.stderr)
        return 2

    print(f"\nopening {a.device}")
    answers: dict = {}
    with protocol.Link(a.device, timeout=3.0) as link:
        link.start_pump()
        link.hello()
        before = show_state(link, "state before")
        print("\nthe bodies:")
        for label, body, _delta in planned:
            answers[label] = probe(link, label, body, a.verbose)
            time.sleep(0.2)
        if not a.skip_frame:
            print("\nthe frame control:")
            try:
                answers["frame"] = upload_a_frame(link, a.verbose)
                print("  " + answers["frame"])
            except Exception as exc:                                    # noqa: BLE001
                answers["frame"] = f"frame refused: {exc}"
                print("  " + answers["frame"])
        after = show_state(link, "state after")

    print("\nsummary:")
    for label, verdict in answers.items():
        print(f"  {label}: {verdict}")
    acks = [v for k, v in answers.items() if k != "frame"]
    print(f"  all bodies answered alike: {len(set(acks)) == 1}")
    for key in ("space", "osdState", "mode"):
        if before.get(key) is not None:
            print(f"  {key}: {before.get(key)} -> {after.get(key)}")
    print("  a `200` for every body plus an accepted frame afterwards is the answer this tool "
          "was written to get.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
