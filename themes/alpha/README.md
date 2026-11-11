# `themes/alpha` — the vendor's own themes, copied out of ALPHA

This is XIGMATEK's theme library for the Connect 360, taken byte for byte out of the
shipped Windows app and unpacked.  Not a re-creation, not a guess at what the themes
look like: 27 layout files as the app stores them, the 44 video clips the app ships
beside them, the 27 baked overlay PNGs the app renders for them, and a `manifest.json`
hashing every one of those bytes — 100 files here, 125 manifest entries (27 of them
`background` records naming the same bytes as 27 of the clips), plus 27 more entries
for the vendor's own encrypted `.thm` containers, which this directory **does not
carry** and records only by size and hash.  See "The `.thm` containers" below.

Why it matters for this project: **the panel never sees any of this.**  PROTOCOL.md §10
records that across all eight of ALPHA's own logs the app uploaded only two kinds of
media — `.osd` (the composite PNG, 11 191 times) and `.mp4` (the background, 10 times) —
and never a layout file.  So the box on the cooler does not know what a gauge is; the
drawing happens in the app, per second, and the panel just shows the PNG.  Anything this
repo shows on that glass is therefore ours to draw, and this directory is the reference:
the coordinates, colours, fonts, sources and motion the vendor actually uses.

Everything here was **read**, never sent.  Nothing in this directory goes on the wire by
itself; uploads still follow PROTOCOL.md §6.

## Where it came from, and how it was unpacked

| | |
|---|---|
| read on | 2026-11-07, from the Windows system volume mounted at `/media/windows-c` |
| themes | `Program Files/ALPHA/resources/static/theme/butt/{480X480,320X240}` — 23 files (incl. `default.thm`) + 4, 64 MB |
| clips | `Program Files/ALPHA/resources/static/media` — 43 `.mp4` + 1 `.png`, 81 MB |
| tool | `tools/thm_unlock.py` |
| result | `python3 tools/thm_unlock.py --from "/media/windows-c/Program Files/ALPHA/resources/static/theme/butt" --media "/media/windows-c/Program Files/ALPHA/resources/static/media" --to themes/alpha --write --no-thm` |

No file outside this repo was created or changed.  The write is idempotent: re-running
it re-derives every byte and reports `kept` (**99 `kept`, 0 `wrote`** on the last such
run, 2026-11-07), so a second run is a check rather than a rewrite.  Every byte in the
`--no-thm` form above was produced by the same code path that produced the bytes this
directory used to carry: re-running it over the pre-removal tree matched 98 of the 98
data files and the 125 manifest entries this tree keeps, key for key, with nothing else
changed.

### The container, and the cipher

A `.thm` is a ZIP holding exactly one entry, `<themeId>.json`; that entry is **hex
text**; those bytes are **AES-256-CBC, PKCS#7 padded**, with

```
key = sha256("Byyeetek2368")                  32 B
iv  = 427979656574656b427979656574656b        16 B  ("ByyeetekByyeetek")
```

PROTOCOL.md §10 used to say these layouts "are not readable without the app's key".
That was wrong, and it was wrong in the interesting direction: the key is in the app in
plain sight.  `resources/app.asar` → `out/main/index.jsc` is V8 bytecode, and a bytecode
cache keeps its string constants, so `strings` reads them out (`tools/asar_extract.py`
unpacks the archive, no node needed):

```
aes-256-cbc   createCipheriv   createDecipheriv   createHash   sha256   digest
Byyeetek2368   427979656574656b
"Invalid theme zip file: should contain exactly one JSON file"
```

The passphrase is the first string, the IV is the second **twice** (the 8-byte constant
repeated to fill a block).  The IV was not guessed: decrypting block 0 of the ciphertext
in ECB mode and XORing the result against the known first 16 plaintext bytes — `{"id":`
plus the digits of the theme id, which the ZIP entry's own name gives — yields the IV.
Four different files returned the same 16 bytes that way, and all 27 then decrypted to
JSON that parses.  Padding is checked (PKCS#7, all 27 clean).

Decrypted, a theme is one JSON object:

```json
{"id": 1757491588836, "width": 480, "height": 480, "ratio": "1:1", "screenStatus": "butt",
 "background": {"type": "MP4", "path": "C:\\Users\\Administrator\\...\\1757491588831.mp4",
                "pathData": "<base64 of the whole clip>"},
 "osd":        {"path": "C:\\Users\\Administrator\\...\\1757491588831.png",
                "pathData": "<base64 of the baked overlay PNG>",
                "widget": [ ... ]}}
```

`pathData` is the media itself, so a `.thm` is self-contained.  Two facts, both verified
on all 27, are what make the copy below checkable instead of claimed:

* every embedded background is byte-identical to a clip the installer ships loose in
  `resources/static/media` — **27 of 27, 0 unique to the `.thm`**;
* every embedded overlay PNG is byte-identical to a PNG the running app left in
  `%APPDATA%\alpha\media\foreground` — **27 of 27**, 26 distinct blobs (two themes,
  1757491589004 and 1757491589687, carry the same PNG under two names).

## The `.thm` containers are recorded, not carried

The tree used to hold the 27 `.thm` files themselves (`thm/`, 27 files, 66 300 082 B —
64 MB, over 40 % of this directory).  They are **gone since 0.3**: they are the vendor's
encrypted container, they are the one part of this copy nothing here reads or could send,
and everything they were evidence *for* — the container format, the cipher and its
constants, each theme's layout, the fact that all 27 embedded backgrounds equal a loose
clip and all 27 embedded overlays equal a PNG the running app left in `%APPDATA%` — is
already in the open in this directory and in PROTOCOL.md §10.  What is kept of the
containers is their identity: `manifest.json` has a `notRedistributed` array with vendor
path, byte count and sha256 for all 27, and every row of `themes[]` carries
`thmFile`/`thmVendorPath`/`thmBytes`/`thmSha256` (the `.thm` column of the table below is
that field, and it still identifies the source file of each layout).

A reader who wants the originals installs the vendor's own software; that is where they
come from, and it is where this copy was read from:

```
https://www.xigmatek.com/wp-content/uploads/files/Connect-Display-Setup-Software-2025-1125.zip
```

which puts them at `Program Files/ALPHA/resources/static/theme/butt/{480X480,320X240}` —
the directory `--from` takes.  With that volume mounted, the hashes in this manifest are
checked rather than asserted:

```
python3 tools/thm_unlock.py --verify --to themes/alpha \
  --from "/media/windows-c/Program Files/ALPHA/resources/static/theme/butt"
```

## What is in this directory

| dir | files | bytes | what it is |
|---|---|---|---|
| `layouts/` | 27 | 127 115 | decrypted layouts, `{480X480,320X240}/<themeId>.json` |
| `clips/` | 44 | 84 392 330 | every loose clip the installer ships (43 `.mp4`, 1 `.png`) |
| `foreground/` | 27 | 407 095 | the baked overlay PNG each theme embeds |
| `manifest.json` | 1 | 78 072 | sha256 + byte count + vendor path for all of the above, plus the 27 `.thm` containers this directory does not carry |

100 files.  The 98 the tool writes come to **84 926 540 B**, and that is the figure
quoted elsewhere in this repository, because it is a stable one: the manifest records it,
so it does not move when this README is edited (the other two files are the manifest and
this README, and nothing pins their sizes: `du -b manifest.json README.md` reads them).
`thm/` is not in any of those totals because it is not here; its 27 entries are in the
manifest, hashed.

Two deliberate choices:

* **The layouts do not carry base64.** `pathData` is replaced with `mediaFile`, a path
  inside this directory, so a layout is a readable document and the bytes live once.
* **There is no `background/` dir.** Since all 27 embedded backgrounds equal a loose
  clip, the clip holds the bytes and the layout points at the clip.  That is 43 179 923 B
  of duplicated video not written.  `manifest.json` still records each theme's own
  `backgroundSha256`, and `--verify` re-hashes the clip it points at, so the aliasing is
  checked, not assumed.  A theme whose background had no loose twin would have gotten its
  own file under `background/`; none did.

Three clips are also vendored at the repo root (`media/Theme_11.mp4`,
`media/Theme_25.mp4`, `media/theme_48.mp4`) because the CLI flags and docs name those
paths.  They are byte-identical to `themes/alpha/clips/` of the same names, e.g.
`Theme_25.mp4` is `39de20f0db3ca543bade61cd569550223940d0b9dd735c6f247c7014a204c76d`
in both places.

### Re-checking it, offline

```
python3 tools/thm_unlock.py --verify --to themes/alpha
```

```
27 files recorded and NOT redistributed (the vendor's encrypted .thm originals); not checked here — add --from DIR to re-hash them
themes/alpha: 125/125 files match manifest hashes (verified)
  counts {'background': 27, 'clip': 44, 'foreground': 27, 'layout': 27}
  layout media references resolved: 54
  theme backgrounds: 27, of which 27 are held by a loose clip of the same bytes
```

That needs no Windows volume: it re-hashes what is in the tree against what
`manifest.json` recorded when the bytes were read.  `tools/verify_manifest.py` runs it.  With
the vendor volume mounted the same command takes `--from DIR` and re-hashes the 27
containers where they live, printing `152/152 files match manifest hashes (verified)` —
measured that way on the author's bench on 2026-11-07, which is what keeps the record of
files this tree does not carry from going stale.

## The 27 themes

Widget counts read off the layouts; clip facts from `ffprobe`
(`python3 tools/theme_previews.py --ratio 480X480`).  The vendor's own material is not
30 fps: the 40 square clips are H.264 `yuv420p` at **20 or 24 fps** — every `Theme_NN`
file is 24 fps except `Theme_35.mp4` (20), every `theme_NN` file is 20 fps except
`theme_38`/`theme_51`, which are 24-fps byte-twins of `Theme_27`/`Theme_29`.  That
answers the rate question PROTOCOL.md §6 raises.  `fg` is the baked overlay PNG's size
in bytes.

The `.thm` column names the container each layout came from (`thmFile` in
`manifest.json`, alongside its vendor path and sha256); the file itself is not here, see
above.

| theme id | `.thm` | clip | fps | frames | dur s | widgets | fg |
|---|---|---|---|---|---|---|---|
| 1757491588836 | `default.thm` | `Theme_35.mp4` | 20 | 101 | 5.05 | arc 1, data 2, text 2 | 26 389 |
| 1757491588063 | `theme_1757491588063.thm` | `Theme_34.mp4` | 24 | 261 | 10.88 | data 2, text 2 | 14 107 |
| 1757491588126 | `theme_1757491588126.thm` | `Theme_01.mp4` | 24 | 120 | 5.00 | bar 1, data 3, text 4 | 17 206 |
| 1757491588315 | `theme_1757491588315.thm` | `Theme_33.mp4` | 24 | 480 | 20.00 | data 1, text 2 | 12 957 |
| 1757491588497 | `theme_1757491588497.thm` | `Theme_14.mp4` | 24 | 480 | 20.00 | data 3, line 2, text 2 | 15 710 |
| 1757491588618 | `theme_1757491588618.thm` | `Theme_28.mp4` | 24 | 397 | 16.54 | bar 1, data 2, text 4 | 19 137 |
| 1757491588804 | `theme_1757491588804.thm` | `Theme_07.mp4` | 24 | 423 | 17.62 | bar 2, data 3, text 3 | 21 035 |
| 1757491588891 | `theme_1757491588891.thm` | `theme_52.mp4` | 20 | 202 | 10.10 | data 2, text 1 | 16 181 |
| 1757491588945 | `theme_1757491588945.thm` | `theme_40.mp4` | 20 | 202 | 10.10 | bar 2, data 3, text 3 | 18 572 |
| 1757491589004 | `theme_1757491589004.thm` | `theme_39.mp4` | 20 | 202 | 10.10 | data 1, text 2 | 12 141 |
| 1757491589113 | `theme_1757491589113.thm` | `theme_37.mp4` | 20 | 467 | 23.35 | bar 1, data 2, text 3 | 17 814 |
| 1757491589217 | `theme_1757491589217.thm` | `Theme_27.mp4` | 24 | 239 | 9.96 | data 1, text 2 | 11 716 |
| 1757491589247 | `theme_1757491589247.thm` | `Theme_25.mp4` | 24 | 23 | 0.96 | data 3, text 2 | 15 111 |
| 1757491589325 | `theme_1757491589325.thm` | `Theme_30.mp4` | 24 | 130 | 5.42 | bar 1, data 3, text 4 | 18 841 |
| 1757491589401 | `theme_1757491589401.thm` | `theme_36.mp4` | 20 | 272 | 13.60 | data 2, text 2 | 14 297 |
| 1757491589484 | `theme_1757491589484.thm` | `Theme_29.mp4` | 24 | 360 | 15.00 | data 2, text 1 | 13 562 |
| 1757491589554 | `theme_1757491589554.thm` | `theme_41.mp4` | 20 | 253 | 12.65 | bar 1, data 2, text 3 | 18 213 |
| 1757491589585 | `theme_1757491589585.thm` | `theme_45.mp4` | 20 | 70 | 3.50 | data 2, text 1 | 12 787 |
| 1757491589611 | `theme_1757491589611.thm` | `theme_46.mp4` | 20 | 109 | 5.45 | data 3, line 2, text 2 | 14 844 |
| 1757491589687 | `theme_1757491589687.thm` | `theme_47.mp4` | 20 | 185 | 9.25 | data 1, text 2 | 12 141 |
| 1757491589759 | `theme_1757491589759.thm` | `theme_48.mp4` | 20 | 217 | 10.85 | bar 1, data 2, text 4 | 20 393 |
| 1757491589804 | `theme_1757491589804.thm` | `theme_49.mp4` | 20 | 63 | 3.15 | data 2, text 2 | 14 832 |
| 1757491589871 | `theme_1757491589871.thm` | `theme_50.mp4` | 20 | 194 | 9.70 | bar 2, data 3, text 3 | 18 542 |

The 320×240 library (a different panel, kept because it is what ALPHA ships for it and
because it is the only place the app's Chinese labels appear):

| theme id | clip | fps | frames | dur s | widgets | fg |
|---|---|---|---|---|---|---|
| 1757492775547 | `2024-05-30_13-43-24-476.mp4` | 20 | 69 | 3.45 | bar 1, data 5, text 4 | 8 183 |
| 1757492775574 | `2024-05-30_14-09-30-913.mp4` | 20 | 75 | 3.75 | data 5, text 3 | 12 669 |
| 1757492775603 | `2024-05-31_15-01-03-396.mp4` | 20 | 42 | 2.10 | bar 2, data 2, text 2 | 6 306 |
| 1757492775627 | `2024-05-31_15-00-10-394.png` | still | — | — | data 4, text 1 | 3 409 |

Canvases: 23 themes 480×480 (`ratio: "1:1"`), 4 themes 320×240 (`ratio: "4:3"`); all 27
`screenStatus: "butt"`.  One 320×240 theme uses a **still PNG background**, and that PNG
is 960×720 — larger than its panel, so the app scales it itself.

`docs/previews/alpha-themes-480X480.png` and `-320X240.png` are the visual proof: each
theme composited from the vendor's own baked overlay over a frame lifted from the
vendor's own clip — the vendor's compositing model, not our drawing.  Reproduce with
`python3 tools/theme_previews.py`.

17 of the 44 clips belong to no shipped theme — `2.mp4`, `3.mp4`, `8.mp4`, `9.mp4`,
`Theme_11/12/13/15/16/17/22/23/24/26/31.mp4`, `theme_38.mp4`, `theme_51.mp4` — and three
pairs are byte-identical twins (`Theme_26`↔`Theme_31`, `Theme_27`↔`theme_38`,
`Theme_29`↔`theme_51`), i.e. 16 distinct clips the library does not use.  Several are
clips this repo has already streamed to the panel in its own tests (`Theme_11`,
`theme_48`), and `Theme_25.mp4` belongs to theme 1757491589247.

## The layout schema, as stored

`osd.widget[]` holds one object per widget: `id` (a UUID from the vendor's editor),
`layerIndex` (always 0 in all 27), `type`, `property` (always a one-element list) and
`widgetContent` (always `""`).  The numeric `property[0].type` is a second, redundant
tag: **0 = text, 1 = data, 2 = arc, 3 = bar, 6 = line**.  152 widgets in total:
`data` 66, `text` 66, `bar` 15, `line` 4, `arc` 1.

Keys present on every widget: `x`, `y`, `controlName` (`""` everywhere), `enableMove`
(`false`), `screenStatus` (`"butt"`), `type`.  Most also carry `canvasProperties` and
`coordBoundary` (both `{480,480}` or `{320,240}`, min 0/0 max canvas/max canvas).
Per kind, the full set actually observed:

| kind | keys beyond the common ones |
|---|---|
| `text` | `content`, `fontFamily`, `fontSize`, `textColor`, `bold`, `italic`, `underline` |
| `data` | `source`, `time`, `valueChangeType`, `fontFamily`, `fontSize`, `textColor`, `bold`, `italic`, `underline` |
| `bar` | `x`,`y`,`width`,`height`, `rotate`, `cornerRadius`, `bgColor`, `startColor`, `endColor`, `minValue`, `maxValue`, `italicAngle`, `source`, `time`, `valueChangeType` |
| `arc` | `x`,`y`, `radius`, `sizeWidth`, `sizeHeight`, `width` (ring thickness), `angleStart`, `angleEnd`, `cornerRadius`, `bgColor`, `startColor`, `endColor`, `minValue`, `maxValue`, `source`, `time`, `valueChangeType` |
| `line` | `x`,`y`,`width`,`height`, `rotate` — and **no colour at all** |

Colours are CSS `rgba(r, g, b, a)` strings, with alpha used (e.g. the arc's
`rgba(161, 246, 255, 0.5)` track).  `cornerRadius` is `0` on 13 widgets, `5` on 2 and
`false` on the arc.  `minValue`/`maxValue` are `0`/`100` on all 16 of the widgets that
carry them.  `canvasProperties` and `coordBoundary` always describe the theme's own
canvas (119 widgets at `{480,480}`, 29 at `{320,240}`, min always `0,0`).  `time` is an
epoch-ms stamp of when the vendor last edited that widget in their build (2024-05-30 …
2025-09-10, 82 stamps) — not a runtime value.

`source` values, all 82 of them, verbatim, with counts: `CPU Temperature` 22,
`CPU Usage` 16, `Time` 13, `Pump Speed` 9, `GPU Temperature` 6, `GPU Usage` 6,
`CPU Frequency` 3, `Date` 3, `GPU Power` 1, `CPU Power` 1, `Upload Speed` 1, `Week` 1.
No `data` or `bar` widget in any of the 27 reads a fan, RAM or disk metric — the editor
offers them (PROTOCOL.md §10) and the shipped library does not use them.

Fonts, verbatim: `Arial` 115, `simsun` 13, `Verdana` 3, `宋体` 1.  `Arial` is everything
on the 480×480 themes except three `Verdana` widgets.

Static `text` content — 18 distinct strings, 21 if you count the two libraries
separately, since `CPU`, `CPU TEMP` and `GPU` appear in both — kept exactly as the vendor
typed them, which includes their typos: they are evidence and are not corrected here.
Both `Smart Display` (480×480) and `Smart Dispaly` (320×240) ship.

```
CPU        CPU CLOCK    CPU TEMP    CPU USED    Cloud        GPU      GPU USED
Smart Display   TEMP    USED    WHITE CLOUD    ↑CPU      ↗CPU TEMP
(320X240 only)  ALPLA   CPU   CPU TEMP   GPU   Smart Dispaly   上传速度   使用率   频率
```

What the layouts do **not** say, and where the answer comes from instead:

* **a `line` widget's colour** — none of the four carries one.  The colour is only in the
  baked overlay PNG.
* **how a `data` value is formatted** — no unit, no format string, no decimals field.
  `°C`, `%`, `GHz`, `RPM` are implied by `source` and appear only in the baked PNG.  The
  formats and the anchor convention (`x`,`y` is the top of the em box, which is Pillow's
  `la`) were measured off the vendor's own preview PNGs and are written up in
  `xigmalcd/render.py`; that is also where the bar geometry (`(x,y)` is the track's
  top-left, `280 × 10` for the current theme's bars) was measured.
* **whether the value is clamped** — `minValue`/`maxValue` are given (bars 0–100; the one
  arc 0–100), nothing says what happens outside them.

### The one `arc`, measured against the app's own frames

The library holds exactly one `arc`: `layouts/480X480/1757491588836.json`
(`default.thm`), `source CPU Temperature`, `minValue`/`maxValue` `0`/`100`.  It is also the
theme the app was displaying while its COM3 traffic was watched, so its own uploads are a
recording of that arc being drawn — 65 overlays in one session, 23 more in the session that
starts at power-on, each a 480×480 RGBA PNG of 24–25 KB.  Every number a renderer needs is
measured out of those frames by `tools/theme_check.py --arc`:

| the layout says | what the app painted | the rule that follows |
|---|---|---|
| `angleStart` 45, `angleEnd` 315 | ink from 135° to 405° in the angles a raster arc takes (0° at 3 o'clock, growing towards 6 o'clock) | the app's 0° is the **bottom** of the circle and grows the same way the raster's does: `pil = app + 90` |
| `x` 107, `y` 106, `sizeWidth`/`sizeHeight` 260 | the ring's ink box ends at x=367 | `x`,`y` is the **top-left of the box**, not the centre |
| `radius` 110, `width` 20 | a stroke band 19.75–20.50 px wide whose centre sits at radius 119.38–121.00 px, probed along 53 rays (ours: 120.00–120.62) | `radius` is the **inner** edge, `width` the stroke; the band is where `radius + width/2` puts it, and the vendor's own rasterisation is the noisier of the two, by ±0.75 px |
| a 270° sweep, `cornerRadius: false` | ink reaches offset 270 and stops dead at 271, and there is none at −1 | both ends are **butt caps, at the declared angle**: the fill's near edge crosses half of its own coverage at **+0.015°** in all 88 frames |
| `minValue` 0, `maxValue` 100 | the fill's far edge at 113.14 / 115.87 / 118.48 / 121.32 / 124.01 / 126.68 / 129.44 / 135.06 / 140.20 / 145.75 / 151.15° for the frames painting 42 / 43 / 44 / 45 / 46 / 47 / 48 / 50 / 52 / 54 / 56, and 153.90 / 156.45 / 159.30 / 161.94 / 164.79 / 167.44° for 57 / 58 / 59 / 60 / 61 / 62 | `(value − min) / (max − min) × sweep`, clamped — worst residual **0.32°** over both captures. The slope needs no reading at all: 13.541° across five one-unit steps is **2.7082°/unit** where the layout declares 2.7000 |

Two things about that table are methods, not results, and they are worth stating because
they are what makes the numbers fair.  Every crossing above is an **alpha crossing at half
of that side's own plateau** — the fill plateaus at 255, the unfilled track at 128 — never an
ink/not-ink threshold, because a threshold is a property of the threshold.  And the pairing
of frame to value is **reading-free**: frames are grouped by the exact pixels they paint for
the arc's own `source`, so each group carries one ring stop, and the digit that stop carries
was then read off a contact sheet (`--digits`) **by eye** — wherever a digit from this table
is quoted elsewhere in this repo it is labelled as a reading, not a measurement.

One frame does not fit the rule, and it is the first frame of the power-on session:
`2026-11-05_07-21-36-052.osd` paints `57°C` with its fill at **135.06°**, where every other
frame painting 57 sits at 153.90°.  The ring was still animating up to its value; the digits
were already there.

**The fill's colour is not the lerp the fields suggest.**  `startColor` is
`rgba(0, 247, 255, 1)`, `endColor` `rgba(0, 255, 113, 1)`, and a renderer that interpolated
one into the other along the sweep would be wrong by up to 17/255 per channel.  Sampling
along the middle of the stroke (radius 116/120/124, alpha 250+ only, averaged over every
frame that reaches the degree) says the colour is a function of the **angle alone** — across
the stroke it varies by ≤2/255, and it does not move with the value at all, which only
decides how far the fill runs.  What the app actually paints: `startColor` held exactly to
32°, ramping 33°→120° down to `rgb(0, 251, 184)`, then flat at `rgb(0, 251, 184)` from 121°
to 165°, the deepest either session ever filled.  **`endColor` appears in no frame of
either capture**, so 166°..270° is a gap and not a plateau: `xigmalcd/layout.py`
`ARC_COLOUR_MEASURED` carries the 22 sampled degrees (reproducing the vendor's pixels at
worst 2.4/255, mean 0.09, against 16.9 worst / 2.97 mean for the straight lerp), it is keyed
by the declared colour pair so it can only ever apply to the theme it was measured on, and
any other pair falls back to the lerp with `draw_arc` saying so out loud.

The unfilled part of the sweep is painted, not left empty: a flat
`rgba(161, 246, 255, 0.5)` track, and its coverage reads exactly **128** — the declared 0.5
alpha, so the app rounds half up.  It runs at the same 20 px width as the fill, to the end of
the sweep.

None of this is on the wire yet: `xigmalcd/layout.py` is the interpreter and
`tools/theme_check.py` is the ruler, and the loop that feeds the panel still draws the
hand-made `alpha` theme in `xigmalcd/render.py`.  See "What is reproduced here" below.


## How ALPHA itself holds these at runtime

Worth recording, because it is how the app's live state connects to this directory.
`%APPDATA%\alpha\store.json` keeps `presetTheme[]`: 27 entries, and their ids
(`1785506774334` … `1785506775818`) are **not** the ids of the `.thm` files — the app
re-instantiates its own library at install time.  Pairing them by exact widget properties
(one-to-one, canvas included): **27 of 27 presets match one shipped layout exactly**, in
the same order (presets 0–3 are the four 320×240 themes, presets 4–26 the 23 480×480
ones, `default.thm` at index 4).

That resolves a loose end in `xigmalcd/render.py`: the store's
`devicesInfo` entry for this panel (keyed by its serial number, which is redacted
throughout this repo) has `currentThemeId` `1785506775818`, i.e.
`presetTheme[26]`, and its
eight widgets are the ones in `layouts/480X480/1757491589871.json` (bar 2, data 3,
text 3, bars at 100,330 and 100,400 sized 280×10 in `rgba(192, 66, 255, 1)` →
`rgba(143, 78, 255, 1)` over a `rgba(196, 162, 255, 1)` track) — the numbers that page's
`alpha` theme draws.  That theme ships with `theme_50.mp4`, but this panel's
`currentThemeBg` is `media\background\Theme_25.mp4`, which is why the store pairs a
`Theme_25` clip with those widgets: the background was changed on its own
(the app has `changeThemeBgBySn` for exactly that).  The store's own copy of the overlay
PNG is *not* the one in the `.thm` — the app re-renders a preview when it imports.

## What is reproduced here, and what is not

Reproduced: the files themselves, their container, their schema, and the vendor's
compositing (previews above).

**A layout interpreter now exists: `xigmalcd/layout.py`.**  It walks `osd.widget[]` and
draws `text`/`data` at `x`,`y` with the layout's own `fontFamily`, `fontSize`, `bold` and
`textColor`, fills `bar` from `minValue`/`maxValue` with `startColor` over `bgColor`, sweeps
the `arc` exactly as measured above, and returns `(image, notes)` where the notes name every
font it substituted, every `source` it had no value for, and every gap it had to guess at.
`tools/theme_check.py` is the ruler that keeps it honest, drawing a copied layout and
comparing it, in pixels, against pictures the vendor drew itself.

What is **not** done: it is not wired to the panel.  The loop that feeds the display still
draws the hand-made `alpha` theme in `xigmalcd/render.py`; `xigmalcd` has no
`--theme-file` switch.  Running a copied theme is therefore a claim about offline PNGs, and
nothing in this repo has put one on the glass.

Three holes in the schema are still open, and each says what it is waiting for:

* **the text a `data` widget paints** — `Time` as `HH:MM` or `HH:MM:SS`, `Week` in which
  language, `kb/s` or `KB/s`, how many decimals on a frequency.  The layouts never say, the
  panel is never given the text (PROTOCOL.md §8: the metrics blob is numbers only), and the
  formats live in the app's V8 bytecode — reachable through the `d8` + View8 route of
  PROTOCOL.md §10 but not yet read out of it.  `layout.FORMATS_MEASURED` carries what has
  been read off the vendor's own baked overlays and marks the rest as a choice made here.
* **a `line` widget's colour and thickness** — still not in the JSON, so the answer came
  from the pictures instead.  The four live in two themes (`Theme_14`, `theme_46`), and
  their own baked overlays (`foreground/1757491588481.png`, `foreground/1757491589608.png`)
  show the stroke as **rgba(240, 255, 255, 255)** — alpha 255 on all 798 pixels of the pair,
  hard-edged, no antialiasing.  The renderer bundle's default (`lineColor:
  "rgba(19, 206, 102, 1)"`, `lineWidth: 2`, `maxTickCount: 10`) is a green no shipped theme
  is observed to draw, so `layout.MEASURED_LINE_INK` carries the measured ink and the green
  stays in the comment.  The thickness turned out to be `height` itself, not `lineWidth`:
  the horizontal widget lights exactly x 115..364 (its declared `width`, 250 px) by
  y 230..231 (its declared `height`) and nothing at y 229 or 232.  And `rotate` turns the
  rect **about its own centre** — x165 y305 width150 height2 at `rotate: 90` lands at
  x 239..240, y 231..380, while a top-left corner pivot would have left it at x=165 and the
  overlay lights 29 pixels there that the centre rects do not explain.  `draw_theme` still
  records `"line colour"` as a gap, because for a `line` in some file nobody has a picture
  of, the ink is still this program's choice.
* **`arc` colour past 165° of the sweep**, and for any `startColor`/`endColor` pair other
  than the one measured above: there it falls back to a straight lerp and says so.

Fonts are a known substitution, and the measurement of it is now in the open rather than in
a hunch.  **This box has no Microsoft fonts**, so `Arial` → Liberation Sans, `simsun` and
`宋体` → Noto Sans CJK, `Verdana` → DejaVu Sans.  Over all **66 static `text` widgets in the
27 themes, all 66 were compared and none was unresolvable** (`tools/theme_check.py`, which
compares ink boxes and ink *coverage* — sum of alpha over 255 — inside the widget's declared
window):

| declared | drawn with | ink box, ours minus the vendor's | ink coverage, vendor vs ours |
|---|---|---|---|
| `arial` 12 / 16 / 20 / 24 / 40, regular | Liberation Sans | width −4…+0 px, height −4…+1 px | 26 354 vs 21 536 |
| `arial` 14 (the two widgets that hold CJK) | Liberation Sans, CJK from Noto | width −13…−11 px | 419 vs 83 |
| `arial` bold 20 / 32 | Liberation Sans Bold | width **−19…−11** px, height +0…+1 px | 8 861 vs 5 939 |
| `Verdana` bold 20 | DejaVu Sans Bold | width +0 px, height +0 px | 1 167 vs 1 028 |
| `simsun` 14 / 24 / 24 bold | Noto Sans CJK | width +1…+10 px, height +0…+4 px | 1 089 vs 1 485 |

Read the columns per face, never pooled across them: Liberation Sans reproduces Arial's
advance widths for the regular faces (−4…0 px over a whole string, and the −4 of the height
column is one `↑CPU` arrow), while **bold is the real difference** — `CPU TEMP` at
`arial/32b` comes out 19 px narrower and far lighter than the vendor's (coverage 2 192
against our 1 564).  The CJK rows point the other way: where a widget holds Latin text
declared in `simsun`, Noto's Latin is wider than SimSun's (+9…+10 px), and where one holds
CJK declared in `Arial`, the vendor's fallback painted far heavier glyphs than Noto manages
at that size (`频率` at 14 px: 30×12 px and coverage 171, against our 19×10 px and
coverage 33).  And on placement, one shared rule and one gap: the vendor's ink starts
**+1…+5 px below** the declared `y` — which is what settled the anchor convention as the top
of the em box — while ours starts +2…+10 px below it, worst on CJK.  So every widget of
ours sits a little lower than the vendor's, by 1 to 5 px.

Whether any of that is visible on a 480×480 panel of about one square inch is an eye
question, and no eye has seen a copied theme on glass yet — none of this is on the wire.

Vendor `path` strings inside every theme point at
`C:\Users\Administrator\AppData\Roaming\alpha\…` — the vendor's own build machine user,
kept verbatim as provenance.  The runtime store quoted above carries paths under
`C:\Users\Tamer\…`, which is this machine, and stays on the Windows volume: nothing from
`%APPDATA%` (logs, caches, 216 MB) was copied here.
