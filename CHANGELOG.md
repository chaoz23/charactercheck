# Changelog

## Unreleased

- Pair every Coverage Inventory answer with its numbered 2024 character-sheet
  question, and include deduplicated sheet-specific lint questions in `quiz`
  without supplying answer keys for non-trusted mechanics.

This section describes source changes after the published 0.6.2 artifact. The
tree still carries `0.6.2` package/version metadata during review; that is not
a claim that PyPI contains these changes. A future release must use a new,
previously unpublished version and update `server.json` in the same release.

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

Published historical release and current PyPI `latest` at the time this file
was written. It predates every item in **Unreleased**, including strict input
validation, CharacterSnapshotV1, canonical field states, privacy-minimized
defaults, and the hardened MCP contract. Use tag `v0.6.2` to reproduce it.

Because PyPI artifacts are immutable, the unreleased source must never be
published again as 0.6.2. Until a new release is explicitly authorized, treat
the source checkout and `pip install charactercheck` as different contracts.
