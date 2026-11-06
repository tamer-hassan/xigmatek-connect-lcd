#!/usr/bin/env python3
"""theme.py - read the panel's theme fields; write them only with --force.

The panel renders its own themes and boot animations: that is why the stock
logo animation at POST is smooth while frames we upload appear only every 7-20
s.  The fields that describe that side of it are visible in `conn` state:

    mode, logo        the panel's own theme/animation selection
    osdState          1 while it shows the OSD layer
    space             free flash, i.e. whether it still holds its theme media

MEASURED on this unit, twice, and the reason this script does not write by
default: **we cannot set those fields.**  Twenty-three different bodies for
`POST logo` (value/index/degree/id/logo/num/number/code/theme/themeId/logoId/
presetThemeId/name/data/state/type/n/i/idx/v/val) all answer `200` and all leave
`logo` at 2147483647, the panel's "not set" - including `{"index":3}` written to
a panel that was reporting `logo=3` at that moment.  `mode` and `presetThemeId`
behave the same.  Writing any of the three clears the panel's theme and does not
select one; with `logo` at 2147483647 the screen is white from the first second
of POST, and the only known way back is ALPHA's own reset under Windows
(AIO Theme -> reset, the app's `waterBlockScreen().recovery(sn)`).

    tools/theme.py                     report the theme fields once
    tools/theme.py --watch 10          report every 10 s
    tools/theme.py --force logo 3      the destructive write, acknowledged

`--force` exists so a probe can be run again on purpose, with the cost stated
out loud.  tools/keyprobe.py is what proved the 23-body result.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import Link

KEYS = ("mode", "logo", "osdState", "brightness", "timeout", "space")
SENTINEL = 2147483647
# the values this unit has always reported while healthy, including right after
# ALPHA's own reset - they are what a write to these topics takes away
GOOD = {"logo": 3, "mode": 0}
WRITABLE = ("logo", "mode", "presetThemeId")


def info(ln, tries=3):
    for _ in range(tries):
        try:
            return ln.device_info()
        except Exception:
            ln.drain(0.4)
    return {}


def report(ln, label="panel"):
    st = info(ln)
    vals = {k: st.get(k) for k in KEYS}
    bad = [k for k in ("logo", "mode") if st.get(k) == SENTINEL]
    print(f"{label}: {vals}"
          + (f"   !! {bad} at 'not set': white screen at next cold POST; "
             "only ALPHA's AIO Theme reset puts them back" if bad else ""),
          flush=True)
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--watch", type=float, default=0.0,
                    help="report every N seconds instead of once")
    ap.add_argument("--force", nargs=2, metavar=("TOPIC", "VALUE"),
                    choices=None,
                    help=f"write one of {WRITABLE}; clears the panel's theme")
    a = ap.parse_args()

    if a.force:
        topic, value = a.force
        if topic not in WRITABLE:
            raise SystemExit(f"{topic}: not a theme field; this tool only "
                             f"touches {WRITABLE}")
        try:
            n = int(value)
        except ValueError:
            raise SystemExit("value must be an integer")
        if abs(n) > 1000:
            raise SystemExit(f"{n} is the panel's 'not set' territory; this "
                             "tool will not write it directly")
        # deliberate, acknowledged probe: Link guards these topics by default
        link_kwargs = {"allow_destructive": True} if _supports_guard() else {}
        with Link(a.device, timeout=3.0, **link_kwargs) as ln:
            ln.start_pump()
            ln.hello(60)
            report(ln, "before")
            print(f"  writing POST {topic} {{\"index\": {n}}} knowing it clears "
                  f"the panel's theme selection (healthy values: {GOOD})",
                  flush=True)
            ln.post(topic, {"index": n})
            code = "-"
            for m in ln.harvest(timeout=0.35):
                if m.code and m.headers.get("AckNumber") != "0":
                    code = m.code
                    break
            print(f"  answer {code}", flush=True)
            report(ln, "after")
    else:
        with Link(a.device, timeout=3.0) as ln:
            ln.start_pump()
            ln.hello(60)
            if a.watch:
                while True:
                    report(ln)
                    time.sleep(a.watch)
            else:
                report(ln)
                print(json.dumps(ln.device_info(), indent=2))


def _supports_guard():
    import inspect
    return "allow_destructive" in inspect.signature(Link.__init__).parameters


if __name__ == "__main__":
    main()
