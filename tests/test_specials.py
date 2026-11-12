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

import ast
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

    def keys_a_drawing_reads(self, fn) -> set:
        """Which keys of the value table one registered drawing reads, out of its own source.

        `ast`, not a list kept here: the same door `themes.keys_read()` uses to ask `layout.py`
        what it reads, applied to a smaller module.  A docstring's word "values" is a constant
        node and cannot be mistaken for a lookup.
        """
        found = set()
        for node in ast.walk(ast.parse(inspect.getsource(fn))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "values" \
                    and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.add(str(node.args[0].value))
            elif isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                    and node.value.id == "values" \
                    and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, str):
                found.add(str(node.slice.value))
        return found

    def test_every_drawing_that_reads_the_table_is_filled_for(self):
        """The two places that fact is written - the drawings and `SPECIAL_LINES` - are one list.

        `fill_lines` puts into a value table exactly the keys `SPECIAL_LINES` lists, and a
        registered `special` reads the keys it needs out of that table by name.  The way that
        goes wrong is the way this repository found it on 2026-11-12: a drawing reads
        `temp-cpu`, the table beside the registry does not list it, the drawing finds nothing to
        say, returns no box, and the row simply is not on the glass - no validation error, no
        skipped note, nothing.  Six names (`readings`, `status`, `fan-cpu`, `fan-gpu`,
        `temp-cpu`, `temp-gpu`) exist nowhere but in that table, so no file can be written that
        asks for them and no `source` lookup can answer for them.

        Asserted both ways on purpose.  A drawing that reads a key nobody fills loses its row,
        which is the fault above; a name listed but reading nothing is a key painted into every
        frame's table for no reader at all, and it is the same drift going the other way.
        """
        reads = {name: self.keys_a_drawing_reads(fn)
                 for name, fn in sorted(themes.SPECIALS.items())}
        self.assertTrue({n for n, k in reads.items() if k},
                        "no registered drawing reads the value table at all, so the listing "
                        "below is a comparison of two empty sets")
        self.assertEqual({name for name, keys in reads.items() if keys},
                         set(themes.SPECIAL_LINES),
                         f"the registry's bodies read {sorted(reads)} and `SPECIAL_LINES` lists "
                         f"{sorted(themes.SPECIAL_LINES)}: a name in one and not the other is a "
                         f"row that draws nothing, filled for nobody")
        for name, keys in sorted(reads.items()):
            with self.subTest(special=name):
                listed = {key for key, _build in themes.SPECIAL_LINES.get(name, ())}
                self.assertEqual(keys, listed,
                                 f"{name} reads {sorted(keys)} from the table and "
                                 f"`SPECIAL_LINES` fills {sorted(listed)} for it")

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


class ALoopAndAPanePaintOnePicture(fixtures.FreshConfigRoot):
    """A layout saved from the editor paints the **same pixels** through the loop's door.

    The editor's pane draws with `themes.draw`; the frame loop draws the very same file with
    `themes.paint`, which resolves a name to a record and hands the file to the painter.  Those
    two doors were written in different orders, and until 2026-11-12 only one of them filled the
    six keys that the four drawings listed in `SPECIAL_LINES` read - `readings`, `status`,
    `fan-cpu`, `fan-gpu`, `temp-cpu`, `temp-gpu`.  Those keys are not `source` names any file
    spells, so nothing validated, nothing was reported as skipped, and each affected row simply
    came back with **no box**: a row the pane showed in full reached the glass as nothing at all.
    The reported case was a saved `alpha`, which lost its two temperature figures and its fan
    pair while keeping the `CPU TEMP`/`GPU TEMP` labels between them - `temp-labels` takes its
    words from `render.A26_TLBL_TEXT` rather than from a reading.  The same door was dropping
    `clock`'s readings line and `dual`'s status line, and nobody had noticed those two because
    the only report of the class of fault came from `alpha`.

    So this class holds a **parity** claim, which is what makes it cheap enough to hold for whole
    layouts with no reference image: one file, one body, two doors, **zero differing pixels**, and
    the same reported box for every `special` row.  It holds it for all five generated layouts,
    saved as files - the three that declare rows reading those keys (`alpha`, `clock`, `dual`)
    and the two that declare no `special` at all (`bars`, `gauge`), because a shared door is not
    supposed to agree only when the layout is interesting.  A blank frame passing for a blank
    frame is excluded twice over - every reported row must carry a box, and every box must hold
    ink on both frames.

    The last check below is the one that proves the first is not vacuous: the same file, the same
    body, the same painter, one value table with the six keys and one without.  It prints the
    whole-frame loss for each of the three layouts that can lose anything, and nothing in this
    file quotes those figures as rules, because they follow the faces installed.

    Nothing here is vendor's: the vendor's 27 layouts use no `special` row at all, which is
    exactly why a decade of pixel-for-pixel vendor comparisons never saw the asymmetry.  The
    layouts are generated, saved into a settings root this test owns, and resolved by name, so
    they arrive at the loop's door the way the owner's `alpha_new` did.
    """

    #: A body with something to say in all six composite keys, pinned in this file rather than
    #: read from this machine, so the two frames being compared are the same two frames on CI's
    #: runner as here.  The fan pair needs `fans` and a GPU `tachometer`: PROTOCOL.md §9 says
    #: the panel reports its own tachs and `docs/limits.md` keeps what that means for a figure.
    BODY = {
        "cpu": {"temperature": 61.0, "load": 62.0, "frequency": 3400, "power": 18.0},
        "gpu": {"temperature": 36.0, "fan": 35.0, "load": 22.0, "memory": 2048,
                "power": 90.0, "frequency": 1200, "memoryRate": 30.0,
                "tachometer": [{"name": "GPU FAN", "value": 1080}]},
        "memory": {"total": 16384, "used": 8192},
        "fans": [{"name": "Fan CPU", "value": 1180}, {"name": "Fan System 5", "value": 890}],
        "gpuMemoryUsed": 2458,
    }
    WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)

    def saved(self, name: str, export: str = "alpha") -> dict:
        """One generated layout, saved as a user layout and resolved back by name."""
        path, _soft = themes.save(themes.export(export), name)
        rec = themes.resolve(name)
        self.assertIsNotNone(rec, f"{path} was written and cannot be resolved")
        self.assertEqual(rec["path"], path, "the loop found a different file than the save wrote")
        return rec

    def specials_in(self, notes: dict) -> dict:
        """The `special` rows one door drew, by name, with the box each was reported at."""
        return {what: box for kind, what, box, _i in (notes.get("boxes") or [])
                if kind == "special"}

    def ink(self, img, box) -> int:
        """Inked pixels inside one reported box, counted from alpha, not colour."""
        if not box:
            return 0
        x0, y0, x1, y1 = (max(0, int(v)) for v in box)
        alpha = img.convert("RGBA").getchannel("A").load()
        return sum(1 for y in range(y0, min(img.height, y1))
                   for x in range(x0, min(img.width, x1)) if alpha[x, y] > 8)

    def test_every_generated_layout_painted_from_a_file_gives_one_picture(self):
        """Each of the five generated layouts, **saved**, paints the same through both doors.

        Held over all five rather than over the one that was reported, because the fault was not
        about `alpha`: what mattered was whether a layout's rows read the composite keys, and
        three of the five declare such rows - `alpha` has three (`fan-figures`, `temp-values`,
        `temp-labels`), `clock` one (`clock-readings`) and `dual` one (`dual-status`).  The two
        that declare no `special` row at all (`bars`, `gauge`) are compared too: a door shared
        between two painters should not need the layout to be interesting in order to agree.
        """
        for export in sorted(themes.EXPORTS):
            with self.subTest(layout=export):
                rec = self.saved(f"copy_{export}", export)
                glass, glass_notes = themes.paint(rec, dict(self.BODY), self.WHEN)
                pane, pane_notes = themes.draw(themes.load(rec["path"]), dict(self.BODY), self.WHEN)
                rows = self.specials_in(pane_notes)
                self.assertEqual(self.specials_in(glass_notes), rows,
                                 f"{export}: the two doors reported a different set of `special` "
                                 f"rows, or the same rows at different boxes, from one file and "
                                 f"one body")
                differing, worst = self.difference(glass, pane)
                self.assertEqual(differing, 0,
                                 f"{export}: the frame the loop paints and the frame the editor "
                                 f"paints differ by {differing} px (worst channel {worst}) - the "
                                 f"pane is not showing what the glass gets")
                for name, box in sorted(rows.items()):
                    with self.subTest(layout=export, row=name):
                        self.assertIsNotNone(box, f"{export}/{name} reported no box: a row that "
                                                  f"comes back box-less is how this defect reached "
                                                  f"the glass")
                        on_glass = self.ink(glass, box)
                        self.assertGreater(on_glass, 0,
                                           f"{export}/{name} painted no ink through the loop's door")
                        self.assertEqual(on_glass, self.ink(pane, box),
                                         f"{export}/{name} holds {on_glass} inked px on the glass "
                                         f"and {self.ink(pane, box)} in the pane")
                # how much each row is worth, printed rather than asserted: the count follows the
                # faces installed on the machine that runs it, so a figure for it belongs here and
                # not in a page
                print(f"  {export:6s} {differing} px differ between the doors; "
                      + (", ".join(f"{name} {self.ink(glass, box)} px"
                                   for name, box in sorted(rows.items())) or "no special row"))

    def difference(self, one, two) -> tuple:
        """Differing pixels and the worst channel, the way every other census here counts them."""
        flat = ImageChops.difference(one.convert("RGBA"), two.convert("RGBA")).get_flattened_data()
        off = [px for px in flat if px != (0, 0, 0, 0)]
        return len(off), max((max(px) for px in off), default=0)

    def test_each_door_paints_at_the_size_it_declares(self):
        """`canvas` is an argument of the shared door, not a number it could read twice.

        `paint` takes the size the **record** carries, `draw` the size the **object** declares.
        Collapsing them to one source - `render.W`/`render.H`, or the file's own `width` -
        would be invisible while every selectable layout is 1:1 at 480x480, which is all the
        library holds today: `themes.scan()` refuses the four 320x240 pages, and the reason
        written above that refusal is that a 320x240 layout drawn at 480 multiplies an
        unmeasured convention by 1.5.  So the distinction is held here with a layout that
        declares 320x240 in one door and a record that carries 320x240 in the other, each
        built by hand, because that is the shape a future 4:3 page would arrive as.
        """
        rec = self.saved("alpha_canvas", "alpha")
        small = themes.load(rec["path"])
        small["width"], small["height"] = 320, 240
        at_object = themes.draw(small, dict(self.BODY), self.WHEN)[0]
        self.assertEqual(at_object.size, (320, 240),
                         "the pane's door painted an object that declares 320x240 at "
                         f"{at_object.size}: it is reading somebody else's size")
        at_record = themes.paint({**rec, "w": 320, "h": 240}, dict(self.BODY), self.WHEN)[0]
        self.assertEqual(at_record.size, (320, 240),
                         "the loop's door painted a record that says 320x240 at "
                         f"{at_record.size}: the canvas the panel is told to expect is not "
                         f"the one it got")

    def test_a_door_that_stops_filling_says_which_rows_it_lost(self):
        """The same fault, one layer down, has to leave a sentence behind - not a blank frame.

        A `special` row that comes back with no box is recorded by `layout.draw_theme` as a row
        with nothing to say, and that is the right reading of a machine missing a sensor: a box
        with no tachometer still draws `CPU FAN -- RPM`, because `fill_lines` builds the figure
        out of what is there.  It is the **wrong** reading of a value table that never carried
        the key at all - that is this module failing, not the machine - and it is how the owner's
        `temp-values` row left the glass without one line of warning.  So the door now names the
        rows it lost and the keys they read, and this check reads the words rather than trusting
        them to be printed.

        `themes.fill_lines` is replaced for the duration of the check, which is the only way to
        put a shipped door into the state the fix removed.  What the check asks is that the
        layout still draws - the other rows are still there, so a "missing" line cannot be an
        artefact of a blank canvas - and that the note says both row names, all six keys, and
        what to do about it.
        """
        rec = self.saved("alpha_words", "alpha")
        real = themes.fill_lines
        themes.fill_lines = lambda vals, metrics: vals
        try:
            img, notes = themes.paint(rec, dict(self.BODY), self.WHEN)
        finally:
            themes.fill_lines = real
        rows = self.specials_in(notes)
        lost = sorted(name for name, box in rows.items() if box is None)
        self.assertEqual(lost, ["fan-figures", "temp-values"],
                         f"a door that does not fill its table lost {lost}, and the notes are "
                         f"the only place that could say so")
        self.assertGreater(self.ink(img, rows["temp-labels"]), 0,
                           "the rows that read no composite key stopped drawing too, so the "
                           "note below is describing an empty frame rather than a partial one")
        said = sorted(str(n) for n in (notes.get("missing") or []))
        self.assertEqual(said, ["special:fan-figures", "special:temp-values"],
                         f"the notes say {said}: a row that vanished from the glass has to be "
                         f"named there, in the words the loop's report and `--check-theme` "
                         f"print, and nothing else may be named with it - this body reads every "
                         f"source the layout asks for, so an extra entry would be the notes "
                         f"crying wolf")
        reasons = {str(k): str(v) for k, v in (notes.get("absent") or {}).items()}
        for name, keys in (("fan-figures", ("fan-cpu", "fan-gpu")),
                           ("temp-values", ("temp-cpu", "temp-gpu"))):
            with self.subTest(row=name):
                why = reasons.get(f"special:{name}", "")
                self.assertTrue(why, f"{name} is listed as missing with no reason beside it")
                for key in keys:
                    self.assertIn(key, why, f"the reason for {name} does not name {key!r}: "
                                            f"{why!r}")
                self.assertIn("draws nothing", why,
                              f"the reason for {name} does not say what becomes of the row: "
                              f"{why!r}")

    def test_taking_the_fill_out_changes_the_picture(self):
        """The guard that the parity above is not vacuous: same file, no `fill_lines`, rows lost.

        One value table with the composite keys and one without, both handed to the same painter
        at the same instant.  If those two frames agreed, the check above would be comparing two
        empty canvases and the asymmetry could come back with nothing failing - which is exactly
        how it arrived: every door that *did* fill the table agreed with itself, and the vendor's
        27 files use no `special` row, so no vendor comparison ever noticed.  The unfilled table
        is what the loop's door used to build; the rows it lost are reported with **no box at
        all**, which is the shape of the owner's complaint - and the loss is measured here for
        every generated layout that declares such a row, not only the reported one.
        """
        total = 0
        for export in sorted(themes.EXPORTS):
            obj = themes.load(self.saved(f"bare_{export}", export)["path"])
            plain, _absent = themes.values(dict(self.BODY), self.WHEN)
            filled, _absent = themes.values(dict(self.BODY), self.WHEN)
            themes.fill_lines(filled, dict(self.BODY))
            bare, bare_notes = layout.draw_theme(obj, plain, canvas=(render.W, render.H),
                                                 specials=themes.SPECIALS)
            whole, whole_notes = layout.draw_theme(obj, filled, canvas=(render.W, render.H),
                                                   specials=themes.SPECIALS)
            unpainted, without = self.specials_in(bare_notes), self.specials_in(whole_notes)
            if not (set(without) & set(themes.SPECIAL_LINES)):
                print(f"  {export:6s} declares no `special` row that reads the value table, so "
                      f"there is nothing here for it to lose")
                continue
            self.assertEqual(without.keys(), unpainted.keys(),
                             f"{export}: a row is missing from the unfilled frame's report rather "
                             f"than drawn with no box, so the symptom this check is built around "
                             f"changed shape")
            changed, same, lost_boxes = [], [], []
            for name, box in sorted(without.items()):
                if name not in themes.SPECIAL_LINES:
                    continue                      # reads no composite key: nothing to take out
                before = self.ink(bare, unpainted[name])
                after = self.ink(whole, box)
                (changed if before != after else same).append(name)
                if unpainted[name] is None:
                    lost_boxes.append(name)
                with self.subTest(layout=export, row=name):
                    self.assertNotEqual(before, after,
                                        f"{export}/{name} paints {after} px with the composite keys "
                                        f"and {before} without them: it does not read the table at "
                                        f"all, and the parity check above is not about it")
            self.assertTrue(changed,
                            f"{export}: no row in {sorted(themes.SPECIAL_LINES)} changed between a "
                            f"value table filled by `fill_lines` and one that is not, so the parity "
                            f"check above could not tell the two doors apart")
            self.assertTrue(lost_boxes,
                            f"{export}: the unfilled table still gave every `SPECIAL_LINES` row a "
                            f"box, so the loop's old door would not have lost a row from the glass "
                            f"and the report of this defect is wrong")
            lit = (sum(1 for v in whole.getchannel("A").get_flattened_data() if v)
                   - sum(1 for v in bare.getchannel("A").get_flattened_data() if v))
            total += lit
            print(f"  {export:6s} an unfilled table paints {lit} px less, and reports no box for "
                  f"{', '.join(sorted(lost_boxes)) or 'nothing'}")
        self.assertGreater(total, 0, "no generated layout loses a pixel when the composites are "
                                     "taken out, so none of the parity claims above can fail")

if __name__ == "__main__":
    unittest.main(verbosity=2)
