#!/usr/bin/env python3
"""The bare-runner audit's own boundary: what it walks, and what the walk has to find.

`tools/audit_bare_runner.py` re-runs every test module that names a **live** sensor door with
`sensors.HWMON_GLOB` pointed at a pattern matching no directory - a machine with no
hardware-monitoring chips at all.  A bare machine is a fact no CI runner is obliged to have, and
this session produced six checks that quietly assumed one:

    #190  510 checks, one failure   `55 != 42`                       host mount table names `nvme0`
    #191  511 checks, one error     `KeyError: 'temperature'`        `disk` implies `temperature`
    (bench) two live reads compared                `38 != 39`        the drive warmed between them
    (bench, an hour later, same fault in new code) `[44, 58, 68]` != `[44, 59, 68]`
    #193  526 checks, OK            431.661 s  \
                                               |  the SAME check, the same 526 checks,
    #194  526 checks, one failure   460.878 s  /   and eight lines of changelog prose apart

#193 and #194 are the reason the tool exists: the assertion that a drive list was non-empty
passed on one runner image and failed on the next, so both outcomes were luck.

What is gated here is the tool's two promises.  Its module list is **derived** from each test
file's AST, so the only hand-kept part is the subprocess case the AST cannot see - which means
completeness cannot rot, and the check that matters is that the finder still *finds*: one test
writes a file that calls `sensors.disk()` and a file that merely mentions it in prose, and asks
the scan which of the two it saw.  A grep-based list would have passed that on the prose file.
"""
from __future__ import annotations

import glob
import importlib
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

audit = importlib.import_module("audit_bare_runner")

#: The modules whose live reading is known and named here on purpose: if one of them stops
#: reading live sensors the pin fails and says so, because a module dropping out of the audit is
#: a module nobody will audit again.
KNOWN_LIVE = ("tests.test_apply_layout", "tests.test_blob_probe", "tests.test_peek_readings",
              "tests.test_sensor_rules", "tests.test_theme_files")


class TheFinder(unittest.TestCase):
    """The scanner is the list, so the scanner is what has to be right."""

    def test_it_notices_a_module_that_calls_a_live_door(self):
        tmp = tempfile.TemporaryDirectory(prefix="xigma-audit-")
        try:
            os.makedirs(os.path.join(tmp.name, "tests"))
            with open(os.path.join(tmp.name, "tests", "test_reads_disk.py"), "w",
                      encoding="utf-8") as fh:
                fh.write("from xigmalcd import sensors\n"
                         "def probe():\n"
                         "    return sensors.disk()\n")
            found = audit.live_test_modules(tmp.name)
            self.assertEqual(found, ("tests.test_reads_disk",),
                             "a module calling `sensors.disk()` was not picked up, so the audit "
                             "silently stopped covering things")
        finally:
            tmp.cleanup()

    def test_it_ignores_a_module_that_only_talks_about_a_door(self):
        """The prose case, which is what a grep would get wrong.

        `tools/audit_bare_runner.py` itself and half the test modules quote
        `sensors.collect()` inside their own explanations; matching that would pad the list with
        modules that never read anything, and a padded list teaches a reader to distrust it.
        """
        tmp = tempfile.TemporaryDirectory(prefix="xigma-audit-")
        try:
            os.makedirs(os.path.join(tmp.name, "tests"))
            with open(os.path.join(tmp.name, "tests", "test_only_says_it.py"), "w",
                      encoding="utf-8") as fh:
                fh.write('"""This file mentions `sensors.collect()` in prose and never calls '
                         'it."""\nimport unittest\n\n\nclass T(unittest.TestCase):\n'
                         '    def test_nothing(self):\n        self.assertTrue(True)\n')
            found = audit.live_test_modules(tmp.name)
            self.assertEqual(found, (),
                             f"prose counted as a live reader: {found}")
        finally:
            tmp.cleanup()

    def test_a_stub_assignment_still_counts_as_live_reading(self):
        """`sensors.collect = lambda: body` admits the module would read the machine."""
        tmp = tempfile.TemporaryDirectory(prefix="xigma-audit-")
        try:
            os.makedirs(os.path.join(tmp.name, "tests"))
            with open(os.path.join(tmp.name, "tests", "test_stubs.py"), "w",
                      encoding="utf-8") as fh:
                fh.write("from xigmalcd import sensors\nsensors.collect = lambda: {}\n")
            self.assertEqual(audit.live_test_modules(tmp.name), ("tests.test_stubs",),
                             "a module that stubs a door was dropped from the audit")
        finally:
            tmp.cleanup()


class TheList(unittest.TestCase):
    def test_the_known_live_readers_are_all_walked(self):
        walked = set(audit.modules())
        missing = sorted(set(KNOWN_LIVE) - walked)
        self.assertEqual(missing, [], f"the audit stopped walking {missing}")

    def test_every_walked_module_is_a_real_file(self):
        for name in audit.modules():
            path = os.path.join(ROOT, *name.split(".")) + ".py"
            self.assertTrue(os.path.exists(path), f"{name} is listed but {path} is not a file")

    def test_the_hand_kept_part_is_only_what_the_ast_cannot_see(self):
        """Every `EXTRA_MODULES` entry must be invisible to the derivation.

        If the finder already picks a module up, listing it by hand is a second copy of a rule -
        the kind that goes stale the day the module stops reading live sensors, leaving the audit
        claiming coverage it no longer has.
        """
        derived = set(audit.live_test_modules())
        overlap = sorted(set(audit.EXTRA_MODULES) & derived)
        self.assertEqual(overlap, [],
                         f"EXTRA_MODULES duplicates derived entries: {overlap}")

    def test_modules_and_walked_are_sorted_and_deduplicated(self):
        m = audit.modules()
        self.assertEqual(list(m), sorted(m), "sorted, so a diff shows an addition not a shuffle")
        self.assertEqual(len(set(m)), len(m))


class TheSubstitution(unittest.TestCase):
    def test_the_glob_matches_no_directory(self):
        self.assertTrue(os.path.isabs(audit.EMPTY_GLOB), audit.EMPTY_GLOB)
        self.assertEqual(glob.glob(audit.EMPTY_GLOB), [],
                         "EMPTY_GLOB matches real directories, so the 'bare machine' is not bare")

    def test_the_substitution_leaves_the_real_walk_intact(self):
        """The tool restores the module's glob on the way out, in a `finally`.

        Worth its own check: the audit patches a module-level constant in its own process, and a
        leaked patch would silently make every later test in that process read nothing - which
        would look like a passing suite on a machine that has sensors.
        """
        import inspect
        src = inspect.getsource(audit.main)
        self.assertIn("sensors.HWMON_GLOB = real", src,
                      "the audit no longer restores the walk it replaced")
        self.assertIn("finally:", src, "the restore is not in a finally block")

    def test_running_the_tool_on_one_module_proves_the_path_works(self):
        """End to end, cheaply: the substitution, the run, and the summary the tool prints."""
        got = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "audit_bare_runner.py"),
                              "tests.test_blob_probe"],
                             capture_output=True, text=True, timeout=300, cwd=ROOT,
                             env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        out = (got.stdout or "") + (got.stderr or "")
        self.assertEqual(got.returncode, 0, out[-800:])
        self.assertIn("0 chips visible", out, out[:400])
        self.assertIn("0 failures, 0 errors", out, out[-400:])
        self.assertIn("motherboard() -> {}", out,
                      "with no hwmon chips the board door must answer nothing")
        self.assertIn("drives() -> []", out,
                      "a `drives` section appeared on a machine with no storage chips")


if __name__ == "__main__":
    unittest.main()
