#!/usr/bin/env python3
"""knobmap.py - which of a drawn theme's options a **layout file** can answer.

The question the theme-editor plan keeps running into: all five of this repo's own themes
also exist as generated layout files (`themes.export`, printed by `--export-theme NAME`), so
what breaks if the file becomes the thing that gets drawn - the door `--theme`, the control
socket and the window all walk through?  That is a measurement, not an opinion, and it is
per option:

For every theme in `render.THEMES`, read the options its own body accepts (its signature,
taken with `inspect` - never a table of them kept by hand), pick one representative value
for each, find the best change to that theme's **generated layout** that answers the same
value, and count the pixels between the two doors.  One reading dict, one clock instant, no
port: `render._now` is pinned, because a code drawing reads the wall clock while
`themes.draw` is handed a time - and an unpinned clock makes a 15 000 px difference out of
the time of day.

A pair at **0 px** (worst channel 0) means the file door can carry that option and the frame
reaching the panel does not change.  A pair above 0 px means routing that theme through a
file would change the picture on the glass, and the figure is the size of the change.  Both
directions of "worse" and "stronger" happen: `--bg black` comes out *more* opaque through
the file door - a plate composited under the finished layer seals every pixel at alpha 255,
while a `theme_*` body's own translucent fills stay translucent against its canvas
(docs/usage.md's `--bg` row) - and an option a body ignores is worse than either, because
both doors then draw the default frame while the reader asked for something else.

Machine dependence, stated: the non-zero figures sit on glyph edges and inside shapes whose
size walks a font's metrics, so they move with the installed faces.  What does not move is
which pairs are exactly 0, and that a non-exact pair is *far* from 0 rather than near it -
the last line of the summary prints the smallest non-zero gap, and
`tests/test_knobmap.py` holds that line and the resulting split.  Nothing here is a claim about the wire beyond the frame's
own pixels: no port is opened, nothing is uploaded.

The knobs are read as what they are, not as flags someone remembers:

* `cli_route` takes each option's route out of `main._theme_kwargs` with `ast`, so a
  parameter nobody on the command line can set (`big`, `gradient`) is reported as such -
  that is how `theme_clock(big=140)` was misread as a flag once already.
* `body_choices` takes the values a body actually compares an option against, so `gradient`
  is asked with `heat` (its other branch) and not with an invented string that would take
  the default's branch and turn a no-op into a pass.
* a parameter in a signature that the body never reads is left out of the rows and said out
  loud, because counting it as 'answered by the file door' would be a lie: both doors draw
  the default frame.  `theme_clock(clock=True, ...)` was exactly that until 0.4, and
  `--no-clock` moved that theme 0 px; the body honours the option now, and the map's
  row for it is exact against the generated layout's deleted `Time` row.

Usage::

    tools/knobmap.py                   # the table, then the split
    tools/knobmap.py --json rows.json  # the same rows, machine-readable
    tools/knobmap.py --theme gauge     # one theme's rows
"""
from __future__ import annotations

import argparse
import ast
import datetime
import inspect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageChops                          # noqa: E402

from xigmalcd import render, themes                        # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: One reading dict.  Its shape is a machine's - the same 15 of the 19 sources the five
#: generated layouts ask that a box with two reported tachometers answers, leaving the
#: `Fan 3`/`Fan 4` slots empty in both doors - and it is pinned here so the split below is
#: reproducible rather than a snapshot of whatever this box was doing.
PIN = {"cpu": {"temperature": 57.0, "load": 62.0, "usage": 62.0, "speedAverage": 3400,
               "power": 18.0},
       "gpu": {"temperature": 47.0, "load": 22.0, "speed": 1200, "fan": 45.0,
               "power": 90.0, "memoryUsage": 2458, "dedicatedTotal": 8192},
       "memory": {"load": 41.0, "used": 53740, "total": 131072},
       "motherboard": {"temperature": 44.0},
       "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 1180},
                {"onBoard": True, "type": "Chassis", "name": "Fan System 5",
                 "value": 890}],
       "timestamp": {}}
WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)

#: the size asked for on both doors.  The socket's own bounds for `clock_size` are 8..120
#: and its documented example is 40, so 40 is the number; `big` is a size too, with no flag
#: and no bounds, and the row says which is which.
SIZE = 40
INK, COLD, HOT, LABEL, TITLE, GAUGE_SOURCE = "amber", 20, 100, "BOARD", "Xigmatek", "load"


def gap_px(a, b):
    """(pixels that disagree in any channel, worst single-channel delta)."""
    flat = ImageChops.difference(a.convert("RGBA"), b.convert("RGBA")).get_flattened_data()
    return (sum(1 for q in flat if q != (0, 0, 0, 0)), max((max(q) for q in flat), default=0))


def lit(im):
    return sum(1 for v in im.getchannel("A").get_flattened_data() if v)


def edited(base, edits, drops=()):
    """A copy of the generated layout with row-level edits, and rows deleted by index."""
    out = []
    for i, w in enumerate(base["osd"]["widget"]):
        if i in drops:
            continue
        pr = dict(w["property"][0])
        pr.update(edits.get(i, {}))
        out.append({"type": w["type"], "property": [pr]})
    o = json.loads(json.dumps(base))
    o["osd"]["widget"] = out
    return o


def rows_of(base, pred):
    return [i for i, w in enumerate(base["osd"]["widget"]) if pred(w)]


def src(w):
    return (w["property"][0] or {}).get("source")


def content(w):
    return (w["property"][0] or {}).get("content")


def best_content_edit(base, code, value):
    """The text row whose `content` answers `code` best, and how far off that still was."""
    best = None
    for i in rows_of(base, lambda w: w["type"] == "text"):
        g = gap_px(code, themes.draw(edited(base, {i: {"content": value}}), PIN, WHEN)[0])
        if best is None or g[0] < best[0][0]:
            best = (g, content(base["osd"]["widget"][i]))
    return best


def body_choices(fn, knob, default):
    """What a body compares `knob` against, how many times it reads it, and a good value.

    `uses == 0` means the option is in the signature and nowhere in the body: a knob nobody
    implements.  (`ast.arg.arg` is a string, not a `Name`, so the `def` line never counts as
    a use - `bg`, which a body reads exactly once, is a use.)
    """
    tree = ast.parse(inspect.getsource(fn))
    lits, uses = set(), 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == knob:
            uses += 1
        if isinstance(node, ast.Compare):
            parts = [node.left] + node.comparators
            if any(isinstance(p, ast.Name) and p.id == knob for p in parts):
                lits |= {p.value for p in parts
                         if isinstance(p, ast.Constant) and isinstance(p.value, str)}
    others = sorted(l for l in lits if l != default)
    value = others[0] if others else default
    if isinstance(default, bool):
        value = not default
    elif isinstance(default, (int, float)) and not isinstance(default, bool):
        value = SIZE
    return value, sorted(lits), uses


_ROUTES: dict = {}


def cli_route(knob):
    """How the loop itself fills this option, read out of `main._theme_kwargs` with `ast`.

    An option in a signature is not automatically something a reader can ask for.  This is
    the difference between `--clock-size 40`, `not args.no_clock`, and a parameter only
    Python can pass - and it is printed in every row, so the map cannot be mistaken for a
    list of flags.
    """
    if not _ROUTES:
        tree = ast.parse(open(os.path.join(REPO, "xigmalcd", "main.py"),
                              encoding="utf-8").read())
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_theme_kwargs")
        for node in ast.walk(fn):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant):
                        _ROUTES.setdefault(str(k.value), ast.unparse(v))
    return _ROUTES.get(knob, "")


def measure(name):
    """One theme's rows, the knobs its signature offers, and the ones its body ignores."""
    base = themes.export(name)
    body = render.THEMES[name]
    sig = inspect.signature(body)
    knobs = [k for k in sig.parameters if k not in ("m", "metrics")]
    out, unread = [], []
    for knob in sorted(knobs):
        default = sig.parameters[knob].default
        value, lits, uses = body_choices(body, knob, default)
        route = cli_route(knob)

        def row(knob_, val, edit, gap, worst):
            out.append({"knob": knob_, "value": val, "edit": edit, "diff_px": gap,
                        "worst_channel": worst, "exact": gap == 0 and worst == 0,
                        "route": route or "(no CLI or socket route: Python only)",
                        "asked_by_body": uses})

        if uses == 0:
            unread.append((knob, default, route))
            continue

        if knob == "ink":
            obj, _ = themes.with_ink(base, name, INK)
            row(knob, INK, "the `textColor` roles `render.SKIN` declares (themes.with_ink)",
                *gap_px(render.draw(PIN, name, ink=INK), themes.draw(obj, PIN, WHEN)[0]))
        elif knob in ("clock", "date"):
            want = "Time" if knob == "clock" else "Date"
            kw = {k: True for k in ("clock", "date") if k in sig.parameters}
            code = render.draw(PIN, name, **dict(kw, **{knob: False}))
            drops = rows_of(base, lambda w: src(w) == want)
            row(knob, False, f"delete the {len(drops)} row(s) whose `source` is `{want}`",
                *gap_px(code, themes.draw(edited(base, {}, set(drops)), PIN, WHEN)[0]))
        elif knob == "fan":
            code = render.draw(PIN, name, fan=False)
            drops = set(rows_of(base, lambda w: (w["property"][0] or {}).get("name")
                                in ("fan-figures", "dual-status")
                                or "FAN" in str(content(w) or "")))
            row(knob, False, f"delete the {len(drops)} row(s) carrying the fan figures",
                *gap_px(code, themes.draw(edited(base, {}, drops), PIN, WHEN)[0]))
        elif knob in ("clock_size", "big"):
            code = render.draw(PIN, name, **{knob: SIZE})
            idx = rows_of(base, lambda w: src(w) == "Time")
            row(knob, SIZE,
                f"`fontSize` {SIZE} on the {len(idx)} Time row(s) "
                f"(default there is {sig.parameters[knob].default})",
                *gap_px(code, themes.draw(edited(base, {i: {"fontSize": SIZE}
                                                       for i in idx}), PIN, WHEN)[0]))
        elif knob in ("cold", "hot"):
            code = render.draw(PIN, name, cold=COLD, hot=HOT)
            idx = rows_of(base, lambda w: str(src(w) or "").endswith("Temperature"))
            row(knob, f"{COLD}/{HOT}",
                f"`minValue`/`maxValue` on the {len(idx)} temperature row(s)",
                *gap_px(code, themes.draw(edited(base, {i: {"minValue": COLD,
                                                            "maxValue": HOT}
                                                          for i in idx}), PIN, WHEN)[0]))
        elif knob == "label":
            code = render.draw(PIN, name, label=LABEL)
            (gap, worst), old = best_content_edit(base, code, LABEL)
            row(knob, LABEL, f"text row {old!r} -> {LABEL!r}", gap, worst)
        elif knob == "title":
            for ask in (False, TITLE):
                code = render.draw(PIN, name, title=ask)
                want = "" if ask is False else TITLE
                (gap, worst), old = best_content_edit(base, code, want)
                row(knob, ask, f"text row {old!r} -> {want!r}" if ask is not False
                    else f"blank text row {old!r}", gap, worst)
        elif knob == "source":
            code = render.draw(PIN, name, source=GAUGE_SOURCE)
            temps = rows_of(base, lambda w: str(src(w) or "").endswith("Temperature"))
            labels = rows_of(base, lambda w: w["type"] == "text"
                             and "TEMP" in str(content(w) or ""))
            edits = {i: {"source": "CPU Usage", "minValue": 0, "maxValue": 100}
                     for i in temps}
            for i in labels:
                edits[i] = dict(edits.get(i, {}), content="CPU LOAD")
            row(knob, GAUGE_SOURCE,
                "repoint `source`, its `minValue`/`maxValue` and its label text together",
                *gap_px(code, themes.draw(edited(base, edits), PIN, WHEN)[0]))
        elif knob == "gradient":
            code = render.draw(PIN, name, gradient=value)
            row(knob, value,
                f"no key for it in the file model (the body compares it against {lits}), "
                f"so the drawing decides the ramp",
                *gap_px(code, themes.draw(base, PIN, WHEN)[0]))
        elif knob == "bg":
            for label, colour in (("clear", render.OVERLAY), ("black", render.BLACK)):
                code = render.draw(PIN, name, bg=colour)
                layer, _ = themes.draw(base, PIN, WHEN)
                plate = (Image.alpha_composite(Image.new("RGBA", layer.size, colour), layer)
                         if colour[3] == 255 else layer)
                row("bg " + label, label,
                    f"a {label} plate composited under the finished layer (`base=`); the "
                    f"code door puts the canvas in *before* the draw "
                    f"({lit(code):,} px lit, {lit(plate):,} lit the other way)",
                    *gap_px(code, plate))
    return sorted(knobs), out, unread


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", metavar="PATH", help="also write the rows as JSON")
    ap.add_argument("--theme", action="append", default=[],
                    help="one theme (repeatable); default: all five")
    args = ap.parse_args()

    names = args.theme or sorted(render.THEMES)
    rows, knobs_of, unread_all = [], {}, []
    real = render._now
    render._now = lambda: WHEN.timetuple()             # one instant, both doors
    try:
        for name in names:
            knobs, out, unread = measure(name)
            knobs_of[name] = knobs
            rows.extend(dict(r, theme=name) for r in out)
            unread_all.extend((name, k, d, r) for k, d, r in unread)
    finally:
        render._now = real

    print("a drawn theme's options, each answered the way a layout file would answer it")
    print(f"  one pinned reading dict at {WHEN:%Y-%m-%d %H:%M:%S}, no port, this machine's "
          f"fonts; the non-zero figures below move with the installed faces, the split does "
          f"not")
    print(f"  {'theme':6s} {'option':12s} {'value':13s} {'gap':>9s} {'worst':>6s}  "
          f"how a reader asks - and what the file door would do")
    for r in rows:
        print(f"  {r['theme']:6s} {r['knob']:12s} {str(r['value'])[:13]:13s} "
              f"{r['diff_px']:>9,} {r['worst_channel']:>6}  {r['route']}")
        print(f"  {'':41s}  {r['edit']}")
    exact = [r for r in rows if r["exact"]]
    gaps = [r for r in rows if not r["exact"]]
    print(f"\n  {len(exact)} of {len(rows)} (theme, option) pairs land at zero differing "
          f"pixels with a worst channel of 0: the file door can carry those knobs and the "
          f"frame reaching the panel does not change")
    print(f"  {len(gaps)} do not, and each is far from 0 rather than near it:")
    for r in gaps:
        print(f"    {r['theme']:6s} {r['knob']:12s} {r['diff_px']:>9,} px  {r['edit'][:78]}")
    if unread_all:
        print(f"  {len(unread_all)} option(s) are in a signature but never read by the body, "
              f"so they are left out of the rows instead of counted as answered:")
        for name, knob, default, route in unread_all:
            print(f"    render.theme_{name}({knob}={default!r}) - route: "
                  f"{route or 'none'} - a reader asking it changes nothing: 0 px")
    no_route = sorted({(r["theme"], r["knob"]) for r in rows if not r["route"]})
    if no_route:
        print(f"  {len(no_route)} pair(s) have no CLI or socket route at all "
              f"(`main._theme_kwargs` has no entry for them): "
              + " ".join(f"{t}.{k}" for t, k in no_route))
    print(f"  the options each theme's own signature offers: "
          + "  ".join(f"{n}:{','.join(k)}" for n, k in sorted(knobs_of.items())))
    smallest = min((r["diff_px"] for r in gaps), default=0)
    biggest = max((r["diff_px"] for r in gaps), default=0)
    print(f"  smallest non-zero gap {smallest:,} px, largest {biggest:,} px: nothing in the "
          f"map sits between 0 and {smallest:,}, which is what makes 'exactly 0 or clearly "
          f"not' a line a machine can check")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"when": WHEN.isoformat(), "reading": PIN, "knobs": knobs_of,
                       "unread": [[n, k, repr(d), r] for n, k, d, r in unread_all],
                       "rows": rows}, fh, indent=1, sort_keys=True)
        print(f"  wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
