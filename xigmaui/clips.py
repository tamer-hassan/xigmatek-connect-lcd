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

_FRAME_CACHE: dict[tuple[str, float], Image.Image] = {}


@dataclass
class Clip:
    path: str
    origin: str                  # "vendored", "vendor library" or "app upload"
    bytes: int = 0
    seconds: float = 0.0
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


def _ffprobe_duration(path: str) -> float:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "default=nk=1:nw=1",
                              path], capture_output=True, text=True, check=True)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 0.0


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
    dur = _ffprobe_duration(path)
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
    """Measure one clip's loop length. Cheap enough to do a row at a time."""
    if not clip.seconds:
        clip.seconds = _ffprobe_duration(clip.path)
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
