"""Failure paths that an agent can act on.

This module exists because of a specific, measured adoption failure. A cold-boot
probe on 2026-07-31 gave a fresh agent the repo URL and the three character refs
an agent actually produces. A public character derived correctly. The other
three — a private sheet, a missing id, a malformed ref — each produced a
fifteen-line Python traceback and **exit code 1**.

Exit 1 is already documented as *"lint findings — the sheet looks
inconsistent."* So a permission error was returning the code that means "this
sheet has inconsistencies". An agent obeying the published contract would read
a private character as a dirty one and carry on confidently. That is worse than
crashing: it is a wrong answer wearing the uniform of a right one.

So every failure here is typed, carries a one-sentence **action**, and exits
**3** — a lane of its own, distinct from lint (1) and unhandled content (2),
both of which still mean "you have usable output".

The other rule this module encodes: **no credentials, ever.** A private sheet
is not a problem to solve with cookies, it is a problem to solve with one
sentence telling the caller how to make it readable. That boundary keeps the
security surface at zero and keeps the support surface small.
"""

#: Failure exits with its own code. 0/1/2 keep their published meanings.
EXIT_FETCH = 3


class CharacterCheckError(Exception):
    """A failure the caller can do something about.

    `kind` is stable and machine-matchable; `action` is the single next thing
    to do, in a sentence, aimed at whoever is reading — human or agent.
    """

    exit_code = EXIT_FETCH

    def __init__(self, kind, message, action, ref=None, detail=None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.action = action
        self.ref = ref
        self.detail = detail

    def as_dict(self):
        d = {"ok": False, "error": self.kind, "message": self.message,
             "action": self.action, "exit_code": self.exit_code}
        if self.ref:
            d["ref"] = self.ref
        if self.detail:
            d["detail"] = self.detail
        return d


def not_public(ref):
    return CharacterCheckError(
        "not_public",
        "D&D Beyond returned 403 Forbidden for this character — it is private "
        "or not shared.",
        "Open the character on D&D Beyond, set Character Privacy to Public, "
        "and retry. If you cannot change it, save the character-service JSON "
        "and pass that file path instead — charactercheck reads a saved file "
        "with no permissions at all, and never asks for credentials.",
        ref=ref)


def not_found(ref):
    return CharacterCheckError(
        "not_found",
        "D&D Beyond returned 404 for this character id.",
        "Check the id. A D&D Beyond character URL looks like "
        "https://www.dndbeyond.com/characters/12345678 — the number at the end "
        "is the id. A deleted character also 404s.",
        ref=ref)


def bad_ref(ref):
    return CharacterCheckError(
        "bad_ref",
        f"No character id could be found in {ref!r}.",
        "Pass a D&D Beyond character URL, a bare numeric id, or the path to a "
        "saved character-service JSON file.",
        ref=ref)


def rate_limited(ref):
    return CharacterCheckError(
        "rate_limited",
        "D&D Beyond returned 429 — too many requests.",
        "Wait a minute and retry. If you are deriving many characters, space "
        "the calls out; there is no bulk endpoint.",
        ref=ref)


def network(ref, detail):
    return CharacterCheckError(
        "network",
        "Could not reach D&D Beyond.",
        "Check network access. charactercheck needs outbound HTTPS to "
        "character-service.dndbeyond.com. If this host has no network, save "
        "the character JSON elsewhere and pass the file path.",
        ref=ref, detail=detail)


def bad_json(ref, detail):
    return CharacterCheckError(
        "bad_json",
        "The response was not the character JSON charactercheck expects.",
        "If you passed a file, confirm it is a character-service v5 payload "
        "(it has a top-level 'data' object). If this came from D&D Beyond, "
        "the API may have changed — please open an issue with the ref.",
        ref=ref, detail=detail)


def upstream(ref, status):
    return CharacterCheckError(
        "upstream",
        f"D&D Beyond returned HTTP {status}.",
        "This is an error on D&D Beyond's side, not in your input. Retry "
        "shortly; if it persists, D&D Beyond may be down.",
        ref=ref, detail=str(status))


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def doctor(ref=None):
    """Diagnose why charactercheck is not working, in one command.

    Exists to convert "it doesn't work" into something the caller can act on
    without opening an issue. Each check reports PASS/FAIL and the first
    failure carries the remedy — so an agent that is stuck runs this, reads one
    line, and proceeds.
    """
    import json as _json
    import socket
    import sys
    import urllib.request

    checks = []

    def add(name, ok, detail, action=None):
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       **({"action": action} if action and not ok else {})})

    v = sys.version_info
    add("python", v >= (3, 9), f"{v.major}.{v.minor}.{v.micro}",
        "charactercheck needs Python 3.9 or newer.")

    try:
        socket.getaddrinfo("character-service.dndbeyond.com", 443)
        add("dns", True, "character-service.dndbeyond.com resolves")
    except OSError as e:
        add("dns", False, str(e),
            "This host cannot resolve D&D Beyond. Work offline instead: save "
            "the character-service JSON and pass the file path.")

    if any(c["check"] == "dns" and c["ok"] for c in checks):
        try:
            req = urllib.request.Request(
                "https://character-service.dndbeyond.com/character/v5/character/1",
                headers={"Accept": "application/json",
                         "User-Agent": "charactercheck-doctor"})
            urllib.request.urlopen(req, timeout=20)
            add("network", True, "outbound HTTPS works")
        except urllib.error.HTTPError:
            # A 403/404 here is a *successful* round trip — the service
            # answered. That is exactly what we are testing for.
            add("network", True, "outbound HTTPS works (service answered)")
        except Exception as e:  # noqa: BLE001 - diagnosing, report anything
            add("network", False, str(e),
                "Outbound HTTPS to character-service.dndbeyond.com failed. "
                "Check egress/proxy, or pass a saved JSON file path instead.")

    if ref:
        try:
            from . import engine
            d = engine.fetch(ref)
            name = (d or {}).get("name") or "(unnamed)"
            add("character", True, f"fetched {name!r}")
        except CharacterCheckError as e:
            add("character", False, f"{e.kind}: {e.message}", e.action)
        except Exception as e:  # noqa: BLE001
            add("character", False, repr(e),
                "Unexpected failure — please open an issue with this output.")

    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "checks": checks,
            "summary": ("all checks passed" if ok else
                        "first failing check carries the action to take")}


def render_doctor(result):
    lines = []
    for c in result["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        lines.append(f"  [{mark}] {c['check']}: {c['detail']}")
        if c.get("action"):
            lines.append(f"         -> {c['action']}")
    lines.append("")
    lines.append("  " + result["summary"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

#: Values derived from the bundled sample character. Pinned so that "is the
#: tool working?" is answerable without a network, without a D&D Beyond
#: account, and without a character of your own.
#:
#: This exists because those three things are the *other* failure modes, and an
#: agent that cannot separate them is stuck: a 403 on someone's private sheet
#: and a broken install look identical from the outside.
SELFTEST_EXPECT = {
    "name": "Torvald Brightmantle",
    "level": 3,
}


def selftest():
    """Derive the bundled sample character and check known values.

    Returns ``(ok, lines)``. Deliberately offline: the sample ships in the
    package, so a pass proves the derivation engine works and isolates any
    remaining problem to network or character access.
    """
    import os

    from . import engine

    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "sample-character.json"),
        os.path.join(os.path.dirname(here), "examples", "sample-character.json"),
        os.path.join(os.path.dirname(here), "tests", "fixtures", "torvald.json"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if not path:
        return False, ["[FAIL] sample character not found in this install"]

    lines, ok = [], True
    try:
        r = engine.derive(path)
    except Exception as e:  # noqa: BLE001 - a selftest reports anything
        return False, [f"[FAIL] derivation raised: {e!r}",
                       "       -> please open an issue with this line"]

    got_name = (r.get("identity") or {}).get("name")
    got_level = (r.get("identity") or {}).get("level")
    for label, got, want in (("name", got_name, SELFTEST_EXPECT["name"]),
                             ("level", got_level, SELFTEST_EXPECT["level"])):
        good = got == want
        ok = ok and good
        lines.append(f"  [{'PASS' if good else 'FAIL'}] {label}: {got!r}"
                     + ("" if good else f" (expected {want!r})"))

    for family in ("abilities", "saves", "skills", "combat"):
        present = bool(r.get(family))
        ok = ok and present
        lines.append(f"  [{'PASS' if present else 'FAIL'}] {family} derived")

    lines.append("")
    lines.append("  offline derivation works — no network, no D&D Beyond "
                 "account, no character of your own required."
                 if ok else
                 "  the engine itself is failing; this is not a network or "
                 "permissions problem.")
    return ok, lines
