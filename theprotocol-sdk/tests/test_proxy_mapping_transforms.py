"""V0664 (Migrate a system, M2, gwo_dd34207af11011b6eb263652): field transforms in a mapping, pure, no eval.

A field node that is a dict whose keys are ALL in VALUE_KEYS and that has `path` (a string starting with $) or `concat` (a list) is a
VALUE NODE: read the path -> null_if -> trim -> case -> regex + group -> map + map_default -> as (+ format, tz) -> round. Every other
dict stays a nested object exactly as before, and every existing recipe maps byte-identically (pinned below against a frozen copy of
the code before this change). A refusal names the mapping's field and the rule and NEVER the record's value. Value nodes are checked
at spec load, not at the first record.
RED on stack master ed708438: mapping.VALUE_KEYS and the transforms do not exist.
"""
from __future__ import annotations

import pathlib
from typing import Any, Mapping

import pytest
import yaml

from theprotocol.proxy import mapping as M
from theprotocol.proxy.plugins import Record, Refused

SECRET = "ZZ-SENTINEL-QQ"


def _rec(payload):
    return Record(record_id="r1", payload=payload, source="legacy")


def _one(node, payload):
    return M.apply({"f": node}, _rec(payload))["f"]


def _refusal(node, payload):
    with pytest.raises(Refused) as e:
        _one(node, payload)
    return e.value.detail


P = "$.payload.v"


def _n(**kw):
    return {"path": P, **kw}


# ── what is a value node ──────────────────────────────────────────────────────────────────────────────────────

def test_the_value_keys_are_the_contract():
    assert M.VALUE_KEYS == {"path", "default", "required", "as", "format", "tz", "trim", "case", "map", "map_default", "null_if",
                            "round", "regex", "group", "concat", "sep"}


@pytest.mark.parametrize("node, yes", [
    ({"path": "$.payload.a"}, True),
    ({"path": "$.payload.a", "default": None}, True),
    ({"path": "$.payload.a", "as": "int", "trim": True}, True),
    ({"concat": ["$.payload.a", "-", "$.payload.b"]}, True),
    ({"path": "payload.a"}, False),                      # no leading $: a nested object, as today
    ({"path": "$.payload.a", "extra": 1}, False),        # a key outside VALUE_KEYS: a nested object, as today
    ({"as": "int"}, False),                              # no path and no concat
    ({"concat": "x"}, False),                            # concat is a list
    ({"a": "$.payload.a"}, False),
])
def test_which_dicts_are_value_nodes(node, yes):
    assert M.is_value_node(node) is yes


def test_a_dict_that_is_not_a_value_node_is_a_nested_object_exactly_as_before():
    out = M.apply({"f": {"path": "$.payload.a", "extra": "$.payload.b"}, "g": {"x": {"y": "$.payload.a"}}},
                  _rec({"a": 1, "b": 2}))
    assert out == {"f": {"path": 1, "extra": 2}, "g": {"x": {"y": 1}}}


def test_the_exactly_once_key_does_not_change():
    assert M.key_for("s", "r", "m", 1) == M.key_for("s", "r", "m", 1)
    assert M.key_for("s", "r", "m", 1).startswith("tpx-") and len(M.key_for("s", "r", "m", 1)) == 44


# ── the legacy behaviour, pinned ──────────────────────────────────────────────────────────────────────────────

def _legacy_map(node: Any, doc: Any, where: str) -> Any:
    """The mapping code as it was before V0664 (frozen copy)."""
    if isinstance(node, str) and node.startswith("$"):
        v = M.lookup(doc, node)
        if v is M._MISSING:
            raise Refused(f"the record has no {node} (the mapping's field {where})")
        return v
    if isinstance(node, Mapping) and "path" in node and set(node) <= {"path", "default"}:
        v = M.lookup(doc, str(node["path"]))
        if v is M._MISSING:
            if "default" in node:
                return node["default"]
            raise Refused(f"the record has no {node['path']} (the mapping's field {where})")
        return v
    if isinstance(node, Mapping):
        return {k: _legacy_map(v, doc, f"{where}.{k}" if where else str(k)) for k, v in node.items()}
    if isinstance(node, list):
        return [_legacy_map(v, doc, f"{where}[{i}]") for i, v in enumerate(node)]
    return node


def _paths(node, out):
    if isinstance(node, str) and node.startswith("$"):
        out.add(node)
    elif isinstance(node, Mapping):
        if "path" in node and isinstance(node["path"], str) and node["path"].startswith("$"):
            out.add(node["path"])
        for v in node.values():
            _paths(v, out)
    elif isinstance(node, list):
        for v in node:
            _paths(v, out)


def _doc_for(paths):
    doc: dict = {"payload": {}, "record_id": "r-1", "source": "legacy", "meta": {"k": "m"}, "observed_at": "2026-11-14T10:00:00+00:00"}
    for p in sorted(paths):
        parts = p[2:].split(".")
        cur: Any = doc
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            nxt = parts[i + 1] if not last else None
            make = [] if (nxt is not None and nxt.isdigit()) else {}
            if isinstance(cur, list):
                idx = int(part)
                while len(cur) <= idx:
                    cur.append(None)
                if last:
                    cur[idx] = f"v:{p}"
                elif cur[idx] is None:
                    cur[idx] = make
                cur = cur[idx]
            else:
                if last:
                    cur.setdefault(part, f"v:{p}")
                else:
                    cur = cur.setdefault(part, make)
    return doc


RECIPES = pathlib.Path(__file__).resolve().parent.parent / "proxy" / "recipes"


@pytest.mark.parametrize("recipe", sorted(p.name for p in RECIPES.iterdir() if (p / "proxy.yaml").exists()))
def test_every_recipes_mappings_map_byte_identically(recipe):
    spec = yaml.safe_load((RECIPES / recipe / "proxy.yaml").read_text())
    assert spec.get("mappings")
    for m in spec["mappings"]:
        fields = m["fields"]
        paths: set = set()
        _paths(fields, paths)
        doc = _doc_for(paths)
        want = _legacy_map(dict(fields), doc, "")
        got = M._map(dict(fields), doc, "")
        assert got == want, f"{recipe}/{m['name']}"


# ── as ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("v, want", [(12, "12"), ("x", "x"), (True, "true"), (False, "false"), (1.5, "1.5"), (None, None)])
def test_as_text(v, want):
    assert _one(_n(**{"as": "text"}), {"v": v}) == want


@pytest.mark.parametrize("v, want", [("12", 12), (" 12 ", 12), (12, 12), (12.0, 12), ("-3", -3), ("+4", 4), (None, None)])
def test_as_int_is_strict(v, want):
    assert _one(_n(**{"as": "int"}), {"v": v}) == want


@pytest.mark.parametrize("v", ["12.5", 12.5, "1e3", "abc", "", True, [1]])
def test_as_int_refuses_what_is_not_a_whole_number(v):
    assert "f: not a whole number" in _refusal(_n(**{"as": "int"}), {"v": v})


@pytest.mark.parametrize("v, want", [("12.50", "12.50"), (12.5, "12.5"), (3, "3"), (" 7 ", "7"), ("-0.10", "-0.10")])
def test_as_decimal_keeps_the_exact_text(v, want):
    assert _one(_n(**{"as": "decimal"}), {"v": v}) == want


@pytest.mark.parametrize("v", ["abc", "NaN", "Infinity", "-inf", "1,5", "", True])
def test_as_decimal_refuses_what_is_not_a_finite_number(v):
    assert "f: not a number" in _refusal(_n(**{"as": "decimal"}), {"v": v})


def test_as_float():
    assert _one(_n(**{"as": "float"}), {"v": "1.5"}) == 1.5 and _one(_n(**{"as": "float"}), {"v": 2}) == 2.0
    for v in ("x", "inf", "nan", "1,5", True):
        assert "f: not a number" in _refusal(_n(**{"as": "float"}), {"v": v})


@pytest.mark.parametrize("v, want", [("true", True), ("FALSE", False), ("Yes", True), ("no", False), ("1", True), ("0", False),
                                      (1, True), (0, False), (True, True), (False, False)])
def test_as_bool(v, want):
    assert _one(_n(**{"as": "bool"}), {"v": v}) is want


@pytest.mark.parametrize("v", ["maybe", "2", 2, "", "ja"])
def test_as_bool_refuses_the_rest(v):
    assert "f: not a boolean" in _refusal(_n(**{"as": "bool"}), {"v": v})


def test_as_date_with_a_format_and_iso():
    assert _one(_n(**{"as": "date", "format": "%d.%m.%Y"}), {"v": "14.11.2026"}) == "2026-11-14"
    assert _one(_n(**{"as": "date"}), {"v": "2026-11-14"}) == "2026-11-14"
    assert _one(_n(**{"as": "date"}), {"v": "2026-11-14T23:30:00Z"}) == "2026-11-14"
    assert "f: not a date in the format %d.%m.%Y" in _refusal(_n(**{"as": "date", "format": "%d.%m.%Y"}), {"v": SECRET})
    assert "f: not an ISO 8601 date" in _refusal(_n(**{"as": "date"}), {"v": SECRET})


def test_as_datetime_in_utc_with_z():
    node = _n(**{"as": "datetime", "format": "%d.%m.%Y %H:%M", "tz": "Europe/Berlin"})
    assert _one(node, {"v": "14.11.2026 10:30"}) == "2026-11-14T09:30:00Z"
    assert _one(node, {"v": "14.07.2026 10:30"}) == "2026-07-14T08:30:00Z"           # summer time: the zone's own rule
    assert _one(_n(**{"as": "datetime"}), {"v": "2026-11-14T10:30:00+01:00"}) == "2026-11-14T09:30:00Z"
    assert _one(_n(**{"as": "datetime"}), {"v": "2026-11-14T10:30:00Z"}) == "2026-11-14T10:30:00Z"
    assert _one(_n(**{"as": "datetime", "tz": "Asia/Tokyo"}), {"v": "2026-11-14T10:30:00"}) == "2026-11-14T01:30:00Z"
    assert _one(_n(**{"as": "datetime", "format": "%Y-%m-%d %H:%M:%S%z"}), {"v": "2026-11-14 10:30:00+0100"}) == "2026-11-14T09:30:00Z"
    assert _one(_n(**{"as": "datetime"}), {"v": "2026-11-14T10:30:00.250000Z"}) == "2026-11-14T10:30:00.250000Z"


def test_a_naive_datetime_without_a_tz_and_a_bad_one_are_refused_by_rule():
    assert "f: a datetime with no zone needs tz" in _refusal(_n(**{"as": "datetime"}), {"v": "2026-11-14T10:30:00"})
    assert "f: not a datetime in the format %d.%m.%Y" in _refusal(
        _n(**{"as": "datetime", "format": "%d.%m.%Y", "tz": "UTC"}), {"v": SECRET})
    assert "f: not an ISO 8601 datetime" in _refusal(_n(**{"as": "datetime"}), {"v": SECRET})


def test_as_json_parses_a_json_string_and_passes_a_structure():
    assert _one(_n(**{"as": "json"}), {"v": '{"a": [1, 2]}'}) == {"a": [1, 2]}
    assert _one(_n(**{"as": "json"}), {"v": {"a": 1}}) == {"a": 1}
    assert "f: not JSON" in _refusal(_n(**{"as": "json"}), {"v": "{" + SECRET})


# ── the operations ────────────────────────────────────────────────────────────────────────────────────────────

def test_trim_and_case():
    assert _one(_n(trim=True), {"v": "  Ada \n"}) == "Ada"
    assert _one(_n(case="upper"), {"v": "ada"}) == "ADA"
    assert _one(_n(case="lower"), {"v": "ADA"}) == "ada"
    assert _one(_n(case="title"), {"v": "ada lovelace"}) == "Ada Lovelace"
    assert _one(_n(trim=True), {"v": 5}) == 5                                   # trim leaves a non-text value alone
    assert "f: case needs text" in _refusal(_n(case="upper"), {"v": 5})


def test_null_if_takes_a_value_or_a_list_and_a_bool_is_not_a_number():
    assert _one(_n(null_if="N/A"), {"v": "N/A"}) is None
    assert _one(_n(null_if=["", "N/A", "-"]), {"v": "-"}) is None
    assert _one(_n(null_if=["", "N/A"]), {"v": "x"}) == "x"
    assert _one(_n(null_if=0), {"v": 0}) is None
    assert _one(_n(null_if=0), {"v": False}) is False                           # False is not the number 0 here
    assert _one(_n(null_if="N/A", **{"as": "int"}), {"v": "N/A"}) is None       # a null stays null through the rest


def test_regex_with_a_group_a_named_group_a_default_and_a_refusal():
    assert _one(_n(regex=r"(\d+)-(\w+)", group=2), {"v": "123-abc"}) == "abc"
    assert _one(_n(regex=r"(\d+)-(\w+)"), {"v": "123-abc"}) == "123"            # the first group by default
    assert _one(_n(regex=r"\d+"), {"v": "id 42x"}) == "42"                      # no group: the whole match
    assert _one(_n(regex=r"(?P<code>[A-Z]+)-\d+", group="code"), {"v": "AB-12"}) == "AB"
    assert _one(_n(regex=r"(\d+)", default="none"), {"v": "abc"}) == "none"
    assert "f: does not match the pattern" in _refusal(_n(regex=r"(\d+)"), {"v": SECRET})


def test_map_with_a_default_and_a_refusal():
    node = _n(map={"A": "active", "B": "blocked", "1": "one"})
    assert _one(node, {"v": "A"}) == "active" and _one(node, {"v": 1}) == "one"
    assert _one(_n(map={"A": "active"}, map_default="unknown"), {"v": "Z"}) == "unknown"
    assert "f: no map entry and no map_default" in _refusal(_n(map={"A": "active"}), {"v": SECRET})


def test_the_order_is_path_null_if_trim_case_regex_map_as_round():
    node = {"path": P, "null_if": " ", "trim": True, "case": "upper", "regex": r"([A-Z]+)-\d+", "map": {"AB": "alpha"}}
    assert _one(node, {"v": " ab-12 "}) == "alpha"        # trim, then case, then regex, then map
    assert _one(node, {"v": " "}) is None                 # null_if saw the raw value, before the trim
    num = {"path": P, "regex": r"(\d+[.,]\d+)", "as": "decimal", "round": 1}
    assert _one(num, {"v": "price 2.35 EUR"}) == "2.4"    # regex first, then the decimal, then the rounding


def test_round_is_half_even_on_a_decimal_never_a_float():
    assert _one(_n(**{"as": "decimal", "round": 1}), {"v": "2.25"}) == "2.2"
    assert _one(_n(**{"as": "decimal", "round": 1}), {"v": "2.35"}) == "2.4"
    assert _one(_n(**{"as": "decimal", "round": 2}), {"v": "0.125"}) == "0.12"
    assert _one(_n(**{"as": "decimal", "round": 0}), {"v": "2.5"}) == "2"
    assert _one(_n(**{"as": "float", "round": 1}), {"v": "2.25"}) == 2.2
    assert _one(_n(**{"as": "int", "round": 0}), {"v": "7"}) == 7
    assert _one(_n(round=1), {"v": 2.25}) == 2.2                                # untyped: by the value's own type
    assert "f: round needs a number" in _refusal(_n(round=1), {"v": "2.25"})     # a text is not a number until `as` says so
    assert "f: round needs a number" in _refusal(_n(round=1), {"v": "abc"})


def test_required_false_and_default():
    assert _one(_n(required=False), {}) is None
    assert _one(_n(required=False), {"v": "x"}) == "x"
    assert _one(_n(required=False, default="d"), {}) == "d"
    assert _one(_n(default="d"), {}) == "d"
    assert "the record has no $.payload.v (the mapping's field f)" in _refusal(_n(), {})
    assert _one(_n(**{"as": "int"}, default=0), {}) == 0                        # a default is a result, not a value to convert


def test_concat_joins_nodes_and_constants_with_sep():
    node = {"concat": ["$.payload.first", " ", "$.payload.last"]}
    assert _one(node, {"first": "Ada", "last": "Lovelace"}) == "Ada Lovelace"
    assert _one({"concat": ["$.payload.a", "$.payload.b"], "sep": "-"}, {"a": 1, "b": 2}) == "1-2"
    assert _one({"concat": [{"path": "$.payload.a", "trim": True}, "$.payload.b"], "sep": "|", "case": "upper"},
                {"a": " x ", "b": "y"}) == "X|Y"                                # the node's own steps, then the concat's
    assert _one({"concat": ["$.payload.a", {"path": "$.payload.b", "required": False}], "sep": "-"}, {"a": 1}) == "1-"
    assert "f: a part of concat is null" in _refusal({"concat": ["$.payload.a", "$.payload.b"]}, {"a": 1, "b": None})
    assert "the record has no $.payload.b" in _refusal({"concat": ["$.payload.a", "$.payload.b"]}, {"a": 1})


def test_nested_objects_and_lists_still_map_inside():
    out = M.apply({"o": {"name": _n(case="upper"), "n": {"path": "$.payload.n", "as": "int"}},
                   "l": [{"path": "$.payload.n", "as": "text"}, "const"]}, _rec({"v": "ada", "n": "7"}))
    assert out == {"o": {"name": "ADA", "n": 7}, "l": ["7", "const"]}


def test_a_nested_fields_refusal_names_its_dotted_path():
    with pytest.raises(Refused) as e:
        M.apply({"o": {"n": {"path": "$.payload.n", "as": "int"}}}, _rec({"n": "x"}))
    assert e.value.detail.startswith("o.n: not a whole number")


@pytest.mark.parametrize("node", [
    _n(**{"as": "int"}), _n(**{"as": "decimal"}), _n(**{"as": "float"}), _n(**{"as": "bool"}), _n(**{"as": "date"}),
    _n(**{"as": "date", "format": "%d.%m.%Y"}), _n(**{"as": "datetime"}), _n(**{"as": "datetime", "format": "%Y", "tz": "UTC"}),
    _n(**{"as": "json"}), _n(regex=r"(\d+)"), _n(map={"A": "b"}), _n(round=2),
    {"concat": ["$.payload.v", "$.payload.w"]},
])
def test_no_refusal_ever_contains_the_value(node):
    bad = {"v": SECRET, "w": None}
    try:
        _one(node, bad)
    except Refused as e:
        assert SECRET not in e.detail and SECRET not in repr(e.answer)
    else:
        pytest.fail("the sentinel value was accepted")


# ── checked at spec load ──────────────────────────────────────────────────────────────────────────────────────

def _problems(fields):
    return M.check_fields(fields, "")


@pytest.mark.parametrize("node, word", [
    ({"path": P, "as": "money"}, "as"),
    ({"path": P, "regex": "(unclosed"}, "regex"),
    ({"path": P, "as": "datetime", "tz": "Mars/Olympus"}, "tz"),
    ({"path": P, "as": "text", "round": 2}, "round"),
    ({"path": P, "as": "date", "round": 2}, "round"),
    ({"path": P, "group": 1}, "group"),
    ({"path": P, "regex": r"(\d)", "group": 5}, "group"),
    ({"path": P, "map_default": "x"}, "map_default"),
    ({"path": P, "map": ["a"]}, "map"),
    ({"path": P, "as": "int", "format": "%Y"}, "format"),
    ({"path": P, "tz": "UTC"}, "tz"),
    ({"path": P, "case": "snake"}, "case"),
    ({"path": P, "round": "two"}, "round"),
    ({"path": P, "required": "no"}, "required"),
    ({"path": P, "trim": "yes"}, "trim"),
    ({"path": P, "sep": "-"}, "sep"),
    ({"path": P, "concat": ["$.payload.a"]}, "concat"),
    ({"concat": []}, "concat"),
    ({"concat": ["$.payload.a", {"path": P, "as": "money"}]}, "as"),
])
def test_a_bad_value_node_is_a_problem_naming_the_field_and_the_rule(node, word):
    problems = _problems({"created": node})
    assert problems and all(p.startswith("created") for p in problems) and any(word in p for p in problems), problems


def test_good_nodes_have_no_problem_and_plain_fields_are_not_looked_at():
    good = {"a": _n(**{"as": "datetime", "format": "%d.%m.%Y", "tz": "Europe/Berlin"}), "b": _n(regex=r"(\d+)", group=1),
            "c": {"concat": ["$.payload.a", {"path": "$.payload.b", "required": False}], "sep": "-"},
            "d": "$.payload.d", "e": {"path": "payload.x", "as": "bogus"}, "f": {"x": {"as": "bogus"}}}
    assert M.check_fields(good, "") == []


def test_the_spec_loader_refuses_a_bad_value_node_naming_the_mapping_and_the_field(tmp_path):
    import proxy_fake as F
    from theprotocol.proxy import plugins
    from theprotocol.proxy.spec import SpecError, parse
    plugins.BUILTINS["source"]["list_source"] = "proxy_fake:ListSource"
    try:
        doc = F.spec_doc(tmp_path, mappings=[{"name": "readings", "version": 1, "from": "feed", "to": "attest",
                                              "fields": {"value": "$.payload.v", "at": {"path": "$.payload.t", "as": "datetime", "tz": "Mars/Olympus"}}}])
        with pytest.raises(SpecError) as e:
            parse(doc, base=tmp_path)
        text = "\n".join(e.value.problems)
        assert "readings" in text and "at" in text and "tz" in text
        doc["mappings"][0]["fields"]["at"] = {"path": "$.payload.t", "as": "datetime", "tz": "Europe/Berlin"}
        assert parse(doc, base=tmp_path) is not None
    finally:
        plugins.BUILTINS["source"].pop("list_source", None)
