#!/usr/bin/env python3
"""Opening a layout: the menu that nobody re-read, and the file no root holds.

Reported on 2026-11-12: *"I discovered a bug where I have no way of opening & loading a
previously saved layout in xigmaui."*  Two separate faults hid inside that one sentence, and
both are gated here rather than argued about:

* **the menu was a snapshot.**  The layout list is built once, when the window is, and was
  rebuilt only after a rename, a save-as or a revert **in that window**.  So a copy that
  appeared by any other door - the CLI's `themes.save`, a second window, a file dropped into
  `~/.config/xigmalcd/themes` by hand - stayed invisible until a restart.  `reload the list`
  is the door now, and the sentence it prints counts what the roots answer *at that moment*,
  out of `themes.scan()` and `themes.user_copies()` - the same two doors `--list-themes` speaks.
* **a path was not a name.**  The menu can only hold what `themes.resolve` reaches: three roots
  and nothing else.  A layout file anywhere else - one copied off another machine, the
  `<name>.json.bak` a save leaves behind, the output of `--export-theme` pointed at a file -
  could not be opened at all.  `open a file…` is that door, and it is honest about the one
  thing it cannot do: **applying a layout sends a name, not a path**, so until the copy is in a
  root the display reads, the panel cannot be told to draw it.

The rules that keep the second door safe are the file model's own: opening writes nothing, a
save goes to the one writable directory, and no layout file is ever sent to the panel.  What is
new is that the window **says which file it is holding** - a layout opened by path is the one
thing in this program whose picture is not yet a picture a loop can draw, and a reader who is
not told that presses `apply to the panel` and is confused twice over.

Nothing here touches a port: the apply checks run on the in-process stub control of
`tests/test_display_remote.py`, and one of them asserts that a refusal leaves **nothing queued**
on that stub's behalf.  The file dialog itself is not drivable headless, so the check drives the
window's one asking step (`_ed_ask_path`), which is why that step exists on its own.

Thirteen checks, in three classes: the menu (`TheMenuThatNobodyReReads`), the path door
(`AFileThatIsNotInALibrary`), and what the panel can be told about what it draws
(`ApplyingWhatThePanelCannotSee`).
"""
from __future__ import annotations

import copy
import json
import os
import unittest

from PyQt6.QtCore import Qt

from tests import fixtures

from tests.test_display_remote import DisplayHarness

from xigmalcd import themes
from xigmaui import app, edit

#: A port no display answers: every window check uses one.
MISSING_PORT = "/dev/xigma-no-such-port"

#: A name written out under a directory no root reads, so no library layout answers it.
FOREIGN = "stray_layout"


def foreign_file(root: str, name: str = FOREIGN, export: str = "bars") -> str:
    """One generated layout, written under `root` at a name no root answers."""
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(themes.export(export), fh)
    return path


class OpeningAWindow(fixtures.FreshConfigRoot):
    """One shown window: no port, nothing remembered from a previous session."""

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, None, restore=False, tray=False)
        self.win.show()
        self.win.resize(1440, 1024)
        fixtures.pump(0.4)
        self.addCleanup(fixtures.close_window, self.win)

    def names_in_menu(self) -> list:
        return [self.win.ed_name.itemText(i) for i in range(self.win.ed_name.count())
                if self.win.ed_name.itemText(i) != app.NO_EDITOR]


class TheMenuThatNobodyReReads(OpeningAWindow):
    """A copy that appeared by another door becomes visible on purpose, not by restart."""

    def test_a_copy_written_after_the_window_opens_waits_for_the_list_to_be_read(self):
        """The fault as reported, and the door that answers it.

        Written by `themes.save` - the CLI's door, the one a person means when they say "I
        saved a layout" - then looked for in the menu this window built at startup.  It is not
        there, which is the report; then the button is clicked and the same name answers with
        no restart.
        """
        path, _soft = themes.save(themes.export("alpha"), "late_copy")
        self.assertTrue(os.path.exists(path), f"{path} was not written")
        self.assertNotIn("late_copy", self.names_in_menu(),
                         "the menu already knew a file written after the window was built, so "
                         "nothing below measures the fault this check names")
        self.win.ed_reload.click()
        fixtures.pump(0.2)
        self.assertIn("late_copy", self.names_in_menu(),
                      "`reload the list` did not pick up a copy sitting in the user root")
        self.win.ed_name.setCurrentText("late_copy")
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, "the copy is listed but does not open")
        self.assertEqual((self.win.ed.name, self.win.ed.origin), ("late_copy", "your copy"))

    def test_the_reload_says_what_the_roots_answer_at_that_moment(self):
        """The counts in that sentence are read out of the doors, never typed as prose."""
        themes.save(themes.export("alpha"), "counted_copy")
        pick, _reject = themes.scan()
        copies = themes.user_copies()
        self.assertIn("counted_copy", copies, "there is no copy to count, so the note is empty")
        self.win.ed_reload.click()
        fixtures.pump(0.2)
        said = self.win.ed_note.text()
        self.assertIn("re-read", said, said[:220])
        self.assertIn(f"{len(copies)}", said,
                      f"the note does not count the {len(copies)} copies it found: {said[:220]}")
        for name in copies:
            self.assertIn(name, said, f"the note does not name the copy `{name}`: {said[:220]}")
        self.assertEqual(len(self.names_in_menu()), len(themes.EXPORTS) + len(pick),
                         "the menu and `themes.scan()` disagree about how many layouts the "
                         "roots hold")
        self.assertIn("Nothing was written", said,
                      f"the note does not say what the press did not do: {said[:220]}")

    def test_reloading_never_re_reads_the_layout_that_is_open_and_unsaved(self):
        """The one thing this act must not do: lose an edit somebody typed.

        The menu is rebuilt with its signals blocked, so the buffer in memory is never read back
        off disk - and the proof is a number the window holds and the file does not.
        """
        path, _soft = themes.save(themes.export("alpha"), "keepme")
        self.win.ed_reload.click()                 # the copy appeared by another door
        fixtures.pump(0.2)
        self.win.ed_name.setCurrentText("keepme")
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, "no layout open, so the edit below is not an edit")
        row = next(i for i, w in enumerate(self.win.ed.widgets()) if "x" in w["property"][0])
        self.win.ed.select(row)
        self.win._editor_pick_widget(row)
        fixtures.pump(0.2)
        box = self.win.ed_rows["x"][2]             # the window's own door for this field
        self.assertTrue(box.isEnabled(), "the x box is shut, so typing below changes nothing")
        box.setValue(int(box.value()) + 9)
        self.win._ed_apply_row("x", commit=True)
        fixtures.pump(0.2)
        typed = int(self.win.ed.prop()["x"])
        self.assertTrue(self.win.ed.dirty, "the typed move did not make the buffer dirty")
        on_disk = themes.load(path)["osd"]["widget"][row]["property"][0]["x"]
        self.assertNotEqual(on_disk, typed,
                            "file and buffer already agree before the reload, so nothing below "
                            "can show that the reload kept anything")
        self.win.ed_reload.click()
        fixtures.pump(0.2)
        self.assertEqual(int(self.win.ed.prop()["x"]), typed,
                         "`reload the list` re-read the open layout and lost the edit")
        self.assertTrue(self.win.ed.dirty, "the buffer went clean under a reload")
        self.assertEqual(themes.load(path)["osd"]["widget"][row]["property"][0]["x"], on_disk,
                         "an act that only re-lists wrote to the file")

    def test_the_two_doors_are_available_when_nothing_is_open(self):
        """They choose the file, so they cannot be gated on having one - or folded away."""
        self.assertIsNone(self.win.ed, "the window did not start with the editor closed")
        for name in ("ed_open", "ed_reload"):
            with self.subTest(control=name):
                wid = getattr(self.win, name)
                self.assertTrue(wid.isEnabled(),
                                f"{name} is shut until a layout is open, which is exactly the "
                                f"moment it is needed")
                self.assertTrue(wid.isVisible(), f"{name} is not on screen")
                self.assertNotIn(wid, self.win._adv_hide,
                                 f"{name} folds away with the knobs that write settings")
        self.win.adv_toggle.setChecked(False)
        fixtures.pump(0.2)
        for name in ("ed_open", "ed_reload"):
            with self.subTest(advanced="off", control=name):
                self.assertTrue(getattr(self.win, name).isVisible(),
                                f"{name} disappeared when `advanced controls` came off")


class AFileThatIsNotInALibrary(OpeningAWindow):
    """`open a file…`: a layout at a path, and the honesty that has to come with it."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.config_root, "elsewhere")
        self.path = foreign_file(self.root)

    def test_a_file_outside_the_roots_opens_and_paints(self):
        self.assertNotIn(FOREIGN, self.names_in_menu(),
                         "the roots already answer that name, so the door below would be "
                         "opening a library layout and calling it a foreign file")
        self.win._editor_open_path(self.path)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, "a layout file outside the roots did not open")
        self.assertEqual(self.win.ed.origin, edit.PATH_ORIGIN, self.win.ed.origin)
        self.assertEqual(self.win.ed.opened, os.path.abspath(self.path),
                         "the model does not know which file it read")
        self.assertEqual(self.win.ed.path, themes.user_theme_path(FOREIGN),
                         "a save from a by-path buffer would go somewhere other than the one "
                         "writable directory")
        self.assertEqual(len(self.win.ed.widgets()),
                         len(themes.export("bars")["osd"]["widget"]),
                         "part of the layout was lost on the way in")
        lit = sum(1 for v in self.win._osd.getchannel("A").get_flattened_data() if v)
        self.assertGreater(lit, 500, f"the pane painted almost nothing: {lit} lit px")
        said = self.win.ed_state.text()
        for needle in (os.path.abspath(self.path), "no root", "save it as your copy"):
            self.assertIn(needle, said, f"the state line does not say {needle!r}: {said[:300]}")
        self.assertIn(FOREIGN, self.names_in_menu(),
                      "the menu lost the entry for the layout this window is holding")
        self.assertEqual(self.win.ed_name.currentText(), FOREIGN,
                         "the menu is not showing the layout that is open")
        # and it survives the other door: a rebuild of the menu from the roots must keep the
        # one entry the roots cannot produce, or the reader has no way back to this file
        self.win.ed_reload.click()
        fixtures.pump(0.2)
        self.assertIn(FOREIGN, self.names_in_menu(),
                      "`reload the list` rebuilt the menu from the roots and dropped the entry "
                      "for a layout this window had opened by path")
        at = self.win.ed_name.findText(FOREIGN)
        tip = str(self.win.ed_name.itemData(at, Qt.ItemDataRole.ToolTipRole) or "")
        self.assertIn(os.path.abspath(self.path), tip,
                      f"the entry does not say which file it opens: {tip[:160]!r}")

    def test_picking_a_by_path_entry_again_reads_the_file_off_disk_again(self):
        """The other half of the report: getting a saved layout **back**, edits and all.

        Somebody else changes the file on disk - another window, a text editor, `git`.  Picking
        the entry again re-reads it, which is what "loading" has to mean for a layout that never
        entered the library.
        """
        self.win._editor_open_path(self.path)
        fixtures.pump(0.4)
        name, before = self.win.ed.name, self.win.ed.obj
        mine = copy.deepcopy(themes.load(self.path))
        for w in mine["osd"]["widget"]:
            w["property"][0]["x"] = int(w["property"][0].get("x") or 0) + 11
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(mine, fh)
        self.win.ed_name.setCurrentText(app.NO_EDITOR)
        fixtures.pump(0.3)
        self.win.ed_name.setCurrentText(name)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, "the by-path entry did not survive, let alone reopen")
        got = [w["property"][0]["x"] for w in self.win.ed.widgets()]
        want = [w["property"][0]["x"] for w in mine["osd"]["widget"]]
        self.assertEqual(got, want,
                         "re-picking the entry kept the buffer it had already read, so the "
                         "file's new contents never arrived")
        self.assertNotEqual(self.win.ed.obj, before, "the reopen handed back the same object")
        self.assertIn(os.path.abspath(self.path), self.win.ed_state.text())

    def test_every_refusal_quotes_the_path_it_refused(self):
        """Five ways a path is not a layout, each answered in words, none of them a crash."""
        with open(os.path.join(self.root, "junk.json"), "w") as fh:
            fh.write("{not json at all")
        with open(os.path.join(self.root, "metrics.json"), "w") as fh:
            json.dump({"cpu": {"temperature": 91.0}}, fh)
        wide = foreign_file(self.root, "wide_layout")
        obj = copy.deepcopy(themes.load(wide))          # never mutate `themes.load`'s cached one
        obj.update({"ratio": "4:3", "width": 320, "height": 240})
        with open(wide, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        for bad, needle in ((os.path.join(self.root, "never_written.json"), "nothing at"),
                            (self.root, "directory"),
                            (os.path.join(self.root, "junk.json"), "not JSON"),
                            (os.path.join(self.root, "metrics.json"), "not a layout"),
                            (wide, "4:3")):
            with self.subTest(refused=bad):
                self.win._editor_open_path(bad)
                fixtures.pump(0.1)
                said = self.win.ed_note.text()
                self.assertIn(bad, said,
                              f"the refusal does not name what was refused: {said[:240]}")
                self.assertIn(needle, said,
                              f"the refusal for {bad} does not say {needle!r}: {said[:240]}")
        self.win._editor_open_path(self.path)
        fixtures.pump(0.3)
        holding = self.win.ed.name
        self.win._editor_open_path(os.path.join(self.root, "never_written.json"))
        fixtures.pump(0.1)
        self.assertEqual(self.win.ed.name, holding,
                         "a failed open closed the layout that was open")

    def test_a_path_the_roots_do_hold_opens_with_the_library_s_own_words(self):
        """`~/.config/xigmalcd/themes/x.json` **is** the layout called `x`: say that, not this."""
        path, _soft = themes.save(themes.export("alpha"), "known_file")
        self.win._editor_open_path(path)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, "a library file opened by path did not open")
        self.assertEqual(self.win.ed.origin, "your copy",
                         "a layout the roots answer was labelled a foreign file, which hides "
                         "the fact that a loop already draws it")
        self.assertNotIn("known_file", self.win._ed_paths,
                         "a library layout was remembered as a by-path open")
        self.assertNotIn(edit.PATH_ORIGIN, self.win.ed_state.text(), self.win.ed_state.text())

    def test_the_button_asks_for_a_path_and_opens_what_it_is_given(self):
        """The wiring, not Qt's dialog: the asking step is where a path comes from.

        `_ed_ask_path` is the window's one step that talks to a file dialog, and it is a step of
        its own precisely so a check can stand in for it: a native dialog cannot be driven
        headless, and a door whose prompt cannot be replaced is a door nothing can prove works.
        The stand-in calls through to the shipped one to read the directory it would open **at**,
        rather than asserting a path nobody chose - a dialog that starts in `/` when layouts live
        under `~/.config/xigmalcd/themes` is a dialog that tells the reader "this is not where I
        expect files".
        """
        asked = []
        self.win._ed_ask_path = lambda: (asked.append(self.path), self.path)[1]
        self.win.ed_open.click()
        fixtures.pump(0.4)
        self.assertEqual(asked, [self.path],
                         "clicking `open a file…` did not ask for a path")
        # where that dialog would have started, read from the shipped step rather than
        # assumed: the reader's own copies, which is the state this door exists for
        themes.save(themes.export("alpha"), "a_copy_first")
        start = self.win._ed_start_dir()
        self.assertTrue(os.path.isdir(start), f"the dialog would open at {start!r}, a directory "
                                              f"that does not exist")
        self.assertEqual(os.path.realpath(start), os.path.realpath(themes.user_root()),
                         f"the dialog opens at {start!r}, not where this program's own copies "
                         f"live, {themes.user_root()}")
        # and the fallback for a box that has never saved one, which is this bench's state
        real_root = themes.user_root
        themes.user_root = lambda: os.path.join(self.config_root, "never_created")
        try:
            fell = self.win._ed_start_dir()
        finally:
            themes.user_root = real_root
        self.assertTrue(os.path.isdir(fell),
                        f"with no user root, the dialog would open at {fell!r}, which does not "
                        f"exist - Qt then puts the reader wherever it likes")
        self.assertIsNotNone(self.win.ed, "the path that was named never reached the door")
        self.assertEqual(self.win.ed.opened, os.path.abspath(self.path))

    def test_a_cancelled_dialog_changes_nothing(self):
        """Cancel is an answer, and the right one: the window stays exactly as it was."""
        self.win._editor_open_path(self.path)
        fixtures.pump(0.4)
        holding, note = self.win.ed.name, self.win.ed_note.text()
        self.win._ed_ask_path = lambda: ""
        self.win.ed_open.click()
        fixtures.pump(0.3)
        self.assertIsNotNone(self.win.ed, "a cancelled dialog closed the open layout")
        self.assertEqual(self.win.ed.name, holding, "a cancelled dialog changed the layout")
        self.assertEqual(self.win.ed_note.text(), note, "a cancelled dialog wrote a note")


class ApplyingWhatThePanelCannotSee(DisplayHarness):
    """`apply to the panel` sends a **name**, so a by-path layout is refused before sending."""

    def setUp(self):
        super().setUp()
        self.root = os.path.join(self.config_root, "elsewhere")
        self.path = foreign_file(self.root)

    def names_in_menu(self) -> list:
        return [self.win.ed_name.itemText(i) for i in range(self.win.ed_name.count())
                if self.win.ed_name.itemText(i) != app.NO_EDITOR]

    def test_a_foreign_layout_is_refused_and_nothing_reaches_the_display(self):
        before = (self.args.theme, self.args.mp4, self.args.clock_size, self.args.scrim)
        self.win._editor_open_path(self.path)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, "the by-path layout did not open")
        self.win.ed_apply_panel.click()
        fixtures.pump(0.3)
        self.assertEqual((self.args.theme, self.args.mp4, self.args.clock_size, self.args.scrim),
                         before, "a refused apply moved one of the display's settings")
        self.assertIsNone(self.ctl.take(),
                          "the refusal queued a command: refusing has to mean nothing was sent")
        said = self.logs()
        self.assertIn("nothing sent", said, said[-500:])
        self.assertIn("*name*", said,
                      f"the refusal does not say why a path cannot be sent: {said[-500:]}")
        self.assertIn(themes.user_root(), said,
                      f"the refusal does not say where to put the file instead: {said[-500:]}")

    def test_saving_it_as_a_copy_is_what_makes_the_same_press_work(self):
        """The refusal has exactly one answer, and this walks it: save, then apply."""
        self.win._editor_open_path(self.path)
        fixtures.pump(0.4)
        self.win._editor_pick_widget(0)
        box = self.win.ed_rows["x"][2]
        box.setValue(int(box.value()) + 4)
        self.win._ed_apply_row("x", commit=True)
        fixtures.pump(0.2)
        self.assertTrue(self.win.ed.dirty, "the typed move did not make the buffer dirty")
        self.win.ed_save.click()
        fixtures.pump(0.5)
        self.assertIn(FOREIGN, themes.user_copies(),
                      f"`save as your copy` did not put a file in {themes.user_root()}, "
                      f"so the press below had nothing to name")
        self.assertIn(FOREIGN, self.names_in_menu(),
                      "the menu never learned the name the copy now answers")
        said = self.win.ed_state.text()
        self.assertIn("saved as your copy", said, said[:300])
        self.assertNotIn("different file", said, said[:300])
        self.win.ed_apply_panel.click()
        fixtures.pump(0.4)
        self.assertEqual(self.args.theme, FOREIGN,
                         "the copy is in the user root and the display was not told to draw it")
        self.assertIn(f"panel draws {FOREIGN}", self.logs(), self.logs()[-500:])

    def test_a_foreign_file_at_a_name_the_library_answers_says_which_file_would_win(self):
        """The sharpest edge of the door: one name, two files, and only one is drawable.

        Opening `/somewhere/Theme_nn.json` - a copy of a vendor layout, made by hand or by a
        backup tool - is legitimate.  But the panel can only be told the *name*, which answers
        from the library, so the state line has to name both files and the press has to refuse
        rather than let a display draw something the reader never looked at.
        """
        vendor = next(r["name"] for r in themes.scan()[0] if not themes.is_copy(r["name"]))
        source = themes.resolve(vendor)["path"]
        os.makedirs(self.root, exist_ok=True)
        collide = os.path.join(self.root, vendor + ".json")
        with open(collide, "w", encoding="utf-8") as fh:
            json.dump(copy.deepcopy(themes.load(source)), fh)
        before = self.args.theme
        self.win._editor_open_path(collide)
        fixtures.pump(0.4)
        self.assertEqual(self.win.ed.origin, edit.PATH_ORIGIN,
                         "a file at a path was opened as the library's layout of that name")
        said = self.win.ed_state.text()
        for needle in ("different file", source):
            self.assertIn(needle, said,
                          f"the state line does not say {needle!r}: {said[:320]}")
        self.win.ed_apply_panel.click()
        fixtures.pump(0.3)
        self.assertEqual(self.args.theme, before,
                         "the display's theme moved under a refused apply")
        self.assertIsNone(self.ctl.take(), "a refused apply sent something to the port")
        self.assertIn(source, self.logs(),
                      "the refusal does not name the file the panel would have drawn")


if __name__ == "__main__":
    unittest.main(verbosity=2)
