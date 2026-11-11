# If the panel goes white

What the vendor's `recovery` request does, why this project ships it as its own command, and what it refuses to do unless it is told to.

The symptom, as it happened on this unit: the fields read `2147483647`, the panel's own
"not set", the display still looks fine, and then the next cold boot is **white from the
first second of POST** with its stored theme media gone. Power cycling does not fix it,
and neither does writing the fields: `logo`, `mode` and `presetThemeId` answer `200` to
every body tried and leave the value at `2147483647` anyway ("Danger" in
[Notes and known limits](limits.md)). The way back is the vendor's own `recovery` request, and this project
sends it from exactly one place, by hand:

```bash
xigmalcd-reset              # dry run: prints the 109-byte frame, sends nothing
xigmalcd-reset --yes        # send it once, wait for the port back, re-read the state
```

In a checkout the command is `tools/reset_panel.py`; both are `xigmalcd/reset.py`, and
the installed spelling exists because a system that came from a `.deb` has no `tools/`
directory to run. What it does, measured against real glass and written up in
PROTOCOL.md §5: `logo` goes `2147483647 -> 3` and `mode` `2147483647 -> 0`, free space
moves to `69664` (the same figure the vendor's own log recorded), the panel's stored
background is dropped, and the USB device re-enumerates - the port disappears and comes
back on its own, which is why the command waits for the node to reappear instead of
sleeping a fixed time. PROTOCOL.md §5 has ~9 s for that reproduction; the window's own
reset path has seen it in ~3 s ([the GUI doc](gui.md)), and both are logged rather than averaged.
The next run re-uploads the background, since that is what `--mp4` does at session start.

**Nothing in this project sends it on its own initiative.** Not a maintainer script, not
the systemd unit - `debian/xigmalcd.service`'s `ExecStart` is `/usr/bin/xigmalcd --theme
alpha --fps 2` and `debian/tests/smoke` fails an install whose unit ever grows
`--allow-reset`. The control socket refuses `reset` unless the display loop was started
with `--allow-reset`, and the window quotes that refusal rather than working around it.
And without `--yes` the command is a printout: `tests/test_packaging.py` asserts "dry run:
nothing sent" plus the 109-byte frame length, from the entry point itself, and
`debian/tests/smoke` asserts the same two things against `/usr/bin/xigmalcd-reset` after
an install.
