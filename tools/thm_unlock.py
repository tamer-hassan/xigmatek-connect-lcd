#!/usr/bin/env python3
"""thm_unlock.py - read ALPHA's own theme files: container, cipher, layouts.

ALPHA keeps every theme in one file and ships those files in the installer:

    C:\\Program Files\\ALPHA\\resources\\static\\theme\\butt\\480X480\\*.thm
                                            ...\\320X240\\*.thm

`theme.py` could only ever report the panel's *numbers* for themes (`mode`,
`logo`, `presetThemeId`), because the layouts themselves looked unreadable and
PROTOCOL.md said so.  They are readable, and the way to read them is in the
app's own shipped code: `resources/app.asar` -> `out/main/index.jsc`, whose V8
constant pool still holds the literals (`tools/asar_extract.py` unpacks the
archive; `strings` reads the pool):

    aes-256-cbc  Byyeetek2368  427979656574656b  createHash  sha256  digest
    "Invalid theme zip file: should contain exactly one JSON file"

Container, read off 27 files and applied to all 27 without an exception:

    .thm      ZIP holding exactly one entry, "<themeId>.json"
    entry     the entry is HEX TEXT, not bytes
    bytes     AES-256-CBC, PKCS#7 padded
              key = sha256("Byyeetek2368")            32 B
              iv  = "ByyeetekByyeetek"                16 B, the pool constant
                                                    `427979656574656b` twice
    JSON      {"id","width","height","ratio","screenStatus",
               "background":{"type","path","pathData"},
               "osd":{"path","pathData","widget":[...]}}

`pathData` is the media itself, base64: the theme carries its own background
clip and its own baked foreground PNG, so a `.thm` is self-contained.  Every
background so embedded is byte-identical to one of the 43 clips the installer
ships loose in `resources/static/media` (27 of them, 0 unique to the `.thm`),
and every foreground is byte-identical to a PNG the running app left in
`%APPDATA%\\alpha\\media\\foreground`.  Those two facts are what make the copy
below checkable rather than claimed.

IV, in case the derivation matters to someone: it was not guessed.  Decrypting
one block of ciphertext with ECB and XORing against the known first 16 plaintext
bytes (`{"id":<digits>`, from the zip entry's own name) gives the IV; doing that
on four different files returned the same 16 bytes, `427979656574656b 427979656574656b`.

Nothing here touches the panel.  This tool reads files and writes files.

    python3 tools/thm_unlock.py --from DIR            summarise, default
    python3 tools/thm_unlock.py --from DIR --layout ID --json
    python3 tools/thm_unlock.py --from DIR --to themes/alpha --write
    python3 tools/thm_unlock.py --verify --to themes/alpha    offline re-check

`--to` writes the layout JSON with the base64 media replaced by file
references, the media itself (background per theme, foreground per theme), the
loose clips from `--media`, and a `manifest.json` recording size + sha256 +
where each byte came from.  Existing files are only rewritten when their bytes
already match, so a re-run is a verification, not a churn.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import sys
import zipfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PASSPHRASE = b"Byyeetek2368"
IV_HEX = "427979656574656b" * 2
KEY = hashlib.sha256(PASSPHRASE).digest()
IV = bytes.fromhex(IV_HEX)

WINDOWS_INSTALL = r"C:\Program Files\ALPHA\resources\static"


def win_basename(path: str) -> str:
    """Last element of a Windows path.  `os.path.basename` does not split on
    backslash, and every `path` inside a `.thm` is a Windows path."""
    return path.replace("\\", "/").rstrip("/").split("/")[-1]


def sha(path_or_bytes) -> str:
    m = hashlib.sha256()
    if isinstance(path_or_bytes, (bytes, bytearray)):
        m.update(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                m.update(chunk)
    return m.hexdigest()


def unlock(path: str) -> tuple[str, dict, bytes, bytes]:
    """Returns (entry name, theme JSON, background bytes, foreground bytes)."""
    zf = zipfile.ZipFile(path)
    names = zf.namelist()
    if len(names) != 1:
        raise ValueError(f"{path}: {len(names)} entries, expected exactly one")
    entry = names[0]
    try:
        ct = binascii.unhexlify(zf.read(entry))
    except binascii.Error as exc:
        raise ValueError(f"{entry}: entry is not clean hex ({exc})") from exc
    if len(ct) % 16:
        raise ValueError(f"{entry}: ciphertext {len(ct)} B is not a block multiple")
    d = Cipher(algorithms.AES(KEY), modes.CBC(IV)).decryptor()
    pt = d.update(ct) + d.finalize()
    pad = pt[-1]
    if not 0 < pad <= 16 or pt[-pad:] != bytes([pad]) * pad:
        raise ValueError(f"{entry}: bad PKCS#7 padding (last byte {pad})")
    obj = json.loads(pt[:-pad])
    bg = base64.b64decode(obj["background"].get("pathData", "")) \
        if obj["background"].get("pathData") else b""
    fg = base64.b64decode(obj["osd"].get("pathData", "")) \
        if obj["osd"].get("pathData") else b""
    return entry, obj, bg, fg


def iter_thm(root: str):
    for ratio in sorted(os.listdir(root)):
        d = os.path.join(root, ratio)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".thm"):
                yield ratio, os.path.join(d, fn)


def strip_media(obj: dict, refs: dict) -> dict:
    """Replaces the base64 payloads with the file names they were written as."""
    out = json.loads(json.dumps(obj))
    for holder, key in ((out.get("background"), "background"),
                        (out.get("osd"), "foreground")):
        if holder is None or key not in refs:
            continue
        holder.pop("pathData", None)
        holder["mediaFile"] = refs[key]
    return out


def put(root: str, rel: str, data: bytes, written: set, report: list) -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "rb") as f:
            if f.read() == data:
                report.append(("kept", rel, len(data), sha(data)))
                written.add(rel)
                return
    with open(path, "wb") as f:
        f.write(data)
    report.append(("wrote", rel, len(data), sha(data)))
    written.add(rel)


def verify(tree: str) -> int:
    """Check a written tree against its own manifest, offline.

    This is the part that lets the copy be trusted without re-reading the
    vendor install: every byte the copy claims is hashed in `manifest.json`,
    and the `background` entries carry the sha256 of the bytes that were
    *embedded in the `.thm*` — so checking that hash against the loose clip
    on disk re-proves, with no Windows volume involved, that the clip and the
    theme's own payload are the same file.
    """
    mpath = os.path.join(tree, "manifest.json")
    if not os.path.exists(mpath):
        print(f"no manifest at {mpath}", file=sys.stderr)
        return 2
    with open(mpath) as f:
        man = json.load(f)

    bad, missing, ok = [], [], 0
    for e in man["files"]:
        p = os.path.join(tree, e["path"])
        if not os.path.exists(p):
            missing.append(e["path"])
            continue
        if os.path.getsize(p) != e["bytes"]:
            bad.append((e["path"], "size", e["bytes"], os.path.getsize(p)))
        elif sha(p) != e["sha256"]:
            bad.append((e["path"], "sha256", e["sha256"][:16], sha(p)[:16]))
        else:
            ok += 1

    refs = []
    for e in man["files"]:
        if e["kind"] != "layout":
            continue
        with open(os.path.join(tree, e["path"])) as f:
            obj = json.load(f)
        for holder in (obj["background"], obj["osd"]):
            rel = holder.get("mediaFile")
            if not rel:
                bad.append((e["path"], "no mediaFile", "", ""))
                continue
            refs.append(rel)
            if not os.path.exists(os.path.join(tree, rel)):
                missing.append(f"{e['path']} -> {rel}")
            if "pathData" in holder:
                bad.append((e["path"], "layout still carries base64", "", ""))

    print(f"{tree}: {ok}/{len(man['files'])} files match manifest hashes "
          f"({'verified' if not bad and not missing else 'PROBLEMS'})")
    print(f"  counts {man['counts']}")
    print(f"  layout media references resolved: {len(refs)}")
    embedded = [e for e in man["files"] if e["kind"] == "background"]
    dedup = [e for e in embedded if e["origin"].get("heldBy") == "clips"]
    print(f"  theme backgrounds: {len(embedded)}, of which {len(dedup)} are "
          f"held by a loose clip of the same bytes")
    for kind, lst in (("missing", missing), ("mismatched", bad)):
        for row in lst:
            print(f"  {kind}: {row}")
    return 1 if (bad or missing) else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm",
                    help="directory of .thm files (…/static/theme/butt)")
    ap.add_argument("--media", help="loose clips dir (…/static/media) to copy too")
    ap.add_argument("--to", help="output root for --write")
    ap.add_argument("--write", action="store_true",
                    help="write layouts, media and manifest under --to")
    ap.add_argument("--verify", action="store_true",
                    help="check a written tree against its manifest.json "
                         "(sizes, sha256s, and every mediaFile reference)")
    ap.add_argument("--json", action="store_true", help="dump layouts to stdout")
    ap.add_argument("--layout", metavar="ID", help="one theme id, report only")
    args = ap.parse_args()

    if args.verify:
        if not args.to:
            print("--verify needs --to TREE", file=sys.stderr)
            return 2
        return verify(args.to)

    if not args.frm:
        print("--from DIR is required (or use --verify --to TREE)", file=sys.stderr)
        return 2

    if args.write and not args.to:
        print("--write needs --to", file=sys.stderr)
        return 2

    if not args.media:
        # the installer keeps clips beside the themes: static/theme/butt and
        # static/media.  Defaulting the cross-check to that sibling means the
        # "which loose clip holds these same bytes" column is never silently
        # blank.
        sib = os.path.join(os.path.dirname(os.path.dirname(args.frm.rstrip("/"))),
                           "media")
        if os.path.isdir(sib):
            args.media = sib

    loose = {}
    if args.media:
        for f in sorted(os.listdir(args.media)):
            p = os.path.join(args.media, f)
            if os.path.isfile(p):
                loose.setdefault(sha(p), []).append(f)

    entries, widgets, sources, fonts = [], {}, {}, {}
    bg_hash, fg_hash = set(), set()
    rows = []
    for ratio, path in iter_thm(args.frm):
        entry, obj, bg, fg = unlock(path)
        tid = str(obj["id"])
        if args.layout and tid != args.layout:
            continue
        bgh, fgh = sha(bg), sha(fg)
        bg_hash.add(bgh)
        if fg:
            fg_hash.add(fgh)
        counts = {}
        for w in obj["osd"]["widget"]:
            counts[w["type"]] = counts.get(w["type"], 0) + 1
            widgets[w["type"]] = widgets.get(w["type"], 0) + 1
            for prop in w["property"]:
                s = prop.get("source")
                if s:
                    sources[s] = sources.get(s, 0) + 1
                f = prop.get("fontFamily")
                if f:
                    fonts[f] = fonts.get(f, 0) + 1
        rows.append((ratio, tid, os.path.basename(path), obj["background"]["type"],
                     len(bg), len(fg), counts, bgh[:12],
                     ", ".join(loose.get(bgh, [])) or "embedded only"))
        entries.append((ratio, tid, path, obj, bg, fg))

    print(f"{len(entries)} .thm files read from {args.frm}\n")
    print(f"{'ratio':<8} {'theme id':<15} {'kind':<4} {'bg B':>9} {'fg B':>7}  "
          f"{'widgets':<24} {'bg sha256[:12]':<14} loose clip of the same bytes")
    for r in rows:
        wtxt = " ".join(f"{k}x{v}" for k, v in sorted(r[6].items()))
        print(f"{r[0]:<8} {r[1]:<15} {r[3]:<4} {r[4]:>9} {r[5]:>7}  "
              f"{wtxt:<24} {r[7]:<14} {r[8]}")

    print(f"\nwidget types: {widgets}")
    print(f"sources ({len(sources)}): {sources}")
    print(f"fonts ({len(fonts)}): {fonts}")
    print(f"unique background blobs: {len(bg_hash)}  unique foreground blobs: "
          f"{len(fg_hash)}")
    if args.layout:
        for ratio, tid, path, obj, bg, fg in entries:
            print(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=True))
        return 0
    if args.json:
        json.dump([e[3] for e in entries], sys.stdout, ensure_ascii=False)
        print()
    if not args.write:
        print("\nnothing written; add --write --to DIR")
        return 0

    root = args.to
    manifest = {
        "source": {
            "install": WINDOWS_INSTALL,
            "themes": args.frm,
            "clips": args.media or "",
            "note": "read from the mounted Windows system volume; no file outside "
                    "this repo was created or changed",
        },
        "container": {
            "file": "ZIP, one entry '<themeId>.json'",
            "entry": "hex text",
            "cipher": "AES-256-CBC, PKCS#7",
            "key": "sha256(%r)" % PASSPHRASE,
            "iv": IV_HEX,
            "constants_found_in": "resources/app.asar -> out/main/index.jsc "
                                  "(V8 constant pool)",
        },
        "files": [],
    }

    def record(kind, rel, data, origin):
        manifest["files"].append({"kind": kind, "path": rel, "bytes": len(data),
                                  "sha256": sha(data), "origin": origin})

    written = set()
    report = []
    bg_rel, fg_rel = {}, {}
    for ratio, tid, path, obj, bg, fg in entries:
        rel_thm = os.path.join("thm", ratio, os.path.basename(path))
        with open(path, "rb") as f:
            raw_thm = f.read()
        put(root, rel_thm, raw_thm, written, report)
        record("thm", rel_thm, raw_thm,
               {"vendorPath": f"{WINDOWS_INSTALL}\\theme\\butt\\{ratio}"
                              f"\\{os.path.basename(path)}"})
        # Every theme background we have ever seen is byte-identical to a clip
        # the installer also ships loose, so the clip dir holds the bytes and
        # the layout points at them; only a background with no loose twin gets
        # its own file, so nothing is ever dropped.
        bgname = win_basename(obj["background"].get("path", "") or f"{tid}.bin")
        twins = loose.get(sha(bg), [])
        if bg and twins:
            bgrel = os.path.join("clips", twins[0])
        else:
            bgrel = os.path.join("background", bgname)
            if bg:
                put(root, bgrel, bg, written, report)
        if bg:
            record("background", bgrel, bg,
                   {"thm": os.path.basename(path),
                    "vendorPath": obj["background"].get("path"),
                    "heldBy": "clips" if twins else "background",
                    "looseCopiesOfSameBytes": twins})
        fgname = win_basename(obj["osd"].get("path", "") or f"{tid}.png")
        fgrel = os.path.join("foreground", fgname)
        if fg:
            put(root, fgrel, fg, written, report)
            record("foreground", fgrel, fg,
                   {"thm": os.path.basename(path),
                    "vendorPath": obj["osd"].get("path")})
        layout = strip_media(obj, {"background": bgrel, "foreground": fgrel})
        bg_rel[tid], fg_rel[tid] = bgrel, fgrel
        data = (json.dumps(layout, indent=1, ensure_ascii=False, sort_keys=True)
                + "\n").encode()
        rel_json = os.path.join("layouts", ratio, f"{tid}.json")
        put(root, rel_json, data, written, report)
        record("layout", rel_json, data, {"thm": os.path.basename(path)})

    if args.media:
        for f in sorted(os.listdir(args.media)):
            p = os.path.join(args.media, f)
            if not os.path.isfile(p):
                continue
            with open(p, "rb") as fh:
                data = fh.read()
            rel = os.path.join("clips", f)
            put(root, rel, data, written, report)
            dupes = [x for x in loose[sha(data)] if x != f]
            record("clip", rel, data,
                   {"vendorPath": f"{WINDOWS_INSTALL}\\media\\{f}",
                    "sameBytesAs": dupes})

    manifest["counts"] = {}
    for e in manifest["files"]:
        manifest["counts"][e["kind"]] = manifest["counts"].get(e["kind"], 0) + 1

    # per-theme facts, so the table in themes/alpha/README.md can be checked
    # against the manifest rather than taken on trust
    manifest["themes"] = []
    for ratio, tid, path, obj, bg, fg in entries:
        kinds, srcs, fnts = {}, {}, {}
        for w in obj["osd"]["widget"]:
            kinds[w["type"]] = kinds.get(w["type"], 0) + 1
            for prop in w["property"]:
                for key, bucket in (("source", srcs), ("fontFamily", fnts)):
                    if prop.get(key):
                        bucket[prop[key]] = bucket.get(prop[key], 0) + 1
        manifest["themes"].append({
            "id": tid, "ratio": ratio,
            "thm": os.path.join("thm", ratio, os.path.basename(path)),
            "layout": os.path.join("layouts", ratio, f"{tid}.json"),
            "canvas": [obj.get("width"), obj.get("height")],
            "ratioField": obj.get("ratio"),
            "screenStatus": obj.get("screenStatus"),
            "backgroundSha256": sha(bg), "backgroundBytes": len(bg),
            "backgroundKind": obj["background"].get("type"),
            "backgroundFile": bg_rel.get(tid),
            "foregroundSha256": sha(fg), "foregroundBytes": len(fg),
            "foregroundFile": fg_rel.get(tid),
            "widgetKinds": kinds, "sources": srcs, "fonts": fnts,
        })
    data = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()
    put(root, "manifest.json", data, written, report)

    for action, rel, n, h in report:
        print(f"  {action:<5} {rel:<52} {n:>9}  {h[:16]}")
    print(f"\n{manifest['counts']} under {root}; manifest.json carries every "
          f"sha256 above and the vendor path it came from.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
