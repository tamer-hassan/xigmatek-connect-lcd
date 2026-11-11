#!/usr/bin/env python3
"""`tools/knobmap.py`'s structure: every option a drawn theme accepts is answered or reported.

Ported from the knobmap section of `tools/selftest.sh`.  The tool answers one question per option,
for each of the five themes drawn in code: can a layout file do what this switch does, and if so how
many pixels apart are the two doors?  The answers themselves are measurements and live in the tool;
what this file holds is the **structure** of the answer, which is the part that does not depend on
which fonts are installed.

Three rules, and each one fails in a way that matters:

* every keyword option in a theme's signature is either a row in the map or in the unread list, and
  the unread list is derived here from the bodies with `ast` - so the tool cannot quietly drop an
  option and make the map look clean;
* exactness is binary.  A row is either 0 px with a worst channel of 0, or it is past a floor taken
  from this run - so "the file door nearly answers it" is not a state the map can be in;
* the reader's text colour and the default transparent canvas are exact for all five themes, and
  the black canvas is *not* exact for any of them.  The first two are the case every parity claim in
  the documents is about; the third is the plate-under-a-layer split, and if it ever stopped
  differing the `--bg` row in `docs/usage.md` would be wrong.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import tempfile
import unittest

from tests import fixtures

from xigmalcd import render, themes

TOOL = os.path.join("tools", "knobmap.py")

#: Options the bodies are known to honour now, each expected to be exactly one row at 0 px.
#: `--no-clock` is here because it used to be the opposite: an option in the signature and nowhere
#: in the body, which the tool reported as unread until 0.4 made the body honour it.
HONOURED = (("clock", "clock"),)


class Knobmap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = tempfile.mktemp(suffix=".json", dir=fixtures.ISOLATED)
        got = fixtures.run(os.path.join(fixtures.REPO, TOOL), "--json", out)
        if got.returncode != 0:
            raise AssertionError(f"tools/knobmap.py failed: {got.stdout[-800:]}{got.stderr[-800:]}")
        with open(out, encoding="utf-8") as fh:
            data = json.load(fh)
        os.unlink(out)
        cls.rows, cls.knobs, cls.unread = data["rows"], data["knobs"], data["unread"]

    def rows_for(self, theme: str, knob: str) -> list:
        """A row belongs to an option when its knob is that name or `<name> <something>` - and
        only then: prefix matching alone would count `clock_size`'s row under `clock` too."""
        return [r for r in self.rows
                if r["theme"] == theme and (r["knob"] == knob or r["knob"].startswith(knob + " "))]

    def test_every_signature_option_is_a_row_or_an_unread_note(self):
        expect_unread, expect_rows = [], 0
        for name in sorted(render.THEMES):
            signature = inspect.signature(render.THEMES[name])
            options = [k for k in signature.parameters if k not in ("m", "metrics")]
            self.assertEqual(self.knobs.get(name), sorted(options),
                             f"theme_{name}'s own option list is not what the tool says it is")
            tree = ast.parse(inspect.getsource(render.THEMES[name]))
            for knob in options:
                uses = sum(1 for node in ast.walk(tree)
                           if isinstance(node, ast.Name) and node.id == knob)
                found = self.rows_for(name, knob)
                if uses == 0:
                    expect_unread.append((name, knob))
                    self.assertEqual(found, [], f"theme_{name} takes `{knob}` and never reads "
                                                "it, and the map has a row for it anyway")
                else:
                    expect_rows += len(found)
                    self.assertGreaterEqual(len(found), 1,
                                            f"theme_{name} reads `{knob}` and the map has no row")
        self.assertEqual(sorted(tuple(u) for u in self.unread), sorted(expect_unread),
                         "the unread list is not what the bodies say it is")
        self.assertEqual(len(self.rows), expect_rows)

    def test_exactness_is_binary_and_the_floor_is_this_runs_own(self):
        exact = [r for r in self.rows if r["exact"]]
        apart = [r for r in self.rows if not r["exact"]]
        for row in exact:
            with self.subTest(theme=row["theme"], knob=row["knob"]):
                self.assertEqual((row["diff_px"], row["worst_channel"]), (0, 0), row)
        self.assertNotEqual(apart, [], "every row is exact, so the floor below has "
                            "nothing to measure")
        for row in apart:
            self.assertGreater(row["diff_px"], 0, row)
        floor = min(r["diff_px"] for r in apart)
        self.assertGreater(floor, 900,
                           f"a non-exact pair sits {floor} px from 0: 'exactly 0 or clearly not' "
                           "stops being a decision, and the map's line moved under it")

    def test_the_readers_colour_and_the_default_canvas_are_exact_for_all_five(self):
        for name in sorted(render.THEMES):
            with self.subTest(theme=name):
                ink = self.rows_for(name, "ink")
                self.assertEqual(len(ink), 1, ink)
                self.assertTrue(ink[0]["exact"],
                                "`themes.with_ink` no longer matches the code drawing: the "
                                "pane's two doors disagree about the reader's own colour")
                clear = self.rows_for(name, "bg clear")
                self.assertEqual(len(clear), 1, clear)
                self.assertTrue(clear[0]["exact"],
                                "at the default transparent canvas the file door and the code "
                                "door are not one picture")

    def test_the_black_canvas_differs_for_every_one_of_them(self):
        """A plate under a layer is not a canvas drawn on, so this *should* differ - and if it
        stopped differing, `docs/usage.md`'s `--bg` row would be describing a door that no longer
        exists."""
        black = [r for r in self.rows if r["knob"] == "bg black"]
        self.assertEqual(len(black), len(render.THEMES), black)
        for row in black:
            with self.subTest(theme=row["theme"]):
                self.assertFalse(row["exact"], row)

    def test_an_option_the_body_honours_today_stays_one_row_at_zero_px(self):
        for name, knob in HONOURED:
            with self.subTest(theme=name, knob=knob):
                found = self.rows_for(name, knob)
                self.assertEqual(len(found), 1, [(r["knob"], r["diff_px"]) for r in found])
                self.assertTrue(found[0]["exact"],
                                f"theme_{name} no longer honours `--no-{knob}` as one row "
                                "landing at 0 px in both doors")


if __name__ == "__main__":
    unittest.main(verbosity=2)
