# The themes, and where their shapes come from

The five themes this project draws, what `alpha` is a redraw *of*, and the geometry that decides how big a number can be inside a gauge ring. The vendor's own library - 27 themes, their layouts, their clips and their baked overlays - is in `themes/alpha/`, and that directory's `README.md` is the write-up of the container, the cipher and the layout schema.

## The 27 vendor themes are not in the picker, and that is not an oversight

`xigmaui`'s theme list and `xigmalcd --theme` both take `sorted(render.THEMES)`:
`alpha`, `bars`, `clock`, `dual`, `gauge`. Those are the pictures **this program**
renders from live readings. The vendor's 27 are files in the vendor's own format, and
nothing in this project has ever put one on the wire or read one back:

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
writes up the container, the cipher and the layout schema.  The two
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
