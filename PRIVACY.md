# Privacy

> **Unreleased contract.** These protections describe the post-0.6.2 source
> checkout. PyPI still exposes the historical 0.6.2 artifact, which does not
> implement this privacy contract; active historical MCP Registry entries have
> unpinned runtime arguments that can resolve to it. No newly versioned
> remediation has been published.

CharacterCheck is currently local, read-only software. This repository does not
operate a hosted service, retain server-side character data, or ship telemetry.

Default outputs omit account identifiers, linked images, appearance, notes,
organizations, backstory, and verbatim persona fields. A character name and
custom mechanical names may remain because they identify the game object being
compiled; callers must still treat them as user-authored data.

Snapshot export uses closed allowlists at the top level and inside supported
nested objects. Unknown fields are omitted rather than copied. The snapshot
records three omission booleans—`unclassified_top_level_omitted`,
`unclassified_nested_omitted`, and `semantic_values_omitted`—without preserving
omitted names or values. Fixed, field-owned semantic-gap codes survive
filtering so known item omissions can route only the affected family to
`unsupported`; a retained unscoped non-item or nested-item gap fails closed as
global `unknown`. It does not export a hash of the raw pre-filter source:
`normalized_data_hash` hashes the default privacy-filtered mechanical
character, while `snapshot_character_hash` hashes the exact filtered character
stored in the snapshot. This keeps explicit persona outside the default
mechanical revision. Canonical derived views carry the same flags under
`meta.source_coverage`. Either unclassified-field flag forces a static
unknown-scope finding and prevents any mechanical family from being labeled
trusted; omitted names and values remain absent. Modifier restriction prose is
replaced by a presence sentinel. Because two different private restrictions
therefore cannot be compared, distinct restriction-bearing snapshots produce
an indeterminate diff at `$`; no digest or text oracle is retained. A distinct
snapshot with any omission flag set is likewise indeterminate.

Persona can be included only through an explicitly authorized local CLI/library
call (`--include-persona` in the CLI). It is bounded and marked sensitive and
untrusted. The unauthenticated MCP server does not offer that capability and
does not read host-local files.

Permission is purpose-specific. One-time inspection, local parsing, agent/DM
access, model-provider transfer, persona use, persistence, replay/evaluation,
training, recurring tests, and public documentation are separate consent
states. Public sharing does not imply any of the others. Narrative may also
identify third parties who did not share the sheet.

The caller owns retention and deletion of exported snapshots, shell history,
logs, model conversations, and downstream indexes. Before any hosted beta, the
operator must publish retention/deletion schedules, subprocessors and transfer
details, participant disclosure, age handling, incident response, and the
applicable legal basis. Revocation must propagate to controllable caches,
shares, logs, evaluations, memory, and indexes.

Historic releases contained live-character references and should not be
treated as consent records. Remediation of tags, package archives, mirrors, or
model caches requires an explicit owner/privacy decision and is not completed
by deleting references from the current tree.
