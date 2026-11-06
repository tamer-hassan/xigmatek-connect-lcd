#!/usr/bin/env python3
"""restore.py - put a picture source back on the panel the way ALPHA does it.

  tools/restore.py --media FILE [--name NAME] [--stream 30]

ALPHA shows a 480x480 video that lives in the panel as the theme background and
paints a 1 Hz RGBA `.osd` PNG over it.  A panel with nothing stored has no
source to show: free space goes up, `logo` reads 0x7fffffff instead of a small
media id, and the screen sits white.  This uploads a background the same way
its log does - announce, wait for the reply, 1000-byte
writes, then `transported` - and reports the two counters that say whether the
panel took it: `space` should drop by the file size and `logo` should stop being
0x7fffffff.

Nothing here touches `recovery`, `config` or `type:"firmware"`.
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xigmalcd import render, sensors
from xigmalcd.protocol import Link, MEDIA_GAP

KEYS = ("mode", "logo", "osdState", "brightness", "timeout", "space", "degree")


def state(ln):
    i = ln.device_info()
    return {k: i.get(k) for k in KEYS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--media", required=True, help="file to store on the panel")
    ap.add_argument("--name", help="name to store it as (default: basename)")
    ap.add_argument("--stream", type=float, default=30.0,
                    help="seconds of 1 Hz .osd frames afterwards (0 to skip)")
    ap.add_argument("--cadence", type=float, default=1.004)
    ap.add_argument("--gap", type=float, default=MEDIA_GAP)
    ap.add_argument("--timeout", type=int, default=60)
    a = ap.parse_args()

    blob = open(a.media, "rb").read()
    name = a.name or os.path.basename(a.media)
    frames = sorted(os.listdir("data/vendor_frames"))

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(a.timeout)
        before = state(ln)
        print("before:", before, flush=True)

        t0 = time.time()
        ln.send_media(name, blob, gap=a.gap, wait=False)
        notice = None
        while notice is None and time.time() - t0 < 15:
            for m in ln.harvest(timeout=0.5):
                if m.headers.get("AckNumber") == "0":
                    notice = m
                    break
        print(f"stored {name} ({len(blob)} B) in {time.time()-t0:.2f} s -> "
              f"notice {notice.code if notice else 'none'}", flush=True)
        time.sleep(1.0)
        after = state(ln)
        print("after: ", after, flush=True)
        print(f"space {before['space']} -> {after['space']} "
              f"({after['space']-before['space']}), logo {before['logo']} -> {after['logo']}",
              flush=True)

        if a.stream and frames:
            print(f"streaming {a.stream:.0f} s of .osd frames at "
                  f"{a.cadence:.3f} s - watch the panel", flush=True)
            t_end = time.time() + a.stream
            k = 0
            while time.time() < t_end:
                tick = time.time()
                fn = frames[k % len(frames)]
                ln.send_media(render.frame_name(),
                              open(os.path.join("data/vendor_frames", fn), "rb").read(),
                              gap=a.gap, wait=False)
                k += 1
                for m in ln.harvest(timeout=0.2):
                    if m.headers.get("AckNumber") == "0" and not m.code.startswith("2"):
                        print(f"     !! frame refused {m.code}", flush=True)
                left = (tick + a.cadence) - time.time()
                if left > 0:
                    time.sleep(left)
            print("end:  ", state(ln), flush=True)


if __name__ == "__main__":
    main()
