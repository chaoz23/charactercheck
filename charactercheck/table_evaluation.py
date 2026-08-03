"""Project CharacterCheck observations into ``table.evaluation/1.0``.

The projection contains assessments and digests, never character values.  It
remains self-attested and cannot promote source, player, or rules-engine data
into encounter, session, or action authority.
"""

import hashlib
import json

from . import __version__


TABLE_EVALUATION_SCHEMA_VERSION = "table.evaluation/1.0"
_INVALID_ERRORS = {
    "bad_ref", "bad_json", "invalid_character", "input_too_large",
    "input_too_deep", "input_limit", "cyclic_reference", "file_policy",
    "snapshot_schema", "snapshot_integrity", "snapshot_required",
    "snapshot_source_mismatch",
}
_UNSUPPORTED_ERRORS = {
    "local_files_disabled", "persona_requires_local", "output_too_large",
}


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def input_digest(ref):
    """Bind an error result to an input without disclosing the reference."""
    return _digest({"command": "derive", "ref": str(ref)})


def _policy(meta):
    value = {
        "rules_profile": meta.get("rules_profile"),
        "adapter_registry_fingerprint": meta.get("adapter_registry_fingerprint"),
        "source_schema_fingerprint": meta.get("source_schema_fingerprint"),
        "authority_boundary": meta.get("authority_boundary"),
    }
    return value, _digest(value)


def _diagnostic(code, message, pointer=None, refs=()):
    result = {"code": str(code)[:256], "message": str(message)}
    if pointer is not None:
        result["pointer"] = str(pointer)
    if refs:
        result["evidence_refs"] = list(dict.fromkeys(refs))
    return result


def _finding(field_id, field, policy, policy_digest):
    evidence = list(dict.fromkeys(
        [field_id] + [str(item) for item in field.get("findings") or []]))
    material = {"field": field_id, "state": field.get("state"),
                "authority": field.get("authority"), "evidence": evidence}
    return {
        "finding_id": "charactercheck-" + _digest(material).split(":", 1)[1][:40],
        "code": "charactercheck.player_authority",
        "severity": "advisory",
        "summary": "%s requires player or session-host reconciliation" % field_id,
        "evidence_refs": evidence,
        "effective_policy": dict(policy, field=field_id,
                                 field_state=field.get("state"),
                                 field_authority=field.get("authority")),
        "policy_version": str(policy.get("rules_profile") or "unknown"),
        "policy_digest": policy_digest,
    }


def project_table_evaluation(report):
    """Return a deterministic, value-free shared evaluation envelope."""
    if not isinstance(report, dict) or not isinstance(report.get("fields"), dict):
        return project_table_error({
            "error": "internal_error",
            "message": "CharacterCheck returned an incoherent derived report.",
        }, _digest({"report": "incoherent"}))

    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    revision = meta.get("source_revision")
    if not (isinstance(revision, str) and revision.startswith("sha256:")
            and len(revision) == 71):
        return project_table_error({
            "error": "internal_error",
            "message": "CharacterCheck report lacks a canonical source revision.",
        }, _digest({"report": "missing-source-revision"}))

    policy, policy_digest = _policy(meta)
    evaluators = []
    errors = []
    advisories = []
    blocking_confirm = 0
    state_counts = {name: 0 for name in (
        "trusted", "confirm", "unsupported", "unknown", "invalid",
        "not_applicable")}

    for field_id, field in sorted(report["fields"].items()):
        if not isinstance(field, dict):
            state, reasons = "invalid", ["field_assessment_invalid"]
            authority = None
        else:
            state = field.get("state")
            reasons = [str(item) for item in field.get("findings") or []]
            authority = field.get("authority")
        if state not in state_counts:
            state, reasons = "invalid", ["field_state_invalid"]
        state_counts[state] += 1

        mutable = (state == "confirm" and authority == "player"
                   and reasons and all(item.startswith("mutable_") for item in reasons))
        if state == "trusted":
            evaluator_status, eligible, evaluated, skipped = "evaluated", 1, 1, 0
            skip_reasons = []
            required = True
        elif state == "not_applicable" or mutable:
            evaluator_status, eligible, evaluated, skipped = "not_applicable", 0, 0, 0
            skip_reasons = []
            required = False
            if mutable:
                advisories.append(_finding(field_id, field, policy, policy_digest))
        else:
            if state == "confirm":
                blocking_confirm += 1
            evaluator_status, eligible, evaluated, skipped = (
                "error" if state == "invalid" else "skipped", 1, 0, 1)
            skip_reasons = [_diagnostic(
                "charactercheck.%s" % state,
                "%s is %s and must not be used as trusted character context" %
                (field_id, state), pointer=field_id,
                refs=[field_id] + reasons)]
            errors.extend(skip_reasons)
            required = True
        evaluators.append({
            "id": field_id, "required": required, "status": evaluator_status,
            "eligible": eligible, "evaluated": evaluated, "skipped": skipped,
            "skip_reasons": skip_reasons,
        })

    if state_counts["invalid"]:
        status = "invalid"
    elif state_counts["unknown"]:
        status = "incomplete"
    elif state_counts["unsupported"]:
        status = "unsupported"
    elif blocking_confirm:
        status = "incomplete"
    elif advisories:
        status = "checked_with_advisories"
    else:
        status = "checked_clean"
    complete = status in {"checked_clean", "checked_with_advisories"}
    eligible = sum(item["eligible"] for item in evaluators)
    evaluated = sum(item["evaluated"] for item in evaluators)
    skipped = sum(item["skipped"] for item in evaluators)
    assessment = {
        field_id: {
            "state": field.get("state"), "authority": field.get("authority"),
            "findings": list(field.get("findings") or []),
        }
        for field_id, field in sorted(report["fields"].items())
        if isinstance(field, dict)
    }
    result = {
        "schema_version": TABLE_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": "charactercheck-" + _digest({
            "version": __version__, "revision": revision,
            "assessment": assessment, "policy_digest": policy_digest,
        }).split(":", 1)[1][:40],
        "tool": {"name": "charactercheck", "version": __version__},
        "subject": {
            "kind": "character",
            "id": "character-" + revision.split(":", 1)[1][:40],
            "session_id": None,
            "entity_refs": [],
        },
        "status": status,
        "exit_code": 0 if status == "checked_clean" else (1 if complete else 2),
        "authority_status": "self_attested",
        "coverage": {
            "complete": complete, "evidence_required": True,
            "input": len(evaluators), "compatible": len(evaluators),
            "eligible": eligible, "evaluated": evaluated, "skipped": skipped,
            "evaluators": evaluators,
        },
        "cursor": {"checked_through_event_id": None,
                   "gap_state": "none" if complete else "unknown",
                   "input_digest": revision},
        "context": {"roster_digest": None, "policy_digest": policy_digest,
                    "config_digest": None, "source_set_digest": revision,
                    "session_descriptor_digest": None},
        "findings": [],
        "advisories": advisories,
        "warnings": [],
        "errors": errors,
    }
    return result


def project_table_error(error, digest):
    """Map a public CharacterCheck failure into a privacy-safe refusal."""
    kind = error.get("error") if isinstance(error, dict) else "internal_error"
    message = (error.get("message") if isinstance(error, dict) else None)
    if kind == "internal_error":
        status = "internal_error"
    elif kind in _INVALID_ERRORS:
        status = "invalid"
    elif kind in _UNSUPPORTED_ERRORS:
        status = "unsupported"
    else:
        status = "incomplete"
    diagnostic = _diagnostic("charactercheck.%s" % kind,
                             message or "CharacterCheck could not derive the character")
    material = {"version": __version__, "input_digest": digest, "error": kind}
    return {
        "schema_version": TABLE_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": "charactercheck-" + _digest(material).split(":", 1)[1][:40],
        "tool": {"name": "charactercheck", "version": __version__},
        "subject": {"kind": "character",
                    "id": "character-input-" + digest.split(":", 1)[1][:40],
                    "session_id": None, "entity_refs": []},
        "status": status, "exit_code": 2,
        "authority_status": "self_attested",
        "coverage": {
            "complete": False, "evidence_required": True,
            "input": 1, "compatible": 0, "eligible": 0,
            "evaluated": 0, "skipped": 0,
            "evaluators": [{
                "id": "character-derivation", "required": True,
                "status": "error", "eligible": 0, "evaluated": 0,
                "skipped": 0, "skip_reasons": [diagnostic],
            }],
        },
        "cursor": {"checked_through_event_id": None, "gap_state": "unknown",
                   "input_digest": digest},
        "context": {"roster_digest": None, "policy_digest": None,
                    "config_digest": None, "source_set_digest": None,
                    "session_descriptor_digest": None},
        "findings": [], "advisories": [], "warnings": [],
        "errors": [diagnostic],
    }
