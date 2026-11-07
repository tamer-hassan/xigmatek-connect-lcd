#!/usr/bin/env python3
"""Make `install/xigmaui.png` and `install/xigmaui.ico`, the launcher icon.

Two sources for one file, and both are reproducible from something in the repo:

    --artwork PATH    the penguin mark (default: install/artwork/xigma-penguin.jpg).
                      The art arrives as a JPEG with a transparent-background
                      checkerboard baked into it - a JPEG cannot carry alpha -
                      so the checkerboard has to become real alpha.  The rule is
                      narrow and stated here rather than eyeballed per run: a
                      pixel is checkerboard when its channels are near-neutral
                      (spread <= CHECK_SPREAD) and light (min channel >=
                      CHECK_LIGHT), and it is *removed* only when it connects to
                      the picture's border.  That connectivity test is what keeps
                      the penguin's white belly painted: the belly is the same
                      colour as the checkerboard, so colour alone cannot tell
                      them apart.  The remaining edge is softened by a pixel of
                      blur, because the art's own anti-aliasing was blended
                      against that checkerboard.
    --draw            the picture the glass actually shows, drawn by the same
                      `render.draw()` the daemon uploads from, over a mid-loop
                      frame of the background clip this project ships with,
                      composited the way the panel composites its two layers
                      (PROTOCOL.md §9).  Useful when the question is "is the
                      drawing code right?" - if the icon looks wrong there, the
                      display code is wrong.

The committed source is `install/artwork/xigma-penguin.jpg`, 654 136 B,
sha256 3774623ba3c4e934d2f40932f2037712f617cad877e2c3d65e8063b97a1e69aa - the
mark in the repo, so the icon is always reproducible from something tracked
rather than from a file that lives only in a Downloads directory.

Metric numbers are pinned in --draw mode, like tools/previews.py pins them, so
re-running does not churn the file every time the CPU happens to be warm.  The
clock is not pinned: it is the clock.

    python3 tools/makeicon.py [-o PATH] [--ico PATH] [--logo PATH]
                              [--logo-size N] [-s SIZE] [--artwork PATH] [--draw]

What it writes, and why each one exists:

    install/xigmaui.png   256x256 RGBA, the file the .desktop entry and the Qt
                          window point at (the entry names a path, so no icon
                          theme has to find it).
    install/xigmaui.ico   the same mark at 16/24/32/48/64/128/256 px, for a
                          Windows shell or an icon theme that wants one file.
    docs/logo.png         the mark without the square padding, for the README.
                          --logo-size keeps it off the order of a megabyte.

Note on the crop: the trimmed box is 1090x944, not 1115x944, and there is still
a thin light strip at the artwork's own left edge. That is the braided tube
running off the canvas, not leftover grid: the grid's period is 16 px, it is
gone everywhere the flood can reach, and the strip is inside the tube's black
outline.  At small icon sizes the mark reads as the penguin; the display behind
it, and the temperature on that display, stop being legible around 48 px.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageChops, ImageDraw, ImageFilter    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "install", "xigmaui.png")
ICO = os.path.join(ROOT, "install", "xigmaui.ico")
ARTWORK = os.path.join(ROOT, "install", "artwork", "xigma-penguin.jpg")

# The checkerboard in the source art is white and one light grey; the art's own
# darkest outline is a near-black, so a spread-and-lightness test separates them
# without touching any coloured part of the drawing.
CHECK_SPREAD = 12
CHECK_LIGHT = 185
# The flood's fill value, in the mask's own mode: "L", so an int.  Worth saying
# because the failure mode is quiet - Pillow's floodfill raises on an int for an
# "L" image and, on an RGB image, silently fills with nothing at all, which reads
# as an icon with a photo of the grey grid still pasted into it.
CHECK_FILL = 128
ICO_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
             (256, 256))

# what ALPHA's own captured frame reads, so --draw matches docs/preview-*.png
PINNED = {"cpu": {"temperature": 57.0, "load": 42.0},
          "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45}}


def checkerboard(rgb: Image.Image) -> Image.Image:
    """"L" mask, 255 where a pixel looks like the baked-in checkerboard."""
    r, g, b = rgb.split()
    hi = ImageChops.lighter(ImageChops.lighter(r, g), b)
    lo = ImageChops.darker(ImageChops.darker(r, g), b)
    neutral = ImageChops.subtract(hi, lo).point(
        lambda v: 255 if v <= CHECK_SPREAD else 0)
    light = lo.point(lambda v: 255 if v >= CHECK_LIGHT else 0)
    return ImageChops.darker(neutral, light)


def reach_from_border(mask: Image.Image) -> tuple:
    """Flood the mask from every border pixel that looks like checkerboard, and
    mark what the flood reaches with CHECK_FILL.  Anything it does not reach is
    interior to the art, however checkerboard-coloured it is.

    The mask is "L" and CHECK_FILL an int on purpose: Pillow's floodfill raises
    on a tuple for an "L" image and, worse, silently fills nothing at all when an
    RGB image is handed an int - and a no-op flood leaves the grey grid inside
    the icon while everything still exits zero.
    """
    w, h = mask.size
    px = mask.load()
    seeds = [(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
    seeds += [(0, y) for y in range(1, h - 1)] + [(w - 1, y)
                                                  for y in range(1, h - 1)]
    fills = 0
    for xy in seeds:
        if px[xy] == 255:
            ImageDraw.floodfill(mask, xy, CHECK_FILL, thresh=64)
            fills += 1
    return mask, fills


def cutout(path: str) -> Image.Image:
    """The mark on a real alpha channel, trimmed to its ink: the checkerboard the
    border reaches becomes transparent, everything else is kept."""
    rgb = Image.open(path).convert("RGB")
    mask, fills = reach_from_border(checkerboard(rgb))
    back = mask.point(lambda v: 255 if v == CHECK_FILL else 0)
    back = back.filter(ImageFilter.GaussianBlur(1.0))   # the art is pre-blended
    alpha = ImageChops.invert(back)
    # JPEG noise leaves a few isolated opaque specks adrift in the cleared area
    # (a noisy pixel whose channels were not near-neutral).  A median pass over
    # the alpha channel clears specks a pixel or two across without touching the
    # art, which is solid at that scale; the count is printed, not assumed.
    clean = alpha.filter(ImageFilter.MedianFilter(3))
    specks = sum(1 for v in ImageChops.difference(alpha, clean).point(
        lambda v: 1 if v > 127 else 0).get_flattened_data() if v)
    img = rgb.copy()
    img.putalpha(clean)
    # trim on the alpha, not the bands: the cleared pixels still hold the grey
    # grid's colours, and getbbox() on an RGBA image counts those as ink
    img = img.crop(img.getchannel("A").getbbox())
    data = img.getchannel("A").get_flattened_data()
    clear = sum(1 for a in data if a == 0)
    white = sum(1 for px in img.get_flattened_data()
                if px[3] > 200 and min(px[:3]) > 200)
    print(f"  source {os.path.basename(path)} {rgb.size[0]}x{rgb.size[1]}  "
          f"border floods {fills}  specks cleared {specks}  trimmed to "
          f"{img.size[0]}x{img.size[1]}  transparent {clear} of "
          f"{img.size[0] * img.size[1]}  near-white kept {white}")
    return img


def square(img: Image.Image) -> Image.Image:
    """Centre the mark on a square canvas: icons are square, and a desktop will
    crop a non-square one however it likes."""
    side = max(img.size)
    pad = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    pad.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)
    return pad


def from_glass(size: int) -> Image.Image:
    from xigmalcd import render
    from xigmalcd.main import DEFAULT_MP4
    from xigmaui import clips as clipdb          # ffmpeg, PIL: no Qt, no port
    back = clipdb.frame(DEFAULT_MP4)
    if back is None:
        print(f"no frame out of {DEFAULT_MP4}: is ffmpeg installed and the clip "
              f"there?", file=sys.stderr)
        return None
    # scrim 0: the shipped clip measures a mean luma of 18.7 of 255, well under
    # the point where white-on-white starts (main.BRIGHT_LUMA), so the plate the
    # daemon would add for a bright clip is not needed here
    osd = render.draw(PINNED, "alpha", bg=render.OVERLAY, clock_size=30,
                      fan=False, scrim=0)
    img = back.resize(osd.size, Image.Resampling.LANCZOS).copy()
    img.alpha_composite(osd)
    print(f"  source {os.path.basename(DEFAULT_MP4)} + the alpha theme, "
          f"pinned metrics {PINNED}")
    return img.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default=OUT)
    ap.add_argument("--ico", default=ICO,
                    help="also write a multi-size .ico here ('' to skip)")
    ap.add_argument("--logo", default="",
                    help="also write the mark itself, trimmed and on alpha, to "
                         "this path (docs/logo.png)")
    ap.add_argument("--logo-size", type=int, default=512,
                    help="long edge for --logo; 0 keeps the source size")
    ap.add_argument("-s", "--size", type=int, default=256,
                    help="edge length in px (the --draw source is 480x480)")
    ap.add_argument("--artwork", default=ARTWORK,
                    help="the mark to use (default: %(default)s)")
    ap.add_argument("--draw", action="store_true",
                    help="use the glass drawing instead of the mark")
    a = ap.parse_args(argv)

    if a.draw:
        img = from_glass(a.size)
        if img is None:
            return 1
    else:
        if not os.path.exists(a.artwork):
            print(f"no artwork at {a.artwork}; use --draw for the glass picture",
                  file=sys.stderr)
            return 1
        mark = cutout(a.artwork)
        if a.logo:
            out = mark
            if a.logo_size and max(mark.size) > a.logo_size:
                scale = a.logo_size / max(mark.size)
                out = mark.resize((round(mark.width * scale),
                                   round(mark.height * scale)),
                                  Image.Resampling.LANCZOS)
            out.save(a.logo, "PNG")
            print(f"{a.logo}  {out.size[0]}x{out.size[1]}  {out.mode}  "
                  f"{os.path.getsize(a.logo)} bytes")
        img = square(mark).resize((a.size, a.size), Image.Resampling.LANCZOS)

    img.save(a.out, "PNG")
    print(f"{a.out}  {img.size[0]}x{img.size[1]}  {img.mode}  "
          f"{os.path.getsize(a.out)} bytes")
    if a.ico:
        img.save(a.ico, "ICO", sizes=ICO_SIZES)
        ico = Image.open(a.ico)
        print(f"{a.ico}  {os.path.getsize(a.ico)} bytes  sizes "
              f"{sorted({s[0] for s in ICO_SIZES})} "
              f"(read back: {ico.size[0]}x{ico.size[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
