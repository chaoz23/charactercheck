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
        self.assertEqual(self.r["unhandled"]["items"], [])
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
        pats = [i["pattern"] for i in self.r["unhandled"]["items"]]
        self.assertIn("munch:cookies", pats)
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


class TestV02BlastRadius(unittest.TestCase):
    """Cold probe 2026-07-24: 'unhandled names what, not which numbers.'"""

    def test_unmapped_pattern_is_named_but_no_longer_condemns_everything(self):
        """Superseded 2026-07-31 by live UXR.

        This used to assert that an unmapped pattern cleared NOTHING —
        `verified_clean == []`. An agent using this at a table objected, and
        was right: one unhandled `bonus:spell-group-healing` was collapsing the
        report to "treat all derived values as unverified", so it could not
        trust AC, saves, skills or HP either. A caveat that covers everything
        is worth the same as no caveat at all.

        The honest position is narrower: an unhandled modifier is **never
        applied**, so no derived value read it. It is still named, and the
        exit code still flips — the caller is told what to go and ask about,
        not told to distrust arithmetic that provably did not consume it.
        """
        r = derive(VEXA)   # planted munch:cookies
        item = [i for i in r["unhandled"]["items"] if i["pattern"] == "munch:cookies"][0]
        self.assertIn("unknown", item["possibly_affects"][0])
        self.assertTrue(item.get("not_applied"))
        self.assertNotEqual(r["unhandled"]["verified_clean"], [])

    def test_clean_sheet_has_no_items(self):
        r = derive(TORVALD)
        self.assertEqual(r["unhandled"]["items"], [])


class TestV02FeatClassification(unittest.TestCase):
    def test_feats_carry_categories(self):
        import copy
        d = json.load(open(VEXA))["data"]
        d["feats"] = [{"definition": {"name": "Alert"}},
                      {"definition": {"name": "Grappler"}},
                      {"definition": {"name": "Fey Touched"}}]
        import charactercheck.engine as E
        W = E.build(d)
        from charactercheck import qa as Q
        # write temp fixture for qa path
        import tempfile, os as _os
        p = tempfile.mktemp(suffix=".json")
        json.dump({"data": d}, open(p, "w"))
        rows = Q.run(p)
        r68 = [x for x in rows if x[0] == 68][0]
        self.assertEqual(r68[2], "OK")
        self.assertEqual(r68[3], "Alert")
        r69 = [x for x in rows if x[0] == 69][0]
        self.assertIn("Grappler [General]", r69[3])
        self.assertIn("Fey Touched [outside SRD table]", r69[3])
        _os.unlink(p)


class TestV02Diff(unittest.TestCase):
    """The sheet is a LIVE state store (Oz, 2026-07-24)."""

    @classmethod
    def setUpClass(cls):
        import copy
        from charactercheck.engine import diff_payloads
        cls.old = json.load(open(VEXA))["data"]
        cls.dp = staticmethod(diff_payloads)

    def _new(self):
        import copy
        return copy.deepcopy(self.old)

    def test_hp_edit_is_state(self):
        n = self._new(); n["removedHitPoints"] = 12
        d = self.dp(self.old, n)
        self.assertEqual(d["state_changes"][0]["affects"], ["hp.current"])
        self.assertEqual(d["build_changes"], [])

    def test_shield_flip_is_build_with_ac_radius(self):
        n = self._new()
        for it in n["inventory"]:
            if it["definition"]["name"] == "Shield":
                it["equipped"] = True
        d = self.dp(self.old, n)
        ch = [c for c in d["build_changes"] if c["field"] == "Shield.equipped"][0]
        self.assertIn("ac", ch["affects"])

    def test_equipping_stashed_gear_is_impossible_lint(self):
        n = self._new()
        for it in n["inventory"]:
            if it["definition"]["name"] == "Chain Mail":
                it["equipped"] = True     # it lives in the stashed chest
        d = self.dp(self.old, n)
        self.assertEqual(d["lint"][0]["severity"], "impossible")

    def test_new_homebrew_reopens_interview(self):
        n = self._new()
        n["modifiers"]["feat"].append({"type": "weird", "subType": "aura",
                                       "value": 1, "isGranted": True})
        d = self.dp(self.old, n)
        self.assertTrue(d["unhandled_new"])
        self.assertIn("unknown", d["unhandled_new"][0]["possibly_affects"][0])
