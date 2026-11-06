#!/usr/bin/env python3
"""Fuzz the panel's command vocabulary and sort the answers into three piles.

The panel turns a request into one of three outcomes, which is the whole oracle:

    no answer        the topic (or verb) is not in the firmware at all
    1 200            accepted, ack or JSON body follows
    1 4xx            the topic exists but the body/params were wrong

So a table of candidate (request line, json body) pairs maps out the command set
without needing a capture of each one. `1 400` answers to `POST realtimeDisplay 1
{"value":1}` is how this found that realtimeDisplay is a real command.

Nothing here reboots or reflashes anything, and it cannot: the topics
`protocol.BLOCKED_TOPICS` names (firmware, update, upgrade, config, recovery,
logo, mode, presetThemeId, and the media-store writes) are dropped from the
table before the first request, because `Link` would refuse them mid-sweep and
this loop reads a refusal as a dead link.  `recovery` is not in the table at
all: it re-enumerates the USB device, which is a factory reset arriving through
a discovery tool, and `tools/reset_panel.py --yes` is the one place it goes out.
Writes that are harmless and reversible (brightness, timeout) are put back.

    tools/fuzz.py                       run the built-in table
    tools/fuzz.py --grep display        only topics matching 'display'
    tools/fuzz.py --file probes.txt     read "REQUEST LINE<TAB>{json}" lines
    tools/fuzz.py -v                    frame-level logging
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from xigmalcd import sensors                                   # noqa: E402
from xigmalcd.protocol import (BLOCKED_TOPICS, Link, ProtocolError,  # noqa: E402
                               find_ports)

M = sensors.collect()          # a real metrics blob, for bodies that want one

# ---------------------------------------------------------------- candidates --
# topic: the payload shapes ALPHA's own binary hints at, plus obvious guesses
PROBES = [
    # --- realtime display: the panel drawing our numbers itself --------------
    ("POST realtimeDisplay 1", {"value": 1}),
    ("POST realtimeDisplay 1", {"value": True}),
    ("POST realtimeDisplay 1", {"state": 1}),
    ("POST realtimeDisplay 1", {"enable": 1}),
    ("POST realtimeDisplay 1", {"on": True}),
    ("POST realtimeDisplay 1", {"status": 1}),
    ("POST realtimeDisplay 1", M),
    ("POST realtimeDisplay 1", {"cpu": M["cpu"]}),
    ("POST realtimeDisplay 1", {"data": M}),
    ("POST realtimeDisplay 1", {"value": M}),
    ("POST realtimeDisplay 1", {}),
    ("POST realtimeDisplay 1", None),
    ("POST realtime 1", M),
    ("POST sysinfoDisplay 1", M),
    ("POST display 1", {"value": 1}),
    # --- power / sleep ------------------------------------------------------
    ("POST power 1", {"event": "resume"}),
    ("POST power 1", {"event": "sleep"}),
    ("POST power 1", {"event": "off"}),
    ("POST power 1", {"value": 1}),
    ("POST power 1", None),
    # --- brightness, unit, page select --------------------------------------
    ("POST brightness 1", {"value": 20}),
    ("POST brightness 1", {"brightness": 20}),
    ("POST brightness 1", 20),
    ("POST degree 1", {"value": 1}),
    ("POST degree 1", 1),
    ("POST mode 1", {"value": 1}),
    ("POST mode 1", 1),
    ("POST logo 1", {"value": 1}),
    ("POST page 1", {"value": 1}),
    ("POST osd 1", {"value": 1}),
    ("POST osdState 1", {"value": 1}),
    # --- the metrics blob under other names ---------------------------------
    ("STATE all 1", M),
    ("STATE status 1", M),
    ("STATE realtime 1", M),
    ("STATE all 2", M),
    ("PUT all 1", M),
    # --- transport / files --------------------------------------------------
    # NB: do NOT announce a transfer and then not send the bytes: the panel
    # takes the next framed requests as file data. POST config 1 with an empty
    # body was also seen to reset the firmware, so it is not probed either.
    ("POST transporting 1", {"index": 0, "blockSize": 0}),
    ("POST background 1", {"type": "media", "fileSize": 0, "fileName": "x.osd"}),
    # `recovery` is deliberately not probed here even though it is in the
    # vocabulary: it re-enumerates the USB device, which this loop would read as
    # "the link went down" and then revive, i.e. a factory reset caused by a
    # discovery sweep.  tools/reset_panel.py --yes is the one place it is sent.
    ("POST conn 1", None),
    ("POST timeout 1", {"value": 60}),
    # --- verbs the app uses but the captures never showed -------------------
    ("GET conn 1", None),
    ("GET transport 1", None),
    # a name the panel cannot have, so this asks whether the verb exists without
    # being able to remove anything that is stored
    ("DELETE media 1", {"fileName": "nope.osd"}),
    ("SET brightness 1", {"value": 100}),
    ("PUT brightness 1", {"value": 100}),
]


def classify(line, replies):
    """One of: silent | 2xx | 4xx | other."""
    if not replies:
        return "silent"
    codes = [m.code for m in replies if m.code]
    if any(c.startswith("4") or c.startswith("5") for c in codes):
        return "4xx"
    if any(c.startswith("2") for c in codes):
        return "2xx"
    return "other"


def probe_once(link, line, body, wait=1.2):
    """One request, plus every reply that arrives within `wait`."""
    link.request(line, body)
    reps, deadline = [], time.monotonic() + wait
    while time.monotonic() < deadline:
        m = link.read(timeout=max(0.05, deadline - time.monotonic()))
        if m is None:
            break
        reps.append(m)
    return reps


def revive(link, verbose=False):
    """Wait out a firmware reset (the panel re-enumerates) and open it again."""
    time.sleep(6.0)
    try:
        link.close()
    except Exception:
        pass
    port, baud = link.ser.portstr, link.ser.baudrate
    for _ in range(6):
        try:
            fresh = Link(port, baud, verbose=verbose)
            fresh.hello()
            print("  .. link back")
            return fresh
        except Exception:
            time.sleep(3.0)
    raise SystemExit("the panel did not come back")


def run(link, probes, verbose=False, gap=0.12):
    """Send each probe, read what comes back, return {outcome: [...]}, link.

    A bad request can reset the panel's firmware - it re-enumerates as the
    ArtInChip 'USB download gadget' and returns a few seconds later - so a dead
    link is caught, attributed to the probe in flight, and revived.
    """
    out, crashed = {}, []
    for line, body in probes:
        try:
            reps = probe_once(link, line, body)
        except Exception as exc:
            crashed.append(line)
            print(f" !! {line} went down with the link: {exc!r}")
            link = revive(link, verbose)
            continue
        kind = classify(line, reps)
        out.setdefault(kind, []).append((line, body, reps))
        flag = {"silent": "  -    ", "2xx": " OK  ", "4xx": " 400 ",
                "other": " ??  "}[kind]
        txt = ""
        if reps:
            codes = " ".join(m.code for m in reps if m.code)
            bodies = " ".join(m.body.decode("utf-8", "replace")[:90]
                              for m in reps if m.body)
            txt = f" [{codes}] {bodies}"
        print(f"{flag} {line:<34} "
              f"{'' if body is None else json.dumps(body)[:60]}{txt}")
        if kind != "silent":
            link.drain(timeout=0.05)
        time.sleep(gap)
    if crashed:
        print("\n !! link dropped during: " + ", ".join(crashed))
    return out, link


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("--grep", help="only probe topics matching this")
    ap.add_argument("--file", help="extra probes: 'REQUEST LINE<TAB>{json}' per line")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    probes = list(PROBES)
    if args.file:
        for ln in open(args.file):
            ln = ln.rstrip("\n")
            if not ln or ln.startswith("#"):
                continue
            line, _, body = ln.partition("\t")
            probes.append((line.strip(), json.loads(body) if body.strip() else None))
    if args.grep:
        rx = re.compile(args.grep, re.I)
        probes = [p for p in probes if rx.search(p[0])]
    # `Link` refuses these unless the caller asks for a destructive link, and the
    # run loop would report that refusal as "the link went down" and reopen the
    # port.  Panel-state writes (logo, mode, presetThemeId) and firmware traffic
    # are not a discovery sweep's business, so they are dropped here and named.
    def topic_of(line: str) -> str:
        parts = line.split()
        return parts[1] if len(parts) > 1 else ""

    held = sorted({topic_of(line) for line, _ in probes
                   if topic_of(line) in BLOCKED_TOPICS})
    probes = [p for p in probes if topic_of(p[0]) not in BLOCKED_TOPICS]
    if held:
        print(f"  not sent, our own guard: {', '.join(held)}")
    if not probes:
        print("nothing matched --grep")
        return 1

    port = args.device or (find_ports() or [("/dev/ttyACM0", "?")])[0][0]
    print(f"probing {port} with {len(probes)} requests\n")
    link = Link(port, args.baud, verbose=args.verbose)
    info = link.hello()
    print(f"device sn={info.get('sn')} fw={info.get('version', {}).get('firmware')} "
          f"brightness={info.get('brightness')} mode={info.get('mode')}\n")

    out, link = run(link, probes, args.verbose)

    print(f"\n== accepted ({len(out.get('2xx', []))}) ==")
    for line, body, reps in out.get("2xx", []):
        print(f"  {line}  {json.dumps(body)[:110] if body is not None else ''}")
    print(f"\n== exists, wrong body ({len(out.get('4xx', []))}) ==")
    for line, body, reps in out.get("4xx", []):
        print(f"  {line}  {json.dumps(body)[:110] if body is not None else ''}")
    print(f"\n== ignored, so not in this firmware ({len(out.get('silent', []))}) ==")
    for line, body, reps in out.get("silent", []):
        print(f"  {line}")

    # undo the writes we know how to undo, and put a picture back on the panel
    # in case a mediaDelete probe took one away
    for line, body in (("POST brightness 1", {"value": 100}),
                       ("POST mode 1", {"value": 0}),
                       ("POST degree 1", {"value": 0}),
                       ("POST timeout 1", {"value": 60})):
        link.request(line, body)
        link.drain(timeout=0.2)
    try:
        from xigmalcd import render
        link.send_media(render.frame_name(), render.to_png(render.draw(M, "gauge")))
        print("\n(put a fresh frame back on the panel)")
    except (ProtocolError, OSError) as exc:
        print(f"\n(did not restore the picture: {exc})")
    link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
