#!/usr/bin/env python3
"""`alpha`'s three `special` rows, held to the theme the way a convention is held to its function.

Ported from the specials block of `tools/selftest.sh`'s vendor-theme section.  `render.theme_alpha`
draws a fan pair and two temperature figures with functions; `themes.SPECIALS` lets a layout file ask
for the same drawings through one row each.  The claim this file defends is not "roughly the same
place" but: **the pixels the row paints are exactly the pixels the theme paints, with the theme's own
bytes, at the size the theme's own rule picks.**

Four rules, and each is spelled out a second way rather than read off the thing it checks:

* the fan pair's shared size is `max(FAN_MIN, min(fit(left), fit(right)))`, and a pair sized apart
  differs from the joint drawing exactly when the two fits disagree - which is what makes the joint
  rule load-bearing instead of decorative;
* `_fit_arc`'s joint sizing is the smaller of the two strings measured alone, and **no single
  `xigma.autoFitMax` width reproduces what the ring's hole decides** - searched exhaustively over
  every whole-pixel budget the canvas holds, against all six readings at once;
* the temperature rows own the free part of each ring's hole, and the zone is derived from the
  ring's own drawing - `temp_arc` on a bare canvas, same supersampling, same downscale - so the
  check is not a rectangle somebody picked;
* and each registered drawing's `.door` marker, which `--list-specials` prints, is read against
  the `layout.draw_special_*` call inside that same function's body - two places one fact is
  written down, and the listing can lie without anything else noticing.

One trap is worth keeping in prose, because it fooled this repository once: a probe that forgets to
inject `themes.SPECIALS` draws nothing at all and reports `boxes: []`, which reads like an empty
answer rather than like a broken probe.
"""
from __future__ import annotations

import datetime
import inspect
import itertools
import unittest
from PIL import Image, ImageDraw, ImageChops

from tests import fixtures

from xigmalcd import layout
from xigmalcd import render
from xigmalcd import themes

FAN_CX = (render.A26_FAN_X[0] + render.A26_FAN_X[1]) // 2
FAN_PITCH = render.A26_FAN_X[1] - render.A26_FAN_X[0]
R_IN = render.A26_RING_R - render.A26_RING_W

#: Written out rather than read off `sensors`, so the number of pairs this walks is a fact about
#: the check and not about a machine.
CPU_TACHES = (None, 999, 1016, 2051, 2448, 9999)
GPU_FANS = (None, 0, 5, 41, 100)
TEMP_VALS = (None, 5, 22, 57, 100, 241)
ARC_PAIRS = list(itertools.product(TEMP_VALS, repeat=2))

#: Two draws of one frame, so a live second between them would land in the isolation set and be
#: counted as part of a fan figure.
FAN_WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)


def css(colour) -> str:
    return f"rgba({colour[0]}, {colour[1]}, {colour[2]}, {colour[3] / 255:.6g})"


def fan_metrics(cpu, gpu) -> dict:
    gpu_part = {"temperature": 47.0}
    if gpu is not None:
        gpu_part["fan"] = float(gpu)
    return {"cpu": {"temperature": 57.0}, "gpu": gpu_part,
            "fans": ([{"name": "Fan CPU", "value": cpu, "type": "Fan"}]
                     if cpu is not None else [])}


def fan_prop() -> dict:
    return {"name": "fan-figures", "x": FAN_CX, "y": render.A26_FAN_Y, "width": FAN_PITCH,
            "fontFamily": "dejavu", "fontSize": render.A26_FAN_F, "bold": False,
            "textColor": css(render.A26_WHITE),
            "xigma": {"anchor": "ma", "autoFitMax": render.A26_FAN_MAX_W}}


def temp_prop(name="temp-values", y=None, ceiling=None) -> dict:
    """One of `alpha`'s two temperature rows.  Every number comes out of `render.py`'s own
    constants, because a number written here would be a second opinion about the theme."""
    return {"name": name,
            "x": (render.A26_TCOL_X[0] + render.A26_TCOL_X[1]) // 2,
            "y": y if y is not None else render.A26_TVAL_Y,
            "width": render.A26_TCOL_X[1] - render.A26_TCOL_X[0],
            "fontFamily": "dejavu",
            "fontSize": ceiling if ceiling is not None else render.A26_TVAL_F,
            "bold": True, "textColor": css(render.A26_WHITE),
            "xigma": {"anchor": "ma",
                      "fitArc": {"cy": render.A26_RING_Y, "radius": R_IN,
                                 "width": render.A26_RING_W,
                                 "angleStart": render.A26_ARC_START - 90,
                                 "angleEnd": render.A26_ARC_START + render.A26_ARC_SWEEP - 90}}}


def rows_frame(props: list, body: dict) -> tuple:
    """A frame carrying exactly these `special` rows, through the loop's own door."""
    values, _absent = themes.values(body)
    themes.fill_lines(values, body)
    obj = {"width": render.W, "height": render.H,
           "osd": {"widget": [{"id": "xigma-alpha-" + p["name"], "type": "special",
                               "property": [p]} for p in props]}}
    return layout.draw_theme(obj, values, canvas=(render.W, render.H), specials=themes.SPECIALS)


def row_box(notes: dict) -> tuple:
    """The box the loop records for the one special row in this frame."""
    rows = [b for b in notes["boxes"] if b[0] == "special"]
    assert len(rows) == 1, notes["boxes"]
    return rows[0][2]


def ink_of(flat: list) -> set:
    """Which pixels of a flattened frame are ink: alpha, not colour.  A downscale of a bright
    stroke against a transparent canvas leaves pixels whose colour channels are non-zero and whose
    alpha is zero - invisible, and a residual of whatever was drawn next to them."""
    return {k for k, v in enumerate(flat) if v[3]}


def arc_fit(strings, ceiling=render.A26_TVAL_F, cx=render.A26_TCOL_X[0], y=render.A26_TVAL_Y):
    img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
    return render._fit_arc(img, tuple(strings), cx, render.A26_RING_Y, y, R_IN,
                           render.A26_RING_R, render.A26_ARC_START, render.A26_ARC_SWEEP, ceiling)


class FanPair(unittest.TestCase):
    """One `special` row against the row `theme_alpha` paints - same place, same bytes."""

    @classmethod
    def setUpClass(cls):
        cls.real_now = render._now
        render._now = lambda: FAN_WHEN.timetuple()

    @classmethod
    def tearDownClass(cls):
        render._now = cls.real_now

    def test_the_row_paints_the_themes_pixels_at_every_tachometer_pair(self):
        walked = 0
        for cpu in CPU_TACHES:
            for gpu in GPU_FANS:
                body = fan_metrics(cpu, gpu)
                with self.subTest(cpu=cpu, gpu=gpu):
                    img, notes = rows_frame([fan_prop()], body)
                    on = render.draw(body, "alpha")
                    off = render.draw(body, "alpha", fan=False)
                    flat_me = list(img.get_flattened_data())
                    flat_on, flat_off = list(on.get_flattened_data()), list(off.get_flattened_data())
                    theme_px = {k for k, v in enumerate(flat_on) if v != flat_off[k]}
                    file_px = {k for k, v in enumerate(flat_me) if v != (0, 0, 0, 0)}
                    self.assertGreater(theme_px, set(), "the theme drew no fan pair to compare")
                    self.assertEqual(theme_px, file_px,
                                     f"the row painted {len(file_px)} px where the theme "
                                     f"painted {len(theme_px)}")
                    for key in file_px:
                        self.assertEqual(flat_on[key], flat_me[key],
                                         "the same pixel, a different byte")
                    self.assertEqual(notes["missing"], [])
                    self.assertEqual(notes["gaps"], [])
                    walked += 1
        self.assertEqual(walked, len(CPU_TACHES) * len(GPU_FANS))

    def test_the_shared_size_is_the_smaller_fit_and_not_the_two_figures_apart(self):
        for cpu in CPU_TACHES:
            for gpu in GPU_FANS:
                body = fan_metrics(cpu, gpu)
                with self.subTest(cpu=cpu, gpu=gpu):
                    img, _notes = rows_frame([fan_prop()], body)
                    figures = (render.cpu_fan_figure(body), render.gpu_fan_figure(body))
                    fits = [render._fit_size(img, s, render.A26_FAN_MAX_W, render.A26_FAN_F,
                                             bold=False) for s in figures]
                    dev = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS),
                                    (0, 0, 0, 0))
                    size, _box = layout.draw_special_pair(ImageDraw.Draw(dev), fan_prop(), figures)
                    self.assertEqual(size, max(render.A26_FAN_MIN, min(fits)),
                                     f"{figures} fit at {fits}")

                    apart = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS),
                                      (0, 0, 0, 0))
                    drawer = ImageDraw.Draw(apart)
                    for x, text, own in zip((FAN_CX - FAN_PITCH // 2, FAN_CX + FAN_PITCH // 2),
                                            figures, fits):
                        render.fan_figures(drawer, (text,), (x,), render.A26_FAN_Y,
                                           render.A26_WHITE, bold=False,
                                           max_w=render.A26_FAN_MAX_W, ceiling=own, floor=own)
                    apart = apart.resize((render.W, render.H), Image.LANCZOS)
                    moved = sum(1 for q in ImageChops.difference(img, apart).get_flattened_data()
                                if q != (0, 0, 0, 0))
                    self.assertEqual(moved > 0, fits[0] != fits[1],
                                     f"fits {fits} apart by {moved} px: the joint rule should "
                                     "show up exactly when the two sizes disagree")

    def test_the_box_the_loop_reports_is_where_the_row_got_painted(self):
        """To within the handful of px a text metric can sit off the ink it measures."""
        for cpu, gpu in itertools.product(CPU_TACHES, GPU_FANS):
            body = fan_metrics(cpu, gpu)
            img, notes = rows_frame([fan_prop()], body)
            flat = list(img.get_flattened_data())
            painted = {k for k, v in enumerate(flat) if v != (0, 0, 0, 0)}
            if not painted:
                continue
            box = row_box(notes)
            ink = (min(k % render.W for k in painted), min(k // render.W for k in painted),
                   max(k % render.W for k in painted), max(k // render.W for k in painted))
            with self.subTest(cpu=cpu, gpu=gpu):
                for a, b in zip(box, ink):
                    self.assertLessEqual(abs(a - b), 4, f"{box} against {ink}")


class ArcSizing(unittest.TestCase):
    """What `xigma.fitArc` does that a width cannot."""

    def test_the_pair_rule_is_exactly_the_smaller_of_the_two_columns_own_size(self):
        for a, b in ARC_PAIRS:
            with self.subTest(cpu=a, gpu=b):
                sa, sb = arc_fit((render._deg(a),)), arc_fit((render._deg(b),))
                self.assertEqual(arc_fit((render._deg(a), render._deg(b))), min(sa, sb),
                                 "a group key would have been enough for this, and the "
                                 "joint walk says it is not about the group")

    def test_no_single_auto_fit_width_reproduces_what_the_ring_hole_decides(self):
        """Exhaustive over every whole-pixel budget the canvas holds, against all six readings at
        once - and not vacuous, because each reading's own ring size *is* reachable by some width."""
        only_draw = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

        def width_fit(text, budget):
            return render._fit_size(only_draw, text, budget, render.A26_TVAL_F, bold=True)

        strings = tuple(render._deg(v) for v in TEMP_VALS)
        budgets = range(40, render.W + 1)
        windows = {s: [b for b in budgets if width_fit(s, b) == arc_fit((s,))] for s in strings}
        self.assertTrue(all(windows[s] for s in strings),
                        {s: w[:3] for s, w in windows.items()})
        reproduced = [b for b in budgets if all(b in windows[s] for s in strings)]
        self.assertEqual(reproduced, [],
                         f"a width of {reproduced[:3]} px reproduces every reading's ring-chosen "
                         "size, so `fitArc` would no longer be needed")


class TemperatureRows(unittest.TestCase):
    """The two rows own the free part of the rings' holes, in both directions."""

    @classmethod
    def setUpClass(cls):
        cls.real_now = render._now
        render._now = lambda: FAN_WHEN.timetuple()
        # the ring's own ink, measured rather than guessed: `temp_arc` on a bare canvas, the same
        # supersampling and the same LANCZOS downscale `theme_alpha` ends with
        in_hole = lambda k: (min(((k % render.W - cx) ** 2 + (k // render.W - render.A26_RING_Y)
                                 ** 2) ** 0.5 for cx in render.A26_TCOL_X) < R_IN)
        tail = set()
        for value in TEMP_VALS[1:]:
            bare = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), render.OVERLAY)
            for cx in render.A26_TCOL_X:
                render.temp_arc(bare, cx, render.A26_RING_Y, float(value), render.A26_ARC_LO,
                                render.A26_ARC_MID, render.A26_ARC_HI, render.A26_RING_R,
                                render.A26_RING_W, render.A26_ARC_TRACK, render.A26_ARC_START,
                                render.A26_ARC_SWEEP)
            bare = bare.resize((render.W, render.H), Image.LANCZOS)
            tail |= {k for k, c in enumerate(bare.get_flattened_data()) if c[3] and in_hole(k)}
        cls.zone = {k for k in range(render.W * render.H) if in_hole(k) and k not in tail}
        cls.tail_px = len(tail)
        cls.clearance = min(R_IN - min(((k % render.W - cx) ** 2
                                        + (k // render.W - render.A26_RING_Y) ** 2) ** 0.5
                                       for cx in render.A26_TCOL_X) for k in tail)

    @classmethod
    def tearDownClass(cls):
        render._now = cls.real_now

    def test_the_rings_resampling_tail_is_smaller_than_the_clearance_the_fit_enforces(self):
        """Otherwise the zone would eat this row's own ink, and the coverage below could pass on
        a row that paints nothing."""
        self.assertLess(self.clearance, render.ARC_FIT_GAP,
                        f"the ring's tail reaches {self.clearance:.1f} px into the hole, the fit "
                        f"holds {render.ARC_FIT_GAP} px of clearance")

    @staticmethod
    def metrics(cpu, gpu) -> dict:
        c, g = {}, {}
        if cpu is not None:
            c["temperature"] = float(cpu)
        if gpu is not None:
            g["temperature"] = float(gpu)
        return {"cpu": c, "gpu": g, "memory": {"used_percent": 41.0},
                "fans": [{"name": "Fan CPU", "value": 1016, "type": "Fan"}], "timestamp": {}}

    def test_each_row_paints_only_in_the_free_zone_and_with_the_themes_bytes(self):
        for cpu, gpu in ARC_PAIRS:
            body = self.metrics(cpu, gpu)
            flat_on = list(render.draw(body, "alpha").get_flattened_data())
            theirs = {k for k in self.zone if flat_on[k][3]}
            for prop, strings, y, ceiling in (
                    (temp_prop(), (render.cpu_temp_text(body), render.gpu_temp_text(body)),
                     render.A26_TVAL_Y, render.A26_TVAL_F),
                    (temp_prop("temp-labels", render.A26_TLBL_Y, render.A26_TLBL_F),
                     render.A26_TLBL_TEXT, render.A26_TLBL_Y, render.A26_TLBL_F)):
                with self.subTest(row=prop["name"], cpu=cpu, gpu=gpu):
                    img, notes = rows_frame([dict(prop)], body)
                    flat = list(img.get_flattened_data())
                    painted = ink_of(flat)
                    self.assertGreater(painted, set(), f"{prop['name']} painted nothing")
                    self.assertLessEqual(painted - self.zone, set(),
                                         f"{prop['name']} put ink where the ring's own drawing "
                                         "puts ink")
                    for key in painted:
                        self.assertEqual(flat_on[key], flat[key],
                                         f"{prop['name']}: same place, different byte")
                    self.assertEqual(notes["missing"], [])
                    self.assertEqual(notes["gaps"], [])
                    dev = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS),
                                    (0, 0, 0, 0))
                    size, _box = layout.draw_special_values(ImageDraw.Draw(dev), prop, strings)
                    self.assertEqual(size, arc_fit(strings, ceiling, render.A26_TCOL_X[0], y))
                    self.assertEqual(size, arc_fit(strings, ceiling, render.A26_TCOL_X[1], y))
                    self.assertEqual(size, min(arc_fit((s,), ceiling, render.A26_TCOL_X[0], y)
                                               for s in strings))
                    box = row_box(notes)
                    ink = (min(k % render.W for k in painted), min(k // render.W for k in painted),
                           max(k % render.W for k in painted),
                           max(k // render.W for k in painted))
                    for a, b in zip(box, ink):
                        self.assertLessEqual(abs(a - b), 4, f"{prop['name']}: {box} vs {ink}")

    def test_the_two_rows_together_own_the_zone_they_are_each_allowed(self):
        for cpu, gpu in ARC_PAIRS[:9]:
            body = self.metrics(cpu, gpu)
            both, _notes = rows_frame([temp_prop("temp-labels", render.A26_TLBL_Y,
                                                 render.A26_TLBL_F), dict(temp_prop())], body)
            painted = ink_of(list(both.get_flattened_data()))
            flat_on = list(render.draw(body, "alpha").get_flattened_data())
            theirs = {k for k in self.zone if flat_on[k][3]}
            with self.subTest(cpu=cpu, gpu=gpu):
                self.assertLessEqual(painted - self.zone, set())
                self.assertLessEqual(theirs - painted, set(),
                                     f"the theme paints {len(theirs - painted)} px of the free "
                                     "zone that neither row takes")


class TheDoorMarkers(unittest.TestCase):
    """Each registered drawing says which door its fields go through, and the marker has to
    agree with the call inside the body.

    `themes.SPECIALS` marks every registered function with a `.door` - `line`, `pair` or
    `values` - and `--list-specials` prints that word.  The marker and the `layout.draw_special_*`
    call in the body are two places the same fact is written down, so they can come apart without
    anything breaking: the row would still draw, and the listing would lie about what its fields
    mean.  Read out of each function's own source with `inspect`, never from a table kept here.
    """

    DOOR_CALLS = {"line": "layout.draw_special_line(", "pair": "layout.draw_special_pair(",
                  "values": "layout.draw_special_values("}

    def test_every_registered_drawing_carries_a_marker(self):
        for name, fn in sorted(themes.SPECIALS.items()):
            with self.subTest(special=name):
                self.assertIn(getattr(fn, "door", None), self.DOOR_CALLS,
                              f"{name}: `door` is {getattr(fn, 'door', None)!r}, not one of "
                              f"{sorted(self.DOOR_CALLS)}")

    def test_the_marker_is_the_call_the_body_actually_makes(self):
        for name, fn in sorted(themes.SPECIALS.items()):
            with self.subTest(special=name):
                source = inspect.getsource(fn)
                called = sorted(door for door, call in self.DOOR_CALLS.items() if call in source)
                self.assertEqual(len(called), 1,
                                 f"{name}'s body calls {called}: exactly one door, or the "
                                 f"marker cannot mean anything")
                self.assertEqual(fn.door, called[0],
                                 f"{name} is marked {fn.door!r} and its body calls "
                                 f"{self.DOOR_CALLS[called[0]]!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
