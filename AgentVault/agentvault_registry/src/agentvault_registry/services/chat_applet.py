"""§OURSTATE-5f — mini-app cards: a DECLARATIVE schema, never markup.

The strategy puts this last on purpose (§4): *"Agent-authored arbitrary UI stays
out until the closed set has earned trust (OURSTATE-5, declarative schema only,
never markup)."* An agent that can send markup can send a login form, and the
person looking at it is one tap from a wallet.

So an applet is a **form description**, not a document:

  * A title, up to 8 fields, and exactly ONE action.
  * Field kinds are a closed set — text, number, choice, confirm. No file
    inputs (media has its own rail with its own limits), no hidden fields
    (something a person cannot see cannot be something they agreed to), no
    "html", no "url", no "script", ever.
  * The action is a DOOR, chosen from a closed list that maps onto rails this
    app already has. An applet cannot invent an endpoint, cannot name a URL,
    and **cannot fire anything**: it fills a door and a human presses it. That
    is the same fill-never-fire rule the slash composer and the voice grammar
    already live under, and it is why an applet is safe to render at all.

What an applet CANNOT express, by construction rather than by review:
free text that renders as markup, a link, an image, an amount without a
currency, or an action this registry does not already offer.
"""
from __future__ import annotations

from typing import Any, Optional

MAX_FIELDS = 8
MAX_LABEL = 80
MAX_TITLE = 120
MAX_CHOICES = 12
MAX_CHOICE_LABEL = 60

FIELD_KINDS = ("text", "number", "choice", "confirm")

# Every action is an EXISTING door. Adding one here means the door already
# exists; it never means building a rail for an applet to reach.
ACTIONS = {
    "open_pay":   "opens the send sheet, prefilled",
    "open_buy":   "opens the service purchase panel for an agent",
    "open_work":  "opens the work picker (contracts / guild)",
    "open_reply": "puts a drafted reply in the composer",
    # §OURCHAT-ORG — the AGORA order ticket. It already exists and already
    # accepts a prefilled symbol, so this is an address for a door rather than
    # a new rail: the applet fills it, the venue prices it, and a human places
    # the order under their own token.
    "open_trade": "opens the exchange order ticket for a symbol",
}

# Named refusals for what an author will actually try first. A generic
# "unknown key" is technically enough and teaches nobody anything.
BANNED_KEYS = {
    "html": "an applet is a form description, not markup",
    "markup": "an applet is a form description, not markup",
    "script": "an applet cannot carry code",
    "url": "an applet cannot carry a link — the action list is the only way out",
    "src": "an applet cannot carry a link — the action list is the only way out",
    "iframe": "an applet cannot embed anything",
    "style": "an applet does not bring its own styling",
    "hidden": "an applet has no hidden fields — what a person cannot see, "
              "they cannot have agreed to",
}


def validate_applet(data: Any) -> Optional[str]:
    """Return a refusal reason, or None. Pure, so the FE renderer and the
    server agree by construction rather than by convention."""
    if not isinstance(data, dict):
        return "an applet card needs an object"

    for k, why in BANNED_KEYS.items():
        if k in data:
            return why

    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        return "an applet needs a title"
    if len(title) > MAX_TITLE:
        return f"an applet title is at most {MAX_TITLE} characters"

    fields = data.get("fields")
    if fields is None:
        fields = []
    if not isinstance(fields, list):
        return "applet.fields must be a list"
    if len(fields) > MAX_FIELDS:
        return f"an applet has at most {MAX_FIELDS} fields"

    seen = set()
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            return f"field {i} must be an object"
        for k, why in BANNED_KEYS.items():
            if k in f:
                return why
        kind = f.get("kind")
        if kind not in FIELD_KINDS:
            return (f"field {i}: kind must be one of {', '.join(FIELD_KINDS)} "
                    f"— the vocabulary is closed")
        key = f.get("key")
        if not isinstance(key, str) or not key.strip():
            return f"field {i} needs a key"
        if key in seen:
            return f"field {i}: duplicate key {key!r}"
        seen.add(key)
        label = f.get("label")
        if not isinstance(label, str) or not label.strip():
            return f"field {i} needs a label"
        if len(label) > MAX_LABEL:
            return f"field {i}: a label is at most {MAX_LABEL} characters"
        if kind == "choice":
            choices = f.get("choices")
            if not isinstance(choices, list) or not choices:
                return f"field {i}: a choice field needs choices"
            if len(choices) > MAX_CHOICES:
                return f"field {i}: at most {MAX_CHOICES} choices"
            for c in choices:
                if not isinstance(c, str) or not c.strip():
                    return f"field {i}: choices are non-empty strings"
                if len(c) > MAX_CHOICE_LABEL:
                    return f"field {i}: a choice is at most {MAX_CHOICE_LABEL} characters"

    action = data.get("action")
    if not isinstance(action, dict):
        return "an applet needs one action"
    for k, why in BANNED_KEYS.items():
        if k in action:
            return why
    kind = action.get("kind")
    if kind not in ACTIONS:
        return (f"action.kind must be one of {', '.join(sorted(ACTIONS))} "
                f"— an applet reaches only doors this app already has")
    label = action.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > MAX_LABEL):
        return f"an action label is a string of at most {MAX_LABEL} characters"

    # A money door must carry its currency with its amount. Three currencies
    # live on this network and §FOREIGNACT was an entire session about a label
    # that disagreed with the money.
    if kind == "open_pay":
        amount = action.get("amount")
        if amount is not None and not action.get("currency"):
            return "an applet that prefills an amount must name the currency"

    return None
