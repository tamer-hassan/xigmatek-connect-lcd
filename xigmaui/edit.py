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
        return cls(themes.load(rec["path"]), origin=themes.origin(rec),
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
