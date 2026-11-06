#!/usr/bin/env python3
"""Ask the panel about every command the vendor app actually sends.

The topic list and the bodies below are not guesses: they are read out of
ALPHA's own code (out/main/index.jsc, decompiled).  ALPHA registers exactly
these topics in its request factory:

    conn  all  waterBlockScreen  waterBlockScreenId  brightness  rotate
    recovery  sysinfoDisplay  displayInSleep  fanLCDSet  mediaDelete  config
    power  realtimeDisplay  presetThemeId  timeout  transport  transported

For each one the panel gives one of three answers, which is the whole oracle:

    1 200 + body      accepted, and the payload means something
    1 200 bare        accepted
    1 4xx             the topic exists, the body was wrong
    no answer         the firmware does not know that topic at all

Settings are read first and put back at the end, and a picture is uploaded
afterwards so the panel ends up showing something.

    tools/vendor_cmds.py                 safe probes + save/restore
    tools/vendor_cmds.py --list          print the table, do not touch the port
    tools/vendor_cmds.py --only bright   only topics matching 'bright'
    tools/vendor_cmds.py --shapes        also probe topics ALPHA never calls

Two things this tool no longer does.  `presetThemeId` used to be in its SAFE
list, and `presetThemeId {"index":0}` is what left a panel white at POST: those
topics answer 200 and then leave logo/mode at the panel's "not set" value, and
only the vendor app's AIO Theme reset (Windows) puts them back - see BLOCKED
below.  And `recovery` is never sent either: it is that same vendor reset, it
re-enumerates the USB device, and it is something to do in Windows by hand.
Nothing here flashes anything: `transport` with a .zip file is the firmware
update path and is never used.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from xigmalcd import render, sensors                         # noqa: E402
from xigmalcd.protocol import Link, ProtocolError, find_ports  # noqa: E402

# ------------------------------------------------------------------ commands --
# (topic, body, what the vendor code does with it)
SAFE = [
    ("power", {}, "ALPHA's 'awake' call: wake the panel"),
    ("power", {"event": "resume"}, "sent on resume from suspend"),
    ("power", {"event": "lock-screen"}, "sent when the PC locks"),
    ("timeout", {"value": 0}, "never sleep"),
    ("timeout", {"value": 60}, "sleep after 60 s of no traffic"),
    ("brightness", {"value": 100}, "panel brightness"),
    ("rotate", {"degree": 0}, "picture rotation"),
    ("realtimeDisplay", {}, "ALPHA only sends this to RTOS panels"),
]

# ALPHA registers presetThemeId, logo and mode, and they answer 200 - but they
# are not settings we can write.  Measured on this unit: every body tried (23
# shapes for logo, index/value/id/themeId/...) leaves the field at 2147483647,
# the panel's "not set", including writing {"index":3} to a panel reporting
# logo=3.  `presetThemeId {"index":0}` from this file's old SAFE list is what
# left a unit white at POST: with logo not set there is no boot animation, and
# only the vendor app's AIO Theme reset puts it back.  Link refuses these
# topics unless built with allow_destructive=True; keep it that way.
BLOCKED = ("presetThemeId", "logo", "mode", "logoSet", "theme",
           "themeBackground")

# topics ALPHA registers but never calls, so their bodies are unknown: the
# empty body is only there to find out whether the panel knows the topic at all
SHAPES = [
    ("waterBlockScreen", {}, "screen layout for the AIO's own LCD block"),
    ("waterBlockScreenId", {}, "id of that block"),
    ("sysinfoDisplay", {}, "let the panel draw the system info itself"),
    ("displayInSleep", {}, "what to show while the PC sleeps"),
    ("fanLCDSet", {}, "fan curve pushed to the panel"),
    # `config` is registered by ALPHA but its body is unknown and it is the bulk
    # device config, so probing it with a guessed body is how a device gets
    # reshaped.  Left untried on purpose.
]

# `recovery` is the vendor app's reset (ALPHA -> AIO Theme -> reset, which logs
# `recovery set: true`).  It is the only known cure for a panel whose logo/mode
# sit at 2147483647, and it re-enumerates the USB device and drops the stored
# picture, so it is documented here and never sent by our tooling: run it in
# Windows when needed.  `Link` refuses the topic as well.
NEVER_SENT = ("recovery", "config", "firmware", "update", "upgrade", "ota")

RESTORE = {                                  # topic -> body that puts info back
    "brightness": lambda i: {"value": int(i.get("brightness", 100))},
    "rotate": lambda i: {"degree": int(i.get("degree", 0))},
    "timeout": lambda i: {"value": int(i.get("timeout", 60))},
}


def ask(link: Link, topic: str, body, note: str, quiet=False) -> str:
    """Send one request and report how the panel answered."""
    seq = link.request(f"POST {topic} 1", body)
    m = link.reply(timeout=1.5)
    if m is None:
        verdict = "no answer        (topic unknown)"
    elif m.code.startswith("4"):
        verdict = f"{m.code}            (topic exists, body wrong)"
    elif m.body:
        verdict = f"{m.code} {m.body[:56].decode('latin-1')}"
    else:
        verdict = f"{m.code} bare      (accepted)"
    if not quiet:
        payload = json.dumps(body, separators=(",", ":")) if body is not None else "-"
        print(f"POST {topic:19s} {payload:26s} {verdict}")
        if note:
            print(f"{'':28s} ^ {note}")
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("--list", action="store_true", help="just show the table")
    ap.add_argument("--only", help="only topics matching this text")
    ap.add_argument("--shapes", action="store_true",
                    help="also probe topics ALPHA registers but never calls")
    ap.add_argument("--no-restore", action="store_true",
                    help="leave the panel as the last probe left it")
    ap.add_argument("-v", "--verbose", action="store_true", help="frame logging")
    args = ap.parse_args()

    probes = list(SAFE) + (SHAPES if args.shapes else [])
    bad = [p for p in probes if p[0] in BLOCKED or p[0] in NEVER_SENT]
    if bad:
        print(f"refusing to send: {bad}", file=sys.stderr)
        probes = [p for p in probes if p not in bad]
    if args.only:
        probes = [p for p in probes if args.only in p[0]]
    if args.list:
        for topic, body, note in probes:
            print(f"POST {topic:19s} "
                  f"{json.dumps(body, separators=(',', ':')):26s} {note}")
        return 0

    port = args.device
    if not port:
        ports = [(p, lab) for p, lab in find_ports() if "Xigmatek" in lab or "ACM" in p]
        if not ports:
            print("no CDC-ACM port found (is /dev/xigmatek-lcd there?)")
            return 1
        port = ports[0][0]
    print(f"port {port}")

    with Link(port, args.baud, timeout=2.0, verbose=args.verbose) as link:
        try:
            info = link.device_info()
        except ProtocolError as exc:
            print(f"handshake failed: {exc}")
            return 1
        print("panel says:", json.dumps(info, separators=(",", ":")))
        print()

        for topic, body, note in probes:
            try:
                ask(link, topic, body, note)
            except ProtocolError as exc:
                print(f"POST {topic:19s} ! {exc}")
            time.sleep(0.2)
        link.drain()

        if not args.no_restore:
            print("\nputting the settings back:")
            for topic, make in RESTORE.items():
                body = make(info)
                ask(link, topic, body, "restored", quiet=True)
            # and leave a picture on it, since brightness/rotate moved around
            metrics = sensors.collect()
            png = render.to_png(render.draw(metrics, "gauge"))
            try:
                res = link.send_media(render.frame_name(), png)
                print(f"re-uploaded a frame -> {res}")
            except ProtocolError as exc:
                print(f"re-upload failed: {exc}")
        link.drain()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
