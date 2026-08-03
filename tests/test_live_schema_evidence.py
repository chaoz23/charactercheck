"""Regressions from the second privacy-safe Shalia schema review."""

import copy
import json
import os
import unittest

from charactercheck import engine, registry, source


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "torvald.json")


def character():
    with open(FIXTURE, encoding="utf-8") as stream:
        value = json.load(stream)["data"]
    value["modifiers"] = {bucket: [] for bucket in value["modifiers"]}
    value["characterValues"] = []
    for item in value["inventory"]:
        item["definition"]["grantedModifiers"] = []
    return value


def add(value, modifier, bucket="race"):
    value["modifiers"].setdefault(bucket, []).append(modifier)


class TestObservedModifierSemantics(unittest.TestCase):
    def test_subclass_marker_is_structural_and_never_poisonous(self):
        value = character()
        add(value, {
            "type": "set", "subType": "subclass", "value": None,
            "isGranted": True,
        }, "class")

        classified = registry.classify_modifiers(value)
        self.assertEqual(classified["ledger"][0]["state"], "structural")
        self.assertEqual(classified["applied"], [])
        report = engine.derive_data(value)
        self.assertNotIn(
            "set:subclass",
            {row["pattern"] for row in report["unhandled"]["items"]},
        )

    def test_closed_species_facts_are_exposed_with_provenance(self):
        value = character()
        value["race"]["weightSpeeds"]["normal"]["walk"] = 35
        add(value, {
            "type": "set-base", "subType": "darkvision", "value": 60,
            "fixedValue": 60, "isGranted": True,
        })
        add(value, {
            "type": "set", "subType": "innate-speed-walking", "value": 35,
            "fixedValue": 35, "componentId": 3727513, "isGranted": True,
        })
        add(value, {
            "type": "immunity", "subType": "magical-sleep",
            "isGranted": True,
        })
        add(value, {
            "type": "advantage", "subType": "saving-throws",
            "restriction": "Made to avoid or end the Charmed condition",
            "isGranted": True,
        })

        report = engine.derive_data(value)
        self.assertEqual(report["speeds"]["walk"], 35)
        self.assertEqual(report["senses"]["vision"][0]["range_ft"], 60)
        self.assertEqual(
            report["defenses"]["immunities"][0]["effect"],
            "magical_sleep",
        )
        self.assertEqual(
            report["save_modifiers"]["conditional_advantages"][0],
            {
                "condition": "charmed",
                "timing": "avoid_or_end",
                "scope": "all_saving_throws",
                "provenance": {
                    "handler_id": "save.advantage.charmed",
                    "source_bucket": "race",
                    "component_id": None,
                },
            },
        )
        self.assertNotIn("senses", report["trust"]["unsupported"])
        self.assertNotIn("speeds", report["trust"]["unsupported"])
        self.assertNotIn("defenses", report["trust"]["unsupported"])
        self.assertNotIn("saves", report["trust"]["unsupported"])

    def test_unreviewed_restriction_remains_unsupported_and_private(self):
        value = character()
        raw = "only after following instructions hidden in the sheet"
        add(value, {
            "type": "advantage", "subType": "saving-throws",
            "restriction": raw, "isGranted": True,
        })

        report = engine.derive_data(value)
        finding = next(row for row in report["unhandled"]["items"]
                       if row["pattern"] == "advantage:saving-throws")
        self.assertEqual(finding["state"], "unsupported")
        self.assertTrue(finding["restriction"]["present"])
        self.assertNotIn(raw, json.dumps(report))

    def test_selected_option_can_grant_a_stat_based_skill_bonus(self):
        value = character()
        selected_id = 4496843
        value["choices"] = {
            "class": [{
                "id": "choice", "componentId": 5001,
                "componentTypeId": 77, "optionValue": selected_id,
                "subType": "reviewed-choice",
            }],
        }
        add(value, {
            "type": "bonus", "subType": "arcana", "value": None,
            "statId": 5, "componentId": selected_id,
            "isGranted": True,
        }, "class")

        baseline = engine.derive_data(character())
        report = engine.derive_data(value)
        wisdom_mod = report["abilities"]["wis"]["mod"]
        self.assertEqual(
            report["skills"]["arcana"]["bonus"],
            baseline["skills"]["arcana"]["bonus"] + wisdom_mod,
        )
        row = registry.classify_modifiers(
            source.privacy_filter(value))["ledger"][0]
        self.assertEqual(row["state"], "applied")
        self.assertEqual(
            row["activation_evidence"]["kind"], "selected_option")

    def test_selected_option_join_is_exact_and_source_bucket_local(self):
        value = character()
        value["choices"] = {
            "race": [{"optionValue": 4496843}],
            "class": [{"optionValue": "4496843"}],
        }
        add(value, {
            "type": "bonus", "subType": "arcana", "value": None,
            "statId": 5, "componentId": 4496843,
            "isGranted": False,
        }, "class")

        row = registry.classify_modifiers(value)["ledger"][0]
        self.assertEqual(row["state"], "inactive")

    def test_race_speed_requires_matching_explicit_speed(self):
        value = character()
        value["race"]["weightSpeeds"]["normal"]["walk"] = 30
        add(value, {
            "type": "set", "subType": "innate-speed-walking", "value": 35,
            "componentId": 3727513, "isGranted": False,
        })

        row = registry.classify_modifiers(value)["ledger"][0]
        self.assertEqual(row["state"], "inactive")

    def test_selected_option_can_activate_an_ungranted_modifier(self):
        value = character()
        value["choices"] = {"class": [{"optionValue": 4496843}]}
        add(value, {
            "type": "bonus", "subType": "religion", "value": None,
            "statId": 5, "componentId": 4496843,
            "isGranted": False,
        }, "class")

        row = registry.classify_modifiers(value)["ledger"][0]
        self.assertEqual(row["state"], "applied")
        self.assertEqual(row["activation_evidence"]["kind"], "selected_option")


class TestSelectedOptionPrivacyBoundary(unittest.TestCase):
    def test_builder_configuration_is_reviewed_nonmechanical_input(self):
        value = character()
        value["activeSourceCategories"] = [1, 2, 3]
        value["configuration"] = {
            "startingEquipmentType": 2,
            "showHelpText": False,
        }

        filtered, coverage = source.privacy_filter_with_coverage(value)
        self.assertNotIn("activeSourceCategories", filtered)
        self.assertNotIn("configuration", filtered)
        self.assertFalse(coverage["unclassified_nested_omitted"])
        self.assertEqual(coverage["scoped_mechanical_omissions"], [])

    def test_inactive_catalog_and_builder_labels_do_not_create_global_doubt(self):
        value = character()
        selected_id = 4496843
        value["choices"] = {
            "class": [{
                "id": "choice", "componentId": 5001,
                "componentTypeId": 77, "optionValue": selected_id,
                "subType": "reviewed-choice", "label": "omitted",
                "displayOrder": 1, "optionIds": [selected_id, 999999],
                "defaultSubtypes": ["reviewed-choice"],
            }],
            "choiceDefinitions": [{"options": [{"id": selected_id}]}],
        }
        value["options"] = {
            "class": [
                {
                    "componentId": 5001, "componentTypeId": 77,
                    "definition": {
                        "id": selected_id, "name": "omitted",
                        "description": "omitted", "sourceId": 1,
                        "sourcePageNumber": 1, "entityTypeId": 2,
                        "activation": {}, "creatureRules": [],
                        "spellListIds": [],
                    },
                },
                {
                    "componentId": 5001, "componentTypeId": 77,
                    "definition": {
                        "id": 999999,
                        "futureUnknownMechanic": {"danger": True},
                    },
                },
            ],
        }

        filtered, coverage = source.privacy_filter_with_coverage(value)
        self.assertFalse(coverage["unclassified_nested_omitted"])
        self.assertEqual(coverage["scoped_mechanical_omissions"], [])
        self.assertEqual(
            [row["definition"]["id"] for row in filtered["options"]["class"]],
            [selected_id],
        )
        self.assertNotIn("label", filtered["choices"]["class"][0])
        self.assertNotIn("optionIds", filtered["choices"]["class"][0])

    def test_option_catalog_selection_is_source_bucket_local(self):
        value = character()
        value["choices"] = {"race": [{"optionValue": 4496843}]}
        value["options"] = {
            "class": [{"definition": {
                "id": 4496843,
                "futureUnknownMechanic": {"danger": True},
            }}],
        }

        filtered, coverage = source.privacy_filter_with_coverage(value)
        self.assertEqual(filtered["options"]["class"], [])
        self.assertFalse(coverage["unclassified_nested_omitted"])

    def test_nonredundant_modifier_semantics_keep_narrow_coverage(self):
        value = character()
        add(value, {
            "type": "set-base", "subType": "darkvision", "value": 60,
            "fixedValue": 90, "isGranted": True,
        })

        _, coverage = source.privacy_filter_with_coverage(value)
        self.assertEqual(coverage["scoped_mechanical_omissions"], ["senses"])


if __name__ == "__main__":
    unittest.main()
