"""Entry point: python3 -m xigmaui [options], and the `xigmaui` console script.

Qt is an extra (`pip install .[gui]`), not a dependency of the display loop, so
this is the one place that says so in words rather than letting the traceback
from `app.py`'s import stand as the message - the same hint install.sh prints
when it cannot `import PyQt6`.
"""
import sys

HINT = "install it with `pip install .[gui]`, or from the distro: sudo apt install python3-pyqt6"


def run(argv=None) -> int:
    try:
        from .app import main
    except ImportError as exc:
        print(f"xigmaui needs Qt, which the display loop does not: {exc}\n  {HINT}",
              file=sys.stderr)
        return 2
    return main(argv)


if __name__ == "__main__":
    sys.exit(run())
