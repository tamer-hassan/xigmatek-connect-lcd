# xigmalcd — system stats on the Xigmatek Connect AIO's built-in LCD

<img src="docs/logo.png" width="220" align="right" hspace="14" alt="the project's mark: a
penguin standing in front of a Connect AIO water block, whose LCD reads 39°C">

Linux counterpart of the Windows `ALPHA` app that ships with Xigmatek **Connect**
series AIO coolers. Those coolers have a 480×480 LCD in a USB port header on the
water block; on Windows the vendor app draws CPU/GPU temps, clocks and fan speeds on
it. On Linux the panel shows up as a plain CDC-ACM serial port (`/dev/ttyACM0`) and
nothing talks the protocol — until now.

This repo draws the same information from Linux sensors and pushes it to the panel as
PNG frames. Verified on real hardware (Connect 360, firmware `V1.2.3`): handshake,
metrics blob and picture upload all work from Kubuntu — the drawn frame is what the
display shows.

**Unofficial, and it says so.** Nothing here is affiliated with, endorsed by or
approved by XIGMATEK; `Xigmatek`, `Connect` and `ALPHA` are their owner's names. The
code — `xigmalcd/`, `xigmaui/`, `tools/`, `install/` — is GPL-3.0-or-later (`LICENSE`),
and the vendor's own files this repo carries as evidence and test assets are labelled
as such wherever they appear ("Licence", at the end).

## What it draws

Five themes, each drawn over a *different* clip from the vendor's own library, and filmed
moving: the digits, the meters and the clock on the glass all change as you watch. What
they show is recorded, not invented — `docs/videos/readings-2026-11-08.json` holds 12
real `sensors.collect()` readings, one per second, taken on the author's bench while
seven parallel clip decodes were running, which is the load rendering these videos puts
on a machine. CPU 68 → 74 °C, CPU load 57.7 → 94.6 %, fan 1 540 → 2 181 RPM, clock
`00:25:16` → `00:25:28`. That box never went idle while this was written — the session
making the videos runs its own model server at about 390 % of 24 cores — so the `gauge`
ring spends the clip near the top of its measured 30..75 °C scale. It is a busy machine,
and the file says so.

| `alpha` (default) over `Theme_25.mp4` | `gauge` over `3.mp4` |
|---|---|
| https://github.com/user-attachments/assets/79094fe1-e2e9-4ce0-9f81-3f3f3ee123e0 | https://github.com/user-attachments/assets/da2cbb5a-cb17-4121-b4c4-f1f53c9cc3ce |

| `dual` over `Theme_30.mp4` | `bars` over `theme_52.mp4` |
|---|---|
| https://github.com/user-attachments/assets/598e1e53-1775-407b-bd25-576b55082bd6 | https://github.com/user-attachments/assets/57e582b7-73c5-42b1-9437-9ede6cf18f18 |

| `clock` over `Theme_07.mp4` | |
|---|---|
| https://github.com/user-attachments/assets/ce8cab80-2125-4011-b44a-9a4e19a08ca3 | |

`clock` runs over a bright clip (mean luma 176 of 255), which is why its lettering
carries a dark plate behind it — the same rule the window applies, described in
[docs/gui.md](docs/gui.md). The sixth video, the same `alpha` clip with the lettering
drawn in `#ffc400` instead of white, is at the bottom of [docs/gui.md](docs/gui.md).

Videos rather than GIFs, because an `.mp4` written into markdown as an image becomes an
`<img>` tag no browser plays — so these went up through GitHub's own editor, which stores
the file on its CDN and writes the URL into the cell. The originals stay in `docs/videos/`,
and the two things are the same bytes: fetching those six URLs answers with the tree's
files `cmp`-clean, sizes and sha256s included ([docs/limits.md](docs/limits.md) keeps that
measurement), so every figure quoted here and there was read out of what you are watching.
Each one is 10–12 s at the clip's own frame rate; `tools/preview_gif.py` makes them through
the same path the window's preview pane uses, and [docs/tools.md](docs/tools.md) carries the
command. Whether they animate on your screen is your browser's motion setting, not a switch
in this repository.

`alpha` is the vendor's currently selected theme redrawn widget for widget, with the
things that theme has no widget for added: a GPU-temperature column, a gauge arc
around each temperature (30-100 °C, position *and* colour carrying the value), a clock
with seconds, and one fan figure under each temperature. [docs/themes.md](docs/themes.md)
has the identity claim, the geometry and why the digits are that size;
[`themes/alpha/`](themes/alpha) holds the vendor's whole library — 27 themes, their
decrypted layouts, their clips and their baked overlays, every byte hashed — and the
contact sheet of it is
[`docs/previews/alpha-themes-480X480.png`](docs/previews/alpha-themes-480X480.png).
The daemon can draw 23 of those 27 layouts as they are - `xigmalcd --theme Theme_07` -
and `xigmalcd --list-themes` prints that set, the four refused on canvas with the reason,
and the one metric this box has no reading for; `--check-theme Theme_07` reports one of
them the way the loop sees it - which file answers the name, what draws from this
machine's readings, and what is skipped. They reach the panel as ordinary
transparent frames: a layout file is never sent, because this firmware does not read one
(PROTOCOL.md §11).

## The window

The same controls in a Qt application: pick a theme, pick a background from every clip
the machine can find, watch the preview, put one frame or the whole loop on the glass.
And because this panel cannot be asked what it is showing, the window says what it
*knows*: the background the running display reported putting there, and the last six
things it did on the port. Three columns — preview, controls, clip library — with an
`advanced controls` switch that folds nine secondary controls - two boxes of them at the
foot of the preview column, five rows in the controls column - away
without changing their values, a `playing` box that
decodes the background in sequence so the preview moves under our layer instead of showing
one still frame of it, a `pane readings` knob on the row between the two, which picks what
body the picture is painted from and never folds away, and one row that is always in sight,
for the colour of the text it
draws. This is a capture of the real program (`tools/screenshot.py`, no panel attached),
with this machine's live readings in the preview:

Behind the `advanced controls` switch sit the panel's own `conn 1` report and the guarded
factory reset. Open in the controls column, always, is a row that opens one of the vendor's
layout files — or one of the five themes generated from our own drawing code — and edits
the fields this program's painter actually reads, with the picture under the preview
redrawn from the file as it changes. The rows themselves too: a row can be added —
always a copy of a row this program already draws, never a table of defaults — removed,
reordered through the list that decides which one paints on top, and stretched by
dragging one of the squares on its box, through the size keys that kind owns. A copy is
yours to rename, and one layout can be saved as a second copy under a new name — a name
nothing in the library answers, by name, by spelling, or by the id inside the file. And a
drag can stick, within two pixels, to a number that same layout already uses: another row's
edge, its centre on the glass, its mirror. There is no grid, because the vendor's files
carry none. And the picture it edits can be painted from another body of readings than the
pinned fixture: **this machine's own, live** — re-read on each preview tick, with the box, the
handles and the hit test taken from that same paint, so the row you point at is the row whose
ink you pointed at — or a metrics file you name, which is held, at the pinned instant, and a
look only: press, drag and arrow keys stay with the pinned frame there, because a number
written from a sample that has already gone stale belongs to a reading that no longer answers.
The panel is never handed a layout file, so what that editor changes is what a
loop on *this* machine draws the next time it names that theme
([docs/gui.md](docs/gui.md) has the row and its limits).

![xigmaui, the window in three columns: the playing preview and the log on the left -
`playing` and the `pane readings` knob on the rows above the picture, and under the log,
behind `advanced controls`, the panel's own report and the guarded factory reset - the
theme picker, the text-colour row and the layout editor in the middle, and the background
clip library on the right, one row per distinct file: 40 rows from the 46 mp4 files this
repository tracks](docs/screenshot-xigmaui.png)

These two are the same window at the two settings of its `advanced controls` switch, and
all three pictures here come from one command: `tools/screenshot.py`, which builds the real
`xigmaui` offscreen — a temporary `XDG_CONFIG_HOME`, so no remembered window size or clip
choice is in the frame, and a port path that **does not exist**, because in that mode the
window's own status action opens the serial port and a screenshot must not take over
somebody's panel. So the status box holds the refusal line rather than a reply, and there is
no serial in these pixels to paint out. The captures that ran here until 2026-11-12 were live
ones, and `docs/limits.md` and `docs/packaging.md` keep that account - including the OCR pass
that found a serial in a published PNG, and the `tests/test_no_serial.py` guard that came out
of it.

![xigmaui, simple mode: the `advanced controls` switch left off, which is what a first run
shows - the playing preview and the log on the left, with the `pane readings` knob shut on
the row above it because there is no layout open to peek at, the theme and text-colour
pickers in the middle, and the background clip library on the right](docs/xigmaui1.png)

![xigmaui, advanced mode: the same switch on, with one layout open in the editor. The pane
draws *that file* rather than the live theme - here the exported `bars` layout, the one that
reserves four fan slots so a row with no reading keeps its place - `the fixture` on the
pane-readings row above it, and beside the picture that widget's own field rows (this one is
the heading line, `text` kind, at x 240 y 30, with its font, its colour, and the `autoFit`
width its drawing reads). Under the layout menu sit the two doors that decide *which file*
the box holds, `reload the list` and `open a file…`; under the field rows, the doors that
act on it: `undo`, `save as your copy`, `revert`, and `apply to the panel` - which sends the
layout's *name* and nothing else - then `rename` and `copy to a new name` beside the box for
the name to give. Under the log, the panel's own report and the guarded reset; on the right,
the clip library with the size and loop length each row measured](docs/xigmaui2.png)

It talks to a display loop that is already running when one is running, and drives the
port itself when nothing is — which is the part that needs care, because the panel
allows exactly one opener. [docs/gui.md](docs/gui.md) is the whole write-up: what every
button sends on the wire, what the window stores between runs, what it costs to run,
and the glass ledger for it with the log file each number came from.

## Quick start

### 1. Debian, Kubuntu, Ubuntu: install the `.deb` files

```bash
# 1. get the two files - the releases page in a browser, or with gh:
gh release download --latest --pattern '*.deb'
# 2. install both from one command line (building them instead is docs/packaging.md):
sudo apt install ./xigmatek-connect-lcd_*_all.deb ./xigmatek-connect-lcd-themes_*_all.deb
# 3. the udev rule is installed but not read yet - replug, or:
sudo udevadm control --reload-rules && sudo udevadm trigger --action=change
# 4. the install *enables* the unit and does not start it:
systemctl --user start xigmalcd.service
xigmaui                                     # the window; needs `sudo apt install python3-pyqt6`
```

That gives `/usr/bin/xigmalcd`, `/usr/bin/xigmaui` and `/usr/bin/xigmalcd-reset`, a
udev rule that makes the port a user-owned `/dev/xigmatek-lcd` and keeps ModemManager
off it, and a user unit whose `ExecStart` is `--theme alpha --fps 2` with no reset
permission. The second package is the vendor's own theme library and is optional on
purpose. Two things about that unit are worth knowing on day one: the install enables it
in systemd's **global user** scope (`/etc/systemd/user/default.target.wants`, so for every
user's next login - taking that back is `sudo systemctl --global disable xigmalcd`), and an
**upgrade** while you are logged in has been seen to start the display on its own three
seconds after apt finished. `systemctl --user stop xigmalcd` frees the port at any point.
Everything else an install does and does not do — including the udev reload above — is
measured and written down in [docs/packaging.md](docs/packaging.md), with the transcripts.

### 2. Any other Linux distribution: run it from this tree

```bash
python3 -m xigmalcd --list                    # find the port and its USB description
python3 -m xigmalcd                           # default theme, 1 fps, the vendor's cadence
python3 -m xigmalcd --fps 3 --clock-size 34   # tighter clock, bigger digits
python3 -m xigmalcd --dry-run /tmp/frames --once   # a PNG, and the port never opened
python3 -m xigmaui                            # the window (needs PyQt6)
python3 -m xigmalcd --status                  # ask the running display what it shows
```

Needs Python 3.9+, [pyserial](https://pypi.org/project/pyserial/) and
[Pillow](https://pillow.readthedocs.io/) — on a Debian-family box
`sudo apt install python3-serial python3-pil`. `/dev/ttyACM0` is `root:dialout`, so be
in that group or install the rule; both recipes, and how to run it at login on a
systemd-less machine, are in [docs/install.md](docs/install.md). The window's extra
dependency is PyQt6 (`pip install .[gui]`), which the display loop never needs.

The default run uploads the theme's background first (`media/Theme_25.mp4`, 215 KB) and
then draws on a **transparent** canvas, so that background keeps playing behind the
picture — which is how the vendor's own app does it, and the pair is what its own config
names, so the default glass is what `ALPHA` showed you on Windows.

## Where the detail lives

| | |
|---|---|
| [docs/install.md](docs/install.md) | requirements, the port and the udev rule, `pip install`, running it at login |
| [docs/usage.md](docs/usage.md) | every `xigmalcd` flag, what goes on the wire and when, one port between two processes |
| [docs/gui.md](docs/gui.md) | the window: controls, what each action sends, settings, cost, glass runs |
| [docs/themes.md](docs/themes.md) | what `alpha` is a redraw of, the ring geometry, the vendor library |
| [docs/packaging.md](docs/packaging.md) | the two `.deb` files, `lintian`, CI, install transcripts, reproducible builds |
| [docs/tools.md](docs/tools.md) | what every script in `tools/` is for, and which question it answers |
| [docs/limits.md](docs/limits.md) | what has been seen on glass, by whom, in how many frames — and what has not |
| [docs/troubleshooting.md](docs/troubleshooting.md) | a panel stuck white, and the one command that brings it back |
| [PROTOCOL.md](PROTOCOL.md) | the wire: the handshake, the frame format, the media upload, the session limit — every claim from a capture |

Everything in those files is measured on the author's bench or read out of a kept log,
and the gaps are named as gaps. The claims that do not need hardware live as ordinary
tests in [`tests/`](tests/), run by the standard library — `python3 -m unittest discover
-s tests` — and that is what CI runs first, on a machine that has never seen a panel.

## How the protocol works

See **[PROTOCOL.md](PROTOCOL.md)** — frame format, the checksum rule, the vendor's
escaping (`0x5A` → `5B 01`, `0x5B` → `5B 02`, counted nowhere), how replies are matched
to requests (`AckNumber = SeqNumber + 1`), the command set, the upload sequence, the
session limits, and how to read the vendor app yourself. It is written out of captures of
the Windows app talking to this panel, and `tools/verify_protocol.py` re-checks that code
against those same captures: **181** host→panel frames re-encoded with **0** disagreeing with
`xigmalcd/protocol.py`, and **267** replies read against the checksum rule with all of
them passing.

`xigmalcd/protocol.py` is the implementation; `xigmalcd/sensors.py` reproduces the
metrics schema; `xigmalcd/render.py` is the drawing; `xigmalcd/main.py` is the loop;
`xigmaui/` is the Qt window over the same four modules.

## Licence

GPL-3.0-or-later for the code, with the vendor's own files carved out and labelled
where they came from. [LICENSE](LICENSE) is the license text;
[debian/copyright](debian/copyright) is the machine-readable version of the same
distinction, and it names what was done to obtain the vendor's files rather than
pretending to license them. If the rights holder of XIGMATEK's files considers their
inclusion wrong, say so at the address in that file's `Upstream-Contact` and they come
down.

## Credit

The protocol was recovered by watching the Windows app talk to a panel that this
project then drove from Linux; the notes on how, and the captures themselves, are in
[PROTOCOL.md](PROTOCOL.md), which is the record of how that discovery went - what was
watched, what was measured, and what was inferred and later corrected.
