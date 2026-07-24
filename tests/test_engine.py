import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from charactercheck import derive, engine  # noqa: E402
from charactercheck.cli import _exit_code  # noqa: E402
from charactercheck import qa  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
TORVALD = os.path.join(FIX, "torvald.json")
VEXA = os.path.join(FIX, "vexa.json")


class TestTorvald(unittest.TestCase):
    """The clean single-class case: everything derives, exit 0."""

    @classmethod
    def setUpClass(cls):
        cls.r = derive(TORVALD)

    def test_ac_with_shield(self):
        self.assertEqual(self.r["combat"]["ac"]["value"], 15)  # 13 chain shirt + dex 0 + shield 2
        self.assertIn("Shield", self.r["combat"]["ac"]["provenance"])

    def test_hp(self):
        self.assertEqual(self.r["combat"]["hp"]["max"], 24)  # 18 + con2*3

    def test_spellcasting(self):
        sp = self.r["spellcasting"]
        self.assertEqual(sp["dc"], 13)  # 8 + pb2 + wis3
        self.assertEqual(sp["cantrips"], ["Sacred Flame"])
        self.assertEqual(sp["prepared"], ["Bless"])
        self.assertEqual(sp["slots_current"], {1: 3})

    def test_saves_proficiency(self):
        self.assertTrue(self.r["saves"]["wis"]["proficient"])
        self.assertEqual(self.r["saves"]["wis"]["bonus"], 5)  # +3 wis +2 pb
        self.assertFalse(self.r["saves"]["str"]["proficient"])

    def test_resources(self):
        self.assertEqual(self.r["resources"][0]["name"], "Channel Divinity")
        self.assertEqual(self.r["resources"][0]["max"], 2)

    def test_clean_exit(self):
        self.assertEqual(_exit_code(self.r), 0)
        self.assertEqual(self.r["unhandled"]["modifier_patterns"], [])
        self.assertEqual(self.r["lint"], [])

    def test_mastery_from_properties(self):
        self.assertIn("Sap", self.r["combat"]["masteries_on_weapons"])


class TestVexa(unittest.TestCase):
    """The gnarly legacy multiclass: containers, hex weapon, adjustments, honest lanes."""

    @classmethod
    def setUpClass(cls):
        cls.r = derive(VEXA)

    def test_ac_manual_adjustment(self):
        self.assertEqual(self.r["combat"]["ac"]["value"], 16)  # breastplate14 + dex1 + adj1
        self.assertIn("manual adjustment", self.r["combat"]["ac"]["provenance"])

    def test_shield_state_available(self):
        st = self.r["combat"]["stance"]["ac_states"]
        self.assertEqual(st["current"], 16)
        raised = [v for k, v in st.items() if "shield" in k]
        self.assertEqual(raised[0]["ac"], 18)

    def test_initiative_feat_bonus(self):
        self.assertEqual(self.r["combat"]["initiative"]["bonus"], 6)  # dex1 + 5

    def test_hp_per_level_bonus(self):
        self.assertEqual(self.r["combat"]["hp"]["max"], 51)  # 30 + con2*7 + 1*7

    def test_hex_weapon_designation(self):
        w = [x for x in self.r["combat"]["weapons"] if x["designated"]][0]
        self.assertEqual(w["name"], "Night Rapier")
        self.assertEqual(w["attack_bonus"], 7)  # CHA 18 (+4) via Hex Warrior + PB 3
        self.assertIn("designated", w["attack_provenance"])

    def test_stance_hands(self):
        st = self.r["combat"]["stance"]
        self.assertEqual(st["main_hand"], "Night Rapier")
        self.assertEqual(st["off_hand"], "Boot Knife (off hand)")

    def test_container_stash_excluded(self):
        self.assertEqual(self.r["inventory"]["weight_carried"], 47.5)
        self.assertIn("Chest (Stashed @ Docks): under the third pier",
                      self.r["inventory"]["stashed_elsewhere"])

    def test_unhandled_lane(self):
        self.assertIn("munch:cookies", self.r["unhandled"]["modifier_patterns"])
        self.assertEqual(_exit_code(self.r), 2)

    def test_pact_slots(self):
        self.assertEqual(self.r["spellcasting"]["slots_current"], {"pact2": 1})


class TestQA(unittest.TestCase):
    def test_qa_runs_100(self):
        rows = qa.run(TORVALD)
        self.assertEqual(len(rows), 100)
        ok = sum(1 for q in rows if q[2] == "OK")
        self.assertGreaterEqual(ok, 85)


if __name__ == "__main__":
    unittest.main()
