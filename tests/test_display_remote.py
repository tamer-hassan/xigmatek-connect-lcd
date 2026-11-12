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

import os
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
