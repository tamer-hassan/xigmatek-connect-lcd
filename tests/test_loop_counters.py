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
import time
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
    #: The run's wall-clock budget, measured rather than fixed.  CI #204 is why.
    BUDGET = 3.0

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="xigma-loop-")
        cls.sock = os.path.join(cls.tmp.name, "loop.sock")
        cls.real_link, cls.real_stdout, cls.real_stderr = daemon.Link, sys.stdout, sys.stderr
        StubLink.calls, StubLink.seen, StubLink.sock = 0, [], cls.sock
        # How long does one frame cost **here**?  That is the only honest way to size the run:
        # the loop paces to `--fps` but never sleeps past a frame it cannot draw, so the number
        # of uploads it makes in a fixed `--duration` is a property of the machine, not of the
        # code.  Measured on the bench this file was written on, three seconds buys twenty-odd
        # frames; on the contended GitHub runner of CI #204 (a 1872.756 s step where its
        # neighbours take ~420 s) the same three seconds bought **three** files, no fourth file
        # ever arrived, and every assertion below about refusals failed because the case under
        # test had not happened.  A budget that is timed by a clock and asserted by a count is a
        # bet on the scheduler - the same fault fixed in `tests/test_window_sizing.py` an hour
        # earlier, in a different file.  So the budget is calibrated from one real frame here,
        # with the measurement printed rather than assumed.
        one = cls.time_one_frame()
        frames_wanted = 2 * EVERY + 4        # two refusals, plus slack for the loop's own ramp
        cls.BUDGET = min(40.0, max(3.0, one * frames_wanted * 2.0))
        print(f"  loop budget: one `alpha` frame costs {one:.3f} s here, so the stub run gets "
              f"{cls.BUDGET:.2f} s - enough for at least {frames_wanted} frames at that rate")
        daemon.Link = StubLink
        out, err = io.StringIO(), io.StringIO()
        sys.stdout, sys.stderr = out, err
        try:
            cls.rc = daemon.main(["--device", "/dev/xigma-stub", "--socket", cls.sock,
                                  "--fps", "20", "--duration", f"{cls.BUDGET:g}",
                                  "--no-state", "--no-mp4", "--theme", "alpha"])
        finally:
            sys.stdout, sys.stderr = cls.real_stdout, cls.real_stderr
        cls.log, cls.report = err.getvalue(), out.getvalue()

    @classmethod
    def time_one_frame(cls) -> float:
        """Draw one frame through the door the loop uses, and report what it took."""
        from xigmalcd import render, sensors
        body = sensors.collect()
        start = time.monotonic()
        render.draw(dict(body, timestamp={}), "alpha")
        return max(0.001, time.monotonic() - start)

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
        self.assertGreaterEqual(raises, 2, f"only {StubLink.calls} files went up in a "
                                           f"{self.BUDGET:.2f} s run (every {EVERY}th refused), "
                                           "so the case under test did not happen even though "
                                           "the budget was measured from a timed frame here - "
                                           "the machine is slower than the calibration frame "
                                           "suggests, or the loop stopped early: "
                                           + self.log[-200:])
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
