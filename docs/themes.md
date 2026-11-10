# The themes, and where their shapes come from

The five themes this project draws, what `alpha` is a redraw *of*, and the geometry that decides how big a number can be inside a gauge ring. The vendor's own library - 27 themes, their layouts, their clips and their baked overlays - is in `themes/alpha/`, and that directory's `README.md` is the write-up of the container, the cipher and the layout schema.

## The 27 vendor themes are not in the picker, and that is not an oversight

`xigmaui`'s theme list takes `sorted(render.THEMES)`: `alpha`, `bars`, `clock`, `dual`,
`gauge`. Those are the pictures **this program** draws from live readings, and the window
lists only what it can preview. `xigmalcd --theme` takes those five **and** 23 of the vendor's 27
layout files, by the name of the background each one declares - `Theme_07`,
or the numeric id `1757491588804` - painted by `xigmalcd/layout.py` at the canvas the
file itself declares and uploaded as an ordinary `.osd` frame. What has never happened,
and still has not, is sending a theme file to the panel:

That declaration is a field, not a naming convention: `background.mediaFile`, and the 23
selectable layouts name 23 different clips between them - no two layouts share one.
`themes.pair(NAME)` reads it, `--list-themes` prints it, and the window follows it:
opening a layout puts that clip under the preview unless the reader has ticked *keep my
background* (docs/gui.md). The five themes this repository draws from `render.py` are not
vendor pages, so there is no vendor record to read for them: they pair with the backdrop
their own published picture is composited over, kept in `themes.CODE_CLIPS` and derived
back out of the README's `<theme>-<clip>.mp4` names by `tools/selftest.sh` on every run.
Three of the four canvas-refused files name clips as
well, and one names a `.png` rather than a clip - one more reason the refusal is keyed on
a file's own `ratio` field rather than on what sits beside it.

* the `.thm` files (27 of them, 6.8 MB at the largest, 66 300 082 B together) are the
  panel-side theme definitions the Windows app decrypts and interprets -
  `tools/thm_unlock.py` opened them with the app's constants to learn what is in them,
  which is a *reading*, not a path back to the device.  They are no longer in this
  repository: since 0.3 the tree keeps the 27 unpacked layouts, the media, and the
  containers' vendor path + byte count + sha256 (`manifest.json`'s `notRedistributed`),
  not the vendor's encrypted originals.  Anyone who wants them installs the vendor's own
  software, which is where this copy came from - `themes/alpha/README.md` names the
  download and the path it lands at, and `--verify --from DIR` re-hashes our record
  against whoever has it;
* the control socket's file gate (`xigmalcd/control.py:check_media_file`) accepts
  `.mp4`, `.png` and `.osd` only, so a `.thm` could not be uploaded through it even
  by hand;
* and the panel is not asked what theme it holds, because it cannot be
  (PROTOCOL.md §11).

The same files also say what colour their lettering is, and the honest answer
is **mostly white, not all**.  Counted across the 23 `480X480` layout files -
the ones the panel's size, byte-identical to what the themes package installs, and
re-derived by the suite's vendor-library section so the sentence cannot rot:

| what | measured |
|---|---|
| `textColor` values in those 23 files | 106, in 9 distinct spellings |
| …that are `rgba(255, 255, 255, 1)` | 88 |
| files whose text is exclusively white | 18 of 23 |
| files mixing in other colours | 5 — `rgba(62,62,62,1)` ×6, `rgba(34,31,31,1)` ×4, `rgba(204,253,255,1)` ×2, `rgba(24,91,105,1)` ×2, one each of `rgba(0,0,0,1)`, `rgba(3,0,34,1)`, `rgba(0,255,229,1)`, `rgba(0,255,113,0.87)` |
| the theme ALPHA has selected (`1757491589871`) | 6 of 6 white |
| `store.json`, this machine | 160 values, 125 white, 13 distinct |

So the window's `text colour` row and `--text-color` do not try to change a
vendor theme's lettering at all: they repaint the layer this program draws.  A
vendor theme's text is decided by that theme's own layout file, and the only way
to change it would be to send the file - which is the thing this section is about
not doing ([docs/gui.md](gui.md)).  It also matters to the claim PROTOCOL.md §10
used to make ("every glyph on this panel is white"); that is now written as what
was counted - white for the selected theme and for the majority of the library,
not for all of it.

What the library **is** good for here, both of them used: its 27 layouts are the
measured geometry the `alpha` preset was redrawn from (`xigmalcd/layout.py`, and the
paragraph below about rings and text sizes), and its media is uploadable -
43 clips and 28 images per install, all 43 clips under the socket gate's 8 MB ceiling
(largest `clips/Theme_22.mp4`, 7 662 077 B) - and note what ffprobe says about them: 40
of the 43 are 480×480 like the panel, **3 are 320×240**, and by rate **23 are 24 fps and
20 are 20 fps** (the 20 fps group is 17 of the 480×480 files plus all three 320×240 ones;
loop lengths 0.96 s to 34.04 s, median 9.96 s). That rate split is why the window's
playing preview paces by the file's own `r_frame_rate` rather than by a constant: a
hard-coded 24 would play nearly half the library at the wrong speed, and 22 ms of ffprobe
per clip is what buys that (docs/gui.md). so the vendor's own library
ships backgrounds the glass is not the size of and nothing here has measured what the
panel does with one (docs/limits.md). Two uploads from that library have been measured on
the packaged unit's own path: `themes/alpha/clips/theme_47.mp4` at 1 211 106 B,
`notice 200 in 1.0 s`, and `themes/alpha/foreground/1757492775624.png` at 3 409 B,
`notice 200 in 0.3 s`. Whether the panel *displays* a still PNG is the one half of that
nobody has looked at the glass to confirm, so the window's picker still lists MP4 rows
only (docs/limits.md keeps that as an open item).

All of that is about *this* program not sending those files, and it stays true: the panel
is never handed a theme, and no plan here changes that. Two things follow from drawing
them here instead, and both are gated in `tools/selftest.sh` rather than asserted here:

* **23 of the 27, on the canvas.** The gate reads each file's own `ratio` field: 23 say
  `1:1` (480×480, the panel's size) and 4 say `4:3` (320×240). The four are refused, with
  the reason printed by `--list-themes` and by a bad `--theme` argument: the em-box anchor
  convention that every text widget in a layout is drawn by was measured at 480, against
  the vendor's own baked overlay (`render.py` records it, `tools/theme_check.py` measures
  it per theme), and scaling an unmeasured convention by 1.5 would put a guess on the
  glass. Keying the gate on `ratio` instead of on the directory name is deliberate: a
  future 480×480 layout must not be filtered out by a path rule.
* **7 metric names over those 23, in 82 widgets' worth of counts**: `CPU Temperature` 17,
  `CPU Usage` 15, `Time` 11, `Pump Speed` 9, `GPU Usage` 6, `GPU Temperature` 3,
  `CPU Frequency` 2. 14 of the 23 need nothing this program has no reading for; 9 ask for
  `Pump Speed`, which this box has never been scanned for. A layout whose metric has no
  reading draws **without that widget** and prints why - a hole that says what it is,
  rather than a zero that reads as a measurement. Faces are substituted the same way and
  said out loud (`arial` -> Liberation Sans, `simsun` -> Noto Sans CJK), because no
  Microsoft fonts are installed here, and the three metric shapes that are this repo's
  choice rather than measured off the vendor's picture (`Time`, `CPU Frequency`,
  `Pump Speed`) are named in the same note.

What is **not** built is an editor drawn from live readings, and a resize that ignores
what a kind owns: there is no scale-everything handle, and no snapping to a grid or to a
neighbour.  Stretching a row by dragging one of the squares on its box went in on
2026-11-10, through the size keys the painter reads for that kind - `width`/`height`
for a `bar`, the pair `line_rect` declares (swapped for a row turned 90°) for a `line`,
the ring of an `arc` scaled with its box, the `fontSize` of a `text` row, the pitch or
the face of a `special`; and so did the rows themselves - added only as a copy of one
that already draws, removed never past the last, reordered through the list that is the
draw order (the bullets, and the digits they hold, are in docs/gui.md).  What **is**
built, since
2026-11-08, is the window's `Layout` box - one layout, one widget, **every field that
widget carries as a row of its own** (10 rows for a `text` widget through 18 for an
`arc`), over the same model the suite drives headless: a layout file under
`~/.config/xigmalcd/themes` is read before the vendor's copy of the same name, a copy
made for editing is byte-identical to the file it came from (23/23), a save is atomic
and keeps a `.bak`, and deleting your copy puts the vendor's back in front. All of it
is offline behaviour: the panel is still handed nothing but `.osd` frames
(docs/usage.md has the `--check-theme` door that reports which file is drawing, and
docs/gui.md what one edit is worth in pixels). The plan, the census it rests on
and the parts that stay gaps are written out in [theme-editor.md](theme-editor.md).

## The `alpha` theme, and its rings

`alpha` is the vendor theme made by redrawing, widget for widget, the theme the vendor app
currently has selected on this panel (`store.json` → `currentThemeId 1785506775818` =
`presetTheme[26]`: big CPU temperature, CPU and GPU usage with bars), with things that
theme has no widget for added: **GPU temperature** in its own column next to the CPU
one, a **gauge arc around each temperature** (30-100 °C, the fill's position *and* its
colour carrying the value - green at 30 °C, amber at 62, red at 100), the **system clock
with seconds** along the bottom, and **one fan figure under each temperature**.  That
selected theme is now identified exactly rather than inferred: the app's 27 `presetTheme`
entries pair one-to-one with the 27 theme files the installer ships, and entry 26 is the
vendor's `1757491589871`.  The whole library - layouts, clips, baked overlays, decrypted
with the app's own constants - is in `themes/alpha/`, and that directory's `README.md`
writes up the container, the cipher and the layout schema; the `.thm` containers themselves
are recorded there by size and sha256 and are not carried in the tree (see the bullet
above).  Two of **our** drawing rules were re-measured while the previews were rebuilt for
0.3, and both are written out in [limits.md](limits.md): every line of the `clock` theme
now fits the same 440 px budget the big time line always had - the readings line measured
494.2 px against a 480 px panel and was simply losing its end glyphs - and the `dual`
theme's rings sit on a neutral track, because the pale cyan default measured 7.4 of 255
luma from its own fill, which is not a meter.  Worth knowing for anyone drawing from these
themes: the `clock` theme also draws a **date line** (`%A %d %B %Y`, fitted to the same
440 px budget), and since 0.3 its time and its date come from one hook, `render._now()` - so
a frame cannot pair one instant's seconds with another day's date, and a preview can freeze
the whole frame rather than just the clock string.  The two
temperature columns are deliberately alike - same label size and weight, one shared size
for both numbers, chosen from whichever reading is wider, so neither can end up bigger
than the other.  Each reading sits inside its ring's hole: at 97 px outer radius the two
rings fit side by side with a 38 px gutter, and that hole is what sizes the text - label
22 (the vendor's own 32 will not clear the stroke), value 58, or 46 the moment a
three-digit temperature appears.  A missing reading draws no arc and reads `--°C`, and a
fan with no reading reads `CPU FAN -- RPM` rather than going quiet.  See
`xigmalcd/render.py` for the measured geometry (the ring's open-bottomed shape is the vendor
skin's own - 269° of solid ink from 136° to 45° on its captured frame - drawn here at 260°
from 140°), `tools/selftest.sh` for the check that keeps text off
the stroke, and [Notes and known limits](limits.md) for what the fan figures can honestly show on a
given board. Its background default is `media/Theme_25.mp4` - the clip
the vendor app itself pairs with that theme - so the default picture is the Windows pairing,
and it needs no extra plate behind the glyphs because it is dark (see `--scrim` in
[the options table](usage.md)).
