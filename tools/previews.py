#!/usr/bin/env python3
"""Regenerate docs/preview-*.png so the README shows what the code actually draws.

The pictures are composited the way the panel composites them: the theme draws on a
transparent canvas (ALPHA's frames paint 4.6 percent of their pixels, PROTOCOL.md §9)
and the panel's stored background layer shows through.  The background here is a frame
lifted out of ALPHA's own theme MP4 with ffmpeg, so a preview is what the glass shows
rather than a drawing on a flat field.

Numbers are pinned rather than read from this box, so re-running does not churn the
images every time the CPU happens to be warm.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                           # noqa: E402
from xigmalcd import render, sensors                            # noqa: E402
from xigmalcd.main import CLIP_LUMA, DEFAULT_MP4, _scrim_for   # noqa: E402

THEMES = ("alpha", "gauge", "dual", "clock", "bars")
# pinned so re-running does not churn the images every time the CPU is warm;
# the CPU pair is what ALPHA's own captured frame reads
PINNED = {"cpu": {"temperature": 57.0, "load": 42.0},
          "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45}}
# the fan figures come from `fans`, which is a list and not a mapping, so it is
# pinned separately: 1957 RPM sits inside the span measured on this board's CPU
# tachometer (fan1 1360-2371 RPM tracking pwm1, PROTOCOL §8) but is not this
# box's live number, which is the point - re-running must not churn the gallery
# every time the CPU happens to be warm
PINNED_FANS = [{"onBoard": True, "type": "Fan", "name": "Fan CPU",
                "value": 1957}]


def background(path=None, frame=None):
    """One frame of the theme background video, or None if it is not available.

    The default is whatever the daemon ships with - `media/Theme_25.mp4`, the
    214 917-byte clip ALPHA pairs with the theme it has selected, 23 frames at
    24 fps in a ~1 s loop - so the gallery shows the same two-layer picture the
    panel gets.  A mid-loop frame is picked: representative, and not the seam,
    which for this clip is a real jump (2.50 against 1.51 typical motion).  The
    other vendored clips behave differently: `media/Theme_11.mp4` is 363 frames
    in a 15.1 s loop with a join smoother than its own motion (0.11 against
    2.54), `media/theme_48.mp4` is 217 frames in a 10.85 s loop with a join of
    4.50 against 0.60 and a mean luma of 227.3, and the old default
    `1757491588831.mp4` is a 5.05 s loop of 101 frames whose first 11 and last 5
    are pure black (PROTOCOL §9), so there a mid-loop frame was the only sane
    choice.  ffmpeg's `select` filter is not used: it silently yields nothing
    when the index runs past the end of the clip, which is easy to do on a
    23-frame file.
    """
    path = path or DEFAULT_MP4
    if not os.path.exists(path):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path,
                            os.path.join(tmp, "f%04d.png")],
                           check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            return None
        made = sorted(os.listdir(tmp))
        if not made:
            return None
        index = len(made) // 2 if frame is None else min(frame, len(made) - 1)
        return Image.open(os.path.join(tmp, made[index])).convert("RGBA")


def main():
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs")
    bg = background()
    print("background:", "vendor MP4 frame" if bg else
          "none (MP4 not mounted or no ffmpeg): drawing over a dark field")
    if bg is None:
        bg = Image.new("RGBA", (render.W, render.H), (9, 26, 36, 255))
    m = sensors.collect()
    for section, vals in PINNED.items():
        m.setdefault(section, {}).update(vals)
    m["fans"] = PINNED_FANS               # pinned, and labelled as pinned above
    # same rule the daemon uses, so the gallery cannot drift from the panel
    from types import SimpleNamespace
    scrim = _scrim_for(SimpleNamespace(scrim=None, mp4=DEFAULT_MP4, bg="clear"))
    print(f"scrim: {scrim} over {os.path.basename(DEFAULT_MP4)} "
          f"(mean luma {CLIP_LUMA.get(os.path.basename(DEFAULT_MP4))} of 255)")
    for theme in THEMES:
        name = os.path.join(out, f"preview-{theme}.png")
        Image.alpha_composite(bg, render.draw(m, theme, scrim=scrim)
                              .convert("RGBA")) \
            .convert("RGB").save(name)
        print("wrote", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
