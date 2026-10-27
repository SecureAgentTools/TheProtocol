"""PHONE FABRIC — MockPhoneDriver: a deterministic scripted Android (2026-07-07).

The permanent test surface. Two apps ship:
  - com.vault.bank  : home → login → dashboard → transfer → done
  - com.acme.browser: home → address → page

Every screen returns a stable accessibility tree; every `act` transitions deterministically
(no randomness — reproducible in CI). No network, no real device. This is what lets the whole
capability→session→revoke→audit loop be tested headless without hardware.
"""
from __future__ import annotations

from typing import Any, Optional

from .driver import ActionResult, Observation, PhoneDriver, UiNode

HOME = "com.android.launcher"

# screen graph: (package, screen) -> {nodes, transitions}
# transitions: node_id -> (package, screen)
_APPS: dict[str, dict[str, dict]] = {
    "com.vault.bank": {
        "login": {
            "nodes": [
                UiNode(id="user", role="input", text="username", editable=True, tappable=True),
                UiNode(id="pass", role="input", text="password", editable=True, tappable=True),
                UiNode(id="signin", role="button", text="Sign in", tappable=True),
            ],
            "transitions": {"signin": ("com.vault.bank", "dashboard")},
        },
        "dashboard": {
            "nodes": [
                UiNode(id="bal", role="text", text="Balance: 4,210.00 BVT"),
                UiNode(id="to_transfer", role="button", text="Transfer", tappable=True),
                UiNode(id="logout", role="button", text="Log out", tappable=True),
            ],
            "transitions": {"to_transfer": ("com.vault.bank", "transfer"), "logout": ("com.vault.bank", "login")},
        },
        "transfer": {
            "nodes": [
                UiNode(id="amount", role="input", text="amount", editable=True, tappable=True),
                UiNode(id="send", role="button", text="Send", tappable=True),
                UiNode(id="back", role="button", text="Back", tappable=True),
            ],
            "transitions": {"send": ("com.vault.bank", "done"), "back": ("com.vault.bank", "dashboard")},
        },
        "done": {
            "nodes": [UiNode(id="ok", role="text", text="Transfer complete")],
            "transitions": {},
        },
    },
    "com.acme.browser": {
        "home": {
            "nodes": [
                UiNode(id="addr", role="input", text="url", editable=True, tappable=True),
                UiNode(id="go", role="button", text="Go", tappable=True),
            ],
            "transitions": {"go": ("com.acme.browser", "page")},
        },
        "page": {
            "nodes": [UiNode(id="content", role="text", text="Example page loaded")],
            "transitions": {},
        },
    },
}
_APP_ENTRY = {"com.vault.bank": "login", "com.acme.browser": "home"}
# D6-523: the screens reached by loading something from the network. The scripted browser loads its page when Go is
# pressed; it keeps no typed address between requests (its state is the app and the screen), so it cannot name the
# address that page came from.
_NETWORK_SCREENS = {("com.acme.browser", "page")}


class MockPhoneDriver:
    backend = "mock"

    def __init__(self, instance_id: str = "mock-0"):
        self.instance_id = instance_id
        self._pkg = HOME
        self._screen = "home"

    async def health(self) -> bool:
        return True

    async def reset(self) -> None:
        self._pkg, self._screen = HOME, "home"

    def restore(self, package: Optional[str], screen: Optional[str]) -> None:
        """Rehydrate driver state from the persisted session row (multi-worker safe).
        For redroid this is a no-op — the device itself holds the state."""
        if package and (package == HOME or package in _APPS):
            self._pkg = package
            self._screen = screen or (_APP_ENTRY.get(package) if package != HOME else "home")

    @property
    def state(self) -> tuple[str, str]:
        return self._pkg, self._screen

    def _tree(self) -> UiNode:
        if self._pkg == HOME:
            kids = [UiNode(id=f"icon:{p}", role="button", text=p.split('.')[-1], package=p, tappable=True) for p in _APPS]
            return UiNode(id="home", role="screen", package=HOME, children=kids)
        scr = _APPS[self._pkg][self._screen]
        return UiNode(id=self._screen, role="screen", package=self._pkg,
                      children=[n for n in scr["nodes"]])

    async def observe(self, *, want_screenshot: bool = False) -> Observation:
        shot = "iVBORw0KMOCK" if want_screenshot else None   # deterministic sentinel, not a real image
        return Observation(package=self._pkg, screen=self._screen, tree=self._tree(), screenshot_b64=shot)

    def network_use(self, action_type: str, *, target: Optional[str] = None,
                    text: Optional[str] = None) -> Optional[str]:
        """D6-523 (the driver contract's optional network_use): None when the action reaches no network, "" when it
        loads something from an address this scripted device cannot name (the browser's Go). Asked before the action."""
        at = (action_type or "").lower()
        if self._pkg == HOME or at not in ("tap", "key", "swipe", "back"):
            return None
        scr = _APPS.get(self._pkg, {}).get(self._screen)
        if scr is None:
            return None
        dest = scr["transitions"].get("back" if at == "back" else (target or ""))
        return "" if dest in _NETWORK_SCREENS else None

    async def launch(self, package: str) -> ActionResult:
        if package not in _APPS:
            return ActionResult(ok=False, package=self._pkg, screen=self._screen, detail=f"unknown package {package}")
        self._pkg, self._screen = package, _APP_ENTRY[package]
        return ActionResult(ok=True, package=self._pkg, screen=self._screen, detail="launched")

    async def act(self, action_type: str, *, target: Optional[str] = None,
                  text: Optional[str] = None, **kw: Any) -> ActionResult:
        at = action_type.lower()
        if at == "launch":
            return await self.launch(target or "")
        if at == "home":
            await self.reset()
            return ActionResult(ok=True, package=self._pkg, screen=self._screen, detail="home")
        if at == "back":
            # back from an app screen → its transition['back'] if any, else home
            if self._pkg != HOME:
                tr = _APPS[self._pkg][self._screen]["transitions"].get("back")
                if tr:
                    self._pkg, self._screen = tr
                    return ActionResult(ok=True, package=self._pkg, screen=self._screen, detail="back")
            await self.reset()
            return ActionResult(ok=True, package=self._pkg, screen=self._screen, detail="back->home")
        if self._pkg == HOME:
            # tapping an app icon on home launches it
            if at == "tap" and target and target.startswith("icon:"):
                return await self.launch(target.split(":", 1)[1])
            return ActionResult(ok=False, package=self._pkg, screen=self._screen, detail="nothing to do on home")
        scr = _APPS[self._pkg][self._screen]
        ids = {n.id for n in scr["nodes"]}
        if target and target not in ids:
            return ActionResult(ok=False, package=self._pkg, screen=self._screen, detail=f"no such node {target}")
        if at == "type":
            return ActionResult(ok=True, package=self._pkg, screen=self._screen, detail=f"typed into {target}")
        if at in ("tap", "key", "swipe"):
            tr = scr["transitions"].get(target or "")
            if tr:
                self._pkg, self._screen = tr
            return ActionResult(ok=True, package=self._pkg, screen=self._screen, detail=f"{at} {target}")
        return ActionResult(ok=False, package=self._pkg, screen=self._screen, detail=f"unknown action {at}")


def make_driver(backend: str, instance_handle: str) -> PhoneDriver:
    """Factory used by the router. redroid backend loads lazily (PF-C)."""
    if backend == "redroid":
        from .redroid_driver import RedroidPhoneDriver  # noqa: PLC0415 — optional, data-plane only
        return RedroidPhoneDriver(instance_handle)
    return MockPhoneDriver(instance_handle)
