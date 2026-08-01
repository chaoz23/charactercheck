# Migration notes

## Unreleased safety foundation after 0.6.2

PyPI currently installs the historical 0.6.2 artifact. The changes below exist
only in the source checkout under review. That checkout also temporarily
reports `0.6.2`, so do not select behavior from the version string alone. Use
schema names/versions and feature detection during review, and require a new
package version before production adoption or publication.

### Input and privacy

- References are parsed strictly. Strings that merely contain digits are no
  longer converted into character IDs.
- Input JSON must satisfy the bounded structural contract.
- Default derived output no longer includes an account-linked character URL,
  username, verbatim unsupported source text, stash notes, or persona.
- Persona requires explicit local `--include-persona`.
- Known public errors no longer serialize `ref` or raw `detail`.

### Canonical assessments and projections

- `derive` now includes `meta`, `fields`, and five exclusive family trust
  lanes. Canonical field states are `trusted`, `confirm`, `unsupported`,
  `unknown`, `invalid`, and `not_applicable`.
- State precedence is fail-closed: `invalid` > `unknown` > `unsupported` >
  `confirm` > `trusted`. A downstream view may preserve or worsen a state; it
  may not remove a material finding.
- Mutable HP, slots, resources, inventory, and equipment observations are
  player/session-host authority. Expected answers in `quiz` are present only
  for canonical `trusted` fields.
- `report` now returns canonical `meta`, `trust`, and `fields` alongside
  findings. `stance` now returns an envelope containing those trust artifacts
  and a nested `stance` value; consumers of the old bare stance object must
  update their path.
- `qa` is now Coverage Inventory, not a score. Its historical
  `OK`/`PARTIAL`/`NO` statuses become `trusted`, `confirm`, `unsupported`,
  `unknown`, `invalid`, or `not_applicable`; MCP QA returns structured rows,
  counts, trust, field assessments, and observation metadata.
- One observation carries one `source_revision` and `as_of` through each
  projection. `autonomous_ready` is false in the current schema.

### Snapshot and MCP breaks

- `snapshot` exports CharacterSnapshotV1. `diff --baseline` now requires that
  versioned object; raw payloads and old derived/intake JSON are rejected.
- `source.normalized_data_hash` is the default privacy-filtered mechanical
  revision; `source.snapshot_character_hash` hashes the exact stored filtered
  character, including persona only when explicitly requested. `snapshot_id`
  covers the whole envelope except its own value.
- Snapshot export drops unclassified top-level and nested fields and records
  three booleans plus a canonical-family-only
  `scoped_mechanical_omissions` list under `source.coverage`; omitted source
  names and values are not serialized. `semantic_values_omitted` distinguishes unsafe formula/property
  text removed after a fixed scoped `_semanticGaps` code was retained. A
  distinct comparison with any omission flag set is
  `comparison_complete: false`, relationship `indeterminate`, and emits `$` in
  `unsupported_changes`. Absence from another lane is not completeness.
- Canonical derived views expose the same typed coverage as
  `meta.source_coverage`.
  Reviewed display/provenance fields do not change trust. Reviewed mechanical
  omissions add `source:scoped-fields-omitted` and route listed families to
  `unsupported`.
  The unclassified top-level/nested flags add
  `source:unclassified-fields-omitted` and route all mechanical families to
  `unknown`. Semantic-value omission is routed by a retained item gap to
  affected families as `unsupported`; a non-item gap remains global `unknown`
  until its dependency scope is classified. Older consumers must not discard
  any coverage key or `_semanticGaps` marker.
- MCP denies local-file references, removes caller-asserted DM-role and persona
  semantics, and accepts an inline CharacterSnapshotV1 object for diff.
- MCP request JSON is strict and bounded. Tool schemas reject unknown
  arguments; successful tool text is a small generic notice and the actual
  object is in `structuredContent`.
- The stdio server negotiates MCP protocol `2025-11-25`, limits request lines
  to 8 MiB and complete JSON-RPC responses to 4 MiB, and returns tool-domain
  failures with `isError: true` plus a structured `retryable` decision.
- Clients that previously parsed the full JSON object from MCP text must move
  to `structuredContent`; the source contract intentionally does not duplicate
  private character context into the compatibility text block.
- Seatpack and intake load their source once. Exported snapshots provide an
  immutable revision for deterministic replay across later calls.
- Distinct snapshots containing intentionally omitted modifier-restriction
  semantics are indeterminate at `$`. A named persona/non-mechanical change
  with the same mechanical revision is `mechanically_unchanged`; only exact
  snapshot identity is `unchanged` without findings.
- Snapshot `observed_at` requires canonical UTC RFC 3339 syntax. It remains
  untrusted observation metadata, not an attested timestamp.
- Package-level `stance` is ref-based and returns its canonical trust envelope.
  Raw `build` is no longer exported. Plain `fetch` and raw `engine.build` fail
  with `source_coverage` when a dict would discard schema-drift metadata; use
  `derive` or `snapshot` instead.
- Bounded unknown/missing armor and attack discriminators no longer reject an
  entire character or silently default to heavy/melee. The adapter preserves
  opaque numeric IDs, adds a fixed scoped semantic gap, excludes the item from
  that arithmetic, and marks AC or weapon/attack families unsupported. Unsafe
  numeric magnitudes and malformed types still fail structural validation.
- Weapon dice, damage type, and property identities are canonicalized through
  the pinned offline adapter registry. Formula/property prose is omitted;
  property ID/name mismatches and incomplete legacy name-only evidence retain
  fixed gaps. Provisional weapon lines remain unsupported until proficiency,
  hand/held state, and property mechanics are proved.
- Derived metadata now carries the offline adapter-registry fingerprint. The
  source-schema fingerprint commits to that registry, coverage keys, and
  semantic-gap blast radii.
- Command-specific flags are closed. Unsupported combinations—including
  `--for-dm` outside `seatpack`/`intake`—return structured `bad_flag` exit 2
  instead of being ignored.

These are intentional safety breaks. Consumers should feature-detect schema
versions and stable error kinds rather than parsing prose. Do not deploy a
source-built artifact under the already-published 0.6.2 version.
