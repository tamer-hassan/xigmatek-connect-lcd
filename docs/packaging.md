# The `.deb` tree, and what a clean machine says about it

Two binary packages rather than one, what each holds, what `lintian` and CI say when they meet them, and the transcripts - bench and runner - that every number in this file was read out of.

## Install from a .deb

The tree packages itself: `debian/` is debhelper 13 with dh-python
(`dh $@ --with python3 --buildsystem=pybuild`), and it builds **two** binary packages
because the second one is not ours to license.

```bash
sudo apt install build-essential devscripts debhelper dh-python \
                 pybuild-plugin-pyproject python3-all python3-setuptools \
                 python3-wheel desktop-file-utils lintian
dpkg-buildpackage -us -uc -b          # the .deb files land one directory up
lintian ../xigmatek-connect-lcd_*.changes
```

That list is `debian/control`'s own Build-Depends plus `devscripts` (where
`dpkg-buildpackage` and `lintian` come from) and `build-essential`, which
debian/control deliberately does not name - an archive builder is assumed to have it -
and which the CI runner's `dpkg-checkbuilddeps` did not have either: its first attempt
on a clean `ubuntu-26.04` machine reported `build-essential:native` among the unmet,
alongside everything else - debhelper Depends on dpkg-dev, and dpkg-dev only Recommends
build-essential (or a `c-compiler`), so an install of Build-Depends with
`--no-install-recommends` does not bring it in. `pybuild-plugin-pyproject` is not decoration either: `debian/rules` records the
build stopping at "PEP517 plugin dependencies are not available" without it.

| file | what is in it | `.deb` | contents |
|---|---|---|---|
| `xigmatek-connect-lcd_0.2_all.deb` | the three commands in `/usr/bin`, `xigmalcd/` and `xigmaui/` in `/usr/lib/python3/dist-packages`, the three vendored clips in `/usr/share/xigmalcd/media`, the udev rule in `/usr/lib/udev/rules.d`, the user unit in `/usr/lib/systemd/user`, the menu entry in `/usr/share/applications`, the icon in `/usr/share/icons/hicolor/256x256/apps`, and the documentation: `README.md`, `PROTOCOL.md` and the ten `docs/*.md` files they link, under `/usr/share/doc/xigmatek-connect-lcd` | 5.2 MB | 47 files |
| `xigmatek-connect-lcd-themes_0.2_all.deb` | ALPHA's own library under `/usr/share/xigmalcd/themes/alpha`: 27 `.thm` files, their decrypted layouts, 44 background clips (43 MP4 and one PNG), 27 baked overlay PNGs, and `manifest.json`, which hashes all 152 entries of the 125 distinct files | 146 MB | 129 files |

Both rows are one build on the author's bench, 2026-11-07: Ubuntu 26.04 "resolute",
debhelper 13.31ubuntu1, dh-python 7.20260309, python3-all 3.14.3-0ubuntu2,
python3-setuptools 78.1.1-0.1build1, `dpkg-buildpackage -us -uc -b` exit 0. The file
counts are `dpkg-deb -c | grep -c`; the byte figures are rounded on purpose, because
this file is installed *inside* the first .deb and a size quoted here would otherwise
move every time the sentence describing it is edited. The exact hashes and sizes of what
a tag builds are written out by the release job from the files it is uploading. The
themes package is a versioned `Recommends` of the code package, so `apt install` takes it
by default and `apt remove xigmatek-connect-lcd-themes` takes exactly its 129 files away -
it owns its own directory rather than symlinking clips into `media/`.

Four things an install does that a checkout does not:

* the modules go to `/usr/lib/python3/dist-packages`, the directory this distro's
  interpreter is on (`python3 -m site`), not the versioned one pybuild defaults to -
  `debian/rules` pins it and says why, because the first two builds measured the
  difference rather than guessing it;
* `postinst` byte-compiles with `py3compile` and then runs
  `deb-systemd-helper --user enable xigmalcd.service`: the unit is **enabled**, not
  started, so an install does not take `/dev/ttyACM0` in the middle of a session. It is
  the only opener from the next login on; `systemctl --user disable --now xigmalcd`
  takes that back, and `loginctl enable-linger $USER` is what makes it run with no
  graphical session at all;
* no `.pyc` is in either `.deb` - they are written on the target, by the target's
  interpreter;
* the udev rule lands in `/usr/lib/udev/rules.d`, the distro's own directory rather than
  `/etc/udev/rules.d`, so removing the package removes the rule with it - and installing
  it does not make udev read it. Measured on this bench immediately after that install:
  the file was there (`/usr/lib/udev/rules.d/99-xigmatek-lcd.rules`, 634 B, dated with
  the install), and `/dev/xigmatek-lcd` did not exist, and `udevadm info /dev/ttyACM0`
  showed `ID_MODEL=Xigmatek_USB_Device` with no `ID_MM_DEVICE_IGNORE` in its properties.
  What applies a rule is udev reading it: replug the panel, or
  `sudo udevadm control --reload-rules && sudo udevadm trigger --action=change`. There is
  no debhelper hook that does it for you either - `dh_installudev` is in the default
  sequence, does nothing without a `debian/<package>.udev` file, installs one when
  present (with a `--priority` prefix on the name), and adds no maintainer-script
  fragment: `grep -l udevadm /usr/share/debhelper/autoscripts/` answers nothing on this
  box.

And `tools/` is installed by neither package, which is the reason the reset command is a
command of its own - see [If the panel goes white](troubleshooting.md).

### The documentation, as an installed thing

README.md is the short page; the detail is in `docs/*.md`, and the links between them are
written `docs/xxx.md` because that is what works in a checkout and on the GitHub page.
Two measurements decided how the package carries them:

* `dh_installdocs` installs whatever `debian/<package>.docs` names **by basename** - a
  throwaway package on this box with an entry `docs/guide.md` put it at
  `usr/share/doc/<pkg>/guide.md`, while an entry naming a *directory* kept its own name.
  Flattened, the README's `docs/…` links would have pointed at a directory that does not
  exist, so `debian/rules` stages the markdown as a tree under
  `/usr/share/doc/<package>/docs/` and a `.install` line moves it. `README.md` and
  `PROTOCOL.md` stay at the doc root, where `.docs` puts them.
* `dh_compress` gzips documentation by default, and the first build of this layout duly
  produced `docs/packaging/smoke-2026-11-07.log.gz` - and would have produced
  `README.md.gz` and `usage.md.gz` too, which breaks every relative link in the tree even
  though the target is present. `override_dh_compress: dh_compress -X.md -X.log` leaves
  the prose and the transcripts plain; the changelog still gets compressed, as usual. It
  costs about 90 KB and buys a doc set that reads on an installed machine.

What the images do **not** do is get packaged: `docs/logo.png`, the five
`docs/preview-*.png`, `docs/screenshot-xigmaui.png` and the two theme contact sheets are
3.5 MB of rendered PNG, and part of that is rendered from XIGMATEK's theme library, which
is the other package's files and its own licence question. So an installed README shows
prose with repo-relative image links, and that is said here rather than discovered by a
reader.

Checked on the unpacked packages, in that layout: **11** markdown files with no `.gz`
next to any of them, **33** links from one document to another resolving, **8** image
links marked repo-only, **3** pointers that only make sense in a checkout
(`LICENSE`, `debian/copyright`, `themes/alpha`), and the one cited transcript present
uncompressed. `debian/tests/smoke` runs that same accounting against a real install, and
`tools/selftest.sh` runs the equivalent over the checkout - every relative link in
README.md and every `docs/*.md` has to name a file that exists, which is what keeps a
split like this from rotting.

Two of the relationship lines in `debian/control` are choices, and both show up on the
desktop. `xigmatek-connect-lcd-themes` is a **Recommends**, so `apt install` takes the
vendor's library by default and one `apt remove` takes it away again.
`python3-pyqt6` is only a **Suggest**, because the loop that holds the port needs no Qt
and a headless box should not be made to carry it - which means an install can put a
menu entry on a machine that cannot open the window it names. What that person gets is
measured, on this bench, by hiding PyQt6 from the installed command with an import
blocker rather than by assuming a box without it: exit 2, two lines, no traceback -

```
xigmaui needs Qt, which the display loop does not: No module named 'PyQt6'
  install it with `pip install .[gui]`, or from the distro: sudo apt install python3-pyqt6
```

and `tools/selftest.sh` now checks that path the same way, so it stays a sentence.

What has been measured about those bytes without installing them: `lintian
2.129.0ubuntu2.1` on the `.changes` says **0 errors, 0 warnings, 0 infos**; unpacked into
a plain directory, with nothing of ours on the import path, the three commands answer
`--help` (9 808, 1 498 and 637 bytes), `import xigmalcd.protocol` resolves inside the
unpacked tree, the packaged code finds its own three clips by its own root rules at the
sizes and md5s the suite pins, `xigmalcd --dry-run DIR --once` writes one 480×480 PNG and
opens no port, `xigmalcd-reset` with no `--yes` prints the 109-byte frame and sends
nothing, the themes tree re-hashes to its manifest (152 entries, 125 distinct paths, 127
files on disk), and `desktop-file-validate` is clean on the installed menu entry.

What an install actually does has now been measured on this bench, root and all:
`sudo apt install` of both files (apt 3.2.1, Ubuntu 26.04, kernel 7.0.0-42-generic,
2026-11-07 05:43) took them off one command line - the versioned `Recommends`
satisfied by the second file rather than by any archive - unpacked 157 MB, and printed
one thing of its own during `Setting up xigmatek-connect-lcd (0.1)`:

```
Created symlink '/etc/systemd/user/default.target.wants/xigmalcd.service' → '/usr/lib/systemd/user/xigmalcd.service'.
```

That is the whole of its enablement. `dpkg-query` afterwards reports the unit
*enabled*, `systemctl --user is-active` reports it *inactive*, and `fuser
/dev/ttyACM0` says nobody is holding the port: installing draws nothing on the glass.
`debian/tests/smoke` then ran against that install and said `all installed checks
passed` - imports out of `/usr/lib/python3/dist-packages`, `xigmalcd --help` 9 808 B
and `xigmaui --help` 1 498 B, the three clips found under `/usr/share/xigmalcd/media`
by the packaged code's own root rules at the sizes and md5s the suite pins, one 480×480
PNG from a dry run with the port never opened, the udev rule, the unit's
`ExecStart=/usr/bin/xigmalcd --theme alpha --fps 2` with no `--allow-reset`, the menu
entry clean through `desktop-file-validate`, the icon 256×256 RGBA with transparent
corners, `/usr/bin/xigmalcd-reset` printing 355 B - the 109-byte frame - and sending
nothing, nothing from `tools/` on PATH, and 152/152 manifest entries re-hashed under the
installed themes path. The transcript of that run is in this tree at
**`docs/packaging/smoke-2026-11-07.log`**, which is what every figure in this paragraph
was read out of, hashes of the two `.deb` files included.

One line in it is worth remembering, because it is a *no*: `Icon=xigmaui` resolves by
theme name **no** in that check. smoke reports it rather than asserting it - whether the
name resolves belongs to the desktop session's icon cache, and the check ran with
`QT_QPA_PLATFORM=offscreen` - and it is exactly why `xigmaui/app.py:ICONS` tries the
hicolor file itself before giving up: the window's icon does not depend on that lookup
working.

CI (`.github/workflows/ci.yml`) runs the same pair on a machine that has never seen this
tree, and that machine answers for itself. Run
[`42337280424`](https://github.com/tamer-hassan/xigmatek-connect-lcd/actions/runs/42337280424)
is the one where every job ran at once - it is the `v0.1` tag, and all four jobs went
green: seventeen offline sections with no panel in sight, then `dpkg-buildpackage -us
-uc -b` exit 0, then `lintian 2.129.0ubuntu2.1 --fail-on error,warning` printing
`errors=0 warnings=0 infos=0`, then the install job taking **both** packages from one
`sudo apt install ./debs/*.deb`, printing the same `Created symlink
'/etc/systemd/user/default.target.wants/xigmalcd.service'` the bench printed, `159 MB` of
additional disk space, and then `debian/tests/smoke` printing `all installed checks
passed` on a runner - including the half the bench install exercised and this job now
exercises too: `manifest 152/152 files hashed clean under
/usr/share/xigmalcd/themes/alpha`.

Before that run, the push-only job (`42335665086`) had installed only the code package -
a pull-request run does not upload the 146 MB - with apt printing
`Recommended packages: xigmatek-connect-lcd-themes` and planning anyway, and smoke's
themes section saying SKIPPED because there was nothing installed to hash.

Two numbers in the runner's smoke transcript differ from the bench one, and both now
have a reason rather than a shrug:

* the dry-run frame is **7 461 B** there (7 339 B in an earlier run of the same job)
  against **12 652 B** here, because a VM has no thermal zones, no tach header and no
  disks behind the paths `xigmalcd/sensors.py` reads, so every field draws `--` and the
  PNG carries less ink. The same host's own two numbers differ by 122 B, which is the
  clock and the readings, not the packaging;
* `xigmaui --help` is **1 499 B** there against **1 498 B** here. That one byte is the
  config path the `--fresh` help line names: `xigmaui/settings.py:39` expands
  `~/.config`, so the text says `/home/runner/...` on a runner and `/home/tamer/...`
  here. Reproduced on one binary on one machine: `HOME=/home/runner xigmaui --help |
  wc -c` answers 1 499 where the same command answers 1 498.

## The release, and what its hashes do and do not prove

[`v0.1`](https://github.com/tamer-hassan/xigmatek-connect-lcd/releases/tag/v0.1) is an
annotated tag on `28dff67` (the tag object is `5d358ce`, its message names both
packages), published by that run's release job. Four assets, with the sizes and sha256s
the release body prints - computed by the job from the files it uploaded, not typed by
hand:

| asset | bytes | sha256 |
|---|---|---|
| `xigmatek-connect-lcd_0.1_all.deb` | 5 218 596 | `75ae0c05e401d84a1627ac2b33bc82df7f5d540771b17a26224b3b4127d7edf8` |
| `xigmatek-connect-lcd-themes_0.1_all.deb` | 146 136 592 | `e3ac8ac5da02ef77dab44f478ff4a0f87400b925cc82f96633abe736c758cf37` |
| `xigmatek-connect-lcd_0.1_amd64.changes` | 3 588 | `48669e3b6fc978292977a0d1fefa82880ec4ec7e23851f7c342e1a722fe2450b` |
| `xigmatek-connect-lcd_0.1_amd64.buildinfo` | 8 636 | `ab4044db8bfd8acd42a901f1cccbe094bd887c6cb1fa972191c4dcf4d87c1049` |

Those hashes identify **those files**, which is what a download check needs. They are
not the hash of a build of the same source: the runner's code package and one built
from the same tree on this bench came out **18 bytes apart** - 5 218 596 B
(`75ae0c05…`) against 5 218 614 B (`7d04f51b…`) - while every file inside agreed:
`dpkg-deb -e` on both, and all **37** entries of `md5sums` identical, and `diff` over the
two `control` members empty.

The 18 bytes were then measured rather than guessed at, and they are the clock:

* The tar members inside the two `.deb` files are dated at each machine's own build
  time - 06:12 on the runner, 06:07 here - not at any fixed stamp.
* `dpkg-buildpackage` does set `SOURCE_DATE_EPOCH`, from the top `debian/changelog`
  entry (`/usr/bin/dpkg-buildpackage`, line 583:
  `$ENV{SOURCE_DATE_EPOCH} ||= $changelog->{timestamp} || time`), and `debhelper`
  computes the same thing in `Dh_Lib.pm`. But `dpkg-deb` **pulls mtimes down** to that
  value and leaves earlier ones alone - measured with a throwaway package both ways
  round: an epoch of 2001 gives archive members dated 2001-09-09 04:46, an epoch in
  2027 leaves them at the build's wall clock.
* The `0.1` entry was stamped `04:40:00 +0000`, which is *later* than both builds
  (04:07Z, 04:12Z), so nothing was clamped and each machine's clock went into the
  archive. The stamp was also wrong: the entry was written at 03:10:42Z (commit
  `e06cd94`), and it now says so.
* zstd's threading is not the variable: `zstd -19 -T1` and `zstd -19 -T24` on the same
  5 652 480 B `data.tar` give byte-identical output (`2142d58e9439ee41…`).

And the property, measured on this tree rather than asserted: two `dpkg-buildpackage
-us -uc -b` runs with `SOURCE_DATE_EPOCH=1794000000` (2026-11-06 23:20Z, in the past)
produced **byte-identical packages**, both of them -

```
5 218 594 B  3bceb52c219a3d91266abc0d213062065298e6115eb96730bd2584c43b65aca2  xigmatek-connect-lcd_0.1_all.deb
146 136 678 B fe2795d1ad65c02c5c7c6fd0f98bb704f7a980038f208da9089ab6c74f84ab6e  xigmatek-connect-lcd-themes_0.1_all.deb
```

with `cmp` clean on each pair, and the extracted file trees of the pinned build and of
the published asset hashing to the same aggregate (`5058cce770826d7ced02dbbf13309d4b`
for the 37 files either way). `tools/selftest.sh` now keeps the one input that decides
this honest: it fails if the top `debian/changelog` entry is dated in the future,
because that is the whole of what lets a build's clock into the archive.

### The clock was still in there, and where it was hiding

Correcting the stamp was necessary and not sufficient. Two builds of one commit -
`8ac3a32`, the runner and this bench - came out **2 bytes apart**: 5 165 848 B
(`bf887c0eb296c481730a125c8234c6e8584c8f5fb9b69d4f4abb2c46d33fe264`) against 5 165 850 B
(`ba72590bcba4d3ae319f776ab07bde29e39ed2551a09e53298407716bba612ea`), with all 47
`md5sums` entries identical, the two `control` members identical, and - the tell - the
decompressed `control.tar` streams identical while the `data.tar` streams were not.

`data.tar` differs where member **mtimes** differ, and this is the half of the rule that
was not understood when the stamp was fixed: `dpkg-deb` pulls mtimes *down* to
`SOURCE_DATE_EPOCH` and leaves earlier ones alone. The runner had cloned the tree minutes
before building, so every staged file was newer than the stamp and came out uniform at the
stamp; on this bench the working files were older than it and kept their own dates -
`PROTOCOL.md` at 05:03, `debian/copyright` at 03:50, the lintian override at 04:13, 68 of
78 entries in `debian/xigmatek-connect-lcd` older than the stamp and 10 newer.

So `debian/rules` has an `execute_before_dh_builddeb` that touches every entry of the
staged trees (`debian/<package>`, `debian/tmp`) to `$(epoch)`, the changelog's own
timestamp - `dpkg-buildpackage` puts the same value in `SOURCE_DATE_EPOCH`, and it is
recomputed here so the recipe does not depend on the builder having exported it. The
archive is then a function of the source, whatever the machine's files remember. The CI
build job checks it before anything else touches the artifacts: one distinct date across
both packages, equal to `dpkg-parsechangelog -STimestamp`. Measured, this bench:

```
75 entries in data.tar, 6 in control.tar, one distinct date between them: 2026-11-07 03:10 (the changelog stamp)
```

and the point of the exercise: with the pin in place, a build of `8ac3a32` on this
24-core bench and the build of `8ac3a32` the 4-core `ubuntu-26.04` runner uploaded are the
**same bytes** - `cmp` clean, both `5 165 848 B`, both
`sha256 bf887c0eb296c481730a125c8234c6e8584c8f5fb9b69d4f4abb2c46d33fe264`. Two consecutive
builds here are identical too, including the 146 MB themes package
(`146 136 356 B`, `9fbcb6e06ab6642e406f37a99d3ff9e4093066cd7dd383ff1e20fd9f7597c82c`),
which is the first time that one has been compared across machines at all: it needs a tag
run to upload it, and the number for it goes in the table below as soon as one has.

zstd needed no pinning and was measured so that this could be said: `-19 -T1` and
`-19 -T24` on the same 5 652 480 B tar produce byte-identical output
(`2142d58e9439ee41…`), and the two builds' `control.tar.zst` members are the same 3 634
bytes with the same frame header.

### The 0.2 tree, built twice here

The version that carries the pin, measured on this bench rather than described:

```
two `dpkg-buildpackage -us -uc -b` runs, `cmp` clean on both packages
  5 168 042 B  sha256 24f564cd06763678cd3ae9964dbbd98d1faad49bf96da195a7a396c208220dd6  code
146 137 362 B  sha256 db4362c2ce1a01717459997f8c85e70d6866f665ef7af825351b83d0c3451b19  themes
one distinct archive-member date in each, equal to debian/changelog's stamp
  2026-11-07 06:54 local = 04:54 UTC, across 75+6 tar entries in the code package and 145+3 in the themes package
47 files / 47 md5sums entries / Installed-Size 5 576 KB     code package
129 files / 129 md5sums entries / Installed-Size 147 854 KB  themes package
lintian 2.129.0ubuntu2.1 --fail-on error,warning: 0 errors, 0 warnings, 0 infos
```

The date the members carry is the moment the changelog entry was made, not the moment the
build ran - which is the whole mechanism, in one line of output. What those four numbers
have not yet met is a build of the same commit on the runner; for `8ac3a32` that
comparison has been made and came out identical, and the number for the tagged tree goes
here as soon as its release job has published.

The 0.2 changelog entry is 80 columns wide on purpose: `lintian` flagged
`debian-changelog-line-too-long` at two lines of the first draft (4 warnings, one per
long line per binary package, because both packages carry the same `changelog.gz`), and
the wrapping is what silenced it rather than an override.
