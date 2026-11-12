#!/usr/bin/env python3
"""Every relative pointer in the documents resolves to a file this repository ships.

Ported from `tools/selftest.sh`'s markdown-link gate.  README.md is the short page and `docs/*.md`
carry the detail, so almost every pointer in this tree is a relative link from one markdown file to
another - and a split like that breaks links **silently**, because a broken relative path is still
valid markdown and GitHub renders it as text.

What is checked: every `[text](target)` and `![alt](target)`, plus the `<img src="...">` form the
README's logo uses, resolved against the file it is written in, with any `#anchor` stripped.
Anchors are deliberately not checked - GitHub and a plain file viewer derive them differently - but
files are, which is the half that moves.  Images count here because in a checkout they exist; the
installed package ships the prose without the pictures (`debian/rules` says why), and the packaged
smoke test checks the installed form for the markdown links only.

The second class holds the other half of the same promise.  A page and a shipped comment are only
as honest as the owner they name, so `tests/<file>` pointers are re-read on every run against the
tracked file list: a named module has to exist, and a named `test_*.py` has to hold a `def test_`.
"""
from __future__ import annotations

import os
import re
import unittest

from tests import fixtures

MARKDOWN = re.compile(r"!?(?:\[[^\]]*\])\(([^)\s]+)")
IMG_TAG = re.compile(r'<img[^>]+src="([^"]+)"')
EXTERNAL = ("http://", "https://", "mailto:", "file:")


def documents() -> list:
    """The published prose: the short page and the detail pages, from the tracked list."""
    docs = [f for f in fixtures.tracked("*.md")
            if f == "README.md" or f.startswith("docs/")]
    assert len(docs) >= 8, docs
    return docs


class RelativeLinks(unittest.TestCase):
    def documents(self) -> list:
        return documents()

    def test_every_relative_link_and_image_names_a_file_that_exists(self):
        links, dead = 0, []
        for doc in self.documents():
            text = fixtures.read(doc)
            found = MARKDOWN.findall(text) + IMG_TAG.findall(text)
            for dest in found:
                dest = dest.split("#", 1)[0]
                if not dest or dest.startswith(EXTERNAL):
                    continue
                links += 1
                if not os.path.exists(os.path.join(fixtures.REPO, os.path.dirname(doc), dest)):
                    dead.append((doc, dest))
        self.assertEqual(dead, [], f"{links} relative links checked")
        self.assertGreaterEqual(links, 40,
                                "so few relative links were found that this check would pass "
                                "on a document set that had lost its pointers")


class NamesChecksThatExist(unittest.TestCase):
    """A page or a shipped comment may only name a check that is in the tree.

    The 0.7 rule is that this repository's claims name their owner: `docs/*.md` and the comments
    in `xigmalcd/`, `xigmaui/` and `tools/` point at a file in `tests/` rather than at "the suite"
    or "the gate" - a habit that only holds as long as the names stay true, which is exactly the
    kind of claim a document rots away from.  So the pointers are re-read on every run:

    * every `tests/<file>` named in the published prose has to be a tracked file, and a `test_*.py`
      one has to hold at least one `def test_`, so a page cannot be satisfied by an empty module;
    * the same for the shipped source, whose comments carry the same promise;
    * and the scan asserts how much it read, because a check that found no pointers would pass.

    Which files the tree ships is taken from `git ls-files`, so a bench with build products lying
    around and CI with a clean tree answer the same question about the same set of files.
    """

    POINTER = re.compile(r"tests/([A-Za-z0-9_.\-]+\.(?:py|txt|json))")

    def shipped_tests(self) -> set:
        return {os.path.basename(f) for f in fixtures.tracked("tests/*")}

    def mentions(self, docs: bool) -> list:
        files = (documents() if docs
                 else [f for f in fixtures.tracked("*.py")
                       if f.startswith(("xigmalcd/", "xigmaui/", "tools/", "debian/"))])
        out = []
        for path in files:
            for match in self.POINTER.finditer(fixtures.read(path)):
                out.append((path, match.group(1)))
        return out

    def test_the_pages_name_checks_that_are_in_the_tree(self):
        named = self.mentions(docs=True)
        self.assertGreaterEqual(len(named), 40,
                                f"only {len(named)} pointers found in the pages: the scan is "
                                "not reading what it thinks it is")
        self.assertGreaterEqual(len({name for _, name in named}), 20, named)
        have = self.shipped_tests()
        gone = sorted({(doc, name) for doc, name in named if name not in have})
        self.assertEqual(gone, [], f"{len(named)} pointers, {len(have)} files in tests/")
        empty = sorted({name for _doc, name in named
                        if name.startswith("test_")
                        and "def test_" not in fixtures.read(os.path.join("tests", name))})
        self.assertEqual(empty, [], "named, but holding no check at all")

    def test_the_shipped_source_names_checks_that_are_in_the_tree(self):
        named = self.mentions(docs=False)
        self.assertGreaterEqual(len(named), 10,
                                f"only {len(named)} pointers found in the shipped source: the "
                                "comments have stopped naming their checks")
        have = self.shipped_tests()
        gone = sorted({(src, name) for src, name in named if name not in have})
        self.assertEqual(gone, [], f"{len(named)} pointers in the source")


if __name__ == "__main__":
    unittest.main(verbosity=2)
