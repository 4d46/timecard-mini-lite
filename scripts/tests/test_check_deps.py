"""Tests for scripts/check-deps. Run: python3 -m unittest discover -s scripts/tests

Each test pins down a way the local tooling can drift from the lock without
anyone noticing; if the check stops spotting one, a test here fails.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
_loader = importlib.machinery.SourceFileLoader("check_deps", str(ROOT / "scripts" / "check-deps"))
_spec = importlib.util.spec_from_loader("check_deps", _loader)
cd = importlib.util.module_from_spec(_spec)
_loader.exec_module(cd)

LOCK = """\
#
#    pip-compile --generate-hashes --output-file=requirements.txt requirements.in
#
ansible-core==2.21.5 \\
    --hash=sha256:aaaa \\
    --hash=sha256:bbbb
    # via ansible
MarkupSafe==3.0.4 \\
    --hash=sha256:cccc
    # via jinja2
"""

WANT_COLLECTIONS = {"community.general": "13.5.0"}
USER_PATH = "/home/example/.ansible/collections/ansible_collections"
BUNDLED_PATH = "/opt/example/site-packages/ansible_collections"


def mismatches(**overrides):
    """find_mismatches with a fully matching baseline, changed by overrides."""
    args = dict(
        want_python="3.14.8", have_python="3.14.8",
        lock=cd.parse_lock(LOCK),
        installed={"ansible-core": "2.21.5", "markupsafe": "3.0.4"},
        want_collections=WANT_COLLECTIONS,
        have_collections={"community.general": ("13.5.0", USER_PATH)},
        ansible_interpreter="/opt/example/bin/python3.14",
        this_interpreter="/opt/example/bin/python3.14",
    )
    args.update(overrides)
    return cd.find_mismatches(**args)


class ParseTests(unittest.TestCase):
    def test_lock_reads_pins_and_skips_hash_and_comment_lines(self):
        self.assertEqual(cd.parse_lock(LOCK), {"ansible-core": "2.21.5", "markupsafe": "3.0.4"})

    def test_real_lock_parses_every_pin(self):
        # Every 'name==version' line in the repo's own lock is picked up, so a
        # format change by pip-compile can't silently shrink what's checked.
        text = (ROOT / "requirements.txt").read_text()
        expected = sum(1 for line in text.splitlines() if "==" in line and not line.startswith(" "))
        self.assertEqual(len(cd.parse_lock(text)), expected)
        self.assertIn("ansible-core", cd.parse_lock(text))

    def test_tool_versions_python(self):
        self.assertEqual(cd.parse_tool_versions("nodejs 22.1.0\npython 3.14.8  # pinned\n"), "3.14.8")
        self.assertIsNone(cd.parse_tool_versions("nodejs 22.1.0\n"))

    def test_collection_versions_compare_as_strings(self):
        # An unquoted two-part pin ('version: 13.5') loads as a float; it must
        # still compare equal to galaxy's string "13.5".
        data = {"collections": [{"name": "ansible.posix", "version": "2.2.2"},
                                {"name": "community.general", "version": 13.5}]}
        self.assertEqual(cd.parse_collections(data),
                         {"ansible.posix": "2.2.2", "community.general": "13.5"})

    def test_ansible_interpreter_from_version_output(self):
        out = ("ansible [core 2.21.5]\n"
               "  python version = 3.14.8 (main, Oct  4 2026) [Clang 21] (/opt/example/bin/python3.14)\n")
        self.assertEqual(cd.ansible_python(out), "/opt/example/bin/python3.14")


class EffectiveCollectionTests(unittest.TestCase):
    def test_first_path_on_search_order_wins(self):
        galaxy = {
            USER_PATH: {"community.general": {"version": "13.5.0"}},
            BUNDLED_PATH: {"community.general": {"version": "12.6.1"}},
        }
        self.assertEqual(cd.effective_collections(galaxy)["community.general"], ("13.5.0", USER_PATH))

    def test_bundled_copy_used_when_pinned_copy_missing(self):
        galaxy = {USER_PATH: {}, BUNDLED_PATH: {"community.general": {"version": "12.6.1"}}}
        self.assertEqual(cd.effective_collections(galaxy)["community.general"], ("12.6.1", BUNDLED_PATH))


class MismatchTests(unittest.TestCase):
    def test_everything_matching_passes(self):
        self.assertEqual(mismatches(), [])

    def test_stale_package_after_lock_update(self):
        # The case this exists for: a PR moved the lock, 'make deps' wasn't run.
        problems = mismatches(installed={"ansible-core": "2.20.9", "markupsafe": "3.0.4"})
        self.assertEqual(problems, ["ansible-core: installed 2.20.9, locked 2.21.5"])

    def test_missing_package(self):
        problems = mismatches(installed={"ansible-core": "2.21.5"})
        self.assertEqual(problems, ["markupsafe: not installed, locked 3.0.4"])

    def test_package_names_compare_normalised(self):
        # The lock and installed metadata spell names differently ('MarkupSafe'
        # vs 'markupsafe', 'ruamel.yaml' vs 'ruamel-yaml'); both sides go
        # through canonical(), so a spelling difference isn't a "missing" package.
        self.assertEqual(cd.canonical("MarkupSafe"), "markupsafe")
        self.assertEqual(cd.canonical("ruamel.yaml"), cd.canonical("ruamel_yaml"))
        self.assertEqual(cd.canonical("ruamel.yaml"), "ruamel-yaml")

    def test_wrong_python(self):
        self.assertEqual(mismatches(have_python="3.12.15"),
                         ["python: running 3.12.15, .tool-versions wants 3.14.8"])

    def test_ansible_on_a_different_interpreter(self):
        problems = mismatches(ansible_interpreter="/usr/local/bin/python3.12")
        self.assertEqual(len(problems), 1)
        self.assertIn("ansible runs on /usr/local/bin/python3.12", problems[0])

    def test_interpreter_symlinks_count_as_the_same(self):
        with mock.patch.object(cd.os.path, "realpath", side_effect=lambda p: "/opt/example/bin/python3.14"):
            self.assertEqual(mismatches(this_interpreter="/opt/example/bin/python3"), [])

    def test_shadowed_collection(self):
        # Pinned copy missing, so Ansible falls back to the older bundled one.
        problems = mismatches(have_collections={"community.general": ("12.6.1", BUNDLED_PATH)})
        self.assertEqual(problems, [f"community.general: using 12.6.1 ({BUNDLED_PATH}), pinned 13.5.0"])

    def test_missing_collection(self):
        self.assertEqual(mismatches(have_collections={}),
                         ["community.general: not installed, pinned 13.5.0"])


class MainTests(unittest.TestCase):
    def run_main(self, argv, env=None):
        err, out = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env or {}, clear=False), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            code = cd.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_override_skips_and_warns(self):
        code, _, err = self.run_main(["check-deps"], {"SKIP_DEPS_CHECK": "1"})
        self.assertEqual(code, 0)
        self.assertIn("WARNING: SKIP_DEPS_CHECK=1", err)

    def test_override_needs_exactly_1(self):
        # SKIP_DEPS_CHECK=0 must not skip. With no files to read, a real check
        # stops at the first read (exit 2), whereas a skip would return 0.
        with mock.patch("builtins.open", side_effect=FileNotFoundError(2, "x", ".tool-versions")):
            code, _, err = self.run_main(["check-deps"], {"SKIP_DEPS_CHECK": "0"})
        self.assertEqual(code, 2)
        self.assertNotIn("WARNING", err)

    def test_mismatch_exits_1_with_fix_and_override_hint(self):
        with mock.patch.object(cd, "find_mismatches", return_value=["ansible-core: installed 2.20.9, locked 2.21.5"]), \
                mock.patch.object(cd, "run", return_value=None):
            code, _, err = self.run_main(["check-deps"], {"SKIP_DEPS_CHECK": ""})
        self.assertEqual(code, 1)
        self.assertIn("ansible-core: installed 2.20.9, locked 2.21.5", err)
        self.assertIn("make deps", err)
        self.assertIn("SKIP_DEPS_CHECK=1", err)

    def test_unknown_argument(self):
        self.assertEqual(self.run_main(["check-deps", "--bogus"])[0], 2)


if __name__ == "__main__":
    unittest.main()
