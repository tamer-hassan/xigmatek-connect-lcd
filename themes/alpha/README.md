# `themes/alpha` — the vendor's own themes, copied out of ALPHA

This is XIGMATEK's theme library for the Connect 360, taken byte for byte out of the
shipped Windows app and unpacked.  Not a re-creation, not a guess at what the themes
look like: 27 layout files as the app stores them, the 44 video clips the app ships
beside them, the 27 baked overlay PNGs the app renders for them, and a `manifest.json`
hashing every one of those 152 files.

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
| result | `python3 tools/thm_unlock.py --from "/media/windows-c/Program Files/ALPHA/resources/static/theme/butt" --to themes/alpha --write` |

No file outside this repo was created or changed.  The write is idempotent: re-running
it re-derives every byte and reports `kept` (126 `kept`, 0 `wrote` on the last such
run), so a second run is a check rather than a rewrite.

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

## What is in this directory

| dir | files | bytes | what it is |
|---|---|---|---|
| `thm/` | 27 | 66 300 082 | the `.thm` files as shipped, untouched — the primary artifact |
| `layouts/` | 27 | 127 115 | decrypted layouts, `{480X480,320X240}/<themeId>.json` |
| `clips/` | 44 | 84 392 330 | every loose clip the installer ships (43 `.mp4`, 1 `.png`) |
| `foreground/` | 27 | 407 095 | the baked overlay PNG each theme embeds |
| `manifest.json` | 1 | 70 398 | sha256 + byte count + vendor path for all of the above |

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
themes/alpha: 152/152 files match manifest hashes (verified)
  counts {'background': 27, 'clip': 44, 'foreground': 27, 'layout': 27, 'thm': 27}
  layout media references resolved: 54
  theme backgrounds: 27, of which 27 are held by a loose clip of the same bytes
```

That needs no Windows volume: it re-hashes what is in the tree against what
`manifest.json` recorded when the bytes were read.  `tools/selftest.sh` runs it.

## The 27 themes

Widget counts read off the layouts; clip facts from `ffprobe`
(`python3 tools/theme_previews.py --ratio 480X480`).  The vendor's own material is not
30 fps: the 40 square clips are H.264 `yuv420p` at **20 or 24 fps** — every `Theme_NN`
file is 24 fps except `Theme_35.mp4` (20), every `theme_NN` file is 20 fps except
`theme_38`/`theme_51`, which are 24-fps byte-twins of `Theme_27`/`Theme_29`.  That
answers the rate question PROTOCOL.md §6 raises.  `fg` is the baked overlay PNG's size
in bytes.

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

## How ALPHA itself holds these at runtime

Worth recording, because it is how the app's live state connects to this directory.
`%APPDATA%\alpha\store.json` keeps `presetTheme[]`: 27 entries, and their ids
(`1785506774334` … `1785506775818`) are **not** the ids of the `.thm` files — the app
re-instantiates its own library at install time.  Pairing them by exact widget properties
(one-to-one, canvas included): **27 of 27 presets match one shipped layout exactly**, in
the same order (presets 0–3 are the four 320×240 themes, presets 4–26 the 23 480×480
ones, `default.thm` at index 4).

That resolves a loose end in `xigmalcd/render.py`: this panel's
`devicesInfo.BYZL24…currentThemeId` is `1785506775818`, i.e. `presetTheme[26]`, and its
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

Not yet: **a renderer that draws these layouts live.**  That is the open work — walk
`osd.widget[]`, place `text`/`data` at `x`,`y` with the layout's own `fontSize` and
`textColor`, fill `bar` between `minValue`/`maxValue` with the layout's `startColor` →
`endColor` over its `bgColor`, sweep the `arc` from `angleStart` to `angleEnd`, and feed
it `sensors.py` instead of the app's metrics.  The primitives (arc, gauge, bar, text and
the font loader) are already in `xigmalcd/render.py`; the alpha theme there is a
hand-drawn reproduction of one of these layouts, not a general layout interpreter.

Fonts are a known substitution, and it is a real difference, not a cosmetic one: **this
box has no Microsoft fonts.**  `Arial` → Liberation Sans (metric-compatible), `simsun`
and `宋体` → Noto Sans CJK, `Verdana` → DejaVu Sans.  Liberation Sans matches Arial's
advance widths, so text placement survives; Verdana is wider than DejaVu Sans, so a
`Verdana` widget may ink a few pixels differently.  Whether the difference is visible on
a 480×480 1-inch panel is an eye question, and no eye has seen it yet — the substitution
is not on the wire.

Vendor `path` strings inside every theme point at
`C:\Users\Administrator\AppData\Roaming\alpha\…` — the vendor's own build machine user,
kept verbatim as provenance.  The runtime store quoted above carries paths under
`C:\Users\Tamer\…`, which is this machine, and stays on the Windows volume: nothing from
`%APPDATA%` (logs, caches, 216 MB) was copied here.
