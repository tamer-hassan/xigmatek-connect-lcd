#!/usr/bin/env python3
"""The layout files a person edits: what a save writes, what it refuses, and what it must not touch.

Ported from the file-model block of `tools/selftest.sh`'s vendor-library section.  This is the part
of the program that can lose somebody's work, so the checks are about bytes rather than about
behaviour-in-the-abstract:

* all 27 copied layouts reproduce **byte for byte** from their own parsed content - which is what
  makes "did my editor corrupt this?" answerable without a diff tool, and why the writer asks each
  file which shape it is in (the files disagree with each other about one setting only: some escape
  non-ASCII as `\\uXXXX`, the ones carrying CJK content keep it raw);
* a copy for editing starts byte-identical to its source, so the difference between the vendor's file
  and yours is only the fields you touched;
* a save is atomic (no `.tmp` survives the replace, the file it overwrote leaves a `.bak`), writes an
  edit that shows up on the glass as the same `(20, 0)` shift the model asked for, and refuses - in
  words - a root it does not own, a generated theme's name, a name with a path element in it, a
  layout with nothing to draw, and a two-element `property` list;
* the vendor's tree is never written to: every layout file outside the user root is hashed before and
  after, and the hashes have to match.

One comparison discipline runs through this file: **every draw is at a pinned instant.**  A layout
with a clock in it is not a function of its file alone, it is a function of the instant too -
measured here, because a gate that forgets it fails in CI once a second, literally.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
import unittest

from tests import fixtures

from xigmalcd import render, sensors, themes

WHEN = datetime.datetime(2026, 2, 17, 9, 30)


def sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class FileShape(unittest.TestCase):
    """The copied library's 27 layouts, and the two conventions their bytes use."""

    def layouts(self) -> list:
        import glob
        return sorted(glob.glob(os.path.join(fixtures.REPO, "themes", "alpha", "layouts", "**",
                                             "*.json"), recursive=True))

    def test_all_27_reproduce_from_their_own_parsed_content(self):
        files = self.layouts()
        self.assertEqual(len(files), 27, files)
        shapes = [themes.shape_of(f) for f in files]
        self.assertNotIn(None, shapes, [f for f, s in zip(files, shapes) if s is None])
        identical = 0
        for path in files:
            text = themes.canonical(themes.load(path), themes.shape_of(path))
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            identical += raw in (text, text + "\n")
        self.assertEqual(identical, 27)
        self.assertGreater(shapes.count(True), 0, "no file escapes non-ASCII any more, so the "
                                                 "writer's question has only one answer")
        self.assertGreater(shapes.count(False), 0)

    def test_a_copy_for_edit_starts_byte_identical_to_its_source(self):
        selectable = themes.scan()[0]
        self.assertGreater(selectable, [], "no selectable layouts to copy")
        same = 0
        try:
            for rec in selectable:
                _record, path, _shape = themes.copy_for_edit(rec["name"])
                with open(path, "rb") as mine, open(rec["path"], "rb") as source:
                    same += mine.read() == source.read()
        finally:
            for rec in selectable:
                themes.delete_user_theme(rec["name"])
        self.assertEqual(same, len(selectable), "a copy for editing changed bytes on the way in")


class Saving(fixtures.FreshConfigRoot):
    """A save writes where it is allowed to, leaves a backup, and refuses everything else."""

    def setUp(self):
        super().setUp()
        self.rec = themes.resolve("Theme_28")
        self.vendor_sha = sha(self.rec["path"])
        self.obj = themes.load(self.rec["path"])
        # a text label with no `source`: it draws on any machine, with any sensors, so a box that
        # does not move here means the edit was ignored, not that a reading was missing
        self.target = next(w for w in self.obj["osd"]["widget"]
                           if not (w.get("property") or [{}])[0].get("source")
                           and (w.get("property") or [{}])[0].get("content"))
        self.label = self.target["property"][0]["content"]
        self.x0 = self.target["property"][0]["x"]
        self.target["property"][0]["x"] = self.x0 + 20
        themes.copy_for_edit("Theme_28")

    def tearDown(self):
        themes.delete_user_theme("Theme_28")
        super().tearDown()

    def vendor_tree(self) -> dict:
        import glob
        paths = sorted(glob.glob(os.path.join(fixtures.REPO, "themes", "alpha", "layouts", "**",
                                              "*.json"), recursive=True))
        return {p: sha(p) for p in paths}

    def test_a_save_is_atomic_and_shows_up_on_the_glass(self):
        before = self.vendor_tree()
        path, soft = themes.save(self.obj, "Theme_28")
        self.assertEqual(soft, [], soft)
        self.assertTrue(path.endswith(".json"), path)
        self.assertFalse(os.path.exists(path + ".tmp"), "a .tmp survived the atomic replace")
        self.assertTrue(os.path.exists(path + ".bak"),
                        "the copy being overwritten left no backup")
        metrics = sensors.collect()
        vendor_img, vendor_notes = themes.draw(themes.load(self.rec["path"]), metrics, WHEN)
        yours_img, yours_notes = themes.draw(self.obj, metrics, WHEN)
        self.assertEqual(len(vendor_notes["boxes"]), len(yours_notes["boxes"]),
                         vendor_notes["missing"])
        delta = [(b[2][0] - a[2][0], b[2][1] - a[2][1])
                 for a, b in zip(vendor_notes["boxes"], yours_notes["boxes"])]
        self.assertEqual([d for d in delta if d != (0, 0)], [(20, 0)],
                         f"the label `{self.label}` did not move by the amount the model asked")
        moved = next(a for a, b in zip(vendor_notes["boxes"], yours_notes["boxes"])
                     if b[2][0] - a[2][0])
        self.assertEqual(moved[1], self.label)
        self.assertEqual(moved[0], self.target["type"])
        # and the vendor's own tree is exactly as it was
        self.assertEqual(self.vendor_tree(), before,
                         "a save wrote somewhere inside the copied library")

    def test_the_doors_a_person_uses_answer_with_the_copy(self):
        checked = fixtures.run(sys.executable, "-m", "xigmalcd", "--check-theme", "Theme_28")
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        self.assertIn("from your copy", checked.stdout.splitlines()[0], checked.stdout)
        listed = fixtures.run(sys.executable, "-m", "xigmalcd", "--list-themes")
        self.assertIn("from your copy", listed.stdout)
        self.assertIn("your copies", listed.stdout)

    def test_a_deleted_copy_puts_the_vendors_file_back_in_front(self):
        themes.save(self.obj, "Theme_28")
        themes.delete_user_theme("Theme_28")
        back = themes.resolve("Theme_28")
        self.assertFalse((back or {}).get("edited"), back)
        # which of the two vendor roots answers is the machine's, not the code's: a bench with the
        # .deb installed reads the copy under /usr/share, a clone reads the one in the checkout
        self.assertIn(themes.origin(back), ("checkout", "package"), themes.origin(back))
        after = fixtures.run(sys.executable, "-m", "xigmalcd", "--list-themes")
        self.assertNotIn("from your copy", after.stdout)
        self.assertIn("nothing saved yet", after.stdout, after.stdout)

    def test_a_file_with_nothing_to_draw_is_not_a_name_the_loop_can_be_told(self):
        """The writer has refused an empty layout since 0.6; the reader now does too.

        `themes.save` will not put down a file with an empty `osd.widget` list, but until
        2026-11-13 a file like that could still arrive by another door - a JSON dropped into
        `~/.config/xigmalcd/themes` by hand, a metrics body saved with the wrong name, a clip's
        sidecar - and `scan()` selected on the `ratio` field alone, so `resolve()` answered it.
        What happened next was measured on 2026-11-13 while fixing `debian/tests/smoke`: the
        file has no `osd` key at all, `layout.draw_theme` walks `obj["osd"]["widget"]`, and the
        loop raised `KeyError: 'osd'` on the frame that named it.  A name the panel could be
        told is a name the painter can paint, so the same rule is now asked at both doors, and
        printed by whichever one refuses.
        """
        os.makedirs(themes.user_root(), exist_ok=True)
        junk = os.path.join(themes.user_root(), "not_a_layout.json")
        with open(junk, "w", encoding="utf-8") as fh:
            json.dump({"id": "junk-id", "ratio": "1:1", "width": 480, "height": 480}, fh)
        pick, reject = themes.scan()
        self.assertNotIn("not_a_layout", [r["name"] for r in pick],
                         "a file with nothing to draw is still selectable, so the loop can be "
                         "pointed at it")
        here = [r for r in reject if r["name"] == "not_a_layout"]
        self.assertEqual(len(here), 1, "the file is not even listed as excluded: an invisible "
                                       "refusal is how a person ends up hunting for their typo")
        self.assertIn("osd", str(here[0].get("why")), here[0])
        self.assertIsNone(themes.resolve("not_a_layout"), "the drawer still answers the name")
        self.assertIsNone(themes.resolve("junk-id"), "and answering it by its `id`")
        self.assertNotIn("not_a_layout", themes.names())
        said = themes.why_not("not_a_layout")
        for needle in ("osd", "widget"):
            self.assertIn(needle, said, f"`why_not` does not say {needle!r}: {said}")
        sentence = "no `osd` with a `widget` list"
        for args in (("--check-theme", "not_a_layout"),
                     ("--theme", "not_a_layout", "--dry-run", "unused")):
            got = fixtures.run(sys.executable, "-m", "xigmalcd", *args)
            self.assertEqual(got.returncode, 2,
                             f"`xigmalcd {' '.join(args)}` did not refuse: exit "
                             f"{got.returncode}, stdout {got.stdout[:300]!r}")
            self.assertIn(sentence, got.stdout + got.stderr,
                          f"`{args[0]}` refused without naming the rule: "
                          f"{(got.stdout + got.stderr)[:400]}")
        listed = fixtures.run(sys.executable, "-m", "xigmalcd", "--list-themes")
        for needle in ("not_a_layout", sentence, "with nothing to draw"):
            self.assertIn(needle, listed.stdout,
                          f"--list-themes does not say {needle!r}: {listed.stdout[:400]}")

    def test_every_path_that_is_not_a_user_copy_is_refused_in_words(self):
        cases = (
            ("outside the user directory",
             lambda: themes.save(self.obj, "Theme_28",
                                 root=os.path.join(themes.SYSTEM_ROOT, "alpha"))),
            ("a generated theme's name", lambda: themes.save(self.obj, "gauge")),
            ("a path element", lambda: themes.save(self.obj, "../escape")),
            ("a nested name", lambda: themes.save(self.obj, "a/b")),
            ("no widgets to draw",
             lambda: themes.save({"width": 480, "height": 480, "osd": {"widget": []}}, "empty")),
            ("a two-element property",
             lambda: themes.save({"width": 480, "height": 480,
                                  "osd": {"widget": [{"type": "text", "id": "xigma-t",
                                                      "property": [{"x": 0, "y": 0},
                                                                   {"x": 1, "y": 1}]}]}},
                                 "two")))
        for what, call in cases:
            with self.subTest(refusal=what):
                with self.assertRaises(ValueError) as got:
                    call()
                self.assertTrue(str(got.exception), "a refusal with no sentence behind it")
        self.assertEqual(sha(self.rec["path"]), self.vendor_sha,
                         "the vendor's file changed while its copy was being argued about")


class Findings(unittest.TestCase):
    """One deliberately broken layout, and the words every one of its problems comes back with."""

    BROKEN = {"width": 480, "height": 480, "osd": {"widget": [
        {"type": "data", "id": "xigma-a", "property": [
            {"x": 600, "y": 10, "source": "Pump Flow", "fontFamily": "comic sans",
             "fontSize": 33, "textColor": "#ffffff",
             "time": "2026-01-01T00:00:00.000Z"}]},
        {"type": "data", "id": "xigma-a", "property": []},
        {"type": "data", "id": "xigma-a", "property": [
            {"x": 5, "y": 5, "source": "CPU Usage", "xigma": {"showIf": "Fan 9 Speed"}}]},
        {"type": "special", "id": "xigma-b", "property": [
            {"x": 10, "y": 10, "name": "mystery-thing", "fontSize": 26}]},
        # the two doors that place a pair, each missing the one key that makes its placement mean
        # something: `temp-values` has a pitch and no ring to size against, `fan-figures` has a
        # ring key it never reads and no pitch, so both figures would land on one point
        {"type": "special", "id": "xigma-d", "property": [
            {"x": 240, "y": 128, "width": 232, "name": "temp-values", "fontSize": 70}]},
        {"type": "special", "id": "xigma-e", "property": [
            {"x": 240, "y": 300, "name": "fan-figures", "fontSize": 20,
             "xigma": {"fitArc": {"cy": 158, "radius": 85, "width": 12,
                                  "angleStart": 45, "angleEnd": 315}}}]},
        {"type": "text", "id": "xigma-c", "property": [{"x": 10, "y": 10}]}]}}

    PHRASES = ("outside the 480x480 canvas", "has no entry in", "is not in layout.FONTS",
               "is outside the ten sizes", "rgba(r, g, b, a)", "repeats inside this theme",
               "has no drawing", "no `content`", "one-element list",
               "no ring to size its text against", "distance between their centres",
               "xigma.showIf names")

    def test_every_problem_this_fixture_carries_is_said_in_words(self):
        hard, soft = themes.validate(self.BROKEN)
        missing = [phrase for phrase in self.PHRASES
                   if not any(phrase in note for note in soft + hard)]
        self.assertEqual(missing, [], f"{len(soft)} soft and {len(hard)} hard findings, and "
                                      f"nothing said about: {missing}")
        self.assertEqual(len(soft), 12, soft)
        self.assertEqual(len(hard), 1, hard)

    def test_a_correct_export_carries_no_hard_finding(self):
        for name in sorted(themes.EXPORTS):
            with self.subTest(theme=name):
                hard, _soft = themes.validate(themes.export(name))
                self.assertEqual(hard, [], name)


class TheClockIsPartOfThePicture(unittest.TestCase):
    """Why every comparison above carries an instant."""

    def test_two_draws_a_second_apart_are_not_the_same_frame(self):
        import time
        first, _ = themes.draw(themes.export("clock"), {}, None)
        time.sleep(1.05)
        second, _ = themes.draw(themes.export("clock"), {}, None)
        drifted = fixtures.differ(first, second)[0]
        self.assertGreater(drifted, 0, "this theme has no clock in it any more, and the "
                                       "pinning below would be measuring nothing")

    def test_the_same_instant_twice_is_the_same_bytes(self):
        a, _ = themes.draw(themes.export("clock"), {}, WHEN)
        import time
        time.sleep(1.05)
        b, _ = themes.draw(themes.export("clock"), {}, WHEN)
        self.assertEqual(fixtures.differ(a, b), (0, 0),
                         "`themes.draw` is not reading the instant it is handed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
