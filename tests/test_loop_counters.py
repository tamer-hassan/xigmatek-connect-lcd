#!/usr/bin/env python3
"""The loop's own counters: what a client reads matches what the log says.

Ported from `tools/selftest.sh`'s loop-counters section.  A panel that throws away every fourth file
is not a hypothetical: `! frame 78`, `98`, `105` and `116` in a kept glass transcript are that shape
- the refusal arrives as an exception out of `send_media`, not as a notice code - and that path once
left those refusals out of `refused`, so a client read "0 refused" beside a log with four refusals in
it.  Nothing on a bench produces that on purpose, so the stub does, spread so that neither the
recover-after rule nor the give-up rule fires.

`xigmalcd.protocol.Link` is **replaced** for the duration of the run, so the loop cannot open a port
even by accident, and the socket it builds is in a temporary directory.  The status snapshots are
taken from inside a frame, which is exactly how `xigmalcd --status` or the window would read them.
"""
from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import unittest

from tests import fixtures

from xigmalcd import control
from xigmalcd import main as daemon
from xigmalcd.protocol import ProtocolError

EVERY = 4            # every fourth file is thrown away, matching the kept transcript's shape


class StubLink:
    """A panel that answers everything and refuses every fourth upload."""

    def __init__(self, port, baud=115200, **kwargs):
        self.port, self.baud = port, baud

    def start_pump(self):
        pass

    def drain(self, timeout=0.15):
        pass

    def close(self):
        pass

    def hello(self, keepalive=60):
        return self.device_info()

    def device_info(self):
        return {"sn": "STUB", "version": {"app": "V1.0.2"}, "space": 61000}

    def harvest(self, timeout=0.0):
        return []

    def post(self, verb, obj=None):
        return 1

    def state_all(self, metrics, wait=False):
        return None

    def send_media(self, name, data, **kwargs):
        # the counter is the class's, not the instance's: the loop reopens its link, and a count
        # that restarts at each link would not match what the run reported
        StubLink.calls += 1
        if StubLink.calls % EVERY == 0:
            raise ProtocolError("device refused the file: 400 b''")
        # asked from inside the frame, so what is read is the snapshot the last completed frame
        # published - exactly what `--status` would print
        StubLink.seen.append(control.Client(StubLink.sock).status())
        return {"notice": "200"}

    calls = 0
    seen: list = []
    sock = ""


class LoopCounters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="xigma-loop-")
        cls.sock = os.path.join(cls.tmp.name, "loop.sock")
        cls.real_link, cls.real_stdout, cls.real_stderr = daemon.Link, sys.stdout, sys.stderr
        StubLink.calls, StubLink.seen, StubLink.sock = 0, [], cls.sock
        daemon.Link = StubLink
        out, err = io.StringIO(), io.StringIO()
        sys.stdout, sys.stderr = out, err
        try:
            cls.rc = daemon.main(["--device", "/dev/xigma-stub", "--socket", cls.sock,
                                  "--fps", "20", "--duration", "3", "--no-state", "--no-mp4",
                                  "--theme", "alpha"])
        finally:
            sys.stdout, sys.stderr = cls.real_stdout, cls.real_stderr
        cls.log, cls.report = err.getvalue(), out.getvalue()

    @classmethod
    def tearDownClass(cls):
        daemon.Link = cls.real_link
        cls.tmp.cleanup()

    def test_the_run_finished_cleanly_and_left_no_socket_behind(self):
        self.assertEqual(self.rc, 0, self.log[-400:])
        self.assertFalse(os.path.exists(self.sock),
                         "a finished run left a socket for a window to find")

    def test_the_printed_tally_and_the_log_agree_about_every_refusal(self):
        tail = [line for line in self.report.splitlines() if "frames confirmed" in line]
        self.assertTrue(tail, self.report[-400:])
        got, attempted = (int(x) for x in re.match(r"(\d+)/(\d+)", tail[-1]).groups())
        raises = StubLink.calls // EVERY
        self.assertGreaterEqual(raises, 2, f"only {StubLink.calls} files: the case under test "
                                          "did not happen")
        self.assertEqual(attempted - got, raises, f"{got}/{attempted} against {raises} raises")
        self.assertEqual(self.log.count("! frame"), raises, self.log[-400:])

    def test_refusals_spread_out_do_not_end_the_run(self):
        self.assertNotIn("stopped: the panel answered", self.log, self.log[-400:])

    def test_every_client_snapshot_says_refused_is_frames_minus_ok(self):
        self.assertGreater(StubLink.seen, [], "no status was ever read during the run")
        for snapshot in StubLink.seen:
            self.assertEqual(snapshot["refused"], snapshot["frames"] - snapshot["ok"], snapshot)
        self.assertTrue(any(s["refused"] for s in StubLink.seen),
                        "no client ever saw a refusal, so the counter is not covered here")

    def test_a_client_reading_mid_run_is_at_most_a_frame_or_two_behind(self):
        raises = StubLink.calls // EVERY
        last = StubLink.seen[-1]
        self.assertGreaterEqual(last["refused"], raises - 2,
                                f"the stub refused {raises} times and the last client read "
                                f"{last['refused']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
