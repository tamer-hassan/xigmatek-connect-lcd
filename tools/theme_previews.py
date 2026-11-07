#!/usr/bin/env python3
"""theme_previews.py - composite every copied ALPHA theme and put it on a sheet.

What was copied is only useful if it can be looked at, so this draws each theme
the way the vendor's own traffic does it: one frame lifted out of the theme's
background clip, with the theme's own baked foreground PNG composited over it.
The foreground is not our drawing - it is the bytes ALPHA embedded in the `.thm`
(`osd.pathData`), identical to what its `path` pointed at while it ran, which is
why the result is a picture of ALPHA's theme rather than a picture of our guess.

Per theme it also asks ffprobe what the clip actually is - frames, fps,
duration - and prints the answer, because those are the numbers that decide
whether a clip can be streamed at the frame rates this panel holds
(PROTOCOL.md: the vendor's own clips are 24-30 fps at 480x480).

    python3 tools/theme_previews.py                       -> docs/previews/
    python3 tools/theme_previews.py --ratio 480X480 --full

`--full` keeps the tiles at panel size (480x480); the default halves them so the
sheet stays a document rather than a 4 MB image.  Nothing here talks to the
panel: it reads files and writes PNGs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageFont                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALPHA = os.path.join(ROOT, "themes", "alpha")
TILE = 240


def probe(clip: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames,r_frame_rate,duration,width,height",
         "-show_entries", "format=duration", "-of", "json", clip],
        capture_output=True, text=True).stdout
    j = json.loads(out)
    s = (j.get("streams") or [{}])[0]
    num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    dur = float(s.get("duration") or j.get("format", {}).get("duration") or 0)
    frames = int(s.get("nb_frames") or 0) or int(round(fps * dur))
    return {"fps": fps, "dur": dur, "frames": frames,
            "width": int(s.get("width") or 0), "height": int(s.get("height") or 0)}


def frame(clip: str, at: float, tmp: str) -> str:
    dst = os.path.join(tmp, "frame.png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}",
                    "-i", clip, "-frames:v", "1", dst], check=True)
    return dst


def load_layouts(ratio: str):
    d = os.path.join(ALPHA, "layouts", ratio)
    for fn in sorted(os.listdir(d)):
        yield fn, json.load(open(os.path.join(d, fn)))


def media(obj: dict, key: str) -> str:
    holder = obj["osd"] if key == "foreground" else obj["background"]
    return os.path.join(ALPHA, holder["mediaFile"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", default="480X480",
                    help="480X480 (this panel) or 320X240")
    ap.add_argument("--full", action="store_true", help="keep tiles at panel size")
    ap.add_argument("--out", default=os.path.join("docs", "previews"))
    ap.add_argument("--t-at", type=float, default=1.0,
                    help="seconds into the clip to lift the frame from")
    args = ap.parse_args()

    layouts = list(load_layouts(args.ratio))
    if not layouts:
        print(f"no layouts for ratio {args.ratio}", file=sys.stderr)
        return 2
    tile = 480 if args.full else TILE
    cols = 4 if args.ratio == "480X480" else 4
    rows = -(-len(layouts) // cols)
    label = 26 if tile >= 480 else 18
    sheet = Image.new("RGB", (cols * tile, rows * (tile + label)), (16, 16, 18))
    draw = ImageDraw.Draw(sheet)
    try:
        fnt = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/"
                                 "DejaVuSans.ttf", 14 if tile >= 480 else 11)
    except OSError:
        fnt = ImageFont.load_default()

    print(f"{len(layouts)} themes, ratio {args.ratio}; "
          f"frame taken at {args.t_at}s\n")
    print(f"{'theme':<15} {'clip':<28} {'clip px':<9} {'fps':>6} {'frames':>7} "
          f"{'dur s':>7} {'fg':<24} widgets")
    with tempfile.TemporaryDirectory() as tmp:
        for i, (fn, obj) in enumerate(layouts):
            clip, fg = media(obj, "background"), media(obj, "foreground")
            still = obj["background"].get("type") != "MP4"
            if still:
                # a still background: no fps, no frames, and the shipped image
                # can be larger than the panel (the app scales it itself)
                im = Image.open(clip)
                p = {"fps": 0.0, "dur": 0.0, "frames": 1,
                     "width": im.size[0], "height": im.size[1]}
            else:
                p = probe(clip)
            kinds = {}
            for w in obj["osd"]["widget"]:
                kinds[w["type"]] = kinds.get(w["type"], 0) + 1
            ktxt = " ".join(f"{k}x{v}" for k, v in sorted(kinds.items()))
            fps_t = "still" if still else f"{p['fps']:.2f}"
            fr_t = "n/a" if still else str(p["frames"])
            dur_t = "n/a" if still else f"{p['dur']:.2f}"
            print(f"{obj['id']:<15} {os.path.basename(clip):<28} "
                  f"{p['width']:>4}x{p['height']:<4} {fps_t:>6} "
                  f"{fr_t:>7} {dur_t:>7} "
                  f"{os.path.basename(fg):<24} {ktxt}")

            src = clip if still else frame(
                clip, min(args.t_at, max(0.0, p["dur"] / 2)), tmp)
            img = Image.open(src).convert("RGB")
            if img.size != (obj["width"], obj["height"]):
                img = img.resize((obj["width"], obj["height"]))
            if os.path.exists(fg):
                over = Image.open(fg).convert("RGBA")
                if over.size != img.size:
                    over = over.resize(img.size)
                img = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
            if tile != obj["width"]:
                img = img.resize((tile, int(tile * obj["height"] / obj["width"])))
            x, y = (i % cols) * tile, (i // cols) * (tile + label)
            sheet.paste(img, (x, y))
            draw.text((x + 3, y + tile + 3),
                      f"{obj['id']}  {os.path.basename(clip)}", fill=(235, 235, 235),
                      font=fnt)

    out = os.path.join(ROOT, args.out)
    os.makedirs(out, exist_ok=True)
    name = f"alpha-themes-{args.ratio}{'-full' if args.full else ''}.png"
    dst = os.path.join(out, name)
    sheet.save(dst)
    print(f"\nwrote {os.path.relpath(dst, ROOT)}  {sheet.size[0]}x{sheet.size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
