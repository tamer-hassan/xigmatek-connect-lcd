"""Parse a Windows serial capture (UTF-16 CSV from a USB monitor) into frames.

RECORDS -> rows, STREAM -> one side's bytes, UPLOADS -> (announcement, file
bytes).  File bytes are raw, straight after the `transport` frame, so UPLOADS
must use the announced size: a 0x5A inside a PNG is not a frame start.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import read_frame, decode            # noqa: E402

HEX_RE = re.compile(r"[0-9a-fA-F ]+")


def records(path):
    """rows of the capture: (timestamp, irp function, direction, payload)"""
    data = open(path, "rb").read().decode("utf-16-le", errors="replace")
    out = []
    for line in data.split("\r\n")[1:]:
        f = line.split("\t")
        if len(f) < 11:
            continue
        hexcol = re.sub(r"[^0-9a-fA-F ]", "", f[5].strip())
        try:
            raw = bytes.fromhex(hexcol) if hexcol else b""
        except ValueError:
            raw = b""
        out.append((f[1].strip(), f[2].strip(), f[3].strip(), raw))
    return out


def stream(recs, func="IRP_MJ_WRITE", direction="DOWN"):
    """all bytes one side pushed, in order, framing and payloads mixed in"""
    return b"".join(r[3] for r in recs if r[1] == func and r[2] == direction)


def frames(buf):
    """yield (frame bytes, next offset); frames here are the labelled ones only"""
    i = 0
    while i < len(buf):
        fr = read_frame(buf, i) if buf[i] == 0x5A else None
        if not fr:
            i += 1
            continue
        fr, i = fr
        yield fr, i


def uploads(buf):
    """(announcement, raw file bytes) for every upload in the stream.

    The panel is told the size first, so the payload is `fileSize` bytes that
    start immediately after the `transport` frame - nothing in between, no
    padding, and 0x5A bytes inside the file are not frame starts.
    """
    out = []
    for fr, i in frames(buf):
        m = decode(fr)
        if not m.line.startswith("POST transport "):
            continue
        try:
            ann = json.loads(m.body)
        except (ValueError, TypeError):
            continue
        size = ann.get("fileSize")
        if isinstance(size, int) and i + size <= len(buf):
            out.append((ann, buf[i:i + size]))
    return out
