"""V0653 (am), item 3 (the hardening list in the sessions' room): the public showcase call's input parsers read a bounded
prefix, so no input can hold a worker.

core/showcase_input.showcase_parts, lifted from main.py's /api/v1/public/showcase/call (public, no sign-in, no length bound
on "input"). Four of its patterns are quadratic on a long run of spaces or digits; on V0652 (a5ef48ddd) the block, lifted
verbatim, took 112 s for one "weather" call holding 20,000 spaces, and 14 s for "currency" on 20,000 digits (timed
2026-11-01; V0653: 0.02 s). The goldens are V0652's own answers for ordinary inputs (computed
from the lifted block): nothing an ordinary input gets changes.
"""
from __future__ import annotations

import time

import pytest

from agentvault_registry.core.showcase_input import SHOWCASE_PARSE_MAX, showcase_parts

GOLD = [
    ('weather', 'Berlin, Germany', '', [{'data': {'city': 'Berlin'}}, {'text': 'Berlin, Germany'}]),
    ('weather', '  Paris , FR ', '', [{'data': {'city': 'Paris'}}, {'text': 'Paris , FR'}]),
    ('weather', 'Tokyo', 'forecast', [{'data': {'task_type': 'forecast', 'city': 'Tokyo'}}, {'text': 'Tokyo'}]),
    ('currency', '100 USD to EUR', '', [{'data': {'amount': 100.0, 'currency_from': 'USD', 'currency_to': 'EUR', 'task_type': 'currency_convert', 'query': '100 USD to EUR'}}, {'text': '100 USD to EUR'}]),
    ('currency', 'GBP -> JPY', '', [{'data': {'currency_from': 'GBP', 'currency_to': 'JPY', 'amount': 1.0, 'task_type': 'currency_convert', 'query': 'GBP -> JPY'}}, {'text': 'GBP -> JPY'}]),
    ('currency', '250', '', [{'data': {'currency_from': 'USD', 'currency_to': 'EUR', 'amount': 250.0, 'task_type': 'currency_convert', 'query': '250'}}, {'text': '250'}]),
    ('currency', 'hello', '', [{'data': {'currency_from': 'USD', 'currency_to': 'EUR', 'amount': 1.0, 'task_type': 'currency_convert', 'query': 'hello'}}, {'text': 'hello'}]),
    ('currency', '12,5 chf in usd', 'x', [{'data': {'task_type': 'currency_convert', 'amount': 12.5, 'currency_from': 'CHF', 'currency_to': 'USD', 'query': '12,5 chf in usd'}}, {'text': '12,5 chf in usd'}]),
    ('ip', 'ip: 8.8.8.8', '', [{'data': {'ip': '8.8.8.8'}}, {'text': 'ip: 8.8.8.8'}]),
    ('ip', 'Address 1.1.1.1', '', [{'data': {'ip': '1.1.1.1'}}, {'text': 'Address 1.1.1.1'}]),
    ('dns', 'https://example.com/path?q=1', '', [{'data': {'domain': 'example.com'}}, {'text': 'https://example.com/path?q=1'}]),
    ('dns', 'example.org.', '', [{'data': {'domain': 'example.org'}}, {'text': 'example.org.'}]),
    ('timezone', 'Sydney, Australia', '', [{'data': {'city': 'Sydney'}}, {'text': 'Sydney, Australia'}]),
    ('cron', '*/5 * * * *', '', [{'data': {'expression': '*/5 * * * *', 'task_type': 'cron_explain'}}, {'text': '*/5 * * * *'}]),
    ('cron', 'every five minutes', '', [{'data': {'description': 'every five minutes'}}, {'text': 'every five minutes'}]),
    ('password', 'Passphrase', '', [{'data': {'type': 'passphrase', 'length': 24}}, {'text': 'Passphrase'}]),
    ('password', 'anything', '', [{'data': {'type': 'password', 'length': 24}}, {'text': 'anything'}]),
    ('units', '5 km to miles', '', [{'data': {'query': '5 km to miles'}}, {'text': '5 km to miles'}]),
    ('text', 'count these words', '', [{'data': {'text': 'count these words'}}, {'text': 'count these words'}]),
    ('converter', '{"a":1}', 'json_to_yaml', [{'data': {'task_type': 'json_to_yaml', 'converter': 'json_to_yaml', 'content': '{"a":1}'}}, {'text': '{"a":1}'}]),
    ('unknown', 'x', '', [{'text': 'x'}]),
    ('weather', '', '', [{'data': {'city': ''}}, {'text': ''}]),
    ('currency', 42, '', [{'data': {'currency_from': 'USD', 'currency_to': 'EUR', 'amount': 42.0, 'task_type': 'currency_convert', 'query': '42'}}, {'text': '42'}]),
]


@pytest.mark.parametrize("service,inp,task_type,parts", GOLD)
def test_an_ordinary_input_gets_v0652s_answer(service, inp, task_type, parts):
    assert showcase_parts(service, inp, task_type) == parts


HOSTILE = [   # the route strips the input first, so each run of spaces sits inside the text
    ("weather", "a" + " " * 200_000 + "x"), ("weather", "," + " " * 200_000 + "!"), ("timezone", "a" + " " * 200_000 + "x"),
    ("currency", "1" * 200_000), ("currency", "AAA" + " " * 200_000 + "x"), ("cron", "1 " * 100_000 + "x"),
    ("ip", "ip:" + " " * 200_000 + "1"), ("dns", "https://" + "a" * 200_000),
]


@pytest.mark.parametrize("service,inp", HOSTILE, ids=[f"{s}-{i}" for i, (s, _) in enumerate(HOSTILE)])
def test_a_long_input_is_parsed_in_bounded_time(service, inp):
    t = time.perf_counter()
    parts = showcase_parts(service, inp, "")
    assert time.perf_counter() - t < 0.5
    assert parts[-1] == {"text": inp.strip()}          # the agent still gets the whole input as text


def test_the_parsed_fields_read_only_the_bounded_prefix_and_free_text_keeps_the_rest():
    long_city = "Berlin" + "x" * 1000
    data = showcase_parts("weather", long_city, "")[0]["data"]
    assert data["city"] == long_city[:SHOWCASE_PARSE_MAX]
    long_text = "words " * 1000
    assert showcase_parts("text", long_text, "")[0]["data"]["text"] == long_text.strip()
