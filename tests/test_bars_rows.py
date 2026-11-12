#!/usr/bin/env python3
"""`bars` from both sides: what the painter writes, and what the source table says it should.

Ported from the `tools/selftest.sh` section that read `render.theme_bars`'s own body and then
counted ink in its ten rows.  The section also asserted sentences about `docs/theme-editor.md` and
`docs/limits.md` quoting the same pitch; that class of gate is gone in 0.7 - the pages name the
command that prints the figure, and no check re-reads a page.

Why both sides, when one of them draws the picture anyway: `bars` is the one theme that is still
code-drawn rather than exported to a layout file, so the only thing tying its rows to the rest of
this program is that its strings come out of the same source table every other theme uses.  The
drawing is asked what it painted by handing `ImageDraw.text` a spy for the duration of one frame -
the strings are taken **out of the drawing**, never restated here - and the source table is asked
what it would print, row for row, in the same order.  Two tests are needed because the drawing has
had two rules since 2026-11-09: a **label belongs to the row's subject** (a fixed row's metric
exists on a box of this shape whether or not this reading answers it, and a fan slot exists where
`sensors` reported a tachometer at that position) while a **number belongs to the reading**.
Keeping them apart is what stops that split from being a story about the code.

Six rules:

* the body holds the arithmetic the plan describes, at the geometry the plan names;
* the fan rows are reserved positional slots in the body that draws them, with the label cut to
  the same 10 characters the drawing cuts;
* the pitch is the same whether this box reports six fans or none - the drawing reserves the
  slots rather than compacting around them;
* a row below a missing reading keeps its place, which is the compaction that was deliberately
  removed;
* a box that answers nothing draws no row at all (and the title and the clock line are not counted
  as rows);
* every `source` name this program can answer has a display shape in `layout.VENDOR_FORMAT`, so a
  text row can never reach the painter and die for want of one.

The pixel counts in the slot census are thresholds with a margin, not exact figures: text in the
value column measures 100 px or more of alpha there, the faint tail of the meter above it never
reaches 20, and the cut is at 40.  A font change that moved those by less than the margin leaves
the answer alone, which is the point of counting it that way.
"""
from __future__ import annotations

import datetime
import inspect
import unittest
from PIL import ImageDraw

from tests import fixtures

from xigmalcd import layout, render, themes

#: The pitch rule `docs/theme-editor.md` describes, spelled as the body writes it.  This is a
#: claim about the source text, and it is here because the arithmetic being *named* somewhere
#: else is not the same as the arithmetic being *used*.
PITCH_RULE = "row_h = min(BARS_ROW_MAX, max(BARS_ROW_MIN, span // max(len(rows), 1)))"

#: The three markers that make the fan rows positional slots rather than a repeat group.
SLOT_MARKERS = ('for slot in range(BARS_SLOTS)', '(fan or {}).get("value")',
                'str((fan or {}).get("name") or f"FAN {slot + 1}")[:10]')

#: A body that answers all six fixed rows and reports no tachometer at all.
ALL_SIX = {"cpu": {"temperature": 57.0, "load": 62.0},
           "gpu": {"temperature": 47.0, "load": 22.0, "memoryUsage": 4096,
                   "dedicatedTotal": 8192},
           "motherboard": {"temperature": 51.0},
           "memory": {"used": 10240, "total": 16384}, "timestamp": {}}

#: A body missing three of the six: the rows below the gap have to stay where they are.
PARTIAL = {"cpu": {"temperature": 57.0, "load": 62.0}, "gpu": {"temperature": 47.0},
           "memory": {"used_percent": 41.0}, "timestamp": {}}

#: The instant the source table is asked about, pinned: a `bars` frame carries a clock.
WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)

FANS_SIX = [{"name": f"Fan {i} on this box", "value": 900 + i, "type": "Fan"}
            for i in range(6)]
FANS_TWO = [{"name": "Fan CPU", "value": 2000, "type": "Fan"},
            {"name": "Fan System 5", "value": 0, "type": "Fan"}]

ROWS_TOTAL = len(themes.BARS_FIXED_ROWS) + render.BARS_SLOTS


def pitch_of(rows: int = ROWS_TOTAL) -> int:
    """The row pitch this body computes for `rows` rows - the arithmetic the plan names."""
    return min(render.BARS_ROW_MAX, max(render.BARS_ROW_MIN, render.BARS_SPAN // max(rows, 1)))


def drawn_rows(metrics: dict) -> tuple:
    """Every string `bars` paints in its label and value columns, in draw order.

    The strings are taken out of the painting itself: `ImageDraw.text` is spied on for the length
    of one frame, and the spy keeps only the two columns the rows own, so the title and the clock
    line cannot be mistaken for rows.
    """
    seen, real = [], ImageDraw.ImageDraw.text

    def spy(self, xy, txt, *args, **kw):
        seen.append((int(xy[0] // render.SS), int(xy[1] // render.SS), str(txt)))
        return real(self, xy, txt, *args, **kw)

    ImageDraw.ImageDraw.text = spy
    try:
        img = render.draw(metrics, "bars", bg=render.OVERLAY)
    finally:
        ImageDraw.ImageDraw.text = real
    return ([t for x, _y, t in seen if x in (render.BARS_LBL_X, render.BARS_VAL_X)], img)


def wanted_rows(metrics: dict) -> tuple:
    """What the source table says each row shows, and which rows carry a number."""
    values, _gone = themes.values(metrics, WHEN)
    fans = (metrics or {}).get("fans") or []
    name_of = {speed: name for speed, name in themes.FAN_SLOTS}
    want, answered = [], []
    for label, bar_src, text_src, _lo, _hi in themes.BARS_ROWS:
        if label is None:                       # a fan slot: its name is a reading too
            if int(bar_src.split()[1]) - 1 < len(fans):
                want.append(layout.text_for(name_of[bar_src], values[name_of[bar_src]]))
        else:                                   # a fixed row has its metric either way
            want.append(label)
        filled = bar_src in values and text_src in values
        answered.append(filled)
        if filled:
            want.append(layout.text_for(text_src, values[text_src]))
    return want, answered


def slots_with_ink(img) -> list:
    """Which of the ten rows has value text in it, counted in the right-hand value column.

    Two geometric facts decide the window, and both are stated rather than tuned away: a meter
    sits `BARS_BAR_DY` below its row's centre and its track is opaque across the whole width, so
    at a 32 px pitch a window centred on a row would be stolen by the meter of the row above -
    the window starts 4 px above the centre, below that intrusion.  And the downscale leaves a
    dozen faint pixels of that track in the next slot, which is why ink here means 40 pixels and
    not one: text in this column counts 100 or more, and the tail never reaches 20.
    """
    pitch = pitch_of()
    out = []
    for i in range(ROWS_TOTAL):
        yc = render.BARS_Y0 + i * pitch
        out.append(sum(1 for y in range(yc - 4, yc + 10) for x in range(440, 453)
                       if img.getpixel((x, y))[3]) >= 40)
    return out


class TheBodyItself(unittest.TestCase):
    """What `render.theme_bars` is made of, read out of its own source."""

    @classmethod
    def setUpClass(cls):
        cls.src = inspect.getsource(render.theme_bars)

    def test_the_pitch_rule_and_the_block_are_the_ones_the_page_names(self):
        self.assertIn(PITCH_RULE, self.src, "the pitch rule is not in `theme_bars`")
        self.assertIn("y, span = BARS_Y0, BARS_SPAN", self.src,
                      "the block is not the named 72 + span")
        self.assertEqual((render.BARS_Y0, render.BARS_SPAN, render.BARS_ROW_MIN,
                          render.BARS_ROW_MAX), (72, 320, 28, 56),
                         "the row geometry the page describes is not what the drawing names")

    def test_the_fan_rows_are_reserved_positional_slots(self):
        for marker in SLOT_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.src, "the fan rows are not reserved positional slots")

    def test_the_row_set_is_the_six_plus_the_slots_the_plan_describes(self):
        """The count of formatters in the body is the shape of the row table: six fixed rows and
        one expression that the slot loop reuses.  A seventh fixed row, or a slot drawn by its own
        copy of the formatter, changes that count - and the pitch census below would then be
        counting a different number of rows."""
        self.assertEqual(self.src.count("lambda v:"), len(themes.BARS_FIXED_ROWS) + 1,
                         f"{self.src.count('lambda v:')} formatters, "
                         f"{len(themes.BARS_FIXED_ROWS)} fixed rows")
        self.assertEqual(ROWS_TOTAL, 10, ROWS_TOTAL)


class WhatTheGlassHolds(unittest.TestCase):
    """The rows as painted: reserved places, and strings that agree with the source table."""

    def test_the_pitch_answers_the_same_whether_the_box_reports_six_fans_or_none(self):
        """The reservation is the whole point of 2026-11-09's change: a box with four fewer
        tachometers gets the same ten places, not a tighter stack."""
        self.assertEqual(pitch_of(), render.BARS_SPAN // ROWS_TOTAL, pitch_of())
        self.assertEqual(pitch_of(), 32, "the pitch moved off 32 px, so every window in this "
                                         "file's pixel census is counting a different row")
        none = slots_with_ink(render.draw(ALL_SIX, "bars", bg=render.OVERLAY))
        six = slots_with_ink(render.draw(dict(ALL_SIX, fans=FANS_SIX), "bars",
                                         bg=render.OVERLAY))
        self.assertEqual(none, [True] * len(themes.BARS_FIXED_ROWS) + [False] * render.BARS_SLOTS,
                         "a box with no fans no longer reserves the slots it is not drawing")
        self.assertEqual(six, [True] * ROWS_TOTAL,
                         "the fifth fan onward is not being kept out of the reserved slots")

    def test_a_row_below_a_missing_reading_keeps_its_place(self):
        """The compaction that was removed on purpose: with three of the six fixed rows
        unanswered, the rows that are drawn stay in their slots rather than closing up."""
        got = slots_with_ink(render.draw(PARTIAL, "bars", bg=render.OVERLAY))
        self.assertEqual(got, [True, True, False, True] + [False] * (ROWS_TOTAL - 4),
                         (got, "rows below a missing reading closed up again"))

    def test_a_box_that_answers_nothing_draws_no_row(self):
        self.assertEqual(slots_with_ink(render.draw({"cpu": {}, "timestamp": {}}, "bars",
                                                     bg=render.OVERLAY)),
                         [False] * ROWS_TOTAL,
                         "a box that answers nothing is drawing a row somewhere - or the title "
                         "and the clock line are being counted as rows")

    def test_every_string_the_painter_writes_is_the_source_tables_string(self):
        """Four shapes of box, both doors, compared in order.

        `bars` is the theme that has to earn its keep as code: if a string it paints ever stopped
        being the string `layout.text_for` produces from the same source name, then the generated
        version of this theme would be a different picture and the parity claims this repository
        makes about exports would not cover it.
        """
        cases = (("all six answered, no fans", ALL_SIX),
                 ("three of the fixed six", PARTIAL),
                 ("six plus six reported fans", dict(ALL_SIX, fans=FANS_SIX)),
                 ("two fans, the second reporting zero", dict(PARTIAL, fans=FANS_TWO)))
        for tag, metrics in cases:
            with self.subTest(box=tag):
                got, _img = drawn_rows(metrics)
                want, _answered = wanted_rows(metrics)
                self.assertEqual(got, want, f"{tag}: the strings `bars` paints are not the ones "
                                           f"the source table would print")

    def test_the_rows_the_source_table_answers_are_the_rows_with_ink(self):
        """Which rows carry a number, counted from the table and from the pixels, must be the
        same list - including a fan row whose subject exists while its reading does not, which
        draws its name and nothing else."""
        for tag, metrics in (("all six answered, no fans", ALL_SIX),
                             ("three of the fixed six", PARTIAL),
                             ("six plus six reported fans", dict(ALL_SIX, fans=FANS_SIX)),
                             ("two fans, the second reporting zero", dict(PARTIAL, fans=FANS_TWO))):
            with self.subTest(box=tag):
                _strings, img = drawn_rows(metrics)
                _want, answered = wanted_rows(metrics)
                self.assertEqual(slots_with_ink(img), answered,
                                 (tag, slots_with_ink(img), answered,
                                  "the rows the source table answers are not the rows the "
                                  "drawing leaves ink in"))


class TheDisplayShapes(unittest.TestCase):
    """A `data` row names a source and nothing else, so the shape of its text is this program's."""

    def test_every_answerable_source_has_a_display_shape(self):
        """No text row may reach the painter for want of a format.  A source that enters
        `themes.source_names()` without an entry here is a row that would print nothing at all,
        and the failure names it."""
        unshaped = [name for name in themes.source_names() if name not in layout.VENDOR_FORMAT]
        self.assertEqual(unshaped, [], f"every source this program answers needs a display "
                                       f"shape: {unshaped}")
        self.assertGreater(len(layout.VENDOR_FORMAT), len(themes.source_names()),
                           "the table has no more shapes than there are sources, so it is "
                           "probably not covering the fan names any more")


def rows_by_slot(metrics: dict) -> dict:
    """Every string `bars` writes, grouped by the row band it lands in.

    The value column's ink window wants 40 px of alpha, and a number reading `0 GB` is narrower
    than that: for the two memory rows the exact strings are the evidence, not the ink count.
    """
    seen, real = [], ImageDraw.ImageDraw.text

    def spy(self, xy, txt, *args, **kw):
        seen.append((int(xy[0] // render.SS), int(xy[1] // render.SS), str(txt)))
        return real(self, xy, txt, *args, **kw)

    ImageDraw.ImageDraw.text = spy
    try:
        render.draw(dict(metrics, timestamp={}), "bars", bg=render.OVERLAY)
    finally:
        ImageDraw.ImageDraw.text = real
    pitch = pitch_of()
    out: dict = {}
    for x, y, t in seen:
        if x in (render.BARS_LBL_X, render.BARS_VAL_X):
            out.setdefault((y - render.BARS_Y0) // pitch, []).append(
                ("label" if x == render.BARS_LBL_X else "value", t))
    return out


#: The five memory shapes the 2026-11-09 diff hunt turned up: a GPU with both figures, a GPU at
#: exactly 0 used, memory with no total, memory with no used, and both at zero.  Each of these
#: either raised inside the frame loop or dropped a row that should have stayed.
MEMORY_CASES = (
    ("a GPU with used and total", ALL_SIX),
    ("a GPU reporting 0 used", dict(ALL_SIX, gpu={"temperature": 47.0, "load": 22.0,
                                                  "memoryUsage": 0, "dedicatedTotal": 8192})),
    ("memory used, no total", dict(ALL_SIX, memory={"used": 10240})),
    ("memory total, no used", dict(ALL_SIX, memory={"total": 16384})),
    ("memory both zero", dict(ALL_SIX, memory={"used": 0, "total": 0})),
)

#: What an integrated GPU does: a used figure and no dedicated total to divide it by.
INTEGRATED_GPU = {"temperature": 47.0, "load": 22.0, "memoryUsage": 4096}


class TheGeneratedFile(unittest.TestCase):
    """What `themes.bars_recipe()` writes, counted from the row table rather than remembered."""

    @classmethod
    def setUpClass(cls):
        cls.obj = themes.export("bars")
        cls.widgets = cls.obj["osd"]["widget"]

    def test_the_export_is_the_heading_the_clock_and_three_widgets_per_row(self):
        self.assertEqual(len(self.widgets), 2 + 3 * len(themes.BARS_ROWS),
                         "the export is not the heading, the clock and three widgets per "
                         "`themes.BARS_ROWS` entry")
        kinds: dict = {}
        for w in self.widgets:
            kinds[w["type"]] = kinds.get(w["type"], 0) + 1
        self.assertEqual(kinds, {"text": 1 + len(themes.BARS_FIXED_ROWS),
                                 "data": 1 + len(themes.BARS_ROWS) + len(themes.FAN_SLOTS),
                                 "bar": len(themes.BARS_ROWS)}, kinds)

    def test_each_rows_three_widgets_answer_for_the_same_place_on_the_glass(self):
        """The label and the number share the row's centre; the meter hangs `BARS_BAR_DY` under
        it.  That is the offset both doors use, and it is why the three are not one assertion: a
        file that put the meter at the row's own y would still draw, and every bar would sit on
        top of its own number."""
        pitch = render.BARS_SPAN // len(themes.BARS_ROWS)
        for i, (label, bar_src, text_src, lo, hi) in enumerate(themes.BARS_ROWS):
            y = render.BARS_Y0 + i * pitch
            lbl, num, meter = (self.widgets[1 + 3 * i], self.widgets[2 + 3 * i],
                               self.widgets[3 + 3 * i])
            with self.subTest(row=i):
                self.assertEqual((lbl["type"] == "text"), label is not None)
                self.assertEqual(num["property"][0]["source"], text_src)
                self.assertEqual(meter["property"][0]["source"], bar_src)
                self.assertEqual((meter["property"][0]["minValue"],
                                  meter["property"][0]["maxValue"]), (lo, hi))
                self.assertEqual(lbl["property"][0]["y"], y)
                self.assertEqual(num["property"][0]["y"], y,
                                 "the number moved off the label's line")
                self.assertEqual(meter["property"][0]["y"], y + render.BARS_BAR_DY,
                                 "the meter's offset from its row is no longer the constant "
                                 "both doors use")
                ext = num["property"][0].get("xigma") or {}
                self.assertEqual(("showIf" in ext), text_src != bar_src,
                                 "the key that says *when* a number draws is on the wrong half "
                                 "of a row whose meter and number divide one pair")
                if label is None:
                    self.assertEqual(lbl["property"][0]["source"], themes._FAN_NAME[bar_src],
                                     "a fan slot's label is not reading the name its box reports")
                else:
                    self.assertEqual(lbl["property"][0]["content"], label)

    def test_every_meter_is_one_convention_and_the_file_validates_clean(self):
        for w in self.widgets:
            if w["type"] == "bar":
                ext = w["property"][0].get("xigma") or {}
                self.assertEqual(ext.get("barPaint"), "render", w["property"][0].get("id"))
                self.assertEqual(ext.get("colourRamp"), "heat", w["property"][0].get("id"))
        hard, _soft = themes.validate(self.obj)
        self.assertEqual(hard, [], hard)

    def test_both_memory_rows_divide_through_one_function(self):
        """The asymmetry that caused the original trouble: one row's test required its numerator
        to be truthy, so a reading of exactly 0 dropped that row while the other kept it.  One
        function now, and the body has to say so."""
        # `render.theme_bars` is the drawing those rows describe: the file says what the
        # division is, and the body that paints it has to do it through one function
        src = inspect.getsource(render.theme_bars)
        self.assertIn('pct_pair(mem, "used", "total")', src)
        self.assertIn('pct_pair(gpu, "memoryUsage", "dedicatedTotal")', src)


class TheMemoryRows(unittest.TestCase):
    """The two rules the diff hunt turned up, measured at the readings that found them."""

    def test_parity_holds_at_every_memory_shape_that_broke_a_row(self):
        for tag, metrics in MEMORY_CASES:
            with self.subTest(reading=tag):
                got = themes.parity("bars", dict(metrics, timestamp={}), WHEN)
                self.assertEqual(got["diff_px"], 0, (tag, got))
                self.assertEqual(got["worst_channel_delta"], 0, (tag, got))
                self.assertGreater(got["code_px"], 0, (tag, "nothing was drawn either way"))
                self.assertEqual(got["code_px"], got["layout_px"], (tag, got))

    def test_a_total_with_no_used_reading_keeps_its_label_and_draws_no_number(self):
        """`KeyError` used to be raised inside the frame loop at this reading - a total, no used.
        The row keeps its label and leaves its number and its meter undrawn."""
        body = dict(ALL_SIX, memory={"total": 16384})
        rows = rows_by_slot(body)
        self.assertEqual(rows.get(4), [("label", "RAM")],
                         "the RAM row drew a number for a numerator that was never reported - "
                         "or `pct_pair` still raises")
        self.assertEqual([t for c, t in rows.get(5, []) if c == "value"], ["4 GB"], rows.get(5))
        self.assertFalse(slots_with_ink(render.draw(dict(body), "bars", bg=render.OVERLAY))[4],
                         "the value column has ink in a row whose number is not drawn")

    def test_a_gpu_at_exactly_zero_used_keeps_its_row_at_nothing_filled(self):
        """The other half of the asymmetry: a 0 reading is a reading.  The number stays, and it
        reads `0 GB`."""
        rows = rows_by_slot(dict(ALL_SIX, gpu={"temperature": 47.0, "load": 22.0,
                                               "memoryUsage": 0, "dedicatedTotal": 8192}))
        self.assertEqual([t for c, t in rows.get(5, []) if c == "value"], ["0 GB"],
                         "a GPU at 0 used dropped its row again - the asymmetry between the two "
                         "memory rows is back")

    def test_a_zero_denominator_is_not_a_pair_to_divide(self):
        rows = rows_by_slot(dict(ALL_SIX, memory={"used": 0, "total": 0}))
        self.assertEqual(rows.get(4), [("label", "RAM")], "a zero denominator drew a RAM row")


class TheKeyThatNamesTheDependency(unittest.TestCase):
    """What `xigma.showIf` is worth, measured by taking it away."""

    def test_exactly_the_two_memory_number_rows_carry_the_key(self):
        obj = themes.export("bars")
        held = [w for w in obj["osd"]["widget"] if "showIf" in (w["property"][0].get("xigma") or {})]
        self.assertEqual(len(held), 2,
                         f"{len(held)} rows carry it: the recipe says two memory rows divide a "
                         "pair while printing a single figure")

    def test_stripping_the_key_changes_the_picture_at_an_integrated_gpu(self):
        """A used figure and no total to divide it by: with the key the row is silent, without it
        the number prints beside an absent meter - 706 px and a worst channel of 255 on this
        bench.  What is asserted is that the difference is not zero, because that is the whole
        reason the key exists; how big it is follows the faces installed and is not quoted here."""
        obj = themes.export("bars")
        stripped = 0
        for w in obj["osd"]["widget"]:
            if "showIf" in (w["property"][0].get("xigma") or {}):
                del w["property"][0]["xigma"]["showIf"]
                stripped += 1
        self.assertEqual(stripped, 2, "nothing was stripped, so this compares one file with itself")

        body = dict(ALL_SIX, gpu=dict(INTEGRATED_GPU))
        values, _gone = themes.values(body, WHEN)
        values = themes.fill_lines(values, body)
        real_now = render._now
        render._now = lambda: WHEN.timetuple()
        try:
            code = render.draw(body, "bars")
        finally:
            render._now = real_now
        file_img, _notes = layout.draw_theme(obj, values, canvas=(render.W, render.H),
                                             specials=themes.SPECIALS)
        px, worst = fixtures.differ(code, file_img)
        self.assertGreater(px, 0, "stripping `showIf` changed nothing, so the key is not doing "
                                  "the work the recipe says it does")
        self.assertGreater(worst, 0, "the difference is invisible in every channel")


class TheReviewDoor(unittest.TestCase):
    """`--check-theme bars` says what it cannot answer, and its two lists have to agree."""

    @classmethod
    def setUpClass(cls):
        got = fixtures.run("python", "-m", "xigmalcd", "--check-theme", "bars")
        if got.returncode not in (0, 2):
            raise AssertionError(f"--check-theme bars exited {got.returncode}: "
                                 f"{got.stdout[-1200:]}{got.stderr[-1200:]}")
        cls.out = got.stdout.splitlines()
        cls.obj = themes.export("bars")

    def asked_deps_guarded(self) -> tuple:
        asked = {w["property"][0]["source"] for w in self.obj["osd"]["widget"]
                 if w["property"][0].get("source")}
        deps = {(w["property"][0].get("xigma") or {}).get("showIf")
                for w in self.obj["osd"]["widget"]} - {None}
        guarded = {w["property"][0]["source"] for w in self.obj["osd"]["widget"]
                   if (w["property"][0].get("xigma") or {}).get("showIf")}
        return asked, deps, guarded

    def cannot_and_skipped(self) -> tuple:
        line = next((ln for ln in self.out if "cannot:" in ln), "")
        cannot = {s.strip() for s in line.split("cannot:", 1)[1].split(",") if s.strip()}
        row = next(ln for ln in self.out if " boxes," in ln)
        tail = row.split("skipped:", 1)[1] if "skipped:" in row else ""
        skipped = set() if not tail.strip() or tail.strip() == "nothing" else \
            {s.strip() for s in tail.split(",") if s.strip()}
        return cannot, skipped

    def test_the_report_says_the_widget_count_it_painted(self):
        self.assertIn(f"{len(self.obj['osd']['widget'])} widgets", self.out[0], self.out[0])

    def test_every_skip_reason_is_a_reading_a_face_or_a_dependency(self):
        asked, _deps, _guarded = self.asked_deps_guarded()
        _cannot, skipped = self.cannot_and_skipped()
        odd = [n for n in skipped
               if not (n.startswith("showIf:") or n.startswith("font:") or n in asked)]
        self.assertEqual(odd, [], "the review door reported something that is neither a reading "
                                  f"this file asks for, nor a dependency, nor a face: {odd}")

    def test_a_row_silenced_by_its_dependency_leaves_the_source_in_cannot_with_no_skip(self):
        """The relation the GitHub runner hit: a box with no GPU at all, `Used GPU Memory`
        unanswerable, and the row already gone before its own source could be called skipped."""
        _asked, deps, guarded = self.asked_deps_guarded()
        cannot, skipped = self.cannot_and_skipped()
        if not cannot and not skipped:
            raise unittest.SkipTest("this box answers every source `bars` asks for, so there is "
                                    "no unanswered reading here to relate - the relation this "
                                    "check holds is the one a runner with no GPU hits")
        skip_src = ({n[len("showIf:"):] for n in skipped if n.startswith("showIf:")}
                    | {n for n in skipped if not n.startswith(("showIf:", "font:"))})
        self.assertTrue(skip_src <= cannot,
                        "a row was skipped for a reading this box says it answered")
        silent = cannot - skip_src
        self.assertTrue(silent <= guarded,
                        "a source sits in `cannot:` with no skip behind it and no `showIf` "
                        "standing in for it")
        notes = {n[len("showIf:"):] for n in skipped if n.startswith("showIf:")}
        lacking = {d for d in deps if d in cannot}
        self.assertTrue(lacking <= notes,
                        "a dependency this box lacks never arrived as a `showIf:<source>` note")


if __name__ == "__main__":
    unittest.main()
