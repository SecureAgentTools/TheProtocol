"""§FRAMEKIT P3.1 (2026-09-12) — THE ONE RULE for a frame's own slug: the prefix its containers carry.

The stack-health rail derived it by slugifying REGISTRY_NAME (§HETZNERLOCK-12), which holds for "EU" (eu)
and "Hetzner Frame" (hetzner-frame) and is WRONG the day a display name stops matching the container
prefix: "Sandbox Alpha" slugifies to `sandbox-alpha` while the frame provisioner named every container
`sbx-alpha-<component>` — measured 2026-09-12: sbx-alpha's own Mission Control read its TEG and Event
Store as DOWN (4/7 healthy) for nine days while Prometheus scraped both as up. The provisioner writes the
prefix into TEG_LAYER_URL (`http://<slug>-teg:8080`) on every frame it builds, so the slug is READ from
there; the display-name slugify remains the fallback for frames with no such URL (Frame A's `teg-layer`,
an operator's `teg-layer`, a frame with no TEG named).
"""
from __future__ import annotations

import os
import re
from typing import Mapping, Optional
from urllib.parse import urlparse


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def frame_slug(env: Optional[Mapping[str, str]] = None) -> str:
    """The prefix of this frame's containers: `<slug>` from TEG_LAYER_URL's host `<slug>-teg` or `<slug>-nginx-teg`, else the
    slugified REGISTRY_NAME. Empty on Frame A (no name) — callers treat "" as Frame A already."""
    e = os.environ if env is None else env
    host = (urlparse((e.get("TEG_LAYER_URL") or "").strip()).hostname or "").lower()
    # §MTLSHOPS V0378: T2 puts the TEG on its socket and the registry dials https://<slug>-nginx-teg:8443
    m = re.match(r"^(.+?)(?:-nginx)?-teg$", host)
    if m:
        return m.group(1)
    return slugify(e.get("REGISTRY_NAME") or "")
