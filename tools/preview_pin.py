"""preview_pin.py - the one set of readings the documented previews draw.

Both preview tools take their numbers from here: `tools/previews.py` (the stills it
writes on demand) and `tools/preview_gif.py` (the animated GIFs the README embeds).
One spelling of "what do the pictures say", because two of them is how a caption ends
up quoting digits that no longer match the file beside it - and the README quotes the
digits.

Why the readings are pinned at all: a committed picture that drew whatever the machine
was doing at the moment of generation changes on every run, and the README quotes the
digits that came out of it.  So the set is fixed in this file, and every number in it
has a source.  What is *not* claimed: nothing in `tests/` re-measures the pictures
these tools write, so `docs/tools.md` names the command that reads them back.

Two kinds of source, and the difference matters, so they are labelled:

* **the meter positions** - `cpu.temperature`/`load`, `gpu.temperature`/`load`, and the
  fan figures - are a *fixture*: they are the pair ALPHA's own captured frame reads
  (`data/vendor_frames`: the panel showing 57 C with its load ring at 42 %, recorded and
  re-read by `tools/theme_previews.py` and PROTOCOL.md §9-§10), and 1 957 RPM, which sits
  inside the span measured on this board's CPU tachometer (`fan1` 1 360-2 371 RPM tracking
  `pwm1`, PROTOCOL §8) without being this box's live number.  That is deliberate: those
  four numbers decide where the arcs land and what colour they are, and a documented
  preview has to land in the same place on every machine.  The gauge theme's scale is
  30..75 C, measured off the vendor's own layout, so 57 C is 60 % of the sweep - the
  middle of the ramp, where position *and* colour carry the value.
* **everything else in the dict** is a *dated snapshot*: verbatim `sensors.collect()` on
  the author's bench at 2026-11-07 23:14, memory, board, disk, GPU memory and the CPU's
  own power/clock fields.  Those do not move an arc: they fill the `bars` rows and the
  `clock` line's RAM figure.

And the reason the fixture is not simply "what this box reads": at 2026-11-07 23:23 the
same bench reported 70 C at 8.8 % load with a GPU-using process running, and under eight
parallel `ffmpeg -stream_loop -1 -i media/Theme_25.mp4 -vf scale=1280:1280 -f null -`
decodes at 11:0x it read 73 C at 89.8 % load and 5 378 MHz.  Both are real; both are
this machine.  At 73 C the gauge's 30..75 sweep is 95.6 % travelled, which reads as
pegged rather than as a measurement - so the picture says 57 and this file says what the
box actually said, next to it, rather than leaving the reader to wonder which is which.
`preview_gif.py --live` draws the live numbers instead, if anyone wants the other answer.

Two shape notes, both learned the hard way:

* memory and disk are in **megabytes**, the vendor's units - `clock` and `bars` print
  `used // 1024` and call the result GB.  The first version of this dict had bytes,
  from a guess, and `bars` drew `RAM 8 089 595 GB`.  Nothing warned.  The suite asserts
  the magnitude now.
* every key is optional in the real thing: `sensors.collect()` omits whole sections on a
  box that has no such thing.  This fixture carries what this bench really reports, and
  no more.
"""
from __future__ import annotations

#: the meter positions: a fixture, sourced above (the vendor's captured frame, and the
#: board's measured tach span)
PINNED_METER = {
    "cpu": {"temperature": 57.0, "load": 42.0, "usage": 42.0},
    "gpu": {"temperature": 47.0, "load": 38.0, "fan": 45},
    # two figures, because `alpha` puts one fan reading under each temperature column
    # (A26_FAN_X): one entry in the list and the GPU column draws nothing.  1 957 RPM is
    # the CPU tach value this fixture has used since 0.2 - inside the span measured on
    # this board (`fan1` 1 360-2 371 RPM tracking `pwm1`, PROTOCOL §8) without being this
    # box's live number, which is the point of pinning it.  1 554 is the chassis fan as
    # this bench really reported it: 2026-11-07 11:0x, in the eight-decode load snapshot
    # named at the top of this file.
    "fans": [{"onBoard": True, "type": "Fan", "name": "Fan CPU", "value": 1957},
             {"onBoard": True, "type": "Chassis", "name": "Fan System 5",
              "value": 1554}],
}

#: everything the previews also print, verbatim from one dated `sensors.collect()`
#: (author's bench, 2026-11-07 23:14, no preview work running at that moment)
PINNED_LIVE = {
    "cpu": {"power": 66, "speedAverage": 5539, "voltage": 1.37},
    "disk": {"temperature": 33, "total": 786, "used": 68},
    "gpu": {"dedicated": 14654, "dedicatedTotal": 16376, "memoryUsage": 14654,
            "power": 71.51, "speed": 2805, "temperature": 44},
    "memory": {"load": 67.6, "temperature": 50, "total": 126157, "used": 85332},
    "motherboard": {"temperature": 56},
}


def readings() -> dict:
    """The whole fixture as one dict, in the shape `render.draw` takes."""
    out: dict = {}
    for src in (PINNED_LIVE, PINNED_METER):
        for section, vals in src.items():
            if section == "fans":
                out["fans"] = [dict(f) for f in vals]
            else:
                out.setdefault(section, {}).update(vals)
    return out


#: the dict both tools import: `render.draw(readings(), theme)` is what a documented
#: preview draws, and `preview_gif.PINNED` is this object
PINNED = readings()
