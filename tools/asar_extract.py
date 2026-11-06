#!/usr/bin/env python3
"""asar_extract.py - read an Electron .asar archive without node.

asar is trivial: a JSON header saying where every file lives, then the file
bytes back to back.  We want this because ALPHA's own JavaScript is inside
`Program Files/ALPHA/resources/app.asar`, and the JavaScript is the protocol:
what it sends, in what order, with which bodies.  Reading it is the difference
between guessing request bodies from a capture and knowing them.

    python3 tools/asar_extract.py ASAR                 list, with sizes
    python3 tools/asar_extract.py ASAR --grep PATTERN  show matching files
    python3 tools/asar_extract.py ASAR --to DIR        unpack everything
    python3 tools/asar_extract.py ASAR --cat PATH      one file to stdout
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys


def header(asar_path: str) -> tuple[dict, int]:
    """Parse the archive header.  Returns (tree, byte offset of file data)."""
    with open(asar_path, "rb") as fh:
        head = fh.read(16)
        if len(head) < 16:
            raise SystemExit("file too small to be an asar")
        # uint32: size of the length field (4); uint32: size of the header
        # pickle; uint32: length of the JSON string that follows.
        pick = struct.unpack_from("<II", head, 4)
        js_len = struct.unpack_from("<I", head, 8)[0]
        blob = fh.read(js_len)
        # The header string is padded out to a 4-byte boundary, so parse the
        # JSON object at the front and ignore the tail.
        tree = json.JSONDecoder().raw_decode(blob.decode("utf-8", "replace"))[0]
    # File data starts right after the 8-byte preamble plus the header pickle.
    return tree, 8 + pick[1]


def walk(node: dict, prefix: str = ""):
    """Yield (path, offset-or-None, size) for every file in the tree."""
    for name, meta in (node.get("files") or {}).items():
        path = f"{prefix}/{name}" if prefix else name
        if "files" in meta:
            yield from walk(meta, path)
        elif "offset" in meta:
            yield path, int(meta["offset"]), meta.get("size", 0)
        else:
            yield path, None, meta.get("size", 0)


def read(asar_path: str, base: int, offset, size) -> bytes:
    if offset is None:
        return b""
    with open(asar_path, "rb") as fh:
        fh.seek(base + int(offset))
        return fh.read(size)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("asar")
    ap.add_argument("--to", metavar="DIR", help="unpack the whole archive here")
    ap.add_argument("--cat", metavar="PATH", help="print one file")
    ap.add_argument("--grep", help="only list files whose name matches")
    ap.add_argument("--name-grep", help="alias of --grep")
    ap.add_argument("--find", metavar="TEXT",
                    help="grep file *contents*: list files containing TEXT, "
                         "with the first hit shown as a short excerpt")
    ap.add_argument("--context", type=int, default=90,
                    help="characters of context around a --find hit")
    ap.add_argument("--fixed", action="store_true",
                    help="--find matches plain text, not a regular expression")
    ap.add_argument("--max", type=int, default=400, help="list limit")
    ap.add_argument("--ext", default="", help="only this extension, e.g. .js")
    a = ap.parse_args()

    tree, base = header(a.asar)
    files = list(walk(tree))
    print(f"{len(files)} files, data starts at byte {base}", file=sys.stderr)

    if a.cat:
        for path, off, size in files:
            if path == a.cat or path.endswith(a.cat):
                sys.stdout.buffer.write(read(a.asar, base, off, size))
                return 0
        print(f"no such file: {a.cat}", file=sys.stderr)
        return 1

    if a.to:
        os.makedirs(a.to, exist_ok=True)
        for path, off, size in files:
            dst = os.path.join(a.to, path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(read(a.asar, base, off, size))
        print(f"unpacked {len(files)} files into {a.to}", file=sys.stderr)
        return 0

    if a.find:
        import re

        rx = re.compile(re.escape(a.find) if a.fixed else a.find)
        hits = 0
        for path, off, size in files:
            if a.ext and not path.endswith(a.ext):
                continue
            if size > 30_000_000:
                continue
            blob = read(a.asar, base, off, size)
            m = rx.search(blob.decode("utf-8", "replace"))
            if not m:
                continue
            hits += 1
            lo = max(0, m.start() - a.context)
            print(f"{path}  ({size} B)  hit at {m.start()}")
            print("    ..." + blob[lo:m.end() + a.context]
                  .decode("utf-8", "replace").replace("\n", " ") + "...")
            if hits >= a.max:
                print(f"... stopped at {hits} files with hits")
                break
        print(f"{hits} files contain it", file=sys.stderr)
        return 0

    pat = a.grep or a.name_grep
    shown = 0
    for path, off, size in sorted(files, key=lambda x: -x[2]):
        if a.ext and not path.endswith(a.ext):
            continue
        if pat and pat.lower() not in path.lower():
            continue
        print(f"{size:10d}  {path}")
        shown += 1
        if shown >= a.max:
            print(f"... {len(files) - shown} more")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
