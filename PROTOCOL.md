# Xigmatek "Connect" AIO — the USB serial protocol

Notes on the link between the Windows `ALPHA` app (`C:\Program Files\ALPHA\ALPHA.exe`)
and the 480×480 LCD mounted in the front of Xigmatek Connect series AIO coolers
(here: Connect 360, device reports app `V1.0.2`, firmware `V1.2.3`, hardware `V2.0`).

Two independent sources, and they agree:

* two serial-monitor captures of ALPHA on COM3 (27 MB and 9.5 MB of UTF-16 text) — **bench
  files, not in this repo**: they sit under `data/captures/`, which `.gitignore` keeps out
  because they carry this panel's serial number and the rest of that Windows session with it.
  Checked against the live panel on Linux: the encoder in `xigmalcd/protocol.py` re-creates
  **all 181 captured host→panel frames byte for byte** (130 in the long session, 51 in the one
  that starts at power-on) and all **267 captured panel replies pass the strict checksum**,
  with `mismatched frames: 0` — that is what
  `python3 tools/verify_protocol.py data/captures/*.txt` prints on the author's bench, and the
  same command against a capture of your own is how to check it here;
* **ALPHA's own code**: `resources/app.asar/out/main/index.jsc` is Ignition (Node
  11.4.183.29) bytecode; patched `d8` plus View8 decompiles it to JS. That gives the
  command registry, the payload builders and the frame packer verbatim, so the
  escaping rule of §4 is read off the vendor's program instead of guessed from bytes.

---

## 1. Transport

The panel is a USB CDC-ACM device (`lsusb`: `1d6b:0109 "Xigmatek USB Device"`), showing
up as `COM3` on Windows and `/dev/ttyACM0` on Linux.

| setting | value |
|---|---|
| baud | 115200, 8N1 |
| DTR | asserted by ALPHA (`dtr = True`) |
| RTS | cleared (`rts = False`) |
| flow control | none |

Nothing is on the bus before ALPHA opens the port: the panel does not talk first, it
only answers requests (`tools/probe.py --listen 30` sees an idle line). The port is
half-duplex in practice — one request, its answer, then the next request.

Two kinds of traffic share the line:

1. **framed** request/reply messages (§2), and
2. **raw bytes** — the contents of a picture file, streamed after a transfer request
   has been approved (§6). These are *not* framed and *not* escaped, which is the main
   trap when splitting a capture into messages.

The SoC is an **ArtInChip** part: if its firmware resets, the USB device disappears and
re-appears for about two seconds as `33c3:6677 "USB download gadget"` before coming back
as `1d6b:0109`. Writes to the handle of a dead session fail with
`OSError: [Errno 5] Input/output error`.

**One opener.** The kernel gives `/dev/ttyACM0` to exactly one process at a time, so a
loop that keeps the glass updated and a second program that wants to change what is on
it cannot both hold the line. The way round it, and the shape everything in this repo
uses, is that the display process is the only opener and everything else talks to
*it*: `xigmalcd/control.py` answers JSON lines on a unix socket
(`$XDG_RUNTIME_DIR/xigmalcd.sock`), the settings a client changes are fields the frame
loop re-reads, and anything that needs the wire is queued for the loop thread to carry
out. `python3 -m xigmalcd --status` and the desktop window are both clients of it.
Nothing about that changes what goes on the serial line; it only decides who is
allowed to put it there.

## 2. Frame layout

```
5A  escape( len_hi len_lo  <payload>  cksum )  5A
```

| field | size | meaning |
|---|---|---|
| `5A` | 1 | frame byte, at both ends (`'Z'`) |
| `len` | 2, big endian | total frame length **including** the 5 framing bytes, counted over the **unescaped** frame |
| payload | `len - 5` | request line + headers + blank line + body (§3) |
| `cksum` | 1 | `(len_hi + len_lo + sum(payload)) & 0xFF`, over the **unescaped** payload |
| `5A` | 1 | frame byte |

Minimum frame is 8 bytes (empty payload). No padding, no gap between frames.

Because `len` counts unescaped bytes, the wire frame is *longer* than `len` whenever the
payload needs escaping. That is the whole reason the old "try `len`, then `len+1` …
up to `len+24`" resync existed; it is gone. `protocol.read_frame(buf, i)` walks the
buffer unescaping as it goes, and the frame ends at the frame byte that lands exactly on
the declared length:

```python
fr, next_index = read_frame(buf, i)      # None -> not a frame (or not complete yet)
```

`Link.read()` feeds that from the serial port: whatever is already in hand is tried
first, so a complete frame is never held up waiting for bytes that do not exist.

## 3. Payload: a miniature HTTP

```
POST conn 1\r\n
SeqNumber=0\r\n
Date=1793856095051\r\n
ContentType=json\r\n
ContentLength=243\r\n
\r\n
{"attribute":["Status","Fan","Pump"], ... }
```

* **request line** — `<VERB> <topic> <detail>`; verbs the vendor code registers: `POST`,
  `GET`, `PUT`, `STATE`, `SET`, `DELETE`. Every reply from the panel is the line `1 200`
  or `1 400` (HTTP-ish — keep the digit test when validating frames).
* **headers** — `<Key>=<Value>\r\n` lines, terminated by a bare `\r\n`. No colon, no
  space, values are bare ASCII (dates are ms epoch integers).
* **body** — compact JSON (`json.dumps(o, separators=(",", ":"))`, no spaces, UTF-8), or
  empty. `ContentLength` is the byte length of that JSON **before escaping** — verified
  on all 180 captured frames that carry a body.

TX headers seen: `SeqNumber` (the host's own counter, 0,1,2,…), `Date` (ms),
`ContentType=json`, `ContentLength`. RX headers: `AckNumber`, `ContentType`,
`ContentLength`.

### AckNumber

A real answer carries **`AckNumber = SeqNumber + 1`**. This is not an assumption: the
vendor's response router looks the request up by `getAckNumber() - 1`, and logs
`"AckNumber error:"` for frames that do not match. Captures bear it out — request 0 is
answered `AckNumber 1`, request 184 is answered `AckNumber 185`.

The panel also sends frames with `AckNumber 0`, which cannot be matched to anything
(0 − 1 = −1): its own notice after a file transfer, and error answers. ALPHA warns about
them and drops them; `Link.awaited(seq)` does the same and hands them back as `strays`.
`Link.reply()` stays deliberately dumb (next frame, whatever it is).

So the request → reply map is:

| reply seen in the captures | count | answers |
|---|---|---|
| `1 200` (empty body, various AckNumber) | 91 | `STATE all 1`, `power`, `timeout`, transfer notice |
| `1 200 {"state":"success"}` | 88 | `POST transported 1` |
| `1 200 {"state":"success","blockMaxSize":1024}` | 87 | `POST transport 1` |
| `1 200 {device info}` | 1 | `POST conn 1` |

## 4. Escaping (the part that cost a day)

Between the two frame bytes the packer quotes both control bytes:

```
0x5A  ->  5B 01        (a frame byte would end the frame early)
0x5B  ->  5B 02        (a bare 5B would start an escape)
```

and nothing else. The extra `5B xx` bytes count for **nothing** in `len` or `cksum`; the
escaping even covers the `len` and `cksum` bytes themselves. That single rule explains
everything the earlier notes called exceptions:

* a `"fans":[` in the metrics blob, or a serial number containing `Z`, becomes escaped —
  the frame is longer on the wire than it declares, and both the checksum and the length
  are still correct once the escaping is undone (`protocol.unescape()`);
* the panel's `conn` reply, which looked like it broke the checksum by one, checks out
  exactly: all 267 captured replies pass `checksum_ok()`.

`protocol.escape()` / `protocol.unescape()` implement it; `mark()`, `unmark()` and the
`--no-marker` flag that belonged to the old model are gone.

File bytes streamed after a `transport` request are **not** escaped: a PNG full of `5A`
and `5B` goes over verbatim, and the only thing that delimits it is the `fileSize` in the
request.

## 5. Command set

ALPHA's request factory registers exactly these topics (decompiled `index.jsc`):

```
conn  all  waterBlockScreen  waterBlockScreenId  brightness  rotate  recovery
sysinfoDisplay  displayInSleep  fanLCDSet  mediaDelete  config  power
realtimeDisplay  presetThemeId  timeout  transport  transported
```

The panel gives one of three answers to anything you send, and that is the whole oracle
for mapping the command set without a capture of each one (`tools/fuzz.py`,
`tools/vendor_cmds.py`):

| outcome | meaning |
|---|---|
| no answer at all | the firmware does not know that topic |
| `1 200` (bare or with a body) | accepted |
| `1 400` | the topic exists, the body was wrong |

Live verdicts for the registered topics, on firmware `V1.2.3`:

| request | body | verdict |
|---|---|---|
| `POST conn 1` | – | `200` + device info (§7) |
| `POST power 1` | `{"event":"resume"}` | `200` accepted; lights the panel up (`brightness` 0 → 100) |
| `POST power 1` | `{"event":"lock-screen"}` | `200` accepted |
| `POST power 1` | `{"event":"unlock-screen"}` | `200` accepted |
| `POST power 1` | `{"event":"on-ac"}` | `400` |
| `POST power 1` | `{}` | **never answered** — ALPHA's bare "awake" call, the panel ignores it |
| `POST timeout 1` | `{"value":60}` | `200` accepted; sleep-after-N-seconds of idle line |
| `POST timeout 1` | `{"value":0}` | `200` accepted; never sleeps (`--no-sleep`) |
| `POST brightness 1` | `{"value":100}` | `200` accepted |
| `POST rotate 1` | `{"degree":0}` | `200` accepted |
| `POST presetThemeId 1` | `{"index":0}` … `{"index":8}` | `200`, and **this is what blanks a panel** — see the warning under the table |
| `POST presetThemeId 1` | `{"index":9}`, `{"index":99}`, `{"index":-1}`, `{"index":"0"}`, `{"index":1785506774474}` | `400` — the index is a small JSON integer, so the range really is 0–8 |
| `POST logo 1`, `POST mode 1` | 23 body shapes each (`index`, `value`, `id`, `themeId`, `name`, `type`, `n`, …) | `200`, and the field it names goes to `2147483647`. Writing `{"index":3}` to a panel reporting `logo=3` sets `logo` to `2147483647` (`tools/keyprobe.py`) |
| `POST realtimeDisplay 1` | `{"enable":true}` | `200` accepted — **the field must be a JSON boolean**: `{"enable":1}`, `{"value":true}` and every other shape tried give `400`. On the display it hides the OSD layer and shows the logo layer; it never draws the metrics itself (§11) |
| `POST realtimeDisplay 1` | `{}`, `{"index":0}`, `{"page":0}`, … | `400` |
| `POST sysinfoDisplay 1` | everything tried (12 shapes) | `400` — the topic exists in this firmware, the right body is still unknown |
| `STATE all 1` | metrics blob (§8) | bare `200` |
| `POST transport 1` | `{"type":"media","fileSize":N,"fileName":"…​.osd"}` | `200 {"state":"success","blockMaxSize":1024}` |
| *(raw bytes)* | N bytes | – |
| `POST transported 1` | `{"md5":"todo","fileName":"…​"}` | `200 {"state":"success"}` |
| `POST waterBlockScreen 1`, `waterBlockScreenId`, `displayInSleep`, `fanLCDSet`, `config`, `mediaDelete` | any | **no answer** — registered by ALPHA, absent from this firmware |
| `POST recovery 1` | `{"enable":true}` | `200` in 6 ms, then the USB device re-enumerates. This is the vendor app's reset; it is the only thing that repairs a panel whose `logo`/`mode` sit at `2147483647` (see below) |

**Everything ALPHA sent on 2026-11-05**, counted out of `logs/2026-11-5.log`
(1 864 requests, five sessions, hours 06/07/15/18/19):

| request | count |
|---|---|
| `POST transport 1` `{type,fileSize,fileName}` | 905 |
| `POST transported 1` `{md5,fileName}` | 905 |
| `STATE all 1` | 19 |
| `POST conn 1` | 11 |
| `POST power 1` `{"event":"resume"}` | 11 |
| `POST timeout 1` `{"value":60}` | 11 |
| `POST recovery 1` `{"enable":true}` | 2 |

That is the whole vocabulary — seven topics, no more, and every one of them is
implemented in `Link`.  Three things that settles, each of them a wrong turn we
had not yet taken: `STATE all` is **not** pushed every second (19 in a whole day,
a couple per session start), an `.osd` announcement carries no fourth key that
could mean "draw this now", and the perfectly-ticking session watched at 19:46 was
produced by nothing but these seven requests plus the file bytes.

**Do not write `logo`, `mode` or `presetThemeId`.** These three are the only
topics in the whole command set that damage a unit, and the damage is not
visible until the next cold boot. Measured on `V1.2.3`, twice:

* every accepted write leaves the field at `2147483647`, the panel's "not set",
  whatever body is sent — there is no way to put a value in from the wire
  (23 shapes tried for `logo` alone, `tools/keyprobe.py`);
* the running display keeps working (it latches the last uploaded frame), so
  the unit looks fine;
* with `logo` not set there is no boot animation, and the screen is **white
  from the first second of POST** — which is how it looks bricked when it
  isn't;
* `space` moves by ~1.3 MB, i.e. the panel frees the theme media it held.

`Link` refuses all three topics (`PermissionError`) unless built with
`allow_destructive=True`. `tools/theme.py` reports the fields and only writes
with `--force`; `tools/vendor_cmds.py` used to carry `presetThemeId
{"index":0}` in its SAFE list, which is what blanked a unit, and no longer does.

The fix is the vendor's own reset, and its exact bytes are in ALPHA's log at
18:39:48 on 2026-11-05, the moment "AIO Theme → reset" was clicked in Windows:

```
POST recovery 1        {"enable":true}         109-byte frame -> 1 200 in 6 ms
```

Nine seconds later that log reads `logo 2147483647 -> 3`,
`mode 2147483647 -> 0`, `osdState 1 -> 0`, `space 69252 -> 69664`. Reproducing
that one frame from Linux (`xigmalcd-reset --yes`, or `tools/reset_panel.py --yes` from
a checkout — both are `xigmalcd/reset.py`, and byte-identical to the
logged frame) does the same thing here: `logo -> 3`, `mode -> 0`,
`space -> 69664`, device back after ~9 s. It is a reset, not a firmware write —
it drops the stored picture and re-enumerates the USB device — but it is still
sent by exactly one hand-invoked command and by nothing in the client.

`md5` is the literal string `todo` in ALPHA's own traffic (`basename(file)` is the only
other key), so the panel is not checking a digest.

**`power` events.** ALPHA forwards Electron's `powerMonitor` events and its own enum
lists exactly seven: `suspend`, `resume`, `on-ac`, `on-battery`, `shutdown`,
`lock-screen`, `unlock-screen`, always as `{"event": …}`. `lock-screen` and
`unlock-screen` are only sent when `deviceConfig.OS === "MCU"`, so the vendor app never
sends them to a panel that reports `"OS":"Linux"` — ours accepts both with `200`, and
`resume` is what moves `brightness` from 0 to 100. `on-ac` gets `400`. `suspend`,
`shutdown` and `on-battery` were not sent on purpose: the first two are how the vendor
app blanks and ends a session on Windows.

**`conn` reports the theme only as a selection id, and we cannot write it.**
`logo`, `mode` and `osdState` are the fields that describe the panel's own
drawing: healthy values on every capture from Windows are `logo=3 mode=0`, and
`logo` is the boot-animation id (`3` = the ALPHA animation seen at POST,
`2147483647` = none, which is the white-at-POST symptom). `osdState` is 1 while
an uploaded picture is the thing being shown, and 0 when the panel has no OSD
layer and shows only its logo image — `recovery` sets it to 0, the first upload
of a session sets it back to 1. Writing any of these topics from the host only
ever clears them (see the warning above).

Two things in the vendor code are worth knowing even though they are not protocol:
`transport` picks `type: "firmware"` when the file's extension is `.zip` and `"media"`
otherwise — **never send a `.zip`, that is the firmware update path** — and ALPHA
transcodes video/images for the panel with ffmpeg (`-an`, `-r 20`,
`-pix_fmt yuv420p`, `scale=trunc(iw/2)*2:trunc(ih/2)*2`).

`realtimeDisplay` is only sent by ALPHA when `deviceConfig.OS === "RTOS"`; our panel
reports `"OS":"Linux"`, so this is unexplored territory: the panel accepts
`{"enable":true}` and changes nothing it reports back (`osdState`, `mode`, `logo`,
`brightness`, `degree`, `timeout`, `space` all unchanged). Whether it starts drawing the
`STATE all 1` numbers by itself can only be seen with eyes on the display
(`tools/realtime.py`).

## 6. Picture upload, step by step

The panel keeps files in its own storage and the live display shows the newest `media`
file it was given, so drawing a frame means uploading a PNG.  The working sequence,
confirmed against the vendor's own log and replayed from Linux:

1. `POST transport 1` with `{"type":"media","fileSize":<len>,"fileName":"<name>.osd"}`,
   and the frame **must carry a `ContentLength` header**.  Without it the media writer
   never engages, and it fails quietly.  Measured again on 2026-11-06 09:09 with the same
   24 550-byte vendor frame and the same file name, six uploads each way
   (`tools/cltest.py`):

   | `transport` frame | ack for the announcement | file notice | `transported` ack |
   |---|---|---|---|
   | with `ContentLength` | 6/6 `200` | 6/6, all `200` | 6/6 `200` |
   | without it | **0/6 — no reply at all** | **0/6 — silence** | **6/6 `200`** |

   So the panel does not go deaf: it drops the malformed request without answering it and
   answers the next well-formed frame normally.  That combination is the trap — a client
   that watches the `transported` ack sees `{"state":"success"}` six times and believes
   six files landed, while the media session was never opened and no file was written.
   Only the notice (`AckNumber: 0`) decides, and no notice is a failure (§5).
2. 20–50 ms later write the raw file bytes: **no framing, no escaping**, the vendor
   writes **blocks of exactly 1000 bytes** (25 blocks in under 90 ms, 24 KB in 87 ms
   ≈ 280 KB/s) and never mixes a frame into them.  The chunking itself is not checked —
   256, 500, 1000, 1024 and 4096-byte writes all landed.  The *pause before the first
   byte* is load-bearing, and it has to be at least 0.02 s.  Swept on 2026-11-06 with the
   same 24 550-byte vendor frame uploaded eight times per setting (`tools/order_probe.py`):

   | pause before the first byte | file verdicts, 8 uploads |
   |---|---|
   | 0.02 s | 8 of 8 accepted, verdict ~29 ms after the announcement |
   | 0.011 s (what ALPHA's own traffic shows) | mixed — some `200`, some `400` |
   | 0 s | 0 of 8 accepted, every `400` landing ~509 ms after the announcement |

   Read that table in either order and it holds.  Run again at 09:11 with the doubtful
   variant **first**, each variant on a session of its own (`--only tight,notice`):
   `gap=0` on a fresh session took 0 of 6, every `400` at ~508 ms; `gap=0.02` in the
   session straight after it took 6 of 6 with the verdict at 28 ms.  So neither a session
   warmed up by accepted uploads nor a cold one changes the answer, and the ~508 ms is the
   panel's media writer giving up on a session it granted moments earlier.
   The daemon's own loop agrees, and rules out the escape route: two back-to-back 120 s
   windows at 3 fps took **361/361** at 0.02 s and **0/128** at zero (127 `400`s, one
   notice that never came), and a 40 s scan at zero took 0/31 at 1 fps, 0/25 at 2 and
   0/48 at 3 — so it is the pause, not the spacing between uploads, and it does not get
   better by going slower.  A session renewal does not cure the refusals either (64 of
   them inside the 0/128 window, each followed by more `400`s).
   And note the trap in the `gap=0` row: `transported` was answered `{"state":"success"}`
   for all 8 refused uploads, exactly as it is for accepted ones.  A client that watches
   that ack reports a perfect run while the panel took nothing.
   *Correction, same day:* an earlier note here claimed `gap=0` had been accepted 6 of 6
   and answered fastest of all.  That read the probe's `grant` line, which is the
   `blockMaxSize` ack and arrives for every upload whether or not the panel takes the
   file.  Re-running the same tool on 2026-11-06 09:06 gives `['400']` for all eight.  The
   file notice (unlabelled, `AckNumber: 0`) is the only verdict — §5.
3. `POST transported 1` with `{"md5":"todo","fileName":"<same name>"}` — **after the
   panel's own file notice**, not immediately after the last block.  This one detail is
   the whole difference between a panel that redraws every second and one that crawls:
   `tools/order_probe.py` uploads the same vendor frame both ways on 2026-11-06, eight
   times per setting at 09:06 and six more at 09:11:

   | when `transported` goes out | first-byte pause | panel answers `transported` | file verdict |
   |---|---|---|---|
   | right after the last file byte (how we did it until then) | 0.02 s | **0 of 8** (1 of 6 earlier) | `200`, 8 of 8 |
   | after the notice, as ALPHA's traffic has it | 0.02 s | **8 of 8** | `200`, 8 of 8 |
   | after the notice, blocks of 1024 | 0.011 s | 8 of 8 | mixed `200`/`400` |
   | after the notice, no first-byte pause | 0 s | 8 of 8 | `400`, 8 of 8 |

   Two things that table makes clear and an earlier version of it did not.  **The file is
   taken in both orders** — the notice says `200` either way — so `transported` is not what
   makes the panel accept the upload, it is the step that makes it commit the file to the
   screen; that is why the old code looked healthy on the wire and crawled on the glass.
   And the verdict column has to carry the **code**: an earlier row here read "notice
   arrived in 19.6 ms" as the file being taken, when the notice it stamped was a `400`.

   ALPHA is not "waiting" for anything: its own file transfer takes 87 ms, so the notice
   (which lands 85 ms after the announcement) arrives on its own a couple of
   milliseconds before its `transported`.  A fast host has to put the confirmation there
   deliberately, because its own bytes are on the wire in 24 ms.
4. Steps 1–3 go out **back to back as one burst**.  Expect `1 200 AckNumber seq+1` with
   `{"state":"success","blockMaxSize":1024}`, then the file notice.  Our own part of it
   costs nothing: the `transport` frame is on the wire in 0 ms and 30 KB of file bytes are
   handed to the kernel in ~20 ms, at every baud from 9600 to 921600 and every write chunk
   from 64 to 16384 bytes (`tools/cycle.py`).  What costs time is the panel's own answer,
   and that is the slow part — see §9 for the two speeds it answers at.

**Do not wait for the `blockMaxSize` ack before writing the file.** It looks like a
handshake, but the media writer behind it is on a short timer: the file bytes have to
arrive within tens of milliseconds of the announcement, and an ack that is waited for can
cost long enough that the announcement's writer has already closed.  That is what the
early `1 400`s were — every ack-first attempt we measured (the baud/line-state sweeps, a
payload replay, a chunk sweep, a verdict-timing run, ~30 uploads) was refused, while the
same bytes sent as one burst were accepted 456 times out of 456 in a ten-minute run.
ALPHA also never waits: in its log the bare ack lands 33 ms after the request and the
file's last block is written 87 ms after it, in parallel.

**The verdict is the panel's own file notice: the unlabelled `1 200` / `1 400` with
`AckNumber 0`.** Nothing else says whether a file was *taken*.  `transported` answers
`{"state":"success"}` even for a file the panel threw away, and `conn`'s `space` does not
move for accepted uploads either (68704 before and after six accepted uploads).  But its
ack is not worthless: it says the confirmation reached the media writer in order, which is
the step that decides whether the picture is composited now or at the next sweep —
1 ack in 6 sent early, 6 in 6 sent after the notice.  `Link.send_media(order="notice")`
returns both, so a client can see the commit as well as the acceptance.  ALPHA's log
contains ~12 000 uploads and not one `4xx`, so `1 400` is always something we did.

**Accepted means available, not yet shown.** With the burst path the frame that gets a
`1 200` notice is the picture the panel will composite next time it looks, and it holds
that frame until a newer one arrives — watched on the unit: our drawn gauge with live
Linux sensor numbers, changing as the loop runs, but only every few seconds (§9 has the
measured tick, §11 the consequence for a clock). That is the second honest signal;
`space` never moves for `.osd` uploads, so notice plus eyes are all there is.

What the files look like: the payloads in the big IRP capture are **plain 480×480 8-bit
RGBA PNGs, 24–25 KB each**, named `2026-11-02_15-50-03-334.osd`
(`%Y-%m-%d_%H-%M-%S-%msec.osd`).  They were pulled out of the capture byte for byte
(`tools/vendor_capture.py`, and `tools/replay.py --extract` saves them for replay):
extracted length equals the declared `fileSize` exactly, the stream starts `89 50 4e 47`,
IHDR says `0x1e0 × 0x1e0`, depth 8, colour type 6.  The `.osd` extension is only a name —
the panel decodes the PNG magic.  They are also **~91 % transparent**: of 230 400 pixels
only about 20 000 are opaque, because ALPHA paints only the gauge and the text and lets
the panel's own layer show through the rest.  Upload an opaque frame instead and you
replace that layer completely — which is why our first tests covered the panel's logo
image entirely (`render.OVERLAY`, `--overlay`).

ALPHA's own cadence, straight out of `logs/2026-11-5.log` (819 uploads that day):

```
06:05:21.785 req  POST transport 1    seq=5  {"type":"media","fileSize":24461,...}
06:05:21.818 resp 1 200               ack=5                 (bare ack)
06:05:21.853 resp 1 200               ack=6  {"state":"success","blockMaxSize":1024}
06:05:21.870 resp 1 200               ack=0                 (file notice: accepted)
06:05:21.872 req  POST transported 1  seq=6  {"md5":"todo","fileName":"...osd"}
06:05:21.878 resp 1 200               ack=7  {"state":"success"}
```

Note the notice (`.870`) arrives *before* `transported` is even sent (`.872`): ALPHA does
not wait for it, and neither should we.  One upload per second, 87 ms of wire time each.

**Media is not limited to still pictures, and the video really does play.** The vendor
installer ships `resources/static/media/Theme_NN.mp4` files, and ffprobe says exactly
**480×480, H.264, `yuv420p`, 20 fps, no audio** — which is what ALPHA's own transcode
step produces (`-an`, `fps(20)`, `-pix_fmt yuv420p`,
`scale=trunc(iw/2)*2:trunc(ih/2)*2`).  Corrected on 2026-11-06, after two wrong claims
here: uploading ALPHA's own `1757491588831.mp4` (659 338 B) from Linux **does put a
moving picture on the panel's background layer** — watched on the unit afterwards.  The
earlier "stored but never plays" reading had two causes: our own uploads were fully
opaque frames covering the background layer completely, and a `recovery` puts the still
logo back until the file is re-uploaded (watched again the same night: after a reset the
background was the still logo, with our digits on top of it).  ALPHA re-uploads the file
at the start of every theme session — 9 s after a reset, ~0.1 s before the first `.osd`
of the stream (`2026-11-5.log` 19:46:36.385) — and it is a fresh write every time:
`space` drops by 736 whatever name is used, so the panel does not deduplicate by name
(`tools/vendortest.py --mp4`, `tools/bgtest.py`).  What remains unknown is what binds a
stored MP4 to a *chosen* theme without a `presetThemeId` write (§11).

## 7. Device info (`POST conn 1` reply, from the panel)

```json
{"attribute":["Status","Fan","Pump"],
 "OS":"Linux",
 "productId":"1",
 "version":{"app":"V1.0.2","firmware":"V1.2.3","hardware":"V2.0"},
 "space":69604,
 "brightness":0,
 "degree":0,
 "sn":"<redacted>",
 "osdState":1,
 "mode":0,
 "logo":3,
 "timeout":60}
```

* `attribute` — the OSD pages this firmware says it has (Status / Fan / Pump), i.e. which
  sections of the metrics blob it presumably renders. Never observed on this unit: our uploaded
  OSD covers the screen and there is no way to read the page contents back (§11), so treat that
  as the vendor's intent rather than a verified behaviour.
* `space` — free storage (KB, presumably).  It **never moves for `.osd` uploads**, so it
  is not a per-file ledger: 41 frames across two sessions on 2026-11-06 left it at the
  same value to the unit.  It does move when stored media is replaced: re-uploading
  `media/Theme_25.mp4` (214 917 B) under the name the panel already held took it
  62428 -> 62424 at 13:25 and 62424 -> 62416 at 14:42, and an earlier same-name
  overwrite of a 659 KB clip moved it by 20.  So a replace ticks it down a little, not
  by the file's size, and the step is not even constant for the same file - 4 then 8
  for two uploads of one identical MP4.  It also fell 69604 -> 69600 across a
  `presetThemeId` sweep, so some other activity writes too.
* `brightness` — 0 while asleep, 100 after `power resume`. `degree` — temperature unit
  (0 = °C). `timeout` — what `POST timeout 1` set. `osdState`, `mode`, `logo` — panel
  state, observed but not mapped.
* `sn` — this panel's own serial number, **redacted here**: it identifies the unit, not the
  protocol, and nothing in this repo needs it.  It is 20 ASCII characters and it contains a
  `Z`, and that is the fact the protocol cares about.  Earlier notes had `BY[L…` for its
  first bytes: that was the escaping misread — on the wire the `Z` is quoted as `5B 01` and
  the real byte is `Z`.
* `"OS":"Linux"` is a firmware build string, nothing to do with the host.

This frame is **escaped** (its payload contains `[`, `]` and the `Z` of the serial), which is
the one to test any reader against: 309 wire bytes for a declared length of 307, and a
checksum that only matches after the escaping is undone.

## 8. `STATE all 1` — the metrics blob

Schema and units, taken from the Windows capture and matched field for field by
`xigmalcd/sensors.py`:

| section | keys | unit / notes |
|---|---|---|
| `network` | `upload`, `download` | KB/s |
| `memory` | `total`, `used` | MB; `load` %, `temperature` (0 on Windows), `speed` MHz |
| `cpu` | `load`, `usage` %, `temperature` °C, `speedAverage` MHz, `power` W, `voltage` V | `voltage` 1.365 V matches `in0_input` of the same board's amdgpu sensor on Linux |
| `gpu` | `load` %, `temperature` °C, `fan` %, `speed` MHz, `power` W, `voltage` V, `memoryUsage`, `dedicated`, `dedicatedTotal` MB | discrete GPU fields |
| `disk` | `total`, `used` GB, `load` %, `activity` %, `temperature` °C, `readSpeed`, `writeSpeed` | |
| `fans` | list of `{onBoard: bool, type, name, value}` | RPM. `type` is `"Fan"` or `"Chassis"`; names are `"Fan CPU"`, `"Fan System 5"`, … |
| `motherboard` | `temperature` | °C, integer |
| `timestamp` | | ms epoch |

Absent sections are tolerated (Linux boards without tach signals simply omit `fans`).

**Those `fans` values are the host's, and they only ever travel down.** Every one of the 34
non-empty `fans` arrays in the log set (12 more carry an empty list) sits inside a frame whose
own bytes spell `STATE all 1`, and the capture's direction marker `--------->` points host to
panel in 34 of 34; no fan or pump value ever appears in anything the panel sent. The same logs
name their source: the app's hardware dump has a sensor collection called
`MSI X870 GAMING PLUS WIFI (MS-7E47) (Nuvoton NCT6687D)` carrying `Fan CPU` 1016-2448 RPM and
`Fan System 5` 1529-1582 RPM alongside the board temperatures and voltages, and the blob's
`fans` entries repeat those two channels. A pump value never appears anywhere in the logs,
even though the panel advertises one: its `conn` reply says `attribute:["Status","Fan",
"Pump"]`, and the app's own `deviceConfig` for this unit (`code C0FP01S0340`) says
`attribute:["Status","Pump"]`. Read as what it is - a capability list, not a source - the
panel is a display for fan data, never a measurement of it.

**Getting those two channels out of Linux (this box, 2026-11-06).** `sudo modprobe nct6683`
binds the same chip - the driver's own strings name NCT6683D, NCT6686D and NCT6687D - and
registers hwmon `nct6687` with ten tach inputs, four PWM outputs, and no `fan*_label` file at
all (it labels the temperatures: `AMD TSI Addr 98h`, `Diode 0 (curr)`, three thermistors). Only
two channels ever read non-zero: `fan1_input` and `fan12_input`. Which one is the cooler's fan
was settled by watching, not by looking a header up - 12 s idle, 45 s of all-24-thread load,
25 s cooldown, sampled every 3 s:

| channel | RPM over that window | moved with |
|---|---|---|
| `fan1` | 1360-2371 | `pwm1` 121-236 and k10temp Tctl 48-79 °C |
| `fan12` | 1538-1577 (never moved) | nothing |

Those spans line up with the vendor's Windows pair - `Fan CPU` 1016-2448 swinging,
`Fan System 5` 1529-1582 flat - so `xigmalcd/sensors.py` `FAN_CHANNELS` pins them under the
vendor's own names, and the theme draws two figures from them: `CPU FAN 1957 RPM` under the CPU
temperature and `GPU FAN 34%` under the GPU one.
`tools/fanscan.py --watch 90` reproduces the measurement on any board; there is no pump channel
here, which agrees with the logs never having carried a pump value.

**Send it twice at startup, then stop.** That is what ALPHA really does: in the 51-frame
init session, `STATE all 1` is TX frames 3 and 4 and nowhere else, and the 63-upload
capture contains no `STATE` frame at all — the picture loop never refreshes metrics.
Feeding the blob once per frame from Linux makes the panel stop answering the media
channel, so `xigmalcd` pushes it twice on start and leaves it alone; `--state-every N`
exists if you want to refresh it and are prepared for that.  The GUI follows the same
rule: `xigmaui/panel.py`'s `_open(blob=...)` pushes it twice at the head of any session
that puts a picture on the glass, never between files, and a session *renewal*
re-helloes without pushing it again.

## 9. Practical notes

* **Permissions (Linux):** the port is `dialout`-owned; add the user to `dialout` or use
  the udev rule in `install/99-xigmatek-lcd.rules` (mode 0666 plus TAGs for the two USB
  ids) and the systemd unit works unprivileged.
* **Only one process can hold the port.** A leftover ALPHA/`xigmalcd` session makes
  opens fail with `EBUSY`; `fuser -k /dev/ttyACM0` clears it.
* **Re-open resets the panel session**, so re-handshake after any serial error —
  `xigmalcd/main.py` does this and continues.
* **Sessions die, and how fast depends on the load.** Three runs:

  | run | rate | frames accepted | wall time before silence |
  |---|---|---|---|
  | gauge, 1 fps | 1 fps | 522 | ~522 s |
  | gauge, 1 fps | 1 fps | **522 again** | ~522 s |
  | clock, 2 fps | 2 fps | 717 | **368 s** |

  Same symptom every time: the panel sends *nothing at all* back — not a NAK, not a
  short frame, silence — and stays that way. Neither a fixed transfer count (522 vs 717)
  nor a fixed timer (522 s vs 368 s) fits, so it is some resource inside the firmware
  that runs out sooner the harder you push it.
* **What revives it** (`tools/session_limit.py` tries all three, in that order):
  * `POST conn 1` again on the same open port: **no**, silence continues;
  * dropping DTR and raising it again with the port still open: **no**;
  * **closing the port and opening it again: yes** — device info comes back first try,
    and the script re-checks that uploads really work, not just the handshake.
  Only ending the session at the CDC level resets whatever is exhausted, which is also
  why restarting ALPHA "fixes" it on Windows.
* So `xigmalcd` renews the session on purpose: `--session-max 500` uploads **or**
  `--session-ttl 300` seconds, whichever comes first. Set either to 0 to disable. After
  `RECOVER_AFTER` (2) consecutive refusals the loop re-handshakes, and if that is
  refused it closes and re-opens the port. **Verified:** with the defaults a 20-minute
  1 fps run delivered **1174/1174 frames with zero refusals**.
* **The renewal rate-scales exactly as intended, and costs nothing on the glass.** At
  3 fps the same `--session-max 500` fires twice in one 400 s run and both times at
  **500 uploads / 167 s** - identical both times, so the panel exhausts per *upload* and
  not per second. Neither renewal cost a frame: 539 uploads confirmed before the first,
  540 in the next slot after it, no `400`, no gap in the numbering. Whole run
  08:46:57-08:53:42: **1173/1175 frames accepted at 3 fps**, the only 2 misses an
  unrelated cluster of refusals described in §9.
* **An idle session is the same clock running the other way.** `pause` stops the loop
  drawing without letting go of the port, so nothing at all goes out and the session
  ages in real time while the glass sits on the last picture it was given. Measured on
  glass on 2026-11-06, six times, in `data/glass/2026-11-06-154148-socket-run.txt`,
  `...-155135-socket-run.txt`, `...-160240-socket-run.txt`, `...-161444-socket-run.txt`,
  `...-165549-socket-run.txt` (that one stopped by hand later, but its
  pause/frame/resume phases completed) and `...-180109-socket-run.txt`: a 20 s pause moved
  the frame counter by **0** and the confirmed-upload counter by **0** in every one, while
  the session the loop was
  holding aged from 48 s to 64 s across the pause, and to 69 s by the time the next phase
  asked for a frame (in the sixth run, 79 s: its phases are a few seconds apart
  differently, and the point is the age, not the number). On `resume` `xigmalcd` re-helloes,
  and re-opens the port first if the pause outlasted `--session-ttl`: that is the clock the
  measured silence above arrives
  on, and a hello alone has never revived a silent session. Each of the six resumed with
  one re-handshake and then drew 20 more uploads, and a `frame` asked for *while paused*
  was drawn too (+1 upload, the display still reported `paused`) after the loop brought
  the session up to date on the way: `~ session restored` at 15:43:00, 15:52:46, 16:03:51,
  16:15:56, 16:57:00 and 18:02:30, carrying the daemon's own note `resumed after 69 s idle:
  session renewed` in four of the five earlier runs - the first run's log has that note for
  its `resume`
  (15:43:04) but not for this forced frame, and nothing in the tree records what changed
  between those two runs, so that run's evidence is the restored-session line plus counters
  reading `session 1 uploads / 4 s` after a session aged to 69 s; the sixth run prints
  `resumed after 79 s idle: session renewed` for its forced frame and `session 1 uploads /
  4 s` straight after, which is the same story at a different age. A `frame` is therefore
  not a `resume`: it repairs the link and leaves the display paused. **What still has not
  been measured through** is a pause longer than `--session-ttl`, which is the case that
  needs the port reopened rather than the hello, and a session left idle for hours. The
  renewal clock itself has now been seen running on its own on real glass four times:
  `session renewed after 299 uploads, 300 s`, `after 295 uploads, 300 s`, `after 299
  uploads, 300 s` and `after 301 uploads, 301 s`, with drawing continuing through each -
  the last of those runs was at 374 of 374 uploads a minute after its renewal and 498 of
  498 at the end. The fifth window never got there: it was stopped at 17:00:58, and its
  session had just been brought up to date at 16:57:05, so its next renewal was still
  ~70 s away.
* **Time the panel's replies when they arrive, not when you get round to reading them.**
  An earlier version of this file claimed the panel serves the link "in ~1-second cycles
  of ~512 bytes" (`conn` 1018 ms, `power` 1013 ms, `transport` 1537 ms).  That was our own
  client: those figures were timestamps of when a request/response loop happened to read,
  and the loop was busy writing.  Our writes are the fast half — a 5 KB file reaches the
  kernel in 21 ms and a 35 KB one in 54 ms, at 9600, 115200 and 921600 baud and with write
  chunks from 64 to 16384 bytes, all the same (`tools/cycle.py`, `tools/writebench.py`).
  Stamped on arrival, the media exchange answers ~30 ms after `transport` at 0.02 s gap,
  against 13-26 ms in ALPHA's own log.  The read side has to be woken by the byte to see
  that: a pump polling with a 200 ms `read()` timeout measures 100-190 ms, which is our own
  poll granularity and not the panel's.  `Link.start_pump()` exists so a client cannot make
  this mistake: a daemon thread holds a read on the port and `read()` only waits on it.
* **`1 400` on uploads was our pacing, not the panel** (this corrects an earlier
  conclusion here, which blamed a wedged media service).  The evidence that cleared the
  panel: its log holds ~12 000 uploads with zero `4xx`; a genuine `.osd` payload lifted
  out of the IRP capture gets `1 200` when sent as one burst and `1 400` when the
  `blockMaxSize` ack is awaited first — same bytes, same size, same name pattern.  Baud
  rate (9600…3000000), DTR/RTS combinations, payload content, chunk size, file-name
  patterns, panel power/theme state and host write throughput (1.6–7.5 MB/s into a
  480 Mbit gadget) were each swept live and none of them changed the verdict; the two
  things that do are the **`ContentLength` header** and **not reading between the three
  writes**.  A missing `ContentLength` is the quieter failure: the panel says nothing at
  all, which is easy to mistake for a dead session.
* `send_media()` treats a missing notice or any `4xx` as a failure.  Note that the old
  success test — `transported` → `{"state":"success"}` — is worthless: the panel says
  that even after refusing the file, which is how "1174/1174 frames delivered" once
  meant "the screen never changed".
* **"Black screen" is not one failure, it is two.** The panel being dark usually just
  means it is asleep: `conn` then reports `brightness: 0`, and `power resume` takes it
  to 100. Separately, if the media slot holds no usable image the panel draws its
  **built-in logo** — the logo layer is a static image once POST has finished, and it is
  what shows whenever the OSD layer has nothing in it. So a dark panel with a healthy
  link and a refused upload are different problems, and the logo is proof the display
  service is still alive. A *white* screen is a third thing: `logo` sitting at
  `2147483647`, which only a host write can cause and only `recovery` undoes (§5).
* **What the display does with the pictures we send, measured with the panel in a
  healthy state (`logo=3 mode=0`) and eyes on it.** The panel composites two layers: a
  background layer (a stored still image, or the stored MP4, which plays — §6), and the
  OSD layer, which is the newest uploaded `.osd` PNG. It always jumps to the **newest**
  file it holds rather than playing through what it took, and holds that frame
  indefinitely, which is why a run can be read off the frozen screen afterwards:

  | what was uploaded, one per second | frames seen on screen | settled on the newest? |
  |---|---|---|
  | flat solid colour, 1 584 B | 8–15 in 30 s (one every 2–3 s) | yes (ended magenta) |
  | big counter, 16–30 KB RGBA | 6 of 30 (~7 s) | no, ended on 24 |
  | same counter, 6.4 KB indexed | 3 of 30 (~15 s) | ended on 28 |
  | same counter, one frame per 5 s | 3 of 12 | **yes, ended on 12** |
  | overlay counter (89.9 % transparent), 14.9 KB | 7 of 30 (~6 s) | logo visible behind the digits |

  Those five rows were measured with our own client, and so was everything below — all of
  it with `transported` sent right after the last file byte, which is now known to be why
  they crawl (§6, and the phase table further down). Repeated on 2026-11-06 with the
  traffic made byte-for-byte identical to ALPHA's (`tools/vendortest.py`), watching the
  LCD, counting changes in 20–40 s windows, every frame accepted with a `200`:

  | run, all at ALPHA's own 1.013 s period | visible changes | frozen last frame |
  |---|---|---|
  | 40 overlay frames, no metrics traffic | ~7 in 40 s | 32 of 40 |
  | **ALPHA's own 65 captured `.osd` PNGs, byte for byte** | — | 53 of 65 |
  | 20 overlay frames | 4–6 in 20 s | 19 of 20 |
  | 20 overlay frames, panel freshly `recovery`-reset | 3 in 20 s | — |
  | 45 s phases cycling plain / past-dated names / future-dated names / 6 KB flat frames, background video playing (`tools/watchtest.py --phases APQT`) | "few frames in each window and big jumps" in **every** phase | — |

  So from Linux the OSD layer moves about once every 4–6 s, and the phase test says what
  it does **not** depend on: the wall clock embedded in the file name (P and Q, ±2 h,
  made no difference), the frame's size or content (6 KB flat frames jumped exactly like
  24 KB glyph frames), the background video playing, metrics traffic, or how long the
  session has run. **That is not a hardware limit** — see the next bullet.
* **The panel does display one frame per second, and ALPHA gets it.** On 2026-11-05 the
  user pressed ALPHA's own "AIO Theme" reset on Windows, watched the LCD, and reported the
  gauge and clock "updating every second perfectly, not missing a frame or a second even".
  Its log for that session (19:46:27 → 19:47:19) is `recovery`, 9 s, then
  `conn`/`power resume`/`timeout 60`/`STATE all`×2, then the 659 338 B theme MP4, then 42
  `.osd` uploads in 43 s at 1.013 s apart with the file notice back 13–26 ms later. Every
  one of those frames reached the glass.
* **It was on our side of the wire, and it is the ordering of `transported`.** Found on
  2026-11-06: sending the confirmation *after* the panel's own file notice, as ALPHA's
  traffic has it, rather than right after the last file byte.  Two independent signals:
  the panel then answers `transported` with `{"state":"success"}` 6 times out of 6 instead
  of once out of 6 (`tools/order_probe.py`, §6), and with that order on the wire the LCD
  ticks at a true 1 Hz — watched for a whole four-minute window (`tools/watchtest.py
  --phases X`, 1024-byte blocks, 08:02:28–08:06:28), "perfect now ticking at 1Hz", 240
  frames, none refused - and it happened again in the same session: "ticking beautifully
  at 1Hz", 08:10:28-08:14:28, right after four minutes of our old order jumping.  The four
  shapes distinguished by phases, and the two things changed together in those windows:

  | phase | block size | `transported` | verdict on the glass |
  |---|---|---|---|
  | Z | 1000 | after the panel's notice | **1 Hz** — 08:21:59–08:25:59, "ticking nicely at 1Hz" |
  | X | 1024 | after the panel's notice | **1 Hz** — watched four times in all: 08:02:28–08:06:28 (240 frames, none refused), 08:10:28–08:14:28, 08:29:59–08:33:59 |
  | A | 1000 | right after the last byte | jumps, 4–6 s per change — every earlier run, then 08:06:28–08:10:28 "dropped back to jumps indeed", 08:14:28–08:18:28 "jumps again", 08:25:59–08:29:59 "was jumping" |
  | K | 1024 | right after the last byte | **freezes for many seconds, then jumps** — 08:33:59–08:37:59 |

  That is a full 2x2 with two rows and two columns read off the glass, in the same
  session on the same panel: the two notice-order phases tick at 1 Hz whatever their
  block size, the two send-it-early phases crawl at 1000-byte blocks *and* at
  1024-byte blocks.  **The block size does nothing; the ordering is the whole of it.**
  The wire measurement agrees without needing any of this: only the ordering was varied
  there, at 1000-byte blocks, and the `transported` ack count went 1/6 → 6/6.
* **What ALPHA paints, measured off its 65 captured `.osd` frames** (`data/vendor_frames/`,
  bench-only and gitignored — `tools/vendor_capture.py --extract` takes them back out of a
  capture — and the reason our first live runs looked wrong next to its):
  * **4.6 % of the pixels are painted** — 9 162 opaque plus 10 807 translucent out of
    230 400, the rest fully transparent, bounding box (106,10)-(367,468).  That is how its
    picture keeps the stored background playing: our opaque black canvas covered it, which
    is now `--bg black` rather than the default.
  * **the gauge is a 260-degree ring, not 300**: outer radius 127 about (236,236), 22 px
    thick, open at the bottom, from 140 degrees clockwise (PIL's degrees) over the top to
    40.  The filled part is opaque and graded cyan (0,247,255) at the low end to mint
    (0,251,184) at the tip; the unfilled ring is the same colour pale (160,242,245) at
    **alpha 128**, not a dark grey, so the background shows through the track too.
    Re-measured afterwards at one-degree steps on the same frame, printing the alpha along
    each ray rather than thresholding it: the band is **radius 109–132** (a 23 px stroke, so
    the outer edge sits at 132, not 127), solid ink runs from **136° to 45°** – a **269°**
    sweep, 91° open – with anti-aliased ends reaching 134° and 46°, and rays from 46° to
    133° carrying no ring pixel at any radius.  The two accounts are the same ring: the
    first was read in 5° bins, this one was not, and they differ by 4° at one end, 5° at the
    other and 5 px of anti-aliased outer edge.
  * **its temperature scale is near 30..75, not the 30..90 we had assumed**, and the two
    readings on the same frame agree: the digits read 57 °C while the arc fill measures
    144-158 degrees of the sweep (55.4-60.8 %), which on a 30..75 scale implies 54.9-57.3 °C.
    On a 30..90 scale the same fill would imply 63-67 °C, five to ten degrees away from its
    own digits, so 30..90 is ruled out.  A degree is therefore worth 2.2 % of the arc for
    ALPHA and was worth 1.7 % for us - its tip moves further for the same temperature.
    (Measured with an angle sampler on the ring at r=108..125, PIL degrees, taking the
    highest alpha along each radius.  The first two passes of that sampler were wrong - one
    used a maths-degrees base, one tripped on the anti-aliased seam at the start of the
    sweep and reported 0 - and both were corrected by validating it against frames whose
    fill the pixel map already shows, and against our own renderer at known temperatures:
    30 °C -> 0 deg, 45 °C -> 31.5 %, 52 °C -> 46.9 %, 60 °C -> 64.6 %, 75 °C -> 98.5 %.)
  * **it barely moves at idle either**: over those 43 s the tip travelled 14 degrees.  Our
    arc is driven by the same quantity and does the same: with a 4-core burn lifted this
    box to 93 °C and then released, the tip swept 256 degrees (pegged), 98.5 % → 38.5 % of
    the sweep as the temperature fell 93 → 48 °C, one step per second.  An idle desktop
    CPU sits inside a degree or two, so a temperature arc looks static on it; that is a
    property of the sensor, not of the wire, and `--gauge-source load` drives the arc from
    CPU busy percent instead when the point is to see it move - and that path was watched
    on the glass (window W3, 08:42:56-08:44:56, 121/121 frames accepted, title "LOAD ARC"):
    "the arc swings every second successfully".
  * text: title and digits white (digits 52 px tall, centred at (239,236)), caption mint
    green 12 px at y312-323, clock mint (0,250,232) 18 px tall, x187-305, y450-467.
* **The capture's own cadence, and what actually carries the value.**  Both sessions upload
  **exactly one overlay a second**: 65 `POST transport` announcements spread over 64 s in the
  long session (15:50:03–15:51:07, 2026-11-02) and 23 over 22 s in the one that starts at
    power-on (07:21:36–07:21:58, 2026-11-05) — every gap 1 s at the capture's one-second
  resolution, every payload a 480×480 RGBA PNG of 24 550–25 647 B.  The metrics blob is a
  different matter: `STATE all 1` is written **twice** in the power-on session (07:21:35 and
  07:21:36, whose own `timestamp` fields are 1 005 ms apart) and **not once** in the long one.
  The panel is fed pixels; the numbers only go to whoever asked.  Which is why the text the
  panel shows — `HH:MM`, `Week_en`, `kb/s` — has to be read out of the vendor's pictures and
  its bytecode rather than expected on the wire (§8, §10).
* **The ring follows the digits it paints, not the newest sample it was given.**  In the
  power-on session the app sent `cpu.temperature` 57 then 56 and never sent the blob again,
  while over those same 23 frames the digit it painted fell 57, 56, 54, 52, 50, 48, 47, 46,
  45, 44, 43, 42 (read off the contact sheet, by eye) and the ring's stop moved with the
  **painted** digit in every frame, never with the 56 still on the wire.  So a `STATE all`
  body and the overlay that follows it are not a pair: on this bench they were two seconds
  and fifteen degrees apart by the end of the session.  `tools/theme_check.py --arc` pairs a
  frame's ring stop to its painted digits for that reason — by grouping frames by the pixels
  they paint for the arc's own `source` — and does not use the blob at all.
* **The ring's geometry and value law, re-measured against the layout — this supersedes the
  "outer radius 127 … 22 px thick … scale near 30..75" reading above.**  That reading came
  from one frame, a max-alpha-along-a-radius sampler in 5° bins, and digits read by eye; what
  follows comes from the theme's own layout (`themes/alpha/layouts/480X480/1757491588836.json`)
  and from all 88 frames of both sessions, read as alpha crossings at half of each side's own
  plateau (`tools/theme_check.py --arc`, and `themes/alpha/README.md` has the full table):

  | | the old reading | measured now |
  |---|---|---|
  | centre | (236,236) | (237,236), which is the layout's box (107,106) 260×260 |
  | stroke band | radius 109–132, "23 px" | 19.75–20.50 px wide, centre at radius 119.38–121.00 — the layout's `radius 110` + `width 20` |
  | sweep | 269° of solid ink, 136°→45° | 135°→405° with **butt caps at the declared angles**: the fill's near edge crosses half coverage at +0.015° in all 88 frames |
  | value law | scale "near 30..75", 2.2 % of the arc per °C | `(value − minValue)/(maxValue − minValue) × sweep` with the declared 0/100, i.e. **2.7082° per unit** measured against 2.7000 declared, worst residual 0.32° |
  | unfilled track | "same colour pale at alpha 128" | confirmed at exactly **128** = `rgba(161, 246, 255, 0.5)`, painted at the same 20 px width to the end of the sweep |

  Note the old 57 °C frame fits the new law: 57/100 × 270° = 153.9°, inside the 144–158° the
  old sampler gave, so the "30..75" scale was inferred from a reading too coarse to need it.
  One frame is the exception on purpose: `2026-11-05_07-21-36-052.osd`, the first of the
  power-on session, paints `57°C` with its fill at **135.06°** — the ring was still animating
  up to the value while the digits were already there.
* **The on-screen clock is stale by up to one frame period, and that is arithmetic, not a
  bug.** The picture you see is the newest frame the panel has committed, and that frame was
  rendered and uploaded a moment ago: render, `transport`, bytes, notice, `transported` and
  its ack put the commit ~90-140 ms after the render (§6 step 3), and the frame then holds
  until the next commit.  So at any glance the seconds digit is 0.1-1.1 s old at 1 fps and
  0.1-0.45 s old at 3 fps.  Measured both ways with eyes on the same picture, the only thing
  changed being the rate: at 1 fps (08:38:30-08:40:30, 121/121 frames accepted) "the clock
  is ~1 s behind"; at 3 fps (08:40:43-08:42:43) "the clock seems to be matching the linux
  system's time".  ALPHA's 1.013 s period gives it exactly the same lag as our 1 fps, which
  is easy to miss next to a Windows clock nearly two hours off - so matching the vendor
  traffic also means matching its ~1 s clock error.  More frames per second is the only
  cure; the panel takes 3 without refusing.
* **The transparent canvas is what makes the background layer visible**, confirmed on the
  glass rather than inferred: the same stored MP4 that plays on Windows showed through our
  gauge as soon as the frames stopped painting every pixel (08:38:30-08:40:30, "background
  video visible behind the gauge").  With `--bg black` the same session shows a black field,
  which is what our earlier runs did.
* **Every background clip in ALPHA's library, measured, because brightness and the loop join
  both decide what the picture looks like.** 40 clips at 480x480 in
  `Program Files/ALPHA/resources/static/media`, each decoded whole and measured frame by frame:
  mean luma of the gray plane, and a *seam* - the mean absolute difference between the last
  frame and the first - against the median difference inside the loop.  Nothing was uploaded to
  measure any of it, and every figure here was measured on 2026-11-06 rather than carried over:
  the seam numbers in the earlier notes were wrong on several clips (`theme_48` was listed at
  0.2 and measures 4.50).
* **Brightness first, because every glyph on this panel is white** - ours and ALPHA's widgets
  alike (`textColor: "rgba(255, 255, 255, 1)"` throughout `store.json`).  Mean luma of
  `theme_48` is 227.3 of 255: a near-white field with white text on it.  `Theme_07` (177.5) and
  `Theme_28` (151.7) are close behind; `theme_49`/`theme_40` sit at 111/103.
* **Then the loop seam.**  Worst joins, seam against typical motion inside the loop: `theme_46`
  2.39 vs 0.19 (12.5x), `theme_39` 77.35 vs 10.05 (7.7x), `theme_48` 4.50 vs 0.60 (7.5x),
  `theme_41` 11.44 vs 1.72 (6.7x), `Theme_22` 2.48 vs 0.38 (6.6x), `theme_47` 6.23 vs 1.52
  (4.1x).  Best joins, where the cut is *smoother* than the clip's own motion: `Theme_29` and
  `theme_51` (byte-identical twins, 0.01 vs 0.83), `Theme_15` (0.00 vs 0.09), **`Theme_11`
  (0.11 vs 2.54)**, `Theme_23` (0.33 vs 1.59), `Theme_35` (0.30 vs 1.00), `Theme_24` (1.55 vs
  2.93).
* **Then black frames**, which read as a stutter: only 6 of the 40 reach pure black (mean luma
  under 2) at all - `Theme_29`/`theme_51` (126 black frames each), `Theme_15` (119),
  `Theme_23` (20), `Theme_35` (14), `theme_39` (5).
* **The clip ALPHA had active, `media/background/1757491588831.mp4`, is a byte-identical copy
  of `Theme_35.mp4`** (md5 `170f837142ae7dd136730cce0536571d` for both), and it is a
  fade-to-black loop: 101 frames at 20 fps in which **frames 0-10 and 96-100 are pure black** -
  0.8 s of black, ~1.15 s counting the fades, once per 5.05 s loop.  It is encoded to join that
  way on purpose: seam 0.30 against 1.00 typical motion, so the join is smoother than the normal
  motion and the animation breathes - bright, black, bright.  Cutting the black out makes it
  worse: a straight trim to frames 11-95 leaves a **4.88** jump at the seam, five times the
  normal motion.  **The eye on the glass under Windows has seen the dip: yes, it is there on
  Windows with that background** - "there was a duration of the dark part on windows with that
  background", 2026-11-06.  So the panel loops that file for ALPHA exactly as it loops it for
  us: the dip is authored into the clip, not a link artefact.
* **What this project ships with, and why.**  `Theme_11.mp4` (3 402 098 B, 363 frames at 24 fps,
  a 15.1 s loop): dark (13.3-24.1 mean luma), no black frames, and the best join of any clip
  that is not near-still, 0.11 against 2.54.  `Theme_24.mp4` (0.94 MB, 4.04 s, seam 1.55 vs
  2.93, luma 15.2-24.8) is the small upload that still reads seamless.  `Theme_25.mp4` - the
  clip the selected theme names, 214 917 B, 23 frames, a 0.96 s loop, 0 black frames, mean luma
  17.1-18.5 - has the shortest loop in the library and a join of 2.50 against 1.51, i.e. a small
  jump once per second.  It is the shipped default anyway (`DEFAULT_MP4`, `media/Theme_25.mp4`),
  because reproducing the vendor's own theme/background pairing is the deliverable; `Theme_11`
  and `theme_48` are vendored alongside it as `--mp4` one-flag alternatives, and `theme_48` is
  the case the automatic `--scrim` plate exists for (luma 227.3 under white glyphs).
* **A single `1 400` pair, in one run out of many, 13 s into a session that began with a
  background upload.** Frames 39 and 40 of the S1 soak - about 13 s into its frame loop,
  since the log does not stamp the refusals themselves - were refused: the file
  notice came back `1 400` with an empty body, which is the shape of a panel that is
  answering and simply will not take that file.  `RECOVER_AFTER` (2) did its job: the loop
  re-handshooked on the spot and the next 1 100+ uploads at 3 fps were all accepted, two
  session renewals included.  Two candidate causes, neither established: the 659 KB
  background uploaded at the head of that same session (no other session in this session's
  history refused anything at 3 fps: the 361-frame W2 window took all of them), or ordinary
  panel-side busyness.  Worth one line, not a theory: 2 of 1 175, self-healed, not
  reproduced.
* **The panel's power state is not the variable either**, whatever it was before: that
  session started with `brightness: 100`, awake, and both the ticking and the jumping
  windows ran in that state.  Worth knowing anyway because ALPHA sends
  `POST power 1 {"event":"resume"}` 11 times in its log and we send it once per session,
  in `hello()`; a panel left alone for four hours is found asleep (`brightness: 0`) again,
  and media traffic does not wake it (§5).
* **How fast it falls asleep between runs, and what stops it**: three runs that connected
  minutes apart (08:38:30, 08:40:43, 08:42:56) all found `brightness: 100`, because each
  one was still inside the 60 s keepalive window set by the previous run's `hello()`.  The
  next connect, 2 min 1 s after the last frame of the third (§6 run, 08:46:57), found
  `brightness: 0` — asleep.  So the sleep clock is roughly the keepalive we ask for, and a
  loop that keeps sending frames keeps the glass awake for free: any framed request counts
  as activity (§5).  A run that starts into a dark panel has to wake it with
  `power resume`, which `hello()` does, and the `1 200` of that request is not proof the
  glass lit.  **It does work, read off the panel:** the S1 session connected to a sleeping
  unit (`brightness: 0` after 2 min idle), sent the resume, and the user watched
  "S1 MP4+3Hz on the panel, with the background moving behind the gauge" for the whole
  400 s window (08:46:57-08:53:39).  So no `--no-sleep` and no extra wake traffic is
  needed for a daemon that starts at login - one `power resume` at connect is enough,
  and the frame loop then holds it awake.
* **What used to be the gap.** Every other traffic-level variable had already been swept
  from Linux and none of them moved the 4–6 s: byte-exact vendor frames, vendor cadence,
  vendor file-name format, RGBA like theirs, transparent overlay frames, no metrics
  traffic at all, waiting for each notice, the theme MP4 uploaded first in the session, a
  panel freshly reset by the vendor's own `recovery`, and a media state (`logo=3 mode=0`,
  background playing) matching Windows.  What *had* been equalised before that: bytes land
  in 24–25 ms at 0.02 s gap (ALPHA's own rate) and the notice comes back ~30 ms after
  `transport` (theirs 13–26 ms), after `start_pump()` was changed to wake on the byte
  instead of polling every 200 ms — our earlier "100–190 ms" was our own poll granularity,
  not the panel.
* **The OSD latches.** With the stream stopped, the last accepted frame stays on screen
  indefinitely — it does not fade, time out, or fall back to the logo. Useful for
  reading a measurement off the panel after a run, and it means "the picture is frozen"
  is not a fault.
* **`recovery {"enable":true}` is the cure for a blanked panel** and is now on the wire
  in one place only, `xigmalcd/reset.py` — met as `xigmalcd-reset` on an installed system
  and as `tools/reset_panel.py` (a wrapper over the same module) in a checkout. It is
  dry-run unless given `--yes` and
  prints the frame it will send. Reproducing it here took the unit from
  `logo=2147483647 mode=2147483647 space=68912` to `logo=3 mode=0 space=69664` in ~9 s
  with the device re-enumerating, which is the same free-space value the vendor's own
  reset landed on. Cold power cycles do **not** fix that state; only this does.
* **Sleep:** with `timeout=60` the panel blanks the display if nothing is sent for a
  minute; any framed request counts as activity, and the 1 fps picture loop keeps it
  awake by itself. `--no-sleep` sets `{"value":0}`.

## 10. Reading the vendor app yourself

`ALPHA.exe` is an Electron app: `resources/app.asar` unpacks with `npx asar extract`,
and the main process is `out/main/index.jsc` — Ignition bytecode for Node 11.4. The
working recipe:

1. build `d8` from V8 **11.4.183.29** (the version Ignition that bytecode came from)
   with the lazy-feedback-vector check in `StartupDataDeserializer::Deserialize` patched
   out, so `loadjsc()` accepts the file;
2. `./d8 --no-lazy -e "loadjsc('index.jsc')"` and dump the disassembly;
3. [View8](https://github.com/rhaym/v8view) (`view8.py --disassembled in.txt out.js`)
   turns it back into readable JS.

That is where the topic list, `md5:"todo"`, the `type: firmware|media` choice, the
ffmpeg flags, the `AckNumber - 1` lookup and the escape rules all come from.

`tools/asar_extract.py` does the archive part without node (list / `--to DIR` / `--cat` /
`--find`), and `--find` works on the compiled main process too, because a V8 bytecode
cache still holds its string constants.  Reading it that way on 2026-11-06 confirmed, in
the app's own words, the upload contract we already use: an announcement, then blocks
sized to the panel's `blockMaxSize`, then the completion request, with a 1000 ms wait for
each reply; the two media kinds the theme flow uploads are its background video and its
per-second widget image; and `md5:"todo"` is the vendor's own literal, not a placeholder
we invented.  Cross-checking its logs the same day: across all eight of them the app ever
sent seven command pairs, and the only media it ever uploaded was `.osd` (11 191) and
`.mp4` (10) - no layout or widget-definition file, so the panel is never handed the theme
JSON and cannot be drawing the gauge and clock itself.

**Not everything in the asar is bytecode.** Only `out/main/index.jsc` and
`out/preload/index.jsc` are; the Vue renderer bundles under `out/renderer/assets/` are plain
JavaScript, and that is where the human-readable part of the product lives - no V8 route
needed. Read out of the installed app at `Program Files/ALPHA/resources/app.asar` on
2026-11-06:

* the metric vocabulary the theme editor offers, in the app's own words: `cpuTemp` "CPU
  Temperature", `gpuTemp` "GPU Temperature", `cpuHz`/`gpuHz`, `cpuRate` "CPU Usage",
  `gpuRate` "GPU Usage", `cpuPower`/`gpuPower`, **`cpuFansSpeed` "CPU Fans Speed"**,
  **`gpuFansSpeed` "GPU Fans Speed"**, `waterPumpSpeed` "Pump Speed", `RAMRate`, `RAMSize`,
  `UsedRAM`, `availableRAM`, disk and network entries (the same list localised into zh-CN
  and zh-TW in the same bundle, `main-6b4df013.js`). Its own monitor page renders those two
  fan rows with the unit `RPM` (`Index-9579526f.js`), so fan speed is a first-class reading
  in this product - the app gets it from the machine, never from the panel;
* the fan names in the compiled main process (`out/main/index.jsc`, read as string
  constants): `sysinfoStatus:fans` and friends (`sysinfoStatus:cpu`, `:gpu`, `:mem`,
  `:network`, `:disk`, `:all`) are renderer-to-main IPC topics for the **host's** sensor
  table, and `waterBlockScreenFan` / `waterBlockScreenFanSet` are the app's own stored
  setting for the cooler (`store:waterBlockScreen:fan`) - neither is a panel request, and no
  frame carrying them ever appears in the captures. `settings:firmwareVersionFans*` belongs
  to the update path, which this project never touches (§5, "never send a `.zip`");
* the widget kinds a theme may contain and how they map onto the editor's canvas shapes
  (`themeUtil-6f6a57f7.js`): `text` → text-node, `data` → number-text-node, `arc` →
  doughnut-node, `bar` → process-bar-node, `chart` → chart-node, plus `img` and `line`.
  Each widget carries `property[0]` with `x`, `y`, `width`/`sizeWidth`,
  `height`/`sizeHeight`, and `store.json`'s `presetTheme[]` holds those numbers verbatim -
  which is how the `alpha` theme in this repo was redrawn, widget for widget;
* the editor previews are built from the same records: `theme.id`, `theme.osd.path` (the
  PNG the app renders), `theme.background.path` and `antvX6.cells` from `osd.widget[]`.

**The other vendor package** (`/media/.../Connect-Display-Setup-Software-2025-1125.zip`,
304 MB) is a Nullsoft installer: `7z x setup.exe '$PLUGINSDIR/app-64.7z'` then
`7z x app-64.7z` gives a full install of **ALPHA V1.0.13** (the panel itself reports app
V1.0.2). Its `resources/app.asar` → `out/main/index.jsc` is **byte-identical** to the one
from the installed app (same md5), so the newer build adds nothing to the protocol — the
topic registry above is current. What that package adds is *content*:

* `resources/static/media/*.mp4` — the panel-bound video, all H.264 `yuv420p`: 40 files
  at 480×480, 3 at 320×240 (the other panel), plus one 960×720 RGBA PNG that a 320×240
  theme uses as a still background.  Rates, measured with ffprobe on 2026-11-07:
  **20 fps or 24 fps, never 30** — every `Theme_NN` clip is 24 fps except
  `Theme_35.mp4` (20 fps), and every `theme_NN` clip is 20 fps except `theme_38.mp4` and
  `theme_51.mp4`, which are 24 fps because they are byte-twins of `Theme_27.mp4` and
  `Theme_29.mp4` under other names.  23 to 817 frames, 0.96 s to 34.0 s per loop; the 27
  clips the shipped themes actually use run 23 to 480 frames (0.96 s to 23.35 s).  So
  "the vendor's clips are 20 fps" is half right, and the panel takes both rates (§6,
  where `Theme_11.mp4` is a 24 fps file);
* `resources/static/theme/<model>/480X480/*.thm` (23 files plus `default.thm`) and
  `.../320X240/*.thm` (4) — a `.thm` is a ZIP holding exactly one entry,
  `<themeId>.json`, and that entry is one long **hex string**.  Those are the theme
  definitions, and **they are readable: the key is in the app.**  Corrected on
  2026-11-07, and the whole library is now in this repo under `themes/alpha/`
  (that directory's `README.md` is the detailed write-up, `tools/thm_unlock.py` is the
  tool).  The cipher's own literals sit in `out/main/index.jsc`'s V8 constant pool,
  readable with `strings`:

  ```
  aes-256-cbc   createCipheriv   createDecipheriv   createHash   sha256   digest
  Byyeetek2368   427979656574656b
  "Invalid theme zip file: should contain exactly one JSON file"
  ```

  so a `.thm` decrypts as AES-256-CBC, PKCS#7, `key = sha256("Byyeetek2368")`,
  `iv = "ByyeetekByyeetek"` (that 8-byte constant twice — recovered, not guessed, by
  ECB-decrypting block 0 and XORing against the known `{"id":<digits>` prefix the ZIP
  entry's own name implies; identical on four files, then verified on all 27).  Each
  theme is self-contained: `background.pathData` and `osd.pathData` are base64 for its
  clip and its baked 480×480 overlay PNG, and **all 27 embedded backgrounds are
  byte-identical to one of the 44 loose clips** in the same `static/` tree, while all 27
  overlay PNGs are byte-identical to PNGs the running app keeps in
  `%APPDATA%\alpha\media\foreground`.

  That does not change what goes on the wire.  The layouts are still never uploaded
  (the paragraph above: only `.osd` and `.mp4` ever appear in the app's logs), so the
  panel is still not drawing gauges and clocks itself — but a Linux driver no longer has
  to reverse-engineer the vendor's designs from screenshots.  Read off the 27 layouts:
  152 widgets (`data` 66, `text` 66, `bar` 15, `line` 4, `arc` 1), all coordinates and
  font sizes in device pixels, colours as `rgba(...)`, metric sources as literal English
  strings (`CPU Temperature` 22, `CPU Usage` 16, `Time` 13, `Pump Speed` 9, …), and the
  formats and anchor conventions that the layouts do *not* state were measured off the
  vendor's own baked PNGs — see `themes/alpha/README.md`.
* `adb` DLLs, `ffmpeg.exe` and OpenCV. ADB is a hint that a `"OS":"Linux"` panel may have
  a second, non-serial path — unexplored, and the panel presents no ADB interface over the
  USB we see today.

## 11. Open questions

* **`mode`, `logo` and `osdState`: understood, and not writable.** `logo` is the boot
  animation id (3 = the ALPHA animation seen at POST, `2147483647` = none, hence a white
  screen at POST), `mode=0` is the healthy value, `osdState` is 1 while an uploaded
  picture is being composited and 0 when only the logo layer is showing. Every host write
  to `logo`/`mode`/`presetThemeId` clears the field to `2147483647` — 23 body shapes each
  — so these topics are refused in `Link` and the only repair is `recovery` (§5).
* **The nine "built-in themes" (`presetThemeId` 0–8) are a dead end.** They are accepted
  as a range and do nothing visible: on a healthy panel `{"index":3}` left `logo`, `mode`,
  `osdState` and `space` unchanged and the screen unchanged. What they demonstrably do is
  clear the panel's theme selection. Not worth touching again.
* **There is no panel-rendered content on this firmware.** The theme JSON in ALPHA's
  `store.json` does declare `osd.widget[]` sources (`CPU Temperature`, `Date&Time`), which
  reads as "the panel draws these" — it does not, at least not on this
  `"OS":"Linux"` / `productId 1` unit. With `realtimeDisplay {"enable":true}` enabled and
  25 s of `STATE all 1` metrics pushed and **no uploads at all**, the screen showed only
  the static logo: no numbers, no clock, and `conn` reported nothing changed. The vendor
  app draws the entire picture itself and streams it as PNGs, which is what the 11 130
  `.osd` uploads in its logs are. Panel-rendered widgets would be the only route to a
  clock ticking at a real 1 Hz, and they are not available here.
* **`realtimeDisplay {"enable":true}` on this unit hides the OSD layer** — the uploaded
  picture disappears and only the logo layer is left — and draws nothing itself. Treat it
  as a display-layer toggle we do not need (`tools/realtime.py`).
* **How the OSD layer repaints: it takes the *newest* file it holds, never plays through
  the backlog, and holds the last frame indefinitely.** No swap animation, no blanking
  between frames.  How often it does that is now settled too: **one second, from Linux
  as well** — see §6 step 3 and §9.  What decided it was the ordering of `transported`,
  not the panel, not the frame, not the host stack.
* **Why ALPHA's uploads landed at 1 Hz and ours did not — closed 2026-11-06.** ALPHA's
  `transported` goes out a millisecond after the panel's own file notice (inevitably: its
  own transfer takes 87 ms and the notice lands at 85 ms: `transported` two milliseconds
  behind it), while ours went out with the last byte, ~6 ms *before* our notice — bytes on
  the wire at 37.9 ms, `transported` at 38.4 ms, notice at 44.5 ms, medians of six.  Send
  it after the notice and
  the panel answers it 6/6 instead of 1/6, and the glass ticks at 1 Hz — watched in the
  same session where our old order was watched jumping minutes earlier (§9).  The host
  stack was never the reason, and neither was the panel's clock against the wall clock in
  our file names (P/Q phases, ±2 h, no effect).
* The right body for `sysinfoDisplay` (topic exists; `{"enable":true}` and 13 other
  shapes answer `400`).
* `space` is a coarse ledger: ~140 KB across a full day of heavy uploading, never per
  file; how many files the panel keeps and for how long is unmapped. What *was* unclear —
  why it jumped ~1.3 MB after the theme writes — is now explained: clearing the theme
  selection frees its media, and `recovery` frees more (68912 → 69664). The two halves of
  its behaviour are now separated by measurement rather than inference: `.osd` frame
  uploads leave it exactly where they found it (41 frames, 2026-11-06), while replacing a
  **stored** MP4 under a name the panel already holds ticks it down by a small constant
  (8 for the 214 917 B `Theme_25.mp4`, 20 for a 659 KB clip) instead of by the file's
  size.
* **What binds a stored MP4 to a *chosen* theme.** The storing and the playing are both
  proven now: `transport {"type":"media","fileName":"<epoch>.mp4"}`, 659 KB accepted,
  `space` moves by its size, and the background layer animates on the glass (§6, corrected
  2026-11-06).  Re-uploading it through the daemon (`-m xigmalcd --mp4`, 08:46:57) gives
  the two numbers that claim was missing: the file lands and is answered `200` **0.7 s**
  after the announcement - 659 KB in 660 thousand-byte writes, about 940 KB/s, so the
  "roughly a minute" guess in the earlier notes was wrong by two orders of magnitude - and
  re-uploading the *same* file name as an overwrite moves `space` by 20 (65084 -> 65064),
  not by the file's size, which is the ledger behaving as a replace rather than an
  addition.  The file's own shape, read with ffprobe: 480x480, **101 frames at 20 fps =
  a 5.05 s loop**, first frame pure black (so a background upload that starts with black
  is not the panel failing).  `tools/previews.py` lifts a mid-loop frame out of it and
  composites our OSD over it, which is how the README previews are made.  ALPHA re-uploads
  its background at the start of every theme session, so a
  `recovery` (which puts the still logo back) is followed by a fresh upload, not by a
  theme selection. Whether a *different* stored MP4 can be made the background without a
  `presetThemeId`/`logo` write is answered by the next two bullets: it can, by uploading it.
* **The background's fade-to-black seam: answered, and it is the clip.** The clip ALPHA had
  active before this one (`1757491588831.mp4`, 659 KB) goes fully black for 0.8 s of every
  5.05 s loop, by construction, and it joins that way on purpose (§9). Watching the same
  panel under Windows on 2026-11-06, with that background active, the dip was seen there
  too - "there was a duration of the dark part on windows with that background". So the
  panel loops that file exactly as authored and nothing about our upload causes it.  What the
  shipped default avoids is one of those failure modes: `Theme_25.mp4` (214 917 B, 23 frames,
  a 0.96 s loop) has **no black frames**, which is why it is what `--mp4` uploads by default,
  but it joins with a small jump once per loop (seam 2.50 against 1.51 typical motion).  It is
  the default because it is the vendor's own pairing for the selected theme, not because it is
  the smoothest loop here - `Theme_11.mp4` is (0.11 against 2.54), and it is vendored and one
  flag away: `--mp4 media/Theme_11.mp4`.
* **What the last-selected theme and background were, and that a different MP4 can become
  the playing background with no theme write.** `store.json` under
  `%APPDATA%/alpha` keeps the selection per serial number:
  `devicesInfo.<sn>.currentThemeId = 1785506775818`, which is `presetTheme[26]` in that same
  file - eight widgets, big CPU temperature plus CPU and GPU usage with bars - and
  `currentThemeBg = media/background/Theme_25.mp4`. The app uploaded exactly that file
  (`Theme_25.mp4`, 214 917 B, `1 200` notice at 09:38:12.355 in its own log), so the pair is
  recorded, not inferred. Re-uploading the same bytes from Linux works: `1 200` in
  0.25-2.4 s depending on size, and `space` in `state` is not a usable ledger of it: across
  four accepted uploads on 2026-11-06 it moved 65644 → 59652 → 56856 (two uploads of the
  3 402 098-byte `Theme_11.mp4`) and then back up 56856 → 62628 (an upload of the 214 917-byte
  `Theme_25.mp4`), a few KB either way regardless of what was sent. Nine more samples of
  the same file on the same day. Session-start uploads: 62416 → 62292 (down 124),
  62288 → 61972 (down 316), 61792 → 61784 (down 8), 61472 → 61276 (down 196) and
  61264 → 61136 (down 128). Mid-run, the same bytes queued over the control socket:
  62288 → 62292 (up 4), 61784 → 61468 (down 316), 61276 → 61264 (down 12) and
  61136 → 62220 (**up 1084**). A single run's `conn 1` also moved on its own: 62416 at
  hello and
  62288 a minute later. The step is not a constant, not the size, and not even stable between
  two reads with no upload in between - that +1084 is the same 214 917 bytes that elsewhere
  cost 316. Treat the file notice as
  the verdict and `space` as context. That closes the question of whether a *different* stored
  MP4 can be
  made the background without touching `presetThemeId`/`logo` (the write that damages a
  unit, §5): it can, by uploading it, because the panel plays the last media file it took.
  Whether the loop seam on the glass matches what the file's frames say still needs an eye
  on the panel, since no `GET` variant reads the display state back.
* **A background upload can get a `1 400` for no reason the file explains - and it is not
  fatal.** Same bytes, same name, same panel: refused at 10:17:22 (the attempt came less
  than a second after another process had opened and closed the port), taken at 10:19:12
  and again at 10:19:16, and taken a third time at 10:19:52 in a run that then drew 181 of
  181 frames at 3 fps. Now seen for both vendored clips and at the head of a clean session:
  `Theme_11.mp4` refused at 10:34:26 and accepted 5.1 s later on the retry, in a run that
  then drew 91 of 91 frames at 1 fps, and `Theme_25.mp4` refused at 11:04:01 and accepted on
  the retry in 2.3 s, that run also drawing 91 of 91. So: four refusals across many uploads,
  each followed by acceptance of the same bytes seconds later, never a frame loop lost.
  A fifth refusal, 15:43:24 on 2026-11-06, is the one that matters for the always-on path:
  that upload had been **queued over the control socket** in a process which had already
  renewed its session twice, it came back `400` with an empty body, the retry inside the
  same call took it 2.0 s later, and that run went on to draw 496 of 496 frames. A sixth
  and seventh, 15:53:11 and 15:53:12, are the same queue in another run where **both**
  attempts were refused: the daemon logged `background Theme_25.mp4 did not land: the panel
  keeps whatever it already has stored`, left the stored background alone, and that run
  still drew 492 of its 496 frames. A third such run refused at 16:04:17 and took the file
  on the retry 2.0 s later, drawing 496 of 496; a fourth took the same bytes on the first
  attempt at 16:16:21, in 0.4 s, and drew 498 of 498; a fifth refused at 16:57:25 and took
  the retry 2.0 s later, reaching 282 of 282 before its owner stopped the window; and a
  sixth took it on the first try at 18:02:54, `200` in 0.4 s and `space` 62 024 -> 61 896,
  in the run whose frames later measured 44-46 KB with the gauge rings (see the bullet on
  frame size below). So across six socket-queued uploads of one file: three refused on the
  first attempt and landed on
  the retry, one refused both ways, two accepted first try. The socket client never sees the
  refusal as an error: what it reads is the daemon's own `background <name> accepted` or
  `did not land` event, which is the only account a client gets of whether a queued file
  landed - and one retry is not always enough.
  In the same session a 70 KB ffmpeg re-encode of that clip (19 frames,
  20 fps, High profile, faststart) *was* refused while the 214 917-byte original next to it
  was accepted twice, so the shape is not the whole story either. What is settled is the
  handling: the background is one file among many, a refusal must not stop the picture loop,
  and one retry is enough in practice (`_upload_background`, `--no-mp4` to skip it).
* **The vendor app never sends a widget/layout file.** Across all eight of its logs,
  11 191 uploads carry `.osd` and 10 carry `.mp4`; nothing else, and the whole logged
  command vocabulary is seven request pairs (`conn`, `power`, `timeout`, `transport`,
  `transported`, `recovery`, `STATE all`). So the panel is not being handed the theme's
  `osd.widget[]` definitions by some route we have missed: ALPHA renders the widgets
  itself into the transparent PNG, and the perfect 1 Hz clock and gauge seen on Windows
  were that PNG stream. The `.thm` theme files in the installer are encrypted, but not
  unreadable — §10 has the container, the key and what the 27 layouts contain, and the
  library itself is copied into this repo at `themes/alpha/`; that is the reference a
  Linux driver has to draw from, since the panel is never handed those definitions.
  `realtimeDisplay`/`sysinfoDisplay` in the app's code belong to product paths this unit
  does not implement — which is why they answer `400` here.
* `GET`/`PUT`/`SET`/`DELETE` topics: registered verbs, never used in the captures.
* **Our own overlay frame's size, and what a gauge costs on the wire.** Until the encoder
  decision below, a transparent `alpha` overlay went up as one full RGBA PNG – the panel's own
  `.osd` payloads are RGBA too (§6) – and the daemon logs the byte count of every tenth frame,
  so these are wire numbers, not lab ones: **30 710–32 157 B** before that theme grew two gauge
  rings (`data/glass/2026-11-06-161444-socket-run.txt`), **44 388–46 014 B** after
  (`data/glass/2026-11-06-180109-socket-run.txt`), same theme, same transparent canvas,
  same 1 fps: **+13 KB per frame, +44 %**, which at 1 fps is about 13 KB/s more of wire.
  The `gauge` frames inside those same two windows – 24 160–27 763 B and 23 193–27 668 B –
  are the control: the link did not change, the picture did. At 3 fps the ringed picture is
  still taken without a refusal: **91 of 91** frames in 30 s, frames 39 400–45 244 B
  (`data/glass/2026-11-06-181251-fps3-alpha.txt`, one process, `--no-mp4`, so those bytes are
  the overlay alone). Those are RGBA-era numbers. Offline the same picture encodes to
  **12.1–13.6 KB** as an indexed PNG (`render.to_png(palette=True)`), and that was not a lab
  curiosity: **for a while the two owners of the port put different files on the wire for the
  same picture.** `xigmalcd` encoded RGBA over a transparent canvas (`main._png`, only offering
  the palette when the canvas was opaque), which is where the 44–46 KB above come from; the
  window's direct-port path called `render.to_png(img)` with no argument, so it got the indexed
  file – and the two watched GUI
  runs logged it: `one frame sent: alpha, 9 KiB PNG, notice 200` at 14:26:47 and 14:42:49, the
  theme before it had rings. That disagreement is now closed: `main._png` returns the indexed
  file on every canvas and `--truecolor` is the way back to RGBA, so the daemon, the plain loop
  and the window's own path put one file on the wire. The evidence for that decision, in the
  order it was gathered:

  * **The panel accepts either shape as an overlay.** Two sittings of the same ringed `alpha`
    picture, each one RGBA / indexed / RGBA back to back, one process each, same box, 1 fps,
    `--no-mp4`, transparent canvas. 2026-11-06 at 20:17:08 / 20:18:13 / 20:19:17: **61 of 61**,
    **61 of 61**, **31 of 31** frames, 42 585–45 040 B / 12 342–13 699 B / 42 001–45 597 B.
    2026-11-07 at 00:24:34 / 00:25:40 / 00:26:46: **61 of 61**, **61 of 61**, **31 of 31**,
    42 560–46 415 B / 12 169–12 401 B / 41 856–42 471 B. Nothing refused, so a transparent
    indexed overlay is answered exactly like the RGBA one, and the wire ratio is measured rather
    than extrapolated: means **43 304 B against 12 655 B** in the first sitting, **43 782 B
    against 12 289 B** in the second, **3.4×** either way — means taken over the frames each
    log prints, every tenth one. The two RGBA windows of a sitting agree with each other by
    **142 B (0.3 %)** in the first sitting and **1 595 B (3.7 %)** in the second, which is what
    makes the ratio worth quoting
    (`data/glass/2026-11-06-201708-encode-A-rgba.txt`, `-201813-encode-B-indexed.txt`,
    `-201917-encode-A2-rgba.txt`, then `2026-11-07-002434-encode-Awatch-rgba.txt`,
    `-002540-encode-Bwatch-indexed.txt`, `-002646-encode-A2watch-rgba.txt`).
  * **The eye sees no difference at this size.** The first sitting has no watcher recorded, so
    on its own it is acceptance-and-wire evidence only. It was repeated an hour later with the
    owner at the panel and each window's encoder written into its on-screen heading, and the
    verdict is **"no difference I could see"** – not in the arc's colour fill, not in how solid
    the digits and labels read. That is the measurement that closed the question. Each sitting
    is A/B/A rather than A/B, so a drift story cannot explain it either. CPU was 45–49 °C
    throughout the watched sitting, so both gauges were filled a little under half: the
    mid-range case, not the red end of the ramp and not a three-digit value.
  * **What the accepted file does give up, so the trade cannot go quietly stale.** Measured
    offline on one ringed frame, printed by `tools/selftest.sh` on every run: the RGBA file is
    **40 777 B and bit-exact**, the indexed file is **12 176 B** and keeps a graded alpha but
    moves it at **36 145 of 230 400 pixels by up to 28/255** and shifts the colour at **12 660
    pixels by up to 26**. Of **11 149 pixels drawn fully opaque, only 74 keep alpha 255**,
    because PIL's octree quantiser treats RGBA as one four-channel colour and averages the
    palette entry shared by a glyph pixel and a track pixel; the gauge ramp is drawn in 80
    colours along its fill and comes back in **13**, one flat colour every ~12 px of arc. The
    half-transparent track is the part that survives: 4 029 pixels at alpha 150, all of them
    back within 11/255 and only 16 by more than 1. That frame carries a seconds clock, so the
    exact byte and pixel counts move by a few hundred from minute to minute – the bands hold,
    not the individual numbers. None of it read on glass in the mid range; if the red end of the
    ramp or a three-digit temperature ever shows it, the answer is `--truecolor`.

  The earlier evidence for the shape itself stays as it was: §9's repaint table shows a 6.4 KB
  **indexed** file displaying (that one was not an overlay) and a 14.9 KB **overlay** displaying
  (its file shape is not recorded), and the watched GUI runs uploaded indexed PNGs of the
  pre-ring `alpha` theme at 9 KiB with the canvas default `clear`. One further window runs the
  new default end to end with no encoder flag given: `ENCODE DEFAULT` at 00:32:17, **31 of 31**
  frames at **12 322–13 372 B** where the same theme as RGBA had logged 42 560–46 415 B
  (`data/glass/2026-11-07-003217-encode-DEFAULT-indexed.txt`).
  The picture's own extremes were put on glass afterwards, with the numbers pinned by
  `--metrics-file` rather than waited for: the gauge ramp filled its whole 260° in the red third
  at **14 253–14 439 B** a frame (104 °C, **46 of 46**) and **14 528–14 557 B** (96 °C, **46 of
  46**), a column missing its temperature drew no arc and cost **11 261–11 398 B** (**46 of
  46**), and a longer repeat of the three-digit case ran **76 of 76** at **14 618–14 751 B**
  (`data/glass/2026-11-07-005051-pin-104-3digit.txt`, `-005142-pin-96-red.txt`,
  `-005233-pin-nocputemp.txt`, `-005552-pin-104-3digit-watch2.txt`). All indexed, all accepted,
  and **none of those four windows sent a metrics blob at all** — a pinned run refuses to hand
  the panel a number this machine did not measure, which is why their frame sizes are still
  comparable with the windows above: same file shape, same canvas, same picture channel, and
  the STATE traffic that normally opens a session simply absent.
* **The reply-latency question is closed.**  Every file shape — our RGBA and indexed
  PNGs, a 1.5 KB flat one, and the panel's own 24–25 KB payloads — answers with the file
  notice 60–160 ms after `transport`, at every cadence from 0.3 s to 3 s, when the replies
  are timed on arrival (`tools/hotpath.py`, `tools/fileshape.py`).  The earlier "bimodal
  40 ms vs exactly 1.00 s" was the client blocking on each verdict, plus timing replies
  when the loop got round to reading rather than when they landed.
* **Whether uploads can be pipelined: yes, and nothing special is needed.** Eight uploads
  every 0.3 s (≈3 fps) through one session: every file notice came back `200`, none
  refused, none missing.  The old "~1 fps ceiling" was our own blocking read, not the
  panel's.
* **The pause before the first file byte is required, and its size is measured — closed
  2026-11-06.** 0.02 s is clean at every rate and every session shape (361/361 in a 120 s
  window at 3 fps, 8/8 and 6/6 in single-frame sweeps); 0.011 s, which is what ALPHA's own
  traffic shows, is marginal and takes some `400`s; 0 s is refused every time, at 1, 2 and
  3 fps, in a fresh session and a warmed one, and the refusal arrives ~508 ms after the
  announcement.  `--gap 0.02` stays.  See the table in §6.
* **How the display repaints is settled above** (the table in §9 and the two
   bullets at the top of this section). What follows are the questions that are
   genuinely still open.
