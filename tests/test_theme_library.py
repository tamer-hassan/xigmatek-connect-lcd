#!/usr/bin/env python3
"""The copied vendor library: which layouts this canvas can select, and what goes under each.

Ported from the library-selection and pairing halves of `tools/selftest.sh`'s vendor-theme section.
The manifest byte checks moved out to `tools/verify_manifest.py`; what stays here is behaviour.

Two rules are worth their lines:

* the canvas decision comes from the file's **ratio field**, not from its path or its name - the
  four 320x240 layouts are refused on that field and still answer with the reason in words;
* `themes.pair` is the one place that reads `background.mediaFile` as an answer, so the window and
  `--list-themes` cannot disagree with each other or with the file.  One clip per layout, no two
  layouts sharing a clip, and a refusal - not an empty string - for names the library has no file
  for, which is what the window prints.

The five themes drawn from `render.py` carry no such key, because a generated layout *is* the
picture and has nothing under it.  Their backdrops are therefore derived here, from the published
pictures' own names, rather than trusted from the constant that encodes them.
"""
from __future__ import annotations

import glob
import os
import unittest

from tests import fixtures

from xigmalcd import layout
from xigmalcd import render
from xigmalcd import themes

#: What the 27 copied layouts divide into on this canvas.  File facts: the same 27 files are in
#: the package, so these counts are not a machine's state.
PICKABLE, REFUSED = 23, 4

#: The sources the library asks for, counted off the 23 pickable layouts.  Counted by the same code
#: the window uses, pinned so a changed library or a changed reader is a diff someone notices.
SOURCES_USED = {"CPU Temperature": 17, "CPU Usage": 15, "Time": 11, "Pump Speed": 9,
                "GPU Usage": 6, "GPU Temperature": 3, "CPU Frequency": 2}

#: How many of the 23 need nothing this program has no reading for, and the only gap the rest have.
CLEAR, ONLY_GAP = 14, {"Pump Speed"}


class Selection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pick, cls.reject = themes.scan()

    def test_the_split_is_by_the_ratio_field_not_by_the_name(self):
        self.assertEqual((len(self.pick), len(self.reject)), (PICKABLE, REFUSED))
        self.assertTrue(all(r["ratio"] == "1:1" for r in self.pick),
                        [r["ratio"] for r in self.pick])
        self.assertTrue(all(r["ratio"] != "1:1" for r in self.reject),
                        [r["ratio"] for r in self.reject])
        self.assertEqual({(r["w"], r["h"]) for r in self.reject}, {(320, 240)})

    def test_the_names_are_unique_whatever_case_they_arrive_in(self):
        self.assertEqual(len({r["name"].lower() for r in self.pick + self.reject}), 27,
                         "a name collides case-insensitively")
        self.assertEqual(len({r["id"] for r in self.pick}), PICKABLE,
                         "two pickable layouts share an id")

    def test_resolution_accepts_the_stem_any_case_and_the_numeric_id(self):
        self.assertEqual(themes.resolve("theme_07")["name"], "Theme_07")
        self.assertEqual(themes.resolve("1757491588804")["name"], "Theme_07")

    def test_what_cannot_be_drawn_answers_with_a_reason(self):
        self.assertIsNone(themes.resolve(self.reject[0]["name"]))
        self.assertIn("ratio 4:3", themes.why_not(self.reject[0]["name"]))
        self.assertIsNone(themes.resolve("gauge"))
        self.assertIn("five", themes.why_not("gauge"),
                      "one of the five generated themes is not a file, and the reason should say so")

    def test_the_sources_the_library_asks_for_are_the_ones_this_program_has(self):
        used = themes.sources_used(self.pick)
        self.assertEqual(used, SOURCES_USED)
        answerable = set(themes.source_names())
        gaps = {}
        for rec in self.pick:
            body = themes.load(rec["path"])
            sources = {p.get("source") for w in (body.get("osd") or {}).get("widget") or []
                       for p in w.get("property") or []}
            gaps[rec["name"]] = {s for s in sources if s} - answerable
        clear = sorted(name for name, gap in gaps.items() if not gap)
        self.assertEqual(len(clear), CLEAR, clear)
        for name, gap in gaps.items():
            if gap:
                self.assertEqual(gap, ONLY_GAP,
                                 f"{name} asks for {sorted(gap)}: the library's only unanswered "
                                 "source used to be Pump Speed, which has never been measured "
                                 "on this box")


class Pairing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pick, cls.reject = themes.scan()

    def test_every_selectable_layout_names_exactly_one_clip_and_no_two_name_the_same(self):
        named: dict = {}
        for rec in self.pick:
            background = str(rec["background"] or "")
            self.assertTrue(background, (rec["name"], "a selectable layout declares no background"))
            named.setdefault(background.rsplit("/", 1)[-1].lower(), []).append(rec["name"])
        shared = {k: v for k, v in named.items() if len(v) > 1}
        self.assertEqual(shared, {}, "two selectable layouts name the same clip, so the "
                                     "pairing stops being a function")
        self.assertEqual(len(named), PICKABLE)

    def test_pair_answers_for_each_by_name(self):
        for rec in self.pick:
            with self.subTest(layout=rec["name"]):
                got, why = themes.pair(rec["name"])
                self.assertEqual(got, rec["background"].rsplit("/", 1)[-1])
                self.assertFalse(why, why)

    def test_a_canvas_refused_layout_can_answer_a_clip_for_the_window_to_open(self):
        """The window must not be able to show what `--theme` will not draw."""
        for rec in self.reject:
            with self.subTest(layout=rec["name"]):
                self.assertFalse(themes.pair(rec["name"])[0])

    def test_a_name_the_library_has_no_file_for_answers_with_a_reason(self):
        clip, why = themes.pair("no-such-layout")
        self.assertFalse(clip)
        self.assertTrue(why, "an empty answer is what a window would have to print as nothing")

    def test_the_five_generated_themes_pair_with_their_own_published_pictures_backdrop(self):
        """`CODE_CLIPS` is a claim about five themes that have no `background.mediaFile`, so it is
        re-derived from the README's own pictures: each is named `<theme>-<clip>.mp4`, and a
        candidate counts only when its clip part resolves as a clip this box holds.  That is how the
        amber-ink figure `alpha-Theme_25-amber.mp4` falls out on its own rather than being excepted
        by hand - `find_media` answers with a path whether or not the file exists, which is how a
        missing clip gets reported as the name it was asked for, so the test is the file."""
        from xigmalcd.main import find_media
        published: dict = {}
        for video in sorted(glob.glob(os.path.join(fixtures.REPO, "docs", "videos", "*.mp4"))):
            stem = os.path.basename(video)[:-4]
            theme, sep, clip = stem.partition("-")
            if not sep or theme not in render.THEMES:
                continue
            if not os.path.isfile(find_media(clip + ".mp4")):
                continue
            published.setdefault(theme, []).append(clip + ".mp4")
        self.assertEqual({k: len(v) for k, v in published.items()},
                         {k: 1 for k in published}, published)
        self.assertEqual(set(published), set(render.THEMES),
                         "a theme drawn here has no published picture naming a backdrop, so "
                         "its pairing would have to be invented")
        self.assertEqual({k: v[0] for k, v in published.items()}, themes.CODE_CLIPS,
                         "themes.CODE_CLIPS is not the backdrop set the README's own pictures "
                         "are composited over")

    def test_pair_answers_for_the_five_generated_names_too(self):
        for name in sorted(themes.EXPORTS):
            with self.subTest(theme=name):
                got, why = themes.pair(name)
                self.assertEqual(got, themes.CODE_CLIPS.get(name))
                self.assertFalse(why, why)


class Shape(unittest.TestCase):
    """The library as the package installs it: 27 layouts, and one row per kind of file."""

    def test_every_pickable_layout_loads_and_has_the_envelope_a_layout_needs(self):
        pick, _reject = themes.scan()
        for rec in pick:
            with self.subTest(layout=rec["name"]):
                body = themes.load(rec["path"])
                self.assertIn("osd", body)
                self.assertTrue(body["osd"].get("widget"), rec["name"])
                # the same keys `layout.draw_theme` reads, from that module rather than a list
                self.assertTrue(hasattr(layout, "draw_theme"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
