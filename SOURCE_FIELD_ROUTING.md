# D&D Beyond source-field routing

> **Unreleased contract.** This registry is a conservative adapter boundary,
> not a claim that D&D Beyond exposes a supported public character API or that
> CharacterCheck implements the complete sheet.

CharacterCheck removes source fields that it does not safely retain. It now
separates four cases rather than treating every omitted key as sheet-wide
uncertainty:

| Source observation | Public trust consequence |
| --- | --- |
| Reviewed display, administrative, or redundant provenance field | Omitted; no trust change |
| Reviewed mechanical field with a bounded dependency | `source:scoped-fields-omitted`; declared families become `unsupported` |
| Novel field or modifier whose dependency cannot be bounded | `source:unclassified-fields-omitted`; every family becomes `unknown` |
| Unsafe formula/property prose with a retained fixed semantic marker | The marker's item/non-item classifier determines scoped `unsupported` or global `unknown` |

Coverage never stores an omitted source key or value. Snapshots and derived
views carry three booleans plus a sorted list of canonical family names:

```json
{
  "unclassified_top_level_omitted": false,
  "unclassified_nested_omitted": false,
  "semantic_values_omitted": true,
  "scoped_mechanical_omissions": ["attacks", "weapons"]
}
```

The registry is implemented in `charactercheck/source_field_registry.py` and
its fingerprint is part of the DDB source-schema fingerprint. A registry edit
therefore changes snapshot compatibility rather than silently reinterpreting
old evidence.

## Current reviewed routing

| Observed source area | Bounded family direction |
| --- | --- |
| Stats display labels | Trust-neutral |
| Class, subclass, class-feature, option, and optional-feature mechanics | Static class/build families; inventory excluded unless item evidence exists |
| Race/origin selections and racial traits | Abilities, defenses, movement, senses, languages, attacks, spellcasting, and resources |
| Background choices | Abilities, saves, skills, languages, inventory, spellcasting, and resources |
| Feats | Static build families; inventory excluded unless item evidence exists |
| Inventory classification, weapon behavior, armor constraints, activation, capacity, and currency | Item, combat, defense, spell-output, movement/sense, and resource families as declared by the registry |
| Spell entries and definitions | Spellcasting, spell attack/DC/output, slots/preparation, attacks, and resources |
| Action entries | Attacks, saves, and resources |
| Custom senses/speeds/actions/defense/proficiency records | Their named sense, speed, action, defense, or proficiency families |
| Known UI, sharing, status, display, and source-provenance metadata | Trust-neutral |

The first registry is intentionally conservative. Several DDB builder
collections can select, replace, or activate mechanics across many families.
Their omission may therefore produce a broad union of `unsupported` families.
That is still materially different from global `unknown`: the adapter has
recognized the source area and bounded its failure mode, but it has not yet
implemented the selection dependency graph needed to recover useful trust.

## Learn-before-build evidence

The mapping was checked against the pinned MIT-licensed DDB Importer commit
[`0227f9c`](https://github.com/MrPrimate/ddb-importer/tree/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460):

- its [character source type](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/types/ddb-character-source.d.ts)
  confirms the observed class/race/background, item, spell, action, choice,
  option, optional-feature, custom-mechanic, and companion containers;
- [AdvancementHelper](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/parser/advancements/AdvancementHelper.ts)
  consumes choice definitions rather than treating them as display metadata;
- [DDBModifiers](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/parser/lib/DDBModifiers.ts)
  uses choices, options, and optional-class-feature records to decide whether a
  modifier is active;
- [CharacterFeatureFactory](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/parser/features/CharacterFeatureFactory.ts)
  uses optional-origin evidence when resolving racial features.

This is conformance/research evidence, not a runtime dependency or permission
to redistribute D&D Beyond data. No DDB Importer code or live character values
are bundled by this registry.

## Supplied-character validation

A privacy-safe, in-memory recheck of the user-supplied public sheet retained no
raw values and reported:

- no unclassified top-level omission;
- no unclassified nested omission;
- reviewed mechanical omissions across the current family catalog;
- one weapon-scoped semantic-value omission.

The result therefore contains no sheet-wide `unknown` finding. It remains
broadly `unsupported` because the adapter still omits material builder,
class/race, action, spell, and item semantics. This is containment and routing
progress, not live-schema completeness or autonomous-agent readiness.

## Required regression behavior

- A reviewed administrative/display field must not change trust.
- A reviewed mechanical omission must affect only its registered families.
- A novel top-level or nested field must remain global `unknown`.
- Omitted source keys and values must never appear in snapshots, reports,
  finding IDs, hashes, logs, or diffs.
- Snapshot replay must preserve scoped and unclassified coverage exactly.
- Distinct snapshots with any omission coverage remain `indeterminate` in
  diff, even when direct trust is family-scoped.
- Source modifier scopes and the public blast-radius router must not drift.
