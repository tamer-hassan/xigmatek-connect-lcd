#!/usr/bin/env python3
"""replay.py - feed the panel pictures exactly the way ALPHA's capture did.

  tools/replay.py --extract CAPTURE          pull the frames out of a Windows
                                             capture into data/vendor_frames/
  tools/replay.py --source vendor            replay those real 480x480 RGBA PNGs
  tools/replay.py --source ours              our renderer, same cadence
  tools/replay.py --cadence 1.004 --seconds 45

The vendor source removes every variable: the same bytes ALPHA sent, the same
1000-byte writes, the same 1.004 s cadence, the same `.osd` names, `timeout 60`.
If the panel shows those and not ours, the difference is our frame, not the
session.
"""
import argparse, glob, os, sys, time
from collections import deque
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors
from xigmalcd.protocol import Link, MEDIA_GAP, MEDIA_CHUNK

FRAME_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "data", "vendor_frames")


def extract(capture):
    """pull the picture bytes out of a Windows capture, in order"""
    from capdump import records, stream, uploads
    got = uploads(stream(records(capture), "IRP_MJ_WRITE", "DOWN"))
    os.makedirs(FRAME_DIR, exist_ok=True)
    for ann, blob in got:
        open(os.path.join(FRAME_DIR, ann["fileName"] + ".png"), "wb").write(blob)
    print(f"{len(got)} frames -> {FRAME_DIR}")


def ours():
    return render.to_png(render.draw(sensors.collect(), theme="clock"), palette=False)


def state(ln):
    return {k: ln.device_info().get(k) for k in ("mode", "logo", "osdState",
                                                 "brightness", "timeout", "space")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--source", choices=("vendor", "ours"), default="vendor")
    ap.add_argument("--extract", metavar="CAPTURE",
                    help="extract frames from a Windows capture and exit")
    ap.add_argument("--seconds", type=float, default=45, help="how long the run lasts")
    ap.add_argument("--cadence", type=float, default=1.004,
                    help="seconds per frame; ALPHA uses 1.004")
    ap.add_argument("--gap", type=float, default=MEDIA_GAP)
    ap.add_argument("--chunk", type=int, default=MEDIA_CHUNK)
    ap.add_argument("--timeout", type=int, default=60,
                    help="keepalive to set at start; ALPHA always sends 60")
    a = ap.parse_args()

    if a.extract:
        extract(a.extract)
        return

    frames = sorted(glob.glob(os.path.join(FRAME_DIR, "*.png")))
    if a.source == "vendor" and not frames:
        sys.exit(f"no vendor frames in {FRAME_DIR}; run --extract on a capture first")

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        ln.hello(a.timeout)
        print("panel at start:", state(ln), flush=True)
        ln.state_all(sensors.collect())
        pending, sent, ok = deque(), 0, 0
        lat = []                                # verdict latency per accepted file
        t_end = time.time() + a.seconds
        k = 0
        while time.time() < t_end:
            t0 = time.time()
            blob = open(frames[k % len(frames)], "rb").read() if a.source == "vendor" else ours()
            name = render.frame_name()
            ln.send_media(name, blob, gap=a.gap, chunk=a.chunk, wait=False)
            pending.append([name, time.time(), len(blob)])
            sent += 1
            k += 1
            for m in ln.harvest(timeout=0.2):
                if m.headers.get("AckNumber") != "0":
                    continue                    # labelled ack: no verdict in it
                if pending:
                    old = pending.popleft()
                    lat.append((time.time() - old[1], old[2]))
                if m.code.startswith("2"):
                    ok += 1
                else:
                    print(f"     !! refused {m.code}", flush=True)
            while pending and time.time() - pending[0][1] > 6:
                print(f"     !! no verdict for {pending.popleft()[0]}", flush=True)
            left = (t0 + a.cadence) - time.time()
            if left > 0:
                time.sleep(left)
        print(f"sent {sent} frames, {ok} accepted, {len(pending)} unanswered", flush=True)
        if lat:
            secs = sorted(v[0] for v in lat)
            half = len(secs) // 2
            early = [v[0] for v in lat[:max(1, len(lat) // 4)]]
            late = [v[0] for v in lat[-max(1, len(lat) // 4):]]
            print(f"verdict latency: min {secs[0]*1000:.0f} ms, median "
                  f"{secs[half]*1000:.0f} ms, max {secs[-1]*1000:.0f} ms; "
                  f"first quarter {sum(early)/len(early)*1000:.0f} ms mean, "
                  f"last quarter {sum(late)/len(late)*1000:.0f} ms mean "
                  f"(growing = the panel is falling behind)", flush=True)
            print(f"frame size: {lat[0][1]} bytes each", flush=True)
        print(f"wall clock now {time.strftime('%H:%M:%S')} - whatever the panel "
              f"shows is its lag", flush=True)
        time.sleep(3)
        ln.drain(1.0)
        print("panel at end:  ", state(ln))


if __name__ == "__main__":
    main()
