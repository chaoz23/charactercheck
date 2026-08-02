"""v0.6 — caveats become permissions and questions.

Every test here traces to feedback filed by an agent that used the tool at a
live table. Its framing was the right one: *"convert caveats into permissions
and questions so an agent can behave correctly under turn pressure."*

The two things it asked for that are NOT built are as deliberate as the four
that are — see charactercheck-epic-operational-clarity. Both drifted toward
needing a content database or a rules judgment, which belong in srdcheck or
nowhere.
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from charactercheck import engine  # noqa: E402
from charactercheck.cli import main  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TORVALD = os.path.join(FIX, "torvald.json")
VEXA = os.path.join(FIX, "vexa.json")


def run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    return code, buf.getvalue()


class TestLintIsActionable(unittest.TestCase):
    """P3: *"the difference between 'tool reports caveat' and 'agent resolves
    caveat at table'."*"""

    def test_every_lint_finding_carries_code_message_and_affects(self):
        for fixture in (TORVALD, VEXA):
            for f in engine.derive(fixture)["lint"]:
                self.assertTrue(f.get("code"), f)
                self.assertTrue(f.get("message"), f)
                self.assertIsInstance(f.get("affects"), list)

    def test_every_lint_finding_carries_a_human_question(self):
        for fixture in (TORVALD, VEXA):
            for f in engine.derive(fixture)["lint"]:
                self.assertTrue((f.get("ask") or "").strip(),
                                f"lint {f.get('code')} has no ask prompt")

    def test_ask_prompts_are_questions_a_gm_can_read_aloud(self):
        for fixture in (TORVALD, VEXA):
            for f in engine.derive(fixture)["lint"]:
                self.assertTrue(f["ask"].endswith("?"), f["ask"])

    def test_affects_names_only_known_families(self):
        for fixture in (TORVALD, VEXA):
            for f in engine.derive(fixture)["lint"]:
                for fam in f["affects"]:
                    self.assertIn(fam, engine.TRUST_FAMILIES)


class TestTrustMap(unittest.TestCase):
    """P1: *"agents need routing, not archaeology."*"""

    def test_the_three_lanes_are_mutually_exclusive(self):
        for fixture in (TORVALD, VEXA):
            t = engine.derive(fixture)["trust"]
            trusted = set(t["trusted"])
            ask = set(t["ask_player"])
            unsup = set(t["unsupported"])
            self.assertFalse(trusted & ask, "a family cannot be both trusted and in doubt")
            self.assertFalse(trusted & unsup)
            self.assertFalse(ask & unsup, "unsupported outranks ask_player")

    def test_a_family_in_doubt_is_never_reported_trusted(self):
        r = engine.derive(VEXA)
        t = r["trust"]
        for f in r["lint"]:
            for fam in f["affects"]:
                self.assertNotIn(fam, t["trusted"],
                                 f"{fam} has an open lint but is marked trusted")

    def test_unsupported_outranks_ask_player(self):
        t = engine.trust_map(
            [{"code": "x", "message": "m", "ask": "q?", "affects": ["spell_output"]}],
            {"items": [{"pattern": "bonus:spell-group-healing",
                        "possibly_affects": ["spell_output"]}]})
        self.assertIn("spell_output", t["unsupported"])
        self.assertNotIn("spell_output", t["ask_player"])

    def test_a_clean_sheet_trusts_everything(self):
        t = engine.trust_map([], {"items": []})
        self.assertEqual(set(t["trusted"]), set(engine.TRUST_FAMILIES))
        self.assertEqual(t["ask_player"], {})
        self.assertEqual(t["unsupported"], {})

    def test_asks_are_deduplicated_and_carry_their_family(self):
        dup = {"code": "c", "message": "m", "ask": "same?", "affects": ["ac"]}
        t = engine.trust_map([dup, dict(dup)], {"items": []})
        self.assertEqual(len(t["asks"]), 1)
        self.assertEqual(t["asks"][0]["affects"], ["ac"])

    def test_the_note_says_unsupported_was_not_applied(self):
        """The phrase the agent explicitly asked to have surfaced."""
        t = engine.trust_map([], {"items": []})
        self.assertIn("not applied", t["note"].lower())


class TestBrief(unittest.TestCase):
    """P5: deterministic short output beats a model-written summary."""

    def test_brief_is_short_enough_for_chat(self):
        text = engine.render_brief(engine.derive(VEXA))
        self.assertLess(len(text), 1200)
        self.assertLess(len(text.splitlines()), 16)

    def test_brief_is_deterministic(self):
        r = engine.derive(TORVALD)
        self.assertEqual(engine.render_brief(r), engine.render_brief(r))

    def test_brief_names_global_unknown_when_present(self):
        text = engine.render_brief(engine.derive(VEXA)).lower()
        self.assertIn("unknown global scope:", text)
        self.assertNotIn("trusted:", text)

    def test_brief_flag_changes_cli_output(self):
        code, out = run(["derive", TORVALD, "--brief"])
        self.assertIn(code, (0, 1, 2))
        self.assertNotIn("{", out.splitlines()[0])


class TestIntake(unittest.TestCase):
    """P4: one pre-session packet, composed rather than invented."""

    def test_intake_lists_what_must_be_resolved_before_dice(self):
        p = engine.intake(VEXA)
        self.assertIn("resolve_before_dice", p)
        for a in p["resolve_before_dice"]:
            self.assertTrue(a["ask"].endswith("?"))

    def test_intake_names_player_authority_fields(self):
        p = engine.intake(TORVALD)
        joined = " ".join(p["player_authority"]).lower()
        for field in ("hp", "slots", "conditions"):
            self.assertIn(field, joined)

    def test_intake_composes_the_existing_seatpack(self):
        p = engine.intake(TORVALD)
        self.assertIn("seatpack", p)
        self.assertIn("identity", p["seatpack"])

    def test_intake_supported_coverage_matches_the_trust_map(self):
        p = engine.intake(VEXA)
        t = engine.derive(VEXA)["trust"]
        self.assertEqual(set(p["no_known_issue_in_supported_coverage"]),
                         set(t["trusted"]))


class TestScopeHeld(unittest.TestCase):
    """The two requests deliberately NOT built, asserted as absences.

    P2 (a table-question catalogue) and P6 (a spell content database) both
    drift toward rules knowledge or shipped content, which this repo refuses.
    If either appears later it should be a deliberate decision, not drift.
    """

    def test_no_answerability_command(self):
        import re
        with open(os.path.join(os.path.dirname(FIX), "..", "charactercheck",
                               "cli.py")) as stream:
            src = stream.read()
        choices = re.search(r"choices=\[([^\]]+)\]", src).group(1)
        self.assertNotIn("answerability", choices)

    def test_no_spell_content_database_shipped(self):
        pkg = os.path.dirname(os.path.abspath(engine.__file__))
        for name in os.listdir(pkg):
            self.assertNotIn("spells", name.lower(),
                             "no spell content database — that is srdcheck's lane")


class TestSecondRoundUXR(unittest.TestCase):
    """Five nits filed after the agent pulled and tested 0.6.0.

    It also correctly diagnosed that no newer version existed — 'either the
    newer push hasn't hit GitHub/PyPI yet, or this is the same 0.6.0 I already
    tested.' It was the latter. Worth recording: the agent's read of the
    release state was right and mine was the one that needed checking.
    """

    def test_mcp_exposes_intake(self):
        """*"For agents, intake is probably the most valuable new surface."*"""
        from charactercheck import mcp
        self.assertIn("intake", [t["name"] for t in mcp.TOOLS])

    def test_mcp_exposes_the_bootstrap_pair(self):
        from charactercheck import mcp
        names = [t["name"] for t in mcp.TOOLS]
        self.assertIn("selftest", names)
        self.assertIn("doctor", names)

    def test_mcp_bootstrap_tools_do_not_require_a_ref(self):
        from charactercheck import mcp
        for t in mcp.TOOLS:
            if t["name"] in ("selftest", "doctor"):
                self.assertNotIn("required", t["inputSchema"],
                                 f"{t['name']} must work with no character")

    def test_mcp_intake_dispatches(self):
        from charactercheck import mcp
        with mock.patch("charactercheck.source.parse_ref", return_value=("id", "12345")), \
                mock.patch("charactercheck.engine.intake",
                           return_value={"resolve_before_dice": []}):
            out = mcp._call("intake", {"ref": "12345"})
        self.assertIn("resolve_before_dice", out)

    def test_schema_lists_every_cli_command(self):
        """*"this is exactly where agents look for contract truth."*"""
        import re
        from charactercheck.cli import SCHEMA
        with open(os.path.join(os.path.dirname(FIX), "..", "charactercheck",
                               "cli.py")) as stream:
            src = stream.read()
        choices = re.search(r"choices=\[([^\]]+)\]", src).group(1)
        for c in (x.strip().strip('"').strip("'") for x in choices.split(",")):
            self.assertIn(c, SCHEMA["commands"], f"--schema omits '{c}'")

    def test_report_brief_produces_a_caveat_summary(self):
        code, out = run(["report", VEXA, "--brief"])
        self.assertIn(code, (0, 1, 2))
        self.assertNotIn("{", out.splitlines()[0])
        self.assertIn("resolve before play", out)

    def test_brief_on_an_unsupported_command_is_refused_not_ignored(self):
        """Silently ignoring a flag is worse than rejecting it: the caller
        believes it worked."""
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            code = main(["stance", TORVALD, "--brief"])
        self.assertEqual(code, 2)

    def test_for_dm_on_derive_is_refused_not_silently_ignored(self):
        """A caller requesting DM redaction must never receive the ordinary
        projection while being led to believe a policy flag took effect."""
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), \
                mock.patch("charactercheck.cli.derive",
                           side_effect=AssertionError("must reject before derive")):
            code = main(["derive", TORVALD, "--for-dm"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"], "bad_flag")
        self.assertIn("--for-dm", payload["message"])

    def test_command_specific_flags_are_closed_not_silently_ignored(self):
        cases = (
            (["derive", TORVALD, "--full"], "--full"),
            (["derive", TORVALD, "--baseline", TORVALD], "--baseline"),
            (["derive", TORVALD, "--json"], "--json"),
            (["selftest", "--pipe"], "--pipe"),
        )
        for argv, flag in cases:
            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(flag=flag), redirect_stdout(stdout), \
                    redirect_stderr(stderr):
                code = main(argv)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stderr.getvalue())["error"],
                             "bad_flag")

    def test_headline_numbers_carry_their_doubt(self):
        """*"under turn pressure, headline numbers are sticky."*"""
        r = engine.derive(VEXA)
        text = engine.render_brief(r)
        head = text.splitlines()[1] if len(text.splitlines()) > 1 else ""
        for fam, label in (("ac", "AC"), ("hp", "HP")):
            if fam in (r["trust"].get("ask_player") or {}) and label in head:
                self.assertIn("(confirm)", head,
                              f"{label} is in ask_player but the headline does not say so")

    def test_verified_clean_says_it_is_not_the_routing(self):
        """A family can be verified_clean AND in ask_player for uncertain AC.
        The payload must say which one is authoritative."""
        r = engine.derive(VEXA)
        note = (r["unhandled"].get("verified_clean_note") or "").lower()
        self.assertIn("trust", note)
        self.assertIn("lint", note)
if __name__ == "__main__":
    unittest.main()
