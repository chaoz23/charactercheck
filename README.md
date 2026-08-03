# CharacterCheck

CharacterCheck is an experimental, read-only compiler for selected D&D Beyond
character-sheet fields. It turns a public share, saved character-service JSON,
or versioned snapshot into deterministic mechanical context with provenance and
named findings.

> **Current release: 0.7.0.** Pin `charactercheck==0.7.0` when installation
> must be reproducible. Verify the installed package version and each field's
> trust state; a version string alone is not proof that a value is supported.

It is not a complete or rules-authoritative character validator. Its output is
not encounter, world, or session state and does not prove that an action is
legal. Unknown upstream fields and unsupported restrictions can affect results;
read the trust and finding data before using a value.

## Run 0.7.0 offline

Python 3.9 or newer is required. The runtime has no third-party dependencies.

```console
git clone https://github.com/chaoz23/charactercheck
cd charactercheck
python3 -m charactercheck selftest
python3 -m charactercheck derive examples/sample-character.json --brief
```

The bundled example is project-authored synthetic data. The smoke test checks
this checkout and selected derivations; it is not evidence of complete D&D
rules correctness.

Install the published package into a virtual environment for the console entry
points:

```console
python3 -m venv .venv
.venv/bin/python -m pip install charactercheck==0.7.0
.venv/bin/charactercheck derive examples/sample-character.json --brief
```

The direct `python3 -m charactercheck` path from a clone has no runtime
dependency install. An editable pip install may bootstrap the `setuptools`
build frontend if the environment does not already provide it. See
[MIGRATING.md](https://github.com/chaoz23/charactercheck/blob/main/MIGRATING.md)
before comparing 0.7.0 output or MCP surfaces with 0.6.x.

For an explicitly public character:

```console
python3 -m charactercheck derive https://www.dndbeyond.com/characters/<id>
```

Public sharing permits retrieval at that moment; it does not establish consent
for publication, recurring tests, persistence, model training, or reuse of
persona and third-party narrative content.

CharacterCheck requests no credentials. For a private sheet, use an authorized
saved character-service JSON file through the local CLI or library; do not pass
cookies, tokens, or session data.

## Product and authority boundary

CharacterCheck currently supports mechanical, read-only preparation for a
human or AI-controlled DM, PC, or NPC. It observes a character source and emits
context or reconciliation candidates. It exposes no mutation tools and does not
become the authority for HP, conditions, concentration, expended resources,
equipment declarations, DM rulings, encounter state, or world state.

The human principal remains responsible for access and use. An AI actor must
not infer permission, role, or visibility from sheet contents or a tool
argument. Where a value is marked `confirm`, `unsupported`, `unknown`, or
`invalid`, the agent should ask the named human authority or decline to use the
value. Manual play without CharacterCheck remains the fallback.

## Ecosystem and calculation boundary

CharacterCheck is being developed as a versioned **D&D Beyond-to-agent
compiler and conformance facade**, not a new complete 5e rules engine. The
strict source/snapshot/privacy/trust layer remains local. Adapter vocabulary is
seeded from a pinned offline DDB config registry that was independently
observed and cross-checked against the MIT-licensed DDB Importer fallback. The
production runtime never fetches that config endpoint. The distributed
registry is a purpose-limited allowlist for current evaluator branches—not a
copy of DDB's full configuration or third-party catalog vocabulary.

Registry membership establishes only that an upstream ID/name was observed;
it does not prove that CharacterCheck implements its mechanics. Bounded unknown
IDs are retained as opaque adapter evidence, fixed semantic-gap codes prevent
default calculations, and unsafe formula/property prose is omitted. Current
weapon proficiency/hand state and unimplemented property semantics therefore
remain explicitly unsupported even when a provisional attack line can be
rendered.

The next mechanics work is a differential conformance spike using exact SRD
revisions, narrow MIT-compatible DDB Importer evidence, and Foundry dnd5e as a
versioned model/behavior oracle. DDB/displayed and third-party calculated values
are attributed claims, not unquestionable truth; disagreement must become a
non-trusted conflict. See
[ECOSYSTEM_CONFORMANCE.md](https://github.com/chaoz23/charactercheck/blob/main/ECOSYSTEM_CONFORMANCE.md)
[SOURCE_FIELD_ROUTING.md](https://github.com/chaoz23/charactercheck/blob/main/SOURCE_FIELD_ROUTING.md),
and [THIRD_PARTY_NOTICES.md](https://github.com/chaoz23/charactercheck/blob/main/THIRD_PARTY_NOTICES.md).

The observed DDB service/config surfaces remain undocumented and unsupported
as public APIs. Their technical availability does not grant commercial access,
content rights, stability, or consent. A commercial build needs a licensed or
counsel-approved input/update path and should prefer an authorized user/host
export until then.

## Inputs

The input parser accepts exactly:

- a positive 1–20 digit character ID with no leading zero;
- an HTTPS URL on `dndbeyond.com` or `www.dndbeyond.com` whose path is exactly
  `/characters/<id>`;
- a direct local regular JSON file, when the calling surface permits files; or
- a `CharacterSnapshotV1` JSON file.

Local symbolic links are rejected. Missing paths are not reinterpreted as IDs.
Raw local character files and HTTP responses are bounded to 8 MiB; a local
CharacterSnapshotV1 envelope may be up to 16 MiB so a maximum-size filtered
source can round-trip with its metadata. JSON also has depth, node, string,
collection, inventory, modifier, and container-traversal limits.

## Commands

| Command | Current contract |
|---|---|
| `derive <ref>` | Selected derived fields, provenance, findings, and trust routing |
| `derive <ref> --brief` | Deterministic chat-sized summary; still subject to findings |
| `derive <ref> --table-evaluation` | Value-free, deterministic, self-attested `table.evaluation/1.0` assessment envelope |
| `stance <ref>` | Envelope containing stance, canonical assessment, trust, fields, and observation metadata |
| `report <ref>` | Canonical field/trust assessments plus findings and identified feature names |
| `qa <ref> [--full]` | 100-question **Coverage Inventory** pairing each answer with a closed field state; not a validity score |
| `seatpack <ref>` | Privacy-minimized read-only character context |
| `intake <ref>` | Pre-session context plus questions and authority boundaries |
| `quiz <ref>` | Settlement and sheet-specific finding questions; non-trusted values never become answer keys |
| `snapshot <ref>` | Export a versioned, integrity-checked observation |
| `diff <ref> --baseline snapshot.json` | Classify supported changes; mark omitted-source comparisons indeterminate |
| `doctor [ref] [--json]` | Diagnose runtime/network/source access without echoing the ref |
| `selftest` | Offline installation and selected-derivation smoke test |

`--pipe` reads refs from standard input. `charactercheck --schema` emits the
machine-readable CLI contract.

`--table-evaluation` is also accepted by `report`. It projects canonical field
states and source/policy digests, never character values. Trusted fields count
as evaluated; unsupported, unknown, invalid, and non-authority confirmation
states fail closed. Mutable player-authority fields are outside the evaluator's
scope and become advisories requiring player/session-host reconciliation. The
envelope is always `self_attested`; it is not proof of source identity,
freshness, table role, encounter state, or action legality.

### Question catalog

The Coverage Inventory pairs each of its 100 answers with the corresponding
human-readable D&D 2024 character-sheet lookup question. Structured rows carry
`number`, `field`, `question`, `state`, `value`, and `content_trust`. The
question catalog is an organizational contract, not an assertion that the
supplied JSON Schema's value types or the complete 2024 rules are implemented.
An answer remains unusable when its row is `unsupported`, `unknown`, or
`invalid`; mutable `confirm` rows remain player/session-host authority.

The settlement `quiz` also includes each sheet-specific lint question exactly
once. Those prompts never receive an expected answer when their affected
family is not trusted. Account identity and roleplay/persona questions remain
privacy-omitted from default output.

### Snapshots and diff

Capture a baseline and compare a later observation:

```console
python3 -m charactercheck snapshot examples/sample-character.json > baseline.json
python3 -m charactercheck diff examples/sample-character.json --baseline baseline.json
```

`CharacterSnapshotV1` records the adapter, source ID, source-schema fingerprint
(which commits to the pinned adapter registry and semantic-gap contract),
observation time, engine/rules profile, privacy classification, hashes,
coverage, and a snapshot ID. Canonical derived metadata also exposes the
adapter-registry fingerprint directly. Account identifiers and linked images
are always removed.
Persona is excluded by default. Snapshots do not migrate silently; unsupported
versions fail with `snapshot_schema`. Observation times use canonical UTC
RFC 3339 (`...Z`) syntax; they describe caller/source observation order, not a
trusted timestamp or proof of freshness.

The hash meanings are intentionally distinct:

- `source.normalized_data_hash` is the canonical hash of the default
  privacy-filtered mechanical character. Projections use it as
  `source_revision`; it deliberately excludes persona and every omitted field.
- `source.snapshot_character_hash` hashes the exact filtered `character` stored
  in the snapshot, so an explicitly persona-inclusive snapshot can differ from
  the default mechanical revision.
- `meta.snapshot_id` covers the complete snapshot envelope except for the ID
  field itself, including observation metadata, privacy declarations, coverage,
  and the stored character.

These hashes are deterministic integrity/content identifiers, not signatures,
attestations, or proof of source authenticity. A party able to edit a snapshot
can recompute unkeyed hashes. Keep baselines in a trusted store and let an
authenticated session host bind them to principals and audit history.

Snapshot filtering is closed at the top level and inside supported nested
objects. `source.coverage` contains three booleans:
`unclassified_top_level_omitted`, `unclassified_nested_omitted`, and
`semantic_values_omitted`, plus a sorted `scoped_mechanical_omissions` list of
canonical family names. It never carries omitted source names or values.
Reviewed display/provenance omissions are trust-neutral; reviewed mechanical
omissions add `source:scoped-fields-omitted` and route only listed families to
`unsupported`. The first two booleans have unknown mechanical scope; derive adds
the static `source:unclassified-fields-omitted` finding and routes every
mechanical family to `unknown`. The third records unsafe semantic text removed
after a fixed, field-scoped `_semanticGaps` code was retained; the
item-semantic ledger routes the affected family to `unsupported` without
copying the text. The same coverage appears as `meta.source_coverage`; a
downstream view may not turn any incomplete observation back into `trusted`.

Diff is partial by design. Its `coverage.classified` list enumerates the coarse
source families it can compare. When either of two distinct snapshots says an
unclassified or reviewed scoped field or unsafe semantic value was omitted, or
either contains private modifier restriction semantics whose text was
intentionally omitted, diff emits a `$`
`unsupported_changes` record, sets `comparison_complete: false`, and reports
the relationship as `indeterminate`; an exact identical snapshot can still be
`unchanged`. Distinct snapshots with the same mechanical revision but a named
persona/non-mechanical delta are `mechanically_unchanged`, not `unchanged`. A
changed mechanical revision that reaches no classifier also falls back to `$`.
Diff reports candidates or uncertainty only and never applies a change.
For controlled D&D Beyond UI research, use the privacy and reversal gates in
[the A → B → A human differential protocol](docs/human-differential-testing.md).

## Trust and canonical field semantics

The `trust` block routes every known stat family into one exclusive
lane:

- `trusted`: no detected finding reaches the field within this version's
  documented coverage. This is not a global safety or rules-validity claim.
- `ask_player`: a known ambiguity requires confirmation; `asks` carries the
  question.
- `unsupported`: observed content has no applicable handler for that family.
- `unknown`: observed content has unknown target scope, so derived families
  fail closed.
- `invalid`: a known handler received malformed or contradictory source data.

Each material value also has a canonical assessment in `fields` with `value`,
`state`, `formula`, `inputs`, `sources`, `rules_profile`, `findings`,
`confidence`, `authority`, `as_of`, `stale`, and `sensitivity`. Field states
are the closed set `trusted`, `confirm`, `unsupported`, `unknown`, `invalid`,
and `not_applicable`. Family `ask_player` maps to field `confirm`.
`not_applicable` is used when a field does not exist for the character, such as
spellcasting fields for a noncaster.

Fail-closed precedence is `invalid` > `unknown` > `unsupported` > `confirm` >
`trusted`; a projection may preserve or worsen a state, never improve it.
Mutable HP, expended slots, resources, and equipment remain player/session-host
authority. `meta.aggregate_state` is the worst material field state and
`meta.autonomous_ready` is currently always false. Values from one observation
share the same default-mechanical `source_revision` and `as_of`.

Views must preserve or worsen trust; they may not remove a material finding.
Consumers should read `meta`, `fields`, `trust`, `lint`, and `unhandled` rather
than treating an aggregate state as proof of completeness. See
[SUPPORT.md](https://github.com/chaoz23/charactercheck/blob/main/SUPPORT.md).

### D&D Beyond mechanics represented in report schema v2

- Builder-choice rows are joined to modifiers by stable mechanical IDs. This
  recovers selected skills, languages, and standard tools even when D&D Beyond
  leaves the modifier's `isGranted` flag false. Builder labels and unselected
  option catalogs are not retained.
- Reviewed direct facts now include species walking speed and darkvision,
  magical-sleep immunity, the closed Charmed-save condition, and numeric
  spell-group healing bonuses. They retain handler/source provenance and stay
  non-trusted whenever separate omitted source mechanics reach their family.
- Armor and shield AC requires `equipped: true`. `combat.weapons` remains an
  inventory view; `combat.active_attacks` is the action-facing view and
  includes the 2024 Unarmed Strike. A weapon mastery property is reported
  separately from `masteries_known` and is never treated as proof that the
  character learned it.
- Ordinary `slots_max` comes from the pinned SRD progression and
  `slots_current` subtracts D&D Beyond's `used` counters. Source-aware
  `spell_profiles` preserve availability and cast modes when the source
  exposes them.
- Public anonymous character payloads can omit class/subclass
  always-prepared spell collections even when the signed-in sheet displays
  them. CharacterCheck accepts enriched `alwaysPreparedSpells`,
  `alwaysKnownSpells`, and `cantrips` collections, but does not invent an
  absent domain/species/feat spell grant from feature prose. That lane remains
  unsupported until direct source evidence or a pinned edition-aware resolver
  is available.
- Death-save counters expose `active` versus `latent`; source
  `isStabilized` and rules-implied three-success stability remain distinct.
  Exhaustion is read from D&D Beyond condition id 4, not from any condition
  that happens to carry a level.

## Privacy and untrusted text

Default CLI and MCP mechanical outputs omit D&D Beyond usernames, account
identifiers, linked images, appearance, notes, backstory, organizations, and
verbatim trait/ideal/bond/flaw text. Custom mechanical names may still be
present and should be treated as user-authored content.

The trusted local CLI/library permits explicit persona opt-in for `seatpack`,
`intake`, or `snapshot` (`--include-persona` in the CLI). Returned persona text
is bounded, labeled `sensitivity: persona` and
`content_trust: untrusted_source_text`, and must never be interpreted as
instructions. The unauthenticated MCP server exposes neither persona opt-in nor
host-local file access. Its former `for_dm` argument was not authorization and
is not a role boundary. In trusted local `seatpack`/`intake` calls, `--for-dm`
replaces all duplicated player-authority live values—current HP/slots, stance,
resources, and inventory—with an explicit marker; it does not grant DM access.

CharacterCheck has no hosted service, account database, telemetry, cache, or
server-side persistence in this repository. The caller controls exported
files, logs, model transfer, and deletion. See
[PRIVACY.md](https://github.com/chaoz23/charactercheck/blob/main/PRIVACY.md) and
[SECURITY.md](https://github.com/chaoz23/charactercheck/blob/main/SECURITY.md).

## Exit and error contract

Exit status is command-specific:

| Command | `0` | `1` | `2` | `3` |
|---|---|---|---|---|
| `derive`, `report` | no lint or unhandled record | lint, with no unhandled record | one or more unhandled records, including unknown/invalid/unsupported states | structured input, retrieval, validation, or internal failure |
| `diff` | complete comparison with no detected change | any named change or an indeterminate omitted-source/restriction comparison | — | structured input, snapshot, retrieval, or internal failure |
| `stance`, `qa`, `snapshot`, `quiz`, `seatpack`, `intake` | projection emitted; inspect embedded fields/findings | — | — | structured input, retrieval, validation, or internal failure |
| `selftest` | smoke test passed | smoke test failed | — | — |
| `doctor` | all checks passed | — | — | at least one diagnostic check failed |

With explicit `--table-evaluation`, the shared contract's exit codes apply:
`0` checked clean, `1` complete with advisories/findings, and `2` incomplete,
unsupported, invalid, or internal error. Native command behavior is unchanged
when the flag is absent. `--brief` and `--table-evaluation` are mutually
exclusive.

The CLI rejects every unsupported command/flag combination with structured
`bad_flag` exit 2; notably `--for-dm` is valid only for `seatpack` and `intake`.
Missing arguments,
unknown commands/options, and `diff` without `--baseline` use argparse's
plain-text usage error and exit 2. An exit 0 from a projection does not imply
that every canonical field is trusted or that autonomous use is safe.

Recognized runtime/input failures return structured `error`, `message`,
`action`, `retryable`, and `exit_code` fields without serializing the ref, local
path, source value, or raw exception detail. Unexpected process-boundary
failures return `internal_error` plus a correlation ID and log only that ID and
the exception class. Library callers receive typed `CharacterCheckError`
instances.

The package-level library surface is deliberately canonical: `derive(ref)` and
`stance(ref)` retain trust/coverage context. `fetch(ref)` returns a plain
privacy-filtered character only when no omission-coverage signal would be lost;
otherwise it raises typed `source_coverage`. The raw arithmetic workspace
builder is internal and is not exported from `charactercheck`. Do not compose a
plain fetched dict into a new derivation when the source reports schema drift;
use `derive`, `snapshot`, or another canonical ref-based view.

## MCP

Run `python3 -m charactercheck.mcp` from the checkout (or
`charactercheck-mcp` after installing that checkout) over stdio. It exposes
`derive`, `stance`, `qa`, `diff`, `snapshot`, `seatpack`, `quiz`, `report`,
`intake`, `selftest`, and `doctor`. It is read-only, accepts public D&D Beyond
references rather than server-local paths, omits persona, and treats mutable
player state conservatively. It does not authenticate a human principal or
enforce table roles; a trusted host must provide those capabilities before
active play.

The stdio server implements MCP protocol `2025-11-25`, accepts at most an
8-MiB request line, and emits at most a 4-MiB JSON-RPC response. Tool-domain
failures return `isError: true` with the structured error contract. Successful
tool data is in `structuredContent`; the text block is deliberately a short
generic notice instead of a duplicate of the character object, reducing
privacy exposure and context use for clients that support structured results.

## Development and CI

```console
python3 -m unittest discover -s tests -v
```

CI's product tests and installed-wheel runtime smokes use only local synthetic
fixtures or mocked network boundaries, with HTTP(S) routed to a closed local
port so an accidental character-service request fails. GitHub Actions
checkout/setup and installation of the packaging frontend still require their
normal GitHub/PyPI bootstrap access, so the workflow as a whole is not an
air-gapped build. No live player character is a permanent test or advertised
example. See
[CHANGELOG.md](https://github.com/chaoz23/charactercheck/blob/main/CHANGELOG.md)
and
[MIGRATING.md](https://github.com/chaoz23/charactercheck/blob/main/MIGRATING.md)
for compatibility notes.

## Credits and marks

Schema semantics for the D&D Beyond character-service payload were partly
informed by reading [MrPrimate/ddb-importer](https://github.com/MrPrimate/ddb-importer)
(MIT). The initial adapter registry was independently observed and cross-checked
against its fallback registry; narrow mapping facts and the snapshot/fallback
design were adapted with attribution. See
[NOTICE](https://github.com/chaoz23/charactercheck/blob/main/NOTICE) and
[THIRD_PARTY_NOTICES.md](https://github.com/chaoz23/charactercheck/blob/main/THIRD_PARTY_NOTICES.md).

D&D Beyond and Dungeons & Dragons are trademarks of Wizards of the Coast.
CharacterCheck is an unofficial, independent project and is not endorsed by or
affiliated with Wizards of the Coast.

<!-- MCP registry ownership marker (do not remove). -->
mcp-name: io.github.chaoz23/charactercheck
