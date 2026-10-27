"""Which series in the SHARED Prometheus are this registry's own (§FESUITE, with agentvault2-bb; 2026-10-02).

One Prometheus scrapes every registry, TEG and store on the host, production and the sandbox alike. An admin status
route that sums a metric with no label of its own therefore sums the whole scraped fleet: sbx-alpha's canary judge
read 37.6% from Frame A's production paths (agentvault2-bb, V0541), and a sandbox console showed production's numbers.

The scrape config names every target's `job` (monitoring/prometheus.yml and /etc/prometheus/targets/*.json, measured
2026-10-02): `<slug>-registry` and `<slug>-teg` for a frame or an operator (an operator's slug without its `cloud-op-`
prefix: amsterdam-registry, sbxalphaop-registry), and Frame A's legacy `registry-a` and `teg-layer-a`. A route selects
its own series with `sel(metric)`, or `sel(metric, component='teg')` for a metric its frame's TEG exports. Where a
deployment names its jobs otherwise, METRICS_SELF_JOB / METRICS_SELF_TEG_JOB say so.
"""
from __future__ import annotations

import os
from typing import Mapping, Optional

from .frame_slug import frame_slug

_FRAME_A = {"registry": "registry-a", "teg": "teg-layer-a"}
_OVERRIDE = {"registry": "METRICS_SELF_JOB", "teg": "METRICS_SELF_TEG_JOB"}


def self_job(component: str = "registry", env: Optional[Mapping[str, str]] = None) -> str:
    """The scrape job of this registry (component='registry') or of its frame's TEG (component='teg')."""
    if component not in _FRAME_A:
        raise ValueError(f"unknown component {component!r}")
    e = os.environ if env is None else env
    override = (e.get(_OVERRIDE[component]) or "").strip()
    if override:
        return override
    slug = frame_slug(e)
    if slug.startswith("cloud-op-"):
        slug = slug[len("cloud-op-"):]
    if slug in ("", "registry-a"):
        return _FRAME_A[component]
    return f"{slug}-{component}"


def sel(metric: str, component: str = "registry", env: Optional[Mapping[str, str]] = None, **labels: str) -> str:
    """`metric{job="<own job>",k="v",...}`: the selector for this registry's own series of `metric`."""
    pairs = [f'job="{self_job(component, env)}"'] + [f'{k}="{v}"' for k, v in labels.items()]
    return metric + "{" + ",".join(pairs) + "}"
