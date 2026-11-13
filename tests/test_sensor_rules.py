#!/usr/bin/env python3
"""Which sensor answers which field - gated against a **built** hwmon tree, not this box.

Written on 2026-11-13 after measuring two fields that had been answering from the wrong place:

* `motherboard.temperature` came out **45-50 °C from `r8169`**, a Realtek network controller,
  because `temps()` was handed a flat list of chips and the code took the `max()` of that list.
  This board's Super-IO - `nct6687`, bound by `nct6683` - publishes a thermal diode and three
  thermistors at **40.5-49.0 °C** and was not in the list at all, and its hottest channel is
  `AMD TSI Addr 98h` at **62-70 °C**, which is the CPU and must never win a row that says
  `Motherboard`.  The vendor's own captured body has `motherboard:{"temperature":38}` beside
  `cpu:{"temperature":57}`: a board number well under the CPU's, which is the shape the tiers
  reproduce and the NIC never did.
* `disk.temperature` came out **31 °C** - the *minimum* over six sensors on two drives - while
  the same blob reports `total` and `used` from the one drive that holds `/`, and the hottest
  sensor on the machine was **67.85 °C**.  So the capacity was `nvme0`'s and the temperature was
  `nvme1`'s, picked because it was the coolest number on the box.

Both rules are gated here on a **constructed** tree, because a CI runner has no NCT6687D, no
DDR5 SPD hubs and sometimes no NVMe at all: the rules are about *selection*, and a check that
asked this machine what it found would pass on one box and mean nothing on another.
`sensors.HWMON_GLOB` is a module-level name rather than a literal inside the loop for exactly
that reason, and `disk_temperature()` takes the controller as an argument for the same one.

The third thing under test is quieter and was latent rather than visible: `hwmon()` sorted
`/sys/class/hwmon/hw*` as **text**, so this boot walked `hwmon0, hwmon1, hwmon10, hwmon11,
hwmon2, hwmon3…` - the Super-IO behind a Wi-Fi card and a GPU.  Today one chip owns the tach
inputs, so nothing on the glass depends on it yet; the moment a second chip reports a fan,
`Fan 1` would be chosen by digit count.
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest

from xigmalcd import layout, sensors, themes

#: The built tree's answers, spelled out because every one of them is a choice the code makes.
SUPERIO_BOARD_MAX = 42      # nct6687's hottest non-CPU channel, 41.5 °C, rounded up
SPD_MAX = 51                # spd5118 hwmon6 at 51.0 - hotter than the NIC, and still a tier 2
NIC = 50                    # r8169 at 50.0 - not the board, whatever its number says
TSI = 67                    # AMD TSI Addr 98h: the CPU, in the same chip


def make_tree(root: str) -> str:
    """A sysfs-shaped hwmon set: a Super-IO, a NIC, four SPD hubs, three NVMe drives, a GPU.

    Values are millidegrees and RPM as the kernel publishes them.  Each nvme hwmon directory
    gets a `device` link the way the real one does, because matching a mount point to a chip
    depends on it.  Returns the glob that walks the tree.
    """
    def chip(name: str, files: dict) -> str:
        path = os.path.join(root, name)
        os.makedirs(path, exist_ok=True)
        for fname, val in files.items():
            with open(os.path.join(path, fname), "w", encoding="utf-8") as fh:
                fh.write(f"{val}\n")
        return path

    chip("hwmon1", {                       # this board's Super-IO: labels its temps, never its
        "name": "nct6687",                 # fans, which is why the fan rules live elsewhere
        "temp1_input": TSI * 1000, "temp1_label": "AMD TSI Addr 98h",
        "temp2_input": 40500, "temp2_label": "Diode 0 (curr)",
        "temp3_input": 41000, "temp3_label": "Thermistor 15",
        "temp4_input": 40500, "temp4_label": "Thermistor 1",
        "temp5_input": 41500, "temp5_label": "Thermistor 15",
        "fan1_input": 1724, "fan2_input": 2453, "fan12_input": 0,
        "pwm1": 182, "pwm2": 182, "pwm3": 0, "pwm4": 153,
    })
    chip("hwmon2", {"name": "r8169_0_b00:00", "temp1_input": NIC * 1000})
    for i in (3, 4, 5, 6):
        chip(f"hwmon{i}", {"name": "spd5118", "temp1_input": 45000 + 1000 * i})
    ctrl = os.path.join(root, "devices", "nvme")
    os.makedirs(ctrl, exist_ok=True)
    drives = {                             # composite and raw sensors, deliberately disagreeing
        "nvme0": {"temp1_input": 41850, "temp1_label": "Composite",
                  "temp2_input": 67850, "temp2_label": "Sensor 2"},
        "nvme1": {"temp1_input": 31850, "temp1_label": "Composite",
                  "temp2_input": 32850, "temp2_label": "Sensor 1"},
        "nvme2": {"temp1_input": 55000, "temp1_label": "Sensor 1"},   # publishes no Composite
    }
    for n, (hw, rows) in enumerate(drives.items(), start=7):
        path = chip(f"hwmon{n}", dict(rows, name="nvme"))
        os.makedirs(os.path.join(ctrl, hw), exist_ok=True)
        os.symlink(os.path.join(ctrl, hw), os.path.join(path, "device"))
    chip("hwmon10", {"name": "amdgpu", "temp1_input": 44000, "temp1_label": "edge"})
    chip("hwmon11", {"name": "k10temp", "temp1_input": 68000, "temp1_label": "Tctl"})
    return os.path.join(root, "hwmon*")


class Built(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="xigma-hwmon-")
        pattern = make_tree(self.tmp.name)
        self.real_glob = sensors.HWMON_GLOB
        sensors.HWMON_GLOB = pattern

    def tearDown(self):
        sensors.HWMON_GLOB = self.real_glob
        self.tmp.cleanup()


class ABoardSensor(Built):
    """Which channel stands for the board, and which never may."""

    def test_the_superio_answers_and_the_nic_does_not(self):
        won = sensors.motherboard_answer()
        self.assertIsNotNone(won, "nothing answered from the built tree")
        chip, label, _val = won
        self.assertEqual(chip, "nct6687",
                         f"the board number came from {chip} [{label}]: a network controller is "
                         "not what a row saying `Motherboard` means")
        self.assertEqual(sensors.motherboard(), {"temperature": SUPERIO_BOARD_MAX},
                         f"expected the Super-IO's hottest board channel "
                         f"({SUPERIO_BOARD_MAX}), got {sensors.motherboard()}")
        # and the point of the tier at all: the answer is *cooler* than the NIC it replaced
        self.assertLess(sensors.motherboard()["temperature"], NIC)

    def test_a_channel_labelling_a_processor_is_never_a_board_candidate(self):
        """The driver labels its temperatures even though it labels no tachometer, and that
        label is the only thing separating the CPU's TSI from the board's own sensors."""
        labels = {label for _c, label, _v in sensors.board_channels()}
        self.assertNotIn("AMD TSI Addr 98h", labels,
                         "the CPU's TSI channel is in the board candidate list: taking the max "
                         f"would print {TSI} °C under the word motherboard")
        self.assertIn("Diode 0 (curr)", labels)
        hottest = max(v for _c, _l, v in sensors.board_channels())
        self.assertLess(hottest, TSI * 1000,
                        "the exclusion did not bite: a candidate is hotter than the CPU channel")

    def test_the_nic_answers_only_when_nothing_else_can(self):
        real = (sensors.BOARD_CHIPS, sensors.DIMM_CHIPS)
        try:
            sensors.BOARD_CHIPS, sensors.DIMM_CHIPS = ("nosuchchip",), ("nosuchchip",)
            won = sensors.motherboard_answer()
            self.assertEqual(won[0], "r8169_0_b00:00",
                             f"with no Super-IO and no SPD hub the fallback should be the NIC, "
                             f"got {won}")
            self.assertEqual(sensors.motherboard(), {"temperature": NIC})
            sensors.BOARD_CHIPS = real[0]
            self.assertEqual(sensors.motherboard_answer()[0], "nct6687",
                             "the tiers did not put the Super-IO back in front of the NIC")
        finally:
            sensors.BOARD_CHIPS, sensors.DIMM_CHIPS = real

    def test_the_dimm_thermistors_are_a_tier_and_not_a_second_voice(self):
        """`spd5118` answers `memory.temperature` as well; a box with a Super-IO must not print
        one die under two field names."""
        dimm = sensors.board_channels(*sensors.DIMM_CHIPS)
        self.assertEqual(len(dimm), 4, f"the built tree should offer four SPD channels: {dimm}")
        self.assertEqual(sensors.motherboard()["temperature"], SUPERIO_BOARD_MAX,
                         "the SPD tier answered while a Super-IO was present")
        real = sensors.BOARD_CHIPS
        try:
            sensors.BOARD_CHIPS = ("nosuchchip",)
            self.assertEqual(sensors.motherboard()["temperature"], SPD_MAX,
                             "with no Super-IO the DIMM thermistors should answer before the "
                             "NIC does")
        finally:
            sensors.BOARD_CHIPS = real

    def test_the_cpu_and_gpu_chips_are_not_board_candidates_at_all(self):
        """k10temp and amdgpu sit in the same directories the board walk visits, and their
        channels are the CPU's and the card's - `NOT_THE_BOARD` is the only thing keeping them
        out of a `max()` that takes the hottest candidate."""
        labels = {label for _c, label, _v in sensors.board_channels("k10temp", "amdgpu")}
        self.assertEqual(labels, set(),
                         f"the board walk accepted {labels} from the CPU and GPU chips: their "
                         "own labels (Tctl, edge) are what keeps them out of a max() that "
                         "otherwise takes the hottest candidate")


class AFanOrder(Built):
    """The chip walk, which decides what `Fan 1` means the day a second chip reports a tach."""

    def test_devices_are_walked_by_number_not_by_digit_count(self):
        order = [os.path.basename(p) for _c, p in sensors.hwmon()]
        self.assertEqual(order, sorted(order, key=lambda s: int(s[5:])),
                         f"hwmon() walked {order}: a text sort puts `hwmon10` before `hwmon2`, "
                         "and an order a reader cannot predict is an order no page can describe")

    def test_the_two_live_tach_channels_come_back_named(self):
        rows = sensors.fans()
        self.assertEqual([(r["name"], r["type"], r["value"]) for r in rows],
                         [("Fan CPU", "Fan", 1724), ("CPU PUMP", "Pump", 2453)],
                         f"the built channels came back as {rows}")
        self.assertNotIn("Fan System 5", [r["name"] for r in rows],
                         "a channel reading 0 RPM was reported as a running fan")


class ADiskSensor(Built):
    """The drive whose capacity is reported is the drive whose temperature is reported."""

    def test_the_root_drives_composite_answers(self):
        deg, whence = sensors.disk_temperature(root="nvme0")
        self.assertEqual(deg, 42, f"nvme0's composite is 41.85 and the answer was {deg}: "
                                  f"{whence}")
        self.assertIn("composite", whence.lower(), whence)
        self.assertNotEqual(deg, 68, "the raw NAND sensor on the same drive was reported as the "
                                     "drive's temperature; the drive's own aggregate is 41.85")

    def test_a_different_drive_gives_a_different_answer(self):
        """The rule follows the mount; it does not always say the same number."""
        a, _wa = sensors.disk_temperature(root="nvme0")
        b, _wb = sensors.disk_temperature(root="nvme1")
        self.assertNotEqual(a, b, "both drives answered the same number, so nothing here shows "
                                  "the root match doing any work")
        self.assertEqual(b, 32)

    def test_a_drive_publishing_no_composite_uses_its_hottest_sensor(self):
        deg, whence = sensors.disk_temperature(root="nvme2")
        self.assertEqual(deg, 55, whence)
        self.assertIn("no composite", whence.lower(), whence)

    def test_the_fallback_is_the_hottest_reading_not_the_coolest_number(self):
        deg, whence = sensors.disk_temperature(root="")
        self.assertEqual(deg, 55, f"an unmatchable mount point must not fall back to a minimum:"
                                  f" {whence}")
        self.assertIn("hottest", whence.lower(), whence)

    def test_the_blob_gains_no_key_the_vendor_does_not_document(self):
        """A new source name must not widen the `STATE all 1` body.

        `_root_controller()` is pointed at one of the built drives here, and that is not
        tidiness: the first version of this check let `collect()` ask the *host's* mount table
        while the drives under test were synthetic, and it failed on CI's runner on 2026-11-13
        (`55 != 42`) because no runner mounts `/` on `nvme0`-as-here.  A check that reads the
        machine it runs on, in order to test a tree it built, is testing the machine.
        """
        real_root = sensors._root_controller
        sensors._root_controller = lambda: "nvme0"
        try:
            body = sensors.collect()
        finally:
            sensors._root_controller = real_root
        for section in ("cpu", "disk", "fans", "memory", "motherboard", "timestamp"):
            self.assertIn(section, body, f"the built tree lost the {section!r} section")
        self.assertEqual(body["disk"]["temperature"], 42, "disk() did not use the new rule")
        self.assertEqual(body["motherboard"]["temperature"], SUPERIO_BOARD_MAX,
                         "motherboard() did not use the tier rule")
        # `network` and `gpu` are legitimately absent on some machines (the vendor's own bodies
        # drop whole sections), so what is gated here is that nothing *extra* appears.
        documented = {"network", "memory", "cpu", "gpu", "disk", "fans", "motherboard",
                      "timestamp"}
        self.assertLessEqual(set(body), documented,
                             f"the blob grew keys the vendor never documented: "
                             f"{sorted(set(body) - documented)}")

class TheSameDoor(unittest.TestCase):
    """No synthetic tree: on whatever machine this runs, the blob and the rule must agree.

    This is the check that would have caught the one that failed on CI's runner - not by
    pinning a number, which is what went wrong first time, but by asserting a *relation*
    between what `collect()` puts on the wire and what `disk_temperature()` reports about it.
    """

    def test_disk_and_motherboard_come_from_the_same_doors_the_pages_quote(self):
        deg, whence = sensors.disk_temperature()
        body = sensors.collect()
        if "disk" in body:
            self.assertEqual(body["disk"]["temperature"], deg,
                             f"the blob says {body['disk']['temperature']} and the rule says "
                             f"{deg} ({whence})")
        won = sensors.motherboard_answer()
        if won is not None:
            self.assertEqual(body.get("motherboard", {}).get("temperature"),
                             sensors.motherboard()["temperature"],
                             "the wire and `motherboard()` disagree")
            self.assertGreaterEqual(
                sensors.motherboard()["temperature"], 0,
                "a board answer that is not a temperature")
        if "fans" in body:
            self.assertEqual([f["name"] for f in body["fans"]],
                             [f["name"] for f in sensors.fans()],
                             "the fans in the blob are not the fans `fans()` reports")


class TheNameIsOurs(unittest.TestCase):
    """`Disk Temperature`: a name this program answers, spelled like the other two temps."""

    def test_the_source_has_a_rule_a_shape_and_no_shipped_layout_asking_for_it(self):
        self.assertIn("Disk Temperature", themes.SOURCES)
        self.assertIn("Disk Temperature", themes.source_names())
        self.assertIn("Disk Temperature", layout.VENDOR_FORMAT)
        self.assertNotIn("Disk Temperature", layout.FORMATS_MEASURED,
                         "the shape is ours - it is not measured off the vendor's picture, and "
                         "`formats_measured()` is what tells --list-themes so")
        used = themes.sources_used(themes.scan()[0])
        self.assertNotIn("Disk Temperature", used,
                         "a shipped layout now asks this name, and the census in "
                         "tests/test_theme_library.py has to change with it")

    def test_a_row_naming_it_paints_a_number(self):
        """The name answers, the shape exists, and the box appears - with one trap noted.

        The row carries a `fontFamily` on purpose: a `text`/`data` row without one is dropped
        by the face probe (`font:` in the notes, with nothing after the colon), which is the
        second time in this sitting that a probe of mine looked like a broken rule when the
        row I built was the thing that could not draw.
        """
        obj = copy.deepcopy(themes.export("clock"))
        obj["osd"]["widget"].append({
            "id": "disk-temp-check", "type": "data",
            "property": [{"x": 10, "y": 10, "source": "Disk Temperature", "fontSize": 30,
                          "fontFamily": "verdana", "textColor": "rgba(255,255,255,1)"}]})
        hard, soft = themes.validate(obj)
        self.assertEqual(hard, [])
        self.assertEqual([s for s in soft if "Disk Temperature" in s], [], soft)
        _plain, plain_notes = themes.draw(themes.export("clock"), {"disk": {"temperature": 45}},
                                          None)
        _img, notes = themes.draw(obj, {"disk": {"temperature": 45}}, None)
        painted = {(b[0], b[1]) for b in notes["boxes"]}
        self.assertIn(("data", "Disk Temperature"), painted,
                      f"the row did not paint: {sorted(painted)} / {notes['missing']}")
        self.assertNotIn("Disk Temperature", notes["missing"], notes["missing"])
        self.assertEqual(len(notes["boxes"]), len(plain_notes["boxes"]) + 1,
                         f"the row drew {len(notes['boxes'])} boxes against "
                         f"{len(plain_notes['boxes'])} without it")


if __name__ == "__main__":
    unittest.main()
