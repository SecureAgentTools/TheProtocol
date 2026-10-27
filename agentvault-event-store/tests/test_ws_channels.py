"""D6-196 (2026-10-16): the WebSocket greeting advertises only channels the store publishes on.

The greeting (and the endpoint's docstring) listed a balance-update channel whose publisher had no caller, so a client
that subscribed to it waited for messages that never came. These tests read the source (no FastAPI, no database, like
test_mint_origin_rule.py): every channel in the greeting's `available_channels` must be one that
`EventPublisher.publish_event` (the publisher every stored event goes through) broadcasts to.

Run: python -m pytest tests/test_ws_channels.py -q   (needs pytest only)
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
if not (ROOT / "src").is_dir():
    ROOT = pathlib.Path("/app")
ROUTER = ROOT / "src" / "routers" / "websocket.py"
PUBLISHER = ROOT / "src" / "services" / "websocket_publisher.py"


def _shape(node: ast.AST) -> str:
    """A channel string or f-string with every placeholder written as {}."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    raise AssertionError(f"not a channel string: {ast.unparse(node)}")


def _advertised() -> set:
    fn = next(n for n in ast.walk(ast.parse(ROUTER.read_text()))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "websocket_endpoint")
    lists = [v for d in ast.walk(fn) if isinstance(d, ast.Dict)
             for k, v in zip(d.keys, d.values)
             if isinstance(k, ast.Constant) and k.value == "available_channels"]
    assert len(lists) == 1, "the greeting's available_channels list is not where it was"
    out = set()
    for el in lists[0].elts:
        name = _shape(el).split(" - ", 1)[0].strip()       # "events:{type} - Events of specific type"
        head, sep, _ = name.partition("{")
        out.add(head + ("{}" if sep else ""))
    return out


def _published() -> set:
    cls = next(n for n in ast.walk(ast.parse(PUBLISHER.read_text()))
               if isinstance(n, ast.ClassDef) and n.name == "EventPublisher")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "publish_event")
    shapes = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and ":" in n.value and " " not in n.value:
            shapes.add(n.value)
        elif isinstance(n, ast.JoinedStr):
            s = _shape(n)
            if ":" in s and " " not in s:
                shapes.add(s)
    return shapes


def test_the_publisher_names_its_channels():
    assert {"agent:{}", "events:all", "events:{}"} <= _published()


def test_every_advertised_channel_is_published_on():
    advertised, published = _advertised(), _published()
    assert advertised, "the greeting advertises no channel"
    dead = sorted(advertised - published)
    assert not dead, f"the greeting advertises channels nothing publishes on: {dead}"


def test_the_endpoint_docstring_lists_the_same_channels():
    fn = next(n for n in ast.walk(ast.parse(ROUTER.read_text()))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "websocket_endpoint")
    doc = ast.get_docstring(fn) or ""
    items = [line.strip()[2:] for line in doc.splitlines() if line.strip().startswith("- ")]
    listed = {item.split(" - ", 1)[0] for item in items if " - " in item and ":" in item.split(" - ", 1)[0]}
    shapes = {n.partition("{")[0] + ("{}" if "{" in n else "") for n in listed}
    assert shapes == _advertised(), f"docstring lists {sorted(shapes)}, the greeting {sorted(_advertised())}"
