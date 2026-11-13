#!/usr/bin/env python3
"""The probe tool's boundaries, gated without ever opening a port.

`tools/blob_probe.py` sends a `STATE all 1` body the panel has never seen, which is the only
way to answer the two questions waiting on it (an extra `drives` section, and a fan row typed
`Pump`).  Sending it once, by hand, with a human watching, is the right amount of nerve.
Everything that makes that safe is asserted here, against the file, without touching the port:

* **`--yes` is not decoration.** Without it the tool says what it would send and exits 2, and no
  device is opened - asserted by running it and reading what came back.
* **It will not take the port from a running display.** Exactly one process may hold it
  (PROTOCOL.md §1). With the service reported active, `--yes` still exits 2, and the refusal
  names the order that is safe. This is gated by *stubbing the answer*, so it holds on a machine
  where no display is running - including CI's runner.
* **No destructive or firmware topic appears anywhere it could be sent.** The topics are listed
  in `FORBIDDEN_TOPICS` and the check reads this tool's own AST: every string that reaches a
  call is compared against that list, and every request verb it uses is named. A docstring may
  mention `recovery` to explain why it is refused; a call may not.
* **The panel's serial is not printed.** `device_info()` answers a dict containing `sn`, and a
  transcript of this probe is the kind of file that ends up quoted in a document. Only
  `PRINTED_KEYS` is echoed, `sn` is not in it, and that is asserted.

The bodies themselves are checked as data: the control differs from the pump body by exactly one
fan row, the extra-section body by exactly one key, and the second control is the first one.

And the payload has to be the one that **ships**: `drive_rows()` is gated to call
`sensors.drives()` rather than assemble rows of its own, because the second probe run answered
`200` for a section the tool had built itself - `0.1` degrees, unsorted - while the shipped door
rounded to whole degrees and sorted by controller.  A verdict about a body nobody sends is not a
verdict about the body that goes out.
"""
from __future__ import annotations

import ast
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from tests import fixtures
from tests.test_sensor_rules import (DRIVE_KEYS, DRIVE_SLOTS, DRIVE_TEMPS,
                                    make_tree)   # one built sysfs, shared by both files
from xigmalcd import sensors, themes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(ROOT, "tools", "blob_probe.py")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

def source_calls() -> list:
    """(called-name, string argument) for every call in the tool's source that takes one."""
    with io.open(TOOL, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return [(fn, lit) for fn, lit in _names_and_strings(tree) if lit is not None]


def calls_inside(function_name: str) -> set:
    """Every call made inside the named top-level function, as dotted names.

    Used to bind `drive_rows()` to the shipped door: a function that re-derives the rows
    passes every data check, because its rows look right - which is exactly how the flawed
    run looked right too.
    """
    with io.open(TOOL, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    fn = next((n for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == function_name), None)
    if fn is None:
        return set()
    out = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                base = f.value.id if isinstance(f.value, ast.Name) else type(f.value).__name__
                out.add(f"{base}.{f.attr}")
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def source_call_names() -> set:
    """Every name called anywhere in the tool, with or without arguments."""
    with io.open(TOOL, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    return {fn for fn, _lit in _names_and_strings(tree)}


def frame_guards() -> list:
    """The `if` blocks whose test mentions `skip_frame` and whose body uploads a frame.

    Written because the first version of the check asked only whether `upload_a_frame` was
    called *somewhere* in the file, and a mutation of the guard to `if False:` kept the name and
    passed: a control that can never run is not a control.
    """
    with io.open(TOOL, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        names = ({n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
                 | {n.attr for n in ast.walk(node.test) if isinstance(n, ast.Attribute)})
        if "skip_frame" not in names:
            continue
        if any(isinstance(c, ast.Call)
               and (isinstance(c.func, ast.Name) and c.func.id == "upload_a_frame"
                    or isinstance(c.func, ast.Attribute) and c.func.attr == "upload_a_frame")
               for c in ast.walk(node)):
            found.append(node)
    return found


def _names_and_strings(tree) -> list:
    out = []
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            args = list(node.args) + [kw.value for kw in node.keywords]
            strings = [a.value for a in args
                       if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            out.append((name, strings[0] if strings else None))
    return out


blob_probe = importlib.import_module("blob_probe")


class TheDryRun(unittest.TestCase):
    def run_tool(self, *argv: str) -> tuple:
        got = subprocess.run([sys.executable, TOOL, *argv], capture_output=True, text=True,
                             timeout=180, cwd=ROOT,
                             env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        return got.returncode, (got.stdout or "") + (got.stderr or "")

    def test_without_yes_it_names_the_bodies_and_opens_nothing(self):
        code, out = self.run_tool()
        self.assertEqual(code, 2, out[:400])
        self.assertIn("nothing was opened", out, out[:400])
        for needle in ("a fan row typed Pump", "an extra section", "drives"):
            self.assertIn(needle, out, f"{needle!r} is not in the plan the dry run prints")
        self.assertNotIn("opening /dev", out, "the dry run opened a port")

    def test_the_plan_promises_the_frame_control_too(self):
        """The end control is not an extra: without it five `200`s prove nothing.

        The first version of this file had no check that noticed when that control was
        removed - a mutation of `if not a.skip_frame:` to `if False` passed all twelve - which
        is how I found the gap: a probe that reports only acks can be run by someone who never
        sees that the acks were the weak half of the measurement.
        """
        code, out = self.run_tool()
        self.assertEqual(code, 2)
        low = out.lower()
        self.assertIn("frame control", low, out[:600])
        self.assertIn("send_media", low, "the dry run does not say how the frame is sent")
        names = source_call_names()
        self.assertIn("upload_a_frame", names,
                      f"the run path never calls the frame control: {sorted(names)}")
        # ... and it must be called *behind the flag*, not anywhere: `if False:` would keep the
        # name in the file while never running it, which is the mutation that first slipped by.
        guards = frame_guards()
        self.assertTrue(guards,
                        "no `if not a.skip_frame:` block calls the frame control, so the "
                        "control is either unconditional or dead")

    def test_every_planned_body_states_what_it_changes(self):
        code, out = self.run_tool()
        self.assertEqual(code, 2)
        self.assertGreaterEqual(out.count("change:"), 5,
                                "a body was printed without its delta, so a reader cannot see "
                                "what is unusual about it")


class ThePortBoundary(unittest.TestCase):
    def test_it_refuses_while_the_display_service_holds_the_port(self):
        """Stubbed, so this check means the same on a runner with no panel as on this bench."""
        real = blob_probe.service_active
        blob_probe.service_active = lambda *a, **kw: True
        try:
            buf = io.StringIO()
            argv = sys.argv
            sys.argv = ["blob_probe.py", "--yes", "--device",
                        os.path.exists(blob_probe.DEFAULT_DEVICE) and blob_probe.DEFAULT_DEVICE
                        or "/dev/null"]
            try:
                with redirect_stdout(buf), redirect_stderr_holder() as err:
                    code = blob_probe.main()
            finally:
                sys.argv = argv
                blob_probe.service_active = real
        except Exception as exc:                                    # noqa: BLE001
            self.fail(f"the refusal path raised instead of refusing: {exc}")
        out = buf.getvalue() + err.getvalue()
        self.assertEqual(code, 2, out[:400])
        self.assertIn("one opener", out.lower(), out[:400])
        self.assertNotIn("answer:", out, "it probed anyway")

    def test_a_missing_device_is_refused_before_anything_else(self):
        real = blob_probe.service_active
        blob_probe.service_active = lambda *a, **kw: False
        try:
            buf = io.StringIO()
            argv = sys.argv
            sys.argv = ["blob_probe.py", "--yes", "--device", "/no/such/port"]
            try:
                with redirect_stdout(buf), redirect_stderr_holder() as err:
                    code = blob_probe.main()
            finally:
                sys.argv = argv
        finally:
            blob_probe.service_active = real
        out = buf.getvalue() + err.getvalue()
        self.assertEqual(code, 2, out[:300])
        self.assertIn("no device", out.lower(), out[:300])
        self.assertNotIn("answer:", out, "it probed a port that does not exist")


class TheTopicBoundary(unittest.TestCase):
    """Read the tool's own AST: what it asks for, and what it never could."""


    def test_no_forbidden_topic_reaches_a_call(self):
        bad = [(fn, lit) for fn, lit in source_calls()
               if any(lit == t or lit.startswith(f"{t} ") or f" {t} " in lit
                      for t in blob_probe.FORBIDDEN_TOPICS)]
        self.assertEqual(bad, [],
                         f"the probe would send {bad}; the topics it refuses are "
                         f"{blob_probe.FORBIDDEN_TOPICS}")

    def test_the_only_requests_it_makes_are_the_ones_it_documents(self):
        # only protocol calls: `dict.get("fans")` is not a verb the panel sees
        verbs = {lit for fn, lit in source_calls() if fn in ("request", "post")}
        self.assertTrue(verbs <= {"STATE all 1", "conn", "hello"},
                        f"unexpected verbs: {verbs}")

    def test_the_panel_serial_is_never_echoed(self):
        self.assertNotIn("sn", blob_probe.PRINTED_KEYS,
                         "`sn` is in the keys the tool prints, which puts the panel's serial "
                         "into a transcript")
        with io.open(TOOL, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("for k in PRINTED_KEYS", src,
                      "show_state no longer filters what it echoes")


class TheBodies(unittest.TestCase):
    """The five payloads, as data - what makes each one unusual has to be exactly one thing."""

    def setUp(self):
        self.planned = blob_probe.bodies()

    def test_there_are_five_and_the_controls_are_identical(self):
        self.assertEqual(len(self.planned), 5)
        first, last = self.planned[0][1], self.planned[4][1]
        self.assertEqual(sorted(first), sorted(last))
        self.assertEqual(first.get("fans"), last.get("fans"))

    def test_the_pump_body_differs_by_exactly_one_row_and_one_value(self):
        base = self.planned[0][1].get("fans") or []
        pump = self.planned[1][1].get("fans") or []
        self.assertEqual(len(pump), len(base) + 1)
        added = [f for f in pump if f not in base]
        self.assertEqual(len(added), 1, f"more than one row was added: {added}")
        self.assertEqual(added[0]["type"], "Pump")
        self.assertEqual(sorted(self.planned[0][1]), sorted(self.planned[1][1]),
                         "the pump body changed a top-level key as well, so the two questions "
                         "would be answered at once and mean nothing")

    def test_the_control_carries_no_Pump_string_at_all(self):
        """The isolation gate, added because the first version of this tool failed it.

        `sensors.collect()` on this box already returns a fan row typed `Pump` - the channel
        pinned on 2026-11-13 - so the control body and the experiment body both contained the
        value under test, and the pair could not have distinguished anything.  The control is
        normalised to the two values the vendor's captures spell, and this is what keeps that
        from quietly reversing itself if `collect()` changes again.
        """
        import json
        base = json.dumps(self.planned[0][1], default=str)
        self.assertNotIn("Pump", base,
                         "the control body carries the value the experiment is asking about, so "
                         "the two answers cannot be compared")
        types = {f.get("type") for f in (self.planned[0][1].get("fans") or [])}
        self.assertTrue(types <= {"Fan", "Chassis"},
                        f"the control's fan rows use {types}; only the vendor's two values may "
                        f"appear there")
        # and the experiment must be the *only* place the value appears
        pump = json.dumps(self.planned[1][1], default=str)
        self.assertIn("Pump", pump, "the experiment body no longer contains the value")
        self.assertEqual(pump.count("Pump"), 1,
                         f"the value appears {pump.count('Pump')} times in the experiment body")

    def test_the_drives_body_adds_exactly_one_key(self):
        base = sorted(self.planned[0][1])
        drives = sorted(self.planned[2][1])
        self.assertEqual(set(drives) - set(base), {"drives"})
        self.assertEqual(set(base) - set(drives), set())

    def test_the_both_body_carries_exactly_the_two_changes(self):
        both = self.planned[3][1]
        self.assertIn("drives", both)
        self.assertEqual([f for f in (both.get("fans") or []) if f.get("type") == "Pump"],
                         [f for f in (self.planned[1][1].get("fans") or [])
                          if f.get("type") == "Pump"])

    def test_the_control_body_carries_neither_value_under_test(self):
        """The isolation gate for **both** questions, because I got this wrong once already.

        The first version stripped the `Pump` type from the control and forgot that
        `sensors.collect()` had, by then, grown a `drives` section of its own - so the control
        and the extra-section experiment differed only by ordering, and the pair could not have
        answered the question.  A control has to be built from the vendor's shape, not from
        whatever the current build happens to send.
        """
        import json
        base = self.planned[0][1]
        self.assertNotIn("drives", base,
                         "the control already carries the section the experiment adds")
        self.assertNotIn("Pump", json.dumps(base, default=str),
                         "the control already carries the Pump type the experiment adds")
        both = json.dumps(self.planned[3][1], default=str)
        self.assertIn("drives", both, "the combined body lost one of the two changes")
        self.assertEqual(both.count("Pump"), 1,
                         f"the value under test appears {both.count('Pump')} times: {both[:200]}")

    def test_a_drive_row_says_what_the_scalar_says(self):
        """The row's shape, on a **built** tree - because on the host it was a coin flip.

        This check used to read this machine and assert the list was not empty, and the runner
        proved that wrong in both directions with identical code: #193 ran 526 checks green in
        431.661 s, #194 ran the same 526 to **one failure** in 460.878 s, and the whole diff
        between those two commits is 8 lines of `debian/changelog` prose
        (`git diff --stat e69c5d7 61b1d6a`).  Some runner images expose a disk temperature chip
        and some do not, so the pass meant nothing either time - `AssertionError: [] is not
        true : this machine publishes no disk temperatures at all`.  The built tree answers the
        same question about the payload without depending on whose VM it is.
        """
        tmp = tempfile.TemporaryDirectory(prefix="xigma-probe-rows-")
        pattern = make_tree(tmp.name)
        real_glob = sensors.HWMON_GLOB
        sensors.HWMON_GLOB = pattern
        try:
            rows = blob_probe.drive_rows()
        finally:
            sensors.HWMON_GLOB = real_glob
            tmp.cleanup()
        self.assertEqual([r["name"] for r in rows], list(DRIVE_SLOTS),
                         f"the payload is not the shipped list: {rows}")
        self.assertEqual([r["temperature"] for r in rows], list(DRIVE_TEMPS),
                         f"a row's number is not the composite-or-hottest rule: {rows}")
        for r in rows:
            self.assertEqual(sorted(r), list(DRIVE_KEYS),
                             f"a key appeared in the certified payload: {r}")
            self.assertTrue(0 < r["temperature"] < 120,
                            f"not degrees: {r} - a millidegree leak would print 41850")
        self.assertGreater(max(rows[0]["sensors"]), rows[0]["temperature"],
                           f"the row hides the hotter raw probe it exists to show: {rows[0]}")


class TheShippedDoor(unittest.TestCase):
    """The `drives` payload the panel answered for must be the payload that ships.

    `data/glass/2026-11-13-184215-blob-probe.txt` is the record of the alternative: the tool
    built its own rows (`0.1` degrees, in walk order) while `sensors.drives()` shipped whole
    degrees sorted by controller.  Every data check in this file passed on that payload, so the
    only way to catch it is to bind the probe to the door.
    """

    def test_drive_rows_is_a_call_to_the_shipped_door_not_a_copy_of_it(self):
        made = calls_inside("drive_rows")
        self.assertIn("sensors.drives", made,
                      f"`drive_rows()` builds its rows from {sorted(made)}; it must call "
                      f"`sensors.drives()`, the door the layouts and the loop both read")
        self.assertFalse({c for c in made if c.endswith("_disk_channels")},
                         f"the probe reaches under the door again: {sorted(made)}")

    def test_the_probe_rows_are_the_shipped_rows_on_a_built_tree(self):
        """One tree, both doors, and the tree is built so a wrong answer is **visible**.

        The obvious version of this check - `drive_rows() == sensors.drives()` on the machine
        running it - failed in the full suite forty seconds after it passed standalone, with
        `sensors: [44, 59, 68]` against `[44, 58, 68]`: the probe read sysfs twice, a few
        hundred milliseconds apart, and the drive warmed by a degree between the reads.  That
        is the same fault this very session recorded as `38 != 39`, re-committed by me in new
        code, so the comparison is done against a constructed tree instead of against a
        drive's current temperature.

        The built tree is not decorative either: its `nvme2` lives in `hwmon7`, first in walk
        order at 55 °C, while the controller order the shipped door applies puts it third.  A
        `drive_rows()` that re-derived rows from the walk - which is what the second probe run
        actually sent to the panel - differs from `sensors.drives()` here and fails.
        """
        tmp = tempfile.TemporaryDirectory(prefix="xigma-probe-")
        pattern = make_tree(tmp.name)
        real_glob = sensors.HWMON_GLOB
        sensors.HWMON_GLOB = pattern
        try:
            rows = blob_probe.drive_rows()
            self.assertEqual(rows, sensors.drives(),
                             "the probe's `drives` payload is not the shipped one, so a `200` "
                             "answers a body nobody sends")
            self.assertEqual([r["name"] for r in rows], list(DRIVE_SLOTS),
                             f"rows came back in walk order: {[r['name'] for r in rows]}")
            self.assertEqual([r["temperature"] for r in rows], list(DRIVE_TEMPS),
                             f"the per-drive rule is not the one _drive_choice applies: {rows}")
            self.assertEqual(sorted(rows[0]), list(DRIVE_KEYS),
                             f"a key appeared in the certified payload: {rows[0]}")
            # the slots and the payload are one list, not two readings of it
            vals, _absent = themes.values({"drives": rows}, fixtures.SESSION_WHEN)
            self.assertEqual(vals.get("Disk 1 Temperature"), DRIVE_TEMPS[0],
                             vals.get("Disk 1 Temperature"))
            self.assertEqual(vals.get("Disk 1 Name"), DRIVE_SLOTS[0])
            self.assertEqual(vals.get("Disk 3 Name"), DRIVE_SLOTS[2],
                             "slot 3 is not the third controller; the ordering above is "
                             "cosmetic and would not survive a boot")
        finally:
            sensors.HWMON_GLOB = real_glob
            tmp.cleanup()

    def test_the_live_relation_holds_under_one_snapshot_of_sysfs(self):
        """The same relation on this machine's real sensors, read **once**.

        Kept because the built tree cannot show what the hardware publishes - and done with
        `sensors._read` cached, so the answer cannot depend on what the drives are doing
        during the check.
        """
        real_read = sensors._read
        cache: dict = {}

        def snapshot(path):
            if path not in cache:
                cache[path] = real_read(path)
            return cache[path]

        sensors._read = snapshot
        try:
            rows = blob_probe.drive_rows()
            self.assertEqual(rows, sensors.drives(),
                             "the probe and the shipped door disagree about this machine")
            if rows:
                vals, _absent = themes.values({"drives": rows}, fixtures.SESSION_WHEN)
                self.assertEqual(vals.get("Disk 1 Temperature"), rows[0]["temperature"],
                                 "the first slot does not read the first shipped row")
                self.assertEqual(vals.get("Disk 1 Name"), rows[0]["name"])
        finally:
            sensors._read = real_read

class redirect_stderr_holder:
    """A tiny stderr buffer that works as a context manager alongside redirect_stdout."""

    def __enter__(self):
        self.buf = io.StringIO()
        self.real = sys.stderr
        sys.stderr = self.buf
        return self.buf

    def __exit__(self, *exc):
        sys.stderr = self.real
        return False


if __name__ == "__main__":
    unittest.main()
