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
  "intake": "one pre-session packet: settled families, the questions to resolve before dice, unsupported content, player-authority fields, baseline-snapshot hint",
  "doctor": "diagnose python / DNS / outbound HTTPS / character reachability; remedy on the first failing check",
  "selftest": "prove the engine works offline against a bundled sample — no network, no account, no character required",
        "seatpack": "everything a seat needs at session start: stats, saves, skills, passives, DCs, features, vision, verbatim persona (--for-dm redacts player-authority state)",
        "quiz": "settlement quiz: questions to ask out loud + the silent answer key (player-authority fields stay null)",
        "diff": "classify every delta between a baseline snapshot and the live sheet",
    },
    "input": "a public D&D Beyond character URL, id, or a saved character-service v5 JSON file",
    "exit_codes": {
        "0": "derived clean",
        "1": "lint findings — the sheet disagrees with itself; output still usable",
        "2": "unhandled content present — NOT a failure; output complete and usable",
        "3": "could not retrieve the sheet — read the 'action' field in the JSON",
    },
    "errors": {
        "note": ("Exit 3 prints structured JSON with a stable 'error' kind and a "
                 "one-sentence 'action'. Never a traceback. charactercheck never "
                 "asks for credentials."),
        "kinds": ["not_public", "not_found", "bad_ref", "network",
                  "rate_limited", "bad_json", "upstream"],
    },
}


def _exit_code(result):
    if result.get("unhandled", {}).get("items"):
        return 2
    if result.get("lint"):
        return 1
    return 0


from . import errors
from . import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="charactercheck", description=__doc__)
    ap.add_argument("command", nargs="?",
                    choices=["derive", "stance", "qa", "report", "diff", "quiz", "seatpack", "intake", "doctor", "selftest"], default="derive")
    ap.add_argument("ref", nargs="?", help="DDB character URL / id / JSON file")
    ap.add_argument("--full", action="store_true", help="qa: print all 100 rows")
    ap.add_argument("--pipe", action="store_true", help="read refs from stdin, one per line")
    ap.add_argument("--for-dm", action="store_true", help="seatpack: redact player-authority live state")
    ap.add_argument("--baseline", help="diff: the intake snapshot JSON to compare against")
    ap.add_argument("--version", action="version", version=f"charactercheck {__version__}")
    ap.add_argument("--brief", action="store_true", help="derive: chat-sized deterministic summary")
    ap.add_argument("--json", dest="json_out", action="store_true", help="doctor: machine-readable output")
    ap.add_argument("--schema", action="store_true", help="print the I/O contract and exit")
    a = ap.parse_args(argv)

    if a.schema:
        print(json.dumps(SCHEMA, indent=1))
        return 0
    if a.command == "selftest":
        ok, lines = errors.selftest()
        print("\n".join(lines))
        return 0 if ok else 1

    if a.command == "doctor":
        res = errors.doctor(a.ref)
        print(errors.render_doctor(res) if not a.json_out else json.dumps(res, indent=1))
        return 0 if res["ok"] else errors.EXIT_FETCH

    refs = [l.strip() for l in sys.stdin if l.strip()] if a.pipe else [a.ref]
    if not refs or refs == [None]:
        ap.error("a character ref is required (or --pipe/--schema)")
    if a.brief and a.command not in ("derive", "report"):
        print(json.dumps({"ok": False, "error": "bad_flag",
                          "message": f"--brief is not supported by '{a.command}'.",
                          "action": "Use --brief with `derive` or `report`, or drop it.",
                          "exit_code": 2}, indent=1), file=sys.stderr)
        return 2

    code = 0
    for ref in refs:
      try:
          if a.command == "derive":
              r = derive(ref)
              print(engine.render_brief(r) if a.brief else json.dumps(r, indent=1))
              code = max(code, _exit_code(r))
          elif a.command == "intake":
              print(json.dumps(engine.intake(ref, for_dm=a.for_dm), indent=1))
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
          elif a.command == "seatpack":
              print(json.dumps(engine.seatpack(ref, for_dm=a.for_dm), indent=1))
          elif a.command == "quiz":
              print(json.dumps(engine.quiz(ref), indent=1))
          elif a.command == "report":
              r = derive(ref)
              if a.brief:
                  print(engine.render_report_brief(r))
                  code = max(code, _exit_code(r))
                  continue
              out = {"unhandled": r["unhandled"], "lint": r["lint"],
                     "feats_identified": r["feats_identified"],
                     "stashed_elsewhere": r["inventory"]["stashed_elsewhere"]}
              print(json.dumps(out, indent=1))
              code = max(code, _exit_code(r))
      except errors.CharacterCheckError as e:
          # Structured, actionable, and on stdout so a piping agent
          # sees it. Never a traceback: see charactercheck/errors.py.
          print(json.dumps(e.as_dict(), indent=1))
          code = max(code, e.exit_code)
    return code


if __name__ == "__main__":
    sys.exit(main())
