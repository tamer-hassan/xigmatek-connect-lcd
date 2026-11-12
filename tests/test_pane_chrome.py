#!/usr/bin/env python3
"""Chrome, menus and one keystroke: four claims about the window that no check held.

Found while re-pointing this repository's pages and comments at the checks that own them.  Four
sentences said "the gate" or "the suite" and named nothing that exists: three described behaviour
that `tools/selftest.sh` gated and that was never ported, and one described a rule that had only
ever been held by nobody complaining.  Rather than quietly downgrade the sentences, this file
holds them.

Four rules, all offscreen, all with no panel attached and no session file written:

* **the marks never reach the frame.**  The dashed selection box, its eight grab squares and any
  guide line are painted in the pane's own `paintEvent`, *over* the picture.  Two readings have to
  disagree and two have to agree: the widget rendered with a mark up and the widget rendered
  without one differ, which is what proves the chrome is being painted at all; the pixmap the label
  is handed, and the image the model painted, are identical with and without it.  If chrome ever
  leaked into the frame, every pixel claim in this repository would be about a picture with a
  selection box burnt into it;
* **a value menu shows the value the row holds, not the first entry of its vocabulary.**  The
  accident was real and it hid in a lucky case: `arcPaint` reads `render`, `render` sorts first,
  so the one field already covered looked right while a `special` drawing `dual-status` was shown
  as `clock-readings` and a `data` row as whichever `source` sorts first.  The check therefore
  looks only at fields whose stored value is *not* the vocabulary's first answer, and fails if no
  such field was ever reached;
* **the tray's theme list is the window's theme list.**  Both come from `sorted(render.THEMES)`,
  built by the shipped builder, and a tray listing something else - or the 28 layout names - would
  be a second answer to the one question a reader asks without opening the window.  A desktop with
  no StatusNotifier host cannot build a tray at all, so that case says so and skips;
* **the upload keystroke stays the window's, and the field keeps its text.**  `Ctrl+Shift+U` is
  readline's upcase-word in some hands; while the button held a bare `Ctrl+U`, pressing it in a
  text field queued an upload and left the edit alone.  The pair that has to hold, as docs/gui.md
  says, is that the chord still reaches the window's action *and* the focused field's text does not
  move.
"""
from __future__ import annotations

import unittest

from PyQt6.QtCore import QEvent, Qt as QQt
from PyQt6.QtGui import QKeyEvent, QKeySequence

from tests import fixtures

from xigmalcd import render, themes
from xigmaui import app, edit as gui_edit

MISSING_PORT = "/dev/xigma-no-such-port"

#: The two fields whose vocabularies are long enough for the wrong-answer bug to be visible: a
#: `special` row names a registered drawing, a `data` row names a reading.
VOCABULARY_FIELDS = ("name", "source")


def first_lucky_field(editor) -> tuple:
    """The first `(row, field, stored, vocabulary)` in this layout whose stored value is *not* the
    vocabulary's sorted-first answer - the case the old bug hid in.  Empty when every field of the
    layout happens to be right by sorting order."""
    for index, widget in enumerate(editor.widgets()):
        pr = (widget.get("property") or [{}])[0]
        for field in VOCABULARY_FIELDS:
            if field not in gui_edit.field_names(widget.get("type")):
                continue
            stored = str(pr.get(field) or "")
            vocab = gui_edit.choices(field)
            if stored and stored in vocab and stored != vocab[0]:
                return (index, field, stored, tuple(vocab))
    return ()


def every_lucky_field(editor) -> list:
    """All the fields whose stored value is not the vocabulary's sorted-first answer, so one
    layout covering `source` cannot leave `name` asserted by nobody."""
    out = []
    for index, widget in enumerate(editor.widgets()):
        pr = (widget.get("property") or [{}])[0]
        for field in VOCABULARY_FIELDS:
            if field not in gui_edit.field_names(widget.get("type")):
                continue
            stored = str(pr.get(field) or "")
            vocab = gui_edit.choices(field)
            if stored and stored in vocab and stored != vocab[0]:
                out.append((index, field, stored, tuple(vocab)))
    return out


def layouts_with_a_non_first_value() -> list:
    """Every selectable layout that has at least one such field, derived from the files rather
    than picked by hand."""
    pick, _reject = themes.scan()
    names = sorted(themes.EXPORTS) + [r["name"] for r in pick]
    found = []
    for name in names:
        try:
            editor = gui_edit.Editor.open_theme(name)
        except Exception:                                       # noqa: BLE001
            continue
        if first_lucky_field(editor):
            found.append(name)
    return found


class PaneHarness(fixtures.FreshConfigRoot):
    """One shown window with a layout open in the editor."""

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, None, restore=False)
        self.win.show()
        self.win.resize(1600, 1200)
        fixtures.pump(0.4)
        self.addCleanup(fixtures.close_window, self.win)

    def open_layout(self, name: str) -> None:
        self.win.ed_name.setCurrentText(name)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, f"opening {name} left no editor")


class TheMarksStayOutOfTheFrame(PaneHarness):
    CANDIDATE = "alpha"

    @classmethod
    def setUpClass(cls):
        # the clock is pinned for this class only: the window repaints once a second,
        # and two reads across a repaint boundary are two different frames.  The hook
        # goes back in tearDownClass - a pin that outlives its own file turns a later
        # file's 'does this picture move?' question into a false answer, which is a
        # failure this repository has already paid for once
        super().setUpClass()
        cls._clock = fixtures.freeze_clock(render)

    @classmethod
    def tearDownClass(cls):
        render._now = cls._clock
        super().tearDownClass()

    def test_a_mark_is_painted_on_the_widget_and_never_in_the_picture(self):
        fixtures.freeze_clock(render)
        self.open_layout(self.CANDIDATE)
        self.win.ed.select(0)
        fixtures.pump(0.2)
        self.assertTrue(self.win.preview.marks,
                        "no mark was up, so the two comparisons below mean nothing")
        frame_without = self.win.preview.pixmap()
        image_without = self.win._pix
        widget_without = self.win.preview.grab()
        self.assertGreater(frame_without.width(), 0, "the pane drew nothing to compare")

        # no pump between the two readings: a repaint re-applies the selected row's
        # marks (docs/gui.md states that rule), so pumping here would put them back
        # by design and the comparison would be of one marked frame against itself
        self.win.preview.set_marks(None)
        self.assertIsNone(self.win.preview.marks, "clearing the marks did not take")
        frame_clear = self.win.preview.pixmap()
        image_clear = self.win._pix
        widget_clear = self.win.preview.grab()

        self.assertNotEqual(widget_without.toImage(), widget_clear.toImage(),
                            "the mark is not being painted over the pane at all, so the check "
                            "below is comparing two absences")
        self.assertEqual(frame_without.toImage(), frame_clear.toImage(),
                         "a mark changed the pixmap the label is handed: chrome reached the frame")
        self.assertEqual(image_without.toImage(), image_clear.toImage(),
                         "a mark changed the image the model painted")

        # the other half of the same rule: the chrome belongs to the *selection*, not to the
        # last press, so the next repaint paints it back for the row that is still selected
        self.win.preview.update()
        fixtures.pump(0.4)
        self.assertTrue(self.win.preview.marks,
                        "the repaint left the pane unmarked while a row was still selected: "
                        "the chrome follows the last press rather than the selection")


class TheMenusSayWhatTheRowHolds(PaneHarness):
    def test_a_value_menu_shows_the_rows_own_value_not_the_first_choice(self):
        """Only the unlucky cases are asserted, and reaching one of them is itself an assertion."""
        seen = set()
        for name in layouts_with_a_non_first_value():
            self.open_layout(name)
            for index, field, stored, vocab in every_lucky_field(self.win.ed):
                # the pane's own door, not the model's: picking a widget here is what a
                # reader does, and it is the door that rebuilds the field rows
                self.win.ed_widget.setCurrentIndex(index)
                fixtures.pump(0.25)
                self.assertIn(field, self.win.ed_rows,
                              f"{name} row {index}: no control for {field!r}")
                self.assertEqual(self.win.ed_rows[field][4], "menu",
                                 f"{name}.{field} is not a menu this check can read")
                ctl = self.win.ed_rows[field][2]
                self.assertEqual(ctl.currentText(), stored,
                                 f"{name} row {index}: the menu shows "
                                 f"{ctl.currentText()!r}, the row holds {stored!r}, "
                                 f"and the vocabulary starts {vocab[0]!r}")
                seen.add(field)
        self.assertEqual(seen, set(VOCABULARY_FIELDS),
                         f"only {sorted(seen)} were ever reached at a vocabulary whose first "
                         f"answer is wrong, so the lucky case is all this check has looked at")

    def test_the_trays_theme_list_is_the_windows_theme_list(self):
        if not app.QSystemTrayIcon.isSystemTrayAvailable():
            raise unittest.SkipTest("no StatusNotifier host on this platform, so the tray this "
                                    "check reads cannot be built here - skipped, not passed")
        self.win._build_tray()
        self.assertIsNotNone(self.win.tray, "a tray was available and none was built")
        from_tray = [a.text() for a in self.win.tray_theme_menu.actions()]
        from_combo = [self.win.theme.itemText(i) for i in range(self.win.theme.count())]
        self.assertEqual(from_tray, sorted(render.THEMES), from_tray)
        self.assertEqual(from_combo, sorted(render.THEMES), from_combo)
        self.assertEqual(from_tray, from_combo,
                         f"the tray offers {from_tray} and the window offers {from_combo}")


class TheKeystrokeStaysTheWindows(PaneHarness):
    CANDIDATE = "alpha"

    def test_ctrl_shift_u_reaches_the_window_and_moves_no_text(self):
        self.assertEqual(self.win.btn_upload.shortcut(), QKeySequence("Ctrl+Shift+U"),
                         "the chord moved, and docs/gui.md still describes this one")
        self.open_layout(self.CANDIDATE)
        box = self.win.ed_newname
        box.setFocus()
        box.setText("a name nobody pressed a chord on")
        fixtures.pump(0.2)
        before = list(self.win._log_lines)

        self.win.raise_()
        self.win.activateWindow()
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            app.QApplication.sendEvent(self.win, QKeyEvent(
                kind, QQt.Key.Key_U, QQt.KeyboardModifier.ControlModifier |
                QQt.KeyboardModifier.ShiftModifier))
        fixtures.pump(0.3)

        after = self.win._log_lines[len(before):]
        self.assertTrue(after, "the chord did nothing at all: no action, no log line")
        said = " ".join(after).lower()
        # on a bench with no display running, the panel path answers by trying the port
        # and failing: that line *is* the chord reaching the window's own action, which
        # is the half of the pair this check needs.  The other half is the field below.
        self.assertTrue(any(word in said for word in
                            ("upload", "background", "clip", "cannot open")),
                        f"the chord reached nothing recognisable: {said[:240]}")
        self.assertEqual(box.text(), "a name nobody pressed a chord on",
                         "the focused field's text moved under the chord")


if __name__ == "__main__":
    unittest.main(verbosity=2)
