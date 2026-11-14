#!/usr/bin/env python3
"""The CI file's own shape, read without a YAML dependency.

Three facts worth holding, all of them learned from a run rather than from taste:

* **Every job declares a timeout.**  GitHub's default is six hours, and a job that cannot
  reach the network - an apt mirror, a pip index, an action download - otherwise sits there
  for six hours before it says so.  A job without `timeout-minutes` is a hole in that rule,
  and it is invisible from the file's own prose.
* **The checks job's budget is stated against a measurement.**  It was 30 minutes, described
  as "four times what the job takes" - and CI #202 attempt 1 came in at exactly 1816 s of
  job, with its `tests/` step alone at **1762 s** against the 406, 406, 412 and 415 s the same
  work took in its neighbours.  A loaded runner ran ~4.2x slow, the suite was cancelled near
  the end with one GUI check failing under the load, and the same commit re-ran green in
  414.2 s.  So the margin was one bad machine, and the number is now 45 minutes with those
  measurements in the comment above it.
* **The comment carries the figures.**  A budget raised without the reason next to it is a
  number someone will "tidy" back down in a month.

Parsed by indentation rather than with `yaml`, because `pyyaml` is not a declared dependency
of this project and a gate that needs an uninstalled import is a gate that errors.
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")

#: The checks job's budget, as the file declares it, and the figures the comment has to carry.
MIN_BUDGET = 45
REQUIRED_FIGURES = ("1762", "414.2", "1816")


def jobs(text: str) -> list:
    """(name, body) for every job under the top-level `jobs:` key."""
    lines = text.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.rstrip() == "jobs:")
    except StopIteration:
        raise AssertionError("no `jobs:` key in the workflow - the file is not what this "
                             "check thinks it is")
    out, name, body = [], None, []
    for line in lines[start + 1:]:
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            if name:
                out.append((name, "\n".join(body)))
            name, body = m.group(1), []
        elif name is not None:
            body.append(line)
    if name:
        out.append((name, "\n".join(body)))
    return out


class WorkflowShape(unittest.TestCase):
    def setUp(self):
        with open(WORKFLOW, encoding="utf-8") as fh:
            self.text = fh.read()
        self.jobs = jobs(self.text)

    def test_the_file_has_the_jobs_this_check_is_about(self):
        names = sorted(n for n, _b in self.jobs)
        self.assertEqual(names, ["checks", "deb", "install", "release"],
                         f"the workflow's jobs are {names}: a job added or renamed has to be "
                         "looked at by the timeout rule below, not skipped past it")

    def test_every_job_declares_a_timeout(self):
        missing = [n for n, body in self.jobs if "timeout-minutes:" not in body]
        self.assertEqual(missing, [],
                         f"{missing}: job(s) with no `timeout-minutes`, which leaves GitHub's "
                         "six-hour default in place - and a job that cannot reach the network "
                         "then holds a runner for six hours before saying so")

    def test_the_checks_budget_covers_the_slowest_run_observed(self):
        body = dict(self.jobs)["checks"]
        declared = int(re.search(r"timeout-minutes:\s*(\d+)", body).group(1))
        self.assertGreaterEqual(declared, MIN_BUDGET,
                                f"the checks job is capped at {declared} minutes; the slowest "
                                "observed attempt took 1816 s of job and was cancelled at the "
                                "30-minute mark, so a lower number is a bet on every runner "
                                "being fast")
        self.assertLessEqual(declared, 60,
                             "a budget this far above the observed worst stops being a guard "
                             "and becomes permission to hang")

    def test_the_comment_next_to_the_budget_carries_the_figures(self):
        """The number without the measurement beside it gets 'tidied' back down."""
        # the lines just above the checks job's `timeout-minutes:` - that is where the
        # reasoning lives, and the rule of this file is that the figures stay there
        lines = self.text.split("\n")
        i = next(k for k, l in enumerate(lines)
                 if l.startswith("    timeout-minutes:") and k > lines.index("jobs:"))
        context = "\n".join(lines[max(0, i - 16):i])
        absent = [f for f in REQUIRED_FIGURES if f not in context]
        self.assertEqual(absent, [],
                         f"the reasoning behind the checks job's timeout has lost {absent}: the "
                         "budget is 45 minutes because CI #202 attempt 1 ran a 1762 s step and "
                         "a 1816 s job against 414.2 s on the same commit, and those numbers are "
                         "why - dropping them leaves a bare figure to argue with")


if __name__ == "__main__":
    unittest.main()
