#!/usr/bin/env python3
"""Put the GUI's drawing paths in front of your eyes: one continuous, labelled run.

    python3 tools/gui_glass.py [--device /dev/ttyACM0] [--mp4 media/Theme_25.mp4]
                               [--live-seconds 30] [--fps 2] [--theme alpha]

Everything on the wire goes through `xigmaui.panel.Panel`, the same worker the
window's four buttons use - status, upload, one frame, live - so this is
evidence about the *GUI's* paths and not about the CLI that already works.  The
destructive path is not reachable from here: `reset` is not among the actions
this driver will queue, and `Panel` asks for a destructive `Link` only from
`_reset` (PROTOCOL.md §5).

The frames are self-labelled: the phase name is the theme's title, so whatever
you saw on the glass has a name and a slot in the log, and the run prints its
own start and end clock plus the window each phase occupied.  The panel has no
readback (§11), so what it *showed* is yours to report; what it *accepted* is in
the notice codes below.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtCore import QCoreApplication                          # noqa: E402
from xigmaui.clips import frame as clip_frame, luma               # noqa: E402
from xigmaui.panel import Panel, flatten, port_busy               # noqa: E402
from xigmalcd import render                                       # noqa: E402
from xigmalcd.main import (BRIGHT_LUMA, DEFAULT_MP4,              # noqa: E402
                           SCRIM_ON_BRIGHT)

# what the window's own "Upload background" button passes (app.py), so the
# driver is not a second, better-tested copy of the same action
GAP, CHUNK = 0.02, 1000
FIELDS = ("space", "brightness", "degree", "osdState", "mode", "logo", "timeout")


def clock() -> str:
    return time.strftime("%H:%M:%S")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--mp4", default=DEFAULT_MP4,
                    help="the background to upload (default: the shipped clip)")
    ap.add_argument("--theme", default="alpha", choices=sorted(render.THEMES))
    ap.add_argument("--clock-size", type=int, default=30)
    ap.add_argument("--text-color", type=render.parse_ink, default=None,
                    metavar="COLOUR",
                    help="the ink of the glyphs this run draws (name or #rrggbb); "
                         "unset keeps the theme's own skin, which for `alpha` "
                         "is the white measured in PROTOCOL.md §10. This is "
                         "the tool that would put the claim on glass: the "
                         "suite measures the ink off-glass, so far")
    ap.add_argument("--fps", type=float, default=2.0,
                    help="live rate: 1 is the vendor's, 2 is the daemon's default")
    ap.add_argument("--live-seconds", type=float, default=30.0,
                    help="0 skips the live phase")
    ap.add_argument("--no-fans", action="store_true")
    ap.add_argument("--no-upload", action="store_true",
                    help="skip the background upload (keeps what is stored)")
    a = ap.parse_args(argv)

    why = port_busy(a.device)
    if why:
        print(f"{why}\nnothing sent.", file=sys.stderr)
        return 2
    if not os.path.isfile(a.mp4):
        print(f"no such clip: {a.mp4}", file=sys.stderr)
        return 2

    app = QCoreApplication([])              # the worker is a QThread; no window
    panel = Panel(a.device)
    panel.log.connect(lambda s: print(f"{clock()}  {s}", flush=True))
    seen: dict[str, tuple[bool, str]] = {}
    panel.done.connect(lambda kind, ok: seen.update({kind: (ok, clock())}))
    shots: list[dict] = []
    panel.status.connect(shots.append)

    img = clip_frame(a.mp4)
    lum = luma(img) if img else 0.0
    scrim = SCRIM_ON_BRIGHT if lum > BRIGHT_LUMA else 0
    print(f"clip {a.mp4}\n  {os.path.getsize(a.mp4)} B, mean luma {lum:.1f}/255 "
          f"-> scrim {scrim} ({'plate' if scrim else 'no plate'}), "
          f"theme {a.theme}, clock {a.clock_size} px, text "
          f"{render.ink_hex(a.text_color) or 'theme default'}")

    def kw(title: str) -> dict:
        return {"bg": render.OVERLAY, "clock_size": a.clock_size,
                "fan": not a.no_fans, "scrim": scrim, "title": title,
                "ink": a.text_color}

    steps: list[tuple[str, dict, str]] = [("status", {}, "baseline")]
    # `fans` here is not the drawing: it decides whether the host's tach and
    # temperature readings go into the `STATE all 1` blob at the head of the
    # session. The drawing is decided by "fan" inside kw() above.
    blob = {"fans": not a.no_fans}
    if not a.no_upload:
        steps.append(("upload", {"path": a.mp4, "gap": GAP, "chunk": CHUNK,
                                 **blob}, "upload"))
    steps.append(("frame", {"theme": a.theme, "kw": kw("GUI frame"), **blob},
                  "one frame"))
    if a.live_seconds:
        steps.append(("live", {"theme": a.theme, "kw": kw("GUI live"),
                               "fps": a.fps, "seconds": a.live_seconds,
                               **blob}, "live"))
    steps.append(("status", {}, "after"))

    start = clock()
    results: list[tuple[str, bool, str]] = []
    print(f"\n== window on the glass: {start} onward")
    for kind, args, label in steps:
        seen.clear()
        when = clock()
        print(f"\n-- {label}  ({kind})  {when}")
        panel.queue(kind, **args)
        while panel.isRunning():
            app.processEvents()
            time.sleep(0.05)
        app.processEvents()
        ok, at = seen.get(kind, (False, clock()))
        results.append((label, ok, at))
        print(f"-- {label}: {'ok' if ok else 'FAILED'} at {at}")

    before, after = (shots + [{}, {}])[:2]
    fb, fa = flatten(before), flatten(after)
    print("\n== panel state, read through the GUI's own status action")
    print(f"{'field':12s} {'before':>12s} {'after':>12s}")
    for key in FIELDS:
        if key in fb or key in fa:
            print(f"{key:12s} {str(fb.get(key, '-')):>12s} "
                  f"{str(fa.get(key, '-')):>12s}")
    print(f"sn {fa.get('sn') or fb.get('sn')}  app {fa.get('app')}  "
          f"fw {fa.get('firmware')}  hw {fa.get('hardware')}")
    print(f"\n== the run: {start} to {clock()}")
    print("   " + "  ".join(f"{label} {'ok' if ok else 'FAILED'} ({at})"
                            for label, ok, at in results))
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
