"""Re-encode every frame captured on Windows and compare byte-for-byte."""
import os
import re, sys, json, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import encode, decode, checksum_ok, read_frame, compact

def records(path):
    d = open(path, 'rb').read().decode('utf-16-le', errors='replace')
    out = []
    for l in d.split('\r\n')[1:]:
        f = l.split('\t')
        if len(f) < 11:
            continue
        h = re.sub(r'[^0-9a-fA-F ]', '', f[5].strip())
        try:
            raw = bytes.fromhex(h) if h else b''
        except Exception:
            raw = b''
        out.append((int(f[0]), f[2], f[3], raw))
    return out

def stream(recs, fn, dr):
    return b''.join(r[3] for r in recs if r[1] == fn and r[2] == dr)

def frames(s):
    """Split a byte stream into frames + the unframed file payloads between them."""
    i, out, runs = 0, [], []
    while i < len(s):
        got = False
        if s[i] == 0x5A:
            fr = read_frame(s, i)
            if fr:
                fr, i = fr
                out.append(fr)
                got = True
                m = decode(fr)
                if m.line.startswith('POST transport ') and m.body:
                    try:
                        fs = json.loads(m.body).get('fileSize')
                    except Exception:
                        fs = None
                    if isinstance(fs, int) and i + fs <= len(s):
                        i += fs
        if not got:
            j = s.find(b'Z', i + 1)
            runs.append((i, j if j > 0 else len(s)))
            i = j if j > 0 else len(s)
    return out, runs

def main():
    if len(sys.argv) < 2:
        print("usage: verify_protocol.py CAPTURE [CAPTURE ...]\n"
              "  CAPTURE is a serial monitor's text render (UTF-16, one row per serial\n"
              "  IRP - tools/vendor_capture.py documents the columns).  The author's two\n"
              "  Windows sessions are bench files under data/captures/, which .gitignore\n"
              "  keeps out of the repo, so a fresh clone has none to point at here: see\n"
              "  README.md, 'Licence', for what that costs and what it means.")
        return 2
    tot = collections.Counter()
    cl_ok = collections.Counter()
    diffs = []
    sent = replies = ck_ok = 0
    for path in sys.argv[1:]:
        recs = records(path)
        for fn, dr in (('IRP_MJ_WRITE', 'DOWN'), ('IRP_MJ_READ', 'UP')):
            frs, runs = frames(stream(recs, fn, dr))
            print('%-46s %-14s %-4s frames=%4d unframed=%d bytes' %
                  (path.split('/')[-1][:44], fn, dr, len(frs), sum(b - a for a, b in runs)))
            for fr in frs:
                m = decode(fr)
                tot[(m.line, bool(m.body))] += 1
                if fn != 'IRP_MJ_WRITE':
                    # the panel's own frames: no re-encoding to do, but the strict
                    # checksum is a claim we make about them, so check it here
                    replies += 1
                    ck_ok += checksum_ok(fr)
                    continue
                sent += 1
                obj = json.loads(m.body) if m.body else None
                # rebuild the header block from scratch: a true round-trip test
                hdrs = {k: m.headers[k] for k in ("SeqNumber", "Date") if k in m.headers}
                if obj is not None:
                    hdrs["ContentType"] = "json"
                    hdrs["ContentLength"] = len(compact(obj))
                mine = encode(m.line, hdrs, obj if obj is not None else b"")
                if mine != fr:
                    diffs.append((m.line, fr, mine))
                if m.body and "ContentLength" in m.headers:
                    cl_ok[m.headers["ContentLength"] == str(len(compact(obj)))] += 1

    print('\nframe kinds:', dict(tot))
    print('ContentLength matches unescaped JSON length:', dict(cl_ok))
    print('host->panel frames re-encoded: %d, mismatched frames: %d'
          % (sent, len(diffs)))
    print('panel replies read: %d, strict checksum ok: %d' % (replies, ck_ok))
    for line, ref, mine in diffs[:4]:
        print('\n%s' % line)
        print('  ref  %r' % ref[:120])
        print('  mine %r' % mine[:120])
        print('  reflen=%d minelen=%d' % (len(ref), len(mine)))


if __name__ == '__main__':
    sys.exit(main())
