"""Canonical trust and projection invariants for agent-facing character data.

These tests intentionally exercise the same uncertain character through the
canonical report and its downstream views.  A view may preserve or worsen a
field assessment; it must never make an uncertain value look authoritative.
"""

import copy
import io
import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

from charactercheck import engine, qa, source
from charactercheck.cli import main as cli_main


FIXTURES = Path(__file__).resolve().parent / "fixtures"
TORVALD = str(FIXTURES / "torvald.json")
VEXA = str(FIXTURES / "vexa.json")

STATES = {
    "trusted", "confirm", "unsupported", "unknown", "invalid",
    "not_applicable",
}
FIELD_KEYS = {
    "value", "state", "formula", "inputs", "sources", "rules_profile",
    "findings", "confidence", "authority", "as_of", "stale",
    "sensitivity",
}
CONFIDENCE = {
    "trusted": 1.0,
    "confirm": 0.6,
    "unsupported": 0.2,
    "unknown": 0.0,
    "invalid": 0.0,
    "not_applicable": None,
}
FIXED_AS_OF = "2026-07-31T12:34:56Z"


def fixture_character(name="torvald"):
    with (FIXTURES / f"{name}.json").open(encoding="utf-8") as stream:
        return json.load(stream)["data"]


def add_modifier(character, modifier, bucket="feat"):
    changed = copy.deepcopy(character)
    changed["modifiers"].setdefault(bucket, []).append(modifier)
    return changed


def restricted_ac_character():
    """A valid payload with a narrowly scoped modifier we cannot adjudicate."""
    return add_modifier(fixture_character(), {
        "type": "bonus",
        "subType": "armor-class",
        "value": 7,
        "isGranted": True,
        "restriction": "Only while a fictional conditional effect is active",
    })


def unknown_scope_character():
    return add_modifier(fixture_character(), {
        "type": "munch",
        "subType": "cookies",
        "value": 1,
        "isGranted": True,
    })


@contextmanager
def local_character(character):
    """Expose a character as a direct, non-symlinked local JSON fixture."""
    with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
        path = Path(directory) / "character.json"
        path.write_text(json.dumps({"data": character}), encoding="utf-8")
        yield str(path)


def cli_json(argv):
    output = io.StringIO()
    with redirect_stdout(output):
        code = cli_main(argv)
    return code, json.loads(output.getvalue())


class TestCanonicalFieldContract(unittest.TestCase):
    def test_every_field_is_a_closed_assessment_record(self):
        loaded = source.LoadedCharacter(
            fixture_character(), "test-fixture", "synthetic", FIXED_AS_OF)
        report = engine.derive_loaded(loaded)

        representative_fields = {
            "identity.name",
            "identity.proficiency_bonus",
            "abilities.str.score",
            "saves.wis.bonus",
            "skills.perception.bonus",
            "senses.vision",
            "combat.ac.value",
            "combat.initiative.bonus",
            "combat.hp.maximum",
            "combat.hp.current",
            "combat.weapons",
            "combat.stance",
            "spellcasting.save_dc",
            "spellcasting.slots.maximum",
            "spellcasting.slots.current",
            "resources",
            "inventory",
        }
        self.assertTrue(representative_fields <= set(report["fields"]))
        self.assertTrue(report["meta"]["read_only"])
        self.assertFalse(report["meta"]["autonomous_ready"])
        self.assertIn(report["meta"]["aggregate_state"], STATES - {"not_applicable"})

        for field_id, assessment in report["fields"].items():
            with self.subTest(field=field_id):
                self.assertTrue(FIELD_KEYS <= set(assessment))
                self.assertIn(assessment["state"], STATES)
                self.assertEqual(
                    assessment["confidence"], CONFIDENCE[assessment["state"]])
                self.assertIsInstance(assessment["inputs"], list)
                self.assertIsInstance(assessment["findings"], list)
                self.assertTrue(all(isinstance(value, str)
                                    for value in assessment["findings"]))
                self.assertEqual(
                    assessment["sources"], [report["meta"]["source_revision"]])
                self.assertEqual(
                    assessment["rules_profile"], report["meta"]["rules_profile"])
                self.assertEqual(assessment["as_of"], FIXED_AS_OF)
                self.assertIs(assessment["stale"], False)
                self.assertIsInstance(assessment["authority"], str)
                self.assertIsInstance(assessment["sensitivity"], str)

    def test_known_character_has_declared_weapon_gaps_and_mutable_confirmations(self):
        report = engine.derive(TORVALD)
        trust = report["trust"]
        weapon_gaps = [
            "item-semantic:weapon_proficiency",
            "item-semantic:weapon_property",
        ]

        self.assertEqual(
            set(trust["trusted"]),
            set(engine.FAMILY_CATALOG) - {"attacks", "weapons"},
        )
        for lane in ("ask_player", "unknown", "invalid"):
            self.assertEqual(trust[lane], {})
        self.assertEqual(trust["unsupported"], {
            "attacks": weapon_gaps,
            "weapons": weapon_gaps,
        })
        self.assertEqual(report["lint"], [])
        self.assertEqual(
            [item["pattern"] for item in report["unhandled"]["items"]],
            weapon_gaps,
        )
        self.assertTrue(all(
            item["state"] == "unsupported" and item["not_applied"]
            for item in report["unhandled"]["items"]
        ))

        non_trusted = {
            field_id: field["state"]
            for field_id, field in report["fields"].items()
            if field["state"] != "trusted"
        }
        self.assertEqual(non_trusted, {
            "combat.hp.current": "confirm",
            "combat.weapons": "unsupported",
            "combat.stance": "confirm",
            "spellcasting.slots.current": "confirm",
            "resources": "confirm",
            "inventory": "confirm",
        })
        for field_id in non_trusted.keys() - {"combat.weapons"}:
            field = report["fields"][field_id]
            self.assertEqual(field["authority"], "player")
            self.assertIn("mutable_player_state", field["findings"])
        self.assertEqual(
            report["fields"]["combat.weapons"]["authority"], "rules_engine")
        self.assertEqual(report["meta"]["aggregate_state"], "unsupported")

    def test_noncaster_spell_fields_are_not_applicable(self):
        character = fixture_character()
        character["classes"][0]["definition"]["name"] = "Fighter"
        character["classes"][0]["definition"]["spellCastingAbilityId"] = None
        character["spells"] = {}
        character["classSpells"] = []
        character["spellSlots"] = []
        character["pactMagic"] = []

        report = engine.derive_data(character)
        self.assertIsNone(report["spellcasting"])
        spell_fields = {
            field_id: field for field_id, field in report["fields"].items()
            if field_id.startswith("spellcasting.")
        }
        self.assertEqual(len(spell_fields), 6)
        for field_id, field in spell_fields.items():
            with self.subTest(field=field_id):
                self.assertEqual(field["state"], "not_applicable")
                self.assertIsNone(field["value"])
            self.assertIsNone(field["confidence"])
            self.assertEqual(field["findings"], [])

    def test_noncaster_spell_fields_preserve_global_unknown(self):
        character = fixture_character()
        character["classes"][0]["definition"]["name"] = "Fighter"
        character["classes"][0]["definition"]["spellCastingAbilityId"] = None
        character["spells"] = {}
        character["classSpells"] = []
        character["spellSlots"] = []
        character["pactMagic"] = []
        character = add_modifier(character, {
            "type": "synthetic-unknown", "subType": "global",
            "value": 1, "isGranted": True,
        })

        report = engine.derive_data(character)
        for field_id, field in report["fields"].items():
            if field_id.startswith("spellcasting."):
                with self.subTest(field=field_id):
                    self.assertEqual(field["state"], "unknown")
                    self.assertEqual(field["confidence"], 0.0)


class TestStateRoutingAndPrecedence(unittest.TestCase):
    def test_contradictory_core_state_routes_to_invalid(self):
        cases = (
            (lambda character: character.update(removedHitPoints=999),
             "combat.hp.current"),
            (lambda character: character["spellSlots"][0].update(used=999),
             "spellcasting.slots.current"),
        )
        for mutate, field_id in cases:
            with self.subTest(field=field_id):
                character = fixture_character()
                mutate(character)
                report = engine.derive_data(character)
                self.assertEqual(report["fields"][field_id]["state"],
                                 "invalid")
                self.assertEqual(report["meta"]["aggregate_state"], "invalid")

    def test_precedence_is_invalid_then_global_unknown_then_unsupported_then_confirm(self):
        lint = [{
            "code": "confirm-ac",
            "message": "confirm it",
            "ask": "What is your AC?",
            "affects": ["ac"],
        }, {
            "code": "confirm-skills",
            "message": "confirm them",
            "ask": "What are your skill bonuses?",
            "affects": ["skills"],
        }]
        unhandled = {"items": [{
            "pattern": "invalid:ac",
            "state": "invalid",
            "possibly_affects": ["ac"],
        }, {
            "pattern": "unsupported:skills",
            "state": "unsupported",
            "possibly_affects": ["skills"],
        }, {
            "pattern": "munch:cookies",
            "state": "unsupported",
            "possibly_affects": ["unknown"],
        }]}

        trust = engine.trust_map(lint, unhandled)
        self.assertEqual(engine._family_assessment(trust, "ac")[0], "invalid")
        self.assertEqual(engine._family_assessment(trust, "skills")[0], "unknown")
        self.assertEqual(engine._family_assessment(trust, "hp")[0], "unknown")
        self.assertEqual(trust["trusted"], [])
        self.assertEqual(set(trust["unknown"]), set(engine.FAMILY_CATALOG))
        self.assertNotIn("ac", trust["ask_player"])
        self.assertNotIn("skills", trust["ask_player"])
        for family in engine.FAMILY_CATALOG:
            self.assertIn(engine._family_assessment(trust, family)[0], STATES)

        without_global = engine.trust_map(lint, {
            "items": unhandled["items"][:2],
        })
        self.assertEqual(
            engine._family_assessment(without_global, "skills")[0],
            "unsupported")
        self.assertEqual(
            engine._family_assessment(without_global, "ac")[0], "invalid")

    def test_narrow_unsupported_modifier_does_not_poison_other_families(self):
        character = add_modifier(fixture_character(), {
            "type": "bonus",
            "subType": "initiative",
            "value": 99,
            "isGranted": True,
            "restriction": "Only under a condition the engine cannot evaluate",
        })
        report = engine.derive_data(character)

        self.assertEqual(report["combat"]["initiative"]["bonus"], 0)
        self.assertEqual(
            report["fields"]["combat.initiative.bonus"]["state"],
            "unsupported")
        self.assertIn("bonus:initiative", report["trust"]["unsupported"]["initiative"])
        self.assertEqual(report["fields"]["combat.ac.value"]["state"], "trusted")
        self.assertIn("ac", report["trust"]["trusted"])
        self.assertEqual(report["trust"]["unknown"], {})
        self.assertEqual(report["meta"]["aggregate_state"], "unsupported")

    def test_global_unknown_cannot_be_upgraded_by_a_canonical_projection(self):
        report = engine.derive_data(unknown_scope_character())
        self.assertEqual(set(report["trust"]["unknown"]),
                         set(engine.FAMILY_CATALOG))
        self.assertEqual(report["fields"]["abilities.str.score"]["state"],
                         "unknown")
        self.assertEqual(
            report["fields"]["identity.proficiency_bonus"]["state"],
            "unknown")
        self.assertEqual(report["fields"]["senses.vision"]["state"],
                         "unknown")
        # Mutable is an additional reason to confirm, not permission to turn
        # globally unknown inventory into a merely confirmable value.
        self.assertEqual(report["fields"]["inventory"]["state"], "unknown")
        self.assertEqual(report["fields"]["combat.hp.current"]["state"],
                         "unknown")
        self.assertEqual(report["meta"]["aggregate_state"], "unknown")

    def test_aggregate_uses_the_highest_severity(self):
        character = unknown_scope_character()
        character = add_modifier(character, {
            "type": "bonus",
            "subType": "armor-class",
            "isGranted": True,
            # Missing numeric value is structurally valid but invalid for this
            # exact handler, giving us invalid + global unknown together.
        })
        report = engine.derive_data(character)
        self.assertEqual(report["fields"]["combat.ac.value"]["state"], "invalid")
        self.assertEqual(report["fields"]["abilities.str.score"]["state"],
                         "unknown")
        self.assertEqual(report["meta"]["aggregate_state"], "invalid")


class TestFindingsAndObservationIdentity(unittest.TestCase):
    def test_finding_ids_are_deterministic_and_well_formed(self):
        character = restricted_ac_character()
        reordered = json.loads(json.dumps(character, sort_keys=True))
        first = engine.derive_data(character)
        second = engine.derive_data(reordered)

        first_ids = {
            item["pattern"]: item["finding_id"]
            for item in first["unhandled"]["items"]
        }
        second_ids = {
            item["pattern"]: item["finding_id"]
            for item in second["unhandled"]["items"]
        }
        self.assertEqual(first_ids, second_ids)
        self.assertIn("bonus:armor-class", first_ids)
        for finding_id in first_ids.values():
            self.assertRegex(finding_id, r"^finding:[0-9a-f]{16}$")

    def test_revision_and_as_of_are_identical_across_one_observation(self):
        character = restricted_ac_character()
        loaded = source.LoadedCharacter(
            character, "test-fixture", "synthetic", FIXED_AS_OF)
        report = engine.derive_loaded(loaded)
        expected_revision = source.mechanical_hash(character)

        self.assertEqual(report["meta"]["source_revision"], expected_revision)
        self.assertEqual(report["meta"]["as_of"], FIXED_AS_OF)
        for field in report["fields"].values():
            self.assertEqual(field["sources"], [expected_revision])
            self.assertEqual(field["as_of"], FIXED_AS_OF)
        self.assertEqual(
            report["combat"]["stance"]["assessment"]["source_revision"],
            expected_revision)

        with mock.patch.object(engine, "fetch_loaded", return_value=loaded):
            seatpack = engine.seatpack("12345")
            intake = engine.intake("12345")
            quiz = engine.quiz("12345")
        for projection in (seatpack, intake, intake["seatpack"], quiz):
            self.assertEqual(projection["meta"]["source_revision"],
                             expected_revision)
            self.assertEqual(projection["meta"]["as_of"], FIXED_AS_OF)
        self.assertEqual(seatpack["trust"], report["trust"])
        self.assertEqual(intake["trust"], report["trust"])
        self.assertEqual(quiz["trust"], report["trust"])


class TestProjectionTrustInvariants(unittest.TestCase):
    def test_dm_redaction_never_improves_unknown_field_state(self):
        character = fixture_character()
        character["modifiers"]["feat"].append({
            "type": "synthetic-unknown", "subType": "global", "value": 1,
            "isGranted": True,
        })
        canonical = engine.derive_data(character)
        pack = engine.seatpack_data(character, canonical, for_dm=True)
        for field_id in ("combat.hp.current", "spellcasting.slots.current",
                         "resources", "inventory"):
            with self.subTest(field=field_id):
                self.assertEqual(canonical["fields"][field_id]["state"],
                                 "unknown")
                self.assertEqual(pack["fields"][field_id]["state"], "unknown")
                self.assertEqual(pack["fields"][field_id]["confidence"], 0.0)

    def test_coverage_inventory_does_not_upgrade_mutable_collections(self):
        rows = {number: state for number, _key, state, _value in qa.run(TORVALD)}
        self.assertEqual(rows[74], "confirm")
        for number in range(91, 97):
            with self.subTest(row=number):
                self.assertEqual(rows[number], "confirm")

    def test_coverage_inventory_does_not_upgrade_global_unknown_rows(self):
        with local_character(unknown_scope_character()) as ref:
            rows = {number: state for number, _key, state, _value in qa.run(ref)}
        for number in (68, 69, 70, 71, 72, 73, 87):
            with self.subTest(row=number):
                self.assertEqual(rows[number], "unknown")

    def test_quiz_never_supplies_an_answer_key_for_a_nontrusted_field(self):
        with local_character(restricted_ac_character()) as ref:
            report = engine.derive(ref)
            quiz = engine.quiz(ref)

        for question in quiz["questions"]:
            with self.subTest(question=question["ask"]):
                self.assertIn(question["state"], STATES)
                if question["state"] != "trusted":
                    self.assertIsNone(question["expect"])

        ac = next(q for q in quiz["questions"] if "AC" in q["ask"])
        self.assertEqual(ac["state"],
                         report["fields"]["combat.ac.value"]["state"])
        self.assertIsNone(ac["expect"])
        self.assertEqual(ac["authority"], "player")
        self.assertEqual(quiz["trust"]["unsupported"]["ac"],
                         report["trust"]["unsupported"]["ac"])

        attunement = next(q for q in quiz["questions"]
                          if "attuned" in q["ask"].lower())
        self.assertEqual(attunement["state"],
                         report["fields"]["inventory"]["state"])
        self.assertIsNone(attunement["expect"])
        self.assertEqual(attunement["authority"], "player")

    def test_qa_and_stance_preserve_ac_uncertainty(self):
        with local_character(restricted_ac_character()) as ref:
            report = engine.derive(ref)
            rows = qa.run(ref)
            code, cli_stance = cli_json(["stance", ref])

        canonical = report["fields"]["combat.ac.value"]
        assessment = report["combat"]["stance"]["assessment"]
        self.assertEqual(assessment["state"], canonical["state"])
        self.assertEqual(assessment["findings"], canonical["findings"])
        self.assertEqual(assessment["source_revision"],
                         report["meta"]["source_revision"])
        self.assertEqual(report["fields"]["combat.stance"]["state"],
                         canonical["state"])

        self.assertEqual(code, 0)
        self.assertEqual(cli_stance["assessment"]["state"], "unsupported")
        self.assertEqual(cli_stance["assessment"]["findings"],
                         canonical["findings"])
        self.assertEqual(len(rows), 100)
        self.assertTrue(all(row[2] in STATES for row in rows))
        armor_class = next(row for row in rows if row[0] == 20)
        self.assertEqual(armor_class[2], "unsupported")

    def test_seatpack_and_intake_do_not_drop_or_upgrade_findings(self):
        character = restricted_ac_character()
        loaded = source.LoadedCharacter(
            character, "test-fixture", "synthetic", FIXED_AS_OF)
        canonical = engine.derive_loaded(loaded)
        with mock.patch.object(engine, "fetch_loaded", return_value=loaded):
            seatpack = engine.seatpack("12345")
            intake = engine.intake("12345")

        expected = canonical["fields"]["combat.ac.value"]
        for label, projection in (
                ("seatpack", seatpack),
                ("intake.seatpack", intake["seatpack"])):
            with self.subTest(projection=label):
                actual = projection["fields"]["combat.ac.value"]
                self.assertEqual(actual["state"], expected["state"])
                self.assertEqual(actual["findings"], expected["findings"])
                self.assertEqual(projection["trust"]["unsupported"]["ac"],
                                 canonical["trust"]["unsupported"]["ac"])
                self.assertEqual(projection["vision"],
                                 canonical["fields"]["senses.vision"]["value"])
        self.assertEqual(intake["unsupported"]["ac"],
                         canonical["trust"]["unsupported"]["ac"])

    def test_for_dm_projection_does_not_mutate_the_canonical_report(self):
        character = restricted_ac_character()
        report = engine.derive_data(character)
        before = copy.deepcopy(report)

        projected = engine.seatpack_data(character, report, for_dm=True)

        self.assertEqual(report, before)
        self.assertEqual(
            projected["fields"]["combat.ac.value"]["findings"],
            before["fields"]["combat.ac.value"]["findings"])
        self.assertEqual(projected["fields"]["combat.ac.value"]["state"],
                         "unsupported")
        self.assertEqual(projected["fields"]["combat.hp.current"]["state"],
                         "confirm")
        self.assertEqual(projected["fields"]["combat.hp.current"]["authority"],
                         "player")

    def test_cli_and_mcp_reports_retain_canonical_trust_artifacts(self):
        character = restricted_ac_character()
        with local_character(character) as ref:
            code, cli_report = cli_json(["report", ref])
            canonical = engine.derive(ref)

        self.assertEqual(code, 2)
        for key in ("meta", "trust", "fields", "unhandled", "lint"):
            self.assertIn(key, cli_report)
        cli_ac = cli_report["fields"]["combat.ac.value"]
        self.assertEqual(cli_ac["state"], "unsupported")
        self.assertEqual(cli_ac["findings"],
                         canonical["fields"]["combat.ac.value"]["findings"])

        from charactercheck import mcp
        with mock.patch.object(engine.source, "parse_ref",
                               return_value=("id", "12345")), \
                mock.patch.object(mcp, "derive", return_value=canonical):
            mcp_report = mcp._call("report", {"ref": "12345"})
        for key in ("meta", "trust", "fields", "unhandled", "lint"):
            self.assertIn(key, mcp_report)
        self.assertEqual(
            mcp_report["fields"]["combat.ac.value"]["state"], "unsupported")
        self.assertEqual(
            mcp_report["fields"]["combat.ac.value"]["findings"],
            canonical["fields"]["combat.ac.value"]["findings"])

    def test_mcp_stance_retains_the_canonical_assessment(self):
        from charactercheck import mcp

        character = restricted_ac_character()
        canonical = engine.derive_data(character)
        with mock.patch.object(engine.source, "parse_ref",
                               return_value=("id", "12345")), \
                mock.patch.object(mcp, "derive", return_value=canonical), \
                mock.patch.object(engine, "derive", return_value=canonical), \
                mock.patch.object(engine, "fetch", return_value=character):
            stance = mcp._call("stance", {"ref": "12345"})

        self.assertIn("assessment", stance)
        self.assertEqual(stance["assessment"]["state"], "unsupported")
        self.assertEqual(
            stance["assessment"]["findings"],
            canonical["fields"]["combat.ac.value"]["findings"])


if __name__ == "__main__":
    unittest.main()
