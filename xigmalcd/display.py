"""display.py - the picture a person last chose, read by the loop at startup.

One small JSON file: which theme to draw, which background to store, how fast.  It exists
because those three decisions used to live in a **packaging file**.  The shipped user unit's
`ExecStart` said `--theme alpha --fps 2`, so what the panel showed at login was whatever the
.deb happened to ship, and changing it meant writing a systemd drop-in - a second place the
same decision had to be recorded, invisible to the window that made it.  The window already
knows what it sent to the glass; this is the part worth remembering across a reboot.

Three doors, one order, stated once and tested:

    an explicit command-line flag  >  this file  >  the code's own default

so `xigmalcd --theme gauge` still means gauge no matter what is saved here, and a machine
with no file at all boots exactly as it did before this module existed (alpha,
`media/Theme_25.mp4`, 1 fps - the vendor app's rate, which is what `--help` has always
promised and what the unit used to overrule).

Why a file of its own rather than reading the window's `~/.config/xigmaui/config.json`: that
file remembers how a *window* looked - splitter widths, the tray, the preview tick rate,
which of three panes had focus - and its `clip` key is an absolute path that
`xigmaui.settings._clean` drops when the file behind it is not on the machine.  A boot
background whose path lived on an unmounted Windows partition would quietly become
`Theme_25.mp4`, which is the right fallback for a preview and a wrong one for a device.  So
a clip in this file is a **bare name**, and the loop resolves it through
`main.media_roots()` - `$XIGMA_MEDIA`, the checkout, the .deb, the theme library - the same
order every other name in this program resolves in.

The writer is the window, and only the window: `xigmaui` calls `save()` at the moments a
person acts on the glass (`Apply these settings`, `Send this background to the panel`, and
the layout editor's `apply to the panel`).  Nothing here is written by the loop, and the
control socket never writes it either, so a scripted experiment - `tools/display_glass.py`
driving a panel for nine minutes - cannot decide what you see at your next login.  A test
holds that line: `tests/test_display_choice.py` runs the loop against a planted file and
fails if the bytes change.

Read with validation rather than trust, in the same shape `xigmaui.settings` uses: a
half-written file, a hand-edited file, and a file naming something this build cannot draw
all end with the loop starting and saying, in its log, which key it ignored and why.
"""
from __future__ import annotations

import json
import os

APP_DIR = "xigmalcd"
FILE_NAME = "display.json"

#: The keys that decide a boot, and nothing else.  `set_at` and `set_by` are provenance the
#: window writes for a human reader; the loop keeps them out of its decisions.
KEYS = ("theme", "clip", "fps")
META_KEYS = ("set_at", "set_by")


def path() -> str:
    """Where the file is, asked of the environment on every call.

    `XDG_CONFIG_HOME` is the only thing this resolves against, which is what lets the test
    suite read a planted file instead of a person's real one (`tests/fixtures.py` sets the
    variable at import, before any body runs, and `tests/test_zz_isolation.py` fails a run
    that writes outside it).  Never bind this at import time: `themes.user_root()` shows why
    - a module-level constant freezes the root the first caller happened to see.
    """
    root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(root, APP_DIR, FILE_NAME)


def _drawable(name: str) -> bool:
    """Can this build draw that name at all - code or library?

    The same test `--theme` applies on the command line, reached through the same doors:
    `render.THEMES` for a drawn theme, `themes.resolve` for a layout file this machine can
    select.  A saved name is held to the rule a typed name is, because a hand-edited file is
    not a different kind of input.
    """
    from . import render, themes
    if name in render.THEMES:
        return True
    try:
        return themes.resolve(name) is not None
    except OSError:                      # an unreadable library is not the file's fault
        return False


def clean(loaded, notes: list | None = None) -> dict:
    """Keep only what the loop could act on, and say out loud what it dropped.

    `notes` collects sentences for the caller to print - a silently ignored key is how a
    saved choice turns into a mystery, which is the failure this module has to be better than
    the file it replaces.  Nothing in here raises: a bad value costs its key, not the boot.
    """
    from . import control

    out: dict = {}
    if not isinstance(loaded, dict):
        if notes is not None:
            notes.append(f"{path()} holds {type(loaded).__name__}, not an object; "
                         "every key falls back")
        return out

    theme = loaded.get("theme")
    if isinstance(theme, str) and theme and os.path.basename(theme) == theme \
            and not theme.startswith("."):
        if _drawable(theme):
            out["theme"] = theme
        elif notes is not None:
            notes.append(f"saved theme {theme!r} is not one this build can draw "
                         f"(no drawn theme of that name and no selectable layout file); "
                         "ignored")
    elif theme is not None and notes is not None:
        notes.append(f"saved theme {theme!r} is not a bare theme name; ignored")

    clip = loaded.get("clip")
    if isinstance(clip, str) and clip and os.path.basename(clip) == clip \
            and not clip.startswith("."):
        if clip.lower().endswith(control.UPLOAD_SUFFIXES):
            out["clip"] = clip
        elif notes is not None:
            notes.append(f"saved background {clip!r} is not a file the media channel takes "
                         f"({'/'.join(control.UPLOAD_SUFFIXES)}); ignored")
    elif clip is not None and notes is not None:
        notes.append(f"saved background {clip!r} is not a bare file name; this file stores "
                     "names and resolves them through the media roots at startup")

    fps = loaded.get("fps")
    if fps is not None:
        lo, hi = control.FPS_RANGE
        try:
            want = float(fps)
        except (TypeError, ValueError):
            if notes is not None:
                notes.append(f"saved fps {fps!r} is not a number; ignored")
        else:
            if lo <= want <= hi:
                out["fps"] = want
            elif notes is not None:
                notes.append(f"saved fps {want} is outside {lo}-{hi}, the range the control "
                             "socket itself accepts; ignored")

    for key in META_KEYS:
        val = loaded.get(key)
        if isinstance(val, str) and val:
            out[key] = val
    return out


def load(notes: list | None = None) -> dict:
    """The saved choice, or {} if there is no usable one.

    Absent, unreadable and malformed all mean the same thing to the loop: nothing was
    chosen, so use the defaults - but not silently, which is what `notes` is for.
    """
    try:
        with open(path(), encoding="utf-8") as fh:
            return clean(json.load(fh), notes)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        if notes is not None:
            notes.append(f"{path()} could not be read as JSON ({exc.__class__.__name__}); "
                         "every key falls back to the program's default")
        return {}


def save(state: dict, notes: list | None = None) -> str | None:
    """Write the choice, atomically.  Called by the window and the installer, never the loop.

    Same shape as `xigmaui.settings.save`: a directory nobody else can read, a temporary
    file, and `os.replace` - so a crash leaves the previous choice intact instead of a
    truncated file that the next boot has to guess about.  Returns the path, or None when
    nothing survivable was in it.

    **"Nothing survivable" is a rule, not a courtesy.**  If every decision key was refused
    - a theme this build cannot draw, a rate outside the socket's own range - the write is
    refused entirely.  Provenance keys (`set_by`, `set_at`) are not a decision: a file
    holding only those reads, to the next start and to anyone who cats it, as though someone
    had chosen something.  Measured, not hypothesised: `XIGMALCD_THEME=theme_of_the_mountains
    install/install.sh` first left a `display.json` with `set_by`/`set_at` in it and no theme,
    which is a file that lies about being a choice.
    """
    want = clean({k: v for k, v in (state or {}).items() if k in KEYS or k in META_KEYS},
                 notes)
    if not any(key in want for key in KEYS):
        if notes is not None:
            notes.append(f"nothing usable was left of the choice being saved, so {path()} "
                         "was not written at all")
        return None
    where = path()
    try:
        os.makedirs(os.path.dirname(where), mode=0o700, exist_ok=True)
        tmp = where + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(want, fh, indent=1, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, where)
    except OSError:
        return None
    return where


def present() -> bool:
    """Is there a saved choice to read?  For reporting, not for decisions."""
    return os.path.isfile(path())
