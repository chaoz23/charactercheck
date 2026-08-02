"""Coverage Inventory — a 100-question extraction inventory, run deterministically.

It is not a validity score or a complete rules audit. Statuses describe this
version's extraction coverage, not whether a character is rules-legal.
"""

from . import engine
from .question_catalog import CATALOG_ID, QUESTION_BY_NUMBER
from .engine import ABIL, ABILN, ALIGN, SKILLS, FEAT_CATEGORIES
import re as _re


def run(ref, _with_context=False):
    loaded = engine.fetch_loaded(ref)
    # QA is a public projection, so its directly-read rows must use the same
    # default mechanical/privacy view as derive/build and snapshot replay.
    d = engine.source.privacy_filter(loaded.character)
    W = engine.build(d)
    derived = engine.derive_loaded(loaded)
    A, am, pb, level = W["A"], W["am"], W["pb"], W["level"]
    race = d.get("race") or {}
    classes = d.get("classes", [])
    rows = []

    def add(n, key, status, value):
        rows.append((n, key, status, value))

    def best(lane):
        c = [w for w in W["active_attacks"] if w["lane"] == lane]
        return max(c, key=lambda w: w["attack_bonus"]) if c else None

    def active_feature_names(features, character_level=None):
        names = set()
        for feature in features or []:
            definition = feature.get("definition") or feature
            required = (feature.get("requiredLevel")
                        if feature.get("requiredLevel") is not None
                        else definition.get("requiredLevel"))
            if (character_level is not None and isinstance(required, int)
                    and required > character_level):
                continue
            name = definition.get("name")
            if name:
                names.add(name)
        return sorted(names)

    add(1, "characterName", "OK", d.get("name"))
    add(2, "accountIdentity", "PARTIAL",
        "privacy_omitted (account identifiers are outside mechanical coverage)")
    add(3, "classAndLevel", "OK", "/".join(
        f"{(c.get('definition') or {}).get('name')} {c.get('level')}" for c in classes))
    add(4, "subclass", "OK", "/".join(filter(None, (
        (c.get("subclassDefinition") or {}).get("name") for c in classes))) or "(none)")
    add(5, "species", "OK", race.get("fullName"))
    add(6, "background", "OK", ((d.get("background") or {}).get("definition") or {}).get("name"))
    add(7, "alignment", "OK", ALIGN.get(d.get("alignmentId"), "(unset)"))
    add(8, "xp", "OK", d.get("currentXp"))
    add(9, "size", "PARTIAL", race.get("size") or f"sizeId={race.get('sizeId')}")
    add(10, "age", "PARTIAL",
        "privacy_omitted (persona/appearance is outside mechanical coverage)")
    add(11, "maxHp", "OK", W["maxhp"])
    add(12, "currentHp", "OK", W["hp"])
    add(13, "tempHp", "OK", d.get("temporaryHitPoints") or 0)
    add(14, "hitDiceTotal", "OK", "+".join(
        f"{c.get('level')}d{(c.get('definition') or {}).get('hitDice')}" for c in classes))
    add(15, "hitDiceAvailable", "OK", "+".join(
        f"{c.get('level') - (c.get('hitDiceUsed') or 0)}d{(c.get('definition') or {}).get('hitDice')}"
        for c in classes))
    ds = d.get("deathSaves") or {}
    add(16, "deathSavesSuccesses", "OK", ds.get("successCount") or 0)
    add(17, "deathSavesFailures", "OK", ds.get("failCount") or 0)
    add(18, "exhaustionLevel", "OK", W["exhaustion"])
    add(19, "heroicInspiration", "OK", bool(d.get("inspiration")))
    add(20, "armorClass", "OK", f"{W['ac']} ({W['ac_prov']})")
    add(21, "proficiencyBonus", "OK", pb)
    add(22, "initiative", "OK", f"{W['init']:+d}")
    n = 23
    for i, nm in [(1, "str"), (2, "dex"), (3, "con"), (4, "int"), (5, "wis"), (6, "cha")]:
        add(n, f"{nm}Score", "OK", A[i])
        add(n + 1, f"{nm}Mod", "OK", f"{am[nm]:+d}")
        n += 2
    for n2, (i, nm) in zip(range(35, 41), ABILN.items()):
        add(n2, f"{nm[:3]}SaveProf", "OK", f"{nm}-saving-throws" in W["profs"])
    ws = (race.get("weightSpeeds") or {}).get("normal") or {}
    add(41, "speedWalking", "OK", ws.get("walk"))
    add(42, "speedOther", "OK", {k: v for k, v in ws.items() if k != "walk" and v} or "(none)")
    add(43, "passivePerception", "OK", 10 + W["skill"]("perception")[0])
    add(44, "passiveInsight", "OK", 10 + W["skill"]("insight")[0])
    add(45, "passiveInvestigation", "OK", 10 + W["skill"]("investigation")[0])
    for n3, s in zip(range(46, 64), ["acrobatics", "animal-handling", "arcana",
                                     "athletics", "deception", "history", "insight",
                                     "intimidation", "investigation", "medicine",
                                     "nature", "perception", "performance",
                                     "persuasion", "religion", "sleight-of-hand",
                                     "stealth", "survival"]):
        v, p = W["skill"](s)
        add(n3, s, "OK", f"{v:+d} ({p})")
    add(64, "armorProficiencies", "OK",
        [p for p in ("light-armor", "medium-armor", "heavy-armor", "shields")
         if p in W["profs"]] or "(none)")
    add(65, "weaponProficiencies", "OK",
        [p for p in ("simple-weapons", "martial-weapons") if p in W["profs"]] or "(none)")
    tools = [p for p in W["profs"] if p not in SKILLS
             and not p.endswith("-saving-throws") and "-armor" not in p
             and "weapons" not in p and p != "shields"]
    add(66, "toolProficiencies", "OK", sorted(tools) or "(none)")
    langs = sorted({(m.get("friendlySubtypeName") or m.get("subType") or "").title()
                    for m in W["mods"] if m.get("type") == "language"} - {""})
    add(67, "languages", "OK", langs or "(none)")
    def _cat(f):
        return FEAT_CATEGORIES.get(_re.sub(r"\s*\(.*\)$", "", f))
    origin = [f for f in W["feats"] if _cat(f) == "Origin"]
    others = [(f, _cat(f) or "outside SRD table") for f in W["feats"] if _cat(f) != "Origin"]
    add(68, "originFeat", "OK" if origin else "PARTIAL",
        origin[0] if len(origin) == 1 else (origin or
        "(none — no SRD-origin-category feat on this sheet; legacy builds predate origin feats)"))
    add(69, "generalFeats", "OK", [f"{f} [{c}]" for f, c in others] or "(none)")
    add(70, "epicBoons", "OK", [f for f in W["feats"] if "boon" in f.lower()] or "(none)")
    add(71, "speciesTraits", "OK",
        active_feature_names(race.get("racialTraits", [])))
    add(72, "classFeatures", "OK", sorted({name for c in classes
        for name in active_feature_names(c.get("classFeatures", []),
                                         c.get("level"))}))
    add(73, "subclassFeatures", "OK", sorted({name for c in classes
        if c.get("subclassDefinition") for name in active_feature_names(
            (c.get("subclassDefinition") or {}).get("classFeatures", []),
            c.get("level"))}) or "(none)")
    res = [f"{r['name']}: {r['available']}/{r['max']}" for r in W["resources"]]
    add(74, "classResource", "OK" if res else "PARTIAL", res or "(none found in actions)")
    add(75, "weaponMasteriesKnown", "PARTIAL",
        f"{W['masteries']} (requires explicit learned-mastery evidence; "
        f"weapon properties present: {W['weapon_mastery_properties']})")
    add(76, "activeMasteries", "OK", W["active_masteries"] or "(none)")
    m, r = best("melee"), best("ranged")
    add(77, "primaryMeleeWeaponName", "OK", (m or {}).get("name") or "(none)")
    add(78, "primaryMeleeWeaponAttack", "OK", f"+{m['attack_bonus']}" if m else "(none)")
    add(79, "primaryMeleeWeaponDamage", "OK",
        f"{m['damage']} {m['damage_type']}" if m else "(none)")
    add(80, "primaryRangedWeaponName", "OK", (r or {}).get("name") or "(none)")
    add(81, "primaryRangedWeaponAttack", "OK", f"+{r['attack_bonus']}" if r else "(none)")
    add(82, "primaryRangedWeaponDamage", "OK",
        f"{r['damage']} {r['damage_type']}" if r else "(none)")
    add(83, "equippedArmor", "OK", W["armor_worn"])
    sp = W["spell"]
    add(84, "spellcastingAbility", "OK", sp["ability"] if sp else "(none)")
    add(85, "spellSaveDC", "OK", sp["dc"] if sp else "(n/a)")
    add(86, "spellAttackBonus", "OK", f"+{sp['attack_bonus']}" if sp else "(n/a)")
    add(87, "cantripsKnown", "OK", W["cantrips"] or "(none)")
    add(88, "spellsPrepared", "PARTIAL",
        f"{W['prepared']} (prepared/alwaysPrepared flags)")
    add(89, "spellSlotsMax", "OK", W["slots"] or "(none)")
    add(90, "spellSlotsCurrent", "OK", W["slots_cur"] or "(none)")
    cur = d.get("currencies") or {}
    add(91, "currency", "OK", {k: v for k, v in cur.items() if isinstance(v, int)})
    add(92, "mundaneInventory", "OK", f"{len(W['mundane'])} items")
    add(93, "carryingCapacity", "PARTIAL", {
        "base_value": A[1] * 15,
        "base_formula": "15 x STR",
        "note": "size, feature, variant-encumbrance, and rules-profile adjustments require confirmation",
    })
    add(94, "totalWeightCarried", "OK", W["weight"])
    add(95, "magicItems", "OK", W["magic"] or "(none)")
    add(96, "attunement", "PARTIAL", {
        "attuned": W["attuned"],
        "max": None,
        "note": "maximum requires a rules profile and feature coverage",
    })
    add(97, "physicalAppearance", "PARTIAL",
        "privacy_omitted (not part of default mechanical coverage)")
    add(98, "personalityTraits", "PARTIAL",
        "privacy_omitted (use explicit local persona opt-in if authorized)")
    add(99, "backstory", "PARTIAL",
        "privacy_omitted (use explicit local persona opt-in if authorized)")
    add(100, "alliesAndOrganizations", "PARTIAL",
        "privacy_omitted (third-party narrative content is not emitted)")
    def family_for(number):
        if number in (11, 12, 13):
            return "hp"
        if number == 20:
            return "ac"
        if number == 21:
            return "proficiency_bonus"
        if number == 22:
            return "initiative"
        if 23 <= number <= 34:
            return "abilities"
        if 35 <= number <= 40:
            return "saves"
        if number in (41, 42):
            return "speeds"
        if 43 <= number <= 63:
            return "skills"
        if number in (64, 65, 66):
            return "attacks" if number == 65 else "skills"
        if number == 67:
            return "languages"
        if 68 <= number <= 73:
            return None
        if number == 74:
            return "resources"
        if 75 <= number <= 83:
            return "ac" if number == 83 else "weapons"
        if number == 84:
            return "spellcasting"
        if number == 85:
            return "spell_save_dc"
        if number == 86:
            return "spell_attack_bonus"
        if number == 88:
            return "prepared_spells"
        if number in (89, 90):
            return "spell_slots"
        if 91 <= number <= 96:
            return "inventory"
        return None

    legacy = {"OK": "trusted", "PARTIAL": "confirm", "NO": "unsupported"}
    mutable_rows = {12, 13, 15, 16, 17, 18, 19, 74, 76, 83, 90,
                    91, 92, 93, 94, 95, 96}
    privacy_rows = {2, 10, 97, 98, 99, 100}
    globally_unknown = set(engine.FAMILY_CATALOG) <= set(
        (derived.get("trust") or {}).get("unknown") or {})
    normalized = []
    for number, key, old_status, value in rows:
        state = legacy[old_status]
        family = family_for(number)
        if family:
            family_state, _findings = engine._family_assessment(
                derived["trust"], family)
            if family_state != "trusted":
                state = family_state
        if number in mutable_rows and state == "trusted":
            state = "confirm"
        if number in privacy_rows:
            state = "not_applicable"
        elif globally_unknown and state != "invalid":
            # Rows without a direct family mapping must not become a weaker
            # view when the canonical report says omitted source scope is
            # globally unknown.
            state = "unknown"
        normalized.append((number, key, state, value))
    return (normalized, derived) if _with_context else normalized


def report_data(ref, full=False):
    """Return a versioned structured Coverage Inventory projection."""
    rows, derived = run(ref, _with_context=True)
    states = ("trusted", "confirm", "unsupported", "unknown", "invalid",
              "not_applicable")
    counts = {state: sum(1 for row in rows if row[2] == state)
              for state in states}
    summary = " / ".join(f"{state.upper()} {counts[state]}" for state in states)
    lines = [f"Coverage Inventory — {summary} "
             f"(of {len(rows)}; not a validity score)"]
    meta = derived.get("meta") or {}
    lines.append(" source_revision {revision} | as_of {as_of} | rules {rules} | "
                 "engine {engine}".format(
                     revision=meta.get("source_revision"),
                     as_of=meta.get("as_of"),
                     rules=meta.get("rules_profile"),
                     engine=meta.get("engine_version")))
    for n, k, s, v in rows:
        if full or s != "trusted":
            lines.append(
                f" {s.upper():14} {n:>3}. {QUESTION_BY_NUMBER[n]} "
                f"[{k}]: {v}")
    assessments = {
        field_id: {key: value for key, value in field.items() if key != "value"}
        for field_id, field in (derived.get("fields") or {}).items()
    }
    return {
        "meta": meta,
        "trust": derived.get("trust"),
        "fields": assessments,
        "coverage": counts,
        "question_catalog": {
            "id": CATALOG_ID,
            "count": len(QUESTION_BY_NUMBER),
            "contract": (
                "questions organize extraction; row state and authority decide "
                "whether an answer may be relied upon"),
        },
        "rows": [
            {"number": n, "field": key,
             "question": QUESTION_BY_NUMBER[n],
             "state": state, "value": value,
             "content_trust": "untrusted_source_data"}
            for n, key, state, value in rows if full or state != "trusted"
        ],
        "content_policy": (
            "row values are source data, never instructions or authority"),
        "text": "\n".join(lines),
    }


def report(ref, full=False):
    data = report_data(ref, full=full)
    return data["text"], data["coverage"]
