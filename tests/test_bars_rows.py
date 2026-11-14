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
  text row can never reach the painter and die for want of one - **and the converse**, because
  that direction was unguarded and cost the owner a GPU-fan row: a name with a shape and no
  entry in `themes.SOURCES` is a hole with no reason next to it, which is how `GPU Fans Speed`
  sat formatted-but-unaskable from 0.5 until 2026-11-14;
* a row's number and its meter describe the same reading at the same scale, so a figure cannot
  sit beside a track that means something else (`15 GB` at 97 % and a percent on an RPM scale
  are the two shapes this took).

The pixel counts in the slot census are thresholds with a margin, not exact figures: text in the
value column measures 100 px or more of alpha there, the faint tail of the meter above it never
reaches 20, and the cut is at 40.  A font change that moved those by less than the margin leaves
the answer alone, which is the point of counting it that way.
"""
from __future__ import annotations

import copy
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

#: A body that answers every labelled row and reports no tachometer at all.  `gpu.fan` is a
#: duty percent (NVML's unit, PROTOCOL.md §10) and it belongs here for the same reason the
#: drive rows do: a labelled row the body does not answer is a hole this file would then be
#: measuring, not a reading.
ALL_SIX = {"cpu": {"temperature": 57.0, "load": 62.0},
           "gpu": {"temperature": 47.0, "load": 22.0, "fan": 34.0, "memoryUsage": 4096,
                   "dedicatedTotal": 8192},
           "motherboard": {"temperature": 51.0}, "disk": {"temperature": 44.0},
           "drives": [{"name": "nvme0", "temperature": 44, "sensors": [44, 55, 68]},
                      {"name": "nvme1", "temperature": 33, "sensors": [33]}],
           "memory": {"used": 10240, "total": 16384}, "timestamp": {}}

#: A body missing several labelled rows - BOARD, DISK, RAM and VRAM: the rows below each gap
#: have to stay where they are.
PARTIAL = {"cpu": {"temperature": 57.0, "load": 62.0}, "gpu": {"temperature": 47.0},
           "memory": {"used_percent": 41.0}, "timestamp": {}}

#: The instant the source table is asked about, pinned: a `bars` frame carries a clock.
WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)

FANS_SIX = [{"name": f"Fan {i} on this box", "value": 900 + i, "type": "Fan"}
            for i in range(6)]
FANS_TWO = [{"name": "Fan CPU", "value": 2000, "type": "Fan"},
            {"name": "Fan System 5", "value": 0, "type": "Fan"}]

#: The row count `bars` draws: the six fixed readings, the drive row added 2026-11-14, and
#: four reserved fan slots.  Derived so a row cannot be inserted in one place and forgotten in
#: another; pinned once, in the census below, where the number is what is being claimed.
ROWS_TOTAL = len(themes.BARS_ROWS)

#: The pitch those rows compute: `BARS_SPAN // ROWS_TOTAL`, inside the shipped clamp.  Named
#: because every pixel window in this file is measured in row bands, and 320 // 10 = 32 stopped
#: being the answer when the drive row went in (2026-11-14): it is 29 now, and the clamp at
#: `BARS_ROW_MIN` is what keeps a twelfth row from spilling past the block.
PITCH = min(render.BARS_ROW_MAX, max(render.BARS_ROW_MIN, render.BARS_SPAN // ROWS_TOTAL))


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
    """What the source table says each row shows, and which rows carry a number.

    One rule for every slot row, fan or drive: the name is asked of `themes.values()` and the
    answer says whether the slot is filled.  The version before this one rebuilt the map from
    `FAN_SLOTS` and counted `metrics["fans"]` by hand, which is a second copy of the rule - and
    the second copy is what raised `KeyError: 'Disk 1 Temperature'` the day the drive slots
    arrived, exactly as the same mistake has been caught here a dozen times.
    """
    values, _gone = themes.values(metrics, WHEN)
    want, answered = [], []
    for label, bar_src, text_src, _lo, _hi in themes.BARS_ROWS:
        if label is None:                       # a slot row: its name is a reading too
            name_src = themes.SLOT_NAMES[bar_src]
            if name_src in values:
                want.append(layout.text_for(name_src, values[name_src]))
        else:                                   # a fixed row has its metric either way
            want.append(label)
        filled = bar_src in values and text_src in values
        answered.append(filled)
        if filled:
            want.append(layout.text_for(text_src, values[text_src]))
    return want, answered


def slots_with_ink(img) -> list:
    """Which row has value text in it, counted in the right-hand value column.

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
                          render.BARS_ROW_MAX), (72, 384, 28, 56),
                         "the row geometry the page describes is not what the drawing names")

    def test_the_fan_rows_are_reserved_positional_slots(self):
        for marker in SLOT_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.src, "the fan rows are not reserved positional slots")

    def test_the_row_set_is_the_six_plus_the_drive_plus_the_slots(self):
        """The count of formatters in the body is the shape of the row table: seven labelled rows
        and one expression the slot loop reuses.  An eighth labelled row, or a slot drawn by its
        own copy of the formatter, changes that count - and the pitch census below would then be
        counting a different number of rows."""
        # What each labelled row's number is spelled by, counted out of the body: three
        # temperature lambdas (CPU, GPU, BOARD) and two slot loops (drive, fan) carry their own
        # `lambda v:` - five - while two rows print through `pct` (LOAD, GPU FAN) and two through
        # `gb` (RAM, VRAM) rather than each copying the shape.  The number is derived from the
        # table on purpose: a row that stops sharing the function shows up here as a count.
        self.assertEqual(self.src.count("lambda v:"), 5,
                         f"{self.src.count('lambda v:')} own-copy formatters in the body")
        self.assertEqual(self.src.count("pct, True,"), 2,
                         "the two percentage rows (LOAD and Fan GPU) must format through the "
                         "one `render.pct` both doors share")
        self.assertEqual(self.src.count("gb("), 2,
                         "the RAM and VRAM numbers must format through the one `gb` function - "
                         "and pass it the field they print, not the fraction their meter uses")
        self.assertEqual(ROWS_TOTAL, 11, ROWS_TOTAL)
        self.assertLessEqual(ROWS_TOTAL, 12,
                             "the block has grown past the canvas's ceiling; see "
                             "test_the_next_row_past_the_eleven_would_fit_and_the_one_after")
        self.assertEqual(len(themes.BARS_ROWS), len(themes.BARS_FIXED_ROWS)
                         + len(themes.BARS_DISK_ROWS) + len(themes.BARS_FAN_ROWS),
                         "the row table is no longer the sum of its three parts")
        self.assertEqual(len(themes.BARS_DISK_ROWS), len(themes.DISK_SLOTS[:2]),
                         "the drive slots in the block and in the vocabulary moved apart")
        # the fan trade, stated where it can be seen: four names answered, three rows drawn, and
        # the number of rows is what the 12-row ceiling is made of
        self.assertEqual(len(themes.FAN_SLOTS), 4, "the fan vocabulary itself moved")
        self.assertEqual(len(themes.BARS_FAN_ROWS), render.BARS_SLOTS,
                         f"the table reserves {len(themes.BARS_FAN_ROWS)} fan slots and the "
                         f"painter draws {render.BARS_SLOTS}")
        self.assertEqual(len(themes.BARS_FIXED_ROWS), 7,
                         "a labelled row joined or left the fixed set: the pitch census and the "
                         "block's ceiling below are both stated in terms of this count")


class WhatTheGlassHolds(unittest.TestCase):
    """The rows as painted: reserved places, and strings that agree with the source table."""

    def test_the_pitch_answers_the_same_whether_the_box_reports_six_fans_or_none(self):
        """The reservation is the whole point of 2026-11-09's change: a box with four fewer
        tachometers gets the same ten places, not a tighter stack."""
        self.assertEqual(pitch_of(), render.BARS_SPAN // ROWS_TOTAL, pitch_of())
        self.assertEqual(pitch_of(), PITCH, f"the pitch moved off {PITCH} px, so every window in "
                                            "this file's pixel census is counting a different "
                                            "row")
        none = slots_with_ink(render.draw(ALL_SIX, "bars", bg=render.OVERLAY))
        six = slots_with_ink(render.draw(dict(ALL_SIX, fans=FANS_SIX), "bars",
                                         bg=render.OVERLAY))
        # Written out position by position, because the positions are the claim: this box's
        # body answers the three temperatures, both drive slots, `Fan GPU` and the three usage
        # rows, and it reports no tachometer at all - so the two fan slots (indices 5 and 6)
        # are the holes.  A formula that puts every hole at the end stopped being true the day
        # the owner asked for the fan group in the middle of the block.
        want_here = [True, True, True,                  # CPU, GPU, BOARD
                     True, True,                        # both drive slots
                     False, False,                      # the two fan slots
                     True,                              # Fan GPU
                     True, True, True]                   # LOAD, RAM, VRAM
        self.assertEqual(len(want_here), ROWS_TOTAL, "the pattern and the table disagree")
        self.assertEqual(none, want_here,
                         "a box with no fans no longer reserves the slots it is not drawing")
        self.assertEqual(six, [True] * ROWS_TOTAL,
                         "the third fan onward is not being kept out of the reserved slots")

    def test_a_row_below_a_missing_reading_keeps_its_place(self):
        """The compaction that was removed on purpose: with three of the labelled rows
        unanswered, the rows that are drawn stay in their slots rather than closing up.

        Spelled out row by row rather than derived, because this is the check that catches a
        reordering.  The order since 2026-11-14 is CPU, GPU, BOARD, the two drive slots, the
        two fan slots, `Fan GPU`, then LOAD, RAM, VRAM, and `PARTIAL` answers two temperatures
        and the load and nothing else - so the holes sit in the middle of the block as well as
        at the end, which is the shape the old pattern could not express.
        """
        got = slots_with_ink(render.draw(PARTIAL, "bars", bg=render.OVERLAY))
        # CPU and GPU answer; BOARD, both drive slots, RAM and VRAM do not (PARTIAL has no
        # `drives` section at all, which is also a real shape: a kernel with no disk driver).
        want = [True, True,                            # CPU, GPU
                False,                                 # BOARD
                False, False,                          # both drive slots
                False, False,                          # both fan slots (PARTIAL has no `fans`)
                False,                                 # Fan GPU: a GPU, no `fan` field
                True, False, False]                    # LOAD answers, RAM/VRAM do not
        assert len(want) == 11, want
        self.assertEqual(len(want), ROWS_TOTAL, "the hand-written pattern and the table disagree")
        self.assertEqual(got, want, (got, "rows below a missing reading closed up again"))

    def test_the_shared_bodies_are_still_whole_when_everything_else_ran(self):
        """A cheap end-of-file guard, and it has already paid for itself.

        The bodies above are module-level and shared: `dict(ALL_SIX)` copies the outer mapping
        and nothing else, so a check that mutates `body["gpu"]` mutates every later check's
        idea of this box.  Writing that bug took three passes to understand - two unrelated
        rows went blank in checks that run after the one that did it, because unittest orders
        classes alphabetically - so the fix is not only the `copy.deepcopy` in the check that
        had it, but a guard that any check which breaks the shared bodies is caught here as
        well, whoever it was.
        """
        vals, gone = themes.values(ALL_SIX, WHEN)
        unlabelled = [src for _l, src, _t, _lo, _hi in themes.BARS_FIXED_ROWS if src not in vals]
        self.assertEqual(unlabelled, [],
                         f"ALL_SIX no longer answers the labelled rows it is meant to answer: "
                         f"{unlabelled} - a check somewhere reached into this body")
        pvals, _pgone = themes.values(PARTIAL, WHEN)
        readings = [k for k in pvals if k not in themes.CLOCKED]
        self.assertEqual(sorted(readings), ["CPU Temperature", "CPU Usage", "GPU Temperature"],
                         f"PARTIAL is the body with three readings and no board, no drives and "
                         f"no memory pair: {sorted(readings)}")
        self.assertNotIn("GPU Fans Speed", pvals,
                         "PARTIAL is the body with a GPU and no fan reading; if it grows one, "
                         "the unanswered-row checks above stop measuring what they claim")

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


    def test_no_display_shape_waits_without_a_source(self):
        """The other direction, and the one that was missing when the GPU fan went unseen.

        `layout.VENDOR_FORMAT` has carried a shape for `GPU Fans Speed` - the vendor's own
        name, read out of its renderer bundle - since 0.5, and `themes.SOURCES` had no entry
        for it, so a theme asking that name got **nothing**: not an error, not a hole with a
        reason beside it, just a row that never appeared.  The owner asked on 2026-11-14 why
        `bars` had no GPU fan; the reading had been on the wire for years (`gpu.fan`, 34-35 %
        across the twelve recorded samples in `docs/videos/readings-2026-11-08.json`) and so
        had the shape.  Only the pairing was missing, and no check looked that way.

        So: any name with a display shape must be askable, and an exception has to be listed
        here with the reason - which is the only place a reader will look.
        """
        unaskable = sorted(set(layout.VENDOR_FORMAT) - set(themes.source_names()))
        self.assertEqual(unaskable, ["CPU Fans Speed"],
                         f"{unaskable}: shape without a source.  A name the painter can format "
                         "but `themes.values()` cannot answer is an invisible hole")
        # ...and the one exception is the honest kind: the vendor offers the aggregate, nothing
        # in its record says how several tachometers combine into one number, and inventing an
        # aggregation rule is not a measurement.
        self.assertIn("CPU Fans Speed", layout.VENDOR_FORMAT,
                      "the exception this check pins has itself gone away: then the assertion "
                      "above has to stop allowing it")
        self.assertNotIn("CPU Fans Speed", themes.SOURCES,
                         "the aggregate now has a source: say what rule combines the tachometers")

    def test_the_vendors_fan_names_are_pairable_or_say_which_one_is_not(self):
        """Both fan aggregates, in one look: one pairs with a field, one does not, and the
        reason is in the source rather than in a comment nobody reads."""
        self.assertEqual(themes.SOURCES["GPU Fans Speed"], ("gpu", "fan"),
                         "the name is the vendor's and so is the field: PROTOCOL.md §10's "
                         "field table spells `gpu.fan` a percent")
        self.assertEqual(sorted(k for k in themes.SOURCES if "Fans Speed" in k),
                         ["GPU Fans Speed"],
                         "the fan aggregates this program answers moved; the check above "
                         "needs its exception list re-read")


def slot_of(label: str) -> int:
    """The row index a label sits at, read out of the table that draws it.

    Three checks here used literal indices (4 for RAM, 5 for VRAM).  Adding a row above them
    re-points those numbers at a different row, which is how a positional pin survives a change
    and then measures the wrong thing - so the labels ask the table where they are.
    """
    hit = [i for i, r in enumerate(themes.BARS_ROWS) if r[0] == label]
    if len(hit) != 1:
        raise AssertionError(f"{label!r} is at {hit} in {[r[0] for r in themes.BARS_ROWS]}")
    return hit[0]


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

    def test_the_export_is_the_heading_the_clock_and_four_widgets_per_row(self):
        self.assertEqual(len(self.widgets), 2 + 4 * len(themes.BARS_ROWS),
                         "the export is not the heading, the clock and four widgets "
                         "(figure, label, number, meter) per `themes.BARS_ROWS` entry")
        kinds: dict = {}
        for w in self.widgets:
            kinds[w["type"]] = kinds.get(w["type"], 0) + 1
        slots = sum(1 for r in themes.BARS_ROWS if r[0] is None)   # fan slots and drive slots
        self.assertEqual(kinds, {
            "text": 1 + len(themes.BARS_ROWS) - slots,
            "data": 1 + len(themes.BARS_ROWS) + slots,
            "bar": len(themes.BARS_ROWS),
            # one gutter figure per row, named from `themes.ROW_ICONS`
            "special": len(themes.BARS_ROWS)}, kinds)

    def test_each_rows_four_widgets_answer_for_the_same_place_on_the_glass(self):
        """A row is four widgets - figure, label, number, meter - and all four mean one line.

        The label and the number share the row's centre; the meter hangs `BARS_BAR_DY` under
        it; the gutter figure's box is centred on the same line, in the strip left of the
        label column.  That is the offset both doors use, and it is why the four are not one
        assertion: a file that put the meter at the row's own y would still draw, and every
        bar would sit on top of its own number - and a file that put the figure at the
        label's x would draw a die across the word `CPU`.  The row's four widgets are also
        checked to be **in the order the painter draws them**, because where two of them
        overlap, the last one down wins, and the two doors once differed by exactly the
        number of antialiased pixels at that boundary.
        """
        pitch = render.BARS_SPAN // len(themes.BARS_ROWS)
        for i, (label, bar_src, text_src, lo, hi) in enumerate(themes.BARS_ROWS):
            y = render.BARS_Y0 + i * pitch
            icon, lbl, num, meter = (self.widgets[1 + 4 * i], self.widgets[2 + 4 * i],
                                     self.widgets[3 + 4 * i], self.widgets[4 + 4 * i])
            with self.subTest(row=i):
                base = themes.ROW_ICONS[bar_src]
                self.assertEqual(icon["type"], "special")
                # the file names the **base** figure and points at the source that may ask
                # for a variant; the variant is resolved at draw time from the reading, so
                # the declared name cannot depend on this machine's fan types
                self.assertEqual(icon["property"][0]["name"], f"icon-{base}",
                                 "the figure the file asks for is not the one this row's "
                                 "meter source maps to in `themes.ROW_ICONS`")
                want_variant = (themes.SLOT_TYPES.get(bar_src)
                                if bar_src in themes.SLOT_TYPES else None)
                declared = (icon["property"][0].get("xigma") or {}).get("iconVariant")
                self.assertEqual(declared, want_variant,
                                 "a tachometer row must name the source its figure's variant "
                                 "comes from, and no other row may name one")
                self.assertEqual((icon["property"][0]["x"],
                                  icon["property"][0]["width"]),
                                 (render.BARS_ICON_X, render.BARS_ICON_BOX[0]))
                self.assertAlmostEqual(
                    icon["property"][0]["y"], y - render.BARS_ICON_BOX[1] / 2,
                    msg="the figure is off its row's line", places=3)
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
                    self.assertEqual(lbl["property"][0]["source"], themes.SLOT_NAMES[bar_src],
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


class TheSlotRows(unittest.TestCase):
    """A slot row's label belongs to the **subject**, and the case that proves it is a row with
    a name and no reading.

    A census mutation - making the drive slot's label follow the temperature instead of the
    row's presence - cost **0 failures**, which is not a fact about the mutation but about the
    readings on hand: every case so far had a name and a temperature together, or neither.  This
    class supplies the missing shape, a `drives[]` row that names a controller and publishes no
    temperature at all (a driver that binds a device before its thermal sensor answers, which is
    what `nvme` does at a cold start here).  Under the shipped rule the label draws, the number
    and the meter do not, and both doors agree; under the mutation the code door silences the
    label and the two part company.
    """

    def row_of(self, source: str) -> int:
        hit = [i for i, r in enumerate(themes.BARS_ROWS) if source in (r[1], r[2])]
        self.assertEqual(len(hit), 1, f"{source} is at {hit}")
        return hit[0]

    def body(self):
        return dict(ALL_SIX, drives=[{"name": "nvme7"},
                                     {"name": "nvme0", "temperature": 44, "sensors": [44]}])

    def test_the_two_doors_agree_when_a_slot_has_a_name_and_no_number(self):
        got = themes.parity("bars", dict(self.body(), timestamp={}), WHEN)
        self.assertEqual((got["diff_px"], got["worst_channel_delta"]), (0, 0),
                         f"a slot row with a name and no temperature split the doors: {got}")
        self.assertIn("Disk 1 Temperature", got["missing"],
                      f"the number was not reported skipped: {got['missing']}")
        self.assertNotIn("Disk 1 Name", got["missing"],
                         "the label was reported skipped too, which is the wrong half of the "
                         "rule: this row has a subject, only its reading is missing")

    def test_the_label_is_drawn_and_the_number_is_not(self):
        rows = rows_by_slot(self.body())
        index = self.row_of("Disk 1 Temperature")
        drawn = rows.get(index, [])
        self.assertIn(("label", "nvme7 /"), drawn,
                      f"row {index} did not draw its marked name: {drawn}")
        self.assertFalse([t for kind, t in drawn if kind == "value"],
                         f"row {index} printed a number it has no reading for: {drawn}")
        img = render.draw(dict(self.body(), timestamp={}), "bars", bg=render.OVERLAY)
        self.assertFalse(slots_with_ink(img)[index],
                         "the value column has ink in a slot whose reading is absent")
        # and the row keeps its place: the next slot's number lands where the table says
        nxt = self.row_of("Disk 2 Temperature")
        self.assertTrue(slots_with_ink(img)[nxt],
                        "the row below a nameless-number slot closed up")


class TheMemoryRows(unittest.TestCase):
    """The two rules the diff hunt turned up, measured at the readings that found them."""

    def test_a_partial_gigabyte_agrees_with_its_own_meter(self):
        """The report that started this: VRAM read `15 GB` on a card sitting at 97%.

        At this box's own GPU numbers - 15 952 MB used of 16 376 - the row's meter filled to
        97.4% while the figure floored to `15 GB`.  On the glass that reads as a card with a
        gigabyte of headroom left, from the same row, at the same instant.  The number now
        carries one decimal, and the check below holds the two halves of the row to the same
        fraction rather than trusting the spelling.
        """
        used, total = 15_952, 16_376
        vals, _gone = themes.values({"gpu": {"memoryUsage": used,
                                             "dedicatedTotal": total}}, WHEN)
        shown = layout.text_for("Used GPU Memory", vals["Used GPU Memory"])
        self.assertEqual(shown, "15.6 GB", shown)
        printed_gib = float(shown.split()[0])
        meter = (used / total)
        # the printed number, read back against the card's total, has to land on the meter
        self.assertLess(abs(printed_gib / (total / 1024) - meter), 0.01,
                        f"{shown} against a meter at {meter:.3f}: the row's two halves disagree")
        # and the rule this replaced, kept visible rather than deleted
        floored = used // 1024
        self.assertEqual(floored, 15)
        self.assertGreater(meter - floored / (total / 1024), 0.03,
                           "the floor rule now agrees with the meter, so this check has stopped "
                           "guarding the defect it was written for")

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
        self.assertEqual(rows.get(slot_of("RAM")), [("label", "RAM")],
                         "the RAM row drew a number for a numerator that was never reported - "
                         "or `pct_pair` still raises")
        self.assertEqual([t for c, t in rows.get(slot_of("VRAM"), []) if c == "value"],
                         ["4.0 GB"], rows.get(slot_of("VRAM")))
        self.assertFalse(slots_with_ink(render.draw(dict(body), "bars",
                                                  bg=render.OVERLAY))[slot_of("RAM")],
                         "the value column has ink in a row whose number is not drawn")

    def test_a_gpu_at_exactly_zero_used_keeps_its_row_at_nothing_filled(self):
        """The other half of the asymmetry: a 0 reading is a reading.  The number stays, and it
        reads `0.0 GB`."""
        rows = rows_by_slot(dict(ALL_SIX, gpu={"temperature": 47.0, "load": 22.0,
                                               "memoryUsage": 0, "dedicatedTotal": 8192}))
        self.assertEqual([t for c, t in rows.get(slot_of("VRAM"), []) if c == "value"],
                         ["0.0 GB"],
                         "a GPU at 0 used dropped its row again - the asymmetry between the two "
                         "memory rows is back")

    def test_a_zero_denominator_is_not_a_pair_to_divide(self):
        rows = rows_by_slot(dict(ALL_SIX, memory={"used": 0, "total": 0}))
        self.assertEqual(rows.get(slot_of("RAM")), [("label", "RAM")],
                         "a zero denominator drew a RAM row")


class TheGpuFanRow(unittest.TestCase):
    """The row the owner asked for on 2026-11-14: the card's fan, in the unit it has.

    Three things to hold, and each of them is a way this kind of row has gone wrong before in
    this file: the number must agree with the meter standing beside it (the `15 GB` at 97 %
    defect), the scale must be the reading's own rather than the neighbouring rows' (a percent
    on the fan slots' 0..3000 track would read as a fan that never speeds up), and a box with
    no such reading must report the row unanswered instead of drawing `0%` - which on a GPU is
    the difference between "silent at idle" and "this card has no fan sensor".
    """

    def test_the_percent_agrees_with_its_own_meter(self):
        used = 34
        vals, _gone = themes.values({"gpu": {"fan": used}}, WHEN)
        shown = layout.text_for("GPU Fans Speed", vals["GPU Fans Speed"])
        self.assertEqual(shown, "34%", shown)
        row = [r for r in themes.BARS_ROWS if r[1] == "GPU Fans Speed"]
        self.assertEqual(len(row), 1, row)
        _label, _meter, _text, lo, hi = row[0]
        self.assertEqual((lo, hi), (0, 100),
                         "the row's meter scale moved off a percentage: `gpu.fan` is a duty "
                         "percent, and on the fan slots' 0..3000 scale 34 % would fill 1 % of "
                         "the track - the same two-halves-of-one-row disagreement as `15 GB`")
        fraction = (used - lo) / (hi - lo)
        self.assertLess(abs(float(shown.rstrip("%")) / 100 - fraction), 0.01,
                        f"{shown} against a meter at {fraction:.3f}")
        # and what the wrong scale would have printed, kept visible: 34 on 0..3000 is a
        # fraction of 0.011, three orders of magnitude from the number beside it
        wrong = (used - 0) / (3000 - 0)
        self.assertGreater(fraction - wrong, 0.03,
                           "this check stopped guarding the scale mix-up it was written for")

    def test_the_row_reads_the_same_field_the_dual_theme_figures(self):
        """One field, spelled two ways by two themes, and neither may invent a unit.

        `render.gpu_fan_figure` has drawn `GPU FAN 34%` under the GPU temperature in `dual`
        since 0.4; the `bars` row prints `34%` beside a percentage meter.  Both come out of
        `gpu.fan`, and a change to the source pairing moves both - which is what this pins,
        because two unit stories for one field is how a row starts lying.
        """
        body = {"gpu": {"fan": 34}}
        vals, _gone = themes.values(body, WHEN)
        self.assertEqual(layout.text_for("GPU Fans Speed", vals["GPU Fans Speed"]), "34%")
        self.assertEqual(render.gpu_fan_figure(body), "GPU FAN 34%")
        self.assertTrue(render.gpu_fan_figure(body).endswith(layout.text_for(
            "GPU Fans Speed", vals["GPU Fans Speed"])),
            "the two figures no longer end in the same spelling of the same reading")
        # no reading at all: `dual` says so in words, `bars` leaves the number out
        self.assertEqual(render.gpu_fan_figure({"gpu": {}}), "GPU FAN --")

    def test_a_box_with_no_gpu_fan_reports_the_row_unanswered(self):
        """An integrated-GPU box (no `nvidia-smi`, no fan in the `amdgpu` hwmon here) has a
        label and no number, and both doors agree about it at 0 px."""
        # `copy.deepcopy`, not `dict()`: a shallow copy shares the `gpu` dict with the
        # module-level body, so deleting a key here deleted it from every later check in the
        # file too.  That is how this was found - the GPU-fan row went blank in two unrelated
        # checks that run after this one, because unittest orders classes alphabetically and
        # `TheGpuFanRow` came first.
        body = copy.deepcopy(ALL_SIX)
        del body["gpu"]["fan"]
        _vals, gone = themes.values(body, WHEN)
        self.assertIn("GPU Fans Speed", gone,
                      "the row should be reported unanswered, with the reason")
        got = themes.parity("bars", dict(body, timestamp={}), WHEN)
        self.assertEqual((got["diff_px"], got["worst_channel_delta"]), (0, 0),
                         f"a missing fan split the doors: {got}")
        self.assertIn("GPU Fans Speed", got["missing"], got["missing"])
        index = [i for i, r in enumerate(themes.BARS_ROWS) if r[1] == "GPU Fans Speed"][0]
        drawn = rows_by_slot(body).get(index, [])
        self.assertIn(("label", "Fan GPU"), drawn,
                      f"the label belongs to the row's subject, so it draws anyway: {drawn}")
        self.assertFalse([t for kind, t in drawn if kind == "value"],
                         f"a box with no fan reading printed a number: {drawn}")
        img = render.draw(dict(body, timestamp={}), "bars", bg=render.OVERLAY)
        self.assertFalse(slots_with_ink(img)[index],
                         "the value column has ink where no reading was reported")
        self.assertTrue(slots_with_ink(img)[index + 1],
                        "the row below a missing reading closed up")

    def test_the_zero_that_is_a_reading_still_prints(self):
        """`fan: 0` is a reading - a card held at zero duty - and prints `0%` with an empty
        track.  `dual`'s figure treats 0 as no reading (`GPU FAN --`), and that difference is
        deliberate and stated here rather than left to drift: a row with a meter has a scale
        that says 0, a figure made of words has no such place to put it."""
        vals, gone = themes.values({"gpu": {"fan": 0, "temperature": 40}}, WHEN)
        self.assertIn("GPU Fans Speed", vals, gone)
        self.assertEqual(layout.text_for("GPU Fans Speed", vals["GPU Fans Speed"]), "0%")
        drawn = rows_by_slot(dict(ALL_SIX, gpu={"fan": 0}))   # replaces, does not mutate
        index = [i for i, r in enumerate(themes.BARS_ROWS) if r[1] == "GPU Fans Speed"][0]
        self.assertEqual([t for kind, t in drawn.get(index, []) if kind == "value"], ["0%"],
                         drawn.get(index))
        self.assertEqual(render.gpu_fan_figure({"gpu": {"fan": 0}}), "GPU FAN --",
                         "the two themes' zero rule moved; the sentence above has to follow")

    def test_the_row_sits_where_its_subject_is(self):
        """Ordering is a claim too: the fan row belongs under the card's temperature, not at
        the end of the block.  Measured off the table, because a row inserted at the end of
        the list would keep every count in this file correct and still read wrong."""
        labels = [r[0] for r in themes.BARS_ROWS]
        self.assertEqual(labels[:3], ["CPU", "GPU", "BOARD"], labels)
        self.assertEqual(labels[7:], ["Fan GPU", "LOAD", "RAM", "VRAM"], labels)
        self.assertEqual([r[0] for r in themes.BARS_ROWS if r[0] is None], [None] * 4,
                         "four slot rows: two drive slots then two fan slots, in the middle")
        # The owner's reason for the order, taken out of the **drawing** rather than the table:
        # given a body that reports two tachometers named the way this box names them, the fan
        # group must read `Fan CPU`, `CPU PUMP`, `Fan GPU`, with no hole between them.
        body = dict(ALL_SIX, fans=[{"name": "Fan CPU", "value": 1650, "type": "Fan"},
                                   {"name": "CPU PUMP", "value": 2450, "type": "Pump"}])
        rows = rows_by_slot(body)
        group = [next((t for kind, t in rows.get(i, []) if kind == "label"), None)
                 for i in (5, 6, 7)]
        self.assertEqual(group, ["Fan CPU", "CPU PUMP", "Fan GPU"],
                         f"the fan group as drawn: {group}; full block {labels}")
        self.assertTrue(all(not r[0] for r in themes.BARS_ROWS[5:7]),
                        "the two rows above `Fan GPU` are the reserved fan slots")


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
        """The two lists the review door prints - **either of which may be empty**.

        Until 2026-11-14 this box always had a hole (`Fan 3`, `Fan 4`), and the helper parsed
        the `cannot:` line as if a theme must have one.  It does not: the block now draws two
        fan slots and this machine reports two tachometers, so the door prints no `cannot:`
        line at all and says `skipped: nothing`.  Requiring that line would have made the
        helper assert the defect rather than report the machine.
        """
        line = next((ln for ln in self.out if "cannot:" in ln), "")
        cannot = ({s.strip() for s in line.split("cannot:", 1)[1].split(",") if s.strip()}
                  if "cannot:" in line else set())
        row = next(ln for ln in self.out if " boxes," in ln)
        tail = row.split("skipped:", 1)[1] if "skipped:" in row else ""
        skipped = set() if not tail.strip() or tail.strip() == "nothing" else \
            {s.strip() for s in tail.split(",") if s.strip()}
        return cannot, skipped

    def test_the_report_says_the_widget_count_it_painted(self):
        self.assertIn(f"{len(self.obj['osd']['widget'])} widgets", self.out[0], self.out[0])

    def test_every_skip_reason_is_a_reading_a_face_or_a_dependency(self):
        asked, _deps, _guarded = self.asked_deps_guarded()
        cannot, skipped = self.cannot_and_skipped()
        odd = [n for n in skipped
               if not (n.startswith("showIf:") or n.startswith("font:") or n in asked)]
        self.assertEqual(odd, [], "the review door reported something that is neither a reading "
                                  f"this file asks for, nor a dependency, nor a face: {odd}")
        # the emptiness has to be the door's own claim, not a parse that missed a line
        if not cannot and not skipped:
            print("  review door: this machine answers every source `bars` asks for")
            self.assertIn("skipped: nothing", "\n".join(self.out),
                          "the door reported no holes but never said so either")
        self.assertLessEqual(cannot, asked,
                             "the door named an unanswered source this file does not ask for")
        # The door's three lists have to agree with **each other**.  Nothing here may compare
        # them with a pinned body: the lists come out of a subprocess that asked this machine's
        # real sensors, so "a name the door cannot answer is one the fixture answers" is not a
        # relation between two facts of the code but a demand that every host look like the
        # fixture.  That is precisely the assertion I wrote on 2026-11-14, and it failed CI #204
        # and #205 for that reason alone - a runner with no GPU puts `GPU Fans Speed` in
        # `cannot` while `PARITY_CASES[0]` answers it, and both facts are true at once.
        asks, answers, said = self.three_lists()
        self.assertTrue(asks and answers,
                        f"the door printed no asks/answers line to read: {self.out[:3]}")
        self.assertEqual(answers | said, asks,
                         f"the door's own accounting does not close: asks {len(asks)}, answers "
                         f"{len(answers)}, cannot {len(said)}")
        self.assertFalse(answers & said,
                         f"a source is both answered and unanswered on this machine: "
                         f"{sorted(answers & said)}")

    def three_lists(self) -> tuple:
        """(asks, answers, cannot) exactly as one run of the door reported them."""
        def grab(needle: str) -> set:
            line = next((ln for ln in self.out if needle in ln), "")
            if needle not in line:
                return set()
            return {s.strip() for s in line.split(needle, 1)[1].split(",") if s.strip()}
        return grab("this theme asks for:"), grab("this machine answers:"), grab("cannot:")

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


class TheBlockStopsBeforeTheClock(unittest.TestCase):
    """The row count has a ceiling, and it is the clock - not taste.

    `bars` reserves six slot rows (four fan, two drive) beside the six fixed readings, so
    **twelve rows is the most this block can ever ask for** on any machine: the reservation is
    what makes that a constant rather than a property of this box.  Adding the second drive slot
    moved the last row's centre from 392 to 424, and the clock from y=452 to y=458 to keep room
    under it.  Nothing held that margin, so this does: the ink of the last row's meter, measured
    from the shipped painter with every slot answered, must clear the clock line's own ink.
    """

    def ink_rows(self, img) -> list:
        d = img.convert("RGBA").getchannel("A").load()
        return [y for y in range(render.H)
                if sum(1 for x in range(render.W) if d[x, y] > 8) > 40]

    def test_the_last_meters_ink_clears_the_clocks_ink(self):
        body = dict(ALL_SIX, fans=FANS_SIX,
                    drives=[{"name": "nvme0", "temperature": 44, "sensors": [44, 55, 68]},
                            {"name": "nvme1", "temperature": 33, "sensors": [33]}])
        real_wh = render.BARS_BAR_WH
        try:
            render.BARS_BAR_WH = (0, 0)
            text_only = set(self.ink_rows(render.draw(dict(body, timestamp={}), "bars")))
        finally:
            render.BARS_BAR_WH = real_wh
        full = self.ink_rows(render.draw(dict(body, timestamp={}), "bars"))
        pitch = min(render.BARS_ROW_MAX, max(render.BARS_ROW_MIN,
                                            render.BARS_SPAN // len(themes.BARS_ROWS)))
        last_centre = render.BARS_Y0 + (len(themes.BARS_ROWS) - 1) * pitch
        # the clock's ink is the run of inked rows below the last row's text band; the meter of
        # the last row is the ink between those two, and it is what must not touch either
        below_text = [y for y in full if y > last_centre + 11]
        meter = [y for y in below_text if y not in text_only]
        if not meter:
            self.skipTest("no meter ink below the last row on this machine: the faces or the "
                          "readings dropped the row, so there is no margin to measure")
        clock_top = min(y for y in below_text if y > max(meter))
        margin = clock_top - max(meter) - 1
        self.assertGreaterEqual(margin, 2,
                                f"the last row's meter ends at y={max(meter)} and the clock's ink "
                                f"begins at y={clock_top}: {margin} px of air.  Adding a row, or "
                                f"moving either anchor, has to keep this measurable - at pitch "
                                f"{pitch} the block has no room for a thirteenth row at all")
        print(f"  block margin: last row centre {last_centre}, meter ink to y={max(meter)}, "
              f"clock ink from y={clock_top} -> {margin} px of air; {len(themes.BARS_ROWS)} rows "
              f"at pitch {pitch}")

    def test_the_clock_anchor_prints_where_its_room_runs_out(self):
        """Two census mutations cost nothing, and the reason is a measurement, not an excuse.

        Moving the clock back to y=452 costs **0** failing checks, and thinning the meter track
        to 4 px at this pitch costs **0** too: at eleven rows the block is one row shorter than
        the canvas permits, so there is slack in both numbers.  Slack that nobody has located is
        slack that gets mistaken for a guard that stopped working, so this finds the boundary by
        moving the clock anchor down toward the block and reporting the last y the margin rule
        still accepts.  The shipped anchor stays at y=458 - where the twelve-row block *needed*
        it, and where the owner's glass has it today - and this says how far it could move.
        """
        body = dict(ALL_SIX, fans=FANS_SIX,
                    drives=[{"name": "nvme0", "temperature": 44, "sensors": [44]},
                            {"name": "nvme1", "temperature": 33, "sensors": [33]}])
        real_xy, real_wh = render.BARS_CLOCK_XY, render.BARS_BAR_WH
        pitch = pitch_of()
        last = render.BARS_Y0 + (len(themes.BARS_ROWS) - 1) * pitch
        margins = {}
        try:
            for y in (440, 444, 448, 450, 452, 454, 456, 458, 460):
                render.BARS_CLOCK_XY = (240, y)
                render.BARS_BAR_WH = (0, 0)
                try:
                    text_only = set(self.ink_rows(render.draw(dict(body, timestamp={}), "bars")))
                finally:
                    render.BARS_BAR_WH = real_wh
                full = self.ink_rows(render.draw(dict(body, timestamp={}), "bars"))
                below = [v for v in full if v > last + 11]
                meter = [v for v in below if v not in text_only]
                later = [v for v in below if v > max(meter)] if meter else []
                margins[y] = (later[0] - max(meter) - 1) if later and meter else None
        finally:
            render.BARS_CLOCK_XY, render.BARS_BAR_WH = real_xy, real_wh
        ok = [y for y, m in margins.items() if m is not None and m >= 2]
        self.assertTrue(ok, "no clock anchor in the swept range clears the 2 px floor")
        lowest = min(ok)
        print(f"  clock anchor margins: " +
              ", ".join(f"y={y}:{margins[y]}px" for y in sorted(margins)))
        print(f"  the floor bites above y={lowest - 4}: the shipped anchor is y={real_xy[1]}, "
              f"so {real_xy[1] - lowest} px of slack is permitted by the geometry and taken by "
              "nobody")
        self.assertGreaterEqual(real_xy[1], lowest,
                                "the shipped clock anchor sits where the margin rule refuses it")
        self.assertGreaterEqual(margins[real_xy[1]], 2,
                                "the shipped anchor no longer clears its own floor")

    def test_the_next_row_past_the_eleven_would_fit_and_the_one_after_that_would_not(self):
        """The ceiling, printed rather than assumed: what each row would cost.

        The block draws **eleven** rows today and the canvas allows **twelve**, so there is one
        row of headroom left and it is reserved by choice, not by geometry: filling it with the
        third fan slot would put a blank row between two fan rows that both have readings on
        this box.  The print below is what a reader weighs that decision against - pitch, the
        last row's centre, and where its meter ink lands relative to the clock's, which this
        file's other check measures rather than computes.
        """
        span, y0 = render.BARS_SPAN, render.BARS_Y0
        for n in (10, 11, 12, 13):
            pitch = min(render.BARS_ROW_MAX, max(render.BARS_ROW_MIN, span // n))
            last = y0 + (n - 1) * pitch
            print(f"  {n} rows -> pitch {pitch}, last centre {last}, meter to "
                  f"{last + render.BARS_BAR_DY + render.BARS_BAR_WH[1] // 2}, canvas {render.H}")
        self.assertEqual(len(themes.BARS_ROWS), 11,
                         "the row count moved; the headroom claim above and every pixel window "
                         "in this file follow it")
        self.assertLess(len(themes.BARS_ROWS), 13,
                        "the block reached a thirteenth row: pitch falls to 29 and the 2 px "
                        "clearance rule is what refuses it, so this check is the trip wire")


class TheRowsDoNotRunIntoEachOther(unittest.TestCase):
    """A row's meter belongs to its own line of text, and touches neither neighbour.

    This is the check the 2026-11-12 geometry change exists to satisfy.  At the old
    constants the block was over-subscribed: on this box the theme's own faces paint a
    row's label and number over 16 ink rows, and a 10 px track paints 12 with
    antialiasing, in a pitch of 32 - which left 15 rows of air for a meter that needed
    them and put the track's ink *inside* the next row's text.  `BARS_BAR_DY` and
    `BARS_BAR_WH` moved together for that reason, and this class is what keeps them
    from drifting back.

    Everything is measured from the shipped painter twice in one run: once with the
    meters suppressed (`BARS_BAR_WH` at zero, which leaves the text exactly as it is) and
    once as shipped.  The difference is meter ink; the text bands are what this box's
    faces lay down, so the pixel counts printed here are a record and the assertion is
    the relation - clear rows on both sides, and the track nearer its own label than the
    row below it, which is the difference between a meter and a separator line.
    """

    def profile(self, img) -> list:
        """Ink per canvas row, **in the text and meter columns only**.

        The x window is not a tuning knob, it is the thing being measured: this class asks
        whether a row's meter is clear of the text above and below it, and the gutter
        figures added on 2026-11-14 stand at x 3..25 - left of both the label column (28)
        and every meter (28..452) - so including them would report a collision that cannot
        happen on the glass.  Their own clearances are measured in `tests/test_icons.py`,
        which holds each figure inside its declared box and clear of the label column.
        """
        d = img.convert("RGBA").getchannel("A").load()
        return [sum(1 for x in range(render.BARS_LBL_X, render.W)
                    if d[x, y] > 8) for y in range(render.H)]

    def bands(self) -> tuple:
        body = dict(ALL_SIX, fans=FANS_SIX, timestamp={})
        real = render.BARS_BAR_WH
        try:
            render.BARS_BAR_WH = (0, 0)
            text = self.profile(render.theme_bars(dict(body)))
        finally:
            render.BARS_BAR_WH = real
        full = self.profile(render.theme_bars(dict(body)))
        pitch = min(render.BARS_ROW_MAX, max(render.BARS_ROW_MIN,
                                             render.BARS_SPAN // len(themes.BARS_ROWS)))
        rows = []
        for i in range(len(themes.BARS_ROWS)):
            centre = render.BARS_Y0 + i * pitch
            inked = [y for y in range(centre - 15, centre + 16) if text[y]]
            if not inked:
                self.skipTest(f"row {i} lays down no text ink here: the theme's faces are "
                              "not installed, so there is no band to keep clear of")
            window = range(inked[-1] + 1, inked[0] + pitch + 15)
            # the track is 424 px wide, so any row where the ink is more than a glyph's
            # worth is the meter: inside the next row's band that is exactly the overlap
            # this check exists to catch, so it must be counted rather than trimmed away
            meter = [y for y in window if full[y] > 300]
            rows.append((i, centre, inked[0], inked[-1],
                         (meter[0], meter[-1]) if meter else None))
        return rows, pitch

    def test_each_rows_meter_is_clear_of_the_text_above_and_below(self):
        rows, pitch = self.bands()
        self.assertEqual(len(rows), len(themes.BARS_ROWS), rows)
        widest = []
        for i, _centre, top, bottom, meter in rows[:-1]:
            with self.subTest(row=i):
                self.assertIsNotNone(meter, f"row {i} drew no meter at a reading that answers it")
                next_bottom = rows[i + 1][3]
                next_top = rows[i + 1][2]
                above = meter[0] - bottom - 1
                below = next_top - meter[1] - 1
                widest.append((i, above, below))
                self.assertGreaterEqual(above, 1,
                                        f"row {i}: its meter starts {above} px under its own "
                                        f"text ({bottom}..{meter[0]})")
                self.assertGreaterEqual(below, 1,
                                        f"row {i}: its meter ends {below} px above row "
                                        f"{i + 1}'s text ({meter[1]}..{next_top}) - the old "
                                        "constants put it inside that text")
                self.assertLess(above, below,
                                f"row {i}: its meter sits {above} px from its own label and "
                                f"{below} px from the row below, so the bar reads as that row's")
        self.assertTrue(widest, "no pair of rows was measured, so nothing above was checked")
        tightest = min(widest, key=lambda t: min(t[1], t[2]))
        self.assertGreaterEqual(min(tightest[1], tightest[2]), 2,
                                f"the tightest clearance in the block is row {tightest[0]} at "
                                f"{tightest[1]} px above / {tightest[2]} px below a pitch of "
                                f"{pitch}: two rows of air is where this starts to read as one")


if __name__ == "__main__":
    unittest.main()
