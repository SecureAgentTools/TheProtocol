"""PHONE FABRIC — the driver contract (2026-07-07).

A PhoneDriver abstracts "a phone an agent can drive". Two implementations:
  - MockPhoneDriver   — deterministic scripted Android; the permanent test surface.
  - RedroidPhoneDriver — ADB/UIAutomator over the network to a real redroid instance
                         (data plane; PF-C; only used when PHONE_FABRIC_BACKEND=redroid).

The contract is tree-first (accessibility tree, à la DroidRun/mobile-mcp), screenshots only
where a caveat permits. Every method is pure I/O against the device — the ROUTER owns
capability checks, budget/metering, and audit. Drivers never touch money or the DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class UiNode:
    """One accessibility-tree node (the unit an agent reasons over)."""
    id: str
    role: str                       # button|text|input|image|list|screen
    text: str = ""
    package: str = ""
    tappable: bool = False
    editable: bool = False
    bounds: Optional[list[int]] = None      # [x,y,w,h] (redroid); None for mock
    children: list["UiNode"] = field(default_factory=list)

    def flatten(self) -> list["UiNode"]:
        out = [self]
        for c in self.children:
            out.extend(c.flatten())
        return out


@dataclass
class Observation:
    package: str
    screen: str
    tree: UiNode
    screenshot_b64: Optional[str] = None    # only when the caveat allows


@dataclass
class ActionResult:
    ok: bool
    package: str
    screen: str
    detail: str = ""


class PhoneDriver(Protocol):
    """The wire an agent's actions ride. Backend-agnostic."""

    backend: str

    async def health(self) -> bool: ...

    async def reset(self) -> None:
        """Return the device to a known home state (new session)."""

    async def observe(self, *, want_screenshot: bool = False) -> Observation: ...

    async def launch(self, package: str) -> ActionResult: ...

    async def act(self, action_type: str, *, target: Optional[str] = None,
                  text: Optional[str] = None, **kw: Any) -> ActionResult:
        """Perform one action. action_type ∈ {tap,type,swipe,key,back,home,launch}.
        `target` is a UiNode.id (mock) or a resource-id/xpath (redroid)."""

    # D6-523, OPTIONAL: a driver that can say which of its actions reach the network implements
    #   network_use(action_type, *, target=None, text=None) -> Optional[str]
    # answering None (the action reaches no network), a host (it reaches that host) or "" (it reaches the network at an
    # address the driver cannot name), BEFORE the action runs. The router enforces the phone_no_network and
    # phone_allowed_domains caveats with it, and refuses to open a session under either caveat on a driver without it.
