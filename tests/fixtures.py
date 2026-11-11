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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from PIL import Image, ImageChops                           # noqa: E402

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


def freeze_clock(render) -> None:
    """Put `render._now` on the pinned instant, for the duration of one process."""
    render._now = lambda: WHEN


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
