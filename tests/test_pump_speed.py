#!/usr/bin/env python3
"""`Pump Speed` answered by a fan row's **type**, and the nine layouts that ask for it.

Written on 2026-11-13, after the owner re-wired this bench - six case fans to the Xigmatek
Mini ARGB controller, the Xigmatek Connect 360's block cable to `PUMP_SYS1`, its radiator
fans to `CPU_FAN1` - and a tachometer that had read 0 in every one of the 30 samples of the
previous watch came up steady at 2459-2469 RPM.  Until then `themes.UNMAPPED` refused
`Pump Speed` for the nine layouts that ask it with a flat sentence, and that refusal was a
*hard-coded constant*: measured at the time, a body offering `{"type": "Pump", "name": "CPU
PUMP", "value": 2410}` still left the source unanswered.  So the name had a rule-shaped hole
in it, and the fix is a rule:

    `themes.FAN_TYPED` answers a source from the first fan row whose `type` matches, and
    `themes.ROW_WHY` says why it cannot when no row does.

What that rule must **not** do is guess.  `nct6683` binds this board's NCT6687D and publishes
ten tach inputs and no `fan*_label` at all, so a channel's identity is a measurement, recorded
once in `sensors.FAN_CHANNELS`, and the type there is the only thing this rule reads - never a
substring of a name.  The first check below is the one that holds that line.

The pixel consequence is asserted as a relation, never as a number: nine files gain exactly
one painted box each when a pump row is present, the other fourteen gain nothing, and every one
of those nine frames differs from its own pumpless twin.  How many *pixels* differ is a face
metric - measured on this bench at 555 px for the seven size-20 rows and 1123 px for the two
size-32 ones - so the check prints those and asserts only that the count is non-zero.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest

from PIL import ImageChops

from tests import fixtures

from xigmalcd import render, sensors, themes

#: A body with every reading the pickable library asks for **except** a pump: `fixtures.SESSION`
#: plus the two fan rows this bench actually reported on 2026-11-13.
NO_PUMP = dict(fixtures.SESSION,
               fans=[{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 1724},
                     {"onBoard": True, "type": "Chassis", "name": "Fan System 5",
                      "value": 1560}])

#: The same body with the pump row the pin table produces: on this bench `sensors.fans()`
#: answered exactly these two rows, in this order, on 2026-11-13 (`fan12` reports no pulses
#: since its fan moved to the ARGB controller, so it drops out).
WITH_PUMP = dict(NO_PUMP, fans=[{"onBoard": True, "type": "Fan", "name": "Fan CPU",
                                 "value": 1724},
                                {"onBoard": True, "type": "Pump", "name": "CPU PUMP",
                                 "value": 2453}])


def paint(rec, body):
    return themes.paint(rec, body, when=fixtures.SESSION_WHEN, scrim=0)


def sources_of(rec) -> set:
    body = themes.load(rec["path"])
    return {str(p.get("source")) for w in (body.get("osd") or {}).get("widget") or []
            for p in w.get("property") or [] if p.get("source")}


class TheRule(unittest.TestCase):
    """`themes.values()` and the row's type, with no sysfs under it."""

    def test_the_rule_reads_the_type_and_never_a_substring_of_the_name(self):
        """The gate on the whole change: a row called `CPU PUMP` but typed `Fan` must not
        answer `Pump Speed`, and a row called `nct6687 fan2` typed `Pump` must."""
        named = {"fans": [{"onBoard": True, "type": "Fan", "name": "CPU PUMP",
                           "value": 2410}]}
        typed = {"fans": [{"onBoard": True, "type": "Pump", "name": "nct6687 fan2",
                           "value": 2410}]}
        out, absent = themes.values(named, fixtures.SESSION_WHEN)
        self.assertIsNone(out.get("Pump Speed"),
                          "a fan whose name says pump answered `Pump Speed`: that is the "
                          "guess this rule exists to refuse - `nct6683` publishes no "
                          "fan*_label, so a name is not evidence")
        self.assertIn("Pump Speed", absent)
        out, _absent = themes.values(typed, fixtures.SESSION_WHEN)
        self.assertEqual(out.get("Pump Speed"), 2410,
                         "a row the pin table typed `Pump` did not answer the source that "
                         "asks for a pump, whatever it is called")

    def test_a_pump_row_reading_zero_is_no_reading(self):
        """An unwired header and a stopped pump print the same thing, so neither prints."""
        body = {"fans": [{"onBoard": True, "type": "Pump", "name": "CPU PUMP", "value": 0}]}
        out, absent = themes.values(body, fixtures.SESSION_WHEN)
        self.assertIsNone(out.get("Pump Speed"))
        self.assertIn("Pump Speed", absent, absent)

    def test_the_refusal_names_the_measurement_that_would_answer_it(self):
        """The sentence a box without a pump gets has to point at the tool, not at a constant."""
        out, absent = themes.values(NO_PUMP, fixtures.SESSION_WHEN)
        self.assertIsNone(out.get("Pump Speed"))
        why = absent["Pump Speed"]
        for needle in ("fanscan", "FAN_CHANNELS"):
            self.assertIn(needle, why, f"{needle!r} is not in the reason a pumpless box gives: "
                                       f"{why}")
        self.assertNotIn("never", why.lower(),
                         f"the reason claims a thing was never looked for again: {why}")

    def test_the_pump_row_keeps_its_pinned_name_in_the_positional_slot(self):
        """`bars` prints `Fan N Name`; a pinned pump in slot 2 must still say what it is."""
        out, _absent = themes.values(WITH_PUMP, fixtures.SESSION_WHEN)
        self.assertEqual(out.get("Fan 2 Name"), "CPU PUMP",
                         "the pump row lost its pinned name on the way to a fan slot, so "
                         "`bars` would print a channel number where it knows a part")
        self.assertEqual(out.get("Fan 2 Speed"), 2453)

    def test_a_pump_is_never_drawn_as_the_cpu_fan(self):
        """`alpha`'s figure, the same trap: the pinned pump is named `CPU PUMP`."""
        only = {"fans": [{"onBoard": True, "type": "Pump", "name": "CPU PUMP", "value": 2410}]}
        both = {"fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 1990},
                         {"onBoard": True, "type": "Pump", "name": "CPU PUMP",
                          "value": 2410}]}
        self.assertEqual(render.cpu_fan_figure(only), "PUMP 2410 RPM",
                         "a pump-typed row was taken for the cooler's fan because its name "
                         "contains 'cpu'")
        self.assertEqual(render.cpu_fan_figure(both), "CPU FAN 1990 RPM",
                         "with a real fan row present the figure moved off it")


class ThePinTable(unittest.TestCase):
    """What `sensors.py` records, without needing this machine's chip to answer."""

    def test_exactly_one_channel_is_pinned_as_a_pump(self):
        pumps = [chan for (_chip, chan), (_name, kind) in sensors.FAN_CHANNELS.items()
                 if kind == "Pump"]
        self.assertEqual(len(pumps), 1,
                         f"{pumps}: two channels pinned as the pump is a name space with two "
                         "answers for one part")
        self.assertEqual(sensors.FAN_CHANNELS[("nct6687", pumps[0])][0], "CPU PUMP")

    def test_the_two_vendor_names_survive_the_repinn(self):
        """The 2026-11-06 pinning is the vendor's own `Fan CPU` / `Fan System 5`, taken out of
        its Windows log - a re-pin for a new part must not quietly rename those."""
        self.assertEqual(sensors.FAN_CHANNELS.get(("nct6687", "fan1")), ("Fan CPU", "Fan"))
        self.assertEqual(sensors.FAN_CHANNELS.get(("nct6687", "fan12")),
                         ("Fan System 5", "Chassis"))


    def test_a_row_can_be_gated_on_the_pump_existing(self):
        """`xigma.showIf` takes a source name, and until this change `Pump Speed` was not one.

        The use is a layout that labels the pump where a pump is sensed and carries no hole
        where it is not: the same object, two bodies, and the painter's own accounting says
        which way it went - a silenced row is reported (`showIf:Pump Speed`), never drawn.
        """
        obj = copy.deepcopy(themes.export("alpha"))
        obj["osd"]["widget"].append({
            "id": "pump-gate", "type": "text",
            "property": [{"x": 20, "y": 20, "content": "PUMP", "fontSize": 30,
                          "fontFamily": "verdana", "textColor": "rgba(255,255,255,1)",
                          "xigma": {"showIf": "Pump Speed"}}]})
        hard, soft = themes.validate(obj)
        self.assertEqual(hard, [])
        self.assertEqual([s for s in soft if "showIf" in s], [],
                         f"the validator does not know the name any more: {soft}")
        with_pump = copy.deepcopy(WITH_PUMP)
        a, na = themes.draw(obj, with_pump, fixtures.SESSION_WHEN)
        b, nb = themes.draw(obj, NO_PUMP, fixtures.SESSION_WHEN)
        self.assertEqual(len(na["boxes"]), len(nb["boxes"]) + 1,
                         f"gated row drawn {len(na['boxes'])}, undrawn {len(nb['boxes'])}")
        self.assertIn("showIf:Pump Speed", nb["missing"], nb["missing"])
        self.assertNotIn("showIf:Pump Speed", na["missing"], na["missing"])
        px = sum(1 for p in ImageChops.difference(a.convert("RGBA"), b.convert("RGBA"))
                 .get_flattened_data() if p != (0, 0, 0, 0))
        self.assertGreater(px, 0, "the gated row appeared in the notes and in no pixel")
        print(f"  the gated pump line is {px} px on this bench's faces")


class TheNineFiles(unittest.TestCase):
    """The library's side: exactly the nine files that ask for a pump change, and nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.pick = themes.scan()[0]

    def test_nine_files_gain_exactly_one_box_and_fourteen_gain_nothing(self):
        asked, gained, printed = [], [], []
        for rec in self.pick:
            if "Pump Speed" in sources_of(rec):
                asked.append(rec["name"])
            before, n_before = paint(rec, NO_PUMP)
            after, n_after = paint(rec, WITH_PUMP)
            changed = sum(1 for px in ImageChops.difference(after.convert("RGBA"),
                                                            before.convert("RGBA"))
                          .get_flattened_data() if px != (0, 0, 0, 0))
            delta = len(n_after["boxes"]) - len(n_before["boxes"])
            if delta:
                gained.append((rec["name"], delta, changed))
        self.assertEqual(len(asked), 9, sorted(asked))
        self.assertEqual(sorted(n for n, _d, _p in gained), sorted(asked),
                         "a file gained a box without asking for a pump, or one that asked "
                         f"gained nothing: {gained}")
        for name, delta, px in gained:
            self.assertEqual(delta, 1, f"{name} gained {delta} boxes for one pump row")
            self.assertGreater(px, 0, f"{name} gained a box and painted no pixel of it")
        # bench figure, printed rather than asserted: it is a face metric
        print(f"\n  pump row painted, this bench: {len(gained)} files, "
              + ", ".join(f"{n} +{p} px" for n, _d, p in gained))

    def test_the_pumpless_body_still_reports_the_widget_rather_than_losing_it(self):
        """The accounting identity: every widget is painted or named in the notes, before and
        after, so a row that cannot be answered is a reported skip and not a vanished widget."""
        for rec in self.pick[:8]:
            with self.subTest(layout=rec["name"]):
                for body in (NO_PUMP, WITH_PUMP):
                    _img, notes = paint(rec, body)
                    skipped = [m for m in notes["missing"] if not str(m).startswith("font:")]
                    self.assertEqual(len(notes["boxes"]) + len(skipped)
                                     + len([m for m in notes["missing"]
                                           if str(m).startswith("font:")]),
                                     rec["widgets"], notes["missing"])


class TheCLIDoor(unittest.TestCase):
    """`--list-themes` speaks about the readings it was handed, not about a constant."""

    #: A driver that swaps `sensors.collect` for a body handed in through the environment, so
    #: the CLI is asked the same question twice on one machine and the answer has to differ.
    #: Asserting this against this box's own sensors would pass whichever way the wiring went.
    DRIVER = ("import json, os;"
              "from xigmalcd import main, sensors;"
              "sensors.collect = lambda: json.loads(os.environ['XIGMA_TEST_BODY']);"
              "main.main(['--list-themes'])")

    def run_cli(self, body: dict) -> str:
        got = subprocess.run([sys.executable, "-c", self.DRIVER],
                             capture_output=True, text=True, timeout=180,
                             cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             env=dict(os.environ, QT_QPA_PLATFORM="offscreen",
                                      XIGMA_TEST_BODY=json.dumps(body)))
        return (got.stdout or "") + (got.stderr or "")

    def test_the_cli_refuses_the_pump_only_when_the_body_has_no_pump_row(self):
        """One subprocess, two bodies: a pumpless one must print the reason, and a body with a
        row typed `Pump` must stop printing it."""
        says_no = self.run_cli(fixtures.SESSION)
        self.assertIn("Pump Speed: 9 widget(s) ask for it and this machine cannot answer it",
                      says_no, says_no[:600])
        self.assertIn("fanscan", says_no, says_no[:600])
        says_yes = self.run_cli(dict(fixtures.SESSION,
                                     fans=[{"onBoard": True, "type": "Pump",
                                            "name": "CPU PUMP", "value": 2453}]))
        self.assertNotIn("Pump Speed: 9 widget(s)", says_yes,
                         f"a body that reports a pump row still told the reader it cannot: "
                         f"{says_yes[:600]}")


if __name__ == "__main__":
    unittest.main()
