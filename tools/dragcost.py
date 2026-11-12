#!/usr/bin/env python3
"""Measure what a drag inside the layout editor's pane costs, on the box running it.

Complaints about this window are usually about feel, and feel is not a constant: the
same act has cost 108 ms and 11 ms on the same machine, depending on what else the event
loop had queued.  So this prints the numbers rather than arguing about them, and it
prints them *split by the call that pays*, because the three things that made a drag
slow were none of them the picture:

* `themes.keys_read()` deriving the readable-field set from `layout.py`'s source - read
  off disk, compiled, walked as ~29 000 AST nodes - once for `move_to` and twice per
  `set`, so five parses per mouse-move event;
* the clip library's thumbnail pass (`thumb_timer`, interval 0, `ffprobe` plus `ffmpeg`
  per clip) holding the event loop while the pointer is in it;
* a `--preview-fps` tick landing mid-drag, repainting a layer the pointer had just drawn
  and reading this machine's sensors to do it.

What it drives is the shipped door, not a copy: a real `xigmaui` window, a real
`QMouseEvent` press/move/release sequence handed to the preview pane's own handlers, and
the row moving through `Editor.move_to`.  The counts it prints (source reads, subprocess
spawns, thumbnail probes, paints) are what `tests/test_canvas.py` asserts, so a figure
here and a check there are the same statement about the same code.

Two safety doors, both of them the same reasoning as `tools/screenshot.py`:

* **`--device` must not exist** unless `--allow-port` is given.  In this mode the window's
  own status action opens the serial port, so a measurement on a bench with a panel
  attached would visit the panel; this tool never sends a frame, and says so.
* **the settings root is always a temporary one.**  `--session` copies this user's saved
  `config.json` - the window size, split, clip, canvas and `preview_fps` they actually
  run with - into a temp `XDG_CONFIG_HOME` and restores *that*, so the measurement sees a
  real session and cannot write to the real settings file.

By default the window is built offscreen, the way `tests/test_window.py` builds one.  The
complaint this tool exists for is about *feel* on a desktop, and offscreen Qt never hands
a pixel to a compositor, so `--on-display` measures the real thing instead: a window
appears on the reader's screen for the few seconds the drags take, and the two numbers
belong to different questions, which is why the tool prints which one it is answering.

Durations belong to a box, so every number here is printed with the box beside it and
nothing is written into a page by this tool.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

MISSING_DEVICE = "/dev/xigma-no-such-port"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device", default=None, metavar="PATH",
                    help=f"port path the window names (default {MISSING_DEVICE}, which "
                         "must not exist).  With --allow-port, the port from --session's "
                         "config is used instead.")
    ap.add_argument("--allow-port", action="store_true",
                    help="let the window open a real port for its own status read, the "
                         "way `xigmaui` does.  This tool sends no frame; a live display "
                         "may still be holding the port.")
    ap.add_argument("--session", action="store_true",
                    help="restore this user's saved config (copied to a temporary "
                         "settings root), so the window is the size, split, clip and "
                         "fps they actually run with")
    ap.add_argument("--layout", default="bars", metavar="NAME",
                    help="which layout to open in the editor (default bars)")
    ap.add_argument("--row", type=int, default=-1, metavar="N",
                    help="which row of that file to drag (default: the first row the "
                         "painter draws ink for)")
    ap.add_argument("--moves", type=int, default=30, help="pointer moves per drag (default 30)")
    ap.add_argument("--drags", type=int, default=3,
                    help="drags to run, so the first one - the one that lands while the "
                         "library is still probing clips - can be told from the rest")
    ap.add_argument("--playing", choices=("on", "off"), default="off",
                    help="whether `playing` is on (default off: the complaint that "
                         "brought this tool was about a drag with nothing animating)")
    ap.add_argument("--on-display", action="store_true",
                    help="draw on the real desktop instead of offscreen.  This is the "
                         "number a reader feels - Qt handing pixels to a compositor is a "
                         "cost the offscreen platform does not have - and a window will "
                         "appear on screen for the few seconds the drags take")
    ap.add_argument("--timer", choices=("on", "off"), default="on",
                    help="whether the `--preview-fps` timer runs (default on, as in a "
                         "session: a tick that lands mid-drag is part of the feel)")
    ap.add_argument("--dx", type=int, default=1, help="px per move, the pointer's stride")
    ap.add_argument("--profile", action="store_true",
                    help="also run the moves under cProfile and print the top frames by "
                         "time in this package")
    ap.add_argument("--no-breakdown", action="store_true",
                    help="skip the per-call timing (the wrappers are the only thing here "
                         "that adds to what is being measured)")
    a = ap.parse_args()

    if a.moves < 2 or a.drags < 1:
        print("--moves needs at least 2 and --drags at least 1: one move of one drag "
              "measures a single call, not a drag", file=sys.stderr)
        return 2

    # The port first, before Qt or a settings root: on a bench where this project's udev
    # rule is installed, /dev/xigmatek-lcd exists and the default is not enough.
    device = a.device
    if device is None:
        device = MISSING_DEVICE
    if a.allow_port and a.device is None and a.session:
        try:
            with open(os.path.join(os.environ.get("XDG_CONFIG_HOME",
                                                  os.path.expanduser("~/.config")),
                                   "xigmaui", "config.json")) as handle:
                device = json.load(handle).get("device") or MISSING_DEVICE
        except (OSError, ValueError):
            pass
    if os.path.exists(device) and not a.allow_port:
        print(f"{device} exists: this window would open it for its own status read, and a "
              f"measurement is not the time.\nPoint --device at a path that is not there, "
              f"or pass --allow-port if you mean it.", file=sys.stderr)
        return 2

    platform_note = "offscreen (no display server, nothing appears on anyone's screen)"
    if a.on_display:
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            print("--on-display asks for the real desktop and this shell has neither "
                  "DISPLAY nor WAYLAND_DISPLAY; drop the switch to measure offscreen",
                  file=sys.stderr)
            return 2
        platform_note = ("the real desktop (a window will appear while this runs: "
                         f"DISPLAY={os.environ.get('DISPLAY', '-')} "
                         f"WAYLAND={os.environ.get('WAYLAND_DISPLAY', '-')})")
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    real_root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    tmp = tempfile.mkdtemp(prefix="xigma-drag-")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
    os.environ["XIGMA_SOCKET"] = os.path.join(tmp, "no-display.sock")
    if a.session:
        real = os.path.join(real_root, "xigmaui")
        if os.path.isdir(real):
            os.makedirs(os.path.join(os.environ["XDG_CONFIG_HOME"], "xigmaui"),
                        exist_ok=True)
            for name in os.listdir(real):
                shutil.copy(os.path.join(real, name),
                            os.path.join(os.environ["XDG_CONFIG_HOME"], "xigmaui", name))
    if not a.allow_port:
        # a restored config names the machine's real port; the window would open it
        cfg = os.path.join(os.environ["XDG_CONFIG_HOME"], "xigmaui", "config.json")
        if os.path.exists(cfg):
            try:
                with open(cfg) as handle:
                    body = json.load(handle)
                body["device"] = device
                with open(cfg, "w") as handle:
                    json.dump(body, handle, indent=1)
            except (OSError, ValueError) as exc:
                print(f"could not rewrite the copied config: {exc}", file=sys.stderr)
                return 2

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)

    from PyQt6.QtWidgets import QApplication
    app_q = QApplication([])
    from PyQt6.QtCore import (PYQT_VERSION_STR, QT_VERSION_STR, QEvent, QPointF, Qt)
    from PyQt6.QtGui import QMouseEvent
    from xigmalcd import render, themes
    from xigmaui import app as gui

    port_note = ("  (opened for a status read: this tool sends no frame)"
                 if a.allow_port else "")
    root_note = ("  (a copy of the saved session)" if a.session
                 else "  (fresh: the window as a first run shows it)")
    print(f"  box             {os.uname().sysname} {os.uname().machine}, python "
          f"{sys.version.split()[0]}, PyQt {PYQT_VERSION_STR}, Qt {QT_VERSION_STR}, Pillow "
          f"{__import__('PIL').__version__}")
    print(f"  code            {os.path.dirname(gui.__file__)}")
    print(f"  platform        {platform_note}")
    print(f"  device          {device}{port_note}")
    print(f"  settings        {os.environ['XDG_CONFIG_HOME']}{root_note}")

    win = gui.Window(device, None, restore=a.session, save_settings=False)
    win.show()
    app_q.processEvents()
    time.sleep(0.4)
    app_q.processEvents()
    if a.layout:
        win.ed_name.setCurrentText(a.layout)
        for _ in range(12):
            app_q.processEvents()
            time.sleep(0.05)
    win.anim_toggle.setChecked(a.playing == "on")
    if a.timer == "off":
        win.preview_timer.stop()
    for _ in range(8):
        app_q.processEvents()
        time.sleep(0.05)
    print(f"  window          {win.width()}x{win.height()}, pane side {win.preview.side}, "
          f"canvas `{win.canvas.currentText()}`, clip "
          f"{os.path.basename(win.mp4) if win.mp4 else 'none'}, playing "
          f"{win.anim_toggle.isChecked()}, preview fps {win.preview_fps}, thumbnails "
          f"pending {len(getattr(win, '_pending', []))}")
    ed = win.ed
    if ed is None:
        print(f"opening {a.layout!r} left the window with no editor: nothing to drag",
              file=sys.stderr)
        return 2
    drawn = [i for i in range(len(ed.widgets())) if ed._row_box(ed.obj, i)]
    if not drawn:
        print(f"{a.layout} draws no row this program can point at", file=sys.stderr)
        return 2
    row = a.row if a.row >= 0 else drawn[0]
    if row not in drawn:
        print(f"row {row} puts no ink on the canvas; this file paints rows {drawn[:8]}",
              file=sys.stderr)
        return 2

    # ---- the counters: every one of these is a count, not a duration -----------------------
    # pre-seeded at zero on purpose: the interesting answer is often "none at all", and a
    # count that goes missing when it is zero cannot tell "nothing happened" from "nothing
    # was counted".
    counts = {"keys_read calls": 0, "reads of layout.py's source": 0,
              "subprocesses (ffprobe, ffmpeg, sensors)": 0}
    spent = {}

    def bump(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    def timed(owner, name, label):
        if not hasattr(owner, name):
            # this tree has no such door.  The tool is useful pointed at an older checkout -
            # that is how "before" and "after" get the same command - so a missing method is
            # said out loud rather than counted as zero work.
            print(f"  note            {label}: no `{name}` in this tree, so it is not timed",
                  file=sys.stderr)
            return
        real = getattr(owner, name)
        counts.setdefault(label, 0)
        spent.setdefault(label, 0.0)

        def wrapper(*args, **kw):
            t0 = time.perf_counter()
            out = real(*args, **kw)
            spent[label] = spent.get(label, 0.0) + (time.perf_counter() - t0) * 1000
            bump(label)
            return out
        setattr(owner, name, wrapper)

    real_run, real_keys = subprocess.run, themes.keys_read
    real_getsource = None

    def counted_run(*args, **kw):
        bump("subprocesses (ffprobe, ffmpeg, sensors)")
        return real_run(*args, **kw)

    def counted_keys(*args, **kw):
        bump("keys_read calls")
        return real_keys(*args, **kw)

    subprocess.run = counted_run
    themes.keys_read = counted_keys
    try:
        import inspect
        real_getsource = inspect.getsource

        def counted_getsource(obj):
            if getattr(obj, "__name__", "") == "xigmalcd.layout":
                bump("reads of layout.py's source")
            return real_getsource(obj)
        inspect.getsource = counted_getsource
    except (ImportError, AttributeError):
        pass

    if not a.no_breakdown:
        timed(ed, "paint", "Editor.paint")
        timed(ed, "move_to", "Editor.move_to")
        timed(ed, "snap_move", "Editor.snap_move")
        timed(win, "_repaint", "Window._repaint (layer)")
        timed(win, "_preview_tick", "Window._preview_tick")
        timed(win, "_show", "Window._show (pixels to Qt)")
        timed(win, "_fit", "Window._fit (scaled pixmap)")
        timed(win, "_captions", "Window._captions")
        timed(win, "_canvas_marks", "Window._canvas_marks")

    ox, oy = win.preview._origin()
    scale = win.preview.side / render.W

    def pane(px: int, py: int) -> tuple:
        return (int(round(ox + px * scale)), int(round(oy + py * scale)))

    def event(kind: str, x: int, y: int):
        kinds = {"press": QEvent.Type.MouseButtonPress, "move": QEvent.Type.MouseMove,
                 "release": QEvent.Type.MouseButtonRelease}
        pos = QPointF(x, y)
        return QMouseEvent(kinds[kind], pos, pos, Qt.MouseButton.LeftButton,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    def drag(nth: int) -> list:
        box = ed._row_box(ed.obj, row)
        start = (box[0] + 2, (box[1] + box[3]) // 2)
        win.preview.mousePressEvent(event("press", *pane(*start)))
        if not win._drag:
            print(f"drag {nth}: the press found no row at panel {start}", file=sys.stderr)
            return []
        times = []
        for step in range(1, a.moves + 1):
            t0 = time.perf_counter()
            win.preview.mouseMoveEvent(event("move", *pane(start[0] + step * a.dx,
                                                            start[1])))
            app_q.processEvents()          # the loop's turn, as it gets it in a session
            times.append((time.perf_counter() - t0) * 1000)
        win.preview.mouseReleaseEvent(event("release", *pane(start[0] + a.moves * a.dx,
                                                              start[1])))
        moved = int((ed.widgets()[row].get("property") or [{}])[0]["x"])
        print(f"  drag {nth}          mean {statistics.mean(times):7.1f} ms, median "
              f"{statistics.median(times):7.1f}, worst {max(times):7.1f} over {a.moves} "
              f"moves (row {row} now at x {moved})")
        return times

    per = []
    for nth in range(1, a.drags + 1):
        per += drag(nth)
    if not per:
        return 2

    print(f"  all drags       {len(per)} moves, mean {statistics.mean(per):.1f} ms, "
          f"median {statistics.median(per):.1f}, worst {max(per):.1f}, "
          f"{statistics.mean(per) / max(1e-9, 1.0):.0f} moves a second if run back to back")
    print("  counts per move " + ", ".join(f"{k} {v / len(per):.2f}" for k, v in
                                           sorted(counts.items())))
    if spent:
        print("  where it went (a parent contains its children: _repaint > paint/_show/"
              "_fit/_captions/_canvas_marks)")
        for key, ms in sorted(spent.items(), key=lambda kv: -kv[1]):
            print(f"    {ms / len(per):7.2f} ms/move  {counts[key] / len(per):5.2f} "
                  f"calls/move  {key}")
    print("  what it means   the counts are what tests/test_canvas.py asserts, so the "
          "figures here\n                  and the checks there are one statement. A "
          "duration belongs to a box:\n                  these are this box's, on this "
          "day, and re-run this command to get them.")

    if a.profile:
        import cProfile
        import io
        import pstats
        pr = cProfile.Profile()
        pr.enable()
        drag("profiled")
        pr.disable()
        out = io.StringIO()
        pstats.Stats(pr, stream=out).sort_stats("tottime").print_stats(240)
        keep = [line for line in out.getvalue().splitlines()
                if any(part in line for part in (here, "ast.py", "ImagingCore", "processEvents"))]
        print("  under cProfile  (its own overhead is in these numbers)")
        print("\n".join(keep[:14]))

    subprocess.run = real_run
    themes.keys_read = real_keys
    if real_getsource is not None:
        import inspect
        inspect.getsource = real_getsource
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
