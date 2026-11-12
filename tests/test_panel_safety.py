#!/usr/bin/env python3
"""The panel-facing worker, with the serial layer replaced: what may reach the wire, and who may ask.

Ported from the stubbed-actions block of `tools/selftest.sh`'s GUI section.  `panel.Link` is
**replaced, not wrapped**, so this file cannot open a port even by accident - which is the whole
reason the block existed in `tools/selftest.sh` and the reason it survives here.

Three safety facts and two protocol facts:

* exactly one place in `Panel` asks for a destructive link, it is `_reset`, and `_reset` refuses
  unless a person typed the word into the box;
* a reset that is allowed opens **one** destructive link in the whole act - and the link it opens
  afterwards to re-read status is an ordinary one, because the vendor's reset re-enumerates the USB
  device and the fd it held died under it;
* PROTOCOL.md §8's rule - the metrics blob goes at the head of a session, twice, and never between
  files - is what the worker's wiring has to keep, because feeding it per frame makes the panel stop
  answering uploads;
* the live frame loop obeys the session limits `xigmalcd.main` owns (it reads them, so there is no
  second copy to test): it keeps its rate, renews on a short clock without re-pushing the blob, stops
  on a channel that answers but refuses every file, and stops with a sentence when the port is gone at
  the moment of renewal.

Two things this file deliberately does not lean on.  The re-enumeration wait (`glob.glob
("/dev/ttyACM*")`, for up to 30 s) is pinned rather than real: this check used to pass on a bench by
finding the author's actual panel in that listing, and on a runner with no such node it waited out
the 30 s and returned False - a verdict about the desk, not about the code.  And the readings are
pinned: unpinned, the first CI runner drew its frames with no temperatures to read and produced a
7,398 B OSD PNG where this bench draws about 12.1 kB, which is not a regression, it is a different
picture.  What the host genuinely has is never asserted.
"""
from __future__ import annotations

import copy
import inspect
import os
import time
import types
import unittest

from tests import fixtures

from xigmalcd import render
from xigmaui import panel

STUB_PORT = "/dev/xigma-stub"
MISSING_PORT = "/dev/xigma-no-such-port"

#: The readings the drawing checks pin, so the byte band below compares like with like on a bench
#: with a Super-IO and a runner with no fan header at all.
FIX = {"cpu": {"temperature": 57.0, "load": 42.0},
       "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
       "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 2400}]}


class StubLink:
    """The serial layer, replaced.  Records everything and speaks to nothing."""

    notice = "200"

    def __init__(self, port, timeout=3.0, allow_destructive=False, **kwargs):
        self.opened_as = (port, allow_destructive)
        self.uploads, self.posts, self.states = [], [], []
        StubLink.instances.append(self)

    instances: list = []
    opens: list = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def start_pump(self):
        pass

    def drain(self, timeout=0.15):
        pass

    def hello(self, keepalive=60):
        return self.device_info()

    def device_info(self):
        return {"sn": "STUB", "version": {"app": "V1.0.2"}, "space": 62428}

    def harvest(self, timeout=0.0):
        return []

    def post(self, verb, obj=None):
        self.posts.append(verb)
        return 1

    def state_all(self, metrics, wait=False):
        # where in the session the blob landed (0 = before the first file), and whether the host
        # sent its tach readings or left them out
        self.states.append((len(self.uploads), metrics.get("fans") is not None))
        return None

    def send_media(self, name, data, **kwargs):
        if not StubLink.notice.startswith("2"):
            from xigmalcd.protocol import ProtocolError
            raise ProtocolError(f"stub answered {StubLink.notice}")
        rec = (name, len(data), kwargs.get("gap", 0.02))
        self.uploads.append(rec)
        StubLink.all_uploads.append(rec)
        return {"notice": StubLink.notice, "state": "success", "seq": 7}

    all_uploads: list = []


class NodesBack:
    """`panel.py`'s `glob`, standing in for the re-enumeration a real device does."""

    asked: list = []

    @staticmethod
    def glob(pattern):
        NodesBack.asked.append(pattern)
        return ["/dev/xigma-stub"]


class WiringSafety(unittest.TestCase):
    def test_exactly_one_place_asks_for_a_destructive_link(self):
        source = inspect.getsource(panel.Panel)
        self.assertEqual(source.count("destructive=True"), 1,
                         "a second destructive call site would put a factory reset on the wire "
                         "from somewhere nobody looked")
        self.assertIn("allow_destructive=destructive", inspect.getsource(panel.Panel._open))

    def test_reset_without_the_typed_word_sends_nothing(self):
        StubLink.instances = []
        worker = panel.Panel(MISSING_PORT)
        captured = []
        worker.log.connect(captured.append)
        self.assertFalse(worker._reset(confirm=""))
        self.assertIn("nothing sent", " ".join(captured), captured)
        self.assertEqual(StubLink.instances, [], "the gate opened a link before it asked")


class StubbedActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real = (panel.Link, panel.sensors, panel.glob, panel.port_busy)
        StubLink.instances, StubLink.all_uploads, StubLink.notice = [], [], "200"
        panel.Link = StubLink
        panel.sensors = types.SimpleNamespace(collect=lambda: copy.deepcopy(FIX))
        panel.port_busy = lambda port: ""
        # the re-enumeration wait is pinned for one test and put back after it, never left patched:
        # a worker that cannot see its own device node is a worker no later test can read
        cls.real_glob = panel.glob

    @classmethod
    def tearDownClass(cls):
        panel.Link, panel.sensors, panel.glob, panel.port_busy = cls.real

    def setUp(self):
        StubLink.instances, StubLink.all_uploads = [], []
        self.notes = []
        self.worker = panel.Panel(STUB_PORT)
        self.worker.log.connect(self.notes.append)

    def clip(self, name="Theme_25.mp4") -> str:
        return os.path.join(fixtures.REPO, "media", name)

    def test_the_background_goes_up_as_one_file_at_the_measured_gap_with_the_blob_first(self):
        path = self.clip()
        with open(path, "rb") as fh:
            blob = fh.read()
        self.assertTrue(self.worker._upload(path=path, gap=0.02, chunk=1000))
        last = StubLink.all_uploads[-1]
        self.assertEqual(last[0], "Theme_25.mp4")
        self.assertEqual(last[1], len(blob), "the whole file went, not a piece of it")
        self.assertEqual(last[2], 0.02, "the measured pre-byte pause is what the loop uses")
        self.assertEqual(StubLink.instances[-1].states, [(0, True), (0, True)],
                         "PROTOCOL.md §8: the metrics blob lands twice at the head of a "
                         "session and never between files")

    def test_a_4xx_notice_is_reported_as_a_refusal_not_a_success(self):
        StubLink.notice = "400"
        try:
            self.assertFalse(self.worker._upload(path=self.clip(), gap=0.02, chunk=1000))
        finally:
            StubLink.notice = "200"
        self.assertIn("refused this background", " ".join(self.notes), self.notes[-3:])

    def test_one_frame_stays_in_its_size_band_and_fans_false_drops_the_tach_array(self):
        self.assertTrue(self.worker._frame(theme="alpha", kw={"bg": render.OVERLAY}, fans=False))
        name, size = StubLink.all_uploads[-1][0], StubLink.all_uploads[-1][1]
        self.assertTrue(name.endswith(".osd"), name)
        # a regression net, not a tracker of PNG trivia: a re-encoded frame, a wrong scale or a
        # canvas that stopped being transparent all move this by more than the band allows
        self.assertGreater(size, 10_000, StubLink.all_uploads[-1])
        self.assertLess(size, 20_000, StubLink.all_uploads[-1])
        self.assertEqual(StubLink.instances[-1].states, [(0, False), (0, False)],
                         "`fans=False` takes the tach array out of the blob as well as off the "
                         "picture, and the blob still lands before the file")

    def test_the_live_run_keeps_its_rate_and_pushes_the_blob_only_at_the_session_head(self):
        """One second at 5 fps is five frames; the band allows the stub answering instantly and
        the loop waking a few ms late, but not the rate being wrong by a factor of two."""
        from xigmalcd import main as daemon
        self.assertTrue(self.worker._live(theme="alpha", kw={"bg": render.OVERLAY},
                                          fps=5.0, seconds=1.0))
        made = StubLink.all_uploads
        self.assertTrue(4 <= len(made) <= 6, made[-8:])
        self.assertEqual(len(StubLink.instances), 1,
                         "a 1 s run at the real session limits should not have reopened")
        self.assertEqual(StubLink.instances[0].states, [(0, True), (0, True)],
                         "the blob belongs at the head of the session, once")

    def test_a_short_session_clock_reopens_and_none_of_the_reopens_re_push_metrics(self):
        """`_live` reads the limits out of `xigmalcd.main`, so patching that is patching the
        worker - there is no second copy of the number to test.  PROTOCOL.md §8's evidence covers
        one session head, not every reopen, and `main.rehandshake` only re-helloes."""
        from xigmalcd import main as daemon
        saved = (daemon.SESSION_TTL, daemon.SESSION_MAX)
        daemon.SESSION_TTL, daemon.SESSION_MAX = 0.2, 0
        try:
            self.assertTrue(self.worker._live(theme="alpha", kw={"bg": render.OVERLAY},
                                              fps=5.0, seconds=1.0))
        finally:
            daemon.SESSION_TTL, daemon.SESSION_MAX = saved
        # 1 s at a 0.2 s clock is five chances to renew; the bound is this file's own (3),
        # because this process is not the only thing on the machine and a loaded bench loses a
        # couple of them to a frame that ran long
        self.assertGreaterEqual(len(StubLink.instances), 3,
                                f"{len(StubLink.instances)} opens in 1 s at a 0.2 s clock")
        for link in StubLink.instances[1:]:
            self.assertEqual(link.states, [],
                             "a renewed session pushed the metrics blob again")
            self.assertFalse(link.opened_as[1], "a renewal asked for a destructive link")

    def test_a_panel_that_answers_but_refuses_every_file_ends_the_run_rather_than_using_its_window(self):
        """PROTOCOL.md §6: reopening does not cure a refusal, so the run stops.  Spending the
        whole window on a dead channel is the failure this guards against."""
        StubLink.notice = "400"
        started = time.monotonic()
        try:
            self.assertFalse(self.worker._live(theme="alpha", kw={"bg": render.OVERLAY},
                                               fps=5.0, seconds=4.0))
        finally:
            StubLink.notice = "200"
        spent = time.monotonic() - started
        self.assertLess(spent, 2.0, f"{spent:.2f} s: the run used its whole 4 s window")
        self.assertLessEqual(len(StubLink.instances), 7,
                            f"{len(StubLink.instances)} reopens: one per RECOVER_AFTER at most")
        self.assertTrue(any("in a row refused" in line for line in self.notes), self.notes[-4:])
        for link in StubLink.instances:
            self.assertEqual(link.uploads, [],
                             "a refused channel still accepted something in this stub")

    def test_a_port_that_goes_away_at_the_renewal_stops_the_run_and_says_so(self):
        """Nothing raises out of the worker, and the `finally` close tolerates a link that
        never opened."""
        from xigmalcd import main as daemon
        seen = {"n": 0}

        def busy_after_first(port: str) -> str:
            seen["n"] += 1
            return f"{port} is held by pid 999 (stub)" if seen["n"] > 1 else ""

        panel.port_busy = busy_after_first
        saved = (daemon.SESSION_TTL, daemon.SESSION_MAX)
        daemon.SESSION_TTL, daemon.SESSION_MAX = 0.2, 0
        try:
            self.assertFalse(self.worker._live(theme="alpha", kw={"bg": render.OVERLAY},
                                               fps=5.0, seconds=2.0))
        finally:
            panel.port_busy = lambda port: ""
            daemon.SESSION_TTL, daemon.SESSION_MAX = saved
        self.assertEqual(len(StubLink.instances), 1,
                         f"{len(StubLink.instances)} links: the run should stop at the first "
                         "renewal that cannot reopen, not try again")
        self.assertTrue(any("port went away at the renewal" in line for line in self.notes),
                        self.notes[-3:])

    def test_asking_for_status_sends_no_metrics_blob(self):
        self.assertTrue(self.worker._status())
        self.assertEqual(StubLink.instances[-1].states, [],
                         "a status read pushed a state frame at the panel")

    def test_reset_opens_exactly_one_destructive_link_and_waits_for_a_pinned_listing(self):
        panel.glob = NodesBack
        NodesBack.asked = []
        try:
            self.assertTrue(self.worker._reset(confirm="reset"))
        finally:
            panel.glob = self.real_glob
        opens = [link.opened_as for link in StubLink.instances]
        destructive = [d for _port, d in opens]
        self.assertEqual(sum(1 for d in destructive if d), 1, opens)
        self.assertGreaterEqual(len(opens), 2,
                                f"a reset re-enumerates and then re-reads status, so it should "
                                f"open more than the one destructive link: {opens}")
        self.assertFalse(opens[-1][1], "the re-read after a reset opened destructively")
        self.assertEqual(NodesBack.asked[:1], ["/dev/ttyACM*"], NodesBack.asked)


if __name__ == "__main__":
    unittest.main(verbosity=2)
