"""Journal 52, "Here It Is" (agentvault2-56, 2026-10-23; his word: "do the blog draft refinements autonomously now"):
the post that goes out with the code base and the open image registry keeps the platform's public vocabulary.

Held in the suite every image runs, like journals 50 and 51: a later edit cannot bring back a word this network does not
use on a public page (the BaFin lane's guard, "token" included, which is why the post calls the gateway the TEG), a
dash, a figure that is not shipped or not described, or the sentence that there is no public image registry. A draft
may hold its figure TODOs; the day it stops being hidden, none may remain.
"""
import pathlib
import re

FE = pathlib.Path(__file__).resolve().parents[1] / "src/agentvault_registry/static/new_registry_frontend"
VIEW = FE / "src/views/BlogView.vue"
SLUG = "here-it-is"
# the production set (/gallery/) or the sandbox set (/gallery/sandbox/, his word 2026-10-25: "we could just say its testing
# data from sandbox")
GALLERY = r"https://docs\.theprotocol\.cloud/gallery/(?:sandbox/)?full/"
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


def test_journal_52_keeps_the_public_vocabulary():
    entry, _content = _post()
    hits = sorted({m.group(0) for m in BANNED.finditer(_text(entry))})   # title, excerpt, tags and body
    assert hits == [], f"words this network does not use on a public page: {hits}"
    assert "—" not in entry and "–" not in entry, "an em or en dash"


def test_every_figure_it_shows_is_shipped_and_described():
    _entry, content = _post()
    figs = re.findall(r'<img src="/static/blog/(p52-[a-z0-9-]+\.jpg)" alt="([^"]*)"', content)
    # the whole console gallery inside the post (his word 2026-10-25: "whole gallery inside post would be cool"): the
    # docs site's shots, served from docs.theprotocol.cloud/gallery/ (the stack's docs-site/public/gallery). A suite
    # here cannot reach that site; the preview's render check loads every one of them
    shots = re.findall(r'<img src="' + GALLERY + r'([a-z0-9_-]+\.(?:webp|jpg))" alt="([^"]*)"', content)
    assert len(figs) >= 20, f"the post shows 22 figures (3 + 10 in carousels of their own); found {len(figs)}"
    assert content.count("<img ") == len(figs) + len(shots), \
        "every picture in the post is a shipped p52 figure or a shot of the docs site's gallery, with its description"
    for name, alt in figs:
        assert (FE / "public/blog" / name).is_file(), f"figure not shipped: {name}"
    for name, alt in figs + shots:
        assert len(alt) > 40 and "{" not in alt, f"no real description for {name}"
        assert not BANNED.search(alt), f"a description uses a word this network does not use on a public page: {name}"


def test_it_says_the_images_pull_without_an_account():
    _entry, content = _post()
    assert "images.theprotocol.cloud/theprotocol/" in content
    assert "no public image registry" not in content.lower()


def test_the_sandbox_preview_banner_never_ships():
    # the sandbox preview (his word 2026-10-23: "put a draft thing on the top so people who mistakenly land on sandbox
    # and read it understand its not the final post") adds the banner on a preview build only; the post never carries it
    entry, _content = _post()
    assert "bl-draft-banner" not in entry and "DRAFT: " not in entry


def test_a_draft_may_hold_its_todos_a_published_post_may_not():
    entry, content = _post()
    assert "REFINEMENT NOTES" not in content, "the refinement notes were applied and leave the post"
    if "hidden: true" in entry:
        return
    assert "FIGURE TODO" not in content and not re.findall(r"\{[A-Z][A-Z0-9_]+\}", content)
