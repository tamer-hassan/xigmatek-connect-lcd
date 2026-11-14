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

Before either package is worth building there is one gate, and CI puts it first: the
offline checks in `tests/`, run by the standard library, with no panel in sight - and the
`.deb` job `needs` that job, so a tree that fails a check never produces a package
(`.github/workflows/ci.yml`).

That checks job has a `timeout-minutes` of its own, and the number is read off GitHub's
durations rather than chosen: it normally runs 405-465 s, so it was capped at 30 minutes -
"four times", with 2% to spare. CI #202 showed what that margin bought. Attempt 1 ran on a
loaded runner: the `tests/` step alone took **1762 s** against the 406, 406, 412 and 415 s of
its four neighbours, the job reached 1816 s, and GitHub cancelled it with one GUI check red.
Attempt 2, *the same commit*, finished green in **414.204 s**. Nothing about the geometry
differed between the two machines, so the cap is 45 minutes now - about six times a normal
run and comfortably above the worst attempt seen - and `tests/test_ci_workflow.py` holds the
file to that: every job declares a timeout (without one, GitHub's default is six hours, so a
job that cannot reach the network holds a runner for six hours before saying so), the checks
budget covers the observed worst without becoming permission to hang, and the comment next to
the number still carries 1762 / 1816 / 414.2, because a budget raised without its reason gets
"tidied" back down.

The check that failed under that load was itself the lesson: `tests/test_window_sizing.py`
waited after a resize with `settle(passes)`, a fixed wall-clock pump of the Qt event loop,
then asserted geometry. Measured on this bench the splitter stops moving after **3 pumps
(0.09 s)**, which is why the bet held for 550-odd checks and broke on a machine running 4.2x
slow. Four resize-dependent checks now wait on the *state the assertion reads*
(`settle_until_stable`, bounded at 60 pumps, returning what it cost), and a check asserts the
bound is met and the sampler converged - an unbounded wait is as useless as a fixed bet.
What is *not* claimed anywhere here is a cause for that slow runner, or a leak: the cleanup
lines naming an orphaned `python3` and `ffmpeg` are what cancellation looks like when a suite
is killed mid-decode, because every `ffmpeg` call in this codebase goes through
`subprocess.run`, which waits.

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

Both rows are one build on the author's bench, 2026-11-07, of the tree at the `v0.2` tag.
A build of the tree at the `v0.3` tag names the files `_0.3_` instead, and that build is
measured in its own section below, "What the 0.3 tree packages, measured" - the themes
package changed shape on the way here, because the vendor's `.thm` containers are no longer
packaged, so that file is a good deal smaller than the 146 137 362 B above while holding the
same library. **The tree is at `0.4`, and `v0.4` is tagged and published**: its record is
the last two sections of this page, built from the tag on the bench and by the runner, and
every byte count between here and there is the `v0.3` tag's. The version
number is spelled the same in three places - the top `debian/changelog` stanza,
`pyproject.toml` and `xigmalcd.__version__` - and the CI job that builds the packages fails
if those spellings ever part company (`debian/README.source` says why).
The build quoted here ran on Ubuntu 26.04 "resolute",
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
  `deb-systemd-helper --user enable xigmalcd.service`. That puts the symlink in
  **`/etc/systemd/user/default.target.wants/`** - root-owned, and systemd calls that
  scope *global*: it applies to every user's next login, not to the one who ran `apt`.
  The consequence is worth knowing before you try to undo it: `systemctl --user disable
  --now xigmalcd` does **not** take it back, and systemd says so rather than failing
  quietly -

  ```
  The following unit files have been enabled in global scope. This means
  they will still be started automatically after a successful disablement
  in user scope:
  xigmalcd.service
  ```

  what takes it back is `sudo systemctl --global disable xigmalcd.service` (per
  `man systemctl`, `--global` "operate[s] on the global user configuration directory"),
  and `apt remove xigmatek-connect-lcd` cleans the symlink up on its own because
  `deb-systemd-helper` recorded it in
  `/var/lib/systemd/deb-systemd-user-helper-enabled/xigmalcd.service.dsh-also`.
  `loginctl enable-linger $USER` is what makes the display run with no graphical
  session at all;
* and one thing that claim has to carry, because the bench found it the hard way: *an
  install does not draw on the glass* was measured on the first install (0.1, 05:43 -
  `active-state: inactive`, `fuser /dev/ttyACM0` empty). An **upgrade** on a machine that
  is logged in is not the same event. Upgrading 0.1 to 0.2 at 07:21, the user manager
  started the display by itself:

  ```
  07:21:44 sudo apt install -y …_0.2_all.deb …_0.2_all.deb     (closed 07:21:47)
  07:21:50 systemd[2466]: Starting xigmalcd.service - Xigmatek Connect LCD - …
  07:21:55 systemd[2466]: Started xigmalcd.service - …          (Main PID 639693)
  07:21:57 xigmalcd[639693]: background Theme_25.mp4 refused (device refused the file: 400 ''); retrying once
  07:21:58 xigmalcd[639693]: background Theme_25.mp4 214917 B -> notice 200 in 2.3 s, space 69084 -> 69104
  ```

  Seven minutes later `xigmalcd --status` over the control socket read back
  `188/188 frames confirmed, 0 refused, session 188 uploads / 94 s`, and `fuser
  /dev/ttyACM0` named PID 639693 as the holder. The 5 s between `Starting` and `Started`
  is this project's own `ExecStartPre=/bin/sleep 5`, not systemd hesitating. What is
  **not** established is who queued that start job: the generated postinst contains no
  `systemctl` call at all (read it: lines 13-31 are `deb-systemd-helper` only), and the
  helper's own logic - `was_enabled` at `/usr/bin/deb-systemd-helper:418` returns true
  when its state file lists links that are all present, and `enable` at line 311 then
  takes the "links already installed" path rather than the `systemctl --global preset`
  one, which is what the existing
  `/var/lib/systemd/deb-systemd-user-helper-enabled/xigmalcd.service.dsh-also` puts it on
  - means the postinst touched the filesystem and nothing else. The user manager
  (`systemd[2466]`) logged a `Reload requested from client PID 639694 ('systemctl')`, in
  the terminal's own scope, five seconds *after* the start job began, so that reload is
  not what queued it either. Two candidates were checked and ruled out as the actor: a
  `systemctl preset` from the helper (not called, as just shown) and `udevadm trigger
  --action=change` (which the transcript's own script ran at 07:21:47, and which re-ran
  rules for every device - visible as KDE losing and regaining its DRM render nodes at
  07:21:47 - but has no path to a user unit with no device dependency). Two data points
  sit on the other side: both times this package has been installed into a machine with no
  logged-in session holding a user manager - the 0.1 install on this bench, and every CI
  runner install - smoke then printed the unit `enabled` and `inactive` with the port free,
  and the runner's install job now prints `unit state  inactive; is-enabled --user=enabled,
  --global=enabled`. So the auto-start has been seen once, on an upgrade inside a live
  session, and never on a fresh install. That is a correlation, and it is written as one.
  Settling it needs
  a second upgrade on a machine where the answer can be varied deliberately - with and
  without a `systemctl --user daemon-reload` either side - and until then the honest
  summary for a reader is the operational one: **upgrading this package on a logged-in
  session can bring the display up on its own**, so stop it first (`systemctl --user stop
  xigmalcd`) if something else is holding the port or you are mid-run on the glass.
  The 0.6 → 0.7 upgrade on the owner's desktop on 2026-11-13 printed the other half of the
  same picture: `systemctl --user restart xigmalcd` answered `Warning: The unit file, source
  configuration file or drop-ins of xigmalcd.service changed on disk. Run 'systemctl --user
  daemon-reload' to reload units.` Neither .deb has a `postinst`, so nothing in an install
  talks to the session's user manager - deliberately, since that manager belongs to the
  desktop, not to dpkg - which means the restart ran the **new** `/usr/bin/xigmalcd` under the
  **old** unit's properties. For this upgrade that made no difference (the two unit files
  agree on `ExecStart`), but the order that provably loads a changed unit is `stop`,
  `daemon-reload`, `start` - and `install/install.sh`, which writes the checkout's own copy
  of the unit, does all three in that order.
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

What the pictures do **not** do is get packaged. `debian/rules` installs prose and
nothing else - `install -m 644 docs/*.md` - so the images, the theme contact sheets, the
videos and the readings JSON that drives them are repo-only material: `docs/logo.png`, the
generated window capture, the two live captures the README carries, `docs/previews/*.png`,
`docs/videos/*.mp4` and `docs/videos/*.json`. Count them with
`du -b docs/*.png docs/previews/*.png docs/videos/*` rather than trusting a number on this
page: a re-shot capture or a re-rendered preview moves the total, and a figure that has to
be re-derived to stay true is a figure that goes stale. There is no gate on these bytes,
and the reason is that the last one existed to keep a sentence in this page honest.

Two things about those files are worth stating, because neither is obvious from the tree.
The videos are also not package material for a second reason: what README links is GitHub's
copy of them - the editor uploads the file to its CDN and writes that URL into the cell - and
a URL is not a path this package could install. The files in `docs/videos/` stay as the
measured originals, byte-identical to what those URLs serve. So an installed README shows
prose with repo-relative links that point at nothing on disk, and that is said here rather
than discovered by a reader.

And one of those pictures was **edited rather than re-shot**. The advanced-mode live capture
shows the panel's `conn 1` reply, and that reply names this panel's serial number: from
2026-11-08 it sat in that PNG as pixels, whole and legible to an OCR pass, until 2026-11-10.
The rule it broke is the one that keeps `data/captures/` and `data/glass/` out of the
repository altogether - the serial stays on the bench - and what had been holding that rule
was grepping the staged diff, which reads bytes and cannot see a pixel. The field is now
painted with the same `<redacted>` wording `docs/gui.md` uses, in a monospace face at the
size and ink colour the window used. `tests/test_no_serial.py` is what keeps it painted out:
both halves of the serial, and the serial's shape, searched through every tracked text file
and every published PNG - the byte half everywhere, the OCR half wherever `tesseract` is
installed, saying so out loud where it is not rather than going quiet.

Checked on the unpacked 0.3 packages, in that layout: **11** markdown files with no `.gz`
next to any of them, **43** links from one document to another resolving (none dead),
**3** image links marked repo-only, **3** pointers that only make sense in a checkout
(`LICENSE`, `debian/copyright`, `themes/alpha`), and the two kept install transcripts
present uncompressed. The image-link count came down from 8 when the GIFs went: two
contact-sheet/screenshot links and one `<img>` tag are all the installed prose still
carries, and the six videos are not links at all. That is why smoke's image rule has to
stay a rule about links: an installed document pointing at a picture that is not installed
is a known, chosen shape, and the documents say so.
`debian/tests/smoke` runs that same accounting against a real install, and
`tests/test_docs_links.py` runs the equivalent over the checkout - every relative link in
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

and `tests/test_launch_unit.py` checks that path the same way, so it stays a sentence.

What has been measured about those bytes without installing them: `lintian
2.129.0ubuntu2.1` on the `.changes` says **0 errors, 0 warnings, 0 infos**; unpacked into
a plain directory, with nothing of ours on the import path, the three commands answer
`--help` (10 488, 1 498 and 637 bytes for this tree - `xigmalcd` was 9 808 in the 0.2
build below, before its `--text-color` flag existed), `import xigmalcd.protocol`
resolves inside the
unpacked tree, the packaged code finds its own three clips by its own root rules at the
  *(the reading below is from when `media/` held three: today `debian/rules` installs
  every file in `media/`, fourteen of them, and the byte figures here are re-taken at the
  next build)*
sizes and md5s `tests/test_pinned_metrics.py` pins, `xigmalcd --dry-run DIR --once` writes one 480×480 PNG and
opens no port, `xigmalcd-reset` with no `--yes` prints the 109-byte frame and sends
nothing, the themes tree re-hashes to its manifest (125 entries over 98 distinct paths,
100 files on disk - the 27 `background` entries naming the same bytes as 27 of the clips,
and the vendor's 27 `.thm` containers living as hashes in `notRedistributed` rather than
as files), and `desktop-file-validate` is clean on the installed menu entry.

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
/dev/ttyACM0` says nobody is holding the port: that first install draws nothing on the
glass. (An upgrade in a live session is a different event - see the bullet above about
the 0.2 upgrade starting the display on its own, and the transcript two files down.)
`debian/tests/smoke` then ran against that install and said `all installed checks
passed` - imports out of `/usr/lib/python3/dist-packages`, `xigmalcd --help` 9 808 B
and `xigmaui --help` 1 498 B, the three clips found under `/usr/share/xigmalcd/media`
  *(same vintage: the count is now every clip in `media/`)*
by the packaged code's own root rules at the sizes and md5s `tests/test_pinned_metrics.py`
pins, one 480×480
PNG from a dry run with the port never opened, the udev rule, the unit's
`ExecStart=/usr/bin/xigmalcd --theme alpha --fps 2` with no `--allow-reset`, the menu
entry clean through `desktop-file-validate`, the icon 256×256 RGBA with transparent
corners, `/usr/bin/xigmalcd-reset` printing 355 B - the 109-byte frame - and sending
nothing, nothing from `tools/` on PATH, and 152/152 manifest entries re-hashed under the
installed themes path - that being the 0.2 package, which carried the 27 `.thm` files;
the 0.3 package's tree hashes 125 and is measured below. The transcript of that run is in
this tree at
**`docs/packaging/smoke-2026-11-07.log`**, which is what every figure in this paragraph
was read out of, hashes of the two `.deb` files included.

One line in it is worth remembering, because it is a *no*: `Icon=xigmaui` resolves by
theme name **no** in that check. smoke reports it rather than asserting it - whether the
name resolves belongs to the desktop session's icon cache, and the check ran with
`QT_QPA_PLATFORM=offscreen` - and it is exactly why `xigmaui/app.py:ICONS` tries the
hicolor file itself before giving up: the window's icon does not depend on that lookup
working. It said the same `no` again in the 0.2 transcript, on the same machine, forty
minutes later.

## The release, and what its hashes do and do not prove

Each tag's release job publishes four assets - the code package, the themes package, the
`.changes` and the `.buildinfo` - and the release body prints their sizes and sha256s,
computed by the job from the files it uploaded rather than typed by hand. Those hashes
identify **those files**: what a download check needs. They are not the hash of "a build of
this source", because two builds of one tree agree on bytes only if the tree lets them.

The one input that decides it is the top `debian/changelog` stamp. `dpkg-buildpackage` takes
`SOURCE_DATE_EPOCH` from that line (`/usr/bin/dpkg-buildpackage`: `$ENV{SOURCE_DATE_EPOCH}
||= $changelog->{timestamp} || time`), and `debhelper` computes the same thing in
`Dh_Lib.pm`; `dpkg-deb` then rewrites every archive member's mtime to it. The direction is
the trap: `dpkg-deb` pulls mtimes **down** to the epoch and leaves earlier ones alone, so an
entry dated in the future lets each machine's wall clock into the archive. That was measured,
not inferred - a throwaway package with an epoch of 2001 gives members dated 2001-09-09 twice
with identical bytes, and one with an epoch in 2027 leaves members at the build's own clock.

The published `v0.1` code package and one built from the same tree on this bench were **18
bytes apart** - 5,218,596 B against 5,218,614 B - while everything inside them agreed: `diff`
over the two `control` members empty, all **37** `md5sums` entries identical. The runner built
at 04:12Z and this bench at 04:07Z, and that entry was stamped 04:40Z, so nothing was clamped.
Two later builds of one tree, with an epoch in the past, came out byte-identical for both
packages, `cmp` clean. And zstd's threading is not the variable: `zstd -19 -T1` and
`zstd -19 -T24` over one 5,652,480 B `data.tar` give the same bytes.

So the rule is a check rather than a habit: `tests/test_debian_changelog.py` fails if the top
`debian/changelog` entry is dated in the future, and the deb job prints the stamp it built
from.

**And the rule is necessary, not sufficient: the toolchain is a second input, measured on
the 0.7 release.** One tagged commit (`c8ffa29`), two machines, both running the same
recipe: the GitHub runner on `ubuntu-26.04` and this bench on `26.10`. The themes package
came out **byte-identical** - `79 932 856 B`, sha256 `204c7647a447450f…` on both sides,
`cmp` clean. The code package did not: `21 578 396 B` / `fb2169110ff9141d…` from the runner
against `21 577 030 B` / `317ba7f09b06a3ba…` from here. Unpacked and diffed, the gap is
small and it is fully explained: **one installed file**, `xigmalcd-0.7.dist-info/WHEEL`,
which the runner wrote and this bench's toolchain did not; `md5sums` differing by that one
line; `control` differing by `Installed-Size: 22540` against `22539`, the 1 kB that file
accounts for; and the two generated maintainer scripts, marked `dh_installsystemduser/
13.31ubuntu1` there and `/14.5ubuntu1` here, with debhelper 14 moving the trixie unmask line
inside an `if [ -z "$DPKG_ROOT" ]`. Nothing about the source differed: the two bench builds
of the same tag (`#20` and `#21`, `dh_clean` then `dpkg-buildpackage -us -uc -b`) came out
identical to each other, both tars, both control members, `cmp` clean.

So a `.deb` hash identifies **this source built by this build toolchain**, and the hashes in
a release's notes are the runner's. Rebuild 0.7 on a box with a different debhelper and the
code package will differ in precisely the places above - a `WHEEL`, one `md5sums` line, one
kilobyte of `Installed-Size`, two script bodies - while the themes package will match. The
stamp rule is what keeps the clocks out of it; the package manager's version is what keeps
the bytes from agreeing across machines, and that is stated here because the alternative is
a maintainer diffing two archives hunting for a source difference that does not exist.

  One correction, recorded where the census is rather than left silent: the 0.7 stanza's
  lead entry first called this `the sixth tag`, and `git for-each-ref refs/tags --format=
  '%(refname:short) %(creatordate:iso-strict)'` counts seven, created in order from v0.1 on
  2026-11-07 to v0.7 on 2026-11-14. The stanza in this tree says `seventh`; the
  `changelog.gz` inside the published `v0.7` archives says `sixth`, because those bytes were
  built from the tag and the tag is not rewritten over a word. The per-release digests - what each tag's CI build and the local rebuilds came out to -
live in that release's own notes, which is where a dated figure belongs. This page keeps the
rule, not the table.
