#!/usr/bin/env python3
"""Does a `transport` frame without a ContentLength header really switch the media
writer off?

PROTOCOL.md §6 says the header is required, and that the failure is the quiet one: the
panel answers *nothing* - no ack for the request, no file notice.  That was measured by
an ad-hoc script that no longer exists, and the same document has just had to correct a
counting error of exactly this kind (a `grant` line was read as if it were the file's
verdict).  So: re-run it and keep the three answers apart.

One upload has up to four answers, and only one of them is the verdict:

    grant    the ack for the `transport` request, body has `blockMaxSize`
    notice   the file's verdict - unlabelled, AckNumber 0, body `200` or `400`
    ack      the reply to `transported`, body {"state":"success"}

A refusal is a `400` notice, which is a *reply*.  Silence means no replies at all, and
that is what a missing ContentLength does.  Nothing here writes a config topic.

    python3 tools/cltest.py [--frames 6]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import protocol as p  # noqa: E402

VENDOR_NAME = "2026-11-05_15-17-55-418.osd"
SETTLE = 0.6        # first upload of a session, sent straight after the handshake, is refused
WAIT = 1.2          # long enough for a notice and for the panel's ~0.5 s give-up


def collect(ln, deadline):
    """Return (grant, notice_code, ack) seen before the deadline.

    The notice is the only one of the three that decides anything, and it is the
    one with no label on it: `AckNumber == "0"` as a string, exactly as
    Link.read_notice() matches it.
    """
    grant = notice = ack = None
    while time.monotonic() < deadline:
        m = ln.read(timeout=max(0.0, deadline - time.monotonic()))
        if m is None:
            break
        body = m.body or b""
        if m.headers.get("AckNumber") == "0":
            notice = f"{m.code} {body.decode('latin-1')[:12].strip()}"
        elif b"blockMaxSize" in body:
            grant = m.code
        elif b'"state":"success"' in body.replace(b" ", b""):
            ack = m.code
    return grant, notice, ack


def upload(ln, blob, name, with_header):
    """One upload, announced with or without the ContentLength header."""
    obj = {"type": "media", "fileSize": len(blob), "fileName": name}
    seq = ln.seq
    if with_header:
        seq = ln.post("transport", obj)
    else:
        hdrs = {"SeqNumber": seq, "Date": int(time.time() * 1000),
                "ContentType": "json"}          # everything else ALPHA sends, minus the length
        ln.ser.write(p.encode(f"POST transport 1", hdrs, obj))
        ln.seq += 1
    time.sleep(p.MEDIA_GAP)
    ln.send_raw(blob, chunk=p.MEDIA_CHUNK)
    t0 = time.monotonic()
    grant, notice, ack = collect(ln, t0 + WAIT)
    ln.post("transported", {"md5": "todo", "fileName": name})
    g2, n2, a2 = collect(ln, time.monotonic() + 0.6)
    return grant or g2, notice or n2, ack or a2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--name", default=VENDOR_NAME,
                    help="a name the panel has already seen, so only the header differs")
    a = ap.parse_args()

    d = "data/vendor_frames"
    blob = open(os.path.join(d, sorted(os.listdir(d))[0]), "rb").read()
    print(f"{len(blob)} bytes, {a.frames} uploads per variant, name {a.name}", flush=True)

    with p.Link(a.device, timeout=2.0) as ln:
        ln.start_pump()
        info = ln.hello(60)
        print(f"panel: {info.get('sn')} space={info.get('space')}", flush=True)
        time.sleep(SETTLE)
        ln.drain(0.2)
        for with_header in (True, False):
            got = []
            for i in range(a.frames):
                got.append(upload(ln, blob, a.name, with_header))
                time.sleep(0.35)
            tag = "with ContentLength   " if with_header else "without ContentLength"
            print(f"\n{tag}: grant={sum(1 for g, _, _ in got if g)}"
                  f" notice={sum(1 for _, n, _ in got if n)}"
                  f" transported-ack={sum(1 for _, _, c in got if c)}", flush=True)
            print(f"   verdicts: {[n for _, n, _ in got]}", flush=True)
            print(f"   grants:   {[g for g, _, _ in got]}  acks: {[c for _, _, c in got]}",
                  flush=True)
            ln.drain(0.3)
            # the unannounced file bytes go into a media writer that was never
            # switched on, so start the next variant from a fresh session
            ln.hello(60)
            time.sleep(SETTLE)
            ln.drain(0.2)
    print("\nonly the notice is the file's verdict: 200 took the file, 400 did not, "
          "None means the panel never answered at all", flush=True)


if __name__ == "__main__":
    main()
