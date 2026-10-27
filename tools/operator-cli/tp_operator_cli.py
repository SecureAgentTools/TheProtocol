#!/usr/bin/env python3
"""tp-operator entrypoint wrapper — used by PyInstaller spec.

Imports the typer app from the tp_operator package so relative imports
within the package work correctly when frozen.
"""
from tp_operator.main import app


if __name__ == "__main__":
    app()
