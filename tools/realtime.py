#!/usr/bin/env python3
"""Try to make the panel draw our numbers itself instead of us painting PNGs.

`realtimeDisplay {"enable":true}` is the only shape the panel takes (numbers and
every other key come back 400), and ALPHA only ever sends it to panels whose
deviceConfig.OS is "RTOS" - ours reports "Linux", so it is unexplored territory.
If it works the panel renders the `STATE all 1` metrics itself: no picture
streaming, no session limits, no 3 fps ceiling.

Watch the display while this runs.  It prints what the panel says at every step
and restores everything afterwards.

    tools/realtime.py                     enable, push metrics, watch, restore
    tools/realtime.py --dwell 15          keep the enabled state for 15 s
    tools/realtime.py --disable           just turn it back off
"""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from xigmalcd import render, sensors                          # noqa: E402
from xigmalcd.protocol import Link, ProtocolError, find_ports   # noqa: E402


def show(link: Link, label: str, n=3, wait=0.8):
    """Print the next n replies, whatever they are."""
    for _ in range(n):
        m = link.reply(timeout=wait)
        if m is None:
            print(f"  {label:22s} (no answer)")
            return None
        print(f"  {label:22s} {m.line} ack={m.headers.get('AckNumber')} "
              f"{(m.body or b'').decode('latin-1')[:90]}")
        if not m.body:
            return m
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device")
    ap.add_argument("--dwell", type=float, default=10.0,
                    help="seconds to leave it enabled while you watch")
    ap.add_argument("--state-every", type=float, default=1.0,
                    help="push metrics every N s while enabled")
    ap.add_argument("--disable", action="store_true",
                    help="only send realtimeDisplay {enable:false}")
    args = ap.parse_args()

    port = args.device or (find_ports() or [("/dev/ttyACM0", "?")])[0][0]
    print(f"port {port}")
    with Link(port, 115200, timeout=2.0) as link:
        before = link.device_info()
        print("before:", json.dumps({k: before.get(k) for k in
              ("osdState", "mode", "logo", "brightness", "degree", "timeout",
               "space")}, separators=(",", ":")))

        if args.disable:
            link.request("POST realtimeDisplay 1", {"enable": False})
            show(link, "disable")
            return 0

        print("\nenabling realtime display:")
        link.request("POST realtimeDisplay 1", {"enable": True})
        show(link, "enable")

        print(f"\npushing metrics for {args.dwell:.0f}s "
              f"(watch the panel now):")
        stop = time.monotonic() + args.dwell
        n = 0
        while time.monotonic() < stop:
            try:
                m = link.state_all(sensors.collect(), wait=True)
                line = f"{m.line} {(m.body or b'')[:70].decode('latin-1')}"
            except ProtocolError as exc:
                line = str(exc)
            n += 1
            if n <= 2:
                print(f"  STATE all 1 -> {line}")
            time.sleep(args.state_every)

        print("\nwhat the panel reports now:")
        after = link.device_info()
        print("after: ", json.dumps({k: after.get(k) for k in
              ("osdState", "mode", "logo", "brightness", "degree", "timeout",
               "space")}, separators=(",", ":")))
        new = {k: v for k, v in after.items() if before.get(k) != v}
        print("changed:", json.dumps(new, separators=(",", ":")) or "nothing")

        print("\nturning it back off and putting a picture back:")
        link.request("POST realtimeDisplay 1", {"enable": False})
        show(link, "disable")
        try:
            print(" ", link.send_media(render.frame_name(),
                                       render.to_png(render.draw(
                                           sensors.collect(), "gauge"))))
        except (ProtocolError, OSError) as exc:
            print(f"  picture failed: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
