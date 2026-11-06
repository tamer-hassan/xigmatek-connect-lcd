#!/usr/bin/env python3
"""What does the panel accept as `media`?  Text, video, junk, and the vendor's
own files — the verdict is the answer, and video is the interesting case because
the panel decodes 480x480 H.264 itself (ALPHA transcodes with -an -r 20
-pix_fmt yuv420p, and its theme files are exactly that).

Never sends a `.zip` name or `type: firmware`: that is the firmware-update path.

    tools/media_types.py                    the standard set
    tools/media_types.py --file a.bin b.mkv  try your own files as media
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from xigmalcd import render, sensors                        # noqa: E402
from xigmalcd.protocol import Link, ProtocolError, find_ports  # noqa: E402

MP4 = "/tmp/opencode/cdss/themes/resources/static/media/2.mp4"
THM = ("/tmp/opencode/cdss/install/resources/static/theme/butt/"
       "480X480/default.thm")


def verdict(link, name, blob, chunk=1000, delay=0.002):
    """Announce, stream, confirm; return a one-line verdict."""
    link.drain(0.1)
    seq = link.post("transport", {"type": "media", "fileSize": len(blob),
                                  "fileName": name})
    try:
        m = link.awaited(seq, timeout=4.0)
    except ProtocolError as exc:
        return f"transport: {exc}"
    if b"blockMaxSize" not in (m.body or b""):
        return f"transport: {m.line} {(m.body or b'')[:40]!r}"
    link.send_raw(blob, chunk=chunk, delay=delay)
    seq = link.post("transported", {"md5": "todo", "fileName": name})
    strays = []
    try:
        m = link.awaited(seq, timeout=6.0, strays=strays)
    except ProtocolError as exc:
        return f"transported: {exc} (late: {[s.line for s in strays]})"
    extra = f" +late {[s.line for s in strays]}" if strays else ""
    return f"transported: {m.line} {(m.body or b'')[:44]!r}{extra}"


def healthy(link, png) -> bool:
    """Is the media channel taking files again?  One small upload answers it."""
    try:
        link.send_media(render.frame_name(), png)
        return True
    except (ProtocolError, OSError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device")
    ap.add_argument("--only", help="just this file name")
    ap.add_argument("--file", action="append", default=[],
                    help="upload these files as media too")
    ap.add_argument("--dwell", type=float, default=6.0,
                    help="seconds to leave each accepted file on screen")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="wait up to N seconds for the panel to take files again "
                         "(do this across a USB power cycle)")
    args = ap.parse_args()

    port = args.device or (find_ports() or [("/dev/ttyACM0", "?")])[0][0]
    link = Link(port)
    info = link.hello()
    print(f"space={info.get('space')} brightness={info.get('brightness')} "
          f"osdState={info.get('osdState')} mode={info.get('mode')} "
          f"logo={info.get('logo')}")

    png = render.to_png(render.draw(sensors.collect(), "gauge"))
    if args.wait:
        limit = time.monotonic() + args.wait
        while not healthy(link, png):
            if time.monotonic() >= limit:
                print("the panel still refuses files - nothing to compare against")
                link.close()
                return 1
            left = limit - time.monotonic()
            print(f"  refused, retrying in 4 s ({left:.0f} s left; "
                  f"cycle the panel's USB now)", flush=True)
            time.sleep(4.0)
            try:                       # a power cycle kills the open handle
                link.close()
            except OSError:
                pass
            try:
                link = Link(port)
                link.hello()
            except (ProtocolError, OSError) as exc:
                print(f"  port/panel not up yet: {exc}", flush=True)
                time.sleep(3.0)
        print("the media channel takes files again\n", flush=True)
    cases = [
        ("notes.txt", b"hello from linux, just text\n" * 40),
        ("notes.osd", b"hello from linux, just text\n" * 40),
        ("junk.bin", bytes(range(256)) * 4),
        ("frame.png", png),                       # control: a real image
        ("frame.osd", png),
    ]
    if os.path.exists(MP4):
        size = os.path.getsize(MP4)
        cases.append(("clip.mp4", open(MP4, "rb").read()[:min(size, 400_000)]))
    else:
        print(f"(no {MP4}; skipping the video case)")
    for path in args.file:
        if os.path.exists(path):
            base = os.path.basename(path)
            if base.lower().endswith(".zip"):
                print(f"refusing {base}: that is the firmware update path")
                continue
            cases.append((base, open(path, "rb").read()))

    for name, blob in cases:
        if args.only and args.only not in name:
            continue
        t0 = time.monotonic()
        line = verdict(link, name, blob)
        sp = ""
        try:
            sp = f" space={link.device_info().get('space')}"
        except ProtocolError:
            pass
        print(f"  {name:14s} {len(blob):7d} B  {time.monotonic()-t0:5.2f}s  "
              f"{line}{sp}", flush=True)
        time.sleep(args.dwell)

    info = link.hello()
    print(f"\nend: space={info.get('space')} osdState={info.get('osdState')} "
          f"mode={info.get('mode')} logo={info.get('logo')} "
          f"brightness={info.get('brightness')}")
    link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
