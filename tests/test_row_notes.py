#!/usr/bin/env python3
"""What a row paints, and what the two doors answer when a file spells something the painter cannot apply.

Ported from three blocks of `tools/selftest.sh`'s GUI section - the row-note line, the `format`
sweep, and the family-name fold.  They share one rule, which is the rule this repository runs on
generally: **the model takes the painter's side, and proves it by drawing.**

* The note line under the editor's rows says what the row paints.  A second implementation of the
  drawing would be a thing that can drift, so the claim is checked the way every other pixel claim
  here is: draw the file, then draw a copy of it with that one row replaced by a literal `text`
  widget whose `content` is the string the model named, and require the two frames to be
  byte-identical.  A row the model says paints no line must be a row the painter skipped, and the
  reason the model gives must be a reason the painter's own notes give;
* a `format` the value cannot be dressed in is refused **on the way in** (this repo's rule: a write
  that cannot be drawn is said, not done) and survived **on the way out** - a file that already
  carries one is reported in the notes and skipped, not raised through the frame loop and not taken
  out along with the rest of the frame.  Which candidates fail is not a list kept here: the check
  asks the painter's own door whether it raises, and the model has to take the same side on each one;
* a family the file spells differently than the vocabulary does (`Arial` in the vendor's files,
  `arial` in `layout.FONTS`) folds, because `layout.font_for` folds - and what makes the fold safe
  is a pixel count of zero, not an argument.  Nothing else folds: a source's case is part of its
  name, and the painter matches sources exactly.

Two kinds of count live in the note-line check.  What the files decide - rows, layouts, which
sources appear - is the same on every machine.  What a **face** decides is not: a row whose family
resolves to no file paints nothing, and CI's runner ships no CJK face, so the painted / twin /
skipped counts differ between machines and only their *relations* are asserted here.
"""
from __future__ import annotations

import copy
import re
import unittest

from tests import fixtures

from xigmalcd import layout, render, themes
from xigmaui import edit as gui_edit

#: Candidate `xigma.format` spellings, chosen to cover the shapes a reader reaches for: printf
#: styles that work, printf styles that raise, and the `str.format` spellings this field does not
#: take.  Nothing about the list says which side each lands on - the check asks the painter.
FORMAT_CANDIDATES = ("%q", "%d %d", "{}", "{:,.0f}", "%.1f", "%s", "{0}", "%A %d %B %Y", "")

#: A two-row layout, hand-built, whose second row is given a format the painter cannot apply.  No
#: shipped file carries one, because the editor refuses to write it - so the survival half of the
#: rule would otherwise never be exercised.
HOLE_ROWS = ({"id": "check-hold-a", "type": "data",
              "property": [{"x": 10, "y": 10, "source": "CPU Temperature",
                            "fontFamily": "dejavu", "fontSize": 20,
                            "textColor": "rgba(255, 255, 255, 1)"}]},
             {"id": "check-hold-b", "type": "data",
              "property": [{"x": 10, "y": 100, "source": "GPU Temperature",
                            "fontFamily": "dejavu", "fontSize": 20,
                            "textColor": "rgba(255, 255, 255, 1)"}]})


def all_editors() -> list:
    return ([gui_edit.Editor(themes.export(name), origin="check", name=name)
             for name in sorted(themes.EXPORTS)]
            + [gui_edit.Editor.open_theme(rec["name"]) for rec in themes.scan()[0]])


def frame_with(props: list) -> dict:
    return {"width": render.W, "height": render.H,
            "osd": {"widget": [dict(row, property=[copy.deepcopy(p)])
                               for row, p in zip(HOLE_ROWS, props)]}}


class WhatARowPaints(unittest.TestCase):
    """The note line, proved by painting rather than by agreement between two pieces of code."""

    @classmethod
    def setUpClass(cls):
        cls.editors = all_editors()

    def test_every_line_the_model_names_is_the_line_the_painter_drew(self):
        rows = twins = skipped = caveats = 0
        reasons, failures = {}, []
        for editor in self.editors:
            base, notes = editor.paint(*editor.fixture())
            drawn = {box[3] for box in (notes.get("boxes") or [])}
            widgets = editor.obj["osd"]["widget"]
            for index, widget in enumerate(editor.widgets()):
                if str(widget.get("type") or "") not in ("text", "data"):
                    continue
                rows += 1
                editor.select(index)
                line, why = editor.drawn_text()
                if line is None:
                    skipped += 1
                    self.assertTrue(why, f"{editor.name} row {index}: a row that paints nothing "
                                         "has to say why")
                    self.assertNotIn(index, drawn,
                                     f"{editor.name} row {index}: the model says no line and the "
                                     f"painter drew one ({why})")
                    key = why.split("`")[1] if "`" in why else why[:20]
                    reasons[key] = reasons.get(key, 0) + 1
                    if "showIf" in why:
                        self.assertTrue(any(str(missing).startswith("showIf:")
                                            for missing in notes.get("missing") or []),
                                        f"{editor.name} row {index}: the model blamed a dependency "
                                        f"the painter never reported: {notes.get('missing')}")
                    continue
                if why:
                    caveats += 1
                    self.assertIn(str((widget.get("property") or [{}])[0].get("source")),
                                  {str(gap) for gap in notes.get("gaps") or []},
                                  f"{editor.name} row {index}: a caveat the painter does not share")
                props = dict((widget.get("property") or [{}])[0])
                props.pop("source", None)
                props["content"] = line
                widgets[index] = {**widget, "type": "text", "property": [props]}
                try:
                    twin, _notes = editor.paint(*editor.fixture())
                finally:
                    widgets[index] = widget
                if twin.tobytes() == base.tobytes():
                    twins += 1
                else:
                    differing = sum(1 for a, b in zip(base.tobytes(), twin.tobytes()) if a != b)
                    failures.append((editor.name, index, repr(line)[:36], differing))
        self.assertGreater(rows, 100, f"{rows} `text`/`data` rows across {len(self.editors)} "
                                      "layouts: the corpus moved, and the claim needs re-reading")
        self.assertFalse(failures, f"{len(failures)} rows whose literal-`text` twin is not the same "
                                   f"picture: {failures[:4]}")
        self.assertEqual(twins + skipped, rows,
                         f"{twins} twins and {skipped} skips of {rows} rows: a row answered neither "
                         "way")
        self.assertGreater(twins, 40, f"{twins} rows paint a line, so the twin half of the rule is "
                                      "barely exercised")
        self.assertGreater(skipped, 0,
                           f"nothing was skipped: the reasons {sorted(reasons)} are the other half "
                           "of the sentence")
        self.assertTrue(reasons, "a skipped row named no reason")
        # the census docs/gui.md quotes, printed rather than pinned: rows, twins, skips and the
        # reason each skip was blamed on.  A figure that only a run can reprint is a figure the
        # page can name the command for.
        print(f"  row census: {rows} `text`/`data` rows over {len(self.editors)} layouts; "
              f"{twins} twins, {skipped} skipped, {caveats} caveats; reasons: "
              + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items())))
        # The same census one level up: which `source` names the layouts in this program ask
        # for, and how many of them only **our own** generated exports ask.  docs/usage.md and
        # docs/limits.md quote a figure from this line, which is why the line exists: the last
        # time the number was retyped by hand it had already moved (the disk names went from
        # "asked by nothing" to "asked by `bars`" inside one commit).
        asked: dict = {}
        for editor in self.editors:
            for widget in editor.widgets():
                src = (widget.get("property") or [{}])[0].get("source")
                if src:
                    asked.setdefault(src, set()).add(editor.name)
        generated = {e.name for e in self.editors if getattr(e, "origin", None) == "check"}
        self.assertGreaterEqual(len(generated), 4,
                                f"only {sorted(generated)} of these editors are marked as "
                                "generated exports: the split below would be counting nothing")
        ours = sorted(name for name, who in asked.items() if who <= generated)
        print(f"  source census: {len(asked)} distinct `source` values over "
              f"{len(self.editors)} layouts; {len(ours)} asked only by a generated export: "
              + ", ".join(ours))
        # ...and the two sets docs/theme-editor.md counts beside that one: source *rows*
        # rather than names, and the `content` literals a layout prints that are not readings.
        source_rows = 0
        literals: set = set()
        literal_rows = 0
        for editor in self.editors:
            for widget in editor.widgets():
                props = widget.get("property") or [{}]
                src = props[0].get("source")
                txt = props[0].get("content")
                if src:
                    source_rows += 1
                if txt and not src:
                    literals.add(str(txt))
                    literal_rows += 1
        print(f"  name census: {source_rows} source rows; {len(literals)} distinct "
              f"`content` literals over {literal_rows} rows; "
              f"{len(set(asked) | literals)} names in the union, "
              f"{source_rows + literal_rows} rows carrying at least one")


class AFormatBothDoors(unittest.TestCase):
    """A format the value cannot be dressed in: refused on the way in, survived on the way out."""

    def setUp(self):
        self.editor = next(e for e in all_editors() if e.name == "bars")
        row = next(i for i, widget in enumerate(self.editor.widgets())
                   if str(widget.get("type") or "") == "data"
                   and (widget.get("property") or [{}])[0].get("source") == "Used RAM")
        self.editor.select(row)
        self.source = self.editor.prop()["source"]
        self.probe = themes.values(*self.editor.fixture())[0][self.source]

    def test_the_model_takes_the_painters_side_on_every_spelling(self):
        agreed, refused, accepted = [], [], []
        for candidate in FORMAT_CANDIDATES:
            raises = True
            try:
                layout.text_for(self.source, self.probe, candidate)
                raises = False
            except Exception:
                pass
            was_dirty, was_steps = self.editor.dirty, self.editor.steps
            ok, note = self.editor.set("format", candidate)
            with self.subTest(format=candidate):
                self.assertEqual(ok, not raises,
                                 f"{candidate!r}: the model and the painter disagree about one "
                                 f"format ({ok}, {raises}) - a row that writes what the drawing "
                                 "cannot apply is the bug this refuses to be")
                agreed.append((candidate, "paints" if not raises else "refused"))
                (accepted if ok else refused).append(candidate)
                if raises:
                    self.assertTrue(note and candidate in note,
                                    "a refusal has to name the format it refused")
                    # a refusal changes nothing: `dirty` and the undo count are read back as they
                    # were before *this* attempt, not as at the start of the sweep - an earlier
                    # candidate that was accepted is a real change the row keeps
                    self.assertEqual((self.editor.dirty, self.editor.steps), (was_dirty, was_steps),
                                     "a refused format moved the file anyway")
                    if candidate.startswith("{"):
                        # the shape people reach for is `str.format`'s, so refusing `{:,.0f}` has
                        # two jobs: say no, and point at the spelling this field takes
                        offered = re.search(r"already implied: `([^`]*)` works", note)
                        if offered:
                            ok2, note2 = self.editor.set("format", offered.group(1))
                            self.assertTrue(ok2, f"the spelling a refusal points at "
                                                 f"({offered.group(1)!r}) does not pass the refusal "
                                                 f"it came from: {note2}")
                            self.assertTrue(self.editor.undo(), "the probe left the row changed")
                            self.assertEqual((self.editor.dirty, self.editor.steps),
                                             (was_dirty, was_steps),
                                             "putting the probe back did not return the row to "
                                             "where it was")
                        else:
                            self.assertIn("not `str.format`", note,
                                          "a brace-style refusal either fixes the reader's "
                                          "spelling or says why it cannot")
        self.assertEqual(len(agreed), len(FORMAT_CANDIDATES))
        self.assertTrue(refused, "no spelling was refused, so the refusal's sentences are not being "
                                 "read by anyone")
        self.assertTrue(accepted, "every spelling was refused, so this field cannot be set at all")

    def test_a_file_that_already_carries_one_is_said_and_skipped_not_raised(self):
        clean_props = [copy.deepcopy(row["property"][0]) for row in HOLE_ROWS]
        clean, clean_notes = themes.draw(frame_with(clean_props), *self.editor.fixture())
        holed = dict(clean_props[1])
        holed["xigma"] = {"format": "%q"}
        broken, broken_notes = themes.draw(frame_with([clean_props[0], holed]),
                                           *self.editor.fixture())
        self.assertFalse([missing for missing in clean_notes.get("missing") or []
                          if str(missing).startswith("format:")],
                         "a clean file reports a format hole")
        holes = [str(missing) for missing in broken_notes.get("missing") or []]
        self.assertTrue(any(hole.startswith("format:GPU Temperature") for hole in holes),
                        f"{holes}: a file naming an unappliable format has to be *said*, the way "
                        "every other hole in a frame is said")
        self.assertEqual(len(broken_notes.get("boxes") or []),
                         len(clean_notes.get("boxes") or []) - 1,
                         "the bad row took another one with it, or nothing was skipped at all")
        self.assertGreater(fixtures.differ(clean, broken)[0], 0,
                           "the two frames are one picture, so no row was left out")
        trial = gui_edit.Editor(frame_with([clean_props[0], holed]), origin="check")
        trial.select(1)
        line, why = trial.drawn_text()
        self.assertIsNone(line, "the model names a line the painter could not draw")
        self.assertIn("cannot be applied", why, why[:200])
        self.assertIn("%q", why, "the answer does not name the format that failed")


class AFamilyTwoSpellings(unittest.TestCase):
    """`Arial` in the vendor's files, `arial` in `layout.FONTS`: one face, and the menu shows the
    spelling the file uses because dropping it would misrepresent the row."""

    def test_the_model_folds_what_the_painter_folds_and_moves_no_ink(self):
        found = None
        for editor in all_editors():
            for index, widget in enumerate(editor.widgets()):
                spelled = str((widget.get("property") or [{}])[0].get("fontFamily") or "")
                vocabulary = gui_edit.choices("fontFamily")
                if spelled and spelled not in vocabulary and spelled.lower() in vocabulary:
                    found = (editor, index, spelled)
                    break
            if found:
                break
        self.assertIsNotNone(found, "no library file writes a family the vocabulary spells another "
                                    "way, so the fold below has nothing to fold - and the menu no "
                                    "longer shows one either")
        editor, index, spelled = found
        editor.select(index)
        before, notes0 = editor.paint(*editor.fixture())
        ok, note = editor.set("fontFamily", spelled)
        self.assertTrue(ok, f"a menu entry the model refuses ({spelled!r}) is a choice the reader "
                            "cannot take")
        self.assertTrue(note and spelled in note, "the fold has to say which spelling it stored")
        self.assertIn(editor.value("fontFamily"), gui_edit.choices("fontFamily"),
                      "what was stored is not a name the vocabulary knows")
        after, notes1 = editor.paint(*editor.fixture())
        differing = fixtures.differ(before, after)[0]
        self.assertEqual(differing, 0, f"folding `{spelled}` moved {differing} px, so it was never "
                                      "the same face")
        self.assertEqual([str(m) for m in notes1.get("missing") or []],
                         [str(m) for m in notes0.get("missing") or []],
                         "the fold changed which rows the painter skipped")

    def test_nothing_else_folds_because_the_painter_folds_nothing_else(self):
        editor = next(e for e in all_editors() if e.name == "bars")
        row = next(i for i, widget in enumerate(editor.widgets())
                   if str(widget.get("type") or "") == "data"
                   and (widget.get("property") or [{}])[0].get("source") == "CPU Temperature")
        editor.select(row)
        ok, note = editor.set("source", "cpu temperature")
        self.assertFalse(ok, "only the family is folded: a source's case is part of its name, and "
                             "the painter matches sources exactly")
        self.assertIn("takes one of", note, note[:200])
        ok, _note = editor.set("fontFamily", "DEJAVU")
        self.assertTrue(ok)
        self.assertEqual(editor.value("fontFamily"), "dejavu",
                         "`font_for` lowercases that one name, so the model has to fold it too")


if __name__ == "__main__":
    unittest.main(verbosity=2)
