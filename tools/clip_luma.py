#!/usr/bin/env python3
"""clip_luma.py - the mean luma of a clip over **every** frame it holds.

`xigmalcd.main.CLIP_LUMA` decides whether the drawing gets a dark plate behind it, and
the dictionary's comment says the figures in it were measured by decoding the file whole.
A single frame does not give the same answer: `Theme_25.mp4` measures 18.7 over its 23
frames and 17.9 at the mid-loop point, and a clip that opens on a still head (the
vendor's `theme_47.mp4` does: 17 frames of play button) reads a different number at
frame 0 than across its loop.  So this is the door that produces those numbers, and the
page that quotes one names this command instead of keeping a figure by hand.

For each file it prints: bytes, frames decoded, mean luma over all of them, the mean of
the darkest and brightest frame, and what `main._scrim_for` would decide for a session
pointed at that clip - the last being the point of the whole exercise: `BRIGHT_LUMA` is
where white-on-white starts, and a clip nobody measured never reaches the rule.

Reads only: no upload, no panel, no writes.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xigmalcd import main  # noqa: E402


def measure(path: str) -> tuple:
    """(frames decoded, mean luma over all of them, darkest frame, brightest frame).

    `format=gray` makes the stride width x height bytes with no channel arithmetic to
    get wrong, and the frame count comes from what actually decoded rather than from the
    container's `nb_frames`, which is a claim the file may not honour.
    """
    dims = _geometry(path)
    if dims is None:
        return (0, 0.0, 0.0, 0.0)
    stride = dims[0] * dims[1]
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", path, "-map", "0:v:0", "-vf", "format=gray",
         "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    per_frame: list = []
    total = 0.0
    out = proc.stdout
    while True:
        chunk = out.read(stride)
        if not chunk:
            break
        if len(chunk) < stride:
            break                    # a truncated tail: not a frame, not counted
        frame = sum(chunk) / stride
        per_frame.append(frame)
        total += frame
    proc.wait(timeout=1800)
    if not per_frame:
        return (0, 0.0, 0.0, 0.0)
    return (len(per_frame), total / len(per_frame), min(per_frame), max(per_frame))


def _geometry(path: str):
    got = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height,nb_frames",
                          "-of", "csv=p=0", path], capture_output=True, text=True,
                         timeout=120)
    bits = got.stdout.strip().splitlines()
    if not bits:
        return None
    f = bits[0].split(",")
    try:
        return (int(f[0]), int(f[1]))
    except (IndexError, ValueError):
        return None


def main_run(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", action="append", default=[],
                    help="directory of mp4 files to measure (repeatable)")
    ap.add_argument("--only", default="", help="measure one file")
    a = ap.parse_args(argv)
    files = []
    if a.only:
        files = [a.only]
    for d in ([] if a.only else (a.dir or ["media"])):
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in sorted(os.listdir(d))
                      if f.lower().endswith(".mp4")]
    print(f"  clip                     bytes      frames   mean   darkest  brightest"
          f"   scrim")
    known = 0
    for path in files:
        n, mean, lo, hi = measure(path)
        base = os.path.basename(path)
        pinned = main.CLIP_LUMA.get(base)
        decision = main._scrim_for(__import__("argparse").Namespace(
            scrim=None, mp4=path, bg="clear"))
        known += pinned is not None
        print(f"  {base:24s} {os.path.getsize(path):9,d} {n:8d}  {mean:6.1f}   "
              f"{lo:6.1f}   {hi:6.1f}   {decision:4d}"
              + (f"   (CLIP_LUMA says {pinned})" if pinned is not None
                 else "   (not in CLIP_LUMA)"))
    print(f"\n  {len(files)} files measured, {known} of them named in "
          f"main.CLIP_LUMA (the dictionary decides the plate; an unmeasured clip gets "
          f"scrim 0 by default, which is the honest answer only while the clip is dark)")
    print(f"  BRIGHT_LUMA {main.BRIGHT_LUMA}, SCRIM_ON_BRIGHT {main.SCRIM_ON_BRIGHT}")
    return 0


if __name__ == "__main__":
    sys.exit(main_run())
