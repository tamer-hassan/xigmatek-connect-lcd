#!/usr/bin/env python3
"""The copied vendor library: which layouts this canvas can select, and what goes under each.

Ported from the library-selection and pairing halves of `tools/selftest.sh`'s vendor-theme section.
The manifest byte checks moved out to `tools/verify_manifest.py`; what stays here is behaviour.

Two rules are worth their lines:

* the canvas decision comes from the file's **ratio field**, not from its path or its name - the
  four 320x240 layouts are refused on that field and still answer with the reason in words;
* `themes.pair` is the one place that reads `background.mediaFile` as an answer, so the window and
  `--list-themes` cannot disagree with each other or with the file.  One clip per layout, no two
  layouts sharing a clip, and a refusal - not an empty string - for names the library has no file
  for, which is what the window prints.

The five themes drawn from `render.py` carry no such key, because a generated layout *is* the
picture and has nothing under it.  Their backdrops are therefore derived here, from the published
pictures' own names, rather than trusted from the constant that encodes them.
"""
from __future__ import annotations

import glob
import os
import unittest

from tests import fixtures

from xigmalcd import layout
from xigmalcd import render
from xigmalcd import main as _main
from xigmalcd import themes

#: What the 27 copied layouts divide into on this canvas.  File facts: the same 27 files are in
#: the package, so these counts are not a machine's state.
PICKABLE, REFUSED = 23, 4

#: The library's `source` names, counted by the same code the window uses and pinned so a
#: changed library or a changed reader is a diff someone notices.  Since 2026-11-13 every one
#: of them has a rule (`Pump Speed` is answered by `themes.FAN_TYPED` from a fan row's type),
#: so the vocabulary has no hole - what is left is a per-body question, and that pair is
#: asserted in the check below: nine layouts are short one reading on a body that reports no
#: pump row, and none is short anything on a body that does.
SOURCES_USED = {"CPU Temperature": 17, "CPU Usage": 15, "Time": 11, "Pump Speed": 9,
                "GPU Usage": 6, "GPU Temperature": 3, "CPU Frequency": 2}
RULELESS_HOLES: set = set()
NEEDS_A_PUMP_ROW, ONLY_GAP = 9, ["Pump Speed"]


class TheDrawnSetCountsItself(unittest.TestCase):
    """Every door that *states* how many themes this program draws states it correctly.

    Adding `birdseye` on 2026-11-14 made three shipped sentences wrong at once, and none of
    them was a comment a reader never sees: the control socket's refusal printed six names
    under the words "the five drawn here", and `--theme`'s help listed
    `alpha, bars, clock, dual, gauge` and called that list "the five".  A theme joins the
    set by going into `render.THEMES` and nothing forces either sentence to move, so the fix
    is not to re-write the numbers - it is to make the strings read the registry, and then to
    refuse the next drift.

    Nothing here hard-codes six.  The count and the names come from `render.THEMES`, and the
    messages are asked of the shipped doors, so a seventh theme keeps this check green by
    itself while a theme added without deriving the words goes red.
    """

    def test_the_control_sockets_refusal_names_the_registry_it_just_read(self):
        from xigmalcd import control, main
        args = main.build_parser().parse_args(["--once"])
        ctl = control.Control(args, "")          # no server thread, no socket, no panel
        refused = ctl._set_theme("definitely-not-a-theme")
        self.assertFalse(refused["ok"])
        said = str(refused["error"])
        n = len(render.THEMES)
        print(f"  refusal for an unknown name, {n} drawn themes: {said}")
        self.assertIn(f"the {n} drawn here", said,
                      f"the socket's refusal does not count its own registry ({n}): {said}")
        for name in sorted(render.THEMES):
            self.assertIn(name, said,
                          f"`{name}` is drawn but the refusal does not name it: {said}")

    def test_the_command_lines_help_counts_and_lists_the_set(self):
        from xigmalcd import main
        n = len(render.THEMES)
        opts = {a.dest: a for a in main.build_parser()._actions}
        phrases = {"theme": f"{n} this program draws",
                   "export_theme": f"of the {n} themes this",
                   "list_themes": f"the {n} drawn"}
        for dest, phrase in phrases.items():
            help_ = str(opts[dest].help or "")
            print(f"  --{dest.replace('_', '-')}: {help_[:120]}")
            self.assertIn(phrase, help_,
                          f"`--{dest.replace('_', '-')}`'s help does not state {n} drawn "
                          f"themes (looked for {phrase!r} in {help_[:160]})")
        listed = str(opts["theme"].help)
        for name in sorted(render.THEMES):
            self.assertIn(name, listed,
                          f"`--theme`'s help does not name `{name}`: {listed[:160]}")

    def test_the_two_prose_doors_count_their_own_registry(self):
        """`themes.why_not` and the writer's reserved-name refusal, asked of the doors.

        Both sentences used to carry the number five in their literal text.  Today they are
        f-strings over `render.THEMES`, so the claim is the registry's rather than a writer's
        memory - and a seventh theme is the test: nothing here may say "five" or "six".
        """
        n = len(render.THEMES)
        reason = themes.why_not("gauge")
        print(f"  why_not('gauge'): {reason}")
        self.assertIn(f"one of the {n} this program draws itself", reason, reason)
        try:
            themes._safe_name("bars")
        except ValueError as exc:
            said = str(exc)
            print(f"  saving over a drawn name: {said[:120]}")
            self.assertIn(f"one of the {n} themes drawn from render.py", said, said)
        else:
            self.fail("_safe_name accepted a drawn theme name: the reserved-name rule is off")
        for claim in (" the five ", " the six ", " five themes", " six themes"):
            self.assertNotIn(claim, reason.lower(), f"{claim!r} hardcoded in {reason}")

    def test_no_shipped_line_states_the_drawn_sets_size_without_saying_so(self):
        """A count of the drawn set, written into a comment, is a claim about a registry.

        Scans the shipped modules for a number-word standing next to the language of the
        drawn set (`drawn`, `generated`, `render.py`, `this program draws`, `theme combo`,
        `code-drawn`) and refuses it unless the same line either reads the number off the
        registry or carries the marker `count-claim-history`, which is how a sentence about
        what an older build said stays in the file honestly.  This is not pedantry about
        prose: `birdseye` arrived on 2026-11-14 and left eleven such sentences behind across
        `xigmaui/app.py`, `xigmaui/edit.py`, `xigmalcd/themes.py`, `xigmalcd/layout.py`,
        `xigmalcd/control.py` and `tools/display_glass.py`, two of them inside strings a user
        reads, one of them promising that a saved `Theme_07` was refused because of "the five
        names" when six had been drawn for a week.
        """
        import re
        # The number-words that could be *this set's* size, and only next to language about
        # the drawn themes themselves.  Kept narrow on purpose: "four" also counts fan slots,
        # "five" counts the parity cases and the text-composite specials, and a rule that
        # flags those would be answered by a pile of exemptions rather than by a better rule.
        number = re.compile(r"\b(three|four|five|six|seven)\b")
        about = re.compile(r"(themes drawn|drawn themes|generated themes|theme names|"
                           r"drawn-from-code|names generated|code-drawn|theme combo|"
                           r"this program draws|themes this repo|list of)", re.I)
        marker = "count-claim-history"
        offenders = []
        scanned = 0
        for path in ("xigmalcd/themes.py", "xigmalcd/control.py", "xigmalcd/main.py",
                     "xigmalcd/render.py", "xigmalcd/layout.py", "xigmaui/app.py",
                     "xigmaui/edit.py", "tools/display_glass.py"):
            text = fixtures.read(path)
            scanned += len(text.split("\n"))
            for lineno, line in enumerate(text.split("\n"), 1):
                if not number.search(line) or not about.search(line):
                    continue
                if marker in line:
                    continue
                # a line that *derives* the count is stating the registry, not remembering it
                if "len(render.THEMES)" in line or "len(themes.EXPORTS)" in line \
                        or "len(EXPORTS)" in line:
                    continue
                offenders.append((path, lineno, line.strip()[:88]))
        print(f"  scanned {scanned} lines of shipped code for a number-word standing "
              f"next to the drawn set: {len(offenders)} unmarked claims")
        self.assertEqual(offenders, [],
                         f"{len(offenders)} lines state the drawn set's size from memory: "
                         + "; ".join(f"{p}:{n} {t!r}" for p, n, t in offenders[:6]))

    def test_the_list_door_prints_the_header_it_draws(self):
        """`--list-themes`'s own header line, read from the door rather than quoted."""
        import contextlib
        import io as _io
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = _main.main(["--list-themes"])   # returns 0 before any port is opened
        self.assertEqual(code, 0, "the listing door did not exit cleanly")
        text = buf.getvalue()
        n = len(render.THEMES)
        header = [ln for ln in text.splitlines() if "drawn here" in ln]
        self.assertEqual(len(header), 1, text[:200])
        names = header[0].split(":", 1)[1].split()
        print(f"  --list-themes header names {len(names)}: {header[0]}")
        self.assertEqual(sorted(names), sorted(render.THEMES), header[0])
        self.assertGreaterEqual(n, 1, "no drawn themes at all?")


class Selection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pick, cls.reject = themes.scan()

    def test_the_split_is_by_the_ratio_field_not_by_the_name(self):
        self.assertEqual((len(self.pick), len(self.reject)), (PICKABLE, REFUSED))
        self.assertTrue(all(r["ratio"] == "1:1" for r in self.pick),
                        [r["ratio"] for r in self.pick])
        self.assertTrue(all(r["ratio"] != "1:1" for r in self.reject),
                        [r["ratio"] for r in self.reject])
        self.assertEqual({(r["w"], r["h"]) for r in self.reject}, {(320, 240)})

    def test_the_names_are_unique_whatever_case_they_arrive_in(self):
        self.assertEqual(len({r["name"].lower() for r in self.pick + self.reject}), 27,
                         "a name collides case-insensitively")
        self.assertEqual(len({r["id"] for r in self.pick}), PICKABLE,
                         "two pickable layouts share an id")

    def test_resolution_accepts_the_stem_any_case_and_the_numeric_id(self):
        self.assertEqual(themes.resolve("theme_07")["name"], "Theme_07")
        self.assertEqual(themes.resolve("1757491588804")["name"], "Theme_07")

    def test_what_cannot_be_drawn_answers_with_a_reason(self):
        self.assertIsNone(themes.resolve(self.reject[0]["name"]))
        self.assertIn("ratio 4:3", themes.why_not(self.reject[0]["name"]))
        self.assertIsNone(themes.resolve("gauge"))
        # and the count in that reason comes from the registry, not from this file: the
        # assertion used to read `assertIn("five", ...)`, which is a check that pins a
        # number to a set that is allowed to grow - exactly what
        # `test_no_shipped_line_states_the_drawn_sets_size_without_saying_so` below now
        # refuses, and the reason that check was written.
        n = len(render.THEMES)
        self.assertIn(f"one of the {n} this program draws itself", themes.why_not("gauge"),
                      "a drawn theme is not a file, and the reason should say which set it "
                      "belongs to, counted off that set")

    def test_the_sources_the_library_asks_for_are_the_ones_this_program_has(self):
        """Two different questions, and 2026-11-13 pulled them apart.

        *Does a name have a rule at all?*  Since `Pump Speed` moved out of `UNMAPPED` (a
        hard-coded sentence that no reading could clear) into `themes.FAN_TYPED` (a rule over a
        fan row's own `type`), the answer is yes for every name the library asks - so this half
        is now a check that the vocabulary has no hole, and that it did not grow one by
        accident.

        *Can a given body answer it?*  Still a nine-file question on a body with no pump row,
        and a zero-file question on one that has a row typed `Pump` - and that pair is asserted
        through `themes.values()`, the door the frame loop itself uses.
        """
        used = themes.sources_used(self.pick)
        self.assertEqual(used, SOURCES_USED)
        answerable = set(themes.source_names())
        holes = {src for src in used if src not in answerable}
        self.assertEqual(holes, RULELESS_HOLES,
                         f"a source the shipped library asks for has no rule: {holes}")

        def gapped(body) -> list:
            absent = set(themes.values(body, fixtures.SESSION_WHEN)[1])
            out = []
            for rec in self.pick:
                src = {p.get("source") for w in (themes.load(rec["path"]).get("osd") or {})
                       .get("widget") or [] for p in w.get("property") or [] if p.get("source")}
                if src & absent:
                    out.append((rec["name"], sorted(src & absent)))
            return out

        without = gapped(fixtures.SESSION)
        self.assertEqual(len(without), NEEDS_A_PUMP_ROW, without)
        for name, gap in without:
            self.assertEqual(gap, ONLY_GAP, f"{name} is short {gap} on a pumpless body")
        pumped = gapped(dict(fixtures.SESSION,
                             fans=[{"onBoard": True, "type": "Pump", "name": "CPU PUMP",
                                    "value": 2453}]))
        self.assertEqual(pumped, [],
                         "a body that reports a pump row still leaves a library layout short")


class Pairing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pick, cls.reject = themes.scan()

    def test_every_selectable_layout_names_exactly_one_clip_and_no_two_name_the_same(self):
        named: dict = {}
        for rec in self.pick:
            background = str(rec["background"] or "")
            self.assertTrue(background, (rec["name"], "a selectable layout declares no background"))
            named.setdefault(background.rsplit("/", 1)[-1].lower(), []).append(rec["name"])
        shared = {k: v for k, v in named.items() if len(v) > 1}
        self.assertEqual(shared, {}, "two selectable layouts name the same clip, so the "
                                     "pairing stops being a function")
        self.assertEqual(len(named), PICKABLE)

    def test_pair_answers_for_each_by_name(self):
        for rec in self.pick:
            with self.subTest(layout=rec["name"]):
                got, why = themes.pair(rec["name"])
                self.assertEqual(got, rec["background"].rsplit("/", 1)[-1])
                self.assertFalse(why, why)

    def test_a_canvas_refused_layout_can_answer_a_clip_for_the_window_to_open(self):
        """The window must not be able to show what `--theme` will not draw."""
        for rec in self.reject:
            with self.subTest(layout=rec["name"]):
                self.assertFalse(themes.pair(rec["name"])[0])

    def test_a_name_the_library_has_no_file_for_answers_with_a_reason(self):
        clip, why = themes.pair("no-such-layout")
        self.assertFalse(clip)
        self.assertTrue(why, "an empty answer is what a window would have to print as nothing")

    def test_the_five_generated_themes_pair_with_their_own_published_pictures_backdrop(self):
        """`CODE_CLIPS` is a claim about five themes that have no `background.mediaFile`, so it is
        re-derived from the README's own pictures: each is named `<theme>-<clip>.mp4`, and a
        candidate counts only when its clip part resolves as a clip this box holds.  That is how the
        amber-ink figure `alpha-Theme_25-amber.mp4` falls out on its own rather than being excepted
        by hand - `find_media` answers with a path whether or not the file exists, which is how a
        missing clip gets reported as the name it was asked for, so the test is the file."""
        from xigmalcd.main import find_media
        published: dict = {}
        for video in sorted(glob.glob(os.path.join(fixtures.REPO, "docs", "videos", "*.mp4"))):
            stem = os.path.basename(video)[:-4]
            theme, sep, clip = stem.partition("-")
            if not sep or theme not in render.THEMES:
                continue
            if not os.path.isfile(find_media(clip + ".mp4")):
                continue
            published.setdefault(theme, []).append(clip + ".mp4")
        self.assertEqual({k: len(v) for k, v in published.items()},
                         {k: 1 for k in published}, published)
        self.assertEqual(set(published), set(render.THEMES),
                         "a theme drawn here has no published picture naming a backdrop, so "
                         "its pairing would have to be invented")
        self.assertEqual({k: v[0] for k, v in published.items()}, themes.CODE_CLIPS,
                         "themes.CODE_CLIPS is not the backdrop set the README's own pictures "
                         "are composited over")

    def test_pair_answers_for_the_five_generated_names_too(self):
        for name in sorted(themes.EXPORTS):
            with self.subTest(theme=name):
                got, why = themes.pair(name)
                self.assertEqual(got, themes.CODE_CLIPS.get(name))
                self.assertFalse(why, why)


class Shape(unittest.TestCase):
    """The library as the package installs it: 27 layouts, and one row per kind of file."""

    def test_every_pickable_layout_loads_and_has_the_envelope_a_layout_needs(self):
        pick, _reject = themes.scan()
        for rec in pick:
            with self.subTest(layout=rec["name"]):
                body = themes.load(rec["path"])
                self.assertIn("osd", body)
                self.assertTrue(body["osd"].get("widget"), rec["name"])
                # the same keys `layout.draw_theme` reads, from that module rather than a list
                self.assertTrue(hasattr(layout, "draw_theme"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
