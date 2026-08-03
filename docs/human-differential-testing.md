# Human differential testing

Use this protocol to learn D&D Beyond state semantics without treating one
sheet, one UI label, or one parser output as a general rule. Use a disposable,
publicly shared test character whose owner explicitly agreed to the test. Do
not publish the resulting snapshots: they contain minimized mechanical
character data even though account, persona, notes, images, and prose are
removed by default.

## A → B → A protocol

1. Write one falsifiable hypothesis and the single UI mutation that tests it.
2. Capture baseline **A** without changing anything else:

   ```console
   python3 -m charactercheck snapshot CHARACTER_REF > a.json
   ```

3. Make exactly one UI change and record what the human sees, without using
   CharacterCheck's prediction as the answer.
4. Capture **B**, then compare it with **A**:

   ```console
   python3 -m charactercheck snapshot CHARACTER_REF > b.json
   python3 -m charactercheck diff CHARACTER_REF --baseline a.json
   ```

5. Reverse the UI change, capture **A2**, and prove the mechanical revision
   returns to the baseline:

   ```console
   python3 -m charactercheck snapshot CHARACTER_REF > a2.json
   python3 -m charactercheck diff CHARACTER_REF --baseline a.json
   ```

6. Record only minimized changed paths, the human-observed result, and the
   CharacterCheck finding/trust transition. Delete working snapshots on the
   agreed schedule.

An omitted-source comparison can be `indeterminate` while still naming known
changes. That is evidence about the adapter boundary, not permission to call
the mutation understood.

## Confidence ladder

- **Observed:** one A → B change produced a plausible source delta.
- **Reversible:** B → A2 restored the exact mechanical revision.
- **Replicated:** the same mapping held on a second independently built sheet.
- **Production-guarded:** a privacy-minimized synthetic fixture, negative case,
  and trust-monotonicity regression ship in CI.

Only production-guarded mappings may make a family `trusted`. Human statements
remain evidence, not parser defaults.

## First corpus

| Sheet | Single-variable trials | Primary issues |
| --- | --- | --- |
| 2024 Fighter 3–5 | selected mastery; mastered/non-mastered weapon; equip flips; shield; two-handed/offhand | COMBAT-001 |
| 2014 prepared caster | prepared/unprepared; legacy markers; class spell source | RULES-001, CAST-001 |
| Paladin/Warlock | standard and Pact slot use/restoration; source-specific spells | SLOT-001, CAST-001 |
| Class + species + feat caster | always-prepared, known, and prepared spells from three sources | CAST-001 |
| Magic-item user | carried/stashed/equipped/attuned/charges/granted spell | MOD-001, AC-001 |
| Homebrew/manual override | AC, ability, speed, attack, and resource overrides one at a time | MOD-001, TEST-001 |

Do not change species, subclass, or several builder choices on a live campaign
character merely to obtain a diff. Those tests belong on disposable sheets.

## Human comprehension round

After parser differentials pass, give `report --brief`, `intake`, and the
value-free table-evaluation projection to a GM or agent without the answer
key. Measure whether they:

- distinguish trusted-within-coverage from complete or rules-legal;
- ask the supplied confirmation question instead of guessing;
- decline unsupported/unknown values;
- recognize mutable player/session authority;
- recover after a correction without retaining the old state.

Score parser correctness, agent behavior, and human comprehension separately.
