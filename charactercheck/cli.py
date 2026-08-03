"""Read-only CharacterCheck CLI. --pipe reads refs from stdin."""
import argparse
import json
import secrets
import sys

from . import derive, engine, errors, qa
from .table_evaluation import input_digest, project_table_error, project_table_evaluation


def _json(value):
    """Render strict JSON; non-finite output is never serialized."""
    return json.dumps(value, indent=1, allow_nan=False)

SCHEMA = {
    "name": "charactercheck",
    "commands": {
        "derive": "selected derived character fields (JSON) with provenance, canonical assessments, unhandled content, and lint",
        "stance": "pre-combat context with canonical assessment; observed equipment state requires confirmation",
        "qa": "run the 100-question coverage inventory (--full for all rows)",
        "report": "canonical trust/field assessments plus unhandled and lint findings",
        "intake": "one pre-session packet: supported-coverage state, questions to resolve before dice, unsupported content, player-authority fields, baseline-snapshot hint",
  "doctor": "diagnose python / DNS / outbound HTTPS / character reachability; remedy on the first failing check",
  "selftest": "check the offline installation against a bundled sample — no network, no account, no character required",
        "seatpack": "read-only character context; persona is omitted unless explicitly requested locally",
        "quiz": "settlement and finding questions; expected values appear only for trusted fields",
        "snapshot": "export CharacterSnapshotV1 for deterministic replay and diff",
        "diff": "classify supported changes from a CharacterSnapshotV1 baseline",
    },
    "input": "CLI/library: an exact public D&D Beyond character URL, bare id, or direct regular-file path; MCP: URL or id only",
    "exit_codes": {
        "0": "command succeeded with no command-specific finding/change status",
        "1": ("derive/report lint-only, diff named change or indeterminate "
              "comparison, or selftest failure"),
        "2": "unsupported content is present; inspect field states before use",
        "3": "input, retrieval, validation, or internal failure; read the action field",
    },
    "command_exit_contracts": {
        "derive/report": ("0 no lint/unhandled; 1 lint with no unhandled; "
                          "2 one or more unhandled records; 3 structured failure"),
        "diff": ("0 complete comparison with no detected change; 1 any named "
                 "change or indeterminate omitted-source/restriction comparison; "
                 "3 structured failure"),
        "stance/qa/snapshot/quiz/seatpack/intake": (
            "0 when emitted even if fields/findings require attention; "
            "3 structured failure"),
        "selftest": "0 pass; 1 fail",
        "doctor": "0 all checks pass; 3 otherwise",
        "usage": ("argparse errors are plain text and exit 2; unsupported "
                  "command-specific flag combinations are "
                  "structured and exit 2"),
    },
    "errors": {
        "note": ("Known failures use stable structured errors. Unexpected failures "
                 "are redacted and carry a correlation id. CharacterCheck never asks "
                 "for credentials."),
        "kinds": list(errors.PUBLIC_ERROR_KINDS),
    },
    "table_evaluation": {
        "flag": "--table-evaluation on derive/report",
        "schema_version": "table.evaluation/1.0",
        "authority_status": "self_attested",
        "privacy": "field assessments and digests only; no character values",
        "exit_codes": "0 checked_clean; 1 complete with advisories/findings; 2 refused",
    },
}


def _exit_code(result):
    if result.get("unhandled", {}).get("items"):
        return 2
    if result.get("lint"):
        return 1
    return 0


from . import __version__


def main(argv=None):
    ap = argparse.ArgumentParser(prog="charactercheck", description=__doc__)
    ap.add_argument("command", nargs="?",
                    choices=["derive", "stance", "qa", "report", "snapshot", "diff", "quiz", "seatpack", "intake", "doctor", "selftest"], default="derive")
    ap.add_argument("ref", nargs="?", help="DDB character URL / id / JSON file")
    ap.add_argument("--full", action="store_true", help="qa: print all 100 coverage rows")
    ap.add_argument("--pipe", action="store_true", help="read refs from stdin, one per line")
    ap.add_argument("--for-dm", action="store_true",
                    help="seatpack/intake: redact player-authority live state")
    ap.add_argument("--include-persona", action="store_true",
                    help="local seatpack/intake/snapshot only: include untrusted persona text")
    ap.add_argument("--baseline", help="diff: the CharacterSnapshotV1 JSON to compare against")
    ap.add_argument("--version", action="version", version=f"charactercheck {__version__}")
    ap.add_argument("--brief", action="store_true", help="derive/report: chat-sized summary")
    ap.add_argument("--json", dest="json_out", action="store_true", help="doctor: machine-readable output")
    ap.add_argument("--schema", action="store_true", help="print the I/O contract and exit")
    ap.add_argument("--table-evaluation", action="store_true",
                    help="derive/report: emit a self-attested table.evaluation/1.0 envelope")
    a = ap.parse_args(argv)

    if a.schema:
        print(_json(SCHEMA))
        return 0

    if a.table_evaluation and a.brief:
        print(_json({
            "ok": False,
            "error": "bad_flag",
            "message": "--brief and --table-evaluation are mutually exclusive.",
            "action": "Drop --brief when requesting the shared JSON envelope.",
            "retryable": False,
            "exit_code": 2,
        }), file=sys.stderr)
        return 2

    flag_contract = (
        (a.brief, "--brief", {"derive", "report"},
         "Use --brief with `derive` or `report`, or drop it."),
        (a.include_persona, "--include-persona",
         {"seatpack", "intake", "snapshot"},
         "Use it only with seatpack, intake, or snapshot."),
        (a.for_dm, "--for-dm", {"seatpack", "intake"},
         "Use it only with seatpack or intake."),
        (a.full, "--full", {"qa"}, "Use it only with qa."),
        (bool(a.baseline), "--baseline", {"diff"}, "Use it only with diff."),
        (a.json_out, "--json", {"doctor"}, "Use it only with doctor."),
        (a.table_evaluation, "--table-evaluation", {"derive", "report"},
         "Use it only with derive or report."),
        (a.pipe, "--pipe",
         {"derive", "stance", "qa", "report", "snapshot", "diff", "quiz",
          "seatpack", "intake"},
         "Use it only with a character projection command."),
    )
    for enabled, flag, allowed, action in flag_contract:
        if enabled and a.command not in allowed:
            print(_json({
                "ok": False,
                "error": "bad_flag",
                "message": f"{flag} is not supported by '{a.command}'.",
                "action": action,
                "retryable": False,
                "exit_code": 2,
            }), file=sys.stderr)
            return 2

    if a.command == "selftest":
        ok, lines = errors.selftest()
        print("\n".join(lines))
        return 0 if ok else 1

    if a.command == "doctor":
        res = errors.doctor(a.ref)
        print(errors.render_doctor(res) if not a.json_out else _json(res))
        return 0 if res["ok"] else errors.EXIT_FETCH

    refs = [l.strip() for l in sys.stdin if l.strip()] if a.pipe else [a.ref]
    if not refs or refs == [None]:
        ap.error("a character ref is required (or --pipe/--schema)")
    code = 0
    for ref in refs:
      try:
          if a.command == "derive":
              r = derive(ref)
              if a.table_evaluation:
                  out = project_table_evaluation(r)
                  print(_json(out))
                  code = max(code, out["exit_code"])
              else:
                  print(engine.render_brief(r) if a.brief else _json(r))
                  code = max(code, _exit_code(r))
          elif a.command == "intake":
              print(_json(engine.intake(ref, for_dm=a.for_dm,
                                        include_persona=a.include_persona)))
          elif a.command == "stance":
              print(_json(engine.stance(ref)))
          elif a.command == "qa":
              text, _ = qa.report(ref, full=a.full)
              print(text)
          elif a.command == "diff":
              if not a.baseline:
                  ap.error("diff requires --baseline <character-snapshot.json>")
              old_snapshot = engine.source.load_snapshot(a.baseline)
              loaded = engine.fetch_loaded(ref)
              d = engine.diff_snapshots(
                  old_snapshot,
                  engine.source.make_snapshot(loaded, include_persona=False))
              print(_json(d))
              code = max(code, 1 if d["meta"]["changes_present"] else 0)
          elif a.command == "snapshot":
              print(_json(engine.snapshot(ref,
                                          include_persona=a.include_persona)))
          elif a.command == "seatpack":
              print(_json(engine.seatpack(ref, for_dm=a.for_dm,
                                          include_persona=a.include_persona)))
          elif a.command == "quiz":
              print(_json(engine.quiz(ref)))
          elif a.command == "report":
              r = derive(ref)
              if a.table_evaluation:
                  out = project_table_evaluation(r)
                  print(_json(out))
                  code = max(code, out["exit_code"])
                  continue
              if a.brief:
                  print(engine.render_report_brief(r))
                  code = max(code, _exit_code(r))
                  continue
              out = engine.report_projection(r)
              print(_json(out))
              code = max(code, _exit_code(r))
      except errors.CharacterCheckError as e:
          # Structured, actionable, and on stdout so a piping agent
          # sees it. Never a traceback: see charactercheck/errors.py.
          if a.table_evaluation:
              out = project_table_error(e.as_dict(), input_digest(ref))
              print(_json(out))
              code = max(code, out["exit_code"])
          else:
              print(_json(e.as_dict()))
              code = max(code, e.exit_code)
      except Exception as exc:  # noqa: BLE001 - redact at the process boundary
          correlation_id = secrets.token_hex(8)
          print(f"charactercheck internal_error correlation_id={correlation_id} "
                f"exception={type(exc).__name__}", file=sys.stderr)
          e = errors.internal_error(correlation_id)
          if a.table_evaluation:
              out = project_table_error(e.as_dict(), input_digest(ref))
              print(_json(out))
              code = max(code, out["exit_code"])
          else:
              print(_json(e.as_dict()))
              code = max(code, e.exit_code)
    return code


if __name__ == "__main__":
    sys.exit(main())
