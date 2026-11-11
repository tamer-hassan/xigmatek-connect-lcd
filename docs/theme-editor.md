# The theme editor, and the 27 vendor themes: the plan, with the numbers under it

**This is a plan, part of it landed.** As of 2026-11-08, stage 0's write-up (this file)
and stages 1-3 are in the tree: `xigmalcd/themes.py` finds the library and the file model
under `~/.config/xigmalcd/themes`, `--list-themes` and `--check-theme` print
it with the counts, `--theme <background name>` selects a layout, the canvas refusal is a
gate on each file's own `ratio` field, and the same names work over the control socket.
Stage 2 is **built**: the export machinery, the `special` kind, the extension keys it
needed, the determinism rules and both gates are in the tree, and all five drawn themes
(`alpha`, `bars`, `clock`, `dual`, `gauge`) generate to layouts that paint *exactly* what
`render.py` paints - zero differing pixels on every reading that answers what they ask,
worst channel delta 0. `alpha` was the one that had to earn its keys; `bars` was the one
that had to earn a change to its own drawing, and what that took is written out under
"The last theme, and the shape it turned out to need" below.

Stage 3, the file model, is in - what it measured is written out under "What building the file model measured" below. **Stage 4 is in, in the two changes the plan named**: `xigmaui/edit.py` is the editor's model, and the window's layout-editor row is a shell over it - what that half measured is under "What the editor's first half measured". Then the canvas in that same pane: press a row's ink box to select it, drag it, nudge it with the arrow keys - under "What the canvas half measured". What is still missing there is the pane drawing live readings instead of the pinned fixture, and any way to snap a row to a grid or to a neighbour. Stage 5 (docs and census) and stage 6 (the glass pass) are not built. Every census figure below is re-derived by `tools/selftest.sh`'s vendor-library
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
3. **The two fan figures stay code-drawn, and so does the ink plate.** A figure that has
   no geometry in the vendor's schema - this theme carries no fan widget at all - enters a
   layout as a `special` row that *names* a code drawing, so its pixels keep
   `--text-color`, the ink halo and supersampling; no PNG assets, no new media roots,
   nothing extra to hash. The plate is not a row: it is the theme-level `scrim` the frame
   loop already applies, from the frame's own alpha.
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
  covering all 12: an unknown `source`, a family outside `layout.FONTS`, a `fontSize`
  outside the **ten** the library ships (12 14 16 20 24 32 40 70 100 140), a colour
  outside `rgba(r, g, b, a)`, a widget off the canvas, an `id` repeated inside one theme,
  a `special` with no drawing, a `special` row that draws a pair with no `width` to place
  the two figures by, a `values` row with no `xigma.fitArc` to size itself against, a
  `text` with no `content`, a repeated `property` entry, and an `xigma.showIf` naming a
  source this program cannot answer - a row whose dependency can never be satisfied never
  draws at all, so a mistyped key there would look like a missing sensor.
* **`--check-theme NAME` is the review door** for all of it: the file's own accounting,
  which root answered, the warnings, then what this machine's readings draw - boxes, lit
  pixels, what was skipped and why, which shapes are this repo's choice rather than
  measured off the vendor's picture, and the sources this box can and cannot answer *for
  that theme*. It exits 2 when the name resolves to nothing (the reason printed by
  `why_not`) or when the file cannot be walked.
- Three kinds of extension, all of them inert to anything but this program, since the JSON
  never goes on the wire: a `special` kind whose `name` is one of a printed list
  (`--list-specials`; five have landed - `clock-readings` and `dual-status`, the composite
  lines, and `alpha`'s three pairs of lettering: `fan-figures`, `temp-values` and
  `temp-labels`, each one row placing two strings at one size that only the drawing decides.
  The label pair was the open question in the previous version of this document - a fifth
  `special`, or two `text` rows with a generated `fontSize` - and it resolved on
  measurement: the size the ring picks for those two constants is 22 px here and is a face
  metric of whatever box draws it, so a generated `fontSize` would bake one machine's
  answer. What is left in `alpha` is the assembly. The
  "segmented tick strip" this row originally named does not exist: it was a guess about a
  drawing `render.py` turned out not to make, and what `theme_alpha` actually draws is now
  printed from its own source by the suite); `autoFit` on a `text`/`data` row, because
  `_fit`/`_fit_size` in
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

### What the editor's first half measured (stage 4, 2026-11-08)

The model is `xigmaui/edit.py`, and it holds no Qt on purpose: the suite drives it in the
GUI section under a temp `XDG_CONFIG_HOME`, so every save, revert and refusal below
happens somewhere that cannot touch the reader's own `~/.config`. The window's group is a
shell over that model, and the gates say so in counts.

* **Opening writes nothing.** 3 library layouts and 5 generated ones opened, and
  the user theme directory still holds 0 files. This was not the first version: an
  earlier `open_theme` copied the file on open, which left a shadow of `Theme_28` behind
  whenever a later assertion failed - and a shadow is not inert, because `--theme
  Theme_28` and the socket both find it first. The count is the gate against that coming
  back.
* **The field list comes out of the code.** 25 field names across 6 kinds
  (`arc bar data line special text`), every one a key `themes.keys_read()` proves
  `layout.py` reads; none of the 11 keys the vendor carries without reading is offered.
* **A save drops nothing it did not understand.** The per-widget `property` key sets
  after a save are identical to the vendor file's, and every inert key that was there is
  still there. An editor that rewrites a schema it does not parse corrupts files.
* **An edit is the picture, and only the picture.** The literal `text` in `Theme_28`,
  x nudged to 227 over **20** spinbox keystrokes, is **1** undo step; exactly one ink box
  moves - by `(20, 0)` - and the other 5 stay put; **1 163 of 230 400** pixels change.
  That is the same edit, the same fixture and the same count as stage 3's shadowing gate,
  reached through the row rather than through the library, which is the point.
* **The file draws what the row drew.** After `save`, `--theme Theme_28` reads the copy
  (origin: *your copy*) and paints a frame byte-identical to the one that was on screen;
  one undo returns the first frame byte for byte; revert removes the copy and the
  vendor's frame is back, identical to the session's first.
* **A colour is stored the way the library writes it.** `#ff4040` becomes
  `rgba(255, 64, 64, 1)` - the spelling all 152 shipped widgets use, and the only one
  `layout.rgba` can read - and the row prints `stored as …` rather than leaving the
  reader to find it in a diff. 838 pixels change.
* **A refusal moves nothing.** Six refused writes against one `special` widget - an
  off-canvas coordinate, a non-number, `cerise`, `bold: "yes"`, `fontSize: null` (only
  this program's own keys mean anything by an absent value), a field the kind does not
  carry, and an unknown drawing name - leave 0 undo steps and `dirty` false.
* **Un-setting is a value.** Removing the gauge ring's `arcPaint` takes the empty `xigma`
  object with it and changes the whole frame by **3 887 px** at the fixture reading - the
  two ring conventions, one key apart (`layout.ARC_PAINT`). Setting it back paints
  byte-identically to the start and leaves 2 undo steps with `dirty` **false**: that flag
  answers "does memory disagree with the file?", not "was anything typed?", so it is
  derived from two snapshots rather than a counter.
* **The rows do not lie about the model.**  Counted by the gate rather than remembered
  here: the layout combo offers 28 names (5 generated + 23 files); a `bar` widget gets
  **15** rows - **11** keys the painter reads for that kind plus **4** of our own; an `x`
  of 9999 sits in the spinbox, refused in words while the picture stays put; and the one
  library layout that carries an `arc` shows `(not set)` in its `arcPaint` row rather
  than picking a default to display.  The figure this bullet used to carry was remembered
  rather than derived, and went stale the day `xigma.showIf` was added for `bars`: it
  said a `bar` had 14 fields.  The pane's cap - never larger than the 480 px glass -
  holds with the rows in it.
* **Pixel counts mean one thing.** `px_differ` in the suite counts pixels that disagree in
  any channel, the same count `themes.parity` reports. The first version divided a byte
  count by four, which printed 905 where the honest number is 1 163 - a fifth out, in the
  direction that flatters the edit.

Not built, and not claimed, as of the 0.5 tree this section describes: drawing the
editor from live readings, and snapping to a grid - the files carry none. What landed on
2026-11-10 (0.6), in place of the first of those, is the **peek**: the pane paints a held body -
this machine's sensors, or a JSON `STATE all 1` file read through the same door `--metrics-file`
uses - at the pinned instant, hides the marks, and refuses any act that writes a number.  The
rows themselves landed that same day: added as a copy of a real row, removed, reordered, and
resized by dragging the squares on their box - each kind through the size keys the
painter actually reads for it, which is a sentence per kind rather than one handle. And
on 2026-11-11, the snapping a *neighbour* implies: a drag pulled onto a number the same
file already uses, 2 px at most, only within one anchor class, plus the centre and the
mirror on x, with the line you left never offered back to you. Also that day, the
naming: a copy renamed, a second copy written under a new name, both taking a fresh `id`
so one `--theme <id>` never answers two files, and a name rule shared by every door that
invents one (`themes.new_name`) - it refuses a name any layout answers today, by name,
by case-fold, or by id, which is what `resolve()` actually matches. The bullets and
every digit they hold are in docs/gui.md. The window's theme combo still lists the five, because
those are the five whose per-theme options and ink the row under that picker edits; a
layout reaches the glass from the editor's box, by `apply to the panel`, and the display
answers with the name it is drawing so the window can show that rather than remember it.

### What the canvas half measured (stage 4, 2026-11-08)

Pointing at the picture is the same model with a different input device, and the gates are
in that order: one block drives `xigmaui/edit.py` with no Qt at all, the next one hands the
pane real `QMouseEvent`/`QKeyEvent` objects and asserts the same outcomes. (There is no
`QTest` in this environment, so the events are constructed and delivered to the widget
rather than synthesised by the toolkit - which is also what the plan expected.)

* **A point belongs to the row that put ink there, and the answer is the file's row, not a
  position.** `hit` reads the boxes `themes.draw` reported - the same boxes `--check-theme`
  prints - and returns the row's index in `osd.widget`. That is not pedantry on this
  layout: the clock line is row 11 and sits ninth in the drawn-box list, because rows whose
  source the fixture cannot answer draw nothing and contribute no box. A row with no box
  cannot be pointed at, and the gate finds a point on the glass with no row under it, so
  the pane can say "that press selects no row" instead of selecting whatever is nearest.
* **Overlaps resolve to the later row, because that is the one on top.** More than one box
  covers the CPU ring's centre, and the temperature figure standing inside it is what a
  press there selects. A ring that claimed every press inside its own bounding box would
  leave the reading inside it ungrabbable.
* **One drag is one undo step, and a drag that ends where it began is none.** The pane
  repaints while the button is down - that is the coarse live apply the plan put second,
  and it is deliberately coarse: every intermediate position goes through `move_to` with
  the run uncommitted, and one step is written at the release. Both fields are checked
  before either is written, so a drag that would put the anchor off the canvas is refused
  whole, in the model's words, and leaves the row at the last position it was allowed to
  hold; a drag that wanders out and back inside one press writes no step and clears
  `dirty`, exactly as a spinbox typed `3` -> `30` -> `3` does.
* **The sentence names the row's distance, not the cursor's.** The pane is scaled and
  centred, so a press at widget pixel *p* is a panel point that `_fit` chose, and the marks
  line up with what was drawn rather than with a second copy of the arithmetic. At a pane
  half the glass' size the glass' last column has no pixel of its own to press, and a
  scaled drag can land one panel px short of the cursor - which is why the note reports
  what the row moved by, measured from the model.
* **The marks never reach the frame.** The dashed box and its label are painted in the
  pane's own paint event, over the picture. The gate re-shows the pane with a mark up and
  without one and compares the PNG bytes the label was given - identical - and the layer
  the caption counts stays byte for byte what `themes.draw` returned. The plan asked for
  this specifically, and it is the claim that keeps "our composite ... not a picture of the
  glass" true with a selection on it.
* **The one thing the model cannot say, the pane does.** A row's *anchor* is bounded by the
  canvas; its ink is not - that is how the vendor's files are checked too, by `x,y`, and
  `validate` is silent about a row parked at the last legal column whose box runs past the
  edge. Only the window admits it, beside the mark: the corner the ink reaches and the
  canvas it is off.
* **Keys are the same door.** The arrow keys nudge the selected row 1 px, 10 px with Shift,
  one undo step each, refused in the model's words at the canvas edge.

What the plan predicted, and what did not match: the boxes were already there
(`notes["boxes"]`) and adding the row's index to them was indeed a few lines and one
caller; the pinned fixture and the still preview were what made a drag readable; the marks
going on an overlay rather than into the composite was the right call and is now gated. The
plan expected editing **only at 1:1** - it is offered at any scale instead, because
`to_panel` derives the mapping from the size `_fit` drew at, and the cost of that choice is
the rounding above, said out loud rather than hidden behind a mode.

Not built, and not claimed: a snap to a grid (the corpus has none: the gcd of every
declared placement is 1), and anything at all to the panel. Live readings came in on
2026-11-11 as the peek, and its shape is the measured half of this section: the pane can
*look* at another body, held and at the pinned instant, while every act that writes a number
stays drawn and judged at the pinned fixture - because at another body's readings the row boxes
move and the same point on the glass answers a different row, counts the suite makes on the
machine it runs on rather than quoting here. What landed on 2026-11-10 is the structural edit - a row
added is a copy of a row that already draws, its position chosen by the painter's boxes
rather than guessed, its order the list's order, its removal refused at the last row in
the library's own words - and the edges: eight squares on the selected row's box, only
the ones the model says its kind can write, and a drag that goes through the same door
as the field rows, one undo step, no file until `save`. And on 2026-11-11 the drag that
lines up: `edit.Editor.snap_lines` / `snap_move` over the numbers this same layout
already declares, the pane painting the model's line and quoting the model's sentence,
the arrow keys and the typed rows left exact. Also that day, the two acts that invent a
name: `rename` and `save as` over a name box, with
`themes.rename_copy` and `edit.Editor.save_as` behind them and one name rule shared by
both (`themes.new_name`: a name nothing in the library answers, by name, by case-fold or
by id), a fresh 13-digit id for any copy that takes a new name, and a menu, a state line
and a revert sentence that all ask `themes.resolve()` what answers the name now instead
of remembering what answered it when the layout was opened. docs/gui.md carries the
bullets and the digits they hold.

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
* **`xigma.showIf`**. One row's drawing depends on a reading other than its own. The shape
  that needed it is `bars`'s memory rows: their meter divides two fields (`used / total`)
  while the number beside it prints one of them (`Used RAM`), and the theme behind the file
  draws *neither* when the division cannot be made - which an integrated GPU does, reporting
  used memory and no dedicated total. A `data` row on `Used RAM` would otherwise print `4 GB`
  beside an absent meter, because the file's own source answers and the theme's does not. So
  the number row names the meter's source here; a row whose dependency is unanswered is
  reported in the skip list as `showIf:<source>`, the same way an unanswered source is, and
  the difference the key makes is measured rather than asserted (the gate strips the key from
  a generated `bars` and counts the pixels it then differs by).
* **`xigma.format`, and the two answers a bad one needs.** A format string goes to
  `strftime` for a clock and to `format()` for a reading, and either door raises when the
  specifier does not fit the value behind it - `%q`, `%d %d`, `{}` and `{:,.0f}` all raise on
  the int this fixture gives for `Used RAM`, while `,.0f` inside the braces does not, which
  is why the braces are refused with the spelling that works. Two answers, not one: the
  editor refuses such a value *before it reaches the file* (`edit.Editor._format_fits`,
  which probes the value this row's `source` actually carries and says which probe it used),
  and the painter survives a file that already carries one - it records
  `format:<source> (ValueError)` in the skip list, like every other hole, and draws the rest
  of the frame. Nine candidates, both doors, same verdict on each: the gate is the agreement,
  not a list of bad specifiers kept in either place.
* **`xigma.fitArc`**. A width budget is the schema's only fit rule, and it cannot express
  what `alpha`'s two temperature columns are sized by: the ring's hole, measured as ink,
  both strings against it at once. So a `special` row that draws that pair names the ring
  it has to clear, in an `arc` row's own vocabulary - `{cy, radius, width, angleStart,
  angleEnd}`, `radius` the inner edge and `width` the stroke, the angles the app's degrees
  where 0 is the bottom of the circle (`layout.arc_angles` measures that rule off the
  vendor's ring). One ring is enough, because the pair's two are congruent and the row is
  symmetric about its own `x`. A row that declares no ring is not drawn, and
  `--check-theme` says which key is missing rather than letting the digits land on the
  gauge. Why this is a key and not a width: the suite searches every whole-pixel budget
  this canvas can hold and none reproduces the sizes the ring picks (docs/limits.md).
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

With those in place, all five generate: `clock` 3 and 1 448 characters, `gauge` 5 and
2 314, `dual` 10 and 4 677, `alpha` 12 and 6 312, `bars` 32 and 14 121 - each byte-identical
across runs - and parity reports the same painted count both ways on every reading that
answers what the theme asks for: 25 530, 25 343, 22 944, 25 010 and 21 003 lit pixels for
`clock`, 20 608, 21 391, 20 498 and 20 743 for `gauge`, 40 006 and 41 842 for `dual`, 40 426
and 39 186 for `alpha`, 76 916 and 76 022 for `bars`, every one of them **zero** differing pixels and a worst channel delta of 0. The diff is taken over all four channels on purpose: an alpha-only comparison
would not see a colour that had drifted, and colour is exactly what a layout carries in
`textColor`. The same gate watches the vendor side from the other direction: all 23
pickable layouts still paint **114 boxes and 315 287 lit pixels** (the total moved by
1 118 px when the `line` measurement landed, and the suite's bench record moved with it),
which is what proves the
anchor/autoFit keys and the `special` branch changed nothing about a vendor theme.

### What settled the ring and the bar, and what is left for the last two

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

`dual` landed on the same machinery: two rings (`xigma.arcPaint: render` plus
`xigma.colourRamp: "heat"`), the bar (`xigma.barPaint: render` with that same ramp sampled
at the value's fraction), and a `special` for its middle line, because `CPU 62%    4101 /
15625 GB` is a composite of three readings inside one string and no vendor `source` stands
for it - `render.dual_status_line` builds it and the layout places it, one builder, two
doors. The bar and each ring were checked at a zero diff on their own before the theme was
assembled: six load values (including 0 and one past the declared maximum) and seven
temperatures (including one below the scale and one above).

**Holding a convention to the function it names is worth doing separately, and doing on
every shape that has one.** Widening that check to 14 load values, with the bar painted
against `render.bar` itself, found a bug the `dual` parity gate could not see: `render.bar`
draws a fill whenever `frac > 0.01` but rounds its corners off `max(frac, 0.02)` - two
different floors - and `BAR_PAINT["render"]` had one number doing both jobs, so a layout
bar at a load between 1 % and 2 % drew **no fill at all**. Parity missed it because none of
its readings land in that band: the two values that found it are 1.5 % and 2 %. The entry
has a `corner_floor` of its own now, and the band is in the gate.

**The ramp question was answered by naming rather than rewriting.** A ramp can be data -
`xigma.colourStops` is, and it reproduces `render.temp_colour` at all 100 sampled segment
positions - but it does not reproduce `render.heat()`: 8 of those 100 come out one unit off,
because `heat` divides by the literals `0.3` and `0.2` where its own breakpoints would give
`0.30000000000000004` and `0.19999999999999996`. Changing `heat` to agree with its own
breakpoints would be the tidy fix, and it would re-render `dual`, `alpha` and `bars`, every
figure of which was read off the current drawing; so the call was to leave the pixels alone
and name the ramp (`xigma.colourRamp`, one entry per drawing, `--print-theme-fields` prints
the names with their reasons). The same rule the fan figures and the two composite lines
follow.

What the last one needs, and it is not what `alpha` needed. `alpha`'s list was no guess:
the suite prints the calls `theme_alpha`'s own body makes, so the row that closed it is a
claim about this source and not a memory of it.

| theme | what it took, or what is missing | why it is a decision, not a lookup |
|---|---|---|
| `alpha` | **exported 2026-11-08:** 12 rows, 6 312 characters, **zero differing pixels** | every item on the derived list landed as a row: the two `temp_arc` rings as `arc` widgets with `xigma.arcPaint: render` and the ramp as `xigma.colourStops` (the three stops come out of `A26_ARC_LO`/`MID`/`HI`, which is the spelling the suite checks against `render.temp_colour` at all 100 sampled positions); the two usage bars as `bar` widgets with `xigma.barPaint: hbar`, the case a vendor `bar` cannot spell, since it declares one flat fill and `render.hbar` gradients per **column** - measured at 28 device-px pairs and 7 at 1x at zero pixels against `render.hbar`; the three pairs of lettering as `special` rows (`fan-figures`, `temp-values`, `temp-labels`), because each pair shares one text size that only the drawing can decide; the usage labels and percentages as `text`/`data` rows, which need nothing joint; and the clock line as a `data` row with `xigma.format` and a width to fit to. The rows were each measured against `theme_alpha`'s own drawing before any of them was assembled (docs/limits.md), which is why the assembled frame reaches zero on the first try rather than after a week of chasing seams |
| `bars` | **the shape was found by measuring, 2026-11-08:** optional fan slots (`Fan 1` through `Fan 4`), and one change to our own drawing - written out under "The last theme, and the shape it turned out to need" |

**The second schema question `alpha` raised was joint text sizing, and it was measured
before it was decided.** Three of the theme's drawings pick one face size for two strings at
once: the fan pair, the two temperature figures inside the rings, and the two labels over
them. The vendor schema
has no way to say "these rows are one size", so there were three candidate answers - one
`special` per group, a `xigma.fitGroup` key, or a `fitText` list hung off the `arc` widget.
The measurements (docs/limits.md, all printed by the suite):

* the joint size is *exactly* the smaller of the members' own fits - 30 fan reading pairs
  and 36 temperature reading pairs, no exception - so a group key would have been enough
  arithmetic, not a guess;
* sized apart, the pair is a different picture: on the author's bench, 25 of 30 fan pairs
  and 26 of 36 value pairs land at two sizes, and the fan row moves by 1 763 to 2 915 px;
* a width cannot do the ring's job. `xigma.autoFitMax` is the schema's only fit rule, and
  it is a width in panel px. Of the 441 whole-pixel budgets this canvas can hold, none
  reproduces the six sizes the ring's own rule picks; the best reaches five of six, and
  the per-reading windows ask for at least 153 px and less than 148 px - an empty interval.

So the fan pair is one `special` named `fan-figures`: the layout says where it is, how far
apart the two figures stand, what size ceiling and what ink they use, and the rule that
makes it a pair - the joint fit, the floor of 16, the step of 2 - stays in
`render.fan_figures`, which is the same function `theme_alpha` draws through. `temp-values`
follows the same shape, for the third bullet above and not for tidiness, and it adds one
thing the fan row does not have: the row has to say **which ring** its pair is sized against
(`xigma.fitArc`), because a pair of figures inside two congruent rings is one drawing
against one hole.  `temp-labels` is that same row with two strings that never change, and it
is a row rather than two `text` widgets for the same measurement - see the row-by-row walk
in docs/limits.md, which is where the two of them are checked together. `render.value_pair` is the door both the theme and the row go
through, and the suite counts the pixels: the row's ink is exactly the theme's in the hole
the ring painter leaves free, at the size `_fit_arc` picks, in all 36 pairs it walks
(docs/limits.md). What that costs is stated plainly: a reader cannot size or move one
member of a group on its own, and the editor's inspector offers the row's own fields (`x`,
`y`, `width` as the pitch, `fontSize` as the ceiling, `textColor`, `bold`, plus
`xigma.anchor` and whichever fit key that door reads - `xigma.autoFitMax` for a width-fitted
pair, `xigma.fitArc` for a ring-fitted one) rather than one field per figure.  The third
pair, `temp-labels`, goes through the same ring-fitted door as the figures: "CPU TEMP" and
"GPU TEMP" are constants, so a file could carry them as two `text` widgets - at a
`fontSize` this program generated, which is a face metric of the machine that generated it,
and the two rows still could not say they are one size.

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
diff is not shipped**, and the suite prints all five in, with each one's pixel diff
counted at every reading it can be given.

### The last theme, and the shape it turned out to need

`bars` is the one theme stage 2 cannot express. An hour ago this document recorded the
decision as "invent a repeat group"; the owner chose the smaller construct instead, and
measuring what `bars` actually is justified that for a reason nobody had written down: the
obstacle was never the row list.

**The construct: optional fan slots, and no new structure.** `Fan 1` through `Fan 4`, each a
row that draws only when that slot has a reading, and each with a `Fan N Name` source so
the name printed is the box's own. The reason that is smaller than a repeat group is a count:
the 23 library layouts this canvas can select ask for **7** `source` names between them -
`CPU Temperature` in 17 widgets, `Time` in 11, `Pump Speed` in 9, and then `CPU Usage`,
`GPU Usage`, `GPU Temperature` and `CPU Frequency` - and not one of them is a fan. So a fan slot adds a name
to our own source table, which this tree already extends, where a repeat group would have
been a new kind of structure in files whose whole point is that they are a fixed list of rows.
And "optional" is not new machinery either: `themes.values()` already reports every source it
cannot answer, and `layout.paint` already leaves that row undrawn and says why.

**The obstacle was the pitch, and it was in our own drawing.** `theme_bars` divided its pitch
out of the rows it *considered* -
`row_h = min(BARS_ROW_MAX, max(BARS_ROW_MIN, span // max(len(rows), 1)))` over a block
starting at `BARS_Y0` - and advanced `y` only for the rows that had a value to show. So the
row list's length, and with it the whole theme's vertical geometry, moved with whatever
`sensors` happened to find: a box with no fans got one pitch, this bench's two fans another.
Measured off the drawn frame, the fourth row of the code's own list came out in the third
place. No static file - fan slots or repeat group - can put a row where such a drawing will
move it.

So the decision had a second half, and it is built now: **`theme_bars` lays out ten rows on
every machine** - six fixed plus four reserved slots taken by position - which makes the pitch
32 px everywhere, and **a row with no reading keeps its place**: it is not drawn, and the
advance happens anyway. That is the rule the 27 library layouts already follow and the
hole-that-says-what-it-is rule docs/themes.md states. `bars` is this project's own drawing
rather than a reproduction of a vendor frame, so nothing measured off glass is invalidated by
changing it; what it costs is a visible gap on the glass where rows used to close up, and the
`bars` preview clip re-rendered from the recorded series in the same change (the preview gate
re-draws the layer and scores the tracked file, so a stale clip fails rather than misleads).
The per-machine cost this document recorded an hour ago shrinks with it: the pitch no longer
depends on this box's fan inventory, and what still varies per box is which slots draw.

**The sources are in** (2026-11-09): `themes.BARS_ROWS` names all ten rows in the order the
drawing lays them out - label, meter source, number source, scale - and `themes.values()`
answers them. Four are per-sensor fan slots (`Fan 1 Speed`..`Fan 4 Speed`, `Fan 1 Name`..
`Fan 4 Name`), which the vendor's vocabulary has no word for: it offers `cpuFansSpeed`
"CPU Fans Speed" and `gpuFansSpeed` "GPU Fans Speed", aggregates only, never a row per
tachometer (PROTOCOL.md 10) - and the two RAM names come straight out of that record
(`RAMRate`, `UsedRAM`), spelled in the display style this tree already uses. Where a reading
is a division rather than a field, it is marked as one: `RAM Rate` divides `used / total` the
way the drawing does, because `sensors` also reports a separate `memory.load`, which is not
the same number as that division on this box, and a meter 424 px wide cannot afford to be
handed the wrong tenth of a percent.

**And `bars` is a file now** (2026-11-09): `themes.bars_recipe()` generates 32 widgets out of
that table and those constants - the heading, the clock line, and three rows per reading -
and it reaches **zero differing pixels at all 13 readings** the parity gate gives it, the ones
that answer everything and the ones that answer almost nothing. Two things it needed that the
plan had not foreseen:

* **`xigma.showIf`, a key nobody had.** Eight of the nine readings in the first pass agreed as
  soon as the slots were in place; the ninth did not, and the case is a normal machine rather
  than a corner - a GPU reporting used memory with no dedicated total, which an integrated GPU
  does. The theme draws neither number nor meter there, because it decides the whole row by the
  division; the file had `Used GPU Memory` as its own source, so it printed `4 GB` beside an
  absent meter: **706 px and a worst channel of 255**. The key is what makes that dependency
  sayable, and the suite measures it rather than taking my word for it: it strips the key from
  a generated `bars`, paints it at that reading, and counts what the file is then off by - and
  holds that number against all three places it is quoted.
* **Two defects in the theme's own ratio code, found by chasing that number.** `theme_bars`
  read `mem["used"]` outright, so a dict reporting a total with no used raised `KeyError`
  inside the frame loop; and it formed its two memory meters by different tests - the GPU row
  needed its numerator to be *truthy*, so a reading of exactly 0 dropped the row, while the
  memory row kept it. Both are one function now, `render.pct_pair`, called from both doors
  (the drawing for its meters, the source table for `RAM Rate` and `GPU Memory Rate`), and a
  zero numerator is a reading: the row exists, at nothing filled. `bars` was the only theme
  that could see either, because it is the only one that reads those fields - which is worth
  saying out loud about the value of pushing every theme through the export door.

What the labels do also moved: a row's **label belongs to its subject and its number to the
reading**, so `BOARD` prints even where the board metric answers nothing, and a fan slot's
name prints only where `sensors` reported a tachometer at that position. That is the same
split the file makes - a literal `text` row for the six fixed labels, a `data` row on
`Fan N Name` for the four slots - and it is what let one drawing and one file agree at every
reading instead of only at the complete ones: a fan slot whose position exists but reports no
RPM, or no name, is exactly such a reading, and the suite's own case list is what keeps that
from being a claim.

What the suite holds, all of it measured: an `ImageDraw.text` spy runs while the frame is
painted, and the label-and-value strings it captures equal, row for row, what
`layout.text_for` produces from `themes.BARS_ROWS` - over four boxes and all ten rows - and
the rows the sources answer are the rows ink lands in. The generated file's row count, kinds
and `y` values are compared against `BARS_ROWS` and the `BARS_*` constants rather than
against remembered numbers, `xigma.showIf` appears on exactly the two rows whose number and
meter read different sources, and the review door's skip list is checked against the same
report's own "cannot answer" half. And `--check-theme bars` no longer warns that its own
new sources are unknown: `themes.source_names()` is one vocabulary, consulted by the painter,
the checker, the editor's menus and the gates.

## What the preview's two doors had to agree about

The window paints a theme two ways: from code (`render.draw`, this machine's live readings)
and from a file (`themes.draw`, the editor's pinned fixture).  Pictures of `bars` from those
two doors looked unrelated - 46 535 differing pixels on this bench's readings - and the
export was not the reason.  The pane was comparing a **live** frame against a **pinned** one,
and the pinned dict had gone stale: it answered **5 of the 19 sources** the five generated
layouts ask, while carrying four keys nothing in the library reads (`gpu.usage`,
`cpu.frequency`, `gpu.frequency`, `memory.used_percent`).  At that fixture the file door
painted `bars` with 14 of its 32 rows against a code drawing of 26, and `alpha`'s GPU row was
missing from one door and `--%` in the other: 4 587 px at one clock instant.

So the preview was fixed by fixing the fixture, not the layout.  `edit.FIXTURE` now answers
15 of the 19 sources, and the four it leaves are `Fan 3`/`Fan 4` name and speed - the
slots past the two tachometers this shape reports, empty in **both** doors, which is `bars`'s
reserved-slots rule being visible rather than hidden.  Three claims about it are gated, in the
section that already holds the editor's model:

* **every key is a key a box reports.**  The group-and-field set is checked against the
  metrics sample `sensors.py` prints at the top of its own module, so an unread key cannot sit
  in a fixture pretending to be a reading - which is precisely how this one did.
* **coverage is what the exports need.**  The sources the five generated layouts ask, minus
  what the fixture answers, must equal exactly the fan slots past its reported tachometers.
  A new reading in a new export has to be pinned here before the preview may be quiet about
  it.
* **the two doors put down the same pixels.**  All five themes at that fixture, at seven ink
  choices: zero differing pixels, worst channel 0.  Measured through the pane's own door
  (`Editor.paint(*Editor.fixture(), ink=...)`), not a hand-built call - and the row counts
  with it, in `bars`: 26 of its 32 rows at the completed fixture, where the same door painted
  14 of its 32 rows before, those two frames differing by 34 362 px (61 790 lit px against
  28 860).

That last claim needed a rule the library did not have.  `themes.draw` takes no `ink` and is
right not to: a layout's colours are its own, which is why a vendored theme looks here the way
it looks in the vendor's app.  An ink moved the code drawing by 18 475 px on this bench and
the file door by **0 px** - the window's text-colour row simply did not reach a generated
layout.  `themes.with_ink` closes it for the five names drawn from code: it copies the layout
and moves the colours `render.SKIN` declares, and `render.SKIN` is now the one table both
doors read, because a `theme_*` body calls `_skin(ink, *SKIN[theme])`.  The substitution is
**key-scoped**, and that is not a detail: `bars` uses `CYAN` both as a heading glyph and as
the `startColor` of all ten of its meters, and only the 22 `textColor` roles may move.  The
gate measures ink through the file door at every colour the parser itself knows - the ten
palette names read out of `parse_ink`, plus a hex and a tuple, 13 inks x 5 layouts, all 65
comparisons at zero pixels - because a preview of *our* theme follows the reader's colour
while a vendor's file never does: open `Theme_28` and the ink row moves it 0 px and says
nothing about it.

What the completed fixture costs is measured as a relation rather than as an absolute, because
this bench is not quiet while it runs: drawing each theme at the completed fixture and at the
same dict with those answers taken back out, alternating in one process, 60 draws each, is
**+0.02 to +0.47 ms** a frame - `bars` the largest, with its 12 extra rows.  The absolute
per-theme milliseconds in docs/gui.md stay labelled as owed a quiet-box re-measurement.

## The surface, and the geometry it must not break

- The preview pane today is a `QLabel` in the left column, capped at `render.W +
  PANE_CHROME` = 532 px (`xigmaui/app.py`), showing a 480×480 frame that `_fit()`
  **never scales up** and scales down only as the pane shrinks. The suite asserts the cap
  arithmetic (`pane_l.maximumWidth() == render.W + app.PANE_CHROME`, `>= render.W` - "the
  frame could never be shown 1:1" - and `pane_l.width() == pane_l.maximumWidth()`), and
  docs/gui.md carries the rest of the pixel census: pane floors 200/300/320, each raised
  to what that column's own contents measure, 66 px
  clip rows with room for 9 clips at the 1440×1024 default on this bench, 10 on CI's runner, a 150 px list floor and an 84 px
  log floor, and a fresh split (532/540/356) that leaves every column at least its
  contents' own minimum width - which 0.4's 1180 px window and 520/460/560 split did
  not, and is what the controls column's horizontal scrollbar came from. Keeping the
  canvas *inside*
  that pane keeps every one of those claims true; moving it into a pane of its own
  invalidates all of them and they all have to be re-measured.
- **Nothing in this repo had ever delivered a pointer event to this window** when this was
  written: no `mousePressEvent`, no `setMouseTracking`, no `QTest`/`sendEvent` anywhere.
  That, not the drawing, was the new surface - and it is what the canvas gate is: real
  press/move/release and key events handed to the offscreen pane, asserting the model's
  `x`/`y` moved by the right number of panel pixels. There is still no `QTest` in this
  environment, so the gate constructs the `QMouseEvent`/`QKeyEvent` objects itself.
- Mapping is small arithmetic once it is written down: `_fit()` computes
  `side = max(16, min(pane.w, pane.h, 480))` and centres the scaled pixmap, so the panel
  coordinate under a pointer is `(label - offset) * 480 / pm.width()`. The plan expected
  **editing only at 1:1**, because below that the pointer lands on interpolated pixels; what
  landed instead maps at whatever scale `_fit` chose - `Canvas.to_panel` reads the size that
  was actually drawn, so the marks and the press agree with the picture and not with a
  second copy of the arithmetic - and the cost is stated in the section above: at a scaled
  pane the glass' last column has no pixel of its own, and the note reports the row's
  distance rather than the cursor's.
- Hit-testing is nearly free: `draw_theme()` already returns `notes["boxes"]`, one ink box
  in device pixels per widget it paints. Adding the widget id to that record is ~10 lines
  and one caller to keep happy (`tools/theme_check.py:789`).
- The pane normally shows the background clip *playing*, at 5-30 fps, under our OSD layer.
  Dragging a widget over moving pixels is unreadable, so the canvas needs the pinned
  metrics fixture and a still preview. And selection chrome must not be painted into the
  composite the caption describes ("our composite of the background clip playing under the
  OSD layer we would send... not a picture of the glass") - it goes on an overlay, so that
  claim keeps its meaning. Both predictions held: an open layout is drawn from the fixture,
  and the marks live in the pane's paint event, gated by comparing what it was shown with a
  mark up and with none.

## Stages, and what each one costs

One sitting is about 3 focused hours at this repo's standard: the claim measured, the
number gated, the docs updated in the same change.

| stage | lands | sittings | hours |
|---|---|---|---|
| 0 | this document, plus the schema written out properly: the `special` list, `autoFit`, the `xigma` block, the determinism rules, and how `--theme` opens past `choices=sorted(render.THEMES)` | 1 | 3 |
| 1 | **landed 2026-11-08.** the 23 `1:1` layouts selectable in the loop: name→layout resolver, human names from `background.mediaFile`, the source→`sensors.collect()` table, `--list-themes`, `notes["missing"]` printed as "no pump tachometer here, widget skipped" and again over the socket's `status`, the four `4:3` themes excluded by a gate on `ratio` so a future 480 layout cannot be dropped by a filter, and a `--theme` name that is canonicalised once at parse time so the CLI, the log and the socket all spell it the same | 1-1½ | 3-4½ |
| 2 | **machinery landed 2026-11-08,** `--export-theme NAME`, `--list-specials`, the `special` kind and its injected registry, the `xigma` extension keys, byte-stability and parity gates over four readings; four of five generate today: `alpha` (12 widgets, 6 312 chars), `clock` (3, 1 448), `gauge` (5, 2 314) and `dual` (10, 4 677) each reach a **zero-pixel diff** on every reading that answers what they ask; `bars` does not, and the table under "What settled the ring and the bar" says what it still needs - including that `bars` may not be expressible as one file at all. (`--print-theme-fields`, listed here as unbuilt, landed with stage 3.) | 2-2½ | 6-7½ **Completed 2026-11-09:** `bars` joined them - 32 widgets, zero differing pixels at all 13 readings the gate gives it - which took a change to that theme's own drawing (ten reserved rows, a row with no reading keeping its place) and one key the schema had never had, `xigma.showIf`. |
| 3 | **landed 2026-11-08.** the file model: the user root `~/.config/xigmalcd/themes` read before the checkout and before `/usr/share`, so an edited copy shadows the vendor's by file operation alone and deleting it puts the vendor's back; `canonical()`/`shape_of()`, `validate()` split into hard (will not draw) and soft (worth saying), `save()` (atomic tmp + `os.replace`, `.bak`, trailing newline, user root only, the five code names refused, traversal names refused), `copy_for_edit()`, `delete_user_theme()`, `user_copies()`, `themes.draw()` for an object that never touched a disk, and `--check-theme NAME` as the review door. The round-trip gate is in: **27/27 layouts reproduce byte for byte** and **23/23 copies are byte-identical to their source**. Not built: the window that drives it | 1-1½ | 3-4½ |
| 4 | **landed 2026-11-08, in the two changes the plan named.** First the model (`xigmaui/edit.py`, no Qt, driven headless by the suite) and the window's layout-editor row over it: one layout combo (3 generated + 23 files), one widget, one field, one value; opening writes nothing; the field list is derived from `themes.keys_read()`; colours are stored in the vendor's `rgba()` spelling; refusals move nothing; 20 keystrokes are 1 undo step; the saved file redraws byte-identically what was on screen (1 163 px for the `(20, 0)` nudge, through both doors). Then the canvas inside that same pane: press a row's ink box to select it (the file's row index, later row wins an overlap), drag to move it - one drag, one undo step, the row follows the cursor and the pane repaints as it goes - and the arrow keys nudge 1 px / 10 px. **Amended 2026-11-10 (0.5):** the field dropdown became rows - every field the kind carries, one row each, **10 for `text` up to 18 for `arc`** counted off the model's lists across 185 widgets, one to three columns as the window's width allows (the window's floor is 1280x1024 now, per the owner), and each row carries a note line saying what that row paints at the pinned fixture - `edit.drawn_text` walking the painter's rules in the painter's order, proved by drawing every text-bearing row twice and requiring the two frames to be byte-identical. **Amended 2026-11-10 (0.6):** the rows themselves became editable - `add`, `remove`, `up`, `down` under the fields - and a new row is always a copy of a row that already draws: this layout's own row of that kind, otherwise a real row from the 28 layouts the editor opens, this repo's five exports ranked first because every row in them is carried to a zero-pixel diff. There is no default table, and none was invented: the vendor's application bundles are not in this tree, so the files are the only evidence of what a row of a kind looks like, and the suite re-counts that evidence (the 5-key envelope, the mandatory keys per kind, the id reuse, what `layerIndex` does not mean) on every run. Where a copy lands is decided by a trial draw and the painter's own boxes, and what a reorder does is proved by pixels in both directions. Built later, in the 0.6 cycle: snapping a row to a *neighbour*'s own numbers (2026-11-11) and the peek at another body's readings (2026-11-11).  Still not built: a snap to a grid - the corpus carries none to snap to | 3-3½ | 9-10½ |
| 5 | docs and gates: docs/themes.md's "not in the picker, and that is not an oversight" section brought up to date, docs/usage.md's CLI table, docs/gui.md's window census, README's five-theme claims, the window's own theme tooltip (it still says the vendor files are for the panel's firmware, which §11 contradicts), `smoke` rendering every installed layout offline against a pinned values dict. The suite grows by at least one section - stage 1's gates belong in the vendor-library section that already re-derives docs/themes.md's colour census, not in a new one - and then every place `twenty` is a gate moves with it: README, docs/tools.md, docs/packaging.md, the top changelog stanza, and the count `.github/workflows/ci.yml` compares against | 1 | 3 |
| 6 | on glass, with the panel attached and the owner watching: the runnable set at 1 and 2 fps, achieved fps, loop seams for the vendor clips, the dark-ink-over-bright question that docs/limits.md still carries, `--no-clock` on `clock` (that frame changed in 0.4 - docs/limits.md's knob map), the quiet-box re-measurement docs/gui.md's cost paragraph owes to `bars`, and the transcript kept the way docs/packaging/ keeps installs | 1 | 3 |
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

### What feature G's gates found about this suite's own harness

Two things, written down because they are facts about the tree and not about a bad day:

* **The pinned pair was shared, and a shallow copy did not protect it - so it deep-copies
  now.** `Editor.fixture()` used to return `dict(FIXTURE)`: one level deep, so every inner dict
  - `memory`, `cpu`, `gpu`, `fans` - was the module's own object.  This section's
  hole-in-the-readings gate pops `memory.total` out of the body it is handed, in order to ask
  what a row does when the reading it depends on vanishes, and with a shallow copy that punch
  went into the module and stayed punched for **every later draw in that process**: the live
  fixture answered 20 of the 21 `source` names the library asks rather than 21, and the only
  visible trace was a census of drawn boxes two short.  Both machines printed the same
  diagnosis, which is how it was caught: feature G's gates count from a fresh parse of
  `edit.py`'s own literal and then say what the live dict had become.

  Repaired on 2026-11-11, and the repair is what the earlier draft of this section said it
  would need its own change for.  `fixture()` returns `copy.deepcopy(FIXTURE)`, the five draws
  inside `edit.py` go through one `_fixture_metrics()` door rather than each inventing its own
  copy, the hole-punch gate now asserts the module's own dict still holds the key it punched
  out of its copy, and feature G's census ends by comparing the live `edit.FIXTURE` with a
  fresh parse of the literal - so a fixture edited on purpose still passes and one worn down by
  a caller does not.  The census prints what the deep copy costs beside the layer draw next to it
  - 0.004 ms here, the median of 200, against a draw measured in milliseconds - so
  pinning the pair properly is free, and the two figures come from the run that
  says them rather than from this page.

  What it cost is the part worth writing down, and the measurement names the rows,
  because a count of drawn boxes belongs to the machine that drew it and a row's `id` does not.
  Closing the hole let `RAM Rate` be answered again - the rate `memory.used` divides by
  `memory.total` to get, and the one name the worn fixture could not answer - and with it the two
  rows that ask for it in the `bars` layout: `xigma-bars-used-ram-value`, a `data` row that
  paints only while `RAM Rate` is answered, and `xigma-bars-ram-rate-meter`, a `bar` row whose
  `source` is that rate.  Three adjacent pairs of drawn rows had no box to be adjacent between
  while the name was missing (`bars` rows 13/14, 14/15 and 15/16), and the figures docs/gui.md
  labels per machine moved with them - 120 adjacent pairs whose boxes never meet became 122 here,
  and 12 / 6 / 6 pairs whose boxes do meet became 13 / 7 / 6.  How many drawn boxes that is worth
  is printed by the suite's own census, on the machine running it; the gate asserts that the two
  rows it names are the two that came back, so this paragraph cannot survive a change to either.
  Both machines' halves are measured now, and the runner's came out of the failed run rather
  than out of anybody's head.  The push carrying the repair failed
  `_pair("the pairs whose boxes never meet")` on CI's runner and printed its own answer - the
  assertion tuple read `(120,), (122, 118)`, which is the runner saying it now counts 120 pairs
  whose boxes never meet where the page still labelled 118 as its half - and the reorder sentence
  beside it said "of the 13 whose boxes do meet, 7 moved ink and 6 did not", which is this
  bench's triple exactly.  So the repair cost the same on either box: the runner went 118 -> 120
  never-meet pairs and 12 / 6 / 6 -> 13 / 7 / 6 on the meet side, the bench went 120 -> 122 and
  12 / 6 / 6 -> 13 / 7 / 6, and the two machines agree on the meet triple again while staying two
  pairs apart on the never-meet side.  The adds (159 across 28 layouts) and the placement triple
  (35 / 109 / 15) did not move on either box.  The follow-up green run, 43027945669, is the first
  that reached the asserts naming the *rows* rather than counting their pixels, and those held on
  CI's runner too: the same two row ids and the same three adjacencies came back there, which is
  what makes the paragraph above a claim about the files rather than about this bench.  What the
  census prints next to them - a copy's median, the layer draw beside it, the counts of boxes and
  pairs inside `bars` - belongs to whichever box ran it, and no page quotes those.

  Because which gate aborts depends on which figure moved, that section now prints every count it
  measured that follows a face - adds, placement, both sides of the reorder census - before any of
  them is held to the page, so one red run answers for all four.  It is a print, not an assert:
  all four follow the fonts on the box that drew them, which is the whole reason they carry a
  machine's label on the page.  What stays asserted is membership - this run's answer has to be
  one of the labelled halves, so a third machine is a sentence to add rather than a range to
  widen - and the same rule that once read `779 and 434` out of a failing gate for the `arc` box
  heights is what read 120 and 13 / 7 / 6 out of this one.

* **A byte compare against a generated theme's frame was a race with this machine's clock,
  and CI's run 43023694060 lost it.** That section asks what a loop drawing a name that has just
  been renamed out from under it ends up painting - the stock `gauge`, in words - and the assert
  compared the loop's frame with `render.draw({}, "gauge")` byte for byte.  The behaviour was
  right; the comparison was not.  The generated themes take their time line from this machine:
  `theme_gauge` calls `clock_str()`, which calls `render._now()` - the one hook docs/limits.md
  says every generated theme reads.  So the two frames were drawn a second apart, and measured
  here unpinned that is 772 of 921 600 bytes differing, every one of them inside the bbox
  (274, 446, 292, 468): the last digit of the clock `theme_gauge` paints at (236, 458).  Pinned
  the way the theme-census gates already pin it - `render._now` pointed at the section's `WHEN`,
  restored in a `finally` - the same two frames a second apart are one picture byte for byte.
  Why only this one: every other byte compare in that section draws through the **file** door,
  and `themes.draw` takes its instant as an argument.  The gate now also asserts the loop drew
  something *other* than `gauge` before the rename, so the identity after it is about a fallback
  rather than about two names that never differed, and its failure message carries a differing-
  byte count and a bbox - what a byte compare ought to print when a race is suspected of it.
* **A repaint re-applies the selected row's marks.** The pane's closing passage asserted that a
  press on empty glass leaves no mark, which is true until the next frame; once another gate's
  `time.sleep()` left a timer tick queued, the assert was reading that tick rather than its own
  act. The passage now stops the preview timer, asserts the clearing, then repaints and asserts
  the honest consequence - the mark returns, because the row is still selected.

## What this document does not claim

This document was written before any of it existed, and it is now part record, part plan.
What does **not** exist in this tree: a snap to a grid - the corpus carries none, so a
snap answers a neighbour's own number instead; the layout export for `bars` - `alpha` assembled
2026-11-08 into 12 rows at a zero pixel diff, its three pairs of lettering as `special`s
(`fan-figures`, `temp-values`, `temp-labels`), its rings and usage bars as `arc`/`bar` rows
naming a painter convention; any unit for the `space` the panel reports.  What does: stages
1-3 as their rows say, stage 4's model with the window's row over it and the canvas in the
pane over that, and since 2026-11-10 the rows themselves - added as a copy of a row that
already draws, removed down to but never including the last one, reordered through the
list that *is* the draw order, and stretched at its edges through the size keys its kind
owns; `--export-theme`, `--list-specials`, `--check-theme` and
`--print-theme-fields`, each gated in `tools/selftest.sh`; and since 2026-11-11 the pane's
**peek** - `main.read_metrics_file` and `sensors.collect()` feeding `Editor.paint` while
`Editor.fixture()` stays the only pair any writing door goes through, `peek_sentence` and
`peek_refusal` owning the words the window shows, and the fold census at twelve controls in
three boxes.

And the census rows are no longer a one-off `python3 -` pass: the library counts, the
field counts, the round-trip and copy identity, the refusals and the `line` measurement are
all re-derived on every run, on two machines. Where a row still rests on the 2026-11-08
queries written out above, it says so. The hours are estimates, and they are stated as
estimates.
