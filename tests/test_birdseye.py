#!/usr/bin/env python3
"""`birdseye`: six dials, five bars, and a background that was cut rather than edited.

The sixth theme drawn from code, added 2026-11-14 at the owner's request: a TEMPERATURES
row and a COOLING row of three dials each, then a USAGE column of five bars with a figure
beside every label.  It is also the first theme of ours whose **background clip is an
asset this repository made**: the owner asked for `theme_47.mp4` without the still frames
that open it - a play button burned into the middle of the first 17 frames - and the rule
this project keeps about vendor files is that they are evidence, hashed in the library's
own manifest and verified byte for byte, so the cut lives in a **copy** and the vendor's
file is left exactly as it arrived.

Ten rules, all of them measured out of the shipped painter, the shipped file, or ffprobe:

* the two doors put down the same pixels at every reading, and the box each dial reports is
  the same box in both;
* every dial's number and name sit **inside** that dial's ring, and no dial's parts land on
  a neighbour's ring - which is the geometry question a three-across row of 104 px boxes
  has to answer at 480 px wide;
* a reading this machine does not report takes its ring, its number and (for a slot) its
  name out, and says so - while a row whose *subject* exists (CPU, GPU, BOARD) keeps its
  label, the same split `bars` was built on;
* the DISK bar reads the vendor's `disk.activity` field, and the check says which sibling
  field it deliberately did **not** choose and why (iowait sits at 0.0 on a machine with
  fast NVMe, and a dead bar is a lie of omission);
* the usage column's gutters are measured as ink in both doors - the figure inside its
  declared box, the label starting clear of that box, the number clear of a meter that is
  drawn full - and the rows do not stand on each other, with the column's slack under the
  caption and above the canvas edge printed for whoever wants a sixth bar (five is the
  measured ceiling at this pitch: 135 px of room, a 30 px pitch, 10 px of box);
* each section's hairline measures as a hairline: in a window grown 6 px around the rule
  the theme declares, nothing else lights up, because a rule that lands on the dials it
  heads has stopped labelling them;
* no row of this export carries `xigma.showIf` - every number here asks the same source
  as its own meter, so a hole is told once by that source and not twice - and the report's
  shape is measured per hole: exactly the `arc`/`bar`/`data` rows that ask it say so (a
  dial is two of those, a usage row is two) while a `special` figure row stays silent on
  purpose, and draws nothing either;
* the paired clip is ours: 168 frames, 8.40 s, and its head measures the absence of the
  play button the original's head has - the original's first 17 frames read a centre luma
  of 6.6 where the cut copy reads 1.5 at the same position;
* the vendor's file is untouched: its sha256 still matches the entry in the library's own
  `manifest.json`, which is what makes "we copied and cut, we did not edit" checkable
  rather than promised;
* the cut is frame-exact and the loop seam is not worse than the file it came from (the
  mean absolute difference of first against last frame: 5.533 trimmed against 5.859);
* the geometry of this layout is **chosen here**, not measured off the vendor's picture,
  and `themes.GEOMETRY_ORIGIN` says so - the same declaration `tests/test_snapping.py`
  uses to hold this file's numbers to a no-near-collision rule;
* the section structure is counted, not assumed: three captions, three rules, six dials,
  five bars, five figures;
* and the ink this theme lays down is printed for the pages to quote.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import unittest

from tests import fixtures

from xigmalcd import layout, render, themes

WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)
TRIMMED = os.path.join("media", "theme_47-trimmed.mp4")

#: A body that answers everything the panel draws, with this bench's real fan topology:
#: two tachometers, the second of them pinned as a pump.
FULL = {"cpu": {"temperature": 62.0, "load": 26.0},
        "gpu": {"temperature": 44.0, "load": 12.0, "fan": 34.0, "memoryUsage": 15952,
                "dedicatedTotal": 16376},
        "motherboard": {"temperature": 40.0},
        "memory": {"used": 84480, "total": 126155},
        "disk": {"temperature": 40.0, "total": 786, "used": 730, "activity": 22.0,
                 "load": 1.4},
        "drives": [{"name": "nvme0", "temperature": 40}],
        "fans": [{"name": "Fan CPU", "value": 1660, "type": "Fan"},
                 {"name": "CPU PUMP", "value": 2455, "type": "Pump"}],
        "timestamp": {}}

#: The same panel on a machine with one tachometer and no discrete card at all.
SPARSE = {"cpu": {"temperature": 55.0, "load": 40.0},
          "motherboard": {"temperature": 38.0},
          "memory": {"used": 4096, "total": 16384},
          "disk": {"total": 240, "used": 90, "activity": 3.0, "load": 0.4},
          "fans": [{"name": "Fan CPU", "value": 900, "type": "Fan"}],
          "timestamp": {}}


def ffprobe(path: str, entries: list) -> dict:
    """One stream's fields, asked of ffprobe in the order named.

    `csv=p=0` prints **one line** with the requested fields comma-separated, so the naive
    read of "one line per field" comes back as a single string and the caller's unpacking
    fails - which is what it did the first time this helper ran here.
    """
    got = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=" + ",".join(entries),
                          "-of", "default=noprint_wrappers=1:nokey=0", path],
                         capture_output=True, text=True, timeout=120)
    if got.returncode or not got.stdout.strip():
        raise AssertionError(f"ffprobe failed on {path}: {got.stderr[-300:]}")
    # `key=value` one per line, because ffprobe prints stream fields in **its** order, not
    # the order they were asked for: a csv read paired `nb_frames` with the duration and
    # this check reported 480 frames for a 168-frame file.  Asking for the names back is
    # the only form that cannot be re-ordered on us.
    out = {}
    for line in got.stdout.strip().splitlines():
        key, _sep, value = line.partition("=")
        out[key.strip()] = value.strip()
    missing = [e for e in entries if e not in out]
    if missing:
        raise AssertionError(f"ffprobe returned no {missing} for {path}: {got.stdout[:200]}")
    return out


def sha256_of(path: str) -> str:
    """The file's digest, with the handle closed - this suite runs with ResourceWarnings
    raised as errors, and an unclosed `open()` inside a check is a failure of the check."""
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def centre_luma(path: str, at: float) -> float:
    """Mean grey of the middle 120x120 of one frame, decoded at `at` seconds."""
    got = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", path,
                          "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, timeout=120)
    if got.returncode or not got.stdout:
        raise AssertionError(f"could not decode {path} at {at} s: {got.stderr[-300:]}")
    from PIL import Image
    im = Image.open(__import__("io").BytesIO(got.stdout)).convert("L")
    c = im.crop((im.width // 2 - 60, im.height // 2 - 60,
                 im.width // 2 + 60, im.height // 2 + 60))
    hist = c.histogram()
    return sum(v * hist[v] for v in range(256)) / (120 * 120)


def seam(path: str, duration: float) -> float:
    """Mean absolute grey difference between the loop's first frame and its last."""
    from PIL import Image, ImageChops

    def grab(at):
        got = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", path,
                              "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, timeout=120)
        return Image.open(__import__("io").BytesIO(got.stdout)).convert("L")
    a, b = grab(0.0), grab(duration - 0.06)
    diff = ImageChops.difference(a, b).getchannel(0).histogram()
    return sum(v * diff[v] for v in range(256)) / (a.width * a.height)


#: Ink threshold: a pixel counts when it is more than a faint edge.  The same constant
#: `tests/test_icons.py` measures the `bars` gutter with, so the two themes are judged by
#: one rule about what "this column has ink in it" means.
INK = 8


def alpha(img):
    return img.convert("RGBA").getchannel("A").load()


def ink_box(d, xs, ys) -> tuple:
    """The bounding box of lit pixels in a window, device px, or None."""
    pts = [(x, y) for y in ys for x in xs if d[x, y] > INK]
    if not pts:
        return None
    return (min(p[0] for p in pts), min(p[1] for p in pts),
            max(p[0] for p in pts), max(p[1] for p in pts))


class BothDoorsOnePicture(unittest.TestCase):
    """The parity claim, and the geometry claim, for one theme at many readings."""

    @classmethod
    def setUpClass(cls):
        cls.obj = themes.export("birdseye")

    def boxes(self, body):
        """The painter's reported boxes, keyed by (kind, name).

        Keyed by name alone would be wrong and quietly: a dial's `arc` and its `data`
        number carry the **same** source name, so a dict on the name keeps whichever came
        last - the 224 px "ring" this check first measured was a bounding box wearing a
        number's label.
        """
        _img, notes = themes.draw(self.obj, dict(body), WHEN)
        by_index = {i: (kind, what, box) for kind, what, box, i
                    in (notes.get("boxes") or [])}
        # ...and id -> box, because a generated file's widget ids are the one address that
        # cannot collide: `xigma-birdseye-cpu-temperature-value` names exactly one row,
        # while "CPU Temperature" is an arc, a number and a meter at once, and "CPU" is
        # both a dial's name and a usage bar's label
        ids = {str(w.get("id")): by_index[i] for i, w in
               enumerate(self.obj["osd"]["widget"]) if i in by_index}
        return ids, notes

    def test_the_two_doors_agree_at_every_body_this_theme_can_be_given(self):
        for label, body in (("every reading", FULL), ("one fan, no card", SPARSE),
                            ("a CPU-only box", {"cpu": {"temperature": 61.0, "load": 5.0},
                                                "timestamp": {}})):
            with self.subTest(body=label):
                got = themes.parity("birdseye", dict(body), WHEN)
                self.assertEqual((got["diff_px"], got["worst_channel_delta"]), (0, 0),
                                 f"{label}: {got}")

    def test_the_export_is_the_header_three_sections_six_dials_and_five_bars(self):
        widgets = self.obj["osd"]["widget"]
        kinds = {}
        for w in widgets:
            kinds[w["type"]] = kinds.get(w["type"], 0) + 1
        self.assertEqual(kinds, {"text": 13, "data": 14, "arc": 6, "bar": 5,
                                 "line": 3, "special": 5}, kinds)
        self.assertEqual(len(widgets), 46)
        # the counts are also asserted structurally, because a bare number can be satisfied
        # by the wrong rows: every dial has a ring, a number and a name; every bar has a
        # figure, a label, a meter and a number
        names = [str((w["property"] or [{}])[0].get("name") or "") for w in widgets]
        self.assertEqual(sum(1 for n in names if n.startswith("icon-")), 5)
        self.assertEqual(len([w for w in widgets if w["type"] == "arc"]),
                         sum(len(row) for row in themes.BIRDSEYE_DIALS))

    def test_each_dials_number_and_name_sit_inside_its_own_ring(self):
        """A dial that prints its number outside its ring is not a dial.

        Addressed by widget id, not by source name or label: `CPU Temperature` is the
        source of an arc, a number and a meter in this one file, and the word `CPU` is both
        a dial's name and a usage bar's label.  Names cannot address a row here; ids can.
        """
        boxes, _notes = self.boxes(FULL)
        for row, (cy, entries) in enumerate(zip(render.BIRDSEYE_DIAL_CY,
                                                themes.BIRDSEYE_DIALS)):
            for col, (label, src, _lo, _hi, _fig) in enumerate(entries):
                cx = render.BIRDSEYE_DIAL_CX[col]
                inner = render.BIRDSEYE_DIAL_R - render.BIRDSEYE_DIAL_W // 2
                slug = src.lower().replace(" ", "-")
                for suffix in ("value", "name"):
                    found = boxes.get(f"xigma-birdseye-{slug}-{suffix}")
                    if found is None:
                        continue
                    _kind, _what, box = found
                    dx = max(abs(box[0] - cx), abs(box[2] - cx))
                    dy = max(abs(box[1] - cy), abs(box[3] - cy))
                    self.assertLessEqual(max(dx, dy), inner + 4,
                                         f"{src}'s {suffix} escapes its dial: its ink box "
                                         f"reaches {max(dx, dy):.1f} px from the centre, "
                                         f"while the ring's inner edge is at {inner}")

    def test_no_dials_box_overlaps_another_dials_or_the_usage_column(self):
        boxes, _notes = self.boxes(FULL)
        rings = {ident: found[2] for ident, found in boxes.items()
                 if ident.endswith("-ring")}
        items = list(rings.items())
        for i, (a_name, a) in enumerate(items):
            for b_name, b in items[i + 1:]:
                clear = (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
                self.assertTrue(clear, f"the {a_name} ring box overlaps the {b_name} ring: "
                                       f"{a} against {b}")
        bar_boxes = [found[2] for ident, found in boxes.items()
                     if ident.endswith("-meter") and "disk" in ident]
        for box in bar_boxes:
            self.assertGreaterEqual(box[1], render.BIRDSEYE_ROW_Y0 - 20,
                                    "a usage meter has climbed into the dial rows")

    def test_a_missing_reading_takes_its_ring_and_number_and_says_which_it_was(self):
        boxes, notes = self.boxes(SPARSE)
        missing = {str(m) for m in (notes.get("missing") or [])}
        # every name here is the source itself: this theme has no gated rows, so there is
        # no `showIf:`-shadowed entry to expect the way `tests/test_bars_rows.py` expects
        # one for `Used GPU Memory`, whose number prints one side of the meter's division
        for src in ("GPU Temperature", "GPU Usage", "Fan 2 Speed", "GPU Fans Speed",
                    "Fan 2 Name", "GPU Memory Rate"):
            self.assertIn(src, missing, f"{src} is unanswered on this body and the report "
                                        f"does not say so: {sorted(missing)[:8]}")
        # and the subject labels still print, because the dials are part of the panel
        self.assertIn("xigma-birdseye-cpu-temperature-value", boxes,
                      "the CPU dial's number vanished from a body that answers the CPU")

    def test_the_sparse_body_still_draws_every_ring_it_can_answer(self):
        got = themes.parity("birdseye", dict(SPARSE), WHEN)
        self.assertGreater(got["boxes"], 20,
                           f"the sparse body draws only {got['boxes']} boxes: the theme is "
                           "supposed to keep its layout and lose only the holes")


class TheColumnClearsItself(unittest.TestCase):
    """The usage column's gutters, measured as ink on both doors, and its fit.

    Three mutations of this theme's own constants cost nothing to the checks that were
    here first, and two of them should not have: sliding the figure's box into the label
    column is a defect, and shrinking the usage pitch by one pixel is not.  So the rules
    below are written as measurements of the drawn frame rather than as pins of the
    constants, and both directions are then tried against them (`/tmp/opencode/mutate_
    birdseye.py` prints the census).

    The `bars` block already has its gutter measured this way - `tests/test_icons.py`'s
    `GutterOnTheGlass` - and a second theme needs the same rule restated rather than
    inherited, because `bars` puts its figure at x=3 against labels at 28 while this one
    uses 6 and 32 in a 20 px box.
    """

    @classmethod
    def setUpClass(cls):
        cls.code = render.draw(dict(FULL), "birdseye", bg=render.OVERLAY)
        cls.file, cls.notes = themes.draw(themes.export("birdseye"), dict(FULL), WHEN)

    def row_band(self, index: int) -> range:
        centre = render.BIRDSEYE_ROW_Y0 + index * render.BIRDSEYE_ROW_PITCH
        return range(centre - render.BIRDSEYE_ROW_PITCH // 2,
                     centre + render.BIRDSEYE_ROW_PITCH // 2)

    def test_the_figure_of_every_row_stays_in_its_box_and_out_of_the_label(self):
        for door, img in (("code", self.code), ("file", self.file)):
            d = alpha(img)
            for i in range(len(themes.BIRDSEYE_BARS)):
                band = self.row_band(i)
                box = ink_box(d, range(render.BIRDSEYE_ICON_X - 3,
                                       render.BIRDSEYE_ICON_X
                                       + render.BIRDSEYE_ICON_BOX[0] + 3), band)
                self.assertIsNotNone(box, f"{door} row {i}: no figure ink at all")
                right = render.BIRDSEYE_ICON_X + render.BIRDSEYE_ICON_BOX[0]
                self.assertLessEqual(box[2], right,
                                     f"{door} row {i}: the figure's ink reaches x={box[2]}, "
                                     f"past its declared box at x={right}")
                # The gutter between the figure's box and the label's ink, measured: this
                # design leaves 6 px (box ends at x=26, the label is anchored at x=32) and
                # the rule refuses anything under 4.  Stated as a clearance rather than as
                # "the next column's window starts where the last one ended", which cannot
                # fail by construction: pushing `BIRDSEYE_ICON_X` from 6 to 14 - the
                # mutation that made the figure's box straddle the label column - moves the
                # box and the ink together, and only a required gap notices.
                label = ink_box(d, range(right + 1, render.BIRDSEYE_BAR_X), band)
                self.assertIsNotNone(label, f"{door} row {i}: no label ink")
                self.assertGreaterEqual(label[0], right + 4,
                                        f"{door} row {i}: the label's ink starts at "
                                        f"x={label[0]} while the figure's box ends at x="
                                        f"{right}: {label[0] - right} px of gutter, and "
                                        "the design measures 6")

    def test_the_number_of_every_row_stays_clear_of_its_meter(self):
        """A full bar and its `100%` must still not touch."""
        full = dict(FULL, cpu={"temperature": 62.0, "load": 100.0},
                    gpu=dict(FULL["gpu"], load=100.0, fan=100.0, memoryUsage=16376),
                    memory={"used": 126155, "total": 126155},
                    disk=dict(FULL["disk"], activity=100.0))
        meter_end = render.BIRDSEYE_BAR_X + render.BIRDSEYE_BAR_W
        for door, img in (("code", render.draw(dict(full), "birdseye",
                                               bg=render.OVERLAY)),
                          ("file", themes.draw(themes.export("birdseye"), dict(full),
                                               WHEN)[0])):
            d = alpha(img)
            for i in range(len(themes.BIRDSEYE_BARS)):
                band = self.row_band(i)
                # the meter itself, first: at 100 % its ink must stop at the declared
                # width, or every clearance measured downstream is measured against a
                # bar that is not the one the file describes
                fill = ink_box(d, range(render.BIRDSEYE_BAR_X, meter_end + 4), band)
                self.assertIsNotNone(fill, f"{door} row {i}: no meter ink at 100 %")
                self.assertLessEqual(fill[2], meter_end,
                                     f"{door} row {i}: the meter's ink reaches x={fill[2]} "
                                     f"past its declared {render.BIRDSEYE_BAR_W} px width")
                # ...then the number, with a measured gutter, for the same reason as above
                number = ink_box(d, range(meter_end + 1, render.W), band)
                self.assertIsNotNone(number, f"{door} row {i}: no number drawn at 100 %")
                self.assertGreaterEqual(number[0], meter_end + 6,
                                        f"{door} row {i}: the number's ink starts at "
                                        f"x={number[0]} against a meter that runs to "
                                        f"x={meter_end}: {number[0] - meter_end} px of "
                                        "gutter, measured here at 15 on a full meter")

    def test_no_row_of_the_column_stands_on_the_next_one(self):
        gaps = {}
        for door, img in (("code", self.code), ("file", self.file)):
            d = alpha(img)
            bands = [ink_box(d, range(0, render.W), self.row_band(i))
                     for i in range(len(themes.BIRDSEYE_BARS))]
            self.assertTrue(all(b for b in bands), f"{door}: a row of the column is empty")
            between = [bands[k + 1][1] - bands[k][3] for k in range(len(bands) - 1)]
            gaps[door] = between
        print(f"  usage row-to-row ink gaps, {render.BIRDSEYE_ROW_PITCH} px pitch: "
              f"code {gaps['code']} px, file {gaps['file']} px")
        for door, between in gaps.items():
            for gap in between:
                self.assertGreaterEqual(gap, 2,
                                        f"{door}: two usage rows' ink sits {gap} px apart - "
                                        "neither a shared baseline nor a spaced row")

    def test_a_section_rule_measures_as_a_rule_not_as_a_band_of_ink(self):
        """Nothing else may share the hairline's row: a rule is what a caption heads.

        The three `line` rows are the only decoration in this layout, and their job is to
        carry the eye from a caption across to the group it names.  A hairline that lands
        **on** the dials it heads stops being a caption and becomes a stripe across six
        rings - which is what happens if the COOLING caption moves from y=182 to y=200,
        nine pixels above where the second dial row's ink begins (246 - 52).  Measured by
        the ink's own height: a rule is `BIRDSEYE_RULE_H` px thick, and in a window grown
        6 px each way nothing else may light up.
        """
        boxes = {str(w.get("id")): w["property"][0]
                 for w in themes.export("birdseye")["osd"]["widget"]}
        for door, img in (("code", self.code), ("file", self.file)):
            d = alpha(img)
            for caption, _cy in themes.BIRDSEYE_SECTIONS:
                prop = boxes[f"xigma-birdseye-rule-{caption.lower()}"]
                x, y = int(prop["x"]), int(prop["y"])
                w, h = int(prop["width"]), int(prop["height"])
                band = ink_box(d, range(x - 2, x + w + 2), range(y - 6, y + h + 8))
                self.assertIsNotNone(band, f"{door}: the {caption} rule drew no ink")
                tall = band[3] - band[1] + 1
                self.assertLessEqual(tall, h + 4,
                                     f"{door}: the {caption} rule measures {tall} px tall "
                                     f"where it declares {h}: something else is sharing "
                                     f"its row (y {band[1]}..{band[3]})")

    def test_the_column_fits_under_its_caption_and_above_the_canvas_edge(self):
        """The slack a reader asks about when they want a sixth bar, printed."""
        rows = len(themes.BIRDSEYE_BARS)
        pitch = render.BIRDSEYE_ROW_PITCH
        caption_y = dict(themes.BIRDSEYE_SECTIONS)["USAGE"]
        first = render.BIRDSEYE_ROW_Y0
        last = render.BIRDSEYE_ROW_Y0 + (rows - 1) * pitch
        slack = render.H - 1 - last - render.BIRDSEYE_ICON_BOX[1] // 2
        print(f"  usage column: {rows} rows on a {pitch} px pitch, {first}..{last} "
              f"centres, caption at y={caption_y}, {slack} px below the last box")
        self.assertGreaterEqual(first - render.BIRDSEYE_ICON_BOX[1] // 2 - caption_y, 12,
                                "the column starts inside its own caption")
        below = render.H - (last + render.BIRDSEYE_ICON_BOX[1] // 2)
        self.assertGreaterEqual(below, 4,
                                f"the last row's figure box ends at "
                                f"{last + render.BIRDSEYE_ICON_BOX[1] // 2}, off a "
                                f"{render.H} px canvas")
        # The ceiling, computed from the theme's own numbers rather than asserted from
        # prose: how many rows fit between the first centre and the canvas edge at this
        # pitch.  Five is the answer today, which is why the column has five bars - and
        # the day somebody wants a sixth, this is the figure that says what has to give.
        room = render.H - 1 - first - render.BIRDSEYE_ICON_BOX[1] // 2
        capacity = room // pitch + 1
        print(f"  usage ceiling at pitch {pitch}: {capacity} rows fit from y={first} "
              f"({room} px of room); this column has {rows}")
        self.assertEqual(capacity, rows,
                         f"the column declares {rows} rows and the canvas would hold "
                         f"{capacity} at a {pitch} px pitch: either a row is missing from "
                         f"the table or {rows - capacity} of them overlap the edge")
        d = alpha(self.code)
        bottom = max(ink_box(d, range(0, render.W), self.row_band(i))[3]
                     for i in range(rows))
        self.assertLessEqual(bottom, render.H - 1,
                             f"the column's ink ends at y={bottom} on a {render.H} px "
                             "canvas")


class TheDeclaredHoles(unittest.TestCase):
    """What this file says about its own dependencies: nothing, and that is the point."""

    def test_no_row_of_this_export_depends_on_another_rows_reading(self):
        gated = [str(w.get("id")) for w in themes.export("birdseye")["osd"]["widget"]
                 if (w["property"][0].get("xigma") or {}).get("showIf")]
        bars_gated = [str(w.get("id")) for w in themes.export("bars")["osd"]["widget"]
                      if (w["property"][0].get("xigma") or {}).get("showIf")]
        print(f"  `xigma.showIf` rows: birdseye {len(gated)}, bars {len(bars_gated)} "
              f"{bars_gated}")
        self.assertEqual(gated, [],
                         f"{len(gated)} rows of birdseye now name a dependency: every "
                         "number in this theme asks the same source as its own meter, so "
                         "the hole is already reported once by that source and a gate "
                         "would report the same hole twice - `bars` needs the key because "
                         "there the number prints one side of the division")
        self.assertGreater(len(bars_gated), 0,
                           "the contrast this check is written against has gone away: "
                           "`bars` no longer gates its memory numbers")

    def test_every_hole_is_reported_by_the_rows_that_can_be_seen_missing(self):
        """The report's shape, corrected twice against claims of my own that measurement refuted.

        First I wrote that an unanswered reading is "reported once" in this theme.  It is
        not, and should not be: a dial is two visible rows on one source (its ring and its
        number), so a machine with no discrete card is told about it twice.  Then I counted
        the usage rows as three each, and the file disagreed: a `special` **figure** row
        never reports anything.  That asymmetry is the actual rule, and it is the same one
        `bars` has had since its gutter column arrived (see
        `tests/test_icons.py`'s check that a row with no reading draws no figure): a figure
        with no reading draws nothing, and the hole it would have illustrated is already on
        the report from the meter and the number beside it - so a third entry naming
        `icon-card` would tell a reader nothing they could act on.

        So what is pinned here is the count *and* the reason for the gap: exactly the
        `arc`/`bar`/`data` rows asking a hole report it, the `special` rows do not, and no
        hole is reported a second way as a `showIf:` shadow, because no row of this file
        depends on another row's reading.
        """
        obj = themes.export("birdseye")
        asking = {}
        for w in obj["osd"]["widget"]:
            prop = w["property"][0]
            src = prop.get("source")
            if src:
                asking.setdefault(str(src), []).append(w["type"])
        _img, notes = themes.draw(obj, dict(SPARSE), WHEN)
        missing = [str(m) for m in (notes.get("missing") or [])]
        visible = {src: sum(1 for kind in kinds if kind in ("arc", "bar", "data"))
                   for src, kinds in asking.items()}
        silent = {src: sum(1 for kind in kinds if kind == "special")
                  for src, kinds in asking.items() if src in visible}
        holes = {src for src in visible if missing.count(src)}
        print(f"  one-fan body with no card: {len(missing)} report entries over "
              f"{len(holes)} holes; visible rows per hole "
              f"{ {s: visible[s] for s in sorted(holes)} }; silent figure rows "
              f"{ {s: silent[s] for s in sorted(holes) if silent[s]} }")
        self.assertEqual(holes, {"GPU Temperature", "GPU Usage", "GPU Memory Rate",
                                 "Fan 2 Speed", "Fan 2 Name", "GPU Fans Speed"},
                         "the holes this body leaves are not the ones the file reports: "
                         f"{sorted(holes)}")
        for src in sorted(holes):
            self.assertEqual(missing.count(src), visible[src],
                             f"{src}: {visible[src]} rows of this theme can be seen to be "
                             f"missing it, {missing.count(src)} said so")
            self.assertEqual(len(asking[src]), visible[src] + silent.get(src, 0),
                             f"{src}: {len(asking[src])} rows ask it and the report says "
                             f"{missing.count(src)}: a kind of row went silent that should "
                             "not have, and the reverse is only true of `special`")
        shadow = [m for m in missing if m.startswith("showIf:")]
        self.assertEqual(shadow, [],
                         f"{shadow} shadow a source report in a theme whose rows carry no "
                         "dependency: the same hole told two ways is how a reader starts "
                         "ignoring the report")

    def test_the_silent_figure_rows_draw_nothing_at_a_hole(self):
        """`special` says nothing on the report, so it had better also draw nothing."""
        vals, _gone = themes.values(dict(SPARSE), WHEN)
        code = render.draw(dict(SPARSE), "birdseye", bg=render.OVERLAY)
        d = alpha(code)
        left = render.BIRDSEYE_ICON_X - 1
        right = render.BIRDSEYE_ICON_X + render.BIRDSEYE_ICON_BOX[0] + 1
        bad = []
        rows = themes.BIRDSEYE_BARS
        for i, (label, src, _lo, _hi, _fig) in enumerate(rows):
            cy = render.BIRDSEYE_ROW_Y0 + i * render.BIRDSEYE_ROW_PITCH
            box = ink_box(d, range(left, right), range(cy - 11, cy + 12))
            answered = vals.get(src) is not None
            if answered and box is None:
                bad.append((label, src, "no figure ink at a row that answers"))
            elif box is not None and not answered:
                bad.append((label, src, f"drew ink at x {box[0]}..{box[2]} at a hole"))
        lit = sum(1 for row in rows if vals.get(row[1]) is not None)
        print(f"  figure column on a one-fan body with no card: {lit} of {len(rows)} rows "
              "answer, and only those carry ink in the figure box")
        self.assertEqual(bad, [], f"figure rows disagreeing with their readings: {bad}")


class TheCutClip(unittest.TestCase):
    """The background this theme names, and the vendor file it was cut from."""

    @classmethod
    def setUpClass(cls):
        cls.trimmed = os.path.join(fixtures.REPO, TRIMMED)
        if not os.path.exists(cls.trimmed):
            raise unittest.SkipTest(f"no {TRIMMED} in this checkout")
        fixtures.need("ffmpeg", "ffprobe")

    def test_the_trimmed_asset_is_what_its_record_says_it_is(self):
        probe = ffprobe(self.trimmed, ["nb_frames", "duration", "width", "height"])
        frames, duration = probe["nb_frames"], probe["duration"]
        wide, tall = probe["width"], probe["height"]
        print(f"  paired clip: {os.path.basename(self.trimmed)} {int(frames)} frames at "
              f"{duration} s, {wide}x{tall}, {os.path.getsize(self.trimmed)} B, "
              f"sha256 {sha256_of(self.trimmed)[:16]}")
        self.assertEqual(int(frames), 168, "the cut moved: 17 leading frames were removed")
        self.assertAlmostEqual(float(duration), 8.40, places=2)
        self.assertEqual((int(wide), int(tall)), (render.W, render.H),
                         "the paired file is not the canvas the themes draw on")

    def test_the_head_of_the_cut_carries_no_play_button_and_the_original_still_does(self):
        """The reason for the cut, measured at the frame the loop starts on."""
        quiet = centre_luma(self.trimmed, 0.0)
        self.assertLess(quiet, 3.0,
                        f"the trimmed clip's first frame reads {quiet:.2f} centre luma: the "
                        "still head is back, or the cut moved")
        src = None
        for root in ("/usr/share/xigmalcd/themes/alpha/clips",
                     os.path.join(fixtures.REPO, "themes", "alpha", "clips")):
            candidate = os.path.join(root, "theme_47.mp4")
            if os.path.exists(candidate):
                src = candidate
                break
        if src is None:
            self.skipTest("no vendor theme_47.mp4 on this machine to compare against")
        loud = centre_luma(src, 0.2)
        self.assertGreater(loud, 4.0,
                           f"the vendor's own head reads {loud:.2f} centre luma - the play "
                           "button is not where the measurement said it was")
        print(f"  play button, measured at the centre of the first frames: vendor head "
              f"{loud:.2f}, cut head {quiet:.2f}")

    def test_the_cut_did_not_worsen_the_loop_seam(self):
        duration = ffprobe(self.trimmed, ["duration"])["duration"]
        ours = seam(self.trimmed, float(duration))
        src = os.path.join("/usr/share/xigmalcd/themes/alpha/clips", "theme_47.mp4")
        if not os.path.exists(src):
            self.skipTest("no vendor file to compare the seam against")
        orig_dur = ffprobe(src, ["duration"])["duration"]
        theirs = seam(src, float(orig_dur))
        print(f"  seam: cut copy {ours:.3f} against vendor file {theirs:.3f} "
              "(mean abs grey difference, first frame vs last)")
        self.assertLessEqual(ours, theirs + 0.5,
                             "the cut copy loops worse than the file it came from")

    def test_the_vendor_file_is_still_the_vendor_file(self):
        """Editing evidence is not how this repository fixes an ugly first second.

        `themes/alpha/manifest.json` lists 125 copied files with a `path`, a `bytes` count
        and a `sha256` each - the record that makes any claim about a vendor frame
        re-checkable by a reader.  So the play-button cut had to be a **new asset beside**
        the vendor's clip, and this check is what keeps it that way: the original's digest
        still matches its own manifest entry, and the manifest entry's byte count still
        matches the file on disk.

        Skipped, with the reason said out loud, on a machine that has no vendored library
        installed - the library is not in this repository's git (docs/limits.md explains
        why: 66 MB of ALPHA's own files, and the panel's serial number inside several of
        them), so the only honest failure is on a box that does have it.
        """
        root = None
        for candidate in ("/usr/share/xigmalcd/themes/alpha",
                          os.path.join(fixtures.REPO, "themes", "alpha")):
            if os.path.exists(os.path.join(candidate, "manifest.json")):
                root = candidate
                break
        if root is None:
            self.skipTest("no vendored library, so no manifest to check the vendor's bytes "
                          "against")
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        wanted = None
        for entry in manifest.get("files") or []:
            if str(entry.get("path") or "").endswith("clips/theme_47.mp4"):
                wanted = entry
                break
        if wanted is None:
            self.skipTest("the manifest carries no clips/theme_47.mp4 entry on this machine")
        on_disk = os.path.join(root, "clips", "theme_47.mp4")
        if not os.path.exists(on_disk):
            self.skipTest("the manifest names the clip; this install does not carry it")
        digest = str(wanted.get("sha256") or "")
        self.assertEqual(len(digest), 64, f"the manifest entry names no usable digest: {wanted}")
        self.assertEqual(sha256_of(on_disk), digest,
                         "the vendor's theme_47.mp4 no longer matches its own manifest "
                         "entry: the cut was made **in place**, and the evidence is gone")
        self.assertEqual(os.path.getsize(on_disk), int(wanted.get("bytes") or -1),
                         "the byte count disagrees with the manifest as well as the digest")
        # and the copy this theme actually pairs with is a different file, by hash: proof
        # that the cut exists as a derived asset and not as an edit of the original
        self.assertNotEqual(sha256_of(on_disk), sha256_of(self.trimmed),
                            "the paired asset and the vendor file are the same bytes, so "
                            "nothing was cut")

    def test_the_theme_declares_the_clip_and_the_pairing_door_agrees(self):
        clip, why = themes.pair("birdseye")
        self.assertEqual(clip, "theme_47-trimmed.mp4", why)
        self.assertFalse(why, "a theme that names a clip answered with a reason anyway")
        self.assertEqual(themes.CODE_CLIPS.get("birdseye"), "theme_47-trimmed.mp4")
        self.assertEqual(str(self_theme_media_file()), "theme_47-trimmed.mp4",
                         "the generated file's own `background.mediaFile` disagrees with "
                         "`CODE_CLIPS`, so the window and the loop would pair differently")

    def test_the_geometry_of_this_theme_is_declared_as_chosen_not_measured(self):
        self.assertEqual(themes.GEOMETRY_ORIGIN.get("birdseye"), "chosen here",
                         "birdseye's placement numbers are ours, and the check that holds "
                         "them to a lattice asks for that declaration by name")


def self_theme_media_file():
    obj = themes.export("birdseye")
    return os.path.basename(str((obj.get("background") or {}).get("mediaFile") or ""))


class TheDiskBar(unittest.TestCase):
    """Which disk field the fifth bar reads, and which one it refuses."""

    def test_the_disk_bar_reads_the_busy_percent_the_vendor_defines(self):
        self.assertEqual(themes.SOURCES["Disk Activity"], ("disk", "activity"))
        vals, _gone = themes.values({"disk": {"activity": 22.0, "load": 1.4}}, WHEN)
        self.assertEqual(layout.text_for("Disk Activity", vals["Disk Activity"]), "22%")
        row = [r for r in themes.BIRDSEYE_BARS if r[1] == "Disk Activity"]
        self.assertEqual(len(row), 1, row)
        self.assertEqual((row[0][0], row[0][2], row[0][3], row[0][4]),
                         ("DISK", 0, 100, "drive"), row[0])

    def test_the_sibling_field_is_reported_on_the_wire_but_not_drawn_and_says_why(self):
        """`disk.load` (iowait %) is a vendor field too.  It is not this bar.

        Recorded in code because it is the kind of choice a later reader re-litigates: on
        this bench iowait reads 0.0 % at idle even while the drive is serving - a fast
        NVMe device finishes requests before anything waits on them - so the bar would be
        empty at the moment a reader wants to know whether storage is doing anything.
        `disk.activity` is the fraction of the interval the device was busy, and it moves:
        0.3 % idle, 22 % while a copy runs.
        """
        self.assertEqual(themes.SOURCES.get("Disk Activity"), ("disk", "activity"))
        asked = {r[1] for r in themes.BIRDSEYE_BARS}
        self.assertNotIn("Disk Load", asked,
                         "a `Disk Load` source joined the bars: re-read this note, and "
                         "docs/limits.md, before accepting the swap")
        body = dict(FULL, disk=dict(FULL["disk"], activity=0.0, load=41.0))
        got = themes.parity("birdseye", body, WHEN)
        self.assertEqual((got["diff_px"], got["worst_channel_delta"]), (0, 0), got)


class TheCensus(unittest.TestCase):
    def test_the_ink_and_box_census_of_this_theme_prints_for_this_machine(self):
        fixtures.need("ffmpeg", "ffprobe")
        code = render.draw(dict(FULL), "birdseye", bg=render.OVERLAY)
        alpha = code.convert("RGBA").getchannel("A").load()
        lit = sum(1 for y in range(render.H) for x in range(render.W) if alpha[x, y] > 8)
        _img, notes = themes.draw(themes.export("birdseye"), dict(FULL), WHEN)
        print(f"  birdseye census: {len(notes['boxes'])} boxes drawn, {lit} lit px of the "
              f"overlay at a full body; {len(themes.export('birdseye')['osd']['widget'])} "
              f"widgets in the generated file")
        self.assertGreater(lit, 20000, "this theme draws almost nothing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
