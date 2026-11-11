#!/usr/bin/env python3
"""The packaged forms against the checkout's: unit, menu entry, name, icon, udev rule.

Ported from `tools/selftest.sh`'s ".deb's unit and menu entry against the checkout's" section.
Nothing here builds a `.deb` - the deb job does that - but every pair of files a build copies from
is compared to the other, and **both sides are read**: there is no remembered list of keys anywhere
in this file, because a list of keys is exactly the thing that goes stale when someone edits one
file and not the other.

The two sanctioned differences between the units are asserted as differences, so a third one shows
up as a failure rather than as a slow drift between what a clone runs and what an install runs.
"""
from __future__ import annotations

import os
import re
import unittest

from tests import fixtures


def groups(path: str) -> dict:
    """key=value by `[group]`, comments skipped: enough for a unit file and a `.desktop` entry,
    and it keeps the main entry's `Exec` apart from the tray action's."""
    out: dict = {}
    current = None
    for line in fixtures.read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            out[current] = {}
        elif current is not None and "=" in line:
            key, _, value = line.partition("=")
            out[current][key] = value.strip()
    return out


class SystemdUnit(unittest.TestCase):
    """`debian/xigmalcd.service` against `install/xigmalcd.service.in`."""

    deb = groups(os.path.join("debian", "xigmalcd.service"))
    checkout = groups(os.path.join("install", "xigmalcd.service.in"))

    def test_what_the_run_is_and_how_it_behaves_are_identical(self):
        for key in ("Description", "After", "PartOf"):
            with self.subTest(key=key):
                self.assertEqual(self.deb["Unit"][key], self.checkout["Unit"][key])
        for key in ("Type", "ExecStartPre", "Restart", "RestartSec", "Nice"):
            with self.subTest(key=key):
                self.assertEqual(self.deb["Service"][key], self.checkout["Service"][key])
        self.assertEqual(self.deb["Install"]["WantedBy"], self.checkout["Install"]["WantedBy"])

    def arguments(self) -> dict:
        """Two spellings of one command line.  The checkout's theme and rate come out of
        `install.sh`'s own defaults, so a changed default cannot drift past this test."""
        install = fixtures.read(os.path.join("install", "install.sh"))
        defaults = dict(re.findall(r'^(\w+)="\$\{XIGMALCD_\w+:-([^"]*)\}"', install, re.M))
        co = self.checkout["Service"]["ExecStart"].replace("@THEME@", defaults["THEME"]) \
                                                  .replace("@FPS@", defaults["FPS"]).split()
        self.assertEqual(co[:2], [os.path.basename(co[0]), "-m"], co[:3])
        self.assertEqual(co[2], "xigmalcd", co[:3])
        db = self.deb["Service"]["ExecStart"].split()
        self.assertEqual(db[0], "/usr/bin/xigmalcd",
                         "the installed form runs the entry point, not `python3 -m`")
        return {"checkout": co[3:], "installed": db[1:]}

    def test_both_exec_start_lines_are_one_command_and_the_real_parser_takes_both(self):
        args = self.arguments()
        self.assertEqual(args["checkout"], args["installed"])
        from xigmalcd import main as cli
        from xigmalcd import render
        for which, argv in args.items():
            with self.subTest(unit=which):
                self.assertNotIn("--allow-reset", argv, argv)
                self.assertNotIn("--no-control", argv, argv)
                ns = cli.build_parser().parse_args(argv)
                self.assertIn(ns.theme, render.THEMES)
                self.assertGreaterEqual(ns.fps, 0.1)
                self.assertLessEqual(ns.fps, 5.0)

    def test_the_two_differences_are_the_layout_and_not_the_panel(self):
        """A checkout needs a working directory because it runs `-m xigmalcd`; an installed system
        has no checkout to cd to, and only it can point a reader at a README in /usr/share/doc."""
        self.assertIn("WorkingDirectory", self.checkout["Service"])
        self.assertNotIn("WorkingDirectory", self.deb["Service"])
        docs = [ln.split("=", 1)[1].strip()
                for ln in fixtures.read(os.path.join("debian", "xigmalcd.service")).splitlines()
                if ln.startswith("Documentation=")]
        self.assertTrue(any(d.startswith("file:/usr/share/doc/xigmatek-connect-lcd/")
                            for d in docs), docs)
        self.assertTrue(any(d.startswith("https://") for d in docs), docs)


class MenuEntry(unittest.TestCase):
    deb = groups(os.path.join("debian", "xigmaui.desktop"))
    checkout = groups(os.path.join("install", "xigmaui.desktop.in"))

    #: 14 keys both forms must spell the same way, read from the files rather than guessed at.
    SHARED = ("Type", "Version", "Name", "GenericName", "GenericName[en_US]", "Comment",
              "Comment[en_US]", "Terminal", "Categories", "Keywords", "StartupNotify",
              "StartupWMClass", "NoDisplay", "Actions")

    def test_the_fourteen_shared_keys_agree(self):
        for key in self.SHARED:
            with self.subTest(key=key):
                self.assertEqual(self.deb["Desktop Entry"][key],
                                 self.checkout["Desktop Entry"][key])

    def test_only_the_way_the_program_is_started_differs(self):
        self.assertTrue(self.checkout["Desktop Entry"]["Exec"].endswith("-m xigmaui"))
        self.assertEqual(self.deb["Desktop Entry"]["Exec"], "xigmaui")
        self.assertIn("Path", self.checkout["Desktop Entry"])
        self.assertNotIn("Path", self.deb["Desktop Entry"])
        self.assertEqual(self.deb["Desktop Action tray"]["Exec"], "xigmaui --hidden")

    def test_desktop_file_validate_agrees_on_the_installed_form(self):
        fixtures.need("desktop-file-validate")
        got = fixtures.run("desktop-file-validate",
                           os.path.join(fixtures.REPO, "debian", "xigmaui.desktop"))
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)


class TheProgramsOwnName(unittest.TestCase):
    """One name, in the four places a reader sees it: title bar, tray tooltip, and both entries."""

    deb = groups(os.path.join("debian", "xigmaui.desktop"))
    checkout = groups(os.path.join("install", "xigmaui.desktop.in"))

    def test_app_py_s_title_is_what_both_entries_say(self):
        src = fixtures.read(os.path.join("xigmaui", "app.py"))
        title = re.search(r'^TITLE = "(.*)"$', src, re.M)
        self.assertIsNotNone(title, "xigmaui/app.py declares no TITLE constant")
        name = self.deb["Desktop Entry"]["Name"]
        self.assertEqual(name, self.checkout["Desktop Entry"]["Name"])
        self.assertEqual(name, title.group(1))
        self.assertIn("setWindowTitle(TITLE)", src)
        self.assertIn("setToolTip(TITLE", src,
                      "the window does not take its own name from TITLE")

    def test_the_name_says_connect_and_not_connect_360(self):
        """The protocol work was measured on a Connect 360 and no other model has been tested, so
        the entry names the family the program is written for rather than one person's unit, and
        keeps `connect 360` as a search keyword only."""
        self.assertIn("connect 360", self.deb["Desktop Entry"]["Keywords"])
        self.assertNotIn("360", self.deb["Desktop Entry"]["Name"])
        self.assertNotIn("360", self.deb["Desktop Entry"]["Comment"])


class TheIcon(unittest.TestCase):
    """The icon is one claim made by three files, so all three are read."""

    INSTALLED = "usr/share/icons/hicolor/256x256/apps/xigmaui.png"

    def test_the_package_installs_the_picture_the_entry_names_and_the_window_looks_for(self):
        entry = groups(os.path.join("debian", "xigmaui.desktop"))["Desktop Entry"]
        self.assertEqual(entry["Icon"], "xigmaui")
        self.assertIn(self.INSTALLED,
                      fixtures.read(os.path.join("debian", "xigmatek-connect-lcd.install")),
                      "the package does not install the icon the entry names")
        self.assertIn("/" + self.INSTALLED, fixtures.read(os.path.join("xigmaui", "app.py")),
                      "xigmaui/app.py does not look where the package puts the picture")
        self.assertTrue(os.path.isfile(os.path.join(fixtures.REPO, "install",
                                                    os.path.basename(self.INSTALLED))))


class UdevRule(unittest.TestCase):
    def test_there_is_exactly_one_and_the_build_installs_it(self):
        """Tracked files, not a walk: a build tree has a copy of the same rule under `debian/tmp`,
        and that is a build artifact rather than a second file someone has to keep in step."""
        fixtures.need("git")
        found = fixtures.tracked("*.rules")
        self.assertEqual(found, [os.path.join("install", "99-xigmatek-lcd.rules")], found)
        self.assertIn("install/99-xigmatek-lcd.rules", fixtures.read(os.path.join("debian",
                                                                                 "rules")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
