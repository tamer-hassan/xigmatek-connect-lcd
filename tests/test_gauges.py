#!/usr/bin/env python3
"""Gauges and lines: a meter whose ring stays out of its way, and text that lands on the glass.

Ported from `tools/selftest.sh`'s legibility and alpha-gauge sections.

Three kinds of claim live here, and they are kept apart on purpose:

* **colour and geometry from constants** - the two rings do not overlap, ink never lands on the
  stroke, a missing reading paints nothing, 40 °C ends green and 95 °C ends red.  These answer the
  same way on every machine, so they are asserted exactly.
* **the same over a real clip** - the ring audit needs a decoded frame of `Theme_30.mp4`, so it
  needs ffmpeg and says so when it does not have it.  The comparison is a ratio (how much better
  the neutral track separates fill from track than the pale default did), not an absolute luma,
  because the absolute belongs to the clip and its frame.
* **a negative control** - the readings line at the old fixed font size still provably reaches both
  canvas edges, so the "before" figure this file keeps quoting stays checkable instead of becoming
  a story.
"""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
import unittest
from PIL import Image

from tests import fixtures

from xigmalcd import render as R

DARK = os.path.join("themes", "alpha", "clips", "Theme_30.mp4")   # mean luma 4.0 of 255

#: dual gauge, cold 30 hot 90: one ring mid-sweep, one low
DUAL = {"cpu": {"temperature": 71.0}, "gpu": {"temperature": 44.0},
        "memory": {"used": 85332, "total": 126157}}
FANS = {"cpu": {"temperature": 57.0, "load": 42.0},
        "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
        "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 2400}]}
WORST_CLOCK = {"cpu": {"temperature": 100.0}, "gpu": {"temperature": 100.0},
               "fans": [{"name": "Fan CPU", "type": "Fan", "onBoard": True,
                         "value": 12345}]}
PINNED_CLOCK = {"cpu": {"temperature": 57.0}, "gpu": {"temperature": 47.0},
                "fans": [{"name": "Fan CPU", "type": "Fan", "onBoard": True,
                          "value": 1957}]}
BANDS = {"time": (150, 240), "date": (270, 310), "readings": (335, 380)}


def luma(px) -> float:
    return 0.2126 * px[0] + 0.7152 * px[1] + 0.0722 * px[2]


def ring_halves(comp, cx, cy, r, frac, start=120, sweep=300, samples=240) -> tuple:
    """(mean luma of the filled part, mean luma of the unfilled part) of one ring."""
    fill, track = [], []
    for i in range(samples):
        angle = math.radians(start + sweep * i / (samples - 1))
        px = comp.getpixel((int(round(cx + r * math.cos(angle))),
                            int(round(cy + r * math.sin(angle)))))
        (fill if i < samples * frac else track).append(luma(px))
    return sum(fill) / len(fill), sum(track) / len(track)


def mid_frame(clip: str, tmp: str) -> Image.Image:
    duration = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                               "-show_entries", "format=duration", "-of", "csv=p=0", clip],
                              check=True, capture_output=True).stdout.decode().strip()
    out = os.path.join(tmp, "f.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{float(duration) / 2:.3f}",
                    "-i", clip, "-frames:v", "1", out], check=True)
    with Image.open(out) as im:
        return im.convert("RGBA").resize((480, 480), Image.LANCZOS)


def dual_over(background: Image.Image, track: tuple) -> Image.Image:
    """Draw `dual` with `track` forced into the ring call.

    Forced, not defaulted: `theme_dual` now passes a track itself, so a `setdefault` here would
    leave the new value in place and measure the same thing twice.
    """
    real = R.gauge

    def patched(img, *a, **kw):
        kw["track"] = track
        return real(img, *a, **kw)

    R.gauge = patched
    try:
        return Image.alpha_composite(background, R.draw(DUAL, "dual", bg=R.OVERLAY))
    finally:
        R.gauge = real


class RingOverAClip(unittest.TestCase):
    """The ring is still drawn; it just no longer out-shouts the fill it sits on."""

    CLIP = os.path.join(fixtures.REPO, DARK)

    def test_the_neutral_track_separates_a_meter_from_its_ring_by_at_least_4x(self):
        fixtures.need("ffmpeg", "ffprobe")
        if not os.path.exists(self.CLIP):
            self.skipTest(f"no {DARK} in this checkout")
        with tempfile.TemporaryDirectory() as tmp:
            bg = mid_frame(self.CLIP, tmp)
            spans = (30.0, 90.0)
            rows = {}
            for label, track in (("now", R.ARC_TRACK), ("before", R.TRACK)):
                comp = dual_over(bg, track)
                cpu = ring_halves(comp, 128, 228, 86, (71.0 - spans[0]) / (spans[1] - spans[0]))
                gpu = ring_halves(comp, 352, 228, 86, (44.0 - spans[0]) / (spans[1] - spans[0]))
                rows[label] = (cpu, gpu)
            gap_now = min(abs(rows["now"][0][0] - rows["now"][0][1]),
                          abs(rows["now"][1][0] - rows["now"][1][1]))
            gap_was = max(abs(rows["before"][0][0] - rows["before"][0][1]),
                          abs(rows["before"][1][0] - rows["before"][1][1]))
            self.assertGreaterEqual(gap_now, 4 * gap_was,
                                    f"the neutral track manages {gap_now:.1f} luma of "
                                    f"separation where the pale default managed {gap_was:.1f}")

    def test_the_track_colour_itself_is_dark_and_semi_transparent(self):
        """A track that is opaque or light would be a second meter, not a track."""
        self.assertLess(R.ARC_TRACK[0], 150)
        self.assertLess(R.ARC_TRACK[3], 255)


class ClockLinesFit(unittest.TestCase):
    """Every line the clock theme draws has to land inside the panel.

    Counted by drawing the string and reading the alpha bbox, which is what the panel would show:
    a clipped glyph is a clipped glyph.  The crop makes it a per-line check rather than a
    whole-picture one - the theme used to fit only its big time line.
    """

    def band_box(self, layout: Image.Image, y0: int, y1: int):
        with layout.getchannel("A").crop((0, y0, layout.width, y1)) as band:
            return band.getbbox()

    def test_each_line_draws_something_and_none_of_it_touches_an_edge(self):
        for label, body in (("pinned readings", PINNED_CLOCK), ("worst realistic", WORST_CLOCK)):
            lay = R.draw(body, "clock", bg=R.OVERLAY).convert("RGBA")
            for band, (y0, y1) in BANDS.items():
                    with self.subTest(readings=label, line=band):
                        box = self.band_box(lay, y0, y1)
                        self.assertIsNotNone(box, f"a line this theme should draw drew "
                                                  f"nothing: {label} / {band}")
                        self.assertGreater(box[0], 0, "ink touches or crosses a panel edge")
                        self.assertLess(box[2], 480, "ink touches or crosses a panel edge")

    def test_the_old_fixed_size_still_provably_overflowed(self):
        """The before figure, kept checkable rather than remembered: that line at font 26, drawn
        centred, was clipped at each end."""
        line = "CPU 100°C    GPU 100°C    12345 RPM"
        with Image.new("RGBA", (R.W * R.SS, R.H * R.SS), (0, 0, 0, 0)) as one:
            R._text(one, (240, 358), line, R.font(26, True), R.CYAN)
            box = one.getchannel("A").getbbox()
        self.assertEqual(box[0], 0, box)
        self.assertEqual(box[2], R.W * R.SS, box)


class AlphaGaugeGeometry(unittest.TestCase):
    """Two rings, and text that may never land on a stroke."""

    CANVAS = None
    R_IN = R.A26_RING_R - R.A26_RING_W
    ARC = (R.A26_ARC_START, R.A26_ARC_SWEEP)

    @classmethod
    def setUpClass(cls):
        cls.CANVAS = Image.new("RGBA", (R.W * R.SS, R.H * R.SS), R.OVERLAY)

    def fit(self, strings, y, ceiling, bold=True) -> tuple:
        """Largest joint size for `strings`, and how far its ink ends up from the stroke
        (negative means clear of it, which is what every text block needs)."""
        size = R._fit_arc(self.CANVAS, strings, R.A26_TCOL_X[0], R.A26_RING_Y, y, self.R_IN,
                          R.A26_RING_R, *self.ARC, ceiling)
        worst = max(R.arc_clear(R.ink_box(self.CANVAS, s, R.font(size, bold), cx, y),
                                cx, R.A26_RING_Y, self.R_IN, R.A26_RING_R, *self.ARC)
                    for s in strings for cx in R.A26_TCOL_X)
        return size, worst

    def ring_pixels(self, pic, cx) -> int:
        """Samples painted along the middle of the stroke for one column."""
        mid = R.A26_RING_R - R.A26_RING_W / 2
        q = pic.convert("RGBA").load()
        hits = 0
        for i in range(161):
            angle = math.radians(R.A26_ARC_START + R.A26_ARC_SWEEP * i / 160)
            x = int(round(cx + mid * math.cos(angle)))
            y = int(round(R.A26_RING_Y + mid * math.sin(angle)))
            hits += 1 if q[x, y][3] else 0
        return hits

    def tip(self, pic, cx) -> tuple:
        """Colour at the tip of the arc for whatever that column is showing."""
        temp = (pic["cpu" if cx == R.A26_TCOL_X[0] else "gpu"])["temperature"]
        frac = ((min(max(temp, R.A26_ARC_LO), R.A26_ARC_HI) - R.A26_ARC_LO)
                / (R.A26_ARC_HI - R.A26_ARC_LO))
        angle = math.radians(R.A26_ARC_START + R.A26_ARC_SWEEP * frac)
        mid = R.A26_RING_R - R.A26_RING_W / 2
        frame = R.draw(pic, "alpha", bg=R.OVERLAY).convert("RGBA")
        return frame.load()[int(round(cx + mid * math.cos(angle))),
                            int(round(R.A26_RING_Y + mid * math.sin(angle)))]

    def test_two_equal_rings_inside_the_canvas_and_not_overlapping(self):
        self.assertEqual(len(set(R.A26_TCOL_X)), 2, R.A26_TCOL_X)
        for x in R.A26_TCOL_X:
            self.assertGreaterEqual(x, R.A26_RING_R)
            self.assertLessEqual(x, R.W - R.A26_RING_R)
        self.assertGreater(R.A26_TCOL_X[1] - R.A26_RING_R, R.A26_TCOL_X[0] + R.A26_RING_R,
                           "the two gauge rings overlap")

    def test_the_joint_rule_keeps_both_columns_one_size_and_a_longer_reading_takes_both_down(self):
        label, label_clear = self.fit(("CPU TEMP", "GPU TEMP"), R.A26_TLBL_Y, R.A26_TLBL_F)
        two, two_clear = self.fit(["57°C", "47°C"], R.A26_TVAL_Y, R.A26_TVAL_F)
        three, three_clear = self.fit(["100°C", "47°C"], R.A26_TVAL_Y, R.A26_TVAL_F)
        self.assertGreater(label, 0)
        self.assertLess(label, R.A26_TLBL_F)
        self.assertLessEqual(label_clear, -3, "label ink is not clear of the stroke")
        self.assertLess(three, two, "a three-digit reading did not drag the shared size down")
        self.assertLess(two_clear, 0)
        self.assertLessEqual(three_clear, -3)

    def test_the_fan_figures_clear_the_ring_and_the_usage_block(self):
        left, right = R.cpu_fan_figure(FANS), R.gpu_fan_figure(FANS)
        self.assertIn("CPU", left)
        self.assertIn("GPU", right)
        self.assertIn("2400", left)
        self.assertIn("45%", right)
        size = max(R.A26_FAN_MIN, min(R._fit_size(self.CANVAS, s, R.A26_FAN_MAX_W,
                                                  R.A26_FAN_F, bold=False)
                                      for s in (left, right)))
        for text in (left, right):
            with self.subTest(figure=text):
                box = R.ink_box(self.CANVAS, text, R.font(size, False), R.A26_FAN_X[0],
                                R.A26_FAN_Y)
                self.assertLess(R.arc_clear(box, R.A26_TCOL_X[0], R.A26_RING_Y, self.R_IN,
                                            R.A26_RING_R, *self.ARC), 0,
                                "a fan figure landed on the ring's stroke")
                self.assertLess(box[3], 294, "a fan figure reached the usage block")
                self.assertLessEqual(box[2] - box[0], R.A26_FAN_MAX_W)

    def test_a_missing_reading_is_two_dashes_and_no_ring_at_all(self):
        self.assertEqual(R._deg(None), "--°C")
        im = R.draw({"cpu": {"temperature": None}, "gpu": {"temperature": None}},
                    "alpha", bg=R.OVERLAY).convert("RGBA")
        for cx in R.A26_TCOL_X:
            with self.subTest(x=cx):
                self.assertEqual(self.ring_pixels(im, cx), 0,
                                 "a column with no temperature painted part of a ring")

    def test_the_tip_colour_carries_the_value(self):
        """40 °C ends green, 95 °C ends red, and neither is the neutral track colour."""
        cool = self.tip({"cpu": {"temperature": 40.0}}, R.A26_TCOL_X[0])
        warm = self.tip({"cpu": {"temperature": 95.0}}, R.A26_TCOL_X[0])
        self.assertTrue(cool[3] and warm[3], (cool, warm))
        self.assertNotEqual(cool[:3], warm[:3])
        self.assertGreater(cool[1], cool[0], f"40 °C tip {cool[:3]} is not green-ish")
        self.assertGreater(warm[0], warm[1], f"95 °C tip {warm[:3]} is not red-ish")
        self.assertNotIn((cool[:3], warm[:3]), [(R.A26_ARC_TRACK[:3],) * 2])

    def test_the_three_ramp_stops_and_the_clamps_at_both_ends(self):
        span = (R.A26_ARC_LO, R.A26_ARC_MID, R.A26_ARC_HI)
        self.assertEqual(R.temp_colour(R.A26_ARC_LO, *span)[:3], R.GREEN[:3])
        self.assertEqual(R.temp_colour(R.A26_ARC_MID, *span)[:3], R.AMBER[:3])
        self.assertEqual(R.temp_colour(R.A26_ARC_HI, *span)[:3], R.RED[:3])
        self.assertEqual(R.temp_colour(200, *span)[:3], R.RED[:3], "clamped with the tip")
        self.assertEqual(R.temp_colour(0, *span)[:3], R.GREEN[:3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
