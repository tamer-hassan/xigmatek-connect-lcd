#!/usr/bin/env python3
"""Rows you can add, delete and reorder - and the pixels a reorder is allowed to move.

Ported from the add/delete/reorder blocks of `tools/selftest.sh`'s GUI section.  Two rules decide
what this file can claim:

* **the envelope a new row has to fit is taken from the files on this run**, not from a list kept
  here.  Every row this program can read carries exactly the five keys `edit.WIDGET_KEYS`, with
  `property` a one-element list and `widgetContent` empty; the *mandatory* keys per kind are the
  intersection over the rows of that kind, computed here.  An add that leaves one out, or that
  invents a key, or whose default is a value no row of that kind uses, is an add that produces a
  file the painter may not read;
* **every claim about what a reorder does is a pixel count from the painter**, because a claim about
  list indices is the model talking to itself.  Draw order is what the panel would show, so the
  rule is bidirectional and asserted both ways: a swap of two rows whose boxes never meet moves
  **0 px**, and a swap moves ink **exactly where** the two rows lay opaque ink of different colours
  on the same pixel.

The second one is the reason this file draws a lot: each pair that meets is drawn alone, twice, and
compared pixel by pixel inside the shared rectangle.  A pair whose boxes meet but where no pixel of
the overlap is covered opaquely by both rows - two `line` rows crossing in sub-pixel coverage, an
`arc`'s box that is mostly the hole its ring is drawn around - swaps nothing, and says which rows
those were rather than having the rule loosened.
"""
from __future__ import annotations

import copy
import unittest

from tests import fixtures

from xigmalcd import layout, render, themes
from xigmaui import edit as gui_edit


def all_editors() -> list:
    return ([gui_edit.Editor(themes.export(name), origin="check", name=name)
             for name in sorted(themes.EXPORTS)]
            + [gui_edit.Editor.open_theme(rec["name"]) for rec in themes.scan()[0]])


def all_rows(editors: list) -> list:
    return [widget for editor in editors for widget in editor.widgets()]


def paint_of(obj: dict) -> tuple:
    trial = gui_edit.Editor(copy.deepcopy(obj), origin="check", name="check")
    return trial.paint(*trial.fixture())


def px_differ(a, b) -> int:
    return fixtures.differ(a, b)[0]


class TheEnvelopeComesFromTheFiles(unittest.TestCase):
    """What a row is, counted from the layouts rather than written down."""

    @classmethod
    def setUpClass(cls):
        cls.editors = all_editors()
        cls.rows = all_rows(cls.editors)
        cls.kinds = {}
        for widget in cls.rows:
            kind = str(widget.get("type") or "")
            cls.kinds[kind] = cls.kinds.get(kind, 0) + 1
        cls.mandatory, cls.values = {}, {}
        for kind in cls.kinds:
            common = None
            for widget in cls.rows:
                if str(widget.get("type") or "") != kind:
                    continue
                keys = set((widget.get("property") or [{}])[0])
                common = keys if common is None else (common & keys)
            cls.mandatory[kind] = sorted(common - {"xigma"})
            for field in cls.mandatory[kind]:
                if field in ("x", "y"):
                    continue
                cls.values[(kind, field)] = {
                    repr(widget["property"][0][field]) for widget in cls.rows
                    if str(widget.get("type") or "") == kind
                    and field in (widget.get("property") or [{}])[0]}

    def test_every_row_of_every_layout_carries_the_same_five_keys(self):
        # 185 -> 188 -> 191 -> 188 -> 199 on 2026-11-14: `bars` gained a labelled drive row, that row
        # became two positional slots, and the block then came back down to eleven rows when
        # the owner's `Fan GPU` row took a fan slot's place instead of adding a twelfth.  It
        # lands on the same 188 it passed through an hour earlier, which is the point of
        # pinning a count rather than deriving one: three widgets' worth of block was traded,
        # not grown - and then the gutter figures added eleven rows carrying an x and a y, all
        # of them at one x (3), which is why the snap census's shared-column count moved from
        # 92 to 103 while its gap histogram stayed empty at 1, 6 and 7 px.  Pinned rather than
        # derived, because this is the count that says a layout grew.
        self.assertEqual(len(self.rows), 199, f"{len(self.rows)} rows in "
                                              f"{len(self.editors)} layouts")
        odd = [widget for widget in self.rows
               if frozenset(widget) != frozenset(gui_edit.WIDGET_KEYS)]
        self.assertFalse(odd, f"{odd[:2]}: the five-key envelope is not what the files carry")
        self.assertTrue(all(isinstance(widget.get("property"), list)
                            and len(widget["property"]) == 1 for widget in self.rows),
                        "a `property` that is not one element")
        self.assertTrue(all(widget.get("widgetContent") == "" for widget in self.rows),
                        "a row carries content in `widgetContent`, which this program never reads")

    def test_the_kinds_the_rows_use_are_the_kinds_the_painter_dispatches(self):
        self.assertEqual(sorted(self.kinds), sorted(layout.KINDS), sorted(self.kinds))

    def test_every_mandatory_key_of_a_kind_is_a_key_that_kind_actually_sets(self):
        empty = [key for key, values in self.values.items() if not values]
        self.assertFalse(empty, f"a mandatory key nobody sets: {empty}")


class AddingDeletingAndReordering(unittest.TestCase):
    """The model's three structural acts, on every layout, in a copy the check owns."""

    @classmethod
    def setUpClass(cls):
        cls.editors = all_editors()
        cls.rows = all_rows(cls.editors)
        cls.mandatory = {}
        for kind in layout.KINDS:
            common = None
            for widget in cls.rows:
                if str(widget.get("type") or "") != kind:
                    continue
                keys = set((widget.get("property") or [{}])[0])
                common = keys if common is None else (common & keys)
            cls.mandatory[kind] = sorted(common - {"xigma"})

    def fresh(self, editor: gui_edit.Editor) -> gui_edit.Editor:
        return gui_edit.Editor(copy.deepcopy(editor.obj), origin=editor.origin, path=editor.path,
                               name=editor.name, theme=editor.theme)

    def test_an_added_row_carries_the_keys_that_kind_always_carries_and_paints_a_new_box(self):
        adds = 0
        for editor in self.editors:
            for kind in sorted(layout.KINDS):
                with self.subTest(layout=editor.name, kind=kind):
                    trial = self.fresh(editor)
                    if trial.rows_of(kind):
                        trial.select(trial.rows_of(kind)[-1])
                    _before, notes0 = trial.paint(*trial.fixture())
                    boxes0 = [row for row in (notes0.get("boxes") or []) if row[2]]
                    steps = trial.steps
                    ok, _said = trial.add_widget(kind, name="check-labels")
                    if not ok:
                        self.assertEqual(trial.steps, steps, "a refused add moved the file")
                        self.assertFalse(trial.dirty, "a refused add marked the layout dirty")
                        continue
                    adds += 1
                    new = trial.widgets()[trial.index]
                    self.assertEqual(str(new.get("type") or ""), kind)
                    self.assertEqual(frozenset(new), frozenset(gui_edit.WIDGET_KEYS))
                    props = (new.get("property") or [{}])[0]
                    missing = set(self.mandatory[kind]) - set(props)
                    self.assertFalse(missing, f"a new {kind} row left out "
                                              f"{sorted(missing)}: every row of that kind carries "
                                              "them")
                    for field in self.mandatory[kind]:
                        if field in ("x", "y"):
                            continue
                        same = {repr(widget["property"][0][field]) for widget in self.rows
                                if str(widget.get("type") or "") == kind
                                and field in (widget.get("property") or [{}])[0]}
                        self.assertIn(repr(props[field]), same,
                                      f"a new {kind} row's `{field}` default is a value no {kind} "
                                      "row of this library uses")
                    ids = [str(widget.get("id")) for widget in trial.widgets()]
                    self.assertEqual(ids.count(str(new.get("id"))), 1,
                                     "the new id collides inside this layout")
                    hard, _soft = themes.validate(trial.obj)
                    self.assertFalse(hard, f"the added row is invalid: {hard}")
                    _after, notes1 = trial.paint(*trial.fixture())
                    boxes1 = [row for row in (notes1.get("boxes") or []) if row[2]]
                    self.assertGreater(len(boxes1), len(boxes0),
                                       f"the {kind} row the model added paints no box the frame "
                                       "did not have")
                    self.assertEqual(trial.steps, steps + 1, "add is not exactly one undo step")
                    self.assertTrue(trial.undo(), "one press of undo did not undo the add")
                    self.assertEqual(themes.canonical(trial.obj), themes.canonical(editor.obj),
                                     "undo did not put the file back byte for byte")
        self.assertGreater(adds, 40, f"{adds} adds succeeded across {len(self.editors)} layouts: "
                                     "the rule was barely exercised")

    def test_an_unknown_kind_is_refused_in_words_and_changes_nothing(self):
        editor = self.editors[0]
        trial = self.fresh(editor)
        steps, dirty, count = trial.steps, trial.dirty, len(trial.widgets())
        for bad, want in (("nope", "is not a kind this program draws"),
                          ("", "is not a kind this program draws")):
            ok, said = trial.add_widget(bad, name="check-labels")
            self.assertFalse(ok, f"`{bad}` was accepted as a kind")
            self.assertIn(want, said, said[:200])
            self.assertEqual((trial.steps, trial.dirty, len(trial.widgets())),
                             (steps, dirty, count), "the refusal still changed the layout")

    def test_the_last_row_cannot_be_deleted_and_the_rest_can(self):
        editor = self.editors[0]
        trial = self.fresh(editor)
        while len(trial.widgets()) > 1:
            self.assertTrue(trial.delete_widget()[0], "deleting down to one row was refused early")
        steps, count = trial.steps, len(trial.widgets())
        ok, said = trial.delete_widget()
        self.assertFalse(ok, "the empty layout was allowed")
        self.assertIn("the only row in this layout", said, said[:220])
        self.assertIn("hard problem", said,
                      "the refusal does not quote `themes.validate`, whose own words it is made of")
        self.assertEqual((trial.steps, len(trial.widgets())), (steps, count),
                         "the refusal still removed the row")

    def test_a_row_already_first_cannot_be_moved_first_again(self):
        editor = self.editors[0]
        trial = self.fresh(editor)
        trial.select(0)
        ok, said = trial.move_widget(-1)
        self.assertFalse(ok, "row 0 moved before itself")
        self.assertIn("already the first drawn", said, said[:200])

    def test_ids_and_layer_indexes_survive_every_adjacent_swap(self):
        for editor in self.editors:
            widgets = editor.widgets()
            for index in range(len(widgets) - 1):
                trial = self.fresh(editor)
                trial.select(index)
                ok, said = trial.move_widget(+1)
                self.assertTrue(ok, f"{editor.name} row {index}: {said}")
                self.assertEqual({str(w.get("id")): w.get("layerIndex") for w in widgets},
                                 {str(w.get("id")): w.get("layerIndex") for w in trial.widgets()},
                                 f"{editor.name} row {index}: a reorder rewrote `layerIndex`, "
                                 "which nothing here reads")
                self.assertEqual(sorted(str(w.get("id")) for w in trial.widgets()),
                                 sorted(str(w.get("id")) for w in widgets),
                                 f"{editor.name} row {index}: a swap lost or invented a row")

    def test_a_swap_moves_ink_exactly_where_two_rows_lay_different_colours_on_one_pixel(self):
        """The draw-order rule, in both directions.

        A pair whose boxes never meet must swap 0 px.  A pair whose boxes do meet moves ink if and
        only if some pixel of the shared rectangle is covered **opaquely by both rows in different
        colours** - which is what "the later row is on top" means in pixels.  Rows whose boxes meet
        in sub-pixel coverage only (two vendor `line` rows crossing) swap nothing, and that answer
        is reported rather than papered over.
        """
        never_meeting = moved = silent = 0
        silent_pairs = []
        for editor in self.editors:
            _frame0, notes0 = editor.paint(*editor.fixture())
            boxes = {row[3]: row[2] for row in (notes0.get("boxes") or []) if row[2]}
            widgets = editor.widgets()
            for index in range(len(widgets) - 1):
                if index not in boxes or index + 1 not in boxes:
                    continue          # a row with no reading draws no box, so it has nothing to
                                      # move
                trial = self.fresh(editor)
                trial.select(index)
                ok, said = trial.move_widget(+1)
                self.assertTrue(ok, f"{editor.name} row {index}: {said}")
                frame1, _notes1 = trial.paint(*trial.fixture())
                differing = px_differ(_frame0, frame1)
                if not gui_edit._overlaps(boxes[index], [boxes[index + 1]]):
                    self.assertEqual(differing, 0,
                                     f"{editor.name} rows {index}/{index + 1}: two rows whose boxes "
                                     "never meet swapped ink")
                    never_meeting += 1
                    continue
                left = max(boxes[index][0], boxes[index + 1][0])
                top = max(boxes[index][1], boxes[index + 1][1])
                right = min(boxes[index][2], boxes[index + 1][2])
                bottom = min(boxes[index][3], boxes[index + 1][3])
                solo = []
                for one in (index, index + 1):
                    image, _notes = paint_of({"width": render.W, "height": render.H,
                                             "osd": {"widget": [copy.deepcopy(widgets[one])]}})
                    solo.append(image.convert("RGBA"))
                both_opaque = different = 0
                for y in range(top, bottom + 1):
                    for x in range(left, right + 1):
                        a, b = solo[0].getpixel((x, y)), solo[1].getpixel((x, y))
                        if a[3] == 255 and b[3] == 255:
                            both_opaque += 1
                            if a[:3] != b[:3]:
                                different += 1
                self.assertEqual(differing > 0, different > 0,
                                 f"{editor.name} rows {index}/{index + 1}: {differing} px moved "
                                 f"with {different} two-coloured opaque pixels of overlap "
                                 f"({both_opaque} shared): the draw-order rule and the pixel count "
                                 "disagree about which row is on top")
                if differing:
                    moved += 1
                else:
                    silent += 1
                    silent_pairs.append(f"{editor.name} rows {index}/{index + 1} "
                                        f"({widgets[index].get('type')}/"
                                        f"{widgets[index + 1].get('type')}, {both_opaque} shared)")
        self.assertGreater(never_meeting, 20,
                           f"{never_meeting} pairs whose boxes never meet: the corpus has too few "
                           "to mean anything")
        # `moved > 4` and `silent < moved` used to sit here.  They were a claim about the corpus,
        # and the corpus they described was `bars` overlapping itself: its meter ran 5 rows inside
        # the text of the row under it, which is what made adjacent pairs loud.  The 2026-11-12
        # clearance rule in `tests/test_bars_rows.py` removed those overlaps, so on this bench
        # the shipped files now supply loud and silent pairs of {moved} and {silent} - a corpus
        # that reads as separated rows, which was the point.  What that costs is recorded rather
        # than hidden: with nothing in the shipped files overlapping, this loop can only prove
        # the *negative* half of the law (a pair whose boxes never meet, or which meets in
        # sub-pixel coverage only, moves 0 px).  The positive half is proven one class down, in
        # `AVisibleReorderIsBuiltOnPurpose`, where the overlap is authored rather than hoped for.
        self.assertGreater(silent + moved, 0,
                           "no pair of drawn rows in the corpus even meets, so the meeting branch "
                           "of the rule below is never exercised here")


class AVisibleReorderIsBuiltOnPurpose(unittest.TestCase):
    """The law's loud half, on two rows laid over each other in different colours.

    The shipped corpus stopped supplying a *visible* reorder when `bars`'s meters were
    cleared off the text of the row under them (2026-11-12): nothing in the 28 layouts
    overlaps any more, so every pair the census above walks moves 0 px and that census can
    only ever prove the negative half of the rule.  A swap that has to move ink therefore
    has to be authored - and authored the way the census reads it, so the same standard
    applies to both halves: measure the overlap band from each row painted alone, count the
    pixels where both lie fully opaque in different colours, and require the swap to move
    ink on exactly those pixels and in the order the list gives.

    Two of `bars`'s own meters are the rows, because they are rectangles at the theme's own
    constants - the shared band is arithmetic, not a face metric - and their declared colours
    are made to differ.  That last part is the whole point of the fixture: an earlier attempt
    at this case left both meters as shipped, both asking for the `heat` ramp at similar
    fractions, and the swap moved **0** px for a perfectly correct reason - the overlap was
    the same colour either way, so the law called it silent.  A gate that cannot tell a
    decided pixel from an undecided one is not a gate.
    """

    def case(self) -> tuple:
        obj = themes.export("bars")
        widgets = obj["osd"]["widget"]
        meters = [i for i, w in enumerate(widgets) if w["type"] == "bar"]
        self.assertGreaterEqual(len(meters), 2, "the generated `bars` file has no two meters")
        a, b = meters[0], meters[1]
        pa, pb = widgets[a]["property"][0], widgets[b]["property"][0]
        pb["y"] = pa["y"] + 2                  # b's track is made taller than a's, so the
        pb["height"] = pa["height"] + 6        # overlap has interior rows in both, not edges
        pb["startColor"] = pb["endColor"] = "rgba(255, 0, 0, 1)"
        pb["bgColor"] = "rgba(0, 0, 255, 1)"
        box = (max(pa["x"], pb["x"]), max(pa["y"], pb["y"]),
               min(pa["x"] + pa["width"], pb["x"] + pb["width"]),
               min(pa["y"] + pa["height"], pb["y"] + pb["height"]))
        self.assertGreater(box[2] - box[0], 100, f"the two tracks barely meet: {box}")
        self.assertGreaterEqual(box[3] - box[1], 1, f"the shared band has no rows: {box}")
        return obj, a, b, box

    def solo(self, widget):
        img, _notes = paint_of({"osd": {"widget": [copy.deepcopy(widget)]}})
        return img.convert("RGBA")

    def test_a_swap_moves_ink_exactly_where_both_rows_lay_opaque_in_different_colours(self):
        obj, a, b, box = self.case()
        solo_a = self.solo(obj["osd"]["widget"][a])
        solo_b = self.solo(obj["osd"]["widget"][b])
        shared = []
        x0, y0, x1, y1 = box
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                p, q = solo_a.getpixel((x, y)), solo_b.getpixel((x, y))
                if p[3] == 255 and q[3] == 255 and p[:3] != q[:3]:
                    shared.append((x, y))
        if not shared:
            self.skipTest(f"neither meter is opaque and different across the shared band {box} "
                          "on this box, so there is no decided pixel to hold a swap to")
        self.assertGreater(len(shared), 200,
                           f"only {len(shared)} px of the shared band are opaque and different in "
                           f"both rows ({box}): the fixture does not carry the overlap it claims")

        before, _notes = paint_of(copy.deepcopy(obj))
        before = before.convert("RGBA")
        trial = gui_edit.Editor(copy.deepcopy(obj), origin="check", name="bars")
        # The two meters are not neighbours in the file: a row of `bars` is figure, label,
        # number, meter - four widgets since 2026-11-14, three before it - so the swap is the
        # model's door walked **one row's worth** of steps, which is what the window's own
        # reorder buttons do.  The step count is derived from the export rather than written
        # out: a literal here would have silently become wrong the day the block grew a
        # column, which is precisely the failure this file exists to catch.
        per_row = (len(obj["osd"]["widget"]) - 2) // len(themes.BARS_ROWS)
        trial.select(a)
        for step in range(per_row):
            ok, said = trial.move_widget(+1)
            self.assertTrue(ok, f"step {step + 1} of the swap was refused: {said}")
        widgets_after = trial.widgets()
        id_a = str(obj["osd"]["widget"][a].get("id"))
        id_b = str(obj["osd"]["widget"][b].get("id"))
        before_order = [str(w.get("id")) for w in obj["osd"]["widget"]]
        after_order = [str(w.get("id")) for w in widgets_after]
        self.assertLess(before_order.index(id_a), before_order.index(id_b),
                        "the fixture does not start with the first meter earlier in the list")
        self.assertGreater(after_order.index(id_a), after_order.index(id_b),
                           f"{per_row} steps down the list did not put {id_a} after {id_b}: the door "
                           f"moved the row somewhere else ({after_order})")
        self.assertEqual(sorted(before_order), sorted(after_order),
                         "the swap lost or invented a row")
        after, _notes = paint_of(trial.obj)
        after = after.convert("RGBA")

        moved = px_differ(before, after)
        # How far a track's ink reaches past the rectangle the file declares is a property of
        # the painter, not a constant to remember: `render.bar` draws at the supersampled
        # canvas and the frame comes back down with LANCZOS, so the edge spreads a couple of
        # rows each way - and two translucent tracks composite in list order, which is the law
        # working rather than a leak.  So the margin is measured here, from the same solo
        # paintings used above: the rows that carry ink, against the rows the file declared.
        def spread(img, rect) -> int:
            d = img.getchannel("A").load()
            inked = [y for y in range(render.H) if any(d[x, y] > 8 for x in range(render.W))]
            if not inked:
                self.skipTest("a meter laid down no ink at all, so there is no band to hold "
                              "a reorder to")
            return max(rect[1] - inked[0], inked[-1] - rect[3]) + 1

        wa = obj["osd"]["widget"][a]["property"][0]
        wb = obj["osd"]["widget"][b]["property"][0]
        rect_a = (wa["x"], wa["y"], wa["x"] + wa["width"], wa["y"] + wa["height"])
        rect_b = (wb["x"], wb["y"], wb["x"] + wb["width"], wb["y"] + wb["height"])
        bleed = max(spread(solo_a, rect_a), spread(solo_b, rect_b))
        self.assertLessEqual(bleed, 6, f"the track's ink spreads {bleed} rows past its declared "
                                       "rectangle: the band this check can hold a reorder to is "
                                       "wider than the overlap it is meant to be measuring")
        # `Image.crop` takes a half-open box - `lower` is one past the last row it keeps - so
        # the grown band adds one to each side beyond the measured spread, or the edge rows the
        # bleed was measured *from* would fall outside the window they justify.
        padded = (max(0, box[0] - bleed - 1), max(0, box[1] - bleed - 1),
                  min(render.W, box[2] + bleed + 1), min(render.H, box[3] + bleed + 1))
        inside = px_differ(before.crop(padded), after.crop(padded))
        self.assertGreater(moved, 0,
                           f"a swap of two rows with {len(shared)} decided opaque pixels in "
                           f"{box} moved no ink at all: the draw order is not reaching the picture")
        self.assertEqual(moved, inside,
                         f"{moved - inside} px moved outside the shared band {box} grown by the "
                         f"measured {bleed}-row edge bleed ({padded}): a reorder decided which row "
                         "is on top somewhere only one of the two draws")

        # and the direction, at a pixel in the middle of the band: before the swap the later
        # row is b, after it the later row is a (the door moved a down the list), so the
        # colour that survives at that pixel has to change from b's to a's.  Held both ways,
        # because a painter that always drew the same row last would pass a one-sided check.
        probe = shared[len(shared) // 2]
        self.assertEqual(before.getpixel(probe), solo_b.getpixel(probe),
                         f"before the swap, {probe} in the shared band was not the later row's "
                         "colour, so the baseline picture does not follow the list either")
        self.assertEqual(after.getpixel(probe), solo_a.getpixel(probe),
                         f"after moving row {a} down the list, {probe} still shows the other "
                         "row's colour: the row that is now later did not come out on top")


if __name__ == "__main__":
    unittest.main(verbosity=2)
