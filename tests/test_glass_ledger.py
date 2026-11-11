#!/usr/bin/env python3
"""The glass ledger: the driver that makes the transcripts, and the tie between a log and a page.

Ported from the parts of `tools/selftest.sh`'s glass-ledger section that did not re-quote a figure.
The rest of that section re-derived counters, spans, CPU-seconds and `**X of Y**` sums out of
`data/glass/*.txt` and compared them to sentences in README and `docs/`.  Those sentences are gone,
and so are the comparisons - the numbers belong to a bench run against one panel, and the tool that
prints them (`tools/display_glass.py`, `tools/log_timeline.py`) is named where the figure would have
been written.

What stays is the two cheap things that were never about numbers:

* **the driver must run what it lists.**  It once did not: a phase labelled "the command-line client"
  shared the plain status body, so the subprocess that runs `xigmalcd --status` was never called and
  three kept logs had no such line in them.  A phase's *kind* is what picks its body, so the two
  tables have to agree in both directions.
* **a run stopped in the middle has to say so.**  `^C` during the renewal wait used to fall through
  to the summary and print "every phase checked out" about a session that had never renewed.

`data/` is gitignored - the transcripts carry this panel's serial number - so a clone has no logs and
the second check skips out loud rather than reporting a pass.
"""
from __future__ import annotations

import ast
import glob
import os
import unittest

from tests import fixtures

DRIVER = os.path.join("tools", "display_glass.py")


class DriverMatchesItsOwnList(unittest.TestCase):
    """Every phase the driver announces has a body, and every body is reached."""

    @classmethod
    def setUpClass(cls):
        cls.src = fixtures.read(DRIVER)
        cls.tree = ast.parse(cls.src)
        cls.phases = cls.bodies = None
        for node in ast.walk(cls.tree):
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id == "PHASES":
                    cls.phases = ast.literal_eval(node.value)
                elif node.targets[0].id == "bodies":
                    cls.bodies = {k.value for k in node.value.keys}

    def test_the_two_tables_agree_in_both_directions(self):
        self.assertIsNotNone(self.phases, "PHASES not found in the driver")
        self.assertIsNotNone(self.bodies, "bodies not found in the driver")
        kinds = [p[0] for p in self.phases]
        self.assertLessEqual(set(kinds), self.bodies,
                             sorted(set(kinds) - self.bodies) and "a phase with no body")
        self.assertLessEqual(self.bodies, set(kinds),
                             f"{sorted(self.bodies - set(kinds))}: a body no phase reaches")

    def test_the_cli_client_is_one_of_the_bodies(self):
        self.assertIn("cli", self.bodies,
                      "the separate `--status` client is not part of any phase, which is how "
                      "three kept logs ended up with no such line")

    def test_no_two_phases_are_labelled_alike(self):
        labels = {p[:2] for p in self.phases}
        self.assertEqual(len(labels), len(self.phases), "two phases labelled alike")

    def test_a_run_cut_short_records_that_it_was_cut_short(self):
        handlers = [n for n in ast.walk(self.tree)
                    if isinstance(n, ast.ExceptHandler)
                    and getattr(n.type, "id", None) == "KeyboardInterrupt"]
        self.assertTrue(handlers, "no KeyboardInterrupt handler to check")
        body = ast.get_source_segment(self.src, handlers[0]) or ""
        self.assertIn("problems.append", body,
                      "a stopped run adds no problem, so it can still claim every phase ran")
        self.assertIn("running[0]", body, "the stopped run does not say which phase it lost")


class LedgerIsNamed(unittest.TestCase):
    """Each kept transcript is pointed at by a page, or it is not evidence for anything."""

    def logs(self) -> list:
        return sorted(os.path.basename(p)
                      for p in glob.glob(os.path.join(fixtures.REPO, "data", "glass", "*.txt")))

    def pages(self) -> str:
        names = ["README.md"] + [f for f in fixtures.tracked("docs/*.md")]
        return "\n".join(fixtures.read(n) for n in names)

    def test_every_kept_transcript_is_named_somewhere_a_reader_would_look(self):
        logs = self.logs()
        if not logs:
            self.skipTest("no transcripts under data/glass/ (gitignored: they carry this "
                          "panel's serial), so there is no ledger to point at")
        text = self.pages()
        missing = [name for name in logs if name not in text]
        self.assertEqual(missing, [],
                         f"{len(missing)} of {len(logs)} kept logs are named nowhere in README "
                         f"or docs/: {missing[:5]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
