# AGENTS.md — if you are an agent, start here

You were probably handed this repo URL and told to use it. This page is the
whole job. It is short on purpose.

## 1. Prove the tool works (no network, no account, no character)

```bash
python3 -m charactercheck selftest      # from a clone, no install needed
```

Every line PASS means the derivation engine is fine. **Do this first.** It
separates *"the tool is broken"* from *"I cannot reach that character"*, which
look identical from the outside and are the two things you will actually hit.

## 2. Derive a character

```bash
python3 -m charactercheck derive https://www.dndbeyond.com/characters/<id>
```

Also accepts a bare id, or a path to a saved character-service JSON file.

If you want a real one to try, this character is public and kept that way as
this project's worked example — she exercises all three trust lanes at once, so
the output is worth reading:

```bash
python3 -m charactercheck derive https://www.dndbeyond.com/characters/150991647 --brief
```

**The deliberate negative case:** she carries one homebrew feat **outside the
SRD**, and that is on purpose — it is what produces the `unsupported` lane. If
every example were clean you would never see what the tool does when it meets
content it cannot model, which is most real sheets.

And if you would rather not touch the network, there is one in the box:

```bash
python3 -m charactercheck derive examples/sample-character.json
```

## 3. Read the exit code before you read the output

| exit | meaning | do this |
|---|---|---|
| **0** | derived clean | use the output |
| **1** | lint findings — the sheet disagrees with itself | **output is usable**; raise `lint[]` with the player |
| **2** | unhandled content present | **NOT a failure. Output is complete and usable.** Resolve the named `unhandled` items with a human. Do not retry — retrying changes nothing |
| **3** | could not retrieve the sheet | read `action` in the JSON and do what it says |

**The most common mistake an agent makes here is treating exit 2 as failure.**
It is not. It means "here is your answer, and here is the one thing about it I
could not model."

## 4. When something fails

Every failure prints JSON with a stable `error` kind and a one-sentence
`action`. There is never a traceback. If you are stuck:

```bash
python3 -m charactercheck doctor <ref>       # add --json for machine output
```

It checks python, DNS, outbound HTTPS, and that specific character, and puts
the remedy on the first failing line.

**Private character?** This tool never asks for credentials, so there are
exactly two answers: set *Character Privacy* to Public on D&D Beyond, or save
the character-service JSON and pass the file path — which needs no permissions
at all.

## 5. Route on the trust map, not on vibes

`derive` returns a `trust` block. Read it before stating anything:

- **`trusted`** — safe to state.
- **`ask_player`** — derived but in doubt. The question that resolves it is in
  `asks`; ask it rather than guessing.
- **`unsupported`** — the engine saw something it does not model targeting this
  family. Say what is missing. Unsupported content was **never applied**, so
  everything else is unaffected by it.

`charactercheck derive <ref> --brief` prints the same thing chat-sized. Prefer
it over summarising the JSON yourself — your summary can drift, this cannot.

`charactercheck intake <ref>` gives one pre-session packet: what is settled,
what must be asked before dice, and which fields are the player's to declare.

## 6. Trust the provenance, not the number

Every derived value carries the arithmetic that produced it:

```json
"ac": {"value": 16, "provenance": "Breastplate 14 + DEX +1 + +1 [manual adjustment]"}
```

If you are about to state a number to a human, you can state why. If a value
matters and `unhandled` lists something under `possibly_affects`, say so rather
than asserting.

## 7. Do not re-derive by hand

If you are tempted to parse the D&D Beyond payload yourself: don't. The
modifier subTypes are full words (`wisdom-score`, not `wis-score`), item
modifiers are gated on attunement and equipped state, and missing one silently
drops a feat or a magic item. That exact mistake was made by the author of this
tool, at a live table, twice in one evening — announcing a wrong Perception
bonus and then "correcting" a right answer to a wrong one. The tool exists to
delete that class of bug.

## Machine-readable surfaces

- `tool.json` — command surface, exit codes, error kinds
- `charactercheck --schema` — the I/O contract
- `llms.txt` — a short prose summary for retrieval
- MCP: `charactercheck-mcp` over stdio exposes `derive`, `stance`, `qa`, `report`

## What this tool will not do

No rules adjudication (that is [srdcheck](https://github.com/chaoz23/srdcheck)).
No credentials, cookies, or browser automation, ever. No character building. No
guessing — unrecognised data is reported, never silently defaulted.
