"""Where a kit sends your rows, and who named it (V0664 M11): a template from a stranger never sends your data anywhere
you did not name.

A kit's writers name their destination in proxy.yaml (a rest url, a sql_upsert host and database or sqlite path, a
file_out folder and its SFTP host). A published kit could carry a literal, or a parameter default, that points at
someone else's server: the dry run is safe (it writes only to scratch twins), but a real load sends the rows.

So every destination is listed after the parameters are filled, with its origin:

    "you"       every part of it that says where (the host, the database, the path, the url's host) is a parameter
                YOU gave, with --set or --params
    "template"  it came from the kit itself: a literal in proxy.yaml, or a parameter's default ("named by the
                template, not by you")

`load` starts only after the destinations are confirmed (--confirm-destinations, or a yes to the list on a terminal),
and for a kit that came from a library (get or fork, remembered in .migrate/template.json while its files are
unchanged) a destination named by the template refuses the load even then, until you set that parameter yourself.
Each source's location is listed the same way (a source only reads, so its origin is shown, never refused).
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set

from .params import PLACEHOLDER

YOU, TEMPLATE = "you", "template"
NAMED_BY_TEMPLATE = "named by the template, not by you"


def _whole(raw: Any) -> Optional[str]:
    """The parameter name when the raw value is exactly one placeholder, else None."""
    m = PLACEHOLDER.fullmatch(raw) if isinstance(raw, str) else None
    return m.group(1) if m else None


def _part_origin(raw: Any, user: Set[str]) -> Dict[str, Any]:
    """Who named one part (a host, a database, a path): `you` only when it is exactly one placeholder you set."""
    name = _whole(raw)
    if name is not None and name in user:
        return {"origin": YOU}
    return {"origin": TEMPLATE, "parameter": name}     # a default (parameter named), or a literal (None)


def _url_origin(raw: Any, user: Set[str]) -> Dict[str, Any]:
    """A url is yours when the whole url is a placeholder you set, or when its scheme-and-host part is made only of
    placeholders you set (https://${HOST}/v1/customers/{id}); a literal host is the template's."""
    name = _whole(raw)
    if name is not None:
        return {"origin": YOU} if name in user else {"origin": TEMPLATE, "parameter": name}
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*://)?([^/?#]*)", str(raw or ""))
    host = m.group(2) if m else ""
    names = PLACEHOLDER.findall(host)
    rest = PLACEHOLDER.sub("", host).replace(":", "")
    if names and all(n in user for n in names) and not rest.strip("0123456789"):
        return {"origin": YOU}
    missing = [n for n in names if n not in user]
    return {"origin": TEMPLATE, "parameter": missing[0] if missing else None}


def _merge(*parts: Dict[str, Any]) -> Dict[str, Any]:
    for p in parts:
        if p["origin"] == TEMPLATE:
            return p
    return {"origin": YOU}


def _sql_where(cfg: Mapping[str, Any], table: Optional[str]) -> str:
    engine = str(cfg.get("engine") or "")
    if engine == "sqlite":
        return f"sqlite:{cfg.get('path')}" + (f" table {table}" if table else "")
    p = cfg.get("port") or (cfg.get("connect_args") or {}).get("port")   # a port given through connect_args too
    port = f":{p}" if p else ""
    return f"{engine}://{cfg.get('host')}{port}/{cfg.get('database') or ''}" + (f"/{table}" if table else "")


def _sql_origin(cfg_raw: Mapping[str, Any], user: Set[str], engine: str) -> Dict[str, Any]:
    """`engine` is the FILLED one: a kit whose engine is ${TARGET_ENGINE} keeps both path and host in its raw config,
    and only the engine chosen says which of them is the destination."""
    if engine == "sqlite":
        return _part_origin(cfg_raw.get("path"), user)
    return _merge(_part_origin(cfg_raw.get("host"), user), _part_origin(cfg_raw.get("database"), user))


def _url_where(method: str, url: str) -> str:
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ""
    port = f":{u.port}" if u.port else ""
    return f"{method} {u.scheme}://{host}{port}{u.path}"      # no userinfo, no query: where, never a credential


def _sftp_where(s: Mapping[str, Any]) -> str:
    port = f":{s['port']}" if s.get("port") else ""
    return f"sftp://{s.get('host')}{port}/{str(s.get('path') or '').lstrip('/')}"


def writer(name: str, type_: str, cfg: Mapping[str, Any], raw: Mapping[str, Any], user: Set[str]) -> Dict[str, Any]:
    if type_ == "sql_upsert":
        where, who = _sql_where(cfg, cfg.get("table")), _sql_origin(raw, user, str(cfg.get("engine") or ""))
    elif type_ == "rest":
        method = str(cfg.get("method") or "POST")
        where, who = _url_where(method, str(cfg.get("url") or "")), _url_origin(raw.get("url"), user)
    elif type_ == "file_out":
        where, who = f"folder {cfg.get('path')}", _part_origin(raw.get("path"), user)
        if cfg.get("sftp"):
            s, sr = cfg["sftp"], raw.get("sftp") or {}
            where += f", then {_sftp_where(s)}"
            who = _merge(who, _part_origin(sr.get("host"), user))
    else:
        where, who = f"{type_} (not a writer a kit may use)", {"origin": TEMPLATE, "parameter": None}
    return {"role": "writer", "name": name, "type": type_, "where": where, **who}


def source(name: str, type_: str, cfg: Mapping[str, Any], raw: Mapping[str, Any], user: Set[str]) -> Dict[str, Any]:
    if type_ == "sqlpoll":
        where, who = _sql_where(cfg, cfg.get("table")), _sql_origin(raw, user, str(cfg.get("engine") or ""))
    elif type_ == "filedrop":
        where, who = f"folder {cfg.get('path')}", _part_origin(raw.get("path"), user)
    elif type_ == "sftp":
        where, who = _sftp_where(cfg), _part_origin(raw.get("host"), user)
    elif type_ == "webhook":
        where, who = f"receives POSTs on {cfg.get('path')}", {"origin": TEMPLATE, "parameter": None}
    else:
        where, who = type_, {"origin": TEMPLATE, "parameter": None}
    return {"role": "source", "name": name, "type": type_, "where": where, **who}


def listing(filled: Mapping[str, Any], raw: Mapping[str, Any], user: Iterable[str]) -> List[Dict[str, Any]]:
    """Every writer's destination and every source's location, filled, each with its origin (and, for one the
    template named through a parameter, that parameter)."""
    u = set(user)
    out = []
    for kind, fn in (("sinks", writer), ("sources", source)):
        for n, s in (filled.get(kind) or {}).items():
            r = ((raw.get(kind) or {}).get(n) or {}).get("config") or {}
            d = fn(n, s.get("type"), s.get("config") or {}, r, u)
            if d["origin"] == TEMPLATE:
                d["note"] = NAMED_BY_TEMPLATE
            else:
                d.pop("parameter", None)
            out.append(d)
    return out


def lines(dests: List[Mapping[str, Any]]) -> List[str]:
    out = []
    for d in dests:
        who = "set by you" if d["origin"] == YOU else NAMED_BY_TEMPLATE + (
            f" (parameter {d['parameter']}: its default)" if d.get("parameter") else " (written in proxy.yaml)")
        out.append(f"{'writes to' if d['role'] == 'writer' else 'reads from'} {d['where']}  [{d['name']}: {who}]")
    return out


def refusals(dests: List[Mapping[str, Any]], *, library: bool) -> List[str]:
    """For a kit from a library: each writer destination the template named, and what lifts it."""
    if not library:
        return []
    out = []
    for d in dests:
        if d["role"] != "writer" or d["origin"] != TEMPLATE:
            continue
        if d.get("parameter"):
            out.append(f"{d['name']} writes to {d['where']}, {NAMED_BY_TEMPLATE}: this kit came from a library, so a "
                       f"load sends nothing there until you set {d['parameter']} yourself (--set {d['parameter']}=... "
                       f"or --params FILE)")
        else:
            out.append(f"{d['name']} writes to {d['where']}, written into the kit's proxy.yaml by the template: this kit "
                       f"came from a library, so a load refuses it; make it a parameter you set (fork the kit, or edit "
                       f"proxy.yaml, which makes it your own kit)")
    return out


def template_wheres(files: Mapping[str, str]) -> Dict[str, str]:
    """name -> where, for every writer and source of the kit AS THE TEMPLATE SHIPPED IT: its literals and its
    parameters' defaults (a parameter with no default stays a placeholder, so it matches nothing a user fills in)."""
    import yaml
    from .params import fill_known
    manifest = yaml.safe_load(files.get("migration.yaml") or "") or {}
    doc = yaml.safe_load(files.get("proxy.yaml") or "") or {}
    if not isinstance(doc, dict) or not isinstance(manifest, dict):
        return {}
    defaults = {n: p["default"] for n, p in (manifest.get("parameters") or {}).items()
                if isinstance(p, dict) and "default" in p}
    filled = fill_known(doc, defaults)
    return {f"{d['role']}:{d['name']}": d["where"] for d in listing(filled, doc, set())}


def follow_the_value(dests: List[Dict[str, Any]], shipped: Mapping[str, str]) -> List[Dict[str, Any]]:
    """For a library kit: a destination is the template's when its VALUE is the one the template ships (its literal
    or its default) and you did not set it yourself, whatever else in the kit you changed; a destination whose value
    you changed (by editing the kit) is yours."""
    out = []
    for d in dests:
        d = dict(d)
        if d["origin"] == TEMPLATE and shipped.get(f"{d['role']}:{d['name']}") != d["where"]:
            d = {k: v for k, v in d.items() if k not in ("parameter", "note")}
            d["origin"], d["changed_from_template"] = YOU, True
        out.append(d)
    return out
