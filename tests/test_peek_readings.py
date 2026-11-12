#!/usr/bin/env python3
"""Feature G: the pane can look at another body of readings, and refuses to be edited inside it.

Ported from the peek block of `tools/selftest.sh`'s GUI section.  The knob under *pane readings*
chooses what the editor's preview paints with: the pinned fixture (the frame every edit is judged
at), this machine's own sensors, or a `STATE all 1` file named in the box beside it.  Only the
first is editable, and the reason is measured rather than philosophical:

* drawing these layouts at the fixture and at another body moves the row boxes, and
  `test_the_row_boxes_change_owner_across_the_glass_between_two_bodies` probes the glass on a grid
  and counts the points that answer a **different row** in one frame than in the other - measured
  against a pinned file rather than this machine's sensors, so the count answers the same on every
  machine.  A handle drawn at a pinned edge would sit over another row's ink, and a drag would grab
  a row nobody pointed at;
* any number such a drag wrote would belong to a sample that is gone a second later: feature F
  derives a centred row's `x` from the width of its ink, and ink width follows the reading.

So in a peek the geometry doors stay shut, the marks go away, and the note line says which knob
puts the editable frame back.  What is *read* is held rather than re-sampled: `sensors.collect()`
or the file is read once per press on the knob and never per repaint - the proof here is a counter
on the door and a byte-for-byte comparison of the held layer.

Two kinds of body, and the assertions are split by what they depend on.  The files in
`tools/metrics/` are pinned, so a count taken against them answers the same on this bench and on
CI's runner and is asserted exactly (`57°C` at the fixture against `104°C` at that file).  This
machine's own sensors are a fact about this machine: what is asserted there is the *shape* - a peek
is held, a press does not re-sample it, the dict handed out is a copy - and never how many pixels a
second of load is worth.
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
        row = next(i for i, widget in enumerate(self.win.ed.widgets())
                   if "Temperature" in str(((widget.get("property") or [{}])[0]).get("source")
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
        by_row = {ri: box for _kind, _what, box, ri in (live.get("boxes") or [])}
        moved = sorted({ri for _kind, _what, box, ri in (pinned.get("boxes") or [])
                        if ri in by_row and tuple(box) != tuple(by_row[ri])})
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

    def test_a_press_samples_the_machine_once_and_a_repaint_leaves_the_frame_alone(self):
        """`sensors.collect()` is the expensive door - 71.8 ms on this bench, per `app.py`'s own
        note - and the pane already pays for it on every repaint to fill its counters line.  What
        *held* means is that the picture does not follow that: the peek's body is sampled once per
        press, and a repaint leaves the frame on screen exactly where it was.

        The two doors are counted separately, because the sentence a reader needs is the second
        one: a press costs one sample **for the body** plus the one its own repaint asks for.
        """
        self.open_layout()
        self.win.preview_timer.stop()               # a tick of the pane is not a press
        samples = []
        real = sensors.collect

        def counting():
            body = real()
            samples.append(body)
            return body

        sensors.collect = counting
        try:
            self.pick("sensors")
            self.assertEqual(len(samples), 2,
                             f"{len(samples)} samples for one press: one for the body the pane "
                             "names and one for the repaint that press triggered")
            held = dict(self.win._peek["metrics"])
            layer = self.layer()
            samples.clear()
            self.win._repaint()
            self.win._repaint()
            self.assertEqual(len(samples), 2,
                             f"{len(samples)} samples for two repaints: the counters line needs "
                             "one each, and nothing else may ask")
            self.assertEqual(self.win._peek["metrics"], held,
                             "the held body moved under the picture: the peek is following the "
                             "sensors, not holding a sample")
            self.assertEqual(self.layer(), layer,
                             "the picture changed on a repaint, with no edit and no press in "
                             "between")
            self.assertEqual(self.layer(), self.paint_of(held),
                             "the pane is not showing the body it names")
        finally:
            sensors.collect = real

    def test_the_held_body_is_a_copy_so_a_caller_cannot_wear_it_down(self):
        """`edit.fixture()`'s shallow copy once cost every later draw a derived rate; the same
        hazard exists one level over, in a peek that hands out the dict `sensors.collect()` made."""
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
