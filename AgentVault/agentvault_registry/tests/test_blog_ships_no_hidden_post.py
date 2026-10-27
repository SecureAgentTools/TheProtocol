"""The release tree carries no hidden journal post (agentvault2-69, 2026-10-25).

His word that night, typed in agentvault2-d6's session about 22:34Z: "approved. just make sure on production newest blog
draft is hidden. i dont want it to leak there." A post marked hidden: true stays off the journal's list and its page,
but the console's BlogView chunk still carries its whole text, so anyone who fetches the script can read it: hidden is
not private. So a draft lives on its own branch (journal 52 on draft/journal52-opening, shown only by the sandbox
preview, scratchpad/blog52/roll_preview_sbx.py) and the release tree holds published posts only; a post that leaves
the journal leaves the tree, and so do the pictures only it showed.

Measured on 8c145c10b before this: 7 hidden entries (journal 52 "Here It Is", the five posts hidden for their old
wording in ee562b3d, and the outbox post, hidden since August 2026 or earlier) and 60 pictures that no published post
shows; 0 since. A draft branch drops this file, as the release tree drops the draft's own test
(test_journal52_wording.py).

The same night, the pictures: every file in public/blog is served at /static/blog/<name> and ships in the public
source, so one that no file in src names is a page of the past anyone can still fetch. Measured on 078766154: 69 such
pictures (older tours, settings and canary shots; 25 MB), named only in old stack scratch lists; 0 since.
"""
import pathlib
import re

FE = pathlib.Path(__file__).resolve().parents[1] / "src/agentvault_registry/static/new_registry_frontend"
VIEW = FE / "src/views/BlogView.vue"
PICTURES = FE / "public/blog"
READERS = (".vue", ".ts", ".js", ".json", ".md", ".css", ".html")


def _without_content(s):
    # the posts' bodies are template literals; a body may quote "hidden: true" (a post about this very rule could)
    out, i = [], 0
    while True:
        a = s.find("content: `", i)
        if a < 0:
            out.append(s[i:])
            return "".join(out)
        out.append(s[i:a])
        k = a + len("content: `")
        while True:   # the closing backtick: the first one that is not escaped
            k = s.index("`", k)
            if s[k - 1] != "\\":
                break
            k += 1
        i = k + 1


def hidden_slugs(s):
    meta = _without_content(s)
    starts = [m.start() for m in re.finditer(r"^\s*slug:\s*'", meta, re.M)]
    found = []
    for n, a in enumerate(starts):
        entry = meta[a:starts[n + 1] if n + 1 < len(starts) else len(meta)]
        if re.search(r"\bhidden:\s*true\b", entry):
            found.append(re.search(r"slug:\s*'([^']+)'", entry).group(1))
    return found


def test_the_reader_finds_a_hidden_entry_and_only_that():
    # a control: a reader that saw nothing would pass the last test for the wrong reason
    entry = "  {\n    slug: '%s',\n    title: 'T',\n%s    content: `<p>%s</p>`\n  },\n"
    s = (entry % ("shown", "", "a body that quotes hidden: true is not a flag")
         + entry % ("draft", "    hidden: true,\n", "body"))
    assert hidden_slugs(s) == ["draft"]


def test_the_reader_reads_the_journal():
    s = VIEW.read_text()
    assert len(re.findall(r"^\s*slug:\s*'", _without_content(s), re.M)) > 40


def test_no_post_in_the_release_tree_is_hidden():
    hidden = hidden_slugs(VIEW.read_text())
    assert hidden == [], (f"hidden posts ship their text in the console's bundle: {hidden}; keep a draft on its own "
                          "branch, and take a post that leaves the journal out of the tree with its pictures")


def pictures_without_a_reader(names, src_text):
    return sorted(n for n in names if n not in src_text)


def _src_text():
    return "\n".join(p.read_text(errors="ignore") for p in (FE / "src").rglob("*") if p.is_file() and p.suffix in READERS)


def test_the_picture_reader_finds_a_picture_nobody_names():
    # a control: a reader that saw every name everywhere would pass the last test for the wrong reason
    assert pictures_without_a_reader(["shown.png", "forgotten.png"], 'src="/static/blog/shown.png"') == ["forgotten.png"]


def test_every_picture_in_the_blog_folder_has_a_reader():
    names = [p.name for p in PICTURES.iterdir() if p.is_file()]
    assert len(names) > 300, len(names)
    orphans = pictures_without_a_reader(names, _src_text())
    assert orphans == [], (f"{len(orphans)} picture(s) in public/blog that no file in src names, still served at "
                           f"/static/blog/<name>: {orphans[:20]}; take them out with the post that showed them")
