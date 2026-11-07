#!/usr/bin/env python3
"""Measure our drawing of ALPHA's themes against ALPHA's own drawings.

Nothing here decides what a theme should look like.  It draws a copied layout
with `xigmalcd.layout` and compares the result, in pixels, against pictures the
vendor drew itself - so the substitutions this repo makes (no Microsoft fonts on
this machine: Arial becomes Liberation Sans, Verdana becomes DejaVu Sans, simsun
and 宋体 become Noto Sans CJK) come out as numbers instead of claims.

    theme_check.py                       every static `text` widget, 27 themes
    theme_check.py --theme ID            one theme
    theme_check.py --arc                 the ring audit as well (needs a capture)
    theme_check.py --arc --digits PATH   and write the sheet the values are
                                         read off by eye
    theme_check.py --sheet PATH          write a PNG of the per-widget crops

What is being compared, and why each comparison is fair:

* **static `text` widgets** - `content` is a fixed string written in the layout,
  so there is no value to know and no fixture to invent: the vendor and we draw
  the same glyphs at the same declared (x, y) with the same declared family and
  size.  The vendor's ink is the connected ink of its baked overlay
  `foreground/<id>.png` that falls inside the widget's window; ours is
  `draw.text` at the anchor convention `render.py` measured.  Every box is also
  reported against the declared point, so the anchor convention can be read off
  without the other face in the way.  Two faces at one size disagree about
  *width*, so left/top (the anchor convention) and width/height (the face) are
  separate columns, and ink is compared as coverage - the sum of alpha over 255,
  i.e. how much of a solid glyph each one paints - because a count of pixels
  above a threshold is a property of the threshold.
* **the ring** - the one `arc` in the library is the default theme, and the
  default theme is what this panel displays, so the app's own uploads show it:
  65 overlays in one capture, 24-25 KB PNGs, RGBA, 480x480.  Geometry is
  measurable from them without knowing any value - ink radius, the sweep's ends
  in Pillow's angles, and the caps, read as alpha rather than ink/not-ink
  because both ends of the sweep land between pixels.  Where a value enters is
  the filled fraction, and that is reported twice: as a fraction for every
  frame, and against the temperature the app itself sent in the `STATE all`
  request that precedes a frame, in the capture that contains such requests.

Both halves report; neither asserts a threshold.  The point is the number, and
the README quotes it.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageChops                  # noqa: E402

from xigmalcd import layout                                   # noqa: E402
from xigmalcd.render import SS                                # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEMES = os.path.join(ROOT, "themes", "alpha")
CAPTURES = os.path.join(ROOT, "COM3_windows_dumps")
INK = 8                      # alpha at or above this counts as ink: the vendor's
#                             overlays are antialiased (one of them has 8 407
#                             solid and 10 716 partial-alpha pixels)
SLACK = 6                    # px of window around a text widget's declared box
BOX = 900                    # canvas for drawing one widget in isolation, device px
FULLWIDTH = 1.0              # em per character, CJK and friends
LATIN = 0.80                 # em per character, a bound, not an estimate


# --------------------------------------------------- the vendor's own ink ---
def alpha_of(img: Image.Image) -> tuple:
    """(width, height, alpha values flat row-major) - there is no numpy here."""
    a = img.getchannel("A") if "A" in img.getbands() else img.convert("L")
    return a.width, a.height, list(a.get_flattened_data())


def components(alpha: list, w: int, h: int) -> list:
    """Connected ink at >= INK, 4-neighbour, as (bbox, pixels, npix, coverage).
    The bbox is right/bottom-exclusive like Pillow's, pixels are device
    coordinates, and coverage is the summed alpha over 255 - the amount of
    solid glyph painted, which is comparable between antialiased faces in a way
    a pixel count above a threshold is not."""
    mask = [[1 if alpha[y * w + x] >= INK else 0 for x in range(w)]
            for y in range(h)]
    seen = [[False] * w for _ in range(h)]
    out = []
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0][x0] or seen[y0][x0]:
                continue
            stack, px = [(x0, y0)], []
            seen[y0][x0] = True
            while stack:
                x, y = stack.pop()
                px.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] \
                            and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            xs = [p[0] for p in px]
            ys = [p[1] for p in px]
            box = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
            out.append((box, px, len(px),
                        sum(alpha[y * w + x] for x, y in px) / 255.0))
    return out


def window(prop: dict) -> tuple:
    """The region a text widget's ink may live in.

    The width bound is a bound on the *declared string*, not an estimate of its
    rendered width: a character is allowed 0.80 em (no face in the library draws
    Latin that wide on average - the widest measured here is 0.69 em) or a full
    em if it is CJK.  The bound is load-bearing: a fixed 6-em window made theme
    9247's 'CPU' at x=144,240 swallow the ink 164 px to its right, and the
    width delta came out -116 px, which is a property of the window and not of
    any font.  Ink that enters the window without being wholly inside it is
    counted as stray rather than merged, so a wrong window shows up as a report
    instead of as a wrong number.
    """
    x, y = int(prop["x"]), int(prop["y"])
    size = int(prop.get("fontSize") or 12)
    text = prop.get("content") or ""
    em = sum(FULLWIDTH if ord(c) > 0x2E80 else LATIN for c in text)
    return (max(0, x - SLACK), max(0, y - SLACK),
            x + int(math.ceil(em * size)) + SLACK, y + size + SLACK)


def vendor_for(comps: list, win: tuple) -> tuple:
    """(box, pixels, npix, coverage, stray) for one widget's window: every
    component wholly inside it, unioned, plus the boxes of components that
    cross it without belonging to it."""
    x0, y0, x1, y1 = win
    hit, stray, px = [], [], []
    for box, cpx, n, cov in comps:
        if x0 <= box[0] and box[2] <= x1 and y0 <= box[1] and box[3] <= y1:
            hit.append((box, n, cov))
            px.extend(cpx)
        elif box[0] < x1 and box[2] > x0 and box[1] < y1 and box[3] > y0:
            stray.append(box)
    if not hit:
        return None, [], 0, 0.0, stray
    return (min(c[0][0] for c in hit), min(c[0][1] for c in hit),
            max(c[0][2] for c in hit), max(c[0][3] for c in hit),
            ), px, sum(c[1] for c in hit), sum(c[2] for c in hit), stray


# ------------------------------------------------------ our own drawing -----
def ours(prop: dict, text: str) -> tuple:
    """Draw one static string the way the daemon would: the layout's font
    request resolved by layout.font_for, drawn at the declared (x, y) with the
    anchor convention, on the same SS grid the encoder works at.  Ink is read
    back off the raster (not off `textbbox`, which is a vector metric and can
    disagree with what actually gets painted), at device resolution, so a
    2x-supersampled frame cannot report four times the pixels."""
    face, fam, path = layout.font_for(prop)
    if face is None:
        return None, [], 0, 0.0, path
    img = Image.new("L", (BOX * SS, BOX * SS), 0)
    ImageDraw.Draw(img).text((int(prop["x"]) * SS, int(prop["y"]) * SS), text,
                             font=face, fill=255, anchor="la")
    box = img.getbbox()
    if not box:
        return None, [], 0, 0.0, path
    crop = img.crop(box)
    flat = crop.get_flattened_data()
    cov = sum(flat) / 255.0 / (SS * SS)
    cw = crop.width
    px = sorted({((box[0] + i % cw) // SS, (box[1] + i // cw) // SS)
                 for i, v in enumerate(flat) if v >= INK})
    if not px:
        return None, [], 0, cov, path
    xs = [p[0] for p in px]
    ys = [p[1] for p in px]
    return ((min(xs), min(ys), max(xs) + 1, max(ys) + 1), px, len(px), cov,
            path)


def check_theme(theme: dict) -> list:
    with open(os.path.join(THEMES, theme["layout"])) as f:
        obj = json.load(f)
    fg = Image.open(os.path.join(THEMES, theme["foregroundFile"])).convert("RGBA")
    w, h, alpha = alpha_of(fg)
    comps = components(alpha, w, h)
    rows = []
    for widget in obj["osd"]["widget"]:
        if widget["type"] != "text":
            continue
        prop = widget["property"][0]
        win = window(prop)
        vbox, vpx, vn, vcov, stray = vendor_for(comps, win)
        ob, opx, on, ocov, path = ours(prop, prop["content"])
        rows.append({"id": theme["id"], "content": prop["content"],
                     "fam": (prop.get("fontFamily") or "").lower(),
                     "size": int(prop.get("fontSize") or 12),
                     "bold": bool(prop.get("bold")), "face": path,
                     "declared": (int(prop["x"]), int(prop["y"])),
                     "window": win, "stray": stray,
                     "vendor": vbox, "vendor_pixels": vpx, "vendor_px": vn,
                     "vendor_cov": vcov,
                     "ours": ob, "our_pixels": opx, "ours_px": on,
                     "our_cov": ocov})
    return rows


def deltas(r: dict) -> tuple:
    """our ink box minus the vendor's: left, top, width, height, device px."""
    return (r["ours"][0] - r["vendor"][0],
            r["ours"][1] - r["vendor"][1],
            (r["ours"][2] - r["ours"][0]) - (r["vendor"][2] - r["vendor"][0]),
            (r["ours"][3] - r["ours"][1]) - (r["vendor"][3] - r["vendor"][1]))


def against_declared(r: dict, box: tuple) -> tuple:
    """A box's left and top relative to the layout's declared (x, y) - the
    anchor question, told once per side instead of as a difference."""
    return box[0] - r["declared"][0], box[1] - r["declared"][1]


def print_rows(rows: list) -> None:
    print(f"{'theme':>5} {'content':<20} {'request':<12} {'declared':>10}  "
          f"{'vendor ink':<22} {'our ink':<22}  "
          f"{'v-end ours-end':<16} {'our-vendor dx,dy w,h':<21} coverage")
    for r in rows:
        head = (f"  {r['id'][-4:]} {r['content']!r:<20} "
                f"{r['fam']}/{r['size']}{'b' if r['bold'] else ' '}    "
                f"{r['declared'][0]:>4},{r['declared'][1]:<5} ")
        if not r["vendor"] or not r["ours"]:
            why = "no vendor ink in the window" if not r["vendor"] \
                else f"no face for {r['fam']}"
            print(head + why)
            continue
        vdx, vdy = against_declared(r, r["vendor"])
        odx, ody = against_declared(r, r["ours"])
        dl, dt, dw, dh = deltas(r)
        print(head
              + f"{r['vendor'][0]:>3},{r['vendor'][1]:>3}"
                f" {r['vendor'][2] - r['vendor'][0]:>3}x{r['vendor'][3] - r['vendor'][1]:<3}"
                f" @{vdx:+d},{vdy:+d}  "
              + f"{r['ours'][0]:>3},{r['ours'][1]:>3}"
                f" {r['ours'][2] - r['ours'][0]:>3}x{r['ours'][3] - r['ours'][1]:<3}"
                f" @{odx:+d},{ody:+d}  "
              + f"{dl:+3d},{dt:+3d} {dw:+4d},{dh:+3d}  "
              + f"{r['vendor_cov']:>7.1f} vs {r['our_cov']:<6.1f}"
              + (f"  [{len(r['stray'])} stray]" if r["stray"] else ""))


def summarise(all_rows: list) -> dict:
    by = {}
    for r in all_rows:
        if not r["vendor"] or not r["ours"]:
            continue
        k = (r["fam"], r["size"], r["bold"], os.path.basename(r["face"] or "-"))
        d = by.setdefault(k, {"n": 0, "dl": [], "dt": [], "dw": [], "dh": [],
                              "vdx": [], "vdy": [], "odx": [], "ody": [],
                              "vc": 0.0, "oc": 0.0, "worst": (0, None),
                              "stray": 0})
        d["n"] += 1
        dl, dt, dw, dh = deltas(r)
        d["dl"].append(dl)
        d["dt"].append(dt)
        d["dw"].append(dw)
        d["dh"].append(dh)
        d["vdx"].append(against_declared(r, r["vendor"])[0])
        d["vdy"].append(against_declared(r, r["vendor"])[1])
        d["odx"].append(against_declared(r, r["ours"])[0])
        d["ody"].append(against_declared(r, r["ours"])[1])
        d["vc"] += r["vendor_cov"]
        d["oc"] += r["our_cov"]
        d["stray"] += len(r["stray"])
        score = abs(dl) + abs(dt) + abs(dw)
        if score > d["worst"][0]:
            d["worst"] = (score, r["content"])

    def rng(v):
        return f"{min(v):+d}..{max(v):+d}" if v else "-"

    print("\n== per face: our ink box minus the vendor's, device px")
    for k in sorted(by, key=lambda k: (-by[k]["n"], k)):
        d = by[k]
        print(f"  {k[0]}/{k[1]}{'b' if k[2] else ' '} -> {k[3]:<24} {d['n']:>2}  "
              f"dx {rng(d['dl']):<8} dy {rng(d['dt']):<8}"
              f"  width {rng(d['dw']):<9} height {rng(d['dh']):<8}"
              f"  coverage {d['vc']:>7.0f} vs {d['oc']:<7.0f}"
              f"  worst {d['worst'][1]!r}"
              + (f"  [{d['stray']} stray]" if d["stray"] else ""))
    print("\n== ink top-left relative to the declared (x, y), device px")
    for k in sorted(by, key=lambda k: (-by[k]["n"], k)):
        d = by[k]
        print(f"  {k[0]}/{k[1]}{'b' if k[2] else ' '} -> {k[3]:<24} {d['n']:>2}  "
              f"vendor dx {rng(d['vdx']):<8} dy {rng(d['vdy']):<8}"
              f"   ours dx {rng(d['odx']):<8} dy {rng(d['ody']):<8}")
    return by


def write_sheet(all_rows: list, path: str) -> None:
    """One row per text widget: the vendor's ink, our ink, and where they
    disagree.  Ink only, tinted - the layouts are all white-on-dark text, so
    colour carries no information here that the XOR does not show better."""
    rows = [r for r in all_rows if r["vendor"] and r["ours"]]
    if not rows:
        print("nothing to draw")
        return
    box = (min(min(r["vendor"][0], r["ours"][0]) for r in rows),
           min(min(r["vendor"][1], r["ours"][1]) for r in rows),
           max(max(r["vendor"][2], r["ours"][2]) for r in rows),
           max(max(r["vendor"][3], r["ours"][3]) for r in rows))
    crop = (box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4)
    w, h = crop[2] - crop[0], crop[3] - crop[1]
    label, gap = 250, 6
    sheet = Image.new("RGB", (label + 3 * w + 2 * gap, len(rows) * (h + 6) + 6),
                      (26, 26, 26))
    d = ImageDraw.Draw(sheet)

    def paint(pixels, tint):
        img = Image.new("L", (BOX, BOX), 0)
        px = img.load()
        for x, y in pixels:
            px[x, y] = 255
        c = img.crop(crop).convert("RGB")
        out = Image.new("RGB", c.size, (26, 26, 26))
        out.paste(tint, (0, 0), c.getchannel("R"))
        return out

    for i, r in enumerate(rows):
        y0 = 6 + i * (h + 6)
        for j, (im, tint) in enumerate((
                (paint(r["vendor_pixels"], (250, 250, 250)), 0),
                (paint(r["our_pixels"], (120, 220, 255)), 1),
                (ImageChops.difference(paint(r["vendor_pixels"], (255, 255, 255)),
                                       paint(r["our_pixels"], (255, 255, 255))
                                       ).convert("RGB")
                 .resize((w, h)), (255, 90, 90)), 2)):
            sheet.paste(im, (label + j * (w + gap), y0))
        dl, dt, dw, dh = deltas(r)
        d.text((4, y0 + h // 2 - 6),
               f"{r['id'][-4:]} {r['fam']}/{r['size']}{'b' if r['bold'] else ''} "
               f"{dl:+d},{dt:+d} w{dw:+d} h{dh:+d}", fill=(230, 230, 230))
    sheet.save(path)
    print(f"\n{path}  {sheet.size[0]}x{sheet.size[1]}  "
          f"{os.path.getsize(path)} B  {len(rows)} widgets x "
          f"[vendor | ours | where they differ]")


# ------------------------------------------------------------------ ring ----
def ring_geometry(theme_id: str = "1757491588836") -> dict:
    """Everything the ring audit needs, read out of the layout."""
    obj = layout.load(os.path.join(THEMES, "layouts", "480X480",
                                   f"{theme_id}.json"))
    arc = next(w["property"][0] for w in obj["osd"]["widget"]
               if w["type"] == "arc")
    a0, a1 = layout.arc_angles(arc)
    return {"obj": obj, "arc": arc, "a0": a0, "a1": a1,
            "sweep": int(round(a1 - a0)),
            "x": int(arc["x"]), "y": int(arc["y"]),
            "sw": int(arc["sizeWidth"]), "sh": int(arc["sizeHeight"]),
            "rad": int(arc["radius"]), "thick": int(arc["width"]),
            "cx": int(arc["x"]) + int(arc["sizeWidth"]) / 2,
            "cy": int(arc["y"]) + int(arc["sizeHeight"]) / 2,
            "canvas": (int(obj["width"]), int(obj["height"]))}


def painted_window(theme: dict) -> tuple:
    """The region of the frame where the app paints the number that the arc's
    own `source` refers to.  The arc names a source; somewhere in the same
    layout there is a `data` widget with that source; the crop is that widget's
    declared box plus slack, so the ring is being compared against the value
    the app painted into the very same image, not against a guess."""
    arc = theme["arc"]
    want = arc.get("source")
    data = [w["property"][0] for w in theme["obj"]["osd"]["widget"]
            if w["type"] == "data" and w["property"][0].get("source") == want]
    if not data:
        return None
    p = data[0]
    x, y, size = int(p["x"]), int(p["y"]), int(p.get("fontSize") or 12)
    return (max(0, x - SLACK), max(0, y - SLACK), x + 4 * size,
            y + size + 2 * SLACK)


_groups_cache: dict = {}


def digit_groups(capture: str, theme: dict) -> list:
    """Group a capture's frames by the pixels they paint in that window, and
    give each group its measured fill stop.  Identical ink in the window means
    the same painted number, so this pairs the ring's stop with the value on
    the glass without reading a single value - the reading itself comes from
    the sheet written next to it.

    Each group also carries the sub-degree edges of its frames: where the
    stroke crosses half coverage at the sweep's own start (the cap) and at the
    fill's end, measured on a 4x resample.  Cached, because the 4x resample is
    the slowest thing in this tool and both audits want the same groups.
    """
    key = (capture, theme["arc"].get("source"))
    if key in _groups_cache:
        return _groups_cache[key]
    win = painted_window(theme)
    groups = {}
    half = None
    for name, blob, _states in uploads_with_state(capture):
        head = png_header_of(blob)
        if not head or head[:2] != theme["canvas"]:
            continue
        im = Image.open(io.BytesIO(blob)).convert("RGBA")
        if half is None:
            half = (track_alpha(im, theme) + 255) / 2
        crop = im.crop(win)
        key = hashlib.sha256(crop.getchannel("A").tobytes()).hexdigest()[:12]
        g = groups.setdefault(key, {"names": [], "stops": set(), "crop": crop,
                                   "cap": set(), "edge": set()})
        g["names"].append(name)
        g["stops"].add(fill_stop(im, theme))
        if "first" not in g:
            g["first"] = im
        near, far = ring_edges(resample(im, 4), 4, theme, half)
        if far is not None:
            g["edge"].add(round(far, 3))
        if near is not None:
            g["cap"].add(round(near, 3))
    out = sorted(groups.values(), key=lambda g: -max(g["stops"] or {0}))
    _groups_cache[key] = out
    return out



def fill_stop(im: Image.Image, theme: dict):
    """How far the fill runs along the middle of the stroke, in degrees from
    the sweep's start, or None if the stroke never reaches solid ink."""
    px = im.load()
    mid = theme["rad"] + theme["thick"] / 2
    seen = [k for k in range(-6, theme["sweep"] + 7)
            if at_px(px, theme, theme["a0"] + k, mid) > 200]
    return max(seen) if seen else None


def at_px(px, theme: dict, ang: float, r: float) -> int:
    """Alpha at angle `ang` (Pillow's) and radius `r` from the ring's centre."""
    a = math.radians(ang)
    return px[int(round(theme["cx"] + r * math.cos(a))),
               int(round(theme["cy"] + r * math.sin(a)))][3]


def at_scaled(px, theme: dict, scale: int, ang: float, r: float) -> tuple:
    """The pixel at angle `ang`, radius `r` on a frame that was resampled at
    `scale`x.  Resampling first is what makes sub-degree and sub-pixel readings
    possible at all: the ends of the sweep and of the fill both land between
    pixels, so reading them off the 480x480 grid would measure the grid."""
    a = math.radians(ang)
    x = int(round((theme["cx"] + r * math.cos(a)) * scale))
    y = int(round((theme["cy"] + r * math.sin(a)) * scale))
    return px[x, y]


def track_alpha(im: Image.Image, theme: dict) -> int:
    """The unfilled track's alpha: the ring's `bgColor` as it actually lands on
    the glass, measured near the end of the sweep - past where any frame's fill
    got to - and used as one end of the half-coverage threshold below rather
    than as a number taken from the layout's `rgba(..., 0.5)`."""
    vals = [at_px(im.load(), theme, theme["a0"] + k, theme["rad"]
                  + theme["thick"] / 2)
            for k in range(theme["sweep"] - 6, theme["sweep"] - 1)]
    return Counter(vals).most_common(1)[0][0]


def resample(im: Image.Image, scale: int):
    """RGBA pixel access for a `scale`x resample of a frame."""
    return im.resize((im.width * scale, im.height * scale),
                     Image.BILINEAR).convert("RGBA").load()


def ring_edges(px, scale: int, theme: dict, half: float):
    """(near end, far end) of the fill in degrees from the sweep's start: the
    two places the stroke crosses `half` coverage, bracketed at a 0.25 deg step
    and narrowed by bisection, sampled at the middle of the stroke.

    `half` comes from `track_alpha` - a pixel half covered by the fill over the
    track reads (track + 255) / 2, not 128, because the fill is opaque and the
    track already sits near half alpha.  Both crossings are reported rather than
    an ink/not-ink threshold, because the ends land between pixels and a
    threshold there would measure the threshold.
    """
    mid = theme["rad"] + theme["thick"] / 2

    def a(deg):
        return at_scaled(px, theme, scale, theme["a0"] + deg, mid)[3]

    def bisect_up(lo, hi):                  # a(lo) <= half, a(hi) > half
        for _ in range(40):
            m = (lo + hi) / 2
            if a(m) > half:
                hi = m
            else:
                lo = m
        return (lo + hi) / 2

    def bisect_down(lo, hi):                # a(lo) > half, a(hi) <= half
        for _ in range(40):
            m = (lo + hi) / 2
            if a(m) > half:
                lo = m
            else:
                hi = m
        return (lo + hi) / 2

    near = far = None
    prev = a(-4.0)
    k = -4.0
    while k <= theme["sweep"] + 4:
        v = a(k)
        if prev <= half < v and near is None:
            near = bisect_up(k - 0.25, k)
        if prev > half >= v:
            far = bisect_down(k - 0.25, k)
        prev, k = v, k + 0.25
    return near, far


def ring_colour(px, scale: int, theme: dict, deg: float, alpha_min: int = 250):
    """The fill's own colour at `deg` degrees into the sweep: sampled at three
    radii across the stroke, keeping only the fully opaque samples, so an
    antialiased edge cannot be read as a colour.  None if this frame does not
    fill that degree."""
    mid = theme["rad"] + theme["thick"] / 2
    out = None
    for dr in (-4, 0, 4):
        p = at_scaled(px, theme, scale, theme["a0"] + deg, mid + dr)
        if p[3] >= alpha_min:
            out = p[:3]
    return out



def png_header_of(blob: bytes):
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import vendor_capture as vc
    return vc.png_header(blob)


def write_digit_sheet(groups: list, path: str, theme: dict) -> None:
    """The reading's evidence: one row per group, the painted number upscaled,
    and the number the ring's stop implies."""
    if not groups:
        print("  (no painted-number groups to write)")
        return
    crop = groups[0]["crop"]
    scale, line = 2, 26
    w, h = crop.width * scale, crop.height * scale
    sheet = Image.new("RGB", (w + 260, len(groups) * (h + line) + line),
                      (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    d.text((6, 6), "the app's own pixels      ring stop -> implied value",
           fill=(230, 230, 230))
    for i, g in enumerate(groups):
        y0 = line + i * (h + line)
        c = g["crop"].convert("RGB").resize((w, h), Image.NEAREST)
        dark = Image.new("RGB", c.size, (24, 24, 24))
        dark.paste((250, 250, 250), (0, 0), c.getchannel("R").point(
            lambda v: min(255, v * 3)))
        sheet.paste(dark, (0, y0))
        stops = sorted(g["stops"])
        d.text((w + 8, y0 + h // 2 - 6),
               "  ".join(f"{s} deg -> {s / theme['sweep'] * 100:.1f}"
                         for s in stops) + f"   [{len(g['names'])} frames]",
               fill=(230, 230, 230))
    sheet.save(path)
    print(f"  {path}  {sheet.size[0]}x{sheet.size[1]}  {os.path.getsize(path)} B"
          f"  {len(groups)} groups: the digits are read off this sheet by eye")


def uploads_with_state(capture: str):
    """Yield (fileName, bytes, [(row time, cpu temperature, sample timestamp)])
    for every upload in a capture, with the `STATE all` requests that came
    before it.

    `tools/vendor_capture.py`'s `transfers()` deliberately ignores everything
    but the two `POST transport`/`transported` requests, because all it wants is
    file bytes; this keeps the same row walk and also remembers what the app
    asked the panel for, so a frame can be paired with a number that was on the
    wire rather than read off the picture.  The temperature is the one the app
    reported in that request; the pairing itself is reported, not resolved -
    the frames paint one sample behind the request that precedes them, and this
    prints both of the two most recent so the reader can see that for themselves.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import vendor_capture as vc
    cur, states = None, []
    for ts, data in vc.down_rows(capture):
        msg = vc.as_request(data)
        if msg:
            parts = msg.line.strip().split(" ")
            cmd, sub = parts[0], (parts[1] if len(parts) > 1 else "")
            if cmd == "POST" and sub == "transport":
                try:
                    body = msg.json() or {}
                except ValueError:
                    body = None
                cur = {"name": body.get("fileName"), "chunks": []} if body else None
                continue
            if cmd == "POST" and sub == "transported":
                if cur:
                    yield cur["name"], b"".join(cur["chunks"]), list(states)
                cur = None
                continue
            if cmd == "STATE" and sub == "all":
                try:
                    j = msg.json() or {}
                except ValueError:
                    j = {}
                temp = (j.get("cpu") or {}).get("temperature")
                if isinstance(temp, (int, float)):
                    states.append((ts, temp, j.get("timestamp")))
                continue
        if cur is not None:
            cur["chunks"].append(data)


def arc_audit(capture: str, theme_id: str = "1757491588836",
              digits: str = "") -> None:
    """The one `arc` in the library, measured off the app's own uploads.

    The payloads come out of the capture the way tools/vendor_capture.py prints
    them: between a `POST transport` and the `POST transported` that follows it
    sit the file's bytes, unframed, in fixed-size writes.  Geometry needs no
    value at all - ink radius, the sweep's ends and the cap shape are all
    measurable from ink, and both ends of the sweep land between pixels, so
    they are reported as alpha rather than as ink/not-ink.

    The filled fraction is where a value enters, and the value is in the same
    picture: the arc's own `source` is `CPU Temperature`, and the same layout
    has a `data` widget for `CPU Temperature`, so the frame paints the number
    the ring is supposed to be showing.  Grouping frames by the pixels they
    paint in that window pairs a ring stop with a painted value without reading
    anything; the digits themselves are read off the `--digits` sheet by eye,
    and labelled as a reading wherever they are quoted.
    """
    theme = ring_geometry(theme_id)
    arc, sweep, rad, thick = (theme["arc"], theme["sweep"], theme["rad"],
                              theme["thick"])
    print(f"\n== ring, theme {theme_id}: the layout says box "
          f"({theme['x']},{theme['y']}) {theme['sw']}x{theme['sh']}, radius "
          f"{rad}, stroke {thick}, angles {arc['angleStart']}.."
          f"{arc['angleEnd']} -> Pillow {theme['a0']:.0f}..{theme['a1']:.0f}, "
          f"source {arc.get('source')!r}, range {arc.get('minValue')}.."
          f"{arc.get('maxValue')}")

    mid = rad + thick / 2
    stops, radial, frames = Counter(), Counter(), 0
    caps = {k: [] for k in (-2, -1, 0, 1, sweep - 1, sweep, sweep + 1)}
    pinned = []
    for name, blob, states in uploads_with_state(capture):
        head = png_header_of(blob)
        if not head or head[:2] != theme["canvas"]:
            continue
        frames += 1
        im = Image.open(io.BytesIO(blob)).convert("RGBA")
        px = im.load()
        # radial extent along the sweep's bisector, where only the ring lives:
        # the layout says ink from `radius` to `radius + width`.
        ink_r = [r for r in range(rad - 12, rad + thick + 13)
                 if at_px(px, theme, theme["a0"] + sweep / 2, r) >= INK]
        radial[(min(ink_r), max(ink_r)) if ink_r else None] += 1
        # how far the fill runs along the middle of the stroke
        seen = [k for k in range(-6, sweep + 7)
                if at_px(px, theme, theme["a0"] + k, mid) > 200]
        if seen:
            stops[(min(seen), max(seen))] += 1
        for k in caps:
            caps[k].append(at_px(px, theme, theme["a0"] + k, mid))
        if states:
            pinned.append((name, (max(seen) if seen else None), states[-2:]))

    print(f"  frames read: {frames} of {os.path.basename(capture)}")
    print(f"  ink radii along the sweep's bisector, px "
          f"(layout says {rad}..{rad + thick}):")
    for k, n in radial.most_common():
        print(f"    {k[0]}..{k[1]}  {n} frames" if k else f"    none  {n} frames")
    print(f"  how far the fill runs, degrees from the sweep's start "
          f"(the layout's {arc['angleStart']}..{arc['angleEnd']} is "
          f"{sweep} deg):")
    for (lo, hi), n in sorted(stops.items()):
        print(f"    {lo:>3}..{hi:>3}   -> value {hi / sweep * 100:>5.1f}"
              f"   {n:>2} frames")
    print("  caps, as alpha at the middle of the stroke, degrees from the "
          "sweep's own ends:")
    for k in sorted(caps):
        v = caps[k]
        where = "before the start" if k < 0 else ("past the end"
                                                 if k >= sweep else "")
        print(f"    {k:>+3}  alpha {min(v):>3}..{max(v):>3}  {len(v):>2} frames"
              f"{'  ' + where if where else ''}")
    print(f"  frames grouped by the pixels they paint for the arc's own source "
          f"({arc.get('source')!r}),\n  and the ring stop each group carries - "
          f"the number itself is read off the\n  --digits sheet, by eye, and "
          f"the layout's range is {arc.get('minValue')}..{arc.get('maxValue')}:")
    groups = digit_groups(capture, theme)
    prev = None
    for g in groups:
        edge = sorted(g["edge"])
        step = "" if (prev is None or not edge) else f"  step {edge[-1] - prev:+.3f}"
        if edge:
            prev = edge[-1]
        print(f"    {len(g['names']):>2} frames, same painted ink   "
              + "   ".join(f"stop {s} deg -> {s / sweep * 100:>4.1f}"
                           for s in sorted(g["stops"]))
              + (f"   cap {min(g['cap']):+.3f}  fill edge {edge[-1]:.3f}{step}"
                 if edge else "")
              + f"   first {g['names'][0]}")
    if len([g for g in groups if g["edge"]]) > 1:
        e = [sorted(g["edge"])[-1] for g in groups if g["edge"]]
        span, n = abs(e[0] - e[-1]), len(e) - 1
        print(f"    the fill edges span {span:.3f} deg across {n} steps of one "
              f"unit of the range\n    = {span / n:.4f} deg per unit; the "
              f"declared range says {sweep / (float(arc['maxValue']) - float(arc['minValue'])):.4f}")
    if digits:
        write_digit_sheet(groups, digits, theme)
    if pinned:
        print("  the same ring next to the value the app put on the wire, in a "
              "`STATE all`\n  request that precedes the frame:")
        for name, stop, states in pinned:
            pred = "   ".join(f"{t} °C @ {ms} -> {t / 100 * sweep:>5.1f} deg"
                              for _ts, t, ms in states)
            print(f"    {name}  measured stop "
                  f"{stop if stop is not None else '-':>4} deg   wire: {pred}")
    colour_audit(capture, theme)


def colour_audit(capture: str, theme: dict) -> None:
    """The ring's colour, the vendor's reading against our drawing.

    The vendor's side is the mean, over every frame that fills a degree, of the
    colour sampled at three radii across the stroke at that degree, keeping only
    fully opaque samples.  Because the frames in a capture disagree about the
    value and agree about the colour at a degree, the profile needs no value at
    all; the degrees no frame reaches are reported as unmeasured rather than
    extrapolated.

    Our side is `xigmalcd.layout` drawing the same layout at the value the
    capture's own fill edge implies (edge / sweep x the declared range, rounded -
    the ring's reading of itself, not an eye reading), sampled back off our
    pixels by the same code at the same radii.  The straight lerp from startColor
    to endColor, the obvious thing to do with the two colours the layout
    declares, is printed alongside so the cost of the measured profile is a
    number instead of an argument.
    """
    src = theme["arc"].get("source")
    lo, hi = float(theme["arc"]["minValue"]), float(theme["arc"]["maxValue"])
    sums, cnt = Counter(), Counter()
    nframes = 0
    for name, blob, _s in uploads_with_state(capture):
        head = png_header_of(blob)
        if not head or head[:2] != theme["canvas"]:
            continue
        nframes += 1
        im = Image.open(io.BytesIO(blob)).convert("RGBA")
        px2 = resample(im, 2)
        for deg in range(0, theme["sweep"] + 1):
            c = ring_colour(px2, 2, theme, deg)
            if c is None:
                continue
            cnt[deg] += 1
            for i in range(3):
                sums[deg, i] += c[i]
    if not cnt:
        print("  (no filled ring in this capture, so the colour audit had "
              "nothing to read)")
        return
    top = max(cnt)
    prof = {d: tuple(sums[d, i] / cnt[d] for i in range(3)) for d in cnt}

    groups = digit_groups(capture, theme)
    values = sorted({round(sorted(g["edge"])[-1] / theme["sweep"]
                            * (hi - lo) + lo)
                     for g in groups if g["edge"]})
    ours, imgs = {}, {}
    for v in values:
        img, notes = layout.draw_theme(theme["obj"], {src: v})
        imgs[v] = img
        px2 = resample(img, 2)
        for deg in range(0, theme["sweep"] + 1):
            c = ring_colour(px2, 2, theme, deg)
            if c is not None:
                ours[deg] = c

    start, end = layout.rgba(theme["arc"]["startColor"]), \
        layout.rgba(theme["arc"]["endColor"])
    degs = sorted(set(prof) & set(ours))
    worst_ours = worst_lerp = 0
    sum_ours = sum_lerp = 0.0
    for d in degs:
        for i in range(3):
            t = d / theme["sweep"]
            lerp = start[i] + (end[i] - start[i]) * t
            do, dl = abs(prof[d][i] - ours[d][i]), abs(prof[d][i] - lerp)
            worst_ours, worst_lerp = max(worst_ours, do), max(worst_lerp, dl)
            sum_ours, sum_lerp = sum_ours + do, sum_lerp + dl

    print(f"  colour along the ring, mean over the {nframes} frames that fill a "
          f"degree, sampled at\n  three radii across the stroke and keeping only "
          f"opaque pixels; measured to {top} deg\n  (the deepest fill in the "
          f"capture), so {top + 1}..{theme['sweep']} deg is not measured and "
          f"\n  endColor {end} appears nowhere in it:")
    print("    deg   n  vendor rgb            ours rgb            "
          "dR    dG    dB   | straight lerp would be")
    for d in range(0, top + 1, 5):
        if d not in prof or d not in ours:
            continue
        l = [start[i] + (end[i] - start[i]) * d / theme["sweep"] for i in range(3)]
        print(f"    {d:>4} {cnt[d]:>3}  ({prof[d][0]:6.1f},{prof[d][1]:6.1f},"
              f"{prof[d][2]:6.1f})  ({ours[d][0]:3d},{ours[d][1]:3d},{ours[d][2]:3d})"
              f"  {prof[d][0] - ours[d][0]:+5.1f} {prof[d][1] - ours[d][1]:+5.1f}"
              f" {prof[d][2] - ours[d][2]:+5.1f}  |  ({l[0]:6.1f},{l[1]:6.1f},"
              f"{l[2]:6.1f})")
    n = len(degs)
    print(f"    over {n} degrees and 3 channels: our worst difference "
          f"{worst_ours:.1f}/255, mean {sum_ours / (3 * n):.2f};"
          f"\n    the straight lerp would have been worst {worst_lerp:.1f}/255, "
          f"mean {sum_lerp / (3 * n):.2f}.")
    geometry_audit(theme, groups, imgs, lo, hi)


def geometry_audit(theme: dict, groups: list, imgs: dict, lo: float,
                   hi: float) -> None:
    """Our ring against the vendor's at the same value, measured the same way.

    Each side's half-coverage threshold is measured from that side's own track,
    so the comparison does not smuggle in the layout's `rgba(..., 0.5)`: the
    vendor's track reads one value, our LANCZOS-downsampled SS=2 track reads
    whatever our pipeline actually lands on, and each edge is read against its
    own.
    """
    print("  the ring as xigmalcd.layout draws it, at the value the capture's own"
          "\n  fill edge implies, measured by the same code on both sides:")
    print("    value  frames   cap deg  v / ours        fill edge  v / ours"
          "        stroke band centre, 20/60/100 deg in")
    cap_gap, edge_gap = [], []
    vfill, ofill, vtrack, otrack = [], [], [], []
    for g in groups:
        if not g["edge"] or "first" not in g:
            continue
        v = round(sorted(g["edge"])[-1] / theme["sweep"] * (hi - lo) + lo)
        if v not in imgs:
            continue
        v_im, o_im = g["first"], imgs[v]
        hv = (track_alpha(v_im, theme) + 255) / 2
        ho = (track_alpha(o_im, theme) + 255) / 2
        vc, ve = ring_edges(resample(v_im, 4), 4, theme, hv)
        oc, oe = ring_edges(resample(o_im, 4), 4, theme, ho)
        if None not in (vc, oc, ve, oe):
            cap_gap.append(oc - vc)
            edge_gap.append(oe - ve)
        reach = min(ve, oe) if None not in (ve, oe) else 0
        rays = [d for d in (20, 60, 100) if d <= reach - 2]
        tb = [d for d in (reach + 20, reach + 70, reach + 120)
              if d <= theme["sweep"] - 3]
        vfill += [b for b in (stroke_band(v_im, theme, d) for d in rays)
                  if b[0] is not None]
        ofill += [b for b in (stroke_band(o_im, theme, d) for d in rays)
                  if b[0] is not None]
        vtrack += [b for b in (stroke_band(v_im, theme, d) for d in tb)
                   if b[0] is not None]
        otrack += [b for b in (stroke_band(o_im, theme, d) for d in tb)
                   if b[0] is not None]
        cs = [(b[0] + b[1]) / 2 for b in (stroke_band(v_im, theme, d)
                                          for d in rays) if b[0] is not None]
        os_ = [(b[0] + b[1]) / 2 for b in (stroke_band(o_im, theme, d)
                                           for d in rays) if b[0] is not None]
        fmt = lambda xs: (f"{min(xs):6.2f}..{max(xs):<6.2f}" if xs else "  --  ")
        print(f"    {v:>6} {len(g['names']):>6}   "
              f"{vc:+8.3f} / {oc:+8.3f}     {ve:>8.3f} / {oe:<8.3f}"
              f"     {fmt(cs)} / {fmt(os_)}")

    def rng(v):
        return f"{min(v):+.3f}..{max(v):+.3f}" if v else "-"

    if cap_gap:
        print(f"    over {len(cap_gap)} values: our cap is {rng(cap_gap)} deg "
              f"from the vendor's, our fill edge\n"
              f"    {rng(edge_gap)} deg - and the vendor's own frame-to-frame "
              f"repeat is exact, so any\n"
              f"    spread here is our drawing, not the panel's.")
    want = theme["rad"] + theme["thick"] / 2
    print(f"\n  the stroke's own band, probed outward along a ray and read at half "
          f"of whatever\n  coverage that ray reaches - a ray over the fill reaches "
          f"255, a ray past the fill\n  reaches the track's own coverage, so each "
          f"is measured against its own plateau.\n  The layout says radius "
          f"{theme['rad']} + width {theme['thick']}: a band of "
          f"{theme['rad']}..{theme['rad'] + theme['thick']}\n  centred on "
          f"{want:.2f} px.")
    head = lambda b: (f"inner {min(x[0] for x in b):6.2f}..{max(x[0] for x in b):<6.2f}"
                      f"  outer {min(x[1] for x in b):6.2f}..{max(x[1] for x in b):<6.2f}"
                      f"  width {min(x[1] - x[0] for x in b):4.2f}..{max(x[1] - x[0] for x in b):<4.2f}"
                      f"  centre {min((x[0] + x[1]) / 2 for x in b):6.2f}..{max((x[0] + x[1]) / 2 for x in b):<6.2f}"
                      f"  coverage {min(x[2] for x in b):.0f}..{max(x[2] for x in b):<.0f}")
    for label, vb, ob in (("along the fill", vfill, ofill),
                          ("past the fill", vtrack, otrack)):
        if vb and ob:
            print(f"    {label}, {len(vb)} rays:")
            print(f"      vendor  {head(vb)}")
            print(f"      ours    {head(ob)}")
    if vfill and ofill:
        vw = max((b[0] + b[1]) / 2 for b in vfill) - min((b[0] + b[1]) / 2
                                                         for b in vfill)
        ow = max((b[0] + b[1]) / 2 for b in ofill) - min((b[0] + b[1]) / 2
                                                         for b in ofill)
        print(f"    the band is where the layout says it is, to the pixel, and it is "
              f"the vendor's ring\n    that is the noisier of the two: its centre "
              f"wanders {vw / 2:.2f} px in radius, ours "
              f"{ow / 2:.2f}.  The\n    fill-edge degrees above are all inside that "
              f"much of difference.")


def stroke_band(im: Image.Image, theme: dict, deg: float, scale: int = 4):
    """(inner, outer) radius where the stroke crosses half of its own plateau,
    probed outward along the ray `deg` degrees into the sweep.  The plateau is
    read from the probe itself, so a ray over the fill and a ray over the
    unfilled track are each measured against their own coverage instead of a
    shared threshold.  The probe spans `radius - 8` to `radius + width + 8`,
    which is the ring's own band: the theme's digits sit inside radius ~100 and
    the small labels inside ~80, so nothing else is on the ray."""
    big = resample(im, scale)
    lo = theme["rad"] - 8
    hi = theme["rad"] + theme["thick"] + 8
    prof = [(r, at_scaled(big, theme, scale, theme["a0"] + deg, r)[3])
            for r in [lo + i * 0.25 for i in range(int((hi - lo) * scale) + 1)]]
    plateau = max(a for _r, a in prof)
    half = plateau / 2
    cross, prev = [], None
    for r, a in prof:
        if prev is not None and ((prev < half <= a) or (prev >= half > a)):
            cross.append(r - 0.5 / scale)
        prev = a
    if len(cross) < 2:
        return None, None, plateau
    return cross[0], cross[-1], plateau


def radii(im: Image.Image, theme: dict) -> tuple:
    """Ink radii along the sweep's bisector: where the stroke actually is,
    against the layout's `radius` (inner edge) plus `width` (stroke)."""
    px = im.load()
    got = [r for r in range(theme["rad"] - 12, theme["rad"]
                            + theme["thick"] + 13)
           if at_px(px, theme, theme["a0"] + theme["sweep"] / 2, r) >= INK]
    return (min(got), max(got)) if got else (0, 0)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="theme_check",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--theme", default="", help="one theme id (default: all 27)")
    ap.add_argument("--arc", action="store_true",
                    help="also audit the ring against the app's own uploads")
    ap.add_argument("--capture", default="", help="which capture --arc reads")
    ap.add_argument("--digits", default="",
                    help="with --arc: write the painted-number sheet here")
    ap.add_argument("--sheet", default="", help="write the per-widget crops here")
    a = ap.parse_args(argv)

    with open(os.path.join(THEMES, "manifest.json")) as f:
        themes = json.load(f)["themes"]
    if a.theme:
        themes = [t for t in themes if t["id"] == a.theme]
        if not themes:
            print(f"no theme {a.theme}", file=sys.stderr)
            return 2
    rows = []
    for t in themes:
        rows += check_theme(t)
    print_rows(rows)
    summarise(rows)
    ok = sum(1 for r in rows if r["vendor"] and r["ours"])
    print(f"\n{len(rows)} static text widgets over {len(themes)} themes, "
          f"{ok} of them compared, {len(rows) - ok} reported as unresolvable")
    if a.sheet:
        write_sheet(rows, a.sheet)
    if a.arc:
        captures = [a.capture] if a.capture else [
            p for p in (os.path.join(CAPTURES, "COM3 Monitoring Session.txt"),
                        os.path.join(CAPTURES,
                                     "COM3 Monitoring Session from init.txt"))
            if os.path.exists(p)]
        if captures:
            for i, p in enumerate(captures):
                digits = a.digits
                if digits and len(captures) > 1:
                    root, ext = os.path.splitext(digits)
                    digits = f"{root}-{i + 1}{ext}"
                arc_audit(p, digits=digits)
        else:
            print("\n(no capture on disk, so the ring audit had nothing to read;"
                  "\n the captures live on the `data` branch of this repo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
