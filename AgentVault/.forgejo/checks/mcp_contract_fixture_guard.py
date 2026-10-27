#!/usr/bin/env python3
"""§EVTYPES8 gate — `requires_fixtures` documents a guard it does not perform.

WHY THIS EXISTS. A census of `McpContract`'s 19 fields against their consumers
found `requires_fixtures` set on 51 contracts and read by NOTHING. What actually
makes a contract skip when its fixture is missing is elsewhere: the sweep
resolves `${name}` inside `arguments` and skips on anything still unresolved. So
the field is a declaration, and the guard is a side effect of the arguments.

MEASURED 2026-09-06: all 51 are consistent — every declared fixture is also
referenced in `arguments`, so nothing is unguarded today. That zero is the
reason this gate can ship green and mean something. The hole it prevents is the
one a reader would walk into: declare `requires_fixtures=["contract_v2_id"]`,
reference it nowhere in `arguments`, and the contract runs against a missing
fixture while its own source says it is protected. Nothing in the run would say
otherwise — the call simply happens with whatever args were there.

Also flags the inverse only as INFO, never as a failure: arguments may legitimately
reference fixtures the contract chose not to enumerate, because the enumeration is
documentation and the resolver is the mechanism.

PURE AST: parses the file, imports nothing from it. No DB, no network, no
settings — so it belongs in the `sanity` job beside the phrase-hygiene gate.

Exit 0 = clean. Exit 1 = at least one contract declares a fixture its arguments
never reference. Exit 2 = the gate could not run — never silently green.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

FIXTURE_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")

CONTRACTS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "agentvault_registry" / "src" / "agentvault_registry"
    / "api_tests" / "contracts" / "mcp_contracts.py"
)


def main() -> int:
    path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else CONTRACTS
    if not path.is_file():
        print(f"GATE ERROR — contracts file not found: {path}", file=sys.stderr)
        return 2
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as e:
        print(f"GATE ERROR — {path} is unparseable: {e}", file=sys.stderr)
        return 2

    declared = 0
    violations: list[str] = []
    undocumented = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, val in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if not isinstance(val, ast.Call):
                continue
            kw = {k.arg: k.value for k in val.keywords}
            arg_text = ast.unparse(kw["arguments"]) if "arguments" in kw else ""
            referenced = set(FIXTURE_RE.findall(arg_text))
            if "requires_fixtures" not in kw:
                if referenced:
                    undocumented += 1
                continue
            declared += 1
            try:
                required = list(ast.literal_eval(kw["requires_fixtures"]))
            except Exception:                                        # noqa: BLE001
                violations.append(
                    f"{key.value} (line {key.lineno}): requires_fixtures is not a "
                    f"literal list — the gate cannot read it, so nobody can"
                )
                continue
            # A skipped contract is never called, so an inconsistency there costs
            # nothing and saying so would only add noise.
            if "skip_reason" in kw:
                continue
            missing = [r for r in required if r not in referenced]
            if missing:
                violations.append(
                    f"{key.value} (line {key.lineno}): declares requires_fixtures="
                    f"{required!r} but `arguments` reference {sorted(referenced) or 'none'} "
                    f"— {missing!r} is guarded by nothing. The sweep skips on an "
                    f"unresolved ${{name}} in `arguments`, never on this field."
                )

    if declared == 0:
        print("GATE ERROR — no contract declares requires_fixtures; either the "
              "field was retired (delete this gate with it) or the parse missed "
              "the dict.", file=sys.stderr)
        return 2

    print(f"§EVTYPES8 fixture-guard: {declared} contract(s) declare requires_fixtures; "
          f"{undocumented} reference a ${{fixture}} without declaring one (fine — the "
          f"declaration is documentation, the resolver is the mechanism)")

    if violations:
        print(f"\nFAIL — {len(violations)} contract(s) declare a fixture nothing "
              f"guards:\n", file=sys.stderr)
        for v in violations:
            print(f"  * {v}", file=sys.stderr)
        print("\nPut the fixture in `arguments` as ${name} so the sweep's own "
              "unresolved-fixture detector skips the contract, or drop the claim.",
              file=sys.stderr)
        return 1

    print("PASS — every declared fixture is also referenced in `arguments`, so the "
          "sweep's unresolved-fixture detector really does guard each one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
