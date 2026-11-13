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
   "fans":[{"onBoard":true,"type":"Fan","name":"Fan CPU","value":1476}],
   "motherboard":{"temperature":38},
   "timestamp":1793863294763}

Units as they appear there: memory MB, disk GB, temperatures whole degrees
Celsius, cpu.speedAverage / gpu.speed MHz, power Watts, voltage Volts,
fans RPM, network KB/s, timestamp in milliseconds.

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
BOARD_CHIPS = ("spd5118", "it87", "nct6775", "nct6779", "f71882fg",
               "emc2305", "r8169")
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


def hwmon(*prefixes: str) -> list[tuple[str, str]]:
    """[(chip name, /sys/class/hwmon/hwN)] whose chip name starts with a prefix."""
    out = []
    for path in sorted(glob.glob("/sys/class/hwmon/hw*")):
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
    dimm = temps("spd5118")
    if dimm:
        mem["temperature"] = _round_temp(max(v for _c, v in dimm))
    speed = _read("/sys/devices/system/memory/physical_memory_speed") \
        or _read("/sys/firmware/dmi/labels/" + "OEM-managed DIMM speed")
    if speed.isdigit():
        mem["speed"] = int(speed)
    return mem


# ------------------------------------------------------------------ disk ---
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
    t = temps(*DISK_CHIPS)
    if t:
        out["temperature"] = _round_temp(min(t, key=lambda cv: cv[1])[1])
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


def motherboard() -> dict:
    t = temps(*BOARD_CHIPS)
    if not t:
        return {}
    return {"temperature": _round_temp(max(v for _c, v in t))}


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
    board = motherboard()
    if board:
        out["motherboard"] = board
    out["timestamp"] = int(time.time() * 1000)
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(collect(), indent=2, ensure_ascii=False))
