"""charactercheck CLI. Exit codes: 0 = derived clean; 1 = lint findings;
2 = unhandled content present (the honest lane). --pipe reads refs from stdin."""
import argparse
import json
import sys

from . import derive, engine, qa

SCHEMA = {
    "name": "charactercheck",
    "commands": {
        "derive": "full derived character (JSON): abilities, saves, skills, combat, spellcasting, resources, inventory, unhandled, lint",
        "stance": "pre-combat block: hands, AC states with costs, attack lines",
        "qa": "run the 100-question QA pass (--full for all rows)",
        "report": "unhandled + lint only — what a table must resolve before play",
    },
    "input": "a public D&D Beyond character URL, id, or a saved character-service v5 JSON file",
    "exit_codes": {"0": "derived clean", "1": "lint findings present", "2": "unhandled content present"},
}


def _exit_code(result):
    if result.get("unhandled", {}).get("items"):
        return 2
    if result.get("lint"):
        return 1
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="charactercheck", description=__doc__)
    ap.add_argument("command", nargs="?",
                    choices=["derive", "stance", "qa", "report", "diff"], default="derive")
    ap.add_argument("ref", nargs="?", help="DDB character URL / id / JSON file")
    ap.add_argument("--full", action="store_true", help="qa: print all 100 rows")
    ap.add_argument("--pipe", action="store_true", help="read refs from stdin, one per line")
    ap.add_argument("--baseline", help="diff: the intake snapshot JSON to compare against")
    ap.add_argument("--version", action="version", version="charactercheck 0.2.0")
    ap.add_argument("--schema", action="store_true", help="print the I/O contract and exit")
    a = ap.parse_args(argv)

    if a.schema:
        print(json.dumps(SCHEMA, indent=1))
        return 0
    refs = [l.strip() for l in sys.stdin if l.strip()] if a.pipe else [a.ref]
    if not refs or refs == [None]:
        ap.error("a character ref is required (or --pipe/--schema)")
    code = 0
    for ref in refs:
        if a.command == "derive":
            r = derive(ref)
            print(json.dumps(r, indent=1))
            code = max(code, _exit_code(r))
        elif a.command == "stance":
            d = engine.fetch(ref)
            print(json.dumps(engine.stance(d), indent=1))
        elif a.command == "qa":
            text, _ = qa.report(ref, full=a.full)
            print(text)
        elif a.command == "diff":
            if not a.baseline:
                ap.error("diff requires --baseline <intake-snapshot.json>")
            old = engine.fetch(a.baseline)
            new = engine.fetch(ref)
            d = engine.diff_payloads(old, new)
            print(json.dumps(d, indent=1))
            code = max(code, 1 if any(d.values()) else 0)
        elif a.command == "report":
            r = derive(ref)
            out = {"unhandled": r["unhandled"], "lint": r["lint"],
                   "feats_identified": r["feats_identified"],
                   "stashed_elsewhere": r["inventory"]["stashed_elsewhere"]}
            print(json.dumps(out, indent=1))
            code = max(code, _exit_code(r))
    return code


if __name__ == "__main__":
    sys.exit(main())
