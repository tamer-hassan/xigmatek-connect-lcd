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

from .render import (A26_FAN_F, A26_FAN_MAX_W, A26_TVAL_F, SS, _FONT_GLOBS,
                     fan_figures, heat, value_pair)

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
    # the two fan entries carry the vendor's own display names now: the app's metric
    # vocabulary was read out of its uncompiled renderer bundle (`cpuFansSpeed` "CPU Fans
    # Speed", `gpuFansSpeed` "GPU Fans Speed", PROTOCOL.md §10, 2026-11-06), and the shorter
    # names these had were ours.  Note what that vocabulary does *not* offer: a row per fan
    # sensor.  It has one aggregate CPU-fan metric and one GPU-fan metric, which is why
    # `bars`'s per-sensor rows need source names the vendor never had (docs/theme-editor.md).
    "CPU Fans Speed": lambda v: f"{int(round(v))}",
    "GPU Fans Speed": lambda v: f"{int(round(v))}",
    # `bars`'s rows, and the rule the suite holds them to: every `source` this program can
    # answer has a display shape here, so a text row can never reach the painter and die for
    # want of one.  The two gigabyte shapes are what the theme's own text prints - a
    # percentage meter with a gigabyte number beside it, which is why one row reads two
    # sources - and the per-sensor fan names cut the label to the same 10 characters the
    # drawing cuts, because the shape that hides a long `sensors` name belongs with the row,
    # not with the reading.  None of these five is measured off the vendor's picture:
    # `draw_theme` reports them as gaps, and `formats_measured()` says which four are.
    "RAM Rate": _pct,
    "GPU Memory Rate": _pct,
    "Used RAM": lambda v: f"{int(v) // 1024} GB",
    "Used GPU Memory": lambda v: f"{int(v) // 1024} GB",
    "Motherboard Temperature": _deg,
    "Fan 1 Speed": lambda v: f"{int(round(v))}",
    "Fan 2 Speed": lambda v: f"{int(round(v))}",
    "Fan 3 Speed": lambda v: f"{int(round(v))}",
    "Fan 4 Speed": lambda v: f"{int(round(v))}",
    "Fan 1 Name": lambda v: str(v)[:10],
    "Fan 2 Name": lambda v: str(v)[:10],
    "Fan 3 Name": lambda v: str(v)[:10],
    "Fan 4 Name": lambda v: str(v)[:10],
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


def fit_ring(prop: dict) -> tuple:
    """The ring a text row is sized against, as the six numbers `render.value_pair` needs:
    `(cx, cy, inner, outer, start, sweep)`, panel px and Pillow degrees.

    `xigma.fitArc` spells the ring in the vocabulary an `arc` row already uses - `radius` is
    the **inner** edge and `width` the stroke, so outer is `radius + width`, and
    `angleStart`/`angleEnd` are the app's own degrees where 0 is the bottom of the circle
    (`arc_angles` measures the rule).  It describes **one** of the pair's two rings, because
    the fit only ever needs one: the two rings are congruent, so measuring the first
    column's - at `x - width/2`, the row being symmetric about its own `x` - answers both,
    which is exactly what `render.theme_alpha` does by passing `A26_TCOL_X[0]`.

    Returns `(ring, why_not)`.  `why_not` names the key that is missing or impossible, in
    words a checker can print: a row that declares no ring cannot be sized, and drawing it
    at the ceiling instead would put the figures over the gauge they stand inside.
    """
    ext = prop.get("xigma") or {}
    arc = ext.get("fitArc")
    if not isinstance(arc, dict):
        return None, "xigma.fitArc is missing, or is not an object"
    absent = [k for k in ("cy", "radius", "width", "angleStart", "angleEnd")
              if k not in arc]
    if absent:
        return None, f"xigma.fitArc carries no {' '.join(absent)}"
    inner, stroke = int(arc["radius"]), int(arc["width"])
    if inner <= 0 or stroke <= 0:
        return None, (f"xigma.fitArc radius {inner} / width {stroke} draws no ring for "
                      f"text to clear")
    start, end = arc_angles(arc)                 # the app's angles, the `arc` row's rule
    if end <= start:
        return None, (f"xigma.fitArc angleEnd {arc['angleEnd']} does not sweep past "
                      f"angleStart {arc['angleStart']}")
    cx = int(prop["x"]) - int(prop.get("width") or 0) // 2
    return (cx, int(arc["cy"]), inner, inner + stroke, start, end - start), ""


def draw_special_values(draw: ImageDraw.ImageDraw, prop: dict, strings) -> tuple:
    """A `special` row that draws a *pair* of readings inside two rings, at one shared size.

    The placement vocabulary is `draw_special_pair`'s - `x` is the pair's centre, `width`
    the distance between the two figures' centres, `fontSize` the size ceiling,
    `textColor`/`bold` the ink, `xigma.anchor` says what an `x` means - and what differs is
    how the size is found: against the ring in `xigma.fitArc` rather than a width, because
    that is the rule this drawing uses.  It is not a gap in the design that the row has to
    name a ring: `xigma.autoFitMax` is a width, and the suite searches every whole-pixel
    budget this canvas can hold and finds none that reproduces what the ring decides
    (docs/limits.md, printed by the `the value pair, apart` line).

    Returns `(size, union ink box in panel px)`, or `(None, None)` when the family cannot be
    resolved or the row declares no ring to clear.  `draw_theme` reports the first, and
    `--check-theme` says which key of the second is missing, so a file is not left guessing
    which of its two problems it has.
    """
    face, fam, path = font_for(prop)
    if face is None:
        return None, None
    ring, _why = fit_ring(prop)
    if ring is None:
        return None, None
    ext = prop.get("xigma") or {}
    half = int(prop.get("width") or 0) // 2
    x = int(prop["x"])
    colour = rgba(prop["textColor"]) if prop.get("textColor") else (255, 255, 255, 255)
    size, boxes = value_pair(draw, tuple(strings), (x - half, x + half), int(prop["y"]),
                             ring, colour, bold=bool(prop.get("bold")),
                             ceiling=int(prop.get("fontSize") or A26_TVAL_F),
                             anchor=str(ext.get("anchor") or "ma"),
                             face=(lambda px: ImageFont.truetype(
                                 path, max(int(px), 1) * SS)) if path else None)
    return size, (min(b[0] for b in boxes), min(b[1] for b in boxes),
                  max(b[2] for b in boxes), max(b[3] for b in boxes))


def draw_special_pair(draw: ImageDraw.ImageDraw, prop: dict, figures) -> tuple:
    """A `special` row that draws a *pair* of code-built figures at one shared size.

    The row's `x`,`y` is the **pair's** centre and its `width` the distance between the two
    figures' centres, so the pair stays symmetric about the anchor the way `alpha` draws it
    and a layout can move it and re-pitch it; `fontSize` is the size ceiling,
    `xigma.autoFitMax` the width budget each figure gets, `textColor` the ink and `bold`
    the weight - the same vocabulary a `text` row already uses, which is what keeps the
    inspector's field list one list.  What stays in the drawing (`render.fan_figures`) is
    the *joint* rule: each figure is walked down until it fits its budget and both draw at
    the smaller of the two, with a floor of 16 and a step of 2.  Those are not per-row
    numbers: they are the reason the two figures look like one row, and a layout that
    could set them separately would be able to un-make the pair.

    Returns (the shared size, the union ink box in panel px), so a caller can say what the
    size came out to.  With a family that cannot be resolved, (None, None): the caller
    reports it rather than substituting a face, as `draw_special_line` does.
    """
    ext = prop.get("xigma") or {}
    face, fam, path = font_for(prop)
    if face is None:
        return None, None
    x, y = int(prop["x"]), int(prop["y"])
    half = int(prop.get("width") or 0) // 2
    colour = rgba(prop["textColor"]) if prop.get("textColor") else (255, 255, 255, 255)
    budget = int(ext.get("autoFitMax") or A26_FAN_MAX_W)
    ceiling = int(prop.get("fontSize") or A26_FAN_F)
    size, boxes = fan_figures(draw, tuple(figures), (x - half, x + half), y, colour,
                              bold=bool(prop.get("bold")), max_w=budget,
                              ceiling=ceiling, anchor=str(ext.get("anchor") or "ma"),
                              face=(lambda px: ImageFont.truetype(
                                  path, max(int(px), 1) * SS)) if path else None)
    return size, (min(b[0] for b in boxes), min(b[1] for b in boxes),
                  max(b[2] for b in boxes), max(b[3] for b in boxes))


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


#: Ramps that stay code, named so a file can ask for one: `xigma.colourRamp`.  Each entry
#: is the very function our themes call, so the named ramp cannot drift from the drawing -
#: and adding one here is a decision, because `themes.XIGMA_KEYS` and the census gate have
#: to agree about the key that carries it.
COLOUR_RAMPS = {"heat": heat}


def colour_ramp(prop: dict) -> tuple:
    """(a named ramp callable, its name, or why there is none).

    A ramp can be data (`xigma.colourStops`) and for `render.temp_colour` that is exact -
    measured at every position a ring steps through, all 100 agree.  `render.heat` is not:
    its breakpoints are 0.5 and 0.8 while its own arithmetic divides by the literals 0.3
    and 0.2, and `0.8 - 0.5` is 0.30000000000000004, so a copy spelled in stops differs at
    8 of 100 sampled positions, by one unit, in the red and blue channels.  The owner's
    decision (docs/theme-editor.md) is to *name* such a ramp rather than change the drawing:
    a named ramp is the same rule the fan figures and the two composite lines follow -
    geometry and colour position come from the file, the picture stays code - and it keeps
    every figure that was read off those themes valid.

    Where the name is applied: on an `arc` it is sampled along the sweep, on a `bar` at the
    value's fraction of the bar's own range.  An unknown name is reported, not guessed at.
    """
    ext = prop.get("xigma") or {}
    name = ext.get("colourRamp")
    if name is None:
        return None, None
    name = str(name)
    if name not in COLOUR_RAMPS:
        return None, name
    return COLOUR_RAMPS[name], name


#: How a `bar`'s fill is rasterised - the same kind of key as `ARC_PAINT`, for the same
#: reason: two painters, two rasters, and an export has to say which one it means.
#:
#:   `vendor`  measured off ALPHA's own preview: the fill spans `round(width x fraction)`
#:             panel pixels, the corners are the declared `cornerRadius`, and the fill is
#:             drawn when that span is at least one pixel.
#:   `render`  what `render.bar` does: the span is `int(width x SS x fraction)` in **device**
#:             pixels (a different rounding: 360 px wide at 63.5 % is 457 device px here
#:             against 456 the other way), the track's corners are `height/2`, the fill's
#:             corners are `min(height/2, int(width x max(fraction, 0.02))/2)` - so the
#:             roundness *changes with the reading* - and a fill is drawn only when the
#:             fraction is above 0.01.  Those are two different numbers in the function, and
#:             they are two different keys here for the same reason: the first version of
#:             this table used 0.02 for both, which loses the fill on a reading between
#:             1 % and 2 % that `render.bar` draws.
#:
#:   `hbar`    what `render.hbar` draws, which is the usage bar of the theme ALPHA selected:
#:             square ends, the track the full declared rectangle, and the fill coloured
#:             **one device column at a time** along the filled part - `startColor` at the
#:             left edge of the fill, `endColor` at its right, so the ramp's far end moves
#:             with the reading.  `render.hbar` walks `i` in `range(int(w x SS x fraction))`
#:             and paints `[x+i, y, x+i+1, y+h]` with a truncating lerp at `i / (n-1)`;
#:             those rectangles overlap by a device pixel and the track's box includes its
#:             far edge, which is what the code does and what is reproduced here rather than
#:             tidied away: the claim of a `barPaint: hbar` file is that it paints this
#:             program's picture, and the gate says whether it does - it does, at zero
#:             differing pixels (docs/limits.md).  A declared `cornerRadius` is ignored by
#:             this convention, because the function it names has no radius argument: the
#:             suite paints this bar with a corner of 0 and of 5 and gets the same picture
#:             both ways.
#:
#: Selected by `xigma.barPaint`; no key means `vendor`, which is what every copied layout
#: is.  A `bar` may also name a colour ramp (`xigma.colourRamp`) or declare stops
#: (`xigma.colourStops`), which are sampled at the value's fraction: `render.bar` colours by
#: value, and a vendor bar has no spelling for that.
BAR_PAINT = {
    "vendor": {"name": "vendor", "span": "round", "track_radius": "declared",
               "fill_radius": "declared", "guard": "span", "floor": 0.0,
               "corner_floor": 0.0, "ramp": "value"},
    "render": {"name": "render", "span": "trunc", "track_radius": "half",
               "fill_radius": "auto", "guard": "frac", "floor": 0.01,
               "corner_floor": 0.02, "ramp": "value"},
    "hbar": {"name": "hbar", "span": "trunc", "track_radius": "square",
             "fill_radius": "square", "guard": "span", "floor": 0.0,
             "corner_floor": 0.0, "ramp": "columns"},
}


def bar_paint(prop: dict) -> tuple:
    """(the convention table for one bar, or None, and the name that was asked for).

    The local is named `ext` for the same reason as `arc_paint`: `themes.keys_read()` reads
    this module's source to find the extension keys, so a new one cannot be added without
    the census noticing.
    """
    ext = prop.get("xigma") or {}
    name = str(ext.get("barPaint") or "vendor")
    if name not in BAR_PAINT:
        return None, name
    return BAR_PAINT[name], name


def draw_bar(draw: ImageDraw.ImageDraw, prop: dict, value) -> tuple:
    """One `bar`.  The app's own preview measures the track at exactly
    width x height from (x, y), and its fill at percent x width / (max-min), so
    a bar is a rectangle, not a rounded one - `cornerRadius` is 0 on 13 of the
    16 widgets that carry it, 5 on two, and those two are drawn round.

    `xigma.barPaint` names which painter's convention the widget was authored for, and
    the three of them disagree about rounding, about the corners, and about where the
    fill's colour comes from:

      `vendor` (no key) - the shape above: the span rounds in panel px, the corners are
      whatever the file declares, and the fill is one flat colour.
      `render`  - `render.bar`: the span truncates in device px, the track is round at
      height/2 whatever the file declares, the fill's corners are a function of the
      reading, and a reading that rounds to no fill still gets 2 %.
      `hbar`    - `render.hbar`, ALPHA's own usage bar: square ends regardless of the
      declared `cornerRadius`, the track covering the whole declared rect, and the fill
      coloured one device column at a time along the filled part.

    The suite paints one bar all three ways and prints the counts; for `hbar` the count
    against `render.hbar` itself is zero, which is the claim that key makes."""
    x, y = int(prop["x"]), int(prop["y"])
    w, h = int(prop["width"]), int(prop["height"])
    conv, conv_name = bar_paint(prop)
    if conv is None:
        return (x, y, x + w, y + h), f"unknown xigma.barPaint {conv_name!r}"
    rad = int(prop.get("cornerRadius") or 0) * SS
    # A declared `cornerRadius` is read three different ways, and that is part of what the
    # key names: the vendor draws what the file says, `render.bar` rounds the track to
    # height/2 whatever the file says, and `render.hbar` has no radius argument at all -
    # so `square` means 0 and is not a request for the widget's own corners.
    if conv["track_radius"] == "half":
        track_rad = (h * SS) // 2
    elif conv["track_radius"] == "square":
        track_rad = 0
    else:
        track_rad = rad
    box = (x * SS, y * SS, (x + w) * SS, (y + h) * SS)
    draw.rounded_rectangle(box, radius=track_rad, fill=rgba(prop["bgColor"]))
    frac = frac_of(prop, value)
    # device-space for the `render` convention, panel space for the vendor's: the two
    # round at different points, which is exactly the difference being named
    span = (int(w * SS * frac) if conv["span"] == "trunc"
            else int(round(w * frac)) * SS)
    if (frac > conv["floor"] if conv["guard"] == "frac" else span > 0):
        if conv["ramp"] == "columns":
            # one device column at a time, `startColor` at the left edge of the *fill*
            # and `endColor` at its right, exactly as `render.hbar` walks it - the ramp's
            # far end therefore moves with the reading, which a declared pair alone does
            # not say and `barPaint: hbar` does
            stops, _bad = colour_stops(prop)
            if stops is None:
                stops = [(0.0, rgba(prop["startColor"])),
                         (1.0, rgba(prop["endColor"]))]
            for i in range(span):
                draw.rectangle((x * SS + i, y * SS, x * SS + i + 1, (y + h) * SS),
                               fill=ramp_at(stops, i / max(span - 1, 1), "trunc"))
        else:
            if conv["fill_radius"] == "auto":
                fill_rad = min((h * SS) // 2,
                               int(w * SS * max(frac, conv["corner_floor"])) // 2)
            elif conv["fill_radius"] == "square":
                fill_rad = 0
            else:
                fill_rad = rad
            ramp, bad = colour_ramp(prop)
            if bad is not None and ramp is None:
                return (x, y, x + w, y + h), f"unknown xigma.colourRamp {bad!r}"
            stops, _why = colour_stops(prop)
            if ramp is not None:
                fill = ramp(frac)
            elif stops is not None:
                fill = ramp_at(stops, frac,
                               "trunc" if conv["span"] == "trunc" else "nearest")
            else:
                fill = rgba(prop["startColor"])
            draw.rounded_rectangle((x * SS, y * SS, x * SS + span, (y + h) * SS),
                                   radius=fill_rad, fill=fill)
    return (x, y, x + w, y + h), None


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


#: How a ring's fill is rasterised.  There are two conventions in this repo's evidence,
#: they belong to different painters, and on the same declared geometry they are *not* the
#: same picture - the suite paints one arc both ways and prints the pixel count between
#: them (164 / 3 366 / 3 889 / 6 989 differing pixels at four values, worst channel
#: delta 255), which is the whole reason this key exists.
#:
#:   `vendor` - ALPHA's own ring, as measured off its captured frames: one degree per
#:              segment, colour sampled at the middle of each segment, butt caps, and
#:              `ARC_COLOUR_MEASURED` consulted for the one pair that has been measured.
#:   `render` - this program's ring, exactly as `render.gauge` draws it: 3 degrees per
#:              segment, each segment drawn 0.4 degrees past its end so the joints do not
#:              show, colour sampled at the *start* of the segment, and the lerp truncates
#:              (`render._lerp`) instead of rounding.
#:
#: Both conventions fall back to a straight lerp for the exported built-ins, because the
#: pair in `ARC_COLOUR_MEASURED` is the vendor's *declared* one - (0,247,255) to
#: (0,255,113) - while `render.ALPHA_HOT` is the plateau that curve was measured to *end*
#: at, (0,251,184).  So the difference printed above is stepping, sampling and rounding
#: alone: same two colours, different raster.
#:
#: `xigma.arcPaint` selects one by name; no key means `vendor`, which is what every copied
#: layout is.  The exported built-ins say `render`, because the claim of an export is that
#: the layout paints what the code paints - a diff of zero, not a close match.
ARC_PAINT = {
    "vendor": {"name": "vendor", "step": max(1, int(round(1 * SS / 2))),
               "sample": "middle", "overlap": 0.0, "round": "nearest",
               "profile": True, "epsilon": 0.0},
    "render": {"name": "render", "step": 3.0, "sample": "start", "overlap": 0.4,
               "round": "trunc", "profile": False, "epsilon": 0.001},
}


def arc_paint(prop: dict) -> tuple:
    """(the convention table for one arc, or None, and the name that was asked for).

    The local is named `ext` because `themes.keys_read()` reads this module's source to
    find which extension keys exist, and that is how a new `xigma` key cannot be added
    without the census noticing it.
    """
    ext = prop.get("xigma") or {}
    name = str(ext.get("arcPaint") or "vendor")
    if name not in ARC_PAINT:
        return None, name
    return ARC_PAINT[name], name


def colour_stops(prop: dict) -> tuple:
    """The `xigma.colourStops` ramp of a widget, as [(fraction, rgba)], or (None, why).

    A ramp written as data: pairs of (position along the widget's own scale, colour),
    interpolated piecewise-linearly - the same idea as the vendor's measured ring ramp in
    `ARC_COLOUR_MEASURED`, in fraction space instead of degrees.

    Why this spelling was tested against our own ramps rather than assumed - sampled at
    every position `render.gauge` actually steps through (3 degrees along a 300-degree
    sweep, 100 positions): `render.temp_colour`'s three-stop ramp, amber at 62 C in a
    30..100 C scale, agrees with this interpolation at **all 100**, because the amber's
    fraction (62-30)/(100-30) round-trips through JSON to the same double.  `render.heat()`
    disagrees with its own stop copy at **8 of the 100**, never by more than one unit and
    only in the red and blue channels, and the eight land in exactly two places: seven
    between the 0.5 and 0.8 stops, where `heat` divides by the literal 0.3 while
    `0.8 - 0.5` is 0.30000000000000004, and one past 0.8, where it divides by 0.2 while
    `1 - 0.8` is 0.19999999999999996.  Under `int()` truncation a product a hair under an
    integer steps down.  That is our arithmetic rather than the schema, and it is what
    still blocks `dual` (docs/theme-editor.md, docs/limits.md).
    """
    ext = prop.get("xigma") or {}
    raw = ext.get("colourStops")
    if raw is None:
        return None, None
    if not isinstance(raw, list) or len(raw) < 2:
        return None, "colourStops needs at least two [fraction, colour] pairs"
    stops = []
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return None, "each colourStops entry is [fraction, rgba(...)]"
        try:
            stops.append((float(pair[0]), rgba(pair[1])))
        except (TypeError, ValueError, KeyError, IndexError):
            return None, f"colourStops entry {pair!r} is not a fraction plus an rgba() colour"
    fr = [f for f, _c in stops]
    if fr != sorted(fr) or fr[0] != 0.0 or fr[-1] != 1.0:
        return None, (f"colourStops must run from 0 to 1 in order; this one runs "
                      f"{fr[0]} to {fr[-1]}")
    return stops, None


def ramp_at(stops: list, t: float, rounding: str = "nearest") -> tuple:
    """Piecewise-linear colour at fraction `t`, rounded the convention's way."""
    t = min(max(t, 0.0), 1.0)
    mix = (lambda a, b, u: tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(4))
           if rounding == "trunc" else
           tuple(round(a[i] + (b[i] - a[i]) * u) for i in range(4)))
    for (f0, c0), (f1, c1) in zip(stops, stops[1:]):
        if t <= f1:
            span = f1 - f0
            return mix(c0, c1, 0.0 if span <= 0 else (t - f0) / span)
    return stops[-1][1]


def arc_colour(prop: dict, deg: float, sweep: float, conv: dict | None = None) -> tuple:
    """(colour, how it was chosen) at `deg` degrees from the sweep's start."""
    conv = conv or ARC_PAINT["vendor"]
    start, end = rgba(prop["startColor"]), rgba(prop["endColor"])
    mix = (lambda a, b, t: tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))
           if conv["round"] == "trunc" else
           tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(4)))
    ramp, bad = colour_ramp(prop)
    if ramp is not None:
        t = max(0.0, min(1.0, deg / sweep))
        return ramp(t), ("`xigma.colourRamp`, sampled at the " + conv["sample"] +
                         " of each segment: a ramp this program draws, named rather than "
                         "copied into stops (see colour_ramp)")
    stops, _bad = colour_stops(prop)
    if stops is not None:
        # a ramp declared in the file beats a profile looked up by colour pair: one is
        # what this theme says it wants, the other is what some other theme was measured
        # doing with colours that happen to match
        t = max(0.0, min(1.0, deg / sweep))
        return ramp_at(stops, t, conv["round"]), (
            f"`xigma.colourStops`, {len(stops)} stops, sampled at the "
            + conv["sample"] + " of each segment")
    tab = ARC_COLOUR_MEASURED.get((start[:3], end[:3])) if conv["profile"] else None
    if tab is None:
        t = max(0.0, min(1.0, deg / sweep))
        col = mix(start, end, t)
        if conv["profile"]:
            return col, ("straight lerp startColor->endColor over the whole sweep "
                         "(this colour pair was never measured on the glass)")
        return col, ("`xigma.arcPaint: " + conv["name"] + "` - straight lerp, sampled at "
                     "the " + conv["sample"] + " of each segment, "
                     + ("truncating" if conv["round"] == "trunc" else "rounding") +
                     ": this program's own ring, not the vendor's measured ramp")
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
    # The fill is not one flat colour, and for the vendor's ring it is not a straight line
    # between the two colours the layout declares either - see ARC_COLOUR_MEASURED.  Which
    # of the two conventions runs here is decided by `xigma.arcPaint`: a copied layout gets
    # the vendor's (measured off ALPHA's frames), an exported built-in gets this program's
    # (what `render.gauge` does), and the difference between them on identical geometry is
    # printed by the suite rather than argued about.
    conv, conv_name = arc_paint(prop)
    if conv is None:
        return (x // SS, y // SS, x // SS + sw, y // SS + sh), \
            f"unknown xigma.arcPaint {conv_name!r}: {' '.join(sorted(ARC_PAINT))}"
    _ramp, bad_ramp = colour_ramp(prop)
    if _ramp is None and bad_ramp is not None:
        return (x // SS, y // SS, x // SS + sw, y // SS + sh), \
            f"unknown xigma.colourRamp {bad_ramp!r}: {' '.join(sorted(COLOUR_RAMPS))}"
    stop = a0 + f * (a1 - a0)
    a, col, ramp_note = a0, None, None
    while a < stop - conv["epsilon"]:
        b = min(a + conv["step"], stop)
        deg = (a + b) / 2 - a0 if conv["sample"] == "middle" else a - a0
        col, ramp_note = arc_colour(prop, deg, a1 - a0, conv)
        draw.arc(box, a, b + conv["overlap"], fill=col, width=thick * SS)
        a = b
    return (x // SS, y // SS, x // SS + sw, y // SS + sh), ramp_note or "no sweep to fill"


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

    `notes["boxes"]` is one entry per row that got drawn: `(kind, what it shows,
    box in panel px, the row's index in `osd.widget`)`.  The index is there because a
    list of *drawn* boxes is not a list of rows - a row whose source has no reading
    contributes nothing to it - and a caller that wants to know which row a point on
    the glass belongs to (the window's canvas, `xigmaui/edit.py:Editor.hit`) has to
    name the file's row, not a position in this list.

    `specials` is the registry for the one added kind, `special`: {name: callable}.  A
    special is a picture that stays code-drawn and takes its position, size and reading
    from the layout - today the clock's readings line, `dual`'s status line and `alpha`'s
    two fan figures and two temperature figures.  It
    exists so those elements can *move* without being baked into PNGs, and the table is
    injected rather than imported here because it is the one place that joins a layout
    kind to a theme drawing, and `themes` is the module that knows both sides.  A name with
    no drawing is
    reported in `notes["missing"]` as `special:<name>`: an unknown name is said, not
    guessed at.

    The `xigma` extension keys a text or data widget may carry - `anchor`,
    `autoFitMax`, `format` - are documented at `draw_text` and `text_for`, each with
    the measured difference between our five and the vendor's files that forced it."""
    W, H = canvas or (obj["width"], obj["height"])
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    notes = {"fonts": {}, "missing": [], "gaps": [], "boxes": []}
    for wi, w in enumerate(obj["osd"]["widget"]):
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
            notes["boxes"].append((kind, prop.get("content") or prop["source"]
                                   if kind == "data" else prop.get("content"),
                                   draw_text(draw, prop, s, face, relayout), wi))
        elif kind == "bar":
            if prop["source"] not in values:
                notes["missing"].append(prop["source"])
                continue
            bar_box, bar_bad = draw_bar(draw, prop, values[prop["source"]])
            if bar_bad:
                notes["missing"].append(bar_bad.split(":", 1)[0])
            notes["boxes"].append(("bar", prop["source"], bar_box, wi))
        elif kind == "arc":
            if prop["source"] not in values:
                notes["missing"].append(prop["source"])
                continue
            box, ramp = draw_arc(draw, prop, values[prop["source"]])
            notes["arc_colour"] = ramp
            if ramp.startswith("unknown "):
                notes["missing"].append(ramp[len("unknown "):].split(":")[0])
            if ramp.startswith("straight"):
                notes["gaps"].append("arc colour, " + prop["source"])
            notes["boxes"].append(("arc", prop["source"], box, wi))
        elif kind == "special":
            name = str(prop.get("name") or "")
            fn = (specials or {}).get(name)
            if fn is None:
                notes["missing"].append(f"special:{name}")
                continue
            # a `special` needs a face like any text row does - both doors build one - so
            # an unresolvable family is said here, in the same words the text kinds use,
            # rather than drawing nothing.  A None box from the door is not an error: it
            # means the drawing had nothing to say (a composite line with no readings),
            # and `notes["missing"]` is for what the file asked for and this machine lacks
            face, fam, path = font_for(prop)
            if face is None:
                notes["missing"].append(f"font:{fam or 'default'}")
                continue
            notes["boxes"].append(("special", name, fn(draw, prop, values), wi))
        elif kind == "line":
            notes["gaps"].append("line colour")
            notes["boxes"].append(("line", prop.get("source") or "line",
                                   draw_line(draw, prop), wi))
    return img.resize((W, H), Image.LANCZOS), notes


def load(path: str) -> dict:
    with open(path) as f:
        return json.load(f)
