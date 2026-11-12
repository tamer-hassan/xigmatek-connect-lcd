#!/usr/bin/env python3
"""Every tooltip this window shows, measured as the pixels it paints.

Ported from the tooltip census of `tools/selftest.sh`'s GUI section.  Reported on 2026-11-11:
every tooltip over the preview pane had a black background and text too faint to read.  A Qt
tooltip is painted by `QTipLabel`, a top-level of the application that takes its colours from the
palette of the widget the tooltip belongs to - so the pane's `background:#101014` stylesheet
dragged that near-black into the popup while the text stayed the palette's own black: **1.11:1**,
with **0** glyph pixels reaching 4.5:1 (WCAG AA for body text).  What ships instead is
`app.apply_tooltip_colours()`: those two colours forced onto the popup's own widget class, and
nothing else.

The popup is **grabbed and its pixels counted**, not read from a palette and trusted: the defect
was a palette nobody had looked at, and a popup that reports one pair while painting another is
exactly how it hid.  And the census is not vacuous, in a way that answers the same on any machine:
hand `QTipLabel` the palette Qt would have given it from the pane (the pane's own `Base` and `Text`
brushes, which is what a stylesheet-painted widget hands over) and the same grab measures
**#101014 behind #000000 at 1.11:1 with 0 readable px** - the reported defect, on command.

What is asserted is the half that answers the same on any machine - a contrast ratio is colour
maths on fixed hexes, and a colour name is a colour name.  The **count** of readable glyph pixels
follows the fonts this box has, so it is reported in the failure text and never asserted as a
floor; only "more than zero" is, because zero readable pixels *is* the reported defect.
"""
from __future__ import annotations

import time
import unittest

from tests import fixtures

from xigmaui import app

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QToolTip, QWidget

MISSING_PORT = "/dev/xigma-no-such-port"

#: WCAG AA for body text.  A ratio, so two machines agree on it.
WCAG_AA = 4.5

#: The plate the preview pane paints for itself, and the one pair the census found that is not
#: `TOOLTIP_BASE`: the popup keeps its owner's background on purpose, and the text colour is the
#: shipped one everywhere.
PANE_PLATE = "#101014"

#: The three spellings the colour row is driven with: the light one, the dark one the tree used
#: before the row's words moved to the label, and a mid-grey that defeats *either* text colour,
#: which is why no promise about a swatch's colour can be made and the swatch carries no popup.
COLOUR_SPELLINGS = ("rgba(255, 255, 255, 255)", "rgba(0, 0, 0, 255)", "rgba(128, 128, 128, 255)")


def luminance(colour: QColor) -> float:
    def channel(value: int) -> float:
        value /= 255.0
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(colour.red()) + 0.7152 * channel(colour.green())
            + 0.0722 * channel(colour.blue()))


def contrast(a: QColor, b: QColor) -> float:
    low, high = sorted((luminance(a), luminance(b)))
    return (high + 0.05) / (low + 0.05)


def popup_of(widget: QWidget) -> tuple:
    """Show `widget`'s tooltip, grab the popup that got painted, and count its pixels.

    Returns (painted background, palette text colour, their ratio, pixels of glyph ink at
    WCAG AA or better, the popup's size, the palette's own base colour).

    The popup is a `QTipLabel`, a top-level Qt creates on demand and destroys on a timer, so it is
    waited for rather than assumed: asking once, immediately, is what made the first version of
    this helper flake between one spelling of a colour and the next.
    """
    QToolTip.showText(widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() // 2)),
                      widget.toolTip(), widget)
    label = None
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and label is None:
        fixtures.pump(0.05)
        label = next((top for top in fixtures.qapp().topLevelWidgets()
                      if top.metaObject().className() == "QTipLabel"), None)
    if label is None:
        raise AssertionError(f"no QTipLabel within 2 s of showText for {type(widget).__name__}")
    image = label.grab().toImage()
    counts: dict = {}
    for y in range(image.height()):
        for x in range(image.width()):
            name = image.pixelColor(x, y).name()
            counts[name] = counts.get(name, 0) + 1
    base = QColor(max(counts, key=counts.get))          # whatever the popup actually painted
    text = label.palette().color(QPalette.ColorRole.ToolTipText)
    own_base = label.palette().color(QPalette.ColorRole.ToolTipBase)
    ink = sum(n for name, n in counts.items() if contrast(QColor(name), base) >= WCAG_AA)
    QToolTip.hideText()
    fixtures.pump(0.03)
    return base, text, contrast(base, text), ink, (image.width(), image.height()), own_base


class EveryLiveTooltip(fixtures.FreshConfigRoot):
    """One shown window at 1280x1024 with a `bars` layout open in its editor."""

    def setUp(self):
        super().setUp()
        fixtures.qapp()
        self.win = app.Window(MISSING_PORT, None, restore=False)
        self.win.show()
        self.win.resize(1280, 1024)
        self.win.ed_name.setCurrentText("bars")
        fixtures.pump(0.4)
        self.addCleanup(fixtures.close_window, self.win)

    def candidates(self) -> list:
        """Every widget this window would answer a hover with: shown, live, and big enough to
        put a cursor on."""
        return [w for w in self.win.findChildren(QWidget)
                if w.toolTip() and w.isVisible() and w.isEnabled()
                and w.width() > 4 and w.height() > 4]

    def test_the_shipped_colours_reach_the_popups_own_class(self):
        """The narrow door: `apply_tooltip_colours` sets both colours on `QTipLabel`'s palette,
        which is the widget class Qt paints the popup with - and no application stylesheet."""
        self.assertFalse(fixtures.qapp().styleSheet(),
                         "an application stylesheet is installed: measured, it costs about 40 px "
                         "of box height in this very window, which is why the door is a palette "
                         "on one class and not a stylesheet")
        pal = fixtures.qapp().palette("QTipLabel")
        self.assertEqual(pal.color(QPalette.ColorRole.ToolTipBase).name(), app.TOOLTIP_BASE,
                         "the popup's background comes from a theme's palette, not the shipped one")
        self.assertEqual(pal.color(QPalette.ColorRole.ToolTipText).name(), app.TOOLTIP_TEXT,
                         "the popup's text colour comes from a theme's palette, not the shipped one")

    def test_no_tooltip_this_window_shows_is_unreadable(self):
        """Each popup shown, grabbed and measured.  A tooltip whose text colour is not the
        shipped one, or whose background is a plate this window does not paint, or whose own
        palette sits under the floor, is the reported defect coming back."""
        found = self.candidates()
        self.assertGreaterEqual(len(found), 20,
                                f"{len(found)} tooltips on this census: a rule asserted over two "
                                "widgets checks nothing")
        painted, unreadable = {}, []
        for widget in found:
            base, text, ratio, ink, _size, own_base = popup_of(widget)
            with self.subTest(widget=type(widget).__name__):
                self.assertEqual(text.name(), app.TOOLTIP_TEXT,
                                 "a popup painted text in a colour the tree does not name")
                self.assertIn(base.name(), (app.TOOLTIP_BASE, PANE_PLATE),
                              "a tooltip took its background from a widget this window does not "
                              "paint a plate on")
                self.assertGreaterEqual(contrast(own_base, text), WCAG_AA,
                                        f"{own_base.name()}+{text.name()} is "
                                        f"{contrast(own_base, text):.2f}:1: the popup's own palette "
                                        "is below the floor")
                self.assertGreater(ink, 0,
                                   f"{base.name()} behind {text.name()} at "
                                   f"{ratio:.2f}:1 leaves 0 readable glyph px")
                painted[(base.name(), text.name())] = painted.get((base.name(), text.name()), 0) + 1
                if ratio < WCAG_AA:
                    unreadable.append((type(widget).__name__, base.name(), text.name(),
                                       round(ratio, 2)))
        self.assertFalse(unreadable, f"{len(found)} live tooltips measured, {unreadable} unreadable "
                                     f"at WCAG AA; pairs painted: {sorted(painted.items())}")

    def test_the_reported_case_still_paints_the_panes_own_plate(self):
        """The popup over the preview pane is the one that was reported, by name.  It keeps the
        pane's #101014 on purpose and gains the lighter text - the pair has to stay readable, and
        it is the pair a person saw at 1.11:1."""
        self.assertTrue(self.win.preview.toolTip(),
                        "the pane stopped carrying a tooltip, so there is no popup to measure")
        base, text, ratio, ink, size, _own = popup_of(self.win.preview)
        self.assertEqual(base.name(), PANE_PLATE,
                         "the pane's popup no longer paints the pane's plate: the colours and the "
                         "pane's stylesheet are being read by something other than the popup")
        self.assertEqual(text.name(), app.TOOLTIP_TEXT)
        self.assertGreaterEqual(ratio, 15.0,
                                f"{base.name()}+{text.name()} came out {ratio:.2f}:1 at "
                                f"{size} px with {ink} readable px")

    def test_a_colour_row_puts_its_words_on_the_label_and_never_on_the_swatch(self):
        """The second hazard the census found, already in the tree before the fix: a tooltip on a
        widget whose stylesheet paints a background paints *that* background.  The colour row's
        swatch paints whatever the layout file names, and no text colour is legible on every
        colour a file can name - so the swatch carries no popup at all and the row's label, which
        paints no background of its own, carries the words."""
        field = self.colour_field()
        label, swatch = self.win.ed_rows[field][0], self.win.ed_rows[field][3]
        self.assertFalse(swatch.toolTip(),
                         "the colour swatch carries a tooltip again: its popup would be painted in "
                         "the layout's own colour, which is not a colour this program can promise "
                         "text for")
        self.assertIn("rgba", label.toolTip(),
                      "the colour row's sentence is not on its label: the words have to live on a "
                      "widget that paints the shipped popup background")

    def test_the_colour_row_stays_readable_at_three_spellings_of_its_own_colour(self):
        """Light, dark, and the mid-grey that defeats either text colour - with the rows rebuilt
        each time, which is where a tooltip would come back.  Taking the swatch's tooltip away has
        to change nothing about how the swatch looks."""
        field = self.colour_field()
        for spell in COLOUR_SPELLINGS:
            with self.subTest(colour=spell):
                self.win.ed.set(field, spell)
                self.win._ed_bind_rows()
                fixtures.pump(0.2)
                label, swatch = self.win.ed_rows[field][0], self.win.ed_rows[field][3]
                before = swatch.grab().toImage().pixelColor(2, 2).name()
                base, text, ratio, _ink, _size, _own = popup_of(label)
                self.assertGreaterEqual(ratio, WCAG_AA,
                                        f"{spell} in the file made a tooltip {ratio:.2f}:1 with "
                                        f"{base.name()} behind {text.name()}")
                self.assertFalse(swatch.toolTip(), "re-binding the rows put a tooltip back on the "
                                                   "swatch")
                self.assertEqual(swatch.grab().toImage().pixelColor(2, 2).name(), before,
                                 "the swatch stopped painting the colour the file names: taking "
                                 "its tooltip away was supposed to change nothing about how it "
                                 "looks")

    def colour_field(self) -> str:
        """The first colour row the `bars` layout offers, with its row shown."""
        for index in range(len(self.win.ed.widgets())):
            self.win.ed.select(index)
            self.win.ed_widget.setCurrentIndex(index)
            fixtures.pump(0.1)
            for field, record in self.win.ed_rows.items():
                if record[4] == "colour" and record[3] is not None:
                    return field
        self.fail("no colour row was offered for a `bars` row, so the swatch case cannot be "
                  "measured")


class TheDoorIsScopedAndIdle(fixtures.FreshConfigRoot):
    """Colouring the popup class may not touch anything else: not the window's controls, not the
    picture the pane has already drawn."""

    @classmethod
    def setUpClass(cls):
        fixtures.qapp()

    def setUp(self):
        super().setUp()
        fixtures.qapp()
        self.win = app.Window(MISSING_PORT, None, restore=False)
        self.win.show()
        # a layout open, so the pane paints the pinned fixture: with no editor the layer is the
        # live theme drawn from this machine's readings, and it moves every tick on its own -
        # which is exactly how the first version of this check flaked
        self.win.ed_name.setCurrentText("bars")
        fixtures.pump(0.4)
        self.win.preview_timer.stop()
        self.addCleanup(fixtures.close_window, self.win)

    def test_the_popup_class_gets_the_colours_and_the_application_palette_does_not(self):
        pal = fixtures.qapp().palette("QTipLabel")
        app_pal = fixtures.qapp().palette()
        self.assertNotEqual(pal.color(QPalette.ColorRole.Window).name(),
                            app_pal.color(QPalette.ColorRole.Window).name(),
                            "the popup palette and the application palette are the same: the class "
                            "targeting went away, and every control would be painted in tooltip "
                            "colours")

    def test_calling_the_door_again_moves_no_pixel(self):
        """`apply_tooltip_colours` runs at window build; calling it again is a no-op, and the
        proof is the pane's own drawn layer compared byte for byte."""
        app.apply_tooltip_colours()
        fixtures.pump(0.2)
        layer = self.win._osd.tobytes()
        app.apply_tooltip_colours()
        fixtures.pump(0.2)
        self.assertEqual(self.win._osd.tobytes(), layer,
                         f"colouring the tooltip class moved the drawn layer: {len(layer):,} B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
