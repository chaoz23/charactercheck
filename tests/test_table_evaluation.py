"""Shared result projection preserves CharacterCheck's trust boundary."""

import copy
import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout

from charactercheck import engine
from charactercheck import errors
from charactercheck.cli import main
from charactercheck.table_evaluation import (
    input_digest,
    project_table_error,
    project_table_evaluation,
)


FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "torvald.json")


class TestTableEvaluationProjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = engine.derive(FIXTURE)

    def test_real_report_is_value_free_and_fail_closed(self):
        result = project_table_evaluation(self.report)
        self.assertEqual(result["schema_version"], "table.evaluation/1.0")
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(result["authority_status"], "self_attested")
        self.assertFalse(result["coverage"]["complete"])
        encoded = json.dumps(result, sort_keys=True)
        self.assertNotIn(self.report["identity"]["name"], encoded)

        def keys(value):
            if isinstance(value, dict):
                return set(value) | {key for item in value.values() for key in keys(item)}
            if isinstance(value, list):
                return {key for item in value for key in keys(item)}
            return set()

        self.assertNotIn("value", keys(result))

    def test_player_authority_is_advisory_not_host_attestation(self):
        report = copy.deepcopy(self.report)
        for field in report["fields"].values():
            if field["state"] == "unsupported":
                field["state"] = "trusted"
                field["findings"] = []
        result = project_table_evaluation(report)
        self.assertEqual(result["status"], "checked_with_advisories")
        self.assertTrue(result["coverage"]["complete"])
        self.assertTrue(result["advisories"])
        self.assertTrue(all(item["severity"] == "advisory"
                            for item in result["advisories"]))
        self.assertIsNone(result["context"]["session_descriptor_digest"])

    def test_projection_is_deterministic_across_observation_time(self):
        first = project_table_evaluation(self.report)
        later = copy.deepcopy(self.report)
        later["meta"]["as_of"] = "2099-01-01T00:00:00Z"
        for field in later["fields"].values():
            field["as_of"] = later["meta"]["as_of"]
        self.assertEqual(first, project_table_evaluation(later))

    def test_unknown_and_invalid_fields_do_not_become_findings(self):
        for state, expected in (("unknown", "incomplete"),
                                ("invalid", "invalid")):
            with self.subTest(state=state):
                report = copy.deepcopy(self.report)
                field = report["fields"]["identity.name"]
                field["state"] = state
                field["findings"] = ["synthetic-gap"]
                result = project_table_evaluation(report)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["coverage"]["complete"])
                self.assertEqual(result["findings"], [])
                self.assertTrue(result["errors"])

    def test_public_errors_map_without_disclosing_the_reference(self):
        secret_ref = "/private/campaign/character-123.json"
        digest = input_digest(secret_ref)
        cases = (
            (errors.bad_ref(secret_ref), "invalid"),
            (errors.not_public(secret_ref), "incomplete"),
            (errors.local_files_disabled(), "unsupported"),
        )
        for error, expected in cases:
            with self.subTest(kind=error.kind):
                result = project_table_error(error.as_dict(), digest)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["exit_code"], 2)
                self.assertNotIn(secret_ref, json.dumps(result, sort_keys=True))

    def test_cli_flag_uses_shared_exit_lane(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["derive", FIXTURE, "--table-evaluation"])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "unsupported")

    def test_brief_and_shared_envelope_cannot_silently_compete(self):
        output = io.StringIO()
        with redirect_stderr(output):
            code = main(["derive", FIXTURE, "--brief", "--table-evaluation"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["error"], "bad_flag")


if __name__ == "__main__":
    unittest.main()
