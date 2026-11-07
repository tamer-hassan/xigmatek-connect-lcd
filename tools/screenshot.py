#!/usr/bin/env python3
"""Regenerate docs/screenshot-xigmaui.png: the real window, captured offscreen.

The README's five `docs/preview-*.png` files are what the *panel* draws - one frame
from each theme, composited the way the glass composites (`tools/previews.py`).  This
is the picture of the *window*: the same Qt application a reader gets from `xigmaui`,
with its theme picker, its preview, its clip library and its status box, exactly as it
lays itself out on first run.

It is generated, not retouched, and the path it takes is the one `tools/selftest.sh`
takes for its GUI section, so the window is a real one:

* `QT_QPA_PLATFORM=offscreen` - no display server needed, and the capture cannot end
  up in someone's face;
* `XDG_CONFIG_HOME` in a temporary directory - the run writes no settings file, and no
  remembered window size or clip choice sneaks into the picture (`restore=False`, which
  is `--fresh`);
* `XIGMA_SOCKET` pointed at a path with nothing listening - with no display running the
  window is its own boss, which is the mode a reader sees on first run;
* `Window(port=...)` on a path that **does not exist**, and a refusal to run if it does:
  in this mode the window's own status action opens the serial port, and a screenshot
  must not be the thing that takes someone's panel over mid-session or draws on the
  glass.  The default is `/dev/xigmatek-lcd`, the name this project's own udev rule
  makes - the path the README tells a user to run - and here there is no panel behind
  it, so the log box holds one honest failure line.

Everything the picture shows is therefore measured: the preview is `render.draw`'s
output over the first frame of `media/Theme_25.mp4` with this machine's live sensor
readings, and the clip rows are the files `xigmaui/clips.py` actually finds, with the
thumbnails ffmpeg actually decodes.  The numbers in it belong to the machine that ran
this script; that is why nothing in the README quotes them.

    tools/screenshot.py                     # writes docs/screenshot-xigmaui.png
    tools/screenshot.py --device PATH -o OUT
    tools/screenshot.py --keep-thumbnails N

`--seconds N` bounds how long the event loop is pumped: thumbnails arrive one batch per
timer tick and they are the slow part of a first paint, so the loop is run until N rows
have icons or the budget runs out.

`--size WxH` (default 1380x860) resizes the window before the grab.  That is a framing
choice, not a claim about a fixed layout: the window's own fresh default is
`settings.DEFAULTS["size"]` - quoted in docs/tools.md and checked against that constant by
the suite, so neither sentence can go stale - and the window is resizable.  1380x860 is what
puts the three columns side by side with six rows of the clip list in frame, which is the
point of the picture; the suite checks the column rules themselves (docs/gui.md).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time

DEFAULT_DEVICE = "/dev/xigmatek-lcd"
DEFAULT_OUT = os.path.join("docs", "screenshot-xigmaui.png")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device", default=DEFAULT_DEVICE,
                    help=f"port path the window names (default {DEFAULT_DEVICE}); it "
                         "must not exist, because in this mode the window would open it")
    ap.add_argument("-o", "--out", default=DEFAULT_OUT, help="where to write the PNG")
    ap.add_argument("--size", default="1380x860", metavar="WxH",
                    help="resize the window to this before grabbing it (default "
                         "1380x860, what the README's picture uses: the three "
                         "columns side by side with six rows of the clip list). "
                         "The window's own fresh default is settings.DEFAULTS"
                         "['size'] and the window is resizable, so this is a "
                         "framing choice, not a claim about a fixed layout)")
    ap.add_argument("--seconds", type=float, default=14.0,
                    help="how long to pump the event loop for thumbnails")
    ap.add_argument("--keep-thumbnails", type=int, default=26,
                    help="stop early once this many clip rows have an icon (and "
                         "so a measured size and loop length): enough that every "
                         "row inside the captured frame carries numbers instead "
                         "of `size ? loop ?`, which was true of most of the "
                         "visible list at the old default of 14")
    ap.add_argument("--allow-port", action="store_true",
                    help="run even if --device exists (draws on real glass; say so)")
    a = ap.parse_args()

    if os.path.exists(a.device) and not a.allow_port:
        print(f"{a.device} exists: this window would open it for its own status read, "
              f"and a screenshot is not the time.\nPoint --device at a path that is "
              f"not there, or pass --allow-port if you mean it.", file=sys.stderr)
        return 2

    # Set before QApplication: the offscreen platform and the settings root are both
    # read at that point, and a stray config file would change the window's size.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    tmp = tempfile.mkdtemp(prefix="xigma-shot-")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
    os.environ["XIGMA_SOCKET"] = os.path.join(tmp, "no-display.sock")
    os.environ.pop("DISPLAY", None)          # nothing here may use a real session

    from PyQt6.QtWidgets import QApplication

    # The checkout's own code, not whatever is installed on this machine: a script run
    # as `python3 tools/screenshot.py` starts with tools/ on sys.path, and on a box that
    # has the .deb installed `import xigmaui` would then silently draw the picture from
    # /usr/lib/python3/dist-packages.  That is exactly what happened on the first run of
    # this tool - 158 clip rows, the installed 0.1's realpath-only dedup, where the tree
    # here gives 69 - and a screenshot of old code is not evidence about this code.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)

    app = QApplication([])
    from xigmaui import app as gui

    print(f"  code              {os.path.dirname(gui.__file__)}")

    win = gui.Window(a.device, 2.0, restore=False, tray=False)
    # framed for the reader, then shown: the left column is capped at the picture's
    # own width (xigmaui/app.py), so everything a wider window buys goes to the
    # controls, which is the point of asking for a larger size here
    try:
        wide, tall = (int(x) for x in a.size.lower().replace("*", "x").split("x"))
        assert wide >= 560 and tall >= 480
    except (TypeError, ValueError, AssertionError):
        print(f"--size {a.size!r}: needs WxH with W >= 560 and H >= 480, which is "
              f"what the two columns need to be readable at all", file=sys.stderr)
        return 2
    win.resize(wide, tall)
    win.show()
    t0 = time.monotonic()
    while time.monotonic() - t0 < a.seconds or len(win.all_clips) - len(
            getattr(win, "_pending", [])) < a.keep_thumbnails:
        app.processEvents()
        pending = getattr(win, "_pending", [])
        if len(win.all_clips) - len(pending) >= a.keep_thumbnails:
            break
    # and every row the frame can actually show carries its numbers: the probe
    # pass is one clip per timer tick by design (115 ffmpeg seeks is 12.7 s on this
    # box and the rows below the fold are not the rows you are looking at), which
    # in a picture means a third of the visible list still reads `size ?  loop ?`.
    # So the visible rows are finished before the grab, through the window's own
    # batching, and nothing else about the lazy pass changes.
    from xigmaui import clips as clipdb
    row_h = win.clips.visualItemRect(win.clips.item(0)).height() or 1
    shown = min(len(win.all_clips), win.clips.viewport().height() // row_h + 1)
    win._pending = [i for i in range(shown)
                    if not win.all_clips[i].px[0]] + list(win._pending)
    for _ in range(shown):
        if not win._pending:
            break
        win._thumb_batch()
        app.processEvents()
    done = len(win.all_clips) - len(getattr(win, "_pending", []))
    pm = win.grab()
    pm.save(a.out, "PNG")
    print(f"  window            {len(win.all_clips)} clip rows, {done} with an icon")
    print(f"  pixmap            {pm.width()}x{pm.height()} -> {a.out}")

    # what the picture is made of, so the caption in the README can be checked against
    # something rather than taken on trust
    try:
        out = subprocess.run(["identify", "-format", "%wx%h %m %B bytes\n", a.out],
                             capture_output=True, text=True)
        report = out.stdout.strip()
    except FileNotFoundError:               # ImageMagick is not a dependency
        from PIL import Image
        im = Image.open(a.out)
        report = (f"{im.size[0]}x{im.size[1]} {im.format} {os.path.getsize(a.out)} B "
                  f"(Pillow; `identify` not installed here)")
    print(f"  file              {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
