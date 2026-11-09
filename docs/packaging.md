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
offline suite - twenty-two offline sections with no panel in sight - and the `.deb` job
`needs`
it, so a tree that fails a check never produces a package (`.github/workflows/ci.yml`).

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
A build of this tree names the files `_0.3_` instead, and that build is measured in its own
section below, "What the 0.3 tree packages, measured" - the themes package changed shape on
the way here, because the vendor's `.thm` containers are no longer packaged, so that file is
a good deal smaller than the 146 137 362 B above while holding the same library. The version
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

What the pictures do **not** do is get packaged, and since 0.3 there are two kinds of
them. The images: `docs/logo.png` and `docs/screenshot-xigmaui.png` (1 070 024 B), the two
theme contact sheets in `docs/previews/` (1 596 454 B). The videos: the six MP4s in
`docs/videos/` (5 039 178 B - the README's five previews plus the amber-ink figure
docs/gui.md carries) and the readings JSON that drives them (13 916 B). **7 719 572 B**
across 11 files, part of it rendered from XIGMATEK's own theme library, which is the
other package's files and its own licence question - and the videos are also not package
material for a second reason: what README links is GitHub's copy of them - the editor
uploads the file to its CDN and writes that URL into the cell - and a URL is not a path this
package could install. The files themselves stay in `docs/videos/` as the measured
originals, byte-identical to what those URLs serve (docs/limits.md keeps that comparison).
So an installed README shows prose with repo-relative links that point at nothing on disk,
and that is said here rather than discovered by a reader.

Those five numbers are not kept by hand any more: the launcher section of
`tools/selftest.sh` re-derives them from the files themselves (logo, the window capture,
the two contact sheets, the six MP4s and the readings JSON) and fails if this page
disagrees.  That gate earned its place the slow way - the video total had drifted by
22 405 B when the amber-ink figure was re-rendered and nothing noticed, and re-shooting
the window picture for the layout editor's new row moved the image total by 7 853 B more.

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
`--help` (10 488, 1 498 and 637 bytes for this tree - `xigmalcd` was 9 808 in the 0.2
build below, before its `--text-color` flag existed), `import xigmalcd.protocol`
resolves inside the
unpacked tree, the packaged code finds its own three clips by its own root rules at the
sizes and md5s the suite pins, `xigmalcd --dry-run DIR --once` writes one 480×480 PNG and
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
by the packaged code's own root rules at the sizes and md5s the suite pins, one 480×480
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

### The 0.2 upgrade on this bench, and what the doc set looks like installed

The second install transcript, **`docs/packaging/smoke-2026-11-07-02.log`**, is an
*upgrade* (0.1 → 0.2) of the two release assets, run by the same kind of script, at
05:21:44Z: apt's own summary `Upgrading: 2, Installing: 0, Removing: 0`, `Space needed:
63.5 kB`, both files hashed in the log (`f8c0cd69…` and `db4362c2…`, which are also this
machine's own build of the tag - the paragraph comparing them is further down). What it
adds to the record:

* `dpkg -L xigmatek-connect-lcd | grep -c '^/usr'`: **62 paths before** (0.1), **74 after**
  (0.2). That is the doc set arriving: the package's own non-directory entry count went
  37 → 47 at the same time, and the difference is the ten `docs/*.md` files and the
  transcript they cite.
* Installed layout, read back off the filesystem: `/usr/share/doc/xigmatek-connect-lcd/`
  holding `PROTOCOL.md` **93 190 B** and `README.md` **9 082 B** - not `.gz`, because of
  `override_dh_compress` - plus `docs/` with `gui.md 40 103`, `handoff-2026-11-05.md
  8 088`, `install.md 5 248`, `limits.md 29 416`, `packaging.md 21 666`, `themes.md
  2 714`, `tools.md 28 358`, `troubleshooting.md 2 493`, `usage.md 18 201`, and
  `docs/packaging/smoke-2026-11-07.log 5 079`. Installed-Size: 5 578 KB code, 147 854 KB
  themes.
* smoke's documents section on a real install: `11 markdown files … none compressed`,
  `33 links inside the doc set, all resolving; 8 image link(s) repo-only by design; 3
  pointer(s) into the source tree (LICENSE, debian/copyright, themes/alpha)`, `1 kept
  log(s)`. The same accounting the CI runner printed for the tag run, on desktop hardware.
* The rest of smoke again green: `--help 9 808 B` and `1 498 B`, the three clips with
  `roots ('/usr/share/xigmalcd/media',)`, a dry-run frame now **12 421 B** (it was 12 652 B
  in the 0.1 transcript: same host, different minute, the numbers on the picture change
  what the PNG costs), the menu entry clean, `xigmalcd-reset` 355 B printed and nothing
  sent, `manifest 152/152 files hashed clean` with `kinds {'thm': 27, 'background': 27,
  'foreground': 27, 'layout': 27, 'clip': 44}`, and `all installed checks passed`.
* The udev rule, this time **applied**: the script ran
  `sudo udevadm control --reload-rules && sudo udevadm trigger --action=change` (labelled
  in the transcript as the script's doing, not apt's), and after it `/dev/xigmatek-lcd ->
  ttyACM0` exists and `udevadm info /dev/ttyACM0` carries `ID_MM_DEVICE_IGNORE=1`. Compare
  the 0.1 transcript, where both were absent with the rule file present: the difference is
  one `udevadm` command, which is exactly the point of that bullet above.
* And the thing that was not planned: the display came up by itself during that upgrade,
  three seconds after apt closed, and was still holding the port when the log finished -
  `188/188 frames confirmed, 0 refused` seven minutes later. The bullet on that, including
  what is not established about the trigger, is under "Four things an install does".

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

Before that run, the push-only job (`42335665086`) had installed only the code package - the
146 MB themes `.deb` was uploaded on a tag only - with apt printing
`Recommended packages: xigmatek-connect-lcd-themes` and planning anyway, and smoke's
themes section saying SKIPPED because there was nothing installed to hash.  **That gap is
closed as of 0.4:** the themes `.deb` is built, uploaded and installed on every run, so the
runner is now the machine that reads the installed library back - manifest re-hash,
`themes.scan()`, all 23 selectable layouts painted, and `--mp4 NAME` resolving the clip each
layout declares (23 of 23, through four roots: the checkout's `media/`, the installed
`media/`, then the theme library in the checkout and in `/usr/share`).  The cost is stated in
the workflow's own comment: 146 MB up and down per run, for 14 days, in a repository that
already tracks 43 of those clips.  What it buys is the difference between a figure one bench
measured once and a figure CI re-measures on every push.

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

### What the 0.3 tree packages, measured

The 0.2 numbers above are the published ones.  The 0.3 tree packages something smaller,
because it no longer carries the vendor's `.thm` containers (docs/themes.md,
`themes/alpha/README.md`).  The pair below was built while the stanza still said
`0.3 UNRELEASED`; the stamped builds, and the runner's build of the same commit, are in the
section further down:

```
  dpkg-buildpackage -us -uc -b          exit 0, twice, 2026-11-08: 01:25:18-01:25:28
                                                 and 01:25:28-01:25:39, 10-11 s apart
  ls -l ../*.deb
      xigmatek-connect-lcd-themes_0.3_all.deb      79 844 056 B   (0.2: 146 137 362 B)
      (the code .deb's own byte count is deliberately absent: this file is installed
       inside that package, so any number written here moves the number it writes)
  dpkg-deb -f ... Installed-Size
      themes  83 111 KiB          (0.2: 147 854 KiB)
      code     5 782 KiB at those builds   (0.2: 5 578 KiB: the doc set grew, twice)
  dpkg -c xigmatek-connect-lcd-themes_0.3_all.deb
      114 members: 102 files + 12 directories
      grep -c '\.thm'                  0        (0.2: 30 members under thm/)
  lintian --tag-display-limit 0 --fail-on error,warning ../*.changes
      errors=0 warnings=0 infos=0 notes=0     (lintian v2.129.0ubuntu2.1, exit 0)
  cmp build1 build2                themes: clean        code: clean
```

102 files: 100 under `/usr/share/xigmalcd/themes/alpha` (the 98 the copy tool writes,
plus `manifest.json` and that directory's own `README.md`) and the `changelog.gz` and
`copyright` debhelper adds.  The manifest inside the themes package records 125 entries
over 98 paths and 27 `notRedistributed` rows, and `dpkg -x` answers the question the smoke
test asks in both directions: every installed file is named by the manifest, every named
file is installed, no surprises either way.  That is also what keeps a `.thm` from
drifting back into the package unnoticed - it would be an unnamed file, and the test fails
on an unnamed file.

The code package's own byte count is deliberately not quoted, for the reason the block
gives: this file is installed inside it, so any size written here moves the number it
writes.  Its Installed-Size went up 200 KiB from 0.2 for the same reason - the doc set grew
twice over, once with the `.thm` notes and once with these - and nothing about the modules
did.

Two builds of this tree, twenty seconds apart on this bench, came out byte-identical,
both packages - and the second run really is a run rather than a re-use of the first
stash: `dh_auto_configure`, `dh_auto_build`, the `override_dh_auto_install` recipe (its
`install -m 644 media/...` line is in both logs), `dh_install`, `dh_missing`,
`dh_compress` and both `dh_builddeb` steps appear in each, and each `dh_builddeb` names the
same two packages at the same sizes: the clock pin `debian/rules` documents above is doing
its job on this smaller tree too.

Two hashes are worth writing down, because only one of them survives an edit to this file.
The **payload** is the claim about the vendor's library, and a reader can take it from any
checkout that does not touch `themes/alpha/`:

```
dpkg -x xigmatek-connect-lcd-themes_0.3_all.deb d
cd d && find usr/share/xigmalcd -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum
```

which answers `46fb6f2da1effd1b4e82522df530cbef7bc08016ee0f9e15a44fa864f88a0b17` over
**100 files** and **85 034 557 B** - computed independently out of two separately built
packages an hour of editing apart, and identical.  The **container** - the `.deb` itself, `dpkg -c` output, byte
count and all - is deliberately *not* hashed here, and that
is not modesty: `changelog.gz` ships inside the themes package, and while the 0.3 stanza
was `UNRELEASED` every note written into it moved the container.  One earlier build of
this same library measured `4ce88e6d22b19a1c2ee7648da2c3677957d4b261750f8130d24d39dbb91980ee`
and 79 841 286 B; the run above, eight changelog edits later, is 79 844 056 B - the library
identical, `46fb6f2d…` in all four: four builds this sitting, four identical digests.  That
is the trap two paragraphs below records, met here
rather than in a reader's bug report.  Once the stanza is stamped and tagged, the container
hash belongs in the release body, computed from the uploaded files by the release job, where
it cannot drift: see `## The release` below for exactly that shape of record at 0.1 and 0.2.
The bench-versus-runner half was still open when that was written, and is closed now:
`v0.3` is tagged, the runner built it, and the comparison - one commit, two machines, both
packages, including the new smaller themes one - is the next section but one.

An earlier pair of builds of this tree did *not* compare clean, and the cause is worth
recording because it is the trap in this kind of check: `debian/changelog` had been
edited between the two runs, which changes `changelog.gz` and the `md5sums` inside
`control.tar`, so the two `ar` member size fields differ at byte 122 and 124 of an 80 MB
file.  A source change between two builds is the one variable the comparison is not
allowed to contain.

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
(`146 136 356 B`, `9fbcb6e06ab6642e406f37a99d3ff9e4093066cd7dd383ff1e20fd9f7597c82c`) -
and the tagged build, two sections below, is the first time that package has been
compared between two machines at all.

zstd needed no pinning and was measured so that this could be said: `-19 -T1` and
`-19 -T24` on the same 5 652 480 B tar produce byte-identical output
(`2142d58e9439ee41…`), and the two builds' `control.tar.zst` members are the same 3 634
bytes with the same frame header.

### The 0.2 tag, built here and built by the runner: the same bytes

```
two `dpkg-buildpackage -us -uc -b` runs of `v0.2` (commit `f627491`) on this bench, and
the release job's own build of the same tag on `ubuntu-26.04`, downloaded back:

  5 168 602 B  sha256 f8c0cd69c07e81d706f277e6302b3be988388335973ee6eb360d6e0d283bf21c  code
146 137 362 B  sha256 db4362c2ce1a01717459997f8c85e70d6866f665ef7af825351b83d0c3451b19  themes

  build1 vs build2 here:  `cmp` clean, both packages
  the bench vs the runner: `cmp` clean, both packages - 5 168 602 B and 146 137 362 B
```

That is the claim the whole mechanism exists to make, and it holds for both files: the
146 MB themes package had never been compared across machines before, because it is only
uploaded on a tag. The hashes in the release body below are therefore something a reader
can produce themselves - `dpkg-buildpackage -us -uc -b` on Ubuntu 26.04 with dpkg 1.23.7
and the debhelper/dh-python/python3 versions named at the top of this file, then
`sha256sum ../xigmatek-connect-lcd_*_all.deb`, and the number matches. A different dpkg or
libzstd can produce a different container around the same files, which is the honest edge
of the statement; `md5sums` inside the package is what travels between toolchains.

One more measured thing from this cycle, about lintian rather than about bytes: the first
draft of the 0.2 changelog entry drew `debian-changelog-line-too-long` four times - once
per long line, per binary package, because both packages carry the same `changelog.gz`.
The lines were wrapped to 80 columns instead of being overridden; the overrides file still
holds only the three `no-manual-page` lines and the one override that explains itself.

### The published v0.2 release

[`v0.2`](https://github.com/tamer-hassan/xigmatek-connect-lcd/releases/tag/v0.2): an
annotated tag object (`9a164f3`) on commit `f627491`, published by run
[`42341460379`](https://github.com/tamer-hassan/xigmatek-connect-lcd/actions/runs/42341460379)
- all four jobs green there, the install job taking both packages this time
(`Setting up xigmatek-connect-lcd-themes (0.2)` then `Setting up xigmatek-connect-lcd
(0.2)`, `159 MB`, the same `Created symlink '/etc/systemd/user/default.target.wants/…'`
line as the bench), and `debian/tests/smoke` printing `all installed checks passed` with
`manifest 152/152 files hashed clean` and the document section
(`11 markdown files … none compressed`, `33 links … all resolving`) on a machine that had
never seen this tree.

| asset | bytes | sha256 |
|---|---|---|
| `xigmatek-connect-lcd_0.2_all.deb` | 5 168 602 | `f8c0cd69c07e81d706f277e6302b3be988388335973ee6eb360d6e0d283bf21c` |
| `xigmatek-connect-lcd-themes_0.2_all.deb` | 146 137 362 | `db4362c2ce1a01717459997f8c85e70d6866f665ef7af825351b83d0c3451b19` |
| `xigmatek-connect-lcd_0.2_amd64.changes` | 4 106 | `fdb62b76f0361b46ac33ccf88443e9db7459c913a631af5ea2312c98130d5299` |
| `xigmatek-connect-lcd_0.2_amd64.buildinfo` | 8 636 | `d4b2f8966b720654f561c6247578bd31ddd39ef4bda7d3e8aa21b0f4df089f48` |

The release body is generated from those bytes by the job that uploads them, and it now
says in words what the section above proves: that the hashes are reproducible from the
source, and that `docs/packaging.md` - this file - keeps the measurement.

One thing to be exact about, because a document about a file it sits inside cannot quote
that file's own bytes: this table was committed *after* `v0.2`, so the published
`.deb` carries a version of this page without the table. The comparison above is between
builds of `f627491`, the tagged tree, which is the tree the release job built - and it is
why the size of each `.deb` in the table at the top of this file stays rounded.

### The 0.3 tag, built here and built by the runner: the same bytes, both packages

```
tag v0.3               annotated tag object `fd2a2ce…`, on commit `954d14d…` - the
                       `main` tip at the moment of tagging
stanza                 `xigmatek-connect-lcd (0.3) resolute; urgency=medium`, stamped
                       `Sun, 08 Nov 2026 01:57:03 +0200`; it becomes
                       `/usr/share/doc/xigmatek-connect-lcd/changelog.gz` in the code package,
                       and that file is what stopped drifting once the tag existed
runner                 one job per ref: `CI: push [v0.3]`, suite, doc/manifest/link gates,
                       build, lintian, install + `debian/tests/smoke`, then release.
                       4 jobs green, published 2026-11-08T00:07:11Z, run 42427996701
bench, same commit     two `dpkg-buildpackage -us -uc -b` in separate build areas, so neither
                       run re-uses the other's stash: 01:58:24-01:58:42 and 01:58:42-01:58:59
```

Then the comparison the 0.2 section describes, done again with the tag pointing at one
commit both machines could check out:

```
xigmatek-connect-lcd_0.3_all.deb
  runner     5 230 088 B  sha256 d6fcc19cb89b9dfb67e00e6cd86616f281a412526662dad1c612adcad96cf668
  bench      5 230 088 B  same digest, and `cmp` against either of the two bench builds: clean
xigmatek-connect-lcd-themes_0.3_all.deb
  runner    79 843 948 B  sha256 1c217e3143e118456f9f75f0b7f51c0cce841a6f8f8ce46bddf5dce7070ca2c2
  bench     79 843 948 B  same digest, and `cmp` clean
payload digest, read out of `dpkg -x` of any of them:
  46fb6f2da1effd1b4e82522df530cbef7bc08016ee0f9e15a44fa864f88a0b17   over 100 files / 85 034 557 B
```

The payload digest is the same one the `0.3 UNRELEASED` pair two sections above printed, so
four builds - two here before the stanza was stamped, two here after, and the runner's -
all carry an identical vendor library.

Two things make this pair more interesting than the 0.2 one, and both are about the themes
package rather than the code:

* Its payload changed by 66 MB on the way here: `146 137 362 B` to `79 843 948 B`, installed
  size `147 854 KiB` to `83 111 KiB`, because the 27 `.thm` containers are no longer shipped
  and their decrypted content is.  A clock pin that survived a documentation edit at 0.2 has
  to survive a payload swap too, and the byte-for-byte agreement between a 4-core runner and
  a 24-core bench is what says it did.
* The runner's install job read that package back and printed the census this file's
  "documentation, as an installed thing" section asks for, for 0.3 rather than 0.2:
  `xigmatek-connect-lcd-themes 0.3 all installed-size 83111 KB`, `11 markdown files … none
  compressed`, `43 links inside the doc set, all resolving; 3 image link(s) repo-only by
  design; 3 pointer(s) into the source`, `2 kept log(s)`, `manifest 125/125 files hashed
  clean under /usr/share/xigmalcd/themes/alpha`, `all installed checks passed`, and
  `Need to get 14.7 MB … 58.1 MB of additional disk space`.  Against 0.2's numbers: links up
  from 33 as the doc set grew, repo-only image links down from 8 to 3 because the GIFs went
  and the previews README links are now GitHub CDN URLs rather than paths, kept logs up from
  1 to 2, and hashed files down from 152 to 125 - exactly the 27 `.thm` rows, which are
  `notRedistributed` entries in the manifest now instead of files on disk.
* The panel was absent again, which the install job says out loud: `the panel is not
  present: everything that can be checked without talking to it is checked`.  Same sentence
  as 0.1 and 0.2, same meaning: the CI box has no such device, and no test pretends to
  judge the glass from a build.

The recipe, so it can be repeated rather than taken on trust - and note that
`gh release download` has no `--dest`; it writes into the current directory:

```
mkdir -p /tmp/verify && cd /tmp/verify
gh release download v0.3 --repo tamer-hassan/xigmatek-connect-lcd --pattern '*.deb' --clobber
sha256sum *.deb

git clone https://github.com/tamer-hassan/xigmatek-connect-lcd src && cd src
git worktree add --detach /tmp/b1 v0.3 && git worktree add --detach /tmp/b2 v0.3
(cd /tmp/b1 && dpkg-buildpackage -us -uc -d -i -I)     # -d: this bench is not a clean chroot
(cd /tmp/b2 && dpkg-buildpackage -us -uc -d -i -I)     # (docs/packaging.md above)
cmp /tmp/b1/*.deb /tmp/verify/*.deb && cmp /tmp/b1/*.deb /tmp/b2/*.deb
```

The same caveat as at 0.2, stated before it bites anyone: this section was committed
*after* `v0.3`, so the published code `.deb` carries an earlier copy of this file.  The
byte counts in the table below are read off the published assets, not off a build of
`HEAD`, and a build of any later commit differs by exactly this page.  The payload digest
is the number that survives an edit here.

### The published v0.3 release

* **v0.3**: <https://github.com/tamer-hassan/xigmatek-connect-lcd/releases/tag/v0.3>,
  published 2026-11-08T00:07:11Z by run 42427996701, and it is the release GitHub marks
  **Latest** - so `gh release download --latest` now answers 0.3, which is what the Quick
  start in README runs.

| file | B | sha256 |
|---|---|---|
| `xigmatek-connect-lcd_0.3_all.deb` | 5 230 088 | `d6fcc19cb89b9dfb67e00e6cd86616f281a412526662dad1c612adcad96cf668` |
| `xigmatek-connect-lcd-themes_0.3_all.deb` | 79 843 948 | `1c217e3143e118456f9f75f0b7f51c0cce841a6f8f8ce46bddf5dce7070ca2c2` |
| `xigmatek-connect-lcd_0.3_amd64.changes` | 19 692 | `dbd659cc8f87afbb762036a15cfdaeb65903ab7804e8b5a677171654d12d5184` |
| `xigmatek-connect-lcd_0.3_amd64.buildinfo` | 8 633 | `b18b2b3e07b1d131135cf759d7cf7aa77d4153d75682a5ed0648d4ce52593e2f` |

The body the job wrote for the release quotes the two `.deb` digests, the lintian summary,
and the sentence the section above proves: that a build of this tag on the same distro and
dpkg version gives those same bytes.  Comparing the two published bodies, `v0.2` and `v0.3`,
says exactly what changed between them and no more: the two asset rows, the two run links,
and one deleted line.  That line is the bug the tag commit fixed - the notes step is a
chain of `echo` lines, and one of them was the tail of an older wording of the closing
paragraph, so the v0.2 body ended with `carry those bench-log-backed claims.` followed by a
stray `claims, each with the bench log it was read out of.`  The v0.3 body's tail is clean.
The published v0.2 body is left as published: the body is the record of what that job did,
and rewriting it after the fact would make the release stop matching its own run.  The
repair would be one line - `gh release edit v0.2 --notes-file <(gh release view v0.2 --json
body --jq .body | grep -v '^claims, each with the bench log')` - and it was tried as a dry
run before writing this sentence: that pipeline differs from the published body by exactly
that one line and nothing else.
