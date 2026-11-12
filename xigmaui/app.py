"""app.py - the main window: preview, theme pick, background pick, status, reset.

Layout follows what this panel actually supports rather than what the vendor's
window looks like:

    +----------------+-----------+------------+  the running display: its counters,
    | preview        | theme     | clip list  |  and the last six things it did on
    | (480x480,      | + layout  | (filter,   |  the port; the theme and its
    |  our           |   editor  |  rows,     |  pickers; the library of
    |  composite,    | + advanced|  state)    |  backgrounds; and, under the
    |  not a mirror  |           |            |  picture, the log - then, behind
    |  of the glass) |           |            |  the switch, the panel-status box
    +----------------+-----------+------------+  and the guarded reset

Three columns, not one long scroll: the clip library wants *height* (40 rows on this
box, 115 with the Windows partition mounted) and it was sharing a single column with
four other boxes, which measured out as a 190 px viewport showing two clips at a time
on a 1 919 px window.  Two rules decide the rest, and both come from measurements:
the frame we draw is exactly 480x480 and `_fit()` never scales it up (showing pixels
the glass does not have would be a lie), so a preview column wider than 480 px is
dead space; and a clip row follows its icon, so the thumbnails are 64 px, not the
112 px that made every row 114 px tall.

The `advanced controls` switch folds away nine secondary controls, in **5**
rows and **2** boxes: canvas, scrim, fan figures, the display's last six port
actions, the 30 second frame run, the panel-status box (its `conn 1` report
and its Refresh button go with the box) and the guarded factory reset.  It is
pixels only, never values: what is
hidden keeps its setting and `Apply` sends it.  The pane's readings knob - what
body the editor's picture is drawn from, and the file path when that body is a
file - is **not** among them: it chooses the picture on the row above it, so it
sits under `playing` and stays put, and it is shut (not hidden) while no layout
is open.  The reset and status boxes sit at
the foot of the *preview* column, where
a 480 px picture leaves slack nothing else can fill; the layout editor does not
fold - it is how the window shows the 23 library layouts it can draw, and
folding it away hid the point of the themes package.  The reset keeps its
double guard wherever it stands: `Reset the panel` stays disabled until the
word is typed.

The preview is `tools/previews.py`'s composite running live: the stored
background frame underneath, `render.draw` on top. It is labelled in the window
because there is no readback from this panel (PROTOCOL.md §11) - a preview here
is a promise about what we will put on the wire, not a picture of the glass.

Two owners, one port. Only one process can hold /dev/ttyACM0 (PROTOCOL.md §1),
so this window has two roles and picks one at startup by looking:

* **a `xigmalcd` is running** (its control socket answers): the window is a
  remote.  It reads the daemon's counters, and its buttons send socket commands -
  theme, clock, canvas, scrim, fans, fps, pause, one frame, one background
  upload.  The glass keeps updating when this window is closed, because the
  frames belong to the daemon.  That is the mode the shipped systemd unit runs
  in, and the tray icon's reason for existing.
* **nothing is running**: the window uses the port itself, one short visit per
  button (`panel.py`).  Nothing reaches the panel without a deliberate click.

The second bullet is why the buttons say what they say.  A clip picked in the
list is only a *selection* until the upload button is pressed, and the window
now reports which of the two the panel is holding: the daemon keeps the last
six things it did on the port, and this window shows that ring, so "I chose it"
and "the panel stores it" cannot be confused the way they were on the bench
(docs/gui.md's walk-through, and the limits write-up).
"""
from __future__ import annotations

import inspect
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image, ImageDraw, ImageFont                      # noqa: E402
from PyQt6.QtCore import QEvent, QSize, Qt, QTimer        # noqa: E402
from PyQt6.QtGui import (QAction, QBrush, QColor, QIcon, QImage, QKeySequence,
                         QPalette, QPainter, QPen, QPixmap)        # noqa: E402
from PyQt6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                             QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                             QProgressBar, QPushButton, QScrollArea,
                             QSizePolicy, QSpinBox, QSplitter, QToolButton,
                             QSystemTrayIcon,
                             QVBoxLayout, QWidget)

from xigmalcd import control as wire                              # noqa: E402
from xigmalcd import protocol, render, sensors, themes       # noqa: E402
from xigmalcd.main import (BRIGHT_LUMA, CLIP_LUMA, DEFAULT_MP4,   # noqa: E402
                           SCRIM_ON_BRIGHT, read_metrics_file)
from . import clips as clipdb
from . import edit
from . import settings
from .daemon import Daemon
from .panel import Panel, describe, flatten, port_busy

# Where the launcher picture is, in the order the spellings win over each other -
# the same installation-aware rule the clips follow (xigmalcd/main.py:media_roots):
# after `apt install` the checkout path does not exist, and a window with no icon is
# a window the taskbar draws as a generic gear and the shell matches by name only.
ICONS = (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "install", "xigmaui.png"),
         "/usr/share/icons/hicolor/256x256/apps/xigmaui.png")
ICON = next((p for p in ICONS if os.path.exists(p)), ICONS[0])

# What this window calls itself - in the title bar, in the tray tooltip, and as the
# `Name=` of both menu entries (install/xigmaui.desktop.in and
# debian/xigmaui.desktop).  One string, four places that show it; the pair that
# `tests/test_packaging_parity.py` reads back against both files, so the entry a
# shell lists and the window it launches cannot end up named differently.  It is the
# vendor's family, not the author's model - the paragraph in
# install/xigmaui.desktop.in says what has actually been measured on which Connect.
TITLE = "Xigmatek Connect LCD"

# How much wider than the picture the preview column may get, in pixels: 22 px of
# the column's own layout margins, 2 px of the preview label's border, ~16 px for
# the vertical scrollbar a short window needs, and slack for a theme's frame.
# The cap is what stops a 2 259 px window from spending half its width on black
# around a 480 px picture (`_fit()` never scales up); _build() applies it and the
# suite checks the arithmetic against the frame size itself.
PANE_CHROME = 52

#: The window's floor, as the owner set it: a 1280x1024 desktop at minimum, up to a
#: 3840x2160 one, with everything between used as it comes.  This is a *floor*, not a
#: size to insist on - a 1024-tall screen with a panel on it hands a window fewer than
#: 1024 px, and a window whose last row of controls cannot be reached is worse than a
#: slightly shorter one - so `Window.__init__` clamps it to what the screen actually
#: offers, never below what the window's own contents measure, and says in its log when
#: that floor bites.  The maximum needs no constant: Qt lets the window grow to the
#: screen, and 3840x2160 is inside that, so what has to be proven is that the layout
#: *uses* the width - see `_ED_COL_PX` and the sizing checks in `tests/test_window_sizing.py`.
MIN_WIDTH, MIN_HEIGHT = 1280, 1024

#: The menu entry that means "this key is not in the file at all", for the one kind of
#: field whose absence is a value: this program's own `xigma` extension keys.  It is a
#: label and a sentinel in one, because the row both shows what the file says and is how
#: a reader un-says it - and because picking the first real choice instead would be a lie
#: (`no arcPaint` is the vendor's ring convention, not "render").
#: The faces the `fontFamily` row's menu has already drawn a preview of, keyed by file,
#: height and the ink colour it was drawn in.  A preview is a Pillow render of the same
#: `.ttf` the painter opens, and re-rendering five of them every time a row is bound would
#: be the only cost this cache saves.
_FACE_ICONS: dict = {}

UNSET = "(not set)"

#: The layout combo's first entry: "close the editor".  A constant rather than a string
#: in two places, because the row's behaviour keys off it and a gate asserts it by name.
NO_EDITOR = "(nobody: preview the theme above)"

#: The two colours every tooltip this program shows is painted with, and the door they
#: go in. A Qt tooltip is drawn by `QTipLabel`, one top-level of the application reused
#: for every popup, and it takes its colours from the **palette of the widget the
#: tooltip belongs to** - so a control whose stylesheet paints a background lends that
#: background to the popup. The preview pane's `background:#101014` did exactly that:
#: the popup over it measured 1.11:1 with 0 pixels of readable glyph ink, the "faint
#: gray" being the antialiasing of the palette's own black text on near-black. That is
#: the reported defect, in numbers.
#:
#: The other doors were measured and rejected. A rule written on the widget - `QToolTip
#: { ... }` inside the pane's own stylesheet - changes nothing at all, because the popup
#: is not the widget's child and Qt hands the label an empty rule (`/* */`). An
#: application stylesheet paints the text everywhere but keeps the widget's own
#: background wherever the widget brings one, and it is not free either: installing one
#: re-polishes every widget through the stylesheet style, which moved this window's own
#: layout: the `arc` editor box the pages label per machine - 858 px in one column, 465
#: px in three - came out 818 and 459 on this bench, and that pair is a record of this
#: box rather than a number a check re-quotes (docs/gui.md). So the colours go in as a
#: palette targeted at the one class that needs them, `QApplication.setPalette(pal,
#: "QTipLabel")`: measured over the window's live tooltips, #2b2b2b behind #f2f2f2
#: (12.65:1) and over the pane its own #101014 behind
#: #f2f2f2 (16.96:1), with every layout figure of the window's own and every drawn pixel
#: left where `tests/test_window.py` and `tests/test_tooltips.py` record them.
#:
#: Dark on purpose: one house style, and the ratios stop depending on what a desktop
#: theme decides a tooltip colour should be - the same class of accident as the one
#: reported.

TOOLTIP_BASE = "#2b2b2b"
TOOLTIP_TEXT = "#f2f2f2"


def apply_tooltip_colours() -> None:
    """Paint every tooltip this program shows with `TOOLTIP_BASE` and `TOOLTIP_TEXT`.

    One palette, all three groups, targeted at the class and nothing else: an application
    palette change on the ToolTip *roles* alone moves the text but leaves the background to
    the widget (measured), and an application stylesheet moves the window's own geometry
    (measured: 40 px and 6 px off two box heights the pages label).  Called wherever a
    `Window` is built, because the doors that build one are many - `main()`, the offline
    suite, a throwaway script - and a rule only one of them remembers is a rule no gate can
    hold.
    """
    qapp = QApplication.instance()
    if qapp is None:                       # no Qt application: nothing to colour
        return
    pal = qapp.palette()
    base, text = QColor(TOOLTIP_BASE), QColor(TOOLTIP_TEXT)
    for grp in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive,
                QPalette.ColorGroup.Disabled):
        for role, colour in ((QPalette.ColorRole.ToolTipBase, base),
                             (QPalette.ColorRole.ToolTipText, text),
                             (QPalette.ColorRole.Window, base),
                             (QPalette.ColorRole.WindowText, text),
                             (QPalette.ColorRole.Base, base),
                             (QPalette.ColorRole.Text, text)):
            pal.setColor(grp, role, colour)
    qapp.setPalette(pal, "QTipLabel")      # the class name, or the whole app follows suit


#: What a colour row asks for, in the words a reader sees on hover.  One constant, because
#: the words are now carried by the row's label (see `_ed_say_rows`) rather than by the
#: swatch, and a gate asserts they are there by name.
COLOUR_TIP = ("pick a colour. This file spells colours the way the vendor's do: "
              "`rgba(r, g, b, a)` with `a` a 0..1 fraction - and typing `#ff4040` or "
              "`amber` here is accepted and stored as rgba, in words, by the note line "
              "under these rows")

#: How much of the window's own log is kept on screen, in lines.  Not taste: the
#: log is one wrapped QLabel, so every new line re-sets the whole text, and a
#: window left open over a long session would otherwise spend its afternoon
#: redrawing 40 000 lines of heartbeat.  The newest 200 is what anyone reads
#: back; the display's journal (`journalctl --user -u xigmalcd -f`, docs/usage.md)
#: is where the full record of a run lives.
LOG_KEEP = 200

#: The clip picker's thumbnail edge, in pixels, and so the row height too: a
#: QListWidget row follows its icon.  112 was the first guess and it cost a row
#: each 114 px of list; 64 still reads as a picture and the same list shows
#: almost twice as many clips.  `_thumb_batch` decodes to whatever this is set
#: to on the widget, so the two cannot drift.
CLIP_ICON = QSize(64, 64)

#: px of border and layout allowance around the preview label, added to the
#: pixmap's own height when the card is clamped to it (`_fit`).
FRAME_CHROME = 4


def app_icon() -> QIcon:
    """The project mark, however this machine knows about it.

    By theme name first: the .deb installs the picture into
    /usr/share/icons/hicolor/256x256/apps/xigmaui.png, which is what makes
    `Icon=xigmaui` in the installed menu entry resolve.  On a box running from a
    checkout there is no icon theme holding it (this machine has none configured),
    so the fallback is the file itself - and the picture is a rendering of the
    glass, which is the one thing worth showing in the taskbar and in the tray,
    where it is the only way to find us."""
    return QIcon.fromTheme("xigmaui",
                           QIcon(ICON) if os.path.exists(ICON) else QIcon())


def _scroll(widget: QWidget) -> QScrollArea:
    """A column that can scroll when the window is shorter than it wants to be."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    return area


def _readable(combo: QComboBox) -> QComboBox:
    """Let a drop-down's list be wider than the box that opens it.

    Measured, not assumed: the closed combo does stretch to the field column
    (208 px in a 299 px box at the fresh window), but the *list* that opens is
    the box's own width, so every entry longer than the box is elided in the one
    place a reader is choosing from.  `data  CPU Temperature  at 166,205` needs
    195 px, the layout editor's longest entry, and a 236 px field column with an
    icon and an arrow leaves less than that to the text.

    The box itself never asks for more than the column can give - that is what
    put a floor under the controls column once, when one combo's entry carried a
    whole sentence inline - so it is the popup's view that gets the extra width,
    which costs no column pixel at all.  Called after every repopulate, because
    the longest entry changes with the layout, with the kind, with the vocabulary.
    """
    view = combo.view()
    metrics = view.fontMetrics()
    wide = max((metrics.horizontalAdvance(combo.itemText(i))
                for i in range(combo.count())), default=0)
    if wide:
        # the row's own furniture: frame, margins, the scroll bar the list may
        # need, and any icon column the entries carry
        view.setMinimumWidth(wide + 60 + combo.iconSize().width())
    return combo


def _ed_face_icon(ctl: QComboBox, path: str, height: int = 15) -> QIcon:
    """A menu icon drawn with the face the painter would actually use.

    The point of the picture in the `fontFamily` row's menu is that it is not Qt's font
    list: the bytes come from the file `layout.font_for` named, through the same Pillow
    call `layout.draw_text` makes, so the shape a reader is choosing is the shape that
    goes to the glass.  It previews the **face**, not the size - every entry is drawn at
    one height, because a menu cannot honestly show what 8 px or 74 px will look like and
    the row's own size is in the row beside it.  The ink is the popup's own text colour,
    so the preview is legible on a light desktop and on a dark one; a family this box has
    no file for gets no icon at all, which is the honest mark.
    """
    col = ctl.palette().color(QPalette.ColorRole.WindowText)
    key = (path, height, col.rgba())
    if key in _FACE_ICONS:
        return _FACE_ICONS[key]
    img = Image.new("RGBA", (34, height + 7), (0, 0, 0, 0))
    ImageDraw.Draw(img).text(
        (2, 3), "Ag", font=ImageFont.truetype(path, height),
        fill=(col.red(), col.green(), col.blue(), 255))
    q = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, img.width * 4,
               QImage.Format.Format_RGBA8888).copy()
    _FACE_ICONS[key] = QIcon(QPixmap.fromImage(q))     # the same conversion the clip
    return _FACE_ICONS[key]                           # icons and the ink chips use


def _ed_face_marks(ctl: QComboBox, faces: dict) -> None:
    """Put each family's own shape in front of its name, and mark the ones with no file.

    The vocabulary is the vendor's (`arial`, `verdana`, `simsun`, `dejavu`, `宋体`), so the
    names tell a reader nothing about what the glass will show; the file this box resolves
    each one to does.  `faces` is `edit.Editor.faces_here()` - the painter's own loader
    answered per name - and the icon is `_ed_face_icon`, drawn from that file.  A name
    with no file gets an empty icon and a tooltip that says so, because the alternative is
    a menu that promises a face this machine cannot draw.
    """
    for i in range(ctl.count()):
        name, path = ctl.itemText(i), faces.get(ctl.itemText(i))
        if name == UNSET:
            # not a family name, so nothing to preview and nothing to warn about.  A
            # `fontFamily` row never offers this entry today - `(not set)` is only put in
            # the menu for this program's own keys, and `fontFamily` is the vendor's - so
            # this branch is the helper declining to mark a thing it was never asked
            # about.  What it says, if a later change does offer it, is the truth about a
            # text row with no family: there is no default face to fall back to.
            ctl.setItemIcon(i, QIcon())
            ctl.setItemData(i, "no `fontFamily` in the file, and there is no default face "
                               "to fall back to: a row without one draws no ink at all",
                            Qt.ItemDataRole.ToolTipRole)
            continue
        if path is None:
            ctl.setItemIcon(i, QIcon())
            ctl.setItemData(
                i, f"no font file on this box answers `{name}`: a row that names it draws "
                   f"no ink at all (the painter puts `font:{name.lower()}` in its "
                   f"`missing` notes, and `--check-theme` prints that)",
                Qt.ItemDataRole.ToolTipRole)
        else:
            ctl.setItemIcon(i, _ed_face_icon(ctl, path))
            ctl.setItemData(i, f"{os.path.basename(path)}\nthe preview is one height for "
                               f"every entry: the row's own `fontSize` decides the size",
                            Qt.ItemDataRole.ToolTipRole)


def _ed_shrink(ctl) -> None:
    """Let one row's control give way, so a column of rows never sets a floor.

    The pair with `_readable`, and the reason a form of 18 rows can live in a 347 px
    column at all: the *list* a drop-down opens carries the entry's width, so the
    closed box is free to be as narrow as its column.  Without this, a `source` menu
    asks for the width of `Motherboard Temperature`, eighteen of them ask for the
    width of the window, and the controls column grows a horizontal scrollbar inside
    itself - the 0.4 defect, rebuilt from the other end.  A spinbox is the same trap
    with different furniture: its range is deliberately wider than any legal value
    (an out-of-range number is *said* by the model, not clamped away), so it must not
    demand room for `-100000` in a column that holds a two-digit `fontSize`.
    """
    if isinstance(ctl, QComboBox):
        ctl.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        ctl.setMinimumContentsLength(6)
    elif isinstance(ctl, QSpinBox):
        ctl.setMinimumWidth(56)
    elif isinstance(ctl, QLineEdit):
        ctl.setMinimumWidth(64)
    ctl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class Canvas(QLabel):
    """The preview pane, with the editor's marks painted **over** the picture.

    Two rules decide this class, and both are claims the documents already make about the
    pane.  First, the image handed to it is the composite the panel would get - our layer
    over the background - so nothing that says "this row is selected" is ever drawn *into*
    that image: the marks are painted in `paintEvent`, over the pixmap, and what the window
    keeps and the caption describes stays byte for byte what the painter returned.  Second,
    the widget knows points and distances and no thing about layouts: every press, drag and
    arrow is turned into panel px and handed to the window, which hands it to
    `xigmaui/edit.py`, so a dragged row and a typed one go through the same `set`/`move` and
    land on one undo stack.

    A press on one of the squares painted on the selected row's box resizes that row; a press
    anywhere else in its ink moves it.  Which squares are painted is the model's answer -
    `edit.Editor.size_edges` puts each of its eight edges through its own resize door - so a
    kind with no size key gets none, and a `text` row, which owns no width, gets none on its
    left or right side.  The squares are chrome belonging to the selected row: the pane's
    later-row-wins rule is about ink, and a grabbed square that moved some other row would be
    a surprise nobody could see coming.  What the drag writes, and the box it reaches, come
    back from the model in words.

    The coordinate mapping is whatever `_fit` chose, not a second decision: the picture is
    centred in the label and never scaled above 1:1, so `side` is the pixmap's own width and
    the slack on either side is the offset.  A point outside the picture is no row's.
    """

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.side = 0                     # the pixmap's width, in widget px
        self.marks = None                 # (box in panel px, one line of text)
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    #: A handle's reach, and where it comes from.  Handles are the eight small squares on
    #: the selected row's box, so a thin row (the vendor's `line` widgets are 2 px thick) is
    #: still grabbable at its ends instead of being nothing but an edge.  `HANDLE` is in
    #: **panel** px because that is the space the marks are kept in, and `HANDLE_MIN` is in
    #: **widget** px because that is the space a cursor can aim at: the pane is never scaled
    #: above 1:1, so the reach is the larger of the two once the scale is applied.
    HANDLE = 4
    HANDLE_MIN = 3

    #: The cursor each edge asks for while its drag is in flight.  The names come from
    #: `edit.Editor.EDGES`, because an edge the model does not know has no handle and no
    #: cursor; a press that is not on an edge goes back to the pane's own arrow.
    CURSORS = {
        "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
        "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
        "top-left": Qt.CursorShape.SizeFDiagCursor,
        "bottom-right": Qt.CursorShape.SizeFDiagCursor,
        "top-right": Qt.CursorShape.SizeBDiagCursor,
        "bottom-left": Qt.CursorShape.SizeBDiagCursor,
    }

    def set_edge_cursor(self, edge: str) -> None:
        """Point like the edge being dragged, or stop pointing."""
        if edge:
            self.setCursor(self.CURSORS.get(edge, Qt.CursorShape.SizeAllCursor))
        else:
            self.unsetCursor()

    def handles(self) -> tuple:
        """The live handles as `((edge, x, y), ...)` in panel px.

        Which edges are live is the window's to say - it asks the model, whose answer comes
        from its own resize door (`edit.Editor.size_edges`) - and where those edges *sit* is
        the pane's, because the pane is the thing holding the box.  The names are the same
        eight both files use: `edit.Editor.EDGES`, the table `tests/test_row_resize.py` holds.
        """
        if not self.marks or len(self.marks) < 4:
            return ()
        x0, y0, x1, y1 = self.marks[0]
        mx, my = (x0 + x1) // 2, (y0 + y1) // 2
        where = {"left": (x0, my), "right": (x1, my), "top": (mx, y0),
                 "bottom": (mx, y1), "top-left": (x0, y0), "top-right": (x1, y0),
                 "bottom-left": (x0, y1), "bottom-right": (x1, y1)}
        return tuple((e,) + where[e] for e in (self.marks[3] or ()) if e in where)

    def handle_at(self, pt: tuple) -> tuple:
        """The handle under this panel point, as `(edge, x, y)`, or `("", 0, 0)`.

        A square reach rather than a round one, because the handle painted on the glass is a
        square: Chebyshev distance, nearest wins, and a point inside the box but not inside a
        handle is a move - which is a visible act, not a silent nothing.
        """
        if not self.marks or self.side <= 0:
            return "", 0, 0
        reach = max(float(self.HANDLE), self.HANDLE_MIN * render.W / max(1, self.side))
        best, best_d = ("", 0, 0), None
        for name, hx, hy in self.handles():
            d = max(abs(int(pt[0]) - hx), abs(int(pt[1]) - hy))
            if d <= reach and (best_d is None or d < best_d):
                best, best_d = (name, hx, hy), d
        return best

    def edge_at(self, pt: tuple) -> str:
        """Which edge this point would drag, or "" when it would move the row."""
        return self.handle_at(pt)[0]

    # ------------------------------------------------------------------ marks --
    def set_marks(self, marks) -> None:
        """What to draw over the picture.

        None, or `(box, one line)` in panel px - plus, while a resize drag is in flight, a
        third item: the box the release would ask for, painted in a solid line next to the
        dashed one that is.  The fourth item is always there when the window is editing: the
        live handles, as `(edge, x, y)` triples, which are the only places a press means a
        resize.  The fifth is a move drag's guide lines, as `(axis, panel px)` pairs - the
        ones `edit.Editor.snap_move` is pulling the row onto right now.
        """
        if marks != self.marks:
            self.marks = marks
            self.update()

    def set_side(self, side: int) -> None:
        """The size `_fit` actually drew the picture at, so marks line up with it."""
        self.side = int(side)
        self.update()

    def _origin(self) -> tuple:
        return ((self.width() - self.side) // 2, (self.height() - self.side) // 2)

    def to_panel(self, pos):
        """Widget px -> panel px, or None when the point is not on the picture."""
        if self.side <= 0:
            return None
        ox, oy = self._origin()
        k = self.side / render.W
        x, y = (pos.x() - ox) / k, (pos.y() - oy) / k
        if not (0 <= x < render.W and 0 <= y < render.H):
            return None
        return int(round(x)), int(round(y))

    def paintEvent(self, event):          # noqa: N802
        super().paintEvent(event)
        if not self.marks or self.side <= 0:
            return
        box, text = self.marks[0], self.marks[1]
        target = self.marks[2] if len(self.marks) > 2 else None
        ox, oy = self._origin()
        k = self.side / render.W
        x0, y0 = ox + box[0] * k, oy + box[1] * k
        w = max(1.0, (box[2] - box[0]) * k)
        h = max(1.0, (box[3] - box[1]) * k)
        p = QPainter(self)
        pen = QPen(QColor("#7fd0ff"))
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(int(round(x0)), int(round(y0)), int(round(w)), int(round(h)))
        # the handles, filled: a row's box is a thin thing (the vendor's `line` widgets are
        # 2 px of ink), and a rule about dragging an edge is only honest if the places that
        # mean an edge are visible.  These are the model's live edges, not a decoration:
        # `handle_at` grabs the same squares this paints.
        reach = max(float(self.HANDLE), self.HANDLE_MIN * render.W / max(1, self.side))
        p.setPen(QPen(QColor("#0b0b0d")))
        p.setBrush(QBrush(QColor("#7fd0ff")))
        for _edge, hx, hy in self.handles():
            p.drawRect(int(round(ox + (hx - reach) * k)),
                       int(round(oy + (hy - reach) * k)),
                       max(1, int(round(2 * reach * k))),
                       max(1, int(round(2 * reach * k))))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if target:
            # what the release would ask for, in a solid line, beside what is on the glass
            # now in a dashed one.  The model may still land elsewhere - a `text` row's box
            # is its ink and the face reaches the height *nearest* the drag, and an `arc`'s
            # ring grows from its own centre - which is what the sentence printed on release
            # says, so the pane promises the ask, not a result it has not computed.
            p.setPen(QPen(QColor("#ffd166")))
            p.drawRect(int(round(ox + target[0] * k)), int(round(oy + target[1] * k)),
                       max(1, int(round((target[2] - target[0]) * k))),
                       max(1, int(round((target[3] - target[1]) * k))))
        guides = self.marks[4] if len(self.marks) > 4 else ()
        if guides:
            # the line a snap is pulling the row onto, drawn end to end across the glass.
            # Without it a row that stops 2 px short of the cursor looks like a pane that
            # lost the drag; with it the reader sees which of the file's numbers took hold.
            # Chrome, and only chrome: the marks never touch the frame, the same rule the
            # handles and the amber ask box are held to.
            p.setPen(QPen(QColor("#8affc1")))
            span = int(round(self.side))      # the pane drew a square of this many widget px
            for axis, value in guides:
                if axis == "x":
                    at = int(round(ox + value * k))
                    p.drawLine(at, int(round(oy)), at, int(round(oy)) + span)
                else:
                    at = int(round(oy + value * k))
                    p.drawLine(int(round(ox)), at, int(round(ox)) + span, at)
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor("#000000"))
        p.drawText(int(round(x0)), max(11, int(round(y0)) - 3), text)
        p.setPen(QColor("#7fd0ff"))
        p.drawText(int(round(x0)), max(10, int(round(y0)) - 4), text)
        p.end()

    # ---------------------------------------------------------------- events --
    def mousePressEvent(self, event):     # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pt = self.to_panel(event.position().toPoint())
            if pt is not None:
                # which handle, if any - the model decides later whether this kind has a
                # size that a drag may write at all, and says so in words if it has not
                self.win._canvas_press(*pt, self.edge_at(pt))
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):      # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            pt = self.to_panel(event.position().toPoint())
            if pt is not None:
                self.win._canvas_move(*pt)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):   # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and (self.win._drag
                                                           or self.win._resize):
            self.win._canvas_release()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):       # noqa: N802
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        delta = {Qt.Key.Key_Left: (-step, 0), Qt.Key.Key_Right: (step, 0),
                 Qt.Key.Key_Up: (0, -step), Qt.Key.Key_Down: (0, step)}.get(event.key())
        if delta is not None and self.win.ed is not None:
            self.win._canvas_nudge(*delta)
            event.accept()
            return
        super().keyPressEvent(event)


class EditorBox(QGroupBox):
    """The editor group, which re-flows its field grid when *it* is resized.

    The window's own `resizeEvent` is not the signal to watch: the columns live in a
    splitter, and dragging a handle never fires it - which is exactly the bug
    docs/gui.md records for the preview picture.  So the box measures its own width
    and asks the window how many columns of rows that width can hold.  It is the same
    hook `_fit()` uses for the glass, applied to a form.
    """

    def __init__(self, title: str, on_width):
        super().__init__(title)
        self._on_width = on_width

    def resizeEvent(self, event):                          # noqa: N802
        super().resizeEvent(event)
        self._on_width(self.width())


class Window(QMainWindow):
    """The main window.

    Both columns sit in scroll areas: on a laptop-height screen the right column
    (theme, clips, status, reset, log) is taller than the window, and a layout
    that cannot scroll simply draws its children over each other - which is what
    the first version did, the clock of the preview landing on the status box.
    """

    def __init__(self, port: str | None = None, preview_fps: float | None = None,
                 restore: bool = True, socket: str = "", tray: bool | None = None,
                 save_settings: bool | None = None):
        """`port` and `preview_fps` passed in win over what was saved: they come
        from the command line, and a command line that says `/dev/ttyACM1`
        should not be overruled by a file. `restore=False` starts from the
        defaults (`--fresh`), which is also what the offline checks use.

        `save_settings` says whether this window may **write** that file, and it
        defaults to `restore`: a window that was told to ignore your session is
        not a window that should replace it.  That is not a hypothetical - an
        offline check or a throwaway script builds a `Window` with a device path
        that does not exist and a rate nobody asked for, the save timer fires
        500 ms later like it does for a person, and the author's real
        `~/.config/xigmaui/config.json` ends up holding `/dev/xigma-no-such-port`
        and a clip nobody chose.  `--fresh` passes `save_settings=True`
        because its own help promises to "ignore and overwrite".

        `socket` says where to look for a running display (default: the same
        place `xigmalcd` puts it), and `tray` overrides whether closing the
        window hides it instead of quitting (`--tray` / `--no-tray`)."""
        super().__init__()
        # Every tooltip this program shows, painted the same way wherever the window is
        # built.  The call sits here rather than in `main()` because the doors that build a
        # `Window` are many - `main()`, `tests/`, a throwaway script - and a rule only
        # one of them remembers is a rule no check can hold.  The function's own
        # comment above carries the measurements that made it necessary.
        apply_tooltip_colours()
        self.autosave = restore if save_settings is None else save_settings
        self._said_no_save = False
        # what the file needed explaining, in its own words: an older key, or two keys that
        # answer one question.  Logged once _build() has given us somewhere to say it.
        self._cfg_notes: list[str] = []
        self.cfg = (settings.load(self._cfg_notes) if restore
                    else settings._clean({}, self._cfg_notes))
        self.setWindowTitle(TITLE)
        self.port = port or self.cfg["device"]
        self.preview_fps = preview_fps or self.cfg["preview_fps"]
        self.player: clipdb.ClipPlayer | None = None   # the preview's decode stream
        self._dead_clips: set[str] = set()   # files whose stream produced nothing
        self._osd: Image.Image | None = None  # our layer, redrawn at preview_fps
        self._played = 0        # frames the pane has actually shown (for docs/measuring)
        self.bg_timer = QTimer(self)          # the background's own clock
        self.bg_timer.timeout.connect(self._play_tick)   # connected once, here
        self.mp4 = self.cfg["clip"]
        # Whether a layout's own background is the one under the preview.  A vendor layout
        # names one clip in its own file (`themes.pair`), and while this is False the window
        # follows that: open `Theme_07`, and `Theme_07.mp4` goes under the layer.  True is
        # the "keep my background" box in the clip column, and a hand is the only thing that
        # ticks it - clicking a library row used to, which is how a window came to look like
        # it was ignoring its own pairing (docs/gui.md).  It is a stored flag rather than
        # "the clip is not the default", because a paired clip and a chosen one are the same
        # shape once they are both paths on disk.
        self.keep_clip = bool(self.cfg.get("keep_my_clip", False))
        self._pair_target = ""          # the clip the open layout names, if any
        self.pair_note = ""             # the sentence the pairing ended with
        # Whether the list's current row moved because a reader clicked it.  Population
        # selects the row that matches the restored clip, and the pairing selects the row
        # it chose; both are the window answering its own question, and treating either as
        # a choice is how a line about "your background" gets printed for a click nobody
        # made.
        self._programmatic = False
        self.tray_wanted = self.cfg["tray"] if tray is None else tray
        self._quitting = False
        self.bg_frame: Image.Image | None = None
        self.bg_note = ""
        self._last: dict = {}
        self._seq = 0
        self._pix = QPixmap()
        # What the panel stores as its background layer, in the only words that
        # can establish it: the running display's own event ring, which records
        # `background <name> accepted` after it reads the file's notice off the
        # wire.  The panel is never asked - it cannot answer (PROTOCOL.md §11) -
        # so "" means "this window has not seen an accept yet", and the UI says
        # exactly that rather than implying the preview is the glass.
        self._stored_bg = ""
        self._queued_bg = ""          # the clip this window last asked for
        self._marked_bg = None        # which row is bold right now ("" = none)
        # what the log pane holds, newest last; capped at LOG_KEEP below
        self._log_lines: list[str] = []

        self.panel = Panel(self.port, self)
        self.panel.log.connect(self._log)
        self.panel.status.connect(self._show_status)
        self.panel.busy.connect(self._busy)
        self.panel.done.connect(self._done)

        # the other owner of the port, if there is one: asked before anything
        # else so no action here tries to open a port the daemon is holding
        self.daemon = Daemon(socket, self)
        self.daemon.log.connect(self._log)
        self.daemon.refreshed.connect(self._show_display)
        self.daemon.changed.connect(self._display_changed)
        self.daemon.done.connect(self._done)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(500)      # one write per burst of clicks
        self.save_timer.timeout.connect(self._save_now)

        self._build()
        # ---- the floor this window may not be dragged under, and the screen it may
        # not overflow (MIN_WIDTH/MIN_HEIGHT above says whose rule it is) ----
        avail = self.screen().availableGeometry()
        floor_w = max(self.minimumSizeHint().width(), min(MIN_WIDTH, avail.width()))
        floor_h = max(self.minimumSizeHint().height(), min(MIN_HEIGHT, avail.height()))
        self.setMinimumSize(floor_w, floor_h)
        # Only the lower bound is applied to the size you left it at.  A window taller
        # than the screen is ordinary desktop behaviour - the window manager moves it and
        # you scroll - while a window shorter than its own contents is a control you
        # cannot reach, so `avail` bounds the floor above and not the window below.
        want = tuple(self.cfg["size"])
        got = (max(want[0], floor_w), max(want[1], floor_h))
        if got != want:
            # refuse-and-say, the same way a bad port path or a two-number `split`
            # is handled: the file said one thing, the screen says another, and the
            # window tells you which one it drew instead of leaving you to find out
            # by hunting for a button that fell off the bottom edge
            self._log(f"window sized {got[0]}x{got[1]}, not {want[0]}x{want[1]}: this "
                      f"window will not go under {floor_w}x{floor_h}, the size its own "
                      f"contents need (the rule is MIN_WIDTH x MIN_HEIGHT, or this "
                      f"screen's {avail.width()}x{avail.height()}, whichever is less)")
        self.resize(*got)                    # as you left it, inside those bounds
        # ...and only now the two columns: a splitter that has never been laid
        # out treats setSizes as a wish, and the second half of the window is
        # what loses.  Verified offscreen: setting it inside _build left the
        # controls 116 px wide at a 2 259 px window.
        self.split.setSizes(self.cfg["split"])
        self._build_tray()
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._preview_tick)
        self.preview_timer.start(max(200, int(1000 / self.preview_fps)))
        self._load_background(self.mp4)
        # A file that needed explaining gets explained here, once, before anything the
        # window does about it: an older key is honoured silently in the sense that the
        # background does not move, and loudly in every other one.
        for _note in self._cfg_notes:
            self._log(_note)
        self._cfg_notes = []
        # Said even at a fresh window, because "the theme chose this background" and "you
        # chose this background" are different claims about the same picture, and the pane
        # cannot tell them apart by looking at it.
        self._apply_pair(self.theme.currentText())
        self.daemon.poll(report=True)
        if not self.daemon.present:
            # the box has to say what it is even when there is nothing to say
            self._display_changed(False)
            self.queue("status")
        self.daemon_timer = QTimer(self)
        # 2 s: the counters are what the window quotes about the glass, and a
        # status read is one round trip on a unix socket, not a visit to a
        # 115200 serial line - the daemon answers from its own snapshot
        self.daemon_timer.timeout.connect(self.daemon.poll)
        self.daemon_timer.start(2000)

    # ---- widgets ---------------------------------------------------------
    def _build(self) -> None:
        left = QWidget()
        lay = QVBoxLayout(left)
        # `playing`: the preview pane can show the background moving rather than
        # one mid-loop frame of it.  Host-side only - it sends nothing, changes
        # nothing on the display, and is a preview of our own compositing in both
        # modes (§11).  It is here rather than behind the advanced switch because
        # it is about what the reader is looking at, and because the one thing it
        # can cost is CPU, which the tooltip says.
        arow = QHBoxLayout()
        self.anim_toggle = QCheckBox("playing")
        self.anim_toggle.setChecked(bool(self.cfg.get("animate")))
        self.anim_toggle.setToolTip(
            "decode the background clip in sequence and show it moving under our "
            "layer, instead of one still frame of it. Nothing goes out on the "
            "wire either way: this is this machine's own ffmpeg decode of the "
            "file plus `render.draw`'s layer on top, and the panel is never asked "
            "what it is showing, so it is still not a picture of the glass. The "
            "clip plays on its own timer at its own measured rate (23 of the "
            "vendor's 43 clips are 24 fps, 20 are 20 fps, capped here at 30), while "
            "our layer and the sensor readings behind it are redrawn at "
            "--preview-fps. The two are deliberately separate clocks: reading the "
            "sensors is ~72 ms of an ~86 ms layer tick, and pasting the layer over "
            "the next frame of the clip is ~0.5 ms, so tying them together makes a "
            "24 fps clip into a slideshow at the preview rate. Measured figures in "
            "docs/gui.md")
        arow.addWidget(self.anim_toggle)
        self.anim_note = QLabel()
        self.anim_note.setStyleSheet("color:#888;font-style:italic;")
        self.anim_note.setWordWrap(True)
        arow.addWidget(self.anim_note, 1)
        lay.addLayout(arow)
        # **What body the pane is painted from** - the other choice about the picture, so it
        # sits on the row under `playing`, above the pane, rather than in the fold beside the
        # knobs that write settings.  It decides nothing about the file: a fresh window opens
        # at the fixture and the choice is never written to the session file, so a window you
        # did not choose cannot come up showing readings it grabbed by itself.  It is also not
        # folded away: the one thing it can cost is a sensor read on the preview tick, and a
        # reader who cannot see the knob cannot know that.
        #
        # Two bodies, two rules, and the difference is the point:
        #
        # * `this machine's readings` is **live**: the preview tick re-reads this box (at
        #   `--preview-fps`, never per pointer event - a mouse-move that reads the sensors is
        #   the cost `tests/test_canvas.py` holds at zero) and the marks, the hit test and the
        #   handles are taken from **that** paint, the frame on screen.  They have to be: at
        #   another body these layouts move their row boxes, `tests/test_peek_readings.py`
        #   counts the points that answer a different row in one frame than in the other, and
        #   a handle drawn from the pinned edges would sit over somebody else's ink.
        # * `a metrics file` is **held**: read once when you name it, and it is the same
        #   picture twice, which is what makes a peek at a saved sample useful at all.  Its
        #   geometry doors stay shut - press, drag, arrow key and handle are refused in the
        #   model's own words - because a number written from a frame that was never this
        #   machine's current one belongs to a sample that is gone.
        #
        # `activated` rather than `currentIndexChanged`: choosing the entry you are already on
        # is how the reader says "read it again, now", which for a live pane is a refresh.
        prow = QHBoxLayout()
        plab = QLabel("pane readings")
        plab.setStyleSheet("color:#888;")
        prow.addWidget(plab)
        self.ed_peek = QComboBox()
        self.ed_peek.addItem("the fixture", "fixture")
        self.ed_peek.addItem("this machine's readings", "sensors")
        self.ed_peek.addItem("a metrics file", "file")
        self.ed_peek.activated.connect(self._editor_peek)
        self.ed_peek.setToolTip(self._ed_peek_tip())
        self.ed_peek_file = QLineEdit()
        self.ed_peek_file.setPlaceholderText("PATH to a JSON `STATE all 1` body")
        self.ed_peek_file.setEnabled(False)
        self.ed_peek_file.editingFinished.connect(self._editor_peek)
        self.ed_peek_file.setToolTip(
            "The same file shape `--metrics-file` takes: its sections replace this "
            "machine's for the picture only. Nothing is sent anywhere: a peek paints, "
            "it does not upload.")
        prow.addWidget(self.ed_peek)
        prow.addWidget(self.ed_peek_file, 1)
        lay.addLayout(prow)
        # The pane is the one widget that both *shows* the frame and can be pointed
        # at: `Canvas` paints the editor's marks over the picture without ever
        # drawing them into it (see its docstring), and it turns presses into panel
        # px for the callbacks further down this class.
        self.preview = Canvas(self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # small minima: a preview pane that cannot shrink drags a horizontal
        # scrollbar onto the whole column, and the frame is scaled to fit anyway
        self.preview.setMinimumSize(160, 160)
        # A QLabel reporting its 480x480 pixmap as a minimum is what put that
        # horizontal bar there. `Ignored` says the pane may be smaller than the
        # picture: `_fit()` scales the frame to whatever room there is.
        self.preview.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Ignored)
        self.preview.setStyleSheet("background:#101014;border:1px solid #333;")
        # The picture has to refit when *this label* changes size, not when the
        # window does: the splitter can resize one column without the window's
        # own resizeEvent ever firing, and dragging the handle while the frame
        # stayed at its old scale is what made the preview pane look stuck.  An
        # event filter on the label is the one hook that sees every way the pane
        # can move.
        self.preview.installEventFilter(self)
        # the picture keeps first call on this column's height: the log under
        # it is a readout that can scroll, while a preview that cannot reach 1:1
        # is a smaller picture of the glass for no reason
        # `6` against the log's `1`: below the 480 px the frame caps at, any
        # height left in the column belongs to the log, which scrolls.  The
        # picture must still *expand* into the square its width allows - with
        # stretch 0 the label collapsed to its pixmap's old sizeHint and the
        # frame came back 160 px at a 520 px pane (measured), which is the same
        # mistake in the other direction.
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding,
                                   QSizePolicy.Policy.Expanding)
        lay.addWidget(self.preview, 6)   # stretch: the frame keeps its square
        self.caption = QLabel()
        self.caption.setWordWrap(True)
        self.caption.setStyleSheet("color:#888;font-style:italic;")
        lay.addWidget(self.caption)
        self.metrics = QLabel()
        self.metrics.setWordWrap(True)
        self.metrics.setStyleSheet("font-family:monospace;color:#bbb;")
        lay.addWidget(self.metrics)

        right = QWidget()
        col = QVBoxLayout(right)
        # one switch, and it says what it hides rather than leaving the reader to
        # find the missing knobs: everything it covers is still in effect, it is
        # only off screen until asked for.
        head = QHBoxLayout()
        self.adv_toggle = QCheckBox("advanced controls")
        self.adv_toggle.setToolTip(
            "show the canvas and scrim pickers, the fan figures switch, the "
            "display's last six port actions, the 30 second frame run, and - at "
            "the foot of the preview column, under the log - the panel-status box "
            "(the `conn 1` report and its Refresh button), the guarded factory "
            "reset and the pane-readings box - what body the editor's picture is "
            "drawn from. Hiding them does not change them: what is not shown is still "
            "what is set, and Apply sends it either way. The layout editor is not "
            "one of these: it stays open, because it is how this window shows the "
            "layouts it can draw")
        self.adv_toggle.setChecked(bool(self.cfg.get("advanced")))
        self.adv_toggle.toggled.connect(self._set_advanced)
        self.anim_toggle.toggled.connect(self._set_animate)
        head.addWidget(self.adv_toggle)
        # the folded list, in one place: `_set_advanced` puts the same words back
        # when it folds, and a note that drifts from what the switch hides is a map
        # with a place missing off it
        self._adv_folded_note = ("canvas, scrim, fans, the display's last six port "
                                 "actions, the 30 s run, the panel-status box and the "
                                 "factory reset.  The pane-readings knob does not fold: "
                                 "it picks the picture above the preview pane.")
        self.adv_note = QLabel(self._adv_folded_note)
        self.adv_note.setStyleSheet("color:#888;font-style:italic;")
        self.adv_note.setWordWrap(True)
        head.addWidget(self.adv_note, 1)
        col.addLayout(head)
        # what the toggle covers, filled in as the boxes are built: pairs of
        # (form label, field) for the QFormLayout rows, and whole widgets for
        # everything else.  A form row whose field is hidden and whose label is
        # not is a gap with a word in it, so both go.
        self._adv_hide: list = []
        # A third column, used when the window is wide: the clip library wants
        # *height* (40 distinct clips, out of the 46 mp4 files this repository tracks,
        # 204 where an installed copy and a mounted partition add theirs) and at
        # 1 919 px it was sharing one long column with the display status, the
        # theme box, the panel hello and the log - measured, the list got 190 px
        # of viewport, which is two rows of 114 px.  Two columns give it the
        # height and leave the settings where they are.
        lib = QWidget()
        lcol = QVBoxLayout(lib)

        live = QGroupBox("The running display")
        self.display_box = live
        llay = QVBoxLayout(live)
        self.d_line = QLabel("not asked yet")
        self.d_line.setWordWrap(True)
        self.d_line.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.d_line.setStyleSheet("font-family:monospace;")
        llay.addWidget(self.d_line)
        self.d_counters = QLabel()
        self.d_counters.setWordWrap(True)
        self.d_counters.setStyleSheet("font-family:monospace;color:#bbb;")
        llay.addWidget(self.d_counters)
        rowd = QHBoxLayout()
        self.btn_pause = QPushButton("Pause the display")
        self.btn_pause.setCheckable(True)
        self.btn_pause.setToolTip(
            "stop drawing without letting go of the port: the panel keeps the "
            "last picture it was given. `resume` re-helloes first, and re-opens "
            "the port if the pause outlasted main.SESSION_TTL, because that is "
            "the clock the measured silence arrives on (PROTOCOL.md §9)")
        self.btn_pause.toggled.connect(self._toggle_pause)
        rowd.addWidget(self.btn_pause)
        self.btn_dframe = QPushButton("One frame now")
        self.btn_dframe.setToolTip("ask the running display for a single frame. "
                                   "It is queued for the frame loop, which is "
                                   "the only thing that touches the port")
        self.btn_dframe.clicked.connect(lambda: self.daemon.frame())
        rowd.addWidget(self.btn_dframe)
        llay.addLayout(rowd)
        rowe = QHBoxLayout()
        rowe.addWidget(QLabel("fps"))
        self.d_fps = QDoubleSpinBox()
        self.d_fps.setRange(0.2, 3.0)
        self.d_fps.setSingleStep(0.5)
        self.d_fps.setDecimals(1)
        # 2 fps is what this link was measured at without refusing (-f 3 needs a
        # clock correction, README); 1 fps is what the vendor app does
        self.d_fps.setValue(1.0)
        self.d_fps.setToolTip("frames a second the display draws. 1 fps is what "
                              "the vendor app does; 2 fps was measured accepted "
                              "on this link, 3 fps only with the clock "
                              "correction")
        rowe.addWidget(self.d_fps)
        self.btn_apply = QPushButton("Apply these settings")
        self.btn_apply.setShortcut(QKeySequence("Ctrl+Return"))
        self.btn_apply.setToolTip(
            "send the theme, clock size, canvas, scrim, fans and fps on this "
            "window to the display that is running. Nothing on this window "
            "changes the glass until you press it - and the background clip is "
            "not one of these settings: that goes with the button in the clips "
            "box, because it overwrites what the panel stores")
        self.btn_apply.clicked.connect(self._apply_to_display)
        rowe.addWidget(self.btn_apply)
        llay.addLayout(rowe)
        # One upload button in the whole window, and it lives with the list you
        # pick from.  This box used to carry a second one with the same label and
        # the same action, which meant a clip could look "sent" from either place
        # and neither said whether it had landed.  What this box shows instead is
        # the answer the panel's side of the wire actually gives.
        self.d_stored = QLabel()
        self.d_stored.setWordWrap(True)
        self.d_stored.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.d_stored.setStyleSheet("font-family:monospace;color:#bbb;")
        llay.addWidget(self.d_stored)
        # the daemon's own record of what it did on the port, last six: a queued
        # upload and its verdict.  Without this the window can only say "asked",
        # and an upload that the panel refused looks exactly like one that never
        # left the socket (xigmalcd/control.py:261 keeps the ring).
        self.d_events = QLabel()
        self.d_events.setWordWrap(True)
        self.d_events.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.d_events.setStyleSheet("font-family:monospace;color:#888;")
        llay.addWidget(self.d_events)
        self._adv_hide.append(self.d_events)
        col.addWidget(live)

        theme = QGroupBox("Theme on the glass")
        form = QFormLayout(theme)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def adv_row(label: str, field) -> None:
            """A settings row the advanced switch covers, label and field both.

            The label is made here rather than read back out of the form: a string
            passed to `addRow` is not always reachable as a widget through
            `itemAt(row, LabelRole)` - it came back None, the labels were never
            registered, and the compact form shipped three orphaned words
            (`canvas`, `scrim`, `fans`) over hidden fields. Seen in a render at
            1 919x1 055, missed by the offscreen checks until it was looked for.
            """
            lab = QLabel(label)
            form.addRow(lab, field)
            self._adv_hide.append(lab)
            self._adv_hide.append(field)

        self.theme = QComboBox()
        self.theme.addItems(sorted(render.THEMES))
        self.theme.setCurrentText(self.cfg["theme"])
        self.theme.currentTextChanged.connect(self._theme_chosen)
        _readable(self.theme)
        self.theme.setToolTip(
            "the drawings `xigmalcd` renders itself, from live sensor readings. "
            "The vendor's layouts are not in this list on purpose: this combo picks "
            "what the *loop* draws from this machine's readings, and the five are what "
            "`render.py` draws from them. The daemon does draw 23 of the library "
            "layouts - `xigmalcd --theme Theme_07`, and `--list-themes` prints the set "
            "with the four refused for their canvas and any file with nothing in it to "
            "draw refused for that reason - and the layout editor below previews "
            "those files on this same pane, at a pinned fixture rather than live "
            "readings. docs/themes.md says what the library is and is not, including "
            "that the panel is never handed a layout file (PROTOCOL.md §11).")
        form.addRow("theme", self.theme)
        # the question this combo provokes, answered where it is asked: the
        # `xigmatek-connect-lcd-themes` package is on the machine, so why is not
        # its 27 themes in the list?  Because that package's contents are the
        # vendor's own files - .thm themes, layouts, baked overlays, clips - and
        # this project has measured one use for them: as background media.  It
        # has never sent a .thm, and it cannot draw one.
        # one line shorter than it was, on purpose: this note is what once pushed
        # the controls column's own minimum past its width - 742 of its 744 px,
        # measured in 0.3 - and a column that scrolls by a hand's width because of a
        # footnote is a bad trade.  The full explanation is the combo's tooltip (set
        # just above) and docs/themes.md, which is what the parenthetical points to.
        vendor = QLabel(
            "the five are what this window draws; 23 of the package's layouts reach "
            "the daemon by name instead (docs/themes.md)")
        vendor.setWordWrap(True)
        vendor.setStyleSheet("color:#888;font-style:italic;")
        form.addRow("", vendor)
        self.clock_size = QSpinBox()
        self.clock_size.setRange(16, 96)
        self.clock_size.setValue(self.cfg["clock_size"])
        self.clock_size.valueChanged.connect(self._changed)
        self.clock_size.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Fixed)
        form.addRow("clock size", self.clock_size)
        self.ink_choice = QComboBox()
        # the colours this module's own palette already ships with, so a choice
        # made here can be spelled the same way on the command line
        # (`--text-color amber`) and on the socket (`{"cmd":"text_color",
        # "value":"amber"}`): one name, one meaning, three doors.  A swatch on
        # each entry, because "mint" is a word and the question is about a colour.
        for label, colour in (("theme default", None),
                              ("white", render.WHITE),
                              ("amber", render.AMBER),
                              ("mint", render.ALPHA_MINT),
                              ("cyan", render.CYAN),
                              ("green", render.GREEN),
                              ("red", render.RED),
                              ("dim", render.DIM)):
            # the data is the hex form, so whatever the entry is called on
            # screen, the value the window saves and sends is one spelling
            self.ink_choice.addItem(label, render.ink_hex(colour))
        self.ink_choice.addItem("pick a colour...", None)
        for i in range(self.ink_choice.count() - 1):
            ink = render.parse_ink(self.ink_choice.itemData(i))
            if ink is None:
                continue
            chip = QPixmap(14, 14)
            chip.fill(QColor(ink[0], ink[1], ink[2]))
            self.ink_choice.setItemIcon(i, QIcon(chip))
        self._set_ink_choice(self.cfg.get("text_color") or "")
        self.ink_choice.activated.connect(self._choose_ink)
        self._ink_tip = (
            "the ink of the text this program draws. It changes our own layer "
            "only: the vendor's themes keep their text colour inside their own "
            "files - the package's 23 480x480 layout files carry 106 `textColor` "
            "values, 88 of them `rgba(255, 255, 255, 1)`, and 5 of the 23 use "
            "other colours for at least some of their lettering - and nothing "
            "here sends those files, so what a vendor theme's lettering is stays "
            "a property of that theme. The panel is not asked either: the colour "
            "is baked into the frame before it is uploaded, which is the only "
            "reason this option exists on a device with no readback. `theme "
            "default` leaves each theme's own skin alone, and for `alpha` that "
            "skin is measured: 6 of 6 text colours in the layout ALPHA has "
            "selected are white (PROTOCOL.md §10)")
        self.ink_choice.setToolTip(self._ink_tip)
        _readable(self.ink_choice)
        form.addRow("text colour", self.ink_choice)
        self.canvas = QComboBox()
        # short entries, long explanations in tooltips: a combo sizes itself to
        # its longest item, and an inline explanation here set a floor under the
        # whole column's width that no window could go below
        self.canvas.addItems(["clear", "black"])
        self.canvas.setItemData(0, "transparent OSD frame: the panel keeps "
                                   "playing its stored background behind it. "
                                   "What the vendor does, and the default.",
                                Qt.ItemDataRole.ToolTipRole)
        self.canvas.setItemData(1, "black canvas: the frame is opened on opaque "
                                   "black. A layout theme goes fully opaque this way; "
                                   "three of our five keep their own translucent fills "
                                   "and still show the stored background through them "
                                   "(`--bg black`, docs/usage.md)",
                                Qt.ItemDataRole.ToolTipRole)
        self.canvas.setCurrentIndex(1 if self.cfg["canvas"] == "black" else 0)
        self.canvas.currentIndexChanged.connect(self._changed)
        self.canvas.currentIndexChanged.connect(lambda _i: self._set_player())
        adv_row("canvas", self.canvas)
        self.scrim = QSpinBox()
        self.scrim.setRange(-1, 255)
        self.scrim.setValue(self.cfg["scrim"])
        self.scrim.setSpecialValueText("auto")
        self.scrim.setToolTip("0 needs no plate, 255 a solid one. `auto` uses the "
                              "daemon's rule: a plate only when the clip's mean "
                              "luma is over "
                              f"{BRIGHT_LUMA}/255, at {SCRIM_ON_BRIGHT}.")
        self.scrim.valueChanged.connect(self._changed)
        adv_row("scrim", self.scrim)
        self.fanline = QCheckBox("fan figures")
        self.fanline.setToolTip("draws `CPU FAN nnnn RPM` under the CPU "
                                "temperature and `GPU FAN nn%` under the GPU "
                                "one, and leaves the `fans` array out of the "
                                "metrics blob - the panel never reports its own "
                                "tachs back, so turning this off only removes "
                                "the drawing and the data we send")
        self.fanline.setChecked(self.cfg["fans"])
        self.fanline.stateChanged.connect(self._changed)
        adv_row("fans", self.fanline)

        col.addWidget(theme)
        # ---- the layout editor (docs/theme-editor.md, stage 4) ----------------
        # The model behind this group is `xigmaui/edit.py`, which holds no Qt: that is
        # the only reason the claims here are gates rather than hopes - what one edit
        # moves, what undo owes back, when a file gets written.  Two of its rules
        # decide what is on screen:
        #
        #   * every field this row offers is a key `layout.py` is *proven* to read
        #     (`themes.keys_read()` takes them out of the painter's own source), so the
        #     vendor's unread bookkeeping - `enableMove`, `screenStatus` - is never
        #     offered and survives a save untouched;
        #   * opening writes nothing.  A file appears on Save, because `--theme Name`
        #     finds your copy first and that shadowing is a fact about files, not about
        #     this window: looking at a theme's fields must not quietly change what the
        #     loop draws.
        #
        # It does not fold: the switch is about the knobs a first run does not
        # need, and this is not one of them - it is the only place the window
        # shows the 23 library layouts the themes package installs, and folding
        # it away made the whole point of that package invisible.  The boxes the
        # switch *does* fold moved to the preview column instead, so this one
        # has the room its rows need.
        editor = EditorBox("Layout: edit a file the loop can draw", self._editor_reflow)
        eform = QVBoxLayout(editor)
        head = QFormLayout()
        # installed before anything is added to it: a layout that is built and never
        # put into the box is destroyed at the end of _build(), and with it every
        # widget that was addRow'd into it - which is how the layout and widget
        # pickers vanished without a trace (`tests/test_window.py` walks the editor's box
        # and asks for them by name, because "no exception" is not how you notice a missing control)
        eform.addLayout(head)
        # one growth policy, stated rather than inherited from whatever style
        # this desktop happens to use: every field fills the field column, so a
        # combo is never a strip narrower than the text it is showing.
        head.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.ed_name = QComboBox()
        # `themes.scan()` is already user-first, so a name that has been edited appears
        # once and opens the copy: reopening continues rather than starting over.  The
        # first entry gives the pane back to the live theme preview.
        self.ed_name.addItem(NO_EDITOR)
        self.ed_name.addItems(sorted(themes.EXPORTS))
        self.ed_name.addItems([r["name"] for r in themes.scan()[0]])
        self._ed_box_readable(self.ed_name)
        # The counts in this sentence are read out of the library rather than remembered:
        # it said "three generated layouts" after `alpha` and `bars` joined the exports, and
        # nothing noticed, because the numbers were typed in prose.  The GUI section asserts
        # every number in it against `themes.EXPORTS` and `themes.scan()`, and it is the same
        # pair `--list-themes` prints, so the window and the CLI cannot disagree about how
        # many layouts there are.
        # The counts in this sentence are read out of the library rather than remembered:
        # it said "three generated layouts" after `alpha` and `bars` joined the exports, and
        # nothing noticed, because the numbers were typed in prose.  The GUI section asserts
        # every number in it against `themes.EXPORTS` and `themes.scan()`, and it is the same
        # pair `--list-themes` prints, so the window and the CLI cannot disagree about how
        # many layouts there are.
        self.ed_name.setToolTip(self._ed_combo_tip())
        self.ed_name.currentTextChanged.connect(self._editor_open)
        _readable(self.ed_name)
        # The two doors that decide **which file this box holds** - as opposed to the three
        # below, which act on the file it already holds.  They are here because a report said
        # "I have no way of opening & loading a previously saved layout", and both halves of
        # that were true.  The menu was built once at startup and rebuilt only after a rename,
        # a save-as or a revert *in this window*, so a copy written by the CLI, by a second
        # window, or by hand into `~/.config/xigmalcd/themes` stayed invisible until a
        # restart.  And a layout file outside the roots the library reads - one copied off
        # another machine, the `<name>.json.bak` a save leaves behind, an `--export-theme`
        # printout - could not be opened at all.
        self.ed_reload = QPushButton("reload the list")
        self.ed_reload.setToolTip(
            "re-read the roots this window lists layouts from - yours first, then this "
            "checkout's, then the installed package - and rebuild the menu.  What is open "
            "stays open, unsaved edits and all: the menu is rebuilt with its signals "
            "blocked, so the layout in memory is never read back off disk.  The line under "
            "the menu says what the re-read found.")
        self.ed_reload.clicked.connect(self._ed_reload_layouts)
        self.ed_open = QPushButton("open a file…")
        self.ed_open.setToolTip(
            "open one layout file by path, wherever it is.  **Opening writes nothing**, here "
            "or in the file.  A file the roots do not hold previews and edits normally, and "
            "`save as your copy` is what puts it under ~/.config/xigmalcd/themes - which is "
            "also what lets `apply to the panel` name it: applying sends a *name*, and the "
            "display reads whatever file that name answers in the roots *it* can see.  The "
            "line under the menu says which file a layout came from.")
        self.ed_open.clicked.connect(self._ed_open_file)
        self._ed_paths: dict = {}       # name -> the path this window opened it from
        self.ed_state = QLabel("not editing: the pane shows the theme above, drawn from "
                               "this machine's readings")
        self.ed_state.setStyleSheet("color:#888;font-style:italic;")
        self.ed_state.setWordWrap(True)
        head.addRow("layout", self.ed_name)
        head.addRow("", self.ed_state)
        # under the menu they act on, and in the form's field column, which that menu already
        # makes wider than both buttons together - so this costs the column no floor
        orow = QHBoxLayout()
        orow.addWidget(self.ed_reload)
        orow.addWidget(self.ed_open)
        orow.addStretch(1)
        head.addRow("", orow)
        # The two doors that choose *which file this box holds* go under the menu they
        # affect, not down with the three that act on the file it already holds.  They are
        # in the form's field column, which the menu already makes wider than both of them
        # together, so they cost the column no floor.
        orow = QHBoxLayout()
        orow.addWidget(self.ed_reload)
        orow.addWidget(self.ed_open)
        orow.addStretch(1)
        head.addRow("", orow)

        self.ed_widget = QComboBox()
        self.ed_widget.setToolTip("one widget of this layout: its kind, what it shows, "
                                  "and where it sits")
        self.ed_widget.currentIndexChanged.connect(self._editor_pick_widget)
        head.addRow("widget", self.ed_widget)

        # Every field the model lists for the selected widget gets a row of its own:
        # there is no `field` menu left to open to find out what a widget carries.
        # Which control a row uses is still not a guess made here - `edit.choices()`,
        # `edit.number_fields()` and `edit.COLOUR_FIELDS` decide menu / spinbox /
        # checkbox / colour picker, the same dispatch the single value box ran on,
        # applied one row at a time.
        #
        # The rows live in a grid that reflows between one, two and three columns
        # depending on the width this splitter happens to give the box (see
        # `EditorBox`), so the 18 rows of an `arc` widget stand a different height in
        # every one of those layouts.  No figure for that height is kept here on
        # purpose: it follows the faces installed, and the pair this comment used to
        # carry - one bench's and one runner's - went stale the day the pane grew a
        # row of buttons.  `python3 -m unittest tests/test_window_sizing.py` prints
        # what this machine measures, at three window widths, and the same gate holds
        # the rule that does not move: the reflow buys height rather than pushing a
        # scrollbar under the column, which is the failure mode 0.5 was written to
        # catch.
        self._ed_host = QWidget()
        self.ed_grid = QGridLayout(self._ed_host)
        self.ed_grid.setContentsMargins(0, 0, 0, 0)
        self.ed_grid.setHorizontalSpacing(10)
        eform.addWidget(self._ed_host)
        self.ed_rows: dict = {}         # field -> (label, host, control, swatch, kind)
        self._ed_focus: dict = {}       # control id -> the field it edits
        self._ed_says: dict = {}        # field -> the sentence that row explains
        self._ed_had: dict = {}         # field -> does the file actually carry this key
        self._ed_kind = ""              # the kind those rows were built for
        self._ed_cols = 1

        for box in (self.ed_name, self.ed_widget):
            box.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)

        brow = QHBoxLayout()
        self.ed_undo = QPushButton("undo")
        self.ed_undo.setToolTip("back one edit. A run of keystrokes in one row is "
                                "one step, not one per press")
        self.ed_undo.clicked.connect(self._editor_undo)
        self.ed_save = QPushButton("save as your copy")
        self.ed_save.setToolTip(
            "write this layout to ~/.config/xigmalcd/themes/<name>.json - the one place "
            "an edited theme lives, and the file `--theme <name>` finds first. The two "
            "vendor trees are refused, and so are the five drawn-from-code names: a "
            "saved `gauge.json` would be a second `theme_gauge` (docs/limits.md)")
        self.ed_save.clicked.connect(self._editor_save)
        self.ed_revert = QPushButton("revert")
        self.ed_revert.setToolTip("drop your copy: the loop reads the vendor's file "
                                  "again. What you typed stays in this window, and the "
                                  "line above says so")
        self.ed_revert.clicked.connect(self._editor_revert)
        brow.addWidget(self.ed_undo)
        brow.addWidget(self.ed_save)
        brow.addWidget(self.ed_revert)
        # The one act here that reaches the glass rather than the file, on its own row for
        # the same measured reason as the rows above: this column's floor is read back off
        # the widest thing it holds, and a longer label is a wider floor for the column.
        prow = QHBoxLayout()
        self.ed_apply_panel = QPushButton("apply to the panel")
        self.ed_apply_panel.setToolTip(self._ed_apply_panel_tip())
        self.ed_apply_panel.clicked.connect(self._apply_layout_to_display)
        prow.addWidget(self.ed_apply_panel)
        prow.addStretch(1)
        # a row of its own across the whole width: three buttons squeezed into a
        # field column is what put a 357 px floor under the whole controls column
        # (measured) while the labels and fields needed barely more
        eform.addLayout(brow)
        eform.addLayout(prow)

        # The two acts that invent a name.  The box holds the name to give, not the name
        # that is: a reader who has just typed a new one should not have it replaced under
        # their cursor, and the window only refills it when a *different* layout is opened
        # (`_editor_state` compares the name it last showed).  Short labels for the same
        # reason as the row above: this column's floor is measured from what it holds, and
        # every sentence about what these do lives in the tooltip before the press and in
        # the model's own words after it.
        nrow = QHBoxLayout()
        self.ed_newname = QLineEdit()
        self.ed_newname.setPlaceholderText("a name for this copy")
        # deliberately no `maxLength`.  A box that stops at the writer's limit would drop
        # the characters a person typed - silently, and then press the rename button with a
        # name that is not the one they typed.  The name belongs to them, so it goes to the
        # door whole and comes back as `theme name '…' is longer than 64 characters`.
        self.ed_newname.setToolTip(self._ed_name_tip())
        self.ed_rename = QPushButton("rename")
        self.ed_rename.setToolTip(self._ed_rename_tip())
        self.ed_rename.clicked.connect(self._editor_rename)
        self.ed_copy = QPushButton("save as")
        self.ed_copy.setToolTip(self._ed_copy_tip())
        self.ed_copy.clicked.connect(self._editor_copy)
        nrow.addWidget(self.ed_newname)
        nrow.addWidget(self.ed_rename)
        nrow.addWidget(self.ed_copy)
        eform.addLayout(nrow)

        # The structural controls, on a row of their own for the same reason.  Their
        # labels are short and the sentence goes where it does the work: in the tooltip
        # before the press, and in the model's own words under the rows after it.  A
        # wider label here is a wider floor for the whole column, which the sizing gate
        # reads back off this pane rather than from a remembered number.
        srow = QHBoxLayout()
        self.ed_add = QToolButton()
        self.ed_add.setText("add")
        self.ed_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.ed_add_menu = QMenu(self.ed_add)
        self.ed_add.setMenu(self.ed_add_menu)
        self.ed_add.setToolTip(
            "insert one row of a kind you choose from this menu.  A new row is always a "
            "copy of a row that already draws - this layout's own row of that kind if it "
            "has one, otherwise a real row from the 28 layouts the editor opens - because "
            "the vendor's application bundles are not in this tree, so the files are the "
            "only evidence this program has of what a row of a kind looks like.  Each "
            "entry says which row it copies")
        self.ed_del = QPushButton("remove")
        self.ed_del.setToolTip(
            "take the selected row out.  The last row of a layout cannot be removed: "
            "emptying the list is a hard problem for the library - there is nothing "
            "to draw, which is not the same as an empty canvas")
        self.ed_del.clicked.connect(self._editor_delete_row)
        self.ed_up = QPushButton("up")
        self.ed_up.setToolTip("draw this row one place earlier.  The list *is* the draw "
                              "order, so an earlier row is painted under the next one")
        self.ed_up.clicked.connect(lambda: self._editor_move_row(-1))
        self.ed_down = QPushButton("down")
        self.ed_down.setToolTip("draw this row one place later, so it paints over the row "
                                "it used to sit under")
        self.ed_down.clicked.connect(lambda: self._editor_move_row(+1))
        for _b in (self.ed_add, self.ed_del, self.ed_up, self.ed_down):
            srow.addWidget(_b)
        srow.addStretch(1)
        eform.addLayout(srow)

        self.ed_note = QLabel()
        self.ed_note.setWordWrap(True)
        self.ed_note.setStyleSheet("color:#999;font-style:italic;")
        eform.addWidget(self.ed_note)
        self.ed_group = editor    # `tests/test_window.py` and `test_snapping.py` name it
        col.addWidget(editor)
        self.ed = None                        # nothing open until a name is picked
        self._ed_notes = {}                   # what the last editor frame reported
        self._ed_named = ""                   # the name the box above was filled with
        self._drag = None                     # (px, py, row x, row y) while dragging
        self._drag_refused = False            # a drag that ran into the canvas edge
        self._drag_note = ""                  # and the sentence it was refused with
        self._resize = None                   # (px, py, edge, row, box) while resizing a row
        self._resize_ask = (0, 0)             # the distance its last move showed
        self._resize_note = ""                # and the last refusal said during that drag
        self._resize_over = ""                # plus what lay under the handle being dragged
        self._resize_target = None            # the ask it is painting, box or nothing
        # What a move drag may be pulled onto.  The model finds these lines by drawing one
        # frame - a row's own ink width comes from the painter - so they are asked once per
        # press and held for the length of the drag, because a motion event cannot afford a
        # frame of its own.  The guide is what the pane paints of them, and `_snap_said` is
        # the model's own sentence about the pull, shown rather than paraphrased.
        # What the pane is *looking at* while a layout is open (feature G): None means
        # the pinned fixture, which is what every geometry door uses and what every
        # byte-for-byte claim in `tests/` is made against.  A dict here holds a body of
        # readings, the instant they are drawn at (always the pinned one) and when they
        # were read; it is never written to the session file.
        self._peek = None
        self._snap_lines = None               # {axis: [(number, what the line is)]}
        self._snap_guide = ()                 # ((axis, panel px), ...) taking hold right now
        self._snap_said = ""                  # the model's words for that pull
        self._off_glass = ""                    # what the last marks said about ink
        # nothing to edit until a layout is open: a row that offers fields before there
        # is a file behind it is a row that will write to nothing
        self._ed_set_enabled(False)

        media = QGroupBox("Background: the layer under our frame")
        mlay = QVBoxLayout(media)
        # the library is 40 rows - 46 mp4 files tracked here, 6 of them copies of a
        # row already standing; 204 files on a bench that has the .deb installed and the
        # mounted, and the row you want is a scroll wheel and a search away:
        # one filter field, matching what a row already shows (name, size, loop
        # length, where it came from), so finding a clip does not need a terminal
        self.clip_filter = QLineEdit()
        self.clip_filter.setPlaceholderText("filter: name, size, length or origin")
        self.clip_filter.setClearButtonEnabled(True)
        self.clip_filter.textChanged.connect(self._filter_clips)
        mlay.addWidget(self.clip_filter)
        self.clips = QListWidget()
        # 64 px icons, not 112: a row's height follows the icon, and 112 px rows
        # meant 114 px per clip - the list viewport showed two clips at a 1 055 px
        # window.  Measured with the same call after the change: 66 px rows.
        # `Fixed` + `uniformItemSizes` because the shipped `Adjust` mode lays the
        # rows out in a grid against the viewport, which is what made one selected
        # row paint as a block taller than the list itself.
        self.clips.setIconSize(CLIP_ICON)
        self.clips.setResizeMode(QListWidget.ResizeMode.Fixed)
        self.clips.setUniformItemSizes(True)
        # elide rather than scroll: a horizontal bar inside a column that also
        # scrolls vertically is very hard to use
        self.clips.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.clips.currentItemChanged.connect(self._clip_chosen)
        # the list is the reason this column exists, and a column that is shorter
        # than four rows makes it useless: let the column scroll instead of
        # squeezing the picker into a strip
        self.clips.setMinimumHeight(150)
        mlay.addWidget(self.clips, 1)
        self.clip_info = QLabel()
        self.clip_info.setWordWrap(True)
        mlay.addWidget(self.clip_info)
        # the send-state, in one line the eye lands on: what the panel stores
        # now, and whether this selection is on it.  `_refresh_clip_state` owns
        # the words; the box title and the button label follow the same rule.
        self.clip_state = QLabel()
        self.clip_state.setWordWrap(True)
        self.clip_state.setStyleSheet("font-family:monospace;")
        mlay.addWidget(self.clip_state)
        # The pairing, said where the clip is chosen rather than in the editor's box: it
        # is the background's business, not the layout fields'.  One button, because a
        # flag a reader sets by accident needs the way back in the same place.
        self.pair_state = QLabel()
        self.pair_state.setWordWrap(True)
        self.pair_state.setStyleSheet("color:#888;font-style:italic;")
        mlay.addWidget(self.pair_state)
        # The opt-out, as a box you can see and tick, rather than a flag set behind your
        # back by a click on the list.  That is the whole of the 0.4 change: a layout's own
        # background arrives automatically, and the only way it does not is this control -
        # whose state is therefore always something the reader chose to be true.
        self.chk_keep = QCheckBox("keep my background")
        self.chk_keep.setToolTip(
            "unticked, the default: choose a layout and the background it names in its own "
            "file goes under the preview, and the row is marked for you.  Ticked: the clip "
            "under the preview stays wherever you left it, and a layout that names another "
            "one says so in the note line and the log instead of moving it.  Nothing else "
            "in the window ticks this box. Each of the five themes this repo draws from "
            "`render.py` names the backdrop its own published picture sits over "
            "(`themes.CODE_CLIPS`), so they pair as well; a layout you authored yourself "
            "names none, and with one of those open the pairing has nothing to do "
            "(docs/themes.md, PROTOCOL.md \u00a711)")
        self.chk_keep.setChecked(self.keep_clip)      # before the connect: no fake click
        self.chk_keep.toggled.connect(self._keep_toggled)
        mlay.addWidget(self.chk_keep)
        self.btn_pair = QPushButton("Use this layout's own clip")
        self.btn_pair.setToolTip(
            "a vendor layout names one background clip in its own file, and the window "
            "follows that pairing unless you tick \"keep my background\" here.  This puts "
            "the layout's own clip back and unticks the box, so it follows again from now "
            "on. Each of the five themes this repo draws from `render.py` names the "
            "backdrop its own published picture sits over, so they pair as well; a layout "
            "you authored yourself names none, and with one of those open the pairing has "
            "nothing to do (docs/themes.md, PROTOCOL.md \u00a711)")
        self.btn_pair.clicked.connect(self._use_pair)
        self.btn_pair.setEnabled(False)
        mlay.addWidget(self.btn_pair)
        row = QHBoxLayout()
        self.btn_upload = QPushButton("Send this background to the panel")
        # Ctrl+Shift+U rather than Ctrl+U, because of what the field directly
        # above this button is for.  Measured offscreen: while the button held a
        # bare Ctrl+U, pressing it in the filter row *queued an upload* and left
        # the field alone - the reader's keystroke (Ctrl+U is readline's "kill the
        # line", and Qt's own QLineEdit binds nothing there) went to the panel
        # path instead.  On Ctrl+Shift+U the button still fires and the field is
        # untouched.
        self.btn_upload.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.btn_upload.clicked.connect(lambda: self.queue(
            "upload", path=self.mp4,
            # the two upload knobs come from the protocol module rather than
            # literals here: 0.02 s and 1000 B are measured wire facts, and a
            # second copy in the GUI could drift away from the measurement
            gap=protocol.MEDIA_GAP, chunk=protocol.MEDIA_CHUNK,
            fans=self.fanline.isChecked()))
        row.addWidget(self.btn_upload)
        self.btn_frame = QPushButton("One frame now")
        self.btn_frame.setToolTip(
            "with a display running: ask it for a single frame, queued for its "
            "own frame loop.  With none running: render this window's preview "
            "frame and put it on the glass as one `.osd` upload.  Either way "
            "the OSD layer only - the panel's stored background is untouched")
        self.btn_frame.clicked.connect(lambda: self.queue(
            "frame", theme=self.theme.currentText(), kw=self._render_kw(),
            fans=self.fanline.isChecked()))
        row.addWidget(self.btn_frame)
        mlay.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        mlay.addWidget(self.progress)
        lcol.addWidget(media, 9)        # the list is why this column exists

        status = QGroupBox("Panel status (what conn 1 reports)")
        slay = QVBoxLayout(status)
        self.status = QLabel("not asked yet")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setStyleSheet("font-family:monospace;")
        slay.addWidget(self.status)
        rrow = QHBoxLayout()
        self.btn_status = QPushButton("Refresh")
        self.btn_status.clicked.connect(lambda: self.queue("status"))
        rrow.addWidget(self.btn_status)
        self.btn_live = QPushButton("Send frames for 30 s")
        # 2 fps for 30 s is 60 uploads, inside one session on both axes
        # (main.SESSION_MAX uploads, main.SESSION_TTL seconds); panel._live
        # renews the session if a longer run ever needs it.
        self.btn_live.clicked.connect(lambda: self.queue(
            "live", theme=self.theme.currentText(), kw=self._render_kw(),
            fps=2.0, seconds=30, fans=self.fanline.isChecked()))
        rrow.addWidget(self.btn_live)
        self._adv_hide.append(self.btn_live)
        slay.addLayout(rrow)
        self.status.setMinimumHeight(70)
        self.status_box = status
        # the foot of the preview column, not the controls column and not the
        # library: `conn 1` answers with fourteen fields and they wrapped to
        # about ten lines in a 300 px column, height taken straight off the
        # clip list.  The preview column has a 480 px picture and, above a
        # short window, slack below it that nothing else can honestly fill (the
        # frame is never scaled up), and the same fields wrap to fewer lines at
        # that column's ~530 px.  Behind the advanced switch with the reset box,
        # so neither pushes anything away.
        self._adv_hide.append(status)

        danger = QGroupBox("Factory reset")
        dlay = QVBoxLayout(danger)
        warn = QLabel("The vendor's `recovery`: the panel goes back to its "
                      "default state and the USB device re-enumerates. Uploads "
                      "after it start with `1 400` until we reconnect.")
        warn.setWordWrap(True)      # unwrapped, this label demanded 876 px of
        dlay.addWidget(warn)        # width and set a floor under the column
        row2 = QHBoxLayout()
        self.confirm = QLineEdit()
        self.confirm.setPlaceholderText("type the word reset to enable")
        self.confirm.textChanged.connect(lambda t: self.btn_reset.setEnabled(
            t.strip().lower() == "reset"))
        row2.addWidget(self.confirm)
        self.btn_reset = QPushButton("Reset the panel")
        self.btn_reset.setEnabled(False)
        self.btn_reset.clicked.connect(self._do_reset)
        row2.addWidget(self.btn_reset)
        dlay.addLayout(row2)
        self.reset_box = danger   # `tests/test_window.py` names it from outside the class
        self._adv_hide.append(danger)
        # The tail of the column: without it, QBoxLayout shares a tall window's
        # leftover height out between every box, so a one-line note label came
        # back 249 px tall (measured) and the controls column grew a blank band
        # under it - the same slack that padding the group boxes with is trying
        # to fill.  Let the boxes have their natural heights and the empty part
        # be plainly at the bottom, where nothing has to explain it.
        col.addStretch(1)

        self.log_view = QLabel()
        self.log_view.setWordWrap(True)
        self.log_view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.log_view.setStyleSheet("font-family:monospace;color:#999;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.log_view)
        # the log is a wrapped label: it must never grow its own width, which is
        # what a word-wrapped QLabel inside a resizable scroll area tends to do
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_scroll = scroll
        slog = QGroupBox("Log")
        slog.setLayout(QVBoxLayout())
        slog.layout().addWidget(scroll)
        self.log_box = slog
        scroll.setMinimumHeight(84)
        # the log goes under the picture, not at the end of the controls stack:
        # the preview column has room below a 480 px frame that nothing else can
        # honestly fill (the picture is never scaled up), while the library column
        # is where the height is scarce - every pixel there is another clip row.
        # `1` against the frame's `0`: the picture takes exactly what a square of
        # the pane's width is, and the log gets whatever height that leaves.
        lay.addWidget(slog, 1)
        # the two boxes the switch folds go under the log, in this column: the
        # calls come after the log's so the order down the column is picture,
        # caption, metrics, log, reset, status.  Their double guard - the word
        # `reset` typed before the button wakes - is a property of the box, not
        # of its position or visibility: folded away, the button is hidden
        # *and* disabled; shown, it is still disabled until the word is typed.
        lay.addWidget(danger)
        lay.addWidget(status)

        split = QSplitter()
        # The preview column gets exactly the room the picture can use and no
        # more.  `_fit()` refuses to scale the 480x480 frame above 1:1 (pixels
        # the glass does not have would only be a bigger lie), so on a 2 259 px
        # window a 440 px share for the left pane meant ~1 000 px of it and a
        # very wide caption for a 480 px picture, while the clip list and the
        # status boxes - the parts you actually work with - were squeezed.  The
        # cap is the frame plus the pane's own chrome; the splitter still
        # drags the preview down to a 160 px thumbnail, and where it lands is
        # remembered (settings.py's `split`).
        pane = _scroll(left)
        pane.setMinimumWidth(200)
        pane.setMaximumWidth(render.W + PANE_CHROME)
        # the other side of the same rule: a handle dragged to the right can
        # otherwise eat the controls column until its wrapped labels and two
        # buttons per row are unreadable, and the window then has an invisible
        # half rather than a narrow one
        controls = _scroll(right)
        controls.setMinimumWidth(300)
        library = _scroll(lib)
        library.setMinimumWidth(320)
        split.addWidget(pane)
        split.addWidget(controls)
        split.addWidget(library)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        split.setCollapsible(2, False)
        split.setStretchFactor(1, 2)
        split.setStretchFactor(2, 3)
        split.setSizes(self.cfg["split"])
        split.splitterMoved.connect(lambda *_a: self.save_timer.start())
        self.split = split
        self.setCentralWidget(split)
        # order matters here: the list has to exist before the send-state line
        # can say which row, if any, the display reports is on the panel
        self.statusBar().showMessage(f"port {self.port}")
        self._populate_clips()
        self._refresh_clip_state()
        # the columns' floors, once the rows they hold exist: the clip list's width
        # is what its longest row needs, and that is not known before the walk
        self._pane_floors()
        # the switch's initial position: setChecked() above ran before the
        # `toggled` connect, so the folding has to be applied here as well
        self._set_advanced(self.adv_toggle.isChecked())
        # ...and the same for the display's widgets, at the end rather than where the
        # display's own box is built: that list names a control in the editor's box, and
        # the editor is built after this point in one pass through `_build`.  With the call
        # where it used to sit, the list named a widget that did not exist yet - which the
        # suite caught as `AttributeError: 'Window' object has no attribute
        # 'ed_apply_panel'` printed from inside `_build`, in every window, on the first run
        # of this change.  Nothing is enabled by this: no display has been polled yet, so
        # the answer is still "off", and the poll that finds one turns it on.
        self._set_display_widgets(False)

    #: The three columns' own floors, in pixels: the preview is the one the picture
    #: can shrink inside (the cap in `_build` is its other half), and the two text
    #: columns are what a wrapped label plus a readable control need.  Those are only
    #: lower bounds - `_pane_floors` raises each one to what the column's own contents
    #: measure - and `tests/test_window_sizing.py` reads both halves back at the window's
    #: own floor and fails if a column ever gets less than what it holds.  That is the
    #: 0.4 defect: the controls column sitting on its 300 px floor while its contents
    #: measured 375 px, so it grew a horizontal scrollbar inside itself.
    PANE_FLOORS = (200, 300, 320)

    #: How many times the floors may be re-measured before the window stops chasing them.
    #: A floor is derived from the contents and the contents move when the floor does, so
    #: one pass cannot see its own effect - but a chain that never settles is a defect in
    #: the sizing rule, not something to keep iterating on.  See `_pane_floors`.
    _FLOOR_PASSES = 4
    _floor_pass = 0

    def _pane_floors(self, settling: bool = False) -> None:
        """No column narrower than what it holds, by construction rather than by hope.

        A pane whose minimum is its contents' minimum cannot be dragged under them, so
        the sideways scrollbar the 0.4 window shipped with is not something a later
        change has to remember to avoid - it is unreachable.  The measured contents are
        used rather than remembered constants because they follow the fonts of the
        machine (the library column is 359 px on the author's bench and 376 px on CI's
        runner) and the number of editor rows the width just allowed - and because a
        closed drop-down has to *show* the widest entry it holds, which is what
        `_ed_box_readable` arranges for the two boxes at the top of the editor.  It also
        reserves the extent of a vertical scrollbar, because that width comes off the
        viewport rather than off the contents - see the comment in the loop.

        The pass is repeated once on the event loop, and that is not decoration: the
        floor is read from the contents, and the contents change when this very call
        makes the splitter redistribute width and the field grid re-flow into another
        number of columns.  A single pass can therefore only see the state before it -
        CI's runner found a 366 px column floor under 380 px of contents, which is the
        overflow this function exists to prevent.  `_FLOOR_PASSES` bounds the follow-ups,
        so a floor that keeps moving fails `tests/test_window_sizing.py` rather than looping
        that runs; a pass that changes nothing ends the chain.
        """
        changed = False
        for i, floor in enumerate(self.PANE_FLOORS):
            area = self.split.widget(i)
            if area is None:
                continue
            inner = area.widget()
            need = inner.minimumSizeHint().width() if inner is not None else 0
            # A pane is a scroll area, so the width its *contents* need is not the width
            # the *viewport* gets: a vertical scrollbar takes its extent off the width.
            # Ignoring that is how 0.5's own fix produced a new instance of the 0.4 bug -
            # a 411 px floor around 411 px of contents, a 397 px viewport, and 14 px of
            # horizontal travel under the editor's rows.  The bar is reserved whether or
            # not it is showing, and that is not laziness: those states chase each other.
            # Pinning a column narrower re-flows the rows into fewer columns, the rows get
            # taller, the bar arrives, the width goes - so the state a floor is measured in
            # is not the state it gets used in, and a minimum that depends on which of them
            # Qt happened to decide last is a minimum that can be wrong.  The extent is the
            # style's number to know, and a column pays for it once.
            if (need and area.verticalScrollBarPolicy()
                    != Qt.ScrollBarPolicy.ScrollBarAlwaysOff):
                need += area.verticalScrollBar().sizeHint().width()
            want = max(floor, need)
            if want != area.minimumWidth():
                area.setMinimumWidth(want)
                changed = True
        if changed:
            if not settling:
                self._floor_pass = 0      # a change the reader made: a fresh budget
            if self._floor_pass < self._FLOOR_PASSES:
                self._floor_pass += 1
                QTimer.singleShot(0, self._settle_floors)
        else:
            self._floor_pass = 0

    def _settle_floors(self) -> None:
        """Measure the floors again, now that the last change has been laid out."""
        self._pane_floors(settling=True)

    def _ed_box_readable(self, box: QComboBox) -> int:
        """Make one editor head box wide enough to show the widest entry it holds.

        `_ed_shrink` lets a row's control give way, and that is right for a form of
        eighteen of them; it is not right for the two boxes that say *which layout* is
        open and *which row* you are editing, because the text they carry all the time is
        the reader's orientation, and an elided `data  Motherboard Tempe…` in the closed
        box is the same complaint the popup width was opened to answer, one widget later.
        So the box asks for its longest entry plus the furniture the popup gets from
        `_readable` (frame, margins, the arrow, a scrollbar the list may need), and
        `_pane_floors` then raises the column to whatever that costs - which is why this
        is not the 0.4 bug returning: the 0.4 window had a 300 px floor and 375 px of
        contents, and the column simply overflowed.

        Returns the width asked for, so the caller can say what it did.
        """
        met = box.view().fontMetrics()
        wide = max((met.horizontalAdvance(box.itemText(i))
                    for i in range(box.count())), default=0)
        box.setMinimumWidth(wide + 60 + box.iconSize().width() if wide else 0)
        return wide

    # ---- preview ---------------------------------------------------------
    # ---- the text colour -------------------------------------------------
    def _set_ink_choice(self, value) -> None:
        """Select the entry for a colour, adding one if nothing matches.

        Matched on the parsed colour rather than the label, so `#ffc400` read
        back from a settings file or from a running display's `status` lands on
        the `amber` entry instead of standing beside it as a second name for the
        same colour.  Colours outside the palette - one chosen with the dialog,
        one another user set on the display - get their own entry, labelled with
        the hex and carrying its swatch.
        """
        ink = render.parse_ink(value)
        if ink is None:
            self.ink_choice.setCurrentIndex(0)
            return
        hexv = render.ink_hex(ink)
        for i in range(self.ink_choice.count()):
            if render.ink_hex(render.parse_ink(self.ink_choice.itemData(i))) == hexv:
                self.ink_choice.setCurrentIndex(i)
                return
        chip = QPixmap(14, 14)
        chip.fill(QColor(ink[0], ink[1], ink[2]))
        self.ink_choice.insertItem(self.ink_choice.count() - 1, QIcon(chip),
                                   hexv, hexv)
        self.ink_choice.setCurrentIndex(self.ink_choice.count() - 2)
        _readable(self.ink_choice)     # the new entry is a hex spelling: wider

    def _choose_ink(self, index: int) -> None:
        """A palette entry is a choice; the last row opens the colour dialog."""
        if index != self.ink_choice.count() - 1:
            self._changed()
            return
        was = self.ink_choice.currentIndex()
        had = render.parse_ink(self.ink_choice.itemData(was)) or render.WHITE
        got = QColorDialog.getColor(QColor(had[0], had[1], had[2]), self,
                                    "Text colour")
        if not got.isValid():              # cancelled: put the old choice back
            self.ink_choice.setCurrentIndex(was)
            return
        self._set_ink_choice(got.name(QColor.NameFormat.HexRgb))
        self._changed()

    def _ink(self):
        """The chosen colour as (r,g,b,a), or None for the theme's own skin."""
        if self.ink_choice.currentIndex() < 1:
            return None
        return render.parse_ink(self.ink_choice.currentData())

    def _render_kw(self) -> dict:
        """The options `render.draw` takes, taken from the widget state.

        The scrim rule is the daemon's, thresholds and all: `main._scrim_for`
        only knows the handful of clips `CLIP_LUMA` measured, and this picker
        can reach any file on the box, so the GUI measures the luma itself and
        applies the same two constants (`BRIGHT_LUMA` where white-on-white
        starts, `SCRIM_ON_BRIGHT` how much plate fixes it).
        """
        theme = self.theme.currentText()
        want = self.scrim.value()
        if want < 0:
            if self.canvas.currentIndex():          # black canvas: nothing shows through
                want = 0
            else:
                lum = clipdb.luma(self.bg_frame) if self.bg_frame else 0.0
                want = SCRIM_ON_BRIGHT if lum > BRIGHT_LUMA else 0
        kw = {"bg": render.BLACK if self.canvas.currentIndex() else render.OVERLAY,
              "clock_size": self.clock_size.value(),
              "ink": self._ink(),
              "fan": self.fanline.isChecked(), "source": "temperature"}
        # themes take different options, exactly as `main._theme_kwargs` finds
        # out by reading the signature rather than keeping a table of them.
        # `scrim` stays outside that filter: `draw` takes it, not the theme.
        params = inspect.signature(render.THEMES[theme]).parameters
        return {k: v for k, v in kw.items() if k in params} | {"scrim": want}

    def _preview_tick(self) -> None:
        """What `preview_timer` actually calls: a repaint, unless the reader is dragging.

        While a canvas drag or a canvas resize drag is in flight, the pointer owns the
        picture: every move event already repainted the layer, from the same pinned
        fixture, with the same file.  So a tick arriving in that moment repaints pixels
        that cannot differ from the ones on screen, and pays for the most expensive call
        in the program to do it - `sensors.collect()`, 189.9 ms on the author's bench,
        100.3 ms for the tick overall.  That is what "laggy" feels like when it is not the
        move itself: a stall in the middle of a drag, once every `--preview-fps` seconds,
        for a frame the drag has already drawn.

        The release repaints with a read, so the line under the picture is fresh again the
        moment the drag ends; nothing here holds a caption back past the pointer.
        `tests/test_canvas.py` counts the paints a tick makes - with a drag in flight and
        without one - rather than timing anything, because a duration belongs to a box.
        """
        if self._drag or self._resize:
            return
        self._repaint()

    def _repaint(self, readings: bool = True) -> None:
        """Redraw **our layer** from fresh readings, then show it.

        This is the expensive half, and it is deliberately the only half tied to
        `--preview-fps` (through `_preview_tick`, which stands down while a canvas drag
        owns the picture): `sensors.collect()` is 71.8 ms and `render.draw` another
        11.9 ms measured here, so a tick of this costs ~84 ms.  The background does
        not move at this rate and never should have: it plays on `bg_timer`, at the
        file's own rate, compositing over the layer cached here (`self._osd`).
        Before that split the pane's redraw rate *was* the animation rate, and a
        24 fps clip at the default 2 fps - or the author's own saved 1 fps - was a
        slideshow, which is what "it stutters at about 1 fps" meant.

        `readings=False` is for an act the reader made with a layout open: a drag, a
        held arrow key, one field written.  With an editor in the pane the picture
        **is** the file painted at the pinned fixture, so the one part of a tick that
        costs the most paints nothing at all - it only colours the line under the
        picture, which keeps the body this tick did not read.  Measured on the author's
        bench, and the reason the parameter exists: 189.9 ms for `sensors.collect()`
        against 10.3 ms for the layout paint, so a dragged row followed the cursor
        about five times a second.  `tests/test_canvas.py` counts the reads an act
        makes - a count, never a duration, because a duration belongs to a box - and
        guards the other side of it: the `preview_timer` tick and the live pane with
        no layout open still read, so the line under the picture cannot freeze.
        """
        m = sensors.collect() if readings else (self._last or {})
        self._last = m
        theme = self.theme.currentText()
        if self.ed is not None:
            # The pane shows *the layout being edited, as this window holds it* - the file's
            # object, saved or not - at the pinned fixture, through `themes.draw`.  The frame
            # loop paints that same layout from disk with `themes.paint`, and the two are one
            # painter, `themes._overlay`, which is what makes this pane's picture the glass's
            # picture rather than a resemblance of it.  It used to be a resemblance and not a
            # fact: the two doors each built their own value table, one filled the keys the
            # `special` rows read and the other did not, and a layout saved here and applied
            # lost two rows on the panel while every picture in this window still showed them.
            # `tests/test_specials.py` now paints a saved layout through both doors and asks for
            # zero differing px.  Not a detail either way: a preview that moved with this
            # machine's readings would make it impossible to tell an edit from a
            # temperature, and the whole claim of the editor is that a field change is
            # the only thing that can move a pixel.
            #
            # `ink` goes to the same door the code drawing uses, and only `Editor.paint`
            # decides whether it can be honoured: for one of the five names generated from
            # `render.py` the theme has a declared skin and the preview follows the
            # reader's colour, for a vendored or saved file the colours are the file's.
            # Both halves of that are measured, not asserted - `tests/test_ink.py` paints
            # the generated layouts and the code drawing at every colour its own parser
            # knows and asks for zero differing pixels (docs/theme-editor.md).
            # **Two entries on the knob, two rules, and one paint where possible.**
            #
            # * **live** - `this machine's readings`.  One paint, from the body this call was
            #   handed: fresh on a preview tick, and `self._last` - the last tick's sample -
            #   on an act of the reader's own.  That is the same split the drag cost lives by
            #   (`tests/test_canvas.py` counts a sensor read per mouse-move at zero), and it
            #   is what lets the pane follow the machine at `--preview-fps` without a pointer
            #   event paying for a read.  It is also why the fixture is *not* painted first
            #   here: drawing the same file twice per event cost 19.9 ms a move against
            #   11.6 ms, and nothing in live mode reads the fixture's boxes - `self._ed_notes`
            #   becomes this paint's, because at another body these layouts move their row
            #   boxes, and a box taken from the pinned frame would point a handle at ink that
            #   is not the row it owns.  The frame on screen is the frame the doors answer at.
            # * **held** - `a metrics file`.  Two paints, because two frames are genuinely in
            #   use: the picture comes from the sample read once, so the same file named twice
            #   paints the same pixels, while `_ed_notes` stays the pinned frame's, because in
            #   that mode the geometry doors are shut and every number is written at the frame
            #   every edit is judged at.
            #
            # How many boxes move between the two bodies is counted by
            # `tests/test_peek_readings.py`, which fails if the count comes back empty; the
            # same file counts the paints a repaint asks for, so the difference above is a
            # check and not a story.  No figure for either is kept here.
            live = self._peek is not None and bool(self._peek.get("live"))
            if live:
                if readings:
                    # the sample this frame was painted from, so the note line and the
                    # caption describe the pixels that are up, not the ones before them.
                    # A copy, for the same reason `fixture()` copies: a caller that wrote to
                    # the dict on the note line would be writing to the body the next frame
                    # is painted from.
                    self._peek["metrics"], self._peek["held"] = (dict(m),
                                                                 time.strftime("%H:%M:%S"))
                img, self._ed_notes = self.ed.paint(metrics=m, when=self._peek["when"],
                                                    ink=self._ink())
            else:
                img, self._ed_notes = self.ed.paint(*self.ed.fixture(), ink=self._ink())
                if self._peek is not None:
                    img, _pk_notes = self.ed.paint(metrics=self._peek["metrics"],
                                                   when=self._peek["when"], ink=self._ink())
        else:
            img = render.draw(m, theme, **self._render_kw())
        self._osd = img
        self._seq += 1
        # which body the pixels on the line above came from, and whether it is still
        # current: `LIVE -` for a pane that follows the machine, `PEEK -` for one holding
        # a sample it read once.  Both name the source, because "whose number is that?" is
        # the question a reader asks of a line full of temperatures.
        pane = ("pinned fixture" if self._peek is None
                else f"{'LIVE - ' if self._peek.get('live') else 'PEEK - '}{self._peek['source']}")
        self.metrics.setText(
            (f"pane: {pane}  |  this machine: " if self.ed is not None else "")
            + f"cpu {(m.get('cpu') or {}).get('temperature')}°C  "
            f"load {(m.get('cpu') or {}).get('load')}%  "
            f"gpu {(m.get('gpu') or {}).get('temperature')}°C  "
            f"gpu fan {(m.get('gpu') or {}).get('fan')}%  "
            + "  ".join(f"{f['name']} {f['value']}" for f in m.get("fans") or [])
            + f"   frame #{self._seq} ({render.frame_name()})")
        if self.player is not None:
            # the cheap path: the new layer goes over the frame we already have,
            # without pulling another clip frame for this tick
            self._play_tick(redraw=False)
        else:
            comp = img
            if self.bg_frame is not None and self.canvas.currentIndex() == 0:
                comp = self.bg_frame.resize(img.size, Image.Resampling.LANCZOS).copy()
                comp.alpha_composite(img)
            self._show(comp)
        self._captions()
        # the pane's marks follow the picture: the box of the row being edited, as this
        # paint reported it, or none at all when no layout is open
        self._canvas_marks()

    def _play_tick(self, redraw: bool = True) -> None:
        """One frame of the background, shown.  This is the animation's clock.

        Cheap by measurement, which is the whole reason it can run at the file's
        20-24 fps while the layer under `preview_fps` does not: the decode is 1.06 ms
        (one frame out of `ClipPlayer`), and pasting the cached layer over it -
        copy, `alpha_composite`, `convert`, `tobytes` - is 0.26 ms more, with the
        resize of a 480x480 frame to the panel's own 480x480 a no-op at 0.02 ms.
        What is left is Qt putting the pixels on a label: the pane's `_fit`.

        `redraw=False` is `preview_fps`'s tick arriving with a layer that is newer
        than the frame: show what we have without pulling another clip frame.
        """
        if self.player is not None and redraw:
            self._advance()
        img = self._osd
        if img is None:
            return
        comp = img
        if self.bg_frame is not None and self.canvas.currentIndex() == 0:
            base = (self.bg_frame if self.bg_frame.size == img.size
                    else self.bg_frame.resize(img.size, Image.Resampling.LANCZOS))
            comp = base.copy()
            comp.alpha_composite(img)
        self._played += 1
        self._show(comp)

    def _show(self, comp: Image.Image) -> None:
        """Hand one image to the label.  Nothing about it is expensive enough to
        need its own timer, which is why the split above works."""
        q = QImage(comp.convert("RGB").tobytes("raw", "RGB"), comp.width,
                   comp.height, QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(q)
        self._fit()

    def _captions(self) -> None:
        """The two lines under the picture, and the seam claim they carry.

        Said once per *layer* tick rather than once per shown frame: the text does
        not change 24 times a second, and `setText` on a wrapped QLabel is not free
        either.
        """
        played = self.player is not None
        if self.ed is not None:
            # The pane is showing a file, not this machine: said in the same place the
            # live preview says what it is, because the two pictures look alike and mean
            # different things.  This pane paints with `themes.draw`; the frame loop paints
            # the same file with `themes.paint`; both are one function - `themes._overlay` -
            # and `--check-theme` asks the loop's door for a file, so the pane and the glass
            # can only disagree about the readings, and those are pinned on purpose.
            miss = ", ".join(sorted(set((self._ed_notes or {}).get("missing") or [])))
            # Which body the pixels came from, in one of three sentences: a live pane that
            # follows this machine and takes its marks from the frame it is showing, a held
            # peek that is a look at one sample, and the pinned fixture itself.  The first
            # two differ about what a press means, so they cannot share a sentence.
            if self._peek is None:
                body_line = ("The readings are the editor's pinned fixture, not this "
                             "machine's, so an edit is the only thing that can move a "
                             "pixel here.")
            elif self._peek.get("live"):
                body_line = ("This frame is **live**: its readings are "
                             f"{self._peek['source']}, last read {self._peek['held']}, at "
                             "the pinned instant so the clock rows do not jump between "
                             "ticks.  The box, the handles and the hit test are taken from "
                             "this paint, so the row you point at is the row you move.")
            else:
                body_line = ("This frame is a **peek**: its readings are "
                             f"{self._peek['source']}, held since {self._peek['held']}, "
                             "drawn at the pinned instant so two peeks of one sample agree "
                             "pixel for pixel. The frame your edits move is the pinned one, "
                             "and nothing on this frame can be grabbed until you choose "
                             "`the fixture` under *pane readings*.")
            self.caption.setText(
                f"Layout `{self.ed.name}` ({self.ed.origin}), drawn through "
                "`themes.draw` - the painter the frame loop also uses, through "
                "`themes.paint`, and the one `--check-theme` asks about a layout file. "
                + body_line
                + (f" No reading for: {miss}." if miss else "")
                + (f" {self.ed.ink_note} - a preview of a theme this repo draws from "
                   "code, not a change to the file: Save writes the colours the file "
                   "declares." if self.ed.ink_note else "")
                + ("" if self.ed.theme or self._ink() is None else
                   " This file's colours are its own: the text-colour row is a "
                   "setting of our drawings, not of a vendor's layout.")
                + " This pane sends nothing: the panel is never handed a layout file "
                  "(PROTOCOL.md \u00a711), so what Save changes is what this machine's "
                  "daemon draws next time it names that theme.")
        elif played:
            # the loop's own facts, from the probe the player already did, instead of
            # the still frame's note: the two used to be concatenated without a
            # separator, which printed "...measures those.background Theme_25.mp4 at
            # mid-loop" - and said "mid-loop" about a clip that was not showing one.
            self.caption.setText(
                "Preview: our composite of the background clip playing under the "
                "OSD layer we would send. This panel has no readback, so it is not "
                "a picture of the glass; the loop seam that arrives here is the "
                "file's own, and PROTOCOL.md \u00a79 measures those.  "
                f"{os.path.basename(self.mp4 or '')} is {self.player.seconds:.2f} s "
                f"at {self.player.fps:g} fps, {self.player.wide}x{self.player.tall}.")
        else:
            self.caption.setText(
                "Preview: our composite of one mid-loop frame of the background "
                "under the OSD layer we would send. This panel has no readback, so "
                "it is not a picture of the glass. " + self.bg_note)
        if played:
            rate = min(max(self.player.fps or 24.0, 5.0), 30.0)
            self.anim_note.setText(
                f"background {os.path.basename(self.mp4 or '')} playing at "
                f"{rate:g} fps"
                + ("" if not self.player.fps or abs(self.player.fps - rate) < 0.05
                   else f" (the file says {self.player.fps:g}, shown at {rate:g})")
                + f"; our layer and the readings behind it redrawn at "
                  f"{self.preview_fps:g} fps")
        else:
            self.anim_note.setText(
                f"still frame; the pane is redrawn at {self.preview_fps:g} fps")

    def _fit(self) -> None:
        """Show the preview as large as the pane allows, never larger than 1:1.

        The frame is exactly 480x480 - what the glass is - so scaling *up* would
        show pixels that are not there, and scaling down is the only way the
        pane can be smaller than the panel.  The cap is in here rather than
        left to the layout because `scaled(KeepAspectRatio)` *does* grow a
        pixmap: measured on this box, a 502 px pane drew the 480 px frame at
        502, which is the lie the docstring above this method promised against.
        """
        if not hasattr(self, "_pix"):
            return
        room = self.preview.size()
        side = max(16, min(room.width(), room.height(), render.W))
        pm = self._pix.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)
        self.preview.set_side(pm.width())   # marks line up with what was drawn
        # and the dark card hugs the picture.  An Expanding label in a tall
        # column keeps the slack *inside itself*, so a 1 055 px window drew the
        # 480 px frame with ~130 px of black above and below it, framed by the
        # same border: on a panel that is one exact square, black bands that are
        # not the glass are worse than no decoration, because they read as part
        # of it.  Clamping the label to the pixmap's own height hands that
        # height to the log under it, which can scroll, instead.
        # Clamped from the pane's *width*, never from the pixmap that is on
        # screen: a height taken from the current pixmap feeds back - the card
        # shrinks to a narrow pane, and then its own maximum height keeps it
        # small when the pane widens again, which is how a 1 919 px window came
        # back with a 343 px frame, which `tests/test_window_sizing.py` now holds.
        # Width is set by the splitter, so it is the quantity that is actually
        # free to grow.
        want = min(room.width(), render.W) + FRAME_CHROME
        if self.preview.maximumHeight() != want:
            self.preview.setMaximumHeight(want)

    def eventFilter(self, obj, event) -> bool:         # noqa: N802
        """Refit the preview whenever the pane itself changed shape.

        Three ways that happens - the window resized, the splitter handle
        dragged, the caption or metrics line wrapping to a different number of
        lines - and only the first used to repaint the picture, which is why a
        dragged handle left the frame at the old scale.
        """
        if obj is self.preview and event.type() == QEvent.Type.Resize:
            self._fit()
        elif event.type() == QEvent.Type.FocusIn and id(obj) in self._ed_focus:
            # the note line under the rows speaks for the row the reader is *in*,
            # because eighteen rows each with their own visible sentence is not a
            # form, it is a manual.  The sentence itself is the model's
            # (`edit.field_note`, `themes.XIGMA_KEYS`), written when the rows were
            # bound, and the label carries it as a tooltip for anyone not tabbing.
            self._ed_explain(self._ed_focus[id(obj)])
        return super().eventFilter(obj, event)

    def _load_background(self, path: str) -> None:
        self.mp4 = path
        self.bg_frame = clipdb.frame(path)
        self.bg_note = (f"background {os.path.basename(path)} at mid-loop"
                        if self.bg_frame else f"no frame from {path}")
        self._set_player()
        self._repaint()

    def _set_player(self) -> None:
        """Start, restart or put away the decode stream behind the preview.

        A still frame comes from `clipdb.frame`, which spawns one ffmpeg and seeks
        - the right shape for a thumbnail and a poor one for a loop, measured at
        an order of magnitude per frame more than a single streaming process.  So
        one process stays open while `playing` is on, and nothing is decoded at
        all while it is off, while the window is hidden, or while the picture is a
        `black` canvas (where the background shows nowhere).
        """
        want = (bool(self.anim_toggle.isChecked()) and self.isVisible()
                # a minimised window is still `isVisible()` to Qt, so `hideEvent`
                # never fires for it - and it draws nothing either
                and not self.isMinimized()
                and self.canvas.currentIndex() == 0
                and (self.mp4 or "").lower().endswith(".mp4")
                # a file that gave not one frame: retried once per tick, that is a
                # fresh ffmpeg and a fresh probe twice a second for a picture that
                # will never move, so it is refused here and said out loud below
                and self.mp4 not in self._dead_clips)
        if not want:
            self._close_player()
            # the two lines under the picture say what the pane is doing, so they
            # have to change when this does - not at the next preview tick, which at
            # `preview_fps 1.0` is up to a second of stale text.  The suite's first
            # attempt at asserting them caught that as a race: the caption still read
            # "one mid-loop frame" a moment after the stream had started.
            self._captions()
            return
        if self.player is not None and self.player.path == self.mp4:
            self._captions()
            return
        self._close_player()
        self.player = clipdb.ClipPlayer(self.mp4)
        self._play_t0 = time.monotonic()
        self._play_due = 0.0
        # the file's rate, not the pane's: 41-50 ms, and never faster than 30 fps,
        # because past that the difference is not something an eye separates and the
        # cost is one full composite plus one `_fit` per frame
        rate = min(max(self.player.fps or 24.0, 5.0), 30.0)
        self.bg_timer.setInterval(max(33, int(1000 / rate)))
        self.bg_timer.start()                 # connected once in __init__: a second
        # connect here would run the tick twice per timer fire and play the clip at
        # double speed, which is the kind of bug a rate split invites
        self._captions()

    def _close_player(self) -> None:
        self.bg_timer.stop()
        if self.player is not None:
            self.player.close()
            self.player = None

    def _advance(self) -> None:
        """Pull as many clip frames as real time is worth, and keep the last one.

        The file's own rate is what paces this: the panel plays its stored MP4 at
        that rate, and the preview's redraw rate is ours (2 fps by default), so
        one tick of the preview is worth a dozen decoded frames of a 24 fps clip.
        Reading them is not free but it is small and measured - about 2 ms a frame
        here - and the cap keeps a window that was stopped (hidden, or suspended
        by a desktop) from decoding minutes of catch-up in one click.
        """
        if self.player is None:
            return
        now = time.monotonic()
        gap = min(1.0, now - self._play_t0)      # never more than a second of it
        self._play_t0 = now
        rate = self.player.fps or 24.0
        self._play_due += gap * rate
        want = int(self._play_due)
        self._play_due -= want
        if want < 1:
            return
        frame = None
        for _ in range(min(want, 60)):
            got = self.player.frame()
            if got is None:
                break
            frame = got
        if self.player.dead:
            # The stream died, so the honest thing is to stop claiming it is
            # playing: fall back to the still frame we already have, name the
            # reason in the line under the picture, and remember the file so the
            # next tick does not start another ffmpeg over it.
            self._dead_clips.add(self.player.path)
            self._close_player()
            self.bg_note = (f"no frame could be decoded from "
                            f"{os.path.basename(self.mp4 or '')}: showing the still "
                            f"frame instead (this machine's ffmpeg is what said so)")
            return
        if frame is not None:
            self.bg_frame = frame

    # ---- settings --------------------------------------------------------
    def _theme_chosen(self, *_a) -> None:
        """A theme picked: the pairing gets the first word, the repaint the second."""
        self._apply_pair(self.theme.currentText())
        self._changed()

    def _changed(self, *_a) -> None:
        """Any picker moved: repaint now, write the file once the burst settles."""
        self._repaint()
        self.save_timer.start()

    def _state(self) -> dict:
        return {"device": self.port, "theme": self.theme.currentText(),
                "clock_size": self.clock_size.value(),
                "text_color": self.ink_choice.currentData() or "",
                "canvas": "black" if self.canvas.currentIndex() else "clear",
                "scrim": self.scrim.value(), "fans": self.fanline.isChecked(),
                "preview_fps": self.preview_fps, "clip": self.mp4,
                "keep_my_clip": self.keep_clip,
                "animate": self.anim_toggle.isChecked(),
                "advanced": self.adv_toggle.isChecked(),
                "size": [self.width(), self.height()],
                # the split as it stands, not as it was saved: the splitter's
                # own handle position is the thing the user moved, and the left
                # pane's cap in _build() is what keeps the preview honest
                "split": list(self.split.sizes()) if hasattr(self, "split")
                        else self.cfg["split"]}

    def _save_now(self) -> str | None:
        if not self.autosave:
            # A window that was told to ignore the session file does not write one.  Said
            # once, in the log (where a reader looks) and in the status bar (where a port
            # error will push it out a second later), and never as an error: this is what
            # `--fresh` and every offline check asked for.
            if not self._said_no_save:
                self._said_no_save = True
                self._log(f"this window does not write {settings.path()}: it was started "
                          f"without your session file (`--fresh` is the one that does)")
                self.statusBar().showMessage(
                    f"this window does not write {settings.path()} "
                    "(started without your session file)", 5000)
            return None
        where = settings.save(self._state())
        if where:
            self.statusBar().showMessage(f"settings saved to {where}", 2500)
        else:
            self._log(f"could not write {settings.path()}: the window will "
                      f"start at its defaults next time")
        return where

    # ---- clips -----------------------------------------------------------
    def _row(self, c: clipdb.Clip) -> str:
        """One picker row. The loop length appears once it has been probed."""
        return (f"{c.name}   {c.size}   "
                f"{f'{c.px[0]}x{c.px[1]}' if c.px[0] else 'size ?'}   "
                f"{f'{c.seconds:.1f} s' if c.seconds else 'loop  ?'}   {c.origin}")

    def _populate_clips(self) -> None:
        """List every distinct clip, then fill thumbnails in the background.

        Thumbnails cost an ffmpeg seek each, so the rows go up at once with what a
        `stat` gives and the pictures and loop lengths arrive a row per timer tick.

        One row per *distinct file*, not one per path: `clipdb.list_clips()` walks
        the roots and collapses copies by length and content (see its docstring).
        Measured where the roots are only this repository: **46 mp4 files, 40 distinct
        contents** (whole-file sha256). On this bench, where the Windows partition is
        mounted and the .deb is installed, the same rule walks **204 mp4
        files across the roots, 40 distinct contents, 121 copies not listed** - 26
        of them the Windows app's own upload history, which re-adds a library clip
        under a millisecond timestamp name (`1757491589240.mp4` is `Theme_25.mp4`,
        and all 26 are like that), and 3 of them the vendor library repeating
        itself inside its own tree.  The window says the numbers out loud, because
        a list that quietly gets shorter looks like a bug.
        """
        self.clips.clear()
        self.all_clips = clipdb.list_clips()
        scan = clipdb.LAST_SCAN
        if scan.get("copies"):
            where = ", ".join(f"{n} {k}" for k, n in
                              sorted(scan["roots"].items(), key=lambda kv: -kv[1]))
            self._log(f"clip library: {scan['files']} mp4 files found, "
                      f"{len(self.all_clips)} distinct clips listed, "
                      f"{scan['copies']} copies left out ({where}); same bytes so "
                      f"one row each, and {scan['renamed']} of them were repeats "
                      f"under a different name - the file listed is the one this "
                      f"program would pick")
        if not self.all_clips:
            self.clips.addItem("(no MP4 found: media/ is empty and the Windows "
                               "partition is not mounted)")
            return
        side = self.clips.iconSize().height()
        for c in self.all_clips:
            item = QListWidgetItem(self._row(c))
            # The row is told its height, not asked to guess it. With
            # `uniformItemSizes` the first item's sizeHint sets the height for all
            # of them, and that hint is taken before any thumbnail exists - which
            # latched every row to 17 px of text and clipped the icons that arrived
            # a tick later. Measured: 17 px at first paint, 66 px only after the
            # lazy pass had run and something else re-hinted the view.
            item.setSizeHint(QSize(0, side + 2))
            item.setData(Qt.ItemDataRole.UserRole, c.path)
            # the daemon's own gate, run here: a row that would come back
            # "the display refused upload: …" is marked before it is ever
            # clicked, with the daemon's words as the reason.  Not a second rule
            # - one call into xigmalcd.control.check_media_file, so the window
            # can never disagree with what the socket will actually accept.
            ok, why = wire.check_media_file(c.path)
            if not ok:
                item.setForeground(QBrush(QColor("#7d7d7d")))
            item.setToolTip(c.path + (f"\n{c.note}" if c.note else "")
                            + ("" if ok else f"\nthe display would refuse "
                                             f"this: {why}"))
            self.clips.addItem(item)
        first = next((i for i, c in enumerate(self.all_clips)
                      if c.path == self.mp4), 0)
        self._programmatic = True
        try:
            self.clips.setCurrentRow(first)
        finally:
            self._programmatic = False
        self._pending = list(range(len(self.all_clips)))
        # the row you selected first, then whatever is on screen, then the rest
        self._pending.remove(first)
        self._pending.insert(0, first)
        if not hasattr(self, "thumb_timer"):
            # **Once, for the life of the window**, and connected once.  A second `QTimer`
            # made here would orphan the first: `closeEvent` and
            # `tests/fixtures.py:close_window` stop the one the window *names*, so an
            # orphan keeps firing `_thumb_batch` - two subprocesses a tick - at whoever
            # runs next, which is how one file's check starved another's deadline.  Nothing
            # calls this twice today; the trap is that it reads as if it may.
            self.thumb_timer = QTimer(self)
            self.thumb_timer.setObjectName("thumb")
            self.thumb_timer.timeout.connect(self._thumb_batch)
        self.thumb_timer.start(0)

    def _filter_clips(self, text: str = "") -> None:
        """Hide the rows this text does not appear in.

        Matching the row's own words, not a separate index: a row already says
        the name, the size, the measured loop length and where the file came
        from (`vendored`, `vendor library`, `app upload`), so `2 MiB`, `theme_47`
        and `vendored` each find what they should.  The row that is currently
        selected stays visible either way - a hidden selection is a selection
        the buttons still act on, and that is a worse surprise than a stray row.
        """
        want = " ".join(str(text).split()).lower()
        for i, c in enumerate(self.all_clips):
            row = self.clips.item(i)
            if row is None:
                continue
            hide = bool(want) and want not in row.text().lower()
            row.setHidden(hide and i != self.clips.currentRow())

    def _thumb_batch(self) -> None:
        """One clip per tick: probe its loop, draw its thumbnail, move on.

        Visible rows go first. 115 clips is 115 ffmpeg seeks: 12.7 s of them
        measured on this box (15.7 s when something else is busy), and the ones
        below the fold are not the ones you are looking at.

        **It stands down while the reader is holding a row.**  A tick is two
        subprocesses - `ffprobe` for the loop length and `ffmpeg` to seek a frame -
        and this timer runs at interval 0, so the library's first pass takes the
        event loop for as long as it has rows left to do.  Measured on this bench
        while writing the sentence: opening the window and dragging at once costs
        **108 ms per mouse-move event** for the first 25 moves (24 `ffprobe`/`ffmpeg`
        spawns across 8 of them), against **11.7 ms** for every drag after the pass
        is done.  That is the shape of "dragging is laggy" when nothing is playing:
        the pane is not the slow part, the queue beside it is.  Nothing is lost by
        waiting - `_pending` keeps the row, the pass resumes on the next tick, and an
        icon arriving 200 ms late is not a fact about the file.
        `tests/test_canvas.py` counts the probes one tick makes with a drag in flight
        and without one: zero and one, never a silent never-finishing pass.
        """
        if self._drag or self._resize:
            return
        if not self._pending:
            self.thumb_timer.stop()
            return
        top = self.clips.indexAt(self.clips.viewport().rect().topLeft())
        bottom = self.clips.indexAt(self.clips.viewport().rect().bottomLeft())
        seen = {r.row() for r in (top, bottom) if r.isValid()}
        i = next((n for n in self._pending if n in seen), self._pending[0])
        self._pending.remove(i)
        item, clip = self.clips.item(i), self.all_clips[i]
        clipdb.probe(clip)
        item.setText(self._row(clip))
        img = clipdb.frame(clip.path)
        if img is None:
            return
        # never drift from the widget's icon size.  And the fit keeps the file's
        # proportions: three of the library's clips are 320x240, and stretching a
        # 4:3 frame into a 64 px square would show a picture that is not in the
        # file.  Letterbox instead, transparently, so the list's own background
        # shows through the bars - and the row's measured `320x240` is the number
        # a reader should trust about the file.
        side = self.clips.iconSize().width()
        box = clipdb.letterbox(img, side)
        q = QImage(box.tobytes("raw", "RGBA"), side, side, side * 4,
                   QImage.Format.Format_RGBA8888).copy()
        item.setIcon(QIcon(QPixmap.fromImage(q)))

    def _apply_pair(self, name: str) -> None:
        """Follow the background a layout names, unless the "keep my background" box is on.

        One rule, said out loud in every branch, because the interesting part is the case
        where it does nothing: the five themes drawn from `render.py` declare no clip at
        all, and a clip the box does not have is a fact the reader needs, not a silence.
        """
        clip, why = themes.pair(name)
        self._pair_target = clip
        if not clip:
            self.pair_note = why if not self.keep_clip else (
                f"background is yours: {os.path.basename(self.mp4)}. "
                f"{why[0].upper() + why[1:]}")
            self._refresh_pair()
            return
        if self.keep_clip:
            self.pair_note = (f"background is yours: {os.path.basename(self.mp4)}. This "
                              f"layout names {clip} - untick \"keep my background\", or "
                              f"press the button below, to take it back.")
            # The reader needs more than a changed line of small print here.  This is the
            # case where a layout declares a clip, the preview does not move, and nothing
            # else about the window looks different - so say it in the log too, in the same
            # words the note uses, and say how to undo it.  Only when the two clips
            # actually differ: opening the layout whose clip is already under the layer is
            # not a refusal, and logging it would be noise.
            if clip != os.path.basename(self.mp4):
                self._log(f"{name} names {clip}; \"keep my background\" is ticked, so "
                          f"the window kept {os.path.basename(self.mp4)}. Untick it, or "
                          f"\"Use this layout's own clip\" takes it back now.")
            self._refresh_pair()
            return
        path, how = clipdb.find(clip, self.all_clips)
        if not path:
            self.pair_note = (f"{name} names {clip}, which this box does not have; "
                              f"keeping {os.path.basename(self.mp4)}.")
            self._refresh_pair()
            return
        self.pair_note = (
            f"{name} pairs with {clip} ({how}); it is under the layer now."
            + ("" if how == "row" else " No row of the library holds these bytes, so "
                                       "nothing is marked in the list."))
        if path != self.mp4:
            was = os.path.basename(self.mp4)
            self._load_background(path)      # repaints, and the note is written after
            self._pair_row(path)
            # The movement is the whole point of the feature, and it replaced a picture -
            # so the log says which one, and what asked for it.
            self._log(f"background: {clip}, {name}'s own clip ({how}), replacing {was}")
        else:
            self._pair_row(path)
        self._refresh_pair()

    def _pair_row(self, path: str) -> None:
        """Mark the list's row for a clip the pairing chose.  Guarded, not silent: the row
        is selected so the reader can see which of the 40 it is, and `_clip_chosen` runs as
        it always does, but the one thing it must not do is record a choice nobody made."""
        for i, clip in enumerate(getattr(self, "all_clips", [])):
            if clip.path == path:
                self._programmatic = True
                try:
                    self.clips.setCurrentRow(i)
                finally:
                    self._programmatic = False
                return

    def _use_pair(self) -> None:
        """The way back: the layout's own clip, and the box unticked so it follows again."""
        self.keep_clip = False
        self.chk_keep.blockSignals(True)     # a button doing it must not log as a tick
        self.chk_keep.setChecked(False)
        self.chk_keep.blockSignals(False)
        self._apply_pair(self.ed.name if self.ed is not None
                         else self.theme.currentText())
        self.save_timer.start()
        self._log(f"background: the layout's own clip ({self.pair_note})")

    def _keep_toggled(self, on: bool) -> None:
        """The one place `keep_my_clip` changes, and a hand did it.

        Unticking takes the open layout's clip back at once rather than waiting for the
        next layout change: a box and a picture that disagree about what is on screen are
        worse than either alone.
        """
        self.keep_clip = on
        name = self.ed.name if self.ed is not None else self.theme.currentText()
        if on:
            self._log('keeping your background: no layout will move it until you untick '
                      '"keep my background"')
        else:
            self._log(f"layouts choose their own background again ({name})")
        self._apply_pair(name)
        self.save_timer.start()

    def _refresh_pair(self) -> None:
        self.pair_state.setText(self.pair_note)
        # the button is the way back from the box, so it only means something while the
        # box is on; with it off the pairing is already doing the button's work
        self.btn_pair.setEnabled(bool(self._pair_target) and self.keep_clip)

    def _clip_chosen(self, item: QListWidgetItem | None, *_a) -> None:
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        i = self.clips.row(item)
        if 0 <= i < len(self.all_clips) and not self.all_clips[i].seconds:
            clipdb.probe(self.all_clips[i])       # picked before its tick came round
            item.setText(self._row(self.all_clips[i]))
        self._load_background(path)
        self._queued_bg = ""          # a new pick has not been asked for yet
        # Picking a row puts that clip under the preview, and nothing else.  Whether a later
        # layout change walks over it belongs to the "keep my background" box, which only a
        # hand moves: until 0.4 a row click set the flag itself, which is how a window ended
        # up refusing to follow any layout's pairing - for reasons the reader could not see
        # (docs/gui.md).  So the cost of the pick is said out loud instead of recorded in
        # silence: the layout open right now names another clip, and will put it back.
        if (not self._programmatic and self._pair_target
                and self._pair_target != os.path.basename(path)):
            _open = (self.ed.name if self.ed is not None else self.theme.currentText())
            self._log(f"background: {os.path.basename(path)}, yours to preview and to "
                      f"send. {_open} names {self._pair_target}, and the next layout "
                      f"change puts it back unless you tick \"keep my background\"")
        self._refresh_clip_state()
        self.save_timer.start()          # next start opens on the clip you chose
        # the detail only: the row itself is the line directly above this label,
        # and repeating it cost two wrapped lines of a short column
        self.clip_info.setText(self._clip_detail(path))

    def _clip_detail(self, path: str) -> str:
        for c in self.all_clips:
            if c.path == path:
                lum = clipdb.measure(c)
                how = ("mean luma, measured by the daemon" if c.name in CLIP_LUMA
                       else "mean luma, measured just now from a decoded frame")
                need = ("needs a scrim plate for white glyphs" if lum > BRIGHT_LUMA
                        else "white glyphs stay readable over it")
                size_note = ""
                if c.px[0] and c.px != (render.W, render.H):
                    # measured here with ffprobe, and the honest half of it stays
                    # unmeasured: 40 of the 43 clips the themes package installs are
                    # 480x480 and 3 are 320x240, and what the panel does with a file
                    # that is not its own size is something no log can show, because
                    # there is no readback (§11).  So the number is shown and the
                    # inference is left to the reader, with the preview labelled a guess
                    size_note = (f"\nthis file is {c.px[0]}x{c.px[1]}, not the "
                                 f"panel's {render.W}x{render.H}: what it does with "
                                 f"that is not measured, so the preview above is a "
                                 f"guess")
                return (f"{how}: {lum:.1f}/255 - {need}"
                        f"{size_note}"
                        f"\nsending it replaces what the panel stores; only the "
                        f"factory reset clears it again")
        return ""

    # ---- the preview's own motion ---------------------------------------
    def _set_animate(self, on: bool) -> None:
        """Play the background, or go back to the one still frame.

        The still stays as the fallback for everything that cannot stream: no
        ffmpeg on the box, an unreadable file, a `black` canvas where no
        background is visible anyway, and a hidden window.
        """
        self._set_player()
        self._repaint()
        self.save_timer.start()

    # ---- the advanced switch --------------------------------------------
    def _set_advanced(self, on: bool) -> None:
        """Show or hide the knobs a first-run reader does not need.

        Hiding is only ever about screen area: every control keeps its value and
        `Apply` sends it, so a compact window is not a window running on defaults
        - the note beside the switch says what is folded away.  The factory-reset
        box folds with the rest: what stands between a stray click and a recovery
        is the typed word and a disabled button, not the box sitting in view.  The
        note beside the switch names every control that folds, and the switch's own
        tooltip says what hiding does and does not do to them.
        """
        for w in self._adv_hide:
            w.setVisible(bool(on))
        self.adv_note.setText(
            self._adv_folded_note if not on
            else "shown, and they keep their values either way")
        self.save_timer.start()

    # ---- the layout editor --------------------------------------------------
    # Every claim in this group belongs to `xigmaui/edit.py`, which holds no Qt and is
    # gated without a display in `tests/test_editor.py`: what an edit moves, what undo owes
    # back, when a file is written.  The window's job is narrow - offer the fields the
    # painter reads, show the picture that comes out of them, and never write a file
    # nobody asked for.
    # ------------------------------------------------------ naming a layout --
    # Renaming a copy and saving one under a second name are the two acts in this pane that
    # invent a name rather than edit a layout.  Both go through `themes.new_name` - one rule
    # for what a name may be, shared with the writer - and `edit.Editor.rename` /
    # `save_as` - one place that says what the act did to the file, the id, and the loop.
    # Nothing here decides anything about a name on its own: the refusals printed under the
    # rows are the model's sentences, and the counts in these tooltips are counted from the
    # library on the way past, the same discipline as the combo's own tooltip.
    def _ed_combo_tip(self) -> str:
        """The layout menu's tooltip, recounted from the library each time it is set."""
        pick, reject = themes.scan()
        return (
            f"the {len(themes.EXPORTS)} generated layouts "
            f"({', '.join(sorted(themes.EXPORTS))}: JSON written out of `render.py` on "
            "demand, also printed by "
            f"`--export-theme NAME`) and every layout file this canvas can select - "
            f"{len(pick)} of the {len(pick) + len(reject)} today, the other {len(reject)} "
            "are 4:3 and refused on a 480x480 panel (docs/themes.md). A name you have "
            "already edited opens your copy.  That is the whole list this menu can hold: it "
            "is built from the roots this program reads, so `reload the list` re-reads them "
            "when a copy appeared by some other door - the CLI, another window, a file you "
            "dropped in yourself - and `open a file…` reaches a layout file no root holds at "
            "all, which is not something a display can be told to draw until you save it as "
            "your copy.  No layout file is ever sent to the panel and nothing is read back "
            "from it (PROTOCOL.md \u00a711): what a save changes is what *this machine's* "
            "daemon draws next time it names that theme")

    def _ed_name_tip(self) -> str:
        """What the name box will accept, said by the doors that enforce each rule."""
        pick, reject = themes.scan()
        names = {r["name"] for r in list(pick) + list(reject)}
        ids = {str(r["id"]) for r in list(pick) + list(reject)}
        return (
            f"the name to give this copy. Up to {themes.NAME_LIMIT} characters, one path "
            "element with no separators and no leading dot; never one of the "
            f"{len(themes.EXPORTS)} names drawn from `render.py`; and never ending in "
            f"{', '.join(themes.WRITER_SUFFIXES)} - this program writes those beside a "
            f"layout, so a layout called `x.json` would live at `x.json.json` while the "
            f"`x.json` next to it is the layout named `x`.  A new name also has to be clear "
            f"of the {len(names)} names and {len(ids)} ids the library answers today, "
            "counted ignoring case: `--theme` matches a name, its case-fold, and an id, so "
            "taking any of them does not add a layout next to that one, it takes that one "
            "out of reach.  None of this reaches the panel: a layout file is never sent "
            "there (PROTOCOL.md \u00a711)")

    def _ed_rename_tip(self) -> str:
        """What renaming a copy does, in the order the act happens in."""
        return ("move your copy to the name in the box.  Two things follow, and both are "
                "said afterwards: the file `--theme <new name>` finds is yours, and its "
                "`id` becomes a fresh one in the shape the vendor's files use, because "
                "`--theme <id>` answers a layout by its id too and two files sharing one "
                "id is a name space with a hole in it.  The rows, the picture and anything "
                "you have typed stay exactly as they are - this is a file act, not an edit, "
                "so it takes no undo step.  Only a copy of yours can be renamed: the "
                "vendor's two trees are never written, and the library's own file under a "
                "name you have never saved is not yours to move.")

    def _ed_copy_tip(self) -> str:
        """What `save as` does, and how it differs from the save button above it."""
        return ("write what is on screen to the name in the box as a second copy, and keep "
                "the file where it is with every byte it has.  The copy in front of you "
                "then takes a fresh id, so the two layouts never answer the same "
                "`--theme <id>`, and this window goes on editing the new one.  That is not "
                "what `save as your copy` refuses: that refusal is about a `gauge.json` "
                "that would be a second `theme_gauge` to disagree with `render.py`.  A "
                "layout drawn from code gets its first file this way, and `--theme gauge` "
                "still draws the code's picture.")

    def _ed_refresh_layouts(self) -> None:
        """Re-list the layout menu from the library, keeping the layout that is open.

        A rename retires one name and creates another, and a save-as creates a name with no
        name retired - so the menu is rebuilt from `themes.EXPORTS` and `themes.scan()`
        rather than patched in place.  Its signals stay blocked across the rebuild:
        selecting the entry for the layout this editor is holding would re-read the file and
        throw away whatever the reader has typed since the last save, which is the one thing
        this act must not do.
        """
        want = self.ed.name if self.ed is not None else NO_EDITOR
        self.ed_name.blockSignals(True)
        self.ed_name.clear()
        self.ed_name.addItem(NO_EDITOR)
        self.ed_name.addItems(sorted(themes.EXPORTS))
        self.ed_name.addItems([r["name"] for r in themes.scan()[0]])
        # a layout opened **by path** this session is not in any root, so the rebuild would
        # drop the entry the reader can see on screen - and with it the only way back to that
        # file.  It is put back after the roots, and its tooltip keeps saying where it came
        # from, because a menu entry that lies about which file it opens is worse than no entry
        for name in sorted(self._ed_paths):
            if self.ed_name.findText(name) < 0:
                at = self.ed_name.count()
                self.ed_name.addItem(name)
                self.ed_name.setItemData(at, f"opened from {self._ed_paths[name]}",
                                         Qt.ItemDataRole.ToolTipRole)
        at = self.ed_name.findText(want)
        if at >= 0:
            self.ed_name.setCurrentIndex(at)
        self.ed_name.blockSignals(False)
        self.ed_name.setToolTip(self._ed_combo_tip())
        self._ed_box_readable(self.ed_name)
        self._pane_floors()

    def _editor_rename(self) -> None:
        """Move this copy to the name in the box.  One file act, no undo step, no re-read."""
        if self.ed is None:
            return
        want = self.ed_newname.text()
        path, notes = self.ed.rename(want)
        if path is None:
            self.ed_note.setText(" / ".join(notes))
            self._log(f"layout not renamed: {notes[0]}")
            self._editor_state()
            return
        self._log("layout renamed: " + "; ".join(notes))
        self.ed_note.setText("  ".join(notes))
        self._ed_refresh_layouts()
        self._apply_pair(self.ed.name)     # the pairing follows the file, and it moved
        self._editor_state()

    def _editor_copy(self) -> None:
        """Write a second copy under the name in the box, and start editing that one."""
        if self.ed is None:
            return
        want = self.ed_newname.text()
        path, notes = self.ed.save_as(want)
        if path is None:
            self.ed_note.setText(" / ".join(notes))
            self._log(f"layout not copied: {notes[0]}")
            self._editor_state()
            return
        self._log("layout copied: " + "; ".join(notes))
        self.ed_note.setText("  ".join(notes))
        self._ed_refresh_layouts()
        self._apply_pair(self.ed.name)
        self._editor_state()

    def _ed_peek_tip(self) -> str:
        """What the pane-readings drop-down offers, in the words the refusal also uses."""
        return ("what body the picture in the pane is painted from, while you edit.  "
                "`the fixture` is the pinned pair every edit is judged at, and the only "
                "frame this program's own numbers - `--metrics-file`'s fixture - decide.  "
                "`this machine's readings` is **live**: the pane re-reads this box on each "
                "preview tick (never on a pointer event, which is what keeps a drag cheap), "
                "and the box, the eight squares and the hit test are taken from that paint, "
                "so the row you point at is the row whose ink you pointed at - at another "
                "body these layouts move their row boxes, and marks from the pinned frame "
                "would sit over different ink.  `a metrics file` is **held**: a JSON "
                "`STATE all 1` body you name, the same file shape `--metrics-file` takes, "
                "read once so the same file gives the same picture twice; on that frame "
                "press, drag, arrow keys and handles are refused, because a number written "
                "from a sample that is already stale belongs to a reading that is gone. "
                "Nothing here is remembered: a fresh window opens at the fixture.  And a "
                "peek is a look at numbers, not a delivery of them: like `--metrics-file`, "
                "it never hands the panel a reading this machine did not measure.")

    def _peek_body(self, mode: str) -> tuple:
        """`(sections, source, reason)`: the body a peek would paint with.

        For `sensors` this is the sample taken **at the press of the knob**, so the pane
        changes under the reader's hand; from that moment the preview tick takes over and
        reads again at `--preview-fps`, which is what *live* means and why the source says
        so.  For `file` this is the only read that ever happens, which is what *held* means:
        the same file named twice gives the same picture, pixel for pixel, and that is the
        whole use of looking at a saved sample.  Either way the cost belongs to the machine
        and the moment, so no figure for it belongs in a source file: docs/limits.md names
        the command that prints one.  A named file goes through `main.read_metrics_file` -
        the door `--metrics-file` uses - and its sections replace this machine's whole
        sections, exactly as `main.sample` does for the loop, because one file shape has to
        mean one thing in one program.
        """
        m = sensors.collect()
        if mode == "sensors":
            return m, "this machine's own sensors, live at each preview tick", ""
        path = self.ed_peek_file.text().strip()
        if not path:
            return {}, "", ("a metrics file has to be named: the same `STATE all 1` body "
                            "`--metrics-file` takes")
        data, why = read_metrics_file(path)
        if why:
            return {}, "", why
        m.update(data)
        return (m, f"{path} ({', '.join(sorted(data)) or 'no sections'}) over this "
                   f"machine's reading", "")

    def _editor_peek(self, *_args) -> None:
        """Choose what body the pane paints while a layout is open (feature G)."""
        if self.ed is None:
            # Nothing to peek at: without an open layout the pane is already showing this
            # machine's readings, through the loop's own door rather than this one.
            self.ed_peek.setCurrentIndex(0)
            self.ed_note.setText("there is no layout open to peek at: the pane already "
                                 "shows the theme above, drawn from this machine's "
                                 "readings")
            return
        mode = self.ed_peek.currentData()
        if mode == "fixture":
            was, self._peek = self._peek, None
            self.ed_peek_file.setEnabled(False)
            if was is not None:
                self.ed_note.setText("the pane is back at the pinned fixture: the "
                                     "readings behind it are the ones every edit is "
                                     "judged at, and the marks are the rows' again")
                self._repaint()
                self._canvas_marks()
            return
        body, source, why = self._peek_body(mode)
        if why:
            # A half-read body is not a picture, so the pinned frame stays up. The chosen
            # mode stays on the combo: a reader who picked `a metrics file` and has not
            # typed the path yet is mid-action, and snapping the control back under their
            # fingers would lose what they were about to name. The note says what is
            # missing, and the frame says where it stands.
            self._peek = None
            self.ed_peek_file.setEnabled(True)
            self.ed_note.setText(f"no peek: {why}")
            self._repaint()
            self._canvas_marks()
            return
        self._peek = {"mode": mode, "metrics": body, "source": source,
                      "when": edit.FIXTURE_WHEN, "held": time.strftime("%H:%M:%S"),
                      "live": mode == "sensors"}
        self.ed_peek_file.setEnabled(mode == "file")
        # painted first, then described: a live pane has just taken a newer sample than the
        # one the knob pressed for, and the sentence a reader reads has to be about the
        # pixels that are up.  `held` for a file body is the same object either way.
        self._repaint()
        self.ed_note.setText(self.ed.peek_sentence(source, self._peek["metrics"],
                                                   self._peek["when"], self._peek["held"],
                                                   live=self._peek["live"]))
        self._canvas_marks()

    def _note_pair(self) -> tuple:
        """The readings the note lines describe: the peek's, while peeking.

        Measured before choosing it, and re-measured by `tests/test_peek_readings.py`
        wherever it runs: some of the rows' sentences change between the fixture and
        this machine's readings, and every change that file has found was a *value*
        (`57°C` to `65°C`) with the reason strings left alone - so recomputing them
        makes the lines say what the frame on
        screen shows, which is the whole rule of the note line. The pinned sentences are
        still one press away, and the geometry doors keep answering from the fixture
        whatever these lines say: the note describes the picture, the doors write the file.
        """
        return ((self._peek["metrics"], self._peek["when"]) if self._peek
                else self.ed.fixture())

    def _editor_open(self, name: str) -> None:
        """Open one layout in the editor.  Reads a file; writes nothing.

        The combo's first entry closes the editor and gives the pane back to the live
        theme preview, which is the difference a reader needs to see: an open layout is
        a picture of *the file*, drawn from a pinned fixture, not of what this machine's
        sensors are putting on the glass right now.

        This re-reads the file, so it is only ever reached for a *different* name:
        `currentTextChanged` cannot fire with the text the menu already holds, which is
        what keeps unsaved changes safe when a reader clicks the entry for the layout that
        is already open.  `_ed_refresh_layouts` blocks the same signal while it rebuilds the
        list for the same reason - after a rename or a save-as, the layout in memory is the
        one the menu should be showing, and re-opening it here would read the moved file
        back and drop whatever was typed since the last save.
        """
        if not name or name == NO_EDITOR:
            self.ed = None
            self._peek = None             # the pane is showing this machine already
            self.ed_peek.setCurrentIndex(0)
            self._ed_set_enabled(False)
            self.ed_state.setText("not editing: the pane below shows the theme above, "
                                  "drawn from this machine's readings")
            self.ed_note.setText("")
            self._apply_pair(self.theme.currentText())
            self._repaint()
            return
        if name in self._ed_paths:
            # a layout this window opened **by path** earlier in the session: picking its
            # entry re-reads that file, which is the whole point of the door - an external
            # edit of the file becomes visible without restarting the window.  Refused in
            # the model's words if the file has since moved or gone.
            self._editor_open_path(self._ed_paths[name])
            return
        try:
            self._editor_take(edit.Editor.open_theme(name))
        except (KeyError, ValueError) as exc:
            # `themes.why_not`'s own sentence: a name that is not a layout, or a file
            # that will not parse.  Nothing here guesses at a repair.
            self.ed = None
            self.ed_state.setText("not editing")
            self.ed_note.setText(str(exc))
            self._repaint()
            return

    def _ed_open_file(self) -> None:
        """The `open a file…` button: ask for a path, then hand it to the door below.

        The asking is one small method of its own (`_ed_ask_path`) rather than a call inline
        here, for the reason every other un-clickable control in this suite has: a native file
        dialog cannot be driven headless, and a door whose prompt cannot be replaced is a door
        no check can reach.  An empty answer - cancel, or an empty line - changes nothing at
        all: the layout that was open stays open, with its unsaved edits, and no note is
        written, because cancelling is not an error.
        """
        path = self._ed_ask_path()
        if not path:
            return
        self._editor_open_path(path)

    def _ed_start_dir(self) -> str:
        """Where the open dialog begins: the one directory this program's copies live in.

        A separate method rather than an argument, because a native dialog cannot be driven
        headless and this is the part of the step a check can still ask about.  It falls back to
        the home directory only when the user root has never been created - a dialog pointing at
        a directory that does not exist opens wherever Qt feels like, which is how a reader ends
        up hunting through `/` for a file two doors would have listed for them.
        """
        root = themes.user_root()
        return root if os.path.isdir(root) else os.path.expanduser("~")

    def _ed_ask_path(self) -> str:
        """The dialog itself, opening where layouts actually live."""
        path, _chosen = QFileDialog.getOpenFileName(
            self, "open a layout file", self._ed_start_dir(),
            "layout files (*.json);;any file (*)")
        return str(path or "")

    def _editor_open_path(self, path: str) -> None:
        """Open one layout file **by path**, at the model's door.  Writes nothing.

        The path is remembered against the name the file's stem gives, so the menu can hold
        the entry and re-picking it re-reads the file.  A refusal leaves every other part of
        the window exactly as it was: the layout that was open stays open, because a door
        that failed on a typo should not also be the act that loses somebody's unsaved edit.
        """
        try:
            ed = edit.Editor.open_path(path)
        except ValueError as exc:
            self.ed_note.setText(str(exc))
            return
        if ed.origin != edit.PATH_ORIGIN:
            # the path was one of the library's own files, so the name door's words - "your
            # copy", "the vendor's file in this checkout" - are the true ones, and no
            # by-path entry is needed for it
            self._ed_paths.pop(ed.name, None)
        else:
            self._ed_paths[ed.name] = os.path.abspath(path)
            if self.ed_name.findText(ed.name) < 0:
                at = self.ed_name.count()
                self.ed_name.addItem(ed.name)
                self.ed_name.setItemData(at, f"opened from {os.path.abspath(path)}",
                                         Qt.ItemDataRole.ToolTipRole)
                self._ed_box_readable(self.ed_name)
                self._pane_floors()
            self.ed_name.blockSignals(True)
            self.ed_name.setCurrentText(ed.name)      # the signal would re-open, i.e. discard
            self.ed_name.blockSignals(False)
        self._editor_take(ed)

    def _ed_reload_layouts(self) -> None:
        """Re-read the roots and rebuild the menu, keeping what is open.

        The counts come out of the doors the menu is built from, in the same breath as the
        rebuild, because a sentence about how many layouts there are has to be re-measured to
        be true - this window used to carry one written by hand, and it went stale the day two
        more exports landed (docs/theme-editor.md).  It says what the roots hold *now*, which
        is the fact a reader pressed the button to find out.
        """
        before = self.ed_name.count()
        self._ed_refresh_layouts()
        now = self.ed_name.count()
        copies = themes.user_copies()
        self.ed_note.setText(
            f"the menu was re-read: {now - 1} layouts in it now "
            f"({before - 1} before), of which {len(copies)} "
            f"{'is' if len(copies) == 1 else 'are'} your copy under {themes.user_root()}"
            + (f": {', '.join(copies)}" if copies else "")
            + (f", plus {len(self._ed_paths)} opened from a path this session"
               if self._ed_paths else "")
            + ". Nothing was written, and what is open was not re-read.")

    def _editor_take(self, ed: "edit.Editor") -> None:
        """Put a freshly-read editor into the window: the rows, the pairing, the pane."""
        self.ed = ed
        # A vendor layout carries its own background; follow it while the background has
        # not been chosen by hand.  This is the only place the pairing is *driven*: the
        # theme combo above lists the five drawn themes, which declare none.
        self._apply_pair(ed.name)
        self._ed_set_enabled(True)
        self.ed_undo.setEnabled(False)
        self.ed_undo.setText("undo")
        self.ed_widget.blockSignals(True)
        self.ed_widget.clear()
        # The short line on the row; the `id` goes in the combo's own tooltip, updated
        # with the selection, because a vendor id is a uuid4 and this column is one box
        # wide.  It is the string a reader greps the file for.
        for i in range(len(self.ed.widgets())):
            self.ed_widget.addItem(self.ed.label(i))
        self.ed_widget.blockSignals(False)
        _readable(self.ed_widget)
        self._ed_box_readable(self.ed_widget)
        self._pane_floors()
        self.ed_widget.setCurrentIndex(0)
        self._editor_pick_widget(0)
        self._repaint()

    def _editor_state(self) -> None:
        """One line: which file answers this name today, and whether a file holds it now.

        The first half comes from `edit.Editor.where`, which asks `themes.resolve()` on the
        current name - the same lookup `--list-themes`, the loop's own log line and the
        socket's `theme` command go through.  It used to be a word remembered from the moment
        the layout was opened, and that word went stale at exactly the three moments that
        matter: a save, a revert, a rename.
        """
        if self.ed is None:
            return
        where = {"generated from render.py":
                 "generated from `render.py`: there is no file, and saving one is "
                 "refused, because a `gauge.json` would be a second `theme_gauge`",
                 "checkout": "the vendor's file in this checkout",
                 "package": "the installed themes package",
                 "your copy": "your copy under ~/.config/xigmalcd/themes",
                 "no file at all": "no file answers this name - it is yours alone, and "
                                   "your copy of it is gone"}.get(
                     self.ed.where, self.ed.where)
        if self.ed.origin == edit.PATH_ORIGIN:
            # The other half of the sentence `where` gives everybody else.  A layout that
            # arrived as a path is not, yet, a thing any display can be told to draw, and
            # there are three cases here that read differently - so what the name resolves to
            # is asked of the resolver rather than assumed: nothing answers it (this window's
            # alone), this window's own copy answers it (saved since, so a loop can draw it),
            # or somebody else's file answers the same name (and that is the file the panel
            # would draw, not the one on screen).
            answered = themes.resolve(self.ed.name)
            if answered is None:
                where = (f"opened from the file you named, {self.ed.opened}; no root this "
                         f"program reads answers `{self.ed.name}`, so this layout is this "
                         "window's alone until you save it as your copy")
            elif os.path.abspath(answered["path"]) == os.path.abspath(self.ed.path or ""):
                where = (f"opened from {self.ed.opened}, saved as your copy at "
                         f"{answered['path']}"
                         + (": that file is what a loop draws" if not self.ed.dirty
                            else " - but the pane holds edits that file does not: save again"))
            else:
                where = (f"opened from {self.ed.opened}; the name `{self.ed.name}` answers "
                         f"from {answered['path']} - a **different file** from the one this "
                         "window holds, and the file `apply to the panel` would draw")
        state = "edit not saved yet" if self.ed.dirty else "nothing outstanding"
        self.ed_state.setText(f"{where}; {state}")
        self.ed_save.setEnabled(self.ed.dirty)
        self.ed_revert.setEnabled(themes.is_copy(self.ed.name))
        self.ed_undo.setEnabled(self.ed.steps > 0)
        self.ed_undo.setText(f"undo ({self.ed.steps})" if self.ed.steps else "undo")
        # the two acts that invent a name.  The box is refilled only when a *different*
        # layout is opened: a reader typing in it has the text under their cursor, and a
        # state refresh that retypes the name would be the window overwriting the person.
        if self._ed_named != self.ed.name:
            self.ed_newname.setText(self.ed.name)
            self._ed_named = self.ed.name
        self.ed_rename.setEnabled(themes.is_copy(self.ed.name))
        self.ed_rename.setToolTip(self._ed_rename_tip())
        self.ed_copy.setEnabled(True)
        self.ed_newname.setToolTip(self._ed_name_tip())
        # the structural controls, answered from the model rather than remembered: what
        # they can do depends on how many rows this layout has and which one is selected,
        # and the menu entries say what each add would copy *before* the press
        self.ed_del.setEnabled(len(self.ed.widgets()) > 1)
        self.ed_up.setEnabled(self.ed.index > 0)
        self.ed_down.setEnabled(self.ed.index < len(self.ed.widgets()) - 1)
        self._ed_fill_add_menu()

    def _editor_pick_widget(self, index: int) -> None:
        """Select one widget and lay out every field that kind carries.

        The rows are rebuilt when the *kind* changes - one `data` row becoming
        another re-binds values, it does not rebuild widgets, so focus and scroll
        position survive picking a different widget - and bound to the model on
        every selection.
        """
        if self.ed is None or int(index) < 0:
            return
        self.ed.select(int(index))
        self.ed_widget.setToolTip(self.ed.tip(int(index)))
        kind = str(self.ed.selected().get("type") or "")
        if kind != self._ed_kind:
            self._ed_build_rows(kind)
        self._ed_bind_rows()
        # the column's floor follows what the boxes now hold: the widget menu's entries
        # are as wide as the widest row any layout puts there, and that changes with the
        # layout - so the narrowest width the pane may be dragged to changes with it.  No
        # loop is possible: an entry's width is a fact about the text and the fonts, never
        # about the width the pane happens to have.
        self._pane_floors()
        # ...and the sentence under the rows goes back with them.  A reader can change the
        # *widget* while the keyboard focus stays where it was - the mouse picks the row
        # above, focus never moves - and then no FocusIn ever fires: the note line would be
        # left explaining the same field of a different widget, which is a sentence about a
        # row that is no longer on screen.  The suite found this by picking a `data` row
        # whose source has no reading and reading a stale `draws as "57°C"`.
        if getattr(self, "_ed_last", ""):
            self._ed_explain(self._ed_last)
        self._editor_state()

    def _ed_fields(self, kind: str) -> list:
        """One kind's fields, in the model's order: painter-read keys, then ours.

        `edit.field_names` is the intersection of what `layout.py` is proven to read
        (`themes.keys_read()` takes them out of the painter's own source) and what
        that kind draws, so the vendor's unread bookkeeping - `enableMove`,
        `screenStatus` - never gets a row and survives a save untouched.  Counting
        those inert keys is `--print-theme-fields`' business, not this form's.
        """
        return list(edit.field_names(kind)) + list(edit.extension_fields(kind))

    def _ed_set_enabled(self, on: bool) -> None:
        """The editor's controls, on or off, in one place.

        Off until a layout is open: a row that offers fields with no file behind it
        is a row that would write to nothing.  The grid's rows ride along with their
        host, so this names the host and the buttons rather than a per-field list that
        could fall out of step with whichever rows exist today.
        """
        for wid in (self.ed_widget, self._ed_host, self.ed_undo, self.ed_save,
                    self.ed_revert, self.ed_add, self.ed_del, self.ed_up, self.ed_down,
                    self.ed_newname, self.ed_rename, self.ed_copy, self.ed_peek):
            wid.setEnabled(on)
        # the peek belongs to an open layout, but its file field rides the *mode*: a
        # path box that is live while the mode is `the fixture` invites a typed path
        # nothing will read
        self.ed_peek_file.setEnabled(on and self.ed_peek.currentData() == "file")

    def _ed_build_rows(self, kind: str) -> None:
        """One control per field this kind carries, wired to the model.

        Which control, and why, is the model's answer rather than a switch written
        here: a menu wherever a vocabulary already exists in code (`edit.choices()`:
        families in `layout.FONTS`, metric names in the source table, drawings in
        `themes.SPECIALS`, painter conventions in `layout.ARC_PAINT`/`BAR_PAINT`,
        named ramps in `layout.COLOUR_RAMPS`), a checkbox for a bool, a spinbox for
        `edit.number_fields()`, a colour row for `edit.COLOUR_FIELDS`, and a plain
        text row only for what is genuinely free text - a line of `content`, a
        `format`.  A free-text box for `bold`, or a menu for a coordinate, is a way
        of typing something the model can only refuse; that is the reason the rows
        are built from those three lists and not from a label per key.
        """
        while self.ed_grid.count():
            item = self.ed_grid.takeAt(0)
            wid = item.widget()
            if wid is not None:
                wid.deleteLater()
        self.ed_rows = {}
        self._ed_focus = {}          # control id -> the field it edits, for the note line
        self._ed_says = {}           # field -> the sentence that row explains
        self._ed_had = {}              # field -> is this key in the file at all
        for field in self._ed_fields(kind):
            label = QLabel(field)
            extra = None                       # the colour row's swatch button
            opts = edit.choices(field)
            if field == "bold":
                ctl, what = QCheckBox("set"), "bool"
                ctl.toggled.connect(lambda on, f=field: self._ed_apply_row(f, True))
            elif opts:
                ctl, what = QComboBox(), "menu"
                ctl.currentIndexChanged.connect(
                    lambda _i, f=field: self._ed_apply_row(f, True))
            elif field in edit.number_fields():
                ctl, what = QSpinBox(), "num"
                # Deliberately wider than any legal value. A spinbox that clamps 999
                # down to 479 is a widget editing the file on its own; this repo's rule
                # is that an out-of-range value is *said*, so the box holds it, the
                # model refuses it, and the note line prints the refusal in its words.
                ctl.setRange(-100000, 100000)
                ctl.valueChanged.connect(lambda *_a, f=field: self._ed_apply_row(f, False))
                ctl.editingFinished.connect(lambda f=field: self._ed_apply_row(f, True))
            elif field in edit.COLOUR_FIELDS:
                ctl, what = QLineEdit(), "colour"
                extra = QPushButton()
                extra.setFixedSize(24, 22)
                extra.clicked.connect(lambda _c, f=field: self._ed_pick_colour(f))
                ctl.textEdited.connect(lambda *_a, f=field: self._ed_apply_row(f, False))
                ctl.editingFinished.connect(lambda f=field: self._ed_apply_row(f, True))
            else:
                ctl, what = QLineEdit(), "text"
                ctl.textEdited.connect(lambda *_a, f=field: self._ed_apply_row(f, False))
                ctl.editingFinished.connect(lambda f=field: self._ed_apply_row(f, True))
            _ed_shrink(ctl)
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(4)
            if extra is not None:
                bl.addWidget(extra)
            bl.addWidget(ctl)
            self.ed_rows[field] = (label, box, ctl, extra, what)
            ctl.installEventFilter(self)
            self._ed_focus[id(ctl)] = field
            if extra is not None:
                extra.installEventFilter(self)
                self._ed_focus[id(extra)] = field
        self._ed_kind = kind
        self._ed_place_rows()

    def _ed_ctl(self, field: str):
        """The control one row edits.  The offline checks drive rows through here."""
        return self.ed_rows[field][2]

    def _ed_place_rows(self) -> None:
        """Put the rows into the grid, column-first, at `self._ed_cols` columns.

        Column-first on purpose: `x`, `y`, `source` and the rest of one kind's list
        read *down* the first column, so a two-column form shows the same order the
        model's list has rather than shuffling it into a zigzag a reader has to chase.
        """
        for field, (label, box, _c, _e, _w) in self.ed_rows.items():
            self.ed_grid.removeWidget(label)
            self.ed_grid.removeWidget(box)
        fields = list(self.ed_rows)
        if not fields:
            return
        per = -(-len(fields) // self._ed_cols)          # ceil: rows per column
        for i, field in enumerate(fields):
            label, box = self.ed_rows[field][0], self.ed_rows[field][1]
            col, row = divmod(i, per)              # i // per = which column of rows,
            self.ed_grid.addWidget(label, row, col * 2)      # i % per = which row down it
            self.ed_grid.addWidget(box, row, col * 2 + 1)
        for col in range(self._ed_cols):
            self.ed_grid.setColumnStretch(col * 2, 0)   # the label takes what it needs
            self.ed_grid.setColumnStretch(col * 2 + 1, 1)
        for col in range(self._ed_cols * 2, 40):        # no leftover stretch columns
            self.ed_grid.setColumnStretch(col, 0)

    #: How much of the column one column of rows is allowed to ask for.  Measured, not
    #: guessed: the grid's own `minimumSizeHint` comes out at **171 px** for one column
    #: of rows, **344** for two and **512** for three - about 171 px per column, because
    #: the control can go that narrow while the *list* it opens still carries the
    #: entry's width (that is `_ed_shrink` doing its job, and `_readable` keeping the
    #: list honest).  240 per column is therefore the point where the next column
    #: genuinely fits rather than merely being asked for.  `tests/test_window_sizing.py`
    #: re-measures those three numbers in the live window and fails if three columns ever
    #: ask for more than this threshold says they get.
    _ED_COL_PX = 240

    #: The rows whose value decides *what line* a `text`/`data` widget paints, as opposed
    #: to where its ink sits or what colour it is.  `content` and `source` choose the
    #: words, `xigma.format` chooses their shape, `fontFamily`/`fontSize`/`bold` choose
    #: the face, `anchor`/`autoFitMax` choose how much of the line survives at the face
    #: it was laid out with, and `xigma.showIf` can take the row out before any of it is
    #: asked.  For these the note line says what the row draws (`edit.drawn_text`); the
    #: ink and position rows say nothing extra, because the picture under the cursor
    #: already answers those in the most direct way available.
    _ED_LINE_FIELDS = ("content", "source", "format", "fontFamily", "fontSize", "bold",
                       "anchor", "autoFitMax", "showIf")

    def _editor_reflow(self, width: int = 0) -> None:
        """One, two or three columns of rows, by the width the *pane* has.

        This is the responsive half, and it is here because the alternative is a
        scrollbar: the 18 rows of an `arc` widget stand a different height in each of
        the three layouts, and this window is the thing that measures it - so no
        figure for that height is repeated here, because the pair of machine-labelled
        readings this comment used to carry went stale the day the pane grew a row of
        buttons.  `python3 -m unittest tests/test_window_sizing.py` prints this
        machine's numbers - the floors, the split, the number of columns the grid laid
        itself out into, and the grid's own ask - and the gate beside it fails a
        controls column that cannot hold what it is shown, which is exactly the 0.4
        defect the fresh-window gate now fails on.  The box asks for it through
        `EditorBox.resizeEvent`, because the window's own `resizeEvent` never fires when a
        splitter handle is what changed.

        The width that decides it is the scroll area's **viewport**, never the box's
        own: the box is laid out at `max(viewport, its own minimum)`, so measuring the
        box and then choosing columns from it feeds itself - more columns, a wider
        minimum, a wider box - which is how the first version of this ended up with
        three columns in a 347 px pane and a horizontal scrollbar under it.  The
        viewport only depends on the splitter, so the loop cannot close.
        """
        if getattr(self, "_ed_reflowing", False):
            return
        self._ed_reflowing = True
        try:
            pane = self.split.widget(1)
            avail = pane.viewport().width() or width
            cols = max(1, min(3, avail // self._ED_COL_PX))
            if cols != self._ed_cols:
                self._ed_cols = cols
                self._ed_place_rows()
            # more columns means a wider minimum for this column, so the floor moves
            # with it - and because the grid only takes another column when the pane
            # already has _ED_COL_PX more to give, the new floor is always inside the
            # room that made the choice.  That is why this cannot oscillate.
            self._pane_floors()
        finally:
            self._ed_reflowing = False

    def _ed_bind_rows(self, only=None) -> None:
        """Read the model back into every row (or one), without firing it.

        The menu rows are filled here rather than at build time, because what a menu
        holds depends on what the row holds: an extension key that is **absent** gets
        the `UNSET` entry and it is the entry selected - showing the first choice
        instead would be the one lie this form could tell, since `arcPaint` missing
        *is* a value (the vendor's ring, not "render").  And a value the vocabulary
        does not name is put in the menu rather than hidden from it: the file is what
        it is, and a row that cannot show it is a row that will silently change it.
        """
        if self.ed is None or not self.ed_rows:
            return
        kind = str(self.ed.selected().get("type") or "")
        ext = set(edit.extension_fields(kind))
        name = str(self.ed.prop().get("name") or "")
        for field, (label, box, ctl, extra, what) in self.ed_rows.items():
            if only is not None and field != only:
                continue
            value = self.ed.value(field)
            if what == "bool":
                ctl.blockSignals(True)
                ctl.setChecked(bool(value))
                ctl.blockSignals(False)
            elif what == "menu":
                items = [str(o) for o in edit.choices(field)]
                ctl.blockSignals(True)
                ctl.clear()
                if value is None and field in ext:
                    items.insert(0, UNSET)
                elif str(value) not in items:
                    items.insert(0, str(value))
                ctl.addItems(items)
                ctl.setCurrentText(str(value) if value is not None else items[0])
                ctl.blockSignals(False)
                _readable(ctl)
                if field == "fontFamily":
                    # each entry shows the face it names, drawn from the file this box
                    # resolves it to, and an entry with no such file says so in its own
                    # tooltip rather than looking like a choice.  The icon size is set
                    # here because the style's default is not a size a face can be read
                    # at, and `_readable` already adds this width to the popup's list.
                    ctl.setIconSize(QSize(34, 22))
                    _ed_face_marks(ctl, self.ed.faces_here())
            elif what == "num":
                ctl.blockSignals(True)
                try:
                    ctl.setValue(int(value))
                    self._ed_had[field] = value is not None
                except (TypeError, ValueError):
                    # A key the file does not carry shows as 0 in the box, and that 0 is
                    # a placeholder, not a value: `_ed_had` remembers it so the row never
                    # writes the key back just because focus passed through.  Inventing
                    # `width: 0` on a drawing that never read `width` would change the
                    # file the reader only came to look at.
                    ctl.setValue(0)     # a missing key: the drawer's own default
                    self._ed_had[field] = False
                ctl.blockSignals(False)
            else:                        # text and colour both edit the spelling
                ctl.blockSignals(True)
                ctl.setText("" if value is None else str(value))
                ctl.blockSignals(False)
            if what == "colour" and extra is not None:
                spelled, _bad = edit.colour_text(value) if value else (None, "")
                extra.setStyleSheet(
                    f"background:{spelled or 'transparent'};"
                    f"border:1px solid #666;")
                # The sentence lives on the row's **label**, not on the
                # swatch, and that is a measurement rather than a taste:
                # a tooltip's popup takes its colours from the widget it
                # belongs to, so a popup on this button would be painted
                # in whatever colour the layout file names - and there
                # is no text colour legible on every colour a file can
                # name. Measured on the shipped tree with the colour
                # spelled `rgba(0, 0, 0, 255)`: a #000000 popup with the
                # palette's #000000 text, 1.00:1, no readable glyph
                # pixels at all; with the tooltip colours forced onto
                # the popup's own class the same black popup gains
                # #f2f2f2 text (legible), but at `rgba(255, 255, 255,
                # 255)` it keeps #ffffff behind that light text, 1.12:1.
                # A label carries no background of its own (the refusal
                # mark is a `color:` rule), so its popup follows the
                # rule at 12.65:1. Taking the tooltip off the swatch
                # changed 0 of its 2,112 grabbed bytes: the swatch
                # paints the colour and the click still opens the
                # dialog, and the words move.
                extra.setToolTip("")
            # why the row exists, from the model rather than from a table here
            label.setStyleSheet("")            # clear any refusal mark from before
        self._ed_say_rows()

    def _ed_say_rows(self) -> None:
        """Re-read the sentence each row carries, without touching any value.

        Two things decide those sentences and one of them is a field a reader can
        change: an extension key has a standing reason (`themes.XIGMA_KEYS`), and what
        a `special` row's `x`/`width`/`fontSize` *mean* depends on which drawing the
        row's `name` selects and which door that drawing draws through
        (`themes.special_is_pair`, `themes.special_door`, asked through
        `edit.field_note`).  So changing `name` changes the meaning of the rows around
        it, and a sentence left over from the previous drawing is a lie about the
        picture on screen.  Only the sentences are refreshed: a reader mid-keystroke in
        another row must not have their text replaced under them.
        """
        if self.ed is None or not self.ed_rows:
            return
        kind = str(self.ed.selected().get("type") or "")
        name = str(self.ed.prop().get("name") or "")
        for field, (label, _box, _ctl, _extra, _what) in self.ed_rows.items():
            why = themes.XIGMA_KEYS.get(field)
            self._ed_says[field] = (
                f"xigma.{field}: {why}" if why
                else (edit.field_note(kind, field, name) or
                      f"{field}: what the painter reads for a {kind} widget"))
            label.setToolTip(self._ed_says[field])
            if _what == "colour":
                # A colour row's second sentence, on the same label. It
                # used to sit on the swatch button, and it cannot go
                # back there: a tooltip's popup takes its colours from
                # the widget it belongs to, and this button's background
                # *is* whatever colour the layout file names. Measured
                # on the shipped tree, with the row spelled `rgba(0, 0,
                # 0, 255)`, that was a #000000 popup with the palette's
                # #000000 text: 1.00:1 and no readable glyph pixel; with
                # the tooltip colours forced on the popup's own class
                # the same popup paints #ffffff behind light text at
                # `rgba(255, 255, 255, 255)`: 1.12:1. A mid-grey defeats
                # either text colour, so no wording can be made legible
                # on every colour a file can name - the sentence moves
                # to a widget that paints no background, and
                # `tests/test_tooltips.py` measures the popup at white, black and grey and
                # fails on any pair of them it can read.
                # `_ed_says` stays the model's sentence alone: the note
                # line under these rows already says this in its own
                # words.
                label.setToolTip(f"{self._ed_says[field]}  {COLOUR_TIP}")

    def _ed_explain(self, field: str) -> None:
        """Say what one row means, and what the row it belongs to paints right now.

        Which sentence is the model's business, not this window's: `themes.XIGMA_KEYS`
        for this program's own keys, `edit.field_note` for the `special` drawings whose
        `x` and `width` mean a pair's centre and pitch rather than a box's corner and
        span - and which of those a row is, the registry answers through the door it
        draws (`themes.special_is_pair`/`special_door`).  Nothing here remembers that.

        The second half is the WYSIWYG one: for a `text` or `data` row, the keys that
        decide its *line* say what that line is (`edit.drawn_text`), because a format
        string or a family name is exactly the kind of value a reader cannot check by
        staring at it in a box.  When the line cannot be painted the same place carries
        the painter's own reason - no reading for that source, a `showIf` these readings
        do not answer, no file for that family on this box, or no family in the file at
        all - and when it is painted by a shape nobody measured off the vendor's picture,
        the caveat says so as well.  The
        suite proves the string is the painted line by drawing both doors and comparing
        the frames byte for byte.
        """
        if self.ed is None:
            return
        says = getattr(self, "_ed_says", {}).get(field, "")
        parts = [says] if says else []
        kind = str(self.ed.selected().get("type") or "")
        if field in self._ED_LINE_FIELDS and kind in ("text", "data"):
            if field == "fontFamily":
                fam, path, bold = self.ed.face_here()
                if not fam:
                    # the row carries no family.  Nothing is resolved and nothing is
                    # invented: the painter skips such a row, so saying "the default face"
                    # would promise ink that never arrives.
                    parts.append("the file names no family at all, and there is no "
                                 "default face to draw with")
                else:
                    same = sorted(f for f, p in self.ed.faces_here().items()
                                  if p and p == path and f != fam)
                    parts.append(f"this box draws `{fam}` as "
                                 + (os.path.basename(path) if path
                                    else "no file at all")
                                 + (" bold" if bold else " regular")
                                 + (f", the same face as {', '.join(same)}" if same
                                    else ""))
            line, note = self.ed.drawn_text(*self._note_pair())
            if line is None:
                parts.append(f"paints no line: {note}")
            else:
                parts.append(f'draws as "{line}"')
                if note:
                    parts.append(note)
        if parts:
            self._ed_last = field
            self.ed_note.setText("   ".join(parts))

    def _ed_row_value(self, field: str):
        """What one row's control currently holds."""
        _label, _box, ctl, _extra, what = self.ed_rows[field]
        if what == "bool":
            return ctl.isChecked()
        if what == "menu":
            return None if ctl.currentText() == UNSET else ctl.currentText()
        if what == "num":
            return ctl.value()
        return ctl.text()

    def _ed_apply_row(self, field: str, commit: bool) -> None:
        """Hand one row's value to the model, and print in words what it did.

        `commit=False` is a keystroke: the picture moves and the undo step waits, so
        a run of typing in one row is one undo (the coalescing `edit.Editor.set`
        implements that, not this window).  A refusal repaints nothing - the layout,
        the dirty flag and the history stay as they were, which is the part an editor
        most often gets wrong - and the refused row's label is marked, because with
        eighteen rows on screen a sentence in a note line is easy to lose.
        """
        if self.ed is None or field not in self.ed_rows:
            return
        if (self.ed_rows[field][4] == "num"
                and not self._ed_had.get(field, True)
                and self._ed_row_value(field) == 0):
            # the placeholder again: an untouched box on a key the file never held.
            # Writing it would be the editor changing the layout, not the reader.
            return
        ok, note = self.ed.set(field, self._ed_row_value(field), commit=commit)
        label = self.ed_rows[field][0]
        label.setStyleSheet("" if ok else "color:#c62828;font-weight:bold;")
        if note:
            self.ed_note.setText(note)
        if ok:
            self._ed_say_rows()          # `name` changes what the rows around it mean
            if self.ed_rows[field][4] == "colour":
                self._ed_bind_rows(field)      # show the rgba the model stored
            if not note:
                self._ed_explain(field)
            self._repaint(readings=False)
        self._editor_state()

    def _ed_pick_colour(self, field: str) -> None:
        """The colour dialog, for the row that asked - the window's one colour route.

        The ink of the *theme* has its own row above (and moves `render.SKIN` for the
        five drawn themes); this one writes this widget's own key, which is what a
        layout file spells.  The value goes in as `#rrggbb` and comes back as
        `rgba(r, g, b, 1)` because `layout.rgba` reads nothing else - `edit.set` says
        that conversion out loud rather than doing it quietly.
        """
        if self.ed is None or field not in self.ed_rows:
            return
        ctl = self.ed_rows[field][2]
        start = QColorDialog.getColor(QColor(ctl.text()) if ctl.text() else QColor(255, 255, 255),
                                      self, f"{field}: pick a colour")
        if not start.isValid():
            return
        ctl.setText(start.name())                # the row shows the hex it typed
        self._ed_apply_row(field, True)

    # ------------------------------------------------ the structural controls --
    def _ed_fill_add_menu(self) -> None:
        """One entry per kind, each saying which real row a new one of that kind copies.

        The sentence is the model's (`edit.Editor.add_note`), not a description written
        here, so the menu cannot promise a row the model would not build.  A `special`
        gets a sub-menu of the drawings this program has, because a `special` with no name
        is not a thinner picture: the painter records `special:<name>` and skips the row,
        which is why the model refuses to add one unnamed.
        """
        if self.ed is None:
            return
        self.ed_add_menu.clear()
        for kind in edit.kinds():
            if kind == "special":
                sub = self.ed_add_menu.addMenu("special")
                for nm in sorted(themes.SPECIALS):
                    act = sub.addAction(nm)
                    act.setToolTip(f"a `special` row drawing `{nm}`; every other key is "
                                   f"copied from {self.ed.add_note('special')}")
                    act.triggered.connect(lambda _c, n=nm: self._editor_add("special", n))
                continue
            act = self.ed_add_menu.addAction(kind)
            act.setToolTip(self.ed.add_note(kind))
            act.triggered.connect(lambda _c, k=kind: self._editor_add(k))

    def _ed_refresh_widget_list(self) -> None:
        """Re-fill the widget menu after rows were added, removed or moved.

        The labels come from the model (`ed.label`), so the menu says what the file holds;
        signals are blocked because replacing the list would otherwise fire a selection
        change against a half-built menu, and the row the model selected is put back by
        index afterwards.
        """
        self.ed_widget.blockSignals(True)
        self.ed_widget.clear()
        for i in range(len(self.ed.widgets())):
            self.ed_widget.addItem(self.ed.label(i))
        self.ed_widget.setCurrentIndex(self.ed.index)
        self.ed_widget.setToolTip(self.ed.tip(self.ed.index))
        self.ed_widget.blockSignals(False)

    def _editor_add(self, kind: str, name: str = "") -> None:
        """Ask the model for a row, then make the window agree with the file."""
        if self.ed is None:
            return
        good, said = self.ed.add_widget(kind, name=name)
        self._log(("row added: " if good else "row refused: ") + said)
        if good:
            self._ed_refresh_widget_list()
            self._editor_pick_widget(self.ed.index)
            self._repaint()
        self.ed_note.setText(said)
        self._editor_state()

    def _editor_delete_row(self) -> None:
        if self.ed is None:
            return
        good, said = self.ed.delete_widget()
        self._log(("row removed: " if good else "row not removed: ") + said)
        if good:
            self._ed_refresh_widget_list()
            self._editor_pick_widget(self.ed.index)
            self._repaint()
        self.ed_note.setText(said)
        self._editor_state()

    def _editor_move_row(self, delta: int) -> None:
        """Slide the selected row through the list.

        `up` is an earlier index, which is *under* the rest: the list is the draw order,
        so the words on the buttons say what happens to the picture rather than what
        happens to a number.
        """
        if self.ed is None:
            return
        good, said = self.ed.move_widget(int(delta))
        self._log(("row reordered: " if good else "row not reordered: ") + said)
        if good:
            self._ed_refresh_widget_list()
            self._editor_pick_widget(self.ed.index)
            self._repaint()
        self.ed_note.setText(said)
        self._editor_state()

    def _editor_undo(self) -> None:
        if self.ed is None:
            return
        if self.ed.undo():
            # Undo puts a whole layout back, and a whole layout includes how many rows
            # there are: a row that was added, removed or moved comes back, so the widget
            # menu is rebuilt from the model before anything is bound to it.  Signals stay
            # blocked inside that rebuild, so this cannot fire a selection change twice.
            self._ed_refresh_widget_list()
            self._ed_bind_rows()      # every row re-reads the model: undo may have
                                      # moved any of them, not the one you were in
            # ...and the sentence line goes back with them. Undo can change which
            # drawing a `special` row is, and that is what decides whether `width` is a
            # pitch or a key the drawing never reads: a note left describing the other
            # door would talk about a picture that is no longer on screen.
            self._ed_explain(getattr(self, "_ed_last", ""))
            self._repaint()
        self._editor_state()

    def _editor_save(self) -> None:
        """Write through the library's one writer, and report what it said."""
        if self.ed is None:
            return
        path, notes = self.ed.save()
        if path is None:
            self.ed_note.setText(" / ".join(notes))
            self._log(f"layout not saved: {notes[0]}")
            self._editor_state()
            return
        self._log(f"layout saved: {path}")
        self.ed_note.setText(
            f"saved at {path}" + (f" - {'; '.join(notes)}" if notes else
                                  f" - `--theme {self.ed.name}` now draws this file, "
                                  "and a loop already running that name picks it up on "
                                  "its next read (the file is re-read when it changes)"))
        self._editor_state()

    def _editor_revert(self) -> None:
        if self.ed is None:
            return
        gone = self.ed.revert()
        self._log(f"layout copy removed: {gone or self.ed.name}")
        # "the loop reads the vendor's file again" is only true of a name the library also
        # has.  A renamed copy answers a name of your own inventing, and there is no vendor
        # file behind it to come back - so the line asks the library which file answers the
        # name now rather than repeating a sentence about a copy that may never have had one.
        back = themes.resolve(self.ed.name)
        self.ed_note.setText(
            "your copy is gone: "
            + (f"--theme {self.ed.name} reads {back['path']} again" if back else
               f"nothing answers {self.ed.name!r}, because that name was yours alone - "
               f"the library has no file of that name to fall back to")
            + ". What you typed is still here, unsaved.")
        self._ed_refresh_layouts()
        self._editor_state()

    def _ed_apply_panel_tip(self) -> str:
        """The button's sentence, before the press.

        Three things a reader cannot see from the picture, in the order they bite: that the
        pane is the pinned fixture and the panel is live readings, that this sends one
        setting where the theme box's Apply sends seven, and that two things this program
        changes elsewhere - the panel's stored background, and the theme's ink - are not in
        this command at all.
        """
        return ("tell a running display to draw the layout this box has open: the one "
                "command `--theme <name>` already means when the loop starts. The pane is "
                "showing the pinned fixture; the panel paints this file at this machine's "
                "live readings, so the digits differ. One setting goes, not seven - the "
                "theme box's `Apply these settings` is where clock size, canvas, scrim, "
                "fans and fps live. What this does not touch: the panel's stored "
                "background (the clips box sends that, Ctrl+Shift+U), the colours written "
                "in the layout file, and what a fresh display starts with, which is its "
                "own `--theme`.")

    def _apply_layout_to_display(self) -> None:
        """Tell a running display to draw the layout this editor has open.  One command.

        `daemon.apply` sends the theme box's seven pickers, and a button sitting under the
        *layout* rows has no business moving the clock size, the canvas, the scrim, the fan
        figures or the frame rate while the reader is looking at one row's `x`.  This is the
        narrow door: `("theme", <this layout's name>)`, and nothing else.

        The door is not new; the handle was.  `control.Control._set_theme` has taken both
        halves of the vocabulary since 0.4 - it refuses only a name that `render.THEMES`
        lacks *and* `themes.resolve` answers None for - while the window's only route to it
        was the theme combo, which lists `sorted(render.THEMES)`: five entries, against the
        28 the editor can open.  Measured on 2026-11-11: with the editor open on `Theme_01`,
        pressing `Apply these settings` sent `theme='alpha'`, and the 23 layouts this program
        paints only from a file - plus any copy of your own - had no route to the glass in
        this window at all.

        What gets said after the press is read, not remembered.  The display's own reply
        carries `status["theme"]` (PROTOCOL.md §11: no readback of pixels, but settings come
        back), and the box counts come from the **loop's own door** for a name that resolves to
        a file - `themes.paint`, the function that will draw the next frame on that panel - and
        from `Editor.paint` for one of the five names this repo draws from code, which has no
        file to resolve.  Against the same file at the pinned fixture: the two frames this
        window is standing between.  Drawn first, before the command goes: a count that failed
        should not be able to leave the panel changed and the window silent.

        That door choice is the whole lesson of a defect fixed on 2026-11-12.  The counts used
        to come from the pane's door while the panel was handed the loop's, and the two filled
        different value tables: a saved copy of `alpha` lost its `temp-values` and
        `fan-figures` rows on the glass and this line still reported a complete picture.  It
        also says why a **count** is not a picture - a `special` row that draws nothing is still
        in `notes["boxes"]`, with no box beside it, so `len()` cannot see the loss.  The figure
        that can is `--check-theme`'s lit pixels, and the caption under the pane names the door
        the count came from.
        """
        if self.ed is None:
            self._log("nothing to apply: the layout box holds nobody. Pick one above, or "
                      "use the theme box's `Apply these settings` for the five this "
                      "program draws from code")
            return
        if not self.daemon.present:
            # the button is disabled in this state; the guard is for the keyboard shortcut
            self._log("no display running to tell: this window visits the port itself, one "
                      "action at a time, and a layout the panel has never seen is one "
                      "frame at a time (`Send one frame`)")
            return
        name = str(self.ed.name)
        if self.ed.origin == edit.PATH_ORIGIN and not themes.is_copy(name):
            # The one press here that cannot be answered by sending a name.  `apply` sends
            # `("theme", <name>)`, and the display resolves that name in the roots **it** can
            # see - so a layout opened from a path outside them would be answered by another
            # file (a vendor's, at a colliding name) or refused, and either way the panel
            # would end up drawing something other than the picture this window is showing.
            # Refusing costs nothing and says what to do instead.
            answered = themes.resolve(name)
            self._log(
                f"nothing sent: `{name}` is the file you opened at {self.ed.opened}, and a "
                f"display is told a *name*, not a path. "
                + (themes.why_not(name) if answered is None else
                   f"that name answers from {answered['path']}, which is not the file in "
                   f"this window")
                + ".  `save as your copy` puts it in "
                + f"{themes.user_root()}, and this same picture is what the panel draws then.")
            return
        # what the two frames this window sits between actually hold, counted by the painter -
        # and by the painter that will do the drawing, which is `themes.paint` for anything
        # resolving to a file.  One variable, not two: the body.  The instant stays
        # `edit.FIXTURE_WHEN`, the same rule feature G set for a peek - `Date`, `Time` and
        # `Week` come from the instant rather than from any reading, so a moving instant would
        # rewrite those rows every second and the count would stop being about readings at all.
        # Drawn before the command goes: a count that failed should not be able to leave the
        # panel changed and the window silent.
        pinned, at = self.ed.fixture()
        rec = themes.resolve(name)
        if rec is not None:
            _live, live_notes = themes.paint(rec, sensors.collect(), at)
            _pin, pin_notes = themes.paint(rec, pinned, at)
        else:
            # one of the five names this repo draws from code: there is no file to resolve, so
            # the editor's object is the thing and `Editor.paint` is its door
            _live, live_notes = self.ed.paint(sensors.collect(), at)
            _pin, pin_notes = self.ed.paint(pinned, at)
        n_live = len(live_notes.get("boxes") or [])
        n_pin = len(pin_notes.get("boxes") or [])
        rep = self.daemon.send("theme", value=name)
        if not rep.get("ok"):
            self._refused_layout(name, rep)
            return
        shown = str((rep.get("status") or {}).get("theme") or name)
        if rec is None:
            # one of the five this program draws from code: the theme box names the same
            # thing, and two controls that disagree about what the panel draws are worse
            # than either one, so make them agree instead of leaving the reader to notice
            if self.theme.currentText() != name:
                self.theme.setCurrentText(name)
            self._log(f"panel draws {shown} (its own status says so). That is one of the "
                      f"five this program draws from `render.py`, so the theme box's picker "
                      f"names it too, and its `Apply these settings` reaches the same door")
        else:
            self._log(f"panel draws {shown} (its own status says so), from "
                      f"{self.ed.where}. At this machine's readings, at the same pinned "
                      f"instant, that file paints "
                      f"{n_live} boxes, against {n_pin} at the pinned fixture the pane is "
                      f"showing: a row whose reading this box cannot answer is skipped on "
                      f"the glass. The panel's stored background is untouched by this "
                      f"command, and so are the colours the file names for its own glyphs - "
                      f"the theme box's colour row paints only what this program draws. And "
                      f"the theme box's `Apply these settings` would send its own pick "
                      f"({self.theme.currentText()}) back over this one: the two controls "
                      f"write the same setting")
        self._log("what a fresh display starts with is its own `--theme`, not this change: "
                  "the service's line says it, and `--theme <name>` at a start is the way "
                  "to make this one stick")

    def _refused_layout(self, name: str, rep: dict) -> None:
        """The display said no to a name this window resolves, so its words are the report.

        Reported 2026-11-11: the five code-drawn names applied, `Theme_*` did not.  Both
        shapes of door were read side by side before a line here was written.  This tree's
        `xigmalcd.control.Control._set_theme` answers `ok=True` for `Theme_01`, `Theme_07`,
        the numeric id `1757491588804` and a copy written into a temp user root, and refuses
        a name nothing resolves with `themes.why_not`'s sentence - which names the roots it
        searched, in the order `themes.roots()` gives them: your copies first, then the
        checkout, then `/usr/share/xigmalcd/themes/alpha`.  The other door is what
        `git show v0.3:xigmalcd/control.py` shows: `if name not in render.THEMES`, and a
        refusal naming the five drawn names and no directory at all.  The installed 0.3
        package ships no `xigmalcd/themes.py`, so that build has nothing to resolve a
        layout with.  The same
        press means different things against different displays, so this says both
        possibilities and how to tell them apart instead of picking one: the display, not
        this window, is what decides.
        """
        _was = (self.daemon.status or {}).get("theme") or "what it had"
        self._log(f"the panel kept {_was}: {name} did not reach it")
        # verbatim, not paraphrased: what separates the two answers below is in the
        # display's own phrasing, and a summary of it would hide the evidence
        self._log(f"the display's own words: {rep.get('error') or 'it gave no reason'}")
        self._log(
            "two possibilities, and those words say which.  (a) that display is older than "
            "this window's layout door: the socket's `theme` command took only the five "
            "names this program draws from `render.py` until 0.4, and a refusal that lists "
            "exactly those five and names no directory is that door.  Which display is "
            "running: the packaged service starts `/usr/bin/xigmalcd`, out of the installed "
            "package, while a display started from a checkout resolves that tree's files.  "
            "(b) that display is new enough, and this layout is not under a root it "
            f"searches - this window opened {name} out of {self.ed.where}, and that door's "
            "refusal names the roots it did search.  `xigmalcd --list-themes` on that "
            "machine prints what it can resolve.  Either way the layout's file is on this "
            "disk, and `save as your copy` writes a version of it into "
            "~/.config/xigmalcd/themes, which every display searches first")

    # ------------------------------------------------------- the canvas door --
    # Pointing at the picture is the other half of the editor: a row's ink box is where
    # that row is on the glass, so a press can select it and a drag can move it.  Nothing
    # in these methods decides anything about a layout - a distance goes to `edit.Editor`,
    # the same door the field spinbox uses, with the same refusals and the same undo stack,
    # and for a resize the same `SIZE_KEYS` table - and the pane's marks are chrome painted
    # by `Canvas`, never pixels added to the composite.
    def _mark_box(self, wi: int):
        """The box row `wi` put ink in, from the last editor paint, or None.

        One lookup for three doors: the pane's rectangle, the pane's hit test (which reads
        the same records) and the model's resize all start here, so nobody keeps a private
        copy of where a row sits.
        """
        for _kind, _what, box, ri in (self._ed_notes.get("boxes") or []):
            if ri == wi and box:
                return box
        return None

    def _canvas_marks(self) -> None:
        """Mark the box the selected row actually put ink in, as the last paint reported.

        This is the resting state: it paints the box that *is*.  While a resize drag is in
        flight `_canvas_resize_move` paints a second box beside it, the one the release
        would ask for, and this method drops that mark again when the drag ends.
        """
        self._off_glass = ""
        if self._peek is not None and not self._peek.get("live"):
            # A **held** peek carries no marks: the box, the eight squares and any guide line
            # would be drawn from the pinned row's edges while the ink on screen came from
            # another body, and `tests/test_peek_readings.py` counts the points on the glass
            # that answer a different row in the other frame than in the pinned one (and
            # fails if none of them does).  Hiding the marks is the honest half of the rule
            # that a held peek cannot be edited in - a handle drawn over nothing is a lie -
            # and the tooltip says so before a press is wasted.  A **live** peek falls
            # through: its marks come from the same paint the picture came from, so the
            # square is over the ink it describes.
            self.preview.set_marks(None)
            self.preview.setToolTip("the pane is peeking at a body it read once, rather "
                                    "than following this machine: press, drag and arrow keys "
                                    "do nothing here.  Choose `the fixture` under *pane "
                                    "readings* to edit the file, or `this machine's "
                                    "readings` to watch it live and edit what you see.")
            return
        if self.ed is None:
            self.preview.set_marks(None)
            self.preview.setToolTip("")
            return
        box = self._mark_box(self.ed.index)
        if box is None:
            # a row the machine could not draw has no box, and a rectangle around nothing
            # would be the pane inventing a position for it.  Its tooltip says why there is
            # nothing to drag, in the same words the model refuses with.
            self.preview.set_marks(None)
            self.preview.setToolTip("this row paints no box at this fixture, so it has no "
                                    "edge to grab and no square to drag")
            return
        text = self.ed.label(self.ed.index)
        w = int(self.ed.obj.get("width") or render.W)
        h = int(self.ed.obj.get("height") or render.H)
        if box[0] < 0 or box[1] < 0 or box[2] >= w or box[3] >= h:
            # the model refuses an *anchor* off the canvas and says nothing about
            # ink that hangs off it, because that is the vendor's rule too (a
            # `property` is checked by x,y).  So the pane says it out loud: a row
            # dragged to the edge is drawing pixels the glass will not show.
            self._off_glass = (f"its ink runs to {box[2]},{box[3]} - off the "
                               f"{w}x{h} canvas")
            text = f"{text}  [{self._off_glass}]"
        handles = self.ed.size_edges(self.ed.index, box)
        # a repaint can arrive in the middle of a resize drag: the note line under the rows
        # changes height, the splitter refits the pane, `_repaint` runs and lands back here.
        # The ask the reader is aiming at has to survive that, so the target comes from the
        # drag's own state instead of being dropped on every repaint.
        self.preview.set_marks((box, text, self._resize_target if self._resize else None,
                                handles, self._snap_guide if self._drag else ()))
        # the tooltip is where the pane says, before a press, what its edge is for - and
        # the answer is the model's, not a sentence written here about kinds
        keys, why = self.ed.size_door(self.ed.index)
        self.preview.setToolTip(
            "press a row's box to select it, and drag it to move it.  "
            + (f"Drag one of the squares on that box to resize the row: this row's size is "
               f"decided by {', '.join(f'`{k}`' for k in keys)}, at its "
               f"{', '.join(handles)} handles.  {why}."
               if keys else f"That row's edges are not handles: {why}.")
            + "  None of it reaches the panel: a save writes your copy.")

    def _canvas_press(self, px: int, py: int, edge: str = "") -> None:
        if self.ed is None:
            return                        # the pane is a live preview: nothing to move
        if self._peek is not None and not self._peek.get("live"):
            # The model's sentence, not one written here: what a held peek is, why a grab is
            # refused, and which knob opens the editable frame again.  A live peek has no
            # such refusal: its marks, its hit test and its handles all come from the frame
            # on screen, so the row you point at is the row you move.
            self.ed_note.setText(self.ed.peek_refusal("A press on the glass"))
            return
        idx = self.ed.hit(self._ed_notes, px, py)
        box = self._mark_box(self.ed.index)
        if edge and box:
            # the eight squares the pane paints are chrome owned by the row that is
            # selected, so a press on one resizes *that* row even where another row's ink
            # lies underneath.  The other rule - the later row wins an overlap - is about
            # ink, and a handle is not ink: grabbed by a reader who can see the square and
            # not the overlap, it would move a row nobody selected.
            handles = self.ed.size_edges(self.ed.index, box)
            self._resize = [px, py, edge, self.ed.index, box, handles]
            self._resize_ask = (0, 0)
            self._resize_note = ""
            self._resize_target = None
            self._resize_over = (f"row {idx}'s ink lies under the handle being dragged: the "
                                 f"row resized is row {self.ed.index}, the one selected"
                                 if idx is not None and idx != self.ed.index else "")
            self.preview.set_edge_cursor(edge)
            self.preview.set_marks((box, self.ed.label(self.ed.index), None, handles))
            return
        if idx is None:
            self.preview.set_marks(None)
            self.ed_note.setText(f"nothing is drawn at {px},{py}: that press selects no "
                                 "row and moves nothing")
            return
        # this press is a move, not a resize: whatever the last press was doing, it ended
        self._resize = None
        if self.ed_widget.currentIndex() == idx:
            self._editor_pick_widget(idx)     # same row: bring its fields up to date
        else:
            self.ed_widget.setCurrentIndex(idx)   # the signal selects it
        pr = self.ed.prop()
        self._drag = [px, py, int(pr.get("x") or 0), int(pr.get("y") or 0)]
        self._drag_refused, self._drag_note = False, ""
        # asked once, at the press, for the row this press selected: `was` is this drag's
        # own starting anchor, which is what lets a row leave a line it is sitting on
        self._snap_lines = self.ed.snap_lines(idx, box=self._mark_box(idx))
        self._snap_guide, self._snap_said = (), ""
        self._canvas_marks()

    def _canvas_move(self, px: int, py: int) -> None:
        """Live apply, coarse on purpose: the row follows the cursor through the model.

        `commit=False` is the spinbox's own coalescing - the picture moves, no undo step
        is written yet - and the canvas edge is a refusal rather than a wall: once the
        model says the anchor would leave the canvas, the sentence is printed and the row
        stays at the last position it was allowed to hold.
        """
        if self._resize:
            self._canvas_resize_move(px, py)
            return
        if self.ed is None or not self._drag:
            return
        x0, y0, ax, ay = self._drag
        gx, gy = ax + px - x0, ay + py - y0
        # the pull is the model's: the lines it offered at the press, this drag's starting
        # anchor, and nothing else.  The pane never decides how far a snap reaches, which
        # number it picks when two lines are near, or what the line is called.
        gx, gy, said = self.ed.snap_move(gx, gy, index=self.ed.index, was=(ax, ay),
                                         lines=self._snap_lines)
        self._snap_guide = tuple(dict.fromkeys(
            (("x", gx) if n.startswith("snapped x") else ("y", gy)) for n in said))
        self._snap_said = "  ".join(said)
        ok, note = self.ed.move_to(gx, gy, commit=False)
        if not ok and not self._drag_refused:
            self.ed_note.setText(note)
            self._drag_note = note
            self._drag_refused = True
        elif self._snap_said:
            # a row that stops 2 px short of the cursor needs a reason on the glass rather
            # than a mystery, and the reason is the file's: this is the number it is on
            self.ed_note.setText(self._snap_said)
        self._repaint(readings=False)
        self._canvas_marks()

    def _canvas_resize_move(self, px: int, py: int) -> None:
        """Paint the box a resize drag is asking for; write nothing yet.

        The ask comes from `edit.Editor.resize_box`, which is the same door `resize_row`
        answers through, so the amber rectangle is the model's arithmetic rather than the
        pane's guess.  Nothing is drawn into the frame and no key is touched: a row's face
        and a ring's radius are decided on release, once, because each of them needs the
        painter to answer first.
        """
        if self.ed is None:
            return
        x0, y0, edge, i, box, handles = self._resize
        dx, dy = px - x0, py - y0
        self._resize_ask = (dx, dy)
        over = f"  {self._resize_over}" if self._resize_over else ""
        nb, bad = self.ed.resize_box(dx, dy, edge, i, box)
        self._resize_target = None if bad else nb
        if bad:
            # the refusal changes as the cursor crosses the glass, so it is said whenever
            # it is a different refusal rather than once per press
            if bad != self._resize_note:
                self.ed_note.setText(bad + over)
                self._resize_note = bad
            self.preview.set_marks((box, self.ed.label(i), None, handles))
            return
        self.preview.set_marks((box, self.ed.label(i), nb, handles))
        asked = (f"dragging row {i}'s {edge} edge: asking for "
                 f"{nb[2] - nb[0]}x{nb[3] - nb[1]} px against the "
                 f"{box[2] - box[0]}x{box[3] - box[1]} px it has. Nothing is written until "
                 f"you let go.")
        self.ed_note.setText(asked + over)

    def _canvas_release(self) -> None:
        if self._resize:
            self._canvas_resize_release()
            return
        if not self._drag:
            return
        if self.ed is None:
            self._drag = None
            return
        pr = self.ed.prop()
        dx = int(pr.get("x") or 0) - self._drag[2]
        dy = int(pr.get("y") or 0) - self._drag[3]
        self._drag = None
        self.ed.commit()                    # one drag, one undo step
        self._ed_bind_rows()                # the x/y rows show where the row landed
        self._repaint()
        self._canvas_marks()
        self._editor_state()
        pr_x, pr_y = int(pr.get("x") or 0), int(pr.get("y") or 0)
        if dx or dy:
            # a drag that was part-refused moved what it was allowed to: say both, because
            # a sentence about a distance the cursor travelled would be a claim about the
            # mouse, not about the row
            said = f"dragged ({dx:+d}, {dy:+d}) px: one undo step, no file until you save"
            self.ed_note.setText(said if not self._drag_refused else
                                 f"{said}. {self._drag_note}, so the row ended at "
                                 f"{pr_x},{pr_y}")
        else:
            self.ed_note.setText(
                "the drag ended where it began: nothing moved, so nothing to undo"
                if not self._drag_refused else
                f"nothing moved: {self._drag_note}")
        if self._off_glass:
            self.ed_note.setText(f"{self.ed_note.text()}. {self._off_glass}")
        if self._snap_said:
            # the last word is the model's: which of this file's numbers the row ended on,
            # and how far the pull was.  Cleared with the drag, so the next press starts
            # clean and a stale line is never painted for a drag that has ended.
            self.ed_note.setText(f"{self.ed_note.text()}. {self._snap_said}")
            self._snap_said, self._snap_guide, self._snap_lines = "", (), None
        if dx or dy:
            self._log(f"canvas drag: {self.ed.name} row {self.ed.index} by "
                      f"({dx:+d}, {dy:+d})")

    def _canvas_resize_release(self) -> None:
        """One press, one drag, one act: hand the ask to the model and say what it wrote.

        The distance is the one the last mouse-move reported, because that is the box the
        reader was shown.  A press on a handle that never moved writes nothing at all, and
        says that rather than calling the door with a zero drag - which would be an act
        whose whole result is a refusal.
        """
        x0, y0, edge, i, box, _handles = self._resize
        dx, dy = self._resize_ask
        over = f"  {self._resize_over}" if self._resize_over else ""
        self._resize, self._resize_ask = None, (0, 0)
        self._resize_over, self._resize_target = "", None
        self.preview.set_edge_cursor("")
        if self.ed is None:
            self._canvas_marks()
            return
        if not dx and not dy:
            self.ed_note.setText(f"the press landed on row {i}'s {edge} edge and the "
                                 f"mouse never moved: nothing was written" + over)
            self._canvas_marks()
            return
        ok, said = self.ed.resize_row(dx, dy, edge, i)
        self.ed_note.setText(said + over)
        self._ed_bind_rows()            # the field rows show the keys that moved
        self._repaint()
        self._canvas_marks()
        self._editor_state()
        if ok:
            self._log(f"canvas resize: {self.ed.name} row {i} from its {edge} edge by "
                      f"({dx:+d}, {dy:+d})")

    def _canvas_nudge(self, dx: int, dy: int) -> None:
        """Arrow keys move the selected row: 1 px, 10 with Shift, one step per press.

        A **held** peek refuses the key before any of that, in the model's words: a nudge is
        a precise act - one pixel asked for, one pixel given - and a frame held from a sample
        that is already stale has no pixel to nudge against.  Feature F never snaps a key
        either; this is the other half of the same rule.  A **live** peek does not refuse it:
        the frame under the key is the frame this machine is answering now, and the marks the
        nudge moves were taken from that paint.
        """
        if self._peek is not None and not self._peek.get("live"):
            self.ed_note.setText(self.ed.peek_refusal("An arrow key"))
            return
        if self.ed is None:
            return
        ok, note = self.ed.move(dx, dy)
        if not ok:
            self.ed_note.setText(note)
            return
        self._ed_bind_rows()                # the x/y rows show the new position
        self._repaint(readings=False)
        self._canvas_marks()
        self._editor_state()
        if self._off_glass:
            self.ed_note.setText(f"nudged ({dx:+d}, {dy:+d}) px: {self._off_glass}")
    # ---- what the panel actually holds ----------------------------------
    def _read_ring(self, events: list) -> None:
        """Learn from the display's record which background it put on the panel.

        That ring is the only account of the *verdict*.  An `upload` over the
        socket answers `queued` in a few milliseconds, because the frame loop -
        never the socket - owns the port (`xigmalcd/control.py`), so the panel's
        answer arrives later and only as a note.  A window that ignored the ring
        could say "I asked" but not "it is there", which is exactly the gap the
        bench fell into when a background change looked like it had done nothing.
        """
        for line in events:
            m = re.search(r"background (\S+) accepted", line)
            if m:
                self._stored_bg = m.group(1)
                continue
            m = re.search(r"queued upload: (\S+)", line)
            if m:
                self._queued_bg = os.path.basename(m.group(1))
        self._refresh_clip_state()

    def _refresh_clip_state(self) -> None:
        """One line that keeps 'I picked this' and 'the panel stores this' apart.

        Three states, because that is all there is evidence for: the display
        reported an accept of this clip, it reported an accept of something
        else, or this window has not seen one.  There is no way to ask the panel
        (PROTOCOL.md §11), so the third is shown as unknown rather than guessed
        from the preview - the preview is our composite, not the glass.
        """
        want = os.path.basename(self.mp4)
        # mark the row that is on the glass, if this window knows: in a 40-row
        # list (115 with the Windows partition mounted) "which of these is the
        # panel actually storing" is the first question, and the answer comes
        # from the display's ring, not from the panel.  Only touched when the
        # answer changed - the status poll runs every 2 s.
        if self._stored_bg != self._marked_bg:
            # the first time _build() reaches here the list has not been
            # populated yet, so there are no rows to mark
            for i, c in enumerate(getattr(self, "all_clips", [])):
                row = self.clips.item(i)
                if row is None:
                    continue
                font = row.font()
                font.setBold(os.path.basename(c.path) == self._stored_bg)
                row.setFont(font)
            self._marked_bg = self._stored_bg
        # First the file itself, with the daemon's own rule (control.py's
        # `check_media_file` - one implementation, so the window can never
        # promise something the socket would refuse).  A clip that check refuses is
        # said out loud before the button is ever pressed: the bench's whole
        # afternoon of "the background change failed" started with a refusal that
        # had no place to be read.
        ok, why = wire.check_media_file(self.mp4)
        if not ok:
            self.btn_upload.setEnabled(False)
            self.btn_upload.setText("This file cannot go to the panel")
            self.btn_upload.setToolTip(why)
            self.clip_state.setStyleSheet("font-family:monospace;color:#c66;")
            self.clip_state.setText(f"{want}: the display's own gate refuses it - "
                                    f"{why}")
            return
        self.btn_upload.setEnabled(True)
        self.btn_upload.setToolTip(
            "send the selected file to the panel as its stored background layer, "
            "under the frame we draw. This overwrites what is stored, and only "
            "the guarded factory reset clears it (docs/troubleshooting.md). "
            "Ctrl+Shift+U")
        if not self.daemon.present:
            self.btn_upload.setText("Send this background to the panel")
            self.clip_state.setStyleSheet("font-family:monospace;color:#888;")
            self.clip_state.setText(
                "no display running, so this window visits the port itself: the "
                "panel stores whatever the last upload left there, and the log "
                "says what the panel answered to each one")
            self.d_stored.setText("the panel stores: only this window's own "
                                  "uploads, one visit at a time")
            return
        if self._stored_bg == want:
            self.btn_upload.setText("Send this background again")
            self.clip_state.setStyleSheet("font-family:monospace;color:#7a7;")
            self.clip_state.setText(
                f"the panel stores {want}: the display reported it accepted it, "
                f"so the frames on the glass are drawing over that picture")
            self.d_stored.setText(f"the panel stores: {want}")
        elif self._stored_bg:
            self.btn_upload.setText("Send this background to the panel")
            self.clip_state.setStyleSheet("font-family:monospace;color:#ca5;")
            self.clip_state.setText(
                f"the panel stores {self._stored_bg}, and this pick ({want}) is "
                f"not on it"
                + (", though you have just asked for it - waiting for the "
                   "display's answer" if self._queued_bg == want else ""))
            self.d_stored.setText(f"the panel stores: {self._stored_bg}")
        else:
            self.btn_upload.setText("Send this background to the panel")
            self.clip_state.setStyleSheet("font-family:monospace;color:#888;")
            self.clip_state.setText(
                "the panel's stored background: this window has not seen an "
                "accept from the display yet, and the panel itself cannot be "
                "asked - the 'last things it did' list below is the record")
            self.d_stored.setText("the panel stores: not reported by the "
                                  "display since this window started watching")

    # ---- actions ---------------------------------------------------------
    def queue(self, kind: str, **kw) -> None:
        """Hand an action to whoever can do it: the running display, or the port.

        When a display is running it holds /dev/ttyACM0, so opening the port
        here would be refused at the `port_busy` check below at best, and a fight
        with a live session at worst.  Every action has a socket route, and the
        daemon's answers - not a guess of ours - are what gets logged.  `live` is
        the one action with nothing to send, because the running display *is* the
        frame loop.

        A busy or missing port is reported in the log and the status bar, never
        as a modal dialog: the worker reports the holder's name anyway, and a
        popup would block the window - and a test - before the action ever ran.
        """
        if self.daemon.present:
            if kind == "live":
                why = ("a display is running, and it is what keeps the glass "
                       "updated. Change it with Apply / Pause / fps above, or "
                       "`systemctl --user stop xigmalcd` if you would rather "
                       "drive the port from this window")
                self._log(why)
                self.statusBar().showMessage(why)
                return
            if kind == "status":
                self.daemon.poll(report=True)
                return
            if kind == "frame":
                self.daemon.frame()
                return
            if kind == "upload":
                path = kw.get("path") or self.mp4
                self._queued_bg = os.path.basename(path)
                rep = self.daemon.upload(path)
                if rep.get("ok"):
                    # `ok` here only means the socket let it into the loop's one
                    # action slot.  The panel's verdict is a separate thing, and
                    # it is the display's own list that carries it.
                    self._log(f"asked the running display for {self._queued_bg}: "
                              f"queued for its frame loop, which is the only "
                              f"thing holding the port. Its list under 'The "
                              f"running display' says when it landed")
                self._refresh_clip_state()
                return
            if kind == "reset":
                # the daemon's gate, not ours: `recovery` over the socket needs
                # it to have been started with --allow-reset, and its reason is
                # more specific than anything we could write here
                self.daemon.reset()
                return
        why = port_busy(self.port)
        if why:
            self._log(why)
            self.statusBar().showMessage(why)
            return
        self.panel.queue(kind, **kw)

    def _do_reset(self) -> None:
        answer = QMessageBox.question(
            self, "Reset the panel?",
            "This sends the vendor's `recovery` frame.\n\n"
            "The panel returns to its default state and the USB device "
            "re-enumerates. It is not a firmware flash, but it does drop the "
            "stored picture.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.queue("reset", confirm=self.confirm.text())
            self.confirm.clear()

    def _busy(self, on: bool, kind: str) -> None:
        self.progress.setVisible(on)
        where = self.daemon.path if self.daemon.present else self.port
        self.statusBar().showMessage(f"{kind}: working on {where}" if on
                                     else self._owner_line())

    def _done(self, kind: str, ok: bool) -> None:
        if ok and kind == "upload" and self.daemon.present:
            # `ok` here came back off a unix socket in a few milliseconds, so it
            # cannot be the panel's answer: the frame loop owns the port and has
            # not touched the file yet.  Saying "upload: ok" over a socket is how
            # a queued-but-refused upload reads as a finished one, which is the
            # confusion this whole box exists to avoid.
            self._refresh_clip_state()
            self.statusBar().showMessage(
                "upload: queued for the display - its own line under 'The "
                "running display' says whether the panel took it")
            return
        self.statusBar().showMessage(f"{kind}: {'ok' if ok else 'failed'}")

    def _show_status(self, info: dict) -> None:
        flat = flatten(info)
        self.status.setText(describe(info) or "the panel answered, but with "
                                              "nothing we could read")
        self._log(f"status: {len(flat)} fields reported")

    def _owner_line(self) -> str:
        """Who holds the port, in the status bar's words."""
        if self.daemon.present:
            return f"display: {self.daemon.line()}"
        return (f"port {self.port} (no display running: this window visits the "
                f"port itself, one action at a time)")

    # ---- the running display --------------------------------------------
    def _set_display_widgets(self, on: bool) -> None:
        # `ed_apply_panel` belongs to this list, not to the editor's own enablement: the
        # editor's fields are useful with no display running (a file can be edited and saved
        # with nothing on the other end of the port), while a command that tells a display
        # what to draw has no recipient at all in that state.
        for w in (self.btn_pause, self.btn_dframe, self.btn_apply, self.d_fps,
                  self.ed_apply_panel):
            w.setEnabled(on)

    def _show_display(self, st: dict) -> None:
        """One poll's worth of the daemon's counters, on screen.

        Everything here is the daemon's own number, copied out of its status
        snapshot: the window has not touched the port and cannot know any of it
        otherwise (PROTOCOL.md §11, no readback)."""
        if not st:
            return
        self.display_box.setTitle(
            f"The running display (xigmalcd on {st.get('port') or self.port})")
        self._set_display_widgets(True)
        self.d_line.setText(wire.describe(st))
        dev = st.get("device") or {}
        self.d_counters.setText(
            f"{st.get('ok')}/{st.get('frames')} uploads the panel confirmed, "
            f"{st.get('refused')} refused, {st.get('errors')} link errors, "
            f"{st.get('renewals')} session renewals\n"
            f"this session {st.get('session_uploads')} uploads "
            f"{st.get('session_age', 0):.0f} s old; last file "
            f"{st.get('last_name') or '-'} {st.get('last_bytes') or 0} B, "
            f"notice {st.get('last_notice') or '-'}\n"
            f"uptime {st.get('uptime', 0):.0f} s, canvas {st.get('canvas')}, "
            f"clock {st.get('clock_size')}, text "
            f"{'not reported by this display' if 'text_color' not in st else (st.get('text_color') or 'theme default')}, "
            f"scrim "
            f"{'auto' if st.get('scrim') is None else st.get('scrim')}, fans "
            f"{'on' if st.get('fans') else 'off'}, pending "
            f"{st.get('pending') or '-'}, space={dev.get('space')}")
        self.d_events.setText(
            "what the display has done on the port, oldest first:\n"
            + "\n".join(st.get("events")
                        or ["   (nothing it has chosen to report since it "
                            "started)"]))
        self._read_ring(st.get("events") or [])
        self._sync_ink_control()
        # the panel-status box, too: over the socket there is no fresh `conn 1`,
        # but the display published the one it got at its session start, and a
        # labelled copy of that is worth more here than "not asked yet".
        if dev:
            self.status.setText(
                "the running display's own hello, from its session start - not "
                "a fresh read:\n"
                + "  " + "  ".join(f"{k}={dev[k]}" for k in sorted(dev)))
        self._syncing = True
        self.btn_pause.setChecked(bool(st.get("paused")))
        self._syncing = False
        # only if it actually moved: a 2 s timer yanking a spinbox the user is
        # dragging is how a status refresh turns into a fight with the window
        if st.get("fps") and abs(float(st["fps"]) - self.d_fps.value()) > 0.05:
            self.d_fps.setValue(float(st["fps"]))
        if not self.isActiveWindow():
            self.statusBar().showMessage(self._owner_line())
        self._tray_sync()

    def _sync_ink_control(self) -> None:
        """The text-colour row, enabled or explained away.

        Against a display too old to know the command, the row would offer a
        choice that cannot be sent - which is what the author's installed 0.2
        service and this window looked like: Apply came back `unknown cmd
        'text_color'` and the log read as though the settings had failed.  So the
        row goes inactive and says why, in the same breath naming the way to make
        it live.  The preview keeps the colour either way, because the window
        draws that picture itself: it is an honest preview of the frame that
        *would* go out, and it has never been a mirror of the glass (§11).
        """
        st = self.daemon.status or {}
        old_display = bool(self.daemon.present) and bool(st) and \
            "text_color" not in st
        self.ink_choice.setEnabled(not old_display)
        self.ink_choice.setToolTip(
            self._ink_tip + ("" if not old_display else
                             "\n\nINACTIVE: the display running here is older "
                             "than this window - its status reports no "
                             "text-colour field, so there is no such command to "
                             "send. Everything else in Apply still goes. Stop it "
                             "(`systemctl --user stop xigmalcd`) and run this "
                             "tree's `python3 -m xigmalcd`, or update the "
                             "package, and the choice becomes sendable"))

    def changeEvent(self, event) -> None:         # noqa: N802
        """Minimised is the other way a window draws nothing.

        Qt keeps reporting a minimised window as `isVisible()`, so `hideEvent` never
        runs for it: the decode stream and the two timers would go on producing a
        picture no one can see, with an ffmpeg holding the file open.  Same
        treatment, same reversal.
        """
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized():
                self.preview_timer.stop()
                self._close_player()
            elif self.isVisible():
                self.preview_timer.start(max(200, int(1000 / self.preview_fps)))
                self._set_player()

    def hideEvent(self, event) -> None:           # noqa: N802
        """A hidden window draws nothing, so it should decode and render nothing.

        Closing the decode stream here is the point: an ffmpeg holding an open
        file for a window that is in the tray is waste the user cannot see, and
        the preview timer at 2 fps is another thing ticking away behind it.  Both
        come back in `showEvent`, and the clip restarts at its beginning rather
        than resuming somewhere in the middle of a loop nobody watched.
        """
        self.preview_timer.stop()
        self._close_player()          # stops bg_timer with it: nothing to show
        super().hideEvent(event)

    def _display_changed(self, present: bool) -> None:
        self._sync_ink_control()
        if present:
            self._set_display_widgets(True)
            self.statusBar().showMessage(self._owner_line())
            return
        self.display_box.setTitle("The running display")
        self._set_display_widgets(False)
        self.d_line.setText("no display running: this window uses the port "
                            "itself, one short visit per action")
        self.d_counters.setText("start one with `python3 -m xigmalcd -f 1`, or "
                                "the login unit if you installed it, and this "
                                "window becomes a remote instead of a driver")
        self.d_events.setText("")
        self._refresh_clip_state()
        self.statusBar().showMessage(self._owner_line())

    def _toggle_pause(self, on: bool) -> None:
        """The button only.  A status refresh setting the same state back must
        not answer itself with a command."""
        if getattr(self, "_syncing", False) or not self.daemon.present:
            return
        self.daemon.pause() if on else self.daemon.resume()

    def _apply_to_display(self) -> None:
        """Send this window's pickers to the display that is running.

        Deliberate, like every other thing that reaches the glass: the preview
        follows a picker as you drag it, the panel only changes on this button,
        because there is no readback with which to undo a change (§11).  The
        scrim goes as the widget has it, so -1 stays `auto` and the daemon's own
        clip-luma rule stays the daemon's."""
        applied = self.daemon.apply({
            "theme": self.theme.currentText(),
            "clock_size": self.clock_size.value(),
            # hex or "" ("" = the theme's own skin), which is what the socket
            # and the settings file both use; the display answers with the hex it
            # kept, so the state line under the buttons shows the colour in force
            "text_color": self.ink_choice.currentData() or "",
            "canvas": "black" if self.canvas.currentIndex() else "clear",
            "scrim": self.scrim.value(),
            "fans": self.fanline.isChecked(),
            "fps": self.d_fps.value(),
        })
        # and what it deliberately left alone, said out loud.  A background is
        # not one of these settings - it is a file that overwrites what the
        # panel stores - so Apply never sends one, and on the bench that
        # distinction read as a broken picker: a clip selected in the list, Apply
        # pressed, and the glass going on drawing over the old picture.
        if applied:
            want = os.path.basename(self.mp4)
            if self._stored_bg and self._stored_bg != want:
                self._log(f"settings sent; the background did not go with them. "
                          f"The panel stores {self._stored_bg} and this window "
                          f"has {want} selected: the clips box sends it (Ctrl+Shift+U)")
            elif self._stored_bg == want:
                self._log(f"settings sent; the panel already stores {want}, so "
                          f"the layer under the frame stayed as it was")

    # ---- tray ------------------------------------------------------------
    def _build_tray(self) -> None:
        """The tray icon: what the display is doing, plus the four things worth
        reaching for without opening the window.

        Only when the desktop has a tray.  `isSystemTrayAvailable` is Qt asking
        the platform - KDE, GNOME with the extension, xfce do; a bare X session
        with no StatusNotifier host does not - and without one this stays the
        plain window it always was, which closes when you tell it to.
        """
        if not self.tray_wanted:
            self.tray = None
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            self._log("no tray on this desktop, so closing this window quits it. "
                      "Either way the glass keeps updating while a display is "
                      "running: those frames belong to xigmalcd")
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        menu = QMenu(self)
        self.tray_line = QAction("no display running", self)
        self.tray_line.setEnabled(False)      # the status line, not a button
        menu.addAction(self.tray_line)
        self.tray_pause = QAction("Pause the display", self)
        self.tray_pause.triggered.connect(self._tray_pause)
        menu.addAction(self.tray_pause)
        # `theme_sub`, not `themes`: the module of that name is what the rest of this class
        # reaches for, and a local QMenu called `themes` would answer instead of it
        # from here on.
        self.tray_theme_menu = theme_sub = menu.addMenu("Theme on the glass")
        for name in sorted(render.THEMES):
            act = QAction(name, self)
            act.triggered.connect(lambda _=False, n=name: self._tray_theme(n))
            theme_sub.addAction(act)
        menu.addSeparator()
        show = QAction("Show window", self)
        show.triggered.connect(self._show_from_tray)
        menu.addAction(show)
        self.tray_stay = QAction("Stay in the tray when closed", self)
        self.tray_stay.setCheckable(True)
        self.tray_stay.setChecked(self.tray_wanted)
        self.tray_stay.toggled.connect(self._tray_stay)
        menu.addAction(self.tray_stay)
        menu.addSeparator()
        bye = QAction("Quit this window", self)
        bye.triggered.connect(self._quit_window)
        menu.addAction(bye)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_click)
        self.tray.setToolTip(TITLE)
        self.tray.show()

    def _tray_pause(self) -> None:
        if not self.daemon.present:
            self._log("nothing to pause: no display is running")
            return
        (self.daemon.resume() if self.daemon.status.get("paused")
         else self.daemon.pause())

    def _tray_theme(self, name: str) -> None:
        """A menu pick says *on the glass*, so it goes to the display as well as
        to the preview - and when nothing is running, the log says the glass did
        not change rather than letting the preview imply that it did."""
        self.theme.setCurrentText(name)
        if self.daemon.present:
            self.daemon.send("theme", value=name)
        else:
            self._log(f"preview set to {name}: no display is running, so the "
                      f"glass still shows what it was last given")

    def _tray_click(self, reason) -> None:
        if reason not in (QSystemTrayIcon.ActivationReason.Trigger,
                          QSystemTrayIcon.ActivationReason.DoubleClick):
            return
        if self.isVisible() and not self.isMinimized():
            self.hide()                 # the same click, twice, is the usual idiom
        else:
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_stay(self, on: bool) -> None:
        self.tray_wanted = on
        self.save_timer.start()         # remembered: `tray` in the config file

    def _quit_window(self) -> None:
        """From the tray menu: close for real, timers and worker thread included."""
        self._quitting = True
        self.close()

    def _tray_sync(self) -> None:
        """Repaint the tray menu's status line and pause item from the daemon's status.

        The guard is the tray, not each widget: `tray_line` and `tray_pause` are built in
        the same block of `_build_tray` as the icon, so an icon with no menu is a state
        this program cannot be in - which is what a test fixture once forgot, and the
        AttributeError it produced went into stderr from a Qt slot and failed nothing.
        """
        if getattr(self, "tray", None) is None:
            return
        st = self.daemon.status
        self.tray.setToolTip(TITLE + " - " + (wire.describe(st) if st
                                              else "no display running"))
        self.tray_line.setText(
            f"{st.get('theme')} at {st.get('fps')} fps, "
            f"{st.get('ok')}/{st.get('frames')} confirmed"
            + (" (paused)" if st.get("paused") else "")
            if st else "no display running")
        self.tray_pause.setText("Resume the display" if st.get("paused")
                                else "Pause the display")
        self.tray_pause.setEnabled(bool(st))

    # ---- log -------------------------------------------------------------
    def _log(self, msg: str) -> None:
        line = time.strftime("%H:%M:%S") + "  " + str(msg).strip()
        self._log_lines.append(line)
        if len(self._log_lines) > LOG_KEEP:
            del self._log_lines[:-LOG_KEEP]
        self.log_view.setText("\n".join(self._log_lines))
        bar = self.log_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())         # keep the newest line in view

    def showEvent(self, event) -> None:                    # noqa: N802
        super().showEvent(event)
        if hasattr(self, "thumb_timer") and getattr(self, "_pending", None):
            self.thumb_timer.start(0)      # the ffmpeg pass carries on from here
        # the other half of what `hideEvent` stopped: the preview's redraw timer,
        # and the decode stream behind it, which starts again at the top of the
        # clip rather than in the middle of a loop nobody watched
        if hasattr(self, "preview_timer"):
            self.preview_timer.start(max(200, int(1000 / self.preview_fps)))
        self._set_player()
        self.statusBar().showMessage(self._owner_line())

    def closeEvent(self, event) -> None:                 # noqa: N802
        if self.tray is not None and self.tray_wanted and not self._quitting:
            # hide rather than quit, and the reason that is safe is the ownership
            # split: the frames on the glass are the daemon's, not this window's
            event.ignore()
            if hasattr(self, "thumb_timer") and getattr(self, "_pending", None):
                # 115 ffmpeg seeks are not worth spending on a hidden window
                self.thumb_timer.stop()
            self.hide()
            self._log("hidden to the tray: the display keeps drawing, because "
                      "those frames belong to xigmalcd. Click the tray icon to "
                      "come back, or Quit from its menu; --no-tray turns this "
                      "off")
            return
        self.preview_timer.stop()
        self.daemon_timer.stop()
        if hasattr(self, "thumb_timer"):
            self.thumb_timer.stop()     # only created once clips were found
        # an ffmpeg left streaming a clip for a preview nobody will see again is a
        # child process outliving its reason.  `hideEvent` covers the tray path;
        # this is the way out.
        self._close_player()
        self.save_timer.stop()
        self._save_now()        # the way it looks now is the way it starts next
        self.panel.stop()
        if getattr(self, "tray", None) is not None:
            self.tray.hide()          # an icon that outlives its window is a lie
        super().closeEvent(event)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="xigmaui", description="Qt front end for the Xigmatek panel: "
        "preview, theme and background picker, status, reset.")
    ap.add_argument("--device", default=None,
                    help="serial port to use (default: the saved one)")
    ap.add_argument("--preview-fps", type=float, default=None,
                    help="preview refresh rate, host side only; the panel is not "
                    "involved (default: the saved one, ~9 ms per frame to draw)")
    ap.add_argument("--fresh", action="store_true",
                    help=f"ignore and overwrite {settings.path()}: start at the "
                         f"defaults")
    ap.add_argument("--socket", default="",
                    help="control socket of a running display. Default is where "
                         "xigmalcd puts it ($XIGMA_SOCKET, then "
                         "$XDG_RUNTIME_DIR/xigmalcd.sock). If something answers "
                         "there, this window drives it and never opens the "
                         "serial port, which is the only way both can run")
    ap.add_argument("--tray", dest="tray", action="store_true", default=None,
                    help="ask for a tray icon even if the saved setting says no")
    ap.add_argument("--no-tray", dest="tray", action="store_false",
                    help="no tray icon: closing the window quits, and the saved "
                         "setting is ignored")
    ap.add_argument("--hidden", action="store_true",
                    help="start in the tray with no window: what you want if the "
                         "window is a control panel you keep out of the way "
                         "while the display runs")
    a = ap.parse_args(argv)

    app = QApplication(sys.argv[:1])
    # argv[0] is whatever python3 was called as, so without this the window's
    # class is "python3": the taskbar would show it under Python and the
    # launcher's StartupWMClass would never match it (the .desktop entry sets
    # StartupWMClass=xigmaui, and on Wayland the app_id comes from this)
    app.setApplicationName(settings.APP)
    app.setDesktopFileName(settings.APP)      # icon + app_id for the shell
    icon = app_icon()
    if not icon.isNull():
        # theme name when the box has one (the .deb's hicolor copy), the file when
        # it does not; see app_icon().  The picture is a rendering of the glass,
        # which is the one thing worth showing in the taskbar and in the tray, where
        # it is the only way to find us
        app.setWindowIcon(icon)
    win = Window(a.device, a.preview_fps, restore=not a.fresh,
                 socket=a.socket, tray=a.tray,
                 save_settings=True)      # `--fresh` says "ignore and overwrite"
    if a.hidden and win.tray is not None:
        # no window, tray only: everything the tray menu can do goes over the
        # control socket, so this works with the display running and without it
        win._log("started in the tray: click the icon for the window, or use "
                 "its menu to pause the display and pick a theme")
    else:
        if a.hidden:
            print("no tray on this desktop: showing the window instead",
                  file=sys.stderr)
        win.show()
    return app.exec()
