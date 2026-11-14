#!/usr/bin/env python3
"""Feature G: what body the editor's pane paints, and what a press on that frame means.

Ported from the peek block of `tools/selftest.sh`'s GUI section.  The knob on the row above
the preview pane chooses what the editor's picture is painted from: the pinned fixture (the
frame every edit is judged at), **this machine's readings - live**, or a `STATE all 1` file
named in the box beside it.  The last two differ about more than where the numbers come
from, and the difference is measured rather than asserted:

* `this machine's readings` follows the machine at `--preview-fps`: the preview tick reads
  again, and the box, the handles and the hit test are taken from **that** paint, so the row
  you point at is the row whose ink you pointed at.  A pointer act reads nothing at all -
  the rule that keeps a drag cheap (`tests/test_canvas.py`) holds here too, and it is
  counted, never timed;
* `a metrics file` is held: read once when it is named, so the same file named twice gives
  the same picture, and its geometry doors stay shut.  The reason is the measurement in
  `test_the_row_boxes_change_owner_across_the_glass_between_two_bodies`: it probes the glass
  on a grid and counts the points that answer a **different row** in one frame than in the
  other - against a pinned file rather than this machine's sensors, so the count answers the
  same on every machine.  A handle drawn at a pinned edge would sit over another row's ink,
  and a drag would grab a row nobody pointed at;
* and any number such a drag wrote would belong to a sample that is gone a second later:
  feature F derives a centred row's `x` from the width of its ink, and ink width follows the
  reading.  That hazard is why a *held* body stays ungrabbable.  The live frame takes a
  press because the reading behind it is the one this machine is answering now, and the next
  tick replaces the numbers and the marks together.

Two kinds of body, and the assertions are split by what they depend on.  The files in
`tools/metrics/` are pinned, so a count taken against them answers the same on this bench and
on CI's runner and is asserted exactly (`57°C` at the fixture against `104°C` at that file).
This machine's own sensors are a fact about this machine, so the bodies the live checks are
driven with are **authored here** - the fixture's own body, and that body with `cpu` at
104.0 - and what is asserted is which of the two the pixels came from, not what a second of
this box's load is worth.
"""
from __future__ import annotations

import builtins
import json
import os
import unittest

from tests import fixtures

from xigmalcd import main as daemon
from xigmalcd import render, sensors
from xigmaui import app, edit as gui_edit

MISSING_PORT = "/dev/xigma-no-such-port"
LAYOUT = "bars"

#: A body this repository carries, with a hot `cpu.temperature` (104.0) and a timestamp nobody's
#: sensors will answer again: `57°C` at the fixture, `104°C` at this file.
HOT_METRICS = os.path.join(fixtures.REPO, "tools", "metrics", "pin-104.json")
HOT_NAME = "pin-104.json"


class TheLoadersDoor(unittest.TestCase):
    """`main.read_metrics_file`: the one rule about a metrics file, answered four ways."""

    def test_a_good_file_gives_its_sections_and_no_reason(self):
        sections, why = daemon.read_metrics_file(HOT_METRICS)
        self.assertEqual(why, "")
        self.assertEqual(sections["cpu"]["temperature"], 104.0, sections.get("cpu"))
        self.assertNotIn("_comment", sections,
                         "a key starting with `_` is a comment in the file, not a section")

    def test_the_four_shapes_a_reader_can_get_wrong(self):
        missing, why = daemon.read_metrics_file(os.path.join(fixtures.ISOLATED, "nope.json"))
        self.assertEqual(missing, {})
        self.assertIn("FileNotFoundError", why, why)

        broken = os.path.join(fixtures.ISOLATED, "broken.json")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        bad, why = daemon.read_metrics_file(broken)
        self.assertEqual(bad, {})
        self.assertIn("JSONDecodeError", why, why)

        listing = os.path.join(fixtures.ISOLATED, "list.json")
        with open(listing, "w", encoding="utf-8") as handle:
            json.dump([{"cpu": {}}], handle)
        wrong, why = daemon.read_metrics_file(listing)
        self.assertEqual(wrong, {})
        self.assertIn("not a list", why, why)

    def test_a_hot_pinned_temperature_survives_a_file_that_cannot_be_read(self):
        """`--metrics-file` caches by mtime, and a failed read must not empty the last good one."""
        saved = (daemon.PINNED, daemon.PINNED_MTIME)

        class Good:
            metrics_file = HOT_METRICS

        class Broken:
            metrics_file = os.path.join(fixtures.ISOLATED, "nope.json")

        try:
            self.assertEqual(daemon._pinned(Good)["cpu"]["temperature"], 104.0)
            self.assertEqual(daemon._pinned(Broken)["cpu"]["temperature"], 104.0,
                             "a file that cannot be read replaced the pinned body with nothing")
        finally:
            daemon.PINNED, daemon.PINNED_MTIME = saved


class PeekHarness(fixtures.FreshConfigRoot):
    """One shown window with a layout open and the peek knob reachable."""

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

    def open_layout(self, name: str = LAYOUT) -> None:
        self.win.ed_name.setCurrentText(name)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, f"opening {name} left no editor")

    def pick(self, mode: str, path: str = "") -> None:
        index = {"fixture": 0, "sensors": 1, "file": 2}[mode]
        if path:
            self.win.ed_peek_file.setText(path)
        self.win.ed_peek.setCurrentIndex(index)
        self.win._editor_peek()
        fixtures.pump(0.3)

    def layer(self) -> bytes:
        return self.win._osd.tobytes()

    def note(self) -> str:
        return self.win.ed_note.text()

    def paint_of(self, metrics: dict, when=None) -> bytes:
        """The same body drawn through a **different** editor object over the same layout, which is
        how a claim about the picture stays a claim and not a tautology."""
        trial = gui_edit.Editor(self.win.ed.obj, origin="check", name=self.win.ed.name)
        image, _notes = trial.paint(metrics=metrics,
                                    when=when or gui_edit.FIXTURE_WHEN, ink=self.win._ink())
        return image.tobytes()

    def pane_point(self, px: int, py: int) -> tuple:
        origin_x, origin_y = self.win.preview._origin()
        return int(round(origin_x + px)), int(round(origin_y + py))

    def press_on(self, px: int, py: int) -> None:
        from PyQt6.QtCore import QEvent, QPointF, Qt as QQt
        from PyQt6.QtGui import QMouseEvent
        x, y = self.pane_point(px, py)
        pos = QPointF(x, y)
        self.win.preview.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                                                     QQt.MouseButton.LeftButton,
                                                     QQt.MouseButton.LeftButton,
                                                     QQt.KeyboardModifier.NoModifier))
        fixtures.pump(0.1)

    def key_right(self) -> None:
        from PyQt6.QtCore import QEvent, Qt as QQt
        from PyQt6.QtGui import QKeyEvent
        self.win.preview.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, QQt.Key.Key_Right,
                                                 QQt.KeyboardModifier.NoModifier))
        fixtures.pump(0.1)


class PeekingAtAPinnedBody(PeekHarness):
    """The file body: pinned, so the numbers below are the same on any machine."""

    def test_the_knob_is_shut_until_a_layout_is_open_and_its_path_box_until_file_mode(self):
        self.assertFalse(self.win.ed_peek.isEnabled(), "the combo is offered with no layout open")
        self.open_layout()
        self.assertTrue(self.win.ed_peek.isEnabled(), "the combo stayed shut after a layout opened")
        self.assertIsNone(self.win._peek)
        self.assertEqual(self.win.ed_peek.currentData(), "fixture")
        self.assertEqual(self.win.ed_peek.currentIndex(), 0)
        self.assertFalse(self.win.ed_peek_file.isEnabled(),
                         "the path box is live in a mode that will not read it")
        for need in ("metrics file", "held", "refused", "fixture"):
            self.assertIn(need, self.win.ed_peek.toolTip(),
                          f"the tooltip under the knob does not say {need!r} is part of the rule")

    def test_a_peek_is_never_written_to_the_session(self):
        """The frame a person was *looking at* is not a setting: nobody should open the window next
        week on a body their sensors no longer answer."""
        self.open_layout()
        self.pick("file", HOT_METRICS)
        self.assertIsNotNone(self.win._peek)
        self.assertFalse([key for key in self.win._state() if "peek" in key.lower()],
                         sorted(self.win._state()))

    def test_peeking_a_file_paints_that_body_and_says_so_in_four_places(self):
        self.open_layout()
        pinned = self.layer()
        self.assertTrue(self.win.preview.marks and self.win.preview.marks[0],
                        "the marks were not there to begin with, so taking them away proves "
                        "nothing")
        self.pick("file", HOT_METRICS)
        peek = self.win._peek
        self.assertIsNotNone(peek)
        self.assertEqual(peek["when"], gui_edit.FIXTURE_WHEN,
                         "the instant of a peek is the pinned one: a live clock rewrites the rows "
                         "that read `Date`, `Time` and `Week`, so the same peek twice would not be "
                         "the same picture")
        self.assertEqual(peek["metrics"]["cpu"]["temperature"], 104.0, peek["metrics"].get("cpu"))
        self.assertIn(HOT_METRICS, peek["source"], peek["source"])
        self.assertEqual(self.layer(), self.paint_of(peek["metrics"]),
                         "the pane is not showing the body it names")
        self.assertNotEqual(self.layer(), pinned,
                            "peeking at a hot body left the pinned frame up: the peek did not move "
                            "the picture")
        self.assertIsNone(self.win.preview.marks,
                          "the handles stayed on a frame whose geometry doors are shut")
        self.assertIn("peeking", (self.win.preview.toolTip() or ""),
                      self.win.preview.toolTip()[:160])
        self.assertEqual(self.note(), self.win.ed.peek_sentence(peek["source"], peek["metrics"],
                                                                peek["when"], peek["held"]),
                         "the note line is not the model's own sentence about this peek")
        self.assertIn("PEEK", self.win.metrics.text(), self.win.metrics.text()[:200])
        self.assertIn(peek["source"], self.win.metrics.text(), self.win.metrics.text()[:200])
        self.assertIn("peek", self.win.caption.text().lower(), self.win.caption.text()[:160])
        self.assertTrue(self.win.ed_peek_file.isEnabled(),
                        "the path box went shut while the file mode is chosen")

    def test_the_note_lines_read_the_body_on_screen_not_the_editable_one(self):
        """`57°C` at the fixture, `104°C` at the pinned file: the note describes the picture, and
        the doors still write the file the edits move."""
        self.open_layout()
        # a `data`/`text` row, not a gutter figure: since 2026-11-14 the block carries an
        # icon widget that reads `CPU Temperature` too, and it comes *earlier* in the list -
        # it paints a shape, so it has no line of text to compare and answering None is
        # correct for it
        row = next(i for i, widget in enumerate(self.win.ed.widgets())
                   if str(widget.get("type") or "") in ("data", "text")
                   and "Temperature" in str(((widget.get("property") or [{}])[0]).get("source")
                                            or ""))
        self.win.ed.select(row)
        fixtures.pump(0.2)
        self.assertEqual(self.win.ed.drawn_text(*self.win.ed.fixture())[0], "57°C",
                         "the fixture's own line changed, so the comparison below means nothing")
        self.pick("file", HOT_METRICS)
        pair = self.win._note_pair()
        self.assertEqual(pair[0]["cpu"]["temperature"], 104.0, pair[0].get("cpu"))
        self.assertEqual(self.win.ed.drawn_text(*pair)[0], "104°C",
                         "the note line still quotes the fixture while the pane paints the peek")

    def test_the_geometry_door_answers_at_the_pinned_frame_while_peeking(self):
        """The row under a point does not move just because the picture did: `hit` reads the notes
        from the pinned draw, and the handles the pane offers come from that same frame."""
        self.open_layout()
        self.win.ed.select(2)
        fixtures.pump(0.2)
        answered = self.win.ed.hit(self.win._ed_notes, 240, 24)
        self.pick("file", HOT_METRICS)
        self.assertEqual(self.win.ed.hit(self.win._ed_notes, 240, 24), answered,
                         "a point on the glass answers a different row in a peek: that is the "
                         "hazard the refusal exists for")

    def test_the_row_boxes_change_owner_across_the_glass_between_two_bodies(self):
        """The census the dropped marks are based on: the same layout, the same instant, two
        bodies, probed on a grid.

        `bars` at the fixture's `57°C` and at the pinned file's `104°C` is one file drawn twice,
        and the boxes the painter reports are *not* the same boxes - a text row's box is its ink,
        and ink width follows the reading.  So the glass is probed on a 6 px grid and the two
        frames are asked what row sits under each point.  The count that matters is the relation:
        points change owner.  If none ever did, the pane could keep painting handles over a peek
        and this check would say so by failing.
        """
        self.open_layout()
        body, _reason = daemon.read_metrics_file(HOT_METRICS)
        self.assertEqual(body["cpu"]["temperature"], 104.0, body.get("cpu"))
        pinned, live = self.win._ed_notes, self.win.ed.paint(
            metrics=body, when=gui_edit.FIXTURE_WHEN, ink=self.win._ink())[1]
        # A reported box may be None: a row whose reading this body cannot answer draws
        # nothing, and since 2026-11-14 that includes the gutter figures.  It is not a
        # mismatch to be compared, it is the absence the doors report in words.
        def boxes(notes):
            return {ri: tuple(box) for _kind, _what, box, ri in (notes.get("boxes") or [])
                    if box is not None}
        by_row, pinned_row = boxes(live), boxes(pinned)
        moved = sorted({ri for ri, box in pinned_row.items()
                        if ri in by_row and box != by_row[ri]})
        self.assertTrue(moved, "no row box moves between the fixture and a body 47 degrees "
                               "hotter: the marks could simply stay, and the refusal would be "
                               "superstition")
        step, probes, flips = 6, 0, 0
        for px in range(0, render.W, step):
            for py in range(0, render.H, step):
                probes += 1
                if self.win.ed.hit(pinned, px, py) != self.win.ed.hit(live, px, py):
                    flips += 1
        self.assertGreater(flips, 0,
                           f"{len(moved)} row boxes moved ({moved}) yet all {probes} probed "
                           f"points still answer the same row: the hazard the peek refusal "
                           f"describes cannot be reproduced")

    def test_one_press_on_the_knob_reads_the_file_once_and_a_repaint_reads_it_not_at_all(self):
        """*Held* is a claim with a cost behind it: the body is read once per press, and a repaint -
        which the preview timer runs at its own rate - must not re-read it."""
        self.open_layout()
        # the pane repaints on its own timer; a tick of that is not a press, and leaving it
        # running here is how a count of reads stops meaning anything
        self.win.preview_timer.stop()
        self.pick("file", HOT_METRICS)
        real = builtins.open
        calls = []

        def counting(path, *args, **kwargs):
            calls.append(str(path))
            return real(path, *args, **kwargs)

        builtins.open = counting
        try:
            self.win._editor_peek()                 # the same press again
            after_press = [path for path in calls if path.endswith(HOT_NAME)]
            held = self.layer()                     # the frame that press produced
            calls.clear()
            self.win._repaint()
            self.win._repaint()
            after_repaints = [path for path in calls if path.endswith(HOT_NAME)]
        finally:
            builtins.open = real
        self.assertEqual(len(after_press), 1,
                         f"{len(after_press)} reads of {HOT_NAME} for one press on the knob")
        self.assertEqual(after_repaints, [],
                         f"{len(after_repaints)} re-reads of {HOT_NAME} across two repaints: a "
                         "held body is not held")
        self.assertEqual(self.layer(), held, "a held body repainted differently, so it is not held")

    def test_a_press_on_the_glass_and_an_arrow_key_are_refused_in_the_models_own_words(self):
        self.open_layout()
        self.win.ed.select(4)
        fixtures.pump(0.2)
        box = self.win.ed._row_box(self.win.ed.obj, 4)
        self.assertTrue(box, "row 4 of `bars` paints no box, so there is no ink to press on")
        self.pick("file", HOT_METRICS)
        steps, dirty = self.win.ed.steps, self.win.ed.dirty
        before = (int(self.win.ed.prop().get("x", -1)), int(self.win.ed.prop().get("y", -1)))
        self.press_on(box[0] + 2, (box[1] + box[3]) // 2)
        self.assertIsNone(self.win._drag, "a press began a drag on a peek whose marks said there "
                                          "was nothing")
        self.assertEqual(self.note(), self.win.ed.peek_refusal("A press on the glass"),
                         self.note()[:220])
        self.key_right()
        self.assertEqual((self.win.ed.steps, self.win.ed.dirty), (steps, dirty),
                         "an arrow key wrote something while peeking")
        self.assertEqual((int(self.win.ed.prop().get("x", -1)),
                          int(self.win.ed.prop().get("y", -1))), before,
                         "an arrow key moved a row while peeking")
        self.assertEqual(self.note(), self.win.ed.peek_refusal("An arrow key"), self.note()[:220])
        for sentence in (self.win.ed.peek_refusal("A press on the glass"),
                         self.win.ed.peek_refusal("An arrow key")):
            self.assertIn("peek", sentence)
            self.assertIn("fixture", sentence,
                          "the refusal does not name the knob that puts the editable frame back")

    def test_a_half_read_body_leaves_the_pinned_frame_up_and_says_why(self):
        self.open_layout()
        pinned = self.layer()
        for path, need in ((os.path.join(fixtures.ISOLATED, "not-here.json"), "FileNotFound"),
                          ("", "has to be named")):
            with self.subTest(path=path or "<empty>"):
                self.win.ed_peek_file.setText(path)
                self.win.ed_peek.setCurrentIndex(2)
                self.win._editor_peek()
                fixtures.pump(0.3)
                self.assertIsNone(self.win._peek, f"{path!r} was accepted as a body")
                self.assertEqual(self.win.ed_peek.currentIndex(), 2,
                                 "the mode was snapped back under the reader's fingers, losing "
                                 "what they were about to name")
                self.assertTrue(self.note().startswith("no peek:"), self.note()[:170])
                self.assertIn(need, self.note(), self.note()[:170])
                self.assertEqual(self.layer(), pinned, "a refused peek moved the picture")
                self.assertTrue(self.win.ed_peek_file.isEnabled(),
                                "the path box was shut while the reader names it")

    def test_choosing_the_fixture_again_puts_the_editable_frame_back(self):
        self.open_layout()
        pinned = self.layer()
        self.pick("file", HOT_METRICS)
        self.assertNotEqual(self.layer(), pinned)
        self.pick("fixture")
        self.assertIsNone(self.win._peek)
        self.assertEqual(self.layer(), pinned, "back at the fixture, the pane is not the frame the "
                                               "edits are judged at")
        self.assertTrue(self.win.preview.marks and self.win.preview.marks[0],
                        "the marks did not come back with the editable frame")


class PeekingAtThisMachine(PeekHarness):
    """The same knob, pointed at a body nobody pins: `sensors.collect()` on this box."""

    def test_a_press_samples_once_a_tick_samples_again_and_a_pointer_act_samples_not_at_all(self):
        """`this machine's readings` is live, and three counts say which parts of it move.

        `sensors.collect()` is the expensive door - 71.8 ms on this bench, per `app.py`'s own
        note - so the pane pays for it on the preview tick and nowhere else.  Three faults hide
        behind that one sentence, and a different count catches each:

        * a pane that re-read per pointer event: the cost `tests/test_canvas.py` holds at zero
          for a drag, held at zero here too;
        * a pane that never re-reads: the complaint this entry exists to answer, the old held
          body painted long after the sample went stale;
        * a pane that re-reads but paints the sample it *names*: it passes both counts above and
          still shows yesterday's temperature.

        So the body on the other side of the stub is something this file sets, and the layer is
        compared byte for byte with that body drawn through a **second editor object**
        (`paint_of`) - which is what keeps "the pane shows what it read" from being a tautology.
        No `pump()` inside a counted window: another window's timer reading this box is not this
        test's business, and an uncounted event between two clears is how a count starts lying.
        """
        self.open_layout()
        self.win.preview_timer.stop()               # a tick of the pane is not a press
        cold = {k: (dict(v) if isinstance(v, dict) else v) for k, v in gui_edit.FIXTURE.items()}
        hot = {**cold, "cpu": {**(cold.get("cpu") or {}), "temperature": 104.0}}
        self.assertNotEqual(self.paint_of(cold), self.paint_of(hot),
                            "the two authored bodies draw the same picture, so nothing below "
                            "could tell which one the pane is showing")
        on_hand = {"body": cold}
        samples, real = [], sensors.collect

        def scripted():
            body = dict(on_hand["body"])
            samples.append(body)
            return body

        sensors.collect = scripted
        try:
            self.win.ed_peek.setCurrentIndex(1)         # `sensors`
            self.win._editor_peek()                     # the shipped door, no pump around it
            self.assertEqual(len(samples), 2,
                             f"{len(samples)} samples for one press: one for the body the knob "
                             "asked for and one for the repaint that press triggered")
            self.assertTrue(self.win._peek and self.win._peek["live"],
                            "the knob did not put the pane in live mode, so the counts below are "
                            "counting a held peek")
            self.assertEqual(self.layer(), self.paint_of(cold),
                             "the frame on screen is not the sample this press took")
            self.assertIn("cpu 57", self.win.metrics.text().replace("°C", ""),
                          f"the counters line under the picture names another body: "
                          f"{self.win.metrics.text()[:150]}")

            on_hand["body"] = hot                       # the machine moved; no edit was made
            samples.clear()
            self.win._preview_tick()                    # what `preview_timer` is connected to
            self.assertEqual(len(samples), 1,
                             f"{len(samples)} samples for one preview tick: the line under the "
                             "picture needs one, and the live pane needs that one to be the "
                             "picture's own")
            self.assertEqual(self.layer(), self.paint_of(hot),
                             "a tick arrived and the frame did not follow it: this pane is "
                             "holding a sample, not following the machine")
            self.assertEqual(self.win._peek["metrics"], hot,
                             "the body the window describes is not the one it just painted")
            self.assertIn("cpu 104", self.win.metrics.text().replace("°C", ""),
                          f"the counters line still names the older sample: "
                          f"{self.win.metrics.text()[:150]}")
            self.assertIn("LIVE -", self.win.metrics.text(),
                          "the line under the picture does not say the body is live")
            self.assertIn("last read", self.win.caption.text(),
                          "the caption does not say when the sample it is showing was taken")

            samples.clear()
            before = int(self.win.ed.prop().get("x") or 0)
            self.win._canvas_nudge(3, 0)                # a held arrow key: an act, not a tick
            self.win._repaint(readings=False)           # what one mouse-move of a drag does
            self.assertEqual(int(self.win.ed.prop().get("x")), before + 3,
                             "the nudge did not move the row, so a read count of zero would be "
                             "measuring an act that did nothing")
            self.assertEqual(samples, [],
                             f"{len(samples)} samples for an arrow key and a repaint: a pointer "
                             "act paints from the tick's sample and never reads the box")
            self.assertEqual(self.layer(), self.paint_of(hot),
                             "the frame moved under the pointer to a body other than the last "
                             "tick's sample")
        finally:
            sensors.collect = real

    def test_the_body_the_note_describes_is_a_copy_so_a_caller_cannot_wear_it_down(self):
        """`edit.fixture()`'s shallow copy once cost every later draw a derived rate; the same
        hazard exists one level over, in a live pane whose note line hands out the very dict the
        next frame will be painted from."""
        self.open_layout()
        self.win.preview_timer.stop()
        real = sensors.collect
        made = []

        def once():
            body = real()
            made.append(body)
            return body

        sensors.collect = once
        try:
            self.pick("sensors")
            handed = self.win._peek["metrics"]
            self.assertTrue(made, "no body was collected, so the identity below means nothing")
            self.assertIsNot(handed, made[-1],
                             "the peek hands out the live dict: a caller editing it would edit the "
                             "sample the picture was drawn from")
        finally:
            sensors.collect = real


class TheLiveFrameIsTheOneYouEdit(PeekHarness):
    """`this machine's readings` is a frame, not a photograph: it follows the box, and the
    pane's geometry answers at it.

    A held peek hides its marks and refuses a press, and the measurement above is why: the
    boxes of these layouts move between bodies, so a handle taken from one frame sits over
    another row's ink.  That argument is about *which frame the marks came from*, not about
    readings, and the live mode answers it the other way round - the marks come from the
    paint that is on screen, so the same hazard is gone and the doors can stay open.  What
    this class holds is exactly that: the box, the handles, the hit test and the arrow key
    all belong to the frame the pane is showing, and a press selects the row whose ink is
    under the pointer **in that frame**.
    """

    def bodies(self) -> tuple:
        """Two authored bodies, one 47 degrees hotter than the other."""
        cold = {k: (dict(v) if isinstance(v, dict) else v) for k, v in gui_edit.FIXTURE.items()}
        return cold, {**cold, "cpu": {**(cold.get("cpu") or {}), "temperature": 104.0}}

    def go_live(self, body: dict) -> None:
        """Put the pane in live mode with `sensors.collect()` handing out one authored body."""
        self.win.preview_timer.stop()               # the count below is the press's, not a tick's
        real = sensors.collect
        sensors.collect = lambda: dict(body)
        self.addCleanup(setattr, sensors, "collect", real)
        self.pick("sensors")
        self.assertTrue(self.win._peek and self.win._peek["live"],
                        "the knob did not put the pane in live mode")

    def notes_at(self, metrics: dict) -> dict:
        """The boxes one body reports, through a second editor over the same file."""
        trial = gui_edit.Editor(self.win.ed.obj, origin="check", name=self.win.ed.name)
        _image, notes = trial.paint(metrics=metrics, when=gui_edit.FIXTURE_WHEN,
                                    ink=self.win._ink())
        return notes

    def test_the_knob_sits_between_playing_and_the_pane_and_never_folds(self):
        """The relation the owner asked for, held as relations: under `playing`, above the
        pane, and on screen whether or not the advanced switch is on."""
        self.win.adv_toggle.setChecked(False)
        fixtures.pump(0.2)
        self.assertFalse(hasattr(self.win, "peek_box"),
                         "the separate `Pane readings` box is back among the settings knobs: "
                         "the knob that chooses this picture belongs above the picture")
        for name in ("ed_peek", "ed_peek_file"):
            with self.subTest(control=name):
                self.assertNotIn(getattr(self.win, name), self.win._adv_hide,
                                 f"{name} folds away with the knobs that write settings")
                self.assertTrue(getattr(self.win, name).isVisible(),
                                f"{name} went away when `advanced controls` came off")
        playing, knob, pane = (self.win.anim_toggle.geometry(), self.win.ed_peek.geometry(),
                               self.win.preview.geometry())
        self.assertLessEqual(playing.bottom(), knob.top(),
                             "the pane-readings knob is not under the `playing` tickbox")
        self.assertLessEqual(knob.bottom(), pane.top(),
                             "the knob is not above the preview pane whose body it chooses")

    def test_a_live_frame_owns_its_own_marks(self):
        self.open_layout()
        cold, hot = self.bodies()
        pinned, live = self.notes_at(cold), self.notes_at(hot)
        by_pinned = {ri: tuple(box) for _kind, _what, box, ri in (pinned.get("boxes") or []) if box}
        by_live = {ri: tuple(box) for _kind, _what, box, ri in (live.get("boxes") or []) if box}
        moved = sorted(ri for ri in by_pinned if ri in by_live and by_pinned[ri] != by_live[ri])
        self.assertTrue(moved,
                        "no row box moves between the fixture's body and one 47 degrees hotter, "
                        "so the pinned marks would have been honest and this rule is a invention")
        row = moved[0]
        self.win.ed.select(row)
        self.go_live(hot)
        marks = self.win.preview.marks
        self.assertTrue(marks and marks[0],
                        "the live pane hid its marks and handles: that is the held peek's rule, "
                        "and it belongs to a body the machine stopped answering")
        self.assertEqual(tuple(marks[0]), by_live[row],
                         f"the box on the live frame is {tuple(marks[0])}, but the frame on "
                         f"screen draws row {row} at {by_live[row]}")
        self.assertNotEqual(tuple(marks[0]), by_pinned[row],
                            "the marks did not move with the body they were drawn for")
        self.assertTrue(marks[3], "the live frame painted no handles for the row it selects")

    def test_a_press_grabs_the_row_the_live_frame_draws(self):
        self.open_layout()
        cold, hot = self.bodies()
        pinned, live = self.notes_at(cold), self.notes_at(hot)
        flip = None
        for px in range(0, render.W, 6):
            for py in range(0, render.H, 6):
                there, here = self.win.ed.hit(pinned, px, py), self.win.ed.hit(live, px, py)
                if here is not None and there != here:
                    flip = (px, py, there, here)
                    break
            if flip:
                break
        self.assertIsNotNone(
            flip, "no point on the glass answers a different row in the two frames: the hazard "
                  "the held refusal describes cannot be reproduced, and the live mode's marks "
                  "would need no rule of their own")
        px, py, pinned_row, live_row = flip
        self.go_live(hot)
        self.press_on(px, py)
        self.assertIsNotNone(self.win._drag,
                             f"a press at {px},{py} grabbed nothing on the live frame: the "
                             "geometry doors stayed shut")
        self.assertEqual(self.win.ed.hit(self.win._ed_notes, px, py), live_row,
                         "the pane's own hit test answers a different row than the frame it is "
                         "showing, so its marks describe a picture nobody is looking at")
        self.assertEqual(self.win.ed.index, live_row,
                         f"the press selected row {self.win.ed.index}; the frame on screen "
                         f"draws row {live_row} at {px},{py} (the pinned frame would have "
                         f"answered {pinned_row})")

    def test_an_arrow_key_writes_on_the_live_frame_and_says_no_refusal(self):
        self.open_layout()
        cold, hot = self.bodies()
        drawable = [ri for _kind, _what, box, ri in (self.notes_at(hot).get("boxes") or []) if box]
        self.assertTrue(drawable, "the hot body draws no row of `bars`, so there is nothing to nudge")
        row = drawable[0]
        self.win.ed.select(row)
        prop = self.win.ed.prop()
        if "x" not in prop:
            self.skipTest(f"row {row} carries no `x` to nudge: pick a placeable row instead")
        before = int(prop["x"])
        self.go_live(hot)
        self.win.ed.select(row)
        self.key_right()
        self.assertEqual(int(self.win.ed.prop()["x"]), before + 1,
                         f"an arrow key moved the row from {before} to "
                         f"{self.win.ed.prop()['x']} on the live frame")
        self.assertNotEqual(self.note(), self.win.ed.peek_refusal("An arrow key"),
                            "the live pane answered with the held peek's refusal")

    def count_paints(self) -> list:
        real, seen = self.win.ed.paint, []

        def counted(*args, **kw):
            out = real(*args, **kw)
            seen.append(1)
            return out
        self.win.ed.paint = counted
        self.addCleanup(setattr, self.win.ed, "paint", real)
        return seen

    def test_a_live_repaint_asks_the_painter_once_and_a_held_one_twice(self):
        """Live mode draws one frame; a held peek draws two, and the count says which is which.

        Following the machine naively painted the fixture and then the live body, twice per
        event: measured on this bench at **19.9 ms a drag move against 11.6 ms** with the knob
        on `the fixture`.  In live mode nothing reads the fixture's boxes any more - the marks,
        the hit test and the snap lines all come from the live paint - so that first drawing
        bought nothing at all.  Counted here rather than timed, because a duration belongs to a
        box and this count does not, and the held mode is asserted at two so the counter cannot
        quietly be counting nothing.
        """
        self.open_layout()
        _cold, hot = self.bodies()
        self.go_live(hot)
        paints = self.count_paints()
        self.win._repaint(readings=False)           # what one mouse-move of a drag does
        self.assertEqual(len(paints), 1,
                         f"{len(paints)} drawings for one live repaint: the frame a live pane "
                         "shows is the one it paints, so a second drawing of the pinned fixture "
                         "is a whole picture nobody looks at")
        self.pick("file", HOT_METRICS)
        paints.clear()
        self.win._repaint(readings=False)
        self.assertEqual(len(paints), 2,
                         f"{len(paints)} drawings for one held repaint: a held peek needs the "
                         "pinned frame for its boxes and the file's body for its pixels, and if "
                         "that stops being two this check has stopped measuring")

    def test_a_held_peek_still_hides_its_marks_while_the_live_one_shows_them(self):
        """The two entries on one knob, told apart by the only thing that matters: whether the
        frame on screen is the frame a press answers at."""
        self.open_layout()
        self.assertTrue(self.win.preview.marks and self.win.preview.marks[0],
                        "the marks were not there before either mode, so taking them away in one "
                        "of them proves nothing")
        _cold, hot = self.bodies()
        self.go_live(hot)
        self.assertTrue(self.win.preview.marks and self.win.preview.marks[0],
                        "no marks in live mode")
        self.pick("file", HOT_METRICS)
        self.assertFalse(self.win._peek["live"], "a file peek came up live: it would re-read the "
                                                "file on every tick and stop being the same "
                                                "picture twice")
        self.assertIsNone(self.win.preview.marks or None,
                          "the held peek is painting marks it cannot honestly claim")
        self.assertIn("peeking", (self.win.preview.toolTip() or ""), self.win.preview.toolTip()[:160])


if __name__ == "__main__":
    unittest.main(verbosity=2)
