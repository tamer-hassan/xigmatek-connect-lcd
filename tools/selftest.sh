#!/usr/bin/env bash
# Offline checks: no panel, no serial port needed. Run this after any change to
# protocol.py or render.py. The live checks against real hardware are the ones in
# README.md ("Tools"): tools/probe.py, tools/send_image.py, tools/session_limit.py.
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
echo "== where clips are looked up: the roots a package install has to get right"
# A checkout is not the only place this code runs.  `pip install .` and the .deb
# built from debian/ put the modules where the repository tree is not, so the
# three roots of xigmalcd.main (env, checkout, /usr/share/xigmalcd/media) are what
# decides whether a user gets the shipped background or a missing-file message.
# Checked against fake roots: no root, no installed package, nothing written
# outside a temp directory.
python3 - <<'PY' || { echo "clip roots FAILED"; exit 1; }
import os, shutil, sys, tempfile
sys.path.insert(0, ".")
from xigmalcd import main as m

# 1. in a checkout: the repository's own media/ is the root, and all three shipped
#    clips resolve inside it - which is what every clip number in README reads
repo = os.path.abspath(m.REPO_MEDIA)
assert m.media_roots() == (repo,), m.media_roots()
for p in (m.DEFAULT_MP4, m.QUIET_MP4, m.BRIGHT_MP4):
    assert os.path.dirname(p) == repo, p
    assert os.path.exists(p), p
print(f"  checkout           default, quiet and bright all resolve inside {repo}")

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
counts = {"thm": (27, 66_300_082), "layout": (27, 127_115),
          "clip": (44, 84_392_330), "foreground": (27, 407_095)}
for kind, (files, byte_total) in counts.items():
    rows = [e for e in man["files"] if e["kind"] == kind]
    assert len(rows) == files, (kind, len(rows), files)
    assert sum(e["bytes"] for e in rows) == byte_total, (kind,)
    print(f"  {kind:<10} {files:>3} files {byte_total:>10} B as documented")
# the dedup the README states: every theme background lives in clips/, none duplicated
themes = man["themes"]
assert len(themes) == 27, len(themes)
assert all(t["backgroundFile"].startswith("clips/") for t in themes)
assert not os.path.exists("themes/alpha/background"), "a background/ dir should not exist"
print(f"  27 themes, all 27 background payloads held by clips/, no background/ dir")
# the three clips vendored at the repo root are the vendor's, twice over
for f in ("Theme_11.mp4", "Theme_25.mp4", "theme_48.mp4"):
    a = hashlib.sha256(open(f"media/{f}", "rb").read()).hexdigest()
    b = hashlib.sha256(open(f"themes/alpha/clips/{f}", "rb").read()).hexdigest()
    assert a == b, (f, a[:12], b[:12])
    print(f"  media/{f} == themes/alpha/clips/{f}  {a[:16]}")
# the contact sheets the README links, at the size the README says they are
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

if shutil.which("desktop-file-validate"):
    subprocess.run(["desktop-file-validate", "debian/xigmaui.desktop"], check=True)
    print("  desktop-file-validate  clean on the installed form too")
else:
    print("  desktop-file-validate  not installed here: SKIPPED on the installed "
          "form (CI installs it as a Build-Depend)")
PY

echo
echo "== the GUI, offscreen and with no panel: window, clips, and the reset gate"
# XIGMA_SOCKET points at nothing on purpose: if a real display happened to be
# running while this ran, the window would be a remote and these port-side
# assertions would be testing the wrong mode
QT_QPA_PLATFORM=offscreen XDG_CONFIG_HOME=$cfgtmp XIGMA_SOCKET=$cfgtmp/no-display.sock \
    python3 - <<'PY' || { echo "gui FAILED"; exit 1; }
import inspect
import sys
import time
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
          f"from the clips, and the assertion below compares them to README's numbers")
    raise SystemExit(1)
found = clipdb.list_clips()
assert found, "no clips found at all"
byname = {c.name: c for c in found}
for name, size in (("Theme_25.mp4", 214_917), ("Theme_11.mp4", 3_402_098),
                   ("theme_48.mp4", 1_333_649)):
    assert byname[name].bytes == size, (name, byname[name].bytes)
    lum = clipdb.measure(byname[name])
    assert abs(lum - CLIP_LUMA[name]) < 0.6, (name, lum, CLIP_LUMA[name])
    secs = clipdb.probe(byname[name])
    assert 0.5 < secs < 20, (name, secs)
    print(f"  {name:16s} {byname[name].bytes:9d} B  luma {lum:5.1f}  "
          f"{secs:5.2f} s loop")

# the third source is the Windows app's own upload history, reachable only when
# that partition is mounted, so the assertion is conditional on it being there
byorigin: dict[str, int] = {}
for c in found:
    byorigin[c.origin] = byorigin.get(c.origin, 0) + 1
import os
from xigmalcd.main import WIN_UPLOADS
if os.path.isdir(WIN_UPLOADS):
    assert byorigin.get("app upload", 0) > 0, byorigin
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
assert 0.1 < build < 5.0, build

m = sensors.collect()
render.to_png(render.draw(m, "alpha"))            # warm the font cache


def _draw_once(m):
    t = time.perf_counter()
    render.draw(m, "alpha", bg=render.OVERLAY)
    return (time.perf_counter() - t) * 1000


draws = sorted(_draw_once(m) for _ in range(15))
mid = draws[len(draws) // 2]
assert 3.0 < mid < 60.0, mid

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
      f"README's Cost paragraph quotes these three")

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
# so this is the rule the GUI has to follow, not a nicety.
#
# Whether the blob carries the tach array is this host's own sensors, not a
# constant: xigmalcd/sensors.py:collect() leaves the whole `fans` section out when
# nothing reads, so a board with nothing wired to a tach header - or a cloud VM -
# legitimately sends the blob without it. The author's bench has a Super-IO with
# the CPU fan on it and reads (0, True); the first CI runner on 2026-11-07 read
# (0, False) and failed here. What is under test is the *placement* - twice, both
# before the first file - so the flag is derived from the same call the worker
# makes instead of pinning the bench's value.
host_fans = "fans" in sensors.collect()
assert links[-1].states == [(0, host_fans), (0, host_fans)], links[-1].states
print(f"  background upload: one file, all {len(blob)} B, gap 0.02 s, "
      f"named for the clip, `STATE all 1` twice before it "
      f"({'with' if host_fans else 'without'} this host's fan readings)")

StubLink.notice = "400"
assert worker._upload(path=mp4, gap=0.02, chunk=1000) is False
assert "refused this background" in " ".join(notes), notes[-3:]
print("  a 4xx notice is reported as a refusal, not a success")
StubLink.notice = "200"

assert worker._frame(theme="alpha", kw={"bg": render.OVERLAY}, fans=False) is True
name, size = uploads[-1][0], uploads[-1][1]
# an alpha OSD frame with the gauge rings measures 12.1-13.5 KB offline (the
# same frame without the rings measured 9.2-9.8 KB); the band below is wide
# enough to notice a regression - a re-encoded or mis-scaled frame - without
# tracking PNG trivia
assert name.endswith(".osd") and 8_000 < size < 40_000, uploads[-1]
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

assert worker._reset(confirm="reset") is True
# `_reset` opens the destructive link and then re-reads status with a normal one,
# so the check is "exactly one destructive open in the whole session, and it was
# not the first" - the source inspection above is what pins it to `_reset`
assert sum(1 for _, d in opened if d) == 1, opened
assert opened[0][1] is False and opened[-1][1] is False, opened[:2] + opened[-1:]
print(f"  reset: one destructive link in {len(opened)} opens, everything else "
      f"non-destructive")
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
assert took < 0.5, took              # six socket commands, no serial round trip
print(f"  Apply: {took * 1000:.0f} ms for six commands; the display is now "
      f"{args.theme}, clock {args.clock_size}, canvas {args.bg}, scrim auto, "
      f"fans off, {args.fps} fps")

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

# the tray is not there in this environment, and that is a supported answer
assert win.tray is None and not QSystemTrayIcon.isSystemTrayAvailable()
win.show()
qapp.processEvents()
win.tray = QSystemTrayIcon()         # what a desktop with a tray gives us
win.tray_wanted = True
win.close()
assert not win.isVisible() and win.preview_timer.isActive() and win.daemon.present
assert "hidden to the tray" in win.log_view.text()
assert looked == [], looked          # hiding never touches the port
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
echo "== the glass ledger: the numbers README quotes have a file behind them"
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
for path in runs:
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
         and "gui-" not in os.path.basename(p)]
readme_here = open("README.md").read()
for p in plain:
    text = open(p).read()
    fin = re.search(r"(\d+)/(\d+) frames confirmed by the panel", text)
    assert fin, (p, "no frame total")
    assert os.path.basename(p) in readme_here, (p, "not named in README")
    assert f"**{fin.group(1)} of {fin.group(2)}**" in readme_here, \
        (p, f"README never quotes {fin.group(1)} of {fin.group(2)}")
    sizes = [int(s) for s in re.findall(r": (\d{4,6}) bytes", text)]
    assert sizes, (p, "no logged frame sizes to quote")
    print(f"  {os.path.basename(p)}: one-process CLI loop on the glass, "
          f"{fin.group(1)}/{fin.group(2)} frames, "
          f"{min(sizes)}-{max(sizes)} B each, named as such in README")

# The other model: a separate display process, driven over its control socket.
# Its log has to carry the same kind of evidence, and for this path the claims
# are different ones - counters moving on their own, `pause` being silence,
# `resume` renewing, a queued upload judged by notice, and the loop renewing its
# own session at --session-ttl and carrying on drawing afterwards.
sock = [p for p in runs if "socket-run" in os.path.basename(p)]
assert sock, "no socket-driven glass run kept, and README's always-on section cites one"
# Two kinds of kept socket log, and they support different claims.  A window the
# owner stopped with ^C never ran its later phases, so it is evidence only for
# what it reached - and README has to say that, not quote it as a full window.
# A window that ran to its own end either passed its checks or listed what
# failed inside itself.
readme = open("README.md").read()
cut = ("^C: stopping the display", "display exited early")
stopped = [p for p in sock if any(m in open(p).read() for m in cut)]
for p in stopped:
    name = os.path.basename(p)
    assert name in readme, (p, "a stopped run is not named in README")
    near = readme[max(0, readme.index(name) - 700):readme.index(name) + 1200]
    assert "stopped" in near or "cut short" in near, \
        (name, "README cites a window that was cut short without saying so")
    print(f"  {name}: cut short by the owner, so it is cited only for the "
          f"phases it reached")
# a run that failed one of its own checks says so in its own log, so pick the
# newest run that claims everything it is cited for and let the older ones stand
# as what they were
clean = [p for p in sock if p not in stopped
         and "== every phase checked out" in open(p).read()]
assert clean, (sock[-1], "no socket run on glass claims its own phases; the "
                          "always-on numbers in README would be folklore")
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
      f"({', '.join(os.path.basename(p) for p in quiet) or 'none'}): README says "
      f"those ran the CLI phase as a plain socket read")
# README's ledger is supposed to be the logs, not a memory of them: every kept
# socket run is named there, and the frame totals it quotes are the ones those
# files end with
for p in sock:
    text = open(p).read()
    assert os.path.basename(p) in readme, (p, "not named in README's ledger")
    fin = re.search(r"(\d+)/(\d+) frames confirmed by the panel", text)
    assert fin, (p, "no frame total in its own log")
    ok, n = fin.groups()
    assert f"**{ok} of {n}**" in readme, (p, f"README never says {ok} of {n}")
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
