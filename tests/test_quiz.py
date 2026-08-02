"""v0.3 settlement quiz (converted to unittest 2026-07-27 - the bare
pytest functions imported cleanly in CI but silently never RAN)."""
import glob, unittest
from unittest import mock
from charactercheck import engine

FIX = sorted(glob.glob("tests/fixtures/*.json"))[0]


class TestQuiz(unittest.TestCase):
    def test_quiz_has_answer_key_and_player_nulls(self):
        q = engine.quiz(FIX)
        ac = next(x for x in q["questions"] if "AC" in x["ask"])
        self.assertIsInstance(ac["expect"], int)
        hp_now = next(x for x in q["questions"] if "right now" in x["ask"])
        self.assertIsNone(hp_now["expect"])
        self.assertEqual(hp_now["authority"], "player")
        self.assertIn("read-only", q["contract"])

    def test_quiz_caveat_matches_unhandled_lane(self):
        q = engine.quiz(FIX)
        d = engine.derive(FIX)
        if d["unhandled"]["items"]:
            self.assertTrue(q["caveat"])
        else:
            self.assertIsNone(q["caveat"])

    def test_unhandled_items_omit_verbatim_source_text(self):
        for item in engine.derive(FIX)["unhandled"]["items"]:
            self.assertEqual(item["source_text"], "omitted_by_default")

    def test_quiz_includes_each_sheet_specific_finding_question_once(self):
        finding = {
            "code": "armor_not_equipped",
            "ask": "Which armour are you actually wearing right now?",
            "affects": ["ac"],
        }
        report = {
            "meta": {},
            "combat": {},
            "fields": {},
            "inventory": {},
            "trust": {
                "trusted": [],
                "ask_player": {},
                "unsupported": {"ac": ["source:gap"]},
                "unknown": {},
                "invalid": {},
                "asks": [finding, dict(finding)],
            },
            "unhandled": {"items": []},
        }
        with mock.patch.object(engine, "derive", return_value=report):
            q = engine.quiz("unused")
        asks = [item["ask"] for item in q["questions"]]
        self.assertEqual(asks.count(finding["ask"]), 1)
        question = next(item for item in q["questions"]
                        if item["ask"] == finding["ask"])
        self.assertIsNone(question["expect"])
        self.assertEqual(question["state"], "unsupported")
        self.assertEqual(question["authority"], "player")
        self.assertEqual(question["affects"], finding["affects"])


if __name__ == "__main__":
    unittest.main()
