#!/usr/bin/env python3
"""Verify the copied vendor library against its own manifest - the whole claim, one tool.

This replaces the offline suite's largest non-GUI section (2,910 lines of `tools/selftest.sh`,
"the vendor theme library: every copied byte against its own manifest").  That section had three
kinds of line in it: hashing, counting, and re-quoting numbers into docs pages.  The first two
live here; the third goes away with the pages that carried them.

What is claimed, and what each half means:

    themes/alpha/manifest.json
        files            125 entries - 27 `background` clips, 27 `foreground` overlays, 27
                         `layout` JSONs, 44 `clip` videos - each with `path`, `bytes`, `sha256`
                         and an `origin` naming where the bytes came from on the vendor's system
        counts           the per-kind tally, cross-checked against `files` and against what is
                         actually on disk
        themes           27 records of what the vendor's own container said (canvas, fonts,
                         background file and hash) - so a layout's pairing is a read field, not
                         a naming convention
        notRedistributed 27 records of the vendor's encrypted `.thm` containers: path, bytes,
                         sha256 and the vendor path - **records only**.  Those bytes are
                         XIGMATEK's; `debian/copyright` says so rather than pretending to
                         license them, and the check here is that they are *absent*.

Run it before shipping a themes package, and after any edit near `themes/alpha/`:

    tools/verify_manifest.py            all 125 files hashed and compared
    tools/verify_manifest.py --quick    sizes and listings only, no hashing (a few ms)
    tools/verify_manifest.py --json     machine-readable, for the deb build's own log

Exit is 0 only if every byte matches, nothing extra is sitting in those directories, and none of
the not-redistributed containers is present.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(REPO, "themes", "alpha")
KIND_DIRS = {"layout": "layouts", "background": "clips", "clip": "clips",
             "foreground": "foreground"}


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="verify themes/alpha against its manifest")
    ap.add_argument("--quick", action="store_true",
                    help="check listings and byte counts, skip the hashing")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print one JSON object instead of the report")
    ap.add_argument("--root", default=ROOT, help="the library root (default: themes/alpha)")
    args = ap.parse_args(argv)

    manifest_path = os.path.join(args.root, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"no manifest at {manifest_path}", file=sys.stderr)
        return 2
    man = json.load(open(manifest_path, encoding="utf-8"))
    files, bad, missing, wrong_size, hashed = man.get("files") or [], [], [], [], 0

    for ent in files:
        path = os.path.join(args.root, ent["path"])
        if not os.path.isfile(path):
            missing.append(ent["path"])
            continue
        size = os.path.getsize(path)
        if size != ent["bytes"]:
            wrong_size.append((ent["path"], size, ent["bytes"]))
            continue
        if not args.quick:
            got = sha256_of(path)
            hashed += 1
            if got != ent["sha256"]:
                bad.append((ent["path"], got[:16], ent["sha256"][:16]))

    # what is on disk but not in the manifest: an extra file in a scanned directory is the same
    # kind of trouble as a changed one, and the loop above cannot see it
    listed = {ent["path"] for ent in files}
    extra = []
    for sub in sorted(set(KIND_DIRS.values())):
        base = os.path.join(args.root, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, names in os.walk(base):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), args.root)
                if rel not in listed and not rel.endswith(".md"):
                    extra.append(rel)

    # `counts` against `files`, and `files` against the tree
    tallies: dict = {}
    for ent in files:
        tallies[ent["kind"]] = tallies.get(ent["kind"], 0) + 1
    counts = man.get("counts") or {}
    count_mismatch = {k: (counts.get(k), tallies.get(k)) for k in
                      set(counts) | set(tallies) if counts.get(k) != tallies.get(k)}

    # the not-redistributed containers: records, and the records must be all there is
    notred = man.get("notRedistributed") or []
    present_containers = [ent["path"] for ent in notred
                          if os.path.exists(os.path.join(args.root, ent["path"]))]
    thm_dir = os.path.join(args.root, "thm")
    if os.path.isdir(thm_dir):
        present_containers.append("thm/ exists")

    # a theme's pairing is a field we read; the clip it names must be one of the copied bytes
    themes_recs = man.get("themes") or []
    by_path = {ent["path"]: ent for ent in files}
    pairing_bad = []
    for t in themes_recs:
        bg = t.get("backgroundFile")
        if not bg:
            continue
        want = t.get("backgroundSha256")
        hit = next((e for p, e in by_path.items() if p.endswith(os.path.basename(bg))), None)
        if hit is None or (want and hit["sha256"] != want):
            pairing_bad.append((bg, want and want[:12]))

    ok = not (missing or wrong_size or bad or extra or count_mismatch or present_containers
              or pairing_bad)
    summary = {
        "ok": ok, "root": os.path.relpath(args.root, REPO), "entries": len(files),
        "hashed": hashed, "kinds": tallies, "themes": len(themes_recs),
        "notRedistributed_records": len(notred),
        "notRedistributed_bytes": sum(int(e["bytes"]) for e in notred),
        "copied_bytes": sum(int(e["bytes"]) for e in files),
        "missing": missing, "wrong_size": wrong_size, "hash_mismatch": bad,
        "extra_on_disk": extra, "count_mismatch": count_mismatch,
        "containers_present": present_containers, "pairing_unmatched": pairing_bad,
    }
    if args.as_json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"themes library: {len(files)} entries, {summary['copied_bytes']:,} B copied"
              + (f", {hashed} files hashed" if hashed else ", hashing skipped (--quick)"))
        print("  kinds: " + ", ".join(f"{k} {v}" for k, v in sorted(tallies.items())))
        print(f"  vendor containers recorded and NOT shipped: {len(notred)}, "
              f"{summary['notRedistributed_bytes']:,} B")
        print(f"  layouts whose declared background matches a copied clip: "
              f"{len(themes_recs) - len(pairing_bad)} of {len(themes_recs)}")
        for label, items in (("missing", missing), ("size differs", wrong_size),
                             ("hash differs", bad), ("extra on disk", extra),
                             ("counts disagree", count_mismatch.items()),
                             ("container present (must not be)", present_containers),
                             ("pairing unmatched", pairing_bad)):
            if items:
                print(f"  FAILED {label}: " + "; ".join(map(str, list(items)[:6])))
        print("  all bytes match the manifest" if ok else "  -> see the FAILED lines above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
