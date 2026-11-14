# Notes and known limits

What has been measured on glass, by whom, with how many frames - and what has not. Every
  number here names the run it came from; the gaps are named too.

## What the panel answers, with the panel attached

* **A chosen text colour reaches the upload, not the panel, and it survives the palette
  encoding.** `--text-color` and the window's `text colour` row change the ink of the
  glyphs this program draws; the frame is then uploaded as pixels, which is the only
  reason the option exists on a device that answers nothing (§11). Measured off-glass by
  `tests/test_ink.py`: painting `gauge` in red leaves its painted area at exactly 6 087
  px as with the theme's own white, moves 1 509 solid white glyph pixels to 1 830 red
  ones with none left white, and holds for all six themes; and after the default
  256-colour palette encoding (§12) the ink returns within **1/255 per channel**.

  And on glass, 2026-11-07 at 10:20-10:22
  (`data/glass/2026-11-07-102041-ink-on-glass-watch.txt`): five inks sent over the control
  socket to a display running from this tree at 1 fps - the theme's own white, `amber`
  `#ffc400`, the off-palette `#8a2be2`, `red` `#ff4040`, `mint` `#00fae8` - held 15 s each,
  **80 frames, 0 refused, 0 link errors**, and `space` reading **67124 at every sample,
  before and after**: an ink changes the pixels of a frame that was going to be uploaded
  anyway, so it costs the panel no room at all. The author watched the panel through the
  run and reports every change on the lettering about a second after its command - the
  next frame, at that fps - and the colours reading as the colours sent, `#8a2be2`
  included. That last one is the interesting case: it is not one of this program's palette
  names, so the only thing between it and the glass was the loop's default 256-colour PNG
  encoding, whose drift `tests/test_encoder.py` measures at 1/255 per channel and the eye agreed with.
  One session renewal landed inside the run and the reported colour never drifted from
  what was sent - it is a setting the frame loop re-reads, not session state.
  Still unmeasured on glass: a **dark** ink over a **bright** clip (the automatic scrim
  rule is measured for white glyphs, and mixing the two would be inventing a threshold),
  and the two bench tools' own Apply/upload phases have not been re-run with the colour
  command in them (`tools/display_glass.py` and `tools/gui_glass.py --text-color` both
  send it now, and this run was driven over the socket by hand instead). A vendor theme's lettering is outside all of this: its
  colour is inside its own files (docs/themes.md).
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
  daemon's canvas is transparent by default now; `--bg black` fills that canvas with opaque
  black, which for a layout theme means the frame covers the background layer completely -
  and for four of our six drawn themes does not, because their own translucent fills are
  replaced rather than blended and keep the stored background visible (the `--bg` row in
  docs/usage.md, and `tests/test_conventions.py` derives which themes from the exports' colour keys). `--mp4 [PATH]` uploads a background the way
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
## Refusals, and what the unattended run left unexplained

* **Seven refusals in fifty-six unattended minutes, and no explanation for them.** The
  packaged unit, left drawing `alpha` at 2 fps after the 0.2 upgrade, logged
  `! frame 1029 / 1097 / 1167 / 2268 / 3162 / 3266 / 6471: device refused the file: 400 b''` -
  seven `1 400` notices on ordinary frames inside 56 minutes, in which the same process
  made **6 694** uploads with `6 687 confirmed` and 0 link errors, `NRestarts=0`
  (`data/glass/2026-11-07-072155-service-2fps-journal.log`). What makes them worth
  writing down is what they are *not*. Every other `400` in this tree's logs is a
  background `.mp4` the panel declined, in a window where a client had deliberately asked
  for an upload (the four cases in the GUI ledger). Here nothing asked - it was the loop's
  own frame, and the frame after each one landed normally. The three background picks the
  author made in `xigmaui` at 07:30-07:33, which was the first explanation offered for
  these, are ruled out by the record: a request that reaches this process leaves a
  `queued upload: <path>` ring note *and* a `background <name> …` journal line, and
  neither appears anywhere between 07:21:58 and 07:51:50, while the two that really did
  arrive are at 07:51:51 and 07:54:09 and both read `notice 200`. The two paths print
  differently too: the loop says `! frame N: device refused the file`, a refused clip says
  `background <name> refused (…); retrying once` (`xigmalcd/main.py:_upload_background`).
  The same `400 b''` did appear at 07:21:57 for the background at session start and was
  accepted 2.3 s after the retry, so the answer is at least transient rather than fatal.
  Not established, and the shape keeps moving: the first three sat 16-85 s *after* a
  renewal, while the seventh (frame 6471, 08:16:09) came 2 min 40 s after the sixth and
  18 s *before* one, so "just after a renewal" was already the wrong model. Candidates
  left untested: a renewal in flight racing the upload, a panel refusing an `.osd` file
  that arrives while it is still committing the previous one, and a rate that has always
  been present at 1 fps too and never reached a count anyone was watching. What would
  settle it is the run that has only half happened: the packaged path with `-v`, both
  directions logged, and `tools/display_glass.py`'s phases driven over a **unit-started**
  display rather than a hand-started one. Two socket uploads have since been carried by
  that unit, which is the first time this project's packaged path has done an upload at
  all - but the frames of that window were never byte-logged, so what happened inside
  them is still only counters and notices.
* **The service path has been observed, and only lightly driven.** Everything in the GUI
  ledger's always-on column was produced by `tools/display_glass.py` driving a
  hand-started display, so it has per-frame byte sizes, phase checks and a client. The
  packaged unit - the thing a person who ran `apt install` actually gets - has now been
  watched for 56 unattended minutes (counters, renewals, cost, journal) and asked for two
  backgrounds over its socket, both accepted. It has never been run through the driver's
  phases: pause and resume across a session TTL, a replug, the per-frame byte log, the
  refusal storm. A soak of an installed system at 2 fps, with the phases and the byte
  log, is still unclaimed.
* **Whether the panel shows a still image as its background is unverified.** Its file
  channel takes one: a 3 409 B PNG out of the vendor's own library went up over the
  packaged unit's socket and came back `notice 200 in 0.3 s` at 07:54:09, and a
  1 211 106 B MP4 from the same package in 1.0 s at 07:51:51. What the glass then looked
  like is the part no log here can supply, because the panel has no readback (§11) and
  nobody at the desk was asked. So `xigmaui` offers MP4 rows only, and the package's 28
  images stay out of the picker until that observation has been made.
* **Three of the vendor's own backgrounds are not the panel's size, and what the panel
  does with them is unmeasured.** ffprobe over the installed library:
  `/usr/share/xigmalcd/themes/alpha/clips/` holds 43 clips, **40 at 480×480** and **3 at
  320×240** (`2024-05-30_13-43-24-476.mp4`, `2024-05-30_14-09-30-913.mp4`,
  `2024-05-31_15-01-03-396.mp4`); the three clips this repository vendors are all
  480×480. So the vendor's own app ships files that are not the glass's resolution -
  which means the panel, or that app, scales them somewhere - but there is no readback
  (§11) and nobody has looked at the glass with one of those three stored, so this
  project states the numbers instead of the effect: `xigmaui` puts the measured size on
  every clip row and, for a file that is not 480×480, says under the list that its
  preview is a guess.
## The themes package: media and reference material, not a theme list

* **The themes package is media and reference material, not a theme list.**
  `xigmatek-connect-lcd-themes` installs the vendor's own 100 files - 27 layouts, 27
  background and 27 foreground images, 43 clips, a manifest and a README - under
  `/usr/share/xigmalcd/themes/alpha/`, every manifest entry re-hashed by
  `debian/tests/smoke` (125 entries over 98 distinct paths, because each theme's
  `background` record names the same bytes as one of the clips).
   **Reading it back is part of that test now:** on a system with the package installed,
   `debian/tests/smoke` runs `themes.scan()` and paints all 23 selectable layouts with one
   pinned dict at one pinned instant - **114 widget boxes** on this bench, **113** on a GitHub
   runner, and the one-box difference is a face: the runner lacks `simsun/20`, so one widget
   is font-skipped there and the test prints that skip instead of pinning a count.  What the
   test holds on both machines is the accounting identity, per layout: painted plus
   source-skipped plus font-skipped equals the manifest's widget count.  9 layouts ask for
   `Pump Speed`, and the body that test paints them at - `fixtures.SESSION`, which carries no
   fan rows at all - leaves that name unanswered on any machine; on this bench's own live
   readings the same nine draw it, from a channel pinned as the pump (PROTOCOL.md §8).  No
   port is opened.  It also
   measures the lookup a pairing cannot work without: the themes package installs the clip
   every one of those 23 layouts names (`/usr/share/xigmalcd/themes/alpha/clips`), and
   since 0.4 the loop's own rule for turning a bare name into a file searches that library
   too, so **all 23 resolve by name** - `--mp4 Theme_07.mp4` means the background that
   layout declares.  Before that change it
   resolved **2 of the 23**, because only the three clips the *main*
   package vendors were roots: `--theme Theme_07` drew the layout while `--mp4
   Theme_07.mp4` could not name the file sitting beside it in the package installed next
   door.  The media roots still come first, so the session default is `media/Theme_25.mp4`
   on every box; the installed test pins the 23 and
   `tests/test_media_roots.py` pins the order, with a planted name that both kinds of root
   hold.  The vendor's encrypted `.thm` containers are not in the package: they were in
   the 0.1 and 0.2 packages, and
   since 0.3 the manifest records them by vendor path, byte count and sha256 only.  The
  smoke test is what keeps that honest in both directions - it walks the installed tree
  and fails on any file the manifest does not name, so a `.thm` cannot sneak back into the
  .deb unnoticed. None of it is a theme this program can select: the window's theme
  picker lists `sorted(render.THEMES)`, the drawings this project renders, because
  nothing here has ever sent a `.thm` to the panel or read one back, and the control
  socket's own `check_media_file` gate does not accept that extension. What that library
  is used for here is measured: its layouts are what the `alpha` preset was redrawn from
  (docs/themes.md, `xigmalcd/layout.py`), and its clips are backgrounds that can be
  uploaded - all 43 of them sit under the socket gate's 8 MB ceiling, the largest being
  `clips/Theme_22.mp4` at 7 662 077 B.
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
## What the sensors report, and what the six drawn themes show

* **Which channel answers `Motherboard` is a selection rule, and it was selecting a network
   controller.** Measured on this box on 2026-11-13, before anything was changed:
   `sensors.motherboard()` returned **45-49 °C from `r8169`** - the Realtek NIC's die - because
   `temps()` walked a flat list of chip prefixes and the code took the `max()` of everything it
   found.  The board's own sensors were in that list only as the DDR5 SPD hubs
   (`spd5118`, 41.0-48.2 °C); the Super-IO was **not in it at all**, although the same chip that
   supplies the tachometers publishes a thermal diode and three thermistors there
   (`Diode 0 (curr)` 40.5-44.5, `Thermistor 1` 44.0, `Thermistor 15` 48.5-49.0) - and its
   hottest channel is `AMD TSI Addr 98h` at **62-70 °C**, which is the CPU read by the
   Super-IO, so adding that chip naively would have made the row worse in a different direction.
   The rule now walks **three tiers**, first one that answers wins - **Super-IO → DDR5 SPD
   thermistors → on-board silicon that is not the board's sensor set, as a last resort** -
   and inside whichever tier answers, **a channel the driver labels a diode beats that tier's
   hottest candidate.**  That preference is the owner's ruling of 2026-11-13, not a
   measurement's conclusion: the BIOS and the `/etc/sensors.d` file written against this board
   both call `Diode 0 (curr)` "Motherboard", so the row follows what the machine labels
   rather than the maximum it could find.  Read in one breath, twice: diode **41.5** against
   thermistors **43.0** (the row prints 42 where the maximum printed 43), and **42.5** against
   **46.5** forty minutes later (43 against 47) - so the cost of agreeing with the board is
   one to four degrees, and it is paid deliberately.  A chip that publishes no diode-labelled
   channel - the SPD hubs, most Super-IOs under a driver that leaves `tempN_label` unset -
   still falls back to that tier's hottest candidate.
   Two guards keep candidates honest, and they catch different mistakes.  **A label filter**
   (`TSI|Tctl|Tccd|CPU|GPU|edge|hotspot`) drops a channel whose own driver label names a
   processor or a card: `nct6683` publishes no `fan*_label` at all, but it does label its
   temperatures, and that label is the only thing separating the Super-IO's read of the CPU's
   TSI (60-70 °C) from its diode and thermistors.  **A membership filter** skips whole chips by
   name (`k10temp`, `amdgpu`, `nvme`, `ath12k_hwmon`, `drivetemp`, `aacs`) whatever their
   number says, because an NVMe composite and a Wi-Fi module die both publish a channel
   labelled plain `temp1`/`Composite` that the label filter would happily accept the day a
   tier named them.
   The bottom tier grew on the owner's ruling of 2026-11-14: `prom21_xhci`, the X870's
   Promontory hub die, soldered to this board, joins `r8169` there - on the argument that a
   chipset hub is a better stand-in for "the board" than a network controller when nothing
   better exists.  **On this machine that changes nothing**: the diode wins tier 1 either way
   (measured map of this boot: 22 temperature channels across 8 chips - Super-IO 38.5-39.5
   plus a 60.0 TSI, SPD 36.8-38.2, `r8169` 43.5, `prom21_xhci` 49.2-50.1, `ath12k_hwmon`
   42.0, `amdgpu` 42.0, `k10temp` 42.1-60.9, `nvme` 28.9-67.8).  The hub die answers only on a
   box with neither a Super-IO diode nor an SPD hub, which is a machine this project has not
   seen; and `ath12k_hwmon` was put in **no** tier by the same ruling, because a Wi-Fi module
   on a socket is a card in every sense the row is meant to exclude, and nothing measured here
   could tell it apart from an add-in card's die.
   Under the first version of the rule this box answered **45-50 °C from `r8169`**; the row is
   now cooler than that and, more to the point, named.  The vendor's own captured body agrees
   with the shape the tiers reproduce and the NIC never did - `motherboard:{"temperature":38}`
   printed beside `cpu:{"temperature":57}`.  `tools/fanscan.py` prints all three tiers, the
   channel that won with its driver label, the guards that were applied, and every chip the
   walk found that the membership rule refused - which is the command to run before believing
   any figure in this bullet, because every number here belongs to this bench.
   `tools/fanscan.py` prints all three tiers, names the channel that won, and says which labels
   were refused; `tests/test_sensor_rules.py` gates the rule on a **built** tree (a runner has
   no NCT6687D), including the two faults this replaces: a flat max, and the NIC in the first
   tier.
* **`disk.temperature` was reporting the wrong drive, because it was reporting the coolest
   number on the machine.** `sensors.disk()` describes one drive with `total` and `used` -
   `shutil.disk_usage("/")`, which on this box is `nvme0n1p6`, a Kingston SNV3S2000G - while
   its temperature came from `min()` over **every** `temp*_input` of **every** disk chip: on
   2026-11-13 that was **31-33 °C**, the composite of `nvme1`, an MSI M461 that holds nothing
   the reader is being told about.  The rule is now: the drive the mount point names, and
   within that drive its **`Composite`** channel - the aggregate the drive declares about
   itself, which is what `sensors -j` and `smartctl` show - falling back to that drive's
   hottest sensor only when it publishes no Composite (an `nvme2`-shaped case in the built
   tree answers 55 °C that way), and to the **hottest** reading across all matched drives when
   the mount point cannot be read at all (an overlay, a mapper name, a btrfs pool).  Measured
   here: **46 °C from `nvme0`'s composite**, and the same drive carries raw probes at **61.9
   and 67.8 °C** that its own aggregate excludes - which is why the composite is the number
   printed and the NAND probe is not: quoting 68 as "the disk temperature" would attribute to
   the drive a reading the drive itself does not treat as its temperature, and the row has no
   room to say which is which.  A new `source` name, **`Disk Temperature`** (→ `disk.temperature`),
   is what lets a layout draw it at all: no shipped file asks for a disk reading - the
   **21** distinct `source` values across the 28 layouts (23 selectable files plus the 5
   generated exports; 41 names if the `content` literals are counted too, and that counting
   rule is spelled out in docs/theme-editor.md) include no storage metric whatsoever - so the
   name is ours, spelled like `CPU Temperature` and `Motherboard
   Temperature`, and `layout.FORMATS_MEASURED` stays at four, which is what
   `--list-themes` means when it says which shapes are this repo's choice.
 * **A GPU fan row that had a shape for four years and no source for one.**  The owner's
   report on 2026-11-14 was "bars is missing GPU Fan", and the reading was never missing:
   `sensors` has filled `gpu.fan` from `nvidia-smi --query-gpu=fan.speed` since the NVIDIA path
   went in, and the twelve recorded samples in `docs/videos/readings-2026-11-08.json` answer it
   at **34, 34, 34, 34, 35, 35, 35, 35, 34, 34, 34, 34 %**.  What was missing was the pairing:
   `layout.VENDOR_FORMAT` has carried a display shape for the vendor's own name
   `GPU Fans Speed` (its editor vocabulary, `gpuFansSpeed`, PROTOCOL.md §10) since 0.5, while
   `themes.SOURCES` had no entry under that name - so a theme asking the vendor's name for a
   GPU fan got **nothing at all**: no error, no skipped-row note, just a row that was never
   there.  `tests/test_bars_rows.py` now gates that direction (`test_no_display_shape_waits_
   without_a_source`), which is the class the previous gate only covered one way.
   **The unit is duty percent, not RPM**, and that is a measurement rather than a preference
   (docs/limits.md's fan section, 2026-11-13): `nvmlDeviceGetFanSpeedRPM` exists in the
   580.178.04 driver installed here and refuses with `Argument version mismatch`, no GPU on this
   box publishes a tachometer - `nvidia` has no hwmon chip at all and this `amdgpu` publishes
   `freq1`/`in0`/`in1`/`power1`/`temp1` only, while the system's ten live `fan*_input` files all
   belong to `nct6687` - and PROTOCOL.md §10's own field table spells `gpu.fan` a percent.  So
   the row's meter is 0..100 like `LOAD`/`RAM`/`VRAM` and its number prints `34%`; putting it on
   the fan slots' 0..3000 track would have filled 1 % of the meter with a fan at a third of its
   range, which is the `15 GB`-at-97 % defect in a different row.  One shared spelling for both
   doors: `render.pct`, referenced by `layout.VENDOR_FORMAT` as `_pct` and called by
   `theme_bars` for `LOAD` and the fan row, replacing a `f"{v:.0f}%"` that agreed by
   coincidence.
   **The row cost a slot, and the arithmetic said so before the code did.** **Twelve** rows at a
   32 px pitch is the block's ceiling (the paragraph above: a thirteenth computes pitch 29, which
   the 2 px clearance rule refuses, and at twelve the last row's meter ink ends at y=442 with the
   clock's ink beginning at y=446 - 3 px of air).  Three placements were measured and put to the
   owner - trade a fan slot, keep the slots and thin the meter to 4 px at pitch 29, or pair the
   fan into the GPU row's number column; the owner chose the first, and it landed as three fan
   slots at twelve rows.
   **The same day the owner re-ordered the block**, and the row count came down to **eleven**:
   `Fan GPU` - relabelled from `GPU FAN`, to read like the rows it sits with - goes **under**
   `Fan CPU` and `CPU PUMP` rather than under the GPU temperature, and LOAD/RAM/VRAM go to the
   bottom.  That order leaves a third reserved fan slot as a blank row *between* two fan rows
   that both have readings on this box, and a hole you can see in the middle of a group is worse
   than a row this machine cannot fill: so `bars` reserves **two** fan slots
   (`themes.FAN_SLOTS[:2]`, `render.BARS_SLOTS` 4 -> 2) and the block draws eleven rows.  The
   ceiling is unchanged as a fact about the canvas; the theme chose to sit one row under it,
   which buys a **34 px pitch** (the clamp's own ceiling for this span is 56 px, so the pitch is
   the division, not a wish) and leaves the last row's meter ink at y=430, **15 px** clear of the
   clock's ink at y=446 - measured by `TheBlockStopsBeforeTheClock`, floor 2 px, printing the
   pitch and centre for ten, eleven, twelve and thirteen rows so the headroom is visible.
   What it costs, stated: a box with three or four tachometers shows only its first two fan rows
   under `bars`; the four `Fan N` name pairs stay answered in the vocabulary for layouts you
   write, and one check pins the two halves together (`len(BARS_FAN_ROWS) == render.BARS_SLOTS`)
   because a second copy of a slot count is how the doors drift - a mutation setting
   `BARS_SLOTS` back to 4 while the table draws two costs **36** failing checks.  What it buys on
   the glass is one number worth more than the row it gave up: with two slots drawn, **this
   machine answers every source `bars` asks for**, and the review door now says
   `skipped: nothing` where it used to name `Fan 3 Name, Fan 3 Speed` (and before that the
   `Fan 3`/`Fan 4` pair).  Row order, from the table: CPU, GPU, BOARD, the two drive slots, the
   two fan slots, `Fan GPU`, LOAD, RAM, VRAM - pinned in `tests/test_bars_rows.py` as a
   *drawn* pattern, `["Fan CPU", "CPU PUMP", "Fan GPU"]` read out of the painter with a body
   that names its fans the way this box names them, because a fan row placed by a table slice
   is a claim about arithmetic and the owner asked for a claim about the glass.
   Figures as re-printed after the move: `bars` is **35 widgets** at **15 497 characters**
   *(superseded within the hour by the gutter column below: **46 widgets**, **19 890
   characters**, parity at 74 125 / 72 814 / 16 283 / 21 558 / 11 086 — the figures kept
   through this bullet are the ones that were true when it was written, because the
   arithmetic in them is the arithmetic that decided the row order)*,
   parity 0 px and worst channel 0 at all five readings - **70 207 / 68 916 / 15 974 / 20 870 /
   11 086** lit px down each door - 69 131 px at the editor's pinned fixture with **35 of 35**
   widgets drawn and no missing source, 69 390 px on this machine's live readings, and 35 boxes /
   69 413 lit px through `--check-theme bars`.  The row census prints 147 `text`/`data` rows over
   28 layouts, 138 twins, **9** skipped, 28 caveats, and the only reason left is `Pump Speed` in
   nine vendored layouts; the source census 22 distinct `source` values, 15 asked only by a
   generated export; the snap census **188 / 92 / 46 / 369** with gaps
   {0: 92, 2: 12, 3: 4, 4: 14, 5: 4} and pulls at 11 / 12 / 57 %; ink moves **24** glyph roles of
   35 widgets.  Every one of those came out of a run rather than out of this page.
   Twenty-one mutations against this block now, nine of them about the fan row: the source
   pairing removed (the original defect) -> **21**; the row's scale moved to RPM in the table ->
   7; the same scale moved in the code door only -> 6; the file door's percent sign dropped ->
   13; the code door loses the row -> 33; the table loses it -> 33; the painter keeps four slots
   -> 36; the fan vocabulary shrinks with the block -> 2; `pct` loses its unit -> 6.  And one
   fault of mine in the new tests, recorded because it cost real debugging: the check that
   deleted `gpu.fan` to build an integrated-GPU body used `dict(ALL_SIX)`, a **shallow** copy,
   so it deleted the key out of the module-level body and two unrelated checks that run after it
   went blank - unittest orders classes alphabetically, so `TheGpuFanRow` came first.  Fixed
   with `copy.deepcopy`, plus `test_the_shared_bodies_are_still_whole_when_everything_else_ran`,
   which catches that shape of mistake whoever makes it.

 * **Gutter figures are drawn, not fonts and not assets** (2026-11-14, at the owner's
   request for icons in `bars`).  Three ways to put a small picture beside a row, two refused
   by measurement rather than taste.  An **icon font** (Font Awesome, a Nerd Font's codings,
   any private-use glyph) resolves against whatever face this machine has, and this project
   has already paid twice for face dependence: the vendor's `simsun` rows are *dropped* on a
   runner with no CJK face - nine widgets, and `tests/test_library_draw.py` reports the faces
   a machine cannot resolve rather than substituting - and the same `text` row measures
   different ink widths under Liberation Sans than under the Arial the vendor designed for
   (`tools/theme_check.py` measures that gap against the vendor's own baked PNG instead of
   trusting the metric-compatibility claim).  A figure that disappears with the font, or
   shifts a pixel with the host, breaks the rule this project holds highest: both doors paint
   identical pixels.  A **baked asset** - an SVG rasterised to a PNG - cannot be moved,
   resized or recoloured from a layout, puts a second copy of the theme's ink outside the
   palette rules, and has no widget kind to sit in: the overlay vocabulary is `text`, `data`,
   `bar`, `arc`, `line` and `special`, and none of them is an image.  So the figures are
   **polygons**: nine of them in `render.ICONS`, drawn on the same supersampled canvas as the
   meters, named from a layout through the `special` kind that already exists, and placed by a
   fourth door - `layout.draw_special_glyph` - joining `line`, `pair` and `values`.
   At **22 px** (1/22 of the glass) the design limit is legibility: one silhouette cue per
   figure, no second detail, because a second detail downsamples into mud.  What survives: a
   die with four-edge leads and a solid core (`chip4`, CPU), a plate with a bracket tab and a
   blower ring (`card`, GPU), a plate with socket, slots and mounting holes (`board`), an M.2
   body with its end notched as a step in the outline (`drive`, both storage rows), a stick
   with four chips and a keyed notch in the bottom edge (`dimm`, RAM), a two-edge package with
   a pin-1 dot (`chip2`, VRAM), a three-wedge rotor (`fan`), a volute ring with two vanes and a
   **tangential outlet** (`impeller`, the pump), and a 240-degree dial whose **needle is the
   row's own fraction** (`gauge`, LOAD: 3 % points low, 97 % points high).
   **Colour is a reading, not a style.**  Each figure is drawn in `heat(frac)` of its own row,
   through `layout.frac_of` - the same call the meter beside it fills with - so the two cannot
   disagree, which is the same defect class as the `15 GB`-at-97 % row one bullet below, in a
   different pair of halves.  A figure carries no `textColor` at all: choosing amber for the
   text must not make a cold die look cool, and a check in `tests/test_ink.py` refuses the key
   on an icon widget while the census adds up as 24 glyph roles + 11 meter tracks + 11 figures
   = 46 widgets.
   **The pump is chosen by what was measured, never by what a label spells.**
   `xigma.iconVariant: "Fan 2 Type"` names another of the row's readings; the table answers
   `Pump` because that channel is pinned by a tachometer that stays flat while its own header's
   duty sweeps (PROTOCOL.md §8); `render.ICON_VARIANTS` maps rotor + `Pump` -> volute.  Four
   source names joined the vocabulary to carry it - `Fan 1 Type` .. `Fan 4 Type`,
   `themes.source_names()` 38 -> 42 - each with a display shape, because a layout may want to
   *print* the type as well as draw by it.  The honesty check is driven at two bodies, because
   one was not enough: at `type: Pump` both doors draw the volute, and at a row **named**
   `CPU PUMP` that reports `type: Fan` both doors draw a rotor - the second case is where a
   label-sniffing implementation shows up, and it took a mutation (the door reading the label)
   to find that the check was only comparing the easy body.
   Two defects the first cut had, and the reason the gate measures ink instead of trusting
   boxes: a die's leads and a stick's ends were drawn **outside** the box they declare
   (double-scaled arithmetic put the CPU figure's ink at x=27.6 against a label column
   starting at x=28), and the whole-frame parity number stayed plausible while the two doors
   disagreed about which of them *won* that overlap - 1 720 px of grey against green.  So
   `tests/test_icons.py` measures every registered figure's ink against its box, and compares
   the doors **row by row in the gutter column**, because a frame-wide diff can be paid for by
   an offset in one place and still come out even.  Twelve mutations counted against the rule:
   leads outside the box -> 2; the notch double-scaled again -> 1; the row table giving CPU the
   GPU's figure -> 1; the export declaring no figure for a row -> 27; the door resolving the
   variant from the **label** -> 1; the variant table emptied -> 1; a fixed ink instead of the
   row's ramp -> 13; the dial's needle ignoring the reading -> 1; the geometry door asking for
   a font again -> 16; the recipe stop naming the variant source -> 5; the key's reason deleted
   -> 3; an unknown figure name drawing something anyway -> 1.
   Census, printed by `python3 -m unittest tests.test_icons`: 11 figure rows of 11,
   **2 717 lit px in the gutter** of 73 128 in the frame, both doors at 73 128 and 0 px
   differing; per-figure ink in device px `board 698, card 430, chip2 436, chip4 631,
   dimm 817, drive 397, fan 915, gauge 355, impeller 614`.  And one process lesson recorded
   here because it was found by hand rather than by a check: adding the fourth door left
   `--list-specials`'s caption table behind it, and the flag raised `KeyError: 'glyph'` -
   596 checks, all green.  A check now runs the flag and fails if any registered drawing
   lacks a caption, or if the print and the registry disagree about the count.

 * **The gigabyte rows were flooring, and the number disagreed with its own meter.**
   `bars` prints RAM and VRAM as a meter (the division) beside a number (one side of it), and the
   number's rule was `int(mb) // 1024`.  At this box's own GPU readings - 15 952 MB of 16 376 -
   that is **15.58 GiB**, so the meter stood at **97.4%** while the figure read `15 GB` on a 16 GB
   card: a nearly full card presented as having a gigabyte of headroom, in one row, at one
   instant.  Rounding to whole gigabytes is not better here, it prints `16 GB` equal to the card's
   total while the meter is at 97%.  So the spelling is one decimal - `15.6 GB` - from one
   function, `render.gb()`, which `layout.VENDOR_FORMAT` references for the file door and
   `theme_bars` calls for the code door; the two gigabyte rows now share it instead of each
   carrying its own lambda, and a row-string check in `tests/test_bars_rows.py` pins that.  The
   check holds the row's two halves to the same fraction (printed value against the card's total,
   within 0.01 of the meter) and asserts the floor rule *would* have disagreed by more than 0.03 -
   so the guard fails if someone decides a whole gigabyte looks tidier.  Width costs nothing
   measurable: the widest number in the block is `82.4 GB`, its ink begins at x=365 and the label
   column ends by x=133, leaving 230 px of air in the row.

 * **Four per-drive slots, on a section the panel was asked about and answered.**
   `sensors.drives()` publishes `drives[]` in the blob - one row per storage controller,
   `{name, temperature, sensors}` - and `themes.DISK_SLOTS` names them for layouts:
   `Disk 1 Temperature` … `Disk 4 Temperature` and `Disk 1 Name` … `Disk 4 Name`, indexed by
   **controller** (`nvme0` before `nvme2`), not by whatever number the kernel happened to give
   the hwmon directory.  Measured twice here on 2026-11-13, forty minutes apart: `nvme0` at
   **41 °C** with published sensors `[41, 52, 68]`, then at **45 °C** with `[45, 57, 68]`, and
   `nvme1` 31 °C then 33 °C - the drives warm while the box works, which is exactly why these
   are printed by `tools/fanscan.py` rather than quoted as a figure a reader has to trust.  So a
   layout can put the boot drive in slot 1 while the hotter raw probe stays visible in the row
   instead of being quietly dropped.  **`bars` draws two of them** as of 2026-11-14 -
   `Disk 1 Name`/`Disk 1 Temperature` and `Disk 2 Name`/`Disk 2 Temperature` - so the first two
   slots are on the glass under that theme, and slots 3 and 4 stay in the vocabulary for layouts
   you write.  No vendored file asks for any of these names: the source census that
   `python3 -m unittest tests.test_row_notes` prints counts **22 distinct `source` values across
   the 28 layouts**, none of them storage-shaped in a vendored file, and the four disk pairs our
   own generated `bars` asks for are among the 15 asked only by a generated export.
 * **The blob tolerates what the vendor never sent - asked directly three times on 2026-11-13.**
   One session, five `STATE all 1` bodies: the control in the vendor's shape; the control plus
   a fan row typed `"Pump"`; the control plus a new top-level `drives` key; both changes
   together; the control again.  Every one answered `<Message 1 200 {AckNumber, CkOK:True} b''>`,
   and the ordinary `.osd` frame uploaded afterwards was accepted, `space` and `osdState`/`mode`
   unchanged.  The run that stands is `data/glass/2026-11-13-223617-blob-probe.txt` - 11 668 B
   frame, and the `drives` payload was `sensors.drives()` itself rather than a hand-rolled
   Two earlier runs are kept in the same directory as the record of getting the payloads
   wrong.  `data/glass/2026-11-13-183954-blob-probe.txt` took its control straight from
   `sensors.collect()`, which on this box already reports the pinned pump channel, so
   control and experiment both carried the `Pump` value and that pair distinguished
   nothing - its `drives` experiment, by contrast, was a genuine new key that day,
   because `collect()` had no such section yet.  `data/glass/2026-11-13-184215-blob-probe.txt`
   fixed the Pump pairing but sent a `drives` payload the probe had assembled itself -
   `0.1` degrees, unsorted - rather than the `sensors.drives()` that shipped later the same
   evening, so what it certified was a near-miss of the body that goes out.  A third fault
   of the same family was caught before it ever reached the panel: once `collect()` grew
   the section, the tool's `base = dict(raw)` control carried the key too, and
   `tests/test_blob_probe.py` failed on exactly that.  In both flawed runs the acks printed
   were the same `200`s; the *question* was not the one claimed.
   What the experiment still cannot measure is whether the panel *reads* those fields: a
   `STATE` reply carries no body, `space` does not move for accepted uploads, and the only topic
   that would make the panel draw the numbers itself is `realtimeDisplay`, which ALPHA sends only
   to an `OS === "RTOS"` unit (PROTOCOL.md §5, §8).

* **`hwmon()` walked the device directories as text, so `hwmon10` came before `hwmon2`.** On
   this boot: nvme, nvme, ath12k, amdgpu, r8169, nct6687, prom21_xhci, k10temp, spd5118 ×4 -
   the Super-IO last-but-two because of a digit count.  Nothing on the glass depended on that
   yet (one chip publishes tachometers), but it decides which row becomes `Fan 1` the day a
   second one does, and a slot order a reader cannot predict is an order no page can describe.
   The walk is numeric now, and `tests/test_sensor_rules.py` asserts the property (every
   consecutive pair in ascending index) rather than this box's chip names.
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
  stopped.
  Re-measured on 2026-11-13 after the machine was re-wired, and a third channel appeared: the
  AIO's block cable on `PUMP_SYS1` came up as `fan2` at 2443-2469 RPM - spread 10 across 23
  rounds over 45 s with all 24 threads loaded, spread 5 across 15 rounds over 30 s at rest -
  **flat while its own header's duty swept**: `pwm2` matched `pwm1` 1:1 (raw 152-182 in paired
  samples, 204-231 in a later 12-round window) and the tach answered to none of it, which is how
  a pump tells itself apart from a fan on a board that gangs the two headers. The
  six case fans went to the cooler's own ARGB controller, which exposes no sensor interface to
  Linux at all (12 hwmon chips before and after), so `fan12` reads 0 today and keeps its pin for
  the next re-wiring. `FAN_CHANNELS` gained `("nct6687", "fan2") = ("CPU PUMP", "Pump")`, that
  pinned type is what `themes.FAN_TYPED` reads to answer `Pump Speed`, and `--watch` now prints
  the duty spans next to the tach spans because the pairing - not a name - is the evidence.
  The GPU half is a percentage: `nvidia-smi`'s `fan.speed`, labelled `%` because NVML's
  `nvmlDeviceGetFanSpeedRPM` exists in this 580.178.04 driver but refuses with "Argument version
  mismatch", and a card that reports no fan at all reads `GPU FAN --` rather than claiming a
  stopped one. Each figure has a 200 px ink budget and the two share one size, taken from
  whichever is wider, never pushed below 16. Measured with our font at the anchors the theme
  draws at: `CPU FAN 2400 RPM` inks 192 px (x 28-220) at font 20 with ink y 250-265 - 29 px
  clear of `CPU USED`'s ink, which starts at y 294, and clear of its gauge ring's stroke, which
  is what `tests/test_gauges.py` asserts rather than trusts. The other tachometers this board
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
  gauge even at 30 °C. A column with no reading draws **no arc at all**: `tests/test_gauges.py`
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
## Driving the loop from a file, and who owns the port

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
  `tools/metrics/` (`pin-104.json`, `pin-96.json`, `pin-no-cpu-temp.json`);
  `tests/test_pinned_metrics.py` checks the offline half of the promise - pinned, the same upload
  call sends **0** metrics
  blobs where unpinned it sends **1**; the pinned 104 frame fills the whole 260° of arc
  over 1 200 samples along the stroke's middle) and its outer colour matches the ramp's own
  hot tip within 12; a section with no temperature paints no samples at all.
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
  indexed file gives up is re-measured offline, one frame at a time, by
  `tests/test_encoder.py` - which asserts bounds, not these counts. The figures below are what
  one alpha-overlay frame gave when they were first counted, and they are a record of that
  measurement:
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
## The published previews, and the digits that come out of them

* **The README's previews are 10-12 s MP4s now, and their digits move.** Six files in
  `docs/videos/`: one per theme, plus the amber-ink figure [docs/gui.md](gui.md) carries.
  Each runs over a different clip from the vendor's library, at the panel's own 480 px and
  the clip's own frame rate, and each is driven by a recorded readings series rather than a
  frozen one - so the temperatures, loads, fan figures, meters and the on-glass clock all
  change while you watch. They are not GIFs because an `.mp4` written into markdown as an
  image becomes an `<img>` tag no browser plays (checked against GitHub's own markdown
  endpoint, not remembered), so a video has to go up through GitHub's editor, which
  rewrites the markdown to point at its CDN.  Until the upload happens, README holds a
  visible marker in each cell - backticked text naming the file to upload and telling whoever
  uploads to delete the marker afterwards - rather than an HTML comment, which would be
  invisible in the raw text they are editing.  The suite counts those slots: markers plus
  uploaded links have to add up to the number of previews the document promises, so a marker
  deleted with nothing put back is a hole it can see - and so is the shape that looks right
  and is dead, a relative `docs/videos/*.mp4` image link.  Two consequences worth writing
  down: nothing inside `docs/` can honestly say "the picture above", and the encoding
  settings are x264's (`crf 20`, `preset medium`) rather than a palette's.

  Every figure in this table was read out of the written files by the 0.6 offline suite, and
  came out identical across four runs on 2026-11-08 - two of them with the machine's own zone
  set to UTC, which is how the clock-zone bullet below was found. At 0.7 nothing re-derives
  this table: `ffprobe` over `docs/videos/*.mp4` recomputes any row of it, and the six rows are
  a record of that run rather than a claim a check holds up.

  | the file | frames | length | rate | bytes | clip → field luma | glyph − halo | moved over 3 s: drawn / untouched |
  |---|---|---|---|---|---|---|---|
  | `alpha-Theme_25.mp4` | 240 | 10.00 s | 24 fps | 908 420 | 17.1 → 15.5 (1.7) | 190.3 − 42.3 = **148.0** | 18.68 / 2.67 (×6.99) |
  | `gauge-3.mp4` | 240 | 12.00 s | 20 fps | 1 930 104 | 41.2 → 38.4 (2.8) | 201.5 − 89.8 = **111.7** | 16.09 / 5.44 (×2.96) |
  | `dual-Theme_30.mp4` | 240 | 10.00 s | 24 fps | 214 113 | 3.3 → 3.2 (0.1) | 176.7 − 38.5 = **138.2** | 17.11 / 0.45 (×37.89) |
  | `clock-Theme_07.mp4` | 240 | 10.00 s | 24 fps | 278 884 | 176.2 → 162.6 (13.6) | 241.0 − 106.4 = **134.6** | 10.63 / 1.59 (×6.69) |
  | `bars-theme_52.mp4` | 240 | 12.00 s | 20 fps | 859 706 | 11.9 → 9.5 (2.4) | 140.6 − 43.4 = **97.1** | 11.48 / 7.34 (×1.56) |
  | `birdseye-theme_47-trimmed.mp4` | 240 | 12.00 s | 20 fps | 1 223 967 | 6.3 → *(not measured)* | *(not measured)* | *(not measured)* |
  | `alpha-Theme_25-amber.mp4` | 240 | 10.00 s | 24 fps | 927 752 | *(the ink figure: see below)* | | |

  The `birdseye` row is the newest, and three of its columns are empty **on purpose**: the
  clip's own mean luma (6.3 of 255) and everything in its first five columns come from the
  render the tool printed (`tools/preview_gif.py --mp4 --no-gif --theme birdseye --clip
  media/theme_47-trimmed.mp4 --series docs/videos/readings-2026-11-08.json --gif-fps 20
  --frames 240 --out docs/videos/birdseye-theme_47-trimmed.mp4`, 1 223 967 B, 240 frames at
  20 fps = 12.00 s, `scrim 0` - the plate rule did not engage, which is the point of pairing
  a fourteen-reading panel with a ground measured dark rather than chosen for looks: the survey that
  chose it measured 44 clips and put `theme_47` at 6.6 luma with motion 5.62, and the cut
  copy reads 6.3).  What has not been measured for this file is the composited field luma,
  the glyph-minus-halo figure and the motion split, and an estimate in those cells would be
  worse than a gap.  The set is now **seven files, 6 342 946 B**, largest `gauge-3.mp4` at
  1 930 104 and smallest `dual-Theme_30.mp4` at 214 113.

  The `bars` row is the exception in that table, and it is labelled rather than quietly
  fixed: that clip was **re-rendered on 2026-11-12**, after the theme's row geometry moved
  (`BARS_BAR_DY` 17 to 12 px and `BARS_BAR_WH` 10 to 6 px tall: a row's text lays down 16
  ink rows and the old track 12, in a pitch of 32, which left 15 rows of air for a meter
  that needed them - see the row-clearance rule in `tests/test_bars_rows.py`), so its bytes
  are this render's (859 706, up from 779 905) and
  its luma and motion columns are still the 2026-11-08 render's. Re-making it is one command:
  `tools/preview_gif.py --mp4 --no-gif --theme bars --clip themes/alpha/clips/theme_52.mp4
  --series docs/videos/readings-2026-11-08.json --gif-fps 20 --frames 240 --out
  docs/videos/bars-theme_52.mp4`, and the tool prints the frames, the rate and the length
  back from the file it wrote.

  **5 118 979 B** for all six, the largest 1.93 MB, and 13 916 B of series JSON beside
  them - that file grew 220 B when it gained one field, the zone it was sampled in; see
  the clock-zone bullet below. Every file stays under 2 MB: GitHub's own browser upload
  limit is a thing of GitHub's and has not been measured here. The ceiling the deleted
  suite held every run was 9 MB per file, comfortably below where that limit is reported
  to be; nothing re-measures the published files now, so `du -b docs/videos/*` re-reads
  the sizes and this sentence names it as a gap rather than a gate (docs/tools.md).

  * **What the digits in them are.** One recorded series drives all six files:
    `docs/videos/readings-2026-11-08.json`, 12 `sensors.collect()` calls at a 1 s cadence
    (measured gaps 1.00-1.01 s, span 11.0 s), held one per displayed second of frames the
    way the panel holds one reading per poll. Everything in it that moved: CPU 68→74 °C,
    CPU load 57.7→94.6 %, GPU 48→51 °C, GPU load 99→100 %, CPU fan 1 540→2 181 RPM, memory
    84 469→85 389 MB, clock `00:25:16`→`00:25:28` with 12 distinct seconds. It is a busy
    machine and the JSON says so rather than hiding it: the sampler waited 90 s for the box
    to drop under 12 % load and it never did, because the session that made these previews
    runs its own model server at roughly 390 % of 24 cores, and the last 7 samples were
    taken with 7 parallel clip decodes running on purpose - the load rendering the videos
    puts on a machine. So the `gauge` ring, whose 30..75 °C scale is the vendor's own
    measured one, sits at 88.9 % travelled on the first sample and 97.8 % on the last.
    That is the box, not the drawing: PROTOCOL §8 measures this board's `fan1` at
    1 360-2 371 RPM and Tctl at 48-79 °C, and every reading is inside both.
  * **The motion gets asserted twice, on purpose.** Per file: two frames 3 s apart differ
    by at least 3/255 mean absolute change over the pixels the layer paints, and more than
    the untouched part of the frame does (the ratios above, 1.55 to 37.89 - the low one is
    `bars` over `theme_52.mp4`, which moves a great deal on its own). And the two layers the
    file was built from, re-rendered against each sample's readings *and each
    sample's clock*, differ at more than 8/255 on 622-6 226 pixels each. One of those
    checks without the other is worthless in a predictable direction: a frozen layer over a
    moving clip passes the file-level test on the background's own motion, and a video whose
    numbers never change still passes the layer test if the series was re-read per frame.
    The re-drawn layer check needs the clock patch: without it both calls printed the wall
    clock of that instant and the `clock` theme looked byte-identical (0.0) while the video
    it was scoring ticked away happily.
  * **A preview's background is checked, not assumed.** The mean luma of each file's
    untouched field (the pixels its theme never paints) is compared with the mean luma of
    the same clip's own first frame: gaps **1.7** (`Theme_25.mp4`), **2.8** (`3.mp4`),
    **0.1** (`Theme_30.mp4`), **13.6** (`Theme_07.mp4`, where the scrim plate's edge bleeds
    into what the mask counts as field) and **2.1** (`theme_52.mp4`). Bound 20; the nearest
    *wrong* pairing on this set is 60 away.
  * **Ink, measured where the layer painted that ink.** The amber figure's mask is the set
    of pixels the reference layer holds at exactly `#ffc400` - **2 268** of them, drawn from
    the sample's own readings *and its own clock*, so the arcs and rings (which keep their
    own colours, ink being about text) cannot inflate the number and the count of lettered
    pixels does not depend on the time of day the check runs. That pin was a fix, not a
    nicety: with the mask's clock left to `time.localtime()`, one unchanged file printed
    2 268 painted pixels in one run and 2 270 in the next, and the same leak moved the
    glyph-vs-halo figures by about a tenth. In the written MP4: 1 144 within 3/255, **2 187
    within 8/255**, 81 still at the exact value, median 3/255, mean 4.3, and 19 pixels beyond
    16/255 (worst 227) where a hairline stroke over a moving picture meets half-resolution
    chroma. The GIF path asks a different question - the closest colour *present anywhere in*
    a 160 px / 6-frame / 128-colour GIF written in the same run is **(252, 197, 2)**, 3/255
    off - and neither stands in for the other, or for the 256-colour PNG the upload path
    sends (§10, 1/255 per channel).

  * **What GitHub writes for a video, and what it then serves.** Both halves of that were
    learned by getting one wrong first.  **The shape:** GitHub's editor writes an *image* as
    `![alt](https://github.com/user-attachments/assets/…)` and a *video* as that URL alone on
    the line, no `!`, no brackets - the renderer turns the bare autolink into an inline
    player.  The suite's slot count only knew the image form, so the commit that finished the
    upload came back `0 markers + 0 uploads for 5 previews` and failed the run (9b0cfa7, CI
    42427101692).  The counting rule was right and its pattern was not; both forms match now,
    which is why an uploaded README and a marker-bearing one can both pass while an empty
    cell cannot.  **The bytes:** the six URLs README and docs/gui.md hold were fetched with
    `curl -L` on 2026-11-08, and every one came back byte-identical to the file in the tree -
    908 420, 1 930 104, 214 113, 802 310, 278 884 and 927 752 B, each `cmp` clean, sha256
    (that record is as-of the tree at `22563ad`: `bars-theme_52.mp4` was re-rendered the
    same day in `06de272` at 779 905 B, and 859 706 B since the 2026-11-12 row-geometry
    change; the six sizes today are the ones the
    launcher section re-stats from the files rather than any figure in these pages)
    `e3c272ec…`, `99c8005b…`, `5117a5c0…`, `cfe8d640…`, `0f73b6be…`, `731cb1a7…`.  What that
    proves is about the link: the URL in the markdown resolves to the tree's own bytes, so a
    reader who opens or saves it gets the measured file.  Whether GitHub's embedded player
    ever fetches a rendition of its own for a given client was not measured and is not
    claimed - the same line this file keeps everywhere, between what a file can be read to
    say and what has to be looked at.  It is a hand measurement with a date rather than a
    gate: a suite that fetched the CDN would stop being the offline suite.  And it says
    nothing about the panel, which still cannot be asked what it shows (§11).
  * **A frame's clock is one instant, and its zone has to be written down.** The first CI
    run of this section measured a different picture than the bench from byte-identical
    files: `clock`'s glyph-against-halo gap read **134.6** here and **126.2** there.  The
    videos were fine.  What differed was the *mask* and the *reference layer* they were
    scored against - both drawn with `time.localtime()`, which follows the machine: the same
    epoch milliseconds print `00:25:16` at UTC+02:00 and `22:25:16` in UTC, and the `clock`
    theme's **date** line, which the theme draws through its own `time.strftime` call, read
    a whole different *day*.  Three fixes.  The series JSON carries `clock_offset_s`
    (7 200 s here, plus a `clock_note` saying what it is for) and anything rendering from it
    uses that zone rather than its own; `render.py` gained `_now()`, one hook every
    time-shaped line in a frame goes through, with `clock_str()` and the new `date_str()`
    both reading it, so patching a frame pins its seconds *and* its date; and the pinned GIF
    shape freezes the whole frame too, `--clock 11:07:42` landing beside this tool's
    reference day - 2026-11-05, the day the vendor's own captured frame is dated with -
    instead of beside whatever day the machine thinks it is.
    Verified by re-rendering `clock-Theme_07.mp4` through the new path: byte-identical to
    the published file (`0f73b6be…`), because the date it drew at render time happened to be
    the sample's date too.  And verified across zones: the whole section prints the same
    table under `TZ=UTC` and `TZ=Asia/Karachi`, glyph 241.0 / halo 106.4 / gap 134.6 in both,
    and the runner's own run of the same section (CI 42425440060) prints those same figures.
  * **What a runner's sensors actually answer, printed rather than assumed.** The same CI
    run is the first measurement of that: `sensors.collect()` there returned
    `cpu, disk, memory, timestamp` - no `gpu`, no `fans`, no `motherboard`, and no
    `cpu.temperature` - against this bench's seven sections.  The first version of the
    preview section died on it (`KeyError: 'temperature'`), because the `--live-seconds`
    step assumed a temperature exists.  It now prints whichever sections came back and
    asserts only what that step is for: that two samples arrived, that a CPU load exists for
    a meter to draw, and that `--record` wrote the zone it sampled in beside them.  Which is
    the same shape as the packaging doc's VM finding (no thermal zones, no tach header, so
    the fields draw `--`) measured one level down - and it is why `xigmalcd/sensors.py`
    wraps every section in a try/except and `render` draws `--` for what is missing
    (PROTOCOL.md §8).
  * **What a runner's fonts answer, and the probe that could not say so.** The 23
    pickable layouts ask for **16** family/bold/size combinations; this bench has all 16,
    the CI runner has **15** - there is no CJK face in that image, so the one `simsun`
    widget in `Theme_01` draws nothing there. That is the whole of the difference between
    this bench's box count and the runner's: **114 boxes** painted here, **113** there,
    and the lit pixels with them - 315 287 against 314 367, both measured after the
    `line` fix below (CI 42467173421 prints that pair, and the same section prints `15
    installed; MISSING: simsun/20` on the runner; the earlier run 42463128743 printed the
    pair before that fix, 114 / 314 169 against 113 / 313 249 - 1 118 px lower in both,
    which is the whole of the delta and one widget's worth of text). The suite prints the
    count for the machine it ran on, this bench's record beside it, and the layout, widget
    and stored `fontFamily`/`fontSize`/`bold` triple that went missing.
    Getting to that number took four commits, because the guard was not measuring what it
    claimed: it asked `bool(layout.font_for(prop))`, and `font_for` answers the three-tuple
    `(face, family, path)` - truthy **even when the face is None** - so the probe reported
    "16 of 16 installed" on a runner that then skipped a widget, and the
    skip-because-of-fonts branch of that gate was dead code from the day it was written.
    Asking for `font_for(...)[0] is not None` is the whole fix. It is also the second time
    tonight that a font-independent assertion had to be pulled apart from a font-dependent
    number: what `tests/test_library_draw.py` asserts on any machine is the accounting identity (boxes +
    skipped sources + skipped faces == the widgets in the file), that every pickable layout
    paints at least one box and more than 500 lit pixels, and that exactly 9 layouts report
    an unanswered *source*, every one of them `Pump Speed`. The totals are printed with
    their machine named.
    The two machines do agree on the part that matters for the export plan: the generated
    `clock` layout and `render.py` put down the same pixels on both - 0 differing pixels,
    worst channel delta 0, over four readings - which is the first cross-machine evidence
    that an export is faithful to the code rather than tuned to this bench. It holds because
    the export names the face its own code uses (`layout.FONTS["dejavu"]`, built out of
    `render._FONT_GLOBS`) instead of a vendor family that resolves to the same files here by
    luck.
  * **A check that compares two pictures has to say *when*, and `tests/test_theme_files.py` measures that
    rule as well as following it.** The file-model section draws one layout from memory and
    the same layout written to disk and read back, and asserts the two pictures are
    byte-identical. Run 42472937258 is the first CI failure of the night and it is a method
    bug, not a restless runner: the two `themes.draw` calls took their "now" from the wall
    clock, so the pair that disagreed differed **because a second went by**, not because of
    anything about the file model. Measured in `tests/test_theme_files.py`, so the rule cannot be
    forgotten again: the same `clock` layout drawn twice with no pinned instant differs by
    **2 819 px** across 1.05 s of wall clock (the count moves with which digits change), and
    drawn twice at one pinned instant it differs by **0** - the assertion being `drift > 0`
    and `pinned == 0`. Every pixel comparison in that section, and `themes.parity`, carry an
    instant for exactly this reason.
  * **The scrim plate, measured on the animated path.** Over the bright clip
    (`Theme_07.mp4`, luma 176.2 of 255): with no plate, glyph 244.8 against its own halo
    191.3, a gap of 53.5; with the plate the window's auto rule puts there (150/255), glyph
    246.0 against halo 153.0, a gap of **93.0** - 1.74x. The glyphs themselves do not get
    brighter; the ring around them gets darker, which is the whole mechanism and the reason
    `render.scrim` hugs the drawn pixels instead of washing the canvas. Measured at 160 px, 8
    frames, because that is what the check costs; comparable to itself, not to the 480 px
    table above.
  * **Loop seams, now that the previews run the clips round more than once.** The `alpha`
    video replays its 0.958 s background 10.4 times in its 10 s, `gauge` 5.7 times,
    `dual` 1.8, `bars` 1.2, and `clock` covers 0.6 of its 17.62 s loop without finishing it.
    Every restart in those files is the clip's own join, measured by §9 at the clip's native
    rate: `Theme_25.mp4` 2.50 against a 1.54 typical step, `Theme_30.mp4` 0.68/0.23,
    `Theme_07.mp4` 0.66/0.20, `theme_52.mp4` 2.49/1.29 and `3.mp4` **12.45**/4.55 - the one
    background here with a genuinely hard-cut loop, which the `gauge` preview inherits. What
    survives from the short-GIF era is the rule, not the table: a preview is only ever
    blamed for a jump the video underneath does not have. The table that measured 2.04 s
    GIFs (2.32/2.35, 11.19/7.24, 2.30/0.77, 0.54/0.41, 10.78/1.87 against their own clips)
    is in git history up to `296fbdb`, along with the files it scored; one finding from it
    stays useful as a warning - the 13.52 jump people saw on `theme_52.mp4` was a short clip
    cutting back through two seconds of a 10.10 s loop, not a bad loop (its own join is a
    mild 2.49 against 1.29).
  * **The GIF path is still here, and still measured**, because it is the shape whose
    digits a caption can quote: pinned readings from `tools/preview_pin.py`, `--clock
    11:07:42`, and `tools/preview_gif.py` writes a 160 px GIF whenever it is asked to - though
    nothing writes one as a check any more, which is the difference between a measured path and
    a gated one. The measurements made while README used it are still true of it: a 6 fps request becomes 12
    frames at a **170 ms** delay because GIF stores delays in 10 ms units (**2.04 s**, not
    2.00); **128 colours** for the whole animation measured 23 % smaller than 256 with the
    drawn colour within 1/255 at 480 px, and 64 colours at 320 px is where ink starts to
    move (7/255); repeating frames is not a saving, since GIF's whole size model is
    inter-frame difference - decoding at the clip's own 24 fps and letting ffmpeg drop to 8
    costs **7 205 675 B** for the animation that sampling at the target rate writes in
    **1 510 157 B**; and 320 px was the right size because GitHub renders this README's body
    **624 px** wide and displayed the old 480 px images at **281-289 px**, while a 480 px GIF
    costs 1.05-1.18 MB each. GitHub's own accessibility docs also say animated GIFs follow the
    reader's system reduced-motion preference (Settings → Accessibility → Motion → "Autoplay
    animated images"), which is why the alt text and the sentence beside the picture had to
    carry the description. A video does not go quiet in the reader's settings that way, and
    it is not in the document at all until someone uploads it - which is what the markers are
    for, and why the six files stay in `docs/videos/` afterwards as the measured originals.

  * **The `clock` theme fitted its big line and not the other two**, which is how a reading
    line ran off the glass: at font 26, `CPU 57°C  GPU 47°C  1957 RPM` measures 494.2 panel px
    against a 480 px panel (14.2 over, 7.1 at each side), and `CPU 100°C  GPU 100°C  12345 RPM`
    measures 548.5; drawn at that size the ink reaches both canvas edges, so the glyph at each
    end is not on the picture at all. All three lines now take the 440 px budget the time line
    always had, and the ink lands at x 29..450 (font 22) for the pinned set and 27..452 (font
    20) for the worst realistic one. Counted by drawing the string and reading the alpha
    channel's bbox, 2026-11-07; `tests/test_gauges.py` crops each of the theme's three lines to its own y
    band and fails if any of them touches a panel edge.
  * **A meter needs a ring that stays out of its way.** `dual` drew its unfilled arc in
    `TRACK` (120,200,220,255), a pale cyan picked at import time with nothing measured behind
    it; it now asks for `ARC_TRACK` (104,118,130,150), the neutral this module already used for
    the alpha arcs. Counted on one decoded frame of each of four clips the vendor ships, mean
    luma along the ring's mid-radius, filled part against unfilled part (CPU ring first, GPU
    ring second):

    | background | `TRACK`, the pale default | `ARC_TRACK`, now |
    |---|---|---|
    | `Theme_30.mp4` (luma 4.0) | 7.4 / 6.1 | 100.4 / 109.0 |
    | `theme_52.mp4` (11.5) | 7.4 / 6.1 | 101.9 / 105.0 |
    | `3.mp4` (56.3) | 7.3 / 5.5 | 67.1 / 81.3 |
    | `Theme_07.mp4` (180.7) | 7.0 / 4.8 | 27.3 / 20.1 |

    Seven luma out of 255 is the complaint stated numerically - the fill used to be *dimmer*
    than its own track - and `tests/test_gauges.py` re-counts the dark-clip case (100.4 against 7.4) every
    run. That last row is the honest limit of a half-transparent track over a bright field, and
    the reason the scrim plate exists rather than a reason to go hunting for a third colour.
    Off screen, both times: these are picture measurements, and the panel still cannot be asked
    what it shows (§11).
  And what those videos are not: they are not a photograph of the glass - §11 still means the
  panel is never asked what it shows - and the digits in them are one **recorded series**, not
  a guess and not a live feed: `docs/videos/readings-2026-11-08.json`, 12 samples at 1 s, with
  the load condition that produced them written in the file's own `source` note. The codec is
  x264 at `crf 20` (YUV 4:2:0), which is not the GIF path's 128-colour palette and not the
  256-colour PNG the upload path sends, whose drift §10 measures at 1/255 per channel. The
  pinned set in `tools/preview_pin.py` is still what the still previews draw and still what a
  GIF caption quotes, and that file still says field by field which of its numbers is a
  **fixture** (57 °C, 60 % of the `gauge` theme's measured 30..75 °C sweep) and which is a
  dated collect. Re-derive any figure above with `tools/preview_gif.py --clip CLIP --theme T
  --series FILE [--live-seconds N --record FILE] --frames N --gif-fps RATE --scale PX --crf N
  [--ink COLOUR] [--scrim N] [--no-gif]`: it prints the bytes, the frame count and length as
  the written file reports them, how many passes of the clip that is, and - with a series in
  play - the min→max of every reading the picture drew.
## What an install carries, and what it leaves out

* **`pip install .` carries no clips, and that is a hole rather than a design.** The three
  MP4s this repo vendors live in `media/`, which is not a Python package, and
  `pyproject.toml` declares no package data for them — so an installed `xigmalcd` finds them
  only where the roots say (`$XIGMA_MEDIA`, a checkout's `media/`,
  `/usr/share/xigmalcd/media`, and then the vendor's theme library in both its
  spellings: `xigmalcd/main.py:media_roots`), and a pip install into a
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
## How this repository keeps its own record

* **Version control: local `git` since 2026-11-06, published 2026-11-07** as
  `tamer-hassan/xigmatek-connect-lcd`, public, `main` only. Tracked: the three vendored
  clips in `media/`, the vendor's theme library in `themes/alpha/` (100 files, 84 926 540
  B of vendor bytes in the 98 the copy tool writes: 27 decrypted layouts, 44 clips, 27 baked overlay PNGs, and a `manifest.json`
  whose 125 entries hash the 98 distinct files they name — the other two files being that
  manifest and this directory's own `README.md`, and the 27 `background` entries naming the
  same bytes as 27 of the clips), the theme contact sheets in `docs/previews/`, plus the
  recorded size and sha256 of the 27 vendor `.thm` containers that are deliberately *not*
  in the tree (66 300 082 B, dropped at 0.3: see docs/themes.md and
  `themes/alpha/README.md`, which names the vendor installer they come from) — which is 66
  MB off the repository, one of the reasons the change was worth making,
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
  **The same rule, in pixels:** on 2026-11-10 an OCR pass found the serial, whole and
  legible, inside `docs/xigmaui2.png` - a live capture published on 2026-11-08, where the
  `conn 1` reply the window shows happens to name it. That file was replaced on 2026-11-12
  by a render of the same window, made by `tools/screenshot.py` offscreen against a port path
  that does not exist, so the status box holds a refusal and there is no serial in the
  picture to paint out; the published history still carries the old bytes.  What had been holding the rule was
  grepping the staged diff, and a staged diff is bytes: it cannot see a picture.  The field
  is painted out now (`docs/packaging.md` keeps the account and the byte cost), and
  `tests/test_no_serial.py` searches both halves of the serial through every published text
  file and every published PNG, by OCR where `tesseract` is installed and saying so where it
  is not.  The published history still holds the file as it was, and the owner decided on
  2026-11-10 to **leave it**: a device serial number on a panel nobody else can address is
  not a credential, and rewriting history would move the tagged releases and the assets
  published from them for no gain.  What is enforced from here forward is the picture, not
  the past.
  **What that costs, said plainly:** a clone cannot re-run `tools/verify_protocol.py` or
  `tools/theme_check.py --arc`, because the captures and the vendor install they read are not
  in the repository. Every wall-clock, byte-count and pixel figure in this file and in
  `PROTOCOL.md` names the bench file it was read out of, so that the run can be **repeated**
  rather than trusted — not so that it can be read here.  `tools/verify_protocol.py` is the
  one place the wire claims are re-encoded against the captures, and
  `tests/test_protocol.py` prints its command line and says out loud that a clone has no
  captures, rather than reporting a pass it did not make.

**Drawing one of ALPHA's own layouts, and what that cannot show.** 23 of the 27 copied
layouts are pickable (`--theme Theme_07`, and `--list-themes` prints the set); 4 are
refused by a gate on each file's own `ratio` field, because they declare 320x240 and the
em-box anchor convention that every text position in a layout depends on is measured at 480
only. Among the 23, `Pump Speed` is asked for by 9 themes: `Theme_28`, `Theme_29`, `Theme_34`,
`theme_36`, `theme_37`, `theme_41`, `theme_45`, `theme_48`, `theme_49`. Until 2026-11-13 there
was no rule for it at all - `themes.UNMAPPED` held a sentence and every one of those 9 widgets
was skipped wherever that program ran, including on a body that reported a pump.  Then the
machine was re-wired (PROTOCOL.md §8: block cable to `PUMP_SYS1`, radiator fans to `CPU_FAN1`,
six case fans to the cooler's own ARGB controller, which exposes nothing to Linux), `fan2` came
up at 2448-2469 RPM and steady through a duty sweep on its own header, and the source gained a
rule over a fan row's `type`.  Here it draws; on a box that reports no pump row the same nine
print why and name the command that would settle it, and `tests/test_pump_speed.py` holds both
halves, so "here" and "there" cannot quietly become one number.  Of the metric
names in the library, four have a display shape measured off the vendor's own baked overlay
(`layout.FORMATS_MEASURED`); within the pickable set that leaves `Time`, `CPU Frequency`
and `Pump Speed` shaped by this repo, and the per-frame note names them. Every face is a
substitution, because no Microsoft fonts are installed here (`arial` -> Liberation Sans,
`simsun` -> Noto Sans CJK), and the per-theme pixel difference against the vendor's own
picture is what `tools/theme_check.py` measures, with `themes/alpha/README.md` keeping
those figures. A layout theme ignores `--text-color`, `--cold`/`--hot`, `--label` and
`--clock-size`: its colours, sizes and geometry are inside its file - which is the same
reason the window's picker does not list what it cannot preview. Nothing about that has
changed on the wire. The window makes exactly one exception to it, in a preview, and says so
under the picture: open one of the six themes this repo draws from code and `themes.with_ink`
writes the reader's text colour into a **copy** of that theme's generated layout, over the
colours `render.SKIN` declares, so the pane's two doors agree at that ink. A vendored or
saved layout is never touched by it - measured at 0 px - and neither is the file a save would
write.

**Why the six drawn themes are still drawn from code.**  All six also exist as
generated layout files (`themes.export`, printed by `--export-theme NAME`), so the file
door could draw them, and `main.paint` already prefers a file for any other name.
Whether that is free is a measurement per option, not per theme, and `tools/knobmap.py`
makes it: one pinned reading dict at one pinned instant, every option each `theme_*`
signature accepts (read with `inspect`), the best row-level edit of that theme's own
export for each, and the pixels between the two doors.  On this run 28 of the 37 (theme,
option) pairs land at zero differing pixels with a worst channel of 0 - the reader's
text colour (through `themes.with_ink`), a clock or fan row switched off by deleting it,
`--clock-size` as the Time row's `fontSize`, `--cold`/`--hot` as `minValue`/`maxValue`,
`--label` and `--title` as a text row's `content`, and the default transparent canvas.
9 of them are far from 0 rather than near it, and the smallest non-zero gap in the whole
map is above 900 px, so the split is a line a machine can check rather than a judgement:
nothing sits between 0 and the floor.  5 of them are the black canvas alone: compositing
a plate under a finished layer is a different frame from opening one on a black canvas
before the supersampled draw and the resample, and it is the *more* opaque of the two
(see the `--bg` row in docs/usage.md - a layout seals every pixel at alpha 255, while
three of our five keep their own translucent fills).  The rest are structural, not
antialiasing: `alpha`'s heading is not a text row a `content` edit can reach, `gauge`'s
`source` moves the arc's ramp and ticks as well as its reading, and `gauge`'s `gradient`
has no key in the file model at all.

One option was in a signature and nowhere in a body until 0.4: `clock` took `clock` and
never read it, while `main._theme_kwargs` routed `--no-clock` straight to it - so that flag
moved 0 px on the one theme whose picture is a clock.  `clock` honours `--no-clock` now: the
big time line goes and the date and the readings line stay in their own y bands, which puts
the pair in the map as a row that lands at 0 px against the generated layout with its `Time`
row deleted.  Anyone using the flag gets a different frame on the glass, so stage 6 of
[theme-editor.md](theme-editor.md) owes it a look; nothing here is claimed from the panel.
Nothing in the map is left unread today, and the section that runs the tool re-derives that
from the bodies rather than remembering it.  Two options - `clock`'s `big` and
`gauge`'s `gradient` - are read by
the body but have no entry in `_theme_kwargs` at all, so no flag or socket message can set
them; `big` is a *size* (`theme_clock(big=140)`), not a flag, and the first version of this
map mistook it for one and asked with `True`.

What belongs to the machine: the non-zero pixel counts walk glyph edges and installed
faces, so `tests/test_knobmap.py` reports them beside the machine and this page carries
only the counts, the sets and the floor.  What does not: which pairs are exactly 0, and
that no option in a signature is left unread - both are re-derived on every run by the
section that runs the tool, and it asserts the words above against the run.  And **none
of this has been looked at on glass yet**: the frame byte counts in docs/usage.md (3 558
B for `Theme_29` up to 8 115 B for `Theme_35`, one pinned fixture, one pinned instant)
are offline figures from `--dry-run`, and the glass pass is stage 6 of
[theme-editor.md](theme-editor.md).  Stage 6 also owes one phase it did not have, added on
2026-11-12 and **still not run**: `tools/display_glass.py`'s `theme` phase applied `gauge`, one
of the six this repo draws from code, and nothing in its table applied a **layout file** - which
is the only way to see on a panel what the 2026-11-12 door fix claims, that a saved copy of
`alpha` keeps its `temp-values` and `fan-figures` rows once the loop, rather than the editor, is
the one drawing it.  The driver has that phase now (`APPLY a layout file`: write a copy with
`themes.save`, name it over the socket, and ask the loop's own painter what it found, with a row
that comes back with no box recorded as a failed phase rather than a line in a log), and the
phase itself is gated statically by `tests/test_glass_ledger.py` - which is all that can be
gated without a panel.  The offline half is measured
(`tests/test_specials.py`, `tests/test_apply_layout.py`); the panel half waits for somebody to
point the driver at a display.

**The file model's limits: where a theme may live, and what a save refuses.** Reading your
own copy is stage 3 there, and the window that writes one landed in 0.4: its `save as your
copy` button, with `themes.save()` behind it, is the only writer in this program.  No flag
writes a theme - `--export-theme NAME` prints a generated layout on stdout and writes
nothing, because a committed `gauge.json` goes stale the first time anyone edits
`theme_gauge`. What the model does and does not allow, all of it gated:

## The file model: one directory, one round trip, one stamp not written

* **One directory is written to: `~/.config/xigmalcd/themes`** (`$XDG_CONFIG_HOME`), and
  it is also scanned first - before the checkout and before `/usr/share/xigmalcd/themes/alpha`.
  `--list-themes` and `--check-theme` print which root answered: "your copy", "checkout"
  or "package". The two vendor trees are never written, for two different reasons: the
  installed one is dpkg-owned and re-hashed 125/125 by `debian/tests/smoke` on every
  install, and the checkout's is the file every number in these docs was read from - an
  edit there would be an edit that breaks the evidence.
* **A path is not a name, and a display is only ever told a name.** Since 2026-11-12 the
  window opens a layout file at any path at all (`open a file…`, `edit.Editor.open_path`),
  which is what a person needs for a copy that came off another machine or for the
  `<name>.json.bak` a save leaves beside a layout: `themes.resolve` reads three roots and
  nothing else, and before that door a layout outside them could not be opened. What did not
  change is where anything may be written or sent: the buffer a path produced saves to
  `~/.config/xigmalcd/themes/<stem>.json` like every other copy, the file it was read from is
  never written, and `apply to the panel` **refuses** such a buffer until it has been saved,
  because the command it sends is `("theme", <name>)` and the display resolves that name in the
  roots *it* can see - which may be a different file with the same stem, or none. The state line
  under the layout menu prints which of those three cases a name is in, by asking
  `themes.resolve()` rather than remembering what it said when the file was opened
  (`tests/test_open_layouts.py`, thirteen checks).
* **A press carries a name, not a buffer - and a save carries no press.** The same rule seen
  from the other side, for the three reports of 2026-11-13: the panel is never handed a layout
  file (§11), so what `("theme", <name>)` changes is *which* file the display draws, and what
  `save as your copy` changes is *what is in* one. A loop already naming that layout
  re-resolves it every frame, so a save alone moves the glass with no apply at all; an apply
  alone reaches none of the keystrokes still in the editor's buffer, so at a name the panel
  already holds it changes nothing on the glass. Since 2026-11-13 the press says so before it
  sends, and prints the distance - differing pixels between the frame this pane paints and the
  frame the display will make, both through `themes.paint`/`themes.draw` at the editor's own
  pinned pair, so the number is about the two pictures and nothing else. It is printed by the
  press itself, in the line under the rows and in the log, and it belongs to the machine that
  prints it: the pixels it counts are mostly glyphs, and a glyph's pixels are a face metric -
  the same reason the pixel figures elsewhere in these pages are quoted beside the box that
  printed them. `tests/test_apply_layout.py` asserts the figure is non-zero when a row's ink
  was changed and absent when it was not, and prints nothing about it - the digits for this
  bench are dated in [theme-editor.md](theme-editor.md).
* **A file with nothing to draw is refused at the reader as well as at the writer.**
  `themes.save` has refused an empty `osd.widget` list since 0.6, but until 2026-11-13
  `scan()` and `resolve()` selected on the `ratio` field alone: a JSON with no `osd` key at
  all, dropped into `~/.config/xigmalcd/themes` by hand or written by something that meant
  its own metrics dump, was a name `--theme` accepted - and `layout.draw_theme` walks
  `obj["osd"]["widget"]`, so the frame naming it raised `KeyError: 'osd'` rather than drawing
  an empty canvas. Selection asks both rules now, `--list-themes` counts the refusals out by
  reason instead of saying "refused", and the editor's by-path door quotes the same sentence
  (`themes.NEED_OSD_WHY`). What did **not** change, and would cost a measurement first:
  selection still does not run `validate()`. The loop re-resolves its theme name on every
  frame, and validating 27 layouts - 152 widgets, every field - per frame is a cost that has
  never been measured here, so the reader asks the one predicate the painter actually needs
  and `--check-theme` is where the detailed report is printed.
* **The six drawn-from-code names cannot be saved as files.** A `gauge.json` would be a
  second source of truth for `render.theme_gauge`, which is exactly the drift the export
  design exists to avoid; a save that tried it is refused, and `--check-theme gauge` says
  the export does not exist yet instead of failing.
* **`property` is a one-element list, and that is a hard rule, not a style preference.**
  All **152** vendor widgets use one entry, and `layout.draw_theme` reads `property[0]` only -
  a second entry would be silently unwritten, which is the failure mode this repo's
  "say the choice, never repair it" rule refuses. Same for an empty `osd.widget` list:
  nothing to draw is not the same thing as an empty canvas. Since 0.6 both rules have a
  door in the editor in front of them, and neither door keeps a private copy of the rule:
  `add_widget` runs `validate` over the layout *with the new row in it* and refuses on any
  hard answer before the row exists, and `delete_widget` refuses the row that would empty
  the list, asking `validate` what it would say about the emptied layout and repeating that
  sentence. The suite re-counts the envelope the rules guard - every one of the **185**
  rows in the **28** layouts the editor opens carries exactly `id`, `layerIndex`, `type`,
  `property`, `widgetContent`, and `property` is one element in all of them - and fails if
  the page's digits stop being that run's.
* **A round trip is byte-identical, with one measured bound.** All 27 shipped layouts
  reproduce from their own parsed content, and `shape_of()` records the one thing the
  vendor's files disagree about - 18 escape non-ASCII as `\uXXXX`, 9 keep it raw - so a
  copy for editing starts out identical to its source (23/23) and a writer that always
  escaped would "change" 9 files nobody opened. Unknown keys survive a save; the
  `xigma.*` extension keys and a `special` kind are inert to anything but this program,
  because the JSON never goes on the wire (PROTOCOL.md §11).
* **`property[].time` is not written.** 82 of the 152 vendor widgets carry a timestamp, in
  27 distinct values, and it is the vendor editor's own save stamp - there is nothing in
  the drawing that reads it. The plan said derive it; building it showed there is nothing
  to derive it *from*, so our exports omit it and a gate asserts that none carries one.
  Export ids are `xigma-*`, never a random uuid, so a generated file is byte-stable.
* **An exported layout is a picture of the theme *with its readings*, and the two doors
  differ where a reading is missing.** `gauge` reaches a zero-pixel diff on every metrics
  dict that answers `CPU Temperature`, and `tests/test_export_parity.py` asserts that. Handed an
  empty one, the code theme still paints what does not depend on a reading - it draws the
  ring's track with no fill, 17 451 lit pixels - while the exported layout paints 4 319,
  because a layout skips each widget whose `source` has no value (the same rule that makes
  `Theme_28` draw six boxes instead of seven). Measured across the fixture readings
  `tests/test_export_parity.py` keeps, code px against layout px: `alpha` missing `GPU Temperature` and both
  loads is 32 106 against 22 932, missing only the two loads 40 497 against 31 323, and with
  nothing answered at all 25 396 against 16 222; `dual` without a GPU temperature is 29 228
  against 18 743 and with nothing answered 27 388 against 6 409; `gauge` 17 451 against
  4 319. In each of those the code theme is drawing what it can without the reading - a
  ring's track with no fill, a bar's track, `--°C` or `--%` - and the layout has no row to
  draw at all. Both
  are right by their own rule, so the counts are printed side by side rather than
  reconciled: an export translates the drawing, not the theme's fallback behaviour. Where a
  code theme skips a widget too - a `dual` with no load reading draws no bar and no status
  line - the two doors agree to the pixel anyway, and `tests/test_export_parity.py` counts those cases
  separately rather than folding them into the pass.
## Conventions a layout names, measured against the function it names

* **A ramp can be written as data, and this was measured rather than assumed.**
  `xigma.colourStops` holds `[fraction, rgba()]` pairs interpolated piecewise-linearly,
  and at every position a ring actually steps through (3 degrees along a 300-degree sweep,
  100 positions) `render.temp_colour`'s three-stop ramp agrees with it at **all 100** -
  the amber's fraction (62-30)/(100-30) round-trips through JSON to the same double - while
  `render.heat()` disagrees with its own stop copy at **8 of 100**, never by more than one
  unit and only in the red and blue channels. The eight land in exactly two segments: seven
  between the 0.5 and 0.8 stops, where `heat` divides by the literal `0.3` while
  `0.8 - 0.5` is `0.30000000000000004`, and one past 0.8, where it divides by `0.2` while
  `1 - 0.8` is `0.19999999999999996`. Under `int()` truncation a product a hair under an
  integer steps down. So the data spelling is exact for a value-keyed three-stop ramp and
  inexact for `heat`, and what that blocks is `dual`, not the schema: the options are to
  fix `heat`'s divisors to agree with its own breakpoints - which moves the recorded
  figures for `dual`, `alpha` and `bars`, since that ramp is in all three - or to name the
  ramp the way a `special` drawing is named. The suite prints the counts, so the choice
  can be made against numbers.
* **A layout that was never shipped, written and read back through the file model, paints
  with zero difference.** The suite authors a one-widget ring (`colourStops` plus
  `xigma.arcPaint: render`, 30..100 C with amber at 62), saves it with `themes.save`,
  resolves it back out of the user directory and draws it through the same door the loop
  uses: against `render.temp_arc` it is **0 differing pixels and worst channel 0** at six
  values - 12, 31, 52, 62, 88, 100 C, 11 411 lit pixels, the 12 reading drawing "no fill"
  both ways. That is stage 4's premise demonstrated before stage 4 exists: an edited file,
  not an export of our code, can be held to the same zero-diff standard.
* **Two ways to rasterise the same ring, and the difference is not rounding.** Our gauge
  ring segments a fill into 3-degree arcs, each drawn 0.4 degrees past its end so the
  joints do not show, colour sampled at the segment's *start* and mixed by truncation
  (`render.gauge`). ALPHA's own ring, measured off its captured frames, is 1-degree arcs
  sampled at the middle, butt caps, with `ARC_COLOUR_MEASURED` consulted for its declared
  colour pair. Same geometry, same two declared colours: **164 / 3 366 / 3 889 / 6 989
  differing pixels** at four readings, worst channel delta 255 - `tests/test_conventions.py` paints one arc
  both ways and prints it. That is why `xigma.arcPaint` exists as an enumerated key instead
  of being left to the painter's mood, and why the copied library, which carries no such
  key, keeps drawing exactly as stage 1 measured it: 114 boxes, 315 287 lit pixels here.
* **The same argument one shape over, for a bar.** `xigma.barPaint` selects `vendor`
  (fill spans `round(width x fraction)` panel px, corners as declared) or `render`
  (`int(width x SS x fraction)` in **device** px, track corners at `height/2`, fill corners
  `min(height/2, int(width x max(fraction, 0.02))/2)` - corners that change with the
  reading). One bar, 360x14 at (60, 340), declared cornerRadius 5, drawn both conventions:
  **203 / 306 / 327 / 206 differing pixels** at 0, 3, 63.5 and 100 % (worst channel delta
  235-255), recorded by `tests/test_conventions.py`. At 63.5 % the fill ends at device px 457 under one rule
  and 456 under the other, which is the whole difference and shows how easy it is to lose a
  pixel to a rounding convention nobody wrote down.
* **A third bar convention, measured against the function it names.** `vendor` and `render`
  describe rules; `xigma.barPaint: hbar` names a drawing - `render.hbar`, the usage bar of
  the theme ALPHA selected - so the claim is settled by painting the same bar both ways:
  square ends whatever the file declares, `bgColor` showing for the whole declared rect, and
  the fill coloured **one device column at a time** along the filled part, `startColor` at
  the fill's left edge and `endColor` at its right, so the ramp's far end travels with the
  value. A vendor `bar` cannot say that: it declares one colour pair and, under `vendor`,
  fills with the near one.
  Measured at `render.py`'s own geometry and inks - `tests/test_pinned_metrics.py` reads `A26_BAR_XY`,
  `A26_BAR_WH`, `A26_TRACK`, `A26_BAR_A` and `A26_BAR_B` out of the module rather than
  writing them down, so the probe cannot drift from the theme it tests - and it is a
  **zero diff**: 28 pairs at device resolution and 7 more after the same LANCZOS downsample
  a 1x frame goes through, all 0 differing pixels with worst channel 0, over values 0, 3,
  22, 62, 100, 137 (past the declared maximum) and -5, on both of ALPHA's usage bars, and
  at declared `cornerRadius` 0 *and* 5. The same declared bar under the other two
  conventions sits **7 354** and **7 347** px away from that drawing at 62 %.
  Two notes on how that gate was built, because both of them bit:
  * the first version declared `cornerRadius: 0` and passed while the convention still
    drew the file's rounded track - `square` was falling through to "declared". `hbar` has
    no radius argument at all, so a declared 5 must not leak in; the second value of that
    pair is what catches it now;
  * a diff of zero can be reached by drawing *nothing*, so `tests/test_export_parity.py` also counts how many
    pixels of the declared rect still read the track's own colour as the value rises:
    **1 376 at 0 % -> 955 at 30 % -> 512 at 62 % -> 0 at 100 %**, the same numbers in both
    drawings. The fill is being walked column by column, not hidden under a track that
    happens to match.
* **The same test for `barPaint: render`, and it found a bug.** That entry names
  `render.bar`, so it is measured against it too: 14 values, 0 differing pixels, at
  `dual`'s own geometry with the `heat` ramp named rather than copied
  (`xigma.colourRamp`, and the ramp is sampled at the value's fraction). The 14 include
  1.01 %, 1.5 %, 2 % and 2.5 %, and those four are the point: `render.bar` draws a fill
  whenever `frac > 0.01` but rounds its corners off `max(frac, 0.02)` - **two** different
  floors - and the convention table had a single `floor` doing both jobs, so a load between
  1 % and 2 % drew **no fill at all** as a layout widget while `render.bar` drew one. The
  parity checks as they then stood never stepped in that band, so nothing caught it until
  `tests/test_conventions.py` did; `corner_floor` is a key of its own now, and that file's load
  list walks 1.5 % and 2 % - the two values that found it.
## Joint sizing, and the construct `bars` needed in the end

* **Two widgets can share one text size, and the schema has no way to say so.** `alpha`
  draws its two fan figures at one size, and its two temperature values at one size, each
  chosen from *both* readings at once. Measured, then decided (owner, 2026-11-08): each
  pair stays one code-drawn `special` and the layout only places it, rather than a new
  `xigma.fitGroup` key. The numbers behind that, all recorded by `tests/test_specials.py`:
  * the fan pair landed. It is one `special` named `fan-figures`, and painted through the
    frame loop's door - `themes.SPECIALS` injected, the instant pinned through
    `render._now` - it puts down the same pixels `theme_alpha` puts down for that row:
    30 reading pairs, and for each one the row's painted-pixel set is exactly the set that
    changes when `fan` switches off, every one of those bytes equal, with nothing reported
    missing and no gaps. The shared size is spelled out again by `tests/test_specials.py` as
    `max(A26_FAN_MIN, min(fits))`, walked through `render._fit_size` (the loop the other
    themes use), and compared with what `layout.draw_special_pair` chose: equal in all 30.
  * sized one at a time the two figures would not match each other: 25 of those 30 reading
    pairs fit at two different sizes, and drawing each at its own size moves the row by
    1 763 to 2 915 px - both counted on the author's bench, on its installed faces, which
    is why `tests/test_specials.py` reports them beside the machine rather than pinning them. What is
    pinned is the shape of it: the row differs from the joint sizing exactly when the two
    fits disagree, so those pixel counts are a real drawing difference and not rounding.
  * the value pair is the same problem with a harder limit. `render._fit_arc` takes **both**
    strings and returns one size, and that size is exactly the smaller of the two columns'
    own fits - 36 reading pairs, no exception (26 of them land at two sizes on the bench).
    So it *could* have been a group key. What it cannot be is `xigma.autoFitMax`, which is
    a width: of the 441 whole-pixel budgets this canvas can hold, not one reproduces the
    sizes the ring picks for `--`, 5, 22, 57, 100 and 241 °C all together (the best
    reaches 5 of the 6), and the per-reading windows run from a floor of 153 px down
    to a ceiling of 148 px - an empty interval. The ring's limit is its hole, not a width,
    so `temp-values` becomes the second group special on measurement and not on taste.
  * the temperature rows landed, and what the second one had to name is the ring itself:
    `xigma.fitArc`, spelled in an `arc` row's own vocabulary (`cy`, `radius` the inner edge,
    `width` the stroke, `angleStart`/`angleEnd` the app's degrees). Held to `theme_alpha` the
    same way the fan row is, over the same 36 reading pairs: each row alone puts down 4 345
    to 7 882 pixels (the figures) and 3 406 (the labels, the same count in every pair,
    because those strings never change) - counts that follow the faces on the bench, so the
    suite prints them rather than pinning them - every one inside the rings' clear hole and
    carrying the theme's own bytes; and the **two rows in one frame** cover that hole
    exactly, in both directions, with nothing the theme paints there left unpainted. What
    that hole *is* was measured rather than drawn as a band: the ring's painter, on a canvas
    of its own through the same supersampling and the same `LANCZOS` downscale the theme ends
    with, leaves **1 016 px** of ink inside the declared inner edge, its deepest pixel
    **2.77 px** past it - antialiasing plus the resampling tail. Those pixels are the ring's,
    and a row that draws text cannot answer for them. What is left of the hole is the rows',
    and it is painted exactly. Their ink stays **5.00 px** inboard of the edge the ring
    paints up to, **2.23 px** clear of that tail - measured on the bench, and the reason
    `render.ARC_FIT_GAP` is a named constant rather than a literal at two call sites: the
    suite holds it above the tail it measures, because a clearance below that would put a
    reading on top of the gauge it belongs to.
  * **ink means alpha, and the difference bites.** A text-only frame still disagrees with the
    theme at a couple of pixels inside that hole, and `tests/test_specials.py` asserts that *every* one of
    those carries alpha 0: colour channels left non-zero by the downscale of a bright stroke
    against a transparent canvas, invisible, and a residual of the ring's own drawing rather
    than of these rows. That is the assembly's remaining job - with the rings drawn as `arc`
    rows into the same 4x canvas and one downscale, the residuals come out of the same
    arithmetic as the theme's.
  * the label pair is a `special` and not two `text` widgets, which is the part a reader
    would call redundant: "CPU TEMP" and "GPU TEMP" are constants, so a file *could* carry
    them, at a `fontSize` this program generated. It would then bake a face metric of the
    machine that generated it - the size the ring decides is 22 px here and is whatever the
    installed fonts answer somewhere else - and an export that cannot be driven to a zero
    diff on the machine drawing it is not shipped. The suite pins the shape of that
    difference: the label row's size is a single number across all 36 pairs, while the
    figures' takes 4 of them.
  * and a `values` row that declares no ring is not drawn at all, in words rather than by
    accident: `--check-theme` prints which `xigma.fitArc` key is missing, and the frame the
    loop paints for that row holds zero pixels - measured, since drawing at the `fontSize`
    ceiling instead would put both figures on the stroke.
* **A ramp can be data, or it can be named - and both are now spelled, because they are
  not equally exact.** See the `xigma.colourStops` and `xigma.colourRamp` entries printed
  by `--print-theme-fields`: three stops reproduce `render.temp_colour` at all 100 sampled
  segment positions and miss `render.heat` at 8 of them by one unit. The owner's decision
  (2026-11-08) was to **name** `heat` rather than fix its arithmetic, because dividing by
  `(0.8 - 0.5)` instead of the literal `0.3` would re-render `dual`, `alpha` and `bars`,
  and every figure recorded for those three themes was read off the drawing as it is. That
  keeps the recorded evidence intact and puts the inconsistency on the record in
  `render.heat`'s docstring rather than in a doc nobody re-reads.
* **`bars` needed a smaller construct than this document first chose, and it needed a change
  to our own drawing more.** Its rows used to be built at draw time from whatever
  `sensors.collect()` reported - six fixed readings plus one row per fan, up to four - and
  the row pitch was `min(56, max(28, 320 // len(rows)))`, so the vertical geometry of the
  theme moved with whatever the box happened to report. That is closed as of 2026-11-08. `theme_bars` now lays out **ten rows on every machine**
  - six fixed readings, two reserved drive slots and four reserved fan slots, all taken by
  position - which makes the pitch 32 px everywhere on every machine, because twelve rows is
  the most the block can ever be asked to lay out, and a row with no reading keeps its place: it is not drawn,
  and the
  advance still happens. That is what the 27 library layouts do, and it is the rule
  docs/themes.md states as "a hole that says what it is, rather than a zero that reads as a
  measurement"; `tests/test_bars_rows.py` holds the twelve-row layout, the keep-place behaviour and the margin under the last meter, counting
  ink in the slots, and it is what made the earlier stance - "invent a repeat group" -
  unnecessary: the 23 selectable library layouts ask for 7 `source` names and none of them is
  a fan, so `Fan 1` is a new name in our own table, while a repeat group would have been a
  new structure in a file whose whole point is being a fixed list of rows.

  What the **drive slots** cost, in pixels, measured rather than guessed (2026-11-14).  The
  pitch is `BARS_SPAN // len(rows)`, so at `BARS_SPAN` 320 ten rows gave 32 px, eleven gave 29
  and twelve give 26 - and at 29 the shipped meter (`BARS_BAR_DY` 12 over a 6 px track) sat
  **1 px** from the text band of the row below it, nearer *that* row's label (1 px) than its own
  (3 px), which is the difference between a meter and a separator line; `tests/test_bars_rows.py`'s
  clearance floor is 2 px and it failed on both halves.  Two ways out were swept on the shipped
  painter with the ink measured from it: thin the meter to (11, 4) at pitch 29, which clears 2 px
  above and 4 below - at the floor, on a track already thinned once from 10 px for this same
  reason - or use the room the block already has below it.  The room was larger than the
  arithmetic suggested, because two of the reserved fan slots draw nothing on a box with two
  tachometers: measured on this machine that day, the ink ended at y=335 and the clock's own ink
  began at y=445, **93 px of empty canvas** inside the block.  (Re-measured on 2026-11-14 after
  the GPU-fan row went in: the block now ends its text ink lower, and the empty run above the
  clock is 45 px rather than 67 - the `TheBlockStopsBeforeTheClock` check prints the current
  pair, y=442 and y=446, which is the number that matters.)  So the span grew instead of the meter being
  thinned - 320 -> 352 for one drive row, then 352 -> **384** for two, with the clock moved from
  y=452 to y=458 to keep the margin - and the pitch stayed 32 px at twelve rows, the track stayed
  6 px, and the inter-row clearances are 3 px above a meter and 4 below.  (Superseded the same
  day, by the paragraph below this one: the block now draws **eleven** rows, and an eleven-row
  block across the same 384 px span computes a 34 px pitch.  The span, the 6 px track and the
  clock's y are what did **not** move.)
  The margin under the last row is now measured too, because at twelve rows there is not much of
  it: `TheBlockStopsBeforeTheClock` in `tests/test_bars_rows.py` draws the block with **every slot
  answered** - the case that has never been drawn here, since this box leaves two fan slots empty
  - and holds the last row's meter ink (to y=442) clear of the clock's ink (from y=446), 3 px of
  air, floor 2.  It also prints what a thirteenth row would compute (pitch 29, last centre 420),
  which is the arithmetic the clearance rule already refuses - and that print is what settled the
  owner's GPU-fan request on 2026-11-14: the row could be added **only by trading one**, so the
  fourth fan slot went back to being a name and not a row.

  What the change costs, stated rather than left to be noticed: on the glass a missing
  reading now leaves a gap where the rows used to close up, and the `bars` preview clip
  had to be re-rendered from the recorded series in the same change - not for tidiness,
  because the deleted suite re-drew the layer from
  `docs/videos/readings-2026-11-08.json` and scored the tracked file against it, so a
  stale clip failed. Nothing does that now: the six video files are 0.7's deliberate
  gap, and `ffprobe` plus `du -b` are the doors to re-measure them at (docs/tools.md).
  The sources followed on 2026-11-09, and so did the file: `themes.BARS_ROWS` names the
  rows - **eleven today**, seven labelled readings and four slot pairs, and the row count is
  what moved on 2026-11-14: a drive row made it eleven, two positional drive slots made it
  twelve, and the owner's `Fan GPU` row plus a dropped fan slot brought it back to eleven, at a
  34 px pitch (see the pitch arithmetic above, and the paragraph after it for the ceiling that
  twelve still is).  Four of them are slot pairs (`Fan N Speed`/`Fan N Name`,
  `Disk N Temperature`/`Disk N Name`) - which the
  vendor's own vocabulary has no word for, since it offers the aggregates `cpuFansSpeed`
  "CPU Fans Speed" and `gpuFansSpeed` "GPU Fans Speed" and never a row per tachometer
  (PROTOCOL.md 10) - while `RAM Rate` and `Used RAM` come out of that record's `RAMRate` and
  `UsedRAM`.  Of those two aggregates the GPU one is now paired with a field and drawn as a row,
  and the CPU one is the single name in `layout.VENDOR_FORMAT` with a shape and no source, said
  out loud in `tests/test_bars_rows.py`; and `themes.bars_recipe()` generates the 46 widgets
  out of that table and the `BARS_*`
  constants. It is pixel-identical to `render.py` at every reading
  `tests/test_bars_rows.py` and `tests/test_export_parity.py` give it, answered and
  unanswered alike. Two things that took were not in the plan:

  * **`xigma.showIf`, a new extension key.** `bars`'s memory rows divide a percentage for the
    meter and print gigabytes for the number, so the number row's drawing depends on a reading
    other than its own - and an integrated GPU is a normal machine that hits it, reporting
    used memory with no dedicated total. The theme draws neither number nor meter there; the
    file, which reads `Used GPU Memory` as its own source, printed `4 GB` beside an absent
    meter: **651 px and a worst channel of 255**, re-measured on this bench after the 2026-11-12
    row-geometry change (the same comparison came out 706 px before it). The key names the dependency, an unanswered
    dependency is reported in the skip list as `showIf:<source>`, and `tests/test_bars_rows.py` measures the
    key's worth by stripping it from a generated `bars` and counting the pixels it then
    differs by. The other prefix in that list came out of the editor's work: an unappliable
    `xigma.format` is reported as `format:<source> (ValueError)`, because the model refuses
    one on the way into the file and the painter still has to survive one that is already in
    it - a hand-edited key then costs one row and says which, instead of stopping the loop.
  * **Two defects in the theme's own ratio code, found chasing that number.** `theme_bars`
    read `mem["used"]` outright, so a reading with a total and no used raised `KeyError`
    inside the frame loop; and its two memory meters were formed by different tests - the GPU
    row required its numerator to be *truthy*, so a reading of exactly 0 dropped the row while
    the memory row kept it. Both go through `render.pct_pair` now, and `tests/test_bars_rows.py` measures the
    rules that follow: at `memory: {total, no used}` the frame draws and the RAM row keeps its
    label with no number and no meter, and at `gpu: {memoryUsage: 0, dedicatedTotal: 8192}`
    the VRAM row draws `0.0 GB` with its track unfilled. A zero numerator is a reading; a zero
    or absent denominator is not a pair. `bars` was the only theme that could have found
    either, because it is the only one that reads those fields.

  What the export did *not* cost is worth recording too: `docs/videos/bars-theme_52.mp4`
    did not have to be re-rendered for these changes, and that is measured rather than
    assumed - the preview section runs `themes.BARS_ROWS` against all twelve samples of
    the recorded series and finds every row this box can have answered at every one -
    the six fixed rows plus the fan slots inside the count its sensors reported, the
    slots beyond that being empty in the old drawing and the new one alike. The rows
    these changes move are exactly the rows with no subject, no reading, or no pair to
    divide. What is left open for `bars` is on the panel, not in the file: the same rows
    at 1 and 2 fps on the glass (stage 6). Nothing about the wire changes either way
    (docs/theme-editor.md carries the decision and the order it is built in, in the
    plan's own table). A related fact came out of the same work: the one colour pair
    with a measured ramp is ALPHA's *declared* pair, (0,247,255) to (0,255,113), and the
    plateau that curve ends at is (0,251,184) - which is what `render.ALPHA_HOT` is. Our
    theme took the far end of ALPHA's curve and drew a straight line to it, so for our
    pair the two conventions differ by stepping alone and neither has a profile to use.
    * **Sizes outside the ten the library ships are allowed and said, not repaired.**
    Those ten are 12 14 16 20 24 32 40 70 100 140, counted out of the 27 files; our own
    generated `clock` export uses 22 and 26, and `--check-theme clock` warns about both.
    That is honest rather than wrong: the drawing is this repo's code, and its
    pixel-parity against `render.py` is measured at a zero diff - but it is also a shape
    no vendor file has ever been seen to use, and the warning says so.
