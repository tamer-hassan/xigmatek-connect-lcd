#!/usr/bin/env python3
"""The promise every other file in this package makes: nothing here touches your session.

Named to run last, so the comparison below happens after every window, save, rename and revert in the
package has had its turn.

`tools/selftest.sh` baselined the sha256 of `~/.config/xigmaui/config.json` before its first section
and compared it again at the end, because in 0.4 a section really did write the author's settings.
The fix was never the guard - it is that every window here is built on a temporary `XDG_CONFIG_HOME`
(`tests/fixtures.py` does that at import, and `FreshConfigRoot` does it again per test).  The guard
stays because a guard that has nothing to catch is still the thing that says so, and because when it
fires the reader needs to know which of the two happened: a test wrote it, or a window is open on
this machine for other reasons.  The second case is real and happened on 2026-11-11 - the author's
own `python3 -m xigmaui`, started before the run, saving on its timer while every section had already
passed - so the message answers that question and still fails.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import unittest

from tests import fixtures


class RealSessionUntouched(unittest.TestCase):
    def test_the_process_ran_on_a_temporary_root_the_whole_time(self):
        root = os.environ.get("XDG_CONFIG_HOME", "")
        self.assertTrue(root, "XDG_CONFIG_HOME is unset, so a window would write the real one")
        self.assertTrue(root.startswith(fixtures.ISOLATED),
                        f"the config root moved out of the temporary tree: {root}")

    def test_nothing_wrote_the_settings_file_a_person_uses(self):
        self.assertEqual(fixtures.config_fingerprint(), fixtures.BASELINE_CONFIG,
                         "the real settings file changed under this run: "
                         + self.who_else())

    def test_nothing_created_one_where_there_was_none(self):
        if fixtures.BASELINE_CONFIG != "absent":
            self.skipTest("a settings file already existed, so the previous check covers it")
        self.assertFalse(os.path.exists(fixtures.REAL_CONFIG), self.who_else())

    @staticmethod
    def who_else() -> str:
        """The two answers a reader can act on.  Deliberately not a pass: a suite that wrote the
        real config is a bug, and a pass that depends on nobody using the machine is a pass worth
        repeating."""
        # The timestamp is the evidence; `ps` at this instant is only a hint.  Twice on
        # 2026-11-14 this guard fired correctly - the real settings file had changed under a run -
        # and its diagnosis was wrong the second time, blaming a test when the write came from a
        # window that had opened and closed between two `pgrep` checks.  A message that asks
        # "is a window alive right now?" cannot answer "what wrote this at 06:35:57?", so the
        # when-and-where-it-falls-in-the-run pair goes into the sentence instead.
        stamp, when, inside = "", "unknown", False
        try:
            stamp = os.path.getmtime(fixtures.REAL_CONFIG)
            when = time.strftime("%H:%M:%S", time.localtime(stamp))
            inside = stamp >= fixtures.RUN_STARTED
        except OSError:
            pass
        began = time.strftime("%H:%M:%S",
                                            time.localtime(fixtures.RUN_STARTED))
        evidence = (f"the file was last written at {when}, "
                    + ("**inside** this run, which began at " + began
                       if inside else "before this run began at " + began))
        try:
            seen = subprocess.run(["pgrep", "-af", "xigma[u]i"], capture_output=True, text=True)
        except OSError:
            return evidence
        live = seen.stdout.strip()
        if not live:
            return (f"{evidence}.  No `xigmaui` process is alive at the moment of this "
                    "comparison, which does not clear the tests either: a window opened and "
                    "closed during the run leaves nothing for `pgrep` to find.  Settle it by "
                    "re-running the modules that build a window or save a layout one at a time, "
                    "reading the fingerprint between each")
        return (f"a window was open on this machine during the run, and it saves on its own "
                f"timer ({evidence}):\n{live}\nclose it and re-run; if the check still fails, "
                "a test wrote it")

    def test_the_diagnosis_names_a_time_and_where_it_falls(self):
        """The failure message is itself code, and it has to be wrong in the open.

        This runs on a **passing** suite - the file is untouched, the check is not reporting a
        failure - because the thing under test is the sentence a reader would get, not the
        settings file.  A guard whose diagnosis misleads is worse than no guard: it sends someone
        to audit 570 checks when the culprit was a window they opened themselves.
        """
        if not os.path.exists(fixtures.REAL_CONFIG):
            self.skipTest("no settings file on this machine, so there is no timestamp to name")
        said = self.who_else()
        self.assertIn("last written at", said, said)
        self.assertTrue(re.search(r"\d\d:\d\d:\d\d", said), f"no clock time in: {said}")
        self.assertTrue("inside this run" in said or "before this run began" in said,
                        f"the message never says where the write falls: {said}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
