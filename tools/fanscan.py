#!/usr/bin/env python3
"""fanscan.py - what fan and pump readings this box can actually produce.

  tools/fanscan.py            list every tachometer channel Linux can see, the
                              Super-IO drivers this kernel offers, and what the
                              alpha theme's two fan figures would draw from them
  tools/fanscan.py --watch 90 sample the tach channels and show which one moves
                              with the CPU, which is how the CPU fan gets
                              identified without guessing
  tools/fanscan.py --demo     render a labelled PNG of the layout using values
                              this box is NOT reporting (host-side only, never
                              sent to the panel)

This tool never opens the panel.  It is here because the CPU fan question is a
sensor question, not a protocol question:

  * The vendor app reads the fans on the host.  Its Windows logs name the chip
    outright - "MSI X870 GAMING PLUS WIFI (MS-7E47) (Nuvoton NCT6687D)", with
    "Fan CPU" 1016-2448 RPM and "Fan System 5" 1529-1582 RPM - and push them
    down to the panel inside the `STATE all 1` metrics blob as
    `"fans":[{"onBoard":true,"type":"Fan","name":"Fan CPU","value":2051}]`
    (34 such bodies across the logs, never one pump value).
  * The panel never reports a tachometer back.  Its own reply advertises
    `attribute: ["Status", "Fan", "Pump"]` and `deviceConfig.code C0FP01S0340`
    with `attribute: ["Status", "Pump"]`: that is a capability it has for
    content the host sends, not a source of readings (PROTOCOL §8).

So `CPU FAN nnn RPM` on the glass needs a Linux hwmon driver for the Super-IO.
On this box `sudo modprobe nct6683` (needs root, so a human runs it) binds the
NCT6687D as hwmon `nct6687`, and `--watch` is how its channels get named; the
result is pinned in `xigmalcd/sensors.py` FAN_CHANNELS.  Reading sysfs needs no
root, so everything here runs unprivileged.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                                # noqa: E402
from xigmalcd import render, sensors                                 # noqa: E402

# What this kernel ships, in the order worth trying on an MSI X870 board.  The
# descriptions are read from the modules themselves, not guessed: `nct6683`
# names NCT6683D/NCT6686D/NCT6687D, which is the family the vendor app named
# for this board.
DRIVERS = ("nct6683", "nct6775", "it87")


def dmi(field: str) -> str:
    try:
        return open(f"/sys/class/dmi/id/{field}").read().strip()
    except OSError:
        return "?"


def modules() -> list[str]:
    """Which candidate drivers exist on this box, and whether they are loaded."""
    try:
        loaded = {l.split()[0] for l in open("/proc/modules")}
    except OSError:
        loaded = set()
    out = []
    for m in DRIVERS:
        try:
            path = subprocess.run(["modinfo", "-F", "filename", m],
                                  capture_output=True, text=True,
                                  check=True).stdout.strip()
        except subprocess.CalledProcessError:
            continue
        desc = ""
        try:
            desc = subprocess.run(["modinfo", "-F", "description", m],
                                  capture_output=True, text=True).stdout.strip()
        except subprocess.CalledProcessError:
            pass
        out.append(f"  {m:9} {'loaded' if m in loaded else 'not loaded':11} "
                   f"{desc:55} {path}")
    return out


def channels() -> list[dict]:
    """Every fan*_input on every hwmon device, plus every pwm output.

    `chan` is the sysfs stem (`fan1`), `label` the driver's own `fan1_label`
    text if it publishes one.  `nct6683` on this board publishes none for fans,
    which is why the identity of a channel has to be measured - see `watch()`.
    """
    rows = []
    for chip, path in sensors.hwmon():
        for chan, label, rpm in sensors._chan_attrs(path, "fan"):
            rows.append({"chip": chip, "chan": chan,
                         "label": "" if label == chan else label, "rpm": rpm})
        for f in sorted(glob.glob(os.path.join(path, "pwm*"))):
            rows.append({"chip": chip, "chan": os.path.basename(f),
                         "label": "", "rpm": None})
    return rows


def tctl() -> str:
    """k10temp's Tctl, the CPU temperature the fan curve is driven by."""
    t = sensors.temps("k10temp")
    return f"{max(v for _c, v in t) / 1000:5.1f}" if t else "    ?"


def demo(path: str) -> None:
    """The layout with values this box is not reporting, titled so it is clear.

    Still useful with a tach driver bound: it is the only way to see the worst
    case widths - four-digit RPM next to a three-digit GPU fan percentage -
    before the glass has to carry them.
    """
    m = sensors.collect()
    real = m.get("fans") or []
    m["fans"] = [{"onBoard": True, "type": "Fan", "name": "Fan CPU",
                  "value": 2371},
                 {"onBoard": True, "type": "Chassis",
                  "name": "Fan System 5", "value": 1577}]
    osd = render.draw(m, "alpha", scrim=0,
                      title="synthetic RPM - layout test, not this box")
    bg = None
    try:                                    # same two-layer picture as the glass
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, here)
        import previews
        bg = previews.background()
    except Exception as exc:
        print(f"  background layer unavailable ({exc}); drawing the OSD alone")
    out = Image.alpha_composite(bg, osd) if bg else osd
    out.convert("RGB").save(path)
    print(f"  wrote {path}")
    print(f"  fan figures in that picture: {' | '.join(fan_figures(m))} - the "
          f"RPM values in them are invented, which is what the title banner says")
    if real:
        print(f"  this box's real readings, for comparison: "
              f"{' | '.join(fan_figures(sensors.collect()))}")
    print("  nothing was sent to the panel")


def fan_figures(m: dict) -> tuple:
    """The two figures the alpha theme draws, in the order it draws them."""
    return (render._cpu_fan_figure(m), render._gpu_fan_figure(m))


def watch(seconds: float) -> None:
    """Sample every tach channel and show which one varies.

    This is how the CPU fan gets identified without guessing.  Passive: it only
    reads sysfs, it never writes a PWM and starts no load.  For the answer to be
    visible the CPU has to warm up while this runs - play something, run a
    build, whatever you already do - because the discriminator is movement: the
    channel that swings with the CPU is the cooler's fan, the flat one is a case
    fan.  On this board that measurement pinned `fan1` at 1360-2371 RPM,
    tracking pwm1 (121-236) and k10temp Tctl (48-79 degC) across a 45 s load
    ramp, while `fan12` sat at 1538-1577 throughout.  That matches the vendor's
    own Windows numbers closely: `Fan CPU` 1016-2448, `Fan System 5` 1529-1582.
    """
    end = time.monotonic() + seconds
    seen: dict[tuple[str, str], list[int]] = {}
    while time.monotonic() < end:
        for row in channels():
            if row["rpm"] is not None:
                seen.setdefault((row["chip"], row["chan"]), []).append(row["rpm"])
        time.sleep(2.0)
    if not seen:
        print("  no tach channels to sample; nothing bound")
        return
    live = {k: v for k, v in seen.items() if max(v) > 0}
    quiet = sorted(k for k, v in seen.items() if max(v) == 0)
    print(f"  sampled {int(seconds)} s, {max(len(v) for v in seen.values())} "
          f"round(s); {len(live)} channel(s) turning"
          + (f", {len(quiet)} reading 0 all along "
             f"({', '.join(c for _h, c in quiet)})" if quiet else ""))
    for (chip, chan), vals in sorted(live.items(),
                                     key=lambda kv: max(kv[1]), reverse=True):
        nz = [v for v in vals if v > 0]
        spread = max(nz) - min(nz)
        hint = ("moved a lot - with a warm CPU, this is the cooler's fan"
                if spread > 150 else "steady - looks like a case fan")
        print(f"    {chip:10} {chan:8} {min(nz):5}-{max(nz):5} RPM  "
              f"spread {spread:5}  {hint}")
        if spread <= 150:
            print("      (a CPU idling through this window proves nothing; "
                  "load it and run it again)")
    print("  pinned in xigmalcd/sensors.py FAN_CHANNELS: " + ", ".join(
        f"{chip} {chan} = {name!r} ({kind})"
        for (chip, chan), (name, kind) in sorted(sensors.FAN_CHANNELS.items())))
    for (chip, chan), vals in sorted(live.items(),
                                     key=lambda kv: max(kv[1]), reverse=True):
        if (chip, chan) not in sensors.FAN_CHANNELS and max(vals) - min(vals) > 150:
            print(f'  {chip} {chan} swings but is not pinned, so the glass calls '
                  f'it plain `FAN`.  To label it, add to FAN_CHANNELS:')
            print(f'      ("{chip}", "{chan}"): ("Fan CPU", "Fan")')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--demo", metavar="PNG", nargs="?",
                    const="/tmp/opencode/fan-demo.png",
                    help="draw the layout with invented RPM values")
    ap.add_argument("--watch", type=float, default=0.0, metavar="SECONDS",
                    help="sample tach channels and show which one varies")
    a = ap.parse_args()

    print(f"board {dmi('board_vendor')} {dmi('board_name')} "
          f"(BIOS {dmi('bios_vendor')} {dmi('bios_version')}, {dmi('bios_date')})")

    rows = channels()
    tach = [r for r in rows if r["rpm"] is not None]
    if tach:
        print(f"\n{len(tach)} tach channel(s), and what each one is called:")
        for r in tach:
            name, kind = sensors.FAN_CHANNELS.get((r["chip"], r["chan"]),
                                                  ("", ""))
            print(f"  {r['chip']:10} {r['chan']:8} {r['rpm']:5} RPM   "
                  f"driver label: {r['label'] or '-':14} pinned as: "
                  f"{name or '-'}{' / ' + kind if kind else ''}")
        outs = [r["chan"] for r in rows if r["rpm"] is None]
        if outs:
            print(f"  outputs, not tachometers: {', '.join(outs)}")
    else:
        print("\nno fan*_input node on any hwmon device.  The chips that are "
              "bound here are: " + ", ".join(c for c, _ in sensors.hwmon()))

    print("\ncandidate drivers on this box:")
    for line in modules():
        print(line)
    print("  loading one needs root:  sudo modprobe nct6683   "
          "(put it in /etc/modules-load.d/ to keep it across boots)")

    readings = sensors.fans()
    print("\nwhat sensors.fans() reports (the STATE all 1 `fans` shape): "
          + json.dumps(readings))
    print("what the alpha theme's two fan figures draw: "
          + " | ".join(fan_figures(sensors.collect())))

    if not readings:
        print("\nwhy that is empty: the board's Super-IO is not enumerated by "
              "ACPI on this BIOS (no NCT/ITE device in /sys/bus/acpi/devices, "
              "no /sys/devices/pnp0 children), so no hwmon driver was ever "
              "asked to bind.  The vendor app reached the same chip by talking "
              "to its config ports directly from userspace under Windows.")

    if a.watch:
        print()
        watch(a.watch)

    if a.demo:
        print()
        demo(a.demo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
