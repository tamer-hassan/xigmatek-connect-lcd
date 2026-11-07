#!/usr/bin/env python3
"""preview_gif.py - the preview pane's animated composite, written out as a GIF.

One code path with the window: `clips.ClipPlayer` decodes the background in order,
`render.draw` draws this program's layer over it (theme, clock size, scrim and the
chosen text colour included), and what comes out is what `xigmaui` shows in its
preview pane while `playing` is ticked - encoded as an animated GIF.

Why GIF, measured rather than remembered: GitHub's markdown turns
`![alt](clip.mp4)` into `<img src="...clip.mp4">`, which no browser plays, so an
MP4 in a README is a link and not a preview.  `--mp4` still writes one, for the
click-through and the release asset.

Two things this had to learn the hard way, both by measuring:

* **Sample, never repeat.**  The first version decoded the clip at its own 20-24 fps
  and told ffmpeg `-r 8` at the end, which is the same frame three times running.
  GIF is built on inter-frame diffs, so the repetition is pure loss: 7,205,675 bytes
  for what samples-at-8-fps writes in 1,510,157 - 4.8x for the identical animation.
  So the sampling happens here, in the same stream the window reads.
* **The palette budget is the cheapest knob left.**  ffmpeg's GIF encoder already
  offsets and diffs frames (`gifflags=offsetting+transdiff` are on by default) and
  `gifsicle` is not installed on this bench and needs a password to add, so the
  measured options are scale, rate, length and colour count.  Halving the palette to
  128 colours costs about 23 % of the bytes and leaves the text colour within
  1/255 per channel; 64 colours is where ink starts to move at 320 px.

Nothing here touches a device: it is host-side drawing over a decoded file, and
PROTOCOL.md §11 still means the panel is never asked what it is showing.  The GIF is
documentation, not evidence about the wire - its palette is ffmpeg's, not the
256-colour PNG the upload path uses.  The tool measures that cost on the file it
wrote and prints it, so the README can quote a number instead of a hope.
"""
from __future__ import annotations

import argparse
import inspect
import io
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                    # noqa: E402

from xigmalcd import render, sensors
from xigmalcd.main import BRIGHT_LUMA, SCRIM_ON_BRIGHT                     # noqa: E402
from xigmaui import clips as clipdb                      # noqa: E402

#: the readings the documented previews draw.  One shared fixture for both preview
#: tools, in tools/preview_pin.py - which also says, field by field, which numbers are a
#: fixture chosen so the arcs land in the same place on every machine (57 C, which is
#: 60 % of the gauge theme's measured 30..75 C span: the middle of the ramp, where both
#: position and colour carry the value) and which are a dated snapshot of the author's
#: bench.  It names the live readings too - this bench read 73 C at 89.8 % under eight
#: parallel ffmpeg decodes, and 70 C at 8.8 % with a GPU-using process running, and at
#: 73 C that arc would sit at 95.6 % of the sweep, which reads as pegged rather than as
#: a measurement.  `--live` draws those instead.
from preview_pin import PINNED                                      # noqa: E402


def frames(path: str, theme: str, ink: tuple | None, clock: str, kw: dict,
           count: int, gif_fps: float) -> list[Image.Image]:
    """`count` composited frames, in order, sampled from one streaming decode.

    The stream is `ClipPlayer` - the same object the window plays with - and the
    sampling keeps every `source_rate / gif_fps`-th frame of it.  The loop seam is
    the file's own: a clip shorter than the GIF's length simply runs past its end
    again, which is what the glass does with it.
    """
    player = clipdb.ClipPlayer(path)
    rate = player.fps or 24.0
    step = max(1, round(rate / max(0.1, gif_fps)))
    render.clock_str = lambda *a, **k: clock
    out: list[Image.Image] = []
    seen = 0
    guard = 0
    while len(out) < count and guard < count * step + 4 * max(1, step):
        bg = player.frame()
        if bg is None:
            break
        guard += 1
        if seen % step == 0:
            base = bg.convert("RGBA").resize((render.W, render.H), Image.LANCZOS)
            base.alpha_composite(render.draw(PINNED, theme, ink=ink, **kw))
            out.append(base)
        seen += 1
    player.close()
    return out


def write_gif(images: list[Image.Image], where: str, fps: float, scale: int,
              colors: int = 256) -> int:
    """Animated GIF through ffmpeg's two-stage palette filter.

    `palettegen` picks one palette for the whole animation - per-frame quantisation
    would flicker - and `stats_mode=full` looks at every pixel of every frame rather
    than only the changed ones, which measured 2-3 % bigger but keeps flat runs of
    our own glyphs stable.  `dither=bayer:bayer_scale=4` is the graded screen: off,
    the file is ~10 % smaller but gradients band; a finer bayer is bigger, not
    better.  `fps=` is deliberately *not* in this filter graph: the frames arriving
    are already the ones that will be shown (see the module docstring).
    """
    graph = (f"scale={scale}:{scale}:flags=lanczos[base];"
             "[base]split=2[pal][src];"
             f"[pal]palettegen=max_colors={colors}:stats_mode=full[p];"
             "[src][p]paletteuse=dither=bayer:bayer_scale=4")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{render.W}x{render.H}", "-r", f"{fps:g}", "-i", "-", "-vf", graph,
         "-loop", "0", "-f", "gif", where],
        input=b"".join(im.convert("RGBA").tobytes() for im in images),
        capture_output=True)          # bytes in, bytes out: no text=True here
    if proc.returncode:
        raise SystemExit("ffmpeg gif failed: "
                         + proc.stderr.decode(errors="replace").strip()[:300])
    return os.path.getsize(where)


def write_mp4(images: list[Image.Image], where: str, fps: float) -> int:
    """The same frames as H.264, at the GIF's rate - the two files show the same
    animation, which is what makes the link honest."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{render.W}x{render.H}", "-r", f"{fps:g}", "-i", "-",
         "-vf", "scale=480:480:flags=lanczos", "-c:v", "libx264", "-pix_fmt",
         "yuv420p", "-movflags", "+faststart", "-an", where],
        input=b"".join(im.convert("RGBA").tobytes() for im in images),
        capture_output=True)
    if proc.returncode:
        raise SystemExit("ffmpeg mp4 failed: "
                         + proc.stderr.decode(errors="replace").strip()[:300])
    return os.path.getsize(where)


def ink_drift(where: str, want: tuple) -> tuple:
    """The colour in the written file that is nearest to our ink, and how far.

    Asked of the decoded frames, not of the encoder's settings: a solid glyph
    survives quantisation as at least one exact value, so this is the distance the
    reader's eye is actually one step from.  `getcolors` is the cheap way to ask -
    a palettised GIF frame holds at most 256 distinct values, not 230 thousand.
    """
    im = Image.open(where)
    best = (999, None)
    n = 0
    while True:
        for _count, px in im.convert("RGB").getcolors(maxcolors=1 << 20):
            d = max(abs(a - b) for a, b in zip(px, want[:3]))
            if d < best[0]:
                best = (d, px)
        n += 1
        try:
            im.seek(n)
        except EOFError:
            break
    return best[1], best[0], n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="write the preview pane's animated composite out as a GIF "
                    "(and optionally the same frames as an MP4). No device is "
                    "opened: this is host-side drawing over a decoded file.")
    ap.add_argument("--clip", default="media/Theme_25.mp4",
                    help="background to play under the layer (default the "
                         "vendored Theme_25.mp4, the file the vendor's own "
                         "store.json pairs with the panel's default theme)")
    ap.add_argument("--theme", default="alpha", choices=sorted(render.THEMES))
    ap.add_argument("--ink", default=None, metavar="COLOUR",
                    help="the text colour to show, by name or #rrggbb; unset is "
                         "the theme's own skin (for `alpha`, white - measured)")
    ap.add_argument("--frames", type=int, default=12,
                    help="frames to show (default 12: at 6 fps that is 2.0 s, "
                         "which is two passes of the 0.96 s vendored loop)")
    ap.add_argument("--gif-fps", type=float, default=6.0,
                    help="frame rate of the GIF (default 6). The window decodes "
                         "every frame of the clip's own 20/24 fps; a GIF cannot "
                         "afford to, so this is the rate it samples at")
    ap.add_argument("--scale", type=int, default=render.W,
                    help="GIF edge in pixels (default 480, the panel's own size)")
    ap.add_argument("--colors", type=int, default=256, choices=(256, 128, 64, 32),
                    help="palette budget for the whole animation (default 256; "
                         "128 measured 23%% smaller with the text colour still "
                         "within 1/255)")
    ap.add_argument("--clock", default=time.strftime("%H:%M:%S"),
                    help="the clock string drawn into the layer (default now; "
                         "pass a fixed one for a reproducible picture)")
    ap.add_argument("--cold", type=int, default=None, metavar="C",
                    help="gauge/alpha cold end of the scale (unset: the theme's "
                         "own measured scale)")
    ap.add_argument("--hot", type=int, default=None, metavar="C", help="ditto, "
                    "hot end")
    ap.add_argument("--scrim", type=int, default=None,
                    help="alpha of the dark plate behind the glyphs; unset uses "
                         "the daemon's measured rule for this clip")
    ap.add_argument("--out", default="", help="write the GIF here (default "
                                              "docs/preview-<theme>-<clip>.gif)")
    ap.add_argument("--mp4", action="store_true",
                    help="also write the same frames as an MP4 next to the GIF, "
                         "for a click-through or a release asset")
    ap.add_argument("--live", action="store_true",
                    help="read real sensors instead of the pinned readings, so "
                         "the picture says what this machine is doing now")
    a = ap.parse_args()

    if not os.path.isfile(a.clip):
        print(f"no such clip: {a.clip}", file=sys.stderr)
        return 1
    ink = render.parse_ink(a.ink)
    dur, wide, tall, fps = clipdb._ffprobe_look(a.clip)
    first = clipdb.frame(a.clip)
    lum = clipdb.luma(first) if first else 0.0
    # One option bag for every theme, then the same signature filter the daemon and
    # the window use (`main._theme_kwargs`, `app._render_kw`): the five themes do not
    # take the same arguments - `alpha` has no `title`, `clock` has no gauge `source`
    # - and an option a theme never asked for is a TypeError, not a silent no-op.
    kw = {"bg": render.OVERLAY, "clock_size": 30, "fan": True,
          "source": "temperature", "cold": a.cold, "hot": a.hot}
    params = inspect.signature(render.THEMES[a.theme]).parameters
    kw = {k: v for k, v in kw.items() if k in params and v is not None}
    if a.scrim is not None:
        kw["scrim"] = a.scrim        # `draw` takes this, the window's `--scrim N` rule
    else:
        # ...and when it is not given, the *window's* auto rule, not the daemon's.
        # `main._scrim_for` only knows the handful of clips `CLIP_LUMA` measured, and
        # this tool can be pointed at any file in the library; `xigmaui/_render_kw`
        # measures the luma and applies the same two constants (BRIGHT_LUMA where
        # white-on-white starts, SCRIM_ON_BRIGHT how much plate fixes it).  The pane
        # draws the plate, so a preview that claims to be "the same composite the pane
        # shows" has to include it.  Counted out of the encoded GIFs for the clock over
        # `Theme_07.mp4` (measured luma 176.3 of 255): glyph against its own grown halo,
        # 47.1 with `--scrim 0` and 110.3 with the plate the rule gives, the mechanism
        # being that `_scrim` hugs what was drawn instead of washing the canvas - the
        # glyph itself stays at 241.7 either way.  The suite prints that figure for all
        # five README files, and holds it at a floor of 30.
        kw["scrim"] = SCRIM_ON_BRIGHT if lum > BRIGHT_LUMA else 0
    global PINNED
    if a.live:
        PINNED = sensors.collect()

    t0 = time.perf_counter()
    ims = frames(a.clip, a.theme, ink, a.clock, kw, a.frames, a.gif_fps)
    made = time.perf_counter() - t0
    if not ims:
        print("no frames decoded: is ffmpeg installed?", file=sys.stderr)
        return 1

    stem = a.out or os.path.join(
        "docs", f"preview-{a.theme}-{os.path.basename(a.clip).rsplit('.', 1)[0]}"
                + (f"-{render.ink_hex(ink)}" if ink else "") + ".gif")
    gif = write_gif(ims, stem, a.gif_fps, a.scale, a.colors)
    passes = (len(ims) / max(0.1, a.gif_fps)) / dur if dur else 0.0
    print(f"  frames            {len(ims)} composited in {made:.1f} s "
          f"({made / len(ims) * 1000:.0f} ms each: decode + render.draw + composite)")
    print(f"  clip              {a.clip}  {dur:.2f} s loop, {fps:g} fps, "
          f"{wide}x{tall}, mean luma {lum:.1f}")
    print(f"  layer             theme {a.theme}, text "
          f"{render.ink_hex(ink) or 'theme default'}, clock {a.clock}, "
          f"scrim {kw.get('scrim', 'auto rule')}")
    print(f"  gif               {stem}  {gif:,} B  {a.scale}x{a.scale} at "
          f"{a.gif_fps:g} fps = {len(ims) / a.gif_fps:.1f} s of a {passes:.1f}-pass "
          f"loop, {a.colors} colours")
    if ink:
        near, dist, seen = ink_drift(stem, ink)
        print(f"  ink in the file   nearest drawn colour {near} off {dist}/255 "
              f"(that palette is ffmpeg's, not the 256-colour PNG the upload path "
              f"uses; {seen} frames read back)")
    if a.mp4:
        where = stem.rsplit(".", 1)[0] + ".mp4"
        size = write_mp4(ims, where, a.gif_fps)
        print(f"  mp4               {where}  {size:,} B  the same {len(ims)} frames "
              f"at {a.gif_fps:g} fps (GitHub renders an .mp4 in markdown as an "
              f"<img>, so this is a link or a release asset, not an inline preview)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
