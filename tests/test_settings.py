#!/usr/bin/env python3
"""What the window remembers between runs, and the junk it refuses.

Ported from `tools/selftest.sh`'s "settings" section.  The file under test is one small JSON
document, and the checks are about two things only: a stored value comes back as the same type the
widget would accept, and a file that a person hand-edited - truncated, wrong type, out of range, or
written by an older release - never stops the window from starting.

`fixtures.py` has already pointed `XDG_CONFIG_HOME` at a temporary root, so every write here lands
somewhere disposable.  One test moves the root again on purpose, because the retired-key case has
to be read from a file on disk rather than from a dict.
"""
from __future__ import annotations

import json
import os
import unittest

from tests import fixtures

from xigmaui import settings

#: A clip that exists in this checkout.  A stored path that does not exist (the Windows partition
#: is not always mounted) is a different case, tested separately.
CLIP = os.path.join(fixtures.REPO, "media", "Theme_11.mp4")


class NoFile(fixtures.FreshConfigRoot):
    def test_a_missing_file_is_defaults_not_an_error(self):
        self.assertEqual(settings.load(), settings._clean({}))
        self.assertFalse(os.path.exists(settings.path()),
                         "the check below assumes there is no file to read")


class RoundTrip(fixtures.FreshConfigRoot):
    """Every value the window can change, saved and read back."""

    WANT = dict(theme="gauge", clock_size=44, canvas="black", scrim=60, fans=False,
                preview_fps=4.5, clip=CLIP, size=[900, 640], keep_my_clip=True)

    def test_every_typed_value_comes_back_as_the_same_thing(self):
        start = dict(settings.load())
        start.update(self.WANT)
        where = settings.save(start)
        self.assertEqual(where, settings.path())
        back = settings.load()
        for key, val in self.WANT.items():
            self.assertEqual(back[key], val, key)

    def test_the_file_is_plain_json_a_person_could_edit(self):
        settings.save(dict(settings.load(), clock_size=44))
        with open(settings.path(), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["clock_size"], 44)


class ThePairingFlag(fixtures.FreshConfigRoot):
    """`keep_my_clip` is a bool and only a bool.

    The difference between "the pairing put this clip here" and "hold this one" is a fact about
    what a human asked for, and the window cannot recover it from a path: both clips are the same
    shape on disk.  So it is stored, and a truthy accident here would silently stop the window
    following a layout's own clip with nothing on screen to say why the picture stopped changing.
    """

    JUNK = ("yes", "true", 1, 0, None, [], {}, 3.5)

    def test_true_survives_a_save_and_a_reload(self):
        state = dict(settings.load(), keep_my_clip=True)
        settings.save(state)
        self.assertIs(settings.load()["keep_my_clip"], True)

    def test_no_other_value_is_taken_as_true(self):
        for junk in self.JUNK:
            with self.subTest(junk=repr(junk)):
                self.assertIs(settings._clean({"keep_my_clip": junk})["keep_my_clip"], False)
        self.assertIs(settings._clean({})["keep_my_clip"], False)
        self.assertIs(settings._clean({"keep_my_clip": False})["keep_my_clip"], False)


class RetiredKey(fixtures.FreshConfigRoot):
    """`clip_customized` was the older key for the same idea, and 0.4 changed what it means.

    An older file said "a row was clicked", a newer one says "a person ticked a box", so four
    combinations are pinned: the one a real upgrade hits, the pair that disagrees with itself, and
    the two that need no explaining - which must stay quiet, because a note nobody needed is a
    note that reads like a fault.
    """

    CASES = (("only the old key, true", {"clip_customized": True}, True, "keep my background"),
             ("only the old key, false", {"clip_customized": False}, False, None),
             ("both keys, new wins", {"clip_customized": True, "keep_my_clip": False}, False,
              "the new key wins"),
             ("neither key", {}, False, None))

    def test_the_four_combinations(self):
        for label, raw, keeps, said in self.CASES:
            with self.subTest(case=label):
                seen: list = []
                got = settings._clean(raw, seen)
                self.assertIs(got["keep_my_clip"], keeps)
                self.assertNotIn("clip_customized", got, "the retired key is still in the dict")
                if said is None:
                    self.assertEqual(seen, [], "a file that needed no explaining handed the "
                                               "window a sentence anyway")
                else:
                    self.assertEqual(len(seen), 1, label)
                    self.assertIn(said, seen[0])

    def test_a_file_on_disk_is_honoured_explained_then_rewritten(self):
        os.makedirs(os.path.join(self.config_root, "xigmaui"), mode=0o700,
                    exist_ok=True)      # `path()` wants the app directory under the root
        was = os.environ["XDG_CONFIG_HOME"]
        try:
            with open(settings.path(), "w", encoding="utf-8") as fh:
                json.dump({"clip_customized": True, "clip": CLIP}, fh)
            note: list = []
            loaded = settings.load(note)
            self.assertIs(loaded["keep_my_clip"], True, loaded)
            self.assertEqual(len(note), 1, note)
            self.assertIn("keep my background", note[0])
            settings.save(loaded)
            with open(settings.path(), encoding="utf-8") as fh:
                disk = json.load(fh)
            self.assertNotIn("clip_customized", disk,
                             "one save should have left only `keep_my_clip` on disk")
            self.assertIs(disk["keep_my_clip"], True)
        finally:
            os.environ["XDG_CONFIG_HOME"] = was


class TextColour(fixtures.FreshConfigRoot):
    """The same validation door rather than a second rule: normalise, or fall back to ""."""

    CASES = (("amber", "#ffc400"), ("#0f8", "#00ff88"), ("#FF4040", "#ff4040"), ("", ""),
             ("cerise", ""), (None, ""), (7, ""))

    def test_a_spelling_the_renderer_accepts_is_stored_as_rrggbb(self):
        for spell, want in self.CASES:
            with self.subTest(spell=repr(spell)):
                self.assertEqual(settings._clean({"text_color": spell})["text_color"], want)

    def test_the_default_is_the_theme_s_own_ink(self):
        self.assertEqual(settings.DEFAULTS["text_color"], "")


class JunkOnDisk(fixtures.FreshConfigRoot):
    """Half-written, truncated, wrongly typed or out of range: the window starts anyway."""

    BODIES = ("", "{", "[]",
              '{"theme": "nope", "clock_size": 9999, "canvas": "x", "fans": "yes",'
              ' "preview_fps": 0, "size": [1, 1], "clip": "/media/windows-c/nope.mp4"}')

    def test_every_unusable_file_falls_back_to_defaults(self):
        for junk in self.BODIES:
            with self.subTest(body=repr(junk[:32])):
                # `save()` makes its own directory; a hand-written file has to be put somewhere,
                # and the app directory under the root is where `path()` says it belongs
                os.makedirs(os.path.dirname(settings.path()), exist_ok=True)
                with open(settings.path(), "w", encoding="utf-8") as fh:
                    fh.write(junk)
                self.assertEqual(settings.load(), settings._clean({}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
