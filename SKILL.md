---
name: charactercheck
version: 0.6.2
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

## Exit codes ARE the verdict

| exit | meaning | what you do |
|---|---|---|
| 0 | derived clean | use the output |
| 1 | lint findings — sheet disagrees with itself | usable; resolve `lint[]` with the player |
| 2 | unhandled content present (the honest lane) | usable; resolve named `unhandled[]` items with a human |
| 3 | could not retrieve the sheet | read `action` in the JSON and follow it |

## Invocation

```bash
charactercheck derive <ddb-url|id|file.json>   # full derivation (--brief for chat-sized)
charactercheck qa <ref>                        # lint pass (--full for all rows)
charactercheck seatpack <ref> [--for-dm]       # session-start pack (persona, vision, redacted live state)
charactercheck diff <ref> --baseline snap.json # what changed since the snapshot
charactercheck intake <ref>                    # save the snapshot diff compares against
charactercheck doctor                          # cold-start environment check
cat refs.txt | charactercheck --pipe derive    # batch
```

MCP server included; machine schema via `--schema`; also `--json` everywhere.

## Worked example

```bash
charactercheck derive examples/sample-character.json --brief
```

```text
Torvald Brightmantle — Cleric 3
  AC 15 · HP 24/24 · init +0
  trusted: ac, hp, initiative, saves, skills, attacks, weapons, speeds,
           proficiency_bonus, spellcasting, spell_save_dc, spell_attack_bonus,
           spell_output, spell_slots, prepared_spells, inventory
```

Exit 0: every listed field is derived and trusted. A private sheet instead
returns exit 3 with `"action": "Open the character on D&D Beyond, set
Character Privacy to Public, and retry [...]"` — relay that action to the
player verbatim; the tool never asks for credentials.

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

- **0.4.0:** `seatpack` added (session-start pack: persona verbatim, vision
  block incl. Devil's Sight, `not_derivable` fence). If you remember a
  seatpack-less tool, that's stale.
- **0.5.1:** exit 3 + `action` field + `doctor` — retrieval failures are now
  structured, never tracebacks.
- The sheet source is the DDB character service; a saved JSON file works
  identically and needs no network or permissions.

Unofficial; not affiliated with D&D Beyond or Wizards of the Coast. Verdicts
are advisory: the table's humans own every judgment call.
