#!/usr/bin/env python3
"""The pieces every check in `tests/` needs, kept in one place.

Ported from `tools/selftest.sh`, whose 13,869 lines built these same fixtures again in each of
its 22 sections.  Four things matter here, and all four are safety rather than convenience:

* the repo root is derived from this file, so a check runs the same from any working directory -
  the old suite relied on being started from the top of the tree;
* `QT_QPA_PLATFORM=offscreen` is set before anything imports Qt, because a GUI check that opens a
  real window on someone's desktop is a different kind of failure;
* the metrics below are **pinned**, and so is the clock: `render._now` and
  `edit.FIXTURE_WHEN` are the only instants a drawing claim can be re-made at.  A check that
  compares two frames drawn a second apart is a check of the wall clock, and one such race was
  measured at 772 differing bytes out of 921,600 before it was pinned;
* no `Panel` in these helpers ever reaches a port.  `StubPanel` records what would have been sent
  and sends nothing; `send` is deliberately absent.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import hashlib                                              # noqa: E402
import shutil                                               # noqa: E402
import subprocess                                           # noqa: E402
import tempfile                                             # noqa: E402

from PIL import Image, ImageChops                           # noqa: E402

# ---- isolation, done once, for the whole process -------------------------------------------------
#
# `tools/selftest.sh` set these three per section, in bash, and its closing guard compared the
# sha256 of `~/.config/xigmaui/config.json` against a baseline taken before it started - because
# in 0.4 a section really did write the author's settings.  Setting them here, at import, means a
# test cannot forget to: `settings.path()` and `themes.user_root()` both read the environment, so
# every window and every save in this package lands in a temporary root that outlives the process.
#
# `XIGMA_SOCKET` points at a path that does not exist.  The window asks for a display through that
# socket before it would ask for a port, so a nonexistent socket is what keeps a GUI check from
# reaching for /dev/ttyACM0 on a bench that has a panel attached.
ISOLATED = tempfile.mkdtemp(prefix="xigma-tests-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(ISOLATED, "config")
os.environ["XIGMA_SOCKET"] = os.path.join(ISOLATED, "no-display.sock")

#: The real settings file, as this process found it.  `test_zz_isolation.py` re-reads it at the
#: end and fails on any difference, which is the guard the old suite closed with.
REAL_CONFIG = os.path.expanduser("~/.config/xigmaui/config.json")


def config_fingerprint() -> str:
    """sha256 of the real settings file, or the string 'absent' when there is none."""
    try:
        with open(REAL_CONFIG, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except FileNotFoundError:
        return "absent"


BASELINE_CONFIG = config_fingerprint()

#: Optional external programs.  Each check that needs one says so out loud rather than measuring a
#: zero and calling it a result - the old suite's worst near-miss was `measure` returning 0.0 luma
#: because ffmpeg was missing, which looked like a changed clip and was an absent decoder.
HAVE = {name: bool(shutil.which(name))
        for name in ("ffmpeg", "ffprobe", "tesseract", "desktop-file-validate",
                     "dpkg-parsechangelog", "git")}


def need(*what: str) -> None:
    """Skip the calling test unless every named program is on this machine."""
    gone = [w for w in what if not HAVE.get(w)]
    if gone:
        raise unittest.SkipTest("not installed here: " + ", ".join(gone)
                                + " - the check that needs it is skipped, not silently passed")


def tracked(*patterns: str) -> list:
    """The repository's own file list, as git knows it.

    "Published" means tracked, not "present in this working tree".  A bench that has just run
    `dpkg-buildpackage` also has `debian/xigmatek-connect-lcd.substvars` and six neighbours, so a
    check that reads what happens to be on disk counts different files on different machines -
    104 here, 97 on CI, for one example the old suite hit.  The list the repository ships is the
    list the rule is about, and it is the same on every machine.
    """
    got = subprocess.run(["git", "ls-files", *patterns], capture_output=True, text=True,
                         check=True, cwd=REPO)
    return sorted(n for n in set(got.stdout.split())
                  if os.path.isfile(os.path.join(REPO, n)))


def read(path: str) -> str:
    """One repository file, as text, named from the top of the tree."""
    with open(os.path.join(REPO, path), encoding="utf-8") as fh:
        return fh.read()


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*argv: str, cwd: str = REPO, env: dict | None = None):
    """One subprocess, with stdout and stderr kept together and no shell in between."""
    whole = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable if a == "python" else a for a in argv],
                          capture_output=True, text=True, cwd=cwd, env=whole)

#: One body of readings, used by every drawing check.  Pinned because the machine's own sensors
#: answer different numbers on a runner (no `gpu` section, no tachometer) and those gaps would be
#: a second thing under test.
METRICS = {
    "cpu": {"temperature": 41.6, "load": 7.4},
    "gpu": {"temperature": 38.0, "load": 12.0},
    "memory": {"used": 8283746304, "total": 33554432000},
    "motherboard": {"temperature": 32.0},
    "fans": [],
}

#: One instant, as both shapes the painters take it: `time.struct_time` for `render._now`,
#: `datetime` for `themes.draw` / `layout.draw_theme`.
WHEN = time.strptime("2026-11-05 09:31:03", "%Y-%m-%d %H:%M:%S")
WHEN_DT = datetime.datetime(*WHEN[:6])

THEMES = ("gauge", "dual", "clock", "bars", "alpha")


def as_datetime(st: time.struct_time) -> datetime.datetime:
    return datetime.datetime(*st[:6])


# ---- the pinned bodies the library and encoder checks draw with -----------------------------------
#
# Not one dict but four, because they answer different questions and each is pinned to the shape it
# was measured in.  `METRICS` above is a Linux box's readings.  These are the shapes the Windows
# sessions recorded, and the copied layouts were drawn against those:

#: The encoder's loss budget is counted on an alpha overlay frame with these readings, which are the
#: ones the captured wire traffic carried.
CAPTURED = {"cpu": {"temperature": 57.0, "load": 42.0},
            "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
            "fans": [{"name": "Fan CPU", "type": "Fan", "value": 1957}]}

#: The 23 copied layouts are painted with a body that has a network section and memory as a
#: percentage, at this instant.
SESSION = {"cpu": {"temperature": 61, "load": 42, "power": 88.5, "speedAverage": 4338},
           "gpu": {"temperature": 55, "load": 63, "power": 37.0, "speed": 1500},
           "network": {"upload": 12.3, "download": 45.6}, "memory": {"load": 7}}
SESSION_WHEN = datetime.datetime(2026, 11, 8, 3, 40, 0)

#: Five bodies for the export-vs-code parity probe.  The first two answer every source every export
#: asks for - which, once `bars` was exported, means a board temperature, a GPU memory pair and
#: **four fan rows**, because `bars` reserves four slots and a box reporting one fan leaves three
#: unanswered by construction.  The last three deliberately do not.  Both complete readings sit at
#: the ends of every scale: 100 degrees, 0 % load, 12 345 RPM on a 0..3000 meter.
PARITY_CASES = ({"cpu": {"temperature": 57, "load": 62},
                 "gpu": {"temperature": 47, "load": 22, "memoryUsage": 2_100_000,
                         "dedicatedTotal": 8_000_000},
                 "motherboard": {"temperature": 41},
                 "memory": {"used": 4_200_000, "total": 16_000_000},
                 "fans": [{"value": 1957, "name": "Fan CPU"},
                          {"value": 1102, "name": "Fan System 5"},
                          {"value": 800, "name": "Fan Pump"},
                          {"value": 640, "name": "Fan Chassis 2"}]},
                {"cpu": {"temperature": 100, "load": 0},
                 "gpu": {"temperature": 100, "load": 0, "memoryUsage": 0,
                         "dedicatedTotal": 8_000_000},
                 "motherboard": {"temperature": 0},
                 "memory": {"used": 0, "total": 16_000_000},
                 "fans": [{"value": 12345, "name": "Fan CPU"}, {"value": 0, "name": "Fan System 5"},
                          {"value": 1, "name": "Fan Pump"}, {"value": 3000,
                                                             "name": "Fan Chassis 2"}]},
                {"cpu": {"temperature": 24}},
                {"cpu": {"temperature": 40}, "gpu": {"temperature": 55}},
                {})


def freeze_clock(render):
    """Put `render._now` on the pinned instant, and hand back the hook it replaced.

    Every class that pins the clock puts the hook back in `tearDownClass`: a later file that asks
    "does this picture move when the second changes?" needs the real one, and a pin that outlives
    its own file turns that question into a false answer.
    """
    previous = render._now
    render._now = lambda: WHEN
    return previous


def count_opaque(img: Image.Image) -> dict:
    """Opaque-ish pixels of a frame, tallied by exact colour.

    `get_flattened_data()` is the fast path on the PIL this package installs; the older spelling
    is kept because a check that cannot run is worse than one that runs slowly.
    """
    flat = img.convert("RGBA")
    rows = (flat.get_flattened_data() if hasattr(flat, "get_flattened_data") else list(flat))
    out: dict = {}
    for p in rows:
        if p[3] > 240:
            out[p] = out.get(p, 0) + 1
    return out


def differ(a: Image.Image, b: Image.Image) -> tuple:
    """(pixels that disagree in any channel, worst single-channel delta) - the pair every
    pixel-comparing check in this package answers with, so a "the same picture" claim always
    carries both halves of that sentence."""
    src = ImageChops.difference(a.convert("RGBA"), b.convert("RGBA"))
    flat = src.get_flattened_data() if hasattr(src, "get_flattened_data") else list(src)
    return (sum(1 for q in flat if q != (0, 0, 0, 0)),
            max((max(q) for q in flat), default=0))


_QAPP = None


def qapp():
    """One `QApplication` for the whole process, on the offscreen platform.

    `QT_QPA_PLATFORM=offscreen` is set at the top of this module, before anything imports Qt, so a
    GUI check cannot open a window on someone's desktop.  One application object per process matters
    for the same reason Qt says it does: two of them is undefined behaviour, and a test file that
    made its own would leave the next file holding a dead one.
    """
    global _QAPP
    if _QAPP is None:
        from PyQt6.QtWidgets import QApplication
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def pump(seconds: float = 0.05) -> None:
    """Run the event loop for a while.

    Qt's own signals are asynchronous - a debounced settings write, a repaint, a worker's log line -
    so a check that reads a value straight after setting it reads the world before the signal ran.
    The old suite used deadline loops for exactly this, and the one it got wrong (waiting for one
    field instead of the whole state) is why a settings round trip once passed on a bench and failed
    on a runner.
    """
    app = qapp()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def close_window(win) -> None:
    """Stop a window's timers and its panel thread, so a later check is not reading a moving picture.

    Leaving a live `panel.Panel` thread running is how one section's stub became another's, and the
    window's own save timer is how a check writes a settings file nobody asked it to.
    """
    for name in ("preview_timer", "thumb_timer", "save_timer", "poll_timer"):
        timer = getattr(win, name, None)
        if timer is not None:
            timer.stop()
    worker = getattr(win, "panel", None)
    if worker is not None:
        try:
            worker.stop()
            worker.wait(3000)
        except RuntimeError:
            pass                        # the thread never started, which is its own answer
    win.close()


class FreshConfigRoot(unittest.TestCase):
    """A base class that gives each test its own empty settings and theme-copy root.

    The process-wide isolation in this module is what stops a check writing the real
    `~/.config/xigmaui/config.json`; this is what stops two checks reading *each other*.  Both
    matter: `settings.load()` after a save, and `themes.user_copies()` after a rename, are only
    meaningful if the root they look in is empty before the test starts.  `themes.user_root()`
    binds at import, so the environment is set here - before any test body, and therefore before
    the first call - and `XDG_CONFIG_HOME` is the only thing either module reads.
    """

    def setUp(self) -> None:
        self._was_config = os.environ.get("XDG_CONFIG_HOME")
        self.config_root = tempfile.mkdtemp(prefix="xigma-cfg-")
        os.environ["XDG_CONFIG_HOME"] = self.config_root

    def tearDown(self) -> None:
        if self._was_config is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._was_config
        shutil.rmtree(self.config_root, ignore_errors=True)


class StubPanel:
    """A panel that writes down what it was asked for and sends nothing anywhere.

    The old suite had this in three sections under three names; one is enough, and its shape is
    the point: `sent` is a list, there is no `send` that could reach a device, and
    `opened` stays `False` because nothing in this package constructs a serial connection.
    """

    def __init__(self) -> None:
        self.sent: list = []
        self.opened = False

    def hello(self):
        self.sent.append(("hello", None))
        return {"notice": "200", "space": 62416}

    def send_frame(self, blob: bytes, **kw):
        self.sent.append(("frame", len(blob)))
        return "200"

    def send_media(self, path: str, **kw):
        self.sent.append(("media", os.path.basename(path)))
        return "200"

    def close(self) -> None:
        self.sent.append(("close", None))

    def kinds(self) -> dict:
        """How many of each thing was recorded - the count every wire-discipline check reads."""
        out: dict = {}
        for kind, _ in self.sent:
            out[kind] = out.get(kind, 0) + 1
        return out
