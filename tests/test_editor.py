#!/usr/bin/env python3
"""The layout editor's model: what an edit is, what it owes back, and what it must never touch.

Ported from the editor-model and edit-cycle blocks of `tools/selftest.sh`'s GUI section.  No Qt is
used here on purpose: the claims are about the file model and the pixels, and the window is a shell
over both.  That split is itself one of the checks - if `edit.py` ever imports Qt, every number below
stops being a model fact and becomes something a broken window can excuse.

The strongest claim in this file is the one that is easy to lose by accident: **saving puts back what
it read**.  The keys each widget carries after a save are the keys the vendor's file carried, plus
`xigma` only where an extension key was set - an editor that rewrites the schema it does not
understand is an editor that corrupts files.  And the second is that the file on disk draws the frame
the pane was showing, byte for byte, so "what I saw is what the panel will get" is a measured fact.
"""
from __future__ import annotations

import ast
import copy
import os
import unittest
from PIL import ImageChops

from tests import fixtures

from xigmalcd import layout
from xigmalcd import themes
from xigmaui import edit as gui_edit

#: A run of spinbox keystrokes, and the distance they add up to.
KEYS, NUDGE = 20, 20

#: Values the row must refuse, and the words each refusal has to contain.  The last three are
#: structural rather than junk: a key this kind cannot carry, a coordinate off the canvas, and a
#: `special` drawing that does not exist.
JUNK_EDITS = (("x", 480, ""), ("x", "not a number", ""), ("textColor", "cerise", ""),
              ("bold", "yes", ""), ("fontSize", None, ""))


def px_differ(a, b) -> int:
    """Pixels where two frames disagree in any channel - the same count `themes.parity` reports,
    so an editor number and an export number mean the same thing."""
    return fixtures.differ(a, b)[0]


class ModelNeedsNoDisplay(unittest.TestCase):
    """The model is the part that can be held to a number, and that is only true without a display."""

    def test_edit_py_imports_nothing_from_qt(self):
        qt = [ln for ln in fixtures.read(os.path.join("xigmaui", "edit.py")).splitlines()
              if "PyQt" in ln]
        self.assertEqual(qt, [], "PyQt in this module would mean every claim in this file runs "
                                 "in the GUI tests instead, where a broken window can excuse a "
                                 "broken model")

    def test_the_row_may_only_offer_keys_the_painter_reads(self):
        pick, _reject = themes.scan()
        opened = [gui_edit.Editor.open_theme(r["name"]) for r in pick[:3]]
        generated = [gui_edit.Editor.open_theme(n) for n in sorted(themes.EXPORTS)]
        read, sub = themes.keys_read()
        census = themes.field_census()
        inert = set(census["keys"]) - set(read)
        kinds = sorted({w["type"] for e in opened + generated for w in e.widgets()})
        self.assertLessEqual(set(kinds), set(layout.KINDS), kinds)
        offered = {f for kind in kinds for f in gui_edit.field_names(kind)}
        self.assertLessEqual(offered, set(read), sorted(offered - set(read)))
        self.assertEqual(offered & inert, set(), sorted(offered & inert))
        ext = {f for kind in kinds for f in gui_edit.extension_fields(kind)}
        self.assertLessEqual(ext, set(sub), sorted(ext - set(sub)))
        self.assertTrue(all("showIf" in gui_edit.extension_fields(k) for k in kinds), kinds)

    def test_opening_layouts_writes_nothing(self):
        self.assertEqual(themes.user_copies(), [], themes.user_copies())
        pick, _reject = themes.scan()
        opened = [gui_edit.Editor.open_theme(r["name"]) for r in pick[:3]]
        generated = [gui_edit.Editor.open_theme(n) for n in sorted(themes.EXPORTS)]
        self.assertEqual(themes.user_copies(), [], "opening a layout wrote a copy")
        for e in generated:
            self.assertEqual(e.origin, "generated from render.py")
            self.assertFalse(e.path)
        for e in opened:
            self.assertIn(e.origin, ("checkout", "package", "your copy"), e.origin)
            self.assertFalse(e.dirty, "opening a layout made it dirty")

    def test_the_picture_comes_from_a_pinned_fixture_not_from_live_sensors(self):
        ed = gui_edit.Editor.open_theme("clock")
        line = ed.fixture_line()
        for want in ("CPU Temperature 57.0", "GPU Temperature 47.0", "2026-02-17"):
            self.assertIn(want, line, line)

    def test_the_shared_fixture_survives_being_handed_out(self):
        """The regression this guards against was real: `fixture()` returned `dict(FIXTURE)`, a
        shallow copy, and one punched-out key poisoned every later draw in the process - which moved
        two machines' answers on a census and looked like a rendering difference."""
        before = copy.deepcopy(gui_edit.FIXTURE)
        ed = gui_edit.Editor.open_theme("bars")
        body, _when = ed.fixture()
        body.setdefault("memory", {}).pop("total", None)
        ed.paint(*ed.fixture())
        self.assertEqual(gui_edit.FIXTURE, before,
                         "`fixture()` handed out something that shares structure with the module "
                         "dictionary")
        fresh = ast.parse(fixtures.read(os.path.join("xigmaui", "edit.py")))
        literal = next(n for n in ast.walk(fresh)
                       if isinstance(n, ast.Assign)
                       and getattr(n.targets[0], "id", "") == "FIXTURE")
        self.assertEqual(gui_edit.FIXTURE, ast.literal_eval(literal.value),
                         "the live fixture is no longer what the module's own literal says")


class AnEditMeasured(fixtures.FreshConfigRoot):
    """Twenty keystrokes, one undo step, one moved ink box, and a file that draws it back."""

    def setUp(self):
        super().setUp()
        self.ed = gui_edit.Editor.open_theme("Theme_28")
        self.base, self.notes0 = self.ed.paint(*self.ed.fixture())
        self.target = next(i for i, w in enumerate(self.ed.widgets())
                           if not (w.get("property") or [{}])[0].get("source")
                           and (w.get("property") or [{}])[0].get("content"))
        self.ed.select(self.target)
        self.x0 = int(self.ed.value("x"))

    def drive(self):
        for step in range(KEYS):
            ok, msg = self.ed.set("x", self.x0 + 1 + step, commit=(step == KEYS - 1))
            self.assertTrue(ok, (step, msg))

    def test_a_run_of_keystrokes_is_one_undo_step_that_moves_exactly_one_box(self):
        self.drive()
        self.assertEqual(self.ed.steps, 1, self.ed.steps)
        self.assertTrue(self.ed.dirty)
        after, notes1 = self.ed.paint(*self.ed.fixture())
        shift = [(int(b[2][0]) - int(a[2][0]), int(b[2][1]) - int(a[2][1]))
                 for a, b in zip(self.notes0["boxes"], notes1["boxes"])]
        self.assertEqual(sum(1 for s in shift if s == (NUDGE, 0)), 1, shift)
        self.assertEqual(sum(1 for s in shift if s == (0, 0)), len(shift) - 1, shift)
        self.assertGreater(px_differ(self.base, after), 200)

    def test_saving_puts_back_every_key_it_read(self):
        self.drive()
        path, warnings = self.ed.save()
        self.assertTrue(path)
        self.assertEqual(warnings, [], warnings)
        keys_before = [sorted((w.get("property") or [{}])[0]) for w in self.ed.widgets()]
        keys_after = [sorted((w.get("property") or [{}])[0])
                      for w in themes.load(path)["osd"]["widget"]]
        self.assertEqual(keys_before, keys_after,
                         [(i, b, a) for i, (b, a) in enumerate(zip(keys_before, keys_after))
                          if b != a][:3])
        _read, _sub = themes.keys_read()
        inert = set(themes.field_census()["keys"]) - set(_read)
        for i, keys in enumerate(keys_before):
            lost = [k for k in keys if k in inert and k not in keys_after[i]]
            self.assertEqual(lost, [], f"row {i} lost the inert vendor keys {lost}")

    def test_the_saved_file_draws_the_frame_the_pane_was_showing(self):
        self.drive()
        path, _warnings = self.ed.save()
        after, _notes = self.ed.paint(*self.ed.fixture())
        again = gui_edit.Editor.open_theme("Theme_28")
        self.assertEqual(again.origin, "your copy", again.origin)
        self.assertFalse(again.dirty)
        self.assertEqual(int(again.widgets()[self.target]["property"][0]["x"]), self.x0 + NUDGE)
        lit, _ = again.paint(*again.fixture())
        self.assertEqual(lit.tobytes(), after.tobytes(),
                         "the file on disk does not draw what the pane drew")

    def test_undo_returns_the_first_frame_byte_for_byte_and_dirty_says_so(self):
        self.drive()
        self.ed.save()
        self.assertFalse(self.ed.dirty, "save did not clear dirty")
        self.assertTrue(self.ed.undo())
        self.assertFalse(self.ed.undo(), "a second undo should find nothing to undo")
        back, notes2 = self.ed.paint(*self.ed.fixture())
        self.assertEqual(back.tobytes(), self.base.tobytes())
        self.assertEqual(notes2["boxes"], self.notes0["boxes"])
        self.assertTrue(self.ed.dirty, "undoing an edit that is saved on disk must say so")

    def test_revert_removes_the_copy_and_the_vendor_picture_comes_back(self):
        self.drive()
        self.ed.save()
        again = gui_edit.Editor.open_theme("Theme_28")
        self.assertTrue(again.revert())
        self.assertEqual(themes.origin(themes.resolve("Theme_28")), "checkout")
        self.assertFalse(again.dirty, "revert wrote the baseline back: nothing is outstanding")
        self.assertEqual(themes.user_copies(), [], "the copy is still there")
        gone = gui_edit.Editor.open_theme("Theme_28")
        self.assertEqual(gone.paint(*gone.fixture())[0].tobytes(), self.base.tobytes())

    def test_a_colour_typed_one_way_is_stored_the_way_the_library_writes_it(self):
        ok, note = self.ed.set("textColor", "#ff4040")
        self.assertTrue(ok, note)
        self.assertEqual(note, "stored as rgba(255, 64, 64, 1)", note)
        self.assertEqual(layout.rgba(self.ed.value("textColor")), (255, 64, 64, 255))
        tinted, _ = self.ed.paint(*self.ed.fixture())
        self.assertGreater(px_differ(self.base, tinted), 100)
        self.assertTrue(self.ed.undo())
        self.assertEqual(self.ed.paint(*self.ed.fixture())[0].tobytes(), self.base.tobytes())

    def test_every_refused_value_is_refused_in_words_and_moves_nothing(self):
        steps, dirty = self.ed.steps, self.ed.dirty
        for field, junk, _want in JUNK_EDITS:
            with self.subTest(field=field, value=repr(junk)):
                ok, note = self.ed.set(field, junk)
                self.assertFalse(ok, f"{field}={junk!r} was accepted")
                self.assertTrue(note, "a refusal with no sentence behind it")
                self.assertEqual(self.ed.steps, steps, "a refusal took an undo step")
                self.assertEqual(self.ed.dirty, dirty, "a refusal changed the document's state")
        after, _notes = self.ed.paint(*self.ed.fixture())
        self.assertEqual(after.tobytes(), self.base.tobytes(), "a refused edit moved pixels")

    def test_a_key_the_row_kind_cannot_carry_is_refused_rather_than_written(self):
        ok, note = self.ed.set("arcPaint", "vendor")
        self.assertFalse(ok)
        self.assertIn("does not carry", note, note)

    def test_a_coordinate_off_the_canvas_is_refused_and_an_unknown_drawing_names_the_choices(self):
        bars = gui_edit.Editor.open_theme("bars")
        bars.select(next(i for i, w in enumerate(bars.widgets()) if w["type"] == "bar"))
        ok, note = bars.set("x", -5)
        self.assertFalse(ok, note)
        self.assertIn("canvas", note, note)
        special = gui_edit.Editor.open_theme("clock")
        special.select(next(i for i, w in enumerate(special.widgets()) if w["type"] == "special"))
        ok, note = special.set("name", "no-such-drawing")
        self.assertFalse(ok, note)
        self.assertIn("takes one of", note, note)
        self.assertEqual((special.steps, special.dirty), (0, False),
                         "six refused writes against that row left a step behind")


class Rows(unittest.TestCase):
    """Adding, removing and reordering rows - the envelope first, then the pixels."""

    def test_opening_a_generated_theme_and_adding_every_kind_leaves_one_undo_step(self):
        for kind in gui_edit.kinds():
            with self.subTest(kind=kind):
                ed = gui_edit.Editor.open_theme(sorted(themes.EXPORTS)[0])
                before, _ = ed.paint(*ed.fixture())
                ok, note = ed.add_widget(kind, name=next(iter(themes.SPECIALS), ""))
                if not ok:
                    self.assertIn(kind, ("special",), note)
                    continue
                self.assertEqual(ed.steps, 1, note)
                row = ed.widgets()[-1]
                self.assertEqual(sorted(row), sorted(ed.widgets()[0]) if ed.widgets() else sorted(row))
                self.assertEqual(len(row["property"]), 1)
                self.assertTrue(str(row["id"]).startswith("xigma-"), row["id"])
                self.assertTrue(ed.undo())
                after, _ = ed.paint(*ed.fixture())
                self.assertEqual(after.tobytes(), before.tobytes(),
                                 "undo did not restore the frame the added row changed")
                self.assertEqual(themes.user_copies(), [], "adding a row wrote a file")

    def test_reordering_two_rows_preserves_ids_and_layer_indexes(self):
        ed = gui_edit.Editor.open_theme("Theme_28")
        ids = [w["id"] for w in ed.widgets()]
        layers = [w.get("layerIndex") for w in ed.widgets()]
        ok, note = ed.move_widget(1, index=1)
        self.assertTrue(ok, note)
        now, now_ids = ed.widgets(), [w["id"] for w in ed.widgets()]
        self.assertEqual(sorted(now_ids), sorted(ids),
                         "a reorder invented or lost a row")
        self.assertEqual(now_ids[1:3], list(reversed(ids[1:3])), note)
        self.assertEqual(now_ids[:1] + now_ids[3:], ids[:1] + ids[3:],
                         "the swap moved a row nobody asked it to")
        self.assertEqual(sorted(w.get("layerIndex") for w in now), sorted(layers or []),
                         "the swap rewrote the vendor's layer indexes as well as the order")
        self.assertEqual(ed.steps, 1, "a swap is one undo step")
        self.assertTrue(ed.undo())
        self.assertEqual([w["id"] for w in ed.widgets()], ids,
                         "undo did not put the draw order back")


if __name__ == "__main__":
    unittest.main(verbosity=2)
