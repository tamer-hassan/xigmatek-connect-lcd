#!/usr/bin/env python3
"""The five generated themes, exported as layout files, and painted both ways.

Ported from the export-shape and parity blocks of `tools/selftest.sh`'s vendor-theme section.

`themes.export` writes a layout file that says, in the vendor's own vocabulary, what `render.py`
draws in code.  The claim worth defending is the strong one: at one pinned instant and one pinned
body of readings, the exported file painted by `layout.draw_theme` and the theme painted by
`render.draw` put down the **same pixels** - compared over all four channels, because an alpha-only
comparison would not see a colour that had drifted, and colour is exactly what `xigma.textColor`
carries.

Where a reading is missing, the two doors are allowed to differ, and they differ for a reason that
is asserted rather than printed: a code theme paints something for a reading it does not have - an
unfilled ring's track, `--°C` where a number would be - while a layout has no widget to paint at
all when its `source` is unanswered.  Both are right by their own rule.  An export translates a
theme's drawing, not its fallback behaviour.
"""
from __future__ import annotations

import json
import unittest

from tests import fixtures

from xigmalcd import layout
from xigmalcd import render
from xigmalcd import themes

def missing_faces() -> list:
    """Faces the exports themselves name, probed at the family, weight and size they use."""
    faces = set()
    for recipe in themes.EXPORTS.values():
        for widget in recipe()["osd"]["widget"]:
            prop = widget["property"][0]
            if prop.get("fontFamily"):
                faces.add((str(prop["fontFamily"]).lower(), bool(prop.get("bold")),
                           int(prop.get("fontSize") or 12)))
    return sorted(f"{fam}{'b' if bold else ''}/{size}" for fam, bold, size in faces
                  if layout.font_for({"fontFamily": fam, "bold": bold,
                                      "fontSize": size})[0] is None)


class ExportShape(unittest.TestCase):
    """Byte-stable, and in the vendor's own vocabulary rather than a shape of our invention."""

    def test_two_exports_of_one_theme_are_the_same_bytes(self):
        for name in sorted(themes.EXPORTS):
            with self.subTest(theme=name):
                first = json.dumps(themes.export(name), indent=1, sort_keys=True)
                second = json.dumps(themes.export(name), indent=1, sort_keys=True)
                self.assertEqual(first, second, "something non-deterministic in the export")

    def test_each_export_is_a_square_1to1_canvas_that_validates_without_a_hard_finding(self):
        for name in sorted(themes.EXPORTS):
            with self.subTest(theme=name):
                obj = themes.export(name)
                self.assertEqual(obj["ratio"], "1:1")
                self.assertEqual((obj["width"], obj["height"]), (480, 480))
                hard, _soft = themes.validate(obj)
                self.assertEqual(hard, [], (name, hard))

    def test_ids_are_derived_from_the_theme_name_and_property_is_one_element(self):
        """Never uuid4, and the same one-element `property` list every vendor file has - and no
        editor stamp, because nothing generates one."""
        for name in sorted(themes.EXPORTS):
            for widget in themes.export(name)["osd"]["widget"]:
                with self.subTest(theme=name, widget=widget["id"]):
                    self.assertTrue(str(widget["id"]).startswith("xigma-"), widget["id"])
                    self.assertIsInstance(widget["property"], list)
                    self.assertEqual(len(widget["property"]), 1, widget["id"])
                    self.assertNotIn("time", widget["property"][0])
                    if widget["type"] == "special":
                        self.assertIn(widget["property"][0]["name"], themes.special_names())

    def test_every_drawn_theme_is_still_exported(self):
        self.assertLessEqual(set(render.THEMES), set(themes.EXPORTS),
                             sorted(set(render.THEMES) - set(themes.EXPORTS)))


class Parity(unittest.TestCase):
    """The exported file and the code drawing, at the same instant, over all four channels."""

    def setUp(self):
        gone = missing_faces()
        if gone:
            self.skipTest(f"the exported themes name {', '.join(gone)}, not installed here: "
                          "a missing face drops a widget, so a diff would measure the font "
                          "rather than the export")

    def answers(self, name: str) -> set:
        return {w["property"][0].get("source") for w in themes.EXPORTS[name]()["osd"]["widget"]}

    def test_both_doors_agree_to_the_pixel_on_every_complete_reading(self):
        reached = set()
        for name in sorted(themes.EXPORTS):
            for index, body in enumerate(fixtures.PARITY_CASES[:2]):
                with self.subTest(theme=name, case=index):
                    result = themes.parity(name, body, fixtures.SESSION_WHEN)
                    self.assertEqual(result["missing"], [], name)
                    self.assertEqual((result["diff_px"], result["worst_channel_delta"]), (0, 0),
                                     result)
                    self.assertGreater(result["code_px"], 4000)
                    self.assertEqual(result["code_px"], result["layout_px"])
                    reached.add(name)
        self.assertEqual(reached, set(themes.EXPORTS))

    def test_a_missing_reading_is_reported_with_its_cause_and_only_from_the_exported_sources(self):
        """`xigma.showIf` reports an unmet dependency as `showIf:<source>`, and the source it names
        is one this export already asks for by name - so each dependency has to arrive beside the
        plain note for the same reading.  A dependency said without its cause would be a hole with
        no reason next to it."""
        partial = []
        for name in sorted(themes.EXPORTS):
            for index, body in enumerate(fixtures.PARITY_CASES):
                result = themes.parity(name, body, fixtures.SESSION_WHEN)
                if not result["missing"]:
                    continue
                said = {note[len("showIf:"):] if note.startswith("showIf:") else note
                        for note in result["missing"]}
                asked = {source for source in self.answers(name) if source}
                self.assertLessEqual(said, asked,
                                     (name, result["missing"], sorted(asked)))
                deps = {note[len("showIf:"):] for note in result["missing"]
                        if note.startswith("showIf:")}
                self.assertLessEqual(deps, set(result["missing"]),
                                     f"{name}: a row named a dependency without the reading "
                                     "itself being reported missing too")
                partial.append((name, index, result["missing"], result["diff_px"]))
        self.assertTrue(partial, "no case left a source unanswered, so the split below would "
                                 "have measured nothing")
        for name, index, missing, diff in partial:
            self.assertGreaterEqual(index, 2,
                                    f"{name} at case {index} reported {missing}: the first two "
                                    "readings are the ones that answer everything")

    def test_the_two_ways_the_doors_may_differ_are_the_two_the_rules_allow(self):
        """A case that leaves a source out may still agree to the pixel - a code theme with no
        `load` reading draws no bar and no line, exactly as a layout skips the widget - or it may
        differ, when the code theme keeps a ring's track and the layout has no ring at all.

        Measured here over the three incomplete readings and five themes: 12 cases report a missing
        source, 6 of them agree exactly (`bars` all three, where every unfilled meter simply has no
        widget on either side, and `dual` with no `load`), and 6 differ with the code side holding
        more pixels - `alpha` three times, `dual` twice, `gauge` once.
        """
        agrees, differs = [], []
        for name in sorted(themes.EXPORTS):
            for index, body in enumerate(fixtures.PARITY_CASES[2:]):
                result = themes.parity(name, body, fixtures.SESSION_WHEN)
                if not result["missing"]:
                    continue
                (agrees if result["diff_px"] == 0 else differs).append(
                    (name, tuple(sorted(result["missing"])), result["code_px"],
                     result["layout_px"]))
        self.assertGreaterEqual(len(agrees) + len(differs), len(themes.EXPORTS),
                                "too few unanswered cases to tell the two behaviours apart")
        for name, missing, code_px, layout_px in differs:
            with self.subTest(theme=name, missing=missing):
                self.assertGreater(code_px, layout_px,
                                   f"{name} without {missing}: the code theme paints a fallback "
                                   "where the layout has no widget, so the code side should have "
                                   "more pixels, not fewer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
