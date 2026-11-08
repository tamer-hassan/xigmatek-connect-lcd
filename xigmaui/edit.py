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

from xigmalcd import layout, render, sensors, themes

def field_names(kind: str) -> tuple:
    """Every field the inspector offers for one kind, in the order the row shows them.

    Not a hand-kept list: what a kind may edit is the intersection of the keys this
    program is *proven* to read (`themes.keys_read()` takes them out of `layout.py`'s
    source with `ast`) and what that kind draws.  A key the vendor carries but nothing
    reads is never offered - the census prints those 11 with the reason each is inert,
    and the vendor editor's own bookkeeping (`enableMove`, `screenStatus`) stays out of
    the form and survives a save untouched, because `themes.save` writes the widget's
    `property` back as it read it.
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
        "special": ("name", "fontFamily", "fontSize", "bold", "textColor"),
    }
    out = ["x", "y"] + [k for k in per_kind.get(kind, ()) if k in read]
    return tuple(out)


def extension_fields(kind: str) -> tuple:
    """Which `xigma` keys apply to this kind, with their reasons (printed by the tool)."""
    _read, sub = themes.keys_read()
    applies = {
        "text": ("anchor", "autoFitMax"),
        "data": ("anchor", "autoFitMax", "format"),
        "bar": ("barPaint", "colourRamp", "colourStops"),
        "arc": ("arcPaint", "colourRamp", "colourStops"),
        "line": (),
        "special": ("anchor",),
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
    if field == "source":
        return tuple(sorted(set(themes.SOURCES) | set(themes.CLOCKED)))
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

    def __init__(self, obj: dict, origin: str = "", path: str = "", name: str = ""):
        self.obj = obj
        self.origin = origin                    # "your copy", "checkout", "package"
        self.path = path                        # where a save would go, "" if new
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
                       name=name)
        rec = themes.resolve(name)
        if rec is None:
            raise KeyError(f"no layout named {name!r}: {themes.why_not(name)}")
        return cls(themes.load(rec["path"]), origin=themes.origin(rec),
                   path=themes.user_theme_path(rec["name"]), name=rec["name"])

    # --------------------------------------------------------------- saving --
    def save(self) -> tuple:
        """Write the edited layout into the user directory, canonically and atomically.

        `themes.save` is the only writer here, and it refuses the two vendor trees, the
        five drawn-from-code names and any name that is not one path element.  Its soft
        findings come back with the path: they are the same warnings `--check-theme`
        prints, and the window shows them rather than repairing anything quietly, which
        is the rule this repo already keeps about a choice.
        """
        hard, _soft = themes.validate(self.obj)
        if hard:
            return None, hard
        path, warnings = themes.save(self.obj, self.name)
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
        gone = themes.delete_user_theme(self.name)
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
        """One line per widget: what it is, and what it shows."""
        w = self.widgets()[self.index if i is None else i]
        pr = (w.get("property") or [{}])[0]
        what = (pr.get("source") or pr.get("content") or pr.get("name")
                or pr.get("type") or "")
        return (f"{w.get('type')}  {what}  at {pr.get('x')},{pr.get('y')}"
                f"  id {w.get('id')}")

    def select(self, index: int) -> None:
        if not 0 <= index < len(self.widgets()):
            raise IndexError(f"widget {index}: this layout has {len(self.widgets())}")
        self.index = index

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
            self.history.append(self._pending)
            self._pending = None
            if len(self.history) > 60:
                del self.history[0]
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
              scrim: int = 0) -> tuple:
        """The layout as the loop would draw it.  Same door as `--check-theme`."""
        return themes.draw(self.obj, metrics or {}, when, scrim=scrim)

    def fixture(self, pinned: bool = True) -> tuple:
        """The metrics and the instant this editor draws with."""
        if not pinned:
            return sensors.collect(), None
        return dict(FIXTURE), FIXTURE_WHEN

    def fixture_line(self) -> str:
        vals, absent = themes.values(*self.fixture())
        return (f"fixture: {', '.join(f'{k} {v}' for k, v in sorted(vals.items()))}"
                + (f"  (no reading for {', '.join(sorted(absent))})" if absent else ""))


#: The pinned fixture: the same readings every documented figure in this repo was read
#: at (docs/limits.md), so an edit shown here is judged against the picture the docs
#: describe rather than against whatever this machine is doing right now.
FIXTURE = {"cpu": {"temperature": 57.0, "load": 62.0, "frequency": 3.4,
                   "power": 18.0},
           "gpu": {"temperature": 47.0, "usage": 22.0, "frequency": 1.2,
                   "power": 90.0},
           "memory": {"used_percent": 41.0},
           "timestamp": {}}
FIXTURE_WHEN = datetime.datetime(2026, 2, 17, 9, 30, 12)
