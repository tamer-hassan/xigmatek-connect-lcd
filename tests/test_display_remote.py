#!/usr/bin/env python3
"""The window driving a display that is already running: a real socket, and never a port.

Ported from `tools/selftest.sh`'s display-remote section.  The other process is modelled honestly -
the same `control.Control` and `control.Server` a running `xigmalcd` builds, with a settings object
standing in for its argparse namespace - and the port it "owns" is a name that does not exist.  The
point of the shape is that the window's route to the panel goes through the process that holds the
port, so a check of that route cannot open one: `panel.port_busy` is replaced with a recorder, and
**the recorder staying empty is itself one of the assertions**.

Two more claims worth their lines:

* a refused reset is reported as the daemon's own refusal, in the daemon's words.  "The panel did not
  answer" is a different failure, and a reader who is told that goes looking for a cable;
* an older display that never reports `text_color` does not get offered a command it cannot take, and
  the window says which settings it left alone rather than reporting a partial success as a whole one.
  That is modelled by taking the key out of the answers - all the window can actually see - rather
  than by installing an old package.
"""
from __future__ import annotations

import inspect
import os
import re
import tempfile
import time
import unittest

from tests import fixtures

from xigmalcd import control, render
from xigmaui import app, panel

STUB_PORT = "/dev/xigma-stub-port"


class DisplayArgs:
    """Stands in for the running daemon's parsed namespace."""
    theme = "alpha"
    fps = 1.0
    title = None
    label = None
    scrim = None
    clock_size = 26
    text_color = None
    bg = "clear"
    mp4 = os.path.join(fixtures.REPO, "media", "Theme_25.mp4")
    no_fans = False


class DisplayHarness(fixtures.FreshConfigRoot):
    """A window pointed at a running display: a real socket, an in-process `Control`, and a port
    name that does not exist.

    Split out from the checks below because a second file drives the same harness to a different
    door (`test_apply_layout.py`), and building that shape twice is how the two would drift.
    """

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="xigma-remote-")
        self.args = DisplayArgs()
        self.ctl = control.Control(self.args, "/dev/xigma-stub")
        self.ctl.publish(frames=41, ok=40, refused=0, errors=0, renewals=1,
                         last_notice="200", last_name="2026-11-06_15-00-00-000.osd",
                         last_bytes=9413, session_uploads=40, session_age=20.0,
                         device={"space": 62416})
        self.srv = control.Server(self.ctl, os.path.join(self.tmp.name, "x.sock"))
        if not self.srv.start():
            raise AssertionError(f"the control server would not start: {self.srv.error}")
        self.looked = []
        self.real_busy = panel.port_busy
        panel.port_busy = lambda port: (self.looked.append(port), "")[1]
        self.win = app.Window(STUB_PORT, 1.0, restore=False, socket=self.srv.path, tray=False)
        self.win.show()
        fixtures.pump(0.2)

    def tearDown(self):
        fixtures.close_window(self.win)
        self.srv.stop()
        panel.port_busy = self.real_busy
        self.tmp.cleanup()
        super().tearDown()

    def logs(self) -> str:
        return "\n".join(self.win._log_lines)



class ApplyCarriesTheBackground(DisplayHarness):
    """`Apply these settings` and the stored layer: what the button sends, and what it refuses to.

    Changed on 2026-11-14 at the owner's request - the second click on "Send this background to
    the panel" is folded into Apply, but **only while \"keep my background\" is unticked**, because
    that box is the reader's own veto over anything moving the stored layer.  Four of the six
    checks here are about the branches where nothing is sent: a button that uploads on one
    machine and not another, without saying so, is worse than one that never uploads.

    Everything is read from the display's side - `Control.take()` is what the frame loop would
    find - so these checks ask \"did an action reach the queue\", not \"did the window print a
    sentence\".  The log lines are asserted too, because a silent skip and a silent refusal look
    identical to a reader who is not watching the ring.
    """

    def setUp(self):
        super().setUp()
        self.other = os.path.join(fixtures.REPO, "media", "Theme_11.mp4")
        self.same = os.path.join(fixtures.REPO, "media", "Theme_25.mp4")
        for path in (self.other, self.same):
            if not os.path.exists(path):
                self.skipTest(f"no {os.path.basename(path)} in this checkout to select")
        self.win.mp4 = self.other

    def pending(self):
        """The action the loop would find if it asked - the only honest yes/no here."""
        return self.ctl.take()

    def test_apply_uploads_the_selected_clip_when_the_box_is_unticked(self):
        self.win.keep_clip = False
        self.win._stored_bg = "theme_47.mp4"       # the ring says a different layer is stored
        self.assertIsNone(self.pending(), "the harness began with something already queued")
        self.win.btn_apply.click()
        got = self.pending()
        self.assertIsNotNone(got, f"nothing reached the loop: {self.logs()[-400:]}")
        kind, path = got
        self.assertEqual(kind, "upload", got)
        self.assertEqual(os.path.basename(str(path)), "Theme_11.mp4", got)
        said = self.logs()
        self.assertIn("the background goes with them: Theme_11.mp4", said, said[-400:])
        self.assertIn("theme_47.mp4", said,
                      "the log never named the layer the panel was holding")
        self.assertIn("queued for its frame loop", said,
                      "the queue answer came from the display's door, not a sentence of ours")

    def test_the_box_stops_the_upload_and_says_which_box_stopped_it(self):
        # the checkbox itself, not the handler: a click emits the signal the window is wired
        # to, so this is the state a reader actually leaves the box in
        self.win.chk_keep.setChecked(True)
        self.assertTrue(self.win.keep_clip, self.win.chk_keep.text())
        fixtures.pump(0.05)
        self.assertIsNone(self.pending(), "toggling the box queued something on its own")
        self.win.btn_apply.click()
        self.assertIsNone(self.pending(),
                          'an upload went out while "keep my background" was ticked')
        self.assertIn("your background stayed", self.logs(),
                      "Apply moved the settings and left the reader to infer why the layer "
                      "did not follow")

    def test_no_bytes_go_when_the_panel_already_holds_that_very_clip(self):
        self.win.keep_clip = False
        self.win.mp4 = self.same
        self.win._stored_bg = os.path.basename(self.same)
        self.win.btn_apply.click()
        self.assertIsNone(self.pending(),
                          "the button pushed a file over a port that already stores it")
        self.assertIn("already stores Theme_25.mp4", self.logs(), self.logs()[-400:])

    def test_an_unread_ring_sends_rather_than_guessing_that_it_is_already_right(self):
        """A window that has seen no accept cannot claim the layer is in place.

        The empty `_stored_bg` is the state a freshly opened window is in, and the two ways out
        (send, or stay quiet and say nothing) both have to be refused in code: the first is what
        the button does, and the second is the silence this repository keeps calling a defect.
        """
        self.win.keep_clip = False
        self.win._stored_bg = ""
        self.win.btn_apply.click()
        got = self.pending()
        self.assertIsNotNone(got, "with nothing read from the ring, the button stayed quiet")
        self.assertIn("no accept from the display yet", self.logs(), self.logs()[-400:])

    def test_nothing_is_sent_when_the_clips_box_holds_no_selection(self):
        self.win.keep_clip = False
        self.win.mp4 = ""
        self.win.btn_apply.click()
        self.assertIsNone(self.pending(), "an empty selection became an empty upload")
        self.assertIn("nothing is selected in the clips box", self.logs(), self.logs()[-400:])

    def test_a_refused_upload_is_reported_in_the_display_s_own_words(self):
        """The loop holds one action slot, so an upload can be refused - and a refusal over
        this socket has to arrive as the display's sentence, not as silence between two of ours.

        The window's own line says Apply tried; the display's line says why it did not land.
        Both are asserted, because the reason is the actionable half: "already queued: X" names
        what is in front of this upload, and a paraphrase of it throws that away.
        """
        self.win.keep_clip = False
        self.win._stored_bg = "theme_47.mp4"
        self.ctl._queue("frame", None)          # whatever the loop was already going to do
        self.win.btn_apply.click()
        got = self.pending()
        self.assertEqual(got, ("frame", None),
                          f"Apply displaced an action already queued for the loop: {got}")
        said = self.logs()
        self.assertIn("the background goes with them: Theme_11.mp4", said, said[-400:])
        self.assertIn("the display would not queue Theme_11.mp4", said, said[-400:])
        self.assertIn("already queued", said,
                      "the display's own reason did not survive into the window's log")

    def test_both_upload_doors_read_the_wire_knobs_from_one_place(self):
        """Apply calls the clips box's own queue rather than carrying a second copy of a write.

        The gap and chunk are measured wire facts held in `xigmalcd/protocol.py`; a second
        literal in the window is how a measured number becomes a preference someone later
        tunes.  Counted out of the shipped source, not asserted as a rate.
        """
        whole = inspect.getsource(app.Window)
        apply_body = inspect.getsource(app.Window._apply_to_display)
        self.assertEqual(whole.count("protocol.MEDIA_GAP"), 2,
                         f"{whole.count('protocol.MEDIA_GAP')} uses of the measured gap: the "
                         "clips box and Apply are meant to read one source, not two copies")
        self.assertEqual(whole.count("protocol.MEDIA_CHUNK"), 2,
                         "the chunk size is likewise asked from one place by both doors")
        # Apply goes through the same door, and there is exactly one such door per kind
        self.assertIn('self.queue("upload"', apply_body.replace("\n", " ").replace("( ", "("),
                      "Apply uploads by its own route rather than the clips box's")
        self.assertEqual(len(re.findall(r"gap=0\.0\d+|chunk=1000\b", whole)), 0,
                         "a wire literal has appeared in the window beside the protocol name")
        self.assertEqual(len(re.findall(r"self\.panel\.queue\(", whole)), 1,
                         f"a second direct port route appeared: the window is meant to have "
                         "one place where it talks to the port itself")

class WindowDrivingADisplay(DisplayHarness):
    def test_the_window_finds_the_display_and_reads_its_published_counters(self):
        self.assertTrue(self.win.daemon.present, self.win.daemon.path)
        self.assertTrue(self.win.d_line.text().startswith("showing alpha"), self.win.d_line.text())
        self.assertIn("40/41 uploads the panel confirmed", self.win.d_counters.text(),
                      self.win.d_counters.text())
        self.assertTrue(self.win.btn_apply.isEnabled())
        self.assertTrue(self.win.btn_pause.isEnabled())

    def test_every_action_goes_to_the_display_and_the_port_is_never_even_looked_at(self):
        self.win.queue("frame")
        self.assertEqual(self.ctl.take(), ("frame", None), "that frame did not go to the display")
        self.assertFalse(self.win.panel.isRunning(),
                         "the window started its own panel thread while a display owned the port")
        clip = os.path.join(fixtures.REPO, "media", "Theme_25.mp4")
        self.win.queue("upload", path=clip, gap=0.02, chunk=1000)
        kind, path = self.ctl.take()
        self.assertEqual((kind, os.path.basename(path or "")), ("upload", "Theme_25.mp4"))
        self.win.queue("status")
        fixtures.pump(0.2)
        self.assertIn("40/41 uploads", self.win.d_counters.text())
        self.assertEqual(self.looked, [],
                         f"the window consulted a port while a display owned it: {self.looked}")

    def test_the_status_box_shows_the_display_s_hello_and_says_it_is_not_a_fresh_read(self):
        self.assertIn("not a fresh read", self.win.status.text(), self.win.status.text())
        self.assertIn("space=62416", self.win.status.text(), self.win.status.text())

    def test_a_reset_the_display_refuses_is_quoted_and_not_called_no_answer(self):
        self.win.queue("reset", confirm="reset")
        fixtures.pump(0.3)
        text = self.logs()
        self.assertIn("the display refused reset", text, text[-400:])
        self.assertIn("reset_panel.py", text, text[-400:])
        self.assertNotIn("no answer", text[-400:],
                         "a refusal was reported as a timeout, which sends a reader to the cable")

    def test_apply_sends_the_pickers_to_the_display_s_own_settings_quickly(self):
        self.win.theme.setCurrentText("gauge")
        self.win.clock_size.setValue(44)
        self.win._set_ink_choice("amber")
        self.win.canvas.setCurrentIndex(1)              # black
        self.win.scrim.setValue(-1)                     # -1 means auto, and stays auto
        self.win.fanline.setChecked(False)
        self.win.d_fps.setValue(2.0)
        started = time.perf_counter()
        self.win.btn_apply.click()
        took = time.perf_counter() - started
        self.assertEqual((self.args.theme, self.args.clock_size, self.args.bg, self.args.scrim),
                         ("gauge", 44, "black", None), self.args.__dict__)
        self.assertIs(self.args.no_fans, True)
        self.assertEqual(self.args.fps, 2.0)
        self.assertLess(took, 0.5, f"{took:.2f} s: seven socket commands, no serial round trip")
        self.assertIn("display told: theme gauge", self.logs())
        self.assertEqual(self.args.text_color, (*render.AMBER[:3], 255))
        self.assertEqual(self.ctl.status()["text_color"], "#ffc400")
        self.win.daemon.poll(report=True)
        fixtures.pump(0.2)
        self.assertIn("text #ffc400", self.win.d_counters.text(),
                      "this is the only place a reader can see the colour the *display* holds, "
                      "as opposed to the one this window would send")

    def test_an_older_display_that_never_mentions_text_color_is_not_offered_that_command(self):
        """The author's own desktop is the mixed-version case: this window from the tree, the
        display from an older package.  All the window can see is the answer, so the key is taken
        out of the answers."""
        real = self.ctl.status

        def like_an_old_display() -> dict:
            status = real()
            status.pop("text_color", None)
            return status

        self.ctl.status = like_an_old_display
        try:
            self.win.daemon.poll(report=True)
            fixtures.pump(0.2)
            self.assertFalse(self.win.daemon.knows("text_color"),
                             "the window is about to send a command this display cannot take")
            self.assertTrue(self.win.daemon.knows("theme"))
            self.assertFalse(self.win.ink_choice.isEnabled(),
                             "the ink row stayed live against a display that cannot set it")
            self.assertIn("INACTIVE", self.win.ink_choice.toolTip(),
                          self.win.ink_choice.toolTip())
            self.assertIn("not reported by this display", self.win.d_counters.text(),
                          self.win.d_counters.text())
            self.win.btn_apply.click()
            fixtures.pump(0.3)
            self.assertEqual(self.args.theme, self.win.theme.currentText())
            text = self.logs()
            self.assertIn("left text_color alone", text, text[-500:])
            self.assertNotIn("unknown cmd", text, "the window sent a command the display refused")
        finally:
            self.ctl.status = real
            self.win.daemon.poll(report=True)
            fixtures.pump(0.2)
            self.assertTrue(self.win.daemon.knows("text_color"),
                            "the patch outlived the check, so later assertions would measure it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
