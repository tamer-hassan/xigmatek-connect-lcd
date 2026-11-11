#!/usr/bin/env python3
"""The canvas as a door: a point on the pane is a point on the glass, and moving a row costs one step.

Ported from the canvas blocks of `tools/selftest.sh`'s GUI section.  Two halves:

* **`Canvas.to_panel`**, the mapping the window uses to turn a click into a row: the 480 px glass
  inside whatever the column gave the pane, with letterboxing where it does not fit.  Before the first
  draw nothing is addressable; the glass's corners map to the picture's corners; a point in a band
  answers None rather than selecting the row nearest to it;
* **`Editor.hit` and `Editor.move`**, where the draw-order law lives: overlapping rows resolve to the
  later row in the file, a row the painter skipped is not hittable, and a move writes the row's own
  coordinate fields in exactly one undo step - while a move that would put the anchor off the canvas
  is refused whole.

An anchor may legally sit at the last column while its ink hangs off the glass.  That is a fact about
these themes' text anchors, and `validate` says nothing about it - refusing it would reject files the
vendor ships and draws.
"""
from __future__ import annotations

import unittest

from tests import fixtures

from xigmalcd import render, themes
from xigmaui import app, edit as gui_edit

MISSING_PORT = "/dev/xigma-no-such-port"


class ThePanesDoor(fixtures.FreshConfigRoot):
    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, 1.0, restore=False)
        self.win.show()
        fixtures.pump(0.15)
        self.win._repaint()
        self.canvas = self.win.preview

    def tearDown(self):
        fixtures.close_window(self.win)
        super().tearDown()

    def point(self, x, y):
        from PyQt6.QtCore import QPoint
        return QPoint(int(x), int(y))

    def test_before_the_first_draw_nothing_is_addressable(self):
        self.canvas.side = 0
        self.assertIsNone(self.canvas.to_panel(self.point(10, 10)),
                          "with no picture on the pane, a click cannot name a panel pixel")

    def test_the_glass_corners_map_to_the_pictures_corners(self):
        self.assertGreater(self.canvas.side, 0, "the pane never drew anything")
        ox, oy = self.canvas._origin()
        self.assertEqual(self.canvas.to_panel(self.point(ox, oy)), (0, 0),
                         f"origin {ox},{oy} side {self.canvas.side}")
        self.assertEqual(self.canvas.to_panel(self.point(ox + self.canvas.side - 1,
                                                         oy + self.canvas.side - 1)),
                         (render.W - 1, render.H - 1))

    def test_a_point_in_the_letterboxing_addresses_no_row(self):
        side = self.canvas.side
        self.canvas.setFixedHeight(side + 60)       # force a band top and bottom
        fixtures.pump(0.1)
        ox, oy = self.canvas._origin()
        self.assertGreaterEqual(oy, 20, "the pane did not actually gain a band")
        self.assertIsNone(self.canvas.to_panel(self.point(ox + 5, oy - 10)),
                          "a click in the band selected a row")
        self.assertIsNotNone(self.canvas.to_panel(self.point(ox + 5, oy + 5)))

    def test_a_wider_pane_still_maps_a_480_px_glass_not_an_upscaled_one(self):
        self.canvas.setFixedWidth(render.W + 200)
        fixtures.pump(0.1)
        self.win._fit()
        self.assertLessEqual(self.canvas.side, render.W,
                             "the pane upscaled a 480 px frame instead of letterboxing it")
        ox, oy = self.canvas._origin()
        self.assertEqual(self.canvas.to_panel(self.point(ox, oy)), (0, 0))


class HitAndMove(unittest.TestCase):
    """Which row a point belongs to, and what moving it costs."""

    def setUp(self):
        self.ed = gui_edit.Editor.open_theme("Theme_28")
        self.img, self.notes = self.ed.paint(*self.ed.fixture())

    def boxes_by_row(self) -> dict:
        return {r[3]: r[2] for r in self.notes["boxes"]}

    def test_every_painted_row_can_be_pointed_at(self):
        boxes = self.boxes_by_row()
        self.assertNotEqual(boxes, {}, "this layout painted nothing to point at")
        unaddressable = []
        for index, row in enumerate(self.ed.widgets()):
            box = boxes.get(index)
            if box is None:
                continue
            probe = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
            if self.ed.hit(self.notes, *probe) != index:
                unaddressable.append((index, row["type"], probe, self.ed.hit(self.notes, *probe)))
        self.assertEqual(unaddressable, [], f"painted rows that do not answer to their own "
                                           f"centre: {unaddressable[:4]}")

    def test_a_row_the_painter_skipped_is_not_hittable(self):
        painted = set(self.boxes_by_row())
        skipped = [i for i in range(len(self.ed.widgets())) if i not in painted]
        self.assertNotEqual(skipped, [], "this layout skips no rows, so the "
                                "check below would be empty")
        for index in skipped:
            self.assertNotEqual(self.ed.hit(self.notes, 10, 10), index,
                                f"row {index} is skipped and has no ink to click")

    def test_overlap_resolves_to_the_row_the_file_lists_later(self):
        boxes = self.boxes_by_row()
        order = self.ed.widgets()
        pair = None
        for i in sorted(boxes):
            for j in sorted(boxes):
                if j <= i:
                    continue
                a, b = boxes[i], boxes[j]
                left, right = max(a[0], b[0]), min(a[2], b[2])
                top, bottom = max(a[1], b[1]), min(a[3], b[3])
                if left < right and top < bottom:
                    pair = (i, j, ((left + right) // 2, (top + bottom) // 2))
                    break
            if pair:
                break
        if not pair:
            self.skipTest("no two rows in Theme_28 overlap at this reading")
        first, second, probe = pair
        self.assertEqual(self.ed.hit(self.notes, *probe), second,
                         f"rows {first} and {second} overlap at {probe}: the later row in the "
                         "file is the one on top, and it is what a click means")

    def test_a_move_writes_both_coordinates_in_one_step_and_writes_no_file(self):
        self.assertEqual(themes.user_copies(), [], themes.user_copies())
        self.ed.select(0)
        x0, y0 = int(self.ed.value("x")), int(self.ed.value("y"))
        ok, note = self.ed.move(6, -4)
        self.assertTrue(ok, note)
        self.assertEqual((int(self.ed.value("x")), int(self.ed.value("y"))), (x0 + 6, y0 - 4), note)
        self.assertEqual(self.ed.steps, 1, "a drag is one undo step, not one per pixel")
        self.assertEqual(themes.user_copies(), [], "an in-memory move wrote a file")
        self.assertTrue(self.ed.undo())
        self.assertEqual((int(self.ed.value("x")), int(self.ed.value("y"))), (x0, y0))

    def test_a_no_op_move_takes_no_step_and_a_whole_off_canvas_move_is_refused(self):
        self.ed.select(0)
        self.ed.move(0, 0)
        self.assertEqual(self.ed.steps, 0, "an empty drag took an undo step")
        ok, note = self.ed.move(-10_000, 0)
        self.assertFalse(ok, note)
        self.assertEqual(self.ed.steps, 0, "a refused move took an undo step")
        self.assertIn("inside", note, note)

    def test_an_anchor_at_the_last_column_is_legal_even_when_the_ink_hangs_off(self):
        self.ed.select(0)
        ok, note = self.ed.set("x", render.W - 1)
        self.assertTrue(ok, note)
        hard, soft = themes.validate(self.ed.obj)
        self.assertEqual(hard, [], hard)
        self.assertFalse(any("canvas" in finding for finding in soft),
                         f"validate objected to a legal anchor: {soft}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
