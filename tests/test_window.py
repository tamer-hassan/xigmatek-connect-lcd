#!/usr/bin/env python3
"""The window, offscreen and with no panel attached.

Ported from the opening blocks of `tools/selftest.sh`'s GUI section - the part that asks what happens
when a person runs this program on a machine with nothing plugged in, and the part that asks what the
window is allowed to write down.

The second question is the load-bearing one.  An offline check or a throwaway script builds a
`Window` with a device path that does not exist and a rate nobody asked for; the save timer fires 500
ms later exactly as it does for a person; and unless `save_settings` says otherwise the author's real
`~/.config/xigmaui/config.json` ends up holding `/dev/xigma-no-such-port` and a clip nobody chose.
That happened in 0.4, which is why `restore=False` defaults to not writing, why this file asserts the
rule rather than relying on it, and why every test here sits on its own temporary `XDG_CONFIG_HOME`.

Pixel-level claims about the pane's contents live in `test_ink.py`, `test_gauges.py` and
`test_export_parity.py`.  Machine-dependent measurements - build time, thumbnail pass, one frame's
render cost, column widths and row capacities - are not here: those figures belong to the machine
that prints them, and the page names the command instead of carrying the number.
"""
from __future__ import annotations

import os
import unittest

from tests import fixtures

from xigmalcd import render
from xigmaui import app, settings

MISSING_PORT = "/dev/xigma-no-such-port"

#: The nine controls behind the advanced switch: five loose rows and two whole boxes.  The
#: pane-readings drop-down used to be the third box; it lives above the preview pane now,
#: where the picture it chooses belongs, and it does not fold - `tests/test_peek_readings.py`
#: holds both halves of that.
FOLDED = ("canvas", "scrim", "fanline", "d_events", "btn_live", "status_box", "reset_box",
          "confirm", "btn_reset")


class WindowWithoutPanel(fixtures.FreshConfigRoot):
    """A window that may not write anything: `save_settings=False`, which is also the default."""

    def setUp(self):
        super().setUp()              # a private, empty settings root for this test alone
        fixtures.qapp()
        self.win = app.Window(MISSING_PORT, 1.0, restore=False)
        self.addCleanup(fixtures.close_window, self.win)
        # a child widget of a window that was never shown reports isVisible() False, which is
        # Qt's rule and not this window's; `tools/selftest.sh` showed every window it inspected
        self.win.show()
        fixtures.pump(0.1)

    def test_it_builds_lists_the_clips_and_previews_every_theme(self):
        self.assertGreaterEqual(self.win.clips.count(), 3, self.win.clips.count())
        for theme in sorted(render.THEMES):
            with self.subTest(theme=theme):
                self.win.theme.setCurrentText(theme)
                self.win._repaint()
                self.assertGreater(self.win.preview.pixmap().width(), 0,
                                   "a theme that cannot be previewed is a theme the "
                                   "combo should not offer")

    def test_the_layout_and_row_pickers_are_owned_by_the_form_they_are_added_to(self):
        """The pickers a person needs in order to open a layout at all are in the box, not just
        in the method that made them.

        The accident this exists to notice: a `QFormLayout` that is built and never put into its
        box is destroyed at the end of `_build()`, taking every widget `addRow`'d into it with it.
        The layout picker, its state line and the row picker once vanished that way - no
        exception, no traceback, a window that looked built.  So the assertion is not "the window
        constructed": it walks the editor's own box and asks for the three rows by name.
        """
        box = self.win.ed_group
        held = []
        stack = [box.layout()]
        while stack:
            layout = stack.pop()
            if layout is None:
                continue
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item.widget() is not None:
                    held.append(item.widget())
                elif item.layout() is not None:
                    stack.append(item.layout())
        self.assertTrue(held, f"{box.__class__.__name__} owns no widgets at all")
        for name in ("ed_name", "ed_state", "ed_widget", "ed_open", "ed_reload"):
            widget = getattr(self.win, name)
            self.assertTrue(any(widget == found for found in held),
                            f"{name} is not in any layout the editor's box owns: the form it "
                            f"was added to was never installed, and it died with that form.  "
                            f"The two `open`/`reload` buttons sit in a QHBoxLayout addRow'd into "
                            f"the form, which is exactly the shape that used to vanish")
            owner, steps = widget.parentWidget(), 0
            while owner is not None and owner is not box and steps < 12:
                owner, steps = owner.parentWidget(), steps + 1
            self.assertIs(owner, box, f"{name} is parented outside the editor's box")

    def test_the_window_builds_against_a_port_that_is_not_there(self):
        """No exception, and the failed action lands in the log where a person can read it."""
        self.assertEqual(self.win.port, MISSING_PORT)
        fixtures.pump(0.3)
        joined = "\n".join(self.win._log_lines)
        self.assertNotIn("Traceback", joined, joined[-400:])

    def test_the_settings_root_is_the_temporary_one_not_a_persons_home(self):
        self.assertTrue(os.environ.get("XDG_CONFIG_HOME"), "no isolated config root")
        self.assertTrue(settings.path().startswith(self.config_root), settings.path())
        self.assertNotEqual(settings.path(), os.path.expanduser("~/.config/xigmaui/config.json"))

    def test_a_window_that_was_told_to_ignore_the_session_never_writes_it(self):
        """The rule that keeps an offline check from replacing a person's file: past the debounce,
        through a close, still nothing - and the window says so in its log rather than silently."""
        fixtures.pump(0.9)                       # the save timer fires 500 ms after a change
        self.win.btn_apply.click()
        fixtures.pump(0.9)
        fixtures.close_window(self.win)
        self.assertFalse(os.path.exists(settings.path()),
                         "a window with save_settings=False wrote a session file")

    def test_the_preview_is_never_scaled_above_the_glass_it_is_showing(self):
        self.win._repaint()
        self.win._fit()
        self.assertLessEqual(self.win.preview.pixmap().width(), render.W,
                             "the pane upscaled a 480 px frame, which is how a preview starts "
                             "looking like the picture rather than the panel")

    def test_the_log_keeps_its_cap_and_drops_the_oldest(self):
        for i in range(app.LOG_KEEP + 40):
            self.win._log(f"line {i}")
        kept = self.win._log_lines
        self.assertLessEqual(len(kept), app.LOG_KEEP)
        self.assertIn(f"line {app.LOG_KEEP + 39}", "\n".join(kept),
                      "the log dropped the newest line instead of the oldest")

    def test_there_is_one_upload_button_and_it_is_not_called_the_old_name(self):
        self.assertNotEqual(self.win.btn_upload.text(), "Upload background")
        self.assertFalse(hasattr(self.win, "btn_upload_bg"),
                         "a second upload control came back")

    def test_a_fresh_window_does_not_claim_to_hold_the_background(self):
        """Populating a list is not the same as a person choosing to keep a clip."""
        self.assertFalse(self.win.keep_clip,
                         "a fresh window decided to hold the background before anyone asked")
        self.assertFalse(self.win.chk_keep.isChecked())


class TheAdvancedSwitch(fixtures.FreshConfigRoot):
    """Five loose rows and three whole boxes fold away; the layout editor never does."""

    def setUp(self):
        super().setUp()
        fixtures.qapp()
        # this is the class that exercises saving, so this window may write - into the temporary
        # root FreshConfigRoot just made for it
        self.win = app.Window(MISSING_PORT, 1.0, restore=False, save_settings=True)
        self.addCleanup(fixtures.close_window, self.win)
        self.win.show()
        fixtures.pump(0.1)

    def widgets(self):
        return [getattr(self.win, name) for name in FOLDED]

    def test_exactly_the_named_controls_fold_and_the_editor_does_not(self):
        self.assertEqual(len(FOLDED), 9)
        self.assertNotIn(self.win.ed_group, self.win._adv_hide,
                         "the layout editor folded away again, and it is the window's only "
                         "layout browser")
        self.win.adv_toggle.setChecked(False)
        fixtures.pump(0.1)
        for name, widget in zip(FOLDED, self.widgets()):
            with self.subTest(control=name):
                self.assertFalse(widget.isVisible(), f"{name} stayed shown when folded")
        for name in ("clips", "theme", "btn_upload", "btn_apply", "log_view", "ed_group",
                     "ed_name", "preview", "clock_size", "ink_choice", "ed_peek",
                     "ed_peek_file", "ed_open", "ed_reload"):
            with self.subTest(kept=name):
                self.assertTrue(getattr(self.win, name).isVisible(),
                                f"the compact view lost {name}, which a first run needs")

    def test_a_folded_control_keeps_the_value_it_was_given(self):
        self.win.adv_toggle.setChecked(False)
        fixtures.pump(0.1)
        self.win.scrim.setValue(200)
        self.assertFalse(self.win.scrim.isVisible())
        self.assertEqual(self.win.scrim.value(), 200,
                         "folding a control away reset it, which is a silent change of picture")

    def test_the_reset_button_is_armed_by_the_typed_word_and_by_nothing_else(self):
        """The double guard is a property of the box, not of its position: folded, hidden **and**
        disabled; shown, still disabled until the word is typed."""
        self.win.adv_toggle.setChecked(False)
        fixtures.pump(0.1)
        self.assertFalse(self.win.btn_reset.isVisible())
        self.assertFalse(self.win.btn_reset.isEnabled())
        self.win.adv_toggle.setChecked(True)
        fixtures.pump(0.2)
        self.assertTrue(self.win.btn_reset.isVisible())
        self.assertFalse(self.win.btn_reset.isEnabled(), "showing the box woke a button nobody armed")
        self.win.confirm.setText("reset")
        fixtures.pump(0.1)
        self.assertTrue(self.win.btn_reset.isEnabled(), "the typed word did not wake the button")
        self.win.confirm.setText("")
        fixtures.pump(0.1)
        self.assertFalse(self.win.btn_reset.isEnabled(), "clearing the word left the reset armed")

    def test_the_switch_and_a_hidden_value_are_remembered_by_the_next_window(self):
        self.win.adv_toggle.setChecked(True)
        fixtures.pump(0.1)
        self.win.scrim.setValue(200)
        self.win._save_now()
        self.assertIs(settings.load()["advanced"], True)
        again = app.Window(MISSING_PORT, None, restore=True)
        self.addCleanup(fixtures.close_window, again)
        self.assertTrue(again.adv_toggle.isChecked(), "the switch was not remembered")
        self.assertEqual(again.scrim.value(), 200,
                         "a hidden control came back at its default instead of at its value")


class SmallContracts(unittest.TestCase):
    """Things stated in one place and honoured in another, checked without building anything."""

    def test_the_fan_checkbox_hands_its_flag_to_every_drawing_button(self):
        import inspect
        source = inspect.getsource(app.Window._build)
        self.assertEqual(source.count("fans=self.fanline.isChecked()"), 3,
                         "the tooltip promises the tachometer array leaves the blob as well as "
                         "the picture; a drawing button that does not pass the flag breaks that")

    def test_the_window_takes_its_name_from_one_constant(self):
        import inspect
        src = inspect.getsource(app.Window)
        self.assertIn("setWindowTitle(TITLE)", src)
        self.assertIn("setToolTip(TITLE", src)

    def test_no_application_stylesheet_is_installed(self):
        """A stylesheet re-polished the whole window and cost 40 px of arc-box height; the palette
        route the tooltip colouring uses does not."""
        self.assertEqual(fixtures.qapp().styleSheet(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
