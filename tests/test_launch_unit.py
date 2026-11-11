#!/usr/bin/env python3
"""The always-on path: the systemd unit template, and the command line it turns into.

Ported from `tools/selftest.sh`'s login-unit and no-Qt blocks.  Three things are checked against
the code rather than against a remembered copy of a list, because a unit that disagrees with the
program it starts does not fail loudly - it fails at start, on a boot, and what a person sees is a
display that never came back:

* the only holes in the template are the ones the installer fills;
* the theme and rate it defaults to are ones the renderer and the control socket accept;
* the expanded `ExecStart` parses through the real argument parser, not one that merely resembles it.

And the other half of the menu entry, on a box without Qt: the `.deb` makes PyQt6 a Suggest rather
than a Depends precisely because the loop that holds the port runs without it, so an installed
system can have the menu entry and no Qt.  What that person gets has to be a sentence.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import textwrap
import unittest

from tests import fixtures

from xigmalcd import main as cli
from xigmalcd import render


class ServiceTemplate(unittest.TestCase):
    """`install/xigmalcd.service.in`, expanded the way `install/install.sh` expands it."""

    @classmethod
    def setUpClass(cls):
        cls.unit = fixtures.read(os.path.join("install", "xigmalcd.service.in"))
        cls.installer = fixtures.read(os.path.join("install", "install.sh"))

    def test_the_only_holes_are_the_ones_the_installer_fills(self):
        self.assertLessEqual(set(re.findall(r"@(\w+)@", self.unit)),
                             {"DIR", "PYTHON", "THEME", "FPS"})

    def expanded(self) -> str:
        """Reads the defaults out of the installer's own `${XIGMALCD_*:-...}` lines, so a changed
        default there cannot drift past a test that remembered the old one."""
        defaults = dict(re.findall(r'^(\w+)="\$\{XIGMALCD_\w+:-([^"]*)\}"', self.installer,
                                   re.M))
        self.assertLessEqual({"THEME", "FPS"}, set(defaults), defaults)
        return (self.unit.replace("@DIR@", fixtures.REPO)
                      .replace("@PYTHON@", sys.executable)
                      .replace("@THEME@", defaults["THEME"])
                      .replace("@FPS@", defaults["FPS"]))

    def arguments(self) -> list:
        start = [ln for ln in self.expanded().splitlines() if ln.startswith("ExecStart=")]
        self.assertEqual(len(start), 1, [ln for ln in self.unit.splitlines()][:4])
        args = start[0].split()[1:]
        self.assertNotIn("@", " ".join(args), args)
        return args

    def test_the_real_parser_takes_the_units_command_line(self):
        """An unknown flag is a SystemExit at start.  `parse_args` on the whole argument list,
        rather than a grep for the flags somewhere in the source."""
        args = self.arguments()
        ns = cli.build_parser().parse_args(args[2:])        # drop `-m xigmalcd`
        self.assertEqual(ns.theme, args[args.index("--theme") + 1])
        self.assertIn(ns.theme, render.THEMES, ns.theme)
        self.assertGreaterEqual(ns.fps, 0.1)
        self.assertLessEqual(ns.fps, 5.0)                   # control.py's accepted range

    def test_the_unit_leaves_the_window_a_socket(self):
        """`--no-control` would take away the door the window uses to drive a running display."""
        self.assertNotIn("--no-control", self.arguments())
        self.assertNotIn("--allow-reset", self.arguments(),
                         "an autostarted unit must never be able to reset the panel")


NO_QT_BLOCKER = textwrap.dedent('''
    import sys


    class Blocker:
        def find_spec(self, name, path=None, target=None):
            if name == "PyQt6" or name.startswith("PyQt6."):
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return None


    sys.meta_path.insert(0, Blocker())
''')


class WithoutQt(unittest.TestCase):
    """Qt is installed on this machine, so the honest way to test its absence is to hide it."""

    def test_the_window_says_what_to_install_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "sitecustomize.py"), "w", encoding="utf-8") as fh:
                fh.write(NO_QT_BLOCKER)
            got = fixtures.run(sys.executable, "-m", "xigmaui", "--help",
                               env={"PYTHONPATH": td})
        text = got.stdout + got.stderr
        self.assertNotIn("Traceback", text, text)
        self.assertEqual(got.returncode, 2, text)
        self.assertIn("xigmaui needs Qt", text, "no plain-language reason")
        self.assertIn("python3-pyqt6", text, "does not name the package to install")


if __name__ == "__main__":
    unittest.main(verbosity=2)
