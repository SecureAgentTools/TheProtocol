#!/usr/bin/env python3
"""Frontend integrity gate (§CIWIDE 2026-08-05).

- Icon.vue duplicate map keys: a duplicate key broke `npm run build-only`
  outright (§OPGUIDE-6 — mdi:alert-octagon declared twice).
- i18n locales must all parse: a broken locale JSON kills the FE at boot.
  Key drift vs en is REPORTED, never gated (translations lag by design and
  the legacy t() wrapper falls back).
- Email templates: no em-dashes in RENDERED text (the outward-text rule).
  Jinja {# comments #} are exempt — they never render.

Every sub-check also fails on an EMPTY probe (0 icon keys / 0 locales /
0 templates means the paths moved, not that the tree is clean).
"""
import json
import pathlib
import re
import sys

FE = pathlib.Path("agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src")
TPL = pathlib.Path("agentvault_registry/src/agentvault_registry/templates/email")
fail = 0

# --- Icon.vue duplicate keys ---
icon = FE / "components/Icon.vue"
keys = re.findall(r"^\s*['\"]([a-z0-9:_.-]+)['\"]\s*:", icon.read_text(encoding="utf-8"), re.M | re.I)
dups = sorted({k for k in keys if keys.count(k) > 1})
print(f"Icon.vue: {len(keys)} keys, duplicates={len(dups)}")
if not keys or dups:
    print(f"  ! duplicates: {dups}")
    fail = 1

# --- i18n locales ---
loc = FE / "i18n/locales"
files = sorted(loc.glob("*.json"))
sets = {}
for f in files:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))

        def flat(d, p=""):
            for k, v in d.items():
                if isinstance(v, dict):
                    yield from flat(v, p + k + ".")
                else:
                    yield p + k

        sets[f.stem] = set(flat(d))
    except Exception as e:
        print(f"  ! {f.name} PARSE FAIL: {e}")
        fail = 1
print(f"i18n: {len(files)} locales, {len(sets)} parse OK")
if not files:
    fail = 1
if "en" in sets:
    for k in sorted(sets):
        if k != "en":
            miss = len(sets["en"] - sets[k])
            if miss:
                print(f"  info: {k} missing {miss} keys vs en (non-gating)")

# --- industry blueprints (strategy §10.2 / §12) ---
# (a) Literal accent colors are banned outside the sanctioned var() fallback
#     position — the page must recolor on theme flip.
# (b) The spine rule: every blueprint's primitives must be MAJORITY built
#     (LIVE / LIVE (gated) / SHADOW vs DESIGNED). It counts capability, not this
#     deployment's switches (2026-09-25). A vapour blueprint fails CI.
# Empty probes fail: 0 data files means the tree moved, not that it is clean.
BP_DATA = FE / "data/blueprints"
BP_COMP = FE / "components/blueprints"
bp_files = sorted(BP_DATA.glob("*.ts")) if BP_DATA.exists() else []
# §18 deep-architecture modules: accent-scanned, never spine carriers.
bp_arch = sorted(BP_DATA.glob("arch/*.ts")) if (BP_DATA / "arch").exists() else []
bp_src = list(bp_files) + bp_arch + (sorted(BP_COMP.glob("*.vue")) if BP_COMP.exists() else [])
lit = 0
for f in bp_src + sorted(FE.glob("views/Blueprint*.vue")):
    if not f.exists():
        continue
    txt = f.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"#00d2d2", txt):
        pre = txt[max(0, m.start() - 40):m.start()]
        if "var(--nc-primary" not in pre:
            print(f"  ! literal accent outside var() fallback: {f.name}")
            lit += 1
ratio_bad = 0
bp_count = 0
for f in bp_files:
    txt = f.read_text(encoding="utf-8", errors="replace")
    # A blueprint carrier has actual status ROWS; types/rails/hero/index do
    # not (a type annotation mentions railStatus without a quoted value).
    total = len(re.findall(r"railStatus:\s*'", txt))
    if total == 0:
        continue
    bp_count += 1
    built = total - len(re.findall(r"railStatus:\s*'DESIGNED'", txt))
    if built * 2 <= total:
        print(f"  ! spine rule: {f.name} built {built}/{total} is not a majority")
        ratio_bad += 1
print(f"blueprints: {bp_count} carriers (need >= 12), literal-accent hits={lit}, spine-rule failures={ratio_bad}")
if bp_count < 12 or lit or ratio_bad:
    fail = 1

# --- email template rendered em-dashes ---
tpls = list(TPL.rglob("*.j2"))
emd = 0
for f in tpls:
    t = re.sub(r"\{#.*?#\}", "", f.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    c = t.count("—")
    if c:
        emd += c
        print(f"  ! rendered em-dash x{c}: {f.name}")
print(f"email templates: {len(tpls)} files, rendered em-dashes={emd}")
if not tpls or emd:
    fail = 1

sys.exit(fail)
