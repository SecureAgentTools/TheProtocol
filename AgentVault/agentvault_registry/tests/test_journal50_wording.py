"""§MCPTEST30 (V0560): journal 50, "One Registry, One Ballot", keeps the platform's public vocabulary.

The post rides in the console's BlogView.vue. Held here, in the suite every image runs, so a later edit of the post cannot
bring back a word this network does not use on a public page (agentvault2-81's landing rules and the BaFin lane's guard),
a dash, a figure that is not shipped, an empty description of a picture, or a placeholder left open.
"""
import pathlib
import re

FE = pathlib.Path(__file__).resolve().parents[1] / "src/agentvault_registry/static/new_registry_frontend"
VIEW = FE / "src/views/BlogView.vue"
SLUG = "one-registry-one-ballot"
BANNED = re.compile(r"\b(earn\w*|rewards?|yields?|returns|dividends?|shares|invest\w*|profit share|banks?|banking|stocks?|IPO|"
                    r"revenue|staking|stake[sd]?|utility token|crypto\w*|on-chain|central bank|tokens?)\b", re.I)


def _post():
    s = VIEW.read_text()
    a = s.index(f"    slug: '{SLUG}',")
    b = s.index("\n`\n  },\n", a) + len("\n`\n  },")   # the content's closing backtick (its JSON block has "  }," lines)
    entry = s[a:b]
    return entry, entry[entry.index("content: `") + len("content: `"):entry.rindex("`")]


def _text(html):
    return re.sub(r"/static/blog/\S+", " ", re.sub(r"<[^>]+>", " ", html))


def test_journal_50_keeps_the_public_vocabulary():
    entry, content = _post()
    hits = sorted({m.group(0) for m in BANNED.finditer(_text(entry))})   # title, excerpt, tags and body
    assert hits == [], f"words this network does not use on a public page: {hits}"
    assert "—" not in entry and "–" not in entry, "an em or en dash"


def test_every_figure_it_shows_is_shipped_and_described():
    _entry, content = _post()
    figs = re.findall(r'<img src="/static/blog/(p50-[a-z0-9-]+\.jpg)" alt="([^"]*)"', content)
    assert len(figs) >= 8
    for name, alt in figs:
        assert (FE / "public/blog" / name).is_file(), f"figure not shipped: {name}"
        assert len(alt) > 40 and "{" not in alt, f"no real description for {name}"


def test_no_placeholder_is_left_open_and_it_is_not_hidden():
    entry, content = _post()
    assert not re.findall(r"\{[A-Z][A-Z0-9_]+\}", content)
    assert "hidden: false" in entry
