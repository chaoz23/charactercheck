"""Contract tests for the fail-closed modifier registry.

These tests deliberately exercise both the registry ledger and the public
derivation.  A handler match alone must never be enough to affect arithmetic:
activation, restriction, operand, and source-evidence checks all have to pass.
"""

import copy
import json
import math
import os
import unittest
from unittest import mock

from charactercheck import engine, registry, source, source_field_registry


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "torvald.json")


def fixture_character():
    with open(FIXTURE, encoding="utf-8") as stream:
        character = json.load(stream)["data"]
    character["modifiers"] = {
        bucket: [] for bucket in character.get("modifiers", {})
    }
    character["characterValues"] = []
    for item in character.get("inventory", []):
        item["definition"]["grantedModifiers"] = []
    return character


def add_modifier(character, modifier, bucket="feat"):
    character["modifiers"].setdefault(bucket, []).append(copy.deepcopy(modifier))


def derived_numbers(character):
    report = engine.derive_data(copy.deepcopy(character))
    return {
        "wis": report["abilities"]["wis"]["score"],
        "ac": report["combat"]["ac"]["value"],
        "initiative": report["combat"]["initiative"]["bonus"],
        "hp_max": report["combat"]["hp"]["max"],
    }


class TestSourceModifierScopeRegistry(unittest.TestCase):
    def test_registry_fingerprint_is_reviewed_and_pinned(self):
        self.assertEqual(
            source_field_registry.REGISTRY_FINGERPRINT,
            "sha256:0409d146ff2fffe4f66347693456ad0bf64411d6910a5128d81fa0922efd37f4",
        )
        self.assertEqual(
            source.SOURCE_SCHEMA_FINGERPRINT,
            "sha256:7d3db435f5eb6f5f697966848ce1c9f419d3582e88c41e4bd9eb95d4262feebc",
        )

    def test_source_family_catalog_matches_engine_catalog(self):
        self.assertEqual(source_field_registry.FAMILIES,
                         set(engine.FAMILY_CATALOG))

    def test_source_and_public_blast_radius_registries_cannot_drift(self):
        for pattern, families in source_field_registry.MODIFIER_PATTERN_SCOPES.items():
            with self.subTest(pattern=pattern):
                self.assertEqual(set(engine.blast(pattern)[0]), set(families))


def workspace_signature(workspace):
    """Material build outputs that CharacterValue records can influence."""
    return {
        "abilities": dict(workspace["A"]),
        "ac": workspace["ac"],
        "skills": {
            skill: workspace["skill"](skill)
            for skill in sorted(engine.SKILLS)
        },
        "custom_names": dict(workspace["cname"]),
        "custom_notes": dict(workspace["cnotes"]),
        "weapon_designations": dict(workspace["hexflag"]),
        "weapons": [
            (weapon["name"], weapon["designated"], weapon["attack_bonus"])
            for weapon in workspace["weapons"]
        ],
    }


class TestHandlerCatalog(unittest.TestCase):
    def test_patterns_and_handler_ids_are_unique(self):
        patterns = [(spec.type_name, spec.subtype) for spec in registry.HANDLERS]
        handler_ids = [spec.handler_id for spec in registry.HANDLERS]

        self.assertTrue(patterns)
        self.assertEqual(len(patterns), len(set(patterns)))
        self.assertEqual(len(handler_ids), len(set(handler_ids)))
        self.assertEqual(len(registry.HANDLER_BY_PATTERN), len(patterns))

    def test_every_handler_has_complete_machine_routable_metadata(self):
        allowed_modes = {"apply", "pass_through"}
        known_families = set(engine.FAMILY_CATALOG)

        for spec in (*registry.HANDLERS, registry.LANGUAGE_HANDLER):
            with self.subTest(handler_id=spec.handler_id):
                self.assertTrue(spec.handler_id)
                self.assertTrue(spec.type_name)
                self.assertTrue(spec.subtype)
                self.assertTrue(spec.affects)
                self.assertLessEqual(set(spec.affects), known_families)
                self.assertIn(spec.mode, allowed_modes)
                self.assertIsInstance(spec.requires_number, bool)
                self.assertIsInstance(spec.restrictions_supported, bool)
                self.assertEqual(spec.rules_profiles,
                                 (source.RULES_PROFILE,))

    def test_catalog_patterns_resolve_to_their_declared_handler(self):
        for spec in registry.HANDLERS:
            with self.subTest(handler_id=spec.handler_id):
                resolved = registry.handler_for({
                    "type": spec.type_name,
                    "subType": spec.subtype,
                })
                self.assertIs(resolved, spec)

        self.assertIs(
            registry.handler_for({"type": "language", "subType": "elvish"}),
            registry.LANGUAGE_HANDLER,
        )
        self.assertIsNone(
            registry.handler_for({"type": "language", "subType": ""})
        )

    def test_ledger_preserves_internal_provenance_and_stable_finding_id(self):
        character = fixture_character()
        modifier = {
            "type": "bonus",
            "subType": "initiative",
            "value": 2,
            "isGranted": True,
            "componentId": 5001,
            "friendlySubtypeName": "Synthetic Alert",
            "restriction": "only while a synthetic condition is true",
        }
        add_modifier(character, modifier, "feat")

        first = registry.classify_modifiers(character)["ledger"][0]
        second = registry.classify_modifiers(character)["ledger"][0]

        self.assertEqual(first["source_bucket"], "feat")
        self.assertEqual(first["component_id"], 5001)
        self.assertEqual(first["component_name"], "Synthetic Alert")
        self.assertEqual(first["handler_id"], "initiative.bonus")
        self.assertEqual(first["affects"], ["initiative"])
        self.assertEqual(first["rules_profile"], source.RULES_PROFILE)
        self.assertEqual(first["restriction"], modifier["restriction"])
        self.assertEqual(first["finding_id"], second["finding_id"])
        self.assertRegex(first["finding_id"], r"^finding:[0-9a-f]{16}$")


class TestFailClosedModifierClassification(unittest.TestCase):
    def test_missing_grant_or_unknown_source_never_applies_known_handler(self):
        for bucket, grant in (("feat", None), ("synthetic", True)):
            character = fixture_character()
            modifier = {"type": "bonus", "subType": "initiative", "value": 9}
            if grant is not None:
                modifier["isGranted"] = grant
            add_modifier(character, modifier, bucket)
            with self.subTest(bucket=bucket, grant=grant):
                classified = registry.classify_modifiers(character)
                self.assertEqual(classified["applied"], [])
                self.assertEqual(classified["ledger"][0]["state"], "unsupported")
                report = engine.derive_data(character)
                expected = "unknown" if bucket == "synthetic" else "unsupported"
                self.assertEqual(report["fields"]["combat.initiative.bonus"]["state"],
                                 expected)
                if bucket == "synthetic":
                    self.assertTrue(report["meta"]["source_coverage"][
                        "unclassified_nested_omitted"])

    def test_unresolved_component_never_applies_known_handler(self):
        character = fixture_character()
        add_modifier(character, {
            "type": "bonus", "subType": "initiative", "value": 9,
            "isGranted": True, "componentId": 987654321,
        })
        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["applied"], [])
        self.assertEqual(classified["ledger"][0]["state"], "unsupported")

    def test_item_effect_requires_explicit_activation_definition_flags(self):
        character = fixture_character()
        item = character["inventory"][0]
        for key in ("canEquip", "canAttune", "isConsumable"):
            item["definition"].pop(key, None)
        item["definition"]["grantedModifiers"] = [{
            "type": "bonus", "subType": "initiative", "value": 9,
            "isGranted": True,
        }]
        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["applied"], [])
        self.assertEqual(classified["ledger"][0]["state"], "unsupported")

    def test_restricted_registered_effect_is_not_applied_and_is_actionable(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        restriction = "only while a synthetic condition is true"
        add_modifier(character, {
            "type": "bonus",
            "subType": "initiative",
            "value": 99,
            "isGranted": True,
            "componentId": 5001,
            "restriction": restriction,
        })

        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["applied"], [])
        self.assertEqual(classified["ledger"][0]["state"], "unsupported")
        self.assertEqual(classified["ledger"][0]["restriction"], restriction)
        self.assertEqual(classified["ledger"][0]["affects"], ["initiative"])

        baseline_report = engine.derive_data(baseline)
        report = engine.derive_data(character)
        self.assertEqual(
            report["combat"]["initiative"]["bonus"],
            baseline_report["combat"]["initiative"]["bonus"],
        )
        finding = report["unhandled"]["items"][0]
        self.assertEqual(finding["pattern"], "bonus:initiative")
        self.assertEqual(finding["state"], "unsupported")
        self.assertTrue(finding["not_applied"])
        self.assertIsNone(finding["restriction"]["sha256"])
        self.assertEqual(finding["restriction"]["text"], "omitted_by_default")
        self.assertNotIn(restriction, json.dumps(report))
        self.assertEqual(report["trust"]["unsupported"]["initiative"],
                         ["bonus:initiative"])
        self.assertNotIn("initiative", report["trust"]["trusted"])

    def test_is_granted_false_is_inactive_and_cannot_change_arithmetic(self):
        baseline = fixture_character()
        baseline_report = engine.derive_data(baseline)
        character = copy.deepcopy(baseline)
        add_modifier(character, {
            "type": "bonus",
            "subType": "initiative",
            "value": 99,
            "isGranted": False,
        })

        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["ledger"][0]["state"], "inactive")
        self.assertEqual(classified["applied"], [])
        self.assertEqual(derived_numbers(character), derived_numbers(baseline))
        report = engine.derive_data(character)
        self.assertEqual(
            report["unhandled"]["items"],
            baseline_report["unhandled"]["items"],
        )
        self.assertEqual(
            {item["pattern"] for item in report["unhandled"]["items"]},
            {
                "item-semantic:weapon_proficiency",
                "item-semantic:weapon_property",
            },
        )

    def test_future_level_feature_modifier_is_inactive(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        feature = character["classes"][0]["classFeatures"][0]
        feature["definition"]["requiredLevel"] = 10
        add_modifier(character, {
            "type": "bonus",
            "subType": "initiative",
            "value": 99,
            "componentId": feature["definition"]["id"],
            "isGranted": True,
        })

        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["ledger"][0]["state"], "inactive")
        self.assertEqual(classified["applied"], [])
        self.assertEqual(derived_numbers(character), derived_numbers(baseline))

    def test_aggregate_item_bucket_is_never_authoritative(self):
        baseline = fixture_character()
        effect = {
            "type": "bonus",
            "subType": "initiative",
            "value": 4,
            "isGranted": True,
        }

        inactive = copy.deepcopy(baseline)
        inactive_item = inactive["inventory"][0]
        inactive_item["equipped"] = False
        inactive_item["definition"]["grantedModifiers"] = [copy.deepcopy(effect)]
        add_modifier(inactive, effect, "item")
        inactive_result = registry.classify_modifiers(inactive)
        self.assertEqual(inactive_result["applied"], [])
        self.assertEqual([row["state"] for row in inactive_result["ledger"]],
                         ["inactive", "inactive"])
        self.assertEqual(derived_numbers(inactive)["initiative"],
                         derived_numbers(baseline)["initiative"])

        active = copy.deepcopy(baseline)
        active_item = active["inventory"][0]
        active_item["equipped"] = True
        active_item["definition"]["grantedModifiers"] = [copy.deepcopy(effect)]
        add_modifier(active, effect, "item")
        active_result = registry.classify_modifiers(active)
        aggregate = [row for row in active_result["ledger"]
                     if row["item_id"] is None][0]
        concrete = [row for row in active_result["ledger"]
                    if row["item_id"] == active_item["id"]][0]
        self.assertEqual(aggregate["state"], "inactive")
        self.assertEqual(concrete["state"], "applied")
        self.assertEqual(concrete["item_name"],
                         active_item["definition"]["name"])
        self.assertEqual(len(active_result["applied"]), 1)
        self.assertEqual(
            derived_numbers(active)["initiative"],
            derived_numbers(baseline)["initiative"] + 4,
        )

    def test_unmatched_aggregate_item_effect_is_unsupported(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        add_modifier(character, {
            "type": "bonus", "subType": "initiative", "value": 7,
            "isGranted": True,
        }, "item")

        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["applied"], [])
        self.assertEqual(classified["ledger"][0]["state"], "unsupported")
        report = engine.derive_data(character)
        self.assertEqual(report["combat"]["initiative"]["bonus"],
                         engine.derive_data(baseline)["combat"]["initiative"]["bonus"])
        self.assertEqual(
            report["fields"]["combat.initiative.bonus"]["state"],
            "unsupported")
        self.assertIn("bonus:initiative",
                      report["trust"]["unsupported"]["initiative"])

    def test_aggregate_item_matching_consumes_concrete_grants_once(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        effect = {
            "type": "bonus", "subType": "initiative", "value": 4,
            "isGranted": True,
        }
        item = character["inventory"][0]
        item["equipped"] = True
        item["definition"]["grantedModifiers"] = [copy.deepcopy(effect)]
        add_modifier(character, copy.deepcopy(effect), "item")
        add_modifier(character, copy.deepcopy(effect), "item")

        classified = registry.classify_modifiers(character)
        aggregate_states = [
            row["state"] for row in classified["ledger"]
            if row["item_id"] is None
        ]
        self.assertEqual(aggregate_states, ["inactive", "unsupported"])
        self.assertEqual(len(classified["applied"]), 1)

        report = engine.derive_data(character)
        self.assertEqual(
            report["combat"]["initiative"]["bonus"],
            engine.derive_data(baseline)["combat"]["initiative"]["bonus"] + 4,
        )
        self.assertEqual(
            report["fields"]["combat.initiative.bonus"]["state"],
            "unsupported",
        )
        self.assertIn("bonus:initiative",
                      report["trust"]["unsupported"]["initiative"])

    def test_attunement_evidence_controls_attunable_item_effects(self):
        character = fixture_character()
        item = character["inventory"][0]
        item["definition"]["canAttune"] = True
        item["definition"]["grantedModifiers"] = [{
            "type": "bonus",
            "subType": "initiative",
            "value": 3,
            "isGranted": True,
        }]
        item["equipped"] = True
        item["isAttuned"] = False

        unattuned = registry.classify_modifiers(character)
        self.assertEqual(unattuned["ledger"][0]["state"], "inactive")
        self.assertEqual(unattuned["applied"], [])

        item["isAttuned"] = True
        attuned = registry.classify_modifiers(character)
        self.assertEqual(attuned["ledger"][0]["state"], "applied")
        self.assertEqual(attuned["applied"][0]["_handler_id"],
                         "initiative.bonus")

        item["equipped"] = False
        unequipped = registry.classify_modifiers(character)
        self.assertEqual(unequipped["ledger"][0]["state"], "inactive")
        self.assertEqual(unequipped["applied"], [])

    def test_stashed_passive_item_effect_is_not_applied(self):
        character = fixture_character()
        container, item = character["inventory"][:2]
        character["characterValues"] = [{
            "typeId": 8,
            "valueId": container["id"],
            "value": "Stash at the synthetic inn",
        }]
        item["containerEntityId"] = container["id"]
        item["definition"].update({
            "canEquip": False,
            "canAttune": False,
            "isConsumable": False,
            "grantedModifiers": [{
                "type": "bonus",
                "subType": "initiative",
                "value": 9,
                "isGranted": True,
            }],
        })

        classified = registry.classify_modifiers(character)
        row = next(entry for entry in classified["ledger"]
                   if entry["item_id"] == item["id"])
        self.assertEqual(row["state"], "inactive")
        self.assertFalse(row["activation_evidence"]["carried"])
        self.assertEqual(classified["applied"], [])

    def test_unknown_item_parent_is_unsupported_not_silently_inactive(self):
        character = fixture_character()
        item = character["inventory"][0]
        item["containerEntityId"] = 987654321
        item["definition"].update({
            "canEquip": False,
            "canAttune": False,
            "isConsumable": False,
            "grantedModifiers": [{
                "type": "bonus",
                "subType": "initiative",
                "value": 9,
                "isGranted": True,
            }],
        })

        classified = registry.classify_modifiers(character)
        row = next(entry for entry in classified["ledger"]
                   if entry["item_id"] == item["id"])
        self.assertEqual(row["state"], "unsupported")
        self.assertIsNone(row["activation_evidence"]["carried"])
        self.assertEqual(classified["applied"], [])

    def test_malformed_bool_and_nonfinite_operands_are_invalid(self):
        malformed = (None, "5", True, [], {}, math.nan, math.inf, -math.inf,
                     10 ** 100)
        for value in malformed:
            with self.subTest(value=repr(value)):
                character = fixture_character()
                add_modifier(character, {
                    "type": "bonus",
                    "subType": "initiative",
                    "value": value,
                    "isGranted": True,
                })
                classified = registry.classify_modifiers(character)
                self.assertEqual(classified["applied"], [])
                self.assertEqual(classified["ledger"][0]["state"], "invalid")
                self.assertEqual(classified["ledger"][0]["affects"],
                                 ["initiative"])

    def test_finite_integer_operands_are_numeric(self):
        for value in (0, -2, 2):
            with self.subTest(value=value):
                character = fixture_character()
                add_modifier(character, {
                    "type": "bonus",
                    "subType": "initiative",
                    "value": value,
                    "isGranted": True,
                })
                classified = registry.classify_modifiers(character)
                self.assertEqual(classified["ledger"][0]["state"], "applied")
                self.assertEqual(classified["applied"][0]["value"], value)

    def test_non_integer_modifier_operands_are_invalid(self):
        for value in (2.0, 2.5):
            with self.subTest(value=value):
                character = fixture_character()
                add_modifier(character, {
                    "type": "bonus",
                    "subType": "initiative",
                    "value": value,
                    "isGranted": True,
                })
                classified = registry.classify_modifiers(character)
                self.assertEqual(classified["ledger"][0]["state"], "invalid")
                self.assertEqual(classified["applied"], [])

    def test_unresolved_per_level_hp_grant_is_not_scaled_or_applied(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        add_modifier(character, {
            "type": "bonus",
            "subType": "hit-points-per-level",
            "value": 10,
            "componentId": 999999,
            "isGranted": True,
        })

        classified = registry.classify_modifiers(character)
        row = classified["ledger"][0]
        self.assertEqual(row["state"], "unsupported")
        self.assertIn("could not be resolved", row["reason"])
        self.assertEqual(classified["applied"], [])

        report = engine.derive_data(character)
        self.assertEqual(report["combat"]["hp"]["max"],
                         engine.derive_data(baseline)["combat"]["hp"]["max"])
        self.assertEqual(report["trust"]["unsupported"]["hp"],
                         ["bonus:hit-points-per-level"])

    def test_resolved_per_level_hp_grant_uses_granting_class_level(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        add_modifier(character, {
            "type": "bonus",
            "subType": "hit-points-per-level",
            "value": 2,
            "componentId": 5001,
            "isGranted": True,
        })

        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["ledger"][0]["state"], "applied")
        self.assertEqual(classified["applied"][0]["_handler_id"], "hp.per-level")
        self.assertEqual(
            derived_numbers(character)["hp_max"],
            derived_numbers(baseline)["hp_max"] + 2 * 3,
        )

    def test_subclass_hp_grant_uses_its_class_not_total_character_level(self):
        character = fixture_character()
        second = copy.deepcopy(character["classes"][0])
        second.update(level=4, classFeatures=[])
        second["definition"].update(id=8800, name="Synthetic Second Class")
        second["subclassDefinition"] = {
            "id": 8801, "name": "Synthetic Subclass",
            "classFeatures": [{"definition": {
                "id": 8802, "name": "Synthetic Durable Feature",
                "requiredLevel": 1,
            }}],
        }
        character["classes"].append(second)
        baseline = copy.deepcopy(character)
        add_modifier(character, {
            "type": "bonus", "subType": "hit-points-per-level", "value": 1,
            "componentId": 8802, "isGranted": True,
        }, "class")

        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["applied"][0]["_granting_class_level"], 4)
        self.assertEqual(derived_numbers(character)["hp_max"],
                         derived_numbers(baseline)["hp_max"] + 4)


class TestUnsupportedAndUnknownRouting(unittest.TestCase):
    def _assert_unknown_modifier(self, modifier, pattern):
        character = fixture_character()
        add_modifier(character, modifier)
        classified = registry.classify_modifiers(character)
        self.assertEqual(classified["ledger"][0]["state"], "unsupported")
        self.assertEqual(classified["ledger"][0]["affects"], ["unknown"])
        self.assertEqual(classified["applied"], [])

        report = engine.derive_data(character)
        item = report["unhandled"]["items"][0]
        self.assertEqual(item["pattern"], pattern)
        self.assertEqual(item["possibly_affects"], ["unknown"])
        self.assertEqual(set(report["trust"]["unknown"]),
                         set(engine.TRUST_FAMILIES))
        self.assertEqual(report["trust"]["trusted"], [])
        self.assertEqual(report["unhandled"]["verified_clean"], [])
        for patterns in report["trust"]["unknown"].values():
            self.assertEqual(patterns, [pattern])
        return report

    def test_wis_score_alias_is_unsupported_and_cannot_change_wisdom(self):
        baseline = derived_numbers(fixture_character())
        report = self._assert_unknown_modifier({
            "type": "bonus",
            "subType": "wis-score",
            "value": 20,
            "isGranted": True,
        }, "bonus:wis-score")
        self.assertEqual(report["abilities"]["wis"]["score"], baseline["wis"])

    def test_ability_cap_without_exact_target_is_unsupported(self):
        character = fixture_character()
        character["stats"][0]["value"] = 20
        character["bonusStats"] = [{"id": ability_id,
                                     "value": 5 if ability_id == 1 else 0}
                                    for ability_id in range(1, 7)]
        add_modifier(character, {
            "type": "bonus",
            "subType": "ability-score-maximum",
            "value": 5,
            "isGranted": True,
        })

        report = engine.derive_data(character)
        self.assertEqual(report["abilities"]["str"]["score"], 20)
        self.assertEqual(report["trust"]["unsupported"]["abilities"],
                         ["bonus:ability-score-maximum"])
        self.assertEqual(report["trust"]["unknown"], {})

    def test_dual_wield_ac_effect_is_unsupported_and_cannot_change_ac(self):
        baseline = derived_numbers(fixture_character())
        report = self._assert_unknown_modifier({
            "type": "bonus",
            "subType": "dual-wield-armor-class",
            "value": 20,
            "isGranted": True,
        }, "bonus:dual-wield-armor-class")
        self.assertEqual(report["combat"]["ac"]["value"], baseline["ac"])

    def test_sleep_immunity_is_unsupported_not_silently_claimed(self):
        self._assert_unknown_modifier({
            "type": "immunity",
            "subType": "sleep",
            "value": None,
            "isGranted": True,
        }, "immunity:sleep")

    def test_arbitrary_unknown_pattern_has_global_unknown_scope(self):
        self._assert_unknown_modifier({
            "type": "synthetic-unknown-type",
            "subType": "synthetic-unknown-subtype",
            "value": 1,
            "isGranted": True,
        }, "synthetic-unknown-type:synthetic-unknown-subtype")

    def test_previously_assumed_character_values_are_explicitly_unsupported(self):
        unused_type_ids = (10, 18, 19, 22)
        self.assertTrue(set(unused_type_ids).isdisjoint(
            registry.CHARACTER_VALUE_HANDLERS))

        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        character["characterValues"] = [
            {"typeId": type_id, "valueId": 1, "value": 999}
            for type_id in unused_type_ids
        ]
        ledger = registry.classify_character_values(character)
        self.assertEqual([row["state"] for row in ledger],
                         ["unsupported"] * len(unused_type_ids))
        self.assertTrue(all(row["handler_id"] is None for row in ledger))
        self.assertEqual(derived_numbers(character), derived_numbers(baseline))

        report = engine.derive_data(character)
        character_value_patterns = {
            f"characterValues typeId {type_id}"
            for type_id in unused_type_ids
        }
        baseline_weapon_gaps = {
            "item-semantic:weapon_proficiency",
            "item-semantic:weapon_property",
        }
        self.assertEqual(
            {item["pattern"] for item in report["unhandled"]["items"]},
            character_value_patterns
            | baseline_weapon_gaps
            | {"source:unclassified-fields-omitted"},
        )
        self.assertTrue(report["meta"]["source_coverage"][
            "unclassified_nested_omitted"])
        self.assertEqual(set(report["trust"]["unknown"]),
                         set(engine.TRUST_FAMILIES))


class TestCharacterValueIsolation(unittest.TestCase):
    def test_oversized_numeric_character_value_is_invalid(self):
        character = fixture_character()
        character["characterValues"] = [{
            "typeId": 2, "valueId": None, "value": 10 ** 100,
        }]
        ledger = registry.classify_character_values(character)
        self.assertEqual(ledger[0]["state"], "invalid")
        report = engine.derive_data(character)
        self.assertEqual(report["fields"]["combat.ac.value"]["state"],
                         "invalid")
        self.assertLess(report["combat"]["ac"]["value"],
                        registry.MAX_MECHANICAL_MAGNITUDE)

    def test_zero_and_conflicting_ability_overrides_do_not_silently_win(self):
        baseline = fixture_character()
        for values, expected_state in ((
                [{"typeId": 41, "valueId": 1, "value": 0}], "invalid"), (
                [{"typeId": 41, "valueId": 1, "value": 18},
                 {"typeId": 41, "valueId": 1, "value": 19}], "unsupported")):
            character = copy.deepcopy(baseline)
            character["characterValues"] = values
            rows = registry.classify_character_values(character)
            with self.subTest(values=values):
                self.assertTrue(all(row["state"] == expected_state for row in rows))
                self.assertEqual(derived_numbers(character), derived_numbers(baseline))

    def test_weapon_designation_rejects_non_weapon_inventory_target(self):
        character = fixture_character()
        armor_id = character["inventory"][0]["id"]
        character["characterValues"] = [{
            "typeId": 28, "valueId": armor_id, "value": True,
        }]
        row = registry.classify_character_values(character)[0]
        self.assertEqual(row["state"], "unsupported")
        self.assertNotIn("normalized", row)

    def test_known_handlers_require_resolved_targets(self):
        cases = (
            ({"typeId": 8, "valueId": "missing-item", "value": "name"},
             ("inventory",)),
            ({"typeId": 28, "valueId": "missing-item", "value": True},
             ("attacks", "weapons")),
            ({"typeId": 24, "valueId": 999, "value": 5}, ("skills",)),
            ({"typeId": 39, "valueId": 99, "value": 5}, ("abilities",)),
        )
        baseline = fixture_character()
        expected = workspace_signature(engine.build(baseline))
        for value, affects in cases:
            with self.subTest(value=value):
                character = copy.deepcopy(baseline)
                character["characterValues"] = [value]
                workspace = engine.build(character)
                row = workspace["character_value_ledger"][0]
                self.assertEqual(row["state"], "unsupported")
                self.assertEqual(tuple(row["affects"]), affects)
                self.assertNotIn("normalized", row)
                self.assertEqual(workspace_signature(workspace), expected)

    def test_known_enumerations_reject_out_of_range_values(self):
        for value in (
                {"typeId": 26, "valueId": 14, "value": 9},
                {"typeId": 27, "valueId": 14, "value": 9}):
            with self.subTest(value=value):
                character = fixture_character()
                character["characterValues"] = [value]
                row = engine.build(character)["character_value_ledger"][0]
                self.assertEqual(row["state"], "invalid")
                self.assertNotIn("normalized", row)

    def test_malformed_known_values_are_invalid_and_cannot_affect_build(self):
        """Every known raw shape that used to reach ``int``/maps is gated."""
        cases = (
            ("boolean AC override",
             {"typeId": 1, "valueId": None, "value": True}, ("ac",)),
            ("nonnumeric AC adjustment",
             {"typeId": 2, "valueId": None, "value": "not-a-number"},
             ("ac",)),
            ("object custom name",
             {"typeId": 8, "valueId": "3", "value": {"name": "bad"}},
             ("inventory",)),
            ("array custom note",
             {"typeId": 9, "valueId": "4", "value": ["bad"]},
             ("inventory",)),
            ("nonnumeric skill bonus",
             {"typeId": 24, "valueId": 14, "value": "not-a-number"},
             ("skills",)),
            ("boolean skill proficiency",
             {"typeId": 26, "valueId": 14, "value": True},
             ("skills",)),
            ("boolean skill ability override",
             {"typeId": 27, "valueId": 14, "value": True},
             ("skills",)),
            ("object weapon designation",
             {"typeId": 28, "valueId": "3", "value": {"enabled": True}},
             ("attacks", "weapons")),
            ("boolean ability bonus",
             {"typeId": 39, "valueId": 5, "value": True},
             ("abilities",)),
            ("object ability override",
             {"typeId": 41, "valueId": 5, "value": {"score": 20}},
             ("abilities",)),
            ("malformed numeric target id",
             {"typeId": 40, "valueId": "not-an-ability", "value": 5},
             ("abilities",)),
        )
        baseline = fixture_character()
        expected = workspace_signature(engine.build(baseline))

        for label, value, affects in cases:
            with self.subTest(case=label):
                character = copy.deepcopy(baseline)
                character["characterValues"] = [copy.deepcopy(value)]
                workspace = engine.build(character)
                row = workspace["character_value_ledger"][0]

                self.assertEqual(row["state"], "invalid")
                self.assertEqual(tuple(row["affects"]), affects)
                self.assertNotIn("normalized", row)
                self.assertIn(row, workspace["unhandled_details"])
                self.assertEqual(workspace_signature(workspace), expected)

    def test_invalid_known_value_routes_to_invalid_public_trust_lane(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        character["characterValues"] = [{
            "typeId": 2,
            "valueId": None,
            "value": True,
        }]

        report = engine.derive_data(character)
        baseline_report = engine.derive_data(baseline)
        self.assertEqual(report["combat"]["ac"]["value"],
                         baseline_report["combat"]["ac"]["value"])
        item = report["unhandled"]["items"][0]
        self.assertEqual(item["pattern"], "characterValues typeId 2")
        self.assertEqual(item["state"], "invalid")
        self.assertTrue(item["not_applied"])
        self.assertEqual(item["possibly_affects"], ["ac"])
        self.assertEqual(report["trust"]["invalid"]["ac"],
                         ["characterValues typeId 2"])
        self.assertNotIn("ac", report["trust"]["trusted"])

    def test_valid_integer_string_is_normalized_before_arithmetic(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        character["characterValues"] = [{
            "typeId": 2,
            "valueId": None,
            "value": "2",
        }]

        workspace = engine.build(character)
        row = workspace["character_value_ledger"][0]
        self.assertEqual(row["state"], "applied")
        self.assertEqual(row["normalized"]["value"], 2)
        self.assertIsInstance(row["normalized"]["value"], int)
        self.assertEqual(workspace["ac"], engine.build(baseline)["ac"] + 2)

    def test_arbitrary_unknown_character_value_id_remains_unsupported(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        character["characterValues"] = [{
            "typeId": 987654,
            "valueId": 5,
            "value": 999,
        }]

        # This is an internal classifier isolation check. The public raw
        # workspace correctly refuses to discard the source-coverage signal.
        workspace = engine.build(character, _privacy_filtered=True)
        row = workspace["character_value_ledger"][0]
        self.assertEqual(row["state"], "unsupported")
        self.assertEqual(row["affects"], ["unknown"])
        self.assertIsNone(row["handler_id"])
        self.assertNotIn("normalized", row)
        self.assertEqual(workspace_signature(workspace),
                         workspace_signature(engine.build(baseline)))

        report = engine.derive_data(character)
        self.assertEqual(report["unhandled"]["items"][0]["state"],
                         "unsupported")
        self.assertEqual(set(report["trust"]["unknown"]),
                         set(engine.TRUST_FAMILIES))


class TestArithmeticIsolation(unittest.TestCase):
    def test_raw_modifier_effects_cannot_bypass_classifier_output(self):
        baseline = fixture_character()
        character = copy.deepcopy(baseline)
        add_modifier(character, {
            "type": "bonus",
            "subType": "initiative",
            "value": 100,
            "isGranted": True,
        })
        add_modifier(character, {
            "type": "bonus",
            "subType": "wisdom-score",
            "value": 100,
            "isGranted": True,
        })

        empty_classification = {"ledger": [], "applied": []}
        with mock.patch.object(registry, "classify_modifiers",
                               return_value=empty_classification):
            workspace = engine.build(character)

        baseline_workspace = engine.build(baseline)
        self.assertEqual(workspace["init"], baseline_workspace["init"])
        self.assertEqual(workspace["A"][5], baseline_workspace["A"][5])
        self.assertEqual(workspace["mods"], [])

    def test_only_normalized_handler_tagged_modifiers_reach_workspace(self):
        character = fixture_character()
        add_modifier(character, {
            "type": "bonus",
            "subType": "initiative",
            "value": 2,
            "isGranted": True,
        })
        add_modifier(character, {
            "type": "bonus",
            "subType": "initiative",
            "value": 50,
            "restriction": "synthetic restriction",
            "isGranted": True,
        })

        workspace = engine.build(character)
        self.assertEqual(len(workspace["mods"]), 1)
        self.assertEqual(workspace["mods"][0]["_handler_id"],
                         "initiative.bonus")
        self.assertEqual(workspace["mods"][0]["_source_bucket"], "feat")
        self.assertEqual(workspace["init"], 2)
        self.assertEqual(workspace["modifier_ledger"][1]["state"],
                         "unsupported")


if __name__ == "__main__":
    unittest.main()
