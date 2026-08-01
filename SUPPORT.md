# Support matrix

This matrix describes the **unreleased source contract after 0.6.2**. It is a
coverage statement, not a claim of rules completeness. PyPI's current 0.6.2
artifact predates these changes even though this checkout temporarily retains
the same version string.

| Distribution | Status | Contract |
|---|---|---|
| Source checkout containing this file | Unreleased; under review | The safety, privacy, snapshot, canonical-assessment, and MCP contract below |
| `pip install charactercheck` | Published historical 0.6.2 | Earlier behavior; do not assume the source contract below |
| `server.json` | DO-NOT-PUBLISH historical descriptor | Intentionally pins `charactercheck==0.6.2`; replace it only as part of an authorized, newly versioned package/manifest release |
| Active MCP Registry entries | Historical and not remediated | Published runtime arguments are unpinned and can resolve to PyPI 0.6.2; deprecate/update them through the registry owner account |

| Area | Unreleased source status | Important boundary |
|---|---|---|
| Public D&D Beyond character retrieval | Supported | Exact public URL/ID only; no credentials |
| Saved character-service JSON | Local CLI/library only | Direct regular files only; bounded and validated |
| CharacterSnapshotV1 | Supported | Default-mechanical revision hash, exact stored-character hash, whole-envelope snapshot ID, canonical UTC observation syntax, three non-identifying omission booleans, and a values-free scoped-family list; unkeyed hashes/times are not attestations or authorization evidence |
| Ability, save, skill, basic AC/HP/initiative derivation | Partial | Only registered handlers and documented checks; bounded unknown armor/attack IDs are retained as fixed semantic gaps and excluded from affected arithmetic rather than rejected or defaulted |
| Weapons, inventory, resources, spell metadata | Partial | Custom, restricted, and edition-specific content may be unsupported |
| Movement, defenses, conditional effects | Limited | Absence from output is not evidence the capability is absent |
| Canonical field assessments | Supported for emitted material fields | Closed states; every projection must preserve or worsen uncertainty; reviewed omissions route declared families to unsupported, unclassified-field omissions and unscoped nested/non-item gaps route all mechanical families to unknown, and fixed root-item gaps route affected families to unsupported |
| Coverage Inventory | Extraction inventory | Six closed states; not character validity or rules legality |
| Snapshot diff | Enumerated partial coverage | Distinct snapshots with any omitted-source coverage or private restriction semantics are indeterminate and emit `$`; same-revision named non-mechanical deltas are `mechanically_unchanged`; nothing is applied |
| Python package API | Canonical ref-based projections | `derive`/`stance` retain trust; plain `fetch` and raw workspace building fail if coverage would be discarded; raw `build` is not package-exported |
| Persona | Explicit local opt-in | Bounded untrusted source text; omitted from MCP |
| MCP | Experimental read-only | Public refs only; no mutation, authentication, or role enforcement |
| Encounter/world/session state | Not supported | Requires a separate authoritative session host |
| Action legality/rules adjudication | Not supported | Character context cannot decide global legality |

Family trust lanes are `trusted`, `ask_player`, `unsupported`, `unknown`, and
`invalid`. Canonical field states are `trusted`, `confirm`, `unsupported`,
`unknown`, `invalid`, and `not_applicable`, with fail-closed precedence of
`invalid` > `unknown` > `unsupported` > `confirm` > `trusted`.

`trusted` means only “no detected finding within supported coverage.” Unknown
rules profiles, unmodeled upstream additions, source drift, and implementation
bugs remain possible. The current source sets `autonomous_ready` false and does
not authorize an AI actor to act without its human/session authority.
