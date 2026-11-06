#!/usr/bin/env python3
"""watchtest.py - a display test you can read at any moment, on your own schedule.

Every earlier rate test here announced "watch from HH:MM:SS to HH:MM:SS", and every
one of those was missed.  This one is designed to be glanced at whenever you happen
to be at the desk, and to answer the question from a single description:

  * it runs for `--minutes` (default 10) at one frame per second;
  * each frame shows a **huge phase letter** and, under it, the frame number and the
    wall clock, so a glance plus one sentence ("about 09:20 I saw a big F, number
    212") pins down exactly which phase the panel was in and how far behind it was;
  * the phases differ in one variable each, so a single report discriminates between
    hypotheses that need two timed observations to separate;
  * the schedule is printed at the start, in relative time, so it is still correct
    even if the run's start time slipped.

Phases, repeated until `--minutes` is up (`--phases` picks which, in order):

  A  vendor-faithful, one frame per second, 1000-byte writes
  K  same frames, written in 1024-byte blocks - the panel's own `blockMaxSize`
  U  same frames as one single write (one contiguous buffer to the driver)
  P  same frames, file names dated `--offset` seconds in the PAST
  Q  same frames, file names dated `--offset` seconds in the FUTURE
  T  tiny flat frames (1.5 KB), which used to tick visibly faster than glyph frames

If the panel's display rate is a property of the panel, all of them look the same.  If
the file name's embedded clock decides when a frame becomes eligible to show, P and Q
differ visibly from A.  If it is frame content/size, T differs.  If it is how the bytes
are split into blocks on the wire, K and U differ.

    python3 tools/watchtest.py --minutes 10
    nohup python3 -u tools/watchtest.py --minutes 10 >/tmp/watch.log 2>&1 &

Reports are additive: any number of glances at any times are useful, and the last
frame is bright magenta, so if the panel is showing magenta it displayed the very
last frame of the run.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render  # noqa: E402
from xigmalcd.protocol import Link, MEDIA_GAP  # noqa: E402

VENDOR_MP4 = ("/media/windows-c/Users/Tamer/AppData/Roaming/alpha/media/background/"
              "1757491588831.mp4")
LETTER_FONT = 300

# phase letter -> what makes it different
PHASES = {
    # ours, exactly as the display loop ran until the ordering was questioned:
    # 1000-byte blocks, 20 ms pause, `transported` right after the last byte
    "A": dict(offset=0.0, chunk=1000, tiny=False, order="fast"),
    # 2x2 of the two things that changed together: block size and ordering.  Z is
    # the ordering fix alone, K the block size alone, X both - ALPHA's shape.
    "K": dict(offset=0.0, chunk=1024, tiny=False, order="fast"),
    "Z": dict(offset=0.0, chunk=1000, tiny=False, order="notice"),
    "X": dict(offset=0.0, chunk=1024, tiny=False, order="notice"),
    "U": dict(offset=0.0, chunk=65536, tiny=False),
    "P": dict(offset=-1.0, chunk=1000, tiny=False),      # -1 = -a.offset
    "Q": dict(offset=1.0, chunk=1000, tiny=False),       # +1 = +a.offset
    "T": dict(offset=0.0, chunk=1000, tiny=True),
    # ALPHA's own bytes, straight off its wire capture, with ALPHA's own file
    # names: same content, same size, same encoder, our host.  If this ticks
    # and A does not, the difference is inside the PNG.
    "R": dict(offset=0.0, chunk=1024, tiny=False, replay=True),
    # ALPHA's exact exchange timing: blockMaxSize blocks and the 11 ms it lets
    # sit between the announcement and the first file byte (we use 20 ms)
    "G": dict(offset=0.0, chunk=1024, tiny=False, gap=0.011),
    "V": dict(offset=0.0, chunk=1024, tiny=False, gap=0.0),
    # ALPHA keeps the panel awake: `power resume` moves `brightness` 0 -> 100 and
    # its log carries 11 of them.  We only ever send one, in `hello()`.  This
    # phase sends one every 20 s on top of the frames.
    "W": dict(offset=0.0, chunk=1000, tiny=False, power=20.0),
}
VENDOR_FRAMES = "data/vendor_frames"


def vname(offset: float) -> str:
    """ALPHA's file-name format, wall clock shifted by `offset` seconds."""
    t = time.time() + offset
    return (time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(t))
            + f"-{int((t % 1) * 1000):03d}.osd")


def card(letter: str, n: int, total: int, tiny: bool = False):
    """Huge phase letter, frame number under it, clock under that.

    The last frame of the whole run is magenta: if the panel is showing magenta it
    displayed the final frame, whatever it was doing in between.
    """
    ink = (255, 0, 255, 255) if n == total else render.WHITE
    if tiny:
        img = render.Image.new("RGBA", (render.W, render.H), render.OVERLAY)
        d = render.ImageDraw.Draw(img)
        d.text((240, 170), letter, font=render.font(220, False), fill=ink,
               anchor="mm")
        d.text((240, 380), str(n), font=render.font(90, False), fill=ink,
               anchor="mm")
        return img
    img = render.Image.new("RGBA", (render.W * render.SS,
                                    render.H * render.SS), render.OVERLAY)
    render._text(img, (240, 150), letter, render._fit(img, letter, 300, 300), ink)
    render._text(img, (240, 330), str(n), render._fit(img, str(n), 260, 150), ink)
    render._text(img, (240, 435), time.strftime("%H:%M:%S"),
                 render.font(42), render.CYAN)
    # The canvas is drawn 2x for smooth glyph edges; the panel only reads a
    # 480x480 PNG, and uploading the big one shows its top-left quadrant, which
    # on the glass looks like a truncated picture pushed into a corner.
    return img.resize((render.W, render.H), render.Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--cadence", type=float, default=1.013,
                    help="seconds per frame; ALPHA's own period")
    ap.add_argument("--phase", type=float, default=45.0,
                    help="seconds per phase, A/P/Q/T cycling")
    ap.add_argument("--offset", type=float, default=7200.0,
                    help="hours-ish clock shift for the P and Q phases, seconds")
    ap.add_argument("--phases", default="APQT",
                    help="which phases to cycle, in order: A plain, K 1024-byte "
                         "blocks, U one single write, P past-dated names, Q "
                         "future-dated names, T tiny frames")
    ap.add_argument("--mp4", action="store_true",
                    help="upload the vendor's theme background first, so the "
                         "background layer is animating like it was on Windows")
    ap.add_argument("--settle", type=float, default=20.0,
                    help="quiet seconds at the end; the picture stays up")
    a = ap.parse_args()

    total = int(a.minutes * 60 / a.cadence)
    plan = a.phases.upper()
    bad = sorted(set(plan) - set(PHASES))
    if bad:
        raise SystemExit(f"unknown phase(s) {''.join(bad)}; "
                         f"choose from {''.join(sorted(PHASES))}")
    t0 = time.time()
    print(f"{total} frames at {a.cadence:.3f} s = {total * a.cadence / 60:.1f} min, "
          f"starting {time.strftime('%H:%M:%S', time.localtime(t0))}", flush=True)
    print("phase schedule (look any time; the letter on the panel says which phase "
          "it is in):", flush=True)
    i = 0
    while i * a.phase < total * a.cadence:
        st, en = t0 + i * a.phase, t0 + (i + 1) * a.phase
        if st > t0 + total * a.cadence:
            break
        print(f"   {plan[i % len(plan)]}  +{i * a.phase:5.0f}s .. +{(i + 1) * a.phase:5.0f}s  "
              f"{time.strftime('%H:%M:%S', time.localtime(st))} - "
              f"{time.strftime('%H:%M:%S', time.localtime(en))}", flush=True)
        i += 1
    print("A ours, `transported` right after the bytes   K 1024-byte blocks   "
          "Z vendor order, 1000-byte blocks   X vendor order and blocks   "
          "U one single write   P names dated in the past   "
          "Q names dated in the future   T tiny frames   R ALPHA's own bytes\n",
          flush=True)

    refused = 0
    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        info = ln.hello(60)
        print("start:", {k: info.get(k) for k in ("logo", "mode", "osdState",
                                                  "brightness", "space")}, flush=True)
        # The panel needs a moment after the handshake before it will take a file -
        # the first upload of a session, sent straight after `conn`, comes back 400.
        time.sleep(0.6)
        ln.drain(0.2)
        if a.mp4:
            blob = open(VENDOR_MP4, "rb").read()
            res = ln.send_media(os.path.basename(VENDOR_MP4), blob,
                                gap=MEDIA_GAP, timeout=90.0)
            print(f"background uploaded: notice {res.get('notice')}, space now "
                  f"{(ln.device_info() or {}).get('space')}", flush=True)

        vendor_files = sorted(os.listdir(VENDOR_FRAMES))
        last_power = time.monotonic()
        for n in range(1, total + 1):
            ph = plan[int((n - 1) * a.cadence // a.phase) % len(plan)]
            cfg = PHASES[ph]
            if cfg.get("replay"):
                # ALPHA's own bytes, untouched: same file the vendor app put on
                # the wire, our host, our cadence
                blob = open(os.path.join(VENDOR_FRAMES,
                                         vendor_files[(n - 1) % len(vendor_files)]),
                            "rb").read()
            else:
                blob = render.to_png(card(ph, n, total, tiny=cfg["tiny"]),
                                     palette=False)
            name = vname(cfg["offset"] * a.offset)
            pw = cfg.get("power")
            if pw and time.monotonic() - last_power >= pw:
                # after the verdict, so its bare `1 200` ack cannot be mistaken
                # for the next file's notice, and drained so it is gone
                ln.post("power", {"event": "resume"})
                ln.drain(0.15)
                last_power = time.monotonic()
            try:
                res = ln.send_media(name, blob, gap=cfg.get("gap", MEDIA_GAP),
                                    chunk=cfg["chunk"], wait=True,
                                    order=cfg.get("order", "notice"))
            except Exception:                              # noqa: BLE001
                # one retry, then carry on: a refusal at the start of a session is
                # normal (the media writer needs the handshake to have settled) and
                # one lost frame in a ten-minute run costs nothing
                try:
                    ln.drain(0.1)
                    res = ln.send_media(name, blob,
                                        gap=cfg.get("gap", MEDIA_GAP),
                                        chunk=cfg["chunk"], wait=True,
                                        order=cfg.get("order", "notice"))
                except Exception as exc2:                  # noqa: BLE001
                    refused += 1
                    print(f"  !! frame {n} ({ph}) refused: {exc2}", flush=True)
                    res = {}
            code = str(res.get("notice") or "")
            if code and not code.startswith("2"):
                refused += 1
                print(f"  !! frame {n} ({ph}) refused: {code}", flush=True)
            if n % 60 == 0:
                print(f"  {n}/{total} in phase {ph} at "
                      f"{time.strftime('%H:%M:%S')}", flush=True)
            left = (t0 + n * a.cadence) - time.time()
            if left > 0:
                time.sleep(left)

        print(f"\nlast frame ({total}) sent at {time.strftime('%H:%M:%S')}; "
              f"going quiet for {a.settle:.0f} s. The picture stays on screen: "
              "magenta means it showed the last frame.", flush=True)
        time.sleep(a.settle)
        print("end:", {k: (ln.device_info() or {}).get(k)
                       for k in ("logo", "mode", "osdState", "brightness",
                                 "space")}, flush=True)

    print(f"\n{total - refused}/{total} frames accepted")
    print("read the panel whenever you like and say what letter and number it shows "
          "- any glance is a data point")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
