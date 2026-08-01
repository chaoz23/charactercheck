import io
import json
import os
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import charactercheck
from charactercheck import engine, errors, mcp, qa, source
from charactercheck.cli import main


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANARY = os.path.join(ROOT, "tests", "privacy", "sensitive-canary.json")
SAMPLE = os.path.join(ROOT, "examples", "sample-character.json")
CANARIES = (
    "ACCOUNT_CANARY_DO_NOT_EMIT",
    "PERSONA_CANARY_DO_NOT_EMIT",
    "IDEAL_CANARY_DO_NOT_EMIT",
    "BOND_CANARY_DO_NOT_EMIT",
    "FLAW_CANARY_DO_NOT_EMIT",
    "ORG_CANARY_DO_NOT_EMIT",
    "APPEARANCE_CANARY_DO_NOT_EMIT",
    "HAIR_CANARY_DO_NOT_EMIT",
    "SKIN_CANARY_DO_NOT_EMIT",
    "EYES_CANARY_DO_NOT_EMIT",
)


def assert_no_canary(case, value):
    rendered = value if isinstance(value, str) else json.dumps(value)
    for canary in CANARIES:
        case.assertNotIn(canary, rendered)


class TestFixtureAndRepositoryPolicy(unittest.TestCase):
    def test_fixture_manifest_covers_every_fixture_and_copies_match(self):
        with open(os.path.join(ROOT, "tests", "fixtures-manifest.json")) as stream:
            manifest = json.load(stream)
        covered = set()
        for fixture in manifest["fixtures"]:
            self.assertEqual(fixture["origin"], "project_authored_synthetic")
            self.assertFalse(fixture["derived_from_live_sheet"])
            canonical = os.path.join(ROOT, fixture["canonical_file"])
            self.assertTrue(os.path.isfile(canonical))
            covered.add(fixture["canonical_file"])
            with open(canonical, "rb") as stream:
                expected = stream.read()
            for copy_path in fixture["copies"]:
                covered.add(copy_path)
                with open(os.path.join(ROOT, copy_path), "rb") as stream:
                    self.assertEqual(stream.read(), expected)
        expected = {
            os.path.relpath(os.path.join(directory, name), ROOT)
            for directory, _dirs, names in os.walk(os.path.join(ROOT, "tests"))
            for name in names if name.endswith(".json")
            and name != "fixtures-manifest.json"
        }
        expected |= {"examples/sample-character.json",
                     "charactercheck/sample-character.json"}
        self.assertEqual(covered, expected)

    def test_no_numeric_character_url_or_developer_private_path_is_tracked(self):
        numeric_url = re.compile(r"https://(?:www\.)?dndbeyond\.com/characters/[0-9]+")
        for directory, dirs, names in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for name in names:
                if not name.endswith((".py", ".md", ".txt", ".json", ".toml", ".yml")):
                    continue
                path = os.path.join(directory, name)
                with open(path, errors="replace") as stream:
                    text = stream.read()
                self.assertIsNone(numeric_url.search(text), path)
                self.assertNotIn("~/" + "Projects/", text, path)

    def test_forbidden_absolute_claims_are_absent_from_contract_docs(self):
        banned = ("output complete and usable", "everything a seat needs",
                  "never a traceback", "safe to state", "classify every delta",
                  "full surface a table uses")
        for name in ("README.md", "AGENTS.md", "llms.txt", "tool.json",
                     "SUPPORT.md"):
            with open(os.path.join(ROOT, name)) as stream:
                text = stream.read().lower()
            for phrase in banned:
                self.assertNotIn(phrase, text, f"{name}: {phrase}")


class TestDefaultPrivacy(unittest.TestCase):
    def test_snapshot_topology_is_fail_closed_for_narrative_schema_drift(self):
        character = source.load(CANARY).character
        secret = "NESTED_PRIVATE_CANARY_DO_NOT_EMIT"
        character.update({
            "gender": secret,
            "backstory": secret,
            "organizations": secret,
            "campaign": {"name": secret, "description": secret},
            "socialName": secret,
        })
        character["background"]["backstory"] = secret
        character["classes"][0]["definition"]["description"] = secret
        character["classes"][0]["definition"]["privateDiary"] = secret
        character["inventory"].append({
            "id": 7001,
            "quantity": 1,
            "equipped": False,
            "isAttuned": False,
            "definition": {"name": "Synthetic item", "weight": 0,
                           "dmSecret": secret},
        })
        character["modifiers"].setdefault("feat", []).append({
            "type": "bonus", "subType": "initiative", "value": 1,
            "isGranted": True, "restriction": secret,
        })
        loaded = source.LoadedCharacter(
            character, "local-json", str(character["id"]),
            "2026-07-31T00:00:00Z")
        snapshot = source.make_snapshot(loaded)
        rendered = json.dumps(snapshot)
        self.assertNotIn(secret, rendered)
        self.assertTrue(snapshot["source"]["coverage"][
            "unclassified_nested_omitted"])
        self.assertFalse(snapshot["source"]["coverage"][
            "unclassified_top_level_omitted"])
        self.assertLessEqual(set(snapshot["character"]),
                             source._MECHANICAL_TOP_LEVEL | {"traits"})
        restriction = snapshot["character"]["modifiers"]["feat"][-1][
            "restriction"]
        self.assertEqual(restriction, "present; source text omitted")

    def test_public_revisions_never_digest_privacy_omitted_values(self):
        first = source.load(CANARY).character
        second = json.loads(json.dumps(first))
        first["gender"] = "first private value"
        second["gender"] = "second private value"
        first_loaded = source.LoadedCharacter(
            first, "local-json", str(first["id"]),
            "2026-07-31T00:00:00Z")
        second_loaded = source.LoadedCharacter(
            second, "local-json", str(second["id"]),
            "2026-07-31T00:01:00Z")

        first_snapshot = source.make_snapshot(first_loaded)
        second_snapshot = source.make_snapshot(second_loaded)
        expected = source.mechanical_hash(first)
        self.assertEqual(expected, source.mechanical_hash(second))
        self.assertEqual(first_snapshot["source"]["normalized_data_hash"],
                         expected)
        self.assertEqual(second_snapshot["source"]["normalized_data_hash"],
                         expected)
        self.assertNotEqual(source.normalized_hash(first),
                            source.normalized_hash(second))
        self.assertNotIn(source.normalized_hash(first),
                         json.dumps(first_snapshot))
        self.assertEqual(engine.derive_loaded(first_loaded)["meta"][
            "source_revision"], expected)
        self.assertEqual(engine.derive_loaded(second_loaded)["meta"][
            "source_revision"], expected)

    def test_unclassified_omissions_make_direct_trust_globally_unknown(self):
        secret = "SCHEMA_DRIFT_VALUE_DO_NOT_EMIT"
        field_name = "futureMechanicalCanary"
        for location in ("top", "nested"):
            character = source.load(CANARY).character
            if location == "top":
                character[field_name] = {"value": secret}
            else:
                character["classes"][0]["definition"][field_name] = secret

            with self.subTest(location=location):
                report = engine.derive_data(character)
                coverage = report["meta"]["source_coverage"]
                expected_key = ("unclassified_top_level_omitted"
                                if location == "top" else
                                "unclassified_nested_omitted")
                self.assertTrue(coverage[expected_key])
                self.assertEqual(set(report["trust"]["unknown"]),
                                 set(engine.FAMILY_CATALOG))
                self.assertEqual(report["meta"]["aggregate_state"],
                                 "unknown")
                finding = next(
                    item for item in report["unhandled"]["items"]
                    if item["pattern"] ==
                    "source:unclassified-fields-omitted")
                self.assertEqual(finding["state"], "unknown")
                rendered = json.dumps(report)
                self.assertNotIn(secret, rendered)
                self.assertNotIn(field_name, rendered)

    def test_reviewed_display_fields_do_not_change_trust(self):
        character = source.load(CANARY).character
        character["canEdit"] = True
        character["dateModified"] = "DISPLAY_CANARY_DO_NOT_EMIT"
        character["stats"][0]["name"] = "DISPLAY_STAT_CANARY_DO_NOT_EMIT"

        report = engine.derive_data(character)

        self.assertEqual(report["meta"]["source_coverage"], {
            "unclassified_top_level_omitted": False,
            "unclassified_nested_omitted": False,
            "semantic_values_omitted": False,
            "scoped_mechanical_omissions": [],
        })
        self.assertEqual(report["trust"]["unknown"], {})
        self.assertEqual(report["trust"]["unsupported"], {})
        rendered = json.dumps(report)
        self.assertNotIn("DISPLAY_CANARY_DO_NOT_EMIT", rendered)
        self.assertNotIn("DISPLAY_STAT_CANARY_DO_NOT_EMIT", rendered)

    def test_reviewed_mechanical_omission_is_family_scoped(self):
        character = source.load(CANARY).character
        character["customSenses"] = [{
            "futureShape": "SCOPED_SENSE_CANARY_DO_NOT_EMIT",
        }]

        report = engine.derive_data(character)
        coverage = report["meta"]["source_coverage"]

        self.assertFalse(coverage["unclassified_top_level_omitted"])
        self.assertFalse(coverage["unclassified_nested_omitted"])
        self.assertEqual(coverage["scoped_mechanical_omissions"], ["senses"])
        self.assertEqual(report["trust"]["unknown"], {})
        self.assertEqual(report["trust"]["unsupported"], {
            "senses": ["source:scoped-fields-omitted"],
        })
        finding = next(
            item for item in report["unhandled"]["items"]
            if item["pattern"] == "source:scoped-fields-omitted")
        self.assertEqual(finding["possibly_affects"], ["senses"])
        rendered = json.dumps(report)
        self.assertNotIn("futureShape", rendered)
        self.assertNotIn("SCOPED_SENSE_CANARY_DO_NOT_EMIT", rendered)

    def test_invalid_external_family_scope_fails_closed_globally(self):
        character = source.load(CANARY).character

        report = engine.derive_data(character, source_coverage={
            "scoped_mechanical_omissions": ["future-family"],
        })

        self.assertTrue(report["meta"]["source_coverage"][
            "unclassified_nested_omitted"])
        self.assertEqual(set(report["trust"]["unknown"]),
                         set(engine.FAMILY_CATALOG))

    def test_snapshot_replay_and_qa_preserve_omission_trust(self):
        character = source.load(CANARY).character
        character["classes"][0]["definition"][
            "futureMechanicalCanary"] = "SCHEMA_DRIFT_VALUE_DO_NOT_EMIT"
        loaded = source.LoadedCharacter(
            character, "local-json", str(character["id"]),
            "2026-07-31T00:00:00Z")
        snapshot = source.make_snapshot(loaded)
        self.assertTrue(snapshot["source"]["coverage"][
            "unclassified_nested_omitted"])

        with tempfile.TemporaryDirectory(
                dir=os.path.realpath(tempfile.gettempdir())) as directory:
            path = os.path.join(directory, "snapshot.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(snapshot, stream)
            report = engine.derive(path)
            rows = qa.run(path)

        self.assertTrue(report["meta"]["source_coverage"][
            "unclassified_nested_omitted"])
        self.assertEqual(set(report["trust"]["unknown"]),
                         set(engine.FAMILY_CATALOG))
        # Feature rows do not have a one-to-one canonical family mapping, so
        # this guards against QA weakening a global unknown to trusted.
        self.assertEqual(next(row for row in rows if row[0] == 68)[2],
                         "unknown")

    def test_plain_fetch_cannot_discard_source_coverage(self):
        character = source.load(CANARY).character
        character["classes"][0]["definition"][
            "futureMechanicalCanary"] = "SCHEMA_DRIFT_VALUE_DO_NOT_EMIT"

        with tempfile.TemporaryDirectory(
                dir=os.path.realpath(tempfile.gettempdir())) as directory:
            path = os.path.join(directory, "character.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"data": character}, stream)

            with self.assertRaises(errors.CharacterCheckError) as caught:
                engine.fetch(path)
            direct = engine.derive(path)

        self.assertEqual(caught.exception.kind, "source_coverage")
        self.assertEqual(set(direct["trust"]["unknown"]),
                         set(engine.FAMILY_CATALOG))
        self.assertNotIn("SCHEMA_DRIFT_VALUE_DO_NOT_EMIT",
                         json.dumps(direct))
        self.assertNotIn("futureMechanicalCanary", json.dumps(direct))

        # The compatibility composition remains usable for fully classified
        # sources and cannot silently change the trust assessment.
        clean_plain = engine.derive_data(engine.fetch(CANARY))
        clean_direct = engine.derive(CANARY)
        def stable_field_contract(report):
            return {
                field_id: {
                    key: assessment.get(key)
                    for key in ("value", "state", "authority", "formula",
                                "sources", "findings", "stale",
                                "sensitivity")
                }
                for field_id, assessment in report["fields"].items()
            }
        self.assertEqual(stable_field_contract(clean_plain),
                         stable_field_contract(clean_direct))
        self.assertEqual(clean_plain["trust"], clean_direct["trust"])

    def test_public_workspace_and_stance_surfaces_preserve_trust(self):
        character = source.load(CANARY).character
        character["futureArmorOracle"] = {"armorClassBonus": 99}

        with self.assertRaises(errors.CharacterCheckError) as caught:
            engine.build(character)
        self.assertEqual(caught.exception.kind, "source_coverage")
        self.assertFalse(hasattr(charactercheck, "build"))

        with tempfile.TemporaryDirectory(
                dir=os.path.realpath(tempfile.gettempdir())) as directory:
            path = os.path.join(directory, "character.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump({"data": character}, stream)
            result = charactercheck.stance(path)

        self.assertEqual(
            result["fields"]["combat.stance"]["state"], "unknown")
        self.assertEqual(set(result["trust"]["unknown"]),
                         set(engine.FAMILY_CATALOG))
        rendered = json.dumps(result)
        self.assertNotIn("futureArmorOracle", rendered)
        self.assertNotIn("armorClassBonus", rendered)

    def test_every_default_cli_library_view_omits_sensitive_canaries(self):
        values = [
            engine.fetch(CANARY),
            engine.derive(CANARY),
            qa.report(CANARY, full=True)[0],
            engine.seatpack(CANARY),
            engine.intake(CANARY),
            engine.quiz(CANARY),
            engine.snapshot(CANARY),
        ]
        for value in values:
            assert_no_canary(self, value)

        for command in ("derive", "qa", "seatpack", "intake", "quiz", "snapshot"):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([command, CANARY] + (["--full"] if command == "qa" else []))
            self.assertIn(code, (0, 1, 2))
            assert_no_canary(self, output.getvalue())

    def test_only_explicit_local_opt_in_returns_persona_canary(self):
        default = json.dumps(engine.seatpack(CANARY))
        opted_in = json.dumps(engine.seatpack(CANARY, include_persona=True))
        self.assertNotIn("PERSONA_CANARY_DO_NOT_EMIT", default)
        self.assertIn("PERSONA_CANARY_DO_NOT_EMIT", opted_in)
        self.assertIn("untrusted_source_text", opted_in)
        self.assertNotIn("ACCOUNT_CANARY_DO_NOT_EMIT", opted_in)
        self.assertNotIn("ORG_CANARY_DO_NOT_EMIT", opted_in)
        for appearance in ("APPEARANCE_CANARY_DO_NOT_EMIT",
                           "HAIR_CANARY_DO_NOT_EMIT",
                           "SKIN_CANARY_DO_NOT_EMIT",
                           "EYES_CANARY_DO_NOT_EMIT"):
            self.assertNotIn(appearance, opted_in)
        opted_snapshot = json.dumps(engine.snapshot(CANARY, include_persona=True))
        opted_intake = json.dumps(engine.intake(CANARY, include_persona=True))
        self.assertIn("PERSONA_CANARY_DO_NOT_EMIT", opted_snapshot)
        self.assertIn("PERSONA_CANARY_DO_NOT_EMIT", opted_intake)
        for appearance in CANARIES[6:]:
            self.assertNotIn(appearance, opted_snapshot)
            self.assertNotIn(appearance, opted_intake)

    def test_persona_opt_in_rejects_remote_references_before_network(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            for call in (engine.snapshot, engine.seatpack, engine.intake):
                with self.subTest(call=call), \
                        self.assertRaises(errors.CharacterCheckError) as caught:
                    call("12345", include_persona=True)
                self.assertEqual(caught.exception.kind, "persona_requires_local")
            urlopen.assert_not_called()

    def test_error_envelopes_omit_refs_paths_and_raw_detail(self):
        secret = "/private/table/SECRET_CHARACTER.json?token=secret"
        for exc in (errors.bad_ref(secret), errors.bad_json(secret, secret),
                    errors.network(secret, secret)):
            assert_no_canary(self, exc.as_dict())
            rendered = json.dumps(exc.as_dict())
            self.assertNotIn(secret, rendered)
            self.assertNotIn("ref", exc.as_dict())
            self.assertNotIn("detail", exc.as_dict())


class TestMCPPrivacyBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(CANARY, "rb") as stream:
            cls.body = stream.read()

    def _response(self, *_args, **_kwargs):
        return io.BytesIO(self.body)

    def test_mcp_default_views_omit_canaries_and_local_files_are_denied(self):
        with mock.patch("urllib.request.urlopen", side_effect=self._response):
            for tool in ("derive", "qa", "seatpack", "intake", "quiz", "snapshot"):
                args = {"ref": "999999999999999999"}
                if tool == "qa":
                    args["full"] = True
                assert_no_canary(self, mcp._call(tool, args))
        with self.assertRaises(errors.CharacterCheckError) as caught:
            mcp._call("derive", {"ref": CANARY})
        self.assertEqual(caught.exception.kind, "local_files_disabled")

    def test_mcp_text_is_bounded_and_does_not_duplicate_structured_sheet(self):
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": "derive",
                              "arguments": {"ref": "999999999999999999"}}}
        stdin, stdout = io.StringIO(json.dumps(request) + "\n"), io.StringIO()
        with mock.patch("sys.stdin", stdin), mock.patch("sys.stdout", stdout), \
                mock.patch("urllib.request.urlopen", side_effect=self._response):
            mcp.main()
        result = json.loads(stdout.getvalue())["result"]
        text = result["content"][0]["text"]
        self.assertLess(len(text), 200)
        self.assertNotIn("Synthetic Canary", text)
        assert_no_canary(self, result)


class TestTruthfulExecutableExamples(unittest.TestCase):
    def test_documented_synthetic_example_executes_offline(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=AssertionError("documented example must be offline")):
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["derive", SAMPLE, "--brief"])
        self.assertIn(code, (0, 1, 2))
        self.assertTrue(output.getvalue().strip())

    def test_tool_manifest_and_mcp_list_the_same_tools(self):
        with open(os.path.join(ROOT, "tool.json")) as stream:
            manifest = json.load(stream)
        self.assertEqual(set(manifest["mcp"]["tools"]),
                         {tool["name"] for tool in mcp.TOOLS})
        self.assertEqual(tuple(manifest["errors"]["kinds"]),
                         errors.PUBLIC_ERROR_KINDS)


if __name__ == "__main__":
    unittest.main()
