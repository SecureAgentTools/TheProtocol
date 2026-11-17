"""V0662 (the route summaries the API tester shows, gwo_5bdeaea2226a32eb05b14899): the API tester page lists the registry's
route summaries from its live OpenAPI, and the generated API reference prints the same texts. Eleven of them, the
capability-permit routes, the act-as route, spawn and the bootstrap request, said "token" in the sense the console words
differently: the sign-in credential is an access key, a bootstrap key, and IronKey's L4 credential is a capability permit
(web console vocabulary gate: src/i18n/vocabulary.test.ts).

What is checked, for each of the eleven operations: the method and the path are exactly what they were (this is words
only; a path, a header name and a field name are identifiers and stay), the summary carries no stake or token word, and
the reference page prints the same summary in that route's row.
RED control: against f569f6a6e's texts all eleven summaries carry "token" (the bootstrap route's auto-made "Request
Bootstrap Token" included), and the page rows say the same.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

OPS = [
    ("post", "/api/v1/onboard/bootstrap/request-token"),
    ("post", "/api/v1/agents/act-token"),
    ("post", "/api/v1/agents/capabilities"),
    ("post", "/api/v1/agents/capabilities/consume"),
    ("get", "/api/v1/agents/capabilities/mine"),
    ("delete", "/api/v1/agents/capabilities/{token_id}"),
    ("post", "/api/v1/agents/capabilities/{token_id}/attenuate"),
    ("post", "/api/v1/agents/spawn"),
    ("get", "/api/v1/agents/{did}/capabilities"),
    ("post", "/api/v1/agents/{did}/capabilities/issue-as-owner"),
    ("delete", "/api/v1/agents/{did}/capabilities/{token_id}"),
]
# the console's value words, English (vocabulary.test.ts WORDS.en): a stake or a token; code in backticks is not read
WORD = re.compile(r"\b(?:un)?stak(?:e|ed|es|er|ers|ing)?\b|\btokens?\b", re.I)
REFERENCE = (Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "static" / "new_registry_frontend"
             / "src" / "assets" / "docs" / "reference" / "api.md")


@pytest.fixture(scope="module")
def schema():
    os.makedirs("/tmp/prom_multiproc_reg", exist_ok=True)
    from agentvault_registry.main import app
    app.openapi_schema = None
    try:
        yield app.openapi()
    finally:
        app.openapi_schema = None


@pytest.mark.parametrize("method,path", OPS)
def test_the_route_is_where_it_was_and_its_summary_uses_the_console_words(schema, method, path):
    ops = schema["paths"].get(path)
    assert ops is not None and method in ops, f"{method.upper()} {path} is not documented any more (words only: paths stay)"
    summary = ops[method].get("summary") or ""
    assert summary, f"{method.upper()} {path} has no summary"
    assert not WORD.search(re.sub(r"`[^`]*`", " ", summary)), f"{method.upper()} {path}: {summary!r}"


@pytest.mark.parametrize("method,path", OPS)
def test_the_reference_page_prints_the_same_summary(schema, method, path):
    summary = schema["paths"][path][method]["summary"]
    row = f"| {method.upper()} | `{path}` | {summary} |"
    assert row in REFERENCE.read_text(encoding="utf-8"), f"reference/api.md has no row {row!r}"
