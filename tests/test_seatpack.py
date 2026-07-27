"""v0.4 seat pack (stdlib unittest - CI installs no deps)."""
import glob, json, os, unittest
from charactercheck import engine

FIX = sorted(glob.glob("tests/fixtures/*.json"))[0]
WILLIAM = os.path.expanduser("~/Projects/agent-table/fixtures/william.json")


class TestSeatpack(unittest.TestCase):
    def test_vision_finds_named_invocation_and_modifier(self):
        payload = {"modifiers": {"race": [{"subType": "darkvision", "value": 60}]},
                   "classes": [{"classFeatures": [
                       {"definition": {"name": "Devil's Sight",
                                       "snippet": "see normally in darkness ... 120 feet"}}]}]}
        feats = {x["feature"]: x for x in engine.vision(payload)}
        self.assertEqual(feats["Darkvision"]["range_ft"], 60)
        self.assertEqual(feats["Devil's Sight"]["range_ft"], 120)

    def test_seatpack_shape_and_persona_fence(self):
        p = engine.seatpack(FIX)
        for k in ("abilities", "saves", "skills", "passives", "vision", "persona"):
            self.assertIn(k, p)
        self.assertTrue(p["persona"]["not_derivable"])
        self.assertIsInstance(p["passives"].get("passive_perception"), int)

    def test_for_dm_redacts_player_authority(self):
        p = engine.seatpack(FIX, for_dm=True)
        hp = (p.get("combat") or {}).get("hp") or {}
        if "current" in hp:
            self.assertEqual(hp["current"], "player-authority")

    @unittest.skipUnless(os.path.exists(WILLIAM), "private fixture, local only")
    def test_regression_devils_sight_surfaces(self):
        feats = {x["feature"] for x in engine.vision(engine.fetch(WILLIAM))}
        self.assertIn("Devil's Sight", feats)


if __name__ == "__main__":
    unittest.main()
