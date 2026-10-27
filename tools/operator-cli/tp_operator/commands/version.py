"""tp-operator version — print version + bundle info."""
from __future__ import annotations

import typer

from .. import __schema_version__, __version__
from ..output import Output, detect_output_mode


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="version", help="Print CLI + schema versions.")
    def version_cmd():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        info = {
            "cli_version": __version__,
            "schema_version": __schema_version__,
        }
        if out.mode == "json":
            out.emit_json(info)
        else:
            out.line(f"tp-operator {__version__} (schema {__schema_version__})")
        raise typer.Exit(code=0)
