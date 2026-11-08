"""Show live system stats on a Xigmatek Connect AIO's in-case LCD.

    python3 -m xigmalcd --theme gauge --fps 1

Frames are drawn locally, uploaded as PNG media files, and the panel shows
the newest one.  Each upload is judged by the panel's own file notice, which is
collected without holding up the picture loop: a frame costs one upload, not a
round trip.  See PROTOCOL.md for the wire format.
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import signal
import sys
import time

from . import control, protocol, render, sensors, themes
from .protocol import Link, ProtocolError, find_ports


def device_info(link, keepalive=60) -> dict:
    try:
        return link.hello(keepalive)
    except ProtocolError as exc:
        print(f"handshake failed: {exc}", file=sys.stderr)
        return {}


PINNED: dict = {}        # last good `--metrics-file` read: a bad edit must not stop the loop
PINNED_MTIME = None      # so the change is logged once, not every frame


def _pinned(args) -> dict:
    """Sections from `--metrics-file`, re-read whenever that file changes.

    The file is a `STATE all 1` body - `{"cpu": {...}, "fans": [...]}` - and each
    section in it replaces that section of the real reading, for the **picture
    only**.  The panel is never handed a number this machine did not measure, so
    a pinned run sends no metrics blob at all: see the `metrics:` line printed at
    session start, and `--state-every` is ignored.  Meant for the cases the
    sensors will not produce on their own - the red end of the gauge ramp, a
    three-digit temperature, a column with no reading - and the log of a window
    like that has to say the numbers were pinned, because nothing on this panel
    reads back.
    """
    global PINNED, PINNED_MTIME
    try:
        mtime = os.stat(args.metrics_file).st_mtime
    except OSError as exc:
        print(f"  ! --metrics-file: {exc}", file=sys.stderr)
        return PINNED
    if mtime == PINNED_MTIME:
        return PINNED
    try:
        with open(args.metrics_file) as fh:
            data = json.load(fh)
        assert isinstance(data, dict), "the file has to be a JSON object"
        # a key starting with `_` is a comment in the file, not a section, so it
        # never reaches the renderer as part of the STATE body
        data = {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as exc:
        print(f"  ! --metrics-file: {type(exc).__name__}: {exc}; "
              f"keeping the last good read", file=sys.stderr)
        PINNED_MTIME = mtime          # so one broken file logs once, not per frame
        return PINNED
    if data != PINNED:
        print("  metrics pinned for the picture (not readings, and not sent to "
              f"the panel): {', '.join(f'{k}.{kk}={vv}' for k, s in data.items()
                                      if isinstance(s, dict)
                                      for kk, vv in s.items()) or data}")
    PINNED, PINNED_MTIME = data, mtime
    return PINNED


def sample(args) -> dict:
    """Read the sensors, with the fan section optional.

    `--metrics-file` replaces whole sections of what is read.  That is a
    rendering override only: `one_frame` and the session-start handshake both
    refuse to push a blob while anything is pinned.
    """
    m = sensors.collect()
    if args.no_fans:
        m.pop("fans", None)
    if getattr(args, "metrics_file", ""):
        m.update(_pinned(args))
    return m


RECOVER_AFTER = 2      # consecutive protocol failures before we try to fix the link
REFUSE_GIVEUP = 6      # 1 400 notices in a row: the panel is answering but will not
                       # take any file, which re-handshaking does not fix (PROTOCOL §6)
SESSION_MAX = 500      # uploads per session before we renew it: the panel goes
                       # silent after ~522 of them at 1 fps
SESSION_TTL = 300      # seconds of session life before we renew it: at 2 fps the
                       # same silence arrives after ~370 s, so watch the clock too


def _repo(*parts):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                        *parts)


WIN_STATIC = "/media/windows-c/Program Files/ALPHA/resources/static/media"
WIN_UPLOADS = ("/media/windows-c/Users/Tamer/AppData/Roaming/alpha/media"
               "/background")
# the vendor app's own state file: the store whose `currentThemeId` picks which
# theme is selected, and whose `textColor` values are counted by the suite (it is
# on the mounted Windows volume, so the check says when it cannot read it)
WIN_STORE = "/media/windows-c/Users/Tamer/AppData/Roaming/alpha/store.json"

# Where this program's own clips are, in the order the spellings win over each
# other.  A package install has to be able to answer this: `pip install .` and
# `apt install xigmatek-connect-lcd` put the code where the checkout is not, and
# `xigmalcd/../media/Theme_25.mp4` then names a file that was never installed.
#
#   $XIGMA_MEDIA                 the one spelling for "use this clip set": the
#                                tests use it, and so can anyone keeping their own
#   <checkout>/media             the repository copy - what runs from a clone, and
#                                what every clip figure in README was read from
#   /usr/share/xigmalcd/media    the Debian/Ubuntu layout: where the .deb puts the
#                                three clips it ships
#
# `media_dir()` is the first that exists, so a clone on a box that also has the
# .deb installed still draws from the clone: otherwise the numbers README quotes
# would depend on what happened to be packaged last.  The clip *library* lists
# every root that exists (xigmaui/clips.py), so an installed themes package is
# not hidden from a display running out of a checkout.
MEDIA_ENV = "XIGMA_MEDIA"
SYSTEM_MEDIA = "/usr/share/xigmalcd/media"
REPO_MEDIA = _repo("media")

# The rest of ALPHA's theme library, as the `xigmatek-connect-lcd-themes` package
# installs it.  It is two things now: a root of the clip *library*, and the layout
# library `--theme <name>` draws from - `xigmalcd/themes.py` finds the files,
# `xigmalcd/layout.py` paints them.  What it is still *not* is anything that goes on
# the wire as itself: the panel is never handed a layout file (PROTOCOL.md §11 reads
# the vendor app's own traffic and finds no such upload), so a library theme is drawn
# here and uploaded as an ordinary `.osd` frame, the same shape a frame of `alpha`
# already is.  The package owns its own directory instead of symlinking clips into
# media/, so removing either package leaves the other's files intact.
SYSTEM_THEMES = "/usr/share/xigmalcd/themes/alpha"


def media_roots() -> tuple:
    """Every clip root that exists, first-winning order, no repeats."""
    roots = []
    env = os.environ.get(MEDIA_ENV)
    if env:
        roots.append(os.path.abspath(env))
    for root in (REPO_MEDIA, SYSTEM_MEDIA):
        if os.path.isdir(root):
            roots.append(os.path.abspath(root))
    return tuple(dict.fromkeys(roots))


def media_dir() -> str:
    """Where a clip name is looked up: the first root that exists, else the
    checkout's, so a missing file is reported as the path this repo says it is."""
    roots = media_roots()
    return roots[0] if roots else REPO_MEDIA


def find_media(name: str, *fallbacks: str) -> str:
    """The first existing file for `name`: the clip roots in order, then the
    Windows volume's copies, then the name under the first root so that a missing
    clip is reported as the file we asked for.  The fallbacks are not decoration:
    the same clip sits on the Windows partition under two different names, and
    which one a frame came from is a fact worth having in the log."""
    for root in (media_roots() or (REPO_MEDIA,)):
        p = os.path.join(root, name)
        if os.path.exists(p):
            return p
    for p in fallbacks:
        if os.path.exists(p):
            return p
    return os.path.join(media_dir(), name)


DEFAULT_MP4 = find_media(
    "Theme_25.mp4",
    # The other half of the theme/background pair ALPHA itself has selected on
    # this machine, so the shipped default reproduces what the vendor app shows
    # rather than a better-looking picture chosen here: store.json says
    # devicesInfo.<sn>.currentThemeBg = media/background/Theme_25.mp4, and
    # 1757491589240.mp4 is a byte-identical copy under the numeric name the
    # media library gives uploads.  214 917 B, 23 frames at 24 fps = a 0.96 s
    # loop, mean luma 18.7 of 255 (dark, which is what white glyphs need), 0
    # black frames.  Measured against the other 39 clips in the vendor's library
    # (each decoded whole, nothing uploaded), its loop seam is 2.50 against 1.51
    # typical motion, so the join is a small jump once per second - a visible
    # imperfection, and the one respect in which this clip is not the best
    # choice.  Accepted because matching the vendor is the point; the two
    # measured-quieter clips are below and `--mp4` reaches them in one flag.
    os.path.join(WIN_UPLOADS, "Theme_25.mp4"),
    os.path.join(WIN_UPLOADS, "1757491589240.mp4"),
    os.path.join(WIN_STATIC, "Theme_25.mp4"),
)
QUIET_MP4 = find_media(
    "Theme_11.mp4",
    # The least obtrusive clip in the same library: 3 402 098 B, 363 frames at
    # 24 fps = a 15.1 s loop, mean luma 13.3-24.1 (dark), 0 black frames, loop
    # seam 0.11 against 2.54 typical motion - the join is smoother than the
    # clip's own motion, i.e. the least visible loop in the library.  Its only
    # cost is size: it uploads in 2.4 s instead of 0.25-0.4 s (PROTOCOL §11).
    # Opt-in: --mp4 media/Theme_11.mp4
    os.path.join(WIN_STATIC, "Theme_11.mp4"),
    os.path.join(WIN_UPLOADS, "Theme_11.mp4"),
)
BRIGHT_MP4 = find_media(
    "theme_48.mp4",
    # The brightest clip in the library and the one ALPHA never pairs with a
    # white-on-transparent theme: 1 333 649 B, 217 frames at 20 fps = a 10.85 s
    # loop, 0 black frames, mean luma 227.3 of 255 - a near-white field under
    # white glyphs - and a loop seam of 4.50 against 0.60 typical motion, so its
    # join is a hard cut.  Vendored so `--mp4 media/theme_48.mp4` is one flag
    # away, and measurable by the fact that the drawing puts a dark plate behind
    # everything it paints for this file (render.scrim, --scrim N).
    os.path.join(WIN_STATIC, "theme_48.mp4"),
    os.path.join(WIN_UPLOADS, "theme_48.mp4"),
)

# Mean luma of each clip on 255, measured by decoding it whole (PROTOCOL.md §9).
# Held here, rather than decoded at startup, because the only thing it decides is
# whether the drawing needs a dark plate behind the glyphs, and a wrong guess
# there is a legibility problem, not a protocol problem.
CLIP_LUMA = {"theme_48.mp4": 227.3, "Theme_11.mp4": 17.5, "Theme_25.mp4": 18.7,
             "Theme_24.mp4": 19.2, "Theme_35.mp4": 7.9, "1757491588831.mp4": 7.9}
SCRIM_ON_BRIGHT = 150       # the plate that makes white glyphs readable there
BRIGHT_LUMA = 128           # where "white-on-white" starts, on 255


def _scrim_for(args) -> int:
    """How much dark plate to paint behind the glyphs, 0-255.

    The glyphs are white by default - ours, and 6 of 6 text colours in the
    layout file of the theme ALPHA has selected - and ALPHA only ever puts
    them over dark clips - which is what the shipped default is, so by default
    nothing is added here and the drawing is the vendor's.  The plate exists for
    the bright opt-in clips: `theme_48.mp4` measures a mean luma of 227.3 of 255,
    a near-white field under white glyphs, and without a plate the reading is
    invisible.  Rule: `--scrim N` always wins; a `--bg black` canvas needs none
    because nothing shows through it; otherwise a clip whose luma was measured
    gets a plate only if it is brighter than mid-grey.  An unmeasured clip gets
    no plate, so `--scrim N` is an explicit thing to ask for.
    """
    if args.scrim is not None:
        return max(0, min(255, args.scrim))
    if not args.mp4 or args.bg == "black":
        return 0
    luma = CLIP_LUMA.get(os.path.basename(args.mp4))
    return SCRIM_ON_BRIGHT if luma is not None and luma > BRIGHT_LUMA else 0


def connect(port, args) -> Link:
    """Open the port and keep a read pending on it (see Link.start_pump).

    The `recovery` guard is decided when the Link is opened, so a display that
    was started with --allow-reset is the only one whose control socket can
    reach it (see control.py)."""
    link = Link(port, args.baud, verbose=args.verbose,
                allow_destructive=getattr(args, "allow_reset", False))
    link.start_pump()
    return link


def rehandshake(link, port, args, reopen=False):
    """Get the panel talking again: re-handshake, and reopen the port if that fails."""
    keep = 0 if args.no_sleep else 60
    try:
        if reopen:
            link.close()
            time.sleep(1.0)
            link = connect(port, args)
        else:
            link.drain()
        link.hello(keep)
        print("  ~ session restored", file=sys.stderr)
    except (ProtocolError, OSError) as exc:
        print(f"  ! session not restored ({exc}); reopening the port",
              file=sys.stderr)
        try:
            link.close()
            time.sleep(1.0)
            link = connect(port, args)
            link.hello(keep)
            print("  ~ port reopened, session restored", file=sys.stderr)
        except (ProtocolError, OSError) as exc2:
            print(f"  ! still failing: {exc2}", file=sys.stderr)
    return link


def refused_by_panel(exc) -> bool:
    """Did the panel's file notice say `1 400`, as opposed to staying quiet?

    The two failures look alike from the outside and are cured by different
    things: a 4xx means the panel is live but rejected this exchange (check the
    upload shape, §6 of PROTOCOL.md), silence means the session is dead, and
    re-opening the port fixes that.
    """
    return "400" in str(exc)


def _canvas(args):
    """Background pixel for a frame: fully transparent, or opaque black.

    Transparent is what the vendor does and therefore what we do: its `.osd`
    frames carry only 4.6 % painted pixels - the arc, the digits, the clock -
    and the panel's stored background keeps playing behind them.  An opaque
    frame covers that layer completely, which is why our first runs over a
    stored MP4 showed a black background (`--bg black` is the old behaviour).
    """
    return render.BLACK if getattr(args, "bg", "clear") == "black" else render.OVERLAY


def _ink_arg(value: str):
    """argparse's `type=` for a text colour: the failure says what to do next."""
    try:
        return render.parse_ink(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def ink_of(args):
    """The display's chosen text colour, or None for the theme's own skin.

    Read as an attribute with a default because a `Control` built from an older
    Namespace - the tests, and a socket client talking to a daemon started
    before this option existed - has no such field, and "no opinion" is the
    right answer for that.
    """
    return getattr(args, "text_color", None)


def _theme_kwargs(args):
    """Render options for the chosen theme, keeping only the ones it takes."""
    kw = {"bg": _canvas(args), "source": args.gauge_source, "ink": ink_of(args),
          "clock": not args.no_clock, "cold": args.cold, "hot": args.hot,
          "title": args.title, "fan": not args.no_fans,
          "clock_size": args.clock_size,
          # the caption follows whatever the arc shows unless it was given
          "label": args.label or ("CPU LOAD" if args.gauge_source == "load"
                                  else "CPU TEMP")}
    if args.cold is None:
        del kw["cold"]                      # let the theme keep its own scale
    if args.hot is None:
        del kw["hot"]
    if args.title is None:
        del kw["title"]           # ditto for the heading: `alpha` has none
    if args.theme not in render.THEMES:
        return {}             # a library theme: its choices are all inside its own file
    params = inspect.signature(render.THEMES[args.theme]).parameters
    return {k: v for k, v in kw.items() if k in params}


def paint(args, metrics, rec=None):
    """One 480x480 overlay, from either half of the theme vocabulary.

    A name in `render.THEMES` is drawn by `render.draw`, with whatever of the render
    options that particular theme accepts.  Any other name is one of ALPHA's layouts,
    painted by `xigmalcd/layout.py` at the canvas the file itself declares; it takes
    none of those options, and `--scrim` is the single exception, because that plate is
    built from the layer's own alpha and needs no per-theme geometry - a library theme
    over a bright clip wants it for the same reason `alpha` does, and docs/limits.md
    keeps the clip luma figures that decided it (`theme_48.mp4`, 227.3 of 255).
    """
    rec = rec if rec is not None else themes.resolve(args.theme)
    if rec is None:
        return render.draw(metrics, args.theme, scrim=_scrim_for(args),
                           **_theme_kwargs(args))
    img, notes = themes.paint(rec, metrics, scrim=_scrim_for(args), base=_canvas(args))
    report(rec, notes)
    return img


_REPORTED: dict = {}


def report(rec: dict, notes: dict) -> None:
    """Say what a library theme drew, once, and again only if it changed.

    A layout names metrics this machine may not have, and a widget that draws nothing
    looks like a broken drawing rather than a missing sensor.  So the skips are printed
    with their reason, and so is every font substitution.  All of it comes out of
    `layout.draw_theme`'s own notes, not out of a summary this file could get wrong.
    """
    faces: dict = {}
    for key, path in (notes.get("fonts") or {}).items():
        faces.setdefault(key.split("/", 1)[0], set()).add(os.path.basename(path))
    here = (tuple(notes.get("missing") or ()),
            tuple(sorted(set(notes.get("gaps") or ()))),
            tuple(f"{fam} -> {'/'.join(sorted(v))}" for fam, v in sorted(faces.items())))
    if _REPORTED.get(rec["name"]) == here:
        return
    _REPORTED[rec["name"]] = here
    missing, gaps, subs = here
    where = ("checkout" if rec["root"] == os.path.abspath(themes.REPO_ROOT)
             else "installed package")
    print(f"  theme {rec['name']} ({rec['id']}): {rec['widgets']} widgets, "
          f"{len(notes.get('boxes') or ())} drawn, layout from the {where}")
    absent = notes.get("absent") or {}
    for src in missing:
        print(f"    skipped {src}"
              + (f" ({absent[src]})" if src in absent else ": no reading for it here"))
    if gaps:
        print("    shaped here, not measured off the vendor's picture: " + ", ".join(gaps))
    if subs:
        print("    faces: " + "; ".join(subs))
    if rec["background"]:
        print(f"    this theme's own background is "
              f"{os.path.basename(rec['background'])} - name it with --mp4; nothing "
              f"here uploads one on its own")


def _png(args, img):
    """Encode a frame: the 256-colour PNG on any canvas, unless `--truecolor`
    asks for 8-bit RGBA.  That default is measured, not assumed - see
    `xigmaui/panel.py`, which has uploaded the indexed file all along, and
    README's encode A/B/A windows, where the owner looked at both shapes on
    real glass and saw no difference.

    What each shape costs, on one ringed `alpha` frame (`tools/selftest.sh`
    prints a live pair; the frame's own seconds clock moves the byte counts by
    a few hundred): RGBA 40.8 KB and bit-exact, indexed 12.2 KB.  Indexed keeps
    a graded alpha - it moves it at ~36 100 of 230 400 pixels by up to 28/255
    and shifts the colour at ~12 700 of them by up to 26 - and the
    half-transparent gauge track survives: 4 029 pixels at alpha 150, all back
    within 11/255, only 16 of them by more than 1.  What it does not keep is
    opacity: the octree path treats RGBA as one four-channel colour, so of
    11 149 pixels drawn fully opaque only 74 still carry alpha 255, and the
    gauge ramp, drawn in 80 colours along its fill, comes back in 13 - one
    flat colour every ~12 px of arc.  None of that read on the glass at the
    size this panel draws: the same frame went up both ways at 1 fps, 61 of 61
    frames both times, 42 560-46 415 B against 12 169-12 401 B."""
    return render.to_png(img, palette=not args.truecolor, colors=args.colors)


def _upload_background(link, args, path: str = ""):
    """Put the theme background MP4 on the panel, as ALPHA does at the start of
    every media session.  The panel stores it and animates the background layer
    under our transparent frames, and the file survives a session renewal; only
    a `recovery` clears it (§9).

    The notice code is the only verdict on whether a file landed.  `space` is
    not: measured across four accepted uploads it moves by a few KB in either
    direction and never resembles the file's size - 65644 -> 59652 -> 56856 for
    the 3.4 MB media/Theme_11.mp4, then 56856 -> 62628 (up) for the 215 KB
    media/Theme_25.mp4.  Report the notice, log `space` for context only.

    Speed, measured on this link: 0.25-2.3 s for 215 KB, 2.4 s for 3.4 MB, so
    clip size is not a constraint even for the vendor's largest files.

    `path` overrides args.mp4: a background asked for over the control socket
    arrives as a path, and it is this thread - the port's only owner - that
    uploads it."""
    path = path or args.mp4
    try:
        blob = open(path, "rb").read()
    except OSError as exc:
        print(f"  ! background {path}: {exc}", file=sys.stderr)
        return False
    before = (link.device_info() or {}).get("space")
    name = os.path.basename(path)
    t = time.monotonic()
    # One retry, because the refusal is positional rather than about the file.
    # Same file, same panel, same shape of session: Theme_25 was refused with
    # `1 400` at 10:17:22 and again at 11:04:01, accepted on the next attempt
    # both times; Theme_11 was refused at 10:34:26 and accepted 5.1 s later.
    # 200 notices on later attempts of the same bytes are the evidence.
    for attempt in (1, 2):
        try:
            res = link.send_media(name, blob, gap=args.gap, chunk=args.chunk,
                                  timeout=90.0)
            break
        except ProtocolError as exc:
            if attempt == 2:
                # A refused background is not a reason to stop drawing: the
                # panel keeps whatever it already has stored, and the OSD layer
                # is a separate file.
                print(f"  ! background {name} ({len(blob)} B): {exc}\n"
                      f"    leaving the panel's stored background as it is "
                      f"(--no-mp4 to skip this upload)", file=sys.stderr)
                return False
            print(f"  background {name} refused ({exc}); retrying once",
                  file=sys.stderr)
            time.sleep(1.0)
    after = (link.device_info() or {}).get("space")
    print(f"background {name} {len(blob)} B -> notice {res.get('notice')} "
          f"in {time.monotonic() - t:.1f} s, space {before} -> {after}",
          file=sys.stderr)
    return str(res.get("notice") or "").startswith("2")


def _run_action(link, port, args, ctl, act):
    """Carry out something a control client asked for, here on the loop thread.

    That is the whole design of control.py: the socket never touches the port,
    it leaves one request in a slot and this thread - the only one that owns
    /dev/ttyACM0 - does it.  Returns the link, which `reset` replaces.

    What a client may not ask for is decided in control.py: no firmware-shaped
    file, and no `recovery` unless the daemon was started with --allow-reset."""
    kind, path = act
    if kind == "upload":
        name = os.path.basename(path)
        if _upload_background(link, args, path):
            ctl.note(f"background {name} accepted")
        else:
            ctl.note(f"background {name} did not land: the panel keeps "
                     f"whatever it already has stored")
        link.drain(0.2)
    elif kind == "reset":
        # only reachable with --allow-reset; the vendor's reset re-enumerates
        # the USB device, so the fd we hold dies under us (PROTOCOL.md §9)
        print("  ! recovery requested over the control socket", file=sys.stderr)
        try:
            link.post("recovery", {"enable": True})
        except (ProtocolError, OSError) as exc:
            ctl.note(f"recovery: {exc}")
        time.sleep(2.0)
        link = rehandshake(link, port, args, reopen=True)
        ctl.note("recovery sent and the session rebuilt: the panel's stored "
                 "background is gone, re-upload a clip if you want one back")
    return link


def _run_action(link, port, args, ctl, act):
    """Carry out something a control client asked for, here on the loop thread.

    That is the whole design of control.py: the socket never touches the port,
    it leaves one request in a slot and this thread - the only one that owns
    /dev/ttyACM0 - does it.  Returns the link, which `reset` replaces.

    What a client may not ask for is decided in control.py: no firmware-shaped
    file, and no `recovery` unless the daemon was started with --allow-reset."""
    kind, path = act
    if kind == "upload":
        name = os.path.basename(path)
        if _upload_background(link, args, path):
            ctl.note(f"background {name} accepted")
        else:
            ctl.note(f"background {name} did not land: the panel keeps "
                     f"whatever it already has stored")
        link.drain(0.2)
    elif kind == "reset":
        # only reachable with --allow-reset; the vendor's reset re-enumerates
        # the USB device, so the fd we hold dies under us (PROTOCOL.md §9)
        print("  ! recovery requested over the control socket", file=sys.stderr)
        try:
            link.post("recovery", {"enable": True})
        except (ProtocolError, OSError) as exc:
            ctl.note(f"recovery: {exc}")
        time.sleep(2.0)
        link = rehandshake(link, port, args, reopen=True)
        ctl.note("recovery sent and the session rebuilt: the panel's stored "
                 "background is gone, re-upload a clip if you want one back")
    return link


def one_frame(link, metrics, args, push_state=False) -> tuple[int, str, str]:
    """Render one frame, put it on the wire, and return (bytes, name, verdict).

    The verdict is the panel's own file notice, and it is asked for as part of
    the upload: `Link.send_media(order="notice")` holds `transported` back until
    the notice has landed, which is the order ALPHA's traffic has it in.  That
    ordering is what makes the panel redraw the picture once a second - send
    `transported` straight after the last file byte and the panel answers the
    upload but answers the confirmation only once in six, and the on-screen
    picture crawls at one change every few seconds (PROTOCOL.md §6, §9).

    The wait costs 30-50 ms of the frame slot, which at 1 Hz is nothing.
    """
    png = _png(args, paint(args, metrics))
    name = render.frame_name()
    if push_state:
        if args.metrics_file:
            print("  ! --state-every skipped: metrics are pinned, and a pinned "
                  "blob would put unmeasured numbers on the wire", file=sys.stderr)
        else:
            try:
                link.state_all(metrics)
            except ProtocolError as exc:
                print(f"  ! metrics ack: {exc}", file=sys.stderr)
    out = link.send_media(name, png, gap=args.gap, chunk=args.chunk,
                          wait=args.order == "fast", order=args.order)
    return len(png), name, str(out.get("notice") or "")


def theme_name(value: str) -> str:
    """Validate `--theme`: one of the five drawn here, or a pickable library layout.

    A refused name is answered with the reason rather than with the whole vocabulary:
    four of the 27 copied layouts are refused on canvas alone, and argparse's stock
    "invalid choice" message would bury that under 27 spellings.  `themes.why_not()` is
    the one place that knows why, and `--list-themes` prints it for all of them.
    """
    if value in render.THEMES:
        return value
    rec = themes.resolve(value)
    if rec is None:
        raise argparse.ArgumentTypeError(themes.why_not(value))
    return rec["name"]        # the canonical spelling, so a lowercase answer on the
    # socket, in `status`, and in a log line all read the same way (`theme_07` typed at
    # the prompt is `Theme_07` everywhere afterwards)


def build_parser() -> argparse.ArgumentParser:
    """The whole command line, in one place: `--help` reads it and the
    offline checks can parse it instead of guessing at the flags."""
    ap = argparse.ArgumentParser(prog="xigmalcd", description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", help="serial port (default: first ttyACM)")
    ap.add_argument("-b", "--baud", type=int, default=115200)
    ap.add_argument("-t", "--theme", default="alpha", metavar="THEME", type=theme_name,
                    help="picture to draw: one of the five this program draws itself "
                         "(alpha, bars, clock, dual, gauge - default alpha, the theme "
                         "the vendor app currently has selected, redrawn from its "
                         "stored geometry with a second temperature inside a gauge "
                         "arc, clock and fan figures added) - or one of ALPHA's own "
                         "library themes, named by its background (Theme_07) and "
                         "painted by xigmalcd/layout.py from that theme's own layout "
                         "file. --list-themes prints both sets, and why four layouts "
                         "are refused")
    ap.add_argument("-f", "--fps", type=float, default=1.0,
                    help="frames per second (the panel takes 3 without refusing; "
                         "1 fps is what the vendor app does)")
    ap.add_argument("--duration", type=float, default=0,
                    help="stop after N seconds (0 = run forever)")
    ap.add_argument("--once", action="store_true", help="push a single frame")
    ap.add_argument("--dry-run", metavar="DIR",
                    help="only write PNGs here, never touch the serial port")
    ap.add_argument("--no-state", action="store_true",
                    help="skip the STATE all 1 metrics blob at startup")
    ap.add_argument("--state-every", type=int, default=0,
                    help="also refresh metrics every Nth frame. ALPHA never "
                         "does this: the panel stops answering the media "
                         "channel if it is fed metrics continuously")
    ap.add_argument("--no-sleep", action="store_true",
                    help="tell the panel never to blank the display "
                         "(timeout value 0 instead of 60 s of idle time)")
    ap.add_argument("--session-max", type=int, default=SESSION_MAX,
                    help="renew the serial session after this many uploads "
                         "(the panel goes silent after ~522; 0 disables)")
    ap.add_argument("--session-ttl", type=int, default=SESSION_TTL,
                    help="also renew the session after this many seconds, since "
                         "the silence also arrives on a ~370 s clock when pushing "
                         "2 fps (0 disables)")
    ap.add_argument("--no-fans", action="store_true",
                    help="leave fans out entirely: no `fans` section in the "
                         "metrics blob and no fan figures on the picture")
    ap.add_argument("--metrics-file", metavar="PATH", default="",
                    help="draw the picture from the sections of a JSON `STATE all "
                         "1` body instead of this machine's readings, re-read "
                         "whenever the file changes. For the cases the sensors "
                         "will not produce: the red end of the gauge ramp, a "
                         "three-digit temperature, a column with no reading. The "
                         "override is for the picture only - while anything is "
                         "pinned no metrics blob is sent at all, and "
                         "`--state-every` is skipped, so the panel is never "
                         "handed a number this machine did not measure")
    ap.add_argument("--truecolor", action="store_true",
                    help="upload 8-bit RGBA PNGs instead of the 256-colour file "
                         "that is the default on every canvas.  Costs about 3.4x "
                         "the bytes (42-46 KB against 12-13 KB for a ringed "
                         "`alpha` frame, both measured on glass) and buys an "
                         "exact alpha; the eye did not notice the difference "
                         "(`--palette` spells out the default, `--truecolor` "
                         "wins if both are given)")
    ap.add_argument("--palette", action="store_true",
                    help="the 256-colour PNG, spelled out: already the default, "
                         "over a transparent canvas as over an opaque one, "
                         "which is what xigmaui/panel.py has always uploaded.  "
                         "12.2 KB against 40.8 KB for the ringed `alpha` frame, "
                         "the gauge ramp quantised from 80 drawn colours to 13, "
                         "and no difference seen on glass")
    ap.add_argument("--bg", choices=("clear", "black"), default="clear",
                    help="canvas under the glyphs: transparent, so the panel's "
                         "own stored background keeps playing behind them "
                         "(what ALPHA does), or opaque black")
    ap.add_argument("--gauge-source", choices=("temperature", "load"),
                    default="temperature",
                    help="what the gauge arc follows. ALPHA follows CPU "
                         "temperature, and the honest consequence is that it "
                         "barely moves on an idle desktop CPU (over its 65 "
                         "captured frames the tip travelled 14 degrees in "
                         "43 s); 'load' follows CPU busy percent, which does "
                         "move every second")
    ap.add_argument("--cold", type=float, default=None,
                    help="gauge arc's bottom of scale (default: the theme's, "
                         "30 for the stock skin, as measured off ALPHA)")
    ap.add_argument("--hot", type=float, default=None,
                    help="gauge arc's top of scale (default 75: that is where "
                         "ALPHA's 57 deg C reading puts its tip, at 60 percent "
                         "of the sweep)")
    ap.add_argument("--title", default=None,
                    help="heading across the top of the picture; with no "
                         "--title a theme uses its own (gauge: 'Smart "
                         "Display', dual: 'CPU / GPU', alpha: none)")
    ap.add_argument("--label", default=None,
                    help="small caption under the gauge (default: CPU TEMP, or "
                         "CPU LOAD when --gauge-source load)")
    ap.add_argument("--no-clock", action="store_true",
                    help="leave the clock off the picture")
    ap.add_argument("--text-color", type=_ink_arg, default=None,
                    metavar="COLOUR",
                    help="the ink of the text this program draws, by name "
                         "(amber, mint, cyan, white...) or #rrggbb. Unset keeps "
                         "each theme's own skin, which for `alpha` is the "
                         "white measured off its captured frames (PROTOCOL.md "
                         "SS10). The vendor's themes keep their text colour in "
                         "their own files, which nothing here sends, so this "
                         "changes our layer only - and the frame is uploaded as "
                         "pixels, so it changes what the panel shows without "
                         "changing any setting inside it")
    ap.add_argument("--clock-size", type=int, default=26, metavar="N",
                    help="clock height in pixels for themes that draw one "
                         "(default 26 of the panel's 480, i.e. 5.4%% of its "
                         "height: legible at arm's length, not across a room)")
    ap.add_argument("--mp4", metavar="PATH", nargs="?", const=DEFAULT_MP4,
                    default=DEFAULT_MP4,
                    help="upload a 480x480 H.264 MP4 as the panel's background "
                         "layer at session start, as ALPHA does with its theme "
                         "background. On by default with media/Theme_25.mp4: the "
                         "clip ALPHA itself pairs with the theme this program "
                         "redraws (215 KB, 23 frames, a 0.96 s loop, mean luma "
                         "18.7 of 255, no black frames). Where that file is "
                         "looked up, in order: $XIGMA_MEDIA, this checkout's "
                         "media/, and /usr/share/xigmalcd/media/ (what the .deb "
                         "installs) - the first that exists. Its measured "
                         "weakness is "
                         "the loop join, 2.50 against 1.51 typical motion, i.e. "
                         "a small jump once per second. Vendored alternatives, "
                         "one flag away: media/Theme_11.mp4 (3.4 MB, 15.1 s, "
                         "luma 13-24, join 0.11 against 2.54, the quietest in the "
                         "vendor's library) and media/theme_48.mp4 (1.33 MB, "
                         "10.85 s, luma 227 - nearly white under white glyphs)")
    ap.add_argument("--scrim", type=int, default=None, metavar="A",
                    help="alpha 0-255 of the dark plate drawn behind the glyphs. "
                         "Unset means automatic: nothing over the shipped dark "
                         "default (mean luma 18.7 of 255), so the picture is what "
                         "the vendor draws, and 150 over a clip measured brighter "
                         "than mid-grey - media/theme_48.mp4 is 227, i.e. white on "
                         "white without it. 0 for --bg black; --scrim 0 turns the "
                         "plate off whatever the clip, and an unmeasured clip gets "
                         "no plate unless you ask for one here")
    ap.add_argument("--no-mp4", action="store_false", dest="mp4",
                    default=DEFAULT_MP4,
                    help="do not upload a background: keep whatever the panel "
                         "already has stored")
    ap.add_argument("--overlay", action="store_true",
                    help="same as --bg clear, which is now the default")
    ap.add_argument("--colors", type=int, default=256, help="palette size")
    ap.add_argument("--order", choices=("notice", "fast"), default="notice",
                    help="when `transported` goes out: after the panel's own "
                         "file notice (the way ALPHA does it, and the only way "
                         "that makes the picture redraw every second) or right "
                         "after the last file byte (the old way)")
    ap.add_argument("--chunk", type=int, default=protocol.MEDIA_CHUNK,
                    help="raw upload chunk size (ALPHA writes 1000-byte blocks)")
    ap.add_argument("--gap", type=float, default=protocol.MEDIA_GAP,
                    help="one pause per upload, between the transfer "
                         "announcement and the first file byte (the vendor's "
                         "is 0.01-0.02 s). Do not set it to 0 for a loop: at "
                         "3 fps with no pause the panel accepted 0 of 128 "
                         "uploads, while the same run at 0.02 s took 361 of "
                         "361 (PROTOCOL.md §6)")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--status", action="store_true",
                    help="ask the display that is already running what it is "
                         "showing, print it, and exit: one line on its control "
                         "socket, the serial port never opened")
    ap.add_argument("--socket", metavar="PATH", default="",
                    help="control socket to listen on while drawing "
                         "(default: $XDG_RUNTIME_DIR/xigmalcd.sock).  Only one "
                         "process can hold the port, so this is how the desktop "
                         "app changes a display that is already running: it "
                         "sends JSON lines here and this loop carries them out")
    ap.add_argument("--no-control", action="store_true",
                    help="do not listen on a control socket at all")
    ap.add_argument("--allow-reset", action="store_true",
                    help="let the control socket send `recovery`.  It "
                         "re-enumerates the USB device and drops the stored "
                         "background, so it is off by default and "
                         "xigmalcd-reset --yes (tools/reset_panel.py --yes in "
                         "a checkout) is the deliberate way")
    ap.add_argument("--list", action="store_true",
                    help="list candidate serial ports and exit")
    ap.add_argument("--export-theme", metavar="NAME",
                    help="print the generated layout for one of the five themes this "
                         "program draws itself, as JSON on stdout: the same file shape "
                         "ALPHA's library uses, so it can be read back, edited, and "
                         "drawn by the same code. Generated on demand and never "
                         "committed - a committed gauge.json goes stale the first time "
                         "anyone edits theme_gauge. Nothing is written to disk and "
                         "nothing here goes near the panel")
    ap.add_argument("--print-theme-fields", action="store_true",
                    help="print the field census an inspector is built from: every key "
                         "the vendor's widgets carry, per kind, and for each one whether "
                         "this program reads it, does not read it, or reads it with no "
                         "vendor file to show. Counted over the vendor's own trees, so "
                         "your copies cannot move these numbers. No port is opened")
    ap.add_argument("--check-theme", metavar="NAME",
                    help="report one theme the way the loop will see it: the file's own "
                         "accounting (widgets, what draws, what is skipped and why), plus "
                         "the warnings worth hearing before an edit - an unknown metric "
                         "name, a size outside the ten the shipped library uses, a colour "
                         "that is not the rgba() spelling, a widget off the canvas")
    ap.add_argument("--list-specials", action="store_true",
                    help="print the names a `special` widget may carry: the parts of "
                         "our own themes that stay code-drawn and take their position, "
                         "size and colour from a layout")
    ap.add_argument("--list-themes", action="store_true",
                    help="list every theme `--theme` can be given: the five drawn "
                         "from render.py, then ALPHA's 1:1 layouts with their widget "
                         "counts and where each file came from, then the layouts "
                         "refused and why. No port is opened")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.overlay:                          # kept for old command lines
        args.bg = "clear"

    if args.print_theme_fields:
        cen = themes.field_census()
        read, sub = themes.keys_read()
        kinds = sorted(cen["kinds"])
        ok_n, out_n = len(themes.scan()[0]), len(themes.scan()[1])
        by_count = sorted(kinds, key=lambda k: (-cen["kinds"][k], k))
        print(f"  field census        {cen['widgets']} widgets in the vendor's "
              f"{ok_n + out_n} layouts (" +
              ", ".join(f"{k} {cen['kinds'][k]}" for k in by_count) + "); "
              f"{len(cen['keys'])} distinct `property` keys")
        head = "  " + "key".ljust(20) + "".join(k.rjust(6) for k in kinds)
        print(head + "   read by layout.py")
        both = sorted(set(read) & set(cen["keys"]))
        for k in both:
            row = "  " + k.ljust(20)
            row += "".join(str(cen["keys"][k].get(kk, 0)).rjust(6) for kk in kinds)
            print(row + "   yes")
        print(f"  read by this program, carried by no vendor file "
              f"({len(set(read) - set(cen['keys']))}): " + ", ".join(
                  sorted(set(read) - set(cen["keys"]))) +
              " - `name` picks a drawing out of --list-specials, `xigma` is our own "
              "theme-level block, and lineColor/lineWidth are the line ink measured off "
              "the two overlays that have a line rather than out of a file")
        print(f"  our own keys inside `xigma` ({len(sub)}), each with the reason it had "
              f"to be added:")
        for k in sub:
            print(f"    {k:<14} {themes.XIGMA_KEYS[k]}")
        print(f"                        that list is read out of `layout.py` with `ast`: "
              f"a key nobody wrote a reason for still shows up here, and the suite fails "
              f"when the two sets disagree")
        unread = sorted(set(cen["keys"]) - set(read))
        print(f"  carried by vendor files, never read here ({len(unread)}), with what the "
              f"value would have done:")
        tpf = cen["time_per_file"]
        for k in unread:
            vals = cen["values"][k]
            if k == "time":
                # the interesting fact is not which timestamps, it is that every widget in
                # one file answers the same one, and no two files answer the same
                top = (f"{len(vals)} distinct over {cen['widgets']} widgets, and "
                       f"{sum(1 for n in tpf.values() if n == 1)} of the {len(tpf)} files "
                       f"answer exactly one of them inside itself")
            else:
                top = ", ".join(f"{v!r} on {n}" for v, n in
                                sorted(vals.items(), key=lambda kv: -kv[1])[:3])
                top += f" (+{len(vals) - 3} more)" if len(vals) > 3 else ""
            print(f"    {k:<18} {top}   - {themes.UNREAD_WHY[k]}")
        print(f"  why the counts matter  a key this program does not read still survives a "
              f"save untouched, so an edited file keeps every field the vendor's own editor "
              f"put in it; and the two that would change how text looks (`italic`, "
              f"`underline`) are one value deep on every widget that carries them, so "
              f"nothing is missing from the picture by leaving them unread")
        return 0

    if args.check_theme:
        # report one theme exactly as the loop will meet it: the file's own accounting,
        # the warnings worth hearing before an edit, and what this machine can answer
        metrics = sensors.collect()
        rec = themes.resolve(args.check_theme)
        if rec is not None:
            obj = themes.load(rec["path"])
            print(f"  {rec['name']} ({rec['id']}): {rec['w']}x{rec['h']} ratio "
                  f"{rec['ratio']}, {rec['widgets']} widgets, from {themes.origin(rec)}")
        elif args.check_theme in themes.EXPORTS:
            obj = themes.export(args.check_theme)
            print(f"  {args.check_theme}: generated from render.py, "
                  f"{len(obj['osd']['widget'])} widgets, every reading named by "
                  f"`source`")
        elif args.check_theme in render.THEMES:
            print(f"  {args.check_theme}: drawn from render.py by code, and no layout "
                  f"export for it yet - {' '.join(sorted(themes.EXPORTS))} have one "
                  f"(docs/theme-editor.md says what each still needs)")
            return 0
        else:
            print(f"  {themes.why_not(args.check_theme)}", file=sys.stderr)
            return 2
        hard, soft = themes.validate(obj)
        for note in hard:
            print(f"  will not draw: {note}")
        for note in soft:
            print(f"  warning: {note}")
        img, notes = themes.draw(obj, metrics)
        lit = sum(1 for v in img.getchannel("A").get_flattened_data() if v)
        print(f"  drawn from this machine's readings: {len(notes['boxes'])} boxes, "
              f"{lit} lit px, skipped: "
              + (", ".join(notes["missing"]) if notes["missing"] else "nothing"))
        if notes["gaps"]:
            print("  shaped by this repo rather than measured off the vendor's "
                  "picture: " + ", ".join(sorted(set(notes["gaps"]))))
        asked = sorted({(w.get("property") or [{}])[0].get("source")
                        for w in obj["osd"]["widget"]
                        if (w.get("property") or [{}])[0].get("source")})
        if asked:
            cannot = [s for s in asked if s in notes.get("absent", {})]
            answers = [s for s in asked if s not in notes.get("absent", {})]
            print("  this theme asks for: " + ", ".join(asked))
            print("  this machine answers: " + (", ".join(answers)
                                                if answers else "none of them"))
            if cannot:
                print("  and cannot: " + ", ".join(cannot))
        return 0 if not hard else 2


    if args.list_specials:
        for name in themes.special_names():
            print(f"  {name}")
        print("  A special is drawn by code and placed by the layout: see "
              "xigmalcd/themes.SPECIALS and docs/theme-editor.md.")
        return 0

    if args.export_theme:
        try:
            obj = themes.export(args.export_theme)
        except KeyError as exc:
            print(f"  {exc.args[0]}", file=sys.stderr)
            return 2
        # sorted keys and no generated-at-run-time values: two runs of this command are
        # byte-identical, which is what the suite gate compares
        print(json.dumps(obj, indent=1, sort_keys=True))
        return 0

    if args.list_themes:
        # read off the filesystem, not out of a table kept by hand, so the counts in
        # this listing are the reason docs/theme-editor.md can state what is runnable
        # instead of estimating it
        print("  drawn here (render.py):  " + " ".join(sorted(render.THEMES)))
        for line in themes.census():
            print(line)
        ok, out = themes.scan()
        print(f"  {len(ok)} pickable, {len(out)} refused on canvas alone")
        used = themes.sources_used(ok)
        print("  sources the pickable set asks for: "
              + ", ".join(f"{k} {v}" for k, v in sorted(used.items(),
                                                        key=lambda kv: (-kv[1], kv[0]))))
        for src, why in sorted(themes.UNMAPPED.items()):
            if src in used:
                print(f"    {src}: {used[src]} widget(s) ask for it and there is no "
                      f"reading for it here - {why}")
        unmeasured = sorted(s for s in used if s not in themes.formats_measured())
        if unmeasured:
            print("    formats taken from this repo, not measured off the vendor's own "
                  "picture: " + ", ".join(unmeasured))
        yours = themes.user_copies()
        if yours:
            print(f"  your copies, read before the vendor's: {' '.join(yours)} "
                  f"(from {themes.user_root()}; a copy of a name the library also has "
                  f"shadows it, and --check-theme reports which one is drawing)")
        else:
            print(f"  nothing saved yet: a theme written to {themes.user_root()} is "
                  f"read before the vendor's copy of the same name, and "
                  f"--check-theme NAME says which file is drawing. The editor that "
                  f"writes one is stage 4 of docs/theme-editor.md")
        return 0

    if args.list:
        for port, prod in find_ports():
            print(f"{port}\t{prod}")
        if not find_ports():
            print("no /dev/ttyACM* ports found")
        return 0

    if args.status:
        # a read of another process's counters, and the only thing that can be
        # asked without owning the port: no serial open anywhere on this path
        client = control.Client(args.socket)
        try:
            st = client.status()
        except control.ControlUnavailable as exc:
            print(f"no display answering on {client.path}: {exc}\n"
                  f"(start one: python3 -m xigmalcd --theme alpha --fps 1)",
                  file=sys.stderr)
            return 1
        print(control.describe(st))
        print(f"  settings: theme {st.get('theme')}, canvas {st.get('canvas')}, "
              f"clock {st.get('clock_size')}, scrim "
              f"{'auto' if st.get('scrim') is None else st.get('scrim')}, text "
              f"{st.get('text_color') or 'theme default'}, "
              f"title {st.get('title') or '-'}")
        print(f"  counters: {st.get('ok')}/{st.get('frames')} uploads the panel "
              f"confirmed, {st.get('refused')} refused, {st.get('errors')} link "
              f"errors, {st.get('renewals')} session renewals, this session "
              f"{st.get('session_uploads')} uploads "
              f"{st.get('session_age', 0):.0f} s old")
        for ev in st.get("events") or []:
            print(f"  {ev}")
        return 0

    if args.dry_run:
        os.makedirs(args.dry_run, exist_ok=True)
        deadline = time.monotonic() + args.duration if args.duration else 0
        n = 0
        while True:
            m = sample(args)
            png = _png(args, paint(args, m))
            path = os.path.join(args.dry_run, f"frame{n:04d}.png")
            with open(path, "wb") as fh:
                fh.write(png)
            print(f"{path}  {len(png)} bytes")
            n += 1
            if args.once or (deadline and time.monotonic() >= deadline):
                return 0
            time.sleep(max(0.0, 1.0 / args.fps))

    port = args.device
    if not port:
        found = find_ports()
        if not found:
            print("no /dev/ttyACM* port found; is the cooler plugged in?",
                  file=sys.stderr)
            return 2
        port = found[0][0]
        if len(found) > 1:
            print(f"several ports, using {port} ({found[0][1]})")

    stop = []
    signal.signal(signal.SIGINT, lambda *_: stop.append(True))
    signal.signal(signal.SIGTERM, lambda *_: stop.append(True))

    print(f"opening {port} at {args.baud}")
    try:
        link = connect(port, args)
    except OSError as exc:
        print(f"cannot open {port}: {exc}\n"
              f"(check permissions: user in the dialout group)",
              file=sys.stderr)
        return 2
    ctl = control.Control(args, port, allow_reset=args.allow_reset)
    srv = None
    if not args.no_control and not args.once:
        # A single frame has nothing to control, and a socket left behind by a
        # finished run would only invite a client to knock on a dead link.
        srv = control.Server(ctl, args.socket)
        if srv.start():
            print(f"control socket {srv.path}: other programs talk to this "
                  f"process, not to {port}")
        else:
            print(f"! control socket not listening: {srv.error}",
                  file=sys.stderr)
    try:
        info = device_info(link, 0 if args.no_sleep else 60)
        if info:
            v = info.get("version", {})
            print(f"device: sn={info.get('sn')} app={v.get('app')} "
                  f"fw={v.get('firmware')} space={info.get('space')} "
                  f"brightness={info.get('brightness')}")
            ctl.publish(device={
                "sn": info.get("sn"), "space": info.get("space"),
                "brightness": info.get("brightness"), "logo": info.get("logo"),
                "mode": info.get("mode"), "osdState": info.get("osdState"),
                "timeout": info.get("timeout"), "app": v.get("app"),
                "firmware": v.get("firmware")})
        if args.metrics_file:
            # the one thing a drawing session normally does before its files is
            # push the machine's numbers.  Not when they are pinned: the panel
            # would be handed readings this machine never took, and the log would
            # then look like every other window in data/glass/.
            print("metrics: PINNED from --metrics-file, so no `STATE all 1` blob "
                  "is sent at all - the panel gets no number this machine did "
                  "not measure, and only the drawn picture uses the pinned ones")
            sample(args)                    # first read, so the pin is logged now
        elif not args.no_state:
            # ALPHA reports the machine twice at startup and afterwards only
            # pushes pictures; the panel stops answering transfers when it is
            # fed metrics continuously, so we follow the same pattern.
            boot = sample(args)
            for _ in range(2):
                link.state_all(boot)
                time.sleep(0.05)
            link.drain()
            # said out loud, because it is the one thing a drawing session does
            # before its files and the glass ledger in README counts on it
            fans = "with" if boot.get("fans") is not None else "without"
            print("metrics: `STATE all 1` twice at session start, then left "
                  f"alone ({fans} the fans array)")
        if args.mp4:
            # ALPHA uploads its theme background first, every media session:
            # that is the layer our transparent frames sit on (§9).  Measured on
            # this link, an accepted upload of either vendored clip returns its
            # notice in 0.25-2.4 s, so it is not repeated on a session renewal
            # only because the panel keeps the file.
            #
            # Said into the control ring as well as into stderr, because the
            # panel cannot be asked what it stores (§11) and a client that
            # connects an hour later has no other way to learn it: the window
            # shows this line as "the panel stores …".  Before it, the ring was
            # empty until someone pressed an upload button, so the honest answer
            # to "which background is on the glass" was "I do not know".
            name = os.path.basename(args.mp4)
            if _upload_background(link, args):
                ctl.note(f"background {name} accepted at session start: this is "
                         f"what the panel stores under our frames")
            else:
                ctl.note(f"background {name} did not land at session start: the "
                         f"panel keeps whatever it already had")
            link.drain(0.2)
        deadline = time.monotonic() + args.duration if args.duration else 0
        n = ok = bad = bad_refused = 0
        refused = 0                       # total 4xx notices, not the streak
        renewals = 0
        since_renew = time.monotonic()
        since_ok = 0                      # `ok` at the last renewal
        size, name, code, last_err = 0, "", "", ""

        def publish() -> None:
            """Hand the loop's numbers to the control socket's snapshot.

            Written here, on the loop thread, and copied under a lock by
            `Control.status()`: a client reading mid-upload never sees a
            counter updated underneath it."""
            ctl.publish(frames=n, ok=ok, refused=refused, errors=bad,
                        renewals=renewals, last_bytes=size, last_name=name,
                        last_notice=code, last_error=last_err,
                        session_uploads=ok - since_ok,
                        session_age=time.monotonic() - since_renew)

        was_paused = False
        while not stop:
            started = time.monotonic()
            act = ctl.take()
            if act:
                link = _run_action(link, port, args, ctl, act)
                if act[0] == "reset":
                    since_renew = time.monotonic()
                    since_ok = ok
            force = bool(act) and act[0] == "frame"
            if ctl.paused and not force:
                # nothing goes out on the wire at all while paused, so the
                # session clock is not the panel's any more than ours
                was_paused = True
                publish()
                time.sleep(0.25)
                continue
            if was_paused:
                was_paused = False
                idle = time.monotonic() - since_renew
                # how long the link sat with no bytes on it decides the repair:
                # past our own session TTL the session is the one measured to go
                # silent (~370 s at 2 fps), and re-opening the port is the only
                # thing that has ever revived that.  A short pause only needs
                # the hello, which is also what wakes a blanked panel.
                link = rehandshake(link, port, args, reopen=idle >= args.session_ttl)
                since_renew = time.monotonic()
                since_ok = ok
                renewals += 1
                ctl.note(f"resumed after {idle:.0f} s idle: session renewed")
            if (args.session_max and ok - since_ok >= args.session_max) or \
               (args.session_ttl and time.monotonic() - since_renew >= args.session_ttl):
                # renew on purpose, before the panel's own limit bites: closing and
                # re-opening the port is the only thing that revives a dead session
                print(f"session renewed after {ok - since_ok} uploads, "
                      f"{time.monotonic() - since_renew:.0f} s", file=sys.stderr)
                link = rehandshake(link, port, args, reopen=True)
                since_renew = time.monotonic()
                since_ok = ok
                renewals += 1
            metrics = sample(args)
            try:
                push = bool(args.state_every) and n % max(1, args.state_every) == 0
                size, name, code = one_frame(link, metrics, args, push_state=push)
                last_err = ""
                if code.startswith("2"):
                    ok += 1
                    bad_refused = 0
                elif code:
                    bad_refused += 1
                    refused += 1
                    print(f"  ! frame {n}: panel refused {name} with {code}",
                          file=sys.stderr)
                    if bad_refused >= REFUSE_GIVEUP:
                        print(
                            "the panel keeps refusing files: the handshake and "
                            "the commands work, but every upload gets a 1 400 "
                            "notice.\nUpload shape is the usual cause - the "
                            "announcement, the file and the confirmation must "
                            "go out as one burst, the transport frame needs its "
                            "ContentLength header, and the confirmation belongs "
                            "after the panel's own notice (PROTOCOL.md §6).",
                            file=sys.stderr)
                        ctl.note("stopped: the panel answered but refused every "
                                 "upload, so this process is letting go of the "
                                 "port")
                        publish()
                        return 3
                # the verdict is already in hand; this only keeps the acks of
                # other commands from piling up in the reader's queue
                link.harvest()
                if args.verbose or n % 10 == 0:
                    cpu = metrics.get("cpu", {}).get("temperature")
                    print(f"frame {n}: {size} bytes, {ok} confirmed, cpu={cpu}")
            except ProtocolError as exc:
                print(f"  ! frame {n}: {exc}", file=sys.stderr)
                last_err = str(exc)
                bad += 1
                if refused_by_panel(exc):
                    bad_refused += 1
                    # a refusal that reaches us as an exception is still a
                    # refusal: the `! frame` line above and the counters a client
                    # reads have to agree, or `--status` says "0 refused" next to
                    # a log full of them
                    refused += 1
                else:
                    bad_refused = 0
                if bad >= RECOVER_AFTER:
                    bad = 0
                    link = rehandshake(link, port, args)
                    since_renew = time.monotonic()
                    since_ok = ok
                    renewals += 1
            except OSError as exc:
                print(f"  ! serial: {exc}; reopening", file=sys.stderr)
                last_err = str(exc)
                bad = 0
                link = rehandshake(link, port, args, reopen=True)
                since_renew = time.monotonic()
                since_ok = ok
                renewals += 1
            else:
                bad = 0
            n += 1
            publish()
            if args.once or (deadline and time.monotonic() >= deadline):
                break
            time.sleep(max(0.0, started + 1.0 / args.fps - time.monotonic()))
        print(f"{ok}/{n} frames confirmed by the panel")
        return 0 if ok else 1
    finally:
        if srv:
            srv.stop()
        link.close()


if __name__ == "__main__":
    sys.exit(main())
