#!/usr/bin/env python3
"""probe.py - is the body key `index`?  Codes are the oracle: 200 landed,
400 means the topic exists and the body did not parse, silence means the
firmware has no such topic.

`presetThemeId {"index":3}` was 200 while 19 other shapes were 400, so the
panel does validate bodies and `index` is one key it knows.  This walks the
other display topics with the same guess, and reports.

Understand the shape of the question first: the only way to ask "does this topic
exist" on this firmware is to **write** to it.  Two of the eight topics are in
`protocol.BLOCKED_TOPICS` (`logo`, `presetThemeId`) and are reported as "not
sent" rather than written to, and `waterBlockScreenId` is refused by the same
guard.  The rest are still writes with no readback - `realtimeDisplay` is
measured to act as a display-layer toggle, and `osdState` and `sysinfoDisplay`
change what the panel draws - so this tool does not run without `--force`, and
`--force` means "I accept that a sweep changes panel state and nothing on the
wire tells me what it changed".

    tools/probe.py --force               walk the unguarded display topics
    tools/probe.py --force --device PATH another port

No firmware/update/recovery topic is touched at any point, and nothing that
deletes media is sent.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import (BLOCKED_TOPICS, Link,
                               ProtocolError)

TOPICS = ("logo", "presetThemeId", "rotate", "osdState", "sysinfoDisplay",
          "displayInSleep", "realtimeDisplay", "waterBlockScreenId")
BODIES = ({"index": 3}, {"index": 1}, {"index": 0}, {"degree": 0},
          {"state": 1}, {"state": 0}, {"type": 1}, {"name": "1"},
          {"value": 1}, {"i": 1}, {"idx": 1})


def info(ln):
    """`conn` state, ignoring whatever the last probe left on the wire."""
    for _ in range(3):
        try:
            return ln.device_info()
        except Exception:
            ln.drain(0.4)
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("--force", action="store_true",
                    help="required: this asks whether a topic exists by "
                         "writing to it, and the panel has no readback, so a "
                         "sweep can change what the glass shows and no reply "
                         "will say that it did")
    a = ap.parse_args()

    if not a.force:
        print("this tool asks whether a topic exists by writing to it.  The "
              "guarded topics (logo, presetThemeId, waterBlockScreen*) are "
              "skipped either way, but the rest are writes too: realtimeDisplay "
              "is measured to toggle a display layer, osdState and "
              "sysinfoDisplay change what the panel draws, and there is no "
              "readback to undo or even confirm any of it.  Pass --force if you "
              "mean to walk them, with eyes on the glass.")
        return 1

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(60)
        i0 = info(ln)
        print("start:", json.dumps({k: i0.get(k) for k in
              ("mode", "logo", "osdState", "brightness", "space")}), flush=True)
        for topic in TOPICS:
            if topic in BLOCKED_TOPICS or topic.startswith("waterBlockScreen"):
                # protocol.py refuses these unless the caller asks for a
                # destructive link, and this tool does not even with --force:
                # `logo`, `presetThemeId` and friends are panel-state writes
                # with no readback, so the honest result is "we did not ask".
                print(f"{topic:18} not sent: our own guard "
                      f"(protocol.BLOCKED_TOPICS)", flush=True)
                continue
            got = []
            for body in BODIES:
                try:
                    ln.request(f"POST {topic} 1", body)
                except (ProtocolError, PermissionError) as exc:
                    print(f"  ! {topic} {json.dumps(body)}: {exc}", flush=True)
                    break
                time.sleep(0.25)
                codes = [m.code for m in ln.harvest(timeout=0.5)
                         if m.code and m.headers.get("AckNumber") != "0"]
                code = codes[0] if codes else "-"
                if code in ("200", "400"):
                    got.append(f"{json.dumps(body)}={code}")
                if code == "200":
                    break                     # first shape the panel took
            i = info(ln)
            print(f"{topic:18} {'  '.join(got) or 'silent (no such topic?)':<52} "
                  f"logo={i.get('logo'):>10} osd={i.get('osdState')} "
                  f"mode={i.get('mode')} br={i.get('brightness')}", flush=True)
        i = info(ln)
        print("end:  ", json.dumps({k: i.get(k) for k in
              ("mode", "logo", "osdState", "brightness", "space")}), flush=True)
    return 0


if __name__ == "__main__":
    # a refusal to run has to be the exit code, or a script reads it as a sweep
    # that happened
    sys.exit(main())
