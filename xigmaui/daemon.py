"""daemon.py - the window's side of the control socket.

`xigmalcd/control.py` is the other half: the daemon owns /dev/ttyACM0, draws the
frames, and answers JSON lines on a unix socket.  This is what the window uses
to talk to it, and one property of that split decides how this file is written:

**A control command never waits on the panel.**  The daemon's server thread only
touches in-process state - it sets a field the frame loop re-reads, or leaves one
request in a slot the loop thread picks up - so every call here returns in
milliseconds.  That is why these calls run on the UI thread: there is no serial
round trip, no 2.4 s upload, no 90 s timeout hiding behind a button.  An upload
arrives as a queue slot and the loop carries it out.

Two things this class refuses to confuse, because they read alike in a log and
mean opposite things:

* **a refusal** - the daemon answered and said no (an out-of-range fps, a `.zip`,
  `reset` without --allow-reset).  The display is up and unchanged.
* **no answer** - nothing is listening.  The display is not running, and
  `present` goes False so the window falls back to its direct-port worker.

A daemon that is not running is the normal state of a development box, not an
error: `poll()` says which it found, quietly.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PyQt6.QtCore import QObject, pyqtSignal                        # noqa: E402

from xigmalcd import control                                        # noqa: E402


class Daemon(QObject):
    """A running `xigmalcd`, as seen from the window."""

    changed = pyqtSignal(bool)        # a display appeared / went away
    refreshed = pyqtSignal(dict)      # a new status snapshot
    log = pyqtSignal(str)
    done = pyqtSignal(str, bool)      # (what was asked, was it accepted)

    def __init__(self, path: str = "", parent=None):
        super().__init__(parent)
        self.path = control.socket_path(path)
        self.client = control.Client(self.path)
        self.present = False
        self.status: dict = {}

    # ---- is anything showing on the glass? -------------------------------
    def poll(self, report: bool = False) -> dict:
        """Ask the socket what it is drawing; {} when nothing answers.

        `report` logs the appearance/disappearance transitions.  The window
        polls on a timer, and a timer that wrote a line every 2 s would fill the
        log with nothing but its own heartbeat.
        """
        try:
            st = self.client.status()
        except control.ControlUnavailable as exc:
            if self.present or report:
                self.log.emit(f"no display on {self.path}: {exc}")
            self._absent()
            return {}
        first = not self.present
        self.present = True
        self.status = st
        if first:
            self.changed.emit(True)
            if report:
                self.log.emit(f"the display is running: {self.line()}")
        self.refreshed.emit(st)
        return st

    def _absent(self) -> None:
        was = self.present
        self.present = False
        self.status = {}
        if was:
            self.changed.emit(False)

    def line(self) -> str:
        """One honest sentence about what the display is doing."""
        return control.describe(self.status)

    # ---- commands --------------------------------------------------------
    def send(self, cmd: str, **kw) -> dict:
        """Ask for one thing.  Never raises: a refusal is data, not a crash."""
        try:
            rep = self.client.ask({"cmd": cmd} | kw)
        except control.ControlUnavailable as exc:
            # only now is "the display is not there" the right sentence: an
            # answer that says `no` is reported as a refusal further down
            self.log.emit(f"no answer from {self.path}: {exc}")
            self._absent()
            self.done.emit(cmd, False)
            return {"ok": False, "error": str(exc)}
        ok = bool(rep.get("ok"))
        if ok:
            self.status = rep.get("status") or self.status
            self.refreshed.emit(self.status)
        else:
            self.log.emit(f"the display refused {cmd}: "
                          f"{rep.get('error') or 'no reason given'}")
        self.done.emit(cmd, ok)
        return rep

    def pause(self) -> dict:
        return self.send("pause")

    def resume(self) -> dict:
        return self.send("resume")

    def frame(self) -> dict:
        """One frame now, even while paused.  Queued, not waited on."""
        return self.send("frame")

    def upload(self, path: str) -> dict:
        """Ask for a background clip.  The daemon's loop does the upload."""
        return self.send("upload", path=path)

    def reset(self) -> dict:
        """`recovery`, and almost always a refusal: see control.py."""
        return self.send("reset")

    #: commands that only a display new enough to have them will know, with the
    #: status field that proves it knows one.  A window and a display of the same
    #: build agree by construction; the mixed case is the installed 0.2 service
    #: driven by a newer window, which is what the author actually has, and the
    #: answer there is to not offer a command that comes back `unknown cmd` and
    #: then call that a failed Apply.
    OPTIONAL = {"text_color": "text_color"}

    def knows(self, cmd: str) -> bool:
        """Does the running display report the field that goes with `cmd`?

        A heuristic, and deliberately the weakest one possible: it asks the
        display what it is doing and looks at what it volunteered.  An empty
        status answers "yes", because knowing nothing is not evidence of an old
        display - `apply` is only reached after a poll that found a display.
        """
        field = self.OPTIONAL.get(cmd)
        if field is None or not self.status:
            return True
        return field in self.status

    def apply(self, state: dict) -> bool:
        """Send the window's pickers to a display that is already running.

        One command per setting, because that is what the socket speaks and
        what lets the daemon refuse one of them on its own merits.  The window's
        `scrim` of -1 means "the daemon's rule", which is sent as `auto` rather
        than as a number the window made up.

        A command the display has never heard of is not a refusal and is not
        sent: it is left out, said out loud, and the rest still goes.  Counting
        that as a failure was the bug - on the installed 0.2 service, Apply with
        a colour picked reported "the display kept its old text_color" as though
        nothing had been applied, when in fact every setting it does know about
        had been.
        """
        want = [("theme", state["theme"]),
                ("clock_size", state["clock_size"]),
                # "" is the theme's own skin, which is what the socket's `null`
                # means; the display answers with the hex it kept, so the window
                # reads back the colour actually in force (xigmalcd/control.py)
                ("text_color", state["text_color"] or None),
                ("bg", state["canvas"]),
                ("scrim", None if state["scrim"] < 0 else state["scrim"]),
                ("fans", state["fans"]),
                ("fps", state["fps"])]
        unknown = [cmd for cmd, _ in want if cmd in self.OPTIONAL
                   and not self.knows(cmd)]
        if unknown:
            want = [(c, v) for c, v in want if c not in unknown]
            self.log.emit(
                "left " + " and ".join(unknown) + " alone: the display running "
                "here does not report it, so it is older than this window. "
                "Everything else was sent; the option works against this tree's "
                "own `python3 -m xigmalcd`, or once the package is updated")
        refused = []
        for cmd, value in want:
            if not self.send(cmd, value=value)["ok"]:
                refused.append(cmd)
        if refused:
            self.log.emit("the display kept its old " + ", ".join(refused))
            return False
        self.log.emit(
            f"display told: theme {state['theme']}, clock {state['clock_size']}, "
            + ("" if unknown else
               f"text {state['text_color'] or 'theme default'}, ")
            + f"canvas {state['canvas']}, scrim "
            f"{'auto' if state['scrim'] < 0 else state['scrim']}, fans "
            f"{'on' if state['fans'] else 'off'}, {state['fps']} fps")
        return not refused
