#!/usr/bin/env python3
"""
Render a network profile (§MONEY-M2).

    render_network_profile.py mainnet   -o config/network_profile.mainnet-2026.env
    render_network_profile.py lowsupply -o config/network_profile.lowsupply-2026.env \
                              --s0 <S0> --grant <GRANT>

`mainnet` is a RECORDING, not a proposal: every value is read from a running
container's env by NAME (never a prefix scan — §CANARYFIX), and only falls back
to the code default when no node sets it. The output annotates which.

`lowsupply` REFUSES without --s0 and --grant. S0 (D1) and the grant (D2) are the
Commander's decisions; nothing here invents them.
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from network_profile_knobs import KNOBS  # noqa: E402

SCOPE_CONTAINER = {
    "registry": "agentvault_registry_a",
    "provisioner": "agentvault_registry_a",
    "teg": "agentvault_teg_layer_a",
    "es": "agentvault_event_store",
    "ops": "cloud-op-op-berlin-registry",
}


def container_env(container: str) -> dict:
    """The container's env as a dict. Read whole and looked up BY NAME by the
    caller — we never pattern-match a container's env (§CANARYFIX: a prefix
    regex printed operator passwords)."""
    try:
        out = subprocess.run(
            ["docker", "inspect", container, "--format", "{{json .Config.Env}}"],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            return {}
        env = {}
        for item in json.loads(out.stdout):
            if "=" in item:
                k, v = item.split("=", 1)
                env[k] = v
        return env
    except Exception:
        return {}


def render_mainnet() -> tuple[list[str], dict]:
    envs = {scope: container_env(c) for scope, c in SCOPE_CONTAINER.items()}
    lines, prov = [], {}
    for k in KNOBS:
        name = k["name"]
        env = envs.get(k["scope"], {})
        if name in env:
            value, source = env[name], f"env:{SCOPE_CONTAINER[k['scope']]}"
        else:
            value, source = k["code_default"], "code-default"
        prov[name] = source
        lines.append((name, value, source, k))
    return lines, prov


def _fmt(d: Decimal) -> str:
    """Trim a computed amount to something a person can read and a parser accepts."""
    d = d.quantize(Decimal("0.000001"), rounding=ROUND_DOWN) if d % 1 else d.quantize(Decimal("1"))
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def render_lowsupply(s0: Decimal, grant: Decimal) -> list:
    """Evaluate every formula FIRST, then build the file.

    All-or-nothing on purpose: a profile written up to the knob that failed is
    worse than no profile, because it looks complete.

    ⚠ The formulas use INTEGER arithmetic (`S0 * 20 / 100`, not `S0 * 0.20`).
    Decimal * float raises, and coercing through float would reintroduce the
    precision defect this whole program exists to remove (§MONEY-R15).
    """
    values = {}
    for k in KNOBS:
        f = k["lowsupply"]
        if f is None:
            continue
        try:
            v = eval(f, {"__builtins__": {}}, {"S0": s0, "GRANT": grant})  # noqa: S307 — table is ours
        except Exception as e:  # noqa: BLE001
            raise SystemExit(
                f"REFUSED: knob {k['name']} has formula {f!r} which does not evaluate "
                f"at S0={s0} GRANT={grant}: {type(e).__name__}: {e}\n"
                f"  Nothing was written. Fix the formula in network_profile_knobs.py."
            )
        if not isinstance(v, Decimal):
            raise SystemExit(
                f"REFUSED: knob {k['name']} formula {f!r} produced {type(v).__name__}, not Decimal. "
                "Use integer arithmetic so the result stays exact."
            )
        values[k["name"]] = v

    lines = []
    for k in KNOBS:
        if k["lowsupply"] is None:
            lines.append((k["name"], None, "posture — set deliberately below", k))
        else:
            lines.append((k["name"], _fmt(values[k["name"]]), f"= {k['lowsupply']}", k))
    return lines


def write(path: Path, header: list[str], lines: list) -> None:
    out = ["# " + h for h in header]
    out.append("")
    scope_now = None
    for name, value, source, k in lines:
        if k["scope"] != scope_now:
            scope_now = k["scope"]
            out.append(f"# ==================== {scope_now.upper()} ====================")
        out.append(f"# {k['note']}")
        out.append(f"#   read at: {k['reader']}   code default: {k['code_default'] or '(empty)'}")
        if value is None:
            out.append(f"#   {source}")
            out.append(f"# {name}=")
        else:
            out.append(f"#   {source}")
            out.append(f"{name}={value}")
        out.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile", choices=["mainnet", "lowsupply"])
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--s0", help="initial mint per frame (D1 — the Commander's)")
    ap.add_argument("--grant", help="genesis grant per person (D2 — the Commander's)")
    a = ap.parse_args()
    stamp = datetime.date.today().isoformat()

    if a.profile == "mainnet":
        lines, prov = render_mainnet()
        measured = sum(1 for v in prov.values() if v.startswith("env:"))
        header = [
            f"network profile: mainnet-2026   (rendered {stamp} by scripts/render_network_profile.py)",
            "",
            "A RECORDING OF THE NETWORK AS IT RUNS TODAY, not a proposal. Every value was read",
            "from a running container by name, or is the literal the code falls back to.",
            f"measured from a container: {measured}/{len(lines)}   code default: {len(lines)-measured}/{len(lines)}",
            "",
            "Selecting this profile changes NOTHING: env still wins, and every value here already",
            "equals what the node uses. It exists so the fresh network has something to diff against.",
        ]
        write(Path(a.out), header, lines)
        print(f"wrote {a.out}: {len(lines)} knobs, {measured} measured from live containers")
        return 0

    if not a.s0 or not a.grant:
        print(
            "REFUSED: lowsupply needs --s0 and --grant.\n"
            "  S0 (the initial mint per frame) is decision D1 and the grant is D2. Both are the\n"
            "  Commander's; this renderer will not invent either. Re-run with his numbers.",
            file=sys.stderr,
        )
        return 2
    s0, grant = Decimal(a.s0), Decimal(a.grant)
    lines = render_lowsupply(s0, grant)
    header = [
        f"network profile: lowsupply-2026   (rendered {stamp})",
        "",
        f"S0    = {s0}   initial mint per frame   (decision D1)",
        f"GRANT = {grant}   genesis grant per person (decision D2)",
        "",
        "Every amount below is a FRACTION of those two numbers, computed by",
        "scripts/render_network_profile.py from scripts/network_profile_knobs.py.",
        "Change S0 or GRANT and re-render; never hand-edit an amount.",
    ]
    write(Path(a.out), header, lines)
    print(f"wrote {a.out}: {len(lines)} knobs at S0={s0} GRANT={grant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
