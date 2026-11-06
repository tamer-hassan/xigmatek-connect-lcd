#!/usr/bin/env python3
"""Find out what ends a session and what brings the panel back.

Uploads frames until the panel stops answering, then tries three fixes, in the
least disruptive order, all on the same open port unless stated:

  1. a fresh POST conn 1            (same file handle)
  2. drop DTR, raise it again       (same file handle)
  3. close the port and open it again

The first one that gets the device-info reply back is what the firmware needs.
Measured here: the panel goes silent after 522 uploads at 1 fps, or after 717 uploads
/ 368 s at 2 fps - then answers nothing at all, no error frame, just silence, until the
port is closed and opened again.

    tools/session_limit.py                 1 fps until the stall, then probe
    tools/session_limit.py --fps 3         does it arrive sooner when pushed harder?
    tools/session_limit.py --only-reopen   skip straight to fix 3
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from xigmalcd import render, sensors                       # noqa: E402
from xigmalcd.protocol import Link, ProtocolError          # noqa: E402


def transfers(link, args) -> int:
    """Push frames until the panel stops answering; return how many got through."""
    n = 0
    while n < args.max_frames:
        started = time.monotonic()
        png = render.to_png(render.draw(sensors.collect(), args.theme),
                            palette=not args.truecolor)
        try:
            link.send_media(render.frame_name(), png)
        except ProtocolError as exc:
            print(f"stalled after {n} transfers ({time.monotonic() - start_of_run:.0f} s "
                  f"into the run): {exc}")
            return n
        n += 1
        if n % 50 == 0:
            print(f"  {n} transfers ok")
        time.sleep(max(0.0, started + 1.0 / args.fps - time.monotonic()))
    print(f"no stall within {n} transfers")
    return n


def try_handshake(link) -> bool:
    """Fix 1: ask for the device info again on the same handle."""
    try:
        link.drain()
        info = link.hello()
        print(f"  1. POST conn 1 again, same handle   -> back (sn={info.get('sn')})")
        return True
    except ProtocolError as exc:
        print(f"  1. POST conn 1 again, same handle   -> {exc}")
        return False


def try_dtr(link) -> bool:
    """Fix 2: pulse the modem lines without closing anything."""
    try:
        link.ser.dtr = False
        link.ser.rts = False
        time.sleep(0.5)
        link.ser.dtr = True
        link.ser.reset_input_buffer()
        time.sleep(1.0)
        info = link.hello()
        print(f"  2. DTR low then high, same handle   -> back (sn={info.get('sn')})")
        return True
    except ProtocolError as exc:
        print(f"  2. DTR low then high, same handle   -> {exc}")
        return False


def try_reopen(link, args) -> Link | None:
    """Fix 3: close and re-open the port (this is what a restart of ALPHA does)."""
    try:
        link.close()
        time.sleep(1.0)
        fresh = Link(args.device, args.baud, verbose=False)
        info = fresh.hello()
        print(f"  3. close + reopen the port          -> back (sn={info.get('sn')})")
        return fresh
    except (ProtocolError, OSError) as exc:
        print(f"  3. close + reopen the port          -> {exc}")
        return None


start_of_run = time.monotonic()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("-t", "--theme", default="clock", choices=sorted(render.THEMES))
    ap.add_argument("-f", "--fps", type=float, default=1.0)
    ap.add_argument("--max-frames", type=int, default=1500)
    ap.add_argument("--truecolor", action="store_true")
    ap.add_argument("--only-reopen", action="store_true",
                    help="skip fixes 1 and 2, go straight to closing the port")
    args = ap.parse_args()

    global start_of_run
    start_of_run = time.monotonic()

    link = Link(args.device, args.baud)
    info = link.hello()
    print(f"session open, {args.device}, "
          f"space={info.get('space')} timeout={info.get('timeout')}")
    print(f"uploading at {args.fps} fps ...")

    n = transfers(link, args)
    if n >= args.max_frames:
        link.close()
        return 0

    print(f"\npanel is silent. Trying to bring it back ({n} transfers in this session):")
    time.sleep(2.0)
    fixed = False
    if not args.only_reopen:
        fixed = try_handshake(link)
        if not fixed:
            time.sleep(1.0)
            fixed = try_dtr(link)
    if not fixed:
        fresh = try_reopen(link, args)
        fixed = fresh is not None
        if fresh:
            link = fresh
    if not fixed:
        print("\nnothing worked - the panel needs a USB reset or a power cycle")
        return 1

    # and confirm uploads really work again, not just the handshake
    try:
        link.send_media(render.frame_name(),
                        render.to_png(render.draw(sensors.collect(), args.theme)))
        print("recovered: the upload channel works again, not just the handshake")
    except ProtocolError as exc:
        print(f"handshake came back but uploads did not: {exc}")
        return 1
    link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
