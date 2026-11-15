#!/usr/bin/env python3
"""The saved boot choice: one file, three doors, and an order that never moves.

`xigmalcd/display.py` holds what a person last asked the glass to show - which theme, which
background, how fast - so the systemd user service can start on a choice instead of on a
packaging default.  What used to decide it was the unit's `ExecStart`, which said
`--theme alpha --fps 2`: to change the picture at login you wrote a drop-in, a second place
the same decision lived, invisible to the window that made it.  The window already knows what
it sent; the loop now knows what was chosen.

The order is the whole contract, and every check here is a attempt to break it in one
direction:

    **an explicit flag beats the file, and the file beats the default**

so `xigmalcd --theme gauge` means gauge whatever the window last saved, a machine where nobody
has ever opened the window boots as it always did (alpha, `media/Theme_25.mp4`, 1 fps - the
vendor's cadence, which is what `--help` promises and what the unit used to overrule), and a
file that is wrong in one key costs that key and nothing else.

Six rules are worth their lines:

* validation with a *reason*, printed.  A saved theme this build cannot draw, a background
  spelled as a path, an fps the control socket itself would refuse, a half-written file: each
  one is named in the log with the key it came from.  Silent fallback is how a boot choice
  turns into a mystery, and the file this replaces was a mystery by construction - a flag in
  a unit nobody had read;
* a clip is stored as a **bare name** and resolved at startup through `main.media_roots()`,
  so the choice survives the copy being in the checkout, in the .deb, in `$XIGMA_MEDIA` or on
  the vendor's library - and a name that resolves to nothing this machine has is reported as
  `saved-missing` rather than quietly drawing `Theme_25.mp4` instead.  A preview may fall
  back; a device should say so;
* the file never becomes a layout.  It lives in `$XDG_CONFIG_HOME/xigmalcd/`, one directory
  above the `themes/` that `themes.scan()` globs, and a check proves the two cannot meet;
* the loop **never writes it**.  Only the window writes, at its three intent doors (`Apply
  these settings`, the clips box's send, the editor's apply-to-panel), so a scripted
  experiment against a live panel cannot decide what you see at your next login;
* one writer, three merges: a press on the clips box must not rewrite the theme, and a press
  of Apply must not rewrite a background it did not send;
* and the same `--fresh` answer as the window's own settings: a window told not to write
  writes nothing, and says which path it left alone.

Printed rather than quoted in the pages: `xigmalcd --display-choice`, which answers the whole
question - what would start, and where each part came from - on any machine.
"""
from __future__ import annotations

import json
import os
import unittest

from tests import fixtures

from xigmalcd import control, display, main, render, themes
from tests import test_display_remote as remote


def parse(*argv: str):
    """A real parsed namespace, so the sentinels under test are the shipped ones."""
    return main.build_parser().parse_args(list(argv))


class ChoiceRoot(fixtures.FreshConfigRoot):
    """Every check here runs against its own empty `$XDG_CONFIG_HOME`.

    `display.path()` asks the environment on each call (the same reason `themes.user_root()`
    matters in `FreshConfigRoot`), so planting a file is one `save()` and removing one is one
    unlink - and no check can pass by finding the developer's real choice.
    """

    def plant(self, **keys) -> str:
        where = display.path()
        os.makedirs(os.path.dirname(where), exist_ok=True)
        with open(where, "w", encoding="utf-8") as fh:
            json.dump(keys, fh)
        return where

    def raw(self) -> bytes:
        with open(display.path(), "rb") as fh:
            return fh.read()

    def resolve(self, *argv: str) -> tuple:
        notes: list = []
        args = parse(*argv)
        came = main.apply_choice(args, notes)
        return args, came, notes


class TheOrderNeverMoves(ChoiceRoot):
    def test_no_file_and_no_flags_gives_the_defaults_the_docs_quote(self):
        args, came, notes = self.resolve()
        self.assertEqual(came, {"theme": "default", "clip": "default", "fps": "default"},
                         came)
        self.assertEqual(args.theme, main.DEFAULT_THEME)
        self.assertEqual(args.fps, main.DEFAULT_FPS)
        self.assertEqual(os.path.basename(str(args.mp4)), "Theme_25.mp4", args.mp4)
        self.assertEqual(notes, [], notes)
        print(f"  no choice on disk: {main.choice_report(args, came)}")

    def test_a_saved_choice_is_used_and_named_as_saved(self):
        self.plant(theme="gauge", clip="Theme_11.mp4", fps=3.0)
        args, came, notes = self.resolve()
        self.assertEqual(came, {"theme": "saved", "clip": "saved", "fps": "saved"}, came)
        self.assertEqual((args.theme, args.fps), ("gauge", 3.0))
        self.assertTrue(str(args.mp4).endswith("Theme_11.mp4"), args.mp4)
        self.assertEqual(notes, [], notes)

    def test_every_flag_beats_the_file_it_was_written_over(self):
        self.plant(theme="gauge", clip="Theme_11.mp4", fps=3.0)
        for flag, key, want in ((("--theme", "bars"), "theme", "bars"),
                                (("--fps", "1"), "fps", 1.0),
                                (("--mp4", "media/theme_48.mp4"), "clip", None)):
            argv = list(flag)
            args, came, _notes = self.resolve(*argv)
            self.assertEqual(came[key], "flag", f"{argv}: {came}")
            if key == "theme":
                self.assertEqual(args.theme, want)
            if key == "fps":
                self.assertEqual(args.fps, want)
            if key == "clip":
                self.assertTrue(str(args.mp4).endswith("theme_48.mp4"), args.mp4)

    def test_no_mp4_is_an_explicit_off_that_a_saved_clip_cannot_overrule(self):
        self.plant(clip="Theme_11.mp4")
        args, came, notes = self.resolve("--no-mp4")
        self.assertIs(args.mp4, False)
        self.assertEqual(came["clip"], "off", came)
        self.assertEqual(notes, [], "an explicit `--no-mp4` should not be second-guessed")

    def test_a_bare_mp4_still_means_the_shipped_default(self):
        self.plant(clip="Theme_11.mp4")
        args, came, _notes = self.resolve("--mp4")
        self.assertEqual(os.path.basename(str(args.mp4)), "Theme_25.mp4", args.mp4)
        self.assertEqual(came["clip"], "flag", "a flag given without an argument is still "
                                             "a flag: the saved choice does not get to "
                                             "answer one")

    def test_a_file_may_answer_one_key_and_leave_the_others_alone(self):
        self.plant(theme="clock")
        args, came, notes = self.resolve()
        self.assertEqual(came, {"theme": "saved", "clip": "default", "fps": "default"}, came)
        self.assertEqual(notes, [], notes)


class ReasonsNotSilence(ChoiceRoot):
    """Every unusable key costs that key and buys a sentence."""

    def test_a_theme_this_build_cannot_draw_is_named_not_ignored(self):
        self.plant(theme="theme_of_the_mountains")
        args, came, notes = self.resolve()
        self.assertEqual(came["theme"], "default", came)
        self.assertEqual(args.theme, main.DEFAULT_THEME)
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("theme_of_the_mountains", notes[0])
        self.assertIn("this build can draw", notes[0], notes[0])
        print(f"  unusable saved theme: {notes[0]}")

    def test_a_saved_library_layout_is_accepted_because_the_loop_can_draw_it(self):
        pick = None
        for name in sorted(themes.names()):
            if name not in render.THEMES and themes.resolve(name) is not None:
                pick = name
                break
        if pick is None:
            self.skipTest("this machine holds no selectable library layout to save")
        self.plant(theme=pick)
        args, came, notes = self.resolve()
        self.assertEqual(args.theme, pick, notes)
        self.assertEqual(came["theme"], "saved", came)

    def test_a_clip_written_as_a_path_is_refused_and_says_what_to_store_instead(self):
        self.plant(clip="/somewhere/else/Theme_11.mp4")
        args, came, notes = self.resolve()
        self.assertEqual(came["clip"], "default", came)
        self.assertTrue(any("bare file name" in n for n in notes), notes)

    def test_a_clip_that_is_not_a_media_file_is_refused(self):
        self.plant(clip="notes.txt")
        _args, came, notes = self.resolve()
        self.assertEqual(came["clip"], "default", came)
        self.assertTrue(any("media channel" in n for n in notes), notes)
        # and the suffix rule is the socket's own rule, read once from one place
        self.assertTrue(any(n.lower().endswith("/".join(control.UPLOAD_SUFFIXES)[:-1] + ")")
                            or "mp4" in n for n in notes), notes)

    def test_an_fps_the_socket_would_refuse_is_refused_here_too(self):
        lo, hi = control.FPS_RANGE
        for bad in (99, 0.0, -1, "fast"):
            self.plant(fps=bad)
            args, came, notes = self.resolve()
            self.assertEqual(came["fps"], "default", f"fps={bad!r}: {came}")
            self.assertEqual(args.fps, main.DEFAULT_FPS, bad)
            self.assertTrue(notes, f"fps={bad!r} was dropped without a reason")
        print(f"  fps range, from the socket: {lo}-{hi}; four junk values refused with notes")

    def test_a_number_shaped_string_still_counts_as_a_rate(self):
        self.plant(fps="2.5")
        args, came, notes = self.resolve()
        self.assertEqual(args.fps, 2.5, came)
        self.assertEqual(came["fps"], "saved", came)

    def test_a_half_written_file_costs_the_file_not_the_boot(self):
        where = self.plant(theme="bars")
        with open(where, "w", encoding="utf-8") as fh:
            fh.write('{"theme": "bar')                    # truncated, as a crash leaves it
        args, came, notes = self.resolve()
        self.assertEqual(came["theme"], "default", came)
        self.assertTrue(any("could not be read" in n for n in notes), notes)
        print(f"  truncated file: {notes[0]}")

    def test_a_json_array_is_reported_as_the_wrong_shape(self):
        where = display.path()
        os.makedirs(os.path.dirname(where), exist_ok=True)
        with open(where, "w", encoding="utf-8") as fh:
            fh.write('["alpha"]')
        _args, came, notes = self.resolve()
        self.assertEqual(came["theme"], "default", came)
        self.assertTrue(any("not an object" in n for n in notes), notes)


class ASavedClipThatIsNotThere(ChoiceRoot):
    def test_the_name_wins_the_decision_and_still_declines_the_upload(self):
        self.plant(clip="a_clip_this_machine_does_not_have.mp4")
        args, came, notes = self.resolve()
        self.assertIs(args.mp4, False, "a missing saved clip must not become someone else's "
                                      "background")
        self.assertEqual(came["clip"], "saved-missing", came)
        self.assertTrue(any("a_clip_this_machine_does_not_have.mp4" in n for n in notes),
                        notes)
        self.assertTrue(any("keeps what it already" in n for n in notes), notes)
        print(f"  saved clip, absent here: {notes[0][:120]}")

    def test_the_same_name_resolves_when_a_root_holds_it(self):
        # the roots are the machine's, so this asks for a clip that must exist anywhere in
        # the order: the vendor library's own `theme_52.mp4` is drawn under `bars` today
        self.plant(clip="theme_52.mp4")
        found = main.find_media("theme_52.mp4")
        if not os.path.isfile(found):
            self.skipTest(f"no theme_52.mp4 in this machine's roots: {found}")
        args, came, notes = self.resolve()
        self.assertEqual(args.mp4, found, came)
        self.assertEqual(came["clip"], "saved", came)


class WhatTheChoiceThenChanges(ChoiceRoot):
    """A saved choice is not only an upload decision - it moves the plate rule too.

    The scrim rule reads the clip's **measured** luma (`main.CLIP_LUMA`, produced by
    `tools/clip_luma.py`), so a boot choice that names a near-white background has to be the
    one the plate decision sees, or the picture drawn at login is judged against a clip that
    is not the one on the glass.  Both directions are checked: the vendor's near-white
    `theme_48.mp4` (227.3 of 255) earns the plate, and `birdseye`'s cut backdrop
    `theme_47-trimmed.mp4` (6.5 whole-file) does not.
    """

    def saved_then_scrim(self, clip: str) -> int:
        self.plant(clip=clip)
        args, came, _notes = self.resolve()
        if came["clip"] != "saved":
            self.skipTest(f"{clip} does not resolve in this machine's roots")
        self.assertNotEqual(args.scrim, 0)
        return main._scrim_for(args)

    def test_a_bright_saved_clip_asks_for_the_plate_without_being_told_to(self):
        plate = self.saved_then_scrim("theme_48.mp4")
        self.assertEqual(plate, main.SCRIM_ON_BRIGHT,
                         f"a clip measured at {main.CLIP_LUMA['theme_48.mp4']} of 255 should "
                         f"not draw white on white; the rule answered {plate}")

    def test_a_dark_saved_clip_leaves_the_picture_as_the_vendor_draws_it(self):
        self.assertEqual(self.saved_then_scrim("theme_47-trimmed.mp4"), 0)

    def test_the_choice_door_opens_no_port_and_writes_nothing(self):
        """`--display-choice` is a reader, on a bench where a real panel is attached.

        The stub is not a quiet fake: constructing it raises, so if the door ever grows a
        port open - a handshake, a `STATE` blob, one frame - the check fails instead of
        politely printing a resolution next to a changed panel.
        """
        from unittest import mock

        class NoPort:
            def __init__(self, *a, **kw):
                raise AssertionError("--display-choice reached for the serial port")

        self.plant(theme="gauge", fps=2.0, clip="Theme_11.mp4")
        before = self.raw()
        with mock.patch.object(main, "Link", NoPort):
            rc = main.main(["--display-choice"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.raw(), before, "the door rewrote the file it was asked to read")


class ItIsNotALayout(ChoiceRoot):
    """One directory matters: `themes/` is globbed for layouts, its parent is not."""

    def test_a_planted_choice_file_never_becomes_a_selectable_theme(self):
        self.plant(theme="bars", clip="Theme_11.mp4", fps=2.0)
        names = set(themes.names())
        for stem in ("display", "display.json"):
            self.assertNotIn(stem, names, f"{stem} is selectable as a layout")
        ok, refused = themes.scan()
        for rec in ok + refused:
            self.assertNotIn(display.path(), str(rec.get("path", "")),
                             f"the scan picked up the choice file: {rec}")
        self.assertIn("bars", names, "the drawn set stopped being selectable mid-check")
        print(f"  library scan over a planted choice file: {len(ok)} pickable, "
              f"{len(refused)} refused, neither one is the choice file")

    def test_the_user_layout_directory_is_still_a_separate_thing(self):
        self.plant(theme="clock")
        self.assertTrue(os.path.dirname(display.path()) != os.path.abspath(themes.user_root()),
                        "the choice file would sit where layouts are written")


class TheLoopReadsButNeverWrites(ChoiceRoot):
    """A writer list that includes the daemon would let an experiment set your boot picture."""

    def test_no_module_under_xigmalcd_calls_the_writer(self):
        hits = []
        for name in sorted(os.listdir(os.path.join(fixtures.REPO, "xigmalcd"))):
            if not name.endswith(".py"):
                continue
            path = os.path.join(fixtures.REPO, "xigmalcd", name)
            src = open(path, encoding="utf-8").read()
            if "display.save" in src:
                hits.append(name)
        self.assertEqual(hits, [],
                         f"{hits} call `display.save`: the loop must read this file only, or "
                         "a scripted run against a live panel decides what a person sees at "
                         "login")
        window = open(os.path.join(fixtures.REPO, "xigmaui", "app.py"),
                      encoding="utf-8").read()
        self.assertIn("display.save", window,
                      "the window stopped being the only writer, and nothing else writes it")

    def test_running_the_loop_leaves_the_file_it_read_byte_identical(self):
        from unittest import mock
        from xigmalcd import protocol, sensors

        self.plant(theme="bars", fps=2.0, clip="Theme_11.mp4")
        before = self.raw()
        real_link, real_ser = main.Link, getattr(main, "Serial", None)

        class SilentLink:
            def __init__(self, *a, **kw):
                pass

            def hello(self, keepalive=60):
                return {"sn": "STUB", "version": {"app": "V1.0.2"}, "space": 60000}

            def harvest(self, timeout=0.0):
                return []

            def post(self, verb, obj=None):
                return 1

            def state_all(self, metrics, wait=False):
                return None

            def send_media(self, name, data, **kw):
                return {"notice": "200"}

            def drain(self, timeout=0.15):
                pass

            def close(self):
                pass

        out_dir = os.path.join(self.config_root, "frames")
        with mock.patch.object(main, "Link", SilentLink):
            rc = main.main(["--dry-run", out_dir, "--once", "--no-mp4"])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isdir(out_dir), "the dry run drew nothing")
        self.assertEqual(self.raw(), before,
                         "the loop modified the choice file it was asked to read")
        del protocol, sensors       # imports kept only for parity with the real loop path
        print(f"  a dry-run session against a planted file: bytes unchanged "
              f"({len(before)} B)")


class TheWindowDoorsWrite(remote.DisplayHarness):
    """Every press that reaches the glass, and only the part of the choice it decided.

    Reuses the harness from `tests/test_display_remote.py` rather than rebuilding it: a real
    `control.Control` and `control.Server` standing in for a running display, a port name
    nothing is behind, and the window pointed at that socket.  The harness builds its window
    with `restore=False` - a `--fresh` window - which is the wrong setting for the saving
    checks and the right one for the last of them, so each saving check flips `autosave` on
    and says why.
    """

    def setUp(self):
        super().setUp()
        for name in ("Theme_11.mp4", "Theme_25.mp4"):
            if not os.path.isfile(os.path.join(fixtures.REPO, "media", name)):
                self.skipTest(f"no {name} in this checkout to choose")

    def test_opening_the_window_saves_nothing_until_a_press(self):
        """Construction is not a decision.

        The harness builds a window, pumps the event loop, and connects it to a stub display.
        If anything wrote the boot choice on that path, then every start of the window - or
        every check in this file - would be rewriting what the owner's panel shows at login,
        and the file would stop being a record of choices.
        """
        self.assertFalse(display.present(),
                         f"opening the window wrote {display.path()}: {self.read()}")

    def read(self) -> dict:
        try:
            with open(display.path(), encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {}

    def save_on(self) -> None:
        """This window is allowed to remember - the default harness one is not."""
        self.win.autosave = True
        self.win._said_no_choice = False

    def media(self, name: str) -> str:
        return os.path.join(fixtures.REPO, "media", name)

    def test_apply_saves_theme_and_rate_and_not_the_background_it_did_not_send(self):
        self.save_on()
        self.win.chk_keep.setChecked(True)              # the reader's veto, honoured
        self.win.theme.setCurrentText("gauge")
        self.win.d_fps.setValue(2.5)
        self.win.mp4 = self.media("Theme_11.mp4")
        self.win._apply_to_display()
        got = self.read()
        self.assertEqual((got.get("theme"), got.get("fps")), ("gauge", 2.5), got)
        self.assertNotIn("clip", got,
                         "the keep box stopped the upload, so the saved background must not "
                         "have moved either")
        self.assertEqual(got.get("set_by"), "xigmaui", got)
        self.assertTrue(got.get("set_at"), got)

    def test_the_clips_door_saves_the_background_and_leaves_the_picture_it_was_not_about(self):
        self.save_on()
        self.win.mp4 = self.media("Theme_11.mp4")
        self.win.btn_upload.click()
        fixtures.pump(0.2)
        got = self.read()
        self.assertEqual(got.get("clip"), "Theme_11.mp4", got)
        self.assertNotIn("theme", got,
                         "a press on the clips box rewrote a picture choice it never touched")

    def test_apply_that_does_send_the_background_saves_it_too(self):
        self.save_on()
        self.win.chk_keep.setChecked(False)
        self.win._stored_bg = ""                        # nothing seen yet: it must send
        # the theme first, then the clip: choosing a theme in the picker follows that theme's
        # own pairing and re-points the preview layer, so a clip set before it is a clip that
        # never existed by the time Apply reads it
        self.win.theme.setCurrentText("clock")
        self.win.mp4 = self.media("Theme_11.mp4")
        self.win._apply_to_display()
        fixtures.pump(0.2)
        got = self.read()
        self.assertEqual((got.get("theme"), got.get("clip")), ("clock", "Theme_11.mp4"), got)

    def test_two_presses_merge_rather_than_clobber(self):
        self.save_on()
        self.win.theme.setCurrentText("dual")
        self.win.d_fps.setValue(2.0)
        self.win._apply_to_display()
        self.win.mp4 = self.media("Theme_11.mp4")
        self.win.btn_upload.click()
        fixtures.pump(0.2)
        got = self.read()
        self.assertEqual((got.get("theme"), got.get("fps"), got.get("clip")),
                         ("dual", 2.0, "Theme_11.mp4"), got)

    def test_the_editors_door_saves_the_name_the_display_answered_with(self):
        """The narrow door - one command, a layout name - still changes the boot picture.

        Driven the way `tests/test_apply_layout.py` drives it: pick the name in the editor's
        box, let the window build the editor, then press `apply to the panel`.  Reproducing
        the send here would prove only that I can call `_save_choice`, which is the shape of
        vacuous check this project keeps having to refuse.
        """
        self.save_on()
        ok, _refused = themes.scan()
        pick = next((str(rec["name"]) for rec in ok if str(rec["name"]) not in render.THEMES),
                    None)
        if pick is None:
            self.skipTest("this machine holds no library layout that is not drawn from code")
        self.win.ed_name.setCurrentText(pick)
        fixtures.pump(0.4)
        self.assertIsNotNone(self.win.ed, f"opening {pick} left no editor")
        self.win.ed_apply_panel.click()
        fixtures.pump(0.3)
        got = self.read()
        self.assertEqual(got.get("theme"), self.args.theme,
                         f"the saved theme is not the name the display says it is drawing "
                         f"(display answers {self.args.theme!r}, file holds {got!r})")
        self.assertNotIn("clip", got, "a layout press changes the picture, not the layer")
        self.assertNotIn("fps", got, "the editor's door is one command; the rate stayed put")
        print(f"  editor door: {pick} -> saved theme {got.get('theme')!r}")

    def test_a_tray_pick_that_reached_the_glass_is_a_boot_choice(self):
        self.save_on()
        self.win._tray_theme("bars")
        self.assertEqual(self.read().get("theme"), "bars", self.read())

    def test_a_tray_pick_with_no_display_running_saves_nothing(self):
        self.save_on()
        self.win.daemon.present = False
        self.win._tray_theme("gauge")
        self.assertEqual(self.read(), {},
                         "a preview-only pick became a boot choice: the glass never showed it")
        self.assertIn("no display is running", self.logs(), self.logs()[-400:])

    def test_a_fresh_window_writes_no_choice_file_and_names_the_path(self):
        # the harness window starts with autosave off: this is the `--fresh` answer
        self.win.chk_keep.setChecked(False)
        self.win.mp4 = self.media("Theme_11.mp4")
        self.win._apply_to_display()
        fixtures.pump(0.2)
        self.assertFalse(os.path.exists(display.path()),
                         "a window told not to save wrote the boot choice anyway")
        self.assertIn(display.path(), self.logs(), self.logs()[-400:])

    def test_the_file_is_written_for_this_user_only(self):
        self.save_on()
        self.win.theme.setCurrentText("gauge")
        self.win._apply_to_display()
        mode = os.stat(display.path()).st_mode & 0o777
        self.assertEqual(mode, 0o600, oct(mode))
        dmode = os.stat(os.path.dirname(display.path())).st_mode & 0o777
        self.assertEqual(dmode, 0o700, oct(dmode))
        print(f"  wrote {display.path()}: file {oct(mode)}, parent directory {oct(dmode)}")




if __name__ == "__main__":
    unittest.main(verbosity=2)
