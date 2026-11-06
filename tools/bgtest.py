#!/usr/bin/env python3
"""bgtest.py - does the panel play a stored MP4 as its own background layer?

The vendor app stores 480x480 MP4 files once (`themeCreator().transportBGFile`)
and then uploads a 480x480 PNG every second.  The panel's boot animation is
smooth while uploaded PNGs only appear every 7-20 s, so the model the vendor's
traffic suggests is two layers:

    stored MP4   played by the panel itself, at its own (smooth) rate
    uploaded PNG composited on top, on the OSD's slow tick

which would explain the user-visible symptom exactly.  This tool tests it on the
wire with the vendor's own files:

    tools/bgtest.py --file /media/windows-c/.../media/background/x.mp4 --frames 40

It uploads the MP4 as `transport {"type":"media"}` - the same request shape as a
picture, only bigger - prints `space` before and after so the flash ledger is
visible, then uploads our clock at the vendor's 1 Hz cadence on top of it.
Nothing but media traffic: no theme, no logo, no recovery, no firmware.
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors
from xigmalcd.protocol import Link, MEDIA_CHUNK, MEDIA_GAP

KEYS = ("logo", "mode", "osdState", "brightness", "space")


def info(ln, tries=3):
    for _ in range(tries):
        try:
            return ln.device_info()
        except Exception:
            ln.drain(0.4)
    return {}


def report(ln, label):
    print(f"{label}: { {k: info(ln).get(k) for k in KEYS} }", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--file", required=True, help="480x480 MP4 to store")
    ap.add_argument("--frames", type=float, default=40.0,
                    help="seconds of 1 Hz clock frames to send afterwards")
    ap.add_argument("--theme", default="clock")
    a = ap.parse_args()

    path = a.file
    blob = open(path, "rb").read()
    name = os.path.basename(path)
    print(f"{name}: {len(blob)} bytes, {len(blob)//MEDIA_CHUNK + 1} chunks",
          flush=True)

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(60)
        report(ln, "before")
        t0 = time.time()
        try:
            out = ln.send_media(name, blob, gap=MEDIA_GAP, chunk=MEDIA_CHUNK,
                                timeout=40.0)
            print(f"stored in {time.time()-t0:.1f} s: "
                  f"{ {k: v for k, v in (out or {}).items() if k != 'notice'} }",
                  flush=True)
        except Exception as e:
            print(f"store failed after {time.time()-t0:.1f} s: {e}", flush=True)
        report(ln, "after store")
        print(f"watch the panel: if the MP4 is a background layer it should be "
              f"playing now ({time.strftime('%H:%M:%S')})", flush=True)
        time.sleep(6)

        end = time.time() + a.frames
        n = 0
        while time.time() < end:
            tick = time.time()
            png = render.to_png(render.draw(sensors.collect(), theme=a.theme),
                                palette=False)
            ln.send_media(render.frame_name(), png, gap=MEDIA_GAP,
                          chunk=MEDIA_CHUNK, wait=False)
            n += 1
            for m in ln.harvest(timeout=0.1):
                if m.headers.get("AckNumber") == "0" and not m.code.startswith("2"):
                    print(f"     !! frame {n} refused {m.code}", flush=True)
            left = (tick + 1.004) - time.time()
            if left > 0:
                time.sleep(left)
        print(f"sent {n} clock frames of ~{len(png)} bytes over the stored "
              f"background, {time.strftime('%H:%M:%S')}", flush=True)
        time.sleep(8)
        report(ln, "after frames")


if __name__ == "__main__":
    main()
