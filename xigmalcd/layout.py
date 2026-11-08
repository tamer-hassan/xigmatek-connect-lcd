"""Draw one of ALPHA's own themes live, from the copied layout.

`themes/alpha/layouts/` says where every widget sits, how big its font is, what
colour it is and what range a bar spans, and `themes/alpha/foreground/` shows what
the app drew for those same widgets with its own sample values.  This module is the
part in between: walk `osd.widget[]` and paint it with values from `sensors.py`.

Three things are kept deliberately separate, because only two of them are measured:

* **geometry and colour** - from the layout, verbatim.  Nothing here invents a
  position, a size or a colour; `line` widgets are the one exception and their
  colour is a documented gap (see `themes/alpha/README.md`).
* **the anchor convention** - measured off the app's own baked PNG for theme
  1757491589871 and written up in `render.py`: `(x, y)` is the top-left of the em
  box (Pillow's `la`), and a bar's `(x, y)` is its track's top-left.  Same em
  box, so `la` is what `draw_text` uses; if that is wrong for some other theme,
  `tools/theme_check.py` says so in pixels rather than leaving it assumed.
* **the formats** - what a `data` widget shows for a number is not in the layouts
  at all (no unit, no decimals field).  `VENDOR_FORMAT` records the ones that
  were measured off the app's own baked PNGs and marks the rest as gaps, so the
  guesswork is visible instead of buried.
"""
from __future__ import annotations

import glob as _glob
import json

from PIL import Image, ImageDraw, ImageFont

from .render import SS, _FONT_GLOBS

# Fonts the layouts name, and what this machine has.  No Microsoft fonts are
# installed here, so every one of these is a substitution; Liberation Sans is
# metric-compatible with Arial, the others are not, and tools/theme_check.py
# measures the difference against the app's own baked PNG instead of trusting it.
FONTS = {
    "arial": {
        "regular": "/usr/share/fonts/**/LiberationSans-Regular.ttf",
        "bold": "/usr/share/fonts/**/LiberationSans-Bold.ttf",
    },
    "verdana": {
        "regular": "/usr/share/fonts/**/DejaVuSans.ttf",
        "bold": "/usr/share/fonts/**/DejaVuSans-Bold.ttf",
    },
    "simsun": {
        "regular": "/usr/share/fonts/**/NotoSansCJK-Regular.ttc",
        "bold": "/usr/share/fonts/**/NotoSansCJK-Bold.ttc",
    },

    # The face this program's own five themes are drawn with, spelled out of
    # render._FONT_GLOBS rather than guessed at: an exported built-in layout names
    # this family instead of borrowing a vendor one that happens to resolve to the
    # same file on this box.  The parity gate in tools/selftest.sh is what proves
    # the two doors put down the same glyphs at the same sizes.
    "dejavu": {
        "regular": _FONT_GLOBS[1],
        "bold": _FONT_GLOBS[0],
    },
    "宋体": {
        "regular": "/usr/share/fonts/**/NotoSansCJK-Regular.ttc",
        "bold": "/usr/share/fonts/**/NotoSansCJK-Bold.ttc",
    },
}

_font_cache: dict = {}


def font_for(prop: dict):
    """The TrueType face for one widget's fontFamily/fontSize/bold, or None if
    the layout names a family we cannot resolve (the caller must say so)."""
    fam = (prop.get("fontFamily") or "").lower()
    size, bold = int(prop.get("fontSize") or 12), bool(prop.get("bold"))
    key = (fam, size, bold)
    if key in _font_cache:
        return _font_cache[key]
    spec = FONTS.get(fam)
    path = None
    if spec:
        for pat in (spec["bold"], spec["regular"]) if bold else (spec["regular"],):
            path = next(iter(_glob.iglob(pat, recursive=True)), None)
            if path:
                break
    face = ImageFont.truetype(path, size * SS) if path else None
    _font_cache[key] = (face, fam, path)
    return _font_cache[key]


def rgba(text: str) -> tuple:
    """CSS `rgba(r, g, b, a)` as Pillow expects.  All 152 widgets' colours are
    this form; alpha is used (the one arc's track is alpha 0.5)."""
    inner = text[text.index("(") + 1:text.rindex(")")]
    p = [float(x) for x in inner.split(",")]
    return (int(p[0]), int(p[1]), int(p[2]),
            int(round(255 * (p[3] if len(p) > 3 else 1))))


# ---------------------------------------------------------------- formats --
# A `data` widget carries a `source` name and nothing else: no unit, no decimal
# count, no format string.  So the text the vendor actually painted had to be
# read back off its own baked overlay PNGs.  What follows records, per source,
# either that reading (with the theme it was read from) or the gap.  `None`
# means: the layouts do not say and no baked PNG of ours has settled it, so the
# entry is a choice made here and drawn as such - it is never put on the wire as
# though it were the vendor's.
def _pct(v):
    return f"{int(round(v))}%"


def _deg(v):
    return f"{int(round(v))}\u00b0C"


VENDOR_FORMAT = {
    # measured off foreground/1757491589862.png (theme 1757491589871): the
    # temperature reads `31` with the degree sign inline, usage reads `11%` and
    # `2%`, both left-aligned on the widget's x
    "CPU Temperature": _deg,
    "GPU Temperature": _deg,
    "CPU Usage": _pct,
    "GPU Usage": _pct,
    # not measured: no shipped theme of ours bakes a value for these, so the
    # shape below is this repo's choice and theme_check reports it as a gap
    "CPU Power": lambda v: f"{v:.1f}",
    "GPU Power": lambda v: f"{v:.1f}",
    "CPU Frequency": lambda v: f"{v:.2f}",
    "GPU Frequency": lambda v: f"{v:.2f}",
    "Pump Speed": lambda v: f"{int(round(v))}",
    "Fan Speed": lambda v: f"{int(round(v))}",
    "GPU Fan Speed": lambda v: f"{int(round(v))}",
    "Memory Usage": _pct,
    "Upload Speed": lambda v: f"{v:.1f}",
    "Download Speed": lambda v: f"{v:.1f}",
    # ALPHA's own constant pool carries `Time_hh:mm`, `Week_en` and `kb/s`, so
    # the app does format these; the formats' values live in V8 bytecode we have
    # not disassembled, so these three shapes are ours until that is done.
    "Time": lambda v: v.strftime("%H:%M:%S"),
    "Date": lambda v: v.strftime("%m/%d/%Y"),
    "Week": lambda v: v.strftime("%A").upper(),
}

FORMATS_MEASURED = ("CPU Temperature", "GPU Temperature", "CPU Usage", "GPU Usage")


def text_for(source: str, value, fmt: str | None = None) -> str:
    """The string one `data` widget shows.

    `fmt` is the extension key (`xigma.format`), and it exists for one reason: an
    exported built-in theme has to keep the shape its own drawing has today, and two of
    those shapes are not the vendor's.  `clock` writes the date as
    `%A %d %B %Y` (`render.date_str`), while the vendor's `Date` shape in this file is
    `%m/%d/%Y` - neither is measured off the vendor's picture, so making the export
    rewrite the theme to *our* vendor-shaped format would change the picture on the
    glass for no measured reason.  Said plainly: a format on a widget is the theme's
    business, and this key keeps both claims true at once.

    A `%`-bearing string is applied with `strftime` to anything that has it (a datetime)
    and with `format()` to a number, which is the only two kinds a `source` can be.
    """
    if fmt:
        if hasattr(value, "strftime"):
            return value.strftime(fmt)
        return format(value, fmt)
    fn = VENDOR_FORMAT.get(source)
    if fn is None:
        raise KeyError(f"no format for source {source!r}")
    return fn(value)


# --------------------------------------------------------------- painting --
def draw_text(draw: ImageDraw.ImageDraw, prop: dict, value: str, face,
              relayout=None) -> tuple:
    """One `text` or `data` widget.  Returns the ink box in device px, which is what
    tools/theme_check.py compares to the vendor's.

    Every ALPHA file anchors at the em box's top-left (`la`), and that is the default
    here unchanged.  Two keys under `xigma` exist because the five themes this program
    wrote for itself are not drawn that way, and an export that pretended they were
    would move ink on the glass:

    * `anchor` - Pillow's anchor name.  `clock`, `bars` and `dual` centre their lines
      (measured in `render._text`, whose default is `mm`), so their export says so
      instead of shifting every centred line left by half its own width.
    * `autoFitMax` - the widest a line may be, in panel px, and `relayout` rebuilds the
      face at a smaller size.  `render._fit` walks the size down in steps of 2 to a floor
      of 10 until the string fits, and the loop below is the same loop: our clock line is
      140 px until a three-digit value forces it down, and a fixed `fontSize` cannot say
      that.  The steps are copied from `_fit` deliberately - a different step would be a
      different size on the glass at the same reading.
    """
    ext = prop.get("xigma") or {}
    anchor = str(ext.get("anchor") or "la")
    maxw = ext.get("autoFitMax")
    x, y = int(prop["x"]) * SS, int(prop["y"]) * SS
    fill = rgba(prop["textColor"]) if prop.get("textColor") else (255, 255, 255, 255)
    if maxw and relayout:
        size = int(prop.get("fontSize") or 10)
        while size > 10 and draw.textlength(value, font=face) > int(maxw) * SS:
            size -= 2
            face = relayout(size)
    draw.text((x, y), value, font=face, fill=fill, anchor=anchor)
    box = draw.textbbox((x, y), value, font=face, anchor=anchor)
    return tuple(v // SS for v in box)


def draw_special_line(draw: ImageDraw.ImageDraw, prop: dict, text: str):
    """A line of text built by code, placed and styled by the layout.

    The `special` kind's text case: same anchor rule, same auto-fit rule, same face
    resolution as `draw_text`.  It exists for the composite strings - the clock
    theme's `CPU 57°C  GPU 47°C  1919 RPM` line is three readings and a fan
    average in one string, so no single vendor `source` stands for it - so that they
    can be moved, resized and recoloured from the layout without a baked PNG and
    without a second drawing path that could drift.  Returns the ink box, or None
    when the family cannot be resolved: the caller reports that rather than
    substituting a different face.
    """
    face, fam, path = font_for(prop)
    if face is None:
        return None
    relayout = lambda size: ImageFont.truetype(path, max(int(size), 1) * SS)
    return draw_text(draw, prop, text, face, relayout)


def draw_bar(draw: ImageDraw.ImageDraw, prop: dict, value) -> tuple:
    """One `bar`.  The app's own preview measures the track at exactly
    width x height from (x, y), and its fill at percent x width / (max-min), so
    a bar is a rectangle, not a rounded one - `cornerRadius` is 0 on 13 of the
    16 widgets that carry it, 5 on two, and those two are drawn round."""
    x, y = int(prop["x"]), int(prop["y"])
    w, h = int(prop["width"]), int(prop["height"])
    rad = int(prop.get("cornerRadius") or 0) * SS
    box = (x * SS, y * SS, (x + w) * SS, (y + h) * SS)
    draw.rounded_rectangle(box, radius=rad, fill=rgba(prop["bgColor"]))
    frac = frac_of(prop, value)
    span = int(round(w * frac))
    if span > 0:
        # startColor -> endColor along the fill; on the shipped themes both bars
        # carry a near-identical pair, so the ramp is usually invisible
        fill = rgba(prop["startColor"])
        draw.rounded_rectangle((x * SS, y * SS, (x + span) * SS, (y + h) * SS),
                               radius=rad, fill=fill)
    return (x, y, x + w, y + h)


def frac_of(prop: dict, value) -> float:
    """Where a value sits in the widget's declared range, clamped.  Every `bar`
    and the one `arc` carry minValue/maxValue, and the arc's are what the
    vendor's own frames use: measured on the 65 overlays of one capture, the
    fill's edge crosses half coverage at 153.90/156.45/159.30/161.94/164.79/
    167.44 degrees along the 270-degree sweep for the frames that display
    57/58/59/60/61/62, and (value - min) / (max - min) x 270 predicts
    153.9/156.6/159.3/162.0/164.7/167.4 - a worst residual of 0.32 deg over
    both captures, which is 0.12 of one unit of the declared range."""
    lo, hi = float(prop.get("minValue", 0)), float(prop.get("maxValue", 100))
    return min(max((float(value) - lo) / (hi - lo), 0.0), 1.0)


def arc_angles(prop: dict) -> tuple:
    """`angleStart`/`angleEnd` in the angles Pillow's `arc` wants.

    Measured, not assumed: the ink of the vendor's own ring runs from 135 deg to
    405 deg in Pillow's terms (0 deg at 3 o'clock, growing clockwise on screen),
    where the layout declares 45 and 315.  So the app's 0 is the bottom of the
    circle and its angles grow the same way Pillow's do, and the rule is
    `pil = app + 90`.  The sweep ends are butt caps: sampled along the ring, ink
    reaches offset 270 and stops dead at 271, and there is none at -1.  Measured
    at 4x on both captures, the fill's near end crosses half coverage at +0.015
    deg in all 88 frames - the cap is at the declared angle, to 0.03 px.
    """
    return float(prop["angleStart"]) + 90.0, float(prop["angleEnd"]) + 90.0


# The ring's colour, read off the app's own frames instead of interpolated from
# the two colours the layout declares.  Sampled along the middle of the stroke
# at 2x, at radius 116/120/124, keeping only fully opaque pixels (alpha 250+),
# averaged over all 65 overlays of one capture: every degree agrees across all
# the frames that reach it, and across the stroke to within 2/255, so the colour
# is a function of the angle alone and of nothing else - in particular not of
# the value being displayed, which only decides how far the fill runs.
#
# It is not a straight line between startColor and endColor.  It holds exactly
# startColor, rgba(0,247,255), from the sweep's start to 32 deg; runs down to
# rgb(0,251,184) between 33 and 120 deg; and stays at rgb(0,251,184) from 121 deg
# to 165 deg, the deepest any frame in either capture fills.  endColor,
# rgba(0,255,113), does not appear anywhere in any frame we have, and 166..270
# deg is simply not measured - no frame reached there, and the unfilled track is
# a flat rgba(161,246,255,0.5).  Linear between the samples below reproduces the
# per-degree readings to within 2/255.
#
# Keyed by the declared pair so it only ever applies to the theme it was
# measured on; any other pair falls back to the straight lerp, which `draw_arc`
# reports as the unmeasured case it is.
ARC_COLOUR_MEASURED = {
    ((0, 247, 255), (0, 255, 113)): {
        0: (0, 247, 255), 30: (0, 247, 255), 35: (0, 247, 253),
        40: (0, 247, 250), 45: (0, 247, 247), 50: (0, 247, 244),
        55: (0, 248, 240), 60: (0, 248, 237), 65: (0, 248, 232),
        70: (0, 248, 228), 75: (0, 248, 224), 80: (0, 249, 220),
        85: (0, 249, 215), 90: (0, 249, 210), 95: (0, 249, 206),
        100: (0, 250, 201), 105: (0, 250, 197), 110: (0, 250, 192),
        115: (0, 250, 189), 120: (0, 251, 185), 125: (0, 251, 184),
        165: (0, 251, 184),
    },
}


def arc_colour(prop: dict, deg: float, sweep: float) -> tuple:
    """(colour, how it was chosen) at `deg` degrees from the sweep's start."""
    start, end = rgba(prop["startColor"]), rgba(prop["endColor"])
    tab = ARC_COLOUR_MEASURED.get((start[:3], end[:3]))
    if tab is None:
        t = max(0.0, min(1.0, deg / sweep))
        col = tuple(round(start[i] + (end[i] - start[i]) * t) for i in range(4))
        return col, ("straight lerp startColor->endColor over the whole sweep "
                     "(this colour pair was never measured on the glass)")
    ks = sorted(tab)
    if deg >= ks[-1]:                    # past the last measured sample: the
        rgb = tab[ks[-1]]                # plateau continues, and that is a gap
    elif deg <= ks[0]:                   # before the first (the cap antialiases
        rgb = tab[ks[0]]                 # here, which is why deg 0 is not read)
    else:
        lo = max(k for k in ks if k <= deg)
        hi = min(k for k in ks if k >= deg)
        t = (deg - lo) / (hi - lo)
        rgb = tuple(round(tab[lo][i] + (tab[hi][i] - tab[lo][i]) * t)
                    for i in range(3))
    return rgb + (start[3],), f"measured profile, {len(tab)} samples"



def draw_arc(draw: ImageDraw.ImageDraw, prop: dict, value) -> tuple:
    """One `arc` (`doughnut-node`), drawn the way the vendor's frames measure.

    Returns (bounding box in device px, how the fill's colour was chosen), so
    the caller can print the colour decision instead of inheriting it silently.

    (x, y) is the **top-left of the bounding box**, not the centre: the box is
    `sizeWidth` x `sizeHeight` (260x260 on the default theme), which puts the
    ink of the vendor's ring at exactly x..x+sizeWidth - its own overlay's alpha
    bbox ends at x=367 for a box at x=107, width 260.  `radius` is the *inner*
    edge (110) and `width` the stroke (20), so outer = 130 = sizeWidth/2, and
    Pillow's `arc`, whose stroke is centred on the ellipse, reproduces that with
    `width` as given.

    That band is now measured rather than inferred (`tools/theme_check.py
    --arc`): probing outward along the ray and taking half of whatever coverage
    that ray reaches - the fill reaches 255, the unfilled track reaches the
    track's own 128 - the vendor's stroke is 19.75..20.50 px wide with its
    centre wandering between radius 119.38 and 121.00 px, and ours is
    19.75..20.25 px wide at 120.00..120.62.  The layout's `radius + width/2` is
    where the ring really is, and the vendor's own rasterisation is the noisier
    of the two.  The unfilled part of the sweep is painted, not left empty: its
    coverage reads exactly 128 = the declared `bgColor` alpha of 0.5.  (Ours
    reads 129..138 at the plateau - the SS=2 -> 1x LANCZOS downsample rings a
    little on a hard alpha edge, which is a defect of ours, by <=10/255.)
    """
    x, y = int(prop["x"]) * SS, int(prop["y"]) * SS
    r = int(prop["radius"])
    sw = int(prop.get("sizeWidth") or 2 * r + int(prop.get("width") or 0) * 2)
    sh = int(prop.get("sizeHeight") or sw)
    thick = int(prop.get("width") or 0)
    box = (x, y, x + sw * SS, y + sh * SS)
    a0, a1 = arc_angles(prop)
    draw.arc(box, a0, a1, fill=rgba(prop["bgColor"]), width=thick * SS)
    f = frac_of(prop, value)
    if f <= 0:
        return (x // SS, y // SS, x // SS + sw, y // SS + sh), "no fill"
    # The vendor's fill is not one flat colour, and it is not a straight line
    # between the two colours the layout declares either - see
    # ARC_COLOUR_MEASURED.  Each degree is its own colour, so the fill is drawn
    # as a run of one-degree arcs (half a degree at SS, so the segment ends land
    # on whole degrees of the sweep).
    start_c, end_c = rgba(prop["startColor"]), rgba(prop["endColor"])
    ramp_note = "measured profile" if (start_c[:3], end_c[:3]) in \
        ARC_COLOUR_MEASURED else "straight lerp (unmeasured colour pair)"
    stop = a0 + f * (a1 - a0)
    step = max(1, int(round(1 * SS / 2)))          # ~1 deg at SS
    a = a0
    while a < stop:
        b = min(a + step, stop)
        col, _ = arc_colour(prop, (a + b) / 2 - a0, a1 - a0)
        draw.arc(box, a, b, fill=col, width=thick * SS)
        a = b
    return (x // SS, y // SS, x // SS + sw, y // SS + sh), ramp_note


#: The only two layouts in this library that carry a `line` widget - `Theme_14` and
#: `theme_46`, four widgets between them - declare no colour for it.  Their own baked
#: overlays (`themes/alpha/foreground/1757491588481.png`, the picture the vendor app drew
#: for its own sample values) say what it is: a solid bar at **rgba(240, 255, 255, 255)**,
#: every one of the 796 pixels of it the same, alpha 255 and hard-edged - no antialiasing
#: anywhere along it.  The renderer bundle's own default for the shape is
#: `lineColor: "rgba(19, 206, 102, 1)"`, a green that no shipped theme is observed to
#: draw, so the measured ink is used and the bundle default stays a comment.
MEASURED_LINE_INK = (240, 255, 255, 255)


def line_rect(prop: dict) -> tuple:
    """The rect a `line` fills, in the two conventions the vendor's picture shows.

    Measured off `foreground/1757491588481.png`, pixel by pixel: the stroke is the declared
    rect `[x, x+width) x [y, y+height)` - the horizontal widget there lights exactly
    x 115..364 (250 px, the declared `width`) by y 230..231 (2 px, the declared `height`),
    and nothing at y 229 or y 232 - so `height` *is* the thickness, not `lineWidth`.
    And `rotate` turns that rect about the rect's own centre: the second widget declares
    x165 y305 width150 height2 at `rotate: 90`, and the picture puts it at x 239..240,
    y 231..380 - which is centre (240, 306), not the top-left corner (a corner pivot would
    have left it at x=165, and a pixel-centre pivot would have lit x=238 as well, which it
    does not).
    """
    x, y = int(prop["x"]), int(prop["y"])
    w, h = int(prop["width"]), int(prop.get("height") or 2)
    if int(prop.get("rotate") or 0) % 180 == 90:      # 90 and 270 across the centre
        cx, cy = x + w / 2.0, y + h / 2.0
        x, y = int(round(cx - h / 2.0)), int(round(cy - w / 2.0))
        x, y, w, h = x, y, h, w
    thick = int(prop.get("lineWidth") or 0)
    if thick and thick != h:
        # an edited file that sets `lineWidth` differently from the declared thickness gets
        # it centred on the rect's own middle line, and the returned box says so rather
        # than quietly keeping the two in agreement
        y, h = y + h // 2 - thick // 2, thick
    return x, y, w, h


def draw_line(draw: ImageDraw.ImageDraw, prop: dict, value=None) -> tuple:
    """One `line`.  All four in this library are decoration: none of them carries a
    `source`, so there is no series to plot, nothing to skip and nothing to flag as a
    missing reading.  What is flagged is the colour: it is not in the file, and what we
    draw is the ink measured off the two vendor overlays that have one."""
    x, y, w, h = line_rect(prop)
    colour = rgba(prop["lineColor"]) if prop.get("lineColor") else MEASURED_LINE_INK
    draw.rectangle((x * SS, y * SS, (x + w) * SS - 1, (y + h) * SS - 1), fill=colour)
    return (x, y, x + w, y + h)


KINDS = {"text": "draw_text", "data": "draw_text", "bar": "draw_bar",
         "arc": "draw_arc", "line": "draw_line", "special": "draw_special"}


def draw_theme(obj: dict, values: dict, *, canvas: tuple | None = None,
               specials: dict | None = None):
    """Paint one theme object.  `values` maps `source` -> number (or a datetime
    for Time/Date/Week).  Returns (image, notes) where notes record every font
    substitution, every source with no value, and every gap touched - so a
    caller can print what was decided rather than trusting it.

    `specials` is the registry for the one added kind, `special`: {name: callable}.  A
    special is a picture that stays code-drawn and takes its position, size and reading
    from the layout - the fan figures, the tick strip, the clock's readings line.  It
    exists so those elements can *move* without being baked into PNGs, and it is
    injected rather than imported because those drawings live in `render.py`, which
    this module must not import (render imports this one).  A name with no drawing is
    reported in `notes["missing"]` as `special:<name>`: an unknown name is said, not
    guessed at.

    The `xigma` extension keys a text or data widget may carry - `anchor`,
    `autoFitMax`, `format` - are documented at `draw_text` and `text_for`, each with
    the measured difference between our five and the vendor's files that forced it."""
    W, H = canvas or (obj["width"], obj["height"])
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    notes = {"fonts": {}, "missing": [], "gaps": [], "boxes": []}
    for w in obj["osd"]["widget"]:
        prop = w["property"][0]
        kind = w["type"]
        if kind in ("text", "data"):
            if kind == "data":
                src = prop["source"]
                if src not in values:
                    notes["missing"].append(src)
                    continue
                ext = prop.get("xigma") or {}
                if src not in FORMATS_MEASURED and not ext.get("format"):
                    notes["gaps"].append(src)
                try:
                    s = text_for(src, values[src], ext.get("format"))
                except KeyError:
                    notes["missing"].append(src)
                    continue
            else:
                s = prop["content"]
            face, fam, path = font_for(prop)
            if face is None:
                notes["missing"].append(f"font:{fam}")
                continue
            notes["fonts"][f"{fam}/{prop.get('fontSize')}"
                           f"{'b' if prop.get('bold') else ''}"] = path
            relayout = ((lambda size: ImageFont.truetype(path,
                        max(int(size), 1) * SS))
                if path else None)
            notes["boxes"].append((kind, prop.get("content") or prop.get("source"),
                                   draw_text(draw, prop, s, face, relayout)))
        elif kind == "bar":
            if prop["source"] not in values:
                notes["missing"].append(prop["source"])
                continue
            notes["boxes"].append(("bar", prop["source"], draw_bar(draw, prop,
                                                                   values[prop["source"]])))
        elif kind == "arc":
            if prop["source"] not in values:
                notes["missing"].append(prop["source"])
                continue
            box, ramp = draw_arc(draw, prop, values[prop["source"]])
            notes["arc_colour"] = ramp
            if ramp.startswith("straight"):
                notes["gaps"].append("arc colour, " + prop["source"])
            notes["boxes"].append(("arc", prop["source"], box))
        elif kind == "special":
            name = str(prop.get("name") or "")
            fn = (specials or {}).get(name)
            if fn is None:
                notes["missing"].append(f"special:{name}")
                continue
            notes["boxes"].append(("special", name, fn(draw, prop, values)))
        elif kind == "line":
            notes["gaps"].append("line colour")
            notes["boxes"].append(("line", prop.get("source") or "line",
                                   draw_line(draw, prop)))
    return img.resize((W, H), Image.LANCZOS), notes


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
