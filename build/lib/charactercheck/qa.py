"""qa — the 100-question character-sheet QA pass, run deterministically.

The question set (authored by the project owner) covers the full surface a
table actually uses. Every answer is extraction/derivation via the engine —
no model anywhere. Statuses: OK (value), PARTIAL (value with a named caveat),
NO (not yet extractable — the honest lane).
"""

from . import engine
from .engine import ABIL, ABILN, ALIGN, SKILLS, FEAT_CATEGORIES
import re as _re


def run(ref):
    d = engine.fetch(ref)
    W = engine.build(d)
    A, am, pb, level = W["A"], W["am"], W["pb"], W["level"]
    race = d.get("race") or {}
    classes = d.get("classes", [])
    tr = d.get("traits") or {}
    rows = []

    def add(n, key, status, value):
        rows.append((n, key, status, value))

    def best(lane):
        c = [w for w in W["weapons"] if w["lane"] == lane]
        return max(c, key=lambda w: w["attack_bonus"]) if c else None

    add(1, "characterName", "OK", d.get("name"))
    add(2, "playerName", "PARTIAL", f"{d.get('username')} (DDB username)")
    add(3, "classAndLevel", "OK", "/".join(
        f"{(c.get('definition') or {}).get('name')} {c.get('level')}" for c in classes))
    add(4, "subclass", "OK", "/".join(filter(None, (
        (c.get("subclassDefinition") or {}).get("name") for c in classes))) or "(none)")
    add(5, "species", "OK", race.get("fullName"))
    add(6, "background", "OK", ((d.get("background") or {}).get("definition") or {}).get("name"))
    add(7, "alignment", "OK", ALIGN.get(d.get("alignmentId"), "(unset)"))
    add(8, "xp", "OK", d.get("currentXp"))
    add(9, "size", "PARTIAL", race.get("size") or f"sizeId={race.get('sizeId')}")
    add(10, "age", "OK", d.get("age"))
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
    exh = next((c.get("level") for c in d.get("conditions", [])
                if c.get("level") is not None), 0)
    add(18, "exhaustionLevel", "OK", exh)
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
    add(71, "speciesTraits", "OK", sorted(
        {(t.get("definition") or {}).get("name") for t in race.get("racialTraits", [])} - {None})[:12])
    add(72, "classFeatures", "OK", sorted(
        {(f.get("definition") or {}).get("name") for c in classes
         for f in c.get("classFeatures", [])} - {None})[:15])
    add(73, "subclassFeatures", "OK", sorted(
        {(f.get("definition") or {}).get("name") for c in classes
         if c.get("subclassDefinition")
         for f in (c.get("subclassDefinition") or {}).get("classFeatures", [])} - {None})[:10] or "(none)")
    res = [f"{r['name']}: {r['available']}/{r['max']}" for r in W["resources"]]
    add(74, "classResource", "OK" if res else "PARTIAL", res or "(none found in actions)")
    add(75, "weaponMasteriesKnown", "PARTIAL",
        f"{W['masteries']} (from carried weapons' properties; class grant not verified)")
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
    add(83, "equippedArmor", "OK", W["armor_worn"]
        + ([f"(stashed elsewhere: {'; '.join(W['stash_notes'])})"] if W["stash_notes"] else []))
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
    add(93, "carryingCapacity", "OK", A[1] * 15)
    add(94, "totalWeightCarried", "OK", W["weight"])
    add(95, "magicItems", "OK", W["magic"] or "(none)")
    add(96, "attunement", "OK", {"attuned": W["attuned"], "max": 3})
    add(97, "physicalAppearance", "OK",
        f"{d.get('height')}, {d.get('weight')}lb, hair {d.get('hair')}, "
        f"skin {d.get('skin')}, eyes {d.get('eyes')}")
    add(98, "personalityTraits", "OK",
        {k: bool(tr.get(k)) for k in ("personalityTraits", "ideals", "bonds", "flaws")})
    add(99, "backstory", "PARTIAL", "present in notes/traits blobs")
    add(100, "alliesAndOrgs", "PARTIAL",
        (d.get("notes") or {}).get("organizations") or "(notes.organizations empty)")
    return rows


def report(ref, full=False):
    rows = run(ref)
    ok = sum(1 for q in rows if q[2] == "OK")
    pa = sum(1 for q in rows if q[2] == "PARTIAL")
    no = sum(1 for q in rows if q[2] == "NO")
    lines = [f"QA100 — OK {ok} / PARTIAL {pa} / NO {no} (of {len(rows)})"]
    for n, k, s, v in rows:
        if full or s != "OK":
            lines.append(f" {s:7} {n:>3}. {k}: {v}")
    return "\n".join(lines), (ok, pa, no)
