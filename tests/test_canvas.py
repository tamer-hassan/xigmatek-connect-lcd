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


class AReadOfTheMachineIsNotPartOfAnEdit(fixtures.FreshConfigRoot):
    """An act on the editor repaints the file; it must not re-read this box.

    The pane's layer paint begins with `sensors.collect()`, which is what puts the machine's
    numbers in the line under the picture.  With a layout open that reading paints nothing:
    `Editor.paint` draws the file at the pinned fixture, deliberately, so a field change is the
    only thing that can move a pixel.  So every mouse-move of a drag - and every arrow-key
    repeat - paid for a full sensor read to colour one line of text.  Measured on the author's
    bench while writing this: 189.9 ms for `sensors.collect()`, 10.3 ms for the layout paint,
    so a dragged row followed the cursor about five times a second on a machine that was doing
    nothing else, playing or not.

    What is asserted is a **count**, which holds on any box, never a duration.  And two guards go
    with it, because "the drag stopped reading" is one step from "nothing reads any more": the
    preview tick still reads with an editor open, and the live pane still reads when no layout is
    open at all.
    """

    LAYOUT = "bars"

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, None, restore=False, save_settings=False)
        self.win.show()
        self.win.resize(1280, 900)
        fixtures.pump(0.4)
        self.win.ed_name.setCurrentText(self.LAYOUT)
        fixtures.pump(0.5)
        self.addCleanup(fixtures.close_window, self.win)
        self.ed = self.win.ed
        self.assertIsNotNone(self.ed, f"opening {self.LAYOUT} left the window with no editor")
        self.row = next(i for i in range(len(self.ed.widgets()))
                        if self.ed._row_box(self.ed.obj, i))
        box = self.ed._row_box(self.ed.obj, self.row)
        self.point = (box[0] + 2, (box[1] + box[3]) // 2)
        self.win.ed_widget.setCurrentIndex(self.row)
        fixtures.pump(0.2)

    # ---- the shipped door, counted rather than replaced -------------------------------------
    def count_reads(self) -> list:
        real, seen = app.sensors.collect, []

        def counted(*args, **kw):
            out = real(*args, **kw)
            seen.append(1)
            return out

        app.sensors.collect = counted
        self.addCleanup(setattr, app.sensors, "collect", real)
        return seen

    def event(self, which: str, x: int, y: int):
        from PyQt6.QtCore import QEvent, QPointF, Qt as QQt
        from PyQt6.QtGui import QMouseEvent
        kinds = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                 "release": QEvent.Type.MouseButtonRelease}
        pos = QPointF(x, y)
        return QMouseEvent(kinds[which], pos, pos, QQt.MouseButton.LeftButton,
                           QQt.MouseButton.LeftButton, QQt.KeyboardModifier.NoModifier)

    def pane_point(self, px: int, py: int) -> tuple:
        ox, oy = self.win.preview._origin()
        k = self.win.preview.side / render.W
        return int(round(ox + px * k)), int(round(oy + py * k))

    def number_of(self, index: int) -> int:
        props = (self.ed.widgets()[index].get("property") or [{}])[0]
        return int(props["x"])

    def test_a_drag_across_the_glass_reads_this_machine_no_more_than_a_tick(self):
        seen = self.count_reads()
        ox, oy = self.pane_point(*self.point)
        self.win.preview.mousePressEvent(self.event("press", ox, oy))
        self.assertTrue(self.win._drag, "the press found no row, so the moves below prove nothing")
        base, before = len(seen), self.number_of(self.row)
        frame = self.win._osd

        for step in (4, 8, 12, 16, 20, 24):
            x, y = self.pane_point(self.point[0] + step, self.point[1])
            self.win.preview.mouseMoveEvent(self.event("move", x, y))

        self.assertNotEqual(self.number_of(self.row), before,
                            "the drag never moved the row, so a read count of zero would be "
                            "measuring an empty act")
        self.assertNotEqual(self.win._osd.tobytes(), frame.tobytes(),
                            "the pane's layer did not change under the drag: a read count of "
                            "zero would then be measuring an act that painted nothing, which is "
                            "how a dead pane would look like a fast one")
        reads = len(seen) - base
        self.assertEqual(reads, 0,
                         f"{reads} sensor reads for 6 drag moves: the file at the pinned "
                         "fixture is what this pane paints, so the reads colour one line of "
                         "text and nothing else")
        self.win.preview.mouseReleaseEvent(self.event("release", *self.pane_point(
            self.point[0] + 24, self.point[1])))

    def test_an_arrow_key_nudge_reads_this_machine_no_more_than_a_drag(self):
        seen = self.count_reads()
        before = self.number_of(self.row)
        for _ in range(6):
            self.win._canvas_nudge(1, 0)
        self.assertEqual(self.number_of(self.row), before + 6,
                         "six nudges did not move the row six px")
        self.assertEqual(len(seen), 0,
                         f"{len(seen)} sensor reads for 6 key repeats: a held arrow key is the "
                         "same act as a drag, at the same rate")

    def test_editing_a_field_reads_this_machine_no_more_than_a_drag(self):
        seen = self.count_reads()
        before = self.number_of(self.row)
        self.ed.select(self.row)
        _label, _box, ctl, _extra, what = self.win.ed_rows["x"]
        self.assertEqual(what, "num", f"the `x` row is a {what} control here, not a number box")
        ctl.setValue(before + 3)
        self.win._ed_apply_row("x", True)
        self.assertEqual(self.number_of(self.row), before + 3, "the field did not reach the model")
        self.assertEqual(len(seen), 0,
                         f"{len(seen)} sensor reads for one field write")

    def test_the_preview_tick_still_reads_with_an_editor_open(self):
        seen = self.count_reads()
        self.win._preview_tick()                # what `preview_timer` is connected to
        self.assertEqual(len(seen), 1,
                         "the tick stopped reading the machine: with an editor open, the line "
                         "under the picture would freeze at whatever it last saw")

    def test_the_live_pane_still_reads_with_no_layout_open(self):
        seen = self.count_reads()
        self.win.ed = None                      # the state the window starts in
        self.win._repaint()
        self.assertEqual(len(seen), 1,
                         "the live preview stopped reading: `render.draw` needs the body, so "
                         "this is the one path where the read is the picture")


class TheRestOfTheWindowWaitsWhileARowIsHeld(fixtures.FreshConfigRoot):
    """Holding a row is an act on one picture; three other kinds of work stand down.

    `AReadOfTheMachineIsNotPartOfAnEdit` above holds the sensors read off the pointer's
    path.  This class holds the three things that turned out to be *bigger* than that read,
    found by profiling 40 real move events of a drag on `bars` on the author's bench rather
    than by guessing at the picture:

    * **the painter's own source.**  `themes.keys_read()` derives the readable field names
      by reading `layout.py` off disk, compiling it and walking ~29 000 AST nodes.  The
      model consults it to decide which fields a kind carries - `move_to` once, each `set`
      twice - so one mouse move paid for **five** parses: 20.3 ms of a 30.1 ms move (67%),
      against 9.7 ms for the actual painting.  A source file does not change while a process
      runs, so the derivation is memoised; what is gated here is the *count*, because the
      derivation itself is the census's whole point.
    * **the `--preview-fps` tick.**  With a row held, the pointer has just repainted the
      layer from the pinned fixture, so a tick arriving in that instant repaints pixels that
      cannot differ - and pays for the read to do it.  Injecting one tick into every fourth
      move, on this bench: mean 32.2 ms and worst **113.9 ms** per move before, mean 10.9 and
      worst 12.0 ms after.
    * **the clip library's thumbnails.**  `thumb_timer` runs at interval 0, one clip per
      tick, and a clip is two subprocesses - `ffprobe` for the loop length, `ffmpeg` to seek
      the frame.  Opening the window and dragging into it costs **108 ms per move** for the
      first 25 moves (24 spawns counted across 8 of them) and 11.7 ms once the pass is done.
      This is what "slow even with playing off" meant: nothing was playing; the queue beside
      the pane was working.

    Every check is a count, and each count is answered from both sides, because "it stopped
    doing the expensive thing" is one edit away from "it stopped doing the thing".
    """

    LAYOUT = "bars"

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, None, restore=False, save_settings=False)
        self.win.show()
        self.win.resize(1280, 900)
        fixtures.pump(0.4)
        self.win.ed_name.setCurrentText(self.LAYOUT)
        fixtures.pump(0.5)
        self.win.preview_timer.stop()       # a timer firing between steps is not the subject
        self.addCleanup(fixtures.close_window, self.win)
        self.ed = self.win.ed
        self.assertIsNotNone(self.ed, f"opening {self.LAYOUT} left the window with no editor")
        self.row = next(i for i in range(len(self.ed.widgets()))
                        if self.ed._row_box(self.ed.obj, i))
        box = self.ed._row_box(self.ed.obj, self.row)
        self.point = (box[0] + 2, (box[1] + box[3]) // 2)

    # ---- the shipped doors, in the window's own coordinates -------------------------------
    def event(self, which: str, x: int, y: int):
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        kinds = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                 "release": QEvent.Type.MouseButtonRelease}
        pos = QPointF(x, y)
        return QMouseEvent(kinds[which], pos, pos, Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    def pane(self, px: int, py: int) -> tuple:
        ox, oy = self.win.preview._origin()
        k = self.win.preview.side / render.W
        return (int(round(ox + px * k)), int(round(oy + py * k)))

    def hold(self) -> None:
        """Press the row, and say so if the press found nothing to hold."""
        self.win.preview.mousePressEvent(self.event("press", *self.pane(*self.point)))
        self.assertTrue(self.win._drag,
                        "the press found no row under the pointer, so every count below is "
                        "measuring a window that is doing nothing")

    def moves(self, steps: int = 6) -> None:
        for step in range(1, steps + 1):
            self.win.preview.mouseMoveEvent(self.event("move", *self.pane(self.point[0] + step,
                                                                          self.point[1])))

    def x_of_row(self) -> int:
        return int((self.ed.widgets()[self.row].get("property") or [{}])[0]["x"])

    # ---- 1. the painter's source is not re-read by an act ----------------------------------
    def test_a_drag_reads_the_painter_s_source_no_more_than_a_field_write_does(self):
        import inspect
        real, seen = inspect.getsource, []

        def counted(module):
            if getattr(module, "__name__", "") == "xigmalcd.layout":
                seen.append(1)
            return real(module)

        inspect.getsource = counted
        self.addCleanup(setattr, inspect, "getsource", real)
        before, anchor = self.x_of_row(), themes.keys_read()
        self.hold()
        self.moves()
        self.assertEqual(self.x_of_row(), before + 6,
                         "the drag did not move the row six px, so a count of zero source "
                         "reads would be measuring an act that changed nothing")
        self.assertEqual(seen, [],
                         f"{len(seen)} reads of `layout.py`'s source for 6 drag moves: the "
                         "readable-field set is a fact about a file that cannot change inside "
                         "a run, and five parses a move is twice what the painting costs")
        self.win.preview.mouseReleaseEvent(self.event("release", *self.pane(self.point[0] + 6,
                                                                            self.point[1])))
        # the memo may not become a second source of truth: the names still come from the
        # painter, and the model still refuses a key that painter never reads
        self.assertEqual(themes.keys_read(), anchor,
                         "`keys_read()` stopped answering with the names it derives from the "
                         "painter - a cache that loses the derivation is a census that lies")
        self.assertGreater(len(anchor[0]), 20,
                           f"the derived set is {len(anchor[0])} names: too small to mean the "
                           "painter was read at all")
        ok, note = self.ed.set("italic", True)
        self.assertFalse(ok, f"the model took a key nothing reads: {note}")
        self.assertIn("does not carry", note, note)

    # ---- 2. the preview tick stands down while a row is held -------------------------------
    def count_paints(self) -> list:
        """Count the layer paints the editor is asked for, through the model's own door."""
        real, seen = self.ed.paint, []

        def counted(*args, **kw):
            out = real(*args, **kw)
            seen.append(1)
            return out
        self.ed.paint = counted
        self.addCleanup(setattr, self.ed, "paint", real)
        return seen

    def test_a_preview_tick_while_a_row_is_held_paints_nothing(self):
        paints = self.count_paints()
        self.hold()
        self.win._preview_tick()
        self.assertEqual(paints, [],
                         f"{len(paints)} layer paints for a tick that arrived mid-drag: the "
                         "pointer has already drawn this file at this fixture, so the tick can "
                         "only repaint identical pixels and pays a sensor read to do it")
        self.win.preview.mouseReleaseEvent(self.event("release", *self.pane(*self.point)))
        paints.clear()                          # the release repaints with a read: not the subject
        self.win._preview_tick()
        self.assertEqual(len(paints), 1,
                         f"{len(paints)} paints for a tick with no row held: the line under "
                         "the picture has stopped following the machine")

    def test_a_held_key_is_not_treated_as_a_drag_by_the_tick(self):
        paints = self.count_paints()
        self.win._canvas_nudge(2, 0)            # an arrow key: no press, so no `_drag`
        paints.clear()
        self.win._preview_tick()
        self.assertEqual(len(paints), 1,
                         f"{len(paints)} paints for a tick after an arrow-key nudge: only a "
                         "press-and-hold is a drag, and a gate that silences the tick for any "
                         "edit would freeze the caption")

    # ---- 3. the ffmpeg/thumbnail pass waits for the pointer -------------------------------
    def test_a_thumbnail_tick_while_a_row_is_held_probes_no_clip(self):
        real_probe, real_frame, seen = app.clipdb.probe, app.clipdb.frame, []
        app.clipdb.probe = lambda *a, **kw: seen.append(("probe",))
        app.clipdb.frame = lambda *a, **kw: seen.append(("frame",))
        self.addCleanup(setattr, app.clipdb, "probe", real_probe)
        self.addCleanup(setattr, app.clipdb, "frame", real_frame)
        # the window's own queue and the window's own timer: `_populate_clips()` is not
        # called here, because re-running it *replaces* `thumb_timer` and the pass that was
        # already running goes on firing under the new one.  Stopping the named timer leaves
        # the queue, which is the only state this door reads.
        self.win.thumb_timer.stop()
        self.addCleanup(self.win.thumb_timer.stop)
        if not self.win._pending:
            self.win._pending = list(range(len(self.win.all_clips)))
        self.assertTrue(self.win._pending,
                        "no clip was left pending, so the deferral below would have been "
                        "proved by an empty queue rather than by a held row")
        queue = len(self.win._pending)
        self.hold()
        self.win._thumb_batch()
        self.assertEqual(seen, [],
                         f"{len(seen)} media probes started inside a drag: ffprobe and ffmpeg "
                         "take the event loop for as long as they run, which is what a stall "
                         "in the middle of a drag feels like")
        self.assertEqual(len(self.win._pending), queue,
                         "the deferred tick threw the queue away instead of waiting: the "
                         "library would silently keep its old rows forever")
        self.win.preview.mouseReleaseEvent(self.event("release", *self.pane(*self.point)))
        self.win._thumb_batch()
        self.assertEqual(len(seen), 2,
                         f"{seen}: a tick with no row held should do exactly one clip - "
                         "a probe and a frame - or the pass never finishes")
        self.assertEqual(len(self.win._pending), queue - 1,
                         "the queue did not shrink by one, so nothing is being consumed")

    def test_the_library_has_one_thumbnail_timer_for_the_life_of_the_window(self):
        """The queue is consumed by one timer, and a second populate may not leave a second.

        A `QTimer` made and forgotten inside `_populate_clips` cannot be stopped by
        `closeEvent` or by the suite's `close_window`, both of which stop the timer the
        window *names*.  An orphan fires `_thumb_batch` at interval 0 - two subprocesses a
        tick - for as long as the queue lasts, into whichever test file runs next.  That is
        not hypothetical here: this file's own thumbnail check did exactly that to
        `tests/test_tooltips.py`'s tooltip deadline on 2026-11-12, on CI and on the bench.
        """
        from PyQt6.QtCore import QTimer
        named = lambda: [t for t in self.win.findChildren(QTimer)      # noqa: E731
                         if t.objectName() == "thumb"]
        self.assertEqual(len(named()), 1,
                         f"{len(named())} timers named `thumb`: the door that arms the "
                         "thumbnail pass should not be able to make another one")
        armed = self.win.thumb_timer
        self.win._populate_clips()                    # the shipped door, run a second time
        self.addCleanup(self.win.thumb_timer.stop)
        self.assertEqual(len(named()), 1,
                         f"a second `_populate_clips()` left {len(named())} timers running "
                         "the pass: the first one is unstoppable by name and keeps spawning")
        self.assertIs(self.win.thumb_timer, armed,
                      "`thumb_timer` was replaced, so the window's own `closeEvent` would "
                      "stop the wrong timer")
        queue = len(self.win._pending)
        self.assertGreater(queue, 0, "a second populate armed no queue, so the pass below "
                                     "could not be counted")
        self.win.thumb_timer.stop()
        seen = []
        real = app.clipdb.probe
        app.clipdb.probe = lambda *a, **kw: seen.append(1)
        self.addCleanup(setattr, app.clipdb, "probe", real)
        self.win._thumb_batch()
        self.win._thumb_batch()
        self.assertEqual(len(seen), 2,
                         f"{len(seen)} probes for two ticks: a tick connected twice, or a "
                         "queue that is not being consumed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
