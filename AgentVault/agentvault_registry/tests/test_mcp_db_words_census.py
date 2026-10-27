"""§MCPTEST30 (V0525, 2026-10-01) — the census finds a database driver's own words in any answer (kind `db_words`).

Measured on sbx-alpha (V0521): getProposalDetail answered 500 "Failed to retrieve proposal: (sqlalchemy.dialects.
postgresql.asyncpg.Error) invalid input for query argument $1: 2147483648 (value out of int32 range)". The product's
guard (errors.withheld_db_words) and the census use the same pattern; this file pins them equal.
"""
from __future__ import annotations

from agentvault_registry import errors
from agentvault_registry.api_tests.contracts import credential_exposure as CE

MEASURED = ("Error: HTTP 500: Failed to retrieve proposal: (sqlalchemy.dialects.postgresql.asyncpg.Error) invalid input "
            "for query argument $1: 2147483648 (value out of int32 range)")


def _answer(text, err=True):
    return {"jsonrpc": "2.0", "id": 1, "result": {"isError": err, "content": [{"type": "text", "text": text}]}}


def test_the_census_and_the_product_guard_read_the_same_words():
    assert CE.DB_WORDS.pattern == errors._DB_ERROR_WORDS.pattern


def test_the_scan_finds_the_words_and_keeps_only_kind_and_path():
    found = list(CE.scan(_answer(MEASURED)))
    assert (CE.DB_WORDS_KIND, "result.content[0].text") in found
    assert all("2147483648" not in k and "2147483648" not in p for k, p in found)
    assert not [k for k, _p in CE.scan(_answer("Error: HTTP 422: A path or query parameter value is out of range"))
                if k == CE.DB_WORDS_KIND]
    inner = list(CE.scan(_answer('{"rows": [], "error": "x [SQL: SELECT 1]"}', err=False)))
    assert (CE.DB_WORDS_KIND, "result.content[0].text.error") in inner


def test_who_may_show_them():
    assert CE.classify("theprotocol_getProposalDetail", CE.DB_WORDS_KIND) == "unexpected"
    admin_only = sorted(CE.admin_only_tools())
    assert admin_only, "the admin bridge's own tools are known"
    assert CE.classify(admin_only[0], CE.DB_WORDS_KIND) == "informational"   # log and event readers show stored errors


def test_the_sentences_name_what_was_found():
    r = CE.row_reason("theprotocol_getProposalDetail", ["db_words at content[*].text"])
    assert r.startswith("BUG-FIND: database words:") and "credential" not in r
    both = CE.row_reason("theprotocol_x", ["field:client_secret at secret", "db_words at text"])
    assert "credential exposure" in both and "database words" in both
    summary = {"unexpected": {"theprotocol_getProposalDetail": ["db_words at content[*].text"],
                              "theprotocol_resetApiTestFlowValues": ["field:refresh_token at cleared_values.refresh_token"]}}
    v = CE.verdict_text(summary)
    assert "BUG-FIND: credential exposure: 1 tool(s)" in v and "BUG-FIND: database words: 1 tool(s)" in v
    assert "getProposalDetail" in v and "2147483648" not in v


def test_the_collector_records_a_database_leak_under_its_tool():
    tok = CE.begin()
    CE.record("theprotocol_getProposalDetail", _answer(MEASURED))
    box = CE.end(tok)
    s = CE.summarize(box)
    assert s["unexpected"] == {"theprotocol_getProposalDetail": ["db_words at <result>"]}   # the tool's own text


def test_exception_words_are_counted_as_informational_until_a_round_measures_them():
    found = list(CE.scan(_answer("Error: HTTP 500: Failed to list: 'NoneType' object has no attribute 'id'")))
    assert (CE.EXCEPTION_WORDS_KIND, "result.content[0].text") in found
    assert CE.classify("theprotocol_getProposalDetail", CE.EXCEPTION_WORDS_KIND) == "informational"
    both = list(CE.scan(_answer(MEASURED + " Traceback (most recent call last)")))
    assert [k for k, _p in both if k in (CE.DB_WORDS_KIND, CE.EXCEPTION_WORDS_KIND)] == [CE.DB_WORDS_KIND]   # one kind per text
    assert not [k for k, _p in CE.scan(_answer("Error: HTTP 422: Value error, must be positive"))
                if k == CE.EXCEPTION_WORDS_KIND]
