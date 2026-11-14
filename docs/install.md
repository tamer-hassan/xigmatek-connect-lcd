# Installing

What the code needs, how a person who installed it from source gets the port, and how it is made to run at login. The two `.deb` files are [packaging.md](packaging.md); this file is the recipe a machine without the package follows.

## Requirements, the port, and the udev rule

Requirements: Python 3.9+, [`pyserial`](https://pypi.org/project/pyserial/),
[Pillow](https://pillow.readthedocs.io/). On Kubuntu/Debian:

```bash
sudo apt install python3-serial python3-pil
```

`/dev/ttyACM0` is `root:dialout`, so either be in the `dialout` group
(`sudo usermod -aG dialout $USER`, then log out/in) or install the udev rule:

```bash
sudo install -m 0644 install/99-xigmatek-lcd.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger --action=change
```

The rule also creates a stable `/dev/xigmatek-lcd` symlink (ACM numbering changes when
the panel re-enumerates) and sets `ID_MM_DEVICE_IGNORE` so ModemManager does not fire
AT commands at the display. Then:

```bash
python3 -m xigmalcd --device /dev/xigmatek-lcd --theme gauge
```

Everything here also installs as a package, and the two halves install separately on
purpose: `pip install .` gives the display loop and the `xigmalcd` command, `pip install
.[gui]` adds PyQt6 and the `xigmaui` command with it. Qt is an extra because the loop that
holds the port runs without it - the same reason `install/install.sh` only checks
`import PyQt6` and names `python3-pyqt6` when it is missing, rather than installing Qt for a
headless box. Three console scripts are declared: `xigmalcd`, `xigmaui`, and
`xigmalcd-reset` - the vendor's panel reset, `xigmalcd/reset.py`, which exists as a command
because a system that came from a `.deb` has no `tools/` directory to run and no other way
back once the panel's `logo`/`mode` read `2147483647` ([If the panel goes white](troubleshooting.md)).
`tests/test_packaging.py` reads `pyproject.toml` to keep all of that true: both packages listed,
PyQt6 in the extra and not in the base dependencies, all three console-script targets
resolving to something callable, and that third one sending nothing when it is called
without `--yes`. Run from a checkout, the first two are `python3 -m xigmalcd` and
`python3 -m xigmaui` either way, and the third is `tools/reset_panel.py` - a wrapper over
the same module. What `pip install .` does *not* do is install the clips this repo
carries in `media/` - fourteen today: three the vendor's own, one cut here from a vendor
clip, ten made on this bench by its owner (see
[Notes and known limits](limits.md)) - so a pip install draws from the checkout's
`media/`; the `.deb` is what puts them in `/usr/share/xigmalcd/media`.
## Run it at login

```bash
install/install.sh                     # deps + port check + systemd user unit + menu entry
XIGMALCD_THEME=clock XIGMALCD_FPS=1 install/install.sh
install/install.sh --udev              # also installs the udev rule (sudo)
install/install.sh --no-desktop        # headless box: skip the window's menu entry
```

That writes `~/.config/systemd/user/xigmalcd.service`, enables it, and starts it
immediately. Check on it with
`journalctl --user -u xigmalcd -f`, stop it with
`systemctl --user disable --now xigmalcd`. To run it without a graphical session,
`loginctl enable-linger $USER`.

(That is the *checkout* unit, and `--user disable` is the right undo for it because
`install.sh` enabled it in your own user directory. The `.deb` puts its enablement in
`/etc/systemd/user/default.target.wants`, which systemd calls global scope, and there
`systemctl --user disable` warns instead of acting - `docs/packaging.md` has both
measured, with the command that does work.)

When PyQt6 imports, it also writes the window's menu entry,
`~/.local/share/applications/xigmaui.desktop`,
pointed at `install/xigmaui.png` (the icon is the project's mark - the penguin at
`install/artwork/xigma-penguin.jpg`, with the transparency checkerboard that the JPEG
carries painted into it turned into real alpha by `tools/makeicon.py`, which also writes
`install/xigmaui.ico` with 16 px through 256 px.  `tools/makeicon.py --draw` still makes
the other icon: the picture the glass actually shows, drawn with the same `render.draw`
the daemon uploads from, over a frame of `media/Theme_25.mp4`, which is the one to look at
when the question is whether the display code is right.  The window sets the same file as
its own icon, which is why the `.desktop` entry names it by path instead of an icon-theme
name). The installer regenerates that PNG only if it is
missing or empty, and then validates the entry with `desktop-file-validate` when that
command exists, so a broken `.desktop` is caught at install time rather than by a menu
that silently shows nothing. `tests/test_launcher.py` checks the shipped `.png` and validates
the template the same way, with no install step involved. The entry has one extra
action, **Start in the tray only** (`python3 -m xigmaui --hidden`), for when the window
is a control panel you keep out of the way; it needs a desktop with a tray, and the
same two checks cover it.

**One process can hold the serial port, so the unit holds it and the window is
its client.** `xigmalcd` listens on a control socket while it draws
(`$XDG_RUNTIME_DIR/xigmalcd.sock`), and the menu entry talks to it there: pick a
theme, upload a background, pause the frame loop, read the counters, all while the
glass stays live. Nothing has to be stopped to use the window any more, and the
display keeps drawing when the window is closed - it hides to the tray, whose menu
has the display's status line, pause/resume and the six themes. See [Two processes,
one port](usage.md#two-processes-one-port) for what the socket accepts and what it refuses.
