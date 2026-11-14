#!/usr/bin/env python3
"""Names a layout answers to, and the act of renaming a copy of one.

Ported from two `tools/selftest.sh` sections: "the three ways a name is spoken for, and the two
ways it is not" and "the act: a copy of a vendor layout, renamed".  These are the gates the 0.6
rename feature shipped with, and they went unported when the suite's GUI and library sections were
moved - which matters more than it looks, because a rename is the one editor act that can make a
layout **unreachable** rather than merely wrong.

The mechanism that makes this worth gating: `scan()` keeps one record per name and `roots()` puts a
person's own directory first, so a copy written at a name the vendor's library already answers does
not sit beside the vendor's file - it hides it, and `resolve(<vendor id>)` then returns the copy.
The same folding runs the other way: two layouts differing only in case would be one name to
`resolve()`, and the refusal rules below depend on that not being the case.  So the corpus is
measured first, and the rules are only honest against a corpus that holds.

Twelve checks, in four groups:

* the name rule: the length limit usable up to its edge and refused past it, in words that name
  the limit; every `WRITER_SUFFIXES` name refused, naming both files that would collide; and no
  layout in this library carrying a name the writer would have to refuse;
* spoken for: a name, its case-fold, its swapcase and a layout's `id` all answer `why_taken`, a
  genuinely free name does not, and a copy's own name in another case is free;
* refused in words: the nine refusals, each carrying its own phrase;
* a fresh id, thirteen digits, above every id the library already answers, and not repeating
  itself within a run;
* the rename itself: everything but the `id` byte-identical, the pixels unchanged, the vendor's
  layout answering again at its own path, the notes saying what happened in the words a person
  reads, the `.bak` travelling with the copy while a crashed save's `.tmp` does not, and the
  background pairing following the copy to its new name.
"""
from __future__ import annotations

import datetime
import os
import unittest

from tests import fixtures

from xigmalcd import main as daemon
from xigmalcd import themes

#: A pinned instant for the draw comparisons: a copied layout carries a clock, so two draws a
#: second apart are not the same bytes and the pixel claim below would be about the wall clock.
WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)

SOURCE = "Theme_07"


def sha(path: str) -> str:
    return fixtures.sha256_of(path)


class TheNameRule(fixtures.FreshConfigRoot):
    """How long a name may be, what it may end in, and what the library would collide with."""

    def test_the_length_limit_is_usable_up_to_its_edge_and_refused_past_it(self):
        """The window deliberately does not cap the name box (`xigmaui/app.py` says why: a box
        that stops at the limit hides the reason), so the writer has to refuse past it in words
        that name the limit.  The edge itself has to be usable, or the constant is a lie."""
        self.assertEqual(themes._safe_name("x" * themes.NAME_LIMIT), "x" * themes.NAME_LIMIT,
                         "the limit itself must be usable")
        with self.assertRaises(ValueError) as got:
            themes._safe_name("x" * (themes.NAME_LIMIT + 1))
        self.assertIn(f"longer than {themes.NAME_LIMIT} characters", str(got.exception),
                      str(got.exception))

    def test_a_side_file_suffix_is_refused_naming_both_colliding_files(self):
        """This module writes `<name>.json.bak` and friends beside a layout.  A layout *named*
        `copy.bak` would live at `copy.bak.json` while `copy.bak` in the same listing is a
        different thing, so the refusal has to say both names or a reader cannot act on it."""
        for suffix in themes.WRITER_SUFFIXES:
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError) as got:
                    themes._safe_name(f"copy{suffix}")
                self.assertIn(f"copy{suffix}.json", str(got.exception), str(got.exception))

    def test_nothing_in_this_library_has_a_name_the_writer_would_refuse(self):
        """The precondition the refusals depend on.  If a shipped layout were named `foo.bak`, or
        if two of them differed only in case, then refusing such a name would be refusing
        something that already exists, and the case-folded resolver could not reach both halves of
        a pair - so the corpus is measured, not assumed."""
        pick, reject = themes.scan()
        every = list(pick) + list(reject)
        names = {r["name"] for r in every}
        ids = {str(r["id"]) for r in every}
        self.assertGreaterEqual(len(names), 27, f"{len(names)} layout names found: the naming "
                                               f"gates below would be measured against a stub")
        self.assertEqual([n for n in names if n.lower().endswith(themes.WRITER_SUFFIXES)], [],
                         "a layout here already carries a name ending in one of the writer's "
                         "own suffixes")
        self.assertEqual(len(names), len({n.lower() for n in names}),
                         "two layouts here differ only in case, which a case-folding resolver "
                         "cannot reach both halves of")
        self.assertEqual(len(ids), len(every), "two layout files share an id")
        self.assertEqual(len(themes.name_space()), len(names) + len(ids),
                         (themes.name_space()[:4], "`name_space()` is not names plus ids"))


class SpokenForNames(unittest.TestCase):
    """The three ways a name is taken, the two ways it is free, and the nine ways it is refused."""

    @classmethod
    def setUpClass(cls):
        pick, reject = themes.scan()
        cls.every = list(pick) + list(reject)
        cls.names = sorted({r["name"] for r in cls.every})
        cls.ids = sorted({str(r["id"]) for r in cls.every})

    def test_a_name_the_library_answers_is_never_free(self):
        """Exact, folded, swapped, or by id: all four are the same door `resolve()` answers, so
        all four have to be reported as taken - and the sentence has to say it, because this is
        what a person reads before their copy hides somebody else's layout."""
        first = self.names[0]
        for spelling in (first, first.lower(), first.swapcase(), self.ids[0]):
            with self.subTest(name=spelling):
                why = themes.why_taken(spelling)
                self.assertTrue(why, f"{spelling!r} reads as a free name")
                self.assertIn("not a free name", why, why)

    def test_a_free_name_is_free_and_a_copies_own_name_is_free_against_itself(self):
        self.assertFalse(themes.why_taken("plain-new-name"), themes.why_taken("plain-new-name"))
        for spelling in (SOURCE, SOURCE.lower()):
            with self.subTest(name=spelling):
                self.assertFalse(themes.why_taken(spelling, free_of=SOURCE),
                                 f"{spelling!r} is what this copy is already called")

    def test_each_refusal_comes_back_with_its_own_words(self):
        """Nine refusals, nine phrases.  A single generic "invalid name" would let four different
        mistakes look identical to a reader who has to fix one of them."""
        # the drawn-set phrase is asked of the registry too: pinning the word "five" here
        # is how a stale sentence got past the file that owns it
        cases = (("gauge", f"one of the {len(themes.EXPORTS)} themes"),
                 ("../escape", "path element"),
                 (".hidden", "leading dot"), ("bad.json", "suffix"),
                 ("x" * (themes.NAME_LIMIT + 1), "longer than"), ("a/b", "path element"),
                 (SOURCE, "not a free name"), (SOURCE.lower(), "not a free name"),
                 (self.ids[0], "not a free name"))
        for name, phrase in cases:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as got:
                    themes.new_name(name)
                self.assertIn(phrase, str(got.exception), f"{name!r}: {got.exception}")

    def test_a_fresh_id_is_thirteen_digits_above_every_answered_one(self):
        """The library's ids are 13-digit numbers; a new one has to be the same shape, larger
        than every existing one (so it cannot shadow anything), and distinct from its own batch."""
        numeric = sorted(int(i) for i in self.ids if str(i).isdigit())
        self.assertEqual(len(numeric), len(self.ids), (self.ids[:3],
                                                       "a vendor layout id is not digits"))
        self.assertEqual({len(str(i)) for i in numeric}, {13}, numeric[:3])
        fresh = [themes.new_id() for _ in range(6)]
        self.assertTrue(all(len(i) == 13 and i.isdigit() for i in fresh), fresh)
        self.assertEqual(len(set(fresh)), 6, f"{fresh}: two fresh ids in one run collided")
        self.assertFalse(set(fresh) & set(self.ids), (fresh[:2],
                                                      "a fresh id landed on an answered one"))
        self.assertTrue(all(int(i) > numeric[-1] for i in fresh),
                        (fresh[0], numeric[-1], "a fresh id was not above the library's"))


class RenamingACopy(fixtures.FreshConfigRoot):
    """The act itself: what moves, what stays byte-identical, and what the notes say."""

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()
        cls.rec = themes.resolve(SOURCE)

    def setUp(self):
        super().setUp()
        _rec, self.src, _soft = themes.copy_for_edit(SOURCE)
        self.obj = themes.load(self.src)
        with open(self.src, "rb") as fh:
            self.raw0 = fh.read()
        self.pixels0 = themes.draw(self.obj, {}, WHEN)[0].tobytes()

    def test_a_rename_changes_the_id_and_nothing_else_in_the_file(self):
        path, _notes = themes.rename_copy(SOURCE, "my-renamed-copy")
        again = themes.load(path)
        changed = sorted(k for k in set(self.obj) | set(again)
                         if themes.canonical(self.obj.get(k), True)
                         != themes.canonical(again.get(k), True))
        self.assertEqual(changed, ["id"], f"a rename changed {changed}: the rows, the canvas, "
                                         f"the background and the ratio are the layout itself")
        strip = lambda obj: themes.canonical({k: v for k, v in obj.items() if k != "id"}, True)
        self.assertEqual(strip(again), strip(self.obj), "everything but the id is byte-identical")
        self.assertNotEqual(again["id"], self.obj["id"], "the id did not move")
        self.assertIsNotNone(themes.shape_of(path), "the renamed file is not canonical-shaped")

    def test_the_renamed_copy_draws_the_same_pixels_as_what_it_came_from(self):
        """A rename is a name change.  If the pixels moved, the layout changed, and no sentence in
        the notes would say so."""
        path, _notes = themes.rename_copy(SOURCE, "my-renamed-copy")
        self.assertEqual(themes.draw(themes.load(path), {}, WHEN)[0].tobytes(), self.pixels0,
                         "renaming a copy moved its pixels, which is a change of layout and not "
                         "of name")

    def test_the_vendors_layout_answers_again_at_its_own_path(self):
        """The hazard the whole flow is built around: a copy sitting at a vendor's name hides it.
        After the move the name has to be free of the copy, the vendor's record has to be what
        `resolve()` returns, and its own id has to point back at the vendor's file."""
        path, _notes = themes.rename_copy(SOURCE, "my-renamed-copy")
        self.assertFalse(os.path.exists(self.src), "the old path is still there after the move")
        self.assertEqual(themes.user_copies(), ["my-renamed-copy"], themes.user_copies())
        back = themes.resolve(SOURCE)
        self.assertTrue(back and not back.get("edited"),
                        (back and themes.origin(back), "the vendor's layout did not come back"))
        self.assertEqual(themes.resolve(str(self.obj["id"]))["path"], back["path"],
                         "the vendor's own id did not go back to the vendor's file")

    def test_the_notes_say_what_happened_in_the_words_a_reader_needs(self):
        _path, notes = themes.rename_copy(SOURCE, "my-renamed-copy")
        said = " ".join(notes)
        for phrase in ("your copy moved: Theme_07.json is now my-renamed-copy.json",
                       "its id went", "answers checkout again",
                       "a copy written at a vendor's own name takes the name"):
            self.assertIn(phrase, said, f"{phrase!r} is not in the notes: {notes}")

    def test_the_backup_travels_with_the_copy_and_a_scratch_file_does_not(self):
        """`.bak` is the previous content of *this* copy, so it follows the copy to its new name;
        a `.tmp` is a crash's leftovers, and moving it would be pretending to recover something
        the program never promised to finish."""
        first, _notes = themes.rename_copy(SOURCE, "my-renamed-copy")
        themes.save(themes.load(first), "my-renamed-copy")      # a second save leaves a .bak
        with open(first + ".tmp", "w", encoding="utf-8") as fh:
            fh.write("{ half written")
        self.assertTrue(os.path.exists(first + ".bak"), "no .bak to follow the copy")
        again, notes2 = themes.rename_copy("my-renamed-copy", "moved-again")
        self.assertTrue(os.path.exists(again + ".bak"), (notes2, "the .bak did not travel with "
                                                                "the copy"))
        self.assertTrue(any("came with it" in n for n in notes2), notes2)
        self.assertTrue(os.path.exists(first + ".tmp"),
                        (notes2, "the scratch file went with the copy, though the notes say it "
                                 "stayed where the crash left it"))
        self.assertFalse(os.path.exists(again + ".tmp"),
                         (notes2, "a `.tmp` appeared under the new name: the rename invented a "
                                  "half-written file rather than leaving one behind"))
        self.assertTrue(any(".tmp stayed where it is" in n for n in notes2), notes2)

    def test_the_copy_is_a_copy_and_keeps_the_background_its_file_names(self):
        path, _notes = themes.rename_copy(SOURCE, "my-renamed-copy")
        self.assertTrue(themes.is_copy("my-renamed-copy"), "the renamed file is not a copy")
        self.assertFalse(themes.is_copy(SOURCE), "the vendor's file reads as somebody's copy")
        self.assertEqual(themes.pair("my-renamed-copy"), themes.pair(SOURCE),
                         (themes.pair("my-renamed-copy"), themes.pair(SOURCE),
                          "the renamed copy stopped naming the background its own file names"))
        self.assertEqual(daemon.theme_name("my-renamed-copy"), "my-renamed-copy")
        self.assertEqual(daemon.theme_name("MY-RENAMED-COPY"), "my-renamed-copy",
                         "the resolver does not fold case")


if __name__ == "__main__":
    unittest.main()
