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
import urllib.error
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

#: Prefix families for modifier subTypes we do not model individually but whose
#: *target* is legible from the name. Matched longest-prefix-first.
#:
#: Added on UXR from an agent using this at a live table: a single unhandled
#: `bonus:spell-group-healing` was collapsing the whole report to "treat all
#: derived values as unverified", and the agent's objection was exactly right —
#: *"too broad for play. I'd rather see 'affects healing spell output only', so
#: I can still trust AC, saves, skills, HP."* A caveat that covers everything
#: is worth the same as no caveat at all, because nobody can act on it.
BLAST_PREFIXES = [
    ("bonus:spell-group-", (["spell_output"], "bonus to a spell group's output")),
    ("bonus:spell-", (["spellcasting"], "spellcasting bonus")),
    ("bonus:skill-", (["skills"], "skill bonus")),
    ("bonus:damage", (["attacks"], "damage bonus")),
    ("bonus:attack", (["attacks"], "attack bonus")),
    ("bonus:ac", (["ac"], "armor-class bonus")),
    ("bonus:hp", (["hp"], "hit-point bonus")),
    ("bonus:save", (["saves"], "saving-throw bonus")),
]

#: Every family the engine derives. Used to compute what an unhandled item
#: provably did NOT touch.
ALL_FAMILIES = ["ac", "initiative", "hp", "saves", "skills", "weapons",
                "spellcasting", "spell_save_dc", "spell_attack_bonus",
                "spell_output", "speeds", "proficiency_bonus", "attacks"]


def blast(pat):
    """What could this unhandled pattern plausibly affect, and what could it not?

    Returns ``(affects, note)``. Exact map first, then prefix family, then a
    last resort.

    The last resort is deliberately *not* "distrust everything". An unhandled
    modifier is **never applied** — that is what unhandled means — so every
    derived number is exactly what it would be if the modifier did not exist.
    The open question is only whether it *should* have been applied. Saying
    "treat all values as unverified" overstates that into uselessness.
    """
    if pat in BLAST_MAP:
        return BLAST_MAP[pat]
    for prefix, val in sorted(BLAST_PREFIXES, key=lambda kv: -len(kv[0])):
        if pat.startswith(prefix):
            return val
    return (["unknown"], "target not legible from the pattern name; it was "
                         "not applied to any derived value")

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


from . import errors  # noqa: E402  (after stdlib imports)


def fetch(ref):
    """Load a character: local JSON file path, bare id, or dndbeyond URL.

    Every failure here raises a typed :class:`~charactercheck.errors.
    CharacterCheckError` carrying a one-sentence action. Nothing raw escapes:
    a caller that gets a urllib traceback cannot act on it, and an agent that
    gets one will either invent a workaround or open an issue. See
    `charactercheck/errors.py` for the measurement that motivated this.
    """
    if os.path.exists(ref):
        try:
            d = json.load(open(ref))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise errors.bad_json(ref, str(e))
        if not isinstance(d, dict):
            raise errors.bad_json(ref, "top level is not an object")
        return d.get("data", d)
    m = re.search(r"(\d+)", str(ref))
    if not m:
        raise errors.bad_ref(ref)
    url = ("https://character-service.dndbeyond.com/character/v5/character/"
           + m.group(1))
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "charactercheck (+https://github.com/chaoz23/charactercheck)"})
    try:
        raw = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise errors.not_public(ref)
        if e.code == 404:
            raise errors.not_found(ref)
        if e.code == 429:
            raise errors.rate_limited(ref)
        raise errors.upstream(ref, e.code)
    except urllib.error.URLError as e:
        raise errors.network(ref, str(getattr(e, "reason", e)))
    except OSError as e:
        raise errors.network(ref, str(e))
    try:
        payload = json.load(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise errors.bad_json(ref, str(e))
    if not isinstance(payload, dict) or "data" not in payload:
        raise errors.bad_json(ref, "response has no 'data' object")
    return payload["data"]


def _mod(score):
    return (score - 10) // 2


#: The SRD multiclass spellcaster table: caster level -> slots per spell level.
#: This is the *independent anchor* for the completeness check below. A
#: character's class levels imply how many slots must exist; if the payload
#: reports none, the payload is wrong, not the rules.
SLOT_TABLE = {
    1: [2], 2: [3], 3: [4, 2], 4: [4, 3], 5: [4, 3, 2], 6: [4, 3, 3],
    7: [4, 3, 3, 1], 8: [4, 3, 3, 2], 9: [4, 3, 3, 3, 1], 10: [4, 3, 3, 3, 2],
    11: [4, 3, 3, 3, 2, 1], 12: [4, 3, 3, 3, 2, 1],
    13: [4, 3, 3, 3, 2, 1, 1], 14: [4, 3, 3, 3, 2, 1, 1],
    15: [4, 3, 3, 3, 2, 1, 1, 1], 16: [4, 3, 3, 3, 2, 1, 1, 1],
    17: [4, 3, 3, 3, 2, 1, 1, 1, 1], 18: [4, 3, 3, 3, 3, 1, 1, 1, 1],
    19: [4, 3, 3, 3, 3, 2, 1, 1, 1], 20: [4, 3, 3, 3, 3, 2, 2, 1, 1],
}
FULL_CASTERS = {"bard", "cleric", "druid", "sorcerer", "wizard"}
HALF_CASTERS = {"paladin", "ranger"}          # slots begin at class level 2
PACT_CASTERS = {"warlock"}                    # pact magic, counted separately


def caster_level(classes):
    """Effective spellcaster level for the multiclass slot table.

    Warlocks are excluded on purpose: pact magic is its own progression and
    does not combine with the table (SRD multiclassing).
    """
    lvl = 0
    for c in classes or []:
        name = ((c.get("definition") or {}).get("name") or "").strip().lower()
        n = c.get("level") or 0
        if name in FULL_CASTERS:
            lvl += n
        elif name in HALF_CASTERS:
            lvl += n // 2
    return lvl


def expected_slots(classes):
    """Slots a character of these classes must have, per the SRD table."""
    return SLOT_TABLE.get(caster_level(classes))


def _slot_rows(d, key):
    return [r for r in (d.get(key) or []) if isinstance(r, dict)]



#: Families a caller can route on. Kept in one place so the trust map, the
#: lint entries and `verified_clean` cannot drift apart.
TRUST_FAMILIES = ["ac", "hp", "initiative", "saves", "skills", "attacks",
                  "weapons", "speeds", "proficiency_bonus", "spellcasting",
                  "spell_save_dc", "spell_attack_bonus", "spell_output",
                  "spell_slots", "prepared_spells", "inventory"]


def _lint(W, code, message, ask=None, affects=()):
    """Record a lint finding as something a caller can act on.

    From live agent UXR: *"Every lint/unhandled should include a short human
    question… This is the difference between 'tool reports caveat' and 'agent
    resolves caveat at table.'"* Exactly right, and it is the same move that
    made the exit-3 errors useful — a finding without a next action is
    archaeology.

    `affects` names the families this finding puts in doubt, which is what
    routes them out of `trusted` and into `ask_player` in the trust map.
    """
    W["lint"].append({"code": code, "message": message,
                      "ask": ask, "affects": sorted(affects)})


def trust_map(lint, unhandled):
    """Route every family into trusted / ask_player / unsupported.

    From live agent UXR: *"agents need routing, not archaeology."* The three
    lists already existed — `verified_clean`, `lint`, `unhandled` — but
    scattered in shapes tuned for a human reading a report. An agent under
    turn pressure needs one place that answers "may I state this number?"

    The three lanes are deliberately exclusive and ordered by severity:

      * ``unsupported`` — the engine saw something it does not model that
        targets this family. Do not state these; say what is missing.
      * ``ask_player``  — derived, but a lint puts it in doubt. One human
        question resolves it, and that question is in ``asks``.
      * ``trusted``     — nothing outstanding touches it. Safe to state.
    """
    unsupported = {}
    for item in (unhandled or {}).get("items", []):
        for fam in item.get("possibly_affects", []):
            if fam in TRUST_FAMILIES:
                unsupported.setdefault(fam, []).append(item["pattern"])

    ask = {}
    for f in lint or []:
        for fam in f.get("affects", []):
            if fam in unsupported:
                continue
            ask.setdefault(fam, []).append(
                {"code": f.get("code"), "ask": f.get("ask")})

    trusted = [f for f in TRUST_FAMILIES
               if f not in unsupported and f not in ask]

    asks = []
    seen = set()
    for f in lint or []:
        q = f.get("ask")
        if q and q not in seen:
            seen.add(q)
            asks.append({"code": f.get("code"), "ask": q,
                         "affects": f.get("affects", [])})

    return {"trusted": trusted,
            "ask_player": {k: v for k, v in sorted(ask.items())},
            "unsupported": {k: sorted(set(v)) for k, v in sorted(unsupported.items())},
            "asks": asks,
            "note": ("Unsupported content was NOT applied to any derived value — "
                     "trust the computed fields, but do not improvise around the "
                     "named unsupported feature.")}


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
    # verbatim payload text per unhandled pattern (the intake interview reads
    # the source's own words, never a paraphrase)
    W["unhandled_text"] = {}
    for m in mods:
        pat = f"{m.get('type')}:{m.get('subType')}"
        if pat in unrec and pat not in W["unhandled_text"]:
            txt = ": ".join(b for b in (m.get("friendlyTypeName"),
                                        m.get("friendlySubtypeName")) if b)
            if m.get("restriction"):
                txt += f" [restriction: {m['restriction']}]"
            if txt:
                W["unhandled_text"][pat] = txt[:280]

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
        _lint(W, "armor_not_equipped",
              "no armor flagged equipped — best carried armor assumed; confirm worn kit",
              ask="Which armour are you actually wearing right now?",
              affects=["ac"])
    if len([i for i in body if i.get("equipped")]) > 1:
        _lint(W, "multiple_armor_equipped",
              "multiple body armors flagged equipped — using the first; confirm",
              ask="You have more than one suit of armour marked worn — which one is on?",
              affects=["ac"])
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
    # ---- completeness oracle: do the slots the rules require actually exist?
    #
    # From live agent UXR: a Cleric 3 came back with slots_max {} because every
    # DDB spellSlots row read available:0. That is not depletion — depletion
    # shows as used>0. It is a payload that never populated the maxima, and a
    # table cannot see the difference without an independent anchor. The class
    # levels ARE that anchor (SLOT_TABLE above).
    classes = d.get("classes") or []
    exp = expected_slots(classes)

    def _slot_gap(rows, label, expectation):
        """Diagnose a slot block. Two failures hide behind one symptom.

        `available` is the maximum and `used` is what has been spent, so:

          * maxima present  -> fine, expended or not
          * no maxima, nothing used -> the payload never populated them
          * no maxima, but used > 0 -> the sheet contradicts itself: those
            slots were spent, so they existed

        The second case was reported by an agent (a Cleric 3 with slots_max
        {}). The third turned up while testing the fix on a second character
        and would have been swallowed by a coarser check — a Paladin/Warlock
        with `available 0, used 3`.
        """
        if not rows:
            return
        if any((r.get("available") or 0) > 0 for r in rows):
            return
        spent = {r["level"]: r.get("used") or 0
                 for r in rows if (r.get("used") or 0) > 0}
        if spent:
            detail = ", ".join(f"{n} spent at L{lv}" for lv, n in sorted(spent.items()))
            _lint(W, "slots_inconsistent",
                  f"{label} inconsistent: every row reports a maximum of 0, yet "
                  f"{detail}. Slots that were spent must have existed — treat "
                  f"the maxima as unknown and confirm with the player.",
                  ask="How many spell slots do you have in total, and how many are left?",
                  affects=["spell_slots"])
        elif expectation:
            shape = ", ".join(f"{n}×L{i + 1}" for i, n in enumerate(expectation) if n)
            _lint(W, "slots_missing",
                  f"{label} missing: caster level {caster_level(classes)} "
                  f"requires {shape}, but every row reports 0 with nothing "
                  f"used — a data gap, not an expended caster.",
                  ask=f"Your sheet shows no spell slots, but a caster of your level should have {shape}. How many do you have?",
                  affects=["spell_slots"])

    _slot_gap(_slot_rows(d, "spellSlots"), "spell slots", exp)

    if any(((c.get("definition") or {}).get("name") or "").lower() in PACT_CASTERS
           for c in classes):
        _slot_gap(_slot_rows(d, "pactMagic"), "pact magic slots", None)
        pact = _slot_rows(d, "pactMagic")
        if pact and not any((r.get("available") or 0) > 0 for r in pact) \
                and not any((r.get("used") or 0) > 0 for r in pact):
            _lint(W, "pact_slots_missing",
                  "pact magic slots missing: this character has warlock levels "
                  "but every pactMagic row reports 0 with nothing used.",
                  ask="How many pact magic slots do you have, and how many are left?",
                  affects=["spell_slots"])

    # ---- prepared spells: its own lane, and NOT gated on slots existing.
    #
    # Previously this only fired when slots were present, so a character with
    # missing slots got neither warning — the two failures hid each other.
    if spell and not prepared:
        _lint(W, "no_prepared_spells",
              "no prepared leveled spells visible — cantrips only. This may be "
              "true, or the sheet may not have a prepared list set.",
              ask="Which leveled spells do you have prepared today?",
              affects=["prepared_spells"])

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
    shaped = {
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
                 "possibly_affects": blast(pat)[0],
                 "note": blast(pat)[1],
                 "not_applied": True,
                 "text": W.get("unhandled_text", {}).get(pat)}
                for pat in W["unhandled_modifiers"]],
            # NB: this answers only "which families did the UNSUPPORTED content
            # not touch". It is deliberately blind to lint, so a family can be
            # listed here and still be in trust.ask_player — Shalia's AC is
            # exactly that: no unsupported modifier reaches it, but her armour
            # is not flagged equipped. `trust` is the authoritative routing;
            # this field is an input to it, not a verdict.
            "verified_clean_note": ("families untouched by UNSUPPORTED content only — "
                                    "this ignores lint. Use `trust` for routing."),
            "verified_clean": sorted(
                set(ALL_FAMILIES)
                - {a for p in W["unhandled_modifiers"] for a in blast(p)[0]}),
        },
        "lint": W["lint"],
    }
    # The trust map is a re-shaping of what is already above, put where an
    # agent will actually look for it. See trust_map() for why it is not
    # merely a convenience.
    shaped["trust"] = trust_map(shaped["lint"], shaped["unhandled"])
    return shaped


STATE_FIELDS = {"removedHitPoints": "hp.current", "temporaryHitPoints": "hp.temp",
                "inspiration": "heroic_inspiration"}


def render_brief(r):
    """Deterministic short output, for chat-sized surfaces.

    From live agent UXR: *"Full JSON is right for machines, but humans in chat
    need… Agents can summarize, but deterministic short output is better."*
    Correct — a model-written summary can drift between runs, and this cannot.
    """
    ident = r.get("identity") or {}
    t = r.get("trust") or {}
    who = ident.get("name") or "character"
    cls = ", ".join(ident.get("classes") or []) or "?"
    lines = [f"{who} — {cls}"]

    combat = r.get("combat") or {}
    ask = set((t.get("ask_player") or {})) | set((t.get("unsupported") or {}))

    def mark(family, text):
        """Headline numbers are sticky under turn pressure.

        From live agent UXR: *"`AC 12` appears in the headline, then `ASK: ac`
        below. That's okay, but I'd prefer `AC 12 (confirm)`… under turn
        pressure, headline numbers are sticky."* Right — a reader takes the
        first number and stops, so the doubt has to travel with it.
        """
        return f"{text} (confirm)" if family in ask else text

    bits = []
    ac = (combat.get("ac") or {}).get("value")
    hp = combat.get("hp") or {}
    if ac is not None:
        bits.append(mark("ac", f"AC {ac}"))
    if hp.get("max") is not None:
        bits.append(mark("hp", f"HP {hp.get('current', hp['max'])}/{hp['max']}"))
    init = (combat.get("initiative") or {}).get("bonus")
    if init is not None:
        bits.append(mark("initiative", f"init {init:+d}"))
    if bits:
        lines.append("  " + " · ".join(bits))

    if t.get("trusted"):
        lines.append("  trusted: " + ", ".join(t["trusted"]))
    if t.get("ask_player"):
        lines.append("  ASK: " + ", ".join(sorted(t["ask_player"])))
    if t.get("unsupported"):
        lines.append("  UNSUPPORTED: " + ", ".join(
            f"{k} ({', '.join(v)})" for k, v in sorted(t["unsupported"].items())))
    for a in (t.get("asks") or []):
        lines.append(f"    ? {a['ask']}")
    return "\n".join(lines)


def render_report_brief(r):
    """Caveat-only summary, chat-sized.

    From live agent UXR: *"`report --brief` returns full JSON. Either reject it
    clearly or make report brief produce the caveat-only Discord summary.
    Silent ignore is the rough edge."* Silently ignoring a flag is the worst of
    the three options — the caller believes it worked.
    """
    t = r.get("trust") or {}
    ident = r.get("identity") or {}
    lines = [f"{ident.get('name') or 'character'} — what to resolve before play"]
    if not t.get("ask_player") and not t.get("unsupported"):
        lines.append("  nothing outstanding — everything derived clean")
        return "\n".join(lines)
    for fam, pats in sorted((t.get("unsupported") or {}).items()):
        lines.append(f"  UNSUPPORTED {fam}: {', '.join(pats)} — say what is "
                     "missing rather than stating a value")
    for a in (t.get("asks") or []):
        fams = ", ".join(a.get("affects") or []) or "?"
        lines.append(f"  ASK ({fams}): {a['ask']}")
    return "\n".join(lines)


def intake(ref, for_dm=False):
    """One pre-session packet: what is settled, and what must be asked first.

    From live agent UXR: *"one pre-session packet for the DM/player to settle
    before dice."* Deliberately a thin composition of the seat pack and the
    trust map rather than a new subsystem — everything here already exists.
    """
    pack = seatpack(ref, for_dm=for_dm)
    r = derive(ref)
    t = r.get("trust") or {}
    return {
        "identity": pack.get("identity"),
        "settled": {fam: True for fam in t.get("trusted", [])},
        "resolve_before_dice": t.get("asks", []),
        "unsupported": t.get("unsupported", {}),
        "player_authority": ["current hp", "expended slots", "conditions",
                             "concentration", "inspiration", "worn/carried kit"],
        "baseline_snapshot_hint": (
            "save this derive output as intake.json, then use "
            "`charactercheck diff <ref> --baseline intake.json` mid-session to "
            "see what the player changed"),
        "seatpack": pack,
    }


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

def quiz(ref):
    """The settlement answer key (protocol S3c): questions the GM asks OUT
    LOUD at a ledger-flush boundary, each with the silently-held expected
    value where derivation has authority — and expect=None, authority=player
    where only the player tracks the truth (the engine NEVER estimates live
    state)."""
    d = derive(ref)
    prof = d.get("combat") or {}
    qs = []
    ac = prof.get("ac") or {}
    if ac.get("value") is not None:
        qs.append({"ask": "Remind me your AC?", "expect": ac["value"],
                   "source": ac.get("provenance")})
    hp = prof.get("hp") or {}
    if hp.get("max") is not None:
        qs.append({"ask": "What's your HP maximum?", "expect": hp["max"],
                   "source": hp.get("provenance")})
    qs.append({"ask": "Where's your HP right now?", "expect": None,
               "authority": "player",
               "note": "live state — cross-check with `diff` against the intake snapshot if declared"})
    sp = d.get("spellcasting") or {}
    if sp.get("slots_max"):
        qs.append({"ask": "How many spell slots per level do you have TOTAL?",
                   "expect": sp["slots_max"], "source": "derived"})
        qs.append({"ask": "Which slots have you expended?", "expect": None,
                   "authority": "player",
                   "note": "live state — engine ledger + diff are the reality check"})
    inv = d.get("inventory") or {}
    if inv.get("attuned") is not None:
        qs.append({"ask": "What are you attuned to?", "expect": inv["attuned"],
                   "source": "derived (isAttuned flags)"})
    unh = (d.get("unhandled") or {}).get("items") or []
    return {"questions": qs,
            "caveat": ("unhandled patterns present — expected values in their "
                       "blast radius are unverified: "
                       + ", ".join(i["pattern"] for i in unh)) if unh else None,
            "contract": "answer key is SILENT — grade privately, remind diplomatically (S3c)"}

VISION_FEATURES = {
    # feature/invocation name -> (range_ft or None if payload-dependent, note)
    "Devil's Sight": (120, "see normally in magical and nonmagical darkness"),
    "Superior Darkvision": (120, "darkvision 120 ft"),
    "Blindsight": (None, "perceive without sight; range per feature text"),
    "Truesight": (None, "true seeing; range per feature text"),
}


def vision(d):
    """Every sight-in-darkness capability on the sheet, with provenance.
    Reported, never adjudicated - lighting conditions are the DM's lane."""
    import re as _re
    out = []
    # 1) sense modifiers (species darkvision etc.)
    for src, ml in (d.get("modifiers") or {}).items():
        for m in ml or []:
            if m and (m.get("subType") or "") == "darkvision":
                out.append({"feature": "Darkvision",
                            "range_ft": m.get("value"),
                            "provenance": f"modifier ({src})"})
    # 2) named vision features anywhere in the payload (options, class
    #    features, feats). Name-keyed walk; provenance = the path context.
    def walk(o, path):
        if isinstance(o, dict):
            n = o.get("name")
            if isinstance(n, str):
                norm = n.strip().replace("\u2019", "'")
                for feat, (rng, note) in VISION_FEATURES.items():
                    if norm == feat:
                        snippet = (o.get("snippet") or o.get("description") or "")
                        g = _re.search(r"(\d+)\s*f", snippet)
                        out.append({"feature": feat,
                                    "range_ft": int(g.group(1)) if g else rng,
                                    "note": note, "provenance": path})
            for k, v in o.items():
                if isinstance(v, (dict, list)) and k != "definition" or k == "definition":
                    walk(v, f"{path}.{k}" if path else k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, path)
    walk(d, "")
    # dedupe by (feature, range)
    seen, uniq = set(), []
    for v in out:
        k = (v["feature"], v.get("range_ft"))
        if k not in seen:
            seen.add(k)
            uniq.append(v)
    return uniq


def seatpack(ref, for_dm=False):
    """Everything a seat needs at session start (spec: Ash, 2026-07-27).
    Assembly with provenance - no new derivation, no invented persona."""
    d = fetch(ref)
    r = derive(ref)
    sk = r.get("skills") or {}
    passives = {f"passive_{k}": 10 + v["bonus"]
                for k, v in sk.items()
                if k in ("perception", "insight", "investigation") and "bonus" in v}
    traits = d.get("traits") or (d.get("data") or {}).get("traits") or {}
    persona = {k: v for k, v in traits.items() if v}
    pack = {
        "identity": r.get("identity"),
        "abilities": r.get("abilities"),
        "saves": r.get("saves"),
        "skills": sk,
        "passives": passives,
        "combat": r.get("combat"),
        "spellcasting": r.get("spellcasting"),
        "resources": r.get("resources"),
        "inventory": r.get("inventory"),
        "vision": vision(d),
        "persona": {
            "from_sheet_verbatim": persona,
            "not_derivable": ["fears beyond stated flaws", "motives beyond stated ideals/bonds",
                              "relationships not on the sheet", "taboos",
                              "behaviour under pressure"],
        },
        "unhandled": r.get("unhandled"),
        "lint": r.get("lint"),
    }
    if for_dm:
        hp = ((pack.get("combat") or {}).get("hp") or {})
        if "current" in hp:
            hp["current"] = "player-authority"
        sp = pack.get("spellcasting") or {}
        if sp and sp.get("slots_current") is not None:
            sp["slots_current"] = "player-authority"
    return pack
