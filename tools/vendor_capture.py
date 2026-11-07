#!/usr/bin/env python3
"""Take the real `.osd` payloads out of a Windows serial-monitor capture.

`data/captures/COM3 Monitoring Session.txt` (bench-only: `data/` is gitignored) is
a serial monitor log in UTF-16 with one row per serial IRP:

    #  Time  Function  Direction  Status  Data  Data (chars)  Data length ...

`IRP_MJ_WRITE`/`DOWN` rows are host->panel, and every write is logged twice
(`DOWN` and its mirror), so only DOWN rows are used.  The rows are atomic
writes, which is what makes the file stream visible: a byte walk over the whole
capture cannot find it, because a PNG body is full of 0x5A bytes that look like
frame starts.

Between a `POST transport` write and the following `POST transported` write sit
the file's bytes, unframed, in fixed-size writes.  That is the ground truth for
§6 of PROTOCOL.md, and the payloads it yields are the best test assets there
are: they are accepted by the panel, and they are accepted byte for byte.

    vendor_capture.py CAP                    statistics for every upload
    vendor_capture.py CAP --extract 3        save three payloads as .osd files
    vendor_capture.py CAP --extract 3 --out DIR
"""
from __future__ import annotations

import argparse
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import protocol  # noqa: E402

HEX_RE = re.compile(r"(?:[0-9A-Fa-f]{2} ){2,}[0-9A-Fa-f]{2}")


def down_rows(path: str):
    """Yield (time, bytes) for every host -> panel write in the capture."""
    text = open(path, encoding="utf-16-le", errors="replace").read()
    for line in text.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 6:
            continue
        if "WRITE" not in cols[2].upper() or "DOWN" not in cols[3].upper():
            continue
        m = HEX_RE.search(line)
        if not m:
            continue
        yield cols[1].strip(), bytes.fromhex("".join(m.group(0).split()))


def as_request(data: bytes):
    """Decoded Message if this whole write is one framed request, else None.

    A chunk of file bytes can start with 0x5A and happen to parse; requiring the
    frame to end exactly at the end of the write and the verb to be a real one
    rules that out.
    """
    got = protocol.read_frame(data, 0)
    if not got or got[1] != len(data):
        return None
    msg = protocol.decode(got[0])
    if msg.line.split(" ")[0] not in protocol.VERBS:
        return None
    return msg


def transfers(path: str):
    """Yield {"body": <transport json>, "chunks": [bytes...]} per upload."""
    cur = None
    for _ts, data in down_rows(path):
        msg = as_request(data)
        if msg:
            verb = msg.line.split(" ")[1] if len(msg.line.split(" ")) > 1 else ""
            if verb == "transport":
                try:
                    body = msg.json() or {}
                except ValueError:
                    body = None
                cur = {"body": body, "chunks": []} if body else None
                continue
            if verb == "transported":
                if cur:
                    yield cur
                cur = None
                continue
        if cur is not None:
            cur["chunks"].append(data)


def png_header(blob: bytes):
    """(width, height, bit depth, colour type) for a PNG, else None."""
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if blob[12:16] != b"IHDR":
        return None
    w, h, depth, ctype = struct.unpack(">IIBB", blob[16:26])
    return w, h, depth, ctype


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vendor_capture", description=__doc__.split("\n")[0])
    ap.add_argument("capture", help="the monitor log (UTF-16 .txt)")
    ap.add_argument("--extract", type=int, default=0,
                    help="save this many payloads under --out")
    ap.add_argument("--out", default=".", help="where to save them")
    args = ap.parse_args(argv)

    n = sizes = 0
    chunk_sizes: dict[int, int] = {}
    exact = 0
    pngs = 0
    names = []
    saved = 0
    for t in transfers(args.capture):
        blob = b"".join(t["chunks"])
        body = t["body"]
        n += 1
        sizes += len(blob)
        for c in t["chunks"]:
            chunk_sizes[len(c)] = chunk_sizes.get(len(c), 0) + 1
        if len(blob) == body.get("fileSize"):
            exact += 1
        hdr = png_header(blob)
        if hdr:
            pngs += 1
        if n <= 3 or n % 25 == 0:
            print(f"  {body.get('fileName')}: declared {body.get('fileSize')}, "
                  f"extracted {len(blob)} in {len(t['chunks'])} chunks, "
                  f"magic {blob[:8].hex()}, png={hdr}")
        if args.extract and saved < args.extract:
            os.makedirs(args.out, exist_ok=True)
            name = os.path.basename(body.get("fileName") or f"upload{n}.osd")
            path = os.path.join(args.out, name)
            with open(path, "wb") as fh:
                fh.write(blob)
            print(f"  saved {path}")
            saved += 1
        if len(names) < 3:
            names.append(body.get("fileName"))

    print(f"\nuploads in capture : {n}")
    print(f"file bytes total   : {sizes}")
    print(f"extract == declared: {exact}/{n}")
    print(f"PNG payloads       : {pngs}/{n}")
    print(f"raw write sizes    : "
          f"{sorted(chunk_sizes.items(), key=lambda kv: -kv[1])[:8]}")
    print(f"name pattern       : {names}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
