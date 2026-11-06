#!/usr/bin/env python3
"""Measure when an accepted file actually reaches the screen.

Every upload gets a `1 200` file notice, and 456 of them landed in 600 s, but the
display only changes every 20-30 s.  So "accepted" is not "shown", and the two
have to be measured separately.  This tool draws a big frame number and the push
clock on every frame, so the answer can be read straight off the panel:

  phase push    N frames, `every` seconds apart   -> ids 1..N climbing
  phase quiet   nothing at all on the wire         -> does the number keep
                                                     climbing by itself?
  phase single  one more frame                     -> how fast does it land?
  phase quiet   again

If the number keeps going up during the quiet phase, the panel is working through
a queue of accepted files; if it freezes and only moves on the next push, the
display service samples the media slot on its own slow timer.

Nothing here touches firmware or update topics.
"""
from __future__ import annotations

import argparse
import glob as _glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import ImageDraw, ImageFont  # noqa: E402
from xigmalcd import protocol, render, sensors  # noqa: E402
from xigmalcd.protocol import Link, ProtocolError  # noqa: E402

SS = 2                     # render's supersample factor; themes draw on a 2x canvas


def bigfont(px: int):
    path = next(iter(_glob.iglob("/usr/share/fonts/**/DejaVuSans-Bold.ttf",
                                 recursive=True)), None)
    return ImageFont.truetype(path, px) if path else ImageFont.load_default(px)


def stamp(img, n: int, t: float):
    """Big frame id + the push clock, drawn on the finished 480x480 frame so it
    is unmistakable at a glance across the room."""
    d = ImageDraw.Draw(img)
    d.rectangle((20, 40, 460, 340), fill=(0, 0, 0, 255))
    d.text((240, 130), f"#{n}", font=bigfont(150), fill=(255, 255, 255, 255),
           anchor="mm")
    d.text((240, 240), time.strftime("%H:%M:%S", time.localtime(t)),
           font=bigfont(56), fill=(120, 220, 255, 255), anchor="mm")
    d.text((240, 300), "this frame was pushed at", font=bigfont(22),
           fill=(170, 170, 170, 255), anchor="mm")
    return img


def push(link, n, m):
    img = render.draw(m, theme="clock")
    stamp(img, n, time.time())
    blob = render.to_png(img.convert("RGBA"), palette=False)
    t0 = time.monotonic()
    try:
        res = link.send_media(render.frame_name(), blob,
                              gap=protocol.MEDIA_GAP, chunk=protocol.MEDIA_CHUNK)
        notice = res.get("notice")
    except (ProtocolError, OSError) as exc:
        notice = f"ERR {exc}"
    print(f"  push #{n:<3} {time.strftime('%H:%M:%S')} {len(blob):6} B "
          f"notice={notice} ({time.monotonic()-t0:.2f}s)", flush=True)
    return notice


def main() -> int:
    ap = argparse.ArgumentParser(prog="frame_lag", description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("-n", "--frames", type=int, default=40,
                    help="frames in the first push phase")
    ap.add_argument("--every", type=float, default=1.2,
                    help="seconds between pushes in the first phase")
    ap.add_argument("--quiet", type=int, default=150,
                    help="seconds of total silence after the first phase")
    ap.add_argument("--quiet2", type=int, default=60,
                    help="seconds of silence after the single frame")
    args = ap.parse_args()

    with Link(args.device, timeout=5.0) as link:
        info = link.hello(0)          # timeout 0: do not blank during the quiet phases
        print("panel:", {k: info.get(k) for k in
                         ("space", "brightness", "mode", "logo", "osdState", "timeout")},
              flush=True)
        n = 0
        bad = 0
        print(f"\n== phase push: {args.frames} frames, {args.every}s apart "
              f"({time.strftime('%H:%M:%S')})", flush=True)
        start = time.monotonic()
        while n < args.frames:
            m = sensors.collect()
            if push(link, n + 1, m) != "200":
                bad += 1
            n += 1
            wait = start + n * args.every - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        last_push = time.strftime("%H:%M:%S")

        print(f"\n== phase quiet: nothing on the wire for {args.quiet} s "
              f"(last push {last_push}). Watch the number on the panel.", flush=True)
        t_end = time.monotonic() + args.quiet
        while time.monotonic() < t_end:
            time.sleep(5)
        print(f"== quiet over at {time.strftime('%H:%M:%S')}", flush=True)

        print(f"\n== phase single: one frame at {time.strftime('%H:%M:%S')}", flush=True)
        m = sensors.collect()
        push(link, n + 1, m)
        n += 1

        print(f"\n== phase quiet: {args.quiet2} s of silence again", flush=True)
        time.sleep(args.quiet2)
        print(f"== done at {time.strftime('%H:%M:%S')}: pushed up to #{n}, "
              f"{bad} refused", flush=True)
    print("\nNow tell me what the panel showed: did the number keep climbing during "
          "the quiet phase, what was the highest number you saw, and how long did "
          "the single frame take to appear?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
