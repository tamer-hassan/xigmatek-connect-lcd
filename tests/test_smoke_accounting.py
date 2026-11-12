#!/usr/bin/env python3
"""The installed-library accounting, run by the suite - in a bare root and in a used one.

`debian/tests/smoke` is the check that runs **after** an install, on somebody's machine, and
until 2026-11-13 it had never been run on a machine that had been used.  Its last section
asked:

    assert len(pick) + len(rej) == len(layouts)

meaning "every layout the package installed is either selectable or refused", where `pick`
and `rej` come from `themes.scan()`.  On a runner with a pristine home that is true.  On the
owner's desktop it was not, and what came back was

    AssertionError: (24, 4, 27, "the installed library's layouts are not all accounted for
    by `themes.scan()`")

because `themes.roots()` puts `$XDG_CONFIG_HOME/xigmalcd/themes` **in front of** the installed
library - on purpose, since that is what makes a copy you edited mean `--theme <name>` - and a
saved layout of your own is a name no manifest has ever listed.  23 selectable + 4 refused =
27 installed, plus one `alpha_new.json` answered 28 names: the arithmetic was never wrong, the
assumption was.  Two more asserts in the same block sat on the same sand: the pairing asked
every *picked* layout to name a clip the themes package installed beside it, and a copy of
`alpha` declares no background at all.

So the accounting is per root now, and this file runs the shipped block - the exact heredoc out
of `debian/tests/smoke`, extracted and executed - against the checkout's own copy of the same
tree, in the three states a real box arrives in:

| the box | installed files | answered from the package | refused on `ratio` | hidden behind a copy of yours | yours, in front |
| --- | --- | --- | --- | --- | --- |
| nobody has ever edited a theme | 27 | 23 | 4 | 0 | 0 |
| one copy at a new name | 27 | 23 | 4 | 0 | 1 |
| one copy at a vendor's own name | 27 | 22 | 4 | 1 | 1 |

It runs the block rather than restating its logic: a rule paraphrased in a test is a rule that
can drift out of the script that actually ships.  Nothing here opens a port or writes to a
vendor tree - the copies go into a fresh `$XDG_CONFIG_HOME` this test owns and throws away - and
the block's CLI cross-check (`xigmalcd --list-themes`) is aimed at this tree's entry point, so
the two halves it compares are the same code and the same roots.

Five checks: the three states above, a file the resolver will not answer for at all, and a
static look at the shipped script so the per-root form cannot quietly become a bare count
again.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import unittest

from tests import fixtures

from xigmalcd import themes

SMOKE = os.path.join("debian", "tests", "smoke")

#: The same library the package installs under `/usr/share/xigmalcd/themes/alpha`, as this
#: checkout holds it: the accounting block reads a manifest and a `layouts/` tree, and both
#: exist here.
LIB = os.path.join(fixtures.REPO, "themes", "alpha")

#: The library's census, which the tests below assert against.
MANIFEST_LAYOUTS, SELECTABLE, REFUSED = 27, 23, 4

#: What the accounting block prints, found so this file can tell it from any other.
MARK = "installed selection"


def accounting_block() -> str:
    """The `python3 - "$lib" <<'PY' ... PY` block that reads the installed library."""
    src = fixtures.read(SMOKE)
    blocks = [b for b in re.findall(r"python3 - \"\$lib\" <<'PY'\n(.*?)\nPY\n", src, re.S)
              if MARK in b]
    assert len(blocks) == 1, (
        f"{len(blocks)} of the script's `$lib` blocks print {MARK!r}: this gate has to know "
        "which one is the library accounting, so keep that sentence unique to it")
    ast.parse(blocks[0])            # the shipped bash must still carry runnable python
    return blocks[0]


class TheShippedAccountingRuns(fixtures.FreshConfigRoot):
    """The block from the smoke script, executed here, in three states of `$XDG_CONFIG_HOME`."""

    def setUp(self):
        super().setUp()
        # The block ends by asking the CLI's own door (`xigmalcd --list-themes`) to agree with
        # the numbers it just measured.  On an installed system those are the same code; run
        # from a checkout, `xigmalcd` on PATH is whatever the package manager left there,
        # reading a different pair of roots - so PATH gets this tree's entry point, and only
        # for this test's subprocess.
        self.bindir = os.path.join(self.config_root, "bin")
        os.makedirs(self.bindir, exist_ok=True)
        shim = os.path.join(self.bindir, "xigmalcd")
        with open(shim, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexec " + sys.executable + " -m xigmalcd \"$@\"\n")
        os.chmod(shim, 0o755)

    def run_block(self) -> tuple:
        env = dict(os.environ, XDG_CONFIG_HOME=self.config_root, PYTHONPATH=fixtures.REPO,
                   PATH=self.bindir + os.pathsep + os.environ["PATH"])
        proc = subprocess.run([sys.executable, "-", LIB], input=accounting_block(),
                              capture_output=True, text=True, cwd=fixtures.REPO, timeout=900,
                              env=env)
        return proc.returncode, proc.stdout, proc.stderr

    def census(self) -> tuple:
        """What this machine's doors answer, measured rather than asserted."""
        pick, rej = themes.scan()
        here = [r for r in pick if os.path.abspath(r["root"]) == os.path.abspath(LIB)]
        mine = sorted({r["name"] for r in pick + rej
                       if os.path.abspath(r["root"]) != os.path.abspath(LIB)})
        return len(here), len(rej), mine

    def test_a_bare_root_is_the_one_state_the_old_identity_described(self):
        code, out, err = self.run_block()
        self.assertEqual(code, 0, f"a fresh home, no copies anywhere, and the shipped "
                                  f"accounting fails:\n{out}\n{err}")
        here, ref, mine = self.census()
        self.assertEqual((here, ref, mine), (SELECTABLE, REFUSED, []),
                         "this checkout's library is not the census the block is written "
                         "against, so the numbers below are about a different tree")
        self.assertIn(f"{SELECTABLE} of the {MANIFEST_LAYOUTS} layouts the manifest lists",
                      out, out)

    def test_one_saved_copy_at_a_name_the_library_never_had(self):
        """What the owner's box actually looked like, and the report it produced."""
        path, _soft = themes.save(themes.export("alpha"), "alpha_new")
        self.assertTrue(os.path.isfile(path), path)
        code, out, err = self.run_block()
        self.assertEqual(code, 0, "the shipped accounting cannot handle a layout of your own "
                                  f"at a name of your own:\n{out}\n{err}")
        here, ref, mine = self.census()
        self.assertEqual((here, ref, mine), (SELECTABLE, REFUSED, ["alpha_new"]))
        self.assertIn("copies in front     1 layout(s)", out, out)
        self.assertIn("alpha_new", out, "the run does not name the copy sitting in front of "
                                        "the package")
        self.assertIn(f"{SELECTABLE} of the {MANIFEST_LAYOUTS} layouts the manifest lists",
                      out, out)

    def test_one_saved_copy_hiding_a_vendor_layout_of_the_same_name(self):
        """The other half of first-winning-root: your copy of a vendor name *is* that name."""
        vendor = next(r["name"] for r in themes.scan()[0]
                      if os.path.abspath(r["root"]) == os.path.abspath(LIB))
        _rec, path, _soft = themes.copy_for_edit(vendor)   # the library's own seeding door
        self.assertTrue(os.path.isfile(path), path)
        won = themes.resolve(vendor)
        self.assertEqual(os.path.abspath(won["path"]), os.path.abspath(path),
                         "`resolve()` never started answering your copy of that name, so this "
                         "is not the state the check below is about")
        code, out, err = self.run_block()
        self.assertEqual(code, 0, "the shipped accounting calls a hidden vendor layout a "
                                  f"broken install:\n{out}\n{err}")
        here, ref, mine = self.census()
        self.assertEqual((here, ref, mine), (SELECTABLE - 1, REFUSED, [vendor]),
                         "a copy in front of an installed name should take exactly one layout "
                         "out of the package's own count")
        for needle in (f"{SELECTABLE - 1} of the {MANIFEST_LAYOUTS} layouts the manifest lists",
                       f"1 hidden behind a copy of yours at the same name: {vendor}"):
            self.assertIn(needle, out, f"the run does not say {needle!r}:\n{out}")

    def test_a_file_with_nothing_to_draw_is_excluded_and_counted_as_one(self):
        """The sharp edge this cycle found, and the rule that closed it.

        `scan()` used to select on the `ratio` field and nothing else, so a JSON in your own
        themes directory that parses, declares 1:1 and carries no `osd` at all was a name
        `resolve()` answered - and `layout.draw_theme` walks `obj["osd"]["widget"]`, so the
        frame naming that file raised `KeyError: 'osd'` instead of drawing an empty canvas.
        Measured while fixing the accounting above, and the same rule the writer already had
        (`themes.save` refuses an empty `osd.widget` list) is now the reader's too.  What this
        check holds is the consequence for the installed accounting: such a file is *refused*,
        named among the exclusions with its reason, counted under "copies in front", and the
        block still closes - rather than reaching the painter and taking the install check
        down with it.
        """
        os.makedirs(themes.user_root(), exist_ok=True)
        junk = os.path.join(themes.user_root(), "not_a_layout.json")
        with open(junk, "w", encoding="utf-8") as fh:
            fh.write('{"id": "x", "ratio": "1:1", "width": 480, "height": 480}\n')
        self.assertIsNone(themes.resolve("not_a_layout"),
                          "selection answers a 1:1 file with no `osd` again, which is how the "
                          "loop gets a `KeyError` on a frame instead of a refusal")
        code, out, err = self.run_block()
        self.assertEqual(code, 0, f"an excluded junk file took the installed accounting down "
                                  f"instead of being counted:\n{out}\n{err}")
        self.assertIn("not_a_layout", out,
                      f"the run never names the file it refused:\n{out}")
        self.assertIn("copies in front     1 layout(s)", out,
                      f"the refused file was not counted as this box's own:\n{out}")
        here, ref, mine = self.census()
        self.assertEqual((here, ref, mine), (SELECTABLE, REFUSED + 1, ["not_a_layout"]),
                         "the census this check is written against moved: a file with nothing "
                         "to draw should land in the excluded list, not in the selectable one")

    def test_the_smoke_script_still_asks_the_identity_per_root(self):
        """The shape of the assert, read out of the shipped script rather than trusted.

        A per-root identity is easy to write once and easy to write back into a bare count by
        whoever edits the script next - and the failure only appears on a box somebody has
        used, which is the only kind of box this packaging check ever runs on.
        """
        block = accounting_block()
        # The script ships in the source tree and runs against the *installed* code, so the
        # two can be different versions on a development box - which is exactly how the owner
        # of one met a confusing AssertionError instead of a named mismatch.
        for needle in ("NEED_OSD_WHY", "are not the same code"):
            self.assertIn(needle, block,
                          f"the accounting no longer says what it needs out of the installed "
                          f"xigmalcd (missing {needle!r}): a check written for a newer reader "
                          "fails an older install with an arithmetic message and sends the "
                          "reader off to look at their own themes directory")
        for needle in ('r["root"]', "hidden", "manifest lists", "copies in front"):
            self.assertIn(needle, block,
                          f"the installed-library accounting no longer mentions {needle!r}: "
                          "it has gone back to counting the files of one root while "
                          "`themes.scan()` reads three")
        self.assertNotIn("len(pick) + len(rej) == len(layouts)", block,
                         "the pristine-home identity is back: 27 installed layouts plus one "
                         "copy of somebody's own answers 28 names, and that is not a bug in "
                         "the install")
        for loop in re.findall(r"for rec in (\w+):", block):
            self.assertIn(loop, ("pick", "sel"),
                          f"the block iterates {loop!r}, a name this file has never heard of")
        self.assertIn("for rec in sel:", block,
                      "the pairing is not limited to the package's own records again, and a "
                      "layout of yours that declares no background is not a broken install")


if __name__ == "__main__":
    unittest.main(verbosity=2)
