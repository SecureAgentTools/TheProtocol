"""The three starter kits (V0665: tp-proxy migrate new --from-starter NAME).

proxy/migrations/ in the SDK's source tree is the ONE source. A wheel is built with the three kits copied into the package
(pyproject.toml's force-include puts them at theprotocol/proxy/migrate/starter_kits/), so `pip install theprotocol-sdk[proxy]`
carries them; a source checkout reads the same folders where they are. A test builds the wheel and fails when a file in it
differs from the source's, byte for byte.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import Kit, KitError, load_kit

# the order the docs list them in
STARTERS = ("sql-to-postgres", "csv-to-postgres", "sql-to-rest")


def starters_dir() -> Optional[Path]:
    """The folder that holds the starters: the package's own copy (an installed wheel), else the source tree's (a checkout)."""
    here = Path(__file__).resolve().parent / "starter_kits"
    if here.is_dir():
        return here
    repo = Path(__file__).resolve().parents[4] / "proxy" / "migrations"      # src/theprotocol/proxy/migrate/ -> the SDK's root
    return repo if repo.is_dir() else None


def starter_kit(name: str) -> Kit:
    """A starter, loaded and checked like any kit (KitError names what is wrong; a missing folder is that too)."""
    root = starters_dir()
    if root is None or name not in STARTERS or not (root / name).is_dir():
        raise KitError([f"the starter {name!r} is not in this installation"])
    return load_kit(root / name)


def listing() -> List[Dict[str, Any]]:
    """Each starter with its title and summary (from its own migration.yaml) and its content hash."""
    out = []
    for name in STARTERS:
        k = starter_kit(name)
        out.append({"name": name, "title": k.manifest.get("title") or name, "summary": k.manifest.get("summary") or "",
                    "content_hash": k.content_hash})
    return out
