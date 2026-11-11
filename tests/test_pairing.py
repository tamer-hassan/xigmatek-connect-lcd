#!/usr/bin/env python3
"""Background pairing: a layout names the clip underneath it, and the window honours that - or says
why it could not.

Ported from the pairing block of `tools/selftest.sh`'s GUI section.  The honest rule is **"pair it
when the file is here, say so when it is not"**, so both halves are checked: the layouts whose clip
this box can list, and the ones whose clip this box does not have.  What a box can honour is derived
from the rows it actually lists rather than assumed from one bench, because a checkout on its own -
nothing installed, no Windows partition mounted - is what a CI runner and a source install are.

The state that reads like a broken window is worth the most lines here: a layout declares a clip, the
preview refuses to move, and nothing else about the picture changed.  That is a person's bug report
("the button does nothing"), and the answer is that the note line says which box governs the picture
and the log carries the same sentence with the way back named.
"""
from __future__ import annotations

import os
import unittest

from tests import fixtures

from xigmalcd import render, themes
from xigmaui import app

MISSING_PORT = "/dev/xigma-no-such-port"


class LayoutsMoveThePicture(fixtures.FreshConfigRoot):
    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, 1.0, restore=False)
        self.win.show()
        fixtures.pump(0.15)
        self.addCleanup(fixtures.close_window, self.win)
        self.pick = themes.scan()[0]

    def base(self) -> str:
        return os.path.basename(self.win.mp4)

    def available(self) -> set:
        return {os.path.splitext(os.path.basename(c.path))[0].lower()
                for c in self.win.all_clips}

    def test_a_fresh_window_has_not_chosen_to_hold_a_background(self):
        self.assertFalse(self.win.keep_clip)
        self.assertFalse(self.win.chk_keep.isChecked(),
                         "populating the clip list selects a row, and that is not a choice")

    def test_every_layout_whose_clip_is_here_takes_its_own_clip(self):
        here = [rec for rec in self.pick
                if os.path.splitext(str(rec["background"]).rsplit("/", 1)[-1])[0].lower()
                in self.available()]
        self.assertGreater(here, [], "this window lists no clip any layout names, so the check "
                                     "below would prove nothing")
        moved, rows_ok = 0, 0
        for rec in here:
            self.win.ed_name.setCurrentText(rec["name"])
            fixtures.pump(0.05)
            moved += self.base() == rec["background"].rsplit("/", 1)[-1]
            row = self.win.clips.currentRow()
            if 0 <= row < len(self.win.all_clips):
                rows_ok += self.win.all_clips[row].path == self.win.mp4
        self.assertEqual(moved, len(here),
                         f"{moved} of {len(here)} layouts did not put their own clip under "
                         "the preview")
        self.assertEqual(rows_ok, len(here),
                         "the library column does not show the row it paired to")

    def test_a_layout_whose_clip_is_not_here_leaves_the_picture_and_says_which_file_is_missing(self):
        missing = [rec for rec in self.pick
                   if os.path.splitext(str(rec["background"]).rsplit("/", 1)[-1])[0].lower()
                   not in self.available()]
        for rec in missing:
            with self.subTest(layout=rec["name"]):
                want = rec["background"].rsplit("/", 1)[-1]
                self.win.ed_name.setCurrentText(rec["name"])
                fixtures.pump(0.05)
                self.assertNotEqual(self.base(), want,
                                    "a clip this box lacks became current")
                self.assertIn("does not have", self.win.pair_note,
                              "the picture stayed put with no sentence saying which file is away")

    def test_the_five_themes_drawn_from_code_pair_with_their_backdrops_too(self):
        for theme, clip in sorted(themes.CODE_CLIPS.items()):
            with self.subTest(theme=theme):
                self.win.theme.setCurrentText(theme)
                self.win.ed_name.setCurrentText(theme)
                fixtures.pump(0.05)
                self.assertEqual(self.base(), clip,
                                 "a theme this repository draws has no backdrop under it, which "
                                 "is the half of the complaint the pairing opened")


class ReaderHoldsThePicture(fixtures.FreshConfigRoot):
    """The box governs layouts, not the reader."""

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, 1.0, restore=False)
        self.win.show()
        fixtures.pump(0.15)
        self.addCleanup(fixtures.close_window, self.win)
        self.pick = themes.scan()[0]

    def base(self) -> str:
        return os.path.basename(self.win.mp4)

    def another_row(self) -> int:
        """A clip row that is not the one the open layout names, if this box has one."""
        wanted = os.path.basename(self.win.mp4)
        for row, clip in enumerate(self.win.all_clips):
            if os.path.basename(clip.path) != wanted:
                return row
        self.skipTest("this window lists one clip only, so there is nothing to hold")
        return -1

    def test_ticking_the_box_stops_layouts_moving_the_picture_but_not_a_row_click(self):
        self.win.chk_keep.setChecked(True)
        self.assertTrue(self.win.keep_clip, "the box did not reach the flag")
        other = self.another_row()
        self.win.clips.setCurrentRow(other)
        fixtures.pump(0.1)
        chosen = self.base()
        self.assertEqual(chosen, os.path.basename(self.win.all_clips[other].path),
                         "the box stopped a reader choosing a clip")
        stayed = 0
        for rec in self.pick[:6]:
            self.win.ed_name.setCurrentText(rec["name"])
            fixtures.pump(0.05)
            stayed += self.base() == chosen
        self.assertEqual(stayed, 6, "a layout walked over a background its reader held")

    def test_the_refusal_is_explained_in_the_log_with_the_way_back_named(self):
        self.win.chk_keep.setChecked(True)
        other = self.another_row()
        self.win.clips.setCurrentRow(other)
        fixtures.pump(0.1)
        for rec in self.pick[:2]:
            self.win.ed_name.setCurrentText(rec["name"])
            fixtures.pump(0.05)
        declined = [line for line in self.win._log_lines
                    if '"keep my background" is ticked' in line]
        self.assertGreaterEqual(len(declined), 1, self.win._log_lines[-4:])
        unlabelled = [line for line in declined if "Use this layout's own clip" not in line]
        self.assertEqual(unlabelled, [],
                         f"the log should name the control that gives the pair back: "
                         f"{unlabelled[:2]}")
        self.assertTrue(self.win.btn_pair.isEnabled(),
                        "the box is ticked and the window offers no way back from it")

    def test_the_way_back_takes_the_clip_and_unticks_the_box(self):
        self.win.chk_keep.setChecked(True)
        other = self.another_row()
        self.win.clips.setCurrentRow(other)
        fixtures.pump(0.1)
        self.win.ed_name.setCurrentText(self.pick[0]["name"])
        fixtures.pump(0.05)
        self.win.btn_pair.click()
        fixtures.pump(0.1)
        self.assertFalse(self.win.keep_clip)
        self.assertFalse(self.win.chk_keep.isChecked(),
                         "the way back took the clip without unticking the box, so the next "
                         "layout would move it and the box would say otherwise")
        self.assertEqual(self.base(), os.path.basename(self.win._pair_target),
                         "the way back did not hand the layout its own clip")

    def test_unticking_moves_the_picture_immediately_rather_than_at_the_next_layout(self):
        self.win.chk_keep.setChecked(True)
        other = self.another_row()
        self.win.clips.setCurrentRow(other)
        fixtures.pump(0.1)
        self.win.chk_keep.setChecked(False)
        fixtures.pump(0.1)
        self.assertEqual(self.base(), os.path.basename(self.win._pair_target),
                         "unticking the box left the picture on a clip the open layout does "
                         "not name")

    def test_a_click_on_a_row_previews_without_ticking_the_box(self):
        before = self.win.keep_clip
        other = self.another_row()
        self.win.clips.setCurrentRow(other)
        fixtures.pump(0.1)
        self.assertEqual(self.win.keep_clip, before,
                         "pointing at a clip row decided to hold it")
        self.assertIn("next layout change", "\n".join(self.win._log_lines).lower(),
                      "the window should say the pick will be overwritten by the next layout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
