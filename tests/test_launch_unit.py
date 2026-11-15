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
from xigmalcd import control
from xigmalcd import render


class ServiceTemplate(unittest.TestCase):
    """`install/xigmalcd.service.in`, expanded the way `install/install.sh` expands it."""

    @classmethod
    def setUpClass(cls):
        cls.unit = fixtures.read(os.path.join("install", "xigmalcd.service.in"))
        cls.installer = fixtures.read(os.path.join("install", "install.sh"))

    def test_the_only_holes_are_the_ones_the_installer_fills(self):
        """`@THEME@` and `@FPS@` are gone, and that removal is the feature.

        They used to be substituted into `ExecStart`, which is what made the picture a
        packaging decision: to change the theme at login you edited a unit file, and the
        window that had already chosen one knew nothing about it.  What is left to fill in is
        where the code lives and which interpreter runs it.
        """
        holes = set(re.findall(r"@(\w+)@", self.unit))
        self.assertEqual(holes, {"DIR", "PYTHON"},
                         f"{sorted(holes - {'DIR', 'PYTHON'})} came back as a hole in the "
                         "unit: a theme, background or rate belongs in the saved choice "
                         "(`xigmalcd/display.py`), not in a service file")

    def expanded(self) -> str:
        """The unit as the installer writes it, read from the installer rather than copied."""
        self.assertNotIn("@THEME@", self.unit)
        self.assertNotIn("@FPS@", self.unit)
        return (self.unit.replace("@DIR@", fixtures.REPO)
                      .replace("@PYTHON@", sys.executable))

    def arguments(self) -> list:
        start = [ln for ln in self.expanded().splitlines() if ln.startswith("ExecStart=")]
        self.assertEqual(len(start), 1, [ln for ln in self.unit.splitlines()][:4])
        args = start[0].split()[1:]
        self.assertNotIn("@", " ".join(args), args)
        return args

    def test_the_units_own_command_line_still_parses(self):
        """An unknown flag is a SystemExit at start, so parse the whole list, don't grep it."""
        args = self.arguments()
        ns = cli.build_parser().parse_args(args[2:])        # drop `-m xigmalcd`
        for flag in ("--theme", "--mp4", "--fps"):
            self.assertNotIn(flag, args,
                             f"the checkout unit grew {flag} back: the saved choice owns "
                             "that decision now, and a unit that names it wins over the "
                             "file with nobody able to see why")
        self.assertIsNone(ns.theme, "the unit sets a theme after all")
        self.assertIsNone(ns.fps)
        self.assertIsNone(ns.mp4)

    def test_what_the_unit_starts_with_is_the_same_triple_the_door_prints(self):
        """Run the resolution the service will run, and hold it to the same bounds.

        The two checks that used to assert the unit's own `--theme alpha --fps 2` were in
        range now ask the question that matters: after `apply_choice`, on a machine with
        nothing saved, is what starts up still a picture at all - a drawable theme, a
        background that resolves to a real file, a rate the socket would accept?
        """
        notes: list = []
        ns = cli.build_parser().parse_args(self.arguments()[2:])
        came = cli.apply_choice(ns, notes)
        self.assertEqual(notes, [], notes)
        self.assertEqual(came, {"theme": "default", "clip": "default", "fps": "default"},
                         came)
        self.assertIn(ns.theme, render.THEMES, ns.theme)
        lo, hi = control.FPS_RANGE
        self.assertTrue(lo <= ns.fps <= hi, f"{ns.fps} outside {lo}-{hi}")
        self.assertTrue(os.path.isfile(str(ns.mp4)),
                        f"the default background does not resolve on this machine: {ns.mp4}")
        print(f"  a unit that names nothing starts at: {cli.choice_report(ns, came)}")

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
