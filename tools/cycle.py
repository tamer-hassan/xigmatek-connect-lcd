#!/usr/bin/env python3
"""Time every step of one upload, and sweep what we control.

ALPHA's own log says a file costs the panel ~25 ms: `transport`, its ack
(`blockMaxSize`) 13 ms later, the file notice 25 ms later, `transported` 26 ms
after the announcement.  The same shape from Linux takes 1.10 s, which is also
the best candidate for the laggy screen.  So time the steps separately:

  post    the `transport` frame write
  raw     the raw file bytes (per chunk write this usually blocks)
  sent    announcement .. `transported` written
  notice  announcement .. the panel's unlabelled file notice

Sweeps: line coding (baud), the gap before the first file byte, the write
chunk, the file size, pushing the `STATE all` metrics blob first, and waiting
for the notice vs pipelining.  Only `conn`/`power`/`timeout` and the media
upload are ever sent; nothing firmware or update related.

  ./tools/cycle.py                      # the sweeps
  ./tools/cycle.py --baud 9600 --files 8
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import protocol, render, sensors  # noqa: E402
from xigmalcd.protocol import Link, ProtocolError  # noqa: E402

STATS = {"network": {"upload": 1, "download": 2}, "memory": {"total": 1, "used": 1,
         "load": 1, "temperature": 0, "speed": 1}, "cpu": {"load": 1,
         "temperature": 50, "speedAverage": 4000, "power": 60, "voltage": 1.2,
         "usage": 10}, "gpu": {"load": 0, "temperature": 30, "fan": 0, "speed": 0,
         "power": 0, "voltage": 0, "memoryUsage": 0, "dedicated": 0,
         "dedicatedTotal": 0}, "disk": {"total": 999, "used": 200, "load": 1,
         "activity": 0, "temperature": 30, "readSpeed": 0, "writeSpeed": 0},
         "fans": [], "motherboard": {"temperature": 35}}


def sample(kind: str) -> bytes:
    if kind == "small":
        from PIL import Image
        img = Image.new("RGBA", (render.W, render.H), (12, 14, 16, 255))
    elif kind == "vendor":                      # flat-ish RGBA, ~24 KB like ALPHA
        from PIL import Image
        img = Image.new("RGBA", (render.W, render.H))
        img.putdata([((x * 7 + y * 3) & 0xFF, (x * 5) & 0xFF, (y * 11) & 0xFF, 255)
                     for y in range(render.H) for x in range(render.W)])
    else:
        img = render.draw(sensors.collect(), theme="clock")
    return render.to_png(img, palette=(kind == "gauge"))


def cycle(link: Link, blob: bytes, gap: float, chunk: int, wait=True,
          state_all=False, timeout=8.0):
    name = render.frame_name()
    t = {}
    link.drain(0.05)
    if state_all:
        link.request("STATE all 1", STATS)
    t0 = time.monotonic()
    link.post("transport", {"type": "media", "fileSize": len(blob),
                            "fileName": name})
    t["post"] = time.monotonic() - t0
    if gap:
        time.sleep(gap)
    t1 = time.monotonic()
    link.send_raw(blob, chunk=chunk)
    t["raw"] = time.monotonic() - t1
    link.post("transported", {"md5": "todo", "fileName": name})
    t["sent"] = time.monotonic() - t0
    if not wait:
        return t
    notice, limit = None, time.monotonic() + timeout
    while time.monotonic() < limit:
        m = link.read(timeout=max(0.05, limit - time.monotonic()))
        if m is None:
            break
        if m.code.startswith("4"):
            raise ProtocolError(f"refused {m.code} {(m.body or b'')[:36]!r}")
        if m.headers.get("AckNumber") == "0":
            notice = m.code
            break
    t["notice"], t["code"] = time.monotonic() - t0, notice
    return t


def main() -> int:
    ap = argparse.ArgumentParser(prog="cycle", description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("--files", type=int, default=3)
    ap.add_argument("--baud", type=int, default=0, help="only this line coding")
    ap.add_argument("--size", default="vendor", help="small|vendor|gauge")
    args = ap.parse_args()

    blob = sample(args.size)
    print(f"frame {len(blob)} B, {args.files} uploads per setting\n", flush=True)
    combos = [("baud", v, dict(gap=0.02, chunk=1000))
              for v in ([args.baud] if args.baud else [9600, 115200, 921600])]
    combos += [("gap", v, dict(gap=v, chunk=1000))
               for v in (0.005, 0.01, 0.05, 0.2)]
    combos += [("chunk", v, dict(gap=0.02, chunk=v))
               for v in (64, 256, 1000, 4096, 16384)]
    combos += [("pipeline", 0, dict(gap=0.02, chunk=1000, wait=False)),
               ("stateall", 0, dict(gap=0.02, chunk=1000, state_all=True))]

    for what, val, kw in combos:
        link = Link(args.device, baud=(val if what == "baud" else 115200),
                    timeout=3.0)
        try:
            link.hello(0)
            out = []
            for _ in range(args.files):
                try:
                    t = cycle(link, blob, **kw)
                    out.append(f"post{t['post']*1e3:5.0f} raw{t['raw']*1e3:6.0f} "
                               f"sent{t['sent']*1e3:6.0f} "
                               f"notice{(t.get('notice') or 0)*1e3:6.0f} {t.get('code','-')}")
                except ProtocolError as exc:
                    out.append(f"ERR {exc}")
            print(f"{what:9} {str(val):>7}  " + "\n           ".join(out), flush=True)
        finally:
            link.close()
        time.sleep(0.4)
    return 0


if __name__ == "__main__":
    sys.exit(main())
