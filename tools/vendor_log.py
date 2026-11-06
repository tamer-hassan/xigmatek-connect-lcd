#!/usr/bin/env python3
"""Read ALPHA's own log files: the authoritative record of what the vendor
software puts on the wire, with payload semantics attached.

ALPHA logs every frame it sends and receives as hex (`data hex:`), so its log is
a protocol capture.  On this machine the logs live on the Windows partition:

    /media/windows-c/Users/Tamer/AppData/Roaming/alpha/logs/2026-11-5.log

    vendor_log.py LOG              what the session did (topics, counts, space)
    vendor_log.py LOG --verify     re-encode every request, byte for byte
    vendor_log.py LOG --dump N     print N request/reply exchanges
    vendor_log.py LOG --uploads    list the upload pairs with timing
    vendor_log.py LOG --space      the panel's `space` value over the session
"""
from __future__ import annotations

import argparse
import binascii
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import protocol  # noqa: E402
from xigmalcd.protocol import decode, encode  # noqa: E402

HEX_RE = re.compile(r"data hex:\s*([0-9A-Fa-f ]+)\s*$")
TS_RE = re.compile(r"^(\d\d:\d\d:\d\d\.\d\d\d)")


def frames(path: str):
    """Yield (timestamp, kind, wire_bytes) for every logged frame."""
    ts = ""
    want = None
    for line in open(path, encoding="utf-8", errors="replace"):
        m = TS_RE.match(line)
        if m:
            ts = m.group(1)
        if "Message Frame:" in line:
            want = "req" if "Request" in line else "resp"
            continue
        if not want:
            continue
        m = HEX_RE.search(line)
        if not m:
            continue
        yield ts, want, binascii.unhexlify("".join(m.group(1).split()))
        want = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--dump", type=int, default=0)
    ap.add_argument("--uploads", action="store_true")
    ap.add_argument("--space", action="store_true")
    a = ap.parse_args()

    allf = list(frames(a.log))
    reqs = [f for f in allf if f[1] == "req"]
    resps = [f for f in allf if f[1] == "resp"]
    print(f"{os.path.basename(a.log)}: {len(reqs)} requests, {len(resps)} replies")

    topics = {}
    for _ts, _k, data in reqs:
        m = decode(data)
        topic = m.line.split(" ")[1] if len(m.line.split(" ")) > 1 else "?"
        topics.setdefault(topic, []).append(((_ts), m))
    for topic, lst in sorted(topics.items(), key=lambda kv: -len(kv[1])):
        print(f"  {topic:16} {len(lst)}")

    if a.verify:
        ok = bad = 0
        first = None
        for ts, _k, data in reqs:
            m = decode(data)
            hdrs = dict(m.headers)
            body = None
            if m.body:
                try:
                    body = json.loads(m.body)      # key order comes from the log
                except ValueError:
                    body = m.body
            rebuilt = encode(m.line, hdrs, body if body is not None else b"")
            if rebuilt == data and protocol.checksum_ok(data):
                ok += 1
            else:
                bad += 1
                if first is None:
                    first = (ts, m.line, data, rebuilt)
        print(f"re-encoded byte-identical: {ok}   differ: {bad}")
        if first:
            print(f"  first difference {first[1]} at {first[0]}:\n"
                  f"    want {first[2].hex()}\n    got  {first[3].hex()}")

    if a.dump:
        n, shown = a.dump, set()
        i = 0
        for i, (ts, _k, data) in enumerate(reqs):
            if n <= 0:
                break
            m = decode(data)
            topic = m.line.split(" ")[1] if len(m.line.split(" ")) > 1 else "?"
            if topic in shown and topic in ("transport", "transported"):
                continue
            shown.add(topic)
            print(f"\n== {ts}  {m.line}  {m.headers}")
            print(f"   body {m.body[:160]!r}")
            if i < len(resps):
                r = decode(resps[i][2])
                print(f"   reply {r.line} {r.headers} {r.body[:120]!r}")
            n -= 1

    if a.uploads:
        cur = None
        for ts, _k, data in reqs:
            m = decode(data)
            parts = m.line.split(" ")
            topic = parts[1] if len(parts) > 1 else ""
            if topic == "transport":
                cur = (ts, m)
            elif topic == "transported" and cur:
                print(f"{cur[0]} -> {ts}  {m.body[:70]!r}")
                cur = None

    if a.space:
        for ts, _k, data in resps:
            m = decode(data)
            if b"space" in m.body:
                j = m.json() or {}
                print(f"{ts}  space={j.get('space')} brightness={j.get('brightness')} "
                      f"mode={j.get('mode')} logo={j.get('logo')} "
                      f"osdState={j.get('osdState')} timeout={j.get('timeout')}")


if __name__ == "__main__":
    main()
