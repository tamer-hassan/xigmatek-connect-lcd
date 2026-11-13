# `tools/`: what each script is for

Every script in `tools/`, what question it answers and what it writes. None of them are installed by the package: the discovery and probe scripts put unmeasured bytes on the wire, which is a bench's job and not a package's.

## The catalogue

**Which tool answers which question.** The list below says what each tool is; this is the
way in from a symptom. Nothing here sends firmware-shaped traffic, and the only thing that
ever touches `recovery` is the reset command: `tools/reset_panel.py` in a checkout, and
`xigmalcd-reset` on a system that installed the package (where `tools/` is not installed at
all). Both spellings are the same code, `xigmalcd/reset.py`, and you invoke it by hand.

| If the question is | run | what it answers |
|---|---|---|
| is the panel healthy after a boot or a reset? | `tools/state.py`, then `tools/bootcheck.py` | the `conn` snapshot, read-only; then two small and two full uploads. `logo`/`mode` at `2147483647` means it is not healthy |
| did my edit break the wire format? | `python3 -m unittest discover -s tests`, then `tools/verify_protocol.py data/captures/*.txt` | twenty-two offline sections with no hardware, then every captured Windows frame re-encoded and diffed: **181 frames, 0 mismatches** (130 in one session, 51 in the other). The captures are bench files, so in a fresh clone the first section prints those figures and says it did not re-derive them |
| does this firmware know that topic at all? | `tools/fuzz.py`, `tools/probe.py` | no answer = no topic, `400` = topic exists and the body was wrong, `200` = the JSON parsed — which is not the same as the write landing |
| will the panel take *my* file? | `tools/send_image.py FILE`; `tools/fileshape.py` if the file's shape is the question | one upload, judged by the panel's own file notice; the second rotates RGBA, indexed, flat and the vendor's own `.osd` files through one session |
| how fast does the glass tick, and why does the clock only move every 20-40 s? | `tools/frame_lag.py`, `tools/indexprobe.py`, `tools/watchtest.py` | a big frame number and the wall clock painted on the glass, so the answer is a glance rather than a stopwatch. Needs eyes on the unit |
| why did uploads go quiet after a few hundred files? | `tools/session_limit.py` | pushes until the panel stops answering, then tries re-handshake, a DTR pulse and a port reopen in that order and says which one worked |
| is the 0.02 s pause before the bytes load-bearing, and is the order of `transported`? | `tools/writebench.py`, `tools/order_probe.py` | both measured on this panel: **361 of 361** at 0.02 s against **0 of 128** at 0 s, and `transported` acked **0 in 8** right after the last byte against **8 in 8** after the notice |
| can the panel draw the numbers itself, with no uploads? | `tools/realtime.py` | answered on this firmware: no — static logo only, the topic is a display-layer toggle |
| which tachometer channel is the CPU fan? | `tools/fanscan.py --watch 90` | which channel moves with the CPU, from sysfs only; never touches a PWM |
| does the always-on model work — display process plus window on one port? | `tools/display_glass.py` | starts the loop, then behaves only as a client of its control socket through every phase, ~9 min, and exits 1 listing what it did *not* show |
| do the window's own buttons work on real glass? | `tools/gui_glass.py` | the same kind of labelled run through `xigmaui.panel.Panel`, the window's own worker |
| what did the vendor app itself actually send? | `tools/log_timeline.py LOG`, `tools/capdump.py`, `tools/vendor_capture.py` | ALPHA's 6-17 MB logs folded into a request sequence, the Windows IRP captures parsed without a Windows box, and the `.osd` payloads taken back out of them |
| the panel is white from the first second | `xigmalcd-reset --yes` (installed) / `tools/reset_panel.py --yes` (checkout) | the vendor's `recovery`, byte-identical to the frame in its own log; the only repair for fields stuck at `2147483647` |
| what would a frame look like, with no panel in the loop? | `python3 -m xigmalcd --dry-run DIR`, `tools/previews.py`, `tools/preview_gif.py` | PNGs on disk from the same render path; a preview composites over the shipped clip the way the panel composites |
| could a generated layout draw one of our five themes instead? | `tools/knobmap.py` | per option, per theme: the best edit of that theme's own export, and the pixels between the two doors. 28 of the 37 pairs land at 0 px; the other 9 are far from 0, and `tests/test_knobmap.py` holds that split, the counts and the floor being ignored |
| the README's previews move, and how would I make another? | `tools/preview_gif.py --clip CLIP --theme T --series FILE --no-gif` (README's set: `--scale 480 --frames 240 --gif-fps 20-or-24 --crf 20 --no-gif`) | the preview pane's composite as a 10-12 s H.264 MP4 — the shape the README links, uploaded through GitHub's editor because an `.mp4` written into markdown becomes an `<img>` nothing plays; with `--series FILE` or `--live-seconds N` every reading in it comes from a recorded `sensors.collect()` series, so the digits, meters and clock move; it prints the bytes, the frame count and length as the written file reports them, how many passes of the clip that is, and the min→max of what it drew |
| what does the window look like, and does the README's picture match the code? | `tools/screenshot.py` | `docs/screenshot-xigmaui.png`: the real Qt window, offscreen, with a port path that does not exist so nothing on the glass is touched |
| dragging a row in the editor's pane is slow — what does a move cost, and what is it paying for? | `tools/dragcost.py`, `--session` for the reader's own saved session | a real `QMouseEvent` drag through the pane's own handlers: per-move mean/median/worst, the split by call, and the counts (`layout.py` source reads, `ffprobe`/`ffmpeg`/`sensors` spawns, tick paints) that `tests/test_canvas.py` asserts |
| what are ALPHA's theme files, and what do its themes actually contain? | `tools/thm_unlock.py`, `tools/theme_previews.py` | the `.thm` container opened with the app's own constants: 27 layouts, 44 clips, 27 baked overlays in `themes/alpha/`, every byte hashed; and a sheet showing each theme over its own clip |

* `tools/probe.py` — the body-key question: does the panel validate bodies, and
  which key names does it know?  Walks eight display topics (`logo`,
  `presetThemeId`, `rotate`, `osdState`, `sysinfoDisplay`, `displayInSleep`,
  `realtimeDisplay`, `waterBlockScreenId`) against eleven guessed bodies and reads
  the codes as the oracle: `200` landed, `400` means the topic exists and the body
  did not parse, silence means the firmware has no such topic.  That is how
  `presetThemeId {"index":3}` was found.  The two topics now in
  `protocol.BLOCKED_TOPICS` (`logo`, `presetThemeId`) and `waterBlockScreen*` are
  reported as "not sent" rather than written to, and because the remaining six are
  also writes with no readback the tool needs `--force` to send any of them; without
  it, it prints what a sweep costs and exits 1.
* `tools/send_image.py FILE` — upload any PNG or `.osd` file, with the vendor's
  chunk timing (`--chunk`, `--gap`). An `.osd` goes up byte for byte as it is on
  disk; a PNG is re-encoded through Pillow and re-padded, which is what you want
  for a picture you drew and not what you want to test a captured file with.
  Good for testing whether the panel's decoder accepts your file without touching
  the render code.
* `tools/verify_protocol.py data/captures/*.txt` — re-encode every frame captured on
  Windows and diff it against the capture byte for byte, then run the strict checksum
  over every frame the panel answered with. The two sessions are bench files: they carry
  this panel's serial number, so `.gitignore` keeps `data/` out of the repo and a clone
  has nothing to point at here — which the tool says out loud instead of printing zeros.
  What they gave on the author's bench, over both files: **181 host→panel frames
  re-encoded, `mismatched frames: 0`** (130 in the long session, 51 in the one that
  starts at power-on; 88 `transport`/`transported` pairs), `ContentLength` equal to the
  unescaped JSON length in 180 of 181 — the one that declares none is the bodyless
  `conn 1` — and **267 panel replies read, 267 checksum-clean**. Against the long
  session alone: **130 and 0**, 65 pairs, `ContentLength` matching in 130 of 130. If
  you change `protocol.py`, run this.
* `tests/` — the offline checks, run by the standard library:
  `python3 -m unittest discover -s tests`.  One file per subject, and the name says what
  it holds: `test_protocol.py` (encode → decode → re-encode, the `0x5A`/`0x5B` quoting, a
  device reply with a bad checksum still parsed on structure), `test_encoder.py` (what the
  indexed file gives up next to RGBA, and the switches read back out of the PNG each dry run
  writes), `test_pinned_metrics.py` (a pinned frame draws the far end of the ramp and sends
  no metrics blob at all), `test_gauges.py`, `test_ink.py`, `test_conventions.py` and
  `test_specials.py` (what a layout file is allowed to name, held to the pixels it claims),
  `test_theme_library.py` and `test_library_draw.py` (which layouts this canvas selects and
  what they paint), `test_export_parity.py`, `test_knobmap.py`, `test_theme_files.py` and
  `test_editor.py` (the five generated themes, and the layout editor's model),
  `test_media_roots.py` and `test_clip_db.py` (where a clip name resolves, and the dedup
  rule), `test_settings.py`, `test_packaging.py`, `test_packaging_parity.py`,
  `test_debian_changelog.py`, `test_launcher.py`, `test_launch_unit.py`, `test_no_serial.py`,
  `test_docs_links.py`, `test_glass_ledger.py`, and the window's own files:
  `test_window.py`, `test_window_sizing.py` (the owner's sizing rule, as relations: no
  column under what it holds, no sideways scroll at the floor, one/two/three columns of
  rows as the width allows), `test_canvas.py`, `test_pairing.py`, `test_display_remote.py`,
  `test_control_socket.py`, `test_panel_safety.py`, `test_loop_counters.py` and
  `test_zz_isolation.py` (nothing here wrote your session file).
  One rule this suite keeps, restated because it was broken and went red on two boxes at
  once: an offline check may **count**, but it may not *wait on a duration* - a duration
  belongs to a box.  `tests/test_tooltips.py`'s popup helper waited 2 s of wall-clock for
  Qt's `QTipLabel` to appear; on a loaded CI runner (run #170) and on a loaded bench it did
  not, so a check about readable colours failed as a check about CPU load, on 2026-11-12.
  It now waits for the widget to be on screen, repeats the request, and counts event-loop
  spins - and its failure prints the spin count, the visibility state and the top-level
  classes present, so the next one says which end failed.  The same day's other cause was
  suite hygiene rather than timing: a check that ran the window's clip-library populate
  door twice left a `QTimer` nobody could stop (the window names one, and an orphan keeps
  firing two subprocesses a tick into whichever file runs next), so `xigmaui/app.py` makes
  that timer once per window and `test_canvas.py` counts how many there are.
* `tools/verify_manifest.py` — the copied vendor library against its own manifest: all 125
  `files[]` entries re-hashed (27 backgrounds, 27 foregrounds, 27 layouts, 44 clips,
  128,106,463 B), `counts` cross-checked against `files` and against the tree, anything extra
  sitting in a scanned directory named, each layout's declared background matched to the hash
  of the clip it names, and the 27 encrypted `.thm` containers confirmed **absent** - recorded
  by hash, never carried.  `--quick` skips the hashing, `--json` is for a build log.

* `tools/gui_glass.py` — the GUI's drawing paths against the real glass, in one
  continuous labelled run: status, background upload, one frame, `--live-seconds`
  at `--fps`, with the phase name as the theme title so whatever you saw has a name
  and a slot in the log, and its own start/end clock printed. Goes through
  `xigmaui.panel.Panel`, the window's own worker, and cannot queue `reset`.
  `--no-upload` skips the background overwrite, `--no-fans` also takes the tach array
  out of the metrics blob rather than only out of the drawing, and `--mp4`/`--theme`/
  `--clock-size`/`--text-color` pick what goes up - `--text-color` being how a chosen
  ink would finally get in front of the glass, which no run has done yet
  ([limits.md](limits.md) keeps that as an open item). Tee its output into `data/glass/` under a name that
  carries the window's date and time: that file is what the ledgers in [gui.md](gui.md) and
  [limits.md](limits.md) quote, and
  `tests/test_glass_ledger.py` checks that every kept transcript is named by a page.
* `tools/display_glass.py` — the same idea for the other model: it **starts a separate
  `xigmalcd` display process** (given `--duration`, so it cannot outlive the script) and
  then behaves only like a client of its control socket, on a socket of its own
  (`xigmalcd-glass.sock`, never the login unit's). Phases: the loop drawing, `--status`
  from the command line, the window's Apply as the socket speaks it (the seven settings
  commands plus a `title` label), `pause`, one `frame`
  asked for while paused, `resume`, a queued background upload, an on-purpose `reset`
  request (refused, because the display was started without `--allow-reset`), and the
  wait for the loop's own session renewal. Each phase names itself on the glass through
  the `title` command, the counters are read back after each one, and the run exits 1
  with a list of what it did *not* show if the pause moved any frame, if the paused
  `frame` drew nothing, if `resume` did not renew, if the upload's notice did not
  arrive, or if no renewal came. Nothing here can send `recovery` — the display is
  started without the flag that would allow it — and nothing sends anything
  firmware-shaped. ~9 min at `--fps 1`, and the log belongs in `data/glass/`.
* `tools/makeicon.py` — redoes the project's mark: `install/xigmaui.png` (256 px, what
  the menu entry and the window use), `install/xigmaui.ico` (the same mark at 16 px
  through 256 px) and `docs/logo.png`.  The source is the committed artwork
  `install/artwork/xigma-penguin.jpg`; because a JPEG cannot carry alpha, the tool
  turns the transparency checkerboard painted into that JPEG into real alpha, keeping
  only the grid the picture's border can reach so the penguin's equally white belly
  survives.  `--draw` makes the other icon instead: the alpha theme drawn by the
  daemon's own `render.draw` over a frame of the shipped clip, numbers pinned, which
  is the one to look at when the question is whether the display code is right.
* `tools/session_limit.py` — push frames until the panel stops answering, then try the
  three candidate cures in order (re-handshake, DTR pulse, port reopen) and report
  which one works. This is how the session-limit behaviour and the cure were pinned
  down; ~6 min at 2 fps, ~9 min at 1 fps.
* `tools/fuzz.py` — the live oracle for unknown topics: no answer means the firmware
  does not know the topic, `1 200` means accepted, `1 400` means the topic exists but
  the body was wrong. The topics in `protocol.BLOCKED_TOPICS` are dropped from its
  table before the first request (`--grep mode` reports that and sends nothing), and
  `recovery` is not in the table at all.
* `tools/vendor_cmds.py` — every command the decompiled vendor app registers, one at a
  time, with the panel's verdict; `--shapes` also probes topics ALPHA registers but never
  calls, `--list` prints the table without touching the port. It no longer sends
  `presetThemeId` (that entry in its old SAFE list is what blanked a unit — see the danger
  note below) and its `--risky recovery` flag is gone: `recovery` belongs to the reset
  command only.
* `tools/realtime.py` — `realtimeDisplay {"enable":true}` plus a metrics heartbeat, with
  no uploads during the experiment itself, to ask whether the panel can draw the numbers
  itself. **Answered, on this firmware: it cannot.** The screen showed only its static
  logo; the topic acts as a display-layer toggle (`--disable` to turn it back off), and
  the tool ends by uploading one gauge frame so the glass is left showing something.
* `tools/reset_panel.py` — the vendor app's own reset, one request, sent by exactly one
  hand-invoked command. In a checkout that command is this script, a thin wrapper over
  `xigmalcd/reset.py`; on an installed system it is `xigmalcd-reset`, the same module
  through pyproject.toml's entry point, because an installed box has no `tools/` to run.
  Dry run by default; `--yes` sends `POST recovery 1 {"enable":true}`, byte-identical to
  the frame in ALPHA's log at 18:39:48 on 2026-11-05, prints the frame
  first, and then waits for the USB device to come back and re-reads the state. This is
  the only thing that repairs a panel whose `logo`/`mode` sit at `2147483647`.
* `tools/theme.py` — read-only by default: reports `mode`, `logo`, `osdState`, `space`
  (`--watch N` to repeat) and says so plainly when the theme fields are at the panel's
  "not set" value. Writes only with `--force TOPIC VALUE`, and states the cost first.
* `tools/keyprobe.py` — the body-shape oracle that proved those topics are unwritable:
  it tries a key list against one topic and checks the field for a **round trip**, because
  a `200` only means the JSON parsed. The run that settled this reported **23 of 23**
  bodies for `logo` answering `200` and leaving the field at `2147483647`; its `KEYS`
  list holds 22 names today, so re-running it prints a different count — the finding,
  not the count, is the part that was measured. `logo`, `mode` and `presetThemeId` are
  now guarded by `Link`, so it refuses to run against them without `--force`, and says
  what the write costs first.
* `tools/state.py` — read-only snapshot of what `conn` reports (`--watch N` to repeat).
  The first thing to run after any boot or reset; it writes nothing.
* `tools/fanscan.py` — every tachometer channel Linux can see, the candidate Super-IO
  drivers with their real `modinfo` descriptions, what each channel is named by
  `sensors.FAN_CHANNELS`, and the two fan figures `alpha` would draw from them.  It also
  prints **which channel answered each of the two fields that had been answering from the
  wrong place**: the three tiers behind `motherboard.temperature` (Super-IO / DIMM SPD
  thermistors / network die as last resort), the one that won and the labels that were
  refused, and for `disk.temperature` the root drive the mount point names, every drive's
  composite against its hottest and coolest raw probe, and which of those the row prints.
  That makes it the command to run before believing any of the figures quoted for those two
  fields in these pages - they are bench numbers, and this tool reprints them on yours.
  `--watch 90`
  samples the tach channels across a warm-up and says which one moves with the CPU, which is
  how the CPU fan gets identified without guessing; it only reads sysfs, never a PWM. Since
  2026-11-13 it samples the `pwm*` **outputs** in the same window and prints their spans beside
  the tach spans - raw 0-255 and the same number over 255 as a duty percent - because that
  pairing is how a pump tells itself from a case fan here: `fan2` held 2443-2469 RPM (spread
  5-10) across 15-23 rounds while its own header's duty swept 152-231 in lockstep with
  `pwm1`, which is the channel `FAN_CHANNELS` now pins as `CPU PUMP`/`Pump`. The watch lines
  also say `pinned as 'CPU PUMP' (Pump)` instead of guessing at a channel the table already
  names. It
  never opens the panel, and `--demo` draws the layout with invented RPM values (titled as
  such) to check the worst-case widths.
* `tools/capdump.py` — parses the UTF-16 Windows IRP captures (`records`, `stream`,
  `frames`, `uploads`) so the vendor's own traffic can be read without a Windows box.
* `tools/replay.py` — put real pictures on the panel and time every verdict:
  `--source vendor` replays ALPHA's own extracted `.osd` PNGs byte for byte,
  `--source ours` renders our themes; it prints per-frame verdict latency, which is how
  "the panel is falling behind" was ruled out. `--extract` pulls the vendor frames out of
  a capture into `data/vendor_frames/`.
* `tools/indexprobe.py` — the self-instrumenting rate measurement: frames carry a big
  frame number plus the wall clock, so one glance at the panel says which frame it is
  showing, and two glances give the panel's rate and its lag. `--cadence`, `--encode
  rgba|pal8`, `--overlay`, `--plain`.
* `tools/vendortest.py` — the ALPHA-faithful driver, for asking why ours looks slower on
  the glass when the bytes are the same: same handshake, MP4 background uploaded first
  (`--mp4`), the vendor's own file-name format, `--frames DIR` to replay captured vendor
  PNGs byte for byte, `--name-a/--name-b` to shift the wall clock inside those names,
  `--no-wait` for our client's fire-and-forget style. Prints cadence and verdict statistics
  and leaves the last frame huge magenta so a glance after the run says where it stopped.
* `tools/writebench.py` — how long one upload spends on the wire and what moves it: bytes
  on wire vs the panel's verdict, for write chunk sizes, the gap before the first byte
  and baud. 30 KB lands in 24 ms at 0.02 s gap. **Its `gap=0` result stands**: the note
  here used to say the `400`s were an artefact of the old blocking reader, but a clean
  A/B at the daemon's own rate settled it — two back-to-back 120 s windows at 3 fps on the
  same panel, `--gap 0.02` then `--gap 0`: the default took **361 of 361**, while `gap=0`
  took **0 of 128** - 127 `400`s and one notice that never came, with 64 re-handshakes in
  between achieving nothing (08:56:29 and 08:58:42, PROTOCOL.md §6). The pause is
  load-bearing, not politeness, and a fresh-session sweep with one 24 550-byte vendor
  frame puts the boundary in the same place: 0.02 s took 8 of 8, ALPHA's own 0.011 s took
  a mix, 0 s took none - every refusal landing ~508 ms after the announcement, which is
  how long the panel's media writer waits before giving up on a session it just granted.
* `tools/cltest.py` — proves the other half of the upload rule: the `transport` frame must
  carry a `ContentLength` header. Same frame, same name, six uploads with the header and
  six without: with it, 6 of 6 taken; without it, no ack for the announcement and no file
  notice at all, yet `transported` is still answered `{"state":"success"}` six times. That
  last part is why the failure is easy to miss - a client watching the ack sees success.
* `tools/order_probe.py` — one real vendor frame, uploaded many times, with every answer
  timestamped as it lands, for four settings. What it settles is that the **ordering of
  `transported`** changes what the panel does: sent right after the last file byte it was
  acked 0 times in 8 (1 in 6 in an earlier run), sent after the panel's own notice 8 in 8.
  Its `--only tight,notice` runs the settings in the order you name, each on a session of
  its own, which is how the gap rule was checked for a warm-up artefact; `--frames N`.
* `tools/watchtest.py` — answers display questions without a stopwatch: every phase puts
  its own letter and frame number on the screen and the windows run minutes long, so any
  glance is a data point and you report the letter you saw rather than watching a moment
  chosen for you. `--phases` picks the shapes, `--phase` their length: A our old upload,
  Z the vendor ordering at our block size, K ALPHA's 1024-byte blocks with our old
  ordering, X both (the vendor shape), plus U one write, P/Q file names dated in the past
  or future, T small frames, R ALPHA's own captured bytes replayed.
* `tools/log_timeline.py LOG` — ALPHA's logs are 6-17 MB of one-second uploads, which hides
  everything else; this prints the request sequence with runs of picture uploads folded
  into one line, plus `--census`, `--names` and `--replies`, and `--from/--to/--around` to
  restrict it to one session.
* `tools/previews.py` — the **still** composite: `docs/preview-<theme>.png`, our transparent
OSD over one frame lifted out of the vendor's background MP4. README does not embed these;
it links the moving MP4s from `tools/preview_gif.py`. The PNGs are not tracked (`.gitignore`
says so), because they are what you run this tool to *look at* after a change to the skin,
not an artefact the tree has to carry in two shapes. Its background defaults to
`media/Theme_25.mp4` and takes any clip you point it at.
* `tools/preview_pin.py` — the readings the **still** previews and the caption-shaped GIFs
draw, in one place, so a caption cannot disagree with the file beside it. Two kinds of
number, labelled: the temperatures, loads and two fan figures are a *fixture* — 57 °C CPU
and 47 °C GPU, the pair ALPHA's own captured frame reads, and 1 957 RPM, inside the
tachometer span PROTOCOL §8 measured without being this box's live number — because those
decide where the arcs land, and 57 °C on the `gauge` theme's measured 30..75 °C scale is
60 % of the sweep, in the part of the ramp where the colour changes too. The memory, board,
disk and CPU-power fields are a dated `sensors.collect()`. The file also records what this
box *actually* read - 73 °C at 89.8 % under eight parallel decodes, 70 °C at 8.8 % with a
GPU-using process running - and why the picture uses neither: at 73 °C that arc sits at
95.6 % of the sweep, which reads as pegged rather than as a measurement. The README videos
do the opposite on purpose, and draw from a recorded series instead: see the next entry,
and `docs/videos/readings-2026-11-08.json`.
* `tools/preview_gif.py` — the same composite **playing**: `ClipPlayer` decoding the
background in sequence and `render.draw` drawing our layer over each frame, which is what
the window's `playing` preview pane shows. It opens no device and needs no Qt. Two shapes
out of one code path:
**GIF** (`--out x.gif`, the default) - short, one pinned reading, `--clock` freezing the
whole frame's clock (the `clock` theme draws a date line too, so `--clock 11:07:42` pins it
to the tool's reference day, 2026-11-05, rather than letting it follow the machine); and
**MP4** (`--mp4 --no-gif --out x.mp4`) - 10-12 s at the
clip's own frame rate, driven by `--live-seconds N` (sample the box once a second and
record it with `--record FILE`) or `--series FILE` (draw from a series recorded earlier, so
six files show one minute of one machine, in the zone that minute was sampled in - the
series JSON records `clock_offset_s`, and a render honours that instead of its own machine's
zone). README's set is six of the second kind, at the
panel's own 480 px, `crf 20`, `preset medium`. The switches are `--clip --theme --ink
--frames --gif-fps --scale --colors --clock --scrim --out --mp4 --no-gif --crf --preset
--live --live-seconds --series --record`, and the tool prints its own measurements, because
these knobs interact in ways nobody guesses right:
  * **sample, never repeat.** Decoding at the clip's own 20-24 fps and then telling ffmpeg
  `-r 6` shows one frame three times running, and GIF is built on inter-frame diffs:
  7 205 675 B for what sampling at the target rate writes in 1 510 157 B, the identical
  animation. So the sampling happens here, keeping every `rate/gif_fps`-th frame of the one
  stream. In the README videos `--gif-fps` equals the clip's own rate, so nothing is dropped
  and the picture is the clip's motion, not a resampled one.
  * **the input has to be looped to be longer than itself.** `-frames:v` against a 0.96 s
  clip stops when the clip does, which made a whole sweep of "3 s and 5 s animations" come
  out as five rows of the same 12 frames. `-stream_loop -1` is what makes an n-second GIF
  out of a short loop - and it is also what the glass does with the file. The videos report
  how many passes of the loop they contain: `alpha` 10.4, `gauge` 5.7, `dual` 1.8,
  `bars` 1.2, `clock` 0.6.
  * **the palette budget only applies to the GIF path.** ffmpeg's GIF encoder already
  offsets and diffs frames (`gifflags=offsetting+transdiff`, on by default), and `gifsicle`
  is not installed on this bench and would need a password to add, so what is left is scale,
  rate, length and colour count: 128 colours measured **23 % smaller** than 256 with the
  drawn colour still within 1/255 at 480 px; 64 colours is where ink starts moving at
  320 px (7/255); dither off is ~10 % smaller and bands the gradients; `stats_mode=diff`
  measured 2-3 % *bigger* here. For MP4 the equivalent knobs are `--crf` and `--preset`:
  crf 20 / medium on the five previews measured 214 KB - 1.93 MB (the spread is the
  background: `Theme_30.mp4` moves 0.46 of a mean-absolute step over 3 s, `theme_52.mp4`
  moves 7.41), and crf 18 / slow is about 40 % bigger.
  * **delays are quantised - GIF only.** A 6 fps GIF is 12 frames at a **170 ms** delay,
  not 167: GIF stores delays in 10 ms units, so the file runs 2.04 s at 5.9 fps. An MP4
  carries a frame rate instead, and the tool now reads it back with ffprobe rather than
  trusting its own arithmetic: all six README files report 240 frames at 24 or 20 fps =
  10.00 s or 12.00 s as written.
  * **what the file did to the ink, measured off the file.** The GIF path reports the
  nearest drawn colour to the ink asked for - the 0.6 suite wrote a 160 px, 6-frame,
  128-colour GIF and read `#ffc400` back as **(252, 197, 2)**, 3/255 off, on this bench. The
  MP4 path asks the harder question, and answers it per pixel: of the **2 268** pixels the
  layer paints at exactly that colour, the written file holds 1 144 within 3/255, 2 187
  within 8/255, 81 unchanged. Two questions, printed side by side, because neither is the
  256-colour PNG the upload path sends (§10 measures that drift at 1/255 per channel).

README's set, as `du -b docs/videos/*` and `ffprobe` read them on this bench: `alpha`
908 420 B / 10.00 s at 24 fps, `gauge` 1 930 104 B / 12.00 s at 20 fps, `dual` 214 113 B,
`clock` 278 884 B, `bars` 859 706 B (re-rendered 2026-11-12, when the theme's row geometry
moved), the amber ink figure 927 752 B — **5 118 979 B** for
six, plus 13 916 B of readings JSON. Those are this bench's figures, re-read rather than
promised: the gate that used to fail this page when one moved is gone, and the reason it
existed is the reason it is not worth re-writing - the 22 405 B the `bars` clip shed when
its fan slots were re-rendered on 2026-11-08 was a fact about a re-render, and a page that
carries the command to re-read it stays true through the next one.
Nothing gates these six files as documents any more, and that is a choice rather than an
oversight: the claims are frame count against the length and rate the written file reports, a
length in the 10-12 s README promises, a size ceiling, the
untouched field matching the clip each marker names (gaps 0.1-13.6), glyph against
its own halo over a floor of 30, the plate's effect measured both ways on the bright clip
(53.5 without, 93.0 with), and the motion claim in two directions: the file has to change
where the layer paints (at least 3/255, and 1.2x the untouched field) *and* the two layers
it was built from have to differ over 622-6 226 pixels once each sample's own clock is put
back. Re-read the first three with `ffprobe` and the ceiling with `du -b`; the rest belongs to
the encoder pass that wrote the files, on one bench, and is quoted as that.  Pointedly no byte
hash: x264 output is its version's business, and a different runner could write different bytes
of the same animation.

* `tools/knobmap.py` — the question the theme-editor plan keeps meeting, measured: every
  drawn theme also exists as a generated layout file, so could the file door draw it instead?
  For each theme, `inspect` takes the options its own body accepts (never a table of them kept
  by hand), one representative value is chosen for each — from the strings the body actually
  compares against (`gradient` takes `heat`, not an invented word that would take the default's
  branch), or by flipping a bool, or a size the socket itself documents (40 of 8..120) — then
  the best edit of that theme's **export** is found and the two doors are compared at one
  pinned reading dict and one pinned clock instant.  No port, nothing uploaded.
  `--json` writes the rows; `tests/test_knobmap.py` runs the tool and holds its
  structure: every signature option is a row or an unread note (the unread list re-derived
  here with `ast`, so the tool cannot quietly drop an option and make the map look clean),
  exactness is binary with a 900 px floor taken from the run, and the reader's ink and the
  default transparent canvas are exact for all five.  It also routes each option out of
  `main._theme_kwargs` with `ast`, because an option in a signature is not a flag: `big` is a
  *size* with no CLI route.  The same reconciliation is what found `theme_clock` taking a
  `clock` argument its body never read, so `--no-clock` moved that theme 0 px; the body
  honours it now (0.4) and the section holds that pair at 0 px in both doors, which is why
  the map has no unread option left.  The counts, the sets and the floor are quoted in
  docs/limits.md and re-derived on every run; the non-zero pixel figures walk glyph edges and
  installed faces, so they are printed beside the machine and never quoted as fixed.
* `tools/screenshot.py` — regenerates the README's three pictures of the **window** rather
  than of the glass: `--mode three-column` writes `docs/screenshot-xigmaui.png`, `--mode
  simple` writes `docs/xigmaui1.png` (the `advanced controls` switch left off, as a first run
  shows it) and `--mode advanced` writes `docs/xigmaui2.png` (that switch on, with
  `--layout NAME` opening one layout in the editor).  The picture was remade on 2026-11-13,
  when the copy button's label changed and that row is the thing a reader is being shown:
  `tools/screenshot.py --mode advanced --layout bars --device PATH`, the path a nonexistent
  one on this bench, whose `/dev/xigmatek-lcd` is a real panel.  On a bench where this project's udev rule
  is installed, `/dev/xigmatek-lcd` exists and the tool refuses to run - the safety door
  working, not a bug - so a capture there points `--device` at a path that is not there: a real `xigmaui` built the way `tests/test_window.py`
  builds it
  (`QT_QPA_PLATFORM=offscreen`, `XDG_CONFIG_HOME` in a temporary directory so no remembered
  settings shape the shot, `XIGMA_SOCKET` pointed at nothing so the window is its own boss),
  pumped until the clip rows have their ffmpeg thumbnails, then `grab()`ed. It refuses to run
  if the `--device` path exists, because in this mode the window's own status read opens the
  port, and a screenshot is not the thing to take someone's panel over with; the default is
  `/dev/xigmatek-lcd`, which on a capture machine has nothing behind it.  `--size WxH`
  frames it (`--size`, default 1440x1024, the window's own fresh default, which is what
the README's picture shows: the three columns side by side, nine rows of the clip list on
this bench and ten rows of the clip list with CI's fonts).  The window is resizable down to
its own floor of 1280x1024, so that framing is a choice and not a claim about the layout:
  `tests/test_window_sizing.py` checks the column rules themselves: every column gets at
least what it holds, no column scrolls sideways at the window's own floor, a drop-down's list
carries the widest entry any layout can put in it, and the field grid takes one, two or three
columns according to the width the controls column has.  Nothing about the layout is fixed by
the picture: the preview column caps itself at the 480 px frame, the clip library is a column
of its own, and the splitter is the user's - which is what that file asserts instead, along
with the floors under those columns, which is what a 1180 px window could not hold.  The size
and row-count sentences above are labelled as bench figures and re-read by whoever looks; no
gate keeps this page's copy of them honest, and that is said here rather than discovered by a
reader.
* `tools/dragcost.py` — what one drag of a row inside the editor's pane costs, **on the box
  running it**. It drives the shipped door and nothing else: a real `xigmaui`, a real
  `QMouseEvent` press/move/release handed to the preview pane's own handlers, the row moving
  through `Editor.move_to`, `processEvents()` between the moves as an event loop gets them.
  It prints per-move mean, median and worst, the time split by the call that pays
  (`Editor.paint`, `_repaint`, `_show`, `_fit`, `_captions`, `_canvas_marks`, `snap_move`),
  and the **counts** - `keys_read` calls, reads of `layout.py`'s source, `ffprobe`/`ffmpeg`/
  `sensors` subprocesses, tick paints - which are the same quantities `tests/test_canvas.py`
  asserts, so a figure here and a check there are one statement about one path. `--session`
  copies the reader's saved config (window size, split, clip, canvas, `preview_fps`) into a
  temporary settings root and restores *that*, so the number is of a session somebody
  actually runs and the real settings file cannot be written; `--drags N` matters because the
  first drag lands while the clip library is still probing clips and is not the same act as
  the later ones; `--pane-readings fixture|sensors|file` drags while the pane is painted from
  the pinned body, **live** from this machine, or a held `--metrics-file`, because a mode that
  draws the file twice per event and one that draws it once look identical on screen and 8 ms
  apart under the pointer; `--profile` adds a cProfile pass, labelled with its own overhead.
  In held mode it says so and stops rather than reporting a drag: that mode refuses a press by
  design, and a measurement of nothing is not a figure. Like
  `tools/screenshot.py` it refuses a `--device` path that exists - the window's status read
  would open the port - and `--allow-port` is there when measuring the real session is the
  point; either way it sends no frame.
  **The record, this bench, 2026-11-12**, `--session --layout bars --moves 25 --drags 3`,
  the same command run against the tree before the three fixes and the tree after: first drag
  **133.2 ms** a move and the drags after it **44.8 / 40.8 ms** (worst **242.5 ms**) before,
  **11.6 / 11.5 / 10.8 ms** (worst **13.6 ms**) after, with reads of `layout.py`'s source
  going from **5.72 per move to 0.00** and media/sensor subprocesses from **0.71 to 0.01**.
  And the same command with `--on-display`, on this bench's own Wayland desktop at the saved
  3072x1646 window, which is where the complaint was felt: **131.2 ms** for the first drag
  and **41.0 ms** for the next, worst **230.5 ms**, at `ba92167`; **12.2 ms** and a worst of
  **16.6 ms** now.  The offscreen and on-display figures agree to within a millisecond and a
  half after the fixes (**11.3** against **12.2**), which is what lets this page say the
  compositor was never part of it - and the tool prints which platform it measured, because
  those two numbers answer different questions.
* `tools/asar_extract.py ASAR` — read an Electron `.asar` without node: list, unpack,
  `--cat` one file, or `--find TEXT` to grep file *contents*, which is how the string
  constants in the app's compiled main process (`out/main/index.jsc`) get mined.
* `tools/thm_unlock.py` — read ALPHA's `.thm` theme files.  The container is a ZIP with
  one hex-text entry, and the cipher's own literals are in that bytecode constant pool
  (`aes-256-cbc`, `Byyeetek2368`, `427979656574656b`, `sha256`), so `key =
  sha256("Byyeetek2368")` and `iv = "ByyeetekByyeetek"` open all 27 without guessing.
  Writes `themes/alpha/`: layouts as readable JSON (base64 media replaced by `mediaFile`
  references), the clips and baked overlay PNGs, and a `manifest.json` hashing every
  byte.  `--write --no-thm` is how this tree is written: the vendor's encrypted `.thm`
  containers (66 300 082 B for 27 of them) are not copied, but their vendor path, size
  and sha256 are still recorded, so the record of them is checkable — the originals come
  from the vendor's installer, whose URL is in `themes/alpha/README.md`.  `--write` is
  idempotent — a re-run reports `kept`, 99 of them, 0 rewrites — and `--verify --to
  themes/alpha` re-checks the tree against that manifest with no Windows volume mounted
  (**125/125 hashes match**, measured 2026-11-07); add `--from DIR` and it also re-hashes
  the 27 files this tree does not carry, where they actually are (**152/152** on the
  author's bench, volume mounted).  Reads files, writes files, never the panel.
* `tools/theme_previews.py` — composite every copied theme onto a contact sheet: one
  frame lifted from the theme's own clip with ffmpeg, the theme's own baked overlay PNG
  composited over it, so the sheet is a picture of the vendor's theme and not of our
  drawing.  Prints what ffprobe says about each clip (fps, frames, duration) as it goes,
  and treats a `PNG` background as the still it is.  Output:
  `docs/previews/alpha-themes-480X480.png` (23 themes) and `-320X240.png` (4).
* `tools/colourtest.py` — the same measurement with nothing to decode: flat solid-colour
  frames, 1 584 bytes each, ending on bright magenta. Counting colour changes gives the
  panel's tick, and landing on magenta proves it shows the *newest* frame rather than
  working through the ones it took.
* `tools/cadence.py` — sweeps upload cadence in labelled phases (each phase prints when it
  goes quiet) to ask whether slowing down makes the panel keep up.
* `tools/bgtest.py` — store one of the vendor's 480×480 MP4 theme backgrounds as media and
  then paint over it, to test the two-layer model. The file really lands, and **it does
  play**: with transparent OSD frames over it the animation shows behind the gauge
  (08:38:30-08:40:30, "background video visible behind the gauge"). The daemon does the
  same upload at session start with `--mp4`.
* `tools/restore.py --media FILE` — puts a picture source back on a panel that has nothing
  stored, in the order ALPHA's log shows: announce, wait for the reply, 1000-byte writes,
  then `transported` (`--name` to store it under another name, `--cadence`, `--gap`,
  `--timeout`). It reports the two counters that say whether the panel took it: `space`
  should drop by the file size and `logo` should stop reading `0x7fffffff`. Nothing here
  touches `recovery`, `config` or `type:"firmware"`.
* `tools/pages.py`, `tools/probe.py`, `tools/topicscan.py`, `tools/preset_probe.py` — the
  topic/body discovery sweep with the reply code as the oracle. The rule these now
  follow, and the reason is the danger note in [Notes and known limits](limits.md): asking a
  topic whether it exists is done by **writing** to it, so every one of them refuses to
  send anything to a topic `Link` guards (`logo`, `mode`, `presetThemeId`, `theme`,
  `themeBackground`, `logoSet`, `waterBlockScreen*`, firmware) unless told twice, and
  each prints what the write costs before it asks for that permission.
  `topicscan.py` and `probe.py` decline the guarded names and say "never asked: our own
  guard" rather than letting them land in the silent column, which would read as "the
  firmware has no handler"; both also need `--force` before they will POST the
  *unguarded* candidates, because those are writes too and nothing on this panel can be
  read back afterwards. `pages.py` and `preset_probe.py` are the exceptions that are
  meant to exist: their whole subject is those guarded writes, so `--force` opens a
  destructive link, and `pages.py` ends by uploading a fresh frame and re-reading `conn`
  so a person can look at the glass instead of trusting the wire. `preset_probe.py`'s
  oracle is `logo` moving, so it says plainly that it cannot undo what it finds.
* `tools/commands.py` — probes the command set the Windows captures never showed, every
  candidate taken out of the string pool of ALPHA's own compiled main process
  (`tools/asar_extract.py` is how that pool gets read). `-v` logs both directions,
  `--send 'GET osd 1'` (with `--body`) sends one arbitrary request, `--mutations` tries
  the reversible ones (brightness, degree) and puts them back. No firmware/update topic,
  no mediaDelete.
* `tools/media_types.py` — what the media channel actually accepts: text, junk, PNG, and
  real 480×480 H.264 MP4, one verdict line per file (`--file x.bin` to try your own). It
  refuses `.zip`, which is the firmware path.
* `tools/burst_upload.py [SECONDS] [THEME]` — render our own frames and upload them with
  the sequence the panel takes, printing its file notice per frame. The fastest proof the
  media path is alive.
* `tools/vendor_log.py LOG` — ALPHA writes every frame it sends and receives as hex, so
  its own log files (`AppData/Roaming/alpha/logs/*.log`) are a protocol capture and the
  authoritative word on the protocol. `--verify` re-encodes every request in the file byte
  for byte (**1672/1672** on the current app), `--uploads` lists upload pairs with timing,
  `--space` tracks the panel's free space, `--dump N` prints exchanges.
* `tools/vendor_capture.py CAPTURE` — the IRP-level Windows monitor log
  (`data/captures/*.txt`, UTF-16, also bench-only for the same reason) also contains the
  raw file stream that ALPHA never logged. It rebuilds every upload byte for byte: **65/65
  payloads match their declared `fileSize`**, all 480×480 8-bit RGBA PNGs, streamed in
  1000-byte writes. `--extract N` saves them as known-good test files.
* `tools/bootcheck.py` — the panel's state plus a small and a full-size upload, twice
  each (`--n`, default 2), in one short run: the first thing to run after the panel has
  been power-cycled.
* `tools/cycle.py` — times each step of one upload (announcement, gap, raw bytes,
  confirmation) and sweeps baud, gap and chunk size. This is what separated the two
  halves of the exchange: our writes take 21–54 ms, the panel's reply is the slow half.
* `tools/hotpath.py` — a reader thread that stamps every panel reply when it arrives, not
  when the client gets round to reading, then sweeps upload cadence over
  `--cadence 1.5,1.2,1.05,0.9,0.7,0.5,0.3` (`--trace` prints the whole arrival log,
  `--cadence` picks your own). This is the tool
  that killed the "~1 fps ceiling": notices land 70–110 ms late at every cadence, and 3
  fps is refused nothing — its fastest step, 0.3 s, is 3.3 fps.
* `tools/fileshape.py` — rotates candidate files (our RGBA and indexed PNGs, a flat one,
  and the vendor's own extracted `.osd` payloads) through one session to ask whether the
  file decides the reply speed. It does not: every shape answers in 60–110 ms.
* `tools/frame_lag.py` — for the display side rather than the wire: pushes a big visible
  frame number at a steady rate, then goes silent, and the question is what the *screen*
  does and when. That is the tool that answers the "the clock only moves every 20–40 s"
  symptom, so it needs eyes on the unit.
