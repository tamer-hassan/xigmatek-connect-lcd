#!/usr/bin/env bash
# Set up xigmalcd on this machine: python deps, serial port access, a systemd
# *user* service that runs the panel loop at login, and a menu entry for the
# Qt window.
#
#   install/install.sh              deps + service + launcher, prints hints
#   install/install.sh --udev       also install the udev rule (sudo)
#   install/install.sh --no-desktop skip the menu entry (headless box)
#   XIGMALCD_THEME=bars XIGMALCD_FPS=1 install/install.sh
#
# The service holds the serial port and keeps the glass updated; the window is
# its client, not a second owner. Only one process can hold the port (PROTOCOL.md
# §1), so `xigmalcd` answers on a control socket - $XDG_RUNTIME_DIR/xigmalcd.sock,
# mode 0600 - and the menu entry talks to it there: theme, clock, canvas, scrim,
# fans, fps, pause, one frame, one background upload, all live, with the display
# running the whole time. The window falls back to driving the port itself only
# when nothing is running, and it says which mode it is in.
#
# The socket cannot reach the two things this project does not do casually: no
# firmware-shaped file is ever accepted by it, and `reset` (the vendor's
# `recovery`) is refused unless the unit is started with --allow-reset.
#
# FPS is worth choosing deliberately.  The panel shows the newest frame it has
# committed, so whatever it displays is up to one frame period old: the clock on
# the glass runs 0.1-1.1 s behind at 1 fps and 0.1-0.45 s behind at 3 fps.  The
# vendor app uploads one picture per second, so 1 is its look and its flash
# writes; 2 halves the clock lag for twice the writes.  Higher rates are not a
# risk to the link - a 400 s run at 3 fps took 1173 of 1175 frames, its two
# session renewals both at exactly 500 uploads / 167 s, and the 3 fps window in
# front of it took all 361.  All of these need the vendor's upload ordering,
# which is the default (PROTOCOL.md §6, §9).
set -uo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON:-$(command -v python3)}"
THEME="${XIGMALCD_THEME:-alpha}"
FPS="${XIGMALCD_FPS:-2}"      # 1 = the vendor's rate, 3 = the tightest clock
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/xigmalcd.service"
RULE="$DIR/install/99-xigmatek-lcd.rules"
DEV="${XIGMALCD_DEVICE:-/dev/ttyACM0}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
DESK="$DATA/applications/xigmaui.desktop"
ICON="$DIR/install/xigmaui.png"

UDEV=0
NODESK=0
for arg in "$@"; do
    case "$arg" in
        --udev) UDEV=1 ;;
        --no-desktop) NODESK=1 ;;
        -h|--help) sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed '$d'; exit 0 ;;
        *) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
    esac
done

say() { printf '\n== %s\n' "$*"; }

udevcmd() {
    sudo install -m 0644 "$RULE" /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger --action=change
    echo "installed /etc/udev/rules.d/99-xigmatek-lcd.rules"
}

say "python dependencies"
if "$PY" -c 'import serial, PIL' 2>/dev/null; then
    echo "pyserial and Pillow are already there"
else
    echo "installing into the user site"
    "$PY" -m pip install --user pyserial pillow || {
        echo
        echo "pip refused (PEP 668). On Kubuntu/Debian use the distro packages:"
        echo "  sudo apt install python3-serial python3-pil"
        exit 1
    }
fi

say "serial port access"
if [ ! -e "$DEV" ]; then
    echo "$DEV is not there - is the cooler plugged in and the cable good?"
elif [ -w "$DEV" ]; then
    echo "$DEV is writable, nothing to do"
else
    echo "$DEV is owned by root:dialout. Pick one:"
    echo "  sudo usermod -aG dialout $USER      # then log out and back in"
    echo "  install/install.sh --udev           # rule + ModemManager exclusion"
fi

if [ "$UDEV" = 1 ]; then
    say "udev rule"
    udevcmd
fi

say "systemd user service"
mkdir -p "$(dirname "$UNIT")"
sed -e "s|@DIR@|$DIR|g" -e "s|@PYTHON@|$PY|g" \
    -e "s|@THEME@|$THEME|g" -e "s|@FPS@|$FPS|g" \
    "$DIR/install/xigmalcd.service.in" > "$UNIT"
echo "wrote $UNIT   (theme=$THEME, fps=$FPS)"
systemctl --user daemon-reload
systemctl --user enable xigmalcd
systemctl --user restart xigmalcd
sleep 4
systemctl --user --no-pager --full status xigmalcd 2>&1 | sed -n '1,10p'

say "the Qt window (xigmaui)"
if [ "$NODESK" = 1 ]; then
    echo "skipped: --no-desktop"
elif ! "$PY" -c 'import PyQt6' 2>/dev/null; then
    echo "PyQt6 is not installed, so there is nothing to put in the menu:"
    echo "  sudo apt install python3-pyqt6"
    echo "the daemon itself does not need it."
else
    if [ ! -s "$ICON" ]; then
        # the mark is install/artwork/xigma-penguin.jpg with its baked-in
        # checkerboard turned into real alpha (a JPEG cannot carry alpha);
        # tools/makeicon.py --draw falls back to the picture the glass shows
        (cd "$DIR" && "$PY" tools/makeicon.py)
    fi
    mkdir -p "$(dirname "$DESK")"
    sed -e "s|@DIR@|$DIR|g" -e "s|@PYTHON@|$PY|g" \
        "$DIR/install/xigmaui.desktop.in" > "$DESK"
    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$DESK" || echo "  (the shell may still show it)"
    fi
    echo "wrote $DESK"
    echo "      icon $ICON"
    if systemctl --user is-active --quiet xigmalcd; then
        echo
        echo "the display is running now and holds $DEV, and the window drives it"
        echo "over the control socket instead of the port: pick a theme, upload a"
        echo "background, pause the frame loop, all with the glass live. The box"
        echo "at the top of the window says which of the two it is doing."
        echo "  pause the display from the window or its tray icon"
        echo "  systemctl --user stop xigmalcd      # only if you want the port"
    fi
fi

cat <<EOF

logs:   journalctl --user -u xigmalcd -f
stop:   systemctl --user disable --now xigmalcd
manual: cd $DIR && $PY -m xigmalcd --theme $THEME --fps $FPS -v

gui:    "Xigmatek Connect LCD" in the application menu, or
        cd $DIR && $PY -m xigmaui            (window, and tray icon if the
        desktop has one)  or  $PY -m xigmaui --hidden   (tray only)
        it talks to the running display over the control socket; with no display
        running it uses the port itself, one action at a time
        closing the window hides it to the tray: --no-tray turns that off, and
        the tray menu's Quit closes it for good
        it remembers its settings in ~/.config/xigmaui/config.json
        (--fresh starts from the defaults, --help lists the rest)

display control socket: ${XDG_RUNTIME_DIR:-/run/user/$UID}/xigmalcd.sock (0600),
        one JSON line in and out; xigmalcd/control.py is the protocol and the
        gates. Ask the running display from anywhere:
        $PY -m xigmalcd --status

If the unit runs but the port is busy or refused, something else owns it:
  fuser -k $DEV
To start it without a graphical session (e.g. headless box):
  loginctl enable-linger $USER
EOF
