"""charactercheck MCP server (stdio, stdlib-only).

Tools: derive, stance, qa, report — same engine as the CLI.
Run: charactercheck-mcp  (or: python -m charactercheck.mcp)
"""
import json
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
    {"name": "report", "description":
        "Only the honesty lanes: unhandled data patterns + lint + identified feats — "
        "what a table must resolve before play.",
     "inputSchema": {"type": "object", "properties": {
         "ref": {"type": "string"}}, "required": ["ref"]}},
]


def _call(name, args):
    ref = args["ref"]
    if name == "derive":
        return derive(ref)
    if name == "stance":
        return engine.stance(engine.fetch(ref))
    if name == "qa":
        text, counts = qa.report(ref, full=args.get("full", False))
        return {"scorecard": {"ok": counts[0], "partial": counts[1], "no": counts[2]},
                "text": text}
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
                    "serverInfo": {"name": "charactercheck", "version": "0.2.0"}}
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
