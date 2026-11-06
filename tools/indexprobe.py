#!/usr/bin/env python3
"""indexprobe.py - measure the panel's render rate without watching it closely.

  tools/indexprobe.py --n 30 --cadence 1.004

Every frame carries a big frame number plus the wall clock, so a single glance
at the panel says which frame it is showing.  Two glances at known times give
both the panel's render rate and how far behind it is:

    rate = (n2 - n1) / (t2 - t1)      lag = (frames sent by time t) - n at time t

The script prints the two glance times before it starts, so you only have to
read a number off the screen twice.
"""
import argparse, os, sys, time
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors
from xigmalcd.protocol import Link, MEDIA_GAP

KEYS = ("mode", "logo", "osdState", "brightness", "space")


def frame(i, n, plain=False, overlay=False):
    """Big frame number, wall clock under it, both readable across a room.

    The **last** frame is bright magenta instead of white, so a screen looked at
    after the run answers two questions by itself: magenta means the panel took
    every frame, a white number means it froze and that number is where.

    `plain` skips the supersampled render: drawn straight at 480x480 on a flat
    background, which makes the PNG a couple of KB instead of thirty-some, so a
    rate test can tell "the panel ticks slowly" from "each frame costs it work".
    `overlay` leaves the background transparent, the way the vendor's own `.osd`
    files do, so the panel keeps its own layer behind the digits.
    """
    bg = render.OVERLAY if overlay else render.BLACK
    ink = (255, 0, 255, 255) if i == n else render.WHITE
    if plain:
        img = Image.new("RGBA", (render.W, render.H), bg)
        d = render.ImageDraw.Draw(img)
        d.text((240, 200), str(i), font=render.font(280, False), fill=ink,
               anchor="mm")
        d.text((240, 420), time.strftime("%H:%M:%S"), font=render.font(40, False),
               fill=render.CYAN, anchor="mm")
        return img
    img = Image.new("RGBA", (render.W * render.SS, render.H * render.SS), bg)
    render._text(img, (240, 190), str(i), render._fit(img, str(i), 400, 340), ink)
    render._text(img, (240, 330), f"of {n}", render.font(34), render.DIM)
    render._text(img, (240, 400), time.strftime("%H:%M:%S"), render.font(44), render.CYAN)
    return img.resize((render.W, render.H), Image.LANCZOS)


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
    ap.add_argument("--n", type=int, default=30, help="frames to send")
    ap.add_argument("--cadence", type=float, default=1.004)
    ap.add_argument("--settle", type=float, default=15.0, help="quiet seconds after")
    ap.add_argument("--plain", action="store_true",
                    help="flat 480x480 frames, a few KB each instead of ~30 KB")
    ap.add_argument("--encode", choices=("rgba", "pal8"), default="rgba",
                    help="colour type 6 (what the vendor sends) or 8-bit indexed")
    ap.add_argument("--overlay", action="store_true",
                    help="transparent background, so the panel's own layer "
                         "shows behind the digits (as the vendor's frames do)")
    ap.add_argument("--colors", type=int, default=256, help="palette size for pal8")
    a = ap.parse_args()

    t0 = time.time()
    glances = [t0 + 15, t0 + a.n * a.cadence + a.settle * 0.6]
    print("read the big number on the panel at these two moments:", flush=True)
    for j, g in enumerate(glances, 1):
        print(f"   glance {j}: {time.strftime('%H:%M:%S', time.localtime(g))}", flush=True)

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(60)
        print("start:", {k: info(ln).get(k) for k in KEYS}, flush=True)
        sent = []
        for i in range(1, a.n + 1):
            tick = time.time()
            img = frame(i, a.n, plain=a.plain, overlay=a.overlay)
            blob = (render.to_png(img, palette=True, colors=a.colors)
                    if a.encode == "pal8" else render.to_png(img, palette=False))
            ln.send_media(render.frame_name(), blob, gap=MEDIA_GAP, wait=False)
            sent.append((i, tick, len(blob)))
            ln.state_all(sensors.collect())
            for m in ln.harvest(timeout=0.1):
                if m.headers.get("AckNumber") == "0" and not m.code.startswith("2"):
                    print(f"     !! frame {i} refused {m.code}", flush=True)
            for j, g in enumerate(glances, 1):
                if tick <= g < tick + a.cadence:
                    print(f"   >>> glance {j} now ({time.strftime('%H:%M:%S')}): "
                          f"newest frame on the wire is {i}", flush=True)
            left = (tick + a.cadence) - time.time()
            if left > 0:
                time.sleep(left)
        print(f"last frame {a.n} sent at {time.strftime('%H:%M:%S')}, "
              f"{sent[0][2]} bytes each; quiet for {a.settle:.0f} s", flush=True)
        time.sleep(a.settle)
        end = time.time()
        print(f"quiet over at {time.strftime('%H:%M:%S')} (+{end-t0:.0f} s): "
              f"{ {k: info(ln).get(k) for k in KEYS} }", flush=True)


if __name__ == "__main__":
    main()
