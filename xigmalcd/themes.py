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

import copy
import datetime
import functools
import glob as _glob
import json
import os
import time

from PIL import Image

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
    """Library roots that exist, first-winning order, no repeats: your edited copies
    first, then the checkout, then the installed package.

    A user root is scanned flat (`<name>.json`); the vendor trees are scanned
    `layouts/<canvas>/*.json`, which is how the installer ships them.  Putting yours first
    is what makes "edit a copy, keep the original" a file operation rather than a
    feature: `--theme Theme_07` finds your copy of that name, and deleting it puts the
    vendor's back in front.
    """
    return tuple(dict.fromkeys(
        r for r in ((os.path.abspath(user_root()), "*.json"),
                    (os.path.abspath(REPO_ROOT), os.path.join("layouts", "**", "*.json")),
                    (SYSTEM_ROOT, os.path.join("layouts", "**", "*.json")))
        if os.path.isdir(r[0])))


#: The canvas a layout must declare to be pickable, and the reason it is the one.
NEED_RATIO = "1:1"

#: How a listing counts the two refusals out, so a line like `--list-themes`'s does not have
#: to say "refused" and leave the reader to guess which kind: the code is on the record.
WHY_LABEL = {"ratio": "on canvas", "empty": "with nothing to draw"}

#: The other thing a file has to have to be a layout at all, and the one wording every door
#: that refuses it uses.  `layout.draw_theme` reads `obj["osd"]["widget"]`: a JSON without
#: that list is not a layout with an empty canvas in it, it is a file the painter raises
#: `KeyError` over - and until 2026-11-13 `scan()` selected on `ratio` alone, so such a file
#: sitting in your own themes directory was a name `--theme` accepted and the loop crashed on.
NEED_OSD_WHY = ("no `osd` with a `widget` list, which is the one thing every layout file in "
                "this library has: it is nothing to draw, and `layout.draw_theme` reads that "
                "key (a `STATE all 1` metrics body, a clip's sidecar or a config file all "
                "look like this from here)")
RATIO_WHY = ('ratio {ratio}: {w}x{h}, and the em-box anchor convention this program '
             'draws text by was measured at 480 only - docs/theme-editor.md keeps that '
             'plan and its cost')


def scan() -> tuple:
    """(selectable, excluded) records for every layout file in `roots()`.

    A record is {name, id, ratio, w, h, path, root, widgets, background}, and an excluded
    one also carries `why` and `why_code` - the sentence this module prints for it and the
    short label beside it - and that same sentence is what `resolve()` refuses by.
    First-winning root by name, exactly like the clip library, so a checkout and an
    installed package never both answer for one name.
    """
    by_name: dict = {}
    for root, pattern in roots():
        for path in sorted(_glob.glob(os.path.join(root, pattern), recursive=True)):
            obj = load(path)
            stem = os.path.splitext(os.path.basename(path))[0] if pattern == "*.json" \
                else os.path.splitext(os.path.basename(
                    (obj.get("background") or {}).get("mediaFile") or path))[0]
            rec = {"name": stem, "id": str(obj.get("id")), "ratio": str(obj.get("ratio")),
                   "w": int(obj.get("width") or 0), "h": int(obj.get("height") or 0),
                   "path": path, "root": root,
                   "edited": pattern == "*.json",
                   "widgets": len((obj.get("osd") or {}).get("widget") or []),
                   "background": (obj.get("background") or {}).get("mediaFile") or ""}
            # first-winning root: `roots()` is already in order, and the vendor's own
            # name-space cannot disagree between a checkout and a package: the
            # manifest is re-hashed in both, `tools/verify_manifest.py` in a checkout
            # and the same walk over the installed tree in `debian/tests/smoke`
            by_name.setdefault(stem, rec)
    # Two things make a file unusable, and both are cheap to ask: the canvas it declares,
    # and whether it holds anything to draw at all.  The second rule arrived on 2026-11-13
    # with `debian/tests/smoke`'s accounting: a JSON that parses, declares 480x480 and carries
    # no `osd` - somebody's metrics dump, a clip's sidecar, half a config file - is a name
    # `resolve()` answered, and `layout.draw_theme` walks `obj["osd"]["widget"]`, so the loop
    # did not draw an empty canvas: it raised `KeyError: 'osd'` on the frame that named the
    # file.  `validate` has always said this in words about a file's contents; this is the
    # same rule one door earlier, where it costs two dict lookups per file per scan rather
    # than a full validation on every frame the loop draws.
    for rec in by_name.values():
        if rec["ratio"] != NEED_RATIO:
            rec["why"], rec["why_code"] = (
                RATIO_WHY.format(ratio=rec["ratio"], w=rec["w"], h=rec["h"]), "ratio")
        elif not rec["widgets"]:
            rec["why"], rec["why_code"] = NEED_OSD_WHY, "empty"
    ok = sorted((r for r in by_name.values() if not r.get("why")),
                key=lambda r: r["name"].lower())
    out = sorted((r for r in by_name.values() if r.get("why")),
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
        # one rule for both spellings, and `scan()`'s own `why` is what says it: the door
        # that lists layouts and the door that draws one cannot be allowed to disagree
        # about whether a file is usable, or a name appears in `--list-themes` and raises
        # in the painter
        if want == rec["name"] or want.lower() == rec["name"].lower():
            return None if rec.get("why") else rec
        if want == rec["id"]:
            return None if rec.get("why") else rec
    return None


def why_not(name: str) -> str:
    """Why `resolve()` answered None, in one line a terminal can be trusted with."""
    ok, out = scan()
    want = str(name).strip()
    for rec in out:
        if want.lower() in (rec["name"].lower(), rec["id"].lower()):
            return rec.get("why") or RATIO_WHY.format(ratio=rec["ratio"], w=rec["w"],
                                                      h=rec["h"])
    if want in render.THEMES:
        return "one of the five this program draws itself"
    return (f"no layout named {name!r} under {' or '.join(r for r, _ in roots())} "
            f"(--list-themes prints what those roots hold; a file in "
            f"{user_root()} shadows a vendor layout of the same name)")


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
    # The three readings `bars` needs that no source name covered yet.  The first two carry
    # the names the vendor's own editor vocabulary uses (PROTOCOL.md 10: `RAMRate`, `UsedRAM`,
    # read out of its uncompiled renderer bundle on 2026-11-06), spelled in the display style
    # every other source here uses; `Motherboard Temperature` has no entry in that record, so
    # it is ours, and the GPU-memory pair below has none either.
    "Used RAM": ("memory", "used"),
    "Used GPU Memory": ("gpu", "memoryUsage"),
    "Motherboard Temperature": ("motherboard", "temperature"),
}

#: Sources whose number comes out of two reported fields rather than one, spelled as a pair
#: of field names so the arithmetic stays in one place: `render.pct_pair` computes them, and
#: it is the same function `render.theme_bars` divides its own meters with.  That matters for
#: `RAM Rate` in particular: `sensors` separately reports a `memory.load` percentage, which is
#: *not* what `used / total` works out to, and handing a 424 px meter the other number moves a
#: fill by a device pixel somewhere.  A derived source with no pair to divide is reported like
#: any other unanswered source, with the two field names in the reason.
DERIVED = {
    "RAM Rate": ("memory", "used", "total"),
    "GPU Memory Rate": ("gpu", "memoryUsage", "dedicatedTotal"),
}


#: The per-sensor fan rows `bars` draws, and the reason they are ours to name: the vendor's
#: editor offers no fan per sensor at all, only the aggregate `cpuFansSpeed` "CPU Fans Speed"
#: and `gpuFansSpeed` "GPU Fans Speed" (PROTOCOL.md 10), while this theme paints one row per
#: tachometer with that sensor's own name beside it.  The slots are positional, in the order
#: `sensors` reports the rows and `theme_bars` reserves them - `fans[0]` through
#: `fans[render.BARS_SLOTS - 1]` - and a name that no such row carries is answered like any
#: other missing reading, with the reason printed rather than a zero painted in its place.
FAN_SLOTS = tuple((f"Fan {i} Speed", f"Fan {i} Name")
                  for i in range(1, render.BARS_SLOTS + 1))

#: `bars`'s rows in the order the drawing lays them out: the label it prints - a literal for
#: the six fixed rows, `None` for a fan slot, whose label is its `Fan N Name` source - then
#: the source the meter divides, the source the number beside it prints, and the scale.  One
#: table, because `tests/test_bars_rows.py` compares it row for row against the
#: strings `render`'s own drawing writes and the ink it leaves, and `bars_recipe()` will
#: build its rows out of it rather than a second copy of it.
BARS_FIXED_ROWS = (
    ("CPU", "CPU Temperature", "CPU Temperature", 30, 90),
    ("GPU", "GPU Temperature", "GPU Temperature", 30, 90),
    ("BOARD", "Motherboard Temperature", "Motherboard Temperature", 25, 80),
    ("LOAD", "CPU Usage", "CPU Usage", 0, 100),
    ("RAM", "RAM Rate", "Used RAM", 0, 100),
    ("VRAM", "GPU Memory Rate", "Used GPU Memory", 0, 100),
)
BARS_ROWS = BARS_FIXED_ROWS + tuple(
    (None, speed, speed, 0, 3000) for speed, _name in FAN_SLOTS)

#: Which reading prints a fan row's label, given the source its meter reads.
_FAN_NAME = {speed: name for speed, name in FAN_SLOTS}

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


def source_names() -> tuple:
    """Every `source` name this program can put a reading behind: the flat fields, the
    derived ratios, the clock, and the positional fan slots.  The checks that
    count them - `tests/test_theme_library.py` and `tests/test_library_draw.py` -
    ask through this door rather than keeping a list of their own, so a new source
    cannot be invisible to the check that would have to know about it."""
    return (tuple(SOURCES) + tuple(DERIVED) + CLOCKED
            + tuple(n for pair in FAN_SLOTS for n in pair))


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
    a zone change moves nothing this program draws, and it does move a library
    theme's clock - measured on the bench on 2026-11-08, four runs identical
    with the machine's own zone set to UTC, a record rather than a gate, since
    nothing in `tests/` re-runs that comparison. A caller holding a
    `struct_time` is taken apart and rebuilt rather than passed through,
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
    for src, (group, num, den) in DERIVED.items():
        val = render.pct_pair(metrics.get(group), num, den)
        if val is None:
            absent[src] = (f"{group}.{num} and {group}.{den} are not a pair this machine "
                           f"reports (one is absent, or the denominator is 0)")
        else:
            out[src] = val
    fans = metrics.get("fans") or []
    for (speed, name) in FAN_SLOTS:
        slot = int(speed.split()[1]) - 1
        fan = fans[slot] if slot < len(fans) else None
        for src, key in ((speed, "value"), (name, "name")):
            if key == "name":
                # `FAN 3` is what the drawing prints for a row that reports a tachometer
                # under no name, so the source answers the same thing: an empty label would
                # disagree with the theme over one row, far from any cause a reader could see
                val = (fan.get("name") or f"FAN {slot + 1}") if fan else None
            else:
                val = fan.get("value") if fan else None
            if val is None:
                absent[src] = (f"this box reports {len(fans)} fan row"
                               f"{'s' if len(fans) != 1 else ''}; slot {slot + 1} has "
                               f"no {key}")
            else:
                out[src] = val
    for src, why in UNMAPPED.items():
        absent[src] = why
    return out, absent


def _overlay(obj: dict, canvas: tuple, metrics: dict, when=None, scrim: int = 0) -> tuple:
    """One layout object, one value table, one painter: the way pixels actually get made.

    **Both** public doors below go through here, and sharing the door is the point of this
    function.  `paint` used to build its own value table and `draw` built its own **plus**
    `fill_lines`, so the two doors answered the same file with two different tables.  The keys
    `fill_lines` adds - `temp-cpu`, `temp-gpu`, `fan-cpu`, `fan-gpu`, `readings`, `status` -
    are not `source` names any vendor file spells: they are the strings the registered
    `special` drawings read, and each of them returns `None` when its strings come back empty.
    A `special` row is then skipped, and `layout.draw_theme` reports it with **no box at all**.
    That is the whole of the defect this function closes: the editor's pane drew
    `temp-values` and `fan-figures` in full, the loop sent a frame without them, and a layout
    saved from the pane and applied to the panel came up on the glass missing two rows.  The
    rows that do *not* read the table survived it - `temp-labels` takes its words from
    `render.A26_TLBL_TEXT` - which is why the loss looked selective rather than total.

    Three of the five layouts this repository generates declare rows that read those keys -
    `alpha` three (`fan-figures`, `temp-values`, `temp-labels`), `clock` one
    (`clock-readings`) and `dual` one (`dual-status`) - and the vendor's 27 files declare no
    `special` kind at all, which is why nothing that compared a vendor file pixel for pixel
    could have seen it: `clock`'s readings line and `dual`'s status line were going missing on
    the glass beside `alpha`'s figures, and no reported case had named them yet.
    `tests/test_specials.py`'s `ALoopAndAPanePaintOnePicture` now saves **each** generated
    layout and asks the two doors for zero differing pixels, the same box per `special` row and
    ink inside every one of those boxes, and prints what each row was worth on the machine that
    ran it.

    `canvas` is a deliberate argument rather than something read off `obj`: `paint` passes the
    size the **record** carries (a library file's own `width`/`height`, which is what the
    panel is told to expect), `draw` passes the size the **object** declares.  A call that
    conflated them would be a picture cropped or padded at a size nobody declared, and the
    two are *not* the same number for the four 320x240 pages in the library - which
    `themes.scan()` refuses to select, for the reason written above that refusal: a 320x240
    layout drawn at 480 multiplies an unmeasured convention by 1.5.  So the split is held
    today by refusal and by `tests/test_specials.py`, not by the library's contents.
    """
    vals, absent = values(metrics, when)
    fill_lines(vals, metrics)
    img, notes = layout.draw_theme(obj, vals, canvas=canvas, specials=SPECIALS)
    # **A `special` row that comes back with no box is said out loud, with its reason.**
    # `layout.draw_theme` records such a row with `box=None`, and its own comment explains why:
    # the drawing had nothing to say.  That is true of a reading this machine lacks - a box with
    # no tachs still draws `CPU FAN -- RPM`, because `fill_lines` builds the figure - but it is
    # *not* true of a key the table never carried, which is a fault in this module rather than in
    # the machine.  Six names - `temp-cpu`, `temp-gpu`, `fan-cpu`, `fan-gpu`, `readings`,
    # `status` - exist nowhere but in `fill_lines`, so a door that skips that call loses those
    # rows from the glass without one word of warning: exactly what the owner saw.  Both doors
    # fill now, and `tests/test_specials.py` holds the two halves apart - the parity of the
    # picture, and the sentence a door that stops filling has to leave in the notes.
    for kind, what, box, _i in (notes.get("boxes") or []):
        if kind != "special" or box is not None:
            continue
        want = sorted(key for key, _fn in (SPECIAL_LINES.get(str(what)) or ())
                      if key not in vals)
        if want:
            notes["missing"].append(f"special:{what}")
            absent[f"special:{what}"] = (
                "this door's value table carries no " + ", ".join(want)
                + ": a registered `special` draws nothing when the keys it reads are absent, "
                "so the frame this loop sends has no such row")
    # `draw_theme` says which widgets it skipped; this says why, in the words this module
    # chose when it refused to invent a reading.  Both belong in the notes.
    notes["absent"] = absent
    if scrim:
        img = render.scrim(img, max(1, min(255, int(scrim))))
    return img, notes


def paint(record: dict, metrics: dict, when=None, scrim: int = 0, base=None) -> tuple:
    """One 480x480 RGBA overlay for a library theme, plus the notes that explain it.

    Returns (image, notes) where notes come from `layout.draw_theme` - every font
    substitution, every skipped widget, every gap touched.  The image is the OSD layer
    only: like our own themes it carries transparency, and the background underneath it
    is the panel's business (or the loop's, for a preview).

    This is the door the **frame loop** uses: a name resolves to a record, the record's file
    is loaded and painted at the canvas the record declares.  `draw` is the door for an object
    that never arrived as a file - a generated export, an editor's buffer, the preview pane -
    and both go through `_overlay`, which is what makes "the pane shows what the glass will
    show" a property of the code rather than a hope.

    `scrim` is the same plate rule our own five get (`render.scrim`): it is built from the
    layer's own alpha, so it needs no per-theme geometry, and a library theme over a
    bright clip needs it for the same reason `alpha` does - docs/limits.md keeps the luma
    figures, and `theme_48.mp4` at 227.3 of 255 is the case that decided it.
    """
    img, notes = _overlay(load(record["path"]), (record["w"], record["h"]), metrics, when, scrim)
    if base is not None and base[3] == 255:
        # `--bg black` is *stronger* here than for our own five: a layout's plate goes
        # under the finished layer, so every pixel of the frame comes out at alpha 255
        # and the panel's stored background is covered completely.  A `theme_*` body
        # instead opens its image with the canvas (`Image.new("RGBA", (W * SS, H * SS), bg)`)
        # and `ImageDraw` replaces a translucent fill rather than blending it with the canvas,
        # so `alpha`, `dual` and `gauge` keep leaking at their own translucent parts.  The
        # suite measures both halves; docs/usage.md's `--bg` row states the split.  Both
        # doors keep transparent as the default, because that is the vendor's shape.
        img = Image.alpha_composite(Image.new("RGBA", img.size, base), img)
    return img, notes


def origin(record: dict) -> str:
    """One of three words for where a record's file came from."""
    if record.get("edited"):
        return "your copy"
    return "checkout" if record["root"] == os.path.abspath(REPO_ROOT) else "package"


def draw(obj: dict, metrics: dict, when=None, scrim: int = 0) -> tuple:
    """Paint a layout object that did not arrive as a file: a generated export, an edited
    buffer on its way to disk, the thing a preview pane needs.

    The same door as `paint` in every part that decides a pixel - `_overlay` is one function
    both call, so the source table, the `fill_lines` composites a `special` row reads, the
    painter and the plate are shared rather than duplicated twice with different arguments.
    What differs is only where the canvas comes from: this one takes the `width` and `height`
    the **object** declares, `paint` takes the record's.

    Before that sharing, the two tables were not the same table and the claim in this
    docstring was the honest one to make about the code: an editor's pane painted rows the
    loop's frame did not contain.  `tests/test_specials.py`'s `ALoopAndAPanePaintOnePicture`
    saves one of the generated layouts and demands zero differing pixels from the two doors,
    so this sentence cannot become false again without a check failing.
    """
    return _overlay(obj, (obj.get("width") or render.W, obj.get("height") or render.H),
                    metrics, when, scrim)


#: Which background each of the five themes drawn from `render.py` is shown against.
#: Not a vendor record - the vendor library holds no page for a theme it did not draw -
#: and not a guess either: these are the clips this project's own published pictures are
#: composited over.  The README's five MP4s are named `<theme>-<clip>.mp4` for it
#: (`alpha-Theme_25.mp4`, `gauge-3.mp4`, ...), and docs/limits.md's census table prints a
#: row per file with that clip's measured luma.  `tests/test_theme_library.py` derives this
#: mapping back out of those file names on every run and fails if it disagrees, so the
#: pairing here cannot drift away from the pictures a reader judges the themes by - which
#: is also how the amber-ink figure falls out on its own, since its clip part is not a file
#: any media root holds.  Every value is a bare name, and each resolves through
#: `main.media_roots()` - the same lookup the window and the loop share - which that same
#: file checks on a bare checkout with nothing installed.
CODE_CLIPS = {"alpha": "Theme_25.mp4", "gauge": "3.mp4", "dual": "Theme_30.mp4",
              "clock": "Theme_07.mp4", "bars": "theme_52.mp4"}


def pair(name: str) -> tuple:
    """Which background clip a theme names, and the reason when it names none.

    Two kinds of answer, both read from a file this repository keeps:

    * A vendor layout declares exactly one clip in `background.mediaFile` - 23 of the
      library's 27 do, and the 23 values are distinct (`scan()` keeps the field for that
      reason, and `--list-themes` prints it).
    * One of the five themes this program draws itself names the clip its own published
      picture sits over (`CODE_CLIPS`), which is why picking `gauge` in the window's
      layout dropdown moves the preview the same way picking `Theme_07` does.

    Anything else - a generated layout somebody authored, a refused 320x240 page, a name
    that is not a layout at all - answers with a *reason* rather than an empty string, so
    the window can say, in the place the question was asked, that the theme under the
    cursor has no clip of its own instead of silently keeping whatever was there.

    The answer comes from whichever file `resolve()` chose, so a copy you have edited
    pairs with the clip your copy names, not the vendor's.

    Returns `(clip_basename, why_not)`; exactly one of the two is ever non-empty.
    """
    if name in EXPORTS:
        clip = CODE_CLIPS.get(name)
        if clip:
            return clip, ""
        return "", (f"{name} is drawn from `render.py` and names no published backdrop, "
                    f"so nothing pairs with it but what you chose")
    rec = resolve(name)
    if rec is None:
        return "", why_not(name)
    if not rec.get("background"):
        return "", (f"{os.path.basename(rec['path'])} declares no `background.mediaFile`")
    return os.path.basename(str(rec["background"])), ""


def describe(record: dict) -> str:
    """One line: what `--theme <name>` will draw, and where the file came from."""
    return (f"  {record['name']:<12} {record['id']}  {record['w']}x{record['h']} "
            f"ratio {record['ratio']}  {record['widgets']} widgets  "
            f"background {os.path.basename(record['background'])}  from {origin(record)}")


# ------------------------------------------------------------ field census --
#: Which layouts the census counts: the vendor's own trees, never the user directory.
#: The numbers in docs are measurements of the vendor's library, so an edit of yours must
#: not be able to move them.
CENSUS_ROOTS = ("layouts",)


def field_census() -> dict:
    """Every key the vendor's `property` objects carry, and who reads it.

    Counted over the shipped layouts only (the checkout's tree, or the installed one), so
    it is a measurement of the vendor's library and not of this machine or of your edits:
    152 widgets in 27 files answer to **33** distinct property keys.  The split that
    matters for an inspector: 21 of the 33 are read by `layout.py`, and 12 are carried by
    vendor files and never read at all - they are the vendor editor's own bookkeeping
    (`enableMove`, `screenStatus`, `coordBoundary`...).  Values are counted as well,
    because "we ignore this key" is only honest when you can say what it would have done:
    `italic` and `underline` are False on every one of the 132 widgets that carry them, so
    nothing is missing from our drawing by dropping them.
    """
    per_kind: dict = {}
    keys: dict = {}
    values: dict = {}
    time_per_file: dict = {}
    pickable, refused = scan()          # first-winning, so one file per layout name
    for path in sorted(r["path"] for r in pickable + refused):
        if not path.endswith(".json"):
            continue
        if True:
            obj = load(path)
            seen_times = set()
        for wd in (obj.get("osd") or {}).get("widget") or []:
            kind = str(wd.get("type") or "")
            per_kind[kind] = per_kind.get(kind, 0) + 1
            for prop in wd.get("property") or []:
                for k, v in prop.items():
                    keys.setdefault(k, {}).setdefault(kind, 0)
                    keys[k][kind] += 1
                    if isinstance(v, (dict, list)):
                        v = json.dumps(v, sort_keys=True)
                    values.setdefault(k, {}).setdefault(str(v), 0)
                    values[k][str(v)] += 1
                    if k == "time":
                        seen_times.add(str(v))
        time_per_file[os.path.basename(path)] = len(seen_times)
    return {"widgets": sum(per_kind.values()), "kinds": per_kind, "keys": keys,
            "values": values, "time_per_file": time_per_file}


#: The `xigma` sub-keys this program reads, each with the reason it had to be added.  The
#: list is *derived* - `keys_read()` finds them by reading `layout.py`'s source - so this
#: table cannot grow silently: a new extension key appears in the census whether or not it
#: has a reason written here, and `tests/test_conventions.py` asserts the
#: two agree. That is the whole mechanism for "every schema addition has a
#: stated reason, or it does not go in".
XIGMA_KEYS = {
    "anchor": "our five draw text centred (`render._text` anchors on \"mm\"); the vendor's "
              "files anchor on the em box's top-left, so an export has to say which",
    "autoFitMax": "our five shrink a face until the line fits (`render._fit_size` walks "
                  "down in steps of 2 to a floor of 10); the vendor schema has a fixed "
                  "`fontSize` and no such rule.  On a `special` row that draws a pair it "
                  "is the budget each figure gets on its own - the pair still draws at "
                  "one size, the smaller of the two fits, which is the rule "
                  "`xigma.autoFitMax` cannot express by itself (docs/limits.md).  It is "
                  "not read at all by the ring-fitted pair door (`temp-values`, "
                  "`temp-labels`), whose size the ring decides: see `xigma.fitArc`",
    "showIf": "another reading this row's drawing depends on: the row is drawn only when "
              "that source has a value.  It exists for the shape `bars` draws and the "
              "vocabulary cannot say - a meter that divides two fields (`used / total`) "
              "beside a number that prints one of them (`Used RAM`): the theme behind the "
              "file draws neither when the division cannot be made, so the number row names "
              "the meter's source here.  A row whose dependency is unanswered is reported "
              "in `missing` as `showIf:<source>`, like any other hole, rather than drawing "
              "nothing quietly",
    "fitArc": "the ring a `special` row's text is sized against, spelled in an `arc` "
              "row's own vocabulary: {cy, radius, width, angleStart, angleEnd}, `radius` "
              "the inner edge and `width` the stroke (so outer = radius + width), the "
              "angles the app's own degrees where 0 is the bottom of the circle - the "
              "same rule `layout.arc_angles` measures off the vendor's ring.  One ring is "
              "enough: the pair's two are congruent, and the row is symmetric about its "
              "own x.  The key exists because our `_fit_arc` picks one size for the two "
              "temperature columns by measuring their ink against this hole, and no width "
              "can do that job: `tests/test_specials.py` searches every whole-pixel "
              "budget this canvas holds and finds none that reproduces the six sizes "
              "it picks (docs/limits.md). "
              "A `values` row that declares no ring cannot be sized, and `--check-theme` "
              "says which of its keys is missing rather than drawing at the ceiling and "
              "letting a reader find the overlap on the glass",
    "format": "our date and time shapes are ours (`render.date_str` writes "
              "`%A %d %B %Y`); the vendor `Date` shape in this repo is `%m/%d/%Y`; neither "
              "has been measured off the vendor's picture, so rewriting our theme to the "
              "other one would change the glass for no measured reason",
    "colourRamp": "a ramp this program draws, named rather than copied into stops: "
                  "`heat` divides by the literals 0.3 and 0.2 where its own breakpoints "
                  "would give 0.30000000000000004 and 0.19999999999999996, so the data "
                  "spelling is off by one unit at 8 of 100 sampled positions. The owner "
                  "chose to name it (no pixels change, every figure read off dual, alpha "
                  "and bars stays valid); sampled along the sweep on an arc, at the "
                  "value fraction on a bar",
    "barPaint": "which painter's bar convention this widget was authored for: `vendor` "
                "(fill spans round(width x fraction), corners as declared), `render` "
                "(device-space truncation, track corners at height/2, fill corners a "
                "function of the reading, floor 0.02) or `hbar` - the one entry that names "
                "a drawing function rather than a set of rules, so it is held to that "
                "function's pixels: `render.hbar`'s square ends whatever the file declares, "
                "its track the whole declared rect, its fill coloured one device column at "
                "a time, so the ramp's far end moves with the reading. 360 px at 63.5 % is "
                "457 device px one way and 456 the other, so a bar export without the key "
                "is a different picture by pixels, not by intent",
    "colourStops": "a ramp written as data: [fraction, rgba()] pairs, interpolated "
                   "piecewise-linearly. Measured against both ramps this repo draws, at "
                   "every position its ring steps through: `render.temp_colour` agrees "
                   "at all 100 of them, `render.heat()` disagrees at 8, never by more "
                   "than one unit and only in red and blue, all 8 in the two segments "
                   "where `heat` divides by the literals 0.3 and 0.2 while its own "
                   "breakpoints give 0.30000000000000004 and 0.19999999999999996. So a "
                   "three-stop value-keyed ring is data here, and `heat` is an open "
                   "question about our arithmetic - which is what blocks `dual`",
    "arcPaint": "which painter's ring convention this widget was authored for: `vendor` "
                "(1-degree segments, colour sampled at each segment's middle - measured "
                "off ALPHA's frames) or `render` (3-degree segments, 0.4 degrees of "
                "overlap, colour at the segment start, truncating lerp - what "
                "`render.gauge` does). On one arc with two unchanged colours that is "
                "164 / 3 366 / 3 889 / 6 989 differing pixels at four readings: the "
                "difference is a drawing, not a rounding, so an export that claims to "
                "describe our ring has to name it",
}

#: Why each key we do not read is safe to leave unread.  The *counts* are deliberately not
#: written here: `--print-theme-fields` prints them out of the census, so a claim like
#: "nothing is lost by dropping this one" is re-measured on every run instead of aging.
UNREAD_WHY = {
    "canvasProperties": "mirrors the file's own width/height",
    "controlName": "the vendor editor's own widget label; `id` is the key this program keys on",
    "coordBoundary": "mirrors the canvas bounds, which the `ratio` gate already reads",
    "enableMove": "the vendor editor's drag lock; nothing moves at draw time",
    "italic": "a text slant this program does not apply",
    "italicAngle": "the same slant, as a degree",
    "screenStatus": "which screen of the vendor app the widget was on",
    "time": "the vendor editor's save stamp - and our exports omit it, because a generated "
            "file has no save event to stamp",
    "type": "the widget's kind a second time, as a number",
    "underline": "a text underline this program does not apply",
    "valueChangeType": "how the vendor app animated a value between samples",
}


@functools.lru_cache(maxsize=1)
def keys_read() -> tuple:
    """The `property` keys this program actually reads - taken out of `layout.py`'s own
    source with `ast`, not from a hand-kept list.

    A hand-written list here would be a second source of truth, and the way it goes stale
    is the way the census goes wrong: the painter gains or drops a key and the table keeps
    claiming the old set.  This asks the module instead - every `prop["k"]` and
    `prop.get("k")` in it - so the two cannot disagree.

    **Memoised, because the derivation is a fact about a source file and not about a
    call.**  `layout.py` does not change while a process runs, so reading the file,
    compiling it and walking ~29 000 AST nodes is work that can be done once.  It was not:
    `Editor.move_to` asks which fields a kind offers, and `Editor.set` asks twice, so one
    mouse-move of a drag in the layout editor paid for **five** parses of the painter.
    Measured on the author's bench while writing this, profiling 40 real move events of a
    drag on `bars`: 30.1 ms per move, of which 20.3 ms (67%) was this function - more than
    twice the 9.7 ms the actual painting costs.  `tests/test_canvas.py` counts the source
    reads an act makes, which is a count and not a duration, so it holds on any box.

    A caller that swaps `xigmalcd.layout` for something else - no shipped code does, and
    the census tests above re-derive the set rather than trusting a copy - has to say so
    with `keys_read.cache_clear()` first.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(layout))
    found, sub = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                and node.value.id in ("prop", "ext") \
                and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            (sub if node.value.id == "ext" else found).add(node.slice.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in ("prop", "ext") and node.args \
                and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            (sub if node.func.value.id == "ext" else found).add(node.args[0].value)
    return tuple(sorted(found)), tuple(sorted(sub))


# ------------------------------------------------------- canonical file shape --
#: Every one of the 27 copied layouts is, byte for byte, `canonical()` of its own parsed
#: content - one indentation, sorted keys, no trailing whitespace - checked on all
#: 27 by `tests/test_theme_files.py`.  The only thing the vendor's own files disagree
#: with each other about is
#: escaping: **18** write non-ASCII strings as `\uXXXX` and **9** keep them raw (the ones
#: carrying a `宋体` family or CJK `content`), which is `json.dump`'s `ensure_ascii` switch
#: and nothing else.  Measured, because it decides what "the round trip is the identity"
#: can promise: a writer that always escaped would "change" 9 files it had not touched.
CANON_INDENT, CANON_KEYS = 1, True


def canonical(obj: dict, ensure_ascii: bool = True) -> str:
    """The file shape this library is stored in, and the one the writer emits."""
    return json.dumps(obj, indent=CANON_INDENT, sort_keys=CANON_KEYS,
                      ensure_ascii=ensure_ascii)


def shape_of(path: str) -> bool:
    """The `ensure_ascii` that reproduces one file exactly - or None if neither does.

    A copy for editing inherits its source's shape, so the diff between the vendor's file
    and yours is only the fields you touched, and "did my editor corrupt this?" has an
    answer that does not need a diff tool.
    """
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    obj = json.loads(raw)
    for esc in (True, False):
        if raw in (canonical(obj, esc), canonical(obj, esc) + "\n"):
            return esc
    return None


# ------------------------------------------------------------- validation --
#: The ten `fontSize` values the shipped library actually uses (counted across the 27
#: layouts).  Outside that set is not wrong - it is untried, which is a different thing,
#: and the report says which.
MEASURED_FONT_SIZES = (12, 14, 16, 20, 24, 32, 40, 70, 100, 140)


def validate(obj: dict) -> tuple:
    """(hard, soft) about a layout object: what refuses to draw, and what is worth saying.

    Hard means `layout.draw_theme` cannot walk it at all (no widgets to walk, a `property`
    that is not the one-element list every vendor file uses).  Soft is everything else: an
    unknown metric name, an off-canvas coordinate, a size outside the ten shipped ones, a
    colour that is not `rgba(...)`, a `special` with no drawing, a font family not in the
    table.  The rule of this repo is that a choice is *said*, not silently repaired, so the
    writer accepts a soft problem and prints it, and the loop's own report at draw time
    still carries the same facts in `notes`.
    """
    hard, soft = [], []
    if not isinstance(obj, dict):
        return ["not an object"], soft
    w, h = int(obj.get("width") or 0), int(obj.get("height") or 0)
    if not w or not h:
        hard.append("no width/height declared")
    widgets = ((obj.get("osd") or {}).get("widget"))
    if not isinstance(widgets, list):
        return hard + ["no `osd.widget` list"], soft
    if not widgets:
        return hard + ["an `osd.widget` list with nothing in it: there is nothing to "
                       "draw, which is not the same as an empty canvas"], soft
    seen_ids = set()
    _answerable = set(source_names()) | set(UNMAPPED)
    for i, wd in enumerate(widgets):
        kind = str(wd.get("type") or "")
        if kind not in layout.KINDS:
            soft.append(f"widget {i}: unknown kind {kind!r}")
            continue
        prop = wd.get("property")
        if not isinstance(prop, list) or not prop:
            hard.append(f"widget {i} ({kind}): `property` must be a one-element list, "
                        "like every vendor file")
            continue
        if len(prop) > 1:
            hard.append(f"widget {i} ({kind}): `property` has {len(prop)} entries; "
                        "every one of the 152 vendor widgets has exactly one, and "
                        "`draw_theme` reads only `property[0]` - the rest would be "
                        "silently unwritten")
            continue
        pr = prop[0]
        wid = str(wd.get("id") or "")
        if wid in seen_ids:
            soft.append(f"widget {i}: id {wid!r} repeats inside this theme "
                        "(vendor files reuse ids ACROSS themes - 152 widgets answer to 54 "
                        "ids - so a row is keyed by theme and id, never by id alone)")
        seen_ids.add(wid)
        x, y = pr.get("x"), pr.get("y")
        if x is None or y is None:
            hard.append(f"widget {i} ({kind}): no x/y")
        elif w and not (0 <= int(x) < w and 0 <= int(y) < h):
            soft.append(f"widget {i} ({kind}): x={x} y={y} is outside the {w}x{h} canvas")
        if pr.get("fontFamily") and str(pr["fontFamily"]).lower() not in layout.FONTS:
            soft.append(f"widget {i} ({kind}): family {pr['fontFamily']!r} is not in "
                        f"layout.FONTS ({' '.join(sorted(layout.FONTS))}) - its widgets "
                        f"will be skipped at draw time and reported")
        if pr.get("fontSize") and int(pr["fontSize"]) not in MEASURED_FONT_SIZES:
            soft.append(f"widget {i} ({kind}): fontSize {pr['fontSize']} is outside the "
                        f"ten sizes the shipped library uses "
                        f"({' '.join(str(x) for x in MEASURED_FONT_SIZES)})")
        if pr.get("textColor") and not str(pr["textColor"]).startswith("rgba("):
            soft.append(f"widget {i} ({kind}): textColor {pr['textColor']!r} is not the "
                        "`rgba(r, g, b, a)` spelling the library uses everywhere")
        src = pr.get("source")
        if src and src not in _answerable:
            soft.append(f"widget {i} ({kind}): source {src!r} has no entry in the "
                        f"vocabulary this program answers ({len(source_names())} names "
                        f"from themes.source_names() - the flat fields, the derived "
                        f"ratios, the clock and the fan slots - plus "
                        f"{len(UNMAPPED)} it names but cannot read) - it will be "
                        "reported as unanswered")
        shown_if = (pr.get("xigma") or {}).get("showIf")
        if shown_if and shown_if not in _answerable:
            soft.append(f"widget {i} ({kind}): xigma.showIf names {shown_if!r}, which "
                        "this program cannot answer.  A row whose dependency can never "
                        "be satisfied never draws at all, and what would be said at "
                        "draw time is a missing reading, not a mistyped key")
        stops, why = layout.colour_stops(pr)
        if why:
            soft.append(f"widget {i} ({kind}): xigma.colourStops is malformed - {why}")
        if kind == "arc" and layout.arc_paint(pr)[0] is None:
            soft.append(f"widget {i} (arc): xigma.arcPaint {layout.arc_paint(pr)[1]!r} "
                        f"is not one of {' '.join(sorted(layout.ARC_PAINT))} - the ring "
                        f"will be reported as unwritten rather than drawn by guesswork")
        if kind == "bar" and layout.bar_paint(pr)[0] is None:
            soft.append(f"widget {i} (bar): xigma.barPaint {layout.bar_paint(pr)[1]!r} "
                        f"is not one of {' '.join(sorted(layout.BAR_PAINT))} - the bar "
                        f"will be reported as unwritten rather than drawn by guesswork")
        if kind == "special" and str(pr.get("name") or "") not in SPECIALS:
            soft.append(f"widget {i}: special name {pr.get('name')!r} has no drawing "
                        f"(--list-specials prints {' '.join(special_names())})")
        # ...and a name that does have one can still be missing what that drawing needs to
        # size itself with.  A `values` row without a ring cannot be fitted at all - it is
        # not drawn, and the reason is said here rather than left for a reader to find as
        # text sitting on top of a gauge.
        if kind == "special":
            door = special_door(str(pr.get("name") or ""))
            if door == "values":
                _ring, why = layout.fit_ring(pr)
                if _ring is None:
                    soft.append(f"widget {i} (special {pr['name']}): {why} - the row has "
                                f"no ring to size its text against, so it is not drawn")
            if door in ("pair", "values") and not pr.get("width"):
                soft.append(f"widget {i} (special {pr['name']}): no `width`, so both "
                            f"figures land on one point - on a pair row `width` is the "
                            f"distance between their centres, not a box width")
        if kind in ("text",) and pr.get("content") is None:
            soft.append(f"widget {i} (text): no `content` string to draw")
    return hard, soft


# ------------------------------------------------------------- the file model --
def user_theme_path(name: str) -> str:
    """Where an edited or new theme of yours would live."""
    return os.path.join(user_root(), f"{name}.json")


#: How long a layout name may be.  The window deliberately does *not* cap its name box
#: at this (`xigmaui/app.py` says why: a box that stops at the limit drops characters and
#: then presses the button with a name nobody typed), so the writer has to refuse past it
#: in words that name the limit - which is what `tests/test_names_and_renames.py` holds:
#: the edge usable, one past it refused, the refusal quoting this constant.
NAME_LIMIT = 64

#: What this module writes *beside* a layout file: `<name>.json.bak` is the previous
#: contents of your last save, and `<name>.json.tmp` is the scratch an atomic write renames
#: into place.  A layout whose name ends in one of them is a directory that lies about
#: itself - measured, not imagined: name the layout `suff.json` and its file is
#: `suff.json.json`, while the `suff.json` sitting next to it is the layout named `suff`.
#: Nothing in this library has such a name - none of the 27 layout names in the three roots
#: ends in any of these, the vendor's own stems being `Theme_NN`, `theme_NN` and four
#: timestamps - so refusing one refuses nothing that already exists.
WRITER_SUFFIXES = (".json", ".bak", ".tmp")


def _safe_name(name: str) -> str:
    """A theme name that cannot escape the user directory, cannot shadow one of the five
    names this program draws from code (those are generated, never stored: a saved
    `gauge.json` would be a second source of truth for `theme_gauge`, which is the failure
    mode docs/theme-editor.md's whole export design exists to avoid), and cannot end in one
    of the suffixes this module uses for its own side files (`WRITER_SUFFIXES` above)."""
    n = str(name or "").strip()
    if not n or n != os.path.basename(n) or "/" in n or "\\" in n or n.startswith("."):
        raise ValueError(f"unsafe theme name {name!r}: a name is one path element, no "
                         "separators, no leading dot")
    if len(n) > NAME_LIMIT:
        raise ValueError(f"theme name {name!r} is longer than {NAME_LIMIT} characters")
    if n in render.THEMES:
        raise ValueError(f"{n!r} is one of the five themes drawn from render.py; those are "
                         "generated by --export-theme rather than saved, so the two cannot "
                         "drift apart")
    for suf in WRITER_SUFFIXES:
        if n.lower().endswith(suf):
            raise ValueError(f"theme name {name!r} ends in {suf!r}, one of the suffixes "
                             f"this program writes beside a layout "
                             f"({', '.join(WRITER_SUFFIXES)}); that name would live at "
                             f"{n}.json while the file {n}.json in the same listing is a "
                             "different layout")
    return n


def name_space() -> tuple:
    """Every name and id `resolve()` answers, as `(spelling, kind, record)` triples.

    Three kinds, because `resolve()` matches three things: a layout's name exactly, that
    name ignoring case, and the file's `id`.  Measured on this library: 27 names, all
    distinct even folded, and 27 distinct ids across the two vendor roots - the name space
    is roomy, so a clash is something a person chose rather than something the vendor left
    behind.  And a copy put at a name that is already in here does not sit *next to* the
    layout that had it: `scan()` keeps one record per name and the user root comes first in
    `roots()`, so the other one stops being reachable at all - `resolve(<vendor id>)`
    answering None after a copy is written at that vendor's name is the measured form.
    """
    ok, out = scan()
    seen = []
    for rec in list(ok) + list(out):
        seen.append((rec["name"], "name", rec))
        seen.append((rec["id"], "id", rec))
    return tuple(seen)


def why_taken(name: str, free_of: str = "") -> str:
    """Why `name` is not a free name for a copy - or `""` when it is.

    `free_of` is the copy being renamed, so one of the two spellings of *its own* name is
    not a clash: a case-only rename of a copy you already hold is a legal act, measured to
    leave one record and one file that `--theme` answers under either spelling.

    What the refusal says is the consequence, measured: with a copy at `theme_07` beside the
    vendor's `Theme_07`, `--list-themes` shows two layouts while every spelling resolves to
    the one file, `main.theme_name` canonicalises the vendor's own spelling to the copy's,
    and the vendor's layout cannot be named by anybody.  A name that agrees with an **id**
    does the same thing to that id, which is how a copy at a vendor's name hides a layout
    whole - so "unused" has to mean name *and* id *and* case, not one of the three.
    """
    want = str(name or "").strip()
    if not want:
        return ""
    for spelling, kind, rec in name_space():
        if want != spelling and want.lower() != spelling.lower():
            continue
        if free_of and spelling.lower() == str(free_of).lower():
            continue
        return (f"{name!r} is not a free name: {origin(rec)} {rec['name']!r} answers "
                f"{kind} {spelling!r} today, at {rec['path']}. A copy of that name is what "
                f"--theme {name} would draw, and {rec['name']!r} would stop being "
                f"reachable - by its id as well, which is how a copy at another layout's "
                f"name hides it whole. Drop that copy first (the window's revert, or "
                f"delete {rec['name']}.json in {user_root()}) or choose another name.")
    return ""


def new_name(name: str, free_of: str = "") -> str:
    """The name a copy may take: one the writer accepts, and one nothing answers today.

    `save()` deliberately does **not** call this - writing at a name that already exists is
    how an edited copy shadows a vendor layout, which is the point of the file model
    (docs/themes.md).  This door is for the acts that *invent* a name: renaming a copy, and
    saving one under a second name.  Both raise, because printing the refusal is what a
    window here does rather than unwinding through one.
    """
    n = _safe_name(name)
    bad = why_taken(n, free_of=free_of)
    if bad:
        raise ValueError(bad)
    return n


#: Ids handed out by this process.  Not a cache of the library: a fresh id has to be clear
#: of the ids already in this run's copies as well as the vendor's, and two renames a
#: millisecond apart are two actions rather than a coincidence.
_ISSUED: set = set()


def new_id() -> str:
    """A layout id in the shape this library already uses, clear of every other one.

    The shape is measured rather than chosen: all 27 vendor layouts carry a 13-digit `id`,
    and read as milliseconds since the epoch they fall inside 1 187 564 ms of one another on
    2025-09-10 - the stamp of an application saving a layout, which is also why the vendor's
    own files are named `<id>.json`.  Widget ids in this library are uuid4 and layout ids are
    not, so this follows the files rather than the widgets.

    Clear of every other one, because `resolve()` matches an id as well as a name: while two
    files share an id, `--theme <id>` answers whichever one `scan()` happens to sort first,
    which is nobody's idea of a decision.  So the candidate is "now, or one past the highest
    id on disk", walked up until it is free.
    """
    ok, out = scan()
    taken = {str(r["id"]) for r in list(ok) + list(out)} | set(_ISSUED)
    highest = max((int(i) for i in taken if str(i).isdigit()), default=0)
    cand = max(int(time.time() * 1000), highest + 1)
    while str(cand) in taken:
        cand += 1
    _ISSUED.add(str(cand))
    return str(cand)


def is_copy(name: str) -> bool:
    """Whether the layout answering `name` is one of yours: a file in the user root."""
    rec = resolve(name)
    return bool(rec and rec.get("edited"))


def copy_for_edit(name: str) -> tuple:
    """Seed an editable copy of a library theme in the user directory.

    Returns (record, path, soft warnings).  The copy keeps the shape of the file it came
    from (`shape_of`), so the only difference between it and the vendor's file is what you
    change afterwards, and the original is never written to: `themes/alpha` under a checkout
    and `/usr/share/xigmalcd/themes/alpha` under a package are both read-only here.
    """
    rec = resolve(name) or next((r for r in scan()[1]
                                 if name.lower() in (r["name"].lower(), r["id"].lower())),
                                None)
    if rec is None:
        raise KeyError(f"no pickable layout named {name!r}: {why_not(name)}")
    obj = load(rec["path"])
    hard, soft = validate(obj)
    if hard:
        raise ValueError("; ".join(hard))
    path = os.path.join(user_root(), rec["name"] + ".json")
    os.makedirs(user_root(), exist_ok=True)
    # byte for byte, not re-dumped: a copy that starts out different from its source makes
    # every later diff a lie. `shape_of` is what says this is even possible - every vendor
    # file is reproducible from its own parsed content, 27 of 27.
    tmp = path + ".tmp"
    with open(rec["path"], "rb") as src, open(tmp, "wb") as dst:
        dst.write(src.read())
    os.replace(tmp, path)
    return rec, path, soft


def save(obj: dict, name: str | None = None, root: str | None = None,
         backup: bool = True, ensure_ascii: bool = True) -> tuple:
    """Write one layout into the user theme directory, canonically and atomically.

    Returns (path, soft_warnings).  Hard problems raise; soft ones come back with the path
    and are also what `validate` reports at draw time.  Only `user_root()` is writable by
    design: `/usr/share/xigmalcd/themes/alpha` is dpkg-owned and `debian/tests/smoke`
    re-hashes 125/125 of its files on every install, and the checkout's copy is what every
    figure in the docs was read from - an edit landing in either would be an edit that
    breaks the evidence.  The previous copy of a name is kept as `<name>.json.bak` so
    "undo my last save" is a file operation, and the write is tmp-then-`os.replace`, so a
    crash cannot leave half a JSON where a working theme used to be.
    """
    hard, soft = validate(obj)
    if hard:
        raise ValueError("; ".join(hard))
    root = root or user_root()
    if os.path.abspath(root) != os.path.abspath(user_root()):
        raise ValueError(f"only {user_root()} is written to; {root} is "
                         + ("the vendor copy this program's figures were read from"
                            if os.path.abspath(root).endswith("themes/alpha")
                            else "not this program's directory to write in"))
    fname = _safe_name(name or (obj.get("id") or ""))
    path = os.path.join(root, fname + ".json")
    os.makedirs(root, exist_ok=True)
    if os.path.exists(path) and backup:
        with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
            dst.write(src.read())
    tmp = path + ".tmp"
    # every one of the 27 vendor files ends with a newline; so does what we write, or a
    # round trip through the editor would show up as a one-byte change in files nobody
    # edited
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(canonical(obj, ensure_ascii) + "\n")
    os.replace(tmp, path)
    return path, soft


def user_copies() -> list:
    """Names of the layouts in the user directory, i.e. the edits that are live now."""
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in _glob.glob(os.path.join(user_root(), "*.json")))


def delete_user_theme(name: str) -> str:
    """Back to the vendor's own: drop your copy, and the installed one is what `--theme`
    finds again.  Never touches anything outside the user directory."""
    path = os.path.join(user_root(), _safe_name(name) + ".json")
    if not os.path.exists(path):
        return ""
    os.unlink(path)
    for extra in (path + ".bak", path + ".tmp"):
        if os.path.exists(extra):
            os.unlink(extra)
    return path


def rename_copy(old: str, new: str) -> tuple:
    """Move one of your copies to a new name.  Returns `(path, what-is-worth-reading)`.

    Two things happen, and both are said in the notes rather than left to be inferred:

    * The file moves.  `<old>.json` becomes `<new>.json`, and `<old>.json.bak` - the
      contents your previous save replaced - moves with it, because a backup left behind
      under a name nothing else uses is debris no other door can clear: `delete_user_theme`
      looks beside the name it is given, so an orphaned `.bak` is permanent.  A
      `<old>.json.tmp`, which only an interrupted save leaves behind, is reported and left
      where it is - its half-written bytes belong to the old name, and moving them under a
      new one would be this program inventing a state it has not earned.
    * The `id` inside it changes.  A copy that takes a new name takes a fresh id
      (`new_id`), because `resolve()` matches an id as well as a name: leave the vendor's
      number in a file now called something else and `--theme <that number>` answers your
      copy while `--theme <vendor name>` answers the vendor's - one layout answering to two
      names, which is a file model with a crack in it.  So this is the one act in the file
      model that rewrites a layout, and the note names the id that went in.

    Raises `ValueError` for every way this can go wrong - not your copy to move, a name the
    writer refuses, a name some layout already answers (by name, by case-folded name, or by
    id), the same name asked for twice, a file already sitting at the destination - and
    moves nothing for any of them.
    """
    was = _safe_name(old)
    src = user_theme_path(was)
    if not os.path.isfile(src):
        mine = user_copies()
        who = resolve(was)
        raise ValueError(
            f"{was!r} is not one of your copies: {user_root()} holds "
            f"{', '.join(mine) if mine else 'nothing'}"
            + (f", and --theme {was!r} reads {who['path']}" if who else
               f", and nothing answers {was!r} at all")
            + ". The window's save, or copy_for_edit, is what makes a copy first")
    name = new_name(new, free_of=was)
    if name == was:
        raise ValueError(f"{was!r} is already the name this copy has: nothing moved")
    dst = user_theme_path(name)
    if os.path.exists(dst):                 # `scan()` should have seen it; the file wins
        raise ValueError(f"{dst} is already there, and moving onto it would delete a copy "
                         "without the `.bak` a save keeps")

    shape = shape_of(src)
    with open(src, encoding="utf-8") as fh:
        obj = json.loads(fh.read())
    was_id = str(obj.get("id"))
    obj["id"] = new_id()
    tmp = dst + ".tmp"
    os.makedirs(user_root(), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(canonical(obj, shape if shape is not None else True) + "\n")
    os.replace(tmp, dst)                    # the new file is down before the old one goes
    os.unlink(src)
    notes = [f"your copy moved: {was}.json is now {name}.json",
             f"its id went {was_id} -> {obj['id']}, in the shape the vendor's own files "
             f"use, so --theme {name} and --theme {obj['id']} answer this file and "
             f"--theme {was_id} no longer does"]
    back = resolve(was)
    if back is not None:
        notes.append(f"{was!r} answers {origin(back)} again: {back['path']}"
                     + (". That is the layout your copy was hiding: a copy written at a "
                        "vendor's own name takes the name *and* the id out of its reach, "
                        "and renaming it away gives both back"
                        if not back.get("edited") else ""))
    else:
        notes.append(f"a loop already running `--theme {was}` will not find that name, and "
                     "an unknown name is not an error there: `render.draw` falls back to "
                     f"`gauge`, so the glass would go on showing a picture of nobody's "
                     f"choosing. Re-point it - the socket's `theme` command takes the same "
                     f"names --theme does, and its answer for {name!r} is this file")
    for extra in (".bak", ".tmp"):
        if not os.path.exists(src + extra):
            continue
        if extra == ".bak":
            os.replace(src + extra, dst + extra)
            notes.append(f"{was}.json.bak came with it: undoing your last save is still "
                         "that save, under the new name")
        else:
            notes.append(f"a half-written {os.path.basename(src + extra)} stayed where it "
                         "is; nothing reads a `.tmp` as a layout, and its bytes are the "
                         "old name's")
    return dst, notes


# ------------------------------------------------------- the specials registry --
#: {name: callable(draw, prop, values) -> ink box}.  A special is a picture that stays
#: code-drawn and takes its position, size, colour and reading from the layout - the
#: decision that keeps `alpha`'s fan figures and temperature pair, and the two composite
#: readings lines, movable without baking PNGs (docs/theme-editor.md).  Three doors, and the
#: door is what decides what a row's fields mean: `layout.draw_special_line` for one line of
#: built text, `draw_special_pair` for two figures at one width-fitted size, and
#: `draw_special_values` for two figures at one size fitted to a ring's hole.  Which door a
#: name goes through is read out of the drawing (`themes.special_door`), not kept in a table
#: here.  Injected into `layout.draw_theme` from here, because the drawings live in
#: `render.py` and layout already imports render, not the other way round.
def _sp_clock_readings(draw, prop, values):
    """The clock theme's third line: built by `render.clock_readings_line`, placed here."""
    line = str(values.get("readings") or "")
    if not line:
        return None
    return layout.draw_special_line(draw, prop, line)


def _sp_dual_status(draw, prop, values):
    """`dual`'s middle line: `render.dual_status_line` builds it, the layout places it."""
    line = str(values.get("status") or "")
    if not line:
        return None
    return layout.draw_special_line(draw, prop, line)


def _sp_fan_figures(draw, prop, values):
    """`alpha`'s two fan figures: built and sized by code, placed by this one row.

    One row and not two, because the two figures share a single text size - each is fitted
    to its own budget and both draw at the smaller of the two fits, so a long CPU figure
    takes the GPU figure down with it. Sized separately they would not match:
    `tests/test_specials.py` walks 30 reading pairs and insists the joint rule
    shows up as a moved row exactly when the two fits disagree. How many of
    those 30 disagree, and how far the row moves when they do - 25 of them, 1
    763 to 2 915 px - are one bench's figures, recorded here, because both
    follow the faces installed. The vendor schema has no way to say "these two
    rows are one size",
    and the owner's decision (2026-11-08) was to keep the pair one code drawing rather than
    invent a group key.  The row can be moved, re-pitched, recoloured and resized; what
    stays in `render.fan_figures` is the rule that makes it a pair, which is the same
    function `theme_alpha` draws with.
    """
    pair = (str(values.get("fan-cpu") or ""), str(values.get("fan-gpu") or ""))
    if not any(pair):
        return None
    return layout.draw_special_pair(draw, prop, pair)[1]


def _sp_temp_values(draw, prop, values):
    """`alpha`'s two temperature figures: one row, **one size**, fitted to the rings.

    The second group special the owner's decision (2026-11-08) calls for, and the one that
    could not have been a key on the existing `xigma.autoFitMax`: the size here is decided
    by how the two strings sit inside the ring's hole, jointly, and a width cannot express
    that.  The suite searched every whole-pixel budget this canvas can hold - none
    reproduces the sizes `_fit_arc` picks for `--`, 5, 22, 57, 100 and 241 degrees; the best
    reaches five of the six, and the windows ask for at least 153 px and less than 148 px
    (docs/limits.md).

    So the row names the ring it has to clear (`xigma.fitArc`, spelled in an `arc` row's
    own vocabulary) and the size comes from `render.value_pair` - the same function
    `theme_alpha` draws its own values through, so a file and the theme cannot reach two
    different sizes for the same pair of readings.  What the row can change is where the
    pair sits, how far apart the two figures are, the ceiling, the ink and the weight; the
    3 px clearance and the walk's floor of 10 stay with the drawing, because they are what
    keeps the digits off the gauge.
    """
    pair = (str(values.get("temp-cpu") or ""), str(values.get("temp-gpu") or ""))
    if not any(pair):
        return None
    return layout.draw_special_values(draw, prop, pair)[1]


def _sp_temp_labels(draw, prop, values):
    """`alpha`'s two temperature *labels*, through the same door as its two figures.

    This row looks redundant and is not, so the reason goes on it: "CPU TEMP" and "GPU
    TEMP" are constants, so a layout *could* carry them as two `text` widgets - except
    `theme_alpha` does not size them that way.  It hands `_fit_arc` **both** strings and
    draws both at the one size that comes out, measured against the ring's hole exactly like
    the figures under them (`render.A26_TLBL_TEXT` names them together for that reason).
    Two `text` rows cannot say "we are one size": the schema's only fit key is a width, and
    the size the ring decides is a face metric of the machine drawing it - docs/limits.md
    has `tests/test_specials.py`'s exhaustive search showing no width reaches
    it. Baking the size this bench measured would be a layout that paints other
    pixels where the fonts differ, and
    an export that cannot be driven to a zero diff is not shipped.

    So it is one `special` with the `values` door, placing a pair of strings that never
    change: `x` their centre, `width` their pitch, `fontSize` the ceiling (the vendor's own
    32), `xigma.fitArc` the ring, `textColor`/`bold` the ink.  What the row does *not* take
    from the file is the words themselves: a layout that could rename them would be a
    different theme's picture, and `theme_alpha`'s words are what every parity gate here
    compares against, so they come from `render` - one place, the same place the code theme
    reads them.
    """
    return layout.draw_special_values(draw, prop, render.A26_TLBL_TEXT)[1]


#: Which door a registered drawing goes through, marked on the drawing itself: `line` is
#: one built string (`layout.draw_special_line`), `pair` two figures at one width-fitted
#: size (`draw_special_pair`), `values` two figures at one ring-fitted size
#: (`draw_special_values`).  The door is what decides what the row's fields mean, so the
#: marker lives here rather than in a table beside the registry - and
#: `tests/test_specials.py` reads each function's own source to check the
#: marker agrees with the call it makes.
_sp_clock_readings.door = "line"
_sp_dual_status.door = "line"
_sp_fan_figures.door = "pair"
_sp_temp_values.door = "values"
_sp_temp_labels.door = "values"


SPECIALS = {"clock-readings": _sp_clock_readings, "dual-status": _sp_dual_status,
            "fan-figures": _sp_fan_figures, "temp-values": _sp_temp_values,
            "temp-labels": _sp_temp_labels}

#: A `special` that draws text this repo builds in code: name -> the (key, builder) pairs
#: it needs.  Every door that paints fills those keys - `_overlay` calls `fill_lines` for
#: both `paint` and `draw`, and `parity` fills the same table for its own comparison - from
#: the same metrics the widgets' own `source`s come from, so the line the code theme writes
#: and the line the layout paints are one string built once: the composite cannot drift into
#: two versions of what the theme says.  A row that draws a pair lists both of its strings.
#: The keys are **not** `source` names a file may spell, which is the trap: a door that skips
#: this call still validates, still reports its rows, and paints the `special` ones as
#: nothing at all.
SPECIAL_LINES = {"clock-readings": (("readings", render.clock_readings_line),),
                 "dual-status": (("status", render.dual_status_line),),
                 "fan-figures": (("fan-cpu", render.cpu_fan_figure),
                                 ("fan-gpu", render.gpu_fan_figure)),
                 "temp-values": (("temp-cpu", render.cpu_temp_text),
                                 ("temp-gpu", render.gpu_temp_text))}


def fill_lines(vals: dict, metrics: dict) -> dict:
    """Add every composite string a `special` needs, built from this frame's readings."""
    for _name, builders in SPECIAL_LINES.items():
        for key, builder in builders:
            vals[key] = builder(metrics)
    return vals


def special_names() -> tuple:
    """Every name a `special` widget may carry. `--list-specials` prints this."""
    return tuple(sorted(SPECIALS))


def special_door(name: str) -> str:
    """Which door this `special` drawing goes through: `line`, `pair`, `values`, or `""`
    when the name is not registered.

    Read off the drawing function itself, because the door is what gives the row's fields
    their meaning - and a table kept beside the registry would be a second opinion about
    someone else's drawing.  The suite reads each function's own source and fails if the
    marker and the `layout.draw_special_*` call disagree.
    """
    return str(getattr(SPECIALS.get(str(name)), "door", ""))


def special_is_pair(name: str) -> bool:
    """Does this row place **two** figures, by its `x` (their shared centre) and its
    `width` (the pitch between them)?

    Both pair-shaped doors do; `special_door` says what differs between them - a width
    budget sizes `fan-figures`, the ring named in `xigma.fitArc` sizes `temp-values`
    (docs/limits.md has the measurement for why a width cannot do that second job).
    """
    return special_door(name) in ("pair", "values")


# ------------------------------------------------------------------ exports --
def with_ink(obj: dict, theme: str, ink) -> tuple:
    """A copy of one generated layout, its glyph colours moved to a reader's ink.

    **Only a generated layout.**  A layout's colours are its own - that is the rule
    `layout.py` states at the top of the module and the reason a vendored theme looks the
    same here as in the vendor's app - so this function is for the five names this repo
    draws from `render.py`, and it is what lets the window preview one of those *as a file*
    without losing the text-colour the reader picked.  Measured before it existed: the
    window's ink row moved the code drawing by 18 475 px on this bench's readings and the
    file door by **0 px**, because `themes.draw` has no ink argument and was right not to
    have one.

    The rule is key-scoped, not colour-scoped, and that distinction is load-bearing:
    `bars` uses `CYAN` both as a heading glyph and as the `startColor` of all ten of its
    meters, and only the `textColor` fields follow an ink.  Arcs, bars, tracks and rings
    keep their colours - several of those colours are measurements off the vendor's own
    frames, and `_skin`'s docstring already says graphics are not ink.

    `theme` names the drawn theme the layout was generated from, and the colours come from
    `render.SKIN`, the one table both doors read.  When a theme declares the same colour
    for two roles - `alpha` declares white three times - the roles cannot be told apart by
    colour alone; every glyph then takes the ink, which is what the code door does for
    `alpha` too, and the count is reported rather than hidden.  The suite proves the whole
    thing at five inks across all five themes to zero differing pixels.

    Returns `(copy, note)`; `note` is "" when nothing was applied.
    """
    if theme not in render.SKIN:
        return copy.deepcopy(obj), (f"no drawn theme named {theme!r}: a layout's colours "
                                    f"are its own, and only {' '.join(sorted(render.SKIN))}"
                                    f" have a declared skin to move")
    baked = render.SKIN[theme]
    inked = render.skin(theme, ink)
    if inked == baked:
        return copy.deepcopy(obj), ""
    table, ambiguous = {}, []
    for from_c, to_c in zip(baked, inked):
        key, want = rgba_str(from_c), rgba_str(to_c)
        if table.get(key, want) != want:
            ambiguous.append(key)         # two roles, one colour: see the docstring
        table.setdefault(key, want)
    for key in ambiguous:
        table[key] = rgba_str(inked[0])   # the primary, which is what `alpha` paints
    out = copy.deepcopy(obj)
    moved = 0
    for widget in out.get("osd", {}).get("widget") or []:
        for prop in widget.get("property") or []:
            current = prop.get("textColor")
            if current in table and table[current] != current:
                prop["textColor"] = table[current]
                moved += 1
    note = (f"{moved} of {len(out.get('osd', {}).get('widget') or [])} widgets re-inked to "
            f"{render.ink_hex(inked[0])}"
            + (f", all three glyph roles together ({', '.join(ambiguous)})"
               if ambiguous else ""))
    return out, note


def rgba_str(colour: tuple) -> str:
    """A render colour as the `rgba(...)` spelling every vendor widget uses."""
    r, g, b = colour[:3]
    a = colour[3] if len(colour) > 3 else 255
    return f"rgba({r}, {g}, {b}, {a / 255:.4g})"


def widget(wid: str, kind: str, prop: dict, layer: int = 0) -> dict:
    """One widget in the vendor's shape: `property` is a one-element list there, and a
    generated file mirrors that so an editor reads one shape for every row."""
    return {"id": wid, "layerIndex": layer, "type": kind, "property": [prop],
            "widgetContent": ""}


def clock_recipe() -> dict:
    """`clock` as a layout: two readings from the clock, one code-drawn line.

    Determinism, because `tests/test_export_parity.py` compares two runs byte
    for byte: ids are derived from the theme name (`xigma-clock-time`), never
    random; the vendor's `property[].time`
    (its editor's stamp: one epoch per theme, on 82 of the 152 widgets) is **omitted**,
    because a generated file has no editor and a stamp with nothing behind it would be a
    field that lies; and no rendered date or number appears anywhere - only `source`
    names, filled in per frame.

    The three `xigma` keys are each a measured difference between our five and the
    vendor's files, not a convenience: `anchor` (ours centre, the vendor's anchor at the
    em-box top-left), `autoFitMax` (ours walk the size down in steps of 2 to a floor of
    10 until the line fits - the same loop as `render._fit_size`), and `format` (our date
    line is `%A %d %B %Y`; the vendor's `Date` shape in this repo is `%m/%d/%Y`, and
    neither is measured off the vendor's picture, so rewriting our theme to the other one
    would change the glass for no measured reason).
    """
    ext = lambda anchor, maxw, fmt=None: dict({"anchor": anchor, "autoFitMax": maxw},
                                              **({"format": fmt} if fmt else {}))
    return {
        "id": "xigma-clock", "width": render.W, "height": render.H, "ratio": "1:1",
        "xigma": {"theme": "clock", "generated-from": "xigmalcd/render.py",
                  "version": __import__("xigmalcd").__version__},
        "osd": {"widget": [
            widget("xigma-clock-time", "data", {
                "x": 240, "y": 190, "source": "Time", "fontFamily": "dejavu",
                "fontSize": 140, "bold": True, "textColor": rgba_str(render.WHITE),
                "xigma": ext("mm", 440, "%H:%M:%S")}, 0),
            widget("xigma-clock-date", "data", {
                "x": 240, "y": 286, "source": "Date", "fontFamily": "dejavu",
                "fontSize": 22, "bold": True, "textColor": rgba_str(render.DIM),
                "xigma": ext("mm", 440, "%A %d %B %Y")}, 1),
            widget("xigma-clock-readings", "special", {
                "name": "clock-readings", "x": 240, "y": 358, "fontFamily": "dejavu",
                "fontSize": 26, "bold": True, "textColor": rgba_str(render.CYAN),
                "xigma": ext("mm", 440)}, 2),
        ]},
    }


def gauge_recipe() -> dict:
    """`gauge` as a layout: the ring, the reading, the label, the clock.

    The ring is where an export has to say which painter it means, and it is the one place
    in the schema where that is unavoidable.  `render.gauge` rasterises a fill as 3-degree
    arcs, each drawn 0.4 degrees past its end so the joints do not show, colour taken at the
    segment's *start* and mixed by truncation; the vendor's ring, measured off ALPHA's
    captured frames, is 1-degree arcs with the colour at each segment's middle and butt
    ends.  Same geometry, same two colours, different raster:
    `tests/test_conventions.py` paints one arc both ways.  How far apart the
    two rasters land - 164 / 3 366 / 3 889 / 6 989 differing pixels at four
    readings, worst channel delta 255 - is a record of that measurement, not a
    number a check re-quotes.  So the widget says `xigma.arcPaint: "render"`,
    no copied layout says anything, and the default stays the measured vendor
    convention
    (`layout.ARC_PAINT` carries both, and `--check-theme` refuses an unknown name).

    One colour detail worth writing down while it is in front of us: the pair that has a
    measured ramp in `ARC_COLOUR_MEASURED` is ALPHA's *declared* one, (0,247,255) to
    (0,255,113), and what that curve was measured to end at is (0,251,184) - which is
    precisely `render.ALPHA_HOT`.  Our theme took the plateau of the vendor's curve as its
    end colour and then drew a straight line to it.  Both conventions therefore fall back
    to a lerp for this widget, and the pixel difference above is stepping and sampling
    alone, not the profile.

    The geometry comes straight out of what was measured off those frames (docs/limits.md,
    `render.ALPHA_*`): centre (236, 236), stroke centre-line at radius 127, 22 px thick,
    open at the bottom, 260 degrees from 140 deg clockwise in Pillow's angles - which in
    the app's own angles, `arc_angles` says, is 50 to 310.  Pillow's arc stroke lies
    *inside* the bbox ellipse, so the bbox is 254 across, the outer edge at 127 and the
    declared inner `radius` 105.  The scale is the app's own 30..75 C, which is what
    `minValue`/`maxValue` are for.
    """
    ext = lambda anchor, maxw=None: dict({"anchor": anchor},
                                         **({"autoFitMax": maxw} if maxw else {}))
    return {
        "id": "xigma-gauge", "width": render.W, "height": render.H, "ratio": "1:1",
        "xigma": {"theme": "gauge", "generated-from": "xigmalcd/render.py",
                  "version": __import__("xigmalcd").__version__},
        "osd": {"widget": [
            widget("xigma-gauge-ring", "arc", {
                "x": 236 - 127, "y": 236 - 127, "sizeWidth": 254, "sizeHeight": 254,
                "radius": 105, "width": 22, "angleStart": 50, "angleEnd": 310,
                "bgColor": rgba_str(render.ALPHA_TRACK),
                "startColor": rgba_str(render.ALPHA_COLD),
                "endColor": rgba_str(render.ALPHA_HOT),
                "minValue": 30, "maxValue": 75, "source": "CPU Temperature",
                "xigma": {"arcPaint": "render"}}, 0),
            widget("xigma-gauge-title", "text", {
                "x": 240, "y": 19, "content": "Smart Display", "fontFamily": "dejavu",
                "fontSize": 20, "bold": True, "textColor": rgba_str(render.WHITE),
                "xigma": ext("mm", 440)}, 1),
            widget("xigma-gauge-value", "data", {
                "x": 236, "y": 236, "source": "CPU Temperature", "fontFamily": "dejavu",
                "fontSize": 52, "bold": True, "textColor": rgba_str(render.WHITE),
                "xigma": ext("mm", 165)}, 2),
            widget("xigma-gauge-label", "text", {
                "x": 236, "y": 318, "content": "CPU TEMP", "fontFamily": "dejavu",
                "fontSize": 14, "bold": True, "textColor": rgba_str(render.ALPHA_LABEL),
                "xigma": ext("mm")}, 3),
            widget("xigma-gauge-clock", "data", {
                "x": 236, "y": 458, "source": "Time", "fontFamily": "dejavu",
                "fontSize": 22, "bold": True, "textColor": rgba_str(render.ALPHA_MINT),
                "xigma": ext("mm")}, 4),
        ]},
    }


def dual_recipe() -> dict:
    """`dual` as a layout: two rings, two readings, two labels, a bar, one line, a clock.

    Both rings carry `xigma.colourRamp: "heat"` and `xigma.arcPaint: "render"`, and the bar
    carries `xigma.barPaint: "render"` with the same named ramp sampled at the value's
    fraction.  Those keys exist because the two painters disagree in pixels, not in intent:
    a bar 360 px wide at 63.5 % spans 457 device px under `render.bar` and 456 under the
    vendor's rounding, and `heat` as data stops is off by one unit at 8 of 100 sampled
    positions (docs/limits.md).  With the keys named, the ring and the bar each reproduce
    their code counterpart at a zero pixel diff on their own, before the whole theme is
    assembled.

    The middle line is a `special` because it is a composite of three readings
    (`cpu.load`, `memory.used`, `memory.total`) in one string with four spaces inside it -
    no vendor `source` stands for that, so the layout places the line and
    `render.dual_status_line` builds it.  One builder, two doors.

    Geometry comes out of `theme_dual`: rings at (128, 228) and (352, 228), bbox semi-axis
    96, stroke 20, 300 degrees from 120 in Pillow's angles (30 to 330 in the app's), scale
    30..90 C; bar at (60, 340) 360x14; title at (240, 26), digits at 222, labels at 298,
    line at 372, clock at 444.
    """
    ext = lambda anchor, maxw=None, **kw: dict(
        {"anchor": anchor}, **({"autoFitMax": maxw} if maxw else {}), **kw)
    rings, readouts = [], []
    for cid, cx, dev, label in (("cpu", 128, "CPU Temperature", "CPU TEMP"),
                                ("gpu", 352, "GPU Temperature", "GPU TEMP")):
        rings.append(widget(f"xigma-dual-{cid}-ring", "arc", {
            "x": cx - 96, "y": 228 - 96, "sizeWidth": 192, "sizeHeight": 192,
            "radius": 76, "width": 20, "angleStart": 30, "angleEnd": 330,
            "bgColor": rgba_str(render.ARC_TRACK),
            "startColor": rgba_str(render.CYAN), "endColor": rgba_str(render.RED),
            "minValue": 30, "maxValue": 90, "source": dev,
            "xigma": {"arcPaint": "render", "colourRamp": "heat"}}, 0))
        readouts.append(widget(f"xigma-dual-{cid}-value", "data", {
            "x": cx, "y": 222, "source": dev, "fontFamily": "dejavu", "fontSize": 52,
            "bold": True, "textColor": rgba_str(render.WHITE),
            "xigma": ext("mm", 120, format=".0f")}, 1))
        readouts.append(widget(f"xigma-dual-{cid}-label", "text", {
            "x": cx, "y": 298, "content": label, "fontFamily": "dejavu",
            "fontSize": 15, "bold": True, "textColor": rgba_str(render.DIM),
            "xigma": ext("mm")}, 1))
    return {
        "id": "xigma-dual", "width": render.W, "height": render.H, "ratio": "1:1",
        "xigma": {"theme": "dual", "generated-from": "xigmalcd/render.py",
                  "version": __import__("xigmalcd").__version__},
        "osd": {"widget": [
            rings[0], readouts[0], readouts[1], rings[1], readouts[2], readouts[3],
            widget("xigma-dual-title", "text", {
                "x": 240, "y": 26, "content": "CPU  /  GPU", "fontFamily": "dejavu",
                "fontSize": 24, "bold": True, "textColor": rgba_str(render.WHITE),
                "xigma": ext("mm", 440)}, 2),
            widget("xigma-dual-bar", "bar", {
                "x": 60, "y": 340, "width": 360, "height": 14, "cornerRadius": 0,
                "bgColor": rgba_str((40, 46, 50, 255)),
                "startColor": rgba_str(render.CYAN), "endColor": rgba_str(render.RED),
                "minValue": 0, "maxValue": 100, "source": "CPU Usage",
                "xigma": {"barPaint": "render", "colourRamp": "heat"}}, 3),
            widget("xigma-dual-status", "special", {
                "name": "dual-status", "x": 240, "y": 372, "fontFamily": "dejavu",
                "fontSize": 17, "bold": True, "textColor": rgba_str(render.DIM),
                "xigma": ext("mm")}, 4),
            widget("xigma-dual-clock", "data", {
                "x": 240, "y": 444, "source": "Time", "fontFamily": "dejavu",
                "fontSize": 30, "bold": True, "textColor": rgba_str(render.CYAN),
                "xigma": ext("mm")}, 5),
        ]},
    }


def alpha_recipe() -> dict:
    """`alpha` as a layout: two rings, three pairs of lettering, two bars, four labels, a clock.

    The fourth export, and the one that had to earn its keys. Everything here was measured
    as a separate row before it was assembled - the ring against `render.temp_arc` at
    `xigma.arcPaint: render` (docs/limits.md: 164 to 6 989 px away under the vendor's
    rasterisation), the bars against `render.hbar` at `xigma.barPaint: hbar` (28 device-px
    pairs and 7 at 1x, zero differing pixels), and the three pairs of lettering against
    `theme_alpha`'s own rows as `special`s (`fan-figures` 30 reading pairs, `temp-values` and
    `temp-labels` 36, their ink measured clear of the rings' stroke and, in both rows
    together, covering the rings' hole exactly). The geometry below is `render.A26_*` read
    out of the module that draws it, never retyped: the ring's bbox is `A26_RING_R` about
    `A26_RING_Y`, its declared `radius` is the inner edge (`A26_RING_R - A26_RING_W`), and
    the angles are the app's own - `layout.arc_angles` measures the +90 rule that turns
    `A26_ARC_START` into them.

    The ramp is data, and it is exact *because* it is the three-stop one. `temp_arc` colours
    its fill through `render.temp_colour`, green at `A26_ARC_LO`, amber at `A26_ARC_MID`, red
    at `A26_ARC_HI`; the stop fractions come out of those same three constants, which is the
    spelling `tests/test_gauges.py` checks against `temp_colour` at all 100
    sampled segment positions (docs/limits.md - `render.heat`, by contrast, is
    off by one unit at 8 of its own stop
    positions, which is why `dual` names its ramp instead of copying it).

    Two rows are `text`/`data` rather than `special` because nothing is joint about them:
    "CPU USED" and "GPU USED" are drawn at their own size each, and the percentage beside
    them is one reading in `VENDOR_FORMAT`'s spelling (`_pct`, the same function the theme
    calls). The clock line is a `data` row with `xigma.format: "%H:%M:%S"` and
    `autoFitMax: 452` because `theme_alpha` fits it to that width with `_fit`, and its
    anchor is `ms` - sitting on y as its baseline - which is neither the vendor's `la` nor
    the centred `mm` the other four exports mostly use.
    """
    pitch = render.A26_TCOL_X[1] - render.A26_TCOL_X[0]
    mid = ((render.A26_ARC_MID - render.A26_ARC_LO)
           / (render.A26_ARC_HI - render.A26_ARC_LO))
    ramp = [[0.0, rgba_str(render.GREEN)], [mid, rgba_str(render.AMBER)],
            [1.0, rgba_str(render.RED)]]
    fit_arc = {"cy": render.A26_RING_Y, "radius": render.A26_RING_R - render.A26_RING_W,
               "width": render.A26_RING_W, "angleStart": render.A26_ARC_START - 90,
               "angleEnd": render.A26_ARC_START + render.A26_ARC_SWEEP - 90}
    rows = []
    for cid, cx, dev in (("cpu", render.A26_TCOL_X[0], "CPU Temperature"),
                         ("gpu", render.A26_TCOL_X[1], "GPU Temperature")):
        rows.append(widget(f"xigma-alpha-{cid}-ring", "arc", {
            "x": cx - render.A26_RING_R, "y": render.A26_RING_Y - render.A26_RING_R,
            "sizeWidth": 2 * render.A26_RING_R, "sizeHeight": 2 * render.A26_RING_R,
            "radius": render.A26_RING_R - render.A26_RING_W,
            "width": render.A26_RING_W,
            "angleStart": render.A26_ARC_START - 90,
            "angleEnd": render.A26_ARC_START + render.A26_ARC_SWEEP - 90,
            "bgColor": rgba_str(render.A26_ARC_TRACK),
            "startColor": rgba_str(render.GREEN), "endColor": rgba_str(render.RED),
            "minValue": render.A26_ARC_LO, "maxValue": render.A26_ARC_HI,
            "source": dev,
            "xigma": {"arcPaint": "render", "colourStops": ramp}}, len(rows)))
    rows.append(widget("xigma-alpha-temp-labels", "special", {
        "name": "temp-labels", "x": (render.A26_TCOL_X[0] + render.A26_TCOL_X[1]) // 2,
        "y": render.A26_TLBL_Y, "width": pitch, "fontFamily": "dejavu",
        "fontSize": render.A26_TLBL_F, "bold": True,
        "textColor": rgba_str(render.A26_WHITE),
        "xigma": {"anchor": "ma", "fitArc": fit_arc}}, len(rows)))
    rows.append(widget("xigma-alpha-temp-values", "special", {
        "name": "temp-values", "x": (render.A26_TCOL_X[0] + render.A26_TCOL_X[1]) // 2,
        "y": render.A26_TVAL_Y, "width": pitch, "fontFamily": "dejavu",
        "fontSize": render.A26_TVAL_F, "bold": True,
        "textColor": rgba_str(render.A26_WHITE),
        "xigma": {"anchor": "ma", "fitArc": fit_arc}}, len(rows)))
    rows.append(widget("xigma-alpha-fan-figures", "special", {
        "name": "fan-figures", "x": (render.A26_FAN_X[0] + render.A26_FAN_X[1]) // 2,
        "y": render.A26_FAN_Y, "width": render.A26_FAN_X[1] - render.A26_FAN_X[0],
        "fontFamily": "dejavu", "fontSize": render.A26_FAN_F, "bold": False,
        "textColor": rgba_str(render.A26_WHITE),
        "xigma": {"anchor": "ma", "autoFitMax": render.A26_FAN_MAX_W}}, len(rows)))
    for (cid, (bx, by), lx, ly, px_, py_, dev) in (
            ("cpu", render.A26_BAR_XY[0], 100, 300, 320, 290, "CPU Usage"),
            ("gpu", render.A26_BAR_XY[1], 100, 370, 322, 362, "GPU Usage")):
        rows.append(widget(f"xigma-alpha-{cid}-cap", "text", {
            "x": lx, "y": ly, "content": f"{cid.upper()} USED", "fontFamily": "dejavu",
            "fontSize": 20, "bold": False, "textColor": rgba_str(render.A26_WHITE),
            "xigma": {"anchor": "la"}}, len(rows)))
        rows.append(widget(f"xigma-alpha-{cid}-pct", "data", {
            "x": px_, "y": py_, "source": dev, "fontFamily": "dejavu", "fontSize": 32,
            "bold": False, "textColor": rgba_str(render.A26_WHITE),
            "xigma": {"anchor": "la"}}, len(rows)))
        rows.append(widget(f"xigma-alpha-{cid}-bar", "bar", {
            "x": bx, "y": by, "width": render.A26_BAR_WH[0],
            "height": render.A26_BAR_WH[1], "cornerRadius": 0,
            "bgColor": rgba_str(render.A26_TRACK), "startColor": rgba_str(render.A26_BAR_A),
            "endColor": rgba_str(render.A26_BAR_B), "minValue": 0, "maxValue": 100,
            "source": dev, "xigma": {"barPaint": "hbar"}}, len(rows)))
    rows.append(widget("xigma-alpha-clock", "data", {
        "x": 240, "y": 470, "source": "Time", "fontFamily": "dejavu", "fontSize": 26,
        "bold": False, "textColor": rgba_str(render.A26_WHITE),
        "xigma": {"anchor": "ms", "autoFitMax": 452, "format": "%H:%M:%S"}}, len(rows)))
    return {
        "id": "xigma-alpha", "width": render.W, "height": render.H, "ratio": "1:1",
        "xigma": {"theme": "alpha", "generated-from": "xigmalcd/render.py",
                  "version": __import__("xigmalcd").__version__},
        "osd": {"widget": rows},
    }


def bars_recipe() -> dict:
    """`bars` as a layout: ten rows of label, number and meter, a heading, a clock line.

    The last of the five, and the one whose obstacle was not the schema but the drawing:
    `theme_bars` reserves four fan slots and lets a row with no reading keep its place
    (2026-11-08, docs/limits.md), so the block carries the same ten rows - and therefore the
    same pitch, `BARS_SPAN // (6 + 4)` - on every machine, and a file can say where each row
    goes.  The rows come from `BARS_ROWS` and the geometry from `render.BARS_*`: no number
    here is a retyped copy of one the drawing already names.

    Three things the vendor's `bar` widget cannot say, which this file says anyway:

    * **One row, two readings.** The two memory rows divide a *percentage* for the meter and
      print *gigabytes* beside it (`RAM Rate` and `Used RAM`, `GPU Memory Rate` and `Used GPU
      Memory`), because that is what the theme draws, and a meter and a number describing one
      sensor at two scales is not a shape the shipped vocabulary has.
    * **A label that is a reading.** The four fan rows print `Fan N Name` - whatever this box
      calls that tachometer, cut to the same 10 characters the drawing cuts.  The vendor's
      editor offers the aggregates `cpuFansSpeed` "CPU Fans Speed" and `gpuFansSpeed` "GPU
      Fans Speed", never a row per sensor (PROTOCOL.md 10), so it never needed a name for one.
    * **A dependency a row can state.** The two memory number rows carry `xigma.showIf`
      naming the meter's source: their own field answers even where the meter's division
      cannot be made - a GPU reporting `memoryUsage` with no `dedicatedTotal`, which an
      integrated GPU does - and the theme draws neither number nor meter then.  Measured,
      before the key existed, at that one reading: 706 px and a worst channel of 255.
    * **A ramp named, not copied.** The meter's colour is `heat(frac)`, so the row names
      `xigma.colourRamp: "heat"` and declares the ramp's two ends; spelling that curve as
      stops differs by one unit at 8 of its 100 sampled positions, which docs/limits.md
      records and `dual` and `gauge` sidestep the same way.

    The heading carries `xigma.autoFitMax` because `theme_bars` fits it through `_fit` - the
    drawing's own width and ceiling, not a fitted guess - and it and the clock sit on the
    anchor `mm` that `_text` draws with.  `cornerRadius` on the meters is declared 0 and is
    ignored in both directions by `barPaint: render`: that painter rounds the track to half
    the height and the fill as a function of the reading, and naming the convention is what
    makes the declared number's silence mean something rather than disagree.
    """
    row_h = min(render.BARS_ROW_MAX,
                max(render.BARS_ROW_MIN,
                    render.BARS_SPAN // (len(BARS_FIXED_ROWS) + len(FAN_SLOTS))))
    track = rgba_str((40, 46, 50, 255))            # `render.bar`'s own default track
    rows = [widget("xigma-bars-heading", "text", {
        "x": render.BARS_TITLE_X, "y": render.BARS_TITLE_Y,
        "content": render.BARS_TITLE_TEXT, "fontFamily": "dejavu",
        "fontSize": render.BARS_TITLE_F, "bold": True,
        "textColor": rgba_str(render.WHITE),
        "xigma": {"anchor": "mm", "autoFitMax": render.BARS_TITLE_W}}, 0)]
    for i, (label, bar_src, text_src, lo, hi) in enumerate(BARS_ROWS):
        y = render.BARS_Y0 + i * row_h
        slug = bar_src.lower().replace(" ", "-")
        if label is None:
            rows.append(widget(f"xigma-bars-{slug}-name", "data", {
                "x": render.BARS_LBL_X, "y": y, "source": _FAN_NAME[bar_src],
                "fontFamily": "dejavu", "fontSize": render.BARS_LBL_F, "bold": True,
                "textColor": rgba_str(render.DIM), "xigma": {"anchor": "lm"}}, len(rows)))
        else:
            rows.append(widget(f"xigma-bars-{slug}-label", "text", {
                "x": render.BARS_LBL_X, "y": y, "content": label, "fontFamily": "dejavu",
                "fontSize": render.BARS_LBL_F, "bold": True,
                "textColor": rgba_str(render.DIM), "xigma": {"anchor": "lm"}}, len(rows)))
        number = {"anchor": "rm"}
        if text_src != bar_src:
            # the memory rows: the number prints one field, the meter divides two, and the
            # drawing behind this file prints neither when the division cannot be made (a
            # GPU with no dedicated total answers `4096` and nothing else).  Named rather
            # than assumed, and `tests/test_bars_rows.py` measures the case
            number["showIf"] = bar_src
        rows.append(widget(f"xigma-bars-{text_src.lower().replace(' ', '-')}-value",
                           "data", {
            "x": render.BARS_VAL_X, "y": y, "source": text_src, "fontFamily": "dejavu",
            "fontSize": render.BARS_VAL_F, "bold": True,
            "textColor": rgba_str(render.WHITE), "xigma": number}, len(rows)))
        rows.append(widget(f"xigma-bars-{slug}-meter", "bar", {
            "x": render.BARS_BAR_X, "y": y + render.BARS_BAR_DY,
            "width": render.BARS_BAR_WH[0], "height": render.BARS_BAR_WH[1],
            "cornerRadius": 0, "bgColor": track, "startColor": rgba_str(render.CYAN),
            "endColor": rgba_str(render.RED), "minValue": lo, "maxValue": hi,
            "source": bar_src,
            "xigma": {"barPaint": "render", "colourRamp": "heat"}}, len(rows)))
    rows.append(widget("xigma-bars-clock", "data", {
        "x": render.BARS_CLOCK_XY[0], "y": render.BARS_CLOCK_XY[1], "source": "Time",
        "fontFamily": "dejavu", "fontSize": render.BARS_CLOCK_F, "bold": True,
        "textColor": rgba_str(render.CYAN),
        "xigma": {"anchor": render.BARS_CLOCK_ANCHOR}}, len(rows)))
    return {
        "id": "xigma-bars", "width": render.W, "height": render.H, "ratio": "1:1",
        "xigma": {"theme": "bars", "generated-from": "xigmalcd/render.py",
                  "version": __import__("xigmalcd").__version__},
        "osd": {"widget": rows},
    }


EXPORTS = {"alpha": alpha_recipe, "bars": bars_recipe, "clock": clock_recipe,
           "dual": dual_recipe, "gauge": gauge_recipe}


def export(name: str) -> dict:
    """Generate the layout for one of the five, on demand. Not written to disk here."""
    try:
        return EXPORTS[name]()
    except KeyError:
        raise KeyError(f"no export for theme {name!r} yet; exported so far: "
                       f"{' '.join(sorted(EXPORTS)) or 'none'}")


def parity(name: str, metrics: dict, when=None) -> dict:
    """Code-drawn vs layout-drawn, in pixels: the check that makes an export
    mean something.

    Both doors get the same metrics and the same instant.  Returned numbers: painted
    pixels each way, the count of pixels where they disagree, and the notes from
    `draw_theme` (which is where a missing face or a missing reading would show up).
    """
    from PIL import ImageChops
    # both doors have to be shown the same instant, and `_now` is the one hook this repo
    # has for that (render.clock_str, date_str and the fan figures all read it).  Without
    # it the code door would print the live second against a layout filled from `when`,
    # and the difference would be a clock, not a drawing.
    real_now = render._now
    if when is not None:
        render._now = lambda: when.timetuple()
    try:
        code = render.draw(metrics, name)
    finally:
        render._now = real_now
    obj = export(name)
    vals, absent = values(metrics, when)
    fill_lines(vals, metrics)
    lay, notes = layout.draw_theme(obj, vals, canvas=(obj["width"], obj["height"]),
                                   specials=SPECIALS)
    a, b = code.convert("RGBA"), lay.convert("RGBA")
    delta = ImageChops.difference(a, b)
    flat = delta.get_flattened_data()
    diff = sum(1 for px in flat if px != (0, 0, 0, 0))
    worst = max((max(px) for px in flat), default=0)
    paint = lambda im: sum(1 for v in im.getchannel("A").get_flattened_data() if v)
    return {"name": name, "code_px": paint(a), "layout_px": paint(b), "diff_px": diff,
            "worst_channel_delta": worst, "boxes": len(notes["boxes"]),
            "missing": notes["missing"], "gaps": sorted(set(notes["gaps"])),
            "absent": sorted(absent)}


def census(limit: int = 0) -> list:
    """The printed lines for `--list-themes`: pickable, then refused, each with its why."""
    ok, out = scan()
    lines = [describe(r) for r in (ok[:limit] if limit else ok)]
    lines += ["  " + f"{r['name']:<12} {r['id']}  {r['w']}x{r['h']} ratio {r['ratio']}"
              f"  NOT PICKABLE: {why_not(r['name'])}" for r in out]
    return lines
