#!/usr/bin/env python3
"""The CI file's own shape, read without a YAML dependency.

Four facts worth holding, all of them learned from a run rather than from taste:

* **Every job declares a timeout.**  GitHub's default is six hours, and a job that cannot
  reach the network - an apt mirror, a pip index, an action download - otherwise sits there
  for six hours before it says so.  A job without `timeout-minutes` is a hole in that rule,
  and it is invisible from the file's own prose.
* **The checks job's budget is stated against a measurement.**  It was 30 minutes, described
  as "four times what the job takes" - and CI #202 attempt 1 came in at exactly 1816 s of
  job, with its `tests/` step alone at **1762 s** against the 406, 406, 412 and 415 s the same
  work took in its neighbours.  A loaded runner ran ~4.2x slow, the suite was cancelled near
  the end with one GUI check failing under the load, and the same commit re-ran green in
  414.2 s.  So the margin was one bad machine, and the number went to 45 minutes with those
  measurements in the comment above it - and to 60 when the v0.8 tag's own checks job ran
  **2112 s**, inside the cap at 78% of it, with `build`, `install + smoke` and `publish`
  all waiting behind it.  A cancelled checks job on a branch costs a re-run; on a tag it
  costs a release, and that is the difference the wider wall is paying for.
* **The comment carries the figures.**  A budget raised without the reason next to it is a
  number someone will "tidy" back down in a month.
* **The release body counts, it does not remember.**  Its "what this release draws" section
  reads `xigmalcd/render.py` and `pyproject.toml` with `ast` and interpolates the counts,
  because on 2026-11-14 this repository had eleven sentences saying "five" about a set of
  six - one of them inside a check - and a release information page is the worst place in the
  tree to carry a stale number: it is where a reader decides whether to upgrade.

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
#: 45 minutes held until the v0.8 tag's checks job ran 2112 s - inside the cap, at 78% of
#: it, with the release hanging off the end of that job - and the file now carries 60 with
#: that number next to it.  The ceiling in the check below is still 60: the point of a
#: timeout is to make a stuck job visible, not to make a slow one comfortable.
MIN_BUDGET = 45
REQUIRED_FIGURES = ("1762", "414.2", "1816", "2112")


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
                             "and becomes permission to hang - 60 is the ceiling this project "
                             "holds itself to, with 2112 s as the slowest checks job observed "
                             "on one day (378 / 473 / 2112 s for the same count)")

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

    def test_the_release_body_counts_rather_than_remembers(self):
        """The published notes derive their numbers from the tree they describe.

        `v0.7` is published with a body generated by this workflow, and the sentence that
        would have gone stale in it is the one a reader acts on - how many themes the release
        draws, how many backgrounds it installs, which version parity holds. The same day this
        project found eleven hardcoded "five"s in its own source, two of them in strings a
        user reads and one inside a check that *pinned* the wrong word
        (`tests/test_theme_library.py::TheDrawnSetCountsItself` now refuses that shape). So
        the release step parses the tree with `ast` - no Pillow import, no dependency the
        runner may not have - and interpolates.

        Four things are asserted: the counts are f-strings over parsed values, no literal
        count of themes or backgrounds appears anywhere in the job, the version comes from
        `xigmalcd/__init__.py` rather than from the tag name alone, and the step sits before
        `gh release create` so what it writes is what gets published.
        """
        body = dict(self.jobs)["release"]
        self.assertIn("ast.parse", body,
                      "the release job no longer reads its own source: the counts in a "
                      "published body have to come from the tree the tag points at")
        for derived in ("{len(themes)}", "{len(clips)}", "{version}"):
            self.assertIn(derived, body,
                          f"`{derived}` is gone, so a number in the release body is typed "
                          "again - and a typed number is the drift this step exists to stop")
        remembered = (re.findall(r"\*\*\s*[a-z0-9]+\s+themes drawn", body)
                      + re.findall(r"\*\*\s*[a-z0-9]+\s+backgrounds installed", body))
        self.assertEqual(remembered, [],
                         f"{remembered}: a hardcoded count of themes or backgrounds in the "
                         "publishing job")
        self.assertIn('assigns("xigmalcd/__init__.py", "__version__")', body,
                      "version parity in the notes must be read from the module, not "
                      "assumed from the tag - the four-door parity rule is what "
                      "tests/test_packaging.py holds, and the release page should agree")
        lines = [l.strip() for l in body.split("\n")]
        drawn = next((k for k, l in enumerate(lines)
                      if l.startswith("- name: what this tag draws")), None)
        create = next((k for k, l in enumerate(lines)
                       if l.startswith("- name: gh release create")), None)
        self.assertIsNotNone(drawn, "the counting step is missing from the release job")
        self.assertIsNotNone(create, "`gh release create` is missing")
        self.assertLess(drawn, create,
                        "the counts must be appended to the notes **before** the release is "
                        "created, or the published body is the one without them")
        print(f"  release body: {len(themes_hint(body))} derived figures wired into the "
              "published notes (counted, not typed)")


def themes_hint(body: str) -> list:
    """The interpolation sites in the release job, for the printed count above."""
    return re.findall(r"\{[a-z_]+\(", body) + re.findall(r"\{version\}", body)


if __name__ == "__main__":
    unittest.main()
