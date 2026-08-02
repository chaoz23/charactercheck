"""v0.4 seat pack (stdlib unittest - CI installs no deps)."""
import glob, json, os, unittest
from charactercheck import engine

FIX = sorted(glob.glob("tests/fixtures/*.json"))[0]
CANARY = os.path.join("tests", "privacy", "sensitive-canary.json")


class TestSeatpack(unittest.TestCase):
    def test_vision_uses_only_activated_registered_modifiers(self):
        payload = {"modifiers": {"race": [{"type": "sense",
                                              "subType": "darkvision",
                                              "value": 60,
                                              "isGranted": True}]},
                   "classes": [{"classFeatures": [
                       {"definition": {"name": "Devil's Sight",
                                       "snippet": "see normally in darkness ... 120 feet"}}]}]}
        feats = {x["feature"]: x for x in engine.vision(payload)}
        self.assertEqual(feats["Darkvision"]["range_ft"], 60)
        self.assertNotIn("Devil's Sight", feats)

        payload["inventory"] = [{"id": 1,
                                  "definition": {"name": "Devil's Sight"}}]
        self.assertNotIn("Devil's Sight",
                         {x["feature"] for x in engine.vision(payload)})

    def test_seatpack_shape_and_persona_is_omitted_by_default(self):
        p = engine.seatpack(FIX)
        for k in ("abilities", "saves", "skills", "passives", "vision", "persona"):
            self.assertIn(k, p)
        self.assertFalse(p["persona"]["included"])
        self.assertNotIn("from_sheet_verbatim", p["persona"])
        self.assertIsInstance(p["passives"].get("passive_perception"), int)

    def test_explicit_local_persona_is_bounded_and_untrusted(self):
        p = engine.seatpack(CANARY, include_persona=True)
        self.assertTrue(p["persona"]["included"])
        self.assertEqual(p["persona"]["content_trust"], "untrusted_source_text")
        self.assertIn("PERSONA_CANARY_DO_NOT_EMIT",
                      p["persona"]["from_sheet_verbatim"]["personalityTraits"])

    def test_for_dm_redacts_player_authority(self):
        p = engine.seatpack(FIX, for_dm=True)
        marker = "player-authority"
        self.assertEqual(p["combat"]["hp"]["current"], marker)
        self.assertEqual(p["combat"]["stance"], marker)
        if p.get("spellcasting") is not None:
            self.assertEqual(p["spellcasting"]["slots_current"], marker)
        self.assertEqual(p["resources"], marker)
        self.assertEqual(p["inventory"], marker)

        expected = {
            "combat.hp.current", "combat.stance",
            "spellcasting.slots.current", "resources", "inventory",
        }
        self.assertEqual(set(p["authority_projection"]["redacted_fields"]),
                         expected)
        for field_id in expected:
            with self.subTest(field=field_id):
                self.assertEqual(p["fields"][field_id]["authority"], "player")
                self.assertEqual(p["fields"][field_id]["value"], marker)

if __name__ == "__main__":
    unittest.main()
