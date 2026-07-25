"""charactercheck engine — deterministic derivation of a D&D Beyond character.

One engine, several views. Input: a public D&D Beyond character (URL, id, or a
saved character-service v5 JSON file). Output: derived stats where every value
is deterministic arithmetic over the payload, plus two honesty lanes:

- ``unhandled``: data patterns this engine recognizes as present but does not
  model — reported by name, never silently defaulted.
- ``lint``: things on the sheet that look wrong or ambiguous (nothing equipped,
  multiple worn-armor candidates, stashed containers).

No network beyond the single public character fetch. No auth. No model calls.
"""

import json
import os
import re
import urllib.request

ABIL = {1: "str", 2: "dex", 3: "con", 4: "int", 5: "wis", 6: "cha"}
ABILN = {1: "strength", 2: "dexterity", 3: "constitution",
         4: "intelligence", 5: "wisdom", 6: "charisma"}
ALIGN = {1: "LG", 2: "NG", 3: "CG", 4: "LN", 5: "N", 6: "CN",
         7: "LE", 8: "NE", 9: "CE"}
SKILLS = {"acrobatics": "dex", "animal-handling": "wis", "arcana": "int",
          "athletics": "str", "deception": "cha", "history": "int",
          "insight": "wis", "intimidation": "cha", "investigation": "int",
          "medicine": "wis", "nature": "int", "perception": "wis",
          "performance": "cha", "persuasion": "cha", "religion": "int",
          "sleight-of-hand": "dex", "stealth": "dex", "survival": "wis"}
# DDB skill entity ids (characterValues valueId space for typeIds 24-27)
SKILL_IDS = {3: "acrobatics", 11: "animal-handling", 6: "arcana", 2: "athletics",
             16: "deception", 7: "history", 12: "insight", 17: "intimidation",
             8: "investigation", 13: "medicine", 9: "nature", 14: "perception",
             18: "performance", 19: "persuasion", 10: "religion",
             4: "sleight-of-hand", 5: "stealth", 15: "survival"}
MASTERIES = {"Vex", "Nick", "Sap", "Topple", "Slow", "Push", "Graze",
             "Cleave", "Flex"}

# SRD 5.2.1 feat categories (closed set, extracted from the source text).
FEAT_CATEGORIES = {
    "Alert": "Origin", "Magic Initiate": "Origin", "Savage Attacker": "Origin",
    "Skilled": "Origin", "Ability Score Improvement": "General",
    "Grappler": "General", "Archery": "Fighting Style", "Defense": "Fighting Style",
    "Great Weapon Fighting": "Fighting Style", "Two-Weapon Fighting": "Fighting Style",
    "Boon of Combat Prowess": "Epic Boon", "Boon of Dimensional Travel": "Epic Boon",
    "Boon of Fate": "Epic Boon", "Boon of Irresistible Offense": "Epic Boon",
    "Boon of Spell Recall": "Epic Boon", "Boon of Truesight": "Epic Boon",
    "Boon of the Night Spirit": "Epic Boon",
}

# Blast-radius map: which derived stats an unhandled pattern could affect.
# Data, versioned with the package. Unknown patterns get the honest maximal
# radius. (v0.2 — cold-probe feedback: name WHICH numbers to double-check.)
BLAST_MAP = {
    "characterValues typeId 34": (["spell_attack_bonus"], "per-spell-class attack override family"),
    "characterValues typeId 35": (["spell_save_dc"], "per-spell-class DC bonus family"),
    "characterValues typeId 33": (["spellcasting"], "spell-class override family"),
    "bonus:speed": (["speeds"], "movement bonus"),
    "bonus:magic": (["attacks"], "magic attack bonus"),
    "bonus:saving-throws": (["saves"], "all-saves bonus"),
    "bonus:proficiency-bonus": (["proficiency_bonus", "saves", "skills", "attacks", "spell_save_dc"], "PB modifier"),
}
MAXIMAL = ["unknown — treat all derived values as unverified"]

# modifier type:subType patterns the engine understands (everything else is
# reported in `unhandled.modifiers` — the completeness contract)
_SKILL_SET = set(SKILLS)


def _recognized(mtype, msub):
    if mtype == "bonus":
        return (msub.endswith("-score") or msub == "initiative"
                or msub in _SKILL_SET or msub == "ability-score-maximum"
                or msub in ("hit-points", "hit-points-per-level",
                            "armor-class", "armored-armor-class",
                            "dual-wield-armor-class"))
    return mtype in ("proficiency", "replace-weapon-ability", "language",
                     "immunity", "resistance", "set-base", "set",
                     "enable-feature", "expertise", "half-proficiency",
                     "advantage", "disadvantage", "sense", "ignore",
                     "protection", "vulnerability", "damage", "carrying-capacity")


def fetch(ref):
    """Load a character: local JSON file path, bare id, or dndbeyond URL."""
    if os.path.exists(ref):
        d = json.load(open(ref))
        return d.get("data", d)
    m = re.search(r"(\d+)", str(ref))
    if not m:
        raise ValueError(f"no character id found in: {ref!r}")
    url = ("https://character-service.dndbeyond.com/character/v5/character/"
           + m.group(1))
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "charactercheck (+https://github.com/chaoz23/charactercheck)"})
    return json.load(urllib.request.urlopen(req))["data"]


def _mod(score):
    return (score - 10) // 2


def build(d):
    """Derive everything once. Returns the raw derivation workspace (dict).

    Prefer :func:`derive` for the shaped, provenance-carrying result.
    """
    W = {"lint": [], "unhandled_modifiers": [], "notes": []}
    cid = d["id"]

    # ---- modifiers: character buckets EXCEPT item, plus activation-gated
    # per-item grantedModifiers (character.modifiers.item is NOT equip-filtered)
    mods = [m for src, ml in (d.get("modifiers") or {}).items()
            if src != "item" for m in (ml or [])]
    for it in d.get("inventory", []):
        de = it.get("definition") or {}
        active = ((de.get("canAttune") and it.get("isAttuned"))
                  or (not de.get("canAttune") and it.get("equipped"))
                  or (not de.get("canEquip") and not de.get("canAttune")
                      and not de.get("isConsumable")))
        if active:
            mods += de.get("grantedModifiers") or []
    W["mods"] = mods
    unrec = sorted({f"{m.get('type')}:{m.get('subType')}" for m in mods
                    if not _recognized(m.get("type") or "", m.get("subType") or "")})
    W["unhandled_modifiers"] = unrec

    # ---- characterValues (typeId semantics: see docs/ddb-schema-notes.md)
    cv = d.get("characterValues") or []
    cname = {str(c["valueId"]): c["value"] for c in cv if c.get("typeId") == 8}
    cnotes = {str(c["valueId"]): c["value"] for c in cv if c.get("typeId") == 9}
    hexflag = {str(c["valueId"]): str(c["value"]) == "True"
               for c in cv if c.get("typeId") in (28, 29)}
    ac_override = next((int(c["value"]) for c in cv
                        if c.get("typeId") == 1 and c.get("value") is not None), None)
    ac_adj = sum(int(c["value"]) for c in cv
                 if c.get("typeId") in (2, 3) and c.get("value") is not None)
    known_cv = {1, 2, 3, 8, 9, 10, 18, 19, 22, 24, 25, 26, 27, 28, 29, 39, 40, 41}
    unk_cv = sorted({c.get("typeId") for c in cv if c.get("typeId") not in known_cv})
    if unk_cv:
        W["unhandled_modifiers"] += [f"characterValues typeId {t}" for t in unk_cv]
    W.update(cname=cname, cnotes=cnotes, hexflag=hexflag,
             ac_override=ac_override, ac_adj=ac_adj)

    # ---- container graph: carried = chain to character w/o a stashed container
    byid = {it["id"]: it for it in d.get("inventory", [])}

    def _stashed(iid):
        nm = (cname.get(str(iid)) or "").lower()
        return "stash" in nm or "left @" in nm

    def carried(it):
        cur = it
        while True:
            if _stashed(cur["id"]):
                return False
            parent = cur.get("containerEntityId")
            if parent == cid or parent not in byid:
                return True
            cur = byid[parent]

    W["carried"] = carried
    W["stash_notes"] = [
        f"{cname.get(str(it['id']), (it.get('definition') or {}).get('name'))}"
        + (f": {cnotes[str(it['id'])]}" if str(it["id"]) in cnotes else "")
        for it in d.get("inventory", []) if _stashed(it["id"])]

    # ---- ability scores: base + racial/feat bonuses, capped at 20 (+max
    # raises), set-if-not-higher, characterValues 39/40 bonus + 41 override
    base = {s["id"]: s["value"] or 10 for s in d["stats"]}
    over = {s["id"]: s["value"] for s in d.get("overrideStats", []) if s.get("value")}
    bon = {s["id"]: s["value"] or 0 for s in d.get("bonusStats", [])}
    for m in mods:
        st = m.get("subType") or ""
        if m.get("type") == "bonus" and st.endswith("-score"):
            for i, n in ABILN.items():
                if st == f"{n}-score":
                    base[i] = base.get(i, 10) + (m.get("value") or 0)
    cv_over = {int(c["valueId"]): int(c["value"]) for c in cv
               if c.get("typeId") == 41 and c.get("value") is not None}
    cv_bon = {}
    for c in cv:
        if c.get("typeId") in (39, 40) and c.get("value") is not None:
            cv_bon[int(c["valueId"])] = cv_bon.get(int(c["valueId"]), 0) + int(c["value"])
    cap = {i: 20 for i in range(1, 7)}
    setv = {i: 0 for i in range(1, 7)}
    for m in mods:
        st = m.get("subType") or ""
        if m.get("type") == "bonus" and st == "ability-score-maximum":
            for i in range(1, 7):
                cap[i] += m.get("value") or 0
        if m.get("type") == "set" and m.get("isGranted", True):
            for i, n in ABILN.items():
                if st == f"{n}-score":
                    setv[i] = max(setv[i], m.get("value") or 0)
    A = {}
    for i in range(1, 7):
        v = min(base.get(i, 10) + bon.get(i, 0) + cv_bon.get(i, 0), cap[i])
        v = max(v, setv[i])
        A[i] = cv_over.get(i) or over.get(i) or v
    am = {ABIL[i]: _mod(v) for i, v in A.items()}
    W.update(A=A, am=am)

    level = sum(c.get("level", 0) for c in d.get("classes", []))
    pb = 2 + max(0, (level - 1)) // 4
    W.update(level=level, pb=pb)

    # ---- proficiencies / skills
    profs = {(m.get("subType") or "").lower() for m in mods if m.get("type") == "proficiency"}
    expertise = {(m.get("subType") or "").lower() for m in mods if m.get("type") == "expertise"}
    halfprof = {(m.get("subType") or "").lower() for m in mods if m.get("type") == "half-proficiency"}
    skill_bonus = {}
    for m in mods:
        st = (m.get("subType") or "").lower()
        if m.get("type") == "bonus" and st in SKILLS:
            skill_bonus[st] = skill_bonus.get(st, 0) + (m.get("value") or 0)
    cv_skill_bon, cv_skill_prof, cv_skill_abil = {}, {}, {}
    for c in cv:
        try:
            sk = SKILL_IDS.get(int(c.get("valueId")))
        except (TypeError, ValueError):
            sk = None
        if not sk or c.get("value") is None:
            continue
        if c.get("typeId") in (24, 25):
            cv_skill_bon[sk] = cv_skill_bon.get(sk, 0) + int(c["value"])
        elif c.get("typeId") == 26:
            cv_skill_prof[sk] = int(c["value"])  # 1 none / 2 half / 3 prof / 4 expertise
        elif c.get("typeId") == 27:
            cv_skill_abil[sk] = ABIL.get(int(c["value"]))

    def skill(n):
        abil = cv_skill_abil.get(n) or SKILLS[n]
        b = am[abil] + skill_bonus.get(n, 0) + cv_skill_bon.get(n, 0)
        lvl = cv_skill_prof.get(n)
        if lvl == 4 or (lvl is None and n in expertise):
            return b + 2 * pb, "expertise"
        if lvl == 3 or (lvl is None and n in profs):
            return b + pb, "proficient"
        if lvl == 2 or (lvl is None and n in halfprof):
            return b + pb // 2, "half"
        return b, "none"

    W.update(profs=profs, expertise=expertise, halfprof=halfprof, skill=skill)

    # ---- initiative
    init_bonus = sum(m.get("value") or 0 for m in mods
                     if m.get("type") == "bonus" and m.get("subType") == "initiative")
    W["init"] = am["dex"] + init_bonus
    W["init_prov"] = f"DEX {am['dex']:+d}" + (f" + {init_bonus} [bonus:initiative]" if init_bonus else "")

    # ---- weapon ability replacement (Hex Warrior etc.)
    weapon_abil = None
    for m in mods:
        if m.get("type") == "replace-weapon-ability":
            st = (m.get("subType") or "").replace("-score", "")
            for i, n in ABILN.items():
                if st == n:
                    weapon_abil = ABIL[i]
    W["weapon_abil"] = weapon_abil

    # ---- AC: equipped-first armor, shield only if equipped, unarmored
    # formulas, item/feat AC bonuses, manual adjustments, override wins
    body, shields = [], []
    for it in d.get("inventory", []):
        de = it.get("definition") or {}
        if not carried(it):
            continue
        if de.get("armorTypeId") == 4:
            shields.append(it)
        elif de.get("armorClass"):
            body.append(it)

    def acof(it):
        de = it["definition"]
        t = de.get("armorTypeId")
        dex = am["dex"] if t == 1 else min(am["dex"], 2) if t == 2 else 0
        return de["armorClass"] + dex

    worn = [i for i in body if i.get("equipped")]
    if not worn and body:
        worn = sorted(body, key=acof, reverse=True)[:1]
        W["lint"].append("no armor flagged equipped — best carried armor assumed; confirm worn kit")
    if len([i for i in body if i.get("equipped")]) > 1:
        W["lint"].append("multiple body armors flagged equipped — using the first; confirm")
    unarmored = 10 + am["dex"]
    unarmored_prov = f"10 + DEX {am['dex']:+d}"
    for m in mods:
        if (m.get("type") == "set" and m.get("subType") == "unarmored-armor-class"
                and m.get("isGranted", True)):
            u = 10 + am["dex"] + (m.get("value") or 0)
            sid = m.get("statId")
            if sid:
                u += am[ABIL.get(sid, "dex")]
            if u > unarmored:
                unarmored = u
                unarmored_prov = (f"10 + DEX {am['dex']:+d}"
                                  + (f" + {ABIL.get(sid, '?').upper()} {am[ABIL.get(sid, 'dex')]:+d}" if sid else "")
                                  + (f" + {m.get('value')}" if m.get("value") else "")
                                  + " [unarmored defense]")
    ac_mod_bonus = sum(m.get("value") or 0 for m in mods
                       if m.get("type") == "bonus"
                       and (m.get("subType") or "") in ("armor-class", "armored-armor-class"))
    prov = []
    if worn:
        de = worn[0]["definition"]
        ac = acof(worn[0])
        t = de.get("armorTypeId")
        dexterm = am["dex"] if t == 1 else min(am["dex"], 2) if t == 2 else 0
        prov.append(f"{cname.get(str(worn[0]['id']), de.get('name'))} {de.get('armorClass')}")
        if dexterm:
            prov.append(f"DEX {dexterm:+d}" + (" [capped 2]" if t == 2 and am["dex"] > 2 else ""))
    else:
        ac = unarmored
        prov.append(unarmored_prov)
    if ac_mod_bonus:
        ac += ac_mod_bonus
        prov.append(f"+{ac_mod_bonus} [feat/item modifiers]")
    if ac_adj:
        ac += ac_adj
        prov.append(f"+{ac_adj} [manual adjustment]")
    sh_eq = [i for i in shields if i.get("equipped")]
    shac = ((shields[0].get("definition") or {}).get("armorClass") or 2) if shields else 0
    if sh_eq:
        ac += shac
        prov.append(f"Shield +{shac}")
    if ac_override is not None:
        ac = ac_override
        prov = [f"override {ac_override} [manual, typeId 1]"]
    W.update(ac=ac, ac_prov=" + ".join(prov),
             shield_carried=bool(shields), shield_equipped=bool(sh_eq), shac=shac,
             armor_worn=[cname.get(str(w["id"]), w["definition"].get("name")) for w in worn])

    # ---- weapons (carried only), masteries from properties
    weapons, masteries, active_masteries = [], set(), set()
    for it in d.get("inventory", []):
        de = it.get("definition") or {}
        dmg = de.get("damage") or {}
        if not dmg.get("diceString") or not carried(it):
            continue
        props = {p.get("name") for p in de.get("properties") or []}
        ms = props & MASTERIES
        masteries |= ms
        if it.get("equipped"):
            active_masteries |= ms
        lane = "ranged" if de.get("attackType") == 2 else "melee"
        use = (max(am["str"], am["dex"]) if "Finesse" in props
               else am["dex"] if lane == "ranged" else am["str"])
        why = "finesse max(STR,DEX)" if "Finesse" in props else ("DEX" if lane == "ranged" else "STR")
        if weapon_abil and hexflag.get(str(it["id"])) and am[weapon_abil] > use:
            use, why = am[weapon_abil], f"{weapon_abil.upper()} [designated weapon]"
        weapons.append({
            "name": cname.get(str(it["id"]), de.get("name")),
            "base_name": de.get("name"), "lane": lane,
            "equipped": bool(it.get("equipped")),
            "designated": hexflag.get(str(it["id"]), False),
            "attack_bonus": use + pb,
            "attack_provenance": f"{why} {use:+d} + PB {pb}",
            "damage": f"{dmg.get('diceString')}{use:+d}",
            "damage_type": de.get("damageType"),
            "properties": sorted(props), "mastery": sorted(ms),
            "offhand_label": bool(re.search(r"off.?hand", cname.get(str(it["id"]), ""), re.I)),
            "two_handed": "Two-Handed" in props, "light": "Light" in props,
            "loading": "Loading" in props})
    W.update(weapons=weapons, masteries=sorted(masteries),
             active_masteries=sorted(active_masteries))

    # ---- HP (per-level bonuses scaled by granting class where linkable)
    class_feature_levels = {}
    for c in d.get("classes", []):
        for f in (c.get("classFeatures") or []):
            fid = (f.get("definition") or {}).get("id")
            if fid:
                class_feature_levels[fid] = c.get("level", 0)
    hp_per_lvl = sum((m.get("value") or 0)
                     * class_feature_levels.get(m.get("componentId"), level)
                     for m in mods if m.get("type") == "bonus"
                     and m.get("subType") == "hit-points-per-level")
    hp_flat = sum(m.get("value") or 0 for m in mods
                  if m.get("type") == "bonus" and m.get("subType") == "hit-points")
    maxhp = d.get("overrideHitPoints") or (
        (d.get("baseHitPoints") or 0) + am["con"] * level
        + (d.get("bonusHitPoints") or 0) + hp_per_lvl + hp_flat)
    hp_prov = (f"base {d.get('baseHitPoints') or 0} + CON {am['con']:+d}×{level}"
               + (f" + {hp_per_lvl} [per-level bonuses]" if hp_per_lvl else "")
               + (f" + {hp_flat} [flat bonuses]" if hp_flat else "")
               + (" (override)" if d.get("overrideHitPoints") else ""))
    W.update(maxhp=maxhp, hp=maxhp - (d.get("removedHitPoints") or 0), hp_prov=hp_prov)

    # ---- spellcasting
    spell = None
    for c in d.get("classes", []):
        aid = (c.get("definition") or {}).get("spellCastingAbilityId")
        if aid:
            spell = {"ability": ABIL[aid], "dc": 8 + pb + am[ABIL[aid]],
                     "attack_bonus": pb + am[ABIL[aid]],
                     "provenance": f"8 + PB {pb} + {ABIL[aid].upper()} {am[ABIL[aid]]:+d}"}
            break
    entries = []
    for src in (d.get("spells") or {}).values():
        entries += src or []
    for cs in d.get("classSpells") or []:
        entries += cs.get("spells") or []
    cantrips = sorted({(e.get("definition") or {}).get("name") for e in entries
                       if (e.get("definition") or {}).get("level") == 0} - {None})
    prepared = sorted({(e.get("definition") or {}).get("name") for e in entries
                       if ((e.get("definition") or {}).get("level") or 0) > 0
                       and (e.get("prepared") or e.get("alwaysPrepared"))} - {None})
    slots = {s["level"]: s.get("available", 0) for s in d.get("spellSlots", []) if s.get("available")}
    slots_cur = {s["level"]: s.get("available", 0) - s.get("used", 0)
                 for s in d.get("spellSlots", []) if s.get("available")}
    for s in d.get("pactMagic", []) or []:
        if s.get("available"):
            slots[f"pact{s['level']}"] = s["available"]
            slots_cur[f"pact{s['level']}"] = s["available"] - s.get("used", 0)
    W.update(spell=spell, cantrips=cantrips, prepared=prepared,
             slots=slots, slots_cur=slots_cur)
    if spell and not prepared and slots:
        W["lint"].append("caster with slots but zero prepared leveled spells — confirm the prepared list")

    # ---- class resources (limitedUse actions)
    res = []
    for src in (d.get("actions") or {}).values():
        for a in (src or []):
            lu = a.get("limitedUse") or {}
            if lu.get("maxUses") or lu.get("statModifierUsesId") or lu.get("useProficiencyBonus"):
                mx = lu.get("maxUses") or 0
                if lu.get("statModifierUsesId"):
                    mx += am[ABIL.get(lu["statModifierUsesId"], "cha")]
                if lu.get("useProficiencyBonus"):
                    mx += pb
                res.append({"name": a.get("name"),
                            "available": max(mx, 0) - (lu.get("numberUsed") or 0),
                            "max": max(mx, 0)})
    W["resources"] = res

    # ---- inventory / weight (carried only; bundle + custom items)
    inv = [i for i in d.get("inventory", []) if carried(i)]
    weight = sum(((i.get("definition") or {}).get("weight") or 0)
                 * (i.get("quantity") or 1)
                 / ((i.get("definition") or {}).get("bundleSize") or 1) for i in inv)
    weight += sum((ci.get("weight") or 0) * (ci.get("quantity") or 1)
                  for ci in d.get("customItems") or [])
    W.update(
        weight=round(weight, 1),
        mundane=sorted({cname.get(str(i["id"]), (i.get("definition") or {}).get("name"))
                        for i in inv if not (i.get("definition") or {}).get("magic")}
                       | {ci.get("name") for ci in d.get("customItems") or []} - {None}),
        magic=sorted({cname.get(str(i["id"]), (i.get("definition") or {}).get("name"))
                      for i in d.get("inventory", [])
                      if (i.get("definition") or {}).get("magic")} - {None}),
        attuned=sorted({(i.get("definition") or {}).get("name")
                        for i in d.get("inventory", []) if i.get("isAttuned")} - {None}))

    # ---- feats (identification only; classification is downstream's job)
    W["feats"] = [(f.get("definition") or {}).get("name")
                  for f in d.get("feats", []) if (f.get("definition") or {}).get("name")]
    return W


def stance(d, W=None):
    """Hands / AC-state / attack-line block — the pre-combat answers."""
    W = W or build(d)
    eq = [w for w in W["weapons"] if w["equipped"]]
    main = (next((w for w in eq if w["designated"]), None)
            or max((w for w in eq if w["lane"] == "melee"),
                   key=lambda w: w["attack_bonus"], default=None)
            or (eq[0] if eq else None))
    conflicts = []
    if main and main["two_handed"]:
        off = "(two-handed grip)"
        if W["shield_equipped"]:
            conflicts.append("two-handed weapon + equipped shield — impossible; ask the player")
    elif W["shield_equipped"]:
        off = "Shield (raised)"
    else:
        lab = [w for w in eq if w["offhand_label"] and w is not main]
        off = lab[0]["name"] if lab else next(
            (w["name"] for w in eq if w is not main and w["light"] and w["lane"] == "melee"), None)
    ac_states = {"current": W["ac"]}
    if W["shield_carried"] and not W["shield_equipped"]:
        ac_states[f"shield raised (+{W['shac']})"] = {
            "ac": W["ac"] + W["shac"],
            "cost": f"requires the off hand ({off or 'free'})"}
    return {"armor_worn": W["armor_worn"],
            "main_hand": (main or {}).get("name"),
            "off_hand": off,
            "readied": [w["name"] for w in eq if w is not main and w["name"] != off],
            "stowed": [w["name"] for w in W["weapons"] if not w["equipped"]],
            "ac_states": ac_states, "conflicts": conflicts}


def derive(ref):
    """Fetch + derive. The shaped, provenance-carrying public result."""
    d = fetch(ref)
    W = build(d)
    A, am = W["A"], W["am"]
    return {
        "identity": {
            "name": d.get("name"),
            "classes": [f"{(c.get('definition') or {}).get('name')} {c.get('level')}"
                        for c in d.get("classes", [])],
            "subclasses": [s for s in ((c.get("subclassDefinition") or {}).get("name")
                                       for c in d.get("classes", [])) if s],
            "species": (d.get("race") or {}).get("fullName"),
            "background": ((d.get("background") or {}).get("definition") or {}).get("name"),
            "level": W["level"], "proficiency_bonus": W["pb"],
            "alignment": ALIGN.get(d.get("alignmentId")),
            "url": f"https://www.dndbeyond.com/characters/{d.get('id')}"},
        "abilities": {ABIL[i]: {"score": v, "mod": _mod(v)} for i, v in A.items()},
        "saves": {a: {"bonus": am[a] + (W["pb"] if f"{n}-saving-throws" in W["profs"] else 0),
                      "proficient": f"{n}-saving-throws" in W["profs"]}
                  for a, n in [("str", "strength"), ("dex", "dexterity"),
                               ("con", "constitution"), ("int", "intelligence"),
                               ("wis", "wisdom"), ("cha", "charisma")]},
        "skills": {n: {"bonus": W["skill"](n)[0], "proficiency": W["skill"](n)[1]}
                   for n in sorted(SKILLS)},
        "combat": {
            "ac": {"value": W["ac"], "provenance": W["ac_prov"]},
            "initiative": {"bonus": W["init"], "provenance": W["init_prov"]},
            "hp": {"current": W["hp"], "max": W["maxhp"], "provenance": W["hp_prov"]},
            "weapons": W["weapons"],
            "masteries_on_weapons": W["masteries"],
            "stance": stance(d, W)},
        "spellcasting": ({"ability": W["spell"]["ability"], "dc": W["spell"]["dc"],
                          "attack_bonus": W["spell"]["attack_bonus"],
                          "provenance": W["spell"]["provenance"],
                          "cantrips": W["cantrips"], "prepared": W["prepared"],
                          "slots_max": W["slots"], "slots_current": W["slots_cur"]}
                        if W["spell"] else None),
        "resources": W["resources"],
        "inventory": {"weight_carried": W["weight"], "magic_items": W["magic"],
                      "attuned": W["attuned"], "stashed_elsewhere": W["stash_notes"]},
        "feats_identified": [
            {"name": f,
             "category": FEAT_CATEGORIES.get(re.sub(r"\s*\(.*\)$", "", f),
                                             "outside SRD 5.2.1 feat table")}
            for f in W["feats"]],
        "unhandled": {
            "items": [
                {"pattern": pat,
                 "possibly_affects": BLAST_MAP.get(pat, (MAXIMAL, None))[0],
                 "note": BLAST_MAP.get(pat, (None, None))[1]}
                for pat in W["unhandled_modifiers"]],
            "verified_clean": ([] if any(
                BLAST_MAP.get(p, (MAXIMAL, None))[0] == MAXIMAL
                for p in W["unhandled_modifiers"])
                else sorted({"ac", "initiative", "hp", "saves", "skills", "weapons"}
                            - {a for p in W["unhandled_modifiers"]
                               for a in BLAST_MAP.get(p, ([], None))[0]})),
        },
        "lint": W["lint"],
    }


STATE_FIELDS = {"removedHitPoints": "hp.current", "temporaryHitPoints": "hp.temp",
                "inspiration": "heroic_inspiration"}


def diff_payloads(old, new):
    """Classify sheet deltas: the DDB sheet is a LIVE state store players edit
    during play (Oz, 2026-07-24). state_changes = engine's authority, reported
    never applied; build_changes = the player's declaration channel -> mini-
    intake; lint = physically impossible edits; unhandled_new = new content
    the engine doesn't model."""
    out = {"state_changes": [], "build_changes": [], "lint": [], "unhandled_new": []}
    for f, stat in STATE_FIELDS.items():
        if (old.get(f) or 0) != (new.get(f) or 0):
            out["state_changes"].append({"field": f, "was": old.get(f) or 0,
                                         "now": new.get(f) or 0, "affects": [stat]})
    slots_o = {s["level"]: s.get("used", 0) for s in old.get("spellSlots", [])}
    slots_n = {s["level"]: s.get("used", 0) for s in new.get("spellSlots", [])}
    for lvl in sorted(set(slots_o) | set(slots_n)):
        if slots_o.get(lvl, 0) != slots_n.get(lvl, 0):
            out["state_changes"].append({"field": f"spellSlots.L{lvl}.used",
                                         "was": slots_o.get(lvl, 0),
                                         "now": slots_n.get(lvl, 0),
                                         "affects": ["spell_slots_current"]})
    # build: equipped/attuned flips + new/removed items
    def items(d):
        return {it["id"]: it for it in d.get("inventory", [])}
    io, i_n = items(old), items(new)
    Wn = build(new)
    for iid in sorted(set(io) | set(i_n)):
        o, n = io.get(iid), i_n.get(iid)
        name = ((n or o).get("definition") or {}).get("name")
        if o and not n:
            out["build_changes"].append({"field": f"{name}.removed", "affects": ["inventory"]})
        elif n and not o:
            de = n.get("definition") or {}
            entry = {"field": f"{name}.added", "affects": ["inventory"]}
            if de.get("armorClass"):
                entry["affects"] = ["ac", "inventory"]
            out["build_changes"].append(entry)
        else:
            de = n.get("definition") or {}
            if bool(o.get("equipped")) != bool(n.get("equipped")):
                aff = ["ac", "stance"] if de.get("armorClass") else                       (["weapons", "stance"] if (de.get("damage") or {}).get("diceString")
                       else ["inventory"])
                ch = {"field": f"{name}.equipped", "was": bool(o.get("equipped")),
                      "now": bool(n.get("equipped")), "affects": aff}
                if n.get("equipped") and not Wn["carried"](n):
                    out["lint"].append({"finding": f"equipped '{name}' — but it sits in a "
                                        "container stashed elsewhere",
                                        "affects": aff, "severity": "impossible"})
                out["build_changes"].append(ch)
            if bool(o.get("isAttuned")) != bool(n.get("isAttuned")):
                out["build_changes"].append({"field": f"{name}.isAttuned",
                                             "was": bool(o.get("isAttuned")),
                                             "now": bool(n.get("isAttuned")),
                                             "affects": ["attunement"]})
    # new unhandled content
    Wo = build(old)
    new_unh = sorted(set(Wn["unhandled_modifiers"]) - set(Wo["unhandled_modifiers"]))
    for pat in new_unh:
        out["unhandled_new"].append({"pattern": pat,
                                     "possibly_affects": BLAST_MAP.get(pat, (MAXIMAL, None))[0]})
    return out
