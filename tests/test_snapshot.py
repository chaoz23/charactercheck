import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from charactercheck import engine, errors, qa, source
from charactercheck.cli import main


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "torvald.json")
OTHER = os.path.join(ROOT, "tests", "fixtures", "vexa.json")


class TestCharacterSnapshotV1(unittest.TestCase):
    def setUp(self):
        self.loaded = source.load(FIXTURE)
        self.snapshot = source.make_snapshot_object(self.loaded)

    def test_snapshot_object_is_deeply_immutable(self):
        first = self.snapshot.character()
        first["name"] = "mutated"
        self.assertNotEqual(self.snapshot.character()["name"], "mutated")

    def test_revision_is_canonical_and_excludes_observation_time(self):
        reordered = copy.deepcopy(self.loaded.character)
        reordered = dict(reversed(list(reordered.items())))
        later = source.LoadedCharacter(
            reordered, self.loaded.adapter, self.loaded.source_id,
            "2099-01-01T00:00:00Z", self.loaded.source_schema,
            self.loaded.source_schema_fingerprint)
        other = source.make_snapshot_object(later)
        self.assertEqual(self.snapshot.revision, other.revision)
        self.assertNotEqual(self.snapshot.snapshot_id, other.snapshot_id)

    def test_round_trip_revalidates_hashes(self):
        envelope = self.snapshot.to_dict()
        round_tripped = source.CharacterSnapshotV1.from_dict(envelope)
        self.assertEqual(round_tripped.revision, self.snapshot.revision)
        envelope["character"]["name"] = "tampered"
        with self.assertRaises(errors.CharacterCheckError) as caught:
            source.CharacterSnapshotV1.from_dict(envelope)
        self.assertEqual(caught.exception.kind, "snapshot_integrity")

    def test_snapshot_integrity_covers_metadata_and_privacy_claims(self):
        for mutate, expected in (
                (lambda e: e["meta"].update(observed_at="2099-01-01T00:00:00Z"),
                 "snapshot_integrity"),
                (lambda e: e["source"].update(adapter="forged-adapter"),
                 "snapshot_integrity"),
                (lambda e: e["privacy"].update(classification="mechanical+persona"),
                 "snapshot_integrity"),
                (lambda e: e["meta"].update(rules_profile="unknown-rules"),
                 "snapshot_schema")):
            envelope = self.snapshot.to_dict()
            mutate(envelope)
            with self.subTest(expected=expected), \
                    self.assertRaises(errors.CharacterCheckError) as caught:
                source.CharacterSnapshotV1.from_dict(envelope)
            self.assertEqual(caught.exception.kind, expected)

    def test_snapshot_rejects_private_fields_even_with_recomputed_hashes(self):
        envelope = self.snapshot.to_dict()
        envelope["character"]["username"] = "private-account"
        envelope["source"]["snapshot_character_hash"] = source.normalized_hash(
            envelope["character"])
        envelope["meta"]["snapshot_id"] = source._snapshot_id(envelope)
        with self.assertRaises(errors.CharacterCheckError) as caught:
            source.CharacterSnapshotV1.from_dict(envelope)
        self.assertEqual(caught.exception.kind, "snapshot_integrity")

    def test_snapshot_rejects_forged_revision_and_source_identity(self):
        for mutate in (
                lambda envelope: envelope["source"].update(
                    normalized_data_hash="sha256:" + "1" * 64),
                lambda envelope: envelope["source"].update(
                    source_id="999999999999")):
            envelope = self.snapshot.to_dict()
            mutate(envelope)
            envelope["meta"]["snapshot_id"] = source._snapshot_id(envelope)
            with self.subTest(mutate=mutate), \
                    self.assertRaises(errors.CharacterCheckError) as caught:
                source.CharacterSnapshotV1.from_dict(envelope)
            self.assertEqual(caught.exception.kind, "snapshot_integrity")

    def test_wrong_snapshot_schema_is_typed(self):
        envelope = self.snapshot.to_dict()
        envelope["schema_version"] = 999
        with self.assertRaises(errors.CharacterCheckError) as caught:
            source.CharacterSnapshotV1.from_dict(envelope)
        self.assertEqual(caught.exception.kind, "snapshot_schema")

    def test_snapshot_rejects_noncanonical_observation_time(self):
        for observed_at in (
                "not-a-time",
                "2026-07-31T12:00:00+00:00",
                "2026-07-31 12:00:00Z",
                "2026-02-30T12:00:00Z",
                "2026-07-31T12:00:00.1234567Z"):
            envelope = self.snapshot.to_dict()
            envelope["meta"]["observed_at"] = observed_at
            envelope["meta"]["snapshot_id"] = source._snapshot_id(envelope)
            with self.subTest(observed_at=observed_at), \
                    self.assertRaises(errors.CharacterCheckError) as caught:
                source.CharacterSnapshotV1.from_dict(envelope)
            self.assertEqual(caught.exception.kind, "snapshot_schema")

    def test_public_metadata_omits_path_and_url(self):
        rendered = json.dumps(self.snapshot.to_dict())
        self.assertNotIn(FIXTURE, rendered)
        self.assertNotIn("dndbeyond.com/characters/", rendered)

    def test_resnapshot_preserves_unclassified_coverage(self):
        character = copy.deepcopy(self.loaded.character)
        character["classes"][0]["definition"]["privateDiary"] = "secret"
        first = source.make_snapshot(source.LoadedCharacter(
            character, self.loaded.adapter, self.loaded.source_id,
            "2026-07-31T00:00:00Z"))
        self.assertTrue(first["source"]["coverage"][
            "unclassified_nested_omitted"])
        self.assertNotIn("secret", json.dumps(first))

        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            path = os.path.join(directory, "snapshot.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(first, stream)
            second = source.make_snapshot(source.load(path))
        self.assertEqual(second["source"]["coverage"],
                         first["source"]["coverage"])

    def test_resnapshot_preserves_scoped_coverage(self):
        character = copy.deepcopy(self.loaded.character)
        character["customSpeeds"] = [{"walk": 35}]
        first = source.make_snapshot(source.LoadedCharacter(
            character, self.loaded.adapter, self.loaded.source_id,
            "2026-07-31T00:00:00Z"))
        self.assertEqual(first["source"]["coverage"][
            "scoped_mechanical_omissions"], ["speeds"])

        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            path = os.path.join(directory, "snapshot.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(first, stream)
            second = source.make_snapshot(source.load(path))
        self.assertEqual(second["source"]["coverage"],
                         first["source"]["coverage"])

    def test_persona_changes_only_the_stored_character_hash(self):
        character = copy.deepcopy(self.loaded.character)
        character["traits"] = {"ideals": "Synthetic ideal"}
        loaded = source.LoadedCharacter(
            character, self.loaded.adapter, self.loaded.source_id,
            "2026-07-31T00:00:00Z")
        mechanical = source.make_snapshot(loaded)
        persona = source.make_snapshot(loaded, include_persona=True)
        self.assertEqual(mechanical["source"]["normalized_data_hash"],
                         persona["source"]["normalized_data_hash"])
        self.assertEqual(mechanical["source"]["normalized_data_hash"],
                         mechanical["source"]["snapshot_character_hash"])
        self.assertNotEqual(persona["source"]["normalized_data_hash"],
                            persona["source"]["snapshot_character_hash"])

    def test_maximum_raw_source_can_round_trip_larger_snapshot_envelope(self):
        with open(FIXTURE, "rb") as stream:
            raw = stream.read()
        snapshot_body = json.dumps(self.snapshot.to_dict(), indent=1).encode()
        self.assertGreater(len(snapshot_body), len(raw))
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            raw_path = os.path.join(directory, "raw.json")
            snapshot_path = os.path.join(directory, "snapshot.json")
            with open(raw_path, "wb") as stream:
                stream.write(raw)
            with open(snapshot_path, "wb") as stream:
                stream.write(snapshot_body)
            with mock.patch.object(source, "MAX_INPUT_BYTES", len(raw)), \
                    mock.patch.object(source, "MAX_SNAPSHOT_BYTES",
                                      len(snapshot_body)):
                source.load(raw_path)
                loaded_snapshot = source.load(snapshot_path)
                source.load_snapshot(snapshot_path)
        self.assertEqual(loaded_snapshot.character["id"], self.loaded.character["id"])


class TestSnapshotProjections(unittest.TestCase):
    def _snapshot_file(self, directory, source_ref=FIXTURE):
        path = os.path.join(directory, "snapshot.json")
        with open(path, "w") as stream:
            json.dump(engine.snapshot(source_ref), stream)
        return path

    def test_derive_from_snapshot_performs_zero_network_calls(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            path = self._snapshot_file(directory)
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("snapshot must be offline")):
                result = engine.derive(path)
        self.assertEqual(result["identity"]["name"], "Torvald Brightmantle")

    def test_composite_views_fetch_exactly_once(self):
        for call in (lambda: engine.seatpack(FIXTURE),
                     lambda: engine.intake(FIXTURE)):
            with self.subTest(call=call), \
                    mock.patch("charactercheck.engine.fetch_loaded",
                               wraps=engine.fetch_loaded) as fetch:
                call()
                self.assertEqual(fetch.call_count, 1)

    def test_repeated_views_over_one_snapshot_are_deterministic(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            path = self._snapshot_file(directory)
            first = engine.derive(path)
            second = engine.derive(path)
        self.assertEqual(first, second)

    def test_default_public_reports_match_snapshot_replay(self):
        for ref in (FIXTURE, OTHER):
            loaded = source.load(ref)
            artifact = source.make_snapshot(loaded)
            replay = source.LoadedCharacter(
                artifact["character"],
                artifact["source"]["adapter"],
                artifact["source"]["source_id"],
                artifact["meta"]["observed_at"],
                artifact["source"]["schema"],
                artifact["source"]["schema_fingerprint"],
                artifact["source"]["normalized_data_hash"],
                artifact["source"]["coverage"],
            )
            with self.subTest(ref=ref):
                direct = engine.derive_loaded(loaded)
                replayed = engine.derive_loaded(replay)
                self.assertEqual(direct, replayed)
                self.assertEqual(direct["meta"]["source_revision"],
                                 artifact["source"]["normalized_data_hash"])

                with mock.patch.object(engine, "fetch_loaded",
                                       return_value=loaded):
                    direct_qa = qa.run("unused")
                with mock.patch.object(engine, "fetch_loaded",
                                       return_value=replay):
                    replay_qa = qa.run("unused")
                self.assertEqual(direct_qa, replay_qa)

    def test_cli_snapshot_diff_copy_paste_round_trip(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            baseline = os.path.join(directory, "baseline.json")
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["snapshot", FIXTURE]), 0)
            with open(baseline, "w") as stream:
                stream.write(output.getvalue())
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["diff", FIXTURE, "--baseline", baseline])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(result["meta"]["changes_present"])
        self.assertEqual(result["meta"]["relationship"], "unchanged")

    def test_diff_rejects_derive_output_and_other_character(self):
        with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
            wrong = os.path.join(directory, "derive.json")
            with open(wrong, "w") as stream:
                json.dump(engine.derive(FIXTURE), stream)
            with self.assertRaises(errors.CharacterCheckError) as caught:
                source.load_snapshot(wrong)
            self.assertEqual(caught.exception.kind, "snapshot_schema")

        with self.assertRaises(errors.CharacterCheckError) as caught:
            engine.diff_snapshots(engine.snapshot(FIXTURE), engine.snapshot(OTHER))
        self.assertEqual(caught.exception.kind, "snapshot_source_mismatch")

    def test_every_changed_top_level_field_is_classified_or_named(self):
        baseline = engine.snapshot(FIXTURE)
        loaded = source.load(FIXTURE)
        changed = copy.deepcopy(loaded.character)
        changed["name"] = "Synthetic Rename"
        candidate = source.make_snapshot(source.LoadedCharacter(
            changed, loaded.adapter, loaded.source_id, "2099-01-01T00:00:00Z",
            loaded.source_schema, loaded.source_schema_fingerprint))
        diff = engine.diff_snapshots(baseline, candidate)
        self.assertIn("name", [item["field"] for item in diff["unsupported_changes"]])
        self.assertTrue(diff["meta"]["changes_present"])


if __name__ == "__main__":
    unittest.main()
