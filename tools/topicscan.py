#!/usr/bin/env python3
"""topicscan.py - which wire topics exist on this firmware?

Silence means no handler.  400 means the topic exists and only the body was
wrong, which is how `rotate` (wants `degree`) and `presetThemeId` (wants a small
`index`) were found.

Be honest about what this costs: it asks by **writing** candidate topics, so the
four names here that are in `protocol.BLOCKED_TOPICS` (`mode`, `theme`,
`themeBackground`, `logoSet`) are declined before the first request and reported
as "never asked" rather than probed - they are the ones measured on this unit to
clear its theme selection, and a topic we never sent must not sit in the silent
column, which is where "no handler" is recorded.  That leaves 41 candidates, each
posted with `{"index":1}` / `{"value":1}` / `{"state":1}` / `{"degree":0}`, and a
topic that reads an index would take 1 as its first entry, so this is not a
zero-cost sweep: it is the tool to run on a panel you are willing to have poked,
with the eyes-on caveat that there is no readback to confirm what any of it did.
That is why it needs `--force`.

    tools/topicscan.py --force            scan the candidate topic names
    tools/topicscan.py --force --device PATH
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import BLOCKED_TOPICS, Link, ProtocolError

TOPICS = (
    "mode", "osd", "osdState", "display", "displayState", "screen", "screenState",
    "theme", "themeId", "themeSet", "lcdMode", "showMode", "playMode", "mediaPlay",
    "play", "media", "mediaIndex", "mediaShow", "mediaSet", "mediaAdd", "mediaList",
    "background", "backgroundSet", "themeBg", "themeBackground", "wallpaper",
    "image", "imageSet", "video", "videoSet", "logoMode", "logoSet", "bootLogo",
    "standby", "sleepMode", "screenOn", "displayOn", "powerScreen", "presetTheme",
    "presetThemeIndex", "realtime", "sysinfo", "infoDisplay", "degree", "brightness",
)
BODIES = ({"index": 1}, {"value": 1}, {"state": 1}, {"degree": 0})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("--force", action="store_true",
                    help="required: every candidate topic is asked about by "
                         "writing to it, and this panel has no readback, so a "
                         "scan can change what the glass shows and no reply "
                         "says that it did")
    a = ap.parse_args()

    if not a.force:
        print("this tool asks whether a topic exists by POSTing to it: 41 "
              "candidate display/media topic names x 4 bodies, every one a "
              "write.  The guarded names (mode, theme, themeBackground, "
              "logoSet) are refused either way, but the rest are writes too, "
              "and a topic that reads an index takes {\"index\":1} as its first "
              "entry.  Nothing on this panel can be read back to tell you what "
              "a scan did, so pass --force only with eyes on the glass.")
        return 1

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(60)
        alive, dead, declined = [], [], []
        for topic in TOPICS:
            if topic in BLOCKED_TOPICS or topic.startswith("waterBlockScreen"):
                # our own guard, and it has to be reported as that: the silent
                # column of this tool means "the firmware has no handler", and a
                # topic we refused to ask for would sit in it as a lie
                declined.append(topic)
                print(f"{topic:18} never asked: our own guard", flush=True)
                continue
            codes = []
            for body in BODIES:
                try:
                    ln.request(f"POST {topic} 1", body)
                except (ProtocolError, PermissionError) as exc:
                    print(f"  ! {topic} {json.dumps(body)}: {exc}", flush=True)
                    break
                time.sleep(0.2)
                got = [m.code for m in ln.harvest(timeout=0.45)
                       if m.code and m.headers.get("AckNumber") != "0"]
                codes.append(got[0] if got else "-")
                if got:
                    break
            line = f"{topic:18} {' '.join(codes)}"
            (alive if "-" not in codes else dead).append(topic)
            print(line, flush=True)
        print("\nexists:", " ".join(alive))
        print("silent:", " ".join(dead))
        if declined:
            print(f"never asked ({len(declined)}, our own guard): "
                  f"{' '.join(declined)}")
    return 0


if __name__ == "__main__":
    # a refusal to run has to be the exit code, or a script reads it as a scan
    # that happened
    sys.exit(main())
