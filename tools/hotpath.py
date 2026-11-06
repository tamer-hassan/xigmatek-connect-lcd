#!/usr/bin/env python3
"""Timestamp the panel's replies when they arrive, not when we get round to reading.

Waiting for the file notice after every upload makes it land 1022 ms after
`transport` no matter the baud, chunk size or file size, while ALPHA's log shows
the same notice ~25 ms after `transport` with uploads 1005 ms apart.  The first
version of this tool only read for a couple of milliseconds between uploads, so
fast cadence made every notice look exactly one cadence late - an artifact of
the tool, not the panel.

So a thread reads the port non-stop and stamps every frame the instant it
arrives, while the main thread starts uploads on a metronome.  `--trace` prints
the whole arrival log, which separates the two timings that matter: the
`blockMaxSize` ack (13 ms for ALPHA) and the unlabelled file notice (25 ms).

Only `conn`/`power`/`timeout` and the media upload go on the wire: nothing
firmware, update or recovery related.

  ./tools/hotpath.py                       # cadence sweep
  ./tools/hotpath.py --trace               # per-frame arrival log
  ./tools/hotpath.py --cadence 1.05 -n 20
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import protocol, render, sensors  # noqa: E402
from xigmalcd.protocol import Link  # noqa: E402


class Reader(threading.Thread):
    """Read the port without stopping; stamp every frame on arrival."""

    def __init__(self, link: Link):
        super().__init__(daemon=True)
        self.link, self.q, self.alive = link, queue.Queue(), True

    def run(self):
        while self.alive:
            try:
                m = self.link.read(timeout=0.1)
            except Exception:
                break
            if m is not None:
                self.q.put((time.monotonic(), m))

    def stop(self):
        self.alive = False
        self.join(timeout=1.0)


def upload(link: Link, blob: bytes, name: str, gap: float, chunk: int) -> float:
    """Put one file on the wire; returns the time `transport` was written."""
    t0 = time.monotonic()
    link.post("transport", {"type": "media", "fileSize": len(blob),
                            "fileName": name})
    if gap:
        time.sleep(gap)
    link.send_raw(blob, chunk=chunk)
    link.post("transported", {"md5": "todo", "fileName": name})
    return t0


def phase(link: Link, blob: bytes, every: float, n: int, gap: float,
          chunk: int, trace=False, tail=4.0):
    """n uploads `every` seconds apart.  Returns (notice latencies, log)."""
    rd = Reader(link)
    rd.start()
    sent, lat, log, bad = [], [], [], [0]
    try:
        start = time.monotonic()
        for i in range(n):
            name = render.frame_name()
            sent.append([name, upload(link, blob, name, gap, chunk)])
            if trace:
                log.append((time.monotonic(), f">> {name} "
                            f"{len(blob)} B sent"))
            wait = start + (i + 1) * every - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _harvest(rd, sent, lat, log, [bad], trace, start)
        limit = time.monotonic() + tail
        while sent and time.monotonic() < limit:
            time.sleep(0.05)
            _harvest(rd, sent, lat, log, [bad], trace, start)
    finally:
        rd.stop()
    return lat, len(sent), bad[0], log


def _harvest(rd, sent, lat, log, bad, trace, start):
    """Match every arrived frame to the oldest file still unacknowledged."""
    while True:
        try:
            t, m = rd.q.get_nowait()
        except queue.Empty:
            return
        body = (m.body or b"").decode(errors="replace")
        ack = m.headers.get("AckNumber")
        if m.code.startswith("4"):
            bad[0] += 1
        if trace:
            log.append((t, f"<< {m.code:3} ack={ack:>5} {body[:46]}"))
        if ack == "0" and sent:
            name, t0 = sent.pop(0)
            lat.append(t - t0)
            if trace:
                log.append((t, f"   notice for {name}: "
                               f"{(t - t0) * 1e3:.0f} ms"))


def main() -> int:
    ap = argparse.ArgumentParser(prog="hotpath",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("-n", "--files", type=int, default=12, help="uploads per phase")
    ap.add_argument("--cadence", default="1.5,1.2,1.05,0.9,0.7,0.5,0.3",
                    help="seconds between uploads, comma separated")
    ap.add_argument("--gap", type=float, default=protocol.MEDIA_GAP)
    ap.add_argument("--chunk", type=int, default=protocol.MEDIA_CHUNK)
    ap.add_argument("--trace", action="store_true",
                    help="print every frame arrival for the first cadence")
    args = ap.parse_args()

    blob = render.to_png(render.draw(sensors.collect(), theme="clock"),
                         palette=False)
    cad = [float(x) for x in args.cadence.split(",")]
    print(f"frame {len(blob)} B, {args.files} uploads per phase, "
          f"gap={args.gap} chunk={args.chunk}", flush=True)

    with Link(args.device, timeout=3.0) as link:
        link.hello(0)
        for i, every in enumerate(cad):
            lat, gone, refused, log = phase(link, blob, every, args.files,
                                            args.gap, args.chunk,
                                            trace=(args.trace and i == 0))
            if args.trace and i == 0:
                for t, line in log:
                    print(f"  {(t - log[0][0]) * 1e3:7.0f}ms  {line}", flush=True)
                print(flush=True)
            if lat:
                s = sorted(lat)
                print(f"{every:5.2f}s  n={len(lat):3}  p50={s[len(s)//2]*1e3:6.0f}ms "
                      f"min={s[0]*1e3:6.0f}ms max={s[-1]*1e3:6.0f}ms  "
                      f"refused={refused}  no-notice={gone}", flush=True)
            else:
                print(f"{every:5.2f}s  no notices  refused={refused}", flush=True)
            time.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
