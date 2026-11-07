# The window: `xigmaui`

What the Qt front end does, what each control sends, what it stores between runs, and what it costs to run. Needs PyQt6, which the display loop never does.

`python3 -m xigmaui` is a window for what `ALPHA`'s window is actually used for on a
machine with the panel plugged in: look at the picture, pick the theme, pick the
background, read the panel's own report, reset. Behind those uses are two halves:
`xigmaui/panel.py` queues five actions against the port - `status`, `upload`,
`frame`, `live`, `reset` - and `xigmaui/daemon.py` sends the same intentions as
socket commands to a display that is already running (`xigmalcd/control.py`). Which
half is used is decided by looking, not by a flag. Each use is a button or a pane
rather than a command line flag. It needs PyQt6 (6.10.2 here, packaged):

```bash
sudo apt install python3-pyqt6
python3 -m xigmaui        # --device PATH, --preview-fps N, --fresh, --socket PATH
                          # --tray / --no-tray, --hidden
```

`install/install.sh` also puts it in the application menu, where the entry is called
**Xigmatek Connect LCD** (`install/xigmaui.desktop.in`, and `debian/xigmaui.desktop`
after an install; see [Run it at login](install.md#run-it-at-login)). That name is the Connect *family*, not
the author's model - every measurement in this repo was taken on a Connect 360, no other
Connect has been tested, and the entry just declines to tell the owner of another Connect
that this is not for their port. `connect 360` stays in the entry's `Keywords`, and the
window's own title bar and tray tooltip say the same thing as the menu (`xigmaui/app.py`,
checked against both files by `tools/selftest.sh`).

**It has two roles and picks one at startup by looking.** Only one process can hold
the port (PROTOCOL.md §1), so:

* **A display is running** (its control socket answers, see "Two processes, one
  port"): the window is a remote. The box at the top of it says what that display is
  drawing and with what counters, and the buttons send socket commands - theme, clock
  size, canvas, scrim, fan figures, fps, `pause`, one frame, one background upload.
  The glass keeps updating when this window is closed, because those frames belong
  to `xigmalcd`. This is the mode the shipped systemd unit implies, and the reason
  the tray icon exists.
* **Nothing is running**: the window uses the port itself, one short visit per action
  (`xigmaui/panel.py`) - open, `hello`, act, close - so `python3 -m xigmalcd` stays
  usable between actions. Nothing reaches the panel without a deliberate click.

Which one is in force is printed in the window's log and status bar, and the
offline suite asserts both (the remote path with a real socket and no serial layer
at all). `--socket PATH` points it somewhere else; `$XIGMA_SOCKET` is honoured by
both sides.

**Tray.** If the desktop has a tray (Qt asks: `isSystemTrayAvailable`), closing the
window hides it instead of quitting, and the icon's menu is: the display's status
line, pause/resume, the five themes (choosing one there sends it to the glass, not
just to the preview), show the window, whether to stay in the tray, and Quit - which
does quit. `--no-tray` turns the whole thing off and closing quits as before;
`--hidden` starts as tray only, which is what you want if the window is a control
panel you keep out of the way. With no tray available the window says so and stays
the plain window it always was; either way the glass keeps updating, because the
frames are the daemon's. The setting is remembered (`tray` in the config file).

It is built on the daemon rather than next to it: every byte goes through
`xigmalcd.protocol.Link`, every pixel through `xigmalcd.render.draw`, and the
background upload is literally `main._upload_background` handed a stand-in for
the daemon's argparse object. The measured wire numbers are imported rather than
repeated - `protocol.MEDIA_GAP` and `MEDIA_CHUNK` for the upload shape,
`main.SESSION_MAX`, `SESSION_TTL`, `RECOVER_AFTER` and `REFUSE_GIVEUP` for what a
session can take - so the window and `python3 -m xigmalcd` cannot drift apart, and
there is one place to change when a number is re-measured.

The three columns are preview / controls / library, and the boxes below sit in
one of them (see "How the three columns get their sizes", after the table):

| box | column | what it does | what lands on the wire |
|---|---|---|---|
| the running display | controls | what the socket says another process is drawing: one sentence, the counters (`40/41 uploads the panel confirmed, 0 refused, 1 renewal`, session age, last file and notice, `space`), **what the panel stores as its background** (`the panel stores: theme_47.mp4`, read out of the display's own event ring), and the ring itself - the last six things that display did on the port, with its verdict on each upload. It also spells out the settings that display is running with - canvas, clock size, scrim, fans, and **the text colour it holds, as the hex it will answer again** (`text #ffc400`), which is the only place in the window you can see a colour you did not pick yourself. Pause, one frame, an fps spin, `Apply these settings` (Ctrl+Return) | socket only; the port is never opened. Measured 1 ms for the commands Apply sends - six on the 0.2 bench ledgers below, seven in the tree, and the suite re-measures the line every run |
| preview | preview | the background with `render.draw`'s OSD layer composited on top - playing, via one streaming ffmpeg, or as one mid-loop frame (`playing` box, see "The preview plays" below), refreshed at `--preview-fps` (default 2). Its column is capped at 480 px plus the pane's chrome, and the picture is never drawn larger than the glass is - see "How the three columns get their sizes" below | nothing |
| theme | controls | the five themes, clock size, **the colour of the text it draws**, `clear`/`black` canvas, scrim, fan figures, and a line saying what the vendor's 27 themes in the other package are and are not | nothing until you press Apply (display running) or one of the send buttons (not running) |
| clips | library | every MP4 the roots hold, listed once per **distinct file** - **40 rows here out of 161 files**: 3 vendored here and 37 from the vendor's library; the other 121 are copies (69 in the Windows app's upload history, 43 in its static media, 9 left by the installed packages), 35 of them under a different name; the last two sources are read off the mounted Windows partition or the installed themes package, and a clip that exists in two roots keeps the row from the root the code would have chosen. One thing that is **not** a root: this checkout's own `themes/alpha/clips` - a clone reaches the vendor's library by installing the themes package, which is why a bare checkout lists 3 clips and an installed box lists 40, while `tools/preview_gif.py --clip themes/alpha/clips/Theme_30.mp4` reaches the tree's copy directly (that is how all five README previews are made). Each row gets an ffmpeg thumbnail, its measured mean luma and its measured frame size (ffprobe: 40 of the 43 clips the themes package installs are 480x480, 3 are 320x240, and a clip that is not the panel's size is labelled a guess under the list). One filter field above the list, and a row the display's own gate would refuse is greyed with its reason in the tooltip | the window's **one** upload button, `Send this background to the panel` (Ctrl+Shift+U): `STATE all 1` twice, then the whole file as one media file |
| background state | library | one line under the list that keeps "I picked this" and "the panel stores this" apart, in three wordings: the display reported accepting this very clip, it reported accepting a different one, or this window has not seen an accept - and the matching row in the list is drawn bold. A file the gate refuses says so, in the gate's words, before the button is pressed | nothing: it is a readout |
| `One frame now` | library | one live frame, preview and glass showing the same render | `STATE all 1` twice, then one `.osd` upload |
| `Send frames for 30 s` | library, advanced | the picture loop, so you can watch the real glass | `STATE all 1` twice, then 60 uploads at 2 fps |
| status | library, advanced | the panel's `conn 1` reply: sn, versions, `space`, `brightness`, `mode`, `logo`, `osdState`, `timeout`, each annotated only where PROTOCOL.md records what it means | `conn 1`, `power resume`, `timeout 60` - and no metrics blob, because it puts no picture on the glass. With a display running there is no fresh `conn 1` to ask for, so the box shows the one that display read at its own session start, labelled as such |
| log | preview, under the picture | the window's own last 200 lines (`LOG_KEEP`): what it sent, what the panel answered, what failed and why. Scrollable, selectable, newest at the bottom; the display's full record is its journal, `journalctl --user -u xigmalcd -f` (docs/usage.md) | nothing: it is a readout |
| `advanced controls` | controls, top row | folds away the six secondary things named further down; it hides pixels and never values | nothing |
| reset | controls, always on | the vendor's `recovery` | needs the word `reset` typed in, then a confirm dialog. With a display running it goes over the socket, which refuses it unless that display was started `--allow-reset`, and the refusal is quoted in the daemon's words |

### How the three columns get their sizes, and why the preview is never bigger than the glass

The window is a splitter with three panes - preview, controls, library - and every
number in that shape comes from a measurement, most of them of a failure:

* the frame `render.draw` produces is **480×480**, exactly what the panel is, and
  `_fit()` caps the pixmap at that size. Qt's `scaled(KeepAspectRatio)` grows a
  pixmap without being told not to, and on a wide window the old code drew the
  480 px picture at 502 px - a picture of the glass containing 22 px of invented
  detail. The suite pins both directions: 1:1 on a wide window, and shrunk to the
  pane when the handle is dragged narrow (`xigmaui/app.py:_fit`);
* so a preview column wider than 480 px + chrome is dead space. That pane gets a
  maximum width (`render.W + PANE_CHROME`, 532 px here). Before the cap, a 2 259 px
  window gave the preview ~993 px for a 480 px picture - and, with the upscale bug,
  drew it at that size - while everything else shared 1 266 px. The floor on the
  other side is a measurement too: the first version applied its sizes before the
  splitter had ever been laid out, and at 2 259 px the controls came back **116 px**
  wide. Hence the sizes are set after the window's own `resize`, and the three
  minimums are 200 / 300 / 320 px;
* **the library is a column of its own**, because of one number: at 1 919×1 055 the
  clip list, sitting fifth in a single long column, had a **190 px viewport** and
  rows **114 px** tall - two clips on screen at a time, on a full-HD monitor.
  The row height follows the icon, so the thumbnails went from 112 px to 64
  (`CLIP_ICON`), and `ResizeMode.Adjust` - which lays rows out against the viewport
  and is what painted one selected clip as a block taller than the list - went to
  `Fixed` with uniform rows. Measured afterwards, and printed by the suite:
  **66 px rows, and room for 7 clips at the fresh 1180×780 window, 12 at
  1919×1055** — rows in view, which is capacity: this bench has 40 distinct clips to
  put in them (161 files behind them), a CI checkout with no themes package has 3;
* **the log sits under the picture**, in the preview column, because that is the one
  place with height to spare: the frame is 480 px and is never scaled up, so a tall
  window leaves room there nothing else can honestly fill - while every pixel of the
  library column is another clip row - with one caveat about the picture: a thumbnail is drawn into a
  64 px square, and a clip that is not the panel's shape (3 of the library's are
  320×240) is letterboxed into it rather than stretched, so the square in the list is
  not a claim about the file's proportions. The `320x240` on the row is.
  The picture still keeps first call on that
  column's height (stretch 6 against the log's), so the log scrolls rather than
  shrinking the glass; the list has a 150 px floor and the log an 84 px one, so a
  short window scrolls instead of turning the picker into a strip;
* where the handles end up is remembered - the settings file's `split`, now three
  numbers, with a two-number file from the old layout grown a third and a restored
  `0` width rejected rather than restored, so a pane hidden by an over-eager drag
  cannot come back as a permanent hole;
* and the picture refits when the **label** resizes, not when the window does:
  dragging a splitter handle never fired the window's `resizeEvent`, which is why the
  preview used to stay at its old scale while its pane changed shape.

The fresh window default is **1180×780** (`xigmaui/settings.py`) - wide enough for
three columns, short enough for a 1080p screen - and the README's capture frames it at
1380×860. Both figures are asserted against the code by the suite, so neither sentence
can go stale.

### The preview plays, or shows one frame

Above the picture there is a `playing` box, and beside it a line that says what the
pane is actually doing (`Theme_25.mp4 at 24 fps, this pane redrawn at 8 fps`, or
`still frame; the pane is redrawn at 2 fps`). It is host-side and sends nothing: the
choice changes only what this machine decodes and composites, and the glass is never
asked what it is showing (§11) either way.

Two decode shapes, and the difference is measured:

* **still** (the old behaviour, and the fallback) asks `clips.frame()`, which spawns
  one ffmpeg and **seeks** to the middle of the loop. Right for a thumbnail, wrong for
  a loop: twelve frames that way cost an order of magnitude more than twelve out of one
  streaming process, and the seek is what would hitch.
* **playing** holds one `clips.ClipPlayer` open, reads raw RGBA frames in order, and at
  end of file restarts the process - so the seam the viewer sees is the file's own
  seam, which PROTOCOL.md §9 measures on the panel. Nothing seeks, because the panel's
  loop restarts at frame 0 too.

The rate comes from the file: `_ffprobe_look` now asks ffprobe for `r_frame_rate` as
well as the geometry, and the player paces by **wall clock** against it, because the
pane's redraw rate (2 fps by default) is ours and the clip's is the vendor's. Of the 43
clips the themes package installs, **23 are 24 fps and 20 are 20 fps** (the 20: 17 of
the 480×480 ones plus all three 320×240 files), so a hard-coded 24 would play a fifth
of the library at the wrong speed. One tick pulls as many frames as the elapsed real
time is worth, with the gap clamped at 1 s and the catch-up at 60 frames, so a window
that was suspended over lunch does not decode an hour in one click.

What it costs, timed on this bench with the window offscreen but live
(`sensors.collect` → `render.draw` → player → whole tick):

| what | per call |
|---|---|
| `sensors.collect()` | **71.8 ms** |
| `render.draw()` with fixed metrics | **11.9 ms** |
| one frame out of `ClipPlayer` | **1.06 ms** |
| pasting the layer over that frame (`copy` + `alpha_composite` + `convert` + `tobytes`) | **0.26 ms** |
| a resize of a 480×480 frame to the panel's own 480×480 | **0.02 ms** (PIL short-circuits an identity resize; a 320×240 frame costs 2.36 ms) |
| one background tick (`_play_tick`) | **0.54 ms** |
| one layer tick (`_repaint`, the old whole tick) | **85.6 ms** |

That table is the argument for **two clocks**, which is what the pane has now: the
layer is redrawn at `--preview-fps` (the expensive half, dominated by reading the
sensors) and the background plays on its own `QTimer` at the file's rate, pasting the
cached layer over each decoded frame. The first version drove both from the preview
timer, so the pane's redraw rate *was* the animation rate: at the author's saved
`preview_fps: 1.0` a 24 fps clip played as **1 fps of slideshow**, which is what a
reader would call broken, and the same pane measured at the default 2 fps showed
2 fps. After the split, the same window with the same 1 fps setting shows
**24.3 frames a second** (23.3 at a 2 fps layer), because a background tick costs
~0.5 ms and only the layer tick pays the ~86 ms.

Both rates are visible in the line under the picture - `background Theme_25.mp4
playing at 24 fps; our layer and the readings behind it redrawn at 1 fps` - and the
suite asserts the separation rather than the average machine: with the layer timer
stopped, a window at `preview_fps 1.0` has to move the picture at least ten times in
two seconds while its layer tick count does not move at all.

What rate you actually get depends on what else the window is doing, and both figures
are measured here rather than quoted as a spec: **24.3 fps** for a pane whose clip
library had finished its ffmpeg thumbnail pass, **19 fps** (40 frames in 2.1 s) for the
window the suite drives while the suite itself runs five other sections' processes
alongside it.  Frames are dropped rather than queued - `_advance` pulls as many as real
time is worth and keeps the last one, so a slow moment costs a frame of the animation
and never a backlog that plays later as a burst.

The rate is capped at 30 fps and floored at 5 (`_set_player`), because past 30 the
difference is not something an eye separates and every extra frame is a composite and
a paint; a file whose rate ffprobe will not give is played at 24 and the line says so. A hidden window decodes nothing at all: `hideEvent` stops
the preview timer and closes the ffmpeg, `showEvent` restarts both at the top of the
clip, and a `black` canvas never opens one, because on black the background shows
nowhere. Measured by watching the counters: 200 event spins with the window hidden
advance no frames.

The seam the viewer sees is the file's, not the pane's: the player never seeks, it reads the
same bytes in order and lets the file loop, and `Theme_25.mp4` is 0.9583 s, which
at 24 fps is 23-24 frames a pass (measured 24, then 23, then 23 - the last pass is short
by the fraction of a frame the resampler drops), and the **first frame of successive
passes is byte-identical** (`f7e5ded0b703` three times), so the restart never splices a
half frame together. That is the same loop the panel plays, and it is why the README's
the same loops the README videos replay,
measured there rather than assumed: the `alpha` video runs the 0.958 s clip 10.4 times in
its 10 s, so its restarts are the clip's own joins - which §9 measures at 2.50 against a
1.54 typical step at the clip's native rate, and docs/limits.md carries that table for
all five backgrounds, including `3.mp4`, whose loop *is* a hard cut (12.45 against 4.55).
A preview is only ever blamed for what it adds, and the suite holds each file to that.

### The advanced switch

A checkbox at the top of the controls column, default **off**, folds away six
secondary things: the `canvas` and `scrim` pickers, the fan-figures switch, the
display's event ring, the panel's own `conn 1` hello, and the "send frames for 30 s"
run. It is about pixels and nothing else - every hidden control keeps its value and
`Apply` sends it, which is what the suite checks by setting `scrim` while it is
invisible, restarting the window and reading the same 200 back. The choice is
remembered (`advanced` in the settings file), and the note beside the switch names
what is folded so a reader is never hunting for a control that exists.

The **guarded factory reset is deliberately not in there**. It stays on screen whether
the switch is on or off: hiding the one thing that can put a panel back to its default
would trade a wasted 90 px for a feature people search for when their panel has gone
white (docs/troubleshooting.md).

### The colour of the text

One row in the theme box, visible whether the advanced switch is on or not, because
"can I make it say a different colour" is a first-run question and not a specialist one.
The entries are `theme default`, this program's own seven palette colours - each with a
swatch, because "mint" is a word and the question is about a colour - and
`pick a colour...`, which opens the toolkit's dialog; a colour chosen that way gets its
own entry, labelled with its hex, so the choice stays visible instead of turning into a
string.

What it actually reaches is the ink of the glyphs **this program draws**:

* it lands in the preview as you pick it, and on the glass when you press Apply - one
  socket command, `text_color`, whose value the display answers back as the hex it kept
  (`text #ffc400` in the state line above), so the colour in force is readable and not
  remembered;
* one parser serves all three doors - `--text-color amber` on the command line,
  `{"cmd": "text_color", "value": "amber"}` on the socket, and the window's combo all go
  through `xigmalcd/render.py:parse_ink`, so they cannot drift into three different rules.
  Palette names win over the CSS/X11 table, deliberately: `red` here is this program's
  `#ff4040`, not CSS's `#ff0000`, and the suite asserts the whole name list against the
  module's own constants;
* the settings file keeps the hex form, so `#0f8` becomes `#00ff88`, `amber` becomes
  `#ffc400`, and a value the renderer would refuse (`cerise`) falls back to the theme's
  own ink the same way an out-of-range clock size does;
* `theme default` is not a colour, it is "leave the theme alone" - and for `alpha` that
  theme's ink *is* a measurement: its text measures white across the captured frames and
  its own layout files (PROTOCOL.md §10), so the default of the replica stays the
  replica.

Two measurements came out of building it, both off-glass and both re-derived by the suite:

* the ink changes the ink and nothing else.  Drawing `gauge` with an ink of pure red
  leaves its painted area exactly where it was (6 087 px before, 6 087 after) and moves
  1 509 solid white glyph pixels to 1 830 red ones with none left white; the same holds
  for all five themes (`alpha` 5 397 white → 5 397 red, 14 995 px painted either way).
  The arcs, bars and tracks keep their colours because those are graphics, and several of
  them are measurements of the vendor's;
* the upload path quantises to 256 colours by default (§12), which is the obvious place
  for a chosen colour to be lost.  It is not: through `to_png`'s palette encoding the
  inked pixel colour comes back within **1/255 per channel** for every colour the window
  offers.

What it does not do, said plainly because the combo invites the question: it does not
change the lettering of a **vendor** theme.  Those themes keep their text colour in their
own layout files, and the panel's firmware reads those; nothing in this project sends
one, so nothing here changes that.  And they are not all white, which is worth knowing
before choosing an ink to sit next to one: across the 23 480×480 layouts there are 106
`textColor` values in 9 spellings, 88 of them white, 18 of the 23 themes exclusively
white and 5 mixing in greys and near-blacks - the table is in
[docs/themes.md](themes.md).  And the panel is never told a colour either: the ink is in the
pixels before the upload, which is the only reason the option exists at all on a device
with no readback (§11).

**It has been put on the glass, and it is the colour that was sent.** On 2026-11-07 at
10:20-10:22 a display running from this tree at 1 fps took five inks over its control
socket - its own white, `amber` (`#ffc400`), the off-palette `#8a2be2`, `red`
(`#ff4040`), `mint` (`#00fae8`) - held 15 s each: **80 frames, 0 refused, 0 link errors**,
and `space` reading **67124 at every sample before and after**, because an ink changes the
pixels of a frame that was going to be uploaded anyway and costs the panel no room. The
author watched the panel through it and saw every change on the lettering about a second
after its command - the next frame at that rate - with each colour reading as the colour
that was sent. `#8a2be2` is the one worth naming: it is not a palette entry, so the only
thing between it and the glass was the loop's default 256-colour PNG encoding, which the
suite measures at 1/255 per channel and the eye agreed with. The run is kept as
`data/glass/2026-11-07-102041-ink-on-glass-watch.txt`; docs/limits.md carries the same
numbers and the two things still unmeasured - a dark ink over a bright clip, and this
command inside the two bench tools' own phases.

One mixed-version case, walked into rather than imagined: the installed **0.2** display
has no such command, so its `status` answer carries no text-colour field. The window
notices that and stops offering the choice -

* the row goes **inactive**, and its tooltip says why and how to make it live
  (`systemctl --user stop xigmalcd` and run this tree's `python3 -m xigmalcd`, or update
  the package);
* Apply still sends the six settings that display does know, in the same millisecond it
  always took, and says which one it left out: *"left text_color alone: the display
  running here does not report it, so it is older than this window. Everything else was
  sent"* - not a failure, because it is not one;
* the state line reads `text not reported by this display`, not the misleading
  `text theme default`: an old display and a new one sitting on its default answer that
  line differently, and the client knows which it is talking to because of what the
  answer contains (`xigmaui/daemon.py:knows`);
* the preview keeps the colour you picked regardless, because the window draws that
  picture itself and has never been a mirror of the glass (§11).

The suite drives exactly this shape - a display whose status lacks the field - and the 0.2
side of it is a kept transcript as well,
`data/glass/2026-11-07-095918-text-color-status.txt`.

One interaction to know about: the automatic scrim plate is a rule measured for
**white** glyphs over bright clips (`theme_48.mp4` at mean luma 227.3, plate at 150).
Choosing a dark ink over a bright field is a combination nothing here has measured, so
`auto` stays the daemon's white-ink rule rather than inventing a second one - if you pick
a dark colour over a bright clip, set the scrim yourself and judge it on the glass.

The same layer in motion, and its lettering in amber rather than the theme's white: a
10 s take over the vendored `Theme_25.mp4` at the panel's own 480 px, its numbers from
one real reading per displayed second, so the digits and the rings move while you watch.
It is the sixth file in `docs/videos/`, and README's five are made the same way over four
other clips.

https://github.com/user-attachments/assets/c119f478-eeb6-4a48-ac70-9c3fa0cd4f35

```
tools/preview_gif.py --theme alpha --clip media/Theme_25.mp4 --ink amber \
  --series docs/videos/readings-2026-11-08.json --frames 240 --gif-fps 24 \
  --scale 480 --no-gif --out docs/videos/alpha-Theme_25-amber.mp4
```

That is the same composite the `playing` pane shows - `ClipPlayer` in sequence,
`render.draw` on top - and the same recorded series behind all six files, so they show
one minute of one machine rather than six separate guesses. What the encoding does to the
ink is measured off the file: of the **2 268** pixels that layer
paints at exactly `#ffc400`, the written file puts **1 144** within 3/255 (median 3, mean
4.3), **2 187** within 8/255 (95th percentile), and **81** still at the exact value. The
tail is thin: 19 pixels sit more than 16/255 away, the worst 227, which is what half-
resolution chroma does to a hairline stroke over a moving picture. That is H.264 at crf 20 quantising in YUV 4:2:0 - it keeps a large flat run of
saturated colour closely without keeping any one value. The GIF path asks a different
question and gets a different number: the closest colour *present anywhere in* a
160 px/6-frame/128-colour GIF written in the same suite run is **(252, 197, 2)**, 3/255
from what was asked. Neither is the 256-colour PNG the upload path sends, whose drift
§10 measures at 1/255 per channel. And nothing here was put on glass to be photographed:
the panel cannot be asked what it shows (§11), so this is our compositing, encoded.

### Two shortcuts, and why they are the ones they are

`Apply these settings` is Ctrl+Return, the upload button is Ctrl+Shift+U. The second
of those was Ctrl+U first, and the bench measured why it cannot be: with the button
holding a bare Ctrl+U, pressing Ctrl+U in the **filter field directly above it** queued
an upload and left the field's text alone. Qt's `QLineEdit` binds nothing on Ctrl+U -
the muscle memory behind that key comes from readline - so the keystroke went to the
panel path instead of to the text the reader was editing. On Ctrl+Shift+U the button
still fires and the field is untouched, which is the pair the suite now checks.

### What the window can and cannot tell you about the background

There is no readback from this panel (PROTOCOL.md §11), so the one sentence that
matters - *what is the picture under our frame right now* - cannot be asked of the
device. What it can be read from is the running display's own event ring, the last
twenty things it chose to record about the port, which every status reply carries:

```
07:51:50 queued upload: /usr/share/xigmalcd/themes/alpha/clips/theme_47.mp4
07:51:51 background theme_47.mp4 accepted
```

Both halves of that are load-bearing, and the window now shows the ring (under
"The running display") plus the derived line (`the panel stores: theme_47.mp4`) -
because a socket `upload` answers `ok` in milliseconds and that `ok` only means
the file got into the loop's one action slot. The verdict is the second line.
In the list itself, the row for that clip is drawn **bold**: in a 40-row library
(161 files behind it, before the copies were collapsed) that is the fastest way to see whether the
row you are looking at is the picture the panel is storing under our frame, and no
row is bold when the display has not reported one.

The bench found the cost of not having that readout, and it is worth writing down
because it looked like a broken feature rather than a missing label: a background
was picked from the list **three times**, three different clips, and the panel kept
drawing the picture it already had. Nothing on screen said why. What had actually
happened is that `Apply these settings` had been pressed each time, and Apply sends
the settings - on that build six of them, theme, clock size, canvas, scrim, fans, fps,
and the text colour since - and *never a file*, by
design, because a background upload overwrites what the panel stores and only the
guarded factory reset undoes that. Picking a row is a selection; the clips box is
what sends it. Three things came out of that afternoon, all in the window now:
the one state line, the ring, and Apply saying out loud which background it left
alone. The author's own `~/.config/xigmaui/config.json` at 07:33 holds
`clip: /usr/share/xigmalcd/themes/alpha/clips/theme_47.mp4` and `clock_size: 30`,
which is the fingerprint of those three picks: the clip moved, the glass did not.


The twice-per-session metrics blob is not decoration: PROTOCOL.md §8 measures that
`STATE all 1` goes out at the head of a session and nowhere else (TX frames 3 and 4 of
the vendor's 51-frame init capture, and no `STATE` frame at all in its 63-upload media
capture), and that a session fed the blob per frame stops answering the media channel.
So the GUI pushes it in `_open()` and never between files, and a session *renewal*
re-helloes without pushing it again, which is what `main.rehandshake` does. The blob is
the host's own readings - Super-IO tachs and temperatures, `nvidia-smi` - and the fan
line's checkbox decides whether the `fans` array is in it or left out, the same rule as
`--no-fans`. Over the socket the same rule is the `fans` command, which flips the
daemon's own `--no-fans`, so the picture's two fan figures and the blob's `fans` array
cannot be argued apart from the window.

Five things it deliberately does not pretend to be:

* **The preview is our composite, not a mirror.** This panel cannot be read
  back: every `GET` variant we have tried simply does not answer, which our
  client reports as its own timeout string, `no reply for request N` - that
  message is ours, not a panel reply, and PROTOCOL.md §11 records the silence.
  So the window draws the two layers itself, the way `tools/previews.py`
  composites the README pictures, and says so under the pane: *"this panel has no
  readback, so it is not a picture of the glass."*
* **A picker, not the vendor's theme editor.** Dragging widgets around would be
  weeks rather than days, because the panel renders nothing itself (§11): the
  theme JSON declares widgets and the firmware ignores them, so an editor means
  drawing every widget in Python and shipping the result as frames. The theme
  pane offers the five themes this repo draws, with the daemon's own options.
* **No storage gauge.** The status pane prints `space` as a number with a note
  that it is not a size ledger: across four accepted uploads it moved a few KB
  in either direction and never resembled the file's size (§9).
* **Not a second owner of the port.** One process can hold it. When a display is
  running the window never opens `/dev/ttyACM0` at all - every action has a socket
  route, and the offline check for that path counts `port_busy` being consulted
  zero times. When nothing is running it holds the port only for the action you
  asked for (open, `hello`, act, close), and if a third process holds it the action
  refuses with that holder's pid (`fuser`) and says how to let go of it: Ctrl-C,
  `systemctl --user stop xigmalcd`, or `fuser -k /dev/ttyACM0`. That is also the log
  line you see when you forgot.
* **The glass does not follow your mouse.** Pickers move the preview; the panel only
  changes on `Apply these settings`, the tray's theme menu, or a send button. That
  is deliberate: with no readback there is no undo (§11), so the hand-off to the
  glass is one deliberate click, and its cost is one line in the log - what the
  daemon was told, in the daemon's reply.

Two side effects worth knowing, because they are writes and not reads:

* Asking for status sends `power resume` and `timeout 60`, so opening this window
  wakes a blanked panel and re-arms the vendor's 60 s idle timeout. That is what
  the daemon's `hello()` does too.
* Reset is the real vendor reset. It drops the stored picture, the USB device
  re-enumerates (seen here ~3 s, ~9 s in the vendor's own log), and uploads
  afterwards would start with `1 400` until the link is renewed - so the GUI
  closes the port, waits for the node to reappear, and reads status again
  rather than carrying on with the old session. The reset command — `xigmalcd-reset --yes`
  on an installed system, `tools/reset_panel.py --yes` in a checkout — is the same frame
  if you would rather see every byte. **With a display
  running, the button is refused** unless that display was started
  `--allow-reset`: the window does not go around a gate, it quotes the reason
  the daemon gave.

Session handling belongs to whoever holds the port, because the panel exhausts an
upload session on **both** axes: about 500 uploads (measured twice, at exactly 500)
and about 300 s of session life (silence at ~370 s at 2 fps, PROTOCOL.md §9). So
`_live()` renews
when either `main.SESSION_MAX` uploads or `main.SESSION_TTL` seconds have passed since
the last renewal, whichever comes first - a 1 fps run reaches the clock first, which is
why counting uploads alone was not enough - renews again after `RECOVER_AFTER` protocol
failures, and stops on its own after `REFUSE_GIVEUP` refusals in a row, because a panel
that answers commands but refuses every file is not cured by reopening (§6), and
spending the rest of the window on a dead channel teaches nothing. If the port
disappears at a renewal - the panel re-enumerated, something else took the port - the
run logs that and stops rather than sending into nothing.

In remote mode all of that is the daemon's, and the window's two contributions are
`pause` and `resume`: while paused nothing at all goes out on the wire, and `resume`
re-helloes - re-opening the port first if the pause outlasted `--session-ttl`, which
is the clock the measured silence arrives on. A short pause needs only the hello,
which is also what wakes a panel that blanked after its 60 s `timeout`.

**What has met hardware through this window, and what has not.** Four of the five
paths have, driven by `tools/gui_glass.py` - a driver that queues the actions
through `xigmaui.panel.Panel`, the same worker the buttons use, so these are
numbers about the GUI's paths rather than about the CLI that already works. Three runs
on 2026-11-06; the first, 13:25:31 to 13:26:06:

| action | what the panel said | what the glass did |
|---|---|---|
| status | `conn 1` with all fourteen fields, twice (`sn=<this panel's serial, redacted>`, app V1.0.2, firmware V1.2.3, hardware V2.0, `space 62428`, `brightness 100`, `logo 3`, `mode 0`, `osdState 1`, `timeout 60`) | writes, not reads: `conn 1`, `power resume`, `timeout 60` |
| upload background | notice `200`, 214 917 B in 0.4 s, `space 62428 -> 62424` | the clip played, seen by eye |
| one frame | notice `200`, one 9 KiB `.osd` PNG | the alpha overlay was on the glass |
| live 30 s at 2 fps | **60 sent, 0 refused**, no session renewal needed at this length | overlay present for the whole window |
| reset | not sent, by the owner's choice | not observed |

One caveat about that ledger, so it cannot mislead: the 13:25 run predates the metrics
blob. Those three drawing rows went up with **no `STATE all 1` in front of them**, which
is why the window was wrong about its own traffic until it was fixed. The follow-up run
below is the one that shows the blob on the glass. Its other weakness is on the record:
that run's raw log was not kept, so the table above is the only artifact of it. The
second run's log is in the repo, which is how the numbers there can be checked.

**Second run, same day, 14:26:45 to 14:27:08** - `tools/gui_glass.py --no-upload
--live-seconds 20 --fps 2`, chosen so nothing was overwritten on the panel, its whole
output kept as `data/glass/2026-11-06-142650-gui-blob.txt`. This is the
glass half of the metrics fix, and the question it answers is whether pushing the blob
at a session head disturbs the media channel, since feeding it per frame does (§8):

| action | what the panel said | what the glass did |
|---|---|---|
| status (baseline) | fourteen fields, `space 62424`, `logo 3` | nothing drawn |
| one frame | `STATE all 1` twice at the session head, then a 9 KiB `.osd` at notice `200` | the alpha overlay appeared |
| live 20 s at 2 fps | `STATE all 1` twice at the session head, then **40 sent, 0 refused**, no renewal needed at this length | overlay present for the whole 20 s |
| status (after) | fourteen fields again, every one identical: `space 62424`, `logo 3`, `mode 0`, `osdState 1`, `timeout 60` | - |

So: four `STATE all 1` pushes in two sessions, every one before that session's first
file, and 41 uploads accepted with no refusal and no session renewal. The blob at a
session head costs the media channel nothing, which is the shape both `xigmalcd` and
`xigmaui` now use. A second thing this run re-confirms from §9: `space` did not move by
a single unit across 41 `.osd` frames, so it is not a ledger of frame uploads.

**Third run, same day, 14:42:46 to 14:42:50** - `tools/gui_glass.py --live-seconds 0`,
so the whole-file path ran with the blob in front of it and the frame loop did not. Log
kept as `data/glass/2026-11-06-144246-gui-mp4.txt`. This closes the hole the run above
left; the file re-uploaded was `media/Theme_25.mp4`, which the panel already held, so the
background on the glass did not change:

| action | what the panel said | what the glass did |
|---|---|---|
| status (baseline) | fourteen fields, `space 62424`, `logo 3` | nothing drawn |
| upload background | `STATE all 1` twice at the session head, then the whole 214 917 B file: notice `200` in 0.4 s, **`space 62424 -> 62416`** | the stored clip kept playing (same file it already had) |
| one frame | `STATE all 1` twice at a new session head, 9 KiB `.osd`, notice `200` | the alpha overlay appeared |
| status (after) | fourteen fields: `space 62416`, everything else identical (`logo 3`, `mode 0`, `osdState 1`, `timeout 60`, `brightness 100`) | - |

Two facts come out of that. The blob does not disturb the whole-file path either: the
214 917 B upload is accepted 0.4 s after the announcement, exactly as it was in the 13:25
run with no blob in front of it. And `space` moved by 8 while a stored MP4 was
re-uploaded under the same name, where the 13:25 upload of that identical file moved it
by 4 and an earlier same-name overwrite of a 659 KB clip moved it by 20 - so the
replace-not-add behaviour PROTOCOL.md records holds, but the step is not a constant and
certainly not the file's size. The split between the two kinds of upload is now measured
rather than assumed: `space` ignores `.osd` frames completely and ticks down a little
when stored media is replaced.

The one gap left in that ledger is reset, and it is a decision rather than an
oversight: `Panel._reset` is the vendor's `recovery`, the only destructive thing
in the app, so it stays covered only by the offline checks (the gate refuses
without the typed word, and exactly one of the stubbed opens in the whole block asks
for a destructive link) and by the reset command, which sends the same frame from
the command line where every byte is printed (`xigmalcd-reset` from a package install,
`tools/reset_panel.py` from a checkout). The four actions above are also the
same functions the CLI has already proven - `main._upload_background`,
`Link.send_media` in the `notice` order - but they were reached through the GUI's
worker this time, which is the part that had not been pressed. One thing does
differ from the CLI on purpose: the GUI uploads whatever MP4 is selected in the
picker, and that is a whole-file overwrite of what the panel stores.

**The other half of that ledger: the always-on path.** Every number above came from the
window visiting the port. The continuous model - a display process holding the port and
drawing, a client changing what it draws over the control socket - has now been driven
through the panel six times on 2026-11-06 by `tools/display_glass.py`, in
`data/glass/2026-11-06-154148-socket-run.txt` (15:41:48-15:50:31),
`data/glass/2026-11-06-155135-socket-run.txt` (15:51:35-16:00:17),
`data/glass/2026-11-06-160240-socket-run.txt` (16:02:40-16:11:22) and
`data/glass/2026-11-06-161444-socket-run.txt` (16:14:44-16:23:27), which ran their full
window, `data/glass/2026-11-06-165549-socket-run.txt` (16:55:49-17:00:58), which was
watched by a person and then stopped by them part way through, and
`data/glass/2026-11-06-180109-socket-run.txt` (18:01:09-18:09:51), the same full window run
again after the alpha theme's gauge rings went in. Each run started its
own `xigmalcd --fps 1 --duration 520 --session-ttl 300` on a socket of its own
(`xigmalcd-glass.sock`, never the login unit's) and then did nothing but behave like a
client: `status`, Apply as six commands, `pause`, one `frame` while paused, `resume`, a
queued background upload, an on-purpose `reset`, and then a wait for the loop's own
session renewal. Only the fourth also ran `python3 -m xigmalcd --status` as a separate
process; the first three meant to and did not, which is spelled out below.

What those four windows measured, counters and notices only:

| phase | what the panel answered |
|---|---|
| the loop drawing | four 520 s windows at 1 fps, one process each. In the fourth one a **second process** ran `python3 -m xigmalcd --status` against the running display and printed its counters - `24/24 frames confirmed, 0 refused` - without the reader ever opening the port; in the first three that phase was mis-wired to the driver's own socket read, see below |
| Apply | the six settings commands and a title in **0 ms**, all four times; the counters said `showing gauge` from the next poll on and stayed `gauge` for the rest of each run |
| `pause` | **0** frames and **0** confirmed uploads moved in 20 s, in all four runs, while the session the process held aged from 48 s to 64 s (and to 69 s by the time the next phase asked for a frame); the counters read `paused gauge` throughout |
| `frame` while paused | **+1** upload, still `paused=True`, in all four runs - and it renewed on the way: `~ session restored` at 15:43:00 / 15:52:46 / 16:03:51 / 16:15:56. Runs 2-4 also carry the daemon's own note `resumed after 69 s idle: session renewed`; run 1's log has that note for its `resume` (15:43:04) but not for this forced frame, and nothing in the tree records what changed between those two runs, so run 1's evidence is the restored-session line plus counters reading `session 1 uploads / 4 s` right after a session that had aged to 69 s. A `frame` is not a `resume` |
| `resume` | 1 re-handshake each time, then 20 uploads |
| queued `upload` | the request reached the loop and the panel's verdict came back every time - four different answers: `400` with an empty body at 15:43:24 and taken on the retry in 2.0 s; **both** attempts refused at 15:53:11-15:53:12, the daemon logging `background Theme_25.mp4 did not land: the panel keeps whatever it already has stored` and carrying on drawing; refused once at 16:04:17 and taken on the retry 2.0 s later; and taken on the first attempt at 16:16:21. The client read its own event in every case (`accepted` or `did not land`) |
| `reset` | asked on purpose, refused in the daemon's own words, because that display was started without `--allow-reset` |
| the session clock | `session renewed after 299 uploads, 300 s` (15:48:04), `after 295 uploads, 300 s` (15:57:51), `after 299 uploads, 300 s` (16:08:56), `after 301 uploads, 301 s` (16:21:01): the renewal came from the clock every time, not from the panel failing, and drawing continued through all four |
| the whole window | **496 of 496** confirmed in the first run (0 refused), **492 of 496** in the second - see below - **496 of 496** in the third and **498 of 498** in the fourth, the last two printing `== every phase checked out` |

Two things those logs also record, because they are the driver's own failings rather than
the panel's: the first two runs **exited 1**, and in both cases the reason was the check,
not the glass. Run 1's upload phase judged the file by the socket's queue slot emptying,
which happens before the loop thread starts the upload, so it called a file that landed two
seconds later a failure; run 2 counted the panel's refusal of a background as this path
having failed. Both are fixed in `tools/display_glass.py`, which now waits for the daemon's
own `background <name> accepted` / `did not land` event and writes a refusal down as what
the panel answered. The last two runs are the ones that ran with those fixes in place.

And one claim above that the first three logs do **not** support, found by
`tools/selftest.sh` rather than by reading: the phase named "the command-line client" was
wired to the same body as the plain status reads, so the subprocess that runs
`python3 -m xigmalcd --status` was never started, and those three logs contain no line from
it. The driver has a phase kind of its own now, and the selftest compares the driver's phase
table against its table of bodies so a phase cannot silently point at the wrong thing again.
The fourth run is the one that shows the separate client: three lines from the subprocess,
counters included, and the display never noticed the difference.

**A fifth window, which nobody drove.** After the 0.2 upgrade, the packaged user unit
started on its own (docs/packaging.md keeps that story, including what is not established
about it) and drew unattended for **56 minutes up to where this file stops** - the unit was
still running when it was read: `/usr/bin/xigmalcd --theme alpha --fps 2`, one process,
`NRestarts=0`. The evidence is the unit's own journal plus reads
over the control socket, kept as `data/glass/2026-11-07-072155-service-2fps-journal.log`,
and it is thinner by design than a `tools/display_glass.py` log: no phases, no per-frame
byte sizes. `tools/selftest.sh` re-derives every number in the table below out of that
file rather than trusting this prose. What it says, at two instants of the same process:

| | at 13.9 min (07:36) | at 47.7 min (08:09) |
|---|---|---|
| uploads | **1 667** in 13.9 min at 2 fps: **1 664 confirmed, 3 refused**, 0 link errors | **5 726**: **5 720 confirmed, 6 refused**, 0 link errors |
| session renewals | 3, each logged `session renewed after 500 uploads, 250 s` - the packaged unit passes no session flags, so this is the defaults, and at 2 fps the **500-upload** limit is what fires: 500 uploads is 250 s, inside the 300 s age limit (`--session-max`, `--session-ttl` in the options table) | 11, all on the same 500-upload limit, 250-251 s apart |
| the uploads the panel refused | all three are `device refused the file: 400 b''` on ordinary frames (**1029, 1097, 1167**), ~34 s apart, in the 4 minutes after a renewal | seven by the time this file was closed at 08:18:02: **1029, 1097, 1167, 2268, 3162, 3266, 6471** - the same shape, spread over 56 min, each followed by a frame that landed |
| backgrounds | `Theme_25.mp4 refused (device refused the file: 400 b''); retrying once` at 07:21:57, then `214 917 B -> notice 200 in 2.3 s, space 69084 -> 69104` at 07:21:58 - the retry path doing its job, and the same `400 b''` answer as the frame refusals | two asked for over the control socket, and this is the first time this project's *packaged* path has been driven through an upload rather than watched: `theme_47.mp4 1 211 106 B -> notice 200 in 1.0 s, space 69100 -> 67844` at 07:51:51 and `1757492775624.png 3 409 B -> notice 200 in 0.3 s, space 67844 -> 68032` at 07:54:09. Both files come from the themes package (`themes/alpha/clips/`, `themes/alpha/foreground/`). Whether the panel *displays* a still PNG is a glass question this file cannot answer (§11); what it answers is the notice |
| what it costs | `CPUUsageNSec=75 192 540 000`, `MemoryPeak=36 003 840 B` (36.0 MB), `NRestarts=0` → **45.2 ms of CPU per confirmed frame**, **9.0 % of one core** sustained at 2 fps | `CPUUsageNSec=270 998 249 000`, `MemoryPeak=36 048 896 B` (36.0 MB), `NRestarts=0` → **47.4 ms of CPU per confirmed frame**, **9.5 % of one core** |

The two cost rows are the same process measured twice, and they agree: about 45-47 ms
of CPU a frame. That is worth setting beside the window's Cost section, which measures
`render.draw` at 12.4-14.1 ms and draw-plus-PNG-encode at about 23 ms, because a preview
neither writes the metrics blob nor pushes a file nor pumps a serial session. The real
path costs roughly twice that, and 9 % of a core sustained is still nowhere near the
reason to think about the frame rate - the reason is the upload count (172 800 a day at
2 fps against 86 400 at 1, the `--fps` row in the options table). Nothing in the 56 minutes
this file covers restarted the process, lost the port, or reported a link error.

Two honesty notes, both of them learned rather than assumed:

* the counters of that 48 minutes are steadier than the picture was. Two reads four
  minutes apart reported different settings - `clock 44` at 07:26 and `clock 30` at
  07:30 - while the packaged `ExecStart` passes no `--clock-size` at all. That one is
  now explained rather than open: the author's own window sent both, one `Apply these
  settings` each, and `~/.config/xigmaui/config.json` carries `clock_size: 30` from the
  second. So this window supports statements about counters, renewals, uploads and cost,
  and still not about what the glass looked like frame by frame;
* the seven refusals are **not** those three background picks. A background request that
  reaches this process leaves two records - a `queued upload: <path>` note in the ring
  and a `background <name> …` line in the journal - and there is neither anywhere between
  07:21:58 and 07:51:50, which is the window those picks fell in. The wording separates
  the paths on its own: the frame loop prints `! frame N: device refused the file`, while
  a refused clip prints `background <name> refused (…); retrying once`. The picks never
  reached the port at all (see "What the window can and cannot tell you"), so the seven
  refusals stay unexplained, and [Notes and known limits](limits.md) keeps them that way.

The fifth window is the watched one, and it is also the one that caught the driver being
dishonest about itself. It ran 16:55:49-17:00:58 and had reached the renewal wait when the
owner stopped it with `^C`. What it measures, with a person watching: `--status` from a
second process again (three lines, `24/24 frames confirmed, 0 refused`), Apply in **0 ms**
with the counters reading `gauge` from the next poll on, 20 s of `pause` moving **0** frames
and **0** uploads while the session aged from 48 s to 64 s, one `frame` while paused
(+1 upload, still paused, `resumed after 69 s idle: session renewed` at 16:57:00), `resume`
with one re-handshake and 20 uploads, a queued `Theme_25.mp4` refused at 16:57:25 and taken
on the retry 2.0 s later (`space` 61136 -> 62220), and `reset` refused again. It ended at
**282 of 282** confirmed, 0 refused. What it does **not** measure is the loop's own TTL
renewal: the session had just been brought up to date at 16:57:05, so the next renewal was
due near 17:02:05 and the window ended at 17:00:58 with the wait still running.

That log claims otherwise, and the claim is the bug. `^C` landed inside the renewal phase,
the phase loop fell out to the summary, and the summary printed `== every phase checked
out` and exited 0 about a renewal that had never happened. Fixed in `tools/display_glass.py`
(an interrupt now names the phase it stopped in and adds it to the run's own list of what it
did not show, so a stopped window exits 1); `tools/selftest.sh` reads the handler to check
it does that, and reads the kept logs as two kinds - windows that ran to their own end, and
this one, cited only for what it reached.

**The sixth window exists for one number: what the rings cost on the wire.** It ran the same
full window at 18:01:09-18:09:51, after `theme_alpha` had put a gauge arc around each
temperature. The alpha stretch is the first 60 s (`LIVE alpha`, before Apply switched the
display to `gauge` like every previous run), and inside it the counters read **29 of 29**
frames confirmed, **0 refused**, at 1 fps - so the bigger picture was taken by the panel at
the vendor's own rate without a single refusal. The daemon logs every tenth frame, and that
is the measurement: three logged alpha frames of **44 489 B**, **44 388 B** and **46 014 B**
at frames 0, 10 and 20 - 44 388-46 014 B in that phase - against **30 710-32 157 B** for the
same theme and the same canvas in the 16:14:44 window before the rings went in: about +13 KB
per frame, **+44 %**. The `gauge` frames in both runs are the control on the link itself,
23 193-27 668 B now against 24 160-27 763 B then, so the growth is the rings and not
something that happened to the wire. The rest of the window behaved like the earlier ones: Apply in **0 ms**,
20 s of `pause` moving 0 frames and 0 uploads, one `frame` while paused (+1, still paused),
`resume` with one re-handshake and 20 uploads, the queued `Theme_25.mp4` accepted on the
first try at 18:02:54 (`space` 62024 -> 61896, notice `200` in 0.4 s), `reset` refused, the
CLI client answering over the socket, and the loop renewing its own session at
`session renewed after 300 uploads, 301 s` (18:07:35) and carrying on drawing. Two frames
were thrown away across the whole window - `! frame 173` at 18:04:27 and `! frame 388` at
18:08:03, both `400` with an empty body, both alone rather than in a row, so
`RECOVER_AFTER` never fired. It ends **496 of 498** and prints `== every phase checked out`.
No person is recorded as watching this one, so its glass column is counters and bytes: the
rings' legibility on real glass - 12 px of stroke at 97 px radius, the colour ramp, and
whether `CPU FAN 1957 RPM` at font 20 reads from the chair - is still an eye's judgement and
has not been made.

The second run's four missing frames are the more interesting half. They arrive in the
40 s after that refused upload - `! frame 78`, `98`, `105`, `116`, each
`device refused the file: 400 b''` - never two in a row, so `RECOVER_AFTER` never fired
and nothing re-handshaked; the next 380 frames were taken without a refusal. So a
refused background and a cluster of refused frames can share a window, and neither one
stopped the picture: that run's last counters were 492 confirmed with the clock still
moving. It also caught a bug in its own bookkeeping: those refusals reached us as an
exception rather than as a notice code, so they went into `frames` but not into
`refused`, and `--status` was reading `0 refused` beside a log with four in it. The fix
is in `xigmalcd/main.py` (the `except ProtocolError` branch), and it is honest to say
what proves it: **not** the two clean runs that followed, which had no refusals at all
(496 of 496 and 498 of 498, 0 refused, so the two counters agree there but nothing was
exercised). What pins it is a test in `tools/selftest.sh` that runs the real loop against a
stub panel which throws away every fourth file - it refuses them the way the panel did, as
`device refused the file: 400 b''` out of `send_media` - and then reads the counters the way
a client does, from inside the loop. The section prints its own arithmetic, so the figures
are measured rather than asserted: 23 files asked for, 5 thrown away, the run printed
`18/23` and said `! frame` five times, and in all 18 client polls `refused` equalled
`frames - ok` while `errors` stayed a streak (max 1). The exact counts move with timing;
what the test insists on is that `frames - ok == refused`, that the `! frame` lines and the
counter agree, and that spread-out refusals never end the run. Finding the case on real
glass was luck, and two runs not reproducing it is the same panel being uncooperative in the
other direction; both are written here rather than papered over.

And the honest limit of these six: **only one of them had a person looking.** Everything
in the table is what the panel answered, not what it showed; the per-phase `title`
labelling exists so that a person looking at the unit can name what they are looking at,
and in the five full windows it went unobserved. The eye-witness rows in the table above
belong to the 13:25, 14:26 and 14:42 runs, which were watched while they ran. The fifth
socket window was watched, and the watcher's verdict was "everything looks good" - which
covers the 1 fps drawing, the theme switching on Apply, the freeze through `pause`, the one
frame drawn while paused, and the clip being handed over, all of it under headings naming
the phase. That verdict is deliberately recorded as coarse: it is one sentence over a whole
window rather than a note per phase, and it stops where the window stopped, so it says
nothing about a session renewal or about a long run. The glass column of the always-on path
is therefore "a person watched a window and it looked right", not a row-by-row account.

What has been watched since, outside those six, is the picture itself: a one-process loop at
120 s and 1 fps with `--title "EYEBALL ALPHA"`, which the owner watched and described as
"everything looked good" - both fan figures with real numbers, both arcs partly filled. That
closes the legibility question for the ringed `alpha` at its normal mid-range state, and
nothing more: no log was kept for a run started in a terminal, so it is an account rather
than a ledger row; it is not one of the six socket windows, so it says nothing about Apply,
`pause`, renewal or upload; and it did not exercise the extremes listed in the gauge note
below. To fill the row-by-row account properly:

```bash
python3 tools/display_glass.py --fps 1 --duration 520 --baseline 25 --applied 25 \
    --paused 20 --resumed 20 --session-ttl 300 --wait-renewal 340 \
    2>&1 | tee data/glass/$(date +%F-%H%M%S)-socket-run.txt
```

That is the window the first four ran (~9 min, the last 340 s of it waiting for the
loop's own renewal); the fifth full one ran the same phases at the driver's own defaults -
30 s of baseline and applied, 330 s of renewal wait - and its renewal arrived 282 s into
that wait, at `session renewed after 300 uploads, 301 s`. Either way the port must be free
when it starts: it refuses to run if something already answers on its socket or holds the
port.

For the one thing a window of that shape can only show for a minute - the `alpha` picture,
which Apply replaces with `gauge` after ~30 s - the shorter way to put the ringed theme in
front of a person is the plain loop, and it has been run twice: 30 s at 3 fps on 2026-11-06
at 18:12:51, **91 of 91** frames confirmed
(`data/glass/2026-11-06-181251-fps3-alpha.txt`), and a 120 s window at 1 fps with
`--title "EYEBALL ALPHA"`, which is the one that was watched. What the 3 fps log cannot say
is whether that picture read well, because nobody was recorded as looking at that one:

```bash
python3 -m xigmalcd --theme alpha --fps 1 --duration 120 --no-mp4 --title "EYEBALL ALPHA"
```

The same plain loop is also how the two encoders were put on the glass for one picture. The
first attempt, on 2026-11-06, settled the panel's half and missed the human one: three windows
straight after each other - RGBA for 60 s at 20:17:08 (**61 of 61** frames, 42 585-45 040 B
each), the same frame 256-colour with `--palette` for 60 s at 20:18:13 (**61 of 61**,
12 342-13 699 B), RGBA again for 30 s at 20:19:17 (**31 of 31**, 42 001-45 597 B) - and nobody
was at the glass for any of them, so their logs say so in their own headers
(`data/glass/2026-11-06-201708-encode-A-rgba.txt`,
`data/glass/2026-11-06-201813-encode-B-indexed.txt`,
`data/glass/2026-11-06-201917-encode-A2-rgba.txt`). What that pair of RGBA windows against the
indexed one established is that a transparent 256-colour overlay of the ringed picture is
accepted exactly like the RGBA one, nothing refused, means **43 304 B against 12 655 B**.

The same three windows, run again an hour later with a person at the panel, settled the rest:
RGBA 60 s at 00:24:34 (**61 of 61**, 42 560-46 415 B), `--palette` 60 s at 00:25:40 (**61 of
61**, 12 169-12 401 B), RGBA 30 s at 00:26:46 (**31 of 31**, 41 856-42 471 B), each with its
encoder in the on-screen heading so nobody had to be told which was which. The owner's account
is **"no difference I could see"** - no steps in the arc's colour fill, no less solid text - and
the CPU sat at 45-49 °C across all three, so both arcs were filled a little under half: the
mid-range case, not the red end of the ramp and not three-digit values
(`data/glass/2026-11-07-002434-encode-Awatch-rgba.txt`,
`data/glass/2026-11-07-002540-encode-Bwatch-indexed.txt`,
`data/glass/2026-11-07-002646-encode-A2watch-rgba.txt`).

So the smaller file won, and the two owners of the port now agree: `xigmalcd` uploads the
256-colour PNG on every canvas, which is what `xigmaui/panel.py` has always done, and
`--truecolor` is how the exact RGBA file is put back on the wire. One window confirms the new
default end to end: `ENCODE DEFAULT` at 00:32:17, no encoder flag given, **31 of 31** frames at
**12 322-13 372 B** where the same theme as RGBA had logged 42 560-46 415 B
(`data/glass/2026-11-07-003217-encode-DEFAULT-indexed.txt`). The offline cost of that choice is
written down rather than hidden - the gauge ramp is drawn in 80 colours and comes back in 13,
one flat colour every ~12 px of arc, and 11 149 fully opaque pixels come back with only 74 of
them still at alpha 255 - and `tools/selftest.sh` prints those numbers on every run, so the
trade cannot quietly go stale. To repeat the comparison:

```bash
python3 -m xigmalcd --theme alpha --fps 1 --duration 60 --no-mp4 \
    --title "ENCODE A RGBA" 2>&1 | tee data/glass/$(date +%F-%H%M%S)-encode-Awatch-rgba.txt
python3 -m xigmalcd --theme alpha --fps 1 --duration 60 --no-mp4 --palette \
    --title "ENCODE B INDEXED" 2>&1 | tee data/glass/$(date +%F-%H%M%S)-encode-Bwatch-indexed.txt
python3 -m xigmalcd --theme alpha --fps 1 --duration 30 --no-mp4 \
    --title "ENCODE A2 RGBA" 2>&1 | tee data/glass/$(date +%F-%H%M%S)-encode-A2watch-rgba.txt
```

Nine minutes of `alpha` rather than a minute of it, with headings naming what each phase
is, is the `LIVE alpha` phase made longer: add `--baseline 300` to the command above and
the first five minutes of the window are the ringed theme at 1 fps, still driven over the
socket, still logged.

Cost, measured on this box and re-measured by `tools/selftest.sh` (it prints the
numbers it just got, so these cannot quietly go stale). The picker lists every clip the
roots hold, and lists each **distinct file** once: **40 rows here, out of 161 mp4
files** - 3 vendored in `media/` and 37 from the vendor's library. The other 121 files are
copies, and where they live is worth naming, because they are three different kinds of
copy: **69** in the Windows app's own upload history (`AppData/Roaming/alpha/media/`),
**43** in the vendor's static media on the mounted partition, and **9** copies the
installed packages left next to files already listed.

**35 of those copies have a different filename from the row they duplicate**, and that is
the whole reason the rule is length-plus-content rather than name-plus-length. The first
pass at this - keyed on `(name, size)`, added when the two packages started overlapping
the checkout - left **69 rows for 161 files**, because the Windows app re-copies a library
clip into its `media/background/` under a millisecond name every time a theme is applied:
`1757491589240.mp4` *is* `Theme_25.mp4`, and **all 26** `175749*.mp4` files there are
byte-identical (whole-file sha256, audited 2026-11-07) to a `Theme_NN`/`theme_NN` clip.
They are not junk, either: the vendor app's own `store.json` names 31 of them as
`recentUsedTheme[].background.path`, which is why this project collapses them in its own
list rather than deleting anything on that volume - the Windows app would then be holding
paths to files that are not there.

The vendor library repeats itself as well, and this repository carries the repeats because
the themes package is the library as the vendor ships it, manifest included: **43 clip
files, 40 distinct** - `Theme_31.mp4` == `Theme_26.mp4`, `theme_38.mp4` == `Theme_27.mp4`,
`theme_51.mp4` == `Theme_29.mp4` (whole-file sha256). Those files stay in the tree, where
the suite verifies every byte against the manifest; in the picker they are one row each.

How the comparison works, since it decides what disappears: same length first, then
sha256 of the first and last MiB. For anything up to 2 MiB those two windows *are* the
whole file, so 27 of the 40 distinct clips here are matched exactly; the 13 larger ones
are matched on length plus both edges, and nothing in this library differs only in its
middle. The audit that produced the figures above used whole-file sha256 on all 161 files,
which is also how the 40 was cross-checked: the list the window builds has exactly as many
rows as that audit found distinct contents - no more (nothing hidden) and no fewer (no
false merges). Two things the row-keeping rule does: the roots are walked in precedence
order, so the survivor is the file `find_media()` would have chosen anyway; and within one
root, the copy with a name a person would recognise wins, because the app's timestamp
names sort *before* `Theme_*` (digits before letters) - a test of the dedupe found
`1757490000001.mp4` taking `Theme_probe.mp4`'s row before that rule existed, and the suite
now plants a renamed copy, a same-name copy, and a same-length **different-content** pair
in a temp root and asserts all three outcomes.

The window builds in **0.21-0.64 s** with those 40 rows up (the spread is the machine
being busy, not the window: the same code prints 0.21 s in a quiet suite run and 0.47-0.53 s
when something else is running); the thumbnails and loop lengths of the first ten rows -
about what one page shows - land in **0.8-1.4 s**, and the rest trickle in behind them: an
ffmpeg seek per clip, **9.9-11.0 s for all 40** in the two runs of 2026-11-07 that printed
it (against 7.2-9.7 s for the 69 rows the pre-dedupe list carried, and 12.7 s for the 115
rows before that - fewer clips, on a busier box, at a cost that did not fall), with the
window interactive throughout. One frame render measures **12.4-14.1 ms** median for
`alpha` on a quiet machine, and the suite, which times the same call while the thumbnail
pass is decoding around it, printed **18.6-24.0 ms** in those two runs. Measured per theme
on a quiet box, `render.draw` with the pinned fixture: `alpha` 12.7 ms, `dual` 9.5,
`gauge` 9.0, `bars` 8.1, `clock` 8.0 (60 draws each, median; the spread is 0.2-0.3 ms
inside that). The `clock` theme's two newly-fitted lines cost nothing measurable: the
same draw with `_fit` swapped for fixed sizes is 8.23 ms off and 8.00 ms on, and fitting
moves the other four themes by 0.02 ms or less - a `textlength` loop over a handful of
sizes is not where a frame's time goes. Either way a 2 fps preview is a few percent of
one core. That is `render.draw` alone; adding the PNG encode the upload needs costs
**10.7 ms** median (10.7-15.0 ms) - about 23 ms for a frame that actually goes up - which
is why the preview does not encode. The gauge rings are most of that growth: the same
draw measured 9.0 ms before the arcs went in, and the frame it produces is now 12.1-13.6 KB
indexed rather than 9.2-9.8 KB.

**What it remembers.** `~/.config/xigmaui/config.json`, written by
`xigmaui/settings.py`: the port, theme, clock size, canvas, scrim, fan figures, preview
rate, window size, the three splitter widths, the text colour, whether the advanced
controls are folded away, whether closing the window hides it to the tray, and the clip
that was selected. The write is atomic and debounced -
500 ms behind a burst of clicks, once more on close - and the read goes through
validation rather than trust: a truncated or hand-edited file falls back to the
defaults instead of stopping the window, out-of-range values are dropped, and a clip
path that is not there (the Windows partition is not always mounted) falls back to
`media/Theme_25.mp4` rather than drawing a blank preview. `--device` and
`--preview-fps` on the command line win over the file, and `--fresh` ignores and
overwrites it. Nothing about the *panel* is stored, because the panel cannot be asked
what it remembers (§11): the file describes the window, not the glass.

Still not wired: a tray icon, and a live-to-glass toggle that keeps running after you
let go - the frame loop only runs for the window it announced, and it always says how
long that is. `tools/selftest.sh` covers
the GUI offline: clip sizes and lumas, all five themes previewed, the scrim rule
tripping on the bright clip and not the dark one, a missing port reported in the
log instead of raising, the settings round-trip plus the junk it refuses, the
`.desktop` entry (through `desktop-file-validate` when it is installed) and its icon,
and the four panel actions run against a stubbed `Link` -
which is where the wire rules get re-checked rather than re-stated: the background
upload hands over the whole file (all 214 917 B of `Theme_25.mp4`) with the 0.02 s
pre-byte pause and the clip's own filename, a frame goes up as one `.osd` PNG bounded
between 8 and 40 KB (12 120 B in the run that last checked this), 1 s at 5 fps is between 4 and 6
uploads (5 on this box), `STATE all 1` lands exactly twice and only before the first
file of a drawing session, `fans=False` leaves the tach array out of it, `status`
pushes no blob at all, a shortened session clock (0.2 s) makes the loop reopen repeatedly
in one second without re-pushing metrics, a port that disappears at a renewal ends the
run with a log line rather than an exception, a row of `400` notices stops the run after
four reopens in 1.3 s instead of spending its 4 s window on a dead channel, a `400`
notice is reported as a refusal instead of a success, and exactly one of the opens asks
for a destructive link.
