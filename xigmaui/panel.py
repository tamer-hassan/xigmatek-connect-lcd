"""panel.py - the thread that opens the port, does one thing, and closes it.

Nothing in the GUI touches the serial port directly. Every action is a short
visit: open `Link`, `hello()`, do the one thing you asked for, close. That keeps
the window responsive and leaves `/dev/ttyACM0` free for `python3 -m xigmalcd`
between actions - one process can hold the port, and this one lets go.

Two rules the worker follows, both because of how this panel behaves:

* **A device that vanishes comes back by re-enumerating.** `recovery` resets the
  device; `Link`'s own `wait_for_device()` is what waits for it, and it has been
  run against a real reset (`tools/reset_panel.py` saw it reappear in about 3 s).
* **An upload's verdict is the notice**, not the ack. `send_media` returns
  `{"notice": ..., "ack": ...}` and the notice is the only verdict that means
  the panel opened the file (PROTOCOL.md §5).

Two more, because a session with pictures in it is a limited resource:

* **The metrics blob goes in twice at the head of a session and then never
  again** (`_open(blob=...)`). That is the vendor's shape - `STATE all 1` is TX
  frames 3 and 4 of its 51-frame init capture and absent from its 63-upload one
  - and it is also `main.py`'s startup order, because a session fed the blob per
  frame stops answering the media channel (PROTOCOL.md §8).
* **Session limits and upload shape are read from the daemon, not repeated
  here**: `panel.py` imports `main`'s `SESSION_MAX`, `SESSION_TTL`,
  `RECOVER_AFTER` and `REFUSE_GIVEUP` where it needs them and `app.py` imports
  `protocol.MEDIA_GAP` and `MEDIA_CHUNK` for the upload button, so the measured
  numbers live in exactly one place and the GUI cannot drift from them.

`report` callbacks hand progress back to the UI thread as plain strings.
"""
from __future__ import annotations

import contextlib
import glob
import io
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtCore import QThread, pyqtSignal                        # noqa: E402

from xigmalcd.protocol import Link, ProtocolError                   # noqa: E402
from xigmalcd import render, sensors                                # noqa: E402


@contextlib.contextmanager
def captured(into):
    """Send a helper's progress prints into the log pane.

    `main._upload_background` reports on stderr - it is the daemon's own
    function, and the daemon is a command-line program. Reaching into the GUI
    would mean editing a module two other passes of this project depend on, so
    instead the GUI borrows the stream for the duration of the call.
    """
    old = sys.stdout, sys.stderr
    buf = io.StringIO()
    sys.stdout = sys.stderr = buf
    try:
        yield buf
    finally:
        sys.stdout, sys.stderr = old
    for line in buf.getvalue().splitlines():
        if line.strip():
            into(line.rstrip())


def port_busy(port: str) -> str:
    """Who else is holding the port, as a human sentence ('' when free).

    `fuser` is how we clear the port during testing, so it is the honest check:
    a refused `open()` from pyserial says `Resource busy` but not who.
    """
    try:
        out = subprocess.run(["fuser", "-s", port], capture_output=True)
        if out.returncode == 0:
            names = subprocess.run(["fuser", port], capture_output=True,
                                   text=True).stdout.split()
            return (f"{port} is held by pid {' '.join(names)}. One process can "
                    f"hold the port, so let go of it first: Ctrl-C in the "
                    f"window running python3 -m xigmalcd, or "
                    f"`systemctl --user stop xigmalcd` if you installed the "
                    f"login unit, or fuser -k {port}")
    except (OSError, ValueError):
        pass
    try:
        with open(port, "rb"):
            return ""
    except OSError as exc:
        return f"cannot open {port}: {exc}"
    return ""


class Panel(QThread):
    """Runs one panel action at a time, off the UI thread."""

    log = pyqtSignal(str)
    status = pyqtSignal(dict)          # parsed `conn 1` reply + extra keys
    frame = pyqtSignal(object)         # PIL image, for "send one frame now"
    done = pyqtSignal(str, bool)       # (what it was, whether it worked)
    busy = pyqtSignal(bool, str)

    def __init__(self, port: str = "", parent=None):
        super().__init__(parent)
        self.port = port or "/dev/ttyACM0"
        self._todo: list[tuple] = []
        self._want = True

    # ---- queue -----------------------------------------------------------
    def queue(self, kind: str, **kw) -> None:
        self._todo.append((kind, kw))
        if not self.isRunning():
            self._want = True
            self.start()

    def stop(self) -> None:
        self._want = False
        self.wait(4000)

    # ---- the loop --------------------------------------------------------
    def run(self) -> None:
        self._want = True
        while self._want and self._todo:
            kind, kw = self._todo.pop(0)
            self.busy.emit(True, kind)
            try:
                ok = getattr(self, f"_{kind}")(**kw)
            except ProtocolError as exc:
                self.log.emit(f"REFUSED/FAILED {kind}: {exc}")
                ok = False
            except Exception as exc:                       # noqa: BLE001
                self.log.emit(f"{kind} raised {type(exc).__name__}: {exc}")
                ok = False
            self.busy.emit(False, kind)
            self.done.emit(kind, bool(ok))
        self._want = False

    # ---- connection ------------------------------------------------------
    def _open(self, destructive: bool = False, blob: dict | None = None) -> Link | None:
        """Open, pump, say hello, and push the metrics blob if one was handed in.

        `Link`'s constructor opens the port, so the busy check has to come first
        and the constructor sits in a try: a `Resource busy` from pyserial says
        nothing about who holds the port, which is why `port_busy()` asks fuser.

        The blob goes here, twice, at the head of the session and nowhere else.
        That is what the vendor does - `STATE all 1` is TX frames 3 and 4 of its
        51-frame init capture and absent from its 63-upload one - and it is what
        `main.py` does at startup, because feeding the blob per frame makes the
        panel stop answering the media channel (PROTOCOL.md §8).
        """
        why = port_busy(self.port)
        if why:
            self.log.emit(why)
            return None
        try:
            link = Link(self.port, timeout=3.0, allow_destructive=destructive)
        except Exception as exc:                               # noqa: BLE001
            self.log.emit(f"could not open {self.port}: {exc}")
            return None
        link.__enter__()
        link.start_pump()
        link.hello(60)
        if blob is not None:
            try:
                for _ in range(2):
                    link.state_all(blob)
                    time.sleep(0.05)
                link.drain()
                fans = "with" if blob.get("fans") is not None else "without"
                self.log.emit(f"metrics: `STATE all 1` twice at session start, "
                              f"then left alone ({fans} the fans array)")
            except ProtocolError as exc:
                self.log.emit(f"metrics: the panel did not answer `STATE all 1`: "
                              f"{exc}")
        return link

    def _close(self, link: Link | None) -> None:
        """Close a link. A no-op when `_open` already failed and said so."""
        if link is None:
            return
        try:
            link.drain(0.05)
        except Exception:                                  # noqa: BLE001
            pass
        link.__exit__(None, None, None)

    # ---- actions ---------------------------------------------------------
    def _status(self, **_) -> bool:
        """Ask the panel who it is and what it is set to (the only read we have)."""
        link = self._open()
        if link is None:
            return False
        try:
            info = link.device_info()
            link.harvest(0.3)
            self.log.emit("device info: " + _flatten(info))
            self.status.emit(info)
            return True
        finally:
            self._close(link)

    def _upload(self, path: str, gap: float, chunk: int, fans: bool = True,
                **_) -> bool:
        """Put an MP4 on the panel as its stored background layer.

        This is the daemon's `main._upload_background` - same raw-file upload,
        same 0.02 s pre-byte pause, same one retry - reached through the GUI
        rather than duplicated here. The panel takes the whole MP4 as one file
        and plays it itself; we do not decode it on the way.

        The metrics blob goes first, in `main.main`'s startup order: hello,
        `STATE all 1` twice, then the picture files. A session that is fed
        metrics per frame stops answering transfers, and ALPHA's own 63-upload
        media capture contains no `STATE` frame at all, so this is one push per
        session and never one per file (PROTOCOL.md §8).
        """
        from xigmalcd.main import _upload_background

        link = self._open(blob=self._blob(fans))
        if link is None:
            return False
        try:
            args = _Args(mp4=path, gap=gap, chunk=chunk)
            with captured(self.log.emit):
                ok = bool(_upload_background(link, args))
            if not ok:
                self.log.emit("the panel refused this background. The refusal is "
                              "positional, not about the file: the same bytes "
                              "were refused with `1 400` and accepted on the "
                              "next attempt (PROTOCOL.md §9). Try again.")
                return False
            info = link.device_info()
            self.status.emit(info)
            self.log.emit(f"background is now {os.path.basename(path)}. The "
                          f"panel plays it, then holds it under the OSD layer "
                          f"until a reset clears it.")
            return True
        finally:
            self._close(link)

    def _blob(self, fans: bool = True) -> dict:
        """The `STATE all 1` body: the host's own sensors, fans optional.

        Same shape and same rule as `main.sample()`, which pops the `fans` array
        under `--no-fans`. These numbers are the host's, read off the Super-IO and
        from `nvidia-smi`; the panel reports `attribute:["Status","Fan","Pump"]`
        as a capability and has never once sent a tach back (PROTOCOL.md §7).
        """
        m = sensors.collect()
        if not fans:
            m.pop("fans", None)
        return m

    def _frame(self, theme: str, kw: dict, fans: bool = True, **_) -> bool:
        """Send one live OSD frame: what the preview shows, on the glass."""
        link = self._open(blob=self._blob(fans))
        if link is None:
            return False
        try:
            m = sensors.collect()
            img = render.draw(m, theme, **kw)
            self.frame.emit(img.copy())
            png = render.to_png(img)
            res = link.send_media(render.frame_name(), png, wait=True)
            notice = str(res.get("notice") or "")
            if not notice.startswith("2"):
                self.log.emit(f"the panel answered this frame with notice {notice}")
                return False
            self.log.emit(f"one frame sent: {theme}, {len(png) // 1024} KiB PNG, "
                          f"notice {notice}")
            return True
        finally:
            self._close(link)

    def _live(self, theme: str, kw: dict, fps: float, seconds: float,
              fans: bool = True, **_) -> bool:
        """Run the frame loop for `seconds` so you can watch the real glass.

        Same ordering the daemon uses and for the same reason: `wait=True` with
        `order="notice"` holds `transported` back until the notice has landed,
        which is what makes the panel redraw once a second instead of once every
        few seconds (PROTOCOL.md §6, §9). A refused frame does not stop the run;
        two failures in a row renew the link, as `main.rehandshake` does.

        The session limits come from `main`, not restated here, because the panel
        exhausts a session on *both* axes: about 500 uploads (measured twice at
        exactly 500 / 167 s at 3 fps) and about 300 s of wall clock (silence at
        ~370 s at 2 fps). A run at 1 fps reaches the clock first, so counting
        uploads alone is not enough for anything longer than a minute or two
        (PROTOCOL.md §9). And a panel that answers but refuses every file is not
        fixed by renewing, so after `REFUSE_GIVEUP` refusals in a row the run
        stops and says so instead of spending the rest of its window on a dead
        channel.
        """
        from xigmalcd.main import (RECOVER_AFTER, REFUSE_GIVEUP, SESSION_MAX,
                                   SESSION_TTL)

        link = self._open(blob=self._blob(fans))
        if link is None:
            return False
        end = time.monotonic() + seconds
        sent = refused = bad = streak = 0
        since_ok = 0
        since_renew = time.monotonic()
        try:
            while time.monotonic() < end:
                t0 = time.monotonic()
                if (SESSION_MAX and sent - since_ok >= SESSION_MAX) or \
                   (SESSION_TTL and time.monotonic() - since_renew >= SESSION_TTL):
                    self.log.emit(
                        f"renewing the upload session on purpose after "
                        f"{sent - since_ok} uploads / "
                        f"{time.monotonic() - since_renew:.0f} s: the panel "
                        f"exhausts one on about {SESSION_MAX} uploads or about "
                        f"{SESSION_TTL} s, whichever comes first")
                    self._close(link)
                    # a renewed session re-helloes and does not re-push the
                    # blob: that is what main.rehandshake does, and §8's
                    # evidence covers a session head, not every reopen
                    link = self._open()
                    if link is None:
                        self.log.emit("the port went away at the renewal, so "
                                      "the run stops here rather than sending "
                                      "into nothing")
                        return False
                    since_ok, since_renew = sent, time.monotonic()
                m = sensors.collect()
                img = render.draw(m, theme, **kw)
                self.frame.emit(img.copy())
                name = render.frame_name()
                try:
                    res = link.send_media(name, render.to_png(img), wait=True)
                    sent += 1
                    notice = str(res.get("notice") or "")
                    if notice.startswith("2"):
                        streak = 0
                    else:
                        refused += 1
                        streak += 1
                    bad = 0
                except ProtocolError as exc:
                    refused += 1
                    bad += 1
                    streak += 1
                    if bad == 1:
                        self.log.emit(f"frame refused: {exc}")
                    if bad >= RECOVER_AFTER:
                        self.log.emit("renewing the session after two failures")
                        self._close(link)
                        link = self._open()
                        if link is None:
                            self.log.emit("the port went away at the renewal, "
                                          "so the run stops here")
                            return False
                        since_ok, since_renew = sent, time.monotonic()
                        bad = 0
                if streak >= REFUSE_GIVEUP:
                    self.log.emit(
                        f"{streak} files in a row refused while the commands "
                        f"still answer: renewing does not cure that, and the "
                        f"usual cause is upload shape (PROTOCOL.md §6). Stopping "
                        f"the run instead of spending its window on a dead "
                        f"channel.")
                    break
                nap = 1.0 / max(0.1, fps) - (time.monotonic() - t0)
                if nap > 0:
                    time.sleep(nap)
            self.log.emit(f"live run: {sent} sent, {refused} refused")
            return sent > 0 and refused == 0
        finally:
            self._close(link)

    def _reset(self, confirm: str, **_) -> bool:
        """The vendor's `recovery` - the same frame `xigmalcd-reset` /
        tools/reset_panel.py sends (xigmalcd/reset.py).

        Destructive: the panel goes back to its default state, the USB device
        re-enumerates, and a `recovery` frame is *not* an acked `conn` close, so
        a client that resets then writes sees `1 400` on the next request
        (PROTOCOL.md §5). That is why this path closes the port and waits for
        the device to come back instead of carrying on using the link.
        """
        if confirm != "reset":
            self.log.emit("reset needs the word `reset` typed in - nothing sent")
            return False
        link = self._open(destructive=True)
        if link is None:
            return False
        try:
            before = link.device_info()
            self.log.emit(f"before: {_flatten(before)}")
            link.post("recovery", {"enable": True})
            self.log.emit("sent. Waiting for the device to re-enumerate.")
        finally:
            self._close(link)
        back = ""
        end = time.monotonic() + 30
        while time.monotonic() < end:
            time.sleep(1.0)
            ports = glob.glob("/dev/ttyACM*")
            if ports:
                back = ports[0]
                self.log.emit(f"device is back as {back}")
                break
        if not back:
            self.log.emit("the device has not come back after 30 s. Unplug and "
                          "replug the panel's USB cable.")
            return False
        time.sleep(1.0)                      # the CDC interface needs a moment
        return self._status()


class _Args:
    """The few attributes `_upload_background` reads from the daemon's argparse."""

    def __init__(self, mp4: str, gap: float, chunk: int):
        self.mp4, self.gap, self.chunk = mp4, gap, chunk


def flatten(info: dict) -> dict:
    """One `key -> value` per field the panel reported, nesting unwrapped.

    The `conn 1` reply is mostly top-level scalars with one nested dict
    (`version`), and the scalars are the interesting part: `sn`, `space`,
    `brightness`, `degree`, `mode`, `logo`, `osdState`, `timeout`. A flattener
    that only walks dicts shows three version strings and nothing else, which is
    what this function's first draft did.
    """
    out: dict = {}
    for k, v in (info or {}).items():
        if isinstance(v, dict):
            out.update(v)
        elif isinstance(v, (list, tuple)):
            out[k] = ",".join(str(x) for x in v)
        else:
            out[k] = v
    return out


# What each reported field means, only where PROTOCOL.md records it. The panel
# is not documented anywhere, so a field we cannot explain is shown as `key=value`
# rather than dressed up with a guess.
FIELD_NOTES = {
    "sn": "serial number",
    "space": "reported free space - not a size ledger (PROTOCOL §9)",
    "brightness": "backlight, 0-100; `power resume` moves it 0 -> 100 (§5)",
    "degree": "rotation, the `rotate` body's degree (§5)",
    "logo": "boot animation id: 3 is ALPHA's, 2147483647 means none (§7)",
    "mode": "panel's own drawing mode; Windows captures show 0 (§7)",
    "osdState": "1 while the OSD layer is drawn; 0 shows only the logo (§7)",
    "timeout": "keepalive seconds we asked for in `hello`",
    "app": "app version",
    "firmware": "firmware version",
    "hardware": "hardware version",
    "OS": "what the panel calls itself",
    "attribute": "what the panel says it can draw - capability only, never "
                 "observed (§7)",
}


def describe(info: dict) -> str:
    """Multi-line, human-readable form for the status pane."""
    lines = []
    for k, v in flatten(info).items():
        note = FIELD_NOTES.get(k)
        lines.append(f"{k} = {v}" + (f"    ({note})" if note else ""))
    return "\n".join(lines)


def _flatten(info: dict) -> str:
    return " ".join(f"{k}={v}" for k, v in flatten(info or {}).items())
