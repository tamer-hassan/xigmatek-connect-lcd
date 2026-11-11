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
"""
from __future__ import annotations

import os
import re
import unittest

from tests import fixtures

MARKDOWN = re.compile(r"!?(?:\[[^\]]*\])\(([^)\s]+)")
IMG_TAG = re.compile(r'<img[^>]+src="([^"]+)"')
EXTERNAL = ("http://", "https://", "mailto:", "file:")


class RelativeLinks(unittest.TestCase):
    def documents(self) -> list:
        docs = [f for f in fixtures.tracked("*.md")
                if f == "README.md" or f.startswith("docs/")]
        self.assertGreaterEqual(len(docs), 8, docs)
        return docs

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
