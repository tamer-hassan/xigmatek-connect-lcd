#!/usr/bin/env python3
"""Does the panel answer an upload differently if we keep ALPHA's ordering?

One upload of one real vendor frame, as ALPHA's log records it (24 305 bytes):

    +0     POST transport 1 {...,"fileSize":24305,...}
    +11    reply {"state":"success","blockMaxSize":1024}   grant, while
    ...    the file bytes are still being streamed (ALPHA does not wait for it)
    ...    24 blocks on the wire inside 10 ms
    +22    reply 1 200, empty body                        the file's verdict
    +23    POST transported 1 {"md5":"todo",...}          ALPHA never waits
    +36    reply {"state":"success"}                      the ack ALPHA sees

One thing we do differently from ALPHA, easy to miss because both appear to work:

* our `transported` goes out immediately after the last file byte, i.e. while
  the media writer is still busy - ALPHA's goes out a millisecond after the
  panel's own notice.  Our probe has never seen the `{"state":"success"}` ack
  for it; ALPHA's log has 905 of them.
So this probe runs the same file with both orders and reports, for each, which
of the three answers arrive and how late.  The counts matter more than the
milliseconds: an ack that only appears in the notice-first order is a real
difference in what the panel thinks happened.  Everything else stays the burst
we know the panel takes - grant and notice are read afterwards, as they land.
"""
import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import Link, MEDIA_CHUNK, MEDIA_GAP    # noqa: E402

# tag, chunk, gap, when `transported` goes out.  `notice` is what ALPHA's log
# shows and the only order that makes the glass redraw; `fast` is what our
# client used to do.  The gap column is the pause between the `transport`
# announcement and the first file byte.
VARIANTS = (("ours   ", MEDIA_CHUNK, MEDIA_GAP, "fast"),
            ("notice ", MEDIA_CHUNK, MEDIA_GAP, "notice"),
            ("vendor ", 1024, 0.011, "notice"),
            ("tight  ", 1024, 0.0, "notice"))

VENDOR = {"grant": 11.0, "verdict": 22.0, "transported": 23.0, "ack": 36.0}
SEEK = 1.5                        # how long to keep listening after the last send


def classify(m):
    """grant / verdict / ack, by what the frame contains rather than its label."""
    body = (m.body or b"").decode("utf-8", "replace").strip()
    if "blockMaxSize" in body:
        return "grant", body
    if '"state"' in body:
        return "ack", body
    if not body:
        return "verdict", m.code
    return None, body


def upload(ln, name, blob, chunk, gap, order, dump=False):
    """One upload, timed at every answer.  `order` is 'fast' or 'notice'.

    The burst is kept exactly as the panel wants it - announce, 20 ms, all the
    file bytes, and the answers read as they land afterwards.  Reading the
    `blockMaxSize` grant before writing is not an option: the media writer
    behind the announcement is on a short timer and every ack-first attempt we
    have measured was refused with `1 400` (PROTOCOL.md §6).
    """
    t, got = {}, {}
    t["announce"] = time.monotonic()
    ln.post("transport", {"type": "media", "fileSize": len(blob),
                          "fileName": name})
    if gap:
        time.sleep(gap)
    ln.send_raw(blob, chunk=chunk)
    t["bytes"] = time.monotonic()

    def send_reported():
        s2 = ln.post("transported", {"md5": "todo", "fileName": name})
        t["transported"] = time.monotonic()
        return s2

    if order == "notice":
        # wait for the panel's own verdict for the file before declaring it done
        deadline = t["bytes"] + SEEK
        while "verdict" not in t and time.monotonic() < deadline:
            m = ln.read(timeout=max(0.0, deadline - time.monotonic()))
            if m is None:
                break
            stamp(m, t, got, dump)
        seq2 = send_reported()
    else:
        seq2 = send_reported()

    deadline = time.monotonic() + SEEK
    while time.monotonic() < deadline:
        m = ln.read(timeout=max(0.0, deadline - time.monotonic()))
        if m is None:
            break
        stamp(m, t, got, dump)
    t["bytes_ms"] = (t["bytes"] - t["announce"]) * 1000
    return t, got


def stamp(m, t, got, dump=False):
    now = time.monotonic()
    kind, info = classify(m)
    if dump:
        print(f"      +{(now - t['announce']) * 1000:6.1f} ms  {m.line:16} "
              f"Ack={m.headers.get('AckNumber'):>3}  {info[:56]!r}")
    if kind and kind not in t:
        t[kind] = now
        got[kind] = info
    return kind


def report(tag, rows, blob_len, chunk, gap, order):
    n = len(rows)
    code = sorted({r["got"].get("verdict") for r in rows if r["got"].get("verdict")})
    print(f"\n{tag}: order={order} chunk={chunk} gap={gap} bytes={blob_len} "
          f"n={n} notice codes={code}")
    for key in ("grant", "bytes", "verdict", "transported", "ack"):
        v = [(r["t"][key] - r["t"]["announce"]) * 1000 for r in rows if key in r["t"]]
        seen = f"{len(v)}/{n}"
        if not v:
            print(f"   {key:11} {seen:>6}  never                      "
                  f"  vendor {VENDOR.get(key, 0):>5.0f} ms")
            continue
        print(f"   {key:11} {seen:>6}  median {statistics.median(v):6.1f} ms  "
              f"min {min(v):6.1f}  max {max(v):6.1f}   "
              f"vendor {VENDOR.get(key, 0):>5.0f} ms")
    acks = [r for r in rows if "ack" in r["t"]]
    print(f"   `transported` answered: {len(acks)}/{n}"
          f"{'  body: ' + acks[0]['got']['ack'][:60] if acks else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--only", default="",
                    help="run only these variants, in the order asked for "
                         "(ours, notice, vendor, tight).  Order matters when "
                         "the question is whether a session already warmed up "
                         "by accepted uploads behaves differently: put the "
                         "variant you doubt first and it runs on a fresh "
                         "session.")
    ap.add_argument("--name", default="2026-11-05_15-17-55-418.osd",
                    help="one of ALPHA's own names, so the panel sees a file "
                         "it has seen before")
    a = ap.parse_args()

    d = "data/vendor_frames"
    blob = open(os.path.join(d, sorted(os.listdir(d))[0]), "rb").read()
    print(f"uploading {a.name} ({len(blob)} bytes) {a.frames}x per variant",
          flush=True)

    with Link(a.device, timeout=3.0) as ln:
        ln.start_pump()
        info = ln.hello(60)
        print(f"panel: {info.get('sn')} space={info.get('space')}", flush=True)
        # same settle the display tools use: the first upload of a session,
        # sent straight after the handshake, comes back 400
        time.sleep(0.6)
        ln.drain(0.2)
        by_tag = {tag.strip(): (tag, chunk, gap, order)
                  for tag, chunk, gap, order in VARIANTS}
        seq = [by_tag[w.strip()] for w in a.only.split(",") if w.strip()] or VARIANTS
        for tag, chunk, gap, order in seq:
            rows = []
            for i in range(a.frames):
                try:
                    t, got = upload(ln, a.name, blob, chunk, gap, order,
                                    dump=(i < 2))
                    rows.append({"t": t, "got": got})
                except Exception as exc:                       # noqa: BLE001
                    print(f"   !! upload {i} failed: {exc}", flush=True)
                time.sleep(0.6)
            if rows:
                report(tag, rows, len(blob), chunk, gap, order)
            # start the next variant from a fresh session, with the same settle
            # the first one gets: the first upload straight after a handshake is
            # refused for its own reason (§6), and that would hide the effect
            # being measured here
            ln.hello(60)
            time.sleep(0.6)
            ln.drain(0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
