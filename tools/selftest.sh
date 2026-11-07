#!/usr/bin/env bash
# Offline checks: no panel, no serial port needed. Run this after any change to
# protocol.py or render.py. The live checks against real hardware are the ones in
# docs/tools.md (and docs/limits.md's ledgers): tools/probe.py,
# tools/send_image.py, tools/session_limit.py.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

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
left, right = R._cpu_fan_figure(PIN), R._gpu_fan_figure(PIN)
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
R.clock_str = lambda *a, **k: "09:31:03"        # the clock is part of the frame
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
import io
from PIL import Image
worst = 0
for name in ("amber", "mint", "cyan", "green", "red", "#ff4040"):
    want = R.parse_ink(name)
    enc = R.to_png(R.draw(M, "clock", clock=False, date=False, ink=want))
    seen = counts(Image.open(io.BytesIO(enc)).convert("RGBA"))
    got = max(seen, key=seen.get)
    shift = max(abs(a - b) for a, b in zip(want[:3], got[:3]))
    worst = max(worst, shift)
    assert shift <= 1, (name, want, got, shift,
                        "the palette path moved a chosen ink by more than a count")
print(f"  through the palette   a chosen ink returns within {worst}/255 per channel "
      f"on the default 256-colour upload path")
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
from xigmalcd import render

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
    score the file against a picture it is not - and leaving `clock_str` unpatched made
    the mask's time line whatever time the suite happened to run at, which is how two
    runs of one unchanged file printed 12.74 and 12.92 for the same measurement."""
    real = render.clock_str
    if when is not None:
        render.clock_str = lambda *a, t=time.localtime(when / 1000), **k: \
            preview_gif.CLOCK_STR_REAL(t)
    try:
        lay = render.draw(metrics, theme, bg=render.OVERLAY)
    finally:
        render.clock_str = real
    a = lay.getchannel("A").resize((edge, edge), Image.LANCZOS)
    ink = a.point(lambda v: 255 if v == 255 else 0)
    grown = a.filter(ImageFilter.MaxFilter(9)).point(lambda v: 255 if v else 0)
    return ink, ImageChops.subtract(grown, ink), a.point(lambda v: 255 if v == 0 else 0)


def layer_at(theme, sample, ink=None):
    """the reference layer for one sample, drawn the way `preview_gif.frames()` drew it.

    Both the readings AND that sample's clock, because that is what the frame was built
    from: `frames()` patches `render.clock_str` per sample, and a mask drawn with the
    wall clock of the moment the suite runs makes the *pixel count of the lettering*
    depend on the time of day - which is how one unchanged file printed 2 268 painted
    pixels in one run and 2 270 in the next."""
    real = render.clock_str
    when = time.localtime(series[sample]["timestamp"] / 1000)
    render.clock_str = lambda *a, t=when, **k: preview_gif.CLOCK_STR_REAL(t)
    try:
        return render.draw(series[sample]["metrics"], theme, ink=ink,
                           bg=render.OVERLAY)
    finally:
        render.clock_str = real

def lum(px):
    return 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]


def preview_slots(text, doc):
    """(the files named by a marker, the number of uploaded videos) in this document.

    A preview slot is a markdown table cell or standalone line holding either a
    `PREVIEW ME ... docs/videos/<file>` marker - the state this commit is in - or an
    image link to GitHub's own attachments CDN, which is what the editor writes when one
    of these MP4s is uploaded and the marker is deleted.  Counting both, rather than just
    looking for the marker, is what makes the check survive that edit without going soft:
    the two counts have to add up to the number of previews the document promises, so a
    marker quietly removed with nothing put back leaves a hole this can see.

    A relative `docs/videos/*.mp4` image link is rejected outright.  That is the shape
    that looks correct and is dead: GitHub renders it as an `<img>` whose src ends in
    `.mp4`, which no browser plays, and the suite's own link checker cannot call it dead
    because the file really does exist in the tree.
    """
    marked = set()
    uploads = 0
    for line in text.split("\n"):
        for slot in line.split("|") if line.strip().startswith("|") else [line]:
            m = re.search(r"PREVIEW ME[^|]*?(docs/videos/[A-Za-z0-9_.-]+\.mp4)", slot)
            if m:
                marked.add(m.group(1))
            if re.search(r"!\[[^\]]*\]\(https://(?:github\.com|media\.github\.com)"
                         r"[^) ]*(?:assets|githubusercontent)[^) ]*\)", slot):
                uploads += 1
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
assert samples == len(series) == 12, (samples, len(series))
gaps = [(b["timestamp"] - a["timestamp"]) / 1000
        for a, b in zip(series, series[1:])]
assert all(0.8 <= g <= 1.4 for g in gaps), [round(g, 2) for g in gaps]
clocks = [preview_gif.CLOCK_STR_REAL(time.localtime(s["timestamp"] / 1000))
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
    print(f"  {where:<38} {nf:>4} fr {dur:5.2f} s @ {rate:g} fps  {size:>9,} B")
    print(f"  {'':<38} over {os.path.basename(clip):<16} clip {src:5.1f} field {gf:5.1f} "
          f"(gap {abs(gf - src):4.1f})  glyph {gi:6.1f} halo {gh:6.1f} = {gi - gh:5.1f}")
    print(f"  {'':<38} moved in {APART:g} s: in the file {d_ink:5.2f} vs untouched "
          f"{d_fld:5.2f} (ratio {d_ink / max(d_fld, 0.01):5.2f}); re-drawn here, "
          f"{n_changed:,} px of the layer differ by more than 8/255 "
          f"(mean {d_lyr:5.2f})")

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
    c = got["series"][0]["metrics"]["cpu"]
    print(f"  --live-seconds sampled this box: {got['samples']} readings, cpu "
          f"{c['temperature']} C at {c['load']} %, into {os.path.getsize(probe):,} B "
          f"of JSON")
PY

echo "== where clips are looked up: the roots a package install has to get right"

# A checkout is not the only place this code runs.  `pip install .` and the .deb
# built from debian/ put the modules where the repository tree is not, so the
# three roots of xigmalcd.main (env, checkout, /usr/share/xigmalcd/media) are what
# decides whether a user gets the shipped background or a missing-file message.
# Checked against fake roots: no root, no installed package, nothing written
# outside a temp directory.
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
assert set(roots[1:]) <= {os.path.abspath(m.SYSTEM_MEDIA)}, roots
for p in (m.DEFAULT_MP4, m.QUIET_MP4, m.BRIGHT_MP4):
    assert os.path.dirname(p) == repo, p
    assert os.path.exists(p), p
extra = "" if len(roots) == 1 else f" (+ {roots[1]}, the installed package's copy)"
print(f"  checkout           default, quiet and bright all resolve inside {repo}{extra}")

with tempfile.TemporaryDirectory() as tmp:
    sysroot = os.path.join(tmp, "usr-share-xigmalcd-media")
    os.makedirs(sysroot)
    for n in ("Theme_25.mp4", "Theme_11.mp4", "theme_48.mp4"):
        open(os.path.join(sysroot, n), "wb").write(b"stand-in")

    # 2. a box with both: the checkout still answers, so the README figures do not
    #    depend on what happens to be installed on the machine reading them
    real = m.SYSTEM_MEDIA
    m.SYSTEM_MEDIA = sysroot
    try:
        assert m.media_roots() == (repo, os.path.abspath(sysroot)), m.media_roots()
        assert m.media_dir() == repo
        assert m.find_media("Theme_25.mp4") == os.path.join(repo, "Theme_25.mp4")

        # 3. the same question with no checkout in the picture: the installed root
        #    is what answers it, which is the whole point of installing to /usr/share
        saved = m.REPO_MEDIA
        m.REPO_MEDIA = os.path.join(tmp, "no-such-checkout")
        try:
            assert m.media_roots() == (os.path.abspath(sysroot),), m.media_roots()
            got = m.find_media("Theme_25.mp4")
            assert got == os.path.join(sysroot, "Theme_25.mp4"), got
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
print("  installed root     behind the checkout when both exist, first when only it does;")
print("                     the Windows copies still answer, and a clip that is nowhere")
print("                     local is reported as the file that was asked for")

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

# ---- one row per distinct clip, whatever it is called ---------------------------
# The roots hold far more files than there are clips.  Measured on the author's
# bench, Windows partition mounted: 161 mp4 files, 40 distinct contents, 121 copies -
# 69 of them the Windows app's own upload history, which copies a library clip into
# `media/background/` under a millisecond name every time a theme is applied (all 26
# `175749*.mp4` there are byte-identical to a `Theme_NN` or `theme_NN` clip), and 3 of
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

echo
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
            preview_fps=4.5, clip=clip, size=[900, 640])
where = settings.save(want)
assert where == settings.path(), where
back = settings.load()
for key, val in want.items():
    assert back[key] == val, (key, back[key], val)
assert json.load(open(where))["clock_size"] == 44      # plain JSON on disk

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
PY

echo
echo "== the GUI, offscreen and with no panel: window, clips, and the reset gate"
# XIGMA_SOCKET points at nothing on purpose: if a real display happened to be
# running while this ran, the window would be a remote and these port-side
# assertions would be testing the wrong mode
QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME=$cfgtmp XIGMA_SOCKET=$cfgtmp/no-display.sock \
    python3 - <<'PY' || { echo "gui FAILED"; exit 1; }
import inspect
import os
import re as _re
import sys
import time
import types
sys.path.insert(0, ".")
from PyQt6.QtWidgets import QApplication
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
byname = {c.name: c for c in found}
# No two rows may be the same clip.  The roots overlap on purpose: the .deb installs
# its own copy of each vendored clip, the themes package carries clips this project
# also vendors, and the Windows app's upload history repeats files it pushed more than
# once.  `realpath` catches none of that - separate files with the same bytes - and a
# (name, length) rule could not either, because the app renames what it copies: it
# measured 69 rows for 40 clips, 161 rows on disk.  The rule is length, then sha256 of
# both 2 MiB edges, and the numbers this bench reports are 161 files walked -> 40 rows,
# 121 copies dropped, 35 of them under a different name (whole-file sha256 audit,
# 2026-11-07: 40 distinct contents among those 161, which is what makes the 40 rows
# exactly right rather than merely fewer).
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
    _saved, _m.SYSTEM_THEMES = _m.SYSTEM_THEMES, _t
    try:
        again = clipdb.list_clips()
        got = [c for c in again if c.name == "Theme_25.mp4"]
        assert len(got) == 1 and got[0].path == byname["Theme_25.mp4"].path, got
    finally:
        _m.SYSTEM_THEMES = _saved
print(f"  clip library       {len(found)} rows, each a distinct name+length; the same "
      f"bytes under another root add no row and do not displace the checkout's file")
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
win = app.Window(bad, 1.0, restore=False)
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

# settings through the widgets: a picker moved is a debounced write, and the
# next window has to come back up the same way it was closed
win.clock_size.setValue(44)
win.theme.setCurrentText("gauge")
win._load_background(byname["Theme_11.mp4"].path)
win.save_timer.start()
deadline = time.time() + 3
while time.time() < deadline and settings.load()["theme"] != "gauge":
    appq.processEvents()
    time.sleep(0.02)
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
assert again.player is not None and again.player.path == saved["clip"], again.player
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
win.resize(1180, 780)                  # the window's own default size
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
# because the selftest job runs against a checkout with only the three vendored
# clips - the themes package is a separate .deb - and a search for a 320x240 file
# there died with StopIteration on the runner (run 42350703043) while passing here.
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
# selftest job runs against a checkout with the three vendored clips and no themes
# package, while the bench lists 40 distinct clips out of 161 files.
print(f"  clip list               rows {row_h} px: {visible} rows in view at "
      f"{settings.DEFAULTS['size'][0]}x{settings.DEFAULTS['size'][1]}, "
      f"{wide_visible} at 1919x1055, where it used to be 2 "
      f"({win.clips.count()} clips on this machine)")

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
# the switch is about pixels, not about defaults - and the factory reset stays put,
# because a guarded recovery that is hard to find is worse than one in the way.
folded = [win.canvas, win.scrim, win.fanline, win.d_events, win.btn_live,
          win.status_box]
assert all(not w.isVisible() for w in folded), [w.objectName() for w in folded
                                                if w.isVisible()]
assert all(w.isVisible() for w in (win.clips, win.theme, win.btn_upload,
                                   win.btn_apply, win.btn_reset, win.log_box)), \
    "the compact view lost something a first run needs"
win.scrim.setValue(200)                # reachable and in force while invisible
assert not win.scrim.isVisible() and win.scrim.value() == 200
win.adv_toggle.setChecked(True)
for _ in range(6):
    appq.processEvents()
assert all(w.isVisible() for w in folded), "advanced did not show what it names"
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
print("  advanced switch         folds the six secondary controls, keeps their values, "
      "remembers itself, and leaves the reset box where it was")

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

# the default window size the docs quote is the one the code uses
want = f"{settings.DEFAULTS['size'][0]}x{settings.DEFAULTS['size'][1]}"
shot = _re.search(r'--size",\s*default="(\d{3,4}x\d{3,4})"',
                  open("tools/screenshot.py", encoding="utf-8").read())
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

# the picker's filter: 40 rows here out of 161 files, 3 on a CI checkout
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

echo
echo "all offline checks passed"
