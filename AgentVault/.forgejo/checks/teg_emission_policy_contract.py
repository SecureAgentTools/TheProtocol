#!/usr/bin/env python3
"""TEG emission-policy contract gate  (§EVTYPES 2026-09-05).

WHY THIS EXISTS
---------------
The TEG event emitter is fail-CLOSED: an event_type with no `emit_from_teg=true`
policy row is DENIED, and `emit()` still returns without raising. So a TEG emit
added without a matching policy decision is a *silently dropped* ledger event --
invisible to Delta (escrow legs are transit-neutral), invisible to the caller,
and invisible to every exception-based instrument.

Measured 2026-09-05 on the live fleet: five TEG-emitted types had no policy row
at all, and their SIBLINGS in the very same files did. `sweeper.py` emits
CrossTEGStaleSwept (row present, allowed) beside CrossTEGStaleOutflowSwept and
ExchangeOrphanExrefLegSwept (no row, denied); `escrow_lock_reconciler.py` emits
NegativeEscrowLockClamped (allowed) beside OrphanedEscrowLockReleased (denied).
Written the same day, one got a row, the other did not. Nothing caught it
because nothing was looking.

WHAT IT DOES
------------
AST-censuses every event_type the TEG tree can emit -- resolving local wrapper
functions (`_emit_audit_event(event_type, ...)` -> `emitter.emit(event_type=...)`)
to a fixpoint, because most literals live at the WRAPPER'S CALLER -- and asserts
each one carries a recorded decision below. Adding a TEG emit without recording
the decision turns this RED.

It also verifies every `code_forced` claim against the source: the table cannot
assert a force-allow that `event_emitter.py` does not actually perform.

No DB, no network, no image -- it belongs in the `sanity` job.
"""
import ast, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))          # <repo>/.forgejo/checks
REPO = os.path.dirname(os.path.dirname(HERE))              # <repo>
# AgentVault checkout (CI) has the TEG tree at the root; the stack superproject
# nests it under AgentVault/. Try both so the gate runs from either cwd.
_CANDIDATES = [
    os.path.join(REPO, "agentvault_teg_layer_mvp", "src"),
    os.path.join(REPO, "AgentVault", "agentvault_teg_layer_mvp", "src"),
]
TEG_SRC = next((c for c in _CANDIDATES if os.path.isdir(c)), _CANDIDATES[0])
EMITTER = os.path.join(TEG_SRC, "teg_core_service", "event_emitter.py")

# ── The decision table. Every TEG-emitted event_type MUST appear here. ──────
#    "policy_row"  -> a migration seeds emit_from_teg=true; the gate trusts the
#                     migration but the LIVE audit (scratchpad/evtypes/) is what
#                     proves the row reached a given frame's DB.
#    "code_forced" -> force-allowed in event_emitter.py regardless of any row;
#                     verified against the source below.
#    "denied"      -> knowingly denied today. NOT a pass mark: each carries the
#                     consequence, and closing one means moving it up.
DECISIONS = {
    "LedgerBalanceChanged":        ("code_forced", "L2 balance outbox; TEG-native. Force-allowed at import AND after every policy fetch (§pass73.3.20) because the fetch replaces the cache wholesale. NOTE: no policy row exists in prod or sandbox -- the in-code comment claiming a 'belt+suspenders' row is wrong."),
    "CrossTEGStaleSwept":          ("policy_row", "mig 0057; live-verified allow on prod TEG."),
    "NegativeEscrowLockClamped":   ("policy_row", "escrow lock reconciler; row present in prod."),
    "TokensTransferred":           ("denied", "DELIBERATE: registry emits it (PART 3). TEG must not, or supply double-counts."),
    "TokensIssued":                ("denied", "DELIBERATE: minting is registry-native via the mint proxy."),
    "TokensStaked":                ("denied", "DELIBERATE: registry orchestrates staking."),
    "TokensUnstaked":              ("denied", "DELIBERATE: registry orchestrates staking."),
    "AgentCreated":                ("denied", "DELIBERATE: registry owns agent lifecycle."),
    "AgentUpdated":                ("denied", "DELIBERATE: registry owns agent lifecycle. No row anywhere; TEG never reaches this path in practice."),
    # ── GAPS: audit events that vanish exactly when they matter ──
    "CrossTEGStaleOutflowSwept":   ("policy_row", "mig 0175 (§BATCH7); sibling of CrossTEGStaleSwept in sweeper.py."),
    "ExchangeOrphanExrefLegSwept": ("policy_row", "mig 0175 (§BATCH7); sibling of CrossTEGStaleSwept in sweeper.py."),
    "OrphanedEscrowLockReleased":  ("policy_row", "mig 0175 (§BATCH7); sibling of NegativeEscrowLockClamped in escrow_lock_reconciler.py."),
}

BASE_EMIT = {"emit", "emit_event", "emit_background", "publish_event", "emit_business_event"}


def _parse_tree(root):
    out = []
    for dp, dn, fns in os.walk(root):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".git", ".venv", "node_modules")]
        for fn in fns:
            if fn.endswith(".py"):
                p = os.path.join(dp, fn)
                try:
                    out.append((p, ast.parse(open(p, encoding="utf-8", errors="replace").read())))
                except SyntaxError:
                    pass
    return out


def _callee(node):
    if isinstance(node.func, ast.Attribute): return node.func.attr
    if isinstance(node.func, ast.Name):      return node.func.id
    return None


def _et_arg(node, callee):
    for kw in node.keywords:
        if kw.arg == "event_type": return kw.value
    if node.args:
        idx = 1 if callee == "emit_event" and len(node.args) > 1 else 0
        if idx < len(node.args): return node.args[idx]
    return None


def census(files):
    """event_type -> [(file, line)], plus unresolved sites."""
    emitset = set(BASE_EMIT)
    for _ in range(6):                                  # wrapper fixpoint
        grew = False
        for _p, tree in files:
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
                if fn.name in emitset: continue
                params = {a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)}
                if "event_type" not in params: continue
                for n in ast.walk(fn):
                    if isinstance(n, ast.Call) and _callee(n) in emitset:
                        et = _et_arg(n, _callee(n))
                        if isinstance(et, ast.Name) and et.id == "event_type":
                            emitset.add(fn.name); grew = True; break
        if not grew: break

    found, unresolved = {}, []
    for path, tree in files:
        consts = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) \
               and isinstance(n.value.value, str):
                for t in n.targets:
                    if isinstance(t, ast.Name): consts[t.id] = n.value.value
        wrapper_lines = set()
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in emitset:
                wrapper_lines.update(range(fn.lineno, (fn.end_lineno or fn.lineno) + 1))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call): continue
            c = _callee(n)
            if c not in emitset: continue
            et = _et_arg(n, c)
            if et is None: continue
            rel = os.path.relpath(path, TEG_SRC)
            if isinstance(et, ast.Constant) and isinstance(et.value, str):
                found.setdefault(et.value, []).append((rel, n.lineno))
            elif isinstance(et, ast.Name) and et.id in consts:
                found.setdefault(consts[et.id], []).append((rel, n.lineno))
            elif isinstance(et, ast.Name) and et.id == "event_type" and n.lineno in wrapper_lines:
                pass                                    # pass-through inside a wrapper
            else:
                unresolved.append((rel, n.lineno, ast.dump(et)[:60]))
    return found, unresolved


def code_forced_types():
    """Types force-allowed in event_emitter.py: `_teg_policy_cache["X"] = True`."""
    src = open(EMITTER, encoding="utf-8").read()
    tree = ast.parse(src)
    forced = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and n.value.value is True:
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                   and t.value.id == "_teg_policy_cache" \
                   and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str):
                    forced.add(t.slice.value)
    return forced


def main():
    if not os.path.isdir(TEG_SRC):
        print("FATAL: TEG source tree not found at %s" % TEG_SRC); return 1
    files = _parse_tree(TEG_SRC)
    if not files:
        print("FATAL: parsed 0 python files under %s -- the census would pass vacuously" % TEG_SRC)
        return 1
    found, unresolved = census(files)
    if not found:
        print("FATAL: censused 0 emit sites -- gate would pass vacuously"); return 1

    forced = code_forced_types()
    rc = 0

    undeclared = sorted(set(found) - set(DECISIONS))
    if undeclared:
        rc = 1
        print("FAIL: TEG emits event types with NO recorded emission decision.")
        print("      TEG is fail-closed: with no emit_from_teg=true row these are SILENTLY DROPPED.")
        for t in undeclared:
            for f, l in found[t]:
                print("        %-34s %s:%s" % (t, f, l))
        print("      -> add a row to DECISIONS in %s with the reason." % os.path.basename(__file__))

    stale = sorted(set(DECISIONS) - set(found))
    if stale:
        rc = 1
        print("FAIL: DECISIONS lists types the TEG no longer emits (table rot): %s" % stale)

    for t, (kind, _why) in sorted(DECISIONS.items()):
        if kind == "code_forced" and t not in forced:
            rc = 1
            print("FAIL: %s is declared code_forced but event_emitter.py never sets "
                  "_teg_policy_cache[%r] = True" % (t, t))
    for t in sorted(forced - set(DECISIONS)):
        rc = 1
        print("FAIL: event_emitter.py force-allows %r but it has no DECISIONS entry" % t)

    if unresolved:
        print("WARN: %d emit site(s) whose event_type could not be resolved statically:" % len(unresolved))
        for f, l, e in unresolved[:10]:
            print("        %s:%s  %s" % (f, l, e))

    gaps = sorted(t for t, (k, w) in DECISIONS.items() if k == "denied" and w.startswith("GAP"))
    print("censused %d TEG event types across %d file(s); %d code_forced; %d known GAPs%s"
          % (len(found), len(files), len(forced), len(gaps),
             (": " + ", ".join(gaps)) if gaps else ""))
    print("OK: every TEG-emitted event type carries a recorded emission decision." if rc == 0
          else "GATE RED")
    return rc


if __name__ == "__main__":
    sys.exit(main())
