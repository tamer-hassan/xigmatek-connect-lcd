#!/usr/bin/env python3
"""What the vendor app *did*, in order, with the picture traffic folded away.

ALPHA's logs are a complete protocol capture, but they are 6-17 MB of
one-second uploads, so reading them by eye hides the interesting parts.  This
prints the request sequence with bodies, collapsing runs of picture uploads
into one line, and can restrict itself to a time window.

    python3 tools/log_timeline.py LOG                    whole session(s)
    python3 tools/log_timeline.py LOG --from 18:41       only after that time
    python3 tools/log_timeline.py LOG --around 18:39:48  +/- 60 s of a moment
    python3 tools/log_timeline.py LOG --census           topic counts only
    python3 tools/log_timeline.py LOG --names           every uploaded file name
    python3 tools/log_timeline.py LOG --replies         what the panel answered
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import decode  # noqa: E402
from tools.vendor_log import frames  # noqa: E402

PICTURE = ("transport", "transported")


def parse_hms(s: str) -> float:
    p = [float(x) for x in s.split(":")]
    while len(p) < 3:
        p.append(0.0)
    return p[0] * 3600 + p[1] * 60 + p[2]


def topic_of(raw: bytes) -> str:
    """'POST transport 1' -> 'transport'; replies -> their 'id code' line."""
    try:
        return decode(raw).line
    except Exception:                            # noqa: BLE001
        return "<undecoded>"


def body_of(raw: bytes) -> str:
    try:
        m = decode(raw)
        j = m.json()
    except Exception:                            # noqa: BLE001
        return ""
    if isinstance(j, dict):
        if "fileName" in j:
            j = {"type": j.get("type"), "fileSize": j.get("fileSize"),
                 "fileName": j["fileName"]}
        return " ".join(f"{k}={v}" for k, v in j.items())
    return str(j)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--from", dest="frm", metavar="HH:MM[:SS]")
    ap.add_argument("--to", metavar="HH:MM[:SS]")
    ap.add_argument("--around", metavar="HH:MM[:SS]")
    ap.add_argument("--window", type=int, default=60)
    ap.add_argument("--census", action="store_true")
    ap.add_argument("--names", action="store_true")
    ap.add_argument("--replies", action="store_true")
    a = ap.parse_args()

    lo, hi = (parse_hms(a.frm) if a.frm else 0.0,
              parse_hms(a.to) if a.to else 86401.0)
    if a.around:
        c = parse_hms(a.around)
        lo, hi = c - a.window, c + a.window

    reqs, reps = [], []
    for ts, kind, raw in frames(a.log):
        secs = parse_hms(ts[:8]) + int(ts[9:]) / 1000
        if not (lo <= secs <= hi):
            continue
        (reqs if kind == "req" else reps).append((ts, raw))

    print(f"{os.path.basename(a.log)}  window {lo/3600:.2f}..{hi/3600:.2f} h:"
          f"  {len(reqs)} requests, {len(reps)} replies")

    counts: dict[str, int] = {}
    for _, raw in reqs:
        t = topic_of(raw)
        counts[t] = counts.get(t, 0) + 1
    for t, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:6d}  {t}")
    if a.census:
        return 0

    if a.names:
        seen = {}
        for ts, raw in reqs:
            try:
                j = decode(raw).json() or {}
            except Exception:                    # noqa: BLE001
                continue
            if isinstance(j, dict) and "fileName" in j:
                kind = "transport" if "fileSize" in j else "transported"
                seen.setdefault(j["fileName"], []).append((ts, kind,
                                                           j.get("fileSize")))
        names = sorted(seen)
        print(f"\n{len(names)} distinct file names, first 12 and last 12:")
        for n in names[:12] + names[-12:]:
            ent = seen[n]
            print(f"  {n:<34} {ent[0][0]}  size={ent[0][2]}")
        return 0

    if a.replies:
        rc: dict[str, int] = {}
        for ts, raw in reps:
            line = topic_of(raw)
            try:
                j = decode(raw).json()
                if j is not None:
                    line += " " + str(j)
            except Exception:                    # noqa: BLE001
                pass
            rc[line] = rc.get(line, 0) + 1
        for line, n in sorted(rc.items(), key=lambda kv: -kv[1])[:25]:
            print(f"  {n:6d}  {line}")
        return 0

    run = 0
    for ts, raw in reqs:
        t = topic_of(raw)
        base = t.split(" ")[1] if len(t.split(" ")) > 1 else t
        if base in PICTURE:
            run += 1
            continue
        if run:
            print(f"  .... {run} picture upload frames "
                  f"(transport + transported) ....")
            run = 0
        print(f"  {ts}  {t:<26} {body_of(raw)}")
    if run:
        print(f"  .... {run} picture upload frames ....")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
