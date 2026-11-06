#!/usr/bin/env python3
"""vendortest.py - drive the panel exactly the way ALPHA does, and ask why ours
looks slower on the glass.

ALPHA's post-reset session, read out of its own log (2026-11-5.log 19:46:27):

    recovery                      <- not done by this tool
    conn / power resume / timeout 60
    STATE all 1                   x2, one second apart, then nothing for a minute
    transport  1757491588831.mp4  659338 B   theme background, every session
    transport  <wallclock>.osd    24.3-25.0 KB, every 1013 ms, and the notice
                                  comes back ~25 ms later, before the next frame

This driver copies all of it: same handshake, same file-name format, RGBA true
colour frames of the vendor's size, one per second, and it **waits for each
frame's notice** before sending the next, like ALPHA does.  Every frame carries
a big frame number and the wall clock, so one glance at the panel says whether
the panel is keeping up (number == elapsed frames) or falling behind.

Two phases, so one run isolates the one thing our normal loop does that ALPHA's
never does - a `STATE all 1` metrics push every second:

    phase A  frames 1..N      no metrics traffic
    phase B  frames N+1..N+M  metrics push every frame (what xigmalcd does)

    python3 tools/vendortest.py                    30 + 30 frames
    python3 tools/vendortest.py --n 20 --b 0       phase A only
    python3 tools/vendortest.py --no-wait         fire-and-forget, our client's style
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors  # noqa: E402
from xigmalcd.protocol import Link, MEDIA_GAP  # noqa: E402
from tools.indexprobe import frame  # noqa: E402

KEYS = ("mode", "logo", "osdState", "brightness", "space")

VENDOR_MP4 = ("/media/windows-c/Users/Tamer/AppData/Roaming/alpha/media/background/"
              "1757491588831.mp4")


def vname(offset: int = 0) -> str:
    """ALPHA's own file-name format, wall clock shifted by `offset` seconds."""
    t = time.time() + offset
    return (time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(t))
            + f"-{int((t % 1) * 1000):03d}.osd")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--n", type=int, default=30, help="phase A frames (no metrics)")
    ap.add_argument("--b", type=int, default=30, help="phase B frames (metrics/s)")
    ap.add_argument("--cadence", type=float, default=1.013,
                    help="seconds per frame, ALPHA's own period")
    ap.add_argument("--settle", type=float, default=15.0)
    ap.add_argument("--no-wait", action="store_true",
                    help="do not wait for each notice (how xigmalcd sends)")
    ap.add_argument("--overlay", action="store_true",
                    help="transparent frames, so the panel's own layer shows "
                         "through - what the vendor's files are")
    ap.add_argument("--plain", action="store_true", help="cheap 480x480 render")
    ap.add_argument("--mp4", metavar="PATH", nargs="?", const="default",
                    help="upload ALPHA's theme background first, exactly as it "
                         "does at session start (default: the 1757491588831.mp4 "
                     "it uploaded today, 659338 B)")
    ap.add_argument("--frames", metavar="DIR",
                    help="replay PNGs from DIR byte for byte instead of "
                         "rendering our own (e.g. data/vendor_frames)")
    ap.add_argument("--name-a", type=int, default=0, metavar="SECONDS",
                    help="shift the wall clock inside phase A's file names by "
                         "this many seconds: negative = files dated in the past")
    ap.add_argument("--name-b", type=int, default=0, metavar="SECONDS",
                    help="same for phase B, so one run compares two clock offsets")
    a = ap.parse_args()

    total = a.n + a.b
    t0 = time.time()
    print(f"phase A: frames 1..{a.n}   "
          f"{time.strftime('%H:%M:%S', time.localtime(t0))} - "
          f"{time.strftime('%H:%M:%S', time.localtime(t0 + a.n * a.cadence))}")
    if a.b:
        print(f"phase B: frames {a.n + 1}..{total} (metrics every frame)   "
              f"{time.strftime('%H:%M:%S', time.localtime(t0 + a.n * a.cadence))} - "
              f"{time.strftime('%H:%M:%S', time.localtime(t0 + total * a.cadence))}")
    print("at any moment the number on the panel tells you where the panel is: "
          "if it equals the frames sent, it is keeping up\n", flush=True)

    lat: list[float] = []
    gaps: list[float] = []
    sizes: list[int] = []
    refused = 0
    last = None
    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        info = ln.hello(60)
        print("start:", {k: info.get(k) for k in KEYS},
              "version", info.get("version"), flush=True)
        ln.state_all(sensors.collect())          # ALPHA: two STATE at session start
        time.sleep(1.0)
        ln.state_all(sensors.collect())
        ln.drain(0.3)

        if a.mp4:                                # ALPHA: the theme background, first
            path = VENDOR_MP4 if a.mp4 == "default" else a.mp4
            blob = open(path, "rb").read()
            name = os.path.basename(path)
            before = (ln.device_info() or {}).get("space")
            t = time.time()
            res = ln.send_media(name, blob, gap=MEDIA_GAP, timeout=90.0)
            after = (ln.device_info() or {}).get("space")
            print(f"background {name} {len(blob)} B -> notice {res.get('notice')} "
                  f"in {time.time() - t:.1f} s, space {before} -> {after}",
                  flush=True)

        reel = []
        if a.frames:
            for f in sorted(os.listdir(a.frames)):
                if f.lower().endswith((".png", ".osd")):
                    reel.append(open(os.path.join(a.frames, f), "rb").read())
            print(f"replaying {len(reel)} stored frames byte for byte", flush=True)

        for i in range(1, total + 1):
            tick = time.time()
            phase = "A" if i <= a.n else "B"
            if reel:
                blob = reel[(i - 1) % len(reel)]
            else:
                img = frame(i, total, plain=a.plain, overlay=a.overlay)
                blob = render.to_png(img, palette=False)  # RGBA, like the vendor
            name = vname(a.name_a if i <= a.n else a.name_b)
            sent_at = time.time()
            res = ln.send_media(name, blob, gap=MEDIA_GAP, wait=not a.no_wait)
            if res.get("notice") is not None:
                lat.append(time.time() - sent_at)
                if not str(res["notice"]).startswith("2"):
                    refused += 1
                    print(f"     !! frame {i} refused: {res}", flush=True)
            elif not a.no_wait:
                refused += 1
                print(f"     !! frame {i}: no notice at all", flush=True)
            if a.b and phase == "B":
                ln.state_all(sensors.collect())
            for m in ln.harvest(timeout=0.05):
                if m.headers.get("AckNumber") == "0" and not m.code.startswith("2"):
                    refused += 1
                    print(f"     !! frame {i} refused late: {m.code}", flush=True)
            sizes.append(len(blob))
            if last is not None:
                gaps.append(tick - last)
            last = tick
            if i % 10 == 0 or i == total:
                print(f"  {i:3d} {phase} {len(blob):6d} B  name {name}  "
                      f"median verdict {statistics.median(lat)*1000:.0f} ms "
                      f"cadence {statistics.median(gaps or [0]):.3f} s", flush=True)
            left = (tick + a.cadence) - time.time()
            if left > 0:
                time.sleep(left)

        print(f"\nlast frame {total} sent at {time.strftime('%H:%M:%S')}; "
              f"quiet for {a.settle:.0f} s - whatever number is on the panel now "
              f"is where it stopped", flush=True)
        time.sleep(a.settle)
        end = time.time()
        info2 = ln.device_info() or {}
        print(f"quiet over {time.strftime('%H:%M:%S')} (+{end - t0:.0f} s): "
              f"{ {k: info2.get(k) for k in KEYS} }", flush=True)

    print(f"\nverdicts: {len(lat)} seen, median {statistics.median(lat)*1000:.0f} ms, "
          f"max {max(lat)*1000:.0f} ms; refused {refused}/{total}")
    print(f"wire cadence: median {statistics.median(gaps):.3f} s, "
          f"min {min(gaps):.3f} s, max {max(gaps):.3f} s")
    sizes.sort()
    print(f"frames: {sizes[0]} / {sizes[len(sizes) // 2]} / {sizes[-1]} B "
          f"(ALPHA's own are 24 351 - 25 042 B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
