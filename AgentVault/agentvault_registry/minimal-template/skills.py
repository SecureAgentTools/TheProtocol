# SPDX-License-Identifier: Apache-2.0
"""The agent's example skill, text-stats: plain Python, no model and no key. Replace it with your own."""
import re
from collections import Counter
from typing import Any, Dict

_WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['-])*", re.UNICODE)
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")


def text_stats(text: str, top: int = 3) -> Dict[str, Any]:
    """Words, characters, sentences and the most used words (longer than three letters) of `text`."""
    words = [w.lower() for w in _WORD.findall(text or "")]
    counted = Counter(w for w in words if len(w) > 3)
    stripped = (text or "").strip()
    sentences = len(_SENTENCE_END.findall(stripped)) or (1 if stripped else 0)
    return {
        "words": len(words),
        "characters": len(text or ""),
        "sentences": sentences,
        "most_used": [{"word": w, "count": n} for w, n in counted.most_common(top)],
    }


def summary(stats: Dict[str, Any]) -> str:
    """One line a person reads."""
    used = ", ".join(f"{m['word']} ({m['count']})" for m in stats["most_used"]) or "none"
    return (f"{stats['words']} words, {stats['characters']} characters, {stats['sentences']} sentences; "
            f"most used: {used}")
