#!/usr/bin/env python3
"""`debian/changelog`: the stamp that makes two builds agree, and the two shapes lintian checks.

Ported from `tools/selftest.sh`'s packaging block.  Both halves were found the slow way, and the
reason each one is here is the reason it is not a style preference:

**The stamp.**  `dpkg-buildpackage` takes `SOURCE_DATE_EPOCH` from the top changelog entry's
timestamp, and `dpkg-deb` rewrites every tar member's mtime to it.  Measured with a toy package,
both ways round: an epoch in the past gives members dated 2001-09-09 twice with the same bytes; an
epoch in the **future** leaves members at the build's wall clock, because `dpkg-deb` only pulls
mtimes *down*.  That is how the published v0.1 asset and the same tree built locally differed by 18
bytes - 5,218,596 B against 5,218,614 B, all 37 file md5s and every control field identical.

**The width and the shape.**  CI runs `lintian --fail-on error,warning`, and
`debian-changelog-line-too-long` is a *warning*: adding one word to a sentence took a line from 77
columns to 82 and failed the .deb job in both packages while the python suite stayed green.  And
dpkg's grammar for a changelog body allows three things - an indented line, a well-formed heading,
a trailer - so a body line at column 0 is read as a heading and fails as
`syntax-error-in-debian-changelog`, once per package that ships `changelog.gz`.  That one came from
a helper that wrapped continuation lines at four spaces and left the first line at none: the suite
was green on both machines, because reading the top stanza's stamp through `dpkg-parsechangelog`
never looks at body indentation.
"""
from __future__ import annotations

import os
import re
import time
import unittest

from tests import fixtures

CHANGELOG = os.path.join("debian", "changelog")

#: dpkg's heading: source name, version in parentheses, a distribution, `; urgency=<word>`.
HEAD = re.compile(r"^[a-z0-9][a-z0-9.+~/-]* \([^()]+\) [^;]+; urgency=\S+$")


class Stamp(unittest.TestCase):
    """A top entry dated in the past is the whole of what makes two builds agree on bytes."""

    def test_the_top_entry_is_not_dated_in_the_future(self):
        fixtures.need("dpkg-parsechangelog")
        got = fixtures.run("dpkg-parsechangelog", "-STimestamp")
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        when = int(got.stdout.strip())
        now = int(time.time())
        self.assertLessEqual(when, now,
                             f"the top entry is dated "
                             f"{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(when))}, which "
                             "is in the future: dpkg-deb only pulls mtimes down to "
                             "SOURCE_DATE_EPOCH, so a build now would date every archive member "
                             "at its own wall clock and two machines could not agree on bytes")


class Width(unittest.TestCase):
    """80 columns is the boundary this repository has evidence for: 80 passes (in both packages),
    82 is flagged, and 81 has never been tested - so the file keeps its existing budget rather than
    probing for a limit nobody has measured."""

    def lines(self) -> list:
        return fixtures.read(CHANGELOG).split("\n")

    def test_no_line_is_over_80_columns(self):
        wide = [(n + 1, len(line)) for n, line in enumerate(self.lines()) if len(line) > 80]
        worst = max(wide, key=lambda t: t[1]) if wide else None
        self.assertEqual(wide, [],
                         f"a debian/changelog line over 80 columns, widest at line "
                         f"{worst}: lintian's debian-changelog-line-too-long fires there and "
                         f"fails the .deb job")

    def test_the_budget_this_gate_enforces_is_still_measurable_off_the_file(self):
        """If the count of lines sitting *at* 80 collapses, the number above is no longer the
        reason for the number, and this test needs a new reason rather than a silent pass."""
        at_limit = sum(1 for line in self.lines() if len(line) == 80)
        self.assertGreaterEqual(at_limit, 10,
                                f"only {at_limit} lines sit at 80 columns; the claim that this "
                                "is the file's own measured budget no longer holds")


class Shape(unittest.TestCase):
    """The three shapes dpkg allows: indented body, well-formed heading, ` -- ` trailer."""

    def test_every_non_blank_line_is_one_of_the_three(self):
        off = [(n + 1, line[:60]) for n, line in enumerate(fixtures.read(CHANGELOG).split("\n"))
               if line.strip() and not line[:1].isspace()
               and not HEAD.match(line.rstrip()) and not line.startswith(" -- ")]
        self.assertEqual(off, [],
                         "a debian/changelog line that is neither indented body, well-formed "
                         "heading nor trailer: dpkg reads it as a heading, lintian fails the "
                         ".deb job on it, and nothing else here does")

    def test_the_file_has_the_headings_the_distributions_are_built_from(self):
        heads = [line for line in fixtures.read(CHANGELOG).split("\n") if HEAD.match(line.rstrip())]
        self.assertGreaterEqual(len(heads), 1, "no well-formed heading in the changelog at all")


if __name__ == "__main__":
    unittest.main(verbosity=2)
