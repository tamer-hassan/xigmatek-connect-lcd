#!/usr/bin/env python3
"""preview_gif.py - the preview pane's animated composite, written out as a file.

One code path with the window: `clips.ClipPlayer` decodes the background in order,
`render.draw` draws this program's layer over it (theme, clock size, scrim and the
chosen text colour included), and what comes out is what `xigmaui` shows in its
preview pane while `playing` is ticked - encoded as an animated GIF (`--out x.gif`)
or as an H.264 MP4 (`--mp4 --no-gif --out x.mp4`).

Two shapes, for two different jobs, and the difference is the *digits*:

* **The GIFs are short and say one thing.**  12 frames, 2.04 s, the pinned readings
  from `tools/preview_pin.py` and `--clock` holding the time still, so a caption can
  quote the numbers afterwards - and nothing in `tests/` re-measures these files, so
  `docs/tools.md` names the command that reads their length and size back off disk.  GIF because
  GitHub's markdown turns `![alt](clip.mp4)` into `<img src="...clip.mp4">` which no
  browser plays, so inline motion has to be a GIF.
* **The MP4s are long and move.**  10-12 s at the clip's own 20-24 fps, driven by
  `--live-seconds N` or `--series FILE`: one real `sensors.collect()` per second, held
  for that second's frames, with the on-glass clock following each sample's wall time.
  So the temperatures, loads, fan figures and the seconds all change the way they do
  on real glass, and the series is saved beside the video (`--record`) as the record
  those digits came from.  These are the files README links - uploaded through
  GitHub's editor, which rewrites the markdown to point at its own CDN, because a
  `.mp4` written by hand into markdown is a dead `<img>`.

Two things this had to learn the hard way, both by measuring:

* **Sample, never repeat.**  The first version decoded the clip at its own 20-24 fps
  and told ffmpeg `-r 8` at the end, which is the same frame three times running.
  GIF is built on inter-frame diffs, so the repetition is pure loss: 7,205,675 bytes
  for what samples-at-8-fps writes in 1,510,157 - 4.8x for the identical animation.
  So the sampling happens here, in the same stream the window reads.
* **The palette budget is the cheapest knob left.**  ffmpeg's GIF encoder already
  offsets and diffs frames (`gifflags=offsetting+transdiff` are on by default) and
  `gifsicle` is not installed on this bench and needs a password to add, so the
  measured options are scale, rate, length and colour count.  Halving the palette to
  128 colours costs about 23 % of the bytes and leaves the text colour within
  1/255 per channel; 64 colours is where ink starts to move at 320 px.

Nothing here touches a device: it is host-side drawing over a decoded file, and
PROTOCOL.md §11 still means the panel is never asked what it is showing.  The GIF is
documentation, not evidence about the wire - its palette is ffmpeg's, not the
256-colour PNG the upload path uses.  The tool measures that cost on the file it
wrote and prints it, so the README can quote a number instead of a hope.
"""
from __future__ import annotations

import argparse
import datetime
import inspect
import io
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                    # noqa: E402

from xigmalcd import render, sensors
from xigmalcd.main import BRIGHT_LUMA, SCRIM_ON_BRIGHT                     # noqa: E402
from xigmaui import clips as clipdb                      # noqa: E402

#: the readings the documented previews draw.  One shared fixture for both preview
#: tools, in tools/preview_pin.py - which also says, field by field, which numbers are a
#: fixture chosen so the arcs land in the same place on every machine (57 C, which is
#: 60 % of the gauge theme's measured 30..75 C span: the middle of the ramp, where both
#: position and colour carry the value) and which are a dated snapshot of the author's
#: bench.  It names the live readings too - this bench read 73 C at 89.8 % under eight
#: parallel ffmpeg decodes, and 70 C at 8.8 % with a GPU-using process running, and at
#: 73 C that arc would sit at 95.6 % of the sweep, which reads as pegged rather than as
#: a measurement.  `--live` draws those instead.
from preview_pin import PINNED                                      # noqa: E402

#: `render.clock_str` before anything patches it.  Both this tool and
#: `tests/fixtures.py::freeze_clock` patch that attribute to pin or advance the clock
#: on the glass, so anything that wants the
#: real formatting - `series_note`, or a later draw - has to hold on to the original.
CLOCK_STR_REAL = render.clock_str

#: The day a pinned preview draws beside its frozen `--clock`.  The GIF shape is the one
#: whose digits a caption quotes, so the whole frame has to be frozen - including the
#: `clock` theme's date line, which used to follow the wall clock and so changed daily and
#: across time zones.  The day is the bench date the vendor's own captured frame is dated
#: with, spelled out here rather than inherited from the machine.
PINNED_DAY = (2026, 11, 5)


def pinned_when(clock: str):
    """a struct_time for `--clock HH:MM:SS` on PINNED_DAY, or None if it does not parse.

    tm_wday and tm_yday are filled in, because `strftime("%A")` reads the former and a
    struct built from a bare tuple would print a weekday of its own inventing.
    """
    try:
        hm = time.strptime(clock, "%H:%M:%S")
    except (ValueError, TypeError):
        return None
    d = datetime.date(*PINNED_DAY)
    return time.struct_time((*PINNED_DAY, hm.tm_hour, hm.tm_min, hm.tm_sec,
                             d.isoweekday() - 1, d.timetuple().tm_yday, -1))


def series_clock(sample, offset=None):
    """the struct_time a sample's on-glass clock shows, with the zone spelled out.

    A series stores epoch milliseconds, and `time.localtime()` is what turns them into the
    digits the glass shows - so one sample reads `00:25:16` on a bench at UTC+02:00 and
    `22:25:16` on a runner in UTC.  Nothing about the picture changes, and that is exactly
    the problem: a mask or a reference layer drawn at the runner's zone is not the picture
    the video holds, which is how one unchanged file's `clock` glyph luma measured 241.0
    here and 225.5 there.  So the JSON beside the videos records `clock_offset_s`, and
    passing that offset - not the reading machine's idea of local - reproduces the frame.

    With no offset, this machine's own, which is what a freshly sampled series wants:
    `save_series` writes that same offset into the file it saves.
    """
    ts = sample["timestamp"] / 1000.0
    if offset is None:
        offset = time.localtime(ts).tm_gmtoff
    return time.gmtime(ts + offset)


def sample_series(seconds: int, period: float = 1.0) -> list[dict]:
    """`seconds` real `sensors.collect()` calls, one per `period`.

    This is what makes a preview show *changes* rather than one frozen reading: the
    temperatures, loads, fan figures and the clock on the glass all come from a
    recorded series, sampled on this machine while the video was being made.  Each
    entry is `{"timestamp": <ms>, "metrics": <the STATE all 1 body>}`, which is the
    shape the daemon uploads and the shape `render.draw` takes, so a sample goes
    straight to the renderer with no translation.

    The sampling is wall-clock paced, and `collect()` itself costs 75-193 ms on this
    board (measured, three runs, 2026-11-08), so the sleep is the period minus that:
    otherwise the series drifts a third of a second per sample and a 12 s video shows
    16 seconds of readings.
    """
    out = []
    for _ in range(seconds):
        t0 = time.perf_counter()
        ts = int(time.time() * 1000)
        m = sensors.collect()
        if m:
            out.append({"timestamp": ts, "metrics": m})
        left = period - (time.perf_counter() - t0)
        if left > 0:
            time.sleep(left)
    return out


def save_series(where: str, series: list[dict], source: str) -> None:
    """Write the series next to the video that drew it, and say where it came from.

    The videos move, so their digits are a claim about a real machine at a real
    minute; the JSON is what that claim traces back to.  It is in the tree for the
    same reason `data/` is.
    """
    off = time.localtime(series[0]["timestamp"] / 1000).tm_gmtoff
    with open(where, "w") as fh:
        json.dump({"source": source, "samples": len(series),
                   "clock_offset_s": off,
                   "clock_note": f"each sample's on-glass clock is its epoch ms read at "
                                 f"UTC{off // 3600:+02d}:{abs(off) % 3600 // 60:02d}, the "
                                 f"zone this box was in when it was sampled - not the zone "
                                 f"of whatever machine renders from the file afterwards",
                   "first": series[0]["timestamp"], "last": series[-1]["timestamp"],
                   "span_s": (series[-1]["timestamp"] - series[0]["timestamp"]) / 1000,
                   "series": series}, fh, indent=1, sort_keys=True)
        fh.write("\n")


def load_series(where: str) -> list[dict]:
    """Read back a recorded series, so six previews can share one set of readings."""
    with open(where) as fh:
        return json.load(fh)["series"]


def load_clock_offset(where: str):
    """the `clock_offset_s` a recorded series carries, or None if it predates the field."""
    with open(where) as fh:
        return json.load(fh).get("clock_offset_s")


def series_note(series: list[dict], offset=None) -> str:
    """What actually moved in this series, as one line: min -> max per field.

    Printed by the tool, because "the numbers change" is the whole point of these files
    and it is worth reading off the series rather than assuming:
    an idle box can sit at one temperature and one fan figure for a quarter minute.
    """
    def vals(section, key):
        return [s["metrics"].get(section, {}).get(key) for s in series]

    def fans():
        got = []
        for s in series:
            got += [f.get("value") for f in s["metrics"].get("fans", [])
                    if f.get("value") is not None]
        return got

    def rng(name, vs):
        vs = [v for v in vs if v is not None]
        if not vs:
            return f"{name} n/a"
        return f"{name} {min(vs):g}->{max(vs):g}"

    clocks = [CLOCK_STR_REAL(series_clock(s, offset)) for s in series]
    parts = [rng("cpu C", vals("cpu", "temperature")),
             rng("cpu %", vals("cpu", "load")),
             rng("gpu C", vals("gpu", "temperature")),
             rng("gpu %", vals("gpu", "load")),
             rng("fan RPM", fans()),
             rng("mem MB", vals("memory", "used")),
             f"clock {clocks[0]}->{clocks[-1]} ({len(set(clocks))} distinct)"]
    return "  ".join(parts)


def frames(path: str, theme: str, ink: tuple | None, clock: str, kw: dict,
           count: int, gif_fps: float, series: list[dict] | None = None,
           offset=None) -> list[Image.Image]:
    """`count` composited frames, in order, sampled from one streaming decode.

    The stream is `ClipPlayer` - the same object the window plays with - and the
    sampling keeps every `source_rate / gif_fps`-th frame of it.  The loop seam is
    the file's own: a clip shorter than the GIF's length simply runs past its end
    again, which is what the glass does with it.

    Without `series`, every frame carries the same pinned reading and the same pinned
    clock - which is what a GIF in a README wants, because the caption quotes those
    digits.  With `series`, the reading and the clock come from one sample per output
    second: the digits change, the arcs move, and `11:07:42` ticks over to
    `11:07:43` exactly as it does on the glass, one second per second.  The sample is
    held for a whole second of frames (`gif_fps` of them), because the panel's own
    reading comes from a one-second poll - a preview that moved its numbers every
    frame would be showing something no display in this project ever shows.
    """
    player = clipdb.ClipPlayer(path)
    rate = player.fps or 24.0
    step = max(1, round(rate / max(0.1, gif_fps)))
    per_sec = max(1, round(gif_fps))
    out: list[Image.Image] = []
    seen = 0
    guard = 0
    real = (render._now, render.clock_str)   # patched for these frames, put back
    try:                                    # afterwards: a leaked patch is how a
                                            # later draw in the same process lies
        while len(out) < count and guard < count * step + 4 * max(1, step):
            bg = player.frame()
            if bg is None:
                break
            guard += 1
            if seen % step == 0:
                if series:
                    s = series[min(len(out) // per_sec, len(series) - 1)]
                    metrics = s["metrics"]
                    # Every time-shaped line in the frame comes from one hook, so one
                    # patch moves them all: the seconds tick one per second the way the
                    # glass does, and the `clock` theme's date line is the sample's date
                    # rather than the date of the minute this happened to render.  (It
                    # used to patch `clock_str` alone, which left the date reading the
                    # wall clock - and off machine, the wall clock follows the reader's
                    # time zone, not the recording's.)
                    when = series_clock(s, offset)
                    render._now = lambda t=when: t
                else:
                    metrics = PINNED
                    when = pinned_when(clock)
                    if when:
                        render._now = lambda t=when: t
                    else:
                        # a 12-hour `--clock "09:31 PM"` cannot be turned into an instant,
                        # so only the time line is pinned - and the date line then says
                        # what day this ran, which is worth knowing rather than hiding
                        render.clock_str = lambda *a, c=clock, **k: c
                        if not out:          # say it once, not once per frame
                            print("  note              --clock %r is not HH:MM:SS, so "
                                  "the date line follows this machine" % clock)
                base = bg.convert("RGBA").resize((render.W, render.H), Image.LANCZOS)
                base.alpha_composite(render.draw(metrics, theme, ink=ink, **kw))
                out.append(base)
            seen += 1
    finally:
        player.close()
        render._now, render.clock_str = real
    return out


def write_gif(images: list[Image.Image], where: str, fps: float, scale: int,
              colors: int = 256) -> int:
    """Animated GIF through ffmpeg's two-stage palette filter.

    `palettegen` picks one palette for the whole animation - per-frame quantisation
    would flicker - and `stats_mode=full` looks at every pixel of every frame rather
    than only the changed ones, which measured 2-3 % bigger but keeps flat runs of
    our own glyphs stable.  `dither=bayer:bayer_scale=4` is the graded screen: off,
    the file is ~10 % smaller but gradients band; a finer bayer is bigger, not
    better.  `fps=` is deliberately *not* in this filter graph: the frames arriving
    are already the ones that will be shown (see the module docstring).
    """
    graph = (f"scale={scale}:{scale}:flags=lanczos[base];"
             "[base]split=2[pal][src];"
             f"[pal]palettegen=max_colors={colors}:stats_mode=full[p];"
             "[src][p]paletteuse=dither=bayer:bayer_scale=4")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{render.W}x{render.H}", "-r", f"{fps:g}", "-i", "-", "-vf", graph,
         "-loop", "0", "-f", "gif", where],
        input=b"".join(im.convert("RGBA").tobytes() for im in images),
        capture_output=True)          # bytes in, bytes out: no text=True here
    if proc.returncode:
        raise SystemExit("ffmpeg gif failed: "
                         + proc.stderr.decode(errors="replace").strip()[:300])
    return os.path.getsize(where)


def write_mp4(images: list[Image.Image], where: str, fps: float, scale: int = 480,
              crf: int = 20, preset: str = "medium") -> int:
    """The same frames as H.264, at the same rate.

    Not an inline preview: GitHub turns an `.mp4` written in markdown into an `<img>`
    no browser plays, so an MP4 in a README is a dead link.  What they are for is the
    upload-then-embed path - GitHub's own editor takes a video file and rewrites the
    markdown to point at its CDN - and a release asset.  H.264 in an MP4 container with
    `+faststart` is what that editor accepts and what every browser plays once it is on
    the CDN, and `yuv420p` is not decoration: without it QuickTime refuses the file.

    `crf`/`preset` are exposed because size is the constraint here.  Measured on the
    five README previews at 320 px, 12 s: crf 20 / medium 0.4-1.4 MB, crf 18 / slow
    about 40 % bigger and still under 2 MB.  The layer's flat colour and text compress
    absurdly well; the background clip is what costs.
    """
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{render.W}x{render.H}", "-r", f"{fps:g}", "-i", "-",
         "-vf", f"scale={scale}:{scale}:flags=lanczos", "-c:v", "libx264",
         "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", "-an", where],
        input=b"".join(im.convert("RGBA").tobytes() for im in images),
        capture_output=True)
    if proc.returncode:
        raise SystemExit("ffmpeg mp4 failed: "
                         + proc.stderr.decode(errors="replace").strip()[:300])
    return os.path.getsize(where)


def probe_video(where: str) -> tuple:
    """Frames, duration and rate as the written file reports them, not as arithmetic.

    Worth asking rather than computing: x264 and the muxer get the last word on what a
    file holds, and the claim this tool makes to README is about the file.
    """
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames,r_frame_rate:format=duration",
         "-of", "default=nw=1", where], capture_output=True, text=True, check=True)
    got = {}
    for line in out.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            got[k] = v
    num, _, den = got.get("r_frame_rate", "0/1").partition("/")
    rate = float(num) / float(den or 1)
    frames = int(got.get("nb_read_frames") or 0)
    dur = float(got.get("duration") or 0.0)
    return frames, dur, rate


def ink_drift(where: str, want: tuple) -> tuple:
    """The colour in the written file that is nearest to our ink, and how far.

    Asked of the decoded frames, not of the encoder's settings: a solid glyph
    survives quantisation as at least one exact value, so this is the distance the
    reader's eye is actually one step from.  `getcolors` is the cheap way to ask -
    a palettised GIF frame holds at most 256 distinct values, not 230 thousand.
    """
    im = Image.open(where)
    best = (999, None)
    n = 0
    while True:
        for _count, px in im.convert("RGB").getcolors(maxcolors=1 << 20):
            d = max(abs(a - b) for a, b in zip(px, want[:3]))
            if d < best[0]:
                best = (d, px)
        n += 1
        try:
            im.seek(n)
        except EOFError:
            break
    return best[1], best[0], n


def main() -> int:
    ap = argparse.ArgumentParser(
        description="write the preview pane's animated composite out as a GIF "
                    "(and optionally the same frames as an MP4). No device is "
                    "opened: this is host-side drawing over a decoded file.")
    ap.add_argument("--clip", default="media/Theme_25.mp4",
                    help="background to play under the layer (default the "
                         "vendored Theme_25.mp4, the file the vendor's own "
                         "store.json pairs with the panel's default theme)")
    ap.add_argument("--theme", default="alpha", choices=sorted(render.THEMES))
    ap.add_argument("--ink", default=None, metavar="COLOUR",
                    help="the text colour to show, by name or #rrggbb; unset is "
                         "the theme's own skin (for `alpha`, white - measured)")
    ap.add_argument("--frames", type=int, default=12,
                    help="frames to show (default 12: at 6 fps that is 2.0 s, "
                         "which is two passes of the 0.96 s vendored loop)")
    ap.add_argument("--gif-fps", type=float, default=6.0,
                    help="frame rate of the GIF (default 6). The window decodes "
                         "every frame of the clip's own 20/24 fps; a GIF cannot "
                         "afford to, so this is the rate it samples at")
    ap.add_argument("--scale", type=int, default=render.W,
                    help="GIF edge in pixels (default 480, the panel's own size)")
    ap.add_argument("--colors", type=int, default=256, choices=(256, 128, 64, 32),
                    help="palette budget for the whole animation (default 256; "
                         "128 measured 23%% smaller with the text colour still "
                         "within 1/255)")
    ap.add_argument("--clock", default=time.strftime("%H:%M:%S"),
                    help="the clock string drawn into the layer (default now; "
                         "pass a fixed one for a reproducible picture)")
    ap.add_argument("--cold", type=int, default=None, metavar="C",
                    help="gauge/alpha cold end of the scale (unset: the theme's "
                         "own measured scale)")
    ap.add_argument("--hot", type=int, default=None, metavar="C", help="ditto, "
                    "hot end")
    ap.add_argument("--scrim", type=int, default=None,
                    help="alpha of the dark plate behind the glyphs; unset uses "
                         "the daemon's measured rule for this clip")
    ap.add_argument("--out", default="", help="write the GIF here (default "
                                              "docs/preview-<theme>-<clip>.gif)")
    ap.add_argument("--mp4", action="store_true",
                    help="also write the same frames as an MP4 next to the GIF, "
                         "for a click-through or a release asset")
    ap.add_argument("--no-gif", action="store_true",
                    help="write only the .mp4 (implies --mp4).  A 10-12 s preview as a "
                         "GIF is several MB of the wrong codec; the long files README "
                         "links are MP4s, uploaded through GitHub's editor and hosted "
                         "on its CDN, where an <img>-shaped .mp4 link is not the problem")
    ap.add_argument("--crf", type=int, default=20, metavar="N",
                    help="x264 quality, lower is bigger: 20 measured 0.4-1.4 MB per "
                         "12 s preview at 320 px")
    ap.add_argument("--preset", default="medium",
                    help="x264 speed/size preset (medium; slow is ~40 %% bigger)")
    ap.add_argument("--live-seconds", type=int, default=0, metavar="N",
                    help="sample the real sensors once a second for N seconds and drive "
                         "the picture from that: temperatures, loads, fans and the on-"
                         "glass clock all move, one reading per displayed second")
    ap.add_argument("--series", metavar="FILE",
                    help="drive the picture from a series recorded earlier by "
                         "--record, so several previews show the same minute")
    ap.add_argument("--record", metavar="FILE",
                    help="with --live-seconds, write the sampled series here as JSON: "
                         "the record the video's digits came from")
    ap.add_argument("--live", action="store_true",
                    help="read real sensors instead of the pinned readings, so "
                         "the picture says what this machine is doing now")
    a = ap.parse_args()

    if not os.path.isfile(a.clip):
        print(f"no such clip: {a.clip}", file=sys.stderr)
        return 1
    ink = render.parse_ink(a.ink)
    dur, wide, tall, fps = clipdb._ffprobe_look(a.clip)
    first = clipdb.frame(a.clip)
    lum = clipdb.luma(first) if first else 0.0
    # One option bag for every theme, then the same signature filter the daemon and
    # the window use (`main._theme_kwargs`, `app._render_kw`): the five themes do not
    # take the same arguments - `alpha` has no `title`, `clock` has no gauge `source`
    # - and an option a theme never asked for is a TypeError, not a silent no-op.
    kw = {"bg": render.OVERLAY, "clock_size": 30, "fan": True,
          "source": "temperature", "cold": a.cold, "hot": a.hot}
    params = inspect.signature(render.THEMES[a.theme]).parameters
    kw = {k: v for k, v in kw.items() if k in params and v is not None}
    if a.scrim is not None:
        kw["scrim"] = a.scrim        # `draw` takes this, the window's `--scrim N` rule
    else:
        # ...and when it is not given, the *window's* auto rule, not the daemon's.
        # `main._scrim_for` only knows the handful of clips `CLIP_LUMA` measured, and
        # this tool can be pointed at any file in the library; `xigmaui/_render_kw`
        # measures the luma and applies the same two constants (BRIGHT_LUMA where
        # white-on-white starts, SCRIM_ON_BRIGHT how much plate fixes it).  The pane
        # draws the plate, so a preview that claims to be "the same composite the pane
        # shows" has to include it.  Counted out of the encoded GIFs for the clock over
        # `Theme_07.mp4` (measured luma 176.3 of 255): glyph against its own grown halo,
        # 47.1 with `--scrim 0` and 110.3 with the plate the rule gives, the mechanism
        # being that `render.scrim` hugs what was drawn instead of washing the canvas - the
        # glyph itself stays at 241.7 either way.  The suite prints that figure for all
        # five README files, and holds it at a floor of 30.
        kw["scrim"] = SCRIM_ON_BRIGHT if lum > BRIGHT_LUMA else 0
    global PINNED
    if a.live:
        PINNED = sensors.collect()

    # The readings for this picture: one pinned set (the GIF shape, the one a caption
    # can quote), or one real sample per displayed second (the MP4 shape, where the
    # digits, the arcs and the clock all move).  A recorded series can be re-used by
    # several previews so six videos show the same minute of one machine.
    series, offset = None, None      # offset: the zone a recorded series was sampled in
    if a.series:
        if a.record:
            print("--series is a recorded series: refusing to overwrite it with "
                  "--record.  Drop one of the two flags.", file=sys.stderr)
            return 2
        series = load_series(a.series)
        offset = load_clock_offset(a.series)
        if offset is not None:
            print(f"  clock zone        the series carries its own: its on-glass clock "
                  f"is its epoch ms read at UTC{offset // 3600:+02d}"
                  f":{abs(offset) % 3600 // 60:02d}, so this render shows the same "
                  f"seconds the recorded one did")
    elif a.live_seconds:
        offset = None            # this box, this minute - save_series writes the zone down
        t0 = time.perf_counter()
        series = sample_series(a.live_seconds)
        if not series:
            print("sensors.collect() returned nothing on this machine", file=sys.stderr)
            return 1
        print(f"  sampled           {len(series)} readings in "
              f"{time.perf_counter() - t0:.1f} s (one sensors.collect() per second)")
        if a.record:
            save_series(a.record, series,
                        f"sensors.collect() on the author's bench, "
                        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(series[0]['timestamp'] / 1000))}"
                        f" local time, {len(series)} samples at 1 s")
            print(f"  recorded          {a.record}  {os.path.getsize(a.record):,} B")
    elif a.record:
        print("--record needs --live-seconds N", file=sys.stderr)
        return 2
    if series:
        print(f"  readings          {len(series)} samples, one per second, and the "
              f"on-glass clock follows each sample's own time: "
              f"{series_note(series, offset)}")
    if a.no_gif:
        a.mp4 = True

    t0 = time.perf_counter()
    ims = frames(a.clip, a.theme, ink, "" if series else a.clock, kw, a.frames,
                 a.gif_fps, series=series, offset=offset)
    made = time.perf_counter() - t0
    if not ims:
        print("no frames decoded: is ffmpeg installed?", file=sys.stderr)
        return 1

    stem = a.out or os.path.join(
        "docs", f"preview-{a.theme}-{os.path.basename(a.clip).rsplit('.', 1)[0]}"
                + (f"-{render.ink_hex(ink)}" if ink else "")
                + (".mp4" if a.no_gif else ".gif"))
    if a.no_gif and not stem.lower().endswith(".mp4"):
        stem += ".mp4"          # --no-gif without --out: the MP4 is the only ask
    passes = (len(ims) / max(0.1, a.gif_fps)) / dur if dur else 0.0
    print(f"  frames            {len(ims)} composited in {made:.1f} s "
          f"({made / len(ims) * 1000:.0f} ms each: decode + render.draw + composite)")
    print(f"  clip              {a.clip}  {dur:.2f} s loop, {fps:g} fps, "
          f"{wide}x{tall}, mean luma {lum:.1f}")
    print(f"  layer             theme {a.theme}, text "
          f"{render.ink_hex(ink) or 'theme default'}, "
          f"{'clock from each sample' if series else 'clock ' + a.clock}, "
          f"scrim {kw.get('scrim', 'auto rule')}")
    vid = None
    if not a.no_gif:
        gif = write_gif(ims, stem, a.gif_fps, a.scale, a.colors)
        print(f"  gif               {stem}  {gif:,} B  {a.scale}x{a.scale} at "
              f"{a.gif_fps:g} fps = {len(ims) / a.gif_fps:.1f} s of a {passes:.1f}-pass "
              f"loop, {a.colors} colours")
        vid = stem.rsplit(".", 1)[0] + ".mp4" if a.mp4 else None
    else:
        vid = stem
    if vid:
        size = write_mp4(ims, vid, a.gif_fps, a.scale, a.crf, a.preset)
        nf, nd, nr = probe_video(vid)
        print(f"  mp4               {vid}  {size:,} B  {a.scale}x{a.scale}, crf {a.crf} "
              f"{a.preset}: {nf} frames at {nr:g} fps = {nd:.2f} s as the written file "
              f"reports it ({len(ims) / a.gif_fps:.2f} s asked for, "
              f"{nd / dur:.1f} passes of the clip)")
        if ink and a.no_gif:
            print(f"  ink in the file   not measured here: the drift check reads the "
                  f"GIF's palette, and an H.264 file has none - it quantises in YUV "
                  f"4:2:0 instead.  Write the GIF too to get the figure.")
    if a.mp4 or a.no_gif:
        print(f"  what an mp4 is    GitHub turns `![alt](x.mp4)` in markdown into an "
              f"<img> no browser plays, so this file is an upload-for-the-editor or a "
              f"release asset, never an inline preview")
    if ink and not a.no_gif:
        near, dist, seen = ink_drift(stem, ink)
        print(f"  ink in the file   nearest drawn colour {near} off {dist}/255 "
              f"(that palette is ffmpeg's, not the 256-colour PNG the upload path "
              f"uses; {seen} frames read back)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
