#!/usr/bin/env python3
"""writebench.py - how long one upload spends on the wire, and what moves it.

ALPHA's own log says its file notice comes back 13-26 ms after `transport`,
which means its 24 KB file was fully received in that time (~1 MB/s).  From
Linux the same notice takes 150-190 ms, so something about how we put bytes on
this CDC-ACM port costs 6x.  This measures the two intervals separately:

    bytes   the `transport` frame sent -> last file byte handed to the kernel
    notice  the `transport` frame sent -> the panel's verdict back

Variants: write chunk size, baud rate, the 20-50 ms pause the media writer
needs before the first byte, and the kernel's `low_latency` tty flag.

    python3 tools/writebench.py
    python3 tools/writebench.py --file data/vendor_frames/<one>.osd.png
"""
from __future__ import annotations

import argparse
import fcntl
import os
import statistics
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors  # noqa: E402
from xigmalcd.protocol import Link  # noqa: E402

TIOCSSERIAL = 0x40385401
TIOCGSERIAL = 0x40385402
ASYNC_LOW_LATENCY = 0x2000


def low_latency(fd: int, on: bool) -> bool:
    """Ask the kernel to push tty bytes without waiting for a buffer to fill."""
    try:
        raw = bytearray(fcntl.ioctl(fd, TIOCGSERIAL, b"\0" * 68))
        off = 40                                    # `flags` sits 10 ints in
        flags, = struct.unpack_from("<i", raw, off)
        flags = flags | ASYNC_LOW_LATENCY if on else flags & ~ASYNC_LOW_LATENCY
        struct.pack_into("<i", raw, off, flags)
        fcntl.ioctl(fd, TIOCSSERIAL, bytes(raw))
        return True
    except OSError:
        return False


def one(ln: Link, blob: bytes, gap: float, chunk: int):
    """Upload once.  Returns (bytes_s, notice_s), both since `transport`.

    A refusal is a result like any other: it is recorded and reported, because
    which settings the panel accepts is exactly what is being measured.
    """
    name = render.frame_name()
    ln.drain(0.1)
    t0 = time.monotonic()
    ln.post("transport", {"type": "media", "fileSize": len(blob),
                          "fileName": name})
    if gap:
        time.sleep(gap)
    ln.send_raw(blob, chunk=chunk)
    t_bytes = time.monotonic() - t0
    ln.post("transported", {"md5": "todo", "fileName": name})
    try:
        notice, _ = ln.read_notice(name, timeout=10.0)
    except Exception as exc:                       # noqa: BLE001
        return t_bytes, time.monotonic() - t0, f"refused {exc}"[:60]
    return t_bytes, (time.monotonic() - t0), notice


def report(tag, runs):
    tb = [r[0] for r in runs]
    tn = [r[1] for r in runs]
    bad = sum(1 for r in runs if not str(r[2]).startswith("2"))
    print(f"  {tag:<38} bytes {statistics.median(tb)*1000:6.0f} ms   "
          f"notice {statistics.median(tn)*1000:6.0f} ms"
          + (f"   !! {bad} refused" if bad else ""), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--n", type=int, default=5, help="samples per variant")
    ap.add_argument("--file", help="upload this file instead of a rendered frame")
    ap.add_argument("--chunks", default="1000,4096,65536")
    ap.add_argument("--gaps", default="0.05,0.02",
                    help="comma-separated pauses between the transport frame and "
                         "the first byte, e.g. --gaps 0.01,0.005,0.002")
    a = ap.parse_args()

    if a.file:
        blob = open(a.file, "rb").read()
    else:
        blob = render.to_png(render.draw(sensors.collect(), "clock"),
                             palette=False)
    print(f"file {len(blob)} B, {a.n} samples per variant\n")

    with Link(a.device, timeout=5.0) as ln:
        ln.start_pump()
        ln.hello(60)
        for chunk in [int(c) for c in a.chunks.split(",")]:
            for gap in [float(g) for g in a.gaps.split(",")]:
                report(f"chunk {chunk:<6} gap {gap:<6} baud 115200",
                       [one(ln, blob, gap, chunk) for _ in range(a.n)])
            time.sleep(1.0)
        for baud in (9600, 921600):
            ln.ser.baudrate = baud
            report(f"chunk 1000   gap 0.05  baud {baud}",
                   [one(ln, blob, 0.05, 1000) for _ in range(a.n)])
        ln.ser.baudrate = 115200
        if low_latency(ln.ser.fileno(), True):
            for chunk in (1000, 65536):
                report(f"low_latency chunk {chunk:<6} gap 0.05",
                       [one(ln, blob, 0.05, chunk) for _ in range(a.n)])
        else:
            print("  low_latency: refused here (needs CAP_SYS_ADMIN)")
        st = ln.device_info() or {}
        print("\nafter:", {k: st.get(k) for k in ("osdState", "space", "logo")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
