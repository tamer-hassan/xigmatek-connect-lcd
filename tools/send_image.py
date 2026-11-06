#!/usr/bin/env python3
"""Upload picture files to the LCD and report exactly what the panel says.

    tools/send_image.py /tmp/opencode/files_init/*.osd     stock frames from a capture
    tools/send_image.py my.png --truecolor                 our own renders
    tools/send_image.py a.png b.png --repeat 3             keep pushing frames
"""
from __future__ import annotations

import argparse
import io
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])

from PIL import Image                                    # noqa: E402
from xigmalcd import protocol, render                    # noqa: E402
from xigmalcd.protocol import Link, ProtocolError, find_ports  # noqa: E402


def load(path: str, truecolor: bool, maxw: int = 480) -> bytes:
    """Return PNG bytes to upload.  .osd files are sent byte for byte."""
    if path.lower().endswith(".osd"):
        return open(path, "rb").read()
    img = Image.open(path).convert("RGBA")
    if img.size != (render.W, render.H):
        img.thumbnail((maxw, maxw), Image.LANCZOS)
        pad = Image.new("RGBA", (render.W, render.H), (0, 0, 0, 255))
        pad.paste(img, ((render.W - img.width) // 2,
                        (render.H - img.height) // 2))
        img = pad
    return render.to_png(img, palette=not truecolor)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("-d", "--device")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("--truecolor", action="store_true",
                    help="write 8-bit RGBA PNGs like the stock app does")
    ap.add_argument("--chunk", type=int, default=protocol.MEDIA_CHUNK,
                    help="raw upload chunk size (the vendor app writes 1000)")
    ap.add_argument("--gap", type=float, default=protocol.MEDIA_GAP,
                    help="pause between the announcement and the first file byte; "
                         "0 gets the file refused, so leave this alone")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--no-handshake", action="store_true")
    args = ap.parse_args()

    port = args.device or (find_ports() or [("/dev/ttyACM0", "?")])[0][0]
    link = Link(port, args.baud, timeout=5.0)
    try:
        if not args.no_handshake:
            info = link.hello()
            print(f"device {info.get('sn')} free space {info.get('space')}")
        for n in range(args.repeat):
            for path in args.files:
                data = load(path, args.truecolor)
                name = render.frame_name()
                print(f"\n{n} {path} -> {name} {len(data)} bytes")
                t0 = time.monotonic()
                try:
                    res = link.send_media(name, data, gap=args.gap,
                                          chunk=args.chunk)
                    took = time.monotonic() - t0
                    print(f"  streamed   : {len(data)} bytes in {took:.2f}s "
                          f"({len(data)/max(took,1e-6)/1024:.1f} KB/s)")
                    print(f"  notice     : {res.get('notice')} "
                          f"state={res.get('state', '-')}")
                except (ProtocolError, OSError) as exc:
                    print(f"  ! {type(exc).__name__}: {exc}")
        return 0
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
