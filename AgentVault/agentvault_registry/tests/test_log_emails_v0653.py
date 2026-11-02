"""V0653 (am), item 7 (the hardening list in the sessions' room): no registry log call prints an e-mail address.

Log lines reach shared places (the container log, Dozzle, the backups), and 157 values in 41 files printed a person's
address whole (logins, registrations, recoveries, admin actions, the operator applications). Each goes through
core/log_identity.email_for_log now: the first character, the domain and a short hash, enough to tell two people apart
and to follow one through a flow, not enough to write to them. This gate reads every log call in the package (the AST:
f-string fields and %-style arguments) and refuses an address-named value (email, admin.email, ['email'],
.get('email')) that does not go through email_for_log; names that are not addresses (email_verified, email_sent, ...)
pass. BASE (a5ef48ddd, V0652): 157 values (5 of them the OAuth flow's, item 8's commit).
"""
from __future__ import annotations

import ast
import pathlib
import re

from agentvault_registry.core.log_identity import email_for_log

PKG = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
LOGGER = re.compile(r"(^|\.)_?(logger|log|logging)$")
EMAILISH = re.compile(r"(?i)e_?mail")
NOT_ADDRESS = re.compile(r"(?i)e_?mails?_?(verified|sent|enabled|count|ok|status|template|domain|type|kind|theme|subject|"
                         r"error|err|result|id|ids|hash|digest|len|length|n|total|on|off|mode|flag|ready|queued|failed|"
                         r"delivered|configured|provider|backend|server|host|port|from_name|settings|config|pattern|patterns)$")


def _ident(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return n.attr
    if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
        return n.slice.value
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args
            and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
        return n.args[0].value
    return ""


def _is_address(n):
    i = _ident(n)
    return bool(i) and bool(EMAILISH.search(i)) and not NOT_ADDRESS.search(i)


def scan_source(text: str, where: str = "<src>"):
    found = []
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS
                and LOGGER.search(ast.unparse(node.func.value))):
            continue
        for a in node.args:
            vals = [v.value for v in a.values if isinstance(v, ast.FormattedValue)] if isinstance(a, ast.JoinedStr) \
                else ([] if isinstance(a, ast.Constant) else [a])
            found += [f"{where}:{node.lineno}: prints {ast.unparse(v)}" for v in vals if _is_address(v)]
    return found


def test_no_registry_log_call_prints_an_address():
    files = sorted(PKG.rglob("*.py"))
    assert len(files) > 500                                   # a gate over nothing passes loudest
    found = []
    for p in files:
        try:
            found += scan_source(p.read_text(encoding="utf-8"), str(p.relative_to(PKG)))
        except SyntaxError:
            pass
    assert not found, "\n".join(found)


def test_the_gate_catches_each_shape_and_passes_the_wrapped_ones():
    planted = (
        "logger.info(f'login {email}')\n"
        "logger.warning(f'admin {admin.email} did it')\n"
        "log.info('reset for %s', developer.email)\n"
        "self.logger.error(f\"recover {body['email']} {data.get('user_email')}\")\n"
        "logger.info(f'ok {email_for_log(email)} verified={email_verified} sent={email_sent}')\n"
        "logger.info('x %s', email_for_log(dev.email))\n")
    got = [f.split(": ", 1)[1] for f in scan_source(planted)]
    assert got == ["prints email", "prints admin.email", "prints developer.email", "prints body['email']",
                   "prints data.get('user_email')"]


def test_the_helper_names_a_person_without_their_address():
    s = email_for_log("M.Someone@Example.org")
    assert s.startswith("m…@example.org #") and "someone" not in s
    assert email_for_log("m.someone@example.org") == s        # one person reads the same in every line
    assert email_for_log(None) == "email:none"
