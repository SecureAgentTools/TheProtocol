"""§MONEY-R50 (2026-09-04) — the registry-name slug rule and the cross-TEG funding-origin guard, ONE copy.

`routers/teg_integration.py` compared `_slug(settings.REGISTRY_NAME)` against the comma list in
`CROSS_TEG_FUND_ORIGIN_ALLOWLIST` (substring per token, default `registry-a`), while the frame
provisioner rendered that allowlist from a DIFFERENT name through NO slug rule and into the TEG's
env block, which nothing reads. A frame it stood up therefore refused to fund its own operators
(agentvault2-07's B7: `403 … This registry is 'Sandbox Alpha' (slug='sandbox-alpha') …`). Both
sides now call these two functions, so the value the provisioner renders is by construction the
value the guard accepts.
"""
from __future__ import annotations

import unicodedata as _ud
from typing import Iterable, List, Optional, Set

DEFAULT_FUND_ORIGIN_ALLOWLIST = "registry-a"


def registry_slug(name: Optional[str]) -> str:
    """The slug the origin guard computes from a registry's display name: NFKD → ASCII → lower,
    spaces → hyphens, outer hyphens stripped. `"Sandbox Alpha"` → `sandbox-alpha`, `sbx-alpha` → `sbx-alpha`."""
    n = name or ""
    return _ud.normalize("NFKD", n).encode("ASCII", "ignore").decode("ASCII").lower().replace(" ", "-").strip("-")


def parse_fund_origin_allowlist(raw: Optional[str], default: str = DEFAULT_FUND_ORIGIN_ALLOWLIST) -> Set[str]:
    """The allowlist tokens (lower-cased, stripped). An UNSET or empty env falls back to `default`,
    so a node with nothing configured keeps prod's historical behaviour (only `registry-a` funds)."""
    src = raw if (raw is not None and raw.strip()) else default
    return {s.strip().lower() for s in src.split(",") if s.strip()}


def fund_origin_allowed(registry_name: Optional[str], raw_allowlist: Optional[str],
                        default: str = DEFAULT_FUND_ORIGIN_ALLOWLIST) -> bool:
    """The guard's decision: may the registry named `registry_name` ORIGINATE cross-TEG treasury
    funding under `raw_allowlist` (the env value)? Substring per token against the name's slug —
    the historical semantics, kept exactly."""
    local_slug = registry_slug(registry_name).lower()
    return any(tok in local_slug for tok in parse_fund_origin_allowlist(raw_allowlist, default))


def fund_origin_allowlist_value(registry_name: str, display_name: str = "",
                                extra_origins: Iterable[str] = ()) -> str:
    """What the frame provisioner renders into `CROSS_TEG_FUND_ORIGIN_ALLOWLIST` on the REGISTRY
    service: the frame's own slug FIRST (a frame absent from its own allowlist cannot fund its
    satellites), under BOTH names the frame may carry as `REGISTRY_NAME` — its container name and
    its human display name (`MAINFRAME_REGISTRY_NAMES` carries both for the same reason) — then the
    extra origins the dual-frame orchestrator adds. Order-preserving, deduplicated, empties dropped."""
    out: List[str] = []
    for n in [registry_name, display_name, *list(extra_origins)]:
        s = registry_slug(n)
        if s and s not in out:
            out.append(s)
    return ",".join(out)
