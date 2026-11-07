# The themes, and where their shapes come from

The five themes this project draws, what `alpha` is a redraw *of*, and the geometry that decides how big a number can be inside a gauge ring. The vendor's own library - 27 themes, their layouts, their clips and their baked overlays - is in `themes/alpha/`, and that directory's `README.md` is the write-up of the container, the cipher and the layout schema.

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
