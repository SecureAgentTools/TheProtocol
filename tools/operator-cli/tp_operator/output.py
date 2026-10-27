"""Output rendering — rich tables, JSON, quiet modes."""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

from rich.console import Console
from rich.table import Table


def detect_output_mode(
    force_json: bool = False,
    force_quiet: bool = False,
    no_color: bool = False,
) -> str:
    """Return one of: 'json', 'quiet', 'plain', 'rich'.

    Auto-detection per Operator_CLI_Strategy.md §3.4. 'quiet' (--quiet) prints errors only, on stderr: the exit code
    carries the verdict (CB-286: it used to mean plain text, which printed everything).
    """
    if force_json:
        return "json"
    if os.environ.get("TP_OPERATOR_JSON") in ("1", "true", "yes"):
        return "json"
    if os.environ.get("CI") == "true":
        return "json"
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "json"
    if os.environ.get("GITLAB_CI") == "true":
        return "json"
    if force_quiet:
        return "quiet"
    if os.environ.get("NO_COLOR"):
        return "plain"
    if no_color:
        return "plain"
    if not sys.stdout.isatty():
        return "plain"
    return "rich"


class Output:
    """Shared output sink for a single CLI invocation."""

    def __init__(self, mode: str = "rich"):
        self.mode = mode
        self.quiet = mode == "quiet"     # errors only; everything else below returns before it prints
        plain = mode in ("plain", "quiet")
        self.console = Console(no_color=plain, force_terminal=(mode == "rich"))
        self.err = Console(stderr=True, no_color=plain)

    def emit_json(self, obj: Any) -> None:
        """Print machine-readable JSON. Used in JSON mode."""
        if self.quiet:
            return
        print(json.dumps(obj, indent=2, default=str, sort_keys=True), flush=True)

    def line(self, text: str, style: Optional[str] = None) -> None:
        if self.quiet:
            return
        if self.mode == "rich":
            self.console.print(text, style=style)
        else:
            print(text, flush=True)

    def error(self, text: str) -> None:
        if self.mode == "rich":
            self.err.print(f"[bold red]ERROR:[/bold red] {text}")
        else:
            print(f"ERROR: {text}", file=sys.stderr, flush=True)

    def warn(self, text: str) -> None:
        if self.quiet:
            return
        if self.mode == "rich":
            self.err.print(f"[bold yellow]WARNING:[/bold yellow] {text}")
        else:
            print(f"WARNING: {text}", file=sys.stderr, flush=True)

    def success(self, text: str) -> None:
        if self.quiet:
            return
        if self.mode == "rich":
            self.console.print(f"[bold green]✓[/bold green] {text}")
        else:
            print(f"OK: {text}", flush=True)

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        if self.quiet:
            return
        if self.mode == "rich":
            t = Table(title=title, show_header=True, header_style="bold cyan")
            for c in columns:
                t.add_column(c)
            for r in rows:
                t.add_row(*r)
            self.console.print(t)
        else:
            print(title)
            print("\t".join(columns))
            for r in rows:
                print("\t".join(r))
