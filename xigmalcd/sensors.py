"""Linux sensors shaped exactly like the 'STATE all 1' payload ALPHA sends.

Reference from a Windows capture (see PROTOCOL.md):

  {"network":{"upload":1,"download":0},
   "memory":{"total":128387,"used":8999,"load":7,"temperature":0,"speed":1800},
   "cpu":{"load":5,"temperature":57,"speedAverage":4338,"power":69,
          "voltage":1.365,"usage":4},
   "gpu":{"load":0,"temperature":32,"fan":0,"speed":2610,"power":37,
          "voltage":0.965,"memoryUsage":0,"dedicated":0,"dedicatedTotal":0},
   "disk":{"total":998,"used":206,"load":20,"activity":0,"temperature":32,
           "readSpeed":0,"writeSpeed":0},
   "drives":[{"name":"nvme0","temperature":32,"sensors":[32,54,68]},
             {"name":"nvme1","temperature":31,"sensors":[31]}],
   "fans":[{"onBoard":true,"type":"Fan","name":"Fan CPU","value":1476}],
   "motherboard":{"temperature":38},
   "timestamp":1793863294763}

One section in the body below is **not** in that capture: `drives[]` is this program's own,
added on 2026-11-14 after the panel was asked directly whether it would answer a `STATE all 1`
body carrying a key it has never seen - it did, `1 200` with `CkOK True`, and accepted the frame
uploaded afterwards (PROTOCOL.md 8).  What that does not show is whether the firmware *reads* the
section, only that it does not refuse it.

Units as they appear there: memory MB, disk GB, temperatures whole degrees
Celsius, cpu.speedAverage / gpu.speed MHz, power Watts, voltage Volts,
fans RPM, network KB/s, timestamp in milliseconds; and in `drives[]`,
`name` the controller instance, `temperature` whole degrees the drive
reports about itself, and `sensors` every reading it publishes, rounded.

Anything a machine cannot measure is left out; ALPHA's own captures drop
whole sections too (no gpu on a box without one, no fans when nothing reads).
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time

CPU_CHIPS = ("k10temp", "zenpower", "coretemp", "k8temp", "cpu_thermal",
             "soc_thermal")
GPU_CHIPS = ("amdgpu", "nvidia", "i915", "gma")
DISK_CHIPS = ("nvme", "drivetemp", "aacs")


class _Rate:
    """Counter deltas per second, so rate fields match ALPHA's units."""

    def __init__(self) -> None:
        self._prev: dict[str, tuple[float, tuple[int, ...]]] = {}

    def get(self, key: str, values: tuple[int, ...]) -> float | None:
        now = time.time()
        prev = self._prev.get(key)
        self._prev[key] = (now, values)
        if not prev or now <= prev[0] or len(prev[1]) != len(values):
            return None
        dt = now - prev[0]
        diffs = [v - p for v, p in zip(values, prev[1])]
        if any(d < 0 for d in diffs):               # counter reset
            return None
        return [d / dt for d in diffs]


_rate = _Rate()


def _read(path: str) -> str:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _int(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


#: Where the hwmon devices live.  A module-level name so the selection rules below can be
#: gated against a constructed tree rather than against whatever this box happens to expose.
HWMON_GLOB = "/sys/class/hwmon/hw*"

#: The board's own sensor set, in tiers - `motherboard()` takes the first tier that answers.
#: Super-IO controllers first: this board's NCT6687D (bound by `nct6683`, published as
#: `nct6687`) carries a thermal diode and three thermistors, which is what a row labelled
#: `Motherboard` means.
BOARD_CHIPS = ("it87", "nct6775", "nct6779", "nct67xx", "nct6687", "nct6683",
               "f71882fg", "emc2305", "tmp75", "tcn75", "lm75")

#: DDR5 SPD hubs (the `spd5118` chips).  They are on the board, and they are also what answers
#: `memory.temperature` - so they are a second tier rather than a co-equal candidate, and a box
#: with a Super-IO never has its DIMM thermistors printed twice.
DIMM_CHIPS = ("spd5118",)

#: On-board silicon that is not the board's sensor set: a network controller's die and the
#: chipset's hub die.  Neither is what a row labelled `Motherboard` means, so they are a last
#: resort rather than a candidate.  `r8169` is here because it *was* the only rule this file
#: ever had - measured at 43.5-50.5 °C it was the hottest thing in a flat `max()`, which is how
#: the glass came to print a Realtek NIC under the word "motherboard" (docs/limits.md).
#: `prom21_xhci` - the AMD Promontory XHCI hub, part of the X870 chipset, soldered to this
#: board - was added to this tier on the owner's decision of 2026-11-14, measured at **50.1 °C**
#: beside the NIC's 43.5.  It changes nothing on a box like this one, because the Super-IO's
#: diode wins the first tier at 38.5; it answers only where no Super-IO diode and no SPD hub is
#: published, and the claim being made is the safe one: on such a box the chipset hub is a
#: better stand-in for "the board" than a network controller is.
#:
#: `ath12k_hwmon` is deliberately **not** here, also the owner's decision of 2026-11-14.  It
#: reads 42.0 °C on this box - cooler than both, so leaving it out costs nothing today - and the
#: reason is the kind this repository keeps having to insist on: it is a Wi-Fi module on a
#: socket, a card in every sense the row is meant to exclude, and there is no measurement here
#: that would tell it apart from an add-in card's die.
BOARD_LAST_RESORT_CHIPS = ("r8169", "prom21_xhci")

#: Chips this boot enumerates that must never answer a `Motherboard` row at any tier: the CPU's
#: own sensor hubs, the card's, the drives', and the Wi-Fi module's.  Named as data so a check
#: can assert the tiers exclude them by membership, not by whatever the temperature happens to
#: be - a cooler excluded chip proves nothing on its own.
NOT_THE_BOARD_CHIPS = ("k10temp", "amdgpu", "nvme", "ath12k_hwmon", "drivetemp", "aacs")

#: A channel whose own driver label names a processor rather than the board.  `nct6683` labels
#: its temperatures even though it labels no tachometers, and on this board one of them is
#: `AMD TSI Addr 98h` - the CPU's thermal sensor read by the Super-IO, 62-70 °C here, against
#: the diode and thermistors at 40.5-42.8.  Without this, adding the Super-IO would have made
#: the "motherboard" reading *worse* than the NIC it already was.
NOT_THE_BOARD = re.compile(r"TSI|Tctl|Tccd|CPU|GPU|edge|hotspot", re.I)


def _hwmon_sort_key(path: str) -> tuple:
    """Order the hwmon directories by their index as a number.

    A plain text sort of `/sys/class/hwmon/hw*` puts `hwmon10` and `hwmon11` **before**
    `hwmon2` - measured on this boot: hwmon0(nvme), hwmon1(nvme), hwmon10(ath12k),
    hwmon11(amdgpu), hwmon2(r8169), hwmon3(nct6687), hwmon4(prom21_xhci), hwmon5(k10temp),
    hwmon6-9(spd5118).  Today that only decides which chip answers `Fan 1` when two chips
    publish tachometers, and here only one does, so nothing is wrong on the glass yet - but it
    is an accident of the digit count, and an order a reader cannot predict is an order no
    document can describe.
    """
    digits = re.findall(r"\d+", os.path.basename(path))
    return (int(digits[0]) if digits else 1 << 30, path)


def hwmon(*prefixes: str) -> list[tuple[str, str]]:
    """[(chip name, /sys/class/hwmon/hwN)] whose chip name starts with a prefix."""
    out = []
    for path in sorted(glob.glob(HWMON_GLOB), key=_hwmon_sort_key):
        chip = _read(os.path.join(path, "name"))
        if chip and (not prefixes or chip.startswith(prefixes)):
            out.append((chip, path))
    return out


def _chan_attrs(path: str, kind: str) -> list[tuple[str, str, int]]:
    """(channel, label, value) for every <kind>N_input on a hwmon device.

    `channel` is the sysfs attribute stem - `fan1`, `temp3` - and `label` is
    the driver's own `<kind>N_label` text when it publishes one, otherwise the
    channel again.  Several drivers label temperatures and not tachometers, and
    `nct6683` on this board is one of them: it gives `temp1_label` = "AMD TSI
    Addr 98h" but no `fan*_label` at all, so a channel's identity has to come
    from measurement (see FAN_CHANNELS below).
    """
    out = []
    for f in sorted(glob.glob(os.path.join(path, f"{kind}*_input")),
                    key=lambda p: int(re.findall(r"\d+", os.path.basename(p))[-1])):
        base = os.path.basename(f)[:-6]
        val = _int(_read(f))
        if val is None:
            continue
        out.append((base, _read(os.path.join(path, f"{base}_label")) or base, val))
    return out


def _attrs(path: str, kind: str) -> list[tuple[str, int]]:
    """(label, value) for every <kind>N_input on a hwmon device."""
    return [(label, val) for _chan, label, val in _chan_attrs(path, kind)]


def temps(*prefixes: str, exclude: str = "") -> list[tuple[str, int]]:
    out = []
    for chip, path in hwmon(*prefixes):
        if exclude and exclude in chip:
            continue
        out.extend((chip, v) for _label, v in _attrs(path, "temp") if 0 < v < 150_000)
    return out


def _round_temp(milli: int) -> int:
    return int((milli + 500) // 1000)


# ------------------------------------------------------------------- cpu ---
def _stat_totals():
    """(all jiffies, idle+jiffies iowait) from the aggregate /proc/stat line."""
    stat = _read("/proc/stat")
    if not stat:
        return None
    parts = [int(x) for x in stat.split("\n", 1)[0].split()[1:]]
    if len(parts) < 4:
        return None
    return sum(parts), parts[3] + (parts[4] if len(parts) > 4 else 0)


def cpu() -> dict:
    out: dict = {}

    totals = _stat_totals()
    if totals:
        d = _rate.get("cpu", totals)
        if d is None:
            # No baseline yet, i.e. the first call in this process, and `load`
            # would be missing from the picture - which reads `--%` on the glass,
            # as it did in the previews until this was fixed.  Take a second
            # reading a tick later: one frame pays 0.1 s, and the percentage is
            # a ratio of deltas so the tick length does not change it.
            time.sleep(0.1)
            again = _stat_totals()
            if again:
                d = _rate.get("cpu", again)
        if d and d[0] > 0:
            used = round(100.0 * (d[0] - d[1]) / d[0], 1)
            out["load"] = used
            out["usage"] = used

    mhz = _int(_read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"))
    if mhz is None:
        for line in _read("/proc/cpuinfo").splitlines():
            if line.startswith("cpu MHz"):
                mhz = int(float(line.split(":")[1]))
                break
    if mhz:
        out["speedAverage"] = mhz // 1000 if mhz > 100_000 else mhz

    t = temps(*CPU_CHIPS)
    if t:
        out["temperature"] = _round_temp(max(v for _c, v in t))

    # AMD boxes usually expose no CPU power rail; the iGPU's package power
    # (PPT) is the closest thing to it.
    for chip, path in hwmon("k10temp", "zenpower", "amdgpu", "coretemp"):
        pw = [v for label, v in _attrs(path, "power")
              if label.lower() in ("power", "ppt", "package power")]
        if pw:
            out["power"] = max(pw) // (1000 if max(pw) > 5000 else 1)
        volt = [v for label, v in _attrs(path, "in")
                if label.lower() in ("vddgfx", "vcore", "cpu vcore", "vin")]
        if volt:
            out["voltage"] = round(max(volt) / 1000.0, 3)
        if "power" in out and "voltage" in out:
            break
    return out


# ---------------------------------------------------------------- memory ---
def memory() -> dict:
    mem = {}
    kv = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if v.split():
            kv[k] = int(v.split()[0])              # kB
    total = kv.get("MemTotal", 0) // 1024
    if not total:
        return mem
    avail = kv.get("MemAvailable", kv.get("MemFree", 0)) // 1024
    mem["total"] = total
    mem["used"] = total - avail
    mem["load"] = round(100.0 * mem["used"] / total, 1)
    dimm = temps(*DIMM_CHIPS)
    if dimm:
        mem["temperature"] = _round_temp(max(v for _c, v in dimm))
    speed = _read("/sys/devices/system/memory/physical_memory_speed") \
        or _read("/sys/firmware/dmi/labels/" + "OEM-managed DIMM speed")
    if speed.isdigit():
        mem["speed"] = int(speed)
    return mem


# ------------------------------------------------------------------ disk ---
def controller_of(dev: str) -> str:
    """A block device name to the controller that owns it: `nvme0n1p6` -> `nvme0`.

    A pure function on purpose.  The mount point is read from `/proc/mounts`, which is not a
    thing a check can hand it - and the mapping is where an NVMe namespace, a partition number
    and an MMC block all look different while naming the one chip whose hwmon dir carries the
    temperature.

    A name that is not a disk at all - an `overlay`, a bind mount, a `mapper` label - answers
    **''**, because the caller's fallback ("report the hottest composite I can see") is the
    right answer for a mount this function cannot read, and a made-up controller name would
    match nothing while looking like a fact.
    """
    name = os.path.basename(dev or "")
    m = re.match(r"(nvme\d+)n\d+(p\d+)?$", name)
    if m:
        return m.group(1)
    m = re.match(r"(mmcblk\d+)p\d+$", name)
    if m:
        return m.group(1)
    m = re.match(r"([a-z]+d[a-z]?)(\d*)$", name)             # sda3, vdb1, xvda1, hda
    if m and m.group(1):
        return m.group(1)
    return ""


def _root_controller() -> str:
    """The disk controller that holds `/`, or '' when the mount point cannot say.

    This is the same drive `disk()` already describes with `total` and `used`, which come from
    `shutil.disk_usage("/")` - and reporting a capacity from one drive while reporting a
    temperature from another is exactly the mistake this fixes.  An `overlay`, a `mapper` name
    or a btrfs pool simply will not match a chip, and `disk_temperature()` falls back to the
    hottest composite in that case rather than guessing at a drive.
    """
    for line in _read("/proc/mounts").splitlines():
        parts = line.split()
        if len(parts) > 2 and parts[1] == "/":
            return controller_of(parts[0])
    return ""


def _disk_channels() -> list[tuple[str, str, list[tuple[str, int]]]]:
    """(chip, controller-instance, [(label, millidegrees)]) for every disk chip.

    The controller name comes from the hwmon device's own link, not from the directory: an nvme
    hwmon lives at `/sys/class/hwmon/hwmonN` and its `device` points at
    `/sys/devices/.../nvme/nvme0`, so `nvme0` is what has to be compared against the mount
    point.  Taking the parent directory instead answers `hwmon` for every drive and matches
    nothing - measured while writing this, and the reason the fallback fired on a box whose
    root disk is plainly named `nvme0`.
    """
    out = []
    for chip, path in hwmon(*DISK_CHIPS):
        link = os.path.join(path, "device")
        dev = os.path.basename(os.path.realpath(link)) if os.path.exists(link) else ""
        rows = [(label, val) for _chan, label, val in _chan_attrs(path, "temp")
                if 0 < val < 150_000]
        if rows:
            out.append((chip, dev, rows))
    return out


def _disk_sort_key(dev: str) -> tuple:
    """Order controllers numerically: `nvme0` before `nvme2`, `sda` before `sdb`.

    The walk order is not this order.  A drive list is what `Disk 1`/`Disk 2` in a layout
    index into, and a slot that moved between boots because the kernel numbered an hwmon
    directory differently is a row that silently changed which drive it reports.
    """
    digits = [int(d) for d in re.findall(r"\d+", dev)]
    return (re.sub(r"\d+", "", dev), digits or [-1], dev)


def _drive_choice(rows: list[tuple[str, int]]) -> tuple[int, bool]:
    """(millidegrees, whether it came from a Composite) for one drive.

    One function, because `disk.temperature` (the scalar the vendor's schema has) and the
    per-drive list added on 2026-11-13 must never disagree about which reading of a drive
    "its temperature" means: the composite when the drive publishes one, else its hottest
    sensor.  Two copies of that choice is exactly the drift this repository keeps having to
    look for.
    """
    comp = [v for label, v in rows if label.lower() == "composite"]
    if comp:
        return max(comp), True
    return max(v for _l, v in rows), False


def drives(root: str | None = None) -> list[dict]:
    """Per-drive readings, the section the panel was asked about on 2026-11-13.

    The shape - `{name, temperature, sensors}` - is deliberately **exactly what the probe
    sent**, not a convenience invented afterwards: `tools/blob_probe.py` put this list under a
    `drives` key in a live `STATE all 1` body and the panel answered `1 200` with `CkOK True`,
    then accepted the ordinary frame that followed
    (`data/glass/2026-11-13-184215-blob-probe.txt`, PROTOCOL.md §8).  Adding a fourth key to
    that row, or reordering it, is a claim that has not been made to the device, so it does not
    happen by accident.

    What is measured and what is not: the panel does not **reject** the section.  Whether it
    reads it is unanswerable from here - a `STATE` reply carries no body, and the only topic
    that would make the panel draw these numbers itself is `realtimeDisplay`, which ALPHA sends
    only to an `OS === "RTOS"` unit while this one reports Linux.

    `name` is the controller instance (`nvme0`), not the model string: it is short enough for a
    10-character display cut, stable across boots, and the value a reader can match against
    `/sys/class/nvme` and `lsblk`.  `temperature` is the whole degrees the drive reports about
    itself - its `Composite` when it publishes one, else its hottest sensor - and `sensors`
    carries every published reading rounded, so a layout that wants the hotter raw probe can
    name it instead of quietly substituting one.

    **Slot 1 is the drive that holds `/`.**  The order is root drive first, then the rest by
    controller - so a layout that draws `Disk 1` is drawing the same drive whose capacity the
    blob's `disk.total`/`disk.used` describe, and a boot drive can be marked by *position*
    rather than by a rule two doors have to agree on.  That is not decoration: measured here,
    the second drive's composite (31 °C today) differs from the first's (41), so a walk-order
    list would put a different drive in slot 1 than the capacity numbers describe, and the
    check that pins this ordering is the one that fails when someone "simplifies" it back to
    the kernel's numbering.  `root` is a parameter for the same reason the disk scalar has one:
    a machine with `/` on its second controller cannot be gated on this box's mount table.
    """
    out = []
    for _chip, dev, rows in _disk_channels():
        if not dev:
            continue
        chosen, _was_comp = _drive_choice(rows)
        out.append({"name": dev,
                    "temperature": _round_temp(chosen),
                    "sensors": sorted({round(v / 1000) for _l, v in rows if 0 < v < 150_000})})
    want = _root_controller() if root is None else root
    out.sort(key=lambda d: (d["name"] != want, _disk_sort_key(d["name"])))
    return out


def disk_temperature(root: str | None = None) -> tuple[int | None, str]:
    """The **whole degrees** to answer `disk.temperature` with, and the sentence saying where.

    `root` is the controller whose drive should answer; by default the one `/` is mounted on.
    It is a parameter rather than something read inside, so the three rules below can be gated
    against a constructed tree on any machine - including one with no second drive to disagree.

    Three rules, in order, and the reason for each:

    * the drive that owns `/` - the same drive `total` and `used` describe.  A second drive can
      sit at a different temperature for perfectly ordinary reasons (a cached drive in a
      bracket runs cooler than the boot drive under a workload), and a glass row that says
      "disk" while naming neither is answering a question about a drive nobody asked about.
      Measured here on 2026-11-13: `/` is on `nvme0` (Kingston SNV3S2000G, composite 41.85,
      hottest sensor 67.85) while the previous rule reported **31.85** - the composite of
      `nvme1` (MSI M461 2TB), because the old rule took the **minimum** of every sensor of
      every drive.  That is not a conservative reading of a disk temperature; it is the
      coolest number on the machine.
    * within one drive: its `Composite` channel when it publishes one.  That is NVMe's own
      aggregate, the number the drive reports about itself, and what `sensors -j` and
      `smartctl` show.  A drive can carry sensors the aggregate deliberately excludes:
      `nvme0` here reads `Sensor 2` at **67.85 °C** while its composite is 41.85, and printing
      68 would be quoting a NAND probe the drive itself does not treat as its temperature.
      If no channel is labelled `Composite`, the hottest sensor of that drive is used and the
      note says so - an unlabelled drive should not be invisible.
    * when the root drive cannot be matched to a chip (`_root_controller()` answering empty,
      or a mapper/btrfs pool), the **hottest** composite across the drives that do match.
      Falling back to the max is the one direction that cannot under-report.
    """
    chans = _disk_channels()
    if not chans:
        return None, "no disk temperature chip (nvme/drivetemp/aacs) published a temp*_input"
    want = _root_controller() if root is None else root
    asked = "the drive that holds /" if root is None else "the drive the caller asked for"
    per_drive = []
    for _chip, dev, rows in chans:
        chosen, was_comp = _drive_choice(rows)
        per_drive.append((dev, chosen, was_comp))
    if want:
        for dev, mdeg, was_comp in per_drive:
            if dev == want:
                where = (f"the composite published by {dev} ({asked})" if was_comp else
                         f"the hottest sensor of {dev} ({asked}; it publishes no Composite "
                         f"channel)")
                return _round_temp(mdeg), where
    hottest = max(v for _d, v, _c in per_drive)
    return _round_temp(hottest), (f"the hottest reading across {len(per_drive)} drive(s); none "
                                  f"matched the mount point")


def disk() -> dict:
    out: dict = {}
    try:
        usage = shutil.disk_usage("/")
        out["total"] = usage.total // (1024 ** 3)
        out["used"] = usage.used // (1024 ** 3)
    except OSError:
        pass

    reads, writes, busy = [], [], []
    for line in _read("/proc/diskstats").splitlines():
        f = line.split()
        if len(f) < 13:
            continue
        if not re.fullmatch(r"sd[a-z]+|nvme\d+n\d+|vd[a-z]+|mmcblk\d+", f[2]):
            continue
        reads.append(int(f[5]))
        writes.append(int(f[9]))
        busy.append(int(f[10]))
    if reads:
        d = _rate.get("disk", tuple(reads + writes + busy))
        if d:
            n = len(reads)
            out["readSpeed"] = round(sum(d[:n]) * 512 / (1024 * 1024), 1)
            out["writeSpeed"] = round(sum(d[n:2 * n]) * 512 / (1024 * 1024), 1)
            busy_s = sum(d[2 * n:])
            out["activity"] = round(min(100.0, 100.0 * busy_s / 1000.0
                                        / max(n, 1)), 1)
    # iowait as this app's idea of disk load
    stat = _read("/proc/stat")
    if stat:
        parts = [int(x) for x in stat.split("\n", 1)[0].split()[1:]]
        if len(parts) > 5:
            d = _rate.get("iowait", (sum(parts), parts[5]))
            if d and d[0] > 0:
                out["load"] = round(100.0 * d[1] / d[0], 1)
    val, _whence = disk_temperature()
    if val is not None:
        out["temperature"] = val
    return out


# --------------------------------------------------------------- network ---
def network() -> dict:
    rx = tx = 0
    for line in _read("/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        if name.strip() == "lo":
            continue
        f = rest.split()
        if len(f) > 8:
            rx += int(f[0])
            tx += int(f[8])
    d = _rate.get("net", (tx, rx))
    if not d:
        return {}
    return {"upload": round(d[0] / 1024, 1), "download": round(d[1] / 1024, 1)}


# ------------------------------------------------------------------- gpu ---
GPU_CACHE = 3.0        # seconds.  nvidia-smi costs ~1 s on a busy GPU, which is
                       # a third of the frame budget at 1 fps, and its numbers
                       # do not move that fast.
_gpu = {"at": 0.0, "val": None}


def _nvidia() -> dict | None:
    """One nvidia-smi round trip; None if it is not there or did not answer."""
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run(
                [smi, "--query-gpu=name,temperature.gpu,utilization.gpu,"
                      "fan.speed,clocks.gr,power.draw,memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5).stdout.strip()
            fields = out.splitlines()[0].split(",") if out else []
            vals = [f.strip() for f in fields]
            if len(vals) >= 3:
                g: dict = {"load": _num(vals[2]), "temperature": _num(vals[1])}
                if _num(vals[3]) is not None:
                    g["fan"] = _num(vals[3])
                if _num(vals[4]):
                    g["speed"] = _num(vals[4])
                if _num(vals[5]):
                    g["power"] = _num(vals[5])
                if _num(vals[6]) is not None:
                    g["memoryUsage"] = _num(vals[6])
                if _num(vals[7]):
                    g["dedicatedTotal"] = _num(vals[7])
                    g["dedicated"] = _num(vals[6]) if _num(vals[6]) else 0
                return g
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
    return None


def gpu() -> dict:
    """One GPU section: NVIDIA through nvidia-smi, otherwise the hwmon chip."""
    if shutil.which("nvidia-smi"):
        if _gpu["val"] is not None and time.monotonic() - _gpu["at"] < GPU_CACHE:
            return dict(_gpu["val"])
        g = _nvidia()
        if g is not None:
            _gpu["at"], _gpu["val"] = time.monotonic(), dict(g)
            return g

    for chip, path in hwmon(*GPU_CHIPS):
        t = [v for _l, v in _attrs(path, "temp")]
        if not t:
            continue
        g = {"temperature": _round_temp(max(t))}
        busy = _int(_read(os.path.join(path, "gpu_busy_percent")))
        if busy is not None:
            g["load"] = busy
        freq = [v for _l, v in _attrs(path, "freq")]
        if freq:
            g["speed"] = max(freq) // 1_000_000 if max(freq) > 1_000_000 \
                else max(freq) // 1000
        pw = [v for _l, v in _attrs(path, "power")]
        if pw:
            g["power"] = max(pw) // (1000 if max(pw) > 5000 else 1)
        volt = [v for label, v in _attrs(path, "in") if "gfx" in label.lower()]
        if volt:
            g["voltage"] = round(max(volt) / 1000.0, 3)
        used = _int(_read(os.path.join(path, "mem_info_vram_used")))
        total = _int(_read(os.path.join(path, "mem_info_vram_total")))
        if used and total:
            g["memoryUsage"] = used // (1024 * 1024)
            g["dedicated"] = g["memoryUsage"]
            g["dedicatedTotal"] = total // (1024 * 1024)
        return g
    return {}


def _num(text):
    try:
        f = float(text)
        return int(f) if f.is_integer() else round(f, 2)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ fans, board --
# The tachometer channels, named.  ALPHA's metrics blob carries entries shaped
# `{"onBoard": true, "type": "Fan", "name": "Fan CPU", "value": 2051}`; the names
# `Fan CPU` and `Fan System 5` below are the vendor's own, taken from the Windows
# logs where this board's NCT6687D sensor collection published `Fan CPU`
# 1016-2448 RPM and `Fan System 5` 1529-1582 RPM (PROTOCOL.md §8).
#
# `nct6683` binds this chip as hwmon `nct6687` and publishes ten tach inputs and four
# PWMs but **no `fan*_label`**, so which channel is which had to be measured here
# rather than looked up - and re-measured when the machine was re-wired.
#
# 2026-11-06, sampled every 3 s across 12 s idle, 45 s of all-24-thread load and 25 s
# of cooldown:
#
#   fan1   1360-2371 RPM, tracking pwm1 (121-236) and k10temp Tctl (48-79 degC)
#   fan12  1538-1577 RPM throughout, never moved by the load
#
# so fan1 is the cooler's fan - it swings over the same span as the vendor's `Fan CPU`
# - while fan12 is flat at exactly the Windows chassis channel's 1529-1582.
#
# 2026-11-13, after six case fans moved to the Xigmatek Mini ARGB controller (which
# exposes no sensor interface to Linux at all) and the Xigmatek Connect 360's block
# cable went to PUMP_SYS1 while its radiator fans went to CPU_FAN1.  23 rounds over
# 45 s, all 24 threads loaded:
#
#   fan1   1692-1957 RPM, spread 265, still tracking pwm1 and k10temp (53-76 degC)
#   fan2   2459-2469 RPM, spread 10, unmoved while pwm2 followed pwm1's duty 1:1
#          (raw 182, 178, 174, 167, 152 in successive paired samples)
#   fan12  0 RPM - the header lost its fan in the same re-wiring
#   fan3, fan4, fan11, fan13, fan14, fan15, fan16   0 RPM in every sample
#
# fan2 is the pump.  Two things say so, and neither is a name: it is the channel that
# came alive when the block cable went into PUMP_SYS1 - it read 0 in all 30 samples of
# the watch taken an hour earlier on the same kernel - and it ignores its own header's
# duty while everything else on this chip follows the CPU curve, which is how a pump
# differs from a fan.  The name `CPU PUMP` and the type `Pump` are **ours**: no
# `Pump` type and no pump value appears in any captured vendor body (PROTOCOL.md §8),
# and `themes.FAN_TYPED` is what turns that pinned type into the `Pump Speed` reading
# nine of the 23 selectable layouts ask for.  fan12 keeps its pin although it reads
# nothing today, because a re-connected case fan should name itself again.
#
# `tools/fanscan.py --watch 90` reproduces all of it on any box; re-pin this table from
# what that prints when the board or the wiring changes.
FAN_CHANNELS = {("nct6687", "fan1"): ("Fan CPU", "Fan"),
                ("nct6687", "fan2"): ("CPU PUMP", "Pump"),
                ("nct6687", "fan12"): ("Fan System 5", "Chassis")}


def fans() -> list[dict]:
    """RPM readings, formatted like ALPHA's fan entries.

    Nothing here speaks to the panel's own fan pages: the panel never measures
    anything, it only displays what the host sends (PROTOCOL §8).  The values
    come from whatever tachometer a Linux hwmon driver publishes, and this box
    has one - `nct6683` on the board's Nuvoton NCT6687D, giving the two channels
    pinned in FAN_CHANNELS.  Channels that are not pinned keep the neutral
    `chip fanN` name, because picking a CPU fan out of two unlabelled channels
    would be a guess.

    `type` follows ALPHA's vocabulary - "Fan", "Chassis", and "Pump" for a channel pinned as
    one.  The vendor's own bodies only ever carry "Fan" and "Chassis"; the pump entry below is
    the one place this program puts a type the vendor never sent, and it is ours because the
    *channel* is ours: pinned from measurement in `FAN_CHANNELS`, not inferred from a label
    this driver does not publish.  Channels are keyed by chip and channel rather than by
    value: a fan and a pump can legitimately read the same RPM, and dropping one of them
    would be a lie.
    """
    out, seen = [], set()
    for chip, path in hwmon():
        for chan, label, rpm in _chan_attrs(path, "fan"):
            if rpm <= 0 or (chip, chan) in seen:
                continue
            seen.add((chip, chan))
            name, kind = FAN_CHANNELS.get((chip, chan), (None, None))
            if name is None:
                name = f"{chip.replace('_', ' ')} {label}".strip()
                low = name.lower()
                kind = ("Pump" if "pump" in low or "aio" in low else
                        "Chassis" if "sys" in low or "chassis" in low
                        or "case" in low else "Fan")
            out.append({"onBoard": True, "type": kind, "name": name,
                        "value": rpm})
    return out


def board_channels(*chips: str) -> list[tuple[str, str, int]]:
    """(chip, driver label, millidegrees) for every channel that can stand for the board.

    Two guards, and they catch different things.  **Membership first**: a chip named in
    `NOT_THE_BOARD_CHIPS` is skipped outright, whatever its number says.  That is not paranoia
    about labels - the Wi-Fi module (`ath12k_hwmon`) and the drives (`nvme`) publish a channel
    labelled plain `temp1`/`Composite`, which the label filter below would happily accept if a
    tier ever named them.  A rule that only rejects things by name is one typo away from
    reporting a SSD as the motherboard.

    **Then the label**: channels whose own driver label names a processor or a card are dropped
    by `NOT_THE_BOARD`, which is the whole reason the Super-IO can be a candidate at all - on
    this board its hottest temperature is `AMD TSI Addr 98h` (60-70 °C measured), and taking the
    max of everything would print that under a row that says `Motherboard`.
    """
    out = []
    for chip, path in hwmon(*(chips or BOARD_CHIPS)):
        if chip in NOT_THE_BOARD_CHIPS:
            continue
        for chan, label, val in _chan_attrs(path, "temp"):
            if 0 < val < 150_000 and not NOT_THE_BOARD.search(label or ""):
                out.append((chip, label, val))
    return out


#: A channel the driver calls a thermal **diode**.  Preferred over the thermistors for
#: `motherboard.temperature` on the owner's decision (2026-11-13): this board's BIOS, and the
#: `/etc/sensors.d` file written against it, name the diode channel "Motherboard"
#: (`Diode 0 (curr)` = 42.5 °C) while the thermistors sit warmer (44.5), and a row that says
#: `BOARD` should agree with what the board itself labels rather than with the hottest thing it
#: can find.  Where a chip publishes no diode - the SPD hubs, most Super-IOs under a driver that
#: leaves `tempN_label` unset - the tier's hottest channel answers instead, and `fanscan.py`
#: prints which of the two it was.
DIODE = re.compile(r"diode", re.I)


def motherboard_answer() -> tuple[str, str, int] | None:
    """The (chip, driver label, millidegrees) that answered `motherboard`, or None.

    Three tiers, first one that answers wins, and each is there for a measured reason:

    1. **the Super-IO's own channels** - a thermal diode and thermistors wired to the board.
       Here that is `nct6687`: `Diode 0 (curr)` 40.5-44.5 °C and `Thermistor 1`/`Thermistor 15`
       40.5-49.0 across the readings taken on 2026-11-13, against `AMD TSI Addr 98h` at 62-70
       (excluded by `NOT_THE_BOARD`).  **Within the tier the diode wins**: the BIOS and the
       owner's `/etc/sensors.d` file both call that channel "Motherboard", so the row follows
       the label rather than the maximum (42.5 vs 44.5 on the day it was decided).  A chip with
       no diode-labelled channel falls back to its hottest candidate.
    2. **the DDR5 SPD thermistors** (`spd5118`, 41.0-47.0 here) - on the board, but the same
       chips also answer `memory.temperature`, so they are a second tier rather than a
       co-equal candidate: a machine with a Super-IO never prints its DIMM numbers twice.
    3. **a network controller's die** (`r8169`, 45.0-50.0 here) - the last resort, because a
       box with no bound Super-IO and no SPD hubs should report the warmest thing it can
       rather than nothing.  It was the *only* rule this file had, which is how `Motherboard`
       on the glass came to read 45-49 °C from a Realtek chip while the board's own diode sat
       unread at 40 (docs/limits.md keeps both readings).

    The vendor's captured body has `motherboard: {"temperature": 38}` beside
    `cpu: {"temperature": 57}` - a board number well below the CPU's, which is the shape tier 1
    reproduces and the NIC never did.  Which channel won matters enough to print: on this box
    the Super-IO thermistors and the NIC die sit a few degrees apart, so the number alone cannot
    show the tier rule working, and `tools/fanscan.py` names the chip and label it chose.  The
    blob has no field for that, and inventing one is a wire change this file does not make from
    a hunch.
    """
    for chips in (BOARD_CHIPS, DIMM_CHIPS, BOARD_LAST_RESORT_CHIPS):
        chans = board_channels(*chips)
        if not chans:
            continue
        diodes = [c for c in chans if DIODE.search(c[1] or "")]
        # the diode the board labels "Motherboard" if there is one, else the hottest channel
        # of that tier; several diodes are possible on a Super-IO, so `max` inside the subset.
        return max(diodes or chans, key=lambda clv: clv[2])
    return None


def motherboard() -> dict:
    """One whole degree, the way ALPHA's `motherboard` section spells it.  The rule and its
    three tiers are in `motherboard_answer()`; the tiers are what this door walks."""
    won = motherboard_answer()
    if won is None:
        return {}
    return {"temperature": _round_temp(won[2])}


# ----------------------------------------------------------------- main ----
def collect() -> dict:
    """The STATE all 1 body, with every unreadable section left out."""
    out: dict = {}
    for key, fn in (("network", network), ("memory", memory), ("cpu", cpu),
                    ("gpu", gpu), ("disk", disk)):
        try:
            val = fn()
        except Exception as exc:                     # never kill the display loop
            print(f"  ! sensors.{key}(): {exc}")
            val = {}
        if val:
            out[key] = val
    try:
        fl = fans()
    except Exception as exc:
        print(f"  ! sensors.fans(): {exc}")
        fl = []
    if fl:
        out["fans"] = fl
    # The per-drive list, on the section name the panel was asked about and answered `200` for
    # (PROTOCOL.md §8).  Absent when no drive publishes a temperature, exactly as `fans` is
    # absent on a board with no tach signals: an empty list would be a claim about storage that
    # the machine did not make.
    dv = drives()
    if dv:
        out["drives"] = dv
    board = motherboard()
    if board:
        out["motherboard"] = board
    out["timestamp"] = int(time.time() * 1000)
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
