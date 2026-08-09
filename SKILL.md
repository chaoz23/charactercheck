---
name: charactercheck
version: 0.7.0
description: >
  Deterministic D&D Beyond character-sheet derivation with per-stat
  provenance. Use it whenever you need a character's real numbers: "what's
  my AC again?", "is this build legal?", "did anything change since last
  session?", "give me the party's sheets for tonight", session-start prep,
  or auditing a sheet a player (or a generation agent) handed you. Every
  stat is computed from the sheet's own data and traceable; anything it
  cannot derive is named, never guessed.
---

# charactercheck — the character accountant for agents

Feed it a D&D Beyond character URL, id, or saved JSON; it derives the full
sheet deterministically (no model calls) and tells you exactly which numbers
to trust and which items a human must resolve.

## Three things to remember

1. **Never hand-derive a sheet the tool can derive.** Your own arithmetic
   over DDB JSON is the documented failure mode — the tool has beaten manual
   derivation every time it was checked. If output looks wrong, suspect your
   reading, then file the discrepancy; don't recompute by hand.
2. **Exit 2 means unhandled content, and the output is still usable.** The
   derived stats are complete; the named `unhandled[]` items are your list of
   things to ask the player about. Don't retry, don't guess, don't discard.
3. **Every failure prints JSON with an `action` field — do what it says.**
   Never a traceback; exit 3 means the sheet couldn't be retrieved at all.

## Exit codes ARE the verdict (per-verb since 0.7.0)

For `derive`/`report`:

| exit | meaning | what you do |
|---|---|---|
| 0 | no lint, nothing unhandled | use the output |
| 1 | lint findings — sheet disagrees with itself | usable; resolve `lint[]` with the player |
| 2 | unhandled/unsupported content present (the honest lane) | trusted fields usable; resolve named items with a human |
| 3 | retrieval/validation/internal failure | read `action` (and `retryable`) in the JSON and follow it |

Projection verbs (`qa`, `seatpack`, `intake`, `snapshot`, `stance`, `quiz`)
exit 0 when the projection is emitted — **inspect the embedded findings; an
exit 0 there is not a cleanliness claim.** `diff`: 0 no change · 1 any named
change · 3 failure.

## Invocation

```bash
charactercheck derive <ddb-url|id|file.json>   # full derivation (--brief for chat-sized)
charactercheck qa <ref>                        # lint pass (--full for all rows)
charactercheck seatpack <ref> [--for-dm]       # session-start pack (redacted live state; --include-persona)
charactercheck diff <ref> --baseline snap.json # what changed since the snapshot
charactercheck intake <ref>                    # save the snapshot diff compares against
charactercheck snapshot <ref>                  # point-in-time projection
charactercheck doctor                          # cold-start environment check
cat refs.txt | charactercheck --pipe derive    # batch
charactercheck derive <ref> --table-evaluation # shared-contract exit codes (0/1/2), for table pipelines
```

MCP server included; machine schema via `--schema`; also `--json` everywhere.

## Worked example

```bash
charactercheck derive examples/sample-character.json --brief
```

```text
Torvald Brightmantle — Cleric 3
  AC 15 · HP 24/24 (confirm) · init +0
  trusted: abilities, ac, initiative, hp, saves, skills, speeds, senses,
           defenses, languages, proficiency_bonus, spellcasting, ...
  UNSUPPORTED: attacks (item-semantic:weapon_proficiency, ...), weapons (...)
```

**Exit 2 — and that's the honest lane working:** every `trusted:` field is
derived and safe to use; the named `UNSUPPORTED` lanes (here: weapon-
proficiency semantics) go to a human. `(confirm)` marks a value the sheet
asserts but the derivation wants confirmed. A private sheet returns exit 3
with `"action": "Open the character on D&D Beyond, set Character Privacy to
Public, and retry [...]"` and `"retryable": false` — relay the action
verbatim; the tool never asks for credentials.

## MUST / MUST NOT

- MUST run `doctor` once on a fresh machine before blaming the network.
- MUST run `intake` at session zero so `diff` has a baseline; run `diff`
  at session start to catch between-session edits.
- MUST use `seatpack --for-dm` when handing a sheet to a DM agent — it
  redacts player-authority live state on purpose.
- MUST relay the `action` field on any failure instead of improvising.
- MUST NOT hand-derive, "correct", or fill in any stat the tool computed —
  if you disagree with a number, the discrepancy is the finding.
- MUST NOT guess at `unhandled[]` items (homebrew, unrecognized modifiers):
  they go to the player/DM by name.
- MUST NOT treat exit 2 as failure or retry it — the output is complete.

## Validation checkpoints (self-audit before using a sheet)

exit code read · `unhandled[]` surfaced to a human (if exit 2) · `lint[]`
resolved or acknowledged (if exit 1) · numbers relayed from output, not from
memory · baseline snapshot exists for diff.

## Cross-skill workflows (check family)

- **Character audit:** derive here → names the tool can't place appear in
  the exit-2 report → `srdcheck jurisdiction "<name>"` for each → in-SRD
  disputes adjudicated by srdcheck, the rest ruled by the DM.
- **Session start:** `diff` against the intake baseline → `seatpack --for-dm`
  to the DM agent → live play begins with numbers nobody derived by hand.
- **Session retro:** dmcheck reads the session ledger; sheet-derived numbers
  referenced in rulings trace back here via provenance.

Family contract: [FAMILY.md](https://github.com/chaoz23/srdcheck/blob/main/FAMILY.md).

## Changelog / stale-knowledge deltas

- **0.7.0:** exit contract is per-verb (projections exit 0 with embedded
  findings — inspect them); `snapshot` verb; `--table-evaluation` maps any
  verb onto the shared 0/1/2 table contract; `--include-persona` gates
  persona output (no longer default); failure JSON adds `retryable`;
  unsupported item-semantic lanes are named per field. If you remember
  0.6.x's single exit table or persona-by-default seatpacks, that's stale.
- **0.5.1:** exit 3 + `action` field + `doctor` — retrieval failures are
  structured, never tracebacks.
- The sheet source is the DDB character service; a saved JSON file works
  identically and needs no network or permissions (MCP server never reads
  host-local files — use the CLI for file refs).

Unofficial; not affiliated with D&D Beyond or Wizards of the Coast. Verdicts
are advisory: the table's humans own every judgment call.
