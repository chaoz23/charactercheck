"""Contract tests for the pinned, offline DDB semantic registry."""

from importlib import resources
import json
from pathlib import Path
import tempfile
import unittest

from charactercheck import ddb_registry
from charactercheck import engine


EXPECTED_FINGERPRINT = (
    "56c8300477353d9a57344e3c89185d3d6a6c4099647fd4320569350b509fbd6f")


def bundled_payload():
    resource = resources.files("charactercheck").joinpath(
        ddb_registry.REGISTRY_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


class RegistryFile:
    def __init__(self, contents):
        self.contents = contents
        self.directory = None
        self.path = None

    def __enter__(self):
        self.directory = tempfile.TemporaryDirectory(
            dir=str(Path(tempfile.gettempdir()).resolve()))
        self.path = Path(self.directory.name) / "registry.json"
        if isinstance(self.contents, str):
            serialized = self.contents
        else:
            serialized = json.dumps(self.contents)
        self.path.write_text(serialized, encoding="utf-8")
        return self.path

    def __exit__(self, exc_type, exc_value, traceback):
        self.directory.cleanup()


class TestBundledDDBRegistry(unittest.TestCase):
    def test_purpose_limited_seeded_semantics_and_gaps_are_preserved(self):
        registry = ddb_registry.DDB_REGISTRY

        self.assertEqual(dict(registry.armor_types), {
            1: "Light Armor", 2: "Medium Armor",
            3: "Heavy Armor", 4: "Shield",
        })
        self.assertEqual(dict(registry.range_types), {
            1: "Melee", 2: "Ranged",
        })
        self.assertEqual(len(registry.damage_types), 13)
        self.assertEqual(registry.damage_types[1], "Bludgeoning")
        self.assertEqual(registry.damage_types[13], "Force")
        self.assertEqual(registry.dice_values, (4, 6, 8, 10, 12))
        self.assertEqual(len(registry.weapon_properties), 12)
        self.assertEqual(registry.weapon_properties[2], "Finesse")
        self.assertEqual(registry.weapon_properties[4], "Light")
        self.assertEqual(registry.weapon_properties[5], "Loading")
        self.assertEqual(registry.weapon_properties[11], "Two-Handed")
        self.assertEqual(registry.weapon_properties[18], "Cleave")
        self.assertEqual(registry.weapon_properties[25], "Vex")
        # Observed catalog values outside current evaluator dependencies stay
        # out of the distributed allowlist and therefore fail closed.
        self.assertNotIn(1, registry.weapon_properties)
        self.assertNotIn(12, registry.weapon_properties)
        self.assertNotIn(56, registry.weapon_properties)

    def test_lookup_is_explicit_and_unknown_ids_remain_unknown(self):
        registry = ddb_registry.DDB_REGISTRY

        self.assertEqual(registry.lookup("armor_types", 4), "Shield")
        self.assertEqual(registry.lookup("range_types", 2), "Ranged")
        self.assertIsNone(registry.lookup("weapon_properties", 999999))
        with self.assertRaises(KeyError):
            registry.lookup("dice_values", 20)
        with self.assertRaises(TypeError):
            registry.lookup("armor_types", True)

    def test_every_distributed_weapon_property_has_a_declared_consumer(self):
        self.assertEqual(set(ddb_registry.WEAPON_PROPERTIES),
                         set(engine.WEAPON_PROPERTY_CONSUMERS))
        self.assertEqual(engine.MASTERIES, {
            "Cleave", "Graze", "Nick", "Push",
            "Sap", "Slow", "Topple", "Vex",
        })

    def test_every_exposed_layer_is_immutable(self):
        registry = ddb_registry.DDB_REGISTRY

        with self.assertRaises(TypeError):
            registry.armor_types[5] = "Synthetic Armor"
        with self.assertRaises(TypeError):
            registry.tables["armor_types"] = {}
        with self.assertRaises(TypeError):
            registry.metadata["source_url"] = "https://example.invalid"
        with self.assertRaises(TypeError):
            registry.metadata["cross_check"]["license"] = "Unknown"
        self.assertIsInstance(registry.metadata["attribution"]["copyright"],
                              tuple)

    def test_fingerprint_and_observation_metadata_are_reproducible(self):
        registry = ddb_registry.DDB_REGISTRY

        self.assertEqual(registry.fingerprint, EXPECTED_FINGERPRINT)
        self.assertEqual(ddb_registry.REGISTRY_FINGERPRINT,
                         EXPECTED_FINGERPRINT)
        self.assertEqual(
            registry.metadata["semantic_fingerprint_sha256"],
            EXPECTED_FINGERPRINT,
        )
        self.assertEqual(
            registry.metadata["source_url"],
            "https://www.dndbeyond.com/api/config/json",
        )
        self.assertEqual(registry.metadata["cross_check"]["license"], "MIT")
        self.assertTrue(registry.metadata["cross_check"]
                        ["allowlisted_subset_match"])

    def test_a_fresh_load_has_the_same_semantics(self):
        loaded = ddb_registry.load_registry()

        self.assertIsNot(loaded, ddb_registry.DDB_REGISTRY)
        self.assertEqual(loaded.fingerprint,
                         ddb_registry.DDB_REGISTRY.fingerprint)
        self.assertEqual(dict(loaded.weapon_properties),
                         dict(ddb_registry.WEAPON_PROPERTIES))


class TestDDBRegistryValidation(unittest.TestCase):
    def assert_invalid(self, payload, message=None):
        with RegistryFile(payload) as path:
            with self.assertRaises(ddb_registry.DDBRegistryError) as raised:
                ddb_registry.load_registry(path)
        if message is not None:
            self.assertIn(message, str(raised.exception))

    def test_root_and_table_shapes_are_closed(self):
        missing = bundled_payload()
        missing["tables"].pop("range_types")
        self.assert_invalid(missing, "missing=['range_types']")

        extra = bundled_payload()
        extra["tables"]["synthetic_types"] = []
        self.assert_invalid(extra, "extra=['synthetic_types']")

        wrong_schema = bundled_payload()
        wrong_schema["schema_version"] = "future"
        self.assert_invalid(wrong_schema, "unsupported registry schema")

    def test_duplicate_and_unsorted_ids_are_rejected(self):
        duplicate = bundled_payload()
        duplicate["tables"]["armor_types"].append(
            {"id": 4, "name": "Duplicate Shield"})
        self.assert_invalid(duplicate, "duplicate id 4")

        unsorted = bundled_payload()
        unsorted["tables"]["range_types"].reverse()
        self.assert_invalid(unsorted, "strictly sorted by id")

    def test_duplicate_and_unsorted_dice_are_rejected(self):
        duplicate = bundled_payload()
        duplicate["tables"]["dice_values"].insert(2, 6)
        self.assert_invalid(duplicate, "duplicate value 6")

        unsorted = bundled_payload()
        unsorted["tables"]["dice_values"] = [6, 4]
        self.assert_invalid(unsorted, "unsorted value 4")

    def test_entry_types_and_fields_are_strict(self):
        boolean_id = bundled_payload()
        boolean_id["tables"]["armor_types"][0]["id"] = True
        self.assert_invalid(boolean_id, "positive integer")

        blank_name = bundled_payload()
        blank_name["tables"]["armor_types"][0]["name"] = " "
        self.assert_invalid(blank_name, "non-empty trimmed string")

        extra_field = bundled_payload()
        extra_field["tables"]["armor_types"][0]["description"] = "prose"
        self.assert_invalid(extra_field, "extra=['description']")

    def test_stale_fingerprint_fails_closed(self):
        changed = bundled_payload()
        changed["tables"]["armor_types"][0]["name"] = "Changed"
        self.assert_invalid(changed, "fingerprint mismatch")

    def test_metadata_shape_hashes_and_attribution_are_validated(self):
        bad_hash = bundled_payload()
        bad_hash["metadata"]["source_body_sha256"] = "not-a-hash"
        self.assert_invalid(bad_hash, "lowercase SHA-256")

        no_match = bundled_payload()
        no_match["metadata"]["cross_check"][
            "allowlisted_subset_match"] = False
        self.assert_invalid(no_match,
                            "allowlisted_subset_match must be true")

        no_attribution = bundled_payload()
        no_attribution["metadata"]["attribution"]["copyright"] = []
        self.assert_invalid(no_attribution, "must be non-empty strings")

    def test_duplicate_json_object_keys_are_rejected_before_validation(self):
        self.assert_invalid('{"schema_version": 1, "schema_version": 2}',
                            "duplicate JSON object key")

    def test_malformed_json_is_reported_as_registry_error(self):
        self.assert_invalid("{", "could not load DDB registry")


if __name__ == "__main__":
    unittest.main()
