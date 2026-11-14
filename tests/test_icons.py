#!/usr/bin/env python3
"""The gutter figures: geometry that stays in its box, colour that comes from the row.

`bars` gained a column of small vector figures on 2026-11-14 at the owner's request - a
die, a card, a board, a drive, a rotor, a volute, a stick, a package, a dial.  They are
drawn, not fonts and not pictures: a glyph from an icon font resolves against whatever
face this machine has installed, and a layout that names a family this box cannot resolve
**drops the row** (measured, docs/limits.md: the CI runner with no CJK face loses the
`simsun` rows), while a baked PNG cannot be moved, resized or recoloured from a file at
all.  So the figures are polygons in `render.ICONS`, named from a layout through the
`special` kind that already exists, and this file is what keeps them honest.

Eleven rules, all of them measured out of the shipped painter rather than asserted about
intent:

* every registered figure puts down ink, and the registry is walked, not listed - an entry
  that draws nothing is a name a layout could ask for and get silence on;
* **a figure stays inside the box it declares.**  The first cut of the die drew its leads
  2.6 px beyond the box on all four sides, which put a CPU's ink at x=27.6 against a label
  column starting at x=28: the two doors disagreed by 1 720 pixels and the glass would have
  read as fuzz.  The box is the promise the clearances are measured against;
* the gutter clears the label column and the meters on every row, measured as ink;
* both doors put down the same pixels at every reading, and the parity gate's 0 px is
  re-asserted here at the column where the figures actually live, because a whole-frame
  diff can be paid for by an offset in one of them and still come out even;
* the pump figure is not the rotor figure - a measured pixel difference, not a rename;
* the variant is chosen by the channel's reported **type** and never by its label, and the
  two cases are driven apart in code: a fan row named `CPU PUMP` that reports `type: Fan`
  draws a rotor, and the same row reporting `Pump` draws the volute;
* a row this machine cannot answer draws no figure, in either door, and its absence is
  reported rather than left as a hole in the column;
* the usage dial's **needle is the reading**: the ink of that figure moves with the value,
  and it moves the same way through the file;
* a figure's ink is its row's ramp colour, sampled and compared, so a hot row cannot show
  a cool chip beside a hot meter;
* one table decides which row gets which figure (`themes.ROW_ICONS`), and the painter
  reaches that same object rather than a copy of it;
* the census this file prints - figures per export, ink per figure, added pixels - is
  printed, so docs name a command instead of carrying numbers.
"""
from __future__ import annotations

import datetime
import unittest

from tests import fixtures

from xigmalcd import layout, render, themes

WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)

#: A body that answers every row of the block, with the two channel types this program
#: pins: the cooler's fan and the pump on `PUMP_SYS1` (docs/limits.md, PROTOCOL.md §8).
FULL = {"cpu": {"temperature": 62.0, "load": 3.0},
        "gpu": {"temperature": 44.0, "fan": 34.0, "memoryUsage": 15952,
                "dedicatedTotal": 16376},
        "motherboard": {"temperature": 40.0},
        "memory": {"used": 84480, "total": 126155},
        "drives": [{"name": "nvme0", "temperature": 40}, {"name": "nvme1", "temperature": 29}],
        "fans": [{"name": "Fan CPU", "value": 1660, "type": "Fan"},
                 {"name": "CPU PUMP", "value": 2455, "type": "Pump"}],
        "timestamp": {}}

GUTTER = range(0, render.BARS_ICON_X + render.BARS_ICON_BOX[0])   # the column asked for
INk = 8            # an alpha above this counts as ink, the same threshold as the row tests


def pitch() -> int:
    return min(render.BARS_ROW_MAX, max(render.BARS_ROW_MIN,
                                        render.BARS_SPAN // len(themes.BARS_ROWS)))


def alpha(img):
    return img.convert("RGBA").getchannel("A").load()


def ink_box(d, xs, ys) -> tuple:
    pts = [(x, y) for y in ys for x in xs if d[x, y] > INk]
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


class FiguresDraw(unittest.TestCase):
    """The registry itself: everything in it is drawable, and drawable means ink."""

    def test_every_registered_figure_puts_down_ink(self):
        empty = []
        sizes = {}
        for name in sorted(render.ICONS):
            img = render.Image.new("RGBA", (render.W * render.SS, render.H * render.SS),
                                   (0, 0, 0, 0))
            d = render.ImageDraw.Draw(img)
            render.draw_icon(d, name, 20, 20, 22, 22, (255, 255, 255, 255), frac=0.5)
            a = img.getchannel("A").load()
            n = sum(1 for y in range(0, 80) for x in range(0, 80) if a[x, y] > INk)
            sizes[name] = n
            if n < 30:
                empty.append((name, n))
        self.assertEqual(empty, [], f"figures that draw almost nothing: {empty}")
        print("  figure ink, device px in a 22 px box: "
              + ", ".join(f"{k} {v}" for k, v in sorted(sizes.items())))

    def test_an_unknown_figure_is_refused_rather_than_drawn_as_something_else(self):
        img = render.Image.new("RGBA", (960, 960), (0, 0, 0, 0))
        self.assertIsNone(render.draw_icon(render.ImageDraw.Draw(img), "no-such-figure",
                                           10, 10, 22, 22, (255, 255, 255, 255)))

    def test_ink_stays_inside_the_declared_box(self):
        """The box is the promise.  Leads, notches and outlet stubs may not cross it."""
        over = {}
        for name in sorted(render.ICONS):
            img = render.Image.new("RGBA", (render.W * render.SS, render.H * render.SS),
                                   (0, 0, 0, 0))
            d = render.ImageDraw.Draw(img)
            x0, y0, w, h = 20, 20, 22, 22
            render.draw_icon(d, name, x0, y0, w, h, (255, 255, 255, 255), frac=0.5)
            a = img.getchannel("A").load()
            ss = render.SS
            box = ink_box(a, range((x0 - 6) * ss, (x0 + w + 6) * ss),
                          range((y0 - 6) * ss, (y0 + h + 6) * ss))
            if box is None:
                self.fail(f"{name} drew nothing at all")
            left, top, right, bottom = (box[0] / ss, box[1] / ss, box[2] / ss, box[3] / ss)
            over[name] = (round(x0 - left, 2), round(right - (x0 + w), 2),
                          round(y0 - top, 2), round(bottom - (y0 + h), 2))
        bad = {k: v for k, v in over.items() if max(v) > 0.0}
        self.assertEqual(bad, {},
                         f"figures whose ink crosses the box (left,right,top,bottom px): {bad}")

    def test_the_volute_is_not_the_rotor(self):
        """A pump looks different from a fan, measurably: not a rename, a different figure."""
        def one(name):
            img = render.Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            render.draw_icon(render.ImageDraw.Draw(img), name, 20, 20, 22, 22,
                             (255, 255, 255, 255), frac=0.8)
            return img
        a, b = one("fan").load(), one("impeller").load()
        diff = sum(1 for y in range(96) for x in range(96) if a[x, y] != b[x, y])
        self.assertGreater(diff, 120,
                           f"the pump figure differs from the rotor by only {diff} device px")


class GutterOnTheGlass(unittest.TestCase):
    """The figures where they are actually drawn: the `bars` block, both doors."""

    @classmethod
    def setUpClass(cls):
        cls.code = render.draw(dict(FULL), "bars", bg=render.OVERLAY)
        cls.file, _notes = themes.draw(themes.export("bars"), dict(FULL), WHEN)

    def row_band(self, index: int) -> range:
        centre = render.BARS_Y0 + index * pitch()
        return range(centre - 16, centre + 17)

    def test_the_gutter_holds_exactly_one_figure_per_answered_row(self):
        n = sum(1 for r in themes.BARS_ROWS
                if render.figure_for(r[1], "Pump" if r[1] == "Fan 2 Speed" else None))
        self.assertEqual(n, len(themes.BARS_ROWS),
                         "every row of this block names a figure")
        icons = [w for w in themes.export("bars")["osd"]["widget"]
                 if w["type"] == "special" and str(w["property"][0].get("name", "")
                                                   ).startswith("icon-")]
        self.assertEqual(len(icons), n,
                         f"{len(icons)} icon widgets in the export against {n} rows")

    def test_no_figure_ink_touches_the_label_or_the_meter(self):
        ca, cb = alpha(self.code), alpha(self.file)
        for door, d in (("code", ca), ("file", cb)):
            for i in range(len(themes.BARS_ROWS)):
                band = self.row_band(i)
                gutter = ink_box(d, GUTTER, band)
                self.assertIsNotNone(gutter, f"{door} row {i}: no figure ink at all")
                self.assertLess(gutter[2], render.BARS_LBL_X,
                                f"{door} row {i}: figure ink reaches x={gutter[2]}, and the "
                                f"label column starts at {render.BARS_LBL_X}")
                # and the row's own figure must not reach the meter of the row above or below
                self.assertLessEqual(gutter[3] - gutter[1] + 1, render.BARS_ICON_BOX[1] + 1,
                                     f"{door} row {i}: the figure is {gutter[3] - gutter[1] + 1} "
                                     f"px tall in a {pitch()} px pitch")

    def test_the_two_doors_agree_on_the_figure_column_at_every_reading(self):
        """Parity where the change is, not only in the frame's totals.

        `tests/test_export_parity.py` compares whole frames and reports 0 px, which is the
        bar to clear; this compares the gutter column row by row, because a difference
        inside the column can be paid for by an opposite one outside it and still sum to
        zero - and it was exactly such a pair of mistakes (double-scaled geometry, and two
        draw orders) that the frame total hid for a day.
        """
        ca, cb = alpha(self.code), alpha(self.file)
        rgb_a, rgb_b = self.code.convert("RGB").load(), self.file.convert("RGB").load()
        rows = []
        for i in range(len(themes.BARS_ROWS)):
            band = self.row_band(i)
            diff = sum(1 for y in band for x in GUTTER
                       if ca[x, y] != cb[x, y] or rgb_a[x, y] != rgb_b[x, y])
            rows.append((i, diff))
        bad = [r for r in rows if r[1]]
        self.assertEqual(bad, [], f"gutter pixels differing, by row: {bad}")

    def test_a_row_with_no_reading_draws_no_figure_in_either_door(self):
        body = dict(FULL, gpu={"temperature": 44.0, "memoryUsage": 15952,
                               "dedicatedTotal": 16376})   # a card with no fan reading
        code = alpha(render.draw(dict(body, timestamp={}), "bars", bg=render.OVERLAY))
        file_img, notes = themes.draw(themes.export("bars"), dict(body, timestamp={}), WHEN)
        index = [i for i, r in enumerate(themes.BARS_ROWS)
                 if r[1] == "GPU Fans Speed"][0]
        band = self.row_band(index)
        self.assertIsNone(ink_box(code, GUTTER, band),
                          "the code door drew a figure for a reading that does not exist")
        self.assertIsNone(ink_box(alpha(file_img), GUTTER, band),
                          "the file door drew one too")
        self.assertIn("GPU Fans Speed", [m for m in notes["missing"]
                                         if not str(m).startswith("font")],
                      "and the row did not say why it was empty")

    def test_the_needle_of_the_usage_dial_is_the_reading(self):
        """LOAD at 3 % and LOAD at 97 % must not be the same picture."""
        def dial(load):
            img = render.draw(dict(FULL, cpu={"temperature": 62.0, "load": load}), "bars",
                              bg=render.OVERLAY)
            index = [i for i, r in enumerate(themes.BARS_ROWS) if r[1] == "CPU Usage"][0]
            a = alpha(img)
            return ink_box(a, GUTTER, self.row_band(index))
        low, high = dial(3.0), dial(97.0)
        self.assertIsNotNone(low)
        self.assertIsNotNone(high)
        img_low = render.draw(dict(FULL, cpu={"temperature": 62.0, "load": 3.0}), "bars",
                              bg=render.OVERLAY)
        img_high = render.draw(dict(FULL, cpu={"temperature": 62.0, "load": 97.0}), "bars",
                               bg=render.OVERLAY)
        la, ha = alpha(img_low), alpha(img_high)
        index = [i for i, r in enumerate(themes.BARS_ROWS) if r[1] == "CPU Usage"][0]
        moved = sum(1 for y in self.row_band(index) for x in GUTTER
                    if la[x, y] != ha[x, y])
        self.assertGreater(moved, 60,
                           f"the dial changed by only {moved} px between 3 % and 97 % load")
        # and the file door moves the same way: the needle is one computation, not two
        fa_low = alpha(themes.draw(themes.export("bars"),
                                   dict(FULL, cpu={"temperature": 62.0, "load": 3.0},
                                        timestamp={}), WHEN)[0])
        fa_high = alpha(themes.draw(themes.export("bars"),
                                    dict(FULL, cpu={"temperature": 62.0, "load": 97.0},
                                         timestamp={}), WHEN)[0])
        moved_file = sum(1 for y in self.row_band(index) for x in GUTTER
                         if fa_low[x, y] != fa_high[x, y])
        self.assertGreater(moved_file, 60,
                           f"the layout's dial moved {moved_file} px against the painter's "
                           f"{moved} - one of the two is not reading the fraction")

    def test_a_figure_is_coloured_by_its_row_s_ramp_not_a_colour_of_ours(self):
        """Sample the solid ink of two figures whose readings sit far apart on their scales.

        A cold CPU die and a hot pump volute are the pair that shows the rule is doing
        something: the colour is not decorative, it is the row's own ramp at the row's own
        reading - the same call its meter fills with - so a figure cannot go calm beside a
        meter that is not.  The antialiased edge pixels are excluded (alpha over 200), and
        the tolerance is the edge blending of a 22 px figure, not a threshold picked to pass.
        """
        rgb = self.code.convert("RGB").load()
        cov = alpha(self.code)
        by_source = {r[1]: i for i, r in enumerate(themes.BARS_ROWS)}

        def mean_ink(source):
            band = self.row_band(by_source[source])
            px = [(x, y) for y in band for x in GUTTER if cov[x, y] > 200]
            self.assertTrue(px, f"{source}: no solid figure ink to sample")
            return tuple(sum(rgb[x, y][c] for x, y in px) / len(px) for c in range(3))

        cases = (("CPU Temperature", 30, 90, FULL["cpu"]["temperature"]),
                 ("Fan 2 Speed", 0, 3000, FULL["fans"][1]["value"]),
                 ("GPU Memory Rate", 0, 100, 15952 / 16376 * 100))
        for source, lo, hi, val in cases:
            want = render.heat((val - lo) / (hi - lo))
            got = mean_ink(source)
            delta = max(abs(got[k] - want[k]) for k in range(3))
            self.assertLess(delta, 46,
                            f"the {source} figure reads {tuple(int(v) for v in got)} where "
                            f"its meter's ramp at {val} on {lo}..{hi} is "
                            f"{tuple(int(v) for v in want)}")


class OneTableOneRule(unittest.TestCase):
    """Where the mapping lives, and what the variant is allowed to be keyed on."""

    def test_the_painter_and_the_recipe_read_one_table(self):
        self.assertIs(render.row_icons(), themes.ROW_ICONS,
                      "the painter is holding its own copy of the row -> figure mapping")

    def test_the_distinct_rows_of_the_block_get_distinct_figures(self):
        """Both doors can agree on a wrong mapping, so the mapping is checked on its own.

        The census and the parity gate hold the two doors equal; they cannot say whether the
        figure chosen for `CPU` is a die.  What can be said, without inventing an opinion
        about art: the rows that are about different things must not wear the same figure,
        and the rows that are the same *kind* of thing (two drives, two tachometers) must.
        A mutation that gave the CPU row the GPU's card changed nothing in either door and
        cost no failure until this check existed - which is the reminder that parity is a
        relation, not a specification.
        """
        # the whole vocabulary, not the drawn block: `Disk 3`/`Fan 4` are answered names
        # that no row of `bars` currently draws, and their figures are part of the claim
        figures = {src: render.figure_for(src, None) for src in themes.ROW_ICONS}
        for src in ("CPU Temperature", "GPU Temperature", "Motherboard Temperature",
                    "RAM Rate", "GPU Memory Rate", "CPU Usage", "GPU Fans Speed"):
            self.assertIsNotNone(figures[src], f"{src} has no figure")
        trio = {figures[s] for s in ("CPU Temperature", "GPU Temperature",
                                     "Motherboard Temperature")}
        self.assertEqual(len(trio), 3, f"the three temperature rows share figures: {trio}")
        pair = {figures[s] for s in ("RAM Rate", "GPU Memory Rate")}
        self.assertEqual(len(pair), 2, f"system memory and card memory wear one figure: {pair}")
        drives = {figures[f"Disk {i} Temperature"] for i in (1, 2, 3, 4)}
        fans = {figures[f"Fan {i} Speed"] for i in (1, 2, 3, 4)}
        self.assertEqual(len(drives), 1, f"the storage rows do not agree on a figure: {drives}")
        self.assertEqual(len(fans), 1, f"the tachometer rows do not agree on a figure: {fans}")
        self.assertNotIn(drives.pop(), trio | pair,
                         "storage reuses a figure that belongs to a temperature or memory row")
        self.assertNotEqual(fans.pop(), figures["CPU Usage"],
                            "the rotor is also the dial: the block would read as a column of "
                            "wheels")

    def test_the_variant_is_keyed_on_the_reported_type_never_the_label(self):
        """The honesty check: a row called `CPU PUMP` that reports `Fan` stays a rotor.

        Label-sniffing is how this project has been wrong about sensors four times - the
        cooler's pump channel reads a name a person typed in `/etc/sensors.d`, and the
        chip publishes none at all.  What was measured is the `type`, so what is drawn is
        chosen from the `type`.
        """
        rotor_body = dict(FULL, fans=[{"name": "Fan CPU", "value": 1660, "type": "Fan"},
                                      {"name": "CPU PUMP", "value": 2455, "type": "Fan"}])
        volute_body = dict(FULL, fans=[{"name": "My Cooler", "value": 1660, "type": "Fan"},
                                       {"name": "Pump", "value": 2455, "type": "Pump"}])
        index = [i for i, r in enumerate(themes.BARS_ROWS) if r[1] == "Fan 2 Speed"][0]
        a = alpha(render.draw(dict(rotor_body, timestamp={}), "bars", bg=render.OVERLAY))
        b = alpha(render.draw(dict(volute_body, timestamp={}), "bars", bg=render.OVERLAY))
        box_rotor = ink_box(a, GUTTER, self.row_band(index))
        box_volute = ink_box(b, GUTTER, self.row_band(index))
        self.assertNotEqual(box_rotor, box_volute,
                            "a row renamed to `Pump` changed figure - the drawing is "
                            "reading labels")
        # ...and the two doors have to agree at **both** bodies, not one.  A version of
        # this check that compared only the `Pump` case passed while the layout door picked
        # its figure by reading the row's label: at the body where the label says `CPU PUMP`
        # but the machine reports `type: Fan`, the painter draws a rotor and that door draws
        # a volute, and the disagreement is exactly the defect - so the quiet case is the
        # one that carries the information.
        for label, body in (("a type that says Pump", volute_body),
                            ("a label that says PUMP, a type that says Fan", rotor_body)):
            la = alpha(render.draw(dict(body, timestamp={}), "bars", bg=render.OVERLAY))
            lb = alpha(themes.draw(themes.export("bars"), dict(body, timestamp={}), WHEN)[0])
            diff = sum(1 for y in self.row_band(index) for x in GUTTER
                       if la[x, y] != lb[x, y])
            self.assertEqual(diff, 0,
                             f"the doors disagree about the pump figure at {label}: {diff} px "
                             "in the gutter column")

    def row_band(self, index: int) -> range:
        centre = render.BARS_Y0 + index * pitch()
        return range(centre - 16, centre + 17)

    def test_the_special_names_are_generated_from_the_figure_table(self):
        """A figure in `render.ICONS` is drawable from a file, by the same name it has in code."""
        missing = [k for k in render.ICONS if f"icon-{k}" not in themes.SPECIALS]
        self.assertEqual(missing, [], f"figures no layout can ask for: {missing}")
        for name, fn in sorted(themes.SPECIALS.items()):
            if name.startswith("icon-"):
                self.assertFalse(getattr(fn, "needs_face", True),
                                 f"{name} would be dropped for a missing font")
                self.assertEqual(fn.draws_icon, name[len("icon-"):],
                                 f"{name} draws a different figure than its name says")

    def test_the_new_extension_key_carries_its_reason_where_the_others_do(self):
        self.assertIn("iconVariant", themes.XIGMA_KEYS,
                      "`xigma.iconVariant` is used by the export and stated nowhere - the "
                      "census gate refuses a key without a reason, and so should this file")
        self.assertIn("iconVariant",
                      {k for w in themes.export("bars")["osd"]["widget"]
                       for p in [w["property"][0]] for k in (p.get("xigma") or {})},
                      "the generated file no longer declares the variant key, so the "
                      "pump row would draw a rotor on one door and a volute on the other")


class TheCensus(unittest.TestCase):
    """Every figure count this page or another might want, printed rather than copied."""

    @classmethod
    def setUpClass(cls):
        cls.code = render.draw(dict(FULL), "bars", bg=render.OVERLAY)

    def test_the_census_of_figure_rows_and_gutter_ink_prints_for_this_machine(self):
        obj = themes.export("bars")
        widgets = obj["osd"]["widget"]
        icons = [w for w in widgets if w["type"] == "special"
                 and str(w["property"][0].get("name", "")).startswith("icon-")]
        both = themes.parity("bars", dict(FULL), WHEN)
        gutter = sum(1 for y in range(render.H) for x in GUTTER
                     if alpha(self.code)[x, y] > INk)
        print(f"  figure census: {len(icons)} icon rows of {len(themes.BARS_ROWS)}; "
              f"{len(widgets)} widgets in the export; {gutter} lit px in the gutter column "
              f"(x 0..{max(GUTTER)}) of {both['code_px']} in the frame; the two doors "
              f"{both['code_px']}/{both['layout_px']} at {both['diff_px']} differing px")
        self.assertEqual(len(icons), len(themes.BARS_ROWS))
        self.assertGreater(gutter, 800,
                           "the gutter column holds almost no ink: something stopped "
                           "drawing the figures")


if __name__ == "__main__":
    unittest.main(verbosity=2)
