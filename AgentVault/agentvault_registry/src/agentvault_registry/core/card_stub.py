"""The placeholder a card wears before its agent has ever described itself.

§CHATCOHERE D5 (2026-09-01). `_build_stub_card_data` mints a card the moment an
agent is onboarded, pointing at the host it claims; the pull-sync worker later
overwrites the agent-owned fields from the agent's own
`/.well-known/agent-card.json`. Until that first successful pull, the card's
description is this sentence — i.e. **the registry saying "this agent has not yet
told us what it does."**

That is a real, objective quality signal and it now has a name, because a second
reader needs it: the OurChat day-one cast refuses to offer an agent that has never
described itself. A cold start on frame-c was shown seven such cards as its first
nine suggestions, all named `*-probe-invalid-*` — a first-time human's first
impression was a wall of the registry's own unfilled stubs.

⚠ It is a NAMED CONSTANT rather than a literal in two files on purpose. The day the
wording changes, a filter matching a copied string would silently stop filtering and
nothing would fail — the quietest kind of regression.
"""

STUB_CARD_DESCRIPTION = "Awaiting first pull-sync from agent's /.well-known/agent-card.json"
