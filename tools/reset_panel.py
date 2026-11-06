#!/usr/bin/env python3
"""reset_panel.py - the vendor app's own panel reset, one request, by hand.

This is the only place in this project that sends `recovery`, and it exists
because the alternative is booting Windows: `logo`/`mode` cannot be set from the
wire (23 body shapes each, every one answers 200 and leaves the field at the
panel's "not set" value 2147483647), and with `logo` not set the panel comes up
white from the first second of POST.

What ALPHA actually sends, read out of its own log at 18:39:48 on 2026-11-05 -
the moment the reset button in "AIO Theme" was pressed - and what this tool
reproduces byte for byte:

    POST recovery 1
    {"enable":true}                        109-byte frame, answered 1 200 in 6 ms

and 9 s later that log reports logo 2147483647 -> 3, mode 2147483647 -> 0,
free space 69252 -> 69664.  It is a reset, not a firmware write: it never
touches the flash image, it drops the stored picture and re-enumerates the USB
device, which is why the app reconnected 9 s later.

    tools/reset_panel.py            dry run: show the frame, send nothing
    tools/reset_panel.py --yes      send it once, then wait for the port back

It sends exactly one request, never retries, and refuses to run without --yes.
`Link` blocks the `recovery` topic for everything else in this project; the
allow_destructive flag here is a deliberate, single-purpose exception.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import Link, encode, find_ports

BODY = {"enable": True}          # compact() -> {"enable":true}, the vendor's 15 bytes
KEYS = ("logo", "mode", "osdState", "brightness", "timeout", "space")


def info(ln, tries=3):
    for _ in range(tries):
        try:
            return ln.device_info()
        except Exception:
            ln.drain(0.4)
    return {}


def show(ln=None):
    st = info(ln) if ln else {}
    return {k: st.get(k) for k in KEYS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=None)
    ap.add_argument("--yes", action="store_true",
                    help="actually send it (default is a dry run)")
    ap.add_argument("--wait", type=float, default=45.0,
                    help="seconds to wait for the USB device to come back")
    a = ap.parse_args()

    port = a.device or next((p for p, lab in find_ports()
                             if "Xigmatek" in lab or "ACM" in p), "/dev/ttyACM0")

    # the frame we will put on the wire, built by the same encoder that has
    # reproduced every one of the vendor's 1672 logged requests byte identically
    demo = encode("POST recovery 1",
                  {"SeqNumber": 21, "Date": 1793896788252, "ContentType": "json",
                   "ContentLength": 15}, b'{"enable":true}')
    print(f"frame to send ({len(demo)} bytes): {demo[:6].hex(' ')} ... "
          f"{demo[-12:].hex(' ')}")
    print("body {\"enable\":true}  ->  POST recovery 1")
    if not a.yes:
        print("\ndry run: nothing sent. Re-run with --yes to reset the panel.")
        print("What happens: the panel drops its stored picture and the USB")
        print("device re-enumerates, exactly as it did when ALPHA's reset button")
        print("was pressed at 18:39:48 on 2026-11-05.")
        return 0

    with Link(port, timeout=3.0, allow_destructive=True) as ln:
        ln.start_pump()
        ln.hello(60)
        before = show(ln)
        print(f"before: {before}", flush=True)
        ln.post("recovery", BODY)
        print("sent. Waiting for the device to come back...", flush=True)
        time.sleep(0.5)
        try:
            for m in ln.harvest(timeout=1.0):
                if m.code:
                    print(f"  answer {m.code}", flush=True)
        except Exception as e:
            print(f"  link went away during the reset ({e})", flush=True)

    deadline = time.time() + a.wait
    gone = False
    while time.time() < deadline:
        if os.path.exists(port):
            if gone:
                print(f"  {port} back after {time.strftime('%H:%M:%S')}", flush=True)
                break
        else:
            if not gone:
                print(f"  {port} disappeared (re-enumerating)", flush=True)
                gone = True
        time.sleep(0.5)
    else:
        print(f"  {port} never came back within {a.wait:.0f} s - check "
              "lsusb / dmesg", flush=True)
        return 1

    time.sleep(2.0)
    for attempt in range(6):
        try:
            with Link(port, timeout=3.0) as ln:
                ln.start_pump()
                ln.hello(60)
                after = show(ln)
                print(f"after:  {after}", flush=True)
                fixed = after.get("logo") not in (None, 2147483647)
                print("logo/mode restored" if fixed
                      else "still at 'not set' - ALPHA's reset in Windows is the "
                           "next step", flush=True)
                return 0 if fixed else 1
        except Exception as e:
            print(f"  port not ready yet ({e})", flush=True)
            time.sleep(3.0)
    return 1


if __name__ == "__main__":
    sys.exit(main())
