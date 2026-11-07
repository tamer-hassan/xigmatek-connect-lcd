# Notes and known limits

What has been measured on glass, by whom, with how many frames - and what has not. Every number here names the run it came from; the gaps are named too.

* **A frame costs one upload, and its verdict is read as part of it.** The loop sends
  `transport` + the file + `transported`, and `Link.send_media(order="notice")` holds that
  last request until the panel's file notice has landed — which is exactly the order ALPHA's
  traffic has, and it costs 30–50 ms of the 1 s frame slot. Counted end to end at 1 fps:
  **240/240 frames confirmed accepted in a four-minute window**. The old fire-and-forget
  shape (`transported` right after the last byte, verdict harvested later) is still
  available as `--order fast`, and it is what the panel answers 1 time in 6.
* **The panel displays one frame per second from Linux too — the ordering of `transported`
  is what decides it.** Say `transported` while the media writer is still busy (right after
  the last byte) and the panel stores the file, answers the upload, but answers the
  confirmation once in six times, and the picture changes once every 4–6 seconds. Say it
  after the panel's own notice, as ALPHA does, and it answers 6 times in 6 and the glass
  ticks every second. Same session, same panel, watched back to back: vendor order
  08:02:28–08:06:28 perfect at 1 Hz, our old order 08:06:28–08:10:28 "dropped back to jumps
  indeed", vendor order again 08:10:28–08:14:28 "ticking beautifully at 1Hz"
  (`tools/watchtest.py --phases XA`, `tools/order_probe.py` for the wire side).
  Everything else that used to be blamed for the 4–6 s is cleared: frame bytes (ALPHA's own
  `.osd` PNGs replayed verbatim), cadence, file-name format, RGBA, transparency, metrics
  traffic, the theme MP4 first in the session, a `recovery`-reset panel, and the host stack.
  The write chunk size is cleared too, by a 2x2 where each combination was watched:
  1000-byte blocks in the vendor order tick at 1 Hz, 1024-byte blocks in the vendor order
  tick at 1 Hz, 1000-byte blocks sent early crawl, and 1024-byte blocks sent early crawl
  (`--phases ZAXK`, PROTOCOL.md §9).
* **The picture is transparent, because ALPHA's is.** Its `.osd` frames paint 4.6 % of the
  230 400 pixels and leave the rest fully transparent, which is how the stored background
  keeps playing behind its gauge (`data/vendor_frames`, measured in PROTOCOL.md §9). So the
  daemon's canvas is transparent by default now; `--bg black` is the old opaque picture,
  which covers the background layer completely. `--mp4 [PATH]` uploads a background the way
  ALPHA does at session start - `media/Theme_25.mp4` (215 KB, the vendor's own pairing for
  this theme) by default, which the panel holds across session renewals (only `recovery`
  clears it); `--no-mp4` skips the upload and leaves the panel's stored file playing.
* **The gauge follows CPU temperature, exactly like ALPHA's, and an idle desktop CPU is
  nearly constant, so it looks static.** Proof that it follows: a 4-core burn took this box
  to 93 °C and the arc tip swept from pegged down to 38.5 % of the arc as the temperature
  fell to 48 °C, one step per second. For comparison, across ALPHA's own 65 captured frames
  its tip moved 14 degrees in 43 seconds. Its scale is also tighter than the one we assumed:
  its digits read 57 °C at 60 % of the sweep, so about 30..75 rather than 30..90 - the skin
  now defaults to that (`--cold`/`--hot` to change it). `--gauge-source load` drives the arc
  from CPU busy percent instead, which moves every second - watched on the glass as
  window W3 (08:42:56-08:44:56, 121/121 accepted): "the arc swings every second
  successfully".
* **The on-screen clock runs up to one frame period behind the machine's.** The panel shows
  the newest file it has *committed*, and that frame was rendered and committed some time
  ago; at 1 fps the seconds digit is therefore 0.1-1.0 s stale at any glance (mean ~0.5 s),
  which is what "about a second behind" was. Measured both ways on the same picture with
  only the rate changed: 1 fps "the clock is ~1 s behind" (08:38:30), 3 fps "the clock seems
  to be matching the linux system's time" (08:40:43), where the panel took **361 of 361 frames
  in 120 s with nothing refused** - at 3 fps the frame is at most ~0.45 s old, which the eye
  stops resolving. ALPHA has the same ~1 s lag at its 1.013 s period,
  hidden by a Windows clock that is nearly two hours off. So `-f 3` is the rate if the clock
  matters and `-f 1` if matching the vendor's write cadence matters: 3 fps is 259 200
  uploads a day instead of 86 400, and it renews the media session every ~167 s rather than
  every ~300.
* **The OSD latches the last frame it took.** Stop uploading and the picture stays up
  indefinitely — no fade, no timeout, no fallback to the logo. `recovery` is what clears
  it (`osdState` 1 → 0).
* **Video plays.** The media channel accepts a 480×480 H.264 MP4 (`yuv420p`, 20 fps, no
  audio), it occupies flash, and the background layer then
  animates on the glass — ALPHA's own 659 338-byte background, uploaded from Linux, played
  on a loop. That file is **101 frames at 20 fps, a 5.05 s loop**, and its very first frame
  is pure black, so a black start is not the panel failing. The panel takes the whole 659 KB
  in **0.7 s** (one pause per upload, not per chunk), and re-uploading the same file name
  moves `space` by 20 rather than 644 because the ledger treats it as a replace. Two things
  used to make this look broken: fully opaque frames cover the
  background completely (the canvas is transparent by default now; `--bg black` is the old
  look), and a `recovery` puts the still logo back until
  the file is re-uploaded, which is exactly what ALPHA does at the start of every theme
  session (`--mp4`, `tools/vendortest.py --mp4`, `tools/bgtest.py`).
* **The panel sleeps when traffic stops, and a running loop keeps it awake for free.** After
  the 60 s keepalive we ask for at connect, a idle unit is found with `brightness: 0`. A run
  that starts into a dark panel wakes it with one `POST power {"event":"resume"}`, which
  `hello()` does — confirmed on the glass, not just by the ack: a session that connected to
  a sleeping panel was watched for its whole 400 s window showing its own title with the
  background moving behind the gauge. So no extra wake traffic is needed; `--no-sleep`
  exists if you want the panel never to sleep at all.
* **Danger: never write `logo`, `mode` or `presetThemeId`, and never send firmware
  traffic.** Those three topics answer `200` to every body tried (23 shapes each at the
  time; the list in `tools/keyprobe.py` holds 22 names today, so that count is a
  date-stamp rather than something to re-derive) and each
  write leaves the field at `2147483647`, the panel's "not set" — writing `{"index":3}` to
  a panel that was reporting `logo=3` clears it. The display keeps working, so the unit
  looks fine, and then the next cold boot is **white from the first second of POST** and
  the panel's stored theme media is gone. A power cycle does not fix it; `recovery` does
  (the reset command: `xigmalcd-reset` once installed, `tools/reset_panel.py` in a
  checkout), and that is the vendor's own reset from ALPHA's "AIO Theme"
  screen, reproduced byte for byte from its log. `Link` refuses all three topics plus
  `recovery`, `config`, `firmware`, `update` and `upgrade` unless explicitly built with
  `allow_destructive=True`, and `send_media()` only ever sends `type:"media"` — a `.zip`
  upload is the firmware update path and is not in this code.
* Only one process can hold the port. If the unit fails to start:
  `fuser /dev/ttyACM0`, then `fuser -k`.
* The panel blanks the display 60 s after the last request (`timeout`); any framed
  request counts as activity, and the frame loop keeps it awake on its own.
  `--no-sleep` sets `timeout` to 0. `power {"event":"resume"}` wakes it and moves
  `brightness` 0 → 100; the vendor's other events are `suspend`, `resume`, `on-ac`,
  `on-battery`, `shutdown`, `lock-screen`, `unlock-screen` (this firmware answers
  `lock-screen`, `unlock-screen` and `resume`, and gives `400` to `on-ac`).
* A serial error re-opens the port and re-handshakes, so a suspend/resume or a USB
  re-enumeration recovers by itself.
* The panel goes quiet on long sessions: it stops sending any bytes at all, after
  ~522 uploads at 1 fps or ~370 s at 2 fps. Only closing and re-opening the port
  revives it — a second `conn` on the same handle and a DTR pulse both do nothing.
  `xigmalcd` renews the session itself every 500 uploads or 300 s; see PROTOCOL.md §9
  and `tools/session_limit.py`, which measures this and tests the candidate cures.
  With that in place a 20-minute run at 1 fps delivered **1174/1174 frames with no
  refusals**, renewing four times — 2.3× past the point where the earlier runs died.
  (That count predates the notice check below, so it says the panel stayed reachable,
  not that it took every file; the same limits are being re-measured with real verdicts.)
* `1 400` as the file notice means **the panel did not take the file**, and
  `send_media()` raises instead of calling that success. Reading that notice is the
  only reliable check: `transported` answers `{"state":"success"}` even for a refused
  file, and `space` does not move for accepted uploads either.
* Uploads are **timing sensitive**, and this is the part that cost the most time. The
  whole exchange — `POST transport`, the raw file, `POST transported` — has to go out as
  one burst, and the first file byte must land at least ~20 ms after the announcement.
  Waiting for the `{"state":"success","blockMaxSize":1024}` ack first, which is the
  natural thing to do, pushes the file past that window and every file gets `1 400`; a
  `ContentLength` header left out of the `transport` frame is quieter and worse — the
  panel answers nothing at all. And **somebody has to be reading the port**: with nobody
  reading, the panel's file notice is delivered a constant ~1.02 s after the upload no
  matter how the file was sent, which drags a whole-second cadence onto every frame even
  when the notice is not awaited. `Link.start_pump()` keeps a reader pending; stamped on
  arrival, the same notice lands ~30 ms after `transport` (`tools/hotpath.py`,
  `tools/writebench.py` - and the pump has to be woken by the byte, not polled at 200 ms,
  to see that).
  Verified with ALPHA's own payloads pulled out of the Windows capture
  (`tools/vendor_capture.py`: 65/65 extracted, all 480×480 8-bit RGBA PNGs): burst →
  `1 200`, ack-first → `1 400`, same bytes. Baud rate, DTR/RTS, chunk size, payload
  content, file-name patterns and power/theme state were each swept live and changed
  nothing.
* **Fan readings come from the motherboard, and `alpha` shows only what it can really read.**
  The vendor app gets RPM from the machine, never from the panel. Its Windows logs name the chip
  outright - `MSI X870 GAMING PLUS WIFI (MS-7E47) (Nuvoton NCT6687D)`, with `Fan CPU`
  1016-2448 RPM and `Fan System 5` 1529-1582 RPM - and 34 of its `STATE all 1` bodies carry
  those readings **down** to the panel as
  `"fans":[{"onBoard":true,"type":"Fan","name":"Fan CPU","value":2051}, ...]`. Nothing fan-shaped
  ever travels back up, and no pump value appears anywhere in the logs; the panel's
  `attribute:["Status","Fan","Pump"]` is a capability list, not a source (PROTOCOL §8). So a
  CPU-fan field on this glass is a **host sensor** question, and under Linux it is answered by
  `sudo modprobe nct6683` - that binds this board's chip as hwmon `nct6687`, which publishes ten
  tach inputs, four PWMs and **no `fan*_label` at all**, so nothing says which channel is the
  cooler. That was settled by measurement: over 12 s idle / 45 s all-thread load / 25 s cooldown,
  `fan1` went 1360-2371 RPM tracking `pwm1` (121-236) and Tctl (48-79 °C) while `fan12` sat at
  1538-1577 and never moved. Those spans match the vendor's Windows pair, so the channels are
  pinned under the vendor's names in `sensors.py` `FAN_CHANNELS`, and the glass draws two
  figures out of them: `CPU FAN 1957 RPM` under the CPU temperature, `GPU FAN 34%` under the GPU
  one. Reproduce it with `tools/fanscan.py --watch 90`; it is
  passive (reads sysfs, never writes a PWM), so warm the CPU while it runs. Any channel that is
  **not** pinned renders as the neutral `FAN nnnn RPM` rather than a guess, and with no tach at
  all the slot still shows `CPU FAN -- RPM` instead of going quiet and looking like the cooler
  stopped. The GPU half is a percentage: `nvidia-smi`'s `fan.speed`, labelled `%` because NVML's
  `nvmlDeviceGetFanSpeedRPM` exists in this 580.178.04 driver but refuses with "Argument version
  mismatch", and a card that reports no fan at all reads `GPU FAN --` rather than claiming a
  stopped one. Each figure has a 200 px ink budget and the two share one size, taken from
  whichever is wider, never pushed below 16. Measured with our font at the anchors the theme
  draws at: `CPU FAN 2400 RPM` inks 192 px (x 28-220) at font 20 with ink y 250-265 - 29 px
  clear of `CPU USED`'s ink, which starts at y 294, and clear of its gauge ring's stroke, which
  is what `tools/selftest.sh` asserts rather than trusts. The other tachometers this board
  reports (`Fan System 5`, a pump on a box that has one) no longer get glass space - two
  figures, one per temperature - but they are still sent: everything `sensors.fans()` reads
  rides into the metrics blob, whose `fans` section
  is what the panel's advertised `Fan`/`Pump` pages are for - never observed rendering here, so
  treat it as intent; `--no-fans` leaves both the blob section and the two drawn figures out,
  and the panel copes with a blob that has no `fans` at all.
* **The `alpha` gauge rings: where the shape comes from, and what it costs.** Each temperature
  sits inside a 260° arc that opens at the bottom - the vendor skin's own shape and sweep,
  taken from its captured frames rather than invented, and at a radius chosen so two rings
  plus a 38 px gutter fit 480 px: centres x 124 and 356, cy 158, 97 px outer radius, 12 px
  stroke (so the two boxes are x 27-221 and x 259-453, y 61-255). Both halves of the reading
  are fitted *against the ring*, not chosen and then checked: `xigmalcd/render.py` `_fit_arc`
  samples ink along the box edges and keeps the largest size that stays clear of the stroke,
  which is why the label is 22 where the vendor's own 32 would sit on top of it, and why the
  values are 58 at two digits and 46 the moment either column reads three. That ratio is the
  vendor's too, in proportion rather than in pixels: in its captured frame the digits inside
  its ring ink 168 px wide and 52 px tall within a 109 px inner radius, ours ink 152 px by
  44.5 px within 85 px. The arc carries the temperature twice over - the fill's position along
  the 260°
  *and* its colour, green at 30 °C through amber at 62 to red at 100, clamped at both ends,
  with the unfilled part left as a translucent track (`A26_ARC_TRACK`) so the ring reads as a
  gauge even at 30 °C. A column with no reading draws **no arc at all**: `tools/selftest.sh`
  samples 161 points along the middle of the stroke and asserts 0 of them are painted.
  What it costs, offline: painted pixels go from 8.7 % (the vendor's own skin frame, 19 969 of
  230 400) to 17.7 % (40 806), the rings themselves being 12 786 of them; one `render.draw`
  goes from 9.0 ms to **12.2 ms** median; and the painting is graded, not binary - 29 700 of
  those 40 806 painted pixels sit at an alpha between 1 and 254, which is the track's
  translucency and the anti-aliasing. The indexed PNG goes from 9.2-9.8 KB to
  **12.1-13.6 KB**, and that is the file the daemon uploads now; at the time the wire numbers
  below were taken it did not, because `main._png` still kept the alpha exact over a
  transparent canvas and put full RGBA on the wire. What the rings cost there:
  **44 388-46 014 B per frame against 30 710-32 157 B for the same theme before the rings** -
  about +13 KB, **+44 %**, measured across two full windows in `data/glass/` (the 16:14:44 and
  18:01:09 runs, `gauge` frames unchanged in both as the control on the link). Both of those
  are RGBA-era numbers: the same theme on today's indexed default logs **12 322-13 372 B** a
  frame (`data/glass/2026-11-07-003217-encode-DEFAULT-indexed.txt`), and the rings' cost in
  that shape is the offline pair above rather than a measured window pair. At 3 fps with
  the rings the panel still refused nothing: **91 of 91** frames confirmed in a 30 s window at
  18:12:51 (`data/glass/2026-11-06-181251-fps3-alpha.txt`), frames 39 400-45 244 B, so the
  re-measured claim that "the panel takes 3 without refusing" now covers the ringed picture
  too. The eye's part, now that it has been done: the owner watched the ringed `alpha` on
  real glass for **120 s at 1 fps** (`--title "EYEBALL ALPHA"`, run in a terminal, so no log
  was kept and this is an account rather than a ledger line) and said **everything looked
  good**, with both fan figures showing real numbers and both arcs partly filled. So the
  layout is judged readable at the size it draws: 12 px stroke at 97 px radius, label 22 and
  value 58 inside the hole, fan figures at 20 under each ring, in the mid-range colours (the
  CPU was sitting at the amber crossover). What that window did **not** show are the extremes -
  no three-digit temperature, so the drop from value 58 to 46; nothing near the red end of the
  ramp; no missing reading, so no `--°C` with no arc. Those three are judged now, on pinned
  numbers (`--metrics-file`, the note below it, and the four `pin-*` windows in `data/glass/`):
  the red arc **"read fine"**, a three-digit `104` inside the ring **"read fine, nothing
  wrong"**, and the empty column **"read correctly"** as no reading rather than as a broken
  gauge. The older sighting (60 s at 5 fps,
  300/300 frames, 2026-11-06) belongs to the earlier single-line fan layout and does not
  vouch for this one.
* **Pinning the numbers to put a case on glass: `--metrics-file`.** Some layouts only arrive
  with numbers the machine will not produce - the far end of the gauge ramp, a three-digit
  temperature, a sensor that is not there. The flag draws the picture from the sections of a
  JSON `STATE all 1` body instead, re-read whenever that file changes, and it is the picture
  **only**: while anything is pinned the loop sends **no metrics blob at all**, `--state-every`
  is refused out loud, and the session-start line says so ("`metrics: PINNED from
  --metrics-file, so no 'STATE all 1' blob is sent at all`"), because the alternative is a
  panel - and later a log - holding readings that were never taken. A key starting with `_` is
  a comment in the file, not a section; a file that stops parsing logs one line and keeps the
  last good read rather than stopping the loop, and a fresh process with a broken file falls
  back to the real sensors rather than resurrecting the old fake. Three fixtures are kept in
  `tools/metrics/` (`pin-104.json`, `pin-96.json`, `pin-no-cpu-temp.json`); `tools/selftest.sh`
  checks the offline half of the promise - pinned, the same upload call sends **0** metrics
  blobs where unpinned it sends **1**; the pinned 104 frame fills the whole 260° of arc
  (**1 298** samples along the stroke's middle) and its outer colour `(255, 66, 64)` matches the
  ramp's own hot tip `(255, 64, 64)`; a section with no temperature paints **0** samples.
  What it costs on the wire, all of it with nothing refused: the filled red arc is
  **14 253-14 439 B** a frame at 104 °C (`data/glass/2026-11-07-005051-pin-104-3digit.txt`,
  **46 of 46**) and **14 528-14 557 B** at 96 °C
  (`data/glass/2026-11-07-005142-pin-96-red.txt`, **46 of 46**) against the mid-range
  **12 322-13 372 B**, and the column with no arc is **11 261-11 398 B**
  (`data/glass/2026-11-07-005233-pin-nocputemp.txt`, **46 of 46**). So the ramp's whole length
  costs about **+2 KB** a frame and a missing reading saves about **-1 KB**. The digits were
  missed in the first window and looked at again in a longer one: `PINNED 104C, WATCH DIGITS`
  at 00:55:52, **76 of 76** frames at **14 618-14 751 B**
  (`data/glass/2026-11-07-005552-pin-104-3digit-watch2.txt`). Every one of those logs says in
  its own header that the numbers were pinned rather than measured, and none of them pushed a
  blob.
  To repeat any of it:

  ```bash
  python3 -m xigmalcd --theme alpha --fps 1 --duration 75 --no-mp4 \
      --title "PINNED 104C, WATCH DIGITS" --metrics-file tools/metrics/pin-104.json \
      2>&1 | tee data/glass/$(date +%F-%H%M%S)-pin-104-3digit.txt
  ```
* **Two owners of the port, and the one file they now send.** `xigmalcd` - the daemon and the
  plain loop - used to encode over a transparent canvas as 32-bit RGBA (about **40.8 KB** for one
  ringed `alpha` frame offline, 42-46 KB on the glass), while the window's direct-port path
  handed the same picture to `render.to_png` and uploaded the indexed file (about **12.2 KB**)
  whatever the canvas: the always-on loop wrote **3.4x** what the window did for one screen, and
  that was an accident of which module was calling. It is closed: `main._png` now uses the
  256-colour PNG on every canvas and `--truecolor` is how the exact RGBA file goes back on the
  wire, so the daemon, the plain loop and `xigmaui/panel.py` all send the same file. The reason
  is a glass comparison rather than a size argument. The same frame went up both ways twice:
  2026-11-06 at 20:17:08 / 20:18:13 / 20:19:17 is wire and acceptance evidence only (**61 of
  61**, **61 of 61**, **31 of 31**; 42 585-45 040 B against 12 342-13 699 B, nobody recorded as
  watching), and 2026-11-07 at 00:24:34 / 00:25:40 / 00:26:46 was watched, with the encoder in
  each window's on-screen heading, and the owner's verdict was **"no difference I could see"**
  (**61 of 61**, **61 of 61**, **31 of 31**; 42 560-46 415 B against 12 169-12 401 B). What the
  indexed file does give up, printed by `tools/selftest.sh` on every run so it cannot go stale:
  it keeps a graded alpha, and the half-transparent gauge track - 4 029 pixels at alpha 150 -
  comes back within 11/255, but PIL's octree quantiser treats RGBA as one four-channel colour,
  so of 11 149 pixels drawn fully opaque only **74** still carry alpha 255, and the gauge ramp,
  drawn in 80 colours along its fill, comes back in **13**, one flat colour every ~12 px of arc.
  None of that read at the 45-49 °C those windows ran at, which is the mid-range case. The
  extremes have since been put on glass too, on pinned numbers rather than on wishful ones
  (`--metrics-file`, the note above), and the indexed file held there as well: the filled red
  arc "read fine", at **14 528-14 557 B** a frame against the mid-range **12 169-12 401 B**.
  Had it shown the banding there, the answer would have been `--truecolor` rather than an
  argument - and for anyone whose panel does show it, that is still the answer.
* **Where the defaults come from.** `alpha` is not a guess: it is the theme the vendor app on
  this machine currently has selected, read from `%APPDATA%/alpha/store.json` -
  `currentThemeId 1785506775818` is entry 26 of that file's `presetTheme` list (eight
  widgets: big CPU temperature, CPU and GPU usage with bars, and no GPU-temperature, clock or
  fan widget), and every coordinate and colour in `theme_alpha` is taken from the `property`
  records in that entry. As of 2026-11-07 that entry can be named exactly: pairing the store's
  27 `presetTheme` entries with the vendor's 27 shipped `.thm` files by exact widget properties
  gives **27 of 27 one-to-one**, and entry 26 is theme `1757491589871`
  (`themes/alpha/layouts/480X480/1757491589871.json`) - the store re-ids the library at install
  time, which is why the ids looked unrelated. The background default follows the same rule -
  reproduce what the vendor app has, rather than a better-looking picture chosen here:
  `currentThemeBg` names `Theme_25.mp4` for that theme, and it is vendored byte-identical under
  `media/`. (That pairing is the app's own doing, not a mistake here: theme `1757491589871`
  ships with `theme_50.mp4`, and the app has `changeThemeBgBySn` for replacing a theme's
  background on its own.) Decoding
  all 40 clips in the vendor's `Program Files/ALPHA/resources/static/media` and measuring
  brightness, black frames and the loop join did show this clip is not the technically best
  choice - `Theme_11.mp4` (3.40 MB, 15.1 s, luma 13.3-24.1, 0 black frames, seam 0.11 vs
  2.54) is the one that stays invisible behind white glyphs - so both alternatives are
  vendored too: `--mp4 media/Theme_11.mp4` for the quiet loop, `--mp4 media/theme_48.mp4`
  for the vendor's brightest (luma 227.3, which is why `--scrim` exists). Matching the
  vendor's pairing is the deliverable, so that is the default and the measured weaknesses of
  it (a join of 2.50 against 1.51, i.e. a small jump once per second) are stated rather than
  fixed. The renderer bundles in `Program Files/ALPHA/resources/app.asar` are plain
  JavaScript, so that vocabulary and the widget types (`text-node`, `number-text-node`,
  `doughnut-node`, `process-bar-node`, `chart-node`) are readable without decompiling
  anything; only `out/main/index.jsc` needs the V8 route in PROTOCOL.md §10. And since
  2026-11-07 the themes themselves are readable too, keys and all - the whole library is in
  `themes/alpha/`, see that directory's README. Re-derive it
  any time with `python3 tools/theme.py` and `python3 tools/vendor_log.py`.
* **`pip install .` carries no clips, and that is a hole rather than a design.** The three
  MP4s this repo vendors live in `media/`, which is not a Python package, and
  `pyproject.toml` declares no package data for them — so an installed `xigmalcd` finds them
  only where the roots say (`$XIGMA_MEDIA`, a checkout's `media/`,
  `/usr/share/xigmalcd/media`: `xigmalcd/main.py:media_roots`), and a pip install into a
  system Python has none of those - though `find_media`'s fallbacks can still land on a
  copy under `/media/windows-c/...` when that volume is mounted, which is what an
  unpacked copy of the .deb did on this bench a minute before this sentence was written.
  What the loop does when nothing answers is say so, once per session:
  `_upload_background`'s `except OSError` prints `  ! background <path>: [Errno 2] No such
  file or directory: ...` to stderr, with `<path>` the `media` one level above the package
  as `media_dir()` spells it - `..` and all, so an install into this distro's system Python
  reports `/usr/local/lib/python3.14/dist-packages/xigmalcd/../media/Theme_25.mp4` rather
  than a directory it never looked in. The loop then keeps drawing frames over whatever the
  panel already has stored: a background it cannot read does not block the frames.
  The two supported
  answers are `apt install` of the `.deb`,
  which puts all three in `/usr/share/xigmalcd/media` ([packaging.md](packaging.md)), or point
  `XIGMA_MEDIA` at a directory of clips from the unit's own environment. `--no-mp4` skips the
  question entirely.
* **Version control: local `git` since 2026-11-06, published 2026-11-07** as
  `tamer-hassan/xigmatek-connect-lcd`, public, `main` only. Tracked: the three vendored
  clips in `media/`, the vendor's theme library in `themes/alpha/` (145 MB: 27 `.thm`
  originals as shipped, 27 decrypted layouts, 44 clips, 27 baked overlay PNGs, and a
  `manifest.json` whose 152 entries hash the 125 distinct files they name — 127 files on
  disk, the other two being that manifest and this directory's own `README.md`, and the 27
  `background` entries naming the same bytes as 27 of the clips), the theme contact sheets
  in `docs/previews/`,
  the project mark and the files generated from it (`install/artwork/xigma-penguin.jpg`,
  `install/xigmaui.png`, `install/xigmaui.ico`, `docs/logo.png`), and the three
  pinned-number fixtures in `tools/metrics/`. Not tracked, and said so in `.gitignore`:
  **everything under `data/`** — the two Windows serial-monitor sessions (37 MB of text,
  plus the `.spm` binaries of the same sessions, which only the Windows monitoring tool
  opens), the logs of every window run made against the real panel in `data/glass/`, and the
  65 vendor `.osd` payloads under `data/vendor_frames/` that `tools/vendor_capture.py` takes
  back out of the captures — plus the usual python noise.  What keeps them out is this
  panel's own serial number, which the captures and the logs both carry: blanking it by
  editing a log would be tampering with the evidence rather than redacting it, so those files
  stay on the bench and the serial is redacted wherever prose quotes one of their fields.
  **What that costs, said plainly:** a clone cannot re-run `tools/verify_protocol.py`,
  `tools/theme_check.py --arc`, or the two `tools/selftest.sh` sections that call them.
  Every wall-clock, byte-count and pixel figure in this README and in `PROTOCOL.md` names the
  bench file it was read out of, so that the run can be **repeated** rather than trusted — not
  so that it can be read here.  Those tools, and both selftest sections, print that they
  skipped instead of reporting a pass.
