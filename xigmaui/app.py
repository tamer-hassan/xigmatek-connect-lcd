"""app.py - the main window: preview, theme pick, background pick, status, reset.

Layout follows what this panel actually supports rather than what the vendor's
window looks like:

    +----------------+-----------+  the running display: its counters, and
    | preview        | theme +   |  the last things it did on the port
    | (480x480,      | clock +   |  background clip list, with measured luma
    |  our           | canvas    |  status from the panel
    |  composite,    | pickers   |  log pane
    |  not a mirror  | buttons   |  guarded reset
    |  of the glass) |           |
    +----------------+-----------+

Two rules decide those proportions, and both come from measurements rather than
taste.  The frame we draw is exactly 480x480 and `_fit()` never scales it up
(showing pixels the glass does not have would be a lie), so a preview column
wider than 480 px is dead space: it gets a maximum width and the controls get
the rest.  And both columns sit in scroll areas, because on a laptop-height
screen the right column is taller than the window.

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
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                             QDoubleSpinBox, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                             QProgressBar, QPushButton, QScrollArea,
                             QSizePolicy, QSpinBox, QSplitter, QSystemTrayIcon,
                             QVBoxLayout, QWidget)

from xigmalcd import control as wire                              # noqa: E402
from xigmalcd import protocol, render, sensors                   # noqa: E402
from xigmalcd.main import (BRIGHT_LUMA, CLIP_LUMA, DEFAULT_MP4,   # noqa: E402
                           SCRIM_ON_BRIGHT)
from . import clips as clipdb
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

#: How much of the window's own log is kept on screen, in lines.  Not taste: the
#: log is one wrapped QLabel, so every new line re-sets the whole text, and a
#: window left open over a long session would otherwise spend its afternoon
#: redrawing 40 000 lines of heartbeat.  The newest 200 is what anyone reads
#: back; the display's journal (`journalctl --user -u xigmalcd -f`, docs/usage.md)
#: is where the full record of a run lives.
LOG_KEEP = 200


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
        lay.addWidget(self.preview, 1)      # stretch: the frame keeps its square
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
        self._set_display_widgets(False)
        col.addWidget(live)

        theme = QGroupBox("Theme on the glass")
        form = QFormLayout(theme)
        self.theme = QComboBox()
        self.theme.addItems(sorted(render.THEMES))
        self.theme.setCurrentText(self.cfg["theme"])
        self.theme.currentTextChanged.connect(self._changed)
        self.theme.setToolTip(
            "the drawings `xigmalcd` renders itself, from live sensor readings. "
            "The vendor's 27 themes are not among them, and this list is not "
            "missing them: those are files for the panel's own firmware and "
            "nothing here sends or interprets them. docs/themes.md says what the "
            "library is used for (its layouts are what `alpha` was measured "
            "against) and what its clips can be used as (a background)")
        form.addRow("theme", self.theme)
        # the question this combo provokes, answered where it is asked: the
        # `xigmatek-connect-lcd-themes` package is on the machine, so why is not
        # its 27 themes in the list?  Because that package's contents are the
        # vendor's own files - .thm themes, layouts, baked overlays, clips - and
        # this project has measured one use for them: as background media.  It
        # has never sent a .thm, and it cannot draw one.
        vendor = QLabel(
            "the five names are what this program draws. The vendor's 27 themes "
            "are its own files for the panel's firmware: nothing here can draw "
            "one, and nothing here has ever sent one. What the themes package "
            "does give this window is its clips and images, in the list below "
            "(docs/themes.md)")
        vendor.setWordWrap(True)
        vendor.setStyleSheet("color:#888;font-style:italic;")
        form.addRow("", vendor)
        self.clock_size = QSpinBox()
        self.clock_size.setRange(16, 96)
        self.clock_size.setValue(self.cfg["clock_size"])
        self.clock_size.valueChanged.connect(self._changed)
        form.addRow("clock size", self.clock_size)
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
        form.addRow("canvas", self.canvas)
        self.scrim = QSpinBox()
        self.scrim.setRange(-1, 255)
        self.scrim.setValue(self.cfg["scrim"])
        self.scrim.setSpecialValueText("auto")
        self.scrim.setToolTip("0 needs no plate, 255 a solid one. `auto` uses the "
                              "daemon's rule: a plate only when the clip's mean "
                              "luma is over "
                              f"{BRIGHT_LUMA}/255, at {SCRIM_ON_BRIGHT}.")
        self.scrim.valueChanged.connect(self._changed)
        form.addRow("scrim", self.scrim)
        self.fanline = QCheckBox("fan figures")
        self.fanline.setToolTip("draws `CPU FAN nnnn RPM` under the CPU "
                                "temperature and `GPU FAN nn%` under the GPU "
                                "one, and leaves the `fans` array out of the "
                                "metrics blob - the panel never reports its own "
                                "tachs back, so turning this off only removes "
                                "the drawing and the data we send")
        self.fanline.setChecked(self.cfg["fans"])
        self.fanline.stateChanged.connect(self._changed)
        form.addRow("fans", self.fanline)
        col.addWidget(theme)

        media = QGroupBox("Background: the layer under our frame")
        mlay = QVBoxLayout(media)
        # the library is 69 rows on this box and 115 with the Windows partition
        # mounted, and the row you want is a scroll wheel and a search away:
        # one filter field, matching what a row already shows (name, size, loop
        # length, where it came from), so finding a clip does not need a terminal
        self.clip_filter = QLineEdit()
        self.clip_filter.setPlaceholderText("filter: name, size, length or origin")
        self.clip_filter.setClearButtonEnabled(True)
        self.clip_filter.textChanged.connect(self._filter_clips)
        mlay.addWidget(self.clip_filter)
        self.clips = QListWidget()
        self.clips.setIconSize(QSize(112, 112))
        # elide rather than scroll: a horizontal bar inside a column that also
        # scrolls vertically is very hard to use
        self.clips.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.clips.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.clips.currentItemChanged.connect(self._clip_chosen)
        mlay.addWidget(self.clips)
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
        col.addWidget(media)

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
        slay.addLayout(rrow)
        col.addWidget(status)

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
        col.addWidget(slog)

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
        controls.setMinimumWidth(320)
        split.addWidget(pane)
        split.addWidget(controls)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)
        split.setStretchFactor(1, 1)
        split.setSizes(self.cfg["split"])
        split.splitterMoved.connect(lambda *_a: self.save_timer.start())
        self.split = split
        self.setCentralWidget(split)
        # order matters here: the list has to exist before the send-state line
        # can say which row, if any, the display reports is on the panel
        self.statusBar().showMessage(f"port {self.port}")
        self._populate_clips()
        self._refresh_clip_state()

    # ---- preview ---------------------------------------------------------
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
              "fan": self.fanline.isChecked(), "source": "temperature"}
        # themes take different options, exactly as `main._theme_kwargs` finds
        # out by reading the signature rather than keeping a table of them.
        # `scrim` stays outside that filter: `draw` takes it, not the theme.
        params = inspect.signature(render.THEMES[theme]).parameters
        return {k: v for k, v in kw.items() if k in params} | {"scrim": want}

    def _repaint(self) -> None:
        m = sensors.collect()
        self._last = m
        theme = self.theme.currentText()
        img = render.draw(m, theme, **self._render_kw())
        self._seq += 1
        self.metrics.setText(
            f"cpu {(m.get('cpu') or {}).get('temperature')}°C  "
            f"load {(m.get('cpu') or {}).get('load')}%  "
            f"gpu {(m.get('gpu') or {}).get('temperature')}°C  "
            f"gpu fan {(m.get('gpu') or {}).get('fan')}%  "
            + "  ".join(f"{f['name']} {f['value']}" for f in m.get("fans") or [])
            + f"   frame #{self._seq} ({render.frame_name()})")
        comp = img
        if self.bg_frame is not None and self.canvas.currentIndex() == 0:
            comp = self.bg_frame.resize(img.size, Image.Resampling.LANCZOS).copy()
            comp.alpha_composite(img)
        rgb = comp.convert("RGB")
        q = QImage(rgb.tobytes("raw", "RGB"), img.width, img.height,
                   QImage.Format.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(q)
        self._fit()
        self.caption.setText(
            "Preview: our composite of the stored background frame plus the OSD "
            "layer we would send. This panel has no readback, so it is not a "
            "picture of the glass. "
            + self.bg_note)

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
        self.preview.setPixmap(self._pix.scaled(
            side, side, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

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
        self._repaint()

    # ---- settings --------------------------------------------------------
    def _changed(self, *_a) -> None:
        """Any picker moved: repaint now, write the file once the burst settles."""
        self._repaint()
        self.save_timer.start()

    def _state(self) -> dict:
        return {"device": self.port, "theme": self.theme.currentText(),
                "clock_size": self.clock_size.value(),
                "canvas": "black" if self.canvas.currentIndex() else "clear",
                "scrim": self.scrim.value(), "fans": self.fanline.isChecked(),
                "preview_fps": self.preview_fps, "clip": self.mp4,
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
        """List every clip, then fill thumbnails in the background of the list.

        Thumbnails cost an ffmpeg seek each, and the clip library here is 115
        files (3 vendored, 43 from the vendor's install, 69 the Windows app
        pushed at some point), so the rows go up at once with what a `stat` gives
        and the pictures and loop lengths arrive a row per timer tick.
        """
        self.clips.clear()
        self.all_clips = clipdb.list_clips()
        if not self.all_clips:
            self.clips.addItem("(no MP4 found: media/ is empty and the Windows "
                               "partition is not mounted)")
            return
        for c in self.all_clips:
            item = QListWidgetItem(self._row(c))
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
        rgb = img.convert("RGB").resize((112, 112), Image.Resampling.LANCZOS)
        q = QImage(rgb.tobytes("raw", "RGB"), 112, 112,
                   QImage.Format.Format_RGB888).copy()
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
        self.clip_info.setText(item.text() + self._clip_detail(path))

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
                return (f"\n{how}: {lum:.1f}/255 - {need}"
                        f"{size_note}"
                        f"\nsending it overwrites what the panel stores, and "
                        f"only a reset clears that again.")
        return ""

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
        # mark the row that is on the glass, if this window knows: in a 69-row
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
            f"clock {st.get('clock_size')}, scrim "
            f"{'auto' if st.get('scrim') is None else st.get('scrim')}, fans "
            f"{'on' if st.get('fans') else 'off'}, pending "
            f"{st.get('pending') or '-'}, space={dev.get('space')}")
        self.d_events.setText(
            "what the display has done on the port, oldest first:\n"
            + "\n".join(st.get("events")
                        or ["   (nothing it has chosen to report since it "
                            "started)"]))
        self._read_ring(st.get("events") or [])
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

    def _display_changed(self, present: bool) -> None:
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
            "canvas": "black" if self.canvas.currentIndex() else "clear",
            "scrim": self.scrim.value(),
            "fans": self.fanline.isChecked(),
            "fps": self.d_fps.value(),
        })
        # and what it deliberately left alone, said out loud.  A background is
        # not one of these six settings - it is a file that overwrites what the
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
