#!/usr/bin/env python3
"""Pinned readings: the cases this machine's sensors will not produce, drawn without sending them.

Ported from `tools/selftest.sh`'s pinned-metrics section.  Two separate jobs, and the second is the
load-bearing one for anyone with a panel attached:

* `--metrics-file` lets a body of readings be supplied, so a 104 °C sweep or a missing temperature
  can be drawn and looked at without a load generator and without a panel;
* while readings are pinned, the upload path sends **no state frames at all** - it would otherwise
  put this machine's live numbers on the glass underneath a picture drawn from the file.

Both halves run against a recording stub, so nothing here can reach a device: `one_frame` is given
an object that appends to a list, and there is no serial call in the file.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import tempfile
import unittest

from tests import fixtures

from xigmalcd import main as m
from xigmalcd import render

HOT = {"cpu": {"temperature": 104.0, "load": 42.0},
       "gpu": {"temperature": 96.0, "load": 61.0},
       "_comment": "a key like this is a note in the file, not a section"}
MISSING = {"cpu": {"load": 42.0}, "gpu": {"load": 61.0}}


def arc_samples(img) -> list:
    """Colours met along the CPU arc's filled part, at the stroke's middle."""
    cx, cy, r = render.A26_TCOL_X[0], render.A26_RING_Y, render.A26_RING_R - 6
    out = []
    for deg10 in range(0, 3600, 2):
        angle = math.radians(render.A26_ARC_START + deg10 / 10.0)
        px = img.getpixel((int(round(cx + r * math.cos(angle))),
                           int(round(cy + r * math.sin(angle)))))
        if px[3] > 200:
            out.append(px[:3])
    return out


class Stub:
    """What a run would put on the wire, recorded instead of sent."""

    def __init__(self):
        self.state, self.media = [], []

    def state_all(self, body):
        self.state.append(body)

    def send_media(self, name, blob, **kwargs):
        self.media.append(blob)
        return {"notice": "1 200"}


class Pinned(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix="xigma-pin-")
        self.hot = os.path.join(self.root.name, "hot.json")
        self.missing = os.path.join(self.root.name, "missing.json")
        for path, body in ((self.hot, HOT), (self.missing, MISSING)):
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(body, fh)
        # distinct on purpose: the pin cache is re-read when the file's clock moves
        os.utime(self.hot, (1_000_000, 1_000_000))
        os.utime(self.missing, (1_000_100, 1_000_100))
        self.carry = (dict(m.PINNED), m.PINNED_MTIME)

    def tearDown(self):
        m.PINNED, m.PINNED_MTIME = self.carry
        self.root.cleanup()

    def args_for(self, extra) -> object:
        return m.build_parser().parse_args(["--theme", "alpha"] + extra)

    @staticmethod
    def quiet(call):
        """Run something that prints a notice, and keep the notice instead of mixing it into the
        test output.  `sample` tells the person running a loop that the picture is not this
        machine's readings, which is right on a terminal and noise in a report."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = call()
        return result, out.getvalue()

    def test_the_run_says_out_loud_that_the_readings_are_not_the_machines(self):
        m.PINNED, m.PINNED_MTIME = {}, None
        _body, text = self.quiet(lambda: m.sample(self.args_for(["--metrics-file", self.hot])))
        self.assertIn("pinned", text.lower(), text)

    def test_the_file_says_what_it_says_and_a_note_is_not_a_section(self):
        m.PINNED, m.PINNED_MTIME = {}, None
        pinned, _text = self.quiet(lambda: m.sample(self.args_for(["--metrics-file", self.hot])))
        self.assertEqual(pinned["cpu"]["temperature"], 104.0)
        self.assertNotIn("_comment", pinned,
                         "a key starting with `_` is a note in the file, not a section")

    def test_pinned_uploads_the_frame_and_no_state_blob(self):
        m.PINNED, m.PINNED_MTIME = {}, None
        args = self.args_for(["--metrics-file", self.hot])
        pinned = self.quiet(lambda: m.sample(args))[0]
        sent = Stub()
        self.quiet(lambda: m.one_frame(sent, pinned, args, push_state=True))
        self.assertEqual(sent.state, [], "a pinned run put this machine's live readings on "
                                         "the glass")
        self.assertEqual(len(sent.media), 1)

    def test_unpinned_sends_both_the_state_and_the_frame(self):
        """The comparison that makes the check above mean something: unpinned, the same call
        sends one of each."""
        m.PINNED, m.PINNED_MTIME = {}, None
        args = self.args_for([])
        sent = Stub()
        self.quiet(lambda: m.one_frame(sent, m.sample(args), args, push_state=True))
        self.assertEqual(len(sent.state), 1)
        self.assertEqual(len(sent.media), 1)

    def test_a_reading_the_sensors_will_not_give_still_draws_the_far_end_of_the_ramp(self):
        m.PINNED, m.PINNED_MTIME = {}, None
        pinned = self.quiet(lambda: m.sample(self.args_for(["--metrics-file", self.hot])))[0]
        drawn = arc_samples(render.draw(pinned, "alpha", bg=render.OVERLAY))
        self.assertGreater(len(drawn), 1200,
                           f"{len(drawn)} samples: expected the whole 260 deg, not half of it")
        tip = render.temp_colour(104.0, render.A26_ARC_LO, render.A26_ARC_MID,
                                 render.A26_ARC_HI)
        worst = max(abs(x - y) for x, y in zip(drawn[-1], tip))
        self.assertLessEqual(worst, 12, f"outer colour {drawn[-1]} against the ramp's own {tip}")

    def test_a_missing_reading_paints_no_arc_at_all(self):
        m.PINNED, m.PINNED_MTIME = {}, None
        body = self.quiet(lambda: m.sample(self.args_for(["--metrics-file", self.missing])))[0]
        gone = arc_samples(render.draw(body, "alpha", bg=render.OVERLAY))
        self.assertEqual(gone, [], gone[:3])


class VendoredBackgrounds(unittest.TestCase):
    """The three clips this repository ships as the vendor's own bytes.

    Pinned sizes and MD5s are the write-detection tripwire: the claim in `debian/copyright` and in
    the theme library's manifest is that these are XIGMATEK's files, so any change to them here is
    a lie about their origin, not an edit.
    """

    FILES = ((m.DEFAULT_MP4, 214_917, "b818b7d3294b3625e9f143e920ccc9b0"),
             (m.QUIET_MP4, 3_402_098, "4a515a8a17204ffb5a23d2ac34dd37ee"),
             (m.BRIGHT_MP4, 1_333_649, "51701687804f60875da872c7f27ad673"))

    def test_each_is_the_vendor_file_the_docs_call_it(self):
        import hashlib
        for path, size, md5 in self.FILES:
            with self.subTest(clip=os.path.basename(path)):
                with open(path, "rb") as fh:
                    blob = fh.read()
                self.assertEqual(len(blob), size)
                self.assertEqual(blob[4:8], b"ftyp", "an MP4 container, not a stub")
                self.assertEqual(hashlib.md5(blob).hexdigest(), md5,
                                 "the vendor's own bytes, not ours")


if __name__ == "__main__":
    unittest.main(verbosity=2)
