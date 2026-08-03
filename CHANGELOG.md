# Changelog

## 0.7.0 - 2026-08-02

- Add a deterministic, value-free `table.evaluation/1.0` projection for
  `derive`/`report`. It preserves canonical field trust, treats mutable
  player-authority state as an out-of-scope advisory, maps gaps and input
  failures to typed refusals, and remains explicitly self-attested.
- Pair every Coverage Inventory answer with its numbered 2024 character-sheet
  question, and include deduplicated sheet-specific lint questions in `quiz`
  without supplying answer keys for non-trusted mechanics.
- Interpret selected D&D Beyond builder choices as activation evidence for
  choice-backed proficiencies, languages, and tools even when the associated
  modifier retains `isGranted: false`; preserve only the mechanical join IDs.
- Treat `equipped` as authoritative for armor, shields, and active weapon
  attacks. Carried armor no longer silently changes AC; an Unarmed Strike is
  synthesized as an available 2024 attack, and a weapon's Sap/Push/etc.
  property is no longer reported as a learned mastery.
- Derive ordinary spell-slot maxima from the pinned SRD progression and use
  D&D Beyond's `used` counter as mutable state. The public payload's observed
  zero `available` value no longer erases valid 4/2 Cleric 3 slots.
- Add source-aware spell profiles that distinguish prepared, always-prepared,
  always-known, and granted availability from at-will, limited-free, and
  spell-slot cast modes. Enriched `alwaysPreparedSpells`,
  `alwaysKnownSpells`, and `cantrips` collections are supported without
  guessing absent subclass spells from prose.
- Preserve death-save activation versus latent counters, keep D&D Beyond's
  `isStabilized` flag separate from rules-implied three-success stability, and
  identify exhaustion only from D&D Beyond condition id 4.

- Reframed the product as experimental read-only character context for human
  and AI seats, with explicit authority and limitations.
- Removed permanent live-character examples and network-dependent fixtures.
- Added privacy-minimized defaults and explicit local persona opt-in.
- Added strict bounded input validation and redacted boundary failures.
  Unknown bounded adapter IDs are preserved and quarantined with scoped fixed
  semantic-gap findings instead of rejecting the whole sheet or defaulting to
  trusted heavy/melee math.
- Added a strictly validated, immutable, pinned offline DDB config registry,
  cross-checked against DDB Importer's MIT fallback. The runtime performs no
  config fetch. The shipped tables are minimized to current evaluator
  dependencies and exclude unrelated catalog vocabulary and generic d20/d100
  dice entries. Registry identity is separate from implemented mechanics.
- Canonicalized structured base-damage dice and property IDs; omitted unsafe
  formula/property prose; rejected null property names; and prevented unknown
  armor/attack/damage/property semantics from entering arithmetic. Provisional
  weapons are explicitly unsupported until proficiency/hand/property semantics
  are implemented.
- Added immutable CharacterSnapshotV1 export and snapshot-based partial diff,
  with separate default-mechanical, stored-character, and whole-envelope hashes;
  closed nested filtering; non-identifying omission coverage; and indeterminate
  fail-closed comparison when distinct snapshots omitted unclassified fields.
  Direct derived views now propagate omission booleans. Unknown-scope schema
  drift routes all mechanical families to unknown; omitted semantic text keeps
  a fixed gap and makes distinct snapshot comparison indeterminate.
  Plain `fetch`/workspace composition now fails closed when that evidence would
  be lost; package-level `stance` is ref-based and trust-bearing, and raw
  `build` is no longer exported.
- Added a versioned, privacy-safe DDB source-field routing registry. Reviewed
  display/provenance omissions are trust-neutral, reviewed mechanical omissions
  carry canonical family scopes and become `unsupported`, and only genuinely
  unclassified paths retain sheet-wide `unknown`. The registry is fingerprinted
  into the source schema and its modifier scopes are checked against the public
  blast-radius router.
- Made distinct snapshot comparisons indeterminate when private modifier
  restrictions were omitted, distinguished same-revision named deltas as
  `mechanically_unchanged`, enforced local character identity, and validated
  canonical UTC observation timestamps.
- Added a handler-backed modifier/character-value ledger; unsupported,
  restricted, inactive, invalid, and unknown-scope records cannot enter
  arithmetic.
- Added canonical field assessments and fail-closed trust precedence across
  derive, stance, report, QA, quiz, seatpack, and intake projections.
- Renamed QA100 externally to Coverage Inventory and replaced the historical
  `OK`/`PARTIAL`/`NO` presentation with six closed assessment states.
- Tightened the unauthenticated MCP boundary: strict JSON-RPC validation,
  public refs only, bounded requests/responses, generic text plus structured
  results, inline snapshot diff baselines, and no caller-asserted role/persona
  switches.
- Rejects command-specific flags outside their supported commands, including
  `--for-dm` outside the only redacting views (`seatpack` and `intake`).
  DM projection now redacts duplicate top-level values for every canonical
  player-authority field rather than leaving a weaker unmarked copy.
- Promoted `ResourceWarning` to an error in synthetic-fixture CI, blackholed
  HTTP(S) during product tests, and added an installed-wheel smoke that runs
  outside the checkout with no package-index access after the wheel is built.
- Added distribution-status warnings, exact command-specific exit documentation,
  the SRD 5.2.1 CC-BY attribution, a complete source-distribution manifest,
  legal-notice wheel metadata, a pinned build backend, and artifact-content
  checks. These guards do not remediate the already-published 0.6.2 artifacts.
- Added an ecosystem conformance contract: use DDB Importer/Foundry and other
  licensed/research oracles before broad hand-authored rules expansion; retain
  oracle disagreement as non-trusted conflict and exact per-component rules
  provenance.

## 0.6.2

Historical release. It predates every item in **0.7.0**, including strict input
validation, CharacterSnapshotV1, canonical field states, privacy-minimized
defaults, and the hardened MCP contract. Use tag `v0.6.2` to reproduce it.

Because PyPI artifacts are immutable, 0.7.0 must never be republished as
0.6.2. Treat version pins as part of the input contract.
