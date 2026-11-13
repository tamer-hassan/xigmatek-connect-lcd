#!/usr/bin/env python3
"""audit_bare_runner.py - run every live-sensor test module with no hwmon chips to find.

This exists because six checks this session were wrong about the **machine** rather than the
code: a mount table that names `nvme0`, a `disk` section implying a `temperature` key, a drive
whose temperature holds still for the length of a function call (twice), a call named in a file
being a call that runs, and a probe check asserting its drive list was non-empty.  The last of
those is the one that settled the pattern: `tests/test_blob_probe.py`'s drive-row check was
identical in CI #193 (526 checks, OK, 431.661 s) and CI #194 (same 526, one failure,
460.878 s), and the only difference between those two commits is eight lines of
`debian/changelog` prose.  Some runner images publish a disk temperature chip, some do not.

So the question is not "did the runner go green" but "does this check depend on what the host
exposes at all".  Answering it for a whole suite is one pointer assignment: `sensors.HWMON_GLOB`
is the single place every hwmon walk goes through, so pointing it at a pattern that matches
nothing simulates a machine with no hardware-monitoring chips at all - a stricter box than any
CI runner, which usually has `coretemp`/`k10temp`/`nvme` present.

Which modules to walk is **derived**, not hand-kept: `live_test_modules()` parses every
`tests/test_*.py` and picks out the ones naming a live door, call or attribute - the latter
because `sensors.collect = lambda: body` is a module admitting it would otherwise read the
machine.  One tuple is kept by hand, `EXTRA_MODULES`, for the case the AST cannot see: a test
that runs a shipped CLI in a subprocess, where the live call happens in the child.
`tests/test_bare_audit.py` pins the finder itself - it writes a file that calls `sensors.disk()`
and requires the scan to notice it, which is the only way this list cannot rot.

    tools/audit_bare_runner.py            # the whole list
    tools/audit_bare_runner.py -v         # per-check names
    tools/audit_bare_runner.py tests.test_pump_speed   # one module

It opens no port, writes nothing outside a temporary directory, and never imports `xigmaui`
unless a listed module does.
"""
from __future__ import annotations

import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xigmalcd import sensors                                            # noqa: E402

#: A glob that matches no directory.  Not `/dev/null`: `glob()` returns [] for a missing path,
#: which is exactly the bare-machine case, and the pattern still has the `hwmon*` tail so a
#: reader can see what was replaced.
EMPTY_GLOB = "/no/such/hwmon*/hwmon*"

#: The doors that reach the machine rather than a fixture.  `hwmon()`, `temps()`,
#: `_chan_attrs()` and the rest are internal to these on every path a layout takes.
LIVE_DOORS = ("collect", "fans", "drives", "disk", "motherboard", "motherboard_answer",
              "disk_temperature", "board_channels")

#: Modules that touch a live door without naming it in an AST-visible way: `test_pump_speed`
#: runs `--list-themes` in a subprocess, which calls `sensors.collect()` inside the child.
#: Hand-kept, and `tests/test_bare_audit.py` checks each entry is still a real file.
EXTRA_MODULES = (
    "tests.test_pump_speed",
)


def live_test_modules(root: str | None = None) -> tuple:
    """Every `tests/test_*.py` that names a live sensor door, found through its AST.

    AST rather than grep because these very files quote `sensors.collect()` in their own
    explanations, and a prose match would be a list nobody can trust.  An attribute reference
    counts too, not only a call: `sensors.collect = lambda: body` is a module admitting it would
    otherwise read the machine, which is exactly what an audit of this class is for.
    """
    import ast
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = []
    for path in sorted(glob.glob(os.path.join(root, "tests", "test_*.py"))):
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        hit = False
        for node in ast.walk(tree):
            target = node.func if isinstance(node, ast.Call) else node
            if (isinstance(target, ast.Attribute) and target.attr in LIVE_DOORS
                    and isinstance(target.value, ast.Name) and target.value.id == "sensors"):
                hit = True
                break
        if hit:
            out.append("tests." + os.path.basename(path)[:-3])
    return tuple(out)


def modules() -> tuple:
    """Derived live readers plus the hand-kept ones, sorted and deduplicated."""
    return tuple(sorted(set(live_test_modules()) | set(EXTRA_MODULES)))


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in argv
    if verbose:
        argv = [a for a in argv if a != "-v"]
    walked = modules()
    wanted = tuple(argv) or walked
    unknown = [m for m in wanted if m not in walked]
    if unknown:
        print(f"not in the live-sensor list: {', '.join(unknown)}\n"
              f"the derived list is: {', '.join(walked)}")
        return 2

    real = sensors.HWMON_GLOB
    sensors.HWMON_GLOB = EMPTY_GLOB
    print(f"hwmon walk pointed at {EMPTY_GLOB!r}: "
          f"{len(sensors.hwmon())} chips visible, {len(sensors.fans())} fan rows, "
          f"motherboard() -> {sensors.motherboard()}, drives() -> {sensors.drives()}")
    try:
        loader = unittest.TestLoader()
        try:
            suite = loader.loadTestsFromNames(list(wanted))
        finally:
            # a module-level fixture that raised during import would otherwise be counted as a
            # test failure and read like a sensor fault; it is a fault in the audit
            errors = getattr(loader, "_errors", [])
            for e in errors:
                print(f"  import error: {e}")
        res = unittest.TextTestRunner(verbosity=2 if verbose else 1).run(suite)
    finally:
        sensors.HWMON_GLOB = real

    bad = len(res.failures) + len(res.errors)
    print(f"\nbare-runner audit: {res.testsRun} checks over {len(wanted)} modules, "
          f"{len(res.failures)} failures, {len(res.errors)} errors, "
          f"{len(res.skipped)} skipped")
    for t, _tb in res.failures + res.errors:
        print(f"  {t.id()}")
    print("\nA module that goes red here is asserting what the host exposes.  The repair is to"
          "\nconstruct the inputs (`make_tree` in tests/test_sensor_rules.py builds a sysfs) or"
          "\nto assert a relation instead of a reading.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
