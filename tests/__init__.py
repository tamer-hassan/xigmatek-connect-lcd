# The offline checks, as ordinary tests.
#
# This package replaces `tools/selftest.sh` (13,869 lines of shell-and-heredoc, deleted in this
# cycle).  The rule that made the old file grow is the rule this package does not follow: a test
# here asserts something about **code**, and never that a page contains a sentence.  Where the old
# suite checked that a figure quoted in `docs/` equalled what this machine measured, the figure
# now comes from the command that prints it, and the page names the command instead of the number.
#
# Run:  python3 -m unittest discover -s tests          (quiet)
#       python3 -m unittest discover -s tests -v       (one line per check)
#
# Nothing here opens a serial port.  `tests/fixtures.py` keeps that honest: the panel is always a
# recording stub, the dry-run door is always used for rendering to disk, and the user's real
# settings root is replaced by a temporary one.
