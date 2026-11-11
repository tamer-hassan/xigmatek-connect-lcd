#!/usr/bin/env python3
"""The PNG the panel is given: the encoder's loss budget, and the switches that choose it.

Ported from `tools/selftest.sh`'s renders section.  The decision these checks hold is a measured
one, made in the order it was made: the indexed 256-colour PNG is what every canvas uploads through
`xigmaui/panel.py`, `--truecolor` asks for 8-bit RGBA instead, and indexed is **not exact** - these
checks say by how much, in both channels, so the choice stays a number rather than a preference.

The frame is the alpha overlay over a transparent canvas, drawn with the readings body from the
Windows captures (kept here as its own constant, not the general fixture: this is the body whose
frames were replayed against PROTOCOL.md, and the numbers below are quoted from that picture).
"""
from __future__ import annotations

import io
import math
import os
import subprocess
import sys
import tempfile
import unittest
from PIL import Image, ImageChops

from tests import fixtures

from xigmalcd import render

CAPTURED = {"cpu": {"temperature": 57.0, "load": 42.0},
            "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
            "fans": [{"name": "Fan CPU", "type": "Fan", "value": 1957}]}

STEP = 0.2                                    # degrees between samples along the arc
RAMP_R = render.A26_RING_R - 6                # mid-radius of the 12 px stroke


class DryRun(unittest.TestCase):
    """Every theme, through the real command line, with the dry-run door that guarantees no port."""

    def test_each_theme_writes_a_480x480_frame(self):
        for theme in fixtures.THEMES:
            with self.subTest(theme=theme), tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, theme)
                got = fixtures.run(sys.executable, "-m", "xigmalcd", "--dry-run", out,
                                   "--once", "--theme", theme)
                self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
                path = os.path.join(out, "frame0000.png")
                self.assertTrue(os.path.isfile(path), got.stdout + got.stderr)
                with Image.open(path) as im:
                    self.assertEqual(im.size, (480, 480))


class LossBudget(unittest.TestCase):
    """What the 256-colour path costs, counted in pixels and in per-channel distance."""

    @classmethod
    def setUpClass(cls):
        cls.frame = render.draw(CAPTURED, "alpha", bg=render.OVERLAY)
        assert cls.frame.mode == "RGBA"
        assert cls.frame.getchannel("A").getextrema() == (0, 255), "not an overlay frame"

    def offset_against_the_drawn_frame(self, blob: bytes) -> tuple:
        """(bytes, pixels whose alpha moved, worst alpha move, pixels whose colour moved,
        worst colour move)."""
        with Image.open(io.BytesIO(blob)) as q:
            q = q.convert("RGBA")
        d = ImageChops.difference(self.frame, q)
        alpha_hist = d.getchannel("A").histogram()
        colour = ImageChops.lighter(ImageChops.lighter(d.getchannel("R"), d.getchannel("G")),
                                    d.getchannel("B"))
        colour_hist = colour.histogram()
        return (len(blob), sum(alpha_hist[1:]), d.getchannel("A").getextrema()[1],
                sum(colour_hist[1:]), colour.getextrema()[1])

    def test_the_rgba_path_is_bit_lossless(self):
        exact = self.offset_against_the_drawn_frame(render.to_png(self.frame, palette=False))
        self.assertEqual((exact[1], exact[3]), (0, 0),
                         "the truecolour path is the one that claims no loss")

    def test_the_indexed_file_is_the_smaller_one_and_within_its_stated_budget(self):
        exact = self.offset_against_the_drawn_frame(render.to_png(self.frame, palette=False))
        pal = self.offset_against_the_drawn_frame(render.to_png(self.frame, palette=True))
        self.assertLess(pal[0] * 3, exact[0], "indexed is not much smaller than RGBA")
        self.assertGreater(pal[2], 0)
        self.assertLessEqual(pal[2], 60, "alpha moved by more than 60/255")
        self.assertGreater(pal[4], 0)
        self.assertLessEqual(pal[4], 60, "colour moved by more than 60/255")
        self.assertGreater(pal[1], 10_000, "almost nothing moved: is this still an overlay frame?")
        self.assertLess(pal[1], 60_000)
        self.assertGreater(pal[3], 5_000)
        self.assertLess(pal[3], 30_000)

    def test_no_glyph_core_keeps_its_full_opacity_under_octree_quantise(self):
        """PIL's octree quantiser takes RGBA as a four-channel colour, so a palette entry that
        mixes an opaque glyph pixel with a half-transparent track pixel comes out in between for
        both.  That is the real cost of the default, and it is worth stating in pixels."""
        with Image.open(io.BytesIO(render.to_png(self.frame, palette=True))) as q:
            quantised = q.convert("RGBA")
        src = self.frame.getchannel("A").histogram()
        pal = quantised.getchannel("A").histogram()
        self.assertLess(pal[255] * 10, src[255], "the fully opaque pixels survived the quantise")
        self.assertLess(src[255], sum(src))

    def test_the_half_transparent_gauge_track_is_nearly_what_it_has_to_keep(self):
        """The track is the reason RGBA was ever considered: alpha 150, isolated from the ramp
        colours, and it comes back within 20/255 with under 2 % worse than that."""
        with Image.open(io.BytesIO(render.to_png(self.frame, palette=True))) as q:
            quantised = q.convert("RGBA")
        diff = ImageChops.difference(self.frame.getchannel("A"), quantised.getchannel("A"))
        track = self.frame.getchannel("A").point(lambda v: 255 if v == 150 else 0)
        on_track = ImageChops.multiply(diff, track).histogram()
        count = track.histogram()[255]
        worst = max((i for i, v in enumerate(on_track) if v), default=0)
        off_by_2 = sum(v for i, v in enumerate(on_track) if i > 1)
        self.assertGreater(count, 0, "this frame has no alpha-150 track to measure")
        self.assertLessEqual(worst, 20)
        self.assertLess(off_by_2 * 50, count)

    def colours_along_the_filled_arc(self, img: Image.Image) -> list:
        """Colours met along the CPU arc's filled part, at the stroke's middle."""
        cx, cy = render.A26_TCOL_X[0], render.A26_RING_Y
        out = []
        for deg10 in range(0, 1500, 2):
            angle = math.radians(render.A26_ARC_START + deg10 / 10.0)
            px = img.getpixel((int(round(cx + RAMP_R * math.cos(angle))),
                               int(round(cy + RAMP_R * math.sin(angle)))))
            if px[3] > 200:
                out.append(px[:3])
        return out

    def test_the_ramp_loses_more_than_two_thirds_of_its_distinct_colours(self):
        """How the two facts above look on the glass: one flat colour per arc-length band, which
        is what the owner looked at on real glass both ways and could not tell apart."""
        with Image.open(io.BytesIO(render.to_png(self.frame, palette=True))) as q:
            quantised = q.convert("RGBA")
        drawn, cols = self.colours_along_the_filled_arc(self.frame), \
            self.colours_along_the_filled_arc(quantised)
        self.assertGreater(len(drawn), 0, "the arc painted nothing to sample")
        self.assertLess(len(set(cols)), len(set(drawn)) // 3,
                        f"{len(set(drawn))} colours drawn, {len(set(cols))} quantised")


class Switches(unittest.TestCase):
    """The switches, on the command line, read back out of the PNG each dry run writes."""

    def test_default_and_palette_are_indexed_and_truecolour_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            runs = {"default": ["--dry-run", os.path.join(td, "dflt"), "--once", "--theme",
                                "alpha"],
                    "palette": ["--dry-run", os.path.join(td, "pal"), "--once", "--theme",
                                "alpha", "--palette"],
                    "truecolor": ["--dry-run", os.path.join(td, "tc"), "--once", "--theme",
                                  "alpha", "--truecolor"]}
            modes, alpha_hist = {}, None
            for which, argv in runs.items():
                got = fixtures.run(sys.executable, "-m", "xigmalcd", *argv)
                self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
                with Image.open(os.path.join(td, {"default": "dflt", "palette": "pal",
                                                  "truecolor": "tc"}[which],
                                             "frame0000.png")) as im:
                    modes[which] = im.mode
                    if which == "default":
                        alpha_hist = im.convert("RGBA").getchannel("A").histogram()
        self.assertEqual(modes["default"], "P")
        self.assertEqual(modes["palette"], "P")
        self.assertEqual(modes["truecolor"], "RGBA")
        # over a transparent canvas the indexed file still carries clear pixels and at least one
        # part-transparent step: the transparency the panel's own scrim rules depend on
        levels = sum(1 for v in alpha_hist[1:255] if v)
        self.assertGreater(alpha_hist[0], 0)
        self.assertGreaterEqual(levels, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
