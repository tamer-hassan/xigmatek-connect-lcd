# The theme editor, and the 27 vendor themes: the plan, with the numbers under it

**A plan, mostly landed.** What it asked for is in the tree. `xigmalcd/themes.py` finds
the vendor library and the file model under `~/.config/xigmalcd/themes`, `--list-themes`
and `--check-theme` print what it finds with the counts, `--theme <background name>`
selects a layout, the canvas refusal comes from each file's own `ratio` field, and the
same names work over the control socket. All six drawn themes (`alpha`, `bars`, `birdseye`,
`clock`, `dual`, `gauge`) generate to layouts that paint *exactly* what `render.py` paints - zero
differing pixels and a worst channel of 0 on every reading that answers what they ask -
which `tests/test_export_parity.py` holds. The editor is `xigmaui/edit.py`, a model with
no Qt in it, and the window's layout-editor row and the canvas in the preview pane are
shells over it: press a row's ink box to select it, drag it, nudge it with the arrow keys,
add a row as a copy of one that already draws, remove and reorder down to but never past
the last row, resize it through the size keys its kind owns. Since 2026-11-11 the pane can
also paint from another body's readings without writing any of them to the panel: the knob
above the picture puts `main.read_metrics_file` and `sensors.collect()` through
`Editor.paint`.  On 2026-11-12 that split in two: `this machine's readings` is **live** - the
preview tick re-reads, and the marks, the handles and the hit test come from that paint, so the
frame on screen is the frame a press answers at - while `a metrics file` stays a **held** look,
at the pinned instant, with the geometry doors shut and `Editor.fixture()` the only pair a door
that changes a number goes through.

What did not happen is the plan's last stage: **the glass pass**, the panel attached and
the owner watching. No canvas claim on this page is measured on glass, and the rows that
owe it are listed in docs/limits.md.

Two rules hold the page itself. Every census figure in it is computed from files in this
tree - `themes.scan()`, `themes.field_census()`, the layout files - and is re-derived on
every run by the check named beside it, so a number cannot rot in place; and where a
figure is a computation under a stated assumption rather than a measurement, it says so.
That is the difference between a measurement and a guess, and this project does not blur
the two (docs/limits.md).

## The decisions, as taken

1. **The editor's surface is a canvas inside the preview pane that already exists**, plus a
   one-row inspector for the fields a drag cannot set (a colour, a font, a metric name).
   There is no multi-row table UI: the row set is what the inspector reads, and
   `--print-theme-fields` is what makes it reviewable in a log rather than only on screen.
2. **Our five themes become exportable data**: `--export-theme NAME` writes
   *(five themes when this stage was written; `birdseye` made the set six on 2026-11-14,
   and the stage is the same stage: every one of them exports and is checked both ways)*
   vendor-shape JSON on demand. The export is *generated and checked*, never committed -
   a committed copy of `gauge.json` goes stale the first time anyone edits
   `theme_gauge`, and this repo has already recorded a comparison that failed because a
   file changed between two builds (docs/packaging.md).
3. **The two fan figures stay code-drawn, and so does the ink plate.** A figure that has
   no geometry in the vendor's schema - this theme carries no fan widget at all - enters a
   layout as a `special` row that *names* a code drawing, so its pixels keep
   `--text-color`, the ink halo and supersampling; no PNG assets, no new media roots,
   nothing extra to hash. The plate is not a row: it is the theme-level `scrim` the frame
   loop already applies, from the frame's own alpha.
4. **The four 320×240 themes are excluded**, with the reason kept next to the check that holds it rather than
   in a comment: the em-box anchor convention is measured only at 480
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
  `xigmalcd/layout.py` paints all six.

## The library as data, counted

From `themes/alpha/layouts/**/*.json`, counted with plain `python3 -` over the tree:

| quantity | value |
|---|---|
| layout files | **27** - 23 at `ratio: "1:1"` (480×480), 4 at `ratio: "4:3"` (320×240) |
| widgets over all themes | **152** (min 3, max 10 per theme - a theme is a short list, not a form) |
| kinds used | `data` 66, `text` 66, `bar` 15, `line` 4, `arc` 1 |
| distinct property keys | **33**, split by who reads them: **22 read by `layout.py`** (that set is taken out of the module with `ast`, not from a hand-kept table, so the painter and the census cannot drift apart); **11 carried by vendor files and never read** - `canvasProperties`, `controlName`, `coordBoundary`, `enableMove`, `italic`, `italicAngle`, `screenStatus`, `time`, `type`, `underline`, `valueChangeType`, every one of them the vendor editor's own bookkeeping, each with a stated reason in the print; and **4 read with no vendor file to show** - `name` (a `special`'s drawing to pick), `xigma` (our theme-level block) and `lineColor`/`lineWidth` (the line ink, measured off the two baked overlays that have a line rather than out of a file). By field: x, y on all 152; `fontFamily`/`fontSize`/`bold`/`italic`/`underline`/`textColor` on 132; `source` on 82; `content` on 66; width on 20 widgets, `height` and `rotate` on 19 each; `minValue`/`maxValue`/`bgColor`/`cornerRadius`/`startColor`/`endColor` on 16; `radius`/`angleStart`/`angleEnd`/`sizeWidth`/`sizeHeight` on the one arc. All of it is re-derived by `xigmalcd --print-theme-fields` |
| distinct `source` values | **12 named** over 82 widgets, across all 27 files (`CPU Temperature` 22, `CPU Usage` 16, `Time` 13, `Pump Speed` 9, `GPU Temperature` 6, `GPU Usage` 6, `CPU Frequency` 3, `Date` 3, `CPU Power`, `GPU Power`, `Upload Speed`, `Week` one each); 70 widgets carry no source at all. Across the **23 pickable** files it is **7 names** - `CPU Temperature` 17, `CPU Usage` 15, `Time` 11, `Pump Speed` 9, `GPU Usage` 6, `GPU Temperature` 3, `CPU Frequency` 2 - which is what `--list-themes` prints and `tests/test_theme_library.py` holds |
| display formats measured | **4 of the 12** - `xigmalcd/layout.py`'s `FORMATS_MEASURED` is CPU/GPU Temperature and CPU/GPU Usage. The rest are this repo's own choice and `draw_theme` reports them in `notes["gaps"]` |
| fonts | 4 families (`Arial` 115, `simsun` 13, `Verdana` 3, `宋体` 1), 10 sizes (12, 14, 16, 20, 24, 32, 40, 70, 100, 140), `textColor` on 132 widgets in **13** distinct spellings over all 27 files - and 106 values in 9 spellings, 88 of them white, across the 23 `1:1` files alone. That narrower count is the table docs/themes.md carries, re-derived by `tests/test_field_census.py`'s vendor-library section, so either number has to name its scope when it is quoted |
| widget ids | all 152 UUID-shaped but only **54 distinct**: unique inside one theme, reused across themes. The editor must key a row by (theme, id), never by id alone |
| `property[].time` | 82 widgets carry it, **27 distinct values**, and the census shows the shape of that: each of the 27 files answers exactly one value inside itself. A save stamp per theme, from the vendor editor - not a reading, and not something a generated file has, so our exports omit it (`--print-theme-fields` re-derives all three numbers) |
| backgrounds | `background.mediaFile` names exactly one clip per theme, 27 distinct names |

The media side, and what the panel makes of it, is already in docs/themes.md and
docs/limits.md: 43 clips and 28 images per install, 40 of 43 clips 480×480 and **3 of them
320×240**, 23 clips at 24 fps and 20 at 20 fps, largest `clips/Theme_22.mp4` at
7 662 077 B - inside the 8 MB ceiling the socket's own `check_media_file` enforces.

## What runs today, and what does not

(Every figure in this section is a computation over the shipped files, not an observation of
one machine, and `tests/test_theme_library.py` recomputes the source census on every run and
pins the counts it finds.)

- **14 of the 23 480×480 themes use only sources `sensors.collect()` already produces.**
  That figure is a computation, not an observation: it pairs the 12 named sources above
  against the groups `xigmalcd/sensors.py` documents (`network`, `memory`, `cpu`, `gpu`,
  `disk`, `fans`, `motherboard`, `timestamp`).
- **9 of the 23 need `Pump Speed`** - `Theme_28`, `Theme_29`, `Theme_34`, `theme_36`,
  `theme_37`, `theme_41`, `theme_45`, `theme_48`, `theme_49`.  That was a hole in the reader
  until 2026-11-13: `themes.UNMAPPED` held one sentence and no reading could clear it, so the
  nine drew without that widget on every machine, including a body that reported a pump.  It is
  now a rule over a fan row's `type` (`themes.FAN_TYPED`), and this box has the row: the channel
  that came alive when the AIO's block cable went into `PUMP_SYS1`, 2448-2469 RPM and flat while
  its own header's duty swept (PROTOCOL.md §8).  What was budgeted as "a measurement with an
  unknown answer, 2 h" cost a `fanscan.py --watch` and a re-wiring done at the machine.
  The source name was never in doubt: the vendor's own vocabulary calls it `waterPumpSpeed`
  (PROTOCOL.md §10).
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
  `notes["gaps"]`, and the checks already had a vendor-library section re-deriving the library's
  colour, clip and aspect figures from the files (`tests/test_theme_library.py`). The work
  was to surface those notes in the loop's own log and hold them there, not invent them.
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

All of this is re-run by `tests/test_theme_files.py`, on a temporary `XDG_CONFIG_HOME`, and
nothing in it is written outside that directory.

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
  pixels on this bench (that count depends on which face resolves the label, so
  `tests/test_theme_files.py` reports it per machine and asserts only the `(20, 0)`-once,
  everything-else-still shape), while the vendor's file is still `2d9ccf610ab9…` byte for byte; `--list-themes`
  and `--check-theme Theme_28` both say "your copy", and after `delete_user_theme` both
  say "checkout" again. The moved widget is deliberately a *literal* text with no
  `source`, so a box that fails to move means the edit was ignored, not that a sensor
  reading was missing.
* **What is refused, in words** (`validate` returns `(hard, soft)`; hard raises on save,
  soft comes back with the path and is printed): writing anywhere but the user root, a
  name that is one of the six drawn from `render.py` (a saved `gauge.json` would be a
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
  printed from its own source by `tests/test_specials.py`); `autoFit` on a `text`/`data` row, because
  `_fit`/`_fit_size` in
  `xigmalcd/render.py` shrink a face until the string fits and the vendor schema has a
  fixed `fontSize` with no such key; and one top-level `xigma` block for theme-level
  properties - ink halo, cold/hot scale, gauge source, scrim mode. The round-trip check below -
  `tests/test_theme_files.py`, which reads all 27 files back through the parser - is what
  makes extra keys safe: unknown keys survive a save.
- **The export is byte-stable or the comparison is noise**, and building it settled three
  of those rules - `tests/test_export_parity.py` holds all four of them: ids are derived from the theme name (`xigma-clock-time`), never `uuid4()`;
  `property[].time` is **omitted** rather than derived - it is the vendor editor's stamp,
  nothing in a drawing depends on it, and a stamp with nothing behind it would be a field
  that lies, so `tests/test_export_parity.py` asserts no export carries one; and an export never contains a
  rendered date or number, only `source` rows - the same rule `render.py`'s `_now()` and
  `date_str()` learned for frames and previews. `ratio: "1:1"` is emitted, the key that keeps the 4:3 themes out of the picker.
- Two checks on the export, both printed: **byte-stability** over two runs, and **pixel
  parity** - the generated JSON rendered by `layout.draw_theme` against the code drawing,
  with the painted-pixel difference printed per theme. Parity is what proves completeness:
  if an export forgets the gauge ring, the diff shows the hole rather than hiding it. A
  theme whose parity cannot be driven to a printed small number does not get exported, and
  the doc says which five are in and which are not.

### What the editor's first half measured (stage 4, 2026-11-08)

The model is `xigmaui/edit.py`, and it holds no Qt on purpose: `tests/test_editor.py`
drives it under a temp `XDG_CONFIG_HOME`, so every save, revert and refusal below happens
somewhere that cannot touch the reader's own `~/.config`. The window's group is a shell
over that model, and the checks say so in counts.

* **Opening writes nothing.** 3 library layouts and 5 generated ones opened, and
  the user theme directory still holds 0 files. This was not the first version: an
  earlier `open_theme` copied the file on open, which left a shadow of `Theme_28` behind
  whenever a later assertion failed - and a shadow is not inert, because `--theme
  Theme_28` and the socket both find it first. That count is what keeps it from coming
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
  That is the same edit, the same fixture and the same count as stage 3's shadowing check
(`tests/test_theme_files.py`),
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
* **The rows do not lie about the model.**  Counted by `tests/test_editor.py` rather than
  remembered here: the layout combo offers 28 names (5 generated + 23 files); a `bar` widget gets
  **15** rows - **11** keys the painter reads for that kind plus **4** of our own; an `x`
  of 9999 sits in the spinbox, refused in words while the picture stays put; and the one
  library layout that carries an `arc` shows `(not set)` in its `arcPaint` row rather
  than picking a default to display.  The figure this bullet used to carry was remembered
  rather than derived, and went stale the day `xigma.showIf` was added for `bars`: it
  said a `bar` had 14 fields.  The pane's cap - never larger than the 480 px glass -
  holds with the rows in it.
* **Pixel counts mean one thing.** `fixtures.differ` counts pixels that disagree in any
  channel, the same count `themes.parity` reports. The first version divided a byte
  count by four, which printed 905 where the honest number is 1 163 - a fifth out, in the
  direction that flatters the edit.

Not built, and not claimed, as of the 0.5 tree this section describes: drawing the
editor from live readings, and snapping to a grid - the files carry none. What landed on
2026-11-10 (0.6), in place of the first of those, is the **peek**: the pane paints a held body -
this machine's sensors, or a JSON `STATE all 1` file read through the same door `--metrics-file`
uses - at the pinned instant, hides the marks, and refuses any act that writes a number.  **The
first of those is built as of 2026-11-12**: `this machine's readings` is live, the frame it paints
is the one the geometry doors answer at, and it is still the file's numbers that are written - only
the readings behind the pixels change, at `--preview-fps`.  A file body keeps the 0.6 rule: held,
marks hidden, writes refused.  The
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
every digit they hold are in docs/gui.md. The window's theme combo still lists the six, because
those are the six whose per-theme options and ink the row under that picker edits; a
layout reaches the glass from the editor's box, by `apply to the panel`, and the display
answers with the name it is drawing so the window can show that rather than remember it.

### What the canvas half measured (stage 4, 2026-11-08)

Pointing at the picture is the same model with a different input device, and the checks
are in that order: one block drives `xigmaui/edit.py` with no Qt at all, the next one hands the
pane real `QMouseEvent`/`QKeyEvent` objects and asserts the same outcomes. (There is no
`QTest` in this environment, so the events are constructed and delivered to the widget
rather than synthesised by the toolkit - which is also what the plan expected.)

* **A point belongs to the row that put ink there, and the answer is the file's row, not a
  position.** `hit` reads the boxes `themes.draw` reported - the same boxes `--check-theme`
  prints - and returns the row's index in `osd.widget`. That is not pedantry on this
  layout: the clock line is row 11 and sits ninth in the drawn-box list, because rows whose
  source the fixture cannot answer draw nothing and contribute no box. A row with no box
  cannot be pointed at, and `tests/test_canvas.py` finds a point on the glass with no row
  under it, so the pane can say "that press selects no row" instead of selecting whatever is nearest.
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
  pane's own paint event, over the picture. `tests/test_pane_chrome.py` grabs the pane with a
  mark up and without one: the two grabs differ, which is what proves the chrome is painted at
  all, while the pixmap the label is handed and the image the model painted are the same either
  way - the layer the caption counts stays byte for byte what `themes.draw` returned. The same
  file holds the rule's other half: the chrome belongs to the selection, not to the last press,
  so a repaint paints the mark back for the row that is still selected. The plan asked for
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
going on an overlay rather than into the composite was the right call, and
`tests/test_pane_chrome.py` is what says so. The
plan expected editing **only at 1:1** - it is offered at any scale instead, because
`to_panel` derives the mapping from the size `_fit` drew at, and the cost of that choice is
the rounding above, said out loud rather than hidden behind a mode.

Not built, and not claimed: a snap to a grid (the corpus has none: the gcd of every
  declared placement is 1), and anything at all to the panel. Live readings came in on
  2026-11-11 as the peek, and its shape is the measured half of this section; it split
  in two on 2026-11-12.  A **file** body is held and at the pinned instant, a look only, and
  every act that writes a number stays drawn and judged at the pinned fixture - because at
  another body's readings the row boxes move and the same point on the glass answers a
  different row, counts `tests/test_peek_readings.py` makes on the machine it runs on rather
  than quoting here (the same probe is what says a *handle taken from the wrong frame* is a
  real hazard and not a story).  **This machine's readings** answers at its own frame
  instead: the marks come from the paint that is up, so the same probe finds no lie to
  refuse, and the count that file holds instead is what the live pane must not do - read the
  box on a pointer event, which is one sample per preview tick and none per mouse-move. What landed on 2026-11-10 is the structural edit - a row added is a copy
  of a row that already draws, its position chosen by the painter's boxes rather than
  guessed, its order the list's order, its removal refused at the last row in the
  library's own words - and the edges: eight squares on the selected row's box, only the
  ones the model says its kind can write, and a drag that goes through the same door as
  the field rows, one undo step, no file until `save`. And on 2026-11-11 the drag that
  lines up: `edit.Editor.snap_lines` / `snap_move` over the numbers this same layout
  already declares, the pane painting the model's line and quoting the model's sentence,
  the arrow keys and the typed rows left exact. Also that day, the two acts that invent
  a name: `rename` and `save as` over a name box, with `themes.rename_copy` and
  `edit.Editor.save_as` behind them and one name rule shared by both (`themes.new_name`:
  a name nothing in the library answers, by name, by case-fold or by id), a fresh
  13-digit id for any copy that takes a new name, and a menu, a state line and a revert
  sentence that all ask `themes.resolve()` what answers the name now instead of
  remembering what answered it when the layout was opened. docs/gui.md carries the
  bullets and the digits they hold.  (That button was relabelled `copy to a new name` on
  2026-11-13, for a reason written up under "What a press carries", below.)

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
  the difference the key makes is measured rather than asserted (`tests/test_bars_rows.py`
  strips the key from a generated `bars` and counts the pixels it then differs by).
* **`xigma.format`, and the two answers a bad one needs.** A format string goes to
  `strftime` for a clock and to `format()` for a reading, and either door raises when the
  specifier does not fit the value behind it - `%q`, `%d %d`, `{}` and `{:,.0f}` all raise on
  the int this fixture gives for `Used RAM`, while `,.0f` inside the braces does not, which
  is why the braces are refused with the spelling that works. Two answers, not one: the
  editor refuses such a value *before it reaches the file* (`edit.Editor._format_fits`,
  which probes the value this row's `source` actually carries and says which probe it used),
  and the painter survives a file that already carries one - it records
  `format:<source> (ValueError)` in the skip list, like every other hole, and draws the rest
  of the frame. Nine candidates, both doors, same verdict on each - `tests/test_row_notes.py`
  is the agreement, not a list of bad specifiers kept in either place.
* **`xigma.fitArc`**. A width budget is the schema's only fit rule, and it cannot express
  what `alpha`'s two temperature columns are sized by: the ring's hole, measured as ink,
  both strings against it at once. So a `special` row that draws that pair names the ring
  it has to clear, in an `arc` row's own vocabulary - `{cy, radius, width, angleStart,
  angleEnd}`, `radius` the inner edge and `width` the stroke, the angles the app's degrees
  where 0 is the bottom of the circle (`layout.arc_angles` measures that rule off the
  vendor's ring). One ring is enough, because the pair's two are congruent and the row is
  symmetric about its own `x`. A row that declares no ring is not drawn, and
  `--check-theme` says which key is missing rather than letting the digits land on the
  gauge. Why this is a key and not a width: `tests/test_specials.py` searches every whole-pixel budget
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

With those in place all six generate; as re-printed on 2026-11-14 by
`python3 -m unittest tests.test_export_parity`: `clock` 3 and 1 448 characters, `gauge` 5
and 2 314, `dual` 10 and 4 677, `alpha` 12 and 6 312, `bars` **46 and 19 890**, `birdseye`
**46 and 19 985** - each
byte-identical across two exports in one run - and `python3 -m unittest
tests.test_export_parity` prints the whole census, per case, with its diff.  Measured
2026-11-14, the two doors agree at **zero** differing pixels and worst channel delta 0 on
every reading that answers what the theme asks, and the cases where they part are named
rather than left out of the list - the six-theme print of 2026-11-14, every number in it
lifted from that run: `clock` agrees at all five cases (25 530 / 25 343 / 22 944 / 25 010 /
21 003 lit px), `bars` at all five (74 125 / 72 814 / 16 283 / 21 558 / 11 086) and
`birdseye` at all five (55 735 / 55 298 / 16 197 / 19 699 / 12 706); `gauge` at four (20 608
/ 21 391 / 20 498 / 20 743, and the fifth 17 451 against 4 319, 13 133 px apart); `dual` at
three (40 006 / 41 842 / 31 338, with 29 228 against 18 743 and 27 388 against 6 409);
`alpha` at two (40 891 / 39 186, then 9 174 px apart at each of the last three).  Those gaps
are the known asymmetry, not a regression: with no `gpu` section to read, the code drawing
keeps the widget and prints `--%`, while the file has no source to name and reports the row
as skipped.  `bars` and `birdseye` have no such parting, and the reason is a design choice
rather than luck: both doors drop a row whose *reading* is gone (a dial with no needle, a
meter with no value) and keep the row whose *subject* is present (the label `GPU`, which is a
part of the panel), so there is nothing left for the two doors to disagree about - so a page
that claimed five zeroes for every theme would be quoting a fiction,
and the print says which cases are which.  This passage's previous `bars` pair, 76 916 /
76 022, had been stale since the meter track went 10 px -> 6 px: a loss of ink with a gain
(a new row) inside it, which no gate would have caught by itself. The diff is taken
over all four channels on purpose: an alpha-only comparison would not see a colour that
had drifted, and colour is exactly what a layout carries in `textColor`.
`tests/test_library_draw.py` watches the vendor side from the other direction: all 23
pickable layouts still paint **114 boxes and 315 287 lit pixels** (the total moved by 1
118 px when the `line` measurement landed, and the bench record in docs/limits.md moved
with it), which is what proves the anchor/autoFit keys and the `special` branch changed
nothing about a vendor theme.

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
unchanged colours, **164 / 3 366 / 3 889 / 6 989 differing pixels** at four readings,
worst channel delta 255 - printed by `tests/test_conventions.py`, because an export
whose claim is "this layout paints what the code paints" cannot be tested while two
painters differ silently. No copied layout carries the key; `layout.ARC_PAINT` defaults
to the vendor's convention, and an unknown name is a soft finding in `validate` and a
`missing` note at draw time rather than a guess.

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
against `render.bar` itself, found a bug the parity checks as they then stood could not
see: `render.bar` draws a fill whenever `frac > 0.01` but rounds its corners off
`max(frac, 0.02)` - two different floors - and `BAR_PAINT["render"]` had one number
doing both jobs, so a layout bar at a load between 1 % and 2 % drew **no fill at all**.
Parity missed it because none of its readings land in that band: the two values that
found it are 1.5 % and 2 %. The entry has a `corner_floor` of its own now, and
`tests/test_conventions.py`'s load list walks 1.5 % and 2 % - the two values that found
it.

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
`tests/test_specials.py` prints the calls `theme_alpha`'s own body makes, so the row that
closed it is a claim about this source and not a memory of it.

| theme | what it took, or what is missing | why it is a decision, not a lookup |
|---|---|---|
| `alpha` | **exported 2026-11-08:** 12 rows, 6 312 characters, **zero differing pixels** | every item on the derived list landed as a row: the two `temp_arc` rings as `arc` widgets with `xigma.arcPaint: render` and the ramp as `xigma.colourStops` (the three stops come out of `A26_ARC_LO`/`MID`/`HI`, which is the spelling `tests/test_conventions.py` checks against `render.temp_colour` at all 100 sampled positions); the two usage bars as `bar` widgets with `xigma.barPaint: hbar`, the case a vendor `bar` cannot spell, since it declares one flat fill and `render.hbar` gradients per **column** - measured at 28 device-px pairs and 7 at 1x at zero pixels against `render.hbar`; the three pairs of lettering as `special` rows (`fan-figures`, `temp-values`, `temp-labels`), because each pair shares one text size that only the drawing can decide; the usage labels and percentages as `text`/`data` rows, which need nothing joint; and the clock line as a `data` row with `xigma.format` and a width to fit to. The rows were each measured against `theme_alpha`'s own drawing before any of them was assembled (docs/limits.md), which is why the assembled frame reaches zero on the first try rather than after a week of chasing seams |
| `birdseye` | **a second theme built from the same parts, 2026-11-14:** six dials in two
sections (arc + number + name each), five usage meters with a `special` figure beside every
label, three section captions with `line` rules, and a background of this repository's own
making - a 168-frame cut of the vendor's `theme_47.mp4`, whose first 17 frames carry a play
button at the centre (measured: head centre-luma 6.62 against the cut's 1.53).  Its geometry
is declared `chosen here` in `themes.GEOMETRY_ORIGIN`, which is what lets
`tests/test_snapping.py` hold its numbers to a lattice rule the vendor's own files are not
held to |
| `bars` | **the shape was found by measuring, 2026-11-08:** optional fan slots (`Fan 1` through `Fan 4`), and one change to our own drawing - written out under "The last theme, and the shape it turned out to need" |

**The second schema question `alpha` raised was joint text sizing, and it was measured
before it was decided.** Three of the theme's drawings pick one face size for two strings at
once: the fan pair, the two temperature figures inside the rings, and the two labels over
them. The vendor schema
has no way to say "these rows are one size", so there were three candidate answers - one
`special` per group, a `xigma.fitGroup` key, or a `fitText` list hung off the `arc` widget.
The measurements (docs/limits.md, all printed by `tests/test_specials.py`):

* the joint size is *exactly* the smaller of the members' own fits - 30 fan reading pairs
  and 36 temperature reading pairs, no exception - so a group key would have been enough
  arithmetic, not a guess;
* sized apart, the pair is a different picture: on the author's bench, 25 of 30 fan pairs
  and 26 of 36 value pairs land at two sizes, and the fan row moves by 1 763 to 2 915 px;
* a width cannot do the ring's job. `xigma.autoFitMax` is the schema's only fit rule, and
  it is a width in panel px. Of the 441 whole-pixel budgets this canvas can hold, none
  reproduces the six sizes the ring's own rule picks; the best reaches five of six, and
  the per-reading windows ask for at least 153 px and less than 148 px - an empty interval.

So the fan pair is one `special` named `fan-figures`: the layout says where it is, how
far apart the two figures stand, what size ceiling and what ink they use, and the rule
that makes it a pair - the joint fit, the floor of 16, the step of 2 - stays in
`render.fan_figures`, which is the same function `theme_alpha` draws through.
`temp-values` follows the same shape, for the third bullet above and not for tidiness,
and it adds one thing the fan row does not have: the row has to say **which ring** its
pair is sized against (`xigma.fitArc`), because a pair of figures inside two congruent
rings is one drawing against one hole.  `temp-labels` is that same row with two strings
that never change, and it is a row rather than two `text` widgets for the same
measurement - see the row-by-row walk in docs/limits.md, which is where the two of them
are checked together. `render.value_pair` is the door both the theme and the row go
through, and `tests/test_specials.py` counts the pixels: the row's ink is exactly the
theme's in the hole the ring painter leaves free, at the size `_fit_arc` picks, in all
36 pairs it walks (docs/limits.md). What that costs is stated plainly: a reader cannot
size or move one member of a group on its own, and the editor's inspector offers the
row's own fields (`x`, `y`, `width` as the pitch, `fontSize` as the ceiling,
`textColor`, `bold`, plus `xigma.anchor` and whichever fit key that door reads -
`xigma.autoFitMax` for a width-fitted pair, `xigma.fitArc` for a ring-fitted one) rather
than one field per figure.  The third pair, `temp-labels`, goes through the same
ring-fitted door as the figures: "CPU TEMP" and "GPU TEMP" are constants, so a file
could carry them as two `text` widgets - at a `fontSize` this program generated, which
is a face metric of the machine that generated it, and the two rows still could not say
they are one size.

Two things that landing the ramp key made possible, before any theme needed it. A ramp is
now data (`xigma.colourStops`), and it was tested against both ramps this repo draws rather
than assumed: exact for `temp_colour` at all 100 sampled segment positions, off by one unit
at 8 of them for `heat` - which is the last obstacle to `dual`, and it is an obstacle inside
our own code (`heat` divides by the literals 0.3 and 0.2 where its breakpoints would give
0.30000000000000004 and 0.19999999999999996).

And the **first authored layout reaches a zero diff**: `tests/test_export_parity.py`
writes a one-widget ring with that ramp through the file model, saves it into the user
directory, resolves it back and draws it through the loop's own door - 0 differing
pixels and worst channel 0 against `render.temp_arc` at six values including one below
the declared scale. No export, no generator, nothing shipped: a file somebody edited,
held to the same standard as our own themes. That is stage 4's premise, demonstrated a
stage early.

The plan's rule holds while all of this happens: **an export that cannot be driven to a zero
diff is not shipped**, and `tests/test_export_parity.py` puts all six through the two
doors, with each one's pixel diff counted at every reading it can be given.

### The last theme, and the shape it turned out to need

`bars` is the one theme stage 2 cannot express. An hour ago this document recorded the
decision as "invent a repeat group"; the owner chose the smaller construct instead, and
measuring what `bars` actually is justified that for a reason nobody had written down: the
obstacle was never the row list.

**Four doors for a `special` row, and what each one's fields mean.**  A `special` is drawn
by code and placed by the file, and which **door** it goes through is what gives its fields
their meaning: `line` (`layout.draw_special_line`) reads `x`,`y` with an anchor and ignores
`width`; `pair` (`draw_special_pair`) reads `width` as the pitch between two figures and
sizes both against `xigma.autoFitMax`; `values` (`draw_special_values`) reads `width` the
same way but sizes the pair against the ring named in `xigma.fitArc`; and since 2026-11-14 a
fourth, **`glyph`** (`layout.draw_special_glyph`) - the gutter figures of `bars` - where
`x`,`y` is a box's corner and `width`/`height` its size, exactly like a `bar` row, with no
anchor in sight.  The door is not inferred from a name table: each registered drawing
carries a `door` marker, and `tests/test_specials.py` reads the function's own source and
fails if the marker and the `layout.draw_special_*` call in the body disagree - and now also
runs `--list-specials` and fails if the printed captions and the registry fall out of step,
which is a defect that shipped silently once (adding the fourth door left that flag's
caption table behind it, and it raised `KeyError: 'glyph'` while every check was green).
A `glyph` row asks for **no font** (`needs_face = False`): it is geometry.  That matters
because a `text` or `special` row whose family this box cannot resolve is *dropped* - the
CI runner loses nine `simsun` widgets that way - and a figure that vanishes for an unrelated
absence would be a hole with no reason beside it.  What a glyph row can also name is
`xigma.iconVariant`: a **source**, not a value, so the figure can change shape according to
what the machine reports - `Fan 2 Type` answering `Pump` draws a volute where a rotor would
otherwise sit - and the resolution happens in the door, so the key is visible to the census
that pairs extension keys with written reasons.  `xigma.` keys the pane will not yet edit:
`iconVariant` is declared by the generator and shown by `--print-theme-fields` with its
reason, and the row inspector offers the fields of the kind, not of the door - a limitation
stated here rather than left to be discovered by someone hunting for the control.

**The construct: optional fan slots, and no new structure.** `Fan 1` through `Fan 4`,
each a row that draws only when that slot has a reading, and each with a `Fan N Name`
source so the name printed is the box's own. The reason that is smaller than a repeat
group is a count: the 23 library layouts this canvas can select ask for **7** `source`
names between them - `CPU Temperature` in 17 widgets, `Time` in 11, `Pump Speed` in 9,
and then `CPU Usage`, `GPU Usage`, `GPU Temperature` and `CPU Frequency` - and not one
of them is a fan. So a fan slot adds a name to our own source table, which this tree
already extends, where a repeat group would have been a new kind of structure in files
whose whole point is that they are a fixed list of rows. And "optional" is not new
machinery either: `themes.values()` already reports every source it cannot answer, and
`layout.paint` already leaves that row undrawn and says why.

**The obstacle was the pitch, and it was in our own drawing.** `theme_bars` divided its pitch
out of the rows it *considered* -
`row_h = min(BARS_ROW_MAX, max(BARS_ROW_MIN, span // max(len(rows), 1)))` over a block
starting at `BARS_Y0` - and advanced `y` only for the rows that had a value to show. So the
row list's length, and with it the whole theme's vertical geometry, moved with whatever
`sensors` happened to find: a box with no fans got one pitch, this bench's two fans another.
Measured off the drawn frame, the fourth row of the code's own list came out in the third
place. No static file - fan slots or repeat group - can put a row where such a drawing will
move it.

So the decision had a second half, and it is built now: **`theme_bars` lays out the same rows on
every machine** - seven fixed readings plus five reserved slots taken by position (three fan,
two drive), **twelve** as of 2026-11-14 - which keeps the pitch at 32 px everywhere, on any
hardware, because twelve rows is the ceiling the reservation implies: a thirteenth computes pitch
29, which the 2 px inter-row clearance rule refuses, and the last row's meter ink already ends at
y=442 with the clock's ink beginning at y=446.  Holding that pitch cost span 320 -> 352 ->
**384** and the clock line moving from y=452 to y=458; docs/limits.md has the arithmetic, the
clearance measurements, and the 3 px of air between the last row's meter and the clock's ink,
which is now a floor a check enforces rather than a fact this page asserts.  The ceiling is why
the owner's GPU-fan row went in **in place of** the fourth fan slot rather than beside it: the
vocabulary answers four `Fan N` pairs, the block draws three. and **a row with no reading keeps its place**: it is not drawn, and the
advance happens anyway. That is the rule the 27 library layouts already follow and the
hole-that-says-what-it-is rule docs/themes.md states. `bars` is this project's own drawing
rather than a reproduction of a vendor frame, so nothing measured off glass is invalidated by
changing it; what it costs is a visible gap on the glass where rows used to close up, and the
`bars` preview clip re-rendered from the recorded series in the same change. Nothing re-draws
that layer against the tracked clip any more - the six `docs/videos` files are the deliberate
gap of 0.7, docs/limits.md and docs/tools.md - so a stale clip is caught by `ffprobe` and an
eyeball, not by a check.
The per-machine cost this document recorded an hour ago shrinks with it: the pitch no longer
depends on this box's fan inventory, and what still varies per box is which slots draw.

**The sources are in** (2026-11-09): `themes.BARS_ROWS` named all ten rows then (eleven today,
drawn in the owner's 2026-11-14 order: three temperatures, two drive slots, two fan slots,
`Fan GPU`, then the three usage rows)
in the order the
drawing lays them out - label, meter source, number source, scale - and `themes.values()`
answers them. Three of the rows are per-sensor fan slots, drawn from four that the vocabulary
answers (`Fan 1 Speed`..`Fan 4 Speed`, `Fan 1 Name`..`Fan 4 Name`), which the vendor's vocabulary
has no word for: it offers the aggregates `cpuFansSpeed` and `gpuFansSpeed` - and the second of
those is a row of this block since 2026-11-14, paired with `gpu.fan` and printed as a duty
percent (docs/limits.md has why it is not RPM), while the first is the one name in
`layout.VENDOR_FORMAT` that has a shape and no source, pinned as an exception by
`tests/test_bars_rows.py` so nobody meets it as a silence again.
"CPU Fans Speed" and `gpuFansSpeed` "GPU Fans Speed", aggregates only, never a row per
tachometer (PROTOCOL.md 10) - and the two RAM names come straight out of that record
(`RAMRate`, `UsedRAM`), spelled in the display style this tree already uses. Where a reading
is a division rather than a field, it is marked as one: `RAM Rate` divides `used / total` the
way the drawing does, because `sensors` also reports a separate `memory.load`, which is not
the same number as that division on this box, and a meter 424 px wide cannot afford to be
handed the wrong tenth of a percent.

**And `bars` is a file now** (2026-11-09, 32 widgets then and 35 since the drive row): `themes.bars_recipe()` generates those widgets out of
that table and those constants - the heading, the clock line, and three rows per reading -
and it reaches **zero differing pixels at every reading** `tests/test_bars_rows.py` and
`tests/test_export_parity.py` give it, the ones
that answer everything and the ones that answer almost nothing. Two things it needed that the
plan had not foreseen:

* **`xigma.showIf`, a key nobody had.** Eight of the nine readings in the first pass agreed as
  soon as the slots were in place; the ninth did not, and the case is a normal machine rather
  than a corner - a GPU reporting used memory with no dedicated total, which an integrated GPU
  does. The theme draws neither number nor meter there, because it decides the whole row by the
  division; the file had `Used GPU Memory` as its own source, so it printed `4 GB` beside an
  absent meter: **651 px and a worst channel of 255** (706 px before the rows' geometry moved
  on 2026-11-12; what the check asserts is that the difference is not zero). The key is what makes that dependency
  sayable, and `tests/test_bars_rows.py` measures it rather than taking anybody's word for it:
  it strips the key from a generated `bars`, paints it at that reading, and counts what the
  file is then off by. How far off is this bench's, so the count is printed there and this
  page keeps only the fact that stripping the key changes the picture.
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
RPM, or no name, is exactly such a reading, and `tests/test_bars_rows.py`'s own case list is
what keeps that from being a claim.

What `tests/test_bars_rows.py` holds, all of it measured: an `ImageDraw.text` spy runs
while the frame is painted, and the label-and-value strings it captures equal, row for
row, what `layout.text_for` produces from `themes.BARS_ROWS` - over four boxes and every
row of the table, eleven today - and the rows the sources answer are the rows ink lands in. The generated
file's row count, kinds and `y` values are compared against `BARS_ROWS` and the `BARS_*`
constants rather than against remembered numbers, `xigma.showIf` appears on exactly the
two rows whose number and meter read different sources, and the review door's skip list
is checked against the same report's own "cannot answer" half. And `--check-theme bars`
no longer warns that its own new sources are unknown: `themes.source_names()` is one
vocabulary, consulted by the painter, the checker, the editor's menus and the checks.

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

So the preview was fixed by fixing the fixture, not the layout.  `edit.FIXTURE` answers
**21 of the 21 sources** the six exports ask today (the count moved when `birdseye`'s DISK
bar asked the vendor's `Disk Activity` and the dict grew it alongside `activity`), and it did not always: 15 of 19 while
`bars` had no drive row at all, 16 of 20 when that row arrived, and the count only closed on
2026-11-14 when the fixture grew a `drives` section and `bars` stopped asking `Fan 3`/`Fan 4`
names it had no way to answer.  Those two fan pairs stay in the vocabulary - four `Fan N` pairs
are answered, two are drawn, because reserving a third slot would have put a blank row between
`CPU PUMP` and `Fan GPU` on this box - and a preview whose rows are all filled is the point:
the reserved-slots rule is still visible where a real machine has a hole, and `--check-theme
bars` on this bench now says `skipped: nothing` rather than naming two.  Three claims about it are held in
`tests/test_fixture_shape.py`:

* **every key is a key a box reports.**  The group-and-field set is checked against the
  metrics sample `sensors.py` prints at the top of its own module, so an unread key cannot sit
  in a fixture pretending to be a reading - which is precisely how this one did.
* **coverage is what the exports need.**  The sources every generated layout asks, minus
  what the fixture answers, must equal exactly the fan slots past its reported tachometers.
  A new reading in a new export has to be pinned here before the preview may be quiet about
  it.
* **the two doors put down the same pixels.**  Every drawn theme at that fixture, at seven ink
  choices: zero differing pixels, worst channel 0.  Measured through the pane's own door
  (`Editor.paint(*Editor.fixture(), ink=...)`), not a hand-built call - and the row counts
  with it, in `bars`: **35 of its 35 widgets** at the completed fixture today - every row
  answered, nothing skipped - against the 35 of 38 with the fan row replacing a slot, the 32 of
  38 with one drive row and two fan slots drawn, the 29 of 35 measured when that rule was
  written, and the 14 of 32 the stale dict produced - a 34 362 px difference between those last
  two 2026-11-12 frames (61 790 lit px against 28 860).  Today the same door lays 69 131 lit px,
  and `themes.parity("bars",
  edit.FIXTURE, edit.FIXTURE_WHEN)` prints the pair with the pixel diff - which is the form these
  pages use now, because the row count moved three times in one day and a count copied by hand is
  a count that goes wrong.

That last claim needed a rule the library did not have.  `themes.draw` takes no `ink`
and is right not to: a layout's colours are its own, which is why a vendored theme looks
here the way it looks in the vendor's app.  An ink moved the code drawing by 18 475 px
on this bench and the file door by **0 px** - the window's text-colour row simply did
not reach a generated layout.  `themes.with_ink` closes it for the five names drawn from
code: it copies the layout and moves the colours `render.SKIN` declares, and
`render.SKIN` is now the one table both doors read, because a `theme_*` body calls
`_skin(ink, *SKIN[theme])`.  The substitution is **key-scoped**, and that is not a
detail: `bars` uses `CYAN` both as a heading glyph and as the `startColor` of all ten of
its meters, and only the 22 `textColor` roles may move.  `tests/test_ink.py` measures
ink through the file door at every colour the parser itself knows - the ten palette
names read out of `parse_ink`, plus a hex and a tuple, 13 inks x 5 layouts, all 65
comparisons at zero pixels - because a preview of *our* theme follows the reader's
colour while a vendor's file never does: open `Theme_28` and the ink row moves it 0 px
and says nothing about it.

What the completed fixture costs is measured as a relation rather than as an absolute, because
this bench is not quiet while it runs: drawing each theme at the completed fixture and at the
same dict with those answers taken back out, alternating in one process, 60 draws each, is
**+0.02 to +0.47 ms** a frame - `bars` the largest, with its 12 extra rows.  The absolute
per-theme milliseconds in docs/gui.md stay labelled as owed a quiet-box re-measurement.

### What the two doors' *tables* had to agree about (2026-11-12)

A report from the owner: an `alpha` edited in the pane, saved as `alpha_new`, and put on the
panel came up **missing the `special temp-values` row** - the two temperature figures between
the rings - while the same layout in the pane still drew it.  Nothing had gone wrong with the
save.  The file on disk was right, the pane was right, and the frame the loop uploaded was
missing two rows, quietly.

The cause was two doors that looked like one door and were not.  The pane paints a layout
file with `themes.draw`; the frame loop paints it with `themes.paint`.  Each built its own
value table, and only the pane's called `fill_lines`, which is where the six composite keys a
`special` row reads come from: `temp-cpu`, `temp-gpu`, `fan-cpu`, `fan-gpu`, `readings`,
`status`.  Those names are not `source` strings a file may spell - no vendor file spells them,
and `validate` has nothing to say about them - so the loop's table simply did not have them,
and each registered drawing that found its pair empty returned **no box at all**.  Two rows
left the picture and nothing in the notes, the log, or `--check-theme` said so: the
`special` rows were in the file, were counted by the file, and drew nothing.

`temp-labels` survived, and that is what makes the loss look selective rather than total: its
two strings are the constants `render.A26_TLBL_TEXT`, not readings, so it never asked the
table for anything.  The same fault was dropping two more rows nobody had reported yet, on
two other layouts: `clock`'s `clock-readings` line and `dual`'s `dual-status` line.  Of the
five layouts this repository generates, **three** declare rows that read those six keys -
`alpha` three rows, `clock` one, `dual` one - and **four** of its **five** `special` rows drew
nothing on the glass, because only `temp-labels` asks the table for nothing.

Three things follow, and all three are in the code rather than in this sentence:

* **One painter, two doors.**  `themes.paint` and `themes.draw` both go through
  `themes._overlay`: one value table, `fill_lines` included, one call to
  `layout.draw_theme`, one scrim plate.  The canvas stays an explicit argument, because it is
  the one place the two doors genuinely differ - a record's declared size against the size the
  object declares - and the four 320x240 pages that would tell them apart are refused by
  `themes.scan()` for the reason written there.
* **A door that stops filling has to say which rows it lost.**  `layout.draw_theme` records a
  `special` with no box, and until now that note was indistinguishable from a machine with a
  missing sensor - which is a legitimate reason for a row to have nothing to say, and why a
  box with no tachometers still draws `CPU FAN -- RPM`.  So `_overlay` compares the lost rows
  against the keys its own table carries and writes both into the notes, and the loop's report
  and `--check-theme` print them.  Reproduced by checking out the old door: the same fault
  that used to print nothing now prints
  `skipped special:temp-values (this door's value table carries no temp-cpu, temp-gpu: ...)`.
* **The registry and its fill table are one list, checked from the source.**  `fill_lines`
  fills exactly what `SPECIAL_LINES` lists, and every registered drawing reads its keys out of
  the value table by name.  `tests/test_specials.py` takes those names out of each drawing's
  own source with `ast` - the door `themes.keys_read()` uses for `layout.py`, aimed at a
  smaller module - and requires the two lists to match in both directions: a drawing that
  reads a key nobody fills loses its row from the glass, and a name listed but never read
  puts a string into every frame that no row will draw.

And the claim the report actually needs, held as pixels: `ALoopAndAPanePaintOnePicture`
generates each drawn layout, **saves** it as a layout file the way the editor does,
resolves it by name, and paints it through both doors at one body and one instant.  Zero
differing px for every one of them - including the two, `clock` and `dual`, that carry only
one `special` row each, and `gauge`, which declares none at all, because a shared door should not agree only when
the layout is interesting - the same box for every `special` row, a box for each of them, and
ink inside every box on both frames, so neither door can pass by drawing nothing.

The figures print on every run and are not rules: they follow the faces installed.  This bench,
at that one body and instant - read them out with
`python3 -m unittest tests.test_specials.ALoopAndAPanePaintOnePicture`:

| layout | the two doors | ink inside each reported `special` box | the same file, table without the composites |
| --- | --- | --- | --- |
| `alpha` | 0 px | `temp-values` 7 251, `temp-labels` 2 899, `fan-figures` 2 234 | 11 167 px lighter, no box for `temp-values`/`fan-figures` |
| `clock` | 0 px | `clock-readings` 3 202 | 4 687 px lighter, no box for `clock-readings` |
| `dual` | 0 px | `dual-status` 1 293 | 1 851 px lighter, no box for `dual-status` |
| `bars`, `gauge` | 0 px | none declared | nothing to lose |

Note the last two columns are not the same measurement, and the difference between them is a
fact about the painter rather than a rounding error: a row's **box** is the ink it declared,
while the whole-frame figure also carries the supersampling tail - every special is drawn at
`layout.SS` and downscaled with LANCZOS, so a few pixels land outside the box the row reports.

Shown non-vacuous, one mutation at a time on `tests/test_specials.py` (15 checks as shipped,
0 failures): the shared door stops filling → 4 failures, one per layout that can lose a row plus
the guard below it; the notes stop naming a lost row → 1; one drawing reads a key `fill_lines`
never writes → 48, the new static check and every temperature-row check in the file;
`SPECIAL_LINES` loses one of the two figure keys → 47; the pane's door ignores the size its
object declares → 1, and the same for the loop's door ignoring the record's → 1.  Back as
shipped: 0.

The route through the window is held the same way: putting `apply to the panel`'s two box counts
back through the pane's painter - which paints the buffer, not the file the display will draw -
fails `tests/test_apply_layout.py` with `(11, 11) != (12, 12)`, the buffer's row count against
the file's.

What is **not** claimed: that this was watched happening on a panel.  The two doors painting one
picture, the words a door leaves when it loses a row, and the box counts the apply route reports
are all measured offline.  The glass half belongs to stage 6 of this plan, and the row it owes
there is specific: apply `alpha_new` - or any saved copy of `alpha` - to a running display and
see the temperature figures and the fan figures on the panel, at the same rows the pane shows.
Until that transcript exists, docs/limits.md's stage-6 ledger carries it as owed, and the
offline parity above is what makes it worth looking at rather than a guess that the fix worked.

### The two doors that decide *which file* the box holds (2026-11-12)

The second half of the same report, and a smaller one on its own: *"I discovered a bug where I
have no way of opening & loading a previously saved layout in xigmaui."*  Probing it on the
owner's own configuration root found two faults, not one, and they had different causes:

| what was asked for | what was actually missing | the door |
| --- | --- | --- |
| a copy saved after the window opened should appear | the layout menu is built once, at startup, and was rebuilt only after a rename, a save-as or a revert **in that window** - so a copy written by the CLI, by a second window, or by hand into `~/.config/xigmalcd/themes` stayed invisible until a restart | `reload the list` |
| a layout file should open from wherever it is | `themes.resolve` reads three roots and nothing else, so a file outside them - one copied off another machine, the `<name>.json.bak` a save leaves behind, an `--export-theme` printout - could not be opened at all | `open a file…`, `edit.Editor.open_path` |

Both are named in the menu's own field column, not down with the three buttons that act on the
file the box already holds; both stay up when `advanced controls` comes off, because they are how
a layout gets into the box rather than what the box does to it.  Neither writes: opening is a read,
and the file that was open stays open through a reload, unsaved edits and all, because the rebuild
blocks the menu's signals on purpose.

The model door is where the honesty lives, and it had to answer three questions `open_theme` never
had to:

* **where does a save from this buffer go?** To `themes.user_theme_path(<stem>)`, the one writable
  directory - *not* to the file that was opened. The file you pointed at may be dpkg's, or the
  checkout's evidence, or a backup; one writable root is a rule of the file model, not a
  preference (docs/limits.md).
* **which file was this buffer read from?** `Editor.opened` carries that, and it is a different
  question from `Editor.path`, which is where a save would go. Keeping them apart is the only way
  the window can say the true sentence, and `edit.PATH_ORIGIN` - one wording, at module level,
  quoted by the state line, by the refusal below and by the checks - is what marks the case.
* **can a display be told to draw it?** No, and this is the one thing the new door cannot do.
  `apply to the panel` sends `("theme", <name>)`; the display resolves the name in the roots *it*
  can see. So the press refuses a by-path buffer and sends nothing, and the state line says which
  of three cases applies: nothing answers the name, your own copy answers it (saved since), or
  somebody else's file answers the same stem - **a different file**, and the one the panel would
  have drawn. `save as your copy` is the whole answer, and a check walks it: refuse, save, apply,
  and the display's own status then names the copy.

A path one of the roots already answers is delegated to `open_theme`, because the origin words have
to stay the true ones: `~/.config/xigmalcd/themes/alpha_new.json` *is* the layout called
`alpha_new`, and calling it "a file you named" would hide the fact that a loop already draws it.

`open_path` refuses in five shapes, each quoting the path: nothing there, a directory, a file that
is not JSON, JSON that parses but carries no `osd`/`widget` - which is the refusal most worth
spelling out, because a `STATE all 1` metrics body, a clip's sidecar and somebody's `config.json`
all load as dictionaries and would leave a pane painting nothing under a title claiming a layout is
open - and a layout at a ratio this canvas refuses, in `themes.RATIO_WHY`'s own sentence, the same
one the library prints for its four 320x240 pages. A refusal leaves the layout that was open
exactly where it was.

The file dialog is a step of its own (`_ed_ask_path`, with `_ed_start_dir` beside it) for the reason
every un-clickable control in this suite has: a native dialog cannot be driven headless, and a door
whose prompt cannot be replaced is a door no check can reach.  So the checks drive the button,
replace that one step, and separately ask the shipped step where it *would* have opened the dialog -
the user's own copies, falling back to the home directory only where no copy has ever been written,
because a dialog pointed at a directory that does not exist opens wherever Qt feels like.

Shown non-vacuous, one mutation at a time on `tests/test_open_layouts.py` (13 checks as shipped, 0
failures): the menu rebuild stops re-adding the entries this window opened by path → 1; the by-path
open stops remembering its file → 2, the reopen and the menu entry; `apply to the panel` stops
refusing a by-path layout → 2, one per refusal, and both also assert nothing reached the stub
control; the path door stops refusing a 4:3 layout → 1; stops refusing a JSON that is not a layout →
1; stops delegating a library file to the name door → 1; the two buttons fold away with the knobs →
5; the state line stops saying which file the buffer came from → 4; the dialog stops opening where
the copies live → 1; the model stops recording the file it read → 3.  Back as shipped: 0.

What is **not** added, on purpose: remembering which layout was open across restarts.  The owner
asked for the two doors above and not for that, and `layout` is not a session key - so a new window
starts at `(nobody: preview the theme above)` and `reload the list` is how the names come back.


### The installed check met a machine that had been used (2026-11-13)

The 0.7 .deb files were built on the bench and installed on the owner's desktop - which is
the first time `debian/tests/smoke` ever ran on a box that had been *used*.  It died in its
last section:

```
AssertionError: (24, 4, 27, "the installed library's layouts are not all accounted for
by `themes.scan()`")
```

Nothing was wrong with the install.  The assert added up what `themes.scan()` returned and
compared it to what the package's own manifest lists, and those two quantities differ on any
box where somebody has saved a layout, because `themes.roots()` puts
`$XDG_CONFIG_HOME/xigmalcd/themes` **in front of** the installed library - on purpose, since
that is the whole mechanism behind "edit a copy, keep the original".  23 selectable + 4
refused = 27 installed, plus one `alpha_new.json`, answered 28 names.  Two more asserts in
the same block sat on the same sand: the pairing asked every *picked* layout to name a clip
the themes package had installed beside it, and a copy of `alpha` declares no background at
all.

The accounting is per root now, and it names the states it finds: each installed layout file
is answered-from-the-package-and-selectable, refused-with-a-reason, or **hidden behind a copy
of yours at the same name** - the last of those printed with the names, because it is the
state a person is usually in without noticing.  The paint loop still walks everything
selectable, copies included, since a copy is what a loop actually draws; the pairing claim is
the package's own, so it walks the package's own records.

| the box | installed files | answered from the package | refused | hidden behind a copy | this box's own, in front |
| --- | --- | --- | --- | --- | --- |
| nobody has edited a theme | 27 | 23 | 4 | 0 | 0 |
| one copy at a new name | 27 | 23 | 4 | 0 | 1 |
| one copy at a vendor's own name | 27 | 22 | 4 | 1 | 1 |

Then the fixed block found a fault that had nothing to do with accounting.  To exercise it,
`tests/test_smoke_accounting.py` writes a JSON that parses, declares `1:1` at 480×480 and
carries no `osd` at all, and `layout.draw_theme` walks `obj["osd"]["widget"]` - so the
painter raised **`KeyError: 'osd'`**.  Which meant `scan()` had been selecting on `ratio`
alone, and such a file in a person's own themes directory was a name `--theme` accepted and
the frame loop crashed on.  The writer has refused an empty layout since 0.6
(`themes.save`), so this was the reader missing the same rule, and it is in the reader now:
`scan()` marks a record unusable with a `why` and a `why_code`, `resolve()` refuses by that
same mark, `why_not()`, `--theme`, `--check-theme` and the editor's `open a file…` all print
`themes.NEED_OSD_WHY`'s one sentence, and `--list-themes` counts the refusals out instead of
saying "refused":

```
  not_a_layout junk-id  480x480 ratio 1:1  NOT PICKABLE: no `osd` with a `widget` list, ...
  23 pickable, 5 refused: 4 on canvas, 1 with nothing to draw
```

What was deliberately **not** done: `scan()` does not run `validate()`.  The loop re-resolves
its theme name on every frame, and validating 27 layouts - 152 widgets, key by key - on every
frame is a cost this repository has never measured, so the reader asks the one predicate the
painter actually needs and `--check-theme` stays the door that prints the detailed report.
That is written as a limit in docs/limits.md rather than left as an unstated difference
between two doors.

Gated, and shown to bite: `tests/test_smoke_accounting.py` (5 checks) *extracts the shipped
heredoc from `debian/tests/smoke` and runs it*, against this checkout's copy of the same tree,
in the three states above plus the unusable file, with the CLI cross-check aimed at this
tree's entry point rather than whatever `xigmalcd` the package manager left on `PATH`.  As
shipped: 5 checks, 0 failures.  Put the old identity back (`len(pick) + len(rej) == len(…)`)
and 2 of the 5 fail - the new-name box and the shadowing box - and the static check that reads
the script fails a third time, because it looks for the per-root wording by name.  Drop the
new reader rule and `tests/test_theme_files.py`'s check fails on all four doors at once
(`--theme` and `--check-theme` exit 0 instead of 2, `--list-themes` says `4 refused`, and
`resolve()` answers the junk name).

One real installed-system reading of the door fix, from the owner's desktop on 2026-11-13, the
command printed for it:

```
$ xigmalcd --check-theme alpha_new
  alpha_new (…): 480x480 ratio 1:1, 12 widgets, from your copy
  drawn from this machine's readings through `themes.paint`, the door the frame loop uses
  for a layout file: 12 boxes, 40390 lit px, skipped: nothing
```

Twelve boxes for twelve widgets, and nothing skipped - the same file that through 0.6's
`themes.paint` reported `temp-values` and `fan-figures` with no box at all.  What this is
*not* is a stage-6 transcript: it is the installed loop's own painter reporting what it
found, on a machine with a panel attached but the port untouched.  The `APPLY a layout file`
phase in `tools/display_glass.py` has still never been run, and the upgrade itself taught one
more thing worth recording: replacing the unit file under a running unit makes systemd say
`The unit file … changed on disk. Run 'systemctl --user daemon-reload'`, so an upgrade needs
the reload it names before a restart draws with the new code.


### What a press carries, and what a save does by itself (2026-11-13)

Three reports the same morning, all about one workflow, and none of them about a colour:

| what was reported | what had actually happened |
| --- | --- |
| "`save as your copy` immediately applies the textColor change of the special `temp-values` in `alpha_new`" | the design, working - and it worked because of an earlier press. `save` writes `~/.config/xigmalcd/themes/alpha_new.json`; a loop that already **names** `alpha_new` re-resolves that name every frame, so its next frame reads the new bytes. This owner's unit line says `--theme alpha`, so the name can only have got there over the socket - one `apply to the panel` they had pressed. That is the same press the next report calls useless, which is what made the pair look contradictory |
| "`apply to the panel` has no effect, if pressed before `save as your copy`" | half true, and the true half had been reported as success. Measured against a stub display: the press moved one setting - `args.theme`, the *name* the panel draws - and no pixels, because the picture comes from a file and the edit had never left this window's buffer |
| "making changes to `alpha_new` and pressing `save as` doesn't seem to have any effect, even if followed by pressing `apply to the panel`" | nothing written, twice. The button labelled `save as` was pressed with `alpha_new` typed into the box beside it, and `themes.new_name` refuses a name something already answers - `'alpha_new' is not a free name: your copy 'alpha_new' answers name 'alpha_new' today, at …`. `save as` reads as an in-place save, so the refusal looked like a silent success; the `apply` that followed sent the name the panel already held, which moves no pixel |

One sentence sits under all three, and it was already in PROTOCOL.md §11 and in the
state line - **a display is only ever told a name**.  `("theme", <name>)` is a whole
command; what the panel then paints is whatever that display's own `themes.resolve()`
answers, in the roots *that* process can read, or `render.theme_<name>` for one of the
five names drawn from code.  A layout file never goes over the wire.  So a save can
move the glass on its own, and an apply cannot carry a keystroke: they are not two
opposite buttons, they are two different objects - a file and a setting.

What was wrong is that the window reported the second case as a plain success.  It now
compares the two pictures before the command goes, and says the difference out loud:

* `xigmaui/app.py`'s `_frame_diff` counts pixels where two frames disagree, and the
  press paints both of them: the buffer through `Editor.paint`, and what the press will
  put on the glass through the door the display uses - `themes.paint` for the record
  `themes.resolve()` answers, `themes.draw(themes.export(name))` for a generated name,
  which `themes.parity` holds at **0** differing px against `render.theme_<name>`.
* One body and one instant - `Editor.fixture()` - for both frames, so the only thing
  the number can be about is the two pictures.
* Measured on this bench, with a `textColor` typed into the `temp-values` row and
  nothing saved: **6812 px between what is on screen here and the file
  …/alpha_new.json** - and **1914 px** for the same edit on the generated `gauge`, where
  the sentence names `render.py` instead of quoting a path that does not exist, and
  points at `copy to a new name` because `themes.save` refuses `gauge.json`.  Both
  figures are this machine's: a px count over glyph pixels is a face metric like every
  other one in these pages, which is why the press prints it rather than the page.
* The clean case is held too, so the sentence stays a difference rather than a
  disclaimer: after `save as your copy` the same press says nothing about pictures,
  because the pane and the file agree.
* A third branch, refused rather than painted: this window reads a file for that name
  and *that* display may not see the root it lives in.  No px figure is claimable
  there - the comparison would need the other process's roots - so the line says what
  the display will draw instead, and the display's own refusal still lands in the log
  in its own words.

The button in the third report is renamed `copy to a new name`, and its tooltip states
the refusal before the press (`'<name>' is not a free name`), points at `save as your
copy` for the layout already open, and says no file changes.  Nothing was loosened: a
second file at a live name is still refused, for the reasons the 2026-11-11 name-rule
section measured.  The apply button's tooltip gained the same fact, and the state line
under the rows says `edits in this buffer only: no file has them, so no display can
draw them` instead of `edit not saved yet`.

Twelve checks in `tests/test_apply_layout.py`, four of them new: the dirty press that
says the two pictures differ and changes no file; the clean press after a save that
must *not* warn; a generated name, which must name `render.py` and not quote a path;
and the whole reported copy sequence - re-ink, press the copy door at the open name,
count the user's root twice, press `apply to the panel`, compare the inks in buffer and
file again.

Shown non-vacuous the same way as every other cycle, one mutation at a time (twelve
checks as shipped, 0 failures): the comparison never spoken at all → **3**; the same
sentence spoken but only **after** the display has answered → **1**, which is what makes
the ordering in the first check a gate and not a flourish; the buffer clause dropped →
**3**; the pixel comparison made to answer **0** whatever the frames are → **3**; the
comparison taken against the pane's own frame, so it always agrees → **3**; the
generated-name branch dropped, so a code-drawn name is reported with a file it has
never had → **1**; the button relabelled back to `save as` → **1**; the state line back
to `edit not saved yet` → **1**; the apply button's tooltip clause dropped → **1**; the
copy button's refusal sentence dropped → **1**.  Back as shipped: 0.

What is **not** claimed: that the number is the same on another machine.  It counts
glyph pixels on the faces this box has installed, and the checks assert it is non-zero
for a changed row and absent for a saved one, never a value.  Nor is anything new sent:
no auto-save, no "apply writes your buffer" door, because the wire has no layout half
(§11) and a press that quietly wrote a file would be the second source of truth this
file model exists to avoid.


### `Pump Speed` got a rule the day the machine got a pump (2026-11-13)

Nine of the 23 selectable layouts ask for `Pump Speed` - `Theme_28`, `Theme_29`, `Theme_34`,
`theme_36`, `theme_37`, `theme_41`, `theme_45`, `theme_48`, `theme_49`, one `data` widget each,
at 197,370 / 197,350 / 193,358 at fontSize 20 and 173,341 at fontSize 32.  The tree's answer
was a constant: `themes.UNMAPPED` held one sentence and `values()` applied it **last**, over
whatever the body reported.  Reading that back showed a fault that had nothing to do with
hardware - handing `values()` a body with five fan rows, one of them
`{"type": "Pump", "name": "CPU PUMP", "value": 2410}`, answered `Fan 3` and `Fan 4` and still
refused `Pump Speed`.  The name had a rule-shaped hole in it.

The second fault was the sentence's own claim: *"`tools/fanscan.py` has never looked for one"*
was true, so it was run.  On the wiring of that day: 10 tach inputs, 2 turning (`fan1`
1692-1957, spread 265, tracking `pwm1` and k10temp 53-76 °C; `fan12` 1525-1575, spread 50),
and 8 reading 0 in all 30 samples - `fan2` among them.

Then the owner re-wired the box - six case fans to the cooler's own ARGB controller, the AIO's
block cable to `PUMP_SYS1`, its radiator fans to `CPU_FAN1` - and the same command answered
differently on the same kernel:

| channel | before the re-wiring | after | |
| --- | --- | --- | --- |
| `fan1` | 1692-1957, spread 265 | 1503-2010 across three windows, spread 135-306 | the cooler's fans: it follows `pwm1` and the CPU |
| `fan2` | 0 in every sample | **2443-2469**, spread 10 under a 24-thread load and spread 5 at rest | the pump: the channel that appeared when the block cable moved |
| `fan12` | 1525-1575, spread 50 | 0 | its fan moved to the controller |
| `fan3`, `fan4`, `fan11`, `fan13-16` | 0 | 0 | nothing plugged in |

The pump was identified by two shapes rather than by a name, and the pairing matters: its
header's duty matched `pwm1` sample for sample (raw 204-231 in one window, 152-182 in another,
identical spread 27) while the tach moved by 10 RPM - a fan on a ganged header follows the
curve, a pump does not.  `FAN_CHANNELS` gained `("nct6687", "fan2") = ("CPU PUMP", "Pump")`,
and `themes.FAN_TYPED = {"Pump Speed": "Pump"}` answers the vendor's name from a row's **type**.
`tools/fanscan.py --watch` samples the `pwm*` outputs in the same window now, because that
pairing is the evidence and it had to be printed somewhere a reader can re-run it.

The rule deliberately reads nothing else.  `{"type": "Fan", "name": "CPU PUMP"}` answers no
`Pump Speed`, and `{"type": "Pump", "name": "nct6687 fan2"}` answers 2410 - that pair is the
first check in `tests/test_pump_speed.py`, and it is the line the old code's comment said it
would not cross ("matching a fan row by name would be a guess wearing a rule").  A row reading
0 is no reading, as it already is for the empty headers `sensors.fans()` drops.  And a bug found
while writing it: `render._tach` chose the CPU fan by a substring of the name, so a pump-only
body printed `CPU FAN 2410 RPM`; the type is read first now and the same body prints
`PUMP 2410 RPM`.

What that buys, printed by the check and not gated as a value: the nine files gain exactly
**one box each** and nothing else changes anywhere in the library - 563 px at size 20 for seven
of them, 1181 px at size 32 for `theme_37` and `theme_41`, on this bench's faces at a pinned
2453 RPM.  (A what-if probe the day before, painting 2410 RPM instead, printed 555 and 1123 for
the same nine rows: the digits are what changed, which is exactly why these are printed and not
asserted.)  Through the CLI: `--check-theme Theme_28` here reads `7 boxes, 20 036 lit px,
skipped: nothing`, where at the suite's pinned body (`fixtures.SESSION`, which carries no fan
rows at all) it is still `6 boxes … skipped: Pump Speed`, and 23 layouts land at 114 painted
boxes with exactly nine reporting one missing source.  `--list-themes` stopped printing the gap
line here because it now asks `themes.values(sensors.collect())` instead of a constant, so the
refusal - `themes.ROW_WHY`, which names `tools/fanscan.py` and the pin table and says nothing
about "this box" - is a per-body fact on every machine.

Two findings about `/etc/sensors.d`, both measured and both written into docs/usage.md, because
the second one contradicted what this repository's author had just said out loud:

* **a label written there never reaches this program.**  `nct6683` publishes `temp*_label` and
  no `fan*_label` at all; the labels `sensors` prints come from userspace `libsensors`, while
  `sensors.py` reads sysfs.  Re-measured on the rewired box: `driver label: -` for all ten
  tach inputs.  The pin table is the only route from a header to the glass.
* **lm-sensors halves a `pwmN` before printing it, so its default percent is wrong.**  Raw and
  display read in one breath: raw 174 → `87%` with no config, `68%` with
  `compute pwmN @/1.275` - and 174/255 is 68.2%, so the config line was right and a suggestion
  to delete it was wrong.  Raw 255 would print `127%` on a default install.  Parenthesising the
  expressions changes nothing; both spellings were run.

Ten checks in `tests/test_pump_speed.py` as this section was first written, 0 failures, 0.9 s;
the file stands at **eleven** now, the eleventh being the `xigma.showIf` gate recorded below -
and `grep -c "^    def test_" tests/test_pump_speed.py` prints it, because a count of checks is
an output, not a fact worth keeping.  The seven mutations and what each
cost: the rule reading a name instead of the type → **1**; the zero guard dropped → **1**;
`ROW_WHY` stripped of both command names → **2** (the in-process one and the CLI one); the pump
taken out of the pin table → **1**; `_tach` back to name-first → **1**; `FAN_TYPED` emptied,
i.e. the blanket refusal restored → **6**; `--list-themes` back to a constant → **1**.  Back as
shipped: 11 checks, 0 failures.

One unlocked door that the census does not show on its own: because `Pump Speed` is in the
vocabulary now, it is a legal `xigma.showIf` dependency.  A row gated on it draws where a pump
is sensed and is **silenced and reported** (`showIf:Pump Speed`) where it is not - 13 boxes
against 12, the gated line 1 376 px on this bench's faces - which is how a layout can carry a
pump label without carrying a hole on a box that has no pump.

What is **not** claimed by that paragraph, and was corrected later the same day: the sentence
above says the firmware has never been *asked* about the string `"Pump"`.  It has been - see the
next section, `tools/blob_probe.py`, and PROTOCOL.md §8.  What survives the asking is the other
half: the panel does not reject it, and nothing about that run can show the panel **reads** it,
because no reply to a `STATE` frame carries a body.  Also still true, and not changed by the
probe: the pump's *duty* is not its *speed*.  `pwm2` at 100% is a real reading of this box and
`Pump Speed` filled from it would be a lie, which is why the source stays refused on a machine
that reports no pump-typed row.  And the six case fans are out of reach: no new hwmon chip
appeared (12 before, 12 after, each named), and the only non-panel oddity on the USB bus is a
Jieli device bound to `snd-usb-audio`.  `Fan 3`/`Fan 4` will fill when something is plugged into
a sensed header - `fan3`, `fan4`, `fan11`, `fan13-16` are waiting there with their `min` and
`pulses` files - and nothing else has to be written for them to answer.


### Eight disk names, and the one measurement that made them possible (2026-11-13)

`themes.DISK_SLOTS` is the same machinery as the fan slots: four positional pairs,
`Disk 1 Temperature`/`Disk 1 Name` … `Disk 4`, answered by index into `sensors.drives()` and
reported, in words, when a slot has no drive behind it (`this box reports 2 drive rows in
`drives`; slot 3 has no name`).  The first two of those pairs are drawn by our own `bars` as of
2026-11-14 - the claim in this section that "nothing shipped asks for any of these names" was
true for one commit and is not any more, and it is left here with that note rather than rewritten,
because the measurement it records is the one that made the rows possible.  The vocabulary the editor's `source` menu offers went from 29
names to **37**; `layout.VENDOR_FORMAT` grew the same eight shapes, which is what
`tests/test_bars_rows.py` requires of every answerable name - a source with no shape is a row
that prints nothing at all.

Two things had to be settled first, and only one of them was a design choice.

* **The blob section.**  A per-drive row is not a display change, it is a wire change: the
  vendor's `STATE all 1` body has one `disk` scalar, so `Disk 2` needs a `drives` list the
  panel has never seen.  That was asked, on the glass, rather than argued about:
  `tools/blob_probe.py` sends the vendor-shaped control, the control plus a fan row typed
  `Pump`, the control plus a `drives` section, both together, then the control again, and
  uploads one ordinary frame afterwards.  Every body answered
  `<Message 1 200 {AckNumber, CkOK:True} b''>` and the 11 668 B frame after them was accepted,
  `space` and `osdState` unchanged (`data/glass/2026-11-13-223617-blob-probe.txt`,
  PROTOCOL.md §8).  What the run cannot show is whether the panel parses the section - there is
  no read-back for a `STATE` frame, and the only topic that would make the panel draw these
  numbers itself is `realtimeDisplay`, which ALPHA sends only to an `OS === "RTOS"` unit.
* **Ordering, which the slots make load-bearing.**  `sensors.drives()` sorts **the drive under
  `/` first**, then the rest by controller (`nvme0` before `nvme2`), never by the number the
  kernel happened to give the hwmon directory - because a slot is a thing a layout names and a
  reader expects to mean the same drive next boot.  Root-first is what lets a block mark the boot
  drive by position (`layout.VENDOR_FORMAT["Disk 1 Name"]` prints `nvme0 /`, the other slots plain)
  and what makes `Disk 1 Temperature` the same reading as the scalar `disk.temperature` whose
  capacity sits beside it - an equality a check now asserts, and it is not vacuous here: the
  second drive's composite is 31 °C against the first's 41.  The built tree in
  `tests/test_sensor_rules.py` puts `nvme2` in `hwmon7` - first in walk order - on purpose, so a
  regression to walk order moves the 55 °C drive into `Disk 1` and fails.

Two runs asked the questions badly before a third asked them straight, and both
transcripts are kept.  The first (`183954`) built its control from `sensors.collect()`
as it stood, and on this box that already reports the pinned pump channel - so control
and experiment both contained the `Pump` value and the pair could not have
distinguished anything.  The second (`184215`) stripped the Pump type and fixed that
half, but it sent a `drives` payload the probe had assembled itself (`0.1` degrees, no
sort) instead of the `sensors.drives()` that shipped later the same evening, so it
certified a near-miss of the body that goes on the wire.  A third fault of the same
family was caught by the checks and never reached the panel: once `collect()` grew a
`drives` section, the tool's `base = dict(raw)` control carried that key as well.  The
tool now builds its control by removing **both** values and takes the rows from the
shipped door, and the checks assert the control contains neither value while the
experiment body contains the string `Pump` exactly once.

The census behind that claim, and the **set** each figure counts, because this page already
carries two of them and a bare number invites the wrong comparison.  Walking every `property` of
every layout and taking the `source` values:

* the 27 installed files (23 pickable + 4 refused) name **12** distinct sources over **82**
  source rows - the row this page's own surface table already quotes, and it ties exactly;
* the 23 pickable files alone name **7**, which is what `--list-themes` prints as "sources the
  pickable set asks for";
* the **28** layouts a reader can actually pick on a clean `$XDG_CONFIG_HOME` - those 23 files
  plus the 5 exports this repo draws out of code - name **22** distinct sources over **108**
  source rows, and **21** more `content` literals if the fixed texts are counted with them
  (43 in the union; 179 rows carrying at least one).  Those five figures are printed, not
  recited: `python3 -m unittest tests.test_row_notes` now ends with a **name census** line next
  to the source census, and it moved when `bars` grew a `Fan GPU` row and dropped a fan slot
  (21/106/20/41/176 -> 22/108/21/43/179 in one commit) - which is the reason the door exists.

The earlier figure this page and the changelog carried said "30 `source`/`content` names across
the 28 files", and it was neither of those counts - corrected the same evening it was written,
and the rule is here so the next reader reproduces the number instead of trusting either.  What
the disk slots rest on is the qualitative half, which all three sets agree on: **not one** of the
12, the 7 or the 22 is storage-shaped.  Printed rather than recited - and this is the list the
print gives today, so a reader who doubts the count runs the door rather than trusting the
sentence: CPU Frequency, CPU Temperature, CPU Usage, Date, `Disk 1 Name`, `Disk 1 Temperature`,
`Disk 2 Name`, `Disk 2 Temperature`, `Fan 1 Name`, `Fan 1 Speed`, `Fan 2 Name`, `Fan 2 Speed`,
`GPU Fans Speed`, `GPU Memory Rate`, `GPU Temperature`, `GPU Usage`, `Motherboard Temperature`,
`Pump Speed`, `RAM Rate`, `Time`, `Used GPU Memory`, `Used RAM`.  Note what is **not** in it:
`Disk 3`/`Disk 4` and `Fan 3`/`Fan 4` are answered names that no layout on this canvas asks for
any more - `bars` draws two slots of each kind - and so is `Disk Temperature`, the scalar.  That
is the difference between the vocabulary (`themes.source_names()`, 38 names) and the corpus
(22), and the gap is where a shape-with-no-source used to hide.  The 12 differ from those by dropping the fan slots the refused files never reach and
adding four the pickable set never names - `CPU Power`, `GPU Power`, `Upload Speed`, `Week`.

The other change in this stretch is a rule the owner chose over the one I had written: within a
board tier, `Motherboard Temperature` prefers the channel the driver labels a **diode** over the
tier's hottest candidate.  Measured here: diode 41.5 °C, thermistors 43.0 - the row prints 42
where the maximum printed 43.  The built tree sets the diode deliberately cooler than the
thermistors so that preference cannot be satisfied by accident, and one check asserts the
label that won contains "diode".


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
  That, not the drawing, was the new surface - and it is what `tests/test_canvas.py` is: real
  press/move/release and key events handed to the offscreen pane, asserting the model's
  `x`/`y` moved by the right number of panel pixels. There is still no `QTest` in this
  environment, so `tests/test_canvas.py` constructs the `QMouseEvent`/`QKeyEvent` objects itself.
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
  and the marks live in the pane's paint event, held by `tests/test_pane_chrome.py`
  comparing what it was shown with a mark up and with none.

## What it cost, and what is still owed

The estimate the plan carried, written 2026-11-08 and kept here as an estimate rather than
a result: **10-12 sittings, 30-36 hours**, of which a useful first cut - stages 0 to 3 plus
the inspector half of stage 4 - was **6-7 sittings, 18-21 hours**, because that part edits
real vendor themes with nothing gated on glass time. A sitting was about 3 focused hours at
this repo's standard: the claim measured, the number gated, the page updated in the same
change.

What the stages turned into, in the order they landed: the resolver and `--list-themes`, the
export machinery and the file model on 2026-11-08; the editor's model with the window's row
over it and the canvas in that pane the same day; `bars` as a generated file and a changed
drawing on 2026-11-09; rows added, removed, reordered and resized on 2026-11-10; the peek on
2026-11-11; and on 2026-11-12 the peek split into a live body and a held one with its knob
moved above the picture, the two painters' value tables made into one, and the two doors that
decide *which file* the editor's box holds.  On 2026-11-13 the check that runs against a real
install met a machine that had been used, and the layout **reader** learned the rule the
layout writer has always had; later the same day three reports about the save-and-apply
workflow turned into a pixel comparison between the pane and the picture a press will make,
and one button renamed for what it actually does.  What has not run is stage 6 - on glass.

Optional, half a sitting: re-read the vendor's renderer bundles with
`tools/asar_extract.py --cat out/renderer/assets/themeUtil-*.js` so every spin range and
default in the inspector is the vendor's own constant instead of our census. No JS bundle
from the vendor app is tracked here - only their file names, in PROTOCOL.md section 10 -
so it needs the installed app off the Windows machine again.

### Six harness rules, each found the expensive way

Four of them failed in the check rather than in the program, which is why they are in `tests/`
and not in a cautionary note.  The fifth is about the sitting itself, and it cost two bogus
suite logs before it was understood.  The sixth is about the machine under the check, and it
cost a CI run that went the other way: the same check, the same 526 checks, green on one runner
image and red on the next.  That one ships with a command.

* **A shared body is an input, not a scratch pad.** `Editor.fixture()` once returned
  `dict(FIXTURE)`: one level deep, so every inner dict was the module's own object. A check
  that punched `memory.total` out of the body it was handed punched it out of the pinned
  pair, and every later draw in that process had no `RAM Rate` row - so the live fixture
  answered 20 of the 21 `source` names the library asks instead of 21, and the only visible
  trace was a census of drawn boxes two short. Both machines printed the same wrong counts,
  which is what made it look like a rendering difference. `tests/test_editor.py` holds the
  rule on the editor's side: it punches the key out of what `fixture()` hands out, then
  requires `edit.FIXTURE` to still hold it *and* to still equal a fresh `ast.literal_eval`
  of the literal in `edit.py`. `tests/test_export_parity.py` holds it on the shipped side:
  neither `themes.parity`, `render.draw` nor `themes.values` writes to the readings it is
  handed, over all six themes and all five shared bodies. The cost of getting it right is
  nothing: the deep copy measured 0.004 ms as the median of 200 on the author's bench,
  beside a layer draw measured in milliseconds, and nothing re-times that pair, so the
  figure belongs to that sitting.
* **A compare between two pictures has to say *when*.** CI's run 43023694060 lost a byte
  compare of one layout against itself because a second went by between the two draws: the
  generated themes read `render._now()` for their clock line, and the two frames differed
  inside one 18x22 bbox - the last digit of a time the machine painted. What came out of it
  is asserted in `tests/test_theme_files.py`: the same layout drawn twice with no pinned
  instant has to differ, and drawn twice at one pinned instant it has to be one picture
  byte for byte. The other half of that check - a display loop drawing a name that has just
  been renamed out from under it, falling back to the stock skin and saying so - was never
  ported, so the race itself stays a gap: `xigmalcd --theme <copy>` is the door to
  re-measure it at, and a byte compare that suspects a race should print a differing-byte
  count and a bbox, which is what that one did.
* **A repaint is an event, not a no-op.** A passage that asserted "a press on empty glass
  leaves no mark" was reading a timer tick another check had queued.
  `tests/test_pane_chrome.py` holds the honest version: the marks are up, then cleared, the
  two readings compared with no repaint between them, and the mark required back after a
  repaint - because the chrome follows the selection, not the last press.

The fourth rule is about figures rather than fixtures, and it is held the same way:
`tests/test_row_acts.py` prints every count that follows the fonts on the box that drew
them - the adds, the placement triple, both sides of the reorder census - before it holds
any of them to a labelled half, so one red run answers for all four. What stays asserted is
membership: a run's answer has to be one of the halves the page labels, so a third machine
is a sentence to add rather than a range to widen. docs/gui.md carries those halves; this
page does not repeat them.

The fifth rule is about the sitting rather than the code, and it was bought with two useless
logs on 2026-11-13: **a mutation sweep and a suite run must not overlap.**
`tests/test_specials.py`'s door-marker check reads `inspect.getsource(fn)` - the file on disk
at the moment it asks - while every other check works from a module the interpreter imported
once.  Running the seven pump mutations while two full suites were in flight made that check
report `'values' != 'pair'` and `'pair' != 'line'` about markers nobody had touched: the
script was rewriting `themes.py` underneath the runs, the source line table had shifted, and
what it read was a neighbouring function's body.  Nothing in the tree was wrong; the
measurement was.  The same thing applies to editing a page while a suite that *reads that
page* is running - `tests/test_bars_rows.py`, `test_ink.py`, `test_knobmap.py`,
`test_specials.py` and `test_glass_ledger.py` all quote these documents - so the suite figure
a changelog entry carries names one run taken with nothing else in flight, and the two
contaminated logs from that afternoon are worth nothing except the rule above.


And a sixth, from the same afternoon, which comes with a command rather than a caution: **a
check may not assert what the host happens to expose.**  Six of this session's faults were
that shape - a mount table that names `nvme0` (#190), a `disk` section implying a
`temperature` key (#191), a drive whose temperature holds still across a function call
(`38 != 39`), the same drift re-committed in a new check an hour later (`[44, 58, 68]` against
`[44, 59, 68]`), a call named in a file being a call that runs, and a probe check asserting
its drive list was non-empty.  That last one is the proof, because **the check was identical in
two runs with opposite outcomes**: #193 ran 526 checks green in 431.661 s, #194 ran the same
526 to one failure in 460.878 s, and `git diff --stat e69c5d7 61b1d6a` is eight lines of
`debian/changelog` prose.  Some runner images publish a disk temperature chip and some do not,
so both of those runs were luck.

So the audit for this class is not reading the tests and hoping, it is
`tools/audit_bare_runner.py`: it points `sensors.HWMON_GLOB` at a pattern that matches no
directory - a box with no hardware-monitoring chips at all, stricter than any runner - and
re-runs every test module that names a live sensor door.  Which modules those are gets
**derived from each file's AST**, not from a hand-kept list and not from grep: a prose mention
of `sensors.collect()` is not a reader, while `sensors.collect = lambda: body` is one (that
assignment is a module admitting it would otherwise touch the machine).  The one hand-kept part
is `EXTRA_MODULES`, for the case the AST cannot see - a test that runs a shipped CLI in a
subprocess, where the live call happens in the child - and `tests/test_bare_audit.py` requires
those entries to be genuinely invisible to the derivation, so the two lists cannot overlap into
a second copy of a rule.

The tool prints its own tally rather than having it quoted: on 2026-11-14 the whole audit
reports **96 checks over 6 modules, 0 failures, 0 errors** in about a minute, with `0 chips
visible, 0 fan rows, motherboard() -> {}, drives() -> []`.  That number went 95 -> 96 when a
check was added to `tests/test_sensor_rules.py` one commit later, which is why these pages
name the command instead of the figure - the same rule the sensor readings obey.  A
module that goes red there is asserting what the host exposes, and the repair is the same two
moves every time: construct the inputs, or assert a relation instead of a reading.

One more thing that audit taught, about censuses rather than code.  Breaking the tool's
`finally`-restore the first time produced a mutation that **did not parse**, so the test module
failed to import and the driver counted "0 failures" - a free pass in a census whose entire
purpose is to notice a missing guard.  The driver now parses the mutated file before trusting
the number and prints `NOT MEASURED` when it cannot, and the mutation was rewritten to be
syntactically valid (`finally:` kept, its body made a no-op).  Six mutations, each counted
after that fix: the substitution pointed at the real tree -> 2; the derivation finding nothing
-> 4; the finder degraded to a text grep -> 2; the walk never restored -> 1; a derived module
also listed by hand -> 1; the tool not reporting what it substituted -> 1.

## What this document does not claim

It was written before any of it existed, so read it as part record and part plan.  What
does **not** exist in this tree:

* a snap to a grid. The corpus carries none, so a snap answers a neighbour's own number
  instead, which is the rule `tests/test_snapping.py` holds the pane to;
* a unit for the `space` the panel reports. The panel's own vocabulary has none, so nothing
  here invents one;
* a glass pass. No canvas, inspector or preview claim on these pages is measured on the
  panel, and the rows that owe one are listed in docs/limits.md;
* a table of the vendor's defaults. Its application bundles are not in this tree, so the
  copied files are the evidence, and `--print-theme-fields` is how they are read out.

What does exist, gated rather than asserted in prose: the six exports and their zero-diff
parity (`tests/test_export_parity.py`); the generated `bars` file, its rows - twelve as of
2026-11-14 - and its two memory rules (`tests/test_bars_rows.py`); the file model with its save, revert, rename and
delete doors (`tests/test_theme_files.py`); the editor's model and the doors over it
(`tests/test_editor.py`); pointing, dragging and the marks (`tests/test_canvas.py`,
`tests/test_pane_chrome.py`); the row acts and the reorder census
(`tests/test_row_acts.py`); the peek's two frames and what may differ between them
(`tests/test_peek_readings.py`); the `special` rows `alpha` declares, the value table they read and the
two doors painting one saved file the same (`tests/test_specials.py`); and the library and field counts
(`tests/test_theme_library.py`, `tests/test_field_census.py`).

The census rows are no longer a one-off `python3 -` pass: the library counts, the field
counts, the round-trip and copy identity, the refusals and the `line` measurement are all
re-derived on every run, on two machines. Where a row still rests on the 2026-11-08 queries
written out above, it says so; the sitting estimates under "What it cost, and what is still
owed" are estimates, stated as such.
