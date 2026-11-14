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
* the two box counts the log prints are the **file's**, counted through the loop's own door
  (`themes.paint`) at this machine's readings and at the pinned fixture - not the editor's buffer,
  which holds acts nobody saved, and not the pane's door, which is a different function;
* the press says, before it sends, when the picture in this pane and the picture the display
  will make are not the same - counted in pixels, both painted at one body and one instant -
  because `apply` sends a *name* and the display reads a file: reported 2026-11-13 as "apply
  to the panel has no effect, if pressed before save as your copy", and true, since the edit
  had never left the window.  The clean case is held too, so the sentence is a difference and
  not a disclaimer, and a generated name says what `render.py` draws instead of quoting a path;
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

from xigmalcd import control, render, sensors, themes
from xigmaui import app, edit

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

    # ---- what a press cannot carry: the pane's picture vs the file's -----------------------
    def row_with_a_colour(self) -> int:
        """The first row this window can re-ink, from the layout it has open."""
        for i, w in enumerate(self.win.ed.widgets()):
            if str((w.get("property") or [{}])[0].get("textColor") or ""):
                return i
        raise AssertionError("no row of this layout carries a `textColor` to change")

    def ink_of(self, index: int) -> tuple:
        """That row's ink in the buffer and in the file, in the order a reader can compare."""
        name = str(self.win.ed.name)
        prop = self.win.ed.widgets()[index]["property"][0]
        buffer = str(prop.get("textColor") or "")
        rec = themes.resolve(name)
        if rec is None:
            return buffer, ""
        twin = themes.load(rec["path"])["osd"]["widget"][index]
        self.assertEqual(str((twin.get("property") or [{}])[0].get("id") or ""),
                         str(prop.get("id") or ""),
                         f"row {index} of the buffer is not row {index} of {rec['path']}, so "
                         "comparing the two by position is reading the wrong pair")
        return buffer, str((twin.get("property") or [{}])[0].get("textColor") or "")

    def reink(self, index: int, colour: str) -> None:
        """Type an ink into the window's own row control, and commit it as a keystroke would."""
        self.win.ed_widget.setCurrentIndex(index)
        fixtures.pump(0.3)
        box = self.win.ed_rows["textColor"][2]
        box.setText(colour)
        self.win._ed_apply_row("textColor", commit=True)
        fixtures.pump(0.3)

    def test_an_unsaved_edit_is_said_before_the_press_that_cannot_carry_it(self):
        """Reported 2026-11-13: "apply to the panel has no effect, if pressed before save as
        your copy".  It had an effect - the name the panel draws moved - and the picture stayed
        the picture of the file, because nothing had been written.  The window used to report
        that press as a plain success.
        """
        self.open_in_editor(self.vendor_layout())
        row = self.row_with_a_colour()
        self.reink(row, "rgba(106, 106, 106, 1)")
        buffer, on_disk = self.ink_of(row)
        self.assertNotEqual(buffer, on_disk,
                            "the edit did not separate this buffer from that file, so nothing "
                            "below can show that a press cannot carry an edit")
        self.assertTrue(self.win.ed.dirty, "the window does not even know the edit is unsaved")
        said = self.press()
        for needle in ("not the same picture", "save as your copy"):
            self.assertIn(needle, said, said[-500:])
        figures = re.findall(r"(\d+) px between", said)
        self.assertEqual(len(figures), 1, f"no single pixel figure in: {said[-400:]}")
        px = int(figures[0])
        self.assertGreater(px, 0, "the pane and the file disagree and the window said 0 px")
        # the order is the fix, not just the sentence: a warning printed after the command has
        # gone is a post-mortem, and the whole point is that the reader learns it at the press
        where_said = said.index("not the same picture")
        where_sent = said.index("panel draws")
        self.assertLess(where_said, where_sent,
                        f"the press spoke after the command went out: {said[-400:]}")
        self.assertEqual(self.args.theme, str(self.win.ed.name),
                         "the press did not do the one thing it can do: name the layout")
        self.assertEqual(self.ink_of(row)[1], on_disk,
                         "the press wrote something: applying a layout is not a save")
        self.assertIn("no file has them", self.win.ed_state.text(), self.win.ed_state.text())
        self.assertIn("the glass will not change", self.win.ed_apply_panel.toolTip(),
                      "the button itself never said that a press carries a name, not the "
                      "keystrokes under the cursor")

    def test_the_same_press_after_a_save_says_nothing_about_the_pictures(self):
        """The clean case, held too: the sentence is a difference, not a disclaimer."""
        self.open_in_editor(self.vendor_layout())
        row = self.row_with_a_colour()
        self.reink(row, "rgba(106, 106, 106, 1)")
        self.win.ed_save.click()
        fixtures.pump(0.4)
        buffer, on_disk = self.ink_of(row)
        self.assertEqual(buffer, on_disk, "the save did not reach the file the display reads")
        self.assertFalse(self.win.ed.dirty, "the buffer is still dirty after a save")
        said = self.press()
        self.assertNotIn("not the same picture", said,
                         f"a clean press was warned about anyway: {said[-400:]}")
        self.assertIn("nothing outstanding", self.win.ed_state.text(), self.win.ed_state.text())

    def test_a_generated_layout_edit_names_the_picture_the_code_draws(self):
        """No file, no save, and a picture the display takes from `render.py`.

        One of the five drawn-from-code names can be edited in this pane and cannot be saved at
        its own name (`themes.save` refuses a `gauge.json`), so the pane and the display are
        allowed to differ here in a way that is not a typo - which is exactly why the sentence
        has to say what the display draws instead of quoting a path that does not exist.
        """
        self.open_in_editor("gauge")
        self.assertIsNone(themes.resolve("gauge"), "the library has grown a `gauge.json`, and "
                                                 "this check is about the branch that has none")
        row = self.row_with_a_colour()
        self.reink(row, "rgba(106, 106, 106, 1)")
        said = self.press()
        self.assertIn("not the same picture", said, said[-500:])
        self.assertIn("`render.py` draws for that name", said, said[-500:])
        for needle in ("copy to a new name", "a second `theme_gauge`"):
            self.assertIn(needle, said,
                          f"the advice at a generated name is not the door that works there "
                          f"({needle!r}): {said[-500:]}")
        self.assertNotIn("/xigmalcd/themes/", said,
                         f"a generated name was reported with a file to save into, which "
                         f"`themes.save` refuses: {said[-400:]}")
        px = int(re.findall(r"(\d+) px between", said)[0])
        self.assertGreater(px, 0, "an edited colour changed no pixel of the picture")

    def test_the_copy_door_says_it_copies_before_it_refuses_the_name_already_open(self):
        """Reported 2026-11-13: "making changes to alpha_new and pressing `save as` button
        doesn't seem to have any effect, even if followed by pressing `apply to the panel`".

        Nothing was written, twice over.  The button labelled `save as` was pressed with the open
        layout's own name in the box next to it, and `themes.new_name` refuses a name something
        already answers - but `save as` reads like an in-place save, so a refusal looked like a
        silent success and the file kept the ink it had.  The `apply` that followed then sent the
        name that very panel already held, which moves no pixel on the glass.  Three things carry
        the fix: the label names the door, the tooltip states the refusal before the press, and
        the press that follows says what the pane and the file disagree about, in pixels.
        """
        name = self.vendor_layout()
        self.open_in_editor(name)
        root = themes.user_root()

        def listing() -> list:
            return sorted(os.listdir(root)) if os.path.isdir(root) else []

        before = listing()
        row = self.row_with_a_colour()
        untouched = self.ink_of(row)[1]
        self.reink(row, "rgba(106, 106, 106, 1)")

        self.assertNotEqual(self.win.ed_copy.text(), "save as",
                            "the button is called `save as` again: that is the label that made a "
                            "refusal read as a save of the layout already open")
        self.assertEqual(self.win.ed_copy.text(), "copy to a new name",
                         f"the copy door is labelled {self.win.ed_copy.text()!r}")
        tip = self.win.ed_copy.toolTip()
        for needle in ("not a free name", "save as your copy"):
            self.assertIn(needle, tip,
                          f"nothing above the press says {needle!r}, which is the other half of "
                          f"this report: {tip[:400]}")

        self.win.ed_newname.setText(name)
        self.win.ed_copy.click()
        fixtures.pump(0.4)
        self.assertIn(f"{name!r} is not a free name", self.win.ed_note.text(),
                      f"the press that changes no file was not refused in the line that carries "
                      f"its refusals: {self.win.ed_note.text()[:300]}")
        self.assertEqual(listing(), before,
                         "a refused copy still wrote something into the user's root")
        self.assertEqual(self.ink_of(row)[1], untouched,
                         "the refused copy reached the file the display reads")
        self.assertEqual(str(self.win.ed.name), name,
                         "a refused copy moved the window off the layout it had open")
        self.assertTrue(self.win.ed.dirty,
                        "the refusal threw away the edit that was typed before it")

        said = self.press()
        for needle in ("not the same picture", "save as your copy"):
            self.assertIn(needle, said,
                          f"the press that follows a refused copy still reports a plain success: "
                          f"{said[-500:]}")
        self.assertGreater(int(re.findall(r"(\d+) px between", said)[0]), 0,
                           "the pane and that file disagree and the window said 0 px")
        self.assertEqual(self.ink_of(row)[1], untouched,
                         "the file on the display's side of the wire still has none of the edit, "
                         "which is the whole report")

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

    def test_the_two_counts_are_the_files_and_not_the_buffer_under_the_cursor(self):
        """The pair the press prints is what the panel can draw, which an unsaved edit is not.

        Two doors sit between this window and that glass, and the log line has to read them the
        right way round.  The numbers used to come from the pane's painter (`Editor.paint`), which
        paints the **buffer**: every act typed since the last save.  The display can only ever
        draw the **file**, so a count taken from the buffer is a count of a picture nobody is
        going to see - and the same wrong door is how a saved copy of `alpha` reached the panel
        without its `temp-values` or `fan-figures` rows on 2026-11-12 while every number this
        window printed said the picture was complete.  A count cannot see that loss at all: a
        `special` row whose keys are missing from the value table stays in `notes["boxes"]` with
        **no box** beside it, so `len()` counts it either way.  That is why the checks in
        `tests/test_specials.py` ask for boxes and ink, and why this one asks which door the
        count came out of.

        So: save a copy of a generated layout, delete a row that draws without saving it, press
        the button, and read the pair back out of the log.  The two numbers have to be the file's.
        `sensors.collect()` is pinned for the length of the check, because the live half of the
        pair is otherwise this machine's temperature at two different instants and a difference
        here would mean nothing.
        """
        name = "alpha_press_copy"
        path, _soft = themes.save(themes.export("alpha"), name)
        self.win._ed_refresh_layouts()          # the shipped door a save-as goes through
        self.open_in_editor(name)
        rec = themes.resolve(name)
        self.assertIsNotNone(rec, f"{path} was saved and does not resolve, so the press below "
                                  "would take the generated-name branch by accident")

        body = {"cpu": {"temperature": 61.0, "load": 62.0, "frequency": 3400, "power": 18.0},
                "gpu": {"temperature": 36.0, "fan": 35.0, "load": 22.0, "memory": 2048,
                        "power": 90.0, "frequency": 1200, "memoryRate": 30.0},
                "memory": {"total": 16384, "used": 8192},
                "fans": [{"name": "Fan CPU", "value": 1180}]}
        pinned, at = self.win.ed.fixture()
        drawn = [wi for _kind, _what, box, wi in ((self.win.ed.paint(pinned, at)[1].get("boxes")
                                                  or [])) if box]
        self.assertTrue(drawn, "the saved copy paints no row with a box, so deleting one below "
                               "changes nothing and the pair means nothing")

        real = sensors.collect
        sensors.collect = lambda: dict(body)
        try:
            ok, note = self.win.ed.delete_widget(drawn[0])
            self.assertTrue(ok, note)
            self.assertTrue(self.win.ed.dirty,
                            "the row was removed and the model is not dirty, so the buffer and "
                            "the file below are the same thing and the pair cannot be told apart")
            said = self.press()
            file_live = len(themes.paint(rec, dict(body), at)[1].get("boxes") or [])
            file_pinned = len(themes.paint(rec, dict(pinned), at)[1].get("boxes") or [])
            buffer_live = len(self.win.ed.paint(dict(body), at)[1].get("boxes") or [])
            self.assertNotEqual(file_live, buffer_live,
                                f"the file paints {file_live} boxes and the edited buffer paints "
                                f"{buffer_live}: the two are not different pictures, so nothing "
                                f"below can say which one the log counted")
            found = re.search(r"paints (\d+) boxes, against (\d+) at the pinned fixture", said)
            self.assertIsNotNone(found, said[-400:])
            self.assertEqual((int(found.group(1)), int(found.group(2))),
                             (file_live, file_pinned),
                             f"the log counted {found.group(1)} and {found.group(2)} boxes, "
                             f"while the file the display was just told to draw paints "
                             f"{file_live} at this machine's readings and {file_pinned} at the "
                             f"pinned fixture: the pair is describing the buffer under the "
                             f"cursor, which is a picture that panel will never be given")
        finally:
            sensors.collect = real

    def test_the_pinned_half_of_the_two_counts_is_the_painters_own_answer(self):
        """The log prints a pair: boxes at this machine's readings, against boxes at the pinned
        fixture.  The pinned half is deterministic - that body, that instant - and it is now
        counted across doors: the log takes its number from `themes.paint`, the loop's door, and
        the expectation here comes from `edit.Editor.paint`, the pane's.  The two agreeing is not
        a courtesy: it is the parity `themes._overlay` exists to keep, and the pair of doors that
        filled different value tables is what let a saved `alpha` lose its `temp-values` and
        `fan-figures` rows on the glass on 2026-11-12.  The live half belongs to this machine's
        sensors and is only checked to be a number.
        """
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
        # the count in that sentence comes from the registry on both sides of the door:
        # an earlier version of this line pinned the word "five", so a sixth drawn theme
        # could only ever have made it red for the wrong reason
        self.assertIn(f"one of the {len(render.THEMES)} this program draws from "
                      f"`render.py`", said, said[-400:])
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
        for phrase in ("two possibilities, and those words say which",
                       "took only the drawn names",
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
