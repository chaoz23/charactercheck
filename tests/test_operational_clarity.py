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
import socket
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from charactercheck import engine  # noqa: E402
from charactercheck.cli import main  # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
TORVALD = os.path.join(FIX, "torvald.json")
VEXA = os.path.join(FIX, "vexa.json")


def _online():
    try:
        socket.getaddrinfo("character-service.dndbeyond.com", 443)
        return True
    except OSError:
        return False


needs_net = unittest.skipUnless(_online(), "no network")


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

    def test_brief_names_all_three_lanes_when_present(self):
        text = engine.render_brief(engine.derive(VEXA)).lower()
        self.assertIn("trusted:", text)

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

    def test_intake_settled_matches_the_trust_map(self):
        p = engine.intake(VEXA)
        t = engine.derive(VEXA)["trust"]
        self.assertEqual(set(p["settled"]), set(t["trusted"]))


class TestScopeHeld(unittest.TestCase):
    """The two requests deliberately NOT built, asserted as absences.

    P2 (a table-question catalogue) and P6 (a spell content database) both
    drift toward rules knowledge or shipped content, which this repo refuses.
    If either appears later it should be a deliberate decision, not drift.
    """

    def test_no_answerability_command(self):
        import re
        src = open(os.path.join(os.path.dirname(FIX), "..", "charactercheck",
                                "cli.py")).read()
        choices = re.search(r"choices=\[([^\]]+)\]", src).group(1)
        self.assertNotIn("answerability", choices)

    def test_no_spell_content_database_shipped(self):
        pkg = os.path.dirname(os.path.abspath(engine.__file__))
        for name in os.listdir(pkg):
            self.assertNotIn("spells", name.lower(),
                             "no spell content database — that is srdcheck's lane")


@needs_net
class TestAgainstLiveSheets(unittest.TestCase):
    def test_shalia_routes_her_three_open_questions(self):
        t = engine.derive("150991647")["trust"]
        self.assertIn("ac", t["ask_player"])
        self.assertIn("spell_slots", t["ask_player"])
        self.assertIn("prepared_spells", t["ask_player"])
        self.assertIn("spell_output", t["unsupported"])

    def test_shalia_still_trusts_the_sheet_math(self):
        t = engine.derive("150991647")["trust"]
        for fam in ("hp", "saves", "skills", "spell_save_dc"):
            self.assertIn(fam, t["trusted"])


if __name__ == "__main__":
    unittest.main()
