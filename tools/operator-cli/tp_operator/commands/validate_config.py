"""tp-operator validate-config — pre-flight env file check."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from .. import __schema_version__
from ..config import OperatorContext, parse_env_file
from ..output import Output, detect_output_mode

REQUIRED_KEYS = [
    "REGISTRY_NAME",
    "OPERATOR_DID",
    "PG_PASS_REGISTRY",
    "PG_PASS_TEG",
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "API_KEY_SECRET",
    "TEG_REGISTRY_JWT_SECRET",
    "TEG_ADMIN_API_KEY",
    "TEG_AVTP_SYSTEM_API_KEY",
    "TEG_TOKEN_SIGNING_KEY",
    "EVENT_STORE_INTERNAL_API_KEY",
]


def _validate(env: Dict[str, str]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    # 1. required keys
    for k in REQUIRED_KEYS:
        present = bool(env.get(k))
        checks.append({"check": f"required:{k}", "result": "pass" if present else "fail",
                       "detail": "present" if present else "missing"})

    # 2. coupling rule: API_KEY_SECRET == TEG_REGISTRY_JWT_SECRET
    a = env.get("API_KEY_SECRET", "")
    b = env.get("TEG_REGISTRY_JWT_SECRET", "")
    if a and b:
        coupling_ok = (a == b)
        checks.append({"check": "coupling:API_KEY_SECRET==TEG_REGISTRY_JWT_SECRET",
                       "result": "pass" if coupling_ok else "fail",
                       "detail": "equal" if coupling_ok else "values differ — generate-operator-env.sh:31"})

    # 3. example-value warnings
    if env.get("MAIL_PASSWORD") == "CHANGE_ME":
        checks.append({"check": "no-example-values", "result": "warn",
                       "detail": "MAIL_PASSWORD=CHANGE_ME — set before deploy"})
    if env.get("MAIL_SERVER") == "smtp.example.com":
        checks.append({"check": "no-example-values", "result": "warn",
                       "detail": "MAIL_SERVER=smtp.example.com — set before deploy"})

    # 4. federation-mode consistency
    minting = env.get("MINTING_AUTHORITY", "").lower()
    lic = env.get("FEDERATION_LICENSE_KEY", "").strip()
    if lic and minting != "disabled":
        checks.append({"check": "federation-mode", "result": "warn",
                       "detail": "FEDERATION_LICENSE_KEY set but MINTING_AUTHORITY not 'disabled'"})

    # 5. permission check (advisory)
    pass_count = sum(1 for c in checks if c["result"] == "pass")
    warn_count = sum(1 for c in checks if c["result"] == "warn")
    fail_count = sum(1 for c in checks if c["result"] == "fail")
    return {
        "schema_version": __schema_version__,
        "checks": checks,
        "summary": {"pass": pass_count, "warn": warn_count, "fail": fail_count},
        "verdict": "fail" if fail_count else ("warn" if warn_count else "pass"),
    }


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="validate-config", help="Pre-flight check on .env.operator schema + coupling rules.")
    def validate_cmd(
        proposed: Optional[Path] = typer.Option(None, "--proposed", help="Validate a different file instead of the operator's current .env.operator"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if proposed:
            env = parse_env_file(proposed)
            result = _validate(env)
            result["source"] = str(proposed)
            payloads = [result]
        else:
            contexts = load_contexts()
            payloads = []
            for ctx in contexts:
                r = _validate(ctx.env)
                r["operator"] = ctx.name
                r["source"] = str(ctx.env_path)
                payloads.append(r)

        if out.mode == "json":
            out.emit_json(payloads[0] if len(payloads) == 1 else {"operators": payloads})
        else:
            for p in payloads:
                src = p.get("operator", "(custom)") + " — " + p.get("source", "")
                badge = {"pass": "[green]PASS[/]", "warn": "[yellow]WARN[/]", "fail": "[red]FAIL[/]"}[p["verdict"]]
                out.line(f"\n[bold]{src}[/]  {badge}")
                rows = [[c["check"], c["result"].upper(), c["detail"]] for c in p["checks"]]
                out.table("checks", ["CHECK", "RESULT", "DETAIL"], rows)
        worst = "pass"
        for p in payloads:
            if p["verdict"] == "fail":
                worst = "fail"
                break
            if p["verdict"] == "warn" and worst == "pass":
                worst = "warn"
        raise typer.Exit(code={"pass": 0, "warn": 1, "fail": 2}[worst])
