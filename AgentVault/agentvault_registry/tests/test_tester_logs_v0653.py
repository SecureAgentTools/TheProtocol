"""V0653 (am), item 13 (the hardening list in the sessions' room): the API tester's log lines carry shapes, never values.

The tester ships in every registry image, and its lines reach the container's log (Dozzle, the backups). It printed whole
request bodies at INFO (the forced onboarding, agent-card, contract and builder bodies), the API-key creation answer whole
(its plain key, shown once), a bootstrap token whole, the obtained tokens, an invitation answer with its token, and token
and TOTP-secret prefixes (a prefix is part of the secret). api_tests/core/log_safe renders what a reader needs: shape()
for a body or an answer, secret() for a credential's presence and length, refusal() for a refusal's words.

This gate reads every log call in routers/admin_api_test.py and api_tests/ (the AST, so a comment never trips it) and
refuses one that prints json.dumps(...), a value named like a credential (a name, an attribute, or a constant key such as
['secret'] or .get('invitation_token')), or a whole body or answer by name, unless the expression goes through shape(),
secret(), refusal(), len(), bool() or .keys(). A response's .text is allowed only at WARNING and above: the registry's and
the TEG's error answers carry messages, not the values they refused (errors.py), and a success answer is never logged as
text. BASE (a5ef48ddd, V0652): the gate names every line above.
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
FILES = [ROOT / "routers" / "admin_api_test.py"] + sorted(p for p in (ROOT / "api_tests").rglob("*.py"))

LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
LOUD = {"warning", "error", "exception", "critical"}
LOGGER = re.compile(r"(^|\.)_?(logger|log|logging)$")
CRED = re.compile(r"(?i)(^|_)(token|tokens|secret|password|passwd|credentials?|creds|api_?key|plain_api_key|client_secret)$")
WHOLE = re.compile(r"(?i)(^|_)(body|payload|data|result|resp|response|key_data|create_data|invite_data|invite_resp|"
                   r"token_result|auth_resp|obtained_tokens|response_?data|responsedata)$")
SAFE_CALLS = {"shape", "secret", "refusal", "outcome", "len", "bool", "type"}
ESCAPE = re.compile(r"#\s*log-safe:\s*\S")   # on the call's lines, with its reason: a value that only LOOKS like one


def _ident(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _unwrap(node):
    """str(x), repr(x), x[:n], f(x)[..]: the value the line prints."""
    while True:
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            node = node.value
        elif isinstance(node, ast.Call) and _ident(node.func) in ("str", "repr") and node.args:
            node = node.args[0]
        else:
            return node


def _problems(call: ast.Call, method: str):
    out = []

    def walk(node):
        if isinstance(node, ast.Call):
            name = _ident(node.func)
            if name in SAFE_CALLS or (isinstance(node.func, ast.Attribute) and node.func.attr == "keys"):
                return
            if isinstance(node.func, ast.Attribute) and node.func.attr in ("dumps", "pformat"):
                out.append("prints a whole value (json.dumps)")
                return
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
                k = node.args[0]
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    if CRED.search(k.value) or WHOLE.search(k.value):
                        out.append(f"prints .get({k.value!r})")
                    return                          # the line prints that one field, not its container
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            k = node.slice.value
            if CRED.search(k) or WHOLE.search(k):
                out.append(f"prints [{k!r}]")
            return
        if isinstance(node, (ast.Name, ast.Attribute)) and CRED.search(_ident(node)):
            out.append(f"prints {_ident(node)}")
        if isinstance(node, ast.Attribute) and node.attr == "text" and method not in LOUD:
            out.append("prints a response's text below WARNING")
        if isinstance(node, ast.FormattedValue):
            v = _unwrap(node.value)
            if isinstance(v, (ast.Name, ast.Attribute)) and WHOLE.search(_ident(v)):
                out.append(f"prints all of {_ident(v)}")
        for child in ast.iter_child_nodes(node):
            walk(child)

    for a in list(call.args) + [k.value for k in call.keywords]:
        walk(a)
    return out


def _log_calls(p):
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    for node in ast.walk(ast.parse(text)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS
                and LOGGER.search(ast.unparse(node.func.value))):
            if any(ESCAPE.search(ln) for ln in lines[node.lineno - 1:node.end_lineno]):
                continue
            yield node


def scan(paths=FILES):
    found = []
    for p in paths:
        for node in _log_calls(p):
            for why in sorted(set(_problems(node, node.func.attr))):
                found.append(f"{p.relative_to(ROOT)}:{node.lineno}: {why}")
    return found


def test_no_tester_log_line_prints_a_value():
    found = scan()
    assert not found, "\n".join(found)


def test_the_gate_reads_files_and_catches_each_shape(tmp_path):
    assert len(FILES) > 50                                  # a gate over nothing passes loudest
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import json\n"
        "logger.info(f'created {json.dumps(key_data)}')\n"
        "logger.info(f'token {bootstrap_token[:20]}...')\n"
        "self.logger.info(f\"secret {self.flow_values.get('secret', 'N/A')[:10]}\")\n"
        "logger.info(f'invite {invite_data}')\n"
        "logger.info(f'ok {resp.text[:100]}')\n"
        "logger.info(f'fine {shape(key_data)} {secret(bootstrap_token)} {len(body)} {list(body.keys())}')\n"
        "logger.error(f'refused {resp.status_code}: {resp.text[:200]}')\n"
        "logger.info(f'type {token_type} expires {expires_in}')\n"
        "logger.info(f'kept {token}')  # log-safe: a file key, not a credential\n"
        "logger.info(f'kept {token}')  # log-safe:\n"
        "logger.info(f'ok {_ls.shape(body)} {_ls.secret(api_key)} {_ls.outcome(create_result)}')\n")
    found = [f.split(": ", 1)[1] for f in scan_file(planted)]
    assert found == ["prints a whole value (json.dumps)", "prints bootstrap_token", "prints .get('secret')",
                     "prints all of invite_data", "prints a response's text below WARNING",
                     "prints token"]                    # an escape without its reason does not count


def scan_file(p):
    out = []
    for node in _log_calls(p):
        out += [f"{node.lineno}: {w}" for w in sorted(set(_problems(node, node.func.attr)))]
    return sorted(out, key=lambda s: int(s.split(":")[0]))
