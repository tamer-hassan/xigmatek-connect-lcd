#!/usr/bin/env python3
"""state.py - read the panel's own state, no writes.

  tools/state.py            once
  tools/state.py --watch 5  every 5 s, to watch what a power cycle does

`mode` and `logo` are the two fields that describe what the panel is showing.
In every healthy Windows capture they read 0 and 3; 2147483647 (0x7fffffff) is
the panel's "not set" value, and both read that since the presetThemeId sweep.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import Link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--watch", type=float, default=0.0, help="seconds between reads")
    ap.add_argument("--n", type=int, default=0, help="stop after N reads")
    a = ap.parse_args()
    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.post("conn")
        k = 0
        while True:
            try:
                i = ln.device_info()
            except Exception as e:
                print(f"{time.strftime('%H:%M:%S')}  no reply: {e}", flush=True)
            else:
                print(f"{time.strftime('%H:%M:%S')}  "
                      f"mode={i.get('mode')} logo={i.get('logo')} "
                      f"osdState={i.get('osdState')} brightness={i.get('brightness')} "
                      f"timeout={i.get('timeout')} degree={i.get('degree')} "
                      f"space={i.get('space')}", flush=True)
                if not k and a.watch == 0:
                    print(json.dumps(i, indent=2, sort_keys=True), flush=True)
            k += 1
            if a.n and k >= a.n or a.watch == 0:
                return
            time.sleep(a.watch)


if __name__ == "__main__":
    main()
