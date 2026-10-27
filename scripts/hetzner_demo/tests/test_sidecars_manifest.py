"""§ONESHOT P2.2 (2026-09-12) — the sidecar manifest: sentences for what is missing, slots that come out clean.

`--wire-prod` used to be seven bare writes that raised Python paths on a host without the file; now
`sidecars.require()` answers with a sentence per missing piece and `unwire()` removes exactly the frame's
own slot from each artifact (a shared line, another frame's job, another net's bundle: never). Pinned on
fixture files, never on this host's live ones.
"""
import importlib.util
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER_DIR = os.path.dirname(HERE)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(DRIVER_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


sc = _load("sidecars")


def test_require_names_every_missing_piece_as_a_sentence(tmp_path):
    m = {"auditor": {"env": str(tmp_path / "nope.env"), "compose": str(tmp_path / "nope.yml")},
         "prometheus": {"mode": "static-yml", "config": str(tmp_path / "nope-prom.yml")},
         "bundles": {"refresh": str(tmp_path / "nope.sh"), "cron_marker": "zz-no-such-marker-zz"},
         "sni": {"script": str(tmp_path / "nope-sni.sh"), "conf": str(tmp_path / "nope.conf")}}
    p = sc.require(m)
    assert len(p) >= 6 and all(isinstance(x, str) and len(x) > 40 for x in p)
    assert any("auditor" in x for x in p) and any("Prometheus" in x for x in p) and any("refresh" in x for x in p)
    assert any("crontab" in x for x in p) and any("SNI" in x for x in p)
    # file_sd mode asks for the targets dir instead of the config
    m["prometheus"] = {"mode": "file_sd", "targets_dir": str(tmp_path / "targets")}
    assert any("file_sd" in x for x in sc.require(m))
    os.makedirs(tmp_path / "targets")
    assert not any("file_sd" in x for x in sc.require(m))


def test_manifest_load_refuses_with_a_sentence_when_absent(tmp_path):
    try:
        sc.load(str(tmp_path / "missing.json"))
    except SystemExit as e:
        assert "sidecars.json.example" in str(e)
    else:
        raise AssertionError("a missing manifest must refuse")


def test_federated_bundle_is_one_file_per_identity_net():
    m = {"bundles": {"federated_by_net": {"fresh-identity": {"list": "/l/fresh", "pem": "/p/fresh.pem"}}}}
    assert sc.federated_bundle_for_net(m, "fresh-identity") == ("/l/fresh", "/p/fresh.pem")
    lst, pem = sc.federated_bundle_for_net(m, "oneshot-identity")
    assert lst == "/etc/theprotocol/oneshot-identity-federated-bundle.list" and pem == "/etc/nginx/oneshot-identity-federated-spire-bundle.pem"
    assert sc.federated_bundle_for_net(m, "fresh-identity") != sc.federated_bundle_for_net(m, "oneshot-identity")


PROM = """global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'eu-registry'
    scrape_interval: 15s
    metrics_path: '/metrics'
    static_configs:
      - targets: ['eu-registry:8000']
        labels: { component: 'registry', frame: 'eu', env: 'prod' }
  - job_name: 'juice-registry'
    scrape_interval: 15s
    static_configs:
      - targets: ['juice-registry:8000']
  - job_name: 'juice-teg'
    static_configs:
      - targets: ['juice-teg:8080']
  - job_name: 'asia-registry'
    static_configs:
      - targets: ['asia-registry:8000']
"""


def test_prometheus_unwire_removes_only_the_frames_jobs(tmp_path):
    p = tmp_path / "prometheus.yml"; p.write_text(PROM)
    n = sc._prom_remove_jobs(str(p), ["juice-registry", "juice-teg", "juice-event-store"])
    out = p.read_text()
    assert n == 2 and "juice" not in out and "job_name: 'eu-registry'" in out and "job_name: 'asia-registry'" in out
    assert "eu-registry:8000" in out and "asia-registry:8000" in out
    assert sc._prom_remove_jobs(str(p), ["juice-registry"]) == 0


def test_apex_ws_block_and_fresh_network_tile_come_out_whole(tmp_path, monkeypatch):
    enabled = tmp_path / "enabled"; enabled.mkdir()
    v = enabled / "theprotocol-apex"
    v.write_text("server {\n    location /ws/events-juice {\n        proxy_pass http://127.0.0.1:8761/ws/events;\n        proxy_http_version 1.1;\n    }\n"
                 "    location /ws/events-eu {\n        proxy_pass http://127.0.0.1:8461/ws/events;\n    }\n}\n")
    monkeypatch.setattr(sc.extras, "NGINX_ENABLED", str(enabled))
    monkeypatch.setattr(sc.extras, "_bak", lambda *a, **k: None)
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    assert sc._apex_remove_ws({"apex": {"vhosts": ["theprotocol-apex"]}}, "juice") == 1
    s = v.read_text(); assert "events-juice" not in s and "events-eu" in s and s.count("{") == s.count("}")
    comp = tmp_path / "docker-compose.production.yml"
    comp.write_text("    environment:\n      FRESH_NETWORK_JSON: '[{\"slug\":\"eu\"},{\"slug\":\"juice\"}]'\n")
    assert sc._fresh_network_remove({"apex": {"prod_compose": str(comp)}}, "juice") is True
    assert json.loads(re.search(r"FRESH_NETWORK_JSON: '(.*)'", comp.read_text()).group(1)) == [{"slug": "eu"}]
    assert sc._fresh_network_remove({"apex": {"prod_compose": str(comp)}}, "juice") is False


def test_auditor_unwire_drops_the_slot_and_the_external_network_only(tmp_path, monkeypatch):
    env = tmp_path / ".env"; env.write_text('X=1\nAUDITOR_EXTRA_FRAMES_JSON=[{"id":"eu"},{"id":"juice","dsn":"postgresql://u:p@h/db"}]\n')
    comp = tmp_path / "docker-compose.yml"
    comp.write_text("services:\n  auditor-agent:\n    networks:\n      - agentvault_main_network\n      - eu_network\n      - juice_network\n"
                    "networks:\n  agentvault_main_network:\n    external: true\n  eu_network:\n    external: true\n  juice_network:\n    external: true\n")
    monkeypatch.setattr(sc.extras, "_bak", lambda *a, **k: None)
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(sc.extras, "auditor_reload", lambda *a, **k: (404, "older auditor"))   # the pre-P3.1 path: env + recreate
    m = {"auditor": {"env": str(env), "compose": str(comp), "service": "auditor-agent"}}
    assert sc._auditor_remove_slot(m, "juice", "juice_network") == (True, True)
    assert json.loads(env.read_text().split("AUDITOR_EXTRA_FRAMES_JSON=")[1]) == [{"id": "eu"}]
    t = comp.read_text(); assert "juice_network" not in t and "eu_network" in t and t.count("external: true") == 2
    assert sc._auditor_remove_slot(m, "juice", "juice_network") == (False, False)


# ── §FRAMEKIT P3.1 (2026-09-12) — joins with aliases, file_sd job labels, reconcile, the two env lines ──

def test_join_plan_redoes_a_join_that_lacks_the_alias_the_code_default_resolves():
    # the flagship case: Prometheus was ON eu_network, but without the `prometheus` alias the registry's
    # default (http://prometheus:9090) was a gaierror — measured: 0 of 90 days on every status component
    cur = {"eu_network": [], "agentvault_main_network": ["agentvault-prometheus", "prometheus"]}
    assert sc.join_plan(cur, "eu_network", ["prometheus"]) == "reconnect"
    assert sc.join_plan(cur, "agentvault_main_network", ["prometheus"]) == "ok"
    assert sc.join_plan(cur, "asia_network", ["prometheus"]) == "connect"
    assert sc.join_plan(cur, "eu_network", []) == "ok"          # an operator net needs no alias


def test_file_sd_targets_carry_the_status_pages_job_names():
    t = sc.file_sd_targets({"name": "juice", "env_label": "sandbox", "operators": ["juiceop-a"]})
    jobs = [x["labels"]["job"] for x in t]
    assert jobs == ["juice-registry", "juice-teg", "juice-event-store", "juiceop-a-registry", "juiceop-a-teg"]
    assert t[0]["targets"] == ["juice-registry:8000"] and t[2]["targets"] == ["juice-event-store:8200"]
    assert t[3]["targets"] == ["cloud-op-juiceop-a-registry:8000"] and t[3]["labels"]["parent"] == "juice"
    assert t[3]["labels"]["frame"] == "juiceop-a" and "parent" not in t[0]["labels"]
    assert all(x["labels"]["env"] == "sandbox" for x in t)
    # the same names the static-yml writer has always produced (public_status.py keys history on them)
    assert sc.networks_for_targets(t) == ["juice_network", "cloud-op-juiceop-a_operator-net"]


def test_static_yml_frame_jobs_read_as_targets_for_reconcile():
    t = sc.static_yml_frame_targets(PROM)
    assert [x["labels"]["job"] for x in t] == ["eu-registry"]          # only jobs carrying a frame label
    assert sc.networks_for_targets(t) == ["eu_network"]
    ops = "  - job_name: 'amsterdam-registry'\n    static_configs:\n      - targets: ['cloud-op-amsterdam-registry:8000']\n" \
          "        labels: { component: 'registry', frame: 'amsterdam', env: 'prod' }\n"
    t2 = sc.static_yml_frame_targets(PROM + ops)
    assert sc.networks_for_targets(t2) == ["eu_network", "cloud-op-amsterdam_operator-net"]


def test_wired_targets_merge_both_modes(tmp_path):
    d = tmp_path / "targets"; d.mkdir()
    (d / "juice.json").write_text(json.dumps(sc.file_sd_targets({"name": "juice", "env_label": "sandbox", "operators": []})))
    (d / "broken.json").write_text("{not json")
    cfg = tmp_path / "prometheus.yml"; cfg.write_text(PROM)
    m = {"prometheus": {"mode": "file_sd", "targets_dir": str(d), "config": str(cfg)}}
    nets = sc.networks_for_targets(sc.wired_targets(m))
    assert nets == ["juice_network", "eu_network"]


def test_metrics_env_lines_come_from_the_manifest_never_a_default():
    assert sc.metrics_env_lines({}) == []
    assert sc.metrics_env_lines({"prometheus": {"query_url": ""}}) == []
    only_prom = sc.metrics_env_lines({"prometheus": {"query_url": "http://tp-sidecars-prometheus:9090/"}})
    assert only_prom == [("PROMETHEUS_URL", "http://tp-sidecars-prometheus:9090"), ("VICTORIA_METRICS_URL", "http://tp-sidecars-prometheus:9090")]
    both = sc.metrics_env_lines({"prometheus": {"query_url": "http://agentvault-prometheus:9090"},
                                 "metrics_store": {"url": "http://victoriametrics:8428"}})
    assert dict(both) == {"PROMETHEUS_URL": "http://agentvault-prometheus:9090", "VICTORIA_METRICS_URL": "http://victoriametrics:8428"}


def test_auditor_frame_networks_from_the_frames_file_or_the_env(tmp_path):
    ff = tmp_path / "frames.json"
    ff.write_text(json.dumps([{"id": "juice", "url": "http://juice-event-store:8200"}, {"id": "x", "url": "http://not-a-frame:9"}]))
    assert sc.auditor_frame_networks({"auditor": {"frames_file": str(ff)}}) == ["juice_network"]
    env = tmp_path / ".env"; env.write_text('AUDITOR_EXTRA_FRAMES_JSON=[{"id":"eu","url":"http://eu-event-store:8200"}]\n')
    assert sc.auditor_frame_networks({"auditor": {"env": str(env)}}) == ["eu_network"]
    assert sc.auditor_frame_networks({"auditor": {"frames_file": str(tmp_path / "missing.json")}}) == []


def test_require_asks_for_a_query_url_and_the_mounted_targets_dir(tmp_path, monkeypatch):
    d = tmp_path / "targets"; d.mkdir()
    monkeypatch.setattr(sc, "_running", lambda c: True)
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        rc = 1 if cmd[:2] == ["docker", "exec"] else 0     # the container does NOT mount the dir
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    m = {"auditor": {"env": str(tmp_path / "e"), "compose": str(tmp_path / "c")},
         "prometheus": {"mode": "file_sd", "targets_dir": str(d), "container": "prom"},
         "bundles": {"refresh": str(tmp_path / "r.sh"), "cron_marker": "zz"}, "sni": {"script": str(tmp_path / "s.sh")}}
    p = sc.require(m)
    assert any("cannot read the targets dir" in x for x in p)
    assert any("query_url" in x for x in p)
    m["prometheus"]["query_url"] = "http://prom:9090"
    assert not any("query_url" in x for x in sc.require(m))


def test_wire_only_prometheus_touches_nothing_else(tmp_path, monkeypatch):
    d = tmp_path / "targets"; d.mkdir()
    joined = []
    monkeypatch.setattr(sc, "ensure_on_network", lambda c, n, a, **k: joined.append((c, n, tuple(a))) or "connect")
    monkeypatch.setattr(sc, "_prom_reload", lambda m: 0)
    monkeypatch.setattr(sc.extras, "auditor_slot", lambda *a, **k: (_ for _ in ()).throw(AssertionError("auditor touched")))
    monkeypatch.setattr(sc.extras, "sni_route", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sni touched")))
    m = {"prometheus": {"mode": "file_sd", "targets_dir": str(d), "container": "prom", "aliases": ["prometheus"]},
         "metrics_store": {"container": "vm", "aliases": ["victoriametrics"]}, "auditor": {"compose": str(tmp_path / "c.yml")}}
    f = {"name": "juice", "env_label": "sandbox", "operators": ["juiceop-a"], "fed_port": 1, "frame_label": "J", "ticker": "JUC"}
    done = sc.wire(m, f, only={"prometheus"}, log=lambda *_: None)
    t = json.load(open(d / "juice.json"))
    assert [x["labels"]["job"] for x in t] == ["juice-registry", "juice-teg", "juice-event-store", "juiceop-a-registry", "juiceop-a-teg"]
    assert ("prom", "juice_network", ("prometheus",)) in joined and ("prom", "cloud-op-juiceop-a_operator-net", ("prometheus",)) in joined
    assert ("vm", "juice_network", ("victoriametrics",)) in joined and not any(c == "vm" and "operator-net" in n for c, n, _ in joined)
    assert "auditor_slot" not in done and "sni" not in done and done["prometheus_targets"].endswith("juice.json")


def test_frame_network_name_follows_the_provisioner_rule():
    # services/frame_test_provisioner.py:355 — hyphens become underscores; the P2 proof pair had none
    assert sc.frame_net_name("sbx-alpha") == "sbx_alpha_network" and sc.frame_net_name("eu") == "eu_network"
    own, ops = sc.frame_networks({"name": "sbx-alpha", "operators": ["sbxalphaop"]})
    assert own == "sbx_alpha_network" and ops == ["cloud-op-sbxalphaop_operator-net"]
    t = sc.file_sd_targets({"name": "sbx-alpha", "env_label": "sandbox", "operators": []})
    assert sc.networks_for_targets(t) == ["sbx_alpha_network"]
    ff_nets = sc.auditor_frame_networks({"auditor": {"env": "/nonexistent"}})
    assert ff_nets == []


def test_prepare_targets_dir_makes_the_files_readable_by_nobody(tmp_path):
    d = tmp_path / "targets"; d.mkdir(mode=0o750)
    (d / "x.json").write_text("[]"); os.chmod(d / "x.json", 0o640)
    m = {"prometheus": {"mode": "file_sd", "targets_dir": str(d)}}
    assert sc.prepare_targets_dir(m) == str(d)
    assert oct(os.stat(d).st_mode & 0o777) == "0o755" and oct(os.stat(d / "x.json").st_mode & 0o777) == "0o644"
    assert sc.prepare_targets_dir({"prometheus": {"mode": "static-yml"}}) is None


def test_auditor_unwire_prefers_the_frames_file_and_reloads_instead_of_recreating(tmp_path, monkeypatch):
    # §FRAMEKIT P3.1: the slot leaves the FILE, the auditor is asked to reload, and a 200 means NO recreate
    fd = tmp_path / "frames"; fd.mkdir()
    ff = fd / "frames.json"; ff.write_text(json.dumps([{"id": "eu", "url": "http://eu-event-store:8200"}, {"id": "juice", "url": "http://juice-event-store:8200", "dsn": "postgresql://u:p@h/db"}]))
    env = tmp_path / ".env"; env.write_text("AUDITOR_ADMIN_TOKEN=t\n")
    comp = tmp_path / "docker-compose.yml"
    comp.write_text("services:\n  auditor-agent:\n    networks:\n      - eu_network\n      - juice_network\n"
                    "networks:\n  eu_network:\n    external: true\n  juice_network:\n    external: true\n")
    calls = []
    monkeypatch.setattr(sc.extras, "_bak", lambda *a, **k: None)
    monkeypatch.setattr(sc.subprocess, "run", lambda cmd, **k: calls.append(cmd) or type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    reloads = []
    monkeypatch.setattr(sc.extras, "auditor_reload", lambda url, tok, **k: reloads.append((url, tok)) or (200, '{"removed":["juice"]}'))
    m = {"auditor": {"env": str(env), "compose": str(comp), "service": "auditor-agent", "container": "auditor-agent",
                     "frames_file": str(ff), "admin_url": "http://127.0.0.1:8045"}}
    assert sc._auditor_remove_slot(m, "juice", "juice_network") == (True, True)
    assert [f["id"] for f in json.loads(ff.read_text())] == ["eu"] and oct(os.stat(ff).st_mode & 0o777) == "0o600"
    assert reloads == [("http://127.0.0.1:8045", "t")]
    assert not any("up" in c and "--force-recreate" in c for c in calls), "a 200 reload must not recreate"
    assert any(c[:3] == ["docker", "network", "disconnect"] for c in calls)
    # the same slot again: nothing to remove, nothing reloaded, nothing recreated
    calls.clear(); reloads.clear()
    assert sc._auditor_remove_slot(m, "juice", "juice_network") == (False, False) and not reloads and not calls


def test_auditor_slot_writes_the_file_and_reloads(tmp_path, monkeypatch):
    ad = tmp_path / "auditor"; (ad / "frames").mkdir(parents=True)
    (ad / ".env").write_text("AUDITOR_ADMIN_TOKEN=tok\nAUDITOR_EXTRA_FRAMES_JSON=[]\n")
    (ad / "docker-compose.yml").write_text("services:\n  auditor-agent:\n    environment:\n      SBX_EVENT_STORE_KEY: k\n      AUDITOR_EXTRA_FRAMES_JSON: x\n"
                                           "    networks:\n      - agentvault_main_network\nnetworks:\n  agentvault_main_network:\n    external: true\n")
    ex = sc.extras
    monkeypatch.setattr(ex, "AUDITOR_DIR", str(ad)); monkeypatch.setattr(ex, "_bak", lambda *a, **k: None)
    envs = {"juice-event-store": "DATABASE_URL=postgresql+asyncpg://u:p@juice-es-db:5432/db\nINTERNAL_API_KEY=key\n",
            "juice-teg-db": "POSTGRES_USER=teg\nPOSTGRES_PASSWORD=p+w\nPOSTGRES_DB=frame_test_teg\n",
            "juice-db": "POSTGRES_USER=registry\nPOSTGRES_PASSWORD=p\nPOSTGRES_DB=frame_test_registry\n"}
    calls = []
    def fake_run(cmd, **k):
        calls.append(cmd)
        out = ""
        if cmd[:2] == ["docker", "inspect"]:
            out = envs.get(cmd[2], "")
        if cmd[:2] == ["docker", "exec"]:
            out = "did:theprotocol:router\n"
        return type("R", (), {"returncode": 0, "stdout": out, "stderr": ""})()
    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    reloads = []
    monkeypatch.setattr(ex, "auditor_reload", lambda url, tok, **k: reloads.append((url, tok)) or (200, "{}"))
    ex.auditor_slot("juice", "Juice", "JUC", "juice-event-store", "juice-es-db", mode="sandbox", frames_file=str(ad / "frames" / "frames.json"))
    fr = json.loads((ad / "frames" / "frames.json").read_text())
    assert [f["id"] for f in fr] == ["juice"] and fr[0]["teg_dsn"].startswith("postgresql://teg:p%2Bw@juice-teg-db:5432/") and fr[0]["mode"] == "sandbox"
    assert oct(os.stat(ad / "frames" / "frames.json").st_mode & 0o777) == "0o600"
    assert reloads == [("http://127.0.0.1:8045", "tok")]
    assert "AUDITOR_EXTRA_FRAMES_JSON=[]" in (ad / ".env").read_text(), "a reloaded auditor needs no env carrier"
    assert not any("--force-recreate" in c for c in calls) and any(c[:3] == ["docker", "network", "connect"] for c in calls)
    # §MTLSHOPS (a) (2026-09-15, agentvault2-85's find): the tracked compose is never edited; the untracked override keeps
    # the join across a recreate
    assert "juice_network" not in (ad / "docker-compose.yml").read_text()
    assert "      - juice_network\n" in (ad / "docker-compose.override.yml").read_text()
