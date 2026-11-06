#!/usr/bin/env python3
"""Make `install/xigmaui.png`, the launcher icon for the Qt window.

Not artwork: it is the picture the glass actually shows, drawn by the same
`render.draw()` the daemon uploads from, over a mid-loop frame of the background
clip this project ships with, composited the way the panel composites its two
layers (PROTOCOL.md §9).  If the icon ever looks wrong, the display code is
wrong - which is the useful property.

Metric numbers are pinned, like tools/previews.py pins them, so re-running does
not churn the file every time the CPU happens to be warm.  The clock is not
pinned: it is the clock.

    python3 tools/makeicon.py [-o PATH] [-s SIZE]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                            # noqa: E402
from xigmalcd import render                                      # noqa: E402
from xigmalcd.main import DEFAULT_MP4                            # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "install", "xigmaui.png")
# what ALPHA's own captured frame reads, so the icon matches docs/preview-*.png
PINNED = {"cpu": {"temperature": 57.0, "load": 42.0},
          "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default=OUT)
    ap.add_argument("-s", "--size", type=int, default=256,
                    help="edge length in px (the drawing itself is 480x480)")
    a = ap.parse_args(argv)

    from xigmaui import clips as clipdb          # ffmpeg, PIL: no Qt, no port
    back = clipdb.frame(DEFAULT_MP4)
    if back is None:
        print(f"no frame out of {DEFAULT_MP4}: is ffmpeg installed and the clip "
              f"there?", file=sys.stderr)
        return 1

    # scrim 0: the shipped clip measures a mean luma of 18.7 of 255, well under
    # the point where white-on-white starts (main.BRIGHT_LUMA), so the plate the
    # daemon would add for a bright clip is not needed here
    osd = render.draw(PINNED, "alpha", bg=render.OVERLAY, clock_size=30,
                      fan=False, scrim=0)
    img = back.resize(osd.size, Image.Resampling.LANCZOS).copy()
    img.alpha_composite(osd)
    img = img.convert("RGBA").resize((a.size, a.size), Image.Resampling.LANCZOS)
    img.save(a.out, "PNG")
    print(f"{a.out}  {img.size[0]}x{img.size[1]}  {os.path.getsize(a.out)} bytes"
          f"   (alpha theme over a mid-loop frame of {os.path.basename(DEFAULT_MP4)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
