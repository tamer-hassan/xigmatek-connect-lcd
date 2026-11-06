#!/usr/bin/env python3
"""Push our own rendered frames through the upload path that the panel accepts.

The panel's media writer only takes a file when the whole exchange - `transport`,
the raw stream, `transported` - is one burst that fits in one of its ~1 s service
cycles, so `Link.send_media` sends it that way and reads the verdict afterwards.
This tool is the live check of that: it renders, uploads, and prints the panel's
own file notice, which is the only honest success signal.

Nothing here touches firmware or update topics: `type` is always `media`.

    tools/burst_upload.py [SECONDS] [THEME]
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import render, sensors  # noqa: E402
from xigmalcd.protocol import Link, ProtocolError  # noqa: E402


def main() -> int:
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    theme = sys.argv[2] if len(sys.argv) > 2 else "gauge"
    link = Link("/dev/ttyACM0", timeout=5.0)
    n = ok = 0
    try:
        info = link.hello(0)
        print("panel:", {k: info.get(k) for k in
                         ("space", "brightness", "mode", "logo", "osdState")})
        t_end = time.monotonic() + secs
        while True:
            m = sensors.collect()
            png = render.to_png(render.draw(m, theme=theme).convert("RGBA"),
                                palette=False)
            start = time.monotonic()
            try:
                res = link.send_media(render.frame_name(), png)
                n += 1
                ok += res.get("notice") == "200"
                took = time.monotonic() - start
                print(f"  {len(png):6} B -> notice={res.get('notice')} "
                      f"state={res.get('state', '-')} "
                      f"{took:.2f}s ({len(png) / took / 1024:.1f} KB/s)",
                      flush=True)
            except (ProtocolError, OSError) as exc:
                print(f"  {len(png):6} B -> {exc}", flush=True)
            if time.monotonic() >= t_end:
                break
            time.sleep(0.2)
        link.drain(0.5)
        info = link.device_info()
        print("panel:", {k: info.get(k) for k in
                         ("space", "brightness", "osdState")})
        print(f"accepted {ok}/{n}")
        return 0 if ok == n and n else 1
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
