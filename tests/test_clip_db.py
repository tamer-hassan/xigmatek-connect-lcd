#!/usr/bin/env python3
"""One row per distinct clip, whatever it is called.

Ported from the dedupe half of `tools/selftest.sh`'s media-roots section.

The roots hold far more files than there are clips, and the duplicates are not accidents: the
Windows app's own upload history copies a library clip into `media/background/` under a
millisecond name every time a theme is applied.  A rule keyed on (name, length) cannot see a
renamed copy, so the list is keyed on **length and content**.  Both halves matter, and the second
is the one that makes this a test rather than a filter: dropping renamed copies must not drop
genuinely different clips that merely happen to share a size.

The fixture is built in a temp root rather than read from the bench.  The old section also quoted
what the author's machine sees with the Windows partition mounted (204 files walked, 166 copies
dropped) - those are bench figures, and the printout that produces them is `xigmaui`'s clip column
and this file's own counts, so no page carries them any more.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from tests import fixtures

from xigmalcd import main as m


def blob(seed: str, size: int = 3 << 20) -> bytes:
    """Deterministic bytes, and deliberately over 2 MiB: the comparison reads a window at each end
    of a file before it falls back to hashing the whole thing, and 3 MiB exercises that edge path."""
    h = hashlib.sha256(seed.encode())
    out = b""
    while len(out) < size:
        out += h.digest() * 4096
        h.update(h.digest())
    return out[:size]


class Dedupe(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xigma-dedupe-")
        self.saved_env = os.environ.get(m.MEDIA_ENV)
        os.environ[m.MEDIA_ENV] = self.tmp.name

    def tearDown(self):
        if self.saved_env is None:
            del os.environ[m.MEDIA_ENV]
        else:
            os.environ[m.MEDIA_ENV] = self.saved_env
        self.tmp.cleanup()

    def write(self, name: str, data: bytes) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_a_renamed_byte_copy_adds_no_row_and_a_different_clip_keeps_its_own(self):
        from xigmaui import clips

        same = blob("one clip")
        self.write("Theme_probe.mp4", same)
        self.write("1757490000001.mp4", same)      # the upload history's spelling of a copy
        tiny = blob("tiny clip", 4096)             # small: both read windows are the whole file
        self.write("tiny_original.mp4", tiny)
        self.write("1757490000002.mp4", tiny)
        self.write("Theme_other.mp4", blob("another clip"))

        rows = clips.list_clips()
        listed = {os.path.basename(r.path) for r in rows}
        self.assertLessEqual({"Theme_probe.mp4", "tiny_original.mp4", "Theme_other.mp4"}, listed,
                             sorted(listed)[:8])
        self.assertEqual([n for n in listed if n.startswith("175749")], [],
                         "a byte-identical copy under another name took its own row")

        scan = clips.LAST_SCAN
        self.assertGreaterEqual(scan["copies"], 2, scan)
        self.assertGreaterEqual(scan["renamed"], 2,
                                "both copies sat under other names, and the scan should say so")
        self.assertEqual(sum(scan["roots"].values()), scan["copies"], scan)
        self.assertEqual(len(clips.list_clips()), len(rows), "the walk is not stable")

    def test_two_clips_of_the_same_length_are_still_two_rows(self):
        from xigmaui import clips

        a, b = blob("first"), blob("second")
        self.assertEqual(len(a), len(b))
        self.write("same_size_one.mp4", a)
        self.write("same_size_two.mp4", b)
        listed = {os.path.basename(r.path) for r in clips.list_clips()}
        self.assertLessEqual({"same_size_one.mp4", "same_size_two.mp4"}, listed,
                             "a rule keyed on length alone would have dropped one of these")


if __name__ == "__main__":
    unittest.main(verbosity=2)
