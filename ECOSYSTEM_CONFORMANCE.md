# Ecosystem conformance plan

Status: proposed implementation contract, 2026-07-31. This is an engineering
and product boundary, not legal advice.

## Decision

CharacterCheck should not become another independently invented D&D rules
engine. It should become a versioned **D&D Beyond-to-agent compiler**:

1. observe and validate an upstream character payload;
2. normalize DDB-specific shapes and identifiers into a stable intermediate
   representation;
3. evaluate only explicitly supported rules components against versioned rules
   evidence;
4. compare derived claims with independent ecosystem implementations and DDB's
   own displayed/calculated values; and
5. project values, provenance, uncertainty, privacy, and authority boundaries
   for AI DMs, PCs, and NPCs.

Existing fail-closed behavior remains the containment layer. The pivot changes
how coverage is earned: mappings and calculations must be learned from pinned,
reviewed evidence instead of guessed from one payload or embedded directly in
the semantic core.

## Evidence and license matrix

Availability is not permission. A public endpoint, repository, identifier, or
calculated value is evidence; it is not automatically redistributable content.
Every imported algorithm, table, fixture, or asset still needs a recorded
source and license decision.

| Evidence source | What it can establish | License/status | CharacterCheck use |
|---|---|---|---|
| DDB character-service payload and DDB-rendered sheet | Actual upstream shapes, identifiers, explicit selections, and DDB-calculated/displayed values | Undocumented and unsupported as a public API; DDB terms and user authorization apply | Input adapter and one conformance oracle. Never treat public sharing as consent to retain, publish, or train on a sheet. |
| [DDB-hosted config endpoint](https://www.dndbeyond.com/api/config/json) | DDB enum/config observations, including names associated with identifiers | Publicly addressable without authentication when reviewed, but not a documented public API, stability promise, permission grant, or open-content license | Review-time evidence only. Do not fetch at package runtime or redistribute the raw payload. |
| [MrPrimate/ddb-importer at `0227f9c`](https://github.com/MrPrimate/ddb-importer/tree/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460) | Mature DDB source types, mappings, modifier handling, AC conversion, and test cases | [MIT software](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/LICENSE.md). Bundled DDB-derived data or non-code content needs separate provenance review. | Primary adapter/conformance reference. MIT code may be adapted only with notice and file-level provenance; prefer independently specified mappings and synthetic tests. |
| [Foundry `dnd5e` at reviewed commit `20531f0`](https://github.com/foundryvtt/dnd5e/tree/20531f08cbd2b7e53063b51ca5a7d17d61323e89) | Mature 5e data models, rules-era handling, calculations, and behavior | MIT software; SRD 5.1/5.2 content is CC BY 4.0; images and other assets have mixed licenses, as documented by the [project](https://github.com/foundryvtt/dnd5e#licenses). | Canonical-model and differential oracle. Adapt only clearly identified MIT software; attribute SRD content; do not bundle unreviewed packs or assets. |
| [Avrae at `4e459b3`](https://github.com/avrae/avrae/tree/4e459b3f01018d307bb85fc9e01dc4edee0eea85) | Character import, dice, and automation behavior from a mature agent-like play system | GPL-3.0 | Study, black-box comparison, and independently written fixtures only unless a deliberate GPL licensing decision is made. |
| [Beyond20 at `3d73795`](https://github.com/kakaroto/Beyond20/tree/3d737952cd1ba505cd73a9f0d4ef8e84c5f47a8b) | DDB page extraction, roll construction, and VTT interoperability patterns | GPL-3.0 at repository level; verify any separately MIT-marked files individually | Study and differential behavior only. Do not copy GPL code into the MIT core. |
| [AboveVTT at `ce1f902`](https://github.com/cyruzzo/AboveVTT/tree/ce1f90287ad3f98f5cbb7ea4664e4d45ef67f0e6) | DDB-integrated VTT behavior, character projection, and live-play edge cases | AGPL-3.0 | Study and differential behavior only. No code copy, linking, or service dependency without an explicit AGPL product decision. |
| [SRD 5.1](https://www.dndbeyond.com/attachments/39j2li89/SRD5.1-CCBY4.0_License_live%20links.pdf) and [SRD 5.2.1](https://media.dndbeyond.com/compendium-images/srd/5.2/SRD_CC_v5.2.1.pdf) | Open normative rules and terminology for the covered 2014 and revised rules | CC BY 4.0, with attribution required | Normative rules baseline. Maintain exact revision and citation per component; do not infer that non-SRD D&D content is included. |

High-value pinned DDB Importer evidence includes its
[character source types](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/types/ddb-character-source.d.ts),
[item source types](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/types/ddb-item-source.d.ts),
[choice advancement handling](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/parser/advancements/AdvancementHelper.ts),
[choice/option/optional-feature modifier activation](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/parser/lib/DDBModifiers.ts),
[AC parser](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/src/parser/character/ac.ts), and
[config refresh safeguards](https://github.com/MrPrimate/ddb-importer/blob/0227f9cb5bee6ec74ac6ea2956b22da4cd7b4460/tools/fetch-ddb-config.mjs).
Pins are research baselines, not automatic upgrade targets.

## Learn-before-build gate

Broad mechanics work is frozen until each candidate component has an evidence
and reuse decision. The required dispositions are:

| Disposition | Meaning |
|---|---|
| `adopt` | Use a compatible, rights-cleared artifact substantially as-is behind an adapter. |
| `adapt` | Port a narrow, pinned, attributed implementation or mapping with explicit deltas. |
| `verify` | Keep CharacterCheck's implementation only after differential and normative review. |
| `build` | Implement only a residual gap for which no compatible reusable implementation exists. |
| `unsupported` | Decline to calculate until evidence, rights, or product scope changes. |

Before choosing one, record the upstream paths and IDs, every implementation
inspected, exact pins, license/reuse class, normative source, fixture coverage,
and unexplained disagreements. A component does not move from `unsupported` to
`build` merely because one synthetic fixture is easy to satisfy.

Oracle counts are not confidence counts. DDB source/config/display values share
one platform lineage; DDB Importer consumes DDB data and targets Foundry;
Foundry modules may reuse the same mappings; and Avrae's public parser delegates
some DDB computation to a private DDB-facing service. Agreement among those
outputs can therefore be correlated. Treat an exact SRD revision and an
independently reviewed synthetic expectation as separate evidence classes, and
record known code/data ancestry for every differential result. No majority
vote can turn three descendants of one mapping into independent validation.

The gate exits only with a per-component decision record, minimized fixture
corpus, reproducible comparison outputs, rights determination, dependency/blast
radius, and a short residual-work estimate. That is the signal used to decide
where to run; implementation velocity is not a substitute for it.

## Compiler architecture

The compile path is one-way and deterministic:

```text
DDB observation
  -> bounded source envelope
  -> DDB adapter (payload/config version)
  -> ImportedCharacterSnapshotV1
  -> edition-specific component evaluators
  -> evidence-backed field claims
  -> role/privacy/authority projection
  -> agent context, report, QA, or diff
```

### 1. Source acquisition and envelope

Keep the current exact-reference, size/depth/node limits, privacy filtering,
immutable snapshot, and source hash behavior. Record the observed DDB service
version, retrieval time, adapter version, config snapshot ID, and redaction
policy. Raw character payloads remain private input and are not test fixtures,
telemetry, or output.

### 2. Versioned DDB adapter

The adapter owns DDB field paths, nullability, enums, `characterValues`,
modifier shapes, and schema drift. These details must not leak into the rules
or agent-projection layers.

Target module boundary:

```text
charactercheck/adapters/ddb/v5/
  schema.py            # structural validation and bounds
  mappings.py          # generated/curated, provenance-bearing identifiers
  normalize.py         # DDB -> ImportedCharacterSnapshotV1
  dependencies.py      # raw paths that can affect each output family
```

An unknown identifier or new field must preserve its path and non-sensitive
shape, then downgrade only every potentially affected family according to the
dependency graph. It must never be guessed, silently defaulted, or learned
into production from a single observation.

### 3. Stable intermediate representation

`ImportedCharacterSnapshotV1` contains typed mechanical facts, explicit
selections, rules-era evidence, opaque source references, and coverage flags.
It contains no DDB narrative descriptions, account identifiers, images, or
persona by default. Source facts and derived values remain separate, even when
they currently agree.

### 4. Component evaluators

Evaluators are small, edition-specific components such as `ac`, `attacks`,
`spellcasting`, `proficiency`, `hp`, `resources`, and `inventory`. A component
may emit a trusted claim only when all declared dependencies are understood and
its provenance record has passed the gates below. There is no global
"complete rules engine" claim.

### 5. Agent projection

This is CharacterCheck's differentiator. It converts claims to the closed
field states `trusted`, `confirm`, `unsupported`, `unknown`, and `invalid`,
then applies privacy and table-authority policy. Current HP, conditions,
concentration, expended slots/resources, equipment declarations, and rulings
remain player/DM/session-host authority even when a source snapshot contains a
value.

## Claim and conflict resolution

Every emitted field claim must carry:

```json
{
  "field": "armor_class",
  "value": 18,
  "state": "trusted",
  "ruleset": "srd-5.2.1",
  "evidence": [
    {
      "kind": "upstream_fact",
      "source": "ddb-character-v5",
      "path": "inventory[...].equipped",
      "observation_hash": "sha256:..."
    },
    {
      "kind": "normative_rule",
      "source": "srd-5.2",
      "locator": "equipment/armor"
    }
  ],
  "evaluator": "ac@1",
  "config_snapshot": "ddb-config@2026-07-31+sha256:...",
  "conflicts": []
}
```

Resolution rules are mandatory:

1. Malformed or out-of-bounds evidence is `invalid`; do not calculate through
   it.
2. Explicit source choices are facts about the DDB build, not proof that a
   table ruling or live state is authoritative.
3. A local derived claim requires complete declared dependencies and an
   edition-specific normative basis or an explicitly documented
   product-convention basis.
4. DDB-displayed values and ecosystem implementations are conformance oracles,
   not authorities. Agreement increases confidence; it does not erase coverage
   gaps.
5. Do not majority-vote conflicts. An unexplained mechanical disagreement is
   retained as `conflict`, a non-trusted Character IR state with every claim
   and oracle version. A role projection may additionally request human
   confirmation, but it may not erase or weaken the conflict.
6. Homebrew, custom text, mixed-edition data, and unknown restrictions remain
   tainted evidence until a component explicitly supports them. Character text
   is data, never instructions.

## Per-component provenance register

No component is enabled without a checked-in provenance record containing:

| Required field | Meaning |
|---|---|
| `component_id` / `evaluator_version` | Stable calculation name and semantic version |
| `output_fields` | Exact canonical fields the component may influence |
| `ruleset` | `2014`, `2024`, or an explicitly unsupported/mixed state |
| `input_dependencies` | All normalized facts and upstream paths that can change the result |
| `enum_sources` | Config snapshot IDs and independently verified identifier mappings |
| `normative_sources` | SRD section/locator or a named DDB product convention |
| `reference_implementations` | Repository, exact commit/tag, files, and observed behavior |
| `reuse_class` | `original`, `clean_room`, `MIT_adapted`, or another reviewed license path |
| `fixture_ids` | Required positive, edge, conflict, and drift tests |
| `known_gaps` | Unsupported restrictions, homebrew, equipment state, and edition cases |
| `review` | Engineering/rules reviewer, date, and license review result |

The register is the source of truth for docs and machine-readable coverage.
Changing a dependency, mapping, rules source, or conflict policy requires a
component version bump and fixture review.

## DDB config snapshot and hash policy

1. Fetch config only in a manually authorized research/update job; never during
   import, package installation, MCP startup, or ordinary tests. Do not store
   credentials, cookies, or tokens.
2. Save the raw response only in an access-controlled, expiring research
   location. Compute `source_sha256` over its exact bytes.
3. Transform it to a minimal allowlist of identifiers and non-expressive labels
   required by supported components. Drop descriptions, URLs, assets, catalog
   content, unknown top-level keys, and anything without a recorded purpose.
4. Serialize the allowlist deterministically as UTF-8 JSON with sorted keys and
   compute `normalized_sha256`. Identify it as
   `ddb-config@YYYY-MM-DD+sha256:<normalized hash>`.
5. Update only through a reviewed PR containing the old/new hash, semantic
   diff, added/removed IDs, affected components, fixture results, license/data
   review, and rollback note. A new ID is unsupported until that PR lands.
6. Retain previous normalized snapshots needed to reproduce released outputs;
   do not retain raw config merely for convenience.
7. Package only a snapshot explicitly cleared for distribution. If clearance
   is absent, ship independently maintained mappings with the same provenance
   fields and keep DDB config as non-distributed verification evidence.

## Differential fixture matrix

Fixtures must be project-authored synthetic SRD characters or specifically
authorized, minimized, irreversible expectations. Never commit a live user's
raw payload. Each cell asserts value, field state, dependencies, provenance,
privacy projection, and expected disagreements—not only a rendered number.

| Family | Required fixture cells | Required comparisons |
|---|---|---|
| Rules era | 2014, 2024, explicit mixed/unknown | DDB edition markers; SRD source; Foundry edition behavior |
| Abilities/proficiency | base scores, bonuses, overrides, half/expertise, multiclass level boundaries | DDB display; DDB Importer mappings; Foundry/Avrae where applicable |
| Armor class | unarmored, light, medium with DEX cap, heavy, shield, natural armor, unarmored defense, bonuses, attunement/equipped state, dual wield, conflicting sets | DDB displayed AC; DDB Importer AC; Foundry model; SRD expectation |
| Attacks | STR/DEX/finesse, melee/ranged/thrown, versatile/two-handed, offhand, magical bonus, ammunition, mastery, unarmed, malformed dice | DDB attack display; DDB Importer/Beyond20/Foundry behavior; SRD expectation |
| Spellcasting | noncaster, full/half/pact caster, multiclass, item-granted spell, multiple abilities, DC/attack, prepared state, slots | DDB display; DDB Importer; Foundry/Avrae; SRD expectation |
| HP and resources | max/temp/current HP, death saves, class resources, pact/normal slots, missing and stale live state | DDB observation plus authority projection; Foundry/Avrae behavior |
| Modifiers | all supported types/subtypes, restrictions, duplicates, item-granted modifiers, `characterValues`, unknown type/subtype/restriction | DDB Importer modifier handling; independently calculated expected claim |
| Inventory | equipped/unequipped, attuned/unattuned, containers, custom/homebrew items, duplicate properties, null names, unknown enums | DDB source types; DDB Importer/Foundry conversion; privacy projection |
| Drift/security | unknown top-level/nested fields, unknown IDs, null/type confusion, oversized/deep input, hostile names/descriptions/dice strings | Fail-closed state and bounded behavior; no prompt/data leakage |
| Snapshots/diff | same observation, named non-mechanical delta, mechanical delta, omitted field, config/evaluator version change | Deterministic hashes and explicit indeterminate/version-change result |

For research-only oracles, record the repository pin, command/tool version,
input fixture ID, scalar result, and output hash. Do not make CI or production
depend on a third-party service or copyleft checkout.

## Acceptance gates

A component cannot emit `trusted` in a release until all gates pass:

1. **Rights:** every copied/adapted line, table, term set, and fixture has a
   provenance/license decision; required notices and CC BY attribution exist.
2. **Schema:** all input paths, nullability, bounds, identifiers, and affected
   families are declared; unknown inputs fail closed without crashing or
   contaminating unrelated data.
3. **Rules:** the supported edition and normative/product-convention basis are
   explicit; mixed edition and homebrew behavior is tested.
4. **Correctness:** every required fixture cell passes exact value, state, and
   provenance assertions, with zero unexplained differential mismatches.
5. **Conflict:** injected disagreement with each oracle produces the documented
   non-trusted state; no code path resolves by silent default or majority vote.
6. **Security:** bounds, malformed JSON, hostile text, dice/formula grammar,
   fuzz/property tests, and deterministic execution pass on every supported
   Python version.
7. **Privacy/authority:** default and DM projections contain no forbidden
   persona/account fields and never promote observed live state to table
   authority.
8. **Reproducibility:** snapshot, adapter, config, evaluator, and ruleset
   versions reproduce byte-stable canonical output offline.
9. **Operations:** ordinary runtime and CI require no DDB credential, DDB
   config fetch, VTT installation, external importer, browser extension, or
   network oracle.

Any unexplained mismatch blocks that component's trusted state, not necessarily
the entire compiler. The release report must list passing components and known
gaps; it must not state generalized D&D rules completeness.

## Prohibited shortcuts

- Do not copy or redistribute DDB descriptions, books, catalog/config dumps,
  images, character narratives, or user sheets.
- Do not assume data inside an MIT repository is MIT-licensed merely because
  adjacent software is.
- Do not copy GPL or AGPL implementation code, fixtures, generated tables, or
  tightly derived structure into the MIT core without a deliberate licensing
  and product decision.
- Do not bundle Foundry packs or assets unless each artifact is confirmed SRD
  or otherwise licensed; the repository's software license does not cover all
  content and assets.
- Do not make DDB, Foundry, DDB Importer, Avrae, Beyond20, or AboveVTT a runtime
  dependency or live production oracle.
- Do not turn one observed ID, one public character, or agreement between two
  descendants of the same mapping into a trusted enum rule.
- Do not use DDB's calculated value as the sole proof of correctness, and do
  not overwrite an explicit DDB fact merely because another VTT differs.
- Do not auto-update mappings or config at runtime, silently coerce unknowns,
  or weaken provenance to improve apparent coverage.

## First implementation slice

Before adding more hand-authored rules:

1. create the adapter boundary and `ImportedCharacterSnapshotV1` schema;
2. create the component provenance register and normalized config manifest;
3. move existing DDB paths/enums behind the adapter, preserving unknown IDs as
   evidence instead of globally guessing or rejecting a whole sheet;
4. build the differential harness and synthetic fixture matrix;
5. re-implement AC as the first vertical component using SRD rules, pinned DDB
   Importer/Foundry evidence, and DDB-displayed conformance; and
6. enable trusted AC only after every gate passes, then repeat independently
   for attacks, spellcasting, and resources.

This sequence keeps the safety foundation while replacing speculative breadth
with measurable, legally reviewable conformance.
