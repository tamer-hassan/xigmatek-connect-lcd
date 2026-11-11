#!/usr/bin/env python3
"""Where clips are looked up: the roots a package install has to get right.

Ported from `tools/selftest.sh`'s media-roots section, including the reason one of its lines used
to be wrong: it read `media_roots() == (repo,)`, which was asserting the state of one machine
rather than a rule.  The bench became an installed box on 2026-11-07 and the assertion described a
machine that no longer existed.  So the checks here are about **order**, which is the rule, and
never about how many roots happen to exist, which belongs to the machine.

Nothing here writes to a real root.  The installed roots are stand-in directories under a temp
path, and the module's own root constants are put back in `tearDown` even when a check fails.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from tests import fixtures

from xigmalcd import main as m
from xigmalcd import themes


class CheckoutFirst(unittest.TestCase):
    """No `XIGMA_MEDIA`, no stand-ins: what a plain clone sees."""

    def setUp(self):
        self.env_saved = os.environ.pop(m.MEDIA_ENV, None)

    def tearDown(self):
        if self.env_saved is not None:
            os.environ[m.MEDIA_ENV] = self.env_saved

    def test_the_checkout_is_the_first_root_and_every_root_was_named_by_the_code(self):
        roots = m.media_roots()
        self.assertEqual(roots[0], os.path.abspath(m.REPO_MEDIA))
        named = [r for r in (os.path.abspath(m.REPO_MEDIA), os.path.abspath(m.SYSTEM_MEDIA),
                             os.path.abspath(m.REPO_CLIP_LIB),
                             os.path.abspath(m.SYSTEM_CLIP_LIB)) if r in roots]
        self.assertEqual([r for r in roots if r in named], named,
                         "a root appeared that this code did not name, or the order changed")

    def test_the_vendor_library_is_a_root_so_a_layout_can_name_its_own_background(self):
        self.assertIn(os.path.abspath(m.REPO_CLIP_LIB), m.media_roots(),
                      "this checkout's `themes/alpha/clips` is not a root, so a layout's "
                      "declared background cannot be named by the loop")

    def test_the_three_vendored_backgrounds_resolve_inside_the_checkout(self):
        for path in (m.DEFAULT_MP4, m.QUIET_MP4, m.BRIGHT_MP4):
            with self.subTest(clip=os.path.basename(path)):
                self.assertEqual(os.path.dirname(path), os.path.abspath(m.REPO_MEDIA))
                self.assertTrue(os.path.exists(path), path)

    def test_every_selectable_layouts_own_clip_resolves_by_bare_name(self):
        """The claim the extra roots exist for, taken from the library rather than from a
        remembered example: `--mp4` and the session default both go through `find_media`, and a
        bare clone passes this the same way an installed box does - the checkout carries the same
        files the themes package installs."""
        selectable, _rejected = themes.scan()
        roots = m.media_roots()
        self.assertGreater(selectable, [], "the theme library came back empty, so this "
                                           "check would have proven nothing")
        for rec in selectable:
            with self.subTest(layout=rec["name"]):
                name, why = themes.pair(rec["name"])
                self.assertTrue(name, why)
                self.assertFalse(why, why)
                got = m.find_media(name)
                self.assertEqual(os.path.basename(got), name, got)
                self.assertTrue(os.path.isfile(got), got)
                self.assertIn(os.path.dirname(got), roots,
                              "a clip resolved outside the root list")

    def test_a_clip_this_repository_vendors_in_media_resolves_there_and_not_in_the_library(self):
        """`Theme_25.mp4` has to mean the same file it meant before the library became a root, or
        the session default moves depending on what is installed."""
        vendored = {os.path.basename(p) for p in (m.DEFAULT_MP4, m.QUIET_MP4, m.BRIGHT_MP4)}
        overlap = sorted(rec["name"] for rec in themes.scan()[0]
                         if themes.pair(rec["name"])[0] in vendored)
        for name in overlap:
            with self.subTest(layout=name):
                self.assertEqual(os.path.dirname(m.find_media(themes.pair(name)[0])),
                                 os.path.abspath(m.REPO_MEDIA),
                                 "a clip `media/` also holds resolved in the theme library")


class StandInRoots(unittest.TestCase):
    """A box with both a checkout and an install, built out of temp directories."""

    NAMES = ("Theme_25.mp4", "Theme_11.mp4", "theme_48.mp4")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xigma-roots-")
        self.sysroot = os.path.join(self.tmp.name, "usr-share-xigmalcd-media")
        self.syslib = os.path.join(self.tmp.name, "usr-share-themes-clips")
        self.replib = os.path.join(self.tmp.name, "checkout-themes-clips")
        for d in (self.sysroot, self.syslib, self.replib):
            os.makedirs(d)
        for n in self.NAMES:
            with open(os.path.join(self.sysroot, n), "wb") as fh:
                fh.write(b"stand-in")
        # the case a layout file produces: a name `media/` does not hold at all, in the library in
        # both spellings; and a name both kinds of root hold, so the order can be seen
        with open(os.path.join(self.syslib, "Theme_probe_07.mp4"), "wb") as fh:
            fh.write(b"installed copy")
        with open(os.path.join(self.replib, "Theme_probe_07.mp4"), "wb") as fh:
            fh.write(b"checkout copy")
        with open(os.path.join(self.replib, "Theme_25.mp4"), "wb") as fh:
            fh.write(b"checkout library copy")
        self.saved = (m.SYSTEM_MEDIA, m.REPO_CLIP_LIB, m.SYSTEM_CLIP_LIB, m.REPO_MEDIA)
        m.SYSTEM_MEDIA = self.sysroot
        m.REPO_CLIP_LIB, m.SYSTEM_CLIP_LIB = self.replib, self.syslib

    def tearDown(self):
        m.SYSTEM_MEDIA, m.REPO_CLIP_LIB, m.SYSTEM_CLIP_LIB, m.REPO_MEDIA = self.saved
        self.tmp.cleanup()

    def test_with_both_the_checkout_still_answers(self):
        """So that a document's clip figures never depend on what happens to be installed on the
        machine reading them."""
        self.assertEqual(m.media_roots(),
                         (os.path.abspath(m.REPO_MEDIA), os.path.abspath(self.sysroot),
                          os.path.abspath(self.replib), os.path.abspath(self.syslib)))
        self.assertEqual(m.media_dir(), os.path.abspath(m.REPO_MEDIA))
        self.assertEqual(m.find_media("Theme_25.mp4"),
                         os.path.join(os.path.abspath(m.REPO_MEDIA), "Theme_25.mp4"))
        self.assertEqual(m.find_media("Theme_probe_07.mp4"),
                         os.path.join(self.replib, "Theme_probe_07.mp4"))
        self.assertNotEqual(m.find_media("Theme_25.mp4"),
                            os.path.join(self.replib, "Theme_25.mp4"),
                            "the media roots must win over a library copy of the same name")

    def test_the_installed_library_answers_when_the_checkout_library_is_not_there(self):
        saved = m.REPO_CLIP_LIB
        m.REPO_CLIP_LIB = os.path.join(self.tmp.name, "no-such-library")
        try:
            self.assertEqual(m.find_media("Theme_probe_07.mp4"),
                             os.path.join(self.syslib, "Theme_probe_07.mp4"))
        finally:
            m.REPO_CLIP_LIB = saved

    def test_with_no_checkout_the_installed_root_answers(self):
        """The whole point of installing to /usr/share."""
        saved = m.REPO_MEDIA
        m.REPO_MEDIA = os.path.join(self.tmp.name, "no-such-checkout")
        try:
            self.assertEqual(m.media_roots(),
                             (os.path.abspath(self.sysroot), os.path.abspath(self.replib),
                              os.path.abspath(self.syslib)))
            self.assertEqual(m.find_media("Theme_25.mp4"),
                             os.path.join(self.sysroot, "Theme_25.mp4"))
            self.assertEqual(m.find_media("Theme_probe_07.mp4"),
                             os.path.join(self.replib, "Theme_probe_07.mp4"))
        finally:
            m.REPO_MEDIA = saved

    def test_the_windows_copies_still_answer_and_a_missing_clip_is_reported_as_asked_for(self):
        win = os.path.join(self.tmp.name, "win", "Theme_99.mp4")
        os.makedirs(os.path.dirname(win), exist_ok=True)
        with open(win, "wb") as fh:
            fh.write(b"windows copy")
        self.assertEqual(m.find_media("Theme_99.mp4", win), win)
        nowhere = m.find_media("Theme_99.mp4")
        self.assertTrue(nowhere.endswith("Theme_99.mp4"), nowhere)
        self.assertFalse(os.path.exists(nowhere),
                         "a clip in no root is still named as the file that was asked for")


class CustomRoot(unittest.TestCase):
    """`$XIGMA_MEDIA` replaces the checkout root, and the window's list walks every root."""

    def test_the_environment_root_comes_first_and_the_window_lists_it_alongside_the_rest(self):
        with tempfile.TemporaryDirectory(prefix="xigma-xigma-media-") as envdir:
            shutil.copy(os.path.join(m.REPO_MEDIA, "Theme_25.mp4"), envdir)
            os.environ[m.MEDIA_ENV] = envdir
            try:
                self.assertEqual(m.media_dir(), os.path.abspath(envdir))
                self.assertEqual(m.media_roots()[:2], (os.path.abspath(envdir),
                                                       os.path.abspath(m.REPO_MEDIA)))
                from xigmaui import clips
                dirs = {os.path.dirname(c.path) for c in clips.list_clips()}
                self.assertIn(os.path.abspath(envdir), dirs)
                self.assertIn(os.path.abspath(m.REPO_MEDIA), dirs,
                              "an installed themes set must not be hidden from a display "
                              "running out of a clone")
            finally:
                del os.environ[m.MEDIA_ENV]


if __name__ == "__main__":
    unittest.main(verbosity=2)
