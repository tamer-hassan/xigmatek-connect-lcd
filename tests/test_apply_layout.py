#!/usr/bin/env python3
"""The editor's own route to the glass: `apply to the panel`, both doors, and what the log says.

Reported on 2026-11-11: everything the layout editor could do with a layout stopped at the file.
A layout could be opened, previewed at the pinned fixture, edited, saved as a copy, renamed and
copied - and no control in the window told a running display to draw it.  Measured in a harness
before a line was written: with the editor on a vendor layout, `Apply these settings` sent
`theme=gauge`, the theme combo's pick, because that combo lists `sorted(render.THEMES)` - five
entries against the 28 this box opens.  The display's own `theme` door has taken a layout name
since 0.4 (`control.Control._set_theme` refuses only a name that `render.THEMES` lacks **and**
`themes.resolve` answers None for), and it answers with the name it is drawing.

So this file drives the narrow door and holds the window to what it owes a reader:

* one socket command, and the display's other six settings untouched - a button under the layout
  rows is not the theme box and must not move clock size, canvas, scrim, fans, rate or ink;
* nothing queued on the port's behalf: applying a layout is not an upload and not a frame, and the
  stored background is a separate act;
* the answer is **read**, not remembered - the window shows the theme the display reports, which
  is the only kind of confirmation this panel can give (PROTOCOL.md §11: settings come back,
  pixels do not);
* when the display refuses, the window quotes the display's own words **before** offering its own
  reason, because the two possible reasons - an old build whose door has no layout half, or a new
  build whose roots do not hold this file - live inside those words, and a paraphrase throws the
  evidence away.

There is deliberately no pre-flight probe, and one check here exists to notice if that stops
being true: the status reply carries no field that says whether a display's `theme` door has the
layout half, so the only command every build can answer is the command itself.
"""
from __future__ import annotations

import os
import re
import unittest

from tests import fixtures

from tests.test_display_remote import DisplayHarness

from xigmalcd import control, render, themes
from xigmaui import app

#: What the five-only door answers, spelled as `git show v0.3:xigmalcd/control.py` spells it -
#: which is also what the installed 0.3 service on this bench said when the owner's report came in.
OLD_DOOR_WORDS = (lambda name: f"unknown theme {name!r}; try {' '.join(sorted(render.THEMES))}")


def old_door(self, value) -> dict:
    """The `theme` door this repository shipped until 0.4: five names, and no layout half."""
    name = str(value or "")
    if name not in render.THEMES:
        return {"ok": False, "error": OLD_DOOR_WORDS(name)}
    with self.lock:
        self.args.theme = name
    return {"ok": True, "status": self.status()}


class ApplyingALayoutToADisplay(DisplayHarness):
    """The same harness - a real socket, an in-process `Control`, a port that does not exist."""

    def setUp(self):
        super().setUp()
        self.mark = 0
        self.other = self._other_settings()

    def _other_settings(self) -> tuple:
        return (self.args.clock_size, self.args.bg, self.args.scrim, self.args.no_fans,
                self.args.fps, self.args.text_color)

    def vendor_layout(self) -> str:
        """A layout that only a file can be: the first name `themes.scan()` answers, which is not
        one of the five `render.py` draws."""
        name = str(themes.scan()[0][0]["name"])
        self.assertNotIn(name, render.THEMES, f"{name} is drawn from code, so the wrong branch "
                                              "would be under test")
        self.assertNotIn(name, {self.win.theme.itemText(i) for i in range(self.win.theme.count())},
                         "the theme combo has grown a layout entry, which is not the shape this "
                         "route took: the picker stays on the five whose per-theme options and ink "
                         "the row under it edits")
        return name

    def open_in_editor(self, name: str) -> None:
        self.win.ed_name.setCurrentText(name)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, f"opening {name} left no editor")
        self.assertEqual(str(self.win.ed.name), name)

    def press(self) -> str:
        """Click `apply to the panel` and return exactly what that press said."""
        before = self.win.log_view.text()
        self.mark = len(before)
        self.win.ed_apply_panel.click()
        fixtures.pump(0.3)
        return self.win.log_view.text()[self.mark:]

    # ---- the guard, first: enabled by a running display, not by an open layout -------------
    def test_a_press_with_no_layout_open_refuses_in_words_and_sends_nothing(self):
        self.open_in_editor(self.vendor_layout())
        self.win.ed_name.setCurrentText(app.NO_EDITOR)
        fixtures.pump(0.3)
        self.assertIsNone(self.win.ed)
        self.assertTrue(self.win.ed_apply_panel.isEnabled(),
                        "the route is dead in a window that has a display and no layout open: it "
                        "should be the other way round, since saying so is the point of that "
                        "branch")
        said = self.press()
        self.assertIn("the layout box holds nobody", said, said[-400:])
        self.assertEqual(self._other_settings(), self.other,
                         "the refusal still reached the display's settings")
        self.assertIsNone(self.ctl.take(), "a refusal queued an action on the port's behalf")

    # ---- the file case: one command, one setting changed, the display's answer read back ----
    def test_the_layout_the_editor_holds_reaches_the_display_by_one_command(self):
        name = self.vendor_layout()
        self.open_in_editor(name)
        pick = self.win.theme.currentText()
        said = self.press()
        self.assertEqual(self.args.theme, name,
                         "the layout the editor holds did not reach the display")
        self.assertEqual(self._other_settings(), self.other,
                         "a button under the layout rows moved a setting that belongs to the "
                         "theme box")
        self.assertIsNone(self.ctl.take(),
                          "applying a layout queued an upload or a frame: the button sends one "
                          "socket command, and the background is a separate act")
        self.assertEqual(self.win.theme.currentText(), pick,
                         "the picker was rewritten to name a layout it cannot preview with its "
                         "own options row")
        self.assertIn(name, self.win.d_line.text(),
                      "the display line does not carry the layout it reports")
        self.assertIn(name, said, said[-400:])
        for phrase in ("panel draws", "its own status says so", "stored background is untouched",
                       "colours the file names", "what a fresh display starts with",
                       "would send its own pick", "this machine's readings, at the same pinned"):
            self.assertIn(phrase, said, f"the press did not say one of the things a reader cannot "
                                        f"see from the picture: {phrase}")

    def test_the_pinned_half_of_the_two_counts_is_the_painters_own_answer(self):
        """The log prints a pair: boxes at this machine's readings, against boxes at the pinned
        fixture.  The pinned half is deterministic - that body, that instant - so it is asserted
        against what `edit.Editor.paint` reports for that same fixture; the live half belongs to
        this machine's sensors and is only checked to be a number."""
        name = self.vendor_layout()
        self.open_in_editor(name)
        pinned = len(self.win.ed.paint(*self.win.ed.fixture())[1].get("boxes") or [])
        self.assertGreater(pinned, 0, "the pinned fixture paints no boxes, so the pair is empty")
        said = self.press()
        found = re.search(r"paints (\d+) boxes, against (\d+) at the pinned fixture", said)
        self.assertIsNotNone(found, said[-500:])
        self.assertEqual(int(found.group(2)), pinned,
                         "the log's pinned-fixture count is not what the editor's own paint of "
                         "that fixture reports")
        self.assertRegex(found.group(1), r"\d+",
                         "the live half of the pair is not a count")

    def test_a_generated_layout_applies_and_the_picker_agrees_with_the_display(self):
        """The five `render.py` themes are pickable by both controls, so the two are made to agree
        rather than left for a reader to notice apart."""
        chosen = self.vendor_layout()
        self.open_in_editor(chosen)
        generated = next(name for name in sorted(themes.EXPORTS)
                         if name != self.win.theme.currentText())
        self.open_in_editor(generated)
        said = self.press()
        self.assertEqual(self.args.theme, generated, "a generated layout did not reach the display")
        self.assertEqual(self.win.theme.currentText(), generated,
                         "the theme box and the display disagree about what is drawn, which is "
                         "the state the log claims to have avoided")
        self.assertIn("one of the five this program draws from `render.py`", said, said[-400:])
        self.assertIsNone(themes.resolve(generated),
                          "a generated name resolved to a file, so the two branches of this "
                          "button are being driven blind")

    # ---- (a) a display whose `theme` door has no layout half --------------------------------
    def test_a_five_only_display_refuses_and_the_window_quotes_it_before_explaining(self):
        name = self.vendor_layout()
        self.open_in_editor(name)
        kept = self.args.theme
        real_door = control.Control._set_theme
        control.Control._set_theme = old_door
        try:
            said = self.press()
        finally:
            control.Control._set_theme = real_door
        self.assertEqual(self.args.theme, kept, "a five-only door accepted a layout name")
        self.assertEqual(self._other_settings(), self.other,
                         "the refusal moved a setting on its way to refusing")
        self.assertIsNone(self.ctl.take(), "a refusal on an old display queued a frame or upload")
        words = OLD_DOOR_WORDS(name)
        self.assertIn(f"the display's own words: {words}", said,
                      "the window paraphrased the display's refusal instead of quoting it - and "
                      "the difference between the two reasons lives in those words")
        self.assertIn(f"the panel kept {kept}: {name} did not reach it", said, said[-400:])
        for phrase in ("two possibilities, and those words say which", "took only the five",
                       "until 0.4", "names no directory is that door",
                       "the packaged service starts `/usr/bin/xigmalcd`",
                       "`xigmalcd --list-themes`", "save as your copy",
                       "~/.config/xigmalcd/themes, which every display searches first"):
            self.assertIn(phrase, said, "the refusal stopped saying how a reader finds out which "
                                        f"display they are talking to: {phrase}")
        self.assertLess(said.index(f"the display's own words: {words}"),
                        said.index("two possibilities, and those words say which"),
                        "the window gave its own reason before quoting the display's, which is "
                        "the order that hides the evidence")

    # ---- (b) a new enough display whose roots simply do not hold this file ------------------
    def test_a_display_that_cannot_see_the_file_refuses_with_its_own_root_list(self):
        name = self.vendor_layout()
        self.open_in_editor(name)
        kept = self.args.theme
        empty = os.path.join(self.tmp.name, "no-layouts-here")
        os.makedirs(empty, exist_ok=True)
        real_roots = themes.roots
        themes.roots = lambda: ((empty, "*.json"),)
        try:
            said = self.press()
        finally:
            themes.roots = real_roots
        self.assertEqual(self.args.theme, kept,
                         "a display that cannot see the file accepted the name anyway")
        self.assertIsNone(self.ctl.take(), "the refusal queued an action for a layout nobody can "
                                           "draw")
        self.assertIn(f"no layout named {name!r} under {empty}", said,
                      "the refusal does not carry the display's own root list, which is the "
                      "evidence for this branch")
        self.assertIn("out of no file at all", said,
                      "the window stopped saying where *it* resolves the name today, and the two "
                      "answers are what tell (a) from (b)")
        self.assertIn("two possibilities, and those words say which", said, said[-400:])
        self.assertIsNotNone(themes.resolve(name),
                             "the roots patch was left in place, so everything after this point "
                             "runs blind")

    def test_there_is_still_no_field_to_probe_before_the_press(self):
        """The refusal is quoted after the command because nothing says, beforehand, which kind of
        display is answering.  If a future build publishes such a field, this fails and the log's
        promise has to be rewritten to use it."""
        caps = [key for key in self.ctl.status()
                if re.search(r"layout|resolv|vocab|door", key, re.I)]
        self.assertFalse(caps, f"{caps}: the display now reports a capability field, so the window "
                               "could warn before the press instead of quoting the refusal after")


if __name__ == "__main__":
    unittest.main(verbosity=2)
