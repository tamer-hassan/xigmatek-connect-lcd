#!/usr/bin/env python3
"""The substitutions a layout file is allowed to name, held to the pixels they claim.

Ported from the convention and `--bg black` blocks of `tools/selftest.sh`'s vendor-theme section.

Two things are pinned here, and both are about drift rather than behaviour:

**A convention that names a function is worth nothing but a zero diff against that function.**
`barPaint: hbar` means `render.hbar`, so the only passing answer is pixel-identical to calling it -
at both usage-bar anchors, at seven values including negative and past-max, with and without a
declared corner radius, at the supersampled canvas *and* at 1x as the panel and the preview see it.
`barPaint: render` means `render.bar`, whose own two floors (`frac > 0.01` for any fill, corners off
`max(frac, 0.02)`) are exactly where a remembered table used one number for both and drew no fill at
all between 1 % and 2 % load.  The probe takes its geometry and its inks from `render.py`'s
constants, because that is how the last remembered figure in this repository went stale.

**`--bg black` has two different answers in the two doors**, and which themes leak is derived from
the exports' own colour keys rather than remembered.  A layout's plate goes *under* the finished
layer, so that frame is opaque everywhere.  A `theme_*` body opens its image with the canvas already
in it, and PIL's `ImageDraw` replaces a pixel for a translucent fill instead of blending it, so a
drawn theme with a translucent colour key keeps leaking.  That is not a bug: it is what keeps a
`--bg black` frame's palette small and the vendor's frames transparent.
"""
from __future__ import annotations

import datetime
import json
import unittest
from PIL import Image, ImageDraw, ImageChops

from tests import fixtures

from xigmalcd import layout
from xigmalcd import render
from xigmalcd import themes

CASES = fixtures.PARITY_CASES
WHEN = fixtures.SESSION_WHEN

#: One bar, declared in the vendor's vocabulary, at the geometry `theme_bars` uses for its meters.
BARPROP = {"x": 60, "y": 340, "width": 360, "height": 14, "cornerRadius": 5,
           "bgColor": "rgba(40, 46, 50, 1)", "startColor": "rgba(0, 247, 255, 1)",
           "endColor": "rgba(0, 247, 255, 1)", "minValue": 0, "maxValue": 100,
           "source": "CPU Usage"}

#: Where `render.bar`'s own two floors make a difference.  1.01 and 1.5 and 2.5 are the point of
#: this list: a load between 1 % and 2 % drew no fill at all once, in a remembered table.
LOADS = (0, 0.5, 1.0, 1.01, 1.5, 2.0, 2.5, 3, 12.5, 63.5, 99.9, 100, 137, -5)


def differ(a: Image.Image, b: Image.Image) -> tuple:
    flat = ImageChops.difference(a.convert("RGBA"), b.convert("RGBA")).get_flattened_data()
    return (sum(1 for q in flat if q != (0, 0, 0, 0)), max((max(q) for q in flat), default=0))


def css(colour) -> str:
    return f"rgba({colour[0]}, {colour[1]}, {colour[2]}, {colour[3] / 255:.6g})"


class ArcPaint(unittest.TestCase):
    """Why `xigma.arcPaint` exists at all: one arc, painted both conventions, measured."""

    @classmethod
    def setUpClass(cls):
        cls.arc = themes.export("gauge")["osd"]["widget"][0]["property"][0]

    def ring(self, declared: bool, value: float) -> Image.Image:
        img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
        prop = json.loads(json.dumps(self.arc))
        if not declared:
            prop.pop("xigma", None)
        layout.draw_arc(ImageDraw.Draw(img), prop, value)
        return img.resize((render.W, render.H), Image.LANCZOS)

    def test_the_declared_convention_is_not_the_default_at_any_reading(self):
        for value in (31.0, 52.0, 57.4, 88.9):
            with self.subTest(value=value):
                pixels, worst = differ(self.ring(True, value), self.ring(False, value))
                self.assertGreater(pixels, 0, "the two conventions drew one picture")
                self.assertGreater(worst, 0)


class BarPaint(unittest.TestCase):
    """Three answers for a bar, and the one that names a function is held to that function."""

    def file_bar(self, which, value, paint, corner) -> Image.Image:
        prop = {"x": render.A26_BAR_XY[which][0], "y": render.A26_BAR_XY[which][1],
                "width": render.A26_BAR_WH[0], "height": render.A26_BAR_WH[1],
                "cornerRadius": corner, "minValue": 0, "maxValue": 100,
                "source": "CPU Usage", "bgColor": css(render.A26_TRACK),
                "startColor": css(render.A26_BAR_A), "endColor": css(render.A26_BAR_B),
                "xigma": {"barPaint": paint}}
        img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
        _box, bad = layout.draw_bar(ImageDraw.Draw(img), prop, value)
        self.assertFalse(bad, (paint, bad))
        return img

    def code_bar(self, which, value) -> Image.Image:
        img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
        render.hbar(img, *render.A26_BAR_XY[which], *render.A26_BAR_WH,
                    min(max(value / 100.0, 0.0), 1.0))
        return img

    def test_hbar_means_render_hbar_at_every_probe_both_ways(self):
        """Device pixels first - the convention's own resolution - and then 1x, as the panel and
        the preview actually see it.  `hbar` takes no radius, so a declared corner must not leak."""
        for which in (0, 1):
            for value in (0, 3, 22, 62, 100, 137, -5):
                for corner in (0, 5):
                    with self.subTest(bar=which, value=value, corner=corner):
                        self.assertEqual(differ(self.code_bar(which, value),
                                                self.file_bar(which, value, "hbar", corner))[0], 0)
        for value in (0, 3, 22, 62, 100, 137, -5):
            with self.subTest(scale="1x", value=value):
                code = self.code_bar(0, value).resize((render.W, render.H), Image.LANCZOS)
                mine = self.file_bar(0, value, "hbar", 5).resize((render.W, render.H),
                                                                 Image.LANCZOS)
                self.assertEqual(differ(code, mine)[0], 0)

    def test_the_other_two_conventions_are_measurably_different_drawings(self):
        for value in (0.0, 3.0, 63.5, 100.0):
            with self.subTest(value=value):
                plain = {"x": BARPROP["x"], "y": BARPROP["y"], "width": BARPROP["width"],
                         "height": BARPROP["height"], "cornerRadius": BARPROP["cornerRadius"],
                         "bgColor": BARPROP["bgColor"], "startColor": BARPROP["startColor"],
                         "endColor": BARPROP["endColor"], "minValue": 0, "maxValue": 100,
                         "source": "CPU Usage"}
                img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
                layout.draw_bar(ImageDraw.Draw(img), plain, value)
                img2 = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS),
                                 (0, 0, 0, 0))
                layout.draw_bar(ImageDraw.Draw(img2), {**plain, "xigma": {"barPaint": "render"}},
                                value)
                self.assertGreater(differ(img, img2)[0], 0,
                                   "the vendor's bar and `render.bar` are the same picture, so "
                                   "the convention stopped meaning anything")

    def test_render_bar_means_render_bar_across_its_own_two_floors(self):
        def code(value):
            img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
            render.bar(img, 60, 340, 360, 14, value / 100.0, render.heat(value / 100.0))
            return img

        def mine(value):
            prop = json.loads(json.dumps(BARPROP))
            prop["xigma"] = {"barPaint": "render", "colourRamp": "heat"}
            img = Image.new("RGBA", (render.W * layout.SS, render.H * layout.SS), (0, 0, 0, 0))
            _box, bad = layout.draw_bar(ImageDraw.Draw(img), prop, value)
            self.assertFalse(bad)
            return img

        for value in LOADS:
            with self.subTest(load=value):
                self.assertEqual(differ(code(value), mine(value))[0], 0,
                                 f"a load of {value} %: `render.bar` draws when frac > 0.01 and "
                                 "rounds its corners off max(frac, 0.02), and the file door has "
                                 "to do both at once")

    def test_the_fill_is_walked_rather_than_hidden_under_the_track(self):
        """The pixels of the declared rect that still read the track's own colour, counted the same
        way in both drawings, falling as the reading rises."""
        def track_px(img):
            x, y = render.A26_BAR_XY[0]
            w, h = render.A26_BAR_WH
            box = img.crop((x, y, x + w, y + h)).get_flattened_data()
            return sum(1 for q in box if q[:3] == render.A26_TRACK[:3])

        walked = []
        for value in (0, 30, 62, 100):
            code = self.code_bar(0, value).resize((render.W, render.H), Image.LANCZOS)
            mine = self.file_bar(0, value, "hbar", 0).resize((render.W, render.H), Image.LANCZOS)
            walked.append((value, track_px(mine), track_px(code)))
            with self.subTest(value=value):
                self.assertEqual(walked[-1][1], walked[-1][2],
                                 "the two drawings leave different amounts of track showing")
        counts = [a for _v, a, _b in walked]
        self.assertGreater(counts[0], counts[1])
        self.assertGreater(counts[1], counts[2])
        self.assertEqual(counts[3], 0, "a full meter still shows track")


class KeysAndTables(unittest.TestCase):
    """The enumerated tables and the reasons `--print-theme-fields` prints cannot drift."""

    def test_every_name_in_a_table_is_named_in_that_keys_stated_reason(self):
        for key, table in (("arcPaint", layout.ARC_PAINT), ("barPaint", layout.BAR_PAINT),
                           ("colourRamp", layout.COLOUR_RAMPS)):
            with self.subTest(key=key):
                unexplained = [name for name in table if name not in themes.XIGMA_KEYS[key]]
                self.assertEqual(unexplained, [],
                                 f"{key}: {unexplained} are drawn but the printed reason does "
                                 "not name them")

    def test_a_name_that_is_not_in_a_table_is_reported_rather_than_drawn_by_guesswork(self):
        bad_bar = {"width": render.W, "height": render.H,
                   "osd": {"widget": [{"id": "xigma-bad", "type": "bar",
                                       "property": [{**BARPROP,
                                                     "xigma": {"barPaint": "hand-painted"}}]}]}}
        hard, soft = themes.validate(bad_bar)
        self.assertEqual(hard, [])
        self.assertTrue(any("barPaint" in s and "hand-painted" in s for s in soft), soft)
        self.assertTrue(all(all(name in s for name in layout.BAR_PAINT)
                            for s in soft if "barPaint" in s),
                        "the finding does not list what is available")

        bad_arc = json.loads(json.dumps(themes.export("gauge")))
        bad_arc["osd"]["widget"][0]["property"][0]["xigma"]["arcPaint"] = "guessed"
        hard, soft = themes.validate(bad_arc)
        self.assertEqual(hard, [])
        self.assertTrue(any("arcPaint" in s and "guessed" in s for s in soft), soft)


class CanvasPlate(unittest.TestCase):
    """`--bg black`, both doors: a plate under a layer, a canvas under a drawing."""

    def translucent_keys(self, obj: dict) -> dict:
        """Every colour key in one export whose alpha is below 1, by row kind."""
        out: dict = {}
        for widget in obj["osd"]["widget"]:
            for key, value in widget["property"][0].items():
                if "color" not in key.lower() or "(" not in str(value):
                    continue
                try:
                    alpha = float(str(value).rsplit(",", 1)[-1].strip(" )"))
                except ValueError:
                    continue
                if alpha < 1:
                    out.setdefault(key, []).append(widget["type"])
        return out

    def leak(self, img: Image.Image) -> tuple:
        hist = img.getchannel("A").histogram()
        below = sum(hist[:255])
        return (below, min((v for v in range(256) if hist[v]), default=255))

    def usable_case(self, name: str) -> int:
        """The first reading where this theme's two doors agree at all - a case that leaves a
        source out would make a canvas figure for that theme noise."""
        for index, body in enumerate(CASES):
            if not themes.parity(name, body, WHEN)["missing"]:
                return index
        return -1

    def test_the_file_door_is_opaque_everywhere_and_the_code_door_leaks_by_declaration(self):
        declared = {name: self.translucent_keys(themes.export(name))
                    for name in sorted(themes.EXPORTS)}
        leaky = sorted(n for n, keys in declared.items() if keys)
        real_now = render._now
        render._now = lambda: WHEN.timetuple()      # one instant on both sides
        try:
            for name in sorted(themes.EXPORTS):
                index = self.usable_case(name)
                if index < 0:
                    continue
                body = CASES[index]
                with self.subTest(theme=name):
                    layer, _notes = themes.draw(themes.export(name), body, WHEN)
                    plate = Image.alpha_composite(Image.new("RGBA", layer.size, render.BLACK),
                                                  layer)
                    self.assertEqual(plate.getextrema()[3], (255, 255),
                                     "a plate left the frame partly clear")
                    self.assertEqual(self.leak(plate)[0], 0)

                    code_layer = render.draw(body, name)
                    code_solid = render.draw(body, name, bg=render.BLACK)
                    leaked, lowest = self.leak(code_solid)
                    if name in leaky:
                        self.assertGreater(leaked, 0,
                                           f"{name}'s own file declares {sorted(declared[name])} "
                                           "and the frame went opaque: the replace-not-blend "
                                           "rule broke")
                        self.assertLess(lowest, 255)
                    else:
                        self.assertEqual(leaked, 0,
                                         f"{name} has no translucent colour key and still leaks "
                                         "on `--bg black`: the split between the doors is no "
                                         "longer about the file")
                    # and the two doors' opaque frames part only by the plate's order
                    plate_over_code = Image.alpha_composite(
                        Image.new("RGBA", code_layer.size, render.BLACK), code_layer)
                    self.assertEqual(differ(code_solid, plate)[0],
                                     differ(code_solid, plate_over_code)[0],
                                     "the two doors disagree *underneath* the plate, so this "
                                     "claim and the parity gate are about different pictures")
                    # at the default transparent canvas they are one picture: that is what every
                    # parity claim means
                    self.assertEqual(differ(code_layer, layer)[0], 0)
        finally:
            render._now = real_now
        self.assertGreater(leaky, [], "no drawn theme declares a translucent colour any more, "
                                      "so the split this class exists for has gone away")


if __name__ == "__main__":
    unittest.main(verbosity=2)
