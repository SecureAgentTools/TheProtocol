"""`tp-proxy migrate ...`: the subcommands' arguments, and how their answers print (text, or JSON with --json)."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

import httpx

from ..plugins import PluginError
from . import commands as C
from . import reports

HELP = """Move a system's data off it: a kit (migration.yaml, proxy.yaml, README.md, sample/) reads system A and writes
system B through the proxy's writers. Try a kit free on its sample (no account, no system at all):
  tp-proxy migrate new my-move --from sql --to sql          (an empty skeleton)
  tp-proxy migrate new --from-starter sql-to-postgres my-move   (a ready kit: see --list-starters)
  tp-proxy migrate dry-run my-move --sample
then against your own systems: plan, dry-run (writes only under KIT/.migrate/scratch/), load, reconcile, certify.
A kit holds no action and no TheProtocol source, so a kit from a stranger can never act as your agent or move
value: it reads system A and writes system B only, with sql_upsert, file_out or rest.
Exit codes: 0 pass or done, 1 a check failed or was refused, 2 a usage or spec error, 3 not measured."""


def add(sub: Any) -> None:
    p = sub.add_parser("migrate", help="move a system's data to another system with a kit (try one free: --sample)",
                       description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    ms = p.add_subparsers(dest="mcmd", required=True)

    def cmd(name: str, help_: str, *, kit: bool = True, params: bool = True) -> argparse.ArgumentParser:
        s = ms.add_parser(name, help=help_)
        if kit:
            s.add_argument("kit", nargs="?", help="the kit's folder (default: here)")
        if params:
            s.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="a parameter's value")
            s.add_argument("--params", metavar="FILE", help="parameters, one KEY=VALUE per line")
        s.add_argument("--json", action="store_true", help="print the answer or report as JSON")
        return s

    s = cmd("new", "scaffold a kit for a kind pair (sql to sql, file to sql, sql to rest), or write a starter kit", kit=False, params=False)
    s.add_argument("name", nargs="?", help="the new kit's name (with --from-starter: the folder to write it to)")
    s.add_argument("--from", dest="from_kind", choices=["sql", "file", "rest"])
    s.add_argument("--to", dest="to_kind", choices=["sql", "file", "rest"])
    s.add_argument("--out", help="the folder (default: ./NAME)")
    s.add_argument("--force", action="store_true")
    s.add_argument("--from-starter", dest="from_starter", metavar="NAME",
                   help="write one of the three starter kits that ship in the package (sql-to-postgres, csv-to-postgres, sql-to-rest)")
    s.add_argument("--list-starters", dest="list_starters", action="store_true", help="list the starter kits, one line each")
    s = cmd("get", "download a kit from a template library and check its content hash", kit=False, params=False)
    s.add_argument("template", help="the template's id")
    s.add_argument("--registry", help="the registry (default: the --identity spec's, else $TP_PROXY_REGISTRY)")
    s.add_argument("--version", type=int)
    s.add_argument("--out")
    s.add_argument("--identity", help="a proxy.yaml whose agent is used (for a paid template)")
    s.add_argument("--force", action="store_true")
    cmd("check", "the manifest, the spec with parameters filled, the caps")
    s = cmd("plan", "inventory: rows and fields per source, mapping coverage")
    s.add_argument("--sample", action="store_true", help="read the kit's samples instead of system A")
    s = cmd("dry-run", "the load into scratch targets under KIT/.migrate/scratch/, then reconcile against them")
    s.add_argument("--sample", action="store_true", help="the kit's samples stand in for system A")
    s.add_argument("--limit", type=int, help="at most N records per source")
    s = cmd("load", "the real load, exactly once, resumable (after its destinations are confirmed)")
    s.add_argument("--confirm-destinations", action="store_true",
                   help="you have read where the rows go (check lists them) and want them sent there")
    cmd("reconcile", "both sides read back and compared by key")
    s = cmd("rollback", "put the SQL targets' rows back as they were before the load")
    s.add_argument("--yes", action="store_true", help="yes, put them back")
    s = cmd("certify", "a migration.certificate attestation from the newest reports", params=False)
    s.add_argument("--identity", help="a proxy.yaml whose registry and agent are used")
    s = cmd("publish", "create the template (or a new version of it), then publish it", params=False)
    s.add_argument("--identity", help="a proxy.yaml whose registry and agent are used")
    s.add_argument("--visibility", choices=["private", "org", "unlisted", "public"])
    s.add_argument("--price", type=float, help="0 (free) or the price of one purchase")
    s.add_argument("--fork-share-bps", type=int, help="the share of a fork's sales its parent's author gets (0..5000)")
    s.add_argument("--changelog", default="")
    s = cmd("fork", "fork a template in the library, then get the fork", kit=False, params=False)
    s.add_argument("template")
    s.add_argument("--slug", help="the fork's slug (default: the parent's slug with -fork)")
    s.add_argument("--identity", help="a proxy.yaml whose registry and agent are used")
    s.add_argument("--out")
    s.add_argument("--force", action="store_true")


def _call(a: Any, transport: Optional[httpx.AsyncBaseTransport]):
    m = a.mcmd
    kw: Dict[str, Any] = {}
    if hasattr(a, "set"):
        kw = {"sets": a.set, "params_file": a.params}
    if m == "new":
        if a.list_starters:
            return C.cmd_list_starters()
        if a.from_starter:
            if a.from_kind or a.to_kind:
                raise C.Stop(C.EXIT_USAGE, ["--from-starter takes no --from or --to: a starter has its own kinds"])
            if a.name and a.out:
                raise C.Stop(C.EXIT_USAGE, ["name the folder once: the argument or --out, not both"])
            return C.cmd_new_starter(a.from_starter, a.name or a.out, a.force)
        if not (a.name and a.from_kind and a.to_kind):
            raise C.Stop(C.EXIT_USAGE, ["new needs NAME, --from and --to (or --from-starter NAME, or --list-starters)"])
        return C.cmd_new(a.name, a.from_kind, a.to_kind, a.out, a.force)
    if m == "get":
        return C.cmd_get(a.template, registry=a.registry, version=a.version, out=a.out, identity=a.identity,
                         force=a.force, transport=transport)
    if m == "check":
        return C.cmd_check(a.kit, **kw)
    if m == "plan":
        return C.cmd_plan(a.kit, sample=a.sample, **kw)
    progress = None if a.json or not sys.stderr.isatty() else _progress
    if m == "dry-run":
        return C.cmd_dry_run(a.kit, sample=a.sample, limit=a.limit, progress=progress, **kw)
    if m == "load":
        ask = None if a.json or not sys.stdin.isatty() else _ask
        return C.cmd_load(a.kit, confirm_destinations=a.confirm_destinations, ask=ask, progress=progress, **kw)
    if m == "reconcile":
        return C.cmd_reconcile(a.kit, **kw)
    if m == "rollback":
        return C.cmd_rollback(a.kit, yes=a.yes, **kw)
    if m == "certify":
        return C.cmd_certify(a.kit, identity=a.identity, transport=transport)
    if m == "publish":
        return C.cmd_publish(a.kit, identity=a.identity, visibility=a.visibility, price=a.price,
                             fork_share_bps=a.fork_share_bps, changelog=a.changelog, transport=transport)
    if m == "fork":
        return C.cmd_fork(a.template, identity=a.identity, out=a.out, force=a.force, slug=a.slug,
                          transport=transport)
    raise C.Stop(C.EXIT_USAGE, [f"no migrate command {m!r}"])  # pragma: no cover


def _progress(line: str) -> None:
    """On a terminal, every few seconds of a run: where it is (counts only)."""
    print(f"tp-proxy migrate: {line}", file=sys.stderr, flush=True)


def _ask(lines: Any) -> bool:
    """On a terminal: the destinations, then a yes or no."""
    print("load sends your rows here:", file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)
    try:
        return input("Send them? Type yes: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _text(code: int, ans: Dict[str, Any]) -> str:
    from .destinations import lines as dest_lines
    if ans.get("schema") == reports.REPORT_SCHEMA_ID:
        lines = reports.text_lines(ans)
        if ans.get("destinations"):
            lines += [f"  {x}" for x in dest_lines(ans["destinations"])]
        if ans.get("written"):
            lines.append(f"  report: {ans['written']}")
        return "\n".join(lines)
    if ans.get("problems"):
        return "\n".join(f"tp-proxy migrate: {p}" for p in ans["problems"])
    if "starters" in ans:
        width = max(len(x["name"]) for x in ans["starters"])
        return "\n".join(f"{x['name'].ljust(width)}  {x['title']}" for x in ans["starters"])
    out = []
    for k, v in ans.items():
        if k == "destinations" and v:
            out.append("destinations:")
            out += [f"  {x}" for x in dest_lines(v)]
            continue
        out.append(f"{k}: {v if isinstance(v, (str, int, float)) or v is None else json.dumps(v, ensure_ascii=False)}")
    return "\n".join(out)


def run(a: Any, transport: Optional[httpx.AsyncBaseTransport] = None) -> int:
    try:
        code, ans = _call(a, transport)
    except C.Stop as e:
        code, ans = e.code, {"problems": e.problems, **e.extra}
    except PluginError as e:
        code, ans = C.EXIT_FAILED, {"problems": [str(e)]}
    if getattr(a, "json", False):
        print(json.dumps({"exit": code, **ans}, indent=1, ensure_ascii=False, default=str))
    else:
        print(_text(code, ans), file=sys.stderr if ans.get("problems") else sys.stdout)
    return code
