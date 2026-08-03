# Support matrix

This matrix describes the **0.7.0 release contract**. It is a coverage
statement, not a claim of rules completeness. Historical 0.6.x artifacts
predate these changes.

| Distribution | Status | Contract |
|---|---|---|
| Source checkout at tag `v0.7.0` | Released | The safety, privacy, snapshot, canonical-assessment, and MCP contract below |
| `pip install charactercheck==0.7.0` | Released | Exact 0.7.0 package contract; verify artifact provenance and field trust |
| `server.json` | Released descriptor | Pins the MCP runtime to `charactercheck==0.7.0` |
| MCP Registry `io.github.chaoz23/charactercheck` 0.7.0 | Released descriptor | Resolves the exact PyPI 0.7.0 package through `uvx` |

| Area | 0.7.0 status | Important boundary |
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
