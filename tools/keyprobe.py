#!/usr/bin/env python3
"""keyprobe.py - find the body key that actually sets a panel field.

A reply of 200 only means the JSON parsed.  The proof that a body is the right
shape is a round-trip: write it, ask `conn` for the field, and see the value we
sent come back.  That is what `brightness {"value":N}` does.  What `logo
{"index":N}` and `mode {"index":N}` do instead is answer 200 and leave the field
at 2147483647, the panel's "not set" - i.e. those bodies are wrong and clear the
panel's theme selection, which is the white screen we have been chasing.

    tools/keyprobe.py --topic logo --want 3 --force    # states the cost first
    tools/keyprobe.py --topic mode  --want 0 --force
    tools/keyprobe.py --topic brightness --want 60     # unguarded: no --force

`logo`, `mode` and `presetThemeId` are in `protocol.BLOCKED_TOPICS`, so without
`--force` this tool refuses to run and says why.  With it, be clear about what
is being risked: it does not make an already-damaged panel worse, but a body
that parses and is wrong leaves the field at 2147483647 on a healthy one, which
is the white screen, and `tools/reset_panel.py --yes` is the only way back.  It
only shows which body shape, if any, puts a real value in the field; when one
does, that is the correct key.
"""
import argparse, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from xigmalcd.protocol import BLOCKED_TOPICS, Link, ProtocolError

SENTINEL = 2147483647

# key names tried for every topic, in the order the vendor's other commands
# suggest them: value (brightness/timeout), degree (rotate), index (the ones we
# guessed), then the obvious aliases for a theme/animation id.
KEYS = ["value", "index", "degree", "id", "logo", "mode", "num", "number",
        "code", "theme", "themeId", "logoId", "presetThemeId", "name",
        "data", "state", "type", "n", "i", "idx", "v", "val"]


def info(ln, tries=3):
    for _ in range(tries):
        try:
            return ln.device_info()
        except Exception:
            ln.drain(0.4)
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/ttyACM0")
    ap.add_argument("--topic", required=True)
    ap.add_argument("--field", help="state field to check (default: --topic)")
    ap.add_argument("--want", type=int, required=True,
                    help="value to write; healthy values: logo 3, mode 0")
    ap.add_argument("--keys", help="comma separated key list to try instead")
    ap.add_argument("--force", action="store_true",
                    help="the topic is one protocol.py guards (logo, mode, "
                         "presetThemeId, the media store, firmware): this "
                         "asks for a deliberate panel-state write with no undo")
    a = ap.parse_args()
    field = a.field or a.topic

    if a.topic in BLOCKED_TOPICS and not a.force:
        print(f"{a.topic} is in protocol.BLOCKED_TOPICS, so Link refuses every "
              f"request for it and this tool has nothing to report: its answer "
              f"is the round trip, and the round trip needs the write. Pass "
              f"--force if you mean it. The cost, stated plainly: a body that "
              f"parses but is wrong leaves {field} at {SENTINEL}, the panel's "
              f"'not set', which is the white screen - and the only thing that "
              f"clears that is tools/reset_panel.py --yes.")
        return 1
    keys = a.keys.split(",") if a.keys else KEYS
    hits, cleared, other = [], [], {}
    with Link(a.device, timeout=3.0,
              **({"allow_destructive": True} if a.force else {})) as ln:
        ln.start_pump()
        ln.hello(60)
        st = info(ln)
        print(f"panel: {field}={st.get(field)} logo={st.get('logo')} "
              f"mode={st.get('mode')} space={st.get('space')}", flush=True)
        for k in keys:
            body = {k: a.want}
            try:
                ln.request(f"POST {a.topic} 1", body)
            except ProtocolError as exc:
                print(f"  ! {a.topic} {json.dumps(body)}: {exc}", flush=True)
                break
            code = "-"
            for m in ln.harvest(timeout=0.3):
                if m.code and m.headers.get("AckNumber") != "0":
                    code = m.code
                    break
            after = info(ln)
            got = after.get(field)
            tag = f"  POST {a.topic} {json.dumps(body)} -> {code}  {field}={got}"
            if code == "200" and got == a.want:
                hits.append(k)
                print(tag + "   <<< ROUND TRIP", flush=True)
            elif got == SENTINEL:
                cleared.append(k)
                print(tag + "   (cleared to not-set)", flush=True)
            else:
                other[k] = (code, got)
                print(tag, flush=True)
            if code == "200" and got == a.want:
                break                                  # leave it set correctly
        end = info(ln)
        print(f"\nround-trip keys: {hits or 'none'}")
        print(f"cleared the field: {len(cleared)} of {len(keys)} bodies tried")
        print(f"other results: {other}")
        print(f"end: {field}={end.get(field)} logo={end.get('logo')} "
              f"mode={end.get('mode')} space={end.get('space')}")


if __name__ == "__main__":
    # main() returns 1 when it refuses to run, and that has to be the exit code:
    # a guard refusal that reports success would be a trap in a script
    sys.exit(main())
