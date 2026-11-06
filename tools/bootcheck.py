#!/usr/bin/env python3
"""First thing to run after the panel has been power-cycled.

Reads the panel's state and tries one small and one full-size media upload, so
a media-store limit (if that is what jams the panel) shows up as a difference
between the two verdicts, and `space` before/after shows whether the panel is
writing the file at all.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors  # noqa: E402
from xigmalcd.protocol import Link, ProtocolError  # noqa: E402


def wait_port(port: str, timeout: float) -> bool:
    """Wait for the CDC-ACM node to come back (the panel re-enumerates at boot)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if os.path.exists(port):
            return True
        time.sleep(0.5)
    return False


def try_upload(link, blob, note):
    name = time.strftime("%Y-%m-%d_%H-%M-%S") + f"-{int(time.time() * 1000) % 1000:03d}.osd"
    t0 = time.monotonic()
    try:
        out = link.send_media(name, blob)
        dt = time.monotonic() - t0
        return (f"{note:10} {len(blob):7} bytes -> {out} in {dt:.2f}s "
                f"({len(blob) / dt / 1024:.1f} KB/s)")
    except (OSError, ProtocolError) as exc:
        return f"{note:10} {len(blob):7} bytes -> {exc}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--wait", type=float, default=0.0,
                    help="seconds to wait for the port to appear")
    ap.add_argument("--n", type=int, default=2, help="repeats of each upload")
    a = ap.parse_args()

    if a.wait and not wait_port(a.port, a.wait):
        sys.exit(f"{a.port} never appeared")

    m = sensors.collect()
    big = render.to_png(render.draw(m, theme="gauge"))
    small = render.to_png(render.draw(m, theme="clock").resize((64, 64)))

    with Link(a.port, timeout=2.0) as link:
        info = link.hello()
        keys = ("space", "brightness", "mode", "logo", "osdState", "timeout",
                "degree")
        print("panel:", " ".join(f"{k}={info.get(k)}" for k in keys))
        print(f"       version={info.get('version')} OS={info.get('OS')}")
        link.state_all(m)
        for _ in range(a.n):
            print("  " + try_upload(link, small, "small"))
            time.sleep(0.8)
            print("  " + try_upload(link, big, "full"))
            time.sleep(0.8)
        try:
            print("after:", link.device_info().get("space"))
        except (OSError, ProtocolError) as exc:
            print("after: conn failed:", exc)


if __name__ == "__main__":
    main()
