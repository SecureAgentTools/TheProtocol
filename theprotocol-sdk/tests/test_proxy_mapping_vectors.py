"""V0664 consoles (C1, gwo_f1c49a39bfe4eaf7ce9d240d): the mapping's shared test vectors.

`tests/data/mapping_vectors.json` holds cases {name, covers, record, fields, expect | refusal [, never_contains]}: a record, a
mapping's `fields` (value nodes among them) and either what `mapping.apply` must give or the exact refusal text. The same file is
copied by scripts/distribution/gen_proxy_catalog.py into the console (src/data/proxy/mapping_vectors.generated.json), where the
TypeScript port of the value nodes (services/proxy/mapping.ts) runs every case too: a case the two languages read differently
fails one of the two suites. The expected values are WRITTEN BY HAND from the module's documented behaviour, never produced by
running the code, or the vectors would only repeat it.

Held here:
* every case gives exactly its expected value (a value, with a Decimal's exact text and a float's number) or its refusal text;
* a refusal never carries a value of the record (`never_contains`);
* the file covers every `as` type, every operation, the order of operations, concat, defaults, `required: false`, nested
  mappings and the paths a record has (a missing tag in `covers` fails this test, so a new operation needs its vector).
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime

import pytest

from theprotocol.proxy import mapping as M
from theprotocol.proxy.plugins import Record, Refused

DATA = pathlib.Path(__file__).resolve().parent / "data" / "mapping_vectors.json"
FILE = json.loads(DATA.read_text(encoding="utf-8"))
CASES = FILE["cases"]


def _record(doc: dict) -> Record:
    extra = {}
    if doc.get("observed_at"):                                                     # the record's time, an ISO text in the file
        extra["observed_at"] = datetime.fromisoformat(doc["observed_at"])
    return Record(record_id=doc.get("record_id", "r1"), payload=doc["payload"], source=doc.get("source", "legacy"),
                  meta=doc.get("meta") or {}, **extra)


def test_the_file_says_what_it_is():
    assert FILE["schema"] == "theprotocol.proxy.mapping-vectors/v1"
    assert len(CASES) >= 80
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names)), "a case name is used twice"
    for c in CASES:
        assert ("expect" in c) != ("refusal" in c), f"{c['name']}: exactly one of expect and refusal"
        assert set(c) <= {"name", "covers", "record", "fields", "expect", "refusal", "never_contains", "note"}, c["name"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_every_vector_gives_its_value_or_its_refusal(case):
    rec = _record(case["record"])
    if "refusal" in case:
        with pytest.raises(Refused) as e:
            M.apply(case["fields"], rec)
        assert str(e.value) == case["refusal"] or e.value.detail == case["refusal"]
        for secret in case.get("never_contains", []):
            assert secret not in str(e.value) and secret not in case["refusal"]
    else:
        got = M.apply(case["fields"], rec)
        assert json.loads(json.dumps(got)) == case["expect"]
        # a Decimal never leaves a value node as a Decimal: its exact text (the same fields feed the actions that call TheProtocol)
        assert json.dumps(got)                                                     # JSON-compatible all the way down


REQUIRED = (
    ["as:text", "as:int", "as:decimal", "as:float", "as:bool", "as:date", "as:datetime", "as:json"]
    + ["op:null_if", "op:trim", "op:case:upper", "op:case:lower", "op:case:title", "op:regex", "op:regex:group",
       "op:regex:default", "op:map", "op:map_default", "op:round", "op:format", "op:tz", "op:default", "op:required_false",
       "op:concat", "op:concat:sep"]
    + ["order:null_if-before-trim", "order:trim-case-regex-map-as-round", "order:map-before-as", "order:null-stays-null"]
    + ["path:payload", "path:record_id", "path:source", "path:meta", "path:observed_at", "path:list-index", "path:missing",
       "nested:object", "nested:list", "constant", "plain-dict-is-not-a-node", "bool-is-not-a-number", "refusal-never-has-value",
       "title-is-pythons", "round:half-even", "tz:summer-and-winter"]
)


def test_the_vectors_cover_every_type_every_operation_and_the_order():
    have = {t for c in CASES for t in c.get("covers", [])}
    assert [t for t in REQUIRED if t not in have] == []
    assert sum(1 for c in CASES if "refusal" in c) >= 20                                  # the refusals are half the contract
    assert any(c.get("never_contains") for c in CASES)


def test_every_value_node_key_has_a_case():
    """A key added to VALUE_KEYS without a vector is a hole in the contract the TypeScript port is checked against."""
    used = set()

    def walk(n):
        if isinstance(n, dict):
            if M.is_value_node(n):
                used.update(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    for c in CASES:
        walk(c["fields"])
    assert sorted(M.VALUE_KEYS - used) == []
