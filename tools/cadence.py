#!/usr/bin/env python3
"""cadence.py - find the upload rate this panel actually renders at.

  tools/cadence.py --cadences 1,2.5,5,10 --phase 40

Sends our big-clock theme at a fixed cadence, with a `STATE all 1` metrics blob
in the same rhythm (the vendor's shape: one upload and one metrics push per
second), then goes quiet for `--settle` seconds so the panel can show whatever
it has.  Each phase prints the wall clock when it goes quiet: whatever time the
panel displays at that moment is its lag at that cadence.

The point is the comparison between phases.  Uploading faster than the panel
renders is not neutral - it is what the vendor app does, and the panel shows one
frame per 10-20 s doing that, so the on-screen clock is always stale.
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors
from xigmalcd.protocol import Link, MEDIA_GAP

KEYS = ("mode", "logo", "osdState", "brightness", "timeout", "space")


def info(ln):
    for _ in range(3):
        try:
            return ln.device_info()
        except Exception:
            ln.drain(0.4)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--cadences", default="1,2.5,5,10",
                    help="comma separated seconds-per-frame, one phase each")
    ap.add_argument("--phase", type=float, default=40.0, help="seconds per phase")
    ap.add_argument("--settle", type=float, default=10.0,
                    help="quiet seconds at the end of each phase")
    ap.add_argument("--theme", default="clock", help="render theme to use")
    ap.add_argument("--metrics", action="store_true", default=True,
                    help="push 'STATE all 1' in the same rhythm (vendor does)")
    a = ap.parse_args()

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(60)
        print("start:", {k: info(ln).get(k) for k in KEYS}, flush=True)
        for cadence in [float(c) for c in a.cadences.split(",")]:
            print(f"\n### PHASE cadence {cadence} s/frame "
                  f"({a.phase:.0f} s of frames) ###", flush=True)
            end = time.time() + a.phase
            n = 0
            while time.time() < end:
                tick = time.time()
                blob = render.to_png(render.draw(sensors.collect(), theme=a.theme),
                                     palette=False)
                ln.send_media(render.frame_name(), blob, gap=MEDIA_GAP, wait=False)
                if a.metrics:
                    ln.state_all(sensors.collect())
                n += 1
                for m in ln.harvest(timeout=0.15):
                    if m.headers.get("AckNumber") == "0" and not m.code.startswith("2"):
                        print(f"     !! refused {m.code}", flush=True)
                left = (tick + cadence) - time.time()
                if left > 0:
                    time.sleep(left)
            print(f"    sent {n} frames of {len(blob)} bytes; quiet now at "
                  f"{time.strftime('%H:%M:%S')} - read the panel's clock", flush=True)
            time.sleep(a.settle)
            ln.drain(0.5)
            print(f"    quiet over at {time.strftime('%H:%M:%S')}; state "
                  f"{ {k: info(ln).get(k) for k in KEYS} }", flush=True)
        print("\nend:", {k: info(ln).get(k) for k in KEYS}, flush=True)


if __name__ == "__main__":
    main()
