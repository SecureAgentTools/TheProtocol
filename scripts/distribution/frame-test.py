#!/usr/bin/env python3
"""Run the MCP tester in a sandbox and compare runs: the last step of test-verified development.

  ./frame-test.py --name <sandbox> --baseline          run the suite on the release images; the report becomes the baseline
  ./frame-test.py --name <sandbox> --compare           run it again (after frame-update.py put your build on the sandbox)
                                                       and compare with the baseline: exit 0 only with no new red
  ./frame-test.py --name <sandbox> --run               run and report, no comparison
  ./frame-test.py --compare --report <new.json> --against <old.json>     compare two reports already on disk

The suite runs INSIDE the sandbox's registry against itself (its own MCP tester, the same run the MCP tester view
starts), as the sandbox's admin. Each report records what was measured: the per-tool verdicts, the build's provenance
from /health (kit version, tree digest, whether it differs from the release), the registry image's id and labels, and a
hash of the suite's own files. Two reports whose suite hash differs measured different tests and are not compared.
Reports go to <stack-root>/<sandbox>-tests/ (kept when the sandbox is torn down).
"""
import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_spec = importlib.util.spec_from_file_location("frame_names", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_names.py"))
frame_names = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(frame_names)

DEFAULT_FLOW = "flow_mcp_lifecycle_complete"
# 2: a tool the sweep runs on more than one surface is keyed tool@tier (the gateway meta-tools run on the public AND the
# admin surface; keyed by name alone, the admin result overwrote the public one, so a regression on one surface was hidden).
# Reports of different formats are never compared: their keys differ, so every tool would read "gone" and "added" and no
# red could be new, a pass by construction.
REPORT_FORMAT = 2
RANK = {"fail": 2, "pass": 1, "skip": 0}
TERMINAL = ("completed", "complete", "done", "failed", "error", "finished", "cancelled")
# the suite's own files as the image holds them: a release image ships them as bytecode, whose 16-byte header carries a
# source timestamp that differs between two builds of the same code, so a .pyc is hashed from byte 16 (the code object)
SUITE_HASH_PY = r"""
import hashlib, os
root = "/app/src/agentvault_registry/api_tests"
h, n = hashlib.sha256(), 0
for d, dirs, fs in sorted(os.walk(root)):
    dirs.sort()
    if "__pycache__" in d:
        continue
    for f in sorted(fs):
        if f.endswith((".py", ".pyc")):
            b = open(os.path.join(d, f), "rb").read()
            b = b[16:] if f.endswith(".pyc") else b
            h.update(os.path.relpath(os.path.join(d, f), root).encode() + b"\0" + hashlib.sha256(b).digest())
            n += 1
print(h.hexdigest() if n else "")
"""


def log(msg):
    print(f"[frame-test {time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def die(msg, code=2):
    log(msg)
    sys.exit(code)


def http(method, url, body=None, headers=None, form=False, timeout=120):
    data, h = None, dict(headers or {})
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except Exception as exc:  # noqa: BLE001 — the caller says what it could not reach
        return None, str(exc)[:200]


def verdict(r):
    if r.get("skipped"):
        return "skip"
    return "pass" if r.get("healthy") else "fail"


def why(r):
    return str(r.get("skip_reason") or r.get("error") or "")[:200]


def keyed_verdicts(results):
    """({key: verdict}, {key: reason}) of one run. A tool name that occurs once is its own key; one that occurs more than
    once is keyed tool@tier; a key that still repeats keeps its WORST verdict (fail over pass over skip)."""
    seen = {}
    for r in results:
        if r.get("tool"):
            seen[r["tool"]] = seen.get(r["tool"], 0) + 1
    verdicts, reasons = {}, {}
    for r in results:
        t = r.get("tool")
        if not t:
            continue
        k = t if seen[t] == 1 else f"{t}@{r.get('tier') or 'none'}"
        v = verdict(r)
        if k not in verdicts or RANK[v] > RANK[verdicts[k]]:
            verdicts[k] = v
            if v != "pass":
                reasons[k] = why(r)
            else:
                reasons.pop(k, None)
    return verdicts, reasons


def compare(new, old):
    """{new_reds, new_greens, still_red, gone, added} between two reports (tool names)."""
    nv, ov = new["verdicts"], old["verdicts"]
    common = set(nv) & set(ov)
    return {
        "new_reds": sorted(t for t in common if nv[t] == "fail" and ov[t] != "fail"),
        "new_greens": sorted(t for t in common if nv[t] == "pass" and ov[t] == "fail"),
        "still_red": sorted(t for t in common if nv[t] == "fail" and ov[t] == "fail"),
        "gone": sorted(set(ov) - set(nv)),
        "added": sorted(set(nv) - set(ov)),
    }


def print_comparison(cmp, new, old):
    log(f"baseline: {old['summary_line']}  ({old.get('build', {}).get('tree_digest', '?')[:12]}, "
        f"modified={old.get('build', {}).get('modified')})")
    log(f"this run: {new['summary_line']}  ({new.get('build', {}).get('tree_digest', '?')[:12]}, "
        f"modified={new.get('build', {}).get('modified')})")
    for key, label in (("new_reds", "NEW RED"), ("new_greens", "new green"), ("still_red", "still red"),
                       ("added", "new tool"), ("gone", "tool gone")):
        items = cmp[key]
        if items:
            log(f"{label} ({len(items)}): " + ", ".join(items[:12]) + (" ..." if len(items) > 12 else ""))
            if key == "new_reds":
                for t in items[:12]:
                    log(f"    {t}: {new['reasons'].get(t, '')}")


def run_suite(stack_root, name, flow, timeout_min, baseline=False):
    dirs = frame_names.stack_dirs(stack_root, name, need_file="frame-up.json")
    if not dirs:
        die(f"no frame named {name} under {stack_root}")
    rec = json.load(open(os.path.join(stack_root, dirs[-1], "frame-up.json")))
    if not rec.get("sandbox_of"):
        die(f"{name} is not a sandbox: the suite runs only in a sandbox (frame-sandbox.py up --for <frame>)")
    base = f"http://127.0.0.1:{(rec.get('ports') or {}).get('registry')}"
    sec_path = os.path.join(rec.get("secrets_dir") or os.path.join(stack_root, f"{name}-secrets"), f".{name}_frame_admin.secret.json")
    try:
        sec = json.load(open(sec_path))
    except OSError:
        die(f"the sandbox's admin login is not readable ({sec_path}); run as the user that stood it up")

    def login():
        st, tok = http("POST", base + "/api/v1/auth/login", {"username": sec["admin_email"], "password": sec["admin_password"]}, form=True)
        if st != 200 or not isinstance(tok, dict):
            die(f"the sandbox's admin could not log in (HTTP {st})")
        return {"Authorization": f"Bearer {tok['access_token']}"}

    auth = login()
    st, health = http("GET", base + "/health")
    build = (health or {}).get("build") if isinstance(health, dict) else None
    # a baseline is the release's own result: taken on a changed build it would hide exactly what the change broke
    # (checked before the run, not after forty minutes of it)
    if baseline and (build or {}).get("modified") is True:
        die(f"{name} runs a build that differs from the release ({(build or {}).get('changed_files')} changed file(s)): a "
            f"baseline is taken on the release images (./frame-update.py --name {name} --rollback puts them back)")
    if baseline and (build or {}).get("modified") is not False:
        log(f"{name}'s build does not say whether it differs from the release (an image built without the kit's "
            f"provenance): this baseline can be compared with, but frame-contribute.py will not accept it")
    img = subprocess.run(["docker", "inspect", f"{name}-registry", "--format", "{{.Image}}\t{{json .Config.Labels}}"],
                         capture_output=True, text=True).stdout.strip()
    image_id, _, labels = img.partition("\t")
    try:
        labels = {k: v for k, v in (json.loads(labels or "{}") or {}).items() if k.startswith("org.theprotocol.kit.")}
    except ValueError:
        labels = {}
    suite = subprocess.run(["docker", "exec", f"{name}-registry", "python3", "-c", SUITE_HASH_PY], capture_output=True, text=True)
    suite_hash = suite.stdout.strip() if suite.returncode == 0 and len(suite.stdout.strip()) == 64 else None
    st, started = http("POST", base + "/api/v1/admin/mcp-tester/run", {"flow_name": flow}, headers=auth)
    rid = (started or {}).get("run_id") if isinstance(started, dict) else None
    if st != 200 or not rid:
        die(f"the sandbox refused the run: HTTP {st} {started}")
    log(f"{name}: run {rid} ({flow}) started")
    t0, run, last = time.time(), None, None
    while time.time() - t0 < timeout_min * 60:
        time.sleep(20)
        if time.time() - t0 > 600 and int(time.time() - t0) % 600 < 20:
            auth = login()                 # a login lasts; refresh it every ten minutes of a long run
        st, run = http("GET", base + f"/api/v1/admin/mcp-tester/runs/{rid}", headers=auth)
        state = (run or {}).get("status") if isinstance(run, dict) else None
        if state != last:
            log(f"{name}: run {rid} {state} after {int(time.time() - t0)} s")
            last = state
        if state in TERMINAL:
            break
    else:
        die(f"run {rid} did not finish within {timeout_min} min", 3)
    st, full = http("GET", base + f"/api/v1/admin/mcp-tester/runs/{rid}?include_results=true", headers=auth, timeout=300)
    results = (full or {}).get("results") or [] if isinstance(full, dict) else []
    s = (full or {}).get("summary") or {}
    verdicts, reasons = keyed_verdicts(results)
    counts = {v: sum(1 for x in verdicts.values() if x == v) for v in ("pass", "fail", "skip")}
    return {
        "report_format": REPORT_FORMAT, "sandbox": name, "flow": flow, "run_id": rid, "status": (full or {}).get("status"),
        "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": {k: s.get(k) for k in ("tool_count", "passed", "failed", "skipped", "pass_pct") if k in s},
        "counts": counts, "summary_line": f"{len(verdicts)} tools: {counts['pass']} pass, {counts['fail']} fail, {counts['skip']} skip",
        "build": build or {}, "image_id": image_id, "image_labels": labels, "suite_hash": suite_hash,
        "verdicts": verdicts, "reasons": reasons, "error": (full or {}).get("error"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", help="the sandbox")
    ap.add_argument("--flow", default=DEFAULT_FLOW, help=f"the tester flow (default {DEFAULT_FLOW}; the federation "
                                                         f"suite is flow_federation_suite_complete on a pair)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--compare", action="store_true")
    ap.add_argument("--report", help="with --compare: a report already on disk instead of a new run")
    ap.add_argument("--against", help="with --compare: the report to compare with (default: the sandbox's baseline)")
    ap.add_argument("--timeout-min", type=float, default=60)
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"))
    a = ap.parse_args(argv)
    if not a.report and not a.name:
        die("--name <sandbox> is required unless --compare is given two reports")
    out_dir = os.path.join(a.stack_root, f"{a.name}-tests") if a.name else None
    if a.compare and not a.report:
        # the baseline this run will be compared with must exist BEFORE the run, not after minutes of it
        against = a.against or os.path.join(out_dir, f"baseline-{a.flow}.json")
        if not os.path.isfile(against):
            die(f"no baseline to compare with ({against}): run --baseline first (with the same --flow)")
    if a.report:
        new = json.load(open(a.report))
    else:
        new = run_suite(a.stack_root, a.name, a.flow, a.timeout_min, baseline=a.baseline)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{new['at'].replace(':', '')}-{a.flow}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(new, f, indent=1, sort_keys=True)
        log(f"report: {path} ({new['summary_line']})")
        if a.baseline:
            with open(os.path.join(out_dir, f"baseline-{a.flow}.json"), "w", encoding="utf-8") as f:
                json.dump(new, f, indent=1, sort_keys=True)
            log(f"baseline set: {out_dir}/baseline-{a.flow}.json")
            return 0
    if not a.compare:
        return 0
    against = a.against or (os.path.join(out_dir, f"baseline-{new['flow']}.json") if out_dir else None)
    if not against or not os.path.isfile(against):
        die(f"no baseline to compare with ({against}): run --baseline first")
    old = json.load(open(against))
    if new.get("flow") != old.get("flow"):
        die(f"the reports ran different flows ({new.get('flow')} / {old.get('flow')}): not comparable", 4)
    if new.get("report_format") != old.get("report_format"):
        die(f"the reports were written in different formats ({old.get('report_format')} / {new.get('report_format')}): their "
            f"tool keys differ, so not comparable; take the baseline again with this frame-test", 4)
    if not new.get("suite_hash") or new.get("suite_hash") != old.get("suite_hash"):
        die(f"the suite itself differs between the two runs (suite hash {str(old.get('suite_hash'))[:12]} -> "
            f"{str(new.get('suite_hash'))[:12]}): a changed test is not evidence about the code; not comparable", 4)
    nb, ob = new.get("build") or {}, old.get("build") or {}
    if nb.get("modified") is True and nb.get("release_digest") and ob.get("tree_digest") and nb["release_digest"] != ob["tree_digest"]:
        die(f"this build changes release {nb['release_digest'][:12]}, and the baseline ran release {ob['tree_digest'][:12]}: "
            f"a new red could be the other release's, not the change's; not comparable (take the baseline on the release "
            f"this change is made against)", 4)
    cmp = compare(new, old)
    print_comparison(cmp, new, old)
    if cmp["new_reds"]:
        log(f"RESULT: {len(cmp['new_reds'])} new red(s): the change breaks what the release passed")
        return 1
    log("RESULT: no new red")
    return 0


if __name__ == "__main__":
    sys.exit(main())
