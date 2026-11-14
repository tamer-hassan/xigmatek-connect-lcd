#!/usr/bin/env python3
"""The launcher, its icon, and the mark they both point at.

Ported from `tools/selftest.sh`'s launcher section.  The two claims worth the lines: a menu entry
is only as good as the program its `Exec` starts and the class the shell matches on, and a shipped
generated file must still be the file its own tool produces - because the failure mode for artwork
is somebody editing the PNG instead of the JPEG it was cut from.

The desktop entry is read **by group**.  The file has a second `Exec` now, in the tray action, and
a flat key/value read of the whole file would quietly test the action instead of the entry.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from PIL import Image

from tests import fixtures

TEMPLATE = os.path.join("install", "xigmaui.desktop.in")
ICON = os.path.join("install", "xigmaui.png")
ICO = os.path.join("install", "xigmaui.ico")
ARTWORK = os.path.join("install", "artwork", "xigma-penguin.jpg")
LOGO = os.path.join("docs", "logo.png")

#: The artwork `tools/makeicon.py` cuts both files from.  Pinned, and named in that tool's own
#: docstring, so a re-encode of the source picture is a deliberate act with a diff in front of it.
ARTWORK_SHA256 = "3774623ba3c4e934d2f40932f2037712f617cad877e2c3d65e8063b97a1e69aa"


def groups_of(text: str) -> dict:
    """An INI-ish desktop file, keyed by its `[Groups]` - which is what makes the two `Exec`s
    mean different things."""
    out: dict = {}
    group = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
            out[group] = {}
        elif group is not None and "=" in line:
            key, _, value = line.partition("=")
            out[group][key] = value
    return out


def expanded() -> str:
    """The template with the placeholders filled the way `install/install.sh` fills them."""
    text = fixtures.read(TEMPLATE)
    return (text.replace("@DIR@", fixtures.REPO)
                .replace("@PYTHON@", sys.executable))


class DesktopEntry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.groups = groups_of(expanded())
        cls.main = cls.groups["Desktop Entry"]

    def test_no_placeholder_survives_the_expansion(self):
        self.assertNotIn("@", "".join(self.main.values()), "a placeholder was left unexpanded")

    def test_the_entry_starts_the_program_of_this_checkout(self):
        self.assertTrue(self.main["Exec"].endswith("-m xigmaui"), self.main["Exec"])
        self.assertTrue(os.path.isdir(self.main["Path"]), self.main["Path"])

    def test_the_icon_is_a_full_path_so_no_icon_theme_is_required(self):
        self.assertEqual(self.main["Icon"], os.path.join(fixtures.REPO, ICON))

    def test_the_class_the_shell_matches_on_is_the_name_the_program_sets(self):
        """Otherwise the launcher's icon and the taskbar entry never line up."""
        self.assertEqual(self.main["StartupWMClass"], "xigmaui")
        src = fixtures.read(os.path.join("xigmaui", "app.py"))
        self.assertIn("setApplicationName", src)
        self.assertIn("setDesktopFileName", src)

    def test_the_tray_action_carries_its_own_way_of_working(self):
        """`--hidden` needs a tray to be useful, and `Path` is only legal in the main group - so
        the action has to move to the checkout itself or `-m xigmaui` would not find the package."""
        act = self.groups["Desktop Action tray"]
        self.assertIn("--hidden", act["Exec"])
        self.assertIn(f"cd {fixtures.REPO} &&", act["Exec"])
        self.assertEqual(self.main["Actions"].rstrip(";"), "tray")
        self.assertNotIn("Path", act, "Path is not legal in an action group")

    def test_the_flags_the_entry_uses_are_flags_the_program_takes(self):
        src = fixtures.read(os.path.join("xigmaui", "app.py"))
        self.assertIn("--hidden", src)
        self.assertIn("--no-tray", src)

    def test_desktop_file_validate_agrees_when_it_is_installed(self):
        fixtures.need("desktop-file-validate")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "xigmaui.desktop")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(expanded())
            got = fixtures.run("desktop-file-validate", path)
            self.assertEqual(got.returncode, 0, got.stdout + got.stderr)

class HeadlessBoundary(unittest.TestCase):
    """The README's claim that the panel runs without a desktop, measured rather than asserted.

    `xigmalcd` is the program that owns the port and draws the frames; `xigmaui` is a client of
    it.  That is not a style rule, it is a dependency fact a reader can be burned by: an install
    on a headless box (a server, a seat with no X or Wayland session, a minimal system with no
    `python3-pyqt6`) has to work, and the only way to keep it working is to hold the boundary
    where a later convenience could break it.

    Three checks, each measuring a different thing: the import graph of the daemon package, the
    same graph for the window (so the first check is not passing because nothing was read), and
    importing every daemon module **with Qt made unavailable at import time**, which is the
    closest this suite can come to a machine that never installed PyQt6.
    """

    GUI = ("PyQt5", "PyQt6", "PySide2", "PySide3", "PySide6", "tkinter", "wx", "kivy")

    def imports_of(self, package: str) -> set:
        """Top-level module names imported by every file under `package`, read out of the AST."""
        import ast
        found = set()
        for entry in sorted(os.listdir(os.path.join(fixtures.REPO, package))):
            if not entry.endswith(".py"):
                continue
            path = os.path.join(fixtures.REPO, package, entry)
            for node in ast.walk(ast.parse(fixtures.read(os.path.join(package, entry)))):
                if isinstance(node, ast.Import):
                    found.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    found.add(node.module.split(".")[0])
            del path
        return found

    def test_the_daemon_package_names_no_toolkit_at_all(self):
        got = sorted(self.imports_of("xigmalcd") & set(self.GUI))
        self.assertEqual(got, [], f"the daemon now imports {got}: a headless install cannot "
                                  "run it, which is what the README promises")
        # non-vacuity: the walk read real imports, and the two it should find are these
        third_party = {"PIL", "serial"}
        self.assertTrue(third_party <= self.imports_of("xigmalcd"),
                        sorted(self.imports_of("xigmalcd")))

    def test_the_window_is_the_half_that_needs_the_toolkit(self):
        self.assertIn("PyQt6", self.imports_of("xigmaui"),
                      "the window no longer imports Qt, so the check above is measuring a "
                      "boundary that has moved - re-read the README before trusting it")

    def test_every_daemon_module_imports_with_qt_absent_from_the_interpreter(self):
        """Import the whole daemon with a hook that refuses any Qt module.

        A grep says no file names PyQt6; this says the package still *loads* when the toolkit is
        not there, which is the property a headless machine cares about.
        """
        probe = (
            "import sys\n"
            "class NoQt:\n"
            "    def find_module(self, name, path=None): return None\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in ('PyQt5','PyQt6','PySide2','PySide6','shiboken2',"
            "'shiboken6'):\n"
            "            raise ImportError(f'{name} is not installed on this machine')\n"
            "        return None\n"
            "sys.meta_path.insert(0, NoQt())\n"
            "import importlib, pkgutil, xigmalcd\n"
            "mods = [m.name for m in pkgutil.iter_modules(xigmalcd.__path__)\n"
            "        if m.name != '__main__']   # __main__ runs the CLI when imported\n"
            "for m in mods: importlib.import_module('xigmalcd.' + m)\n"
            "print(len(mods), 'modules', ','.join(sorted(mods)))\n"
        ).replace("\\n", "\n")
        got = fixtures.run(sys.executable, "-c", probe)
        self.assertEqual(got.returncode, 0,
                         f"the daemon does not import without Qt: {got.stderr[-500:]}")
        self.assertIn("modules", got.stdout, got.stdout)
        del probe


class TheFlagTableMatchesTheParser(unittest.TestCase):
    """The page that lists the flags and the program that reads them are one set.

    Found the hard way on 2026-11-14: adding `--frames` to `main.build_parser()` was done by
    replacing the block of lines above it, and the replacement silently dropped
    `ap.add_argument("--once", ...)`.  Every CLI test that passes `--once` would have gone red
    - two of them did, in this very file's neighbours - but the flag list in docs/usage.md,
    the systemd unit, the desktop entry and the window's own toggles were untouched, so the
    damage looked like a broken test rather than a removed feature.  A documented flag that
    the parser does not have is the same class of fault as a source with no painter and a
    shape with no source, and it is gated the same way: both directions, with the exceptions
    named.

    49 flags are documented in `docs/usage.md`; the parser defines 52 options of which three
    are argparse's own (`-h`, `--help`) plus whatever this check catches.  Printed, so the
    page can quote the door rather than a number kept by hand.
    """

    def test_every_documented_flag_is_one_the_parser_takes(self):
        import re
        with open(os.path.join(fixtures.REPO, "docs", "usage.md"), encoding="utf-8") as fh:
            rows = [ln for ln in fh.read().split("\n") if ln.startswith("| `")]
        documented = set()
        for ln in rows:
            cell = ln.split("|")[1]
            documented.update(re.findall(r"-{1,2}[a-z][a-z0-9-]*", cell))
        from xigmalcd import main
        known = {opt for act in main.build_parser()._actions for opt in act.option_strings}
        print(f"  flag reconciliation: {len(documented)} documented, {len(known)} defined, "
              f"{sorted(known - documented - {'-h', '--help'}) or 'none'} undocumented")
        self.assertEqual(sorted(documented - known), [],
                         f"{sorted(documented - known)} are documented but the parser does "
                         "not take them - the page is describing a flag that no longer exists")
        extra = sorted(known - documented - {"-h", "--help"})
        self.assertEqual(extra, [],
                         f"{extra} are accepted by the CLI and named nowhere in "
                         "docs/usage.md: a flag nobody can read about is a flag nobody uses")
        for must in ("--once", "--duration", "--frames", "--theme", "--list-themes"):
            self.assertIn(must, known,
                          f"`{must}` is gone from the parser: this is exactly the accident "
                          "the class exists to catch")



class TheMark(unittest.TestCase):

    """Both files come from one artwork, and both are the tool's output, byte for byte."""

    def test_the_png_is_a_mark_and_not_a_plate(self):
        """The artwork arrives as a JPEG with a transparency checkerboard painted into it, so if
        that grid ever survives the extraction the icon is a photo of a grey grid.  The corners are
        where it would show."""
        with Image.open(os.path.join(fixtures.REPO, ICON)) as im:
            self.assertEqual(im.size, (256, 256))
            self.assertEqual(im.mode, "RGBA")
            corners = [im.getpixel(xy)[3] for xy in ((0, 0), (255, 0), (0, 255), (255, 255))]
        self.assertEqual(corners, [0, 0, 0, 0], corners)
        self.assertGreater(os.path.getsize(os.path.join(fixtures.REPO, ICON)), 20_000)

    def test_the_ico_offers_every_size_rather_than_one_shrunken_bitmap(self):
        with Image.open(os.path.join(fixtures.REPO, ICO)) as im:
            sizes = im.info["sizes"]
        self.assertIn((16, 16), sizes)
        self.assertIn((256, 256), sizes)
        self.assertGreater(os.path.getsize(os.path.join(fixtures.REPO, ICO)), 20_000)

    def test_the_artwork_is_the_one_the_tool_names(self):
        got = fixtures.sha256_of(os.path.join(fixtures.REPO, ARTWORK))
        self.assertEqual(got, ARTWORK_SHA256)
        self.assertIn(got, fixtures.read(os.path.join("tools", "makeicon.py")),
                      "the tool's docstring no longer names this artwork")

    def test_regenerating_the_shipped_files_gives_the_same_bytes(self):
        """The strongest version of both checks above: in artwork mode `makeicon.py` reads no clock
        and no live metrics, so it is deterministic.  A difference means a generated file was
        edited by hand instead of its source."""
        with tempfile.TemporaryDirectory() as td:
            out, outico = (os.path.join(td, n) for n in ("i.png", "i.ico"))
            got = fixtures.run(sys.executable, os.path.join(fixtures.REPO, "tools", "makeicon.py"),
                               "-o", out, "--ico", outico)
            self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
            for shipped, made in ((ICON, out), (ICO, outico)):
                with self.subTest(file=shipped):
                    self.assertEqual(fixtures.sha256_of(os.path.join(fixtures.REPO, shipped)),
                                     fixtures.sha256_of(made))

    def test_the_logo_the_front_page_shows_is_the_same_mark_on_alpha(self):
        with Image.open(os.path.join(fixtures.REPO, LOGO)) as im:
            self.assertEqual(im.mode, "RGBA")
            self.assertGreater(im.width, im.height)
        self.assertIn(f'"{LOGO}"', fixtures.read("README.md"), "README: no logo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
