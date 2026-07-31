# charactercheck

**Deterministic D&D Beyond character-sheet derivation with provenance — every stat computed and traceable, every unhandled case named, never guessed.**

The D&D Beyond API returns *build data* — there is no computed AC, attack bonus, or save anywhere in the payload. Everyone who consumes it re-derives the math, usually inside a host app (a VTT module, a browser extension) or, worse, by letting a language model guess. charactercheck is that derivation as a **standalone, dependency-free library and CLI**: the character accountant for agents.

> **Cold-boot probe (2026-07-24):** a fresh agent session given only this repo URL derived a live character correctly in **2 commands, zero failures** (install → derive), ~seconds end-to-end.
>
> **Status: 0.1 — young but real.** The derivation surface is the [100-question QA pass](#the-qa-pass) below, run in CI on synthetic fixtures. Unrecognized data is *reported, never silently defaulted* — that honesty contract is the product.

## Start here (agent or human): 2 commands

```console
$ pip install charactercheck                                   # stdlib only, no dependencies
$ charactercheck derive https://www.dndbeyond.com/characters/<id>
```

That is the whole happy path. Works on any **public** D&D Beyond character —
URL, bare id, or a saved character-service JSON file. No login, no cookies, no
API key, ever.

### If it does not work, read the exit code

Every failure prints **structured JSON with an `action` field** — the one next
thing to do. **Never a traceback.**

| exit | meaning | what to do |
|---|---|---|
| **0** | derived clean | use the output |
| **1** | lint findings — the sheet disagrees with itself | usable output; resolve `lint[]` with the player |
| **2** | unhandled content present | **not a failure.** Output is complete and usable; resolve the named `unhandled` items with a human. Don't retry |
| **3** | **could not retrieve the sheet** | read `action` in the JSON — private sheet, bad id, or no network |

```console
$ charactercheck derive https://www.dndbeyond.com/characters/1
{
 "ok": false,
 "error": "not_public",
 "message": "D&D Beyond returned 403 Forbidden for this character — it is private or not shared.",
 "action": "Open the character on D&D Beyond, set Character Privacy to Public, and retry. If you cannot change it, save the character-service JSON and pass that file path instead — charactercheck reads a saved file with no permissions at all, and never asks for credentials.",
 "exit_code": 3
}
```

Error kinds are stable and matchable: `not_public` · `not_found` · `bad_ref` ·
`network` · `rate_limited` · `bad_json` · `upstream`.

### Stuck? One command diagnoses it

```console
$ charactercheck doctor <ref>          # add --json for machine output
  [PASS] python: 3.12.1
  [PASS] dns: character-service.dndbeyond.com resolves
  [PASS] network: outbound HTTPS works
  [FAIL] character: not_public: D&D Beyond returned 403 Forbidden ...
         -> Open the character on D&D Beyond, set Character Privacy to Public ...
```

### Private character? Two supported answers

charactercheck **never asks for credentials** — that is a deliberate boundary,
not a gap. So:

1. **Make it public.** Character sheet → *Character Privacy* → Public. This is
   the usual answer and takes ten seconds.
2. **Or work from a file.** Save the character-service JSON anywhere you can
   read it and pass the path: `charactercheck derive ./shalia.json`. No
   permissions involved at all — useful for private campaigns, air-gapped
   hosts, and CI.

## What a derived character looks like

```console
$ charactercheck derive https://www.dndbeyond.com/characters/<id>
{
 "combat": {
  "ac": {"value": 16, "provenance": "Breastplate 14 + DEX +1 + +1 [manual adjustment]"},
  "initiative": {"bonus": 6, "provenance": "DEX +1 + 5 [bonus:initiative]"},
  "hp": {"current": 51, "max": 51, "provenance": "base 30 + CON +2×7 + 7 [per-level bonuses]"},
  "stance": {"main_hand": "Night Rapier", "off_hand": "Boot Knife (off hand)",
             "ac_states": {"current": 16,
                           "shield raised (+2)": {"ac": 18, "cost": "requires the off hand"}}},
  ...
 },
 "unhandled": {"modifier_patterns": ["munch:cookies"]},
 "lint": []
}
```

## For agents

- **`tool.json`** at the repo root and **`charactercheck --schema`** describe the full I/O contract.
- **`--pipe`** reads refs from stdin for batch runs.
- **MCP server**: `charactercheck-mcp` (stdio) exposes `derive`, `stance`, `qa`, `report`.
- Every derived number carries a **provenance string** — the arithmetic that produced it — so a downstream agent (or a suspicious player) can audit any value without re-deriving it.

```console
$ charactercheck stance <ref>    # what's in each hand, AC states with costs
$ charactercheck seatpack <ref>  # everything a seat needs before a session
$ charactercheck report <ref>    # ONLY the honesty lanes — resolve these before play
$ charactercheck qa <ref>        # the 100-question pass, per-question OK/PARTIAL/NO
$ charactercheck diff <ref> --baseline intake.json   # what the player changed mid-session
```

> **Why this matters, from a real table:** an agent was handed a D&D Beyond
> link and reported *"D&D Beyond is showing me the signed-out shell, not the
> sheet stats"* — then played a whole session rolling flat d20s with no
> modifiers, while the GM hand-derived her numbers and **got them wrong twice**
> (a throwaway script matched `wis-score`; D&D Beyond calls it
> `wisdom-score`, silently dropping a feat's +2 WIS). `charactercheck derive`
> gets that sheet right in one command. Hand-derivation is the bug this product
> exists to delete.

## Why provenance and refusal, not just numbers

A character sheet is a mix of derivable core-rules content and everything else — homebrew, legacy-edition options, manual overrides someone typed in three campaigns ago. Tools that guess produce confident wrong numbers; at a real table those become wrong rulings. charactercheck's contract:

1. **Derived** values carry their arithmetic (`AC 17 = Breastplate 14 [equipped] + DEX +1 [medium cap] + 2 [manual adjustment]`).
2. **Unhandled** data is surfaced by name (an unknown modifier pattern, an unrecognized characterValue type) and flips the exit code — your cue to ask the player, not to guess.
3. **Lint** catches sheets that disagree with themselves: nothing flagged equipped, stale damage, a caster with slots and zero prepared spells, gear stashed in a container that was left somewhere else entirely (yes, the container graph is modeled — a chest labeled "stashed @ the docks" stops contributing weight and armor candidates).

## The QA pass

`tests/` ships a 100-question QA suite covering the surface a table actually uses — vitals, saves, all 18 skills, passives, weapons and masteries, spell slots (pact included), resources with used-counts, encumbrance, attunement. CI runs it on synthetic fixtures on every push; the scorecard is generated, never hand-edited. Current: **92 OK / 7 PARTIAL / 1 NO** per fixture-class, with every PARTIAL/NO carrying a named reason in the output.

## What it does NOT do (on purpose)

- **No rules adjudication** — "is this action legal" is a different product ([srdcheck](https://github.com/chaoz23/srdcheck), this project's sibling: srdcheck judges actions, charactercheck derives the actor).
- **No private sheets** — public share links only; this tool will never ask for credentials.
- **No VTT output, no homebrew content database, no character building.**
- **No guessing** — the whole point.

## As a library

```python
from charactercheck import derive, stance, fetch

r = derive("https://www.dndbeyond.com/characters/<id>")
r["combat"]["ac"]              # {'value': 17, 'provenance': 'Breastplate 14 + ...'}
r["unhandled"]                 # what you must resolve by asking a human
stance(fetch("<id>"))          # hands / AC states / attack lines
```

## Credits

- Schema semantics for the D&D Beyond v5 payload were partly informed by reading the source of [MrPrimate/ddb-importer](https://github.com/MrPrimate/ddb-importer) (MIT) — the most complete derivation math in the ecosystem, coupled to FoundryVTT. No code was copied; see `NOTICE`.
- The 100-question QA schema was authored for this project.
- D&D Beyond is a trademark of Wizards of the Coast. charactercheck is unofficial, unaffiliated, and reads only what a character's owner has made public.

<!-- MCP registry ownership marker (do not remove): binds this repo's PyPI package to its registry namespace. -->
mcp-name: io.github.chaoz23/charactercheck


## The settlement quiz (v0.3)

```
charactercheck quiz <ref>
```

Questions the GM asks **out loud** at a ledger-flush boundary, each with the
silently-held expected answer where derivation has authority (AC, HP max,
total slots, attunement — with provenance strings). Live state only the
player tracks (current HP, expended slots) is `expect: null,
authority: "player"` — the engine never estimates. Grade privately, remind
diplomatically; `diff` against the intake snapshot is the reality check.
Unhandled patterns propagate as a caveat naming what the answer key cannot
verify. Unhandled items now also carry the payload's own verbatim `text`
so intake interviews read the source's words, never a paraphrase.


## The seat pack (v0.4)

```
charactercheck seatpack <ref> [--for-dm]
```

Everything a seat needs at session start, in one call: abilities, saves,
skills with proficiency flags, passives, DCs, combat block, resources,
inventory, **vision** (species darkvision plus Devil's Sight-class features,
with provenance — born from a live table where a DM narrated a warlock blind),
and a persona section carrying the sheet's own trait/ideal/bond/flaw text
verbatim with an explicit `not_derivable` list: charactercheck never invents
personality. `--for-dm` redacts player-authority live state per the
settlement contract.
