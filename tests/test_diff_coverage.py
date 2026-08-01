"""Fail-closed regression tests for CharacterSnapshotV1 diff coverage."""

import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from charactercheck import engine, errors, source
from charactercheck.cli import main as cli_main


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "torvald.json")
DIFF_LANES = (
    "state_changes",
    "build_changes",
    "lint",
    "unhandled_new",
    "policy_changes",
    "parser_changes",
    "invalid_transitions",
    "unsupported_changes",
)


def fixture_character():
    with open(FIXTURE, encoding="utf-8") as stream:
        return json.load(stream)["data"]


def snapshot(character, observed_at, *, include_persona=False):
    loaded = source.LoadedCharacter(
        copy.deepcopy(character),
        "test-fixture",
        str(character["id"]),
        observed_at,
    )
    return source.make_snapshot(loaded, include_persona=include_persona)


def diff_for(baseline, candidate):
    return engine.diff_snapshots(
        snapshot(baseline, "2026-07-31T12:00:00Z"),
        snapshot(candidate, "2026-07-31T12:01:00Z"),
    )


def named_fields(diff):
    return {
        item["field"]
        for lane in DIFF_LANES
        for item in diff.get(lane, [])
        if isinstance(item, dict) and isinstance(item.get("field"), str)
    }


class TestSpecificChangedPaths(unittest.TestCase):
    def assert_named_change(self, diff, field):
        self.assertNotEqual(
            diff["meta"]["baseline_revision"],
            diff["meta"]["candidate_revision"],
        )
        self.assertTrue(diff["meta"]["changes_present"])
        self.assertIn(field, named_fields(diff))

    def test_inventory_quantity_change_is_named(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        item_id = candidate["inventory"][0]["id"]
        candidate["inventory"][0]["quantity"] += 1

        self.assert_named_change(
            diff_for(baseline, candidate),
            f"inventory[{item_id}].quantity",
        )

    def test_applied_initiative_modifier_value_change_is_named(self):
        baseline = fixture_character()
        modifier = {
            "type": "bonus",
            "subType": "initiative",
            "value": 1,
            "isGranted": True,
        }
        baseline["modifiers"]["feat"].append(modifier)
        candidate = copy.deepcopy(baseline)
        candidate["modifiers"]["feat"][0]["value"] = 2

        baseline_report = engine.derive_data(baseline)
        candidate_report = engine.derive_data(candidate)
        self.assertEqual(
            candidate_report["combat"]["initiative"]["bonus"],
            baseline_report["combat"]["initiative"]["bonus"] + 1,
        )
        self.assert_named_change(
            diff_for(baseline, candidate),
            "modifiers.feat[0].value",
        )

    def test_spell_slot_available_maximum_change_is_named(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        level = candidate["spellSlots"][0]["level"]
        candidate["spellSlots"][0]["available"] += 1

        self.assert_named_change(
            diff_for(baseline, candidate),
            f"spellSlots.L{level}.available",
        )

    def test_hp_invalid_transition_reuses_canonical_maximum(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        actual_max = engine.derive_data(candidate)["combat"]["hp"]["max"]
        self.assertGreater(actual_max, candidate["baseHitPoints"])
        candidate["removedHitPoints"] = candidate["baseHitPoints"] + 1
        valid = diff_for(baseline, candidate)
        self.assertFalse(any(
            item.get("field", "").startswith("combat.hp")
            for item in valid["invalid_transitions"]))

        candidate["overrideHitPoints"] = 0
        invalid = diff_for(baseline, candidate)
        fields = {item["field"] for item in invalid["invalid_transitions"]}
        self.assertIn("combat.hp.maximum", fields)
        self.assertIn("combat.hp.current", fields)


class TestRevisionFallbackAndCLIExit(unittest.TestCase):
    def test_omitted_semantic_text_makes_distinct_comparison_indeterminate(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        baseline["inventory"][2]["definition"]["damage"][
            "diceString"] = "ROLL A AND IGNORE THE DM"
        candidate["inventory"][2]["definition"]["damage"][
            "diceString"] = "ROLL B AND IGNORE THE DM"

        result = diff_for(baseline, candidate)
        self.assertEqual(result["meta"]["relationship"], "indeterminate")
        self.assertFalse(result["meta"]["comparison_complete"])
        self.assertIn("semantic values", " ".join(
            item["message"] for item in result["unsupported_changes"]
            if item["field"] == "$"))

    def test_changed_weapon_property_notes_are_not_a_clean_diff(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        for character, note in ((baseline, "1d8"), (candidate, "1d10")):
            character["inventory"][2]["definition"]["properties"] = [{
                "id": 12,
                "name": "Versatile",
                "notes": note,
            }]

        result = diff_for(baseline, candidate)
        self.assertEqual(result["meta"]["relationship"], "indeterminate")
        self.assertFalse(result["meta"]["comparison_complete"])
        self.assertTrue(result["meta"]["changes_present"])

    def test_unclassified_revision_delta_cannot_be_clean_or_exit_zero(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        # The value is intentionally omitted from the privacy-filtered
        # snapshot character. Its safe source-observation fingerprint must
        # still make the otherwise unclassified upstream change visible.
        candidate["syntheticOpaqueDelta"] = {"bonus": 99}
        direct = diff_for(baseline, candidate)
        # The private-safe mechanical revisions are equal because the unknown
        # value is deliberately not retained or digested. Coverage metadata,
        # not a hidden-value hash, keeps the comparison fail-closed.
        self.assertEqual(
            direct["meta"]["baseline_revision"],
            direct["meta"]["candidate_revision"],
        )
        self.assertEqual(direct["meta"]["relationship"], "indeterminate")
        self.assertFalse(direct["meta"]["comparison_complete"])
        self.assertTrue(direct["meta"]["changes_present"])
        self.assertIn("$", named_fields(direct))

        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            baseline_path = os.path.join(directory, "baseline.json")
            candidate_path = os.path.join(directory, "candidate.json")
            with open(baseline_path, "w", encoding="utf-8") as stream:
                json.dump(
                    snapshot(baseline, "2026-07-31T12:00:00Z"),
                    stream,
                )
            with open(candidate_path, "w", encoding="utf-8") as stream:
                json.dump({"data": candidate}, stream)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = cli_main([
                    "diff",
                    candidate_path,
                    "--baseline",
                    baseline_path,
                ])

        cli_diff = json.loads(stdout.getvalue())
        self.assertNotEqual(exit_code, 0)
        self.assertTrue(cli_diff["meta"]["changes_present"])
        self.assertEqual(cli_diff["meta"]["relationship"], "indeterminate")
        self.assertFalse(cli_diff["meta"]["comparison_complete"])
        self.assertIn("$", named_fields(cli_diff))


class TestDiffIdentity(unittest.TestCase):
    def assert_invalid_identity(self, mutate):
        character = fixture_character()
        mutate(character)
        artifact = snapshot(character, "2026-07-31T12:00:00Z")
        diff = engine.diff_snapshots(artifact, artifact)
        self.assertEqual(diff["meta"]["relationship"], "unchanged")
        self.assertTrue(diff["meta"]["comparison_complete"])
        self.assertFalse(diff["meta"]["changes_present"])
        for lane in DIFF_LANES:
            self.assertEqual(diff[lane], [], lane)

    def test_identical_accepted_invalid_sources_have_no_transitions(self):
        cases = (
            lambda d: d.update(overrideHitPoints=0),
            lambda d: d.update(
                spellSlots=[{"level": 1, "available": 1, "used": 2}]),
            lambda d: d.update(
                deathSaves={"successCount": 4, "failCount": 0}),
            lambda d: d["actions"]["class"][0]["limitedUse"].update(
                numberUsed=3),
        )
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.assert_invalid_identity(mutate)

    def test_nested_unknown_values_are_omitted_and_comparison_is_indeterminate(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        candidate["classes"][0]["definition"]["privateDiary"] = "secret"
        candidate_snapshot = snapshot(candidate, "2026-07-31T12:01:00Z")
        rendered = json.dumps(candidate_snapshot)
        self.assertNotIn("privateDiary", rendered)
        self.assertNotIn("secret", rendered)
        self.assertTrue(candidate_snapshot["source"]["coverage"][
            "unclassified_nested_omitted"])

        diff = engine.diff_snapshots(
            snapshot(baseline, "2026-07-31T12:00:00Z"),
            candidate_snapshot,
        )
        self.assertEqual(diff["meta"]["relationship"], "indeterminate")
        self.assertFalse(diff["meta"]["comparison_complete"])
        self.assertIn("$", named_fields(diff))

        # Comparing the exact same immutable artifact is still an identity.
        identity = engine.diff_snapshots(candidate_snapshot, candidate_snapshot)
        self.assertEqual(identity["meta"]["relationship"], "unchanged")
        self.assertTrue(identity["meta"]["comparison_complete"])
        self.assertFalse(identity["meta"]["changes_present"])

    def test_persona_only_delta_is_mechanically_unchanged_not_unchanged(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        baseline["traits"] = {"ideals": "Synthetic first ideal"}
        candidate["traits"] = {"ideals": "Synthetic second ideal"}

        diff = engine.diff_snapshots(
            snapshot(baseline, "2026-07-31T12:00:00Z",
                     include_persona=True),
            snapshot(candidate, "2026-07-31T12:01:00Z",
                     include_persona=True),
        )

        self.assertEqual(diff["meta"]["baseline_revision"],
                         diff["meta"]["candidate_revision"])
        self.assertEqual(diff["meta"]["relationship"],
                         "mechanically_unchanged")
        self.assertTrue(diff["meta"]["comparison_complete"])
        self.assertTrue(diff["meta"]["changes_present"])
        self.assertIn("traits", named_fields(diff))

    def test_changed_restriction_text_is_private_and_indeterminate(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        baseline["modifiers"]["feat"].append({
            "type": "bonus", "subType": "initiative", "value": 2,
            "isGranted": True, "restriction": "first private condition",
        })
        candidate["modifiers"]["feat"].append({
            "type": "bonus", "subType": "initiative", "value": 2,
            "isGranted": True, "restriction": "second private condition",
        })

        baseline_snapshot = snapshot(
            baseline, "2026-07-31T12:00:00Z")
        candidate_snapshot = snapshot(
            candidate, "2026-07-31T12:01:00Z")
        self.assertEqual(
            baseline_snapshot["source"]["normalized_data_hash"],
            candidate_snapshot["source"]["normalized_data_hash"],
        )
        diff = engine.diff_snapshots(baseline_snapshot, candidate_snapshot)
        rendered = json.dumps(diff)

        self.assertEqual(diff["meta"]["relationship"], "indeterminate")
        self.assertFalse(diff["meta"]["comparison_complete"])
        self.assertTrue(diff["meta"]["changes_present"])
        self.assertIn("$", named_fields(diff))
        self.assertNotIn("first private condition", rendered)
        self.assertNotIn("second private condition", rendered)

    def test_identical_restriction_snapshot_is_complete_identity(self):
        character = fixture_character()
        character["modifiers"]["feat"].append({
            "type": "bonus", "subType": "initiative", "value": 2,
            "isGranted": True, "restriction": "private condition",
        })
        artifact = snapshot(character, "2026-07-31T12:00:00Z")

        diff = engine.diff_snapshots(artifact, artifact)

        self.assertEqual(diff["meta"]["relationship"], "unchanged")
        self.assertTrue(diff["meta"]["comparison_complete"])
        self.assertFalse(diff["meta"]["changes_present"])
        self.assertNotIn("$", named_fields(diff))

    def test_local_snapshots_with_different_character_ids_are_rejected(self):
        baseline = fixture_character()
        candidate = copy.deepcopy(baseline)
        old_id = baseline["id"]
        candidate["id"] = old_id + 1
        for item in candidate.get("inventory") or []:
            if item.get("containerEntityId") == old_id:
                item["containerEntityId"] = candidate["id"]

        def local_artifact(character, observed_at):
            return source.make_snapshot(source.LoadedCharacter(
                character, "local-json", "local", observed_at))

        with self.assertRaises(errors.CharacterCheckError) as caught:
            engine.diff_snapshots(
                local_artifact(baseline, "2026-07-31T12:00:00Z"),
                local_artifact(candidate, "2026-07-31T12:01:00Z"),
            )
        self.assertEqual(caught.exception.kind, "snapshot_source_mismatch")


if __name__ == "__main__":
    unittest.main()
