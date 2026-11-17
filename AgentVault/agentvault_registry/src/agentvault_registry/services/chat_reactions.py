"""V0662 (OurChat lane): reactions to a message. The pure rules; the writes are services/chat_service.py::add_reaction /
remove_reaction.

A reaction is one word from a CLOSED list, not an emoji: it reads the same on every device, translates, and carries no
money, no meaning the room did not agree on. A person (or an agent) puts each word on a message once and takes it off
again. A reaction wakes no session: no notice, no push, no sync wake (it is a tick on a message, not a message), and it
leaves no read receipt: the room sees how many chose a word, and each person sees which words are their own.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

#: the words, in the order they are drawn: got it, agree, thanks, done, a question, looking
VOCAB: Tuple[str, ...] = ("ack", "agree", "thanks", "done", "question", "look")


def valid(key: object) -> bool:
    return isinstance(key, str) and key in VOCAB


def summarize(rows: Iterable[Tuple[str, str]], my_keys: Set[str]) -> List[Dict[str, object]]:
    """[(word, reactor_key)] -> [{key, count, mine}] in VOCAB order, only the words someone chose."""
    counts: Dict[str, int] = {}
    mine: Set[str] = set()
    for word, who in rows:
        if word not in VOCAB:
            continue
        counts[word] = counts.get(word, 0) + 1
        if who in my_keys:
            mine.add(word)
    return [{"key": w, "count": counts[w], "mine": w in mine} for w in VOCAB if w in counts]


def refusal(kind: str, *, deleted: bool) -> Optional[str]:
    """Why a message takes no reaction, or None."""
    if deleted:
        return "this message was taken back"
    if kind == "system":
        return "a system line takes no reaction"
    return None
