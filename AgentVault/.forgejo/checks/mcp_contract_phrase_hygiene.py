#!/usr/bin/env python3
"""§EVTYPES2 gate — a refusal contract must assert something PORTABLE and REAL.

WHY THIS EXISTS. The 158 destructive-tool contracts were derived by probing live
nodes, and four of the five defects found while building them were defects of the
PHRASE, not of the tool:

  * a phrase carrying a node-specific HTTP status ("X returned HTTP 403") pins one
    node's answer onto every node that runs the suite;
  * a phrase carrying an identifier from the probe run (a DID, a UUID, a timestamp)
    can never match again, because the next run mints different ones;
  * a bare `expect_status="error_4xx"` with no phrase asserts only the status class,
    which this file's own doctrine has banned since 2026-05-26;
  * a contract claiming BOTH success and an error phrase can never be satisfied.

Every one of those was found by watching a failure COUNT move in the wrong
direction (1 -> 36, once) and then reading backwards. That is archaeology, and it
only works when someone happens to be looking. All four are decidable from the
source text, so they belong in CI.

PURE AST: parses the file, imports nothing from it. Runs with no DB, no network,
no settings — which is why it can live in the `sanity` job.

Exit 0 = clean. Exit 1 = at least one violation. Exit 2 = the gate could not run
(unparseable file, dict not found) — never silently green.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[2]
# §EVTYPES8 2026-09-06: the path is overridable so this gate can be CONTROLLED
# without editing the file it guards. It could not be, and that cost a real
# measurement: two candidate phrases were "tested" by pointing an argument at
# planted copies, the gate read the real file both times, and both came back
# PASS. The tell was the contract COUNT not moving (483 → 483) — the same shape
# as §SANDBOXGATE, where a gate whose scope excluded the new files reported the
# identical key count and the not-moving number WAS the finding. CI still calls
# it with no arguments and nothing changes there.
TARGET = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1
          else ROOT / "agentvault_registry/src/agentvault_registry/api_tests/contracts/mcp_contracts.py")

# ── what a phrase must never carry ───────────────────────────────────────────
# Each is a literal that is true of ONE node or ONE run, never of the contract.
NONPORTABLE = [
    (re.compile(r"\bHTTP\s+[1-5]\d\d\b"),
     "a bare HTTP status code — node-specific (the operator and the mainframe "
     "refuse the same call with different codes)"),
    (re.compile(r"did:(?:theprotocol|cos):[0-9a-fA-F]{8}-"),
     "a DID minted by the probe run — the next run mints a different one"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
     "a UUID from the probe run"),
    (re.compile(r"\b20\d\d-\d\d-\d\dT\d\d:\d\d"),
     "an ISO timestamp from the probe run"),
    (re.compile(r"\b(?:sbx-(?:alpha|beta)|registry-a|frame-[bc])-[a-z-]+\b"),
     "a container name — the suite runs against more than one node"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
     "an IP literal (see tests/test_no_box_ip_code_literals.py for the class)"),
    # §EVTYPES8 2026-09-06 — added BEFORE the first contract that could trip it.
    # §DIDWIDEN's new refusals interpolate a trust domain with !r, so they render
    # as ...trust domain 'eu-1788674784.theprotocol.cloud' is this registry's own
    # issuer namespace... A contract that pins the rendered sentence pins ONE
    # frame's hostname, which the next frame does not have — the same defect as
    # pinning a DID, in a shape none of the patterns above could see (measured:
    # that exact phrase passed this gate). Quoted-only and URL-excluded on
    # purpose: a stable constant like the extension URI
    # https://theprotocol.cloud/extensions/v1/... is portable and must stay
    # legal, and it appears unquoted inside a URL. Zero existing phrases match,
    # so this ships with no grandfathered entry.
    (re.compile(r"(?<!/)['\"](?!/)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
                r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+['\"]"),
     "a quoted hostname / trust domain — one node's identity, not the "
     "contract's (pin the code word and the stable clause, stop before the "
     "interpolated name)"),
]

# Quoted tokens that merely LOOK DNS-shaped and are not node identities.
_HOSTLIKE_EXEMPT = re.compile(r"['\"][^'\"]*\.(?:py|json|ya?ml|md|txt|pem|crt|key|log|sh|js|ts|vue)['\"]")

# A phrase shorter than this matches so much that it asserts nothing.
MIN_PHRASE_LEN = 8

# A phrase of exactly this shape says only "the tool errored somehow". Legal —
# sometimes it is all both nodes agree on — but counted, so the strength of the
# refusal set is a number in the log rather than an assumption.
WEAK = re.compile(r"^\w+ returned HTTP$")


# ── the pre-existing violations, named ───────────────────────────────────────
# Nine contracts predating §EVTYPES2 carry the same defects. They are NOT fixed
# here on purpose: a better phrase can only come from PROBING the tool, and
# inventing one from the tool's name is precisely the mistake this gate exists to
# stop. So they are grandfathered with a reason each, and the gate enforces two
# directions — a NEW violation fails, and an entry that no longer violates ALSO
# fails, so the list can only shrink and never silently rots.
#
# To clear one: probe the tool on a mainframe AND a cloud-op, take the sentence
# both nodes actually say, then delete its line here.
GRANDFATHERED: dict[str, str] = {
    # EMPTY as of 2026-09-06. All nine original entries were re-probed on a
    # mainframe AND both cloud-ops and rewritten to pin the RAIL that answered
    # ("authResetPassword returned HTTP") instead of a status code that
    # expect_status already asserts. Keep it empty: an entry here is a contract
    # nobody has probed, and the gate fails on a stale one, so it cannot rot.
}


def _kw(node: ast.Call, name: str):
    for k in node.keywords:
        if k.arg == name:
            return k.value
    return None


def _str_list(node) -> list[str] | None:
    """Return the literal strings in a str or list-of-str node, else None."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple)):
        out = []
        for e in node.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                out.append(e.value)
            else:
                return None          # computed — the gate cannot read it
        return out
    return None


def main() -> int:
    if not TARGET.exists():
        print(f"GATE ERROR: {TARGET} not found", file=sys.stderr)
        return 2
    try:
        tree = ast.parse(TARGET.read_text(), filename=str(TARGET))
    except SyntaxError as exc:
        print(f"GATE ERROR: {TARGET} does not parse: {exc}", file=sys.stderr)
        return 2

    contracts: list[tuple[str, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                    and isinstance(v, ast.Call)
                    and getattr(v.func, "id", None) == "McpContract"):
                contracts.append((k.value, v))

    if not contracts:
        print("GATE ERROR: found no McpContract(...) entries — did the file's "
              "shape change? Refusing to report green.", file=sys.stderr)
        return 2

    violations: list[str] = []
    weak = 0
    checked = 0

    # (0) §EVTYPES4 — a tool named TWICE in the dict literal is a contract that can
    # never fire. Python keeps the last entry and discards the first in silence, so
    # the dead one reads exactly like coverage while asserting nothing. This is not
    # hypothetical here: a 2026-05-26 comment in the target file records the same
    # class being found and fixed once ("last one wins"), and NINE more had crept
    # back in by 2026-09-06 — two of which had silently WEAKENED a live contract
    # (getMyVotingPower lost "positions", getMyA2APaymentTokens lost its
    # expect_keys entirely). Cheap to decide from the source; therefore CI's job.
    seen: dict[str, int] = {}
    for name, call in contracts:
        if name in seen:
            violations.append(
                f"{name}: defined twice (lines {seen[name]} and {call.lineno}) — a "
                f"duplicate dict key keeps only the LAST entry, so the earlier one "
                f"is dead code that looks like coverage. Merge them and delete one.")
        seen[name] = call.lineno

    for name, call in contracts:
        status_node = _kw(call, "expect_status")
        # expect_status is a string class ("success", "error_4xx") OR a literal
        # int status; only the string form carries the error-class doctrine.
        status = None
        if isinstance(status_node, ast.Constant) and isinstance(status_node.value, str):
            status = status_node.value
        phrases = _str_list(_kw(call, "expect_error_message_contains"))
        has_err_keys = _kw(call, "expect_error_keys") is not None
        skipped = _kw(call, "skip_reason") is not None

        # (1) doctrine: an error status must be paired with a body assertion
        if status and status.startswith("error") and not skipped:
            if not phrases and not has_err_keys:
                violations.append(
                    f"{name}: expect_status={status!r} with no "
                    f"expect_error_message_contains / expect_error_keys — a bare "
                    f"error-class assertion is banned by this file's own doctrine")

        # (3) a contract cannot claim success AND an error phrase
        if status == "success" and phrases:
            violations.append(
                f"{name}: expect_status='success' together with "
                f"expect_error_message_contains — unsatisfiable")

        if not phrases:
            continue
        checked += 1

        for p in phrases:
            s = p.strip()
            # (4) a phrase that matches everything asserts nothing
            if len(s) < MIN_PHRASE_LEN:
                violations.append(
                    f"{name}: phrase {p!r} is shorter than {MIN_PHRASE_LEN} "
                    f"characters — it matches too much to be an assertion")
            # (2) portability
            # §EVTYPES8: strip quoted filenames first — they are DNS-shaped to a
            # regex and are never a node's identity, so they must not be read as
            # one. Only the hostname rule needs this; stripping before the loop
            # keeps one text for every pattern rather than a per-rule special case.
            p_scan = _HOSTLIKE_EXEMPT.sub("<file>", p)
            for rx, why in NONPORTABLE:
                if rx.search(p_scan):
                    violations.append(f"{name}: phrase {p!r} carries {why}")
            if WEAK.match(s):
                weak += 1

    offenders = {v.split(":", 1)[0] for v in violations}
    fresh = [v for v in violations if v.split(":", 1)[0] not in GRANDFATHERED]
    stale = sorted(set(GRANDFATHERED) - offenders)

    print(f"§EVTYPES2 phrase hygiene: {len(contracts)} contracts, "
          f"{checked} carrying refusal phrases, {weak} of those weak "
          f"(\"<tool> returned HTTP\" — status class only, portable but generic); "
          f"grandfathered {len(GRANDFATHERED)}, still violating "
          f"{len(offenders & set(GRANDFATHERED))}")

    rc = 0
    if fresh:
        print(f"\nFAIL — {len(fresh)} NEW violation(s):\n", file=sys.stderr)
        for v in fresh:
            print(f"  * {v}", file=sys.stderr)
        print("\nA refusal contract must assert a sentence the PRODUCT says, on "
              "every node the suite runs against. Probe both node classes and pin "
              "what they agree on — never trim a guess into shape.", file=sys.stderr)
        rc = 1
    if stale:
        print(f"\nFAIL — {len(stale)} GRANDFATHERED entr(ies) no longer violate; "
              f"delete them so the list keeps meaning something:\n", file=sys.stderr)
        for t in stale:
            print(f"  * {t}", file=sys.stderr)
        rc = 1
    if rc:
        return rc

    print("PASS — no new violations; the grandfathered list is exactly the "
          "contracts that still need a probe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
