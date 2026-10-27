"""Per-endpoint declarative contracts (AAA+ refactor 2026-05-21).

Each module in this package registers contracts via the @Endpoint decorator
in api_tests.core.contract. Importing this package (via load_all() below)
triggers registration of every contract into the contract_registry.

Usage:
    from agentvault_registry.api_tests.contracts import load_all
    load_all()  # call once at app startup
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)


def load_all() -> int:
    """Recursively import every submodule in this package + its subpackages.

    Returns the number of contracts registered after the load.
    """
    from ..core.contract import contract_count

    pkg_path = Path(__file__).resolve().parent
    pkg_name = __name__  # "agentvault_registry.api_tests.contracts"
    loaded = 0
    failed = 0

    for finder, module_name, ispkg in pkgutil.walk_packages([str(pkg_path)], prefix=f"{pkg_name}."):
        try:
            importlib.import_module(module_name)
            loaded += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to load contract module {module_name}: {e!r}")

    logger.info(
        f"AAA+ Contracts loaded: {loaded} modules ({failed} failed) => {contract_count()} registered endpoints"
    )
    return contract_count()
