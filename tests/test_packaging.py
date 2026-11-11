#!/usr/bin/env python3
"""The package as a person installs it: what is declared, what resolves, what is sent.

Ported from `tools/selftest.sh`'s packaging block.  Nothing here builds a `.deb` - the deb job in
CI does that and runs lintian over the result - but the three things a build cannot notice are
checked here, in second rather than minute:

* what the wheel is told to include, and where Qt is allowed to appear;
* that every console script names something callable;
* that the one entry point able to put a destructive frame on the wire refuses, by default, to
  send anything at all.

That last one is the load-bearing line in this file.  The whole suite's claim that it never opens
`/dev/ttyACM0` rests on `xigmalcd-reset`'s dry-run default, so it is re-run rather than trusted.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import os
import re
import tomllib
import unittest

from tests import fixtures

import xigmalcd

PYPROJECT = os.path.join(fixtures.REPO, "pyproject.toml")
CHANGELOG = os.path.join(fixtures.REPO, "debian", "changelog")

#: sha256 of https://www.gnu.org/licenses/gpl-3.0.txt as fetched on 2026-11-07.  Pinned, so a
#: LICENSE that was quietly replaced - reworded, switched to GPL-2, truncated - is a failure
#: rather than a diff somebody reads carefully.
GPL3_SHA256 = "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986"


class Declared(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PYPROJECT, "rb") as fh:
            cls.cfg = tomllib.load(fh)

    def test_both_importable_packages_are_declared(self):
        pk = self.cfg["tool"]["setuptools"]["packages"]
        self.assertIn("xigmalcd", pk)
        self.assertIn("xigmaui", pk)

    def test_qt_belongs_only_in_the_gui_extra(self):
        """The display loop runs without Qt; the window does not, and the dependency split says so."""
        self.assertTrue(any("PyQt6" in d
                            for d in self.cfg["project"]["optional-dependencies"]["gui"]))
        self.assertFalse(any("PyQt6" in d for d in self.cfg["project"]["dependencies"]),
                         "Qt belongs in the [gui] extra: the display loop runs without it")

    def test_every_console_script_resolves_to_a_callable(self):
        scripts = self.cfg["project"]["scripts"]
        self.assertEqual(set(scripts), {"xigmalcd", "xigmaui", "xigmalcd-reset"})
        for name, target in sorted(scripts.items()):
            with self.subTest(script=name):
                mod, _, attr = target.partition(":")
                self.assertTrue(callable(getattr(importlib.import_module(mod), attr)), target)


class ResetGate(unittest.TestCase):
    """Called with no arguments, against whatever ports happen to exist: it builds the frame,
    prints it, and sends nothing."""

    def test_no_arguments_means_a_dry_run(self):
        from xigmalcd import reset as resetmod
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = resetmod.main([])
        text = out.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("dry run: nothing sent", text)
        self.assertIn("frame to send (109 bytes)", text,
                      "the vendor's own frame length, so the frame shown is the frame that "
                      "would go")


class VersionParity(unittest.TestCase):
    """One number, three places a reader meets it: the import, the wheel, the changelog.

    The build job compares the changelog with the tag as well, but that pair only exists during a
    build; this one exists on every push, which is where a bumped `pyproject.toml` and an
    un-bumped `xigmalcd.__version__` show up.
    """

    def test_the_import_and_the_declared_version_agree(self):
        with open(PYPROJECT, "rb") as fh:
            declared = tomllib.load(fh)["project"].get("version")
        self.assertEqual(xigmalcd.__version__, declared)

    def test_the_top_changelog_stanza_carries_the_same_number(self):
        with open(CHANGELOG, encoding="utf-8") as fh:
            head = fh.readline()
        got = re.match(r"^\S+ \(([^)]+)\) \S+;.*$", head)
        self.assertIsNotNone(got, f"not a changelog heading: {head!r}")
        self.assertEqual(got.group(1), xigmalcd.__version__,
                         "debian/changelog, pyproject.toml and xigmalcd.__version__ are the "
                         "same version, in the same commit, or a release is mislabelled")


class Licence(unittest.TestCase):
    """The licence the README states and the one the package declares are the same file."""

    def test_the_spdx_expression_and_the_file(self):
        with open(PYPROJECT, "rb") as fh:
            project = tomllib.load(fh)["project"]
        self.assertEqual(project.get("license"), "GPL-3.0-or-later")
        self.assertEqual(project.get("license-files"), ["LICENSE"])
        with open(os.path.join(fixtures.REPO, "LICENSE"), "rb") as fh:
            raw = fh.read()
        self.assertIn(b"GNU GENERAL PUBLIC LICENSE\n                       Version 3", raw[:200])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), GPL3_SHA256,
                         "LICENSE is not the FSF's gpl-3.0.txt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
