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

The five previews below **play**: our transparent OSD layer composited over the vendor's
own background MP4 running on repeat — the same two-layer picture the panel puts on the
glass, and the same loop whose restart seam PROTOCOL.md §9 measures there.

| `alpha` (default) | `gauge` |
|---|---|
| ![the alpha theme's layer over the vendored background, running: two ring gauges reading CPU 73 °C and GPU 34 °C, the hotter one's arc curving far round the ring in warm colours and the cooler's a short arc in green, fan figures of 2 238 RPM and 35 %, load bars at 90 % and 0 %, clock 11:07:42](docs/preview-alpha.gif) | ![the gauge theme, running: one large ring gauge reading 73 °C with the arc's length and colour both carrying the value, the clock under it](docs/preview-gauge.gif) |

| `dual` | `clock` |
|---|---|
| ![the dual theme, running: two rings side by side reading 73 and 34 with the numbers inside them and a load and memory line under each](docs/preview-dual.gif) | ![the clock theme, running: 11:07:42 across the middle, Saturday 07 November 2026 under it, CPU, GPU and fan figures along the bottom](docs/preview-clock.gif) |

| `bars` | |
|---|---|
| ![the bars theme, running: SYSTEM MONITOR with a row and a meter for CPU, GPU, BOARD, LOAD, RAM, VRAM and two fans, each value printed at the right of its row](docs/preview-bars.gif) | |

They are GIFs because GitHub renders an `.mp4` in a README as an `<img>` no browser
plays, so motion here has to be a GIF. `tools/preview_gif.py` writes them through the
same path the window's preview pane uses — `clips.ClipPlayer` decoding the file,
`render.draw` drawing our layer over it — at 320 px, 12 frames, a 170 ms delay, 128
colours. What is *not* live: the digits are one dated sample from the author's bench
under a stated load (CPU 73 °C at 89.8 % load, CPU fan 2 238 RPM, 82 of 123 GB of
memory), the same pinned readings every time, so the picture says the same thing on
every machine. The GIF's palette is ffmpeg's, not the 256-colour PNG the panel is fed;
measured back out of the encoded files, the drawn colours land 0-2 per channel from
what `render.py` asked for. And because a GIF carries a length, the restart is worth
A word for readers who cannot see the motion: GitHub documents that animated GIFs
follow the reader's system reduced-motion preference by default, under
**Settings → Accessibility → Motion → "Autoplay animated images"**
([Managing accessibility settings](https://docs.github.com/en/account-and-profile/how-tos/account-settings/managing-accessibility-settings)),
so these five may reach you as a still frame. The files themselves loop for ever
(`loop = 0` in each, asserted by the suite), the first frame of each is a real composited
frame rather than a fade-in, and the alt text above says what each picture shows - which
is what has to carry the description when the motion does not.

And because a GIF carries a length, the restart is worth
measuring rather than trusting: by PROTOCOL.md §9's own metric the five files join at
2.05-2.36 against typical steps of 2.15-2.52, so the restart never stands out — and it
is smoother than that same clip's raw join measured there (2.50 against 1.51), because
our redrawn layer raises every ordinary step.

`alpha` is the vendor's currently selected theme redrawn widget for widget, with the
things that theme has no widget for added: a GPU-temperature column, a gauge arc
around each temperature (30-100 °C, position *and* colour carrying the value), a clock
with seconds, and one fan figure under each temperature. [docs/themes.md](docs/themes.md)
has the identity claim, the geometry and why the digits are that size;
[`themes/alpha/`](themes/alpha) holds the vendor's whole library — 27 themes, their
decrypted layouts, their clips and their baked overlays, every byte hashed — and the
contact sheet of it is
[`docs/previews/alpha-themes-480X480.png`](docs/previews/alpha-themes-480X480.png).

## The window

The same controls in a Qt application: pick a theme, pick a background from every clip
the machine can find, watch the preview, put one frame or the whole loop on the glass.
And because this panel cannot be asked what it is showing, the window says what it
*knows*: the background the running display reported putting there, and the last six
things it did on the port. Three columns — preview, controls, clip library — with an
`advanced controls` switch that folds the secondary knobs away without changing their
values, a `playing` box that decodes the background in sequence so the preview moves
under our layer instead of showing one still frame of it, and one row that is always in
sight, for the colour of the text it draws. This is a capture of the real program
(`tools/screenshot.py`, no panel attached), with this machine's live readings in the
preview:

![xigmaui, the window in three columns: the playing preview and the log on the left,
the display's status, the theme picker and the text-colour row in the middle, and the
background clip library on the right listing this machine's clips once per distinct
file - 40 of them, from 161 mp4 files in the roots it walks](docs/screenshot-xigmaui.png)

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
and the gaps are named as gaps. `tools/selftest.sh` runs the nineteen offline sections
that hold the claims which do not need hardware — it is what CI runs first, on a machine
that has never seen a panel.

## How the protocol works

See **[PROTOCOL.md](PROTOCOL.md)** — frame format, the checksum rule, the vendor's
escaping (`0x5A` → `5B 01`, `0x5B` → `5B 02`, counted nowhere), how replies are matched
to requests (`AckNumber = SeqNumber + 1`), the command set, the upload sequence, the
session limits, and how to read the vendor app yourself. It is written out of captures of
the Windows app talking to this panel, and the offline suite re-checks that code against
those same captures: **181** host→panel frames re-encoded with **0** disagreeing with
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
[PROTOCOL.md](PROTOCOL.md). [docs/handoff-2026-11-05.md](docs/handoff-2026-11-05.md) is
the record of how that discovery went, kept as history rather than as current state.
