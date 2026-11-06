#!/usr/bin/env python3
"""Which files does the panel answer fast, and which does it sit on for a second?

The same upload shape - `transport`, 50 ms, raw bytes, `transported` - comes back
with the file notice 40-160 ms later in some runs and a near-exact 1.00 s later in
others, and the one thing that lines up so far is the file itself: the panel's own
24-25 KB payloads (13/25/26 ms in its log) and our 30 KB RGBA PNGs are quick, our
13 KB indexed PNGs and 5 KB flat ones are not.

So upload real alternatives through one session, in rotating rounds, and time the
notice when it arrives (see hotpath.py for why that matters).  Among the shapes is
the vendor's own PNG bytes, lifted out of the IRP capture by `vendor_capture.py`
and byte-for-byte what the panel accepted from ALPHA.

  ./tools/fileshape.py                      # all shapes, two rounds
  ./tools/fileshape.py --osd /tmp/opencode/vendor_osd

Nothing firmware, update or recovery related: `conn`/`power`/`timeout` and media.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                  # noqa: E402
from hotpath import phase                              # noqa: E402
from xigmalcd import protocol, render, sensors         # noqa: E402
from xigmalcd.protocol import Link                     # noqa: E402


def shapes(osd_dir: str) -> dict:
    """Candidate files, keyed by a label that says what each one is."""
    m = sensors.collect()
    img = render.draw(m, theme="clock")
    out = {
        "ours RGBA 8bpc": render.to_png(img, palette=False),
        "ours indexed": render.to_png(img, palette=True),
    }
    flat = Image.new("RGBA", (render.W, render.H), (12, 14, 16, 255))
    out["flat RGBA"] = render.to_png(flat, palette=False)
    for path in sorted(glob.glob(os.path.join(osd_dir, "*.osd")))[:2]:
        out[f"ALPHA {os.path.basename(path)[:14]}"] = open(path, "rb").read()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="fileshape",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("--osd", default="/tmp/opencode/vendor_osd",
                    help="directory of real .osd payloads from vendor_capture")
    ap.add_argument("-n", "--files", type=int, default=6, help="uploads per shape")
    ap.add_argument("--cadence", type=float, default=1.05)
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args()

    files = shapes(args.osd)
    for label, blob in files.items():
        print(f"  {len(blob):6} B  {label}")
    print(flush=True)

    with Link(args.device, timeout=3.0) as link:
        link.hello(0)
        for rnd in range(args.rounds):
            print(f"-- round {rnd + 1}", flush=True)
            for label, blob in files.items():
                lat, gone, refused, _ = phase(link, blob, args.cadence,
                                              args.files, protocol.MEDIA_GAP,
                                              protocol.MEDIA_CHUNK)
                if lat:
                    s = sorted(lat)
                    print(f"   {len(blob):6} B {label:26} p50={s[len(s)//2]*1e3:6.0f}ms "
                          f"min={s[0]*1e3:5.0f} max={s[-1]*1e3:6.0f}  "
                          f"refused={refused} no-notice={gone}", flush=True)
                else:
                    print(f"   {len(blob):6} B {label:26} no notices "
                          f"refused={refused}", flush=True)
                time.sleep(1.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
