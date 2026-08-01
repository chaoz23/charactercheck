# Security policy

> **Unreleased contract.** The hardening below exists only in the post-0.6.2
> source checkout. PyPI still exposes historical 0.6.2 behavior; active
> historical MCP Registry entries have unpinned runtime arguments that can
> resolve to it. Do not deploy that artifact expecting these controls; no newly
> versioned remediation has been published.

CharacterCheck treats character payloads and character-authored text as hostile
input. Inputs are parsed with strict reference grammar, bounded reads, duplicate
key and non-finite number rejection, structural validation, and graph limits.
Known failures are translated to redacted structured errors. Please do not put
character references, source JSON, local paths, cookies, tokens, campaign text,
or persona content in public issues.

Snapshot filtering uses closed nested allowlists. Unclassified source keys and
unsafe semantic values are omitted; three boolean coverage flags record only
that a top-level key, nested key, or semantic value was omitted. Fixed
field-owned semantic-gap codes survive filtering so the affected family can be
routed to `unsupported` without retaining hostile text; unscoped non-item or
nested-item gaps fail closed as global `unknown`. The exported normalized revision
hashes the default privacy-filtered mechanical character, not the raw source. A
diff between distinct snapshots with any coverage flag set fails closed as
`indeterminate`, emits a `$` unsupported comparison, and never treats omitted
content as proven equal.

Snapshot hashes are unkeyed integrity/content identifiers. They are not digital
signatures, trusted timestamps, source attestations, or authorization evidence;
a writer can alter a snapshot and recompute them. Trusted hosts must protect
baseline storage and bind snapshots to authenticated principals and audit logs.

Report a vulnerability privately through GitHub's private vulnerability
reporting for this repository when available. Include the CharacterCheck
version, error kind, and correlation ID; use a minimal synthetic reproduction.

The project does not accept D&D Beyond credentials, cookies, or session tokens.
MCP is unauthenticated and read-only. A host must add authenticated principals,
role/visibility policy, approval and audit controls before granting any broader
capability. Character-sheet text is data, never an instruction to the agent or
host.
