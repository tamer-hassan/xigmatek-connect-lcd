#!/usr/bin/env python3
"""Walk the panel's own pages so a person can watch and report what changes.

The fuzzer showed `POST mode 1 {"value":N}` and `POST logo 1 {"value":N}` answer
`1 200` while the panel's conn reply advertises attribute pages
["Status","Fan","Pump"] plus fields mode / logo / osdState.  Read that verdict
carefully: `200` means the body parsed, and on this firmware it is all it means -
the field lands at `2147483647`, the panel's "not set", which is the white-screen
state the danger note in docs/limits.md describes.  Whether those commands select the page
the panel draws from the `STATE all 1` metrics blob can only be settled by looking
at the display, so this script cycles the values, slowly, and prints what it sent.
That is the whole point of the tool, and the reason it needs `--force`: it writes
three guarded topics, it cannot verify what it did, and the panel has no readback.

`POST presetThemeId 1 {"index":N}` is different: it is ALPHA's own call, it selects
one of the panel's **built-in themes**, and it needs no upload — which makes it the one
request that can still change the screen while the media channel is refusing files.
Indexes 0..8 are accepted, 9 is `1 400`, and nothing about the choice shows up in the
`conn` reply, so again: eyes on the panel.

    tools/pages.py --force                 mode 0..4, logo 0..3, themes 0..8, then
                                           the tool re-sends mode/logo as conn
                                           reported them at the start
    tools/pages.py --force --dwell 10      slower, easier to read
    tools/pages.py --force --only mode     skip the other sweeps
    tools/pages.py --force --only theme    built-in themes only

Without `--force` it says the cost and sends nothing.  Be clear that the restore at
the end is a *hope*: putting `logo {"value":3}` back is itself one of the guarded
writes whose effect nothing on the wire confirms, which is why the tool ends by
uploading a fresh frame and printing the conn fields so a person can look at the
glass and say what state it is actually in.
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from xigmalcd import render, sensors                           # noqa: E402
from xigmalcd.protocol import Link, ProtocolError, find_ports  # noqa: E402


def send(link, line, body, note=""):
    try:
        link.request(line, body)
    except ProtocolError as exc:
        # our own guard, not the panel: report it as the refusal it is rather
        # than ending the run with a traceback halfway through a sweep
        print(f"  --> {line:<24} {str(body):<24} [not sent: {exc}]", flush=True)
        return []
    reps = []
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        m = link.read(timeout=max(0.05, deadline - time.monotonic()))
        if m is None:
            break
        reps.append(m)
    codes = " ".join(m.code for m in reps if m.code) or "no reply"
    print(f"  --> {line:<24} {str(body):<24} [{codes}] {note}", flush=True)
    link.drain(timeout=0.05)
    return reps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device")
    ap.add_argument("--dwell", type=float, default=6.0)
    ap.add_argument("--only", choices=("mode", "logo", "theme"))
    ap.add_argument("--max", type=int, default=4, help="highest mode to try")
    ap.add_argument("--themes", type=int, default=9,
                    help="how many built-in themes to try (panel has 9: 0..8)")
    ap.add_argument("--force", action="store_true",
                    help="required: every sweep here writes a topic protocol.py "
                         "guards, and a wrong body clears the panel's theme "
                         "selection. Says what it costs, then sends")
    args = ap.parse_args()

    if not args.force:
        print("every sweep in this tool writes `mode`, `logo` or "
              "`presetThemeId`, and those are in protocol.BLOCKED_TOPICS for a "
              "reason measured on this panel: each one answers `1 200` and "
              "leaves the field at 2147483647, the panel's 'not set', which is "
              "how a unit ends up sitting white with the media channel still "
              "working. conn does not report which built-in theme is selected, "
              "so there is no undo to read back - the last write wins and "
              "tools/reset_panel.py --yes is the way out. Pass --force if you "
              "mean to watch it happen; the tool then re-sends mode/logo at the "
              "end, which is itself one of those guarded writes.")
        return 1

    port = args.device or (find_ports() or [("/dev/ttyACM0", "?")])[0][0]
    link = Link(port, allow_destructive=True)
    info = link.hello()
    start = {k: info.get(k) for k in ("mode", "logo", "osdState", "brightness")}
    print(f"device {start}\n")

    m = sensors.collect()
    for _ in range(2):
        link.state_all(m)
        time.sleep(0.05)
    link.drain()
    print(f"pushed metrics twice: cpu {m['cpu']['temperature']} C, "
          f"gpu {m.get('gpu', {}).get('temperature')} C, "
          f"mem {m['memory']['load']}%\n")

    if args.only in (None, "mode"):
        print("== POST mode 1 ==  (watch the panel)")
        for v in range(0, args.max + 1):
            send(link, "POST mode 1", {"value": v}, f"dwell {args.dwell:.0f} s")
            time.sleep(args.dwell)

    if args.only in (None, "logo"):
        print("\n== POST logo 1 ==")
        for v in range(0, 4):
            send(link, "POST logo 1", {"value": v}, f"dwell {args.dwell:.0f} s")
            time.sleep(args.dwell)

    if args.only in (None, "theme"):
        print(f"\n== POST presetThemeId 1 ==  (built-in themes, no upload needed; "
              f"index {args.themes} should be the first rejected one)")
        for v in range(0, args.themes + 1):
            send(link, "POST presetThemeId 1", {"index": v},
                 f"dwell {args.dwell:.0f} s")
            time.sleep(args.dwell)

    print("\n== back to what it was ==")
    # the theme is deliberately not restored: conn does not report which of the nine
    # built-in themes is showing, so there is no "previous value" to put back
    for line, body in (("POST mode 1", {"value": start.get("mode") or 0}),
                       ("POST logo 1", {"value": start.get("logo") or 3}),
                       ("POST brightness 1", {"value": 100})):
        try:
            send(link, line, body, "restoring")
        except (ProtocolError, OSError) as exc:
            print(f"  ! {line}: {exc}")

    # and put our own picture back, since that is what the live slot shows
    try:
        link.send_media(render.frame_name(), render.to_png(render.draw(m, "gauge")))
        print("  .. live frame restored")
    except (ProtocolError, OSError) as exc:
        print(f"  ! frame not restored: {exc}")

    info = link.hello()
    print("\nafter:", {k: info.get(k) for k in
                       ("mode", "logo", "osdState", "brightness", "space")})
    link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
