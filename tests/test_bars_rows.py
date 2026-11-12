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


if __name__ == "__main__":
    unittest.main()
