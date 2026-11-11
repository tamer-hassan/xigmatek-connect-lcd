#!/usr/bin/env python3
"""The control socket: one owner of the port, and exactly what a client may ask it for.

Ported from `tools/selftest.sh`'s control-socket section.  Nothing here opens a serial device: the
`Control` object is handed a path that is a stub name, `Control.__init__` only *stores* it, and the
loop's executors run against an injected fake link.  A real unix socket in a temp directory is used,
because "what a client may ask for" is a claim about the door, not about a function someone could
call directly.

The gates in this file are the reason the package can be installed on a machine with a panel
attached and left running:

* `reset` is refused unless the daemon was started with `--allow-reset`, and the refusal names the
  two ways to do it deliberately;
* `quit` is refused in favour of systemd, because a display that answers to a socket should not be
  able to stop its own service by asking nicely;
* an upload refuses a firmware-shaped file - the media channel is not PROTOCOL.md §7's path;
* a second daemon on the same socket is refused rather than replacing the first, and the socket
  file is mode 0600.
"""
from __future__ import annotations

import contextlib
import io
import os
import socket
import subprocess
import sys
import tempfile
import unittest

from tests import fixtures

from xigmalcd import control
from xigmalcd import main as daemon
from xigmalcd import protocol
from xigmalcd import render
from xigmalcd import themes

STUB_PORT = "/dev/xigma-stub"


class Args:
    """Stands in for the daemon's parsed namespace.  `gap` and `chunk` are here because the
    upload shape is not a client's to set."""
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
    gap = protocol.MEDIA_GAP
    chunk = protocol.MEDIA_CHUNK
    no_sleep = False
    baud = 115200
    verbose = False


class WhereTheSocketIs(unittest.TestCase):
    """The unit sets `$XDG_RUNTIME_DIR`; a shell or a test does not; `$XIGMA_SOCKET` beats both -
    and the window has to find the same path the daemon created."""

    def setUp(self):
        self.saved = os.environ.pop(control.SOCKET_ENV, None)

    def tearDown(self):
        if self.saved is not None:
            os.environ[control.SOCKET_ENV] = self.saved

    def test_the_environment_names_it_when_it_is_set(self):
        os.environ[control.SOCKET_ENV] = "/tmp/example.sock"
        self.assertEqual(control.socket_path(), "/tmp/example.sock")

    def test_without_it_somewhere_that_exists_and_is_private_answers(self):
        where = control.socket_path()
        self.assertTrue(where.endswith(control.DEFAULT_NAME) or "xigma" in os.path.basename(where),
                        where)
        self.assertTrue(os.path.isdir(os.path.dirname(where)), where)

    def test_an_explicit_path_is_expanded_and_absolute(self):
        got = control.socket_path("~/never-created.sock")
        self.assertNotIn("~", got)
        self.assertTrue(got.startswith(os.path.expanduser("~") + os.sep), got)


class OneOwner(unittest.TestCase):
    """A real server thread on a real socket file, over a stubbed port."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="xigma-ctl-")
        cls.args = Args()
        cls.ctl = control.Control(cls.args, STUB_PORT)
        cls.srv = control.Server(cls.ctl, os.path.join(cls.tmp.name, "x.sock"))
        if not cls.srv.start():
            raise AssertionError(f"the control server would not start: {cls.srv.error}")
        cls.client = control.Client(cls.srv.path)

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.args.theme = "alpha"
        self.args.fps = 1.0
        self.args.scrim = None
        self.args.bg = "clear"
        self.args.text_color = None
        # the counters a client reads are published by the loop, and this class shares one server,
        # so every test starts where a loop that has drawn nothing would be
        self.ctl.publish(frames=0, ok=0, refused=0, renewals=0, session_uploads=0,
                         session_age=0.0, last_notice="", last_name="", last_bytes=0, device={})

    def test_the_socket_is_private_to_this_user(self):
        mode = os.stat(self.srv.path).st_mode & 0o777
        self.assertEqual(mode, 0o600, oct(mode))

    def test_a_client_reads_the_settings_the_loop_is_running_with(self):
        self.assertTrue(self.client.available())
        status = self.client.status()
        self.assertEqual(status["theme"], "alpha")
        self.assertEqual(status["port"], STUB_PORT)
        self.assertFalse(status["paused"])
        self.assertEqual(status["frames"], 0)
        self.assertIn("showing alpha", control.describe(status))

    def test_a_theme_name_means_the_same_thing_here_as_on_the_command_line(self):
        refused = self.client.ask({"cmd": "theme", "value": "nope"})
        self.assertFalse(refused["ok"])
        self.assertIn("unknown theme", refused["error"])
        self.assertEqual(self.args.theme, "alpha")
        self.assertTrue(self.client.ask({"cmd": "theme", "value": "gauge"})["ok"])
        self.assertEqual(self.args.theme, "gauge")
        library = themes.selectable()[0]["name"]
        self.assertTrue(self.client.ask({"cmd": "theme", "value": library})["ok"], library)
        self.assertEqual(self.args.theme, library)
        rejected = self.client.ask({"cmd": "theme", "value": themes.scan()[1][0]["name"]})
        self.assertFalse(rejected["ok"])
        self.assertIn("ratio 4:3", rejected["error"],
                      "the canvas refusal is quoted back, not swallowed")

    def test_ranges_are_refused_and_the_stored_setting_unchanged(self):
        for cmd, bad, good, attr in (("fps", 99, 1.5, "fps"), ("scrim", 300, 150, "scrim")):
            with self.subTest(cmd=cmd):
                self.assertFalse(self.client.ask({"cmd": cmd, "value": bad})["ok"])
                self.assertNotEqual(getattr(self.args, attr), bad)
                self.assertTrue(self.client.ask({"cmd": cmd, "value": good})["ok"])
                self.assertEqual(getattr(self.args, attr), good)
        self.assertFalse(self.client.ask({"cmd": "fps", "value": "hot"})["ok"])
        self.assertEqual(self.args.fps, 1.5)
        self.assertFalse(self.client.ask({"cmd": "bg", "value": "blue"})["ok"])
        self.assertTrue(self.client.ask({"cmd": "bg", "value": "black"})["ok"])
        self.assertEqual(self.args.bg, "black")
        self.assertTrue(self.client.ask({"cmd": "title", "value": "Xigma"})["ok"])
        self.assertEqual(self.args.title, "Xigma")
        self.assertTrue(self.client.ask({"cmd": "clock_size", "value": 40})["ok"])
        self.assertEqual(self.args.clock_size, 40)
        self.assertFalse(self.client.ask({"cmd": "nope"})["ok"])

    def test_text_colour_uses_the_same_parser_and_does_not_take_a_port_slot(self):
        before_events = len(self.client.status()["events"])
        self.assertTrue(self.client.ask({"cmd": "text_color", "value": "amber"})["ok"])
        self.assertEqual(self.args.text_color, (*render.AMBER[:3], 255))
        self.assertEqual(self.client.status()["text_color"], "#ffc400",
                         "read back as the same hex a client can send again")
        self.assertEqual(self.client.ask({"cmd": "config"})["config"]["text_color"], "#ffc400")
        bad = self.client.ask({"cmd": "text_color", "value": "cerise"})
        self.assertFalse(bad["ok"])
        self.assertIn("try #rrggbb", bad["error"])
        for quiet in (None, "", "default"):
            with self.subTest(cleared=repr(quiet)):
                self.assertTrue(self.client.ask({"cmd": "text_color", "value": quiet})["ok"])
                self.assertIsNone(self.client.status()["text_color"],
                                  "back to the theme's own skin")
        self.assertEqual(len(self.client.status()["events"]), before_events,
                         "a colour change took a slot in the port's event ring, which it "
                         "reaches only as pixels")

    def test_pause_and_resume_are_the_loops_own(self):
        self.assertTrue(self.client.ask({"cmd": "pause"})["ok"])
        self.assertTrue(self.ctl.paused)
        self.assertTrue(self.client.status()["paused"])
        self.assertIn("paused", control.describe(self.client.status()))
        self.assertTrue(self.client.ask({"cmd": "resume"})["ok"])
        self.assertFalse(self.ctl.paused)

    def test_an_upload_is_refused_before_it_reaches_the_queue(self):
        """Nothing firmware-shaped, and nothing the media channel cannot hold: PROTOCOL.md §7 is a
        different path."""
        with tempfile.TemporaryDirectory() as td:
            fake = os.path.join(td, "fw.zip")
            with open(fake, "wb") as fh:
                fh.write(b"PK\x03\x04fake")
            refused = self.client.ask({"cmd": "upload", "path": fake})
            self.assertFalse(refused["ok"])
            self.assertIn("firmware", refused["error"])
            big = os.path.join(td, "big.mp4")
            with open(big, "wb") as fh:
                fh.truncate(9_000_000)
            self.assertFalse(self.client.ask({"cmd": "upload", "path": big})["ok"])
        self.assertFalse(self.client.ask({"cmd": "upload", "path": "/nope/missing.mp4"})["ok"])
        self.assertFalse(self.client.ask({"cmd": "upload"})["ok"])
        self.assertIsNone(self.ctl.take(), "a refused upload left something for the loop to do")

    def test_one_action_at_a_time_and_the_client_can_see_it(self):
        clip = os.path.join(fixtures.REPO, "media", "Theme_25.mp4")
        asked = self.client.ask({"cmd": "upload", "path": clip})
        self.assertTrue(asked["ok"], asked)
        self.assertEqual(asked["queued"], "upload")
        self.assertEqual(self.client.status()["pending"], "upload")
        again = self.client.ask({"cmd": "upload", "path": clip})
        self.assertFalse(again["ok"])
        self.assertIn("already queued", again["error"])
        self.assertEqual(self.ctl.take(), ("upload", clip))
        self.assertIsNone(self.ctl.take())
        self.assertEqual(self.client.status()["pending"], "")

    def test_reset_is_refused_unless_the_daemon_was_started_to_allow_it(self):
        refused = self.client.ask({"cmd": "reset"})
        self.assertFalse(refused["ok"])
        self.assertIn("reset_panel.py", refused["error"],
                      "the refusal names how to do it deliberately")
        self.assertIsNone(self.ctl.take())
        free = control.Control(Args(), STUB_PORT, allow_reset=True)
        self.assertTrue(free.request({"cmd": "reset"})["ok"])
        self.assertEqual(free.take(), ("reset", None),
                         "the loop, not the socket, is the one that would act on it")

    def test_quit_is_refused_in_favour_of_systemd(self):
        refused = self.client.ask({"cmd": "quit"})
        self.assertFalse(refused["ok"])
        self.assertIn("systemctl", refused["error"])

    def test_junk_from_a_client_is_answered_and_the_thread_survives(self):
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.connect(self.srv.path)
        try:
            conn.sendall(b"not json\n")
            self.assertIn(b"not JSON", conn.recv(4096))
        finally:
            conn.close()
        self.assertTrue(self.client.available(), "the server stopped answering")

    def test_a_second_daemon_on_the_same_socket_is_refused_rather_than_replacing_the_first(self):
        second = control.Server(self.ctl, self.srv.path)
        self.assertFalse(second.start())
        self.assertIn("already running", second.error)

    def test_a_client_reading_mid_frame_gets_a_copy_not_a_live_dict(self):
        self.ctl.publish(frames=12, ok=11, refused=1, renewals=2, last_notice="200",
                         last_name="2026-11-06_15-00-00-000.osd", last_bytes=9413,
                         session_uploads=11, session_age=11.0, device={"space": 62416})
        status = self.client.status()
        self.assertEqual((status["frames"], status["ok"], status["refused"], status["renewals"]),
                         (12, 11, 1, 2), status)
        self.assertEqual(status["device"]["space"], 62416)
        status["frames"] = 999
        self.assertEqual(self.client.status()["frames"], 12,
                         "`status()` handed out the live counters")

    def test_the_command_line_asks_the_running_display_through_the_same_socket(self):
        self.ctl.publish(frames=12, ok=11, refused=1, renewals=2, last_notice="200",
                         last_name="2026-11-06_15-00-00-000.osd", last_bytes=9413,
                         session_uploads=11, session_age=11.0, device={"space": 62416})
        env = dict(os.environ, XIGMA_SOCKET=self.srv.path)
        got = subprocess.run([sys.executable, "-m", "xigmalcd", "--status"],
                             capture_output=True, text=True, env=env, cwd=fixtures.REPO)
        self.assertEqual(got.returncode, 0, got.stderr)
        published = control.Client(self.srv.path).status()
        self.assertIn(f"showing {published['theme']} at {published['fps']} fps", got.stdout,
                      got.stdout)
        self.assertIn("11/12 uploads the panel confirmed", got.stdout)
        self.assertIn("settings: theme alpha", got.stdout)

    def test_no_display_answering_is_an_exit_1_and_a_sentence(self):
        env = dict(os.environ, XIGMA_SOCKET=os.path.join(self.tmp.name, "gone.sock"))
        got = subprocess.run([sys.executable, "-m", "xigmalcd", "--status"],
                             capture_output=True, text=True, env=env, cwd=fixtures.REPO)
        self.assertEqual(got.returncode, 1)
        self.assertIn("no display answering", got.stderr)


class LoopExecutors(unittest.TestCase):
    """The socket leaves one request in a slot; the loop's thread does the work, so the fake link
    is where the truth is."""

    class FakeLink:
        def __init__(self, **kwargs):
            self.posts, self.sent = [], []

        def close(self):
            pass

        def drain(self, timeout=0.15):
            pass

        def hello(self, keepalive=60):
            return self.device_info()

        def device_info(self):
            return {"space": 62424}

        def post(self, verb, obj=None):
            self.posts.append(verb)

        def send_media(self, name, data, **kwargs):
            self.sent.append((name, len(data), kwargs.get("gap")))
            return {"notice": "200"}

    def test_an_upload_a_client_asked_for_is_carried_out_by_the_ports_only_owner(self):
        args = Args()
        ctl = control.Control(args, "/dev/xigma-no-such-port", allow_reset=True)
        clip = os.path.join(fixtures.REPO, "media", "Theme_25.mp4")
        self.assertTrue(ctl.request({"cmd": "upload", "path": clip})["ok"])
        link = self.FakeLink()
        report = io.StringIO()
        with contextlib.redirect_stderr(report):
            daemon._run_action(link, "/dev/xigma-no-such-port", args, ctl, ctl.take())
        self.assertEqual(len(link.sent), 1, link.sent)
        self.assertEqual(link.sent[-1][:2], ("Theme_25.mp4", 214_917), link.sent)
        self.assertIn("accepted", ctl.status()["events"][-1], ctl.status()["events"])
        # the loop's own line: what went up, what the panel answered, and the space either side
        self.assertIn("Theme_25.mp4 214917 B", report.getvalue(), report.getvalue())
        self.assertIn("notice 200", report.getvalue())

    def test_the_reset_path_posts_recovery_once_and_only_because_it_was_asked(self):
        args = Args()
        ctl = control.Control(args, "/dev/xigma-no-such-port", allow_reset=True)
        self.assertTrue(ctl.request({"cmd": "reset"})["ok"])
        link = self.FakeLink()
        report = io.StringIO()
        with contextlib.redirect_stderr(report):
            daemon._run_action(link, "/dev/xigma-no-such-port", args, ctl, ctl.take())
        self.assertEqual(link.posts, ["recovery"], link.posts)
        self.assertIn("recovery requested over the control socket", report.getvalue(),
                      "a client asking for a reset should leave a line in the loop's log")
        self.assertTrue(any("stored" in note for note in ctl.status()["events"]),
                        "the note about what a reset costs is what a person reads afterwards")


class AFailedRunLeavesNoSocket(unittest.TestCase):
    """The precondition for the window's presence check not lying."""

    def test_a_run_that_cannot_open_its_port_leaves_no_socket_behind(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "dead.sock")
            got = subprocess.run([sys.executable, "-m", "xigmalcd", "--device",
                                  "/dev/xigma-no-such-port", "--once"],
                                 capture_output=True, text=True, cwd=fixtures.REPO,
                                 env=dict(os.environ, XIGMA_SOCKET=path))
            self.assertEqual(got.returncode, 2, got.stdout + got.stderr)
            self.assertFalse(os.path.exists(path),
                             "a window asking whether a display is running would have "
                             "found one that was not")


if __name__ == "__main__":
    unittest.main(verbosity=2)
