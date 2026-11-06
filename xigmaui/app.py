"""app.py - the main window: preview, theme pick, background pick, status, reset.

Layout follows what this panel actually supports rather than what the vendor's
window looks like:

    +---------------------------+  theme + clock + canvas options
    |  preview (480x480)        |  background clip list, with measured luma
    |  "our composite, not a    |  status from the panel
    |   mirror of the glass"    |  log pane
    +---------------------------+  guarded reset

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

The preview is `tools/previews.py`'s composite running live: the stored
background frame underneath, `render.draw` on top. It is labelled in the window
because there is no readback from this panel (PROTOCOL.md §11) - a preview here
is a promise about what we will put on the wire, not a picture of the glass.
"""
from __future__ import annotations

import inspect
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                            # noqa: E402
from PyQt6.QtCore import QSize, Qt, QTimer                        # noqa: E402
from PyQt6.QtGui import QAction, QIcon, QImage, QPixmap           # noqa: E402
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

ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "install", "xigmaui.png")


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
        self.setWindowTitle("Xigma - Xigmatek Connect 360")
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
        self.btn_apply.setToolTip("send the theme, clock size, canvas, scrim, "
                                  "fans and fps on this window to the display "
                                  "that is running. Nothing on this window "
                                  "changes the glass until you press it")
        self.btn_apply.clicked.connect(self._apply_to_display)
        rowe.addWidget(self.btn_apply)
        self.btn_dupload = QPushButton("Upload background")
        self.btn_dupload.setToolTip("queue this clip for the running display's "
                                    "frame loop. It replaces the panel's stored "
                                    "background; only a reset clears it")
        self.btn_dupload.clicked.connect(lambda: self.daemon.upload(self.mp4))
        rowe.addWidget(self.btn_dupload)
        llay.addLayout(rowe)
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
        form.addRow("theme", self.theme)
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

        media = QGroupBox("Background clips")
        mlay = QVBoxLayout(media)
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
        row = QHBoxLayout()
        self.btn_upload = QPushButton("Upload background")
        self.btn_upload.setToolTip("send the selected MP4 to the panel as its "
                                   "stored background layer. This overwrites "
                                   "what is stored; only a reset clears it.")
        self.btn_upload.clicked.connect(lambda: self.queue(
            "upload", path=self.mp4,
            # the two upload knobs come from the protocol module rather than
            # literals here: 0.02 s and 1000 B are measured wire facts, and a
            # second copy in the GUI could drift away from the measurement
            gap=protocol.MEDIA_GAP, chunk=protocol.MEDIA_CHUNK,
            fans=self.fanline.isChecked()))
        row.addWidget(self.btn_upload)
        self.btn_frame = QPushButton("Send one frame")
        self.btn_frame.setToolTip("render the preview frame now and put it on the "
                                  "glass as one `.osd` upload")
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
        split.addWidget(_scroll(left))
        split.addWidget(_scroll(right))
        split.setSizes([440, 560])
        self.setCentralWidget(split)
        self.statusBar().showMessage(f"port {self.port}")
        self._populate_clips()

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
        pane can be smaller than the panel.
        """
        if not hasattr(self, "_pix"):
            return
        self.preview.setPixmap(self._pix.scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:              # noqa: N802
        super().resizeEvent(event)
        self._fit()

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
                "size": [self.width(), self.height()]}

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
            item.setToolTip(c.path + (f"\n{c.note}" if c.note else ""))
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
                return (f"\n{how}: {lum:.1f}/255 - {need}"
                        f"\nsending it overwrites what the panel stores, and "
                        f"only a reset clears that again.")
        return ""

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
                self.daemon.upload(kw.get("path") or self.mp4)
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
        for w in (self.btn_pause, self.btn_dframe, self.btn_apply,
                  self.btn_dupload, self.d_fps):
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
        self.d_events.setText("\n".join(st.get("events") or []))
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
        self.daemon.apply({
            "theme": self.theme.currentText(),
            "clock_size": self.clock_size.value(),
            "canvas": "black" if self.canvas.currentIndex() else "clear",
            "scrim": self.scrim.value(),
            "fans": self.fanline.isChecked(),
            "fps": self.d_fps.value(),
        })

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
        self.tray = QSystemTrayIcon(QIcon(ICON) if os.path.exists(ICON)
                                    else QIcon(), self)
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
        self.tray.setToolTip("Xigma")
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
        self.tray.setToolTip("Xigma - " + (wire.describe(st) if st
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
        cur = self.log_view.text()
        self.log_view.setText((cur + "\n" if cur else "") + line)
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
    if os.path.exists(ICON):
        # set directly rather than by theme name: on a box with no icon theme
        # configured (this one) `fromTheme` finds nothing, and the picture is a
        # rendering of the glass, which is the one thing worth showing there -
        # in the taskbar and in the tray, where it is the only way to find us
        app.setWindowIcon(QIcon(ICON))
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
