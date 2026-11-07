"""control.py - the socket between the running display and anything that wants
to talk to it.

One process can hold /dev/ttyACM0 (PROTOCOL.md §1), so the panel cannot be driven
by a window and a service at once.  This is the way round that: `xigmalcd` keeps
the port and the only thread that ever writes to it, and the window becomes a
client of a unix socket.  Nothing here opens a port, and nothing here sends a
frame - the daemon's own loop picks up what the socket asked for on its next
iteration.  That single-owner rule is the whole point, so it is enforced by
construction rather than by convention:

* settings the loop re-reads every iteration (theme, fps, title, scrim, canvas)
  are just fields on `Control`, guarded by a lock;
* anything that touches the panel (a background upload, one forced frame) goes
  onto a one-item "pending action" queue that only the loop thread pops;
* the status the socket hands back is a snapshot the loop writes after each
  frame, so a client can read it while the loop is mid-upload and never sees a
  half-updated counter.

Protocol, one JSON object per line in each direction:

    {"cmd": "status"}                     -> {"ok": true, "status": {...}}
    {"cmd": "theme", "value": "gauge"}    -> {"ok": true, "status": {...}}
    {"cmd": "fps", "value": 1.5}          {"cmd": "clock_size", "value": 40}
    {"cmd": "bg", "value": "black"}       {"cmd": "scrim", "value": "auto"}
    {"cmd": "fans", "value": false}       {"cmd": "title", "value": "Xigma"}
    {"cmd": "pause"} / {"cmd": "resume"}
    {"cmd": "upload", "path": "media/Theme_11.mp4"}   queued for the loop
    {"cmd": "frame"}                                  queued for the loop
    {"cmd": "config"}                                effective settings + paths

Errors come back as {"ok": false, "error": "..."}, and one command is refused by
default: `reset` is the vendor's `recovery`, which re-enumerates the USB device,
so it needs the daemon to have been started with --allow-reset.  A socket should
not be a way to reach a destructive write nobody asked for.

The socket lives at $XDG_RUNTIME_DIR/xigmalcd.sock (falling back to
/run/user/UID, ~/run, /tmp/xigma-UID.sock), the directory is created 0700 and the
socket chmodded to 0600, and the peer's uid is checked with SO_PEERCRED.  That is
defence against another ordinary user, not against anything running as you.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import threading
import time

SOCKET_ENV = "XIGMA_SOCKET"
DEFAULT_NAME = "xigmalcd.sock"

#: canvas under the glyphs.  Same two choices as `--bg`: transparent, so the
#: panel's own stored clip keeps playing behind the picture (what ALPHA does),
#: or opaque black.
CANVASES = ("clear", "black")


# ---- where the socket lives -------------------------------------------------

def socket_path(explicit: str = "") -> str:
    """Where to find (or create) the control socket.

    $XDG_RUNTIME_DIR is the systemd-user location, which is what the shipped
    unit sets; without it (a plain shell, a test) we fall back somewhere that
    exists and is private to this uid.
    """
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    env = os.environ.get(SOCKET_ENV)
    if env:
        return os.path.abspath(os.path.expanduser(env))
    for base in (os.environ.get("XDG_RUNTIME_DIR"),
                 f"/run/user/{os.getuid()}",
                 os.path.expanduser("~/.local/run")):
        if base and os.path.isdir(base):
            return os.path.join(base, DEFAULT_NAME)
    return f"/tmp/xigma-{os.getuid()}.sock"


# ---- the shared state ------------------------------------------------------

class Control:
    """What the loop reads every iteration, and what a client may change.

    `args` is the daemon's own parsed settings, kept as the single settings
    object so the loop's code does not change shape; `apply()` mutates it under
    the lock.  `status()` is the snapshot the loop publishes.
    """

    #: what a client may change by name, and how to sanity-check the value
    SETTINGS = {
        "theme": str,
        "fps": float,
        "title": str,
        "label": str,
        "scrim": int,
        "clock_size": int,
        "bg": str,
    }

    def __init__(self, args, port: str, allow_reset: bool = False):
        self.args = args
        self.port = port
        self.allow_reset = allow_reset
        self.lock = threading.Lock()
        self.started = time.time()
        self.paused = False
        self.stop = False
        # counters the loop owns; published, never written by a client
        self.counters: dict = {"frames": 0, "ok": 0, "refused": 0,
                               "renewals": 0, "errors": 0,
                               "last_notice": "", "last_name": "",
                               "last_bytes": 0, "last_error": "",
                               "session_uploads": 0, "session_age": 0.0,
                               "device": {}}
        # one slot: a client asks, the loop thread does.  Only the loop pops it,
        # so panel traffic keeps one owner.
        self._pending: tuple | None = None
        self._events: list[str] = []          # recent notes, newest last

    # -- client side ---------------------------------------------------------
    def request(self, obj: dict) -> dict:
        """Apply one command.  Returns {"ok": ..., "status"/"error": ...}."""
        cmd = str(obj.get("cmd") or "").strip().lower()
        if cmd in ("", "status"):
            return {"ok": True, "status": self.status()}
        if cmd == "config":
            return {"ok": True, "config": self.config(),
                    "status": self.status()}
        if cmd == "pause":
            with self.lock:
                self.paused = True
            self.note("paused by the control socket: no frames go out until "
                      "resume")
            return {"ok": True, "status": self.status()}
        if cmd == "resume":
            with self.lock:
                self.paused = False
            self.note("resumed")
            return {"ok": True, "status": self.status()}
        if cmd == "theme":
            return self._set_theme(obj.get("value"))
        if cmd == "fps":
            return self._set_number("fps", obj.get("value"), 0.1, 5.0)
        if cmd == "clock_size":
            return self._set_number("clock_size", obj.get("value"), 8, 120)
        if cmd == "scrim":
            if obj.get("value") in (None, "", "auto", -1):
                # back to the daemon's own rule: a plate only over a clip
                # measured brighter than mid-grey (main._scrim_for)
                with self.lock:
                    self.args.scrim = None
                return {"ok": True, "status": self.status()}
            return self._set_number("scrim", obj.get("value"), 0, 255)
        if cmd == "fans":
            val = obj.get("value")
            if not isinstance(val, bool):
                return {"ok": False, "error": "fans needs true or false"}
            # one switch, two effects, both of them the daemon's own: the fan
            # line on the picture and the `fans` array in the metrics blob
            with self.lock:
                self.args.no_fans = not val
            return {"ok": True, "status": self.status()}
        if cmd in ("title", "label"):
            val = str(obj.get("value") if obj.get("value") is not None
                      else self._default(cmd))
            with self.lock:
                setattr(self.args, cmd, val)
            return {"ok": True, "status": self.status()}
        if cmd == "bg":
            return self._set_bg(obj.get("value"))
        if cmd == "upload":
            return self._queue("upload", obj.get("path"))
        if cmd == "frame":
            return self._queue("frame", None)
        if cmd == "reset":
            if not self.allow_reset:
                return {"ok": False,
                        "error": "refusing reset: `recovery` re-enumerates the "
                                 "USB device and returns the panel to its "
                                 "default state. Start xigmalcd with "
                                 "--allow-reset if you mean to allow it over "
                                 "the socket; xigmalcd-reset --yes (in a "
                                 "checkout, tools/reset_panel.py --yes) is "
                                 "the deliberate way."}
            return self._queue("reset", None)
        if cmd in ("quit", "stop", "exit"):
            # stopping the display is systemd's job; say so rather than doing
            # something a user cannot undo from a menu click
            return {"ok": False,
                    "error": "use systemctl --user stop xigmalcd (or Ctrl-C) "
                             "to stop the display; the socket can pause it, "
                             "which is reversible"}
        return {"ok": False, "error": f"unknown cmd {cmd!r}"}

    def _set_theme(self, value) -> dict:
        from . import render
        name = str(value or "")
        if name not in render.THEMES:
            return {"ok": False,
                    "error": f"unknown theme {name!r}; "
                             f"try {' '.join(sorted(render.THEMES))}"}
        with self.lock:
            self.args.theme = name
        return {"ok": True, "status": self.status()}

    def _set_number(self, field: str, value, lo, hi) -> dict:
        try:
            val = float(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"{field} needs a number"}
        if not lo <= val <= hi:
            return {"ok": False, "error": f"{field} must be between {lo} and {hi}"}
        with self.lock:
            setattr(self.args, field, int(val) if field != "fps" else val)
        return {"ok": True, "status": self.status()}

    def _set_bg(self, value) -> dict:
        bg = str(value or "")
        if bg not in CANVASES:
            return {"ok": False,
                    "error": f"unknown canvas {bg!r}; "
                             f"try {' '.join(CANVASES)}"}
        with self.lock:
            self.args.bg = bg
        return {"ok": True, "status": self.status()}

    def _default(self, field: str):
        return getattr(self.args, field, "")

    def _queue(self, kind: str, path) -> dict:
        """Ask the loop thread to do something that needs the port."""
        if kind == "upload":
            ok, why = check_media_file(path)
            if not ok:
                return {"ok": False, "error": why}
        with self.lock:
            if self._pending is not None:
                want = path or kind
                have = self._pending[1] or self._pending[0]
                return {"ok": False,
                        "error": f"already queued: {have}; {want} not queued "
                                 f"(one action at a time, so the loop cannot "
                                 f"be talked into two uploads at once)"}
            self._pending = (kind, path)
        self.note(f"queued {kind}{': ' + str(path) if path else ''}")
        return {"ok": True, "queued": kind, "status": self.status()}

    def take(self) -> tuple | None:
        """Loop-thread only: pop the pending action, if any."""
        with self.lock:
            act, self._pending = self._pending, None
        return act

    # -- publishing ----------------------------------------------------------
    def note(self, text: str) -> None:
        with self.lock:
            self._events.append(f"{time.strftime('%H:%M:%S')} {text}")
            del self._events[:-20]

    def publish(self, **kw) -> None:
        """Loop-thread only: publish counters a client can read."""
        with self.lock:
            self.counters.update(kw)

    def status(self) -> dict:
        with self.lock:
            out = dict(self.counters)
            out.update({
                "paused": self.paused,
                "pending": (self._pending[0] if self._pending else ""),
                "theme": getattr(self.args, "theme", ""),
                "fps": getattr(self.args, "fps", 0.0),
                "title": getattr(self.args, "title", ""),
                "canvas": getattr(self.args, "bg", ""),
                "clock_size": getattr(self.args, "clock_size", 0),
                "scrim": getattr(self.args, "scrim", None),
                "fans": not getattr(self.args, "no_fans", False),
                "port": self.port,
                "uptime": round(time.time() - self.started, 1),
                "events": list(self._events[-6:]),
            })
            return out

    def config(self) -> dict:
        with self.lock:
            return {
                "port": self.port,
                "theme": getattr(self.args, "theme", ""),
                "fps": getattr(self.args, "fps", 0.0),
                "clip": getattr(self.args, "mp4", "") or "",
                "canvas": getattr(self.args, "bg", ""),
                "clock_size": getattr(self.args, "clock_size", 0),
                "scrim": getattr(self.args, "scrim", None),
                "title": getattr(self.args, "title", ""),
                "fans": not getattr(self.args, "no_fans", False),
                "allow_reset": self.allow_reset,
                "socket": socket_path(),
            }


# ---- what an upload may be --------------------------------------------------

#: never accept these, whatever the extension says.  `type: "firmware"` is the
#: update path (PROTOCOL.md §7) and a .zip is how the vendor ships it; a socket
#: must not become a route to either.
REFUSED_SUFFIXES = (".zip", ".bin", ".img", ".tar", ".gz", ".hex", ".elf")


def check_media_file(path) -> tuple[bool, str]:
    """Is this a picture file the media channel can hold?  (path, why not)"""
    if not path:
        return False, "upload needs a path"
    p = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isfile(p):
        return False, f"no such file: {p}"
    low = p.lower()
    if low.endswith(REFUSED_SUFFIXES):
        return False, (f"refusing {os.path.basename(p)}: that is not a picture "
                       f"file and the media channel is not the way to send one "
                       f"(the firmware path is `type: \"firmware\"`, which "
                       f"nothing in this project sends)")
    if not low.endswith((".mp4", ".png", ".osd")):
        return False, f"not something the panel can store: {os.path.basename(p)}"
    size = os.path.getsize(p)
    if size == 0:
        return False, f"{os.path.basename(p)} is empty"
    if size > 8_000_000:
        # the largest thing the vendor app has ever pushed here is Theme_11.mp4
        # at 3.4 MB; anything much bigger is a mistake rather than a background
        return False, f"{os.path.basename(p)} is {size} B, which is past the " \
                      f"largest clip this panel is known to take"
    return True, p


# ---- the server thread ------------------------------------------------------

class Server:
    """Accepts JSON lines and answers them against a `Control`."""

    def __init__(self, control: Control, path: str = ""):
        self.control = control
        self.path = socket_path(path)
        self._srv: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.error = ""

    def start(self) -> bool:
        d = os.path.dirname(self.path) or "."
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            if os.path.exists(self.path):
                # a stale socket from a dead run: nothing answers on it, so
                # saying "address in use" and dying is worse than replacing it
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM):
                        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        probe.connect(self.path)
                        probe.close()
                    self.error = f"{self.path} is answering: another xigmalcd " \
                                 f"is already running"
                    return False
                except OSError:
                    os.unlink(self.path)
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(self.path)
            os.chmod(self.path, 0o600)      # only this user, whatever umask says
            srv.listen(4)
            self._srv = srv
        except OSError as exc:
            self.error = f"cannot listen on {self.path}: {exc}"
            return False
        self._thread = threading.Thread(target=self._run, name="xigma-control",
                                        daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
            self._srv = None
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def _run(self) -> None:
        while self._srv is not None:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return                      # stop() closed the listener
            try:
                self._handle(conn)
            except (OSError, ValueError) as exc:
                self.control.note(f"control connection dropped: {exc}")
            except Exception as exc:
                # whatever a client sent, it must not be able to take the
                # display down with it: the frame loop is a different thread
                # and keeps drawing
                self.control.note(f"control request failed: "
                                  f"{type(exc).__name__}: {exc}")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn: socket.socket) -> None:
        if not self._peer_is_us(conn):
            conn.sendall(b'{"ok": false, "error": "peer uid is not mine"}\n')
            return
        conn.settimeout(5.0)
        buf = b""
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line.decode("utf-8", "replace"))
                except ValueError as exc:
                    out = {"ok": False, "error": f"not JSON: {exc}"}
                else:
                    out = self.control.request(obj if isinstance(obj, dict)
                                               else {"cmd": "status"})
                try:
                    conn.sendall(json.dumps(out).encode() + b"\n")
                except OSError:
                    return

    def _peer_is_us(self, conn: socket.socket) -> bool:
        """SO_PEERCRED: the socket file is 0600, and this says so anyway.

        `struct ucred` is three ints on Linux - pid, uid, gid - and the kernel
        fills them in, so nothing on the other end of the connection can claim
        another uid."""
        if not hasattr(socket, "SO_PEERCRED"):
            return True
        try:
            raw = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                  struct.calcsize("iii"))
        except OSError:
            return True
        uid = struct.unpack("iii", raw)[1]
        return uid in (os.getuid(), 0)


# ---- the client side --------------------------------------------------------

class Client:
    """Talks to a running `xigmalcd`.  Raises ControlUnavailable if not there."""

    def __init__(self, path: str = "", timeout: float = 3.0):
        self.path = socket_path(path)
        self.timeout = timeout

    def available(self) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(self.path)
            return True
        except OSError:
            return False

    def ask(self, obj: dict) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout)
                s.connect(self.path)
                s.sendall(json.dumps(obj).encode() + b"\n")
                buf = b""
                while b"\n" not in buf:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
        except OSError as exc:
            raise ControlUnavailable(f"no answer from {self.path}: {exc}") \
                from exc
        line = buf.split(b"\n", 1)[0]
        try:
            return json.loads(line.decode("utf-8", "replace"))
        except ValueError as exc:
            raise ControlUnavailable(f"{self.path} said non-JSON: {line[:80]!r}") \
                from exc

    def status(self) -> dict:
        rep = self.ask({"cmd": "status"})
        if not rep.get("ok"):
            raise ControlUnavailable(rep.get("error", "no status"))
        return rep["status"]


class ControlUnavailable(OSError):
    """No daemon, no socket, or an answer we cannot use."""


def describe(status: dict) -> str:
    """One honest line about what a running display is doing."""
    if not status:
        return "not running"
    state = "paused" if status.get("paused") else "showing"
    dev = status.get("device") or {}
    return (f"{state} {status.get('theme')} at {status.get('fps')} fps on "
            f"{status.get('port')}: {status.get('ok')}/{status.get('frames')} "
            f"frames confirmed, {status.get('refused')} refused, "
            f"session {status.get('session_uploads')} uploads / "
            f"{status.get('session_age', 0):.0f} s, "
            f"space={dev.get('space')}, last notice "
            f"{status.get('last_notice') or '-'}")
