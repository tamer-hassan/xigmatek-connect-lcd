# The theme editor, and the 27 vendor themes: the plan, with the numbers under it

**This is a plan, part of it landed.** As of 2026-11-08, stage 0's write-up (this file)
and stages 1-3 are in the tree: `xigmalcd/themes.py` finds the library and the file model
under `~/.config/xigmalcd/themes`, `--list-themes` and `--check-theme` print
it with the counts, `--theme <background name>` selects a layout, the canvas refusal is a
gate on each file's own `ratio` field, and the same names work over the control socket.
Stage 2 is **partly** built: the export machinery, the `special` kind, the extension keys
it needed, the determinism rules and both gates are in the tree, and two of the five themes
(`clock` and `gauge`) generate to layouts that paint *exactly* what `render.py` paints - zero
differing pixels across four readings each, worst channel delta 0. The other three do not
generate yet, and what they still need is written out below.
Stage 3, the file model, is in - what it measured is written out under "What building the file model measured" below. Stage 4 (the inspector and the canvas), stage 5 (docs and census) and stage 6 (the glass pass) are not built. Every census figure below is re-derived by `tools/selftest.sh`'s vendor-library
section, so it cannot rot in place. The decisions are
settled with the owner; the census is measured out of the files in this tree on the same
date, and each figure says where it came from, so that a reader can re-run it rather than
take it on trust. Where a number is a computation under a stated assumption, it says so -
that is the difference between a measurement and a guess, and this project does not blur
the two (docs/limits.md).

## The decisions, as taken

1. **The editor's surface is a canvas inside the preview pane that already exists**, plus a
   one-row inspector for the fields a drag cannot set (a colour, a font, a metric name).
   There is no multi-row table UI: the row set is what the inspector reads, and
   `--print-theme-fields` is what makes it reviewable in a log rather than only on screen.
2. **Our five themes become exportable data**: `--export-theme NAME` writes
   vendor-shape JSON on demand. The export is *generated and gated*, never committed -
   a committed copy of `gauge.json` goes stale the first time anyone edits
   `theme_gauge`, and this repo has already recorded a comparison that failed because a
   file changed between two builds (docs/packaging.md).
3. **The fan figures, the segmented tick strip and the plate stay code-drawn.** They enter
   a layout as a `special` row that *names* a code drawing, so their pixels keep
   `--text-color`, the ink halo and supersampling; no PNG assets, no new media roots,
   nothing extra to hash.
4. **The four 320×240 themes are excluded**, with the reason kept next to the gate rather
   than in a comment: the em-box anchor convention is measured only at 480
   (`xigmalcd/render.py`, and `themes/alpha/README.md`'s layout table).

## Why this is all host-side work, and why that is what bounds the cost

- **There is no panel-rendered content on this firmware** (PROTOCOL.md §11): with
  `realtimeDisplay {"enable":true}` on, 25 s of `STATE all 1` metrics pushed and no
  uploads at all, the screen showed only the static logo. The vendor app draws the whole
  picture itself and streams it - across all eight of its logs it sent seven command pairs
  and its only uploads were `.osd` (11 191) and `.mp4` (10): **no layout file ever goes to
  the panel**, so the panel is never handed the theme JSON and cannot be drawing a gauge
  (PROTOCOL.md §10).
- Therefore the editor never writes a theme to the panel, never needs a `.thm`
  re-encrypted, and `presetThemeId` stays refused: every host write to
  `logo`/`mode`/`presetThemeId` clears the field to `2147483647` (23 body shapes each) and
  the only repair is `recovery`, which this project keeps hand-invoked behind `--yes`.
- The one panel-side half is the background, and it already exists:
  `transport {"type":"media","fileName":"<name>.mp4"}`.
- The vendor's own format is *richer than the 27 shipped layouts use*: PROTOCOL.md §10
  records, read out of the app's `themeUtil-*.js` renderer bundle, seven kinds -
  `text` (text-node), `data` (number-text-node), `arc` (doughnut-node), `bar`
  (process-bar-node), `chart` (chart-node), `img`, `line`. The layouts use five, and
  `xigmalcd/layout.py` paints all five.

## The library as data, counted

From `themes/alpha/layouts/**/*.json`, counted with plain `python3 -` over the tree:

| quantity | value |
|---|---|
| layout files | **27** - 23 at `ratio: "1:1"` (480×480), 4 at `ratio: "4:3"` (320×240) |
| widgets over all themes | **152** (min 3, max 10 per theme - a theme is a short list, not a form) |
| kinds used | `data` 66, `text` 66, `bar` 15, `line` 4, `arc` 1 |
| distinct property keys | **33**, split by who reads them: **22 read by `layout.py`** (that set is taken out of the module with `ast`, not from a hand-kept table, so the painter and the census cannot drift apart); **11 carried by vendor files and never read** - `canvasProperties`, `controlName`, `coordBoundary`, `enableMove`, `italic`, `italicAngle`, `screenStatus`, `time`, `type`, `underline`, `valueChangeType`, every one of them the vendor editor's own bookkeeping, each with a stated reason in the print; and **4 read with no vendor file to show** - `name` (a `special`'s drawing to pick), `xigma` (our theme-level block) and `lineColor`/`lineWidth` (the line ink, measured off the two baked overlays that have a line rather than out of a file). By field: x, y on all 152; `fontFamily`/`fontSize`/`bold`/`italic`/`underline`/`textColor` on 132; `source` on 82; `content` on 66; width on 20 widgets, `height` and `rotate` on 19 each; `minValue`/`maxValue`/`bgColor`/`cornerRadius`/`startColor`/`endColor` on 16; `radius`/`angleStart`/`angleEnd`/`sizeWidth`/`sizeHeight` on the one arc. All of it is re-derived by `xigmalcd --print-theme-fields` |
| distinct `source` values | **12 named** over 82 widgets, across all 27 files (`CPU Temperature` 22, `CPU Usage` 16, `Time` 13, `Pump Speed` 9, `GPU Temperature` 6, `GPU Usage` 6, `CPU Frequency` 3, `Date` 3, `CPU Power`, `GPU Power`, `Upload Speed`, `Week` one each); 70 widgets carry no source at all. Across the **23 pickable** files it is **7 names** - `CPU Temperature` 17, `CPU Usage` 15, `Time` 11, `Pump Speed` 9, `GPU Usage` 6, `GPU Temperature` 3, `CPU Frequency` 2 - which is what `--list-themes` prints and what the suite gates |
| display formats measured | **4 of the 12** - `xigmalcd/layout.py`'s `FORMATS_MEASURED` is CPU/GPU Temperature and CPU/GPU Usage. The rest are this repo's own choice and `draw_theme` reports them in `notes["gaps"]` |
| fonts | 4 families (`Arial` 115, `simsun` 13, `Verdana` 3, `宋体` 1), 10 sizes (12, 14, 16, 20, 24, 32, 40, 70, 100, 140), `textColor` on 132 widgets in **13** distinct spellings over all 27 files - and 106 values in 9 spellings, 88 of them white, across the 23 `1:1` files alone. That narrower count is the table docs/themes.md carries, re-derived by the suite's vendor-library section, so either number has to name its scope when it is quoted |
| widget ids | all 152 UUID-shaped but only **54 distinct**: unique inside one theme, reused across themes. The editor must key a row by (theme, id), never by id alone |
| `property[].time` | 82 widgets carry it, **27 distinct values**, and the census shows the shape of that: each of the 27 files answers exactly one value inside itself. A save stamp per theme, from the vendor editor - not a reading, and not something a generated file has, so our exports omit it (`--print-theme-fields` re-derives all three numbers) |
| backgrounds | `background.mediaFile` names exactly one clip per theme, 27 distinct names |

The media side, and what the panel makes of it, is already in docs/themes.md and
docs/limits.md: 43 clips and 28 images per install, 40 of 43 clips 480×480 and **3 of them
320×240**, 23 clips at 24 fps and 20 at 20 fps, largest `clips/Theme_22.mp4` at
7 662 077 B - inside the socket gate's 8 MB ceiling.

## What runs today, and what does not

(The figures in this section are the ones `tools/selftest.sh` re-derives on every run, in
the vendor-library section, from the shipped files - not a snapshot of a one-off pass.)

- **14 of the 23 480×480 themes use only sources `sensors.collect()` already produces.**
  That figure is a computation, not an observation: it pairs the 12 named sources above
  against the groups `xigmalcd/sensors.py` documents (`network`, `memory`, `cpu`, `gpu`,
  `disk`, `fans`, `motherboard`, `timestamp`).
- **9 of the 23 need `Pump Speed`** - `Theme_28`, `Theme_29`, `Theme_34`, `theme_36`,
  `theme_37`, `theme_41`, `theme_45`, `theme_48`, `theme_49` - and no tachometer has ever
  been looked for on this box: `tools/fanscan.py` has never been pointed at a pump header. Finding one is a
  measurement with an unknown answer, budgeted at 2 h - the vendor's own vocabulary calls
  it `waterPumpSpeed` (PROTOCOL.md §10), so the source name is settled even if the sensor
  is not.
- On a machine where `gpu`, `fans` and `motherboard` are absent the count drops, and that
  is not hypothetical: a CI runner's `sensors.collect()` answered only `cpu`, `disk`,
  `memory` and `timestamp` on 2026-11-07. The loop must therefore degrade by *skipping the
  widget and saying so* - which is exactly what `draw_theme`'s `notes["missing"]` already
  records; the work is to surface it, not to invent it.
- Open gaps that stay gaps until measured: the arc colour ramp (`arc_colour` lerps
  `startColor`→`endColor` for any pair it has never seen on glass - one pair has been, and
  it is the vendor's declared one rather than our `ALPHA_COLD`/`ALPHA_HOT`), the four-stop
  `heat()` and three-stop `temp_colour()` ramps that no colour-pair spelling can express, and
  the 8 unmeasured display formats - which is where the existing roadmap items `Time_hh:mm`, `Week_en` and
  `kb/s` live.
- **The `line` gap closed on 2026-11-08, and closed by the vendor's own pixels rather than
  by a guess.** The four `line` widgets live in two themes (`Theme_14`, `theme_46`) and
  carry no colour, no thickness of their own and no `source` at all - they are decoration,
  not a series. Their baked overlays say what the app drew: a hard-edged
  **rgba(240, 255, 255, 255)** bar; the stroke is the declared rect `[x, x+width) ×
  [y, y+height)`, so `height` *is* the thickness; and `rotate` turns that rect about its
  own centre (the 90° widget at x165 y305 width150 height2 lands at x 239..240,
  y 231..380). Measured both ways: our painter's 798 pixels are the overlay's 798 pixels,
  0 differ, and a top-left corner pivot - the other plausible rule - would light 29
  overlay pixels that the centre rects do not explain, so the corner rule is refuted
  rather than preferred. `layout.MEASURED_LINE_INK` is now the default ink; the renderer
  bundle's green `rgba(19, 206, 102, 1)` is recorded and not used, because no shipped
  theme is observed to draw it.
- The same files carry a `rotate` on **two `bar` widgets** as well (both in the 320×240
  set, at 270°), and `draw_bar` does not read it. Nothing pickable needs it today, so it is
  not a bug on the glass - but the inspector cannot offer a rotation control for a `bar`
  until the rule is measured, and the same overlay trick that settled the `line` will
  settle it: the 4:3 themes have baked pictures too.
- The degrade-and-print behaviour stage 1 needs is already half-built: `xigmalcd/layout.py`
  records every skipped source in `notes["missing"]` and every unmeasured format in
  `notes["gaps"]`, and the suite already has a vendor-library section that re-derives the
  library's colour, clip and aspect figures from the files. The work is to surface those
  notes in the loop's own log and gate them, not to invent them.
- The reference material for closing the format gaps is in the tree: each theme's baked
  overlay (`themes/alpha/foreground/<id>.png`) is what the vendor drew for its own sample
  values, and `tools/theme_check.py` already measures our drawing against those pictures,
  theme by theme, in pixels.

## The model, and the determinism it needs

- A user theme is a layout file **in the vendor shape** under `~/.config/xigmalcd/themes/`,
  found by a first-winning root exactly like `media_roots()`. A vendor layout is therefore
  already a valid editable user theme, and "edit the 27" costs no new format.
- **The editor never writes into `/usr/share/xigmalcd/themes/alpha`.** Those files are
  dpkg-owned and re-hashed by `debian/tests/smoke`, 125/125, on every install; "back to
  the vendor's own" means re-reading the installed copy. The checkout's copy is read-only
  here for a second reason: it is the file every figure in these docs was read from.

### What building the file model measured (stage 3, 2026-11-08)

All of this is printed by `tools/selftest.sh` in the vendor-library section, on a temp
`XDG_CONFIG_HOME`, and nothing in it is written outside that directory.

* **Every shipped layout is reproducible from its own parsed content: 27/27.** One
  indentation (1 space), sorted keys, newline-terminated, and the only thing the vendor's
  own files disagree about is escaping: **18** write non-ASCII as `\uXXXX`, **9** keep it
  raw (the ones carrying a `宋体` family or CJK `content`). That is `json.dump`'s
  `ensure_ascii` switch and nothing else, and it is why `shape_of(path)` asks each file
  which shape it is in and `copy_for_edit` keeps it: a writer that always escaped would
  "change" 9 files nobody opened.
* **A copy for editing is byte-identical to its source, 23/23** - not re-dumped. After
  that, the diff between the vendor's file and yours is only what you touched.
* **Shadowing works as a file operation:** moving one text widget's `x` by 20 in a copy of
  `Theme_28` moves exactly that widget's box by `(20, 0)` and changes 1 163 of 230 400
  pixels on this bench (that count depends on which face resolves the label, so the gate
  prints it per machine and asserts only the `(20, 0)`-once, everything-else-still
  shape), while the vendor's file is still `2d9ccf610ab9…` byte for byte; `--list-themes`
  and `--check-theme Theme_28` both say "your copy", and after `delete_user_theme` both
  say "checkout" again. The moved widget is deliberately a *literal* text with no
  `source`, so a box that fails to move means the edit was ignored, not that a sensor
  reading was missing.
* **What is refused, in words** (`validate` returns `(hard, soft)`; hard raises on save,
  soft comes back with the path and is printed): writing anywhere but the user root, a
  name that is one of the five drawn from `render.py` (a saved `gauge.json` would be a
  second source of truth for `render.theme_gauge` - exactly what the export design exists
  to avoid), a name with a path separator or a leading dot, an empty `osd.widget` list,
  and a `property` with more than one entry - because `draw_theme` reads only
  `property[0]`, so the rest would be silently unwritten. The soft list, one fixture
  covering all nine: an unknown `source`, a family outside `layout.FONTS`, a `fontSize`
  outside the **ten** the library ships (12 14 16 20 24 32 40 70 100 140), a colour
  outside `rgba(r, g, b, a)`, a widget off the canvas, an `id` repeated inside one theme,
  a `special` with no drawing, a `text` with no `content`, a repeated `property` entry.
* **`--check-theme NAME` is the review door** for all of it: the file's own accounting,
  which root answered, the warnings, then what this machine's readings draw - boxes, lit
  pixels, what was skipped and why, which shapes are this repo's choice rather than
  measured off the vendor's picture, and the sources this box can and cannot answer *for
  that theme*. It exits 2 when the name resolves to nothing (the reason printed by
  `why_not`) or when the file cannot be walked.
- Three kinds of extension, all of them inert to anything but this program, since the JSON
  never goes on the wire: a `special` kind whose `name` is one of a printed list
  (`--list-specials`; the three we need are `cpu-fan-figure`, `gpu-fan-figure`,
  `tick-strip`); `autoFit` on a `text`/`data` row, because `_fit`/`_fit_size` in
  `xigmalcd/render.py` shrink a face until the string fits and the vendor schema has a
  fixed `fontSize` with no such key; and one top-level `xigma` block for theme-level
  properties - ink halo, cold/hot scale, gauge source, scrim mode. The round-trip gate
  below is what makes extra keys safe: unknown keys survive a save.
- **The export is byte-stable or the gate is noise**, and building it settled three of
  those rules: ids are derived from the theme name (`xigma-clock-time`), never `uuid4()`;
  `property[].time` is **omitted** rather than derived - it is the vendor editor's stamp,
  nothing in a drawing depends on it, and a stamp with nothing behind it would be a field
  that lies, so the gate asserts no export carries one; and an export never contains a
  rendered date or number, only `source` rows - the same rule `render.py`'s `_now()` and
  `date_str()` learned for frames and previews. `ratio: "1:1"` is emitted, the key the
  exclusion gate reads.
- Two gates on the export, both printed: **byte-stability** over two runs, and **pixel
  parity** - the generated JSON rendered by `layout.draw_theme` against the code drawing,
  with the painted-pixel difference printed per theme. Parity is what proves completeness:
  if an export forgets the gauge ring, the diff shows the hole rather than hiding it. A
  theme whose parity cannot be driven to a printed small number does not get exported, and
  the doc says which five are in and which are not.

## What generating an export actually found

The plan assumed our five would fit the vendor's shape with one added kind and two
extension keys. Building the first export (`clock`) turned up three, each because of a
measured difference between our drawing and the vendor's files - which is the point of
finding that out before an editor is built on top of it:

* **`special`**, the added kind. The clock theme's third line is
  `CPU 57°C  GPU 47°C  1919 RPM`: three readings and a fan *average* in one string, so no
  single vendor `source` stands for it. `render.clock_readings_line` builds the text once
  and both doors draw it - one builder, two doors, so what the code theme says and what the
  generated layout says cannot drift apart.
* **`xigma.anchor`**. Every vendor widget anchors at the em box's top-left (`la`, measured
  off the vendor's own baked overlay); `clock`, `bars` and `dual` centre their lines
  (`render._text`'s default is `mm`). Exporting a centred theme without saying so slides
  every line left by half its own width - and that is not a theory: the first export run
  here drew the big time line from x -108 to 588, because the fit rule and the anchor had
  not both been carried across.
* **`xigma.autoFitMax`**. `render._fit_size` walks a size down in steps of 2 to a floor of
  10 until a line fits a width budget; a vendor file declares one fixed `fontSize` and has
  no such rule. The generated file carries the same loop, with the same step and the same
  floor, because a different step is a different glyph size on the glass at the same
  reading.
* **`xigma.format`**. Our date line is `%A %d %B %Y` (`render.date_str`); this repo's
  vendor `Date` shape is `%m/%d/%Y`; and *neither* is measured off the vendor's picture.
  Rewriting our theme into the other shape would change the glass for no measured reason,
  so the export states its own format - and `draw_theme` stops calling that a gap, because
  a stated format is not a guess.
* **the `dejavu` family key.** Our five are drawn with DejaVu Sans and DejaVu Sans Bold
  (`render._FONT_GLOBS`). That is not one of the vendor's four names, and resolving it
  through `layout.FONTS["dejavu"]`, built out of `_FONT_GLOBS` so both doors read the same
  paths, beats borrowing `Verdana`, which only lands on the same files on this box.

The `special` registry is injected into `layout.draw_theme` rather than imported there,
because `layout` already imports `render` and not the other way round; an unknown name comes
back in `notes["missing"]` as `special:<name>`, so a typo in a layout is reported instead of
drawn as something else.

With those in place, `clock` generates to 3 widgets and 1 448 characters and `gauge` to 5
widgets and 2 314 characters, both byte-identical across runs, and parity reports the same
painted count both ways on four readings each - 25 548, 25 545, 22 944 and 21 003 lit pixels
for `clock`, 20 608, 21 391, 20 498 and 17 451 for `gauge` - with **zero** differing pixels
and a worst channel delta of 0. The diff is taken over all four channels on purpose: an alpha-only comparison
would not see a colour that had drifted, and colour is exactly what a layout carries in
`textColor`. The same gate watches the vendor side from the other direction: all 23
pickable layouts still paint **114 boxes and 315 287 lit pixels** (the total moved by
1 118 px when the `line` measurement landed, and the suite's bench record moved with it),
which is what proves the
anchor/autoFit keys and the `special` branch changed nothing about a vendor theme.

### What settled the gauge ring, and what is left for the other three

The ring was the last geometry question that could not be answered from the tree, and
`gauge` answered it: centre (236, 236), stroke centre-line at radius 127, 22 px thick, 260
degrees from 140° clockwise in Pillow's angles - which in the app's own angles is 50 to 310,
because `arc_angles` measured `pil = app + 90` off ALPHA's frames - and a **30..75 °C**
scale, which is the scale the captured frames imply (docs/limits.md records that the digits
read 57 °C with the tip sitting at 58-63 % of the sweep). Pillow's arc stroke lies *inside*
the bbox ellipse, so the declared `sizeWidth` is 254 with the outer edge at 127 and the
inner `radius` 105.

Building it exposed a difference that had never had to be named, and it is now a key:
**`xigma.arcPaint`**. `render.gauge` rasterises a fill as 3-degree arcs, each drawn 0.4
degrees past its end so the joints do not show, with the colour taken at each segment's
*start* and mixed by truncation. The vendor's ring, measured off its own frames, is
1-degree arcs with the colour at each segment's middle and butt caps. One arc, two
unchanged colours, **164 / 3 366 / 3 889 / 6 989 differing pixels** at four readings, worst
channel delta 255 - printed by the suite, because an export whose claim is "this layout
paints what the code paints" cannot be tested while two painters differ silently. No copied
layout carries the key; `layout.ARC_PAINT` defaults to the vendor's convention, and an
unknown name is a soft finding in `validate` and a `missing` note at draw time rather than
a guess.

While that was open, one colour fact came out: the pair with a measured ramp in
`ARC_COLOUR_MEASURED` is ALPHA's *declared* one, (0,247,255) to (0,255,113), and the plateau
that curve was measured to end at is (0,251,184) - which is exactly `render.ALPHA_HOT`. Our
theme took the end of the vendor's curve as its own end colour and drew a straight line to
it, so the numbers above are stepping, sampling and rounding only: for this pair neither
painter has a profile to differ about.

What the remaining three need, each with the reason it is not yet answerable:

| theme | what is missing | why it is a decision, not a lookup |
|---|---|---|
| `bars` | `render.hbar`'s per-column gradient | a vendor `bar` declares `startColor` and `endColor`, and `draw_bar` fills flat from `startColor`; a per-column ramp has no spelling in the vendor schema. Either a `xigma` ramp key names a code-drawn gradient, or the bar becomes a `special`. Both are on the table, neither is measured |
| `dual` | two rings on `heat()`, a `render.bar` whose fill radius is a function of the value (`min(h/2, w*max(frac,0.02)/2)`, so its corners change with the reading), and `_fit_arc` | **ramps are settled as data** - `xigma.colourStops`, measured exact against `temp_colour` at all 100 sampled positions and off by one unit at 8 of them against `heat`, because `heat` divides by the literals 0.3 and 0.2 while its breakpoints are 0.5 and 0.8 (docs/limits.md, printed by the suite) - so `dual` waits on a decision about *our* arithmetic, not on the schema. `_fit_arc` picks **one** text size jointly for two columns so a three-digit reading takes both down together: a relationship between widgets, which a per-widget schema cannot hold without a group key |
| `alpha` | the two fan figures, the tick strip, and its rings' `temp_colour` ramp | the fan figures and the tick strip stay code-drawn by decision (no PNG assets), so each needs a `special` drawing in `themes.SPECIALS` first - `clock-readings` is the pattern, and it reached a zero diff |

Two things that landing the ramp key made possible, before any theme needed it. A ramp is
now data (`xigma.colourStops`), and it was tested against both ramps this repo draws rather
than assumed: exact for `temp_colour` at all 100 sampled segment positions, off by one unit
at 8 of them for `heat` - which is the last obstacle to `dual`, and it is an obstacle inside
our own code (`heat` divides by the literals 0.3 and 0.2 where its breakpoints would give
0.30000000000000004 and 0.19999999999999996).

And the **first authored layout reaches a zero diff**: the suite writes a one-widget ring
with that ramp through the file model, saves it into the user directory, resolves it back and
draws it through the loop's own door - 0 differing pixels and worst channel 0 against
`render.temp_arc` at six values including one below the declared scale. No export, no
generator, nothing shipped: a file somebody edited, held to the same standard as our own
themes. That is stage 4's premise, demonstrated a stage early.

The plan's rule holds while all of this happens: **an export that cannot be driven to a zero
diff is not shipped**, and the suite prints which of the five are in and which are out.

## The surface, and the geometry it must not break

- The preview pane today is a `QLabel` in the left column, capped at `render.W +
  PANE_CHROME` = 532 px (`xigmaui/app.py`), showing a 480×480 frame that `_fit()`
  **never scales up** and scales down only as the pane shrinks. The suite asserts the cap
  arithmetic (`pane_l.maximumWidth() == render.W + app.PANE_CHROME`, `>= render.W` - "the
  frame could never be shown 1:1" - and `pane_l.width() == pane_l.maximumWidth()`), and
  docs/gui.md carries the rest of the pixel census: splitter minimums 200/300/320, 66 px
  clip rows with room for 7 clips at the 1180×780 default, a 150 px list floor and an 84 px
  log floor, the controls column needing 742 of its 744 px. Keeping the canvas *inside*
  that pane keeps every one of those claims true; moving it into a pane of its own
  invalidates all of them and they all have to be re-measured.
- **Nothing in this repo has ever delivered a pointer event to this window.** There is no
  `mousePressEvent`, no `setMouseTracking`, no `QTest`/`sendEvent` in `xigmaui/` or in any
  of the suite's sections; the offscreen tests call methods. That, not the drawing, is the
  new surface: synthetic press/move/release against an offscreen window, asserting the
  saved JSON's `x`/`y` moved by the right number of panel pixels.
- Mapping is small arithmetic once it is written down: `_fit()` computes
  `side = max(16, min(pane.w, pane.h, 480))` and centres the scaled pixmap, so the panel
  coordinate under a pointer is `(label - offset) * 480 / pm.width()`. Below 1:1 the
  pointer lands on interpolated pixels, so **editing is offered only at 1:1** and the
  canvas says so otherwise - the same stance `_fit()` already takes about scaling up, and
  it is testable against the cap the suite asserts.
- Hit-testing is nearly free: `draw_theme()` already returns `notes["boxes"]`, one ink box
  in device pixels per widget it paints. Adding the widget id to that record is ~10 lines
  and one caller to keep happy (`tools/theme_check.py:789`).
- The pane normally shows the background clip *playing*, at 5-30 fps, under our OSD layer.
  Dragging a widget over moving pixels is unreadable, so the canvas needs the pinned
  metrics fixture and a still preview. And selection chrome must not be painted into the
  composite the caption describes ("our composite of the background clip playing under the
  OSD layer we would send... not a picture of the glass") - it goes on an overlay, so that
  claim keeps its meaning.

## Stages, and what each one costs

One sitting is about 3 focused hours at this repo's standard: the claim measured, the
number gated, the docs updated in the same change.

| stage | lands | sittings | hours |
|---|---|---|---|
| 0 | this document, plus the schema written out properly: the `special` list, `autoFit`, the `xigma` block, the determinism rules, and how `--theme` opens past `choices=sorted(render.THEMES)` | 1 | 3 |
| 1 | **landed 2026-11-08.** the 23 `1:1` layouts selectable in the loop: name→layout resolver, human names from `background.mediaFile`, the source→`sensors.collect()` table, `--list-themes`, `notes["missing"]` printed as "no pump tachometer here, widget skipped" and again over the socket's `status`, the four `4:3` themes excluded by a gate on `ratio` so a future 480 layout cannot be dropped by a filter, and a `--theme` name that is canonicalised once at parse time so the CLI, the log and the socket all spell it the same | 1-1½ | 3-4½ |
| 2 | **machinery landed 2026-11-08,** `--export-theme NAME`, `--list-specials`, the `special` kind and its injected registry, the `xigma` extension keys, byte-stability and parity gates over four readings; two of five generate today: `clock` (3 widgets, 1 448 chars) and `gauge` (5 widgets, 2 314 chars) both reach a **zero-pixel diff** on four readings each; `alpha`/`bars`/`dual` do not generate yet and the table under "What settled the gauge ring" says what each still needs. (`--print-theme-fields`, listed here as unbuilt, landed with stage 3.) | 2-2½ | 6-7½ |
| 3 | **landed 2026-11-08.** the file model: the user root `~/.config/xigmalcd/themes` read before the checkout and before `/usr/share`, so an edited copy shadows the vendor's by file operation alone and deleting it puts the vendor's back; `canonical()`/`shape_of()`, `validate()` split into hard (will not draw) and soft (worth saying), `save()` (atomic tmp + `os.replace`, `.bak`, trailing newline, user root only, the five code names refused, traversal names refused), `copy_for_edit()`, `delete_user_theme()`, `user_copies()`, `themes.draw()` for an object that never touched a disk, and `--check-theme NAME` as the review door. The round-trip gate is in: **27/27 layouts reproduce byte for byte** and **23/23 copies are byte-identical to their source**. Not built: the window that drives it | 1-1½ | 3-4½ |
| 4 | the surface: one-row inspector over the fields each kind carries (sized by `--print-theme-fields`, which prints the per-kind field census), the canvas inside the existing pane, pinned fixture and still preview, keyboard nudge, undo coalescing, coarse live apply (a name that resolves to your copy, since `--theme`/`status`/the socket already spell one name one way) | 3-3½ | 9-10½ |
| 5 | docs and gates: docs/themes.md's "not in the picker, and that is not an oversight" section brought up to date, docs/usage.md's CLI table, docs/gui.md's window census, README's five-theme claims, the window's own theme tooltip (it still says the vendor files are for the panel's firmware, which §11 contradicts), `smoke` rendering every installed layout offline against a pinned values dict. The suite grows by at least one section - stage 1's gates belong in the vendor-library section that already re-derives docs/themes.md's colour census, not in a new one - and then every place `twenty` is a gate moves with it: README, docs/tools.md, docs/packaging.md, the top changelog stanza, and the count `.github/workflows/ci.yml` compares against | 1 | 3 |
| 6 | on glass, with the panel attached and the owner watching: the runnable set at 1 and 2 fps, achieved fps, loop seams for the vendor clips, the dark-ink-over-bright question that docs/limits.md still carries, and the transcript kept the way docs/packaging/ keeps installs | 1 | 3 |
| | **total** | **10-12** | **30-36 h** |

The useful-first-cut shape is unchanged in size: stages 0-3 plus the inspector half of
stage 4 is **6-7 sittings (18-21 h)**, and that already edits real vendor themes with no
unknowns and nothing gated on glass time. The canvas then lands inside stage 4 rather than
replacing it.

Optional, ½-1 sitting: re-reading the vendor's renderer bundles with
`tools/asar_extract.py --cat out/renderer/assets/themeUtil-*.js` so every spin range and
default in the inspector is the vendor's own constant instead of our census. No JS bundle
from the vendor app is tracked in this tree - only their file names appear, in
PROTOCOL.md §10 - so this needs the installed app off the Windows machine again.

## The order of work, each change independently green

1. This document, plus the pointer from docs/themes.md.
2. Stage 1 in two changes: resolver and `--list-themes` (nothing selectable yet), then
   selection with the printed `missing` behaviour and the `ratio` exclusion gate.
3. Stage 2: generator, byte-stability gate, pixel-parity gate.
4. Stage 3, then stage 4 in two changes (inspector and pinned fixture first, canvas and
   live apply second), then stage 5's docs and census in one.
5. Stage 6 on the bench, own sitting, transcript kept.

## What this document does not claim

This document was written before any of it existed, and it is now part record, part plan.
What does **not** exist in this tree: an editor surface of any kind (no inspector, no
canvas, no save path driven by a window - the file model is there and its writer is
exercised by the suite, but nothing in the CLI writes a theme); layout exports for
`alpha`/`bars`/`dual`/`gauge`; the fan-figure and tick-strip `special` drawings. What does:
stages 1-3 as their rows say, plus `--export-theme`, `--list-specials`,
`--check-theme` and `--print-theme-fields`, each gated in `tools/selftest.sh`.

And the census rows are no longer a one-off `python3 -` pass: the library counts, the
field counts, the round-trip and copy identity, the refusals and the `line` measurement are
all re-derived on every run, on two machines. Where a row still rests on the 2026-11-08
queries written out above, it says so. The hours are estimates, and they are stated as
estimates.
