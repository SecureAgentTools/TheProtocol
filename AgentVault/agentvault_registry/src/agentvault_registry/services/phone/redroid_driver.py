"""PHONE FABRIC — RedroidPhoneDriver: real Android-in-Docker over the network (2026-07-07).

The data-plane driver. Talks to a per-instance **fabric-agent sidecar** (ships in
docker-compose.phone-fabric.yml) that wraps ADB + UIAutomator and exposes the PhoneDriver
contract over a small internal HTTP API. The registry never runs ADB itself — it calls the
sidecar, which is the only thing with device access. This keeps the money-core process free
of Android tooling and lets the phone instances live on a **dedicated host** (Commander-gated:
kernel binder/ashmem + ~2 GB/instance — NOT the shared prod box).

State lives on the DEVICE, so `restore()` is a no-op (unlike the mock). The wire is
tree-first; screenshots only when the caller allows (the router already gates on the caveat).

Activated ONLY when PHONE_FABRIC_BACKEND=redroid. `make_driver()` imports this lazily, so a
mock-only deployment never needs httpx-to-a-sidecar or a running instance.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from .driver import ActionResult, Observation, UiNode

# Where the fabric-agent sidecars are reachable. In compose, an internal DNS name per
# instance (e.g. http://phone-agent-0:9911). The pool maps a session's instance handle → base.
_AGENT_BASE_TMPL = os.getenv("PHONE_REDROID_AGENT_BASE", "http://{handle}:9911")
_TIMEOUT = float(os.getenv("PHONE_REDROID_TIMEOUT", "20"))


def _node_from_json(j: dict) -> UiNode:
    return UiNode(
        id=j.get("id", ""), role=j.get("role", "text"), text=j.get("text", ""),
        package=j.get("package", ""), tappable=bool(j.get("tappable")),
        editable=bool(j.get("editable")), bounds=j.get("bounds"),
        children=[_node_from_json(c) for c in j.get("children", [])],
    )


class RedroidPhoneDriver:
    backend = "redroid"

    def __init__(self, handle: str):
        self.handle = handle
        self.base = _AGENT_BASE_TMPL.format(handle=handle)

    async def _call(self, method: str, path: str, json_body: Optional[dict] = None) -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.request(method, f"{self.base}{path}", json=json_body)
            r.raise_for_status()
            return r.json()

    async def health(self) -> bool:
        try:
            return (await self._call("GET", "/health")).get("ok", False)
        except Exception:  # noqa: BLE001
            return False

    async def reset(self) -> None:
        try:
            await self._call("POST", "/reset")
        except Exception:  # noqa: BLE001 — a fresh instance may already be home
            pass

    def restore(self, package: Optional[str], screen: Optional[str]) -> None:
        # No-op: the redroid device holds its own state.
        return None

    @property
    def state(self):
        # Redroid state is the device's; the router reads current_app/screen from `observe`.
        return None, None

    async def observe(self, *, want_screenshot: bool = False) -> Observation:
        j = await self._call("POST", "/observe", {"screenshot": want_screenshot})
        return Observation(package=j.get("package", ""), screen=j.get("activity", ""),
                           tree=_node_from_json(j.get("tree", {})),
                           screenshot_b64=j.get("screenshot") if want_screenshot else None)

    async def launch(self, package: str) -> ActionResult:
        j = await self._call("POST", "/launch", {"package": package})
        return ActionResult(ok=j.get("ok", False), package=j.get("package", package),
                            screen=j.get("activity", ""), detail=j.get("detail", ""))

    async def act(self, action_type: str, *, target: Optional[str] = None,
                  text: Optional[str] = None, **kw: Any) -> ActionResult:
        j = await self._call("POST", "/act", {"type": action_type, "target": target, "text": text, **kw})
        return ActionResult(ok=j.get("ok", False), package=j.get("package", ""),
                            screen=j.get("activity", ""), detail=j.get("detail", ""))
