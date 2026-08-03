import json
import os
import sys
import copy
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from charactercheck import derive, engine  # noqa: E402
from charactercheck.cli import _exit_code  # noqa: E402
from charactercheck import qa  # noqa: E402
from charactercheck.question_catalog import (  # noqa: E402
    CATALOG_ID, QUESTION_BY_NUMBER, QUESTIONS)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
TORVALD = os.path.join(FIX, "torvald.json")
VEXA = os.path.join(FIX, "vexa.json")


class TestTorvald(unittest.TestCase):
    """Single-class fixture: supported values derive with named combat gaps."""

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
        self.assertEqual(sp["slots_max"], {1: 4, 2: 2})
        self.assertEqual(sp["slots_current"], {1: 3, 2: 2})

    def test_saves_proficiency(self):
        self.assertTrue(self.r["saves"]["wis"]["proficient"])
        self.assertEqual(self.r["saves"]["wis"]["bonus"], 5)  # +3 wis +2 pb
        self.assertFalse(self.r["saves"]["str"]["proficient"])

    def test_resources(self):
        self.assertEqual(self.r["resources"][0]["name"], "Channel Divinity")
        self.assertEqual(self.r["resources"][0]["max"], 2)

    def test_weapon_gaps_are_honest(self):
        self.assertEqual(_exit_code(self.r), 2)
        patterns = {item["pattern"] for item in self.r["unhandled"]["items"]}
        self.assertIn("item-semantic:weapon_proficiency", patterns)
        self.assertIn("item-semantic:weapon_property", patterns)
        self.assertIn("weapons", self.r["trust"]["unsupported"])
        self.assertEqual(self.r["lint"], [])

    def test_weapon_property_is_not_claimed_as_learned_mastery(self):
        self.assertEqual(self.r["combat"]["masteries_known"], [])
        self.assertIn(
            "Sap", self.r["combat"]["mastery_properties_on_weapons"])


class TestValidatedDDBDifferentials(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(TORVALD, encoding="utf-8") as stream:
            cls.base = json.load(stream)["data"]

    def test_carried_armor_is_not_worn_and_unarmed_is_active(self):
        character = copy.deepcopy(self.base)
        for item in character["inventory"]:
            item["equipped"] = False
        report = engine.derive_data(character)
        expected_ac = 10 + report["abilities"]["dex"]["mod"]
        self.assertEqual(report["combat"]["ac"]["value"], expected_ac)
        self.assertEqual(report["combat"]["active_attacks"][0]["name"],
                         "Unarmed Strike")

    def test_spell_profiles_preserve_source_and_cast_modes(self):
        character = copy.deepcopy(self.base)
        longstrider = {"definition": {"name": "Longstrider", "level": 1}}
        free = copy.deepcopy(longstrider)
        free["usesSpellSlot"] = False
        free["limitedUse"] = {"maxUses": 1, "numberUsed": 0,
                              "resetType": 2}
        slotted = copy.deepcopy(longstrider)
        slotted["usesSpellSlot"] = True
        character["spells"]["race"] = [free, slotted]
        character["classSpells"] = [{
            "alwaysPreparedSpells": [{
                "definition": {"name": "Aid", "level": 2},
                "usesSpellSlot": True,
            }],
        }]

        spellcasting = engine.derive_data(character)["spellcasting"]
        profiles = {(row["name"], row["source"]): row
                    for row in spellcasting["spell_profiles"]}
        self.assertEqual(profiles[("Longstrider", "race")]["cast_modes"],
                         ["limited_free", "spell_slot"])
        self.assertIn("Aid", spellcasting["prepared"])
        self.assertEqual(
            profiles[("Aid", "class")]["availability"],
            ["always_prepared"],
        )

    def test_death_save_counters_can_be_latent_and_stability_is_separate(self):
        character = copy.deepcopy(self.base)
        character["deathSaves"] = {
            "successCount": 3, "failCount": 0, "isStabilized": False,
        }
        state = engine.derive_data(character)["combat"]["death_saves"]
        self.assertFalse(state["active"])
        self.assertTrue(state["latent"])
        self.assertFalse(state["source_is_stabilized"])
        self.assertTrue(state["rules_imply_stable"])

    def test_exhaustion_uses_condition_id_four_only(self):
        character = copy.deepcopy(self.base)
        character["conditions"] = [{"id": 99, "level": 5},
                                   {"id": 4, "level": 2}]
        self.assertEqual(engine.build(character)["exhaustion"], 2)


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
        # The synthetic grant resolves to the four-level Warlock component;
        # per-level effects do not silently scale across unrelated classes.
        self.assertEqual(self.r["combat"]["hp"]["max"], 48)  # 30 + con2*7 + 1*4

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
        self.assertEqual(self.r["inventory"]["stashed_elsewhere"]["count"], 1)
        self.assertEqual(self.r["inventory"]["stashed_elsewhere"]["details"],
                         "omitted_by_default")

    def test_unhandled_lane(self):
        pats = [i["pattern"] for i in self.r["unhandled"]["items"]]
        self.assertIn("munch:cookies", pats)
        self.assertEqual(_exit_code(self.r), 2)

    def test_pact_slots(self):
        self.assertEqual(
            self.r["spellcasting"]["slots_current"],
            {1: 2, "pact2": 1},
        )


class TestQA(unittest.TestCase):
    def test_qa_runs_100(self):
        rows = qa.run(TORVALD)
        self.assertEqual(len(rows), 100)
        states = {"trusted", "confirm", "unsupported", "unknown", "invalid",
                  "not_applicable"}
        self.assertTrue(all(q[2] in states for q in rows))
        self.assertTrue(any(q[2] == "trusted" for q in rows))
        self.assertTrue(any(q[2] == "confirm" for q in rows))

    def test_qa_exposes_the_complete_numbered_question_catalog(self):
        self.assertEqual(len(QUESTIONS), 100)
        self.assertEqual(set(QUESTION_BY_NUMBER), set(range(1, 101)))
        self.assertTrue(all(question.endswith("?") for question in QUESTIONS))
        data = qa.report_data(TORVALD, full=True)
        self.assertEqual(data["question_catalog"], {
            "id": CATALOG_ID,
            "count": 100,
            "contract": (
                "questions organize extraction; row state and authority decide "
                "whether an answer may be relied upon"),
        })
        self.assertEqual(len(data["rows"]), 100)
        for row in data["rows"]:
            self.assertEqual(row["question"],
                             QUESTION_BY_NUMBER[row["number"]])

    def test_qa_text_pairs_each_answer_with_its_question(self):
        data = qa.report_data(TORVALD, full=True)
        self.assertIn(
            "1. What is the character's name? [characterName]",
            data["text"])
        self.assertIn(
            "100. What allies, organizations, or Bastions (2024 DMG) is "
            "the character affiliated with? [alliesAndOrganizations]",
            data["text"])


if __name__ == "__main__":
    unittest.main()


class TestV02BlastRadius(unittest.TestCase):
    """Cold probe 2026-07-24: 'unhandled names what, not which numbers.'"""

    def test_unmapped_pattern_is_named_and_fails_closed_globally(self):
        """An unknown target cannot justify trusting any derived family."""
        r = derive(VEXA)   # planted munch:cookies
        item = [i for i in r["unhandled"]["items"] if i["pattern"] == "munch:cookies"][0]
        self.assertIn("unknown", item["possibly_affects"][0])
        self.assertTrue(item.get("not_applied"))
        self.assertEqual(r["unhandled"]["verified_clean"], [])
        self.assertEqual(r["trust"]["trusted"], [])
        self.assertEqual(set(r["trust"]["unknown"]), set(engine.TRUST_FAMILIES))

    def test_known_fixture_has_only_declared_weapon_gaps(self):
        r = derive(TORVALD)
        patterns = {item["pattern"] for item in r["unhandled"]["items"]}
        self.assertEqual(patterns, {
            "item-semantic:weapon_proficiency",
            "item-semantic:weapon_property",
        })
        self.assertEqual(r["trust"]["unknown"], {})


class TestV02FeatClassification(unittest.TestCase):
    def test_feats_carry_categories(self):
        import copy
        with open(VEXA) as stream:
            d = json.load(stream)["data"]
        d["feats"] = [{"definition": {"name": "Alert"}},
                      {"definition": {"name": "Grappler"}},
                      {"definition": {"name": "Fey Touched"}}]
        import charactercheck.engine as E
        W = E.build(d)
        from charactercheck import qa as Q
        # write temp fixture for qa path
        import tempfile
        with tempfile.TemporaryDirectory(
                dir=os.path.realpath(tempfile.gettempdir())) as directory:
            p = os.path.join(directory, "feat.json")
            with open(p, "w") as stream:
                json.dump({"data": d}, stream)
            rows = Q.run(p)
        r68 = [x for x in rows if x[0] == 68][0]
        # Vexa has a global unknown-scope modifier. The row still inventories
        # the observed feat, but QA may not weaken canonical unknown to trusted.
        self.assertEqual(r68[2], "unknown")
        self.assertEqual(r68[3], "Alert")
        r69 = [x for x in rows if x[0] == 69][0]
        self.assertIn("Grappler [General]", r69[3])
        self.assertIn("Fey Touched [outside SRD table]", r69[3])


class TestV02Diff(unittest.TestCase):
    """The sheet is a LIVE state store (Oz, 2026-07-24)."""

    @classmethod
    def setUpClass(cls):
        import copy
        from charactercheck.engine import diff_payloads
        with open(VEXA) as stream:
            cls.old = json.load(stream)["data"]
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
        ch = [c for c in d["build_changes"]
              if c["field"].endswith(".equipped")][0]
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
