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
| layout editor | controls, always on | opens one of the layouts this machine can select (or one of the 5 generated ones), shows its widgets, and lays out every field that widget carries as a row of its own (8 to 18 rows by kind, from the model's list); the pane under the picture then shows *that file* rather than the live theme | nothing, ever: the panel is never handed a layout file (PROTOCOL.md §11). What `save` changes is what this machine's own daemon draws next time it names that theme |
| clips | library | every MP4 the roots hold, listed once per **distinct file** - **40 rows out of the 46 mp4 files this repository tracks** (204 files on the author's bench, where the installed package and a mounted Windows partition add themselves; still 40 rows): 3 rows from the clips vendored here and 37 from the vendor's library on any of those boxes, the rest of the files being copies that collapse by content - 6 among the 46 tracked here (3 of them under another name), 164 on the bench, and the dated audit of all of it is written out under "Cost, measured on this box" below. This checkout's own `themes/alpha/clips` is one of the roots the list walks: 43 clip files, byte-identical to what `xigmatek-connect-lcd-themes` installs (the suite re-hashes every one against that package's manifest), which is what lets a clone pair all 23 layouts `--list-themes` prints and why the same 40 rows turn up on a CI runner with nothing installed. `tools/preview_gif.py --clip themes/alpha/clips/Theme_30.mp4` reaches those files by path, which is how all five README previews are made. Each row gets an ffmpeg thumbnail, its measured mean luma and its measured frame size (ffprobe: 40 of the 43 clips the themes package installs are 480x480, 3 are 320x240, and a clip that is not the panel's size is labelled a guess under the list). One filter field above the list, and a row the display's own gate would refuse is greyed with its reason in the tooltip | the window's **one** upload button, `Send this background to the panel` (Ctrl+Shift+U): `STATE all 1` twice, then the whole file as one media file |
| background state | library | one line under the list that keeps "I picked this" and "the panel stores this" apart, in three wordings: the display reported accepting this very clip, it reported accepting a different one, or this window has not seen an accept - and the matching row in the list is drawn bold. A file the gate refuses says so, in the gate's words, before the button is pressed | nothing: it is a readout |
| `One frame now` | library | one live frame, preview and glass showing the same render | `STATE all 1` twice, then one `.osd` upload |
| `Send frames for 30 s` | library, advanced | the picture loop, so you can watch the real glass | `STATE all 1` twice, then 60 uploads at 2 fps |
| status | preview, under the log, advanced | the panel's `conn 1` reply: sn, versions, `space`, `brightness`, `mode`, `logo`, `osdState`, `timeout`, each annotated only where PROTOCOL.md records what it means | `conn 1`, `power resume`, `timeout 60` - and no metrics blob, because it puts no picture on the glass. With a display running there is no fresh `conn 1` to ask for, so the box shows the one that display read at its own session start, labelled as such |
| log | preview, under the picture | the window's own last 200 lines (`LOG_KEEP`): what it sent, what the panel answered, what failed and why. Scrollable, selectable, newest at the bottom; the display's full record is its journal, `journalctl --user -u xigmalcd -f` (docs/usage.md) | nothing: it is a readout |
| `advanced controls` | controls, top row | folds away the nine secondary controls named further down, in two boxes at the foot of the preview column; it hides pixels and never values | nothing |
| reset | preview, under the log, advanced | the vendor's `recovery` | needs the word `reset` typed in, then a confirm dialog. With a display running it goes over the socket, which refuses it unless that display was started `--allow-reset`, and the refusal is quoted in the daemon's words |

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
  **66 px rows, and room for 9 clips at the fresh 1440×1024 window on this bench (10 on CI's runner), 10 at 1919×1055 (11 there)**
  — rows in view, which is capacity: this bench has 40 distinct clips to
  put in them (204 files behind them on the author's bench), while a checkout of this
  repository on its own - no installed package, no second partition - walks the 46 mp4 files
  it tracks and gets the same 40 rows;
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
  preview used to stay at its old scale while its pane changed shape;
* and a column is never narrower than what it holds.  Each column's contents have a
  minimum width of their own, and those widths follow the fonts of the machine they are
  measured on, so the suite reads them wherever it runs.  On the author's bench the controls
  column's contents measure **362 px** with a layout open in its editor and the library's
  rows want **359 px**, and a column's floor is that number plus the **14 px** a vertical
  scrollbar takes off the viewport - **376** and **373 px** of floor.  GitHub's runner,
  where `simsun` is missing and another face stands in, comes out at **394** and **390 px**
  of floor for the same two rules.  Checked out at the
  `v0.4` tag and measured on this bench the same way, that column wanted **265 px**
  folded and **375 px** with the editor open while 0.4's window and split gave it
  **300 px**, so it grew a horizontal scrollbar *inside itself* with **89 px** of its own
  contents off screen - and the library column overflowed by **7 px** the same way.  Those
  0.4 figures were re-measured against the tag on 2026-11-10 rather than kept in a gate: a
  gate can only hold this tree, and what this tree asserts is that the same failure cannot
  come back - the suite builds a fresh window and checks both halves, no column narrower
  than its contents' own minimum and no horizontal scrollbar in any of the three;
* and a drop-down shows what it holds, box and list both.  Swept across all **28** layouts
  the editor can open, the widest row its widget menu can be handed measures **247 px** on
  this bench (`data  Motherboard Temperature  at 452,136`) and 264 px on CI's runner.  In
  0.4 the list opened at its box's width and the box was whatever the column left it, so in
  a **300 px** column that entry was cut in the one place a reader is choosing between
  entries.  Both halves are fixed now: the popup's own view gets the width (**323 px** for
  that row, 340 px on the runner) and costs the column nothing, and `_ed_box_readable`
  makes the closed box ask for its longest entry, because an elided
  `data  Motherboard Tempe…` in the box that says *which row you are editing* is the same
  complaint one widget later.  That second half is what the controls column pays for: with
  the widest menu on show its contents measure **411 px** here and its floor is **425 px**.
  It is not the 0.4 failure coming back - `_pane_floors` raises a pane to what its contents
  insist on *plus* the width a vertical scrollbar takes off the viewport, and that plus is
  how this rule was found: the column had a 411 px floor around 411 px of contents, which
  left a 397 px viewport and **14 px** of horizontal travel, the 0.4 defect arriving one
  fix later.  The suite pins the controls pane to *its own floor*, reads the width back
  before it claims anything about it, fails if the pinned column scrolls sideways at all,
  and asserts the half that has to hold at every width - the list a reader chooses from is
  never narrower than the widest entry any of the 28 layouts puts in that row.  Then it
  prints which branch the closed box landed in: **443 px** of column, **340 px** of
  box around a **264 px** entry on the runner, and **425 px**, **323 px** and **247 px** on
  this bench - so the entry fits the box and the list alike on either.  A box's
  own `minimumSizeHint` is still held under its longest entry, so the column is not paying
  for anything the text itself does not need.

The window's floor is the owner's rule, written in `xigmaui/app.py` as `MIN_WIDTH,
MIN_HEIGHT = 1280, 1024`: a 1280×1024 desktop at minimum, up to a 3840×2160 one, and
everything between used as it comes. It is a floor rather than an insistence -
`Window.__init__` takes `max(what the contents measure, min(1280x1024, what the screen
offers))`, so a screen with a panel on it that cannot show 1 024 px of window gets the
most it can, and the window **says so in its own log** rather than letting the bottom
row of controls fall off the edge. The fresh default is **1440×1024**
(`xigmaui/settings.py`), which is above the floor and inside a 1080p screen.

The splitter is asked for **532 / 540 / 356** at that window - the left column capped at
the 480 px frame plus its chrome, the controls given enough for two columns of editor
rows, the library the rest - and a fresh window reads them back as **532 / 527 / 373** on
this bench and **532 / 510 / 390** on CI's runner: the first digit is the cap the code
sets, the other two are each pane's floor, which is what its contents measure plus the
width a vertical scrollbar reserves, so they follow the machine's fonts. Every column comes back wider than its own contents measure.
The same three numbers are a shape at other widths: `QSplitter` scales an over-wide
request down proportionally and its stretch factors hand a wide window's slack to the
controls and the library, so at 3840×2160 the library column is **over 1 300 px** across
on either machine and shows **28** clip rows on both, while the preview stays capped at its
532 px - it is never scaled up, because pixels the glass does not have would only be a
bigger lie. The suite builds a window at these defaults, reads the splitter back, asserts
each column is at least as wide as what it holds, that none of the three scrolls sideways,
that the field grid's columns arrive as the window widens, and that its own minimum never
exceeds the room that justified them; every figure above is then read out of this page and
held to whichever of the two labelled machines is running the suite.

And the columns' floors are not remembered constants: `_pane_floors()` raises each pane's
minimum to its own contents' `minimumSizeHint` plus a reserved vertical scrollbar, so at a
1280×1024 desktop the three columns' floors are **272 / 376 / 373 px** on this bench and
**282 / 394 / 390 px** on CI's runner, where the code's lower bounds are 200, 300 and 320.
A pane
that cannot be dragged under what it holds cannot grow a horizontal scrollbar inside
itself, so the 0.4 failure mode is unreachable rather than merely avoided. The controls
floor is the editor's own footprint, so it moves twice over: one column of editor rows asks for **376 px** of controls on this bench, two columns for **400**, three for **568** - and **394 / 417 / 589** on CI's runner - a closed drop-down that has to show the longest entry it holds is part of what those columns carry, and the window's own minimum rises with them. Every one of those digits is read out of this page and held to whichever of the two labelled machines is running the suite, because a floor that follows the fonts is not a constant to compare.
The 18 rows of an `arc` widget stand **858 px** tall in one column and **465 px** in three there, the grid's own ask going **171 / 344 / 512 px** - **751** and **406 px**, asking **180 / 361 / 533**, on CI's runner as of its pass for the first of the two control rows below the fields - which is the reflow buying height without buying a scrollbar, and all twelve figures come off the sizing pass the suite runs on every machine. Those four heights are what the two rows of controls under the fields cost, in height and never in a column's width: 0.5 read 796 / 403 here and 723 / 378 there, the row of row-level controls added 31 px on the bench and 28 px on the runner, and the name box with its two buttons is another 31 px on this bench (827 / 434 to 858 / 465). What that second row costs on CI's runner is a figure only a run there prints, so it is not written here: the pair gate holds whichever machine is running the suite to the half labelled with its name, and when it disagrees the page is wrong.

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

A checkbox at the top of the controls column, default **off**, folds away nine
secondary controls: the `canvas` and `scrim` pickers, the fan-figures switch, the
display's last six port actions, the "send frames for 30 s" run, the panel-status
box - the `conn 1` report and its `Refresh` button go with their box - and the
factory reset's whole box, its word field and its button with it, three controls in
one.  They fold as two boxes at the foot
of the preview column, under the log, rather than as loose rows in the controls
column: `conn 1` answers with fourteen fields that wrapped to about ten lines in a
300 px column, and the picture's column is the one with height spare below a 480 px
frame.  It is about pixels and nothing else - every hidden control keeps its value
and `Apply` sends it, which is what the suite checks by setting `scrim` while it is
invisible, restarting the window and reading the same 200 back.  The choice is
remembered (`advanced` in the settings file), and the note beside the switch names
what is folded so a reader is never hunting for a control that exists.  The suite
holds that note, the switch's tooltip and this document to the same list, and checks
the set by parent as well as by length: nine controls, in the two boxes it says.

The **guarded factory reset moved in behind the switch**, which reverses what 0.4
documented - there the box stayed on screen whatever the switch said, on the grounds
that a recovery which is hard to find is worse than one in the way.  What actually
stands between a stray click and a factory reset is the word `reset` typed into the
field and a button that stays disabled until it is, and the suite now checks that
guard *in the folded state*: hidden, then shown, the button is still disabled, and it
wakes only when the word is typed.  A control that is hidden and disabled is guarded
twice over.  The CLI route (`xigmalcd recovery --port … --yes`) is where the recovery
is documented, and it is unaffected by any of this.

The **layout editor is deliberately not in there**.  It sits in the controls column,
open: that group box is the only place the window shows the 23 layouts the themes
package installs, and folding it away by default meant the point of that package was
invisible until a reader found an unrelated checkbox.

### The layout editor

One group box, on show by default, that opens a layout as data: the three
generated themes (`clock`, `dual`, `gauge` - JSON written out of `render.py` on demand)
and the 23 layout files this canvas can select, the same set `--list-themes` prints.
Two picks - layout, then widget - and then **every field that widget carries is on
screen at once, one row each**: no menu to open to find out what a row holds. The
counts are the model's, not a table kept here: `edit.field_names(kind)` plus
`edit.extension_fields(kind)` is **10 rows for a `text` widget, 11 for `data`, 12 for
`special`, 8 for `line`, 15 for `bar`, 18 for `arc`** - measured across the
**185 widgets** in the 28 layouts the editor can open, in the gate. Which control a row
uses is the model's answer too: a menu wherever a vocabulary already exists in code
(`edit.choices()` - 5 families, 27 readings for `source` and `showIf`, 6 anchors, 5
special drawings, the painter conventions, the named ramps), a checkbox for `bold`, a
spinbox for `edit.number_fields()`, a colour row with a swatch and the colour dialog for
`edit.COLOUR_FIELDS`, and a plain text box only for what is genuinely free text - a line
of `content`, a `format`. The grid takes one column of rows in a narrow controls column
and two or three as the window widens, which is what 1280×1024 through 3840×2160 is for.
And the picture itself can be pointed at: press a row to select it, drag it to move it,
nudge it with the arrow keys.

What the suite holds this to, rather than assumes - every one of these is something an
editor commonly gets wrong:

* **The note line under the rows says what the row paints.** For a `text` or `data` widget
  the keys that choose the line - `content`, `source`, `xigma.format`, `fontFamily`,
  `fontSize`, `bold`, `anchor`, `autoFitMax`, `xigma.showIf` - print the sentence the row
  means *and* the line it produces: `draws as "57°C"`, or `paints no line: no reading for
  `Fan 3 Name` on this machine: the row is skipped`, or the caveat that a shape is
  `layout.VENDOR_FORMAT`'s rather than one measured off the vendor's picture. The string
  comes from `edit.drawn_text`, which walks the painter's own rules in the painter's own
  order (`themes.values` for the reading, `layout.text_for` for the shape,
  `layout.font_for` for the face, a `showIf` asked before the row's own source), and it is
  proved by painting rather than by agreement between two pieces of code: the suite draws
  each of the **145** `text`/`data` rows of the **28** layouts twice, once as the file has
  it and once with that row replaced by a literal `text` widget whose `content` is the
  string the model named, and the two frames must be byte-identical. **132** rows paint a
  line at this fixture and all **132** twins came back identical - on CI's runner, where no
  CJK face is installed for the vendor's `simsun` rows to resolve, **131** paint and all
  **131** twins come back identical. The **13** that do not here (**14** there) are rows the
  painter skips too, each with the reason the model gives: `Pump Speed` in **9** layouts,
  the `Fan 3`/`Fan 4` slots this box reports no tachometer for, and on the runner the rows
  whose family has no file to open. **23** of the painted lines are spelled by a shape the
  file itself declares unmeasured (**22** there). Punch a hole in
  the readings and both doors answer the same way: `bars`' RAM row depends on `RAM Rate`,
  spelled from `memory.used` / `memory.total`; with the total gone the model says so, the
  painter records `showIf:RAM Rate`, and the `GPU Memory Rate` row beside it still paints.
* **A `format` the value cannot be dressed in is refused on the way in and survived on the
  way out.** `%q`, `%d %d`, `{}` and `{:,.0f}` all raise inside `format()` for the int this
  fixture gives `Used RAM`; the model refuses each one, names the value it probed, and leaves
  `dirty` and the undo count exactly where they were - and for the brace spellings it points
  at the form this field actually takes (`,.0f`), only after checking that the suggestion
  paints. A file that *already* carries one - built in the suite, not written by the editor -
  does not stop the frame loop: the painter records `format:<source> (ValueError)` in its
  skip list and draws the rest, 2 rows clean becoming 1 row and one said hole.
* **The `fontFamily` menu shows the face it names.** Each entry carries a preview drawn
  with the file `layout.font_for` resolves that name to on *this* box - the same Pillow call
  the painter makes, so the shape you choose is the shape that reaches the glass, at one
  height because a row's own size is in the row beside it - and the tooltip says which file
  it was drawn from. A family whose globs match nothing here gets no preview and says so
  both in its tooltip and in the note line, because the painter skips such a row entirely
  (`font:<family>` in its `missing` notes): a name with no file is not a smaller face, it is
  no ink - and neither is a row with **no `fontFamily` at all**, which is the fact nobody
  guesses from a form, since there is no default face to fall back to. All five vendor names
  resolve on the author's bench, so the gate builds the other cases instead of waiting for
  them: it adds a family with no file to `layout.FONTS` for the length of the check (and
  asserts the table comes back unchanged), puts `Impact` on an open row in memory - no file
  is written - and hands the model and the painter a row with the key absent.

* **A family spelled the file's way is folded, once, and said.** The vendor's rows write
  `Arial` and `layout.FONTS` names `arial`; `layout.font_for` lowercases before it resolves,
  so those are one face on the glass - which made the menu's own entry (the row's value,
  shown rather than dropped) a choice the model refused. It no longer refuses: the row keeps
  the name `layout.FONTS` carries, the window says what was stored, and the suite compares
  the two frames for a real vendor row and finds **0 px** of difference. Nothing else folds
  - `source`, `showIf`, `name` and `anchor` are keys the painter matches exactly, and
  `source: cpu temperature` is still refused in words.

* **Rows can be added, removed and reordered, and a new row is always a copy of a row that
  already draws.** Four controls under the fields do it - `add`, `remove`, `up`, `down` - and
  each entry of the add menu says, before it is pressed, which row the new one copies: this
  layout's own row of that kind if it has one, otherwise a real row somewhere in the corpus,
  with this repo's five exports ranked first because every row in them is carried to a
  zero-pixel diff against the picture it exports. There is no table of defaults in this code,
  and an honest one was not available: the vendor's application bundles are not in this tree
  (only their file names are, in PROTOCOL.md §10), so the files are the only evidence of what
  a row of a kind looks like. The files decide the shape too, and the suite re-counts them on
  every run: all **185** rows in the **28** layouts carry exactly the **5** keys `id`,
  `layerIndex`, `type`, `property`, `widgetContent`; `property` is a one-element list in every
  one and `widgetContent` is `""`; and a new row carries the **7 / 7 / 11 / 14 / 7 / 9** keys
  that `text` / `data` / `bar` / `arc` / `special` / `line` rows always carry, each of its
  values a value rows of that kind already use. A `special` is the one kind the model refuses
  unnamed - the sub-menu lists the **5** drawings `themes.SPECIALS` registers - because a
  `special` nothing draws is not a thinner picture but no picture, which is what the painter's
  `special:<name>` note says. Ids follow the spelling of the file being edited (UUIDs in the
  vendor's, `xigma-…` in ours) and stay unique inside a layout, which `themes.validate` only
  asks softly - those **23** files' **123** rows answer to **25** distinct ids, one id
  shared by **18** of those rows - and the model obeys it anyway.  What a structural edit
  reaches is the file, and the check is made against the file rather than against the object
  in memory: the rows come back out of it in the same order, and the file on disk draws the
  frame the pane was showing when `save` was pressed.
* **A row's edge resizes it, and what the drag writes is that kind's own size - read off
  the painter, not chosen.** The pane paints eight small squares on the selected row's box,
  and which of them exist is the model's answer: `edit.Editor.size_edges` puts every edge
  through its own resize door and the pane paints what comes back, so a handle the model
  would refuse is never offered. A `bar` gets all eight, because its box *is* `x,y` to
  `x+width,y+height` - every `bar` row this run draws a box for has exactly that box, and the
  rows that do not are the ones whose source this machine reports no reading for, which have
  no edge to grab. A `line` gets all eight, and it is the one kind whose resize needs no
  drawing: `layout.line_rect` predicts the drawn box of **4** of the **4** line rows exactly,
  including the two the vendor turns 90°, where the box's horizontal extent comes from
  `height` - and where that rect's pivot, or a `lineWidth` recentring the thickness, puts the
  box somewhere other than where the drag left it, `x`/`y` are corrected from the same
  prediction and the sentence says they were. An `arc` gets all eight, and a drag scales the
  ring with its box rather than stretching a band around a fixed ring, because `radius` and
  `width` move the ink and leave the box exactly where it was (a +8 px push on `radius` moved
  the box 0 px and the picture by thousands of pixels): the drag writes `sizeWidth`,
  `sizeHeight`, `radius` and `width` together, keeping `sizeWidth == 2*radius + 2*width` and
  `sizeWidth == sizeHeight`, the arithmetic **6** of the **6** `arc` rows in the library obey.
  A one-axis drag on one of those squares makes the box no longer square, and the note says
  so instead of quietly squaring it back.
* **A `text` or `data` row is resized by its face, because it owns no other size.** Not one
  of the **145** `text`/`data` rows carries a `width` or `height` key: their box is the ink
  the face lays down, and a +8 px push on `fontSize` moves that box's width by an amount
  that is never 8 px, differs from row to row, and belongs to this machine's fonts rather
  than to the file (the suite measures the spread on every row and prints it). So the pane
  paints no square on a text row's left or right side, and its top, bottom and corner
  squares ask for a height the model reaches by *searching* faces (bracket the target, then
  bisect, drawing every candidate), which lands on a face whose box is near the ask but
  rarely exactly it: the sentence quotes the box that reached, and the amber rectangle on the
  glass quotes the box that was asked. A `special` row's two axes are two different keys -
  `width` is the pitch between the figures' centres, `fontSize` is their face - so it has no
  corner squares at all.
* **Two things a handle never writes, and the caps that own an extent instead.** `cornerRadius`
  is carried by **25** of the `bar`/`arc` rows, and pushing it +8 left every box those
  rows have exactly where it was; `rotate` is carried by **12** `bar` rows and pushing it +8 changed
  **0 px** on all **12**, because nothing in `layout.py` reads it on a `bar`. Where a cap owns
  the extent the drag is refused in that cap's name rather than writing a face nobody asked
  for: `xigma.autoFitMax` fits a row to a width and `xigma.fitArc` fits a `special`'s figures
  into a ring, and both refusals say which of the two it is and that the row to change is that
  one. A row that draws no box at this fixture has no edge to drag, and the sentence carries
  the painter's own reason (`Fan 3 Name`, `Fan 3 Speed`, …).
* **The pane shows the ask; the model returns the result.** While the mouse is down, the pane
  paints - in a solid line, next to the dashed box that is - the box `edit.Editor.resize_box`
  says the release would ask for. That door is the one `resize_row` answers through, so the
  amber rectangle is not a second guess kept in the window; a repaint in the middle of a drag
  (the note line growing, the splitter refitting the pane) puts that ask back rather than
  dropping it. A press on a square belongs to the row that is selected even when another
  row's ink lies under it - the pane's later-row-wins rule is a rule about ink, and a grabbed
  square that moved some other row would be a surprise nobody could see coming - and when that
  happens the note says whose ink is under the square. One press-drag-release is exactly one
  undo step, moves pixels, and writes no file: every accepted drag the suite drove put the
  layout object back byte for byte under one press of undo, and every refusal left `dirty`,
  the undo count and the picture exactly where they were found.
* **Where a new row lands is decided by the painter's boxes, and the sentence says what
  happened.** A trial draw with the row in it reports the box that row *actually* paints - an
  anchor does not mean the same thing for every kind and every `xigma.anchor` - and that box
  is walked over the canvas in **4 px** steps to the free position nearest the one it was
  copied from. Where there is no such position the row stays where its source sits and the
  sentence says so, and the row is left selected so the reader can drag it; quietly moving a
  row nobody asked to move, or parking one where it is invisible without saying, is the same
  repair this model refuses elsewhere.  How an add ends is a picture question, so it is
  measured rather than reasoned about: the **159** adds across the **28** layouts come out
  **35 / 109 / 15** on this bench - clear where their source sits, moved to the nearest free
  spot, still meeting another box and saying so in the sentence - and **35 / 109 / 15** on
  CI's runner, and the gate holds whichever machine is running it to its half of that pair.
* **A reorder is the draw order, and it is proved with pixels.** The rule, asserted in both
  directions over every adjacent pair of drawn rows in all 28 layouts: a swap moves ink
  **exactly** where the two rows both cover some pixel opaquely and in different colours.
  Pairs whose bounding boxes never meet swap 0 px, and the gate fails if one of them moves a
  pixel; pairs whose boxes meet but whose ink never both lie opaque in the overlap also swap
  0 px, which is what an `arc`'s box (mostly the hole its ring is drawn around) and two vendor
  `line` rows crossing in sub-pixel coverage look like. Which pair falls on which side is a
  font question, so it is measured, and both machines are named: **120** adjacent pairs of
  drawn rows have boxes that never meet on this bench and **118** on CI's runner, and of the
  **12** whose boxes do meet **6** moved ink and **6** did not - the same 12 / 6 / 6 on both.
  `layerIndex` is left exactly where it was: over the vendor's files it equals the row's
  position in **23** of their **123** rows and differs in **100** (`Theme_01` gives six of its
  eight rows 0), nothing in `layout.py` reads it, and inventing a meaning the files do not
  show would be a repair rather than a fix.
* **The last row of a layout cannot be removed, in `validate`'s own words.** Emptying the list
  is a hard problem - "an `osd.widget` list with nothing in it: there is nothing to draw,
  which is not the same as an empty canvas" - so the model asks that same door what it would
  say and repeats it, and `remove` stays disabled at one row instead of letting a reader find
  the sentence at save time. Every one of the four acts is exactly **one** undo step and the
  steps are last-in-first-out: one press after a remove puts the row back with the reorder
  still standing, the next takes the reorder back, and the frame says which of the two was
  undone. The refusals - a kind nothing draws, a `special` with no name, a move past either
  end of the list, the last row - all leave `dirty`, the undo count and the file exactly where
  they found them, which the gate checks rather than hopes.

* **Opening writes nothing.** The file appears at `save`, because your copy of a name is
  what `--theme` and the control socket find first, and that shadowing is a fact about
  files: browsing a theme's fields must not quietly change what the loop draws. The gate
  opens 3 library layouts and 5 generated ones and then counts the user directory:
  empty.
* **A copy can be renamed, and the new name has to be one nothing answers.** The box beside
  the `rename` and `save as` buttons holds the name to *give*, not the name that is, and it
  keeps what you typed: it has no length cap, because a box that stopped at the writer's
  **64**-character limit would drop the characters under a reader's fingers and then act on
  a name nobody typed - the door answers `longer than 64 characters` instead. A new name has
  to clear three things at once, because `themes.resolve()` matches three: the **27** layout
  names the library holds, those names folded (to the resolver `theme_07` and `Theme_07` are
  one name), and the **27** `id` numbers inside the files. That is not caution, it is
  measured: a copy put at a vendor's own name takes that layout out of reach by name *and* by
  id - `resolve(<that id>)` answers None afterwards - and a copy at `theme_07` beside the
  vendor's `Theme_07` leaves `--list-themes` showing two layouts while every spelling
  resolves to one file. Only a copy of yours can be renamed; the vendor's two trees are never
  written. A rename is a file act, not an edit: no undo step, `dirty` exactly as it was, and
  every row and pixel where they were (the suite draws the layout before and after and
  compares). The `id` inside the file does change - a fresh 13-digit number in the shape the
  vendor's own files use, their **27** falling inside **1 187 564 ms** of one another -
  because two files answering one `--theme <id>` is a name space with a hole in it.
  `<name>.json.bak` travels with the copy, so undoing your last save is still that save; a
  half-written `.tmp` is reported and left where it is, because its bytes belong to the old
  name. And a name may not end in `.json`, `.bak` or `.tmp`: this program writes those beside
  a layout, so a layout named `x.json` would live at `x.json.json` while the `x.json` in the
  same listing is the layout named `x`. None of the **27** names here does, so that rule
  refuses nothing that exists.
* **`save as` writes a second copy and leaves the first one alone.** The file the layout came
  from keeps every byte it had and the id it had; the new copy takes a fresh id, so the two
  never answer the same `--theme <id>`, and the window goes on editing the new one. This is
  also how a layout drawn from `render.py` gets its first file: `save as your copy` still
  refuses `gauge.json`, because that would be a second `theme_gauge` free to disagree with
  `render.py`, while `my-own-gauge.json` is a layout of yours and `--theme gauge` keeps
  drawing the code's picture.
* **Which file answers a name is asked, never remembered.** The line under the layout menu
  reads `themes.resolve()` on the current name - the same door `--list-themes`, the loop's
  own log line and the socket's `theme` command go through - because the three moments that
  move a file (a save, a revert, a rename) are exactly the moments a remembered answer goes
  stale: after a revert of a renamed copy it says *no file answers this name*, which is true
  and was not sayable from a word kept from when the layout was opened. The menu is rebuilt
  from the library after each of those acts - a rename retires one entry and creates another
  - with its signals blocked while it happens, because selecting the entry for the layout
  already in memory would re-read the file and throw away everything typed since the last
  save. A loop re-resolves its name every frame, so a rename reaches it on the next frame;
  and when the name was yours alone nothing answers it, because `render.draw` falls back to
  `gauge` - measured, pixel for pixel - which is why the note says to re-point the loop over
  the socket, whose `theme` command takes the same names `--theme` does. A *fresh* `--theme`
  of that dead name exits 2 with `themes.why_not`'s sentence instead.
* **The field list comes out of the code.** A kind offers the intersection of the keys
  `layout.py` is *proven* to read (`themes.keys_read()` parses the painter's own source)
  and what that kind draws - 25 names across 6 kinds today, counted in the gate. The keys
  the vendor's files carry that nothing reads (`enableMove`, `screenStatus`, and eight
  more, each with its reason printed by `--print-theme-fields`) are never offered, and the
  writer keeps them in the file exactly as it found them, because an editor that drops
  keys it does not understand is an editor that corrupts the vendor's own files. Alongside
  them sit the `xigma.*` keys this program drew up for itself - offered on every kind,
  because a drawing convention or a dependency is a property of the row, not of the shape -
  and the one added on 2026-11-09 for `bars`, `xigma.showIf`, gets the same menu as
  `source` does: the list of readings this program can answer, so a row cannot be pointed
  at a dependency nobody will ever satisfy.
* **And what a field means, when the drawing is what decides it.** A `special` row whose
  drawing is a *pair* of figures reads `width` as the distance between the two figures'
  centres, and `x` as their shared centre; a row whose drawing is one line of built text
  reads `width` not at all. The field list cannot show that difference - both rows are
  `special` - so the note line says it in both directions rather than leaving a reader to
  set a number that does nothing. Which shape a name has is read out of the registry:
  `themes.special_door` and `themes.special_is_pair` are checked against the door each
  drawing function actually calls (`layout.draw_special_line`, `draw_special_pair` or
  `draw_special_values`), found in its own source, so the window keeps no list of which
  drawings are pairs. Inside the two pair doors the sentence still splits, and the gate
  checks that too: a width-fitted row is told its `fontSize` is a ceiling over
  `xigma.autoFitMax`, a ring-fitted row is told that key is the one its drawing never
  reads and that its size walks down against `xigma.fitArc` instead. The gate also
  measures the claim
  instead of trusting the prose: a declared pitch and the two figures' ink-box centres
  agree to within 2 px on the painted frame, and narrowing the pitch moves each figure
  half the difference inboard.
* **The pane shows the file, at pinned readings.** `themes.draw` - the door
  `--check-theme` uses and the frame loop uses for a layout theme - with the fixture every
  documented figure in this repo was read at (CPU 57.0 °C, GPU 47.0 °C, 2026-02-17
  09:30:12), and that fixture is shaped like a machine: it answers 15 of the 19 sources the
  five generated layouts ask, the four it leaves being the `Fan 3`/`Fan 4` slots past its two
  reported tachometers. The line under the picture says so (`pane: pinned fixture | this
  machine: …`) because a preview that moved with the sensors would make it impossible to tell
  an edit from a temperature. Because both doors read that one dict, a generated layout and
  the theme it was generated from put down the same picture here: zero differing pixels for
  all five, at seven ink choices, worst channel 0, gated. The text-colour row therefore
  reaches a generated layout - by `themes.with_ink`, into a copy, so what Save writes keeps
  the file's own colours - and does not reach anybody else's: open `Theme_28` and an ink moves
  it 0 px (docs/theme-editor.md).
* **The picture can be pointed at, and what a point means is the paint's answer.** The
  ink box `themes.draw` records for the selected row is marked on the pane. Press inside a
  box and that row is selected; where two boxes overlap the **later** row wins, because
  that is the one drawn on top - which is what makes the temperature figure standing inside
  a gauge ring grabbable, instead of leaving the ring under the cursor steal the press.
  Hold the button and drag: the row follows the cursor through the same model the spinbox
  writes to, one drag is one undo step, a run that ends where it began writes none, and the
  pane repaints as you go. The arrow keys move the selected row 1 px, or 10 px with Shift.
  A press on empty glass says that point is no row's, and a row the readings could not draw
  has no box to press - so the pane never invents a position for something it did not paint.
* **The mark is chrome, and the pane admits one thing the model cannot.** The dashed
  rectangle and its label are painted over the picture in the pane's own paint event, and
  never drawn into the frame the caption counts; the gate re-shows the pane with a mark up
  and without one and compares the bytes it was handed. And a row's *anchor* is bounded by
  the canvas while its ink is not, which is how the vendor's own files are checked - `x` at
  the last legal column is legal and the row still draws pixels the glass will never show.
  `validate` says nothing about that, so the sentence sits beside the mark ("its ink runs
  to x,y - off the 480x480 canvas") rather than leaving a clipped row as the reader's
  discovery.
* **A refused value changes nothing at all.** Type 9999 into `x` and the spinbox holds it,
  the note prints the model's sentence ("must stay inside the 480x480 canvas this layout
  declares"), and the picture, the dirty flag and the undo history do not move. Six
  attempts at one widget leave zero undo steps.

One display bug in that row, caught by the gate that landed with the pair row: a value
menu selected the **first** entry of its vocabulary instead of the value the row holds. The
two agree by luck in the case that was already gated - the ring's `arcPaint` reads `render`,
and `render` sorts first - but a `special` drawing `dual-status` was shown as
`clock-readings`, and a `data` row was shown as whichever source sorts first rather than the
one it reads. The menu now selects the row's own value, and the gate checks the claim on
both shapes: on `name`, whose vocabulary starts elsewhere, and on `source`, where the widget
picked for the check is deliberately not the one that sorts first.

What one edit is worth, in pixels: the literal text widget in `Theme_28` moved 20 px in x
over twenty spinbox keystrokes is **one** undo step; exactly one ink box moves, by
(20, 0), the other five stay put, and 1 163 of 230 400 pixels change. Saving puts the file
in `~/.config/xigmalcd/themes/`, after which `--theme Theme_28` reads *that* file and
paints a byte-identical frame; one undo returns the first frame byte for byte; revert
removes the copy and the vendor's picture is back. A colour typed as `#ff4040` is stored
as `rgba(255, 64, 64, 1)` - the spelling all 152 shipped widgets use, which `layout.rgba`
can read and `#ff4040` cannot - and the note says `stored as …` instead of leaving the
reader to find it in a diff. An extension key can be un-set: removing the gauge ring's
`arcPaint` takes the empty `xigma` object with it and changes the frame by 1 200 px at
this reading (that is what the two ring conventions in `layout.ARC_PAINT` are worth), and
a vendor arc that never carried the key shows `(not set)` rather than picking a default to
display.

What it does **not** do, said plainly: nothing is sent to the panel (PROTOCOL.md §11 - the
panel is never handed a layout file), so what a save changes is what *this machine's*
daemon draws next time it names that theme; a row can be added only as a copy of a row
that already draws, removed down to but never including the last one, and reordered only
through the list that *is* the draw order; a row's size changes only through the keys its
kind owns - there is no scale-everything handle, and no grid or snap to drag against -
and nothing about a row's *position* is guessed at; the editor draws from the pinned
fixture and not live readings; and the theme combo above still lists only the five,
because that combo picks what the loop draws from this machine's sensors.

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
(204 files behind it on this bench, 46 of them tracked here, before the copies were
 collapsed) that is the fastest way to see whether the
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

**A layout names the picture under it, and the dropdown selects it automatically.**
Every vendor layout declares exactly one clip in its own file (`background.mediaFile`):
all 23 selectable layouts name a distinct one, and `themes.pair(NAME)` is the one place
that reads it, so `--list-themes` and the window cannot disagree with each other or with
the file. Choosing a layout in the dropdown puts its own clip under the preview and marks
that row in the library column - measured over all 23 vendor layouts and all five
generated exports in that dropdown, every one of them resolved to a row on this bench, and
the suite asserts both halves. Two cases are said out loud rather than left to be inferred:

* **the five themes this repository draws from `render.py` pair with the backdrop their own
  published picture sits over** - `alpha`→`Theme_25.mp4`, `gauge`→`3.mp4`,
  `dual`→`Theme_30.mp4`, `clock`→`Theme_07.mp4`, `bars`→`theme_52.mp4`, kept in
  `themes.CODE_CLIPS`. That is not a guess and not a vendor record either: the vendor
  library has no page for a theme it did not draw, so the honest source is this project's
  own pictures - the README's MP4s are named `<theme>-<clip>.mp4` for it, and
  `tools/selftest.sh` derives the set back out of those file names on every run and fails
  if the table disagrees. The amber-ink figure (`alpha-Theme_25-amber.mp4`) drops out of
  that derivation by itself, because its clip part is not a file any media root holds.
  `clock` is the one backdrop that is bright, so pairing it brings the scrim plate with it
  - the same luma rule as everywhere else, not a per-theme setting. A layout *you* authored
  names no clip at all, and the line under the clip list says so instead of leaving the
  reader to wonder whether the pairing is broken.
* **a background stays put only if you say so, with a box you can see.** *keep my
  background*, in the clip column, stored as the bool `keep_my_clip` - a stored flag,
  because "hold this one" is a fact about a human that no path on disk can recover.
  Ticked, opening a layout leaves the background alone and says which clip that layout
  would have used - in the note line under the picture **and** in the log, because a
  preview that refuses to move looks exactly like a broken window and a line of small
  print is easy to miss.  **Use this layout's own clip** unticks it, takes the pair back,
  and re-arms the pairing.

That box used to be set by clicking a row in the library, under the old key
`clip_customized`, and 0.4 stopped doing that: a row pick is a preview and a thing you
may send, and until a reader asks otherwise the layout in the dropdown owns the picture.
So clicking a row now prints what the pick costs - which clip the open layout names, and
that the next layout change brings it back - and nothing in the window ticks the box by
itself. A file written by the older window is read once and honoured: `clip_customized:
true` becomes a ticked box, so an upgrade does not move a background under anybody, and
the window says so in its log before it does anything else; the next save writes only the
new key. Populating the list also selects a row; that is the window answering its own
question, and the gate checks that it does *not* tick the box or print that line, because
it looked exactly like a choice.

The pairing changes nothing about the wire: it decides what the *preview* composites
under our layer, and the upload button is still the only thing that sends a file to the
panel (docs/themes.md, PROTOCOL.md §11). One thing to keep straight about the two
lookups: they share one root list. `--mp4 NAME` and the loop's default come from
`xigmalcd.main.media_roots()`, and the window's list walks those same roots and adds the two Windows ones
on top - so a layout resolved from the checkout gets its clip from
the checkout in both doors, and `--mp4 Theme_07.mp4` means the very file `--list-themes`
printed beside that layout's name.  A row the window lists is handed to the upload as an
absolute path either way, so the pairing changes nothing on the wire by itself.


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
* **A picker plus an editor, not the vendor's theme editor.** The panel renders
  nothing itself (§11): the theme JSON declares widgets and the firmware ignores
  them, so editing a layout means drawing every widget in Python and shipping the
  result as frames - which is what this does, and it is what makes a row's
  position draggable on screen at all. What it is *not* is the vendor's app: a new row
  is always a copy of a row this program already draws rather than a table of defaults,
  nothing about a layout is ever sent to the panel, and the theme pane offers the five
  themes this repo draws, with the daemon's own options.
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
roots hold, and lists each **distinct file** once: **40 rows out of the 46 mp4 files this
repository tracks
files** - 3 vendored in `media/` and 37 from the vendor's library. The other 121 files are
copies, and where they live is worth naming, because they are three different kinds of
copy: **69** in the Windows app's own upload history (`AppData/Roaming/alpha/media/`),
**43** in the vendor's static media on the mounted partition, and **9** copies the
installed packages left next to files already listed.

**35 of those copies have a different filename from the row they duplicate**, and that is
the whole reason the rule is length-plus-content rather than name-plus-length. The first
pass at this - keyed on `(name, size)`, added when the two packages started overlapping
the checkout - left **69 rows for 161 files** on this bench (that count predates the
checkout's own clip root), because the Windows app re-copies a library
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
middle. The audit that produced the figures above used whole-file sha256 over the files
the roots held that day, and the same audit over the 46 tracked files finds 40 distinct contents:
the three `media/` clips the README figures were rendered from, and three pairs the vendor
library repeats inside its own tree (`Theme_26`/`Theme_31`, `Theme_27`/`theme_38`,
`Theme_29`/`theme_51`). That is what makes 40 rows the exactly right answer rather than merely
a smaller one - the list the window builds has as many rows as the audit found distinct
contents, no more (nothing hidden) and no fewer (no false merges) - and the suite re-derives
the four digits from the tree itself, in the section that lists the rows:
46 files, 40 rows, 6 copies dropped, 3 of them renamed. Two things the row-keeping rule does: the roots are walked in precedence
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
inside that). `bars` at 8.1 ms is the drawing from before its fan slots landed on
2026-11-08 - its row list went from this box's eight to ten - and that row is owed a
re-measurement on a quiet box, which is said here rather than quietly quoted from a run
with the display daemon drawing at 2 fps in the background. What the editor's completed
fixture costs *is* measurable on a busy box, because it is a relation and both halves were
timed in one process, alternating, 60 draws each: **+0.02 to +0.47 ms** a frame, `bars`
the largest with the 12 rows its fan slots and memory readings now answer
(docs/theme-editor.md). The five numbers above are still labelled, because they are
absolute and no run of them has had a quiet machine yet. The `clock` theme's two newly-fitted lines cost nothing measurable: the
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
controls are folded away, whether closing the window hides it to the tray, the clip
that was selected, and `keep_my_clip` - whether the *keep my background* box is ticked.
The write is atomic and debounced -
500 ms behind a burst of clicks, once more on close - and the read goes through
validation rather than trust: a truncated or hand-edited file falls back to the
defaults instead of stopping the window, out-of-range values are dropped, and a clip
path that is not there (the Windows partition is not always mounted) falls back to
`media/Theme_25.mp4` rather than drawing a blank preview. `--device` and
`--preview-fps` on the command line win over the file, and `--fresh` ignores and
overwrites it.

**One older key is read once.** A file written before 0.4 may hold `clip_customized`,
which meant "a row was clicked, so no layout may walk over that clip". `_clean` maps it
to `keep_my_clip` and leaves the behaviour alone - a box that was effectively on stays on,
so an upgrade moves nothing - and `load(notes=...)` hands the window the sentence it
prints in its log before the first pairing line: *the older `clip_customized: true` in
your file is now the "keep my background" box, and it is ticked so nothing moved under
you.* The next save writes only the new key, and a file that somehow carries both is
answered by the new one, with a note saying the old key is on its way out. A stored junk
value (`"yes"`, `1`, `null`) is still refused: only a real bool counts, because a truthy
string here would quietly stop the window following its pairing.

**A window that was started without that file does not write one.** `save_settings`
defaults to `restore`, so a normal session and `--fresh` (whose help promises to
overwrite) both write, while an offline check or a throwaway script - a `Window` built
against a device that does not exist, at a rate nobody asked for - cannot replace a
person's session file, and says once in its own log that it is not writing. That rule is
here because one of this project's own test sections did exactly that: it set
`XDG_CONFIG_HOME=$cfgtmp` from a variable assigned 600 lines earlier in a different
section, which expands to nothing when the section is run on its own, so the write landed
in `~/.config/xigmaui/config.json`. The next `python3 -m xigmaui` by hand opened on a clip
nobody had chosen, pointed at `/dev/xigma-no-such-port`, and carried
`clip_customized: true` - the older flag that stopped the window following any layout's
own background, and the reason the pairing complaint that opened this section looked like
a broken window rather than a stored bool. Two things were wrong with that: the section
was not self-contained, and
the window had no rule about writing a file it had refused to read. Nothing about the
*panel* is stored, because the panel cannot be asked
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
