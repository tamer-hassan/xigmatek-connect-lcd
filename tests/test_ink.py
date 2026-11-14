#!/usr/bin/env python3
"""The reader's text colour: one parser, three doors, and the pixels that prove it landed.

Ported from `tools/selftest.sh`'s "ink" section.  What survives here is every check that was
about code; what does not appear at all is the narration that quoted PROTOCOL.md or
docs/limits.md, because those pages now say which command prints the figure instead of carrying
a figure this suite had to re-measure.

Why the two-door half is the load-bearing one: `themes.draw` has no `ink` argument - a layout's
colours are its own, which is why a vendored theme looks here as it looks in the vendor's app -
so the window's text-colour choice used to reach the code-drawn themes and not the generated
layouts.  Measured on this bench, one ink moved the code drawing by 18,475 px and the file door
by 0.  `themes.with_ink` closes that, and the claim proved below is the strong form: at every
colour the parser itself knows, a generated layout and `render.draw` come out the same picture,
zero differing pixels.
"""
from __future__ import annotations

import ast
import io
import os
import unittest

from tests import fixtures
from tests.fixtures import METRICS, THEMES, WHEN_DT, count_opaque, differ

from xigmalcd import render as R
from xigmalcd import themes as T

RED = (255, 0, 0, 255)


def palette_names() -> list:
    """Every colour name `parse_ink` knows, read out of the module rather than remembered.

    The window's combo and the CLI's help both list these; taking them from the AST is what stops
    this file from measuring a list it invented.
    """
    with open(os.path.join(fixtures.REPO, "xigmalcd", "render.py"),
              encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "named")
    return [k.value for k in node.value.keys]


def keyed(obj: dict, key: str) -> list:
    """One colour key in widget order, not sorted: the whole point is to compare the same widget
    with itself, and many widgets do not carry the key at all."""
    return [(w["property"][0] or {}).get(key) for w in obj["osd"]["widget"]]


class ParseInk(unittest.TestCase):
    """The parser behind `--text-color`, the socket's `text_color`, and the window's row."""

    OK = {"#ff4040": (255, 64, 64, 255), "#0f8": (0, 255, 136, 255),
          "amber": (*R.AMBER[:3], 255), "mint": (*R.ALPHA_MINT[:3], 255),
          "white": R.WHITE, "rgb(0,230,118)": (*R.GREEN[:3], 255),
          "default": None, "": None, "auto": None, None: None}
    JUNK = ("cerise", "#gg", "red green", 5, ("r", "e", "d"), (1, 2, 300))

    def test_spellings_that_mean_a_colour(self):
        for got, want in self.OK.items():
            self.assertEqual(R.parse_ink(got), want, got)

    def test_junk_is_refused_in_words_a_human_sees(self):
        for bad in self.JUNK:
            with self.assertRaises(ValueError) as got:
                R.parse_ink(bad)
            self.assertIn("try #rrggbb", str(got.exception))

    def test_the_names_the_message_lists_are_the_module_own_constants(self):
        paired = {"white": R.WHITE, "black": R.BLACK, "cyan": R.CYAN, "green": R.GREEN,
                  "amber": R.AMBER, "red": R.RED, "dim": R.DIM, "track": R.TRACK,
                  "mint": R.ALPHA_MINT, "label": R.ALPHA_LABEL}
        for name, colour in paired.items():
            self.assertEqual(colour[:3], R.parse_ink(name)[:3], name)


class InkArithmetic(unittest.TestCase):
    """One constant pinned rather than trusted, and the skin rule that uses it."""

    def test_dim_ratio_is_pinned(self):
        self.assertEqual(R.INK_DIM, 0.62)

    def test_dim_moves_each_channel(self):
        self.assertEqual(R._dim((255, 64, 64, 255)), (158, 40, 40, 255))
        self.assertEqual(R._dim(R.WHITE)[:3], (158, 158, 158))

    def test_hex_round_trip_and_the_none_passthrough(self):
        self.assertEqual(R.ink_hex(R.parse_ink("AMBER")), "#ffc400")
        self.assertIsNone(R.ink_hex(None))
        self.assertEqual(R.parse_ink(R.ink_hex(R.AMBER)), (*R.AMBER[:3], 255))

    def test_theme_default_leaves_the_theme_own_skin_alone(self):
        self.assertEqual(R._skin(None, R.WHITE, R.DIM, R.CYAN), (R.WHITE, R.DIM, R.CYAN))
        fg, mid, acc = R._skin("#ff0000", R.WHITE, R.DIM, R.CYAN)
        self.assertEqual((fg, acc), (RED, RED))
        self.assertEqual(mid, R._dim(fg))


class InkOnPixels(unittest.TestCase):
    """`ink=` in a signature means nothing if a theme still paints its digits from a constant."""

    @classmethod
    def setUpClass(cls):
        cls.real_now = fixtures.freeze_clock(R)

    @classmethod
    def tearDownClass(cls):
        R._now = cls.real_now

    def test_every_theme_recolours_its_glyphs_and_nothing_else(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                # an (r,g,b) tuple, not the word "red": in this module `red` is the palette name
                # meaning R.RED (#ff4040), and the precedence is what the help text promises
                plain = count_opaque(R.draw(METRICS, theme))
                inked = count_opaque(R.draw(METRICS, theme, ink=(255, 0, 0)))
                self.assertGreater(plain.get(R.WHITE, 0), 200, "no solid glyph core")
                self.assertGreater(inked.get(RED, 0), 200)
                self.assertEqual(inked.get(R.WHITE, 0), 0, "a glyph kept the theme's own ink")
                before, after = sum(plain.values()), sum(inked.values())
                self.assertLess(abs(after - before), 0.06 * before,
                                "choosing an ink redrew the frame, not its letters")

    def test_a_chosen_ink_survives_the_default_palette_path(self):
        """The upload quantises to 256 colours (PROTOCOL.md §12), so an ink has to survive that."""
        for name in ("amber", "mint", "cyan", "green", "red", "#ff4040"):
            with self.subTest(ink=name):
                want = R.parse_ink(name)
                pre = count_opaque(R.draw(METRICS, "clock", clock=True, date=False, ink=want))
                # check the premise before measuring the trip: the frame must carry the ink it is
                # asking about, in thousands of pixels
                self.assertGreater(pre.get(want, 0), 1000,
                                   "this frame does not carry the ink being asked about, so the "
                                   "assert below would measure another colour's trip")
                enc = R.to_png(R.draw(METRICS, "clock", clock=True, date=False, ink=want))
                from PIL import Image
                seen = count_opaque(Image.open(io.BytesIO(enc)).convert("RGBA"))
                got = max(seen, key=seen.get)
                shift = max(abs(a - b) for a, b in zip(want[:3], got[:3]))
                self.assertLessEqual(shift, 1, "the palette path moved the ink by >1/255")


class InkThroughTheFileDoor(unittest.TestCase):
    """`themes.with_ink`: the window's colour, written into a copy of a generated layout."""

    INKS = [None] + palette_names() + ["#ff4040", (10, 200, 120, 255)]

    @classmethod
    def setUpClass(cls):
        cls.real_now = fixtures.freeze_clock(R)

    @classmethod
    def tearDownClass(cls):
        R._now = cls.real_now

    def test_both_doors_end_up_the_same_picture(self):
        for theme in THEMES:
            base = T.export(theme)
            for ink in self.INKS:
                with self.subTest(theme=theme, ink=ink):
                    inked, _note = T.with_ink(base, theme, ink)
                    gap, chan = differ(R.draw(METRICS, theme, ink=ink),
                                       T.draw(inked, METRICS, WHEN_DT)[0])
                    self.assertEqual((gap, chan), (0, 0),
                                     "a generated layout and the code drawing disagree at "
                                     "this ink: the skin table, the recipe and the export no "
                                     "longer say the same thing")
            self.assertEqual(T.export(theme), base, "`with_ink` wrote through its copy")

    def test_only_the_glyph_roles_move(self):
        """`bars` is where the glyph/graphic distinction has teeth: its heading glyph and its
        eleven meter tracks are the same CYAN, and an ink may take only the glyph."""
        base = T.export("bars")
        inked, _note = T.with_ink(base, "bars", "amber")
        for key in ("startColor", "endColor", "bgColor"):
            self.assertEqual(keyed(base, key), keyed(inked, key),
                              f"an ink moved a graphic's colour ({key}), not a glyph's")
        moved = sum(1 for a, b in zip(keyed(base, "textColor"), keyed(inked, "textColor"))
                    if a != b)
        # 24 today: the heading, the clock, one label per row and one number per row.  The
        # figure moved from 22 when the drive row went in (2026-11-14); a widget count derived
        # from the table and a glyph count pinned like this one meet in the middle, and the
        # difference between them is exactly the meters.
        self.assertEqual(moved, 24, "the glyph roles an ink may move are no longer 24 of "
                                    f"{len(base['osd']['widget'])} widgets")
        self.assertEqual(moved + sum(1 for w in base["osd"]["widget"] if w["type"] == "bar"),
                         len(base["osd"]["widget"]),
                         "glyph roles plus meter tracks are not the whole layout")

    def test_a_layout_that_is_not_one_of_the_five_comes_back_untouched(self):
        refused, note = T.with_ink(T.export("bars"), "Theme_28", "amber")
        self.assertIn("no drawn theme named", note)
        self.assertEqual(refused, T.export("bars"))

    def test_alpha_says_its_three_glyph_roles_are_one_colour(self):
        _obj, note = T.with_ink(T.export("alpha"), "alpha", "amber")
        self.assertIn("all three glyph roles together", note)

    def test_the_palette_this_file_measures_is_the_palette_the_parser_knows(self):
        """A guard against this file drifting from the module: the names it offers come from
        `render.py`'s own table, so the window cannot offer a colour never measured here."""
        names = set(palette_names())
        self.assertEqual(names, {"white", "black", "cyan", "green", "amber", "red", "dim",
                                 "track", "mint", "label"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
