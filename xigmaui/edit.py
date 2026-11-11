"""The editor's model: one layout, one selected widget, one pinned fixture.

This module holds no Qt.  It is the part of the editor that can be *held to a
number* - what a field means, what changing it does to the picture, and what undo
owes you - and the window is a thin shell over it.  That split is deliberate: the
claim of stage 4 in docs/theme-editor.md is not "there is a form", it is "an edit
you make here is the frame the loop would send", and the only way to gate that is to
keep the drawing and the file model in one place that the suite can drive headless.

Three rules, all of them borrowed from the library (xigmalcd/themes.py) rather than
invented here:

* **The vendor's files are never what changes.**  `open_theme` only reads; the single
  writer is `themes.save`, which puts the layout under `~/.config/xigmalcd/themes`
  and refuses both vendor trees and the five drawn-from-code names.  `themes.resolve`
  is user-first, so from that moment `--theme` means your copy.
* **The picture is the loop's picture.**  `paint` calls `themes.draw`, which is what
  `--check-theme` uses and what the frame loop uses for a layout theme.  There is no
  second renderer for the editor, because a second renderer is a second truth.
* **The fixture is pinned.**  Editing a field while the readings change underneath
  you makes the picture jump for reasons that are not your edit.  The metrics and the
  instant are fixed until you ask for live readings; `fixture_line` says what they are
  so the window can print it rather than imply it.
"""
from __future__ import annotations

import copy
import datetime
import os
import re
import uuid

from xigmalcd import layout, render, themes

def field_names(kind: str) -> tuple:
    """Every field the inspector offers for one kind, in the order the row shows them.

    Not a hand-kept list: what a kind may edit is the intersection of the keys this
    program is *proven* to read (`themes.keys_read()` takes them out of `layout.py`'s
    source with `ast`) and what that kind draws.  A key the vendor carries but nothing
    reads is never offered - the census prints those 11 with the reason each is inert,
    and the vendor editor's own bookkeeping (`enableMove`, `screenStatus`) stays out of
    the form and survives a save untouched, because `themes.save` writes the widget's
    `property` back as it read it.

    A `special` row that draws a *pair* edits `width`: `layout.draw_special_pair` reads it
    as the distance between the two figures' centres, so it is a placeable number like any
    other, and `field_note` below is where the row says what it means.
    """
    read = set(themes.keys_read()[0])
    per_kind = {
        "text": ("content", "fontFamily", "fontSize", "bold", "textColor"),
        "data": ("source", "fontFamily", "fontSize", "bold", "textColor"),
        "bar": ("source", "minValue", "maxValue", "width", "height", "cornerRadius",
                "bgColor", "startColor", "endColor"),
        "arc": ("source", "minValue", "maxValue", "width", "radius", "sizeWidth",
                "sizeHeight", "angleStart", "angleEnd", "bgColor", "startColor",
                "endColor"),
        "line": ("width", "height", "rotate", "lineColor", "lineWidth"),
        "special": ("name", "width", "fontFamily", "fontSize", "bold", "textColor"),
    }
    out = ["x", "y"] + [k for k in per_kind.get(kind, ()) if k in read]
    return tuple(out)


def field_note(kind: str, field: str, name: str = "") -> str:
    """One sentence on what a field *means* for this row, when its name is not enough.

    The `special` kind needs this more than any other, because its fields are read by a
    drawing this repo wrote and not by a painter with one shape: a row that draws a *pair*
    of figures reads `width` as the distance between the two figures' centres and `x` as
    their shared centre, while a row that draws one line of built text reads `width` not at
    all.  A field list cannot show that difference - both rows are `special` - so the note
    line says it in both directions, rather than leaving a reader to set a number that
    does nothing.  Which shape a name has is asked of the registry, whose entry knows the
    door it draws through (`themes.special_is_pair`, and `themes.special_door` for which of
    the two pair doors it is), because the door is what decides the meaning:
    `layout.draw_special_pair` reads `width` and `xigma.autoFitMax`, `draw_special_line`
    reads neither, and `draw_special_values` reads `width` but sizes itself against
    `xigma.fitArc`.
    """
    if kind != "special":
        return ""
    pair = themes.special_is_pair(name)
    if field == "width":
        return (("for this drawing, `width` is the distance between the two figures' "
                 "centres: each is placed half this far to one side of x, so the pair "
                 "stays centred on it. It is not a box width") if pair else
                ("this drawing is one line of built text: it does not read `width`. What "
                 "the line may be is `fontSize` with `xigma.autoFitMax`, and where it "
                 "starts is x, y with `xigma.anchor`"))
    if not pair:
        return ""
    if field in ("x", "y"):
        return "the pair's own anchor point, not one figure's corner"
    if field == "fontSize":
        # a ceiling, not the size: the drawing walks down until both figures fit.  What
        # they are fitted *against* is the difference between the two pair doors, and a
        # note that said "autoFitMax" for a row that never reads it would be the kind of
        # sentence this repo keeps having to take back
        return ("a ceiling. Both figures are fitted to `xigma.autoFitMax`, and the pair "
                "draws at the smaller of the two fits, at or below this size"
                if themes.special_door(name) == "pair" else
                "a ceiling this pair never reaches: the size walks down until both figures "
                "clear the ring named in `xigma.fitArc`, and both draw at that one size")
    return ""


def extension_fields(kind: str) -> tuple:
    """Which `xigma` keys apply to this kind, with their reasons (printed by the tool)."""
    _read, sub = themes.keys_read()
    applies = {
        "text": ("anchor", "autoFitMax", "showIf"),
        "data": ("anchor", "autoFitMax", "format", "showIf"),
        "bar": ("barPaint", "colourRamp", "colourStops", "showIf"),
        "arc": ("arcPaint", "colourRamp", "colourStops", "showIf"),
        "line": ("showIf",),
        "special": ("anchor", "autoFitMax", "fitArc", "showIf"),
    }
    return tuple(k for k in applies.get(kind, ()) if k in sub)


#: The choices a field can take, enumerated rather than free text, because the whole
#: vocabulary already exists in code: families in `layout.FONTS`, metric names in the
#: source table, special drawings in `themes.SPECIALS`, painter conventions in
#: `layout.ARC_PAINT`/`layout.BAR_PAINT`, named ramps in `layout.COLOUR_RAMPS`.  The
#: window shows these as a menu; the model refuses a value outside them, in words.
def choices(field: str) -> tuple:
    if field == "fontFamily":
        return tuple(sorted(layout.FONTS))
    if field in ("source", "showIf"):
        # both name a reading, so both get the same vocabulary - every source this program
        # can put a value behind, including the derived ratios and the positional fan slots
        return tuple(sorted(themes.source_names()))
    if field == "name":
        return themes.special_names()
    if field == "arcPaint":
        return tuple(sorted(layout.ARC_PAINT))
    if field == "barPaint":
        return tuple(sorted(layout.BAR_PAINT))
    if field == "colourRamp":
        return tuple(sorted(layout.COLOUR_RAMPS))
    if field == "anchor":
        return ("mm", "la", "lt", "lm", "rm", "rb")
    if field in ("bold",):
        return (True, False)
    return ()


#: The five colour fields a widget can carry, and the one spelling the library uses for
#: all of them: CSS `rgba(r, g, b, a)` with `a` a 0..1 fraction (measured across the 152
#: shipped widgets - `layout.rgba`'s docstring is where that census lives).
COLOUR_FIELDS = ("textColor", "bgColor", "startColor", "endColor", "lineColor")

#: The one menu field whose value the painter folds before looking it up.
#: `layout.font_for` lowercases `fontFamily`, so the `Arial` the vendor's files write and
#: the `arial` `layout.FONTS` names are the **same face** on the glass - and an editor
#: that shows the file's spelling in its menu but refuses it in its model is offering a
#: choice it will not take.  Every other menu is matched exactly, because the painter
#: matches it exactly: `source`, `showIf`, `name` and `anchor` are dictionary keys, so
#: their case is part of the value and nothing is folded for them.
CASE_FOLDED_FIELDS = ("fontFamily",)


def kinds() -> tuple:
    """The row kinds this program draws, taken from the painter's own table."""
    return tuple(sorted(layout.KINDS))


def colour_text(value) -> tuple:
    """(a colour in the vendor's spelling, or None, and the sentence if it failed).

    The reader may write `rgba(255, 64, 64, 1)` - the shape the files already hold, kept
    exactly as typed, because alpha there is already a fraction and rewriting it would
    move digits nobody touched - or any colour `render.parse_ink` reads: `#ff4040`,
    `amber`, `rgb(0,230,118)`.  The second kind becomes `rgba(...)`, because
    `layout.rgba` cannot read anything else and a file that reaches the drawer with
    `#ff4040` in it fails far from its cause.  What was stored comes back as a note the
    window prints, so the conversion is said out loud rather than done quietly.
    """
    if isinstance(value, str) and "(" in value:
        try:
            layout.rgba(value)
        except (ValueError, IndexError):
            return None, (f"{value!r} is not an rgba() colour: write rgba(r, g, b, a) "
                          f"with a between 0 and 1, or a name like amber, or #ff4040")
        return value, ""
    try:
        argb = render.parse_ink(value)
    except ValueError as exc:
        return None, str(exc)
    if argb is None:
        return None, ("a colour has to be a colour: this program's own 'default' means "
                      "'the theme's skin', which a layout file spells by not setting one")
    r, g, b, a = argb
    alpha = "1" if a == 255 else f"{a / 255:.6g}"
    return f"rgba({r}, {g}, {b}, {alpha})", ""


def number_fields() -> tuple:
    """Fields held as numbers, so the row can use a spinbox and nudges add to them."""
    return ("x", "y", "width", "height", "radius", "sizeWidth", "sizeHeight",
            "minValue", "maxValue", "angleStart", "angleEnd", "cornerRadius",
            "rotate", "lineWidth", "fontSize", "autoFitMax")


def _overlaps(box: tuple, others: list) -> bool:
    """Does this ink box meet any of those boxes?

    The boxes come out of `layout.draw` as `(x0, y0, x1, y1)` in panel px, and `hit` treats
    them as inclusive.  For placing a new row this answers the question a reader would ask,
    which is whether the two *meet*: two boxes that only share an edge are not on top of each
    other, so the test is strict at the edges.
    """
    x0, y0, x1, y1 = box
    for o in others:
        if x0 < o[2] and x1 > o[0] and y0 < o[3] and y1 > o[1]:
            return True
    return False


#: The five keys that every one of the **185** widget rows in the **28** layouts this
#: editor opens carries - measured over the 23 vendor files and the 5 generated exports,
#: and re-counted by the suite on every run rather than remembered here: one distinct key
#: set, `id`, `layerIndex`, `property`, `type`, `widgetContent`, and `property` a
#: one-element list in all 185 (`themes.validate` makes that hard, because
#: `layout.draw_theme` reads `property[0]` and would silently leave the rest unwritten).
#: `widgetContent` is `""` in every row this program has ever read.
WIDGET_KEYS = ("id", "layerIndex", "type", "property", "widgetContent")

#: How far the placement scan steps across the canvas when it is looking for a free spot:
#: fine enough to find a gap a copied row fits in, coarse enough that the scan is a few
#: thousand overlap tests rather than a few hundred thousand.  It is a cost, not a claim
#: about the glass - what the suite holds is the behaviour (a row that would meet another
#: box is moved to the nearest place it does not, and a row with nowhere to go stays where
#: its source sits and says so in words) and it prints, per machine, how many of the adds
#: went which way.
PLACE_STEP = 4

#: The two structural keys nothing here reads, and what the files say about them.
#: `layerIndex` is **not** the row's position: over the vendor's files it equals the row's
#: position in **23** of their **123** rows and differs in **100** (`Theme_01` gives six of
#: its eight rows 0).  Nothing in `layout.py` touches it either.  So a reorder leaves it
#: exactly as it stands: the order that draws is the order of `osd.widget` - which is what
#: `hit` follows ("later row wins an overlap") and what the painter walks - and giving an
#: inert key a meaning the vendor's own files do not show is the silent repair this repo
#: refuses.  Every digit in that sentence is the suite's, re-counted from the files on each
#: run: the gate fails if it stops being true, here or in docs/gui.md.
_UUID_ID = re.compile(r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")

_REF_ROWS: dict = {}


def reference_row(kind: str) -> tuple:
    """A real row of `kind` for a layout that carries none: `(row, the sentence that says
    where it came from)`, or `(None, the refusal)`.

    Ranked on purpose.  First this program's own five exports, because every row in them is
    carried to a zero-pixel diff against the picture it exports - a default taken from there
    is a default proven to draw - and then the vendor's files in name order.  A new row is
    always a copy of a row that exists somewhere in this corpus, never a table of values
    somebody guessed: the vendor's application bundles are not in this tree (only their file
    names are, in PROTOCOL.md §10), so these files are the only evidence of what a row
    of a kind looks like.
    """
    if kind in _REF_ROWS:
        return copy.deepcopy(_REF_ROWS[kind][0]), _REF_ROWS[kind][1]
    for name in sorted(themes.EXPORTS):
        for w in ((themes.EXPORTS[name]().get("osd") or {}).get("widget") or []):
            if str(w.get("type") or "") == kind:
                _REF_ROWS[kind] = (w, f"a copy of `{name}`'s `{w.get('id')}` row, from the "
                                      f"five layouts this repo draws from code")
                return copy.deepcopy(_REF_ROWS[kind][0]), _REF_ROWS[kind][1]
    ok, _bad = themes.scan()
    for rec in sorted(ok, key=lambda r: r["name"]):
        for w in ((themes.load(rec["path"]).get("osd") or {}).get("widget") or []):
            if str(w.get("type") or "") == kind:
                _REF_ROWS[kind] = (w, f"a copy of `{rec['name']}`'s `{w.get('id')}` row, "
                                      f"one of the vendor's files")
                return copy.deepcopy(_REF_ROWS[kind][0]), _REF_ROWS[kind][1]
    return None, (f"none of the {len(themes.EXPORTS) + len(ok)} layouts has a `{kind}` row, "
                  f"so there is no real row to copy and this model will not invent one")
class Editor:
    """One layout being edited: its widgets, the selected one, and an undo stack."""

    def __init__(self, obj: dict, origin: str = "", path: str = "", name: str = "",
                 theme: str | None = None):
        self.obj = obj
        self.origin = origin                    # "your copy", "checkout", "package"
        self.path = path                        # where a save would go, "" if new
        # Which drawn theme this layout was generated from, or None if it came from a
        # file.  It is what decides whether the window's text colour may move the
        # preview at all: a layout's colours are its own (`layout.py` says so at the top
        # of the module, and it is why a vendored theme looks the same here as in the
        # vendor's app), while one of the five names this repo draws from `render.py` has
        # a *declared* skin - `render.SKIN` - that `themes.with_ink` can move.
        self.theme = theme
        # a vendor file's top-level `id` is a number (the theme id), so the *name* is
        # carried separately: it is what `--theme <name>` and `themes.resolve` speak
        self.name = name or str(obj.get("id") or "theme")
        self.index = 0
        self.history: list[dict] = []           # deep copies, one per committed change
        self._pending: dict | None = None       # the value before a run of keystrokes
        # two snapshots, and `dirty` is read off them rather than remembered:
        #   _baseline  what this editor first read, i.e. what the loop draws today
        #   _saved     what a file holds from this editor's side of things
        # They start the same because opening writes nothing.  `save` moves _saved to
        # the new object; `revert` moves it back to _baseline, because the copy is gone
        # and the vendor's file is what the loop will read again.
        self._baseline = copy.deepcopy(obj)
        self._saved = copy.deepcopy(obj)
        self.ink_note = ""        # what `paint(..., ink=)` did, for the caption

    @property
    def dirty(self) -> bool:
        """Memory and disk disagree.

        Opening a layout never makes it dirty, editing it always does, and `save` or
        `revert` is what clears it - so the word means what a reader assumes it means,
        and the window can put it next to the Save button without a flag to keep in
        step.
        """
        return self.obj != self._saved

    # ------------------------------------------------------------ opening --
    @classmethod
    def open_theme(cls, name: str) -> "Editor":
        """A layout the library has, read in for editing.  **Opening writes nothing.**

        The layout is read into memory and only `save` puts a file down, because the
        shadowing rule - your copy of a name is what `--theme` and the control socket
        find first - is a fact about files: the moment a copy appears is the moment the
        reader chose it, and browsing a theme's fields should not silently change what
        the loop draws.  A name that has already been edited resolves to the copy, which
        is the point: reopening continues rather than starting over.

        One of the five drawn from code is generated instead (`themes.export`), because
        there is no file for it and there will not be one: a saved `gauge.json` would be
        a second source of truth for `render.theme_gauge` (docs/limits.md).
        """
        if name in themes.EXPORTS:
            return cls(themes.export(name), origin="generated from render.py", path="",
                       name=name, theme=name)
        rec = themes.resolve(name)
        if rec is None:
            raise KeyError(f"no layout named {name!r}: {themes.why_not(name)}")
        # `themes.load` hands back the object it caches by (path, mtime) - that is how an
        # edited theme shows up on the loop's next frame without a restart.  The editor
        # edits in place, so taking that object without a copy would put unsaved keystrokes
        # into the library's own cache, where `scan()`, `pair()` and `describe()` read them:
        # one process, two readers, and the file said to be on disk disagreeing with the
        # preview of it.
        return cls(copy.deepcopy(themes.load(rec["path"])), origin=themes.origin(rec),
                   path=themes.user_theme_path(rec["name"]), name=rec["name"])

    # --------------------------------------------------------------- saving --
    def save(self) -> tuple:
        """Write the edited layout into the user directory, canonically and atomically.

        `themes.save` is the only writer here, and it raises for the names it will not
        take: the two vendor trees, and the five drawn-from-code names - a saved
        `gauge.json` would be a second `theme_gauge` to disagree with `render.theme_gauge`
        (docs/limits.md).  A refusal comes back as (None, the reasons), because a window
        should print that sentence rather than unwind through it, and the suite can then
        read the same words the reader sees.
        """
        hard, _soft = themes.validate(self.obj)
        if hard:
            return None, hard
        try:
            path, warnings = themes.save(self.obj, self.name)
        except (ValueError, OSError) as exc:
            return None, [str(exc)]
        self.path = path
        self._saved = copy.deepcopy(self.obj)     # from here, disk holds this picture
        return path, warnings

    def revert(self) -> str:
        """Drop the copy: the loop reads the vendor's file again.

        The edits stay in memory - this is not an "are you sure" dialog, and a reader
        who has spent ten minutes moving widgets should not lose them because they
        wanted to see the original once.  `dirty` says so out loud, and `undo` or a
        reopen is how they get back.
        """
        try:
            gone = themes.delete_user_theme(self.name)
        except ValueError as exc:           # a name the writer would not take either
            return f""
        self._saved = copy.deepcopy(self._baseline)
        return gone


    # ---------------------------------------------------- naming a copy --
    @property
    def where(self) -> str:
        """Where the file that answers this layout's name comes from **today**.

        `origin` is what this editor read when it opened, and it stays that: "the vendor's
        file in this checkout" is a true sentence about the bytes in memory.  What moves is
        the file `--theme` finds, and it moves at exactly three moments - a save, a revert,
        a rename - so an answer remembered from before one of them is a stale answer about
        a file that no longer answers.  The window asks this door instead: it is
        `themes.resolve()` on the current name, the same lookup `--list-themes`, the loop's
        own log line and the control socket's `theme` command go through.
        """
        if not self.path and self.name in themes.EXPORTS:
            return "generated from render.py"
        rec = themes.resolve(self.name)
        if rec is None:
            return "no file at all"          # your copy is gone and the library never had
                                            # this name: a renamed copy, then a revert
        return themes.origin(rec)

    def _retire_id(self, fresh: str) -> None:
        """Say that this layout's id is now `fresh`, everywhere memory holds one.

        `history` snapshots whole objects, so an id left behind in them would creep back on
        the first press of undo: an undo step is a change of *content*, never a change of
        identity.  `_baseline` is deliberately not touched - it is the bytes this editor
        first read, under a name and an id that may both be gone by now, and it is what
        `revert` hands back to `_saved` to say "the copy is gone, your typing is not".
        """
        fresh = str(fresh)
        if str(self.obj.get("id")) == fresh:
            return
        self.obj["id"] = fresh
        self._saved["id"] = fresh
        if self._pending is not None:
            self._pending["id"] = fresh
        for snap in self.history:
            snap["id"] = fresh

    def rename(self, name: str) -> tuple:
        """Move this copy to a new name.  `(path, notes)`, or `(None, [the reason])`.

        A file act, not an edit: no undo step is taken, nothing in the layout's rows moves,
        and the picture is the same picture.  What changes is the name the library answers
        and the `id` inside the file - see `themes.rename_copy` for why an id has to come
        along with a new name, and `why` below for the refusals.  Memory follows the file:
        the new id is written into the object, its snapshots and its save-point, so
        `dirty` says exactly what it said before the press.
        """
        try:
            path, notes = themes.rename_copy(self.name, name)
        except (ValueError, OSError) as exc:
            return None, [str(exc)]
        # the id the door chose is read back through the library's own parser rather than
        # guessed at: `themes.load` keys on (path, mtime), and this path is brand new
        self._retire_id(themes.load(path).get("id"))
        self.name = os.path.basename(path)[:-len(".json")]
        self.path = path
        self.origin = "your copy"           # there is no vendor file behind *this* name
        return path, notes

    def save_as(self, name: str) -> tuple:
        """Write this layout again, under a name nothing in the library answers.

        `(path, notes)`, or `(None, [the reason])`.  This is how one layout becomes two of
        yours: the file where it was stays exactly as it was - every byte, and its id - and
        the new copy takes a fresh id (`themes.new_id`) so that no two files answer the same
        `--theme <id>`.  From here the editor is editing the new copy; the old one is just
        another layout, and the note says which file is which.

        A layout that never had a file - one of the five drawn from `render.py` - gets its
        first one here, and that is not the thing the save button refuses: what is refused
        is a `gauge.json` that would be a second source of truth for `theme_gauge`.  A file
        called `my-gauge.json` is a layout of its own, and `--theme gauge` still draws the
        code's picture.
        """
        try:
            nm = themes.new_name(name)
        except (ValueError, OSError) as exc:
            return None, [str(exc)]
        fresh = themes.new_id()
        out = copy.deepcopy(self.obj)
        out["id"] = fresh
        hard, _soft = themes.validate(out)
        if hard:
            return None, hard
        was_name, was_path = self.name, self.path
        try:
            path, warnings = themes.save(out, nm)
        except (ValueError, OSError) as exc:
            return None, [str(exc)]
        self._retire_id(fresh)
        self._saved = copy.deepcopy(self.obj)
        self.name, self.path = nm, path
        self.origin = "your copy"
        notes = [
            f"{os.path.basename(path)} is yours, under the name {nm!r} and with id {fresh}",
            (f"{os.path.basename(was_path)} stays where it was, with id "
             f"{themes.load(was_path).get('id')}: two layouts, two ids, and the window is "
             "now editing the new one" if was_path and os.path.exists(was_path) else
             (f"there was no file for {was_name!r} before this: it is drawn from "
              f"`render.py`, and `--theme {was_name}` still draws the code's picture"
              if not was_path else
              f"{was_name!r} had no copy of its own, so nothing was left behind"))] + \
            list(warnings)
        return path, notes

    # ------------------------------------------------------------ widgets --
    def widgets(self) -> list:
        return self.obj.get("osd", {}).get("widget") or []

    def selected(self) -> dict:
        return self.widgets()[self.index]

    def prop(self) -> dict:
        return (self.selected().get("property") or [{}])[0]

    def label(self, i: int | None = None) -> str:
        """One short line per widget: what it is, and what it shows.

        Deliberately short enough for a combo box that is one column wide: the id is in
        `tip`, which is where a tooltip can be as long as it needs to be.
        """
        w = self.widgets()[self.index if i is None else i]
        pr = (w.get("property") or [{}])[0]
        what = (pr.get("source") or pr.get("content") or pr.get("name")
                or pr.get("type") or "")
        return (f"{w.get('type')}  {what}  at {pr.get('x')},{pr.get('y')}")

    def tip(self, i: int | None = None) -> str:
        """The same line with the widget's `id`, which is how a reader finds the one
        entry in the file to check the edit in a diff.  Vendor ids are uuid4 and ours
        are `xigma-*`; both are shown as they are."""
        w = self.widgets()[self.index if i is None else i]
        return f"id {w.get('id')}  |  {self.label(i)}"

    def select(self, index: int) -> None:
        if not 0 <= index < len(self.widgets()):
            raise IndexError(f"widget {index}: this layout has {len(self.widgets())}")
        self.index = index

    # ---------------------------------------------------------- the canvas --
    def hit(self, notes: dict, x: int, y: int):
        """Which row's ink box covers this panel px, or None if nothing is there.

        The boxes are the ones `paint` records - the same boxes `--check-theme` prints -
        so the pane and the report agree about where a row sits without either keeping a
        copy of the answer.  Each record carries the row's own index in `osd.widget`, and
        that is what comes back: a list of *drawn* boxes is not a list of rows, because a
        row whose source has no reading contributes nothing to it, and a window that
        answered "row 3" from a position in that list would select the wrong entry in a
        file with anything skipped.  Where two boxes overlap, the **later** row wins,
        because that is the one drawn on top: `alpha`'s temperature figures sit inside its
        gauge rings, and "last one wins" is what makes a reading inside a dial grabbable at
        all instead of leaving the ring under the cursor steal the click.
        """
        found = None
        for rec in notes.get("boxes") or []:
            box, wi = rec[2], rec[3]
            if not box:
                continue
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                found = wi
        return found

    def move_to(self, nx: int, ny: int, commit: bool = True) -> tuple:
        """Put the selected row's anchor at (nx, ny) panel px, as **one** undo step.

        This is what a drag and what an arrow key both end up calling, and the two rules
        in it are the ones a reader would otherwise be surprised by.  Both fields are
        checked before either is written: a move that would leave the anchor off the
        canvas is refused whole, in `_check`'s own words, because moving `x` and not `y`
        would put the row somewhere nobody dragged it to.  And a move to where the row
        already is writes nothing at all - no run in progress, no undo step - so a click
        that turns out not to be a drag does not leave a press of undo doing nothing.
        """
        pr = self.prop()
        kind = str(self.selected().get("type") or "")
        x, y = int(pr.get("x") or 0), int(pr.get("y") or 0)
        nx, ny = int(nx), int(ny)
        if (nx, ny) == (x, y):
            return True, ""
        ext = set(extension_fields(kind))
        for field, val in (("x", nx), ("y", ny)):
            bad = self._check(kind, field, val, ext)
            if bad:
                return False, bad
        ok_x, note_x = self.set("x", nx, commit=False)
        ok_y, note_y = self.set("y", ny, commit=False)
        if not (ok_x and ok_y):
            self.undo()                       # drop the run: one field refused the other
            return False, note_x or note_y or "the row refused the move"
        if commit:
            self.commit()
        return True, ""

    def move(self, dx: int, dy: int, commit: bool = True) -> tuple:
        """The same door measured as a distance: see `move_to` for what it guarantees."""
        pr = self.prop()
        return self.move_to(int(pr.get("x") or 0) + int(dx),
                            int(pr.get("y") or 0) + int(dy), commit=commit)

    # ------------------------------------------------------------ snapping a drag --
    #: How close a row has to come to a line before it is pulled onto it, in panel px.
    #: The number comes out of counting the library's own declarations, not out of taste:
    #: of the **185** rows that carry an `x` or a `y` in the **28** layouts this pane can
    #: open, **89** hold an `x` another row of the same file holds exactly and **44** do
    #: the same with `y` - **317** pairs of rows holding one number between them.  And the
    #: rest are apart on purpose: the nearest other row's `x` is 1 px away for **0** of
    #: those rows, 2 px away for **12**, and 3 px away for **4**, with nothing at all 6 or
    #: 7 px off.  So 2 px is the break between "these two are meant to line up" and "these
    #: two are spaced".  Three is not that break: a drag of 3 px right is pulled onto
    #: another row's `x` 11% of the time at 1 px, **12%** at t=2 and **57%** at t=3,
    #: because rows sharing a column sit within 3 px of each other's landing - a snap
    #: arguing with the person dragging.  Those counts read only the numbers in the files,
    #: so the suite re-counts them on every machine and the gate holds this module's
    #: sentence, docs/gui.md and the changelog stanza to whatever it answers.
    #: `SNAP_PX` is also the measure of what the arrow keys do **not** do: a 1 px nudge
    #: pulled back is a keypress that did nothing.
    SNAP_PX = 2

    @staticmethod
    def anchor_class(row: dict) -> str:
        """`'l'`, `'m'` or `'r'`: what this row's `x` means on the glass.

        The vendor's rows keep Pillow's two-letter anchor name under `xigma.anchor`, and
        the **first** letter is the horizontal one (`la` left-ascender, `rm` right-middle,
        `mm` middle-middle); the second says only where the line sits vertically.  That is
measured rather than read off the name: the suite draws the layouts this pane can
        open and compares each row's declared `x` with its ink box, and finds `la` and `lm`
        rows with `x` exactly at the box's left edge, `rm` rows exactly at its right edge,
        and `ma`/`mm`/`ms` rows strictly between the two - their `x` *is* the centre.  Those
        are pixels, so they follow the face they were drawn in: the assertion belongs to the
        run that makes it, not to this sentence.  A row with no `xigma.anchor` is
        `layout.py`'s default, `la`.
        """
        pr = (row.get("property") or [{}])[0]
        a = str((pr.get("xigma") or {}).get("anchor") or "la").strip().lower()
        return a[0] if a[:1] in ("l", "m", "r") else "l"

    def _centre(self) -> tuple:
        """The middle of the canvas **this file declares**, as `(x, y)`.

        Not a constant: the same door the field bounds use reads `width`/`height` off the
        layout and falls back to `render.W`/`render.H`, so this layout centres where its own
        file says.  Every layout this program can select declares 480x480 today
        (docs/themes.md keeps the four 4:3 files out of the picker), so the honest form is:
        240 here, because this file says 480.
        """
        return (int(self.obj.get("width") or render.W) // 2,
                int(self.obj.get("height") or render.H) // 2)

    def _x_number(self, index: int, coord: float, box) -> tuple:
        """The `x` that puts *this* row's edge at a glass coordinate, and what it cost.

        A line on the glass is a coordinate, and the number a row has to write to reach it
        depends on its own anchor class.  A centre-anchored row writes the coordinate itself;
        a left- or right-anchored row adds or takes away half its ink, and the only door that
        knows a row's ink width is the painter.  `box` is that row's drawn box, out of the
        single frame `snap_lines` draws; `(None, reason)` when it has none, which is the
        answer D's edges give too for a row with no box to grab.
        """
        cls = self.anchor_class(self.widgets()[index])
        coord = int(round(coord))
        if cls == "m":
            return coord, ""
        if not box:
            return None, ("this row paints no box at this fixture, so its ink has no width "
                          "to centre with")
        half = (box[2] - box[0]) / 2.0
        said = f"half this row's {box[2] - box[0]} px of ink at this fixture"
        if cls == "l":
            return int(round(coord - half)), said
        return int(round(coord + half)), said

    def snap_lines(self, index: int | None = None, box=None) -> dict:
        """The lines this layout offers one row: `{axis: [(number, what it is)]}`.

        Three families, and each one is a habit measured in these files rather than a
        convention invented here:

        * another row's declared `x`, **only within one anchor class**.  **317** pairs of
          rows in this library hold the same number; snapped across classes, the two rows'
          ink would sit most of a canvas apart rather than lined up (the suite measures how
          far, on the machine it runs on, and refuses the pair if the answer ever comes back
          small), so a number aligns only when both rows agree what it means.  A row with a
          declared width offers its other edge too: `x + width` for a `bar`, `x + sizeWidth`
          for an `arc`, `x + width` for a `line` (the rect `layout.line_rect` draws, which
          D's resize door already reads), and the two figures' centres - `x - width/2` and
          `x + width/2`, the pitch D's size door names - for a `special` pair row.
        * another row's declared `y`, with no class rule: the anchor's second letter runs
          along the line, it does not move ink left or right, and **44** rows already hold a
          `y` another row of the same file holds.
        * the canvas centre and the mirror of another row's centre, **on x only** - and the
          files chose that, not this module: **13** rows declare `x` exactly 240 and **220**
          pairs declare two `x` values that sum to the 480 the same file declares, while on
          the other axis **3** rows sit at the middle and **8** pairs mirror.  A habit on one
          axis is not a habit on the other, so y gets no centre line and no mirror line
          (`_centre` reads the middle off this file rather than assuming 240).
        * the canvas edges are **not** lines, on either axis: not one row in those 28 layouts
          declares `x` or `y` at 0 or at 479.  The edges are what `move_to` refuses to cross,
          not a number rows line themselves up on.
        """
        i = self.index if index is None else int(index)
        rows = self.widgets()
        cls = self.anchor_class(rows[i])
        # one draw for the whole question: `_row_box` draws per call, which a model gate can
        # afford and a live drag cannot, because a drag asks on every motion event.  The pane
        # already holds this row's box in its own marks and hands it in.
        _img, _notes = themes.draw(self.obj, dict(FIXTURE), FIXTURE_WHEN)
        boxes = {r[3]: tuple(r[2]) for r in (_notes.get("boxes") or []) if r[2]}
        my_box = box if box is not None else boxes.get(i)
        out: dict = {"x": [], "y": []}

        def add(axis, value, said):
            v = int(round(value))
            if not any(v == got for got, _s in out[axis]):
                out[axis].append((v, said))

        for j, w in enumerate(rows):
            if j == i:
                continue
            pr = (w.get("property") or [{}])[0]
            kind = str(w.get("type") or "")
            if pr.get("x") is not None and self.anchor_class(w) == cls:
                xj = int(pr["x"])
                add("x", xj, f"row {j} (`{kind}`, {cls}-anchored like this row) "
                              f"declares `x`")
                for key in {"bar": ("width",), "arc": ("sizeWidth",),
                            "line": ("width",)}.get(kind) or ():
                    if pr.get(key):
                        add("x", xj + int(pr[key]),
                            f"row {j} (`{kind}`)'s far edge, its `x` plus its `{key}`")
                if kind == "special" and themes.special_is_pair(str(pr.get("name") or "")):
                    pitch = int(pr.get("width") or 0)
                    for sign in (-1, 1):
                        if pitch:
                            add("x", xj + sign * pitch // 2,
                                f"row {j}'s {'left' if sign < 0 else 'right'} figure, "
                                f"at its `x` {'-' if sign < 0 else '+'} half the pitch "
                                f"{pitch}")
            if pr.get("y") is not None:
                add("y", int(pr["y"]), f"row {j} declares `y`")

        c0, _cy = self._centre()
        centre, cost = self._x_number(i, c0, my_box)
        if centre is not None:
            add("x", centre, f"the canvas centre, {c0}" + (f", plus {cost}" if cost else
                             ", which is what this row's own `x` means"))
        for j, w in enumerate(rows):
            if j == i or (w.get("property") or [{}])[0].get("x") is None:
                continue
            pr = (w.get("property") or [{}])[0]
            other = boxes.get(j)
            # a row that paints ink is placed by where that ink sits; a row that paints none
            # at this fixture falls back on the anchor point, which is the number the file
            # wrote and so is the only honest centre it can offer
            mid = ((other[0] + other[2]) / 2.0 if other else int(pr["x"]))
            mir, cost = self._x_number(i, 2 * c0 - mid, my_box)
            if mir is not None:
                add("x", mir, f"mirrored about the centre with row {j}, whose centre is at "
                              f"{int(round(mid))}" + (f", plus {cost}" if cost else ""))
        for axis in out:
            out[axis].sort()
            # a line off this file's canvas is not a line anyone can land on: the mirror
            # arithmetic can ask for a negative `x`, and `move_to` would refuse that landing
            # anyway, but the pane would then spend a guide line drawing nothing on the glass
            cx, cy = self._centre()
            lim = (2 * cx, 2 * cy)[0 if axis == "x" else 1]
            out[axis] = [(v, s) for v, s in out[axis] if 0 <= v < lim]
        return out

    def snap_move(self, nx: int, ny: int, index: int | None = None, was=None,
                  box=None, lines=None) -> tuple:
        """Pull a drag's landing onto the nearest line the layout offers, `SNAP_PX` at most.

        `(x, y, notes)`, and nothing is written: `move_to` stays the door that writes, with
        its own refusal of an anchor off the canvas.  `was` is the anchor the drag
        **started** from, and a line the row was already sitting on is not offered - that is
        how a row leaves a line it is on, with no modifier and no checkbox, which is what
        these files ask for.  89 of the 185 rows here hold an `x` another row of the same
        file holds, so without break-away a 2 px drag from a shared column would be undone
        by the snap before the pointer had moved.

        The notes say which line took hold and what the pull was, in the words `snap_lines`
        built; the pane shows them while the mouse is down and again after the release, the
        same ask-and-result rule feature D painted the resize box by.
        """
        i = self.index if index is None else int(index)
        nx, ny = int(nx), int(ny)
        # `lines` is here because a drag asks on every motion event and the lines cost one
        # frame to find: the pane computes them once, at the press, and hands the same answer
        # to every event until the rows change.  A caller with no such state (a gate, the
        # field-row door) lets the model work it out.
        lines = lines if lines is not None else self.snap_lines(i, box=box)
        notes = []
        for axis, want, from_ in (("x", nx, (was or (nx, ny))[0]),
                                  ("y", ny, (was or (nx, ny))[1])):
            best = None
            for value, said in lines[axis]:
                if abs(value - from_) <= self.SNAP_PX:      # the line you left is not a line
                    continue
                pull = abs(value - want)
                if pull <= self.SNAP_PX and (best is None or pull < best[0]):
                    best = (pull, value, said)
            if best:
                notes.append(f"snapped {axis} {want} -> {best[1]} ({best[0]} px away): "
                             f"{best[2]}")
                if axis == "x":
                    nx = best[1]
                else:
                    ny = best[1]
        return nx, ny, notes

    # ------------------------------------------------ add / delete / reorder rows --
    def rows_of(self, kind: str) -> list:
        """Indexes of the rows of one kind, in draw order."""
        return [i for i, w in enumerate(self.widgets()) if str(w.get("type") or "") == kind]

    def _step(self) -> None:
        """Record the whole layout as the state one press of undo goes back to.

        Field writes coalesce a run of keystrokes into one step (`set(commit=False)`, then
        `commit`); adding, removing or moving a row is one act, so it gets one snapshot
        here.  A run still in progress is committed first, so a row added while a spinbox is
        mid-drag does not swallow that keystroke.
        """
        self.commit()
        self.history.append(copy.deepcopy(self.obj))
        if len(self.history) > 60:
            del self.history[0]

    def _source_row(self, kind: str) -> tuple:
        """The row a new one of `kind` copies, and the sentence naming it.

        The selected row when it is of that kind - "duplicate what I am looking at" is the
        common case, and it keeps this file's own conventions, its inert bookkeeping keys
        included - otherwise the last row of that kind in this layout, otherwise
        `reference_row` further up this module.
        """
        mine = self.rows_of(kind)
        if mine:
            i = self.index if self.index in mine else mine[-1]
            row = copy.deepcopy(self.widgets()[i])
            return row, f"a copy of row {i} of this layout (`{row.get('id')}`)"
        return reference_row(kind)

    def _new_id(self, kind: str) -> str:
        """An id in the spelling this file already uses, and unique inside it.

        The vendor's rows spell their ids as UUIDs; this repo's own exports spell them as
        `xigma-<theme>-<part>`.  Both are respected, because a user copy of `gauge` that
        suddenly carries a UUID next to `xigma-gauge-ring` reads like two files welded
        together.  Uniqueness is only a *soft* rule in `themes.validate`: the vendor's files
        reuse ids across themes - **152** rows in **27** files answering to **54** distinct
        ids, one id shared by **18** of those rows - so a row is keyed by theme and id,
        never by id alone.  The model obeys the soft rule anyway rather than collecting a
        warning on every add, and the suite re-counts those four digits from the files on
        each run.
        """
        ids = [str(w.get("id") or "") for w in self.widgets()]
        if ids and all(_UUID_ID.match(i) for i in ids):
            return str(uuid.uuid4())
        stem = (os.path.commonprefix(ids + [f"xigma-{self.name}"])
                or f"xigma-{self.name}").strip("-")
        n = 0
        while True:
            n += 1
            cand = f"{stem}-{kind}-{n}"
            if cand not in ids:
                return cand

    def _place(self, row: dict) -> tuple:
        """Where a copied row would sit without landing on another row's ink.

        Decided by the painter's own boxes, which is the only answer that can be right: a
        row's anchor does not mean the same thing for every kind and every `xigma.anchor`,
        so a trial draw reports the box this row *actually* paints at its copied position,
        and that box is then walked over the canvas, in `PLACE_STEP` px steps, to the
        nearest where it started.  A layout with no free room keeps the copied position and
        says so in words, because moving a row nobody asked to move is the silent repair
        this model refuses everywhere else - and the reader can drag it, which is what the
        canvas is for.

        Returns `((x, y), the sentence about where)`, or `(None, why it cannot be placed)`.
        """
        prop = (row.get("property") or [{}])[0]
        trial = copy.deepcopy(self.obj)
        widgets = trial.setdefault("osd", {}).setdefault("widget", [])
        widgets.append(copy.deepcopy(row))
        new_i = len(widgets) - 1
        _img, notes = themes.draw(trial, dict(FIXTURE), FIXTURE_WHEN)
        box = next((r[2] for r in (notes.get("boxes") or [])
                    if r[3] == new_i and r[2]), None)
        if box is None:
            skipped = [str(m) for m in (notes.get("missing") or [])]
            return None, (f"a copy of that row paints no box at this fixture"
                          f"{': ' + ', '.join(skipped) if skipped else ''}, so there is "
                          f"nothing to place")
        others = [r[2] for r in (notes.get("boxes") or []) if r[3] != new_i and r[2]]
        w, h = box[2] - box[0], box[3] - box[1]
        ox, oy = int(prop.get("x") or 0), int(prop.get("y") or 0)
        off_x, off_y = box[0] - ox, box[1] - oy
        cw = int(self.obj.get("width") or render.W)
        ch = int(self.obj.get("height") or render.H)
        inside = 0 <= box[0] and 0 <= box[1] and box[2] <= cw and box[3] <= ch
        if inside and not _overlaps(box, others):
            return (ox, oy), f"{w}x{h} px, where its source sits, clear of the rest"
        if w > cw or h > ch:
            # a `special` pair's box spans both figures, so it can be wider than the glass
            # itself (one of `alpha`'s is 608 px across a 480 px canvas).  There is no
            # anchor that puts such a box wholly inside, so the row stays where its source
            # sits and the sentence says why, rather than the scan inventing a spot whose
            # candidate would hang off the edge.
            return (ox, oy), (f"{w}x{h} px is bigger than the {cw}x{ch} canvas itself, so "
                              f"no anchor can seat it wholly inside: it stays where its "
                              f"source sits and you drag it")
        best, best_d = None, None
        for top in range(0, ch - h + 1, PLACE_STEP):
            for left in range(0, cw - w + 1, PLACE_STEP):
                cand = (left, top, left + w, top + h)
                if _overlaps(cand, others):
                    continue
                d = abs(left - box[0]) + abs(top - box[1])
                if best_d is None or d < best_d:
                    best, best_d = cand, d
        if best is None:
            return (ox, oy), (f"no free room on this {cw}x{ch} canvas for a {w}x{h} px box "
                              f"that meets none of the {len(others)} boxes already drawn, "
                              f"so it stays where its source sits and you drag it")
        return (best[0] - off_x, best[1] - off_y), (f"{w}x{h} px, moved to the nearest free "
                                                    f"spot clear of the {len(others)} boxes "
                                                    f"already drawn")

    def add_note(self, kind: str) -> str:
        """What `add_widget(kind)` would copy, in the same words it would say.

        The window puts this in the menu entry's tooltip, so a reader chooses knowing
        which row the new one comes from - and a kind with no row anywhere to copy is said
        so rather than offered.
        """
        return self._source_row(kind)[1]

    def add_widget(self, kind: str, name: str = "", at: int | None = None) -> tuple:
        """Insert one row of `kind`.  Returns `(ok, what_was_said)`; nothing moves unless
        the whole act is accepted, and the sentence says what was copied and where it went.

        Three things are asked before anything is written, and they are the library's own
        answers rather than a private list here.  `themes.validate` runs over the layout
        **with the new row in it**, so a hard problem (a `property` that is not the
        one-element list, no x/y) is refused before the row exists, and the soft ones (a
        size outside the ten the shipped library uses, a source it cannot answer, a family
        with no file here) come back in the sentence instead of being discovered later in the
        skip list.  And a `special` row without a name from `themes.SPECIALS` is refused
        outright, because a `special` nothing draws is not a thinner picture: the painter
        records `special:<name>` and skips the row.
        """
        if kind not in layout.KINDS:
            return False, (f"`{kind}` is not a kind this program draws; "
                           f"{', '.join(sorted(layout.KINDS))}")
        row, whence = self._source_row(kind)
        if row is None:
            return False, whence
        prop = (row.get("property") or [{}])[0]
        if kind == "special":
            want = str(name or "").strip()
            if want not in themes.SPECIALS:
                return False, (f"a `special` row has to name one of "
                               f"{', '.join(sorted(themes.SPECIALS))}: "
                               f"`{want or '(nothing)'}` is not a drawing this program "
                               f"has, so the painter would record `special:{want}` and "
                               f"put no ink on the glass")
            prop["name"] = want
        row["id"] = self._new_id(kind)
        spot, where = self._place(row)
        if spot is None:
            return False, where
        prop["x"], prop["y"] = int(spot[0]), int(spot[1])
        row["property"] = [prop]
        row.setdefault("type", kind)
        new_i = (len(self.widgets()) if at is None
                 else max(0, min(int(at), len(self.widgets()))))
        trial = copy.deepcopy(self.obj)
        twidgets = trial.setdefault("osd", {}).setdefault("widget", [])
        twidgets.insert(new_i, copy.deepcopy(row))
        hard, soft = themes.validate(trial)
        if hard:
            return False, "the layout with this row added would not draw: " + "; ".join(hard)
        self._step()
        self.widgets().insert(new_i, row)
        self.select(new_i)
        # And the answer is read back off the painter rather than trusted from the
        # arithmetic that placed it: the box this row actually paints at that anchor, and
        # whether it now meets another row's.  What the trial draw predicted and what the
        # layout does can differ by a pixel of supersampling, and a claim about the glass is
        # only worth what the glass was asked.
        _img, notes = themes.draw(self.obj, dict(FIXTURE), FIXTURE_WHEN)
        boxes = [r for r in (notes.get("boxes") or []) if r[2]]
        mine = next((r[2] for r in boxes if r[3] == new_i), None)
        note = (f"added a {kind} row `{row['id']}` at {prop['x']},{prop['y']}: {whence}, "
                f"{where}")
        if mine is None:
            skipped = ", ".join(str(m) for m in (notes.get("missing") or []))
            note += (f"  it paints no box at this fixture - the skip list says why "
                     f"({skipped or 'no note'})")
        else:
            meet = sorted(r[3] for r in boxes
                          if r[3] != new_i and _overlaps(mine, [r[2]]))
            note += (f"  it draws at {mine[0]},{mine[1]}..{mine[2]},{mine[3]} px, "
                     + (f"meeting row {' '.join(map(str, meet))} - drag it"
                        if meet else "clear of every other row"))
        if soft:
            note += "  said, not repaired: " + "; ".join(soft)
        return True, note

    def delete_widget(self, index: int | None = None) -> tuple:
        """Remove one row.  The last row of a layout cannot be removed.

        That is not a user-interface preference: `themes.validate` calls an `osd.widget` list
        with nothing in it a hard problem, so the model asks that same door what it would say
        and repeats its answer verbatim rather than paraphrasing the library.  The window
        keeps the control disabled instead of letting a reader find this at save time.
        """
        ws = self.widgets()
        i = self.index if index is None else int(index)
        if not 0 <= i < len(ws):
            return False, (f"row {i}: this layout has {len(ws)} rows "
                           f"(0..{len(ws) - 1})")
        if len(ws) == 1:
            probe = copy.deepcopy(self.obj)
            probe.setdefault("osd", {})["widget"] = []
            hard = themes.validate(probe)[0]
            return False, ("that is the only row in this layout, and emptying it is a hard "
                           "problem in `themes.validate`'s own words: " + "; ".join(hard) +
                           "  Add the row you mean to put here first.")
        was = self.label(i)
        self._step()
        row = ws.pop(i)
        self.index = min(i, len(ws) - 1)
        return True, (f"removed row {i}: {was} - the layout now has {len(ws)} rows, "
                      f"drawn in the same order as before without this one")

    def move_widget(self, delta: int, index: int | None = None) -> tuple:
        """Slide one row through the list, which *is* the draw order.

        `osd.widget` order is what the painter walks and what `hit` follows ("the later row
        wins an overlap"), so a reorder changes which of two overlapping rows is on top while
        moving no ink at all - and that is the half the suite proves with pixels rather than
        with an assert about list indices.  `layerIndex` is left exactly as it was: see
        `WIDGET_KEYS` above for what the vendor's own files say that key means.
        """
        ws = self.widgets()
        i = self.index if index is None else int(index)
        if not 0 <= i < len(ws):
            return False, f"row {i}: this layout has {len(ws)} rows"
        j = i + int(delta)
        if not 0 <= j < len(ws):
            return False, (f"row {i} is already the "
                           f"{'first drawn' if j < 0 else 'last drawn, so it paints on top'}"
                           f" of {len(ws)}")
        self._step()
        ws[i], ws[j] = ws[j], ws[i]
        self.index = j
        return True, (f"row {i} and row {j} swapped: the list is the draw order, so "
                      f"`{ws[j].get('id')}` is now under `{ws[i].get('id')}` where the two "
                      f"meet")

    # ------------------------------------------------------ resizing a row's box --
    #: Which keys an edge drag may write, per kind, and what each one *is* on the glass.
    #:
    #: Not a preference: this is what `layout.py` reads as an extent, and every line of it
    #: was measured against the painter before the door was written.  The suite re-checks the
    #: outer bound on every run - `themes.keys_read()` walks the painter's own source with
    #: `ast`, so a key nothing reads cannot be offered here - and re-measures the rest by
    #: drawing.  A figure that follows a face is printed per machine, not kept here.
    #:
    #:   `bar`    `width`, `height`.  The box *is* `(x, y, x+width, y+height)` for every
    #:            `bar` row the painter draws a box for - the suite asserts that as a rule,
    #:            and prints how many rows had a box to check this run, because a `Fan 3` or
    #:            `Fan 4` speed with no reading on this machine draws nothing and so has no
    #:            edge to grab.  `cornerRadius` moves the ink and not the box: of the rows
    #:            that carry one and draw one, pushing it +8 left every box where it was, so
    #:            no handle writes it.
    #:   `line`   `width`, `height`.  `layout.line_rect()` predicts the drawn box exactly,
    #:            4 rows out of 4, and this is the one kind whose resize can be decided
    #:            without drawing.  For a `rotate: 90` row the two swap - +8 px of `height`
    #:            is +8 px of box width - and the rect pivots about its own centre, so the
    #:            box's corner is not the declared rect's corner: `x`/`y` are corrected from
    #:            that same prediction and the sentence says they were.  When a row carries a
    #:            non-zero `lineWidth`, `draw_line` replaces the thickness with it, so the
    #:            drag writes `lineWidth` instead - no shipped file carries one, so the suite
    #:            builds that case rather than waiting for a file.
    #:   `arc`    `sizeWidth`, `sizeHeight`, and with them `radius` and `width`.  The box is
    #:            that band, while `radius` and the stroke's `width` move the ink inside it
    #:            and leave the box exactly where it was - measured on all 6 arc rows: +8 px
    #:            on `radius` moves the box 0 px and the picture by thousands of pixels - so
    #:            a drag scales the ring with its box.  It keeps the arithmetic every arc row
    #:            in the library obeys, `sizeWidth == 2*radius + 2*width`, and 6 of 6 are
    #:            square; a one-axis drag leaves a box that is not, and says so rather than
    #:            squaring it back.  Rounding the four keys independently breaks the
    #:            identity: `Theme_35`'s row comes out a pixel off at 1.25x, a ring that no
    #:            longer meets its own box.
    #:   `text`,  `fontSize` only.  No `text` or `data` row in the library carries `width` or
    #:   `data`   `height` at all - 145 rows, none with either - because the box is the ink
    #:            the face lays down: pushing the face +8 moves that box's width by an
    #:            amount that is never 8 px, differs from row to row, and belongs to this
    #:            machine's fonts - the suite measures the spread and prints it.
    #:            So the pane offers no side handles on those kinds, the drag searches faces
    #:            by drawing them, and the sentence names the box that *reached* instead of
    #:            claiming the edge followed the cursor.  A row fitted to `xigma.autoFitMax`
    #:            is the exception the sweep finds in `clock`: pushing its face moved that
    #:            box 0 px either way, because the cap owns the extent - said, and refused,
    #:            not written.
    #:   `special` by the door that draws it (`themes.special_door`).  On the `pair` and
    #:            `values` doors `width` is the pitch between the two figures' centres rather
    #:            than a box width - +8 px of it is +8 px of box, the origin moving -4 px
    #:            because the figures sit at `x +/- width/2` - and `fontSize` is a ceiling
    #:            that door reaches in some rows and not others; the `line` door takes the
    #:            text rule.  The two axes are different keys with different meanings, so a
    #:            corner drag is refused, and where `xigma.fitArc` or `xigma.autoFitMax` owns
    #:            the extent the face cannot move it: the refusal names whichever it is.
    SIZE_KEYS: dict = {
        "bar": ("width", "height"),
        "line": ("width", "height"),
        "arc": ("sizeWidth", "sizeHeight"),
        "text": ("fontSize",),
        "data": ("fontSize",),
    }
    #: The face sizes the `fontSize` search will try, and why they are bounded: `layout.
    #: font_for` builds a truetype face at `fontSize * SS`, and Pillow refuses a pixel size
    #: of 0 or of millions with an `OSError` from inside the frame loop.  10 is the floor the
    #: painter's own auto-fit loop stops at (`layout.draw_text`: `while size > 10 ...`), and
    #: 400 is four times the largest face any row in the library carries (140, in `clock`).
    MIN_FACE = 10
    MAX_FACE = 400

    #: The edges the pane puts a handle on.  A `special` row's two axes are different keys,
    #: so the corner entries are refused there rather than being a compromise.
    EDGES = ("right", "left", "bottom", "top",
             "bottom-right", "top-right", "bottom-left", "top-left")
    #: How far `size_edges` pushes an edge when it asks the door whether that edge is live.
    #: It is a question about the *rules*, so the distance only has to be big enough to tell
    #: a refusal from an acceptance: 8 px clears the 2 px floor and the rounding of an
    #: `arc`'s stroke, and no row's door is open at 8 px and shut at 9.
    EDGE_PROBE = 8

    def size_door(self, index: int | None = None) -> tuple:
        """`(keys, the sentence naming what each one is)` for one row's resize.

        `keys` is empty when this program cannot resize that row, and then the sentence is
        the reason - the same shape every other refusal in this model has.
        """
        w = self.selected() if index is None else self.widgets()[int(index)]
        kind = str(w.get("type") or "")
        prop = (w.get("property") or [{}])[0]
        if kind == "special":
            name = str(prop.get("name") or "")
            door = themes.special_door(name) if name in themes.SPECIALS else ""
            if door == "line":
                return ("fontSize",), (f"`{name}` is drawn through the line door, so its "
                                       f"extent is the face it sets: `fontSize`")
            if door in ("pair", "values"):
                return ("width", "fontSize"), (
                    f"`{name}` is a `{door}` row: `width` is the pitch between the two "
                    f"figures' centres, not a box width, and `fontSize` is a ceiling "
                    f"the door reaches only when the figures' own fit allows it")
            return (), (f"`{name or '(unnamed)'}` is not a drawing this program has, "
                        f"so there is no extent for a handle to write")
        if kind in self.SIZE_KEYS:
            keys = self.SIZE_KEYS[kind]
            if kind in ("text", "data"):
                return keys, ("a `text`/`data` row carries no `width` or `height` key: "
                              "the box is the ink its face lays down, so the size to "
                              "write is `fontSize`")
            if kind == "arc":
                return keys, ("an `arc`'s box is its `sizeWidth` x `sizeHeight` band, while "
                              "`radius` and `width` move the ring inside it, so the drag "
                              "scales the ring and keeps `sizeWidth == 2*radius + 2*width`")
            if kind == "line":
                return keys, ("a `line`'s box comes from `layout.line_rect`: `width` and "
                              "`height`, the axes swapped for a `rotate: 90` row, and "
                              "`lineWidth` replacing the thickness when the row carries one")
            return keys, ("a `bar`'s box is `x,y` to `x+width,y+height`, so its edges are "
                          "`width` and `height`")
        return (), f"`{kind or '(no type)'}` has no size key this program reads"

    def size_edges(self, index: int | None = None, box: tuple | None = None) -> tuple:
        """Which of `EDGES` give this row a handle, in the order `EDGES` lists them.

        Not a second table kept here: each of the eight is put through `_resize_plan` with a
        small push in both directions, and the ones that door refuses are the ones the pane
        paints no handle for.  So the squares on the glass and the model's own answer cannot
        drift apart, and a press somewhere other than a handle is a move - a visible act
        rather than a silent nothing.  Pass `box` when the caller already knows it (the pane
        does), because this is asked on every repaint and asking the painter again would be
        the slow way to agree.

        What it answers is whether an edge has *any* legal push of that size, not whether
        every distance is legal: a `special`'s bottom handle is live because its face does
        decide its height sometimes, and a particular drag can still be refused because that
        row's `xigma.fitArc` fit is what owns the extent.  The refusal on release says so.
        """
        i = self.index if index is None else int(index)
        if box is None:
            box = self._row_box(self.obj, i)
        out = []
        for edge in self.EDGES:
            dx = self.EDGE_PROBE if ("right" in edge or "left" in edge) else 0
            dy = self.EDGE_PROBE if ("top" in edge or "bottom" in edge) else 0
            for sign in (1, -1):
                if not self._resize_plan(dx * sign, dy * sign, edge, i, box)[5]:
                    out.append(edge)
                    break
        return tuple(out)

    def _row_box(self, obj: dict, index: int) -> tuple:
        """The box one row of `obj` paints, read off the painter rather than computed."""
        _img, notes = themes.draw(obj, dict(FIXTURE), FIXTURE_WHEN)
        for rec in (notes.get("boxes") or []):
            if rec[3] == index and rec[2]:
                return rec[2]
        return None

    def _skip_words(self, obj: dict) -> list:
        """The painter's own reasons for putting no ink on the glass."""
        return [str(m) for m in (themes.draw(obj, dict(FIXTURE), FIXTURE_WHEN)[1]
                                 .get("missing") or [])]

    def _font_for_height(self, row: dict, want: int) -> tuple:
        """The `fontSize` that puts a row's ink box nearest `want` px tall.

        A search, not a formula: the box comes from `draw.textbbox`, so the only answer that
        can be right is one that drew.  Bracket the target, then bisect - a dozen or so solo
        draws - and return the box that reached beside the size, because a face is stepped by
        the font and the box that reaches is rarely the box that was asked for.
        `(None, None, the reason)` covers the two cases the door has to refuse: a row that
        paints no box, and a row whose box does not answer its face at all because
        `xigma.autoFitMax` fits it to a width.
        """
        now = int((row.get("property") or [{}])[0].get("fontSize") or 12)

        def probe(size):
            t = copy.deepcopy(row)
            tp = (t.get("property") or [{}])[0]
            tp["fontSize"] = int(size)
            return self._row_box({"width": render.W, "height": render.H,
                                  "osd": {"widget": [t]}}, 0)

        base = probe(now)
        if base is None:
            return None, None, ("that row paints no box at this fixture, so it has no "
                                "height for a face to be chosen against")
        h0 = base[3] - base[1]
        bigger = want > h0
        lo, hi, step = now, now, 4
        boxed = False
        for _ in range(20):
            hi = min(self.MAX_FACE, max(self.MIN_FACE, hi + step if bigger else hi - step))
            edge_box = probe(hi)
            if edge_box is None:
                break
            h = edge_box[3] - edge_box[1]
            if (h >= want) if bigger else (h <= want):
                boxed = True
                break
            if h == h0:
                return None, None, ("pushing `fontSize` did not move this row's box at "
                                    "all, so some other key owns its extent")
            step *= 2
            if hi == self.MAX_FACE or hi <= self.MIN_FACE:
                break
        if not boxed:
            return None, None, ("no face in the search reached that height: something "
                                "other than `fontSize` decides this row's extent")
        a, b = (lo, hi) if lo < hi else (hi, lo)
        if bigger:
            a, b = now, hi
        box_a, box_b = probe(a), probe(b)
        for _ in range(20):
            if b - a <= 1:
                break
            mid = (a + b) // 2
            box_m = probe(mid)
            if box_m is None:
                b, box_b = mid - 1, probe(b)
                continue
            if (box_m[3] - box_m[1]) >= want:
                b, box_b = mid, box_m
            else:
                a, box_a = mid, box_m
        nearer = (b, box_b) if (box_a and box_b
                                and abs((box_b[3] - box_b[1]) - want)
                                <= abs((box_a[3] - box_a[1]) - want)) else (a, box_a)
        return nearer[0], nearer[1], ""

    def _resize_plan(self, dx: int, dy: int, edge: str, index: int | None = None,
                     box: tuple | None = None) -> tuple:
        """Everything one resize drag decides before it writes a key or searches a face.

        `(row index, kind, its `property`, the box it paints now, the box the drag asks
        for, "")` when the ask is legal, and `(i, kind, prop, box, None, the reason)` when
        it is not.

        This is split out for one reason: the pane draws the box the release would ask for
        while the drag is still in flight, and a second copy of this arithmetic in
        `app.py` would be a second rule free to drift from the first.  So the window asks
        this door and paints its answer.  `box` lets a caller that already knows the box -
        the window does, it is the one the last paint reported in `_ed_notes` - skip asking
        the painter again on every mouse-move event, which is the slow way of agreeing.
        """
        ws = self.widgets()
        i = self.index if index is None else int(index)
        if not 0 <= i < len(ws):
            return i, "", {}, None, None, f"row {i}: this layout has {len(ws)} rows"
        if edge not in self.EDGES:
            return i, "", {}, None, None, (
                f"`{edge}` is not an edge this pane puts a handle on: "
                f"{', '.join(self.EDGES)}")
        row = ws[i]
        prop = (row.get("property") or [{}])[0]
        kind = str(row.get("type") or "")
        keys, why = self.size_door(i)
        if not keys:
            return i, kind, prop, None, None, f"row {i}: {why}"
        if box is None:
            box = self._row_box(self.obj, i)
        if box is None:
            skipped = self._skip_words(self.obj)
            return i, kind, prop, None, None, (
                f"row {i} paints no box at this fixture"
                f"{': ' + ', '.join(skipped) if skipped else ''}, so it has no edge to drag")
        x0, y0, x1, y1 = box
        cw = int(self.obj.get("width") or render.W)
        ch = int(self.obj.get("height") or render.H)
        hx = int(dx) if ("right" in edge or "left" in edge) else 0
        vy = int(dy) if ("top" in edge or "bottom" in edge) else 0

        if kind in ("text", "data") and not vy:
            cap = int(((prop.get("xigma") or {}).get("autoFitMax")) or 0)
            return i, kind, prop, box, None, (
                f"row {i}: a `text`/`data` row owns no width, so a side-to-side drag "
                f"writes nothing.  Its box is {x1 - x0}x{y1 - y0} px of ink"
                + (f", fitted to `xigma.autoFitMax` {cap} px" if cap else "")
                + "; its face is the size, and that is a top/bottom drag")
        if kind == "special":
            if hx and vy:
                return i, kind, prop, box, None, (
                    f"row {i}: a `{str(prop.get('name') or '')}` row's two axes are "
                    f"different keys - `width` is the pitch between the figures, "
                    f"`fontSize` their face - so a corner drag has no meaning here; drag "
                    f"one axis at a time")
            if not hx and not vy:
                return i, kind, prop, box, None, (
                    f"row {i}: that drag asks for no change on either axis")

        nb = [x0, y0, x1, y1]
        if "left" in edge:
            nb[0] += hx
        if "right" in edge:
            nb[2] += hx
        if "top" in edge:
            nb[1] += vy
        if "bottom" in edge:
            nb[3] += vy
        if nb[2] - nb[0] < 2 or nb[3] - nb[1] < 2:
            return i, kind, prop, box, None, (
                f"row {i}: that leaves a {nb[2] - nb[0]}x{nb[3] - nb[1]} px box, and a "
                f"row that small is not a row")
        if not (0 <= nb[0] and 0 <= nb[1] and nb[2] <= cw and nb[3] <= ch):
            was_off = not (0 <= x0 and 0 <= y0 and x1 <= cw and y1 <= ch)
            return i, kind, prop, box, None, (
                f"row {i}: "
                + (f"its box is already off the {cw}x{ch} glass at {x0},{y0}..{x1},{y1}, "
                   f"and this drag does not bring it back "
                   f"({nb[0]},{nb[1]}..{nb[2]},{nb[3]}), so nothing is written - drag the "
                   f"row inside first" if was_off else
                   f"that puts the box at {nb[0]},{nb[1]}..{nb[2]},{nb[3]}, off the "
                   f"{cw}x{ch} canvas, so nothing is written")
                + f". The room from here: left {x0} px, top {y0} px, right {cw - x1} px, "
                f"bottom {ch - y1} px")
        return i, kind, prop, box, tuple(nb), ""

    def resize_box(self, dx: int, dy: int, edge: str = "bottom-right",
                   index: int | None = None, box: tuple | None = None) -> tuple:
        """The box a drag of `(dx, dy)` on `edge` is asking for, or the reason it cannot.

        `(box, "")` or `(None, the sentence)`.  This is the door the pane uses while the
        mouse is still down: it paints that box in a solid line next to the dashed one the
        row has, so what is being promised is visible before anything is written.  It
        decides nothing about the file - no key is chosen, no face searched, no step taken -
        which is why it can run on every mouse-move event without drawing.
        """
        _i, _kind, _prop, _had, nb, bad = self._resize_plan(dx, dy, edge, index, box)
        return (None, bad) if bad else (nb, "")

    def resize_row(self, dx: int, dy: int, edge: str = "bottom-right",
                   index: int | None = None) -> tuple:
        """Grow or shrink one row's box.  Returns `(ok, what_was_said)`; one act, one step.

        The drag's ask is settled first by `_resize_plan` - every refusal that needs no
        drawing, in its words - and what is left here is the part that knows the kind: the
        keys *that kind* owns (`SIZE_KEYS` above) are what gets written, and the answer
        quotes the box the painter reports afterwards instead of the arithmetic that got
        there.  The refusals left in this half write nothing and take no undo step: a face
        that would not move the box, a `special` whose figures' pitch cannot go negative, an
        `arc` whose stroke would leave no hole, and a `line` whose declared keys cannot come
        out at the extent asked for.  A `line` is the one kind decided without drawing -
        `layout.line_rect` is pure arithmetic and predicts the drawn box exactly - and where
        its pivot or its `lineWidth` centring puts the box somewhere other than the drag's,
        `x`/`y` are corrected from that prediction and the sentence says so.
        """
        i, kind, prop, box, nb, bad = self._resize_plan(dx, dy, edge, index)
        if bad:
            return False, bad
        x0, y0, x1, y1 = box
        row = self.widgets()[i]
        hx = int(dx) if ("right" in edge or "left" in edge) else 0
        vy = int(dy) if ("top" in edge or "bottom" in edge) else 0
        keys, why = self.size_door(i)
        rot90 = kind == "line" and int(prop.get("rotate") or 0) % 180 == 90

        wrote: dict = {}
        said: list = []
        all_wrote: dict = {}
        face = (kind in ("text", "data")
                or (kind == "special" and "fontSize" in keys and not hx))
        if face:
            want = nb[3] - nb[1]
            size, got, bad = self._font_for_height(row, want)
            if bad:
                owner = ("`xigma.fitArc` is the ring the figures are fitted into"
                         if (kind == "special" and themes.special_door(
                                 str(prop.get("name") or "")) == "values")
                         else "`xigma.autoFitMax` fits it to a width")
                return False, f"row {i}: {bad} - {owner}, and that is the row to change"
            now = int(prop.get("fontSize") or 12)
            if size == now:
                return False, (f"row {i}: `fontSize` {now} already puts the box nearest "
                               f"{want} px tall ({got[2] - got[0]}x{got[3] - got[1]} px), "
                               f"so that drag would write a value the row already has")
            wrote["fontSize"] = all_wrote["fontSize"] = size
            said.append(f"the face went {now} -> {size} and the box reached "
                        f"{got[2] - got[0]}x{got[3] - got[1]} px against the "
                        f"{nb[2] - nb[0]}x{want} px the drag asked for; a text row's "
                        f"extent is the ink its face lays down")
            if hx and kind != "special":
                said.append("the width the drag asked for is not a key this row owns")
        elif kind == "arc":
            sw, sh = nb[2] - nb[0], nb[3] - nb[1]
            r0, th0 = int(prop.get("radius") or 0), int(prop.get("width") or 0)
            base = int(prop.get("sizeWidth") or (2 * r0 + 2 * th0)) or 1
            thick = max(1, int(round(th0 * sw / base)))
            inner = sw - 2 * thick
            if inner <= 0:
                return False, (f"row {i}: a {sw} px band with a {thick} px stroke leaves no "
                               f"hole: that row's rule is `sizeWidth == 2*radius + 2*width` "
                               f"and the radius it needs would be {inner} px")
            sq = int(prop.get("sizeWidth") or 0) == int(prop.get("sizeHeight") or 0)
            if sw != sh and sq:
                said.append(f"the box is no longer square ({sw}x{sh}); all 6 arc rows in "
                            f"this library are, and nothing here quietly repairs that")
            if "left" in edge:
                wrote["x"] = all_wrote["x"] = int(prop.get("x") or 0) + hx
            if "top" in edge:
                wrote["y"] = all_wrote["y"] = int(prop.get("y") or 0) + vy
            wrote.update({"sizeWidth": sw, "sizeHeight": sh, "radius": inner // 2,
                          "width": thick})
            all_wrote.update(wrote)
            said.append(f"the ring scales with its box: `radius` {r0} -> {inner // 2}, "
                        f"stroke `width` {th0} -> {thick}, so 2*radius + 2*width is "
                        f"still {sw}")
        elif kind == "line":
            # `layout.line_rect` is pure arithmetic - it predicts the drawn box exactly,
            # measured on 4 rows out of 4 - so a `line` is the one kind whose resize can be
            # decided without drawing.  The box's two extents come from different declared
            # keys depending on the row's own `rotate`, and the corner of the declared rect
            # is *not* the corner of the box when the row is rotated (the rect pivots about
            # its own centre) or when `lineWidth` recentres the thickness: so `x`/`y` are
            # corrected from the prediction, and the sentence says that they were.
            lw = int(prop.get("lineWidth") or 0)
            prop_h = int(prop.get("height") or 2)
            box_w, box_h = nb[2] - nb[0], nb[3] - nb[1]
            wrote["height" if rot90 else "width"] = max(1, box_w)
            thick_key = "lineWidth" if (lw and lw != prop_h) else (
                "width" if rot90 else "height")
            wrote[thick_key] = max(1, box_h)
            if lw and thick_key == "lineWidth":
                said.append(f"the row carries `lineWidth` {lw} and `draw_line` replaces "
                            f"the declared thickness with it, centred on the rect's middle "
                            f"line, so that is what was written")
            probe_p = dict(prop)
            probe_p.update({k: v for k, v in wrote.items() if k in ("width", "height",
                                                                   "lineWidth")})
            px0, py0, pw, ph = layout.line_rect(probe_p)
            if (pw, ph) != (box_w, box_h):
                return False, (f"row {i}: the keys this row's rules offer come out "
                               f"{pw}x{ph} px, not the {box_w}x{box_h} px the drag asked "
                               f"for, so nothing is written")
            if (px0, py0) != (nb[0], nb[1]):
                wrote["x"] = int(prop.get("x") or 0) + (nb[0] - px0)
                wrote["y"] = int(prop.get("y") or 0) + (nb[1] - py0)
                said.append("the declared rect's corner is not this box's corner, so "
                            f"`x`/`y` were set from `line_rect` to put the box at "
                            f"{nb[0]},{nb[1]} where the drag left it")
            if rot90:
                said.append(f"`rotate: {int(prop.get('rotate') or 0)}` turns the rect about "
                            f"its own centre, so the box's horizontal extent is `height` on "
                            f"this row")
        elif kind == "bar":
            wrote["width"] = all_wrote["width"] = max(1, nb[2] - nb[0])
            wrote["height"] = all_wrote["height"] = max(1, nb[3] - nb[1])
            if "left" in edge:
                wrote["x"] = int(prop.get("x") or 0) + hx
            if "top" in edge:
                wrote["y"] = int(prop.get("y") or 0) + vy
        elif kind == "special" and "width" in keys:
            pitch = int(prop.get("width") or 0) + ((nb[2] - nb[0]) - (x1 - x0))
            if pitch < 0:
                return False, (f"row {i}: the pitch between the two figures cannot be "
                               f"negative ({pitch}); `width` is their centres' distance and "
                               f"a negative one swaps them")
            wrote["width"] = all_wrote["width"] = pitch
            said.append(f"`width` is the pitch between the figures' centres: "
                        f"{int(prop.get('width') or 0)} -> {pitch}, each figure moving "
                        f"{((nb[2] - nb[0]) - (x1 - x0)) // 2} px outward")
        for key in list(wrote):
            if str(prop.get(key)) == str(wrote[key]):
                del wrote[key]
        if not wrote:
            return False, (f"row {i}: that drag leaves "
                           + ", ".join(f"`{k}` {prop.get(k)}" for k in sorted(keys))
                           + ", which is what the row already has")
        unwritten = sorted(k for k in set(all_wrote) - set(wrote)
                           if str(prop.get(k)) == str(all_wrote[k]))
        if unwritten:
            said.append("left unwritten because the row already holds them: "
                        + ", ".join(f"`{k}` {prop.get(k)}" for k in unwritten))
        if not wrote:
            return False, f"row {i}: {why}, and this drag asks for none of those keys"

        # the library's answer first: a key that field's own rule refuses is refused here, in
        # that rule's words, before a step is taken or a byte is written
        self.select(i)
        ext = set(extension_fields(kind))
        for key, val in sorted(wrote.items()):
            bad = self._check(kind, key, val, ext)
            if bad:
                return False, (f"row {i}: `{key}` = {val} is refused by that field's "
                               f"own rule: {bad}")

        # one act, one undo step: close any field run still open (so a resize cannot be
        # swallowed by a keystroke that was mid-drag), then let these writes form the run
        # that `commit` turns into a single step.
        self.commit()
        soft = []
        for key, val in sorted(wrote.items()):
            good, note = self.set(key, val, commit=False)
            if not good:
                return False, f"row {i}: the model refused `{key}` after all: {note}"
            if note:
                soft.append(note)
        self.commit()
        after = self._row_box(self.obj, i)
        moved = ""
        if after:
            edges = [("left", x0, after[0]), ("top", y0, after[1]),
                     ("right", x1, after[2]), ("bottom", y1, after[3])]
            moved = ("  the edges that moved: "
                     + ", ".join(f"{n} {a}->{b}" for n, a, b in edges if b != a))
        return True, (f"resized row {i} ({kind}) with a {edge} drag of {dx},{dy}: wrote "
                      + ", ".join(f"`{k}` {v}" for k, v in sorted(wrote.items()))
                      + f"; the box went {x0},{y0}..{x1},{y1} -> "
                      + (f"{after[0]},{after[1]}..{after[2]},{after[3]}" if after
                         else "nothing at all")
                      + ".  " + "; ".join(said) + moved
                      + ("  said, not repaired: " + "; ".join(soft) if soft else ""))

    def commit(self) -> None:
        """End a coalesced run of writes: a spinbox settling, one drag, one nudge.

        `set(commit=False)` applies a change without promising an undo step for it, and
        this is where the promise is made - once for the run, not once per keystroke.  A
        run that ends where it began writes no step: a row dragged out and back, or a
        spinbox typed `3` -> `30` -> `3`, is not a change anyone can undo, and the history
        would otherwise hold a press of undo that visibly does nothing.
        """
        if self._pending is not None:
            if self._pending != self.obj:
                self.history.append(self._pending)
                if len(self.history) > 60:
                    del self.history[0]
            self._pending = None

    # -------------------------------------------------------------- values --
    def value(self, field: str):
        """What one field currently holds (extension keys included, `None` if unset)."""
        if field in ("x", "y") or field in field_names(self.selected().get("type", "")):
            return self.prop().get(field)
        return (self.prop().get("xigma") or {}).get(field)

    def set(self, field: str, value, commit: bool = True) -> tuple:
        """Set one field.  Returns (ok, what_was_said): the second half is empty when
        the value went in exactly as written, and a sentence when it was rewritten (a
        colour converted to `rgba()`, or a family folded to the spelling `layout.FONTS`
        carries) or when the write was refused and nothing moved.  The window prints it,
        which is how a reader finds out that `#ff4040` became
        `rgba(255, 64, 64, 1)` without opening a diff.

        `commit=False` is a keystroke in a spinbox: the change is applied and the
        picture moves, but the undo step is not written until the field settles, so a
        run of keystrokes is one undo rather than one per press.  That is the
        coalescing the plan asked for, and it is why the history holds whole layouts:
        the unit a reader wants back is the state before they started typing.
        """
        kind = str(self.selected().get("type") or "")
        ext = set(extension_fields(kind))
        if field in ext:
            holder = self.prop().setdefault("xigma", {})
        elif field in field_names(kind):
            holder = self.prop()
        else:
            return False, (f"a {kind or '?'} widget does not carry {field!r}; this row "
                           f"offers {', '.join(field_names(kind)) or 'nothing'}")
        bad = self._check(kind, field, value, ext)
        if bad:
            return False, bad
        note = ""
        if field in COLOUR_FIELDS:
            text, bad = colour_text(value)
            if bad:
                return False, bad
            if text != value:
                note = f"stored as {text}"
            value = text
        if field in CASE_FOLDED_FIELDS and isinstance(value, str):
            # the painter's fold, applied once and said out loud: the row keeps a family
            # name `layout.FONTS` actually carries, and the reader is told the picture did
            # not move (the suite checks that, pixel by pixel, for a vendor row that writes
            # the capitalised spelling).
            _choice = choices(field)
            if value not in _choice:
                canon = next((c for c in _choice if isinstance(c, str)
                              and c.lower() == value.lower()), None)
                if canon is not None:
                    wrote, value = value, canon
                    note = (f"`{canon}` stored in place of `{wrote}`: the painter "
                            f"lowercases `{field}` before resolving it, so this is the "
                            f"same face and the row now names it the way `layout.FONTS` "
                            f"spells it")
        if self._pending is None:
            self._pending = copy.deepcopy(self.obj)
        if field in ("x", "y") and value is not None:
            value = int(value)
        elif field in number_fields() and value is not None:
            # every one of these is an integer in all 27 vendor files, so an editor that
            # typed 30 and stored "30" or 30.0 would make the saved file differ from the
            # source in a way the reader never asked for.  A deliberate fraction stays a
            # fraction (a maxValue of 2.5 is a legal scale end, just not one shipped).
            number = float(value)
            value = int(number) if number.is_integer() else number
        if field in ext and value is None:
            holder.pop(field, None)            # un-setting an extension key is a value
            if not holder:
                self.prop().pop("xigma", None)  # an empty `xigma` is a wart, not a value
        else:
            holder[field] = value
        if commit:
            self.commit()
        return True, note

    def _check(self, kind: str, field: str, value, ext: set) -> str:
        """Refuse, in words, what the painter would otherwise have to guess at.

        The refusals are the point of the model: every one of them is a case where
        `layout.py` would have to choose something, and a choice made in silence by a
        painter is how a layout ends up drawing something its author did not write.
        """
        if value is None:
            # un-setting is only ever meaningful for one of our own extension keys:
            # its absence *is* a value there (`no arcPaint` = the vendor's convention).
            # A vendor key has no unset - `fontSize: null` is not "the default size".
            return "" if field in ext else (
                f"{field} cannot be left out of a {kind} widget: only this program's "
                f"own keys ({', '.join(sorted(ext))}) mean anything by an absent value")
        if field == "bold":
            if not isinstance(value, bool):
                return f"bold is a checkbox, not {value!r}"
        else:
            choice = choices(field)
            if choice and value not in choice:
                if field in CASE_FOLDED_FIELDS and any(
                        isinstance(c, str) and c.lower() == str(value).lower()
                        for c in choice):
                    # the same value the file already holds, spelled the file's way.  The
                    # menu offers it, the painter resolves it, and `set` says which
                    # spelling ends up in the file.
                    return ""
                return f"{field} takes one of: {' '.join(map(str, choice))}"
        if field in number_fields():
            try:
                float(value)
            except (TypeError, ValueError):
                return f"{field} is a number, not {value!r}"
        if field in ("x", "y"):
            w = int(self.obj.get("width") or render.W)
            h = int(self.obj.get("height") or render.H)
            if not 0 <= int(value) < (w if field == "x" else h):
                return (f"{field} must stay inside the {w}x{h} canvas this layout "
                        f"declares - a widget off the glass cannot be shown here")
        if field == "format":
            # `xigma.format` goes straight into `layout.text_for`, which hands it to
            # `strftime` for a clock and to `format()` for a reading.  Either door raises
            # on a specifier that does not fit the value behind it - `%q` and `{:.1f}` on
            # an int are the two that showed up while wiring the note line - and a format
            # the painter cannot apply is worse than an out-of-range number: `layout.draw`
            # catches what it expects (`KeyError`) and nothing else, so a file carrying one
            # does not draw a wrong figure, it stops the frame loop.  So the row tries the
            # value this widget would actually be given.  If the source answers at this
            # fixture that is its reading; if it does not, the probe is the clock instant
            # for a clock source and a plain number for every other, which is what
            # `themes.SOURCES` says the name means.  A refusal always names the probe.
            return self._format_fits(value)
        return ""

    def _format_fits(self, fmt) -> str:
        """Can `xigma.format` be applied to the value this row's `source` carries?"""
        if not isinstance(fmt, str):
            return f"format is a string of strftime or format() specifiers, not {fmt!r}"
        prop = self.prop()
        src = str(prop.get("source") or "")
        if not src:
            return (f"this row has no `source` to format: a `text` row paints its "
                    f"`content` exactly as written, so `format` would do nothing")
        vals, absent = themes.values(*self.fixture())
        if src in vals:
            probe, whence = vals[src], f"the reading this fixture gives for `{src}`"
        elif src in themes.CLOCKED or src in ("Time", "Date"):
            probe, whence = self.fixture()[1], f"the clock (`{src}`)"
        else:
            probe, whence = 1234.0, f"a number (no reading for `{src}` here)"
        try:
            got = layout.text_for(src, probe, fmt)
        except KeyError:
            return (f"`{src}` has no shape this program knows, so a `format` is the only "
                    f"way to spell it - and `{fmt}` cannot be applied to {whence}")
        except (ValueError, TypeError) as exc:
            hint = ""
            if fmt.startswith("{"):
                # the shape people reach for is `str.format`'s, and this field is
                # `format(value, X)`: the braces are already there.  Pointing at the
                # spelling this one takes is only worth doing when the pointer has been
                # checked on the same value - advice that also raises is worse than no
                # advice - and an empty suggestion ("no format at all") is not advice a
                # reader can act on, so it is not offered.
                _inner = fmt[1:]
                if _inner.startswith(":"):
                    _inner = _inner[1:]
                _inner = _inner.rstrip("}")
                if _inner:
                    try:
                        layout.text_for(src, probe, _inner)
                        hint = (" - this field is `format(value, X)`, so the braces are "
                                f"already implied: `{_inner}` works")
                    except Exception:
                        hint = (" - this field is `format(value, X)`, not `str.format`, "
                                "so the braces are already implied")
                else:
                    hint = (" - this field is `format(value, X)`, not `str.format`: the "
                            "braces are already implied, and what is between them has to "
                            "be a presentation type (`,.0f`, `.1f`, `d`); leaving the field "
                            "empty means the shape this program already spells")
            return (f"`{fmt}` cannot be applied to {whence} ({exc}); `layout.text_for` "
                    f"would raise on it, and the frame loop would stop{hint}")
        return "" if got else f"`{fmt}` spells nothing for {whence}"

    # ---------------------------------------------------------------- undo --
    def undo(self) -> bool:
        """One step back, preferring the run in progress to the older history.

        While a spinbox is mid-drag there are two states that are not the reader's
        starting point.  Undo discards the run in progress and leaves the committed
        history alone, so one press always returns to something they had agreed to
        see, and a second press goes back a whole edit rather than a keystroke.
        """
        if self._pending is not None:
            self.obj, self._pending = self._pending, None
        elif self.history:
            self.obj = self.history.pop()
        else:
            return False
        self.index = min(self.index, max(0, len(self.widgets()) - 1))
        return True

    @property
    def steps(self) -> int:
        return len(self.history)

    # -------------------------------------------------------------- render --
    def paint(self, metrics: dict | None = None, when: datetime.datetime | None = None,
              scrim: int = 0, ink=None) -> tuple:
        """The layout as the loop would draw it.  Same door as `--check-theme`.

        `ink` is the window's text colour, and it is honoured **only while this editor
        holds a generated layout** - one of the five names this repo draws from code.  It
        goes in by copying the object and moving its glyph colours
        (`themes.with_ink`), never by editing `self.obj`: the file a save would write
        keeps its own colours, and a reader's colour choice is a property of this view.
        A vendored or user-saved layout ignores the argument, which is the rule that
        theme's file already states about itself.  `self.ink_note` carries what happened,
        for the caption under the picture.
        """
        obj, self.ink_note = ((themes.with_ink(self.obj, self.theme, ink)
                               if self.theme else (self.obj, ""))
                              if ink is not None else (self.obj, ""))
        return themes.draw(obj, metrics or {}, when, scrim=scrim)

    def fixture(self) -> tuple:
        """The metrics and the instant this editor draws with - always the same pair.

        There is deliberately no live-readings door here yet: an edit shown against
        sensors that move underneath it cannot be judged, and every byte-for-byte
        comparison in the gates (the frame before an edit, the frame after, the frame
        read back off disk) only means anything because the instant is fixed.  Showing
        this machine's readings is stage 4's own next step, listed as unbuilt in
        docs/theme-editor.md rather than half-offered by a flag nothing exercises.
        """
        return dict(FIXTURE), FIXTURE_WHEN

    def fixture_line(self) -> str:
        vals, absent = themes.values(*self.fixture())
        return (f"fixture: {', '.join(f'{k} {v}' for k, v in sorted(vals.items()))}"
                + (f"  (no reading for {', '.join(sorted(absent))})" if absent else ""))

    # ----------------------------------------------------- what a row paints --
    def drawn_text(self, metrics: dict | None = None,
                   when: datetime.datetime | None = None) -> tuple:
        """What the selected row paints as a line of text, and what is said beside it.

        Returns `(string, sentence)`.  The string is `None` when the row paints nothing,
        and then the sentence is the reason; when a string is painted the sentence is
        empty - unless the string came from a shape nobody measured off the vendor's
        picture, in which case it says so.  "Say what you cannot do, and say what you
        guessed" is the same rule the painter follows in `notes["missing"]` and
        `notes["gaps"]`, and this is the half a reader can act on: the `content`,
        `format`, `source`, `fontFamily` and `xigma.showIf` rows all change this line.

        It is deliberately not a second renderer.  Every rule here is the painter's own,
        read in the order `layout.draw` applies them - a `xigma.showIf` the readings
        cannot satisfy takes the row out before its own source is ever asked; an
        unanswered source skips it; `layout.text_for` is the only formatting door and a
        format the value cannot be dressed in skips it; and the face is asked last,
        because a row with a correct string and a family this box cannot open draws
        nothing either - which is also what a row with *no* `fontFamily` at all does,
        since there is no default face to fall back to - and the claim that this *is* the
        painted line is proved by painting, not by agreement between two pieces of code:
        for every text-bearing row of the 28 layouts this editor opens, the suite draws
        the file, then draws a copy of the file with that one row replaced by a literal
        `text` widget whose `content` is the string returned here, and requires the two
        frames to be byte-identical.  145 rows in 28 layouts, 132 of them painting a line
        at this fixture on the author's bench - 131 on CI's runner, whose fonts have no CJK
        face for `simsun` to resolve - with 0 pixels of difference between the two doors, in
        1.5 s.
        """
        kind = str(self.selected().get("type") or "")
        if kind not in ("text", "data"):
            return None, _NOT_A_LINE.get(
                kind, f"a `{kind}` row paints no line of text")
        prop = self.prop()
        if metrics is None:
            metrics, when = self.fixture()
        vals, absent = themes.values(metrics, when)
        ext = prop.get("xigma") or {}
        shown_if = ext.get("showIf")
        if shown_if and shown_if not in vals:
            return None, (f"its `xigma.showIf` is `{shown_if}`, and these readings do "
                          f"not answer it: the row is skipped")
        src = prop.get("source")
        if kind == "data" and src not in vals:
            return None, (f"no reading for `{src}` on this machine: the row is skipped"
                          if src in absent else
                          f"`{src}` is not a source name this program can answer")
        if kind == "text":
            line, caveat = str(prop.get("content") or ""), ""
        else:
            try:
                line = layout.text_for(src, vals[src], ext.get("format"))
            except KeyError:
                return None, f"`{src}` has no shape this program knows how to spell"
            except (ValueError, TypeError) as exc:
                # the painter's own answer, in the painter's own words: a `format` the
                # value cannot be dressed in is a row that draws nothing, reported and not
                # raised (`layout.draw` records `format:<source>` in `missing`).  The row
                # should not have been saved with it - `edit.Editor._format_fits` refuses
                # one on the way in - so reaching this line means the file came from
                # somewhere else.
                return None, (f"its `format` {ext.get('format')!r} cannot be applied to "
                              f"`{src}` ({exc}): the painter skips the row and says so")
            caveat = ("" if src in layout.FORMATS_MEASURED or ext.get("format") else
                      f"`{src}` is spelled by `layout.VENDOR_FORMAT`, which is not one of "
                      f"the {len(layout.FORMATS_MEASURED)} shapes measured off the "
                      f"vendor's picture - `--check-theme` reports it as a gap, and a "
                      f"`format` here is how you settle it")
        # last, as the painter checks it last: the face.  A row with a correct string and a
        # family nothing here can open still draws nothing, so the string is not worth
        # reporting until the face has been asked about.
        face, fam, _path = layout.font_for(prop)
        if face is None:
            if not str(prop.get("fontFamily") or "").strip():
                # the other way to have no face: the key is simply not in the file.  There
                # is no default to fall back to - `layout.draw` notes `font:` with an empty
                # name and skips the row - so this is a row that draws nothing, and a
                # reader who has just cleared a family needs to be told that out loud.
                return None, ("the file carries no `fontFamily`, and there is no default "
                              "face to fall back to: the painter notes `font:` and skips "
                              "the row, so it puts no ink on the glass")
            return None, (f"this box has no file for the family `{fam}`, so the row "
                          f"draws nothing - the vendor's names are not fonts")
        return line, caveat

    def face_here(self) -> tuple:
        """What family the selected row asked for, and the file this box has for it.

        `(family, path_or_None, bold)`, answered by `layout.font_for` - the loader the
        painter itself uses, at the row's own size and weight.  It matters more than a
        label: when a family resolves to nothing, `layout.draw` records `font:<family>`
        in `notes["missing"]` and the row is skipped - no ink at all - so an unresolvable
        family is a row that quietly vanishes from the frame.
        """
        face, fam, path = layout.font_for(self.prop())
        return fam, path, bool(self.prop().get("bold"))

    def faces_here(self) -> dict:
        """Every family the editor offers, answered with the file this box has for it.

        `family -> path`, `None` where nothing matches.  The five names come from
        `choices("fontFamily")`, which is `layout.FONTS`' own vocabulary, and each is
        resolved through `layout.font_for` at the selected row's size and weight, so the
        two facts the window needs - which entries are dim because this box has no such
        file, and which names are the *same face* spelled differently - are read off the
        painter's table rather than remembered here.  On a box with only DejaVu and
        Liberation installed that is worth saying out loud: `verdana` and `dejavu` land
        on one file, `simsun` and `宋体` on another, and `arial` on Liberation, which is a
        metric-compatible stand-in and not the vendor's font.
        """
        prop = dict(self.prop())
        fams = list(choices("fontFamily"))
        own = str(prop.get("fontFamily") or "")
        if own and own not in fams:
            fams.append(own)        # a file can name a family the vocabulary does not
        return {fam: layout.font_for({**prop, "fontFamily": fam})[2] for fam in fams}


#: Why a row that is not a line of text cannot have one.  Said per kind, because "no"
#: that names the reason is the difference between an editor and a form: an `arc` row is
#: not missing a string, it is a sweep, and the keys that decide it are named in the rows
#: above this one.
_NOT_A_LINE = {
    "bar": "a `bar` row paints a meter: `minValue`/`maxValue` and the fill colour decide "
           "it, and its figure is a separate `data`/`text` row",
    "arc": "an `arc` row paints a sweep: `startAngle`/`endAngle` (or `minValue`/"
           "`maxValue`) and a paint convention, never a line of text",
    "line": "a `line` row paints a rule - width, colour and two points",
    "special": "a `special` row hands the drawing its own text: the named drawing builds "
               "its line(s) from whatever sources it asks for (`--list-specials`)",
}


#: The pinned fixture: the same readings every documented figure in this repo was read
#: at (docs/limits.md), so an edit shown here is judged against the picture the docs
#: describe rather than against whatever this machine is doing right now.
#:
#: Its **shape is a machine's**, and that is not incidental.  The five generated layouts
#: ask 19 sources between them; the numbers below answer 15 of them - the same 15 a box
#: with two reported tachometers answers, leaving `Fan 3`/`Fan 4` slots empty in **both**
#: doors, which is the reserved-slots rule of `bars` being visible rather than hidden.
#: When this dict answered only 5, the pane showed a `bars` layout with 14 of its 32 rows
#: next to a code drawing of 26 and the two pictures looked unrelated: 46 535 differing
#: pixels, none of them about the file.  The suite now holds the two doors to **zero
#: differing pixels at this fixture** for all five themes, at the window's ink choices
#: too, and it asserts the coverage: every source a real box can answer for these five
#: files has a pinned value here, so a new reading in a new export has to be answered
#: here before the preview is allowed to be quiet about it.
#:
#: **Every key here is a key a real box reports** - the set is a subset of the metrics
#: shape `sensors.py` documents at the top of the module and PROTOCOL.md 10 records, and
#: the suite asserts that against the module's own sample rather than against this
#: comment.  It used to be otherwise, and that is how the pane went wrong quietly: this
#: dict carried `gpu.usage`, `cpu.frequency`, `gpu.frequency` and `memory.used_percent`,
#: which **nothing in the library reads** (`themes.values` asks `gpu.load`,
#: `cpu.speedAverage`, `gpu.speed`, and `memory.used`/`total`), while the keys that are
#: read were missing.  A fixture can be wrong in both directions at once, and only a gate
#: over the key names sees it: at that fixture the pane's file door left `alpha`'s GPU row
#: out altogether while its code door drew `--%` and the ring's track - 4 587 px between
#: them at one instant - and it showed `bars` with 14 of its 32 rows.
#:
#: `memory.used`/`total` are MB as that sample spells them, chosen so the derived ratio
#: and the printed gigabytes agree (53 740 of 131 072 is 41 %, which reads `52 GB`);
#: `cpu.usage` sits beside `cpu.load` because that is what `sensors.collect()` emits.
FIXTURE = {"cpu": {"temperature": 57.0, "load": 62.0, "usage": 62.0,
                   "speedAverage": 3400, "power": 18.0},
           "gpu": {"temperature": 47.0, "load": 22.0, "speed": 1200, "fan": 45.0,
                   "power": 90.0, "memoryUsage": 2458, "dedicatedTotal": 8192},
           "memory": {"load": 41.0, "used": 53740, "total": 131072},
           "motherboard": {"temperature": 44.0},
           "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 1180},
                    {"onBoard": True, "type": "Chassis", "name": "Fan System 5",
                     "value": 890}],
           "timestamp": {}}
FIXTURE_WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)
