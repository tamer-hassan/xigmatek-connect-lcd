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
        colour converted to `rgba()`) or when the write was refused and nothing moved.
        The window prints it, which is how a reader finds out that `#ff4040` became
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
        return ""

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
