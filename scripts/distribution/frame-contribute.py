#!/usr/bin/env python3
"""Package a suggested change with its evidence: the patch, the test reports, the comparison, a sign-off.
  ./frame-contribute.py --pristine <the kit tarball you downloaded> \\
      --baseline <stack-root>/<sandbox>-tests/baseline-flow_mcp_lifecycle_complete.json \\
      --after    <stack-root>/<sandbox>-tests/<time>-flow_mcp_lifecycle_complete.json \\
      --signoff "Your Name <you@example.org>"
--baseline and --after may be given once per flow, in pairs (a federation change carries the lifecycle sweep's pair
and the federation suite's). When your change touches the test suite itself (anything under api_tests/), the two runs
cannot be compared, because a changed test is not evidence about the code; then each flow needs a THIRD report,
--control: the NEW suite run on the UNMODIFIED release images (build the suite change alone, put it on the sandbox, run),
given in the same order. The rules (§REVIEWLANE): the suite change turns no existing tool red on the release; the new
tools may be red there, which is your feature's own tests failing before the feature exists; on your change the same
suite holds no new red, and every one of those reds is green. Red then green, in one archive.
It writes dist/contribution-<time>.tar.gz in the kit holding:
  contribution.patch   a unified diff of every file your tree changed against the release (KIT_FILES.sha256 names them,
                       the tarball supplies the originals), headed by the kit version, both tree digests, each flow's
                       result and your Developer Certificate of Origin sign-off (DCO.md)
  baseline-<flow>.json, [control-<flow>.json,] after-<flow>.json, comparison-<flow>.txt   frame-test.py's reports and
                       their comparison
  MANIFEST.txt         the sha256 of every file in the archive
It refuses when the evidence is not about this change: each after report must name THIS tree's digest (built from the
code you are contributing), each control must name the release plus exactly your suite change, each pair must come from
the same suite, each baseline must be of the unmodified release this tree changes, and no after report may hold a new red
(a regression is fixed before it is suggested). Where the archive goes is not decided by this script.
"""
import argparse
import datetime
import difflib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def die(msg, code=2):
    print(f"[frame-contribute] {msg}", flush=True)
    sys.exit(code)


def is_suite_path(rel: str) -> bool:
    """The test suite frame-test's suite hash covers: the registry's api_tests tree (flows, contracts, the federation suite)."""
    return "/api_tests/" in "/" + rel


def originals(pristine, paths):
    """{path: bytes or None} from the kit tarball (its members sit under one top-level directory)."""
    out = {p: None for p in paths}
    with tarfile.open(pristine, "r:gz") as tar:
        for m in tar:
            if not m.isfile():
                continue
            rel = m.name.split("/", 1)[1] if "/" in m.name else m.name
            if rel in out:
                out[rel] = tar.extractfile(m).read()
    return out


def unified(path, old, new):
    """A unified diff of one file; binary content is named, not diffed."""
    try:
        a = old.decode("utf-8").splitlines(keepends=True) if old is not None else []
        b = new.decode("utf-8").splitlines(keepends=True) if new is not None else []
    except UnicodeDecodeError:
        return f"Binary file {path} differs\n"
    return "".join(difflib.unified_diff(a, b, f"a/{path}" if old is not None else "/dev/null",
                                        f"b/{path}" if new is not None else "/dev/null"))


def control_tree(release: dict, now: dict, suite_changed) -> str:
    """The digest of the release plus exactly the suite change: what the control run must have measured."""
    expected = dict(release)
    for p in suite_changed:
        if p in now:
            expected[p] = now[p]
        else:
            expected.pop(p, None)
    return hashlib.sha256("".join(f"{v}  {k}\n" for k, v in sorted(expected.items())).encode()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pristine", required=True, help="the kit tarball you downloaded (its originals)")
    ap.add_argument("--baseline", required=True, action="append", help="a baseline report (once per flow)")
    ap.add_argument("--after", required=True, action="append", help="the after report of the same flow (same order)")
    ap.add_argument("--control", action="append", default=[],
                    help="the control report of the same flow (same order): the NEW suite on the unmodified release, "
                         "required when the change touches api_tests/")
    ap.add_argument("--signoff", required=True, help='"Your Name <you@example.org>" (DCO.md)')
    ap.add_argument("--root", default=KIT_ROOT, help="the kit tree holding your change (default: this kit)")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    kp = _load("kit_provenance", "kit_provenance.py")
    ft = _load("frame_test", "frame-test.py")
    if "<" not in a.signoff or "@" not in a.signoff:
        die('--signoff must be "Your Name <you@example.org>" (the Developer Certificate of Origin, DCO.md)')
    changed, release = kp.changed(a.root)
    if changed is None:
        die(f"{a.root} has no {kp.MANIFEST}: it is not an unpacked kit, so the change cannot be told apart from the release")
    if not changed:
        die("the tree does not differ from the release: there is nothing to contribute")
    if len(a.baseline) != len(a.after):
        die(f"--baseline and --after come in pairs, one pair per flow ({len(a.baseline)} baseline(s), {len(a.after)} after)")
    if a.control and len(a.control) != len(a.after):
        die(f"--control comes once per flow, in the same order as --baseline and --after ({len(a.control)} control(s), "
            f"{len(a.after)} after)")
    now = kp.digests(a.root)
    tree = kp.tree_digest(now)
    suite_changed = sorted(p for p in changed if is_suite_path(p))
    if suite_changed and not a.control:
        die(f"the change touches the test suite ({', '.join(suite_changed[:3])}{', ...' if len(suite_changed) > 3 else ''}): "
            f"give a --control per flow, the new suite run on the unmodified release images (TEST_VERIFIED_DEVELOPMENT.md §3b), "
            f"because two runs of different suites are not comparable")
    if a.control and not suite_changed:
        die("--control given but the change does not touch the test suite (api_tests/): two runs are the evidence")
    expected_control = control_tree(release, now, suite_changed) if suite_changed else None
    pairs = []
    for i, (bpath, apath) in enumerate(zip(a.baseline, a.after)):
        baseline, after = json.load(open(bpath)), json.load(open(apath))
        flow = after.get("flow") or "?"
        if (after.get("build") or {}).get("tree_digest") != tree:
            die(f"{apath}: the after report measured tree {str((after.get('build') or {}).get('tree_digest'))[:12]}, and "
                f"this tree is {tree[:12]}: build it (./build.sh), put it on the sandbox (./frame-update.py) and run "
                f"./frame-test.py again")
        if (baseline.get("build") or {}).get("modified") is not False:
            die(f"{bpath}: the baseline did not run the unmodified release (its build says modified is not false): take "
                f"the baseline on the release images")
        if (baseline.get("build") or {}).get("tree_digest") != kp.tree_digest(release):
            die(f"{bpath}: the baseline ran release {str((baseline.get('build') or {}).get('tree_digest'))[:12]}, and this "
                f"tree changes release {kp.tree_digest(release)[:12]}: take the baseline on the release this change is made "
                f"against")
        if baseline.get("flow") != flow or not after.get("suite_hash"):
            die(f"{bpath} and {apath} did not run the same flow, or the after report carries no suite hash: not comparable")
        if baseline.get("report_format") != after.get("report_format"):
            die(f"{bpath} and {apath} were written in different report formats: take the baseline again with this frame-test")
        if any(flow == f for f, *_rest in pairs):
            die(f"two pairs for the flow {flow}: give one pair per flow")
        stage = None
        if a.control:
            cpath = a.control[i]
            control = json.load(open(cpath))
            cb = control.get("build") or {}
            if cb.get("tree_digest") != expected_control:
                die(f"{cpath}: the control measured tree {str(cb.get('tree_digest'))[:12]}, and the release plus your suite "
                    f"change is {expected_control[:12]}: build the suite change ALONE first, put it on the sandbox and run "
                    f"(TEST_VERIFIED_DEVELOPMENT.md §3b)")
            if cb.get("modified") is not True:
                die(f"{cpath}: the control does not say its tree differs from the release")
            if control.get("flow") != flow:
                die(f"{cpath}: the control ran the flow {control.get('flow')}, not {flow}")
            if not control.get("suite_hash") or control.get("suite_hash") != after.get("suite_hash"):
                die(f"{cpath} and {apath} did not run the same suite: the control must run the suite you are contributing")
            if control.get("report_format") != after.get("report_format"):
                die(f"{cpath} and {apath} were written in different report formats")
            c1 = ft.compare(control, baseline)
            if c1["new_reds"]:
                die(f"{flow}: your suite change turns {len(c1['new_reds'])} existing tool(s) red on the release "
                    f"({', '.join(c1['new_reds'][:5])}): a changed test that fails on the release is not evidence about "
                    f"the code", 1)
            expected = sorted(t for t in c1["added"] if control["verdicts"].get(t) == "fail")
            cmp = ft.compare(after, control)
            if cmp["new_reds"]:
                die(f"{flow}: the after report holds {len(cmp['new_reds'])} new red(s) against the control "
                    f"({', '.join(cmp['new_reds'][:5])}): fix them first", 1)
            not_green = sorted(t for t in expected if after["verdicts"].get(t) != "pass")
            if not_green:
                die(f"{flow}: {len(not_green)} of the {len(expected)} new test(s) that fail on the release still fail on "
                    f"your change ({', '.join(not_green[:5])}): the change does not turn its own tests green", 1)
            stage = {"control": control, "control_new_reds": c1["new_reds"], "control_added": c1["added"],
                     "control_gone": c1["gone"], "expected_reds": expected, "turned_green": expected}
        else:
            if baseline.get("suite_hash") != after.get("suite_hash"):
                die(f"{bpath} and {apath} did not run the same suite (suite hash differs): not comparable; a change to "
                    f"api_tests/ needs a --control per flow")
            cmp = ft.compare(after, baseline)
            if cmp["new_reds"]:
                die(f"{flow}: the after report holds {len(cmp['new_reds'])} new red(s) "
                    f"({', '.join(cmp['new_reds'][:5])}): fix them first", 1)
        pairs.append((flow, baseline, after, cmp, stage))
    olds = originals(a.pristine, changed)
    now_stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kit_version = (pairs[0][2].get("build") or {}).get("kit_version") or "?"
    head = [f"TheProtocol kit {kit_version}: a suggested change",
            f"release tree {kp.tree_digest(release)}", f"changed tree {tree}", f"files changed: {len(changed)}"]
    for flow, b, af, _c, stage in pairs:
        if stage:
            head.append(f"tests: {flow} {b.get('summary_line')} -> {stage['control'].get('summary_line')} -> "
                        f"{af.get('summary_line')}, red then green: {len(stage['expected_reds'])}")
        else:
            head.append(f"tests: {flow} {b.get('summary_line')} -> {af.get('summary_line')}, no new red")
    head += ["", f"Signed-off-by: {a.signoff}", "", ""]
    body = "".join(unified(p, olds[p], open(os.path.join(a.root, p), "rb").read() if os.path.isfile(os.path.join(a.root, p)) else None)
                   for p in changed)
    files = {"contribution.patch": ("\n".join(head) + body).encode()}
    for flow, baseline, after, cmp, stage in pairs:
        lines = [f"flow:     {flow}", f"baseline: {baseline.get('summary_line')}"]
        if stage:
            lines.append(f"control:  {stage['control'].get('summary_line')}")
        lines.append(f"after:    {after.get('summary_line')}")
        for k in ("new_reds", "new_greens", "still_red", "added", "gone"):
            lines.append(f"{k} ({len(cmp[k])}): {', '.join(cmp[k])}")
        if stage:
            for k in ("control_new_reds", "control_added", "control_gone", "expected_reds", "turned_green"):
                lines.append(f"{k} ({len(stage[k])}): {', '.join(stage[k])}")
            files[f"control-{flow}.json"] = json.dumps(stage["control"], indent=1, sort_keys=True).encode()
        files[f"baseline-{flow}.json"] = json.dumps(baseline, indent=1, sort_keys=True).encode()
        files[f"after-{flow}.json"] = json.dumps(after, indent=1, sort_keys=True).encode()
        files[f"comparison-{flow}.txt"] = ("\n".join(lines) + "\n").encode()
    files["MANIFEST.txt"] = "".join(f"{hashlib.sha256(v).hexdigest()}  {k}\n" for k, v in sorted(files.items())).encode()
    # under dist/ (a build output, outside what kit_provenance digests), so the archive never becomes part of the change
    out = a.out or os.path.join(a.root, "dist", f"contribution-{now_stamp}.tar.gz")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(f"contribution-{now_stamp}/{name}")
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    print(f"[frame-contribute] {out}: {len(changed)} changed file(s)"
          + (f", {len(suite_changed)} in the suite (red then green)" if suite_changed else "") + "; "
          + "; ".join(f"{f}: {af.get('summary_line')}" for f, _b, af, _c, _s in pairs) + ", no new red")
    return 0


if __name__ == "__main__":
    sys.exit(main())
