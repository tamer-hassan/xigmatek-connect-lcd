#!/usr/bin/env python3
"""Put the always-on path in front of your eyes: a display process, driven over its socket.

    python3 tools/display_glass.py [--duration 520] [--fps 1] [--theme alpha]
                                   [--device /dev/ttyACM0] [--no-upload]

`tools/gui_glass.py` drives the port directly, one short visit per action.  This
drives the other model, the one the systemd unit runs in: a **separate `xigmalcd`
process** owns /dev/ttyACM0 and draws, and everything here is a client of its
control socket (`xigmalcd/control.py`).  So the phases below are evidence about
the continuous path - counters, `pause`/`resume`, Apply-as-commands, a queued
background upload - and not about the CLI loop that already has glass logs.

Every phase names itself on the glass.  The `title` command sets the heading the
theme draws, so what you see at any moment says which phase put it there; that is
the only labelling this panel can carry, since it has no readback (PROTOCOL.md
§11).  The run prints its own start and end clock, the daemon's counters after
each phase, and the daemon's own log lines with a `daemon|` prefix.

What it checks rather than hopes:

* a window **cut short by `^C` says so**: the phase it stopped in is written into
  the log's own list of what the run did not show, so a stopped run cannot print
  `every phase checked out` about phases it never reached (it once did, during
  the renewal wait);
* the counters are readable by a **second process** while the loop draws: one phase
  runs `python3 -m xigmalcd --status` as its own subprocess, against the socket, and
  that process never opens the port;
* the panel accepts the frames (**counters**, `ok/frames`, not "the loop ran");
* `pause` really is silence: the loop's frame counter must not move at all while
  paused, and the one `frame` command sent in that window must be the only thing
  that moves it;
* `resume` renews (that is the pause repair, PROTOCOL.md §9) and the loop carries
  on drawing afterwards;
* a layout that exists **only as a saved file** is drawn by the loop, and every
  `special` row that file declares comes back with a box.  A row the loop's own
  painter cannot fill fails the phase.  That is the shape of the 2026-11-12 report:
  a released loop painted a saved copy of `alpha` with no `temp-values` and no
  `fan-figures` row, at any colour, while every counter kept moving - because the
  row was not drawn wrong, it was not drawn;
* a queued `upload` is carried out by the loop thread and judged by the panel's
  file notice.  The answer may be no - it was, twice on 2026-11-06, once taken on
  the retry and once refused twice - and a refusal is written down as what the
  panel answered rather than as this path having failed, because the path is the
  thing under test: queued, carried by the loop, verdict read back by the client;
* a session renewal happens on its own at `--session-ttl`, and the run keeps
  going through it - which is the long-horizon claim docs/limits.md makes and has
  never shown for this path;
* `reset` is refused, because the daemon was started without `--allow-reset`.  It
  is asked on purpose and its refusal logged: a gate that is never knocked on is
  not a measured gate.  Nothing here can send `recovery`, and nothing here sends
  anything firmware-shaped.

Keep the artifact: run it with the output going to the ledger, e.g.

    python3 tools/display_glass.py 2>&1 | tee data/glass/$(date +%F-%H%M%S)-socket-run.txt
"""
import argparse
import datetime
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd import control                                        # noqa: E402
from xigmalcd import render                                         # noqa: E402
from xigmalcd import sensors, themes                                # noqa: E402
from xigmalcd.main import DEFAULT_MP4                               # noqa: E402
from xigmaui.panel import port_busy                                 # noqa: E402

PHASES = (("status", "BASELINE", "what the display reports about itself"),
          ("live", "LIVE alpha", "the loop drawing on its own"),
          ("cli", "CLI --status", "the command-line client, port untouched"),
          ("theme", "APPLY gauge", "the window's Apply, sent as commands"),
          ("file", "APPLY a layout file", "a name only a saved JSON answers, drawn by the loop"),
          ("pause", "PAUSED", "silence on the wire; the last picture stays"),
          ("frame", "PAUSED frame", "one frame, asked for while paused"),
          ("resume", "RESUMED", "resume renews and the loop carries on"),
          ("upload", "UPLOAD clip", "queued here, uploaded by the loop"),
          ("gate", "GATE reset", "the socket refuses recovery"),
          ("renewal", "TTL renewal", "the loop renews its own session"),
          ("status", "AFTER", "counters after the whole run"))


def clock() -> str:
    return time.strftime("%H:%M:%S")


def say(msg: str = "") -> None:
    print(msg, flush=True)


def pipe(proc, tag: str) -> None:
    """Mirror the daemon's output, prefixed, so the log shows both halves."""
    for line in proc.stdout:
        say(f"{clock()}  daemon| {line.rstrip()}")


class Display:
    """One running `xigmalcd`, reached only through its socket.

    Nothing here raises: if the display has gone, the calls come back empty and
    the phases below fail their own checks and say so, rather than taking a
    traceback out of a run that is standing in front of a panel.
    """

    def __init__(self, sock: str):
        self.client = control.Client(sock)
        self.path = self.client.path

    def ask(self, obj: dict) -> dict:
        try:
            rep = self.client.ask(obj)
        except control.ControlUnavailable as exc:
            say(f"        {obj.get('cmd')}: {exc}")
            return {"ok": False, "error": str(exc)}
        if not rep.get("ok"):
            say(f"        refused: {rep.get('error')}")
        return rep

    def counters(self) -> dict:
        try:
            return self.client.status()
        except control.ControlUnavailable as exc:
            say(f"        status: {exc}")
            return {}

    def line(self) -> str:
        st = self.counters()
        return control.describe(st) if st else "the display is not answering"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="display_glass",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--socket", default="",
                    help="control socket for the run (default: a private one in "
                         "$XDG_RUNTIME_DIR, so this never talks to the login unit "
                         "by accident)")
    ap.add_argument("--duration", type=float, default=520.0,
                    help="how long the display process runs: it is given "
                         "--duration so it cannot outlive this script")
    ap.add_argument("--fps", type=float, default=1.0,
                    help="the daemon's drawing rate (1 is the vendor's)")
    ap.add_argument("--theme", default="alpha", choices=sorted(render.THEMES))
    ap.add_argument("--baseline", type=float, default=30.0,
                    help="seconds of plain drawing before anything is asked")
    ap.add_argument("--applied", type=float, default=30.0,
                    help="seconds to let the applied settings run")
    ap.add_argument("--paused", type=float, default=20.0,
                    help="seconds to stay paused; the loop must draw nothing")
    ap.add_argument("--resumed", type=float, default=20.0,
                    help="seconds of drawing after resume")
    ap.add_argument("--wait-renewal", type=float, default=330.0,
                    help="seconds to wait for the loop's own session renewal")
    ap.add_argument("--session-ttl", type=int, default=300,
                    help="the daemon's --session-ttl (0 to skip the renewal phase)")
    ap.add_argument("--clip", default=DEFAULT_MP4,
                    help="background to queue over the socket")
    ap.add_argument("--no-upload", action="store_true",
                    help="skip the upload phase (the panel keeps what it has)")
    a = ap.parse_args(argv)

    if a.socket:
        sock = control.socket_path(a.socket)
    else:
        # a name of its own, in the same directory: a driver that found the login
        # unit's socket would be testing that unit's config rather than this run's,
        # and would be arguing with a process that is already drawing.  So the
        # default is never the default socket - and the check below refuses a run
        # if something already answers there.
        base = control.socket_path("")
        sock = os.path.join(os.path.dirname(base), "xigmalcd-glass.sock")
        say(f"-- socket  (not given): using {sock}, not {base}")
    why = port_busy(a.device)
    if why:
        say(f"{why}\nnothing sent: this driver needs the port for its own run.")
        return 2
    if os.path.exists(sock) and control.Client(sock).available():
        say(f"something already answers on {sock}; not starting a second display")
        return 2
    if not os.path.isfile(a.clip):
        say(f"no such clip: {a.clip}")
        return 2

    daemon = [sys.executable, "-u", "-m", "xigmalcd", "--device", a.device,
              "--socket", sock, "--duration", str(a.duration),
              "--fps", str(a.fps), "--theme", a.theme,
              "--session-ttl", str(a.session_ttl),
              "--title", "STARTING"]
    say(f"== display: {' '.join(daemon)}")
    say(f"   socket {sock}")
    proc = subprocess.Popen(daemon, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    threading.Thread(target=pipe, args=(proc, "daemon"), daemon=True).start()

    d = Display(sock)
    deadline = time.monotonic() + a.duration
    problems: list[str] = []      # our path failed to do what it claims
    notes: list[str] = []         # the panel's answers, good or bad

    def until(seconds: float, note: str = "") -> None:
        """Poll during a phase, printing the counters every few seconds."""
        end = time.monotonic() + seconds
        last = 0.0
        while time.monotonic() < end and proc.poll() is None:
            if time.monotonic() - last >= 5.0:
                last = time.monotonic()
                say(f"    {clock()}  {d.line()}")
            time.sleep(0.3)
        if proc.poll() is not None:
            say(f"    the display process exited during {note} "
                f"(code {proc.returncode})")
            problems.append(f"{note}: the display exited")

    def phase(kind: str, title: str, what: str, body) -> None:
        say(f"\n-- {what}  ({kind})  {clock()}")
        if kind not in ("status", "gate"):
            # the heading the theme draws: this panel has no readback, so the
            # only labelling the glass can carry is its own caption (§11)
            d.ask({"cmd": "title", "value": title})
        body()
        say(f"-- {what}: {d.line()}")

    def live_base() -> None:
        until(a.baseline, "baseline")

    def cli_status() -> None:
        out = subprocess.run([sys.executable, "-m", "xigmalcd", "--status",
                              "--socket", sock], capture_output=True, text=True)
        for ln in (out.stdout or out.stderr).splitlines():
            say(f"    --status| {ln}")
        if out.returncode:
            problems.append("--status exited nonzero while the display ran")

    def apply() -> None:
        """The window's Apply button, as the socket speaks it (`daemon.apply`)."""
        t0 = time.perf_counter()
        want = [("theme", "gauge"), ("clock_size", 44),
                ("text_color", "#ffc400"),        # the amber the window offers
                ("bg", "clear"),
                ("scrim", None), ("fans", True), ("fps", a.fps),
                ("title", "APPLY gauge")]
        refused = [cmd for cmd, val in want
                   if not d.ask({"cmd": cmd, "value": val}).get("ok")]
        took = time.perf_counter() - t0
        after = d.ask({"cmd": "status"}).get("status", {})
        say(f"    eight commands in {took * 1000:.0f} ms"
            + (f", refused: {refused}" if refused else "")
            + f"; the display now holds text "
            f"{after.get('text_color') or 'theme default'}")
        until(a.applied, "applied")

    def apply_file() -> None:
        """A layout that only a **saved file** answers, named over the socket.

        `apply` above sends one of the five names this repo draws out of `render.py`.  This
        sends a name that exists nowhere except as JSON in the one writable theme directory -
        the state a person reaches with `save as your copy` in the window, or `themes.save`
        from a script.  The loop reads it back through `themes.resolve` and `themes.paint`,
        the same two doors that put the picture on this panel, and the phase prints what that
        painter found: the file it answered, and one line per `special` row with its box.

        A `special` row with **no box** is the fault this phase was written for.  Reported on
        2026-11-12: a released loop's `themes.paint` filled no value table, so a saved copy of
        `alpha` showed no `temp-values` and no `fan-figures` on the glass while its file said
        nothing wrong - and every counter kept moving, because the row was simply never drawn.
        Nothing in a suite that only asks the pane could see it, so here the missing rows are a
        failed phase, not a sentence.  `notes["missing"]` is what `themes.paint` reports for a
        registered row it could not fill (`xigmalcd/themes.py:_overlay`), and the window prints
        the same list under `--check-theme`.

        Written with the library's own writer and removed again at the end: the theme the
        display held before is put back first, so the glass is never left pointing at a file
        this phase deleted.  A `^C` inside this phase does leave the copy behind - say so in
        the log, because `--list-themes` and the window's `revert` are how you find and drop
        it.  Nothing is read back off the panel (PROTOCOL.md §11): the census is this machine
        counting what its own painter sees, and the glass is what you are looking at.
        """
        name = "xigma-glass-file"
        prev = str((d.ask({"cmd": "status"}).get("status") or {}).get("theme") or a.theme)
        path, soft = themes.save(themes.export("alpha"), name)
        say(f"    the file this phase writes: {path}"
            + (f"; the library's own note: {soft[0]}" if soft else ""))
        got = d.ask({"cmd": "theme", "value": name})
        say(f"    named it over the socket: ok={got.get('ok')}, the display now holds "
            f"theme={((got.get('status') or {}).get('theme'))!r}")
        until(a.applied, "file layout applied")
        rec = themes.resolve(name)
        if rec is None:
            problems.append(f"nothing resolves {name!r}, the file this run wrote")
            return
        say(f"    this machine's resolver answers: {rec['path']}")
        img, notes = themes.paint(rec, sensors.collect(), datetime.datetime.now())
        rows = [(w, b) for kind, w, b, _i in (notes.get("boxes") or []) if kind == "special"]
        alpha = img.getchannel("A")
        for what, box in rows:
            x0, y0, x1, y1 = (max(0, int(v)) for v in box)
            lit = sum(1 for y in range(y0, min(img.height, y1))
                      for x in range(x0, min(img.width, x1)) if alpha[x, y] > 8)
            say(f"      row {what:14s} box={box} ink={lit} px")
        gone = sorted(notes.get("missing") or [])
        say(f"    {len(rows)} special row(s) drawn; rows the painter could not fill: "
            f"{gone or 'none'}")
        if gone:
            problems.append(f"the loop's painter drew no box for {', '.join(gone)}")
        d.ask({"cmd": "theme", "value": prev})
        say(f"    back to {prev!r}, and the copy is removed: "
            f"{themes.delete_user_theme(name) or 'nothing was removed'}")

    def pause() -> None:
        d.ask({"cmd": "pause"})
        before = d.counters()
        until(a.paused, "paused")
        after = d.counters()
        moved = (after.get("frames", 0) - before.get("frames", 0),
                 after.get("ok", 0) - before.get("ok", 0))
        if moved != (0, 0) or not after.get("paused"):
            problems.append(f"pause was not silence: {moved} frames moved")
        say(f"    during {a.paused:.0f} s paused: frames {moved[0]}, uploads "
            f"{moved[1]} (both must be 0), paused={after.get('paused')}")

    def frame_now() -> None:
        before = d.counters()
        d.ask({"cmd": "frame"})
        until(4.0, "paused frame")
        after = d.counters()
        got = after.get("ok", 0) - before.get("ok", 0)
        say(f"    one `frame` while paused: uploads +{got}, still "
            f"paused={after.get('paused')}")
        # worth reading out loud, because it is what the pause repair really is:
        # asking for a frame after an idle gap brings the session up to date
        # first (hello only, unless the gap outlasted --session-ttl), and the
        # display stays paused afterwards - the `frame` is not a `resume`
        for ev in (after.get("events") or [])[-3:]:
            say(f"    event| {ev}")
        if got < 1:
            problems.append("`frame` while paused drew nothing")
        if not after.get("paused"):
            problems.append("`frame` while paused resumed the display: it should "
                            "have stayed paused")

    def resume() -> None:
        before = d.counters()
        d.ask({"cmd": "resume"})
        until(a.resumed, "resumed")
        after = d.counters()
        ren = after.get("renewals", 0) - before.get("renewals", 0)
        drew = after.get("ok", 0) - before.get("ok", 0)
        say(f"    resume: {ren} session renewal(s), {drew} uploads after it")
        if ren < 1 or drew < 1:
            problems.append(f"resume did not renew and draw ({ren}, {drew})")

    def upload() -> None:
        path = os.path.abspath(a.clip)
        rep = d.ask({"cmd": "upload", "path": path})
        if not rep.get("ok"):
            problems.append("upload was refused")
            return
        name = os.path.basename(path)
        say(f"    queued {name} {os.path.getsize(path)} B; pending="
            f"{d.counters().get('pending')!r}")
        # The verdict is the daemon's own event about the file, not the queue
        # slot emptying: `pending` is cleared before the loop thread starts the
        # upload, so waiting on that reads the events too early and would call a
        # file that landed two seconds later a failure.
        end = time.monotonic() + 60
        verdict = None
        while time.monotonic() < end and proc.poll() is None:
            for ev in d.counters().get("events") or []:
                if name in ev and ("accepted" in ev or "did not land" in ev):
                    verdict = ev
                    break
            if verdict:
                break
            time.sleep(0.5)
        for ev in (d.counters().get("events") or [])[-4:]:
            say(f"    event| {ev}")
        if verdict is None:
            problems.append("no verdict for the queued upload inside 60 s: the "
                            "socket path did not report back")
        elif "accepted" not in verdict:
            # A refusal is the panel's answer, not our failure: what this phase
            # exists to show is that the request reached the loop, the loop
            # carried it out, and the panel's verdict came back to the client.
            # Seen twice on 2026-11-06, both ways: taken on the retry at
            # 15:43:26, refused twice at 15:53:11-15:53:12.
            notes.append(f"the panel refused the queued background: {verdict}")
            say(f"    NOTE {verdict}  (the request still went all the way: "
                f"queued, carried by the loop, verdict read back)")
        else:
            say(f"    {verdict}")

    def gate() -> None:
        rep = d.ask({"cmd": "reset"})
        if rep.get("ok"):
            problems.append("reset was NOT refused: the gate is open")
        say(f"    asked for reset on a display without --allow-reset: refused="
            f"{not rep.get('ok')}")

    def renewal() -> None:
        if not a.session_ttl:
            say("    --session-ttl 0: no renewal phase")
            return
        before = d.counters().get("renewals", 0)
        started = time.monotonic()
        last = d.counters()             # the snapshot from before the renewal
        end = started + a.wait_renewal
        while time.monotonic() < end and proc.poll() is None:
            st = d.counters()
            if st.get("renewals", 0) > before:
                # the daemon prints its own figure (`session renewed after N
                # uploads, M s`) on the same log; the two here are what a client
                # can see, which is a session it watched age
                say(f"    renewed on its own after {time.monotonic() - started:.0f} s "
                    f"of watching: the session was {last.get('session_uploads')} "
                    f"uploads / {last.get('session_age', 0):.0f} s old; renewals="
                    f"{st.get('renewals')}")
                until(20.0, "after renewal")
                st2 = d.counters()
                say(f"    still drawing after it: uploads now "
                    f"{st2.get('ok')}/{st2.get('frames')}")
                if st2.get("ok", 0) <= st.get("ok", 0):
                    problems.append("no uploads after the renewal")
                return
            if st:
                last = st
            time.sleep(2.0)
        problems.append(f"no session renewal inside {a.wait_renewal:.0f} s")

    def wait_socket(seconds: float = 20.0) -> bool:
        """The daemon opens the port before it starts listening, so give it time
        to do both.  A run that asked questions before there was a socket would
        spend its first phase failing for a reason that has nothing to do with
        the panel."""
        t0 = time.monotonic()
        end = t0 + seconds
        while time.monotonic() < end:
            if d.client.available():
                say(f"    listening on {d.path} after "
                    f"{time.monotonic() - t0:.1f} s")
                return True
            if proc.poll() is not None:
                say(f"    the display exited (code {proc.returncode}) before it "
                    f"had a socket.  Its own lines above say why.")
                return False
            time.sleep(0.2)
        say(f"    nothing answering on {d.path} after {seconds:.0f} s")
        return False

    start = clock()
    say(f"\n== window on the glass: {start} onward "
        f"(display --duration {a.duration:.0f} s)")
    bodies = {"status": lambda: say(f"    {d.line()}"),
              "live": live_base, "cli": cli_status, "theme": apply,
              "file": apply_file,
              "pause": pause, "frame": frame_now, "resume": resume,
              "upload": upload, "gate": gate, "renewal": renewal}
    # the phase a ^C lands in, so the summary can say which claims this log
    # cannot make: a window stopped during the renewal wait has never seen a
    # renewal, and once printed `== every phase checked out` anyway
    running = [None]
    try:
        if not wait_socket():
            problems.append("the display never had a control socket, so nothing "
                            "was put on the glass by this path")
        for kind, title, what in PHASES:
            if kind == "upload" and a.no_upload:
                say(f"\n-- {what}  ({kind})  skipped (--no-upload)")
                continue
            if proc.poll() is not None:
                say(f"\n-- {what}: the display process exited "
                    f"(code {proc.returncode})")
                problems.append(f"{what}: display exited early")
                break
            running[0] = what
            phase(kind, title, what, bodies[kind])
            running[0] = None
        # cross-check the loop's own arithmetic while it is still answering:
        # everything attempted but not confirmed is a file the panel threw away,
        # and the `refused` counter is supposed to agree with that difference
        final = d.counters()
        lost = final.get("frames", 0) - final.get("ok", 0)
        if lost > 0:
            notes.append(f"the panel threw away {lost} of {final.get('frames')} "
                         f"frames this run; the daemon counts "
                         f"{final.get('refused')} of them as refusals")
    except KeyboardInterrupt:
        say("^C: stopping the display: this window was cut short by the owner")
        if running[0]:
            problems.append(
                f"stopped during {running[0]}: the phases after it never ran, so "
                f"this log says nothing about them")
        else:
            notes.append("stopped by the owner after the last phase: everything "
                         "listed above ran, the display was asked to stop early")
        proc.terminate()
    finally:
        if proc.poll() is None:
            # let it finish its own --duration: the lines it prints on the way out
            # (final counters, the socket closing) belong in this log too
            left = max(0.0, deadline - time.monotonic()) + 15
            say(f"\nwaiting up to {left:.0f} s for the display to finish its own "
                f"--duration")
            try:
                proc.wait(timeout=left)
            except subprocess.TimeoutExpired:
                say("stopping the display process")
                proc.terminate()
                proc.wait(timeout=10)

    say(f"\n== the run: {start} to {clock()}, display exit {proc.returncode}")
    say("   " + "  ".join(f"{what} ({kind})" for kind, _, what in PHASES))
    if notes:
        say("\n== what the panel answered along the way")
        for nt in notes:
            say(f"   * {nt}")
    if problems:
        say("\n== what this run did NOT show")
        for p in problems:
            say(f"   ! {p}")
        return 1
    say("\n== every phase checked out: counters moved, pause was silence, "
        "resume renewed, the queued upload reached the panel and came back with "
        "a verdict, reset was refused, and the loop renewed its own session and "
        "kept drawing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
