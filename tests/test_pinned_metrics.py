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


class CarriedBackgrounds(unittest.TestCase):
    """The clips `media/` holds that are *not* the vendor's bytes, and the set as a set.

    `VendoredBackgrounds` above pins three files with an MD5 each, because the claim in
    `debian/copyright` is that those are XIGMATEK's and unchanged.  This class holds the
    other eleven, and the reason is different: those are ours to make, so nothing forbids
    changing them - but a clip that a theme *pairs with*, or that ships in a package,
    should not change silently either.  Two of them do carry a claim:

    * `theme_47-trimmed.mp4` is a derived asset: 17 leading frames removed from the
      vendor's `theme_47.mp4`, whose own digest `tests/test_birdseye.py` verifies against
      the library manifest.  Its frames, length and digest are pinned there; pinned here as
      well so the whole media set is one table.
    * the ten made on this bench by the owner of it, contributed on 2026-11-14 with the
      owner's own statement that they are theirs to license.  Nothing here can verify that
      sentence - it is a fact about a person, not about bytes - so the pin records what was
      contributed, which is the half that *is* checkable and the half a later reader can
      diff against.

    Then the two directions the set can drift: a file in `media/` that git does not track
    (this happened on 2026-11-14, when three tracked clips vanished from the working tree
    and ten untracked ones appeared, and nothing but a `git status` said so), and an
    install line in `debian/rules` that names fewer clips than the repository holds.
    """

    #: name -> (bytes, sha256), as measured on the tree 2026-11-14
    OWN = (
        ("AI_chip_black.mp4", 897970,
         "7af4554236bf8217d474646e13fc55d408ab89dd11a5ac9aee489163b0c0a80e"),
        ("AI_chip_blue.mp4", 407170,
         "b3395fea1af3200c28a6b596731f3728e183d7e7b6ad9981f0d6e417372bd1d9"),
        ("AI_network.mp4", 1683651,
         "0aca417addb5b81441aa1916ee1e69d5583cd2b6fe1dc64532287440a9472f45"),
        ("cpu_processing.mp4", 638956,
         "3f1f8ecace47a43ac5e174af04a292a187b3395bb55c8efe4eaae935cffd1ec9"),
        ("interstellar.mp4", 1269262,
         "da76c24f38ccf9f117985e5a0a36489dcb3a392c9c04a052adcd136b06e51f06"),
        ("matrix_binary.mp4", 2655470,
         "9bf2d8bc5ad54c8b7cce56c35161c209c2c65fcd82b4075e20f4b1ca9f00b51e"),
        ("matrix_black.mp4", 502996,
         "7b6e3cb71f0d4ed0149a2c83df99725fe95ca3f98e7f39b3bc08ec7d20f4060c"),
        ("matrix_blue.mp4", 1806149,
         "cda74b7d9ed65a92cc884fab08ec0045cc3ed191629586c916f9d9d7c7247bec"),
        ("matrix_magenta.mp4", 1624475,
         "54cdbc50cbac8d9a8ef29964c5a5e2024bed287b37e03a1dfb52e2ca2fdc5b93"),
        ("water_splash.mp4", 3522068,
         "edd044a0c2fb56706427bba8720d3c4e241b4f4abb2c60719e8fbf0d688986e0"),
        ("theme_47-trimmed.mp4", 1071306,
         "21a949135a287d7df7cb143ebf4cdc635feb9785ec0b4153dcf479734c842f2d"),
    )

    def test_each_carried_clip_is_the_file_the_table_records(self):
        import hashlib
        total = 0
        for name, size, digest in self.OWN:
            path = os.path.join("media", name)
            with self.subTest(clip=name):
                if not os.path.exists(path):
                    self.skipTest(f"no {path} in this checkout")
                with open(path, "rb") as fh:
                    blob = fh.read()
                self.assertEqual(len(blob), size, f"{name} changed length")
                self.assertEqual(blob[4:8], b"ftyp", "an MP4 container, not a stub")
                self.assertEqual(hashlib.sha256(blob).hexdigest(), digest,
                                 f"{name}'s bytes changed: this is a re-encode, not an edit")
                total += size
        print(f"  carried clips pinned: {len(self.OWN)}, {total:,d} B "
              f"(every one of them the repository's own, not the vendor's)")

    def test_every_clip_in_media_is_tracked_and_every_tracked_one_is_present(self):
        """Both halves of the slip this bench had on 2026-11-14.

        Three vendored clips had been deleted from the working tree and ten untracked ones
        had appeared in the same directory, and every gate in the suite stayed green except
        the two that resolve clip names - because nothing else asked what `git` thinks is in
        that directory.  A media set that ships is a set, and a set has membership.
        """
        on_disk = sorted(f for f in os.listdir("media") if f.lower().endswith(".mp4"))
        tracked = sorted(os.path.basename(p) for p in fixtures.tracked()
                         if p.startswith("media/") and p.endswith(".mp4"))
        print(f"  media/: {len(on_disk)} files on disk, {len(tracked)} tracked by git")
        self.assertEqual(on_disk, tracked,
                         f"the directory and the index disagree: on disk only "
                         f"{sorted(set(on_disk) - set(tracked))}, in git only "
                         f"{sorted(set(tracked) - set(on_disk))}")

    def test_the_package_installs_the_whole_set(self):
        """`debian/rules` names what ships, so the rules can be read and counted."""
        with open(os.path.join("debian", "rules"), encoding="utf-8") as fh:
            rules = fh.read()
        tracked = sorted(os.path.basename(p) for p in fixtures.tracked()
                         if p.startswith("media/") and p.endswith(".mp4"))
        # the *file* install, not the `install -d` that makes the directory first
        line = [ln for ln in rules.split("\n")
                if "usr/share/xigmalcd/media" in ln and "install -m" in ln]
        self.assertEqual(len(line), 1, rules[:200])
        spelled = " ".join(line)
        named = [f for f in tracked if f in spelled]
        globbed = "media/*.mp4" in spelled
        print(f"  debian/rules installs {len(named)} named clips"
              + (" plus a `media/*.mp4` glob" if globbed else " (no glob)"))
        if globbed:
            self.assertEqual(named, [], "a glob and named files in one line: the named ones "
                                        "are either redundant or the set is not a set")
            return
        self.assertEqual(sorted(named), tracked,
                         f"the install line names {len(named)} of {len(tracked)} clips the "
                         f"repository tracks; the rest ship as nothing at all: "
                         f"{sorted(set(tracked) - set(named))}")



if __name__ == "__main__":
    unittest.main(verbosity=2)
