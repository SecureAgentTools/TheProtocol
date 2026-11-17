"""One JSON encoder for the writers (rest, file_out), so a value a transform gives never raises a TypeError.

A mapping's `as: decimal` and `round` give a `decimal.Decimal`. The standard encoder refuses it, and turning it into a float
would round it, which is the one thing a migration must not do to money. So a Decimal is written as a JSON NUMBER with its
exact digits (`12.50` stays `12.50`), by the only route the standard encoder leaves open: the encoder is given a unique
placeholder for each Decimal and the placeholder's quotes are replaced by the digits afterwards. Anything else the encoder does
not know (a date, a time, a UUID, bytes, a set) is written as text, never as an error. A Decimal that is not a number
(NaN, Infinity) has no JSON form and is written as text.
"""
from __future__ import annotations

import base64
import datetime as _dt
import decimal
import json
import uuid
from typing import Any, Dict


def _digits(d: decimal.Decimal) -> str:
    """The exact digits of a finite Decimal, in a form every JSON reader takes. Plain notation unless the exponent is so
    large that spelling it out would be a megabyte; then the scientific form, which JSON allows and which is exact too."""
    exp = d.as_tuple().exponent
    if isinstance(exp, int) and -60 <= exp <= 60:
        return format(d, "f")
    return str(d)


def _text(o: Any) -> Any:
    if isinstance(o, (_dt.datetime, _dt.date, _dt.time)):
        return o.isoformat()
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(o)).decode("ascii")
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def dumps(obj: Any, **kw: Any) -> str:
    """`json.dumps(obj, **kw)` that also takes a Decimal (exact digits, as a number) and any other value (as text)."""
    marker = f"tpdec{uuid.uuid4().hex}"
    found: Dict[str, str] = {}

    def default(o: Any) -> Any:
        if isinstance(o, decimal.Decimal):
            if not o.is_finite():
                return str(o)
            token = f"{marker}{len(found)}"
            found[token] = _digits(o)
            return token
        return _text(o)
    out = json.dumps(obj, default=default, **kw)
    for token, digits in found.items():
        out = out.replace(f'"{token}"', digits)
    return out
