# The theme editor, and the 27 vendor themes: the plan, with the numbers under it

**This is a plan, part of it landed.** As of 2026-11-08, stage 0's write-up (this file)
and stage 1 are in the tree: `xigmalcd/themes.py` finds the library, `--list-themes` prints
it with the counts, `--theme <background name>` selects a layout, the canvas refusal is a
gate on each file's own `ratio` field, and the same names work over the control socket.
Stages 2-6 are not built: no generated export, no file model, no inspector, no canvas, no
glass pass. Every census figure below is re-derived by `tools/selftest.sh`'s vendor-library
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
| distinct property keys | **30**: x, y on all 152; `fontFamily`/`fontSize`/`bold`/`italic`/`underline`/`textColor` on 132; `source` on 82; `content` on 66; width/height/rotate on ~20; `minValue`/`maxValue`/`bgColor`/`cornerRadius`/`startColor`/`endColor` on 16; `radius`/`angleStart`/`angleEnd`/`sizeWidth`/`sizeHeight` on the one arc |
| distinct `source` values | **12 named** over 82 widgets, across all 27 files (`CPU Temperature` 22, `CPU Usage` 16, `Time` 13, `Pump Speed` 9, `GPU Temperature` 6, `GPU Usage` 6, `CPU Frequency` 3, `Date` 3, `CPU Power`, `GPU Power`, `Upload Speed`, `Week` one each); 70 widgets carry no source at all. Across the **23 pickable** files it is **7 names** - `CPU Temperature` 17, `CPU Usage` 15, `Time` 11, `Pump Speed` 9, `GPU Usage` 6, `GPU Temperature` 3, `CPU Frequency` 2 - which is what `--list-themes` prints and what the suite gates |
| display formats measured | **4 of the 12** - `xigmalcd/layout.py`'s `FORMATS_MEASURED` is CPU/GPU Temperature and CPU/GPU Usage. The rest are this repo's own choice and `draw_theme` reports them in `notes["gaps"]` |
| fonts | 4 families (`Arial` 115, `simsun` 13, `Verdana` 3, `宋体` 1), 10 sizes (12, 14, 16, 20, 24, 32, 40, 70, 100, 140), `textColor` on 132 widgets in **13** distinct spellings over all 27 files - and 106 values in 9 spellings, 88 of them white, across the 23 `1:1` files alone. That narrower count is the table docs/themes.md carries, re-derived by the suite's vendor-library section, so either number has to name its scope when it is quoted |
| widget ids | all 152 UUID-shaped but only **54 distinct**: unique inside one theme, reused across themes. The editor must key a row by (theme, id), never by id alone |
| `property[].time` | 82 widgets carry it, **27 distinct values** - one epoch per theme, the same value on every widget of that theme |
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
- Open gaps that stay gaps until measured: the `line` colour (4 widgets; the layouts carry
  no colour and `draw_line` uses the vendor app's own default, flagged), the arc colour
  ramp (`arc_colour` lerps `startColor`→`endColor` for any pair it has never seen on
  glass), and the 8 unmeasured display formats - which is where the existing roadmap items
  `Time_hh:mm`, `Week_en` and `kb/s` live.
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
  the vendor's own" means re-reading the installed copy.
- Three kinds of extension, all of them inert to anything but this program, since the JSON
  never goes on the wire: a `special` kind whose `name` is one of a printed list
  (`--list-specials`; the three we need are `cpu-fan-figure`, `gpu-fan-figure`,
  `tick-strip`); `autoFit` on a `text`/`data` row, because `_fit`/`_fit_size` in
  `xigmalcd/render.py` shrink a face until the string fits and the vendor schema has a
  fixed `fontSize` with no such key; and one top-level `xigma` block for theme-level
  properties - ink halo, cold/hot scale, gauge source, scrim mode. The round-trip gate
  below is what makes extra keys safe: unknown keys survive a save.
- **The export is byte-stable or the gate is noise**, so: derive ids
  (`xigma-<theme>-<n>`, never `uuid4()`), derive `property[].time` from the changelog date
  and put one value on every widget of a theme the way the vendor's files do, never emit a
  rendered date or number - only `source` rows, which is the same rule `render.py`'s
  `_now()`/`date_str()` learned for frames and previews - and emit `ratio: "1:1"`, the key
  the exclusion gate reads.
- Two gates on the export, both printed: **byte-stability** over two runs, and **pixel
  parity** - the generated JSON rendered by `layout.draw_theme` against the code drawing,
  with the painted-pixel difference printed per theme. Parity is what proves completeness:
  if an export forgets the gauge ring, the diff shows the hole rather than hiding it. A
  theme whose parity cannot be driven to a printed small number does not get exported, and
  the doc says which five are in and which are not.

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
| 2 | the export and its two gates (byte-stability, pixel parity), the three specials, `--print-theme-fields` | 2-2½ | 6-7½ |
| 3 | the file model: atomic save plus `.bak` under `~/.config`, warnings-not-errors validation from the census above (unknown source, off-canvas x/y, a `fontSize` outside the ten measured, an unparseable `rgba()`, overlapping boxes), and the round-trip gate: an unedited vendor theme re-saves byte-identical with unknown keys preserved | 1-1½ | 3-4½ |
| 4 | the surface: one-row inspector over the fields each kind carries, the canvas inside the existing pane, pinned fixture and still preview, keyboard nudge, undo coalescing, coarse live apply (`{"cmd":"theme","value":"user:foo"}`) | 3-3½ | 9-10½ |
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

It claims no behaviour that exists: there is no editor, no `--export-theme`, no `special`
kind and no selectable vendor theme in this tree. Every number above is either quoted from
a file in this repo (PROTOCOL.md, themes/alpha/README.md, docs/themes.md, docs/limits.md,
docs/gui.md), printed by a tool that exists here (`tools/theme_check.py`,
`tools/theme_previews.py`, `xigmalcd/layout.py`), or counted by a `python3 -` pass over
`themes/alpha/layouts/**/*.json` on 2026-11-08 whose queries are written out above. The
hours are estimates, and they are stated as estimates.
