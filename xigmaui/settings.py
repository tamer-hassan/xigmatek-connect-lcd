"""settings.py - what the window remembers between runs.

One small JSON file in the XDG config dir, written atomically, and read back
with validation rather than trust: every value is checked against the range the
widget accepts, and a clip path that no longer exists (the Windows partition is
not always mounted) falls back to the daemon's default background rather than
drawing a blank preview.

Nothing here decides a wire rule. What is stored is only what the window would
have looked like: port, theme, clock size, canvas, scrim, fan figures, preview
rate, whether closing the window hides it to the tray, and the clip that was
selected. The panel itself is never asked what it remembers, because it cannot
be (PROTOCOL.md §11).
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

APP = "xigmaui"
# where the file lives, and what each key may be
DEFAULTS: dict = {
    "device": "/dev/ttyACM0",
    "theme": "alpha",
    "clock_size": 30,          # pixels, 16-96: the theme's own default is 26
    "canvas": "clear",         # or "black"
    "scrim": -1,               # -1 = the daemon's luma rule
    "fans": True,
    "preview_fps": 2.0,        # host-side only; a frame renders in ~9 ms
    "size": [1000, 620],       # the window as you left it
    "tray": True,              # close hides it to the tray; False quits on close
}


def path() -> str:
    root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(root, APP, "config.json")


def _clip_default() -> str:
    from xigmalcd.main import DEFAULT_MP4
    return DEFAULT_MP4


def _clean(loaded: dict) -> dict:
    """Keep only values the widgets would actually accept."""
    from xigmalcd import render

    out = dict(DEFAULTS)
    out["clip"] = _clip_default()
    if not isinstance(loaded, dict):
        return out
    if isinstance(loaded.get("device"), str) and loaded["device"]:
        out["device"] = loaded["device"]
    if loaded.get("theme") in render.THEMES:
        out["theme"] = loaded["theme"]
    for key, lo, hi in (("clock_size", 16, 96), ("scrim", -1, 255)):
        try:
            n = int(loaded[key])
            if lo <= n <= hi:
                out[key] = n
        except (KeyError, TypeError, ValueError):
            pass
    if loaded.get("canvas") in ("clear", "black"):
        out["canvas"] = loaded["canvas"]
    if isinstance(loaded.get("fans"), bool):
        out["fans"] = loaded["fans"]
    if isinstance(loaded.get("tray"), bool):
        out["tray"] = loaded["tray"]
    try:
        fps = float(loaded["preview_fps"])
        if 0.5 <= fps <= 10:
            out["preview_fps"] = fps
    except (KeyError, TypeError, ValueError):
        pass
    size = loaded.get("size")
    # only a size we could actually draw into: a 1x1 window remembered from a
    # broken layout is worse than the default
    if (isinstance(size, (list, tuple)) and len(size) == 2
            and all(isinstance(n, (int, float)) and 400 <= n <= 8000 for n in size)):
        out["size"] = [int(n) for n in size]
    clip = loaded.get("clip")
    if isinstance(clip, str) and os.path.isfile(clip):
        # DEFAULT_MP4 is built relative to the module, so it arrives as
        # `.../xigmalcd/../media/Theme_25.mp4`; a file you might edit by hand
        # should read as one clean path
        out["clip"] = os.path.normpath(clip)
    return out


def load() -> dict:
    """The saved window state, or the defaults if there is no usable file."""
    try:
        with open(path(), encoding="utf-8") as fh:
            return _clean(json.load(fh))
    except FileNotFoundError:
        return _clean({})
    except (OSError, ValueError):
        # a half-written or hand-edited file is not a reason not to start
        return _clean({})


def save(state: dict) -> str | None:
    """Write the state. Returns the path, or None if the disk said no."""
    want = _clean(state)
    where = path()
    try:
        os.makedirs(os.path.dirname(where), mode=0o700, exist_ok=True)
        tmp = where + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(want, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, where)          # atomic: a crash cannot truncate it
        return where
    except OSError:
        return None
