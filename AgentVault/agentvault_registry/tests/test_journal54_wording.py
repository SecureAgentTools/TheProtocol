"""Journal 54, "The Last Puzzle Piece" (session-lead, 2026-11-09; the Commander's seq 2868: the post goes into V0660):
the post on the proxy and accountable quantum compute keeps the platform's public vocabulary and its promises about itself.

Held in the suite every image runs, like journals 50 to 52: a later edit cannot bring back a word this network does not
use on a public page ("token" and "cryptography" included), a dash, a figure that is not shipped or not described, or
lose the two sentences the post is careful about (off by default, simulators only).
A draft may be hidden; the sandbox preview's banner never ships.
"""
import pathlib
import re

FE = pathlib.Path(__file__).resolve().parents[1] / "src/agentvault_registry/static/new_registry_frontend"
VIEW = FE / "src/views/BlogView.vue"
SLUG = "the-last-puzzle-piece"
BANNED = re.compile(r"\b(earn\w*|rewards?|yields?|returns|dividends?|shares|invest\w*|profit share|banks?|banking|stocks?|IPO|"
                    r"revenue|staking|stake[sd]?|utility token|crypto\w*|on-chain|central bank|tokens?)\b", re.I)


def _post():
    s = VIEW.read_text()
    a = s.index(f"    slug: '{SLUG}',")
    j = s.index("content: `", a) + len("content: `")
    k = j
    while True:   # the content's closing backtick: the first one that is not escaped
        k = s.index("`", k)
        if s[k - 1] != "\\":
            break
        k += 1
    return s[a:k], s[j:k]


def _text(html):
    return re.sub(r"/static/blog/\S+", " ", re.sub(r"<[^>]+>", " ", html))


def test_journal_54_keeps_the_public_vocabulary():
    entry, _content = _post()
    hits = sorted({m.group(0) for m in BANNED.finditer(_text(entry))})   # title, excerpt, tags and body
    assert hits == [], f"words this network does not use on a public page: {hits}"
    assert "—" not in entry and "–" not in entry, "an em or en dash"


def test_every_figure_it_shows_is_shipped_and_described():
    _entry, content = _post()
    figs = re.findall(r'<img src="/static/blog/(p54-[a-z0-9-]+\.jpg)" alt="([^"]*)"', content)
    assert len(set(n for n, _ in figs)) == 14, f"the post shows fourteen figures; found {sorted(set(n for n, _ in figs))}"
    assert content.count("<img ") == len(figs), "every picture in the post is a shipped p54 figure with its description"
    for name, alt in figs:
        assert (FE / "public/blog" / name).is_file(), f"figure not shipped: {name}"
        assert len(alt) > 40 and "{" not in alt, f"no real description for {name}"
        assert not BANNED.search(alt), f"a description uses a word this network does not use on a public page: {name}"


def test_it_keeps_the_two_sentences_it_is_careful_about():
    _entry, content = _post()
    text = _text(content)
    assert "switched off by default" in text and "QUANTUM_WORKLOADS_MODE" in text
    assert "simulators only" in text.lower() or "Simulators and test credits only" in text


def test_it_claims_no_quantum_advantage():
    _entry, content = _post()
    text = _text(content).lower()
    assert "no claims about quantum advantage" in text
    for phrase in ("quantum advantage is", "faster than any classical", "beats classical"):
        assert phrase not in text, f"an advantage claim: {phrase}"


def test_the_sandbox_preview_banner_never_ships():
    # the sandbox preview adds a DRAFT banner on a preview build only; the post never carries it
    entry, _content = _post()
    assert "bl-draft-banner" not in entry and "DRAFT: " not in entry
