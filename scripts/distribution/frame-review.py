#!/usr/bin/env python3
"""Review a suggested change from its evidence archive: the maintainer's half of test-verified development (§REVIEWLANE).

  ./frame-review.py contribution-<time>.tar.gz [--pristine <the release kit tarball>] [--cla-file <acceptances>]
                    [--own-after <your own after report, once per flow>] [--design-issue <id or url>]
                    [--out review.md] [--json review.json]

frame-contribute.py packs what a contributor claims: the patch, the test reports of every flow (two, or three when the
change touches the test suite), their comparison and a sign-off. This script reads that archive and answers, check by
check, whether the claim holds, then writes one page (Markdown, plus the same as JSON) the maintainer reads before
reading the diff. It never trusts the archive's own comparison: it recomputes it from the reports with frame-test.py's
own rule.

A change to the test suite (anything under api_tests/, the tree frame-test's suite hash covers) carries a THIRD report
per flow, the control: the new suite run on the unmodified release. The rules (§REVIEWLANE-2, frame-contribute's own):
the control turns no existing tool red against the baseline; the tools the suite change adds may be red there (the
change's own tests, failing before the change exists), and those are the expected reds; the after report holds no new
red against the control, and every expected red is green in it. Red then green, in one archive.

Checks (each GREEN, RED, HELD or NOT MEASURED, with the sentence that says why):
  R1  the archive's shape (one top directory, exactly the member set frame-contribute writes, no path escapes; a control
      report for every flow or for none)
  R2  the manifest (every sha256 matches; every member is listed; nothing listed is missing)
  R3  the patch header (kit version, both tree digests, the file count, one tests line per flow, a Signed-off-by line
      with a real-looking name and an address; a one-word name is HELD for a human, the DCO asks for a real name)
  R4  the evidence, per flow (the baseline ran the unmodified release the patch changes; the after report measured the
      changed tree; same flow, same suite, same report format; NO NEW RED, recomputed; the shipped comparison agrees;
      with a control: the rules above, recomputed, and an existing tool gone from the suite is HELD for a human)
  R5  the diff (no binary file, no forbidden path such as an env file or a key, the file count as the header says; the
      areas it touches are named for the human: money, contracts, identity, federation, migrations, frontend, kit, legal,
      the suite; a suite change without a control is RED, frame-contribute refuses to pack one; a change to the
      instruments themselves (frame-test, frame-contribute, frame-review, kit_provenance, the MCP tester's own router)
      is HELD; the size caps over code files: 20 files or 600 changed lines, 12 or 400 when money, contracts, identity
      or federation is touched; over the cap is HELD unless --design-issue names the issue the change is read under)
  R6  no secret shape in an added line (the export's own shapes; the local denylist when one exists); never printed
  R7  with --pristine: the header's release tree is that kit's tree, the patch applies to it (git apply --check), and
      with controls: the release plus exactly the suite hunks is the tree every control run measured
  R8  the CLA acceptance is on file (--cla-file: one "Name <address>" or acceptance sentence per line; the sign-off's
      address must appear); without it the review is HELD, never refused: the archive may be right and the record late
  R9  with --own-after: your own run of the same suite on the same tree agrees (same suite hash, same tree digest, no
      new red against the contributor's baseline, or its control; every expected red green); a differing verdict set is
      HELD, a new red RED; without it NOT MEASURED
  R10 the summary line of every tests: header line matches the reports it names (both formats: two runs, or three
      with "red then green: N")
  R11 red then green: GREEN with the count per flow; GREEN "no suite change" for a two-run archive; HELD when an
      existing tool is gone from the suite; RED when a rule is broken
  R12 coverage: money, contracts or federation touched without the federation suite in the archive is RED; for money
      or contracts every tool of the after report named supply, delta, invariant or solvency must pass (RED otherwise,
      NOT MEASURED when the report holds none)

Verdict: REFUSED on any RED (exit 2), HELD on any HELD (exit 1), else MERGEABLE (exit 0), with the NOT MEASURED items
listed as what the human still owes. The page ends with what the human reads regardless: the diff itself, the design
against the issue, the invariant where money moves, the words a user will see. REVIEWING.md is the process this
script serves; it decides nothing about where the archive came from (a pull request or a mail).
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SIGNOFF = re.compile(r"^Signed-off-by:\s*(.+?)\s*<([^<>\s@]+@[^<>\s@]+\.[^<>\s@]+)>\s*$")
FLOW_FILES = ("baseline-{f}.json", "after-{f}.json", "comparison-{f}.txt")
CONTROL_FILE = "control-{f}.json"
FED_FLOW = "flow_federation_suite_complete"
# the size caps over code files (docs excluded): (files, changed lines); the tighter pair when a risk area is touched
CAPS = {"default": (20, 600), "risk": (12, 400)}
RISK_AREAS = ("money", "contracts", "identity", "federation")
INVARIANT_TOOL = re.compile(r"(?i)supply|delta|invariant|solvency")
# the instruments: what produces or judges the evidence. A change to them cannot be verified by the evidence they
# produce, so it waits for a human. The MCP tester's own router runs the suite on the sandbox, so it is one of them.
INSTRUMENTS = re.compile(r"(^|/)(frame-test|frame-contribute|frame-review|kit_provenance)\.py$|(^|/)mcp_tester(_sandbox)?\.py$")
# the export's G3 (key FILE paths) plus the carriers a change must never touch; .env.example, .env.sample and *.tmpl are
# shipped templates and stay reviewable
FORBIDDEN = (re.compile(r"(^|/)\.env(?!\.example$|\.sample$|\.tmpl$)(\.[^/]*)?$"), re.compile(r"\.key$"),
             re.compile(r"-key\.pem$"), re.compile(r"\.(p12|pfx|jks)$"), re.compile(r"(^|/)docker-certs/"),
             re.compile(r"(^|/)(token-signing\.key|mcp-registry-key\.pem|dummy_upstream_ca\.key)$"),
             re.compile(r"(^|/)(KIT_FILES\.sha256|BUILD_INFO\.json)$"), re.compile(r"(^|/)id_(rsa|ed25519|ecdsa)"))
AREAS = [  # (name, pattern over the changed path, what it means for the reader)
    ("money", re.compile(r"(?i)teg|a2a_payment|exchange|agora|treasury|transfer|bridge|staking|reward|fx_|escrow|fee"),
     "value moves here: read the change against the supply invariant and the existing transfer rails"),
    ("contracts", re.compile(r"(?i)contract"),
     "a contract's lifecycle: escrow, milestones, cross-frame replicas; read it against the invariant and the federation suite"),
    ("migration", re.compile(r"alembic/versions/"), "a migration: the downgrade path is part of the review"),
    ("identity", re.compile(r"(?i)spire|svid|mtls|identity|auth|jwt|security\.py|permission|authz|delegation"),
     "identity or authority: read who may call what, before and after"),
    ("federation", re.compile(r"(?i)federation|peer_registr|invitation|cross_teg|xframe|cross-frame"),
     "crosses frames: the federation suite's pair is the evidence that counts"),
    ("frontend", re.compile(r"new_registry_frontend/"), "the console: words a user reads, the i18n gate, the type ratchet"),
    ("kit", re.compile(r"scripts/distribution/|templates/frame-test/|tools/frame-runner/|tools/operator-cli/"),
     "the kit or the runner: a stranger's standup runs this"),
    ("legal", re.compile(r"(?i)legal|LICENS|CLA\.md|DCO\.md|CONTRIBUTING|SECURITY\.md|CODE_OF_CONDUCT|content/compliance"),
     "legal or contribution text: the maintainer's own eyes, no merge by evidence alone"),
]
SUITE_MEANING = "the test suite: the control run is the evidence, the new tests red on the release and green on the change"
TEST_PATHS = re.compile(r"(^|/)tests?/|_test\.py$|\.test\.ts$|\.spec\.ts$")
DOC_SUFFIX = (".md", ".txt", ".rst")


def is_suite_path(rel: str) -> bool:
    """The test suite frame-test's suite hash covers (the registry's api_tests tree): frame-contribute's own rule."""
    return "/api_tests/" in "/" + rel


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Review:
    """The checks and their verdicts, in order, with everything the page needs."""

    def __init__(self):
        self.rows = []          # (id, verdict, sentence)
        self.facts = {}         # what the page prints beside the verdicts

    def add(self, cid, verdict, sentence):
        self.rows.append((cid, verdict, sentence))

    def has(self, verdict):
        return any(v == verdict for _c, v, _s in self.rows)

    def decision(self):
        if self.has("RED"):
            return "REFUSED", 2
        if self.has("HELD"):
            return "HELD", 1
        return "MERGEABLE", 0


def read_archive(path):
    """{member name (without the top dir): bytes}, the top dir; raises ValueError on a shape frame-contribute never writes."""
    with tarfile.open(path, "r:gz") as tar:
        members = [m for m in tar.getmembers()]
        tops = set()
        out = {}
        for m in members:
            if not m.isfile():
                raise ValueError(f"{m.name}: not a plain file")
            if m.name.startswith("/") or ".." in m.name.split("/"):
                raise ValueError(f"{m.name}: a path that leaves the archive")
            parts = m.name.split("/", 1)
            if len(parts) != 2 or not parts[0].startswith("contribution-"):
                raise ValueError(f"{m.name}: not under one contribution-<time>/ directory")
            tops.add(parts[0])
            data = tar.extractfile(m).read()
            out[parts[1]] = data
        if len(tops) != 1:
            raise ValueError(f"{len(tops)} top directories, frame-contribute writes one")
    return out, tops.pop()


def parse_header(patch):
    """The header lines frame-contribute writes, and the body (the unified diff) after them."""
    text = patch.decode("utf-8", errors="replace")
    lines = text.split("\n")
    head = {"tests": [], "signoff": None, "errors": []}
    body_at = None
    for i, line in enumerate(lines):
        if line.startswith("--- ") or line.startswith("Binary file "):
            body_at = i
            break
        if i == 0:
            m = re.match(r"^TheProtocol kit (\S+): a suggested change$", line)
            if m:
                head["kit_version"] = m.group(1)
            else:
                head["errors"].append("line 1 is not 'TheProtocol kit <version>: a suggested change'")
        elif line.startswith("release tree "):
            head["release_tree"] = line[len("release tree "):].strip()
        elif line.startswith("changed tree "):
            head["changed_tree"] = line[len("changed tree "):].strip()
        elif line.startswith("files changed: "):
            try:
                head["files_changed"] = int(line[len("files changed: "):].strip())
            except ValueError:
                head["errors"].append("the files changed line is not a number")
        elif line.startswith("tests: "):
            head["tests"].append(line[len("tests: "):].strip())
        elif line.startswith("Signed-off-by:"):
            m = SIGNOFF.match(line)
            if m:
                head["signoff"] = (m.group(1), m.group(2))
            else:
                head["errors"].append("the Signed-off-by line is not 'Name <address>'")
    body = "\n".join(lines[body_at:]) if body_at is not None else ""
    return head, body


def diff_files(body):
    """[(path, added, removed, binary)] from a unified diff in frame-contribute's form (a/ and b/ prefixes, /dev/null)."""
    files = []
    cur = None
    for line in body.split("\n"):
        if line.startswith("Binary file ") and line.endswith(" differs"):
            files.append([line[len("Binary file "):-len(" differs")], 0, 0, True])
            cur = None
        elif line.startswith("--- "):
            cur = [None, 0, 0, False]
            old = line[4:].split("\t")[0]
            if old != "/dev/null":
                cur[0] = old[2:] if old.startswith("a/") else old
        elif line.startswith("+++ ") and cur is not None:
            new = line[4:].split("\t")[0]
            if new != "/dev/null":
                cur[0] = new[2:] if new.startswith("b/") else new
            files.append(cur)
        elif cur is not None and line.startswith("+") and not line.startswith("+++"):
            cur[1] += 1
        elif cur is not None and line.startswith("-") and not line.startswith("---"):
            cur[2] += 1
    return files


def added_lines(body):
    """(path, the added text) for every '+' line, the diff headers excluded."""
    out = []
    path = None
    for line in body.split("\n"):
        if line.startswith("+++ "):
            new = line[4:].split("\t")[0]
            path = new[2:] if new.startswith("b/") else new
        elif line.startswith("+") and not line.startswith("+++"):
            out.append((path, line[1:]))
    return out


def check_shape(rv, files):
    flows = sorted(n[len("baseline-"):-len(".json")] for n in files if n.startswith("baseline-") and n.endswith(".json"))
    controls = sorted(n[len("control-"):-len(".json")] for n in files if n.startswith("control-") and n.endswith(".json"))
    three = bool(controls)
    expected = {"contribution.patch", "MANIFEST.txt"}
    for f in flows:
        expected |= {t.format(f=f) for t in FLOW_FILES}
        if three:
            expected.add(CONTROL_FILE.format(f=f))
    rv.facts["flows"] = flows
    rv.facts["three_run"] = three
    if not flows:
        rv.add("R1", "RED", "no flow: the archive carries no baseline report, so there is no evidence to review")
    elif three and set(controls) != set(flows):
        rv.add("R1", "RED", f"a control report for some flows and not others ({', '.join(controls)} of {', '.join(flows)}): "
                            f"frame-contribute writes one for every flow or for none")
    elif set(files) != expected:
        extra, missing = sorted(set(files) - expected), sorted(expected - set(files))
        rv.add("R1", "RED", f"the member set is not frame-contribute's: extra {extra}, missing {missing}")
    else:
        rv.add("R1", "GREEN", f"one contribution directory, {len(files)} members, {len(flows)} flow(s): {', '.join(flows)}"
                              + (", each with its control run" if three else ""))
    return flows


def check_manifest(rv, files):
    listed = {}
    for line in files.get("MANIFEST.txt", b"").decode("utf-8", errors="replace").splitlines():
        if len(line) > 66 and line[64:66] == "  ":
            listed[line[66:]] = line[:64]
    bad = []
    for name, data in files.items():
        if name == "MANIFEST.txt":
            continue
        if name not in listed:
            bad.append(f"{name} not in the manifest")
        elif hashlib.sha256(data).hexdigest() != listed[name]:
            bad.append(f"{name} differs from its manifest digest")
    for name in listed:
        if name not in files:
            bad.append(f"{name} listed but absent")
    if bad:
        rv.add("R2", "RED", "; ".join(bad))
    else:
        rv.add("R2", "GREEN", f"{len(listed)} members match their sha256")


def check_header(rv, head, flows):
    errors = list(head["errors"])
    for key in ("kit_version", "release_tree", "changed_tree", "files_changed"):
        if key not in head:
            errors.append(f"no {key.replace('_', ' ')} line")
    for key in ("release_tree", "changed_tree"):
        if key in head and not HEX64.match(head[key]):
            errors.append(f"the {key.replace('_', ' ')} is not a sha256")
    if head.get("release_tree") and head.get("release_tree") == head.get("changed_tree"):
        errors.append("release tree and changed tree are the same digest: nothing changed")
    named = [t.split(" ", 1)[0] for t in head["tests"]]
    if sorted(named) != sorted(flows):
        errors.append(f"the tests lines name {named} and the archive holds {flows}")
    if head["signoff"] is None:
        errors.append("no Signed-off-by line (DCO.md: every contribution is signed off)")
    if errors:
        rv.add("R3", "RED", "; ".join(errors))
        return
    name, mail = head["signoff"]
    rv.facts["signoff"] = {"name": name, "email": mail}
    rv.facts["kit_version"] = head["kit_version"]
    rv.facts["release_tree"] = head["release_tree"]
    rv.facts["changed_tree"] = head["changed_tree"]
    words = [w for w in re.split(r"\s+", name) if w]
    if len(words) < 2 or not all(re.search(r"[A-Za-zÀ-ɏ]", w) for w in words):
        rv.add("R3", "HELD", f"the sign-off name '{name}' does not look like a real name (DCO.md asks for one): a human decides")
    else:
        rv.add("R3", "GREEN", f"kit {head['kit_version']}, release {head['release_tree'][:12]} -> changed {head['changed_tree'][:12]}, "
                              f"{head['files_changed']} file(s), signed off by {name} <{mail}>")


def red_then_green(ft, base, control, after):
    """frame-contribute's rules for a three-run flow, recomputed: what the control and the after report say."""
    c1 = ft.compare(control, base)
    expected = sorted(t for t in c1["added"] if control["verdicts"].get(t) == "fail")
    cmp = ft.compare(after, control)
    return cmp, {"control_new_reds": c1["new_reds"], "control_added": c1["added"], "control_gone": c1["gone"],
                 "expected_reds": expected, "turned_green": sorted(t for t in expected if after["verdicts"].get(t) == "pass"),
                 "not_green": sorted(t for t in expected if after["verdicts"].get(t) != "pass"),
                 "after_new_reds": cmp["new_reds"]}


def check_evidence(rv, files, head, flows, ft):
    problems, notes, held = [], [], []
    reports, rtg = {}, {}
    if not flows:
        rv.add("R4", "RED", "no flow to check: there is no evidence in the archive")
        return reports
    three = rv.facts.get("three_run")
    for f in flows:
        try:
            base = json.loads(files[f"baseline-{f}.json"].decode("utf-8"))
            after = json.loads(files[f"after-{f}.json"].decode("utf-8"))
            control = json.loads(files[CONTROL_FILE.format(f=f)].decode("utf-8")) if three else None
        except (ValueError, KeyError) as e:
            problems.append(f"{f}: a report is not JSON or is missing ({e.__class__.__name__})")
            continue
        reports[f] = {"base": base, "after": after, "control": control}
        bb, ab = base.get("build") or {}, after.get("build") or {}
        if bb.get("modified") is not False:
            problems.append(f"{f}: the baseline did not run the unmodified release (modified is not false)")
        if bb.get("tree_digest") != head.get("release_tree"):
            problems.append(f"{f}: the baseline ran tree {str(bb.get('tree_digest'))[:12]}, the patch changes {str(head.get('release_tree'))[:12]}")
        if ab.get("tree_digest") != head.get("changed_tree"):
            problems.append(f"{f}: the after report measured tree {str(ab.get('tree_digest'))[:12]}, the patch produces {str(head.get('changed_tree'))[:12]}")
        if ab.get("modified") is not True:
            problems.append(f"{f}: the after report does not say the tree differs from the release")
        if base.get("flow") != f or after.get("flow") != f or (control is not None and control.get("flow") != f):
            problems.append(f"{f}: a report names another flow ({base.get('flow')} / {after.get('flow')}"
                            + (f" / {control.get('flow')}" if control is not None else "") + ")")
        sh = after.get("suite_hash")
        if not sh or len(str(sh)) != 64:  # frame-test's own rule: a 64-char hash
            problems.append(f"{f}: the after report carries no suite hash")
        elif control is None and base.get("suite_hash") != sh:
            problems.append(f"{f}: the two reports did not run the same suite (suite hash)")
        elif control is not None and control.get("suite_hash") != sh:
            problems.append(f"{f}: the control and the after report did not run the same suite (suite hash)")
        if base.get("report_format") != after.get("report_format") or (
                control is not None and control.get("report_format") != after.get("report_format")):
            problems.append(f"{f}: the reports were written in different formats")
        if control is not None and (control.get("build") or {}).get("modified") is not True:
            problems.append(f"{f}: the control does not say its tree differs from the release")
        if not all(isinstance(r.get("verdicts"), dict) for r in (base, after) + ((control,) if control is not None else ())):
            problems.append(f"{f}: a report carries no verdicts")
            continue
        shipped = files.get(f"comparison-{f}.txt", b"").decode("utf-8", errors="replace").split("\n")
        if control is None:
            cmp, stage = ft.compare(after, base), None
            if cmp["new_reds"]:
                problems.append(f"{f}: {len(cmp['new_reds'])} new red(s): {', '.join(cmp['new_reds'][:5])}")
        else:
            cmp, stage = red_then_green(ft, base, control, after)
            rtg[f] = stage
            if stage["control_new_reds"]:
                problems.append(f"{f}: the suite change turns {len(stage['control_new_reds'])} existing tool(s) red on the "
                                f"release: {', '.join(stage['control_new_reds'][:5])}")
            if cmp["new_reds"]:
                problems.append(f"{f}: {len(cmp['new_reds'])} new red(s) against the control: {', '.join(cmp['new_reds'][:5])}")
            if stage["not_green"]:
                problems.append(f"{f}: {len(stage['not_green'])} of the {len(stage['expected_reds'])} new test(s) that fail on "
                                f"the release still fail on the change: {', '.join(stage['not_green'][:5])}")
            if stage["control_gone"]:
                held.append(f"{f}: {len(stage['control_gone'])} existing tool(s) are gone from the suite "
                            f"({', '.join(stage['control_gone'][:5])}): a test that went away is a human's call")
        keys = [(k, cmp[k]) for k in ("new_reds", "new_greens", "still_red", "added", "gone")]
        if stage is not None:
            keys += [(k, stage[k]) for k in ("control_new_reds", "control_added", "control_gone", "expected_reds", "turned_green")]
        for key, value in keys:
            if f"{key} ({len(value)}): {', '.join(value)}" not in shipped:
                problems.append(f"{f}: the shipped comparison does not agree with the recomputed {key}")
                break
        if stage is None:
            notes.append(f"{f}: {len(after['verdicts'])} tools, {len(cmp['still_red'])} still red, {len(cmp['new_greens'])} new green, "
                         f"{len(cmp['added'])} added, {len(cmp['gone'])} gone, 0 new red")
        else:
            notes.append(f"{f}: {len(after['verdicts'])} tools; the control turned no existing tool red and left "
                         f"{len(stage['expected_reds'])} new test(s) red on the release; the after report holds 0 new red "
                         f"against it and {len(stage['turned_green'])} turned green")
    rv.facts["reports"] = {f: {"baseline": r["base"].get("summary_line"), "after": r["after"].get("summary_line"),
                               "control": r["control"].get("summary_line") if r["control"] is not None else None}
                           for f, r in reports.items()}
    rv.facts["red_then_green"] = rtg
    if problems:
        rv.add("R4", "RED", "; ".join(problems))
    elif held:
        rv.add("R4", "HELD", "; ".join(held + notes))
    else:
        rv.add("R4", "GREEN", "; ".join(notes))
    return reports


def check_diff(rv, head, body, design_issue=""):
    files = diff_files(body)
    paths = [f[0] for f in files if f[0]]
    errors, held, notes = [], [], []
    binaries = [f[0] for f in files if f[3]]
    if binaries:
        errors.append(f"binary file(s) cannot be reviewed as a diff: {', '.join(binaries[:5])}")
    forbidden = [p for p in paths if any(r.search(p) for r in FORBIDDEN)]
    if forbidden:
        errors.append(f"forbidden path(s): {', '.join(forbidden[:5])}")
    if head.get("files_changed") is not None and head["files_changed"] != len(files):
        errors.append(f"the header says {head['files_changed']} file(s) changed and the diff holds {len(files)}")
    added = sum(f[1] for f in files)
    removed = sum(f[2] for f in files)
    suite = [p for p in paths if is_suite_path(p)]
    code_paths = [p for p in paths if not is_suite_path(p)]
    areas = []
    for name, pat, meaning in AREAS:
        # a test under api_tests/ is not the code it tests: the four risk areas are read over the code paths only
        hit = [p for p in (code_paths if name in RISK_AREAS else paths) if pat.search(p)]
        if hit:
            areas.append({"area": name, "files": hit, "meaning": meaning})
    if suite:
        areas.append({"area": "suite", "files": suite, "meaning": SUITE_MEANING})
    only_docs = bool(paths) and all(p.endswith(DOC_SUFFIX) for p in paths)
    only_tests = bool(paths) and all(TEST_PATHS.search(p) or is_suite_path(p) for p in paths)
    instruments = [p for p in paths if INSTRUMENTS.search(p)]
    three = bool(rv.facts.get("three_run"))
    if suite and not three:
        errors.append(f"the test suite changes ({', '.join(suite[:3])}) and the archive carries no control run: "
                      f"frame-contribute refuses to pack that, so this archive was made by hand (REVIEWING.md §3b)")
    if three and not suite:
        errors.append("the archive carries control runs and the diff does not touch the test suite (api_tests/): "
                      "frame-contribute refuses that too")
    if instruments:
        held.append(f"the instruments themselves change ({', '.join(instruments[:3])}): the evidence cannot verify a change "
                    f"to the thing that produces or judges it, a human reads it as a suggestion of its own")
    code = [f for f in files if f[0] and not f[0].endswith(DOC_SUFFIX)]
    n_code, n_lines = len(code), sum(f[1] + f[2] for f in code)
    risky = [a["area"] for a in areas if a["area"] in RISK_AREAS]
    cap_files, cap_lines = CAPS["risk"] if risky else CAPS["default"]
    over = n_code > cap_files or n_lines > cap_lines
    cap_text = (f"{n_code} code file(s) and {n_lines} changed line(s) against a cap of {cap_files} files or {cap_lines} lines"
                + (f" (the cap where {', '.join(risky)} is touched)" if risky else ""))
    if over and design_issue:
        notes.append(f"over the cap, {cap_text}: read in slices under design issue {design_issue}")
    elif over:
        held.append(f"over the cap, {cap_text}: split it, or the design issue names it as a whole (REVIEWING.md)")
    rtg = rv.facts.get("red_then_green") or {}
    rv.facts["diff"] = {"files": [{"path": f[0], "added": f[1], "removed": f[2], "binary": f[3]} for f in files],
                        "added": added, "removed": removed, "areas": areas, "docs_only": only_docs, "tests_only": only_tests,
                        "suite_changed": suite, "instruments": instruments,
                        "caps": {"code_files": n_code, "changed_lines": n_lines, "cap_files": cap_files, "cap_lines": cap_lines,
                                 "risk_areas": risky, "over": over, "design_issue": design_issue or None}}
    if errors:
        rv.add("R5", "RED", "; ".join(errors))
    elif held:
        rv.add("R5", "HELD", "; ".join(held))
    else:
        kinds = ", ".join(a["area"] for a in areas) or ("docs only" if only_docs else "tests only" if only_tests else "no flagged area")
        sentence = f"{len(files)} file(s), +{added} -{removed}; areas: {kinds}"
        if suite:
            sentence += f"; red then green: {sum(len(s['turned_green']) for s in rtg.values())}"
        rv.add("R5", "GREEN", "; ".join([sentence] + notes))


def check_secrets(rv, body, denylist_path):
    try:
        ex = _load("oss_export", "oss_export.py")
        shapes = ex.SHAPES
    except Exception as e:  # a gate that cannot load is not a pass
        rv.add("R6", "RED", f"the secret shapes could not be loaded from oss_export.py ({e.__class__.__name__})")
        return
    literals = []
    if denylist_path and os.path.isfile(denylist_path):
        with open(denylist_path, "rb") as fh:
            literals = [ln.strip() for ln in fh.read().splitlines() if len(ln.strip()) >= 12 and not ln.startswith(b"#")]
    hits = []
    for path, text in added_lines(body):
        raw = text.encode("utf-8", errors="replace")
        for name, pat in shapes.items():
            if pat.search(raw):
                hits.append(f"{name} in {path}")
        for lit in literals:
            if lit in raw:
                hits.append(f"a denylisted literal in {path}")
    if hits:
        rv.add("R6", "RED", "; ".join(sorted(set(hits))[:8]))
    else:
        rv.add("R6", "GREEN", f"no secret shape in the added lines ({len(shapes)} shapes, {len(literals)} denylisted literals checked)")


def check_pristine(rv, head, body, pristine, kp, reports=None):
    three = bool(rv.facts.get("three_run"))
    if not pristine:
        rv.add("R7", "NOT MEASURED", "no --pristine kit tarball given: the release tree and the apply check are not verified"
               + ("; nor is the tree the control runs measured (the release plus exactly the suite change)" if three else ""))
        return
    tmp = tempfile.mkdtemp(prefix="frame-review-")
    try:
        with tarfile.open(pristine, "r:gz") as tar:
            names = tar.getnames()
            top = names[0].split("/", 1)[0] if names else ""
            safe = [m for m in tar.getmembers() if not (m.name.startswith("/") or ".." in m.name.split("/"))]
            tar.extractall(tmp, members=safe)
        root = os.path.join(tmp, top)
        release = kp.read_manifest(root)
        if release is None:
            rv.add("R7", "RED", f"the kit tarball carries no {kp.MANIFEST}: it is not a release kit")
            return
        digest = kp.tree_digest(release)
        if digest != head.get("release_tree"):
            rv.add("R7", "RED", f"the evidence is about release {str(head.get('release_tree'))[:12]} and this kit is {digest[:12]}")
            return
        with open(os.path.join(tmp, "contribution.patch"), "w", encoding="utf-8") as fh:
            fh.write(body if body.endswith("\n") else body + "\n")
        patch = os.path.join(tmp, "contribution.patch")
        r = subprocess.run(["git", "apply", "--check", patch], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            rv.add("R7", "RED", f"the patch does not apply to the release kit: {r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else 'git apply refused'}")
            return
        if not three:
            rv.add("R7", "GREEN", f"release tree {digest[:12]} is this kit's, and the patch applies to it cleanly")
            return
        # the control must have measured the release plus exactly the suite change: apply only the suite hunks to the
        # pristine tree, digest it the way a build does, and compare with every control report's tree
        r = subprocess.run(["git", "apply", "--include=*/api_tests/*", "--include=api_tests/*", patch], cwd=root,
                           capture_output=True, text=True)
        if r.returncode != 0:
            rv.add("R7", "RED", f"the suite hunks do not apply to the release kit: {r.stderr.strip().splitlines()[-1][:160] if r.stderr.strip() else 'git apply refused'}")
            return
        control_tree = kp.tree_digest(kp.digests(root))
        measured = {f: str((rep["control"].get("build") or {}).get("tree_digest"))
                    for f, rep in (reports or {}).items() if rep.get("control") is not None}
        wrong = sorted(f"{f} ({tree[:12]})" for f, tree in measured.items() if tree != control_tree)
        if wrong:
            rv.add("R7", "RED", f"the control run(s) of {', '.join(wrong)} did not measure the release plus exactly the suite "
                                f"hunks ({control_tree[:12]}): a control runs the new suite on the unmodified release")
        else:
            rv.add("R7", "GREEN", f"release tree {digest[:12]} is this kit's, the patch applies to it cleanly, and every control "
                                  f"run measured the release plus exactly the suite hunks ({control_tree[:12]})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_cla(rv, cla_file):
    so = rv.facts.get("signoff")
    if not so:
        rv.add("R8", "HELD", "no sign-off to look up")
        return
    if not cla_file:
        rv.add("R8", "HELD", "no acceptance record given (--cla-file): the review is held until the CLA acceptance is on file")
        return
    if not os.path.isfile(cla_file):
        rv.add("R8", "HELD", f"{cla_file} does not exist: held until the CLA acceptance is on file")
        return
    with open(cla_file, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    mail = so["email"].lower()
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        if mail in line.lower():
            rv.add("R8", "GREEN", f"the CLA acceptance for {so['email']} is on file")
            return
    rv.add("R8", "HELD", f"no CLA acceptance on file for {so['email']}: held until it is (CLA.md, How to accept)")


def check_own(rv, own_paths, reports, head, ft):
    if not own_paths:
        rv.add("R9", "NOT MEASURED", "not reproduced: no --own-after report; run the loop in REVIEWING.md §4 for money, identity, "
                                     "federation or migration changes")
        return
    problems, notes, held = [], [], []
    seen = set()
    for p in own_paths:
        try:
            own = json.load(open(p, encoding="utf-8"))
        except (OSError, ValueError) as e:
            problems.append(f"{p}: not a report ({e.__class__.__name__})")
            continue
        f = own.get("flow")
        if f not in reports:
            problems.append(f"{p}: flow {f} is not in the archive")
            continue
        if f in seen:
            problems.append(f"{p}: the flow {f} was given twice")
            continue
        seen.add(f)
        base, after, control = reports[f]["base"], reports[f]["after"], reports[f]["control"]
        ob = own.get("build") or {}
        if ob.get("tree_digest") != head.get("changed_tree"):
            problems.append(f"{f}: your run measured tree {str(ob.get('tree_digest'))[:12]}, the patch produces {str(head.get('changed_tree'))[:12]}")
            continue
        if own.get("suite_hash") != after.get("suite_hash"):
            problems.append(f"{f}: your run used another suite than the contributor's")
            continue
        if not isinstance(own.get("verdicts"), dict):
            problems.append(f"{p}: carries no verdicts")
            continue
        # a suite change is compared with its control (the same suite); every expected red must be green in your run too
        cmp = ft.compare(own, control if control is not None else base)
        if cmp["new_reds"]:
            problems.append(f"{f}: your own run holds {len(cmp['new_reds'])} new red(s) the contributor's did not: {', '.join(cmp['new_reds'][:5])}")
            continue
        if control is not None and isinstance(control.get("verdicts"), dict) and isinstance(base.get("verdicts"), dict):
            _cmp, stage = red_then_green(ft, base, control, own)
            if stage["not_green"]:
                problems.append(f"{f}: your own run leaves {len(stage['not_green'])} expected red(s) red: {', '.join(stage['not_green'][:5])}")
                continue
        if own.get("verdicts") != after.get("verdicts"):
            diff = sorted(k for k in set(own.get("verdicts", {})) | set(after.get("verdicts", {}))
                          if own.get("verdicts", {}).get(k) != after.get("verdicts", {}).get(k))
            held.append(f"{f}: no new red, but {len(diff)} verdict(s) differ from the contributor's run ({', '.join(diff[:5])})")
        else:
            notes.append(f"{f}: reproduced, verdict for verdict")
    missing = sorted(set(reports) - seen)
    if problems:
        rv.add("R9", "RED", "; ".join(problems))
    elif held:
        rv.add("R9", "HELD", "; ".join(held + notes))
    elif missing:
        rv.add("R9", "HELD", f"reproduced {', '.join(sorted(seen))}; not reproduced: {', '.join(missing)}")
    else:
        rv.add("R9", "GREEN", "; ".join(notes))


def check_tests_lines(rv, head, reports):
    bad = []
    rtg = rv.facts.get("red_then_green") or {}
    for line in head["tests"]:
        f = line.split(" ", 1)[0]
        if f not in reports:
            continue
        base, after, control = reports[f]["base"], reports[f]["after"], reports[f]["control"]
        if control is None:
            want = f"{f} {base.get('summary_line')} -> {after.get('summary_line')}, no new red"
        else:
            n = len(rtg[f]["expected_reds"]) if f in rtg else "?"
            want = (f"{f} {base.get('summary_line')} -> {control.get('summary_line')} -> {after.get('summary_line')}, "
                    f"red then green: {n}")
        if line != want:
            bad.append(f"{f}: the header's tests line does not match the reports")
    if bad:
        rv.add("R10", "RED", "; ".join(bad))
    else:
        rv.add("R10", "GREEN", "every tests line in the header matches the reports it names")


def check_red_then_green(rv):
    if not rv.facts.get("three_run"):
        rv.add("R11", "GREEN", "no suite change: two runs per flow are the evidence")
        return
    rtg = rv.facts.get("red_then_green") or {}
    if not rtg:
        rv.add("R11", "RED", "the archive carries control runs, and none could be read with its baseline and after report")
        return
    broken, gone, notes = [], [], []
    for f, s in sorted(rtg.items()):
        if s["control_new_reds"]:
            broken.append(f"{f}: the suite change turns existing tool(s) red on the release ({', '.join(s['control_new_reds'][:5])})")
        if s["after_new_reds"]:
            broken.append(f"{f}: new red(s) against the control ({', '.join(s['after_new_reds'][:5])})")
        if s["not_green"]:
            broken.append(f"{f}: new test(s) still red on the change ({', '.join(s['not_green'][:5])})")
        if s["control_gone"]:
            gone.append(f"{f}: existing tool(s) gone from the suite ({', '.join(s['control_gone'][:5])})")
        notes.append(f"{f}: red then green: {len(s['turned_green'])}")
    if broken:
        rv.add("R11", "RED", "; ".join(broken))
    elif gone:
        rv.add("R11", "HELD", "; ".join(gone) + ": a test that went away is a human's call")
    else:
        rv.add("R11", "GREEN", "; ".join(notes))


def check_coverage(rv, flows, reports):
    areas = {a["area"] for a in (rv.facts.get("diff") or {}).get("areas", [])}
    need = sorted(areas & {"money", "contracts", "federation"})
    if not need:
        rv.add("R12", "GREEN", "no money, contracts or federation area: the flows given are the coverage")
        return
    problems = []
    if FED_FLOW not in flows:
        problems.append(f"the areas touched require the federation suite too ({', '.join(need)} without {FED_FLOW} in the archive)")
    invariant = bool(areas & {"money", "contracts"})
    seen, not_pass = [], []
    if invariant:
        for f in sorted(reports):
            for tool, v in sorted((reports[f]["after"].get("verdicts") or {}).items()):
                if INVARIANT_TOOL.search(tool):
                    seen.append(tool)
                    if v != "pass":
                        not_pass.append(f"{tool} ({v}, {f})")
        if not_pass:
            problems.append(f"invariant tool(s) not pass in the after report: {', '.join(not_pass[:5])}")
    if problems:
        rv.add("R12", "RED", "; ".join(problems))
    elif invariant and not seen:
        rv.add("R12", "NOT MEASURED", "no invariant tool in the report (a tool named supply, delta, invariant or solvency): "
                                      "the invariant is read by hand")
    else:
        rv.add("R12", "GREEN", f"the federation suite is in the archive for {', '.join(need)}"
               + (f"; {len(seen)} invariant tool(s), every one pass" if invariant else ""))


def render(rv, archive, decision, now):
    d = rv.facts
    lines = [f"# Review of {os.path.basename(archive)}", "",
             f"Decision: **{decision}** ({now})", ""]
    if d.get("kit_version"):
        so = d.get("signoff") or {}
        lines.append(f"Kit {d['kit_version']}, release tree `{d['release_tree'][:12]}`, changed tree `{d['changed_tree'][:12]}`, "
                     f"signed off by {so.get('name')} <{so.get('email')}>.")
        lines.append("")
    lines += ["| # | verdict | what was measured |", "|---|---|---|"]
    for cid, v, s in rv.rows:
        lines.append(f"| {cid} | {v} | {s.replace('|', '/')} |")
    lines.append("")
    diff = d.get("diff")
    if diff:
        lines.append(f"## The change: {len(diff['files'])} file(s), +{diff['added']} -{diff['removed']}")
        lines.append("")
        caps = diff.get("caps")
        if caps:
            lines.append(f"Size: {caps['code_files']} code file(s), {caps['changed_lines']} changed line(s); the cap is "
                         f"{caps['cap_files']} files or {caps['cap_lines']} lines"
                         + (f" ({', '.join(caps['risk_areas'])})" if caps["risk_areas"] else "")
                         + (f"; over it, read in slices under design issue {caps['design_issue']}" if caps["over"] and caps["design_issue"]
                            else "; over it" if caps["over"] else "") + ".")
            lines.append("")
        for f in diff["files"]:
            lines.append(f"- `{f['path']}` +{f['added']} -{f['removed']}" + (" (binary)" if f["binary"] else ""))
        lines.append("")
        if diff["areas"]:
            lines.append("## Read these parts slowly")
            lines.append("")
            for a in diff["areas"]:
                lines.append(f"- **{a['area']}**: {a['meaning']} ({', '.join(a['files'][:6])})")
            lines.append("")
    if d.get("reports"):
        lines.append("## The evidence")
        lines.append("")
        rtg = d.get("red_then_green") or {}
        for f, r in d["reports"].items():
            if r.get("control") is not None:
                s = rtg.get(f) or {}
                lines.append(f"- {f}: baseline {r['baseline']} -> control {r['control']} -> after {r['after']}, red then green: "
                             f"{len(s.get('turned_green', []))} of {len(s.get('expected_reds', []))}")
            else:
                lines.append(f"- {f}: baseline {r['baseline']} -> after {r['after']}")
        lines.append("")
    lines += ["## What the machine cannot do", "",
              "- Read the diff. The checks above say the evidence is about this change and holds; they do not say the change is right.",
              "- Read the design against the issue it answers, and the words a user will see.",
              "- Where value moves, read it against the supply invariant and the existing rails (CONTRIBUTING.md §4).",
              "- A NOT MEASURED row is yours to close or to accept as such; a HELD row waits for the thing it names.", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive", help="the contribution-<time>.tar.gz frame-contribute.py wrote")
    ap.add_argument("--pristine", default="", help="the release kit tarball the change is made against")
    ap.add_argument("--cla-file", default="", help="the CLA acceptance record (one acceptance per line)")
    ap.add_argument("--own-after", action="append", default=[], help="your own after report of a flow (frame-test.py)")
    ap.add_argument("--denylist", default=os.getenv("TP_SECRET_DENYLIST", ""), help="a local secret-literal denylist (optional)")
    ap.add_argument("--design-issue", default="", help="the design issue a change over the size caps is read under (an id or a url)")
    ap.add_argument("--out", default="", help="the review page (Markdown); default review-<archive>.md beside the archive")
    ap.add_argument("--json", default="", help="the same as JSON; default beside the page")
    a = ap.parse_args(argv)
    kp = _load("kit_provenance", "kit_provenance.py")
    ft = _load("frame_test", "frame-test.py")
    rv = Review()
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        files, top = read_archive(a.archive)
    except (OSError, tarfile.TarError, ValueError) as e:
        rv.add("R1", "RED", f"the archive cannot be read as a contribution: {e}")
        files, top = {}, ""
    flows = check_shape(rv, files) if files else []
    head, body = parse_header(files.get("contribution.patch", b"")) if files else ({"tests": [], "signoff": None, "errors": ["no patch"]}, "")
    reports = {}
    if files:
        check_manifest(rv, files)
        check_header(rv, head, flows)
        reports = check_evidence(rv, files, head, flows, ft)
        check_diff(rv, head, body, a.design_issue.strip())
        check_secrets(rv, body, a.denylist)
        check_pristine(rv, head, body, a.pristine, kp, reports)
        check_cla(rv, a.cla_file)
        check_own(rv, a.own_after, reports, head, ft)
        check_tests_lines(rv, head, reports)
        check_red_then_green(rv)
        check_coverage(rv, flows, reports)
    decision, rc = rv.decision()
    stem = os.path.basename(a.archive)
    for suf in (".tar.gz", ".tgz"):
        if stem.endswith(suf):
            stem = stem[:-len(suf)]
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.archive)), f"review-{stem}.md")
    js = a.json or (out[:-3] if out.endswith(".md") else out) + ".json"
    page = render(rv, a.archive, decision, now)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(js, "w", encoding="utf-8") as fh:
        json.dump({"archive": os.path.basename(a.archive), "top": top, "decision": decision, "at": now,
                   "checks": [{"id": c, "verdict": v, "sentence": s} for c, v, s in rv.rows], "facts": rv.facts},
                  fh, indent=1, sort_keys=True)
    print(f"[frame-review] {decision}: " + "; ".join(f"{c} {v}" for c, v, _s in rv.rows) + f" -> {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
