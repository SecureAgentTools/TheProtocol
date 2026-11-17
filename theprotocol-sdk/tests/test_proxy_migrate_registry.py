"""V0664 Migrate (M3): the commands that act on a registry. certify refuses without a passing reconcile and then sends ONE
attestation (migration.certificate) carrying every report's hash and the kit's content hash; get writes a kit only when
its content hash holds (a tampered kit is refused, nothing written); publish creates then versions; fork forks then
gets. The library routes are section D's, answered here by a fake. Red before M3: no `migrate` command."""
from __future__ import annotations

import json
import os

import httpx
import pytest

import proxy_fake as F
import test_proxy_migrate_run as RUN

sqlkit = RUN.sqlkit           # the SQLite kit fixture, shared
tpj = RUN.tpj

LIB = "/api/v1/workflow-templates"


class Library:
    """The fake registry (token, attestations) plus section D's library routes."""

    def __init__(self):
        self.reg = F.FakeRegistry()
        self.templates = {}
        self.seen = []
        self.keys = {}      # Idempotency-Key -> (body, response): the registry's replay of a retried POST

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if not path.startswith(LIB):
            return self.reg.handle(request)
        self.seen.append((request.method, path, request.headers.get("idempotency-key")))
        body = json.loads(request.content) if request.content else {}
        parts = path[len(LIB):].strip("/").split("/") if path != LIB else []
        if request.method == "POST" and not parts:
            tid = f"wtpl_{len(self.templates) + 1}"
            self.templates[tid] = {"id": tid, "slug": body["slug"], "versions": {1: body}, "published": set(),
                                   "meta": {k: body.get(k) for k in ("visibility", "pricing_model", "price")}}
            return httpx.Response(201, json={"template_id": tid, "version": 1})
        t = self.templates.get(parts[0]) if parts else None
        if t is None:
            return httpx.Response(404, json={"detail": "no such template"})
        if request.method == "GET" and len(parts) == 1:
            return httpx.Response(200, json={"id": t["id"], "slug": t["slug"],
                                             "current_version": max(t["published"], default=None)})
        if request.method == "POST" and parts[1:] == ["versions"]:
            n = max(t["versions"]) + 1
            t["versions"][n] = body
            return httpx.Response(201, json={"template_id": t["id"], "version": n})
        if request.method == "POST" and len(parts) == 4 and parts[3] == "publish":
            t["published"].add(int(parts[2]))
            return httpx.Response(200, json={"published": True})
        if request.method == "GET" and len(parts) == 4 and parts[3] == "kit":
            v = t["versions"][int(parts[2])]
            from theprotocol.proxy.migrate import content_hash
            h = t.get("served_hash") or content_hash(v["manifest"], v["files"])
            files = dict(v["files"])
            if t.get("tamper"):
                files["README.md"] = files["README.md"] + "\nchanged on the way\n"
            return httpx.Response(200, json={"template_id": t["id"], "version": int(parts[2]), "files": files,
                                             "content_hash": h})
        if request.method == "POST" and parts[1:] == ["fork"]:
            # section D's fork, as the registry answers it: body.slug required (422), one slug per agent (409), and a
            # retried key replays the first answer
            key = request.headers.get("idempotency-key")
            if key in self.keys:
                first_body, first = self.keys[key]
                if first_body != body:
                    return httpx.Response(422, json={"detail": "the Idempotency-Key was used with another body"})
                return first
            slug = str(body.get("slug") or "")
            import re
            if not re.match(r"^[a-z0-9][a-z0-9-]{1,118}$", slug):
                return httpx.Response(422, json={"detail": "a slug of 2 to 119 lowercase letters, digits and '-'",
                                                 "code": "slug"})
            if any(x["slug"] == slug for x in self.templates.values()):
                return httpx.Response(409, json={"detail": {"code": "slug_taken",
                                                            "message": "this agent already has a template with that slug"}})
            fid = f"wtpl_{len(self.templates) + 1}"
            src = t["versions"][max(t["published"])]
            self.templates[fid] = {"id": fid, "slug": slug, "versions": {1: src}, "published": {1}, "meta": {}}
            resp = httpx.Response(201, json={"template_id": fid, "slug": slug})
            self.keys[key] = (body, resp)
            return resp
        if request.method == "POST" and parts[1:] == ["certified"]:
            t.setdefault("certified", []).append((body["attestation_id"], body["attestation_data"]))
            return httpx.Response(200, json={"counted": True})
        if request.method == "PATCH" and len(parts) == 1:
            t["meta"].update(body)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"detail": f"no route {path}"})

    @property
    def transport(self):
        return httpx.MockTransport(self.handle)


@pytest.fixture
def lib():
    return Library()


@pytest.fixture
def identity(tmp_path, monkeypatch):
    monkeypatch.setenv("TP_TEST_CLIENT_SECRET", F.CLIENT_SECRET)
    p = tmp_path / "agent-proxy.yaml"
    p.write_text(f"""version: 1
name: my-agent
registry: https://registry.test
identity:
  agent_did: {F.DID}
  client_id: {F.CLIENT_ID}
  client_secret: env:TP_TEST_CLIENT_SECRET
sources: {{}}
mappings: []
""")
    return str(p)


def tpt(argv, capsys, transport):
    from theprotocol.proxy.cli import main
    code = main([*argv, "--json"], transport=transport)
    return code, json.loads(capsys.readouterr().out)


def test_certify_refuses_without_a_passing_reconcile(sqlkit, identity, lib, capsys):
    code, ans = tpt(["migrate", "certify", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 1 and any("no load report" in p for p in ans["problems"])
    assert tpj(["migrate", "load", "--confirm-destinations", sqlkit["kit"], *sqlkit["sets"]], capsys)[0] == 0
    import sqlite3
    c = sqlite3.connect(sqlkit["target"])
    c.execute("UPDATE customers SET email = 'x@example.invalid' WHERE legacy_id = 1")
    c.commit()
    c.close()
    assert tpj(["migrate", "reconcile", sqlkit["kit"], *sqlkit["sets"]], capsys)[0] == 1
    code, ans = tpt(["migrate", "certify", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 1 and any("did not pass" in p for p in ans["problems"])
    assert lib.reg.writes() == []


def test_certify_sends_one_attestation_with_every_reports_hash(sqlkit, identity, lib, capsys):
    for step in (["plan"], ["dry-run", "--sample"], ["load", "--confirm-destinations"], ["reconcile"]):
        assert tpj(["migrate", step[0], sqlkit["kit"], *step[1:], *sqlkit["sets"]], capsys)[0] == 0
    code, ans = tpt(["migrate", "certify", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 0, ans
    assert len(lib.reg.effects) == 1
    body = lib.reg.effects[0]
    assert body["attestation_type"] == "migration.certificate" and body["target_agent_did"] == F.DID
    claim = body["attestation_data"]["claim"]
    from theprotocol.proxy.migrate import load_kit
    from theprotocol.proxy.migrate.reports import newest
    kit = load_kit(sqlkit["kit"])
    assert claim["template"] == {"local": kit.content_hash}
    for step in ("inventory", "dry_run", "load", "reconcile"):
        assert claim["reports"][step] == newest(kit, step)[0]["report_sha256"]
    assert claim["verdict"] == "pass" and claim["moved"] == 4 and claim["rejected"] == 0
    assert ans["attestation_id"] == "att-1"
    # again: the same claim, the same key, the registry answers its first answer; nothing is kept twice
    code, ans = tpt(["migrate", "certify", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 0 and len(lib.reg.effects) == 1


def test_certify_refuses_a_report_changed_after_it_was_written(sqlkit, identity, lib, capsys):
    for step in ("load", "reconcile"):
        assert tpj(["migrate", step, sqlkit["kit"], *(["--confirm-destinations"] if step == "load" else []),
                    *sqlkit["sets"]], capsys)[0] == 0
    d = os.path.join(sqlkit["kit"], ".migrate", "reports")
    f = next(os.path.join(d, x) for x in os.listdir(d) if x.startswith("reconcile-"))
    doc = json.load(open(f))
    doc["reconcile"]["customers"]["mismatched"] = 0
    doc["verdict"] = "pass"
    doc["targets"] = {"forged": {}}
    json.dump(doc, open(f, "w"))
    code, ans = tpt(["migrate", "certify", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 1 and any("does not hold" in p for p in ans["problems"]) and lib.reg.effects == []


def test_publish_get_fork_and_a_certified_library_kit(sqlkit, identity, lib, capsys, tmp_path):
    code, ans = tpt(["migrate", "publish", sqlkit["kit"], "--identity", identity, "--price", "0"], capsys,
                    lib.transport)
    assert code == 0 and ans["created"] is True and ans["version"] == 1, ans
    tid = ans["template_id"]
    # a second publish of the kit is a new version of the same template
    open(os.path.join(sqlkit["kit"], "README.md"), "a").write("More words.\n")
    code, ans = tpt(["migrate", "publish", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 0 and ans["created"] is False and ans["template_id"] == tid and ans["version"] == 2
    assert {(m, p) for m, p, _ in lib.seen if m == "POST"} >= {("POST", LIB), ("POST", f"{LIB}/{tid}/versions"),
                                                              ("POST", f"{LIB}/{tid}/versions/1/publish"),
                                                              ("POST", f"{LIB}/{tid}/versions/2/publish")}
    # get: a free kit needs no identity, the newest published version by default
    out = tmp_path / "got"
    code, ans = tpt(["migrate", "get", tid, "--registry", "https://registry.test", "--out", str(out)], capsys,
                    lib.transport)
    assert code == 0, ans
    assert ans["template"]["id"] == tid and ans["template"]["version"] == 2
    assert "More words." in (out / "README.md").read_text()
    # get keeps the files as they came, so what the template names stays known after the user edits the kit (M11)
    assert (out / ".migrate" / "template" / "proxy.yaml").read_text() == (out / "proxy.yaml").read_text()
    # fork: the library's fork, then its kit
    code, ans = tpt(["migrate", "fork", tid, "--identity", identity, "--out", str(tmp_path / "forked")], capsys,
                    lib.transport)
    assert code == 0 and ans["forked_from"] == tid and ans["template_id"] != tid, ans
    assert (tmp_path / "forked" / "migration.yaml").is_file()


def test_get_refuses_a_tampered_kit_and_writes_nothing(sqlkit, identity, lib, capsys, tmp_path):
    code, ans = tpt(["migrate", "publish", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    tid = ans["template_id"]
    lib.templates[tid]["tamper"] = True
    out = tmp_path / "bad"
    code, ans = tpt(["migrate", "get", tid, "--registry", "https://registry.test", "--out", str(out)], capsys,
                    lib.transport)
    assert code == 1 and any("content hash" in p and "refused" in p for p in ans["problems"]), ans
    assert not out.exists()


def test_certify_counts_a_library_kit_on_the_library(sqlkit, identity, lib, capsys, tmp_path):
    code, ans = tpt(["migrate", "publish", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    tid = ans["template_id"]
    for step in ("load", "reconcile"):
        assert tpj(["migrate", step, sqlkit["kit"], *(["--confirm-destinations"] if step == "load" else []),
                    *sqlkit["sets"]], capsys)[0] == 0
    code, ans = tpt(["migrate", "certify", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 0 and ans["library"] == "counted", ans
    sent = lib.reg.effects[0]["attestation_data"]
    assert lib.templates[tid]["certified"] == [(ans["attestation_id"], sent)]
    assert sent["claim"]["template"]["id"] == tid
    # the exact data the TEG hashed, kept beside the id: the hash the library checks holds
    import hashlib
    cert = json.load(open(os.path.join(sqlkit["kit"], ".migrate", "certificate.json")))
    assert cert["attestation_id"] == ans["attestation_id"] and cert["attestation_data"] == sent
    assert hashlib.sha256(json.dumps(cert["attestation_data"], sort_keys=True).encode()).hexdigest() in lib.reg.hashes


def test_certify_needs_an_identity(sqlkit, capsys):
    for step in ("load", "reconcile"):
        assert tpj(["migrate", step, sqlkit["kit"], *(["--confirm-destinations"] if step == "load" else []),
                    *sqlkit["sets"]], capsys)[0] == 0
    code, ans = tpj(["migrate", "certify", sqlkit["kit"]], capsys)
    assert code == 2 and "--identity" in ans["problems"][0]


# ── V0664 M8 step 4 (session-tester, seq 4090; session-lead seq 4106): the CLI fork sends a slug ──
def _published(sqlkit, identity, lib, capsys):
    code, ans = tpt(["migrate", "publish", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 0, ans
    return ans["template_id"]


def _fork_posts(lib):
    return [(p, k) for m, p, k in lib.seen if m == "POST" and p.endswith("/fork")]


def test_fork_sends_the_parents_slug_with_fork_and_a_retry_lands_on_the_same_fork(sqlkit, identity, lib, capsys,
                                                                                    tmp_path):
    tid = _published(sqlkit, identity, lib, capsys)
    parent = lib.templates[tid]["slug"]
    code, ans = tpt(["migrate", "fork", tid, "--identity", identity, "--out", str(tmp_path / "a")], capsys, lib.transport)
    assert code == 0, ans
    fid = ans["template_id"]
    assert lib.templates[fid]["slug"] == f"{parent}-fork"
    n = len(lib.templates)
    # the same command again (a retry): the same slug, the same key, the registry's replay: no second fork
    code, ans = tpt(["migrate", "fork", tid, "--identity", identity, "--out", str(tmp_path / "b")], capsys, lib.transport)
    assert code == 0 and ans["template_id"] == fid and len(lib.templates) == n, ans
    keys = [k for _, k in _fork_posts(lib)]
    assert len(keys) == 2 and keys[0] == keys[1] and f"{parent}-fork" in keys[0]


def test_fork_slug_option_names_the_fork_and_goes_into_the_key(sqlkit, identity, lib, capsys, tmp_path):
    tid = _published(sqlkit, identity, lib, capsys)
    code, ans = tpt(["migrate", "fork", tid, "--slug", "my-own-copy", "--identity", identity,
                     "--out", str(tmp_path / "a")], capsys, lib.transport)
    assert code == 0, ans
    assert lib.templates[ans["template_id"]]["slug"] == "my-own-copy"
    assert "my-own-copy" in _fork_posts(lib)[-1][1]
    # --slug is read before anything is sent: a bad one is refused here, nothing posted
    before = len(_fork_posts(lib))
    code, ans = tpt(["migrate", "fork", tid, "--slug", "Bad Slug", "--identity", identity,
                     "--out", str(tmp_path / "b")], capsys, lib.transport)
    assert code == 1 and any("--slug" in p for p in ans["problems"]) and len(_fork_posts(lib)) == before, ans


def test_fork_with_a_taken_slug_exits_1_naming_slug(sqlkit, identity, lib, capsys, tmp_path):
    tid = _published(sqlkit, identity, lib, capsys)
    parent = lib.templates[tid]["slug"]
    lib.templates["wtpl_99"] = {"id": "wtpl_99", "slug": f"{parent}-fork", "versions": {}, "published": set(),
                                "meta": {}}
    code, ans = tpt(["migrate", "fork", tid, "--identity", identity, "--out", str(tmp_path / "a")], capsys, lib.transport)
    assert code == 1 and any("already has a template" in p and "--slug" in p for p in ans["problems"]), ans
    assert not (tmp_path / "a").exists()


def test_the_stub_refuses_a_fork_without_a_slug(sqlkit, identity, lib, capsys):
    """The control: the stub answers the empty body exactly as the registry did in M8 (422), so the tests above
    could not pass with the old json={}."""
    tid = _published(sqlkit, identity, lib, capsys)
    r = lib.handle(httpx.Request("POST", f"https://registry.test{LIB}/{tid}/fork", json={},
                                 headers={"Idempotency-Key": "k-empty"}))
    assert r.status_code == 422 and "slug" in r.text


def test_fork_slug_default_stays_inside_the_librarys_rule():
    from theprotocol.proxy.migrate.commands import FORK_SLUG, fork_slug
    assert fork_slug("sql-to-postgres") == "sql-to-postgres-fork"
    long = fork_slug("a" * 119)
    assert len(long) <= 119 and long.endswith("-fork") and FORK_SLUG.match(long)
    assert FORK_SLUG.match(fork_slug("")) and FORK_SLUG.match(fork_slug("x-" * 70))


# ── session-tester, seq 4099: certify says why the library does not count it ──
def test_certify_on_a_changed_library_kit_says_not_counted(sqlkit, identity, lib, capsys, tmp_path):
    tid = _published(sqlkit, identity, lib, capsys)
    out = tmp_path / "got"
    code, ans = tpt(["migrate", "get", tid, "--registry", "https://registry.test", "--out", str(out)], capsys,
                    lib.transport)
    assert code == 0, ans
    (out / "README.md").write_text((out / "README.md").read_text() + "\nmy own note\n")
    from theprotocol.proxy.migrate import load_kit
    assert "local" in load_kit(str(out)).template_ref()
    import test_proxy_migrate_run as RUN2
    sets = [x.replace(sqlkit["kit"], str(out)) for x in sqlkit["sets"]]
    for step in ("load", "reconcile"):
        assert RUN2.tpj(["migrate", step, str(out), *(["--confirm-destinations"] if step == "load" else []), *sets],
                        capsys)[0] == 0
    code, ans = tpt(["migrate", "certify", str(out), "--identity", identity], capsys, lib.transport)
    assert code == 0 and ans["library"] == "not counted: the kit files differ from version 1", ans
    assert "certified" not in lib.templates[tid]


def test_certify_on_a_local_kit_says_not_counted(sqlkit, identity, lib, capsys):
    for step in ("load", "reconcile"):
        assert tpj(["migrate", step, sqlkit["kit"], *(["--confirm-destinations"] if step == "load" else []),
                    *sqlkit["sets"]], capsys)[0] == 0
    code, ans = tpt(["migrate", "certify", sqlkit["kit"], "--identity", identity], capsys, lib.transport)
    assert code == 0 and ans["library"].startswith("not counted: a local kit"), ans
