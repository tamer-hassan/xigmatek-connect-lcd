#!/usr/bin/env python3
"""Feature D: resizing a row by its edge, with the size keys taken from the painter.

Ported from the resize block of `tools/selftest.sh`'s GUI section.  The promise the pane makes is
**per kind**, so the check asks the painter rather than the model: which keys an edge drag writes,
whether the box follows the drag, whether the row's own arithmetic survives, and whether one press
of undo puts the file back.

Three rules hold all of it up:

* **a handle never writes a key the painter does not read.**  The outer bound is taken from
  `layout.py`'s own source - `themes.keys_read()` - not from a list kept here, so a size key that
  stops being read is caught rather than inherited;
* **a handle never writes a key that no edge owns.**  `cornerRadius`, `rotate`, `source`, `content`,
  the fonts, the ids: a drag that moved one of those would be editing the row's *subject* through
  its frame;
* **the drawn box is the claim.**  A `bar`'s box is exactly its declared `x,y,x+width,y+height`;
  a `line`'s is what `layout.line_rect` says, including the rows the vendor turns 90°, where the
  box's horizontal extent comes from `height`; an `arc` keeps `sizeWidth == 2*radius + 2*width`.
  Where the two disagree, the drag corrects `x`/`y` rather than leaving the ink where the model
  said it would not be.

`text` and `data` are the exceptions, and the reason is measured here rather than asserted in
prose: their box is the ink their face lays down, so a vertical handle writes `fontSize` and the
height lands *near* the ask, never on it - and pushing `fontSize` by 8 px moves a box's width by
an amount that is never 8, differs from row to row, and belongs to this machine's fonts.  No `width`
key could carry that, which is why those kinds own no side handle at all.
"""
from __future__ import annotations

import copy
import unittest

from tests import fixtures

from xigmalcd import layout, render, themes
from xigmaui import edit as gui_edit

#: Keys no edge of any row owns.  A drag that wrote one of these would be changing what the row
#: *is* by pulling on its frame.
NEVER_WRITTEN = ("cornerRadius", "rotate", "autoFitMax", "fitArc", "angleStart", "angleEnd",
                 "minValue", "maxValue", "source", "content", "name", "textColor",
                 "fontFamily", "fontFace", "family", "bold", "anchor", "arcPaint", "barPaint",
                 "id", "layerIndex", "type", "widgetContent")

#: How far each test edge is pushed.  12 px is large enough to survive any face's rounding and
#: small enough to stay on the glass.
PUSH = 12

#: A line turned 90° with a thickness, a plain line with one, and a `data` row whose extent
#: belongs to a cap: no shipped file carries these three shapes, so they are built here.  The
#: rotated row is the case the `x`/`y` correction exists for.
SYNTHESISED = {"width": render.W, "height": render.H, "osd": {"widget": [
    {"id": "gate-rot-line", "layerIndex": 0, "type": "line", "widgetContent": "",
     "property": [{"x": 165, "y": 305, "width": 150, "height": 2, "rotate": 90,
                   "lineWidth": 9}]},
    {"id": "gate-plain-line", "layerIndex": 0, "type": "line", "widgetContent": "",
     "property": [{"x": 10, "y": 60, "width": 100, "height": 4, "rotate": 0,
                   "lineWidth": 30}]},
    {"id": "gate-capped", "layerIndex": 0, "type": "data", "widgetContent": "",
     "property": [{"x": 20, "y": 20, "source": "CPU Temperature", "fontSize": 140,
                   "fontFamily": "dejavu", "bold": False,
                   "textColor": "rgba(255,255,255,1)", "xigma": {"autoFitMax": 120}}]}]}}


def editors() -> list:
    """Every layout the pane can open: the five generated, and every vendor file it selects."""
    return ([gui_edit.Editor(themes.export(name), origin="check", name=name)
             for name in sorted(themes.EXPORTS)]
            + [gui_edit.Editor.open_theme(rec["name"]) for rec in themes.scan()[0]])


def all_rows() -> list:
    """(editor, row index, widget) for every row of every layout the pane can open."""
    return [(editor, index, widget)
            for editor in editors() for index, widget in enumerate(editor.widgets())]


def box_for(editor: gui_edit.Editor, frame_index=None) -> dict:
    """{row index: box} as the painter reports it, at this editor's own fixture."""
    _image, notes = editor.paint(*editor.fixture())
    boxes = {row[3]: row[2] for row in (notes.get("boxes") or []) if row[2]}
    return boxes if frame_index is None else boxes.get(frame_index)


def poke_draw(editor: gui_edit.Editor, index: int, key: str, value):
    """Draw a copy of a layout with one `property` key set straight into the dict.

    Deliberately not `Editor.set`: this measures what the *painter* does with a key, and a key the
    inspector refuses to offer is exactly the one worth measuring.
    """
    obj = copy.deepcopy(editor.obj)
    (obj["osd"]["widget"][index]["property"][0])[key] = value
    trial = gui_edit.Editor(obj, origin="check", name=editor.name)
    return trial.paint(*trial.fixture())


def poke_row(editor: gui_edit.Editor, index: int, row: dict, key: str, value):
    """Draw the editor's layout with `row`'s index replaced, plus `key` set to `value`."""
    obj = copy.deepcopy(editor.obj)
    obj["osd"]["widget"][index] = copy.deepcopy(row)
    (obj["osd"]["widget"][index]["property"][0])[key] = value
    trial = gui_edit.Editor(obj, origin="check", name=editor.name)
    return trial.paint(*trial.fixture())


def single_row_editor(widget: dict) -> gui_edit.Editor:
    """An editor holding one row, for the face measurements: the box is the ink, and nothing else
    in the layout should be allowed to influence it."""
    obj = {"width": render.W, "height": render.H, "osd": {"widget": [copy.deepcopy(widget)]}}
    return gui_edit.Editor(obj, origin="check", name="check-face")


class TheVocabularyComesFromThePainter(unittest.TestCase):
    """The bound on what a handle may write is the painter's own source, not a list kept here."""

    def test_every_kind_the_door_knows_is_a_kind_the_library_draws(self):
        kinds = {str(widget.get("type") or "") for _e, _i, widget in all_rows()}
        self.assertEqual(sorted(kinds), sorted(layout.KINDS),
                         f"{sorted(kinds)} vs {sorted(layout.KINDS)}")
        self.assertTrue(set(gui_edit.Editor.SIZE_KEYS) <= set(layout.KINDS),
                        gui_edit.Editor.SIZE_KEYS)

    def test_every_size_key_is_one_the_painter_reads(self):
        read, read_xigma = themes.keys_read()
        for kind, keys in gui_edit.Editor.SIZE_KEYS.items():
            for key in keys:
                self.assertIn(key, read, f"{kind}: `{key}` is a size key `layout.py` does not "
                                         "read, so a drag would write a key nothing draws")
        for key in ("autoFitMax", "fitArc"):
            self.assertIn(key, read_xigma, f"the door names a cap nothing reads: {key}")


class WhatTheFilesSayAboutSize(unittest.TestCase):
    """The drawn-box claims.  A `box` here is always the one the painter reports."""

    @classmethod
    def setUpClass(cls):
        cls.rows = all_rows()
        cls.boxes = {}
        for editor, index, widget in cls.rows:
            cls.boxes.setdefault(id(editor), {})[index] = box_for(editor, index)

    def declared(self, widget: dict) -> dict:
        return (widget.get("property") or [{}])[0]

    def test_every_drawn_bar_box_is_exactly_its_declared_rect(self):
        drawn = exact = 0
        for editor, index, widget in self.rows:
            if str(widget.get("type") or "") != "bar":
                continue
            box = self.boxes[id(editor)].get(index)
            if not box:
                continue                     # no reading for its source, so no box at all
            drawn += 1
            props = self.declared(widget)
            if box == (int(props["x"]), int(props["y"]),
                       int(props["x"]) + int(props["width"]),
                       int(props["y"]) + int(props.get("height") or 0)):
                exact += 1
        self.assertGreater(drawn, 0, "no `bar` row drew a box, so the rule would be empty")
        self.assertEqual(exact, drawn,
                         f"{exact}/{drawn}: a drawn `bar` row's box is not its declared "
                         "`x,y,x+width,y+height`")

    def test_every_drawn_line_box_is_what_line_rect_predicts(self):
        total = exact = 0
        for editor, index, widget in self.rows:
            if str(widget.get("type") or "") != "line":
                continue
            total += 1
            props = self.declared(widget)
            left, top, width, height = layout.line_rect(props)
            box = self.boxes[id(editor)].get(index)
            if box and box == (left, top, left + width, top + height):
                exact += 1
        self.assertGreater(total, 0, "no `line` row was found to compare")
        self.assertEqual(exact, total,
                         f"{exact}/{total}: `line_rect` did not predict a drawn line's box")

    def test_every_arc_row_keeps_the_arithmetic_its_ring_is_drawn_with(self):
        rows = identical = square = 0
        for editor, index, widget in self.rows:
            if str(widget.get("type") or "") != "arc":
                continue
            rows += 1
            props = self.declared(widget)
            identical += int(props.get("sizeWidth") or 0) == 2 * int(props.get("radius") or 0) \
                + 2 * int(props.get("width") or 0)
            square += int(props.get("sizeWidth") or 0) == int(props.get("sizeHeight") or 0)
        self.assertGreater(rows, 0, "no `arc` rows in the library")
        self.assertEqual(identical, rows, f"{identical}/{rows}: an `arc` row in the library does "
                                          "not keep `sizeWidth == 2*radius + 2*width`")
        self.assertEqual(square, rows, f"{square}/{rows}: an `arc` row is not square, so the "
                                       "corner rule below would be measuring nothing")

    def test_no_text_or_data_row_carries_a_width_or_height_key(self):
        """Those kinds' box is the ink their face lays down; a `width` key would be a second,
        disagreeing answer about how big the row is."""
        rows = with_wh = 0
        for editor, index, widget in self.rows:
            if str(widget.get("type") or "") not in ("text", "data"):
                continue
            rows += 1
            props = self.declared(widget)
            with_wh += "width" in props or "height" in props
        self.assertGreater(rows, 0)
        self.assertEqual(with_wh, 0, f"{with_wh} of {rows} `text`/`data` rows carry a `width` or "
                                     "`height` key, and the door's rule for those kinds is that "
                                     "their box is their ink")

    def bar_with_the_keys_planted(self, widget: dict) -> dict:
        """A copy of a real `bar` row with `cornerRadius` and `rotate` written into it.

        Not one layout in the copied library carries either key, so the corpus on its own cannot
        say whether a handle that refuses them is refusing something real.  These are the keys the
        vendor's own vocabulary names, planted on a row that does draw, which is how the two rules
        below stop being vacuous.
        """
        props = copy.deepcopy(widget)
        props["property"][0].update({"cornerRadius": 6, "rotate": 0})
        return props

    def planted_bar_rows(self) -> list:
        """(editor, index, row with both keys planted) for every `bar` row that draws a box."""
        out = []
        for editor, index, widget in self.rows:
            if str(widget.get("type") or "") != "bar" or not self.boxes[id(editor)].get(index):
                continue
            row = self.bar_with_the_keys_planted(widget)
            out.append((editor, index, row))
        return out

    def test_a_push_on_cornerRadius_leaves_the_box_exactly_where_it_was(self):
        """A handle never writes that key, and this is why: the painter's box does not move when
        the key is pushed straight into the file, so a drag could not have reported it."""
        counted = still = 0
        for editor, index, row in self.planted_bar_rows():
            box = self.boxes[id(editor)][index]
            counted += 1
            _image, notes = poke_row(editor, index, row, "cornerRadius",
                                     int(row["property"][0]["cornerRadius"]) + 8)
            moved = {r[3]: r[2] for r in (notes.get("boxes") or []) if r[2]}.get(index)
            still += 1 if moved == box else 0
        self.assertGreater(counted, 4, f"{counted}: too few `bar` rows draw a box to measure on")
        self.assertEqual(still, counted,
                         f"{still}/{counted}: pushing `cornerRadius` moved a box, and the page "
                         "says a handle never writes that key")

    def test_a_push_on_a_bars_rotate_changes_no_pixel_at_all(self):
        """The other key a handle refuses on a `bar`: measured, `rotate` is inert in the drawing on
        this canvas, which is what makes the refusal sentence true rather than convenient."""
        counted = inert = 0
        for editor, index, row in self.planted_bar_rows():
            counted += 1
            before, _notes = poke_row(editor, index, row, "rotate", 0)
            after, _notes2 = poke_row(editor, index, row, "rotate", 8)
            inert += 1 if not fixtures.differ(before, after)[0] else 0
        self.assertGreater(counted, 4, f"{counted}: too few `bar` rows to measure on")
        self.assertEqual(inert, counted,
                         f"{inert}/{counted}: a `bar` row's `rotate` changed the picture, so "
                         "something reads it and the refusal sentence is wrong")

    def test_eight_pixels_of_face_buys_a_width_that_is_never_eight_pixels(self):
        """The rule the page writes, measured one row at a time: the width a face push buys is not
        the push itself, it is not the same from row to row, and its size belongs to this machine's
        fonts - so no `width` key could carry it, and the door writes the face instead."""
        widths = []
        capped = 0
        for editor, index, widget in self.rows:
            if str(widget.get("type") or "") not in ("text", "data"):
                continue
            props = self.declared(widget)
            size = int(props.get("fontSize") or 12)
            capped += 1 if int(((props.get("xigma") or {}).get("autoFitMax")) or 0) else 0
            one = single_row_editor(widget)
            before = one._row_box(one.obj, 0)
            bigger = copy.deepcopy(one.obj)
            bigger["osd"]["widget"][0]["property"][0]["fontSize"] = size + 8
            two = gui_edit.Editor(bigger, origin="check", name="check-face")
            after = two._row_box(two.obj, 0)
            if not before or not after:
                continue
            widths.append((after[2] - after[0]) - (before[2] - before[0]))
        self.assertTrue(widths, "no `text`/`data` row drew a box, so the face claim "
                                      "cannot be measured")
        self.assertTrue(all(value != 8 for value in widths),
                        f"{min(widths)}..{max(widths)}: +8 px of face moved some row's box exactly "
                        "+8 px of width")
        moved = [value for value in widths if value]
        self.assertGreater(len(moved), 0, "no row answered its face at all")
        self.assertGreater(len(set(widths)), 3,
                           f"{widths[:8]}: a face push bought the same width everywhere, which is "
                           "not what the page says")
        still = [value for value in widths if not value]
        self.assertLessEqual(len(still), capped,
                             f"{len(still)} rows did not move at all, and only {capped} name "
                             "`xigma.autoFitMax`: a row with no cap has to answer its face")


class TheSweep(unittest.TestCase):
    """Every edge the row's own rules say is live, pushed 12 px, and what that owes back.

    One pass, because the expensive part is the face search a `text`/`data` resize runs - a dozen
    solo draws per ask, per the door's own comment - and seven assertions must not each pay for it.
    The pass records what each row answered; every check below reads the record.
    """

    @classmethod
    def setUpClass(cls):
        cls.rows = all_rows()
        cls.evidence = []
        for editor, index, widget in cls.rows:
            kind = str(widget.get("type") or "")
            base = themes.canonical(editor.obj)
            _image, notes = editor.paint(*editor.fixture())
            box = {row[3]: row[2] for row in (notes.get("boxes") or []) if row[2]}.get(index)
            live = editor.size_edges(index, box)
            straight = tuple(edge for edge in live if "-" not in edge)
            corners = tuple(edge for edge in live if "-" in edge)
            edges = straight + (corners if kind not in ("text", "data")
                                else corners[:1] if index % 4 == 0 and corners else ())
            record = {"name": editor.name, "index": index, "kind": kind, "base": base,
                      "box": box, "live": live, "edges": edges, "declined": [], "accepted": [],
                      "side": []}
            trial = gui_edit.Editor(copy.deepcopy(editor.obj), origin="check", name=editor.name)
            trial.select(index)
            for edge in edges:
                # grow first, because that is the direction the sentence about a row's edges reads
                # in; if the glass is in the way, the same edge pushed the other way is the test
                sign_x = PUSH if "right" in edge else -PUSH if "left" in edge else 0
                sign_y = PUSH if "bottom" in edge else -PUSH if "top" in edge else 0
                for mult in (1, -1):
                    dx, dy = sign_x * mult, sign_y * mult
                    steps = trial.steps
                    ok, said = trial.resize_row(dx, dy, edge, index)
                    if ok:
                        break
                    if trial.steps != steps or themes.canonical(trial.obj) != base:
                        record["declined"].append((edge, dx, dy, said, "MOVED SOMETHING"))
                if not ok:
                    record["declined"].append((edge, dx, dy, said, ""))
                    continue
                after = (trial.widgets()[index].get("property") or [{}])[0]
                before = (widget.get("property") or [{}])[0]
                changed = sorted(key for key in set(after) | set(before)
                                 if after.get(key) != before.get(key))
                _frame, new_notes = trial.paint(*trial.fixture())
                new_box = {row[3]: row[2] for row in (new_notes.get("boxes") or [])
                           if row[2]}.get(index)
                trial.undo()
                record["accepted"].append({"edge": edge, "dx": dx, "dy": dy,
                                           "steps": trial.steps, "changed": changed,
                                           "was": box, "now": new_box,
                                           "back": themes.canonical(trial.obj) == base})
            # the sides a `text`/`data` row owns nothing for are still asked, so that the model's
            # answer - not the pane's marks - is what is on record
            if kind in ("text", "data"):
                trial = gui_edit.Editor(copy.deepcopy(editor.obj), origin="check", name=editor.name)
                trial.select(index)
                for side in ("left", "right"):
                    ok, said = trial.resize_row(PUSH, 0, side, index)
                    record["side"].append((side, ok, said, trial.steps == 0,
                                           themes.canonical(trial.obj) == base))
            cls.evidence.append(record)

    def of_kind(self, *kinds: str) -> list:
        return [item for item in self.evidence if item["kind"] in kinds]

    def test_a_text_or_data_row_owns_no_side_handle_and_refuses_them_in_words(self):
        """The sides the door says nothing about are still asked, and still refused: the pane hides
        those handles, but the model's answer is the claim, not the marks."""
        asked = 0
        for record in self.of_kind("text", "data"):
            self.assertFalse({"left", "right"} & set(record["live"]),
                             f"{record['name']} row {record['index']}: {record['live']} - a side "
                             "handle on a kind with no width")
            for side, ok, said, no_steps, untouched in record["side"]:
                asked += 1
                self.assertFalse(ok, f"{record['name']} row {record['index']} accepted a {side} drag")
                # two different refusals, and which one applies is this machine's picture: a row
                # whose source has no reading paints no box, so it has no edge at all
                want = "owns no width" if record["box"] else "paints no box"
                self.assertIn(want, said, f"{record['name']} row {record['index']} {side}: "
                                          f"{said!r} with box {record['box']}")
                self.assertTrue(no_steps, "the refusal took an undo step")
                self.assertTrue(untouched, "the refusal wrote something")
        self.assertGreater(asked, 20, f"{asked} side drags asked: the rule was barely tested")

    def test_a_special_row_has_no_corner_handles(self):
        seen = 0
        for record in self.of_kind("special"):
            seen += 1
            self.assertFalse(any("-" in edge for edge in record["live"]),
                             f"{record['name']} row {record['index']}: {record['live']} - a corner "
                             "handle on a `special`")
        self.assertGreater(seen, 0, "no `special` row in the library")

    def test_a_resize_never_writes_a_key_the_painter_does_not_read(self):
        read, _read_xigma = themes.keys_read()
        for record in self.evidence:
            for item in record["accepted"]:
                for key in item["changed"]:
                    with self.subTest(layout=record["name"], row=record["index"],
                                      edge=item["edge"], key=key):
                        self.assertIn(key, read, "a handle wrote a key `layout.py` does not read")
                        self.assertNotIn(key, NEVER_WRITTEN, "no edge owns that key")

    def test_one_resize_is_exactly_one_undo_step_that_returns_the_file_byte_for_byte(self):
        accepted = returned = 0
        for record in self.evidence:
            for item in record["accepted"]:
                accepted += 1
                with self.subTest(layout=record["name"], row=record["index"], edge=item["edge"]):
                    self.assertEqual(item["steps"], 0,
                                     f"the undo after a {item['edge']} drag left {item['steps']} "
                                     "steps standing")
                    self.assertTrue(item["back"], "one press of undo did not put the layout back")
                returned += 1
            for edge, dx, dy, said, moved in record["declined"]:
                self.assertNotEqual(moved, "MOVED SOMETHING",
                                    f"{record['name']} row {record['index']}: a refused {edge} "
                                    f"drag took an undo step or wrote a key ({said!r})")
        self.assertGreater(accepted, 100, f"{accepted} accepted drags measured, {returned} undone")

    def test_declared_geometry_boxes_follow_the_drag_one_pixel_for_one_pixel(self):
        """`bar`, `line` and `arc` are drawn from the numbers in the file, so their box has to move
        by exactly what the drag asked - the kinds where no correction is allowed.  A `top` or
        `left` delta moves the anchor, not the far side, so the extent is the negated delta."""
        checked = 0
        for record in self.of_kind("bar", "line", "arc"):
            if not record["box"]:
                continue
            for item in record["accepted"]:
                edge, dx, dy = item["edge"], item["dx"], item["dy"]
                self.assertIsNotNone(item["now"], f"{record['name']} row {record['index']}: the "
                                                  "resized row paints no box any more")
                grew = (record["box"][2] - record["box"][0], record["box"][3] - record["box"][1])
                got = (item["now"][2] - item["now"][0], item["now"][3] - item["now"][1])
                want = (grew[0] + (dx if "right" in edge else -dx if "left" in edge else 0),
                        grew[1] + (dy if "bottom" in edge else -dy if "top" in edge else 0))
                self.assertEqual(got, want,
                                 f"{record['name']} row {record['index']} {edge} ({dx},{dy}): "
                                 f"{grew} -> {got}, the drag asked for {want}")
                checked += 1
        self.assertGreater(checked, 60, f"{checked}: almost no declared-geometry box was followed")

    def test_an_arc_keeps_its_ring_arithmetic_and_a_corner_keeps_it_square(self):
        checked = 0
        for record in self.of_kind("arc"):
            for item in record["accepted"]:
                checked += 1
                self.assertIsNotNone(item["now"], f"{record['name']} row {record['index']}: the "
                                                  "resized ring paints no box any more")
                if item["dx"] and item["dy"]:
                    width = item["now"][2] - item["now"][0]
                    height = item["now"][3] - item["now"][1]
                    self.assertEqual(width, height,
                                     f"{record['name']} row {record['index']}: a corner drag on a "
                                     "square ring left it skewed")
        self.assertGreater(checked, 8, f"{checked}: too few `arc` edges were resized to mean "
                                       "anything")
        # the arithmetic itself is re-read from the files, because a drag that ends at the same
        # numbers the sweep started with cannot show the rule holding
        for editor, index, widget in self.rows:
            if str(widget.get("type") or "") != "arc":
                continue
            props = (widget.get("property") or [{}])[0]
            trial = gui_edit.Editor(copy.deepcopy(editor.obj), origin="check", name=editor.name)
            trial.select(index)
            ok, _said = trial.resize_row(0, PUSH, "bottom", index)
            if not ok:
                continue
            after = (trial.widgets()[index].get("property") or [{}])[0]
            self.assertEqual(int(after["sizeWidth"]),
                             2 * int(after["radius"]) + 2 * int(after["width"]),
                             f"{editor.name} row {index}: the ring no longer meets its own box")

    def test_a_text_rows_handle_writes_the_face_and_lands_near_the_ask(self):
        """The height is what the face lays down, so the drag is answered *approximately*: the
        result has to be nearer the ask than where it started, and the only key written is the
        face."""
        landed = []
        for record in self.of_kind("text", "data"):
            if not record["box"]:
                continue
            for item in record["accepted"]:
                self.assertEqual(item["changed"], ["fontSize"],
                                 f"{record['name']} row {record['index']} {item['edge']}: a text "
                                 f"row's resize wrote {item['changed']}, more than the face")
                grew = (record["box"][2] - record["box"][0], record["box"][3] - record["box"][1])
                got = (item["now"][2] - item["now"][0], item["now"][3] - item["now"][1])
                edge, dy = item["edge"], item["dy"]
                want = grew[1] + (-dy if "top" in edge else dy)
                self.assertNotEqual(got[1], grew[1],
                                    f"{record['name']} row {record['index']} {edge}: the face left "
                                    "the height alone")
                self.assertLessEqual(abs(got[1] - want), abs(grew[1] - want) + 1,
                                     f"{record['name']} row {record['index']} {edge} (0,{dy}): "
                                     f"{grew} -> {got}, asked {want}: the face moved away from the "
                                     "ask")
                landed.append(abs(got[1] - want))
        self.assertGreater(len(landed), 20, f"{len(landed)} face-bound rows were resized")

    def test_a_special_rows_handle_writes_only_what_its_painter_can_be_given(self):
        checked = 0
        for record in self.of_kind("special"):
            if not record["box"]:
                continue
            for item in record["accepted"]:
                self.assertTrue(set(item["changed"]) <= {"width", "fontSize"},
                                f"{record['name']} row {record['index']} {item['edge']}: "
                                f"{item['changed']}")
                checked += 1
        self.assertGreater(checked, 0, "no `special` edge was resized")


class TheCasesNoShippedFileCarries(unittest.TestCase):
    """A line turned 90° carrying a thickness, a plain line carrying one, and a row whose extent
    belongs to a cap - built in memory, because no layout in the library has these shapes."""

    def setUp(self):
        self.editor = gui_edit.Editor(copy.deepcopy(SYNTHESISED), origin="check", name="check-syn")
        self.base = themes.canonical(SYNTHESISED)

    def test_a_line_turned_ninety_degrees_grows_its_thickness_not_its_length(self):
        """`line_rect` pivots the declared rect about its own centre, so for a `rotate: 90` row the
        *vertical* handle owns `lineWidth` and the horizontal one owns `height`."""
        for index, edge, dx, dy, key in ((0, "bottom", 0, PUSH, "lineWidth"),
                                         (0, "right", PUSH, 0, "height"),
                                         (1, "bottom", 0, -2, "lineWidth")):
            with self.subTest(row=index, edge=edge):
                self.editor.select(index)
                before = box_for(self.editor, index)
                ok, said = self.editor.resize_row(dx, dy, edge, index)
                self.assertTrue(ok, f"{said}: the refusal is the wrong answer for this shape")
                after = box_for(self.editor, index)
                self.assertEqual((after[2] - after[0], after[3] - after[1]),
                                 (before[2] - before[0] + dx, before[3] - before[1] + dy),
                                 "a synthetic line's box did not follow the drag")
                props = (self.editor.widgets()[index].get("property") or [{}])[0]
                self.assertIsNotNone(props.get(key), f"the key that drag owns (`{key}`) is missing")
                self.editor.undo()
                self.assertEqual(themes.canonical(self.editor.obj), self.base,
                                 "undo of the synthetic resize did not return the file")

    def test_a_row_whose_extent_is_a_cap_refuses_and_names_that_cap(self):
        """`fontSize` 140 with `xigma.autoFitMax` 120: the drawn extent belongs to the cap, not to
        the face, so a handle that cannot move the cap has to say so."""
        self.editor.select(2)
        steps = self.editor.steps
        ok, said = self.editor.resize_row(0, PUSH, "bottom", 2)
        self.assertFalse(ok, "a capped row's face was resized anyway")
        self.assertIn("xigma.autoFitMax", said,
                      f"the refusal does not name the key that owns the extent: {said!r}")
        self.assertEqual(self.editor.steps, steps, "the refusal took an undo step")
        self.assertEqual(themes.canonical(self.editor.obj), self.base, "the refusal wrote")

    def test_a_special_fitted_into_a_ring_refuses_by_naming_fitArc(self):
        """The same sentence, one kind over: `xigma.fitArc` decides how big those figures are."""
        found = ""
        for editor, index, widget in all_rows():
            if str(widget.get("type") or "") != "special":
                continue
            trial = gui_edit.Editor(copy.deepcopy(editor.obj), origin="check", name=editor.name)
            trial.select(index)
            ok, said = trial.resize_row(0, 40, "bottom", index)
            if not ok and "xigma.fitArc" in said:
                self.assertEqual(trial.steps, 0, "the refusal took an undo step")
                self.assertEqual(themes.canonical(trial.obj), themes.canonical(editor.obj),
                                 "the fitArc refusal wrote something")
                found = f"{editor.name} row {index}"
                break
        self.assertTrue(found, "no `special` row refused a face drag by naming `xigma.fitArc`")


if __name__ == "__main__":
    unittest.main(verbosity=2)
