#!/usr/bin/env python3
"""The panel's serial number stays on the bench - in the pixels as well as the bytes.

Ported from `tools/selftest.sh`'s serial block.  This is the privacy rule the whole `data/` tree
exists for: every transcript that holds the serial raw (`data/captures/`, `data/glass/`) is left out
of the repository outright, and prose writes `sn=<this panel's serial, redacted>`.

What held that line used to be a habit: grep the staged diff.  A staged diff is bytes, and a
screenshot keeps a serial as **pixels**, so the habit could not see one.  On 2026-11-10 an OCR pass
found the serial, whole and legible, in `docs/xigmaui2.png` - the README's advanced-mode capture,
committed on 2026-11-08 and published ever since.  It was painted out the same day.  The byte half
of this check runs everywhere; the pixel half runs where tesseract is installed and says so out
loud where it is not, because a scan that silently did nothing is worse than one that admits it.

The two marks are written **split up on purpose**, and that is not decoration: the habit this
replaces was grepping a diff for the first four characters of the serial, so a file that spelled it
out would trip its own check on every commit.  The shape regex is the second net, which means the
literal halves only ever have to be one at a time.
"""
from __future__ import annotations

import re
import unittest

from tests import fixtures

MARKS = ("BY" + "ZL", "WC07" + "AM")
SHAPE = re.compile(r"[A-Z]{4}\d{4}[A-Z]{2}\d{2}[A-Z]{2}\d{6}")

#: Where a serial could be published from.  `tests/` is on this list as well, which is why the
#: marks above are written split.
TEXT_GLOBS = ("README.md", "PROTOCOL.md", "docs/*.md", "docs/**/*.md", "debian/*",
              "install/*", "tools/*.py", "xigmalcd/*.py", "xigmaui/*.py", "tests/*.py")


def carries(path: str) -> list:
    """Either mark, as bytes, or a token with the serial's shape, in one file."""
    with open(path, "rb") as fh:
        raw = fh.read()
    hits = [m for m in MARKS if m.encode() in raw]
    shape = SHAPE.search(raw.decode("utf-8", "replace"))
    if shape:
        hits.append(shape.group(0))
    return hits


class PublishedText(unittest.TestCase):
    def test_the_list_is_the_size_of_the_repository(self):
        """A guard against the search itself falling over: if the file list comes back short, the
        check below would pass by reading almost nothing."""
        self.assertGreaterEqual(len(self.files()), 90,
                                "the published-text list fell over, so the serial search would "
                                "be searching almost nothing")

    def files(self) -> list:
        found = set()
        for pattern in TEXT_GLOBS:
            found.update(fixtures.tracked(pattern))
        return sorted(found)

    def test_the_serial_is_not_in_anything_the_repository_ships(self):
        hits = {}
        for rel in self.files():
            found = carries(rel)
            if found:
                hits[rel] = found
        self.assertEqual(hits, {}, "the panel's serial is in published text, which is the rule "
                                   "the whole data/ tree exists to keep")


class PublishedPictures(unittest.TestCase):
    """Only the PNGs.  The six MP4s film the glass, not the window, so the one field that carries a
    serial is never in frame - and the readings JSON they draw from is text, read above."""

    def test_no_published_picture_carries_it_in_pixels(self):
        fixtures.need("tesseract")
        # Ours, not the vendor's: `themes/alpha/foreground/*.png` are the vendor's own drawings,
        # their integrity is the manifest's job, and a serial in one of them would be a serial of
        # the vendor's, not of this panel.
        stills = [f for f in fixtures.tracked("*.png")
                  if f.startswith(("docs/", "media/", "install/"))]
        self.assertNotEqual(stills, [], "no published PNGs found, so this check would have "
                                        "read nothing and reported a pass")
        hits = {}
        for rel in stills:
            got = fixtures.run("tesseract", rel, "-")
            # spaces and newlines out: OCR splits a long token differently every run
            flat = (got.stdout or "").replace(" ", "").replace("\n", "")
            why = [m for m in MARKS if m in flat]
            shape = SHAPE.search(flat)
            if shape:
                why.append(shape.group(0))
            if why:
                hits[rel] = why
        self.assertEqual(hits, {}, "a published picture carries the panel serial in pixels: "
                                   "paint it out the way docs/xigmaui2.png was, do not just "
                                   "re-shoot and hope")


if __name__ == "__main__":
    unittest.main(verbosity=2)
