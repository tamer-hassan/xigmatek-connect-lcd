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

| pane | what it does | what lands on the wire |
|---|---|---|
| the running display | what the socket says another process is drawing: one sentence, the counters (`40/41 uploads the panel confirmed, 0 refused, 1 renewal`, session age, last file and notice, `space`), **what the panel stores as its background** (`the panel stores: theme_47.mp4`, read out of the display's own event ring), and the ring itself - the last six things that display did on the port, with its verdict on each upload. Pause, one frame, an fps spin, `Apply these settings` (Ctrl+Return) | socket only; the port is never opened. Measured 1 ms for the six commands Apply sends |
| preview | the stored background frame with `render.draw`'s OSD layer composited on top, refreshed at `--preview-fps` (default 2). Its column is capped at 480 px plus the pane's chrome, and the picture is never drawn larger than the glass is - see "How wide each half gets" below | nothing |
| theme | the five themes, clock size, `clear`/`black` canvas, scrim, fan figures, and a line saying what the vendor's 27 themes in the other package are and are not | nothing until you press Apply (display running) or one of the send buttons (not running) |
| clips | every MP4 the roots hold, listed once per clip - **69 rows** on this box: 3 vendored here, 40 more from the vendor's library, 26 more from the 69 files the Windows app has pushed to this panel (the rest are byte-identical re-uploads); the last two sources are read off the mounted Windows partition or the installed themes package, and a clip that exists in two roots keeps the row from the root the code would have chosen. Each row gets an ffmpeg thumbnail and its measured mean luma. One filter field above the list, and a row the display's own gate would refuse is greyed with its reason in the tooltip | the window's **one** upload button, `Send this background to the panel` (Ctrl+U): `STATE all 1` twice, then the whole file as one media file |
| background state | one line under the list that keeps "I picked this" and "the panel stores this" apart, in three wordings: the display reported accepting this very clip, it reported accepting a different one, or this window has not seen an accept. A file the gate refuses says so, in the gate's words, before the button is pressed | nothing: it is a readout |
| `One frame now` | one live frame, preview and glass showing the same render | `STATE all 1` twice, then one `.osd` upload |
| `Send frames for 30 s` | the picture loop, so you can watch the real glass | `STATE all 1` twice, then 60 uploads at 2 fps |
| status | the panel's `conn 1` reply: sn, versions, `space`, `brightness`, `mode`, `logo`, `osdState`, `timeout`, each annotated only where PROTOCOL.md records what it means | `conn 1`, `power resume`, `timeout 60` - and no metrics blob, because it puts no picture on the glass. With a display running there is no fresh `conn 1` to ask for, so the box shows the one that display read at its own session start, labelled as such |
| reset | the vendor's `recovery` | needs the word `reset` typed in, then a confirm dialog. With a display running it goes over the socket, which refuses it unless that display was started `--allow-reset`, and the refusal is quoted in the daemon's words |

### How wide each half gets, and why the preview is never bigger than the glass

The two columns sit in a splitter, and three measured rules decide its shape rather
than a designer's taste:

* the frame `render.draw` produces is **480×480**, exactly what the panel is, and
  `_fit()` caps the pixmap at that size. Qt's `scaled(KeepAspectRatio)` grows a
  pixmap without being told not to, and on a wide window the old code drew the
  480 px picture at 502 px - a picture of the glass containing 22 px of invented
  detail. The suite pins both directions: 1:1 on a wide window, and shrunk to the
  pane when the handle is dragged narrow (`xigmaui/app.py:_fit`);
* so a preview column wider than 480 px + chrome is dead space. The left pane gets
  a maximum width (`render.W + PANE_CHROME`, 532 px here) and the controls get the
  rest. Before that cap, a 2 259 px window gave the preview column ~993 px for a
  480 px picture - and, with the upscale bug above, drew that picture at ~993 px -
  while the parts you actually work with shared 1 266 px. The floor on the other
  side is a measurement too: the first version of the cap applied its sizes before
  the splitter had ever been laid out, and at 2 259 px the controls column came back
  **116 px** wide. That is the "invisible half" failure, and it is why the sizes are
  set after the window's own `resize`, why the right pane has a 320 px minimum, and
  why the suite asserts both. Where the handle ends up is remembered - the settings
  file's `split` key - and a restored `0` width is rejected rather than restored, so
  a pane hidden by an over-eager drag cannot come back as a permanent hole.
* and the picture refits when the **label** resizes, not when the window does:
  dragging the splitter never fired the window's `resizeEvent`, which is why the
  preview used to stay at its old scale while its pane changed shape.

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

The bench found the cost of not having that readout, and it is worth writing down
because it looked like a broken feature rather than a missing label: a background
was picked from the list **three times**, three different clips, and the panel kept
drawing the picture it already had. Nothing on screen said why. What had actually
happened is that `Apply these settings` had been pressed each time, and Apply sends
six settings - theme, clock size, canvas, scrim, fans, fps - and *never a file*, by
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
roots hold, and lists each one **once**: 69 rows here - 3 vendored in `media/`, 40 more
from the vendor library in `themes/alpha/`, and 26 more from the 69 files the Windows
app has pushed to this panel, the other 43 of those being byte-for-byte re-uploads of
clips already on the list. That dedup is new, and so is the evidence for it: with the
packages installed, roots overlap by copies rather than by links, and listing rows for
every path gave **161 rows for 69 clips**; all 92 dropped pairs were compared by full
sha256, and not one of them was a same-name, same-length pair that held different
bytes. The row that survives is the file `find_media()` would have chosen anyway,
because the roots are walked in precedence order, and `tools/selftest.sh` plants a copy
of `Theme_25.mp4` in another root to keep that true.

The window builds in **0.21-0.64 s** with those 69 rows up (the spread is the machine
being busy, not the window: the same code prints 0.21 s in a quiet suite run and 0.64 s
when something else is running); the thumbnails and loop lengths of the first ten rows -
about what one page shows - land in **0.80 s**, and the rest trickle in behind them: an
ffmpeg seek per clip, **7.2-9.7 s for all 69** (12.7 s for the 115 rows this box listed
before the dedup), with the window interactive throughout. One frame render measures
**12.4-14.1 ms** median (11.7-22.7 ms over 15 draws, transparent canvas, `alpha` theme);
the selftest, which times the same call while the thumbnail pass is decoding around it,
prints its own median in the same line. Either way a 2 fps preview is a few percent of
one core. That is `render.draw` alone; adding the PNG encode the upload needs costs
**10.7 ms** median (10.7-15.0 ms) - about 23 ms for a frame that actually goes up - which
is why the preview does not encode. The gauge rings are most of that growth: the same
draw measured 9.0 ms before the arcs went in, and the frame it produces is now 12.1-13.6 KB
indexed rather than 9.2-9.8 KB.

**What it remembers.** `~/.config/xigmaui/config.json`, written by
`xigmaui/settings.py`: the port, theme, clock size, canvas, scrim, fan figures, preview
rate, window size, whether closing the window hides it to the tray, and the clip that
was selected. The write is atomic and debounced -
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
