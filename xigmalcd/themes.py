"""The theme library: which layouts exist, what they are called, and which ones can
honestly be drawn here.

ALPHA's own theme library is 27 layout files (docs/themes.md, and the write-up of the
container and the schema in `themes/alpha/README.md`).  `xigmalcd/layout.py` paints one
of those files; this module answers the three questions a caller has before it can ask
that: where the files are, what one is called, and what is allowed to be picked.

Two of those answers are measurements and one is a refusal, and the refusal is the load-
bearing one:

* **Canvas.** `themes/alpha/layouts/**` carries 23 layouts at `ratio "1:1"` (480x480,
  the panel's own size) and 4 at `"4:3"` (320x240).  Only the `1:1` set is selectable.
  The anchor convention every text widget is drawn by - `(x, y)` is the top-left of the
  em box - was measured against the vendor's own baked overlay at 480 (the `render.py`
  comment that records it, and `tools/theme_check.py`, which re-measures it per theme in
  pixels).  A 320x240 layout drawn at 480 multiplies an unmeasured convention by 1.5, so
  those four stay out until someone measures them (`docs/theme-editor.md` keeps the plan
  and the cost).  The gate is on the file's own `ratio` field, not on the directory name.
* **Names.** `--theme Theme_07` rather than `--theme 1757491588804`.  Each layout names
  exactly one background clip in `background.mediaFile`, and the 27 stems are unique -
  case-insensitively too, which is why `Theme_11` and `theme_11` cannot collide.  The
  numeric theme id is accepted as well, because that is the form `store.json` uses and
  the form `tools/theme_check.py` prints.
* **Sources.** A layout's `data`/`bar`/`arc` widgets name a metric in `property[].source`
  - 12 distinct names across the 27 files, over 82 widgets.  `SOURCES` below pairs each
  with a field of `sensors.collect()`.  Where there is no field to read, the widget is
  skipped and the reason is printed; nothing here draws a made-up number.
"""
from __future__ import annotations

import datetime
import glob as _glob
import json
import os

from . import layout
from . import render

#: Where a copy of the library can be.  Same reasoning and same order as
#: `main.media_roots()`: a checkout wins over an installed package, so the numbers the
#: documents quote cannot drift under a build that happens to have a .deb on the machine.
REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                         "themes", "alpha")
SYSTEM_ROOT = "/usr/share/xigmalcd/themes/alpha"

def user_root() -> str:
    """Where an edited theme lives.  Never the two roots above: `/usr/share/.../themes/alpha`
    is dpkg-owned and `debian/tests/smoke` re-hashes every file in it (125/125), so an edit
    that landed there would be an edit the package manager disagrees with."""
    root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(root, "xigmalcd", "themes")


def roots() -> tuple:
    """Library roots that exist, first-winning order, no repeats."""
    return tuple(dict.fromkeys(r for r in (os.path.abspath(REPO_ROOT), SYSTEM_ROOT)
                               if os.path.isdir(r)))


#: The canvas a layout must declare to be pickable, and the reason it is the one.
NEED_RATIO = "1:1"
RATIO_WHY = ('ratio {ratio}: {w}x{h}, and the em-box anchor convention text is drawn by '
             'was measured at 480 only - docs/theme-editor.md keeps that plan and its cost')


def scan() -> tuple:
    """(selectable, excluded) records for every layout file in `roots()`.

    A record is {name, id, ratio, w, h, path, root, widgets, background}.  First-winning
    root by name, exactly like the clip library, so a checkout and an installed package
    never both answer for one name.
    """
    by_name: dict = {}
    for root in roots():
        for path in sorted(_glob.glob(os.path.join(root, "layouts", "**", "*.json"),
                                      recursive=True)):
            obj = load(path)
            stem = os.path.splitext(os.path.basename(
                (obj.get("background") or {}).get("mediaFile") or path))[0]
            rec = {"name": stem, "id": str(obj.get("id")), "ratio": str(obj.get("ratio")),
                   "w": int(obj.get("width") or 0), "h": int(obj.get("height") or 0),
                   "path": path, "root": root,
                   "widgets": len((obj.get("osd") or {}).get("widget") or []),
                   "background": (obj.get("background") or {}).get("mediaFile") or ""}
            # first-winning root: `roots()` is already in order, and the vendor's own
            # name-space cannot disagree between a checkout and a package (the suite
            # asserts the two trees carry the same 27 layouts, byte for byte)
            by_name.setdefault(stem, rec)
    ok = sorted((r for r in by_name.values() if r["ratio"] == NEED_RATIO),
                key=lambda r: r["name"].lower())
    out = sorted((r for r in by_name.values() if r["ratio"] != NEED_RATIO),
                 key=lambda r: r["name"].lower())
    return ok, out


_objects: dict = {}


def load(path: str) -> dict:
    """One layout file, parsed once per (path, mtime).

    The loop paints a layout every frame, and re-reading a JSON to draw the same picture
    240 times an hour is a choice that has to be made on purpose.  The mtime is the key
    because an edited theme - the whole point of the plan in docs/theme-editor.md - has to
    show up on the next frame without a restart.
    """
    key = (path, os.stat(path).st_mtime_ns)
    obj = _objects.get(key)
    if obj is None:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        _objects.clear()
        _objects[key] = obj
    return obj


def selectable() -> list:
    return scan()[0]


def names() -> list:
    """Every name `resolve()` accepts, built-ins first: what `--theme` can be told."""
    return sorted(render.THEMES) + [r["name"] for r in selectable()]


def resolve(name: str):
    """The layout record for `name`, or None if `name` is a built-in or unknown.

    Accepts the stem (`Theme_07`), the stem in any case, and the numeric id that
    `store.json` and `tools/theme_check.py` use.
    """
    ok, out = scan()
    want = str(name).strip()
    for rec in ok + out:
        if want == rec["name"] or want.lower() == rec["name"].lower():
            return rec if rec["ratio"] == NEED_RATIO else None
        if want == rec["id"]:
            return rec if rec["ratio"] == NEED_RATIO else None
    return None


def why_not(name: str) -> str:
    """Why `resolve()` answered None, in one line a terminal can be trusted with."""
    ok, out = scan()
    want = str(name).strip()
    for rec in out:
        if want.lower() in (rec["name"].lower(), rec["id"].lower()):
            return RATIO_WHY.format(ratio=rec["ratio"], w=rec["w"], h=rec["h"])
    if want in render.THEMES:
        return "one of the five this program draws itself"
    return (f"no layout named {name!r} under {' or '.join(roots())} "
            f"(a user theme is one you save; docs/theme-editor.md keeps that plan)")


# ---------------------------------------------------------------- sources --
# A layout's widgets say what they want by name, in `property[].source`.  The names are
# the vendor's own - PROTOCOL.md §10 reads the same vocabulary out of the app's renderer
# bundle (`cpuTemp` "CPU Temperature" ... `waterPumpSpeed` "Pump Speed").  The right-hand
# side is ours: which field of `sensors.collect()` answers that name.  Where the pairing
# matches what `render.theme_alpha` already draws from the selected vendor theme, that is
# said; where it is this program's decision, that is said too.
SOURCES = {
    "CPU Temperature": ("cpu", "temperature"),      # as in theme_alpha
    "GPU Temperature": ("gpu", "temperature"),      # as in theme_alpha
    "CPU Usage": ("cpu", "load"),                   # as in theme_alpha
    "GPU Usage": ("gpu", "load"),                   # as in theme_alpha
    "CPU Power": ("cpu", "power"),                  # ours: no shipped layout bakes one
    "GPU Power": ("gpu", "power"),                  # ours
    "CPU Frequency": ("cpu", "speedAverage"),        # ours
    "GPU Frequency": ("gpu", "speed"),               # ours: unused by the shipped library
    "Download Speed": ("network", "download"),       # ours: unused by the shipped library
    "Upload Speed": ("network", "upload"),           # ours
    "Memory Usage": ("memory", "load"),              # ours: unused by the shipped library
}

#: Sources that want a wall clock, and get one instant per frame - the same rule
#: `render._now()` exists for (a frame that calls `time.strftime` twice shows two
#: different seconds in one picture).
CLOCKED = ("Time", "Date", "Week")

#: Sources a shipped layout asks for and this machine has no field for yet.  `Pump Speed`
# (9 of the 23 selectable themes) wants the AIO pump's tachometer; `sensors.fans()`
# answers rows with names, and no measurement has ever established which row, if any, is
# the pump on this box.  Matching a fan row by name would be a guess wearing a rule, so
# the widget is skipped and the reason is printed instead.
UNMAPPED = {"Pump Speed": "no pump tachometer has been measured on this box "
                          "(tools/fanscan.py has never looked for one)"}


def formats_measured() -> tuple:
    """Which source names have a display shape measured off the vendor's own baked
    overlay, rather than chosen by this program: `layout.FORMATS_MEASURED`, four of them,
    and `draw_theme` reports every other one it paints as a gap."""
    return layout.FORMATS_MEASURED


def sources_used(records: list) -> dict:
    """{source name: how many widgets ask for it}, over the given layout records."""
    tally: dict = {}
    for rec in records:
        for w in (load(rec["path"]).get("osd") or {}).get("widget") or []:
            for prop in w.get("property") or []:
                src = prop.get("source")
                if src:
                    tally[src] = tally.get(src, 0) + 1
    return tally


def _clock(when=None):
    """One instant, as a `datetime`, for every clock-shaped source in a frame.

    `layout.VENDOR_FORMAT` formats Time/Date/Week with `datetime.strftime`, so that is the
    type it wants.  Defaulting through `render._now()` is the point: that is the one hook
    this repo has for "what moment is this frame", so patching it - which is how
    `tools/preview_gif.py` pins a recorded series to the second it was sampled, and how
    the suite proves a zone change moves nothing - moves a library theme's clock too.  A
    caller holding a `struct_time` is taken apart and rebuilt rather than passed through,
    because `time.struct_time` has no `strftime` (the first run here proved it by failing).
    """
    if when is None:
        return datetime.datetime(*render._now()[:6])
    if hasattr(when, "strftime"):
        return when
    return datetime.datetime(*tuple(when)[:6])


def values(metrics: dict, when=None) -> tuple:
    """(values, absent) for one frame: what every `source` in the library can be given.

    `values` is what `layout.draw_theme` wants; `absent` names the sources it could not
    answer and why, so a caller can print the decision rather than leave a hole that
    reads like a bug.  A sensor group that is simply not on this machine (`gpu` is often
    absent, and a CI runner once answered only `cpu`, `disk`, `memory`, `timestamp`) is
    reported the same way as a source with no rule.
    """
    when = _clock(when)
    out, absent = {}, {}
    for src, (group, field) in SOURCES.items():
        val = (metrics.get(group) or {}).get(field)
        if val is None:
            absent[src] = f"sensors.collect() answered no {group}.{field}"
        else:
            out[src] = val
    for src in CLOCKED:
        out[src] = when
    for src, why in UNMAPPED.items():
        absent[src] = why
    return out, absent


def paint(record: dict, metrics: dict, when=None, scrim: int = 0) -> tuple:
    """One 480x480 RGBA overlay for a library theme, plus the notes that explain it.

    Returns (image, notes) where notes come from `layout.draw_theme` - every font
    substitution, every skipped widget, every gap touched.  The image is the OSD layer
    only: like our own themes it carries transparency, and the background underneath it
    is the panel's business (or the loop's, for a preview).

    `scrim` is the same plate rule our own five get (`render.scrim`): it is built from the
    layer's own alpha, so it needs no per-theme geometry, and a library theme over a
    bright clip needs it for the same reason `alpha` does - docs/limits.md keeps the luma
    figures, and `theme_48.mp4` at 227.3 of 255 is the case that decided it.
    """
    vals, absent = values(metrics, when)
    img, notes = layout.draw_theme(load(record["path"]), vals,
                                   canvas=(record["w"], record["h"]))
    # `draw_theme` says which widgets it skipped; this says why, in the words this module
    # chose when it refused to invent a reading.  Both belong in the notes.
    notes["absent"] = absent
    if scrim:
        img = render.scrim(img, max(1, min(255, int(scrim))))
    return img, notes


def describe(record: dict) -> str:
    """One line: what `--theme <name>` will draw, and where the file came from."""
    return (f"  {record['name']:<12} {record['id']}  {record['w']}x{record['h']} "
            f"ratio {record['ratio']}  {record['widgets']} widgets  "
            f"background {os.path.basename(record['background'])}  from "
            f"{'checkout' if record['root'] == os.path.abspath(REPO_ROOT) else 'package'}")


def census(limit: int = 0) -> list:
    """The printed lines for `--list-themes`: pickable, then refused, each with its why."""
    ok, out = scan()
    lines = [describe(r) for r in (ok[:limit] if limit else ok)]
    lines += ["  " + f"{r['name']:<12} {r['id']}  {r['w']}x{r['h']} ratio {r['ratio']}"
              f"  NOT PICKABLE: {why_not(r['name'])}" for r in out]
    return lines
