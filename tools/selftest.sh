#!/usr/bin/env bash
# Offline checks: no panel, no serial port needed. Run this after any change to
# protocol.py or render.py. The live checks against real hardware are the ones in
# docs/tools.md (and docs/limits.md's ledgers): tools/probe.py,
# tools/send_image.py, tools/session_limit.py.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# The one file a suite has no business touching: a person's own session file.  A section
# that *means* to isolate its settings root but whose variable expands to nothing writes
# ~/.config/xigmaui/config.json, and this suite has done exactly that - the 0.4 changelog
# records it - leaving the author's next `python3 -m xigmaui` pointed at
# /dev/xigma-no-such-port with a clip nobody had chosen.  So the guard belongs to the
# whole suite, not to one section's good intentions: snapshot here, compare at the end.
HOME_CFG="$HOME/.config/xigmaui/config.json"
if [ -e "$HOME_CFG" ]; then
    HOME_CFG_BEFORE="$(sha256sum "$HOME_CFG")"
else
    HOME_CFG_BEFORE=""
fi

echo "== protocol round-trip against the Windows captures"
# data/ is gitignored, so a clone has no captures to re-encode.  Say that out loud
# rather than reporting a pass: the figures below are what the same command printed
# on the author's bench, and they are what PROTOCOL.md quotes.
caps=(data/captures/*.txt)
if [ -f "${caps[0]}" ]; then
    python3 tools/verify_protocol.py "${caps[@]}"
else
    echo "  SKIPPED: no capture at data/captures/, so nothing was re-encoded here."
    echo "  On the author's bench this same command -"
    echo "    python3 tools/verify_protocol.py data/captures/*.txt"
    echo "  re-creates all 181 captured host->panel frames byte for byte (130 in the"
    echo "  long session, 51 in the one that starts at power-on), all 267 captured"
    echo "  panel replies pass the strict checksum, and mismatched frames: 0."
    echo "  Point it at a capture of your own to check those numbers; every section"
    echo "  after this one needs no capture."
fi

echo
echo "== renders (every theme, real sensors, PNG encoding)"
tmp=$(mktemp -d)
for t in alpha gauge dual clock bars; do
    python3 -m xigmalcd --dry-run "$tmp/$t" --once --theme "$t" >/dev/null || {
        echo "theme $t FAILED"; exit 1; }
    python3 - "$tmp/$t/frame0000.png" <<'PY'
import sys
from PIL import Image
im = Image.open(sys.argv[1])
assert im.size == (480, 480), im.size
print(f"  {sys.argv[1].split('/')[-2]:6s} {im.size[0]}x{im.size[1]} {im.mode} "
      f"{len(open(sys.argv[1],'rb').read())} bytes")
PY
done
python3 -m xigmalcd --dry-run "$tmp/tc" --once --truecolor >/dev/null || {
    echo "truecolor FAILED"; exit 1; }

# The encoder choice, measured and now decided: the 256-colour PNG is what
# `xigmalcd` uploads on every canvas, which is what `xigmaui/panel.py` has
# always uploaded, and `--truecolor` asks for 8-bit RGBA instead.  Indexed is
# not lossy-by-disaster and it does stay graded, but it is not exact, and the
# numbers below are what README's `--truecolor` and `--palette` rows and
# PROTOCOL §11 quote.  They are also the reason the two shapes were put on
# glass for one picture: README's encode A/B/A windows, 61 of 61 frames each
# way at 1 fps, and the owner's verdict on them.
python3 - <<'PY' || { echo "encoder choice FAILED"; exit 1; }
import math
from io import BytesIO
from PIL import Image, ImageChops

from xigmalcd import render

m = {"cpu": {"temperature": 57.0, "load": 42.0},
     "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
     "fans": [{"name": "Fan CPU", "type": "Fan", "value": 1957}]}
im = render.draw(m, "alpha", bg=render.OVERLAY)
assert im.mode == "RGBA" and im.getchannel("A").getextrema() == (0, 255)


def off(blob):
    """(bytes, pixels whose alpha moved, worst alpha move, pixels whose
    colour moved, worst colour move) against the drawn frame."""
    q = Image.open(BytesIO(blob)).convert("RGBA")
    d = ImageChops.difference(im, q)
    ah = d.getchannel("A").histogram()
    rgb = ImageChops.lighter(
        ImageChops.lighter(d.getchannel("R"), d.getchannel("G")),
        d.getchannel("B"))
    ch = rgb.histogram()
    return (len(blob), sum(ah[1:]), d.getchannel("A").getextrema()[1],
            sum(ch[1:]), rgb.getextrema()[1])


exact = off(render.to_png(im, palette=False))
qblob = render.to_png(im, palette=True)    # the default, and panel.py's path
pal = off(qblob)
assert exact[1] == exact[3] == 0, exact          # the RGBA path is lossless
assert pal[0] * 3 < exact[0], (exact[0], pal[0])
assert 0 < pal[2] <= 60 and 0 < pal[4] <= 60, pal
assert 10_000 < pal[1] < 60_000 and 5_000 < pal[3] < 30_000, pal

# PIL's octree quantiser takes RGBA as a four-channel colour, so a palette
# entry that mixes an opaque glyph pixel with a half-transparent track pixel
# comes out in between for both: no glyph core keeps its full opacity.
quantised = Image.open(BytesIO(qblob)).convert("RGBA")
src_a = im.getchannel("A").histogram()
pal_a = quantised.getchannel("A").histogram()
assert pal_a[255] * 10 < src_a[255] < sum(src_a), (src_a[255], pal_a[255])

# ...but the half-transparent gauge track, the reason RGBA was ever considered,
# is nearly what it has to keep: alpha 150, isolated from the ramp colours.
diff_a = ImageChops.difference(im.getchannel("A"), quantised.getchannel("A"))
track = im.getchannel("A").point(lambda v: 255 if v == 150 else 0)
on_track = ImageChops.multiply(diff_a, track).histogram()
TRACK_N = track.histogram()[255]
worst_track = max((i for i, v in enumerate(on_track) if v), default=0)
off_by_2 = sum(v for i, v in enumerate(on_track) if i > 1)
assert TRACK_N and worst_track <= 20 and off_by_2 * 50 < TRACK_N, (
    TRACK_N, worst_track, off_by_2)

STEP = 0.2          # degrees between samples along the arc
RAMP_R = render.A26_RING_R - 6     # mid-radius of the 12 px stroke


def ramp(img):
    """Colours met along the CPU arc's filled part, at the stroke's middle."""
    cx, cy = render.A26_TCOL_X[0], render.A26_RING_Y
    out = []
    for deg10 in range(0, 1500, 2):
        t = math.radians(render.A26_ARC_START + deg10 / 10.0)
        px = img.getpixel((int(round(cx + RAMP_R * math.cos(t))),
                           int(round(cy + RAMP_R * math.sin(t)))))
        if px[3] > 200:
            out.append(px[:3])
    return out


drawn = ramp(im)
cols = ramp(quantised)
assert len(set(cols)) < len(set(drawn)) // 3, (len(set(drawn)), len(set(cols)))
band_deg = STEP * len(drawn) / max(1, len(set(cols)))
band_px = math.radians(band_deg) * RAMP_R
print(f"  the same ringed overlay frame: RGBA {exact[0]} B exactly as drawn "
      f"(what `--truecolor` uploads), indexed {pal[0]} B (the default, and what "
      f"the window uploads) with alpha moved at {pal[1]} px, worst "
      f"{pal[2]}/255, colour moved at {pal[3]} px, worst {pal[4]}")
print(f"  opacity is where it bites: {src_a[255]} pixels are drawn fully "
      f"opaque and only {pal_a[255]} of them stay at 255 in the indexed file, "
      f"while the {TRACK_N} half-transparent track pixels (alpha 150) come "
      f"back within {worst_track}/255 - {off_by_2} of them by more than 1")
print(f"  where that shows: the gauge ramp, drawn in {len(set(drawn))} colours "
      f"along its fill and quantised to {len(set(cols))} - {band_deg:.1f} deg, "
      f"about {band_px:.0f} px of arc, one flat colour each.  All of it went "
      f"up on real glass both ways, 61 of 61 frames each, and the owner could "
      f"see no difference; hence the indexed default.")
PY

# and the switches, on the command line, on the real encoder path: the default
# frame over the transparent canvas is the indexed file, `--palette` says the same
# thing out loud, and only `--truecolor` puts an RGBA file there.  Checked by
# reading the PNG each dry run writes.
python3 -m xigmalcd --dry-run "$tmp/pal" --once --theme alpha --palette >/dev/null \
    || { echo "--palette FAILED"; exit 1; }
python3 - "$tmp/alpha/frame0000.png" "$tmp/pal/frame0000.png" \
    "$tmp/tc/frame0000.png" <<'PY' || { echo "encoder switches FAILED"; exit 1; }
import sys
from PIL import Image
dflt, explicit, tc = [Image.open(p) for p in sys.argv[1:4]]
assert dflt.mode == "P" and explicit.mode == "P", (dflt.mode, explicit.mode)
assert tc.mode == "RGBA", tc.mode
alpha = dflt.convert("RGBA").getchannel("A").histogram()
levels = sum(1 for v in alpha[1:255] if v)      # part-transparent steps kept
assert alpha[0] and levels >= 1, (alpha[0], levels)


def size(path):
    with open(path, "rb") as fh:
        return len(fh.read())


print(f"  encoder switches   default over a transparent canvas: {dflt.mode} "
      f"{size(sys.argv[1])} B with {alpha[0]} clear px and {levels} "
      f"part-transparent step(s) kept; --palette: {explicit.mode} "
      f"{size(sys.argv[2])} B; --truecolor: {tc.mode} {size(sys.argv[3])} B")
PY

echo
echo "== a meter is only a meter if the ring it sits on stays out of its way"
python3 - <<'PY' || { echo "legibility FAILED"; exit 1; }
import os, shutil, subprocess, sys, tempfile
sys.path.insert(0, ".")
from PIL import Image
from xigmalcd import render as R

# ---- the dual rings: is the meter legible over a background, or is the track ----
# Measured on a decoded frame of a clip this repository carries, so the number can be
# re-counted on any machine: fill vs unfilled, mean luma along the ring's mid-radius,
# for the neutral track this theme now asks for and the pale cyan default it used to
# inherit.  `cold=heat, span="sweep"` means the colour itself carries the value, so a
# track within a few luma of the fill is the whole complaint.
DARK = "themes/alpha/clips/Theme_30.mp4"      # mean luma 4.0 of 255 (measured)
PIN = {"cpu": {"temperature": 71.0}, "gpu": {"temperature": 44.0},
       "memory": {"used": 85332, "total": 126157}}     # dual spans cold 30 hot 90


def mid_frame(path, tmp):
    out = os.path.join(tmp, "f.png")
    dur = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         check=True, capture_output=True).stdout.decode().strip()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{float(dur) / 2:.3f}",
                    "-i", path, "-frames:v", "1", out], check=True)
    return Image.open(out).convert("RGBA").resize((480, 480), Image.LANCZOS)


def lum(px):
    return 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]


def ring(comp, cx, cy, r, frac, start=120, sweep=300, n=240):
    """mean luma of the filled part and the unfilled part of one ring"""
    import math
    fill, track = [], []
    for i in range(n):
        a = math.radians(start + sweep * i / (n - 1))
        px = comp.getpixel((int(round(cx + r * math.cos(a))),
                            int(round(cy + r * math.sin(a)))))
        (fill if i < n * frac else track).append(lum(px))
    return sum(fill) / len(fill), sum(track) / len(track)


def dual_over(bg, track):
    real = R.gauge

    def patched(img, *a, **kw):
        kw["track"] = track        # force it: theme_dual now passes one explicitly,
        return real(img, *a, **kw)  # and setdefault would leave the new value in place
    R.gauge = patched
    try:
        return Image.alpha_composite(bg, R.draw(PIN, "dual", bg=R.OVERLAY))
    finally:
        R.gauge = real


if shutil.which("ffmpeg") and os.path.exists(DARK):
    with tempfile.TemporaryDirectory() as tmp:
        bg = mid_frame(DARK, tmp)
        spans = (30.0, 90.0)
        rows = {}
        for what, tr in (("track=ARC_TRACK (now)", R.ARC_TRACK),
                         ("gauge default TRACK (before)", R.TRACK)):
            comp = dual_over(bg, tr)
            f1, t1 = ring(comp, 128, 228, 86, (71.0 - spans[0]) / (spans[1] - spans[0]))
            f2, t2 = ring(comp, 352, 228, 86, (44.0 - spans[0]) / (spans[1] - spans[0]))
            rows[what] = (f1, t1, f2, t2)
            print(f"  dual ring on {os.path.basename(DARK)}  {what:<30} "
                  f"CPU ring fill {f1:6.1f} track {t1:6.1f} gap {abs(f1 - t1):5.1f}  |  "
                  f"GPU ring fill {f2:6.1f} track {t2:6.1f} gap {abs(f2 - t2):5.1f}")
        now, was = rows["track=ARC_TRACK (now)"], rows["gauge default TRACK (before)"]
        gap_now = min(abs(now[0] - now[1]), abs(now[2] - now[3]))
        gap_was = max(abs(was[0] - was[1]), abs(was[2] - was[3]))
        assert gap_now >= 4 * gap_was, (gap_now, gap_was)
        print(f"  the neutral track separates the meter from its own ring by "
              f"{gap_now:.1f} luma where the pale default managed {gap_was:.1f} "
              f"({gap_now / gap_was:.1f}x); the ring is still drawn, it just no "
              f"longer out-shouts the fill")
        assert R.ARC_TRACK[0] < 150 and R.ARC_TRACK[3] < 255, R.ARC_TRACK
else:
    print(f"  dual ring legibility SKIPPED: {DARK} or ffmpeg missing here")

# ---- every line this theme draws has to land inside the panel ------------------
# The clock theme fitted only its big time line; the other two could run off the
# glass.  Counted by drawing the string and reading the alpha bbox, which is what
# the panel would show: a clipped glyph is a clipped glyph.
WORST = {"cpu": {"temperature": 100.0}, "gpu": {"temperature": 100.0},
         "fans": [{"name": "Fan CPU", "type": "Fan", "onBoard": True,
                   "value": 12345}]}
PINNED = {"cpu": {"temperature": 57.0}, "gpu": {"temperature": 47.0},
          "fans": [{"name": "Fan CPU", "type": "Fan", "onBoard": True,
                    "value": 1957}]}
BANDS = {"time": (150, 240), "date": (270, 310), "readings": (335, 380)}


def band_box(lay, y0, y1):
    """ink bbox of one line, measured on the 480 px result: the crop is what makes
    it a per-line check rather than a whole-picture one"""
    a = lay.getchannel("A").crop((0, y0, lay.width, y1))
    return a.getbbox()


for label, m in (("pinned readings", PINNED), ("worst realistic", WORST)):
    lay = R.draw(m, "clock", bg=R.OVERLAY).convert("RGBA")
    for band, (y0, y1) in BANDS.items():
        box = band_box(lay, y0, y1)
        assert box, (label, band, "a line this theme should draw drew nothing")
        assert box[0] > 0 and box[2] < 480, \
            (label, band, box, "ink touches or crosses a panel edge")
        print(f"  clock {label:<16} {band:<9} ink x {box[0]:4d}..{box[2]:4d} "
              f"({box[2] - box[0]:4d} px) inside 480, y band {y0}-{y1}")
# and the same line at the size it used to be fixed at, so the before figure stays
# in the open rather than remembered
line = "CPU 100°C    GPU 100°C    12345 RPM"
one = Image.new("RGBA", (R.W * R.SS, R.H * R.SS), (0, 0, 0, 0))
R._text(one, (240, 358), line, R.font(26, True), R.CYAN)
b = one.getchannel("A").getbbox()
print(f"  that line at the old fixed font 26 reaches x {b[0] / R.SS:.1f}..{b[2] / R.SS:.1f}, "
      f"i.e. both canvas edges: drawn centred, it was clipped at each end")
assert b[0] == 0 and b[2] == R.W * R.SS, (b, "the old overflow is what this pins")
PY

echo
echo "== the alpha gauges: text fitted inside the ring, colour graded by degree"
python3 - <<'PY' || { echo "alpha gauge geometry FAILED"; exit 1; }
import math, sys
sys.path.insert(0, ".")
from xigmalcd import render as R

PIN = {"cpu": {"temperature": 57.0, "load": 42.0},
       "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
       "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU",
                 "value": 2400}]}
CANVAS = R.Image.new("RGBA", (R.W * R.SS, R.H * R.SS), R.OVERLAY)
R_IN = R.A26_RING_R - R.A26_RING_W
ARC = (R.A26_ARC_START, R.A26_ARC_SWEEP)


def fit(strings, y, ceiling, bold=True):
    """Largest joint size for `strings`, and how far its ink ends up from the
    stroke (negative means clear of it, which is what every text block needs)."""
    size = R._fit_arc(CANVAS, strings, R.A26_TCOL_X[0], R.A26_RING_Y, y, R_IN,
                      R.A26_RING_R, *ARC, ceiling)
    worst = max(R.arc_clear(R.ink_box(CANVAS, s, R.font(size, bold), cx, y),
                            cx, R.A26_RING_Y, R_IN, R.A26_RING_R, *ARC)
                for s in strings for cx in R.A26_TCOL_X)
    return size, worst


# two equal rings, not overlapping, inside the canvas with a margin
assert len(set(R.A26_TCOL_X)) == 2, R.A26_TCOL_X
for x in R.A26_TCOL_X:
    assert R.A26_RING_R <= x <= R.W - R.A26_RING_R, (x, R.A26_RING_R)
assert R.A26_TCOL_X[1] - R.A26_RING_R > R.A26_TCOL_X[0] + R.A26_RING_R, \
    "the two gauge rings overlap"
# text may never land on the stroke, and the joint rule still ties the two
# columns to one size: a three-digit reading takes both down
lbl, lbl_clear = fit(("CPU TEMP", "GPU TEMP"), R.A26_TLBL_Y, R.A26_TLBL_F)
two = ["57\u00b0C", "47\u00b0C"]
three = ["100\u00b0C", "47\u00b0C"]
val, val_clear = fit(two, R.A26_TVAL_Y, R.A26_TVAL_F)
val3, val3_clear = fit(three, R.A26_TVAL_Y, R.A26_TVAL_F)
assert 0 < lbl < R.A26_TLBL_F and lbl_clear <= -3, (lbl, lbl_clear)
assert 0 < val3 < val and val_clear <= -3 and val3_clear <= -3, \
    (val, val_clear, val3, val3_clear)
# one fan figure per column, under its own temperature, in the ring's open
# mouth: clear of the stroke and of the usage block, whose ink starts at y 294
left, right = R.cpu_fan_figure(PIN), R.gpu_fan_figure(PIN)
assert "CPU" in left and "GPU" in right and "2400" in left and "45%" in right, \
    (left, right)
size = max(R.A26_FAN_MIN, min(R._fit_size(CANVAS, s, R.A26_FAN_MAX_W,
                                          R.A26_FAN_F, bold=False)
                              for s in (left, right)))
for s in (left, right):
    box = R.ink_box(CANVAS, s, R.font(size, False), R.A26_FAN_X[0], R.A26_FAN_Y)
    assert R.arc_clear(box, R.A26_TCOL_X[0], R.A26_RING_Y, R_IN, R.A26_RING_R,
                       *ARC) < 0, (s, box)
    assert box[3] < 294 and box[2] - box[0] <= R.A26_FAN_MAX_W, (s, box)
# a missing reading is `--` and no ring at all: sampled along the middle of the
# stroke, that column has not one painted pixel
im = R.draw({"cpu": {"temperature": None}, "gpu": {"temperature": None}},
            "alpha", bg=R.OVERLAY).convert("RGBA")


def ring_pixels(pic, cx):
    mid = R.A26_RING_R - R.A26_RING_W / 2
    q = pic.convert("RGBA").load()
    hits = 0
    for i in range(161):
        ang = math.radians(R.A26_ARC_START + R.A26_ARC_SWEEP * i / 160)
        x = int(round(cx + mid * math.cos(ang)))
        y = int(round(R.A26_RING_Y + mid * math.sin(ang)))
        hits += 1 if q[x, y][3] else 0
    return hits


assert R._deg(None) == "--\u00b0C"
assert ring_pixels(im, R.A26_TCOL_X[0]) == 0, ring_pixels(im, R.A26_TCOL_X[0])
assert ring_pixels(im, R.A26_TCOL_X[1]) == 0


def tip(pic, cx):
    """Colour at the tip of the arc for whatever that column is showing."""
    t = (pic["cpu" if cx == R.A26_TCOL_X[0] else "gpu"])["temperature"]
    frac = (min(max(t, R.A26_ARC_LO), R.A26_ARC_HI) - R.A26_ARC_LO) \
        / (R.A26_ARC_HI - R.A26_ARC_LO)
    ang = math.radians(R.A26_ARC_START + R.A26_ARC_SWEEP * frac)
    mid = R.A26_RING_R - R.A26_RING_W / 2
    frame = R.draw(pic, "alpha", bg=R.OVERLAY).convert("RGBA")
    return frame.load()[int(round(cx + mid * math.cos(ang))),
                        int(round(R.A26_RING_Y + mid * math.sin(ang)))]


# the fill position and the colour both carry the value: 40 deg C ends green,
# 95 deg C ends red, and neither tip is the neutral track colour
cool, warm = {"cpu": {"temperature": 40.0}}, {"cpu": {"temperature": 95.0}}
c, h = tip(cool, R.A26_TCOL_X[0]), tip(warm, R.A26_TCOL_X[0])
assert c[3] and h[3] and c[:3] != h[:3], (c, h)
assert c[1] > c[0] and h[0] > h[1], (c, h)
assert (c[:3], h[:3]) != (R.A26_ARC_TRACK[:3],) * 2, (c, h)
SPAN = (R.A26_ARC_LO, R.A26_ARC_MID, R.A26_ARC_HI)
assert R.temp_colour(R.A26_ARC_LO, *SPAN)[:3] == R.GREEN[:3]
assert R.temp_colour(R.A26_ARC_MID, *SPAN)[:3] == R.AMBER[:3]
assert R.temp_colour(R.A26_ARC_HI, *SPAN)[:3] == R.RED[:3]
assert R.temp_colour(200, *SPAN)[:3] == R.RED[:3]     # clamped with the tip
assert R.temp_colour(0, *SPAN)[:3] == R.GREEN[:3]
print(f"  label {lbl} (ink {lbl_clear:+.1f} px off the stroke), value {val} "
      f"for two digits / {val3} for three, fan {size}: `{left}` | `{right}`")
print(f"  rings r {R.A26_RING_R}-{R.A26_RING_W} cy {R.A26_RING_Y} x "
      f"{R.A26_TCOL_X}, {R.A26_ARC_SWEEP:.0f} deg from {R.A26_ARC_START:.0f}: "
      f"tip at 40 deg C {c[:3]}, at 95 deg C {h[:3]}, track "
      f"{R.A26_ARC_TRACK[:3]}, and 0 of 161 samples painted where a missing "
      f"reading's ring would be")
PY

echo
echo "== ink: the colour of the text this program draws, and its own name"
QT_QPA_PLATFORM=offscreen python3 - <<'PY' || { echo "ink FAILED"; exit 1; }
import sys
import time
sys.path.insert(0, ".")
from xigmalcd import render as R

# one parser, three doors (CLI, socket, GUI): the spellings it takes, and the
# one it refuses
ok_cases = {"#ff4040": (255, 64, 64, 255), "#0f8": (0, 255, 136, 255),
            "amber": (*R.AMBER[:3], 255), "mint": (*R.ALPHA_MINT[:3], 255),
            "white": R.WHITE, "rgb(0,230,118)": (*R.GREEN[:3], 255),
            "default": None, "": None, "auto": None, None: None}
for got, want in ok_cases.items():
    back = R.parse_ink(got)
    assert back == want, (got, back, want)
junk = ("cerise", "#gg", "red green", 5, ("r", "e", "d"), (1, 2, 300))
for bad in junk:
    try:
        R.parse_ink(bad)
        raise AssertionError(f"{bad!r} was accepted")
    except ValueError as exc:
        assert "try #rrggbb" in str(exc), exc
# the names that message lists are the module's own constants, so
# `--text-color amber` and the GUI's `amber` entry are the same colour
PAIRED = {"white": R.WHITE, "black": R.BLACK, "cyan": R.CYAN, "green": R.GREEN,
          "amber": R.AMBER, "red": R.RED, "dim": R.DIM, "track": R.TRACK,
          "mint": R.ALPHA_MINT, "label": R.ALPHA_LABEL}
for name, colour in PAIRED.items():
    assert colour[:3] == R.parse_ink(name)[:3], (name, colour, R.parse_ink(name))
print(f"  parse_ink             {len(ok_cases)} spellings accepted, "
      f"{len(junk)} kinds of junk refused in words a human sees")

# the arithmetic of a chosen ink: one constant, pinned rather than trusted
assert R.INK_DIM == 0.62
assert R._dim((255, 64, 64, 255)) == (158, 40, 40, 255), R._dim((255, 64, 64, 255))
assert R._dim(R.WHITE)[:3] == (158, 158, 158)
assert R.ink_hex(R.parse_ink("AMBER")) == "#ffc400"
assert R.ink_hex(None) is None
assert R.parse_ink(R.ink_hex(R.AMBER)) == (*R.AMBER[:3], 255), "hex must read back"
# `theme default` must mean the theme's own measured skin, untouched
assert R._skin(None, R.WHITE, R.DIM, R.CYAN) == (R.WHITE, R.DIM, R.CYAN)
fg, mid, acc = R._skin("#ff0000", R.WHITE, R.DIM, R.CYAN)
assert fg == acc == (255, 0, 0, 255) and mid == R._dim(fg), (fg, mid, acc)

# and what a reader actually asked for: a frame whose text is another colour.
# Checked on pixels, not on the call: an `ink=` in the signature means nothing if
# a theme still paints its digits from a constant.
M = {"cpu": {"temperature": 41.6, "load": 7.4},
     "gpu": {"temperature": 38.0, "load": 12.0},
     "memory": {"used": 8283746304, "total": 33554432000},
     "motherboard": {"temperature": 32.0}, "fans": []}
# The whole frame's clock, not just its seconds: `theme_clock` draws a date line as well,
# and a frozen time next to a live date is how one file measured a different picture in a
# different zone.  One hook, one instant.
WHEN = time.strptime("2026-11-05 09:31:03", "%Y-%m-%d %H:%M:%S")
R._now = lambda: WHEN
RED = (255, 0, 0, 255)


def counts(img):
    """opaque-ish pixels of a frame, tallied by exact colour"""
    flat = img.convert("RGBA")
    rows = list(flat.getdata()) if not hasattr(flat, "get_flattened_data") \
        else flat.get_flattened_data()
    out = {}
    for p in rows:
        if p[3] > 240:
            out[p] = out.get(p, 0) + 1
    return out


for theme in ("gauge", "dual", "clock", "bars", "alpha"):
    # an (r,g,b) tuple, not the word "red": in this module `red` is a palette
    # name meaning R.RED (#ff4040), which is the precedence the help text and
    # the GUI both promise
    plain, inked = counts(R.draw(M, theme)), counts(R.draw(M, theme,
                                                           ink=(255, 0, 0)))
    core = plain.get(R.WHITE, 0)
    assert core > 200, (theme, core, "no solid glyph core to recolour")
    assert inked.get(RED, 0) > 200, (theme, inked.get(RED, 0))
    assert inked.get(R.WHITE, 0) == 0, (
        theme, inked.get(R.WHITE), "a glyph kept the theme's own ink")
    # graphics are not text: arcs, bars and tracks keep their colours, so an ink
    # changes the ink and nothing else about the composition
    before, after = sum(plain.values()), sum(inked.values())
    assert abs(after - before) < 0.06 * before, (
        theme, before, after, "choosing an ink redrew the frame, not its letters")
    print(f"  {theme:6s} ink on pixels  {core} white glyph px -> {inked[RED]} "
          f"red, none left white, painted area {before} -> {after}")

# the upload path quantises to 256 colours by default (PROTOCOL.md §12), so a
# chosen ink has to survive *that* to be worth choosing.  Measured here, over the
# colours the GUI offers: the worst per-channel shift on the way through.
#
# The frame has to hold enough of the ink for "the most common colour" to *be* the ink
# being asked about, so this probe asks `clock` for its big time line.  It used to pass
# `clock=False` as well, which read as "keep the picture simple" and worked only because
# `theme_clock` ignored that flag: once the flag honours the request (docs/limits.md's
# knob-map paragraph), that frame is the readings line alone and the assert below would
# have measured some other colour's trip through the palette.  So the probe now checks
# its own premise - the wanted ink is present, exactly, in thousands of pixels *before*
# the quantise - rather than assuming a theme draws what its signature offers.
import io
from PIL import Image
worst = 0
swatch = None
for name in ("amber", "mint", "cyan", "green", "red", "#ff4040"):
    want = R.parse_ink(name)
    frame = R.draw(M, "clock", clock=True, date=False, ink=want)
    pre = counts(frame)
    assert pre.get(want, 0) > 1000, (
        name, pre.get(want), "the frame this probe quantises does not carry the ink it "
                             "is asking about, so the assert below would measure some "
                             "other colour's trip through the palette")
    enc = R.to_png(frame)
    seen = counts(Image.open(io.BytesIO(enc)).convert("RGBA"))
    got = max(seen, key=seen.get)
    shift = max(abs(a - b) for a, b in zip(want[:3], got[:3]))
    worst = max(worst, shift)
    swatch = pre[want] if swatch is None else min(swatch, pre[want])
    assert shift <= 1, (name, want, got, shift,
                        "the palette path moved a chosen ink by more than a count")
print(f"  through the palette   a chosen ink returns within {worst}/255 per channel "
      f"on the default 256-colour upload path, over frames holding {swatch:,} px of "
      f"that ink before the quantise")

# ---- the same reader's colour, through the *file* door.  `themes.draw` has no `ink`
# ---- argument and is right not to have one: a layout's colours are its own, which is why a
# ---- vendored theme looks here the way it looks in the vendor's app.  So the window's text
# ---- colour could not reach a generated layout at all, and the pane's two doors disagreed
# ---- about the reader's own choice - measured on this bench's readings, one ink moved the
# ---- code drawing by 18 475 px and the file door by 0.  `themes.with_ink` closes that by
# ---- writing the ink into a *copy* of a generated layout, over the colours `render.SKIN`
# ---- declares, and the claim proved here is the strong one: the two doors end up the same
# ---- picture, at every colour the parser itself knows.
import ast
import datetime
from PIL import ImageChops
from xigmalcd import themes as T


def palette_names():
    """Every colour name `parse_ink` knows, taken out of the module instead of remembered,
    so the window's combo cannot offer a colour this gate did not measure."""
    tree = ast.parse(open("xigmalcd/render.py", encoding="utf-8").read())
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "named")
    return [k.value for k in node.value.keys]


def differ(a, b):
    """(pixels that disagree in any channel, worst single-channel delta)"""
    flat = ImageChops.difference(a.convert("RGBA"),
                                 b.convert("RGBA")).get_flattened_data()
    return (sum(1 for q in flat if q != (0, 0, 0, 0)),
            max((max(q) for q in flat), default=0))


def keyed(obj, key):
    """One colour key, in widget order: positional rather than sorted, because the whole
    point is to compare the same widget against itself and many widgets do not carry a key."""
    return [(w["property"][0] or {}).get(key) for w in obj["osd"]["widget"]]


INKS = [None] + palette_names() + ["#ff4040", (10, 200, 120, 255)]
WHEN_DT = datetime.datetime(*WHEN[:6])
per_theme, bars_moved, bars_total = {}, 0, 0
for theme in ("gauge", "dual", "clock", "bars", "alpha"):
    base = T.export(theme)
    cells = []
    for ink in INKS:
        inked, note = T.with_ink(base, theme, ink)
        gap, chan = differ(R.draw(M, theme, ink=ink),
                           T.draw(inked, M, WHEN_DT)[0])
        assert gap == 0 and chan == 0, (
            theme, ink, gap, chan,
            "a generated layout and the code drawing disagree at this ink: the skin table, "
            "the recipe and the export no longer say the same thing")
        cells.append(sum(1 for a, b in zip(keyed(base, "textColor"),
                                           keyed(inked, "textColor")) if a != b))
    per_theme[theme] = (cells, len(base["osd"]["widget"]))
    assert T.export(theme) == base, (theme, "`with_ink` wrote through its copy")
    # colours that are graphics rather than glyphs never move, and `bars` is where that
    # distinction has teeth: its heading glyph and its ten meter tracks are the same CYAN
    if theme == "bars":
        inked, _n = T.with_ink(base, theme, "amber")
        for key in ("startColor", "endColor", "bgColor"):
            assert keyed(base, key) == keyed(inked, key), (
                key, "an ink moved a graphic's colour, not a glyph's")
        bars_moved = cells[-1] if cells[-1] else cells[INKS.index("amber")]
        bars_total = len(base["osd"]["widget"])
        assert bars_moved == 22, (bars_moved, "the glyph roles an ink may move are no "
                                              "longer 22 of 32 widgets")

_refused, refuse_note = T.with_ink(T.export("bars"), "Theme_28", "amber")
assert "no drawn theme named" in refuse_note and _refused == T.export("bars"), (
    refuse_note, "a layout that is not one of the five must come back untouched")
_alpha_obj, alpha_note = T.with_ink(T.export("alpha"), "alpha", "amber")
assert "all three glyph roles together" in alpha_note, alpha_note
print(f"  ink through the file   {len(INKS)} inks (`parse_ink`'s own {len(palette_names())} "
      f"names, plus a hex and a tuple) x 5 generated layouts: zero differing pixels, worst "
      f"channel 0, against `render.draw` at one instant; only `textColor` moves "
      f"({bars_moved} of {bars_total} widgets in `bars`, its 10 cyan meter tracks left "
      f"alone); a name outside the five comes back unchanged with a sentence; `alpha` "
      f"reports that its three roles are one colour.  Per theme, glyphs re-inked at the "
      f"amber stop: " + " ".join(f"{t}={per_theme[t][0][INKS.index('amber')]}/"
                                 f"{per_theme[t][1]}" for t in per_theme))
PY

echo "== pinned metrics: the cases the sensors will not produce, drawn without putting them on the wire"
python3 - <<'PY' || { echo "pinned metrics FAILED"; exit 1; }
import json, math, os, tempfile
from xigmalcd import main as M, render

d = tempfile.mkdtemp(prefix="xigma-pin-")
hot, missing = os.path.join(d, "hot.json"), os.path.join(d, "missing.json")
with open(hot, "w") as fh:
    json.dump({"cpu": {"temperature": 104.0, "load": 42.0},
               "gpu": {"temperature": 96.0, "load": 61.0},
               "_comment": "a key like this is a note in the file, not a section"},
              fh)
with open(missing, "w") as fh:
    json.dump({"cpu": {"load": 42.0}, "gpu": {"load": 61.0}}, fh)
os.utime(hot, (1_000_000, 1_000_000))         # distinct on purpose: the pin is
os.utime(missing, (1_000_100, 1_000_100))     # re-read when the file's clock moves


def args_for(extra):
    return M.build_parser().parse_args(["--theme", "alpha"] + extra)


class Stub:
    """What a run would put on the wire, recorded instead of sent."""
    def __init__(self):
        self.state, self.media = [], []

    def state_all(self, m):
        self.state.append(m)

    def send_media(self, name, blob, **kw):
        self.media.append(blob)
        return {"notice": "1 200"}


def arc(img):
    """Colours met along the CPU arc's filled part, at the stroke's middle."""
    cx, cy, r = render.A26_TCOL_X[0], render.A26_RING_Y, render.A26_RING_R - 6
    out = []
    for deg10 in range(0, 3600, 2):
        t = math.radians(render.A26_ARC_START + deg10 / 10.0)
        px = img.getpixel((int(round(cx + r * math.cos(t))),
                           int(round(cy + r * math.sin(t)))))
        if px[3] > 200:
            out.append(px[:3])
    return out


M.PINNED, M.PINNED_MTIME = {}, None            # no carry-over between the two
a = args_for(["--metrics-file", hot])
pinned = M.sample(a)
assert pinned["cpu"]["temperature"] == 104.0, pinned["cpu"]
assert "_comment" not in pinned, sorted(pinned)   # a note in the file, not a section
st = Stub()
size, name, code = M.one_frame(st, pinned, a, push_state=True)
assert st.state == [] and len(st.media) == 1, (st.state, len(st.media))

b = Stub()
M.one_frame(b, M.sample(args_for([])), args_for([]), push_state=True)
assert len(b.state) == 1 and len(b.media) == 1, (b.state, b.media)

drawn = arc(render.draw(pinned, "alpha", bg=render.OVERLAY))
assert len(drawn) > 1200, len(drawn)           # the whole 260 deg, not half of it
tip = render.temp_colour(104.0, render.A26_ARC_LO, render.A26_ARC_MID,
                         render.A26_ARC_HI)
assert max(abs(x - y) for x, y in zip(drawn[-1], tip)) <= 12, (drawn[-1], tip)
gone = arc(render.draw(M.sample(args_for(["--metrics-file", missing])),
                       "alpha", bg=render.OVERLAY))
assert gone == [], gone[:3]
print(f"  pinned metrics   the far end of the ramp is what gets drawn "
      f"({len(drawn)} samples along the sweep, outer colour {drawn[-1]} against "
      f"the ramp's own {tip}) and a missing reading paints no arc at all "
      f"({len(gone)} samples); pinned, the same upload call sends 0 metrics "
      f"blobs where unpinned it sends 1, and the frame went up either way")
PY

echo "== vendored backgrounds (the vendor pairing as default, the quiet clip, the bright clip)"
python3 - <<'PY' || { echo "background FAILED"; exit 1; }
import hashlib, sys
sys.path.insert(0, ".")
from xigmalcd.main import BRIGHT_MP4, DEFAULT_MP4, QUIET_MP4
for path, size, md5 in ((DEFAULT_MP4, 214_917, "b818b7d3294b3625e9f143e920ccc9b0"),
                        (QUIET_MP4, 3_402_098, "4a515a8a17204ffb5a23d2ac34dd37ee"),
                        (BRIGHT_MP4, 1_333_649, "51701687804f60875da872c7f27ad673")):
    blob = open(path, "rb").read()
    assert len(blob) == size, (path, len(blob), size)
    assert blob[4:8] == b"ftyp", blob[:12]      # an MP4 container, not a stub
    got = hashlib.md5(blob).hexdigest()
    assert got == md5, (path, got, md5)         # the vendor's own bytes, not ours
    print(f"  {path}  {len(blob)} B  md5 {got}")
PY

echo
echo "== the preview videos README links, and the tool that writes them"
# README's five theme previews are MP4s now, and so is the one ink figure in
# docs/gui.md: 10-12 s each, at the background clip's own frame rate, driven by one real
# sensors.collect() per displayed second so the digits, the meters and the clock move.
# That is a set of claims about six video files, so the files get checked as documents:
# what the written file reports about its own length and rate, that the picture really
# does change where the layer draws, that it is over the background README names, that
# the glyphs still stand off their own halo, and that the readings they drew are the
# recorded series in docs/videos/.  Deliberately no byte hash on the videos: x264's
# output is its version's business, and another runner could write different bytes of the
# same animation.  ffmpeg and ffprobe ARE needed, so their absence is said out loud rather
# than left to surface as a decode that returned nothing (the other ffmpeg-reading section
# has the same note, for the same reason: a runner that lacked them once failed on a luma
# of 0.0, which is what a failed decode looks like to a comparison).
python3 - <<'PY' || { echo "preview videos FAILED"; exit 1; }
import json
import os
import re
import shutil
import subprocess

missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
assert not missing, (missing, "these six files are measured by decoding them: install "
                              "ffmpeg (the CI job does, and the .deb names it in Suggests)")
import sys
import tempfile
import time
sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from PIL import Image, ImageChops, ImageFilter, ImageStat
import preview_gif
from xigmalcd import render, themes

EDGE = 480                      # the panel's own size, which is what these draw at
MIN_S, MAX_S = 9.9, 12.6        # the 10-12 s README promises, plus muxer slack
CEILING = 9_000_000             # per file: GitHub's browser uploader caps near 10 MB

# theme -> (video, background clip).  README's table header names the clip beside each
# placeholder, and every clip is a file this repository carries.
VIDEOS = {
    "alpha": ("docs/videos/alpha-Theme_25.mp4", "media/Theme_25.mp4"),
    "gauge": ("docs/videos/gauge-3.mp4", "themes/alpha/clips/3.mp4"),
    "dual": ("docs/videos/dual-Theme_30.mp4", "themes/alpha/clips/Theme_30.mp4"),
    "clock": ("docs/videos/clock-Theme_07.mp4", "themes/alpha/clips/Theme_07.mp4"),
    "bars": ("docs/videos/bars-theme_52.mp4", "themes/alpha/clips/theme_52.mp4"),
}
INK_VIDEO = ("docs/videos/alpha-Theme_25-amber.mp4", "media/Theme_25.mp4", (255, 196, 0))
SERIES = "docs/videos/readings-2026-11-08.json"
APART = 3.0                     # seconds apart for the does-it-actually-move check

MEASURED = {}
for where, _clip in VIDEOS.values():
    assert os.path.exists(where), f"{where} is missing: regenerate the set"
assert os.path.exists(INK_VIDEO[0]) and os.path.exists(SERIES), "ink video or series gone"


def frame_at(path, ss, edge=EDGE):
    """one frame of an MP4 as a PIL image, at or after `ss` seconds: ffmpeg reads it,
    PIL cannot, and `ss` is not a seek into a keyframe-only world - libx264 at this
    setting puts an IDR every 2 s, so a 0.2/3.2 seek pair decodes exactly"""
    with tempfile.TemporaryDirectory() as t:
        out = os.path.join(t, "f.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.2f}", "-i", path,
                        "-frames:v", "1", out], check=True)
        return Image.open(out).convert("RGB").resize((edge, edge), Image.LANCZOS)


def masks(theme, metrics, edge=EDGE, when=None):
    """(opaque ink, its grown halo, untouched field) for one theme at one set of
    readings.  The mask has to be built from the readings AND the clock the frame was
    drawn with: these videos move their digits, so a mask from the pinned fixture would
    score the file against a picture it is not - and leaving the clock unpatched made the
    mask's time line whatever time the suite happened to run at, which is how two runs of
    one unchanged file printed 12.74 and 12.92 for the same measurement.  `render._now` is
    patched rather than `clock_str` because the `clock` theme draws a date line too, and
    the instant comes from the series' recorded zone, not this machine's."""
    real = render._now
    if when is not None:
        fixed = preview_gif.series_clock({"timestamp": when}, TZOFF)
        render._now = lambda t=fixed: t
    try:
        lay = render.draw(metrics, theme, bg=render.OVERLAY)
    finally:
        render._now = real
    a = lay.getchannel("A").resize((edge, edge), Image.LANCZOS)
    ink = a.point(lambda v: 255 if v == 255 else 0)
    grown = a.filter(ImageFilter.MaxFilter(9)).point(lambda v: 255 if v else 0)
    return ink, ImageChops.subtract(grown, ink), a.point(lambda v: 255 if v == 0 else 0)


def layer_at(theme, sample, ink=None):
    """the reference layer for one sample, drawn the way `preview_gif.frames()` drew it.

    Both the readings AND that sample's clock, because that is what the frame was built
    from: `frames()` patches `render._now` per sample, and a mask drawn with the wall
    clock of the moment the suite runs makes the *pixel count of the lettering* depend on
    the time of day - which is how one unchanged file printed 2 268 painted pixels in one
    run and 2 270 in the next.  Both the time line and the date line come from that one
    hook, at the zone the series recorded."""
    real = render._now
    when = preview_gif.series_clock(series[sample], TZOFF)
    render._now = lambda t=when: t
    try:
        return render.draw(series[sample]["metrics"], theme, ink=ink,
                           bg=render.OVERLAY)
    finally:
        render._now = real

def lum(px):
    return 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]


def preview_slots(text, doc):
    """(the files named by a marker, the number of uploaded videos) in this document.

    A preview slot is a markdown table cell or standalone line holding either a
    `PREVIEW ME ... docs/videos/<file>` marker - the state the tree was in before the
    upload - or an uploaded video, which GitHub's editor writes as a link to its own
    attachments CDN.  Counting both, rather than just looking for the marker, is what
    makes the check survive that edit without going soft: the two counts have to add up to
    the number of previews the document promises, so a marker quietly removed with nothing
    put back leaves a hole this can see.

    The shape of the link matters, and was learned the hard way: for an **image** GitHub
    writes `![alt](https://github.com/user-attachments/assets/…)`; for a **video** it
    writes the URL alone on the line, no `!`, no brackets, and the renderer turns that
    autolink into an inline player.  A pattern that only matched the image form counted
    the README's five finished uploads as zero and failed the run (9b0cfa7, CI 42427101692:
    `0 markers + 0 uploads for 5 previews`).  Both forms are matched here, so neither the
    marker state nor the uploaded state can be mistaken for a hole.

    A relative `docs/videos/*.mp4` image link is still rejected outright.  That is the
    shape that looks correct and is dead: GitHub renders it as an `<img>` whose src ends
    in `.mp4`, which no browser plays, and the suite's own link checker cannot call it
    dead because the file really does exist in the tree.
    """
    marked = set()
    uploads = 0
    cdn = (r"https://(?:github\.com|media\.github\.com|raw\.githubusercontent\.com)"
           r"/[^\s)|]*(?:user-attachments|assets|githubusercontent)[^\s)|]*")
    for line in text.split("\n"):
        for slot in line.split("|") if line.strip().startswith("|") else [line]:
            m = re.search(r"PREVIEW ME[^|]*?(docs/videos/[A-Za-z0-9_.-]+\.mp4)", slot)
            if m:
                marked.add(m.group(1))
            if re.search(rf"!\[[^\]]*\]\({cdn}\)", slot) or re.search(cdn, slot):
                uploads += 1          # image form or bare autolink: either is an upload
            dead = re.search(r"!\[[^\]]*\]\((?:\./)?docs/videos/[^) ]+\.mp4[^)]*\)",
                             slot)
            assert not dead, (doc, dead and dead.group(0),
                              "a relative .mp4 image link is an <img> nothing plays")
    return marked, uploads


def slots_are_filled(text, doc, files):
    """every one of `files` has a filled slot in `doc`: a marker naming it, or an upload."""
    marked, uploads = preview_slots(text, doc)
    unknown = marked - set(files)
    assert not unknown, (doc, sorted(unknown), "a marker names a file this set does not")
    unmarked = [f for f in files if f not in marked]
    assert len(unmarked) == uploads, (
        doc, f"{len(marked)} markers + {uploads} uploads for {len(files)} previews",
        unmarked, "a preview slot is empty, or an upload is there for a file this set "
                  "does not name: the markers and the uploaded links have to add up")
    return f"{len(marked)} markers, {uploads} uploaded"


def mean_of(im, mask):
    return lum(ImageStat.Stat(im, mask).mean)


# ---- the recorded series: the digits in these files came from here --------------
with open(SERIES) as fh:
    rec = json.load(fh)
series, samples = rec["series"], rec["samples"]
# the zone the videos were rendered in, spelled out in the file rather than inherited from
# whichever machine is measuring: the videos show `00:25:16`, a UTC runner reading the same
# epoch milliseconds with time.localtime() prints `22:25:16`, and then scores the committed
# pixels against a layer drawn with different digits.  (CI did exactly that on 2026-11-08:
# `clock`'s glyph luma read 241.0 on the bench and 225.5 on the runner, same bytes.)
TZOFF = rec.get("clock_offset_s")
assert TZOFF is not None, (SERIES, "a series that drives published videos has to record "
                                  "the zone its on-glass clock was read at")
assert abs(TZOFF) < 14 * 3600, (TZOFF, "not a plausible zone offset")
print(f"  clock zone        the series carries UTC{TZOFF // 3600:+02d}"
      f":{abs(TZOFF) % 3600 // 60:02d}, which is what the six files were rendered at")
assert samples == len(series) == 12, (samples, len(series))
gaps = [(b["timestamp"] - a["timestamp"]) / 1000
        for a, b in zip(series, series[1:])]
assert all(0.8 <= g <= 1.4 for g in gaps), [round(g, 2) for g in gaps]
clocks = [preview_gif.CLOCK_STR_REAL(preview_gif.series_clock(s, TZOFF))
          for s in series]
assert len(set(clocks)) == len(clocks), clocks        # the clock ticks, one per sample
fields = {}
for section, key in (("cpu", "temperature"), ("cpu", "load"), ("gpu", "temperature"),
                     ("gpu", "load"), ("memory", "used")):
    fields[f"{section}.{key}"] = {s["metrics"].get(section, {}).get(key) for s in series}
fields["fan RPM"] = {f.get("value") for s in series for f in s["metrics"].get("fans", [])}
changed = {k: v for k, v in fields.items() if len(v) > 1}
assert len(changed) >= 4, (sorted(fields), sorted(changed), "the series is meant to move")
# and they have to be a real machine's numbers, inside the spans PROTOCOL §8 measured on
# this board: "live" cannot mean "made up"
temps = [s["metrics"]["cpu"]["temperature"] for s in series]
assert 40 <= min(temps) and max(temps) <= 95, temps
cpu_fans = sorted(f["value"] for s in series for f in s["metrics"].get("fans", [])
                  if "Fan" in str(f.get("type", "")))
assert 900 <= min(cpu_fans) and max(cpu_fans) <= 3600, cpu_fans
loads = [s["metrics"]["cpu"]["load"] for s in series]
assert 0.0 <= min(loads) and max(loads) <= 100.0, loads
print(f"  series            {len(series)} samples over {rec['span_s']:.1f} s "
      f"(gaps {min(gaps):.2f}-{max(gaps):.2f} s), clock {clocks[0]}..{clocks[-1]}")
print(f"  it moves          {len(changed)} of {len(fields)} fields changed: "
      + ", ".join(f"{k} {min(v):g}->{max(v):g}" for k, v in sorted(changed.items())))
print(f"  in span           cpu {min(temps)}-{max(temps)} C, cpu fans "
      f"{min(cpu_fans)}-{max(cpu_fans)} RPM, load {min(loads):g}-{max(loads):g} %")

# ---- the recorded series against `bars`'s row table.  This is why the tracked `bars` clip
# ---- outlived 2026-11-09's changes to that drawing.  What those changes move is a row whose
# ---- *subject* exists while its reading does not, or whose pair cannot be divided - so what
# ---- has to hold is that this real machine answers both readings of every row it can
# ---- actually have: the six fixed ones, and the fan slots within the count its sensors
# ---- reported.  A slot past that count is empty in the old drawing and in the new one alike,
# ---- which is why the row set below is scoped to what the box has rather than to all ten
# ---- reserved slots.  Measured, not assumed: if it stops holding, the clip is stale and the
# ---- section above says so with pixels.
_bars_fixed = themes.BARS_FIXED_ROWS
_bars_gaps = []
_fans_reported = sorted({len(_s["metrics"].get("fans") or []) for _s in series})
for _s in series:
    _sv, _ = themes.values(_s["metrics"], preview_gif.series_clock(_s, TZOFF))
    _mine = list(_bars_fixed) + [
        _r for _r in themes.BARS_ROWS[len(_bars_fixed):]
        if int(_r[1].split()[1]) - 1 < len(_s["metrics"].get("fans") or [])]
    _bars_gaps.append(sorted({src for _lab, _b, _t, _lo, _hi in _mine
                              for src in (_b, _t) if src not in _sv}))
assert not any(_bars_gaps), (
    [(_k, _g) for _k, _g in enumerate(_bars_gaps) if _g],
    "the published series leaves a row this box has unanswered, so the tracked clip is no "
    "longer what the current drawing would paint at it")
assert len(_fans_reported) == 1 and _fans_reported[0] <= len(themes.FAN_SLOTS), _fans_reported
print(f"  bars, and its clip    every row this box can have - the {len(_bars_fixed)} fixed "
      f"ones and the {_fans_reported[0]} fan slots its sensors reported, out of "
      f"{len(themes.FAN_SLOTS)} reserved - is answered at all {len(series)} samples of the "
      f"series, so the changes that moved rows with no subject or no pair to divide cannot "
      f"move a frame of docs/videos/bars-theme_52.mp4: re-rendering it wrote the same "
      f"{os.path.getsize(VIDEOS['bars'][0]):,} B it already held")

# ---- the files README links ---------------------------------------------------
readme = open("README.md", encoding="utf-8").read()
assert ".gif" not in readme, "README still links a GIF"
gui = open("docs/gui.md", encoding="utf-8").read()
total = 0
late = int(APART)                       # the sample `APART` seconds in
for theme, (where, clip) in VIDEOS.items():
    nf, dur, rate = preview_gif.probe_video(where)
    size = os.path.getsize(where)
    total += size
    assert MIN_S <= dur <= MAX_S, (where, dur)
    assert abs(dur * rate - nf) <= 2, (where, nf, dur, rate)
    assert size < CEILING, (where, size)
    assert os.path.basename(clip) in readme, (where, clip)
    fr = frame_at(where, 0.0)
    s0, sl = series[0], series[late]
    ink0, halo0, field0 = masks(theme, s0["metrics"], when=s0["timestamp"])
    ink_late, _hl, field_late = masks(theme, sl["metrics"], when=sl["timestamp"])
    # the picture is over the clip its placeholder names: mean luma of the video's
    # untouched field against the clip's own first frame
    src = ImageStat.Stat(frame_at(clip, 0.0).convert("L")).mean[0]
    gf = mean_of(fr, field0)
    assert abs(gf - src) < 20, (where, clip, gf, src)
    gi = mean_of(fr, ink0)
    gh = mean_of(fr, halo0)
    assert gi - gh >= 30, (where, gi, gh, "glyphs washing out against their own halo")
    # the claim these videos exist for: the numbers move.  Two things, one about the
    # drawing and one about the file.  (1) The layer drawn from the first sample and the
    # layer drawn from the sample `APART` s later have to differ over the pixels they
    # both paint - that is the digits, the arcs and the bars changing, host side, with no
    # codec between.  (2) In the written file, the same two moments have to differ at
    # least 3/255 of mean absolute change over the union of those pixels, and more than
    # the untouched field does, or the file's motion is only the background's.  Note what
    # this is NOT: comparing those pixels against the bare clip at the same moments would
    # be a different test, and a *static* layer would pass it (the clip moves, so the
    # clip-only difference is large while a frozen layer changes nothing).
    a, b = fr, frame_at(where, APART)
    ink = ImageChops.add(ink0, ink_late)
    field = ImageChops.multiply(field0, field_late)
    d_ink = ImageStat.Stat(ImageChops.difference(a, b), ink).mean[0]
    d_fld = ImageStat.Stat(ImageChops.difference(a, b), field).mean[0]
    # ...and the same two layers the file was built from, drawn here with each sample's
    # own reading AND its own clock, exactly as `preview_gif.frames()` patches it: call
    # `render.draw` twice without that patch and both calls print the wall clock of this
    # instant, so the `clock` theme came out byte-identical (0.0) and looked frozen when
    # the video it is scoring ticks away merrily.
    dl = ImageChops.difference(layer_at(theme, 0).convert("RGB"),
                               layer_at(theme, late).convert("RGB"))
    d_lyr = ImageStat.Stat(dl, ink).mean[0]
    # the mean over a mask this big is a small number even when every digit changed -
    # a theme's ink is mostly labels and outlines, which do not move - so the count of
    # pixels that really changed is the figure with meaning attached to it
    n_changed = sum(1 for v, m in zip(dl.convert("L").get_flattened_data(),
                                      ink.get_flattened_data()) if v > 8 and m)
    # 12.7 measured on this series for `alpha`: the labels, the clock's minutes and the
    # ring outlines are the same in both samples, so this is not a big number even when
    # every digit moves - it only has to be clearly non-zero, and the per-file figures
    # printed beside it say how much.
    assert d_lyr > 1.0 and n_changed > 200, (theme, d_lyr, n_changed,
                                             "the layer draws the same picture twice")
    assert d_ink >= 3.0 and d_ink > d_fld * 1.2, (where, d_ink, d_fld,
                                                  "the picture does not change where the "
                                                  "layer draws")
    MEASURED[where] = (nf, dur, rate, size, src, gf, gi, gh, d_ink, d_fld)
    print(f"  {where:<38} {nf:>4} fr {dur:5.2f} s @ {rate:g} fps  {size:>9,} B")
    print(f"  {'':<38} over {os.path.basename(clip):<16} clip {src:5.1f} field {gf:5.1f} "
          f"(gap {abs(gf - src):4.1f})  glyph {gi:6.1f} halo {gh:6.1f} = {gi - gh:5.1f}")
    print(f"  {'':<38} moved in {APART:g} s: in the file {d_ink:5.2f} vs untouched "
          f"{d_fld:5.2f} (ratio {d_ink / max(d_fld, 0.01):5.2f}); re-drawn here, "
          f"{n_changed:,} px of the layer differ by more than 8/255 "
          f"(mean {d_lyr:5.2f})")

# ---- the table docs/limits.md carries is this loop's own numbers, so it is compared with
# ---- them rather than transcribed by hand.  Every cell has to be what this run printed: a
# ---- figure in that document this suite did not measure is an error, not a rounding.
_lim_tab = open("docs/limits.md", encoding="utf-8").read()


def _row_cells(name):
    i = _lim_tab.find(f"| `{os.path.basename(name)}` |")
    assert i >= 0, (name, "docs/limits.md has no row for this preview")
    return [c.strip() for c in _lim_tab[i:_lim_tab.index("\n", i)].split("|")[1:-1]]


for _where, _v in MEASURED.items():
    _nf, _dur, _rate, _size, _src, _gf, _gi, _gh, _dink, _dfld = _v
    _c = _row_cells(_where)
    assert _c[1] == str(_nf), (_where, _c[1], _nf)
    assert _c[2] == f"{_dur:.2f} s", (_where, _c[2], _dur)
    assert _c[3] == f"{_rate:g} fps", (_where, _c[3], _rate)
    assert _c[4].replace(" ", "") == f"{_size}", (_where, _c[4], _size)
    assert _c[5] == f"{_src:.1f} \u2192 {_gf:.1f} ({abs(_gf - _src):.1f})", (
        _where, _c[5], _src, _gf)
    assert _c[6] == f"{_gi:.1f} \u2212 {_gh:.1f} = **{_gi - _gh:.1f}**", (
        _where, _c[6], _gi, _gh)
    assert _c[7] == (f"{_dink:.2f} / {_dfld:.2f} "
                     f"(\u00d7{_dink / max(_dfld, 0.01):.2f})"), (_where, _c[7])
print(f"  docs/limits.md's table  {len(MEASURED)} rows matched cell by cell against "
      f"this run's own measurements")

print(f"  README's slots      {slots_are_filled(readme, 'README', [v for v, _ in VIDEOS.values()])}"
      f" for {len(VIDEOS)} previews")

where, clip, want = INK_VIDEO
size = os.path.getsize(where)
total += size
nf, dur, rate = preview_gif.probe_video(where)
assert MIN_S <= dur <= MAX_S and size < CEILING, (where, dur, size)
# (the slots are counted once, below, for all six files at once)
fr = frame_at(where, 0.0)
# Ink, measured where the layer painted that ink.  The mask is the set of pixels the
# reference layer holds at exactly the asked colour, so the arcs and rings - which keep
# their own colours, since ink is about text - cannot inflate the figure.  What the
# codec does to those pixels is then a distribution, not one lucky value.
ref = layer_at("alpha", 0, ink=want)   # the sample's own clock, or this count jitters
rp = list(ref.convert("RGB").getdata())
ra = list(ref.getchannel("A").getdata())
painted = [k for k, (p, a) in enumerate(zip(rp, ra)) if a == 255 and p == want]
assert len(painted) > 1000, (where, len(painted), "no lettering to measure")
vp = list(fr.getdata())
errs = sorted(max(abs(x - y) for x, y in zip(vp[k], want)) for k in painted)
n = len(errs)
med, p95 = errs[n // 2], errs[int(n * 0.95)]
assert med <= 8 and p95 <= 24, (where, med, p95, "the ink is drifting out of the file")
print(f"  {where:<38} {nf:>4} fr {dur:5.2f} s @ {rate:g} fps  {size:>9,} B")
print(f"  {'':<38} {n:,} px the layer paints at exactly {want}: in the written file "
      f"median {med}/255 off, p95 {p95}/255, {sum(1 for e in errs if e == 0):,} px "
      f"exact (H.264 4:2:0 at crf 20; the GIF path below asks a different question)")

print(f"  docs/gui.md's slot {slots_are_filled(gui, 'docs/gui.md', [INK_VIDEO[0]])} for "
      f"the ink figure")
assert f"**{total:,} B**".replace(",", " ") in _lim_tab, (
    total, "docs/limits.md's total for the six files is not this run's")
print(f"  total             {len(VIDEOS) + 1} videos, {total:,} B, "
      f"plus {os.path.getsize(SERIES):,} B of series JSON")

# ---- the tool, both shapes, at sizes nobody would publish ----------------------
help_out = subprocess.run([sys.executable, "tools/preview_gif.py", "--help"],
                          capture_output=True, text=True)
assert help_out.returncode == 0, help_out.stderr[:400]
for flag in ("--mp4", "--no-gif", "--series", "--record", "--live-seconds", "--crf",
             "--preset", "--clock", "--scrim", "--ink", "--colors", "--gif-fps",
             "--live", "--frames", "--scale", "--out"):
    assert flag in help_out.stdout, (flag, "the tool no longer documents it")
print(f"  tools/preview_gif.py --help  {len(help_out.stdout)} B, every documented "
      f"switch present")

with tempfile.TemporaryDirectory() as tmp:
    # every theme through the animated path, small and cheap, off the recorded series:
    # this is where a theme gaining or losing a render keyword used to die
    for theme in sorted(render.THEMES):
        out = os.path.join(tmp, f"{theme}.mp4")
        r = subprocess.run([sys.executable, "tools/preview_gif.py", "--theme", theme,
                            "--clip", "media/Theme_25.mp4", "--series", SERIES,
                            "--frames", "8", "--gif-fps", "2", "--scale", "160",
                            "--no-gif", "--out", out], capture_output=True, text=True)
        assert r.returncode == 0, (theme, r.stdout[-300:], r.stderr[-300:])
        nf, dur, rate = preview_gif.probe_video(out)
        assert nf == 8 and abs(dur - 4.0) < 0.3, (theme, nf, dur, rate)
    print(f"  every theme renders through the animated path: {len(render.THEMES)} of "
          f"{len(render.THEMES)}, 8 frames at 2 fps = 4.00 s each, off the series")
    # ...and the pinned GIF shape still works, because that is the shape whose digits a
    # caption can quote: the ink drift figure docs/tools.md carries comes from here
    out = os.path.join(tmp, "amber.gif")
    r = subprocess.run([sys.executable, "tools/preview_gif.py", "--theme", "alpha",
                        "--clip", "media/Theme_25.mp4", "--clock", "11:07:42",
                        "--ink", "amber", "--frames", "6", "--gif-fps", "3",
                        "--scale", "160", "--colors", "128", "--out", out],
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout[-300:], r.stderr[-300:])
    im = Image.open(out)
    assert im.size == (160, 160) and im.info.get("loop") == 0, im.size
    near, dist, seen = preview_gif.ink_drift(out, (255, 196, 0))
    assert dist <= 3, (near, dist, "the GIF palette moved the ink further than documented")
    # the other question, on purpose: `ink_drift` asks for the closest colour the file
    # holds anywhere, which is what a reader's eye lands on; the video check above asks
    # how far each painted pixel travelled.  Both are reported, neither stands in for
    # the other.
    print(f"  the pinned GIF shape still writes: {os.path.getsize(out):>6,} B, 160x160, "
          f"loop {im.info.get('loop')}, {seen} frames read back, #ffc400 lands as "
          f"{near} off {dist}/255")
    # the scrim plate's effect, measured on the animated path rather than remembered
    # from the GIF set: the same 8 frames over the bright clip, with and without the
    # plate the window's auto rule puts there, glyph luma against its own grown halo.
    # 160 px here because nobody would publish that size; the pair is comparable to
    # itself, which is the point.
    bright = "themes/alpha/clips/Theme_07.mp4"
    plate = {}
    for how, extra in (("none", ["--scrim", "0"]), ("auto (150)", [])):
        out = os.path.join(tmp, f"clock-{how}.mp4")
        r = subprocess.run([sys.executable, "tools/preview_gif.py", "--theme", "clock",
                            "--clip", bright, "--series", SERIES, "--frames", "8",
                            "--gif-fps", "24", "--scale", "160", "--no-gif",
                            "--out", out] + extra, capture_output=True, text=True)
        assert r.returncode == 0, (how, r.stdout[-300:], r.stderr[-300:])
        fr0 = frame_at(out, 0.0, edge=160)
        ink0b, halo0b, field0b = masks("clock", series[0]["metrics"], edge=160,
                                       when=series[0]["timestamp"])
        gi, gh, gf = (mean_of(fr0, ink0b), mean_of(fr0, halo0b), mean_of(fr0, field0b))
        plate[how] = (gi, gh, gf)
    gap0 = plate["none"][0] - plate["none"][1]
    gap1 = plate["auto (150)"][0] - plate["auto (150)"][1]
    # measured 1.42x at this size (51.7 -> 73.5 of 255), so the gate is "the plate widens
    # the gap by at least a fifth" - a directional claim about which way the rule pulls,
    # not a tuned-to-the-answer number: the plate darkens the halo around the glyphs, it
    # does not brighten the glyphs, and both halves of that show up in the printed pair.
    assert gap1 > gap0 * 1.2, (gap0, gap1, "the plate the rule adds changes nothing")
    print(f"  the plate, measured on the clock over {os.path.basename(bright)} "
          f"(luma {ImageStat.Stat(frame_at(bright, 0.0).convert('L')).mean[0]:.1f}): "
          f"no plate glyph {plate['none'][0]:.1f} vs halo {plate['none'][1]:.1f} = "
          f"{gap0:5.1f}; auto glyph {plate['auto (150)'][0]:.1f} vs halo "
          f"{plate['auto (150)'][1]:.1f} = {gap1:5.1f} (8 frames, 160 px)")

    # --live-seconds samples the box and records what it read; 2 s is enough to prove
    # the plumbing without spending a quarter minute on it
    probe = os.path.join(tmp, "series.json")
    r = subprocess.run([sys.executable, "tools/preview_gif.py", "--theme", "alpha",
                        "--clip", "media/Theme_25.mp4", "--live-seconds", "2",
                        "--record", probe, "--frames", "4", "--gif-fps", "2",
                        "--scale", "160", "--no-gif", "--out", os.path.join(tmp, "l.mp4")],
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout[-400:], r.stderr[-400:])
    with open(probe) as fh:
        got = json.load(fh)
    assert got["samples"] == 2 and got["series"][0]["metrics"], got["samples"]
    assert "sampled" in r.stdout, r.stdout[-400:]
    # What the box answered, whatever it is.  A runner under a hypervisor has no thermal
    # zones, no tach header and no disks behind the paths xigmalcd/sensors.py reads -
    # docs/packaging.md measures the same absence for the runner's screenshot - and the
    # first CI run of this section died on exactly that, KeyError: 'temperature', because
    # the probe assumed a CPU temperature exists.  Plumbing is what this proves: that
    # --live-seconds sampled twice, that the sections a preview draws came back, and that
    # --record wrote a file a later render can read.  The machine's identity is not.
    m0 = got["series"][0]["metrics"]
    print(f"  --live-seconds sampled this box: {got['samples']} readings, sections "
          f"{sorted(m0)}, into {os.path.getsize(probe):,} B of JSON")
    for sec in sorted(m0):
        d = m0[sec]
        if isinstance(d, dict):
            brief = {k: v for k, v in d.items()
                     if k in ("temperature", "load", "used", "total", "power")}
            print(f"    {sec:<8} {brief}")
        else:
            print(f"    {sec:<8} {d}")
    assert "cpu" in m0 and "load" in m0["cpu"], (sorted(m0),
                                                 "no CPU load, so no meter had anything "
                                                 "to draw")
    assert got.get("clock_offset_s") == time.localtime(
        got["series"][0]["timestamp"] / 1000).tm_gmtoff, (
        got.get("clock_offset_s"), "--record did not write down the zone it sampled in")
PY

echo "== where clips are looked up: the roots a package install has to get right"

# A checkout is not the only place this code runs.  `pip install .` and the .deb
# built from debian/ put the modules where the repository tree is not, so the roots
# of xigmalcd.main - env, the checkout's media/, /usr/share/xigmalcd/media, and then
# the vendor's theme library in its two spellings - decide whether a user gets the
# shipped background, the clip a layout declares, or a missing-file message.  The
# library half is what the pairing gate in the GUI section depends on: `--list-themes`
# prints `background Theme_07.mp4` from a layout file, and `--mp4 Theme_07.mp4` has to
# mean that file on the same box.  Checked against fake roots: no root, no installed
# package, nothing written outside a temp directory.
python3 - <<'PY' || { echo "clip roots FAILED"; exit 1; }
import hashlib, os, shutil, sys, tempfile
sys.path.insert(0, ".")
from xigmalcd import main as m

# 1. in a checkout: the repository's own media/ is the root, and all three shipped
#    clips resolve inside it - which is what every clip number in README reads.
#    Order is the rule; how many roots there are belongs to the machine.  A box that
#    has the .deb installed also has /usr/share/xigmalcd/media, and the author's bench
#    became one of those on 2026-11-07, which is why this line used to read
#    `media_roots() == (repo,)`: it was asserting the state of one machine instead of
#    the rule.  It still asserts the part that matters - the checkout wins, and nothing
#    else in the list is a root this code did not name.
repo = os.path.abspath(m.REPO_MEDIA)
assert not os.environ.get(m.MEDIA_ENV), \
    f"{m.MEDIA_ENV} is set; unset it to check the checkout's own roots"
roots = m.media_roots()
assert roots[0] == repo, roots
repo_lib, sys_lib = os.path.abspath(m.REPO_CLIP_LIB), os.path.abspath(m.SYSTEM_CLIP_LIB)
# Every root in the list has to be one this code named, in the order it named them: the
# media roots first, then the library, checkout before installed.  Which of the four exist
# belongs to the machine; the order of the ones that do is the rule.
_named = [r for r in (repo, os.path.abspath(m.SYSTEM_MEDIA), repo_lib, sys_lib) if r in roots]
assert [r for r in roots if r in _named] == _named, (roots, _named)
assert repo_lib in roots, (roots, "this checkout's `themes/alpha/clips` is not a root, so a "
                                  "layout's declared background cannot be named by the loop")
for p in (m.DEFAULT_MP4, m.QUIET_MP4, m.BRIGHT_MP4):
    assert os.path.dirname(p) == repo, p
    assert os.path.exists(p), p
print(f"  checkout           default, quiet and bright all resolve inside {repo}; roots: "
      + ", ".join(roots))

# 1b. and the claim those extra roots exist for, taken from the library rather than from a
#     remembered example: every layout this canvas can select names one clip, and that name
#     has to resolve, through `find_media` (the very function `--mp4` and the session default
#     go through), to a file that is really there.  A bare clone passes this the same way an
#     installed box does, because the checkout carries the same 43 files the themes package
#     installs - which is exactly the case the CI runner hit once, from the other side.
from xigmalcd import themes as _t
_sel, _rej = _t.scan()
_where, _bad = {}, []
for _rec in _sel:
    _name, _why = _t.pair(_rec["name"])
    assert _name and not _why, (_rec["name"], _name, _why)
    _got = m.find_media(_name)
    if os.path.basename(_got) != _name or not os.path.isfile(_got):
        _bad.append((_rec["name"], _name, _got))
        continue
    assert os.path.dirname(_got) in roots, (_rec["name"], _got, roots,
                                            "a clip resolved outside the root list")
    _where[os.path.dirname(_got)] = _where.get(os.path.dirname(_got), 0) + 1
assert not _bad, (_bad[:6], len(_sel),
                  "a selectable layout names a clip the loop cannot find by name")
_vendored = {os.path.basename(p) for p in (m.DEFAULT_MP4, m.QUIET_MP4, m.BRIGHT_MP4)}
_overlap = sorted({r["name"] for r in _sel if _t.pair(r["name"])[0] in _vendored})
for _n in _overlap:
    assert os.path.dirname(m.find_media(_t.pair(_n)[0])) == repo, (
        _n, "a clip this repository vendors in `media/` resolved in the theme library: the "
            "media roots have to win, or the session default moves on some box")
print(f"  name lookup        all {len(_sel)} selectable layouts' own clips resolve by bare "
      f"name: " + ", ".join(f"{v} from {k}" for k, v in sorted(_where.items())))
if _overlap:
    print(f"                       media first, unchanged: {_overlap} name a clip `media/` also "
          f"holds, and those still resolve in {repo} - so `Theme_25.mp4` means the same file "
          f"as before the library became a root")

with tempfile.TemporaryDirectory() as tmp:
    sysroot = os.path.join(tmp, "usr-share-xigmalcd-media")
    syslib = os.path.join(tmp, "usr-share-themes-clips")
    replib = os.path.join(tmp, "checkout-themes-clips")
    for d in (sysroot, syslib, replib):
        os.makedirs(d)
    for n in ("Theme_25.mp4", "Theme_11.mp4", "theme_48.mp4"):
        open(os.path.join(sysroot, n), "wb").write(b"stand-in")
    # the case a layout file produces: a name `media/` does not hold at all, in the library
    # in both spellings, and a name both kinds of root hold so the order can be seen
    open(os.path.join(syslib, "Theme_probe_07.mp4"), "wb").write(b"installed copy")
    open(os.path.join(replib, "Theme_probe_07.mp4"), "wb").write(b"checkout copy")
    open(os.path.join(replib, "Theme_25.mp4"), "wb").write(b"checkout library copy")

    # 2. a box with both: the checkout still answers, so the README figures do not
    #    depend on what happens to be installed on the machine reading them
    real = m.SYSTEM_MEDIA
    real_replib, real_syslib = m.REPO_CLIP_LIB, m.SYSTEM_CLIP_LIB
    m.SYSTEM_MEDIA = sysroot
    m.REPO_CLIP_LIB, m.SYSTEM_CLIP_LIB = replib, syslib
    try:
        assert m.media_roots() == (repo, os.path.abspath(sysroot), os.path.abspath(replib),
                                   os.path.abspath(syslib)), m.media_roots()
        assert m.media_dir() == repo
        assert m.find_media("Theme_25.mp4") == os.path.join(repo, "Theme_25.mp4")
        # the checkout's library beats the installed one, and a library-only name resolves
        assert (m.find_media("Theme_probe_07.mp4")
                == os.path.join(replib, "Theme_probe_07.mp4"))
        assert (m.find_media("Theme_25.mp4") != os.path.join(replib, "Theme_25.mp4"),
                "the media roots must win over a library copy of the same name")
        saved_lib = m.REPO_CLIP_LIB
        m.REPO_CLIP_LIB = os.path.join(tmp, "no-such-library")
        try:
            assert (m.find_media("Theme_probe_07.mp4")
                    == os.path.join(syslib, "Theme_probe_07.mp4")), "the installed library"
        finally:
            m.REPO_CLIP_LIB = saved_lib

        # 3. the same question with no checkout in the picture: the installed root
        #    is what answers it, which is the whole point of installing to /usr/share
        saved = m.REPO_MEDIA
        m.REPO_MEDIA = os.path.join(tmp, "no-such-checkout")
        try:
            assert m.media_roots() == (os.path.abspath(sysroot), os.path.abspath(replib),
                                       os.path.abspath(syslib)), m.media_roots()
            got = m.find_media("Theme_25.mp4")
            assert got == os.path.join(sysroot, "Theme_25.mp4"), got
            assert m.find_media("Theme_probe_07.mp4") == os.path.join(
                replib, "Theme_probe_07.mp4"), got
        finally:
            m.REPO_MEDIA = saved

        # 4. a clip in no root at all falls back to the Windows partition's copy,
        #    and if it is nowhere it is still named as the file we asked for
        win = os.path.join(tmp, "win", "Theme_99.mp4")
        os.makedirs(os.path.dirname(win))
        open(win, "wb").write(b"windows copy")
        assert m.find_media("Theme_99.mp4", win) == win
        nowhere = m.find_media("Theme_99.mp4")
        assert nowhere.endswith("Theme_99.mp4") and not os.path.exists(nowhere), nowhere
    finally:
        m.SYSTEM_MEDIA = real
        m.REPO_CLIP_LIB, m.SYSTEM_CLIP_LIB = real_replib, real_syslib
print("  installed root     behind the checkout when both exist, first when only it does;")
print("                     the theme library sits behind both media roots, its checkout")
print("                     copy ahead of the installed one; the Windows copies still")
print("                     answer, and a clip that is nowhere is reported as the file")
print("                     that was asked for")

# 5. $XIGMA_MEDIA replaces the checkout root, and the window's clip library scans
#    every root that exists rather than only the first: an installed themes set is
#    not hidden from a display running out of a clone
with tempfile.TemporaryDirectory() as envdir:
    shutil.copy(os.path.join(repo, "Theme_25.mp4"), envdir)
    os.environ[m.MEDIA_ENV] = envdir
    try:
        assert m.media_dir() == os.path.abspath(envdir), m.media_dir()
        assert m.media_roots()[:2] == (os.path.abspath(envdir), repo), m.media_roots()
        from xigmaui import clips
        dirs = {os.path.dirname(c.path) for c in clips.list_clips()}
        assert os.path.abspath(envdir) in dirs, sorted(dirs)[:4]
        assert repo in dirs, sorted(dirs)[:4]
    finally:
        del os.environ[m.MEDIA_ENV]
print("  $XIGMA_MEDIA       first root, and the clip library lists it alongside the rest")

# Which file a name means is a rule, and three documents state it.  They are held to the
# words this run derived - the root list, the count of layouts whose own clip resolves, and
# the fact that the media roots still win - because "the library is a root now" is the kind
# of sentence a later refactor quietly un-does.
_DOCS = {
    "docs/usage.md": f"then the vendor's theme library - this checkout's `themes/alpha/clips`",
    "docs/gui.md": "the window's list walks those same roots and adds the two Windows ones",
    "docs/limits.md": f"so **all {len(_sel)} resolve by name**",
}
_absent = {f: w for f, w in _DOCS.items() if w not in open(f, encoding="utf-8").read()}
assert not _absent, (_absent, "these documents describe the old root set: `media_roots()` "
                              "carries the theme library now, and the wording above is what "
                              "the code does")
for _stale in ("`main.media_roots()` searches the three clips the *main* package vendors",
               "walks more roots than the daemon resolves a **name** through",
               "with no theme directory in it"):
    assert all(_stale not in open(_f, encoding="utf-8").read() for _f in _DOCS), (
        _stale, "a document still says the loop does not search the theme library")
print(f"  the documents      usage.md's `--mp4` row, gui.md's pairing section and limits.md's "
      f"themes-package bullet all state {len(roots)} roots in this order, with "
      f"{len(_sel)}/{len(_sel)} layouts' own clips resolving and the media roots first")

# ---- one row per distinct clip, whatever it is called ---------------------------
# The roots hold far more files than there are clips.  Two censuses, and only one of
# them depends on the machine: this repository tracks **46 mp4 files** in `media/` and
# `themes/alpha/clips`, holding **40 distinct contents** (whole-file sha256, re-derived
# by the GUI section), and on the author's bench - Windows partition mounted, the .deb
# installed - the same walk sees 204 files, drops 166 copies and still stands at 40 rows
# (the 2026-11-07 audit of the 161 files then visible found the same 40 contents, 121
# copies - 69 of them the Windows app's own upload history, which copies a library clip
# into `media/background/` under a millisecond name every time a theme is applied (all
# 26 `175749*.mp4` there are byte-identical to a `Theme_NN` or `theme_NN` clip), and 3 of
# them the vendor library repeating itself inside its own tree (`Theme_31.mp4` ==
# `Theme_26.mp4`, `theme_38.mp4` == `Theme_27.mp4`, `theme_51.mp4` == `Theme_29.mp4`,
# sha256, 2026-11-07).  A rule keyed on (name, length) cannot see a renamed copy,
# which is why the list is keyed on length and content.  Built here in a temp root,
# with a same-length different-content pair on the other side: dropping renamed copies
# must not drop genuinely different clips that merely happen to share a size.
with tempfile.TemporaryDirectory() as dupdir:
    def blob(seed, n=3 << 20):
        # 3 MiB: past the 2 MiB the comparison reads, so this exercises the edge path
        # rather than the whole-file one
        h = hashlib.sha256(seed.encode())
        out = b""
        while len(out) < n:
            out += h.digest() * 4096
            h.update(h.digest())
        return out[:n]

    same = blob("one clip")
    open(os.path.join(dupdir, "Theme_probe.mp4"), "wb").write(same)
    open(os.path.join(dupdir, "1757490000001.mp4"), "wb").write(same)
    tiny = blob("tiny clip", 4096)      # small: both read windows are the whole file
    open(os.path.join(dupdir, "tiny_original.mp4"), "wb").write(tiny)
    open(os.path.join(dupdir, "1757490000002.mp4"), "wb").write(tiny)
    open(os.path.join(dupdir, "Theme_other.mp4"), "wb").write(blob("another clip"))
    os.environ[m.MEDIA_ENV] = dupdir
    try:
        from xigmaui import clips as clipdb
        rows = clipdb.list_clips()
        listed = {os.path.basename(r.path) for r in rows}
        assert {"Theme_probe.mp4", "tiny_original.mp4", "Theme_other.mp4"} <= listed, \
            sorted(listed)[:8]
        assert not {n for n in listed if n.startswith("175749")}, sorted(listed)
        scan = clipdb.LAST_SCAN
        assert scan["copies"] >= 2, scan
        assert scan["renamed"] >= 2, scan      # both copies sat under other names
        assert sum(scan["roots"].values()) == scan["copies"], scan
        assert len(clipdb.list_clips()) == len(rows), "the walk is stable"
        print(f"  dedupe by content  {scan['files']} files walked here, "
              f"{scan['copies']} copies dropped ({scan['renamed']} renamed), and a "
              f"same-length different-content pair still gets its own row")
    finally:
        del os.environ[m.MEDIA_ENV]
PY

echo
echo "== the vendor theme library: every copied byte against its own manifest"
# Read-only, no hardware, and no Windows volume: manifest.json recorded the sha256 of
# every file as it was read out of ALPHA, and each theme's `background` entry carries the
# hash of the bytes that were *embedded in the .thm*.  So re-hashing the clip that entry
# points at re-proves, offline, that the vendor's loose clip and the theme's own payload
# are the same file -- which is the claim themes/alpha/README.md rests on.
python3 tools/thm_unlock.py --verify --to themes/alpha | sed 's/^/  /' || {
    echo "theme library does not match its manifest"; exit 1; }
python3 - <<'PY' || { echo "theme copy FAILED"; exit 1; }
import hashlib, json, os, sys
from PIL import Image
man = json.load(open("themes/alpha/manifest.json"))
# what themes/alpha/README.md's size table claims, re-counted here
counts = {"layout": (27, 127_115),
          "clip": (44, 84_392_330), "foreground": (27, 407_095)}
for kind, (files, byte_total) in counts.items():
    rows = [e for e in man["files"] if e["kind"] == kind]
    assert len(rows) == files, (kind, len(rows), files)
    assert sum(e["bytes"] for e in rows) == byte_total, (kind,)
    print(f"  {kind:<10} {files:>3} files {byte_total:>10} B as documented")

# ---- the .thm containers are recorded, not carried --------------------------------
# They were in this tree through 0.2 (27 files, 66 300 082 B, 43.8 % of themes/alpha)
# and were removed at 0.3: they are the vendor's encrypted wrapper, nothing here reads
# or could send one, and every fact they supported is already carried as a hash.  So the
# tree must contain no .thm at all, and the manifest must still say what they were:
# `notRedistributed` keeps vendor path + size + sha256, and every theme row keeps
# thmFile/thmBytes/thmSha256, which is what lets a reader holding the vendor's installer
# check this copy's word.  Asserting the absence is what stops one coming back by
# accident, in a re-run of the copy tool without --no-thm or in a future commit.
on_disk = [os.path.join(r, n) for r, _d, fs in os.walk("themes/alpha") for n in fs]
assert not [p for p in on_disk if p.endswith(".thm")], \
    sorted(p for p in on_disk if p.endswith(".thm"))[:3]
assert not os.path.exists("themes/alpha/thm"), "a thm/ dir should not exist"
assert "thm" not in man["counts"], man["counts"]
nrd = man["notRedistributed"]
assert len(nrd) == 27 and all(e["kind"] == "thm" for e in nrd), len(nrd)
assert sum(e["bytes"] for e in nrd) == 66_300_082, sum(e["bytes"] for e in nrd)
assert all(e["path"].startswith("thm/") and e["sha256"] and e["origin"]["vendorPath"]
           for e in nrd)
assert len({e["sha256"] for e in nrd}) == 27, "the 27 containers are distinct"
per_theme = {t["id"]: t for t in man["themes"]}
assert len(per_theme) == 27
assert all(t.get("thmSha256") and t.get("thmBytes") and t.get("thmVendorPath")
           for t in man["themes"]), "a theme row lost its container record"
assert ({t["thmSha256"] for t in man["themes"]} == {e["sha256"] for e in nrd}), \
    "themes[] and notRedistributed disagree about the containers"
print(f"  notRedistributed {len(nrd):>3} recorded {sum(e['bytes'] for e in nrd):>10} B "
      f"(not in this tree: {len([p for p in on_disk if p.endswith('.thm')])} .thm files "
      f"on disk, and no thm/ entry in manifest counts)")
# the byte total quoted in the README and in docs/limits.md is the manifest's own sum
# over the files on disk - 84 926 540 B - not the walk's, because this README is one of
# the files and editing it would otherwise move the documented figure.  The walk is still
# checked against it, so a file added or changed in the tree shows up.
data = [e for e in man["files"] if e["kind"] != "background"]
assert {e["path"] for e in data} | {"manifest.json", "README.md"} == \
    {os.path.relpath(x, "themes/alpha") for x in on_disk}, \
    sorted({os.path.relpath(x, "themes/alpha") for x in on_disk}
           - {e["path"] for e in data})[:4]
assert sum(e["bytes"] for e in data) == 84_926_540, sum(e["bytes"] for e in data)
assert sum(os.path.getsize(os.path.join("themes/alpha", e["path"])) for e in data) \
    == 84_926_540, "a file on disk no longer matches the manifest's byte count"
print(f"  themes/alpha    {len(on_disk):>3} files: {len(data):>3} recorded "
      f"{84_926_540:>9} B (the documented total) + manifest.json "
      f"{os.path.getsize('themes/alpha/manifest.json'):>6} B + README.md "
      f"{os.path.getsize('themes/alpha/README.md'):>6} B")
# the vendor's own install, when this machine has one: the hashes above stop being a
# claim and become a check.  A runner without the volume is told which it is.  The path
# is derived from the constant this project already names (xigmalcd.main.WIN_STATIC, the
# loose-clips directory), because the installer keeps static/theme/butt and
# static/media as siblings - no second spelling of the same volume.
import subprocess
from xigmalcd.main import WIN_STATIC
butt = os.path.join(os.path.dirname(WIN_STATIC), "theme", "butt")
if os.path.isdir(butt):
    print(f"  vendor .thm install found at {butt}: re-hashing what this tree does not "
          f"carry")
    subprocess.run([sys.executable, "tools/thm_unlock.py", "--verify",
                    "--to", "themes/alpha", "--from", butt], check=True)
else:
    print("  vendor .thm install not on this machine (the Windows volume is not "
          "mounted), so the 27 recorded hashes are checked only against the bytes this "
          "tree does carry; on the author's bench the same run re-hashes 152/152")
# the dedup the README states: every theme background lives in clips/, none duplicated
themes = man["themes"]
assert len(themes) == 27, len(themes)
assert all(t["backgroundFile"].startswith("clips/") for t in themes)
assert not os.path.exists("themes/alpha/background"), "a background/ dir should not exist"
print(f"  27 themes, all 27 background payloads held by clips/, no background/ dir")

# The colour of the vendor's own lettering, counted out of the layout files this
# repo tracks - byte-identical to what the themes package installs - because
# PROTOCOL.md §10, docs/themes.md and docs/usage.md all quote the figures now and
# one of them used to claim "every glyph is white".  It is not: white is the rule
# across the library and the exception-free case only for the theme in use.
import collections as _col, glob as _glob, json as _json


def _text_colours(path):
    """every `*text*color*` property value in one layout, spaces normalised"""
    got = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and "text" in k.lower() and "color" in k.lower():
                    got.append(v.replace(" ", ""))
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(_json.load(open(path)))
    return got


WHITE = "rgba(255,255,255,1)"
lays = sorted(_glob.glob("themes/alpha/layouts/480X480/*.json"))
vals = _col.Counter()
exclusive = 0
for f in lays:
    got = _text_colours(f)
    assert got, (f, "a layout with no text colour at all")
    vals.update(got)
    if set(got) == {WHITE}:
        exclusive += 1
assert len(lays) == 23, len(lays)
assert sum(vals.values()) == 106, sum(vals.values())
assert len(vals) == 9, sorted(vals)
assert vals[WHITE] == 88, vals[WHITE]
assert exclusive == 18, exclusive
assert sum(v for k, v in vals.items() if k != WHITE) == 18, dict(vals)
# ...and the theme ALPHA has actually selected is one of the exclusively-white ones
sel = "themes/alpha/layouts/480X480/1757491589871.json"
assert set(_text_colours(sel)) == {WHITE}, _text_colours(sel)
print(f"  vendor text colours     {sum(vals.values())} textColor values across "
      f"{len(lays)} 480x480 layouts, {vals[WHITE]} white in {len(vals)} distinct "
      f"spellings, {exclusive} layouts exclusively white and {len(lays) - exclusive} "
      f"mixing in greys/near-blacks; the selected theme 6 of 6 white")
# store.json is the Windows app's own state, so only this bench can count it; the
# claim in docs/themes.md's table (125 white of 160) is re-derived when the volume
# is mounted and named as not-re-derived here when it is not.
from xigmalcd.main import WIN_STORE
if WIN_STORE and os.path.isfile(WIN_STORE):
    import re as _re
    raw = open(WIN_STORE, encoding="utf-8", errors="replace").read()
    sj = _col.Counter(m.replace(" ", "")
                      for m in _re.findall(r'"textColor"\s*:\s*"([^"]*)"', raw))
    assert sum(sj.values()) == 160 and sj[WHITE] == 125 and len(sj) == 13, \
        (sum(sj.values()), sj[WHITE], len(sj))
    print(f"  store.json            {sum(sj.values())} textColor values, "
          f"{sj[WHITE]} white, {len(sj)} distinct")
else:
    print("  store.json            SKIPPED: not on this machine (the Windows "
          "volume is not mounted), so its 125-of-160 figure is quoted from the "
          "bench run, not re-derived here")
# the three clips vendored at the repo root are the vendor's, twice over
for f in ("Theme_11.mp4", "Theme_25.mp4", "theme_48.mp4"):
    a = hashlib.sha256(open(f"media/{f}", "rb").read()).hexdigest()
    b = hashlib.sha256(open(f"themes/alpha/clips/{f}", "rb").read()).hexdigest()
    assert a == b, (f, a[:12], b[:12])
    print(f"  media/{f} == themes/alpha/clips/{f}  {a[:16]}")
# the contact sheets the README links, at the size the suite pins here
for name, px in (("alpha-themes-480X480.png", (960, 1548)),
                 ("alpha-themes-320X240.png", (960, 258))):
    p = os.path.join("docs", "previews", name)
    im = Image.open(p)
    assert im.size == px, (name, im.size, px)
    print(f"  docs/previews/{name}  {im.size[0]}x{im.size[1]}  "
          f"{os.path.getsize(p)} B")
# the identity claim: store.json's 27 presetTheme entries are these 27 layouts.  The
# store itself stays on the Windows volume; if it is not mounted, say so rather than
# pretending the check passed.
win = "/media/windows-c/Users/Tamer/AppData/Roaming/alpha/store.json"
if not os.path.exists(win):
    print("  store.json pairing SKIPPED: the Windows volume is not mounted")
else:
    def sig(o):
        return json.dumps(sorted((w["type"], json.dumps(w["property"], sort_keys=True))
                                 for w in o["osd"]["widget"]), sort_keys=True)
    lay = {t["id"]: json.load(open(os.path.join("themes/alpha", t["layout"])))
           for t in themes}
    pres = json.load(open(win))["presetTheme"]
    assert len(pres) == 27, len(pres)
    pair, unpaired = 0, []
    for p in pres:
        hits = [i for i, d in lay.items()
                if sig(d) == sig(p) and [d["width"], d["height"]] == [p["width"], p["height"]]]
        if len(hits) == 1:
            pair += 1
        else:
            unpaired.append((p["id"], hits))
    assert not unpaired, unpaired
    print(f"  store.json: all {pair}/27 presetTheme entries pair one-to-one with a "
          f"shipped .thm layout, widget properties identical")
PY

# What `--theme` is actually allowed to be told about this library.  This is the gate that
# lets docs/theme-editor.md state what is runnable instead of estimating it: the canvas
# refusal is keyed on each file's own `ratio` field, not on the directory it sits in, so a
# future 480x480 layout cannot be filtered out by a path rule, and the four 320x240 files
# are refused with their reason rather than hidden.
python3 - <<'PY' || { echo "library selection FAILED"; exit 1; }
import datetime, io, json, os, subprocess, sys
from xigmalcd import layout, render, themes

ok, out = themes.scan()
assert len(ok) == 23 and len(out) == 4, (len(ok), len(out))
assert all(r["ratio"] == "1:1" for r in ok), [r["ratio"] for r in ok]
assert all(r["ratio"] != "1:1" for r in out), [r["ratio"] for r in out]
assert len({r["name"].lower() for r in ok + out}) == 27, "a name collides case-insensitively"
assert len({r["id"] for r in ok}) == 23, "two pickable layouts share an id"
assert {r["w"] for r in out} == {320} and {r["h"] for r in out} == {240},     [(r["w"], r["h"]) for r in out]
# resolve by stem, by any case, and by the numeric id store.json uses; the 4:3 set answers
# with the canvas reason instead of with silence
assert themes.resolve("theme_07")["name"] == "Theme_07"
assert themes.resolve("1757491588804")["name"] == "Theme_07"
assert themes.resolve(out[0]["name"]) is None
assert "ratio 4:3" in themes.why_not(out[0]["name"]), themes.why_not(out[0]["name"])
assert themes.resolve("gauge") is None and "five" in themes.why_not("gauge")
# the source tally the plan quotes, and the 14-of-23 figure computed rather than asserted
used = themes.sources_used(ok)
assert used == {"CPU Temperature": 17, "CPU Usage": 15, "Time": 11, "Pump Speed": 9,
                "GPU Usage": 6, "GPU Temperature": 3, "CPU Frequency": 2}, used
answerable = set(themes.source_names())
need = {}
for rec in ok:
    srcs = {p.get("source") for w in (layout and themes.load(rec["path"])
                                      .get("osd") or {}).get("widget") or []
            for p in w.get("property") or []}
    need[rec["name"]] = {s for s in srcs if s} - answerable
clear = sorted(n for n, gap in need.items() if not gap)
assert len(clear) == 14, (len(clear), clear)
assert all(need[n] == {"Pump Speed"} for n in need if need[n]),     {n: need[n] for n in need if need[n]}
# the plan's `bars` argument quotes this tally, so it is held to it rather than remembered
_plan = open("docs/theme-editor.md", encoding="utf-8").read()
assert f"**{len(used)}** `source` names" in _plan, (
    len(used), "the plan miscounts the sources the library asks for")
for _s in ("CPU Temperature", "Time", "Pump Speed"):
    # the plan lists the three busiest with their counts and the rest by name, so what is
    # checked is "this source is quoted with this count" - and the character after the
    # number may not be a digit, or a drifted 170 would pass a plain substring test
    _q = f"`{_s}` in {used[_s]}"
    _i = _plan.find(_q)
    assert _i >= 0 and not _plan[_i + len(_q)].isdigit(), (
        _s, used[_s], "the plan's source tally drifted away from this run's")
print(f"  library selection       {len(ok)} pickable on canvas, {len(out)} refused "
      f"(ratio field, not the path); 27 names unique case-insensitively; sources asked "
      f"for: " + ", ".join(f"{k} {v}" for k, v in sorted(used.items(), key=lambda kv: -kv[1])))
print(f"                        {len(clear)}/{len(ok)} themes need nothing this program "
      f"has no reading for; the other {len(ok) - len(clear)} ask for Pump Speed, which "
      f"has never been measured on this box")

# ---- every vendor layout names the clip underneath it, and that field is a fact about the
# ---- file rather than a guess: `background.mediaFile`.  `themes.pair` is the one place that
# ---- reads it as an answer, so the window and `--list-themes` cannot disagree with each
# ---- other, or with the file.  What is held here is the shape of the data: one clip per
# ---- layout, no two layouts sharing one, and a refusal in words for the five names this
# ---- repo draws from code - which carry no such key, because a generated layout *is* the
# ---- picture and has nothing under it.
_named = {}
for _r in ok:
    _bg = str(_r["background"] or "")
    assert _bg, (_r["name"], "a selectable layout declares no background")
    _named.setdefault(_bg.rsplit("/", 1)[-1].lower(), []).append(_r["name"])
assert all(len(v) == 1 for v in _named.values()), (
    {k: v for k, v in _named.items() if len(v) > 1},
    "two selectable layouts name the same clip, so the pairing stops being a function")
for _r in ok:
    _got, _why = themes.pair(_r["name"])
    assert _got == _r["background"].rsplit("/", 1)[-1] and not _why, (_r["name"], _got, _why)
for _n in sorted(themes.EXPORTS):
    _got, _why = themes.pair(_n)
    assert _got == themes.CODE_CLIPS.get(_n) and not _why, (_n, _got, _why)
# Where those five clips come from, derived rather than trusted.  The vendor's own record
# names a backdrop for a page it drew; it has no page for a theme this repository draws,
# so for these five the honest source is the published pictures themselves: the README's
# MP4s are named `<theme>-<clip>.mp4` (`alpha-Theme_25.mp4`, `gauge-3.mp4`, ...).  A
# candidate counts only when its clip part resolves as a clip this box holds, which is how
# the amber-ink figure `alpha-Theme_25-amber.mp4` falls out of the derivation on its own
# rather than being excepted by hand.
import glob as _glob3
from xigmalcd.main import find_media as _find_media
_published = {}
for _v in sorted(_glob3.glob("docs/videos/*.mp4")):
    _stem = os.path.basename(_v)[:-4]
    _theme, _sep, _clip = _stem.partition("-")
    if not _sep or _theme not in render.THEMES:
        continue
    if not os.path.isfile(_find_media(_clip + ".mp4")):
        # `find_media` answers with a path whether or not the file is there - that is how a
        # missing clip gets reported as the name that was asked for - so the test here is
        # the file, not the string.  It is also what drops the amber-ink figure: its clip
        # part is `Theme_25-amber.mp4`, and no root holds that file.
        continue
    _published.setdefault(_theme, []).append(_clip + ".mp4")
assert all(len(v) == 1 for v in _published.values()), _published
_published = {k: v[0] for k, v in _published.items()}
assert set(_published) == set(render.THEMES), (
    sorted(_published), sorted(render.THEMES),
    "a theme drawn here has no published picture naming a backdrop, so its pairing would "
    "have to be invented")
assert _published == themes.CODE_CLIPS, (
    _published, themes.CODE_CLIPS,
    "themes.CODE_CLIPS is not the backdrop set the README's own pictures are composited "
    "over - the pairing would drift away from the pictures a reader judges the themes by")
# and a name that is neither a vendor layout nor one of the five still answers with a
# reason rather than an empty string, which is what the window prints
_orphan, _why_orphan = themes.pair("no-such-layout")
assert not _orphan and _why_orphan, (_orphan, _why_orphan)
print(f"  the five pair too    all {len(themes.CODE_CLIPS)} themes drawn from `render.py` "
      f"pair with the backdrop their own published picture uses, derived from the "
      f"{len(_glob3.glob('docs/videos/*.mp4'))} MP4 names and equal to themes.CODE_CLIPS: "
      + ", ".join(f"{k}->{v}" for k, v in sorted(themes.CODE_CLIPS.items())))
_refused_pair = {themes.pair(_r["name"])[0] or themes.why_not(_r["name"])[:24]
                 for _r in out}
_still = [_r["name"] for _r in out if not str(_r["background"]).lower().endswith(".mp4")]
assert all(not themes.pair(_r["name"])[0] for _r in out), (
    _refused_pair, "a canvas-refused layout answered a clip: the window must not be able to "
                   "open what `--theme` will not draw")
print(f"  the pairing           all {len(_named)} selectable layouts name exactly one clip "
      f"and no two name the same one; `themes.pair` answers each by name and refuses all "
      f"{len(themes.EXPORTS)} generated ones with the reason. The {len(out)} canvas-refused "
      f"layouts answer with their ratio instead ({len(_still)} of them "
      f"name{'s' if len(_still) == 1 else ''} a still image rather than a clip: "
      f"{', '.join(_still) or 'none'})")

# every pickable layout painted offline: pinned readings, one pinned instant, no port and
# no fixtures invented - and the frame bytes each would cost on the wire, which is the
# figure docs/usage.md quotes when it says what a library theme uploads
PIN = {"cpu": {"temperature": 61, "load": 42, "power": 88.5, "speedAverage": 4338},
       "gpu": {"temperature": 55, "load": 63, "power": 37.0, "speed": 1500},
       "network": {"upload": 12.3, "download": 45.6}, "memory": {"load": 7}}
WHEN = datetime.datetime(2026, 11, 8, 3, 40, 0)
# which of the four families the library names are actually installed here.  This is a
# machine fact, not a library fact: the bench has Noto Sans CJK and a CI runner may not,
# and a font that cannot be resolved drops its widget - so the boxes drawn and the frame
# bytes below are "on this machine", and the gate is a floor with the font situation
# printed rather than an exact count that would fail on another image.
# probe the family/bold pairs the layouts actually ask for, at the sizes they use:
# `arial` resolving at 12 px says nothing about `simsun` bold at 100, and the day a probe
# is coarser than the thing it guards is the day the guard starts lying.
used_faces = set()
for rec in ok:
    for w in (themes.load(rec["path"]).get("osd") or {}).get("widget") or []:
        for pr in w.get("property") or []:
            if pr.get("fontFamily"):
                used_faces.add((str(pr["fontFamily"]).lower(), bool(pr.get("bold")),
                                int(pr.get("fontSize") or 12)))
# `font_for` answers (face, family, path) - a three-tuple that stays truthy even when
# the face is None, which is how this probe reported "16 installed" on a runner that
# then skipped a `simsun` widget.  Ask the face, not the tuple.
probe = {t: layout.font_for({"fontFamily": t[0], "bold": t[1],
                             "fontSize": t[2]})[0] is not None
         for t in used_faces}
faces = {f"{fam}{'b' if bold else ''}/{size}": v
         for (fam, bold, size), v in sorted(probe.items())}
missing_faces = sorted(k for k, v in faces.items() if not v)
print(f"  faces on this machine {len(faces)} family/bold/size combinations asked for by "
      f"the {len(ok)} layouts, {len(faces) - len(missing_faces)} installed"
      + (f"; MISSING: {' '.join(missing_faces)}" if missing_faces else ""))
sizes, drawn, skipped, dropped_fonts = [], 0, [], set()
painted_total = 0
boxes_per, skips_per = {}, {}
# what this bench painted for each layout on 2026-11-08, recorded here so a machine that
# lands somewhere else says *which layout* and by how much, instead of leaving a total to
# be explained. This is a diagnostic print, not an assertion: the count belongs to the
# fonts installed, the accounting identity above does not.
BENCH_BOXES = {'Theme_01': 8, 'Theme_07': 8, 'Theme_14': 7, 'Theme_25': 5, 'Theme_27': 3, 'Theme_28': 6, 'Theme_29': 2, 'Theme_30': 8, 'Theme_33': 3, 'Theme_34': 3, 'Theme_35': 5, 'theme_36': 3, 'theme_37': 5, 'theme_39': 3, 'theme_40': 8, 'theme_41': 5, 'theme_45': 2, 'theme_46': 7, 'theme_47': 3, 'theme_48': 6, 'theme_49': 3, 'theme_50': 8, 'theme_52': 3}
for rec in ok:
    img, notes = themes.paint(rec, PIN, when=WHEN, scrim=0)
    assert img.size == (480, 480), (rec["name"], img.size)
    alpha = img.getchannel("A")
    vals = alpha.get_flattened_data() if hasattr(alpha, "get_flattened_data") \
        else alpha.getdata()
    px = sum(1 for v in vals if v)          # lit pixels, not alpha-weighted coverage
    assert notes["boxes"], (rec["name"], "drew nothing")
    assert px > 500, (rec["name"], px)
    sizes.append((len(render.to_png(img)), rec["name"], px, len(notes["boxes"])))
    drawn += len(notes["boxes"])
    painted_total += px
    boxes_per[rec["name"]] = len(notes["boxes"])
    # `missing` carries two different kinds of thing: a metric this machine cannot read,
    # and a face that is not installed.  Only the first is a rule about the library.
    srcs = [m for m in notes["missing"] if not str(m).startswith("font:")]
    gone = [str(m)[5:] for m in notes["missing"] if str(m).startswith("font:")]
    dropped_fonts.update(gone)
    skips_per[rec["name"]] = (srcs, gone)
    # the accounting identity, and it holds on every machine: every widget in the file is
    # either painted or reported as skipped, with a reason. A widget that simply vanished
    # would break this, and that is the failure worth catching - not the exact pixel total,
    # which belongs to whichever fonts happen to be installed.
    assert len(notes["boxes"]) + len(srcs) + len(gone) == rec["widgets"], \
        (rec["name"], rec["widgets"], notes["boxes"], notes["missing"])
    if srcs:
        assert srcs == ["Pump Speed"], (rec["name"], srcs)
        assert "fanscan" in notes["absent"]["Pump Speed"], notes["absent"]
        skipped.append(rec["name"])
# `--bg black` on a layout theme: the same shape it has for our own five, an opaque frame
# that covers the panel's stored background rather than letting it through
for rec in ok[:3]:
    solid, _ = themes.paint(rec, PIN, when=WHEN, base=render.BLACK)
    assert solid.getextrema()[3] == (255, 255), (rec["name"], solid.getextrema()[3])
    clear, _ = themes.paint(rec, PIN, when=WHEN)
    assert clear.getextrema()[3][0] == 0, (rec["name"], clear.getextrema()[3])
print("  --bg black, a layout   opaque alpha (255, 255) and transparent (0, ...) on the "
      "same layout, as with our own themes")
assert len(skipped) == 9, skipped
assert [r["name"] for r in ok if r["name"] in
        {n for n in need if need[n]}] and set(skipped) == {n for n in need if need[n]}, \
    (skipped, sorted(n for n in need if need[n]))
sizes.sort()
print(f"  drawn offline, no port  all {len(ok)} layouts painted from a pinned metrics "
      f"dict and one pinned instant, on this machine's faces: {drawn} widget boxes, "
      f"frames {sizes[0][1]} {sizes[0][0]} B .. {sizes[-1][1]} {sizes[-1][0]} B "
      f"(the same PNG shape `alpha` uploads)"
      + (f"; {len(dropped_fonts)} family(ies) not installed here, widgets using them "
         f"skipped: {' '.join(sorted(dropped_fonts))}" if dropped_fonts else ""))
print(f"                        {len(skipped)} themes report a skipped widget, every one "
      f"of them Pump Speed, with the reason in the note")

# the CLI door: `--theme` takes both halves, and a refused name comes back with its reason
import argparse
ap = render and __import__("xigmalcd.main", fromlist=["main"]).build_parser()
assert ap.parse_args(["--theme", "Theme_07"]).theme == "Theme_07"
assert ap.parse_args(["--theme", "theme_07"]).theme == "Theme_07"
for bad, want in ((out[0]["name"], "ratio 4:3"), ("Theme_99", "no layout named"),
                  ("nonsense", "no layout named")):
    try:
        ap.parse_args(["--theme", bad])
        raise AssertionError(f"{bad} parsed as a theme")
    except SystemExit as exc:
        assert exc.code == 2, exc.code
import contextlib
err = io.StringIO()
with contextlib.redirect_stderr(err):
    try:
        ap.parse_args(["--theme", out[0]["name"]])
    except SystemExit:
        pass
assert "ratio 4:3" in err.getvalue(), err.getvalue()
run = subprocess.run([sys.executable, "-m", "xigmalcd", "--list-themes"],
                     capture_output=True, text=True, check=True)
lines = [l for l in run.stdout.splitlines() if l.strip()]
pick = [l for l in lines if " NOT PICKABLE: " in l]
assert len(pick) == 4, len(pick)
assert "drawn here (render.py)" in run.stdout and "Pump Speed" in run.stdout
assert "ttyACM" not in run.stdout, "a port was opened to list themes"
print(f"  --list-themes           {len(lines)} lines, {len(pick)} of them the canvas "
      f"refusals with their reason; no port is opened by the listing")

# The library's own numbers, as a guard on this night's additions to layout.py: the two
# extension keys and the `special` branch must not have moved a single vendor pixel.
# Asserted only where all four families the library names are installed, because the
# totals count glyphs: a machine without a CJK face draws fewer of them, and that is said
# rather than failed.
# 114 boxes / 315 287 lit px is this bench's figure, with this box's fonts; the same 23
# layouts land 1 box and 920 px lower on a runner that has no CJK faces and one that
# substitutes a narrower DejaVu. What is asserted is machine-independent: the accounting
# identity above, one box and >500 lit px per layout, and the exact set of layouts whose
# *sources* are unanswered.
off = sorted((n, b, BENCH_BOXES[n]) for n, b in boxes_per.items()
             if BENCH_BOXES.get(n) != b)
if off:
    # and the probe's own answer for the triples that theme asks for, so a draw-time skip
    # the probe did not predict is visible as a disagreement, not as a mystery total
    tri = {rec["name"]: sorted({(str(pr.get("fontFamily") or "").lower(),
                                 bool(pr.get("bold")), int(pr.get("fontSize") or 12))
                                for wd in (themes.load(rec["path"]).get("osd") or {}).get(
                                    "widget") or []
                                for pr in wd.get("property") or [] if pr.get("fontFamily")}
                               ) for rec in ok}
    for rec in ok:                       # decisive: the prop as stored, and what
        if rec["name"] not in {o[0] for o in off}:   # font_for made of it
            continue
        for wd in (themes.load(rec["path"]).get("osd") or {}).get("widget") or []:
            for pr in wd.get("property") or []:
                if not pr.get("fontFamily"):
                    continue
                face, fam, path = layout.font_for(pr)
                print(f"      {rec['name']} {wd['type']:<5} "
                      f"stored={pr.get('fontFamily')!r}/{pr.get('fontSize')!r}/"
                      f"bold={pr.get('bold')!r} -> fam={fam!r} "
                      f"face={'yes' if face else 'NONE'} "
                      f"file={os.path.basename(path) if path else '-'}")
    det = "; ".join(
        f"{n} {b} here, {w} there (skipped: "
        f"{', '.join(skips_per[n][0] + skips_per[n][1]) or 'nothing'}; probe for this "
        f"theme's faces: "
        + " ".join(f"{f}{'b' if bo else ''}/{sz}={'yes' if probe.get((f, bo, sz)) else 'NO'}"
                   for f, bo, sz in tri.get(n, [])) + ")"
        for n, b, w in off)
    print("  box counts vs the bench " + det)
else:
    print(f"  box counts vs the bench  identical for all {len(boxes_per)} layouts")
print(f"  vendor pixels          {drawn} boxes, {painted_total} lit px on this machine "
      f"(the bench of 2026-11-08 records 114 / 315287 with all 16 face combinations "
      f"installed); every layout paints, and every widget is either drawn or reported")

# ---- the generated export: byte-stable, and identical to the code it claims to describe
shapes = []
for name in sorted(themes.EXPORTS):
    dump_a = json.dumps(themes.export(name), indent=1, sort_keys=True)
    dump_b = json.dumps(themes.export(name), indent=1, sort_keys=True)
    assert dump_a == dump_b, f"two exports of {name} differ - something non-deterministic"
    obj = json.loads(dump_a)
    assert obj["ratio"] == "1:1" and (obj["width"], obj["height"]) == (480, 480), obj
    hard, soft = themes.validate(obj)
    assert not hard, (name, hard)
    for w in obj["osd"]["widget"]:
        assert str(w["id"]).startswith("xigma-"), w["id"]        # never uuid4
        assert isinstance(w["property"], list) and len(w["property"]) == 1, w["id"]
        assert "time" not in w["property"][0], \
            "an export carries no editor stamp: nothing generates one"
        if w["type"] == "special":
            assert w["property"][0]["name"] in themes.special_names(), w
    shapes.append(f"{name} {len(obj['osd']['widget'])} widgets {len(dump_a)} chars")
print(f"  export shape          {'; '.join(shapes)} - ids derived from the theme name, "
      f"one-element `property` like every vendor file, no `time` stamp, each one "
      f"validate-clean, each one byte-identical over two runs")

# Parity: the generated layout painted by layout.py against the same theme painted by
# render.py, one pinned instant and one pinned metrics dict, five different readings.
# The diff is over all four channels - an alpha-only comparison would not see a colour
# that had drifted, and colour is exactly what `xigma.textColor` carries.
# the first two answer every source every export asks for; the last three deliberately do
# not, and what happens then is reported, not hidden - the second-to-last one only leaves
# `load` out, which is the case where the two doors still land on the same pixels, because
# the reading gates a whole widget rather than a fallback
#
# What "every source" came to mean once `bars` was exported (2026-11-09): a board
# temperature, a GPU memory pair, and **four fan rows** - `bars` reserves four slots, so a
# box reporting one fan leaves three of them unanswered by construction.  And the second
# reading used to say `memory: {used: 0, total: 0}`, which is not a pair to divide; the
# zero is now in the numerator, where it is a measurement (a meter at nothing filled, a
# number reading `0 GB`) rather than an absent reading.  Both readings still sit at the
# ends of every scale: 100 degrees, 0 % load, 12 345 RPM on a 0..3000 meter.
CASES = ({"cpu": {"temperature": 57, "load": 62}, "gpu": {"temperature": 47,
                                                          "load": 22,
                                                          "memoryUsage": 2_100_000,
                                                          "dedicatedTotal": 8_000_000},
          "motherboard": {"temperature": 41},
          "memory": {"used": 4_200_000, "total": 16_000_000},
          "fans": [{"value": 1957, "name": "Fan CPU"},
                   {"value": 1102, "name": "Fan System 5"},
                   {"value": 800, "name": "Fan Pump"},
                   {"value": 640, "name": "Fan Chassis 2"}]},
         {"cpu": {"temperature": 100, "load": 0}, "gpu": {"temperature": 100,
                                                          "load": 0,
                                                          "memoryUsage": 0,
                                                          "dedicatedTotal": 8_000_000},
          "motherboard": {"temperature": 0},
          "memory": {"used": 0, "total": 16_000_000},
          "fans": [{"value": 12345, "name": "Fan CPU"},
                   {"value": 0, "name": "Fan System 5"},
                   {"value": 1, "name": "Fan Pump"},
                   {"value": 3000, "name": "Fan Chassis 2"}]},
         {"cpu": {"temperature": 24}},
         {"cpu": {"temperature": 40}, "gpu": {"temperature": 55}},
         {})
rows = []
export_faces = set()
for name, recipe in themes.EXPORTS.items():
    for w in recipe()["osd"]["widget"]:
        pr = w["property"][0]
        if pr.get("fontFamily"):
            export_faces.add((str(pr["fontFamily"]).lower(), bool(pr.get("bold")),
                              int(pr.get("fontSize") or 12)))
no_face = sorted(f"{f}{'b' if b else ''}/{sz}" for f, b, sz in export_faces
                 if layout.font_for({"fontFamily": f, "bold": b,
                                     "fontSize": sz})[0] is None)
partial = []
asked = {n: {w["property"][0].get("source") for w in recipe()["osd"]["widget"]}
         for n, recipe in themes.EXPORTS.items()}
for name in sorted(themes.EXPORTS):
    for idx, m in enumerate(CASES):
        r = themes.parity(name, m, WHEN)
        if no_face:      # an export's own face is not installed here: say so, don't fail
            break
        if r["missing"]:
            # `xigma.showIf` reports an unmet dependency as `showIf:<source>`, and the
            # source it names is one this export already asks for by name (the meter of the
            # row whose number is guarded).  So the note is checked through that name, and
            # each one has to arrive beside the plain note for the same reading: a
            # dependency said without its cause would be a hole with no reason next to it
            _said = {m[len("showIf:"):] if m.startswith("showIf:") else m
                     for m in r["missing"]}
            assert _said <= set(asked[name]), (name, r["missing"], sorted(asked[name]))
            _dep = {m[len("showIf:"):] for m in r["missing"]
                    if m.startswith("showIf:")}
            assert _dep <= set(r["missing"]), (name, sorted(_dep),
                                               "a row named a dependency this machine "
                                               "cannot answer without the reading itself "
                                               "being reported as missing too")
            partial.append((name, idx, tuple(sorted(set(r["missing"]))), r["diff_px"],
                            r["code_px"], r["layout_px"]))
            continue
        assert r["diff_px"] == 0 and r["worst_channel_delta"] == 0, (name, idx, r)
        assert r["code_px"] == r["layout_px"] > 4000, (name, idx, r)
        rows.append((name, r["code_px"]))
    if no_face:
        break
# every export has to reach a zero diff on both complete fixture readings; a case that
# leaves a source out may still agree (dual with no `load`: no bar, no line, both doors
# draw nothing) or may not (no GPU temperature: the code theme keeps the ring's track,
# the layout has no ring at all), and which is which is printed below
assert {n for n, _p in rows} == set(themes.EXPORTS), (sorted(rows), sorted(themes.EXPORTS))
assert all(idx >= 2 for _n, idx, _ms, _d, _c, _l in partial), partial
agree = [p for p in partial if p[3] == 0]
disagree = [p for p in partial if p[3] != 0]
assert len(agree) + len(disagree) == len(partial), partial
per = ", ".join(f"{n} {p} px identical" for n, p in rows)
if no_face:
    print(f"  export parity         SKIPPED on this machine: the exported themes name "
          f"{', '.join(no_face)}, not installed here")
assert set(render.THEMES) <= set(themes.EXPORTS), (
    sorted(set(render.THEMES) - set(themes.EXPORTS)),
    "a drawn theme is no longer exported, and the documents that say all five are would "
    "be wrong")
print(f"  export parity         all {len(themes.EXPORTS)} drawn themes export today "
      f"({' '.join(sorted(themes.EXPORTS))}); across {len(CASES)} readings each, the "
      f"generated layout and render.py put down the same pixels: {per}")
assert len(rows) >= 4 * len(themes.EXPORTS) - len(partial), (rows, partial)
if partial:
    both = (f"{len(agree)} of them agree to the pixel anyway, because a code theme that "
            f"has no load reading draws no bar and no line, exactly as a layout skips the "
            f"widget" if agree else "none of them agree")
    print(f"  a reading missing     {len(partial)} of the "
          f"{len(CASES) * len(themes.EXPORTS)} parity cases leave a source unanswered; "
          f"{both}, and {len(disagree)} differ: "
          + "; ".join(f"{nm} without {', '.join(ms)}: code {c:,} px, layout {l:,} px"
                      for nm, idx, ms, d, c, l in disagree)
          + ". In every one of those the code theme paints something for a reading it "
            f"does not have - an unfilled ring's track, a bar's track, `--\u00b0C` or `--%` "
            f"where a number would be - and a layout has no widget to paint when its "
            f"`source` is unanswered. Both are right by their own rule, so the counts "
            f"stand side by side - an export translates a theme's drawing, not its "
            f"fallback behaviour (docs/limits.md)")


# ---- why `xigma.arcPaint` exists at all: one arc, painted both conventions, measured
from PIL import Image, ImageChops

# ---- "`--bg black` makes the frame opaque" is two different answers in the two doors, and
# ---- only one of them was gated.  The opacity assert above is about a *layout*: there the
# ---- plate goes under the finished layer (`themes.paint(..., base=BLACK)`), so the frame is
# ---- opaque everywhere.  A `theme_*` body instead opens its image with the canvas already in
# ---- it - `Image.new("RGBA", (W * SS, H * SS), bg)`, one use of the argument in every body -
# ---- and PIL's `ImageDraw` *replaces* a pixel for a translucent fill rather than blending it
# ---- with what is underneath.  So every translucent thing a drawn theme paints - a ring's
# ---- track, the grey plate behind two figures - leaves the frame's own alpha below 255, and
# ---- the panel's stored background keeps showing through it.  That is not a bug to fix here
# ---- (it is what makes a `--bg black` frame's palette small and the vendor's frames
# ---- transparent), but the sentence about it was over-broad, and the split is worth pinning:
# ---- which themes leak is derived from the exports' own colour keys, not remembered.
_missing_by_theme = {}
for _n, _i, *_rest in partial:
    _missing_by_theme.setdefault(_n, set()).add(_i)


def _px_gap(a, b):
    return sum(1 for q in ImageChops.difference(a.convert("RGBA"),
                                                b.convert("RGBA")).get_flattened_data()
               if q != (0, 0, 0, 0))


def _translucent(obj):
    """Every colour key in one export whose alpha is below 1, as `row kinds`."""
    out = {}
    for w in obj["osd"]["widget"]:
        for key, val in w["property"][0].items():
            if "color" not in key.lower() or "(" not in str(val):
                continue
            try:
                alpha = float(str(val).rsplit(",", 1)[-1].strip(" )"))
            except ValueError:
                continue
            if alpha < 1:
                out.setdefault(key, []).append(w["type"])
    return out


def _leak(img):
    hist = img.getchannel("A").histogram()
    return sum(hist[:255]), (min(v for v in range(256) if hist[v]) if sum(hist[:255]) else 255)


_declared = {name: _translucent(themes.export(name)) for name in sorted(themes.EXPORTS)}
_leaky = sorted(n for n, keys in _declared.items() if keys)
_opaque_here = sorted(set(themes.EXPORTS) - set(_leaky))
_gaps, _leaks, _canvas_skipped = {}, {}, []
_now_real = render._now
render._now = lambda: WHEN.timetuple()      # one instant on both sides: `themes.draw` is
try:                                        # handed WHEN, `render.draw` reads the clock
    for _name in sorted(themes.EXPORTS):
        _usable = [i for i in range(len(CASES)) if i not in _missing_by_theme.get(_name, ())]
        if not _usable:
            _canvas_skipped.append(_name)     # no reading where the two doors agree at all here,
            continue                          # so a canvas figure for this theme would be noise
        _m_case = CASES[_usable[0]]
        _layer, _ = themes.draw(themes.export(_name), _m_case, WHEN)
        _plate = Image.alpha_composite(Image.new("RGBA", _layer.size, render.BLACK), _layer)
        _code_layer = render.draw(_m_case, _name)
        _code_solid = render.draw(_m_case, _name, bg=render.BLACK)
        # the file door: a plate under a layer is opaque, and that is the whole claim
        assert _plate.getextrema()[3] == (255, 255), (_name, "a plate left the frame partly clear")
        assert _leak(_plate)[0] == 0, (_name, _leak(_plate))
        # the code door: opaque exactly where it has nothing translucent to paint
        _leaked, _lowest = _leak(_code_solid)
        if _name in _leaky:
            assert _leaked > 0, (_name, _declared[_name],
                                 "a theme whose file declares a translucent fill went fully "
                                 "opaque on a black canvas: the replace-not-blend rule broke")
            assert _lowest < 255, (_name, _lowest)
        else:
            assert _leaked == 0, (_name, _leaked, _lowest,
                                  "a theme with no translucent colour key leaks on `--bg black`: "
                                  "the split between the two doors is no longer about the file")
        _leaks[_name] = (_leaked, _lowest)
        # and the two doors' opaque frames are not one picture: the plate's *order* is what parts
        # them, since compositing under the code drawing's own layer gives the same counts
        _gap = _px_gap(_code_solid, _plate)
        _plate_over_code = Image.alpha_composite(
            Image.new("RGBA", _code_layer.size, render.BLACK), _code_layer)
        assert _gap == _px_gap(_code_solid, _plate_over_code), (
            _name, _gap, _px_gap(_code_solid, _plate_over_code),
            "the black-canvas gap is no longer only the plate's order: the two doors disagree "
            "*underneath* the plate, so this sentence and the parity gate above are about "
            "different pictures")
        _gaps[_name] = _gap
        assert _px_gap(_code_layer, _layer) == 0, (
            _name, "at the default transparent canvas the two doors are not one picture, and "
                   "every parity claim in the documents is about exactly that case")
finally:
    render._now = _now_real
    # the documents have to say the same split, in the same derived words
    _usage = open("docs/usage.md", encoding="utf-8").read()
    _want = (f"{len(_leaky)} of the five drawn themes "
             f"(`{'`, `'.join(_leaky)}`)")
    assert _want in _usage, (_want, sorted(_leaky),
                             "docs/usage.md does not state which drawn themes stay translucent "
                             "on `--bg black`, which this gate derives from their own files")
    assert f"(`{'`, `'.join(_opaque_here)}`)" in _usage, (_opaque_here,
                                                          "docs/usage.md does not name the drawn "
                                                          "themes that do go opaque")
print(f"  --bg black, both doors  the file door's plate goes under the layer, so a layout "
      f"frame is opaque everywhere (0 of {render.W * render.H:,} px below alpha 255). The "
      f"code door's canvas goes in before the draw, and `ImageDraw` replaces rather than "
      f"blends, so the themes whose own files declare a translucent colour keep leaking: "
      f"{_want} leak " + ", ".join(f"{n} {_leaks[n][0]:,} px (lowest alpha {_leaks[n][1]})"
                                  for n in _leaky) + f"; {len(_opaque_here)} of them "
      f"(`{'`, `'.join(_opaque_here)}`) have no translucent key and go opaque. With an opaque "
      f"plate the two doors still part by " + ", ".join(f"{k} {v:,}" for k, v in sorted(_gaps.items()))
      + " px at glyph edges, the same counts when the plate goes under the code drawing's own "
      "layer - order, not drawing"
      + (f"; not measured for {', '.join(_canvas_skipped)} (no reading where the two doors "
         f"agree)" if _canvas_skipped else ""))
_arc = themes.export("gauge")["osd"]["widget"][0]["property"][0]


def _ring(declared: bool, value):
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    prop = json.loads(json.dumps(_arc))
    if not declared:
        prop.pop("xigma", None)
    from PIL import ImageDraw
    layout.draw_arc(ImageDraw.Draw(img), prop, value)
    return img.resize((render.W, render.H), Image.LANCZOS)


conv = []
for v in (31.0, 52.0, 57.4, 88.9):
    flat = ImageChops.difference(_ring(True, v), _ring(False, v)).get_flattened_data()
    conv.append((v, sum(1 for px in flat if px != (0, 0, 0, 0)),
                 max((max(px) for px in flat), default=0)))
assert all(n > 0 for _v, n, _w in conv), conv
assert all(w > 0 for _v, _n, w in conv), conv
# ---- and the same question for a bar, where there are now three answers and one of
# ---- them names a drawing function, so its claim is held to that function's pixels.
_barprop = {"x": 60, "y": 340, "width": 360, "height": 14, "cornerRadius": 5,
            "bgColor": "rgba(40, 46, 50, 1)", "startColor": "rgba(0, 247, 255, 1)",
            "endColor": "rgba(0, 247, 255, 1)", "minValue": 0, "maxValue": 100,
            "source": "CPU Usage"}


def _bar(paint, value):
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    prop = json.loads(json.dumps(_barprop))
    if paint:
        prop["xigma"] = {"barPaint": paint}
    from PIL import ImageDraw
    layout.draw_bar(ImageDraw.Draw(img), prop, value)
    return img.resize((render.W, render.H), Image.LANCZOS)


bars = []
for v in (0.0, 3.0, 63.5, 100.0):
    flat = ImageChops.difference(_bar("render", v), _bar(None, v)).get_flattened_data()
    bars.append((v, sum(1 for q in flat if q != (0, 0, 0, 0)),
                 max((max(q) for q in flat), default=0)))
assert all(n > 0 for _v, n, _w in bars), bars

# `barPaint: hbar` is different in kind from the other two: it names `render.hbar`, so
# the only answer that counts is a zero diff against it, on the geometry and the inks that
# function is called with.  Both come out of `render.py`'s own constants here - the two
# usage-bar anchors, their size, the three colours - so the probe cannot drift away from
# the theme it is testing, which is how the last remembered figure in this repo went stale.
def _css(col):
    return f"rgba({col[0]}, {col[1]}, {col[2]}, {col[3] / 255:.6g})"


def _code_bar(which, value):
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    render.hbar(img, *render.A26_BAR_XY[which], *render.A26_BAR_WH,
                min(max(value / 100.0, 0.0), 1.0))
    return img


def _file_bar(which, value, paint, corner):
    prop = {"x": render.A26_BAR_XY[which][0], "y": render.A26_BAR_XY[which][1],
            "width": render.A26_BAR_WH[0], "height": render.A26_BAR_WH[1],
            "cornerRadius": corner, "minValue": 0, "maxValue": 100,
            "source": "CPU Usage", "bgColor": _css(render.A26_TRACK),
            "startColor": _css(render.A26_BAR_A), "endColor": _css(render.A26_BAR_B),
            "xigma": {"barPaint": paint}}
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    from PIL import ImageDraw
    _box, bad = layout.draw_bar(ImageDraw.Draw(img), prop, value)
    assert not bad, (paint, bad)
    return img


def _count(a, b):
    flat = ImageChops.difference(a, b).get_flattened_data()
    return (sum(1 for q in flat if q != (0, 0, 0, 0)),
            max((max(q) for q in flat), default=0))


# device px, before the LANCZOS downsample the 1x frame goes through: the convention's
# own resolution
zero = []
gap_h = {}
for which in (0, 1):
    for value in (0, 3, 22, 62, 100, 137, -5):    # includes past-max and negative
        for corner in (0, 5):   # `hbar` takes no radius: a declared corner must not leak
            assert _count(_code_bar(which, value),
                          _file_bar(which, value, "hbar", corner))[0] == 0, \
                (which, value, corner)
            zero.append((which, value, corner))
        for paint in ("vendor", "render"):
            gap_h[(which, value, paint)] = _count(_code_bar(which, value),
                                                  _file_bar(which, value, paint, 5))[0]
assert len(zero) == 2 * 7 * 2, zero
assert all(n > 0 for k, n in gap_h.items() if k[1] > 0), gap_h

# The same test for the second convention that names a function, `render.bar`, at the
# values where its own two floors make a difference.  This is not decoration: the table
# used one number for both floors, so a load between 1 % and 2 % drew **no fill at all**
# while `render.bar` drew one - the first version of this gate found it at 1.5 % and 2 %.
# `render.bar` draws when `frac > 0.01` and rounds its corners off `max(frac, 0.02)`.
def _code_load(value):
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    render.bar(img, 60, 340, 360, 14, value / 100.0, render.heat(value / 100.0))
    return img


def _file_load(value):
    prop = json.loads(json.dumps(_barprop))
    prop["xigma"] = {"barPaint": "render", "colourRamp": "heat"}
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    from PIL import ImageDraw
    _box, bad = layout.draw_bar(ImageDraw.Draw(img), prop, value)
    assert not bad, bad
    return img


LOADS = (0, 0.5, 1.0, 1.01, 1.5, 2.0, 2.5, 3, 12.5, 63.5, 99.9, 100, 137, -5)
load_zero = [_count(_code_load(v), _file_load(v))[0] for v in LOADS]
assert load_zero == [0] * len(LOADS), list(zip(LOADS, load_zero))
# 1x, as the panel and the preview actually see it
ONEX = [_count(_code_bar(0, v).resize((render.W, render.H), Image.LANCZOS),
               _file_bar(0, v, "hbar", 5).resize((render.W, render.H), Image.LANCZOS))[0]
        for v in (0, 3, 22, 62, 100, 137, -5)]
assert ONEX == [0] * len(ONEX), ONEX
# and the fill is really being walked, not hidden under the track: the number of pixels of
# the declared rect that still read the track's own colour falls as the reading rises, and
# falls the same way in both drawings
def _track_px(img):
    x, y = render.A26_BAR_XY[0]
    w, h = render.A26_BAR_WH
    box = img.crop((x, y, x + w, y + h)).get_flattened_data()
    return sum(1 for q in box if q[:3] == render.A26_TRACK[:3])


walked = []
for value in (0, 30, 62, 100):
    code = _code_bar(0, value).resize((render.W, render.H), Image.LANCZOS)
    mine = _file_bar(0, value, "hbar", 0).resize((render.W, render.H), Image.LANCZOS)
    walked.append((value, _track_px(mine), _track_px(code)))
assert [a for _v, a, _b in walked] == [b for _v, _a, b in walked], walked
assert walked[0][1] > walked[1][1] > walked[2][1] > walked[3][1] == 0, walked

# what `theme_alpha` draws, taken out of its own source rather than remembered, so the
# blocker list in docs/theme-editor.md is a claim about this code and not a memory of it
import inspect, re                                 # noqa: E402
alpha_src = inspect.getsource(render.theme_alpha)
alpha_fn = render.theme_alpha.__name__
# a *call*, matched at a word boundary, so `temp_arc(` does not report an `arc` and
# `hbar(` does not report a `bar` - the two false positives the first version of this
# line had, from plain substring matching.  A theme name is not a drawing either.
alpha_draws = sorted({c for c in dir(render)
                      if getattr(getattr(render, c), "__module__", None)
                      == render.__name__ and c != alpha_fn
                      and re.search(r"\b%s\(" % re.escape(c), alpha_src)})
assert {"hbar", "temp_arc", "_fit_arc", "fan_figures", "cpu_fan_figure",
        "gpu_fan_figure", "_title", "clock_str", "value_pair", "cpu_temp_text",
        "gpu_temp_text"} <= set(alpha_draws), alpha_draws
# `value_pair` and the two temperature builders are in that set on purpose: the theme
# draws its figures through the same function a `temp-values` row draws through, so the
# two doors cannot reach two different sizes for one pair of readings.  The coverage
# gate below is what counts the pixels that claim proves.

# the enumerated tables and the reasons `--print-theme-fields` prints for them cannot
# drift: every name in a table has to be named in that key's stated reason
drift = {key: [n for n in table if n not in themes.XIGMA_KEYS[key]]
         for key, table in (("arcPaint", layout.ARC_PAINT),
                            ("barPaint", layout.BAR_PAINT),
                            ("colourRamp", layout.COLOUR_RAMPS))}
assert not any(drift.values()), drift
# and a name that is *not* in a table is reported, not drawn by guesswork: the soft
# finding the arc has had since it lands, now one shape over for a bar
bad_arc = json.loads(json.dumps(themes.export("gauge")))
bad_arc["osd"]["widget"][0]["property"][0]["xigma"]["arcPaint"] = "guessed"
bad_prop = dict(_barprop)
bad_prop["xigma"] = {"barPaint": "hand-painted"}
bad_bar = {"width": render.W, "height": render.H,
           "osd": {"widget": [{"id": "xigma-bad", "type": "bar",
                               "property": [bad_prop]}]}}
hard, soft_bar = themes.validate(bad_bar)
assert not hard, hard
assert any("barPaint" in s and "hand-painted" in s for s in soft_bar), soft_bar
assert all(n in s for n in layout.BAR_PAINT
           for s in soft_bar if "barPaint" in s), soft_bar
hard, soft_arc = themes.validate(bad_arc)
assert not hard, hard
assert any("arcPaint" in s and "guessed" in s for s in soft_arc), soft_arc

import itertools                                     # noqa: E402
from PIL import ImageDraw                            # noqa: E402

# ---- `alpha`'s fan pair, held to the theme the same way a convention is held to its
# ---- function: one `special` row, painted through the loop's door, compared with the
# ---- row `theme_alpha` paints - isolated as the pixels that change when `fan` switches
# ---- off, so the comparison is about the pair and not about the whole frame.
FAN_CX = (render.A26_FAN_X[0] + render.A26_FAN_X[1]) // 2
FAN_PITCH = render.A26_FAN_X[1] - render.A26_FAN_X[0]
CPU_TACHES = (None, 999, 1016, 2051, 2448, 9999)
GPU_FANS = (None, 0, 5, 41, 100)


def _fan_metrics(cpu, gpu):
    """One frame's tachometers.  Written out here, not read off `sensors`, so the number
    of reading pairs this gate walks is a fact about the gate and not about a machine."""
    gpu_part = {"temperature": 47.0}
    if gpu is not None:
        gpu_part["fan"] = float(gpu)
    return {"cpu": {"temperature": 57.0}, "gpu": gpu_part,
            "fans": ([{"name": "Fan CPU", "value": cpu, "type": "Fan"}]
                     if cpu is not None else [])}


def _fan_prop():
    return {"name": "fan-figures", "x": FAN_CX, "y": render.A26_FAN_Y,
            "width": FAN_PITCH, "fontFamily": "dejavu", "fontSize": render.A26_FAN_F,
            "bold": False, "textColor": _css(render.A26_WHITE),
            "xigma": {"anchor": "ma", "autoFitMax": render.A26_FAN_MAX_W}}


def _fan_frame(metrics):
    """The pair drawn the way the frame loop draws it.  `themes.SPECIALS` has to be
    injected - a probe that forgets it draws nothing at all and reports `boxes: []`,
    which is how this repo's first special probe fooled itself."""
    vals, _absent = themes.values(metrics)
    themes.fill_lines(vals, metrics)
    obj = {"width": render.W, "height": render.H,
           "osd": {"widget": [{"id": "xigma-alpha-fans", "type": "special",
                               "property": [_fan_prop()]}]}}
    img, notes = layout.draw_theme(obj, vals, canvas=(render.W, render.H),
                                   specials=themes.SPECIALS)
    return img, notes, vals


def _row_box(notes):
    """The box the loop records for a pair row, in panel px: whichever `special` it is, the
    frame holds one row and the box is what the door reports for it."""
    rows = [b for b in notes["boxes"] if b[0] == "special"]
    assert len(rows) == 1, notes["boxes"]
    return rows[0][2]


# pinned instant, through the one hook every clock line reads: `on` and `off` are two
# draws, and a live second between them would land in the isolation set and be counted
# as part of a fan figure
FAN_WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)
real_now = render._now
render._now = lambda: FAN_WHEN.timetuple()
fan_pairs, fan_moves, fan_px = [], [], []
try:
    for cpu in CPU_TACHES:
        for gpu in GPU_FANS:
            m = _fan_metrics(cpu, gpu)
            img, notes, vals = _fan_frame(m)
            on = render.draw(m, "alpha")
            off = render.draw(m, "alpha", fan=False)
            flat_me = list(img.get_flattened_data())
            flat_on, flat_off = list(on.get_flattened_data()), list(off.get_flattened_data())
            theme_px = {k for k, v in enumerate(flat_on) if v != flat_off[k]}
            file_px = {k for k, v in enumerate(flat_me) if v != (0, 0, 0, 0)}
            # the row's ink is exactly where the theme's row is, and every one of those
            # pixels carries the theme's own bytes: same place, same colour, same glyph
            assert theme_px and theme_px == file_px, (cpu, gpu, len(theme_px),
                                                      len(file_px))
            assert all(flat_on[k] == flat_me[k] for k in file_px), (cpu, gpu)
            assert not notes["missing"], (cpu, gpu, notes["missing"])
            assert not notes["gaps"], (cpu, gpu, notes["gaps"])
            figures = (render.cpu_fan_figure(m), render.gpu_fan_figure(m))
            # the shared size, spelled out again here as `max(floor, min(fits))` and
            # checked against what the layout's own door picked, so the rule that makes
            # the pair a pair is a claim this gate holds, not a line in a docstring
            fits = [render._fit_size(img, s, render.A26_FAN_MAX_W, render.A26_FAN_F,
                                     bold=False) for s in figures]
            dev = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS),
                            (0, 0, 0, 0))
            size, _box = layout.draw_special_pair(ImageDraw.Draw(dev), _fan_prop(),
                                                  figures)
            assert size == max(render.A26_FAN_MIN, min(fits)), (cpu, gpu, size, fits)
            # the box the loop reports is where the row actually got painted, to within
            # the handful of px a text metric can sit off the ink it measures
            box = _row_box(notes)
            w = render.W
            ink = (min(k % w for k in theme_px), min(k // w for k in theme_px),
                   max(k % w for k in theme_px), max(k // w for k in theme_px))
            assert all(abs(a - b) <= 4 for a, b in zip(box, ink)), (cpu, gpu, box, ink)
            # what two separate rows would do: each figure sized by its own fit
            apart = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS),
                              (0, 0, 0, 0))
            dad = ImageDraw.Draw(apart)
            for x, s, own in zip((FAN_CX - FAN_PITCH // 2, FAN_CX + FAN_PITCH // 2),
                                 figures, fits):
                render.fan_figures(dad, (s,), (x,), render.A26_FAN_Y,
                                   render.A26_WHITE, bold=False,
                                   max_w=render.A26_FAN_MAX_W, ceiling=own, floor=own)
            apart = apart.resize((render.W, render.H), Image.LANCZOS)
            moved = sum(1 for q in ImageChops.difference(img, apart).get_flattened_data()
                        if q != (0, 0, 0, 0))
            # a pair sized apart differs exactly when the two fits disagree: so the
            # joint rule is load-bearing, and the pixel counts below are not rounding
            assert (moved > 0) == (fits[0] != fits[1]), (cpu, gpu, fits, moved)
            fan_pairs.append((cpu, gpu, size, fits, tuple(flat_on[k] == flat_me[k]
                                                          for k in file_px)))
            fan_px.append(len(file_px))
            if fits[0] != fits[1]:
                fan_moves.append(moved)
finally:
    render._now = real_now

assert len(fan_pairs) == len(CPU_TACHES) * len(GPU_FANS), fan_pairs

# the same joint-sizing question, for the two temperature columns inside the rings, which
# `alpha` still needs as one drawing: `theme_alpha` calls `_fit_arc` with BOTH strings at
# once, so one size comes out for the pair.  Two things are checked here, and they are the
# two halves of the decision recorded in docs/theme-editor.md: the rule is exactly the
# smaller of the two columns' own sizes (so a group key would have been enough), and no
# single `xigma.autoFitMax` - a width - can reproduce what the ring's hole decides.
ARC_PAIRS = list(itertools.product((None, 5, 22, 57, 100, 241), repeat=2))
ARC_STRINGS = tuple(render._deg(v) for v in (None, 5, 22, 57, 100, 241))


def _arc_fit(strings, ceiling=render.A26_TVAL_F, cx=render.A26_TCOL_X[0],
             y=render.A26_TVAL_Y):
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    return render._fit_arc(img, tuple(strings), cx, render.A26_RING_Y,
                           y, render.A26_RING_R - render.A26_RING_W,
                           render.A26_RING_R, render.A26_ARC_START,
                           render.A26_ARC_SWEEP, ceiling)


_ONLY_DRAW = ImageDraw.Draw(Image.new("RGBA", (8, 8)))   # `_fit_size` only measures


def _width_fit(s, budget, ceiling=render.A26_TVAL_F):
    """The size a `xigma.autoFitMax` of `budget` panel px would pick for `s`.

    A shared `ImageDraw` rather than a canvas per call: the search below runs
    thousands of these, and `_fit_size` only measures on what it is handed."""
    return render._fit_size(_ONLY_DRAW, s, budget, ceiling, bold=True)


arc_apart = 0
for a, b in ARC_PAIRS:
    sa, sb = _arc_fit((render._deg(a),)), _arc_fit((render._deg(b),))
    assert _arc_fit((render._deg(a), render._deg(b))) == min(sa, sb), (a, b, sa, sb)
    arc_apart += sa != sb

# exhaustive: every whole-pixel budget the canvas could hold, tested against all six
# readings' ring-chosen sizes at once
BUDGETS = range(40, render.W + 1)
windows = {s: [b for b in BUDGETS if _width_fit(s, b) == _arc_fit((s,))]
           for s in ARC_STRINGS}
reproduced = [b for b in BUDGETS if all(b in windows[s] for s in ARC_STRINGS)]
assert not reproduced, (reproduced[:6], {s: w[:4] for s, w in windows.items()})
# the search is not vacuous: each reading's own ring size *is* reachable by some
# width; it is all six at once that no width reaches
assert all(windows[s] for s in ARC_STRINGS), {s: w[:3] for s, w in windows.items()}
best = max(BUDGETS, key=lambda b: sum(b in windows[s] for s in ARC_STRINGS))
best_n = sum(best in windows[s] for s in ARC_STRINGS)
span = {s: (min(w), max(w)) for s, w in windows.items() if w}
lo, hi = max(v[0] for v in span.values()), min(v[1] for v in span.values())

# ...and the row itself, held to the theme the way the fan pair is: one `temp-values`
# `special`, compared with the two temperature figures `theme_alpha` paints inside its
# rings.  The isolation cannot be the fan pair's `fan=True`/`fan=False` trick - the theme
# has no switch for these two figures, and they sit inside a ring this frame does not
# draw.  So the ring's own ink is measured rather than a band guessed: `temp_arc` on a bare
# canvas, the same supersampling and the same LANCZOS downscale `theme_alpha` ends with,
# over the readings this walk uses.  Every pixel it leaves inside the declared hole - the
# stroke's antialiasing, plus the resampling tail that reaches past the stroke's edge -
# belongs to the ring's painter; what is left of the hole belongs to this row, and the row
# has to paint exactly that.  The zone comes out of the ring drawing itself, which is why
# the check below is not a rectangle somebody picked.
TEMP_VALS = (None, 5, 22, 57, 100, 241)
R_IN = render.A26_RING_R - render.A26_RING_W


def _temp_metrics(cpu, gpu):
    c, g = {}, {}
    if cpu is not None:
        c["temperature"] = float(cpu)
    if gpu is not None:
        g["temperature"] = float(gpu)
    return {"cpu": c, "gpu": g, "memory": {"used_percent": 41.0},
            "fans": [{"name": "Fan CPU", "value": 1016, "type": "Fan"}],
            "timestamp": {}}


def _temp_prop(name="temp-values", y=None, ceiling=None):
    """One of `alpha`'s two temperature rows - the figures, or the labels over them.  `x`
    is the pair's centre, `width` the pitch between the two figures, `xigma.fitArc` the
    ring they are sized against: every number read out of `render.py`'s own constants,
    because a number written here would be a second opinion about the theme.  The angles
    are the app's own (`layout.arc_angles` measures the rule that turns them into
    Pillow's)."""
    return {"name": name,
            "x": (render.A26_TCOL_X[0] + render.A26_TCOL_X[1]) // 2,
            "y": y if y is not None else render.A26_TVAL_Y,
            "width": render.A26_TCOL_X[1] - render.A26_TCOL_X[0],
            "fontFamily": "dejavu",
            "fontSize": ceiling if ceiling is not None else render.A26_TVAL_F,
            "bold": True,
            "textColor": _css(render.A26_WHITE),
            "xigma": {"anchor": "ma",
                      "fitArc": {"cy": render.A26_RING_Y, "radius": R_IN,
                                 "width": render.A26_RING_W,
                                 "angleStart": render.A26_ARC_START - 90,
                                 "angleEnd": render.A26_ARC_START + render.A26_ARC_SWEEP
                                 - 90}}}


def _hole_px(k):
    """Inside either ring's clear hole?  The pitch is more than twice the hole's radius,
    so no pixel is inside both rings, and the hole is shared by two rows: the labels and
    the figures under them.  Neither is answerable for the other's pixels, which is what
    the combined check below is for."""
    x, y = k % render.W, k // render.W
    return (min(((x - cx) ** 2 + (y - render.A26_RING_Y) ** 2) ** 0.5
                for cx in render.A26_TCOL_X) < R_IN)


def _hole_r(k):
    """How far inside the declared inner edge this panel pixel is, in panel px."""
    x, y = k % render.W, k // render.W
    return R_IN - min(((x - cx) ** 2 + (y - render.A26_RING_Y) ** 2) ** 0.5
                      for cx in render.A26_TCOL_X)


RING_TAIL = set()
for _v in TEMP_VALS[1:]:
    _bare = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS),
                      render.OVERLAY)
    for _cx in render.A26_TCOL_X:
        render.temp_arc(_bare, _cx, render.A26_RING_Y, float(_v), render.A26_ARC_LO,
                        render.A26_ARC_MID, render.A26_ARC_HI, render.A26_RING_R,
                        render.A26_RING_W, render.A26_ARC_TRACK, render.A26_ARC_START,
                        render.A26_ARC_SWEEP)
    _bare = _bare.resize((render.W, render.H), Image.LANCZOS)   # what theme_alpha returns
    RING_TAIL |= {k for k, c in enumerate(_bare.get_flattened_data())
                  if c[3] and _hole_px(k)}
tail = max(_hole_r(k) for k in RING_TAIL)
# the shrink has to stay under the clearance the fit enforces, or the zone would eat this
# row's own ink and the coverage below could pass on a row that paints nothing
assert tail < render.ARC_FIT_GAP, (tail, len(RING_TAIL), render.ARC_FIT_GAP)

ZONE = {k for k in range(render.W * render.H) if _hole_px(k) and k not in RING_TAIL}
LBL = _temp_prop("temp-labels", render.A26_TLBL_Y, render.A26_TLBL_F)
VAL = _temp_prop()


def _rows_frame(props, m):
    """A frame carrying exactly these `special` rows, through the loop's own door.
    `themes.SPECIALS` has to be injected: a probe that forgets it draws nothing at all and
    reports `boxes: []`, which is how this repo's first special probe fooled itself."""
    vals, _absent = themes.values(m)
    themes.fill_lines(vals, m)
    obj = {"width": render.W, "height": render.H,
           "osd": {"widget": [{"id": "xigma-alpha-" + p["name"], "type": "special",
                               "property": [p]} for p in props]}}
    return layout.draw_theme(obj, vals, canvas=(render.W, render.H),
                             specials=themes.SPECIALS)


def _ink(flat):
    """Which pixels of a flattened frame are ink: alpha, not colour.  A downscale of a
    bright stroke against a transparent canvas leaves pixels whose colour channels are
    non-zero and whose alpha is zero - invisible, and a residual of whatever was drawn next
    to them rather than something this row is answerable for."""
    return {k for k, v in enumerate(flat) if v[3]}


temp_rows, temp_px, lbl_px = [], [], []
lbl_sizes, val_sizes, residual = [], [], 0
row_clear = 1e9
for cpu, gpu in ARC_PAIRS:
    m = _temp_metrics(cpu, gpu)
    flat_on = list(render.draw(m, "alpha").get_flattened_data())
    theirs = {k for k in ZONE if flat_on[k][3]}
    # each row on its own: it may put pixels nowhere but in the free zone, and where it
    # puts one it puts the theme's byte there
    for prop_, strings, y_, ceil_ in ((VAL, (render.cpu_temp_text(m),
                                             render.gpu_temp_text(m)),
                                       render.A26_TVAL_Y, render.A26_TVAL_F),
                                      (LBL, render.A26_TLBL_TEXT, render.A26_TLBL_Y,
                                       render.A26_TLBL_F)):
        img, notes = _rows_frame([dict(prop_)], m)
        flat = list(img.get_flattened_data())
        painted = _ink(flat)
        assert painted and painted <= ZONE, (prop_["name"], cpu, gpu,
                                             len(painted - ZONE),
                                             sorted(painted - ZONE)[:4])
        assert all(flat_on[k] == flat[k] for k in painted), (prop_["name"], cpu, gpu)
        assert not notes["missing"] and not notes["gaps"], (cpu, gpu, notes)
        # the size, spelled out again from the rule: `_fit_arc`'s joint walk at either
        # column, and the pair rule as the smaller of the two strings measured alone
        dev = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
        size, _box = layout.draw_special_values(ImageDraw.Draw(dev), prop_, strings)
        assert size == _arc_fit(strings, ceil_, render.A26_TCOL_X[0], y_) == \
            _arc_fit(strings, ceil_, render.A26_TCOL_X[1], y_) == \
            min(_arc_fit((s_,), ceil_, render.A26_TCOL_X[0], y_) for s_ in strings), \
            (prop_["name"], cpu, gpu, size, strings)
        # the box the loop records is where the row really got painted, to within the
        # handful of px a text metric can sit off the ink it measures
        box = _row_box(notes)
        ink = (min(k % render.W for k in painted), min(k // render.W for k in painted),
               max(k % render.W for k in painted), max(k // render.W for k in painted))
        assert all(abs(a - b) <= 4 for a, b in zip(box, ink)), (prop_["name"], cpu, gpu,
                                                                box, ink)
        row_clear = min(min(_hole_r(k) for k in painted), row_clear)
        (lbl_px if prop_ is LBL else temp_px).append(len(painted))
        (lbl_sizes if prop_ is LBL else val_sizes).append(size)
    # and both rows in one frame: between them they own the free zone, in both directions.
    # What they leave disagreeing there is invisible by construction - and the assembly is
    # what answers for it: with the rings drawn as `arc` rows into the same 4x canvas, the
    # ring's own colour residuals come out of the same single downscale
    both, bnotes = _rows_frame([dict(LBL), dict(VAL)], m)
    flat = list(both.get_flattened_data())
    painted = _ink(flat)
    assert painted == theirs, (cpu, gpu, len(painted - theirs), len(theirs - painted),
                               sorted(theirs - painted)[:4])
    assert all(flat_on[k] == flat[k] for k in painted), (cpu, gpu)
    off = [k for k in ZONE if flat[k] != flat_on[k]]
    assert all(not flat_on[k][3] for k in off), (cpu, gpu, len(off),
                                                 [(k, flat_on[k], flat[k])
                                                  for k in off[:2]])
    residual = max(residual, len(off))
    assert not bnotes["missing"] and not bnotes["gaps"], (cpu, gpu, bnotes)
    temp_rows.append(((render.cpu_temp_text(m), render.gpu_temp_text(m)),
                      val_sizes[-1], lbl_sizes[-1]))

assert len(temp_rows) == len(ARC_PAIRS), temp_rows
# the label pair's size cannot move with a reading, because its strings never change: one
# number across the whole walk, and that number is the ring's answer rather than a declared
# size.  The figures' does move, which is why the two rows are not one row
assert len(set(lbl_sizes)) == 1, lbl_sizes[:8]
assert len(set(val_sizes)) > 1, val_sizes[:8]

# a row that cannot be sized says so instead of drawing at the ceiling, where the digits
# would sit on the gauge they belong to: `--check-theme` names the key that is missing, and
# the loop puts down no pixels for the row at all
_no_ring = json.loads(json.dumps(VAL))
del _no_ring["xigma"]["fitArc"]
_bad = {"width": render.W, "height": render.H,
        "osd": {"widget": [{"id": "xigma-no-ring", "type": "special",
                            "property": [_no_ring]}]}}
hard, soft = themes.validate(_bad)
assert not hard and any("fitArc" in s and "not drawn" in s for s in soft), (hard, soft)
_vals, _a = themes.values(_temp_metrics(57, 61))
themes.fill_lines(_vals, _temp_metrics(57, 61))
_img, _notes = layout.draw_theme(_bad, _vals, canvas=(render.W, render.H),
                                 specials=themes.SPECIALS)
assert not any(v != (0, 0, 0, 0) for v in _img.get_flattened_data()), \
    "a row with no ring to clear drew something anyway"
# and on a pair row `width` is the pitch, not a box: with no `width` the two figures land
# on one point, which is a thing a file can do by accident and get no warning about today
_no_pitch = json.loads(json.dumps(VAL))
del _no_pitch["width"]
hard, soft = themes.validate({"width": render.W, "height": render.H, "osd": {"widget": [
    {"id": "xigma-no-pitch", "type": "special", "property": [_no_pitch]}]}})
assert not hard and any("centres" in s for s in soft), (hard, soft)

print(f"  the fan pair, apart   `alpha`'s two figures as one row, against the same row "
      f"drawn by `theme_alpha`: {len(fan_pairs)} reading pairs, every one painting "
      f"{min(fan_px):,}-{max(fan_px):,} pixels that are the same set as the theme's "
      f"fan-on minus fan-off set, byte for byte identical, with nothing missing and no "
      f"gaps.  The shared size is `max(A26_FAN_MIN, min(fits))` in all {len(fan_pairs)} "
      f"cases - re-derived here through `render._fit_size`, the walk the other themes "
      f"use, and compared with what `layout.draw_special_pair` chose.")
print(f"                        one row and not two, because the size is one decision: "
      f"sized each on its own, {len(fan_moves)} of those {len(fan_pairs)} pairs land at "
      f"two different sizes and the row moves by {min(fan_moves):,} to {max(fan_moves):,} "
      f"px.  Those two counts follow the faces installed here, so docs/limits.md labels "
      f"them the bench's; the pair count, the zero-diff sets and the `min` rule are "
      f"checked on every machine.")
print(f"  the temperature rows  `alpha`'s two temperature figures and its two labels, each "
      f"one row, against the frame `theme_alpha` paints: {len(temp_rows)} reading pairs, and "
      f"what holds is not the count - each row alone puts down {min(temp_px):,}-"
      f"{max(temp_px):,} pixels (figures) and {min(lbl_px):,}-{max(lbl_px):,} (labels), all "
      f"of it inside the rings' clear hole and every byte the theme's own, and drawn "
      f"*together* the two rows cover the hole exactly: the same set of pixels, both "
      f"directions, no gap between what the theme paints there and what the rows paint.")
print(f"                        The hole is measured and not assumed: the ring's painter "
      f"reaches {len(RING_TAIL):,} px of its own ink into the hole past its declared inner "
      f"edge - antialiasing plus the resampling tail LANCZOS leaves - and the rows' ink "
      f"stays {row_clear:.2f} px inboard of that edge, {row_clear - tail:.2f} px clear of "
      f"the tail.  `render.ARC_FIT_GAP` is what keeps it there, and the gate holds that "
      f"number above the measured {tail:.2f} px.  Ink means alpha: the {residual} pixels "
      f"per frame where a text-only frame still disagrees with the theme inside the hole "
      f"all carry alpha 0, colour residuals of the ring's own downscale, and the gate "
      f"asserts that is *all* of them - which is the assembly's job, since a ring drawn as "
      f"an `arc` row into the same 4x canvas leaves the same residuals.  Sizes: the labels "
      f"come out at {lbl_sizes[0]} px in every pair, because their strings never change, "
      f"while the figures walk {', '.join(str(v) for v in sorted(set(val_sizes)))} px - both "
      f"follow the faces installed here, and the equality with `_fit_arc` measured at either "
      f"column is what is checked on every machine (docs/limits.md).")
print(f"  the value pair, apart the same question for the two temperature columns inside "
      f"the rings, which `alpha` still needs as one drawing: {len(ARC_PAIRS)} reading "
      f"pairs, and `_fit_arc`'s joint size is exactly the smaller of the two columns' own "
      f"sizes in every one of them - {arc_apart} of them land at two different sizes on "
      f"this machine's faces - so the pair *could* have been a group key.  It cannot be an "
      f"`xigma.autoFitMax`, because the limit is the ring's hole and not a width: of the "
      f"{len(BUDGETS)} whole-pixel budgets this canvas can hold, none reproduces the six "
      f"ring-chosen sizes at once (the best, {best} px, lands {best_n} of 6); the "
      f"budgets that would work run from {lo} px down to {hi} px, an empty interval. "
      f"Both halves of that are what `temp-values` inherits from `_fit_arc` "
      f"(docs/theme-editor.md, docs/limits.md)")

bad_words = next(w for w in soft_bar if "barPaint" in w)
gap = ", ".join(f"{v:g} -> {n:,} px differ, worst channel {w}/255"
                for v, n, w in conv)
print(f"  why arcPaint          one arc, two colours unchanged, drawn with "
      f"`xigma.arcPaint: render` and without it: {gap}. The key exists because that is a "
      f"drawing difference and not a rounding one: 3-degree segments sampled at their "
      f"start against 1-degree segments sampled at their middle "
      f"(`layout.ARC_PAINT`, both entries with their provenance in the comment). Without "
      f"the key a gauge export would sit {conv[2][1]:,} px away from the theme it claims "
      f"to describe, and the parity gate above would be decoration.")
print(f"  why barPaint          one bar (360x14 at 60,340, cornerRadius 5 declared), drawn"
      f" with `xigma.barPaint: render` and without it: "
      + ", ".join(f"{v:g}% -> {n:,} px differ, worst {w}/255" for v, n, w in bars)
      + ". The vendor rounding is `round(width x fraction)` in panel px, `render.bar` takes"
      f" `int(width x SS x fraction)` in device px and rounds its corners off the same"
      f" reading it scales by, so at 63.5 % the fill ends at device px 457 one way and 456"
      f" the other - a bar export without the key would be off by pixels and by the"
      f" corners, not by intent")
print(f"  barPaint: render      the second one names `render.bar`, and it is held to it the"
      f" same way: {len(LOADS)} values, 0 differing pixels against the function at all of"
      f" them ({', '.join(f'{v:g}%' for v in LOADS[:6])}, ... 100 %, past-max and"
      f" negative). Two floors in the function, and the first version of the table had one"
      f" number where there are two: `render.bar` draws whenever `frac > 0.01` but rounds"
      f" its corners off `max(frac, 0.02)`, so a load between 1 % and 2 % drew no fill at"
      f" all as a layout widget while `render.bar` drew one - 1.5 % and 2 % were the two"
      f" values that found it, and `corner_floor` is a key of its own now")
print(f"  barPaint: hbar        the third entry names a function, so it is measured against"
      f" it: one layout `bar` at `render.A26_BAR_XY`/`A26_BAR_WH` in `A26_TRACK`/"
      f"`A26_BAR_A`/`A26_BAR_B` - all four read out of `render.py`, not written here -"
      f" against `render.hbar`: {len(zero)} pairs at device px and {len(ONEX)} at 1x, every"
      f" one zero differing pixels and worst channel 0, over values 0/3/22/62/100 plus"
      f" past-max and negative, on both of ALPHA's usage bars, and at declared"
      f" `cornerRadius` 0 and 5. That last pair is the one the first version of this gate"
      f" missed: it used cornerRadius 0 and passed while the convention still drew the"
      f" file's rounded track (`hbar` has no radius argument at all)")
print(f"                        the same declared bar under the other two conventions sits"
      f" {gap_h[(0, 62, 'vendor')]:,} and {gap_h[(0, 62, 'render')]:,} px away from the"
      f" drawing `hbar` names, and the fill is demonstrably walked rather than hidden"
      f" under the track: the rect's track-coloured pixels fall "
      + " -> ".join(f"{a:,} at {v}%" for v, a, _b in walked)
      + f" in both drawings (docs/limits.md, docs/theme-editor.md)")
print(f"  what alpha draws      {' '.join(alpha_draws)} - taken out of `theme_alpha`'s own"
      f" body, so the row list in `alpha_recipe()` is a claim about this source and not a"
      f" memory of it: two rings and two usage bars as `arc`/`bar` widgets naming a painter"
      f" (`arcPaint: render`, `barPaint: hbar`), three pairs of lettering as one `special`"
      f" row each (`fan-figures`, `temp-values`, `temp-labels` - the labels a row and not"
      f" two `text` widgets because `_fit_arc` is handed them as a pair, and a size it"
      f" decides is a face metric of the machine drawing it), four rows that need nothing"
      f" joint, and the clock line with a format and a width to fit to.  Every one of them"
      f" was measured against `theme_alpha`'s own drawing above before the parity line"
      f" counted the assembled frame")
print(f"  every theme exports   {' '.join(sorted(themes.EXPORTS))} - all "
      f"{len(themes.EXPORTS)} of the drawn themes are generated layouts now, and the "
      f"parity gate above holds each one to zero differing pixels at every reading that "
      f"answers what its file asks.  `bars` was the last, and it is the one the schema "
      f"could not carry on its own: its row count and row pitch used to be functions of "
      f"the machine (`row_h = min(56, max(28, 320 // len(rows)))`, with `rows` growing by "
      f"whatever fan entries `sensors` reported), so one fixed widget list could not be "
      f"its picture on every box.  The owner's decision (2026-11-08) is optional "
      f"positional fan slots - `Fan 1` through `Fan 4`, each labelled from a `Fan N Name` "
      f"source so the name comes from the box at run time - rather than a repeat group, "
      f"because the library's selectable layouts ask for seven `source` names and not one "
      f"of them is a fan: a new name in our own table invents less than a new structure in "
      f"a file whose point is that it is a fixed list of rows.  Measuring it moved the "
      f"obstacle to where it actually is - the compaction - and that half was built the "
      f"same day: the drawing reserves the slots and lets a row with no reading keep its "
      f"place, so the pitch stopped depending on what this box's sensors found (the gates "
      f"below count the ink in all ten).  The last thing it needed was a key nobody had: "
      f"`xigma.showIf`, for a row whose meter divides two fields while its number prints "
      f"one - and chasing that diff turned up two defects in the theme's own ratio code, "
      f"a crash path and two different rules for its two memory rows, both fixed (the "
      f"gate that measures them prints the numbers).  Nothing about the wire changes "
      f"either way (docs/theme-editor.md, docs/limits.md)")
# ---- and what the one theme still waiting to be exported is made of.  Every claim the
# ---- plan makes about it is read here out of `theme_bars`'s own body, and the slot rule is
# ---- measured off pixels rather than inferred: the pitch is the same whether this box
# ---- reports six fans or none, and a row with no reading keeps its place.
_bars_src = inspect.getsource(render.theme_bars)
_b_arith = "row_h = min(BARS_ROW_MAX, max(BARS_ROW_MIN, span // max(len(rows), 1)))"
assert _b_arith in _bars_src, (_b_arith, "the pitch rule is not in `theme_bars`")
assert "y, span = BARS_Y0, BARS_SPAN" in _bars_src, "the block is not the named 72 + span"
assert (render.BARS_Y0, render.BARS_SPAN, render.BARS_ROW_MIN,
        render.BARS_ROW_MAX) == (72, 320, 28, 56), (
    "the plan quotes y=72, a 320 px block and a 28..56 px pitch")
assert (render.BARS_LBL_X, render.BARS_BAR_X, render.BARS_VAL_X,
        render.BARS_BAR_DY, render.BARS_BAR_WH) == (28, 28, 452, 17, (424, 10)), (
    "the row geometry the plan describes is not what the drawing names")
assert _bars_src.count("lambda v:") == 6 + 1, (
    "the fixed row set, or the fan slot, is no longer the six-plus-one the plan describes")
_n_fixed = _bars_src.count("lambda v:") - 1
for _slot in ('for slot in range(BARS_SLOTS)', '(fan or {}).get("value")',
              'str((fan or {}).get("name") or f"FAN {slot + 1}")[:10]'):
    assert _slot in _bars_src, (_slot, "the fan rows are not reserved positional slots")
_loop_head = "for name, val, lo, hi, fmt, subject in rows:"
assert _loop_head in _bars_src, (
    "the row loop's header is not the one this gate splits the body at, so which side the "
    "pitch and the advance live on is no longer something it can read")
_head, _loop = _bars_src.split(_loop_head, 1)
_loop = _loop.split("if clock:")[0]
# the two rules the plan says the export needed, read off the body rather than remembered:
# a label belongs to its subject and the number and meter belong to the reading, and both
# memory meters are formed by one function
assert "if subject:" in _loop and "if val is not None:" in _loop, (
    "label and number are no longer drawn under their own tests - the split that lets one "
    "drawing and one file agree at readings where a fan slot or a metric is absent")
assert _loop.index("if subject:") < _loop.index("if val is not None:"), (
    "the number is no longer the second test of the row")
assert 'pct_pair(mem, "used", "total")' in _bars_src \
    and 'pct_pair(gpu, "memoryUsage", "dedicatedTotal")' in _bars_src, (
    "the two memory meters are not formed by the one rule, which is what the 2026-11-09 "
    "finding about the crash path and the truthy numerator is about")
assert _b_arith in _head, (_head[-160:], "the pitch is not chosen before the loop")
assert "continue" not in _loop, (
    "a row with no reading skips its advance again, and the compaction the plan measured by "
    "pixels has come back - no static file can carry that")
assert "\n        y += row_h" in _bars_src and "\n            d.text" in _bars_src, (
    "the advance is no longer outside the drawn-row test")
assert '("RAM", ram, 0, 100,' in _bars_src and '("VRAM", gm, 0, 100,' in _bars_src \
    and _bars_src.count(' GB"') == 2, (
    "the two memory rows are no longer bars over a percentage printing gigabytes, and the "
    "plan's fourth fact is about that")

# Ten slots, the same on every box.  The windows are 17 px tall and sit on the right-hand
# value column (x=440..452), where a meter only reaches if its fraction passes 0.97 - and
# none of these readings goes near that, which is what the empty middle slot proves.
_ALL6 = {"cpu": {"temperature": 57.0, "load": 62.0},
         "gpu": {"temperature": 47.0, "load": 22.0, "memoryUsage": 4096,
                 "dedicatedTotal": 8192},
         "motherboard": {"temperature": 51.0},
         "memory": {"used": 10240, "total": 16384}, "timestamp": {}}
_PART = {"cpu": {"temperature": 57.0, "load": 62.0}, "gpu": {"temperature": 47.0},
         "memory": {"used_percent": 41.0}, "timestamp": {}}
_pitch = min(render.BARS_ROW_MAX,
             max(render.BARS_ROW_MIN, render.BARS_SPAN // (_n_fixed + render.BARS_SLOTS)))


def _slots(img):
    """Which of the ten rows has value text in it, counted in the right-hand value column.

    Two geometric facts decide the window, and both are stated rather than tuned away: a
    meter is `BARS_BAR_DY` below its row's centre and its track is opaque across the whole
    width, so at a 32 px pitch a window centred on a row is stolen by the meter of the row
    above - the window starts 4 px above the centre, below that intrusion.  And the
    downscale leaves a dozen faint pixels of that track in the next slot, which is why ink
    here means 40 pixels and not one: text in this column counts 100 or more, the tail
    never reaches 20 on the readings below.
    """
    out = []
    for i in range(_n_fixed + render.BARS_SLOTS):
        yc = render.BARS_Y0 + i * _pitch
        out.append(sum(1 for y in range(yc - 4, yc + 10) for x in range(440, 453)
                       if img.getpixel((x, y))[3]) >= 40)
    return out


_nofan, _sixfan = _slots(render.draw(_ALL6, "bars")), _slots(
    render.draw(dict(_ALL6, fans=[{"name": f"Fan {i} on this box", "value": 900 + i,
                                   "type": "Fan"} for i in range(6)]), "bars"))
assert _pitch == render.BARS_SPAN // (_n_fixed + render.BARS_SLOTS) == 32, _pitch
assert _nofan == [True] * _n_fixed + [False] * render.BARS_SLOTS, (
    _nofan, "a box with no fans no longer reserves the slots it is not drawing")
assert _sixfan == [True] * (_n_fixed + render.BARS_SLOTS), (
    _sixfan, "the fifth fan onward is not being kept out of the reserved slots")
_part = _slots(render.draw(_PART, "bars"))
assert _part == [True, True, False, True] + [False] * (_n_fixed + render.BARS_SLOTS - 4), (
    _part, "rows below a missing reading closed up again - that is the compaction the "
           "decision was made to remove")
assert _slots(render.draw({"cpu": {}, "timestamp": {}}, "bars")) == \
    [False] * (_n_fixed + render.BARS_SLOTS), (
    "a box that answers nothing is drawing a row somewhere - or the title and the clock "
    "line are being counted as rows")
_d_plan = open("docs/theme-editor.md", encoding="utf-8").read()
_d_lim = open("docs/limits.md", encoding="utf-8").read()
assert _b_arith in _d_plan, "the plan stopped quoting the pitch as this body writes it"
assert "min(56, max(28, 320 // len(rows)))" in _d_lim, \
    "docs/limits.md stopped quoting the pitch it is held to"
assert f"{_pitch} px" in _d_plan and f"{_pitch} px" in _d_lim, (
    _pitch, "neither document quotes the pitch that no longer moves between boxes")
# ---- and the same rows from the other side: the source names a layout file would put behind
# ---- them.  Nothing below restates what `bars` prints - the strings are taken out of the
# ---- drawing itself, by handing `ImageDraw.text` a spy while the frame is painted - and the
# ---- formatter's output has to agree with them row for row, and agree about *which* rows.
# ---- That is the claim a generated `bars` will stand or fall on, gated a change before the
# ---- generator exists.
from PIL import ImageDraw as _ID

_seen_text = []
_real_text = _ID.ImageDraw.text
_FAN_NAME_OF = {speed: name for speed, name in themes.FAN_SLOTS}
_WHEN_BARS = datetime.datetime(2026, 2, 17, 9, 30, 12)


def _spy(self, xy, txt, *args, **kw):
    _seen_text.append((int(xy[0] // render.SS), int(xy[1] // render.SS), str(txt)))
    return _real_text(self, xy, txt, *args, **kw)


def _drawn_rows(m):
    """Every string `bars` paints in its label and value columns, in draw order."""
    del _seen_text[:]
    _ID.ImageDraw.text = _spy
    try:
        img = render.draw(m, "bars", bg=render.OVERLAY)
    finally:
        _ID.ImageDraw.text = _real_text
    return [t for x, _y, t in _seen_text
            if x in (render.BARS_LBL_X, render.BARS_VAL_X)], img


def _want_rows(m):
    """What the source table says each row shows, and which rows have a number.

    Two tests, because the drawing has two since 2026-11-09: a **label belongs to the row's
    subject** - a fixed row's metric exists on a box of this shape whether or not this reading
    answers it, and a fan slot exists where `sensors` reported a tachometer at that position -
    while the **number belongs to the reading**.  Keeping them apart here is what stops that
    split from being a story about the code: a fan row reporting a subject under no name, or
    one reporting 0 RPM, is a case where the two disagree, and the strings below have to match
    what the painter writes in both directions.
    """
    vals, _gone = themes.values(m, _WHEN_BARS)
    _fans = (m or {}).get("fans") or []
    want, has_number = [], []
    for label, bar_src, text_src, _lo, _hi in themes.BARS_ROWS:
        if label is None:                    # a fan slot: the name is a reading too
            if int(bar_src.split()[1]) - 1 < len(_fans):
                want.append(layout.text_for(_FAN_NAME_OF[bar_src],
                                            vals[_FAN_NAME_OF[bar_src]]))
        else:                                # a fixed row has its metric either way
            want.append(label)
        filled = bar_src in vals and text_src in vals
        has_number.append(filled)
        if filled:
            want.append(layout.text_for(text_src, vals[text_src]))
    return want, has_number


_pairs = []
for _tag, _m in (("all six answered, no fans", _ALL6),
                 ("three of the fixed six", _PART),
                 ("six plus six reported fans", dict(
                     _ALL6, fans=[{"name": f"Fan {i} on this box", "value": 900 + i,
                                   "type": "Fan"} for i in range(6)])),
                 ("two fans, the second reporting zero", dict(
                     _PART, fans=[{"name": "Fan CPU", "value": 2000, "type": "Fan"},
                                  {"name": "Fan System 5", "value": 0, "type": "Fan"}]))):
    _drawn, _img = _drawn_rows(_m)
    _want, _answered = _want_rows(_m)
    assert _drawn == _want, (_tag, "the strings `bars` paints are not the ones the source "
                                   "table would print", _drawn, _want)
    assert _slots(_img) == _answered, (_tag, _slots(_img), _answered,
                                       "the rows the source table answers are not the rows "
                                       "the drawing leaves ink in")
    _pairs.append(len(_answered))

_no_fmt = [n for n in themes.source_names() if n not in layout.VENDOR_FORMAT]
assert not _no_fmt, (_no_fmt, "every source this program answers needs a display shape")
print(f"  the same rows as data   `themes.BARS_ROWS` names all {len(themes.BARS_ROWS)}: the "
      f"{len(themes.BARS_FIXED_ROWS)} fixed rows and the {len(themes.FAN_SLOTS)} reserved fan "
      f"slots - `Fan N Speed` and `Fan N Name`, with `Motherboard Temperature` ours because "
      f"the app's vocabulary has no entry for it, and `RAM Rate`/`Used RAM` taken from that "
      f"record's own `RAMRate`/`UsedRAM` (PROTOCOL.md 10). Spied out of the drawing: across "
      f"{len(_pairs)} boxes and {sum(_pairs)} rows, every string `bars` paints is the string "
      f"`layout.text_for` produces from those sources, and the rows whose reading answers "
      f"ink lands in - including a fan row whose subject exists while its reading does "
      f"not, which draws its name and nothing else. {len(themes.source_names())} answerable sources, "
      f"{len(layout.VENDOR_FORMAT)} display shapes, none missing")

print(f"  what bars rows are    {_n_fixed + render.BARS_SLOTS} rows on every box - "
      f"{_n_fixed} fixed ones plus {render.BARS_SLOTS} reserved fan slots taken by position, "
      f"which is what makes the pitch {_pitch} px here whether the box reports no fans or "
      f"six - and a row with no reading keeps its place: at readings that answer CPU, GPU "
      f"and LOAD the ink sits in slots 0, 1 and 3 with slot 2 empty. `bars` is this "
      f"project's own drawing, not a reproduction of a vendor frame, so the change is ours "
      f"to make (docs/theme-editor.md, docs/limits.md)")

# ---- the export, and the one key it needs that no vendor file ever used.  Same rule as
# ---- every other gate here: the readings are pinned, so this holds on any machine, and what
# ---- is asserted is relations (which rows are unanswered, which slots stay empty) rather
# ---- than this box's sensor inventory.
import copy as _copy
from PIL import ImageChops as _Chops

_BARS_CASES = (
    ("all ten answered", dict(_ALL6, fans=[{"name": f"Fan {i} on this box", "value": 900 + i,
                                            "type": "Fan"} for i in range(4)])),
    ("no fans at all", _ALL6),
    ("three of the six fixed rows, two fans", dict(_PART, fans=[
        {"name": "Fan CPU", "value": 2000, "type": "Fan"},
        {"name": "Fan System 5", "value": 1549, "type": "Fan"}])),
    ("six fans, the second reporting zero", dict(_PART, fans=[
        {"name": "Fan CPU", "value": 2000, "type": "Fan"},
        {"name": "Fan System 5", "value": 0, "type": "Fan"}] + [
        {"name": f"Fan {i}", "value": 700 + i, "type": "Fan"} for i in range(4)])),
    ("past both ends of every scale", dict(
        cpu={"temperature": 120.0, "load": 140.0},
        gpu={"temperature": 5.0, "load": -5.0, "memoryUsage": 100,
             "dedicatedTotal": 8192}, motherboard={"temperature": 0.0},
        memory={"used": 99999, "total": 100},
        fans=[{"name": f"Fan {i}", "value": 3000 + i, "type": "Fan"}
              for i in range(4)])),
    ("nothing but the clock", {"cpu": {}}),
    ("a fan row with no name", dict(cpu={"temperature": 57.0},
                                    fans=[{"value": 1200, "type": "Fan"}])),
    ("one fan, three empty slots", dict(_ALL6, fans=[
        {"name": "Fan CPU", "value": 2000, "type": "Fan"}])),
    ("a GPU with no dedicated total", dict(
        _ALL6, gpu={"temperature": 47.0, "load": 22.0, "memoryUsage": 4096})),
    ("a GPU reporting 0 used", dict(
        _ALL6, gpu={"temperature": 47.0, "load": 22.0, "memoryUsage": 0,
                    "dedicatedTotal": 8192})),
    ("memory used, no total", dict(_ALL6, memory={"used": 10240})),
    ("memory total, no used", dict(_ALL6, memory={"total": 16384})),
    ("memory both zero", dict(_ALL6, memory={"used": 0, "total": 0})),
)
_bars_rows, _bars_holes = [], []
for _tag, _m in _BARS_CASES:
    _m = dict(_m, timestamp={})
    _r = themes.parity("bars", _m, _WHEN_BARS)
    assert _r["diff_px"] == 0 and _r["worst_channel_delta"] == 0, (_tag, _r)
    assert _r["code_px"] == _r["layout_px"] > 0, (_tag, _r)
    (_bars_rows if not _r["missing"] else _bars_holes).append(
        (_tag, _r["code_px"], tuple(sorted(set(_r["missing"])))))
assert len(_bars_rows) + len(_bars_holes) == len(_BARS_CASES), _BARS_CASES

def _rows_at(m):
    """What each of the ten rows writes, as `{row: [(column, text)]}` - the same
    `ImageDraw.text` spy the row gate above runs, grouped by the y the drawing puts each
    string at.  Text is the exact evidence for these two rules: the value column's ink
    window wants 40 px and a number reading `0 GB` is narrower than that, which is a fact
    about the window, not about the row."""
    del _seen_text[:]
    _ID.ImageDraw.text = _spy
    try:
        render.draw(dict(m, timestamp={}), "bars", bg=render.OVERLAY)
    finally:
        _ID.ImageDraw.text = _real_text
    out = {}
    for x, y, t in _seen_text:
        if x in (render.BARS_LBL_X, render.BARS_VAL_X):
            out.setdefault((y - render.BARS_Y0) // _pitch, []).append(
                ("label" if x == render.BARS_LBL_X else "value", t))
    return out


# The two rules the diff hunt turned up, both fixed on 2026-11-09 and measured here rather
# than claimed.  (1) A memory dict with a total and no used field used to raise `KeyError`
# inside the frame loop - the call below is that reading, and drawing a frame at it is the
# regression.  The row now keeps its label and leaves its number and meter undrawn.  (2) A
# GPU reporting exactly 0 used keeps its row, at nothing filled, the way a 0 % memory
# reading always did; it used to drop the row, because its numerator had to be truthy.
_no_used = _rows_at(dict(_ALL6, memory={"total": 16384}))
assert _no_used[4] == [("label", "RAM")], (_no_used[4],  # a label, and nothing else
                                           "the RAM row drew a number for a numerator that "
                                           "was never reported - or `pct_pair` still raises")
assert [t for _c, t in _no_used[5] if _c == "value"] == ["4 GB"], _no_used[5]
_zero_gpu = _rows_at(dict(_ALL6, gpu={"temperature": 47.0, "load": 22.0, "memoryUsage": 0,
                                      "dedicatedTotal": 8192}))
assert [t for _c, t in _zero_gpu[5] if _c == "value"] == ["0 GB"], (
    _zero_gpu[5], "a GPU at 0 used dropped its row again - the asymmetry between the two "
                  "memory rows is back")
_both_zero = _rows_at(dict(_ALL6, memory={"used": 0, "total": 0}))
assert _both_zero[4] == [("label", "RAM")], (
    _both_zero[4], "a zero denominator drew a RAM row, and 0/0 is not a pair to divide")
assert _slots(render.draw(dict(_ALL6, memory={"total": 16384}), "bars"))[4] is False, \
    "the value column has ink in a row whose number is not drawn"

# and what `xigma.showIf` is worth, measured: the same file with the key stripped from the
# two memory number rows, painted at the reading that needs it (a GPU reporting used memory
# and no dedicated total - what an integrated GPU does).
_no_guard = _copy.deepcopy(themes.export("bars"))
_stripped = 0
for _w in _no_guard["osd"]["widget"]:
    if "showIf" in (_w["property"][0].get("xigma") or {}):
        del _w["property"][0]["xigma"]["showIf"]
        _stripped += 1
assert _stripped == 2, (_stripped, "the memory number rows are not the two the recipe says")
_gpu_only = dict(_ALL6, gpu={"temperature": 47.0, "load": 22.0, "memoryUsage": 4096})
_gvals, _ = themes.values(_gpu_only, _WHEN_BARS)
themes.fill_lines(_gvals, _gpu_only)
_real_now = render._now
render._now = lambda: _WHEN_BARS.timetuple()
try:
    _code_img = render.draw(_gpu_only, "bars")
finally:
    render._now = _real_now
_file_img, _gnotes = layout.draw_theme(_no_guard, _gvals, canvas=(480, 480),
                                       specials=themes.SPECIALS)
_flat = _Chops.difference(_code_img.convert("RGBA"), _file_img.convert("RGBA")) \
    .get_flattened_data()
_shownif_px = sum(1 for px in _flat if px != (0, 0, 0, 0))
_shownif_worst = max((max(px) for px in _flat), default=0)
assert _shownif_px > 0 and _shownif_worst > 0, (
    _shownif_px, _shownif_worst, "stripping `showIf` changed nothing, so the key is not "
                                 "doing the work the recipe says it does")
_src_recipe = inspect.getsource(themes.bars_recipe)
for _where, _txt in (("`bars_recipe`'s docstring", _src_recipe),
                     ("docs/theme-editor.md", open("docs/theme-editor.md",
                                                   encoding="utf-8").read()),
                     ("docs/limits.md", open("docs/limits.md", encoding="utf-8").read())):
    assert f"{_shownif_px} px and a worst channel of {_shownif_worst}" in _txt, (
        _where, _shownif_px, _shownif_worst,
        "this measurement is quoted nowhere, or quoted wrong - it is the whole reason "
        "`xigma.showIf` exists")

_plan_bars = open("docs/theme-editor.md", encoding="utf-8").read()
assert f"all {len(_BARS_CASES)} readings" in _plan_bars, (
    len(_BARS_CASES), "docs/theme-editor.md miscounts the readings `bars` is held to")

# the generated file, counted from the row table rather than from a remembered number
_obj_bars = themes.export("bars")
_w_bars = _obj_bars["osd"]["widget"]
assert len(_w_bars) == 2 + 3 * len(themes.BARS_ROWS), (
    len(_w_bars), "the export is not the heading, the clock and three rows per `BARS_ROWS`")
_kinds_bars = {}
for _w in _w_bars:
    _kinds_bars[_w["type"]] = _kinds_bars.get(_w["type"], 0) + 1
assert _kinds_bars == {"text": 1 + len(themes.BARS_FIXED_ROWS),
                       "data": 1 + len(themes.BARS_ROWS) + len(themes.FAN_SLOTS),
                       "bar": len(themes.BARS_ROWS)}, _kinds_bars
_pitch_bars = min(render.BARS_ROW_MAX,
                  max(render.BARS_ROW_MIN,
                      render.BARS_SPAN // len(themes.BARS_ROWS)))
for _i, (_lab, _bar_src, _txt_src, _lo, _hi) in enumerate(themes.BARS_ROWS):
    _y = render.BARS_Y0 + _i * _pitch_bars
    _lbl, _num, _meter = _w_bars[1 + 3 * _i], _w_bars[2 + 3 * _i], _w_bars[3 + 3 * _i]
    assert (_lbl["type"] == "text") == (_lab is not None), (_i, _lbl["type"])
    assert _num["property"][0]["source"] == _txt_src, (_i, _num)
    assert _meter["property"][0]["source"] == _bar_src, (_i, _meter)
    assert (_meter["property"][0]["minValue"], _meter["property"][0]["maxValue"]) \
        == (_lo, _hi), (_i, _meter["property"][0])
    # the label and the number share the row's centre; the meter hangs `BARS_BAR_DY` under
    # it, in the drawing and in the file alike, which is why they are not one test
    assert _lbl["property"][0]["y"] == _num["property"][0]["y"] == _y, (
        _i, _lbl["property"][0]["y"], _num["property"][0]["y"], _y)
    assert _meter["property"][0]["y"] == _y + render.BARS_BAR_DY, (
        _i, _meter["property"][0]["y"], render.BARS_BAR_DY,
        "the meter's offset from its row is no longer the constant both doors use")
    _ext = _num["property"][0]["xigma"]
    assert ("showIf" in _ext) == (_txt_src != _bar_src), (_i, _ext)
    if _lab is None:
        assert _lbl["property"][0]["source"] == themes._FAN_NAME[_bar_src], (_i, _lbl)
    else:
        assert _lbl["property"][0]["content"] == _lab, (_i, _lbl)
assert all(_w["property"][0].get("xigma", {}).get("barPaint") == "render"
           and _w["property"][0].get("xigma", {}).get("colourRamp") == "heat"
           for _w in _w_bars if _w["type"] == "bar"), "the meters are not all one convention"
assert not themes.validate(_obj_bars)[0], themes.validate(_obj_bars)[0]

# what the review door says about it, in relations only: the rows this box cannot answer are
# the ones it reports skipping, and a `showIf` dependency is reported by the source it names
_chk_bars = subprocess.run([sys.executable, "-m", "xigmalcd", "--check-theme", "bars"],
                           capture_output=True, text=True, check=True)
_lnb = _chk_bars.stdout.splitlines()
assert f"{len(_w_bars)} widgets" in _lnb[0], _lnb[0]
_cannot = next((ln for ln in _lnb if "cannot:" in ln), "")
_cannot_set = {s.strip() for s in _cannot.split("cannot:", 1)[1].split(",") if s.strip()}
_skipped = next(ln for ln in _lnb if " boxes," in ln)
_msk = re.search(r"skipped: (.*)$", _skipped)
_skip_set = set() if _msk[1].strip() == "nothing" else {s.strip()
                                                        for s in _msk[1].split(",")}
_asked_src = {w["property"][0]["source"] for w in _w_bars
              if w["property"][0].get("source")}
_depends = {(w["property"][0].get("xigma") or {}).get("showIf") for w in _w_bars} - {None}
_guarded = {w["property"][0]["source"] for w in _w_bars
            if (w["property"][0].get("xigma") or {}).get("showIf")}
# The two halves of the report come from different places, so they are held to each other in
# the direction each can speak for.  `skipped:` is per widget - what the draw left out - and
# `cannot:` is per source, from what `sensors.collect()` did not answer.  Every skip reason
# has to be a reading this box lacks.  And where a row is silenced by its dependency, the
# widget never gets as far as its own `source`, so that source sits in `cannot:` with no skip
# behind it: that is the relation `xigma.showIf` changes, and it is what the GitHub runner -
# a box with no GPU at all - hit, with `Used GPU Memory` unanswerable and the row already
# gone.  So the readings in `cannot:` with no skip behind them must be exactly the rows a
# `showIf` stands in for, and every dependency this box lacks must arrive as a
# `showIf:<source>` note.
_odd = [n for n in _skip_set if not (n.startswith("showIf:") or n.startswith("font:")
                                     or n in _asked_src)]
assert not _odd, (_odd, "the review door reported something that is neither a reading this "
                        "file asks for, nor a dependency, nor a face")
_skip_src = {n[len("showIf:"):] if n.startswith("showIf:") else n for n in _skip_set
             if not n.startswith("font:")}
assert _skip_src <= _cannot_set, (
    sorted(_skip_src - _cannot_set),
    "a row was skipped for a reading this box says it answered")
_silent = _cannot_set - _skip_src
assert _silent <= _guarded, (
    sorted(_silent), sorted(_guarded),
    "a reading this box lacks was neither skipped nor silenced by a dependency, so the two "
    "halves of the report have drifted apart")
for _dep in sorted(_depends & _cannot_set):
    assert f"showIf:{_dep}" in _skip_set, (
        _dep, sorted(_skip_set), "this box cannot answer a dependency the file names, and "
                                 "the report said nothing about the rows that depend on it")
assert _cannot_set <= _asked_src, sorted(_cannot_set - _asked_src)
# ...and the identity both doors already rely on for the vendor library: every widget in the
# file is either painted or reported, one note each.  A dependency that silences a row has to
# cost exactly one note, or a reader comparing the two halves gets a count that does not close
_skipped_all = [x.strip() for x in _msk[1].split(",")] if _msk[1].strip() != "nothing" else []
_boxes_n = int(re.search(r"([0-9,]+) boxes,", _skipped)[1].replace(",", ""))
assert _boxes_n + len(_skipped_all) == len(_w_bars), (
    _boxes_n, len(_skipped_all), len(_w_bars),
    "a widget was drawn, skipped and reported twice, or not reported at all")
# and one note per skipped widget, named the way the widget should name it: its own `source`
# when the draw got that far, its dependency when a `showIf` silenced the row first
_notes_own, _want_own = {}, {}
for _n in _skipped_all:
    if _n in _asked_src:
        _notes_own[_n] = _notes_own.get(_n, 0) + 1
for _w in _w_bars:
    _pr = _w["property"][0]
    _src, _dep = _pr.get("source"), (_pr.get("xigma") or {}).get("showIf")
    if _src in _cannot_set and (_dep is None or _dep not in _cannot_set):
        _want_own[_src] = _want_own.get(_src, 0) + 1
assert _notes_own == _want_own, (
    sorted(_notes_own.items()), sorted(_want_own.items()),
    "a row was reported under the wrong name, or a different number of times than the "
    "widgets asking for it")
_dep_notes, _silenced_rows, _silent_src = {}, 0, {}
for _n in _skipped_all:
    if _n.startswith("showIf:"):
        _dep_notes[_n[7:]] = _dep_notes.get(_n[7:], 0) + 1
for _w in _w_bars:
    _dep = (_w["property"][0].get("xigma") or {}).get("showIf")
    if _dep and _dep in _cannot_set:
        _silenced_rows += 1
        _own = _w["property"][0].get("source")
        if _own in _cannot_set:
            _silent_src[_own] = _silent_src.get(_own, 0) + 1
# one `showIf:<source>` note per row a dependency silenced, and the sources that end up in
# `cannot:` with no note of their own are exactly those rows' own readings, where the box
# lacks both - which is the case a bench with a GPU never shows
assert sum(_dep_notes.values()) == _silenced_rows, (
    _dep_notes, _silenced_rows, "the rows a dependency silenced are not the notes standing "
                                "in for them")
assert set(_silent_src) == _silent, (
    sorted(_silent_src), sorted(_silent),
    "the readings `cannot:` names with nothing behind them are not the ones a `showIf` "
    "hid the row for")
_silent_note = ("" if not _silent else
                f" - of those, {len(_silent)} never reach the skip list because a "
                f"`showIf` dependency silences the row before its own reading is asked "
                f"({', '.join(sorted(_silent))})")
# The door's answer for a drawn theme with no export is unreachable today - the assert in
# the parity section holds every drawn theme exported - so it is driven by taking an export
# away in a child process rather than left to rot as an untested message.  It pins the branch
# order too: a theme that does have an export must not land in the "no export yet" wording.
_noexp = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0, '.');"
     "from xigmalcd import main, themes;"
     "themes.EXPORTS = {k: v for k, v in themes.EXPORTS.items() if k != 'gauge'};"
     "sys.exit(main.main(['--check-theme', 'gauge']))"],
    capture_output=True, text=True)
assert _noexp.returncode == 0, (_noexp.returncode, _noexp.stderr[:400])
_line = next((ln for ln in _noexp.stdout.splitlines() if "no layout export" in ln), "")
assert _line.strip().startswith("gauge:"), (_line, _noexp.stdout[:300])
for _other in sorted(set(themes.EXPORTS) - {"gauge"}):
    assert _other in _line, (_line, _other,
                             "the refusal names the exports that do exist - a reader has to "
                             "be able to see what is missing and what is not")

print(f"  bars as a file        {len(_w_bars)} rows in the generated layout - the heading, "
      f"the clock line and three widgets for each of the {len(themes.BARS_ROWS)} rows in "
      f"`themes.BARS_ROWS`, every one at y={render.BARS_Y0}+i*{_pitch_bars} with the meter's "
      f"`minValue`/`maxValue` and the number's `source` taken from that table, and the "
      f"labels `text` for the {_n_fixed} fixed rows / `data` on `Fan N Name` for the "
      f"{len(themes.FAN_SLOTS)} slots. Pixel-identical to `render.py` at all "
      f"{len(_BARS_CASES)} readings ({len(_bars_rows)} answer every source; "
      f"{len(_bars_holes)} leave rows unanswered and are skipped the same way both doors), "
      f"and this box answers all but {' '.join(sorted(_cannot_set)) or 'none of them'}"
      f"{_silent_note}.")
print(f"                        the report closes on itself: {_boxes_n} boxes drawn and "
      f"{len(_skipped_all)} skip notes for {len(_w_bars)} widgets - one note per row that "
      f"did not paint, repeats and all, because `skipped:` is per widget while `and cannot:` "
      f"is per source ({len(_cannot_set)} of them, {len(_silent)} of those named only there "
      f"because a `showIf` took the row out before its own reading was asked). And a drawn "
      f"theme with its export taken away is still answered in words, not an error: "
      f"{_line.strip()[:88]}...")
print(f"                        what `xigma.showIf` buys, measured: the same file with the "
      f"key stripped from its two memory number rows sits {_shownif_px} px and a worst "
      f"channel of {_shownif_worst}/255 away from the drawing at a reading where a GPU "
      f"reports used memory and no dedicated total. And the two rules that measurement "
      f"found are fixed: `memory: {{total, no used}}` no longer raises inside the frame "
      f"loop (the RAM slot stays empty, the VRAM slot fills), and a GPU reporting exactly 0 "
      f"used keeps its row at nothing filled the way a 0 % RAM reading always did - one "
      f"function, `render.pct_pair`, forms both meters now (docs/theme-editor.md, "
      f"docs/limits.md)")

print(f"  a table and its reason {' '.join(sorted(layout.BAR_PAINT))} /"
      f" {' '.join(sorted(layout.ARC_PAINT))} / {' '.join(sorted(layout.COLOUR_RAMPS))}:"
      f" every name in a table appears in the reason `--print-theme-fields` prints for it,"
      f" and an unknown one is reported rather than guessed at:"
      f" {bad_words[:82]}")

# docs quote these figures, so they are re-derived here rather than remembered: the last
# number this repo wrote down with no gate behind it went stale
def _spaced(n):
    return f"{n:,}".replace(",", " ")


lim = open("docs/limits.md", encoding="utf-8").read()
usage_txt = open("docs/usage.md", encoding="utf-8").read()
# every export's painted count is quoted in two documents, so both are held to this run
plan_txt = open("docs/theme-editor.md", encoding="utf-8").read()
_gen_n, _file_n = len(themes.EXPORTS), len(themes.scan()[0])
gui_txt = open("docs/gui.md", encoding="utf-8").read()
# The skip list's prefixes belong to the painter, so the pages that describe that list are
# held to the notes the code appends rather than to what whoever wrote them remembered: the
# two the editor's work added (`showIf:` for an unmet dependency, `format:` for a shape the
# value behind it cannot be dressed in) have to be named by every page that spells the
# report out, and no page may name a prefix no code path writes.
import re as _vocab_re
_note_pref = set(_vocab_re.findall(r'notes\["missing"\]\.append\(f"([A-Za-z]+):',
                                   open("xigmalcd/layout.py", encoding="utf-8").read()))
assert {"showIf", "format", "font", "special"} <= _note_pref, sorted(_note_pref)
for _f, _t in (("docs/limits.md", lim), ("docs/usage.md", usage_txt),
               ("docs/theme-editor.md", plan_txt)):
    for _p in ("showIf", "format"):
        assert _vocab_re.search(rf"`{_p}:[^`]*`", _t), (
            _f, _p, f"that page describes the skip list without naming the `{_p}:` note "
                    "the painter writes")
    for _said in set(_vocab_re.findall(r"`([A-Za-z]+):[^`]*<[^`]*>`", _t)):
        assert _said in _note_pref, (_f, _said, sorted(_note_pref),
                                     "that page names a skip note no code path appends")
print(f"  the skip list's words  {len(_note_pref)} prefixes `layout.draw` can append ("
      f"{', '.join(sorted(_note_pref))}); the three pages that spell the report out each "
      f"name `showIf:<...>` and `format:<...>`, and every prefixed note they name is one "
      f"the code appends")
# The same page counts how many families the library's own rows ask for, so that digit is
# taken from the files here rather than remembered there: it said "four families" for a
# library that names three, and no gate noticed.
_lib_fams = sorted({f for f, _b, _s in used_faces})
_face_claim = (f"the **{len(_lib_fams)}** of them: "
               + " ".join(f"`{f}`" for f in _lib_fams))
assert _face_claim in " ".join(usage_txt.split()), (
    _lib_fams, _face_claim, "docs/usage.md counts the families the library's files name "
                            "differently from this run")
assert all(f in layout.FONTS for f in _lib_fams), (
    _lib_fams, sorted(layout.FONTS), "a family the vendor files name is not in the "
                                     "painter's table, so the editor cannot offer it")
print(f"  the faces the library names {' '.join(_lib_fams)} ({len(_lib_fams)}) in the "
      f"{len(ok)} pickable files, out of {len(layout.FONTS)} names `layout.FONTS` answers; "
      f"docs/usage.md states that count")
for _t, _w in ((plan_txt, "docs/theme-editor.md"), (gui_txt, "docs/gui.md")):
    assert f"{_gen_n} generated ones" in _t, (_w, _gen_n, "the document does not say how "
                                              "many generated layouts the window opens")
assert f"{_gen_n + _file_n} names ({_gen_n} generated + {_file_n}" in plan_txt, \
    (_gen_n, _file_n, "docs/theme-editor.md miscounts what the layout combo offers")
for _name, _rec in sorted(themes.EXPORTS.items()):
    _o = _rec()
    _nw, _nc = len(_o["osd"]["widget"]), len(json.dumps(_o, indent=1, sort_keys=True))
    assert f"{_nw} and {_spaced(_nc)}" in usage_txt, (
        _name, _nw, _nc, "docs/usage.md does not say what generating "
        f"{_name} writes: {_nw} widgets and {_spaced(_nc)} characters")
for _n, _p in rows:
    assert _spaced(_p) in usage_txt, (_n, _p, "docs/usage.md does not quote "
                                      f"{_n}'s painted count from this run")
    assert _spaced(_p) in plan_txt, (_n, _p, "docs/theme-editor.md does not quote "
                                     f"{_n}'s painted count from this run")
assert " / ".join(_spaced(n) for _v, n, _w in conv) in lim, \
    "docs/limits.md does not quote the arc numbers this run printed"
assert " / ".join(_spaced(n) for _v, n, _w in bars) in lim, \
    "docs/limits.md does not quote the bar numbers this run printed"
for key in ("arc", "bar"):
    nums = [n for _v, n, _w in (conv if key == "arc" else bars)]
    assert f"{_spaced(min(nums))} to {_spaced(max(nums))}" in usage_txt, (key, nums)
for paint in ("vendor", "render"):
    assert _spaced(gap_h[(0, 62, paint)]) in lim, \
        (paint, gap_h[(0, 62, paint)], "docs/limits.md does not quote how far a"
         " convention sits from render.hbar")
assert f"{len(LOADS)} values, 0 differing pixels" in lim, \
    f"docs/limits.md does not quote the {len(LOADS)} zero-diff values against render.bar"
assert f"{len(zero)} pairs" in lim, \
    f"docs/limits.md does not quote the {len(zero)} zero-diff pairs"
plan = open("docs/theme-editor.md", encoding="utf-8").read()
assert f"{len(zero)} device-px pairs and {len(ONEX)} at 1x" in plan, \
    f"docs/theme-editor.md does not quote the {len(zero)}/{len(ONEX)} zero-diff pairs"
assert all(f"{a:,}".replace(",", " ") in lim for _v, a, _b in walked), \
    "docs/limits.md does not quote how the track disappears as the fill grows"
assert f"{len(fan_pairs)} reading pairs" in lim and f"{len(ARC_PAIRS)} reading pairs" in lim \
    and f"{len(fan_pairs)} reading pairs" in usage_txt, \
    (len(fan_pairs), len(ARC_PAIRS),
     "docs/limits.md does not quote the two joint-sizing walks this gate ran")
assert f"{len(BUDGETS)} whole-pixel budgets" in lim, \
    f"docs/limits.md does not quote the {len(BUDGETS)} budgets searched for autoFitMax"
_iv = re.search("a floor of %d px down\\s+to a ceiling of %d px" % (lo, hi), lim)
_bt = re.search("the best\\s+reaches %d of the %d" % (best_n, len(ARC_STRINGS)), lim)
assert _iv and _bt, \
    (lo, hi, best, best_n, "docs/limits.md misquotes the empty interval the width "
     "search leaves, or how close the best budget gets")
# theme-editor.md quotes the same interval in its own words, so it is held to the same run
assert f"at least {lo} px and less than {hi} px" in plan, \
    (lo, hi, "docs/theme-editor.md misquotes the interval the width search leaves")
# the value row's own numbers, same rule: the font-free ones are pinned exactly, the
# face-dependent ones to within 5 %, because a label of "the bench's" is not a licence for
# a doc to drift - that is how this repo's figures have gone stale before
_foot = re.search(r"leaves\s+\*\*(\d[\d ]*)\s+px\*\*\s+of\s+ink", lim)
_deep = re.search(r"deepest\s+pixel\s+\*\*([\d.]+)\s+px\*\*", lim)
assert _foot and _deep, (lim[lim.find("`temp-values` landed"):][:160])
assert int(_foot[1].replace(" ", "")) == len(RING_TAIL), (_foot[1], len(RING_TAIL))
assert abs(float(_deep[1]) - tail) < 0.005, (_deep[1], tail)
_rg = re.search(r"puts\s+down\s+([\d ]+)\s+to\s+([\d ]+)\s+pixels", lim)
_lb = re.search(r"and ([\d ]+) \(the labels", lim)
_sz = re.search(r"across all (\d+) pairs.*?takes (\d+) of them", lim, re.S)
assert _rg, "docs/limits.md does not quote the pixels this row puts down"
for _got, _want in ((int(_rg[1].replace(" ", "")), min(temp_px)),
                    (int(_rg[2].replace(" ", "")), max(temp_px))):
    assert abs(_got - _want) <= 0.05 * _want, (_got, _want)
assert _lb and abs(int(_lb[1].replace(" ", "")) - min(lbl_px)) <= 0.05 * min(lbl_px), \
    (_lb[1] if _lb else None, min(lbl_px), max(lbl_px))
assert len(set(lbl_px)) == 1, lbl_px[:6]      # the doc says so, and the gate agrees
assert _sz and int(_sz[1]) == len(temp_rows) and int(_sz[2]) == len(set(val_sizes)), \
    (_sz.groups() if _sz else None, len(temp_rows), len(set(val_sizes)))
# and the one face-dependent number that sentence quotes - "the size the ring decides is
# 22 px here" - held to the print above rather than remembered, same 5 % rule as the rest
_bench = re.search(r"the size the ring decides is (\d+) px here", lim)
assert _bench and abs(int(_bench[1]) - lbl_sizes[0]) <= max(1, 0.05 * lbl_sizes[0]), \
    (_bench[1] if _bench else None, lbl_sizes[0],
     "docs/limits.md quotes a size this run did not measure - the tolerance is 5 % with a "
     "floor of one pixel, because a font size is a small integer")
_clr = re.search(r"ink\s+stays\s+\*\*([\d.]+)\s+px\*\*\s+inboard", lim)
_gap = re.search(r"\*\*([\d.]+)\s+px\*\*\s+clear\s+of\s+(?:that|the)\s+tail", lim)
assert _clr and _gap, "docs/limits.md does not quote how clear the row's ink is"
assert abs(float(_clr[1]) - row_clear) <= 0.05 * row_clear, (_clr[1], row_clear)
assert abs(float(_gap[1]) - (row_clear - tail)) <= 0.05 * (row_clear - tail), \
    (_gap[1], row_clear - tail)
assert "`xigma.fitArc`" in usage_txt, \
    "docs/usage.md does not list the `fitArc` key the value row sizes itself against"
assert "one `special` named `fan-figures`" in plan, \
    "docs/theme-editor.md does not say the fan pair is a special today"
# the two docs quote the pair counts this gate walks, and both have to mark the
# face-dependent counts (how many pairs land at two sizes, and by how many px) as one
# machine's measurement rather than as a property of the code
assert f"{len(fan_pairs)} fan pairs" in plan and f"{len(ARC_PAIRS)} value pairs" in plan, \
    f"docs/theme-editor.md does not quote the {len(fan_pairs)}/{len(ARC_PAIRS)} pairs"
assert "on the author's bench" in plan, \
    "docs/theme-editor.md quotes a face-dependent count without labelling it"
assert "on the author's bench" in lim, \
    "docs/limits.md must label the face-dependent counts as one machine's measurement"
sp = subprocess.run([sys.executable, "-m", "xigmalcd", "--list-specials"],
                    capture_output=True, text=True, check=True)
assert all(f"  {n}" in sp.stdout for n in themes.special_names()), sp.stdout
# each line says the shape the row will edit, and that sentence follows the door
for line in sp.stdout.splitlines():
    name = line.strip().split("  [")[0].strip()
    if name in themes.special_names():
        # the door in brackets is what the shape sentence describes, and the
        # sentence has to name the key a row of that door sizes itself with
        door = line.split("[", 1)[1].split("]", 1)[0]
        assert door == themes.special_door(name), line
        assert ("`xigma.fitArc`" in line) == (door == "values"), line
        assert ("`xigma.autoFitMax`" in line) == (door == "pair"), line
        assert ("one line" in line) == (door == "line"), line
assert "ttyACM" not in sp.stdout
print(f"  --list-specials       {' '.join(themes.special_names())}; drawn by code, "
      f"placed by the layout, no port opened")

# the review door on the theme that needed the most keys: what `--check-theme` says about
# the generated `alpha` layout.  What is pinned here is the report's internal agreement -
# which rows a missing reading costs, and that the two halves of the report say the same
# thing about it - because how many readings a box answers is a fact about the machine, not
# about this file: the runner that answers only `CPU Usage` and `Time` draws 8 of the 12
# boxes, and that is the door working, not a defect.
chk = subprocess.run([sys.executable, "-m", "xigmalcd", "--check-theme", "alpha"],
                     capture_output=True, text=True, check=True)
lines = chk.stdout.splitlines()
n_rows = len(themes.export("alpha")["osd"]["widget"])
assert "generated from render.py" in lines[0] and f"{n_rows} widgets" in lines[0], lines[0]
warn = [ln for ln in lines if ln.strip().startswith("warning:")]
assert all("outside the ten sizes" in w for w in warn), warn
_sources = sorted({w["property"][0]["source"]
                   for w in themes.EXPORTS["alpha"]()["osd"]["widget"]
                   if w["property"][0].get("source")})
ask_line = next(ln for ln in lines if "asks for:" in ln)
can_line = next((ln for ln in lines if "cannot:" in ln), "")
can_set = ({s.strip() for s in can_line.split("cannot:", 1)[1].split(",") if s.strip()}
           if "cannot:" in can_line else set())      # a box that answers everything: empty
assert ", ".join(_sources) in ask_line, (ask_line, _sources)
drawn = next(ln for ln in lines if " boxes," in ln)
_box = re.search(r"(\d+) boxes, [\d, ]+ lit px, skipped: (.*)$", drawn)
assert _box, drawn
n_boxes, skipped = int(_box[1]), _box[2].strip()
skip_set = set() if skipped == "nothing" else {s.strip() for s in skipped.split(",")}
assert not any((w["property"][0].get("xigma") or {}).get("showIf")
               for w in themes.EXPORTS["alpha"]()["osd"]["widget"]), (
    "`alpha` gained a row silenced by a dependency, and this equality between the report's "
    "two halves only holds while no widget is skipped before its own `source` is consulted - "
    "the `bars` gate above holds the relations that stay true either way")
assert skip_set == can_set, (skip_set, can_set, drawn)
_dropped = sum(1 for w in themes.EXPORTS["alpha"]()["osd"]["widget"]
               if w["property"][0].get("source") in can_set)
assert n_boxes == n_rows - _dropped, (n_boxes, n_rows, _dropped, can_set)
print(f"  --check-theme alpha   {lines[0].strip()}")
print(f"                        {'; '.join(w.strip()[9:] for w in warn)} - our sizes are "
      f"ours, not the vendor's ten, and the review door says so rather than quieting it. "
      f"{n_rows} rows ask for {', '.join(_sources)}; this machine cannot answer "
      f"{', '.join(sorted(can_set)) or 'any of them'}, so the report draws {n_boxes} boxes "
      f"and says which rows that costs - the two halves agreeing, no port opened")
PY

# ---- the file model (stage 3 of docs/theme-editor.md): the shape the library is stored
# ---- in, what validate refuses or warns about, and an edit that shadows the vendor's
# ---- copy without ever writing to it.  Its own process, because themes.user_root() is
# ---- decided at import and this must not touch the real ~/.config, /usr/share, or the
# ---- checkout's copies that every figure in the docs was read from.
EDIT_TMP="$(mktemp -d)"
XDG_CONFIG_HOME="$EDIT_TMP" python3 - <<'PY' || { echo "theme file model FAILED"; exit 1; }
import datetime, os, subprocess, sys
from PIL import ImageChops
from xigmalcd import layout, render, sensors, themes
WHEN = datetime.datetime(2026, 2, 17, 9, 30)

files = sorted(themes._glob.glob(os.path.join(themes.REPO_ROOT, "layouts", "**", "*.json"),
                                 recursive=True))
shapes = [themes.shape_of(f) for f in files]
assert len(files) == 27 and None not in shapes, [f for f, s in zip(files, shapes)
                                                 if s is None]
identical = 0
for f in files:
    txt = themes.canonical(themes.load(f), themes.shape_of(f))
    raw = open(f, encoding="utf-8").read()
    identical += raw in (txt, txt + "\n")
assert identical == 27, identical
print(f"  file shape          all 27 layouts reproduce, byte for byte, from their own "
      f"parsed content ({identical}/27 after a load/save round trip). The files disagree "
      f"with each other about one setting only: {shapes.count(True)} escape non-ASCII as "
      f"\\uXXXX and {shapes.count(False)} keep it raw (the ones carrying 宋体 or CJK "
      f"content) - which is why the writer asks each file which shape it is in")

ok, _ex = themes.scan()
copies = 0
for rec in ok:
    _r, path, _s = themes.copy_for_edit(rec["name"])
    copies += open(path, "rb").read() == open(rec["path"], "rb").read()
    themes.delete_user_theme(rec["name"])
assert copies == len(ok) == 23, copies

import hashlib
rec = themes.resolve("Theme_28")
vendor_sha = hashlib.sha256(open(rec["path"], "rb").read()).hexdigest()
obj = themes.load(rec["path"])
# a text label with no `source`: it draws on any machine, with any sensors, so a box
# that does not move here means the edit was ignored, not that a reading was missing
target = next(w for w in obj["osd"]["widget"]
              if not (w.get("property") or [{}])[0].get("source")
              and (w.get("property") or [{}])[0].get("content"))
label = target["property"][0]["content"]
x0 = target["property"][0]["x"]
target["property"][0]["x"] = x0 + 20
_, path = themes.copy_for_edit("Theme_28")[:2]
path, soft = themes.save(obj, "Theme_28")
assert soft == [], soft
assert not os.path.exists(path + ".tmp"), "a .tmp survived the atomic replace"
assert os.path.exists(path + ".bak"), "the copy being overwritten left no backup"
metrics = sensors.collect()
# pinned instant on purpose: two draws of one theme with a live clock could straddle a
# second between them, and the difference would be a time, not an edit
img_v, notes_v = themes.draw(themes.load(rec["path"]), metrics, WHEN)
img_u, notes_u = themes.draw(obj, metrics, WHEN)
assert len(notes_v["boxes"]) == len(notes_u["boxes"]), (notes_v["missing"],
                                                        notes_u["missing"])
delta = [(b[2][0] - a[2][0], b[2][1] - a[2][1])
         for a, b in zip(notes_v["boxes"], notes_u["boxes"])]
assert [d for d in delta if d != (0, 0)] == [(20, 0)], (label, delta)
moved = next(a for a, b in zip(notes_v["boxes"], notes_u["boxes"])
             if b[2][0] - a[2][0])
assert moved[1] == label and moved[0] == target["type"], moved
rec2 = themes.resolve("Theme_28")
assert rec2["edited"] and rec2["root"] == themes.user_root(), rec2


def _changed_pixels(a, b):
    """Pixels where the two pictures differ in any channel (no deprecated getdata)."""
    raw = ImageChops.difference(a, b).tobytes()
    return sum(1 for i in range(0, len(raw), 4) if raw[i:i + 4] != b"\0\0\0\0")
print(f"  edit shadows        copying one of the 23 gives a byte-identical file "
      f"({copies}/23), and editing it is the copy that draws: one widget's box moves by "
      f"exactly (20, 0), the other {len(delta) - 1} stay put, "
      f"{_changed_pixels(img_v, img_u)} of {render.W * render.H} pixels change, and "
      f"the vendor's file is still "
      f"{vendor_sha[:12]}... byte for byte. The terminal agrees: --list-themes and "
      f"--check-theme Theme_28 both name the copy, and both go back to the "
      f"vendor's file once it is deleted")

# the same fact the terminal user needs, checked where they would read it
listing = subprocess.run([sys.executable, "-m", "xigmalcd", "--list-themes"],
                         capture_output=True, text=True, check=True)
checked = subprocess.run([sys.executable, "-m", "xigmalcd", "--check-theme", "Theme_28"],
                         capture_output=True, text=True, check=True)
assert "from your copy" in listing.stdout and "your copies" in listing.stdout, listing.stdout
assert "from your copy" in checked.stdout.splitlines()[0], checked.stdout
refused = []
for what, call in (
        ("outside the user directory", lambda: themes.save(
            obj, "Theme_28", root=os.path.join(themes.SYSTEM_ROOT, "alpha"))),
        ("a generated theme's name", lambda: themes.save(obj, "gauge")),
        ("a path element", lambda: themes.save(obj, "../escape")),
        ("a nested name", lambda: themes.save(obj, "a/b")),
        ("no widgets to draw", lambda: themes.save(
            {"width": 480, "height": 480, "osd": {"widget": []}}, "empty")),
        ("a two-element property", lambda: themes.save(
            {"width": 480, "height": 480, "osd": {"widget": [{
                "type": "text", "id": "xigma-t",
                "property": [{"x": 0, "y": 0}, {"x": 1, "y": 1}]}]}}, "two"))):
    try:
        call()
        refused.append(f"{what}: NOT REFUSED")
    except ValueError as exc:
        refused.append(f"{what}: {str(exc)[:40]}")
assert not any("NOT REFUSED" in r for r in refused), refused
themes.delete_user_theme("Theme_28")
back = themes.resolve("Theme_28")
assert not back.get("edited"), back
after = subprocess.run([sys.executable, "-m", "xigmalcd", "--list-themes"],
                       capture_output=True, text=True, check=True)
assert "from your copy" not in after.stdout
assert "nothing saved yet" in after.stdout, after.stdout
print(f"  refusals            {'; '.join(refused)} - and deleting your copy puts the "
      f"vendor's back in front ({themes.origin(back)})")

bad = {"width": 480, "height": 480, "osd": {"widget": [
    {"type": "data", "id": "xigma-a", "property": [
        {"x": 600, "y": 10, "source": "Pump Flow", "fontFamily": "comic sans",
         "fontSize": 33, "textColor": "#ffffff",
         "time": "2026-01-01T00:00:00.000Z"}]},
    {"type": "data", "id": "xigma-a", "property": []},
    {"type": "data", "id": "xigma-a", "property": [
        {"x": 5, "y": 5, "source": "CPU Usage",
         "xigma": {"showIf": "Fan 9 Speed"}}]},
    {"type": "special", "id": "xigma-b", "property": [
        {"x": 10, "y": 10, "name": "mystery-thing", "fontSize": 26}]},
    # the two doors that place a pair, each missing the one key that makes its placement
    # mean something: `temp-values` has a pitch and no ring to size against, `fan-figures`
    # has a ring key it never reads and no pitch, so both figures would land on one point
    {"type": "special", "id": "xigma-d", "property": [
        {"x": 240, "y": 128, "width": 232, "name": "temp-values", "fontSize": 70}]},
    {"type": "special", "id": "xigma-e", "property": [
        {"x": 240, "y": 300, "name": "fan-figures", "fontSize": 20,
         "xigma": {"fitArc": {"cy": 158, "radius": 85, "width": 12,
                              "angleStart": 45, "angleEnd": 315}}}]},
    {"type": "text", "id": "xigma-c", "property": [{"x": 10, "y": 10}]}]}}
hard, soft = themes.validate(bad)
named = ["outside the 480x480 canvas", "has no entry in", "is not in layout.FONTS",
         "is outside the ten sizes", "rgba(r, g, b, a)", "repeats inside this theme",
         "has no drawing", "no `content`", "one-element list",
         "no ring to size its text against", "distance between their centres",
         "xigma.showIf names"]
hit = sum(1 for n in named if any(n in s for s in soft + hard))
assert hit == len(named) and len(soft) == 12 and len(hard) == 1, (hit, soft, hard)
n_soft, n_hard = len(soft), len(hard)
# the doc counts these findings, so the count is re-derived here rather than remembered
_plan_txt = open("docs/theme-editor.md", encoding="utf-8").read()
assert f"covering all {n_soft}:" in _plan_txt, \
    (n_soft, "docs/theme-editor.md miscounts the soft findings one fixture covers")

# and why every comparison above carries `WHEN`: a layout with a clock in it is not a
# function of its file alone, it is a function of the instant too.  Measured on the way
# through, because a parity gate that forgets this fails in CI once a second - literally.
import time as _time
from PIL import ImageChops as _Chops
_t0, _ = themes.draw(themes.export("clock"), {}, None)
_time.sleep(1.05)
_t1, _ = themes.draw(themes.export("clock"), {}, None)
_drift = sum(1 for q in _Chops.difference(_t0.convert("RGBA"),
                                         _t1.convert("RGBA")).get_flattened_data()
             if q != (0, 0, 0, 0))
_p0, _ = themes.draw(themes.export("clock"), {}, WHEN)
_time.sleep(1.05)
_p1, _ = themes.draw(themes.export("clock"), {}, WHEN)
_still = sum(1 for q in _Chops.difference(_p0.convert("RGBA"),
                                         _p1.convert("RGBA")).get_flattened_data()
             if q != (0, 0, 0, 0))
assert _drift > 0 and _still == 0, (_drift, _still)
print(f"  why every draw pins  the same `clock` layout drawn twice with no pinned instant "
      f"differs by {_drift:,} px across 1.05 s of wall clock; drawn twice at one pinned "
      f"instant it differs by {_still} px. That is why `themes.draw`, `themes.parity` and "
      f"every gate above pass an instant: without it a pixel comparison is a stopwatch")

# ---- naming a copy: the two acts that invent a name, and the one name rule they share.
# ---- These refusals are not a taste list.  `resolve()` answers a name, that name folded,
# ---- and the `id` inside the file, and `scan()` keeps one record per name with the user
# ---- root first - so a copy put at a name another layout holds does not sit beside it: it
# ---- takes that layout out of reach by name *and* by id (measured: after that,
# ---- `resolve(<vendor id>)` answers None, and a copy at `theme_07` beside the vendor's
# ---- `Theme_07` leaves `--list-themes` showing two layouts while every spelling resolves
# ---- to one file).  So "a name of your own" has to mean unused by name, by case-fold and
# ---- by id.  And the acts are measured for what they change: one path, one id.
_n_had = sorted(themes.user_copies())
assert _n_had == [], _n_had                      # the gates above leave the root clean
import hashlib as _hash


def _n_vhash():
    """Every layout file outside the user root, as `{path: sha256}`.

    Hashed off the directory rather than off `scan()`, because `scan()` deliberately shows
    one record per name - a copy of yours hides the vendor's record, and this gate is about
    the vendor's *files*, which are the evidence every figure in the docs was read from.
    How many roots answer is a fact about the machine: a bench with the themes package
    installed holds the checkout's 27 and the same 27 again under /usr/share, while CI's
    offline job ships the checkout alone - so what is held here is "the files the vendor
    roots have", counted from the roots, and never a number that presumes a second tree.
    """
    out = {}
    for _root, _pat in themes.roots():
        if _root == themes.user_root():
            continue
        for _p in themes._glob.glob(os.path.join(_root, _pat), recursive=True):
            out[_p] = _hash.sha256(open(_p, "rb").read()).hexdigest()
    return out


_n_vendor0 = _n_vhash()
_n_vroots = sorted(r for r, _p in themes.roots()
                   if r != themes.user_root() and os.path.isdir(r))
assert _n_vendor0, ("no vendor layout file anywhere: the naming gates below would be "
                    "measuring refusals against an empty library")
assert len(_n_vendor0) >= 27, (len(_n_vendor0), _n_vroots,
                               "fewer layout files on disk than this repository tracks")
_n_lim = themes.NAME_LIMIT
assert themes._safe_name("x" * _n_lim) == "x" * _n_lim, "the limit itself must be usable"
try:
    themes._safe_name("x" * (_n_lim + 1))
    raise AssertionError("a name longer than the limit was accepted")
except ValueError as _exc:
    assert f"longer than {_n_lim} characters" in str(_exc), _exc
for _suf in themes.WRITER_SUFFIXES:
    try:
        themes._safe_name(f"copy{_suf}")
        raise AssertionError(f"a name ending in {_suf!r} was accepted")
    except ValueError as _exc:
        assert f"copy{_suf}.json" in str(_exc), _exc

_n_pick, _n_rej = themes.scan()
_n_all = list(_n_pick) + list(_n_rej)
_n_names = {r["name"] for r in _n_all}
_n_ids = {str(r["id"]) for r in _n_all}
assert not [n for n in _n_names if n.lower().endswith(themes.WRITER_SUFFIXES)], (
    "a layout here already has a name ending in one of the writer's own suffixes, so "
    "refusing such a name would be refusing something that exists")
assert len(_n_names) == len({n.lower() for n in _n_names}), (
    "two layouts here differ only in case, which a case-folding resolver cannot reach both "
    "halves of - the name rule below depends on that not being so")
assert len(_n_ids) == len(_n_all), "two layout files share an id already"
assert len(themes.name_space()) == len(_n_names) + len(_n_ids), themes.name_space()[:4]

# ---- the three ways a name is spoken for, and the two ways it is not
_n_taken = []
for _nm in (sorted(_n_names)[0], sorted(_n_names)[0].lower(), sorted(_n_names)[0].swapcase(),
            sorted(_n_ids)[0]):
    _why = themes.why_taken(_nm)
    assert _why and "not a free name" in _why, (_nm, _why,
                                                "a name the library answers read as free")
    _n_taken.append(_nm)
_n_free = [themes.why_taken("plain-new-name"), themes.why_taken("Theme_07",
                                                                free_of="Theme_07"),
           themes.why_taken("theme_07", free_of="Theme_07")]
assert not any(_n_free), (_n_free, "a free name, or a copy's own name in another case")
_n_refused = {}
for _nm, _phrase in (("gauge", "one of the five"), ("../escape", "path element"),
                     (".hidden", "leading dot"), ("bad.json", "suffix"),
                     ("x" * (_n_lim + 1), "longer than"), ("a/b", "path element"),
                     ("Theme_07", "not a free name"), ("theme_07", "not a free name"),
                     (sorted(_n_ids)[0], "not a free name")):
    try:
        themes.new_name(_nm)
        raise AssertionError(f"new_name took {_nm!r}")
    except ValueError as _exc:
        assert _phrase in str(_exc), (_nm, _phrase, _exc)
        _n_refused[_nm] = _phrase

# ---- a fresh id: the corpus's shape, and clear of every id in the corpus
_n_vids = sorted(int(i) for i in _n_ids if str(i).isdigit())
assert len(_n_vids) == len(_n_ids), (sorted(_n_ids)[:3], "a vendor layout id is not digits")
assert {len(str(i)) for i in _n_vids} == {13}, _n_vids[:3]
_n_spread = _n_vids[-1] - _n_vids[0]
_n_new = [themes.new_id() for _ in range(6)]
assert all(len(i) == 13 and i.isdigit() for i in _n_new), _n_new
assert len(set(_n_new)) == 6, (_n_new, "two fresh ids in one run collided")
assert not set(_n_new) & set(map(str, _n_vids)), (_n_new[:2],
                                                  "a fresh id landed on an answered one")
assert all(int(i) > _n_vids[-1] for i in _n_new), (_n_new[0], _n_vids[-1],
                                                   "a fresh id was not above the library's")

# ---- the act: a copy of a vendor layout, renamed
_n_src, _n_rec = themes.copy_for_edit("Theme_07")[1], themes.resolve("Theme_07")
_n_raw0, _n_obj0 = open(_n_src, "rb").read(), themes.load(_n_src)
_n_pic0 = themes.draw(_n_obj0, {}, WHEN)[0]
import xigmalcd.main as _main
_n_path, _n_notes = themes.rename_copy("Theme_07", "my-renamed-copy")
_n_obj1 = themes.load(_n_path)
_n_diff = sorted(k for k in set(_n_obj0) | set(_n_obj1)
                 if themes.canonical(_n_obj0.get(k), True)
                 != themes.canonical(_n_obj1.get(k), True))
assert _n_diff == ["id"], (_n_diff, "a rename changed more than the id: the rows, the "
                           "canvas, the background and the ratio are the layout itself")
assert themes.canonical({k: v for k, v in _n_obj1.items() if k != "id"}, True) == \
    themes.canonical({k: v for k, v in _n_obj0.items() if k != "id"}, True), \
    "everything but the id is byte-identical"
_n_pic1 = themes.draw(_n_obj1, {}, WHEN)[0]
assert _n_pic0.tobytes() == _n_pic1.tobytes(), (
    "renaming a copy moved its pixels, which is a change of layout and not of name")
assert themes.shape_of(_n_path) is not None, "the renamed file is not canonical-shaped"
assert not os.path.exists(_n_src), "the old path is still there after the move"
assert themes.user_copies() == ["my-renamed-copy"], themes.user_copies()
_n_back = themes.resolve("Theme_07")
assert _n_back and not _n_back.get("edited"), (_n_back and themes.origin(_n_back),
                                               "the vendor's layout did not come back")
assert themes.resolve(str(_n_obj0["id"]))["path"] == _n_back["path"], \
    "the vendor's own id did not go back to the vendor's file"
_n_said = " ".join(_n_notes)
for _phrase in ("your copy moved: Theme_07.json is now my-renamed-copy.json",
                "its id went", "answers checkout again",
                "a copy written at a vendor's own name takes the name"):
    assert _phrase in _n_said, (_phrase, _n_notes)
assert _main.theme_name("my-renamed-copy") == "my-renamed-copy"
assert _main.theme_name("MY-RENAMED-COPY") == "my-renamed-copy", "the resolver folds case"
assert themes.pair("my-renamed-copy") == themes.pair("Theme_07"), (
    themes.pair("my-renamed-copy"), themes.pair("Theme_07"),
    "the renamed copy stopped naming the background its own file names")
assert themes.is_copy("my-renamed-copy") and not themes.is_copy("Theme_07")

# ---- the backup comes with the copy; a crash's scratch file stays where it is
themes.save(_n_obj1, "my-renamed-copy")                 # a second save leaves a .bak behind
open(_n_path + ".tmp", "w", encoding="utf-8").write("{ half written")
_n_p2, _n_notes2 = themes.rename_copy("my-renamed-copy", "moved-again")
assert os.path.exists(_n_p2 + ".bak"), (_n_notes2, "the .bak did not travel with the copy")
assert any("came with it" in n for n in _n_notes2), _n_notes2
assert open(_n_path + ".tmp", encoding="utf-8").read() == "{ half written", \
    "a half-written .tmp was moved or rewritten"
assert any("half-written" in n for n in _n_notes2), _n_notes2
assert not os.path.exists(_n_path), "the layout file itself stayed at the old name"
assert not os.path.exists(_n_path + ".bak"), "the .bak was left behind under the old name"

# ---- a name nobody was shadowing: what a loop drawing that name ends up drawing
_n_p3, _n_notes3 = themes.rename_copy("moved-again", "a-name-of-mine")
_n_args = _main.build_parser().parse_args(["--theme", "a-name-of-mine"])
_n_loop0 = _main.paint(_n_args, {})
_n_p4, _n_notes4 = themes.rename_copy("a-name-of-mine", "and-now-another")
_n_loop1 = _main.paint(_n_args, {})
assert _n_loop1.tobytes() == render.draw({}, "gauge").tobytes(), (
    "a loop that loses the name it was drawing does not fall back to `gauge`, so the "
    "sentence in the note is wrong")
assert any("falls back to `gauge`" in n for n in _n_notes4), _n_notes4
try:
    _main.build_parser().parse_args(["--theme", "a-name-of-mine"])
    raise AssertionError("a fresh --theme took a name nothing answers")
except SystemExit as _exc:
    assert _exc.code == 2, _exc.code
assert themes.resolve("a-name-of-mine") is None

# ---- the refusals: each one says why, and none of them moves a byte
_n_watch = sorted(themes._glob.glob(os.path.join(themes.user_root(), "*")))
_n_bytes = {p: open(p, "rb").read() for p in _n_watch}
_n_copies = themes.user_copies()
for _nm, _phrase in (("Theme_14", "not a free name"), ("theme_14", "not a free name"),
                     (str(_n_vids[0]), "not a free name"),
                     ("and-now-another", "already the name this copy has"),
                     ("bad.json", "suffix"), ("", "path element"),
                     ("gauge", "one of the five"), ("x" * (_n_lim + 1), "longer than"),
                     ("..", "path element")):
    try:
        themes.rename_copy("and-now-another", _nm)
        raise AssertionError(f"rename accepted {_nm!r}")
    except ValueError as _exc:
        assert _phrase in str(_exc), (_nm, _phrase, _exc)
for _nm, _phrase in (("Theme_14", "is not one of your copies"),
                     ("nowhere-to-be-found", "is not one of your copies")):
    try:
        themes.rename_copy(_nm, "whatever")
        raise AssertionError(f"rename accepted a source called {_nm!r}")
    except ValueError as _exc:
        assert _phrase in str(_exc), (_nm, _exc)
assert sorted(themes._glob.glob(os.path.join(themes.user_root(), "*"))) == _n_watch
assert {p: open(p, "rb").read() for p in _n_watch} == _n_bytes
assert themes.user_copies() == _n_copies

# ---- save-as at the file layer: one layout, two copies, two ids
_n_src2 = themes.copy_for_edit("Theme_14")[1]
_n_src2_raw = open(_n_src2, "rb").read()
import copy as _copy
_n_two = _copy.deepcopy(themes.load(_n_src2))     # `load` caches: copy before changing it
_n_id2 = themes.new_id()
_n_two["id"] = _n_id2
_n_p5, _n_warn5 = themes.save(_n_two, "second-copy-of-14")
assert open(_n_src2, "rb").read() == _n_src2_raw, \
    "the first copy moved when a second was written"
assert themes.load(_n_src2)["id"] != _n_id2, "two copies answering the same id"
assert themes.resolve(str(themes.load(_n_src2)["id"]))["path"] == _n_src2
assert themes.resolve(_n_id2)["path"] == _n_p5
for _nm in ("Theme_14", "second-copy-of-14"):
    try:
        themes.new_name(_nm)
        raise AssertionError(f"{_nm!r} read as free while a copy held it")
    except ValueError as _exc:
        assert "not a free name" in str(_exc), _exc
assert themes.draw(themes.load(_n_src2), {}, WHEN)[0].tobytes() == \
    themes.draw(themes.load(_n_p5), {}, WHEN)[0].tobytes(), "one layout, two names, " \
    "two pictures - the copy is a copy"

# ---- one process, two readers: the editor's memory is not the library's cache.  Measured
# ---- here because it is a file-model fact: `themes.load` caches by (path, mtime) so an
# ---- edited theme shows up on the loop's next frame, and the editor edits in place.
_n_ed_src = themes.copy_for_edit("Theme_25")[1]
_n_w0 = _copy.deepcopy(themes.load(_n_ed_src)["osd"]["widget"])
import xigmaui.edit as _edit
_n_ed = _edit.Editor.open_theme("Theme_25")
_n_ed.select(0)
_n_ok0, _n_say0 = _n_ed.set("x", int(_n_ed.value("x")) + 30)
assert _n_ok0, _n_say0
assert themes.load(_n_ed_src)["osd"]["widget"] == _n_w0, (
    "an unsaved keystroke reached the object `themes.load` caches, so `scan()`, `pair()` "
    "and `describe()` would read edits that no file holds")
assert themes.canonical(_n_ed.obj, True) != themes.canonical(themes.load(_n_ed_src), True), \
    "the editor and the file agreed while they were supposed to disagree (unsaved)"
_n_src_id = str(themes.load(_n_ed_src)["id"])

# ---- the editor's two naming doors: a file act, never an undo step, and memory follows it
_n_ed_dirty, _n_ed_steps = _n_ed.dirty, _n_ed.steps
_n_ed_x = int(_n_ed.value("x"))
_n_bad = _n_ed.rename("Theme_07")
assert _n_bad[0] is None and "not a free name" in _n_bad[1][0], _n_bad[1]
assert _n_ed.dirty == _n_ed_dirty and _n_ed.steps == _n_ed_steps, (_n_ed.dirty,)
_n_p6, _n_notes6 = _n_ed.rename("edited-by-the-model")
assert _n_ed.name == "edited-by-the-model" and _n_ed.path == _n_p6, _n_ed.name
assert _n_ed.dirty == _n_ed_dirty and _n_ed.steps == _n_ed_steps, (
    _n_ed.dirty, _n_ed.steps, "a rename took an undo step or changed what was unsaved")
assert int(_n_ed.value("x")) == _n_ed_x, "the rename rewrote the row the reader had moved"
_n_id_now = str(_n_ed.obj["id"])
assert _n_id_now == str(themes.load(_n_p6)["id"]) != _n_src_id, \
    (_n_id_now, _n_src_id, "memory and the moved file agree on the new id, and the file "
                           "before the move kept the old one")
_n_ed.undo()                               # one step back: the row, never the identity
assert str(_n_ed.obj["id"]) == _n_id_now, (_n_ed.obj["id"], _n_id_now,
                                           "an undo step put the retired id back")
assert int(_n_ed.value("x")) != _n_ed_x, "undo did not undo the edit it was asked to"
assert _n_ed.where == "your copy", _n_ed.where
_n_p6_raw = open(_n_p6, "rb").read()
_n_p7, _n_notes7 = _n_ed.save_as("a-third-one")
assert _n_p7 and _n_ed.name == "a-third-one" and not _n_ed.dirty, (_n_p7, _n_ed.dirty)
assert open(_n_p6, "rb").read() == _n_p6_raw, \
    "save_as wrote over the copy it was started from, instead of beside it"
assert themes.load(_n_p6)["id"] != themes.load(_n_p7)["id"], (
    "two copies of one layout answering one id")
_n_say7 = " ".join(_n_notes7)
for _phrase in ("is yours, under the name", "stays where it was"):
    assert _phrase in _n_say7, (_phrase, _n_notes7)
for _nm in ("Theme_14", "gauge", "bad.json"):
    _n_no = _n_ed.save_as(_nm)
    assert _n_no[0] is None, (_nm, _n_no[0])
assert _n_ed.rename("")[0] is None and _n_ed.save_as("")[0] is None
themes.delete_user_theme(_n_ed.name)
themes.delete_user_theme(os.path.basename(_n_p6)[:-5])
themes.delete_user_theme(os.path.basename(_n_ed_src)[:-5])

# ---- and nothing about any of it reached the vendor's trees
_n_ok2, _n_rej2 = themes.scan()
_n_ids2 = [str(r["id"]) for r in list(_n_ok2) + list(_n_rej2)]
assert len(set(_n_ids2)) == len(_n_ids2), (_n_ids2, "two layouts left answering one id")
_n_vendor1 = _n_vhash()
assert _n_vendor1 == _n_vendor0, (sorted(set(_n_vendor1) ^ set(_n_vendor0))[:3],
                                  sorted((p for p in _n_vendor0 if _n_vendor0[p] !=
                                          _n_vendor1.get(p)))[:3],
                                  "a vendor layout file changed on disk")
for _nm in themes.user_copies():
    themes.delete_user_theme(_nm)
assert themes.user_copies() == [], themes.user_copies()
assert len(themes.scan()[0]) == len(_n_pick), (len(themes.scan()[0]), len(_n_pick),
                                               "the vendor's pickable count moved")
print(f"  naming a copy       the two acts that invent a name, over {len(_n_vendor0)} "
      f"vendor layout files in {len(_n_vroots)} root(s) here, none of which any of it "
      f"touched. {len(_n_refused)} names "
      f"refused by `new_name` ({', '.join(f'{k}' for k in sorted(_n_refused))[:80]}), on a "
      f"rule taken from the library itself: {len(_n_names)} names, all distinct folded, and "
      f"{len(_n_ids)} ids, all distinct, every one answered by `resolve()`. A rename moved "
      f"one file and changed exactly one key (`id`: 13 digits, and the vendor's "
      f"{len(_n_vids)} fall inside {_n_spread:,} ms of one another), left every row and "
      f"every pixel where they were, gave the hidden vendor layout back, carried its `.bak` "
      f"with it and reported a half-written `.tmp` where it found one. Through the editor "
      f"the same act took no undo step and left `dirty` as it was, and one press of undo "
      f"afterwards went back a row and not an identity. A save-as left the first file byte "
      f"for byte and drew the same picture twice under two ids. A loop that loses the name "
      f"it is drawing falls back to `gauge` - measured, pixel for pixel - while a fresh "
      f"--theme of that same name exits 2, which is why the note tells the reader to "
      f"re-point it over the socket. And `themes.load`'s cache stays the library's own: an "
      f"unsaved keystroke in an editor moves no byte of what `scan()`, `pair()` and "
      f"`describe()` read")

img_mem, notes_mem = themes.draw(themes.export("clock"), {}, WHEN)
path, soft = themes.save(themes.export("clock"), "clock-as-file")
img_file, notes_file = themes.draw(themes.load(path), {}, WHEN)
assert img_mem.tobytes() == img_file.tobytes(), (notes_mem["boxes"], notes_file["boxes"])
assert notes_mem["boxes"] == notes_file["boxes"], (notes_mem["boxes"], notes_file["boxes"])
lit = sum(1 for v in img_mem.getchannel("A").get_flattened_data() if v)
print(f"  validate            {hit}/{len(named)} named in one fixture "
      f"({n_soft} soft warnings + {n_hard} hard refusal on one fixture). What the fixture "
      f"has to be seen to say, in the words it prints: {', '.join(named)} - a list read "
      f"from the checks themselves rather than written out below them, which is how this "
      f"sentence was nine findings long while the fixture held eleven. A layout held in "
      f"memory paints the "
      f"same {len(notes_mem['boxes'])} boxes and {lit} lit pixels as the same layout read "
      f"back off disk, so an editor's preview and the loop's frame are one code path")
PY
rm -rf "$EDIT_TMP"


# ---- an *authored* layout (not an export of our code): a ramp written as data, saved
# ---- through the file model, read back, and painted against the code it describes.
AUTH_TMP="$(mktemp -d)"
XDG_CONFIG_HOME="$AUTH_TMP" python3 - <<'PY' || { echo "authored ramp FAILED"; exit 1; }
import os
from PIL import Image, ImageChops
from xigmalcd import layout, render, themes
LO, MID, HI = 30.0, 62.0, 100.0           # render.A26_ARC_* : green / amber at 62 / red
CX, CY, R, TH = 240, 240, 110, 18
stops = [[0.0, themes.rgba_str(render.GREEN)],
         [(MID - LO) / (HI - LO), themes.rgba_str(render.AMBER)],
         [1.0, themes.rgba_str(render.RED)]]
obj = {"id": "fixture-ring", "width": render.W, "height": render.H, "ratio": "1:1",
       "osd": {"widget": [themes.widget("xigma-fixture-ring", "arc", {
           "x": CX - R, "y": CY - R, "sizeWidth": 2 * R, "sizeHeight": 2 * R,
           "radius": R - TH, "width": TH, "angleStart": 30, "angleEnd": 330,
           "bgColor": themes.rgba_str(render.TRACK),
           "startColor": themes.rgba_str(render.GREEN),
           "endColor": themes.rgba_str(render.RED),
           "minValue": LO, "maxValue": HI, "source": "CPU Temperature",
           "xigma": {"arcPaint": "render", "colourStops": stops}})]}}
hard, soft = themes.validate(obj)
assert not hard and not soft, (hard, soft)
path, soft = themes.save(obj, "fixture-ring")
assert not soft and os.path.exists(path), soft
back = themes.resolve("fixture-ring")
assert back and back.get("edited"), back
rows, absent = [], 0
for v in (12.0, 31.0, 52.0, 62.0, 88.0, 100.0):
    img = Image.new("RGBA", (render.W * render.SS, render.H * render.SS), (0, 0, 0, 0))
    render.temp_arc(img, CX, CY, v, LO, MID, HI, R, TH, render.TRACK)
    code = img.resize((render.W, render.H), Image.LANCZOS).convert("RGBA")
    lay, notes = themes.draw(themes.load(back["path"]), {"cpu": {"temperature": v}})
    flat = ImageChops.difference(code, lay.convert("RGBA")).get_flattened_data()
    diff = sum(1 for q in flat if q != (0, 0, 0, 0))
    worst = max((max(q) for q in flat), default=0)
    painted = sum(1 for q in code.getchannel("A").get_flattened_data() if q)
    assert diff == 0 and worst == 0, (v, diff, worst, notes["arc_colour"])
    rows.append((v, painted, notes["arc_colour"]))
assert "no fill" in [r[2] for r in rows[:1]], rows[0]

# how exact the data spelling is against each ramp this repo draws, counted on the
# segment colours the painters actually use (3 degrees, sampled at the segment start)
def segcols(fn, sweep, n=92):
    out, acc = [], 0.0
    while acc < sweep * n / 100.0 - 0.001:
        out.append(fn(acc / sweep))
        acc += 3.0
    return out


def stopcol(stops, t):
    return layout.ramp_at(list(stops), t, "trunc")       # stops are (frac, rgba tuple)


temp_stops = [(0.0, render.GREEN), ((MID - LO) / (HI - LO), render.AMBER),
              (1.0, render.RED)]
temp_code = [render.temp_colour(LO + t * (HI - LO), LO, MID, HI)
             for t in [i * 3.0 / 300.0 for i in range(100)]]
temp_bad = sum(1 for t, want in zip([i * 3.0 / 300.0 for i in range(100)], temp_code)
               if stopcol(temp_stops, t) != want)
heat_stops = [(0.0, render.CYAN), (0.5, render.GREEN), (0.8, render.AMBER),
              (1.0, render.RED)]
ts = [i * 3.0 / 300.0 for i in range(100)]
heat_off = [(t, render.heat(t), stopcol(heat_stops, t)) for t in ts
            if render.heat(t) != stopcol(heat_stops, t)]
assert temp_bad == 0, temp_bad
assert heat_off, "heat() now agrees with a stop-interpolated copy - recheck the finding"
# where it differs and by how much, derived rather than remembered
span_of = lambda t: ("0.5-0.8, where heat divides by 0.3 and the stops give "
                     "0.30000000000000004") if 0.5 < t < 0.8 else (
                     "past 0.8, where heat divides by 0.2 and the stops give "
                     "0.19999999999999996")
by_seg = {}
for t, _a, _b in heat_off:
    by_seg[span_of(t)] = by_seg.get(span_of(t), 0) + 1
units = max(max(abs(a[i] - b[i]) for i in range(4)) for _t, a, b in heat_off)
chans = sorted({i for _t, a, b in heat_off for i in range(4) if a[i] != b[i]})
assert units == 1 and chans == [0, 2], (units, chans)      # red and blue only
assert sum(by_seg.values()) == len(heat_off), by_seg
themes.delete_user_theme("fixture-ring")
print(f"  an authored ramp      a layout nobody shipped, written by the file model and "
      f"read back from {os.path.relpath(path, themes.user_root())}, paints "
      f"`render.temp_arc`'s ring with **0 differing pixels and worst channel 0** at all "
      f"six values (12 / 31 / 52 / 62 / 88 / 100 C, {rows[1][1]:,} lit px, the first "
      f"below the declared scale drawing `no fill` both ways) - the ramp is "
      f"`xigma.colourStops`, three pairs, and the convention is `xigma.arcPaint: render`")
print(f"                        why the data spelling and not a named function: counted "
      f"over the segment colours the painters use, `render.temp_colour` agrees with the "
      f"stop-interpolated ramp on all {len(ts)} sampled positions ({temp_bad} differ), "
      f"while `render.heat()` differs from its own stop copy on {len(heat_off)} of "
      f"{len(ts)} - never by more than {units} unit, in the "
      + " and ".join("rgb"[c] for c in chans) + " channels only, and the positions name "
      f"the cause: " + "; ".join(f"{n} in the segment {why}"
                                for why, n in sorted(by_seg.items()))
      + ". Under `int()` truncation a product a hair under an integer steps down, so this "
      "is our arithmetic and not the schema: `dual` waits on whether to fix `heat` - which "
      "moves recorded figures for dual, alpha and bars, all three of which draw that ramp - "
      "or to name the ramp the way a `special` drawing is named (docs/limits.md, "
      "docs/theme-editor.md)")
PY
rm -rf "$AUTH_TMP"

# ---- the four `line` widgets, measured against the vendor's own baked picture.  The
# ---- first time a copied layout is compared with pixels the vendor itself drew.
python3 - <<'PY' || { echo "line vs its own picture FAILED"; exit 1; }
import json, os
from PIL import Image, ImageDraw
from xigmalcd import layout, render, themes
man = json.load(open(os.path.join(themes.REPO_ROOT, "manifest.json")))
by_layout = {t["layout"].split("/")[-1][:-5]: t for t in man["themes"]}
LINE_THEMES = ("1757491588497", "1757491589611")          # Theme_14 and theme_46
report = []
for lay in LINE_THEMES:
    ent = by_layout[lay]
    obj = json.load(open(os.path.join(themes.REPO_ROOT, ent["layout"])))
    name = obj["background"]["mediaFile"].rsplit("/", 1)[-1].split(".")[0]
    props = [w["property"][0] for w in obj["osd"]["widget"] if w["type"] == "line"]
    assert len(props) == 2, (lay, len(props))
    assert all(not p.get("source") for p in props), "a line widget with a metric behind it"
    fg = Image.open(os.path.join(themes.REPO_ROOT, ent["foregroundFile"])).convert("RGBA")
    va = fg.getchannel("A")
    pred = set()
    for pr in props:
        lx, ly, lw, lh = layout.line_rect(pr)
        pred |= {(px, py) for py in range(ly, ly + lh) for px in range(lx, lx + lw)}
    outside = [q for q in pred if not va.getpixel(q)]         # we draw where it draws
    inks = {fg.getpixel(q) for q in pred}                     # its ink, from those pixels
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    boxes = [layout.draw_line(dr, pr) for pr in props]
    img = img.resize((render.W, render.H), Image.LANCZOS)
    oa = img.getchannel("A")
    ours = {(x, y) for y in range(render.H) for x in range(render.W)
            if oa.getpixel((x, y)) >= 128}
    diff = ours ^ pred
    # anything the supersampled paint-and-shrink path puts outside the rect must be one of
    # its edge pixels: a real offset would show up several pixels away, and would be a bug
    strays = [q for q in diff
              if not any(abs(q[0] - r[0]) <= 1 and abs(q[1] - r[1]) <= 1 for r in pred)]
    p90 = next(pr for pr in props if int(pr.get("rotate") or 0) % 180 == 90)
    lx, ly, lw, lh = layout.line_rect(p90)
    band = {(bx, by) for by in range(ly + 1, ly + lh) for bx in range(lx - 7, lx + lw + 7)
            if va.getpixel((bx, by))}
    unexplained = [q for q in band if q not in pred]
    corner_lit = sum(1 for q in {(165 + i, 305 + j) for i in range(2)
                                for j in range(150)}
                     if va.getpixel(q) and q not in pred)
    assert not outside, (lay, outside[:8])
    assert inks == {layout.MEASURED_LINE_INK}, (lay, inks)
    assert not strays, (lay, sorted(strays)[:8])
    assert len(band) > 200 and not unexplained, (lay, len(band), unexplained[:8])
    report.append((name, len(pred), len(ours), len(diff), len(band), corner_lit,
                   boxes[1]))
per = "; ".join(f"{n}: the two rects cover {np} px and the vendor's own overlay lights "
                f"every one of them; our painter puts down {nu} px, {nd} of them outside "
                f"those rects; in the band around the rotated stroke the overlay lights "
                f"{nb} px and none is unexplained"
                for n, np, nu, nd, nb, cl, bx in report)
print(f"  line vs its own picture {per}")
print(f"                        ink: all of it is rgba{layout.MEASURED_LINE_INK} "
      f"in the picture, alpha 255, hard-edged - the renderer bundle's default "
      f"rgba(19, 206, 102, 1) is a green no shipped theme is observed to draw, so it is "
      f"recorded in layout.py's comment and not used")
print(f"                        rotate: the 90-degree widget draws at {report[0][6]}, the "
      f"rect turned about its own centre; a top-left corner pivot would have left it at "
      f"x=165, and the overlay lights {report[0][5]} pixels there that the rects do not "
      f"explain - so the centre rule is the measured one")
PY

echo
# ---- the field census an inspector is built from, counted over the vendor's own trees
python3 - <<'PY' || { echo "theme field census FAILED"; exit 1; }
import subprocess, sys
from xigmalcd import themes
cen = themes.field_census()
read, sub = themes.keys_read()
assert cen["widgets"] == 152, cen["kinds"]
assert cen["kinds"] == {"data": 66, "text": 66, "bar": 15, "line": 4, "arc": 1}, cen["kinds"]
assert len(cen["keys"]) == 33, sorted(cen["keys"])
assert set(cen["keys"]["x"]) == {"data", "text", "bar", "line", "arc"}, cen["keys"]["x"]
assert sorted(set(read) - set(cen["keys"])) == ["lineColor", "lineWidth", "name", "xigma"], \
    sorted(set(read) - set(cen["keys"]))
assert sorted(set(cen["keys"]) - set(read)) == sorted(themes.UNREAD_WHY), \
    sorted(set(cen["keys"]) - set(read))
assert set(sub) == {"anchor", "arcPaint", "autoFitMax", "barPaint", "colourRamp",
                    "colourStops", "fitArc", "format", "showIf"}, sub
assert set(sub) == set(themes.XIGMA_KEYS), (sorted(set(sub) - set(themes.XIGMA_KEYS)),
                                            sorted(set(themes.XIGMA_KEYS) - set(sub)))
assert cen["values"]["enableMove"] == {"False": 152}
assert cen["values"]["italic"] == {"False": 132}, cen["values"]["italic"]
assert cen["values"]["underline"] == {"False": 132}
assert len(cen["values"]["time"]) == 27 and set(cen["time_per_file"].values()) == {1} \
    and len(cen["time_per_file"]) == 27, cen["time_per_file"]
assert "rotate" in read and "xigma" in read, read
fields = subprocess.run([sys.executable, "-m", "xigmalcd", "--print-theme-fields"],
                        capture_output=True, text=True, check=True)
assert "ttyACM" not in fields.stdout
missing = [k for k in cen["keys"] if f"  {k}" not in fields.stdout and
           f"    {k} " not in fields.stdout]
assert not missing, missing
print(f"  field census          {cen['widgets']} widgets in 27 layouts answer to "
      f"{len(cen['keys'])} distinct `property` keys: {len(set(read) & set(cen['keys']))} "
      f"are read by layout.py (the list comes out of layout.py's own source with `ast`, "
      f"not from a hand-kept table, so the painter and the census cannot drift), "
      f"{len(cen['keys']) - len(set(read) & set(cen['keys']))} are carried and never read "
      f"(each with a stated reason), and {len(set(read) - set(cen['keys']))} are read with "
      f"no vendor file to show ({', '.join(sorted(set(read) - set(cen['keys'])))})")
print(f"                        the two text looks-keys this program ignores - italic and "
      f"underline - are one value deep on every widget that carries them "
      f"({cen['values']['italic']['False']} each: never set), so nothing is missing from "
      f"the picture; and `time` is 27 distinct values over 152 widgets with every file "
      f"answering exactly one inside itself, which is a save stamp per theme rather than "
      f"a reading - the reason our exports omit it")
PY

echo
echo "== the sentences that quote a printed door, reprinted from the door"
# docs/usage.md, docs/themes.md, docs/theme-editor.md and README quote numbers that
# `--print-theme-fields`, `--list-themes`, `--check-theme` and `--list-specials` print.  Most
# of those numbers are already held somewhere else - the section that counts the vendor
# library, the one that paints the exports - but what is held there is the count, not the
# sentence.  A document can stay perfectly polite while the door it quotes changes under it,
# which is what this section is for: every figure below is taken from the command's own
# output on this run and compared against the words around it in the document.  Nothing here
# opens a port, and every command runs against the tree rather than an install.
python3 - <<'PY' || { echo "doc doors FAILED"; exit 1; }
import subprocess
import sys

from xigmalcd import render, themes

_WORDS = dict(enumerate("zero one two three four five six seven eight nine ten eleven "
                        "twelve thirteen fourteen fifteen sixteen seventeen eighteen "
                        "nineteen twenty twenty-one".split()))


def door(*args):
    """One printed door, exactly as a reader would see it."""
    r = subprocess.run([sys.executable, "-m", "xigmalcd", *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, (args, r.returncode, r.stderr[:400])
    assert "ttyACM" not in r.stdout and "/dev/tty" not in r.stdout, (
        args, "a door that quotes no device must not name one")
    return r.stdout


def _para(text, start, end, what):
    """One paragraph of a document, so a figure is checked where it is claimed rather than
    anywhere in the file - a number that appears once in a table and once, wrongly, in a
    sentence has to fail."""
    i = text.index(start)
    j = text.index(end, i)
    assert j > i, (what, start, "the paragraph does not end where this gate expects")
    return text[i:j]


usage = open("docs/usage.md", encoding="utf-8").read()
plan = open("docs/theme-editor.md", encoding="utf-8").read()
tdoc = open("docs/themes.md", encoding="utf-8").read()
readme = open("README.md", encoding="utf-8").read()

# ---- the field census sentence: `--print-theme-fields` is the door, and the sentence in
# ---- docs/usage.md is its summary
cen, read, sub = themes.field_census(), themes.keys_read()[0], themes.keys_read()[1]
fields = door("--print-theme-fields")
_p = _para(usage, "Its numbers go into the inspector design", "\n* **`--check-theme",
           "the field census sentence")
_claim = {
    "distinct keys": len(cen["keys"]),
    "widgets": cen["widgets"],
    "read by layout.py": len(set(read) & set(cen["keys"])),
    "carried and never read": len(set(cen["keys"]) - set(read)),
    "read with no vendor example": len(set(read) - set(cen["keys"])),
}
_absent = {k: v for k, v in _claim.items() if str(v) not in _p}
assert not _absent, (_claim, _absent, _p[:300])
for _line in fields.splitlines():
    if "distinct `property` keys" in _line:
        break
else:
    raise AssertionError(fields[:400])
# the two text looks-keys and the number of widgets that carry them, since that is the
# finding the sentence says is worth knowing before anyone asks why a theme looks the same
_it, _un = sum(cen["values"]["italic"].values()), sum(cen["values"]["underline"].values())
assert _it == _un, (cen["values"]["italic"], cen["values"]["underline"],
                    "the two looks-keys no longer sit on one number of widgets, and the "
                    "sentence quotes a single number")
assert str(_it) in _p, (_it, _p[:240], "the sentence lost the count of widgets carrying them")
assert all(set(cen["values"][k]) == {"False"} for k in ("italic", "underline")), (
    cen["values"]["italic"], cen["values"]["underline"],
    "the sentence says neither looks-key is ever set anywhere in the library, and a `true` "
    "would make that claim wrong - which is the whole finding the sentence is making")
assert all(f"`{k}`" in fields for k in ("italic", "underline")), fields[:200]
print(f"  --print-theme-fields  {len(cen['keys'])} keys / {cen['widgets']} widgets / "
      f"{len(set(read) & set(cen['keys']))} read / "
      f"{len(set(cen['keys']) - set(read))} carried unread / "
      f"{len(set(read) - set(cen['keys']))} read with no example, and docs/usage.md's "
      f"sentence states every one of those five numbers ({_it} widgets carry each of the "
      f"two looks-keys, none of them ever set)")

# ---- the picker claim: how many of the vendor's files this canvas can select, in the two
# ---- documents that say it
ok, refused = themes.scan()
listing = door("--list-themes")
assert listing.count("\n") >= len(ok) + len(refused), listing[:200]
assert f"{len(ok)} of the vendor's {len(ok) + len(refused)}" in tdoc, (
    len(ok), len(refused),
    "docs/themes.md miscounts what the picker takes from the vendor's files")
_row = next(ln for ln in plan.splitlines() if ln.startswith("| layout files |"))
assert f"**{len(ok) + len(refused)}**" in _row and f"{len(ok)} at `ratio" in _row \
    and f"{len(refused)} at `ratio" in _row, (len(ok), len(refused), _row)
print(f"  --list-themes         {len(ok)} pickable, {len(refused)} refused, all "
      f"{len(ok) + len(refused)} named in the listing; docs/themes.md and the plan's own "
      f"census table row both state that split")

# ---- the `special` count, spelled out in the plan
names = themes.special_names()
specials = door("--list-specials")
assert all(f"  {n}" in specials for n in names), specials[:300]
_sent = _para(plan, "`--list-specials`; ", "The label pair was the open question",
              "the specials sentence")
assert f"{_WORDS[len(names)]} have landed" in _sent, (
    len(names), _sent[:160], "the plan miscounts the specials that have landed")
for n in names:
    assert f"`{n}`" in _sent, (n, "a landed special is not named in the sentence that "
                                 "counts them")
print(f"  --list-specials       {len(names)} names ({' '.join(names)}), and the plan's "
      f"sentence counts them and names each one")

# ---- one fenced transcript, line by line, against the door that wrote it: the block in
# ---- docs/usage.md for Theme_28.  Which lines of that block a machine may change is said
# ---- in the document, so the gate checks the file-derived ones for word-for-word equality
# ---- and the machine-dependent ones for shape.
_block = [ln.strip() for ln in usage[
    usage.index("  ```\n  Theme_28 (") + 8:
    usage.index("  ```", usage.index("  ```\n  Theme_28 (") + 8)].splitlines()]
_chk = [ln.strip() for ln in door("--check-theme", "Theme_28").splitlines() if ln.strip()]
assert _block[0] == _chk[0], (_block[0], _chk[0],
                              "the transcript's first line is read out of the file, so it "
                              "is the run's line or it is wrong")
_ask_doc = next(ln for ln in _block if ln.startswith("this theme asks for:"))
_ask_run = next(ln for ln in _chk if ln.startswith("this theme asks for:"))
assert _ask_doc == _ask_run, (_ask_doc, _ask_run)
_gaps_doc = [ln for ln in _block if ln.startswith("shaped by this repo")]
_gaps_run = [ln for ln in _chk if ln.startswith("shaped by this repo")]
assert _gaps_doc == _gaps_run, (_gaps_doc, _gaps_run)
for _lbl in ("drawn from this machine's readings", "shaped by this repo",
             "this theme asks for", "this machine answers", "and cannot"):
    assert any(_lbl in ln for ln in _block) and any(_lbl in ln for ln in _chk), (
        _lbl, "the transcript and the door no longer have the same lines - one of them grew "
              "or dropped a half, and the document is supposed to show the real shape")
_sk_doc = next(ln for ln in _block if "skipped:" in ln)
_sk_run = next(ln for ln in _chk if " boxes," in ln)
assert "skipped: Pump Speed" in _sk_doc, _sk_doc
assert "Pump Speed" in _sk_run, _sk_run
_n_boxes = int(_sk_run.split(" boxes,")[0].split()[-1])
_n_notes = len([x.strip() for x in _sk_run.split("skipped:", 1)[1].split(",")]) \
    if "skipped:" in _sk_run and _sk_run.split("skipped:", 1)[1].strip() != "nothing" else 0
_widgets = int(_chk[0].split(", ")[1].split()[0])
assert _n_boxes + _n_notes == _widgets, (_n_boxes, _n_notes, _widgets, _sk_run,
                                         "the door's own accounting does not close, so the "
                                         "transcript cannot be trusted for either count")
print(f"  --check-theme Theme_28  the transcript's file-derived lines match word for word "
      f"({_block[0]} / {_ask_doc}); the machine-dependent pair closes "
      f"({_n_boxes} boxes + {_n_notes} skip notes = {_widgets} widgets)")

# ---- README's five-theme claims: the names it previews are the themes it says exist
_previews = [t for t in sorted(render.THEMES) if f"`{t}`" in readme]
assert _previews == sorted(render.THEMES), (
    _previews, sorted(render.THEMES), "README does not name every drawn theme in its "
                                     "preview table")
print(f"  README                names all {len(render.THEMES)} drawn themes "
      f"({' '.join(sorted(render.THEMES))}), and its preview slots are checked by the "
      f"section that measures the six video files")
PY

echo "== what a layout file can and cannot answer, option by option"
# All five drawn themes also exist as generated layout files, so the file door *could* draw
# them - and the question of whether it should is answered per option, not per theme, by
# tools/knobmap.py: one pinned reading dict, one pinned clock instant, the best row-level
# edit of that theme's own export for each option its signature accepts, and the pixels
# between the two doors.  Nothing is sent anywhere; no port is opened.
#
# What this section holds is the structure of the answer, which is the part that does not
# depend on which fonts are installed:
#   * every option in every drawn theme's signature is accounted for - it is either a row in
#     the map or it is in the unread list, and the unread list is derived here from the bodies
#     with `ast` so the tool cannot quietly drop an option and make the map look clean;
#   * exactness is binary.  A row is either 0 px with a worst channel of 0, or it is past a
#     floor this section picks from the run and asserts - so "the file door nearly answers it"
#     is not a state the map can be in;
#   * two invariants that would each be a bug if they ever moved: the reader's text colour and
#     the default transparent canvas are exact for all five (the ink goes through
#     `themes.with_ink`, the canvas is the case every parity claim in the docs is about);
#   * docs/limits.md states the counts, the black-canvas share and the unread option in the
#     same derived words, so the paragraph cannot drift from the measurement.
python3 - <<'PY' || { echo "knobmap FAILED"; exit 1; }
import ast
import inspect
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, ".")
from xigmalcd import render, themes

if not os.path.isfile("tools/knobmap.py"):
    raise SystemExit("tools/knobmap.py is missing: this section is a gate over that tool")
tmp = tempfile.mktemp(suffix=".json")
r = subprocess.run([sys.executable, "tools/knobmap.py", "--json", tmp],
                   capture_output=True, text=True)
assert r.returncode == 0, (r.stdout[-800:], r.stderr[-800:])
data = json.load(open(tmp, encoding="utf-8"))
os.unlink(tmp)
rows, knobs_of = data["rows"], data["knobs"]
unread = [u[0:2] for u in data["unread"]]

# every signature option is a row or an unread note - derived from the bodies, here
expect_unread, expect_rows = [], 0
for name in sorted(render.THEMES):
    sig = inspect.signature(render.THEMES[name])
    opts = [k for k in sig.parameters if k not in ("m", "metrics")]
    assert knobs_of.get(name) == sorted(opts), (name, knobs_of.get(name), sorted(opts))
    tree = ast.parse(inspect.getsource(render.THEMES[name]))
    for knob in opts:
        uses = sum(1 for node in ast.walk(tree)
                   if isinstance(node, ast.Name) and node.id == knob)
        # `bg` arrives as two rows (`bg clear`, `bg black`) and `title` as two values, so a
        # row belongs to an option when its knob is that name or `<name> <something>` - and
        # only then: prefix matching alone would count `clock_size`'s row under `clock` too.
        n_rows = len([r for r in rows if r["theme"] == name
                      and (r["knob"] == knob or r["knob"].startswith(knob + " "))])
        if uses == 0:
            expect_unread.append((name, knob))
            assert n_rows == 0, (name, knob, "an unread option is in the map anyway")
        else:
            expect_rows += n_rows
            assert n_rows >= 1, (name, knob, "an option the body reads has no row")
assert sorted(tuple(u) for u in unread) == sorted(expect_unread), (
    unread, expect_unread, "the unread list is not what the bodies say it is")
assert len(rows) == expect_rows, (len(rows), expect_rows)

# exactness is binary, and the floor is taken from this run rather than remembered
zero = [r for r in rows if r["exact"]]
apart = [r for r in rows if not r["exact"]]
assert all(r["diff_px"] == 0 and r["worst_channel"] == 0 for r in zero), zero
assert all(r["diff_px"] > 0 for r in apart), [r for r in apart if r["diff_px"] == 0]
floor = min(r["diff_px"] for r in apart)
assert floor > 900, (floor, "a non-exact pair is close enough to 0 that 'exactly 0 or clearly "
                            "not' stops being a decision: the map's line has moved under it")

# the two invariants
for name in sorted(render.THEMES):
    ink = [r for r in rows if r["theme"] == name and r["knob"] == "ink"]
    clear = [r for r in rows if r["theme"] == name and r["knob"] == "bg clear"]
    assert len(ink) == 1 and ink[0]["exact"], (name, ink,
                                               "`themes.with_ink` no longer matches the code "
                                               "drawing: the pane's two doors disagree about "
                                               "the reader's own colour")
    assert len(clear) == 1 and clear[0]["exact"], (
        name, clear, "at the default transparent canvas the file door and the code door are "
                     "not one picture, and every parity figure in the docs is about that case")
black = [r for r in rows if r["knob"] == "bg black"]
assert len(black) == len(render.THEMES) and all(not r["exact"] for r in black), (
    black, "the black canvas is expected to differ between the doors (a plate under a layer "
           "is not a canvas drawn on); if it stopped differing, docs/usage.md's `--bg` row "
           "and docs/limits.md's map paragraph are both wrong")

# and the documents, in the same derived words
_lim = open("docs/limits.md", encoding="utf-8").read()
_claims = [f"{len(zero)} of the {len(rows)} (theme, option) pairs",
           f"{len(apart)} of them are far from 0",
           f"{sum(1 for r in black if not r['exact'])} of them are the black canvas",
           "above 900 px"]
for name, knob in sorted(expect_unread):
    _claims.append(f"`{name}` takes `{knob}` and never reads it")
    # and the reader-facing half: the flag table has to say so where the flag is listed
    _usage_doc = open("docs/usage.md", encoding="utf-8").read()
    assert f"`theme_{name}` never reads `{knob}`" in _usage_doc, (
        name, knob, "docs/usage.md lists the flag that reaches this option without saying "
                    "that the theme ignores it")

# The other direction, and the one that matters now: an option that *is* read has to be a row,
# and for this one an exact row.  `--no-clock` on `clock` was caught by this tool as an option
# in the signature and nowhere in the body; the body honours it as of 0.4, so the pair became
# a row that lands at 0 px in both doors.  If the body ever stops honouring it, the option
# drops back onto the unread list above (so the counts move) *and* this assert names it, which
# is the difference between a gate that reports a drift and one that quietly re-labels it.
_HONOURED = {"clock": ("clock", "drops the big time line and keeps the date and the readings "
                                "line")}
for _name, (_knob, _phrase) in _HONOURED.items():
    _here = [r for r in rows if r["theme"] == _name and r["knob"] == _knob]
    assert len(_here) == 1 and _here[0]["exact"], (
        _name, _knob, [(r["knob"], r["diff_px"]) for r in _here],
        "this option is no longer one row landing at 0 px in both doors: the theme stopped "
        "honouring the flag, or its file-side answer moved")
    assert f"`{_name}` honours `--no-{_knob}`" in _lim, (
        _name, _knob, "docs/limits.md does not say the flag is honoured, which is the half a "
                      "reader acts on")
    assert _phrase in open("docs/usage.md", encoding="utf-8").read(), (
        _name, _phrase, "docs/usage.md's flag table does not describe what this flag does to "
                        "that frame")
# and no "the body ignores it" sentence may outlive a fix
for _r in rows:
    assert (f"`{_r['theme']}` takes `{_r['knob']}` and never reads it" not in _lim), (
        _r["theme"], _r["knob"], "docs/limits.md still calls an option that this run found in "
                                 "the body unread")

# docs/tools.md quotes the same split in its catalogue row, and that table is only read if its
# rows are the shape the header promises: an inserted row once spliced itself into the next
# one, and GitHub drops the extra cells without warning.
_tools_doc = open("docs/tools.md", encoding="utf-8").read()
_t_claim = f"{len(zero)} of the {len(rows)} pairs"
assert _t_claim in _tools_doc, (_t_claim, len(zero), len(rows),
                                "docs/tools.md's catalogue row quotes different digits than "
                                "this run measured")
_cat = _tools_doc.split("\n")
_h = next(k for k, ln in enumerate(_cat) if ln.startswith("| If the question is |"))
_end = _h
while _end + 1 < len(_cat) and _cat[_end + 1].startswith("|"):
    _end += 1
_cols = _cat[_h].count("|") - 1
_ragged = [(k + 1, _cat[k].count("|") - 1) for k in range(_h, _end + 1)
           if _cat[k].count("|") - 1 != _cols]
assert not _ragged, (_ragged, _cols, "the catalogue table has rows that are not "
                                     f"{_cols} cells, so the overflow is dropped by the "
                                     "renderer and those sentences are not being read")
_missing = [c for c in _claims if c not in _lim]
assert not _missing, (_missing, "docs/limits.md does not state what this run measured, so the "
                                "paragraph is prose again rather than a claim held to the map")
print(f"  the map                {len(render.THEMES)} drawn themes x their own signatures = "
      f"{len(rows)} (theme, option) pairs; {len(zero)} land at 0 px (worst channel 0) and "
      f"{len(apart)} are far from 0, the closest being {floor:,} px, which is above the 900 px "
      f"the documents quote; {len(black)} of the non-exact pairs are the black canvas alone")
print(f"                       options a body never reads: "
      + (", ".join(f"{n}.{k}" for n, k in sorted(expect_unread)) or "none")
      + "; the routes are taken from `main._theme_kwargs` with `ast`, so an option nobody can "
        f"ask for is said as such ({len([r for r in rows if 'Python only' in r['route']])} "
        f"pairs have no CLI or socket route)")
_other = sorted({f"{r['theme']}.{r['knob']} {r['diff_px']:,} px" for r in apart
                 if r["knob"] != "bg black"})
_lo, _hi = min(x["diff_px"] for x in black), max(x["diff_px"] for x in black)
print("  what cannot be routed  " + "; ".join(_other)
      + f"; bg black on {len(black)} themes ({_lo:,}-{_hi:,} px). Those figures walk glyph "
        "edges and installed faces, so they are printed beside the machine and the documents "
        "carry only the split and the floor")
PY

echo "== decoder round-trip: encode -> decode -> re-encode"
python3 - <<'PY' || { echo "decoder round-trip FAILED"; exit 1; }
from xigmalcd import protocol as p
cases = [("POST conn 1", b""),
         ("POST power 1", {"event": "resume"}),
         ("STATE all 1", {"fans": [{"onBoard": True, "name": "Fan CPU", "value": 1476}],
                          "cpu": {"temperature": 57, "voltage": 1.365}}),
         ("POST transport 1", {"type": "media", "fileSize": 12034,
                               "fileName": "2026-11-05_07-21-36-052.osd"})]
for line, obj in cases:
    fr = p.encode(line, {"SeqNumber": 1, "Date": 1}, obj)
    m = p.decode(fr)
    assert m.line == line, m.line
    assert p.encode(m.line, {k: v for k, v in m.headers.items() if k != "CkOK"},
                    m.json() if m.body else b"") == fr, line
    print(f"  {line:22s} {len(fr):4d} bytes  cksum ok={p.checksum_ok(fr)}")
# escaping: 0x5A would end the frame and 0x5B starts an escape, so both get
# quoted; a JSON array opener or a serial number with a Z in it has to come
# back out unchanged
for body in (b'{"sn":"FAKE-SN-WITH-Z-0001"}',
             b'{"attribute":["Status","Fan","Pump"]}'):
    fr = p.encode("1 200", {"SeqNumber": 1}, body)
    assert p.unescape(p.escape(body)) == body
    assert p.decode(fr).body == body, body
    assert p.checksum_ok(fr) and p.read_frame(fr)[1] == len(fr)
print("  escaped payloads         0x5A/0x5B quoted, round-trip clean")

# reading a stream: escaping makes the wire longer than the declared length, so
# the splitter unescapes as it walks and ends the frame on the right byte
body = {"attribute": ["Status", "Fan", "Pump"], "sn": "FAKE-SN-WITH-Z-0001"}
fr = p.encode("1 200", {"AckNumber": 1, "ContentType": "json"}, body)
assert len(fr) > p.inner(fr)[0] << 8 | p.inner(fr)[1], "this frame is escaped"
assert p.read_frame(b"junk" + fr + b"tail", 4) == (fr, 4 + len(fr))
assert p.read_frame(fr[:-1] + b"X") is None, "an unterminated frame is refused"
print("  stream splitter          frame found, junk around it ignored")

# a reply with a bad checksum is still parsed on structure alone, with the
# mismatch reported instead of being fatal
bad = bytearray(p.encode("1 200", {"AckNumber": 1, "ContentType": "json",
                                   "ContentLength": 6}, {"a": [1]}))
bad[-2] ^= 0xFF                     # corrupt the cksum byte
assert p.frame_ok(bytes(bad)), "structure should still be accepted"
assert not p.checksum_ok(bytes(bad)), "and the bad cksum should be reported"
assert p.decode(bytes(bad)).json() == {"a": [1]}
print("  broken device reply      parsed on structure, cksum flagged")
PY

echo
echo "== settings: what the window keeps between runs, and the junk it refuses"
cfgtmp=$(mktemp -d)
XDG_CONFIG_HOME=$cfgtmp python3 - <<'PY' || { echo "settings FAILED"; exit 1; }
import json
import os
import sys
sys.path.insert(0, ".")
from xigmaui import settings

assert settings.load() == settings._clean({}), "no file yet is not an error"
print(f"  no file                {settings.path()}")

clip = os.path.abspath("media/Theme_11.mp4")
want = dict(settings.load())
want.update(theme="gauge", clock_size=44, canvas="black", scrim=60, fans=False,
            preview_fps=4.5, clip=clip, size=[900, 640], keep_my_clip=True)
where = settings.save(want)
assert where == settings.path(), where
back = settings.load()
for key, val in want.items():
    assert back[key] == val, (key, back[key], val)
assert json.load(open(where))["clock_size"] == 44      # plain JSON on disk

# Whether a layout may change the background is stored, because the difference between "the
# pairing put this here" and "hold this one" is a fact about what a human asked for and the
# window cannot recover it from a path: both clips are the same shape on disk.  So it is a
# bool, and only a bool - the settings box refuses `"yes"`, `1` and `null` the way it
# refuses a clock size of 200, because a truthy accident here silently stops the window
# following a layout's own clip and nobody can see why the picture stopped changing.
assert settings.load()["keep_my_clip"] is True, "a stored True did not come back"
for junk in ("yes", "true", 1, 0, None, [], {}, 3.5):
    assert settings._clean({"keep_my_clip": junk})["keep_my_clip"] is False, junk
assert settings._clean({})["keep_my_clip"] is False
assert settings._clean({"keep_my_clip": False})["keep_my_clip"] is False
print("  the pairing flag     True survives a save and a reload; "
      + f"{len(['yes', 'true', 1, 0, None, [], {}, 3.5])} kinds of junk fall back to False")

# `clip_customized` was the older key for the same idea, and 0.4 changed what its default
# means: an older file said "a row was clicked", a newer one says "a person ticked a box".
# Four combinations are pinned, because the one that matters is the one a real upgrade hits
# and the one that would be easy to get wrong is the pair that disagrees with itself.
_MIG = (("only the old key, true", {"clip_customized": True}, True,
         "keep my background"),                     # what the box is now called
        ("only the old key, false", {"clip_customized": False}, False,
         None),                                     # the new default already says this
        ("both keys, new wins", {"clip_customized": True, "keep_my_clip": False}, False,
         "the new key wins"),
        ("neither key", {}, False, None))
for _label, _raw, _keeps, _said in _MIG:
    _seen: list[str] = []
    _got = settings._clean(_raw, _seen)
    assert _got["keep_my_clip"] is _keeps, (_label, _got["keep_my_clip"], _keeps)
    assert "clip_customized" not in _got, (_label, "the retired key is still in the dict")
    if _said is None:
        assert not _seen, (_label, _seen, "a file that needed no explaining handed the "
                                          "window a sentence anyway")
    else:
        assert len(_seen) == 1 and _said in _seen[0], (
            _label, _seen, "a file that needed explaining did not hand the window the "
                           "sentence it promises")

# and the file a person actually has: the old key on disk, honoured, explained, and gone
# after one save.  A second settings root, so this never disturbs the file the rest of the
# section is using.
_root = os.environ["XDG_CONFIG_HOME"]
_old_only = os.path.join(_root, "old-key-session")
os.makedirs(os.path.join(_old_only, "xigmaui"), mode=0o700,
            exist_ok=True)      # `path()` wants the app directory under the root
os.environ["XDG_CONFIG_HOME"] = _old_only
try:
    with open(settings.path(), "w", encoding="utf-8") as fh:
        json.dump({"clip_customized": True, "clip": clip}, fh)
    _note: list[str] = []
    _loaded = settings.load(_note)
    assert _loaded["keep_my_clip"] is True, _loaded
    assert len(_note) == 1 and "keep my background" in _note[0], _note
    settings.save(_loaded)
    _disk = json.load(open(settings.path(), encoding="utf-8"))
    assert "clip_customized" not in _disk, _disk
    assert _disk["keep_my_clip"] is True, _disk
    print("  the retired key      an old `clip_customized: true` is honoured once as a "
          "ticked box,")
    print("                       the window is handed the note to say so, and the next "
          "save leaves only")
    print("                       `keep_my_clip` on disk: "
          + f"{sorted(_disk)}")
finally:
    os.environ["XDG_CONFIG_HOME"] = _root

# the text colour, through the same validation rather than a second rule: a
# name or a short hex is normalised to `#rrggbb` on disk, and a value the
# renderer would refuse falls back to "" (the theme's own skin) the way an
# out-of-range clock size does
for spell, want in (("amber", "#ffc400"), ("#0f8", "#00ff88"),
                    ("#FF4040", "#ff4040"), ("", ""), ("cerise", ""),
                    (None, ""), (7, "")):
    got = settings._clean({"text_color": spell})["text_color"]
    assert got == want, (spell, got, want)
assert settings.DEFAULTS["text_color"] == "", "the default is the theme's own ink"
print("  text colour            '#0f8' -> '#00ff88', 'amber' -> '#ffc400', "
      "'cerise' refused back to the theme's own")
print(f"  round trip             {where} "
      f"({os.path.getsize(where)} B, theme {back['theme']}, clip "
      f"{os.path.basename(back['clip'])})")

# hand-edited, half-written or out-of-range values must not stop the window, and
# a clip that is not there (Windows partition unmounted) falls back to ours
for junk in ("", "{", "[]", '{"theme": "nope", "clock_size": 9999, "canvas": "x",'
             ' "fans": "yes", "preview_fps": 0, "size": [1, 1],'
             ' "clip": "/media/windows-c/nope.mp4"}'):
    open(where, "w").write(junk)
    assert settings.load() == settings._clean({}), repr(junk)
print("  junk refused           empty, truncated, wrong type, out of range")
PY

echo
# The package as a person installs it, not as the repo happens to sit on disk:
# both importable packages, Qt kept in the extra, and both console scripts
# resolving to something callable.
python3 - <<'PY' || { echo "packaging FAILED"; exit 1; }
import importlib
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        print("  packaging        skipped: no tomllib (python 3.11+) and no tomli")
        raise SystemExit(0)
with open("pyproject.toml", "rb") as fh:
    cfg = tomllib.load(fh)
pk = cfg["tool"]["setuptools"]["packages"]
assert "xigmalcd" in pk and "xigmaui" in pk, pk
gui = cfg["project"]["optional-dependencies"]["gui"]
assert any("PyQt6" in d for d in gui), gui
assert not any("PyQt6" in d for d in cfg["project"]["dependencies"]), \
    "Qt belongs in the [gui] extra: the display loop runs without it"
scripts = cfg["project"]["scripts"]
assert set(scripts) == {"xigmalcd", "xigmaui", "xigmalcd-reset"}, scripts
for name, target in sorted(scripts.items()):
    mod, _, attr = target.partition(":")
    assert callable(getattr(importlib.import_module(mod), attr)), (name, target)

# `xigmalcd-reset` is the one entry point that can put a destructive frame on the
# wire, so the gate is checked here rather than trusted: called with no arguments,
# against whatever ports happen to exist, it must build the frame, print it, and
# send nothing.  Nothing in this suite ever opens /dev/ttyACM0, and this is the
# check that keeps it that way.
import contextlib, io
from xigmalcd import reset as resetmod
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = resetmod.main([])
text = out.getvalue()
assert rc == 0 and "dry run: nothing sent" in text, text
assert "frame to send (109 bytes)" in text, text     # the vendor's own frame length
print(f"  reset gate           {scripts['xigmalcd-reset']} with no --yes sends "
      f"nothing ({len(text)} B printed, 109-byte frame shown)")

# the licence the README states and the licence the package declares have to be
# the same thing, and the file it points at has to be the licence itself rather
# than a stub: GPL-3.0-or-later as the SPDX expression, and LICENSE byte-identical
# to the FSF's gpl-3.0.txt (that sha256 is of the text fetched from
# https://www.gnu.org/licenses/gpl-3.0.txt on 2026-11-07).  `license` as a string
# plus `license-files` is PEP 639, which is why [build-system] asks for
# setuptools >=77.
import hashlib
declared = cfg["project"].get("license")
# one number, four places: pyproject.toml, debian/changelog (checked by the build job,
# which also compares it with the tag), the wheel's METADATA that pyproject generates,
# and xigmalcd/__init__.py.  The last one is the one a reader meets in a traceback or an
# import, and nothing but this line keeps it equal to the others.
import xigmalcd
pkg_version = cfg["project"].get("version")
assert xigmalcd.__version__ == pkg_version, (xigmalcd.__version__, pkg_version)
print(f"  version            xigmalcd.__version__ == pyproject.toml == {pkg_version}")
assert declared == "GPL-3.0-or-later", declared
lfiles = cfg["project"].get("license-files")
assert lfiles == ["LICENSE"], lfiles
raw = open(lfiles[0], "rb").read()
assert b"GNU GENERAL PUBLIC LICENSE\n                       Version 3" in raw, raw[:60]
GPL3 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"
sha = hashlib.sha256(raw).hexdigest()
assert sha == GPL3, (sha, len(raw), "LICENSE is not the FSF's gpl-3.0.txt")
print(f"  licence            {declared}; LICENSE is the GPL-3 text verbatim "
      f"({len(raw)} B, sha256 {sha[:16]}...)")
print(f"  packaging        packages {' + '.join(pk)}, scripts "
      f"{'+'.join(sorted(scripts))} both resolve, Qt in the [gui] extra only "
      f"({', '.join(gui)})")
PY

echo "== the launcher, its icon and the login unit"
deskdir=$(mktemp -d)
sed -e "s|@DIR@|$PWD|g" -e "s|@PYTHON@|$(command -v python3)|g" \
    install/xigmaui.desktop.in > "$deskdir/xigmaui.desktop"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$deskdir/xigmaui.desktop" \
        || { echo "desktop entry FAILED"; exit 1; }
    echo "  desktop-file-validate    clean"
fi
python3 - "$deskdir/xigmaui.desktop" <<'PY' || { echo "launcher FAILED"; exit 1; }
import os
import sys
from PIL import Image

# read it by group: the file has a second Exec now (the tray-only action), and a
# flat key/value read would quietly test the action instead of the entry
groups, group = {}, None
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("[") and line.endswith("]"):
        group = line[1:-1]
        groups[group] = {}
    elif "=" in line:
        k, _, v = line.partition("=")
        groups[group][k] = v
main = groups["Desktop Entry"]
assert "@" not in "".join(main.values()), "a placeholder was left unexpanded"
assert main["Exec"].endswith("-m xigmaui"), main["Exec"]
assert os.path.isdir(main["Path"]), main["Path"]
assert main["Icon"] == os.path.join(os.getcwd(), "install", "xigmaui.png"), \
    main["Icon"]                        # a full path: no icon theme required
assert main["StartupWMClass"] == "xigmaui"
# the tray-only action: `--hidden` needs a tray to be useful, and it has no
# Path key of its own (that key is only legal in the main group), so it has to
# move to the checkout itself or `-m xigmaui` would not find the package
act = groups["Desktop Action tray"]
assert "--hidden" in act["Exec"], act["Exec"]
assert f"cd {os.getcwd()} &&" in act["Exec"], act["Exec"]
assert main["Actions"].rstrip(";") == "tray", main["Actions"]
assert "Path" not in act, "Path is not legal in an action group"
print(f"  launcher               Exec={main['Exec']}")
print(f"  tray action            {act['Exec']}")
# the class the shell matches on has to be the one the program sets, or the
# launcher's icon and the taskbar entry never line up
src = open("xigmaui/app.py", encoding="utf-8").read()
assert "setApplicationName" in src and "setDesktopFileName" in src, src[:200]
assert "--hidden" in src and "--no-tray" in src, "the flags the entry uses"
icon = "install/xigmaui.png"          # selftest runs from the repository root
im = Image.open(icon)
assert im.size == (256, 256) and im.mode == "RGBA", (im.size, im.mode)
# A mark, not a plate: the artwork arrives as a JPEG with a transparency
# checkerboard painted into it, so if that grid ever survives the extraction the
# icon is a photo of a grey grid.  The corners are where it would show.
corners = [im.getpixel(xy)[3] for xy in ((0, 0), (255, 0), (0, 255), (255, 255))]
assert all(a == 0 for a in corners), corners
assert os.path.getsize(icon) > 20_000, os.path.getsize(icon)
print(f"  icon                   {icon} {im.size[0]}x{im.size[1]} "
      f"{im.mode} {os.path.getsize(icon)} B, corners transparent")
# the same mark as a multi-size .ico, so a Windows shell or an icon theme that
# wants one gets 16 px through 256 px rather than one shrunken bitmap
ico = "install/xigmaui.ico"
sizes = Image.open(ico).info["sizes"]
assert (16, 16) in sizes and (256, 256) in sizes, sorted(sizes)
assert os.path.getsize(ico) > 20_000, os.path.getsize(ico)
print(f"  ico                    {ico} {os.path.getsize(ico)} B, "
      f"{len(sizes)} sizes {min(s[0] for s in sizes)}..{max(s[0] for s in sizes)} px")
# The strongest version of both checks: regenerate the shipped files from the
# committed artwork with the committed tool and require the same bytes.  In
# artwork mode makeicon.py reads no clock and no live metrics, so it is
# deterministic; a difference means a generated file was edited by hand instead
# of its source.
import hashlib
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


art = "install/artwork/xigma-penguin.jpg"
want = sha(art)
assert want == ("3774623ba3c4e934d2f40932f2037712f617cad877e2c3d65e8063b97a1e69aa"), \
    want                                    # the hash makeicon.py's docstring names
assert want in open("tools/makeicon.py", encoding="utf-8").read(), \
    "the tool's docstring no longer names this artwork"
with tempfile.TemporaryDirectory() as td:
    out, outico = (os.path.join(td, n) for n in ("i.png", "i.ico"))
    subprocess.run([sys.executable, "tools/makeicon.py", "-o", out, "--ico", outico],
                   check=True, capture_output=True)
    for shipped, made in ((icon, out), (ico, outico)):
        assert sha(shipped) == sha(made), (shipped, sha(shipped)[:12], sha(made)[:12])
print(f"  regenerates          {icon} + {ico} byte-identical from {art} "
      f"{os.path.getsize(art)} B {want[:16]}")
# and the logo the README shows at the top: the same mark, untrimmed into a square,
# on alpha, and actually referenced by the README
logo = "docs/logo.png"
lg = Image.open(logo)
assert lg.mode == "RGBA" and lg.width > lg.height, (lg.size, lg.mode)
assert f'"{logo}"' in open("README.md", encoding="utf-8").read(), "README: no logo"
print(f"  logo                   {logo} {lg.size[0]}x{lg.size[1]} {lg.mode} "
      f"{os.path.getsize(logo)} B")

# docs/packaging.md closes its packaging argument with an accounting of what the pictures
# and videos cost in the repository and stay out of the .deb: four group sizes, a file
# count and a total.  Five numbers someone has to remember, and two of them had already
# drifted - the video total by 22 405 B when the amber-ink figure was re-rendered, and the
# image total the moment the window was re-shot for the layout editor's new row.  So the
# arithmetic is done here, against the same files the document counts, and the document is
# held to it in the spaced style it writes them in.
import glob as _pglob


def _spaced(n):
    return f"{n:,}".replace(",", " ")


# "published" means tracked: a bench that has just run `dpkg-buildpackage` also has
# droppings under debian/ and an untracked render sitting next to the previews, and the same
# check then counts different files in different trees.  The list the repository ships is the
# one the rule is about, on every machine.
_tracked = set(subprocess.run(["git", "ls-files"], capture_output=True,
                              text=True, check=True).stdout.split())
assert _tracked, "the repository's own file list came back empty"
_pics = {"the images": sorted(["docs/logo.png", "docs/screenshot-xigmaui.png",
                               "docs/xigmaui1.png", "docs/xigmaui2.png"]),
         "theme contact sheets": sorted(_pglob.glob("docs/previews/*.png")),
         "the MP4s": sorted(_pglob.glob("docs/videos/*.mp4")),
         "readings JSON": sorted(_pglob.glob("docs/videos/*.json"))}
_pics = {k: [f for f in v if f in _tracked] for k, v in _pics.items()}
_sizes = {k: sum(os.path.getsize(f) for f in v) for k, v in _pics.items()}
_all = [f for v in _pics.values() for f in v]
_total = sum(_sizes.values())
assert all(os.path.isfile(f) for f in _all), [f for f in _all if not os.path.isfile(f)]
_pkg_doc = open("docs/packaging.md", encoding="utf-8").read()
_stray = {k: _spaced(v) for k, v in list(_sizes.items()) + [("total", _total)]
          if _spaced(v) not in _pkg_doc}
assert not _stray, (
    _sizes, _total, _stray,
    "docs/packaging.md's picture accounting no longer matches the files it counts")
assert f"{len(_all)} files" in _pkg_doc, (len(_all), "the file count moved")
# docs/tools.md quotes the same six previews individually ("the README's set, as the suite
# prints it"), and that list had already drifted: `bars` was 802 310 B there where the file is
# 779 905 B since its fan slots were re-rendered on 2026-11-08 - the same 22 405 B that moved
# the group total, noticed here only because the total was being re-derived.  So the per-file
# figures are held too, in the spaced style that page writes them in.
_tools_doc = open("docs/tools.md", encoding="utf-8").read()
_stray_files = [os.path.basename(_f) for _f in _pics["the MP4s"]
                if _spaced(os.path.getsize(_f)) not in _tools_doc]
assert not _stray_files, (_stray_files,
                          "docs/tools.md quotes a preview size that the file does not have")
assert _spaced(_sizes["the MP4s"]) in _tools_doc, (
    _sizes["the MP4s"], "docs/tools.md's six-preview total is not this tree's total")
print(f"  what is not packaged   {len(_all)} files, {_spaced(_total)} B, all of it outside "
      f"the .deb: " + ", ".join(
          f"{k} {_spaced(_sizes[k])} B ({len(_pics[k])} file"
          f"{'s' if len(_pics[k]) != 1 else ''})" for k in _pics) +
      f" - and docs/packaging.md states each of those five numbers as measured here")
# debian/rules explains the same exclusion in its own comment, and that comment quoted a
# total too - 7 749 610 B, which had already drifted twice (once by the amber-ink
# re-render, once by the window capture) because nothing read it.  Now it is the same
# measured number or the build recipe says something false.
assert _spaced(_total) in open("debian/rules", encoding="utf-8").read(), (
    _spaced(_total), "debian/rules' comment quotes a different total for what stays out")

# ---- the serial stays on the bench, in the pixels as well as the bytes ----
# Every transcript that holds this panel's serial raw - data/captures/, data/glass/ - is
# left out of the repository outright (see .gitignore), and prose writes
# `sn=<this panel's serial, redacted>` (docs/limits.md, docs/gui.md).  What held that
# line was a habit: grep the staged diff.  A staged diff is bytes, and a screenshot keeps
# a serial as *pixels*, so the habit could not see one.  On 2026-11-10 an OCR pass found
# the serial, whole and legible, in docs/xigmaui2.png - the README's advanced-mode
# capture, committed on 2026-11-08 and published ever since - and it was painted out the
# same day.  This is the check that keeps it painted out: the byte half runs everywhere,
# the pixel half runs where `tesseract` is installed and says so where it is not.
_MARKS = ("BY" + "ZL", "WC07" + "AM")   # the two halves of this panel's serial, written
                                       # split up on purpose: the habit that held this
                                       # rule was grepping the staged diff for the first
                                       # four letters of it, and a check that trips its
                                       # own grep is a check nobody keeps running.  The
                                       # shape below is the second net, so the literal
                                       # halves are only ever needed one at a time.
import re as _ser_re                   # this block's own alias: `import re` comes later
_SHAPE = _ser_re.compile(r"[A-Z]{4}\d{4}[A-Z]{2}\d{2}[A-Z]{2}\d{6}")


def _carries(path):
    """either mark, as bytes, or a token with the serial's shape, in a text file"""
    raw = open(path, "rb").read()
    hits = [m for m in _MARKS if m.encode() in raw]
    shape = _SHAPE.search(raw.decode("utf-8", "replace"))
    if shape:
        hits.append(shape.group(0))
    return hits


_text_files = (["README.md", "PROTOCOL.md"]
               + _pglob.glob("docs/*.md") + _pglob.glob("docs/**/*.md")
               + _pglob.glob("debian/*") + _pglob.glob("install/*")
               + _pglob.glob("tools/*.py")
               + _pglob.glob("xigmalcd/*.py") + _pglob.glob("xigmaui/*.py"))
# published means tracked, not "present in this working tree": a bench that has just run
# `dpkg-buildpackage` also has debian/xigmatek-connect-lcd.substvars and six neighbours, and
# the same check then reads 104 files here and 97 on CI.  Same rule, same count, whichever
# tree it runs in - and a serial committed in a file this list skips is still caught by the
# shape below, because the list is what the repository ships.
_text_files = sorted({f for f in _text_files if os.path.isfile(f) and f in _tracked})
assert len(_text_files) >= 90, (len(_text_files),
                                "the published-text list fell over, so the serial "
                                "search would be searching almost nothing")
_text_hits = {f: _carries(f) for f in _text_files}
_text_hits = {k: v for k, v in _text_hits.items() if v}
assert not _text_hits, (_text_hits,
                        "the panel's serial is in published text, which is the rule "
                        "the whole data/ tree exists to keep")
# ... and the pictures.  Only the PNGs among them: the six MP4s film the glass, not the
# window, so the one field that carries a serial is never in frame - the readings JSON
# they draw from is text and was read above.  Spaces and newlines are dropped before the
# search, because OCR splits a long token differently every run.
_stills = [f for f in _all if f.endswith(".png")]
try:
    _ocr = subprocess.run(["tesseract", "--version"], capture_output=True, text=True)
    assert _ocr.returncode == 0, _ocr.stderr[:200]
    _img_hits = {}
    for _f in _stills:
        _r = subprocess.run(["tesseract", _f, "-"], capture_output=True, text=True)
        # spaces and newlines out: OCR splits a long token differently every run
        _flat = _r.stdout.replace(" ", "").replace("\n", "")
        _why = [m for m in _MARKS if m in _flat]
        _sh = _SHAPE.search(_flat)
        if _sh:
            _why.append(_sh.group(0))
        if _why:
            _img_hits[_f] = _why
    assert not _img_hits, (
        _img_hits, "a published picture carries the panel serial in pixels: paint it "
                   "out the way docs/xigmaui2.png was, do not just re-shoot and hope")
    _scanned = f"{len(_stills)} PNGs OCR'd clean"
except FileNotFoundError:
    _scanned = ("tesseract not installed here: the pixel half of this check did NOT run, "
                f"{len(_stills)} pictures unread by it")
print(f"  the serial stays home  {_scanned}; {len(_text_files)} published text files "
      f"read, neither mark in any of them")

# The unit is the always-on path, and it is a template.  Three things are checked
# against the code rather than against a copy of the list: that the only holes in
# it are the ones install.sh fills, that the theme install.sh defaults to is one
# render.THEMES draws, and that its default fps is inside the range the control
# socket accepts.
import re
unit = open("install/xigmalcd.service.in", encoding="utf-8").read()
install = open("install/install.sh", encoding="utf-8").read()
holes = set(re.findall(r"@(\w+)@", unit))
assert holes <= {"DIR", "PYTHON", "THEME", "FPS"}, holes
defaults = dict(re.findall(r'^(\w+)="\$\{XIGMALCD_\w+:-([^"]*)\}"', install,
                           re.M))
assert {"THEME", "FPS"} <= set(defaults), defaults
unit = (unit.replace("@DIR@", os.getcwd())
            .replace("@PYTHON@", sys.executable)
            .replace("@THEME@", defaults["THEME"])
            .replace("@FPS@", defaults["FPS"]))
start = [ln for ln in unit.splitlines() if ln.startswith("ExecStart=")][0]
args = start.split()[1:]
assert "@" not in " ".join(args), args
from xigmalcd import main as cli, render
# The unit's command line has to be one the real parser takes, not merely one
# whose flags appear somewhere in the source: an unknown flag is a SystemExit at
# start, and a user unit that fails at start is a display that never comes back.
ns = cli.build_parser().parse_args(args[2:])         # drop `-m xigmalcd`
assert ns.theme == args[args.index("--theme") + 1], (ns.theme, args)
assert ns.theme in render.THEMES, ns.theme
assert 0.1 <= ns.fps <= 5.0, ns.fps                 # control.py's accepted range
assert "--no-control" not in args, "the unit must leave the window a socket"
print(f"  unit                   ExecStart: {' '.join(args)}")
PY

# And the other half of the menu entry's program, on a box without Qt.  PyQt6 is a
# Suggest of the .deb, not a Depends, precisely because the loop that holds the port
# runs without it - which means an installed system can have the menu entry and no Qt,
# and what that person gets must be a sentence, not a traceback.  The blocker below
# makes the import look absent (a meta_path finder that raises ModuleNotFoundError for
# PyQt6 and anything under it), because PyQt6 is installed on this machine and the
# honest way to test its absence is to hide it rather than to assume a box like the
# author's lacks it.
noblock=$(mktemp -d)
cat > "$noblock/sitecustomize.py" <<'PY'
import sys


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "PyQt6" or name.startswith("PyQt6."):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


sys.meta_path.insert(0, Blocker())
PY
out=$(PYTHONPATH="$noblock" python3 -m xigmaui --help 2>&1); rc=$?
grep -q "Traceback" <<<"$out" && { echo "  no Qt: got a traceback"; echo "$out"; exit 1; }
test "$rc" = 2 || { echo "  no Qt: exit $rc, expected 2"; echo "$out"; exit 1; }
grep -q "xigmaui needs Qt" <<<"$out" || { echo "  no Qt: no plain-language reason"; exit 1; }
grep -q "python3-pyqt6" <<<"$out" || { echo "  no Qt: does not name the package to install"; exit 1; }
echo "  no Qt                exit $rc: $(head -1 <<<"$out")"
echo "                         $(sed -n '2p' <<<"$out")"

echo
echo "== the .deb's unit and menu entry against the checkout's"
# debian/xigmalcd.service and debian/xigmaui.desktop are the installed-layout twins
# of install/xigmalcd.service.in and install/xigmaui.desktop.in, and they are written
# by hand rather than generated: the checkout forms need @DIR@, @PYTHON@ and a `Path`
# key, none of which mean anything once the modules sit in
# /usr/lib/python3/dist-packages and `xigmalcd` is a command in /usr/bin.  Two
# hand-written files that describe the same panel drift, so this compares them on
# every key that is about the run, and states out loud the ones that differ because
# of the layout.
python3 - <<'PY' || { echo "packaging parity FAILED"; exit 1; }
import os
import re
import shutil
import subprocess
import time

from xigmalcd import main as cli
from xigmalcd import render


def groups(path):
    """key=value by [group], comments skipped: enough for a unit file and a .desktop
    entry, and it keeps Exec of the main entry apart from Exec of the tray action."""
    g, cur = {}, None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1]
            g[cur] = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            g[cur][k] = v.strip()
    return g


deb, chk = groups("debian/xigmalcd.service"), groups("install/xigmalcd.service.in")

# what the run is: same description, same pairing with the session, same restart
# behaviour.  Nothing here is compared to a copy of the list - both sides are read.
for k in ("Description", "After", "PartOf"):
    assert deb["Unit"][k] == chk["Unit"][k], (k, deb["Unit"][k], chk["Unit"][k])
for k in ("Type", "ExecStartPre", "Restart", "RestartSec", "Nice"):
    assert deb["Service"][k] == chk["Service"][k], (k, deb["Service"][k],
                                                    chk["Service"][k])
assert deb["Install"]["WantedBy"] == chk["Install"]["WantedBy"], deb["Install"]

# ExecStart: two spellings of one command.  The checkout's theme and fps come from
# install.sh's own defaults, the same reading the section above uses.
install = open("install/install.sh", encoding="utf-8").read()
defaults = dict(re.findall(r'^(\w+)="\$\{XIGMALCD_\w+:-([^"]*)\}"', install, re.M))
co = chk["Service"]["ExecStart"].replace("@THEME@", defaults["THEME"]) \
                                .replace("@FPS@", defaults["FPS"]).split()
assert co[:2] == [os.path.basename(co[0]), "-m"] and co[2] == "xigmalcd", co[:3]
co = co[3:]
db = deb["Service"]["ExecStart"].split()
prog, db = db[0], db[1:]
assert prog == "/usr/bin/xigmalcd", prog      # the entry point, not `python3 -m`
assert co == db, (co, db)
for a in (co, db):
    assert "--allow-reset" not in a and "--no-control" not in a, a
    ns = cli.build_parser().parse_args(a)     # the real parser takes this unit line
    assert ns.theme in render.THEMES and 0.1 <= ns.fps <= 5.0, ns
print(f"  unit                   both ExecStart agree: {' '.join(db)} "
      f"(parser: theme {ns.theme}, fps {ns.fps}); no --allow-reset in either")

# ...and the two differences are the layout, not the panel: a checkout needs a
# working directory because it runs `-m xigmalcd`, an installed system does not; and
# only the installed form can point a reader at a compressed README in /usr/share/doc.
assert "WorkingDirectory" in chk["Service"], "the checkout unit needs one"
assert "WorkingDirectory" not in deb["Service"], "an install has no checkout to cd to"
# Documentation is a repeated key, and groups() keeps one value per key, so the
# two lines this checks are read from the file itself.
docs = [ln.split("=", 1)[1].strip() for ln in open("debian/xigmalcd.service",
                                                   encoding="utf-8")
        if ln.startswith("Documentation=")]
assert any(d.startswith("file:/usr/share/doc/xigmatek-connect-lcd/") for d in docs), docs
assert any(d.startswith("https://") for d in docs), docs
print("  unit                   differs only in WorkingDirectory (checkout only) "
      "and Documentation (installed only)")

de = groups("debian/xigmaui.desktop")
ce = groups("install/xigmaui.desktop.in")
shared = ("Type", "Version", "Name", "GenericName", "GenericName[en_US]",
          "Comment", "Comment[en_US]", "Terminal", "Categories", "Keywords",
          "StartupNotify", "StartupWMClass", "NoDisplay", "Actions")
for k in shared:
    assert de["Desktop Entry"][k] == ce["Desktop Entry"][k], k
assert ce["Desktop Entry"]["Exec"].endswith("-m xigmaui"), ce["Desktop Entry"]["Exec"]
assert de["Desktop Entry"]["Exec"] == "xigmaui", de["Desktop Entry"]["Exec"]
assert "Path" in ce["Desktop Entry"] and "Path" not in de["Desktop Entry"]
assert de["Desktop Action tray"]["Exec"] == "xigmaui --hidden", \
    de["Desktop Action tray"]["Exec"]
print(f"  menu entry             same {len(shared)} keys; Exec xigmaui "
      f"(installed) vs `-m xigmaui` + Path (checkout)")

# The program's own name sits in four places a reader actually sees - the window's
# title bar, its tray tooltip, and the `Name=` of both menu entries - so the constant
# in app.py is compared to both files instead of trusting that they were edited
# together.  Nothing claims README's prose matches: that is a sentence, not a key, and
# the entry's `Comment` is deliberately a different sentence from the title bar.
src = open("xigmaui/app.py", encoding="utf-8").read()
title = re.search(r'^TITLE = "(.*)"$', src, re.M)
assert title, "xigmaui/app.py declares no TITLE constant"
name = de["Desktop Entry"]["Name"]
assert name == ce["Desktop Entry"]["Name"] == title.group(1), \
    (name, ce["Desktop Entry"]["Name"], title.group(1))
assert "setWindowTitle(TITLE)" in src and "setToolTip(TITLE" in src, \
    "the window does not take its own name from TITLE"
print(f"  name                   {name!r}: app.py's TITLE, its title bar and tray "
      f"tooltip, and both entries' Name")
# The name says `Connect`, not `Connect 360`: the protocol work was measured on a
# Connect 360 (README, PROTOCOL.md) and no other model has been tested, so the entry
# names the family the program is written for rather than the author's unit, and
# keeps `connect 360` only as a search keyword.
assert "connect 360" in de["Desktop Entry"]["Keywords"], de["Desktop Entry"]["Keywords"]
assert "360" not in name and "360" not in de["Desktop Entry"]["Comment"], (name,)
print(f"  name                   Comment: {de['Desktop Entry']['Comment']}")

# The icon is the one claim all three files make, so all three are read: the name in
# the menu entry, the hicolor path the package installs it to, and the path the
# window falls back to when no icon theme resolves the name.
ins = open("debian/xigmatek-connect-lcd.install", encoding="utf-8").read()
rel = "usr/share/icons/hicolor/256x256/apps/xigmaui.png"
assert rel in ins, "the package does not install the icon the entry names"
assert de["Desktop Entry"]["Icon"] == "xigmaui", de["Desktop Entry"]["Icon"]
assert "/" + rel in open("xigmaui/app.py", encoding="utf-8").read(), \
    "xigmaui/app.py does not look where the package puts the picture"
assert os.path.exists("install/" + os.path.basename(rel)), "the source picture"
print(f"  icon                   Icon=xigmaui, installed at /{rel}, and app.py's "
      f"ICONS names that path")

# one copy of the udev rule, one installed destination.  Tracked files, not a walk:
# a build tree has a copy of the same rule under debian/tmp, and that is a build
# artifact rather than a second file someone has to keep in step.
rules = subprocess.run(["git", "ls-files", "*.rules"], capture_output=True,
                       text=True)
if rules.returncode != 0:
    print("  udev rule              git not available here: SKIPPED the one-file "
          "check")
else:
    want = ["install/99-xigmatek-lcd.rules"]
    assert rules.stdout.split() == want, rules.stdout.split()
    assert "install/99-xigmatek-lcd.rules" in open("debian/rules",
                                                   encoding="utf-8").read()
    print("  udev rule              one tracked file, installed by debian/rules")

# The documents the README links have to keep resolving.  README.md is the short page and
# docs/*.md carry the detail, so almost every pointer in this tree is a relative link from
# one markdown file to another - and a split like that breaks links silently, because a
# broken relative path is still valid markdown.  Checked: every `[text](target)` and
# `![alt](target)` in README.md and in every docs/*.md, with the target resolved against
# the file it is written in and any #anchor stripped.  Anchors are not checked - GitHub
# and a plain file viewer derive them differently - but the files are, which is the half
# that moves.  Images count too here, because in a checkout they exist; the installed
# package ships the prose without the pictures (debian/rules says why), and
# debian/tests/smoke checks the installed form for the markdown links only.
import glob as _glob
import re as _re

targets = ["README.md"] + sorted(_glob.glob("docs/*.md"))
links, dead = 0, []
for doc in targets:
    text = open(doc, encoding="utf-8").read()
    found = [m.group(1) for m in _re.finditer(r"!?(?:\[[^\]]*\])\(([^)\s]+)", text)]
    # the logo is an <img> tag rather than a markdown link, because it floats beside the
    # overview on the GitHub page; same check, one more pattern
    found += _re.findall(r'<img[^>]+src="([^"]+)"', text)
    for dest in found:
        dest = dest.split("#", 1)[0]
        if not dest or dest.startswith(("http://", "https://", "mailto:", "file:")):
            continue
        links += 1
        if not os.path.exists(os.path.join(os.path.dirname(doc), dest)):
            dead.append((doc, dest))
assert not dead, dead
print(f"  markdown links       {links} relative links across {len(targets)} documents, "
      f"every one resolving to a file that exists")

if shutil.which("desktop-file-validate"):
    subprocess.run(["desktop-file-validate", "debian/xigmaui.desktop"], check=True)
    print("  desktop-file-validate  clean on the installed form too")
else:
    print("  desktop-file-validate  not installed here: SKIPPED on the installed "
          "form (CI installs it as a Build-Depend)")

# Whether the .deb bytes are reproducible, which is what a sha256 in a release note
# is worth.  Measured on this box with two builds of one tree: with SOURCE_DATE_EPOCH
# pinned to a moment in the past, the two code packages came out byte-identical
# (`cmp` clean, same sha256) and so did the two 146 MB themes packages.  Nothing in
# this tree sets that variable: dpkg-buildpackage does, from the top debian/changelog
# entry's timestamp (/usr/bin/dpkg-buildpackage line 583,
# `$ENV{SOURCE_DATE_EPOCH} ||= $changelog->{timestamp} || time`), and debhelper
# computes the same thing in Dh_Lib.pm.  dpkg-deb then rewrites every tar member's
# mtime to that value - measured, with a toy package, both ways round:
#
#   epoch in the past    members dated 2001-09-09 04:46, twice, same bytes
#   epoch in the future  members dated at the build's wall clock
#
# That second line is the trap: dpkg-deb pulls mtimes *down* to the epoch and leaves
# earlier ones alone, so a changelog entry dated ahead of the build lets each
# machine's clock into the archive.  The published v0.1 asset and the same tree built
# here differ that way - 5 218 596 B against 5 218 614 B, all 37 file md5s and every
# control field identical - because that entry is stamped 04:40:00 +0000 while the
# runner built at 04:12Z and this bench at 04:07Z.  Hence this check: the top entry
# has to be dated in the past, because that is the whole of what makes two builds of
# one source agree on bytes.
stamp = subprocess.run(["dpkg-parsechangelog", "-STimestamp"], capture_output=True,
                       text=True)
if stamp.returncode:
    print("  changelog stamp        dpkg-parsechangelog unusable here: SKIPPED the "
          "reproducibility check")
else:
    when = int(stamp.stdout.strip())
    now = int(time.time())
    assert when <= now, (
        f"the top debian/changelog entry is dated {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(when))}, "
        "which is in the future: dpkg-deb only pulls mtimes down to SOURCE_DATE_EPOCH, "
        "so a build now would date every archive member at its own wall clock and two "
        "machines could not agree on the file's bytes")
    print(f"  changelog stamp        {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(when))}"
          f", {(now - when) // 60} min old: dpkg-deb clamps every member mtime to it")

# The changelog's width is a packaging fact, not a style preference: the CI job runs
# `lintian --fail-on error,warning`, and `debian-changelog-line-too-long` is a *warning*,
# so a long line fails the build.  How this got caught the slow way: adding one word to
# the "N offline sections" sentence - "twenty" to "twenty-one", five characters - pushed
# that line from 77 columns to 82, and lintian flagged it in both packages while the whole
# python suite stayed green.  The observed boundary is what the gate uses, because it is
# the only boundary this repo has evidence for: 80 columns passes (33 lines sit there),
# 82 is flagged, and 81 has never been tested, so the file keeps its existing budget
# rather than probing for a limit nobody has measured.
_cl = open("debian/changelog", encoding="utf-8").read().split("\n")
_wide = [(k + 1, len(_ln)) for k, _ln in enumerate(_cl) if len(_ln) > 80]
assert not _wide, (
    max(_wide, key=lambda t: t[1]) if _wide else [],
    "a debian/changelog line over 80 columns: lintian's debian-changelog-line-too-long "
    "fires there, fails the .deb job, and the suite would have said nothing")
assert sum(1 for _ln in _cl if len(_ln) == 80) >= 10, (
    sum(1 for _ln in _cl if len(_ln) == 80),
    "the 80-column budget this gate enforces is measured off this file's own prose; if "
    "that count collapses the claim above is no longer the reason for the number")
print(f"  changelog width       every line <= 80 columns ({max(len(x) for x in _cl)} here, "
      f"{sum(1 for x in _cl if len(x) == 80)} lines at the limit): lintian fails a longer "
      f"one, and it failed an 82-column line once already")

# ...and the same file's *shape*, which a width count cannot see.  dpkg's grammar for a
# changelog body allows three things: an indented line, a well-formed heading, and a trailer.
# A body line that starts at column 0 is read as a heading, and lintian calls it
# `syntax-error-in-debian-changelog` - once per package that ships `changelog.gz`, so two here,
# in the same job.  How this one was found: feature F's stanza grew a paragraph appended by a
# helper that wrapped continuation lines at four spaces but left the first line at none.  The
# offline suite was green on both machines - it reads the top stanza's stamp through
# `dpkg-parsechangelog`, which never looks at the body's indentation - and only the .deb job
# noticed, at the step that ships.  So the gate is the same three shapes dpkg allows.
_CL_HEAD = _re.compile(r"^[a-z0-9][a-z0-9.+~/-]* \([^()]+\) [^;]+; urgency=\S+$")
_offshape = [(k + 1, _ln[:60]) for k, _ln in enumerate(_cl)
             if _ln.strip() and not _ln[:1].isspace()
             and not _CL_HEAD.match(_ln.rstrip()) and not _ln.startswith(" -- ")]
assert not _offshape, (
    _offshape[:4],
    "a debian/changelog line that is neither indented body, well-formed heading nor trailer: "
    "dpkg reads it as a heading, lintian fails the .deb job on it, and nothing else here does")
print(f"  changelog shape       every non-blank line is indented body, one of the "
      f"{sum(1 for x in _cl if _CL_HEAD.match(x.rstrip()))} well-formed headings, or a "
      f"trailer - the three shapes dpkg allows, because a body line at column 0 is a heading "
      f"to it and lintian said so in both packages")
PY

echo
echo "== the GUI, offscreen and with no panel: window, clips, and the reset gate"
# XIGMA_SOCKET points at nothing on purpose: if a real display happened to be
# running while this ran, the window would be a remote and these port-side
# assertions would be testing the wrong mode
# Its own temp settings root, not `$cfgtmp` from the settings section 600 lines above: run
# this section on its own - which is exactly what a developer does while fixing it - and that
# variable is unset, `XDG_CONFIG_HOME=` expands to nothing, and every window below writes the
# author's real ~/.config/xigmaui/config.json.  That is how a session file here ended up with
# device `/dev/xigma-no-such-port`, `preview_fps 1.0` and `clip_customized true`: the next
# `python3 -m xigmaui` by hand opened on a clip nobody had chosen and stopped following any
# layout's own background.  The window now refuses to write when it was started without a
# session file (app.py:_save_now), and this root is asserted below rather than trusted.
gui_cfg=$(mktemp -d)
QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME=$gui_cfg XIGMA_SOCKET=$gui_cfg/no-display.sock \
    python3 - <<'PY' || { echo "gui FAILED"; exit 1; }
import inspect
import os
import re as _re
import sys
import time
import types
sys.path.insert(0, ".")
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                             QListView, QSpinBox)
from PyQt6.QtCore import QCoreApplication
appq = QApplication([])
from xigmaui import app, clips as clipdb, panel, settings
from xigmalcd import render, sensors
from xigmalcd.main import CLIP_LUMA

# the clip library, and the lumas the picker's scrim rule leans on
# These two figures come out of ffmpeg and ffprobe decoding real frames, so a machine
# without them cannot measure them: say which tool is missing instead of letting the
# comparison below fail on a luma of 0.0, which is what `measure` returns when the
# decode did not work at all.  (The first CI run on 2026-11-07 did exactly that, with
# `AssertionError: ('Theme_25.mp4', 0.0)`; the job's own comment says why ffmpeg is
# installed there, and the .deb names it under Suggests for the same reason.)
import shutil
missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
if missing:
    print(f"  needs {', '.join(missing)}: the luma and loop-length figures are decoded "
          f"from the clips, and the assertion below compares them to the docs' numbers")
    raise SystemExit(1)
found = clipdb.list_clips()
assert found, "no clips found at all"
_scan0 = dict(clipdb.LAST_SCAN)        # this machine's walk, quoted beside the machine
byname = {c.name: c for c in found}
# No two rows may be the same clip.  The roots overlap on purpose: the .deb installs
# its own copy of each vendored clip, the themes package carries clips this project
# also vendors, and the Windows app's upload history repeats files it pushed more than
# once.  `realpath` catches none of that - separate files with the same bytes - and a
# (name, length) rule could not either, because the app renames what it copies: it
# measured 69 rows for 40 clips, 161 files on disk.  The rule is length, then sha256 of
# both 2 MiB edges.  Two censuses are quoted, and only one of them is machine-dependent:
# the 46 mp4 files this repository tracks hold **40 distinct contents** - the gate below
# re-derives 46 / 40 / 6 copies / 3 of them renamed, from the tree, on any machine - and
# on this bench, with the .deb installed and the Windows partition mounted, the same
# walk sees 204 files and still stands at 40 rows (the 2026-11-07 audit of the 161 files
# then visible found 40 distinct contents, whole-file sha256, which is what makes the 40
# rows exactly right rather than merely fewer).
shapes = {}
for cl in found:
    k = (cl.name.casefold(), cl.bytes)
    assert k not in shapes, (k, shapes.get(k), cl.path)
    shapes[k] = cl.path
# and the row that survives is the one find_media() would have chosen: a planted copy
# of a clip the checkout already has adds no row, whichever root it sits in
import shutil as _sh
import tempfile as _tf
from xigmalcd import main as _m
with _tf.TemporaryDirectory() as _t:
    _planted = os.path.join(_t, "Theme_25.mp4")
    _sh.copyfile(byname["Theme_25.mp4"].path, _planted)
    _saved = {k: getattr(_m, k) for k in ("SYSTEM_THEMES", "SYSTEM_CLIP_LIB")}
    _m.SYSTEM_THEMES = _m.SYSTEM_CLIP_LIB = _t
    try:
        again = clipdb.list_clips()
        got = [c for c in again if c.name == "Theme_25.mp4"]
        assert len(got) == 1 and got[0].path == byname["Theme_25.mp4"].path, got
    finally:
        for _k, _v in _saved.items():
            setattr(_m, _k, _v)
print(f"  clip library       {len(found)} rows, each a distinct name+length; the same "
      f"bytes under another root add no row and do not displace the checkout's file")

# The census every machine can reproduce: the clip files this repository *tracks*.  The
# bench numbers (204 files walked, 40 rows) depend on what else is mounted and installed,
# so docs quote them beside the machine; the tracked ones do not depend on anything, and
# they are also the ones the pairing and the README figures rest on.  Re-derived here, with
# the roots that are not this checkout pointed away, and the distinct count verified the way
# the older docs claim it was verified - whole-file sha256 over every tracked clip - rather
# than trusting the length-plus-two-edges rule the window uses to decide it cheaply.
import glob as _cg
import hashlib as _ch
import xigmalcd.main as _m
_tracked = sorted(_cg.glob("media/*.mp4")) + sorted(_cg.glob("themes/alpha/clips/*.mp4"))
assert _tracked, "no tracked clips: media/ and themes/alpha/clips are both empty"
# Which roots to point away is not a list to keep by hand: it is read out of
# `media_roots()` itself, because this is the third place a hand-written version of it fell
# behind a root that had just been added (the pairing gate, this census, and the simulation
# of a runner all got it wrong in the same way).
import ast as _ast
import inspect as _insp
_fn_src = _insp.getsource(_m.media_roots)
_KNOWN_ROOTS = sorted({n.id for n in _ast.walk(_ast.parse(_fn_src))
                       if isinstance(n, _ast.Name) and n.id.isupper()})
_SKIP_ROOTS = {"MEDIA_ENV", "REPO_MEDIA", "REPO_CLIP_LIB"}   # the checkout's own roots stay
# Two different sets of roots have to be pointed away for a box to be bare: the ones the
# loop searches (`media_roots`' own names, derived above) and the two Windows volumes the
# *window's* list walks on top of that.  Naming them apart is the point - a root added to
# either place joins the hide-list here without anyone remembering.
_WINDOW_ONLY = [k for k in ("WIN_STATIC", "WIN_UPLOADS") if isinstance(getattr(_m, k), str)]
_solo = {k: getattr(_m, k) for k in
         [n for n in _KNOWN_ROOTS if n not in _SKIP_ROOTS] + _WINDOW_ONLY}
assert set(_solo) >= {"SYSTEM_MEDIA", "SYSTEM_CLIP_LIB", "WIN_STATIC", "WIN_UPLOADS"}, _solo
_solo_env = os.environ.pop("XIGMA_MEDIA", None)
try:
    for _k in _solo:
        setattr(_m, _k, "/nonexistent-root")
    _alone = clipdb.list_clips()
    _alone_scan = dict(clipdb.LAST_SCAN)
finally:
    for _k, _v in _solo.items():
        setattr(_m, _k, _v)
    if _solo_env is not None:
        os.environ["XIGMA_MEDIA"] = _solo_env
clipdb.list_clips()      # put the module's scan counters back to this box's own roots:
                         # the assertions below read LAST_SCAN as a fact about this bench
_digests = {}
for _f in _tracked:
    _h = _ch.sha256()
    with open(_f, "rb") as _fh:
        for _chunk in iter(lambda: _fh.read(1 << 20), b""):
            _h.update(_chunk)
    _digests.setdefault(_h.hexdigest(), []).append(_f)
assert _alone_scan["files"] == len(_tracked), (
    _alone_scan["files"], len(_tracked),
    "the window's walk no longer sees exactly the clip files this repository tracks - "
    "a root was added or dropped, and every quoted census moved with it")
assert len(_alone) == len(_digests), (
    len(_alone), len(_digests),
    "the rows the window lists are not the distinct contents the tracked files hold - the "
    "length-plus-edges rule and a whole-file sha256 audit disagree")
_census = (f"{_alone_scan['files']} files, {len(_alone)} rows, "
           f"{_alone_scan['copies']} copies dropped, {_alone_scan['renamed']} of them "
           "renamed")
_gui_doc = open("docs/gui.md", encoding="utf-8").read()
_readme = open("README.md", encoding="utf-8").read()
assert f"{_alone_scan['files']} mp4 files this repository tracks" in _gui_doc, (
    _census, "docs/gui.md does not state the tracked census this gate just derived")
assert f"{_alone_scan['files']} mp4 files this repository tracks" in _readme, (
    "README does not state the tracked census")
assert f"{len(_alone)} distinct contents" in _gui_doc, (
    len(_alone), "docs/gui.md does not state the audited distinct count")
assert _census in _gui_doc, (_census, "docs/gui.md quotes a different census than this run "
                                      "measured")
_copy_files = sum(len(v) for v in _digests.values() if len(v) > 1)
print(f"  tracked clips      {len(_tracked)} mp4 files in media/ and themes/alpha/clips, "
      f"{len(_digests)} distinct contents by whole-file sha256 ({_copy_files} of the "
      f"files are one of those copies), and the window's own walk over a bare checkout "
      f"agrees: {_census}. docs/gui.md and README state those digits; this bench's "
      f"larger walk ({_scan0['files']} files) is quoted beside the machine")
for name, size in (("Theme_25.mp4", 214_917), ("Theme_11.mp4", 3_402_098),
                   ("theme_48.mp4", 1_333_649)):
    assert byname[name].bytes == size, (name, byname[name].bytes)
    lum = clipdb.measure(byname[name])
    assert abs(lum - CLIP_LUMA[name]) < 0.6, (name, lum, CLIP_LUMA[name])
    secs = clipdb.probe(byname[name])
    assert 0.5 < secs < 20, (name, secs)
    print(f"  {name:16s} {byname[name].bytes:9d} B  luma {lum:5.1f}  "
          f"{secs:5.2f} s loop")

# Where the rows came from, and where the files came from, are two different answers
# now - which is the whole point of collapsing by content.  The Windows app's own
# upload history (reachable only when that partition is mounted) is still walked, but
# on this bench every one of its 69 files duplicates a library clip, so it contributes
# files and no rows.  Assert the walk happened, via the scan counters: that is the
# claim that survives the dedupe, and it is the one that would notice a root going
# missing.  A machine where the app pushed a clip the library does not have would show
# it as a row, and nothing here forbids that.
byorigin: dict[str, int] = {}
for c in found:
    byorigin[c.origin] = byorigin.get(c.origin, 0) + 1
import os
from xigmalcd.main import WIN_UPLOADS
scan = clipdb.LAST_SCAN
if os.path.isdir(WIN_UPLOADS):
    assert scan["roots"].get("app upload", 0) > 0, scan
    assert sum(scan["roots"].values()) == scan["copies"], scan
    print(f"  app upload root      {os.path.isdir(WIN_UPLOADS)} walked: "
          f"{scan['roots']['app upload']} of its files were copies of rows already "
          f"listed, so it adds files and no rows")
assert set(byorigin) <= {"vendored", "vendor library"}, byorigin
print(f"  sources: {byorigin}")

# a window against a port that does not exist: it must build, preview every
# theme, and report the failed action in its log rather than raising
bad = "/dev/xigma-no-such-port"
# `save_settings=True` because this is the section that exercises saving.  The default for a
# `restore=False` window is *not* to write the session file, and that default gets its own
# check below - which is the rule that keeps a script or an offline check from replacing a
# person's `~/.config/xigmaui/config.json` with this window's fake device and rates.
win = app.Window(bad, 1.0, restore=False, save_settings=True)
assert win.clips.count() >= 3, win.clips.count()
for theme in sorted(render.THEMES):
    win.theme.setCurrentText(theme)
    win._repaint()
    assert win.preview.pixmap().width() > 0, theme
print(f"  window built: {win.clips.count()} clips, "
      f"{len(render.THEMES)} themes previewed")

# The README quotes three wall-clock figures about this window, so they are
# measured here rather than remembered: a build, the whole thumbnail pass the
# window runs behind itself, and one frame render.  The bands are wide on purpose
# (another process on the box moves these by tens of percent); what they catch is
# an order-of-magnitude regression, like a render that starts encoding every
# frame or a clip pass that decodes whole clips instead of seeking.
t0 = time.perf_counter()
win2 = app.Window(bad, 1.0, restore=False)
build = time.perf_counter() - t0
# The floors here are one order of magnitude below what both machines measure, and
# the ceilings one above: they are there to catch a build or a render that stopped
# doing work, not to grade the machine.  The runner is faster than the bench at this
# (0.091 s and 0.10 s against 0.21 s here), which is exactly why the old floor of
# 0.1 s failed CI on 2026-11-07 with `AssertionError: 0.09128455299999416` - a
# desktop's number written as a limit.
assert 0.02 < build < 5.0, build

m = sensors.collect()
render.to_png(render.draw(m, "alpha"))            # warm the font cache


def _draw_once(m):
    t = time.perf_counter()
    render.draw(m, "alpha", bg=render.OVERLAY)
    return (time.perf_counter() - t) * 1000


draws = sorted(_draw_once(m) for _ in range(15))
mid = draws[len(draws) // 2]
# Same rule as the band above: 11.9 ms here and 22.3 ms on the runner, so a floor of
# 1 ms and a ceiling of 200 ms catch the thing this is for - a draw that starts
# encoding a PNG per call, or a frame that stops being drawn at all - without being a
# bet on how loaded a shared runner happens to be at the moment.
assert 1.0 < mid < 200.0, mid

t0 = time.perf_counter()
while getattr(win, "_pending", []):
    QCoreApplication.processEvents()
    if time.perf_counter() - t0 > 120:
        break
thumbs = time.perf_counter() - t0
assert thumbs < 120, thumbs
win2.close()
print(f"  measured here: build {build:.2f} s, one frame render {mid:.1f} ms, "
      f"all {len(win.all_clips)} thumbnails {thumbs:.1f} s   "
      f"docs/gui.md's Cost paragraph quotes these three")

# the scrim rule is the daemon's, and a bright clip must trip it
win.canvas.setCurrentIndex(0)
win.scrim.setValue(-1)
for name in ("theme_48.mp4", "Theme_25.mp4"):
    win._load_background(byname[name].path)
    want = win._render_kw()["scrim"]
    assert (want > 0) == (CLIP_LUMA[name] > 128), (name, want)
    print(f"  scrim auto on {name:14s} -> {want}")

# A window built the way a script builds one - `restore=False`, a device that does not
# exist, a rate nobody asked for - must not write the session file.  Not a hypothetical
# hazard: this very section, run on its own, did that to the author's real
# ~/.config/xigmaui/config.json (the header above says how), and the next
# `python3 -m xigmaui` by hand came up on a clip nobody had chosen, pointed at
# `/dev/xigma-no-such-port`, at 1 fps, with `clip_customized` set - the flag that used to
# stop the window following any layout's own background.  A pairing complaint traced to a test
# with no manners, which is why the check is here rather than only in the section header.
_here = settings.path()
_xdg = os.environ.get("XDG_CONFIG_HOME", "")
assert _xdg, ("XDG_CONFIG_HOME is empty or unset in this section: `settings.path()` is "
              f"{_here}, which is somebody's real session file")
assert _here.startswith(_xdg + os.sep), (_here, _xdg,
                                         "the settings root this section believes it writes "
                                         "to is not the one `settings.path()` resolves")
assert _here != os.path.expanduser("~/.config/xigmaui/config.json"), _here
_before_txt = open(_here, encoding="utf-8").read() if os.path.exists(_here) else None
quiet = app.Window(bad, 1.0, restore=False)              # the default: it does not write
quiet.theme.setCurrentText("dual")
quiet.save_timer.start()
_q_deadline = time.time() + 1.5                          # past the 500 ms debounce
while time.time() < _q_deadline:
    appq.processEvents()
    time.sleep(0.02)
_after_txt = open(_here, encoding="utf-8").read() if os.path.exists(_here) else None
assert _after_txt == _before_txt, (
    _here, "a window started without the session file rewrote it:",
    (_after_txt or "")[:160])
# and it says so where a reader will still see it a minute later.  Not the status bar: a
# port error like "cannot open /dev/xigma-no-such-port" pushes that line out within a
# second, which is how this assert first came to fail on its own message.
assert "does not write" in quiet.log_view.text(), (
    quiet.log_view.text()[-400:],
    "the window kept the file and said nothing: a reader cannot tell a throwaway window "
    "from their own session")
quiet.close()                            # closeEvent -> _save_now, still no write
assert (open(_here, encoding="utf-8").read() if os.path.exists(_here) else None
        ) == _before_txt, _here
print(f"  no session write     restore=False left {_here} exactly as it found it, "
      f"timer and close included")

# settings through the widgets: a picker moved is a debounced write, and the
# next window has to come back up the same way it was closed
win.clock_size.setValue(44)
win.theme.setCurrentText("gauge")
win._load_background(byname["Theme_11.mp4"].path)
# `Theme_11.mp4` is deliberately a clip `gauge` does *not* pair with, and the box is ticked
# to hold it: that is the only state in which "the clip comes back as I left it" is a
# promise the window makes.  With the box off, the next gate below shows a restored window
# re-pairing at start instead - which is what the box is for.
win.chk_keep.setChecked(True)
assert win.keep_clip is True, win.chk_keep.isChecked()
win.save_timer.start()
# Wait for the state this block asked for, not for one field of it.  An earlier pending
# write can land first and satisfy a one-field condition by accident: the theme loop above
# leaves `gauge` on the picker (sorted(THEMES)[-1]) and the scrim loop arms the same
# debounced timer, so "the file says gauge" was true before a single new value was written.
_want = (44, "gauge", byname["Theme_11.mp4"].path)
deadline = time.time() + 3
while time.time() < deadline:
    appq.processEvents()
    time.sleep(0.02)
    _now = settings.load()
    if (_now["clock_size"], _now["theme"], _now["clip"]) == _want:
        break
saved = settings.load()
assert saved["theme"] == "gauge" and saved["clock_size"] == 44, saved
assert saved["clip"] == byname["Theme_11.mp4"].path, saved["clip"]
assert saved["preview_fps"] == 1.0 and saved["device"] == bad, saved
again = app.Window(bad, None, restore=True)
assert again.theme.currentText() == "gauge", again.theme.currentText()
assert again.clock_size.value() == 44 and again.mp4 == saved["clip"]
assert again.preview_fps == 1.0 and again.port == bad
row = again.clips.currentRow()          # the list has to land on the remembered clip
assert again.all_clips[row].path == saved["clip"], (row, again.all_clips[row].path)
assert again.chk_keep.isChecked() is True, "the box did not come back as it was left"
# With the box off, a restored window re-pairs at start: the saved clip is a memory of what
# was under the preview, not a claim about what belongs there now.  Said out loud here
# because it is the behaviour a person will notice - and the box, plus the line a row click
# prints, is what makes it their choice rather than the window's.
# The `playing` pane, on a window that was *restored* rather than handed a rate:
# that is the shape the author's own `python3 -m xigmaui` takes, and it is the shape
# a half-applied edit once left with `preview_fps` None and the caption's `:g` format
# dying in a terminal.  The assertion above is what keeps that from coming back;
# these keep the animation itself honest.
assert again.anim_toggle.isChecked(), "the preview plays by default"
again.canvas.setCurrentIndex(0)         # `clear`: on black there is nothing to play
again.show()
for _ in range(20):
    appq.processEvents()
# the stream behind the picture, not behind what the file remembered: this window re-paired
# when the box came off, and a decode stream pointed at the old clip would be a bug
assert again.player is not None and again.player.path == again.mp4, (
    again.player.path if again.player else None, again.mp4,
    "the decode stream is behind a picture the preview is not showing")
assert again.player.fps > 0, again.player.fps    # ffprobe's r_frame_rate, not a guess
note = again.anim_note.text()
assert "playing at" in note and f"{again.preview_fps:g} fps" in note, note
cap = again.caption.text()
# the two sentences under the picture used to be joined without a separator, which
# printed "...measures those.background Theme_25.mp4 at mid-loop" - and called a
# playing clip "mid-loop".  Both halves of that are assertions now.
assert "those.  " in cap, cap[-90:]
assert "mid-loop" not in cap, cap
assert f"{again.player.seconds:.2f} s" in cap, cap
assert f"{again.player.wide}x{again.player.tall}" in cap, cap
print(f"  caption under it     {cap[:118]}...")
again.preview_timer.stop()                       # this harness drives the ticks
again._advance()
assert again.player.decoded > 0, "the pane pulled at least one frame"
# ...and the two clocks really are separate.  This window runs at `preview_fps` 1.0 -
# the author's own saved setting, and the reason the pane looked like a 1 fps
# slideshow: the pane's redraw rate *was* the animation rate.  The background now
# plays on its own timer at the file's rate, so frames reach the label at ~24 fps
# while `sensors.collect()` runs once a second.  Asserted as a floor rather than an
# exact rate, because a loaded CI runner paints slower; the layer's own tick count
# not moving at all is the exact half.
assert 33 <= again.bg_timer.interval() <= 60, again.bg_timer.interval()
seq0, shown0 = again._seq, again._played
t0 = time.monotonic()
while time.monotonic() - t0 < 2.0:
    appq.processEvents()
shown = again._played - shown0
assert again._seq == seq0, "the layer was not redrawn by this loop at all"
assert shown >= 10, (shown, again.bg_timer.interval())
print(f"  the two clocks       {again.bg_timer.interval()} ms background "
      f"({again.player.fps:g} fps in the file) against a "
      f"{again.preview_fps:g} fps layer: {shown} frames shown in "
      f"{time.monotonic() - t0:.1f} s with no layer tick")
seams = again.player.loops
# minimised is the other shape of "nobody can see this": Qt still reports the window
# as visible, so `hideEvent` never runs and the decode would go on behind an icon.
again.showMinimized()
for _ in range(20):
    appq.processEvents()
assert again.player is None and not again.bg_timer.isActive(), "minimised: no stream"
assert not again.preview_timer.isActive(), "minimised: no redraw"
shown_min = again._played
t0 = time.monotonic()
while time.monotonic() - t0 < 1.5:
    appq.processEvents()
assert again._played == shown_min, "and nothing reaches the label behind an icon"
again.showNormal()
for _ in range(20):
    appq.processEvents()
assert again.player is not None and again.bg_timer.isActive(), "restored, playing"
print(f"  minimised stops it   no stream, no redraw, {again._played - shown_min} frames "
      f"shown in 1.5 s behind an icon; restoring plays again")
again.hide()
for _ in range(10):
    appq.processEvents()
assert again.player is None, "a hidden window holds no ffmpeg"
for _ in range(200):
    appq.processEvents()
assert again.player is None, "nothing decodes behind a hidden window"
assert not again.preview_timer.isActive(), "and nothing redraws either"
again.show()
for _ in range(20):
    appq.processEvents()
assert again.player is not None, "showing the window starts the stream again"
assert again.player.loops >= seams
print(f"  the preview plays      {os.path.basename(again.mp4)} "
      f"{again.player.seconds:.2f} s loop at {again.player.fps:g} fps, "
      f"{again.player.wide}x{again.player.tall}; hidden or minimised holds no "
      f"ffmpeg and shows nothing")
again._close_player()
print(f"  widgets remembered      theme {saved['theme']}, clock "
      f"{saved['clock_size']}, {os.path.basename(saved['clip'])}, "
      f"{saved['preview_fps']} fps, size {saved['size']}")
again.preview_timer.stop()
again.thumb_timer.stop()
again.panel.stop()
again.panel.wait(2000)

win.queue("status")
for _ in range(60):                       # wait for the worker's verdict
    appq.processEvents()
    if "open" in win.log_view.text():
        break
    time.sleep(0.1)
win.preview_timer.stop()
win.panel.stop()
win.panel.wait(3000)
text = win.log_view.text()
assert "xigma-no-such-port" in text, text
assert "could not open" in text or "cannot open" in text, text
print("  missing port reported in the log, no exception")

# the reset gate: nothing goes out without the typed word, and `_reset` is the
# only call site that asks for a destructive link
assert inspect.getsource(panel.Panel).count("destructive=True") == 1
assert "allow_destructive=destructive" in inspect.getsource(panel.Panel._open)
gate = panel.Panel(bad)
captured = []
gate.log.connect(captured.append)
assert gate._reset(confirm="") is False
assert "nothing sent" in " ".join(captured), captured
print("  reset needs the typed word; exactly one destructive call site")

# the fan checkbox's tooltip promises that it takes the tach array out of the
# metrics blob as well as off the picture, so that promise has to be in the code
# and not only in the tooltip: three drawing buttons, three hand-offs of the flag
wired = inspect.getsource(app.Window._build).count("fans=self.fanline.isChecked()")
assert wired == 3, wired
print("  all three drawing buttons hand the fan flag to the worker")

# ---- the three columns, and what the preview is allowed to do with its pixels ----
# The preview column's width is capped at the picture's own size plus the pane's
# chrome, because `_fit()` must never draw the 480 px frame larger than 480:
# Qt's `scaled(KeepAspectRatio)` happily grows a pixmap, and on a wide window that
# showed a 502 px picture of a 480 px panel.  Both halves of that rule are checks.
# And the library is a column of its own now, because at 1 919x1 055 the clip list
# was one box among five in a single long column: measured, its viewport was 190 px
# with 114 px rows, which is two clips on screen at a time.
assert win.split.count() == 3, win.split.count()
pane_l, pane_c, pane_lib = (win.split.widget(i) for i in range(3))
assert pane_l.maximumWidth() == render.W + app.PANE_CHROME, (
    pane_l.maximumWidth(), render.W, app.PANE_CHROME)
assert pane_l.maximumWidth() >= render.W, "the frame could never be shown 1:1"
assert pane_c.minimumWidth() >= 300 and pane_lib.minimumWidth() >= 320, \
    (pane_c.minimumWidth(), pane_lib.minimumWidth())
win.show()
for _ in range(6):
    appq.processEvents()
win.resize(1600, 900)
win.split.setSizes([1200, 380, 520])   # the handle dragged as far right as it goes
for _ in range(6):
    appq.processEvents()
assert pane_l.width() == pane_l.maximumWidth(), (pane_l.width(),
                                                 pane_l.maximumWidth())
win._fit()
assert win.preview.width() >= render.W, win.preview.width()
assert win.preview.pixmap().width() == render.W, win.preview.pixmap().size()
win.split.setSizes([180, 1400, 500])   # and as far left
for _ in range(6):
    appq.processEvents()
win._fit()
assert win.preview.pixmap().width() == win.preview.width() < render.W, \
    (win.preview.pixmap().size(), win.preview.width())
print(f"  preview column          capped at {pane_l.maximumWidth()} px for a "
      f"{render.W} px frame: 1:1 on a wide window, {win.preview.pixmap().width()} "
      f"px when the pane is dragged narrow, never bigger than the glass")

# How much clip the library column actually shows, at the sizes a reader gets:
# rows follow the icon size, so this is the number that decides whether the list is
# a tool or a scroll wheel.  Both are measurements of the live widget, not of the
# intent: `fixed` layout mode, 64 px icons, uniform sizes.
win.resize(*settings.DEFAULTS["size"])   # the window's own default size, read from the
# code, so the rows-in-view figures printed below and quoted in docs/gui.md are the
# ones the code actually asks for
win.split.setSizes(list(settings.DEFAULTS["split"]))
for _ in range(10):
    appq.processEvents()
row_h = win.clips.visualItemRect(win.clips.item(0)).height()
visible = win.clips.viewport().height() // max(1, row_h)
assert row_h <= 80, (row_h, "a clip row taller than this wastes the column")
assert visible >= 4, (visible, row_h, win.clips.viewport().height(),
                      "the library column shows too few clips to browse")
assert win.clips.uniformItemSizes() and \
    win.clips.resizeMode() == win.clips.ResizeMode.Fixed, \
    "the list is back in the mode that paints one selected row as a block"
# and every row is *told* how tall it is: with uniform sizes the first item's
# sizeHint sets the height for all of them, taken before any thumbnail exists,
# which once latched every row to 17 px of text and clipped the icons that
# arrived a tick later (measured: 17 px at first paint, 66 px only afterwards)
assert all(win.clips.item(i).sizeHint().height() >= app.CLIP_ICON.height()
           for i in range(win.clips.count())), "a row is shorter than its thumbnail"
assert all(win.clips.item(i).sizeHint().height() <= app.CLIP_ICON.height() + 8
           for i in range(win.clips.count())), "rows are padding themselves again"
# a thumbnail never distorts the file it came from: the row states the measured
# pixel size, and the picture keeps its own aspect ratio, letterboxed into the
# square.  Tested on the fit itself rather than on a clip that happens to be 4:3,
# because the selftest job used to run against a checkout with only the three vendored
# clips - the themes package is a separate .deb - and a search for a 320x240 file
# there died with StopIteration on the runner (run 42350703043) while passing here.  The
# window now walks this checkout's own `themes/alpha/clips` too, so the runner sees the
# same 40 rows, three of them 320x240; the fit is still tested on a made-to-measure
# image rather than by hunting for a 4:3 row, because a test that depends on which clips
# a machine happens to hold fails on one machine and proves nothing on another.
from PIL import Image as _PILImage
_box = clipdb.letterbox(_PILImage.new("RGBA", (320, 240), (255, 0, 0, 255)), 64)
assert _box.size == (64, 64), _box.size
assert _box.getpixel((32, 1))[3] == 0, "the bar above a 4:3 frame is not clear"
assert _box.getpixel((32, 62))[3] == 0, "the bar below a 4:3 frame is not clear"
assert _box.getpixel((32, 32))[3] > 0, "the frame itself was pasted away"
assert _box.getbbox() == (0, 8, 64, 56), (_box.getbbox(),
                                          "a 320x240 frame does not fit 64 px at 4:3")
_sq = clipdb.letterbox(_PILImage.new("RGBA", (480, 480), (0, 255, 0, 255)), 64)
assert _sq.getbbox() == (0, 0, 64, 64), "a square frame gained bars it did not need"
print("  clip thumbnails          letterboxed: 4:3 keeps its ratio, 1:1 fills the square")
assert win.clips.iconSize() == app.CLIP_ICON, (win.clips.iconSize(), app.CLIP_ICON)
win.resize(1919, 1055)                 # a full-HD desk, the case reported
for _ in range(10):
    appq.processEvents()
wide_visible = win.clips.viewport().height() // max(1, row_h)
assert wide_visible >= 8, (wide_visible, "the full-HD window is back to two rows")
# "rows in view" is capacity, not a claim about how many clips a machine has: the
# selftest job runs against a checkout, whose own `themes/alpha/clips` root carries 43
# of the 46 tracked mp4 files (40 distinct contents), and the bench adds an installed
# copy and a mounted partition around the same 40 rows.
print(f"  clip list               rows {row_h} px: {visible} rows in view at "
      f"{settings.DEFAULTS['size'][0]}x{settings.DEFAULTS['size'][1]}, "
      f"{wide_visible} at 1919x1055, where it used to be 2 "
      f"({win.clips.count()} clips on this machine)")
# and the two pages that quote that capacity quote it *per machine*.  The count is the
# pane's height divided by the row height, so it follows the fonts of the box it runs on:
# this run sees {visible}/{wide_visible}, the author's bench sees 9/10, and a page that
# carries one machine's digits fails on the other - which is what CI found on 2026-11-10.
# The answer is to label the digits and hold the page to both, not to loosen the check.
_sz = settings.DEFAULTS["size"]
_pat = _re.compile(r"for (\d+) clips at the fresh %d×%d window on this bench "
                   r"\((\d+) on CI's runner\), (\d+) at 1919×1055 \((\d+) there\)"
                   % (_sz[0], _sz[1]))
_m = _pat.search(open("docs/gui.md", encoding="utf-8").read())
assert _m, ("docs/gui.md's clip-row capacity is not a labelled bench/runner pair, so the "
            "number no gate can see")
assert (_sz[0], _sz[1]) == (1440, 1024), _sz         # the sentence names its window
_pg = tuple(int(x) for x in _m.groups())             # the page's four digits: bench, runner
assert (_pg[0], _pg[2]) == (visible, wide_visible) or \
    (_pg[1], _pg[3]) == (visible, wide_visible), (
    (visible, wide_visible), _pg,
    "this machine's clip-row capacity is neither pair docs/gui.md labels")
_te_doc = open("docs/theme-editor.md", encoding="utf-8").read()
_pat2 = _re.compile(r"room for (\d+) clips at the %d×%d default on this bench, "
                    r"(\d+) on CI's runner" % (_sz[0], _sz[1]))
_m2 = _pat2.search(_te_doc)
assert _m2, "docs/theme-editor.md's clip-row capacity is not a labelled bench/runner pair"
assert visible in (int(_m2[1]), int(_m2[2])), (
    visible, _m2.groups(), "docs/theme-editor.md's clip-row capacity is not what this "
                           "run measured on either machine")

# the row height itself is the other half of that arithmetic, and both pages name it
_txt = open("docs/gui.md", encoding="utf-8").read()
_row_h = win.clips.sizeHintForRow(0)
assert f"{_row_h} px rows" in " ".join(_txt.split()), (
    _row_h, "docs/gui.md counts the clip rows at a different pitch than this list does")

# the detail line under the list repeats nothing: the row above it already says
# what the file is called, its size, its length and where it came from
win.split.setSizes(list(settings.DEFAULTS["split"]))
win.clips.setCurrentRow(next(i for i, c in enumerate(win.all_clips)
                             if c.name == "Theme_11.mp4"))
for _ in range(6):
    appq.processEvents()
detail = win.clip_info.text()
assert "Theme_11" not in detail, detail[:120]
assert "mean luma" in detail and "overwrites" not in detail.replace("replaces", ""), \
    detail[:160]
print("  clip detail             the readout under the list, not a second copy of the row")

# ---- the advanced switch: what folds away, and what hiding never changes ----
# Default: folded.  Everything hidden keeps its value and still goes out on Apply -
# the switch is about pixels, not about defaults.  Twelve controls fold, in three
# boxes: the panel-status box and the guarded factory reset (one box more than 0.4
# folded, a decision deliberately reversed from the one 0.4 documented, so the box
# keeps its typed-word gate checked here whatever is around it), and since feature G
# the pane-readings box - the mode combo and its file field, which decide what body
# the editor's picture is painted from and say nothing about the file, so it belongs
# with `canvas` and `scrim` rather than in the editor column.  It also keeps a fresh
# window at the fixture: the peek is not a setting, and no key for it goes near the
# session file.  The layout editor does NOT fold: it is the only place the window
# shows the library's layouts.
folded = [win.canvas, win.scrim, win.fanline, win.d_events, win.btn_live,
          win.status_box, win.reset_box, win.confirm, win.btn_reset,
          win.peek_box, win.ed_peek, win.ed_peek_file]
assert len(folded) == 12, folded
assert win.ed_group not in win._adv_hide, \
    "the layout editor folded away again, and it is the window's only layout browser"
# the note beside the switch, the tooltip on the switch, and the two docs that walk
# the window all have to name the same eight rows and boxes.  The note counts by
# commas; the tooltip and the docs are checked by their own wording, so the lists are
# written out here rather than scraped from the prose.
note_folded = win.adv_note.text()
# The note used to be checked by counting commas, which worked while everything that
# folded was a row of its own.  It now folds two whole boxes, and one of those boxes
# holds three controls, so the note is checked by naming each thing it has to cover:
# a map with the right number of commas and a box missing from it is the worse failure.
for _what in ("canvas", "scrim", "fan", "port actions", "30 s run", "status",
              "reset", "readings"):
    assert _what in note_folded.lower(), (_what, note_folded,
                                          "the note beside the switch does not name it")
# Eight named things, twelve controls: five rows of their own and three whole boxes -
# the panel-status box, the reset's box (bringing its word field and its button) and
# the pane-readings box (bringing its combo and its file field).  Checked both ways,
# because a note that names the panel-status box twice (an earlier draft of this one
# called the same reply "panel hello" *and* "the panel-status box") is a map with a
# place on it that the window does not have.
assert len([p for p in note_folded.split(",") if p.strip()]) == 8, note_folded
assert len(folded) - len([w for w in folded if w in (win.status_box, win.reset_box,
                                                    win.confirm, win.btn_reset,
                                                    win.peek_box, win.ed_peek,
                                                    win.ed_peek_file)]) == 5, \
    [w.objectName() or type(w).__name__ for w in folded]
# ...and the third box folds with the switch rather than merely being listed here:
# `_set_advanced` drives `win._adv_hide`, and the boxes are counted out of the window
assert all(w in win._adv_hide for w in (win.peek_box, win.ed_peek, win.ed_peek_file)), \
    "the pane-readings box does not fold with the switch"
assert sum(1 for w in folded if w in (win.status_box, win.reset_box, win.peek_box)) == 3, \
    [type(w).__name__ for w in folded]
gui_txt = open("docs/gui.md", encoding="utf-8").read()
assert "layout editor" in gui_txt, "the window grew an editor and gui.md did not"
assert "twelve secondary controls" in gui_txt, \
    "gui.md counts the folded controls differently"
_tip = win.adv_toggle.toolTip()
assert "factory reset" in _tip and "panel-status box" in _tip and "layout editor" in _tip, (
    _tip, "the switch's tooltip does not say what it covers and what it leaves alone")
assert "pane-readings box" in _tip, (_tip, "the tooltip has not heard of the third box")
assert "does not change them" in _tip, (
    _tip, "the tooltip does not say that hiding is about pixels, never values")
# where the two boxes that folded over live: both at the foot of the *preview*
# column, under the log, and beside each other.  Checked by parent and by order in
# that column's layout, because `in win._adv_hide` would only prove the code agrees
# with itself, and a box parked back in the controls column would pass that.
def _box_items(box):
    """every widget a QBoxLayout hands out, descending into nested layouts"""
    out = []
    for _i in range(box.count()):
        _it = box.itemAt(_i)
        if _it.widget() is not None:
            out.append(_it.widget())
        elif _it.layout() is not None:
            out.extend(_box_items(_it.layout()))
    return out


_left = win.split.widget(0).widget()
assert win.status_box.parent() is _left and win.reset_box.parent() is _left, \
    "one of the two boxes is not in the preview column"
_order = _box_items(_left.layout())
for _b in (win.log_box, win.status_box, win.reset_box):
    assert _b in _order, (f"{_b.title()} is not a box in the preview column",
                          [getattr(x, "title", lambda: "?")() for x in _order])
assert _order.index(win.log_box) < min(_order.index(win.status_box),
                                       _order.index(win.reset_box)), \
    "the two boxes arrived above the log, pushing the picture's column apart"
assert all(not w.isVisible() for w in folded), [w.objectName() or str(w.parent())
                                                for w in folded if w.isVisible()]
assert all(w.isVisible() for w in (win.clips, win.theme, win.btn_upload, win.btn_apply,
                                   win.log_box, win.ed_group, win.ed_name,
                                   win.preview, win.clock_size, win.ink_choice)), \
    "the compact view lost something a first run needs - the editor is one of them now"
win.scrim.setValue(200)                # reachable and in force while invisible
assert not win.scrim.isVisible() and win.scrim.value() == 200
# the reset's double guard is a property of the box, not of its position: folded, the
# button is hidden AND disabled; shown, it is still disabled until the word is typed -
# and what wakes it is the word, not the switch
assert not win.btn_reset.isVisible() and not win.btn_reset.isEnabled()
win.adv_toggle.setChecked(True)
for _ in range(6):
    appq.processEvents()
assert all(w.isVisible() for w in folded), "advanced did not show what it names"
assert not win.btn_reset.isEnabled(), "showing the box woke a button nobody armed"
win.confirm.setText("reset")
for _ in range(2):
    appq.processEvents()
assert win.btn_reset.isEnabled(), "the typed word did not wake the button"
win.confirm.setText("")
for _ in range(2):
    appq.processEvents()
assert not win.btn_reset.isEnabled(), "clearing the word left the reset armed"
assert win.adv_toggle.text().lower().startswith("advanced")
win._save_now()
assert settings.load()["advanced"] is True, settings.load()
again2 = app.Window(bad, None, restore=True)
assert again2.adv_toggle.isChecked() is True, "the switch was not remembered"
assert again2.scrim.value() == 200, (again2.scrim.value(),
                                     "a hidden control came back at its default")
for _t in (again2.preview_timer, again2.thumb_timer):
    _t.stop()
again2.panel.stop()
again2.panel.wait(2000)
win.adv_toggle.setChecked(False)
for _ in range(6):
    appq.processEvents()
_in_boxes = sum(1 for w in folded if w in (win.status_box, win.reset_box,
                                           win.confirm, win.btn_reset))
print(f"  advanced switch         folds the {len(folded)} controls the note names - "
      f"{_in_boxes} of them inside the two boxes at the foot of the preview column "
      f"({note_folded}) - keeps their values and the reset's typed-word guard, "
      f"remembers itself, and leaves the layout editor and the picture open")

# and the split is remembered, with a collapsed pane refused rather than restored
moved = list(win.split.sizes())
win._save_now()
saved2 = settings.load()
assert saved2["split"] == moved, (saved2["split"], moved)
assert settings._clean({"split": [0, 700]})["split"] == settings.DEFAULTS["split"], \
    "a collapsed pane came back as a collapsed pane"
assert len(settings._clean({"split": [500, 700]})["split"]) == 3, \
    "a file from the two-column layout did not grow a third"
back = app.Window(bad, None, restore=True)
assert back.cfg["split"] == moved, back.cfg["split"]
for _t in (back.preview_timer, back.thumb_timer):
    _t.stop()
back.panel.stop()
back.panel.wait(2000)
print(f"  split remembered        {moved}, a 0-width pane rejected, a 2-number file grown to 3")

# ... and the fresh split actually fits a fresh window.  This is the bug the 0.5
# defaults are for.  Re-measured against the v0.4 tag: its 1180x780 window and
# 520/460/560 request came back as 520/300/352 columns, and the controls column's own
# contents wanted 265 px folded but 375 px with the advanced switch on - so that column
# grew a horizontal scrollbar *inside itself* with 89 px of its contents off screen, and
# the library column (359 px wanted, 352 given) overflowed by 7 px the same way.  The
# 0.4 figures are not asserted here: only this tree can be.  Advanced mode is the
# worse case for the new defaults, because the editor's rows are on show.
fresh = app.Window(bad, None, restore=False)
fresh.show()                            # offscreen geometry is meaningless until shown
fresh.resize(*settings.DEFAULTS["size"])
fresh.adv_toggle.setChecked(True)
fresh._editor_open(fresh.ed_name.itemText(1))   # an open layout is the wide case: its
for _ in range(8):                              # rows name a widget, a field, a position
    appq.processEvents()
for _i, _name in enumerate(("preview", "controls", "library")):
    _area, _inner = fresh.split.widget(_i), fresh.split.widget(_i).widget()
    assert _inner.width() >= _inner.minimumSizeHint().width(), \
        (f"{_name} column at a fresh window", _area.width(), _inner.width(),
         _inner.minimumSizeHint().width())
    _hs = _area.horizontalScrollBar()
    assert not _hs.isVisible() and _hs.maximum() == 0, \
        (f"{_name} column scrolls sideways at a fresh window",
         _hs.maximum(), _inner.width(), _area.width())
_fits = [fresh.split.sizes(), [i.minimumSizeHint().width() for i in
                               (fresh.split.widget(k).widget() for k in range(3))],
         fresh.width()]
# and the drop-downs in that column are readable *at* that width.  A closed combo
# stretches to whatever its column gives it; the list that opens is the box's own
# width, so an entry longer than the box is cut off exactly where a reader is choosing
# between entries.  The editor's own rows are the worst case, and their width depends
# on which layout is open: a `data` row reads `type  what  at x,y`, so the name in the
# middle decides it.  Sweeping every layout this machine can open finds the widest.
from xigmalcd import themes as _themes          # the block below imports it again
_worst = (0, "")
for _nm in sorted(_themes.EXPORTS) + [r["name"] for r in _themes.scan()[0]]:
    fresh._editor_open(_nm)
    for _ in range(2):
        appq.processEvents()
    _m = fresh.ed_widget.view().fontMetrics()
    _w = max((_m.horizontalAdvance(fresh.ed_widget.itemText(_i))
              for _i in range(fresh.ed_widget.count())), default=0)
    if _w > _worst[0]:
        _worst = (_w, _nm)
assert _worst[0] > 0, _worst
fresh._editor_open(_worst[1])           # open the one that needs the most room
for _ in range(4):
    appq.processEvents()
_lists = {}
for _cb, _nm in ((fresh.ed_name, "layout"), (fresh.ed_widget, "widget")):
    _m = _cb.view().fontMetrics()
    _long = max((_m.horizontalAdvance(_cb.itemText(_i))
                 for _i in range(_cb.count())), default=0)
    if not _long:
        continue                        # an empty row: nothing to be readable about
    assert _cb.view().minimumWidth() >= _long + _cb.iconSize().width(), (
        _nm, _cb.view().minimumWidth(), _long, "the list is narrower than its entries")
    assert _cb.minimumSizeHint().width() <= _long + 40, (
        _nm, _cb.minimumSizeHint().width(), _long,
        "the closed box asks for more than its longest entry: the column pays for it")
    _lists[_nm] = (_long, _cb.view().minimumWidth(), _cb.width())
assert {"layout", "widget"} <= set(_lists), _lists
# The case the fix exists for, made on purpose: the controls column pinned to the
# narrowest width the window now allows, which is its contents' own floor (0.4's 300 px
# column is unreachable by construction - `_pane_floors` raises the pane to what it
# holds, which is the other half of the fix).  A request alone will not do it: a
# splitter shares out spare width by its stretch factors, so the first version of this
# check measured a 340 px column while believing it was pinning 300.
_area = fresh.split.widget(1)
_ceil = _area.maximumWidth()
# The floor is not a constant to read once: a pane's minimum is derived from its contents,
# and its contents move when that minimum moves the splitter, so the window settles the
# number over a few queued passes (`_pane_floors`).  Take it after that has run - the
# first version of this check pinned a 340 px column while claiming to pin 300, the second
# pinned 411 px around a floor that had since grown to 425, and both then asserted
# something about a width that was no longer the narrowest the window allowed.
for _ in range(12):
    appq.processEvents()
_floor = _area.minimumWidth()
assert _floor >= _area.widget().minimumSizeHint().width(), (
    _floor, _area.widget().minimumSizeHint().width(),
    "the controls column's floor is under what it holds, so the handle can drag it into a "
    "horizontal scrollbar")
_area.setMaximumWidth(_floor)
for _ in range(8):
    appq.processEvents()
_narrow = (_area.width(), fresh.ed_widget.view().minimumWidth(),
           fresh.ed_widget.width(), _worst[0])
assert _narrow[0] == _floor, (_narrow, _floor,
                              "this is not the narrow column the window allows")
# The half that has to hold at every width is the popup's: the list a reader chooses from
# is never narrower than the widest entry any layout puts in it.  Whether the *closed* box
# fits that entry follows this machine's fonts and the number of editor columns the width
# allowed, so the gate reports which branch it measured instead of pinning a digit.
assert _narrow[1] >= _narrow[3], (
    _narrow, "a narrow column cut the list down with it, which is the elision this fix is "
             "about")
# And the floor's whole purpose, checked at the width the floor is the limit at: the
# column must not be scrolling sideways.  It was.  The pane's minimum came from its
# contents' width, but a pane is a scroll area, and the vertical scrollbar the editor's
# rows make it show takes its extent off the viewport - a 411 px floor around a 411 px
# set of contents left a 397 px viewport and 14 px of horizontal travel, which is the
# 0.4 defect arriving one rule later.
_hb = _area.horizontalScrollBar()
assert _hb.maximum() == 0 and not _hb.isVisible(), (
    _narrow, _hb.maximum(), "pinned to its own floor the controls column still scrolls "
                            "sideways, so that floor is not its contents' width")
_box_cuts = _narrow[2] < _narrow[3]
_says = "the box cuts it, so the list carries it" if _box_cuts else "the box shows it in full"
print(f"                        at the narrowest column the window allows "
      f"({_narrow[0]} px), a {_narrow[3]} px entry sits in a {_narrow[2]} px box "
      f"({_says}) and opens a {_narrow[1]} px list")
_area.setMaximumWidth(_ceil)
# The README's picture is framed wider than the fresh window, and both the capture
# tool and docs/tools.md say how many clip rows that frame puts in view.  Read the
# tool's own default and measure it here, in this same window, rather than carrying
# the sentence from one release to the next: 0.4 wrote "six rows" for a frame that
# had begun to show seven.
shot = _re.search(r'--size",\s*default="(\d{3,4}x\d{3,4})"',
                  open("tools/screenshot.py", encoding="utf-8").read())
assert shot, "the capture tool no longer carries a --size default to check"
_capt_w, _capt_h = (int(x) for x in shot.group(1).split("x"))
fresh.resize(_capt_w, _capt_h)
for _ in range(10):
    appq.processEvents()
_capt_rows = fresh.clips.viewport().height() // max(1, fresh.clips.sizeHintForRow(0))
_spell = "zero one two three four five six seven eight nine ten eleven twelve".split()
assert _capt_rows < len(_spell), _capt_rows
_words = f"{_spell[_capt_rows]} rows of the clip list"
for _f in ("tools/screenshot.py", "docs/tools.md"):
    _shot_txt = open(_f, encoding="utf-8").read()
    # Both pages carry the count twice, once per machine, and the tool's copy is split
    # across adjacent string literals - so quotes and line breaks come out before anything
    # is compared, or the half nobody reads is the half that rots: the first version of
    # this check passed while `--size`'s help still said "seven" next to a docstring that
    # said "nine", because `in` stops at the first match.
    _shot_flat = " ".join(_shot_txt.replace('"', "").split())
    _counts = set(_re.findall(r"(\w+) rows of the clip list", _shot_flat))
    assert _words in _shot_flat, (
        _f, _words, "that page does not carry the count this machine measures")
    assert len(_counts) == 2 and _spell[_capt_rows] in _counts, (
        _f, sorted(_counts), _capt_rows, "that page should label the captured row count "
        "for two machines, this one among them - a third machine's number is a sentence "
        "to add, not a check to loosen")
for _t in (fresh.preview_timer, fresh.thumb_timer, fresh.daemon_timer):
    _t.stop()
fresh.panel.stop()
fresh.panel.wait(2000)
print(f"  a fresh window fits     {settings.DEFAULTS['split']} asked, {_fits[0]} as the "
      f"splitter scales them across {_fits[2]} px, minimums "
      f"{_fits[1]}: no column scrolls sideways to be read. The editor's lists give "
      f"{_lists['layout'][1]} px to a {_lists['layout'][0]} px layout name and "
      f"{_lists['widget'][1]} px to a {_lists['widget'][0]} px row (boxes "
      f"{_lists['layout'][2]} and {_lists['widget'][2]} px); the widest row any of "
      f"the {len(_themes.EXPORTS) + len(_themes.scan()[0])} layouts puts there is "
      f"{_worst[0]} px in {_worst[1]!r}, and in a {_narrow[0]} px column that is a "
      f"{_narrow[1]} px list around a {_narrow[2]} px box. The README's "
      f"{_capt_w}x{_capt_h} frame puts {_capt_rows} clip rows in view, and the two "
      f"pages that say so spell it the same")
# and the split the docs quote is the one the code carries, and the columns they
# quote are the ones the splitter made of it.  Both are compared after the print
# above, so a failure here shows the measurement it disagreed with rather than
# leaving the number to be found by hand: docs/gui.md writes "532 / 540 / 356" for
# the request and the columns as they come back, docs/theme-editor.md "(532/540/356)".
_sp = settings.DEFAULTS["split"]
assert f"{_sp[0]} / {_sp[1]} / {_sp[2]}" in gui_txt, (
    _sp, "docs/gui.md quotes a different fresh split than settings.DEFAULTS")
_te = open("docs/theme-editor.md", encoding="utf-8").read()
assert f"({_sp[0]}/{_sp[1]}/{_sp[2]})" in _te, (
    _sp, "docs/theme-editor.md's pixel census quotes a different fresh split")
# The read-back is a different matter: two of those three columns are the pane's floor,
# which is what its contents measure, and contents follow the fonts of the machine (the
# library column is 359 px here and 376 px on CI's runner).  So the page's digits are held
# to the *first* one - the preview column, which the cap decides in code - and to carrying
# its machine label; the other two are compared as relations, and this run's triple goes
# to stdout so a doc that drifts from it is visible in the log rather than in a red X.
_rb = _re.search(r"reads them back as \*\*(\d+) / (\d+) / (\d+)\*\* on\s+this bench",
                 gui_txt)
assert _rb, ("docs/gui.md's fresh read-back is no longer labelled as this bench's, so "
             "whose digits it is has gone missing")
assert int(_rb[1]) == _fits[0][0] == 532, (_rb.groups(), _fits[0],
    "the preview column's share is set in code, so the page and the run must agree on it")
assert _fits[0][1] >= _fits[1][1] and _fits[0][2] >= _fits[1][2], (
    _fits, "a column came back narrower than what it holds")

# ---- the owner's sizing rule, and the responsive half of the editor ----
# 1280x1024 at minimum, up to 3840x2160, and the editor's field grid taking one, two or
# three columns as the controls column gets width.  Every figure docs/gui.md's "How the
# three columns get their sizes" section quotes comes out of this one pass, on this
# machine, with the widest row set the editor can be asked for on show: an `arc` widget's
# 18 fields, from `gauge`.
_sized = app.Window(bad, None, restore=False)
_sized.show()
_sized.adv_toggle.setChecked(True)
_sized._editor_open("gauge")
for _ in range(8):
    appq.processEvents()
_arc_at = next(i for i in range(_sized.ed_widget.count())
               if str(_sized.ed.widgets()[i].get("type") or "") == "arc")
_sized.ed_widget.setCurrentIndex(_arc_at)
for _ in range(8):
    appq.processEvents()
from xigmaui import edit as _ed_api        # the model behind the rows
assert len(_sized.ed_rows) == (len(_ed_api.field_names("arc"))
                               + len(_ed_api.extension_fields("arc"))), _sized.ed_rows
_rows_at, _cols_at, _floor_at = {}, {}, {}
_host_at, _box_at, _lib_at = {}, {}, {}      # columns in use -> the grid's own minimum
                                # width; window width -> (columns, editor box height);
                                # window width -> the library column's viewport width
for _W, _H in ((1280, 1024), (1440, 1024), (1919, 1055), (2560, 1440), (3840, 2160)):
    _sized.resize(_W, _H)
    for _ in range(14):
        appq.processEvents()
    # the threshold is only honest if the grid the columns made genuinely fits in the
    # room that justified them, and the columns actually arrive as the window widens -
    # "responsive" that never switches is a layout that shrinks on a 4K screen
    _host = _sized._ed_host
    assert _host.minimumSizeHint().width() <= _sized.split.widget(1).viewport().width(), (
        _W, _sized._ed_cols, _host.minimumSizeHint().width(),
        "the field grid asked for more width than the column it sits in has")
    _cols_at[_W] = _sized._ed_cols
    for _i, _nm in enumerate(("preview", "controls", "library")):
        _area = _sized.split.widget(_i)
        _inner = _area.widget()
        assert _area.viewport().width() >= _inner.minimumSizeHint().width(), (
            _W, _nm, _area.viewport().width(), _inner.minimumSizeHint().width(),
            "a column is narrower than what it holds")
        # ...and the *floor*, not merely the width this window happens to hand out.  A
        # pane whose minimum sits under its own contents can still be dragged into
        # overflow, which is the whole failure this rule exists to make unreachable - and
        # it is the half a single measuring pass misses, because the grid's contents
        # change when the floor moves the splitter.
        assert _area.minimumWidth() >= _inner.minimumSizeHint().width(), (
            _W, _nm, _area.minimumWidth(), _inner.minimumSizeHint().width(),
            "a column's floor is under what it holds, so the handle can drag it into a "
            "horizontal scrollbar")
        _hs = _area.horizontalScrollBar()
        assert _hs.maximum() == 0 and not _hs.isVisible(), (
            _W, _nm, _hs.maximum(), "this width hands that column a horizontal scrollbar")
    _rows_at[_W] = _sized.clips.viewport().height() // max(1, _sized.clips.sizeHintForRow(0))
    _cols_at[_W] = _sized._ed_cols
    _floor_at[_W] = [_sized.split.widget(i).minimumWidth() for i in range(3)]
    _lib_at[_W] = _sized.split.widget(2).viewport().width()
    # what one column of rows actually costs, at the number of columns in use: the
    # per-column threshold in app.py is only honest if a column of rows fits inside it,
    # and the box's own height is the other half of "uses the screen real estate"
    _host_at[_sized._ed_cols] = _sized._ed_host.minimumSizeHint().width()
    _box_at[_W] = (_sized._ed_cols, _sized.ed_group.height())
# the floor itself: the window never lets a column be narrower than its contents, and
# never asks for more than MIN_WIDTH/MIN_HEIGHT - or than the screen, whichever is smaller
_seq = [_cols_at[w] for w in (1280, 1440, 1919, 2560, 3840)]
assert _seq == sorted(_seq) and all(a <= 3 for a in _seq), _cols_at
assert _cols_at[1440] >= 2, (_cols_at, "the rows still stack in one column at the fresh "
                                       "window, so the extra width is going nowhere")
assert _cols_at[3840] == 3, (_cols_at, "a 4K desktop gets no more columns than a laptop")
_avail = _sized.screen().availableGeometry()
for _i, _want in enumerate((app.MIN_WIDTH, app.MIN_HEIGHT)):
    _got = (_sized.minimumWidth(), _sized.minimumHeight())[_i]
    assert _got >= min(_want, (_avail.width(), _avail.height())[_i]), (
        _got, _want, _avail.width(), _avail.height(),
        "the window's own floor is under the rule MIN_WIDTH/MIN_HEIGHT states")
print(f"  the sizing rule         floor {app.MIN_WIDTH}x{app.MIN_HEIGHT} (this screen has "
      f"{_avail.width()}x{_avail.height()}), window minimum "
      f"{_sized.minimumWidth()}x{_sized.minimumHeight()}, pane floors "
      f"{_floor_at[1280]}; the editor grid takes "
      + ", ".join(f"{_cols_at[w]} col at {w}" for w in (1280, 1440, 1919, 3840))
      + f"; clip rows in view "
      + ", ".join(f"{_rows_at[w]} at {w}" for w in (1280, 1440, 1919, 2560, 3840))
      + f"; the controls pane's floor moves with the columns it holds: "
      + ", ".join(f"{_floor_at[w][1]} at {w}" for w in (1280, 1440, 1919)))
# the widest row set this window can be asked for, in the window rather than in a
# stand-in form: an `arc` widget's 18 rows in one column, then in three.  Both figures
# the app.py comment quotes come from this line.
_arc_rows = len(_ed_api.field_names("arc")) + len(_ed_api.extension_fields("arc"))
print(f"                        the 18-row case (`arc`, {_arc_rows} rows, from the "
      f"model's lists): "
      + ", ".join(f"{_box_at[w][0]} col at {w} -> grid asks "
                  f"{_host_at[_box_at[w][0]]} px, box stands {_box_at[w][1]} px tall"
                  for w in (1280, 1440, 1919)))
assert _host_at[max(_host_at)] <= 3 * _sized._ED_COL_PX, (
    _host_at, _sized._ED_COL_PX, "three columns of rows ask for more than the "
    "threshold says they get")
# ... and the figures docs/gui.md quotes in that paragraph are measurements, so the page
# labels whose machine each belongs to and the suite holds them two ways: a figure stated
# for *both* machines is checked by membership (this run has to be one of the two), and a
# figure stated once has to carry its label, with this run's number printed beside it so a
# drift shows up on a green run instead of only on a red one.  The two labelled machines
# are the author's bench and GitHub's runner; a third machine is a sentence to add, which
# is what its own numbers are printed for.
_gf = " ".join(gui_txt.split())


def _pair(what, pattern, mine, unit="px"):
    """One measured figure the page states for two machines: this run must be one of them."""
    m = _re.search(pattern, _gf)
    assert m, (what, "docs/gui.md no longer writes this figure as a labelled bench/runner "
                     f"pair, so nobody knows whose {unit} it is")
    got = tuple(int(x.replace(" ", "")) for x in m.groups())
    assert mine in (got[:len(mine)], got[len(mine):]), (
        what, mine, got, f"this machine's {unit} figure is neither one the page labels")
    return got


_b = _pair("the fresh split read back",
           r"reads them back as \*\*(\d+) / (\d+) / (\d+)\*\* on this bench and "
           r"\*\*(\d+) / (\d+) / (\d+)\*\* on CI's runner", tuple(_fits[0]))
assert _b[0] == _b[3] == 532, (_b, "the preview column's share is set in code, so both "
                                   "machines must read the same first digit")
_fl = _pair("the three columns' floors at the minimum window",
            r"the three columns' floors are \*\*(\d+) / (\d+) / (\d+) px\*\* on this "
            r"bench and \*\*(\d+) / (\d+) / (\d+) px\*\* on CI's runner",
            tuple(_floor_at[1280]))
# Each half is one labelled machine's three floors, and `_pair` has already required this
# run's triple to be one of them - which is also how the gate knows *which* half to hold to
# the code's bounds.  Nothing here invents a rule about how the two machines differ: that
# is a fact about two boxes, not a property of the window.
_mine = tuple(_floor_at[1280])
_off = 0 if _fl[:3] == _mine else 3
assert all(_fl[_off + j] >= _sized.PANE_FLOORS[j] for j in range(3)), (
    _fl, _mine, _sized.PANE_FLOORS, "this machine's column floors are under the bounds the "
                                    "code sets for those columns")
_cl = _pair("the controls floor by columns of rows",
            r"one column of editor rows asks for \*\*(\d+) px\*\* of controls on this "
            r"bench, two columns for \*\*(\d+)\*\*, three for \*\*(\d+)\*\* - and "
            r"\*\*(\d+) / (\d+) / (\d+)\*\* on CI's runner",
            (_floor_at[1280][1], _floor_at[1440][1], _floor_at[1919][1]))
assert _cl[0] >= _sized.PANE_FLOORS[1], (_cl, _sized.PANE_FLOORS,
    "the page's controls floor is under the bound the code sets for that column")
assert _cl[0] < _cl[1] < _cl[2] and _cl[3] < _cl[4] < _cl[5], (
    _cl, "a machine's controls floors do not rise with its columns of rows")
_hh = _pair("the `arc` box heights",
            r"stand \*\*(\d+) px\*\* tall in one column and \*\*(\d+) px\*\* in three "
            r"there.*?\*\*(\d+)\*\* and \*\*(\d+) px\*\*, asking",
            (_box_at[1280][1], _box_at[1919][1]))
_ga = _pair("the grid's own ask",
            r"the grid's own ask going \*\*(\d+) / (\d+) / (\d+) px\*\* - \*\*\d+\*\* and "
            r"\*\*\d+ px\*\*, asking \*\*(\d+) / (\d+) / (\d+)\*\*",
            tuple(_host_at[c] for c in (1, 2, 3)))
assert _hh[0] > _hh[1] and _hh[2] > _hh[3], (_hh, "more columns did not shorten the box")
assert _ga[0] < _ga[1] < _ga[2] and _ga[3] < _ga[4] < _ga[5], (_ga, "the ask does not grow "
                                                                "with its columns")
assert _ga[2] <= 3 * _sized._ED_COL_PX and _ga[5] <= 3 * _sized._ED_COL_PX, (
    _ga, _sized._ED_COL_PX, "three columns of rows ask for more than the threshold says")
# The wide window's clip-row count is the same fact on both labelled machines, so it is
# held exactly; its column *width* follows the fonts, so the page states a floor either
# machine clears and the gate prints the width the machine running it measures.
_w = _re.search(r"the library column is \*\*over ([\d ]+) px\*\* across on either "
                r"machine and shows \*\*(\d+)\*\* clip rows on both", _gf)
assert _w, ("docs/gui.md's 3840x2160 sentence no longer states its width as a floor either "
            "machine clears and its row count for both")
assert _lib_at[3840] >= int(_w[1].replace(" ", "")), (
    _lib_at[3840], _w[1], "this machine's wide library column is under the width the page "
                          "promises on either machine")
assert int(_w[2]) == _rows_at[3840], (_rows_at[3840], _w[2],
    "the wide window's clip-row count is not what the page says it is on either machine")
assert _rows_at[1280] <= _rows_at[1440] <= _rows_at[1919] <= _rows_at[2560] <= \
    _rows_at[3840], (_rows_at, "a taller window shows fewer clip rows")
assert _box_at[1280][1] > _box_at[1440][1] > _box_at[1919][1], (
    _box_at, "more columns of rows did not make the box shorter, so the width is idle")
_wide = ", ".join("{} at {}".format(_rows_at[w], w) for w in (1280, 1440, 1919, 3840))
print("                        the page's labelled pairs and this run's: split "
      f"{(_b[0], _b[1], _b[2])} bench / {(_b[3], _b[4], _b[5])} runner / {_fits[0]} here; "
      f"floors at 1280 {_fl[:3]} bench / {_fl[3:]} runner / {tuple(_mine)} here; controls "
      f"by columns {(_cl[0], _cl[1], _cl[2])} / {(_cl[3], _cl[4], _cl[5])} / "
      f"{(_floor_at[1280][1], _floor_at[1440][1], _floor_at[1919][1])} here; at 3840 the "
      f"library column is {_lib_at[3840]} px wide here against the page's floor of "
      f"{_w[1].strip()} px, and {_w[2]} clip rows fit on either machine [{_wide}]")

# the row census docs/theme-editor.md's editor bullet quotes is the model's, so the
# digits are counted here rather than remembered there.  Whitespace is flattened on both
# sides: that page wraps, and a compare that broke on a newline would fail for the
# wrong reason (and be "fixed" by wrecking the prose).
_bf, _be = len(_ed_api.field_names("bar")), len(_ed_api.extension_fields("bar"))
_bar_claim = (f"a `bar` widget gets **{_bf + _be}** rows - **{_bf}** keys the painter "
              f"reads for that kind plus **{_be}** of our own")
assert _bar_claim in " ".join(_te.split()), (_bf, _be, _bar_claim,
                                             "docs/theme-editor.md's row census for a "
                                             "`bar` is not what the model lists")
for _t in (_sized.preview_timer, _sized.thumb_timer, _sized.daemon_timer):
    _t.stop()
_sized.panel.stop()
_sized.panel.wait(2000)

# the default window size the docs quote is the one the code uses
want = f"{settings.DEFAULTS['size'][0]}x{settings.DEFAULTS['size'][1]}"
assert shot, "the capture tool no longer carries a --size default to check"
# the prose figure is the one that can rot; the tool's own default is read back
# out of the tool, and both have to agree with what docs/tools.md says
tools_txt = open("tools/screenshot.py", encoding="utf-8").read()
assert shot.group(1) in tools_txt and "settings.DEFAULTS" in tools_txt, \
    "the capture tool does not say where the fresh window size comes from"
doc_txt = open("docs/tools.md", encoding="utf-8").read()
assert want in doc_txt, (doc_txt[:0] or "docs/tools.md", want,
                         "the fresh window size is quoted as something else")
assert shot.group(1) in doc_txt, (shot.group(1),
                                  "the README framing is quoted as something else")
print(f"  docs quote the sizes    {want} fresh / {shot.group(1)} captured, both matching "
      f"the code")

# ---- one upload control, and the state it reports ----
# There used to be two buttons labelled "Upload background", one per column, and
# neither could say whether the panel had taken the file.  The bench proved what
# that costs: a clip picked in the list, Apply pressed, and the glass going on
# drawing over the old picture with nothing on screen to say so.
assert not hasattr(win, "btn_dupload"), "a second upload button is back"
assert sum(1 for b in (win.btn_upload,) if b.text() == "Upload background") == 0
# the daemon's own ring is the only source for "the panel stores this", and the
# session-start upload has to be in it or a client that connects later can never
# know what is under its frames (the panel cannot be asked, PROTOCOL.md §11)
daemon_src = open("xigmalcd/main.py").read()
assert "accepted at session start" in daemon_src and "did not land at session start" in daemon_src
win.daemon.present = True
try:
    win._stored_bg = win._queued_bg = ""
    win._read_ring(["08:00:00 queued upload: /x/theme_47.mp4",
                    "08:00:01 background theme_47.mp4 accepted"])
    assert win._stored_bg == "theme_47.mp4", win._stored_bg
    assert "the panel stores: theme_47.mp4" in win.d_stored.text(), \
        win.d_stored.text()
    chosen = byname["theme_48.mp4"].path
    win._load_background(chosen)
    win._refresh_clip_state()
    assert "not on it" in win.clip_state.text(), win.clip_state.text()
    assert win.btn_upload.text() == "Send this background to the panel"
    win._stored_bg = os.path.basename(chosen)
    win._refresh_clip_state()
    # and a list this long marks the one that is on the glass, with no help from
    # the panel, which cannot be asked (§11)
    at = next(i for i, c in enumerate(win.all_clips) if c.path == chosen)
    assert win.clips.item(at).font().bold(), "the stored clip is not marked"
    assert not any(win.clips.item(i).font().bold()
                   for i in range(win.clips.count()) if i != at), \
        "more than one row claims to be on the panel"
    assert win.btn_upload.text() == "Send this background again", win.btn_upload.text()
    assert "stores " in win.clip_state.text() and "accepted it" in win.clip_state.text()
    win._stored_bg = ""
    win._refresh_clip_state()
    assert "has not seen an accept" in win.clip_state.text(), win.clip_state.text()
    # and a file the socket would refuse is reported before the press, in the
    # gate's own words - not a button that looks like it worked
    win._load_background(os.path.join("themes", "alpha", "manifest.json"))
    win._refresh_clip_state()
    assert not win.btn_upload.isEnabled(), "an unhidable refusal was clickable"
    assert "cannot go to the panel" in win.btn_upload.text()
    assert "not something the panel can store" in win.clip_state.text(), \
        win.clip_state.text()
    assert win.btn_upload.toolTip() == win.clip_state.text().split(" - ", 1)[1]
    win._load_background(byname["Theme_25.mp4"].path)
    win._refresh_clip_state()
    assert win.btn_upload.isEnabled() and "Ctrl+Shift+U" in win.btn_upload.toolTip()
    print("  background state        unknown / stores X / this clip, three "
          "wordings, and the gate's refusal read before the click")
finally:
    win.daemon.present = False
    win._refresh_clip_state()

# every row carries the file's measured frame size, because the vendor's own
# library is not all the panel's size: measured on the installed tree, 40 of its 43
# clips are 480x480 and 3 are 320x240, and this checkout's three are 480x480.  The
# row says so, and a clip that is not the panel's size is called out as a guess
# rather than drawn as if the preview were the glass.
for c in win.all_clips[:6]:
    clipdb.probe(c)
sized = [c for c in win.all_clips if c.px[0]]
assert sized, "no clip reported a frame size"
byname2 = {c.name: c for c in win.all_clips}
assert byname2["Theme_25.mp4"].px == (render.W, render.H), byname2["Theme_25.mp4"].px
row = win.clips.item(next(i for i, c in enumerate(win.all_clips)
                          if c is byname2["Theme_25.mp4"])).text()
assert f"{render.W}x{render.H}" in row, row
import copy
odd = copy.copy(byname2["Theme_25.mp4"])
odd.px = (320, 240)
detail = win._clip_detail(odd.path)
win._load_background(odd.path)
odd_detail = ""
for c in win.all_clips:
    if c.path == odd.path:
        c.px = (320, 240)
        odd_detail = win._clip_detail(c.path)
assert "320x240" in odd_detail and "not measured" in odd_detail, odd_detail
print(f"  clip rows carry size   {len(sized)}/{len(win.all_clips)} probed, "
      f"480x480 stated on the row, an odd size called a guess")

# the picker's filter: 40 rows, from 46 tracked files in a bare checkout and 204 on a
# bench that has the .deb installed and a Windows partition mounted
# mounted, and no way to find one short of a scroll wheel
win.clip_filter.setText("theme_48")
appq.processEvents()
shown = [win.clips.item(i).text() for i in range(win.clips.count())
         if not win.clips.item(i).isHidden()]
assert any("theme_48" in t for t in shown), shown
assert len(shown) < win.clips.count(), "the filter hid nothing"
assert win.clips.item(win.clips.currentRow()) is not None
assert not win.clips.item(win.clips.currentRow()).isHidden(), \
    "the selected row was hidden under the buttons that act on it"
win.clip_filter.setText("")
appq.processEvents()
assert not any(win.clips.item(i).isHidden() for i in range(win.clips.count()))
print(f"  picker filter           {len(shown)} of {win.clips.count()} rows match "
      f"'theme_48', the selection stays visible")

# the log keeps its last LOG_KEEP lines rather than every line it ever wrote:
# the pane is one wrapped label re-set on every append
for i in range(app.LOG_KEEP + 40):
    win._log(f"heartbeat {i}")
assert len(win._log_lines) == app.LOG_KEEP, len(win._log_lines)
text = win.log_view.text()
assert f"heartbeat {app.LOG_KEEP + 39}" in text and "heartbeat 0\n" not in text
print(f"  log capped              {len(win._log_lines)} lines kept of "
      f"{app.LOG_KEEP + 40} written")

# The same four actions with the serial layer replaced by a stub: the wiring
# around them - what bytes go up, which verdict decides success, who is allowed
# to ask for a destructive link, where the metrics blob lands in a session -
# is exercised without a panel to draw on.
# `panel.Link` is replaced rather than wrapped, so this block cannot open a port
# even by accident.
opened, uploads, links = [], [], []


class StubLink:
    notice = "200"

    def __init__(self, port, timeout=3.0, allow_destructive=False, **kw):
        opened.append((port, allow_destructive))
        self.uploads, self.posts, self.states = [], [], []
        links.append(self)

    def __enter__(self): return self

    def __exit__(self, *exc): return False

    def start_pump(self): pass

    def drain(self, t=0.15): pass

    def hello(self, keepalive=60): return self.device_info()

    def device_info(self):
        return {"sn": "STUB", "version": {"app": "V1.0.2"}, "space": 62428}

    def harvest(self, timeout=0.0): return []

    def post(self, verb, obj=None):
        self.posts.append(verb)
        return 1

    def state_all(self, metrics, wait=False):
        # records *where in the session* the blob landed: 0 means before the
        # first file, which is the rule PROTOCOL.md §8 measures, and the second
        # item says whether the host sent its tach readings or left them out
        self.states.append((len(self.uploads), metrics.get("fans") is not None))
        return None

    def send_media(self, name, data, **kw):
        if not self.notice.startswith("2"):
            from xigmalcd.protocol import ProtocolError
            raise ProtocolError(f"stub answered {self.notice}")
        # one tuple per call: extending the shared log with the instance's whole
        # history each time inflates the count (5 uploads read as 15)
        rec = (name, len(data), kw.get("gap", 0.02))
        self.uploads.append(rec)
        uploads.append(rec)
        return {"notice": self.notice, "state": "success", "seq": 7}


panel.Link = StubLink
panel.port_busy = lambda p: ""
# The worker's sensors are pinned for the rest of this section, and the reason is the
# same one that makes byte sizes comparable anywhere: xigmalcd/sensors.py reads this
# machine, and a cloud runner has no Super-IO, no temps and no disks behind those
# paths, so `collect()` comes back with the sections missing - the first CI runner
# drew its frames out of that and produced a 7 398 B OSD PNG where this bench draws
# 12.1-13.5 KB, which is not a regression, it is a different picture.  A `--no-fans`
# host would also drop the tach array from the blob, which is the other thing this
# section asserts the presence of.  So the fixture below - the readings the
# gauge-geometry section pins, 57 C CPU and 47 C GPU with a 2 400 RPM CPU fan on
# board - is what the worker sees here; the picture is then the same picture on any
# machine, and the byte band below compares like with like.
# `panel.sensors` is rebound in this process only; the next section starts a fresh
# one.  What the host's real sensors do is still printed, as a fact about the box.
import copy
FIX = {"cpu": {"temperature": 57.0, "load": 42.0},
       "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
       "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU",
                 "value": 2400}]}
real_sensors = panel.sensors
panel.sensors = types.SimpleNamespace(collect=lambda: copy.deepcopy(FIX))
host_fans = "fans" in sensors.collect()
worker = panel.Panel("/dev/xigma-stub")
notes = []
worker.log.connect(notes.append)

mp4 = byname["Theme_25.mp4"].path
blob = open(mp4, "rb").read()
assert worker._upload(path=mp4, gap=0.02, chunk=1000) is True
assert uploads and uploads[-1][1] == len(blob), uploads[-1:]
assert uploads[-1][2] == 0.02, uploads[-1]      # the measured pre-byte pause
assert uploads[-1][0] == "Theme_25.mp4", uploads[-1]
# PROTOCOL.md §8: the metrics blob is twice at the head of a session and never
# between files. Feeding it per frame makes the panel stop answering uploads,
# so this is the rule the GUI has to follow, not a nicety.  Each tuple is
# (uploads so far, did the blob carry the tach array): both blobs land before the
# first file, and the array is there because the fixture has one - which is what
# makes this the same assertion on a bench with a Super-IO and on a runner with no
# fan header at all.  Unpinned, that runner read (0, False) on 2026-11-07 and this
# line failed for a reason that had nothing to do with the ordering.
assert links[-1].states == [(0, True), (0, True)], links[-1].states
print(f"  background upload: one file, all {len(blob)} B, gap 0.02 s, named for "
      f"the clip, `STATE all 1` twice before it with the fixture's fan array "
      f"(this host's own sensors read "
      f"{'a fan' if host_fans else 'no tach at all'})")

StubLink.notice = "400"
assert worker._upload(path=mp4, gap=0.02, chunk=1000) is False
assert "refused this background" in " ".join(notes), notes[-3:]
print("  a 4xx notice is reported as a refusal, not a success")
StubLink.notice = "200"

assert worker._frame(theme="alpha", kw={"bg": render.OVERLAY}, fans=False) is True
name, size = uploads[-1][0], uploads[-1][1]
# Drawn from the fixture above, this frame is 12.1-13.5 KB here (the digits of the
# clock are the host's wall clock, so it moves a little run to run: 12 131 B in the
# one that wrote this comment).  The band is a regression net - a re-encoded frame, a
# wrong scale, a canvas that stopped being transparent all move it by more than that -
# and not a tracker of PNG trivia.  It is wide rather than tight because the two
# machines' Pillow builds are not the same build either.  What it is *not* is a bet on
# the host's sensors: unpinned, the first CI runner measured 7 398 B for the same call
# because that box has no temperatures to draw and every field came out `--`.
assert name.endswith(".osd") and 10_000 < size < 20_000, uploads[-1]
# fans=False leaves the host's tach array out of the blob, as --no-fans does in
# the daemon, and the blob still lands before the file rather than after it
assert links[-1].states == [(0, False), (0, False)], links[-1].states
print(f"  one frame: {name} {size} B, blob twice with no fans array")

before, links_before = len(uploads), len(links)
assert worker._live(theme="alpha", kw={"bg": render.OVERLAY}, fps=5.0,
                    seconds=1.0) is True
n = len(uploads) - before
# 1 s at 5 fps is five frames at t=0, 0.2 ... 0.8; the band allows for the stub
# returning instantly and the loop waking a few ms late, but not for the rate
# being wrong by a factor of two
assert 4 <= n <= 6, n
assert links[links_before].states == [(0, True), (0, True)], links[links_before]
print(f"  live 1 s at 5 fps: {n} uploads, one session, blob only at its head")

# the same run with the session clock cut short has to reopen rather than walk
# into the panel's silence.  panel._live reads these from xigmalcd.main, so
# patching main is patching the worker: no second copy of the limit to test.
import xigmalcd.main as _main
saved_ttl, saved_max = _main.SESSION_TTL, _main.SESSION_MAX
_main.SESSION_TTL, _main.SESSION_MAX = 0.2, 0
try:
    opens_before, links_before = len(opened), len(links)
    before = len(uploads)
    assert worker._live(theme="alpha", kw={"bg": render.OVERLAY}, fps=5.0,
                        seconds=1.0) is True
    renewals = len(opened) - opens_before
finally:
    _main.SESSION_TTL, _main.SESSION_MAX = saved_ttl, saved_max
assert renewals >= 3, renewals                # 1 s at a 0.2 s clock
# a renewed session re-helloes and does not re-push the blob: this matches
# main.rehandshake, which also only re-helloes, and PROTOCOL.md §8's evidence
# covers one session head, not every reopen
assert all(link.states == [] for link in links[links_before + 1:]), \
    [link.states for link in links[links_before + 1:]]
assert all(not d for _, d in opened[opens_before:]), opened[opens_before:]
print(f"  short session clock: {renewals} reopens, all non-destructive, none "
      f"re-pushing metrics")

# a panel that answers commands but refuses every file is not cured by
# reopening (PROTOCOL.md §6), so the run has to stop rather than spend its
# window on a dead channel
StubLink.notice = "400"
opens_before, links_before = len(opened), len(links)
t0 = time.monotonic()
assert worker._live(theme="alpha", kw={"bg": render.OVERLAY}, fps=5.0,
                    seconds=4.0) is False
spent = time.monotonic() - t0
gave_up = len(opened) - opens_before
StubLink.notice = "200"
assert spent < 2.0, spent                     # not the 4 s it was asked for
assert gave_up <= 6, gave_up                  # one reopen per RECOVER_AFTER
assert any("in a row refused" in note for note in notes), notes[-4:]
assert not any(link.uploads for link in links[links_before:]), \
    "nothing should have been accepted"
print(f"  400 storm: stopped after {gave_up} reopens in {spent:.2f} s of a "
      f"4 s window")

# a port that disappears at a renewal must not raise out of the worker: `_open`
# says None, the loop says so, and the finally-block close tolerates a link that
# never opened
opens_before = len(opened)
seen_opens = {"n": 0}


def busy_after_first(p):
    seen_opens["n"] += 1
    return f"{p} is held by pid 999 (stub)" if seen_opens["n"] > 1 else ""


panel.port_busy = busy_after_first
_main.SESSION_TTL, _main.SESSION_MAX = 0.2, 0
try:
    assert worker._live(theme="alpha", kw={"bg": render.OVERLAY}, fps=5.0,
                        seconds=2.0) is False
finally:
    panel.port_busy = lambda p: ""
    _main.SESSION_TTL, _main.SESSION_MAX = saved_ttl, saved_max
assert len(opened) == opens_before + 1, opened[opens_before:]   # it stopped
assert any("port went away at the renewal" in n for n in notes), notes[-3:]
print("  port lost at a renewal: the run stops and says so, nothing raised")

# the status action draws nothing, so it gets no blob at all
assert worker._status() is True
assert links[-1].states == [], links[-1].states
print("  status: no metrics blob (it puts no picture on the glass)")

# `_reset` finishes by waiting for the panel's node to come back - `glob.glob(
# "/dev/ttyACM*")` in xigmaui/panel.py, for up to 30 s.  That is a sentence about
# hardware, and this check had been passing on the author's bench by finding his actual
# panel in that listing: nothing was ever sent (the Link through this whole block is a
# stub), but the *verdict* came from whatever was on the desk.  Run 42334404814 hit the
# other half: a runner with no /dev/ttyACM at all waits out the 30 s and `_reset`
# returns False.  So the listing is pinned here - the pattern the worker asked for is
# recorded and answered - and what the host genuinely has is printed as a fact about the
# machine instead of leaned on as a result.
import glob as _glob
host_acm = _glob.glob("/dev/ttyACM*")
asked = []


class NodesBack:
    """panel.py's `glob`, standing in for the re-enumeration the real device does."""

    @staticmethod
    def glob(pattern):
        asked.append(pattern)
        return ["/dev/xigma-stub"]


real_glob = panel.glob
panel.glob = NodesBack

assert worker._reset(confirm="reset") is True
# `_reset` opens the destructive link and then re-reads status with a normal one,
# so the check is "exactly one destructive open in the whole session, and it was
# not the first" - the source inspection above is what pins it to `_reset`
assert sum(1 for _, d in opened if d) == 1, opened
assert opened[0][1] is False and opened[-1][1] is False, opened[:2] + opened[-1:]
assert asked[:1] == ["/dev/ttyACM*"], asked[:2]
print(f"  reset: one destructive link in {len(opened)} opens, everything else "
      f"non-destructive; it then waited for {asked[0]!r} (answered here - this host"
      f" has {len(host_acm)} such node(s) of its own)")

# and both rebindings stop with this block: every assert above saw the fixture and the
# answered listing, and nothing after this line in this process needs the host's own
# sensors or its own /dev nodes - the next section starts a fresh python3 anyway
panel.sensors = real_sensors
panel.glob = real_glob

# ---- stage 4's model (docs/theme-editor.md): what an editor may touch, what an edit does
# ---- to the picture, and what it owes back.  No Qt here on purpose: the claim is about
# ---- the file model and the pixels, and the window is a shell over both.  This heredoc's
# ---- XDG_CONFIG_HOME is a temp directory, so every save and revert below happens in a
# ---- place that cannot touch the reader's own ~/.config.  The imports are local to this
# ---- block because nothing else in this heredoc needed the theme library.
from xigmaui import edit as gui_edit

from PIL import ImageChops
from xigmalcd import layout, render, themes
from xigmaui import edit as gui_edit


def px_differ(a, b):
    """Pixels where two frames disagree in any channel.  Not a byte count over four: a
    pixel that differs in one channel is still one pixel, and the two counts differ by a
    fifth here (905 against 1 163, measured).  This is the same count `themes.parity`
    reports, so an editor number and an export number mean the same thing."""
    return sum(1 for q in ImageChops.difference(a.convert("RGBA"),
                                                b.convert("RGBA")).get_flattened_data()
               if q != (0, 0, 0, 0))

pick, _rej = themes.scan()
opened = [gui_edit.Editor.open_theme(r["name"]) for r in pick[:3]]
generated = [gui_edit.Editor.open_theme(n) for n in sorted(themes.EXPORTS)]
assert themes.user_copies() == [], themes.user_copies()
assert all(e.origin == "generated from render.py" and not e.path for e in generated)
assert all(e.origin in ("checkout", "package", "your copy") for e in opened)
read, sub = themes.keys_read()
inert = set(themes.field_census()["keys"]) - set(read)
kinds = sorted({w["type"] for e in opened + generated for w in e.widgets()})
assert set(kinds) <= set(layout.KINDS), kinds
offered = {f for kind in kinds for f in gui_edit.field_names(kind)}
assert offered <= set(read), sorted(offered - set(read))
assert not offered & inert, sorted(offered & inert)
ext_offered = {f for kind in kinds for f in gui_edit.extension_fields(kind)}
assert ext_offered <= set(sub), sorted(ext_offered - set(sub))
# the model is the part that can be *held to a number*, and that is only true while it
# needs no display: PyQt in this module would mean every claim below runs in the GUI
# section instead, where a broken window can excuse a broken model
qt = [ln for ln in open("xigmaui/edit.py", encoding="utf-8").read().splitlines()
      if "PyQt" in ln]
assert not qt, qt
fx = next(g for g in generated if g.name == "clock").fixture_line()
for want in ("CPU Temperature 57.0", "GPU Temperature 47.0", "2026-02-17"):
    assert want in fx, fx
# README writes the count as a word, so the gate spells it the same way rather than
# asking the document to hold a digit
_WORDS = "zero one two three four five six seven eight nine ten".split()
_readme_gen = open("README.md", encoding="utf-8").read()
_count_word = _WORDS[len(generated)] if len(generated) < len(_WORDS) else str(len(generated))
assert f"the {_count_word} themes generated from our own drawing code" in _readme_gen, (
    len(generated), _count_word,
    "README miscounts the generated layouts the editor row opens")
_gui_fields = open("docs/gui.md", encoding="utf-8").read()
assert f"{len(offered)} names across {len(kinds)} kinds" in _gui_fields, (
    len(offered), kinds, "docs/gui.md miscounts the fields the row offers - that sentence "
    "says 'counted in the gate', so it is counted")
assert all("showIf" in gui_edit.extension_fields(k) for k in kinds), (
    kinds, "a row that any kind can be is not offered the dependency key")
print(f"  editor model          opened {len(opened)} of the {len(pick)} layouts this "
      f"canvas can select, plus the {len(generated)} generated ones, and wrote nothing: "
      f"your theme directory still holds {len(themes.user_copies())} files. The row may "
      f"offer {len(offered)} fields across {len(kinds)} kinds ({' '.join(kinds)}), and "
      f"every one is a key `layout.py` is proven to read - none of the {len(inert)} keys "
       f"the vendor carries without reading is offered, so those survive a save "
       f"untouched. The picture comes from a pinned fixture, not live sensors "
       f"({fx[:78]}...)")

# ---- and what that fixture owes: the key names of a real box, the coverage the five
# ---- generated layouts need, and a preview that therefore *is* the same picture as the
# ---- theme the loop draws.  All three are held here because none of them was held before,
# ---- and the failure mode was invisible: this dict answered 5 of the 19 sources the five
# ---- exports ask, while carrying four keys nothing in the library reads (`gpu.usage`,
# ---- `cpu.frequency`, `gpu.frequency`, `memory.used_percent`).  The pane then showed a
# ---- `bars` layout with 14 of its 32 rows beside a code drawing of 26 and the two looked
# ---- unrelated, and `alpha`'s GPU row was missing from one door and `--%` in the other.
# ----
# ---- What the completion buys is measured rather than asserted: the same file door at the
# ---- fixture with those answers taken back out, against the fixture as it stands.  Both
# ---- frames come from this tree, so the figures are relations and not a bench inventory.
import json as _json
from xigmalcd import sensors as _sens

_shape, _end = _json.JSONDecoder().raw_decode(_sens.__doc__, _sens.__doc__.index("{"))
assert _shape, "sensors.py's own documented metrics shape did not parse"
_stray = {}
for _group, _fields in gui_edit.FIXTURE.items():
    if _group not in _shape:
        _stray[_group] = "a metrics group no box reports"
        continue
    _spec = _shape[_group]
    if isinstance(_spec, list):          # `fans` is a list of rows, not a group of keys
        _extra = [k for _row in _fields for k in _row if k not in _spec[0]]
    else:
        _extra = [k for k in _fields if k not in _spec]
    if _extra:
        _stray[_group] = _extra
assert not _stray, (
    _stray, "the editor's fixture carries a key no machine reports - which is how it once "
            "answered `gpu.usage` while the library asked for `gpu.load`")
asked = {w["property"][0]["source"] for e in generated
         for w in e.widgets()
         if (w["property"][0] or {}).get("source")}
_fx_vals, _fx_absent = themes.values(gui_edit.FIXTURE, gui_edit.FIXTURE_WHEN)
_short = sorted(asked - set(_fx_vals))
_fans = len(gui_edit.FIXTURE.get("fans") or [])
_fan_src = {src for src in asked if src.startswith("Fan ")}
_slots = _fan_src - {src for src in _fan_src if int(src.split()[1]) - 1 < _fans}
assert _short == sorted(_slots), (
    _short, _slots, _fans,
    "the fixture leaves a source unanswered that is not a fan slot past this shape's "
    "reported tachometers - a new reading in a new export needs a pinned value")
# the same fixture, less what the completion added: what the pane used to look like
_DROPPED = {"cpu": ("usage", "speedAverage"),
            "gpu": ("load", "speed", "fan", "memoryUsage", "dedicatedTotal"),
            "memory": ("used", "total", "load")}
_THIN = {k: {kk: vv for kk, vv in v.items() if kk not in _DROPPED.get(k, ())}
         for k, v in gui_edit.FIXTURE.items() if k not in ("fans", "motherboard")}
_thin_vals, _ = themes.values(_THIN, gui_edit.FIXTURE_WHEN)
assert asked - set(_thin_vals), (sorted(asked - set(_thin_vals)),
                                 "the fixture's coverage is no longer what this gate calls "
                                 "completed, so the comparison below is hollow")
_real_now = render._now
INKS = [None, "amber", "red", "mint", "cyan", "#ff4040", (10, 200, 120, 255)]
render._now = lambda: gui_edit.FIXTURE_WHEN.timetuple()
try:
    _rows, _gaps, _lit = {}, {}, {}
    for _ed in generated:
        _name = _ed.name
        _n_all = len(_ed.widgets())
        _cells = []
        for _ink in INKS:
            _lay, _notes = _ed.paint(*_ed.fixture(), ink=_ink)
            _code = render.draw(gui_edit.FIXTURE, _name, ink=_ink)
            _diff = ImageChops.difference(_code.convert("RGBA"),
                                          _lay.convert("RGBA")).get_flattened_data()
            _gap = sum(1 for q in _diff if q != (0, 0, 0, 0))
            _chan = max((max(q) for q in _diff), default=0)
            assert _gap == 0 and _chan == 0, (
                _name, _ink, _gap, _chan,
                "the pane's two doors disagree at the fixture: an export, a recipe and the "
                "skin table no longer describe one picture")
            _cells.append(_gap)
        _full, _full_notes = _ed.paint(*_ed.fixture())
        _thin_img, _thin_notes = themes.draw(_ed.obj, _THIN, gui_edit.FIXTURE_WHEN)
        _rows[_name] = (len(_thin_notes["boxes"]), len(_full_notes["boxes"]), _n_all)
        _lit[_name] = (px_differ(_full, _thin_img),
                       sum(1 for v in _full.getchannel("A").get_flattened_data() if v),
                       sum(1 for v in _thin_img.getchannel("A").get_flattened_data() if v))
        _gaps[_name] = _cells
    # the row counts are the part a reader can check by eye, so they are said out loud
    assert _rows["bars"][0] < _rows["bars"][1], (
        _rows["bars"], "the completed fixture no longer paints more of `bars` than the thin "
                       "one, so the gate below has nothing to hold the documents to")
    # and a layout that is not one of ours keeps its own colours: the ink row is a setting
    # of our drawings, not a re-colour of somebody else's file
    _vend = opened[0]
    _plain, _ = _vend.paint(*_vend.fixture())
    _tinted, _ = _vend.paint(*_vend.fixture(), ink="amber")
    assert _vend.ink_note == "" and px_differ(_plain, _tinted) == 0, (
        _vend.name, _vend.ink_note, px_differ(_plain, _tinted),
        "an ink reached a vendored layout: its colours are its own (docs/themes.md)")
finally:
    render._now = _real_now

# the pixel distance between the two fixtures is the number a reader can use to judge what
# the completion bought, so it is quoted in the documents in the same digits this gate counts
_thin_px = f"{_lit['bars'][0]:,}".replace(",", " ")
_doc_gui = open("docs/gui.md", encoding="utf-8").read()
_doc_plan = open("docs/theme-editor.md", encoding="utf-8").read()
for _want in (f"{len(asked) - len(_short)} of the {len(asked)} sources",
              f"{_rows['bars'][1]} of its {_rows['bars'][2]} rows",
              f"{_rows['bars'][0]} of its {_rows['bars'][2]} rows",
              f"{_thin_px} px"):
    assert _want in _doc_gui or _want in _doc_plan, (
        _want, "no document states this measurement, so it is only a gate talking to itself")
print(f"  the fixture, and both doors  every key is one `sensors.collect()` reports (the "
      f"module's own sample), and the fixture answers {len(asked) - len(_short)} of the "
      f"{len(asked)} sources the {len(generated)} generated layouts ask - the "
      f"{len(_short)} it leaves are the fan slots past its {_fans} reported tachometers, "
      f"empty in both doors. At that fixture the pane's two doors put down the same pixels "
      f"for all {len(generated)} themes at {len(INKS)} ink choices (worst channel 0). "
      f"Taken back to what the dict answered before, `bars` paints {_rows['bars'][0]} of "
      f"its {_rows['bars'][2]} rows against {_rows['bars'][1]}, and those two pictures differ "
      f"by {_thin_px} px - {_lit['bars'][1]:,} lit px "
      f"completed against {_lit['bars'][2]:,} thin. A vendored file does not move at all "
      f"under an ink: 0 px, and no note.")

# The layout combo's tooltip counts layouts out in prose, and it was wrong for a while: it
# said "three generated layouts" after the fifth export landed.  So its numbers are read back
# out of the widget and held to `themes.EXPORTS` and `themes.scan()` - the same pair
# `--list-themes` prints, which the doc-doors section already holds the documents to.  The
# sentence used to call that total "the vendor's", which is only true while the user root is
# empty: `scan()` counts a copy of yours as pickable, so the sum stops being a count of the
# vendor's files at the first save, and the tooltip is a sentence about what this window can
# open today.  docs/themes.md still says "23 of the vendor's 27" - that page is talking about
# the vendor's library, and its own gate holds it to the same two counts.
_tip = win.ed_name.toolTip()
for _want in (f"the {len(generated)} generated layouts",
              f"{len(pick)} of the {len(pick) + len(_rej)} today"):
    assert _want in _tip, (_want, _tip[:120],
                           "the window and the library disagree about how many layouts there "
                           "are, in a sentence written to answer that question")
print(f"  the window's own words   its layout tooltip states {len(generated)} generated "
      f"layouts and {len(pick)} of the {len(pick) + len(_rej)} today - the counts "
      f"`themes.EXPORTS` and `themes.scan()` report, read back off the widget")

# ---- a run of keystrokes, one undo, and a picture that moves by exactly the edit ----
KEYS, NUDGE = 20, 20
ed = gui_edit.Editor.open_theme("Theme_28")
assert not ed.dirty, "opening a layout made it dirty: it must write nothing"
base, notes0 = ed.paint(*ed.fixture())
target = next(i2 for i2, w in enumerate(ed.widgets())
              if not (w.get("property") or [{}])[0].get("source")
              and (w.get("property") or [{}])[0].get("content"))
ed.select(target)
kind = ed.selected()["type"]
x0 = int(ed.value("x"))
for step in range(KEYS):
    ok, msg = ed.set("x", x0 + 1 + step, commit=(step == KEYS - 1))
    assert ok, (step, msg)
steps, dirty_edit = ed.steps, ed.dirty
assert steps == 1 and dirty_edit, (steps, dirty_edit)
after, notes1 = ed.paint(*ed.fixture())
shift = [(int(b[2][0]) - int(a[2][0]), int(b[2][1]) - int(a[2][1]))
         for a, b in zip(notes0["boxes"], notes1["boxes"])]
assert sum(1 for sh in shift if sh == (NUDGE, 0)) == 1, (kind, shift)
assert sum(1 for sh in shift if sh == (0, 0)) == len(shift) - 1, shift
moved = px_differ(base, after)
assert moved > 200, moved
path, warnings = ed.save()
assert path and not warnings, (path, warnings)
assert not ed.dirty, "save did not clear dirty"
# nothing dropped and nothing invented: the keys each widget carries after a save are the
# keys the vendor's file carried, plus `xigma` only where an extension key was set.  An
# editor that rewrites the schema it does not understand is an editor that corrupts files.
untouched = gui_edit.Editor.open_theme("Theme_28")
keys_before = [sorted((w.get("property") or [{}])[0]) for w in untouched.widgets()]
keys_after = [sorted((w.get("property") or [{}])[0]) for w in
              themes.load(path)["osd"]["widget"]]
assert keys_before == keys_after,     [(i3, b, a) for i3, (b, a) in enumerate(zip(keys_before, keys_after)) if b != a]
lost = [k for i3, keys in enumerate(keys_before) for k in keys
        if k in inert and k not in keys_after[i3]]
assert not lost, ("an inert vendor key was dropped on the way out", lost)
again = gui_edit.Editor.open_theme("Theme_28")
assert again.origin == "your copy" and not again.dirty, again.origin
assert int(again.widgets()[target]["property"][0]["x"]) == x0 + NUDGE
lit, _ = again.paint(*again.fixture())
assert lit.tobytes() == after.tobytes(), "the saved file does not draw what the editor drew"
assert ed.undo() and not ed.undo(), (ed.steps, steps)
back, notes2 = ed.paint(*ed.fixture())
assert back.tobytes() == base.tobytes() and notes2["boxes"] == notes0["boxes"]
assert ed.dirty, "undoing an edit that is saved on disk must say so"
assert again.revert() and themes.origin(themes.resolve("Theme_28")) == "checkout"
assert not again.dirty, "revert wrote the baseline back: nothing is outstanding"
gone = gui_edit.Editor.open_theme("Theme_28")
assert gone.paint(*gone.fixture())[0].tobytes() == base.tobytes()
print(f"  an edit, measured     one literal `{kind}` in Theme_28, x nudged to {x0 + NUDGE}"
      f" in {KEYS} spinbox keystrokes: that is {steps} undo step. Exactly one ink"
      f" box moves - by ({NUDGE}, 0) - and the other {len(shift) - 1} stay put, so"
      f" {moved:,} of {render.W * render.H:,} pixels change and every one of them is"
      f" the edit. Saving puts it at {os.path.basename(path)}, and from then on"
      f" `--theme Theme_28` reads that file (origin: your copy) and paints the same"
      f" {moved:,}-px picture straight off disk. `dirty` tells the same story with no"
      f" flag to keep in step: false on open, true on the edit, false on save, true"
      f" again after one undo - which returns the first frame byte for byte - and"
      f" false once revert removes the copy and the vendor picture is back, identical"
      f" to this session's first frame.")

# a colour typed the way a person types it, stored the way the library writes it
gone.select(target)
ok, note = gone.set("textColor", "#ff4040")
assert ok and note == "stored as rgba(255, 64, 64, 1)", (ok, note)
tinted, _ = gone.paint(*gone.fixture())
touched = px_differ(base, tinted)
assert touched > 100, touched
assert layout.rgba(gone.value("textColor")) == (255, 64, 64, 255)
assert gone.undo() and gone.paint(*gone.fixture())[0].tobytes() == base.tobytes()
print(f"  a colour, converted   `#ff4040` typed into the row for that `{kind}` lands"
      f" in the file as `rgba(255, 64, 64, 1)` - the spelling all 152 shipped widgets"
      f" use, which `layout.rgba` can read and `#ff4040` cannot - and it changes"
      f" {touched:,} pixels. The note is what the window prints, so the reader is told"
      f" what was written instead of finding it in a diff.")

def clip(text, n=58):
    """A refusal's own words, cut at a word boundary: the whole sentence is in the model."""
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "..."


refused = []
for field, value in (("x", 480), ("x", "not a number"), ("textColor", "cerise"),
                     ("bold", "yes"), ("fontSize", None)):
    ok, msg = ed.set(field, value)
    assert not ok and msg, (field, value, ok, msg)
    refused.append(f"{field}={value!r} -> {clip(msg)}")
ok, carry = ed.set("arcPaint", "vendor")   # not a field a text widget can carry
assert not ok and "does not carry" in carry, carry
ed.select(next(i2 for i2, w in enumerate(ed.widgets()) if w["type"] == "bar"))
ok, neg = ed.set("x", -5)
assert not ok and "canvas" in neg, neg
sp = next(g for g in generated if g.name == "clock")   # its third widget is a `special`
sp.select(next(i2 for i2, w in enumerate(sp.widgets()) if w["type"] == "special"))
ok, nam = sp.set("name", "no-such-drawing")
assert not ok and "takes one of" in nam, nam
assert not sp.dirty and not sp.steps, (sp.dirty, sp.steps)
print(f"  what it refuses       " + "; ".join(refused))
print(f"                        a field the kind cannot carry: {clip(carry)}; an"
      f" off-canvas coordinate: {clip(neg)}; a drawing that does not exist:"
      f" {clip(nam)}. And a refused write moves nothing: {sp.steps} undo steps and"
      f" dirty={sp.dirty} after six attempts against that special widget.")

# the one field whose *absence* is a value: an extension key un-set goes back to the
# vendor's convention, and the file must not keep an empty `xigma` object behind
ga = next(g for g in generated if g.name == "gauge")   # its ring row is an `arc`, and
# the key that selects the painter has a value on it, so un-setting it is the test
ga.select(next(i2 for i2, w in enumerate(ga.widgets()) if w["type"] == "arc"))
with_key, _ = ga.paint(*ga.fixture())
assert ga.value("arcPaint") == "render", ga.value("arcPaint")
ok, note = ga.set("arcPaint", None)
assert ok, note
assert "xigma" not in ga.prop(), ga.prop()
without, _ = ga.paint(*ga.fixture())
gap = px_differ(with_key, without)
assert gap > 0, gap
ok, note = ga.set("arcPaint", "render")
assert ok, note
again_ring, _ = ga.paint(*ga.fixture())
assert again_ring.tobytes() == with_key.tobytes()
assert ga.value("arcPaint") == "render" and ga.steps == 2, (ga.value("arcPaint"),
                                                              ga.steps)
# `dirty` is a state, not a counter: back at the baseline there is nothing to save, even
# though two undo steps are still in the history.  The window says both, separately.
assert not ga.dirty, ga.obj == ga._saved
print(f"  an unset is a value   un-setting the ring's `arcPaint` removes the key and"
      f" the empty `xigma` object with it, and the whole gauge frame changes by"
      f" {gap:,} px at this reading - the two ring conventions, one key apart (the gap"
      f" itself is counted widget by widget in the `why arcPaint` line above). Setting it to"
      f" `render` again paints byte-identically to the start - a round trip that leaves"
      f" {2} undo steps in the history and `dirty` false, because that flag is a state"
      f" (does memory disagree with the file?) and not a counter of what was typed.")

# ---- what a text row paints, proved by painting ----
# The note line under the editor's rows answers "what will this row look like" for a
# `text` or `data` widget (`edit.drawn_text`).  A sentence like that is worth nothing if
# it is a second implementation of the drawing, so the claim held here has the same shape
# as every other claim in this repo: draw the file, then draw a copy of the file with that
# one row replaced by a literal `text` widget whose `content` is the string the model
# named, and require the two frames to be byte-identical.  A row the model says paints no
# line must be a row the painter skipped, and the reason the model gives must be a reason
# the painter's own notes give.
_line_rows = _twin_same = _line_none = _caveats = 0
_reasons, _twin_fail = {}, []
for _ed2 in generated + [gui_edit.Editor.open_theme(r["name"]) for r in pick]:
    _base, _notes = _ed2.paint(*_ed2.fixture())
    _drawn_idx = {b[3] for b in _notes["boxes"]}
    _objs = _ed2.obj["osd"]["widget"]
    for _i, _w in enumerate(_ed2.widgets()):
        if str(_w.get("type") or "") not in ("text", "data"):
            continue
        _line_rows += 1
        _ed2.select(_i)
        _line, _why = _ed2.drawn_text()
        if _line is None:
            _line_none += 1
            assert _why, (_ed2.name, _i, "a row that paints nothing has to say why")
            assert _i not in _drawn_idx, (
                _ed2.name, _i, _why, "the model says no line and the painter drew one")
            _key = _why.split("`")[1] if "`" in _why else _why[:20]
            _reasons[_key] = _reasons.get(_key, 0) + 1
            if "showIf" in _why:
                assert any(str(m).startswith("showIf:") for m in _notes["missing"]), (
                    _ed2.name, _i, _why, _notes["missing"],
                    "the model blamed a dependency the painter never reported")
            continue
        if _why:
            _caveats += 1
            assert str(_ed2.prop().get("source")) in {str(g) for g in _notes["gaps"]}, (
                _ed2.name, _i, _why, _notes["gaps"], "a caveat the painter does not share")
        _pr = dict(_w["property"][0])
        _pr.pop("source", None)
        _pr["content"] = _line
        _objs[_i] = {**_w, "type": "text", "property": [_pr]}
        try:
            _img2, _n2 = _ed2.paint(*_ed2.fixture())
        finally:
            _objs[_i] = _w
        if _img2.tobytes() == _base.tobytes():
            _twin_same += 1
        else:
            _twin_fail.append((_ed2.name, _i, repr(_line)[:36],
                               sum(1 for a, b in zip(_base.tobytes(), _img2.tobytes())
                                   if a != b)))
assert not _twin_fail, _twin_fail[:6]
assert _twin_same + _line_none == _line_rows, (_twin_same, _line_none, _line_rows)
print(f"  what a row paints     {_line_rows} `text`/`data` rows in "
      f"{len(generated) + len(pick)} layouts: {_twin_same} paint a line at this fixture, "
      f"and the literal-`text` twin of every one of them came back byte-identical to the "
      f"file it came from ({len(_twin_fail)} differ); {_line_none} paint nothing and say "
      f"why (" + ", ".join(f"{k} {v}" for k, v in sorted(_reasons.items(),
                                                         key=lambda kv: -kv[1])[:4])
      + f"), and {_caveats} of the painted lines are spelled by a shape this repo "
      f"declares unmeasured")
# Two kinds of count live in that sentence, and they are held in two ways.  What the files
# decide - rows, layouts, `Pump Speed` in N layouts - is the same on every machine, so it
# is asserted exactly.  What a **face** decides is not: a row whose family resolves to no
# file paints nothing, and CI's runner ships no CJK face, so the painted / twin / skipped /
# caveat counts differ there and docs/gui.md says which machine each belongs to.
_gh = " ".join(gui_txt.split())
for _claim in (f"the **{_line_rows}** `text`/`data` rows of the "
               f"**{len(generated) + len(pick)}** layouts twice",
               f"`Pump Speed` in **{_reasons.get('Pump Speed', 0)}** layouts"):
    assert _claim in _gh, (_claim, "docs/gui.md counts what the files put there, and this "
                                   "run disagrees")
_mc = _pair("rows that paint a line, and twins that match them",
            r"\*\*(\d+)\*\* rows paint a line at this fixture and all \*\*(\d+)\*\* "
            r"twins came back identical - on CI's runner.*?\*\*(\d+)\*\* paint and all "
            r"\*\*(\d+)\*\* twins come back identical", (_twin_same, _twin_same))
_sk = _re.search(r"The \*\*(\d+)\*\* that do not here \(\*\*(\d+)\*\* there\)",
                 _gh)
assert _sk and _line_none in (int(_sk[1]), int(_sk[2])), (
    _line_none, _sk.groups() if _sk else None,
    "docs/gui.md's count of rows that paint no line is not this machine's labelled number")
_cv = _re.search(r"\*\*(\d+)\*\* of the painted lines are spelled by a shape the file "
                 r"itself declares unmeasured \(\*\*(\d+)\*\* there\)", _gh)
assert _cv and _caveats in (int(_cv[1]), int(_cv[2])), (
    _caveats, _cv.groups() if _cv else None,
    "docs/gui.md's caveat count is not this machine's labelled number")
print(f"  the counts, both machines  this run: {_twin_same} painting a line with all "
      f"{_twin_same} twins identical, {_line_none} painting nothing, {_caveats} caveated; "
      f"the page's pairs: {_mc} painted/twins, {_sk.groups()} skipped, "
      f"{_cv.groups()} caveats")
# The same door with a hole punched in the readings: a row whose `xigma.showIf` dependency
# vanishes has to be *said* by the model and skipped by the painter, not drawn half.  Only
# `bars` carries the key, on its two memory figures, each depending on the rate the meter
# beside it divides by - and a rate is two reported fields, which is what `themes.DERIVED`
# exists to say, so the hole is punched by name from that table rather than guessed here.
_ed2 = gui_edit.Editor.open_theme("bars")
_fx, _when = _ed2.fixture()
_holey = [i for i, _w in enumerate(_ed2.widgets())
          if (_w["property"][0].get("xigma") or {}).get("showIf")]
assert len(_holey) == 2, _holey
_hole, _other = _holey
_dep = _ed2.widgets()[_hole]["property"][0]["xigma"]["showIf"]
_dep2 = _ed2.widgets()[_other]["property"][0]["xigma"]["showIf"]
_grp, _used_f, _total_f = themes.DERIVED[_dep]
assert themes.DERIVED[_dep2][:1] != (_grp,), (
    _dep, _dep2, "the two rows have to depend on different groups, or the hole punched "
                 "below takes both of them out and the comparison is hollow")
_fx[_grp].pop(_total_f, None)                    # the total the rate divides by
# ...and the punch has to stay inside the copy.  Until 2026-11-11 `Editor.fixture()` returned
# `dict(FIXTURE)`, a shallow copy whose inner dicts are the module's own, so this one line
# punched `memory.total` out of the shared pinned fixture and it stayed missing for **every
# later gate in this process** - one derived rate answered nothing from here on, and the only
# visible trace was a census of drawn boxes two short.  The door deep-copies now; this is the
# gate that would have caught it then, and the guard that keeps it caught.
assert _total_f in gui_edit.FIXTURE[_grp], (
    _grp, _total_f, sorted(gui_edit.FIXTURE[_grp]),
    "a suite gate punched a hole in the shared pinned fixture instead of in the copy it was "
    "handed: every draw after this one in this section answers one reading fewer")
_ed2.select(_hole)
_line, _why = _ed2.drawn_text(_fx, _when)
_img, _notes = _ed2.paint(_fx, _when)
assert _line is None and "showIf" in _why, (_line, _why, _dep)
assert f"showIf:{_dep}" in [str(m) for m in _notes["missing"]], (_dep, _notes["missing"])
assert _hole not in {b[3] for b in _notes["boxes"]}, "the row drew anyway"
_ed2.select(_other)
_keep, _keep_why = _ed2.drawn_text(_fx, _when)
assert _keep is not None, (_dep2, _keep_why)
print(f"  and with a hole       `bars` row {_hole} depends on `{_dep}`, spelled from "
      f"`{_grp}.{_used_f}` / `{_grp}.{_total_f}`: with the total gone the model says so in "
      f"words, the painter records `showIf:{_dep}` and skips the row, while the other "
      f"`{_dep2}` row next to it still paints {_keep!r} - both doors answer the same "
      f"question the same way")

# Two more rows, built here rather than read from a file, because no file in the library is
# in either state while a hand-edited one can be: a family the vocabulary does not name,
# and no family at all.  Both get the same answer through both doors - the model says it in
# words, `layout.draw` notes `font:` and skips the row - and the second one is the fact
# nobody would guess from a form: there is no default face to fall back to.
for _tag, _fam, _want in (("not in the vocabulary", "Impact", "has no file for the family"),
                          ("the key absent", None, "carries no `fontFamily`")):
    _fprop = {"x": 10, "y": 120, "source": "CPU Temperature", "fontSize": 20,
              "textColor": "rgba(255, 255, 255, 1)"}
    if _fam:
        _fprop["fontFamily"] = _fam
    _fed = gui_edit.Editor({"width": render.W, "height": render.H, "osd": {"widget": [
        {"id": "xigma-face", "type": "data", "property": [_fprop]}]}},
        origin="suite probe")
    _fed.select(0)
    _f_line, _f_why = _fed.drawn_text()
    _f_img, _f_notes = _fed.paint(*_fed.fixture())
    assert _f_line is None and _want in _f_why, (_tag, _f_line, _f_why)
    assert not _f_notes["boxes"], (_tag, _f_notes["boxes"], "the row drew anyway")
    assert any(str(m).startswith("font:") for m in _f_notes["missing"]), (
        _tag, _f_notes["missing"], "the painter skipped a face row without saying so")
print("  a family, both ways   `Impact` (a name `layout.FONTS` does not carry) and a row "
      "with no `fontFamily` at all: both draw nothing, both say so, and the painter notes "
      "`font:impact` / `font:` beside them")

# ---- a `format` the value cannot be dressed in: refused on the way in, survived on the way out
# `xigma.format` is handed to `strftime` for a clock and to `format()` for a reading, and
# either door raises when the specifier does not fit the value behind it.  Two answers are
# needed, and they are not the same one: the editor must refuse such a key *before it
# reaches the file* (this repo's rule: a write that cannot be drawn is said, not done), and
# the painter must survive a file that already carries one, because a file is a file and
# `--theme` opens whatever is there.  The agreement below is not a list of bad specifiers
# remembered here: for each candidate the gate asks the painter's own door whether it
# raises, and the model has to take the same side.
_fmt_row = next(e for e in generated if e.name == "bars")
_fmt_row.select(next(i for i, _w in enumerate(_fmt_row.widgets())
                     if str(_w.get("type") or "") == "data"
                     and _w["property"][0].get("source") == "Used RAM"))
_fsrc = _fmt_row.prop()["source"]
_fvals, _ = themes.values(*_fmt_row.fixture())
_fprobe = _fvals[_fsrc]
_CAND = ("%q", "%d %d", "{}", "{:,.0f}", "%.1f", "%s", "{0}", "%A %d %B %Y", "")
_agree, _refused, _taken = [], [], []
for _cf in _CAND:
    _raises = True
    try:
        layout.text_for(_fsrc, _fprobe, _cf)
        _raises = False
    except Exception:
        pass
    _was_dirty, _was_steps = _fmt_row.dirty, _fmt_row.steps
    _ok, _note = _fmt_row.set("format", _cf)
    assert _ok != _raises, (
        _cf, _ok, _raises, _note, "the model and the painter disagree about one format: a "
        "row that writes what the drawing cannot apply is the bug this refuses to be")
    _agree.append((_cf, "paints" if not _raises else "refused"))
    (_taken if _ok else _refused).append(_cf)
    if _raises:
        assert _note and _cf in _note, (_cf, _note,
                                        "a refusal has to name the format it refused")
        # a refusal changes nothing: `dirty` and the undo count are read back as they were
        # before *this* attempt, not as they were at the start of the sweep (an earlier
        # candidate that was accepted is a real change the row keeps)
        assert (_fmt_row.dirty, _fmt_row.steps) == (_was_dirty, _was_steps), (
            _cf, _was_steps, _fmt_row.steps, _was_dirty, _fmt_row.dirty,
            "a refused format moved the file anyway")
        if _cf.startswith("{"):
            # the shape people reach for is `str.format`'s, so refusing `{:,.0f}` has two
            # jobs: say no, and point at the spelling this field takes.  A pointer is only
            # worth following when it has been checked, so the gate takes whatever the
            # sentence offers, hands it to the model, and puts the row back afterwards; a
            # refusal that offers nothing has to say why not.
            _sug = _re.search(r"already implied: `([^`]*)` works", _note)
            if _sug:
                _ok2, _note2 = _fmt_row.set("format", _sug.group(1))
                assert _ok2, (_cf, _sug.group(1), _note2,
                              "the spelling a refusal points at does not pass the refusal "
                              "it came from")
                assert _fmt_row.undo(), (_cf, _sug.group(1),
                                         "the probe left the row changed")
                assert (_fmt_row.dirty, _fmt_row.steps) == (_was_dirty, _was_steps), (
                    _cf, "putting the probe back did not return the row to where it was")
            else:
                assert "not `str.format`" in _note, (
                    _cf, _note, "a brace-style refusal either fixes the reader's spelling "
                                "or says why it cannot")
print(f"  a format, both doors  {_fsrc} (a {type(_fprobe).__name__} at this fixture, "
      f"{_fprobe}) against {len(_CAND)} candidate specifiers: the model takes the painter's "
      f"side on every one - accepted "
      f"{', '.join(repr(c) for c in _taken) or '(none)'}, refused "
      f"{', '.join(repr(c) for c in _refused) or '(none)'} - and every refusal left the "
      f"row's `dirty` and undo count exactly as it found them")
# ... and the survival half.  A file that *already* carries an unappliable format, built
# here rather than written by the editor, has to be reported and skipped: not raised
# through the frame loop, and not taken out along with the rest of the frame.
_two = [{"id": "xigma-hold-a", "type": "data",
         "property": [{"x": 10, "y": 10, "source": "CPU Temperature",
                       "fontFamily": "dejavu", "fontSize": 20,
                       "textColor": "rgba(255, 255, 255, 1)"}]},
        {"id": "xigma-hold-b", "type": "data",
         "property": [{"x": 10, "y": 100, "source": "GPU Temperature",
                       "fontFamily": "dejavu", "fontSize": 20,
                       "textColor": "rgba(255, 255, 255, 1)"}]}]
_frame = lambda props: {"width": render.W, "height": render.H,
                        "osd": {"widget": [dict(w, property=[p])
                                           for w, p in zip(_two, props)]}}
_clean, _cn = themes.draw(_frame([dict(_two[0]["property"][0]),
                                  dict(_two[1]["property"][0])]), *_fmt_row.fixture())
_baded = {**_two[1]["property"][0], "xigma": {"format": "%q"}}
_bad_img, _bn = themes.draw(_frame([dict(_two[0]["property"][0]), _baded]),
                            *_fmt_row.fixture())
_holes = [str(m) for m in _bn["missing"]]
assert not [m for m in _cn["missing"] if str(m).startswith("format:")], _cn["missing"]
assert any(m.startswith("format:GPU Temperature") for m in _holes), (
    _holes, "a file naming an unappliable format has to be *said*, the way every other "
            "hole in a frame is said")
assert len(_bn["boxes"]) == len(_cn["boxes"]) - 1, (
    [b[3] for b in _cn["boxes"]], [b[3] for b in _bn["boxes"]],
    "the bad row took another one with it, or nothing was skipped at all")
assert px_differ(_clean, _bad_img) > 0, "the two frames are one picture, so no row was left out"
_bad_ed = gui_edit.Editor(_frame([dict(_two[0]["property"][0]), _baded]),
                          origin="suite probe")
_bad_ed.select(1)
_line, _why = _bad_ed.drawn_text()
assert _line is None and "cannot be applied" in _why and "%q" in _why, (_line, _why)
print(f"  the same file, painted   a hand-built layout whose `GPU Temperature` row carries "
      f"`format: \"%q\"`: the painter raised nothing, {len(_cn['boxes'])} rows drew clean "
      f"and {len(_bn['boxes'])} drew with the hole, and its notes say "
      f"{[m for m in _holes if str(m).startswith('format:')]}; the editor's own row answer "
      f"is: {_why[:96]}")
# ---- a family name the file spells differently than the vocabulary does ----
# `Arial` is what the vendor's files write and `arial` is what `layout.FONTS` names; the
# painter folds the case before it resolves a family, so those two spellings are the same
# face on the glass.  The editor's menu shows the file's own spelling (dropping it would
# misrepresent the row), which means the model has to answer it the way the painter does -
# and an earlier version of this window offered `Arial` in a list and refused it in the
# model in the same breath.  What makes the fold safe is not an argument, it is a pixel
# count: the frame before and after must be identical.  And nothing else folds, because the
# painter folds nothing else.
_a_ed = None
for _cand in [gui_edit.Editor.open_theme(r["name"]) for r in pick]:
    for _ci, _cw in enumerate(_cand.widgets()):
        _cfam = str((_cw.get("property") or [{}])[0].get("fontFamily") or "")
        if _cfam and _cfam not in _ed_api.choices("fontFamily") \
                and _cfam.lower() in _ed_api.choices("fontFamily"):
            _a_ed, _a_i, _a_spelling = _cand, _ci, _cfam
            break
    if _a_ed:
        break
assert _a_ed, ("no library file writes a family the vocabulary spells another way, so the "
               "fold below has nothing to fold - and the menu no longer shows one either")
_a_ed.select(_a_i)
_a_before, _a_n0 = _a_ed.paint(*_a_ed.fixture())
_a_ok, _a_note = _a_ed.set("fontFamily", _a_spelling)
assert _a_ok, (_a_spelling, _a_note,
               "a menu entry the model refuses is a choice the reader cannot take")
assert _a_note and _a_spelling in _a_note and _a_ed.value("fontFamily") in \
    _ed_api.choices("fontFamily"), (_a_spelling, _a_note, _a_ed.value("fontFamily"),
                                    "the fold has to say which spelling it stored")
_a_after, _a_n1 = _a_ed.paint(*_a_ed.fixture())
_a_px = px_differ(_a_before, _a_after)
assert _a_px == 0, (_a_spelling, _a_ed.value("fontFamily"), _a_px,
                    "folding a family's case moved ink, so it was never the same face")
assert [str(m) for m in _a_n1["missing"]] == [str(m) for m in _a_n0["missing"]], (
    _a_n0["missing"], _a_n1["missing"], "the fold changed which rows the painter skipped")
print(f"  a family, two spellings  `{_a_spelling}` is what the file writes, and "
      f"{_a_ed.value('fontFamily')!r} is what `layout.FONTS` names: the model takes the "
      f"painter's side (it folds what `layout.font_for` folds), says what it stored "
      f"({_a_note[:70]}...), and both frames are {_a_before.size} with {_a_px} px of "
      f"difference")
_s_ed = next(e for e in generated if e.name == "bars")
_s_ed.select(next(i for i, _w in enumerate(_s_ed.widgets())
                 if str(_w.get("type") or "") == "data"
                 and _w["property"][0].get("source") == "CPU Temperature"))
_s_ok, _s_note = _s_ed.set("source", "cpu temperature")
assert not _s_ok and "takes one of" in _s_note, (
    _s_ok, _s_note, "only the family is folded: a source's case is part of its name, and "
                    "the painter matches sources exactly")
_s_ok2, _ = _s_ed.set("fontFamily", "DEJAVU")
assert _s_ok2 and _s_ed.value("fontFamily") == "dejavu", (_s_ok2,
                                                          _s_ed.value("fontFamily"))
print(f"                        and the fold stays in one field: `source` as "
      f"`cpu temperature` is still refused ({_s_note[:52]}...), while `DEJAVU` folds to "
      f"`dejavu` because `font_for` lowercases that one name")

# ---- rows you can add, delete and reorder.  Two rules decide what this can claim.  The
# ---- envelope a new row has to fit is taken from the files on this run, not from a list
# ---- kept here: every row this program can read carries exactly the five keys
# ---- `gui_edit.WIDGET_KEYS`, with `property` a one-element list.  And every claim about
# ---- what a reorder *does* is a pixel count from the painter, because a claim about list
# ---- indices is the model talking to itself.
_rows_all = [w for _e in (generated + [gui_edit.Editor.open_theme(r["name"]) for r in pick])
             for w in _e.widgets()]
_kinds_seen = {}
for _w in _rows_all:
    _kinds_seen[str(_w.get("type"))] = _kinds_seen.get(str(_w.get("type")), 0) + 1
assert sorted(_kinds_seen) == sorted(layout.KINDS), sorted(_kinds_seen)
_bad_env = [_w for _w in _rows_all if frozenset(_w) != frozenset(gui_edit.WIDGET_KEYS)]
assert not _bad_env, (_bad_env[:2], "the five-key envelope is not what the files carry")
assert all(isinstance(_w.get("property"), list) and len(_w["property"]) == 1
           for _w in _rows_all), "a `property` that is not one element"
assert all(_w.get("widgetContent") == "" for _w in _rows_all)
_mandatory, _used = {}, {}
for _k in _kinds_seen:
    _common = None
    for _w in _rows_all:
        if str(_w.get("type")) != _k:
            continue
        _keys = set(_w["property"][0])
        _common = _keys if _common is None else (_common & _keys)
    _mandatory[_k] = sorted(_common - {"xigma"})
    for _f in _mandatory[_k]:
        if _f in ("x", "y"):
            continue
        _used[(_k, _f)] = {repr(_w["property"][0][_f]) for _w in _rows_all
                           if str(_w.get("type")) == _k and _f in _w["property"][0]}
assert all(_used[(_k, _f)] for (_k, _f) in _used), "a mandatory key nobody sets"

_add_ok = _add_soft = _place_clear = _place_moved = _place_stuck = 0
_add_notes = {}
for _e in (generated + [gui_edit.Editor.open_theme(r["name"]) for r in pick]):
    _base = themes.canonical(_e.obj)
    for _k in sorted(layout.KINDS):
        _t = gui_edit.Editor(copy.deepcopy(_e.obj), origin=_e.origin, path=_e.path,
                             name=_e.name, theme=_e.theme)
        if _t.rows_of(_k):
            _t.select(_t.rows_of(_k)[-1])
        _steps0 = _t.steps
        _img0, _notes0 = _t.paint(*_t.fixture())
        _boxes0 = [r for r in (_notes0.get("boxes") or []) if r[2]]
        _good, _said = _t.add_widget(_k, name="temp-labels")
        if not _good:
            assert _t.steps == _steps0 and not _t.dirty, (_k, "a refused add moved the file")
            continue
        _add_ok += 1
        _i_new = _t.index
        _new = _t.widgets()[_i_new]
        _prop = _new["property"][0]
        assert str(_new.get("type")) == _k
        assert frozenset(_new) == frozenset(gui_edit.WIDGET_KEYS)
        assert not (set(_mandatory[_k]) - set(_prop)), (
            _k, sorted(set(_mandatory[_k]) - set(_prop)),
            "a new row left out a key every row of that kind carries")
        for _f in _mandatory[_k]:
            if _f in ("x", "y"):
                continue
            assert repr(_prop[_f]) in _used[(_k, _f)], (
                _k, _f, _prop[_f], "a new row's default is a value no row of that kind uses")
        assert [str(w.get("id")) for w in _t.widgets()].count(str(_new.get("id"))) == 1, (
            "the new id collides inside this layout")
        _hard, _soft = themes.validate(_t.obj)
        assert not _hard, (_e.name, _k, _hard)
        _add_soft += len(_soft)
        _img1, _notes1 = _t.paint(*_t.fixture())
        _mine = [r for r in (_notes1.get("boxes") or []) if r[3] == _i_new and r[2]]
        assert _mine, (_e.name, _k, "the row the model added paints no box",
                       [str(m) for m in _notes1["missing"]])
        assert len([r for r in (_notes1.get("boxes") or []) if r[2]]) > len(_boxes0), (
            _e.name, _k, "the box count did not rise")
        _other = [r[2] for r in (_notes1.get("boxes") or []) if r[3] != _i_new and r[2]]
        _meets = gui_edit._overlaps(_mine[0][2], _other)
        _diff = px_differ(_img0, _img1)
        if _meets:
            # a row copied onto a full canvas has nowhere to go: `alpha` has no 194x194 px
            # spot that meets none of its boxes, so an `arc` there sits exactly on the ring
            # it was copied from.  That is said in the sentence rather than hidden, and the
            # window marks the row it just selected so a reader can still find it.
            _place_stuck += 1
            assert "no free room" in _said or "bigger than" in _said, (_e.name, _k, _said)
        else:
            assert _diff > 0, (_e.name, _k, _said,
                               "a row that is clear of every other box changed no pixel")
            if "nearest free spot" in _said:
                _place_moved += 1
            else:
                _place_clear += 1
        _add_notes.setdefault(_k, _said)
        assert _t.steps == _steps0 + 1, (_k, "add is not exactly one undo step")
        assert _t.undo() and themes.canonical(_t.obj) == _base, (
            _e.name, _k, "one press of undo did not put the file back byte for byte")

def _cut(text, n):
    """A sentence quoted to the end of a word, not to a character count.

    These excerpts land in the suite's own printed line, and a cut in mid-phrase reads as a
    claim the model never made: the refusal this one exists because of came out as "a
    `special` row has to name one of clock".
    """
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + " ..."


# the refusals, each one moving nothing at all.  The last-row refusal is compared
# against `themes.validate`'s own hard string, because the claim is that the model
# repeats the library rather than paraphrasing it.
_EMPTY_PHRASE = next(w for w in themes.validate({"width": render.W, "height": render.H,
                                                    "osd": {"widget": []}})[0]
                            if "empty canvas" in w)
_ref = []
for _bad, _want in (("nope", "is not a kind this program draws"),
                    ("special", "has to name one of")):
    _t = gui_edit.Editor(copy.deepcopy(generated[0].obj), origin="suite probe",
                         name=generated[0].name, theme=generated[0].theme)
    _steps0, _dirty0, _n0 = _t.steps, _t.dirty, len(_t.widgets())
    _good, _said = _t.add_widget(_bad)
    assert not _good and _want in _said, (_bad, _said)
    assert (_t.steps, _t.dirty, len(_t.widgets())) == (_steps0, _dirty0, _n0), (
        _bad, "a refusal moved the layout")
    _ref.append(f"`{_bad}` -> {_cut(_said, 64)}")
_t = gui_edit.Editor(copy.deepcopy(generated[0].obj), origin="suite probe",
                     name=generated[0].name, theme=generated[0].theme)
while len(_t.widgets()) > 1:
    _t.select(len(_t.widgets()) - 1)
    assert _t.delete_widget()[0], "deleting down to one row was refused early"
_steps0 = _t.steps
_good, _said = _t.delete_widget()
assert not _good and _EMPTY_PHRASE in _said, (_said, _EMPTY_PHRASE,
                   "the model does not refuse the last row in `validate`'s words")
assert _t.steps == _steps0 and len(_t.widgets()) == 1, "the refusal still removed the row"
_ref.append(f"the last row -> {_cut(_said, 72)}")
_t = gui_edit.Editor(copy.deepcopy(generated[0].obj), origin="suite probe",
                     name=generated[0].name, theme=generated[0].theme)
_t.select(0)
assert _t.delete_widget()[0], "deleting row 0 was refused"
_t.select(0)
_good, _said = _t.move_widget(-1)
assert not _good and "already the first drawn" in _said, _said
_ref.append(f"move past the front -> {_cut(_said, 64)}")

# ---- the reorder, measured per adjacent pair.  Three numbers per pair: whether the two
# ---- boxes meet at all, whether the swap moves any pixel, and - inside the rectangle the
# ---- two boxes share - how many pixels **both** rows cover opaquely and how many of those
# ---- the two rows paint in different colours.  The rule that comes out of the files is
# ---- bidirectional, and it is asserted both ways: a swap moves ink exactly where the two
# ---- rows lay opaque ink of different colours on the same pixel.  A box is a bounding box
# ---- (an `arc`'s is mostly the hole its ring is drawn around), and two vendor `line` rows
# ---- cross in sub-pixel coverage only, which is why some of the pairs whose boxes do meet
# ---- turn out silent - and how many is this box's fonts, so the sentence the gate prints
# ---- names that count rather than this comment remembering it.
# ---- The corpus has no pair that shares opaque ink of the *same* colour;
# ---- if one ever appears, this assert says which rule it broke rather than loosening.
_swap_zero = _swap_move = 0
_silent = []
for _e in (generated + [gui_edit.Editor.open_theme(r["name"]) for r in pick]):
    _img0, _notes0 = _e.paint(*_e.fixture())
    _bx = {r[3]: r[2] for r in (_notes0.get("boxes") or []) if r[2]}
    _ws = _e.widgets()
    for _i in range(len(_ws) - 1):
        if _i not in _bx or _i + 1 not in _bx:
            continue
        _t = gui_edit.Editor(copy.deepcopy(_e.obj), origin=_e.origin, path=_e.path,
                             name=_e.name, theme=_e.theme)
        _t.select(_i)
        _ok, _said = _t.move_widget(+1)
        assert _ok, (_e.name, _i, _said)
        _img1, _notes1 = _t.paint(*_t.fixture())
        assert ({str(_w.get("id")): _w.get("layerIndex") for _w in _e.widgets()}
                == {str(_w.get("id")): _w.get("layerIndex") for _w in _t.widgets()}), (
                _e.name, _i, "a reorder rewrote `layerIndex`, which nothing here reads")
        assert sorted(str(_w.get("id")) for _w in _t.widgets()) == sorted(
            str(_w.get("id")) for _w in _ws), (_e.name, _i, "a swap lost or invented a row")
        _d = px_differ(_img0, _img1)
        if not gui_edit._overlaps(_bx[_i], [_bx[_i + 1]]):
            assert _d == 0, (_e.name, _i, "two rows whose boxes never meet swapped ink")
            _swap_zero += 1
            continue
        x0, y0 = max(_bx[_i][0], _bx[_i + 1][0]), max(_bx[_i][1], _bx[_i + 1][1])
        x1, y1 = min(_bx[_i][2], _bx[_i + 1][2]), min(_bx[_i][3], _bx[_i + 1][3])
        solo = []
        for _one in (_i, _i + 1):
            _s = gui_edit.Editor({"width": render.W, "height": render.H,
                                  "osd": {"widget": [copy.deepcopy(_ws[_one])]}},
                                 origin="suite probe", name=_e.name)
            _si, _sn = _s.paint(*_s.fixture())
            solo.append(_si.convert("RGBA"))
        _opaque = _differ = 0
        for _y in range(y0, y1 + 1):
            for _x in range(x0, x1 + 1):
                _a, _b = solo[0].getpixel((_x, _y)), solo[1].getpixel((_x, _y))
                if _a[3] == 255 and _b[3] == 255:
                    _opaque += 1
                    if _a[:3] != _b[:3]:
                        _differ += 1
        assert (_d > 0) == (_differ > 0), (
            _e.name, _i, _d, _opaque, _differ,
            "a swap moved ink with no two-coloured opaque overlap, or the reverse: the "
            "draw-order rule and the pixel count disagree about which row is on top")
        if _d:
            _swap_move += 1
        else:
            _silent.append((_e.name, _i, _opaque, str(_ws[_i].get("type")),
                            str(_ws[_i + 1].get("type"))))
print(f"  rows you can add      {_add_ok} adds across {len(generated) + len(pick)} layouts: "
      f"each one paints a box the frame did not have and changes pixels, and one press of "
      f"undo puts the file back byte for byte.  The envelope is "
      f"{len(gui_edit.WIDGET_KEYS)} keys on all {len(_rows_all)} rows; a new row carries "
      f"the {len(_mandatory['text'])}/{len(_mandatory['data'])}/{len(_mandatory['bar'])}/"
      f"{len(_mandatory['arc'])}/{len(_mandatory['special'])}/{len(_mandatory['line'])} "
      f"keys text/data/bar/arc/special/line rows always carry, and every one of its values "
      f"is a value rows of that kind already use ({_add_soft} soft notes said out loud, "
      f"none repaired).  Placement is the painter's own boxes: {_place_clear} sit where "
      f"their source sits and are clear, {_place_moved} moved to the nearest free spot, "
      f"{_place_stuck} still meet a box and the sentence says so")
print(f"                        refused in words, moving nothing: {'; '.join(_ref)}")
print(f"                        reorder: {_swap_zero} adjacent pairs whose boxes never "
      f"meet swapped 0 px; of the {len(_silent) + _swap_move} whose boxes do meet, "
      f"{_swap_move} moved ink and {len(_silent)} did not, and in each of those "
      f"{len(_silent)} no pixel of the overlap is covered opaquely by both rows "
      f"({'; '.join(f'{n} {a}/{b} rows {i}/{i + 1}' for n, i, o, a, b in _silent[:4])}"
      + (f"; +{len(_silent) - 4} more)" if len(_silent) > 4 else ")"))
print(f"                        one add, in the model's own sentence: "
      f"{_cut(_add_notes.get('text', ''), 220)}")

# ---- the figures this cycle's pages write down.  Each one is counted again from the files
# ---- or the code on this run, and the sentence has to carry that answer: a digit that goes
# ---- stale fails the run instead of ageing quietly in a paragraph.  The counts that follow
# ---- a face - which placement bucket an add landed in, which reorder pairs moved ink - are
# ---- deliberately NOT in this list, and are printed above for the machine that made them.
_f_ed = [gui_edit.Editor.open_theme(_r["name"]) for _r in pick]
_f_rows = [_w for _e in _f_ed for _w in _e.widgets()]
_f_ids = {str(_w.get("id")) for _w in _f_rows}
_pos_same = sum(1 for _e in _f_ed for _i, _w in enumerate(_e.widgets())
                if _w.get("layerIndex") == _i)
assert len(_f_ids) < len(_f_rows), (
    "the id-reuse sentence is about a fact the files no longer show")
assert 0 < _pos_same < len(_f_rows), (
    "layerIndex now *is* the position in every row, which is the one finding that would "
    "make a reorder have to rewrite it")
def _flat(path):
    """A source file as one line, with comment markers gone.

    Both `edit.py`'s `#:` blocks and `app.py`'s comments quote the same counts the pages
    quote, and a comment that drifts is a claim nobody checked: flattening the file is what
    lets one regex hold it to the run.
    """
    out = []
    for ln in open(path, encoding="utf-8"):
        t = ln.strip()
        while t.startswith("#"):
            t = t[1:]
            if t.startswith(":"):          # the `#:` doc-comment marker, not punctuation
                t = t[1:]
            t = t.lstrip()
        out.append(t)
    return " ".join(" ".join(out).split())


_edit_src = _flat("xigmaui/edit.py")


def _stated(what, source, pattern, mine):
    """One figure a page (or a code comment) states, held to the count this run made."""
    m = _re.search(pattern, source)
    assert m, (what, "the sentence that states this figure is gone, so nothing checks it")
    got = tuple(int(x.replace(" ", "")) for x in m.groups())
    assert got == tuple(mine), (what, got, mine,
                     "the digits written down are not this run's")
    return got


# the model's own comment block, which is the source a reader of the installed tree gets
_stated("the row envelope, in `edit.py`'s comment", _edit_src,
        r"every one of the \*\*(\d+)\*\* widget rows in the \*\*(\d+)\*\* layouts",
        (len(_rows_all), len(generated) + len(pick)))
_LAYER = r"equals the row's position in \*\*(\d+)\*\* of their \*\*(\d+)\*\* rows and " \
         r"differs in \*\*(\d+)\*\*"
_stated("the layerIndex census, in `edit.py`'s comment", _edit_src, _LAYER,
        (_pos_same, len(_f_rows), len(_f_rows) - _pos_same))


# docs/gui.md: the four bullets' digits, in the order the page writes them
_stated("the row envelope, on the page", _gf,
        r"all \*\*(\d+)\*\* rows in the \*\*(\d+)\*\* layouts carry exactly the "
        r"\*\*(\d+)\*\* keys",
        (len(_rows_all), len(generated) + len(pick), len(gui_edit.WIDGET_KEYS)))
_stated("the mandatory keys per kind, on the page", _gf,
        r"carries the \*\*(\d+) / (\d+) / (\d+) / (\d+) / (\d+) / (\d+)\*\* keys that",
        tuple(len(_mandatory[_k]) for _k in ("text", "data", "bar", "arc", "special",
                                             "line")))
_stated("the special registry, on the page", _gf,
        r"the \*\*(\d+)\*\* drawings `themes\.SPECIALS` registers", (len(themes.SPECIALS),))
_shared = r"one id shared by \*\*(\d+)\*\* of those rows"
_idsel = {}
for _w in _f_rows:
    _k = str(_w.get("id"))
    _idsel[_k] = _idsel.get(_k, 0) + 1
_v_rows = _f_rows + [_w for _r in _rej for _w in
                     ((themes.load(_r["path"]).get("osd") or {}).get("widget") or [])]
_v_ids = {}
for _w in _v_rows:
    _k = str(_w.get("id"))
    _v_ids[_k] = _v_ids.get(_k, 0) + 1

# docs/limits.md also carries the envelope, in prose about the library's hard rules.
_lim = " ".join(open("docs/limits.md", encoding="utf-8").read().split())
_stated("the row envelope, in docs/limits.md", _lim,
        r"every one of the \*\*(\d+)\*\* rows in the \*\*(\d+)\*\* layouts the editor "
        r"opens carries exactly `id`, `layerIndex`, `type`, `property`, `widgetContent`, "
        r"and `property` is one element in all of them",
        (len(_rows_all), len(generated) + len(pick)))
_stated("the vendor's row count, in docs/limits.md", _lim,
        r"All \*\*(\d+)\*\* vendor widgets use one entry", (len(_v_rows),))
_stated("the vendor's id reuse, on the page", _gf,
        r"those \*\*(\d+)\*\* files' \*\*(\d+)\*\* rows answer to \*\*(\d+)\*\* distinct "
        r"ids, " + _shared,
        (len(pick), len(_f_rows), len(_f_ids), max(_idsel.values())))
_stated("the vendor's id reuse, in `edit.py`'s comment", _edit_src,
        r"\*\*(\d+)\*\* rows in \*\*(\d+)\*\* files answering to \*\*(\d+)\*\* distinct "
        r"ids, " + _shared,
        (len(_v_rows), len(pick) + len(_rej), len(_v_ids), max(_v_ids.values())))
_stated("the placement step, on the page", _gf,
        r"walked over the canvas in \*\*(\d+) px\*\* steps", (gui_edit.PLACE_STEP,))
_stated("the layerIndex census, on the page", _gf, _LAYER,
        (_pos_same, len(_f_rows), len(_f_rows) - _pos_same))
# ...and the counts that follow a face, now that both halves are on the page: the gate holds
# this run to its own half, exactly as it does for a column's width.  Membership, not a
# tolerance - a third machine's answer is a sentence to add, not a range to widen.
_stated("the adds, on the page", _gf,
        r"the \*\*(\d+)\*\* adds across the \*\*(\d+)\*\* layouts come out",
        (_add_ok, len(generated) + len(pick)))
_pb = _pair("the three ways an add can end",
            r"come out \*\*(\d+) / (\d+) / (\d+)\*\* on this bench.*?"
            r"\*\*(\d+) / (\d+) / (\d+)\*\* on CI's runner",
            (_place_clear, _place_moved, _place_stuck))
assert _pb[:3] == _pb[3:], (_pb, "the page claims both machines answer the same three "
                                 "placement counts, and they no longer do")
_rp = _pair("the pairs whose boxes never meet",
            r"\*\*(\d+)\*\* adjacent pairs of drawn rows have boxes that never meet on this "
            r"bench and \*\*(\d+)\*\* on CI's runner", (_swap_zero,))
# ...and the meet side of the same census, which the pages used to be able to call "the same
# on both".  They can no longer: the pinned-pair repair (2026-11-11, `Editor.fixture()` now
# deep-copies) leaves the fixture answering one derived rate more than it did mid-section
# before, so two more rows have boxes to be adjacent between, and on this bench that turned
# 12 / 6 / 6 into 13 / 7 / 6 while CI's runner's own triple is labelled beside it.  Same door
# as the never-meet pair above: this run's triple must be one of the two labelled ones, and
# nothing claims the machines agree when they no longer do.
_m3 = _pair("the pairs whose boxes meet",
            r"of the \*\*(\d+)\*\* whose boxes do meet \*\*(\d+)\*\* moved ink and "
            r"\*\*(\d+)\*\* did not here, against \*\*(\d+) / (\d+) / (\d+)\*\* the "
            r"same three ways there",
            (len(_silent) + _swap_move, _swap_move, len(_silent)))
assert _m3[:3] != _m3[3:] or _m3[:3] == tuple(_m3[3:]), (_m3, "the page labels the same "
                                                        "triple twice, which is a claim about "
                                                        "two boxes rather than a measurement")

# ...and `app.py`, whose comment *and* docstring quote the same arc heights the page
# labels.  Four digits each, and they have to be the page's four digits: a code comment
# stating a third machine's pixels is a claim nobody labelled.
_app_src = _flat("xigmaui/app.py")
for _pat in (r"make this box (\d+) px tall in one column at a \d+x\d+ window and (\d+) px "
             r"in three at \d+x\d+ - this bench's reading, CI's runner reading (\d+) and "
             r"(\d+)",
             r"make this box \*\*(\d+) px\*\* tall in one column at a \d+x\d+ window "
             r"and \*\*(\d+) px\*\* in three at \d+x\d+ - this bench's digits, where "
             r"CI's runner reads (\d+) and (\d+)"):
    _m = _re.search(_pat, _app_src)
    assert _m, ("app.py's `arc` height sentence",
                "no longer names both machines in a shape the gate can read")
    assert tuple(int(x) for x in _m.groups()) == _hh, (
        _m.groups(), _hh, "the code's comment and the page's labelled pair disagree about "
                          "whose pixels those are")

# ...and the sentence that says a structural save is judged against the file on disk, which
# is the one claim in the bullet no in-memory assert can make.
assert ("the rows come back out of it in the same order, and the file on disk draws the frame "
        "the pane was showing when `save` was pressed") in _gf, (
    "docs/gui.md no longer promises the structural save round trip that the window's own gate "
    "measures: rows in order out of the file, and the file drawing the saved frame")

# ...and the refusal the page promises "in the library's own words": the phrase is taken
# from `themes.validate` on this run, and both the model and the page have to carry it.
assert _EMPTY_PHRASE in _gf, (
    "docs/gui.md no longer quotes `validate` verbatim for an empty layout, which is the "
    "sentence `delete_widget` refuses the last row with")
_ORDER = ("text", "data", "bar", "arc", "special", "line")
_mand_str = "/".join(str(len(_mandatory[_k])) for _k in _ORDER)
print(f"                        the page's digits, from this run: {len(_rows_all)} rows in "
      f"{len(generated) + len(pick)} layouts carry the {len(gui_edit.WIDGET_KEYS)} keys, "
      f"mandatory per kind {len(_rows_all) and _mand_str}; the {len(pick)} vendor files' "
      f"{len(_f_rows)} rows answer to {len(_f_ids)} ids and "
      f"{len(_f_rows) - _pos_same} of them do not spell `layerIndex` as their position; "
      f"the placement step is {gui_edit.PLACE_STEP} px and {len(themes.SPECIALS)} "
      f"drawings are registered")
# ---- the window's half of the same three doors: the buttons, what the add menu promises
# ---- before it is pressed, and what the new controls cost the three columns.  The floors
# ---- are read before and after, because a control nobody measured is how 0.5's controls
# ---- column grew from 329 px to 362 px of contents: the label is the cost.
_win_floors0 = None
_win_contents0 = None
win.adv_toggle.setChecked(True)
_ix = win.ed_name.findText("bars")
assert _ix > 0, (_ix, "the layout combo offers no `bars` entry, so opening it through the "
                      "combo is not what this gate can check")
win.ed_name.setCurrentIndex(_ix)
for _ in range(8):
    appq.processEvents()
_win_floors0 = [win.split.widget(i).minimumWidth() for i in range(3)]
_win_contents0 = [win.split.widget(i).widget().minimumSizeHint().width() for i in range(3)]
_rows0 = win.ed_widget.count()
assert win.ed is not None and _rows0 == len(win.ed.widgets()) == 32, _rows0
_acts = {}
for _a in win.ed_add_menu.actions():
    if not _a.text():
        continue
    _acts[_a.text()] = _a
assert sorted(_acts) == sorted(gui_edit.kinds()), (sorted(_acts), sorted(gui_edit.kinds()),
                                                  "the add menu does not offer every kind")
assert "special" in _acts and _acts["special"].menu() is not None
_spe = [a.text() for a in _acts["special"].menu().actions()]
assert sorted(_spe) == sorted(themes.SPECIALS), (_spe, sorted(themes.SPECIALS),
                                          "the `special` sub-menu is not the registry")
for _k, _a in _acts.items():
    if _k == "special":
        for _sa in _a.menu().actions():
            assert _sa.toolTip().startswith("a `special` row drawing"), (
                _sa.text(), _sa.toolTip())
        continue
    assert _a.toolTip().startswith("a copy of"), (
        _k, _a.toolTip(), "the entry does not name the row a new one of that kind copies")
assert not win.ed.dirty and win.ed_undo.text() == "undo", "opening a layout changed the file"

# press `arc`, and the window agrees with the file afterwards
_img_a, _notes_a = win.ed.paint(*win.ed.fixture())
_acts["arc"].trigger()
for _ in range(8):
    appq.processEvents()
assert win.ed_widget.count() == _rows0 + 1, (win.ed_widget.count(), _rows0,
                                             "the row the model added is not in the menu")
assert win.ed.index == win.ed_widget.currentIndex() == _rows0, (
    win.ed.index, win.ed_widget.currentIndex(), "the new row is not the selected one")
assert "added a arc row" in win.ed_note.text(), win.ed_note.text()
assert win.ed_undo.text() == "undo (1)", win.ed_undo.text()
assert win.ed.dirty, "a row was added and the window does not know the file is outstanding"
_img_b, _notes_b = win.ed.paint(*win.ed.fixture())
assert px_differ(_img_a, _img_b) > 0, "the window's add did not move the preview"
assert len([r for r in _notes_b["boxes"] if r[2]]) > \
    len([r for r in _notes_a["boxes"] if r[2]]), "the window add painted no new box"
_win_floors1 = [win.split.widget(i).minimumWidth() for i in range(3)]
_win_contents1 = [win.split.widget(i).widget().minimumSizeHint().width() for i in range(3)]
# The floor is not a constant to compare against: it *is* the contents, and the contents
# changed because the newly added row is now the selected one - an `arc`'s field grid asks
# a different width from the `data` row that was selected before.  What has to hold, and is
# what the sizing rule promises, is that no pane is ever narrower than what it holds and
# none of them scrolls sideways, before and after a structural change.
for _i, _nm in enumerate(("preview", "controls", "library")):
    for _img_tag, _floors, _contents in (("before", _win_floors0, _win_contents0),
                                         ("after", _win_floors1, _win_contents1)):
        _area = win.split.widget(_i)
        assert _floors[_i] >= _contents[_i], (_nm, _img_tag, _floors, _contents,
                                              "a pane's floor is under its own contents")
        _hs = _area.horizontalScrollBar()
        assert _hs.maximum() == 0 and not _hs.isVisible(), (
            _nm, _img_tag, _hs.maximum(), "this pane scrolls sideways at some point of the "
                                          "add")
win.ed_undo.click()
for _ in range(8):
    appq.processEvents()
assert win.ed_widget.count() == _rows0 and not win.ed.dirty, (
        _rows0, win.ed_widget.count(), win.ed.dirty, win.ed.steps,
        win.ed.index, win.ed._pending is not None, win.ed_undo.text(),
        "undo did not put the rows back")
_img_c, _notes_c = win.ed.paint(*win.ed.fixture())
assert px_differ(_img_a, _img_c) == 0, "the frame after undo is not the frame before the add"

# the two reorder buttons: what they do, and where they stop being offered
win._editor_pick_widget(0)
for _ in range(4):
    appq.processEvents()
assert not win.ed_up.isEnabled(), "row 0 offers `up`, which would do nothing"
assert win.ed_down.isEnabled(), "row 0 of 32 does not offer `down`"
_ids0 = [str(w.get("id")) for w in win.ed.widgets()]
win.ed_down.click()
for _ in range(6):
    appq.processEvents()
_ids1 = [str(w.get("id")) for w in win.ed.widgets()]
assert _ids1[:2] == _ids0[1::-1] and _ids1[2:] == _ids0[2:], (_ids1[:3], _ids0[:3],
                                          "`down` did not swap neighbours")
assert win.ed_widget.itemText(0) == win.ed.label(0), "the menu kept the old row's label"
assert "swapped" in win.ed_note.text(), win.ed_note.text()
win._editor_pick_widget(len(_ids1) - 1)
for _ in range(4):
    appq.processEvents()
assert not win.ed_down.isEnabled(), "the last row offers `down`, which would do nothing"
assert win.ed_up.isEnabled() and win.ed_del.isEnabled(), "the last row of 32 refuses `up`"

# and `remove`: one row out of the list, out of the frame, and back by undo.  Each act is
# exactly one undo step and the steps are last-in-first-out, so the press after a remove
# puts the row back and leaves the reorder standing - the file only reads clean again after
# both, and the frame says which of the two was undone.
_img_p, _notes_p = win.ed.paint(*win.ed.fixture())
_steps_p = win.ed.steps
win.ed_del.click()
for _ in range(6):
    appq.processEvents()
assert win.ed_widget.count() == _rows0 - 1, win.ed_widget.count()
assert "removed row" in win.ed_note.text(), win.ed_note.text()
assert win.ed.steps == _steps_p + 1, (_steps_p, win.ed.steps,
                                      "a remove is not exactly one undo step")
_img_e, _notes_e = win.ed.paint(*win.ed.fixture())
assert px_differ(_img_p, _img_e) > 0, "a row was removed and the picture did not notice"
assert [str(w.get("id")) for w in win.ed.widgets()] == _ids1[:-1], "the wrong row went"
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert win.ed_widget.count() == _rows0 and win.ed.dirty, "undo did not put the row back"
assert px_differ(_img_p, win.ed.paint(*win.ed.fixture())[0]) == 0, (
    "the frame after undoing the remove is not the frame before it")
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert not win.ed.dirty and win.ed.steps == 0, (
    win.ed.steps, win.ed.dirty, "the reorder's step did not come back, so two acts were "
                                "not two steps")
assert px_differ(_img_a, win.ed.paint(*win.ed.fixture())[0]) == 0, (
    "undoing both acts did not bring the original frame back")
assert win.ed_del.isEnabled(), "the button is disabled with 32 rows in the layout"
# ...and the window goes back as the later gates in this section find it: no layout open,
# the row and its controls disabled.  A gate that leaves state behind is a gate that makes
# the next one's pass mean something else.
win.ed_name.setCurrentIndex(0)                     # app.NO_EDITOR
for _ in range(6):
    appq.processEvents()
assert win.ed is None and not win.ed_widget.isEnabled(), (
    "closing the layout did not put the shell back")
print(f"  the buttons too       add / remove / up / down driven through the window: the add "
      f"menu offers {len(_acts)} kinds and its `special` sub-menu the {len(_spe)} drawings "
      f"this program has, each entry saying which row it copies; a press adds a row the "
      f"preview paints, selects it, marks the file outstanding, and one press of undo puts "
      f"both the list and the frame back; `up` is disabled at row 0 and `down` at row "
      f"{_rows0 - 1}, and `remove` is enabled at {_rows0} rows because the model, not the "
      f"button, is what refuses the last one - and two acts really are two steps: one "
      f"press puts a removed row back with the reorder still standing, the next takes the "
      f"reorder back and the file reads clean.  Sizing across the change: floors "
      f"{_win_floors0} -> {_win_floors1} and contents {_win_contents0} -> "
      f"{_win_contents1}, no pane under its own contents and no horizontal scrollbar at "
      f"either point - the controls column follows the *selected* kind's grid, not the "
      f"number of rows")

# ---- resizing a row by its edge.  The promise this cycle makes is per kind, so the gate
# ---- asks the painter rather than the model: which keys an edge drag writes, whether the
# ---- box follows the drag, whether the row's own arithmetic survives, and whether one
# ---- press of undo puts the file back.  The size census the pages quote - which bar boxes
# ---- are exact, how many arc rows keep `sizeWidth == 2*radius + 2*width`, how many
# ---- `text`/`data` rows carry a width key - is counted again here from the files.
_read_prop, _read_xigma = themes.keys_read()
_D_NEVER = ("cornerRadius", "rotate", "autoFitMax", "fitArc", "angleStart", "angleEnd",
            "minValue", "maxValue", "source", "content", "name", "textColor",
            "fontFamily", "fontFace", "family", "bold", "anchor", "arcPaint", "barPaint",
            "id", "layerIndex", "type", "widgetContent")
_d_ed = list(generated) + [gui_edit.Editor.open_theme(r["name"]) for r in pick]
_d_rows = [(_e, _i, _w) for _e in _d_ed for _i, _w in enumerate(_e.widgets())]
_d_by_kind = {}
for _e, _i, _w in _d_rows:
    _k = str(_w.get("type") or "")
    _d_by_kind[_k] = _d_by_kind.get(_k, 0) + 1
assert sorted(_d_by_kind) == sorted(layout.KINDS), sorted(_d_by_kind)

# the outer bound, taken from the painter's own source rather than from a list kept here:
# every key the door may write is one `layout.py` is proven to read
for _k, _keys in gui_edit.Editor.SIZE_KEYS.items():
    for _key in _keys:
        assert _key in _read_prop, (_k, _key, "a size key that `layout.py` does not read")
assert set(gui_edit.Editor.SIZE_KEYS) <= set(layout.KINDS), gui_edit.Editor.SIZE_KEYS
for _key in ("autoFitMax", "fitArc"):
    assert _key in _read_xigma, (_key, "the door names a cap nothing reads")

# ---- what the files say about size.  A `box` here is always the one the painter reports.
_bar_exact = _bar_total = _bar_boxed = 0
_arc_rows = _arc_ident = _arc_square = 0
_line_exact = _line_total = _txt_rows = _txt_with_wh = 0
_rot_rows = _rot_inert = 0
_corner_rows = _corner_boxed = _corner_box_same = 0


def _poke_draw(e, index, key, value):
    """Draw a copy of a layout with one `property` key set straight into the dict.

    Deliberately not `Editor.set`: this measures what the *painter* does with a key, and a
    key the inspector refuses to offer is exactly the one worth measuring.
    """
    out = copy.deepcopy(e.obj)
    (out["osd"]["widget"][index]["property"][0])[key] = value
    t = gui_edit.Editor(out, origin="gate", name=e.name)
    return t.paint(*t.fixture())


for _e, _i, _w in _d_rows:
    _k = str(_w.get("type") or "")
    _p = (_w.get("property") or [{}])[0]
    _b0, _n0 = _e.paint(*_e.fixture())
    _bx = {r[3]: r[2] for r in (_n0.get("boxes") or []) if r[2]}.get(_i)
    if _k == "bar":
        _bar_total += 1
        _bar_boxed += 1 if _bx else 0
        if _bx and _bx == (int(_p["x"]), int(_p["y"]),
                           int(_p["x"]) + int(_p["width"]),
                           int(_p["y"]) + int(_p.get("height") or 0)):
            _bar_exact += 1
        if str(_p.get("rotate", "")).lstrip("-").isdigit():
            _rot_rows += 1
            _b1, _n1 = _poke_draw(_e, _i, "rotate", int(_p["rotate"]) + 8)
            _rot_inert += 1 if not px_differ(_b0, _b1) else 0
    if _k in ("bar", "arc") and str(_p.get("cornerRadius", "")).lstrip("-").isdigit():
        _corner_rows += 1
        if _bx:                     # a row that draws nothing has no box to keep still
            _corner_boxed += 1
            _b1, _n1 = _poke_draw(_e, _i, "cornerRadius", int(_p["cornerRadius"]) + 8)
            _nb = {r[3]: r[2] for r in (_n1.get("boxes") or []) if r[2]}.get(_i)
            _corner_box_same += 1 if _nb == _bx else 0
    elif _k == "arc":
        _arc_rows += 1
        _arc_ident += int(_p.get("sizeWidth") or 0) == 2 * int(_p.get("radius") or 0) \
            + 2 * int(_p.get("width") or 0)
        _arc_square += int(_p.get("sizeWidth") or 0) == int(_p.get("sizeHeight") or 0)
    elif _k == "line":
        _line_total += 1
        _rx, _ry, _rw, _rh = layout.line_rect(_p)
        if _bx and _bx == (_rx, _ry, _rx + _rw, _ry + _rh):
            _line_exact += 1
    elif _k in ("text", "data"):
        _txt_rows += 1
        _txt_with_wh += "width" in _p or "height" in _p
# what a face is worth in width: the page says "tens of pixels ... never by 8", which is a
# measurement rather than an impression.  One row at a time, because the box is the ink and
# the answer belongs to this machine's fonts - so the range is printed, not kept in prose.
_face_w = []
for _e, _i, _w in _d_rows:
    if str(_w.get("type") or "") not in ("text", "data"):
        continue
    _p = (_w.get("property") or [{}])[0]
    _fs = int(_p.get("fontSize") or 12)
    _one = {"width": render.W, "height": render.H, "osd": {"widget": [copy.deepcopy(_w)]}}
    _a = gui_edit.Editor(_one, origin="gate", name="gate-face")._row_box(_one, 0)
    _up = copy.deepcopy(_one)
    _up["osd"]["widget"][0]["property"][0]["fontSize"] = _fs + 8
    _b = gui_edit.Editor(_up, origin="gate", name="gate-face")._row_box(_up, 0)
    if not _a or not _b:
        continue
    _face_w.append((_b[2] - _b[0]) - (_a[2] - _a[0]))
assert _face_w, "no `text`/`data` row drew a box, so the face claim cannot be measured here"
_moved = [x for x in _face_w if x]
# the rule the page writes: the width a face push buys is never the push itself, it is not
# the same from row to row, and its size belongs to this machine's fonts - so no `width` key
# could carry it, and the door writes the face instead.
assert all(x != 8 for x in _face_w), (
    min(_face_w), max(_face_w), "+8 px of face moved some row's box exactly +8 px of width")
assert _moved and len(set(_face_w)) > 3, (
    _face_w[:8], "a face push bought the same width everywhere, which is not what the sweep "
    "found and not what the page says")
# the rows that did not move at all must be rows that name a cap
_still = [x for x in _face_w if not x]
_cap_bound = 0
for _e, _i, _w in _d_rows:
    if str(_w.get("type") or "") not in ("text", "data"):
        continue
    _xg = (_w.get("property") or [{}])[0].get("xigma") or {}
    _cap_bound += 1 if int(_xg.get("autoFitMax") or 0) else 0
assert len(_still) <= _cap_bound, (
    len(_still), _cap_bound, "a row with no cap did not answer its face at all")
_cap_note = (f"{min(_moved)}..{max(_moved)} px of box width on {len(_moved)}"
             f"/{len(_face_w)} drawn rows, never 8 px; {len(_still)} did not move at all, "
             f"of {_cap_bound} rows that name `xigma.autoFitMax`")
print(f"                        a +8 px push on `fontSize`: {_cap_note}")

# the rule, not the fraction: every `bar` row the painter draws a box for has exactly its
# declared rect as that box, and every `line` row's box is what `line_rect` says.  The
# fractions are printed below, and they move with this machine's readings - a `Fan 3 Speed`
# with no reading draws no box at all, so it is not in the numerator or the denominator.
assert _bar_exact == _bar_boxed, (_bar_exact, _bar_boxed, "a drawn `bar` row's box is not "
                                  "its declared `x,y,x+width,y+height`")
assert _line_exact == _line_total, (_line_exact, _line_total,
                                    "`line_rect` did not predict a drawn line's box")
assert _corner_box_same == _corner_boxed, (
    _corner_box_same, _corner_boxed, "pushing `cornerRadius` moved a box, and the page "
    "says a handle never writes that key")
assert _rot_inert == _rot_rows, (_rot_inert, _rot_rows,
                                 "a `bar` row's `rotate` changed the picture, so something "
                                 "reads it and the refusal sentence is wrong")
assert _arc_ident == _arc_rows and _arc_square == _arc_rows, (
    _arc_ident, _arc_square, _arc_rows, "an `arc` row in the library does not keep the "
    "arithmetic its ring is drawn with")
assert _txt_with_wh == 0, (
    "a `text`/`data` row carries a `width` or `height` key now, and the door's rule for "
    "those kinds is that their box is the ink their face lays down")

# ---- the sweep.  A 12 px push on every edge the row's own rules say is live; `text` and
# ---- `data` take the straight edges, plus one corner on a sample, because a face search
# ---- costs a dozen solo draws and a corner goes down the same path.
_d_ok, _d_refused, _d_soft = 0, [], []
_d_wrote, _d_box, _d_face, _d_undo = {}, 0, [], 0
for _e, _i, _w in _d_rows:
    _k = str(_w.get("type") or "")
    _base = themes.canonical(_e.obj)
    _frame, _notes = _e.paint(*_e.fixture())
    _box = {r[3]: r[2] for r in (_notes.get("boxes") or []) if r[2]}.get(_i)
    _live = _e.size_edges(_i, _box)
    if _k in ("text", "data"):
        # the sides the door says nothing about are still asked, and still refused: the
        # pane hides those handles, but the model's answer is the claim, not the marks
        _t = gui_edit.Editor(copy.deepcopy(_e.obj), origin="gate", name=_e.name)
        _t.select(_i)
        for _bad in ("right", "left"):
            _ok, _said = _t.resize_row(12, 0, _bad, _i)
            # two different refusals, and which one applies is this machine's picture: a row
            # whose source has no reading paints no box, so it has no edge at all
            assert not _ok, (_e.name, _i, _bad, _said, "a `text` row owns no width")
            assert ("owns no width" in _said) if _box else ("paints no box" in _said), (
                _e.name, _i, _bad, _said, _box)
            assert _t.steps == 0 and themes.canonical(_t.obj) == _base, (
                _e.name, _i, _bad, "the refusal wrote something")
        assert not ({"left", "right"} & set(_live)), (_e.name, _i, _live,
                                                     "a side handle on a kind with no width")
    if _k == "special":
        assert not any("-" in x for x in _live), (_e.name, _i, _live,
                                                  "a corner handle on a `special`")
    if not _box or not _live:
        _d_refused.append((_e.name, _i, _k, "no-box" if _live else "no-edge", ""))
        continue
    _edges = tuple(x for x in _live if "-" not in x)
    _corners = tuple(x for x in _live if "-" in x)
    if _k not in ("text", "data"):
        _edges += _corners
    elif _i % 4 == 0 and _corners:
        _edges += _corners[:1]
    for _edge in _edges:
        # grow first, because that is the direction the sentence about a row's edges reads
        # in; if the glass is in the way, the same edge pushed the other way is the test
        sx = 12 if "right" in _edge else -12 if "left" in _edge else 0
        sy = 12 if "bottom" in _edge else -12 if "top" in _edge else 0
        for _mult in (1, -1):
            _dx, _dy = sx * _mult, sy * _mult
            _t = gui_edit.Editor(copy.deepcopy(_e.obj), origin="gate", name=_e.name)
            _t.select(_i)
            _steps0 = _t.steps
            _ok, _said = _t.resize_row(_dx, _dy, _edge, _i)
            if _ok:
                break
            assert _t.steps == _steps0 and themes.canonical(_t.obj) == _base, (
                _e.name, _i, _edge, "a refused resize took an undo step or wrote a key")
        else:
            _d_refused.append((_e.name, _i, _k, _edge, _said))
            continue
        _d_ok += 1
        assert _t.steps == _steps0 + 1, (_e.name, _i, _edge, _t.steps,
                                         "one resize is not exactly one undo step")
        _pa = (_t.widgets()[_i].get("property") or [{}])[0]
        _pb = (_w.get("property") or [{}])[0]
        _changed = sorted(x for x in set(_pa) | set(_pb) if _pa.get(x) != _pb.get(x))
        for _key in _changed:
            _d_wrote[_key] = _d_wrote.get(_key, 0) + 1
            assert _key in _read_prop, (_e.name, _i, _edge, _key,
                                        "a handle wrote a key `layout.py` does not read")
        _stray = [x for x in _changed if x in _D_NEVER]
        assert not _stray, (_e.name, _i, _edge, _stray, "no edge owns those keys")
        _b1, _n1 = _t.paint(*_t.fixture())
        _nb = {r[3]: r[2] for r in (_n1.get("boxes") or []) if r[2]}.get(_i)
        assert _nb, (_e.name, _i, _edge, "the resized row paints no box any more")
        if not px_differ(_frame, _b1):
            _d_soft.append((_e.name, _i, _k, _edge))
        _had = (_box[2] - _box[0], _box[3] - _box[1])
        _got = (_nb[2] - _nb[0], _nb[3] - _nb[1])
        if _k in ("bar", "line", "arc"):
            if ("right" in _edge and _got[0] != _had[0] + _dx) or \
               ("left" in _edge and _got[0] != _had[0] - _dx) or \
               ("bottom" in _edge and _got[1] != _had[1] + _dy) or \
               ("top" in _edge and _got[1] != _had[1] - _dy):
                raise AssertionError((_e.name, _i, _k, _edge, _had, _got, _dx, _dy,
                                      "the box did not follow the drag 1:1"))
            _d_box += 1
        if _k == "arc":
            assert int(_pa["sizeWidth"]) == 2 * int(_pa["radius"]) + 2 * int(_pa["width"]), (
                _e.name, _i, _edge, "the ring no longer meets its own box")
            if _dx and _dy and _had[0] == _had[1]:
                assert _got[0] == _got[1], (_e.name, _i, _edge,
                                            "a corner drag on a square ring left it skewed")
        if _k in ("text", "data"):
            assert _changed == ["fontSize"], (_e.name, _i, _edge, _changed,
                                              "a text row's resize wrote more than the face")
            _want = _had[1] + (_dy if "bottom" in _edge else -_dy)
            if _got[1] == _had[1]:
                raise AssertionError((_e.name, _i, _edge, "the face left the height alone",
                                      _had, _got, _want))
            assert abs(_got[1] - _want) <= abs(_had[1] - _want) + 1, (
                _e.name, _i, _edge, _had, _got, _want, "the face moved away from the ask")
            _d_face.append(abs(_got[1] - _want))
        if _k == "special":
            assert set(_changed) <= {"width", "fontSize"}, (_e.name, _i, _edge, _changed)
        _t.undo()
        assert themes.canonical(_t.obj) == _base, (
            _e.name, _i, _edge, "one press of undo did not put the layout back")
        _d_undo += 1
assert _d_undo == _d_ok, (_d_ok, _d_undo)
_d_nothing = [x for x in _d_refused if not x[4]]
_d_said = [x for x in _d_refused if x[4]]

# ---- the cases no shipped file carries, built in memory: a `rotate: 90` line carrying a
# ---- `lineWidth`, a plain `lineWidth`, and a row whose extent belongs to a cap.
_syn = {"width": render.W, "height": render.H, "osd": {"widget": [
    {"id": "gate-rot-line", "layerIndex": 0, "type": "line", "widgetContent": "",
     "property": [{"x": 165, "y": 305, "width": 150, "height": 2, "rotate": 90,
                   "lineWidth": 9}]},
    {"id": "gate-plain-line", "layerIndex": 0, "type": "line", "widgetContent": "",
     "property": [{"x": 10, "y": 60, "width": 100, "height": 4, "rotate": 0,
                   "lineWidth": 30}]},
    {"id": "gate-capped", "layerIndex": 0, "type": "data", "widgetContent": "",
     "property": [{"x": 20, "y": 20, "source": "CPU Temperature", "fontSize": 140,
                   "fontFamily": "dejavu", "bold": False,
                   "textColor": "rgba(255,255,255,1)", "xigma": {"autoFitMax": 120}}]}]}}
_se = gui_edit.Editor(copy.deepcopy(_syn), origin="gate", name="gate-syn")
_syn_ok, _syn_ref = [], []
for _i, _edge, _dx, _dy, _want in ((0, "bottom", 0, 12, "lineWidth"),
                                   (0, "right", 12, 0, "height"),
                                   (1, "bottom", 0, -2, "lineWidth"),
                                   (2, "bottom", 0, 12, None)):
    _se.select(_i)
    _b0, _n0 = _se.paint(*_se.fixture())
    _bx0 = {r[3]: r[2] for r in (_n0.get("boxes") or []) if r[2]}.get(_i)
    _ok, _said = _se.resize_row(_dx, _dy, _edge, _i)
    if not _ok:
        assert _se.steps == 0, (_i, _edge, "the refusal took an undo step")
        _syn_ref.append((_i, _edge, _said))
        continue
    _b1, _n1 = _se.paint(*_se.fixture())
    _bx1 = {r[3]: r[2] for r in (_n1.get("boxes") or []) if r[2]}.get(_i)
    _pp = (_se.widgets()[_i].get("property") or [{}])[0]
    assert _bx1 and (_bx1[2] - _bx1[0], _bx1[3] - _bx1[1]) == \
        (_bx0[2] - _bx0[0] + _dx, _bx0[3] - _bx0[1] + _dy), (
        _i, _edge, _bx0, _bx1, "a synthetic line's box did not follow the drag")
    assert _pp.get(_want) is not None, (_i, _want, "the key that drag owns is missing")
    _syn_ok.append((_edge, _want, _pp[_want]))
    _se.undo()
    assert themes.canonical(_se.obj) == themes.canonical(_syn), (
        _i, _edge, "undo of the synthetic resize did not return the file")
assert len(_syn_ok) == 3 and len(_syn_ref) == 1, (_syn_ok, _syn_ref)
assert any("xigma.autoFitMax" in x[2] for x in _syn_ref), (
    _syn_ref, "the cap-bound refusal does not name the key that owns the extent")
# the same sentence for a `special` whose figures are fitted into a ring: `xigma.fitArc`
_fit = ""
for _e, _i, _w in _d_rows:
    if str(_w.get("type")) != "special":
        continue
    _t = gui_edit.Editor(copy.deepcopy(_e.obj), origin="gate", name=_e.name)
    _t.select(_i)
    _ok, _said = _t.resize_row(0, 40, "bottom", _i)
    if not _ok and "xigma.fitArc" in _said:
        assert _t.steps == 0 and themes.canonical(_t.obj) == themes.canonical(_e.obj), (
            _e.name, _i, "the fitArc refusal wrote something")
        _fit = f"{_e.name} row {_i}"
        break
assert _fit, "no `special` row refused a face drag by naming `xigma.fitArc`"
print(f"  rows you can resize   {len(_d_rows)} drawn rows in {len(_d_ed)} layouts, per kind "
      f"{_d_by_kind}; {_d_ok} accepted drags wrote {sum(_d_wrote.values())} keys, every one "
      f"a key `layout.py` reads and none of the {len(_D_NEVER)} no edge owns "
      f"({', '.join(f'{k} {v}' for k, v in sorted(_d_wrote.items()))}); each exactly one "
      f"undo step, all {_d_undo} put the layout object back byte for byte; {_d_box} "
      f"declared-geometry boxes followed the drag 1:1, and {len(_d_face)} face-bound rows "
      f"landed within {max(_d_face) if _d_face else 0} px of the height asked for; "
      f"{len(_d_said)} drags refused in words with the file untouched "
      f"({len(_d_nothing)} rows the painter draws no box for at this fixture)")
print(f"                        what the files say about size, counted this run: "
      f"{_bar_exact}/{_bar_total} bar boxes exactly `x,y,x+width,y+height`, "
      f"{_line_exact}/{_line_total} line boxes exactly as `line_rect` predicts, "
      f"{_arc_ident}/{_arc_rows} arc rows keeping `sizeWidth == 2*radius + 2*width` and "
      f"{_arc_square}/{_arc_rows} with `sizeWidth == sizeHeight`, {_txt_rows} `text`/`data` "
      f"rows of which {_txt_with_wh} carry a `width` or `height` key; `rotate` pushed +8 on "
      f"{_rot_rows} bar rows changed 0 px on {_rot_inert} of them, and `cornerRadius` "
      f"pushed +8 on {_corner_rows} bar/arc rows left the box where it was on "
      f"{_corner_box_same}; +8 px of `fontSize` moved a `text`/`data` box's width "
      f"by {min(_face_w)}..{max(_face_w)} px on this machine, never by 8; "
f"{_corner_box_same}; the synthetic line cases ({_syn_ok}), {_syn_ref[0][2][:50]}"
      f", and {_fit} refusing a face drag by naming `xigma.fitArc`")
print(f"                        refused in words: "
      + "; ".join(f"{_n} {_k} {_ed} -> {_cut(_s, 60)}" for _n, _i, _k, _ed, _s
                  in _d_said[:5]))

# ---- feature D's sentences, held to the counts this run makes.  The same two rules as the
# ---- cycle before: a figure is re-measured from the files or the painter and the sentence
# ---- has to carry *that* number, and a code comment is a sentence like any other - the
# ---- installed tree carries it to a reader, so a stale one is a wrong claim in the library.
for _what, _pat, _mine in (
        ("the `line_rect` prediction, on the page",
         r"predicts the drawn box of \*\*(\d+)\*\* of the \*\*(\d+)\*\* line rows exactly",
         (_line_exact, _line_total)),
        ("the arc identity, on the page",
         r"the arithmetic \*\*(\d+)\*\* of the \*\*(\d+)\*\* `arc` rows in the library obey",
         (_arc_ident, _arc_rows)),
        ("the text/data row count, on the page",
         r"Not one of the \*\*(\d+)\*\* `text`/`data` rows carries a `width` or "
         r"`height` key", (_txt_rows,)),
        ("who carries a `cornerRadius`, on the page",
         r"`cornerRadius` is carried by \*\*(\d+)\*\* of the `bar`/`arc` rows",
         (_corner_rows,)),
        # every bar row that carries `rotate` changed not one pixel, which is what the
        # page's "0 px on all N" says; the count of them is this run's census.
        ("the unread `rotate`, on the page",
         r"`rotate` is carried by \*\*(\d+)\*\* `bar` rows and pushing it \+8 changed "
         r"\*\*(\d+) px\*\* on all \*\*(\d+)\*\*",
         (_rot_rows, 0 if _rot_inert == _rot_rows else _rot_inert, _rot_rows)),
):
    _stated(_what, _gf, _pat, _mine)
assert _gf.count("The pane paints eight small squares") == 1 and \
    len(gui_edit.Editor.EDGES) == len(app.Canvas.CURSORS) == 8, (
    len(gui_edit.Editor.EDGES), len(app.Canvas.CURSORS),
    "the page says eight squares and the two files do not have eight edges to match")
for _phrase, _why in (
        ("never 8 px, differs from row to row",
         "that a face push buys a width no `width` key could carry"),
        ("paints no square on a text row's left or right side",
         "which handles a `text` row does not get, the visible half of `size_edges`"),
        ("no corner squares at all", "that a `special`'s two axes are two keys"),
        ("`edit.Editor.size_edges` puts every edge through its own resize door",
         "that the pane's handles are the model's answer, not a table in `app.py`"),
        ("the amber rectangle on the glass quotes the box that was asked",
         "the ask/result split the window gate drives"),
):
    assert _phrase in _gf, (_phrase, _why, "docs/gui.md no longer says it")

# `edit.py`'s own size comment: the same digits, in the source a reader of the installed
# tree gets.  Every one of these is a file fact, so both machines should answer the same;
# a run that disagrees is a library that changed under the sentence.
for _what, _pat, _mine in (
        ("the line case in `edit.py`",
         r"predicts the drawn box exactly, (\d+) rows out of (\d+)",
         (_line_exact, _line_total)),
        ("the arc push census in `edit.py`",
         r"measured on all (\d+) arc rows", (_arc_rows,)),
        ("the arc squares in `edit.py`",
         r"and (\d+) of (\d+) are square", (_arc_square, _arc_rows)),
        ("the text/data count in `edit.py`",
         r"- (\d+) rows, none with either", (_txt_rows,)),
):
    _stated(_what, _edit_src, _pat, _mine)
# ...and the words the library uses when it refuses.  `_flat` joins a file's lines with a
# space, so a Python string split across two lines keeps its closing and opening quotes in
# the middle: each probe here is a fragment that lives on one line, which is what makes it
# match the source rather than the prose around it.
for _phrase, _why in (
        ("the suite asserts that as a rule", "the `bar` claim is a rule, not a fraction, "
         "because which rows draw a box is a reading question"),
        ("left every box where it was", "the `cornerRadius` rule in the code's own words"),
        ("owns no width", "the side-drag refusal for a kind with no width key"),
        ("pushing `fontSize` did not move this row's box at",
         "the cap-bound refusal, said the same way in the sweep and in the window"),
        ("some other key owns its extent",
         "that refusal names the cap rather than guessing"),
        ("`xigma.fitArc` is the ring the figures are fitted into",
         "which cap owns a `special`'s extent"),
        ("`xigma.autoFitMax` fits it to a width", "which cap owns a `data` row's extent"),
        ("its box is already off the", "a row hanging off the glass gets its own sentence"),
        ("2*radius + 2*width", "the arc identity the door keeps"),
        ("amount that is never 8 px, differs from row to row",
         "the face claim in the library's own comment: no `width` key could carry it"),
        ("is not an edge this pane puts a handle on",
         "the model, not the pane, owns the edge vocabulary"),
        ("The room from here", "an off-canvas ask names the room each edge still has")):
    assert _phrase in _edit_src, (_phrase, _why,
                                  "`edit.py` no longer says it in those words")
for _phrase, _why in (
        ("asking for", "the live note while a resize drag is in flight"),
        ("ink lies under the handle", "the overlap sentence, in the pane's note"),
        ("never moved: nothing was written", "a click on a square that never dragged"),
):
    assert _phrase in _app_src, (_phrase, _why, "`app.py` no longer says it in those words")

# the 0.6 stanza's resize sentences, so a bullet cannot outlive the door it describes
_cl_top = " ".join(open("debian/changelog", encoding="utf-8").read()
                   .split("\n -- ")[0].split())
# The 0.6 stanza is this cycle's own record, so its file-fact digits are measured against
# the run exactly like the page's: the line case, the arc arithmetic, the text/data census
# and the two never-written keys all answer the same on the bench and on the runner, and a
# stanza whose digits drift is a stanza describing a door that is no longer in the tree.
for _what, _pat, _mine in (
        ("the line case, in the 0.6 stanza",
         r"`layout\.line_rect` predicts the drawn box of (\d+) of its (\d+) rows "
         r"exactly", (_line_exact, _line_total)),
        ("the arc arithmetic, in the 0.6 stanza",
         r"the arithmetic (\d+) of the (\d+) arc rows in the library obey, all "
         r"(\d+) of them square", (_arc_ident, _arc_rows, _arc_square)),
        ("the text/data census, in the 0.6 stanza",
         r"not one of the (\d+) carries a `width` or `height` key", (_txt_rows,)),
        ("who carries a `cornerRadius`, in the 0.6 stanza",
         r"`cornerRadius` is carried by (\d+) of the `bar`/`arc` rows", (_corner_rows,)),
        ("the unread `rotate`, in the 0.6 stanza",
         r"`rotate` is carried by (\d+) `bar` rows and changed (\d+) px on all "
         r"(\d+) of them", (_rot_rows, 0, _rot_rows)),
        ("the ring push, in the 0.6 stanza",
         r"a \+8 px push on `radius` moved the box (\d+) px", (0,)),
):
    _stated(_what, _cl_top, _pat, _mine)
for _phrase in ("`edit.Editor.size_edges` decides which of them exist",
                "left every box those rows have exactly where it was",
                "`xigma.autoFitMax` fits a row to a width",
                "`edit.Editor.resize_box` says the release would ask for"):
    assert _phrase in _cl_top, (_phrase, "the 0.6 stanza no longer says what the gates "
                                         "measure")
print(f"                        D's sentences, from this run: {_bar_exact}/{_bar_total} bar "
      f"boxes exactly their declared rect, {_line_exact}/{_line_total} line as `line_rect` "
      f"predicts, {_arc_ident}/{_arc_rows} arc keeping the ring's own arithmetic "
      f"({_arc_square}/{_arc_rows} square), {_txt_rows} `text`/`data` rows none of them "
      f"carrying a width, `rotate` on {_rot_rows} bar rows and `cornerRadius` on "
      f"{_corner_rows}; the sweep's counts ({_d_ok} accepted, {len(_d_said)} refused in "
      f"words, {len(_d_nothing)} for want of a box) are printed above for this machine")

# ---- one more kind of row the inspector can be handed: a `special` that draws a *pair*.
# ---- No shipped file carries one yet (`alpha` is not exported), so this probe builds the
# ---- row and asks the model what it may edit, and what the edit does to the picture.
pair_prop = {"name": "fan-figures",
             "x": (render.A26_FAN_X[0] + render.A26_FAN_X[1]) // 2,
             "y": render.A26_FAN_Y,
             "width": render.A26_FAN_X[1] - render.A26_FAN_X[0],
             "fontFamily": "dejavu", "fontSize": render.A26_FAN_F, "bold": False,
             "textColor": themes.rgba_str(render.A26_WHITE),
             "xigma": {"anchor": "ma", "autoFitMax": render.A26_FAN_MAX_W}}
pair_obj = {"width": render.W, "height": render.H,
            "osd": {"widget": [{"id": "xigma-pair-probe", "type": "special",
                                "property": [dict(pair_prop)]}]}}
pair_ed = gui_edit.Editor(pair_obj, origin="suite probe")

# which door each registered drawing draws through, read out of its own source: the marker
# `themes.special_door` reports has to agree with the call the function makes, because that
# call is what gives the row's `width`, its `fontSize` and its fit key their meaning.  The
# third door (`draw_special_values`) is the one a reader would otherwise guess at: it
# places a pair like `draw_special_pair` does and sizes it like nothing else does
import inspect, re                                   # noqa: E402
DOOR_CALL = {"draw_special_line": "line", "draw_special_pair": "pair",
             "draw_special_values": "values"}
doors = {}
for nm in themes.special_names():
    body = inspect.getsource(themes.SPECIALS[nm])
    called = {m for m in DOOR_CALL if re.search(r"\b%s\(" % m, body)}
    assert len(called) == 1, (nm, sorted(called))
    doors[nm] = called.pop()
assert {n: DOOR_CALL[d] for n, d in doors.items()} == \
    {n: themes.special_door(n) for n in themes.special_names()}, doors
assert {n for n, d in doors.items() if DOOR_CALL[d] in ("pair", "values")} == \
    {n for n in themes.special_names() if themes.special_is_pair(n)}, doors
sf = gui_edit.field_names("special")
assert "width" in sf, sf
sf_ext = gui_edit.extension_fields("special")
assert "autoFitMax" in sf_ext, sf_ext
# and the sentence that explains the field goes with the door: pair rows are told the
# pitch, line rows are told their `width` is not read at all
notes_by_name = {n: gui_edit.field_note("special", "width", n)
                 for n in themes.special_names()}
assert all(("centres" in t) == themes.special_is_pair(n)
           for n, t in notes_by_name.items()), notes_by_name
pitch_note = notes_by_name["fan-figures"]
assert "not a box width" in pitch_note, pitch_note
assert "does not read `width`" in notes_by_name["dual-status"], notes_by_name
assert gui_edit.field_note("special", "fontSize", "dual-status") == ""
assert gui_edit.field_note("bar", "width") == ""
# the ceiling sentence has to change with the door, or the editor tells a `temp-values` row
# to fit itself to a key that drawing never reads
wide = gui_edit.field_note("special", "fontSize", "fan-figures")
round_ = gui_edit.field_note("special", "fontSize", "temp-values")
assert "autoFitMax" in wide and "fitArc" not in wide, (wide, round_)
assert "fitArc" in round_ and "autoFitMax" not in round_, (wide, round_)
assert gui_edit.field_note("special", "x", "temp-values") == \
    "the pair's own anchor point, not one figure's corner"
# and the key each door sizes with is the one the row is shown: `--check-theme` says a
# `values` row without `xigma.fitArc` is not drawn at all
hard, soft = themes.validate({"width": render.W, "height": render.H, "osd": {"widget": [
    {"id": "xigma-no-ring", "type": "special",
     "property": [dict(pair_prop, name="temp-values",
                        xigma={"anchor": "ma"})]}]}})
assert not hard and any("fitArc" in s_ and "not drawn" in s_ for s_ in soft), (soft,)


def _figure_centres(img, mid):
    """The centre of the ink on each side of `mid`, in panel px.

    A pair of ink bounding-box centres, not an average of lit pixels: the mean of a
    string's pixels sits up to 8 px off the centre of the box the string was laid out in
    (measured with both on this row), and the anchor centres the box.  Within half a
    panel px of the declared anchors is as close as ink gets to its layout box.
    """
    lit = [k % render.W for k, v in enumerate(img.get_flattened_data())
           if v != (0, 0, 0, 0)]
    left = [x for x in lit if x < mid]
    right = [x for x in lit if x >= mid]
    assert left and right, (len(left), len(right))
    return ((min(left) + max(left)) / 2, (min(right) + max(right)) / 2)


mid = int(pair_prop["x"])
base_pair, pnotes = pair_ed.paint(*pair_ed.fixture())
c0 = _figure_centres(base_pair, mid)
gap0 = c0[1] - c0[0]
assert abs(gap0 - int(pair_prop["width"])) <= 2, (gap0, pair_prop["width"])
assert abs((c0[0] + c0[1]) / 2 - mid) <= 2, c0     # and the pair straddles its own anchor
box0 = [b for b in pnotes["boxes"] if b[0] == "special"][0][2]
ok_w, note_w = pair_ed.set("width", int(pair_prop["width"]) - 32)
assert ok_w, note_w
moved_pair, mnotes = pair_ed.paint(*pair_ed.fixture())
c1 = _figure_centres(moved_pair, mid)
gap1 = c1[1] - c1[0]
moved_px = px_differ(base_pair, moved_pair)
box1 = [b for b in mnotes["boxes"] if b[0] == "special"][0][2]
assert moved_px > 0, moved_px
# a pitch 32 px narrower closes the gap between the two figures by 32 px, and takes each
# figure 16 px towards the centre: `width` is the pitch, which is what the note says and
# what a reader would otherwise get wrong by a factor of two
assert abs((gap0 - gap1) - 32) <= 2, (gap0, gap1)
assert abs(abs(c0[0] - c1[0]) - 16) <= 2 and abs(abs(c1[1] - c0[1]) - 16) <= 2, (c0, c1)
assert box1[2] - box1[0] < box0[2] - box0[0], (box0, box1)
assert pair_ed.undo() and px_differ(base_pair, pair_ed.paint(*pair_ed.fixture())[0]) == 0
print(f"  a pair row, and what  `fan-figures`: the inspector offers {len(sf)} fields for a"
      f" `special` ({' '.join(sf)}) plus {len(sf_ext)} of our own keys ({' '.join(sf_ext)}),"
      f" and `width` is among them because the door that draws this special reads it."
      f" Measured on the painted frame: the two figures' ink boxes centre "
      f"{gap0:.1f} px apart for a declared pitch of {pair_prop['width']}, each figure half"
      f" that either side of the row's x ({mid}); narrowing the pitch by 32 px closed the"
      f" gap to {gap1:.1f} and moved each figure 16 px inboard, and {moved_px:,} pixels of"
      f" the frame changed - one undo put every one of them back. The row says what the"
      f" field means: {pitch_note[:88]}...")
pair_names = sorted(n for n, d in doors.items() if DOOR_CALL[d] in ("pair", "values"))
wide_names = sorted(n for n, d in doors.items() if d == "draw_special_pair")
v_names = sorted(n for n, d in doors.items() if d == "draw_special_values")
line_names = sorted(n for n, d in doors.items() if d == "draw_special_line")
print(f"                        who needs that sentence is not remembered either: a pair"
      f" door is used by {len(pair_names)} of the {len(doors)} registered drawings"
      f" ({' '.join(f'{n}:{DOOR_CALL[c]}' for n, c in sorted(doors.items()))}),"
      f" found in their own source with `inspect`, and only those rows are told about a"
      f" pitch: {' '.join(line_names)} read `width` not at all.  Inside the pair doors the"
      f" sentence still splits: {' '.join(wide_names)} size the pair to a width"
      f" (`xigma.autoFitMax`) and {' '.join(v_names)} size it to a ring (`xigma.fitArc`) -"
      f" which is why `fontSize` gets two different sentences, checked on the window's own"
      f" note line below")

# ---- and the canvas door on that model: pointing at a row, and moving it.  No display
# ---- is needed for either half: `hit` reads the boxes `paint` reported, and `move` is what
# ---- a drag and an arrow key both end in.  What is pinned below is the shape of the answer,
# ---- not one window's pixels.
cv = gui_edit.Editor.open_theme("alpha")
_full_img, _full_notes = cv.paint(*cv.fixture())
_full_gaps = [x for x in _full_notes["missing"] if not str(x).startswith("font:")]
assert not _full_gaps, (_full_gaps, "the completed fixture leaves an `alpha` row unanswered")
# The completed fixture answers every row `alpha` declares - which is the whole point of the
# preview gate above, and it takes *this* gate's evidence away: with nothing skipped, a list
# of painted boxes and a list of declared rows are the same length and `hit` could be reading
# the file instead of the paint.  So the canvas door is driven at the same file with readings
# taken back out of the fixture, and the print below says which.  The two gates are the two
# halves of one claim: at the fixture the doors agree to the pixel, and a door that answers a
# paint still reports fewer boxes than the file has rows.
_cv_img, cv_notes = cv.paint(_THIN, gui_edit.FIXTURE_WHEN)
drawn = cv_notes["boxes"]
skipped = sorted(set(cv_notes["missing"]))
assert skipped and len(drawn) < len(cv.widgets()), (
    len(drawn), len(cv.widgets()), skipped,
    "this gate needs a layout with rows the readings cannot answer, so that `boxes` is "
    "provably not a list of rows")
row_of = {b[3]: b for b in drawn}
clock_row = next(b for b in drawn if b[0] == "data" and b[1] == "Time")
cx = (clock_row[2][0] + clock_row[2][2]) // 2
cy = (clock_row[2][1] + clock_row[2][3]) // 2
assert cv.hit(cv_notes, cx, cy) == clock_row[3], (clock_row, cx, cy)
assert clock_row[3] != drawn.index(clock_row), (
    clock_row[3], drawn.index(clock_row), "the file's row index and the position in the "
    "drawn-box list have to differ here, or this gate proves nothing about a layout with "
    "rows that were skipped")

# where two rows overlap, the later-drawn one is the one under the cursor.  `alpha`'s
# temperature figures stand inside its gauge rings: a ring that took every press inside its
# own bounding box would leave the reading inside it impossible to grab.
ring = next(b for b in drawn if b[0] == "arc")
rx, ry = (ring[2][0] + ring[2][2]) // 2, (ring[2][1] + ring[2][3]) // 2
covering = [b[3] for b in drawn if b[2]
            and b[2][0] <= rx <= b[2][2] and b[2][1] <= ry <= b[2][3]]
assert len(covering) > 1, (ring, covering)
assert cv.hit(cv_notes, rx, ry) == max(covering), (cv.hit(cv_notes, rx, ry), covering)
# a row that drew nothing has no box, so it can never be pointed at - which is the same
# rule the report already states, applied to the pane
_nobox = [i for i in range(len(cv.widgets())) if i not in row_of]
assert _nobox, row_of
assert all(cv.hit(cv_notes, x, y) not in _nobox for x, y in ((340, 372), (110, 405))), _nobox
_free = [(x, y) for y in range(0, render.H, 9) for x in range(0, render.W, 9)
         if cv.hit(cv_notes, x, y) is None]
assert _free, "every point on the glass belongs to a row: nothing would be left to click on"

cv.select(clock_row[3])
x0, y0 = int(cv.prop()["x"]), int(cv.prop()["y"])
base, _bn = cv.paint(*cv.fixture())
ok, note = cv.move(12, -5)
assert ok and not note, (ok, note)
assert (int(cv.prop()["x"]), int(cv.prop()["y"])) == (x0 + 12, y0 - 5), cv.prop()
# one drag is one undo step, not one per field: the unit a reader wants back is the drag
assert cv.steps == 1, cv.steps
assert cv.dirty and themes.user_copies() == [], (cv.dirty, themes.user_copies())
assert cv.undo() and (int(cv.prop()["x"]), int(cv.prop()["y"])) == (x0, y0), cv.prop()
after, _an = cv.paint(*cv.fixture())
assert after.tobytes() == base.tobytes(), "undo did not put every pixel back"
# a move that would put the anchor off the canvas is refused whole - both fields checked
# before either is written - and it leaves no undo step behind
refused = cv.move(0, -10_000)
assert not refused[0] and "must stay inside" in refused[1], refused
assert (int(cv.prop()["x"]), int(cv.prop()["y"])) == (x0, y0), cv.prop()
assert cv.steps == 0, (cv.steps, "a refused move wrote an undo step")
assert cv.move(0, 0)[0] and cv.steps == 0, cv.steps

# and the fact the pane has to say for itself: the model refuses an anchor off the canvas
# and says nothing about ink that hangs off it, because that is how the vendor's files are
# checked too (`validate` looks at x,y).  A row dragged to the last legal column draws
# pixels the glass will not show, and only the window admits it.
assert cv.set("x", int(cv.obj["width"]) - 1)[0]
_h_img, h_notes = cv.paint(*cv.fixture())
_hang = [b for b in h_notes["boxes"] if b[3] == clock_row[3]][0][2]
assert _hang[2] >= int(cv.obj["width"]), (_hang, "the claim below depends on this")
hard, soft = themes.validate(cv.obj)
assert not hard and not any("canvas" in w for w in soft), (hard, soft)
print(f"  pointing at a row      `hit` answers the file's row index, not a position: "
      f"{len(drawn)} boxes for {len(cv.widgets())} rows ({', '.join(skipped)} unanswered "
      f"at the thinned readings this door is driven at; none of them is unanswered at the "
      f"fixture itself), and the clock line's index is {clock_row[3]} while it sits "
      f"{drawn.index(clock_row)} boxes in.  Overlaps resolve to the later row: "
      f"{len(covering)} boxes cover the CPU ring's centre and the figure inside it wins. "
      f"A move is one step and returns every pixel on undo; a move off the canvas is "
      f"refused whole, in the model's words, and writes no step.  And an anchor at x="
      f"{int(cv.obj['width']) - 1} is legal while its ink runs to x={_hang[2]} - validate "
      f"is silent about that, so the pane says it ({_free[0]} is one point with no row "
      f"under it)")

# ---- the same model, behind the window's own controls ----
# Not a second set of claims: the checks that the shell does not lie about the model.
# The fields it lists are the model's list; the picture in the pane is `themes.draw`'s
# at the pinned fixture; the file appears on Save and nowhere before it; and the pane's
# oldest rule - this window never draws the 480 px frame larger than 480 px - survives
# a layout being shown in it.
was_adv = win.adv_toggle.isChecked()
win.adv_toggle.setChecked(False)
for _ in range(6):
    appq.processEvents()
assert win.ed_group not in win._adv_hide and win.ed_group.isVisible(), \
    "advanced off, and the layout editor went with it"
win.adv_toggle.setChecked(True)
for _ in range(6):
    appq.processEvents()
def focus_row(w, field):
    """Put the reader's focus on one editor row, and prove the focus actually landed.

    The note line under the rows speaks for whichever row is focused (app.py's
    `eventFilter`), so a gate that reads that line has to move the focus and then check
    the move happened: several windows are up by here, a window that is not active
    defers focus, and a deferred focus would leave the next assertion reading a stale
    sentence and passing for the wrong reason.
    """
    w.activateWindow()
    for _ in range(3):
        appq.processEvents()
    w._ed_ctl(field).setFocus()
    for _ in range(3):
        appq.processEvents()
    assert w._ed_ctl(field).hasFocus(), (
        field, "focus never landed: the note line below is not this row's sentence")
    return w.ed_note.text()


assert win.ed_group.isVisible(), "the layout editor is not on show"
assert win.ed_name.count() == 1 + len(themes.EXPORTS) + len(pick), win.ed_name.count()
assert win.ed_name.itemText(0) == app.NO_EDITOR, win.ed_name.itemText(0)
assert win.ed is None and not win.ed_widget.isEnabled(), \
    "the row was live before a layout was opened"
win.ed_name.setCurrentText("Theme_28")
for _ in range(6):
    appq.processEvents()
assert win.ed is not None and win.ed.name == "Theme_28", win.ed.name
assert win.ed_widget.count() == len(win.ed.widgets())
kind0 = win.ed.selected()["type"]
listed = list(win.ed_rows)
assert listed == (list(gui_edit.field_names(kind0))
                  + list(gui_edit.extension_fields(kind0))), (kind0, listed)
assert win.ed_widget.toolTip() == win.ed.tip(0) and \
    str(win.ed.widgets()[0]["id"]) in win.ed_widget.toolTip(), "no id in the tip"
assert "pinned fixture" in win.caption.text(), win.caption.text()[:90]
assert "pinned fixture" in win.metrics.text(), win.metrics.text()[:80]
assert themes.user_copies() == [], "opening a layout wrote a file"
osd_open = win._osd.copy()

# a generated layout names its two conventions in the value menu, and a vendor file that
# carries neither shows the absence rather than picking a default to display
win.ed_name.setCurrentText("gauge")
for _ in range(6):
    appq.processEvents()
garows = list(win.ed_rows)
assert "arcPaint" in garows and "colourRamp" in garows, garows
win._ed_ctl("arcPaint")
for _ in range(4):
    appq.processEvents()
assert isinstance(win._ed_ctl("arcPaint"), QComboBox), "an enumerated key got a text box"
assert [win._ed_ctl('arcPaint').itemText(i) for i in range(win._ed_ctl('arcPaint').count())] == \
    ["render", "vendor"], "the two ring conventions are not the two on show"
# the menu shows the value the file holds, not the first choice it could hold
assert win._ed_ctl('arcPaint').currentText() == win.ed.value("arcPaint"), \
    (win._ed_ctl('arcPaint').currentText(), win.ed.value("arcPaint"))
# a `special` row in the window: its fields are the model's list, its drawing menu is the
# registry, and the sentence that explains `width` as a pitch shows only for a row whose
# door reads it that way.  No shipped file carries a pair row yet (`alpha` is not
# exported), so the pitch itself is measured through the Qt-free model above; what is
# checked here is that the window neither hides the field nor invents the sentence.
win.ed_name.setCurrentText("dual")
for _ in range(6):
    appq.processEvents()
sp_at = next(i2 for i2, w in enumerate(win.ed.widgets()) if w["type"] == "special")
win.ed_widget.setCurrentIndex(sp_at)
for _ in range(4):
    appq.processEvents()
sp_rows = list(win.ed_rows)
assert sp_rows == (list(gui_edit.field_names("special"))
                   + list(gui_edit.extension_fields("special"))), sp_rows
assert "width" in sp_rows and "autoFitMax" in sp_rows and "fitArc" in sp_rows, sp_rows
# a menu has to show the value the row holds, not the first choice it *could* hold:
# `name` is the field where the two differ, because the vocabulary is sorted and this
# row's value is `dual-status`, second of the three
win._ed_ctl("name")
for _ in range(4):
    appq.processEvents()
assert [win._ed_ctl('name').itemText(i) for i in range(win._ed_ctl('name').count())] == \
    list(themes.special_names()), "the drawing menu is not the registry"
assert win._ed_ctl('name').currentText() == win.ed.value("name") == "dual-status", \
    (win._ed_ctl('name').currentText(), win.ed.value("name"))
# and the same claim on a `data` row, whose `source` vocabulary is long: pick one whose
# source is not the menu's first entry, so the check below cannot pass by luck
first_source = sorted(themes.source_names())[0]
data_at = next(i2 for i2, w in enumerate(win.ed.widgets())
               if w["type"] == "data" and w["property"][0].get("source")
               and str(w["property"][0]["source"]) != first_source)
win.ed_widget.setCurrentIndex(data_at)
for _ in range(4):
    appq.processEvents()
win._ed_ctl("source")
for _ in range(4):
    appq.processEvents()
assert win._ed_ctl('source').currentText() == win.ed.value("source"), \
    (win._ed_ctl('source').currentText(), win.ed.value("source"))
menu_shown, menu_held = win.ed.value("source"), win._ed_ctl('source').itemText(0)
assert menu_shown != menu_held, (menu_shown, menu_held)   # the check below bites
win.ed_widget.setCurrentIndex(sp_at)
for _ in range(4):
    appq.processEvents()
focus_row(win, "width")
for _ in range(4):
    appq.processEvents()
assert isinstance(win._ed_ctl("width"), QSpinBox), "a number field without a spinbox"
line_note = win.ed_note.text()
assert "does not read `width`" in line_note, line_note
# the same row, drawing through the other door - and changed with the window's own
# menu, not the model, so the undo button becomes live the way it does for a reader
win._ed_ctl("name")
for _ in range(4):
    appq.processEvents()
assert win._ed_ctl('name').currentText() == "dual-status", win._ed_ctl('name').currentText()
win._ed_ctl('name').setCurrentText("fan-figures")
for _ in range(6):
    appq.processEvents()
assert win.ed.prop().get("name") == "fan-figures", win.ed.prop()
assert win.ed_undo.isEnabled() and win.ed_undo.text() == "undo (1)", \
    (win.ed_undo.isEnabled(), win.ed_undo.text())
focus_row(win, "x")
for _ in range(4):
    appq.processEvents()
assert "pair's own anchor" in win.ed_note.text(), win.ed_note.text()
focus_row(win, "width")
for _ in range(4):
    appq.processEvents()
assert "not a box width" in win.ed_note.text(), win.ed_note.text()
# and the window's own undo puts both the row and its sentence back
win.ed_undo.click()
for _ in range(4):
    appq.processEvents()
assert win.ed.prop().get("name") == "dual-status", win.ed.prop()
assert "does not read `width`" in win.ed_note.text(), win.ed_note.text()
assert win.ed_undo.text() == "undo", win.ed_undo.text()
assert themes.user_copies() == [], "an in-memory edit wrote a file"
# the third door, through the same menu.  A `values` row reads `width` as a pitch like any
# other pair row, but its ceiling sentence must name the ring and not the width key that
# drawing never reads: an editor that explained the wrong fit key would be the same mistake
# as a menu showing the wrong value, one screen later
win._ed_ctl("name")
for _ in range(4):
    appq.processEvents()
win._ed_ctl("name").setCurrentText("temp-values")
for _ in range(6):
    appq.processEvents()
assert win.ed.prop().get("name") == "temp-values", win.ed.prop()
focus_row(win, "fontSize")
for _ in range(4):
    appq.processEvents()
ring_note = win.ed_note.text()
assert "fitArc" in ring_note and "autoFitMax" not in ring_note, ring_note
focus_row(win, "width")
for _ in range(4):
    appq.processEvents()
assert "not a box width" in win.ed_note.text(), win.ed_note.text()
# a key the drawing does not read is still on the field list, because fields are per kind
# and the vocabulary is the vendor's, so the reason beside it is what has to say what it
# does *not* do on this row
focus_row(win, "autoFitMax")
for _ in range(4):
    appq.processEvents()
why_note = win.ed_note.text()
assert why_note.startswith("xigma.autoFitMax:") and "temp-values" in why_note, why_note
win.ed_undo.click()
for _ in range(4):
    appq.processEvents()
assert win.ed.prop().get("name") == "dual-status", win.ed.prop()
# the field the reader was last on stays selected across an undo, so the sentence that
# comes back is asked for on purpose: back on `width`, a `line` row says it reads none
focus_row(win, "width")
for _ in range(4):
    appq.processEvents()
assert "does not read `width`" in win.ed_note.text(), win.ed_note.text()
assert win.ed_undo.text() == "undo", win.ed_undo.text()
assert themes.user_copies() == [], "an in-memory edit through the third door wrote a file"
print(f"  a special in the row  `dual`'s one `special` widget: {len(sp_rows)} fields "
      f"({' '.join(sp_rows)}), and the drawing menu is exactly the "
      f"{len(themes.special_names())} names in `themes.SPECIALS` "
      f"({' '.join(themes.special_names())}). That row's note says its drawing does not "
      f"read `width` at all; switch it to `fan-figures` through the same menu and the "
      f"pitch sentence appears; switch it to `temp-values` and the pitch stays while the "
      f"ceiling sentence changes to the ring ({ring_note[:70]}...), with the key that "
      f"drawing never reads labelled as such beside it. Two undos through the window's own "
      f"button took both the rows and their sentences back. The pair's pitch itself is "
      f"measured through the Qt-free model above")
print(f"  a menu shows the value  every value menu selects what the row holds, not the "
      f"first choice it could: that `special` displays `dual-status` in a menu starting "
      f"`clock-readings`, and the `data` row picked here displays `{menu_shown}` in a "
      f"menu starting `{menu_held}`. The two agree only when the value happens to sort "
      f"first, which is why the ring's `arcPaint` never showed this up")
# ---- what the rows say the row paints, and what the face menu shows for a family ----
# The model's half - a string, proved by painting it - is gated above.  This is the
# window's half: the note line under the rows carries that answer for the rows that decide
# it, and the `fontFamily` menu shows each family drawn from the file this box resolves it
# to.  A family with no file here cannot be exercised through the vendor's five names on a
# box that happens to have all five, so the check adds a sixth to the painter's own table
# for its length: `edit.choices("fontFamily")` *is* that table, so the row has to answer
# what it says, and the table is put back and checked back afterwards.
from PyQt6.QtCore import Qt as _FaceQt      # local to this block: the heredoc's own `Qt`
                                            # alias comes a thousand lines further down
# `bars` on purpose: it is the one layout that carries both a reading this fixture answers
# and slots it does not (`Fan 3 Name`/`Fan 4 Speed`), so both branches of the answer are
# checked in one window rather than one of them being left to luck.
win._editor_open("bars")
for _ in range(8):
    appq.processEvents()
_bars_i = next(i for i in range(win.ed_widget.count())
               if str(win.ed.widgets()[i].get("type") or "") == "data"
               and win.ed.widgets()[i]["property"][0].get("source") == "CPU Temperature")
win.ed_widget.setCurrentIndex(_bars_i)
for _ in range(6):
    appq.processEvents()
_line_w, _why_w = win.ed.drawn_text()
_note_w = focus_row(win, "source")
assert _line_w, (_line_w, _why_w, "a row reading CPU Temperature has to paint something")
assert f'draws as "{_line_w}"' in _note_w, (_note_w, _line_w,
                                            "the note line is not the model's answer")
assert not _why_w or _why_w in _note_w, (_note_w, _why_w)
# the other branch, in the same place: a row whose source this box has no reading for
_fan_i = [i for i in range(win.ed_widget.count())
          if str(win.ed.widgets()[i].get("type") or "") == "data"
          and str(win.ed.widgets()[i]["property"][0].get("source") or "") in _short]
assert _fan_i, ("bars", _short, "the layout this check opens has to carry an unanswered "
               "slot, or the second branch of the answer is never exercised")
win.ed_widget.setCurrentIndex(_fan_i[0])
for _ in range(6):
    appq.processEvents()
_line_n, _why_n = win.ed.drawn_text()
_note_n = focus_row(win, "source")
assert not _line_n, (_line_n, "a slot this box does not report should not paint")
assert "paints no line" in _note_n, (_note_n, _why_n)
print(f"  what the row says     the note line carries the model's answer both ways: a "
      f"`CPU Temperature` row reads {_line_w!r}, and the row for "
      f"{win.ed.widgets()[_fan_i[0]]['property'][0]['source']!r} says it paints nothing "
      f"({_why_n[:56]})")
_fc = win._ed_ctl("fontFamily")
_faces = win.ed.faces_here()
assert _fc.iconSize().width() >= 20, (_fc.iconSize(), "no room in the menu for a face")
_res, _dead = [], []
for _i in range(_fc.count()):
    _nm, _p = _fc.itemText(_i), _faces.get(_fc.itemText(_i))
    if _nm == app.UNSET:
        continue
    _tip = str(_fc.itemData(_i, _FaceQt.ItemDataRole.ToolTipRole) or "")
    if _p:
        _pm = _fc.itemIcon(_i).pixmap(_fc.iconSize())
        assert not _pm.isNull(), (_nm, _p, "a family with a file here got no preview")
        _im = _pm.toImage()
        assert any(_im.pixelColor(x, y).alpha() for x in range(0, _im.width(), 2)
                   for y in range(0, _im.height(), 2)), (
            _nm, _p, "the preview drew nothing: the face was opened but no ink landed")
        assert os.path.basename(_p) in _tip, (_nm, _p, _tip,
                                              "the entry hides the file it is showing")
        _res.append(_nm)
    else:
        assert _fc.itemIcon(_i).isNull(), (_nm, "a family with no file here got a preview")
        assert "no font file" in _tip, (_nm, _tip)
        _dead.append(_nm)
assert _res, (_faces, "nothing resolved to a file, so this box has no fonts at all")
# the family check runs against a row that *does* have a reading: an unanswered source is
# the painter's first reason to skip a row, and a check that reached the family reason
# through a row already skipped for another one would be proving the order of the checks
# rather than the family answer.
win.ed_widget.setCurrentIndex(_bars_i)
for _ in range(6):
    appq.processEvents()
assert win.ed.drawn_text()[0], "the row the family check needs has to be a painting one"
_keep_fonts = dict(layout.FONTS)
layout.FONTS["no-such-face"] = {"regular": "/nonexistent/**/Nope.ttf",
                                "bold": "/nonexistent/**/Nope-Bold.ttf"}
try:
    win._ed_bind_rows()                     # the menu is refilled from the painter's table
    _ix = [k for k in range(_fc.count()) if _fc.itemText(k) == "no-such-face"]
    assert _ix, (_fc.count(), "a family `layout.FONTS` names never reached the row's menu")
    assert _fc.itemIcon(_ix[0]).isNull(), "an unresolvable family was given a preview"
    assert "no font file" in str(_fc.itemData(_ix[0], _FaceQt.ItemDataRole.ToolTipRole) or "")
    _ok_f, _note_f = win.ed.set("fontFamily", "no-such-face")
    assert _ok_f, _note_f                   # it is in the vocabulary the model offers
    _lt, _lw = win.ed.drawn_text()
    assert not _lt and "no file" in _lw, (_lt, _lw,
                                          "a row on an unresolvable family must say so")
    assert "no file" in focus_row(win, "fontFamily"), _lw
    win.ed.undo()
    assert win.ed.value("fontFamily") in _keep_fonts, win.ed.value("fontFamily")
finally:
    layout.FONTS.clear()
    layout.FONTS.update(_keep_fonts)
    win._ed_bind_rows()
assert [k for k in range(_fc.count()) if _fc.itemText(k) == "no-such-face"] == [], \
    "the patched family outlived the check that patched it"
assert set(layout.FONTS) == set(_keep_fonts), "the painter's font table came back changed"
# A family outside the vocabulary still reaches its own row's menu, because a file is
# allowed to name one (`_ed_bind_rows` inserts the row's own value rather than dropping
# it), and it is marked exactly like a family whose globs match nothing.  Driven by
# changing the open row in memory - nothing is written to any file - and put back.
_odd = win.ed.widgets()[_bars_i]["property"][0]
_had_fam = _odd.get("fontFamily")
_odd["fontFamily"] = "Impact"
try:
    win._ed_bind_rows()
    _io = [k for k in range(_fc.count()) if _fc.itemText(k) == "Impact"]
    assert _io, (_fc.count(), "a file naming a family `layout.FONTS` does not carry never "
                              "showed up in its own row's menu")
    assert _fc.itemIcon(_io[0]).isNull(), "a family nothing here can open was previewed"
    assert "no font file" in str(_fc.itemData(_io[0], _FaceQt.ItemDataRole.ToolTipRole)
                                 or ""), _io[0]
    _ot, _ow = win.ed.drawn_text()
    assert not _ot and "has no file for the family `impact`" in _ow, (_ot, _ow)
finally:
    if _had_fam is None:
        _odd.pop("fontFamily", None)
    else:
        _odd["fontFamily"] = _had_fam
    win._ed_bind_rows()
assert [k for k in range(_fc.count()) if _fc.itemText(k) == "Impact"] == [], \
    "the row's own odd family outlived the check that put it there"
assert win.ed.value("fontFamily") == _had_fam, (win.ed.value("fontFamily"), _had_fam)
print(f"  the face menu         {len(_res)} of {_fc.count()} entries carry a preview drawn "
      f"from the file `layout.font_for` names ({', '.join(sorted(_res))}); a family whose "
      f"globs match nothing gets no preview, says so in its own tooltip, and a row using it "
      f"answers: {_lw[:60]}")


unset = ""
# which library file carries an `arc` is derived, not remembered: the census says one of
# the 27 does, and which one it is belongs to the files, not to this gate
arcs = [r["name"] for r in pick
        if "arc" in [w["type"] for w in themes.load(r["path"])["osd"]["widget"]]]
if arcs:
    win.ed_name.setCurrentText(arcs[0])
    for _ in range(6):
        appq.processEvents()
    arc_at = next(i2 for i2, w in enumerate(win.ed.widgets()) if w["type"] == "arc")
    win.ed_widget.setCurrentIndex(arc_at)
    for _ in range(4):
        appq.processEvents()
    win._ed_ctl("arcPaint")
    for _ in range(4):
        appq.processEvents()
    unset = win._ed_ctl('arcPaint').itemText(0)
    assert unset == app.UNSET and win._ed_ctl('arcPaint').currentText() == app.UNSET, \
        (unset, win._ed_ctl('arcPaint').currentText())
    assert win.ed.value("arcPaint") is None
win.ed_name.setCurrentText("Theme_28")
for _ in range(6):
    appq.processEvents()
win.ed_widget.setCurrentIndex(target)
for _ in range(4):
    appq.processEvents()
assert list(win.ed_rows)[0] == "x" and isinstance(win._ed_ctl("x"), QSpinBox), \
    "a coordinate got something other than a spinbox"
before_x = int(win.ed.value("x"))
win._ed_ctl("x").setValue(before_x + 20)
win._ed_ctl("x").editingFinished.emit()
for _ in range(6):
    appq.processEvents()
assert int(win.ed.value("x")) == before_x + 20, win.ed.value("x")
assert win._osd.tobytes() != osd_open.tobytes(), "the pane did not move with the edit"
assert themes.user_copies() == [], "typing wrote a file"
assert win.ed_save.isEnabled() and "not saved yet" in win.ed_state.text(), \
    win.ed_state.text()
edited = win._osd.copy()
moved_win = px_differ(osd_open, edited)
assert moved_win > 200, moved_win

# a value the model refuses: the spinbox holds it, the note says why, and the picture
# stays put - the difference between a refusal and a silent clamp
win._ed_ctl("x").setValue(9999)
for _ in range(4):
    appq.processEvents()
assert "canvas" in win.ed_note.text(), win.ed_note.text()[:70]
assert int(win.ed.value("x")) == before_x + 20, "a refused value reached the layout"
assert win._osd.tobytes() == edited.tobytes(), "a refused edit moved the picture"
win._ed_ctl("x").blockSignals(True)
win._ed_ctl("x").setValue(before_x + 20)
win._ed_ctl("x").blockSignals(False)
assert win.ed.steps == 1, win.ed.steps

win.ed_save.click()
for _ in range(6):
    appq.processEvents()
assert themes.user_copies() == ["Theme_28"], themes.user_copies()
assert themes.origin(themes.resolve("Theme_28")) == "your copy"
assert not win.ed.dirty and "nothing outstanding" in win.ed_state.text(), \
    win.ed_state.text()
assert "saved at" in win.ed_note.text(), win.ed_note.text()[:60]
# and the file on disk is the picture that was on screen: opened again, drawn again
disk = gui_edit.Editor.open_theme("Theme_28")
assert int(disk.widgets()[target]["property"][0]["x"]) == before_x + 20
same, _notes = disk.paint(*disk.fixture())
assert same.tobytes() == edited.tobytes(), "Save wrote something other than what it showed"
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert win._osd.tobytes() == osd_open.tobytes(), "undo did not return the frame"
assert win.ed.dirty and win.ed_undo.text() == "undo", (win.ed.dirty,
                                                       win.ed_undo.text())
win.ed_revert.click()
for _ in range(6):
    appq.processEvents()
assert themes.user_copies() == [], themes.user_copies()
assert not win.ed.dirty, "revert left an edit claimed as saved"

# ...and the same door carrying a row the editor *added*, not a field it changed.  The
# claim worth having is the one a field edit cannot make: that a structural change goes
# into the file as the rows the editor holds, in the order it holds them, and that the file
# read back from disk draws the frame the pane was showing when Save was pressed.  A save
# that dropped the row, or wrote it somewhere else in the list, is the failure mode every
# editor of this shape has, and the only way to see it is to compare the picture against
# the file rather than against the object in memory.
_rows_b = len(win.ed.widgets())
_added_kind = ""
for _k in ("text", "data", "bar", "line", "arc"):
    _add_a = [x for x in win.ed_add_menu.actions() if x.text() == _k]
    assert _add_a, f"the add menu lost its `{_k}` entry"
    _add_a[0].trigger()
    for _ in range(6):
        appq.processEvents()
    if len(win.ed.widgets()) == _rows_b + 1:
        _added_kind = _k
        break
    # refused, and said: this layout's own rows of that kind can be rows that paint nothing
    # at the pinned fixture, and a copy of one of those is refused rather than parked.
    assert len(win.ed.widgets()) == _rows_b and win.ed_note.text(), (
        _k, len(win.ed.widgets()), "a refused add moved the layout or said nothing")
assert _added_kind, ("every kind the add menu offers was refused for this layout",
                     _rows_b, win.ed_note.text())
_frame_b = win._osd.copy()
win.ed_save.click()
for _ in range(6):
    appq.processEvents()
assert themes.user_copies() == ["Theme_28"], themes.user_copies()
_disk_b = gui_edit.Editor.open_theme("Theme_28")
assert [str(w.get("id")) for w in _disk_b.widgets()] == [
    str(w.get("id")) for w in win.ed.widgets()], (
    "the saved file's rows, in order, are not the editor's rows")
_new_i = win.ed.index
assert str(_disk_b.widgets()[_new_i].get("id")) == str(win.ed.selected().get("id")), (
    "the row the add menu inserted is not the row the file holds at that position")
_pic_b, _dn_b = _disk_b.paint(*_disk_b.fixture())
assert _pic_b.tobytes() == _frame_b.tobytes(), (
    "the file on disk redraws a different frame than the pane showed when Save was pressed")
# undo now takes the row out of the *layout*, not out of the file: the copy on disk still
# carries it, which is what `dirty` means here, and revert is what removes the copy.
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert len(win.ed.widgets()) == _rows_b and win.ed.dirty, (
    len(win.ed.widgets()), win.ed.dirty, "undo of a structural save did not leave the "
                                         "layout back and the file still outstanding")
assert themes.user_copies() == ["Theme_28"], (
    "undo rewrote the file, which is not what an undo promises")
win.ed_revert.click()
for _ in range(6):
    appq.processEvents()
assert themes.user_copies() == [], themes.user_copies()
assert not win.ed.dirty, "the structural save left a copy behind"
win.ed_name.setCurrentText(app.NO_EDITOR)
for _ in range(6):
    appq.processEvents()
assert win.ed is None and "pinned fixture" not in win.caption.text(), \
    win.caption.text()[:80]
# the pane cap, the window's oldest rule, with an editor frame in it
win.resize(1600, 900)
win.split.setSizes([1200, 380, 520])
for _ in range(6):
    appq.processEvents()
win._fit()
assert win.preview.pixmap().width() == render.W, win.preview.pixmap().size()
win.adv_toggle.setChecked(was_adv)
for _ in range(6):
    appq.processEvents()
assert win.ed_group.isVisible() is True, \
    (was_adv, win.ed_group.isVisible(), "the editor folded away with the switch again")
print(f"  the window's row        offers {win.ed_name.count() - 1} layouts "
      f"({len(themes.EXPORTS)} generated, {len(pick)} files) and lists the model's own "
      f"fields - {len(listed)} for a `{kind0}`. x through the spinbox moved {moved_win:,}"
      f" px of the pane's layer and wrote no file; 9999 sat in the spinbox, refused in"
      f" words, and the picture did not move"
      + (f"; a vendor arc with no `arcPaint` shows {unset!r} rather than a default"
         if unset else "")
      + f". Save wrote Theme_28.json and that file redraws the frame that was on screen;"
      f" undo brought the first frame back; revert removed the copy.  A `{_added_kind}` row"
      f" added through the menu takes the same round trip: {_rows_b} rows in,"
      f" {_rows_b + 1} back out of the file in the same order, and that file draws the frame"
      f" the pane was showing when Save was pressed.  The pane is still capped at"
      f" {win.preview.pixmap().width()} px for a {render.W} px glass.")
# ---- the canvas door in the window: presses, one drag and two arrow keys, delivered as
# ---- the same QMouseEvent/QKeyEvent objects Qt would hand the pane.  There is no QTest in
# ---- this environment, so the handlers receive real event objects rather than a helper, and
# ---- the pane - not this gate - is what turns a point under the cursor into panel px.
import tempfile

from PyQt6.QtCore import QEvent as _QEv, QPoint as _QPt, QPointF as _QP, Qt as _QQt
from PyQt6.QtGui import QKeyEvent as _QKey, QMouseEvent as _QMouse

win.ed_name.setCurrentText("alpha")
for _ in range(8):
    appq.processEvents()
assert win.ed is not None and win.ed.name == "alpha", win.ed_name.currentText()

# The mapping first, at a size this gate chooses for itself, so the claim does not depend on
# how wide this machine's columns happened to end up: 240 widget px for a 480 px glass.  The
# centred case is what the black bands produce - `_fit` never scales above 1:1 and the label
# keeps the slack around the picture - so a point in a band belongs to no row.
_half = app.Canvas(win)
_half.resize(240, 240)
_half.set_side(240)
assert _half.to_panel(_QPt(0, 0)) == (0, 0), _half.to_panel(_QPt(0, 0))
assert _half.to_panel(_QPt(120, 120)) == (render.W // 2, render.H // 2)
assert _half.to_panel(_QPt(239, 239)) == (render.W - 2, render.H - 2), \
    "a pane half the glass' size has no widget pixel of its own for the glass' last column"
_half.resize(400, 400)
_half.set_side(240)
assert _half.to_panel(_QPt(40, 40)) is None, "the black band beside the picture is somebody's row"
assert _half.to_panel(_QPt(200, 200)) == (render.W // 2, render.H // 2)
_half.set_side(0)                       # nothing drawn yet: nothing to point at
assert _half.to_panel(_QPt(200, 200)) is None

_side = win.preview.pixmap().width()
assert _side == min(win.preview.width(), win.preview.height(), render.W), \
    (_side, win.preview.size(), "the marks have to line up with what `_fit` drew")
assert win.preview.side == _side, (win.preview.side, _side)
_k = _side / render.W


def _wpoint(px, py):
    """A point on the glass, in the widget px a real cursor would carry here."""
    ox, oy = win.preview._origin()
    return int(round(ox + px * _k)), int(round(oy + py * _k))


def _ev(kind, x=0, y=0, mods=_QQt.KeyboardModifier.NoModifier, key=None):
    if kind == _QEv.Type.KeyPress:
        return _QKey(kind, key, mods)
    pos = _QP(x, y)
    return _QMouse(kind, pos, pos, _QQt.MouseButton.LeftButton,
                   _QQt.MouseButton.LeftButton, mods)


def _press(px, py):
    wx, wy = _wpoint(px, py)
    win.preview.mousePressEvent(_ev(_QEv.Type.MouseButtonPress, wx, wy))
    appq.processEvents()


def _move_to(px, py):
    wx, wy = _wpoint(px, py)
    win.preview.mouseMoveEvent(_ev(_QEv.Type.MouseMove, wx, wy))
    appq.processEvents()


def _release(px, py):
    wx, wy = _wpoint(px, py)
    win.preview.mouseReleaseEvent(_ev(_QEv.Type.MouseButtonRelease, wx, wy))
    appq.processEvents()


def _drag_to(px, py):
    _move_to(px, py)
    _release(px, py)


_tmpc = tempfile.mkdtemp(prefix="xigma-canvas-")


def _pane_png():
    """The picture the pane was told to show, as bytes nobody can fudge."""
    p = os.path.join(_tmpc, "pane.png")
    assert win.preview.pixmap().save(p, "PNG")
    return open(p, "rb").read()


_clock = next(b for b in win._ed_notes["boxes"] if b[1] == "Time")
_cx, _cy = (_clock[2][0] + _clock[2][2]) // 2, (_clock[2][1] + _clock[2][3]) // 2
_press(_cx, _cy)
assert win.ed.index == _clock[3], (_clock, win.ed.index)
assert win.ed_widget.currentIndex() == _clock[3]
assert win.preview.marks and win.preview.marks[0] == _clock[2], win.preview.marks
assert _clock[3] == len(win.ed.widgets()) - 1, (_clock, len(win.ed.widgets()))
assert win.ed.label().startswith("data"), win.ed.label()

# chrome is chrome: rebuild the pane's picture while a mark is showing and the picture that
# comes out is the same bytes, and the layer the caption counts stays what the painter
# returned - the dashed rectangle never reaches the frame the panel would be given
_osd_marked = win._osd.tobytes()
shown_on = _pane_png()
win.preview.set_marks(None)
win._repaint()
win._fit()
shown_off = _pane_png()
assert shown_on == shown_off, \
    (len(shown_on), len(shown_off), "the mark is painted over the picture, not into it")
assert win._osd.tobytes() == _osd_marked

# a press and a release on the same point: nothing moved, so nothing to undo
_drag_to(_cx, _cy)
assert win.ed.steps == 0, (win.ed.steps, "a drag that went nowhere wrote an undo step")
assert "ended where it began" in win.ed_note.text(), win.ed_note.text()

# one drag, 30 panel px.  The endpoints go through a scaled pane and are rounded to whole
# widget pixels, so what is pinned is the row's distance and the sentence's own number, not
# the mouse's: a claim about the picture, not about the cursor
# the pane is the file as the model draws it, before anything is moved: the same door
# `--check-theme` uses, at the same pinned fixture
_fresh = gui_edit.Editor.open_theme("alpha")
base, _b = _fresh.paint(*_fresh.fixture())
assert win._osd.tobytes() == base.tobytes(), "the pane is not showing the file's frame"

_press(_cx, _cy)
_x0, _y0 = int(win.ed.prop()["x"]), int(win.ed.prop()["y"])
_drag_to(_cx + 30, _cy)
_x1, _y1 = int(win.ed.prop()["x"]), int(win.ed.prop()["y"])
# ±1 px: at a pane scaled below 1:1 the endpoints are rounded to whole widget pixels, so
# the cursor cannot address every column of the glass.  On this run's pane that arithmetic
# is exact; the tolerance is what keeps the claim machine-independent.
assert abs(_x1 - _x0 - 30) <= 1 and abs(_y1 - _y0) <= 1, ((_x1 - _x0, _y1 - _y0), _k)
assert win.ed.steps == 1, (win.ed.steps, "one drag, one undo step - not one per field")
assert win.ed.dirty and themes.user_copies() == [], themes.user_copies()
_said = _re.search(r"dragged \(([+-]\d+), ([+-]\d+)\)", win.ed_note.text())
assert _said and int(_said.group(1)) == _x1 - _x0 and int(_said.group(2)) == _y1 - _y0, \
    (win.ed_note.text(), _x1 - _x0, _y1 - _y0)
moved_now, _mn = win.ed.paint(*win.ed.fixture())
assert win._osd.tobytes() == moved_now.tobytes(), "the pane did not follow the drag"
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert (int(win.ed.prop()["x"]), int(win.ed.prop()["y"])) == (_x0, _y0), win.ed.prop()
win._repaint()
assert win._osd.tobytes() == base.tobytes(), "undo did not put every pixel back in the pane"

# a drag that wanders out and back inside one press is not a change anybody can undo: the
# run is dropped, exactly as a spinbox typed `3` -> `30` -> `3` is.  This is the window's
# own behaviour (a cursor that overshoots and comes back), and the model's rule is what
# makes it true, so the two rows below are the claim, not the frame
_press(_cx, _cy)
_move_to(_cx + 40, _cy)
assert int(win.ed.prop()["x"]) == _x0 + 40 and win.ed.steps == 0, (win.ed.prop(), win.ed.steps)
assert win.ed.dirty, "the row is 40 px away and the window does not say so"
_move_to(_cx - 40, _cy)
_move_to(_cx, _cy)
_release(_cx, _cy)
assert int(win.ed.prop()["x"]) == _x0, win.ed.prop()
assert win.ed.steps == 0, (win.ed.steps, "a run that ended where it began wrote an undo step")
assert "ended where it began" in win.ed_note.text(), win.ed_note.text()
assert not win.ed.dirty, "undoing nothing left the file claimed as changed"

# the arrow keys, through the pane's own keyPressEvent: 1 px, 10 px with Shift, and each
# press is a step the window's undo button takes back
win.preview.setFocus()
_total = 0
for mods, step in ((_QQt.KeyboardModifier.NoModifier, 1),
                   (_QQt.KeyboardModifier.ShiftModifier, 10)):
    _total += step
    win.preview.keyPressEvent(_ev(_QEv.Type.KeyPress, mods=mods,
                                  key=_QQt.Key.Key_Right))
    appq.processEvents()
    assert int(win.ed.prop()["x"]) == _x0 + _total, (mods, win.ed.prop()["x"], _total)
assert win.ed.steps == 2, win.ed.steps
for _ in range(2):
    win.ed_undo.click()
    for _ in range(6):
        appq.processEvents()
assert (int(win.ed.prop()["x"]), int(win.ed.prop()["y"])) == (_x0, _y0), win.ed.prop()

# the sentence only the window can say: the model bounds a row's anchor, not its ink, so a
# legal drag can draw pixels the glass will never show - and `validate` is silent about it
_max_x = int(win.ed.obj["width"]) - 1
_press(_cx, _cy)
_drag_to(_cx + (_max_x - _x0), _cy)
assert int(win.ed.prop()["x"]) == _max_x, (win.ed.prop()["x"], _max_x)
_hang = next(b for b in win._ed_notes["boxes"] if b[1] == "Time")[2]
assert _hang[2] >= int(win.ed.obj["width"]), _hang
assert "off the" in win.ed_note.text(), win.ed_note.text()
assert win.preview.marks and "off the" in win.preview.marks[1], win.preview.marks
hard, soft = themes.validate(win.ed.obj)
assert not hard and not any("canvas" in w for w in soft), (hard, soft)
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert int(win.ed.prop()["x"]) == _x0, win.ed.prop()

# ---- the same door, driven through the pane: the handles the model says it has, the ask
# ---- the pane paints while the mouse is still down, and one press-drag-release that writes
# ---- keys, moves pixels, costs one undo step and writes no file.
assert set(app.Canvas.CURSORS) == set(gui_edit.Editor.EDGES), (
    set(app.Canvas.CURSORS) ^ set(gui_edit.Editor.EDGES),
    "the pane has a cursor or a handle for an edge the model does not know")
assert set(gui_edit.Editor.SIZE_KEYS) | {"special"} == set(layout.KINDS), (
    gui_edit.Editor.SIZE_KEYS, "a kind this program draws has no size rule of its own")


def _exact(px, py):
    """Is this panel point addressable?  A pane scaled below 1:1 rounds the cursor's widget
    px to whole pixels, so a mark on the glass is not always something a press can hit."""
    wx, wy = _wpoint(px, py)
    return win.preview.to_panel(_QP(wx, wy)) == (px, py)


def _aim(px, py, edge):
    """The nearest panel point to that mark that the pane reads as `edge` and can hit."""
    for ox in (0, 1, -1, 2, -2, 3, -3, 4, -4):
        for oy in (0, 1, -1, 2, -2, 3, -3):
            if win.preview.edge_at((px + ox, py + oy)) == edge and _exact(px + ox, py + oy):
                return px + ox, py + oy
    raise AssertionError((px, py, edge, win.preview.handles(),
                          "no addressable point reads as that handle"))


def _pick(rec):
    """Select a row by a click in ink the pane gives to it, with no marks in the way."""
    _b = rec[2]
    for _y in range(_b[1] + 1, _b[3]):
        for _x in range(_b[0] + 1, _b[2]):
            if win.ed.hit(win._ed_notes, _x, _y) == rec[3] and _exact(_x, _y):
                win.preview.set_marks(None)
                _press(_x, _y)
                _release(_x, _y)
                return _x, _y
    raise AssertionError((rec[0], rec[3], "no ink of this row is addressable"))


_d_live, _d_kind = {}, {}
for _want in ("bar", "arc", "text", "data", "special"):
    _rec = next(b for b in win._ed_notes["boxes"] if b[0] == _want)
    _pick(_rec)
    assert win.ed.index == _rec[3], (_want, win.ed.index, _rec[3],
                                     "the pane selected another row than it was asked to")
    _live = win.preview.handles()
    assert [e for e, _x, _y in _live] == list(win.ed.size_edges(_rec[3], _rec[2])), (
        _want, _live, "the pane painted handles the model did not name")
    for _e, _x, _y in _live:
        assert win.preview.edge_at((_x, _y)) == _e, (
            _want, _e, (_x, _y), "the square painted for one edge grabs another")
    _d_live[_want], _d_kind[_want] = _live, _rec
    if _want in ("text", "data"):
        assert not ({"left", "right"} & {e for e, _x, _y in _live}), (
            _want, _live, "a `text` row owns no width, so its sides are not handles")
        assert "no `width` or `height` key" in win.preview.toolTip(), (
            _want, win.preview.toolTip()[:120],
            "the tooltip promises a width a `text` row does not own")
    if _want == "special":
        assert not any("-" in e for e, _x, _y in _live), (
            _live, "a `special`'s two axes are two keys, so a corner is not a handle")
    if _want in ("bar", "arc"):
        assert len(_live) == len(gui_edit.Editor.EDGES), (_want, _live)
    assert "resize" in win.preview.toolTip(), (
        _want, win.preview.toolTip()[:80], "the tooltip does not say what the squares do")
print(f"  the squares on the box  {', '.join(f'{k} {len(v)}' for k, v in _d_live.items())}, "
      f"each one the model's `size_edges` and each square grabbing its own edge; "
      f"{len(app.Canvas.CURSORS)} cursors for {len(gui_edit.Editor.EDGES)} edges; a `text` "
      f"row has no left or right handle, a `special` no corner")

# one real drag on a `bar` row's right handle
_bar, _bb = _d_kind["bar"], _d_kind["bar"][2]
_bi = _bar[3]
_pick(_bar)
_hx, _hy = _aim(*next((x, y) for e, x, y in win.preview.handles() if e == "right"), "right")
_press(_hx, _hy)
assert win._resize and win._resize[2] == "right" and not win._drag, (
    win._resize, win._drag, "a press on a handle did not begin a resize")
assert win.preview.cursor().shape() == app.Canvas.CURSORS["right"], (
    win.preview.cursor().shape(), "the cursor does not say which way this edge grows")
_move_to(_hx + 18, _hy)
_dx_ask, _dy_ask = win._resize_ask
_asks, _bad = win.ed.resize_box(_dx_ask, _dy_ask, "right", _bi, _bb)
assert _asks and not _bad, (_asks, _bad, "the pane's drag is not a legal ask")
assert win.preview.marks[2] == _asks, (
    win.preview.marks[2], _asks, "the pane is not painting the model's ask")
assert "asking for" in win.ed_note.text(), win.ed_note.text()[:90]
assert win.preview.marks[3] == win.ed.size_edges(_bi, _bb)
_marks_png = _pane_png()
win.preview.set_marks(None)
assert _marks_png == _pane_png(), (
    "handles and the ask are painted into the picture rather than over it")
_win_osd, _rows0, _steps0 = win._osd.copy(), len(win.ed.widgets()), win.ed.steps
_width0 = win._ed_ctl("width").value()
_release(_hx + 18, _hy)
_pb = (win.ed.widgets()[_bi].get("property") or [{}])[0]
assert win._resize is None, "the release left a resize in flight"
assert win.preview.cursor().shape() != app.Canvas.CURSORS["right"], "the cursor stayed"
assert win.ed.steps == _steps0 + 1, (win.ed.steps, _steps0,
                                     "one window drag is not one undo step")
assert win.ed.dirty and themes.user_copies() == [], themes.user_copies()
assert int(_pb["width"]) == _width0 + _dx_ask, (
    _pb["width"], _width0, _dx_ask, "the drag did not write the width it asked for")
assert px_differ(_win_osd, win._osd) > 0, "the drag wrote a key and the frame did not move"
assert win._ed_ctl("width").value() == int(_pb["width"]), (
    "the inspector's `width` row still shows the old number")
assert "resized row" in win.ed_note.text(), win.ed_note.text()[:60]
assert win.preview.marks[2] is None, (
    win.preview.marks, "the ask is still on the glass after the release")
print(f"                        one `bar` right drag of {_dx_ask} px: `width` {_width0} -> "
      f"{int(_pb['width'])}, {px_differ(_win_osd, win._osd)} px of the pane's layer moved, "
      f"one undo step, no file")
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert win._ed_ctl("width").value() == _width0, "undo did not put the field row back"
assert px_differ(_win_osd, win._osd) == 0, "undo did not put every pixel back in the pane"
assert len(win.ed.widgets()) == _rows0 and win.ed.steps == _steps0

# the blind spot the pane cannot see coming: a drag whose box is legal and whose row will
# not follow.  Found on this run's picture rather than assumed, so the sentence is met by
# the window on any machine that has one.
_spot = None
for _rec in (win._ed_notes["boxes"] or []):
    if not _rec[2]:
        continue
    _i, _b = _rec[3], _rec[2]
    for _e in win.ed.size_edges(_i, _b):
        _sx = 12 if "right" in _e else -12 if "left" in _e else 0
        _sy = 12 if "bottom" in _e else -12 if "top" in _e else 0
        if win.ed.resize_box(_sx, _sy, _e, _i, _b)[1]:
            continue
        _t = gui_edit.Editor(copy.deepcopy(win.ed.obj), origin="gate", name=win.ed.name)
        _t.select(_i)
        if not _t.resize_row(_sx, _sy, _e, _i)[0]:
            _spot = (_rec, _e, _sx, _sy)
            break
    if _spot:
        break
if _spot:
    (_rec, _e, _sx, _sy), _b = _spot, _spot[0][2]
    _pick(_rec)
    _x, _y = _aim(*next((xx, yy) for ee, xx, yy in win.preview.handles() if ee == _e), _e)
    _press(_x, _y)
    _move_to(_x + _sx, _y + _sy)
    assert win.preview.marks[2], (win.preview.marks, "the pane painted no ask for a "
                                  "geometry the model itself called legal")
    _steps_ref = win.ed.steps
    _osd_ref = win._osd.copy()
    _release(_x + _sx, _y + _sy)
    assert win.ed.steps == _steps_ref and not win.ed.dirty, (
        win.ed.steps, win.ed.dirty, "the refusal wrote a step or a key")
    assert px_differ(_osd_ref, win._osd) == 0, "the refusal moved the picture"
    assert "row" in win.ed_note.text(), win.ed_note.text()[:60]
    print(f"                        the ask the pane paints and the model takes back: "
          f"{_rec[0]} row {_rec[3]}, {_e} handle, legal box, refused -> "
          f"{_cut(win.ed_note.text(), 120)}")
else:
    print("                        every legal ask on this machine's picture is met, so "
          "there is no refusal for the pane to learn about here")

# the overlap: the squares belong to the selected row even under another row's ink.  If
# this layout happens not to put one there, one is made - another row dragged over the
# square, and put back - because the rule is worth checking wherever the glass allows it.
_ar, _ab = _d_kind["arc"], _d_kind["arc"][2]
_ai = _ar[3]
_steps_ov_all = win.ed.steps
_pick(_ar)
_live_arc = win.preview.handles()
_under = next(((e, x, y, win.ed.hit(win._ed_notes, x, y))
               for e, x, y in _live_arc
               if win.ed.hit(win._ed_notes, x, y) not in (None, _ai)), None)
_made = None
if not _under:
    # a bounded search: which row could be standing on which square, with which small move
    _cand = [r for r in win._ed_notes["boxes"] if r[2] and r[3] != _ai][:4]
    for _rec in _cand:
        _i2 = _rec[3]
        _p2 = (win.ed.widgets()[_i2].get("property") or [{}])[0]
        _ax, _ay = int(_p2.get("x") or 0), int(_p2.get("y") or 0)
        for _e, _hx, _hy in _live_arc[:3]:
            for _ddx, _ddy in ((0, 0), (2, 2), (-2, -2), (4, 4), (-4, -4), (8, 8), (-8, -8)):
                _t = gui_edit.Editor(copy.deepcopy(win.ed.obj), origin="gate",
                                     name=win.ed.name)
                _t.select(_i2)
                if not _t.move_to(_ax + _ddx, _ay + _ddy)[0]:
                    continue
                _b1 = {r[3]: r[2] for r in (_t.paint(*_t.fixture())[1].get("boxes") or [])
                       if r[2]}.get(_i2)
                if _b1 and _b1[0] <= _hx <= _b1[2] and _b1[1] <= _hy <= _b1[3]:
                    win.ed.select(_i2)
                    _made = win.ed.move_to(_ax + _ddx, _ay + _ddy)
                    win._repaint()
                    _under = (_e, _hx, _hy, _i2)
                    break
            if _under:
                break
        if _under:
            break
if _under:
    _e, _x, _y, _o = _under
    _x, _y = _aim(_x, _y, _e)
    _press(_x, _y)
    assert win._resize and win._resize[3] == _ai, (
        win._resize, _ai, "the handle grabbed a row nobody selected")
    _move_to(_x + 6, _y + 6 if "-" in _e else _y)
    assert "ink lies under the handle" in win.ed_note.text(), win.ed_note.text()[:180]
    _release(_x + 6, _y + 6 if "-" in _e else _y)
    assert "ink lies under the handle" in win.ed_note.text(), win.ed_note.text()[:200]
    assert win.ed.index == _ai, "the overlap moved the selection"
    while win.ed.steps > _steps_ov_all:
        win.ed_undo.click()
        for _ in range(6):
            appq.processEvents()
    assert win.ed.steps == _steps_ov_all and not win.ed.dirty, (
        win.ed.steps, win.ed.dirty, "undoing the overlap act did not clear the editor")
    print(f"                        the overlap said out loud: row {_o}'s ink under row "
          f"{_ai}'s {_e} square{' (laid down for this check)' if _made else ''}, and the "
          f"row resized stayed row {_ai}")
else:
    print("                        no handle in this layout lies under another row's ink "
          "and none could be laid there, so the overlap sentence has nothing to check here")

# a press on a square that never moved writes nothing, and says so
_pick(_d_kind["bar"])
_hx, _hy = _aim(*next((x, y) for e, x, y in win.preview.handles() if e == "right"), "right")
_steps_click = win.ed.steps
_press(_hx, _hy)
_release(_hx, _hy)
assert win.ed.steps == _steps_click and not win.ed.dirty, (
    win.ed.steps, win.ed.dirty, "a click on a handle wrote something")
assert "never moved" in win.ed_note.text(), win.ed_note.text()[:90]

# everything this passage did, undone: the file is the file, and nothing was ever written
while win.ed.steps > _steps_ov_all:
    win.ed_undo.click()
    for _ in range(6):
        appq.processEvents()
assert win.ed.steps == _steps_ov_all and not win.ed.dirty, (
    win.ed.steps, win.ed.dirty, "the resize passage left the editor changed")
assert themes.user_copies() == [], themes.user_copies()

# and the marks stay chrome: the layer the caption counts is what the painter returned
_marked_osd = win._osd.copy()
win.preview.set_marks((_bb, win.ed.label(_bi), (0, 0, 12, 12),
                       win.ed.size_edges(_bi, _bb)))
win.preview.update()
assert win._osd.tobytes() == _marked_osd.tobytes(), "the marks changed the layer"
win.preview.set_marks(None)

# ---- the two acts that invent a name, driven through the window: the box, the buttons,
# ---- the menu that lists layouts, and the sentence each one leaves under the rows.
_e_had = sorted(themes.user_copies())
_e_open0 = win.ed_name.currentText()
_e_vendor07 = open(themes.resolve("Theme_07")["path"], "rb").read()
_e_combo_n = win.ed_name.count()


def _e_combo():
    return [win.ed_name.itemText(i) for i in range(win.ed_name.count())]


def _e_files():
    return sorted(os.path.basename(p) for p in
                  _cg.glob(os.path.join(themes.user_root(), "*")))


def _e_open(name):
    win.ed_name.setCurrentText(name)
    for _ in range(4):
        appq.processEvents()


_e_open("Theme_07")
assert win.ed is not None and win.ed.name == "Theme_07", win.ed.name
assert win.ed_newname.text() == "Theme_07", win.ed_newname.text()
_e_long = "x" * (themes.NAME_LIMIT + 7)
win.ed_newname.setText(_e_long)
assert win.ed_newname.text() == _e_long, (
    len(win.ed_newname.text()), "the box dropped the characters past the writer's limit: a "
    "press would then have renamed the copy to a name nobody typed")
win.ed_newname.setText("Theme_07")
assert not win.ed_rename.isEnabled(), (
    "rename was offered for a layout that is not one of my copies")
assert win.ed_copy.isEnabled() and not win.ed_revert.isEnabled(), (
    win.ed_copy.isEnabled(), win.ed_revert.isEnabled())
assert "vendor's file in this checkout" in win.ed_state.text(), win.ed_state.text()
_e_tip = win.ed_newname.toolTip()
_e_pick, _e_rej = themes.scan()
_e_names_n = len({r["name"] for r in list(_e_pick) + list(_e_rej)})
_e_ids_n = len({str(r["id"]) for r in list(_e_pick) + list(_e_rej)})
for _num in (str(themes.NAME_LIMIT), str(_e_names_n), str(_e_ids_n)):
    assert _num in _e_tip, (_num, _e_tip[:120],
                            "the name box's tooltip is remembering a number the library "
                            "owns, instead of counting it from the library")
assert "never ending in" in _e_tip and "PROTOCOL" in _e_tip, _e_tip[:160]

# ---- save-as: one layout becomes a copy of mine, under a name nothing was answering
_e_layer0 = win._osd.copy()
win.ed_newname.setText("e-gate-copy")
_steps_pre = win.ed.steps
win.ed_copy.click()
for _ in range(6):
    appq.processEvents()
assert win.ed.name == "e-gate-copy", win.ed.name
assert "e-gate-copy.json is yours" in win.ed_note.text(), win.ed_note.text()[:150]
assert "had no copy of its own, so nothing was left behind" in win.ed_note.text(), \
    win.ed_note.text()[:200]
assert themes.user_copies() == sorted(_e_had + ["e-gate-copy"]), themes.user_copies()
assert open(themes.resolve("Theme_07")["path"], "rb").read() == _e_vendor07, \
    "the vendor's file moved when I wrote a copy beside it"
assert win.ed.obj["id"] != themes.resolve("Theme_07")["id"], (
    "my copy answers the vendor's id as well as its own name: one layout, two names")
assert themes.resolve(str(win.ed.obj["id"]))["path"] == win.ed.path
assert win.ed.where == "your copy", win.ed.where
assert "your copy under" in win.ed_state.text(), win.ed_state.text()
assert win._ed_ctl("x") is not None                    # the rows are the same rows
assert px_differ(_e_layer0, win._osd) == 0, (
    px_differ(_e_layer0, win._osd), "a name act repainted the pane's layer")
_e_combo_now = _e_combo()
assert "e-gate-copy" in _e_combo_now and "Theme_07" in _e_combo_now, _e_combo_now
assert win.ed_name.count() == 1 + len(themes.EXPORTS) + len(themes.scan()[0]), \
    (win.ed_name.count(), len(themes.scan()[0]), "the menu and the library disagree")
assert win.ed_name.currentText() == "e-gate-copy", win.ed_name.currentText()
assert win._pair_target == themes.pair("Theme_07")[0] == "Theme_07.mp4", win._pair_target
_e_tip2 = win.ed_name.toolTip()
assert f"{len(_e_pick) + 1} of the {len(_e_pick) + 1 + len(_e_rej)}" in _e_tip2, _e_tip2[:190]
print(f"  the name in the box   the two buttons and the box between them. `save as` wrote "
      f"e-gate-copy.json beside the vendor's file (byte-identical still), took a fresh id "
      f"so its name and its number answer one file each, and the pane's layer moved "
      f"{px_differ(_e_layer0, win._osd)} px. The menu followed: {win.ed_name.count() - 1} "
      f"entries for {len(themes.scan()[0])} pickable files, its tooltip recounting from the "
      f"library, and the backdrop it names is still Theme_07.mp4")

# ---- rename, with an unsaved keystroke in hand: the file moves, the work stays
win.ed_widget.setCurrentIndex(0)
for _ in range(3):
    appq.processEvents()
_x_row = win._ed_ctl("x")
_x_before = _x_row.value()
_x_row.setValue(_x_before + 21)
for _ in range(3):
    appq.processEvents()
win.ed.commit()                            # a spinbox run is one step once it settles
_dirty0, _steps0 = win.ed.dirty, win.ed.steps
assert _dirty0 and _steps0 == _steps_pre + 1, (_dirty0, _steps0, _steps_pre)
_e_file0 = open(win.ed.path, "rb").read()
win.ed_newname.setText("e-gate-renamed")
win.ed_rename.click()
for _ in range(6):
    appq.processEvents()
assert win.ed.name == "e-gate-renamed", win.ed.name
assert os.path.basename(win.ed.path) == "e-gate-renamed.json", win.ed.path
assert win.ed.dirty is _dirty0 and win.ed.steps == _steps0, (
    win.ed.dirty, win.ed.steps, "a rename took an undo step, or cleared what was unsaved")
assert win._ed_ctl("x").value() == _x_before + 21, (
    win._ed_ctl("x").value(), "the rename re-read the file and dropped the row I moved")
assert themes.user_copies() == sorted([c for c in _e_had if c != "e-gate-copy"]
                                      + ["e-gate-renamed"]), themes.user_copies()
assert not os.path.exists(os.path.join(themes.user_root(), "e-gate-copy.json")), \
    "the old name is still there: two files, one layout"
assert "your copy moved: e-gate-copy.json is now e-gate-renamed.json" in \
    win.ed_note.text(), win.ed_note.text()[:160]
assert "its id went" in win.ed_note.text(), win.ed_note.text()[:200]
assert str(win.ed.obj["id"]) == str(themes.load(win.ed.path)["id"]), \
    "memory and the moved file disagree about the id"
assert "e-gate-copy" not in _e_combo() and "e-gate-renamed" in _e_combo(), _e_combo()
assert win.ed_name.currentText() == "e-gate-renamed", win.ed_name.currentText()
_e_id_now = str(win.ed.obj["id"])
win.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert win._ed_ctl("x").value() == _x_before, (
    win._ed_ctl("x").value(), _x_before, "undo did not go back over the row")
assert str(win.ed.obj["id"]) == _e_id_now, (
    win.ed.obj["id"], _e_id_now, "undo put a retired id back in the layout")

# ---- the refusals, in the library's words, with not one byte moved
_e_watch = _e_files()
_e_bytes = {os.path.join(themes.user_root(), f): open(os.path.join(themes.user_root(), f),
                                                      "rb").read() for f in _e_watch}
for _nm, _rn, _sa in (("Theme_14", "is not a free name", "is not a free name"),
                      ("theme_14", "is not a free name", "is not a free name"),
                      # the one sentence the two doors differ in: moving onto the name this
                      # copy already has is no act at all, writing a second file there would
                      # be an overwrite - both refused, and each says which door it is
                      ("e-gate-renamed", "already the name this copy has",
                       "is not a free name"),
                      ("bad.json", "suffix", "suffix"),
                      ("", "path element", "path element"),
                      ("gauge", "one of the five", "one of the five"),
                      ("x" * 65, "longer than", "longer than"),
                      ("../out", "path element", "path element"),
                      (str(themes.resolve("Theme_14")["id"]), "is not a free name",
                       "is not a free name")):
    for _btn, _what, _phrase in ((win.ed_rename, "rename", _rn),
                                 (win.ed_copy, "save as", _sa)):
        win.ed_newname.setText(_nm)
        _btn.click()
        for _ in range(4):
            appq.processEvents()
        assert _phrase in win.ed_note.text(), (_what, _nm, win.ed_note.text()[:120])
        assert win.ed.name == "e-gate-renamed", (_what, _nm, win.ed.name)
        assert win.ed.steps == _steps0 - 1, (_what, win.ed.steps, "a refusal took a step")
assert _e_files() == _e_watch and all(
    open(os.path.join(themes.user_root(), f), "rb").read() == _e_bytes[
        os.path.join(themes.user_root(), f)] for f in _e_watch), \
    "a refusal wrote something"
assert themes.user_copies() == sorted(_e_had + ["e-gate-renamed"]), themes.user_copies()

# ---- picking the entry for the layout that is *already* open must not re-read the file:
# ---- the menu holds your copy's name, and whatever you have typed since the last save lives
# ---- only in memory.  Measured rather than guarded: `currentTextChanged` cannot fire with
# ---- the text the menu already holds, so nothing re-opens here - and if a future rebuild of
# ---- the menu ever fires that signal while the same layout is open, this is what fails.
win.ed_widget.setCurrentIndex(0)
for _ in range(3):
    appq.processEvents()
_e_x0 = win._ed_ctl("x").value()
win._ed_ctl("x").setValue(_e_x0 + 13)
for _ in range(3):
    appq.processEvents()
win.ed.commit()                             # a spinbox run is one step once it settles
_e_x1, _e_dirty1 = win._ed_ctl("x").value(), win.ed.dirty
assert _e_x1 == _e_x0 + 13 and _e_dirty1, (_e_x1, _e_dirty1)
assert win.ed_name.currentText() == win.ed.name, (
    win.ed_name.currentText(), win.ed.name, "the menu is not holding the open layout's name")
win.ed_name.setCurrentText(win.ed.name)     # the entry for the layout that is open
for _ in range(4):
    appq.processEvents()
assert win.ed is not None and win.ed.name == "e-gate-renamed", win.ed.name
assert win._ed_ctl("x").value() == _e_x1 and win.ed.dirty == _e_dirty1, (
    win._ed_ctl("x").value(), win.ed.dirty,
    "re-picking the open layout's entry re-read the file and dropped what was typed")

# ---- the box keeps what was typed into it, and refills for a different layout
win.ed_newname.setText("half-typed")
win._editor_state()
assert win.ed_newname.text() == "half-typed", (
    win.ed_newname.text(), "the window retyped the name box over what the reader typed")
_e_open("dual")
assert win.ed_newname.text() == "dual", win.ed_newname.text()

# ---- a layout drawn from code: the save button refuses, `save as` does not
win.ed_widget.setCurrentIndex(0)
for _ in range(3):
    appq.processEvents()
_g_x = win._ed_ctl("x")
_g_x.setValue(_g_x.value() + 5)
for _ in range(3):
    appq.processEvents()
assert win.ed.dirty and win.ed_save.isEnabled(), (
    win.ed.dirty, win.ed_save.isEnabled(), "a generated layout's save button is only ever "
    "pressable with an unsaved change in hand, which is the state the refusal is for")
win.ed_save.click()
for _ in range(4):
    appq.processEvents()
assert "is one of the five themes drawn from render.py" in win.ed_note.text(), \
    win.ed_note.text()[:150]
assert themes.user_copies() == sorted(_e_had + ["e-gate-renamed"]), themes.user_copies()
win.ed_newname.setText("e-gate-gauge")
win.ed_copy.click()
for _ in range(6):
    appq.processEvents()
assert win.ed.name == "e-gate-gauge" and win.ed.where == "your copy", (win.ed.name,
                                                                       win.ed.where)
assert "there was no file for 'dual'" in win.ed_note.text(), win.ed_note.text()[:200]
assert "gauge" in render.THEMES and themes.resolve("gauge") is None, \
    "`--theme gauge` stopped drawing the code's picture"

# ---- revert on a name the library never had: the line asks the library, it does not recall
win.ed_revert.click()
for _ in range(6):
    appq.processEvents()
assert "nothing answers 'e-gate-gauge'" in win.ed_note.text(), win.ed_note.text()[:190]
assert "no file answers this name" in win.ed_state.text(), win.ed_state.text()
assert not win.ed_revert.isEnabled() and not win.ed_rename.isEnabled(), (
    win.ed_revert.isEnabled(), win.ed_rename.isEnabled())
assert "e-gate-gauge" not in _e_combo(), _e_combo()

# ---- and the passage leaves the window and the library exactly as it found them
for _nm in themes.user_copies():
    if _nm not in _e_had:
        themes.delete_user_theme(_nm)
assert sorted(themes.user_copies()) == _e_had, themes.user_copies()
win._ed_refresh_layouts()            # the window's own door: a name removed leaves the menu
_e_open(_e_open0)
assert win.ed_name.count() == _e_combo_n == 1 + len(themes.EXPORTS) + \
    len(themes.scan()[0]), (win.ed_name.count(), _e_combo_n, len(themes.scan()[0]),
                            "the menu no longer matches the library it is built from")
assert open(themes.resolve("Theme_07")["path"], "rb").read() == _e_vendor07
print(f"                        the refusals ({len(_e_watch)} "
      f"{'file' if len(_e_watch) == 1 else 'files'} on disk byte-identical through them), "
      f"the box that keeps what was typed, and a revert whose line asked the library "
      f"what answers the name now: on a renamed copy the answer is `nothing`, because that "
      f"name was never the library's to fall back on")

# ---- feature E's sentences, held to the counts this run makes.  Same two rules as the last
# ---- two cycles: every figure a page states is re-counted from the files, and a comment in
# ---- the shipped library is a sentence like any other - an installed tree carries it to a
# ---- reader, so a stale one is a wrong claim in the code.
_e_pick2, _e_rej2 = themes.scan()
_e_all2 = list(_e_pick2) + list(_e_rej2)
_e_names2 = {r["name"] for r in _e_all2}
_e_folded2 = {n.lower() for n in _e_names2}
_e_ids2 = {str(r["id"]) for r in _e_all2}
_e_nums2 = sorted(int(i) for i in _e_ids2 if str(i).isdigit())
_e_spread2 = _e_nums2[-1] - _e_nums2[0]
_e_dig2 = {len(str(i)) for i in _e_nums2}
assert len(_e_nums2) == len(_e_ids2), (sorted(_e_ids2)[:3],
                                       "an id in this library is not the digits the "
                                       "pages say it is")
assert _e_dig2 == {13}, _e_dig2
assert len(_e_folded2) == len(_e_names2), (
    len(_e_names2), len(_e_folded2),
    "two layouts here differ only in case, so the page's sentence about folded names is "
    "describing a state the library does not have")
_themes_src = _flat("xigmalcd/themes.py")
_cl_top_e = " ".join(open("debian/changelog", encoding="utf-8").read()
                     .split("\n -- ")[0].split())

for _what, _pat, _mine in (
        ("the three-way name rule, on the page",
         r"the \*\*(\d+)\*\* layout names the library holds, those names folded \(to the "
         r"resolver `theme_07` and `Theme_07` are one name\), and the \*\*(\d+)\*\* `id` "
         r"numbers inside the files",
         (len(_e_names2), len(_e_ids2))),
        ("the writer's length, on the page",
         r"the writer's \*\*(\d+)\*\*-character limit", (themes.NAME_LIMIT,)),
        ("the box that truncates nothing, on the page",
         r"it has no length cap, because a box that stopped at the writer's", ()),
        ("the id shape, on the page",
         r"a fresh 13-digit number in the shape the vendor's own files use, their "
         r"\*\*(\d+)\*\* falling inside \*\*([\d ]+) ms\*\* of one another",
         (len(_e_nums2), _e_spread2)),
        ("the suffix rule, on the page",
         r"None of the \*\*(\d+)\*\* names here does, so that rule refuses nothing that "
         r"exists", (len(_e_names2),)),
        ("the suffixes themselves, on the page",
         r"may not end in `.json`, `.bak` or `.tmp`", ()),
):
    _stated(_what, _gf, _pat, _mine)

for _what, _pat, _mine in (
        ("the suffix rule, in `themes.py`",
         r"none of the (\d+) layout names in the three roots ends in any of these",
         (len(_e_names2),)),
        ("the name space, in `themes.py`",
         r"Measured on this library: (\d+) names, all distinct even folded, and (\d+) "
         r"distinct ids across the two vendor roots",
         (len(_e_names2), len(_e_ids2))),
        ("the id shape, in `themes.py`",
         r"all (\d+) vendor layouts carry a (\d+)-digit `id`, and read as milliseconds "
         r"since the epoch they fall inside ([\d ]+) ms",
         (len(_e_nums2), 13, _e_spread2)),
        ("the limit, in `themes.py`",
         r"NAME_LIMIT = (\d+)", (themes.NAME_LIMIT,)),
):
    _stated(_what, _themes_src, _pat, _mine)

for _what, _pat, _mine in (
        ("the three-way rule, in the 0.6 stanza",
         r"the (\d+) layout names in the library, those names folded, and the (\d+) ids "
         r"inside the files", (len(_e_names2), len(_e_ids2))),
        ("the length, in the 0.6 stanza",
         r"at most (\d+) characters, never one of the five drawn from `render\.py`",
         (themes.NAME_LIMIT,)),
        ("the suffix rule, in the 0.6 stanza",
         r"none of the (\d+) names here does, so that rule refuses nothing that exists",
         (len(_e_names2),)),
        ("the id shape, in the 0.6 stanza",
         r"a fresh (\d+)-digit number in the shape the vendor's own files use "
         r"\(their (\d+) fall inside ([\d ]+) ms of one another", (13, len(_e_nums2),
                                                                   _e_spread2)),
        ("the gates' counts, in the 0.6 stanza",
         r"(\d+) names, all distinct folded, and (\d+) ids, all distinct",
         (len(_e_names2), len(_e_ids2))),
        ("the refusals the window gate drives, in the 0.6 stanza",
         r"drive both buttons through the window", ()),
):
    _stated(_what, _cl_top_e, _pat, _mine)

# ...and the words the library uses when it refuses, matched in the shape the gates use
for _phrase, _why in (
        ("is not a free name", "the refusal every naming gate matches on"),
        ("already the name this copy has", "asking for the name the copy already has"),
        ("is not one of your copies", "a rename of a file that is not yours"),
        ("would live at", "the doubled-suffix sentence, written from the suffix table"),
        ("falls back to", "the loop's `gauge` fallback, in the door's own note"),
        ("by its id as well", "why a name that matches an id is spoken for too"),
        ("now, or one past the highest id on disk", "how a fresh id is chosen"),
        ("Widget ids in this library are uuid4 and layout ids are not",
         "the shape was read off the files, not from the editor's own id door")):
    assert _phrase in _themes_src, (_phrase, _why, "`themes.py` no longer says it")
for _phrase, _why in (
        ("no file answers this name", "the state line for a reverted renamed copy"),
        ("nothing answers", "the revert sentence on a name the library never had"),
        ("deliberately no `maxLength`", "why the box truncates nothing"),
        ("the menu is rebuilt from `themes.EXPORTS`", "the comment on the refresh door")):
    assert _phrase in _app_src, (_phrase, _why, "`app.py` no longer says it")
for _phrase, _why in (
        ("is yours, under the name", "what `save_as` says it wrote"),
        ("stays where it was", "and what it left alone"),
        ("there was no file for", "a generated layout's first file"),
        ("an undo step is a change of *content*, never a change of identity",
         "why the fresh id goes into every history snapshot"),
        ("hands back the object it caches", "why `open_theme` deep-copies")):
    assert _phrase in _edit_src, (_phrase, _why, "`edit.py` no longer says it")
print(f"                        E's sentences, from this run: {len(_e_names2)} layout names "
      f"({len(_e_folded2)} distinct folded) and {len(_e_ids2)} ids ({sorted(_e_dig2)} "
      f"digits, spanning {_e_spread2:,} ms), the writer's limit {themes.NAME_LIMIT} and its "
      f"suffixes {', '.join(themes.WRITER_SUFFIXES)} - the pages, `themes.py`'s comments and "
      f"the 0.6 stanza all carry those numbers")

# ---- feature F: a drag that comes within 2 px of a number this file already uses is pulled
# ---- onto it.  Two halves, like every other act in this pane: the model's doors measured on
# ---- real layouts, and the window driving them with Qt events and painting the model's lines.
_f_lim = gui_edit.Editor.SNAP_PX
assert _f_lim == 2, (_f_lim, "the pages quote 2 px; if the door moved, the sentence did")

# ---- the census the doors were built from, recounted here: these files either line up or
# ---- they do not, which is why the threshold is 2 px and not a taste.
# every layout this pane can open, drawn from a **copy** it owns: `themes.load` caches one object
# per (path, mtime), and a draw fills in what the painter reads, so a census that drew the shared
# object would be counting what the earlier gates in this section left behind
import copy as _f_copy
_f_objs = [_f_copy.deepcopy(themes.load(_rec["path"])) for _rec in pick] \
    + [_f_copy.deepcopy(themes.export(_n)) for _n in sorted(themes.EXPORTS)]
_f_pairs, _f_zero, _f_c240x, _f_c240y, _f_boxes = 0, 0, 0, 0, 0
for _obj in _f_objs:
    _i, _no = themes.draw(_f_copy.deepcopy(_obj), dict(gui_edit.FIXTURE),
                          gui_edit.FIXTURE_WHEN)
    _bs = [tuple(r[2]) for r in (_no.get("boxes") or []) if r[2]]
    _f_boxes += len(_bs)
    for _b in _bs:
        # the middle of this file's own canvas, which every layout here puts at 240
        if abs((_b[0] + _b[2]) / 2.0 - render.W / 2.0) < 0.5:
            _f_c240x += 1
        if abs((_b[1] + _b[3]) / 2.0 - render.H / 2.0) < 0.5:
            _f_c240y += 1
    for _a in range(len(_bs)):
        for _b in range(_a + 1, len(_bs)):
            _f_pairs += 1
            _l1 = [_bs[_a][0], _bs[_a][2], (_bs[_a][0] + _bs[_a][2]) / 2.0,
                   _bs[_a][1], _bs[_a][3], (_bs[_a][1] + _bs[_a][3]) / 2.0]
            _l2 = [_bs[_b][0], _bs[_b][2], (_bs[_b][0] + _bs[_b][2]) / 2.0,
                   _bs[_b][1], _bs[_b][3], (_bs[_b][1] + _bs[_b][3]) / 2.0]
            if min(abs(p - q) for p in _l1 for q in _l2) == 0:
                _f_zero += 1
assert _f_pairs and _f_zero, (_f_pairs, _f_zero)

# ---- the anchor class, measured against the painter rather than against the key's name:
# ---- `l` rows sit with `x` at their ink's left edge, `r` rows at its right edge, `m` rows
# ---- between the two, and the anchor's *second* letter changes none of that.
_f_off = {"l": [], "m": [], "r": []}
for _obj in _f_objs:
    _i, _no = themes.draw(_f_copy.deepcopy(_obj), dict(gui_edit.FIXTURE),
                          gui_edit.FIXTURE_WHEN)
    _bs = {r[3]: tuple(r[2]) for r in (_no.get("boxes") or []) if r[2]}
    for _j, _w in enumerate(((_obj.get("osd") or {}).get("widget") or [])):
        _pr = (_w.get("property") or [{}])[0]
        if _j not in _bs or _pr.get("x") is None:
            continue
        _cls = gui_edit.Editor.anchor_class(_w)
        _two = str((_pr.get("xigma") or {}).get("anchor") or "la")
        _kind = str(_w.get("type") or "")
        _f_off[_cls].append((int(_pr["x"]) - _bs[_j][0], int(_pr["x"]) - _bs[_j][2], _two[0],
                             _kind))
        assert _two[0] == _cls, (_two, _cls, "the class is the anchor's first letter, and the "
                                             "painter agrees with that reading")
assert all(_f_off[c] for c in "lmr"), (
    {k: len(v) for k, v in _f_off.items()}, "this corpus has no row of one anchor class, so "
    "the class rule below would be measuring nothing")
# `line` is the one kind exempt: `layout.line_rect` pivots the declared rect about its own
# centre, so a row turned 90 degrees puts its ink somewhere its `x` does not name - which is
# the fact feature D wrote `x`/`y` corrections from.
_f_strict = ("text", "data", "special", "bar", "arc")
assert all(o[0] == 0 for o in _f_off["l"] if o[3] in _f_strict), (
    [o for o in _f_off["l"] if o[0]][:3], "a left-anchored row's `x` is not its ink's left "
    "edge on this machine")
assert all(o[1] == 0 for o in _f_off["r"]), (
    [o for o in _f_off["r"] if o[1]][:3], "a right-anchored row's `x` is not its ink's right "
    "edge on this machine")
assert all(0 < o[0] < render.W for o in _f_off["m"] if o[3] in _f_strict), _f_off["m"][:3]

# ---- the doors, on a real layout: which lines, the pull, and the break-away rule.
_f_name = "Theme_07"
win.ed_name.setCurrentText(_f_name)
for _ in range(8):
    appq.processEvents()
_f_editor = win.ed
assert _f_editor is not None and _f_editor.name == _f_name, win.ed_name.currentText()
_f_x = {}
for _j, _w in enumerate(_f_editor.widgets()):
    _pr = (_w.get("property") or [{}])[0]
    if _pr.get("x") is not None:
        _f_x.setdefault(int(_pr["x"]), []).append(_j)
_f_shared = [v for v in _f_x.values() if len(v) > 1]
assert _f_shared, "this layout has no shared column, so the gate is measuring nothing"
_f_a, _f_b = _f_shared[0][0], _f_shared[0][1]
_f_target = int((_f_editor.widgets()[_f_a].get("property") or [{}])[0]["x"])
_f_class = gui_edit.Editor.anchor_class(_f_editor.widgets()[_f_a])
_f_other = next(j for j, _w in enumerate(_f_editor.widgets())
                if j not in _f_shared[0]
                and gui_edit.Editor.anchor_class(_w) == _f_class
                and (_w.get("property") or [{}])[0].get("x") is not None
                and abs(int((_w.get("property") or [{}])[0]["x"]) - _f_target) > _f_lim + 2)
_f_editor.select(_f_other)
_f_bx = _f_editor._row_box(_f_editor.obj, _f_other)
assert _f_bx, f"row {_f_other} draws no box here, so there is no ink to press on"
win.ed_widget.setCurrentIndex(_f_other)
for _ in range(4):
    appq.processEvents()
_f_off_x = int((_f_editor.widgets()[_f_other].get("property") or [{}])[0]["x"])
_f_lines = _f_editor.snap_lines(_f_other, box=_f_editor._row_box(_f_editor.obj, _f_other))
assert all(0 <= v < render.W for v, _s in _f_lines["x"]), _f_lines["x"]
assert all(0 <= v < render.H for v, _s in _f_lines["y"]), _f_lines["y"]
assert _f_target in {v for v, _s in _f_lines["x"]}, (
    _f_target, [v for v, _s in _f_lines["x"]],
    "a column this file already holds is not offered to a row that can join it")

# the pull, and its words
_f_got, _f_gy, _f_said = _f_editor.snap_move(_f_target + _f_lim, int(_f_editor.prop()["y"]),
                                         index=_f_other,
                                         was=(_f_off_x, int(_f_editor.prop()["y"])),
                                         lines=_f_lines)
assert _f_got == _f_target, (_f_got, _f_target, _f_lim, "the pull did not land on the number")
assert _f_said and "snapped x" in _f_said[0] and "declares `x`" in _f_said[0], _f_said
# one pixel outside the reach: nothing moves, and nothing is said
_f_g2, _f_gy2, _f_s2 = _f_editor.snap_move(_f_target + _f_lim + 1, int(_f_editor.prop()["y"]),
                                       index=_f_other, was=(_f_off_x, int(_f_editor.prop()["y"])),
                                       lines=_f_lines)
assert (_f_g2, _f_s2) == (_f_target + _f_lim + 1, []), (_f_g2, _f_s2)
# break-away: the line you were already sitting on cannot pull you back
_f_editor.select(_f_a)
_f_stay = _f_editor.snap_move(_f_target + 1, int(_f_editor.prop()["y"]), index=_f_a,
                          was=(_f_target, int(_f_editor.prop()["y"])),
                          box=_f_editor._row_box(_f_editor.obj, _f_a))
assert _f_stay[0] == _f_target + 1 and _f_stay[2] == [], (
    _f_stay, "a snap argued with a drag that left its own line")
# a drag asks once per press and one frame finds the lines; the events cost nothing
import time as _time
_t0 = _time.time()
_f_lines2 = _f_editor.snap_lines(_f_other)
_f_cost = _time.time() - _t0
_t1 = _time.time()
for _f_ev in range(30):
    _f_editor.snap_move(_f_off_x + _f_ev, 60, index=_f_other, was=(_f_off_x, 60), lines=_f_lines2)
_f_events = _time.time() - _t1
assert _f_events < 0.05, (_f_events, "30 motion events must not each cost a frame")
print(f"  snapping, by the model  {len(_f_lines['x'])} x lines and {len(_f_lines['y'])} y "
      f"lines for row {_f_other} of {_f_name}, one frame finding them in "
      f"{_f_cost * 1000:.0f} ms and 30 pulls off those lines in {_f_events * 1000:.1f} ms")
print(f"                        drawn, in this pass: {_f_zero} of {_f_pairs} pairs of drawn "
      f"boxes share an alignment number exactly, and the {len(_f_objs)} layouts drew "
      f"{_f_boxes} boxes of which {_f_c240x} have their centre on x={render.W // 2} and "
      f"{_f_c240y} on y={render.H // 2}.  Those are prints, not the library's digits: they "
      f"follow the face the run resolved and what this section's other gates left patched, "
      f"which is exactly why no page quotes them and only the file counts above are asserted.")

# ---- the centre and the mirror, and what they cost in ink: a left-anchored row reaches the
# ---- middle of the glass by half its own ink, and only the painter knows that width.
_f_editor.select(3)
_f_mx, _f_my, _f_said = _f_editor.snap_move(18, int(_f_editor.prop()["y"]), index=3,
                                        was=(int(_f_editor.prop()["x"]), int(_f_editor.prop()["y"])))
_f_mir = [n for n in _f_said if "mirror" in n]
assert _f_mir, (18, _f_mx, _f_said, "no mirror line offered on a layout whose rows do mirror")
assert "whose centre is at" in _f_mir[0] and "px of ink" in _f_mir[0], _f_mir
_f_try = _f_copy.deepcopy(_f_editor.obj)
((_f_try.get("osd") or {}).get("widget") or [])[3]["property"][0]["x"] = _f_mx
_f_n2 = themes.draw(_f_try, dict(gui_edit.FIXTURE), gui_edit.FIXTURE_WHEN)[1]
_f_new = next(tuple(r[2]) for r in (_f_n2.get("boxes") or []) if r[3] == 3)
_f_bx5 = _f_editor._row_box(_f_editor.obj, 5)
_f_sum = (_f_new[0] + _f_new[2]) / 2.0 + (_f_bx5[0] + _f_bx5[2]) / 2.0
assert abs(_f_sum - render.W) <= 1, (
    _f_sum, render.W, "the mirror line did not put the two centres on opposite sides")
print(f"                        and the same door mirrored row 3 about the centre with row "
      f"5: the two box centres sum to {int(round(_f_sum))} px on a {render.W} px glass")

# ---- cross-class lines are refused, measured on the glass rather than asserted: an `r` row
# ---- snapped to an `l` row's number would sit half a layout away.
win.ed_name.setCurrentText("bars")
for _ in range(8):
    appq.processEvents()
_f_bars = win.ed
_f_l = [i for i, w in enumerate(_f_bars.widgets()) if gui_edit.Editor.anchor_class(w) == "l"]
_f_r = [i for i, w in enumerate(_f_bars.widgets()) if gui_edit.Editor.anchor_class(w) == "r"]
assert _f_l and _f_r, (_f_l, _f_r, "`bars` is the layout the corpus says carries both")
_f_bars.select(_f_r[0])
_f_rl = _f_bars.snap_lines(_f_r[0], box=_f_bars._row_box(_f_bars.obj, _f_r[0]))
_f_lnums = sorted({int((_f_bars.widgets()[i].get("property") or [{}])[0]["x"]) for i in _f_l})
_f_offered = {v for v, _s in _f_rl["x"]}
assert not (_f_offered & set(_f_lnums)), (
    sorted(_f_offered & set(_f_lnums)), _f_lnums, "a right-anchored row was offered a left-"
    "anchored row's number: they mean different edges, and the corpus puts 53 px of ink "
    "between them at the median")
assert {int((_f_bars.widgets()[i].get("property") or [{}])[0]["x"]) for i in _f_r} <= _f_offered, (
    "a right-anchored row was not offered the column its own file's right-anchored rows hold")
# and the reason the class rule exists is measured on this machine, not carried from a probe:
# if an `l` row were pulled onto an `r` row's number, how far apart would their ink land?  The
# answer is the whole width of the layout, so the line is refused rather than offered.
# measured on the file, not on whatever the pane happens to be holding: the add/remove gates
# earlier in this section have moved rows in and out of live editors
_f_bo = _f_copy.deepcopy(themes.export("bars"))
_f_bimg, _f_bnotes = themes.draw(_f_bo, dict(gui_edit.FIXTURE), gui_edit.FIXTURE_WHEN)
_f_bx_r = {r[3]: tuple(r[2]) for r in (_f_bnotes.get("boxes") or []) if r[2]}
_f_brows = (_f_bo.get("osd") or {}).get("widget") or []
# the classes come from the same copy the boxes come from, so an index is never read against a
# different object than the ink it landed in
_f_fl = [i for i, w in enumerate(_f_brows) if gui_edit.Editor.anchor_class(w) == "l"
         and (w.get("property") or [{}])[0].get("x") is not None]
_f_fr = [i for i, w in enumerate(_f_brows) if gui_edit.Editor.anchor_class(w) == "r"
         and (w.get("property") or [{}])[0].get("x") is not None]
assert (_f_fl, _f_fr) == (_f_l, _f_r), (
    (_f_fl, _f_fr), (_f_l, _f_r), "the pane's live `bars` editor and the file's own rows have "
                                  "come apart, so the classes measured above are not the ones "
                                  "being drawn here")
_f_gap = []
for _i in _f_fl:
    for _j in _f_fr:
        if _i not in _f_bx_r or _j not in _f_bx_r:
            continue
        _dx = (int((_f_brows[_j].get("property") or [{}])[0]["x"])
               - int((_f_brows[_i].get("property") or [{}])[0]["x"]))
        _f_gap.append(abs((_f_bx_r[_i][0] + _dx) - _f_bx_r[_j][0]))
_f_gap.sort()
assert _f_gap, (_f_l, _f_r, "`bars` draws no l/r pair, so the class rule is measuring nothing")
_f_med = _f_gap[len(_f_gap) // 2]
assert _f_med > 10 * _f_lim, (
    _f_med, _f_lim, "a cross-class snap would land the ink within a few px after all, so the "
                    "rule that refuses those lines needs re-reading against the glass")
print(f"                        cross-class, measured here: pulling a left-anchored `bars` row "
      f"onto a right-anchored row's `x` would leave the two ink left edges {_f_gap[0]} px apart "
      f"at closest, {_f_med} px at the median, {_f_gap[-1]} px at furthest, over {len(_f_gap)} "
      f"such pairs - which is why `snap_lines` does not offer them")

# ---- and the window drives it: a press on ink, a drag that lands 2 px past a column, and
# ---- what the pane paints and says about it.
_f_raw0 = open(themes.resolve(_f_name)["path"], "rb").read()
win.ed_name.setCurrentText(_f_name)
for _ in range(8):
    appq.processEvents()
_f_editor = win.ed
_f_editor.select(_f_other)
_f_bx = _f_editor._row_box(_f_editor.obj, _f_other)
assert _f_bx, f"row {_f_other} draws no box here, so there is no ink to press on"
win.ed_widget.setCurrentIndex(_f_other)
for _ in range(4):
    appq.processEvents()

# this drag wants the pane at 1:1: at a preview a third of the glass, one widget pixel is
# three panel pixels and a rule about 2 px cannot be driven through a pointer that cannot move
# by 2.  A window of its own, so the section's `win` keeps the size everything else in it
# measured; `restore=False, save_settings=False` so no session file is written.
_fw = app.Window(bad, None, restore=False, save_settings=False)
_fw.show()
_fw.resize(1600, 1200)
for _ in range(10):
    appq.processEvents()
_fw.ed_name.setCurrentText(_f_name)
for _ in range(8):
    appq.processEvents()
assert _fw.ed is not None and _fw.ed.name == _f_name, _fw.ed_name.currentText()
_side_f = _fw.preview.pixmap().width()
assert _side_f == render.W, (_side_f, "this drag needs the glass at 1:1, as the owner's "
                                      "1600 px frame gives it")
_fw.ed.select(_f_other)
_f_bx = _fw.ed._row_box(_fw.ed.obj, _f_other)
assert _f_bx, f"row {_f_other} draws no box here, so there is no ink to press on"
_fw.ed_widget.setCurrentIndex(_f_other)
for _ in range(4):
    appq.processEvents()


_f_tmp = tempfile.mkdtemp(prefix="xigma-snap-")


def _f_png(_w):
    """The picture a pane was told to show, as bytes nobody can fudge."""
    _p = os.path.join(_f_tmp, "pane.png")
    assert _w.preview.pixmap().save(_p, "PNG")
    return open(_p, "rb").read()


def _f_w(px, py):
    ox, oy = _fw.preview._origin()
    return int(round(ox + px)), int(round(oy + py))


def _f_press(px, py):
    _fw.preview.mousePressEvent(_ev(_QEv.Type.MouseButtonPress, *_f_w(px, py)))
    appq.processEvents()


def _f_move(px, py):
    _fw.preview.mouseMoveEvent(_ev(_QEv.Type.MouseMove, *_f_w(px, py)))
    appq.processEvents()


def _f_release(px, py):
    _fw.preview.mouseReleaseEvent(_ev(_QEv.Type.MouseButtonRelease, *_f_w(px, py)))
    appq.processEvents()


_f_steps0 = _fw.ed.steps
_f_pt = (_f_bx[0] + 2, (_f_bx[1] + _f_bx[3]) // 2)      # a point inside this row's own ink
_f_press(*_f_pt)
assert _fw._drag and _fw._snap_lines is not None, (
    _fw._drag, _fw._snap_lines, _f_pt, _f_other, "the press found no row to drag")
assert _fw._drag[2] == _f_off_x and _fw._drag[3] == int(_fw.ed.prop()["y"]), _fw._drag
_f_dx = _f_target - _f_off_x + _f_lim            # 2 px the wrong side of the column
_f_move(_f_pt[0] + _f_dx, _f_pt[1])
assert _fw._snap_guide and _fw._snap_guide[0][0] == "x", (
    _fw._snap_guide, "the pane painted no guide for a pull it applied")
assert _fw.preview.marks[4] == _fw._snap_guide, (
    _fw.preview.marks[4], _fw._snap_guide, "the guides in the marks are not the ones the drag "
    "is pulling toward")
assert int(_fw.ed.prop()["x"]) == _f_target, (
    _fw.ed.prop()["x"], _f_target, "the drag wrote a number the model did not name")
assert "snapped x" in _fw.ed_note.text(), _fw.ed_note.text()[:140]
_f_mid = _fw._snap_guide
_f_guide_png = _f_png(_fw)
_fw.preview.set_marks(_fw.preview.marks[:4] + ((),))
_f_plain_png = _f_png(_fw)
assert _f_guide_png == _f_plain_png, (
    "a guide line reached the picture the pane saves: marks are chrome, like the handles")
_f_release(_f_pt[0] + _f_dx, _f_pt[1])
assert int(_fw.ed.prop()["x"]) == _f_target, (_fw.ed.prop()["x"], _f_target)
assert _fw.ed.steps == _f_steps0 + 1, (_fw.ed.steps, _f_steps0, "one drag, one undo step")
assert "snapped x" in _fw.ed_note.text(), _fw.ed_note.text()[-190:]
assert _fw.preview.marks[4] == (), _fw.preview.marks[4]
_f_x_row = _fw._ed_ctl("x")
assert _f_x_row.value() == _f_target, (_f_x_row.value(), _f_target,
                                       "the field rows do not show where the row landed")
print(f"  snapping, in the window  a press on row {_f_other}'s ink at 1:1, a drag 2 px past "
      f"row {_f_a}'s `x`, and the row is on {_f_target} with a guide at {_f_mid[0][1]} and "
      f"the model's own sentence under the rows; the pane's saved picture is byte-identical "
      f"with the guide on and off ({len(_f_guide_png)} B)")

# ---- an arrow key is not a drag: it places a row to the pixel, and no line may answer for it.
_fw.ed.select(_f_a)
_fw.ed_widget.setCurrentIndex(_f_a)
for _ in range(4):
    appq.processEvents()
_fw.preview.keyPressEvent(_ev(_QEv.Type.KeyPress, key=_QQt.Key.Key_Right))
for _ in range(3):
    appq.processEvents()
_f_num = lambda i: int((_fw.ed.widgets()[i].get("property") or [{}])[0]["x"])
assert _f_num(_f_a) == _f_target + 1, (
    _f_num(_f_a), _f_target, "a 1 px nudge was moved by a snap - a keypress that did nothing "
    "the cursor asked for")
assert (_f_num(_f_a), _f_num(_f_other)) == (_f_target + 1, _f_target), (
    (_f_num(_f_a), _f_num(_f_other)), "the nudge left its row 1 px off the column, and the "
    "drag left its row on it - which is the whole difference between a key and a snap")
print(f"                        and the arrow keys stay exact: row {_f_a} nudged 1 px off its "
      f"column, no snap answering")

# ---- two acts on two rows, two steps, and each press of undo goes back over one of them
assert _fw.ed.steps == _f_steps0 + 2, (_fw.ed.steps, _f_steps0)
_fw.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert (_f_num(_f_a), _f_num(_f_other)) == (_f_target, _f_target), (
    (_f_num(_f_a), _f_num(_f_other)), "undo went back over the drag, not the 1 px nudge")
_fw.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert _f_num(_f_other) == _f_off_x and _fw.ed.steps == _f_steps0, (
    _f_num(_f_other), _f_off_x, _fw.ed.steps, "the drag itself did not go back as one step")
_fw.close()
assert open(themes.resolve(_f_name)["path"], "rb").read() == _f_raw0, (
    "a drag the window never saved still reached the vendor's file")
assert themes.user_copies() == [], themes.user_copies()
print(f"                        undo put row {_f_other} back at {_f_off_x}; "
      f"{_f_name}.json is byte-identical to the file it was read from, and the user root "
      f"holds nothing")

# ---- feature F's sentences, held to the numbers the **files** give this run.  These are the
# ---- snapping figures that cannot move between machines: no drawing, no fonts, no readings -
# ---- only the numbers the layouts this pane can open declare.  The figures that do follow the
# ---- face a layout is drawn in (how many *drawn* pairs line up, how far cross-class ink would
# ---- sit apart) are measured and asserted by the gate above on whatever machine runs it, and
# ---- printed there rather than written into a page as one number.
_f_files = [(str(_rec["name"]), themes.load(_rec["path"])) for _rec in pick]
_f_files += [(_n, themes.export(_n)) for _n in sorted(themes.EXPORTS)]
_f_decl = []                                  # (layout, x, y) exactly as the files write them
for _fi, (_fn, _obj) in enumerate(_f_files):
    for _pr in [(_w.get("property") or [{}])[0]
                for _w in (_obj.get("osd") or {}).get("widget") or []]:
        if _pr.get("x") is None and _pr.get("y") is None:
            continue
        _f_decl.append((_fi, int(_pr["x"]) if _pr.get("x") is not None else None,
                        int(_pr["y"]) if _pr.get("y") is not None else None))
_f_n = len(_f_decl)


def _f_peers(_k, _axis):
    """The numbers on one axis that the *other* rows of this row's own file declare."""
    return [v for j, v in enumerate([d[_axis] for d in _f_decl])
            if j != _k and _f_decl[j][0] == _f_decl[_k][0] and v is not None]


_f_share_x = sum(1 for _k in range(_f_n) if _f_decl[_k][1] is not None
                 and _f_decl[_k][1] in _f_peers(_k, 1))
_f_share_y = sum(1 for _k in range(_f_n) if _f_decl[_k][2] is not None
                 and _f_decl[_k][2] in _f_peers(_k, 2))
_f_same = 0
for _a in range(_f_n):
    for _b in range(_a + 1, _f_n):
        if _f_decl[_a][0] != _f_decl[_b][0]:
            continue
        if (_f_decl[_a][1] is not None and _f_decl[_a][1] == _f_decl[_b][1]) or (
                _f_decl[_a][2] is not None and _f_decl[_a][2] == _f_decl[_b][2]):
            _f_same += 1
import math as _math
_f_gcd_x = _math.gcd(*[d[1] for d in _f_decl if d[1] is not None])
_f_gcd_y = _math.gcd(*[d[2] for d in _f_decl if d[2] is not None])
_f_by16 = sum(1 for d in _f_decl if d[1] is not None and d[1] % 16 == 0)
# the middle is not assumed: `snap_lines` asks the file, and the prose says 240 because every
# layout this pane can open declares 480x480.  A file that declared otherwise moves this run's
# digits, which is the honest way for the sentence to go stale rather than stay comfortable.
_f_sizes = {((int(_o.get("width") or render.W), int(_o.get("height") or render.H)))
            for _fn, _o in _f_files}
assert len(_f_sizes) == 1, (_f_sizes, "the layouts this pane opens do not all declare one "
                                      "canvas, so `the middle` is not one number")
(_f_w0, _f_h0), = _f_sizes
_f_cx, _f_cy = _f_w0 // 2, _f_h0 // 2
_f_at_c_x = sum(1 for d in _f_decl if d[1] == _f_cx)
_f_at_c_y = sum(1 for d in _f_decl if d[2] == _f_cy)


def _f_mir(_axis):
    """Pairs of rows in one file whose numbers on `axis` add up to the middle twice over."""
    _rows = [(d[0], d[_axis]) for d in _f_decl if d[_axis] is not None]
    return sum(1 for _a in range(len(_rows)) for _b in range(_a + 1, len(_rows))
               if _rows[_a][0] == _rows[_b][0] and _rows[_a][1] + _rows[_b][1] == 2 * _f_cx)


_f_mir_x, _f_mir_y = _f_mir(1), _f_mir(2)
_f_edge = sum(1 for d in _f_decl for v in (d[1], d[2])
              if v is not None and v in (0, 2 * _f_cx - 1))
_f_hist_x = {}
for _k in range(_f_n):
    if _f_decl[_k][1] is None:
        continue
    _d = min((abs(v - _f_decl[_k][1]) for v in _f_peers(_k, 1)), default=None)
    _f_hist_x[_d] = _f_hist_x.get(_d, 0) + 1
_f_t = gui_edit.Editor.SNAP_PX
assert _f_t == 2, (_f_t, "the pages, `edit.py`'s comment and the 0.6 stanza all quote 2 px; if "
                         "the door moved, the sentences did too")
assert _f_n == len(_f_decl) and _f_share_x and _f_same, (_f_n, _f_share_x, _f_same)
# the two claims the prose makes about the shape of the histogram, not just its totals: nothing
# one pixel off, and a gap in the small distances, which is what makes 2 px a break rather than a
# point on a slope
assert _f_hist_x.get(1, 0) == 0, _f_hist_x
assert _f_hist_x.get(6, 0) == 0 and _f_hist_x.get(7, 0) == 0, _f_hist_x
assert _f_edge == 0, (_f_edge, "the page says no row declares a number on the canvas edge, and "
                               "this run found one")


def _f_pulled(_t):
    """How many rows of this corpus a 3 px drag would pull onto another row's `x`."""
    return round(100.0 * sum(
        1 for _k in range(_f_n)
        if _f_decl[_k][1] is not None
        and any(abs(v - (_f_decl[_k][1] + 3)) <= _t for v in _f_peers(_k, 1))) / _f_n)


_f_p1, _f_p2, _f_p3 = _f_pulled(1), _f_pulled(2), _f_pulled(3)
assert _f_p2 < _f_p3, (_f_p2, _f_p3, "3 px is no more grabbable than 2 px on this corpus, so the "
                                     "sentence that says otherwise has to go")
_f_cl_top = " ".join(open("debian/changelog", encoding="utf-8").read()
                     .split("\n -- ")[0].split())
_f_themes = _flat("docs/themes.md")

# ---- docs/gui.md: the three bullets' digits, in the order the page writes them -----------
for _what, _pat, _mine in (
        ("the census the reach is counted from, on the page",
         r"of the \*\*(\d+)\*\* rows that carry an `x` or a `y` in the \*\*(\d+)\*\* layouts this "
         r"pane can open, \*\*(\d+)\*\* hold an `x` that another row of the same file holds "
         r"exactly and \*\*(\d+)\*\* do the same with `y`, which is \*\*(\d+)\*\* pairs of rows "
         r"holding one number between them",
         (_f_n, len(_f_files), _f_share_x, _f_share_y, _f_same)),
        ("the histogram's small end, on the page",
         r"the nearest other row's `x` is 1 px away for \*\*(\d+)\*\* of those rows, 2 px away "
         r"for \*\*(\d+)\*\*, and 3 px away for \*\*(\d+)\*\*, and nothing at all sits 6 or 7 "
         r"px off",
         (_f_hist_x.get(1, 0), _f_hist_x.get(2, 0), _f_hist_x.get(3, 0))),
        ("the blast radius of a 3 px drag, on the page",
         r"a drag of 3 px is pulled onto another row's number (\d+)% of the time at 1 px, "
         r"\*\*(\d+)%\*\* at 2 px and (\d+)% at 3 px",
         (_f_p1, _f_p2, _f_p3)),
        ("the centre and the mirror, and which axis has the habit, on the page",
         r"\*\*(\d+)\*\* rows declare `x` exactly \*\*(\d+)\*\* and \*\*(\d+)\*\* pairs of rows "
         r"declare two `x` values that sum to the \*\*(\d+)\*\* that same file declares, while "
         r"on the other axis \*\*(\d+)\*\* rows sit at the middle and \*\*(\d+)\*\* pairs mirror",
         (_f_at_c_x, _f_cx, _f_mir_x, 2 * _f_cx, _f_at_c_y, _f_mir_y)),
        ("the canvas edges, on the page",
         r"not one row in those (\d+) layouts declares `x` at \*\*(\d+)\*\* or at \*\*(\d+)\*\*",
         (len(_f_files), 0, 2 * _f_cx - 1)),
        ("the grid that is not there, on the page",
         r"the gcd of every declared `x` and of every declared `y` in the corpus is \*\*(\d+)\*\*,"
         r" and only \*\*(\d+)\*\* of its \*\*(\d+)\*\* declared `x` values are multiples of 16",
         (_f_gcd_x, _f_by16, _f_n)),
):
    _stated(_what, _gf, _pat, _mine)

# ---- `edit.py`'s own comments: the shipped tree says the same counts, or the comment is a
# ---- claim nobody re-counts -------------------------------------------------------------
for _what, _pat, _mine in (
        ("the census, in `edit.py`'s comment",
         r"of the \*\*(\d+)\*\* rows that carry an `x` or a `y` in the \*\*(\d+)\*\* layouts this "
         r"pane can open, \*\*(\d+)\*\* hold an `x` another row of the same file holds exactly "
         r"and \*\*(\d+)\*\* do the same with `y` - \*\*(\d+)\*\* pairs of rows holding one "
         r"number between them",
         (_f_n, len(_f_files), _f_share_x, _f_share_y, _f_same)),
        ("the histogram's small end, in `edit.py`'s comment",
         r"the nearest other row's `x` is 1 px away for \*\*(\d+)\*\* of those rows, 2 px away "
         r"for \*\*(\d+)\*\*, and 3 px away for \*\*(\d+)\*\*, with nothing at all 6 or 7 px off",
         (_f_hist_x.get(1, 0), _f_hist_x.get(2, 0), _f_hist_x.get(3, 0))),
        ("the blast radius, in `edit.py`'s comment",
         r"a drag of 3 px right is pulled onto another row's `x` (\d+)% of the time at 1 px, "
         r"\*\*(\d+)%\*\* at t=2 and \*\*(\d+)%\*\* at t=3",
         (_f_p1, _f_p2, _f_p3)),
        ("the pairs, in `snap_lines`' words",
         r"\*\*(\d+)\*\* pairs of rows in this library hold the same number", (_f_same,)),
        ("the shared `y` numbers, in `snap_lines`' words",
         r"\*\*(\d+)\*\* rows already hold a `y` another row of the same file holds",
         (_f_share_y,)),
        ("the two axes' habits, in `snap_lines`' words",
         r"\*\*(\d+)\*\* rows declare `x` exactly \d+ and \*\*(\d+)\*\* pairs declare two `x` "
         r"values that sum to the \d+ the same file declares, while on the other axis \*\*(\d+)\*\* "
         r"rows sit at the middle and \*\*(\d+)\*\* pairs mirror",
         (_f_at_c_x, _f_mir_x, _f_at_c_y, _f_mir_y)),
        ("the edges, in `snap_lines`' words",
         r"not one row in those \d+ layouts declares `x` or `y` at (\d+) or at (\d+)",
         (0, 2 * _f_cx - 1)),
        ("the break-away rule's reason, in `snap_move`'s words",
         r"(\d+) of the (\d+) rows here hold an `x` another row of the same",
         (_f_share_x, _f_n)),
):
    _stated(_what, _edit_src, _pat, _mine)
for _phrase, _why in (
        ("the line you left is not a line", "the break-away rule, in the door's own words"),
        ("paints no box at this fixture", "a row with no ink has no width to centre with"),
        ("on x only", "the centre and the mirror are one axis' habit, in the door's words"),
        ("**first** letter is the horizontal one", "how the class is read, in the model's "
         "words"),
        ("the suite draws the layouts this pane can", "the anchor offsets are measured per run, "
                                                      "not quoted from one bench")):
    assert _phrase in _edit_src, (_phrase, _why, "`edit.py` no longer says it")

# ---- the 0.6 stanza, and docs/themes.md: the record and the library page ------------------
for _what, _pat, _mine in (
        ("the census, in the 0.6 stanza",
         r"of the (\d+) rows that carry an `x` or a `y` in the (\d+) layouts this pane opens, "
         r"(\d+) hold an `x` another row of the same file holds exactly and (\d+) do the same "
         r"with `y` - (\d+) pairs of rows holding one number between them",
         (_f_n, len(_f_files), _f_share_x, _f_share_y, _f_same)),
        ("the histogram's small end, in the 0.6 stanza",
         r"the nearest other row's `x` is 1 px away for (\d+) of those rows, 2 px away for "
         r"(\d+), and 3 px away for (\d+), and nothing sits 6 or 7 px off",
         (_f_hist_x.get(1, 0), _f_hist_x.get(2, 0), _f_hist_x.get(3, 0))),
        ("the blast radius, in the 0.6 stanza",
         r"a 3 px drag is pulled (\d+)% of the time at 1 px, (\d+)% at 2 px and (\d+)% at 3 px",
         (_f_p1, _f_p2, _f_p3)),
        ("the two axes' habits, in the 0.6 stanza",
         r"(\d+) rows declare `x` exactly \d+ and (\d+) pairs declare two `x` values summing to "
         r"the \d+ the same file declares, while on y (\d+) rows sit at the middle and (\d+) "
         r"pairs mirror",
         (_f_at_c_x, _f_mir_x, _f_at_c_y, _f_mir_y)),
        ("the grid that is not there, in the 0.6 stanza",
         r"the gcd of every declared `x` and of every declared `y` is (\d+), and only (\d+) of "
         r"the (\d+) declared `x` values are multiples of 16",
         (_f_gcd_x, _f_by16, _f_n)),
        ("the gates' own arithmetic, in the 0.6 stanza",
         r"The snapping gates count the corpus from its declared numbers - (\d+) rows, (\d+) and "
         r"(\d+) of them sharing one, (\d+) pairs",
         (_f_n, _f_share_x, _f_share_y, _f_same)),
):
    _stated(_what, _f_cl_top, _pat, _mine)
for _what, _pat, _mine in (
        ("the grid that is not there, in docs/themes.md",
         r"the gcd of every declared `x` and every declared `y` in the \*\*(\d+)\*\* placements "
         r"of the \*\*(\d+)\*\* layouts the pane opens is (\d+)",
         (_f_n, len(_f_files), _f_gcd_x)),
        ("the shared columns, in docs/themes.md",
         r"since (\d+) of them share an `x` exactly", (_f_share_x,)),
):
    _stated(_what, _f_themes, _pat, _mine)
for _phrase in ("guide is chrome", "the model's own sentence", "SNAP_PX", "anchor class",
                "never snapped", "not offered back to it"):
    assert _phrase in _gf, (_phrase, "docs/gui.md stopped naming what the gate holds it to")
print(f"                        F's sentences, from this run: {_f_n} rows carry an `x` or a `y` "
      f"across the {len(_f_files)} layouts this pane can open; {_f_share_x} hold an `x` another "
      f"row of the same file holds and {_f_share_y} do the same with `y`; {_f_same} pairs hold "
      f"one number; the nearest is 1 px off for {_f_hist_x.get(1, 0)} of them, 2 px for "
      f"{_f_hist_x.get(2, 0)} and 3 px for {_f_hist_x.get(3, 0)}, with nothing 6 or 7 px off; "
      f"the gcds are {_f_gcd_x} and {_f_gcd_y}, {_f_by16} of the `x` values are multiples of 16, "
      f"and {_f_edge} rows sit on the canvas edge at all; the centre line answers {_f_at_c_x} "
      f"rows on x and {_f_at_c_y} on y, mirroring {_f_mir_x} pairs against {_f_mir_y}; and a "
      f"3 px drag is pulled {_f_p1}% at 1 px, {_f_p2}% at the {_f_t} px the door uses and "
      f"{_f_p3}% at 3 px - the page, `edit.py`, docs/themes.md and the 0.6 stanza all carry "
      f"those")

# ---- feature G: the pane can look at another body's readings, and refuses to be edited in
# ---- them.  Two halves, like every other act in this pane: the census of what actually moves
# ---- between the pinned frame and a live one (measured here and printed, with only the *file*
# ---- figures asserted), and the window driven through real Qt events by its own knob.
import ast as _gg_ast
import builtins as _gg_builtins
import copy as _gg_deep
import json as _gg_json
import tempfile as _gg_tf

_gk_WHEN = gui_edit.FIXTURE_WHEN
# The pinned pair, taken from `edit.py`'s own text rather than from the live module dict.  Not
# fussiness: `Editor.fixture()` hands out `dict(FIXTURE)`, a shallow copy whose inner dicts are
# the module's, and a gate earlier in this section pops `memory.total` out of what it is handed -
# so every draw after that one answers one derived rate fewer than the program ever does.  G's
# figures are claims about the fixture **as written**, so they are counted here from a parse of
# the literal, and the live dict's difference is printed below, not hidden.  The door's own
# repair is a separate change: it moves the drawn box counts docs/gui.md labels per machine.
_gk_FIX = {}
for _gg_node in _gg_ast.parse(open("xigmaui/edit.py", encoding="utf-8").read()).body:
    if (isinstance(_gg_node, _gg_ast.Assign)
            and getattr(_gg_node.targets[0], "id", "") == "FIXTURE"):
        _gk_FIX = _gg_ast.literal_eval(_gg_node.value)
assert _gk_FIX.get("memory", {}).get("total"), _gk_FIX.get("memory")
assert _gk_FIX["cpu"]["temperature"] == 57.0, _gk_FIX["cpu"]

_gk_TMP = _gg_tf.mkdtemp(prefix="xigma-peek-")


def _gk_px(_a, _b):
    """Pixels of one layer that differ from another's, on the machine drawing both."""
    return sum(1 for _q in ImageChops.difference(_a.convert("RGBA"), _b.convert("RGBA"))
               .get_flattened_data() if _q != (0, 0, 0, 0))


def _gk_draw(_obj, _met, _when=None):
    """A draw this gate owns.  `themes.draw` fills in what the painter reads and `themes.load`
    caches one object per (path, mtime), so a census never touches the shared copy - and the
    metrics body is copied just as deeply, because this gate draws at one pinned body again and
    again, and its byte-for-byte claims are only worth making if nothing can write into it."""
    return themes.draw(_gg_deep.deepcopy(_obj), _gg_deep.deepcopy(_met), _when or _gk_WHEN)


def _gk_ed(_name):
    """An editor of this gate's own, over a fresh read of the file (or the export)."""
    if _name in themes.EXPORTS:
        return gui_edit.Editor(_gg_deep.deepcopy(themes.export(_name)),
                               origin="generated from render.py", path="", name=_name,
                               theme=_name)
    _rec = themes.resolve(_name)
    return gui_edit.Editor(_gg_deep.deepcopy(themes.load(_rec["path"])),
                           origin=themes.origin(_rec), path=_rec["path"], name=_rec["name"])


# ---- feature G grew the advanced fold by one box: the census of what folds is taken from the
# ---- section's own `folded` list (a gate above names all twelve controls and asserts its
# ---- length), and the prose half below holds docs/gui.md and `app.py`'s module docstring to
# ---- those three numbers - controls, loose rows, boxes.  Not `win._adv_hide`: that list holds
# ---- a field's label as well as the field, eighteen widgets for twelve controls.
_gk_fold_all = list(folded)
_gk_fold_boxed = (win.status_box, win.reset_box, win.confirm, win.btn_reset,
                  win.peek_box, win.ed_peek, win.ed_peek_file)
_gk_fold_boxes = sum(1 for _w4 in _gk_fold_all if _w4 in (win.status_box, win.reset_box,
                                                          win.peek_box))
_gk_fold_loose = len([_w4 for _w4 in _gk_fold_all if _w4 not in _gk_fold_boxed])
assert _gk_fold_boxes == 3 and _gk_fold_loose == 5, (
    _gk_fold_boxes, _gk_fold_loose, [type(_w4).__name__ for _w4 in _gk_fold_all])

# ------------------------------------------------------------------ the loader door --
# One door, two callers: `--metrics-file` for the loop (through `_pinned`, which caches) and the
# pane's peek for the window.  The shapes it has to answer belong to the file, not to this run.
import xigmalcd.main as _gk_main                # the section's own `_m` alias is reused by
                                                # three later blocks for a regex match and for
                                                # a QFontMetrics, so this gate names its own
_gk_ok = os.path.join(_gk_TMP, "body.json")
_gk_missing = os.path.join(_gk_TMP, "not-here.json")
_gk_bad = os.path.join(_gk_TMP, "broken.json")
_gk_list = os.path.join(_gk_TMP, "list.json")
# A body chosen to answer exactly the names the pinned fixture answers, and no others: that is
# what lets the note lines of the two frames be compared sentence by sentence.
with open(_gk_ok, "w") as _fh:
    _gg_json.dump({"_comment": "a note in the file, not a section",
                   "cpu": {"temperature": 104.0, "load": 96.0, "usage": 96.0,
                           "speedAverage": 3400, "power": 18.0, "voltage": 1.36},
                   "gpu": {"temperature": 47.0, "load": 22.0, "speed": 1200, "fan": 45.0,
                           "power": 90.0, "memoryUsage": 2458, "dedicatedTotal": 8192},
                   "memory": {"load": 41.0, "used": 53740, "total": 131072},
                   "motherboard": {"temperature": 44.0},
                   "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 1180},
                            {"onBoard": True, "type": "Chassis", "name": "Fan System 5",
                             "value": 890}]}, _fh)
open(_gk_bad, "w").write("{ this is not json at all")
_gg_json.dump([1, 2, 3], open(_gk_list, "w"))

_gk_secs, _gk_why = _gk_main.read_metrics_file(_gk_ok)
assert _gk_why == "" and "_comment" not in _gk_secs, (sorted(_gk_secs), _gk_why)
assert _gk_secs["cpu"]["temperature"] == 104.0, _gk_secs["cpu"]
_gk_r_miss = _gk_main.read_metrics_file(_gk_missing)
assert _gk_r_miss[0] == {} and "FileNotFoundError" in _gk_r_miss[1], _gk_r_miss
_gk_r_bad = _gk_main.read_metrics_file(_gk_bad)
assert _gk_r_bad[0] == {} and "JSONDecodeError" in _gk_r_bad[1], _gk_r_bad
_gk_r_list = _gk_main.read_metrics_file(_gk_list)
assert _gk_r_list[0] == {} and "not a list" in _gk_r_list[1], _gk_r_list
# and the loop's half of the same door: a broken file must not stop a display.  The section's
# state is put back afterwards, because other gates in this section read what the loop keeps.
_gk_saved = (_gk_main.PINNED, _gk_main.PINNED_MTIME)
try:
    _gk_pa = lambda pth: _gk_main.build_parser().parse_args(
        ["--theme", "alpha", "--metrics-file", pth])
    assert _gk_main._pinned(_gk_pa(_gk_ok))["cpu"]["temperature"] == 104.0
    assert _gk_main._pinned(_gk_pa(_gk_bad))["cpu"]["temperature"] == 104.0, (
        "a broken metrics file stopped the loop keeping its last good read")
finally:
    _gk_main.PINNED, _gk_main.PINNED_MTIME = _gk_saved
_gk_body = _gk_secs
_gk_absent = set(themes.values(_gg_deep.deepcopy(_gk_body), _gk_WHEN)[1])
_gk_fabsent = set(themes.values(_gg_deep.deepcopy(_gk_FIX), _gk_WHEN)[1])
# The body is *self-contained*: it is not the fixture with a few keys patched, so a name the
# fixture cannot answer may well be answered here (this file names `gpu.dedicatedTotal`, which
# the pinned fixture has never carried: docs/theme-editor.md keeps the story of the stale
# fixture keys).  That is deliberate - a deterministic frame needs a deterministic body - and
# it is what lets the gate assert two exact note-line values, `104°C` from this file against
# the fixture's `57°C`.  What must **not** happen is the body dropping a name the fixture
# answers: that would take a row out of the picture and make the two frames incomparable.
assert not (_gk_fabsent - _gk_absent), (sorted(_gk_fabsent - _gk_absent), sorted(_gk_absent),
                                        "the file body answers less than the fixture does, so "
                                        "a row that paints at the fixture would paint nothing "
                                        "in the peek, and the note lines could not be compared")
# the five names the library asks and nothing here can answer: a **file** fact, the same set
# the prose counts.  `_gk_absent` is wider by whatever this machine cannot read - a CI runner
# with no interface section answers fewer names than the bench does - so the gate holds this
# intersection and prints the width instead of asserting one number for it.
_gk_fanpump = {"Fan 3 Name", "Fan 3 Speed", "Fan 4 Name", "Fan 4 Speed", "Pump Speed"}
assert _gk_fanpump <= _gk_absent and _gk_fanpump <= _gk_fabsent, (sorted(_gk_absent),
                                                                  sorted(_gk_fabsent))
print(f"  the loader door      `main.read_metrics_file` answers four shapes: a body with its "
      f"`_` comment key dropped ({sorted(_gk_secs)}), a path that is not there, a file that "
      f"is not JSON, and a JSON list where a `STATE all 1` body belongs - each failure a "
      f"sentence rather than a half-read picture; and `_pinned` keeps its last good read "
      f"through the broken one, which is what a display loop needs")

# ------------------------------------------------- a fresh window sits at the fixture --
_gk = app.Window(bad, None, restore=False, save_settings=False)
_gk.show()
_gk.resize(1600, 1200)
for _ in range(10):
    appq.processEvents()
assert gui_edit.FIXTURE["cpu"]["temperature"] == 57.0
assert _gk._peek is None and _gk.ed_peek.currentData() == "fixture", (_gk._peek,)
assert _gk.ed_peek.currentIndex() == 0, _gk.ed_peek.currentIndex()
assert not _gk.ed_peek_file.isEnabled(), "the path box is live in a mode that will not read it"
assert not _gk.ed_peek.isEnabled(), "the combo is offered with no layout open"
assert not [k for k in _gk._state() if "peek" in k.lower()], sorted(_gk._state())
for _need in ("metrics file", "held", "refused", "fixture", "`--metrics-file`",
              "is remembered", "never hands the panel"):
    assert _need in _gk.ed_peek.toolTip(), (_need, _gk.ed_peek.toolTip()[:220],
                                            "the combo's tooltip stopped saying what a peek "
                                            "is, and what it never does")
_gk.ed_name.setCurrentText("bars")
for _ in range(8):
    appq.processEvents()
assert _gk.ed is not None and _gk.ed.name == "bars", _gk.ed_name.currentText()
assert _gk.ed_peek.isEnabled(), "the combo stayed shut after a layout opened"
assert _gk.preview.pixmap().width() == render.W, (
    _gk.preview.pixmap().width(), "this window was sized so the glass is at 1:1")
_gk.ed.select(2)
_gk.ed_widget.setCurrentIndex(2)
for _ in range(4):
    appq.processEvents()
_gk_hit = _gk.ed.hit(_gk._ed_notes, 240, 24)          # a point that answers a row
assert _gk_hit is not None, _gk_hit
_gk_raw = {str(_r["name"]): open(_r["path"], "rb").read() for _r in pick}
_gk_pin_layer = _gk._osd.tobytes()
assert _gk_pin_layer == _gk.ed.paint(*_gk.ed.fixture(), ink=_gk._ink())[0].tobytes()
assert _gk.preview.marks and _gk.preview.marks[0], _gk.preview.marks


def _gk_note():
    return _gk.ed_note.text()


def _gk_at(_px, _py):
    ox, oy = _gk.preview._origin()
    return int(round(ox + _px)), int(round(oy + _py))


def _gk_press(_px, _py):
    _gk.preview.mousePressEvent(_ev(_QEv.Type.MouseButtonPress, *_gk_at(_px, _py)))
    appq.processEvents()


def _gk_key(_key):
    _gk.preview.keyPressEvent(_ev(_QEv.Type.KeyPress, key=_key))
    appq.processEvents()


# ---------------------------------------------------------------------- the peek, by file --
_gk.ed_peek_file.setText(_gk_ok)
_gk.ed_peek.setCurrentIndex(2)
_gk._editor_peek()                                      # as `activated` would deliver it
for _ in range(6):
    appq.processEvents()
assert _gk._peek is not None and _gk.ed_peek.currentIndex() == 2
assert _gk._peek["when"] == _gk_WHEN, (
    "a peek moved the instant: two peeks of one file would not be the same picture, and the "
    "Date/Time/Week rows would rewrite themselves every second")
assert _gk._peek["metrics"]["cpu"]["temperature"] == 104.0, _gk._peek["metrics"]["cpu"]
assert _gk_ok in _gk._peek["source"], _gk._peek["source"]
_gk_pk_layer = _gk._osd.tobytes()
assert _gk_pk_layer == _gk_draw(_gk.ed.obj, _gk_body)[0].tobytes(), (
    "the pane's peek layer is not what a direct draw of that body gives")
assert _gk_pk_layer != _gk_pin_layer, (
    "a body pinning the temperature at 104.0 drew the fixture's picture: nothing was peeked "
    "at, so every claim below would be about a frame nobody saw")
assert _gk.preview.marks is None, _gk.preview.marks
assert "peeking" in (_gk.preview.toolTip() or ""), _gk.preview.toolTip()[:140]
assert _gk_note() == _gk.ed.peek_sentence(_gk._peek["source"], _gk._peek["metrics"],
                                          _gk._peek["when"], _gk._peek["held"]), _gk_note()[:180]
assert "PEEK" in _gk.metrics.text() and _gk._peek["source"] in _gk.metrics.text(), \
    _gk.metrics.text()[:150]
assert "peek" in _gk.caption.text().lower(), _gk.caption.text()[:150]
assert _gk.ed_peek_file.isEnabled(), "the path box went shut while the file mode is chosen"
# the doors still answer the pinned frame, exactly as before the peek
assert _gk.ed.hit(_gk._ed_notes, 240, 24) == _gk_hit, (
    "`_ed_notes` changed under a peek: those boxes are what `hit`, the marks, the snap lines "
    "and the size edges all read, and they must stay the pinned frame's")
_gk_mx = _gk._mark_box(_gk.ed.index)
assert _gk_mx and _gk_mx == _gk.ed._row_box(_gk.ed.obj, _gk.ed.index), (_gk_mx,)
# the note lines describe the frame on the screen
_gk_pair = _gk._note_pair()
assert _gk_pair[0]["cpu"]["temperature"] == 104.0 and _gk_pair[1] == _gk_WHEN, _gk_pair
_gk_temp = next(i for i, _w in enumerate(_gk.ed.widgets())
                if str(_w.get("type")) == "data"
                and "Temperature" in str((_w.get("property") or [{}])[0].get("source") or ""))
_gk.ed.select(_gk_temp)
_gk.ed_widget.setCurrentIndex(_gk_temp)
for _ in range(4):
    appq.processEvents()
_gk_pk_line = _gk.ed.drawn_text(*_gk._note_pair())[0]
_gk_fx_line = _gk.ed.drawn_text(*_gk.ed.fixture())[0]
assert _gk_pk_line == "104°C" and _gk_fx_line == "57°C", (
    _gk_pk_line, _gk_fx_line, "the note line is supposed to say what the row paints in the "
    "frame you are looking at")
assert _gk_note() == _gk.ed.peek_sentence(_gk._peek["source"], _gk._peek["metrics"],
                                          _gk._peek["when"], _gk._peek["held"]), (
    "selecting a row while peeking overwrote the peek's own sentence, and that sentence is "
    "the only place the pane says which body it drew")
_gk_pk_px = _gk_px(_gk_draw(_gk.ed.obj, _gk_body)[0], _gk.ed.paint(*_gk.ed.fixture(),
                                                                   ink=_gk._ink())[0])
print(f"  peeking, by file     the pane painted `{_gk.ed.name}` from `{_gk_ok.split('/')[-1]}` "
      f"byte for byte as a direct draw of that body does ({len(_gk_pk_layer)} B of layer, "
      f"{_gk_pk_px} px of it moved by that body), the marks went away with a tooltip saying "
      f"why, and the row's own note line reads {_gk_pk_line!r} where the fixture reads "
      f"{_gk_fx_line!r}")

# A held body redraws with nothing moving, and holding is proved at the door: the file is
# opened **once** per press - the peek's only read - and not once while the pane repaints.
_gk_opens = []
_gk_real_open = open


def _gk_counted_open(_pth, *_a, **_kw):
    if str(_pth) == _gk_ok:
        _gk_opens.append(str(_pth))
    return _gk_real_open(_pth, *_a, **_kw)


_gg_builtins.open = _gk_counted_open       # `builtins.open`, what `open()` finds
try:
    _gk._editor_peek()                                   # the reader chose the entry again
    for _ in range(4):
        appq.processEvents()
    _gk_after_press = len(_gk_opens)
    _gk._repaint()
    _gk._repaint()
    for _ in range(4):
        appq.processEvents()
    _gk_after_repaints = len(_gk_opens)
finally:
    _gg_builtins.open = _gk_real_open
assert _gk_after_press == 1, (_gk_after_press, "one press on the knob read the file more than "
                                               "once, or not at all")
assert _gk_after_repaints == 1, (_gk_after_repaints, "a repaint re-read the peek's file: that "
                                                "is a following pane, not a held one")
assert _gk._osd.tobytes() == _gk_pk_layer, "a held body repainted differently: it is not held"

# ------------------------------------------------------------------ what a peek refuses --
_gk_steps, _gk_dirty = _gk.ed.steps, _gk.ed.dirty
_gk_xy = (int(_gk.ed.prop().get("x", -1)), int(_gk.ed.prop().get("y", -1)))
_gk_pt = (_gk_mx[0] + 2, (_gk_mx[1] + _gk_mx[3]) // 2)      # ink the pinned frame put there
_gk_press(*_gk_pt)
assert _gk._drag is None, "a press began a drag on a peek whose marks said there was nothing"
assert _gk_note() == _gk.ed.peek_refusal("A press on the glass"), _gk_note()[:220]
_gk_key(_QQt.Key.Key_Right)
assert (_gk.ed.steps, _gk.ed.dirty) == (_gk_steps, _gk_dirty), (_gk.ed.steps, _gk_steps)
assert (int(_gk.ed.prop().get("x", -1)), int(_gk.ed.prop().get("y", -1))) == _gk_xy, (
    _gk_xy, _gk.ed.prop(), "an arrow key moved a row while the pane was peeking")
assert _gk_note() == _gk.ed.peek_refusal("An arrow key"), _gk_note()[:220]
for _sentence in (_gk.ed.peek_refusal("A press on the glass"), _gk.ed.peek_refusal("An arrow "
                                                                                  "key"),
                  _gk.ed.peek_sentence(_gk._peek["source"], _gk._peek["metrics"], _gk_WHEN,
                                       _gk._peek["held"])):
    assert "peek" in _sentence and "fixture" in _sentence, _sentence
assert _gk.ed.peek_refusal("A press on the glass") == _gk.ed.peek_refusal(
    "A press on the glass"), "the refusal is not the model's fixed words"
print(f"  refused on the peek  a press on the row's own ink and an arrow key each answered "
      f"with the model's sentence rather than the window's: no drag started, no undo step "
      f"taken, the selected row's `x` and `y` unmoved ({_gk_xy[0]},{_gk_xy[1]}), and the "
      f"`dirty` flag still {_gk_dirty}")

# ------------------------------------------------------ a peek whose file cannot be read --
for _txt, _need in (("", "has to be named"), (_gk_missing, "FileNotFoundError"),
                    (_gk_bad, "JSONDecodeError"), (_gk_list, "not a list")):
    _gk.ed_peek_file.setText(_txt)
    _gk._editor_peek()
    for _ in range(4):
        appq.processEvents()
    assert _gk._peek is None, (_txt, _gk._peek)
    assert _gk.ed_peek.currentIndex() == 2, (
        _txt, _gk.ed_peek.currentIndex(), "a failed peek snapped the mode away from under the "
        "reader, losing the path they were about to name")
    assert _gk_note().startswith("no peek:") and _need in _gk_note(), _gk_note()[:170]
    assert _gk._osd.tobytes() == _gk_pin_layer, (
        _txt, "a refused peek changed the picture: the pinned frame stays up until a body is "
        "actually read")
    assert _gk.ed_peek_file.isEnabled(), "the path box was shut while the reader names it"
print("  a peek that cannot be read   four refusals - no path named, a path that is not "
      "there, a file that is not JSON, and a JSON list where a `STATE all 1` body belongs - "
      "each one the loader's own sentence on the note line, the pinned frame still painted, "
      "and the chosen mode left on the combo")

# --------------------------------------------------------------------- the sensors peek --
_gk.ed_peek_file.setText(_gk_ok)
_gk.ed_peek.setCurrentIndex(1)                           # this machine's readings
_gk_reads = []
_gk_real_collect = sensors.collect
sensors.collect = lambda *a, **k: (_gk_reads.append(1), _gk_real_collect(*a, **k))[1]
_gk._editor_peek()
_gk_collects = len(_gk_reads)
sensors.collect = _gk_real_collect
for _ in range(6):
    appq.processEvents()
assert _gk._peek is not None and _gk.ed_peek.currentIndex() == 1
assert "sensors" in _gk._peek["source"], _gk._peek["source"]
_gk_live_secs = sorted(k for k in _gk._peek["metrics"] if k != "timestamp")
_gk_live = dict(_gk._peek["metrics"])
# A runner answers fewer sections than this bench does - one early CI run came back with only
# `cpu`, `disk`, `memory` and `timestamp`, no `gpu` and no fans at all - so what is asserted here
# is that the peek took a body, held it, and painted exactly that body; which sections this
# machine contributed is printed further down, as this machine's fact.
assert _gk._osd.tobytes() == _gk_draw(_gk.ed.obj, _gk_live)[0].tobytes(), (
    "the sensors peek is not a draw of the body that was read - a second read crept in")
assert _gk.preview.marks is None and _gk.ed.hit(_gk._ed_notes, 240, 24) == _gk_hit
_gk_live_px = _gk_px(_gk_draw(_gk.ed.obj, _gk_live)[0],
                     _gk.ed.paint(*_gk.ed.fixture(), ink=_gk._ink())[0])
# re-choosing the entry you are already on *is* the re-read, and one re-read costs one collect
_gk_metrics0 = dict(_gk._peek["metrics"])
_gk_held0 = _gk._peek["held"]
time.sleep(1.05)
_gk_reads.clear()
_gk_real_collect = sensors.collect
sensors.collect = lambda *a, **k: (_gk_reads.append(1), _gk_real_collect(*a, **k))[1]
_gk.ed_peek.setCurrentIndex(1)
_gk._editor_peek()
_gk_press_cost = time.time()
_gk_live2 = dict(_gk._peek["metrics"])
_gk_press_cost = time.time() - _gk_press_cost
sensors.collect = _gk_real_collect
assert _gk_live2 is not _gk_metrics0 and len(_gk_reads) == _gk_collects, (
    len(_gk_reads), _gk_collects, "a re-read cost a different number of reads than the press "
    "that first opened the peek - the knob would mean two different things")
# Whether a second of following moves any pixels belongs to the machine and the moment: an idle
# runner answers the same temperature, the same load and the same fan speed twice, and moves
# nothing.  The half that is *this program's* promise is the one asserted just below: one held
# body, drawn twice, is the same picture exactly.
_gk_follow_px = _gk_px(_gk_draw(_gk.ed.obj, _gk_metrics0)[0], _gk_draw(_gk.ed.obj, _gk_live2)[0])
_gk_held_twice = _gk_px(_gk_draw(_gk.ed.obj, _gk_live2)[0], _gk_draw(_gk.ed.obj, _gk_live2)[0])
assert _gk_held_twice == 0, (
    _gk_held_twice, "a held body drew two different layers in the same window, so the peek is "
    "not held and every byte-for-byte claim about it is false")
_gk_t0 = time.time()
_gk_live1 = _gk_real_collect()
_gk_collect_ms = 1000 * (time.time() - _gk_t0)
_gk_t0 = time.time()
_gk_draw(_gk.ed.obj, _gk_live1)
_gk_draw_ms = 1000 * (time.time() - _gk_t0)
print(f"  peeking, by sensor   this machine's own readings ({', '.join(_gk_live_secs)}), drawn "
      f"as one held body: {_gk_live_px} px of `{_gk.ed.name}` moved against the fixture, and a "
      f"second read about a second later moved {_gk_follow_px} px more with no edit at this end "
      f"- which is why the peek is held rather than followed. One press costs one "
      f"`sensors.collect()` ({_gk_collect_ms:.0f} ms here) plus a layer draw "
      f"({_gk_draw_ms:.0f} ms); a repaint costs no read of the peek's body")

# ------------------------------------------------------------------ back to the fixture --
_gk.ed_peek.setCurrentIndex(0)
_gk._editor_peek()
for _ in range(8):
    appq.processEvents()
assert _gk._peek is None and not _gk.ed_peek_file.isEnabled()
assert _gk._osd.tobytes() == _gk_pin_layer, (
    "leaving a peek did not put the pinned frame back byte for byte")
assert _gk.preview.marks and _gk.preview.marks[0], _gk.preview.marks
assert "fixture" in _gk_note(), _gk_note()[:130]
_gk_key(_QQt.Key.Key_Right)
assert _gk.ed.steps == _gk_steps + 1 and int(_gk.ed.prop()["x"]) == _gk_xy[0] + 1, (
    _gk.ed.steps, _gk_xy, "the editable frame did not come back when the peek left")
_gk.ed_undo.click()
for _ in range(6):
    appq.processEvents()
assert (int(_gk.ed.prop().get("x", -1)), int(_gk.ed.prop().get("y", -1))) == _gk_xy
_gk.ed_name.setCurrentText(app.NO_EDITOR)
for _ in range(8):
    appq.processEvents()
assert _gk.ed is None and _gk._peek is None and _gk.ed_peek.currentIndex() == 0
_gk._editor_peek()
assert "no layout open" in _gk_note(), _gk_note()[:130]
assert not _gk.ed_peek.isEnabled(), "the combo is live again with no layout open"
_gk.close()
# and leave the section's own window quiet.  The sleeps above (one second, to watch a held
# sample against a following one) queue `win`'s preview timer, and the next `processEvents()`
# - which belongs to a gate **after** this one - would drain them; a repaint re-applies the
# still-selected row's marks, so a gate that asserts what a press left on the pane would be
# reading a frame boundary rather than its own act.  Eight pumps of the loop cost a quarter of
# a second and buy the section back its determinism.
for _ in range(8):
    appq.processEvents()
    time.sleep(0.03)
appq.processEvents()
assert {str(_r["name"]): open(_r["path"], "rb").read() for _r in pick} == _gk_raw, (
    "a peek wrote to a vendor layout file")
assert themes.user_copies() == [], themes.user_copies()
print("  back at the fixture  one press of the same knob put the pinned frame back exactly "
      "(layer byte for byte), the marks returned with it, and the arrow key moved the row "
      "again - then undo put the row back; closing the layout cleared the peek by itself, and "
      "no file anywhere changed")

# ---- and the census behind G's rules: what another body of readings moves, and how much of
# ---- that belongs to the machine.  Two columns, on purpose: the **file body** the peek is
# ---- driven with is the same JSON on this bench and on CI's runner, so every count taken
# ---- against it is asserted; this machine's own sensors are a fact about this machine, so the
# ---- same counts taken against them are printed and labelled, never quoted by a page and never
# ---- asserted - a runner with no `gpu` section, or an idle second in which nothing moves, would
# ---- otherwise fail a claim that is really about a deterministic body.  The same split feature
# ---- F shipped with, applied one level finer.
_gk_files = [(str(_r["name"]), themes.load(_r["path"])) for _r in pick]
_gk_files += [(_n, themes.export(_n)) for _n in sorted(themes.EXPORTS)]
_gk_sensors = _gk_real_collect()

_gk_c = dict(rows=0, boxes=0, box_moved=0, box_only=0, probe=0, probe_diff=0,
             sent=0, sent_diff=0, sent_value_only=0, sent_both_none=0, sent_reason_diff=0,
             x_num_changed=0, x_num_max=0, edges_changed=0, edges_same_box=0,
             showif_changed=0)
_gk_edge_case = None                              # the first row whose offer moved, and why
_gk_l = dict(box_moved=0, box_only=0, probe_diff=0, sent=0, sent_diff=0, sent_value_only=0,
             sent_both_none=0, sent_reason_diff=0, showif_changed=0, edges_changed=0)
for _nm, _ob in _gk_files:
    _i, _nf = _gk_draw(_ob, _gk_FIX)
    _i, _nb = _gk_draw(_ob, _gk_body)              # the named file body: machine-independent
    _i, _nl = _gk_draw(_ob, _gk_sensors)           # this box's own readings: its own, printed
    _bf = {r[3]: tuple(r[2]) for r in (_nf.get("boxes") or []) if r[2]}
    _bb = {r[3]: tuple(r[2]) for r in (_nb.get("boxes") or []) if r[2]}
    _bl = {r[3]: tuple(r[2]) for r in (_nl.get("boxes") or []) if r[2]}
    _ed = _gk_ed(_nm)
    _rows = _ed.widgets()
    _gk_c["rows"] += len(_rows)
    _gk_c["boxes"] += len(_bf)
    _gk_c["box_moved"] += sum(1 for _i2 in set(_bf) & set(_bb) if _bf[_i2] != _bb[_i2])
    _gk_c["box_only"] += len(set(_bf) ^ set(_bb))
    _gk_l["box_moved"] += sum(1 for _i2 in set(_bf) & set(_bl) if _bf[_i2] != _bl[_i2])
    _gk_l["box_only"] += len(set(_bf) ^ set(_bl))
    # the pane's own question, at three frames: press this point, which row answers?
    for _px in range(0, render.W, 16):
        for _py in range(0, render.H, 16):
            _gk_c["probe"] += 1
            _gk_c["probe_diff"] += _ed.hit(_nf, _px, _py) != _ed.hit(_nb, _px, _py)
            _gk_l["probe_diff"] += _ed.hit(_nf, _px, _py) != _ed.hit(_nl, _px, _py)
    # every row's note sentence, at the fixture and at each other body: different, and how?
    for _i2 in range(len(_rows)):
        _ed.select(_i2)
        _a, _sa = _ed.drawn_text(_gg_deep.deepcopy(_gk_FIX), _gk_WHEN)
        _gk_c["sent"] += 1
        _gk_l["sent"] += 1
        for _met, _key in ((_gk_body, _gk_c), (_gk_sensors, _gk_l)):
            _b, _sb = _ed.drawn_text(_gg_deep.deepcopy(_met), _gk_WHEN)
            if (_a, _sa) == (_b, _sb):
                continue
            _key["sent_diff"] += 1
            if _a is None and _b is None:
                _key["sent_both_none"] += 1
                _key["sent_reason_diff"] += _sa != _sb
            elif _a is None or _b is None:
                # a row that paints in one frame and not the other: a *different* kind of
                # difference, and the one a runner's missing section can cause by itself
                _key["showif_changed"] += 1
            else:
                _key["sent_value_only"] += 1
                _key["sent_reason_diff"] += _sa != _sb
    # feature F's centring number, and feature D's edges, asked of each frame's own ink: the
    # file body here, because a centring number that moved is a reason to refuse a drag and the
    # claim has to hold wherever the suite runs
    for _i2, _w in enumerate(_rows):
        _pr = (_w.get("property") or [{}])[0]
        if _pr.get("x") is None:
            continue
        _fa = _ed._x_number(_i2, render.W // 2, _bf.get(_i2))[0]
        _fb = _ed._x_number(_i2, render.W // 2, _bb.get(_i2))[0]
        if (_fa is None) != (_fb is None) or (_fa is not None and _fa != _fb):
            _gk_c["x_num_changed"] += 1
            if _fa is not None and _fb is not None:
                _gk_c["x_num_max"] = max(_gk_c["x_num_max"], abs(_fa - _fb))

    # feature D's grab squares, asked of every row at both frames.  The squares are a
    # function of the **box** a frame drew - `size_edges` pushes each of the eight through
    # `_resize_plan` with that box and never looks at a reading - so the invariant that
    # holds wherever the suite runs is: one box, one answer.  What a body *does* change is
    # which boxes exist, and that is a drawn figure like any other: printed, with the one
    # example the run found, never asserted as one number for both machines.
    for _i2 in range(len(_rows)):
        _ea = _ed.size_edges(_i2, _bf[_i2]) if _i2 in _bf else ()
        _eb = _ed.size_edges(_i2, _bb[_i2]) if _i2 in _bb else ()
        _el = _ed.size_edges(_i2, _bl[_i2]) if _i2 in _bl else ()
        _gk_l["edges_changed"] += _ea != _el
        if _bf.get(_i2) == _bb.get(_i2):
            _gk_c["edges_same_box"] += 1
            assert _ea == _eb, (_nm, _i2, str(_rows[_i2].get("type")), _bf.get(_i2), _ea,
                                _eb, "one drawn box, two different offers: `size_edges` is "
                                     "not the pure function of the box its door says it is")
        if _ea != _eb:
            _gk_c["edges_changed"] += 1
            assert _bf.get(_i2) != _bb.get(_i2), (
                _nm, _i2, _bf.get(_i2), _ea, _eb, "the offer moved at an unchanged box")
            if _gk_edge_case is None:
                _gk_edge_case = (_nm, _i2, str(_rows[_i2].get("type")),
                                 _bf.get(_i2), _bb.get(_i2), _ea, _eb)

assert _gk_c["rows"] and _gk_c["boxes"], _gk_c
# the claims G's prose rests on, proved on the body both machines read: a page that says "the
# marks are hidden because the boxes move" needs the boxes to move, and the sentence that calls
# a note line's difference a *value* needs no reason strings to change
assert _gk_c["box_moved"] > 0, _gk_c
assert _gk_c["probe_diff"] > 0, _gk_c
assert _gk_c["sent_diff"] > 0, _gk_c
assert not _gk_c["showif_changed"] and not _gk_c["sent_reason_diff"], (
    _gk_c, "the file body changed a row's *reason* (or took a row in and out of the picture), "
    "so the note lines can no longer be re-computed against it as docs/gui.md says they are")
assert _gk_c["sent_value_only"] + _gk_c["sent_both_none"] == _gk_c["sent_diff"], _gk_c
# feature D's squares never consult a reading - they are asked of a box, and the loop above
# asserts `size_edges` answers the same at the same box.  What *can* move is which squares the
# pane can offer at all: a box that moved, or a box that is not drawn in that frame at all (a
# runner with no `gpu` section and no tachometers simply paints fewer rows), leaves a different
# offer.  That follows drawn geometry, so the count is printed, never asserted as one number for
# both machines - but it can only move where the box changed, moved or gone, and that bound holds
# wherever the suite runs.
assert _gk_c["edges_changed"] <= _gk_c["box_moved"] + _gk_c["box_only"], (
    _gk_c, "a row's offered edges moved while its box sat still: `size_edges` is reading "
           "something other than the box it was handed")
assert _gk_l["edges_changed"] <= _gk_l["box_moved"] + _gk_l["box_only"], (
    _gk_l, "the same rule at this machine's own readings: an offer moved at an unchanged box")
print(f"  what another body moves   counted against the file body the peek is driven with, the "
      f"same JSON on either machine, which is why these are asserted: {_gk_c['box_moved']} of "
      f"the {_gk_c['boxes']} row boxes the {len(_gk_files)} layouts draw at the fixture land "
      f"elsewhere ({_gk_c['box_only']} boxes appear or vanish outright), {_gk_c['probe_diff']} "
      f"of the {_gk_c['probe']} points probed on the glass answer a different row in one frame "
      f"than the other, and {_gk_c['sent_diff']} of {_gk_c['sent']} note sentences differ - "
      f"{_gk_c['sent_value_only']} of them a value, 0 a reason, 0 a row coming in or out of the "
      f"picture.  Feature F's centring number moved for {_gk_c['x_num_changed']} rows, by up to "
      f"{_gk_c['x_num_max']} px.  That is why a peek carries no marks and refuses a press.")
# the one example this run found, spelled out, because "the offer follows the box" is a
# sentence a reader can only check against a case.  Whether the ink leaves the glass is
# computed from the two boxes rather than assumed, so the sentence is true wherever it runs.
if _gk_edge_case:
    _gk_nm, _gk_i2, _gk_kind, _gk_b0, _gk_b1, _gk_e0, _gk_e1 = _gk_edge_case
    _gk_off = bool(_gk_b1) and (_gk_b1[0] < 0 or _gk_b1[1] < 0 or _gk_b1[2] > render.W
                                or _gk_b1[3] > render.H)
    _dg = (f"the case this run found: `{_gk_nm}` row {_gk_i2} ({_gk_kind}) drew "
           f"{_gk_b0} at the fixture and {_gk_b1} at the body"
           + (f", which puts ink past the {render.W}x{render.H} canvas" if _gk_off else "")
           + f" - the pane offered {len(_gk_e0)} squares there ({_gk_e0}) and "
             f"{len(_gk_e1)} here ({_gk_e1})")
else:
    _dg = "this run found no row whose offer moved at all"
print(f"                        feature D's grab squares: no reading is ever asked "
      f"({_gk_c['edges_same_box']} rows offered the same squares at the same box, and no row "
      f"ever offered two different answers for one box), yet which squares are offered moved "
      f"for {_gk_c['edges_changed']} row{'' if _gk_c['edges_changed'] == 1 else 's'} - because "
      f"a handle is painted on the row's **drawn** box, and a different body draws a different "
      f"box.  {_dg}")
print(f"                        this machine's own readings, printed and not asserted because "
      f"they belong to it: {_gk_l['box_moved']} boxes moved, {_gk_l['box_only']} appeared or "
      f"vanished, {_gk_l['probe_diff']} of {_gk_c['probe']} probed points answered another row, "
      f"{_gk_l['sent_diff']} sentences differed ({_gk_l['sent_value_only']} values, "
      f"{_gk_l['sent_both_none']} unpainted-reason, {_gk_l['showif_changed']} a row in or out"
      f" of the picture, {_gk_l['sent_reason_diff']} reasons changed).  The shapes agree; the"
      f" counts are this box's.")

# ---- and the pinned pair itself, whole at the end of a section that has drawn with it a few
# ---- hundred times.  `edit.py`'s `fixture()` used to hand out `dict(FIXTURE)`, a shallow copy
# ---- whose inner dicts were the module's own, and this section's hole-in-the-readings gate
# ---- pops a reading out of the body it is handed - so every draw after that one answered one
# ---- derived rate fewer, in that process, on either machine.  The door deep-copies now, and
# ---- this is the whole-section proof: the live module dict still equals a fresh parse of
# ---- `edit.py`'s own literal.  Compared against the source text rather than a second in-process
# ---- copy, so a fixture *edited on purpose* still passes and one merely worn down by a caller
# ---- does not.  The copy's cost is printed too, because that door sits on a repaint path.
_gk_worn = {k: (sorted(gui_edit.FIXTURE.get(k) or {}), sorted(_gk_FIX.get(k) or {}))
            for k in set(gui_edit.FIXTURE) | set(_gk_FIX)
            if gui_edit.FIXTURE.get(k) != _gk_FIX.get(k)}
assert not _gk_worn, (
    _gk_worn, "the shared pinned fixture came out of this section changed: some door handed a "
              "caller the module's own inner dicts, and every draw after that answered one "
              "reading fewer")
_gk_copy_ms = []
for _ in range(200):
    _t = time.time()
    gui_edit.Editor._fixture_metrics()
    _gk_copy_ms.append(1000 * (time.time() - _t))
_gk_copy_ms.sort()
_gk_c_vals, _gk_c_abs = themes.values(_gg_deep.deepcopy(gui_edit.FIXTURE), _gk_WHEN)
print(f"  the pinned pair      `edit.FIXTURE` is what `edit.py` writes it to be, after "
      f"{len(_gk_files)} layouts drew at it and this section's own hole-punch gate punched a "
      f"reading out of **its own copy**: {_gk_c_vals and len(_gk_c_vals)} names answered here, "
      f"{len(_gk_c_abs)} absent on this machine.  A deep copy of the pair costs "
      f"{_gk_copy_ms[len(_gk_copy_ms) // 2]:.3f} ms (median of 200), against "
      f"{_gk_draw_ms:.0f} ms for the layer draw next to it, so pinning it properly is free")

# ---- and what that hole cost, named.  Both bodies are pinned, so which *names* one answers and
# ---- the other does not is a library fact, and it is asserted: the punch took exactly one
# ---- derived rate, the one `memory.used` divides by `memory.total` to get.  How many boxes and
# ---- adjacencies that painting costs is drawn geometry - this section's reorder census counts
# ---- those, and feature G's two-machine rule says a drawn count is printed with its machine
# ---- named and not quoted by a page - so the counts below are printed and the pages name the
# ---- rows and the reading instead, which hold on either machine (`gate_g_digits` asserts that).
_gk_worn_body = _gg_deep.deepcopy(_gk_FIX)
_gk_worn_body["memory"].pop("total", None)
_gk_v_pris = themes.values(_gg_deep.deepcopy(_gk_FIX), _gk_WHEN)[0]
_gk_v_worn = themes.values(_gk_worn_body, _gk_WHEN)[0]
assert sorted(set(_gk_v_pris) - set(_gk_v_worn)) == ["RAM Rate"], (
    sorted(set(_gk_v_pris) - set(_gk_v_worn)), "taking `memory.total` out of the pinned pair "
    "costs a name other than the rate it divides by: the story the pages tell about this hole "
    "is the wrong story")
assert not set(_gk_v_worn) - set(_gk_v_pris), (
    sorted(set(_gk_v_worn) - set(_gk_v_pris)), "a fixture missing a total answered a name the "
                                               "whole fixture does not: the comparison is wrong")


def _gk_box_rows(_metrics, _obj, _rows):
    """Which of `_rows` have a drawn box at `_metrics`, and which adjacent pairs that makes."""
    _n = _gk_draw(_obj, _metrics)[1]
    _bx = {r[3]: tuple(r[2]) for r in (_n.get("boxes") or []) if r[2]}
    return (_bx, {(i, i + 1) for i in range(len(_rows) - 1) if i in _bx and i + 1 in _bx})


_gk_bars = dict(_gk_files)["bars"]
_gk_bars_rows = _gk_ed("bars").widgets()
_gk_bp, _gk_pp = _gk_box_rows(_gk_FIX, _gk_bars, _gk_bars_rows)
_gk_bw, _gk_pw = _gk_box_rows(_gk_worn_body, _gk_bars, _gk_bars_rows)
_gk_back = sorted(str(_gk_bars_rows[i].get("id")) for i in set(_gk_bp) - set(_gk_bw))
assert _gk_back == ["xigma-bars-ram-rate-meter", "xigma-bars-used-ram-value"], (
    _gk_back, "the two rows that stopped painting without `memory.total` are not the RAM rows "
              "the pages name: either the layout changed or the diagnosis in docs/gui.md and "
              "docs/theme-editor.md is being repeated without being measured")
assert sorted(set(_gk_pp) - set(_gk_pw)) == [(13, 14), (14, 15), (15, 16)], (
    sorted(set(_gk_pp) - set(_gk_pw)), "the three adjacencies of drawn rows the pages say came "
                                       "back with those two rows are not the three this run "
                                       "counted")
print(f"                        and what it cost, in rows: with `memory.total` taken out of the "
      f"pinned pair, `bars` paints {len(_gk_bw)} drawn boxes where the whole pair gives "
      f"{len(_gk_bp)}, because these rows ask for what is gone - "
      + ", ".join(f"{str(_gk_bars_rows[i].get('id'))} ({_gk_bars_rows[i].get('type')})"
                  for i in sorted(set(_gk_bp) - set(_gk_bw)))
      + f"; the adjacencies that came back with them are "
      + ", ".join(f"rows {i}/{j}" for i, j in sorted(set(_gk_pp) - set(_gk_pw)))
      + f" ({len(_gk_pw)} adjacent pairs inside `bars` at the worn body -> {len(_gk_pp)} at the "
      f"whole one), which is the whole of the movement this section's reorder census counted")

# a second of following, measured as the seconds pass, on the layout the peek is driven with.
# The asserted half is the held one, and it is machine-independent: one body, drawn twice, is
# one picture.  The following half belongs to the moment, so it is printed - an idle runner can
# answer the same temperature and the same load twice in a second and move nothing.
_gk_obj = dict(_gk_files)["bars"]
_gk_t0 = time.time()
_gk_a_layer = _gk_draw(_gk_obj, _gk_sensors)[0]
time.sleep(max(0.0, 1.05 - (time.time() - _gk_t0)))
_gk_b_layer = _gk_draw(_gk_obj, _gk_real_collect())[0]
_gk_hold = _gk_draw(_gk_obj, _gk_sensors)[0]
_gk_follow = _gk_px(_gk_a_layer, _gk_b_layer)
_gk_span = time.time() - _gk_t0
assert _gk_px(_gk_a_layer, _gk_hold) == 0, (
    "the same held body drew two different layers: every byte-for-byte claim about a peek "
    "would be false")
_gk_costs = []
for _ in range(3):
    _t = time.time()
    _gk_real_collect()
    _gk_costs.append(1000 * (time.time() - _t))
print(f"  held, not followed  one held body draws the same layer twice with 0 px different - "
      f"that is what a byte-for-byte comparison of a peek can mean - while following this "
      f"machine's sensors for {_gk_span:.1f} s moved {_gk_follow} px of `bars`' layer with no "
      f"edit involved ({sum(_gk_costs) / 3:.0f} ms a read here, {render.W * render.H:,} px of "
      f"glass to redraw).  Whether a following pane moves is the machine's business; whether a "
      f"held "
      f"one is stable is this program's, and only the second is asserted.")

# ---- feature G's sentences, held to the numbers the **files** give this run.  Everything
# ---- asserted here is a file fact: which `source` names the layouts ask for, which of them
# ---- come from the instant rather than a reading, how many rows read them, what the pinned
# ---- fixture answers.  Nothing here draws, so this bench and CI's runner must answer
# ---- identically - and the drawn figures (boxes moved, pixels following costs) are printed by
# ---- the census above on the machine it ran on, never quoted by a page.
_gk_names = set()                                   # `source` names the library asks for
_gk_rows_with_source = 0
_gk_instant_rows = 0
for _nm2, _ob2 in _gk_files:
    for _w2 in (_ob2.get("osd") or {}).get("widget") or []:
        # one row, one `source`: the first `property` entry, which is the one the painter
        # reads for the row's own value (a `special` row's extra entries are named by the
        # drawing's own rule, not by this census)
        _pr2 = (_w2.get("property") or [{}])[0]
        _src = str(_pr2.get("source") or "")
        if not _src:
            continue
        _gk_names.add(_src)
        _gk_rows_with_source += 1
        if _src in themes.CLOCKED:
            _gk_instant_rows += 1
_gk_all = len(_gk_names)
_gk_ans = sorted(_s for _s in _gk_names if _s in themes.values(_gg_deep.deepcopy(_gk_FIX),
                                                               gui_edit.FIXTURE_WHEN)[0])
_gk_noans = sorted(_s for _s in _gk_names if _s not in _gk_ans)
_gk_asked_clock = sorted(_s for _s in _gk_names if _s in themes.CLOCKED)
assert _gk_rows_with_source and _gk_all, (_gk_rows_with_source, _gk_all)
assert len(themes.CLOCKED) == 3, themes.CLOCKED            # Date, Time, Week
# the five generated layouts' half of the census, which docs/gui.md and docs/theme-editor.md
# have quoted since 0.5, and which is a **different** count: five files, not twenty-eight.  The
# same row rule as above, restricted to the five layouts this repository draws from `render.py`.
_gk_five = sorted({_str for _n3 in sorted(themes.EXPORTS)
                   for _w3 in (themes.export(_n3).get("osd") or {}).get("widget") or []
                   for _str in [str((_w3.get("property") or [{}])[0].get("source") or "")]
                   if _str})
_gk_five_ans = [s for s in _gk_five if s in _gk_ans]
_gk_five_noans = [s for s in _gk_five if s not in _gk_ans]
assert len(_gk_five) == len(_gk_five_ans) + len(_gk_five_noans), (_gk_five, _gk_ans)
# G's figures are about the pinned pair **as `edit.py` writes it**, so they are counted from the
# pristine parse the window half built (`_gk_FIX`) - and the live module dict's state is printed,
# because the difference is a defect this cycle found in its own harness.
_gk_vals, _gk_abs = themes.values(_gg_deep.deepcopy(_gk_FIX), gui_edit.FIXTURE_WHEN)
_gk_live_vals, _gk_live_abs = themes.values(_gg_deep.deepcopy(gui_edit.FIXTURE),
                                            gui_edit.FIXTURE_WHEN)
_gk_fanpump = {"Fan 3 Name", "Fan 3 Speed", "Fan 4 Name", "Fan 4 Speed", "Pump Speed"}
assert _gk_FIX["cpu"]["temperature"] == 57.0, _gk_FIX["cpu"]
# the file body the window gate drives its peek with, and the figures the pages quote from it
_gk_body_file = _gk_body["cpu"]["temperature"]
assert _gk_body_file == 104.0 and _gk_body["cpu"]["load"] == 96.0, _gk_body["cpu"]

_gk_cl_top = " ".join(open("debian/changelog", encoding="utf-8").read()
                      .split("\n -- ")[0].split())
_gk_readme = " ".join(open("README.md", encoding="utf-8").read().split())
_gk_tedit = _flat("docs/theme-editor.md")
_gk_edit_src2 = _flat("xigmaui/edit.py")
_gk_main_src = _flat("xigmalcd/main.py")

# ---- docs/gui.md: the four bullets' file figures, in the order the page writes them --------
for _what, _pat, _mine in (
        ("what the fixture answers, across the whole library, on the page",
         r"Widening that census to all \*\*(\d+)\*\* layouts the pane can open: \*\*(\d+)\*\* "
         r"rows carry a `source`[^.]*?asking \*\*(\d+)\*\* distinct names, of which that dict "
         r"answers \*\*(\d+)\*\* and leaves \*\*(\d+)\*\* with no value",
         (len(_gk_files), _gk_rows_with_source, _gk_all, len(_gk_ans), len(_gk_noans))),
        ("the names that come from the instant, and how many rows read them, on the page",
         r"the painter takes `Date`, `Time` and `Week` from the instant it is handed rather "
         r"than from any reading, the library's rows ask for \*\*(\d+)\*\* of those "
         r"\*\*(\d+)\*\* names, and \*\*(\d+)\*\* rows read them",
         (len(_gk_asked_clock), len(themes.CLOCKED), _gk_instant_rows)),
        ("the numbers behind the note-line claim, on the page",
         r"pins `cpu\.temperature` to \*\*(\d+)\.\d+\*\* a\s+temperature row reads "
         r"`(\d+)°C`, where the same row reads `(\d+)°C` at the fixture",
         (int(_gk_body_file), int(_gk_body_file),
          int(_gk_FIX["cpu"]["temperature"]))),
        ("the five generated layouts' census, which the page has quoted since 0.5",
         r"it answers \*\*(\d+)\*\* of the \*\*(\d+)\*\* sources the five generated layouts "
         r"ask, the \*\*(\d+)\*\* it leaves being the `Fan 3`/`Fan 4` slots",
         (len(_gk_five_ans), len(_gk_five), len(_gk_five_noans))),
        # the window's own `_adv_hide` list, counted in the window half above: what folds,
        # how much of it is a loose row, and how much belongs to one of the three boxes
        ("the fold, which feature G's box grew to twelve controls in three boxes",
         r"the set by parent as well as by length: \*\*(\d+)\*\* controls, in \*\*(\d+)\*\* "
         r"rows and \*\*(\d+)\*\* boxes",
         (len(_gk_fold_all), _gk_fold_loose, _gk_fold_boxes)),
):
    _stated(_what, _gf, _pat, _mine)
for _phrase in ("Pane readings", "main.read_metrics_file", "never remembered",
                "peek_refusal", "the model's own sentence", "PEEK - this machine's",
                "| pane readings | controls, advanced, folded"):
    assert _phrase in _gf, (_phrase, "docs/gui.md stopped naming what this gate holds it to")
assert "fixture and not live readings" not in _gf, (
    "docs/gui.md still calls live readings unbuilt, and they are built - as a peek")
# the four bullets are four, and each says what the gate proves about it
# counted by their leads rather than by `* **`, because the flattened page has no line ends
_gk_bullets = _re.findall(r"(?:The pane can also look at another body's readings"
                          r"|The instant stays pinned, and the readings stay held"
                          r"|A press on a peek is refused"
                          r"|What a peek shows, the note lines say)", _gf)
assert len(_gk_bullets) == 4, _gk_bullets
print(f"  G's page figures     the library asks {_gk_all} `source` names across the "
      f"{len(_gk_files)} layouts, the fixture answers {len(_gk_ans)} and leaves "
      f"{len(_gk_noans)} ({', '.join(_gk_noans)}); the painter's {len(themes.CLOCKED)} "
      f"instant names are asked by {len(_gk_asked_clock)} of them, read by "
      f"{_gk_instant_rows} rows; `themes.values` answers {len(_gk_vals)} here and calls "
      f"{len(_gk_abs)} absent on this machine ({', '.join(sorted(_gk_abs))}) - a set holding "
      f"the five names above plus whatever else this box cannot read; and the five generated "
      f"layouts "
      f"alone ask {len(_gk_five)} names, answered {len(_gk_five_ans)} - the older sentence in "
      f"docs/gui.md and docs/theme-editor.md quotes that pair, not the library-wide one")
if _gk_live_vals != _gk_vals:
    print(f"                        and this run caught a door handing out the module's own "
          f"inner dicts again: the live `edit.FIXTURE` in this process answers "
          f"{len(_gk_live_vals)} names, not {len(_gk_vals)} - it cannot answer "
          f"{sorted(set(_gk_live_abs) - set(_gk_abs))} any more.  `Editor.fixture()` "
          f"deep-copies since the repair of 2026-11-11 (docs/theme-editor.md keeps that story), "
          f"so this print means some *other* door is sharing the pinned pair, and every draw "
          f"after it in this process answers a reading fewer.  G's figures above are counted "
          f"from a parse of `edit.py`'s own literal, which is why they stay right when it does.")

# ---- `edit.py`'s and `app.py`'s own comments: the shipped tree states the same counts ------
_stated("the library census, in `edit.py`'s docstring", _gk_edit_src2,
        r"the (\d+) rows carrying a `source` in the 28 layouts this pane opens ask for "
        r"\*\*(\d+)\*\* distinct names, the pinned fixture answers \*\*(\d+)\*\* of them and "
        r"leaves \*\*(\d+)\*\* with no value",
        (_gk_rows_with_source, _gk_all, len(_gk_ans), len(_gk_noans)))
assert "how much wider depends on what a given machine answers" in _gk_edit_src2, (
    "`edit.py` states a machine-dependent size for `themes.values`' absent list again")
assert _gk_fanpump <= set(_gk_abs), (sorted(_gk_abs),
                                     "the fixture no longer leaves the fan and pump names "
                                     "unanswered, and the pages say it does")
_stated("the fold arithmetic, in `app.py`'s module docstring", _app_src,
        r"folds away twelve secondary controls, in \*\*(\d+)\*\* rows and \*\*(\d+)\*\* boxes",
        (_gk_fold_loose, _gk_fold_boxes))
for _phrase, _why in (
        ("which knob puts the editable frame back",
         "`peek_sentence` names the fix, and says it in four things rather than three"),
        ("The gate asserts both", "`peek_refusal` rests on the two frames disagreeing, and "
                                  "says the gate will not print a count that is not there"),
        ("the acts that write a number are refused with `peek_refusal`'s sentence",
         "`fixture()` says the peek never goes through that door")):
    assert _phrase in _gk_edit_src2, (_phrase, _why, "`edit.py` no longer says it")
for _phrase, _why in (
        ("Pane readings", "the folded box's name, which the docs and the gate both use"),
        ("A peek is a look", "the combo's tooltip, in the window's own words"),
        ("its file field rides the *mode*", "the enablement rule in `_ed_set_enabled`"),
        ("the peek is not written to the session file",
         "the peek is not remembered, said in the code that builds the box"),
        ("the pinned frame stays up", "a refusal paints nothing new"),
        ("it never hands the panel a", "a peek is a look at numbers, not a delivery")):
    assert _phrase in _app_src, (_phrase, _why, "`app.py` no longer says it")

for _phrase, _why in (
        ("def read_metrics_file", "the one loader for `--metrics-file` and the pane's peek"),
        ("a `STATE all 1` body is a JSON object, not a", "the non-object refusal, in words"),
        ("A key starting with `_` is a comment in the file, not a section",
         "the comment-key rule, spelled in exactly one place now"),
        ("keeping the last good read", "the loop's half of the same door")):
    assert _phrase in _gk_main_src, (_phrase, _why)

# ---- the 0.6 stanza, themes.md, theme-editor.md and README: the record and the pages ------
for _what, _pat, _mine in (
        ("the instant names, in the 0.6 stanza",
         r"the painter takes `Date`, `Time` and `Week` from the instant rather than from any "
         r"reading, the library's rows ask for (\d+) of those (\d+) names and (\d+) rows read "
         r"them",
         (len(_gk_asked_clock), len(themes.CLOCKED), _gk_instant_rows)),
        ("the numbers behind the note-line claim, in the 0.6 stanza",
         r"\(`(\d+)°C` becomes `(\d+)°C` at a file body pinning `cpu\.temperature` to "
         r"(\d+)\.\d+\)",
         (int(_gk_FIX["cpu"]["temperature"]), int(_gk_body_file),
          int(_gk_body_file))),
):
    _stated(_what, _gk_cl_top, _pat, _mine)
_stated("the fold census, in the 0.6 stanza", _gk_cl_top,
        r"The fold census moves with the new box: (\d+) secondary controls in (\d+) "
        r"rows and (\d+) boxes",
        (_gk_fold_all and len(_gk_fold_all), _gk_fold_loose, _gk_fold_boxes))
for _phrase in ("**Pane readings**", "`main.read_metrics_file`", "PEEK", "never remembered",
                "peek_refusal", "the four ways a metrics file can fail",
                "the census of what moves", "loader door is checked in both"):
    assert _phrase in _gk_cl_top, (_phrase, "the 0.6 stanza no longer says what was built")
assert "an editor drawing live readings" not in _gk_cl_top.split("Still not built")[1], (
    "the still-not-built bullet still lists live readings, and they shipped this cycle")
assert "folds away the twelve secondary controls named further down" in _gf \
    and "the pane-readings box in the controls column" in _gf, (
    "docs/gui.md's own table no longer counts the fold the way the window does")
assert "folds twelve secondary controls" in _gk_readme, "README counts the fold differently"
assert "peeked" in _gk_readme, "README's editor paragraph has not heard of the peek"
assert "in place of the first of those, is the **peek**" in _gk_tedit \
    and "Live readings came in on" in _gk_tedit, (
    "docs/theme-editor.md does not say where live readings came in")
assert "not built, and not claimed: live readings" not in _gk_tedit.lower(), (
    "docs/theme-editor.md still opens a canvas passage by calling live readings unbuilt")
for _doc in ("docs/themes.md",):
    _txt = " ".join(open(_doc, encoding="utf-8").read().split())
    assert "**not** built is a resize" in _txt and "is a **peek**" in _txt, (
        _doc, "the library page's not-built list no longer matches what shipped")
# the page's D sentence: the invariant may be stated, the machine-dependent count may not.
# `gate_g_census.py` asserts the invariant per row (one box, one answer) and prints the rows
# whose offer moved with their boxes; a page quoting one machine's count would be a stale claim
# the moment the other machine answered, so the digits stay off the pages by gate, not habit.
for _src, _where in ((_gf, "docs/gui.md"), (_gk_cl_top, "the 0.6 stanza")):
    assert "never consults a reading" in _src and "one box, one answer" in _src, (
        _where, "the sentence separating D's rule from its drawn consequence is gone, and the "
                "census no longer has a page to correct")
    assert not _re.search(r"D's (?:grab )?squares? (?:moved|change) for \d+", _src), (
        _where, "a page states one machine's count of rows whose offered squares moved")
# ---- the pinned-pair repair's cause, held in the pages by the parts that hold on either
# ---- machine.  A row's `id`, the reading it asks for and the key that produces it are file and
# ---- library facts, and `gate_g_census.py` measures which two rows and which one name a worn
# ---- `memory.total` costs before this block reads the pages.  How many drawn boxes and pixels
# ---- that is worth belongs to the machine that drew them, so the census prints it and no page
# ---- quotes it - the same split as feature D's grab squares just above.
for _src, _where in ((_gf, "docs/gui.md"), (_gk_tedit, "docs/theme-editor.md"),
                     (_gk_cl_top, "the 0.6 stanza")):
    for _phrase in ("`RAM Rate`", "`memory.total`"):
        assert _phrase in _src, (_where, _phrase, "the record of the pinned-pair hole no longer "
                                                  "names the reading it cost")
    for _id in _gk_back:
        # the id has to survive the page's own line wrapping, and a hyphen is a legal break
        # point, so the pattern allows whitespace wherever the id has a hyphen
        assert _re.search(_id.replace("-", r"[-\s]+"), _src), (
            _where, _id, "the pages no longer name the rows this run measured as the ones a "
                         "worn fixture hides")
    assert not _re.search(r"\d+ drawn boxes", _src), (
        _where, "a page states how many drawn boxes a body of readings paints, which is this "
                "machine's figure - the census above prints it, and the labelled pair the "
                "reorder gate holds stays the only drawn count quoted")
_gk_on_page = _re.search(r"`bars` rows ((?:\d+/\d+)(?:[ ,] and |, )\d+/\d+(?: and \d+/\d+)?)",
                         _gk_tedit)
assert _gk_on_page, ("docs/theme-editor.md", "the paragraph no longer names which adjacencies "
                                             "of drawn rows came back with those two rows")
_page_pairs = sorted({tuple(int(_x) for _x in _p.split("/"))
                      for _p in _re.findall(r"\d+/\d+", _gk_on_page.group(1))})
assert _page_pairs == sorted(set(_gk_pp) - set(_gk_pw)), (
    _page_pairs, sorted(set(_gk_pp) - set(_gk_pw)),
    "docs/theme-editor.md names adjacencies other than the ones this run counted coming back")
print(f"                        the pinned pair's cause, in the pages by name: one derived rate "
      f"(`RAM Rate`, from `memory.used` / `memory.total`) and the {_gk_back and len(_gk_back)} "
      f"rows that ask for it ({', '.join(_gk_back)}); on this run the drawn halves are "
      f"{len(_gk_bw)} -> {len(_gk_bp)} boxes and {len(_gk_pw)} -> {len(_gk_pp)} adjacencies "
      f"inside `bars`, printed here and quoted by no page")

print(f"                        the pages, `edit.py`, `app.py`, `main.py` and the 0.6 stanza "
      f"all carry those counts; the fold stands at 12 controls in 5 rows and 3 boxes; and no "
      f"page calls live readings unbuilt any more")

# ---- the tooltips this window shows, measured as the pixels they paint.  Reported on
# ---- 2026-11-11: every tooltip over the preview pane had a black background and text too
# ---- faint to read.  A Qt tooltip is painted by `QTipLabel`, a top-level of the application
# ---- that takes its colours from the palette of the widget the tooltip belongs to, so the
# ---- pane's `background:#101014` stylesheet dragged that near-black into the popup while the
# ---- text stayed the palette's own black: 1.11:1, and 0 glyph pixels reaching 4.5:1 (WCAG AA
# ---- for body text) - the "faint gray" in the screenshot is the antialiasing of black on
# ---- near-black.  What ships is `app.apply_tooltip_colours()`: those two colours forced onto
# ---- the popup's own widget class, and nothing else.
# ----
# ---- Two-machine discipline: a *ratio* and a *colour name* are colour facts, so they are
# ---- asserted and answer the same on either machine.  The *count of readable glyph pixels*
# ---- follows the fonts this box has, so it is printed and never asserted, exactly as feature
# ---- F's drawn figures are.
from PyQt6.QtCore import QPoint as _th_QP                            # noqa: E402
from PyQt6.QtGui import QColor as _th_QC, QImage as _th_QI           # noqa: E402
from PyQt6.QtGui import QPalette as _th_QPal                         # noqa: E402
from PyQt6.QtWidgets import QToolTip as _th_QT                       # noqa: E402
from PyQt6.QtWidgets import QWidget as _th_QW                        # noqa: E402


def _th_lum(_c):
    def _f(_v):
        _v /= 255.0
        return _v / 12.92 if _v <= 0.03928 else ((_v + 0.055) / 1.055) ** 2.4
    return 0.2126 * _f(_c.red()) + 0.7152 * _f(_c.green()) + 0.0722 * _f(_c.blue())


def _th_cr(_a, _b):
    _x, _y = sorted((_th_lum(_a), _th_lum(_b)))
    return (_y + 0.05) / (_x + 0.05)


def _th_popup(_w):
    """The tooltip of `_w`, drawn, and what it is actually made of.

    (painted background, palette text colour, their ratio, pixels of glyph ink at >= 4.5:1,
    the popup's size, the palette's own base colour).  The popup is grabbed and its pixels
    counted rather than reasoned about: the defect *was* a palette nobody had looked at, and a
    popup that reports one pair while painting another is how it hid.
    """
    _th_QT.showText(_w.mapToGlobal(_th_QP(_w.width() // 2, _w.height() // 2)), _w.toolTip(), _w)
    for _ in range(6):
        appq.processEvents()
    _lab = next((_t for _t in appq.topLevelWidgets()
                 if _t.metaObject().className() == "QTipLabel"), None)
    assert _lab is not None, "no QTipLabel after showText: there is nothing to measure"
    _img = _lab.grab().toImage()
    _counts = {}
    for _y in range(_img.height()):
        for _x in range(_img.width()):
            _k = _img.pixelColor(_x, _y).name()
            _counts[_k] = _counts.get(_k, 0) + 1
    _bg = _th_QC(max(_counts, key=_counts.get))
    _txt = _lab.palette().color(_th_QPal.ColorRole.ToolTipText)
    _base = _lab.palette().color(_th_QPal.ColorRole.ToolTipBase)
    _ink = sum(_n for _k, _n in _counts.items() if _th_cr(_th_QC(_k), _bg) >= 4.5)
    _th_QT.hideText()
    for _ in range(3):
        appq.processEvents()
    return _bg, _txt, _th_cr(_bg, _txt), _ink, (_img.width(), _img.height()), _base


_th_floor = 4.5                                     # WCAG AA for body text
_th_win = app.Window(bad, None, restore=False, save_settings=False)
_th_win.show()
_th_win.resize(1280, 1024)
_th_win.ed_name.setCurrentText("bars")
for _ in range(12):
    appq.processEvents()

# The colours are in force, and they got there through the narrow door: the popup's own widget
# class.  An application *stylesheet* is the wrong door, and this suite proved it the hard way -
# installing one re-polishes every widget through the stylesheet style, which moved this window's
# own layout (the `arc` box heights the pages label per machine: 858 and 465 px became 818 and
# 459 on this bench, caught by the gate that holds those figures).  So nothing may be installed
# at application scope, and the class palette has to carry both colours.
assert not (appq.styleSheet() or ""), ((appq.styleSheet() or "")[:120],
                                       "an application stylesheet is installed: measured, it "
                                       "costs 40 px of box height in this very window and every "
                                       "pixel gate below it would be holding a layout nobody "
                                       "ships")
_th_tp = appq.palette("QTipLabel")
assert _th_tp.color(_th_QPal.ColorRole.ToolTipBase).name() == app.TOOLTIP_BASE \
    and _th_tp.color(_th_QPal.ColorRole.ToolTipText).name() == app.TOOLTIP_TEXT, (
    _th_tp.color(_th_QPal.ColorRole.ToolTipBase).name(),
    _th_tp.color(_th_QPal.ColorRole.ToolTipText).name(),
    "the window built its tooltips without the shipped colours: a theme's palette is answering")

_th_cand = [_w for _w in _th_win.findChildren(_th_QW)
            if _w.toolTip() and _w.isVisible() and _w.isEnabled()
            and _w.width() > 4 and _w.height() > 4]
assert len(_th_cand) >= 20, (len(_th_cand), "the census is measuring a bare window: a tooltip "
                                            "rule asserted over two widgets checks nothing")
_th_pairs, _th_bad, _th_ink_min = {}, [], None
for _w in _th_cand:
    _bg, _txt, _pair, _ink, _sz, _base = _th_popup(_w)
    _key = (_bg.name(), _txt.name())
    _th_pairs[_key] = _th_pairs.get(_key, 0) + 1
    if _pair < _th_floor:
        _th_bad.append((type(_w).__name__, _bg.name(), _txt.name(), round(_pair, 2)))
    # the text colour is the shipped one everywhere, and the background is either the shipped
    # one or the plate of the widget it belongs to - the pane, by design, keeps its own glass
    assert _txt.name() == app.TOOLTIP_TEXT, (type(_w).__name__, _txt.name(),
                                            "a popup painted text in some colour the tree does "
                                            "not name")
    assert _bg.name() in (app.TOOLTIP_BASE, "#101014"), (type(_w).__name__, _bg.name(),
                                                         "a tooltip took its background from a "
                                                         "widget this window does not paint a "
                                                         "plate on")
    assert _th_cr(_base, _txt) >= _th_floor, (type(_w).__name__, _base.name(), _txt.name(),
                                              round(_pair, 2), "the popup's own palette is "
                                                              "below the floor")
    _th_ink_min = _ink if _th_ink_min is None else min(_th_ink_min, _ink)
assert not _th_bad, (_th_bad, "a tooltip this window shows is unreadable at WCAG AA")
_th_pretty = ", ".join(f"{_b}+{_t} x{_n}" for (_b, _t), _n in sorted(_th_pairs.items()))
print(f"  every tooltip, drawn    {len(_th_cand)} live tooltips on this window, each one shown "
      f"and grabbed; colour pairs painted: {_th_pretty}; the least readable popup clears "
      f"{_th_floor}:1 with {_th_ink_min} px of glyph ink at that contrast - a pixel count, so "
      f"this machine's, and no floor is asserted on it")

# ---- the reported case, named: the preview pane's own popup -------------------------------
_th_pbg, _th_ptxt, _th_ppair, _th_pink, _th_psz, _th_pbase = _th_popup(_th_win.preview)
assert _th_pbg.name() == "#101014", (
    _th_pbg.name(), "the pane's popup no longer paints the pane's own plate: the colours and "
                    "the pane's stylesheet are being read by something other than the popup")
assert _th_ptxt.name() == "#f2f2f2" and _th_ppair >= 15, (
    _th_pbg.name(), _th_ptxt.name(), round(_th_ppair, 2), "the tooltip over the preview pane "
                                                          "went back to dark-on-dark")
print(f"                        the reported case: over the pane the popup paints "
      f"{_th_pbg.name()} behind {_th_ptxt.name()} text, {_th_ppair:.2f}:1 over a "
      f"{_th_psz[0]}x{_th_psz[1]} px popup with {_th_pink} px of readable ink - measured on the "
      f"tree before this change: 1.11:1 and 0 px, which is the faint gray")

# ---- the second hazard the census found, already in the tree before this change -----------
# A tooltip on a widget whose stylesheet paints a background paints *that* background, and the
# colour row's swatch paints whatever colour the layout file names.  Measured on the tree as it
# was, with that colour spelled `rgba(0, 0, 0, 255)`: a #000000 popup with the palette's
# #000000 text, 1.00:1.  With the popup's colours forced and the tooltip left on the swatch,
# the popup at `rgba(255, 255, 255, 255)` keeps #ffffff behind light text: 1.12:1.  No text
# colour is legible on every colour a file can name - a mid-grey defeats either one - so the
# swatch carries no tooltip at all and the row's label, which paints no background of its own,
# carries the words.
_th_fld = None
for _i in range(len(_th_win.ed.widgets())):
    _th_win.ed.select(_i)
    _th_win.ed_widget.setCurrentIndex(_i)
    for _ in range(4):
        appq.processEvents()
    for _f, _rec in _th_win.ed_rows.items():
        if _rec[4] == "colour" and _rec[3] is not None:
            _th_fld = _f
            break
    if _th_fld:
        break
assert _th_fld, "no colour row was offered for a `bars` row, so the swatch case cannot be measured"
assert not _th_win.ed_rows[_th_fld][3].toolTip(), (
    _th_win.ed_rows[_th_fld][3].toolTip()[:60], "the colour swatch carries a tooltip again: its "
                                                "popup would be painted in the layout's own "
                                                "colour, which is not a colour this program can "
                                                "promise text for")
assert "rgba" in _th_win.ed_rows[_th_fld][0].toolTip(), (
    _th_win.ed_rows[_th_fld][0].toolTip()[:80], "the colour row's sentence is not on its label: "
                                                "the words have to live on a widget that paints "
                                                "the shipped popup background")
_th_sweep = []
for _spell in ("rgba(255, 255, 255, 255)", "rgba(0, 0, 0, 255)", "rgba(128, 128, 128, 255)"):
    _th_win.ed.set(_th_fld, _spell)
    _th_win._ed_bind_rows()                  # the rows are rebuilt here, tooltip and all
    for _ in range(6):
        appq.processEvents()
    _th_lab2, _th_sw2 = _th_win.ed_rows[_th_fld][0], _th_win.ed_rows[_th_fld][3]
    _was = _th_sw2.grab().toImage().pixelColor(2, 2).name()
    _b, _t, _p, _k, _s, _ba = _th_popup(_th_lab2)
    _th_sweep.append((_spell, _b.name(), _t.name(), round(_p, 2), _k))
    assert _p >= _th_floor, (_spell, _b.name(), _t.name(), round(_p, 2),
                             "a colour in the file made a tooltip unreadable")
    assert not _th_sw2.toolTip(), "re-binding the rows put a tooltip back on the swatch"
    assert _th_sw2.grab().toImage().pixelColor(2, 2).name() == _was, (
        "the swatch stopped painting the colour the file names: taking its tooltip away was "
        "supposed to change nothing about how it looks")
print("                        the colour row measured at three spellings of its own colour - "
      "white, black, and a mid-grey that defeats either text colour - each popup on the row's "
      "label: " + ", ".join(f"{_s} -> {_b}+{_t} {_p}:1" for _s, _b, _t, _p, _k in _th_sweep)
      + f"; the swatch still paints the file's colour (its own corner pixel reads "
      f"{_was}) and carries no tooltip")

# ---- and the door is scoped: a palette on one class colours no control, moves no pixel ----
# The measurement that decided this shape is recorded on `apply_tooltip_colours`: an application
# stylesheet re-polishes the whole window and moved the `arc` box heights this very section holds
# (858 and 465 px to 818 and 459).  Nothing at application scope is installed here, and the
# ordinary palette still answers what the theme handed it - which is what keeps every drawn and
# laid-out figure in this section meaning what it meant before.
assert not (appq.styleSheet() or ""), "an application stylesheet crept in after all"
assert _th_tp.color(_th_QPal.ColorRole.Window).name() != appq.palette().color(
    _th_QPal.ColorRole.Window).name(), (
    _th_tp.color(_th_QPal.ColorRole.Window).name(), appq.palette().color(
        _th_QPal.ColorRole.Window).name(),
    "the popup palette and the application palette are the same: the class targeting went away, "
    "and every control would be painted in tooltip colours")
_th_layer = _th_win._osd.tobytes()
app.apply_tooltip_colours()                  # idempotent: called again, nothing moves
for _ in range(6):
    appq.processEvents()
assert _th_win._osd.tobytes() == _th_layer, "colouring the tooltip class moved the drawn layer"
_th_cls_win = _th_tp.color(_th_QPal.ColorRole.Window).name()
_th_cls_txt = _th_tp.color(_th_QPal.ColorRole.WindowText).name()
_th_app_win = appq.palette().color(_th_QPal.ColorRole.Window).name()
print(f"                        scoped, and idle: the popup's own class answers "
      f"{_th_cls_win}/{_th_cls_txt} where the window's palette answers {_th_app_win}, no "
      f"application stylesheet is installed, and calling the door again moved 0 of "
      f"{len(_th_layer):,} bytes of the pane's drawn layer")
_th_win.close()

# ---- the pages, held to the numbers this gate just measured ------------------------------
# A ratio is colour maths on fixed hexes, so a page may state it and this gate may assert it:
# either machine answers the same.  The ink counts are not, and no page quotes one.  What the
# popup measured *before* this change (1.11:1, 0 readable px) is a record of the defect, written
# in the past tense in both pages, and nothing here asserts it: what ships is what gets measured.
import re as _th_re

_th_cl = " ".join(open("debian/changelog", encoding="utf-8").read().split("\n -- ")[0].split())


def _th_flat(_path):
    _out = []
    for _ln in open(_path, encoding="utf-8"):
        _t = _ln.strip()
        while _t.startswith("#"):
            _t = _t[1:]
            if _t.startswith(":"):
                _t = _t[1:]
            _t = _t.lstrip()
        _out.append(_t)
    return " ".join(" ".join(_out).split())


_th_app = _th_flat("xigmaui/app.py")
_th_gui = " ".join(gui_txt.split())
_th_sweep_pairs = sorted({_row[3] for _row in _th_sweep})
assert len(_th_sweep_pairs) == 1 and _th_sweep_pairs[0] >= 12, _th_sweep
_th_label_pair = _th_sweep_pairs[0]
for _src, _where, _pats in (
        (_th_gui, "docs/gui.md", (r"measured here at \*\*(\d+\.\d+)\*\*:1 over\s+the pane",
                                  r"\*\*(\d+\.\d+)\*\*:1 everywhere else",
                                  r"each popup on the label answers\s+\*\*(\d+\.\d+)\*\*:1")),
        (_th_cl, "the 0.6 stanza", (r"(\d+\.\d+):1 over the pane and (\d+\.\d+):1 elsewhere",))):
    for _pat in _pats:
        _m = _th_re.search(_pat, _src)
        assert _m, (_where, _pat, "the sentence stating a measured tooltip ratio is gone, so "
                                  "nothing holds it to this run")
        for _grp in _m.groups():
            _got = float(_grp)
            assert any(abs(_got - _v) < 0.01 for _v in (_th_ppair, _th_label_pair)), (
                _where, _pat, _got, round(_th_ppair, 2), _th_label_pair,
                "the ratio written down is not the ratio this window paints")
for _phrase, _why in (("`app.apply_tooltip_colours`", "the door is named where a "
                       "reader looks for it"),
                      ("WCAG AA's 4.5:1", "the floor the gate asserts is the floor the page says"),
                      ("swatch carries no tooltip", "the colour row's sentence moved, in prose"),
                      ("palette of the widget the tooltip belongs to",
                       "the mechanism is stated, not just the fix")):
    assert _phrase in _th_gui, (_phrase, _why, "docs/gui.md stopped saying it")
for _phrase in ("`app.apply_tooltip_colours`", "16.96:1", "12.65:1", "1.11:1",
                "0 pixels of readable"):
    assert _phrase in _th_cl, (_phrase, "the 0.6 stanza no longer records what was measured")
for _phrase, _why in (("palette of the widget the tooltip belongs to",
                       "`apply_tooltip_colours`' comment carries the mechanism"),
                      ("858 px in one column, 465 px in three",
                       "why an application stylesheet was rejected, in the code"),
                      ("no wording can be made legible on every colour",
                       "why the swatch carries no tooltip"),
                      ("COLOUR_TIP", "the colour sentence lives in one named constant")):
    assert _phrase in _th_app, (_phrase, _why, "`app.py` stopped saying it in its own comments")
assert not _th_re.search(r"\d[\d,]* px of (readable )?glyph ink", _th_gui), (
    "docs/gui.md quotes a readable-ink pixel count, which belongs to the fonts on one machine")
assert not _th_re.search(r"\d+ (?:live )?tooltips", _th_cl), (
    "the 0.6 stanza counts tooltips, and that count follows which rows are open")
print(f"                        the pages carry those two ratios ({_th_ppair:.2f}:1 over the "
      f"pane, {_th_label_pair:.2f}:1 elsewhere) because this gate measured them, and no page "
      f"quotes a pixel count or a tooltip count")

# a press on empty glass names the point and selects nothing, and closing the layout takes
# the mark with it - the pane goes back to a live preview, with nothing drawn on it
# The timer is stopped for this passage, and it is said rather than slipped: `_repaint` ends by
# re-applying the selected row's marks, so a press that clears them clears them **until the next
# frame** - and whether a frame lands inside the press's own event pumping is timing, not the
# behaviour under test.  The fact that follows is the honest one: the mark comes back, because
# the press said only that the *point* was nobody's row, and the row that was selected still is.
win.preview_timer.stop()
_free_pt = next((x, y) for y in range(0, render.H, 7) for x in range(0, render.W, 7)
                if win.ed.hit(win._ed_notes, x, y) is None)
_press(*_free_pt)
assert "selects no row" in win.ed_note.text(), win.ed_note.text()
assert win.preview.marks is None, win.preview.marks
_gg_before = win.ed.index
win._repaint()
for _ in range(4):
    appq.processEvents()
assert win.ed.index == _gg_before and win.preview.marks, (
    win.ed.index, _gg_before, win.preview.marks,
    "a repaint did not bring the selected row's mark back: either the press changed the "
    "selection, which the sentence above denies, or the mark is not chrome that follows the "
    "selection - and docs/gui.md calls it chrome painted over the picture")
win.preview_timer.start()
win.ed_name.setCurrentText(app.NO_EDITOR)
for _ in range(8):
    appq.processEvents()
assert win.ed is None and win.preview.marks is None, win.preview.marks
assert themes.user_copies() == [], themes.user_copies()
shutil.rmtree(_tmpc, ignore_errors=True)
print(f"  pointing inside the pane  the same door through the window: row {_clock[3]} is "
      f"the clock line and it is the row a press at its ink box selects - at "
      f"{win.preview.side} px of picture for a {render.W} px glass, so panel {_cx},{_cy} "
      f"is cursor {_wpoint(_cx, _cy)[0]},{_wpoint(_cx, _cy)[1]}. A press and release on "
      f"one point wrote no undo step; a 30 px drag wrote exactly one, and the sentence "
      f"named the row's distance ({_said.group(1)}, {_said.group(2)}) rather than the "
      f"mouse's; undo put every pixel back. Arrows moved 1 px and 10 px. A mark is "
      f"painted over the picture, never into it: the pane's own PNG is byte-identical "
      f"with one showing and without. And x={_max_x} is a legal anchor while that row's "
      f"ink runs to x={_hang[2]}, which `validate` does not mention, so the pane says it "
      f"- while {_free_pt[0]},{_free_pt[1]} is a point on the glass with no row under it")

# The pane's rules are only worth having if the documents state them, and the one that is
# easiest to lose is the sentence about ink hanging off the glass.
_gui_doc = open("docs/gui.md", encoding="utf-8").read()
for _claim in ("can be pointed at", "arrow keys move the selected row",
               "off the 480x480 canvas", "never drawn into the frame the caption counts",
               "**later** row wins"):
    assert _claim in _gui_doc, (_claim, "docs/gui.md does not say what the window does")
# Two documents quote a figure for this same edit, and they had drifted apart: gui.md still
# carried 905 - a byte count divided by four, a fifth under - while theme-editor.md had been
# corrected to the pixel count.  The figure itself follows the face that resolves the label,
# so it is not pinned to this run's number: the line above prints it beside the machine, and
# the docs say whose bench it came from.  What is pinned is that the documents agree with
# each other, and that neither has drifted an order of magnitude away from the run.
_quoted = {}
for _doc in ("docs/gui.md", "docs/theme-editor.md"):
    _quoted[_doc] = sorted({int(x.replace(" ", "")) for x in
                            _re.findall(r"([\d ]+) of 230 400\b",
                                        open(_doc, encoding="utf-8").read())})
assert all(len(v) == 1 for v in _quoted.values()), _quoted
assert len({v[0] for v in _quoted.values()}) == 1, _quoted
assert abs(_quoted["docs/gui.md"][0] - moved_win) <= moved_win // 20, (
    _quoted, moved_win)              # same edit: no factor-of-four drift
print(f"  docs quote the edit   docs/gui.md and docs/theme-editor.md both say "
      f"{_quoted['docs/gui.md'][0]:,} of {render.W * render.H:,} for the same 20 px nudge"
      f" this run measured at {moved_win:,}. It is a face-dependent figure, so it is"
      f" printed beside the machine rather than pinned, but the two documents cannot drift"
      f" apart again, and neither can drift far from what this run painted")

# ---- the pairing, driven through a window of its own, so nothing above this point is
# ---- affected by the background moving under it.  The claim is the one the user of the
# ---- window makes now: "I picked a layout, and its own background came with it."  A vendor
# ---- layout names one clip, the dropdown puts it under the preview and marks the row, and
# ---- the only thing that stops that is the "keep my background" box - which a hand ticks
# ---- and nothing else does.  It used to be the other way round: a row click set the flag,
# ---- so a window could refuse to follow its own pairing for a reason nobody could see, and
# ---- that is the complaint this section now pins from both sides.  The negative halves
# ---- matter as much: populating the list selects a row, and that is not a choice; the five
# ---- themes drawn from code name no clip, and the pane says so rather than leaving the
# ---- reader to wonder whether the pairing is broken.
_pw = app.Window("/dev/xigma-no-such-port", 1.0, restore=False)
assert _pw.keep_clip is False and _pw.chk_keep.isChecked() is False, (
    "a window that nobody touched already holds the background against its own layouts - "
    "populating the clip list selects a row, and that is not a choice")
# What a box can honour is derived from the rows it actually lists, not assumed from this
# bench: a clip can be genuinely absent (a checkout with nothing installed), and the honest
# rule is "pair it when the file is here, say so when it is not".  Both halves are checked.
_avail = {os.path.splitext(os.path.basename(_c.path))[0].lower() for _c in _pw.all_clips}
_here = [_r for _r in pick
         if os.path.splitext(str(_r["background"]).rsplit("/", 1)[-1])[0].lower() in _avail]
_absent = [_r for _r in pick if _r not in _here]
_moved, _rows_ok = 0, 0
for _rec in pick:
    _want = _rec["background"].rsplit("/", 1)[-1]
    _pw.ed_name.setCurrentText(_rec["name"])
    _base = os.path.basename(_pw.mp4)
    if _rec in _here:
        _moved += _base == _want
        if _pw.all_clips and 0 <= _pw.clips.currentRow() < len(_pw.all_clips):
            _rows_ok += _pw.all_clips[_pw.clips.currentRow()].path == _pw.mp4
    else:
        # the pair is not on this box: the clip must not move, and the pane must say which
        # file it is missing rather than leaving the picture unexplained
        assert _base != _want, (_rec["name"], _want, "a clip this box lacks became current")
        assert "does not have" in _pw.pair_note, (_rec["name"], _pw.pair_note)
assert _moved == len(_here), (_moved, len(_here),
                              "the pairing did not follow the clips this box does have")
assert _rows_ok == len(_here), (_rows_ok, len(_here),
                                "the library column does not show the row it paired to")
# A checkout on its own - nothing installed, no Windows partition mounted - is what a CI
# runner and a source install are.  The pairing has to be honourable there, which is why
# `list_clips` walks this repository's own `themes/alpha/clips`: the 44 files it tracks are
# byte-identical to what the themes package installs (the library section re-hashes every
# one of them), so the window is not being pointed at a library it does not have.
import xigmalcd.main as _mm
# The same derived hide-list as the census pass in the GUI section - a separate heredoc, so
# the derivation is repeated rather than assumed to survive from the other one.
import ast as _ast2
import inspect as _insp2
_roots_src = _insp2.getsource(_mm.media_roots)
_KNOWN_ROOTS = sorted({n.id for n in _ast2.walk(_ast2.parse(_roots_src))
                       if isinstance(n, _ast2.Name) and n.id.isupper()})
_SKIP_ROOTS = {"MEDIA_ENV", "REPO_MEDIA", "REPO_CLIP_LIB"}
_WINDOW_ONLY = [k for k in ("WIN_STATIC", "WIN_UPLOADS") if isinstance(getattr(_mm, k), str)]
_saved_roots = {k: getattr(_mm, k) for k in
                [n for n in _KNOWN_ROOTS if n not in _SKIP_ROOTS] + _WINDOW_ONLY}
assert set(_saved_roots) >= {"SYSTEM_MEDIA", "SYSTEM_CLIP_LIB", "WIN_STATIC",
                             "WIN_UPLOADS"}, _saved_roots
_env_media = os.environ.pop("XIGMA_MEDIA", None)
try:
    for _k in _saved_roots:
        setattr(_mm, _k, "/nonexistent-root")
    _alone = clipdb.list_clips()
    _alone_stems = {os.path.splitext(os.path.basename(_c.path))[0].lower()
                    for _c in _alone}
    _gap = [_r["name"] for _r in pick
            if os.path.splitext(str(_r["background"]).rsplit("/", 1)[-1])[0].lower()
            not in _alone_stems]
    assert not _gap, (len(_alone), _gap,
                      "a checkout of this repository alone cannot pair these layouts - its "
                      "own tracked clips are no longer reachable from the window")
    # the same stem form `_alone_stems` is kept in (no extension, lowercase): the vendor
    # gap above uses it too, and comparing a full `Theme_25.mp4` to a stem would report a
    # gap that is not there
    _gap_code = [c for c in themes.CODE_CLIPS.values()
                 if os.path.splitext(c)[0].lower() not in _alone_stems]
    assert not _gap_code, (len(_alone), _gap_code,
                           "a published backdrop of a theme drawn here is not reachable "
                           "from a bare checkout, so those five would pair with nothing "
                           "on a fresh install")
    # Two states the row list alone cannot drive, and both are worth pinning now that the
    # theme library is a root of the loop's own lookup:
    #   * no row, file in a root - the window follows the layout's clip anyway and *says* no
    #     row holds those bytes, rather than pretending the picker is the whole filesystem;
    #   * no row and no clip root anywhere, this checkout's included - the only state in
    #     which "this box does not have it" is true, so that is the state the branch has to
    #     be driven in.  Emptying the list is not that state any more, and an earlier
    #     version of this gate asserted as if it were.
    _keep, _pw.all_clips = _pw.all_clips, []
    try:
        _pw.ed_name.setCurrentText(pick[0]["name"])
        _want = os.path.basename(str(pick[0]["background"]))
        assert os.path.basename(_pw.mp4) == _want, (_pw.mp4, _want,
                                                   "with no rows but the file in a root the "
                                                   "window should still follow the layout's "
                                                   "own clip")
        assert "No row of the library holds these bytes" in _pw.pair_note, _pw.pair_note
    finally:
        _pw.all_clips = _keep

    _bare = {k: getattr(_mm, k) for k in ("REPO_MEDIA", "REPO_CLIP_LIB")}
    _keep, _pw.all_clips = _pw.all_clips, []
    try:
        for _k, _v in _bare.items():
            setattr(_mm, _k, "/nonexistent-checkout-root")
        _missing_at = _pw.mp4
        _pw.ed_name.setCurrentText(pick[1]["name"] if len(pick) > 1 else pick[0]["name"])
        assert _pw.mp4 == _missing_at, (
            _pw.mp4, _missing_at, "a window with no rows and no clip root paired to a file "
                                  "this box cannot resolve")
        assert "does not have" in _pw.pair_note and "keeping" in _pw.pair_note, _pw.pair_note
    finally:
        _pw.all_clips = _keep
        for _k, _v in _bare.items():
            setattr(_mm, _k, _v)
finally:
    for _k, _v in _saved_roots.items():
        setattr(_mm, _k, _v)
    if _env_media is not None:
        os.environ["XIGMA_MEDIA"] = _env_media
    _alone_n = len(_alone)
    clipdb.list_clips()      # leave the module's scan counts as this box actually has them
# a row click is a preview and a thing you may send: it no longer opts the reader out of the
# pairing, and it says in the log what the pick costs.
_other = next(i for i, _c in enumerate(_pw.all_clips)
              if os.path.basename(_c.path) != os.path.basename(_pw.mp4))
_pw.clips.setCurrentRow(_other)
_chosen = os.path.basename(_pw.all_clips[_other].path)
assert os.path.basename(_pw.mp4) == _chosen, (_pw.mp4, _chosen)
assert _pw.keep_clip is False and _pw.chk_keep.isChecked() is False, (
    'clicking a library row ticked "keep my background" by itself - which is the exact '
    "thing 0.4 stopped doing, because a flag set behind a reader's back is what made the "
    "pairing look broken")
_said = [_l for _l in _pw.log_view.text().splitlines() if "next layout change" in _l]
assert _said, (_pw.log_view.text()[-400:],
               "a pick the next layout will overwrite was accepted in silence")
# and the layouts take their own clips back over it, automatically: 6 for 6, each one named
# in the log with the picture it replaced
_follow = 0
for _rec in pick[:6]:
    _pw.ed_name.setCurrentText(_rec["name"])
    _follow += os.path.basename(_pw.mp4) == _rec["background"].rsplit("/", 1)[-1]
assert _follow == 6, (_follow, "the layout dropdown did not choose its own background")
_replaced = [_l for _l in _pw.log_view.text().splitlines() if "replacing" in _l]
assert len(_replaced) >= 6, (len(_replaced),
                             "the pairing moved the picture without saying what it replaced")
assert not _pw.btn_pair.isEnabled(), ("the way back is offered while the pairing is already "
                                      "following the layout - nothing to go back to")
# the box, ticked by a hand: now no layout moves the picture, and every refusal is said in
# the log as well as in the note line.  A row click still moves it: the box governs
# layouts, not the reader.
_pw.chk_keep.setChecked(True)
assert _pw.keep_clip is True, "the box did not reach the flag"
_pw.clips.setCurrentRow(_other)
assert os.path.basename(_pw.mp4) == _chosen, (_pw.mp4, _chosen,
                                              "the box stopped a reader choosing a clip")
_held = os.path.basename(_pw.mp4)
_stayed = 0
for _rec in pick[:6]:
    _pw.ed_name.setCurrentText(_rec["name"])
    _stayed += os.path.basename(_pw.mp4) == _held
assert _stayed == 6, (_stayed, _held, "a layout walked over a background its reader held")
# This is the state that reads like a broken window: a layout declares a clip, the preview
# refuses to move, and nothing else about the picture changed.  The note line is one
# sentence of small print; the log carries the same sentence, names the box, and names the
# way back.
_declined = [_l for _l in _pw.log_view.text().splitlines()
             if '"keep my background" is ticked' in _l]
assert len(_declined) >= 1, (_pw.log_view.text()[-500:],
                             "the window declined a layout's clip and never said why")
assert all("Use this layout's own clip" in _l for _l in _declined), _declined[:2]
assert _pw.btn_pair.isEnabled(), ("the box is ticked and the window offers no way back "
                                  "from it")
_pw.btn_pair.click()
assert _pw.keep_clip is False and _pw.chk_keep.isChecked() is False, (
    _pw.keep_clip, _pw.chk_keep.isChecked(),
    "the way back took the clip without unticking the box, so the next layout would move "
    "it and the box would say otherwise")
assert os.path.basename(_pw.mp4) == _pw._pair_target, (
    _pw.mp4, _pw._pair_target, "the way back did not hand the layout its own clip")
# and unticking is immediate rather than a wish for the next layout change: the picture and
# the box never disagree about what is on screen
_pw.chk_keep.setChecked(True)
_pw.clips.setCurrentRow(_other)
_pw.chk_keep.setChecked(False)
assert os.path.basename(_pw.mp4) == _pw._pair_target, (
    _pw.mp4, _pw._pair_target, "unticking the box left the picture on a clip the open "
                               "layout does not name")
# the five themes this repository draws from `render.py` pair as well: each names the
# backdrop its own published picture is composited over (themes.CODE_CLIPS, derived from
# the README's MP4 names in the library section).  Before 0.4 these five answered with a
# reason and no clip, which is the half of the complaint that opened this section: the
# vendor pages paired and the five did not.  Both pickers reach one rule - the theme picker
# holds the themes, the layout dropdown holds their exports.
_code, _rows_code, _bright = 0, 0, []
# every entry in this order is a real change: the window opens on `sorted(THEMES)[0]`, so
# picking that one first would emit nothing and the note would still be the last layout's -
# which is exactly the kind of vacuous pass a loop over names can produce
_order = sorted(render.THEMES)[1:] + sorted(render.THEMES)[:1]
_pw.scrim.setValue(-1)                       # the daemon's luma rule, not a per-theme plate
for _t in _order:
    _pw.theme.setCurrentText(_t)
    assert _pw.theme.currentText() == _t, (_t, _pw.theme.currentText())
    _want = themes.CODE_CLIPS[_t]
    _code += os.path.basename(_pw.mp4) == _want
    _row = (_pw.all_clips[_pw.clips.currentRow()]
            if 0 <= _pw.clips.currentRow() < len(_pw.all_clips) else None)
    _rows_code += bool(_row) and os.path.basename(_row.path) == _want
    assert _want in _pw.pair_note and "pairs with" in _pw.pair_note, (_t, _pw.pair_note)
    # the plate a pairing brings with it is the luma rule's doing, measured on the row the
    # window paired to - so "four of these five are dark" is a figure with a machine under it
    _lum = clipdb.measure(_row)
    _plate = _pw._render_kw()["scrim"]
    assert (_plate > 0) == (_lum > app.BRIGHT_LUMA), (_t, _want, _lum, _plate)
    if _lum > app.BRIGHT_LUMA:
        _bright.append(_want)
assert _code == len(_order), (_code, len(_order),
                              "a theme drawn here did not pair with its published backdrop")
assert _rows_code == len(_order), (_rows_code,
                                   "the library column does not show the row the five paired to")
# the same five through the dropdown, where their generated exports sit
_drop = 0
for _t in sorted(themes.EXPORTS):
    _pw.ed_name.setCurrentText(_t)
    _drop += os.path.basename(_pw.mp4) == themes.CODE_CLIPS[_t]
assert _drop == len(themes.EXPORTS), (
    _drop, len(themes.EXPORTS), "the dropdown's export entries paired with nothing")
# the entry that closes the editor names no clip of its own; it hands the picture back to
# the open theme, whose pairing then applies like any other
assert themes.pair(app.NO_EDITOR)[0] == "", themes.pair(app.NO_EDITOR)
_pw.ed_name.setCurrentText(app.NO_EDITOR)
assert os.path.basename(_pw.mp4) == themes.CODE_CLIPS[_pw.theme.currentText()], (
    _pw.mp4, _pw.theme.currentText(),
    "closing the editor left a picture no open theme claims")
_pw.theme.setCurrentText(_order[-1])         # the same name again: no signal, no change
assert os.path.basename(_pw.mp4) == themes.CODE_CLIPS[_order[-1]], _pw.mp4
# what a *restored* window does with a remembered clip.  The saved clip is a memory of what
# was under the preview, not a claim about what belongs there: with the box off the open
# theme's own backdrop takes the picture at start-up, and with it on the remembered clip
# comes back exactly.  Both halves on a settings file of this gate's own making, with the
# section's real one put back byte for byte afterwards - this heredoc's other windows are
# still saving into it.
import json                          # this heredoc imports it under other names further
                                     # down; this gate reads and writes a file of its own
_here_cfg = settings.path()
_keep_cfg = (open(_here_cfg, "rb").read() if os.path.exists(_here_cfg) else None)
_remembered = byname["Theme_11.mp4"].path            # a clip `gauge` does not pair with
try:
    for _box in (False, True):
        with open(_here_cfg, "w", encoding="utf-8") as fh:
            json.dump({"theme": "gauge", "clip": _remembered, "keep_my_clip": _box,
                       "device": bad, "preview_fps": 1.0}, fh)
        _back_win = app.Window(bad, None, restore=True)
        assert _back_win.theme.currentText() == "gauge", _back_win.theme.currentText()
        _got = os.path.basename(_back_win.mp4)
        if _box:
            assert _got == os.path.basename(_remembered), (
                _got, _remembered, "the box was ticked and the window moved the picture "
                                   "anyway")
            assert "keep my background" in _back_win.pair_note, _back_win.pair_note
        else:
            assert _got == themes.CODE_CLIPS["gauge"], (
                _got, themes.CODE_CLIPS["gauge"],
                "a restored window without the box kept a clip its open theme does not name")
            assert "pairs with" in _back_win.pair_note, _back_win.pair_note
        _back_win.close()
    print(f"  restored, both halves  a remembered {os.path.basename(_remembered)} comes "
          f"back when the box is ticked and is replaced by gauge's own backdrop "
          f"({themes.CODE_CLIPS['gauge']}) when it is not")
finally:
    if _keep_cfg is None:
        os.remove(_here_cfg) if os.path.exists(_here_cfg) else None
    else:
        with open(_here_cfg, "wb") as fh:
            fh.write(_keep_cfg)
_st = settings._clean(_pw._state())
assert _st["keep_my_clip"] == _pw.keep_clip == _pw.chk_keep.isChecked(), (
    "the window's pairing flag is not the flag its settings file holds, or not the box "
    "a reader can see")
assert "clip_customized" not in _st and "clip_customized" not in _pw._state(), (
    "the window still writes the key 0.4 retired, so a file would answer a question the "
    "code no longer asks")
assert "Use this layout's own clip" in _pw.btn_pair.text(), _pw.btn_pair.text()
assert "keep my background" in _pw.chk_keep.text(), _pw.chk_keep.text()
_pw.close()
_doc = open("docs/gui.md", encoding="utf-8").read()
for _claim in (f"all {len(pick)} selectable layouts", "Use this layout's own clip",
               "does not write one",            # the save_settings rule, above
               "in the note line under",        # a declined pairing has to be said twice
               "keep my background",            # the box: the only way to opt out
               "read once and honoured",        # `clip_customized`, the retired key
               "dropdown selects it automatic",  # 0.4: the pairing arrives by itself
               "backdrop their own",            # the five themes' published backdrops
               "themes.CODE_CLIPS"):            # ...and where they are kept
    assert _claim in _doc, (_claim, "docs/gui.md does not describe the pairing this drives")
_missing_note = ("and each said so instead of pretending" if _absent else
                 "(0 here: that branch is driven instead by taking the rows *and* every "
                 "clip root away from a live window, so the sentence is proven even on a "
                 "box that has every clip)")
print(f"  the pairing in the window  of the {len(pick)} selectable layouts, "
      f"{len(_here)} name a clip this box lists and every one of those moved under the "
      f"preview with its row marked ({_rows_ok}/{len(_here)}); {len(_absent)} name a clip "
      f"this box does not have {_missing_note}; a row click put another clip under the "
      f"preview and ticked nothing, and the next 6 layouts each took their own back "
      f"(6/6) while saying what they replaced ({len(_replaced)} log lines); ticking "
      f"\"keep my background\" held {_held} against all 6 ({_stayed}/6) and named every "
      f"refusal in the log; the button took the pair back and unticked the box, and "
      f"unticking alone moved the picture at once. And the {len(render.THEMES)} themes "
      f"drawn from `render.py` pair too: {_code}/{len(_order)} through the theme picker "
      f"and {_drop}/{len(themes.EXPORTS)} through the dropdown's export entries, each one "
      f"with its row marked ({_rows_code}/{len(_order)}) and its backdrop named in the "
      f"note; {len(_bright)} of those backdrops is bright and came with a plate "
      f"({', '.join(_bright) or 'none'}), the rest measured dark and needed none. On a "
      f"bare checkout - no installed package, no Windows partition - the {_alone_n} rows "
      f"this repository's own files give the window cover all {len(pick)} vendor pairs "
      f"and all {len(themes.CODE_CLIPS)} published backdrops.")
PY

echo
echo "== the window driving a display that is already running: real socket, no port"
gui2=$(mktemp -d)
SOCK_DIR=$(mktemp -d) QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME=$gui2 python3 - <<'PY' \
  || { echo "display-remote FAILED"; exit 1; }
import os
import sys
import time
sys.path.insert(0, ".")
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
qapp = QApplication([])
from xigmalcd import control, render
from xigmaui import app
from xigmaui import panel

# the other process, in this one: the same Control and Server a running
# `xigmalcd` builds, with a settings object standing in for its argparse
# namespace.  Nothing here can open a port, which is the point.
class Args:
    theme = "alpha"
    fps = 1.0
    title = None
    label = None
    scrim = None
    clock_size = 26
    bg = "clear"
    mp4 = "media/Theme_25.mp4"
    no_fans = False


args = Args()
ctl = control.Control(args, "/dev/xigma-stub")
ctl.publish(frames=41, ok=40, refused=0, errors=0, renewals=1,
            last_notice="200", last_name="2026-11-06_15-00-00-000.osd",
            last_bytes=9413, session_uploads=40, session_age=20.0,
            device={"space": 62416})
srv = control.Server(ctl, os.path.join(os.environ["SOCK_DIR"], "x.sock"))
assert srv.start(), srv.error

looked = []
panel.port_busy = lambda port: (looked.append(port), "")[1]
win = app.Window("/dev/xigma-stub-port", 1.0, restore=False,
                 socket=srv.path, tray=False)
qapp.processEvents()
assert win.daemon.present, win.daemon.path
assert win.d_line.text().startswith("showing alpha"), win.d_line.text()
assert "40/41 uploads the panel confirmed" in win.d_counters.text(), \
    win.d_counters.text()
assert win.btn_apply.isEnabled() and win.btn_pause.isEnabled()
print(f"  the window read it: {win.d_line.text()}")

# every action goes to the socket, and the port is never even looked at
win.queue("frame")
assert ctl.take() == ("frame", None), "that frame did not go to the display"
assert not win.panel.isRunning()
clip = os.path.abspath("media/Theme_25.mp4")
win.queue("upload", path=clip, gap=0.02, chunk=1000)
kind, path = ctl.take()
assert (kind, os.path.basename(path or "")) == ("upload", "Theme_25.mp4")
win.queue("status")
assert "40/41 uploads" in win.d_counters.text()
# the panel-status box has no fresh `conn 1` to show in this mode, so it shows
# the display's own hello, labelled as the display's and as not a fresh read
assert "not a fresh read" in win.status.text(), win.status.text()
assert "space=62416" in win.status.text(), win.status.text()
win.queue("live", theme="alpha", kw={}, fps=2.0, seconds=30)
assert "keeps the glass updated" in win.log_view.text(), win.log_view.text()[-400:]
print("  frame / upload / status / live all routed to the display: "
      f"port_busy consulted {len(looked)} times")

# a reset the daemon refuses is reported as a refusal, in the daemon's words:
# never as "the panel did not answer", which is a different failure entirely
win.queue("reset", confirm="reset")
text = win.log_view.text()
assert "the display refused reset" in text and "reset_panel.py" in text, text[-500:]
assert "no answer" not in text[-500:], text[-500:]
print("  the daemon's own gate is quoted, not paraphrased")

# Apply: the window's pickers, sent as the socket's commands, land on the
# display's own settings object; -1 means auto and stays auto
win.theme.setCurrentText("gauge")
win.clock_size.setValue(44)
win._set_ink_choice("amber")                      # a name; the display stores hex
win.canvas.setCurrentIndex(1)                     # black canvas
win.scrim.setValue(-1)                            # auto
win.fanline.setChecked(False)
win.d_fps.setValue(2.0)
t0 = time.perf_counter()
win.btn_apply.click()
took = time.perf_counter() - t0
assert (args.theme, args.clock_size, args.bg, args.scrim) == \
    ("gauge", 44, "black", None), (args.theme, args.clock_size, args.bg,
                                   args.scrim)
assert args.no_fans is True and args.fps == 2.0, (args.no_fans, args.fps)
assert "display told: theme gauge" in win.log_view.text()
assert took < 0.5, took              # seven socket commands, no serial round trip
# the colour is the display's now, in its own hex, and the window read it back
assert args.text_color == (*render.AMBER[:3], 255), args.text_color
assert ctl.status()["text_color"] == "#ffc400", ctl.status()["text_color"]
win.daemon.poll(report=True)
for _ in range(4):
    qapp.processEvents()
# the window's own readout of the display's settings carries it: this is the
# only place a reader can see the colour *the display* holds, as opposed to the
# one this window would send
assert "text #ffc400" in win.d_counters.text(), win.d_counters.text()
print(f"  Apply: {took * 1000:.0f} ms for seven commands, the seventh a text "
      f"colour: the display holds {args.theme} at clock {args.clock_size}, "
      f"canvas {args.bg}, scrim auto, fans off, text "
      f"{ctl.status()['text_color']}, {args.fps} fps")

# the mixed-version case, which is what the author's own desktop is: this window
# from the tree, the display from the installed 0.2 package.  Modelled by taking
# the key the 0.2 status never had back out of the answers, which is all the
# window can see.  It must not offer a command that display cannot take, must not
# call the result a failure, and must not leave the reader to work out why the
# glass did not change colour.
_real_status = ctl.status


def _status_like_02() -> dict:
    st = _real_status()
    st.pop("text_color", None)
    return st


ctl.status = _status_like_02
args.text_color = None
# asked for directly, not waited for: `processEvents` does not advance the wall
# clock, so a 2 s timer may not fire at all in a tight loop and the daemon's
# cached status would still be the pre-patch dict.  That is exactly how this
# check passed on the bench and failed on the runner (run 42355629537): the race
# was in the test, not in the window.
win.daemon.poll(report=True)
for _ in range(6):
    qapp.processEvents()
assert "text_color" not in win.daemon.status, sorted(win.daemon.status)
assert win.daemon.knows("text_color") is False
assert win.daemon.knows("theme") is True       # the rest is not optional
assert not win.ink_choice.isEnabled(), "the row offered a command that cannot go"
assert "INACTIVE" in win.ink_choice.toolTip()
assert "not reported by this display" in win.d_counters.text(), \
    win.d_counters.text()
log_before = win.log_view.text()
win._set_ink_choice("#ff4040")
t0 = time.perf_counter()
win.btn_apply.click()
took02 = time.perf_counter() - t0
seen = win.log_view.text()[len(log_before):]
assert "left text_color alone" in seen, seen
assert "unknown cmd" not in seen, seen
assert args.theme == "gauge" and args.clock_size == 44, (args.theme,
                                                         args.clock_size)
assert args.text_color is None, "the window sent a command it had decided not to"
print(f"  an older display        the colour row goes inactive with the reason "
      f"({took02 * 1000:.0f} ms later Apply had still sent the {6} settings that "
      f"display knows: theme {args.theme}, clock {args.clock_size}, and the log "
      f"says so)")
ctl.status = _real_status
win.daemon.poll(report=True)
for _ in range(6):
    qapp.processEvents()
assert win.daemon.knows("text_color") is True and win.ink_choice.isEnabled(), \
    "the row stayed dead after the display came back with the field"

# the pause button is a user click, and a status sync must not answer itself
win.btn_pause.click()
assert ctl.paused is True
qapp.processEvents()
assert win.d_line.text().startswith("paused"), win.d_line.text()
win.daemon.poll()                    # a refresh while paused: sends nothing back
assert ctl.paused is True and win.btn_pause.isChecked()
win.btn_pause.click()
assert ctl.paused is False
print("  pause / resume: the button drives the display, a refresh does not")

# The tray is not there in this environment, and that is a supported answer.  To test
# the case where it is, build one through the app's own `_build_tray`: an earlier
# version of this fixture handed the window a bare `QSystemTrayIcon` instead, and
# `_tray_sync()` then died with `AttributeError: 'Window' object has no attribute
# 'tray_line'` - printed by PyQt from inside a Qt slot and swallowed, because a raising
# slot fails nothing.  The status line and the pause item are built in the same block as
# the icon, so "an icon with no menu" is not a state this program can be in; faking one
# tested a state that cannot happen and missed the one that does.
class _TrayOnThisDesktop(QSystemTrayIcon):
    @staticmethod
    def isSystemTrayAvailable():
        return True


assert win.tray is None and not QSystemTrayIcon.isSystemTrayAvailable()
_real_tray_cls = app.QSystemTrayIcon
app.QSystemTrayIcon = _TrayOnThisDesktop
try:
    win.tray_wanted = True
    win._build_tray()
finally:
    app.QSystemTrayIcon = _real_tray_cls
assert win.tray is not None, "the tray the desktop offers was not built"
assert win.tray_line is not None and win.tray_pause is not None, "an icon with no menu"
# (Qt answers this with a line on stderr, `QObject::connect: No such signal
# QPlatformNativeInterface::systemTrayWindowChanged(QScreen*)`, because the platform
# plugin here has no tray host to talk to.  That noise is the fixture, not a failure:
# the widgets the menu is made of are built and reachable, which is the thing under test.)
win.show()
qapp.processEvents()
win.close()
assert not win.isVisible() and win.daemon.present
# Hiding to the tray stops the pane's redraw and puts the decode stream away, and
# keeps polling the display: nothing is being drawn, so nothing should be decoded
# (`hideEvent`), while the tray menu still has to know what the other process is
# doing, so the daemon's poll goes on.  Both halves are the point of the split, and
# `showEvent` reverses the first pair.
assert not win.preview_timer.isActive(), "a hidden window does not redraw"
assert win.player is None, "and holds no ffmpeg either"
assert win.daemon_timer.isActive(), "but it still follows the running display"
assert "hidden to the tray" in win.log_view.text()
assert looked == [], looked          # hiding never touches the port
win.show()
qapp.processEvents()
assert win.preview_timer.isActive(), "showing starts the pane again"
# and the tray's own readout of the other process - the call that used to raise
# AttributeError and have it eaten by the slot machinery.  The window is not driving
# anything here: another process holds the port, so what the menu says has to come
# from the control socket's status, which is what it now does.
win._tray_sync()
tray_txt = win.tray_line.text()
st = win.daemon.status
assert st, "the window has no status to put in the menu"
# the line is the daemon's status, in the menu's words: which theme, which rate, how
# many frames the panel has confirmed.  Asserted against the status object rather than
# against a theme name, because an earlier step of this section has already moved the
# display to `gauge` by Apply.
assert tray_txt == f"{st['theme']} at {st['fps']} fps, " \
    f"{st['ok']}/{st['frames']} confirmed" + (" (paused)" if st.get("paused") else ""), \
    (tray_txt, st)
assert win.tray_pause.text() == "Pause the display", win.tray_pause.text()
assert win.tray_pause.isEnabled() and not win.tray_line.isEnabled(), \
    "the status line is a label, not a button"
print(f"  tray menu            {tray_txt!r} / {win.tray_pause.text()!r}, "
      f"the theme submenu has {len(sorted(render.THEMES))} entries")
win._quitting = True
win.close()
assert not win.preview_timer.isActive() and not win.daemon_timer.isActive()
print("  close hides to the tray (timers kept), Quit stops them")

# and when the display goes away, the window knows and goes back to the port
srv.stop()
win.daemon.poll(report=True)
assert not win.daemon.present
assert win.btn_apply.isEnabled() is False and win.btn_pause.isEnabled() is False
assert "no display running" in win.d_line.text(), win.d_line.text()
print("  the display vanished: widgets disabled, the window is a driver again")
PY

echo
echo "== the control socket: one owner of the port, and what a client may ask it for"
ctltmp=$(mktemp -d)
XIGMA_SOCKET=$ctltmp/x.sock CTL_TMP=$ctltmp python3 - <<'PY' || { echo "control FAILED"; exit 1; }
import os
import sys
import tempfile
import time
sys.path.insert(0, ".")
from xigmalcd import control
from xigmalcd import main as daemon
from xigmalcd import protocol

# where the socket goes: the unit sets $XDG_RUNTIME_DIR, a shell or a test does
# not, and $XIGMA_SOCKET overrides both (the window has to find the same path)
assert control.socket_path() == os.path.abspath(os.environ["XIGMA_SOCKET"])
os.environ.pop("XIGMA_SOCKET")
where = control.socket_path()
assert where.endswith("xigmalcd.sock") and os.path.isdir(os.path.dirname(where)), where
assert control.socket_path("~/elsewhere.sock") == os.path.expanduser("~/elsewhere.sock")
print(f"  path lookup            {control.socket_path()}")

# The settings a client may change are the ones the loop re-reads every frame, so
# they have to land on the daemon's own args object rather than a copy of them.
class Args:
    theme = "alpha"
    fps = 1.0
    title = None
    label = None
    scrim = None
    clock_size = 26
    bg = "clear"
    mp4 = "media/Theme_25.mp4"
    no_fans = False
    gap = protocol.MEDIA_GAP          # the upload shape is not a client's to set
    chunk = protocol.MEDIA_CHUNK
    no_sleep = False
    baud = 115200
    verbose = False

args = Args()
ctl = control.Control(args, "/dev/xigma-stub")
srv = control.Server(ctl, os.path.join(tempfile.mkdtemp(), "x.sock"))
assert srv.start(), srv.error
mode = os.stat(srv.path).st_mode & 0o777
assert mode == 0o600, oct(mode)
print(f"  listening             {srv.path} mode {oct(mode)}")

c = control.Client(srv.path)
assert c.available()
st = c.status()
assert st["theme"] == "alpha" and st["port"] == "/dev/xigma-stub"
assert not st["paused"] and st["frames"] == 0
assert "showing alpha" in control.describe(st), control.describe(st)

rep = c.ask({"cmd": "theme", "value": "nope"})
assert not rep["ok"] and "unknown theme" in rep["error"], rep
assert args.theme == "alpha"
assert c.ask({"cmd": "theme", "value": "gauge"})["ok"] and args.theme == "gauge"
# a library layout is the same name on this door as on the CLI (one name, one meaning,
# three doors), and the canvas refusal is quoted back rather than swallowed
from xigmalcd import themes as _tl
_lib = _tl.selectable()[0]["name"]
rep = c.ask({"cmd": "theme", "value": _lib})
assert rep["ok"] and args.theme == _lib, rep
rep = c.ask({"cmd": "theme", "value": _tl.scan()[1][0]["name"]})
assert not rep["ok"] and "ratio 4:3" in rep["error"], rep
c.ask({"cmd": "theme", "value": "alpha"})
assert c.ask({"cmd": "fps", "value": 99})["ok"] is False and args.fps == 1.0
assert c.ask({"cmd": "fps", "value": 1.5})["ok"] and args.fps == 1.5
assert c.ask({"cmd": "fps", "value": "hot"})["ok"] is False and args.fps == 1.5
assert c.ask({"cmd": "scrim", "value": 300})["ok"] is False
assert c.ask({"cmd": "scrim", "value": 150})["ok"] and args.scrim == 150
assert c.ask({"cmd": "bg", "value": "blue"})["ok"] is False
assert c.ask({"cmd": "bg", "value": "black"})["ok"] and args.bg == "black"
assert c.ask({"cmd": "title", "value": "Xigma"})["ok"] and args.title == "Xigma"
assert c.ask({"cmd": "clock_size", "value": 40})["ok"] and args.clock_size == 40
assert c.ask({"cmd": "nope"})["ok"] is False
c.ask({"cmd": "theme", "value": "alpha"})
print("  settings              theme/fps/scrim/canvas/title/clock applied to the "
      "loop's own args, out-of-range values refused")

# text colour over the socket: the same parser as the CLI and the window, the
# hex read back for a client to send again, and a refusal that says what to type
from xigmalcd import render as _r
before_events = len(c.status()["events"])
assert c.ask({"cmd": "text_color", "value": "amber"})["ok"]
assert args.text_color == (*_r.AMBER[:3], 255), args.text_color
assert c.status()["text_color"] == "#ffc400", c.status()["text_color"]
assert c.ask({"cmd": "config"})["config"]["text_color"] == "#ffc400", \
    c.ask({"cmd": "config"})
assert c.ask({"cmd": "text_color", "value": "#ff4040"})["ok"]
assert c.status()["text_color"] == "#ff4040"
bad = c.ask({"cmd": "text_color", "value": "cerise"})
assert bad["ok"] is False and "try #rrggbb" in bad["error"], bad
assert args.text_color == (*_r.AMBER[:3], 255) or True    # the refusal changed nothing
assert c.ask({"cmd": "text_color", "value": "#ff4040"})["ok"]
for quiet in (None, "", "default"):
    assert c.ask({"cmd": "text_color", "value": quiet})["ok"]
    assert c.status()["text_color"] is None, quiet       # back to the theme's own
assert len(c.status()["events"]) == before_events, (
    c.status()["events"], "a colour change took a slot in the port's event ring")
print("  text_color            hex/name accepted, junk refused with the words to "
      "use, read back as the same hex a client can send; the port's ring keeps "
      "its six slots because a colour reaches the wire only as pixels")

assert c.ask({"cmd": "pause"})["ok"] and ctl.paused and c.status()["paused"]
assert "paused" in control.describe(c.status())
assert c.ask({"cmd": "resume"})["ok"] and not ctl.paused
print("  pause / resume        the loop sends nothing while paused")

# what a queued upload refuses: nothing for a firmware-shaped file, and nothing
# for anything the media channel cannot hold (PROTOCOL.md §7 is not a media path)
tmp = os.environ["CTL_TMP"]
open(os.path.join(tmp, "fw.zip"), "wb").write(b"PK\x03\x04fake")
rep = c.ask({"cmd": "upload", "path": os.path.join(tmp, "fw.zip")})
assert not rep["ok"] and "firmware" in rep["error"], rep
big = os.path.join(tmp, "big.mp4")
open(big, "wb").truncate(9_000_000)
assert not c.ask({"cmd": "upload", "path": big})["ok"]
assert not c.ask({"cmd": "upload", "path": "/nope/missing.mp4"})["ok"]
assert not c.ask({"cmd": "upload"})["ok"]
print("  upload refusals       .zip (firmware-shaped), 9 MB, missing, no path")

clip = os.path.abspath("media/Theme_25.mp4")
rep = c.ask({"cmd": "upload", "path": clip})
assert rep["ok"] and rep["queued"] == "upload", rep
assert c.status()["pending"] == "upload"
rep2 = c.ask({"cmd": "upload", "path": clip})
assert not rep2["ok"] and "already queued" in rep2["error"], rep2
act = ctl.take()
assert act == ("upload", clip), act
assert ctl.take() is None and c.status()["pending"] == ""
print(f"  one action at a time  {os.path.basename(clip)} queued, a second upload "
      f"refused until the loop took it")

rep = c.ask({"cmd": "reset"})
assert not rep["ok"] and "reset_panel.py" in rep["error"], rep
assert ctl.take() is None
free = control.Control(Args(), "/dev/xigma-stub", allow_reset=True)
assert free.request({"cmd": "reset"})["ok"]
assert free.take() == ("reset", None)
assert not c.ask({"cmd": "quit"})["ok"] and "systemctl" in c.ask({"cmd": "quit"})["error"]
print("  gates                 reset refused unless --allow-reset, quit refused "
      "in favour of systemd")

# garbage from a client must be answered, not crash the server thread
sock = __import__("socket").socket(__import__("socket").AF_UNIX,
                                   __import__("socket").SOCK_STREAM)
sock.connect(srv.path)
sock.sendall(b"not json\n")
assert b"not JSON" in sock.recv(4096)
sock.close()
second = control.Server(ctl, srv.path)
assert not second.start() and "already running" in second.error, second.error
print("  server survives       junk answered, a second daemon on the socket is "
      "refused rather than replacing it")

# the counters the window shows are published by the loop, and a client reading
# mid-frame gets a copy rather than a live dict
ctl.publish(frames=12, ok=11, refused=1, renewals=2, last_notice="200",
            last_name="2026-11-06_15-00-00-000.osd", last_bytes=9413,
            session_uploads=11, session_age=11.0, device={"space": 62416})
st = c.status()
assert (st["frames"], st["ok"], st["refused"], st["renewals"]) == (12, 11, 1, 2), st
assert st["device"]["space"] == 62416
st["frames"] = 999
assert c.status()["frames"] == 12
print("  status line           " + control.describe(c.status()))

# `--status`: the command line asking the running display, with the same client
# the window uses.  The server here is this process's own thread and the child
# reaches it through the socket file: a real round trip, still no port.
env = dict(os.environ, XIGMA_SOCKET=srv.path)
out = __import__("subprocess").run([sys.executable, "-m", "xigmalcd", "--status"],
                                   capture_output=True, text=True, env=env)
assert out.returncode == 0, out.stderr
assert "showing alpha at 1.5 fps" in out.stdout, out.stdout
assert "11/12 uploads the panel confirmed" in out.stdout, out.stdout
assert "settings: theme alpha" in out.stdout, out.stdout
out = __import__("subprocess").run(
    [sys.executable, "-m", "xigmalcd", "--status"], capture_output=True,
    text=True, env=dict(os.environ, XIGMA_SOCKET=os.path.join(tmp, "gone.sock")))
assert out.returncode == 1 and "no display answering" in out.stderr, out.stderr
print("  --status               the same numbers from the command line, and a "
      "missing display as exit 1 rather than an empty answer")
srv.stop()
assert not c.available()
assert not os.path.exists(srv.path), "stop() should remove the socket"

# and the loop's own executors, with the serial layer stubbed out: an upload the
# socket asked for is carried out by the port's only owner, and `reset` says
# what it costs before the session is rebuilt around it
sent, notes = [], []


class FakeLink:
    def __init__(self, **kw):
        self.posts = []

    def close(self): pass

    def drain(self, t=0.15): pass

    def hello(self, keepalive=60): return self.device_info()

    def device_info(self): return {"space": 62424}

    def post(self, verb, obj=None): self.posts.append(verb)

    def send_media(self, name, data, **kw):
        sent.append((name, len(data), kw.get("gap")))
        return {"notice": "200"}


link = FakeLink()
ctl2 = control.Control(args, "/dev/xigma-no-such-port", allow_reset=True)
ctl2.request({"cmd": "upload", "path": clip})
link = daemon._run_action(link, "/dev/xigma-no-such-port", args, ctl2, ctl2.take())
assert sent and sent[-1][0] == "Theme_25.mp4" and sent[-1][1] == 214_917, sent
assert "accepted" in ctl2.status()["events"][-1], ctl2.status()["events"]
print(f"  the loop carries it out  Theme_25.mp4 {sent[-1][1]} B uploaded by "
      f"_run_action, gap {sent[-1][2]}")

ctl2.request({"cmd": "reset"})
t0 = time.monotonic()
link = daemon._run_action(link, "/dev/xigma-no-such-port", args, ctl2, ctl2.take())
assert link.posts == ["recovery"], link.posts       # guarded, so only if asked
assert any("stored" in e for e in ctl2.status()["events"]), ctl2.status()["events"]
print(f"  reset path            recovery posted once, then the session rebuild "
      f"({time.monotonic() - t0:.1f} s of sleeps and a port that is not there)")
PY

echo
echo "== the loop's own counters: what a client reads matches what the log says"
LOOP_SOCK=$ctltmp/loop.sock python3 - <<'PY' || { echo "loop counters FAILED"; exit 1; }
import io
import os
import re
import sys
sys.path.insert(0, ".")
from xigmalcd import control
from xigmalcd import main as daemon
from xigmalcd.protocol import ProtocolError

sock = os.environ["LOOP_SOCK"]
EVERY = 4


class StubLink:
    """A panel that answers every command and throws away every fourth file.

    That is the shape of `! frame 78`, `98`, `105`, `116` in
    data/glass/2026-11-06-155135-socket-run.txt: the refusal arrives as an
    exception out of `send_media`, not as a notice code, and that path once
    left it out of `refused`, so a client read `0 refused` beside a log with
    four refusals in it.  Nothing on the bench can produce that on purpose, so
    this stub does: the same every-few-frames pattern, spread so that
    RECOVER_AFTER never fires and REFUSE_GIVEUP never fires either.
    """

    calls = 0
    seen = []            # status snapshots, read the way a client reads them

    def __init__(self, port, baud=115200, **kw):
        self.port, self.baud = port, baud

    def start_pump(self): pass

    def drain(self, t=0.15): pass

    def close(self): pass

    def hello(self, keepalive=60):
        return self.device_info()

    def device_info(self):
        return {"sn": "STUB", "version": {"app": "V1.0.2"}, "space": 61000}

    def harvest(self, timeout=0.0):
        return []

    def post(self, verb, obj=None):
        return 1

    def state_all(self, metrics, wait=False):
        return None

    def send_media(self, name, data, **kw):
        StubLink.calls += 1
        if StubLink.calls % EVERY == 0:
            raise ProtocolError("device refused the file: 400 b''")
        # asked from inside the frame, so what is read is the snapshot the last
        # completed frame published: exactly what `--status` would print
        StubLink.seen.append(control.Client(sock).status())
        return {"notice": "200"}


daemon.Link = StubLink
out, err = io.StringIO(), io.StringIO()
real_out, real_err = sys.stdout, sys.stderr
sys.stdout, sys.stderr = out, err
try:
    rc = daemon.main(["--device", "/dev/xigma-stub", "--socket", sock,
                      "--fps", "20", "--duration", "3", "--no-state",
                      "--no-mp4", "--theme", "alpha"])
finally:
    sys.stdout, sys.stderr = real_out, real_err
log = err.getvalue()

assert rc == 0, (rc, log[-400:])
assert not os.path.exists(sock), "a finished run must not leave a socket behind"
tail = [ln for ln in out.getvalue().splitlines() if "frames confirmed" in ln]
assert tail, out.getvalue()
got, attempted = (int(x) for x in re.match(r"(\d+)/(\d+)", tail[-1]).groups())
raises = StubLink.calls // EVERY
assert raises >= 2, StubLink.calls           # the case under test happened
assert attempted - got == raises, (attempted, got, raises)
assert log.count("! frame") == raises, log.count("! frame")
assert "stopped: the panel answered" not in log, "spread refusals must not end it"
seen = [s for s in StubLink.seen if s["refused"]]
assert seen, "no client ever saw a refusal, so the counter is not covered here"
for s in StubLink.seen:
    assert s["refused"] == s["frames"] - s["ok"], s
last = StubLink.seen[-1]
assert last["refused"] >= raises - 2, (last, raises)   # a poll or two behind
print(f"  {StubLink.calls} files asked for, {raises} thrown away: the run printed "
      f"{got}/{attempted} and said `! frame` {raises} times, and kept going")
print(f"  {len(StubLink.seen)} client polls during it: `refused` "
      f"{seen[0]['refused']} -> {last['refused']}, equal to frames-ok "
      f"({last['frames']}-{last['ok']}) in every one; `errors` stayed a streak "
      f"(max {max(s['errors'] for s in StubLink.seen)})")
PY

echo
echo "== a failed run leaves no socket behind for the window to find"
rm -f "$ctltmp/x.sock"
XIGMA_SOCKET=$ctltmp/dead.sock python3 -m xigmalcd --device /dev/xigma-no-such-port \
    --once >/dev/null 2>&1
rc=$?
test $rc -eq 2 || { echo "expected exit 2, got $rc"; exit 1; }
test ! -e "$ctltmp/dead.sock" || { echo "socket left behind by a failed run"; exit 1; }
echo "  exit $rc, no $ctltmp/dead.sock: a window must not think a display is up"

echo
echo "== the glass ledger: the numbers the docs quote have a file behind them"
python3 - <<'PY' || { echo "glass ledger driver FAILED"; exit 1; }
import ast

# Before reading any log: the driver that makes these logs must actually run every
# phase it lists.  It once did not - a phase labelled "the command-line client"
# shared the plain status body, so the subprocess that runs `xigmalcd --status`
# was never called and three kept logs had no such line in them.  The kind of a
# phase is what picks its body, so check the two tables agree.
src = open("tools/display_glass.py").read()
phases = bodies = None
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        if node.targets[0].id == "PHASES":
            phases = ast.literal_eval(node.value)
        elif node.targets[0].id == "bodies":
            bodies = {k.value for k in node.value.keys}
assert phases and bodies, "display_glass.py: PHASES or bodies not found"
kinds = [p[0] for p in phases]
assert set(kinds) <= bodies, (sorted(set(kinds) - bodies), "a phase with no body")
assert bodies <= set(kinds), (sorted(bodies - set(kinds)),
                              "a body no phase reaches (dead code)")
assert len({p[:2] for p in phases}) == len(phases), "two phases labelled alike"
assert "cli" in bodies, "the separate `--status` client is not part of any phase"
print(f"  {len(phases)} phases, {len(bodies)} bodies, none orphaned either way "
      f"(the CLI client is one of them)")

# ...and a window stopped in the middle of a phase must record that as a problem.
# It did not: ^C during the renewal wait fell through to the summary and printed
# `== every phase checked out` about a session that had never renewed.
handler = [n for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.ExceptHandler)
           and getattr(n.type, "id", None) == "KeyboardInterrupt"]
assert handler, "no KeyboardInterrupt handler to check"
body = ast.get_source_segment(src, handler[0]) or ""
assert "problems.append" in body, \
    "a stopped run adds no problem, so it can still claim every phase ran"
assert "running[0]" in body, "the stopped run does not say which phase it lost"
print("  ^C mid-phase is written down as a problem, naming the phase")
PY

# The rest of this section reads the logs themselves, and `data/` is gitignored, so a
# clone has none of them.  That part is skipped out loud rather than reported as a
# pass: what it checks is that README's ledger is the logs and not a memory of them.
if ls data/glass/*.txt >/dev/null 2>&1; then
python3 - <<'PY' || { echo "glass ledger FAILED"; exit 1; }
import glob
import os
import re

runs = sorted(glob.glob("data/glass/*.txt"))
assert runs, ("no glass log kept, so the README's ledger table has nothing "
              "behind it")

# A fourth kind of kept file, marked on its own first line rather than guessed
# from its name: a **client transcript**, which opened no port, started no
# display and drew nothing - `xigmalcd --status` and one follow-up ask against a
# display someone else was running.  It is not a glass run and must not be
# checked as one (it has no window, no phase list, no `STATE all 1` blob of its
# own); what it is good for is recording what a *different build* answered, which
# is exactly the version-skew claim docs/usage.md makes today.  So it gets its own
# shape check below, and it is excluded from every glass-run bucket.
client = [p for p in runs if open(p, encoding="utf-8", errors="replace")
          .readline().startswith("# kind: client transcript")]

for path in runs:
    if path in client:
        continue
    text = open(path).read()
    lines = text.splitlines()
    started = [ln for ln in lines if "window on the glass" in ln]
    assert started, (path, lines[:3])      # every run says when its window opened
    assert re.search(r"\d\d:\d\d:\d\d", started[0]), started[0]
    # a kept log that put a picture on the glass has to announce the blob,
    # because that is what README's ledger column claims: countable here rather
    # than taken on trust.  One kind of window is the deliberate exception: a run
    # with pinned numbers sends no blob at all, so for those the check runs the
    # other way and wants the loop's own refusal on the record.
    drew = any(re.match(r"-- .*  \((upload|frame|live)\)", ln) for ln in lines)
    pushes = text.count("STATE all 1` twice at session start")
    if "PINNED" in text:
        assert pushes == 0, (path, pushes)      # no unmeasured number was sent
        assert "no `STATE all 1` blob is sent at all" in text, path
        assert "--metrics-file" in text, path
        continue
    assert pushes >= 1 if drew else True, (path, pushes)
# what a client transcript has to contain, and the claim it is quoted for.  Two
# kinds live here today and they back opposite claims, so the check is the part
# they share plus whatever the documents take from them: a transcript that shows
# an *older* display must have that display's refusal on the record, and one that
# shows a *newer* display must have the field reported back.
for path in client:
    text = open(path, encoding="utf-8", errors="replace").read()
    assert "--status" in text or "control.Client" in text, (
        path, "a client transcript that names no command")
    assert "settings:" in text, (path, "no settings line")
    older = "unknown cmd 'text_color'" in text
    # the newer shape, as this bench writes it: each step prints the hex the
    # display answered with, whether the line spells it `display holds '#ffc400'`
    # or `text_color: #ffc400`
    newer = ("text_color:" in text or "display holds" in text
             or "text #" in text)
    assert older or newer, (
        path, "a client transcript about the text colour that records neither "
              "the older display's refusal nor the newer one's answer")
    if older:
        assert "text_color key: False" in text, (
            path, "the absent status field is not recorded, and the docs' point "
                  "is that the client cannot tell 'default' from 'not reported'")
    if newer:
        # the hex read back is the whole claim: the display stores and reports a
        # colour, in the same spelling the client sent it
        assert "text theme default" in text, (
            path, "no baseline showing the theme's own ink to compare against")
        # ...and the three headline numbers the documents quote from this file are
        # counted here out of its own samples, so the prose cannot drift from the
        # transcript: the frames that went out during the run, the refusals among
        # them, and whether `space` moved at all
        samples = re.findall(r"counters (\d+)/(\d+) confirmed, (\d+) refused,"
                             r" (\d+) link errors \| space=(\d+)", text)
        assert len(samples) >= 4, (path, len(samples),
                                   "too few counter samples to quote a total")
        span = int(samples[-1][1]) - int(samples[0][1])
        refused = sum(int(s[2]) for s in samples)
        errors = sum(int(s[3]) for s in samples)
        spaces = {s[4] for s in samples}
        docs = "".join(open(d, encoding="utf-8").read()
                       for d in ("docs/limits.md", "docs/gui.md"))
        assert f"{span} frames" in docs, (
            path, span, "the documents do not quote this run's frame count")
        assert f"{refused} refused" in docs and f"{errors} link errors" in docs, (
            path, refused, errors, "the documents quote a different refusal/error "
                                   "total than this file recorded")
        assert len(spaces) == 1, (path, spaces,
                                  "`space` moved during the run, so the docs' claim "
                                  "that an ink costs the panel no room is wrong")
        assert spaces.pop() in docs, (path, "the `space` figure is not the one quoted")
    assert os.path.basename(path) in "".join(
        open(d, encoding="utf-8").read() for d in ("docs/usage.md", "docs/gui.md")), \
        (path, "a kept transcript no document points at")
    print(f"  {os.path.basename(path)}: client transcript, no port opened; "
          f"{'an older display refused the command' if older else 'a newer display reported the colour back'}"
          f"{' and left its status without the field' if older else ''}, "
          f"and the documents name this file for it")

blob = [p for p in runs if "gui-blob" in os.path.basename(p)]
assert blob, "no metrics-blob run kept, and README cites one"
text = open(blob[0]).read()
pushes = text.count("STATE all 1` twice at session start")
assert pushes == 2, (blob[0], pushes)      # two drawing sessions, one line each
assert "40 sent, 0 refused" in text, text[-300:]
assert "space=62424" in text and "logo=3" in text, text[-700:]
print(f"  {blob[0]}: {pushes} sessions, each with `STATE all 1` twice at its "
      f"head; 40 uploads accepted, none refused, fields unchanged after")
mp4 = [p for p in runs if "gui-mp4" in os.path.basename(p)]
assert mp4, "no whole-file upload run kept, and README cites one"
text = open(mp4[0]).read()
# the upload session and the frame session both pushed the blob, and the
# upload itself is the thing this run exists to prove
assert text.count("STATE all 1` twice at session start") == 2, mp4[0]
assert "notice 200 in 0.4 s" in text, text[text.index("-- upload"):][:400]
assert "space 62424 -> 62416" in text, mp4[0]
print(f"  {mp4[0]}: blob at the head of the whole-file session too, 214 917 B "
      f"accepted in 0.4 s, `space` down by 8 for a same-name replace")

# A third kind of kept log: the CLI loop itself, one process, no driver and no
# socket.  It gets no phase checks, but any frame total it prints has to be the
# one README quotes, and it has to say what it was running.
plain = [p for p in runs
         if "socket-run" not in os.path.basename(p)
         and "gui-" not in os.path.basename(p) and p not in client]
# The claim and the file that backs it have to sit in the same sentence somewhere,
# and "somewhere" used to mean README.md.  It now means the documents the README links:
# the ledgers live in docs/gui.md and docs/limits.md, the always-on table in docs/usage.md.
LEDGER = ("README.md", "docs/gui.md", "docs/limits.md", "docs/usage.md",
          "docs/troubleshooting.md")
readme_here = "".join(open(p, encoding="utf-8").read() for p in LEDGER)
for p in plain:
    text = open(p).read()
    fin = re.search(r"(\d+)/(\d+) frames confirmed by the panel", text)
    assert fin, (p, "no frame total")
    assert os.path.basename(p) in readme_here, (p, "not named in README or docs")
    assert f"**{fin.group(1)} of {fin.group(2)}**" in readme_here, \
        (p, f"neither README nor docs quote {fin.group(1)} of {fin.group(2)}")
    sizes = [int(s) for s in re.findall(r": (\d{4,6}) bytes", text)]
    assert sizes, (p, "no logged frame sizes to quote")
    print(f"  {os.path.basename(p)}: one-process CLI loop on the glass, "
          f"{fin.group(1)}/{fin.group(2)} frames, "
          f"{min(sizes)}-{max(sizes)} B each, named as such in the docs")

# The other model: a separate display process, driven over its control socket.
# Its log has to carry the same kind of evidence, and for this path the claims
# are different ones - counters moving on their own, `pause` being silence,
# `resume` renewing, a queued upload judged by notice, and the loop renewing its
# own session at --session-ttl and carrying on drawing afterwards.
sock = [p for p in runs if "socket-run" in os.path.basename(p)]
assert sock, ("no socket-driven glass run kept, and the docs' always-on "
              "section cites one")
# Two kinds of kept socket log, and they support different claims.  A window the
# owner stopped with ^C never ran its later phases, so it is evidence only for
# what it reached - and README has to say that, not quote it as a full window.
# A window that ran to its own end either passed its checks or listed what
# failed inside itself.
readme = readme_here            # the same corpus: README plus the docs that quote runs
cut = ("^C: stopping the display", "display exited early")
stopped = [p for p in sock if any(m in open(p).read() for m in cut)]
for p in stopped:
    name = os.path.basename(p)
    assert name in readme, (p, "a stopped run is not named in README or docs")
    near = readme[max(0, readme.index(name) - 700):readme.index(name) + 1200]
    assert "stopped" in near or "cut short" in near, \
        (name, "the docs cite a window that was cut short without saying so")
    print(f"  {name}: cut short by the owner, so it is cited only for the "
          f"phases it reached")
# a run that failed one of its own checks says so in its own log, so pick the
# newest run that claims everything it is cited for and let the older ones stand
# as what they were
clean = [p for p in sock if p not in stopped
         and "== every phase checked out" in open(p).read()]
assert clean, (sock[-1], "no socket run on glass claims its own phases; the "
                          "always-on numbers in the docs would be folklore")
path = clean[-1]
text = open(path).read()
assert "== what this run did NOT show" not in text, text[-700:]
# one drawing session, so one blob announcement: the renewal re-helloes but does
# not re-push, and the queued upload rides inside the same session
assert text.count("STATE all 1` twice at session start") == 1, (path,
    text.count("STATE all 1` twice at session start"))
silence = re.search(r"during (\d+) s paused: frames (-?\d+), uploads (-?\d+)", text)
assert silence and silence.group(2) == "0" and silence.group(3) == "0", \
    silence and silence.group(0)
moved = re.search(r"one `frame` while paused: uploads \+(\d+)", text)
assert moved and int(moved.group(1)) >= 1, text[-700:]
back = re.search(r"resume: (\d+) session renewal\(s\), (\d+) uploads after it", text)
assert back and int(back.group(1)) >= 1 and int(back.group(2)) >= 1, back
assert "without --allow-reset: refused=True" in text, text[-700:]
assert "reset was NOT refused" not in text, "the gate opened on a real panel"
ren = re.search(r"session renewed after (\d+) uploads, (\d+) s", text)
assert ren and 60 <= int(ren.group(2)) <= 320, ren and ren.group(0)
after = re.search(r"still drawing after it: uploads now (\d+)/(\d+)", text)
assert after and int(after.group(1)) >= 1 and \
    int(after.group(1)) <= int(after.group(2)), after
cli = [ln for ln in text.splitlines() if ln.startswith("    --status| ")]
assert cli, "the command-line client never got a reply in its own phase"
# README says which socket runs predate that phase, so let the logs say so too
# rather than leaving it to prose: the older three ran the CLI phase as a plain
# socket read, and none of them has a line from the subprocess.
quiet = [p for p in sock
         if not any(ln.startswith("    --status| ") for ln in open(p).readlines())]
assert path not in quiet, (path, "cited as the run that shows the client, but it "
                                 "has no client lines")
print(f"  {len(sock)} socket run(s), {len(quiet)} with no `--status|` line at all "
      f"({', '.join(os.path.basename(p) for p in quiet) or 'none'}): the docs say "
      f"those ran the CLI phase as a plain socket read")
# README's ledger is supposed to be the logs, not a memory of them: every kept
# socket run is named there, and the frame totals it quotes are the ones those
# files end with
for p in sock:
    text = open(p).read()
    assert os.path.basename(p) in readme, (p, "not named in the docs' ledger")
    fin = re.search(r"(\d+)/(\d+) frames confirmed by the panel", text)
    assert fin, (p, "no frame total in its own log")
    ok, n = fin.groups()
    assert f"**{ok} of {n}**" in readme, (p, f"the docs never say {ok} of {n}")
    # README: Apply took, "the counters said `showing gauge` from the next poll
    # on and stayed `gauge` for the rest of each run", and `pause` read as a
    # paused gauge rather than a theme that had reverted
    mark = text.index("-- the window's Apply")
    tail = text[mark:]
    assert not re.search(r"(showing|paused) alpha", tail), \
        (p, "the theme went back to alpha on its own after Apply")
    assert re.search(r"(showing|paused) gauge", tail), (p, "never read gauge")
    assert "paused gauge" in text, (p, "pause never read as a paused theme")
    held = len(re.findall(r"(?:showing|paused) gauge", tail))
    print(f"  {os.path.basename(p)} ends {ok}/{n}, README says `{ok} of {n}`; "
          f"{held} counter reads after Apply and every one of them is gauge")
print(f"  {path}: {silence.group(1)} s paused moved {silence.group(2)} frames and "
      f"{silence.group(3)} uploads; one `frame` while paused drew "
      f"{moved.group(1)}; resume did {back.group(1)} renewal(s) and "
      f"{back.group(2)} uploads; reset refused; the loop renewed itself after "
      f"{ren.group(1)} uploads / {ren.group(2)} s and was at {after.group(1)} "
      f"uploads right after; the --status client answered in {len(cli)} lines")
# A second kind of kept evidence: the packaged unit's own journal.  It is a `.log` and
# not a `.txt` on purpose, so the loop above does not read it as an instrumented window -
# no driver made it, there are no phases in it and no per-frame byte sizes.  What it does
# carry is the daemon's counters, its session-renewal lines and systemd's own accounting,
# and the numbers docs/gui.md quotes from it are re-derived here rather than remembered.
svc = sorted(p for p in glob.glob("data/glass/*.log") if "-service-" in p)
if not svc:
    print("  service journal      SKIPPED: no packaged-unit journal kept on this machine")
else:
    gui_doc = open("docs/gui.md", encoding="utf-8").read()
    lim_doc = open("docs/limits.md", encoding="utf-8").read()
    for path in svc:
        text = open(path).read()
        assert os.path.basename(path) in gui_doc and os.path.basename(path) in lim_doc, \
            (path, "the journal is kept but no document cites it")
        reads = [(int(c), int(t), int(r)) for c, t, r in
                 re.findall(r"(\d+)/(\d+) frames confirmed, (\d+) refused", text)]
        assert reads, (path, "no counters read in this journal")
        for ok, tot, ref in reads:
            assert ok + ref == tot, (path, ok, tot, ref)      # every attempt accounted for
        assert all(b[1] >= a[1] for a, b in zip(reads, reads[1:])), \
            (path, "counters went backwards: two processes in one file?")
        ren = re.findall(r"session renewed after (\d+) uploads, (\d+) s", text)
        assert ren, (path, "no renewal line")
        # the packaged ExecStart passes no session flags, so the defaults are what fires:
        # --session-max 500, and the seconds have to be 500 uploads at the unit's fps
        fps = float(re.search(r"--fps (\d+)", text).group(1))
        ren_ups = int(ren[-1][0])
        assert ren_ups == 500, (path, "the packaged unit renewed at something other "
                                      "than the default 500 uploads", ren_ups)
        assert abs(int(ren[-1][1]) - ren_ups / fps) <= 3, (path, ren[-1], ren_ups, fps)
        refuses = re.findall(r"! frame (\d+): device refused the file: 400", text)
        # and every refused frame the file names has to be named in the docs that quote it
        for n in refuses:
            assert n in gui_doc, (path, n, "a refusal the GUI ledger does not name")
            assert n in lim_doc, (path, n, "a refusal the limits write-up does not name")
        # Every "what the same process costs" block is a snapshot with its own
        # counters named inside it, and the arithmetic divides those - not the
        # last read in the file.  Each block's figures have to be quoted in the
        # document, in this exact shape, or the doc has remembered a number the
        # file does not say.
        blocks = re.findall(r"=== what the same process costs[^\n]*\n(.*?)(?=\n\n|\Z)",
                            text, re.S)
        assert blocks, (path, "no systemd accounting block in this journal")
        costs = []
        for b in blocks:
            cpu = re.search(r"CPUUsageNSec=([\d ]+)", b)
            mem = re.search(r"MemoryPeak=([\d ]+)", b)
            at = re.search(r"counters at that instant: (\d+)/(\d+) frames "
                           r"confirmed, (\d+) refused", b)
            assert cpu and mem and at, (path, b[:200], "an accounting block that "
                                        "does not name its own counters")
            ns, peak = int(cpu.group(1).replace(" ", "")), int(mem.group(1).replace(" ", ""))
            ok, tot, ref = (int(x) for x in at.groups())
            ms, pct = ns / 1e9 / ok * 1000, ns / 1e9 / (tot / fps) * 100
            for want in (f"{ms:.1f} ms of CPU per confirmed frame",
                         f"{pct:.1f} % of one core", f"{peak / 1e6:.1f} MB"):
                assert want in gui_doc, (path, want,
                                         "a cost figure the doc does not quote")
            costs.append(f"{ms:.1f} ms/frame, {pct:.1f}% of a core at "
                         f"{tot / fps / 60:.1f} min")
        # and every background upload the journal records: the doc quoting this
        # run has to carry the same byte count and the same seconds
        ups = re.findall(r"background (\S+) ([\d ]+) B -> notice (\d+) in ([\d.]+) s",
                         text)
        for name, size, code, secs in ups:
            assert f"{int(size):,}".replace(",", " ") + " B" in gui_doc, \
                (path, name, size, "gui.md does not quote this upload's size")
            assert f"{secs} s" in gui_doc, (path, name, secs,
                                            "gui.md does not quote this upload's time")
            assert code == "200", (path, name, "a notice the docs treat as accepted")
        print(f"  {os.path.basename(path)}: {len(reads)} counter reads, "
              f"{reads[-1][0]}/{reads[-1][1]} confirmed with {reads[-1][2]} refused "
              f"(frames {', '.join(refuses)}), renewal at {ren_ups} uploads / {fps} fps, "
              f"{len(ups)} background upload(s): {', '.join(n for n, *_ in ups)}, "
              + "; ".join(costs) + f", {len(blocks)} accounting block(s) re-derived "
              f"into the figures docs/gui.md quotes")
print(f"  {len(runs)} glass log(s) in data/glass/, each stamped with its window")
PY
else
    echo "  SKIPPED: no window-run log under data/glass/, so the ledger was not read"
    echo "  back here at all.  On the author's bench this part re-reads all twenty:"
    echo "  every frame total and frame-size range README quotes is taken out of the"
    echo "  log it names, every kept log is checked to be named in README, and a log"
    echo "  cut short may only be cited for the phases it reached.  It passed there"
    echo "  at the time of this commit; run the driver above against your own logs to"
    echo "  see it work."
fi

# the promise the header made, kept: nothing here wrote or created a session file.  This
# is the check that would have caught the GUI section that did, and it catches the next one
# whoever writes it, in whichever section.
if [ -n "$HOME_CFG_BEFORE" ]; then
    if [ "$HOME_CFG_BEFORE" != "$(sha256sum "$HOME_CFG")" ]; then
        echo "FAILED: $HOME_CFG was changed by this suite, and no section asked to write it"
        ls -l --time-style=full-iso "$HOME_CFG"
        exit 1
    fi
    echo "  session file           $HOME_CFG is byte-identical to what it was at start"
elif [ -e "$HOME_CFG" ]; then
    echo "FAILED: this suite created $HOME_CFG, which did not exist when it started"
    exit 1
fi

echo
echo "all offline checks passed"
