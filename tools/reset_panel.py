#!/usr/bin/env python3
"""reset_panel.py - the checkout spelling of `xigmalcd-reset`.

The implementation, and the prose about what the vendor's own reset request is and
what it does to the panel, is in `xigmalcd/reset.py`: read that, or run
`tools/reset_panel.py --help`.  This file exists so the command README,
docs/troubleshooting.md, PROTOCOL.md and the rest of tools/ refer to works from a
checkout, and so that one command has one implementation - it is a wrapper, not a
second copy.

    tools/reset_panel.py            dry run: show the frame, send nothing
    tools/reset_panel.py --yes      send it once, then wait for the port back

The .deb installs the same code as /usr/bin/xigmalcd-reset; nothing in this project
sends `recovery` on its own, and `Link` keeps the topic blocked for the display
loop, the control socket and the window unless a loop was started with
--allow-reset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.reset import main      # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
