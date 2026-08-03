"""Release-workflow supply-chain and runtime guardrails."""

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


class TestArtifactActions(unittest.TestCase):
    def test_artifact_actions_are_node24_generations_and_commit_pinned(self):
        workflow = RELEASE_WORKFLOW.read_text()
        uses = re.findall(
            r"actions/(upload-artifact|download-artifact)@([^\s]+) # v([^\s]+)",
            workflow,
        )

        self.assertEqual(len(uses), 5)
        self.assertEqual([name for name, _, _ in uses].count("upload-artifact"), 1)
        self.assertEqual([name for name, _, _ in uses].count("download-artifact"), 4)

        minimum_node24_major = {"upload-artifact": 7, "download-artifact": 8}
        for name, revision, version in uses:
            with self.subTest(action=name, version=version):
                self.assertRegex(revision, r"^[0-9a-f]{40}$")
                self.assertGreaterEqual(
                    int(version.split(".", 1)[0]),
                    minimum_node24_major[name],
                )


if __name__ == "__main__":
    unittest.main()
