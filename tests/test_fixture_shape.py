#!/usr/bin/env python3
"""The editor's pinned fixture, what it owes, and the two doors it has to agree with.

Ported from the fixture-shape and ink-parity blocks of `tools/selftest.sh`'s GUI section.  The
pane shows *the file being edited*, drawn by `themes.draw` at a pinned body (`edit.FIXTURE`) and a
pinned instant, so that a field change is the only thing that can move a pixel.  That decision
creates three obligations, and none of them was held before they were written down here:

* **the fixture's key names belong to a real machine.**  A group or field that no box reports is a
  value the library will never ask for and the reader will never see.  This is not a style rule:
  the dict once answered 5 of the 19 sources the five exports ask while carrying four keys nothing
  in the library reads (`gpu.usage`, `cpu.frequency`, `gpu.frequency`, `memory.used_percent`), and
  the pane then showed a `bars` layout with 14 of its 32 rows beside a code drawing of 26 and the
  two looked unrelated;
* **the fixture answers every source the five drawn themes ask for**, except the fan slots past the
  tachometers that body reports - which is the one hole a reader should see, because the same hole
  exists on a machine with fewer fans plugged in;
* **the preview *is* the picture the loop would send.**  Both doors, at every ink choice the
  parser's own vocabulary accepts, down to zero differing pixels and a zero worst channel.  An
  export, a recipe and the skin table have to describe one picture, or the pane is a preview of
  something else.

A vendored layout is deliberately outside the ink rule: `--text-color` is a setting of *our*
drawings, not a re-colour of somebody else's file, so painting a vendor file with an ink asked for
moves nothing and says nothing.
"""
from __future__ import annotations

import json
import unittest

from tests import fixtures

from xigmalcd import render, sensors, themes
from xigmaui import edit as gui_edit

#: The ink choices the parser's own vocabulary accepts, plus a hex and a raw tuple: what the
#: window's colour row can actually hand the drawing doors.  Nothing here is a list of names
#: remembered for the test: `test_every_name_is_one_the_parser_takes` keeps it honest.
INKS = (None, "amber", "red", "mint", "cyan", "#ff4040", (10, 200, 120, 255))

#: The keys `xigmaui`'s fixture carried before it was completed to what the library asks.  Kept as
#: an explicit list because the point of the comparison below is a *relation* - the completed body
#: answers strictly more of the corpus than that one did - and a relation needs both sides named.
THIN_BEFORE = {"cpu": ("usage", "speedAverage"),
               "gpu": ("load", "speed", "fan", "memoryUsage", "dedicatedTotal"),
               "memory": ("used", "total", "load")}


def documented_shape() -> dict:
    """The metrics shape `sensors.py` documents in its own module docstring."""
    text = sensors.__doc__ or ""
    start = text.index("{")
    shape, _end = json.JSONDecoder().raw_decode(text, start)
    return shape


def generated() -> list:
    """The five drawn themes, opened the way the window opens them.

    `open_theme` is not a convenience: it is the door that records which theme a layout came from,
    and `Editor.paint(ink=...)` needs that to know whether the reader's colour can be honoured at
    all.  Wrapping `themes.export(name)` in an Editor by hand leaves an ink row that silently does
    nothing.
    """
    return [gui_edit.Editor.open_theme(name) for name in sorted(themes.EXPORTS)]


class TheFixtureNamesWhatARealBoxReports(unittest.TestCase):
    def setUp(self):
        self.shape = documented_shape()

    def test_the_shape_this_rule_is_measured_against_exists(self):
        self.assertTrue(self.shape, "sensors.py's own documented metrics shape did not parse")

    def test_no_group_or_field_of_the_fixture_is_one_no_machine_reports(self):
        stray = {}
        for group, fields in gui_edit.FIXTURE.items():
            if group not in self.shape:
                stray[group] = "a metrics group no box reports"
                continue
            spec = self.shape[group]
            if isinstance(spec, list):        # `fans` is a list of rows, not a group of keys
                extra = [key for row in fields for key in row if key not in spec[0]]
            else:
                extra = [key for key in fields if key not in spec]
            if extra:
                stray[group] = extra
        self.assertFalse(stray, f"{stray}: the editor's fixture carries a key no machine reports - "
                                "which is how it once answered `gpu.usage` while the library asked "
                                "for `gpu.load`")

    def test_the_five_drawn_themes_ask_only_for_what_the_fixture_answers(self):
        asked = {((widget.get("property") or [{}])[0])["source"]
                 for editor in generated() for widget in editor.widgets()
                 if (widget.get("property") or [{}])[0].get("source")}
        answered, _absent = themes.values(gui_edit.FIXTURE, gui_edit.FIXTURE_WHEN)
        missing = sorted(asked - set(answered))
        fans = len(gui_edit.FIXTURE.get("fans") or [])
        fan_sources = {source for source in asked if str(source).startswith("Fan ")}
        slots = fan_sources - {source for source in fan_sources
                               if int(str(source).split()[1]) - 1 < fans}
        self.assertEqual(missing, sorted(slots),
                         f"{missing}: the fixture leaves a source unanswered that is not a fan slot "
                         f"past this shape's {fans} reported tachometers - a new reading in a new "
                         "export needs a pinned value")

    def test_the_completion_still_buys_something_so_the_relation_below_is_not_hollow(self):
        # dict groups only: `fans` and `drives` are lists, and `motherboard` is the one field
        # the thin body never carried (THIN_BEFORE names keys per group, and a list has none)
        thin = {group: {key: value for key, value in fields.items()
                        if key not in THIN_BEFORE.get(group, ())}
                for group, fields in gui_edit.FIXTURE.items()
                if isinstance(fields, dict) and group != "motherboard"}
        asked = {((widget.get("property") or [{}])[0])["source"]
                 for editor in generated() for widget in editor.widgets()
                 if (widget.get("property") or [{}])[0].get("source")}
        answered, _absent = themes.values(thin, gui_edit.FIXTURE_WHEN)
        self.assertTrue(asked - set(answered),
                        "the fixture's coverage is no longer more than the thin body it replaced, "
                        "so the comparison below measures nothing")


class ThePreviewIsThePictureTheLoopSends(unittest.TestCase):
    """Both doors, at the pinned body and instant, at every ink the parser takes."""

    @classmethod
    def setUpClass(cls):
        cls.editors = generated()

    def test_every_name_is_one_the_parser_takes(self):
        for ink in INKS:
            if ink is None or isinstance(ink, tuple):
                continue
            self.assertIsNotNone(render.parse_ink(ink),
                             f"{ink!r} is not in the parser's vocabulary, so "
                                                  "the sweep below is skipping a colour a reader "
                                                  "can choose")

    def test_the_file_door_and_the_code_door_agree_to_the_pixel_at_every_ink(self):
        when = gui_edit.FIXTURE_WHEN
        saved = render._now
        render._now = lambda: when.timetuple()
        try:
            for editor in self.editors:
                for ink in INKS:
                    with self.subTest(theme=editor.name, ink=ink):
                        layer, _notes = editor.paint(*editor.fixture(), ink=ink)
                        code = render.draw(gui_edit.FIXTURE, editor.name, ink=ink)
                        differing, worst = fixtures.differ(code, layer)
                        self.assertEqual((differing, worst), (0, 0),
                                         f"{editor.name} at ink {ink!r}: {differing} px, worst "
                                         f"{worst}/255 - the pane's two doors disagree, so an "
                                         "export, a recipe and the skin table no longer describe "
                                         "one picture")
        finally:
            render._now = saved

    def test_the_completed_fixture_paints_more_of_bars_than_the_body_it_replaced(self):
        # dict groups only: `fans` and `drives` are lists, and `motherboard` is the one field
        # the thin body never carried (THIN_BEFORE names keys per group, and a list has none)
        thin = {group: {key: value for key, value in fields.items()
                        if key not in THIN_BEFORE.get(group, ())}
                for group, fields in gui_edit.FIXTURE.items()
                if isinstance(fields, dict) and group != "motherboard"}
        editor = next(e for e in self.editors if e.name == "bars")
        _full, full_notes = editor.paint(*editor.fixture())
        _thin, thin_notes = themes.draw(editor.obj, thin, gui_edit.FIXTURE_WHEN)
        self.assertLess(len(thin_notes.get("boxes") or []), len(full_notes.get("boxes") or []),
                        "the completed fixture no longer paints more of `bars` than the thin one, "
                        "so the row counts the pages quote have stopped meaning the completion")

    def test_a_vendored_layout_keeps_the_colours_its_file_names(self):
        """The ink row is a setting of this program's drawings.  A vendor's file carries its own
        `textColor` values, and re-colouring somebody else's theme would misrepresent the picture
        the panel's own theme application shows."""
        vendor = gui_edit.Editor.open_theme(themes.scan()[0][0]["name"])
        plain, _notes = vendor.paint(*vendor.fixture())
        tinted, _notes2 = vendor.paint(*vendor.fixture(), ink="amber")
        self.assertEqual(vendor.ink_note, "",
                         f"a vendored layout reported an ink answer: {vendor.ink_note!r}")
        differing, worst = fixtures.differ(plain, tinted)
        self.assertEqual((differing, worst), (0, 0),
                         f"asking for amber moved {differing} px of a vendor's file (worst "
                         f"{worst}/255): the ink row is re-colouring a theme it does not own")


if __name__ == "__main__":
    unittest.main(verbosity=2)
