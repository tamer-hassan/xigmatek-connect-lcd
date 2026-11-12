#!/usr/bin/env python3
"""The owner's sizing rule, and the parts of the window that respond to it.

Ported from the fresh-window and sizing blocks of `tools/selftest.sh`'s GUI section, minus the
machine's numbers.  The old block printed a triple of column widths ("532 / 540 / 356") and a clip
row count, and then checked that two documents quoted those same digits for this machine.  That is
the shape this cycle retires: a figure that depends on the fonts of the box it was measured on cannot
live in a page and cannot live in a test, so **the pages name the window instead, and this file keeps
only the relations** - which are the same relations that block asserted, and which fail exactly where
the 0.4 defect failed:

* a column is never narrower than what it holds, and holding it is not the same as fitting it: a
  pane is a scroll area, and the vertical scrollbar its contents force takes its extent off the
  viewport, so a floor equal to the contents' width still leaves horizontal travel;
* a drop-down's **list**, not just its box, carries the widest entry any layout can put in it -
  `_readable` buys that width from the popup, which costs no column pixel, and `_ed_shrink` is its
  pair: a row's control gives way so a form of eighteen never sets a floor;
* minimum 1280x1024, resizable to 3840x2160, and the field grid taking one, two or three columns
  according to the width the controls column actually has.

Nothing here asserts a pixel count that belongs to a machine.  Every number comes out of the window
or out of `app.py`'s own constants while the window is on screen.
"""
from __future__ import annotations

import unittest

from tests import fixtures

from xigmalcd import themes
from xigmaui import app, settings
from xigmaui import edit as gui_edit

MISSING_PORT = "/dev/xigma-no-such-port"

#: The widest row set the editor can be asked for: an `arc` widget's fields, from `gauge`.  The
#: 18 rows of one `arc` row are what made the grid reflow, so a check on a two-field layout proves
#: nothing about a three-column pane.
WIDEST_LAYOUT, WIDEST_ROW_KIND = "gauge", "arc"


class SizedWindow(fixtures.FreshConfigRoot):
    """One shown window, advanced controls open, the widest row set on show."""

    def setUp(self):
        super().setUp()
        fixtures.qapp()
        self.win = app.Window(MISSING_PORT, None, restore=False)
        self.win.show()
        self.win.adv_toggle.setChecked(True)
        self.win._editor_open(WIDEST_LAYOUT)
        fixtures.pump(0.4)
        self.arc_row = next(i for i in range(self.win.ed_widget.count())
                            if str(self.win.ed.widgets()[i].get("type") or "")
                            == WIDEST_ROW_KIND)
        self.win.ed_widget.setCurrentIndex(self.arc_row)
        fixtures.pump(0.3)
        self.addCleanup(fixtures.close_window, self.win)

    def settle(self, passes: int = 12) -> None:
        """Let `_pane_floors` finish.

        A pane's minimum comes from its contents, and its contents move when that minimum moves the
        splitter, so one pass can only see the state before it.  Both versions of this gate that came
        before this file pinned the wrong column while believing they pinned the right one - 340 px
        instead of 300, then 411 px around a floor that had grown to 425.
        """
        fixtures.pump(passes * 0.03)

    def panes(self) -> list:
        return [self.win.split.widget(i) for i in range(3)]

    def widest_entry(self, box) -> tuple:
        """(widest text, its width in that box's own font) - the thing `_readable` buys room for."""
        metrics = box.view().fontMetrics()
        texts = [box.itemText(i) for i in range(box.count())]
        wide = max(texts, key=lambda t: metrics.horizontalAdvance(t), default="")
        return wide, metrics.horizontalAdvance(wide)


class ColumnsHoldWhatTheyShow(SizedWindow):
    def test_a_fresh_window_gives_every_column_at_least_what_it_holds(self):
        self.settle()
        asked = settings.DEFAULTS["split"]
        self.assertEqual(self.win.cfg["split"], list(asked),
                         "the defaults the window starts from are not the ones settings.py carries")
        sizes = self.win.split.sizes()
        self.assertEqual(len(sizes), 3, sizes)
        for index, (area, width) in enumerate(zip(self.panes(), sizes)):
            with self.subTest(column=index):
                self.assertGreaterEqual(width, area.minimumWidth(),
                                        f"a column came back narrower than its own floor: {sizes}")
                self.assertGreaterEqual(area.minimumWidth(),
                                        area.widget().minimumSizeHint().width(),
                                        "the floor is under what the pane holds, so the handle "
                                        "can drag it into a horizontal scrollbar")

    def test_no_column_scrolls_sideways_to_be_read(self):
        self.settle()
        for index, area in enumerate(self.panes()):
            bar = area.horizontalScrollBar()
            with self.subTest(column=index):
                self.assertTrue(bar.maximum() == 0 or not bar.isVisible(),
                                f"column {index} travels sideways: maximum {bar.maximum()}")

    def test_the_class_bounds_are_floors_not_the_answer(self):
        """`PANE_FLOORS` is what a wrapped label plus a readable control need; the real minimum is
        whatever the pane's contents measure, which is the other half of the 0.4 fix."""
        self.settle()
        for index, area in enumerate(self.panes()):
            with self.subTest(column=index):
                self.assertGreaterEqual(area.minimumWidth(), app.Window.PANE_FLOORS[index],
                                        f"this machine's floor is under the bound app.py names")

    def test_pinned_to_its_own_floor_the_controls_column_still_does_not_travel(self):
        """The 0.4 defect arriving one rule later: the pane's minimum came from its contents' width,
        but the vertical scrollbar the rows force took its extent off the viewport - a 411 px floor
        around 411 px of contents left a 397 px viewport and 14 px of horizontal travel."""
        self.settle()
        area = self.panes()[1]
        floor = area.minimumWidth()
        ceiling = area.maximumWidth()
        area.setMaximumWidth(floor)
        self.settle(8)
        self.assertEqual(area.width(), floor,
                         f"{area.width()} px is not the narrow column this window allows")
        bar = area.horizontalScrollBar()
        self.assertTrue(bar.maximum() == 0 and not bar.isVisible(),
                        f"pinned to its own floor the column still scrolls sideways "
                        f"(maximum {bar.maximum()}), so that floor is not its contents' width")
        area.setMaximumWidth(ceiling)
        self.settle()

    def test_a_list_is_never_narrower_than_the_widest_entry_any_layout_puts_in_it(self):
        """Held at the narrowest column the window allows, because that is where a cut would show.
        Whether the *closed box* also fits that entry follows this machine's fonts, so the assertion
        is on the popup and the branch is reported in the failure message."""
        self.settle()
        area = self.panes()[1]
        floor, ceiling = area.minimumWidth(), area.maximumWidth()
        area.setMaximumWidth(floor)
        self.settle(8)
        widest = max(self.widest_entry(box)[1] for box in (self.win.ed_name, self.win.ed_widget))
        for name, box in (("layout", self.win.ed_name), ("widget", self.win.ed_widget)):
            entry, width = self.widest_entry(box)
            with self.subTest(box=name):
                self.assertGreaterEqual(box.view().minimumWidth(), width,
                                        f"a {width} px entry sits in a "
                                        f"{box.view().minimumWidth()} px list, in a "
                                        f"{box.width()} px box at {area.width()} px: the popup "
                                        "stopped carrying the width, which is the elision "
                                        "`_readable` exists to answer")
                if box is self.win.ed_widget:
                    self.assertIn(entry, self.model_row_labels(),
                                  f"{entry!r} is the widest thing this box offers, and it is "
                                  "not a label the model produces")
                else:
                    self.assertTrue(entry == app.NO_EDITOR
                                    or entry in self.offered_layout_names(),
                                    f"{entry!r} is the widest name this box offers, and it is "
                                    "neither a layout nor the sentinel that means none is open")
        area.setMaximumWidth(ceiling)
        self.settle()

    def test_the_two_buttons_under_the_layout_menu_cost_the_column_no_width(self):
        """`reload the list` and `open a file…` sit in the menu's own field column.

        Added because the page says the rows of controls under the fields cost **height** and
        never a column's width, and a new row of buttons is exactly the change that could make
        that sentence false.  Measured two ways: the two buttons together are narrower than the
        widest entry the layout menu has to stay readable for (which is what sets this column's
        floor), and hiding them does not move the floor by a pixel.

        The floors themselves are this machine's, so they are printed rather than asserted:
        `docs/gui.md` points at this command for the figures instead of carrying them.
        """
        self.settle()
        area = self.panes()[1]
        entry, menu = self.widest_entry(self.win.ed_name)
        buttons = sum(b.sizeHint().width() for b in (self.win.ed_open, self.win.ed_reload))
        self.assertLess(buttons, menu,
                        f"the two buttons ask {buttons} px, more than the {menu} px the "
                        f"{entry!r} entry needs: this row, not the menu, now sets the "
                        f"column's floor")
        before = area.minimumWidth()
        for box in (self.win.ed_open, self.win.ed_reload):
            box.setVisible(False)
        self.win._pane_floors()
        self.settle(14)
        self.assertEqual(area.minimumWidth(), before,
                         f"hiding the two buttons moved the column's floor from {before} to "
                         f"{area.minimumWidth()} px, so they are what it is measuring")
        for box in (self.win.ed_open, self.win.ed_reload):
            box.setVisible(True)
        self.settle(8)

    def test_the_census_of_floors_and_row_heights_prints_for_the_machine_running_it(self):
        """The figures docs/gui.md names this command for, on whatever box runs it.

        Nothing here asserts a pixel count: what the page promises is the *rule* - no column
        narrower than what it holds - and the figures are this machine's fonts and rows.  They
        print here so a reader with a different desktop can compare their own window against
        the same three widths instead of against a bench that is not theirs.
        """
        self.settle()
        for width in (1280, 1440, 1919):
            self.win.resize(width, 1024)
            self.settle(16)
            floors = [a.minimumWidth() for a in self.panes()]
            print(f"  {width} px wide: columns' floors {floors} px, split "
                  f"{self.win.split.sizes()}, the field grid laid out in {self.win._ed_cols} "
                  f"column(s) of rows, its own ask {self.win._ed_host.sizeHint().height()} px "
                  f"tall")
        print(f"  app.py's own lower bounds: {self.win.PANE_FLOORS}")

    def offered_layout_names(self) -> set:
        return {rec["name"] for rec in themes.scan()[0]} | set(themes.EXPORTS)

    def model_row_labels(self) -> set:
        """Every row label the editor can be asked to show, from the model rather than from the box."""
        names = [rec["name"] for rec in themes.scan()[0]] + sorted(themes.EXPORTS)
        out = set()
        for name in names:
            model = gui_edit.Editor.open_theme(name)
            for index in range(len(model.widgets())):
                out.add(model.label(index))
        return out


class TheFloorAsApplied(SizedWindow):
    """A window nobody has opened a layout in yet: the floor as `__init__` sets it.

    The exact formula (`max(minimumSizeHint, min(MIN_*, screen))`) is not asserted, because
    `minimumSizeHint` moves once the editor's rows exist and the floor is taken at one instant - the
    first version of this check pinned 999 px against a window whose hint had become 1029.  What is
    asserted is what a reader of the page is promised: the floor never comes under the rule unless
    the screen is smaller, and a size that does come under it is refused out loud.
    """

    def setUp(self):
        fixtures.FreshConfigRoot.setUp(self)
        fixtures.qapp()
        self.win = app.Window(MISSING_PORT, None, restore=False)
        self.win.show()
        fixtures.pump(0.3)
        self.addCleanup(fixtures.close_window, self.win)

    def test_a_left_behind_size_under_the_rule_comes_back_up_and_says_so(self):
        """`~/.config/xigmaui/config.json` can hold a size from a window someone shrank years ago;
        the window refuses it and logs the refusal rather than drawing a cut-off control."""
        settings.save(dict(settings.DEFAULTS, size=[900, 700]))
        again = app.Window(MISSING_PORT, None, restore=True)
        self.addCleanup(fixtures.close_window, again)
        self.assertGreaterEqual(again.width(), again.minimumWidth())
        self.assertGreaterEqual(again.height(), again.minimumHeight())
        self.assertIn("window sized", "\n".join(again._log_lines), again._log_lines[-3:])


class TheSizingRule(SizedWindow):
    """1280x1024 at minimum, up to 3840x2160, and the field grid taking what the width gives it."""

    def test_the_floor_never_undershoots_the_rule_or_this_screen(self):
        """1280x1024 is the owner's floor.  A screen smaller than that is the one exception the
        window applies - offscreen Qt reports an 800x800 screen - and a pane whose contents need
        more beats both, so the claim that survives on any machine is the lower bound."""
        self.assertEqual((app.MIN_WIDTH, app.MIN_HEIGHT), (1280, 1024),
                         "the owner's sizing rule changed, and the page that states it has to "
                         "change with it")
        avail = self.win.screen().availableGeometry()
        for got, bound, limit, label in (
                (self.win.minimumWidth(), avail.width(), app.MIN_WIDTH, "width"),
                (self.win.minimumHeight(), avail.height(), app.MIN_HEIGHT, "height")):
            with self.subTest(dimension=label):
                self.assertGreaterEqual(got, min(limit, bound),
                                        f"{label}: the floor is {got}, under both the rule "
                                        f"({limit}) and this screen ({bound})")
                self.assertGreaterEqual(got, 640,
                                        f"{label}: {got} px is not a window a control can live in")

    def test_a_window_dragged_to_that_floor_still_holds_what_it_shows(self):
        """The responsive half, at the narrow end: the field grid reflows to fewer columns, the
        pane's floor comes down with it, and no column is left travelling sideways to be read."""
        self.win.resize(700, 600)
        self.settle(20)
        self.assertGreaterEqual(self.win.width(), self.win.minimumWidth())
        self.assertGreaterEqual(self.win.height(), self.win.minimumHeight())
        self.assertLess(self.win._ed_cols, 3, "the form kept three columns of rows in a window "
                                              "at its floor, which is the 0.4 defect with the "
                                              "signs reversed")
        for index, (area, width) in enumerate(zip(self.panes(), self.win.split.sizes())):
            with self.subTest(column=index):
                self.assertGreaterEqual(width, area.minimumWidth(),
                                        f"at {self.win.width()} px, column {index} is {width} "
                                        f"and its contents need {area.minimumWidth()}")
                bar = area.horizontalScrollBar()
                self.assertTrue(bar.maximum() == 0 or not bar.isVisible(),
                                f"column {index} travels sideways at the floor")

    def test_every_column_gains_from_a_larger_window(self):
        """The responsive half: the extra width goes to the columns, it does not sit in one of them."""
        self.settle()
        small = self.win.split.sizes()
        self.win.resize(3840, 2160)
        self.settle(20)
        big = self.win.split.sizes()
        for index, (a, b) in enumerate(zip(small, big)):
            with self.subTest(column=index):
                self.assertGreaterEqual(b, a, f"{small} -> {big}: column {index} lost width "
                                              "when the window grew")
        self.assertGreater(sum(big) - sum(small), 1500,
                           f"{small} -> {big}: a 3840 px window did not pass its width on")

    def test_the_field_grid_holds_exactly_the_columns_the_column_can_afford(self):
        """`_ED_COL_PX` is not a wish: the grid asks the pane how much it has and divides, and the
        number of columns it lands on is the claim.  At 4k that is three; at the minimum, one."""
        self.win.resize(app.MIN_WIDTH, app.MIN_HEIGHT)
        self.settle(16)
        narrow = self._cols_and_width()
        self.assertEqual(narrow[1], max(1, min(3, narrow[0] // app.Window._ED_COL_PX)),
                         f"a {narrow[0]} px controls column asked for {narrow[1]} columns")
        self.assertLessEqual(narrow[1], 3, "the grid took more columns than it promises to take")
        self.win.resize(3840, 2160)
        self.settle(20)
        wide = self._cols_and_width()
        self.assertEqual(wide[1], 3, f"a {wide[0]} px column took {wide[1]} columns of rows")
        self.assertGreater(wide[1], narrow[1],
                           f"{narrow} -> {wide}: the form did not reflow into the extra width, "
                           "so the wide window is just a tall one")

    def _cols_and_width(self) -> tuple:
        pane = self.win.split.widget(1)
        fixtures.pump(0.2)
        return pane.width(), self.win._ed_cols

    def test_three_columns_of_rows_fit_inside_the_threshold_that_promises_them(self):
        """`_ED_COL_PX` is a claim about what three columns need, so at the widest window the row
        host must not ask for more than three of them."""
        self.win.resize(3840, 2160)
        self.settle(20)
        self.assertEqual(self.win._ed_cols, 3, "the row host is not showing three columns, so "
                                              "this check would measure nothing")
        host = self.win._ed_host
        asked = host.minimumSizeHint().width()
        self.assertLessEqual(asked, 3 * app.Window._ED_COL_PX,
                             f"three columns of `{WIDEST_ROW_KIND}` rows ask for {asked} px, "
                             f"more than 3 x {app.Window._ED_COL_PX} px says they get")


if __name__ == "__main__":
    unittest.main(verbosity=2)
