# Running `xigmalcd`: options, the wire, and one port between two processes

The flag table, what goes to the panel and when, and the arrangement that lets a service and a window share a device that allows exactly one opener.

## The background layer, and why the rate matters

The default run uploads the theme background first (`media/Theme_25.mp4`, 215 KB) and
then draws on a **transparent** canvas, so that background keeps playing behind the picture
- which is how the vendor's own app does it, and the pair is what its own config names, so
the default glass is what ALPHA showed you on Windows. `--bg black` paints an opaque field
over the background instead; `--no-mp4` skips the upload and uses whatever the panel already
has stored. Two other vendored clips are one flag away: `--mp4 media/Theme_11.mp4` (3.4 MB,
the quietest loop in the vendor's library) and `--mp4 media/theme_48.mp4` (1.33 MB, nearly
white under white glyphs, which is why a `--scrim` plate is drawn automatically for it).

Choose the rate deliberately: the glass shows the newest frame the panel has *committed*,
so what you see is up to one frame period old - the seconds digit runs ~1 s behind at
1 fps and stops looking behind at 3 fps. 1 fps is the vendor's cadence and its write
count; every frame is one `transport`/`transported` pair, and the ordering inside that
pair is not cosmetic, see [Notes and known limits](limits.md).
## What the panel gets

Two things, in this order:

1. `STATE all 1` — a JSON metrics blob with the same schema and units the Windows app
   uses (cpu/gpu/disk/memory/network/fans/motherboard). It matches the
   `attribute:["Status","Fan","Pump"]` the panel reports, i.e. the pages it says it has;
   this project has never seen those pages render (our OSD covers the screen and there
   is no readback), so that is the vendor's intent, not an observed behaviour. Sent
   **twice at
   startup**, like ALPHA does: the panel stops answering the picture channel if it is
   fed metrics continuously, so `--state-every` exists but defaults to off.
2. One PNG per frame — rendered at 960×960 and downscaled for clean type, uploaded as
   `<timestamp>.osd` through the media transfer channel. The loop never waits on the
   panel: 40 KB was handed to the kernel in ~50 ms, the panel confirms each file ~100 ms
   later while the next frame is being drawn, and `--fps` is the metronome. (That write
   timing was measured when frames went up as RGBA; they are about 12 KB now, and the
   write has not been re-timed.) The stock files from the Windows app are 480×480 8-bit
   RGBA PNGs (~24 KB). Ours are the 256-colour file on either canvas, transparent or
   opaque: **12.2 KB** for one ringed `alpha` frame offline, 12 322-13 372 B a frame in
   the first window run with that default. The choice was made on glass, not on the
   offline numbers - the same frame went up both ways at 1 fps, **61 of 61** frames each,
   42 560-46 415 B against 12 169-12 401 B, and what the offline numbers predict (a gauge
   ramp drawn in 80 colours coming back in 13) was not visible from the chair.
   `--truecolor` puts the exact 8-bit RGBA file back on the wire, where the alpha of the
   half-transparent gauge track is kept to the unit ([Notes and known limits](limits.md),
   PROTOCOL.md §11).

Sensors on this machine: `k10temp` (Ryzen Tctl), `amdgpu` (iGPU power/voltage),
`nvme` and `r8169` via hwmon, `nvidia-smi` for the discrete GPU, `/proc` for load,
memory and network rates, and the board's Nuvoton NCT6687D tachometers once
`sudo modprobe nct6683` has bound them — that is what makes `CPU FAN nnnn RPM` real
(`tools/fanscan.py` lists the channels and shows how the CPU one was identified).
Put the module in `/etc/modules-load.d/` if you want it at every boot.

## Options

| flag | meaning |
|---|---|
| `-d, --device PATH` | serial port; default is the first `/dev/ttyACM*` |
| `-b, --baud N` | 115200 (the panel's only rate) |
| `-t, --theme NAME` | `alpha` (default), `gauge`, `dual`, `clock`, `bars` - or one of ALPHA's own library themes by name (`Theme_07`, or its numeric id `1757491588804`, in any case: it is stored as the file spells it). The library themes are painted from their own copied layout files by `xigmalcd/layout.py`; see "ALPHA's layouts as a picture" below. `alpha` is the theme the vendor app currently has selected (`presetTheme[26]` in its `store.json`), redrawn from that file's own widget geometry, with a GPU-temperature column matched to the CPU one, a 30-100 °C gauge arc around each temperature (green through amber to red), a seconds clock and one fan figure under each temperature |
| `-f, --fps N` | frames per second. 1 is the vendor app's rate and its write count. Higher rates are real, not wasted: the glass takes the newest frame it has committed, so the picture you see is up to one frame period old - the on-screen clock runs ~1 s behind at 1 fps and stops looking behind at 3 fps, and the panel accepted **361/361** frames in one 120 s window and **1173/1175** in a 400 s soak at 3 fps; the ringed `alpha` picture, which is the biggest frame this code sends (39 400-45 244 B), took 3 fps too - **91 of 91** in 30 s. Choose it for the write count you are willing to spend (86 400 uploads a day at 1 fps, 259 200 at 3) |
| `--duration N` | stop after N seconds |
| `--once` | push one frame and exit |
| `--dry-run DIR` | render to PNGs in DIR, never touch the port (test a theme) |
| `--bg clear\|black` | `clear` (default) draws on a transparent canvas, so the panel's own background layer keeps playing behind our glyphs - the way ALPHA's `.osd` files do, which paint 4.6 percent of their pixels. `black` is the old opaque picture, which covers that layer completely |
| `--mp4 [PATH]` | upload a 480×480 H.264 MP4 as the panel's background layer at session start, as ALPHA does with its theme background. **On by default**, with `media/Theme_25.mp4` from this repo (214 917 B, 23 frames at 24 fps, a 0.96 s loop, byte-identical to the copy `currentThemeBg` names in `%APPDATA%/alpha`, mean luma 18.7 of 255 so it is dark under white glyphs, 0 black frames). Its measured weakness is the loop join: 2.50 against 1.51 typical frame-to-frame motion, i.e. a small jump once per second. It is the default because it is the vendor's own pairing, not because it measures best; the two measured-quieter vendored clips are one flag away - `--mp4 media/Theme_11.mp4` (3 402 098 B, 363 frames at 24 fps, a 15.1 s loop, luma 13.3-24.1, 0 black frames, join 0.11 against 2.54 - the smoothest loop in the vendor's library, taken in **2.4 s**) and `--mp4 media/theme_48.mp4` (1 333 649 B, 10.85 s, luma 227.3, a near-white field for white text and a join of 4.50 against 0.60, hence the automatic `--scrim`). All figures come from decoding all 40 vendor clips, not from sampling ("Where the defaults come from"). `Theme_24.mp4` in the vendor tree is the smallest upload that still reads seamless (0.94 MB, 4.04 s, join 1.55 vs 2.93) |
| `--no-mp4` | skip the upload and leave the panel's stored background playing. The panel plays the last media file it took, so what is stored now is whatever the last run uploaded (`Theme_25.mp4` after the 11:04 run); only a reset clears it — `xigmalcd-reset --yes` on an installed system, `tools/reset_panel.py --yes` in a checkout — which puts the still logo back |
| `--text-color COLOUR` | the ink of the text this program draws: a name from this program's own palette (`amber`, `mint`, `cyan`, `white`, `dim`…), `#rgb`/`#rrggbb`, or anything PIL's colour table names. Unset keeps each theme's own skin - and for `alpha` that skin is the white measured in its layout file (6 of 6 text colours, PROTOCOL.md §10), which is why unset is the default and not a guess. It changes **our layer only**: the vendor's themes keep their text colour inside their own files - 106 `textColor` values across the 23 480×480 layouts, 88 of them `rgba(255, 255, 255, 1)`, 5 of those themes using other colours at all - and nothing here sends one, so a vendor theme's lettering is whatever that theme's file says, whatever this says (docs/themes.md has the table). The colour is baked into the frame before it is uploaded, so the panel is never told a colour and is never asked one (§11). Measured off-glass by the suite: a chosen ink comes back within **1/255 per channel** after the default 256-colour palette encoding, and choosing one leaves the frame's painted area unchanged (gauge 6 087 px before and after) - the ink moves the ink, not the composition |
| `--clock-size N` | how tall the clock's digits are, in pixels, for themes that draw one. Default 26 of the panel's 480 |
| `--gauge-source temperature\|load` | what the arc follows. `temperature` is what ALPHA uses, and on an idle desktop CPU it barely moves (across ALPHA's own 65 captured frames the tip travelled 14 degrees in 43 s); `load` follows CPU busy percent, which moves every second |
| `--cold N`, `--hot N` | the gauge's scale. Default 30/75, measured off ALPHA: its digits read 57 °C at 55-61 percent of the sweep |
| `--title TEXT`, `--label TEXT`, `--no-clock` | what the picture says. Themes without a heading ignore `--title`; `--label` defaults to `CPU TEMP`, or `CPU LOAD` with `--gauge-source load` |
| `--scrim A` | alpha 0-255 of the dark plate drawn behind the glyphs. Unset is automatic: no plate over the shipped dark default (luma 18.7), a plate at `SCRIM_ON_BRIGHT` 150 over a vendored clip measured brighter than mid-grey (`theme_48.mp4` is 227, white on white without it), no plate for `--bg black` or an unmeasured clip. White glyphs by default - ours, and 6 of 6 `textColor` values in the layout of the theme ALPHA has selected (across the library's 23 480×480 layouts, 88 of 106 text colours are that white; the suite re-derives both counts) |
| `--order notice\|fast` | when `transported` goes out. `notice` (default) holds it until the panel's own file notice lands, which is the order ALPHA's traffic has and the only order that makes the glass redraw every frame; `fast` sends it right after the last file byte, and the panel answers that 1 time in 6 and the picture jumps (`tools/order_probe.py`, PROTOCOL.md §6) |
| `--truecolor` | put the exact 8-bit RGBA PNG on the wire instead of the 256-colour file that is the default on **every** canvas. Costs 3.4× the bytes — on glass one ringed `alpha` frame measured **42 560-46 415 B against 12 169-12 401 B** (means 43 782 B against 12 289 B) — and it is the only shape that keeps the half-transparent gauge track's alpha to the unit. What the default gives up is in `tools/selftest.sh`'s prints: the gauge ramp drawn in 80 colours coming back in 13, and 74 of 11 149 fully opaque pixels keeping alpha 255. Both shapes went up **61 of 61** frames at 1 fps and the owner could see no difference from the chair, which is why RGBA is the opt-in (PROTOCOL.md §11) |
| `--palette` | spell the default out: the 256-colour PNG, over a transparent canvas as over an opaque one, which is what `xigmaui/panel.py` has always uploaded. Kept so older command lines and README's encode A/B/A windows mean what they say; `--truecolor` wins if both are given |
| `--colors N` | palette size for the indexed file (default 256) |
| `--chunk N`, `--gap S` | raw upload chunk size, and the one pause between the `transport` announcement and the first file byte (the vendor app: 1000 bytes; the pause is 0.02 s and see §6 before setting it to 0) |
| `--overlay` | old name for `--bg clear`, kept so earlier command lines still work |
| `--no-state` | skip the metrics blob entirely |
| `--state-every N` | refresh metrics every Nth frame (see the caveat above) |
| `--no-fans` | leave fans out entirely: no `fans` section in the metrics blob, and no fan figures on the picture |
| `--metrics-file PATH` | draw the picture from the sections of a JSON `STATE all 1` body instead of this machine's readings, re-read whenever the file changes. For the layouts the sensors will not produce: the red end of the gauge ramp, a three-digit temperature, a column with no reading. Picture **only** - while anything is pinned the loop sends no metrics blob at all and `--state-every` is refused out loud, so the panel is never handed a number this machine did not measure. Fixtures in `tools/metrics/`, watched windows and wire sizes under "Notes and known limits" |
| `--no-sleep` | set the panel's idle timeout to 0 so it never blanks the screen (default: vendor's 60 s) |
| `--session-max N` | renew the serial session every N uploads (default 500, 0 = never) |
| `--session-ttl N` | also renew it every N seconds of session life (default 300, 0 = never) |
| `--socket PATH` | where to listen for control requests while drawing. Default: `$XIGMA_SOCKET`, else `$XDG_RUNTIME_DIR/xigmalcd.sock`, else `/run/user/UID`, `~/.local/run`, `/tmp/xigma-UID.sock`. The directory is created 0700 and the socket chmodded 0600, and the peer's uid is checked with `SO_PEERCRED`. See "Two processes, one port" |
| `--no-control` | do not listen on a control socket at all (also implied by `--once`: a single frame has nothing to control, and a socket left behind by a finished run would only invite a client to knock on a dead link) |
| `--allow-reset` | let the control socket reach `recovery`, which re-enumerates the USB device and drops the stored background. Off by default; `xigmalcd-reset --yes` (in a checkout, `tools/reset_panel.py --yes`) stays the deliberate way |
| `--status` | ask the display that is already running what it is showing, print it, exit. One line on the control socket: the serial port is never opened, so this works while the loop runs. Exit 1 with "no display answering" when nothing is listening |
| `--list` | list candidate ports with their USB descriptions |
| `--export-theme NAME` | print the generated layout for one of the five drawn-from-code themes as JSON on stdout - sorted keys, byte-identical between runs. Two have a generator today (`clock`, `gauge`); asking for one that does not prints which are in and what the others still need. Nothing is written to disk, and what it prints is a layout this program draws, never something sent to the panel |
| `--check-theme NAME` | report one theme exactly as the loop will meet it: which root answered the name (ALPHA's file, or your copy of it), the file's own accounting, then what this machine's readings actually draw - boxes, lit pixels, which widgets were skipped and why, which shapes are this repo's choice rather than measured off the vendor's picture, and the sources *that theme* asks for split into answered and not. Plus the warnings worth hearing before an edit: a metric name with no entry, a font family `layout.FONTS` does not know, a `fontSize` outside the ten the shipped library uses, a colour outside `rgba()`, a widget off the canvas, an `id` repeated inside one theme, a `property` that is not the one-element list every vendor file uses. Exit 2 if the name resolves to nothing, or if the file cannot be walked at all |
| `--print-theme-fields` | print the field census an inspector is built from: all 152 widgets of ALPHA's 27 layouts answered key by key, per kind, and for each key whether `xigmalcd/layout.py` reads it, carries it without reading it (with the reason, and how many values it is ever set to), or reads it with no vendor file to show. Counted over the vendor's own trees, so an edit of yours cannot move the numbers. No port is opened |
| `--list-specials` | print the names a `special` widget may carry: the parts of our own themes that stay code-drawn and take position, size and colour from a layout |
| `--list-themes` | print everything `--theme` accepts: the five drawn from `render.py`, then ALPHA's 23 `1:1` layouts with their widget counts and which tree the file came from, then the four refused and the reason. No port is opened
| `-v, --verbose` | log every frame in both directions |

### ALPHA's layouts as a picture

`--theme` now speaks two vocabularies, and the difference is where the pixels come from.
The five named themes are drawn by code in `render.py`. Any other accepted name is one of
ALPHA's copied layout files, painted by `xigmalcd/layout.py` at the canvas the file itself
declares - and it is still one transparent `.osd` PNG per frame, because the panel is
never handed a layout file (PROTOCOL.md §11 reads the vendor app's traffic and finds no
such upload; docs/themes.md).

`--list-themes` prints the set with the numbers behind it. All of these are re-derived by
`tools/selftest.sh` in the vendor-library section, so the paragraph is a record, not a
claim:

* **23 pickable, 4 refused, and the refusal is on the file's own `ratio` field** - the
  23 declare `1:1` at 480×480, the 4 declare `4:3` at 320×240. A 320×240 layout would
  multiply the em-box anchor convention by 1.5, and that convention was measured at 480
  only. Keying the gate on `ratio` rather than on the directory name is what stops a
  future 480×480 file from being filtered out by a path rule.
* **7 metric names are asked for** over those 23 files: `CPU Temperature` 17 widgets,
  `CPU Usage` 15, `Time` 11, `Pump Speed` 9, `GPU Usage` 6, `GPU Temperature` 3,
  `CPU Frequency` 2. **14 of the 23 need nothing this program has no reading for**; the
  other 9 ask for `Pump Speed`, and no pump tachometer has ever been looked for on this
  box (`tools/fanscan.py` has never been pointed at one).
* **A widget with no reading is skipped and said so**, not drawn as a zero. Painted
  offline from one pinned metrics dict and one pinned instant, all 23 layouts draw
  something - 114 widget boxes between them on this bench, whose fonts resolve all four
  families the library names; the suite prints the face situation per machine, because a
  box with no CJK face installed drops those widgets and lands under that count - and 9
  print
  `skipped Pump Speed: no pump tachometer has been measured on this box`. The same notes
  name every face substitution (`arial` -> `LiberationSans-Regular.ttf`, `simsun` ->
  Noto Sans CJK) and every shape that is this repo's choice rather than something measured
  off the vendor's baked overlay: `Time`, `CPU Frequency`, `Pump Speed`.
* **What it uploads**, at that pinned fixture: the smallest library frame is `Theme_29`
  at 3 558 B and the largest `Theme_35` at 8 115 B, the same 256-colour PNG shape `alpha`
  uses, which README's encode A/B measured on glass at 12 169-12 401 B per frame. So a library
  theme is cheaper on the wire than our own, and nothing about the rate changes.
* A layout theme takes none of the render options (`--cold`, `--hot`, `--label`,
  `--clock-size`, `--text-color`): its geometry, colours, sizes and font faces are inside
  its file. Two flags do apply, because they are rules about the *layer* rather than about
  a theme: `--scrim`, whose plate is built from the layer's own alpha and needs no
  per-theme geometry (docs/limits.md), and `--bg black`, which makes the frame opaque so it
  covers the panel's stored background - gated both ways in the suite, opaque alpha
  (255, 255) against the same layout's transparent (0, ...)
* Over the control socket the same names work - `{"cmd":"theme","value":"Theme_07"}` -
  because one name should mean one thing in all three doors. The **window's** picker still
  lists the five: the window previews what it lists, and it cannot preview a layout yet.
  That is the editor plan in [theme-editor.md](theme-editor.md), and it is the one thing
  here that is not built.
* **The field census behind that plan is printed, not remembered**: `--print-theme-fields`.
  Its numbers go into the inspector design - 33 distinct keys across 152 widgets, 22 read,
  11 carried by the vendor's files and never read, 4 read with no vendor example - and one
  of its findings is worth knowing before anyone asks why a theme looks the same here as in
  the vendor app: the two keys that would change how text looks, `italic` and `underline`,
  are set on none of the 132 widgets that carry them.
* **`--check-theme NAME` is how you read one of these files before touching it.** It runs
  the same code path the loop runs (`themes.draw`, which is also what an editor's preview
  pane would use), and its lines are the accounting rather than a pretty print:

  ```
  Theme_28 (1757491588618): 480x480 ratio 1:1, 7 widgets, from checkout
  drawn from this machine's readings: 6 boxes, 19 253 lit px, skipped: Pump Speed
  shaped by this repo rather than measured off the vendor's picture: Time
  this theme asks for: CPU Usage, Pump Speed, Time
  this machine answers: CPU Usage, Time        and cannot: Pump Speed
  ```

  Which lines of that are stable and which are not: the first is read out of the file and
  is the same on every machine (the suite pins 23 pickable / 4 refused and every widget
  count), `skipped: Pump Speed` for those 9 themes is gated on every machine, and the box
  and pixel counts are this bench's - 19 253 lit px is from 2026-11-08, printed next to the
  machine name for exactly that reason. For one of the five it says where the drawing comes
  from: `clock: generated from render.py, 3 widgets`, and for a theme whose export is not
  built yet it says so instead of failing.
* **One theme directory is read, and one is writable, and they are the same one:**
  `~/.config/xigmalcd/themes` (`$XDG_CONFIG_HOME`). A `<name>.json` there is scanned
  **before** the checkout and before `/usr/share/xigmalcd/themes/alpha`, so an edited copy
  of `Theme_28` is what `--theme Theme_28` draws, and deleting the file puts the vendor's
  back in front - `--list-themes` and `--check-theme` both print which one answered
  ("your copy" or "checkout" or "package"). Neither `themes/alpha` in a checkout nor the
  installed `/usr/share` tree is ever written: the first is where every number in these
  docs was read from, the second is dpkg-owned and re-hashed by the install test. The five
  drawn-from-code names are refused as file names too, so there cannot be a second
  `gauge` that disagrees with `render.theme_gauge`.
* **Two of the five can be exported as data, and both are pixel-identical to the code.**
  `--export-theme clock` generates 3 widgets and 1 448 characters, `--export-theme gauge`
  5 widgets and 2 314, each byte-identical between runs, and the suite's parity gate paints
  each one both ways - through `render.py` and through `layout.draw_theme` - on four
  readings: **zero differing pixels, worst channel delta 0**, 25 548 / 25 545 / 22 944 /
  21 003 lit pixels for `clock` and 20 608 / 21 391 / 20 498 / 17 451 for `gauge`. Getting
  the gauge's ring to zero is what forced a new key into the schema, `xigma.arcPaint`: our
  ring is rasterised as 3-degree segments sampled at their start, ALPHA's measured ring as
  1-degree segments sampled at their middle, and on one arc with the same two colours that
  is 164 to 6 989 differing pixels. An export that cannot be driven to a diff of 0 is not
  shipped, so `alpha`, `bars` and `dual` stay code-drawn for now and docs/theme-editor.md
  lists what each still needs.
* **Nothing in the CLI writes a theme today.** The writer is in the library -
  `copy_for_edit`, `save`, `delete_user_theme` - and it is gated, not shipped as a flag:
  a save is atomic (tmp then `os.replace`), keeps the previous file as `<name>.json.bak`,
  emits the same shape the vendor's files are in (all 27 reproduce byte for byte from
  their own parsed content; 18 of them escape non-ASCII and 9 do not, so the writer asks
  each file which shape it is in), and refuses a name with a path separator in it. Stage 4
  of [theme-editor.md](theme-editor.md) is the window that drives it.

## Two processes, one port

`/dev/ttyACM0` allows exactly one opener (PROTOCOL.md §1), so a service keeping
the glass updated and a desktop window choosing what goes on it cannot both have
the port. The way round it is a control socket: **the display process owns the
serial line and the frame loop, and everything else is a client of it**
(`xigmalcd/control.py`, and `xigmaui/daemon.py` is the window's half).

The socket is a unix socket at `$XDG_RUNTIME_DIR/xigmalcd.sock` (see `--socket`
for the fallback chain), directory 0700, socket 0600 whatever the umask says, a
stale socket from a dead run replaced rather than treated as a conflict, and the
peer's uid checked with `SO_PEERCRED` even though the file mode already excludes
other users. That is defence against another ordinary user on this machine, and
nothing more: a process running as you could already open the port itself.

```
$ python3 -m xigmalcd --status
showing alpha at 1.0 fps on /dev/ttyACM0: 24/24 frames confirmed, 0 refused, session 24 uploads / 23 s, space=61472, last notice 200
  settings: theme alpha, canvas clear, clock 26, scrim auto, title CLI --status
  counters: 24/24 uploads the panel confirmed, 0 refused, 0 link errors, 0 session renewals, this session 24 uploads 23 s old
```

That is a real answer, taken out of `data/glass/2026-11-06-161444-socket-run.txt`: the
`--status` client ran against a display that was mid-run at 1 fps, and nothing about the
display changed because it asked.

The settings line carries one more field in the tree than it did in 0.2, and reading a
display that predates the option is worth seeing, because that is what an upgrade in
either direction looks like from the client side:

```
$ python3 -m xigmalcd --status          # tree code, against the installed 0.2 display
showing alpha at 2.0 fps on /dev/ttyACM0: 18772/18787 frames confirmed, 15 refused, session 272 uploads / 135 s, space=69084, last notice 200
  settings: theme alpha, canvas clear, clock 30, scrim auto, text theme default, title -
  counters: 18772/18787 uploads the panel confirmed, 15 refused, 0 link errors, 37 session renewals, this session 272 uploads 135 s old
```

`data/glass/2026-11-07-095918-text-color-status.txt`, and the same file has the follow-up:
asking that 0.2 display `{"cmd": "text_color", "value": "amber"}` answers
`unknown cmd 'text_color'` and leaves its status untouched, and its status carries no
`text_color` key at all. So the new client prints `text theme default` for a 0.2 display -
the *reading* is true, since that display has no ink but its theme's own, but the client
got it from a missing key rather than from an answer, and it cannot tell the two apart.
Both sides of that are the suite's to keep honest: the socket section asserts the hex
round trip against a display that does know the command.

The reply also carries the daemon's **event ring** - the last twenty things it chose to
record about the port, six of them in every status answer - and `--status` prints them
under the counters. That ring is the only way a client learns the *verdict* on a
background upload, because the socket answer on its own says only `queued` (the frame
loop owns the port and does the sending):

```
$ python3 -m xigmalcd --status      # the packaged unit on this bench, 08:09 local
  counters: 5720/5726 uploads the panel confirmed, 6 refused, 0 link errors, 11 session renewals, this session 220 uploads 109 s old
  07:51:50 queued upload: /usr/share/xigmalcd/themes/alpha/clips/theme_47.mp4
  07:51:51 background theme_47.mp4 accepted
  07:54:08 queued upload: /usr/share/xigmalcd/themes/alpha/foreground/1757492775624.png
  07:54:09 background 1757492775624.png accepted
```

What that transcript cannot tell you is what the unit had put on the panel *before*
anyone asked: its session-start background upload (07:21:58) is not in the ring, because
that upload ran in the loop before any client could have queried it and nothing noted it.
The tree has since closed that gap - the session-start upload now lands in the ring as
`background <name> accepted at session start: this is what the panel stores under our
frames` - and that is what lets `xigmaui` answer "the panel stores X" instead of
"I have not seen an accept" ([docs/gui.md](gui.md)).

One JSON object per line in each direction, and the same fields back:

| command | what it does |
|---|---|
| `status`, `config` | the loop's counters (a copy, so a client reading mid-upload never sees a counter change underneath it) and the effective settings. `refused` counts the **frame** uploads the panel threw away, whether its `1 400` came back as a notice or reached us as an exception - the two used to disagree, which is how a log with four refusals in it read `0 refused`. A refused **background** is not in that number: it is reported in the daemon's own events (`background <name> did not land`), because it is not part of the picture loop. `errors` is a streak - the consecutive failures the loop is sitting on right now, back to 0 after the next accepted frame or recovery - and not a total |
| `theme`, `fps`, `clock_size`, `bg`, `scrim`, `fans`, `title` | change the settings the loop re-reads every frame, on the daemon's own argparse object. Bounds: fps 0.1-5.0, clock 8-120, scrim 0-255 or `auto`. `fans` is one switch with the daemon's two effects - the line on the picture and the `fans` array in the metrics blob |
| `text_color` | the ink of the glyphs the display draws: `{"cmd": "text_color", "value": "#ff4040"}`, a palette name, or `null`/`""`/`"default"` to go back to the theme's own skin. `status` and `config` answer with the hex it kept, which the client can send straight back. A bad value comes back `{"ok": false, "error": "text colour 'cerise' is not something I can read: try #rrggbb (like #ff4040), one of amber black cyan …"}` and changes nothing. It is **not** a port action, so it deliberately takes no slot in the event ring - that ring is where a client reads "the panel stores X", and spending its six published entries on a colour choice would push real port evidence out of them. A display from 0.2 answers `unknown cmd 'text_color'`, refused rather than misapplied (`data/glass/2026-11-07-095918-text-color-status.txt`) |
| `pause`, `resume` | nothing goes out on the wire while paused, so the panel keeps the last picture it was given. `resume` re-helloes, and re-opens the port if the pause outlasted `--session-ttl`, which is the clock the measured silence arrives on (§9). A short pause only needs the hello, which is also what wakes a blanked panel |
| `upload PATH`, `frame` | **queued, not performed**: the server thread leaves one request in a one-slot slot and the frame loop - the only thread that touches the port - carries it out on its next iteration. A second upload while one is waiting is refused rather than stacked |
| `reset` | refused unless the daemon was started with `--allow-reset` |
| `quit`, `stop` | refused: stopping the display is `systemctl --user stop xigmalcd`, which is reversible in a way a menu click is not |

What it refuses, and why that is written into the server rather than left to the
client:

* **anything firmware-shaped.** `.zip`, `.bin`, `.img`, `.tar`, `.gz`, `.hex`,
  `.elf` are refused by name and the refusal says why: the update path is
  `type: "firmware"` (§7), which nothing in this project sends, and a socket must
  not become a route to it. Files over 8 MB are refused as past the largest thing
  the vendor app has ever pushed here (3.4 MB); only `.mp4`, `.png` and `.osd` are
  accepted, and an empty file is a mistake rather than a picture.
* **`recovery` by default**, because it re-enumerates the USB device and clears
  the stored background (§9). `Link`'s own destructive guard is decided when the
  port is opened, so a daemon started without `--allow-reset` cannot reach that
  even from its own loop thread.
* **a refusal is never reported as silence.** Both the client and the window
  distinguish "the display answered `no`" from "nothing is listening", because
  those mean opposite things and are cured by opposite things.

`--status` is the same client from the command line, and `tools/selftest.sh`
exercises the socket end to end: bounds, the one-slot queue, the `.zip` refusal,
the `reset` refusal, junk from a client, a second daemon refused on a live socket,
a failed run leaving no socket behind, and the window driving a display over a
real socket with the serial layer absent. Cost, measured there: the window's
Apply button, six socket commands, in **1 ms** - a control command never waits on
the panel, because the daemon's server thread only touches in-process state.

The gap worth knowing about: **nothing here has been run for hours.** Five 520 s windows
at 1 fps have now been driven through the socket on real glass to their own end, each
renewing its session at `--session-ttl` (300 s) and carrying on drawing - 496 of 496
confirmed, 492 of 496, 496 of 496, 498 of 498, and 496 of 498 in the one run after the
alpha theme's gauge rings went in; PROTOCOL.md §9 and §11. That is past the ~370 s at which an
unrenewed session
goes silent.
A sixth window was watched and stopped by hand at 5 min, so it counts for the phases it
reached and not for duration. Beyond that nothing has been measured: no run has been left
up overnight, and no session has been left paused past its `--session-ttl`, which is the
case that needs the port reopened rather than the hello. `journalctl --user -u xigmalcd` is
where a long run would first be seen.
