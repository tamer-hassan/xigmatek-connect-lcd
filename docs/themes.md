# The themes, and where their shapes come from

The five themes this project draws, what `alpha` is a redraw *of*, and the geometry that decides how big a number can be inside a gauge ring. The vendor's own library - 27 themes, their layouts, their clips and their baked overlays - is in `themes/alpha/`, and that directory's `README.md` is the write-up of the container, the cipher and the layout schema.

## The 27 vendor themes are not in the picker, and that is not an oversight

`xigmaui`'s theme list takes `sorted(render.THEMES)`: `alpha`, `bars`, `clock`, `dual`,
`gauge`. Those are the pictures **this program** draws from live readings, and they are the
five whose own options - a title, a label, a `cold`/`hot` band, a gauge source, an ink colour -
the window edits with that picker. It is not that the window cannot show the others: the layout
editor previews every selectable file in the box beside the picture, and since 2026-11-11 it
puts one on the glass from there, by `apply to the panel`. `xigmalcd --theme` takes those five **and** 23 of the vendor's 27
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
back out of the README's `<theme>-<clip>.mp4` names by `tests/test_theme_library.py`.
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
the ones the panel's size, byte-identical to what the themes package installs, and counted
from those files by `xigmalcd.themes.field_census` rather than kept by hand:

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
is never handed a theme, and no plan here changes that. Three things follow from drawing
them here instead - the first two are gated in `tests/test_theme_library.py`, the third in
`tests/test_theme_files.py` and `tests/test_smoke_accounting.py`, and none of them is
asserted here:

* **23 of the 27, on the canvas.** The gate reads each file's own `ratio` field: 23 say
  `1:1` (480×480, the panel's size) and 4 say `4:3` (320×240). The four are refused, with
  the reason printed by `--list-themes` and by a bad `--theme` argument: the em-box anchor
  convention that every text widget in a layout is drawn by was measured at 480, against
  the vendor's own baked overlay (`render.py` records it, `tools/theme_check.py` measures
  it per theme), and scaling an unmeasured convention by 1.5 would put a guess on the
  glass. Keying the gate on `ratio` instead of on the directory name is deliberate: a
  future 480×480 layout must not be filtered out by a path rule.
* **Two refusals, not one, and the listing says which.** Since 2026-11-13 `--list-themes`
  counts the reasons out (`23 pickable, 4 refused: 4 on canvas` on a box that has never
  edited a theme) because there are two ways a file in the library is unusable: the canvas it
  declares, and having nothing in it to draw. The second was a hole, not a refinement -
  `scan()` selected on `ratio` alone, so a JSON with no `osd` in your own themes directory was
  a name `resolve()` answered, and `layout.draw_theme` walks `obj["osd"]["widget"]`, so the
  frame naming it raised `KeyError: 'osd'` rather than painting an empty canvas. `themes.save`
  has refused to *write* an empty layout since 0.6; the reader doors - `scan()`, `resolve()`,
  `--theme`, `--check-theme`, and the editor's `open a file…` - now refuse to *read* one, in
  `themes.NEED_OSD_WHY`'s words. Held by `tests/test_theme_files.py` and by
  `tests/test_smoke_accounting.py`, which runs the installed check in three states of
  `$XDG_CONFIG_HOME`.
* **7 metric names over those 23, in 82 widgets' worth of counts**: `CPU Temperature` 17,
  `CPU Usage` 15, `Time` 11, `Pump Speed` 9, `GPU Usage` 6, `GPU Temperature` 3,
  `CPU Frequency` 2.  The vocabulary this program answers is wider than what the library
  asks - **37 names** through `themes.source_names()` - and eight of them are asked by nothing
  shipped here: `Disk Temperature` (→ `disk.temperature`, the composite of the drive that
  holds `/`) and the four positional pairs `Disk 1 Temperature`/`Disk 1 Name` …
  `Disk 4 Temperature`/`Disk 4 Name`, which index the `drives` list `sensors.drives()`
  publishes - ordered by controller, so `nvme0` is slot 1 whatever the kernel numbered its
  hwmon directory.  No file of the vendor's names a storage reading at all, so those names and
  their display shapes are this repo's, and they exist so a layout of **yours** can put drive
  temperatures on the glass (docs/limits.md has the rules, the measured numbers and the
  probe that made the extra blob section permissible).  Whether any of them is missing from a given machine is a per-machine
  question, and since 2026-11-13 the only one that can be is `Pump Speed`: it is answered by a
  fan row whose `type` is `Pump` (`themes.FAN_TYPED`), and this bench has one - the channel that
  came alive when the AIO's block cable went into `PUMP_SYS1`, steady at 2459-2469 RPM while its
  own header's duty swept (PROTOCOL.md §8).  On a body with no tachometer at all the nine
  layouts skip that widget instead, with the reason naming the command that would settle it
  (`tools/fanscan.py`), and `tests/test_pump_speed.py` holds both halves.  Because the name is
  in the vocabulary now, it is also a legal `xigma.showIf` dependency: a row can be gated on a
  pump being sensed at all, and on a box that reports no such row it is silenced and *reported*
  (`showIf:Pump Speed`) rather than drawing a hole - measured on this bench as 13 boxes against
  12, the gated line 1 376 px.  Either way a widget
  with no reading draws **without that widget** and prints why - a hole that says what it is,
  rather than a zero that reads as a measurement. Faces are substituted the same way and
  said out loud (`arial` -> Liberation Sans, `simsun` -> Noto Sans CJK), because no
  Microsoft fonts are installed here, and the three metric shapes that are this repo's
  choice rather than measured off the vendor's picture (`Time`, `CPU Frequency`,
  `Pump Speed`) are named in the same note.

What is **not** built is a resize that ignores what a kind owns, and a snap to a grid:
what *is* built, on 2026-11-11, is a **peek** - the editor's pane can be pointed at this
machine's own readings, or at a JSON `STATE all 1` file the reader names through the same door
`--metrics-file` uses, held rather than followed, drawn at the pinned instant, with every act
that writes a number refused on it.  An edit is still judged only against the pinned fixture,
and no peek is remembered or sent anywhere: there is no scale-everything handle, and there is no
grid, because these files carry none - the gcd of every declared `x` and every declared `y` in
the **185** placements of the **28** layouts the pane opens is 1.  What did go in, on
2026-11-11, is a drag that can be pulled onto a number the *same file* already uses, 2 px at
most: another row's `x` within one anchor class, another row's `y`, and on x the centre and the
mirror of another row's centre - the lines those 185 rows actually hold, since 89 of them share
an `x` exactly.  Stretching a row by dragging one of the squares on its box went in on
2026-11-10, through the size keys the painter reads for that kind - `width`/`height`
for a `bar`, the pair `line_rect` declares (swapped for a row turned 90°) for a `line`,
the ring of an `arc` scaled with its box, the `fontSize` of a `text` row, the pitch or
the face of a `special`; and so did the rows themselves - added only as a copy of one
that already draws, removed never past the last, reordered through the list that is the
draw order - and the two acts that give a copy a name of its own, which is a rule about
the whole library rather than about one file, because `resolve()` answers a name, that
name folded, and the id inside it (the bullets, and the digits they hold, are in
docs/gui.md).  What **is**
built, since
2026-11-08, is the window's `Layout` box - one layout, one widget, **every field that
widget carries as a row of its own** (10 rows for a `text` widget through 18 for an
`arc`), over the same model `tests/test_editor.py` drives headless: a layout file under
`~/.config/xigmalcd/themes` is read before the vendor's copy of the same name, a copy
made for editing is byte-identical to the file it came from (23/23), a save is atomic
and keeps a `.bak`, and deleting your copy puts the vendor's back in front. All of it
is offline behaviour: the panel is still handed nothing but `.osd` frames
(docs/usage.md has the `--check-theme` door that reports which file is drawing, and
docs/gui.md what one edit is worth in pixels). The plan, the census it rests on
and the parts that stay gaps are written out in [theme-editor.md](theme-editor.md).

## The name is looked up by the display, not by the window

Nothing about a layout's file travels over the socket.  A **name** travels: `--theme Theme_07`
on a command line, `("cmd": "theme", "value": "Theme_07")` on the socket, `apply to the panel`
in the window.  The process that owns the port is the one that looks that name up, in
`themes.roots()`, in this order: your own copies (`$XDG_CONFIG_HOME/xigmalcd/themes`, scanned
flat), then the checkout's `themes/alpha`, then `/usr/share/xigmalcd/themes/alpha` out of the
package - a checkout deliberately wins over an installed package, so the figures the documents
quote cannot drift under a build that happens to have a `.deb` on the machine.  Which means the
same press means different things against different displays, and a window that could open the
file has no way to know what is on the other end of the socket until it asks.

Both answers were read on 2026-11-11 by driving each build's own `Control._set_theme` in
process, with `/dev/xigma-no-such-port` never opened and no byte sent anywhere:

* the **installed 0.3 package** answered `ok=True` for `alpha` and `gauge` and refused
    `Theme_01`, `Theme_07`, the numeric id `1757491588804` and a copy of mine, each time with
    `unknown theme '<name>'; try alpha bars clock dual gauge` - the five names, and no
    directory.  That build ships no `xigmalcd/themes.py` at all (`find_spec` answers None in
    that package; `git ls-tree v0.3 xigmalcd/themes.py` is empty, and the file lands in 0.4
    with stage 1 of docs/theme-editor.md), so it has nothing to resolve a layout name with;
* **this tree's** same door answered `ok=True` for all four of those names, and refuses only
    a name nothing resolves, and that refusal quotes `themes.why_not`, which prints the roots
    it searched and tells you to run `--list-themes`;
* and the **files were never the problem**: `xigmatek-connect-lcd-themes` puts **23** layout
    JSONs at `/usr/share/xigmalcd/themes/alpha/layouts/480X480/` on this bench, so what a 0.3
    service is missing is the code that reads them - a newer display, not more files.
* and the package's own root is enough by itself, which an installed build says about
    itself: an install's `themes.roots()` is `['$XDG_CONFIG_HOME/xigmalcd/themes',
    '/usr/share/xigmalcd/themes/alpha']` - the checkout entry is simply absent - and on this
    bench the same **23** names resolve inside those two roots, `Theme_07` to
    `/usr/share/xigmalcd/themes/alpha/layouts/480X480/1757491588804.json`, and the name list
    comes out identical to the checkout's.  So the remedy for an installed service is the newer
    package.  (Labelled as this bench's measurement, because GitHub's runner has no such
    directory: the **23** is `themes.scan()`'s own selectable count, and a reader only finds
    files inside that root on a machine that has the package installed.)
* and that remedy has now been read off a newer install on the same machine, the same day: the
    bench's `xigmatek-connect-lcd` and `-themes` packages went to **0.6**, built from this tree,
    and driven the same way - in process, `/dev/xigma-no-such-port` never opened - that build's
    `_set_theme` answers `ok=True` for `alpha`, `Theme_07` and `Theme_01`, and still refuses a
    name nothing resolves, with the two roots above named in the refusal.  So the sentence that
    starts this section is the whole of it: the name travels, and which names travel is a fact
    about the display's build, not the window's.

So a `Theme_*` that opens, previews, edits and saves in the window and is then refused by the
display comes down to two cases, and the display's own sentence tells them apart.  A refusal
that lists the five drawn names and names no directory is a door from before 0.4.  A refusal
that reads `no layout named 'Theme_07' under <roots>` is a display with the door, in front of
roots that do not hold this file - because those are *its* roots, and this window resolved the
name somewhere else.  `xigmalcd --list-themes` on the machine running the display prints what
that display can resolve, and *save as your copy* writes a layout into the first of those
roots, the one every display searches before the other two.  So putting one of these names on the glass against an old service means a display that can
resolve it: the loop's own `--theme <name>` door at a start, from a 0.4 or newer build, with the
background that layout names coming by the same route (`--mp4 Theme_07.mp4`, docs/limits.md). And
one process can hold the port, so the display that is running has to stop before another one
starts - which is a decision about someone's panel, not a step to take quietly.

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
from 140°), `tests/test_gauges.py` for the check that keeps text off
the stroke, and [Notes and known limits](limits.md) for what the fan figures can honestly show on a
given board. Its background default is `media/Theme_25.mp4` - the clip
the vendor app itself pairs with that theme - so the default picture is the Windows pairing,
and it needs no extra plate behind the glyphs because it is dark (see `--scrim` in
[the options table](usage.md)).
