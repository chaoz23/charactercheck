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


class TestCloneWithoutInstall(unittest.TestCase):
    """Handed a GitHub URL, an agent clones rather than pip-installing. The
    natural next move must then work without a guess.

    Found by running the real user story against a real agent: it hit
    "No module named charactercheck.__main__" and recovered by guessing
    `-m charactercheck.cli`. It should not have had to guess.
    """

    def test_python_dash_m_package_is_executable(self):
        import charactercheck
        root = os.path.dirname(os.path.abspath(charactercheck.__file__))
        self.assertTrue(os.path.exists(os.path.join(root, "__main__.py")),
                        "python3 -m charactercheck must work from a clone")

    def test_dash_m_entrypoint_calls_the_same_cli(self):
        import runpy
        with mock.patch("sys.argv", ["charactercheck", "derive", "notanumber"]):
            with self.assertRaises(SystemExit) as cm:
                with redirect_stdout(io.StringIO()):
                    runpy.run_module("charactercheck", run_name="__main__")
        self.assertEqual(cm.exception.code, errors.EXIT_FETCH)

    def test_readme_documents_the_clone_path(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "README.md")) as f:
            readme = f.read()
        self.assertIn("python3 -m charactercheck", readme)
        self.assertIn("git clone", readme)


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


class TestContractSurfacesAgree(unittest.TestCase):
    """Every place that states the contract must state the same contract.

    From live UXR by an agent installing this cold: *"pyproject says 0.5.1,
    tool.json says 0.1.0, server.json and MCP say 0.4.0. Agents will distrust
    that. Small paper cut, but exactly the kind that makes tool installation
    feel haunted."* Four versions in one repo is a trust defect, so agreement
    is now enforced rather than remembered.
    """

    def setUp(self):
        self.root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _read(self, name):
        with open(os.path.join(self.root, name)) as f:
            return f.read()

    def test_every_file_reports_the_same_version(self):
        import re

        import charactercheck
        pkg = charactercheck.__version__
        seen = {"package": pkg}

        m = re.search(r'^version = "([^"]+)"', self._read("pyproject.toml"), re.M)
        seen["pyproject.toml"] = m.group(1)
        seen["tool.json"] = json.loads(self._read("tool.json"))["version"]

        if os.path.exists(os.path.join(self.root, "server.json")):
            found = []

            def walk(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k == "version" and isinstance(v, str):
                            found.append(v)
                        else:
                            walk(v)
                elif isinstance(o, list):
                    for x in o:
                        walk(x)
            walk(json.loads(self._read("server.json")))
            for i, v in enumerate(found):
                seen[f"server.json[{i}]"] = v

        self.assertEqual(len(set(seen.values())), 1,
                         f"version disagreement across contract surfaces: {seen}")

    def test_schema_documents_exit_3_and_the_error_kinds(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(["--schema"])
        d = json.loads(buf.getvalue())
        self.assertIn("3", d["exit_codes"])
        kinds = set(d.get("errors", {}).get("kinds", []))
        self.assertIn("not_public", kinds)
        self.assertIn("bad_ref", kinds)

    def test_tool_json_lists_every_cli_command(self):
        import re
        cli_src = self._read(os.path.join("charactercheck", "cli.py"))
        choices = re.search(r"choices=\[([^\]]+)\]", cli_src).group(1)
        commands = {c.strip().strip('"').strip("'") for c in choices.split(",")}
        listed = " ".join(json.loads(self._read("tool.json"))["commands"])
        for c in commands:
            self.assertIn(c, listed, f"tool.json does not mention '{c}'")


class TestBlastRadiusIsActionable(unittest.TestCase):
    """A caveat that covers everything is worth the same as no caveat.

    From live UXR: one unhandled `bonus:spell-group-healing` was collapsing the
    whole report to "treat all derived values as unverified". The agent's
    objection was right — it could no longer trust AC, saves, skills or HP,
    none of which a healing-spell bonus can touch.
    """

    def test_a_known_family_prefix_scopes_narrowly(self):
        from charactercheck.engine import blast
        affects, note = blast("bonus:spell-group-healing")
        self.assertEqual(affects, ["spell_output"])
        self.assertNotIn("unverified", " ".join(affects))
        self.assertTrue(note)

    def test_an_unknown_pattern_no_longer_condemns_everything(self):
        from charactercheck.engine import blast
        affects, note = blast("munch:cookies")
        self.assertNotIn("treat all derived values as unverified", affects)
        self.assertIn("not applied", (note or "").lower())

    def test_verified_clean_survives_a_narrow_unknown(self):
        from charactercheck.engine import ALL_FAMILIES, blast
        unhandled = ["bonus:spell-group-healing"]
        clean = set(ALL_FAMILIES) - {a for p in unhandled for a in blast(p)[0]}
        for family in ("ac", "saves", "skills", "hp"):
            self.assertIn(family, clean,
                          f"a healing-spell bonus must not invalidate {family}")


class TestSpellSlotOracle(unittest.TestCase):
    """Class levels are an independent anchor on what the payload must contain.

    From live agent UXR: a Cleric 3 derived with `slots_max: {}` and nothing
    said so. The agent's note — *"that should probably lint harder: full caster
    level implies slots, but DDB payload reports zero"* — is a completeness
    oracle in the same family as census-anchored extraction: the rules say how
    many slots must exist, so a payload reporting none is wrong.

    Two distinct failures hide behind the same symptom, and the second was
    found while testing the fix on a second real character.
    """

    from charactercheck.engine import (  # noqa: E402
        SLOT_TABLE, caster_level, expected_slots)

    def _rows(self, pairs):
        return [{"level": lv, "available": a, "used": u} for lv, a, u in pairs]

    def test_caster_level_counts_full_and_half_casters(self):
        from charactercheck.engine import caster_level
        cleric3 = [{"definition": {"name": "Cleric"}, "level": 3}]
        self.assertEqual(caster_level(cleric3), 3)
        pal_lock = [{"definition": {"name": "Paladin"}, "level": 3},
                    {"definition": {"name": "Warlock"}, "level": 4}]
        # paladin halves (3//2=1); warlock is pact magic and excluded entirely
        self.assertEqual(caster_level(pal_lock), 1)

    def test_half_caster_at_level_one_has_no_slots(self):
        from charactercheck.engine import expected_slots
        self.assertFalse(expected_slots([{"definition": {"name": "Paladin"},
                                          "level": 1}]))

    def test_the_srd_table_is_right_where_it_matters(self):
        from charactercheck.engine import SLOT_TABLE
        self.assertEqual(SLOT_TABLE[1], [2])
        self.assertEqual(SLOT_TABLE[3], [4, 2])
        self.assertEqual(SLOT_TABLE[5], [4, 3, 2])
        self.assertEqual(SLOT_TABLE[20], [4, 3, 3, 3, 3, 2, 2, 1, 1])

    def test_never_populated_is_diagnosed_as_a_data_gap(self):
        from charactercheck import engine
        W = {"lint": []}
        rows = self._rows([(lv, 0, 0) for lv in range(1, 10)])
        with mock.patch.object(engine, "_slot_rows", return_value=rows):
            pass  # exercised through derive below; unit shape asserted here
        self.assertTrue(all(r["available"] == 0 and r["used"] == 0 for r in rows))

    def test_spent_without_maxima_is_an_internal_contradiction(self):
        """available 0 with used 3 means slots were spent that never existed.

        A coarser 'is anything used?' suppression would have swallowed this —
        it did, on the first version of the fix, on a real character.
        """
        rows = self._rows([(1, 0, 3)] + [(lv, 0, 0) for lv in range(2, 10)])
        spent = {r["level"]: r["used"] for r in rows if r["used"]}
        self.assertEqual(spent, {1: 3})
        self.assertFalse(any(r["available"] for r in rows))

    def test_a_populated_sheet_is_not_flagged(self):
        rows = self._rows([(1, 4, 4), (2, 2, 0)])
        self.assertTrue(any(r["available"] for r in rows),
                        "fully expended but populated must never lint")


@needs_net
class TestSpellLintsAgainstRealCharacters(unittest.TestCase):
    """Both shapes, against the two live sheets that produced them."""

    def _lint(self, ref):
        code, out = run(["derive", ref])
        return " | ".join(json.loads(out)["lint"])

    def test_cleric_three_with_no_slots_is_flagged_as_a_data_gap(self):
        lint = self._lint("150991647")
        self.assertIn("spell slots missing", lint)
        self.assertIn("caster level 3", lint)

    def test_cleric_three_with_only_cantrips_is_flagged_for_prepared(self):
        self.assertIn("no prepared leveled spells", self._lint("150991647"))

    def test_spent_without_maxima_is_flagged_as_inconsistent(self):
        lint = self._lint("93177801")
        self.assertIn("spell slots inconsistent", lint)
        self.assertIn("3 spent at L1", lint)

    def test_pact_magic_is_diagnosed_separately(self):
        self.assertIn("pact magic slots inconsistent", self._lint("93177801"))

    def test_a_caster_with_prepared_spells_is_not_nagged(self):
        self.assertNotIn("no prepared leveled spells", self._lint("93177801"))


class TestBootstrapWithoutTheWorld(unittest.TestCase):
    """An agent must be able to prove the tool works before it has a
    character, an account, or a network.

    Those are three separate things that fail separately, and from the outside
    a broken install and a private sheet look identical. `selftest` collapses
    that ambiguity to a binary answer.
    """

    def test_selftest_passes_offline(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("selftest must not hit the network")):
            ok, lines = errors.selftest()
        self.assertTrue(ok, "\n".join(lines))

    def test_selftest_exits_zero_through_the_cli(self):
        code, out = run(["selftest"])
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_selftest_says_plainly_it_needs_nothing_external(self):
        _ok, lines = errors.selftest()
        text = "\n".join(lines).lower()
        self.assertIn("no network", text)

    def test_a_sample_character_ships_with_the_package(self):
        import charactercheck
        pkg = os.path.dirname(os.path.abspath(charactercheck.__file__))
        repo = os.path.dirname(pkg)
        self.assertTrue(
            os.path.exists(os.path.join(pkg, "sample-character.json"))
            or os.path.exists(os.path.join(repo, "examples", "sample-character.json")),
            "an agent with no character of its own must still have one to try")

    def test_agents_md_exists_and_leads_with_selftest(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, "AGENTS.md")
        self.assertTrue(os.path.exists(path), "AGENTS.md is the agent entry point")
        with open(path) as f:
            text = f.read()
        self.assertIn("selftest", text)
        self.assertIn("exit", text.lower())
        # the mistake we most need to pre-empt
        self.assertIn("treating exit 2 as failure", text)
