"""480x480 RGBA frames for the Connect LCD.

The panel only ever shows a PNG that was uploaded as a media file, so this
module just draws pictures.  Sizes matter: the link is CDC-ACM at 115200 baud
(~11 KB/s of usable payload), so a 24 KB frame like ALPHA's own takes about
two seconds to push.  Flat UI art quantises to a 256-colour palette almost
losslessly, which roughly halves the bytes.
"""
from __future__ import annotations

import glob as _glob
import io
import math
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W = H = 480
SS = 2                       # supersample factor, keeps arcs smooth

BLACK = (0, 0, 0, 255)
OVERLAY = (0, 0, 0, 0)      # transparent canvas: the panel keeps its own layer
WHITE = (255, 255, 255, 255)
CYAN = (0, 229, 255, 255)
GREEN = (0, 230, 118, 255)
AMBER = (255, 196, 0, 255)
RED = (255, 64, 64, 255)
DIM = (150, 170, 180, 255)
TRACK = (120, 200, 220, 255)

# the unfilled part of an arc, for the rings where a pale track would swamp the fill.
# Chosen here, not taken from the vendor: ALPHA's own layouts give `bgColor` to their
# bar widgets (rgba(196,162,255,1), kept below as `A26_TRACK`) and declare no track for
# an arc at all, so the honest claim is only "neutral, so the value's own ramp is the
# colour that moves on the ring".  What *is* measured is the effect on legibility, and
# it is counted where it has to be - over decoded frames of the clips the library ships
# (see `theme_dual`, and docs/limits.md).
ARC_TRACK = (104, 118, 130, 150)

# ---- ink: the colour of the glyphs we draw ----------------------------------
#
# Each theme used to paint its text with a constant chosen at import time.  It
# is a parameter now, because this is the one part of a frame's look this
# project can honestly change: the text is drawn here, on this machine, and
# uploaded as pixels.
#
# What it is *not*: the vendor's themes keep their text colour inside their own
# files, and those colours are not all white.  Counted, over the 23 480x480
# layout files the themes package installs (the same bytes this repository
# carries under themes/alpha/layouts, and `themes.field_census()` re-derives them): 106
# `textColor` values, 9 distinct, 88 of them `rgba(255, 255, 255, 1)`, in 18 of
# the 23 files exclusively and in 5 mixed with greys and near-blacks.  The theme
# ALPHA has selected is one of the exclusively-white ones - 6 of its 6.  That
# colour is read by the panel's firmware from a `.thm`/layout file, and nothing
# in this project sends one, so nothing here changes it (docs/themes.md,
# docs/limits.md, PROTOCOL.md §10).
#
# `INK_DIM` is a design constant, not a measurement: how much darker the lines
# a theme treats as secondary get when a reader picks an ink.  It lives here so
# `tests/test_ink.py::test_dim_ratio_is_pinned` can hold the arithmetic rather than
# the prose about it.
INK_DIM = 0.62

#: spellings that mean "use the theme's own skin"
DEFAULT_INK = ("", "default", "theme default", "theme", "auto")


def parse_ink(value):
    """One entry point for a text colour: CLI flag, socket value, GUI setting.

    Returns an (r, g, b, a) tuple, or None for "the theme's own skin".  Raises
    ValueError in words fit to be shown to a human, because the socket's answer
    and argparse's error are both read by people.

    Accepted: empty, `default`/"theme default"/"auto" (all -> None); `#rgb`,
    `#rrggbb`, `#rrggbbaa`; the names of this module's own palette (`amber`,
    `mint`, `cyan` - the colours the themes actually ship with, so a choice
    made from the GUI's list can be spelled the same way on the command line);
    anything else PIL's colour table names, which is how `rebeccapurple` or
    `rgb(0,230,118)` work; and tuples/lists, which is what this module's own
    defaults and the tests hand in.
    """
    from PIL import ImageColor
    if value is None or isinstance(value, (tuple, list)):
        if not value:
            return None
        try:
            return _argb(tuple(value))
        except ValueError:
            # a tuple can arrive from a hand-written JSON request as well as from
            # Python, and either way the words end up in someone's log, so the
            # message is the same one as for a bad string
            raise ValueError(_ink_help(value)) from None
    text = str(value).strip()
    key = text.lower()
    if not text or key in DEFAULT_INK:
        return None
    named = {"white": WHITE, "black": BLACK, "cyan": CYAN, "green": GREEN,
             "amber": AMBER, "red": RED, "dim": DIM, "track": TRACK,
             "mint": ALPHA_MINT, "label": ALPHA_LABEL}
    if key in named:
        return _argb(named[key])
    try:
        got = ImageColor.getrgb(text)
    except (ValueError, AttributeError):
        raise ValueError(_ink_help(text, named)) from None
    return _argb(got)


def _ink_help(value, named=None) -> str:
    """The one sentence every rejected text colour comes back with.

    It reaches a person twice - argparse's error line on a terminal, and the
    socket's `error` field in the window's log - so it names what to write
    rather than what went wrong internally.
    """
    names = " ".join(sorted(named)) if named else (
        " ".join(sorted((k for k in ("white", "black", "cyan", "green", "amber",
                                     "red", "dim", "track", "mint", "label")))))
    return (f"text colour {value!r} is not something I can read: try #rrggbb "
            f"(like #ff4040), one of {names}, or 'default' for the theme's own")


def _argb(c) -> tuple:
    """Any PIL-shaped colour -> 8-bit RGBA.

    The channel check is not fussiness: `parse_ink` also takes a list or tuple,
    and without it `("r","e","d")` would have been accepted as three channels of
    text and reached PIL's drawer, where it fails far from its cause.
    """
    def ok(v):
        return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255
    if len(c) in (3, 4) and all(ok(v) for v in c):
        return (c[0], c[1], c[2], c[3] if len(c) == 4 else 255)
    raise ValueError(f"not a colour: {c!r}")


def ink_hex(ink) -> str | None:
    """`#rrggbb` for a colour that crossed the socket, or None for 'default'.

    The status and config answers carry the display's ink, and a tuple arrives
    as a JSON array nobody would read.  Hex is what `parse_ink` accepts back, so
    the value round-trips: read it, send it, get the same colour.  The alpha
    channel is dropped, because the glyph's transparency is the theme's doing,
    not the reader's choice.
    """
    if ink is None:
        return None
    r, g, b, _a = _argb(ink)
    return f"#{r:02x}{g:02x}{b:02x}"


def _dim(ink, k: float = INK_DIM) -> tuple:
    """`ink` at `k` of its brightness, alpha kept.

    Straight sRGB multiplication, which is what "dimmer" means on this panel:
    there is no contrast knob on the wire, and blending towards black keeps the
    hue.  The suite pins the arithmetic.
    """
    r, g, b, a = _argb(ink)
    return (round(r * k), round(g * k), round(b * k), a)


def _skin(ink, primary, secondary, accent):
    """The three glyph colours of one theme, reader's override applied.

    `ink=None` keeps the theme's own measured skin - the default, and the
    reason the `alpha` replica still matches what was captured (its text
    measures white, §10).  Any other value paints every glyph with it; the
    lines a theme treats as secondary - `DIM` in dual/clock/bars, the label and
    clock tints in gauge - get the same hue at `INK_DIM`, so changing the ink
    changes the colour without flattening the page.  Arcs, bars and tracks keep
    their own colours either way: they are graphics, and several of those
    colours are measurements.
    """
    if ink is None:
        return primary, secondary, accent
    # `parse_ink`, not `_argb`: a theme can be called straight from Python with
    # `ink="red"` or `ink=(255,0,0)`, and a colour that fails should fail with
    # the sentence this module promises rather than inside a drawer.
    fg = parse_ink(ink)
    return fg, _dim(fg), fg

# ALPHA's own skin, measured off the 65 `.osd` frames captured from its log
# (data/vendor_frames).  Only 4.6 % of its pixels are painted - 9 162 opaque plus
# 10 807 translucent of 230 400 - which is how its picture lets the panel's
# stored background keep playing behind it (PROTOCOL.md §9).
#
#   ring    outer radius 127 about (236, 236), 22 px thick, open at the bottom:
#           260 degrees, from 140 deg clockwise (PIL degrees) over the top
#   fill    opaque, graded cyan (0,247,255) at the low end to mint (0,251,184)
#   track   the same ring unfilled: pale cyan (160,242,245) at alpha 128
#   text    title and digits white, label mint-green, clock mint (0,250,232)
#   scale   its digits read 57 deg C while the tip sits at 58-63 % of the sweep,
#           which puts its temperature scale near 30..75 rather than the 30..90
#           we had assumed - a degree is worth 2.2 % of the arc there, so the
#           same temperature change moves ALPHA's tip twice as far as ours did
ALPHA_TRACK = (160, 242, 245, 128)
ALPHA_COLD = (0, 247, 255, 255)
ALPHA_HOT = (0, 251, 184, 255)
ALPHA_MINT = (0, 250, 232, 255)
ALPHA_LABEL = (0, 245, 130, 255)

_FONT_GLOBS = (
    "/usr/share/fonts/**/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/**/DejaVuSans.ttf",
    "/usr/share/fonts/**/*Bold.ttf",
    "/usr/share/fonts/**/*.ttf",
)
_fonts: dict[tuple, object] = {}


def font(size: int, bold: bool = True):
    """First usable TrueType font for `size` device pixels (bitmap fallback)."""
    key = (size, bold)
    if key not in _fonts:
        pat = _FONT_GLOBS[0] if bold else _FONT_GLOBS[1]
        path = None
        for g in (pat, *_FONT_GLOBS[2:]) if bold else (pat, _FONT_GLOBS[3]):
            try:
                path = next(iter(_glob.iglob(g, recursive=True)), None)
            except OSError:
                path = None
            if path:
                break
        px = max(int(size), 1) * SS
        try:
            _fonts[key] = (ImageFont.truetype(path, px) if path
                           else ImageFont.load_default(px))
        except OSError:
            _fonts[key] = ImageFont.load_default(px)
    return _fonts[key]


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(4))


def heat(t: float, cold=CYAN, hot=RED):
    """Colour for a 0..1 fraction, cyan -> green -> amber -> red."""
    t = min(max(t, 0.0), 1.0)
    if t < 0.5:
        return _lerp(cold, GREEN, t * 2)
    if t < 0.8:
        return _lerp(GREEN, AMBER, (t - 0.5) / 0.3)
    return _lerp(AMBER, hot, (t - 0.8) / 0.2)


def _text(img, xy, s, fnt, fill, anchor="mm"):
    """Draw at device coordinates on the supersampled canvas."""
    ImageDraw.Draw(img).text((xy[0] * SS, xy[1] * SS), s, font=fnt, fill=fill,
                             anchor=anchor)


def _fit_size(draw_or_img, s, max_w, size, bold=True):
    """`_fit_draw` handed an image instead of an `ImageDraw` - the door the five themes
    call.  Accepts either: a probe that walks sizes one string at a time should not have to
    allocate a canvas per call, and both doors have to walk the same loop whatever they are
    handed."""
    d = draw_or_img if hasattr(draw_or_img, "textlength") else ImageDraw.Draw(draw_or_img)
    return _fit_draw(d, s, max_w, size, bold)


def _fit_draw(draw, s, max_w, size, bold=True, mk=None):
    """The largest size <= `size` at which `s` fits in `max_w` panel px, walked on the
    caller's `ImageDraw`: the loop, the step of 2 and the floor of 10 are one function, so
    a picture drawn through a `special` and a picture drawn by a theme cannot end up at two
    different sizes for one string.

    `mk(size)` builds the face for one step of the walk; it defaults to this module's
    `font(size, bold)` so a caller that passes a face factory measures with exactly the
    faces it will draw with.
    """
    mk = mk or (lambda px: font(px, bold))
    while size > 10 and draw.textlength(s, font=mk(size)) > max_w * SS:
        size -= 2
    return size


def _fit(img, s, max_w, size, bold=True):
    """Shrink the font size until the string fits `max_w` device pixels."""
    return font(_fit_size(img, s, max_w, size, bold), bold)


# ------------------------------------------------------------------- arcs --
def arc(img, bbox, start, span, width, colour):
    """One arc segment.  Angles are degrees clockwise from 3 o'clock."""
    ImageDraw.Draw(img).arc(bbox, start, start + span, fill=colour,
                            width=width * SS)


def gauge(img, cx, cy, radius, frac, width=26, track=TRACK, cold=CYAN,
          hot=RED, start=120, sweep=300, span="fill"):
    """Arc gauge with a 300-degree sweep starting at the lower left.

    The unfilled remainder is a faint track.  `span="fill"` gradients the
    colour over the filled part (the stock skin's look), `span="sweep"`
    gradients it across the whole sweep so the colour also encodes value.
    `cold` may be a colour or a ramp function taking 0..1.
    """
    frac = min(max(frac, 0.0), 1.0)
    bbox = [int((cx - radius) * SS), int((cy - radius) * SS),
            int((cx + radius) * SS), int((cy + radius) * SS)]
    arc(img, bbox, start, sweep, width, track)
    filled, acc, step = sweep * frac, 0.0, 3.0
    denom = filled if span == "fill" else sweep
    ramp = cold if callable(cold) else (lambda t, a=cold, b=hot: _lerp(a, b, t))
    while acc < filled - 0.001:
        seg = min(step, filled - acc)
        t = acc / denom if denom else 0.0
        arc(img, bbox, start + acc, seg + 0.4, width, ramp(t))
        acc += seg


def _ink_box_draw(draw, s, f, cx, y, anchor="ma"):
    """`ink_box` on a caller's `ImageDraw`, so a probe and a theme measure the same ink
    without one of them allocating a canvas."""
    box = draw.textbbox((0, 0), s, font=f, anchor=anchor)
    return [box[0] / SS + cx, box[1] / SS + y, box[2] / SS + cx, box[3] / SS + y]


def ink_box(img, s, f, cx, y, anchor="ma"):
    """Where a string's pixels land, in panel px, drawn at (cx, y).

    PIL reports text in its own supersampled space and includes the glyph's
    bearings, so this is the ink - what shows on the glass - not the em box
    `_fit` measures against.
    """
    return _ink_box_draw(ImageDraw.Draw(img), s, f, cx, y, anchor)


def arc_clear(box, cx, cy, r_in, r_out, start, sweep):
    """Clearance of an ink box to a painted arc band, in panel px.

    Positive means the ink lands on top of the arc, so a layout is only clean
    when this is negative, and the number says by how much it misses.  Samples
    walk the box's four edges rather than just its corners, because the hole's
    boundary is a curve.  A sample outside the arc's angular range counts as
    missing it, penalised by the arc-length distance to the nearest end of the
    arc - ink in the ring's open mouth is free, unless it crowds an end.
    """
    x0, y0, x1, y1 = box
    worst = -1e9
    for t in [i / 40.0 for i in range(41)]:
        for px, py in ((x0 + (x1 - x0) * t, y0), (x0 + (x1 - x0) * t, y1),
                       (x0, y0 + (y1 - y0) * t), (x1, y0 + (y1 - y0) * t)):
            dist = math.hypot(px - cx, py - cy)
            ang = (math.degrees(math.atan2(py - cy, px - cx)) - start) % 360.0
            off = 0.0 if ang <= sweep else min(ang - sweep, 360.0 - ang)
            off = math.radians(off) * dist
            worst = max(worst, min(dist - r_in, r_out - dist) - off)
    return worst


#: How far the arc fit keeps a figure's ink out of the stroke band, panel px.  Named
#: rather than written at the two call sites because `tests/test_specials.py` measures the
#: ring painter's own resampling tail - the faint pixels LANCZOS leaves past the stroke's
#: edge, inside the hole - and holds this number above it: below that, a reading sized by the
#: rule could sit on top of the gauge it belongs to (that file's `TemperatureRows`).
ARC_FIT_GAP = 3.0


def _fit_arc_draw(draw, strings, cx, cy, y, r_in, r_out, start, sweep, size,
                  bold=True, gap=ARC_FIT_GAP, mk=None):
    """`_fit_arc`'s walk on a caller's `ImageDraw`, so a theme and a `special` row
    measuring the same strings against the same ring cannot land on two sizes."""
    mk = mk or (lambda px: font(px, bold))
    while size > 10 and max(
            arc_clear(_ink_box_draw(draw, s, mk(size), cx, y),
                      cx, cy, r_in, r_out, start, sweep) for s in strings) > -gap:
        size -= 2
    return size


def _fit_arc(img, strings, cx, cy, y, r_in, r_out, start, sweep, size,
             bold=True, gap=ARC_FIT_GAP):
    """Largest size <= `size` where every string keeps `gap` px off the arc.

    A joint rule: every string in the set is measured and one size comes out,
    so the two columns are always the same size and weight and a three-digit
    reading takes both readings down together instead of leaving one bigger
    than the other.  The limit is the ring's hole rather than a width, and it
    is measured as ink at the anchor the theme actually draws at.
    """
    return _fit_arc_draw(ImageDraw.Draw(img), strings, cx, cy, y, r_in, r_out,
                         start, sweep, size, bold, gap)


def temp_colour(t, lo, mid, hi, cold=GREEN, warm=AMBER, hot=RED):
    """Green at `lo` degrees, amber at `mid`, red at `hi`, clamped outside.

    Three stops rather than `heat()`'s four because the point is a temperature
    the person can read off the colour: cool is green, warm is yellow/orange,
    hot is red, and there is no cyan stage in between.
    """
    t = min(max(t, lo), hi)
    if t <= mid:
        return _lerp(cold, warm, (t - lo) / (mid - lo))
    return _lerp(warm, hot, (t - mid) / (hi - mid))


def temp_arc(img, cx, cy, value, lo, mid, hi, radius, width, track,
             start=120, sweep=300):
    """Gauge ring for a temperature: 30..100 degrees, colour graded by degree.

    The fill position and the colour both carry the value, so the arc says the
    same thing at a glance from across the room and in a photograph.  A missing
    reading draws nothing: a gauge would imply a number, and the reading next to
    it already says `--\u00b0C`.
    """
    if value is None:
        return None
    frac = (min(max(value, lo), hi) - lo) / (hi - lo)
    gauge(img, cx, cy, radius, frac, width=width, track=track, start=start,
          sweep=sweep, span="sweep",
          cold=lambda t: temp_colour(lo + t * (hi - lo), lo, mid, hi))
    return frac


def pct_pair(part: dict, numerator: str, denominator: str):
    """One pair of reported fields as a percentage, or None where there is no pair.

    Both of `bars`'s memory rows are formed this way, and until 2026-11-09 they were not
    formed *alike*: the GPU row required its numerator to be truthy, so a reading of exactly
    0 dropped the row, while the memory row kept it - and it read `mem["used"]` outright, so
    a dict reporting a total with no used raised `KeyError` inside the frame loop instead of
    drawing a hole.  Neither of those is a shape a layout file can describe, so the rule is
    stated once here (the source table calls it from the other door, and both doors are
    measured against each other by `tests/test_export_parity.py`).  A zero numerator is a
    reading: the row exists, at nothing filled.
    """
    part = part or {}
    den = part.get(denominator)
    val = part.get(numerator)
    if not den or val is None:
        return None
    return val / den * 100


def bar(img, x, y, w, h, frac, colour, bg=(40, 46, 50, 255)):
    d = ImageDraw.Draw(img)
    x, y, w, h = int(x * SS), int(y * SS), int(w * SS), int(h * SS)
    frac = min(max(frac, 0.0), 1.0)
    r = min(h // 2, int(w * max(frac, 0.02)) // 2)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    if frac > 0.01:
        d.rounded_rectangle([x, y, x + int(w * frac), y + h], radius=r,
                            fill=colour)


def _now():
    """This frame's idea of "now", as a struct_time - the one hook every clock line uses.

    A frame's time and date have to come from one instant, and a preview, a suite check or
    a replay wants to say what that instant is.  Patching `clock_str` alone used to leave
    the `clock` theme's date line reading the wall clock by itself, so a preview could pair
    a recorded `00:25:16` with the date of whatever moment it happened to render - and off
    machine, `time.localtime()` follows the reader's zone: the same epoch milliseconds read
    at UTC say `Friday 07 November 2026` where a UTC+02:00 render showed `Saturday 08
    November 2026`.  Everything time-shaped in a theme goes through here, so one patch
    moves the whole frame.
    """
    return time.localtime()


def date_str(now=None, fmt="%A %d %B %Y"):
    """The `clock` theme's date line, from the same instant its time line comes from."""
    return time.strftime(fmt, now or _now())


def clock_str(now=None, fmt24=True):
    return time.strftime("%H:%M:%S" if fmt24 else "%I:%M %p", now or _now())


def _title(img, s, y=22, size=24, colour=WHITE, x=240, width=440):
    """The centred heading.  `x` and `width` are parameters because one theme names both -
    `bars`, whose title is a row in a layout file - and the defaults are the values every
    theme has always drawn with."""
    _text(img, (x, y), s, _fit(img, s, width, size), colour)


# ----------------------------------------------------------------- themes --
def theme_gauge(m, title="Smart Display", clock=True, label="CPU TEMP",
                cold=30.0, hot=75.0, gradient="stock", bg=OVERLAY,
                source="temperature", ink=None):
    """The stock skin, drawn where ALPHA draws its own: arc, digits, label, clock.

    Geometry and colours come from ALPHA's captured frames (see the ALPHA_*
    constants); `source` says what the arc follows.  `temperature` is what
    ALPHA uses, and the honest caveat is that a desktop CPU idles inside a
    degree or two, so the tip barely moves - over the 65 vendor frames, at
    their machine's idle, the tip travelled 14 degrees in 43 seconds.  `load`
    tracks CPU busy percent instead, which does move every second.
    """
    img = Image.new("RGBA", (W * SS, H * SS), bg)
    fg, mid, acc = _skin(ink, *SKIN["gauge"])
    cpu = m.get("cpu") or {}
    val = cpu.get(source) if source in ("temperature", "load") else None
    if val is None:
        val = cpu.get("temperature")
        source = "temperature"
    if source == "load" and (cold, hot) == (30.0, 75.0):
        cold, hot = 0.0, 100.0              # the arc is a percent scale then
    frac = 0.0 if val is None else (val - cold) / (hot - cold)
    ramp = (lambda t: heat(t, CYAN, RED)) if gradient == "heat" \
        else (lambda t: _lerp(ALPHA_COLD, ALPHA_HOT, t))
    gauge(img, 236, 236, 127, frac, width=22, track=ALPHA_TRACK, cold=ramp,
          start=140, sweep=260, span="sweep")
    if title:
        _title(img, title, y=19, size=20, colour=fg)
    if val is not None:
        s = (f"{round(val)}\u00b0C" if source == "temperature" else f"{val:.0f}%")
        _text(img, (236, 236), s, _fit(img, s, 165, 52), fg)
    if label:
        _text(img, (236, 318), label, font(14), mid)
    if clock:
        _text(img, (236, 458), clock_str(), font(22), acc)
    return img.resize((W, H), Image.LANCZOS)


def theme_dual(m, title="CPU  /  GPU", clock=True, cold=30.0, hot=90.0,
               bg=OVERLAY, ink=None):
    """Two arc gauges side by side, plus a load bar and the clock."""
    img = Image.new("RGBA", (W * SS, H * SS), bg)
    fg, mid, acc = _skin(ink, *SKIN["dual"])
    cpu = m.get("cpu") or {}
    gpu = m.get("gpu") or {}
    for cx, dev, name in ((128, cpu, "CPU TEMP"), (352, gpu, "GPU TEMP")):
        t = dev.get("temperature")
        frac = 0.0 if t is None else (t - cold) / (hot - cold)
        # `track=ARC_TRACK`, the neutral ring this module already uses for alpha's
        # arcs, and not the module default `TRACK` (120,200,220,255) - a pale cyan
        # picked at import time with nothing measured behind it.  Measured, not
        # guessed: one mid-loop frame of four clips the vendor ships, composited
        # under this theme's layer, sampling the ring at its mid-radius over 240
        # points and averaging the luma of the filled part against the unfilled one
        # (2026-11-07, off screen - this is a picture measurement, not a glass one):
        #
        #   background (mean luma)      today's TRACK      neutral track
        #   Theme_30.mp4   (4.0)         7.4 / 6.1          100.4 / 109.0
        #   theme_52.mp4   (11.5)        7.4 / 6.1          101.9 / 105.0
        #   3.mp4          (56.3)        7.3 / 5.5           67.1 / 81.3
        #   Theme_07.mp4   (180.7)       7.0 / 4.8           27.3 / 20.1
        #
        # (two figures per row: the CPU ring at 68 % of the sweep and the GPU ring at
        # 23 %.)  Seven luma out of 255 is the whole complaint: a green-yellow tip on a
        # near-white ring is not a meter, and on the bright clip the fill is *dimmer*
        # than its own track.  The neutral carries 20-109 depending on how bright the
        # background is, and that last row is the honest limit of a half-transparent
        # track over a bright clip - which is what the scrim is for (docs/gui.md), not
        # a colour choice.
        gauge(img, cx, 228, 96, frac, width=20, cold=heat, span="sweep",
              track=ARC_TRACK)
        if t is not None:
            s = f"{round(t)}"
            _text(img, (cx, 222), s, _fit(img, s, 120, 52), fg)
        _text(img, (cx, 298), name, font(15), mid)
    if title:
        _title(img, title, y=26, colour=fg)
    util = cpu.get("load")
    if util is not None:
        bar(img, 60, 340, 360, 14, util / 100.0, heat(util / 100.0))
        _text(img, (240, 372), dual_status_line(m), font(17), mid)
    if clock:
        _text(img, (240, 444), clock_str(), font(30), acc)
    return img.resize((W, H), Image.LANCZOS)


def clock_readings_line(m: dict) -> str:
    """The third line of `clock`: both temperatures and the mean of the fan rows.

    The empty string is what keeps the line off the panel when this machine answers
    none of the three, rather than drawing a row of dashes.

    Named instead of inlined for the export plan (docs/theme-editor.md): this line is
    a composite - a fan *average* of a list - so no single vendor `source` stands for
    it, and an exported `clock` layout places it as a `special` that draws the text
    built here.  One builder, two doors: the code theme and the layout cannot drift
    apart in what they say, because they read the same string.
    """
    cpu = (m.get("cpu") or {}).get("temperature")
    gpu = (m.get("gpu") or {}).get("temperature")
    parts = []
    if cpu is not None:
        parts.append(f"CPU {round(cpu)}\u00b0C")
    if gpu is not None:
        parts.append(f"GPU {round(gpu)}\u00b0C")
    fans = [f.get("value") for f in m.get("fans") or [] if f.get("value")]
    if fans:
        parts.append(f"{round(sum(fans) / len(fans))} RPM")
    return "    ".join(parts) if parts else ""


def dual_status_line(m: dict) -> str:
    """`dual`'s middle line: the CPU load, and memory in GB when there is memory to say.

    Pulled out of `theme_dual` for the same reason as `clock_readings_line`, and with the
    same consequence: the string is a composite of three readings (`cpu.load`,
    `memory.used`, `memory.total`) and the padding between the two halves is four spaces
    inside one string, so no vendor `source` stands for it.  An exported `dual` layout
    places it as a `special` and draws the text built here - one builder, two doors, so
    what the code theme says and what the layout says cannot drift apart.

    The empty string means "nothing to say": `theme_dual` draws the line only when a load
    reading exists, and a layout with no value for it reports it as missing rather than
    painting a bare `%`.
    """
    util = (m.get("cpu") or {}).get("load")
    if util is None:
        return ""
    mem = m.get("memory") or {}
    line = f"CPU {util:.0f}%"
    if mem.get("total"):
        line += (f"    {mem.get('used', 0) // 1024} / "
                 f"{mem.get('total', 0) // 1024} GB")
    return line


def theme_clock(m, clock=True, big=140, date=True, bg=OVERLAY, ink=None):
    """Mostly a clock: huge time, one line of readings underneath.

    `clock=False` drops the big time line and leaves the date and the readings line where
    they are - the layout does not re-flow, because the two remaining lines each have their
    own y band and nothing moves into the gap.  That rule was in the signature and not in
    the body for most of this project's life: `--no-clock` reached this theme through
    `_theme_kwargs` and did nothing at all.  That is the kind of gap a knob table hides and
    a map measured against the drawing cannot (`tools/knobmap.py`), and the section that runs
    it now holds this pair at zero differing pixels - the code drawing drops the line, the
    generated layout answers the same option by deleting its `Time` row.  On the glass this
    is a frame change for anyone using the flag, so it belongs with the bench pass in
    docs/theme-editor.md's stage 6.
    """
    img = Image.new("RGBA", (W * SS, H * SS), bg)
    fg, mid, acc = _skin(ink, *SKIN["clock"])
    if clock:
        t = clock_str()
        # One budget for every line in this theme: 440 panel px, which is what the big
        # time line already used and what the other two did not.
        _text(img, (240, 190), t, _fit(img, t, 440, big), fg)
    if date:
        date_s = date_str()
        # `Wednesday 31 December 2099` measures 382.5 panel px at 22, so the date
        # fits today and the budget is insurance for the day it does not - a locale
        # with a longer month name, which is the `Week_en`/`Time_hh:mm` format gap
        # docs/limits.md still writes down as unfilled.
        _text(img, (240, 286), date_s, _fit(img, date_s, 440, 22), mid)
    line = clock_readings_line(m)
    if line:
        # The line that used to run off the glass.  At font 26, `CPU 57°C  GPU 47°C
        # 1957 RPM` - the pinned readings every documented preview uses - measures
        # 494.2 panel px against a 480 px panel: 14.2 px over, 7.1 at each end.  The
        # worst realistic line, `CPU 100°C  GPU 100°C  12345 RPM`, measures 548.5:
        # 68.5 px over.  Drawn at that size it reaches both canvas edges (ink bbox x
        # 0.0..480.0, i.e. clipped at both ends: the "C" of "CPU" and the last "M" of
        # "RPM" are not on the picture).  Fitted to the same 440 px budget the time
        # line has always had, it lands at x 29..450 (font 22) for the pinned set and
        # 27..452 (font 20) for the worst one - 421 and 425 px of ink in a 480 px
        # panel.  Counted by drawing the string and reading the alpha channel's bbox,
        # 2026-11-07; `tests/test_gauges.py` crops each of the theme's three lines to its own
        # y band and fails if any of them touches a panel edge.
        _text(img, (240, 358), line, _fit(img, line, 440, 26), acc)
    return img.resize((W, H), Image.LANCZOS)


#: `bars`'s geometry, named so that a generated layout file can read these numbers instead
#: of repeating them - the same reason `alpha`'s recipe reads the `A26_*` constants.  The
#: block runs from `BARS_Y0` down `BARS_SPAN` px; a row is its label at `BARS_LBL_X`
#: (left-middle), a value right-aligned at `BARS_VAL_X`, and a meter `BARS_BAR_DY` below the
#: row's centre, `BARS_BAR_WH` in size.  `BARS_SLOTS` fan rows are reserved on every machine,
#: and that is why the pitch no longer moves between boxes - see the docstring.
#:
#: `BARS_BAR_DY` and `BARS_BAR_WH` are a pair, and the vertical budget is what sets them: at
#: a pitch of 32 the theme's own faces lay 16 ink rows down for label and number, which leaves
#: 15 rows of air for the meter - so a track 10 px tall (12 of ink once the supersampled edge
#: is downsampled) hung 5 rows *inside* the next row's text, and the block read as a stack of
#: smudged lines at any preview size below the glass.  `tests/test_bars_rows.py`'s
#: `TheRowsDoNotRunIntoEachOther` measures both bands from the shipped painter - once with the
#: meters suppressed, once as shipped - and holds the clearance positive on each side and the
#: meter closer to its own label than to the row under it, because a bar that sits nearer the
#: line below reads as that line's separator rather than as this row's meter.
#: `BARS_SPAN` moved 320 -> 352 when the drive row went in (2026-11-14), and the reason is
#: arithmetic the clearance check forced: the pitch is `BARS_SPAN // len(BARS_ROWS)`, so at 320
#: ten rows gave 32 px and eleven give 29 - and at 29 the shipped meter sat **1 px** from the
#: text band of the row below it, nearer that row's label than its own, i.e. a bar reading as
#: the next line's separator.  Two ways out were measured, not chosen: thin the meter to
#: (DY 11, height 4), which clears by 2 px - at the floor - and costs track thickness on the
#: glass; or give the block the room it already had below it.  The block ends at y=409 and the
#: clock line's own ink begins at y=440 (measured, 31 px of air), so the span grows and the
#: pitch, the 6 px track and the clearance stay exactly as the ten-row layout had them: 3 px
#: above a meter, 4 px below.
BARS_Y0, BARS_SPAN = 72, 352
BARS_ROW_MIN, BARS_ROW_MAX = 28, 56
BARS_LBL_X, BARS_VAL_X = 28, 452
BARS_BAR_X, BARS_BAR_DY, BARS_BAR_WH = 28, 12, (424, 6)
BARS_LBL_F, BARS_VAL_F, BARS_CLOCK_F = 18, 20, 28
BARS_CLOCK_XY, BARS_CLOCK_ANCHOR = (240, 452), "mm"
BARS_TITLE_TEXT, BARS_TITLE_X, BARS_TITLE_Y = "SYSTEM MONITOR", 240, 30
BARS_TITLE_F, BARS_TITLE_W = 24, 440        # the ceiling and the width `_fit` walks
BARS_SLOTS = 4


def theme_bars(m, clock=True, bg=OVERLAY, ink=None):
    """Row per reading with a meter: temps, load, memory, and four fan slots.

    Two rules here exist so this theme can be a layout file at all, and both were decided
    2026-11-08 with the measurement written down next to them (docs/theme-editor.md,
    docs/limits.md).

    * The fan rows are four **reserved slots**, taken by position - `fans[0]` through
      `fans[3]` - rather than one row per fan this box happens to report.  So the row list
      has the same length on a machine with six fans and on one with none, and the pitch
      below stops depending on what `sensors` found.
    * A row with no reading **keeps its place**: its number and meter are not drawn, and the
      advance still happens.  That is what the 27 library layouts do, and it is the rule
      docs/themes.md states as "a hole that says what it is, rather than a zero that reads as
      a measurement".
    * A row's **label belongs to its subject, not to its reading**: `BOARD` is drawn when the
      box has a board-temperature metric to report on, whatever that metric answers, and a fan
      slot's name is drawn only where `sensors` reported a fan at that position.  That is the
      same split the layout file makes - a literal `text` row for the six fixed labels, a
      `data` row on `Fan N Name` for the four slots - and it is what lets one drawing and one
      file agree at every reading instead of only at the complete ones.

    What that costs on the glass is stated rather than left to be noticed: when a reading is
    missing, the rows under it no longer close up.  Before this, the pitch was divided out of
    the rows the theme *considered* while `y` advanced only for the rows that drew - measured
    at readings where 3 of the 6 fixed rows answered, the fourth row of the list was drawn in
    the third place, y=178 - and no static file could say where such a row goes, because the
    answer moved with the box.  A file with literal `x,y` per row needs a theme that puts a
    row where the file says it is.
    """
    img = Image.new("RGBA", (W * SS, H * SS), bg)
    fg, mid, acc = _skin(ink, *SKIN["bars"])
    cpu = m.get("cpu") or {}
    gpu = m.get("gpu") or {}
    mem = m.get("memory") or {}
    board = m.get("motherboard") or {}
    ram = pct_pair(mem, "used", "total")
    gm = pct_pair(gpu, "memoryUsage", "dedicatedTotal")
    # (label, reading, scale, the reading's shape, whether the row has a subject at all).
    # The subject matters because a label belongs to it and a number belongs to the reading:
    # the six fixed rows are about metrics this machine has (a `BOARD` row exists even when
    # this box's sensors answer nothing for it), while a fan slot exists only if `sensors`
    # reported a row at that position.  Same split the layout file makes - a literal `text`
    # row for the fixed labels, a `data` row on `Fan N Name` for the slots - which is what
    # lets one drawing and one file agree at every reading.
    rows = [("CPU", cpu.get("temperature"), 30, 90, lambda v: f"{v:.0f}\u00b0C", True),
            ("GPU", gpu.get("temperature"), 30, 90, lambda v: f"{v:.0f}\u00b0C", True),
            ("BOARD", board.get("temperature"), 25, 80,
             lambda v: f"{v:.0f}\u00b0C", True),
            # the drive the capacity numbers describe: `disk.temperature`, the same scalar,
            # not `drives[0]` - see `themes.BARS_DISK_ROWS` for why one row may not mix a
            # positional label with a non-positional reading
            ("DISK", (m.get("disk") or {}).get("temperature"), 25, 80,
             lambda v: f"{v:.0f}\u00b0C", True),
            ("LOAD", cpu.get("load"), 0, 100, lambda v: f"{v:.0f}%", True),
            ("RAM", ram, 0, 100,
             lambda v: f"{mem.get('used', 0) // 1024} GB", True),
            ("VRAM", gm, 0, 100,
             lambda v: f"{gpu.get('memoryUsage', 0) // 1024} GB", True)]
    fans = m.get("fans") or []
    for slot in range(BARS_SLOTS):
        fan = fans[slot] if slot < len(fans) else None
        rows.append((str((fan or {}).get("name") or f"FAN {slot + 1}")[:10],
                     (fan or {}).get("value"), 0, 3000, lambda v: f"{round(v)}",
                     fan is not None))
    _title(img, BARS_TITLE_TEXT, x=BARS_TITLE_X, y=BARS_TITLE_Y,
           size=BARS_TITLE_F, width=BARS_TITLE_W, colour=fg)
    d = ImageDraw.Draw(img)
    y, span = BARS_Y0, BARS_SPAN
    row_h = min(BARS_ROW_MAX, max(BARS_ROW_MIN, span // max(len(rows), 1)))
    for name, val, lo, hi, fmt, subject in rows:
        if subject:                             # the label belongs to the row's subject
            d.text((BARS_LBL_X * SS, y * SS), name, font=font(BARS_LBL_F), fill=mid,
                   anchor="lm")
        if val is not None:                     # the number and the meter to the reading
            d.text((BARS_VAL_X * SS, y * SS), fmt(val), font=font(BARS_VAL_F), fill=fg,
                   anchor="rm")
            bar(img, BARS_BAR_X, y + BARS_BAR_DY, BARS_BAR_WH[0], BARS_BAR_WH[1],
                (val - lo) / (hi - lo), heat((val - lo) / (hi - lo)))
        y += row_h                              # ...and the rest of the block stays put
    if clock:
        _text(img, BARS_CLOCK_XY, clock_str(), font(BARS_CLOCK_F), acc,
          anchor=BARS_CLOCK_ANCHOR)
    return img.resize((W, H), Image.LANCZOS)


# --------------------------------------------- ALPHA's own selected theme ---
#
# `theme_alpha` redraws the theme ALPHA currently has picked and adds things
# that theme does not have: GPU temperature beside the CPU temperature, the
# system clock along the bottom, two fan figures, and a gauge arc around each
# of the two temperatures.
#
# Which theme: Windows AppData/Roaming/alpha/store.json says
# devicesInfo.<sn>.currentThemeId = 1785506775818, which is presetTheme[26],
# and currentThemeBg = media/background/Theme_25.mp4.  Named exactly since
# 2026-11-07: pairing the store's 27 presetTheme entries with the 27 .thm files
# the installer ships (widget properties compared) is 27 of 27 one-to-one, and
# entry 26 is the vendor's theme 1757491589871 - the store re-ids the library at
# install time.  That theme ships with theme_50.mp4; the Theme_25.mp4 here is a
# background the app changed on its own (changeThemeBgBySn).  The layout is
# themes/alpha/layouts/480X480/1757491589871.json.  Its eight widgets, as
# stored (480x480 canvas, all coordinates device pixels, every text colour
# rgba(255,255,255,1)):
#
#   CPU TEMP       text  font  32 bold   110, 80
#   CPU Temperature     data  font 100 bold   106,120
#   CPU USED       text  font  20        100,300   CPU Usage data font 32 320,290
#   CPU Usage      bar  100,330   280 x 10
#   GPU USED       text  font  20        100,370   GPU Usage data font 32 322,362
#   GPU Usage      bar  100,400   280 x 10
#
#   both bars: startColor rgba(192,66,255,1) -> endColor rgba(143,78,255,1) over
#   a track of bgColor rgba(196,162,255,1), minValue 0, maxValue 100, type 3
#
# The anchor convention is read off the app's own rendered preview of this
# theme, media/foreground/1757491589862.png, which is the same eight widgets
# drawn with sample values.  In it both bars measure exactly 280 x 10 at
# (100,330) and (100,400) - a bar's (x, y) is its track's top-left - and the ink
# of a text widget starts a few pixels under its declared y: font 32 at y=80
# inks y 85-107, font 100 at y=120 inks y 132-210, font 32 at y=290 inks y
# 294-316.  So (x, y) is the top of the em box, which is Pillow's "la" anchor.
# The same preview fixes the formats: a two-digit temperature with the degree
# sign inline, and usage as `11%` and `2%`, both inking from their declared x
# (323-380 for `11%` at x=320, 322-366 for `2%` at x=322) - left-aligned on the
# anchor, not on the bars' right edge.  Those two samples also say what the bars
# mean: 31 of 280 columns painted on the CPU bar, 6 of 280 on the GPU bar, i.e.
# the fill is percent x 2.8 px, exactly the minValue 0 / maxValue 100 range the
# JSON declares.
#
# Four deliberate deviations, all forced by the additions:
#   * the temperature pair.  The vendor's single reading is font 100, and two
#     readings at 100 do not fit the panel (262 px each, 524 plus a gutter out
#     of 480), so both readings are drawn at one shared size chosen by
#     `_fit_arc` - measured 58 for two-digit values, 46 when a three-digit one
#     appears - under two labels sized from the vendor's own 32, and each pair
#     inside a gauge arc of its own.  See A26_T*, A26_RING_* and A26_ARC_*
#     below for the measured geometry.
#   * the arcs themselves.  No preset theme of theirs gauges a text widget, so
#     the ring's shape is borrowed from the vendor's own skin - measured off its
#     captured frames at one-degree steps: 269 degrees of solid ink from 136 deg
#     to 45, a 23 px stroke across radius 109-132 (PROTOCOL §7).  We draw 260
#     degrees from 140: the same open-bottomed shape, ends 4-5 deg short of
#     theirs, a 12 px stroke across radius 85-97, and a 100 degree mouth instead
#     of their 91 because ours carries the fan figures.  The scale is ours: 30 to
#     100 degrees C, the colour graded green through amber to red along the sweep.
#   * `°C` is drawn with a real degree sign; the captured frames of ALPHA's skin
#     show the same inline form.
#   * the additions themselves: no preset theme of theirs carries a clock, a fan
#     reading or a GPU temperature, so those have no vendor geometry and are
#     placed here in the vendor's style - the two fan figures under their own
#     temperature rather than one line between them.
#
# DejaVu is not the vendor's typeface, so ink lands a few pixels off theirs at
# the same declared size: the preview's `CPU TEMP` inks y 85-107 and x 111-293,
# ours y 83-111 and x 109-293 - the right edge matches to the pixel, ours is 3 px
# higher and 4 px taller.  Same for the bars, which are geometry not type: both
# measure exactly 280 x 10 at (100,330) and (100,400).
A26_WHITE = (255, 255, 255, 255)
A26_BAR_A = (192, 66, 255, 255)            # startColor
A26_BAR_B = (143, 78, 255, 255)            # endColor
A26_TRACK = (196, 162, 255, 255)           # bgColor


def hbar(img, x, y, w, h, frac, a=A26_BAR_A, b=A26_BAR_B, track=A26_TRACK):
    """Square-ended bar, gradient across the filled part, track showing after.

    `bar()` rounds its ends and has no gradient; the stock theme's bars are
    square with a left-to-right gradient, measured off its own preview.
    """
    frac = min(max(frac, 0.0), 1.0)
    d = ImageDraw.Draw(img)
    x, y, w, h = int(x * SS), int(y * SS), int(w * SS), int(h * SS)
    d.rectangle([x, y, x + w, y + h], fill=track)
    n = int(w * frac)
    for i in range(n):
        d.rectangle([x + i, y, x + i + 1, y + h],
                    fill=_lerp(a, b, i / max(n - 1, 1)))


def _pct(value):
    return "--%" if value is None else f"{round(value)}%"


def _deg(value):
    return "--\u00b0C" if value is None else f"{round(value)}\u00b0C"


def cpu_temp_text(m) -> str:
    """The CPU column's figure as `alpha` draws it: `57\u00b0C`, or `--\u00b0C` when this
    machine has no reading.

    Named for the export plan (docs/theme-editor.md), with the reason `clock_readings_line`
    already carries: the two columns are one drawing sized jointly against the rings, so a
    layout places them as a `special` and draws the strings built here.  One builder, two
    doors, so the code theme and the file cannot say two different things about the same
    reading.
    """
    return _deg((m.get("cpu") or {}).get("temperature"))


def gpu_temp_text(m) -> str:
    """The GPU column's figure: the same shape, read off the card's temperature."""
    return _deg((m.get("gpu") or {}).get("temperature"))


# The temperature pair: two equal columns, each a label over its value, each
# inside a gauge arc of its own.
#
# The vendor's theme has one reading, and its two lines define the style: the
# `CPU TEMP` label is Arial 32 bold at (110, 80) and the `CPU Temperature` value
# is Arial 100 bold at (106, 120) (store.json, presetTheme[26]).  A GPU reading
# is ours to place, and both at 100 is physically impossible: "47°C" at font 100
# measures 262 px in our font, so the pair needs 524 px plus a gutter out of the
# panel's 480.  Equal treatment of the two readings is the choice made here;
# there is no vendor geometry for a second temperature to copy.
#
# The arcs are ours too - no preset theme of theirs puts a gauge around a text
# widget - and they are what sizes the readings now, because a reading has to
# fit inside the ring's hole:
#
#   ring    centre x 124 and 356 (the column centres, 232 apart), cy 158, outer
#           radius 97, stroke 12 px: boxes x 27-221 and 259-453 with a 38 px
#           gutter, y 61-255.  97 is near the ceiling - two rings cannot
#           overlap, so the radius stays under 116 - and at 97 each column keeps
#           a 27 px panel margin, with room under the ring for the fan figures
#           before the usage block's ink at y 294.
#   extent  260 degrees from 140 degrees, open at the bottom.  The vendor's own
#           skin draws the same shape, measured at one-degree steps on its
#           captured frame: solid ink 136 deg through the top to 45 (269 deg),
#           91 deg open.  Ours starts 4 deg later and stops 5 deg earlier, so
#           the mouth is 100 deg wide - enough for the fan figures, which the
#           vendor's ring has no room for because its digits fill it.
#   value   the joint fit is now against the hole rather than a width, and the
#           widest string either column can produce still decides it for both.
#           Measured with `_fit_arc` at these anchors: 58 for two-digit values
#           ("47°C" inks 152 px, x 48-200, y 138-183, clearing the arc by
#           4.5 px) and 46 when a three-digit one appears ("100°C" inks the same
#           152 px, y 136-171).  Those keep the vendor's proportion: in its
#           captured frames the digits inside its ring ink 53 px tall against an
#           inner radius of 109 (data/vendor_frames: white ink y 210-262, x
#           159-326), a ratio of 0.49; ours ink 44 px in an 85 px hole, 0.52.
#   label   22, from the vendor's 32 as the ceiling: at 32 "CPU TEMP" inks 185
#           px and its corners land 5 px on top of the arc, and 22 is the
#           largest size that clears the stroke by 3 px (inks x 61-187, y
#           108-124).
#   fan     one figure per column, sitting in the ring's open mouth: ink y
#           250-265 at font 20, which is 29 px clear of `CPU USED`'s ink at 294.
A26_TLBL_TEXT = ("CPU TEMP", "GPU TEMP")   # the two labels, in column order.  Named
                                           # because both are joint-sized against the
                                           # ring: two strings measured together, one
                                           # size out, so a file or a theme that said
                                           # them separately could land on two sizes
A26_TLBL_F = 32                      # label size ceiling: the vendor's own
A26_TVAL_F = 74                      # value size ceiling: what the pair used
                                     # before the rings went in
A26_TCOL_X = (124, 356)              # column centres, symmetric about 240
A26_TLBL_Y, A26_TVAL_Y = 104, 128    # ink anchors, inside the ring
A26_RING_R, A26_RING_W, A26_RING_Y = 97, 12, 158
A26_ARC_START, A26_ARC_SWEEP = 140.0, 260.0
# the gauge's stated span, and the temperature where the ramp reaches full
# amber: below that it climbs green to amber, above it amber to red, and a
# reading past 100 can push the tip no further, so the colour clamps with it
A26_ARC_LO, A26_ARC_MID, A26_ARC_HI = 30.0, 62.0, 100.0
A26_ARC_TRACK = ARC_TRACK             # the unfilled part: neutral, so the
                                      # green-to-red fill is the only colour
                                      # moving on the ring (the constant and its
                                      # note live up with the other inks)
A26_FAN_X = A26_TCOL_X               # one fan figure per column, each under its
                                    # own temperature, not one line between them
A26_FAN_Y = 246
A26_FAN_MAX_W = 200                  # ink budget per figure: measured 192 px
                                     # for `CPU FAN 2400 RPM` at font 20
A26_FAN_F, A26_FAN_MIN = 24, 16      # size range; both figures share one size,
                                     # chosen from the wider of the two, and it
                                     # is never pushed under 16
# the two usage bars, and the one reason they are named here instead of written
# inline: `xigma.barPaint: hbar` in a layout file claims to paint *this* bar -
# square ends, `A26_TRACK` showing for the whole declared rect, the fill coloured
# one device column at a time - and the only answer that settles that claim is a
# picture-by-picture diff against `hbar` at its own geometry.  The geometry comes
# from ALPHA's captured frames: both bars ink exactly 280 x 10 px, at (100, 330)
# and (100, 400), their left edges aligned under their own `CPU USED`/`GPU USED`
# labels (see the note above `theme_alpha`).
A26_BAR_XY = ((100, 330), (100, 400))
A26_BAR_WH = (280, 10)
# (For reference: the size the vendor declares for a `GPU Temperature` data
# widget elsewhere, presetTheme[8] and [16], is 40 - half of its CPU reading.
# That is the asymmetry this layout gives up.)


def fan_figures(draw, figures, xs, y, colour=A26_WHITE, bold=False,
                max_w=A26_FAN_MAX_W, ceiling=A26_FAN_F, floor=A26_FAN_MIN,
                anchor="ma", face=None):
    """Two figures, centred one under each of two columns, at **one** shared size.

    This is `alpha`'s fan row, and the shared size is the whole point of it.  Each figure
    is fitted against `max_w` panel px by `_fit_draw`'s walk, and the pair draws at the
    smaller of the two fits, never below `floor`: the wider figure decides the size for
    both, so the two columns always match.  Sized one at a time they would not - over the
    30 reading pairs `tests/test_specials.py` walks, the two figures' own fits disagree on
    25 of them and drawing each at its own moves the row by 1 763 to 2 915 px - both of
    those counts are one bench's, recorded here, because they depend on the faces
    installed.  The check holds the relation: the joint rule shows up as a moved row
    **exactly when** the two fits disagree, and nowhere else.  The pair is one drawing
    because the sizes are not independent (docs/theme-editor.md).

    `anchor` is the anchor of each figure, which the layout says (`xigma.anchor`) for the
    same reason it says it for a text row: what an `x` means.  The theme's own row anchors
    mid-top ("ma"), centring each figure on its column.  `face` is the face factory,
    `face(size) -> font`: a theme leaves it alone and gets this module's own `font(size,
    bold)`, a layout passes one built from the family its row names (as `draw_text` does),
    so the walk and the drawing never disagree about which face a size means.

    Returns the size it chose and the two ink boxes, in panel px: the caller can say what
    the shared size came out to rather than leave a reader to measure it back off the
    picture.  A layout reaches this through one `special` row (`themes.SPECIALS`), which
    supplies the two anchors and the colour; the fit rule and the floors stay here, in the
    drawing, because they are what makes the pair a pair.
    """
    mk = face or (lambda px: font(px, bold))
    size = max(floor, min(_fit_draw(draw, s, max_w, ceiling, bold, mk)
                          for s in figures))
    fnt = mk(size)
    boxes = []
    for x, s in zip(xs, figures):
        draw.text((x * SS, y * SS), s, font=fnt, fill=colour, anchor=anchor)
        boxes.append(tuple(v // SS for v in
                           draw.textbbox((x * SS, y * SS), s, font=fnt,
                                         anchor=anchor)))
    return size, boxes


def value_pair(draw, strings, xs, y, ring, colour=A26_WHITE, bold=True,
               ceiling=A26_TVAL_F, anchor="ma", gap=ARC_FIT_GAP, face=None):
    """Two figures, one under each of two columns, at one size fitted to a **ring's hole**.

    This is `alpha`'s temperature row, and it is a drawing rather than two text rows
    because of how its size is chosen: both strings are measured and one size comes out
    (`_fit_arc`'s joint rule), and what they are measured against is the ring's clear
    radius, not a width.  The schema's only fit key is a width, and
    `tests/test_specials.py`'s exhaustive search over every whole-pixel budget this
    canvas can hold finds none that reproduces the six sizes this rule picks for
    `--`, 5, 22, 57, 100 and 241 degrees.

    `ring` is the six numbers `arc_clear` works from - `(cx, cy, inner, outer, start,
    sweep)`, panel px and Pillow degrees - and it describes **one** of the two rings: they
    are congruent, so measuring one column answers both, which is what `theme_alpha` has
    always done by passing `A26_TCOL_X[0]`.  A layout row gets the same shape for free when
    its `x` is the pair's centre and its `width` the pitch between the two figures: the
    first column sits at `x - width/2`.

    `gap` (the clearance `ARC_FIT_GAP` states) and the walk's floor of 10 stay here with
    the rule.  They are what keeps the figure off the ring, so a file that could set them
    could draw the text over the gauge it is standing in.

    Returns the size it chose and the two ink boxes, in panel px.
    """
    cx, cy, r_in, r_out, start, sweep = ring
    mk = face or (lambda px: font(px, bold))
    size = _fit_arc_draw(draw, tuple(strings), cx, cy, y, r_in, r_out, start,
                         sweep, ceiling, bold, gap, mk)
    fnt = mk(size)
    boxes = []
    for x, s in zip(xs, strings):
        draw.text((x * SS, y * SS), s, font=fnt, fill=colour, anchor=anchor)
        boxes.append(tuple(v // SS for v in
                           draw.textbbox((x * SS, y * SS), s, font=fnt,
                                         anchor=anchor)))
    return size, boxes


def theme_alpha(m, title=None, clock=True, clock_size=26, fan=True,
                bg=OVERLAY, ink=None):
    """The theme ALPHA has selected, plus GPU temp, clock and fan figures."""
    img = Image.new("RGBA", (W * SS, H * SS), bg)
    # every glyph in this theme measures white (§10, and `A26_WHITE` above), so
    # the theme has no secondary ink to preserve: an override lands on all of
    # it uniformly.  That is a departure from the measured replica, and the GUI
    # says so rather than leaving the reader to notice.
    fg, mid, acc = _skin(ink, *SKIN["alpha"])
    cpu = m.get("cpu") or {}
    gpu = m.get("gpu") or {}

    # temperatures: two equal columns, each inside a gauge arc of its own.
    # Same label size and weight on both lines, same value size and weight,
    # each value centred under its label.  The arcs go first because the text
    # sizes are fitted against the ring's hole: nothing may land on the stroke.
    r_in = A26_RING_R - A26_RING_W
    for x, reading in zip(A26_TCOL_X, (cpu.get("temperature"),
                                       gpu.get("temperature"))):
        temp_arc(img, x, A26_RING_Y, reading, A26_ARC_LO, A26_ARC_MID,
                 A26_ARC_HI, A26_RING_R, A26_RING_W, A26_ARC_TRACK,
                 A26_ARC_START, A26_ARC_SWEEP)
    temps = (cpu_temp_text(m), gpu_temp_text(m))
    ring = (A26_TCOL_X[0], A26_RING_Y, r_in, A26_RING_R, A26_ARC_START,
            A26_ARC_SWEEP)
    tlbl = font(_fit_arc(img, A26_TLBL_TEXT, A26_TCOL_X[0], A26_RING_Y,
                         A26_TLBL_Y, r_in, A26_RING_R, A26_ARC_START,
                         A26_ARC_SWEEP, A26_TLBL_F))
    for x, label in zip(A26_TCOL_X, A26_TLBL_TEXT):
        _text(img, (x, A26_TLBL_Y), label, tlbl, fg, anchor="ma")
    # the values go through `value_pair`, which is also the door a `special` row draws
    # through: one size for both columns, fitted to the ring's hole.  One drawing, two
    # doors, so a layout cannot reach a different size than the theme does.
    value_pair(ImageDraw.Draw(img), temps, A26_TCOL_X, A26_TVAL_Y, ring, fg)

    # fans: this theme has no fan widget, so there is no geometry to copy.  One
    # figure per column, sitting in the ring's open mouth, so each one is under
    # the temperature it belongs to rather than one line between them.
    if fan:
        fan_figures(ImageDraw.Draw(img), (cpu_fan_figure(m), gpu_fan_figure(m)),
                    A26_FAN_X, A26_FAN_Y, fg)

    # usage: vendor geometry, exact, its values left-aligned on their anchors
    (cpu_bar, gpu_bar), (bar_w, bar_h) = A26_BAR_XY, A26_BAR_WH
    _text(img, (100, 300), "CPU USED", font(20, bold=False), fg,
          anchor="la")
    _text(img, (320, 290), _pct(cpu.get("load")), font(32, bold=False),
          fg, anchor="la")
    hbar(img, *cpu_bar, bar_w, bar_h, (cpu.get("load") or 0) / 100.0)
    _text(img, (100, 370), "GPU USED", font(20, bold=False), fg,
          anchor="la")
    _text(img, (322, 362), _pct(gpu.get("load")), font(32, bold=False),
          fg, anchor="la")
    hbar(img, *gpu_bar, bar_w, bar_h, (gpu.get("load") or 0) / 100.0)

    # clock, small and centred along the bottom, below the lower bar (which
    # ends at y=409).  26 of the panel's 480 px, so its digits ink about 19 px
    # - ALPHA's own `Time` widget in store.json declares fontSize 14, so this
    # is already bigger than the vendor's; --clock-size raises it further.
    if clock:
        t = clock_str()
        _text(img, (240, 470), t, _fit(img, t, 452, clock_size, bold=False),
              fg, anchor="ms")
    if title:
        _title(img, title, y=26, size=20, colour=fg)
    return img.resize((W, H), Image.LANCZOS)


def _tach(m) -> tuple:
    """This box's tachometers, split into (CPU fan, pump, another fan).

    The vendor's fan readings come from the motherboard, not the panel.  Its
    logs show the app reading this board's Super-IO - "MSI X870 GAMING PLUS
    WIFI (MS-7E47) (Nuvoton NCT6687D)" with "Fan CPU" 1016-2448 RPM and "Fan
    System 5" 1529-1582 RPM - and pushing them down to the panel inside the
    `STATE all 1` metrics blob, as `fans: [{onBoard: true, type: "Fan",
    name: "Fan CPU", value: 2051}, ...]` (34 such bodies in the logs, never a
    pump value).  The panel only ever receives them: its reply advertises
    `attribute: ["Status", "Fan", "Pump"]` as a capability and reports no
    tachometer of its own.  So a fan figure on this panel means host sensors,
    and on Linux that means an hwmon driver for the NCT6687D: `nct6683` binds
    it as hwmon `nct6687`, publishes ten tach inputs and four PWMs, and labels
    only the temperatures - which is why `sensors.FAN_CHANNELS` pins fan1 as
    the CPU fan from a measured spin-up (1360-2371 RPM against pwm1) rather
    than from a label (`tools/fanscan.py --watch`, PROTOCOL.md §8).
    """
    tach = [f for f in (m.get("fans") or []) if f.get("value")]
    pump = next((f for f in tach if f.get("type") == "Pump"), None)
    # Type first, then name.  A pinned pump channel is named `CPU PUMP` on this board, so a
    # name-only rule would take the pump for the cooler's fan the moment the real fan row went
    # missing, and the figure would print `CPU FAN 2459 RPM` for a pump that never speeds up.
    # Measured as a defect before it was fixed: `{"type": "Pump", "name": "CPU PUMP"}` on its
    # own came out `CPU FAN 2410 RPM` through the old rule.
    cpu_fan = next((f for f in tach if f is not pump
                    and "cpu" in str(f.get("name", "")).lower()),
                   None)
    other = next((f for f in tach if f is not cpu_fan and f is not pump), None)
    return cpu_fan, pump, other


def cpu_fan_figure(m) -> str:
    """The figure that sits under the CPU temperature: the board's CPU fan.

    The wording follows where the channel's identity came from.  A channel
    pinned in `sensors.FAN_CHANNELS`, or one whose driver does publish a label
    that mentions CPU, is drawn as `CPU FAN`; a pump channel as `PUMP`, because
    on this AIO the pump is the CPU's cooling.  An unpinned channel is drawn as
    the neutral `FAN nnnn RPM`, because picking which of two unlabelled
    tachometers is the CPU fan would be a guess - the pinning is done by
    measurement once, in the sensors layer, where the evidence is written down.

    Never faked, never left out: with no tachometer bound the figure reads
    `CPU FAN -- RPM`, so the slot is visible from the chair and says plainly
    that this box has no reading, rather than going quiet and looking like the
    AIO had stopped.
    """
    cpu_fan, pump, other = _tach(m)
    if cpu_fan:
        return f"CPU FAN {round(cpu_fan['value'])} RPM"
    if pump:
        return f"PUMP {round(pump['value'])} RPM"
    if other:
        return f"FAN {round(other['value'])} RPM"
    return "CPU FAN -- RPM"           # no tach bound: the figure admits it


def gpu_fan_figure(m) -> str:
    """The figure that sits under the GPU temperature: the card's fan.

    A percentage, not RPM: `nvidia-smi` reports `fan.speed` in percent and
    NVML's `nvmlDeviceGetFanSpeedRPM` refuses here with "Argument version
    mismatch", so it stays honest and says `%`.  A card that reports no fan at
    all - and `nvidia-smi` reports 0 for "not supported" as well as for
    stopped, which is why 0 is treated as no reading - reads `GPU FAN --`, so
    the slot stays visible and empty rather than claiming a stopped fan.

    The board's remaining tachometers - this board's `Fan System 5`, a pump on
    a box that reports one - no longer get a place on this theme's glass: the
    layout carries two figures, one per temperature.  They are still sent:
    everything `sensors.fans()` reads rides into the `STATE all 1` metrics blob
    at the head of a session (PROTOCOL.md §8), and `--no-fans` takes that array
    out along with the figures.
    """
    fan = (m.get("gpu") or {}).get("fan")
    return f"GPU FAN {round(fan)}%" if fan else "GPU FAN --"


THEMES = {"gauge": theme_gauge, "dual": theme_dual, "clock": theme_clock,
          "bars": theme_bars, "alpha": theme_alpha}

#: The three glyph colours each drawn theme owns - primary, secondary, accent - in one
#: place, so that **both** doors read the same declaration.  `_skin` above applies a
#: reader's ink to a triple; a layout file bakes the *default* triple into its
#: `textColor` fields, and `themes.with_ink` moves exactly those fields by way of this
#: table.  Before it existed the ink question could only be answered by looking inside
#: five theme functions, and the window's text-colour row moved the code drawing by
#: thousands of pixels while a generated layout, painted by `themes.draw`, did not move
#: at all: the pane's two doors disagreed about the reader's own colour choice.  The
#: suite now holds the two doors to zero differing pixels at five inks across all five
#: themes, which is what makes this table a fact rather than a list.
#:
#: `alpha` repeats one colour three times deliberately: its measured skin is white text
#: on a mostly-transparent picture (PROTOCOL.md 10), and the copy of that theme the
#: vendor's own frames show has no dimmer second role.
SKIN = {"gauge": (WHITE, ALPHA_LABEL, ALPHA_MINT),
        "dual": (WHITE, DIM, CYAN), "clock": (WHITE, DIM, CYAN),
        "bars": (WHITE, DIM, CYAN),
        "alpha": (A26_WHITE, A26_WHITE, A26_WHITE)}


def skin(theme: str, ink=None) -> tuple:
    """The three glyph colours of one drawn theme, a reader's ink applied.

    One accessor for both doors: `theme_*` calls `_skin(ink, *SKIN[theme])` and
    `themes.with_ink` calls this, so a theme cannot change its skin in one door and keep
    the other at the old colours.
    """
    return _skin(ink, *SKIN[theme])


def scrim(img: Image.Image, alpha: int, grow: int = 6) -> Image.Image:
    """Put a translucent dark plate under everything the theme painted.

    Needed because the glyphs of the theme ALPHA selected are all white - 6 of 6
    `textColor` values in its layout file, and ours are white unless the reader
    picks another ink - and the panel always has a moving picture behind it.  The clip this project ships with is dark, so by
    default nothing is added here; a bright vendored clip, `theme_48.mp4`,
    measures a mean luma of 227.3 of 255 - a near-white field - and white on
    white is unreadable, so for clips measured that bright the OSD carries its
    own background: the plate is built from the frame's own alpha channel, grown
    by `grow` supersampled pixels (3 device px), which hugs whatever was drawn
    and needs no per-theme geometry.  `main._scrim_for` decides the amount,
    `--scrim 0` turns it off.

    It is a deviation from the vendor on purpose: ALPHA never pairs a bright
    clip with this theme, so it never has to solve this.
    """
    ink = img.getchannel("A").filter(ImageFilter.MaxFilter(max(3, grow * 2 + 1)))
    if alpha < 255:
        ink = ink.point(lambda v: v * alpha // 255)
    plate = Image.new("RGBA", img.size, (0, 0, 0, 0))
    plate.putalpha(ink)                       # black, masked by the grown ink
    return Image.alpha_composite(plate, img)


# `draw()` takes an argument called `scrim`, so the plate needs a module-level name the
# argument cannot shadow: renaming the argument would break every caller that spells it
# out (`main.paint`, `xigmaui`, the preview tools), which is a worse trade than an alias.
_plate = scrim


def draw(metrics, theme="gauge", scrim: int = 0, **kw) -> Image.Image:
    """Render one 480x480 frame of `theme` from a metrics dict.

    `kw` reaches the theme, so `ink=(r,g,b)` - or the string form, once put
    through `parse_ink` - recolours the glyphs of any theme without touching
    its geometry or its graphics colours.
    """
    img = THEMES.get(theme, theme_gauge)(metrics, **kw)
    if scrim:
        img = _plate(img, max(1, min(255, int(scrim))))
    return img if img.size == (W, H) else img.resize((W, H))


def to_png(img: Image.Image, palette: bool = True, colors: int = 256) -> bytes:
    """Encode for upload.  The stock files are 8-bit RGBA; a 256-colour PNG of
    the same picture is about a third the bytes - 12.2 KB against 40.8 KB for
    one ringed `alpha` frame - and it is not the same picture either: measured
    offline it stays graded, but it moves the alpha at ~36 100 of 230 400
    pixels by up to 28/255 and shifts the colour at ~12 700 of them
    (`tests/test_encoder.py` re-measures a live pair on every run).  Octree quantising treats RGBA as
    one four-channel colour, so it averages opacity too: of that frame's 11 149
    fully opaque pixels only 74 keep alpha 255, while its 4 029 half-transparent
    track pixels come back within 11/255.

    Transparency is kept either way: the vendor's own `.osd` files are RGBA with
    ~91 % of their pixels transparent, which is how its picture lets the panel's
    stored background show through, so the palette path quantizes with fast
    octree when the frame has alpha (median cut cannot carry it).  Which shape
    goes on the wire is the caller's call, and the two callers disagree today:
    `main._png` offers the palette only over an opaque canvas, while
    `xigmaui/panel.py` passes no argument at all.  On display speed the only
    measurement here is old and coarse: under the wrong `transported` ordering a
    16-30 KB RGBA counter showed 6 of 30 frames and a 6.4 KB indexed one 3 of 30
    (PROTOCOL.md §9), so smaller did not buy more frames - and that comparison
    has not been repeated since the ordering was fixed.
    """
    buf = io.BytesIO()
    has_alpha = img.mode == "RGBA" and img.getextrema()[3][0] < 255
    if palette and not has_alpha:
        img.convert("RGB").quantize(colors=colors, method=Image.MEDIANCUT,
                                    dither=Image.NONE).save(buf, "PNG",
                                                             optimize=True)
    elif palette:
        img.quantize(colors=colors, method=Image.FASTOCTREE,
                     dither=Image.NONE).save(buf, "PNG", optimize=True)
    else:
        img.convert("RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def frame_name() -> str:
    """The name ALPHA gives its live picture: 2026-11-05_07-21-36-052.osd"""
    return (time.strftime("%Y-%m-%d_%H-%M-%S")
            + f"-{int((time.time() % 1) * 1000):03d}.osd")
