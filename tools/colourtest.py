#!/usr/bin/env python3
"""colourtest.py - can this panel display one frame per second at all?

  tools/colourtest.py --n 30 --cadence 1.0 --cycles 3

Sends flat solid-colour frames - a few hundred bytes each, no glyphs, nothing
to decode - in a fixed colour order, and ends on bright magenta.  Watching the
screen answers three things at once:

  * how many changes you see: the panel's display rate,
  * whether it settles on magenta: whether it shows the newest frame or works
    through the ones it has already taken,
  * whether the changes are evenly spaced (its own tick) or bunched.

If colours flash about once a second, the panel is fast and the cost is in our
frames.  If they crawl, the panel's tick is the limit and no amount of encoder
work will raise it - the client has to stop sending faster than it can show.
"""
import argparse, sys, time
from PIL import Image, ImageDraw
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__))))
from xigmalcd import render, sensors
from xigmalcd.protocol import Link, MEDIA_GAP

ORDER = [(220, 30, 30), (30, 200, 40), (40, 80, 230), (230, 210, 40),
         (220, 60, 200), (40, 210, 220), (240, 130, 30), (20, 20, 20)]
LAST = (255, 0, 255)          # bright magenta: the frame it should end on


def flat(rgb):
    return Image.new("RGBA", (render.W, render.H), rgb + (255,))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--cadence", type=float, default=1.0)
    ap.add_argument("--settle", type=float, default=12.0)
    a = ap.parse_args()

    seq = [ORDER[i % len(ORDER)] for i in range(a.n - 1)] + [LAST]
    sizes = []
    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(60)
        print(f"colour order: " + " ".join(
            f"{i+1}:{'mag' if c == LAST else 'rgb'}" for i, c in enumerate(seq[:8]))
            + " ...", flush=True)
        print(f"sending {a.n} flat frames at {a.cadence} s, then {a.settle:.0f} s "
              f"quiet. The last frame is MAGENTA.", flush=True)
        for i, rgb in enumerate(seq, 1):
            tick = time.time()
            blob = render.to_png(flat(rgb), palette=False)
            sizes.append(len(blob))
            ln.send_media(render.frame_name(), blob, gap=MEDIA_GAP, wait=False)
            ln.state_all(sensors.collect())
            for m in ln.harvest(timeout=0.1):
                if m.headers.get("AckNumber") == "0" and not m.code.startswith("2"):
                    print(f"     !! frame {i} refused {m.code}", flush=True)
            left = (tick + a.cadence) - time.time()
            if left > 0:
                time.sleep(left)
        print(f"all {a.n} sent, {sizes[0]} bytes each, last at "
              f"{time.strftime('%H:%M:%S')}; quiet for {a.settle:.0f} s", flush=True)
        time.sleep(a.settle)
        print(f"quiet over at {time.strftime('%H:%M:%S')} - what colour is it?",
              flush=True)


if __name__ == "__main__":
    main()
