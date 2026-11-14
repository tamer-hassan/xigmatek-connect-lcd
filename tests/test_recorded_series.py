#!/usr/bin/env python3
"""The recorded series beside the published clips: what may be claimed about a video, and what the
`bars` drawing owes it.

Ported from the two `tools/selftest.sh` sections titled "the recorded series" and "the recorded
series against `bars`'s row table".

A committed picture is a claim about a moment, so the moment has to be in the file.  Six of the
clips under `docs/videos` were rendered from `docs/videos/readings-2026-11-08.json`, twelve
`sensors.collect()` calls a second apart on a real board; the JSON is tracked, and it is the only
way any of those pictures can be re-made rather than admired.  What is asserted here is the ledger
and one rule that depends on it:

* the file says **which zone** its on-glass clock was read at.  This is not decoration: the series
  stores epoch milliseconds, `time.localtime()` turns those into the digits the glass shows, and a
  UTC runner reading the same milliseconds prints `22:25:16` where the video holds `00:25:16`.  CI
  scored committed pixels against a layer drawn with the wrong digits on 2026-11-08 and one file's
  clock glyph measured 241.0 here and 225.5 there, unchanged;
* the twelve samples are about a second apart, the clock advances over all twelve, and every
  tracked field changes somewhere across them - a series that does not move cannot show a change,
  which is the whole point of the longer MP4s;
* the readings are inside the spans PROTOCOL.md 8 records for this board, so "a real machine" is
  not a story told about a made-up dict;
* **every `bar` row this box could have had is answered at every sample.**  This is why
  `docs/videos/bars-theme_52.mp4` outlived the changes that followed: those changes moved a row
  whose *subject* exists while its reading does not, or a pair that cannot be divided.  A slot past
  the reported fan count is empty in the old drawing and the new one alike, which is why the rows
  below are scoped to what the recording has rather than to all four reserved slots;
* the fan count the series reports is one value, and it fits inside `themes.FAN_SLOTS`, so the
  sentence above is about a bounded set rather than about whatever the box happened to answer.

What is deliberately *not* here: the frame counts, durations, byte ceilings and luma comparisons the
old suite ran over the six `docs/videos/*.mp4` files.  Those measured the files against a page that
quoted their sizes, which is the class of gate 0.7 stopped keeping; `ffprobe` and `du -b` re-read
them in one line (docs/tools.md).
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest

from tests import fixtures

from xigmalcd import themes

TOOLS = os.path.join(fixtures.REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import preview_gif                                        # noqa: E402

SERIES = "docs/videos/readings-2026-11-08.json"

#: The fields the published pictures are about, in the shape the daemon uploads them.
TRACKED_FIELDS = (("cpu", "temperature"), ("cpu", "load"), ("gpu", "temperature"),
                  ("gpu", "load"), ("memory", "used"))

#: PROTOCOL.md 8's spans for this board.  A series inside these spans is a reading; outside them
#: it is a guess, and every clip rendered from it would be a picture of nothing.
SPANS = {"temperature": (40, 95), "fan": (900, 3600), "load": (0.0, 100.0)}


class RecordedSeries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(fixtures.REPO, SERIES), encoding="utf-8") as fh:
            cls.rec = json.load(fh)
        cls.series = cls.rec["series"]
        cls.tzoff = cls.rec.get("clock_offset_s")

    def clock_of(self, sample) -> str:
        """The digits that sample's on-glass clock showed, in the zone the file records."""
        return preview_gif.CLOCK_STR_REAL(preview_gif.series_clock(sample, self.tzoff))

    def test_the_file_records_the_zone_its_clock_was_read_at(self):
        """Without this the same bytes print different digits on two machines, and any comparison
        between a committed frame and a re-drawn one is a comparison of two different pictures."""
        self.assertIsNotNone(self.tzoff, (SERIES, "a series that drives published videos has to "
                                                  "record the zone its on-glass clock was read at"))
        self.assertLess(abs(self.tzoff), 14 * 3600, (self.tzoff, "not a plausible zone offset"))
        self.assertTrue(self.rec.get("clock_note"),
                        "the offset needs a sentence beside it, or the next reader removes it")

    def test_the_sample_count_is_the_one_the_file_claims(self):
        self.assertEqual(self.rec["samples"], len(self.series),
                         (self.rec["samples"], len(self.series)))
        self.assertEqual(len(self.series), 12, "the published clips were rendered from twelve "
                                               "samples; a different count is a different series")

    def test_the_samples_are_about_one_second_apart(self):
        """Loose bounds on purpose: what is being refused is a series with a hole in it or a
        collapsed clock, not a scheduler that took 1.02 s instead of 1.00 s."""
        gaps = [(b["timestamp"] - a["timestamp"]) / 1000
                for a, b in zip(self.series, self.series[1:])]
        self.assertEqual(len(gaps), len(self.series) - 1)
        bad = [round(g, 2) for g in gaps if not 0.8 <= g <= 1.4]
        self.assertEqual(bad, [], f"samples {bad} s apart: this is not a one-second series")

    def test_the_clock_on_the_glass_advances_over_every_sample(self):
        """Twelve distinct clock strings, in order.  A series whose clock repeats would let a
        *time* change hide inside a frame that was actually frozen."""
        clocks = [self.clock_of(s) for s in self.series]
        self.assertEqual(len(set(clocks)), len(clocks), clocks)
        stamps = [time.strptime(c, "%H:%M:%S") for c in clocks]
        self.assertTrue(all(a < b for a, b in zip(stamps, stamps[1:])), clocks)

    def test_the_series_actually_moves(self):
        """Every tracked field changes across the twelve samples.

        "Live" is the claim the longer MP4s make, and an idle box can sit at one temperature and
        one fan figure for a quarter minute - so a series that holds still cannot show a change.
        This file is tracked bytes rather than a machine's readings, which is why the bound is
        exact instead of the loose `at least four` the old suite used: a partial freeze is the
        failure mode, and four of six moving would still hide one row painted at the same figure
        for a quarter minute."""
        fields = {f"{section}.{key}": {s["metrics"].get(section, {}).get(key)
                                      for s in self.series}
                  for section, key in TRACKED_FIELDS}
        fields["fan RPM"] = {f.get("value") for s in self.series
                             for f in s["metrics"].get("fans", [])}
        still = sorted(k for k, v in fields.items() if len(v) < 2)
        self.assertEqual(still, [], f"{len(fields)} fields tracked, {still} never change: a clip "
                                    f"rendered from this series shows no change in them")

    def test_the_numbers_are_inside_the_spans_this_board_reports(self):
        """Real readings, not invented ones: PROTOCOL.md 8's spans for the Connect's sensors."""
        temps = [s["metrics"]["cpu"]["temperature"] for s in self.series]
        loads = [s["metrics"]["cpu"]["load"] for s in self.series]
        fans = sorted(f["value"] for s in self.series for f in s["metrics"].get("fans", [])
                      if "Fan" in str(f.get("type", "")))
        lo, hi = SPANS["temperature"]
        self.assertTrue(all(lo <= t <= hi for t in temps), (min(temps), max(temps)))
        lo, hi = SPANS["load"]
        self.assertTrue(all(lo <= v <= hi for v in loads), (min(loads), max(loads)))
        self.assertTrue(fans, "the recording reports no fan row at all")
        lo, hi = SPANS["fan"]
        self.assertTrue(all(lo <= v <= hi for v in fans), (fans[0], fans[-1]))

    def test_the_fan_count_is_stable_and_fits_the_reserved_slots(self):
        """The row table below is scoped to what the box reported.  If the count wandered over the
        series, "every row this box can have" would not be one bounded set."""
        counts = sorted({len(s["metrics"].get("fans") or []) for s in self.series})
        self.assertEqual(len(counts), 1, counts)
        self.assertLessEqual(counts[0], len(themes.FAN_SLOTS),
                             (counts[0], len(themes.FAN_SLOTS)))

    def test_every_bar_row_this_box_could_have_is_answered_at_every_sample(self):
        """The rule that makes the `bars` clip durable rather than lucky.

        `themes.bars_recipe()` builds the labelled rows - the six fixed readings and the drive
        row that went in on 2026-11-14 - and then the reserved fan slots.  A slot past the
        reported count has no subject, and a row with no subject draws empty in the old drawing
        and the new one alike - so the changes that move rows with no subject, or a pair that
        cannot be divided, cannot move a frame of this clip.  What has to hold is that every row
        this recording could have had gets a reading at every one of its twelve samples.

        Rows are told apart by **shape**, not by offset.  The previous version sliced
        `BARS_ROWS[len(fixed):]` and called everything past the six a fan slot, which is how an
        inserted row broke it with `invalid literal for int(): 'Temperature'` - an assumption
        about where rows live, checked by counting rather than by asking what they are.
        """
        labelled = [row for row in themes.BARS_ROWS if row[0] is not None]
        slots = [row for row in themes.BARS_ROWS if row[0] is None]
        self.assertEqual(len(labelled), len(themes.BARS_FIXED_ROWS) + len(themes.BARS_DISK_ROWS),
                         f"{len(labelled)} labelled rows in the table: the split by shape here "
                         "has to agree with the split the recipe draws")
        gaps = []
        for n, sample in enumerate(self.series):
            values, _ = themes.values(sample["metrics"],
                                      preview_gif.series_clock(sample, self.tzoff))
            mine = labelled + [
                row for row in slots
                if int(row[1].split()[1]) - 1 < len(sample["metrics"].get("fans") or [])]
            unanswered = sorted({source for _label, bar, text, _lo, _hi in mine
                                 for source in (bar, text) if source and source not in values})
            if unanswered:
                gaps.append((n, unanswered))
        self.assertEqual(gaps, [],
                         f"the published series leaves a row this box has unanswered, so the "
                         f"tracked clip is no longer what the current drawing would paint at it: "
                         f"{gaps}")


if __name__ == "__main__":
    unittest.main()
