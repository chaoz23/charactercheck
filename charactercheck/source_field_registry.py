"""Privacy-safe routing for source fields omitted by the partial DDB adapter.

The registry intentionally records only container paths and canonical output
families. Runtime coverage carries the union of those families, never omitted
field names or values. A field outside these reviewed containers remains
unclassified and therefore fails closed with global unknown scope.
"""

import hashlib
import json


FAMILIES = frozenset({
    "abilities", "ac", "initiative", "hp", "saves", "skills", "attacks",
    "weapons", "speeds", "senses", "defenses", "languages",
    "proficiency_bonus", "spellcasting", "spell_save_dc",
    "spell_attack_bonus", "spell_output", "spell_slots", "prepared_spells",
    "inventory", "resources",
})

ABILITY = frozenset({"abilities"})
CLASS_BUILD = FAMILIES - {"inventory"}
RACE_BUILD = frozenset({
    "abilities", "ac", "initiative", "hp", "saves", "skills", "attacks",
    "weapons", "speeds", "senses", "defenses", "languages",
    "spellcasting", "spell_save_dc", "spell_attack_bonus", "spell_output",
    "prepared_spells", "resources",
})
BACKGROUND_BUILD = frozenset({
    "abilities", "saves", "skills", "languages", "inventory",
    "spellcasting", "spell_output", "prepared_spells", "resources",
})
FEAT_BUILD = FAMILIES - {"inventory"}
ITEM = frozenset({"inventory", "resources"})
ITEM_MECHANICS = frozenset({
    "abilities", "ac", "initiative", "hp", "saves", "skills", "attacks",
    "weapons", "speeds", "senses", "defenses", "languages",
    "spellcasting", "spell_save_dc", "spell_attack_bonus", "spell_output",
    "inventory", "resources",
})
SPELL = frozenset({
    "attacks", "spellcasting", "spell_save_dc", "spell_attack_bonus",
    "spell_output", "spell_slots", "prepared_spells", "resources",
})
ACTION = frozenset({"attacks", "saves", "resources"})

# None means the key remains truly unclassified. An empty set means the key is
# reviewed non-mechanical metadata that may be omitted without changing trust.
TOP_LEVEL = {
    # Builder filters and score-generation method describe how the UI was
    # configured, not additional mechanics beyond the explicit selected
    # character records retained by this adapter.
    "activeSourceCategories": frozenset(),
    "adjustmentXp": frozenset({"resources"}),
    "canEdit": frozenset(),
    "choices": CLASS_BUILD | RACE_BUILD | BACKGROUND_BUILD | FEAT_BUILD | ITEM,
    "choiceDefinitions": CLASS_BUILD | RACE_BUILD | BACKGROUND_BUILD | FEAT_BUILD | ITEM,
    "configuration": frozenset(),
    "creatures": frozenset({"attacks", "defenses", "resources"}),
    "customActions": ACTION,
    "customDefenseAdjustments": frozenset({"ac", "saves", "defenses"}),
    "customProficiencies": frozenset({
        "saves", "skills", "weapons", "languages"}),
    "customSenses": frozenset({"senses"}),
    "customSpeeds": frozenset({"speeds"}),
    "dateModified": frozenset(),
    "features": CLASS_BUILD | RACE_BUILD | FEAT_BUILD,
    "isAssignedToPlayer": frozenset(),
    "lifestyleId": frozenset(),
    "optionalClassFeatures": CLASS_BUILD,
    "optionalOrigins": RACE_BUILD,
    "options": CLASS_BUILD | RACE_BUILD | BACKGROUND_BUILD | FEAT_BUILD | ITEM,
    "providedFrom": frozenset(),
    "raceDefinitionId": frozenset(),
    "raceDefinitionTypeId": frozenset(),
    "status": frozenset(),
    "statusSlug": frozenset(),
}

# Only keys observed in the pinned adapter research are routed. A novel key in
# even a familiar container remains global unknown until reviewed; recognizing
# the parent container alone is not enough evidence to classify arbitrary
# future mechanics.
CLASS_KEYS = frozenset({
    "activation", "affectedFeatureDefinitionKeys", "canCastSpells", "classId",
    "color", "complexity", "creatureRules", "definitionId",
    "displayOrder", "entityID", "entityType", "entityTypeId",
    "equipmentDescription", "featureType",
    "featuresSectionType", "grantedFeats", "hasItemMappings", "hideInBuilder",
    "hideInSheet", "highlights", "iconicGear", "id", "infusionRules",
    "isHomebrew", "isStartingClass", "isSubClassFeature", "knowsAllSpells",
    "levelScale", "levelScales", "limitedUse", "name", "parentClassId",
    "multiClassDescription", "prerequisite", "prerequisites",
    "primaryAbilities", "sourceId", "sources", "spellCastingLearningStyle",
    "spellContainerName", "spellListIds", "spellPrepareType", "spellRules",
    "subclassDefinition", "subclassDefinitionId", "summary", "wealthDice",
})
ITEM_KEYS = frozenset({
    "attunementDescription", "baseArmorName", "baseItemId", "baseTypeId",
    "canBeAddedToInventory", "capacity", "capacityWeight", "categoryId",
    "chargesUsed", "containerDefinitionKey", "containerEntityTypeId", "cost",
    "currency", "definitionId", "definitionKey", "definitionTypeId",
    "displayAsAttack", "entityTypeId", "equippedEntityId",
    "equippedEntityTypeId", "filterType", "fixedDamage", "gearTypeId",
    "groupedId", "isCustomItem", "isHomebrew", "isLegacy", "isMonkWeapon",
    "isPack", "levelInfusionGranted", "limitedUse", "longRange",
    "originDefinitionKey", "originEntityId", "originEntityTypeId", "range",
    "rarity", "sourceId", "sourcePageNumber", "sources", "stackable",
    "stealthCheck", "strengthRequirement", "subType", "tags", "type",
    "version", "weaponBehaviors", "weightMultiplier",
})
RACE_KEYS = frozenset({
    "activation", "affectedFeatureDefinitionKeys", "baseName", "baseRaceId",
    "baseRaceName", "baseRaceTypeId", "categories", "creatureRules",
    "creatureTypeId", "definitionKey", "displayConfiguration", "displayOrder",
    "encumbered", "entityID", "entityRaceId", "entityRaceTypeId",
    "entityType", "entityTypeId", "featIds", "featureType", "groupIds",
    "heavilyEncumbered", "hideInBuilder", "hideInSheet", "hideOnDetailsPage",
    "highlights", "isCalledOut", "isHomebrew", "isLegacy", "isSubRace",
    "override", "pushDragLift", "sourceId", "sourcePageNumber", "sources",
    "speciesGroupId", "spellListIds", "subRaceShortName", "supportsSubrace",
    "type",
})
BACKGROUND_KEYS = frozenset({
    "bonds", "contractsDescription", "customBackground", "definitionId",
    "entityTypeId", "equipmentDescription", "featList", "featureDescription",
    "featureIsFeat", "flaws", "grantedFeats", "hasCustomBackground", "ideals",
    "isHomebrew",
    "languagesDescription", "personalityTraits", "primaryAbilities",
    "skillProficienciesDescription", "sourceId", "sources", "spellListIds",
    "spellsPostDescription", "spellsPreDescription",
    "suggestedCharacteristicsDescription", "suggestedLanguages",
    "suggestedProficiencies", "toolProficienciesDescription",
})
SPELL_KEYS = frozenset({
    "activation", "additionalDescription", "asPartOfWeaponAttack",
    "atHigherLevels", "atWillLimitedUseLevel", "baseLevelAtWill",
    "canCastAtHigherLevel", "castAtLevel", "castOnlyAsRitual",
    "castingTimeDescription", "characterClassId", "componentId",
    "componentTypeId", "components", "componentsDescription",
    "concentration", "conditions", "countsAsKnownSpell", "damageEffect",
    "definitionId", "definitionKey", "displayAsAttack", "duration",
    "entityTypeId", "healing", "healingDice", "id", "isHomebrew",
    "isLegacy", "isSignatureSpell", "limitedUse", "modifiers",
    "overrideSaveDc", "range", "rangeArea", "requiresAttackRoll",
    "requiresSavingThrow", "restriction", "ritual", "ritualCastingType",
    "saveDcAbilityId", "scaleType", "school", "sourceId", "sources",
    "spellCastingAbilityId", "spellGroups", "spellListId", "tags",
    "tempHpDice", "usesSpellSlot", "version",
})
ACTION_KEYS = frozenset({
    "abilityModifierStatId", "actionType", "activation", "ammunition",
    "attackSubtype", "attackTypeRange", "componentId", "componentTypeId",
    "damageTypeId", "dice", "displayAsAttack", "entityTypeId", "fixedSaveDc",
    "fixedToHit", "id", "isMartialArts", "isProficient", "numberOfTargets",
    "onMissDescription", "range", "saveFailDescription", "saveStatId",
    "saveSuccessDescription", "spellRangeType", "value",
})
FEAT_KEYS = frozenset({
    "activation", "categories", "componentId", "componentTypeId",
    "creatureRules", "definitionId", "definitionKey", "entityTypeId",
    "isHomebrew", "isRepeatable", "prerequisites", "repeatableParentId",
    "sourceId", "sourcePageNumber", "sources", "spellListIds",
})
LIMITED_USE_KEYS = frozenset({
    "maxNumberConsumed", "minNumberConsumed", "name", "operator",
    "proficiencyBonusOperator", "resetDice", "resetType",
})
NON_MECHANICAL_NESTED_KEYS = frozenset({
    "cardDescription", "cardEyebrow", "cardHeading", "classFantasy",
    "definitionKey", "featureName", "moreDetailsUrl", "slug",
    "sourcePageNumber", "subclassFlavorText", "subclassTagline", "tagline",
})

PATH_RULES = (
    ("stats[]", frozenset({"name"}), frozenset()),
    ("overrideStats[]", frozenset({"name"}), frozenset()),
    ("bonusStats[]", frozenset({"name"}), frozenset()),
    ("classes[]", CLASS_KEYS, CLASS_BUILD),
    ("inventory[]", ITEM_KEYS, ITEM_MECHANICS),
    ("race", RACE_KEYS, RACE_BUILD),
    ("background", BACKGROUND_KEYS, BACKGROUND_BUILD),
    ("spells", SPELL_KEYS | LIMITED_USE_KEYS, SPELL),
    ("classSpells", SPELL_KEYS | LIMITED_USE_KEYS, SPELL),
    ("choices", frozenset({
        "backgroundType", "choiceType", "componentTypeId", "entityTypeId",
        "defaultSubtypes", "displayOrder", "isInfinite", "isOptional",
        "itemDefinitionKey", "label", "optionIds", "options", "requiredLevel",
        "spellListId", "tagConstraints",
    }), CLASS_BUILD | RACE_BUILD | BACKGROUND_BUILD | FEAT_BUILD | ITEM),
    ("actions", ACTION_KEYS | LIMITED_USE_KEYS, ACTION),
    ("feats[]", FEAT_KEYS, FEAT_BUILD),
    ("spellSlots[]", frozenset({"id"}), frozenset({"spell_slots"})),
    ("pactMagic[]", frozenset({"id"}), frozenset({"spell_slots"})),
    ("deathSaves", frozenset({"isStabilized"}), frozenset({"hp"})),
    ("currencies", frozenset(), ITEM),
    ("customItems[]", frozenset(), ITEM),
)

# These preferences affect presentation or UI defaults, not the mechanical
# character projection implemented by CharacterCheck.
IGNORED_BY_PATH = {
    "preferences": frozenset({
        "abilityScoreDisplayType", "diceSetId", "enableContainerCurrency",
        "enableDarkMode", "primaryMovement", "primarySense", "privacyType",
        "sharingType", "showScaledSpells", "showUnarmedStrike",
    }),
}

MODIFIER_METADATA_KEYS = frozenset({
    "availableToMulticlass", "componentTypeId", "entityId", "entityTypeId",
    "friendlySubtypeName", "friendlyTypeName", "id", "modifierSubTypeId",
    "modifierTypeId",
})
MODIFIER_SEMANTIC_KEYS = frozenset({
    "bonusTypes", "dice", "duration", "fixedValue", "requiresAttunement",
    "tagConstraints",
})
MODIFIER_PATTERN_SCOPES = {
    "advantage:saving-throws": frozenset({"saves"}),
    "bonus:spell-group-healing": frozenset({"spell_output"}),
    "immunity:magical-sleep": frozenset({"defenses"}),
    "proficiency:calligraphers-supplies": frozenset({"skills"}),
    "set-base:darkvision": frozenset({"senses"}),
    "set:innate-speed-walking": frozenset({"speeds"}),
    # ``set:subclass`` is a redundant selection marker. The explicit
    # ``subclassDefinition`` and its level-gated features are authoritative.
    "set:subclass": frozenset(),
}


def modifier_scope(modifier):
    pattern = f"{modifier.get('type') or ''}:{modifier.get('subType') or ''}"
    return MODIFIER_PATTERN_SCOPES.get(pattern)


def omission_scope(path, key):
    """Return a family set, empty reviewed-ignore set, or ``None``."""
    if path == "$":
        return TOP_LEVEL.get(key)
    ignored = IGNORED_BY_PATH.get(path)
    if ignored is not None and key in ignored:
        return frozenset()
    if key in NON_MECHANICAL_NESTED_KEYS:
        return frozenset()
    for prefix, keys, families in PATH_RULES:
        if path.startswith(prefix) and key in keys:
            return families
    return None


_REGISTRY_CONTRACT = {
    "version": 1,
    "top_level": {key: sorted(value) for key, value in sorted(TOP_LEVEL.items())},
    "path_rules": [[path, sorted(keys), sorted(families)]
                   for path, keys, families in PATH_RULES],
    "ignored_by_path": {
        path: sorted(keys) for path, keys in sorted(IGNORED_BY_PATH.items())},
    "modifier_metadata_keys": sorted(MODIFIER_METADATA_KEYS),
    "modifier_semantic_keys": sorted(MODIFIER_SEMANTIC_KEYS),
    "modifier_pattern_scopes": {
        pattern: sorted(families)
        for pattern, families in sorted(MODIFIER_PATTERN_SCOPES.items())},
    "non_mechanical_nested_keys": sorted(NON_MECHANICAL_NESTED_KEYS),
}
REGISTRY_FINGERPRINT = "sha256:" + hashlib.sha256(
    json.dumps(_REGISTRY_CONTRACT, sort_keys=True,
               separators=(",", ":")).encode("utf-8")
).hexdigest()
