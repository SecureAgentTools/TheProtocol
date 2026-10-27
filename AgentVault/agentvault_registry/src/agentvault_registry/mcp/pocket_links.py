"""§POCKETBRIDGE3 (WS-C3) — deep links from MCP tool results into Pocket.

A Claude answer on the phone should open the exact Pocket surface it talks
about, so a handful of tool results carry `open_in_app`. Purely additive keys
(no pydantic response models on the MCP path, and the curated outputSchemas
set additionalProperties true) — existing consumers are untouched.

URL discipline mirrors core/public_url.py: the baked BASE_URL default is a
TRUTHY loopback, so only a non-loopback PUBLIC_URL/BASE_URL yields an absolute
link; otherwise the link is app-relative (still correct when pasted after the
registry origin).
"""
import os


def _base() -> str:
    for var in ("PUBLIC_URL", "BASE_URL"):
        v = (os.getenv(var) or "").strip().rstrip("/")
        if v and "localhost" not in v and "127.0.0.1" not in v:
            return v
    return ""


def pocket_link(path: str) -> str:
    """`path` like '/pocket/payments?order=42' → absolute /ui# deep link when possible."""
    return f"{_base()}/ui#{path}"


def with_pocket_link(result, path: str):
    """Merge open_in_app into a dict result; anything else passes through untouched."""
    if isinstance(result, dict) and "error" not in result:
        return {**result, "open_in_app": pocket_link(path)}
    return result
