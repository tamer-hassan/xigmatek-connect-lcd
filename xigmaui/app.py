"""app.py - the main window: preview, theme pick, background pick, status, reset.

Layout follows what this panel actually supports rather than what the vendor's
window looks like:

    +----------------+-----------+------------+  the running display: its counters,
    | preview        | theme     | clip list  |  and the last things it did on the
    | (480x480,      | + clock   | (filter,   |  port; the theme and its pickers;
    |  our           | + canvas  |  rows,     |  the library of backgrounds and the
    |  composite,    | + advanced|  state)    |  panel's own hello; and, under the
    |  not a mirror  | + reset   |            |  picture, the log
    |  of the glass) |           |            |
    +----------------+-----------+------------+

Three columns, not one long scroll: the clip library wants *height* (40 rows on this
box, 115 with the Windows partition mounted) and it was sharing a single column with
four other boxes, which measured out as a 190 px viewport showing two clips at a time
on a 1 919 px window.  Two rules decide the rest, and both come from measurements:
the frame we draw is exactly 480x480 and `_fit()` never scales it up (showing pixels
the glass does not have would be a lie), so a preview column wider than 480 px is
dead space; and a clip row follows its icon, so the thumbnails are 64 px, not the
112 px that made every row 114 px tall.

The `advanced controls` switch folds away the seven secondary things (canvas, scrim,
fan figures, the display's event log, the panel's `conn 1` hello, the 30 second
frame run, the layout editor).  It is pixels only, never values: what is hidden keeps
its setting and `Apply` sends it.  The guarded factory reset stays on screen whatever
the switch says, because a recovery that is hard to find is worse than one that is in
the way.

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
from PIL import Image                                            # noqa: E402
from PyQt6.QtCore import QEvent, QSize, Qt, QTimer        # noqa: E402
from PyQt6.QtGui import (QAction, QBrush, QColor, QIcon, QImage,
                         QKeySequence, QPixmap)                    # noqa: E402
from PyQt6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox,
                             QDoubleSpinBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                             QProgressBar, QPushButton, QScrollArea,
                             QSizePolicy, QSpinBox, QSplitter, QStackedWidget,
                             QSystemTrayIcon,
                             QVBoxLayout, QWidget)

from xigmalcd import control as wire                              # noqa: E402
from xigmalcd import protocol, render, sensors, themes       # noqa: E402
from xigmalcd.main import (BRIGHT_LUMA, CLIP_LUMA, DEFAULT_MP4,   # noqa: E402
                           SCRIM_ON_BRIGHT)
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
# debian/xigmaui.desktop).  One string, four places that show it; the suite's
# packaging-parity section reads this constant back against both files, so the entry a
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

#: The menu entry that means "this key is not in the file at all", for the one kind of
#: field whose absence is a value: this program's own `xigma` extension keys.  It is a
#: label and a sentinel in one, because the row both shows what the file says and is how
#: a reader un-says it - and because picking the first real choice instead would be a lie
#: (`no arcPaint` is the vendor's ring convention, not "render").
UNSET = "(not set)"

#: The layout combo's first entry: "close the editor".  A constant rather than a string
#: in two places, because the row's behaviour keys off it and a gate asserts it by name.
NO_EDITOR = "(nobody: preview the theme above)"

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


class Window(QMainWindow):
    """The main window.

    Both columns sit in scroll areas: on a laptop-height screen the right column
    (theme, clips, status, reset, log) is taller than the window, and a layout
    that cannot scroll simply draws its children over each other - which is what
    the first version did, the clock of the preview landing on the status box.
    """

    def __init__(self, port: str | None = None, preview_fps: float | None = None,
                 restore: bool = True, socket: str = "", tray: bool | None = None):
        """`port` and `preview_fps` passed in win over what was saved: they come
        from the command line, and a command line that says `/dev/ttyACM1`
        should not be overruled by a file. `restore=False` starts from the
        defaults (`--fresh`), which is also what the offline checks use.

        `socket` says where to look for a running display (default: the same
        place `xigmalcd` puts it), and `tray` overrides whether closing the
        window hides it instead of quitting (`--tray` / `--no-tray`)."""
        super().__init__()
        self.cfg = settings.load() if restore else settings._clean({})
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
        self.resize(*self.cfg["size"])       # as you left it
        # ...and only now the two columns: a splitter that has never been laid
        # out treats setSizes as a wish, and the second half of the window is
        # what loses.  Verified offscreen: setting it inside _build left the
        # controls 116 px wide at a 2 259 px window.
        self.split.setSizes(self.cfg["split"])
        self._build_tray()
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._repaint)
        self.preview_timer.start(max(200, int(1000 / self.preview_fps)))
        self._load_background(self.mp4)
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
        self.preview = QLabel()
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
            "display's event log, the panel's own `conn 1` hello, the 30 second "
            "frame run, and the layout editor. Hiding them does not change them: "
            "what is not shown is still what is set, and Apply sends it either way")
        self.adv_toggle.setChecked(bool(self.cfg.get("advanced")))
        self.adv_toggle.toggled.connect(self._set_advanced)
        self.anim_toggle.toggled.connect(self._set_animate)
        head.addWidget(self.adv_toggle)
        self.adv_note = QLabel("canvas, scrim, fans, the event log, panel hello, the "
                               "30 s run, the layout editor")
        self.adv_note.setStyleSheet("color:#888;font-style:italic;")
        self.adv_note.setWordWrap(True)
        head.addWidget(self.adv_note, 1)
        col.addLayout(head)
        # what the toggle covers, filled in as the boxes are built: pairs of
        # (form label, field) for the QFormLayout rows, and whole widgets for
        # everything else.  A form row whose field is hidden and whose label is
        # not is a gap with a word in it, so both go.
        self._adv_hide: list = []
        # whole boxes the switch folds, parked here until the controls column is
        # finished: they belong at its foot, in the slack that column has and the
        # library column does not
        self._adv_boxes: list = []
        # A third column, used when the window is wide: the clip library wants
        # *height* (40 distinct clips here, out of 161 files in the roots) and at
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
        self._set_display_widgets(False)
        col.addWidget(live)

        theme = QGroupBox("Theme on the glass")
        form = QFormLayout(theme)

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
        self.theme.currentTextChanged.connect(self._changed)
        self.theme.setToolTip(
            "the drawings `xigmalcd` renders itself, from live sensor readings. "
            "The vendor's layouts are not in this list on purpose: this combo picks "
            "what the *loop* draws from this machine's readings, and the five are what "
            "`render.py` draws from them. The daemon does draw 23 of the library "
            "layouts - `xigmalcd --theme Theme_07`, and `--list-themes` prints the set "
            "with the four refused on canvas - and the layout editor below previews "
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
        # one line shorter than it was, on purpose: this note is the reason the
        # controls column at the fresh 1180x780 default needed 742 of its 744 px,
        # and a column that scrolls by a hand's width because of a footnote is a
        # bad trade.  The full explanation is the combo's tooltip (set just above)
        # and docs/themes.md, which is what the parenthetical points to.
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
        self.canvas.setItemData(1, "opaque black frame: covers the stored "
                                   "background completely (`--bg black`)",
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
        # It folds away with the advanced switch - one group box, one entry in
        # `_adv_hide`.  A first run does not need a layout editor, and this column
        # measured 742 of its 744 px at the fresh 1180x780 default before it arrived.
        editor = QGroupBox("Layout: edit a file the loop can draw")
        eform = QFormLayout(editor)
        self.ed_name = QComboBox()
        # `themes.scan()` is already user-first, so a name that has been edited appears
        # once and opens the copy: reopening continues rather than starting over.  The
        # first entry gives the pane back to the live theme preview.
        self.ed_name.addItem(NO_EDITOR)
        self.ed_name.addItems(sorted(themes.EXPORTS))
        self.ed_name.addItems([r["name"] for r in themes.scan()[0]])
        self.ed_name.setToolTip(
            "the three generated layouts (`clock`, `dual`, `gauge`: JSON written out of "
            "`render.py` on demand, also printed by `--export-theme NAME`) and every "
            "layout file this canvas can select - 23 of the vendor's 27 today, the other "
            "four are 4:3 and refused on a 480x480 panel (docs/themes.md). A name you "
            "have already edited opens your copy. No layout file is ever sent to the "
            "panel and nothing is read back from it (PROTOCOL.md \u00a711): what a save "
            "changes is what *this machine's* daemon draws next time it names that theme")
        self.ed_name.currentTextChanged.connect(self._editor_open)
        self.ed_state = QLabel("not editing: the pane shows the theme above, drawn from "
                               "this machine's readings")
        self.ed_state.setStyleSheet("color:#888;font-style:italic;")
        self.ed_state.setWordWrap(True)
        eform.addRow("layout", self.ed_name)
        eform.addRow("", self.ed_state)

        self.ed_widget = QComboBox()
        self.ed_widget.setToolTip("one widget of this layout: its kind, what it shows, "
                                  "and where it sits")
        self.ed_widget.currentIndexChanged.connect(self._editor_pick_widget)
        eform.addRow("widget", self.ed_widget)

        self.ed_field = QComboBox()
        self.ed_field.setToolTip(
            "a key the painter actually reads. This list comes out of the code rather "
            "than a table kept here: `themes.keys_read()` parses `layout.py`, and the "
            "keys the vendor's files carry that nothing reads - which "
            "`--print-theme-fields` prints with the reason each is inert - are not "
            "offered")
        self.ed_field.currentTextChanged.connect(self._editor_pick_field)
        eform.addRow("field", self.ed_field)

        # One page per kind of value, because a free-text box for `bold` or a menu for a
        # coordinate is a way of typing something the model can only refuse.  The menus
        # are the vocabulary that already exists in code: families in `layout.FONTS`,
        # metric names in the source table, drawings in `themes.SPECIALS`, painter
        # conventions in `layout.ARC_PAINT`/`BAR_PAINT`, named ramps in
        # `layout.COLOUR_RAMPS`.
        self.ed_stack = QStackedWidget()
        self.ed_num = QSpinBox()
        # Deliberately wider than any legal value. A spinbox that clamps 999 down to 479
        # is a widget editing the file on its own; this repo's rule is that an
        # out-of-range value is *said*, so the spinbox holds it, the model refuses it,
        # and the note under this row prints the refusal.
        self.ed_num.setRange(-100000, 100000)
        self.ed_num.valueChanged.connect(lambda *_a: self._editor_apply(False))
        self.ed_num.editingFinished.connect(lambda: self._editor_apply(True))
        self.ed_menu = QComboBox()
        self.ed_menu.currentIndexChanged.connect(lambda _i: self._editor_apply(True))
        self.ed_text = QLineEdit()
        self.ed_text.textEdited.connect(lambda *_a: self._editor_apply(False))
        self.ed_text.editingFinished.connect(lambda: self._editor_apply(True))
        self.ed_bool = QCheckBox("bold")
        self.ed_bool.toggled.connect(lambda _b: self._editor_apply(True))
        for page in (self.ed_num, self.ed_menu, self.ed_text, self.ed_bool):
            self.ed_stack.addWidget(page)
        eform.addRow("value", self.ed_stack)

        brow = QHBoxLayout()
        self.ed_undo = QPushButton("undo")
        self.ed_undo.setToolTip("back one edit. A run of keystrokes in the value box is "
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
        eform.addRow("", brow)

        self.ed_note = QLabel()
        self.ed_note.setWordWrap(True)
        self.ed_note.setStyleSheet("color:#999;font-style:italic;")
        eform.addRow("", self.ed_note)
        self.ed_group = editor                   # the suite's gate names it from outside
        self._adv_hide.append(editor)
        col.addWidget(editor)
        self.ed = None                        # nothing open until a name is picked
        self._ed_notes = {}                   # what the last editor frame reported
        # nothing to edit until a layout is open: a row that offers fields before there
        # is a file behind it is a row that will write to nothing
        for wid in (self.ed_widget, self.ed_field, self.ed_stack, self.ed_undo,
                    self.ed_save, self.ed_revert):
            wid.setEnabled(False)

        media = QGroupBox("Background: the layer under our frame")
        mlay = QVBoxLayout(media)
        # the library is 40 rows on this box - 161 files, 121 of them copies
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
        # controls column, not library: `conn 1` answers with fourteen fields and
        # they wrap to about ten lines in a 300 px column, which is height taken
        # straight off the clip list.  The controls column has the slack instead
        # (measured: ~450 px of it empty at 1 919x1 055), and this box is behind
        # the advanced switch anyway, where it cannot push the reset box away.
        self._adv_boxes.append(status)
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
        col.addWidget(danger)
        for _b in self._adv_boxes:
            col.addWidget(_b)
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
        # the switch's initial position: setChecked() above ran before the
        # `toggled` connect, so the folding has to be applied here as well
        self._set_advanced(self.adv_toggle.isChecked())

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

    def _repaint(self) -> None:
        """Redraw **our layer** from fresh readings, then show it.

        This is the expensive half, and it is deliberately the only half tied to
        `--preview-fps`: `sensors.collect()` is 71.8 ms and `render.draw` another
        11.9 ms measured here, so a tick of this costs ~84 ms.  The background does
        not move at this rate and never should have: it plays on `bg_timer`, at the
        file's own rate, compositing over the layer cached here (`self._osd`).
        Before that split the pane's redraw rate *was* the animation rate, and a
        24 fps clip at the default 2 fps - or the author's own saved 1 fps - was a
        slideshow, which is what "it stutters at about 1 fps" meant.
        """
        m = sensors.collect()
        self._last = m
        theme = self.theme.currentText()
        if self.ed is not None:
            # The pane shows *the file being edited*, drawn by `themes.draw` - the same
            # door `--check-theme` uses and the frame loop uses for a layout theme - at
            # the pinned fixture.  Not a detail: a preview that moved with this
            # machine's readings would make it impossible to tell an edit from a
            # temperature, and the whole claim of the editor is that a field change is
            # the only thing that can move a pixel.
            img, self._ed_notes = self.ed.paint(*self.ed.fixture())
        else:
            img = render.draw(m, theme, **self._render_kw())
        self._osd = img
        self._seq += 1
        self.metrics.setText(
            ("pane: pinned fixture  |  this machine: " if self.ed is not None else "")
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
            # different things.  `themes.draw` is the door `--check-theme` uses and the
            # frame loop uses for a layout theme, so the pane and the glass can only
            # disagree about the readings, and those are pinned on purpose.
            miss = ", ".join(sorted(set((self._ed_notes or {}).get("missing") or [])))
            self.caption.setText(
                f"Layout `{self.ed.name}` ({self.ed.origin}), drawn through "
                "`themes.draw` - the door `--check-theme` uses, and the frame loop uses "
                "for a layout theme. The readings are the editor's pinned fixture, not "
                "this machine's, so an edit is the only thing that can move a pixel "
                "here."
                + (f" No reading for: {miss}." if miss else "")
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
        # back with a 343 px frame (the suite caught it as QSize(343, 343)).
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
                "animate": self.anim_toggle.isChecked(),
                "advanced": self.adv_toggle.isChecked(),
                "size": [self.width(), self.height()],
                # the split as it stands, not as it was saved: the splitter's
                # own handle position is the thing the user moved, and the left
                # pane's cap in _build() is what keeps the preview honest
                "split": list(self.split.sizes()) if hasattr(self, "split")
                        else self.cfg["split"]}

    def _save_now(self) -> str | None:
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
        Measured on this bench, where the Windows partition is mounted: **161 mp4
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
        self.clips.setCurrentRow(first)
        self._pending = list(range(len(self.all_clips)))
        # the row you selected first, then whatever is on screen, then the rest
        self._pending.remove(first)
        self._pending.insert(0, first)
        self.thumb_timer = QTimer(self)
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
        """
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
        box stays on screen whatever the switch says: a guarded recovery that is
        hard to find is worse than one that is merely in the way.
        """
        for w in self._adv_hide:
            w.setVisible(bool(on))
        self.adv_note.setText(
            "canvas, scrim, fans, the event log, panel hello, the 30 s run, the "
            "layout editor"
            if not on else "shown, and they keep their values either way")
        self.save_timer.start()

    # ---- the layout editor --------------------------------------------------
    # Every claim in this group belongs to `xigmaui/edit.py`, which holds no Qt and is
    # gated in tools/selftest.sh without a display: what an edit moves, what undo owes
    # back, when a file is written.  The window's job is narrow - offer the fields the
    # painter reads, show the picture that comes out of them, and never write a file
    # nobody asked for.
    def _editor_open(self, name: str) -> None:
        """Open one layout in the editor.  Reads a file; writes nothing.

        The combo's first entry closes the editor and gives the pane back to the live
        theme preview, which is the difference a reader needs to see: an open layout is
        a picture of *the file*, drawn from a pinned fixture, not of what this machine's
        sensors are putting on the glass right now.
        """
        if not name or name == NO_EDITOR:
            self.ed = None
            for wid in (self.ed_widget, self.ed_field, self.ed_stack, self.ed_undo,
                        self.ed_save, self.ed_revert):
                wid.setEnabled(False)
            self.ed_state.setText("not editing: the pane below shows the theme above, "
                                  "drawn from this machine's readings")
            self.ed_note.setText("")
            self._repaint()
            return
        try:
            self.ed = edit.Editor.open_theme(name)
        except (KeyError, ValueError) as exc:
            # `themes.why_not`'s own sentence: a name that is not a layout, or a file
            # that will not parse.  Nothing here guesses at a repair.
            self.ed = None
            self.ed_state.setText("not editing")
            self.ed_note.setText(str(exc))
            self._repaint()
            return
        for wid in (self.ed_widget, self.ed_field, self.ed_stack, self.ed_save,
                    self.ed_revert):
            wid.setEnabled(True)
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
        self.ed_widget.setCurrentIndex(0)
        self._editor_pick_widget(0)
        self._repaint()

    def _editor_state(self) -> None:
        """One line: where this layout came from, and whether a file holds it now."""
        if self.ed is None:
            return
        where = {"generated from render.py":
                 "generated from `render.py`: there is no file, and saving one is "
                 "refused, because a `gauge.json` would be a second `theme_gauge`",
                 "checkout": "the vendor's file in this checkout",
                 "package": "the installed themes package",
                 "your copy": "your copy under ~/.config/xigmalcd/themes"}.get(
                     self.ed.origin, self.ed.origin)
        copies = themes.user_copies()
        state = "edit not saved yet" if self.ed.dirty else "nothing outstanding"
        self.ed_state.setText(f"{where}; {state}")
        self.ed_save.setEnabled(self.ed.dirty)
        self.ed_revert.setEnabled(self.ed.name in copies)
        self.ed_undo.setEnabled(self.ed.steps > 0)
        self.ed_undo.setText(f"undo ({self.ed.steps})" if self.ed.steps else "undo")

    def _editor_pick_widget(self, index: int) -> None:
        """Select one widget and rebuild the field list for its kind."""
        if self.ed is None or int(index) < 0:
            return
        self.ed.select(int(index))
        self.ed_widget.setToolTip(self.ed.tip(int(index)))
        kind = str(self.ed.selected().get("type") or "")
        fields = list(edit.field_names(kind)) + list(edit.extension_fields(kind))
        self.ed_field.blockSignals(True)
        self.ed_field.clear()
        self.ed_field.addItems(fields)
        self.ed_field.blockSignals(False)
        if fields:
            self.ed_field.setCurrentIndex(0)
            self._editor_pick_field(fields[0])
        self._editor_state()

    def _editor_pick_field(self, field: str) -> None:
        """Show the right editor for one field, holding its current value.

        A menu wherever the vocabulary already exists in code, a checkbox for a bool, a
        spinbox for a number, and a text box only for what is genuinely free text - a
        colour, a format, a line of content.  That split is `edit.choices()` and
        `edit.number_fields()`, not a guess made here.
        """
        if self.ed is None:
            return
        value = self.ed.value(field)
        opts = edit.choices(field)
        spelled = [str(o) for o in opts]
        if field == "bold":
            page = self.ed_bool
            self.ed_bool.blockSignals(True)
            self.ed_bool.setChecked(bool(value))
            self.ed_bool.blockSignals(False)
        elif opts:
            page = self.ed_menu
            self.ed_menu.blockSignals(True)
            self.ed_menu.clear()
            # An extension key that is absent has no value to select, and showing the
            # first choice as though it were would be the one lie this row could tell:
            # `arcPaint` missing means the vendor's ring, not "render".  So the row says
            # it is missing, and choosing that entry is how a reader un-sets a key.
            ext = field in edit.extension_fields(
                str(self.ed.selected().get("type") or ""))
            items = list(spelled)
            if value is None and ext:
                items.insert(0, UNSET)
            elif str(value) not in items:
                items.insert(0, str(value))   # a value the vocabulary does not name
            self.ed_menu.addItems(items)
            self.ed_menu.setCurrentText(items[0])
            self.ed_menu.blockSignals(False)
        elif field in edit.number_fields():
            page = self.ed_num
            self.ed_num.blockSignals(True)
            try:
                self.ed_num.setValue(int(value))
            except (TypeError, ValueError):
                self.ed_num.setValue(0)      # a missing key: the drawer's own default
            self.ed_num.blockSignals(False)
        else:
            page = self.ed_text
            self.ed_text.blockSignals(True)
            self.ed_text.setText("" if value is None else str(value))
            self.ed_text.blockSignals(False)
        self.ed_stack.setCurrentWidget(page)
        # an extension key gets the reason it exists next to the field, because that is
        # the one thing a reader cannot infer from the value: `no arcPaint` is not
        # "unset", it is the vendor's ring
        why = themes.XIGMA_KEYS.get(field)
        self.ed_note.setText(f"xigma.{field}: {why}" if why else "")

    def _editor_value(self):
        """What the on-screen editor currently holds for the selected field."""
        page = self.ed_stack.currentWidget()
        if page is self.ed_bool:
            return self.ed_bool.isChecked()
        if page is self.ed_menu:
            return (None if self.ed_menu.currentText() == UNSET
                    else self.ed_menu.currentText())
        if page is self.ed_num:
            return self.ed_num.value()
        return self.ed_text.text()

    def _editor_apply(self, commit: bool) -> None:
        """Hand one value to the model, and print in words what it did.

        `commit=False` is a keystroke: the picture moves and the undo step waits, so a
        run of typing is one undo (the coalescing `edit.Editor.set` implements).  A
        refusal repaints nothing - the layout, the dirty flag and the history stay as
        they were, which is the part an editor most often gets wrong.
        """
        if self.ed is None:
            return
        field = self.ed_field.currentText()
        if not field:
            return
        ok, note = self.ed.set(field, self._editor_value(), commit=commit)
        if note:
            self.ed_note.setText(note)
        if ok:
            self._repaint()
        self._editor_state()

    def _editor_undo(self) -> None:
        if self.ed is None:
            return
        if self.ed.undo():
            self.ed_note.setText(f"back one step: {self.ed.steps} left in the history")
            self._editor_pick_field(self.ed_field.currentText())
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
        self.ed_note.setText("your copy is gone: the loop reads the vendor's file "
                             "again. What you typed is still here, unsaved.")
        self._editor_state()
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
        # promise something the socket would refuse).  A clip the gate refuses is
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
                    # `ok` here only means the gate let it into the loop's one
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
        for w in (self.btn_pause, self.btn_dframe, self.btn_apply, self.d_fps):
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
        themes = menu.addMenu("Theme on the glass")
        for name in sorted(render.THEMES):
            act = QAction(name, self)
            act.triggered.connect(lambda _=False, n=name: self._tray_theme(n))
            themes.addAction(act)
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
                 socket=a.socket, tray=a.tray)
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
