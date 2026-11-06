"""xigmaui - a Qt front end for the panel, built on top of xigmalcd.

It is a control panel and a preview, not a reimplementation: every byte on the
wire goes through `xigmalcd.protocol.Link`, every pixel through
`xigmalcd.render.draw`, and the theme/background geometry is the daemon's, so
what the window shows is what `python3 -m xigmalcd` would put on the glass.

    python3 -m xigmaui                 (PyQt6, needs a display)
    python3 -m xigmaui --device /dev/ttyACM0 --preview-fps 2

Two limits the interface is built around, both measured rather than assumed:

* **The panel cannot be read back.** Every `GET` variant answers "no reply for
  request N" (PROTOCOL.md §11), so the preview here is *our own composite* of
  the background frame plus the OSD layer, the same way `tools/previews.py`
  composites the README pictures. It is labelled as such in the window. It is
  not a mirror of the glass, and nothing in this app claims otherwise.
* **One process can hold the port.** The app opens `/dev/ttyACM0` only for the
  action you asked for (status, upload, one frame, reset) and closes it again,
  so the display daemon stays usable. If something else holds it, the action
  fails with the name of the holder instead of hanging.

Nothing in this app can send a firmware or update frame: `Link` refuses the
`firmware`/`update`/`config`/`fan`/`pump` topics, and `recovery` is reachable
only from the reset button, which needs a typed confirmation.

Which paths have met this panel, and which have not: the status path has (its
`conn 1` reply is what the status pane shows), the drawing paths have not - no
upload, frame, live run or reset has been sent from this window. They call
`main._upload_background`, `Link.send_media` and `tools/reset_panel.py`'s frame,
all proven from the command line, but that is not the same as the button having
been pressed. The README's "The GUI" section keeps the ledger.
"""
