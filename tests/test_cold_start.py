"""The cold-start contract: an agent given only the README must succeed, or
fail in a way it can act on.

This suite exists because of a measured failure, not a hypothetical one. On
2026-07-31 a cold-boot probe ran the three character refs an agent actually
produces. A public character derived correctly. The other three — a private
sheet, a missing id, a malformed ref — each produced a fifteen-line Python
traceback and **exit code 1**.

Exit 1 is documented as *"lint findings — the sheet looks inconsistent."* So a
permission error was returning the code that means "this sheet has
inconsistencies", and an agent obeying the published contract would read a
private character as a dirty one and carry on. That is worse than crashing.

Network-touching checks are marked and skipped when offline, so this suite is
useful in CI and on a plane.
"""

import io
import json
import os
import socket
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from charactercheck import errors  # noqa: E402
from charactercheck.cli import main  # noqa: E402


def _online():
    try:
        socket.getaddrinfo("character-service.dndbeyond.com", 443)
        return True
    except OSError:
        return False


ONLINE = _online()
needs_net = unittest.skipUnless(ONLINE, "no network")


def run(argv):
    """Run the CLI, capturing stdout and the exit code."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


class TestFailuresAreActionable(unittest.TestCase):
    """Every failure is typed, carries an action, and exits 3."""

    def test_every_error_kind_has_a_nonempty_action(self):
        for factory in (errors.not_public, errors.not_found, errors.bad_ref,
                        errors.rate_limited):
            e = factory("ref")
            self.assertTrue(e.action.strip(), f"{e.kind} has no action")
            self.assertEqual(e.exit_code, errors.EXIT_FETCH)

    def test_error_payload_is_machine_matchable(self):
        d = errors.not_public("x").as_dict()
        for key in ("ok", "error", "message", "action", "exit_code"):
            self.assertIn(key, d)
        self.assertFalse(d["ok"])
        self.assertEqual(d["error"], "not_public")

    def test_fetch_failures_do_not_collide_with_the_lint_lane(self):
        """Exit 1 means 'the sheet disagrees with itself'. A permission error
        is not that, and must never borrow its code."""
        self.assertNotIn(errors.EXIT_FETCH, (0, 1, 2))

    def test_private_sheet_advice_never_asks_for_credentials(self):
        action = errors.not_public("x").action.lower()
        for banned in ("password", "cookie", "token", "log in", "login",
                       "credential"):
            if banned == "credential":
                # the sentence *promises* we never ask for credentials
                self.assertIn("never asks for credentials", action)
                continue
            self.assertNotIn(banned, action)

    def test_private_sheet_advice_names_both_supported_answers(self):
        action = errors.not_public("x").action.lower()
        self.assertIn("public", action)      # make it public
        self.assertIn("file", action)        # or pass a saved JSON file

    def test_bad_ref_needs_no_network(self):
        code, out = run(["derive", "notanumber"])
        self.assertEqual(code, errors.EXIT_FETCH)
        self.assertEqual(json.loads(out)["error"], "bad_ref")


class TestNoTracebackEscapes(unittest.TestCase):
    """A caller that receives a Python traceback cannot act on it."""

    def _assert_clean(self, code, out, kind):
        self.assertEqual(code, errors.EXIT_FETCH)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("File \"", out)
        self.assertEqual(json.loads(out)["error"], kind)

    def _http(self, status):
        return urllib.error.HTTPError("u", status, "err", {}, None)

    def test_403_is_not_public(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._http(403)):
            self._assert_clean(*run(["derive", "12345"]), kind="not_public")

    def test_404_is_not_found(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._http(404)):
            self._assert_clean(*run(["derive", "12345"]), kind="not_found")

    def test_429_is_rate_limited(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._http(429)):
            self._assert_clean(*run(["derive", "12345"]), kind="rate_limited")

    def test_500_is_upstream_not_the_callers_fault(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._http(503)):
            self._assert_clean(*run(["derive", "12345"]), kind="upstream")

    def test_no_network_is_diagnosed_as_network(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("no route to host")):
            self._assert_clean(*run(["derive", "12345"]), kind="network")

    def test_garbage_json_is_diagnosed(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=io.BytesIO(b"<html>nope</html>")):
            self._assert_clean(*run(["derive", "12345"]), kind="bad_json")

    def test_response_without_data_object_is_diagnosed(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=io.BytesIO(b'{"nope": 1}')):
            self._assert_clean(*run(["derive", "12345"]), kind="bad_json")


class TestDoctor(unittest.TestCase):
    """One command that turns 'it doesn't work' into a diagnosis."""

    def test_doctor_runs_without_a_ref(self):
        code, out = run(["doctor", "--json"])
        self.assertIn(code, (0, errors.EXIT_FETCH))
        res = json.loads(out)
        names = [c["check"] for c in res["checks"]]
        self.assertIn("python", names)

    def test_doctor_reports_the_action_on_the_failing_check(self):
        with mock.patch("charactercheck.engine.fetch",
                        side_effect=errors.not_public("x")):
            res = errors.doctor("12345")
        bad = [c for c in res["checks"] if not c["ok"]]
        self.assertTrue(bad)
        self.assertTrue(bad[-1]["action"].strip())
        self.assertFalse(res["ok"])

    def test_doctor_text_output_is_readable(self):
        with mock.patch("charactercheck.engine.fetch",
                        side_effect=errors.not_public("x")):
            text = errors.render_doctor(errors.doctor("12345"))
        self.assertIn("FAIL", text)
        self.assertIn("->", text)

    def test_a_403_during_the_network_probe_still_counts_as_reachable(self):
        """403/404 from the probe means the service ANSWERED, which is what
        the network check is actually testing."""
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.HTTPError("u", 403, "f", {}, None)):
            res = errors.doctor()
        net = [c for c in res["checks"] if c["check"] == "network"]
        if net:
            self.assertTrue(net[0]["ok"])


class TestReadmeContract(unittest.TestCase):
    """The user story is 'read the README and use it', so the README must
    actually carry the contract it promises."""

    def setUp(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md")) as f:
            self.readme = f.read()

    def test_readme_documents_exit_3(self):
        self.assertIn("3", self.readme)
        self.assertIn("could not retrieve the sheet", self.readme.lower())

    def test_readme_documents_every_error_kind(self):
        for kind in ("not_public", "not_found", "bad_ref", "network",
                     "rate_limited", "bad_json", "upstream"):
            self.assertIn(kind, self.readme, f"README omits {kind}")

    def test_readme_names_the_private_sheet_answer(self):
        low = self.readme.lower()
        self.assertIn("character privacy", low)
        self.assertIn("never asks for credentials", low)

    def test_readme_leads_with_the_two_command_quickstart(self):
        head = self.readme[:self.readme.index("## Why provenance")
                           if "## Why provenance" in self.readme
                           else len(self.readme)]
        self.assertIn("pip install charactercheck", head)
        self.assertIn("charactercheck derive", head)
        self.assertIn("doctor", head)


@needs_net
class TestLiveUserStory(unittest.TestCase):
    """The literal user story, against the real service."""

    PUBLIC = "https://www.dndbeyond.com/characters/150991647"

    def test_a_public_character_derives(self):
        code, out = run(["derive", self.PUBLIC])
        self.assertIn(code, (0, 1, 2), "0/1/2 all mean 'you have usable output'")
        d = json.loads(out)
        self.assertIn("identity", d)
        self.assertTrue(d["identity"]["name"])

    def test_a_private_character_is_actionable_not_a_crash(self):
        code, out = run(["derive", "https://www.dndbeyond.com/characters/1"])
        self.assertEqual(code, errors.EXIT_FETCH)
        self.assertNotIn("Traceback", out)
        self.assertEqual(json.loads(out)["error"], "not_public")


if __name__ == "__main__":
    unittest.main()
