"""The public showcase call's input parsers (main.py's /api/v1/public/showcase/call), out of the route so they can be tested.

V0653 (am) item 3 (the hardening list in the sessions' room): the route is public (no sign-in, 50 calls an hour per address)
and its input had no length bound, and four of these patterns are quadratic on a long run of spaces or digits (the country
suffix, the two-letter code, the amount-and-currency search: one weather call holding 20,000 spaces took 112 s on V0652).
The parsers read the first SHOWCASE_PARSE_MAX characters (a city, a currency phrase, an address, a domain, a cron line
are all far shorter); the text part, and the fields the agent reads as free text, keep the whole input. Lifted from
main.py verbatim otherwise (V0652, a5ef48ddd).
"""
from __future__ import annotations

import re as _re
from typing import Any, Dict, List

SHOWCASE_PARSE_MAX = 256


def showcase_parts(service: str, input_data: Any, task_type: str) -> List[Dict[str, Any]]:
    """The A2A message parts for one showcase call: a data part with the parsed fields first (when there is one), then
    the input as text."""
    raw = str(input_data).strip()
    q = raw[:SHOWCASE_PARSE_MAX]      # what the parsers below read; the text part keeps the whole input
    parts = [{"text": raw}]
    data_part = {"task_type": task_type} if task_type else {}

    if service == "weather":
        # Strip country suffixes — geocoder works better with just city
        city = _re.sub(r',?\s*(germany|deutschland|usa|us|uk|france|japan|china|india|spain|italy|australia|canada|brazil|mexico|russia|turkey|netherlands|sweden|norway|switzerland|austria|poland|belgium|czech|denmark|finland|greece|hungary|ireland|portugal|romania|thailand|vietnam|indonesia|philippines|malaysia|singapore|korea|south\s*korea|new\s*zealand|south\s*africa|egypt|morocco|argentina|chile|colombia|peru|israel|uae|saudi\s*arabia)\s*$', '', q, flags=_re.IGNORECASE).strip()
        city = _re.sub(r',?\s*\w{2}$', '', city).strip() if ',' in city else city  # Strip 2-letter country codes after comma
        data_part["city"] = city or q

    elif service == "currency":
        # Parse natural language: "100 USD to EUR", "100", "USD EUR", "convert 50 euros to dollars"
        raw_up = q.upper()
        # Common currency name mapping
        _cnames = {"DOLLAR": "USD", "DOLLARS": "USD", "EURO": "EUR", "EUROS": "EUR",
                   "POUND": "GBP", "POUNDS": "GBP", "YEN": "JPY", "YUAN": "CNY",
                   "FRANC": "CHF", "FRANCS": "CHF", "RUPEE": "INR", "RUPEES": "INR",
                   "KRONA": "SEK", "KRONE": "NOK", "WON": "KRW", "REAL": "BRL", "REAIS": "BRL"}
        for name, code in _cnames.items():
            raw_up = raw_up.replace(name, code)
        # Try pattern: amount FROM to TO
        m = _re.search(r'(\d+(?:[.,]\d+)?)\s*([A-Z]{3})\s+(?:TO|IN|INTO|->|→)\s*([A-Z]{3})', raw_up)
        if not m:
            # Try: FROM to TO (no amount)
            m2 = _re.search(r'([A-Z]{3})\s+(?:TO|IN|INTO|->|→)\s*([A-Z]{3})', raw_up)
            if m2:
                data_part["currency_from"] = m2.group(1)
                data_part["currency_to"] = m2.group(2)
                data_part["amount"] = 1.0
            else:
                # Try: just amount + currency (assume USD to EUR)
                m3 = _re.search(r'(\d+(?:[.,]\d+)?)\s*([A-Z]{3})?', raw_up)
                if m3:
                    amt = float(m3.group(1).replace(',', '.'))
                    frm = m3.group(2) or "USD"
                    data_part["currency_from"] = frm
                    data_part["currency_to"] = "EUR" if frm == "USD" else "USD"
                    data_part["amount"] = amt
                else:
                    data_part["currency_from"] = "USD"
                    data_part["currency_to"] = "EUR"
                    data_part["amount"] = 1.0
        else:
            data_part["amount"] = float(m.group(1).replace(',', '.'))
            data_part["currency_from"] = m.group(2)
            data_part["currency_to"] = m.group(3)
        data_part["task_type"] = "currency_convert"
        data_part["query"] = raw

    elif service == "ip":
        # Clean IP — strip "ip:", whitespace, etc.
        ip_clean = _re.sub(r'^(?:ip[:\s]+|address[:\s]+)', '', q, flags=_re.IGNORECASE).strip()
        data_part["ip"] = ip_clean or q

    elif service == "dns":
        # Clean domain — strip protocols, paths, whitespace
        domain = _re.sub(r'^(?:https?://)', '', q, flags=_re.IGNORECASE).split('/')[0].strip().rstrip('.')
        data_part["domain"] = domain or q

    elif service == "timezone":
        # Strip country suffixes same as weather
        city = _re.sub(r',?\s*(germany|deutschland|usa|us|uk|france|japan|china|india|spain|italy|australia|canada|brazil)\s*$', '', q, flags=_re.IGNORECASE).strip()
        data_part["city"] = city or q

    elif service == "units":
        data_part["query"] = raw

    elif service == "text":
        data_part["text"] = raw

    elif service == "cron":
        # Auto-detect if it's an expression or description
        if _re.match(r'^[\d*/,\-]+(\s+[\d*/,\-]+){4}$', q.strip()):
            data_part["expression"] = q.strip()
            data_part["task_type"] = "cron_explain"
        else:
            data_part["description"] = raw

    elif service == "password":
        ptype = raw.lower().strip()
        data_part["type"] = ptype if ptype in ("password", "passphrase", "api_key", "uuid") else "password"
        data_part["length"] = 24

    elif service == "converter":
        data_part["converter"] = task_type
        data_part["content"] = raw

    if data_part:
        # Put data part FIRST so agents that iterate parts pick structured data before raw text
        parts.insert(0, {"data": data_part})
    return parts
