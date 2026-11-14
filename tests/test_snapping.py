#!/usr/bin/env python3
"""Feature F: a drag that comes within `SNAP_PX` of a number this file already uses is pulled onto it.

Ported from the snapping block of `tools/selftest.sh`'s GUI section.  Two halves, as every act in
that pane has: the model's doors, measured on real layouts, and the window driving them with Qt
events and painting the model's lines.

The rule splits by what a figure depends on, and that split is the reason the file reads the way
it does:

* **file facts** - how many rows of the 28 layouts declare a number another row of the same file
  declares, and how far apart the nearest other number sits.  Those answer the same on every
  machine, so they are asserted, and they are what makes 2 px a *break* rather than a point on a
  slope: nothing in this corpus sits 1 px from a peer's number, and nothing sits 6 or 7 px away
  either;
* **drawn facts** - which placement a row's ink actually lands at, and how far a wrong-class snap
  would put two rows apart.  Those follow the face the layout resolves to, so they are asserted as
  *relations* with a margin (a cross-class snap must land more than ten SNAP_PX apart, an
  `l` row's `x` must equal its ink's left edge exactly), never as the counts a machine printed.

And one rule the pages state: **an arrow key is not a drag.** A nudge places a row to the pixel and
no line answers for it, which is the only way two rows can end up 1 px apart on purpose.
"""
from __future__ import annotations

import copy
import math
import os
import unittest

from tests import fixtures

from xigmalcd import render, themes
from xigmaui import app
from xigmaui import edit as gui_edit


MISSING_PORT = "/dev/xigma-no-such-port"

#: The layout the doors are driven on: it has a column two of its rows share, which is what a snap
#: needs in order to be observable at all.
COLUMN_LAYOUT = "Theme_07"

#: The layout the cross-class rule is measured on, because the corpus says it carries both an
#: `l` row and an `r` row.
CLASS_LAYOUT = "bars"


def layouts_with_copies() -> list:
    """Every layout this pane can open, each as a copy the caller owns.

    `themes.load` caches one object per (path, mtime) and a draw fills in what the painter reads,
    so a census that drew the shared object would be counting what another check left behind.
    """
    found = [copy.deepcopy(themes.load(rec["path"])) for rec in themes.scan()[0]]
    found += [copy.deepcopy(themes.export(name)) for name in sorted(themes.EXPORTS)]
    return found


def declared(obj: dict) -> list:
    """(x, y) exactly as one file writes them, one entry per row that carries either."""
    out = []
    for widget in (obj.get("osd") or {}).get("widget") or []:
        props = (widget.get("property") or [{}])[0]
        if props.get("x") is None and props.get("y") is None:
            continue
        out.append((int(props["x"]) if props.get("x") is not None else None,
                    int(props["y"]) if props.get("y") is not None else None))
    return out


def drawn_boxes(obj: dict) -> dict:
    """{row index: box} as the painter reports it, drawing at the pinned fixture."""
    notes = themes.draw(copy.deepcopy(obj), dict(gui_edit.FIXTURE), gui_edit.FIXTURE_WHEN)[1]
    return {row[3]: tuple(row[2]) for row in (notes.get("boxes") or []) if row[2]}


class TheFilesLineUpOrTheyDoNot(unittest.TestCase):
    """The census the doors were built from: these files either share numbers or they do not."""

    @classmethod
    def setUpClass(cls):
        cls.objects = layouts_with_copies()
        # The vendor's files and this program's generated ones are two corpora with two
        # different stories to tell, and one check (the gap histogram below) used to mix
        # them.  Their ids separate them cleanly: every layout this repository generates is
        # `xigma-<theme>`, and none of the copied ones is.
        cls.ours = {i for i, obj in enumerate(cls.objects)
                    if str(obj.get("id") or "").startswith("xigma-")}
        cls.declared = []                      # (layout index, x, y)
        for index, obj in enumerate(cls.objects):
            for x, y in declared(obj):
                cls.declared.append((index, x, y))

    def peers(self, index: int, axis: int) -> list:
        """The numbers on one axis that the *other* rows of this row's own file declare."""
        mine = self.declared[index][0]
        column = [row[axis] for row in self.declared]
        return [value for j, value in enumerate(column)
                if j != index and self.declared[j][0] == mine and value is not None]

    def nearest_own_number(self, index: int, axis: int):
        mine = self.declared[index][axis]
        if mine is None:
            return None
        peers = self.peers(index, axis)
        return min((abs(value - mine) for value in peers), default=None)

    def test_the_threshold_is_two_pixels_and_the_pages_say_the_same(self):
        self.assertEqual(gui_edit.Editor.SNAP_PX, 2,
                         "the pages, `edit.py`'s comment and the changelog all quote 2 px; if "
                         "the door moved, the sentences did too")

    def test_the_corpus_shares_columns_on_purpose(self):
        rows = self.declared
        share_x = sum(1 for k in range(len(rows)) if rows[k][1] is not None
                      and rows[k][1] in self.peers(k, 1))
        share_y = sum(1 for k in range(len(rows)) if rows[k][2] is not None
                      and rows[k][2] in self.peers(k, 2))
        same = sum(1 for a in range(len(rows)) for b in range(a + 1, len(rows))
                   if rows[a][0] == rows[b][0]
                   and ((rows[a][1] is not None and rows[a][1] == rows[b][1])
                        or (rows[a][2] is not None and rows[a][2] == rows[b][2])))
        self.assertGreater(share_x, 0, "no two rows of any file share an `x`, so the rule would "
                                       "have nothing to pull onto")
        self.assertGreater(share_y, 0)
        self.assertGreater(same, 0)
        # docs/gui.md quotes these four totals as the reach of the 2 px snap.  Printed here so
        # the page can name the command that re-counts them instead of carrying numbers that go
        # stale the day a layout grows a row (it did, on 2026-11-14: `bars` took a drive row and
        # the census moved 185 -> 188 rows).
        print(f"  snap census: {len(rows)} rows carry an x or y across {len(self.objects)} "
              f"layouts; {share_x} hold an x a peer in the same file holds, {share_y} do the "
              f"same with y; {same} pairs of rows hold one number between them")

    def test_the_corpus_has_no_grid_to_snap_to(self):
        """The other half of the pages' claim: these files have **no grid**, so a snap that
        landed on a tidy multiple would be this program inventing a rule the vendor never wrote.

        Measured with `math.gcd` over every declared coordinate, and printed, because
        docs/gui.md carried the second figure - "27 of 191" - as prose with no command behind
        it, and it went stale the same day the row census did.  A number a page quotes and no
        door reprints is a number that quietly stops being true.
        """
        xs = [row[1] for row in self.declared if row[1] is not None]
        ys = [row[2] for row in self.declared if row[2] is not None]
        gx = xs[0]
        for v in xs[1:]:
            gx = math.gcd(gx, v)
        gy = ys[0]
        for v in ys[1:]:
            gy = math.gcd(gy, v)
        self.assertEqual((gx, gy), (1, 1),
                         f"the corpus's coordinates now share a divisor ({gx}/{gy}): there is a "
                         "grid in these files, and the snap's 2 px reach needs re-arguing "
                         "against it")
        on16 = sum(1 for v in xs if v % 16 == 0)
        self.assertLess(on16, len(xs) // 2,
                        "most of the declared x values sit on a 16 px lattice now: the "
                        "'no grid to snap to' sentence below has to be re-read")
        print(f"  grid census: gcd over {len(xs)} declared `x` and {len(ys)} declared `y` values "
              f"is {gx}/{gy}; {on16} of the `x` values are multiples of 16 "
              f"({len(self.declared)} rows carry an x or a y)")

    def test_two_pixels_is_a_break_in_the_histogram_not_a_point_on_a_slope(self):
        """The two shape claims, not just the totals: nothing sits one pixel from a peer's number,
        and nothing sits 6 or 7 px away either.  That gap is why "2 px" separates 'this file means
        these two to line up' from 'these two are spaced', and why 3 px would argue with the person
        dragging."""
        # ...and only the vendor's rows.  The 2 px argument was measured off ALPHA's files
        # - "nothing sits 1 px from a peer's number, and nothing at 6 or 7 either" - and
        # adding this program's own `birdseye` layout filled the 6 px hole with five rows,
        # which is not a counter-example to the argument about the vendor's conventions:
        # the numbers involved are the **corners of boxes** (an icon's box top sits 6 px
        # from the meter's top because the icon is 20 px tall and the bar is 8), not
        # anchors two rows were meant to share.  Keeping the two corpora in one histogram
        # was the mistake; a generated layout's own grid is checked separately below.
        distances = {}
        rows = [row for row in self.declared if row[0] not in self.ours]
        for k, row in enumerate(self.declared):
            if row[0] in self.ours:
                continue
            gap = self.nearest_own_number(k, 1)
            if gap is not None:
                distances[gap] = distances.get(gap, 0) + 1
        self.assertEqual(distances.get(1, 0), 0,
                         f"something now sits 1 px from a peer's number: {sorted(distances.items())}")
        self.assertEqual(distances.get(6, 0), 0, f"the 6-7 px gap has filled in: {sorted(distances.items())}")
        self.assertEqual(distances.get(7, 0), 0, f"the 6-7 px gap has filled in: {sorted(distances.items())}")
        # the histogram the page reads the 2 px break out of, printed so the figures in
        # docs/gui.md name a command rather than a snapshot
        near = {k: v for k, v in sorted(distances.items()) if k <= 5}
        print(f"  nearest-peer x gap, {len(rows)} vendor rows (the {len(self.ours)} "
              f"generated layouts are excluded here and counted below): {near} px; "
              f"nothing at 1, 6 or 7 px is the claim")

    def test_no_two_numbers_of_our_own_layouts_land_one_pixel_apart(self):
        """What a generated layout does have to guarantee - and it is not the vendor's rule.

        The 2 px threshold was argued from the vendor's files: their rows either share a
        column exactly (0 px) or are spaced by 2..5 px, with nothing at 1, 6 or 7, so 2 px
        sits in a real break in the distribution.  This program's own layouts do not
        participate in that argument - `bars` puts an icon box at x=3, its labels at 28 and
        its values at 452, and `birdseye` mixes a 30 px usage pitch with box corners 6 px
        apart, which is what filled the vendor histogram's 6 px hole the moment the layout
        was added.  Box corners are not anchors: a 20 px icon and an 8 px meter starting 6
        px apart means nothing about intent.

        So the claim kept for our own files is the narrow one that does mean something:
        no two numbers in one generated layout sit exactly 1 px apart.  That distance has
        no interpretation - it is not alignment (0) and not spacing (>= 2), it is a
        near-collision, and it is what a copied-and-nudged coordinate leaves behind.
        """
        chosen = {f"xigma-{name}" for name, origin in themes.GEOMETRY_ORIGIN.items()
                  if origin == "chosen here"}
        self.assertEqual(len(chosen), 2, sorted(chosen))
        checked = 0
        for index, obj in enumerate(self.objects):
            ident = str(obj.get("id"))
            if ident not in chosen:
                continue
            checked += 1
            for axis, label in ((1, "x"), (2, "y")):
                values = sorted({row[axis] for row in self.declared
                                 if row[0] == index and row[axis] is not None})
                gaps = [b - a for a, b in zip(values, values[1:])]
                self.assertTrue(gaps, f"{ident} declares no {label} pairs to compare")
                print(f"  own-grid, {ident:16s} {label}: {len(values)} distinct values, "
                      f"closest pair {min(gaps)} px apart")
                self.assertGreaterEqual(min(gaps), 2,
                                        f"{ident} has two {label} numbers 1 px apart "
                                        f"({values}): a near-collision, neither alignment "
                                        "nor spacing")
        self.assertEqual(checked, len(chosen),
                         f"{sorted(chosen)} are declared as grids of our own, but only "
                         f"{checked} of them are in this corpus")

    def test_three_pixels_is_more_grabbable_than_two_on_this_corpus(self):
        """The prose says a 3 px reach would pull rows onto columns they do not mean; that has to
        stay true of the files, or the sentence about it goes."""
        rows = self.declared

        def pulled(threshold: int) -> int:
            hits = sum(1 for k in range(len(rows)) if rows[k][1] is not None
                       and any(abs(value - (rows[k][1] + 3)) <= threshold
                               for value in self.peers(k, 1)))
            return round(100.0 * hits / len(rows))

        self.assertLess(pulled(2), pulled(3),
                        "3 px is no more grabbable than 2 px on this corpus, so the sentence that "
                        "says otherwise has to go")
        print(f"  a drag pulled onto a peer's number: {pulled(1)}% at 1 px, {pulled(2)}% at 2 px, "
              f"{pulled(3)}% at 3 px of {len(rows)} rows")

    def test_no_row_declares_a_number_on_the_canvas_edge(self):
        edge = sum(1 for _i, x, y in self.declared for value in (x, y)
                   if value is not None and value in (0, render.W - 1, render.H - 1))
        self.assertEqual(edge, 0, "the page says no row declares a number on the canvas edge, and "
                                  "this run found one")

    def test_the_middle_is_one_number_because_every_layout_declares_one_canvas(self):
        """The prose says a snap to the middle means 240.  That is not assumed: it follows because
        every layout this pane opens declares the same canvas."""
        sizes = {(int(obj.get("width") or render.W), int(obj.get("height") or render.H))
                 for obj in self.objects}
        self.assertEqual(len(sizes), 1, f"{sizes}: the layouts this pane opens do not all declare "
                                        "one canvas, so `the middle` is not one number")
        (width, height), = sizes
        at_x = sum(1 for _i, x, _y in self.declared if x == width // 2)
        at_y = sum(1 for _i, _x, y in self.declared if y == height // 2)
        self.assertGreater(at_x, 0, "no row declares the horizontal middle, so a centre snap would "
                                    "be offered to nothing")
        self.assertGreater(at_y, 0)

    def test_rows_mirror_across_the_middle_in_the_files_themselves(self):
        rows = [(i, x) for i, x, _y in self.declared if x is not None]
        middle = render.W // 2
        mirrors = sum(1 for a in range(len(rows)) for b in range(a + 1, len(rows))
                      if rows[a][0] == rows[b][0] and rows[a][1] + rows[b][1] == 2 * middle)
        self.assertGreater(mirrors, 0, "nothing in this corpus mirrors across the middle, so the "
                                       "mirror line the pane offers is answering nothing")


class WhatThePainterAgreesTo(unittest.TestCase):
    """The anchor class, measured against the painter rather than against the key's name."""

    @classmethod
    def setUpClass(cls):
        cls.objects = layouts_with_copies()

    def offsets_by_class(self) -> dict:
        """{class: [(x - ink left, x - ink right, anchor as spelled, kind)]}."""
        out = {"l": [], "m": [], "r": []}
        for obj in self.objects:
            boxes = drawn_boxes(obj)
            for index, widget in enumerate((obj.get("osd") or {}).get("widget") or []):
                props = (widget.get("property") or [{}])[0]
                if index not in boxes or props.get("x") is None:
                    continue
                klass = gui_edit.Editor.anchor_class(widget)
                spelled = str((props.get("xigma") or {}).get("anchor") or "la")
                out[klass].append((int(props["x"]) - boxes[index][0],
                                   int(props["x"]) - boxes[index][2], spelled[0],
                                   str(widget.get("type") or "")))
        return out

    def test_every_anchor_class_the_corpus_uses_has_rows(self):
        counts = {key: len(value) for key, value in self.offsets_by_class().items()}
        self.assertTrue(all(counts[key] for key in counts),
                        f"{counts}: this corpus has no row of one anchor class, so the class rule "
                        "below would be measuring nothing")

    def test_the_class_is_the_anchors_first_letter_and_the_painter_agrees(self):
        for rows in self.offsets_by_class().values():
            for _left, _right, spelled, _kind in rows:
                self.assertEqual(spelled, spelled[0],
                                 "the anchor's first letter is what the class reads, and the "
                                 "painter stopped agreeing with that reading")

    def test_a_left_or_right_anchored_rows_x_is_exactly_its_ink_edge(self):
        """`line` is the one kind exempt: `layout.line_rect` pivots the declared rect about its own
        centre, so a row turned 90° puts its ink somewhere its `x` does not name - which is the
        fact the resize door's `x`/`y` corrections were written from."""
        strict = ("text", "data", "special", "bar", "arc")
        offsets = self.offsets_by_class()
        self.assertTrue(all(row[0] == 0 for row in offsets["l"] if row[3] in strict),
                        f"{[r for r in offsets['l'] if r[0]][:3]}: a left-anchored row's `x` is "
                        "not its ink's left edge on this machine")
        self.assertTrue(all(row[1] == 0 for row in offsets["r"]),
                        f"{[r for r in offsets['r'] if r[1]][:3]}: a right-anchored row's `x` is "
                        "not its ink's right edge on this machine")
        self.assertTrue(all(0 < row[0] < render.W for row in offsets["m"] if row[3] in strict),
                        offsets["m"][:3])

    def test_the_drawn_census_is_not_empty_so_a_relation_can_be_measured_on_it(self):
        """How many pairs of *drawn* boxes share an alignment number, and how many sit on the
        middle, are counts a face produces.  What is held here is that the corpus is rich enough
        for the door above to mean something - not the digits."""
        pairs = aligned = centred_x = centred_y = boxes = 0
        for obj in self.objects:
            rows = list(drawn_boxes(obj).values())
            boxes += len(rows)
            for a in range(len(rows)):
                for b in range(a + 1, len(rows)):
                    pairs += 1
                    left = [rows[a][0], rows[a][2], (rows[a][0] + rows[a][2]) / 2.0,
                            rows[a][1], rows[a][3], (rows[a][1] + rows[a][3]) / 2.0]
                    right = [rows[b][0], rows[b][2], (rows[b][0] + rows[b][2]) / 2.0,
                             rows[b][1], rows[b][3], (rows[b][1] + rows[b][3]) / 2.0]
                    if min(abs(p - q) for p in left for q in right) == 0:
                        aligned += 1
            for box in rows:
                if abs((box[0] + box[2]) / 2.0 - render.W / 2.0) < 0.5:
                    centred_x += 1
                if abs((box[1] + box[3]) / 2.0 - render.H / 2.0) < 0.5:
                    centred_y += 1
        self.assertGreater(pairs, 0, f"{boxes} drawn boxes, no pairs: the census is empty")
        self.assertGreater(aligned, 0, f"of {pairs} pairs of drawn boxes, none shares an alignment "
                                       "number, so the doors are pulling onto nothing")
        self.assertGreater(centred_x + centred_y, 0, "no drawn box sits on the middle of the glass")


class TheDoors(fixtures.FreshConfigRoot):
    """`snap_lines` and `snap_move`, on a layout with a shared column."""

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, None, restore=False)
        self.win.show()
        self.win.ed_name.setCurrentText(COLUMN_LAYOUT)
        fixtures.pump(0.4)
        self.editor = self.win.ed
        self.assertIsNotNone(self.editor, f"opening {COLUMN_LAYOUT} left no editor")
        self.addCleanup(fixtures.close_window, self.win)
        self.limit = gui_edit.Editor.SNAP_PX

    def column_rows(self) -> tuple:
        """(two rows that share one `x`, that `x`, and a third row of the same class far from it)."""
        numbers: dict = {}
        for index, widget in enumerate(self.editor.widgets()):
            props = (widget.get("property") or [{}])[0]
            if props.get("x") is not None:
                numbers.setdefault(int(props["x"]), []).append(index)
        shared = next(row for row in numbers.values() if len(row) > 1)
        target = next(key for key, row in numbers.items() if row is shared)
        klass = gui_edit.Editor.anchor_class(self.editor.widgets()[shared[0]])
        other = next(j for j, widget in enumerate(self.editor.widgets())
                     if j not in shared and gui_edit.Editor.anchor_class(widget) == klass
                     and (widget.get("property") or [{}])[0].get("x") is not None
                     and abs(int((widget.get("property") or [{}])[0]["x"]) - target) > self.limit + 2)
        return shared[0], shared[1], target, other

    def test_what_a_row_is_offered_stays_on_the_glass_and_includes_its_own_files_columns(self):
        _a, _b, target, other = self.column_rows()
        self.editor.select(other)
        lines = self.editor.snap_lines(other, box=self.editor._row_box(self.editor.obj, other))
        self.assertTrue(lines, "no lines offered at all")
        for axis, size in (("x", render.W), ("y", render.H)):
            for value, _style in lines[axis]:
                self.assertTrue(0 <= value < size,
                                f"a {axis} line at {value} is off a {size} px glass")
        self.assertIn(target, [value for value, _style in lines["x"]],
                      "a column this file already holds is not offered to a row that can join it")

    def test_a_drag_that_lands_on_the_reach_is_pulled_onto_the_number_and_says_so(self):
        _a, _b, target, other = self.column_rows()
        self.editor.select(other)
        moved = int(self.editor.prop()["x"])
        lines = self.editor.snap_lines(other, box=self.editor._row_box(self.editor.obj, other))
        got, _y, said = self.editor.snap_move(target + self.limit, int(self.editor.prop()["y"]),
                                              index=other, was=(moved, int(self.editor.prop()["y"])),
                                              lines=lines)
        self.assertEqual(got, target, f"{got}: the pull did not land on the number")
        self.assertTrue(said and "snapped x" in said[0] and "declares `x`" in said[0], said)

    def test_one_pixel_outside_the_reach_moves_nothing_and_says_nothing(self):
        _a, _b, target, other = self.column_rows()
        self.editor.select(other)
        moved = int(self.editor.prop()["x"])
        lines = self.editor.snap_lines(other, box=self.editor._row_box(self.editor.obj, other))
        got, _y, said = self.editor.snap_move(target + self.limit + 1,
                                              int(self.editor.prop()["y"]), index=other,
                                              was=(moved, int(self.editor.prop()["y"])),
                                              lines=lines)
        self.assertEqual((got, said), (target + self.limit + 1, []),
                         f"{got}, {said}: a row outside the reach was moved or talked about")

    def test_the_line_you_were_already_sitting_on_cannot_pull_you_back(self):
        """Break-away: a drag that leaves its own column has to be allowed to leave."""
        a, _b, target, _other = self.column_rows()
        self.editor.select(a)
        stay = self.editor.snap_move(target + 1, int(self.editor.prop()["y"]), index=a,
                                     was=(target, int(self.editor.prop()["y"])),
                                     box=self.editor._row_box(self.editor.obj, a))
        self.assertEqual(stay[0], target + 1, f"{stay}: a snap argued with a drag that left its "
                                              "own line")
        self.assertEqual(stay[2], [], stay[2])

    def test_a_drag_asks_for_its_lines_once_and_motion_events_do_not_redraw_them(self):
        """`snap_lines` reads the painter, so calling it per motion event would cost a frame per
        pixel of travel.  The window asks once on press; this is the cost that promise buys."""
        import time
        _a, _b, _target, other = self.column_rows()
        self.editor.select(other)
        started = time.monotonic()
        lines = self.editor.snap_lines(other)
        found = time.monotonic() - started
        self.assertLess(found, 2.0, f"one frame finding the lines took {found:.2f} s")
        moved = int(self.editor.prop()["x"])
        started = time.monotonic()
        for step in range(30):
            self.editor.snap_move(moved + step, 60, index=other, was=(moved, 60), lines=lines)
        spent = time.monotonic() - started
        self.assertLess(spent, 0.05, f"30 motion events cost {spent * 1000:.0f} ms: something is "
                                     "repainting the lines per event")

    def test_the_mirror_line_costs_ink_the_file_does_not_name_and_lands_on_the_middle(self):
        """A left-anchored row reaches the middle by half its own ink, and only the painter knows
        that width.  The mirrored pair's box centres have to end up on opposite sides."""
        self.editor.select(3)
        got, _y, said = self.editor.snap_move(18, int(self.editor.prop()["y"]), index=3,
                                              was=(int(self.editor.prop()["x"]),
                                                   int(self.editor.prop()["y"])))
        mirror = [line for line in said if "mirror" in line]
        self.assertTrue(mirror, f"no mirror line offered on a layout whose rows do mirror: {said}")
        self.assertIn("whose centre is at", mirror[0])
        self.assertIn("px of ink", mirror[0])
        trial = copy.deepcopy(self.editor.obj)
        ((trial.get("osd") or {}).get("widget") or [])[3]["property"][0]["x"] = got
        boxes = drawn_boxes(trial)
        other_box = self.editor._row_box(self.editor.obj, 5)
        self.assertIsNotNone(other_box, "row 5 of this layout draws no box, so the pair is missing")
        total = (boxes[3][0] + boxes[3][2]) / 2.0 + (other_box[0] + other_box[2]) / 2.0
        self.assertLessEqual(abs(total - render.W), 1,
                             f"the mirror line put the two centres at a sum of {total}: not "
                             f"opposite sides of a {render.W} px glass")


class ACrossClassLineIsRefused(fixtures.FreshConfigRoot):
    """An `r` row snapped onto an `l` row's number would sit half a layout away."""

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        self.win = app.Window(MISSING_PORT, None, restore=False)
        self.win.show()
        self.win.ed_name.setCurrentText(CLASS_LAYOUT)
        fixtures.pump(0.4)
        self.editor = self.win.ed
        self.assertIsNotNone(self.editor, f"opening {CLASS_LAYOUT} left no editor")
        self.addCleanup(fixtures.close_window, self.win)
        self.left = [i for i, w in enumerate(self.editor.widgets())
                     if gui_edit.Editor.anchor_class(w) == "l"]
        self.right = [i for i, w in enumerate(self.editor.widgets())
                      if gui_edit.Editor.anchor_class(w) == "r"]
        self.assertTrue(self.left and self.right,
                        f"{CLASS_LAYOUT} is the layout the corpus says carries both: got "
                        f"{self.left}, {self.right}")

    def test_a_right_anchored_row_is_never_offered_a_left_anchored_rows_number(self):
        offered = {value for value, _style in
                   self.editor.snap_lines(self.right[0],
                                          box=self.editor._row_box(self.editor.obj,
                                                                   self.right[0]))["x"]}
        numbers = {int((self.editor.widgets()[i].get("property") or [{}])[0]["x"])
                   for i in self.left}
        self.assertFalse(offered & numbers,
                         f"{sorted(offered & numbers)}: a right-anchored row was offered a "
                         "left-anchored row's number: they mean different edges")
        own = {int((self.editor.widgets()[i].get("property") or [{}])[0]["x"]) for i in self.right}
        self.assertTrue(own <= offered,
                        "a right-anchored row was not offered the column its own file's "
                        "right-anchored rows hold")

    def test_the_rule_is_worth_it_measured_against_the_ink(self):
        """How far apart would two rows land if the class rule did not exist?  If the answer were a
        few pixels, the rule that refuses those lines would need re-reading."""
        obj = copy.deepcopy(themes.export(CLASS_LAYOUT))
        boxes = drawn_boxes(obj)
        rows = (obj.get("osd") or {}).get("widget") or []
        left = [i for i, w in enumerate(rows) if gui_edit.Editor.anchor_class(w) == "l"
                and (w.get("property") or [{}])[0].get("x") is not None]
        right = [i for i, w in enumerate(rows) if gui_edit.Editor.anchor_class(w) == "r"
                 and (w.get("property") or [{}])[0].get("x") is not None]
        self.assertEqual((left, right), (self.left, self.right),
                         "the pane's live editor and the file's own rows have come apart, so the "
                         "classes measured above are not the ones being drawn here")
        gaps = []
        for i in left:
            for j in right:
                if i not in boxes or j not in boxes:
                    continue      # this row paints no box at this fixture, so it has no ink
                shift = (int((rows[j].get("property") or [{}])[0]["x"])
                         - int((rows[i].get("property") or [{}])[0]["x"]))
                gaps.append(abs((boxes[i][0] + shift) - boxes[j][0]))
        gaps.sort()
        self.assertTrue(gaps, f"{CLASS_LAYOUT} draws no l/r pair, so the class rule measures "
                              "nothing")
        median = gaps[len(gaps) // 2]
        self.assertGreater(median, 10 * gui_edit.Editor.SNAP_PX,
                           f"a cross-class snap would land the ink {gaps[0]}-{gaps[-1]} px apart "
                           f"(median {median}), which is not far enough to need a rule")


class TheWindowDrivesIt(fixtures.FreshConfigRoot):
    """A press on ink, a drag that lands 2 px past a column, and what the pane paints and says.

    The pane has to be at 1:1: at a preview a third of the glass, one widget pixel is three panel
    pixels and a rule about 2 px cannot be driven through a pointer that cannot move by 2.  There
    is no QTest in this environment, so the handlers receive the same `QMouseEvent` and `QKeyEvent`
    objects Qt would hand them, and the pane - not this file - is what turns a point under the
    cursor into panel px.
    """

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        with open(themes.resolve(COLUMN_LAYOUT)["path"], "rb") as handle:
            self.raw = handle.read()
        self.win = app.Window(MISSING_PORT, None, restore=False, save_settings=False)
        self.win.show()
        self.win.resize(1600, 1200)
        fixtures.pump(0.4)
        self.win.ed_name.setCurrentText(COLUMN_LAYOUT)
        fixtures.pump(0.4)
        self.addCleanup(fixtures.close_window, self.win)
        self.editor = self.win.ed
        self.assertIsNotNone(self.editor, f"opening {COLUMN_LAYOUT} left no editor")
        rows = {}
        for index, widget in enumerate(self.editor.widgets()):
            props = (widget.get("property") or [{}])[0]
            if props.get("x") is not None:
                rows.setdefault(int(props["x"]), []).append(index)
        self.pair = next(row for row in rows.values() if len(row) > 1)
        self.target = next(key for key, row in rows.items() if row is self.pair)
        klass = gui_edit.Editor.anchor_class(self.editor.widgets()[self.pair[0]])
        self.mover = next(j for j, widget in enumerate(self.editor.widgets())
                          if j not in self.pair
                          and gui_edit.Editor.anchor_class(widget) == klass
                          and (widget.get("property") or [{}])[0].get("x") is not None
                          and abs(int((widget.get("property") or [{}])[0]["x"]) - self.target)
                          > gui_edit.Editor.SNAP_PX + 2)
        self.moved_from = self.number_of(self.mover)
        self.box = self.editor._row_box(self.editor.obj, self.mover)
        self.assertIsNotNone(self.box, f"row {self.mover} draws no box here, so there is no ink "
                                       "to press on")
        self.point = (self.box[0] + 2, (self.box[1] + self.box[3]) // 2)
        self.win.ed_widget.setCurrentIndex(self.mover)
        fixtures.pump(0.2)

    # ---- Qt's own event objects -------------------------------------------------------------
    def mouse_event(self, which: str, x: int, y: int):
        from PyQt6.QtCore import QEvent, QPointF, Qt as QQt
        from PyQt6.QtGui import QMouseEvent
        kinds = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                 "release": QEvent.Type.MouseButtonRelease}
        pos = QPointF(x, y)
        return QMouseEvent(kinds[which], pos, pos, QQt.MouseButton.LeftButton,
                           QQt.MouseButton.LeftButton, QQt.KeyboardModifier.NoModifier)

    def pane_point(self, px: int, py: int) -> tuple:
        origin_x, origin_y = self.win.preview._origin()
        return int(round(origin_x + px)), int(round(origin_y + py))

    def press(self) -> None:
        x, y = self.pane_point(*self.point)
        self.win.preview.mousePressEvent(self.mouse_event("press", x, y))
        fixtures.pump(0.05)

    def moved_target(self) -> tuple:
        """The pane point that lands this row `SNAP_PX` the wrong side of the column."""
        limit = gui_edit.Editor.SNAP_PX
        return self.pane_point(self.point[0] + (self.target - self.moved_from + limit),
                               self.point[1])

    def drag_onto_column(self) -> None:
        self.press()
        self.assertTrue(self.win._drag, "the press found no row to drag")
        self.assertIsNotNone(self.win._snap_lines, "the press found no lines to snap toward")
        self.assertEqual(self.win._drag[2], self.moved_from, self.win._drag)
        x, y = self.moved_target()
        self.win.preview.mouseMoveEvent(self.mouse_event("move", x, y))
        fixtures.pump(0.05)

    def release_onto_column(self) -> None:
        x, y = self.moved_target()
        self.win.preview.mouseReleaseEvent(self.mouse_event("release", x, y))
        fixtures.pump(0.05)

    def nudge_off_column(self) -> None:
        """One arrow key, one pixel, no line answering for it."""
        from PyQt6.QtCore import QEvent, Qt as QQt
        from PyQt6.QtGui import QKeyEvent
        self.editor.select(self.pair[0])
        self.win.ed_widget.setCurrentIndex(self.pair[0])
        fixtures.pump(0.2)
        self.win.preview.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, QQt.Key.Key_Right,
                                                 QQt.KeyboardModifier.NoModifier))
        fixtures.pump(0.1)

    def number_of(self, index: int) -> int:
        return int((self.editor.widgets()[index].get("property") or [{}])[0]["x"])

    def test_the_pane_is_at_1_1_so_a_pointer_can_move_by_the_reach(self):
        self.assertEqual(self.win.preview.pixmap().width(), render.W,
                         "this drag needs the glass at 1:1; a preview scaled below it cannot be "
                         "driven by a 2 px rule")

    def test_a_drag_two_pixels_past_a_column_lands_on_it_with_the_models_own_sentence(self):
        steps = self.editor.steps
        self.drag_onto_column()
        self.assertTrue(self.win._snap_guide and self.win._snap_guide[0][0] == "x",
                        f"{self.win._snap_guide}: the pane painted no guide for a pull it applied")
        self.assertEqual(self.win.preview.marks[4], self.win._snap_guide,
                         "the guides in the marks are not the ones the drag is pulling toward")
        self.assertEqual(self.number_of(self.mover), self.target,
                         "the drag wrote a number the model did not name")
        self.assertIn("snapped x", self.win.ed_note.text(), self.win.ed_note.text()[:200])
        self.release_onto_column()
        self.assertEqual(self.number_of(self.mover), self.target)
        self.assertEqual(self.editor.steps, steps + 1, "one drag, one undo step")
        self.assertEqual(self.win.preview.marks[4], (),
                         "the guide stayed in the pane after the release")
        self.assertEqual(self.win._ed_ctl("x").value(), self.target,
                         "the field rows do not show where the row landed")

    def test_a_guide_line_never_reaches_the_picture_the_pane_shows(self):
        """Marks are chrome, like the resize handles: what the pane draws for itself is not part of
        the frame it puts on screen."""
        self.drag_onto_column()
        self.assertTrue(self.win._snap_guide)
        with_guide = self.win.preview.pixmap().toImage()
        self.win.preview.set_marks(self.win.preview.marks[:4] + ((),))
        without = self.win.preview.pixmap().toImage()
        self.assertEqual((with_guide.width(), with_guide.height()),
                         (without.width(), without.height()))
        differing = sum(1 for y in range(with_guide.height()) for x in range(with_guide.width())
                        if with_guide.pixelColor(x, y) != without.pixelColor(x, y))
        self.assertEqual(differing, 0, f"{differing} px changed when a guide line was taken out of "
                                       "the marks, so the guide reached the picture")

    def test_an_arrow_key_is_not_a_drag_it_places_the_row_to_the_pixel(self):
        self.drag_onto_column()
        self.release_onto_column()
        self.assertEqual(self.number_of(self.mover), self.target)
        self.nudge_off_column()
        self.assertEqual(self.number_of(self.pair[0]), self.target + 1,
                         "a 1 px nudge was moved by a snap - a keypress that did nothing the "
                         "cursor asked for")
        self.assertEqual((self.number_of(self.pair[0]), self.number_of(self.mover)),
                         (self.target + 1, self.target),
                         "the nudge left its row 1 px off the column, and the drag left its row on "
                         "it - which is the whole difference between a key and a snap")

    def test_two_acts_on_two_rows_are_two_steps_and_each_undo_goes_back_over_one(self):
        self.drag_onto_column()
        self.release_onto_column()
        self.nudge_off_column()
        self.assertEqual(self.editor.steps, 2, f"{self.editor.steps}: the two acts above did not "
                                               "leave two steps")
        self.win.ed_undo.click()
        fixtures.pump(0.2)
        self.assertEqual((self.number_of(self.pair[0]), self.number_of(self.mover)),
                         (self.target, self.target),
                         "undo went back over the drag, not the 1 px nudge")
        self.win.ed_undo.click()
        fixtures.pump(0.2)
        self.assertEqual(self.number_of(self.mover), self.moved_from,
                         "the drag itself did not go back as one step")
        self.assertEqual(self.editor.steps, 0)

    def test_the_whole_pass_left_the_vendors_file_alone_and_the_user_root_empty(self):
        """Nothing here saves, so the file on disk is still the bytes it was read from, and no copy
        appeared under `~/.config/xigmalcd/themes`."""
        self.drag_onto_column()
        self.release_onto_column()
        self.nudge_off_column()
        with open(themes.resolve(COLUMN_LAYOUT)["path"], "rb") as handle:
            self.assertEqual(handle.read(), self.raw,
                             "a drag the window never saved still reached the vendor's file")
        self.assertEqual(themes.user_copies(), [], themes.user_copies())


if __name__ == "__main__":
    unittest.main(verbosity=2)
