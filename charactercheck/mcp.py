"""charactercheck MCP server (stdio, stdlib-only).

Tools: derive, stance, qa, report — same engine as the CLI.
Run: charactercheck-mcp  (or: python -m charactercheck.mcp)
"""
import json

from . import __version__
from . import errors
import sys

from . import derive, engine, qa

TOOLS = [
    {"name": "derive", "description":
        "Derive a D&D Beyond character deterministically: abilities, saves, skills, "
        "AC/HP/initiative with provenance strings, weapons, spellcasting, resources, "
        "inventory — plus 'unhandled' (data patterns not modeled, named) and 'lint' "
        "(sheet inconsistencies). Input: public DDB character URL or id.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string", "description": "DDB character URL or id"}},
         "required": ["ref"]}},
    {"name": "stance", "description":
        "Pre-combat stance: what is in each hand, AC states with their costs "
        "(e.g. 'shield raised: 19 — costs the off hand'), readied and stowed weapons.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"}}, "required": ["ref"]}},
    {"name": "qa", "description":
        "Run the 100-question character-sheet QA pass; per-question OK/PARTIAL/NO.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"}, "full": {"type": "boolean"}}, "required": ["ref"]}},
    {"name": "diff", "description":
        "Classify deltas between an intake snapshot and the live sheet — the DDB "
        "sheet is a live state store players edit during play. Lanes: state_changes "
        "(engine's authority), build_changes (player's declaration channel), lint "
        "(impossible edits), unhandled_new (new unmodeled content).",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"}, "baseline_path": {"type": "string"}},
         "required": ["ref", "baseline_path"]}},
    {"name": "seatpack", "description":
        "Everything a seat needs at session start: abilities, saves, skills, passives, DCs, combat block, resources, inventory, vision features (incl. Devil's Sight-class invocations), and verbatim sheet persona with an explicit not_derivable list. for_dm=true redacts player-authority live state.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}, "for_dm": {"type": "boolean"}},
                     "required": ["ref"]}},
    {"name": "quiz", "description":
        "Settlement quiz for a character: questions the GM asks out loud plus the silent expected answers; player-authority live state (current HP, expended slots) is null by contract.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}},
                     "required": ["ref"]}},
    {"name": "report", "description":
        "Only the honesty lanes: unhandled data patterns + lint + identified feats — "
        "what a table must resolve before play.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"}}, "required": ["ref"]}},
    {"name": "intake", "description":
        "One pre-session packet: which stat families are settled, the exact questions to "
        "resolve before dice (each with the family it unblocks), unsupported content, the "
        "fields that are the player's to declare, and a baseline-snapshot hint. Probably the "
        "most useful single call for an agent taking a seat.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"},
         "for_dm": {"type": "boolean",
                    "description": "redact player-authority live state"}},
         "required": ["ref"]}},
    {"name": "selftest", "description":
        "Prove the engine works offline against a bundled sample character — no network, no "
        "D&D Beyond account, no character required. Run this first when bootstrapping: it "
        "separates 'the tool is broken' from 'I cannot reach that character'.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "doctor", "description":
        "Diagnose why it is not working: python, DNS, outbound HTTPS, and (with a ref) "
        "reachability of that character. Each check reports PASS/FAIL and the first failure "
        "carries the remedy.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}}}},
]


def _call(name, args):
    # These three are the bootstrap surface and do not all require a ref, so
    # they are handled before the ref lookup that every other tool needs.
    if name == "selftest":
        ok, lines = errors.selftest()
        return {"ok": ok, "report": "\n".join(lines)}
    if name == "doctor":
        return errors.doctor(args.get("ref"))
    if name == "intake":
        return engine.intake(args["ref"], for_dm=bool(args.get("for_dm")))

    ref = args["ref"]
    if name == "derive":
        return derive(ref)
    if name == "stance":
        return engine.stance(engine.fetch(ref))
    if name == "qa":
        text, counts = qa.report(ref, full=args.get("full", False))
        return {"scorecard": {"ok": counts[0], "partial": counts[1], "no": counts[2]},
                "text": text}
    if name == "seatpack":
        return engine.seatpack(ref, for_dm=bool(args.get("for_dm")))
    if name == "quiz":
        return engine.quiz(ref)
    if name == "diff":
        return engine.diff_payloads(engine.fetch(args["baseline_path"]),
                                    engine.fetch(ref))
    if name == "report":
        r = derive(ref)
        return {"unhandled": r["unhandled"], "lint": r["lint"],
                "feats_identified": r["feats_identified"]}
    raise ValueError(f"unknown tool {name}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        method = req.get("method")
        resp = {"jsonrpc": "2.0", "id": rid}
        try:
            if method == "initialize":
                resp["result"] = {
                    "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "charactercheck", "version": __version__}}
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                resp["result"] = {"tools": TOOLS}
            elif method == "tools/call":
                p = req.get("params", {})
                out = _call(p.get("name"), p.get("arguments") or {})
                resp["result"] = {"content": [{"type": "text",
                                               "text": json.dumps(out, indent=1)}],
                                  "structuredContent": out if isinstance(out, dict) else None}
            else:
                if rid is None:
                    continue
                resp["error"] = {"code": -32601, "message": f"method not found: {method}"}
        except Exception as e:  # noqa: BLE001 — surface as tool error, keep serving
            resp["error"] = {"code": -32000, "message": str(e)}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
