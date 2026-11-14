#!/usr/bin/env python3
"""What the vendor's own files carry, counted from the files: the census behind `--print-theme-fields`.

Ported from the "theme field census" section of `tools/selftest.sh`, whose bash block asserted a
table of counts and then ran the printed door to see that the table and the door agree.

Why this is a check about code and not about the vendor's data: `field_census()` counts keys in the
27 layouts this repository tracks, and `keys_read()` takes the readable set out of `layout.py`'s own
source with `ast`.  Neither list is kept by hand, so the two can only disagree in three ways - a key
the painter reads that no shipped file carries, a key a file carries that nothing reads, and an
extension key with no reason written next to it.  Each of those is a defect in *this* program, and
each is asserted below.  The counts themselves (152 widgets, 33 keys) are claims about tracked bytes,
so they answer the same on every machine; the one number that would be machine-dependent, which
fonts are installed, never enters this file.

Four rules:

* the census is the library: 152 widgets in 27 files, five kinds, **33** distinct `property` keys,
  and `x` is the one key every kind carries;
* the two directions of the drift are both pinned - four keys the painter reads with no shipped
  file to show for it, and eleven the files carry that nothing reads, each of those eleven with a
  stated reason in `themes.UNREAD_WHY`;
* the extension names `layout.py` reads are exactly the names with an entry in `themes.XIGMA_KEYS`,
  which is the mechanism that makes "every schema addition has a stated reason, or it does not go
  in" more than a sentence;
* `--print-theme-fields` prints every key the census found and never prints a port, so the door a
  reader runs is the same measurement, not a second copy of it.
"""
from __future__ import annotations

import unittest

from tests import fixtures

from xigmalcd import themes

#: The four names `layout.py` reads that no shipped layout carries.  `lineColor` and `lineWidth`
#: are this program's own, added for `line` rows the vendor never drew; `name` and `xigma` are
#: structural (`osd.widget[].name`, and the extension namespace), not per-key reads.
READ_WITHOUT_A_FILE = ["lineColor", "lineWidth", "name", "xigma"]

#: The nine extension keys, spelled out because the pair of lists has to be equal in both
#: directions: a tenth name appearing in `layout.py` without a `XIGMA_KEYS` entry fails here, and
#: so does an entry no painter reads.
EXTENSION_KEYS = ["anchor", "arcPaint", "autoFitMax", "barPaint", "colourRamp",
                  "colourStops", "fitArc", "format", "iconVariant", "showIf"]
# `iconVariant` joined on 2026-11-14 with the gutter figures: a row asks that its figure
# change shape according to **another** of its readings (`Fan 2 Type` answering `Pump`
# draws a volute rather than a rotor).  The reason is written where the mechanism keeps
# them, in `themes.XIGMA_KEYS`, and the check below refuses a key read by the painter with
# no reason beside it - which is the whole value of listing them twice.


class FieldCensus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cen = themes.field_census()
        cls.read, cls.sub = themes.keys_read()

    def test_the_library_is_the_count_the_census_reports(self):
        """A census that silently started covering fewer files would make every other number in
        this file mean something else, so the shape comes first: 152 widgets in the 27 layouts,
        split across the five kinds the painter knows."""
        self.assertEqual(self.cen["widgets"], 152, self.cen["kinds"])
        self.assertEqual(self.cen["kinds"], {"data": 66, "text": 66, "bar": 15, "line": 4,
                                            "arc": 1}, self.cen["kinds"])
        self.assertEqual(len(self.cen["keys"]), 33, sorted(self.cen["keys"]))

    def test_one_key_is_carried_by_every_kind_the_painter_draws(self):
        """`x` is the shared geometry: if a kind stopped answering for it, the snap rules in
        `xigmaui/edit.py` would be counting a smaller corpus than they claim."""
        self.assertEqual(set(self.cen["keys"]["x"]), {"data", "text", "bar", "line", "arc"},
                         self.cen["keys"]["x"])

    def test_the_painter_and_the_census_cannot_drift_in_either_direction(self):
        """Two lists, both derived, and the difference between them pinned as a set of names.

        `keys_read()` walks `layout.py`'s source with `ast`, so a key that stops being read drops
        out of the readable set and into the unread one - and this assertion is where that shows
        up.  The unread side is `themes.UNREAD_WHY`, whose whole purpose is that "we ignore this
        key" is only honest when you can say what the key was for.
        """
        missing_from_files = sorted(set(self.read) - set(self.cen["keys"]))
        self.assertEqual(missing_from_files, READ_WITHOUT_A_FILE, missing_from_files)
        never_read = sorted(set(self.cen["keys"]) - set(self.read))
        self.assertEqual(never_read, sorted(themes.UNREAD_WHY), never_read)
        self.assertIn("rotate", self.read)
        self.assertIn("xigma", self.read)

    def test_the_extension_names_the_painter_reads_are_the_names_with_a_written_reason(self):
        """The mechanism behind the rule: `XIGMA_KEYS` is not a table somebody maintains beside
        the code, it is the set `layout.py` was found to read.  Add a key to the painter and this
        fails until the reason is written down; delete the reason and it fails too."""
        self.assertEqual(sorted(self.sub), EXTENSION_KEYS, self.sub)
        self.assertEqual(set(self.sub), set(themes.XIGMA_KEYS),
                         (sorted(set(self.sub) - set(themes.XIGMA_KEYS)),
                          sorted(set(themes.XIGMA_KEYS) - set(self.sub))))

    def test_the_two_text_looks_the_program_ignores_are_one_value_deep(self):
        """`italic` and `underline` are the keys a reader would notice missing from a drawing, so
        dropping them needs evidence: every widget that carries them carries them as False."""
        self.assertEqual(self.cen["values"]["italic"], {"False": 132}, self.cen["values"]["italic"])
        self.assertEqual(self.cen["values"]["underline"], {"False": 132})
        self.assertEqual(self.cen["values"]["enableMove"], {"False": 152})

    def test_time_is_a_save_stamp_per_file_rather_than_a_reading(self):
        """27 distinct `time` values over 152 widgets, every file answering exactly one inside
        itself.  That is the reason the exports this program writes omit the key: a per-theme save
        stamp is not something the panel shows, and re-writing it on every save would make an
        unchanged theme differ by bytes."""
        self.assertEqual(len(self.cen["values"]["time"]), 27, sorted(self.cen["values"]["time"]))
        self.assertEqual(set(self.cen["time_per_file"].values()), {1}, self.cen["time_per_file"])
        self.assertEqual(len(self.cen["time_per_file"]), 27)

    def test_the_printed_door_is_the_same_measurement_and_never_names_a_port(self):
        """The census above is what `--print-theme-fields` prints, so a key can be missing from
        the door only by a bug.  The port half is the shipped promise: no argument this program
        takes, and nothing it prints, names a serial device."""
        got = fixtures.run("python", "-m", "xigmalcd", "--print-theme-fields")
        self.assertEqual(got.returncode, 0, got.stdout[-1500:] + got.stderr[-1500:])
        out = got.stdout
        self.assertNotIn("ttyACM", out, out[-800:])
        self.assertNotIn("/dev/tty", out, out[-800:])
        absent = [k for k in self.cen["keys"]
                  if f"  {k}" not in out and f"    {k} " not in out]
        self.assertEqual(absent, [], sorted(absent))


if __name__ == "__main__":
    unittest.main()
