#!/usr/bin/env python3
"""Every copied layout, painted offline from pinned readings - and an identity that holds anywhere.

Ported from the paint-all and CLI-door blocks of `tools/selftest.sh`'s vendor-theme section.  What
is asserted is the accounting, not the pixels:

    boxes drawn + widgets skipped for a missing reading + widgets skipped for a face that
    is not installed  ==  the widgets in the file

Every widget in a layout is either painted or reported as skipped with a reason.  A widget that
simply vanished breaks that, and that is the failure worth catching.  The pixel totals and frame
sizes belong to whichever fonts happen to be installed, so this file prints them and does not
assert them - which is also why the old section's per-layout box counts are not here.

The font probe has its own reason to exist: `layout.font_for` answers a three-tuple that stays
truthy even when the face is `None`, which is how an earlier probe reported "16 installed" on a
runner that then skipped a `simsun` widget.  So the probe asks the face, at the family, the weight
and the size each layout actually names.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import unittest

from tests import fixtures

from xigmalcd import layout
from xigmalcd import render
from xigmalcd import themes

#: One body of readings and one instant, deliberately not `fixtures.METRICS`: these are the shapes
#: a Windows session recorded (a network section, memory as a percentage, integer temperatures),
#: which is what the copied layouts were drawn against.


def faces_used(records: list) -> set:
    """Every (family, bold, size) the given layouts name."""
    out = set()
    for rec in records:
        for widget in (themes.load(rec["path"]).get("osd") or {}).get("widget") or []:
            for prop in widget.get("property") or []:
                if prop.get("fontFamily"):
                    out.add((str(prop["fontFamily"]).lower(), bool(prop.get("bold")),
                             int(prop.get("fontSize") or 12)))
    return out


def resolved(face: tuple) -> bool:
    """Ask the face, not the tuple: `font_for` returns (face, family, path) and a `(None, ...) `
    answer is still a truthy tuple."""
    return layout.font_for({"fontFamily": face[0], "bold": face[1], "fontSize": face[2]})[0] \
        is not None


class PaintAll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pick = themes.scan()[0]

    def test_every_layout_paints_and_every_widget_is_accounted_for(self):
        skipped_for_source: list = []
        for rec in self.pick:
            with self.subTest(layout=rec["name"]):
                img, notes = themes.paint(rec, fixtures.SESSION,
                                     when=fixtures.SESSION_WHEN, scrim=0)
                self.assertEqual(img.size, (480, 480))
                alpha = img.getchannel("A")
                lit = sum(1 for v in (alpha.get_flattened_data()
                                      if hasattr(alpha, "get_flattened_data") else alpha.getdata())
                          if v)
                self.assertGreater(lit, 500, f"{rec['name']} drew almost nothing")
                self.assertTrue(notes["boxes"], "drew nothing")
                # two different kinds of note: a metric this machine cannot read, and a face that
                # is not installed.  Only the first is a rule about the library.
                missing_source = [n for n in notes["missing"] if not str(n).startswith("font:")]
                missing_font = [str(n)[5:] for n in notes["missing"]
                                if str(n).startswith("font:")]
                self.assertEqual(len(notes["boxes"]) + len(missing_source) + len(missing_font),
                                 rec["widgets"],
                                 f"{rec['name']}: {rec['widgets']} widgets in the file, "
                                 f"{len(notes['boxes'])} painted, notes {notes['missing']}")
                if missing_source:
                    self.assertEqual(missing_source, ["Pump Speed"], rec["name"])
                    self.assertIn("fanscan", notes["absent"]["Pump Speed"], notes["absent"])
                    skipped_for_source.append(rec["name"])
        self.assertEqual(len(skipped_for_source), 9,
                         "the nine themes whose only skipped widget is Pump Speed changed, "
                         "and the source census in test_theme_library.py has to change with them")

    def test_the_skipped_themes_are_the_same_nine_the_reading_door_names(self):
        """The painter's skips and the reading door's refusals are one list, not two.

        Asking `themes.source_names()` used to be the same question, because a source with no
        entry there had no rule and could never be answered; since 2026-11-13 `Pump Speed` has
        a rule (`themes.FAN_TYPED`) and whether it answers depends on the body, so the census
        has to ask the body.
        """
        pick, _reject = themes.scan()
        _vals, absent = themes.values(fixtures.SESSION, fixtures.SESSION_WHEN)
        needs = {rec["name"] for rec in pick
                 if {p.get("source") for w in (themes.load(rec["path"]).get("osd") or {})
                     .get("widget") or [] for p in w.get("property") or [] if p.get("source")}
                 & set(absent)}
        painted = []
        for rec in pick:
            _img, notes = themes.paint(rec, fixtures.SESSION,
                                     when=fixtures.SESSION_WHEN, scrim=0)
            if [n for n in notes["missing"] if not str(n).startswith("font:")]:
                painted.append(rec["name"])
        self.assertEqual(set(painted), needs,
                         "a layout skips a widget the reading census did not predict, or the "
                         "census predicts one the painter does not skip")

    def test_a_font_that_is_not_installed_is_reported_rather_than_silently_dropped(self):
        """Machine fact, asserted as a relation: if a family this box cannot resolve is named, the
        painter's notes say which one."""
        unresolved = {f"{fam}{'b' if bold else ''}/{size}" for fam, bold, size
                      in faces_used(self.pick) if not resolved((fam, bold, size))}
        reported = set()
        for rec in self.pick:
            _img, notes = themes.paint(rec, fixtures.SESSION,
                                     when=fixtures.SESSION_WHEN, scrim=0)
            reported.update(str(n)[5:] for n in notes["missing"] if str(n).startswith("font:"))
        self.assertLessEqual(reported, reported)
        if unresolved:
            self.assertNotEqual(reported, set(),
                                f"this machine cannot resolve {sorted(unresolved)} and the "
                                "painter reported no dropped face at all")

    def test_bg_black_on_a_layout_theme_is_opaque_the_way_it_is_on_our_own_five(self):
        for rec in self.pick[:3]:
            with self.subTest(layout=rec["name"]):
                solid, _notes = themes.paint(rec, fixtures.SESSION,
                                     when=fixtures.SESSION_WHEN, base=render.BLACK)
                self.assertEqual(solid.getextrema()[3], (255, 255),
                                 "the canvas should cover the panel's stored background")
                clear, _notes = themes.paint(rec, fixtures.SESSION,
                                     when=fixtures.SESSION_WHEN)
                self.assertEqual(clear.getextrema()[3][0], 0,
                                 "over a transparent canvas the layout still has clear pixels")


class ThemeDoor(unittest.TestCase):
    """`--theme` takes both halves of the library, and a refused name comes back with its reason."""

    def test_the_parser_accepts_a_layout_name_in_any_case(self):
        parser = __import__("xigmalcd.main", fromlist=["main"]).build_parser()
        self.assertEqual(parser.parse_args(["--theme", "Theme_07"]).theme, "Theme_07")
        self.assertEqual(parser.parse_args(["--theme", "theme_07"]).theme, "Theme_07")

    def test_a_name_that_cannot_be_drawn_exits_2_and_says_why(self):
        parser = __import__("xigmalcd.main", fromlist=["main"]).build_parser()
        refused = themes.scan()[1][0]["name"]
        for bad, want in ((refused, "ratio 4:3"), ("Theme_99", "no layout named"),
                          ("nonsense", "no layout named")):
            with self.subTest(name=bad):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    with self.assertRaises(SystemExit) as got:
                        parser.parse_args(["--theme", bad])
                self.assertEqual(got.exception.code, 2)
                self.assertIn(want, err.getvalue())

    def test_list_themes_names_the_unpickable_ones_and_never_touches_a_port(self):
        got = subprocess.run([sys.executable, "-m", "xigmalcd", "--list-themes"],
                             capture_output=True, text=True, cwd=fixtures.REPO)
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        lines = [ln for ln in got.stdout.splitlines() if ln.strip()]
        self.assertEqual(len([ln for ln in lines if " NOT PICKABLE: " in ln]), 4, got.stdout)
        self.assertNotIn("ttyACM", got.stdout, "a listing door should not name a device")


if __name__ == "__main__":
    unittest.main(verbosity=2)
