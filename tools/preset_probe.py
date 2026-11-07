#!/usr/bin/env python3
"""preset_probe.py - find the body shape `presetThemeId` takes, with no screen.

The panel reports the theme it is currently showing as `logo` in `conn`: 3 in
every healthy Windows capture, 0x7fffffff on this unit since the sweep that
blanked it.  So `logo` is the oracle: a write that lands changes it, a write the
panel ignores does not.  ALPHA never sends this command in any of its 8 logs, so
the body key has to be found by probing.

That means this tool exists in order to write a guarded topic, so it refuses to
run without `--force`, and `--force` should not be handed out casually:
`presetThemeId` is in `protocol.BLOCKED_TOPICS` because the same class of write
(`logo`, `mode`) answers `1 200` and leaves the field at 2147483647, which is the
white-screen state on this unit.  `presetThemeId` is the one topic in that group
that has *ever* changed the glass without an upload (indexes 0..8 answer `200`,
9 answers `400`, and `conn` reports nothing about which built-in theme is
showing), so a probe here can move the screen and cannot tell you what it moved
it to.  Eyes on the panel, or do not run it.

    tools/preset_probe.py --force        the sweep, with `logo` read after each body
    tools/preset_probe.py --force --want 0    write 0 rather than 3

Without `--force` it states the cost and sends nothing.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import Link, ProtocolError

KEYS = ("mode", "logo", "osdState", "brightness", "timeout", "space")

BODIES = [
    {"value": 3}, {"id": 3}, {"themeId": 3}, {"presetThemeId": 3},
    {"index": 3}, {"presetId": 3}, {"theme": 3}, {"value": "3"}, {"id": "3"},
    {"state": 3}, {"num": 3}, {"no": 3}, {"tid": 3}, {"mcuPresetThemeId": 3},
    {"value": 3, "id": 3}, {"id": 3, "type": "preset"},
    {"data": {"id": 3}}, {"value": 3, "valueType": "number"},
    {}, None,
]


def _revalue(obj, want: int):
    """Every copy of 3 in a body template becomes `want`, at any depth.

    The templates below are written around the value 3 because 3 is the theme
    healthy Windows captures report in `logo`; --want should not silently probe a
    mixture of 3s and something else.
    """
    if isinstance(obj, dict):
        return {k: _revalue(v, want) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_revalue(v, want) for v in obj]
    return want if obj == 3 else obj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-d", "--device", default="/dev/ttyACM0")
    ap.add_argument("--want", type=int, default=3,
                    help="the value to write in every shape "
                         "(3 is the theme healthy Windows captures report)")
    ap.add_argument("--force", action="store_true",
                    help="required: every request here writes a topic "
                         "protocol.py guards, with no readback to confirm "
                         "what it did")
    a = ap.parse_args()

    if not a.force:
        print("every request in this tool writes `presetThemeId`, which is in "
              "protocol.BLOCKED_TOPICS: the guarded class of write answers "
              "`1 200` and can leave the panel's theme field at 2147483647, the "
              "'not set' that shows as a white screen. This tool's oracle is "
              "`logo` in conn, so it needs the write to answer at all - but it "
              "cannot undo one, and conn never reports which built-in theme is "
              "selected. Run it with eyes on the glass and --force, or not at "
              "all.")
        return 1

    bodies = [{k: a.want if isinstance(v, int) else v
               for k, v in b.items()} if isinstance(b, dict) else b
              for b in BODIES]
    with Link(a.device, timeout=3.0, allow_destructive=True) as ln:
        ln.start_pump()
        ln.hello(60)
        before = ln.device_info()
        print("before:", {k: before.get(k) for k in KEYS}, flush=True)
        for body in bodies:
            try:
                ln.request("POST presetThemeId 1", body)
            except (ProtocolError, PermissionError) as exc:
                # our own guard, mid-sweep: report it and stop rather than
                # ending the run with a traceback and no closing state
                print(f"  ! not sent: {exc}", flush=True)
                break
            time.sleep(0.3)
            rep = [f"{m.code}{(m.body or b'')[:34].decode('latin1', 'replace')}"
                   for m in ln.harvest(timeout=0.7)]
            i = ln.device_info()
            mark = "changed" if i.get("logo") != before.get("logo") else "  same "
            print(f"{mark} logo={i.get('logo'):>11} space={i.get('space'):>6} "
                  f"body={json.dumps(body) if body is not None else '(none)':<28} "
                  f"{' '.join(rep)[:60]}", flush=True)
            if i.get("logo") != before.get("logo"):
                print("     >>> presetThemeId", body, "took effect", flush=True)
                print("         `logo` moved, which is the answer this tool "
                      "exists for; look at the glass and say what it now shows",
                      flush=True)
                break
        i = ln.device_info()
        print("after: ", {k: i.get(k) for k in KEYS}, flush=True)
    return 0


if __name__ == "__main__":
    # a guard refusal has to be the exit code, or a script reads it as a sweep
    # that ran
    sys.exit(main())
