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
RATIO_WHY = ('ratio {ratio}: {w}x{h}, and the em-box anchor convention this program '
             'draws text by was measured at 480 only - docs/theme-editor.md keeps that '
             'plan and its cost')


def scan() -> tuple:
    """(selectable, excluded) records for every layout file in `roots()`.

    A record is {name, id, ratio, w, h, path, root, widgets, background}.  First-winning
    root by name, exactly like the clip library, so a checkout and an installed package
    never both answer for one name.
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


def paint(record: dict, metrics: dict, when=None, scrim: int = 0, base=None) -> tuple:
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
                                   canvas=(record["w"], record["h"]),
                                   specials=SPECIALS)
    # `draw_theme` says which widgets it skipped; this says why, in the words this module
    # chose when it refused to invent a reading.  Both belong in the notes.
    notes["absent"] = absent
    if scrim:
        img = render.scrim(img, max(1, min(255, int(scrim))))
    if base is not None and base[3] == 255:
        # `--bg black` means the same thing for a layout as for our own themes: the frame
        # is opaque, so it covers the panel's stored background instead of letting it
        # show through. Transparent is the vendor's shape and the default here.
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

    Same doors as `paint` - same source table, one instant, the specials registry - so
    what an editor shows and what the loop uploads cannot be two different pictures.
    """
    vals, absent = values(metrics, when)
    vals["readings"] = render.clock_readings_line(metrics)
    img, notes = layout.draw_theme(obj, vals,
                                   canvas=(obj.get("width") or render.W,
                                           obj.get("height") or render.H),
                                   specials=SPECIALS)
    if scrim:
        img = render.scrim(img, max(1, min(255, int(scrim))))
    notes["absent"] = absent
    return img, notes


def describe(record: dict) -> str:
    """One line: what `--theme <name>` will draw, and where the file came from."""
    return (f"  {record['name']:<12} {record['id']}  {record['w']}x{record['h']} "
            f"ratio {record['ratio']}  {record['widgets']} widgets  "
            f"background {os.path.basename(record['background'])}  from {origin(record)}")


# ------------------------------------------------------- canonical file shape --
#: Every one of the 27 copied layouts is, byte for byte, `canonical()` of its own parsed
#: content - one indentation, sorted keys, no trailing whitespace - checked on all 27 by
#: the suite.  The only thing the vendor's own files disagree with each other about is
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
    raw = open(path, encoding="utf-8").read()
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
        if src and src not in SOURCES and src not in CLOCKED and src not in UNMAPPED:
            soft.append(f"widget {i} ({kind}): source {src!r} has no entry in "
                        "themes.SOURCES - it will be reported as unanswered")
        if kind == "special" and str(pr.get("name") or "") not in SPECIALS:
            soft.append(f"widget {i}: special name {pr.get('name')!r} has no drawing "
                        f"(--list-specials prints {' '.join(special_names())})")
        if kind in ("text",) and pr.get("content") is None:
            soft.append(f"widget {i} (text): no `content` string to draw")
    return hard, soft


# ------------------------------------------------------------- the file model --
def user_theme_path(name: str) -> str:
    """Where an edited or new theme of yours would live."""
    return os.path.join(user_root(), f"{name}.json")


def _safe_name(name: str) -> str:
    """A theme name that cannot escape the user directory, and cannot shadow one of the
    five names this program draws from code (those are generated, never stored: a saved
    `gauge.json` would be a second source of truth for `theme_gauge`, which is the failure
    mode docs/theme-editor.md's whole export design exists to avoid)."""
    n = str(name or "").strip()
    if not n or n != os.path.basename(n) or "/" in n or "\\" in n or n.startswith("."):
        raise ValueError(f"unsafe theme name {name!r}: a name is one path element, no "
                         "separators, no leading dot")
    if len(n) > 64:
        raise ValueError(f"theme name {name!r} is longer than 64 characters")
    if n in render.THEMES:
        raise ValueError(f"{n!r} is one of the five themes drawn from render.py; those are "
                         "generated by --export-theme rather than saved, so the two cannot "
                         "drift apart")
    return n


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


# ------------------------------------------------------- the specials registry --
#: {name: callable(draw, prop, values) -> ink box}.  A special is a picture that stays
#: code-drawn and takes its position, size, colour and reading from the layout - the
#: decision that keeps the fan figures, the tick strip and the clock's readings line
#: movable without baking PNGs (docs/theme-editor.md).  Injected into
#: `layout.draw_theme` from here, because the drawings live in `render.py` and layout
#: already imports render, not the other way round.
def _sp_clock_readings(draw, prop, values):
    """The clock theme's third line: built by `render.clock_readings_line`, placed here."""
    line = str(values.get("readings") or "")
    if not line:
        return None
    return layout.draw_special_line(draw, prop, line)


SPECIALS = {"clock-readings": _sp_clock_readings}


def special_names() -> tuple:
    """Every name a `special` widget may carry. `--list-specials` prints this."""
    return tuple(sorted(SPECIALS))


# ------------------------------------------------------------------ exports --
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

    Determinism, because the gate compares two runs byte for byte: ids are derived from
    the theme name (`xigma-clock-time`), never random; the vendor's `property[].time`
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


EXPORTS = {"clock": clock_recipe}


def export(name: str) -> dict:
    """Generate the layout for one of the five, on demand. Not written to disk here."""
    try:
        return EXPORTS[name]()
    except KeyError:
        raise KeyError(f"no export for theme {name!r} yet; exported so far: "
                       f"{' '.join(sorted(EXPORTS)) or 'none'}")


def parity(name: str, metrics: dict, when=None) -> dict:
    """Code-drawn vs layout-drawn, in pixels: the gate that makes an export mean something.

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
    vals["readings"] = render.clock_readings_line(metrics)
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
