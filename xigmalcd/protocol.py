"""Serial protocol used by the ALPHA app that ships with Xigmatek Connect AIO coolers.

Reverse engineered from Windows serial captures of ALPHA.exe on COM3 (see PROTOCOL.md).
Wire format:

    0x5A  escape( len_hi len_lo  <payload>  cksum )  0x5A

  len     u16 BE, total frame length including all 5 framing bytes, counted over
          the *unescaped* frame
  payload "<REQUEST LINE>\r\n<Key>=<Value>\r\n...\r\n\r\n<body>"
  cksum   (len_hi + len_lo + sum(payload)) & 0xFF, over the unescaped payload

Escaping (read out of ALPHA's own packer, out/main/index.jsc): between the two 0x5A
frame bytes, a 0x5A is written as 0x5B 0x01 and a 0x5B as 0x5B 0x02; both extra bytes
count for nothing in len or cksum.  File bytes streamed after a `transport` request
are sent raw, without any of this.
"""

from __future__ import annotations

import glob
import json
import os
import threading
import time

import serial

SOH = 0x5A            # frame start/end byte
ESC = 0x5B            # escape lead byte
ESC_Z = 0x01          # ESC ESC_Z -> one 0x5A
ESC_B = 0x02          # ESC ESC_B -> one 0x5B
VERBS = ("POST", "GET", "PUT", "STATE", "SET", "DELETE")

# Topics we refuse to send unless a Link is built with allow_destructive=True.
#
# `logo`, `mode` and `presetThemeId` answer 200 to every body tried (23 shapes
# for logo alone) and each write leaves the field at 2147483647, the panel's
# "not set".  A panel that reported logo=3 went to 2147483647 from writing
# {"index":3}; with logo not set the screen is white from the first second of
# POST, and the only known fix is the vendor app's own reset (Windows ->
# ALPHA -> AIO Theme -> reset, `waterBlockScreen().recovery(sn)`), which we do
# not send.  These writes are therefore one-way doors, not settings.
#
# Everything else on the list is firmware/update traffic, which can brick the
# panel and which the vendor app never sends either: across eight app logs and
# 22 380 requests its whole vocabulary is conn, power, timeout, STATE,
# transport, transported.
BLOCKED_TOPICS = frozenset(("logo", "mode", "presetThemeId", "theme",
                            "themeBackground", "logoSet", "config", "recovery",
                            "firmware", "update", "upgrade", "ota"))

# What the panel's media writer needs, measured: the raw stream is chunked at
# 1000 bytes (its blockMaxSize ack says 1024; chunking is not actually
# observable, 256- and 4096-byte writes land just the same), and the first file
# byte must not arrive until ~20 ms after the announcement.  Writing it
# immediately gets the file refused every time: 0/8 at 0 ms against 8/8 at
# 20 ms, same frame, same session (tools/order_probe.py, 2026-11-06).
MEDIA_CHUNK = 1000
# Measured, not guessed (tools/writebench.py, tools/order_probe.py, and the
# daemon's own loop): the pause between the `transport` announcement and the
# first file byte has to be at least 0.02 s.  Swept one 24 550-byte vendor
# frame, eight uploads per setting - 0.02 s took 8/8, 0.011 s (which is what
# ALPHA's own log shows) took a mix of 200s and 400s, 0 s took 0/8 with every
# refusal landing ~509 ms after the announcement, which is how long the panel's
# media writer waits before giving up on a session it granted.  The loop backs
# it up at scale: 361/361 uploads at 0.02 s against 0/128 at 0, and the failure
# does not go away by going slower (0/31 at 1 fps, 0/25 at 2, 0/48 at 3).
# 0.02 s also lands the whole 30 KB frame in 25 ms with its verdict back in
# 30 ms, so there is nothing to win by tuning it down; ALPHA's log shows 25 ms
# for the same pair of events, so this is the vendor's own envelope.
MEDIA_GAP = 0.02


class ProtocolError(Exception):
    pass


def compact(obj) -> bytes:
    """JSON exactly as ALPHA writes it: no spaces, no unicode escapes."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def escape(buf: bytes) -> bytes:
    """Quote 0x5A and 0x5B the way ALPHA's packer does.

    A frame byte would end the frame early and the lead byte would start an
    escape, so both get quoted; nothing else changes.
    """
    out = bytearray()
    for c in buf:
        if c == SOH:
            out += bytes([ESC, ESC_Z])
        elif c == ESC:
            out += bytes([ESC, ESC_B])
        else:
            out.append(c)
    return bytes(out)


def unescape(buf: bytes) -> bytes:
    """Inverse of escape().  A lead byte that quotes nothing is left alone."""
    out, i = bytearray(), 0
    while i < len(buf):
        if buf[i] == ESC and i + 1 < len(buf) and buf[i + 1] in (ESC_Z, ESC_B):
            out.append(SOH if buf[i + 1] == ESC_Z else ESC)
            i += 2
        else:
            out.append(buf[i])
            i += 1
    return bytes(out)


class Message:
    """A decoded frame: request line, headers, raw body bytes."""

    __slots__ = ("line", "headers", "body", "raw")

    def __init__(self, line, headers, body, raw=b""):
        self.line, self.headers, self.body, self.raw = line, headers, body, raw

    @property
    def verb(self):
        return self.line.split(" ")[0]

    @property
    def code(self):
        p = self.line.split(" ")
        return p[1] if len(p) > 1 else ""

    def json(self):
        return json.loads(self.body.decode("utf-8", "replace")) if self.body else None

    def __repr__(self):
        return f"<Message {self.line} {self.headers} {self.body[:60]!r}>"


def encode(line, headers=None, body=b"") -> bytes:
    """Build one frame.  `line` is e.g. 'POST conn 1'; body may be bytes/dict/list."""
    payload = compact(body) if isinstance(body, (dict, list)) else bytes(body)
    hdr = line.encode("latin-1") + b"\r\n"
    for k, v in (headers or {}).items():
        hdr += f"{k}={v}\r\n".encode("latin-1")
    hdr += b"\r\n"
    plain = hdr + payload                      # what len/cksum are computed over
    n = len(plain) + 5
    if n > 0xFFFF:
        raise ProtocolError(f"frame too long ({n} bytes)")
    hi, lo = n >> 8, n & 0xFF
    ck = (hi + lo + sum(plain)) & 0xFF
    return bytes([SOH]) + escape(bytes([hi, lo]) + plain + bytes([ck])) + bytes([SOH])


def inner(fr: bytes) -> bytes:
    """Length field, payload and checksum of a wire frame, escaping undone."""
    return unescape(fr[1:-1])


def decode(fr: bytes) -> Message:
    pl = inner(fr)[2:-1]
    head, _, body = pl.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    headers = {}
    for ln in lines[1:]:
        k, _, v = ln.partition(b"=")
        headers[k.decode("latin-1")] = v.decode("latin-1")
    return Message(lines[0].decode("latin-1"), headers, body, fr)


def checksum_ok(fr: bytes) -> bool:
    """Strict check: framing, length and cksum, after undoing the escaping."""
    if fr[0] != SOH or fr[-1] != SOH or len(fr) < 8:
        return False
    buf = inner(fr)
    n = (buf[0] << 8) | buf[1]
    if len(buf) != n - 2:                       # buf leaves out the two frame bytes
        return False
    return (buf[0] + buf[1] + sum(buf[2:-1])) & 0xFF == buf[-1]


def frame_ok(fr: bytes) -> bool:
    """Accept a frame on structure alone, ignoring its checksum."""
    if fr[0] != SOH or fr[-1] != SOH or len(fr) < 8:
        return False
    buf = inner(fr)
    n = (buf[0] << 8) | buf[1]
    if len(buf) != n - 2:
        return False
    line = buf[2:].split(b"\r\n", 1)[0].decode("latin-1")
    head = line.split(" ")[0]
    return head in VERBS or head.isdigit()


def read_frame(buf: bytes, i: int = 0):
    """Wire frame that starts at buf[i], as (bytes, index just past it).

    The declared length counts unescaped bytes, so the frame is found by
    unescaping while walking: the first unescaped pair gives the length, and the
    frame ends at the frame byte that lands exactly on that length.  None means
    "no frame starts here" (or it has not arrived in full yet).
    """
    if i >= len(buf) or buf[i] != SOH:
        return None
    un, j, n = bytearray(), i + 1, None
    while j < len(buf):
        c = buf[j]
        if c == SOH:
            # a frame byte is only legal at the very end of a frame
            if n is not None and len(un) == n - 2:
                return bytes(buf[i:j + 1]), j + 1
            return None
        if c == ESC and j + 1 < len(buf) and buf[j + 1] in (ESC_Z, ESC_B):
            un.append(SOH if buf[j + 1] == ESC_Z else ESC)
            j += 2
        elif c == ESC and j + 1 >= len(buf):
            return None                          # escape sequence still arriving
        else:
            un.append(c)
            j += 1
        if n is None and len(un) >= 2:
            n = (un[0] << 8) | un[1]
            if n < 8:
                return None                      # bogus length, resync
    return None


class Link:
    """Session over the CDC-ACM port: send a request, read its acknowledgement."""

    def __init__(self, port="/dev/ttyACM0", baud=115200, timeout=3.0, verbose=False,
                 allow_destructive=False):
        self.ser = serial.Serial(port, baud, timeout=timeout, write_timeout=timeout)
        self.ser.dtr = True           # ALPHA asserts DTR and clears RTS
        self.ser.rts = False
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self.seq = 0
        self.verbose = verbose
        self.allow_destructive = allow_destructive
        self._buf = bytearray()
        self._cv = threading.Condition()
        self._pump = False
        self._pump_thread = None

    def close(self):
        """Stop the reader thread before handing the port back: pyserial's
        close() nils its own fd and a pump between select() and os.read() then
        raises TypeError inside the thread."""
        self._pump = False
        thread = self._pump_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(0.5)
            self._pump_thread = None
        try:
            self.ser.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- sending -------------------------------------------------------------
    def request(self, line, obj=None, headers=None):
        """Send `line` (e.g. 'STATE all 1'); returns the sequence number to await."""
        topic = line.split(" ")[1] if " " in line else line
        if not self.allow_destructive and (
                topic in BLOCKED_TOPICS or topic.startswith("waterBlockScreen")):
            raise PermissionError(
                f"refusing POST {topic}: this topic is not in the vendor app's "
                f"vocabulary and on this unit it clears the panel's own theme "
                f"(logo/mode go to 2147483647, white screen at POST, fixed only "
                f"by ALPHA's AIO Theme reset) or is firmware traffic. Pass "
                f"Link(..., allow_destructive=True) to send it anyway.")
        seq, self.seq = self.seq, self.seq + 1
        hdrs = {"SeqNumber": seq, "Date": int(time.time() * 1000)}
        if obj is not None:
            hdrs["ContentType"] = "json"
            hdrs["ContentLength"] = len(compact(obj))   # ALPHA counts the *unescaped* JSON
        else:
            hdrs.update(headers or {})
        fr = encode(line, hdrs, obj if obj is not None else b"")
        if self.verbose:
            print(f"--> {line} seq={seq} len={len(fr)}")
        self.ser.write(fr)
        return seq

    def post(self, verb, obj=None):
        return self.request(f"POST {verb} 1", obj)

    def send_raw(self, data: bytes, chunk=1000, delay=0.0):
        """Stream unframed file bytes, in 1000-byte writes like ALPHA."""
        for i in range(0, len(data), chunk):
            self.ser.write(data[i:i + chunk])
            if delay:
                time.sleep(delay)

    # -- receiving -----------------------------------------------------------
    def start_pump(self):
        """Keep a host-side read pending on the port at all times.

        This is not an optimisation, it is how the panel is talked to.  With
        nobody reading, the panel's reply to a media upload is only delivered a
        constant 1022 ms after the file lands, however we send it - baud, chunk
        size, gap and file size make no difference, one retry tick per file.
        With a reader pending the same notice comes back in ~30 ms, which is
        ALPHA's own range (13-26 ms in its log).  The pump has to be woken by
        the byte rather than polled: with a 200 ms `read()` timeout we measured
        100-190 ms and mistook our own poll granularity for the panel's speed.
        Having somebody read also stops the panel queueing frames that then
        pile up behind the next upload.
        """
        if self._pump:
            return
        self._pump = True
        self._pump_thread = threading.Thread(target=self._pump_loop, daemon=True)
        self._pump_thread.start()

    def stop_pump(self):
        self._pump = False

    def pumping(self) -> bool:
        """True while a live pump thread is the only reader of the port."""
        return self._pump and self._pump_thread is not None \
            and self._pump_thread.is_alive()

    def _pump_loop(self):
        """Wake on the first byte, then take everything else already queued.

        The 50 ms cap is not a tuning knob, it is the wake-up latency: with a
        200 ms `read()` timeout the pump sat in `read()` when a reply landed, so
        the panel's verdict reached us 100 ms (median) after the panel had
        already answered it - an artefact of our own poll granularity, and the
        reason we measured 100-190 ms where ALPHA's log shows 13-26 ms.
        """
        while self._pump:
            self.ser.timeout = 0.05
            try:
                chunk = self.ser.read(1)
                if chunk:
                    # one frame never arrives spread over two polls: take the
                    # rest of what the kernel already has before handling it
                    rest = self.ser.in_waiting
                    if rest:
                        chunk += self.ser.read(rest)
            except (OSError, serial.SerialException):
                # pyserial raises this on CDC-ACM glitches - the kernel says
                # the port is readable and then returns nothing, which happens
                # when the panel resets and when two threads read at once.  It
                # is recoverable; a pump that dies here would leave every
                # read() waiting on a thread that no longer exists.
                time.sleep(0.05)
                continue
            if chunk:
                with self._cv:
                    self._buf += chunk
                    if len(self._buf) > 0x8000:     # nobody is reading: stale
                        del self._buf[:len(self._buf) - 0x8000]
                    self._cv.notify_all()

    def _fill(self, n: int, limit: float) -> bool:
        """Try to get the internal buffer up to n bytes.

        False means either the deadline passed or the device stopped sending
        mid-way; callers have to cope with a short buffer either way, because a
        frame's real length is only known once its last byte has arrived.
        """
        while len(self._buf) < n:
            left = limit - time.monotonic()
            if left <= 0:
                return False
            self.ser.timeout = min(left, 0.5)
            chunk = self.ser.read(n - len(self._buf))
            if not chunk:
                return len(self._buf) > 0
            self._buf += chunk
        return True

    def read(self, timeout=3.0):
        """Next Message, or None on timeout.

        Whatever is already in hand is tried first - every frame byte as a
        possible frame end - so a complete frame is never held up waiting for
        bytes that do not exist.  Bytes that line up with nothing are dropped
        one at a time until a frame byte starts a real frame.

        With `start_pump()` running the bytes arrive on the pump thread and this
        only waits on it; without a pump it reads the port itself.
        """
        limit = time.monotonic() + timeout
        while True:
            if self.pumping():
                with self._cv:
                    m = self._scan()
                    if m is not None:
                        return m
                    left = limit - time.monotonic()
                    if left <= 0:
                        return None
                    self._cv.wait(min(left, 0.25))
                continue
            m = self._scan()
            if m is not None:
                return m
            if time.monotonic() >= limit:
                return None
            if len(self._buf) > 0x10000:                # runaway: start over
                del self._buf[:len(self._buf) // 2]
            # grow geometrically: escapes make a frame longer than it declares
            if not self._fill(max(3, min(len(self._buf) * 2, 0x10000)), limit):
                return None

    def _scan(self):
        """Pull one complete Message out of the buffer, or return None."""
        while self._buf and self._buf[0] != SOH:
            del self._buf[0]
        for end in range(2, len(self._buf)):
            if self._buf[end] != SOH:
                continue
            got = read_frame(bytes(self._buf[:end + 1]), 0)
            if got:
                fr, nxt = got
                del self._buf[:nxt]
                m = decode(fr)
                m.headers["CkOK"] = str(checksum_ok(fr))
                if self.verbose:
                    print(f"<-- {m.line} {m.headers} {m.body[:70]!r}")
                return m
        return None

    def reply(self, timeout=3.0):
        """The next frame from the device, whatever it answers.

        Order is the only reliable thing in a stream of bare acks; `awaited()` is
        the call that matches a reply to its request.
        """
        return self.read(timeout)

    def awaited(self, seq, timeout=3.0, strays=None):
        """The frame that answers request `seq`.

        A real answer carries `AckNumber = SeqNumber + 1`: ALPHA looks the
        request up by AckNumber-1 and logs "AckNumber error:" about frames that
        do not match, which is how the rule is known.  The panel also sends
        unlabelled frames (AckNumber 0) - its own notice after a file transfer,
        and answers it could not match - so those are collected in `strays`.
        A 4xx is always reported as an error: the panel gives its failures an
        AckNumber of 0, so they cannot be lined up with a request afterwards.
        """
        limit = time.monotonic() + timeout
        seen = []
        while time.monotonic() < limit:
            m = self.read(timeout=max(0.05, limit - time.monotonic()))
            if m is None:
                break
            if m.code.startswith("4"):
                raise ProtocolError(f"device answered {m.code} to request {seq}: "
                                    f"{(m.body or b'')[:60]!r}")
            if m.headers.get("AckNumber") == str(seq + 1):
                if strays is not None:
                    strays.extend(seen)
                return m
            seen.append(m)
        if seen:                                  # an unlabelled ack is still an ack
            if strays is not None:
                strays.extend(seen[:-1])
            return seen[0]
        raise ProtocolError(f"no reply for request {seq}")

    def drain(self, timeout=0.15):
        """Throw away anything the panel sent but we never read."""
        n = 0
        while self.read(timeout=timeout):
            n += 1
            timeout = 0.05
        return n

    def wait(self, seq=None, timeout=3.0):
        """Read the answer to the last request."""
        m = self.reply(timeout)
        if m is None:
            raise ProtocolError(f"no reply for request {seq}")
        return m

    # -- high level ----------------------------------------------------------
    def _reply_json(self, timeout=3.0, want: bytes = b"", seq=None):
        """Read until a reply carries the JSON we are looking for.

        `seq` matches on AckNumber = seq + 1 and turns a 4xx into an error; without
        it the next frames are simply scanned.  `want` names a substring the body
        must contain, because the panel answers some requests twice - a bare ack
        first, the JSON after it.
        """
        if seq is not None:
            strays = []
            m = self.awaited(seq, timeout=timeout, strays=strays)
            frames = strays + [m]
        else:
            limit, frames = time.monotonic() + timeout, []
            while time.monotonic() < limit:
                m = self.read(timeout=max(0.05, limit - time.monotonic()))
                if m is None:
                    break
                frames.append(m)
        for m in frames:
            body = m.body.strip()
            if body and (not want or want in body):
                try:
                    return m.json() or {}
                except ValueError:
                    pass
        if not frames:
            raise ProtocolError("no reply from device")
        return {}

    def device_info(self):
        """Who we are talking to: 'POST conn 1' and its JSON answer.

        The reply carries sn, OS, versions, free space and the current
        brightness/degree/mode/logo/timeout settings.
        """
        self.drain()
        seq = self.request("POST conn 1")
        return self._reply_json(want=b"attribute", seq=seq)

    def hello(self, keepalive=60):
        """conn + power resume + keepalive timeout, as ALPHA does at startup."""
        info = self.device_info()
        seq = self.post("power", {"event": "resume"})
        self.awaited(seq, timeout=2.0)
        seq = self.post("timeout", {"value": keepalive})
        self.awaited(seq, timeout=2.0)
        self.drain()
        return info

    def state_all(self, metrics, wait=False):
        """Push the system metrics blob ('STATE all 1').

        The panel answers with a bare ack; nobody reads it unless wait=True,
        because the acks pile up and slow the picture loop down.
        """
        seq = self.request("STATE all 1", metrics)
        return self.awaited(seq, timeout=2.0) if wait else None

    def send_media(self, name: str, data: bytes, gap=MEDIA_GAP,
                   chunk=MEDIA_CHUNK, timeout=12.0, wait=True,
                   order="notice"):
        """Upload one file the way the panel's media writer expects it.

        Everything goes out as one burst - `transport`, a short pause, the raw
        file in 1000-byte writes, then `transported`.  Three rules, all measured
        on the wire rather than guessed:

        * the first file byte must arrive about 20 ms after the announcement,
          never straight away.  The boundary is measured: 0.02 s took 8/8 uploads
          of one 24 550-byte vendor frame, ALPHA's own 0.011 s took a mix of
          `200`s and `400`s, and 0 s took none of 8 - every refusal a `1 400`
          landing ~508 ms after the announcement, which is how long the panel's
          media writer waits before giving up on a session it granted
          (`tools/order_probe.py`, `tools/writebench.py`).  `gap=0` also fails
          in a fresh session and at any rate, 0/31 at 1 fps against 361/361 at
          0.02 s and 3 fps, so it is not something a slower loop fixes.
        * somebody has to be reading the port the whole time, see
          `start_pump()`.  With nobody reading, the panel delivers the notice
          for a file a constant 1022 ms after the announcement no matter how the
          file was sent - baud, chunk size, gap and file size all make no
          difference - whereas ALPHA's log shows that same notice 13-26 ms after
          `transport`, 905 times out of 905.  With a byte-driven reader we
          measure ~30 ms, so this is now as fast as the vendor app, not merely
          faster than our first attempt.
        * `transported` belongs **after** the panel's notice, not immediately
          after the last file byte.  In ALPHA's log the notice lands at +22 ms
          and `transported` at +23 ms, and the panel answers it with
          {"state":"success"} at +36 ms - 905 of those acks in the capture.  Send
          it while the media writer is still busy (our old order) and no ack for
          it has ever been seen from us.  Whether that ordering changes anything
          the panel does is what `tools/order_probe.py` measures.

        The verdict is the panel's own unlabelled notice (AckNumber 0): 200 took
        the file, 4xx did not.  `transported` answers {"state":"success"} even
        after a refusal, and `conn`'s free space does not move either way, so
        neither says anything.  No notice at all is also a failure, and it is
        what a malformed request does: a `transport` frame without a
        ContentLength header is dropped without any reply to it at all - no ack
        for the request, no notice for the file - while the panel goes on to
        answer the *next* frame normally, `transported` included (6/6 `success`
        acks for 6 refused uploads, `tools/cltest.py`).  So a client that trusts
        the ack believes a file landed that the panel never opened.

        `wait=False` still waits for the verdict when `order="notice"` (about 30 ms
        with the pump running) and returns its code; with `order="fast"` it puts
        the file on the wire, returns, and the notice has to be picked up later
        with `read_notice()`.
        """
        if not self.pumping():
            self.drain(0.05)                # with a pump the frames are already in
        self.post("transport", {"type": "media", "fileSize": len(data),
                                "fileName": name})
        if gap:
            time.sleep(gap)
        self.send_raw(data, chunk=chunk)
        notice = None
        if order == "notice":
            notice = self.read_notice(name, timeout=timeout)[0]
        seq = self.post("transported", {"md5": "todo", "fileName": name})
        if not wait:
            return {"notice": notice, "seq": seq}

        ack = None
        if notice is None:
            notice, ack = self.read_notice(name, timeout=timeout, seq=seq)
        else:
            m = self.read(timeout=0.5)      # the {"state":"success"} ack
            if m is not None and m.body:
                ack = m.body.strip()
        out = {"notice": notice}
        if ack:
            try:
                out.update(json.loads(ack) or {})
            except ValueError:
                out["transported"] = ack[:60].decode("latin-1")
        if out.get("state") not in (None, "success"):
            raise ProtocolError(f"device said about {name}: {out}")
        return out

    def harvest(self, timeout=0.0):
        """Every reply that has already arrived, without waiting for one.

        Use this instead of waiting for a reply in the picture loop.  A client
        that blocks on each verdict sends its next file a second later than a
        client that does not, and on this link the panel's notice for a file
        either arrives ~100 ms after the upload or at the moment the *next*
        request arrives - never in between - so blocking is what makes a frame
        cost 1.1 s.  ALPHA never waits either: in its log the notice for a file
        lands before `transported` for that file is even written.
        """
        out, limit = [], time.monotonic() + timeout
        while True:
            m = self.read(timeout=max(0.0, limit - time.monotonic()))
            if m is None:
                return out
            out.append(m)

    def read_notice(self, name: str, timeout=12.0, seq=None):
        """Wait for the notice belonging to the file just uploaded.

        Returns (notice code, `transported` ack body).  A 4xx or plain silence
        both mean the file was not taken, and both raise.
        """
        notice, ack = None, None
        limit = time.monotonic() + timeout
        while time.monotonic() < limit:
            m = self.read(timeout=max(0.05, limit - time.monotonic()))
            if m is None:
                break
            if m.code.startswith("4"):
                raise ProtocolError(f"device refused the file: {m.code} "
                                    f"{(m.body or b'')[:60]!r}")
            if m.headers.get("AckNumber") == "0":
                notice = m.code           # unlabelled: this is the file's verdict
            elif seq is not None and m.body and \
                    m.headers.get("AckNumber") == str(seq + 1):
                ack = m.body.strip()
            if notice:
                break                       # the ack is nice; the notice decides
        if notice is None:
            raise ProtocolError(f"no file notice from device for {name}")
        return notice, ack


def _sysfs_attr(path: str) -> str:
    """One sysfs attribute, stripped, or "" if it is not there.

    Read with a `with`: these are looked up on every port scan and every session renewal, and
    `open(p).read()` leaves the handle to the garbage collector - which is what this module's own
    tests turned into a `ResourceWarning` naming `/sys/.../product`.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def usb_label(tty: str) -> str:
    """'Xigmatek USB Device [1d6b:0109]' for the USB device behind a tty node.

    The tty's sysfs dir is the USB *interface*; the product string lives one level
    up on the USB *device*, so walk up until we find it.
    """
    path = os.path.realpath(f"/sys/class/tty/{tty.split('/')[-1]}/device")
    ids = ""
    for _ in range(4):
        prod = _sysfs_attr(f"{path}/product")
        vendor, product = _sysfs_attr(f"{path}/idVendor"), _sysfs_attr(f"{path}/idProduct")
        if vendor and product:
            ids = f"{vendor}:{product}"
        if prod:
            return f"{prod} [{ids}]" if ids else prod
        if os.path.dirname(path) == path:
            break
        path = os.path.dirname(path)
    return f"[{ids}]" if ids else "?"


def find_ports(pattern="/dev/ttyACM*"):
    """Candidate CDC-ACM ports with their USB product strings."""
    return [(p, usb_label(p)) for p in sorted(glob.glob(pattern))]
