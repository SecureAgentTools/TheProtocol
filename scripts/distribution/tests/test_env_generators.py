"""The kit's two env generators, run for real in a scratch directory (bash and openssl, nothing else).

CB-006: two scripts share the name generate-operator-env.sh. The standalone one (scripts/distribution) printed the
environment on stdout for the caller to redirect; the one an operator bundle carries (nginx-templates) writes its files
itself and printed progress on stdout, so the documented redirect wrote that progress over the head of the file it had
just written. One contract now: the files land in the current directory at 0600, progress goes to stderr, stdout stays
empty, and a redirect into .env.operator leaves the same file.
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
STANDALONE = HERE / "generate-operator-env.sh"
BUNDLE = HERE / "nginx-templates" / "generate-operator-env.sh"
GENERATORS = {"standalone": STANDALONE, "bundle": BUNDLE}


def run_generator(which, cwd, name="my-registry", redirect=False):
    """Run a generator in cwd; with redirect, as `gen name > .env.operator` (the older documented form)."""
    script = GENERATORS[which]
    if redirect:
        r = subprocess.run(["bash", "-c", f'bash "{script}" "{name}" > .env.operator'], cwd=cwd,
                           capture_output=True, text=True, timeout=60)
    else:
        r = subprocess.run(["bash", str(script), name], cwd=cwd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r


def env_of(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


@pytest.mark.parametrize("which", sorted(GENERATORS))
def test_the_file_lands_in_the_current_directory_and_stdout_stays_empty(tmp_path, which):
    r = run_generator(which, tmp_path)
    env = tmp_path / ".env.operator"
    assert r.stdout == "" and "Created .env.operator" in r.stderr
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert len(env_of(env)) >= 20 and "PG_PASS_REGISTRY" in env_of(env)


@pytest.mark.parametrize("which", sorted(GENERATORS))
def test_the_older_redirect_form_leaves_the_same_file(tmp_path, which):
    run_generator(which, tmp_path, redirect=True)
    text = (tmp_path / ".env.operator").read_text()
    assert "[generate]" not in text and text.startswith("# .env.operator")
    assert len(env_of(tmp_path / ".env.operator")) >= 20


def test_the_standalone_env_passes_the_registrys_production_checks_once_base_url_is_set(tmp_path):
    """CB-015 / CB-318: a BASE_URL that is not localhost turns on validate_production_config, which refuses CORS open to
    every origin and, on a standalone registry (its own frame, IS_CENTRAL_REGISTRY), a missing federation health-check
    secret. The generator wrote neither, so following the README made the registry refuse to start. ALLOWED_ORIGINS
    must be a JSON list (a bare URL or a comma list fails to parse at import)."""
    run_generator("standalone", tmp_path)
    env = env_of(tmp_path / ".env.operator")
    origins = json.loads(env["ALLOWED_ORIGINS"])
    assert isinstance(origins, list) and origins and "*" not in origins
    assert all(isinstance(o, str) and o.startswith(("http://", "https://")) for o in origins)
    assert len(env["FEDERATION_HEALTH_CHECK_SECRET"]) >= 32


# CB-320: settings no service reads leave the generators, the composes and the tester env. The transfer fee is the
# registry's enforcement policy (DEFAULT_FEE_RATE / MAX_FEE_RATE reached the TEG and changed nothing), and the registry
# reads the RATE_LIMIT_* roles into a table nothing consults (slowapi limits per route).
UNREAD = ("DEFAULT_FEE_RATE", "MAX_FEE_RATE", "RATE_LIMIT_DEVELOPER", "RATE_LIMIT_AGENT", "RATE_LIMIT_PUBLIC",
          "RATE_LIMIT_ADMIN")


@pytest.mark.parametrize("which", sorted(GENERATORS))
def test_no_generator_writes_a_setting_no_service_reads(tmp_path, which):
    run_generator(which, tmp_path)
    assert not set(UNREAD) & set(env_of(tmp_path / ".env.operator"))


def test_no_kit_compose_or_tester_env_passes_them():
    for rel in ("docker-compose.standalone.yml", "nginx-templates/docker-compose.operator.yml"):
        text = (HERE / rel).read_text()
        assert not [n for n in UNREAD if n in text], rel
    extras = HERE.parents[1] / "scripts" / "hetzner_demo" / "standup_extras.py"
    if extras.exists():
        code = "\n".join(ln for ln in extras.read_text().splitlines() if not ln.lstrip().startswith("#"))
        assert not [n for n in UNREAD if f'"{n}"' in code]


# CB-111: the bundle an operator downloads boots on its own host. Its compose interpolates the proxy trust secrets and
# the Redis passwords with no default and starts Redis with --aclfile ./redis-users.acl, and its terminators send a
# marker only once it is rendered; the bundle's generator wrote none of these (only a frame's provisioner did, for a
# cloud operator it hosts, with services/operator_provisioner.apply_operator_secrets). It now writes them for any name
# but cloud-op-*, in the provisioner's shapes; a cloud operator's frame still renders its own.
TEMPLATES = HERE / "nginx-templates"
SECRETS = ("REGISTRY_PROXY_TRUST_SECRET", "TEG_PROXY_TRUST_SECRET", "REDIS_PASSWORD_REGISTRY", "REDIS_PASSWORD_TEG")
APP_RULES = ("~* &* +@all -flushall -flushdb -config -debug -shutdown -acl -monitor -replicaof -slaveof -module -save "
             "-bgsave -bgrewriteaof -failover -cluster -migrate -restore -sync -psync -swapdb")


def _bundle_dir(tmp_path):
    """The layout a frame's bundle extracts to: the compose and the generator at the top, the confs under nginx/."""
    d = tmp_path / "bundle"
    (d / "nginx").mkdir(parents=True)
    for f in ("docker-compose.operator.yml", "pgbouncer.ini"):
        (d / f).write_bytes((TEMPLATES / f).read_bytes())
    for f in ("nginx-federation.conf", "nginx-teg.conf"):
        (d / "nginx" / f).write_bytes((TEMPLATES / f).read_bytes())
    return d


def _live(text, header, value):
    import re
    return re.findall(rf'^[ \t]*proxy_set_header[ \t]+{re.escape(header)}[ \t]+"{re.escape(value)}"[ \t]*;', text, re.M)


def test_a_bundle_run_on_its_own_host_gets_everything_its_compose_needs(tmp_path):
    import hashlib
    import re
    d = _bundle_dir(tmp_path)
    run_generator("bundle", d, name="op-lisbon-self")
    env = env_of(d / ".env.operator")
    compose = re.sub(r"(?m)^\s*#.*$", "", (d / "docker-compose.operator.yml").read_text())
    needed = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", compose))
    assert set(SECRETS) <= needed and not sorted(needed - set(env)), sorted(needed - set(env))
    for k in SECRETS:
        assert re.fullmatch(r"[0-9a-f]{64}", env[k]), k
    acl = (d / "redis-users.acl").read_text().splitlines()
    assert acl == ["user default on nopass resetkeys resetchannels -@all +ping",
                   f"user registry on #{hashlib.sha256(env['REDIS_PASSWORD_REGISTRY'].encode()).hexdigest()} {APP_RULES}",
                   f"user teg on #{hashlib.sha256(env['REDIS_PASSWORD_TEG'].encode()).hexdigest()} {APP_RULES}"]
    if os.geteuid() == 0:
        st = (d / "redis-users.acl").stat()
        assert (st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)) == (999, 1000, 0o600)
    fed = (d / "nginx" / "nginx-federation.conf").read_text()
    teg = (d / "nginx" / "nginx-teg.conf").read_text()
    for text in (fed, teg):
        assert "#OPDIST-MARKER#" not in text and "_TRUST_SECRET__" not in text
    template_fed = (TEMPLATES / "nginx-federation.conf").read_text()
    template_teg = (TEMPLATES / "nginx-teg.conf").read_text()
    assert len(_live(fed, "X-Registry-Proxy-Auth", env["REGISTRY_PROXY_TRUST_SECRET"])) \
        == template_fed.count("X-Registry-Proxy-Auth") > 0
    assert len(_live(fed, "X-TEG-Proxy-Auth", env["TEG_PROXY_TRUST_SECRET"])) == template_fed.count("X-TEG-Proxy-Auth") > 0
    assert len(_live(teg, "X-TEG-Proxy-Auth", env["TEG_PROXY_TRUST_SECRET"])) == template_teg.count("X-TEG-Proxy-Auth") > 0


def test_a_second_run_renders_the_markers_again_with_its_own_values(tmp_path):
    d = _bundle_dir(tmp_path)
    run_generator("bundle", d, name="op-lisbon-self")
    run_generator("bundle", d, name="op-lisbon-self")
    env = env_of(d / ".env.operator")
    fed = (d / "nginx" / "nginx-federation.conf").read_text()
    assert len(_live(fed, "X-Registry-Proxy-Auth", env["REGISTRY_PROXY_TRUST_SECRET"])) \
        == (TEMPLATES / "nginx-federation.conf").read_text().count("X-Registry-Proxy-Auth")


def test_a_cloud_operator_leaves_its_secrets_to_its_frame(tmp_path):
    """The frame's renderer runs after this script and refuses a conf whose marker another value already took, and
    appends its own four values to .env.operator: the generator touches none of it for a cloud-op-* name."""
    d = _bundle_dir(tmp_path)
    r = run_generator("bundle", d, name="cloud-op-lisbon")
    env = env_of(d / ".env.operator")
    assert not set(SECRETS) & set(env) and not (d / "redis-users.acl").exists()
    for f in ("nginx-federation.conf", "nginx-teg.conf"):
        assert (d / "nginx" / f).read_bytes() == (TEMPLATES / f).read_bytes()
    assert "its frame writes" in r.stderr


@pytest.mark.parametrize("name", ["op-lisbon-self", "cloud-op-lisbon"])
def test_an_operator_is_born_reading_the_release_channel(tmp_path, name):
    """CB-343: only the provisioner's fallback env said RELEASE_CHANNEL_CHECK_ENABLED=true; an operator whose env came
    from this generator (the normal path, and the runner's) never checked the channel."""
    run_generator("bundle", _bundle_dir(tmp_path), name=name)
    assert env_of(tmp_path / "bundle" / ".env.operator")["RELEASE_CHANNEL_CHECK_ENABLED"] == "true"
