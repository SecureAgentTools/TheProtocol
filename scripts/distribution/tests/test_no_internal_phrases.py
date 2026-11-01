"""kit beta.30 (agentvault2-7c, 2026-10-31; the dev machine's beta.29 run, finding 5): frame-up printed "credential discarded,
by his standing word" to a stranger. No string the kit's scripts can print names the maintainer's word or decision; docstrings
(code documentation) are not output and are not read here."""
import glob
import io
import os
import re
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PHRASE = re.compile(r"\bhis (word|standing|decision|call|answer|eye|approval|order)\b|\bthe Commander\b", re.I)


def output_strings(path):
    toks = tokenize.generate_tokens(io.StringIO(open(path, errors="replace").read()).readline)
    for t in toks:
        if t.type == tokenize.STRING and not t.string.lstrip("rbfuRBFU").startswith(('"""', "'''")):
            yield t.start[0], t.string


def test_no_kit_output_names_the_maintainers_word():
    files = glob.glob(os.path.join(ROOT, "scripts", "distribution", "*.py")) + glob.glob(os.path.join(ROOT, "scripts", "hetzner_demo", "*.py"))
    assert len(files) > 20   # the scan read the kit, not an empty glob
    hits = [f"{os.path.relpath(f, ROOT)}:{n}: {s[:90]}" for f in files for n, s in output_strings(f) if PHRASE.search(s)]
    assert not hits, "\n".join(hits)
