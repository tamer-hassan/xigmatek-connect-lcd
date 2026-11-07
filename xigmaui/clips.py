"""clips.py - the background clips this box can offer, and frames out of them.

Clip roots, in the order the app lists them.  The first three are this project's
own clips (`xigmalcd.main.media_roots()` says which of them exist); the last two
are the vendor's copies, reachable only from a box that has the Windows volume
mounted or the themes package installed.  Every root that exists is scanned, and a
clip found twice is listed once: the same file under two spellings, or the same bytes
under two roots - a checkout on a box that also has the .deb installed holds both
copies of all three vendored clips.  The root that comes first in the order below is
the row that stays, because that is the file `find_media()` would have picked:

  the checkout's media/    the clips vendored into this repository. `Theme_25.mp4`
                           is the one ALPHA pairs with the theme it has selected
                           (214 917 bytes, 23 frames at 24 fps, mean luma 18.7),
                           and it is the daemon's default background.  `$XIGMA_MEDIA`
                           replaces this root with a clip set of your own.
  /usr/share/xigmalcd/media where the .deb installs those three clips.
  ALPHA's installed library `/usr/share/xigmalcd/themes/alpha/clips`, which the
                           `xigmatek-connect-lcd-themes` package puts there: all
                           43 clips of the 27 themes, not just the three this
                           project vendors.
  ALPHA's static media     the vendor's own library, read straight off the mounted
                           Windows partition when there is one (`WIN_STATIC`), so
                           picking one here is the same file the vendor app ships.
  ALPHA's uploads          `%APPDATA%/alpha/media/...`, the clips the Windows app
                           actually pushed to this panel at some point.

Frames come out of ffmpeg, one frame per call, because decoding a whole clip to
pick a mid-loop frame (what tools/previews.py does once per run) is far too slow
for a browser that repaints while you click. ffmpeg's `select` filter is avoided
for the reason previews.py records: it silently yields nothing when the index
runs past the end, which is easy to do on a 23-frame file.

Everything here is host-side. Nothing in this module opens a serial port.
"""
from __future__ import annotations

import glob
import hashlib
import io
import os
import subprocess
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                            # noqa: E402

from xigmalcd import render                                      # noqa: E402
# `render` for one thing: the panel's own geometry, as the fallback when ffprobe
# cannot read a file.  `xigmalcd.main` stays a function-level import (it is the CLI,
# with argparse and the media roots in it); `xigmalcd.render` is PIL and stdlib only,
# so taking it at module level costs nothing and a missing name costs a crash: the
# line below once read `int(wide or render.W)` with no import at all, and survived
# only because `wide or ...` short-circuits whenever ffprobe answers.

_FRAME_CACHE: dict[tuple[str, float], Image.Image] = {}


@dataclass
class Clip:
    path: str
    origin: str                  # "vendored", "vendor library" or "app upload"
    bytes: int = 0
    seconds: float = 0.0
    px: tuple = (0, 0)             # width, height; (0, 0) until probed
    fps: float = 0.0               # the file's own rate; 0.0 until probed
    luma: float = -1.0           # mean of 0-255, -1 until measured
    note: str = ""
    thumbs: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        # the roots come out of media_roots() already abspath'd, but a clip can
        # also arrive from the settings file or from `--mp4` with a `..` or a
        # relative path in it, and one clean spelling per clip is what lets the
        # picker recognise that path instead of falling back to row 0.
        self.path = os.path.normpath(self.path)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def size(self) -> str:
        return f"{self.bytes / 1024:.0f} KiB" if self.bytes < 1024 * 1024 \
            else f"{self.bytes / 1024 / 1024:.1f} MiB"


def _ffprobe_look(path: str) -> tuple[float, int, int, float]:
    """One ffprobe, four numbers: seconds, the frame's width and height, and the
    frame rate.

    The rate is what makes an honest *played* preview possible: the player paces
    by wall-clock time, so it has to know how many frames of the file a second of
    real time is worth.  `r_frame_rate` is ffprobe's own "real base framerate"
    (a rational like `24/1`), which is the number to pace against; the container's
    average rate can differ after variable-frame-rate edits, and neither is
    something the panel is asked about (§11).

    The geometry is not decoration.  Of the 43 clips the themes package installs,
    40 are 480x480 - the panel's own size - and **3 are 320x240** (measured on the
    installed tree with the same call, the odd ones being the timestamp-named
    `2024-05-30_*` and `2024-05-31_*` files the vendor app's own history holds);
    all three clips this repository vendors are 480x480.  What the panel does with
    a file that is not its size is not measured and cannot be - there is no
    readback (§11) - so the picker shows the number and leaves the inference to
    you rather than making one.
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, check=True)
        numbers = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.CalledProcessError):
        return 0.0, 0, 0, 0.0
    try:
        w, h = (int(numbers[0]), int(numbers[1])) if len(numbers) >= 4 else (0, 0)
        fps = _rate(numbers[2]) if len(numbers) >= 4 else 0.0
        return float(numbers[-1]), w, h, fps
    except (ValueError, IndexError):
        return 0.0, 0, 0, 0.0


def _rate(text: str) -> float:
    """`24/1`, `30000/1001` or `24` -> frames per second, 0.0 when unspecced."""
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den = float(den)
            return float(num) / den if den else 0.0
        return float(text)
    except (ValueError, ZeroDivisionError):
        return 0.0


def letterbox(img: Image.Image, side: int) -> Image.Image:
    """`img` fitted into a `side` x `side` RGBA square, bars left transparent.

    The picker's thumbnails go here.  Stretching is the obvious implementation and
    it is a lie about the file: three of the 43 clips the themes package installs
    are 320x240, and a 4:3 frame drawn into a square shows a picture that is not in
    the file - right next to a row printing `320x240`.  Fitting and leaving the bars
    clear means the square in the list never contradicts the number on the row, and
    the list's own background shows through.
    """
    thumb = img.convert("RGBA")
    thumb.thumbnail((side, side), Image.Resampling.LANCZOS)   # keeps the ratio
    box = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    box.paste(thumb, ((side - thumb.width) // 2, (side - thumb.height) // 2), thumb)
    return box


def frame(path: str, at: float = 0.5) -> Image.Image | None:
    """One RGBA frame from `path`, `at` of the way through its loop.

    Mid-loop is the honest choice for these files: `Theme_25.mp4`'s seam is a
    real jump (2.50 against 1.51 typical motion) and `1757491588831.mp4` starts
    and ends with black frames (PROTOCOL §9), so a first frame misleads.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, round(mtime, 3), round(at, 3))
    hit = _FRAME_CACHE.get(key)
    if hit is not None:
        return hit.copy()
    dur, _wide, _tall, _fps = _ffprobe_look(path)   # size and rate are for the picker/player
    seek = dur * at if dur > 0.2 else 0.0
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{seek:.3f}", "-i", path,
             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    if not out.stdout:
        return None
    img = Image.open(io.BytesIO(out.stdout)).convert("RGBA")
    _FRAME_CACHE[key] = img
    return img.copy()


class ClipPlayer:
    """One clip, decoded in order, so the window can *play* a background.

    Why not the `frame()` above, once per preview tick: that function spawns an
    ffmpeg per frame and seeks, which is the right shape for a thumbnail (one
    image, never again) and the wrong shape for a loop.  Measured on this bench
    over `Theme_25.mp4`: twelve frames through one streaming process took
    0.03 s - about 2.5 ms each - while twelve seeks cost an order of magnitude
    more, and the seek is what would put a visible hitch in the playback.

    One process stays open, raw RGBA frames come out of it in order, and at EOF
    it is restarted - so the viewer sees the same loop seam the panel sees, and
    PROTOCOL.md §9 measures those seams (which is why they are worth seeing).
    Nothing seeks: the panel's loop restarts at frame 0 too, so the restart point
    is part of what is being shown rather than a detail to hide.

    Nothing here is measured on the panel: this decodes and shows the file on
    *this* machine, and §11 still means the glass cannot be asked what it is
    doing.
    """

    def __init__(self, path: str):
        self.path = path
        # probed once, here, before a single frame is read - because the window
        # prints the rate beside the picture, and a player that only learned its own
        # frame rate at the first `frame()` spent one redraw saying "at 0 fps".  The
        # suite caught exactly that as `AssertionError: 0.0`.  One ffprobe is 22 ms
        # measured across the 46 clips this box can see: too much to do per frame,
        # cheap to do once.
        dur, wide, tall, fps = _ffprobe_look(path)
        self.seconds = dur
        self.wide, self.tall = int(wide or render.W), int(tall or render.H)
        self.fps = float(fps)      # 0.0 = ffprobe did not say; callers pace at 24
        self._proc: subprocess.Popen | None = None
        self._left = b""
        self.frames = 0          # frames since the last loop restart
        self.decoded = 0         # frames ever produced: the number worth measuring
        self.loops = 0           # end-of-file restarts, i.e. the seams a viewer saw
        self.dead = False        # a stream that produced no frame: stop, don't spin

    def _spawn(self) -> None:
        self.close()
        self._left = b""
        try:
            self._proc = subprocess.Popen(
                ["ffmpeg", "-v", "error", "-i", self.path, "-f", "rawvideo",
                 "-pix_fmt", "rgba", "-"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            self._proc = None
            return

    def frame(self) -> Image.Image | None:
        """The next frame, or None if ffmpeg is not available at all.

        Blocks for the length of one decode - a few milliseconds, measured above
        - which at the window's preview rate is nothing; a non-blocking version
        would need a thread and a queue to drop the same frames a human could
        not tell apart.

        Once a stream has failed - see `dead` - it stays failed and says so
        instead of being started again.
        """
        if self.dead:
            return None
        if self._proc is None:
            self._spawn()
        if self._proc is None:
            return None
        need = self.wide * self.tall * 4
        buf = self._left
        while len(buf) < need:
            chunk = self._proc.stdout.read(need - len(buf))
            if not chunk:                      # end of file: the loop restarts
                if self.frames == 0:
                    # ...unless this spawn never produced a frame at all, which is
                    # not a loop seam but a failure: a missing file, an undecodable
                    # stream, an ffmpeg without the codec.  Restarting there is an
                    # infinite loop - measured, in the sense that it ate a 16-minute
                    # harness timeout on a path that only ever needed one honest
                    # `None`.  So: give up, once, and let the caller fall back to the
                    # still frame it already has.
                    self.dead = True
                    self.close()
                    return None
                self.frames = 0
                self.loops += 1
                self._spawn()
                if self._proc is None:
                    return None
                continue
            buf += chunk
        self._left = buf[need:]
        self.frames += 1
        self.decoded += 1
        return Image.frombytes("RGBA", (self.wide, self.tall), buf[:need])

    def close(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdout:
                    self._proc.stdout.close()
            except (OSError, ValueError):
                pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


def luma(img: Image.Image) -> float:
    """Mean luma, from PIL's C histograms: cheap enough to measure every clip
    in a list, and it is what decides whether glyphs need a `--scrim` plate."""
    g = img.convert("L")
    hist = g.histogram()
    return sum(i * h for i, h in enumerate(hist)) / max(1, sum(hist))


def list_clips(extra: str = "") -> list[Clip]:
    """Every clip the app can offer, best-guess order first."""
    from xigmalcd.main import (MEDIA_ENV, SYSTEM_MEDIA, SYSTEM_THEMES,
                               WIN_STATIC, WIN_UPLOADS, media_roots)

    found: list[Clip] = []
    seen = set()          # realpaths: one file, several spellings
    taken = {}            # (name, length) -> the row already standing for that shape

    def edge(path: str) -> str:
        """sha256 of the first and the last MiB.

        Only consulted when a name and a length have already matched, which is a
        handful of pairs however many roots exist.  Reading the whole file would be
        the honest comparison; this reads 2 MB of the largest clip in the library
        instead, which is enough to tell a copy apart from a same-named,
        same-length neighbour - the Windows app's own upload history has 69 entries
        on this box and repeats itself by name."""
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            h.update(fh.read(1 << 20))
            try:
                fh.seek(-(1 << 20), os.SEEK_END)
            except OSError:             # shorter than the window: the head is all of it
                return h.hexdigest()
            h.update(fh.read(1 << 20))
        return h.hexdigest()

    def add(path: str, origin: str, note: str = "") -> None:
        real = os.path.realpath(path)
        if real in seen:
            return
        size = os.path.getsize(path)
        key = (os.path.basename(path).casefold(), size)
        prev = taken.get(key)
        if prev is not None and edge(found[prev].path) == edge(path):
            # The same clip sitting in two roots: the checkout's media/ and the copy
            # the .deb put in /usr/share/xigmalcd/media, or a clip this project
            # vendors itself and the themes package also carries.  realpath alone did
            # not catch that - these are separate files with the same bytes - and on
            # the author's bench, once the packages were installed, it showed as 161
            # rows where 115 clips exist.  The roots are walked in precedence order,
            # so the row that stays is the file find_media() would have chosen.
            seen.add(real)
            return
        taken[key] = len(found)
        seen.add(real)
        found.append(Clip(path=path, origin=origin, bytes=size, note=note))

    # (root, pattern, origin). The root is checked with isdir rather than the
    # pattern's own dirname: for a recursive pattern that dirname is the `**`
    # component, which never exists, and that silently hid every clip the
    # Windows app had ever pushed - 69 of them on this machine
    sources = [(_root, "*.mp4", "vendored",
                "installed with the package" if _root == SYSTEM_MEDIA else
                ("chosen with $XIGMA_MEDIA" if _root == os.path.abspath(
                    os.environ.get(MEDIA_ENV, "-")) else ""))
               for _root in media_roots()]
    sources += [(os.path.join(SYSTEM_THEMES, "clips"), "*.mp4", "vendor library",
                 "installed with xigmatek-connect-lcd-themes"),
                (WIN_STATIC, "*.mp4", "vendor library",
                 "mounted from the Windows partition"),
                (WIN_UPLOADS, "**/*.mp4", "app upload",
                 "pushed to this panel by the Windows app, on the Windows partition")]
    for root, pat, origin, note in sources:
        if not os.path.isdir(root):
            continue
        for path in sorted(glob.glob(os.path.join(root, pat), recursive=True)):
            add(path, origin, note)
    if extra:
        add(extra, "chosen by you")

    # no duration pass here: 115 clips on this box costs 2.4 s of ffprobe, which
    # is 2.4 s of blank window before the first frame. `probe()` fills it in per
    # clip as the picker walks its rows.
    return found


def probe(clip: Clip) -> float:
    """Measure one clip's loop length and frame size. One row at a time."""
    if not clip.seconds or not clip.px[0]:
        clip.seconds, w, h, clip.fps = _ffprobe_look(clip.path)
        clip.px = (w, h)
    return clip.seconds


def measure(clip: Clip) -> float:
    """Fill in the per-clip numbers the picker shows. Called off the UI thread."""
    from xigmalcd.main import CLIP_LUMA

    if clip.luma < 0:
        known = CLIP_LUMA.get(clip.name)
        if known is not None:
            clip.luma = known                 # already measured by the daemon
        else:
            img = frame(clip.path)
            clip.luma = luma(img) if img else 0.0
    return clip.luma
