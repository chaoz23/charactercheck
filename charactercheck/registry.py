"""Fail-closed modifier and character-value coverage registry.

Recognition is generated from handler declarations. A record that has no
handler, an unsupported restriction, invalid data, or unmet activation evidence
never enters the arithmetic modifier list.
"""

from dataclasses import dataclass
from collections import Counter
import hashlib
import json
import math

from . import ddb_registry


ABILITIES = ("strength", "dexterity", "constitution",
             "intelligence", "wisdom", "charisma")
SKILLS = ("acrobatics", "animal-handling", "arcana", "athletics",
          "deception", "history", "insight", "intimidation",
          "investigation", "medicine", "nature", "perception",
          "performance", "persuasion", "religion", "sleight-of-hand",
          "stealth", "survival")
SAVES = tuple(f"{ability}-saving-throws" for ability in ABILITIES)
EQUIPMENT_PROFICIENCIES = (
    "light-armor", "medium-armor", "heavy-armor", "shields",
    "simple-weapons", "martial-weapons",
)
TOOL_PROFICIENCIES = (
    "alchemists-supplies", "brewers-supplies", "calligraphers-supplies",
    "carpenters-tools", "cartographers-tools", "cobblers-tools",
    "cooks-utensils", "disguise-kit", "forgery-kit", "glassblowers-tools",
    "herbalism-kit", "jewelers-tools", "leatherworkers-tools",
    "masons-tools", "navigators-tools", "painters-supplies", "poisoners-kit",
    "potters-tools", "smiths-tools", "thieves-tools", "tinkers-tools",
    "weavers-tools", "woodcarvers-tools",
)


@dataclass(frozen=True)
class HandlerSpec:
    handler_id: str
    type_name: str
    subtype: str
    affects: tuple
    mode: str = "apply"
    requires_number: bool = False
    restrictions_supported: bool = False
    rules_profiles: tuple = ("srd-5.2.1-partial",)


def _spec(handler_id, type_name, subtype, affects, **kwargs):
    return HandlerSpec(handler_id, type_name, subtype, tuple(affects), **kwargs)


HANDLERS = []
for ability in ABILITIES:
    HANDLERS.append(_spec(f"ability.bonus.{ability}", "bonus",
                          f"{ability}-score", ["abilities"],
                          requires_number=True))
    HANDLERS.append(_spec(f"ability.set.{ability}", "set",
                          f"{ability}-score", ["abilities"],
                          requires_number=True))
    HANDLERS.append(_spec(f"weapon.replace.{ability}",
                          "replace-weapon-ability", f"{ability}-score",
                          ["attacks", "weapons"]))
for skill in SKILLS:
    HANDLERS.append(_spec(f"skill.bonus.{skill}", "bonus", skill,
                          ["skills"], requires_number=True))
    HANDLERS.append(_spec(f"skill.expertise.{skill}", "expertise", skill,
                          ["skills"]))
    HANDLERS.append(_spec(f"skill.half.{skill}", "half-proficiency", skill,
                          ["skills"]))
for proficiency in (*SKILLS, *SAVES, *EQUIPMENT_PROFICIENCIES,
                    *TOOL_PROFICIENCIES):
    HANDLERS.append(_spec(f"proficiency.{proficiency}", "proficiency",
                          proficiency, ["skills", "saves", "attacks",
                                        "weapons"]))
HANDLERS.extend((
    _spec("initiative.bonus", "bonus", "initiative", ["initiative"],
          requires_number=True),
    _spec("hp.flat", "bonus", "hit-points", ["hp"], requires_number=True),
    _spec("hp.per-level", "bonus", "hit-points-per-level", ["hp"],
          requires_number=True),
    _spec("ac.unconditional", "bonus", "armor-class", ["ac"],
          requires_number=True),
    _spec("ac.unarmored", "set", "unarmored-armor-class", ["ac"],
          requires_number=True),
    _spec("sense.darkvision", "sense", "darkvision", ["senses"],
          requires_number=True, mode="pass_through"),
))

HANDLER_BY_PATTERN = {(spec.type_name, spec.subtype): spec for spec in HANDLERS}
if len(HANDLER_BY_PATTERN) != len(HANDLERS):  # import-time invariant
    raise RuntimeError("duplicate modifier handler pattern")

LANGUAGE_HANDLER = _spec("language.declaration", "language", "*",
                         ["languages"], mode="pass_through")


CHARACTER_VALUE_HANDLERS = {
    1: ("ac.override", ("ac",)),
    2: ("ac.bonus", ("ac",)),
    3: ("ac.adjustment", ("ac",)),
    8: ("inventory.custom-name", ("inventory",)),
    9: ("inventory.custom-note", ("inventory",)),
    24: ("skill.misc-bonus", ("skills",)),
    25: ("skill.magic-bonus", ("skills",)),
    26: ("skill.proficiency", ("skills",)),
    27: ("skill.ability", ("skills",)),
    28: ("weapon.designation", ("attacks", "weapons")),
    29: ("weapon.designation", ("attacks", "weapons")),
    39: ("ability.bonus", ("abilities",)),
    40: ("ability.bonus", ("abilities",)),
    41: ("ability.override", ("abilities",)),
}
CHARACTER_VALUE_SKILL_IDS = frozenset(
    (3, 11, 6, 2, 16, 7, 12, 17, 8, 13, 9, 14, 18, 19, 10, 4, 5, 15))
SUPPORTED_MODIFIER_BUCKETS = frozenset(
    ("race", "class", "background", "feat", "condition", "item"))
MAX_MECHANICAL_MAGNITUDE = 1_000_000


# Fixed-code adapter/evaluator gaps. Reasons and blast radii are code-owned;
# player/source text never becomes a pattern or reason.
ITEM_SEMANTIC_GAPS = {
    "armor_type": {
        "affects": ("ac",),
        "reason": ("armor discriminator/base value is missing, unknown, or "
                   "unsupported; the item was excluded from AC arithmetic"),
    },
    "attack_type": {
        "affects": ("attacks", "weapons"),
        "reason": ("attack range discriminator is missing or unknown; the "
                   "item was not defaulted to melee or ranged"),
    },
    "damage_dice": {
        "affects": ("attacks", "weapons"),
        "reason": ("base damage dice are malformed, inconsistent, or outside "
                   "the pinned adapter registry"),
    },
    "damage_type": {
        "affects": ("attacks", "weapons"),
        "reason": ("weapon damage type is missing or outside the pinned "
                   "adapter registry"),
    },
    "additional_damage_semantics": {
        "affects": ("attacks", "weapons"),
        "reason": ("additional base-damage fields are present but this "
                   "evaluator does not implement their semantics"),
    },
    "weapon_property": {
        "affects": ("attacks", "weapons"),
        "reason": ("a weapon property identifier/name is missing, mismatched, "
                   "unknown, or not fully interpreted"),
    },
    "weapon_proficiency": {
        "affects": ("attacks", "weapons"),
        "reason": ("this evaluator does not yet prove weapon proficiency and "
                   "hand/held state before adding proficiency bonus"),
    },
}
ITEM_SEMANTIC_GAP_CODES = frozenset(ITEM_SEMANTIC_GAPS)


def _inventory_activation(character):
    """Return item-id activation evidence without trusting aggregate buckets."""
    custom_names = {
        str(record["normalized"]["valueId"]): record["normalized"]["value"]
        for record in classify_character_values(character)
        if record["state"] == "applied"
        and record["normalized"].get("typeId") == 8
    }
    by_id = {str(item.get("id")): item
             for item in character.get("inventory") or []}
    character_id = str(character.get("id"))

    def carried(item):
        current = item
        seen = set()
        while current is not None:
            item_id = str(current.get("id"))
            if item_id in seen:
                return None
            seen.add(item_id)
            label = str(custom_names.get(item_id) or "").lower()
            if "stash" in label or "left @" in label:
                return False
            parent = current.get("containerEntityId")
            if parent is None or str(parent) == character_id:
                return True
            current = by_id.get(str(parent))
        # A non-null parent outside the inventory graph is neither affirmative
        # carried evidence nor affirmative stashed evidence.
        return None

    activation = {}
    for item in character.get("inventory") or []:
        definition = item.get("definition") or {}
        carried_evidence = carried(item)
        can_equip = definition.get("canEquip")
        can_attune = definition.get("canAttune")
        consumable = definition.get("isConsumable")
        equipped = item.get("equipped")
        attuned = item.get("isAttuned")
        quantity = item.get("quantity")
        quantity_positive = (quantity is None or (
            isinstance(quantity, int) and not isinstance(quantity, bool)
            and quantity > 0))
        evidence = {
            "carried": carried_evidence,
            "quantity_positive": quantity_positive,
            "equipped": equipped if isinstance(equipped, bool) else None,
            "attuned": attuned if isinstance(attuned, bool) else None,
            "requires_equipped": can_equip if isinstance(can_equip, bool) else None,
            "requires_attuned": can_attune if isinstance(can_attune, bool) else None,
            "consumable": consumable if isinstance(consumable, bool) else None,
        }
        incomplete = (carried_evidence is None
                      or evidence["requires_equipped"] is None
                      or evidence["requires_attuned"] is None
                      or evidence["consumable"] is None
                      or (evidence["requires_equipped"] is True
                          and evidence["equipped"] is None)
                      or (evidence["requires_attuned"] is True
                          and evidence["attuned"] is None))
        active = (not incomplete and carried_evidence is True
                  and quantity_positive
                  and (evidence["requires_equipped"] is False
                       or evidence["equipped"] is True)
                  and (evidence["requires_attuned"] is False
                       or evidence["attuned"] is True)
                  and evidence["consumable"] is False)
        state = "unknown" if incomplete else ("active" if active else "inactive")
        activation[str(item.get("id"))] = (state, evidence)
    return activation


def _component_evidence(character):
    """Index source component ids, activation, and granting class levels."""
    known, active, class_levels = set(), {}, {}

    def register(definition, *, class_level=None, wrapper=None):
        definition = definition or {}
        component_id = definition.get("id")
        if component_id is None:
            return
        known.add(component_id)
        required = ((wrapper or {}).get("requiredLevel")
                    if (wrapper or {}).get("requiredLevel") is not None
                    else definition.get("requiredLevel"))
        enabled = (class_level is None or not isinstance(required, int)
                   or required <= class_level)
        active[component_id] = active.get(component_id, False) or enabled
        if enabled and class_level is not None:
            class_levels.setdefault(component_id, set()).add(class_level)

    race = character.get("race") or {}
    for trait in race.get("racialTraits") or []:
        register(trait.get("definition") or trait, wrapper=trait)
    background = character.get("background") or {}
    register(background.get("definition"))
    for feat in character.get("feats") or []:
        register(feat.get("definition") or feat, wrapper=feat)
    for cls in character.get("classes") or []:
        class_level = cls.get("level") or 0
        register(cls.get("definition"), class_level=class_level)
        subclass = cls.get("subclassDefinition") or {}
        register(subclass, class_level=class_level)
        feature_groups = (
            cls.get("classFeatures") or [],
            (cls.get("definition") or {}).get("classFeatures") or [],
            subclass.get("classFeatures") or [],
        )
        for features in feature_groups:
            for feature in features:
                register(feature.get("definition") or feature,
                         class_level=class_level, wrapper=feature)
    return known, active, class_levels


def handler_for(modifier):
    mtype = modifier.get("type") or ""
    subtype = modifier.get("subType") or ""
    spec = HANDLER_BY_PATTERN.get((mtype, subtype))
    if spec:
        return spec
    if mtype == "language" and isinstance(subtype, str) and subtype:
        return LANGUAGE_HANDLER
    return None


def _finding_id(record):
    material = {key: record.get(key) for key in (
        "pattern", "source_bucket", "component_id", "item_id", "state",
        "handler_id", "reason")}
    body = json.dumps(material, sort_keys=True, separators=(",", ":"),
                      default=str).encode("utf-8")
    return "finding:" + hashlib.sha256(body).hexdigest()[:16]


def _has_affirmative_weapon_shape(definition):
    """Return whether the filtered definition is unambiguously a weapon."""
    damage = definition.get("damage") or {}
    dice = damage.get("diceString")
    attack_type = definition.get("attackType")
    if (not isinstance(dice, str)
            or type(attack_type) is not int
            or attack_type not in ddb_registry.RANGE_TYPES):
        return False
    count, separator, sides = dice.partition("d")
    if not separator or not count.isdigit() or not sides.isdigit():
        return False
    # The adapter reconstructs canonical dice strings from validated integers.
    # Rechecking that shape here keeps this classifier safe for direct callers.
    if (len(count) > 3 or len(sides) > 4
            or count.startswith("0") or sides.startswith("0")):
        return False
    return (1 <= int(count) <= 100
            and int(sides) in ddb_registry.DICE_VALUES)


def classify_item_semantics(character):
    """Convert fixed adapter/evaluator gap codes into trust ledger records.

    Unknown source values have already been removed or canonicalized by the
    adapter. Only fixed code-owned patterns and reasons cross this boundary.
    """
    ledger = []
    for item in character.get("inventory") or []:
        definition = item.get("definition") or {}
        codes = set(definition.get("_semanticGaps") or [])
        damage = definition.get("damage") or {}
        if damage.get("diceString"):
            # Until COMBAT-001 is implemented, never label a calculated attack
            # line trusted merely because its shape was parseable.
            codes.add("weapon_proficiency")
            handled_properties = {"Finesse"}
            if any((prop.get("name") not in handled_properties)
                   for prop in definition.get("properties") or []):
                codes.add("weapon_property")
        for original_code in sorted(codes):
            code = original_code
            spec = ITEM_SEMANTIC_GAPS.get(code)
            if spec is None:
                # Validation should make this unreachable. Retain a global
                # fixed-code finding if an internal caller bypassed it.
                code = "unknown"
                spec = {
                    "affects": ("unknown",),
                    "reason": "unknown internal item semantic-gap code",
                }
            record = {
                "pattern": f"item-semantic:{code}",
                "source_bucket": "item",
                "component_id": definition.get("id"),
                "item_id": item.get("id"),
                "restriction": None,
                "affects": list(spec["affects"]),
                "handler_id": None,
                "state": "unsupported",
                "reason": spec["reason"],
            }
            record["finding_id"] = _finding_id(record)
            ledger.append(record)
    return ledger


def classify_non_item_semantics(character):
    """Fail closed for fixed semantic gaps without a classified blast radius.

    The current adapter does not yet have a complete dependency graph for
    class, race, feat, action, spell, or nested inventory definitions. One
    retained fixed marker therefore has unknown global scope. Root inventory
    definition markers are excluded because ``classify_item_semantics`` gives
    them a fixed, scoped blast radius. This is deliberately conservative and
    survives replay of a naked snapshot character without envelope coverage.
    """
    stack = [value for key, value in character.items() if key != "inventory"]
    found = False
    for item in character.get("inventory") or []:
        definition = item.get("definition") or {}
        root_gaps = set(definition.get("_semanticGaps") or [])
        if ("weapon_property" in root_gaps
                and not _has_affirmative_weapon_shape(definition)):
            # A weapon-property marker has a narrow attacks/weapons blast
            # radius only when the item is affirmatively a weapon. On armor,
            # containers, or ambiguous shapes its dependency scope is unknown.
            found = True
        # Traverse the complete item, but skip only the marker on its root
        # definition. Descendant definitions do not inherit the root item's
        # scoped semantics and must fail closed globally until classified.
        stack.extend(value for key, value in item.items()
                     if key != "definition")
        stack.extend(value for key, value in definition.items()
                     if key != "_semanticGaps")
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if value.get("_semanticGaps"):
                found = True
                break
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    if not found:
        return []
    record = {
        "pattern": "source-semantic:unscoped-definition",
        "source_bucket": "source",
        "component_id": None,
        "item_id": None,
        "restriction": None,
        "affects": ["unknown"],
        "handler_id": None,
        "state": "unknown",
        "reason": ("a definition outside the scoped inventory-item root "
                   "retained a fixed semantic gap; its dependency scope is "
                   "not yet classified"),
    }
    record["finding_id"] = _finding_id(record)
    return [record]


def _modifier_signature(modifier):
    """Mechanical identity used only to match aggregate item duplicates."""
    material = {key: modifier.get(key) for key in (
        "type", "subType", "value", "statId", "componentId", "isGranted",
        "restriction",
    )}
    return json.dumps(material, sort_keys=True, separators=(",", ":"),
                      default=str)


def _selected_choice_evidence(character, bucket, modifier):
    """Return minimal evidence that a builder-choice modifier is selected.

    DDB choice modifiers can retain ``isGranted: false`` even while selected.
    The stable join observed in controlled differentials is choice id
    ``2-<modifier id>`` plus a non-null optionValue. Component identifiers,
    when both sides provide them, must also agree.
    """
    modifier_id = modifier.get("id")
    if modifier_id is None:
        return None
    wanted = f"2-{modifier_id}"
    for choice in (character.get("choices") or {}).get(bucket) or []:
        if str(choice.get("id")) != wanted or choice.get("optionValue") is None:
            continue
        if (choice.get("componentId") is not None
                and modifier.get("componentId") is not None
                and choice.get("componentId") != modifier.get("componentId")):
            continue
        if (choice.get("componentTypeId") is not None
                and modifier.get("componentTypeId") is not None
                and choice.get("componentTypeId") != modifier.get("componentTypeId")):
            continue
        return {
            "kind": "selected_builder_choice",
            "choice_id": wanted,
            "option_selected": True,
        }
    return None


def classify_modifiers(character):
    """Return ``ledger`` and the only modifiers arithmetic may consume."""
    inventory_activation = _inventory_activation(character)
    inventory_entries = []
    concrete_item_signatures = Counter()
    for item in character.get("inventory") or []:
        definition = item.get("definition") or {}
        activation_state, evidence = inventory_activation[str(item.get("id"))]
        for modifier in definition.get("grantedModifiers") or []:
            concrete_item_signatures[_modifier_signature(modifier)] += 1
            inventory_entries.append((
                "item", modifier,
                {"id": item.get("id"),
                 "name": definition.get("name"),
                 "active": activation_state == "active",
                 "activation_state": activation_state,
                 "activation_evidence": evidence},
            ))

    entries = []
    for bucket, modifiers in (character.get("modifiers") or {}).items():
        for modifier in modifiers or []:
            # DDB's aggregate `modifiers.item` bucket has no per-item
            # equip/attunement evidence. A byte-for-byte mechanical duplicate
            # of a concrete inventory grant is an inactive summary row; an
            # unmatched aggregate row is unsupported, never presumed inactive.
            if bucket == "item":
                signature = _modifier_signature(modifier)
                matched = concrete_item_signatures[signature] > 0
                if matched:
                    # Aggregate rows and concrete grants must correspond
                    # one-for-one. Membership-only matching lets one concrete
                    # effect hide arbitrarily many unsupported aggregate rows.
                    concrete_item_signatures[signature] -= 1
                item_context = {
                    "id": None, "name": None, "active": False,
                    "activation_state": "inactive" if matched else "unknown",
                    "aggregate": True, "matched_concrete": matched,
                }
            else:
                item_context = None
            entries.append((bucket, modifier, item_context))
    entries.extend(inventory_entries)

    known_components, feature_activation, feature_class_levels = (
        _component_evidence(character))
    ledger, applied = [], []
    for bucket, modifier, item in entries:
        mtype = modifier.get("type") or ""
        subtype = modifier.get("subType") or ""
        pattern = f"{mtype}:{subtype}"
        spec = handler_for(modifier)
        record = {
            "pattern": pattern,
            "source_bucket": bucket,
            "component_id": modifier.get("componentId"),
            "component_name": (modifier.get("friendlySubtypeName")
                               or modifier.get("friendlyTypeName")),
            "item_id": (item or {}).get("id"),
            "item_name": (item or {}).get("name"),
            "restriction": (modifier.get("restriction") or "")[:280] or None,
            "affects": list(spec.affects) if spec else ["unknown"],
            "handler_id": spec.handler_id if spec else None,
            "rules_profile": "srd-5.2.1-partial",
            "activation_evidence": (item or {}).get("activation_evidence"),
        }
        component_id = modifier.get("componentId")
        choice_evidence = _selected_choice_evidence(
            character, bucket, modifier)
        if choice_evidence:
            record["activation_evidence"] = choice_evidence
        if modifier.get("isGranted") is False and not choice_evidence:
            record.update(state="inactive",
                          reason="no selected builder-choice evidence")
        elif modifier.get("isGranted") is not True and not choice_evidence:
            record.update(state="unsupported",
                          reason="granting evidence is missing or malformed")
        elif bucket not in SUPPORTED_MODIFIER_BUCKETS:
            record.update(state="unsupported",
                          reason="modifier source bucket is not supported")
        elif component_id is not None and item is None \
                and component_id not in known_components:
            record.update(state="unsupported",
                          reason="granting source component could not be resolved")
        elif feature_activation.get(component_id) is False:
            record.update(state="inactive",
                          reason="granting feature is above the class level")
        elif item is not None and item.get("aggregate") \
                and item.get("matched_concrete"):
            record.update(
                state="inactive",
                reason="aggregate item record is duplicated by concrete item evidence")
        elif item is not None and item.get("activation_state") == "unknown":
            record.update(state="unsupported",
                          reason="item possession evidence is incomplete")
        elif item is not None and not item["active"]:
            record.update(state="inactive", reason="activation evidence is false")
        elif not spec:
            record.update(state="unsupported", reason="no registered handler")
        elif record["restriction"] and not spec.restrictions_supported:
            record.update(state="unsupported",
                          reason="restriction semantics are not supported")
        elif spec.requires_number and (
                not isinstance(modifier.get("value"), int)
                or isinstance(modifier.get("value"), bool)
                or abs(modifier.get("value")) > MAX_MECHANICAL_MAGNITUDE):
            record.update(state="invalid",
                          reason="handler requires a finite integer value")
        elif spec.handler_id == "hp.per-level" and (
                component_id not in feature_class_levels
                or len(feature_class_levels[component_id]) != 1):
            record.update(state="unsupported",
                          reason="granting class level could not be resolved unambiguously")
        else:
            record.update(state="applied" if spec.mode == "apply" else "pass_through",
                          reason=None)
            normalized = dict(modifier)
            normalized["_handler_id"] = spec.handler_id
            normalized["_source_bucket"] = bucket
            if (spec.handler_id == "hp.per-level"
                    and component_id in feature_class_levels):
                normalized["_granting_class_level"] = next(iter(
                    feature_class_levels[component_id]))
            applied.append(normalized)
        record["finding_id"] = _finding_id(record)
        ledger.append(record)
    return {"ledger": ledger, "applied": applied}


def classify_character_values(character):
    """Classify character-value records before the engine may consume them.

    The returned list remains the public compatibility shape. Each applied
    row additionally carries a normalized copy; callers must not read the raw
    ``characterValues`` collection after classification.
    """
    ledger = []
    inventory_ids = {str(item.get("id"))
                     for item in character.get("inventory") or []}
    weapon_ids = {
        str(item.get("id"))
        for item in character.get("inventory") or []
        if (item.get("definition") or {}).get("attackType") in (1, 2)
        and isinstance(((item.get("definition") or {}).get("damage") or {}).get(
            "diceString"), str)
    }
    for index, value in enumerate(character.get("characterValues") or []):
        type_id = value.get("typeId")
        handler = (CHARACTER_VALUE_HANDLERS.get(type_id)
                   if isinstance(type_id, int) and not isinstance(type_id, bool)
                   else None)
        record = {
            "index": index,
            "pattern": f"characterValues typeId {type_id}",
            "type_id": type_id,
            "value_id": value.get("valueId"),
            "handler_id": handler[0] if handler else None,
            "affects": list(handler[1]) if handler else ["unknown"],
            "state": "unsupported",
            "reason": "no registered characterValue handler",
        }
        normalized = dict(value)
        if handler:
            target_resolved = True
            if type_id in (8, 9):
                valid = (isinstance(value.get("valueId"), (int, str))
                         and not isinstance(value.get("valueId"), bool)
                         and isinstance(value.get("value"), str))
                if valid:
                    target_resolved = str(value.get("valueId")) in inventory_ids
            elif type_id in (28, 29):
                valid = (isinstance(value.get("valueId"), (int, str))
                         and not isinstance(value.get("valueId"), bool)
                         and (isinstance(value.get("value"), bool)
                              or value.get("value") in ("True", "False")))
                if valid:
                    normalized["value"] = (value.get("value") is True
                                           or value.get("value") == "True")
                    target_resolved = str(value.get("valueId")) in weapon_ids
            else:
                raw = value.get("value")
                try:
                    numeric = int(raw)
                    valid = (not isinstance(raw, bool)
                             and isinstance(raw, (int, float, str))
                             and str(raw).strip() not in ("", "+", "-")
                             and float(raw).is_integer()
                             and math.isfinite(float(raw)))
                except (TypeError, ValueError, OverflowError):
                    valid = False
                if valid:
                    normalized["value"] = numeric
                    valid = abs(numeric) <= MAX_MECHANICAL_MAGNITUDE
                if type_id in (24, 25, 26, 27, 39, 40, 41):
                    try:
                        normalized["valueId"] = int(value.get("valueId"))
                    except (TypeError, ValueError, OverflowError):
                        valid = False
                    if isinstance(value.get("valueId"), bool):
                        valid = False
                if valid and type_id in (24, 25, 26, 27):
                    target_resolved = (
                        normalized.get("valueId") in CHARACTER_VALUE_SKILL_IDS)
                elif valid and type_id in (39, 40, 41):
                    target_resolved = normalized.get("valueId") in range(1, 7)
                if valid and type_id == 26:
                    valid = normalized.get("value") in range(1, 5)
                elif valid and type_id == 27:
                    valid = normalized.get("value") in range(1, 7)
                elif valid and type_id == 41:
                    # Zero is used by some producers as an unset sentinel. It
                    # is not a supported ability score override.
                    valid = normalized.get("value") in range(1, 31)
            if valid:
                if target_resolved:
                    record.update(state="applied", reason=None,
                                  normalized=normalized)
                else:
                    record.update(
                        state="unsupported",
                        reason="registered handler target could not be resolved")
            else:
                record.update(state="invalid",
                              reason="registered handler received malformed data")
        record["finding_id"] = _finding_id(record)
        ledger.append(record)

    # A single-valued declaration may not silently win by source order.
    # Additive CharacterValues intentionally do not participate in this pass.
    exclusive_groups = {}
    for record in ledger:
        if record["state"] != "applied":
            continue
        normalized = record["normalized"]
        type_id = normalized.get("typeId")
        target = normalized.get("valueId")
        if type_id == 1:
            key = ("ac.override",)
        elif type_id in (8, 9, 26, 27, 41):
            key = (record["handler_id"], target)
        elif type_id in (28, 29):
            key = ("weapon.designation", target)
        else:
            continue
        exclusive_groups.setdefault(key, []).append(record)
    for records in exclusive_groups.values():
        if len(records) < 2:
            continue
        for record in records:
            record.update(state="unsupported",
                          reason="conflicting duplicate single-value declarations")
            record.pop("normalized", None)
            record["finding_id"] = _finding_id(record)
    return ledger
