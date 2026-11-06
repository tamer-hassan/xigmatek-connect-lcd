#!/usr/bin/env python3
"""Probe the command set the Windows captures never showed.

Every candidate below came out of the constant pool of ALPHA's own main process
(resources/app.asar -> out/main/index.jsc, V8 bytecode whose string literals are
readable with `strings`), where the vendor's log lines name them: "realtimeDisplay;
resp body:", "recovery set: true; resp body:", "transporting resp body:",
"sync background;", "sync config to device", "sync mcu theme id:".

Nothing destructive is sent: no firmware/update topics, no mediaDelete.

    tools/commands.py                    probe the read-only candidates
    tools/commands.py -v                 dump every frame both ways
    tools/commands.py --send 'GET osd 1' send one arbitrary request and reply
    tools/commands.py --mutations        also try the reversible SET-ish ones
                                         (brightness, degree) and put them back
"""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from xigmalcd import sensors                                   # noqa: E402
from xigmalcd.protocol import (BLOCKED_TOPICS, Link, ProtocolError,  # noqa: E402
                               find_ports)

# (request line, json body or None) - read-only / harmless
READS = [
    ("GET conn 1", None),
    ("GET config 1", None),
    ("GET deviceConfig 1", None),
    ("GET osd 1", None),
    ("GET mode 1", None),
    ("GET logo 1", None),
    ("GET brightness 1", None),
    ("GET degree 1", None),
    ("GET timeout 1", None),
    ("GET realtimeDisplay 1", None),
    ("GET sysinfoDisplay 1", None),
    ("GET displayInSleep 1", None),
    ("GET fanLCDSet 1", None),
    ("GET presetThemeId 1", None),
    ("GET recovery 1", None),
    ("GET power 1", None),
    ("GET media 1", None),
    ("GET mediaList 1", None),
    ("GET file 1", None),
    ("GET status 1", None),
    ("GET background 1", None),
    ("GET firmware 1", None),
    ("GET transport 1", None),
    ("POST conn 1", None),
    ("POST status 1", None),
    ("POST realtimeDisplay 1", None),
    ("POST realtimeDisplay 1", {"value": 1}),
    ("STATE all 1", None),
    ("STATE status 1", None),
    ("STATE realtimeDisplay 1", None),
    # no SET/PUT with guessed bodies: a wrong shape could blank the OSD page
]

# reversible writes, run only with --mutations; each is undone right after
MUTATIONS = [
    ("POST brightness 1", {"value": 20}, ("POST brightness 1", {"value": 100})),
    ("POST degree 1", {"value": 1}, ("POST degree 1", {"value": 0})),
    ("POST timeout 1", {"value": 30}, ("POST timeout 1", {"value": 60})),
]


def guarded(line: str) -> bool:
    """Would `Link` refuse this request line?  Same rule as protocol.request().

    A guarded read is not a silent panel: it is us declining to ask, and this
    tool's only output is the difference between those two.
    """
    parts = line.split()
    topic = parts[1] if len(parts) > 1 else ""
    return topic in BLOCKED_TOPICS or topic.startswith("waterBlockScreen")


def ask(link, line, body, wait=1.2):
    """Send one request, print whatever the panel says back."""
    try:
        link.request(line, body)
    except (ProtocolError, PermissionError) as exc:
        # `Link`'s own guard raises PermissionError, and this tool's whole value
        # is the distinction between "the panel did not answer" and "we never
        # asked": reporting a guard refusal as `(no reply)` would put a topic in
        # the "not in the firmware" pile on the strength of our own policy
        print(f"  !! not sent: {exc}")
        return None
    got = []
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        m = link.read(timeout=max(0.05, deadline - time.monotonic()))
        if m is None:
            break
        got.append(m)
        txt = m.body.decode("utf-8", "replace") if m.body else ""
        print(f"  <-- {m.line:<8} {m.headers}  {txt[:400]}")
    if not got:
        print("  <-- (no reply)")
    return got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("--send", action="append", default=[],
                    help="send this exact request line (with --body)")
    ap.add_argument("--body", help="json body for --send")
    ap.add_argument("--mutations", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    port = args.device or (find_ports() or [("/dev/ttyACM0", "?")])[0][0]
    link = Link(port, args.baud, verbose=args.verbose)
    info = link.hello()
    print(f"device: sn={info.get('sn')} fw={info.get('version', {}).get('firmware')} "
          f"space={info.get('space')} brightness={info.get('brightness')} "
          f"mode={info.get('mode')} logo={info.get('logo')} osdState={info.get('osdState')}")

    if args.send:
        for line in args.send:
            body = json.loads(args.body) if args.body else None
            print(f"\n--> {line}  {args.body or ''}")
            ask(link, line, body, wait=3.0)
        link.close()
        return 0

    silent, not_sent, asked = [], [], 0
    for line, body in READS:
        if guarded(line):
            not_sent.append(line)
            continue
        asked += 1
        extra = f"  {json.dumps(body)}" if body else ""
        print(f"\n--> {line}{extra}")
        if not ask(link, line, body):
            silent.append(line)
        link.drain()

    if args.mutations:
        print("\n== reversible writes ==")
        for line, body, undo in MUTATIONS:
            if guarded(line):
                not_sent.append(line)
                continue
            print(f"\n--> {line}  {json.dumps(body)}")
            ask(link, line, body, wait=2.0)
            print(f"--> undo {undo[0]}  {json.dumps(undo[1])}")
            ask(link, undo[0], undo[1], wait=2.0)
            link.drain()

    print(f"\n{len(silent)} of {asked} requests got no answer at all: {silent}")
    if not_sent:
        print(f"  never asked, our own guard ({len(not_sent)}): {not_sent}. They "
              f"are not evidence about the firmware: `Link` refuses those topics "
              f"because writing them clears this panel's theme, and a read that "
              f"was never sent says nothing either way")
    link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
