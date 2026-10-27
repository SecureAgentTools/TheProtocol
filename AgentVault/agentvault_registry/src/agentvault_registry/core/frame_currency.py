"""THE frame's settlement currency, asked in ONE place.

§CHATCOHERE D3 (2026-09-01). A cold start on frame-c measured one screen giving three
answers: the composer said "2.000000 BVT per answer", the agent card said "2.0 BVT", and
the refusal that followed said "Insufficient balance: 0 AVT available, 2.000000 AVT
required". Ten user-facing money messages across the routers hardcoded "AVT", so on every
frame that is not Frame A they named a currency the frame does not use.

That is §FOREIGNACT's law broken inside a money rail: a label attached to an amount must
come from the same place the amount does — and **empty unit beats wrong unit**.

⚠ This is the FALLBACK, and only ever that. Where the action carries its OWN denominated
record — a contract row with a `currency` column, a foreign agent's card price, a
cross-frame settlement — THAT record wins. The frame's currency is the right answer for a
LOCAL balance (which is what every caller of this module is talking about) and the wrong
answer for anything settled in a counterparty's unit.

⚠ Twenty-odd modules already read this env into their own `_FRAME_CCY` constant for
response models. Those are deliberately untouched — they work, and rewriting them is a
different batch's risk. What is single-sourced here is the *messages*, which are the half
that was wrong.
"""
import os


def frame_currency() -> str:
    """`FRAME_CURRENCY` env — Frame A = AVT, Frame B = JDAY, Frame C = BVT.

    Defaults to AVT, which is correct for Frame A and for any registry that has not
    declared otherwise; a blank or whitespace value degrades to AVT rather than to an
    empty unit, because an amount with no unit at all is its own defect.
    """
    return (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
