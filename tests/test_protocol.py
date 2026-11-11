#!/usr/bin/env python3
"""The wire: encode, decode, re-encode, and what a broken reply still tells us.

Ported from `tools/selftest.sh`'s "decoder round-trip" and "protocol round-trip against the
Windows captures" sections.  Nothing in this file opens a port: every frame is a byte string
handled in memory, and the fake serial numbers in it are invented, which is how a privacy check
coexists with a wire check.

The captures half stays a tool.  `tools/verify_protocol.py` re-encodes every captured host->panel
frame from the two Windows serial-monitor sessions and compares it with the bytes on the wire, and
it prints how many frames it matched.  `data/captures/` is gitignored, because those files carry
this panel's own serial number, so a clone has nothing to re-encode and this test says so out loud
instead of reporting a pass.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import unittest

from tests import fixtures

from xigmalcd import protocol as p

CASES = [("POST conn 1", b""),
         ("POST power 1", {"event": "resume"}),
         ("STATE all 1", {"fans": [{"onBoard": True, "name": "Fan CPU", "value": 1476}],
                          "cpu": {"temperature": 57, "voltage": 1.365}}),
         ("POST transport 1", {"type": "media", "fileSize": 12034,
                               "fileName": "2026-11-05_07-21-36-052.osd"})]


class RoundTrip(unittest.TestCase):
    """encode -> decode -> re-encode gives back the same bytes, headers included."""

    def test_every_frame_kind_comes_back_the_same_bytes(self):
        for line, obj in CASES:
            with self.subTest(line=line):
                fr = p.encode(line, {"SeqNumber": 1, "Date": 1}, obj)
                m = p.decode(fr)
                self.assertEqual(m.line, line)
                again = p.encode(m.line,
                                 {k: v for k, v in m.headers.items() if k != "CkOK"},
                                 m.json() if m.body else b"")
                self.assertEqual(again, fr)
                self.assertTrue(p.checksum_ok(fr), line)

    def test_the_length_field_and_the_checksum_agree(self):
        """`checksum_ok` is strict: it checks framing, the declared length and the byte."""
        for line, obj in CASES:
            with self.subTest(line=line):
                fr = p.encode(line, {"SeqNumber": 1}, obj)
                self.assertTrue(p.checksum_ok(fr))
                lied = bytearray(fr)
                lied[2] ^= 0x01          # the high byte of the declared length
                self.assertFalse(p.checksum_ok(bytes(lied)),
                                 "a frame whose length field lies should not pass the "
                                 "strict check, and `frame_ok` is what tells the two apart")


class Escaping(unittest.TestCase):
    """0x5A would end the frame and 0x5B starts an escape, so both get quoted."""

    BODIES = (b'{"sn":"FAKE-SN-WITH-Z-0001"}',
              b'{"attribute":["Status","Fan","Pump"]}')

    def test_quoting_is_exactly_reversible(self):
        for body in self.BODIES:
            with self.subTest(body=body[:24]):
                self.assertEqual(p.unescape(p.escape(body)), body)
                fr = p.encode("1 200", {"SeqNumber": 1}, body)
                self.assertEqual(p.decode(fr).body, body)
                self.assertTrue(p.checksum_ok(fr))
                self.assertEqual(p.read_frame(fr)[1], len(fr))

    def test_the_splitter_unescapes_as_it_walks(self):
        """An escaped frame is longer on the wire than it declares; the frame still ends right."""
        body = {"attribute": ["Status", "Fan", "Pump"], "sn": "FAKE-SN-WITH-Z-0001"}
        fr = p.encode("1 200", {"AckNumber": 1, "ContentType": "json"}, body)
        declared = p.inner(fr)[0] << 8 | p.inner(fr)[1]
        self.assertGreater(len(fr), declared, "this frame is expected to be escaped")
        self.assertEqual(p.read_frame(b"junk" + fr + b"tail", 4), (fr, 4 + len(fr)))

    def test_an_unterminated_frame_is_refused_not_guessed(self):
        fr = p.encode("1 200", {"AckNumber": 1}, {"a": [1]})
        self.assertIsNone(p.read_frame(fr[:-1] + b"X"))


class DeviceReplies(unittest.TestCase):
    """A reply with a bad checksum is still parsed on structure, with the mismatch reported."""

    def test_structure_is_accepted_and_the_cksum_problem_said(self):
        bad = bytearray(p.encode("1 200", {"AckNumber": 1, "ContentType": "json",
                                          "ContentLength": 6}, {"a": [1]}))
        bad[-2] ^= 0xFF
        self.assertTrue(p.frame_ok(bytes(bad)), "structure should still be accepted")
        self.assertFalse(p.checksum_ok(bytes(bad)), "and the bad cksum should be reported")
        self.assertEqual(p.decode(bytes(bad)).json(), {"a": [1]})


class Captures(unittest.TestCase):
    """The Windows sessions, re-encoded by the tool that exists for them."""

    def test_the_tool_matches_every_captured_frame(self):
        caps = sorted(glob.glob(os.path.join(fixtures.REPO, "data", "captures", "*.txt")))
        if not caps:
            self.skipTest("no capture under data/captures/ (gitignored: they carry this panel's "
                          "serial), so nothing was re-encoded here. The tool prints its own "
                          "figures where a capture exists: "
                          "python3 tools/verify_protocol.py data/captures/*.txt")
        got = subprocess.run([sys.executable, os.path.join(fixtures.REPO, "tools",
                                                           "verify_protocol.py")] + caps,
                             capture_output=True, text=True, cwd=fixtures.REPO)
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
