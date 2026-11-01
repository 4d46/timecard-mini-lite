"""Tests for the Makefile's help. Run: python3 -m unittest discover -s scripts/tests

'make help' only lists targets that carry a '## description', so a new target
added without one silently vanishes from the list; and without .DEFAULT_GOAL a
plain 'make' runs whatever target happens to come first (it used to be deploy).
"""

import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET = re.compile(r"^([a-zA-Z0-9][a-zA-Z0-9_-]*):(?!=)")


def make(*args):
    return subprocess.run(["make", "-C", str(ROOT), *args],
                           capture_output=True, text=True, check=True).stdout


def public_targets():
    """(name, line) for every target a user is meant to run (not _private)."""
    for line in (ROOT / "Makefile").read_text().splitlines():
        m = TARGET.match(line)
        if m:
            yield m.group(1), line


class MakeHelpTests(unittest.TestCase):
    def test_every_public_target_has_a_description(self):
        missing = [name for name, line in public_targets() if "## " not in line]
        self.assertEqual(missing, [], "add '## description' to these targets so 'make help' lists them")

    def test_help_lists_every_public_target(self):
        listed = {line.split()[0] for line in make("help").splitlines() if line.startswith("  ")}
        self.assertTrue({name for name, _ in public_targets()} <= listed)

    def test_help_hides_private_targets(self):
        self.assertNotIn("_inject", make("help"))

    def test_plain_make_shows_help_and_never_runs_a_playbook(self):
        # -n prints what the default goal would run without running it. Match
        # the commands themselves: the help text mentions ansible-playbook too.
        dry = make("-n")
        self.assertIn("awk", dry)
        self.assertNotIn("ansible-playbook -i", dry)
        self.assertNotIn("op inject -f", dry)


if __name__ == "__main__":
    unittest.main()
