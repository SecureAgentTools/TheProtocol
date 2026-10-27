"""§OPDIST — a cloud operator is BORN with its markers and its Redis ACL, or it is not provisioned at all.

Until 2026-09-16 a freshly provisioned operator came up with an open Redis (no ACL file, every client connecting as
`default`) and two terminators that forwarded certificate headers with no marker, so the apps behind them either
trusted a header anyone on that network could write, or (on a marker-carrying image) refused every mTLS call. The six
running operators were brought to the posture by hand; this is the half that makes the NEXT one born right.

The rendering is one function, `operator_provisioner.apply_operator_secrets`, called by `cloud_provisioner` after its
Step 5 with the same dict Step 2 wrote into `.env.operator`.

⚠ THE POINT OF THE REFUSAL: the terminator templates ship the marker as a PLACEHOLDER because the secret is per
operator. A conf shipped with the placeholder still in it sends a marker the app cannot match, so every mTLS call
through that terminator is refused. It happens to fail in the safe direction today only because the placeholder is 26
characters against the app's 32-character minimum, which is arithmetic rather than design. The refusal is the guard.

Control: each green case has a red twin here (a surviving placeholder raises; a missing conf raises), and the wiring is
checked structurally so that moving the secret generation inside a conditional is caught rather than discovered at
provision time as a NameError.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import pathlib
import re

import pytest

_HERE = pathlib.Path(__file__).resolve()
# OPDIST_SRC points the whole file at another services/ directory, which is how the red control is run: against the
# pre-fix tree, every case here must fail rather than pass quietly.
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry" / "services")


def _path(name: str) -> pathlib.Path:
    """The file, whichever base OPDIST_SRC names.

    ⚠ ONE VARIABLE, TWO MEANINGS: this file reads OPDIST_SRC as the services/ directory and the two sibling
    OPDIST suites read it as the package root, so a run that sets it once for all three silently missed a test
    here (measured 2026-09-16, in the image). Every path in this file goes through here rather than joining _SRC
    directly, so both meanings resolve and a control run cannot be quietly partial.
    """
    rel = name if name.endswith(".py") else f"{name}.py"
    return (_SRC / rel) if (_SRC / rel).exists() else (_SRC / "services" / rel)


def _load(name: str):
    """Load one module by path. `services/x` and `x` both work, so a test can name the file it means."""
    path = _path(name)
    spec = importlib.util.spec_from_file_location(f"_opdist_{name.replace('/', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def opprov():
    return _load("operator_provisioner")


def _bundle(tmp_path, teg_extra: str = "", fed_extra: str = ""):
    nginx = tmp_path / "nginx"
    nginx.mkdir()
    # The shape the templates ship: the marker line is COMMENTED, so a registry still on an older image copies a conf
    # that behaves exactly as today's does. Uncommenting is the first half of what apply_operator_secrets does.
    (nginx / "nginx-teg.conf").write_text(
        'location /api/v1/ {\n  #OPDIST-MARKER# proxy_set_header X-TEG-Proxy-Auth "__TEG_PROXY_TRUST_SECRET__";\n}\n' + teg_extra)
    (nginx / "nginx-federation.conf").write_text(
        'location /api/v1/federation/ {\n  #OPDIST-MARKER# proxy_set_header X-Registry-Proxy-Auth "__REGISTRY_PROXY_TRUST_SECRET__";\n}\n'
        'location /api/v1/cross-teg/ {\n  #OPDIST-MARKER# proxy_set_header X-TEG-Proxy-Auth "__TEG_PROXY_TRUST_SECRET__";\n}\n' + fed_extra)
    return tmp_path


def test_every_minted_secret_is_distinct_and_long_enough_to_be_usable(opprov):
    """The count is DERIVED, not typed: §OPDIST added a fifth (AUDITOR_RO_PASSWORD) and a literal 4 made this fail
    for the arithmetic rather than for the property it is about — a repeated value would make two identities one."""
    v = opprov.generate_operator_secrets()
    assert sorted(v) == sorted(opprov.OPERATOR_SECRET_NAMES)
    assert len(set(v.values())) == len(opprov.OPERATOR_SECRET_NAMES), "a repeated value would make two identities one"
    for name, value in v.items():
        assert re.fullmatch(r"[0-9a-f]{64}", value), name
        # The app turns the header path OFF below 32 characters, which refuses rather than trusting: a short marker is
        # not a weak marker, it is no marker, and this is the length that keeps the path ON.
        assert len(value) >= 32


def test_every_placeholder_is_rendered_and_the_acl_is_written(opprov, tmp_path):
    d = _bundle(tmp_path)
    v = opprov.generate_operator_secrets()
    opprov.apply_operator_secrets(str(d), v, "fixture")

    teg = (d / "nginx" / "nginx-teg.conf").read_text()
    fed = (d / "nginx" / "nginx-federation.conf").read_text()
    assert v["TEG_PROXY_TRUST_SECRET"] in teg and "__" not in teg
    # the federation terminator proxies BOTH the registry and this operator's own TEG, so it carries both markers
    assert v["REGISTRY_PROXY_TRUST_SECRET"] in fed and v["TEG_PROXY_TRUST_SECRET"] in fed and "__" not in fed
    for conf in ("nginx-teg.conf", "nginx-federation.conf"):
        assert oct(os.stat(d / "nginx" / conf).st_mode & 0o777) == "0o600", conf

    acl = (d / "redis-users.acl").read_text().splitlines()
    assert acl[0].startswith("user default ") and "+ping" in acl[0] and "-@all" in acl[0]
    assert [l.split()[1] for l in acl[1:]] == ["registry", "teg"]
    assert not any(value in "\n".join(acl) for value in v.values()), "the ACL file carries hashes, never passwords"
    assert oct(os.stat(d / "redis-users.acl").st_mode & 0o777) == "0o600"


def test_control_a_surviving_placeholder_refuses_to_provision(opprov, tmp_path):
    # A second placeholder the substitution does not know about: the conf would ship a marker the app cannot match.
    d = _bundle(tmp_path, teg_extra='proxy_set_header X-Other "__REGISTRY_PROXY_TRUST_SECRET__";\n')
    (d / "nginx" / "nginx-teg.conf").write_text(
        (d / "nginx" / "nginx-teg.conf").read_text().replace("__REGISTRY_PROXY_TRUST_SECRET__", "__UNRENDERED__"))
    v = opprov.generate_operator_secrets()
    # the known placeholders still render; the unknown one is what must be caught, so assert on the message
    (d / "nginx" / "nginx-teg.conf").write_text(
        'proxy_set_header X-TEG-Proxy-Auth "__TEG_PROXY_TRUST_SECRET__";\n'
        'proxy_set_header X-Registry-Proxy-Auth "__REGISTRY_PROXY_TRUST_SECRET__";\n')
    with pytest.raises(RuntimeError) as e:
        opprov.apply_operator_secrets(str(d), v, "fixture")
    assert "__REGISTRY_PROXY_TRUST_SECRET__" in str(e.value) and "nginx-teg.conf" in str(e.value)


def test_control_a_missing_terminator_conf_refuses_to_provision(opprov, tmp_path):
    d = _bundle(tmp_path)
    (d / "nginx" / "nginx-teg.conf").unlink()
    with pytest.raises(RuntimeError) as e:
        opprov.apply_operator_secrets(str(d), opprov.generate_operator_secrets(), "fixture")
    assert "nginx-teg.conf" in str(e.value)


def test_the_wiring_generates_before_it_writes_and_renders_after_step_five():
    """Structural, so a refactor that moves the generation into a conditional is caught here and not at provision time.

    The name must be bound in the function BODY (not inside an `if`/`with`), and the render call must come after it.
    """
    src = _path("cloud_provisioner.py").read_text()
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and any("op_secrets" == getattr(t, "id", None)
                 for s in ast.walk(n) for t in getattr(s, "targets", []))),
        None)
    assert fn is not None, "nothing binds op_secrets any more"
    top_level = [s for s in fn.body if isinstance(s, ast.Assign)
                 and any(getattr(t, "id", None) == "op_secrets" for t in s.targets)]
    assert len(top_level) == 1, "op_secrets must be bound once, in the function body, not inside a block"
    binding_line = top_level[0].lineno
    calls = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "apply_operator_secrets"]
    assert calls, "nothing renders the operator's markers any more"
    assert min(calls) > binding_line, "the render must come after the secrets exist"

def test_control_an_old_conf_with_new_code_refuses_rather_than_provisioning_a_deaf_operator(opprov, tmp_path):
    """The other ordering, which fails silently and is the one the bind mount makes possible.

    These confs are a HOST BIND MOUNT shared by every frame on the box while this code ships in an image, so the two
    can be out of step in BOTH directions. New code against a conf that predates the marker work finds no placeholder,
    substitutes nothing and would hand the apps a marker their terminators never send: every mTLS call refused, with
    nothing in any log to say why.
    """
    nginx = tmp_path / "nginx"
    nginx.mkdir()
    for conf in ("nginx-teg.conf", "nginx-federation.conf"):
        (nginx / conf).write_text("location /api/v1/ {\n  proxy_set_header X-SSL-Client-Verify $ssl_client_verify;\n}\n")
    with pytest.raises(RuntimeError) as e:
        opprov.apply_operator_secrets(str(tmp_path), opprov.generate_operator_secrets(), "fixture")
    # the message must say WHICH of the two states it found, because "no marker" and "a commented marker" have
    # different fixes: update the shared templates, or find out why the uncommenting did not run
    assert "no LIVE" in str(e.value) and "predates the marker work" in str(e.value)


def test_the_shipped_shape_is_inert_for_a_registry_that_cannot_render_it(opprov, tmp_path):
    """The reason the marker ships commented: these confs are one bind mount and the renderer ships per image.

    A registry still on an older image copies the file verbatim. With the marker commented, what it copies behaves
    exactly as today's conf does, so an operator provisioned from EU or ASIA while they are a version behind is
    unaffected rather than born with a terminator sending an unrendered placeholder to apps that would refuse it.
    """
    d = _bundle(tmp_path)
    shipped = (d / "nginx" / "nginx-teg.conf").read_text()
    live_lines = [l for l in shipped.splitlines() if "Proxy-Auth" in l and not l.strip().startswith("#")]
    assert live_lines == [], f"the shipped template must carry no LIVE marker line, found {live_lines}"
    assert opprov.MARKER_COMMENT in shipped

    # and after rendering there is no comment left, which is its own refusal if something only half-renders
    opprov.apply_operator_secrets(str(d), opprov.generate_operator_secrets(), "fixture")
    rendered = (d / "nginx" / "nginx-teg.conf").read_text()
    assert opprov.MARKER_COMMENT not in rendered
    assert [l for l in rendered.splitlines() if "X-TEG-Proxy-Auth" in l and not l.strip().startswith("#")]


def test_control_a_substituted_but_still_commented_marker_refuses(opprov, tmp_path):
    """The failure mode the shipped comment introduces, and the one a substring check cannot see.

    agentvault2-85's catch: a COMMENTED directive contains both the header name and the secret, so asserting the text
    is present passes on a conf where the substitution worked and the uncommenting did not. nginx ignores the line
    while the apps demand the marker, which is the silently deaf operator the assertion exists to prevent. The check
    has to assert the directive is ACTIVE: anchored at its own line start, with no '#' in front of it.
    """
    v = opprov.generate_operator_secrets()
    nginx = tmp_path / "nginx"
    nginx.mkdir()
    (nginx / "nginx-teg.conf").write_text(
        'location /a {\n  # proxy_set_header X-TEG-Proxy-Auth "%s";\n}\n' % v["TEG_PROXY_TRUST_SECRET"])
    (nginx / "nginx-federation.conf").write_text(
        'location /b {\n  #OPDIST-MARKER# proxy_set_header X-Registry-Proxy-Auth "__REGISTRY_PROXY_TRUST_SECRET__";\n}\n'
        'location /c {\n  #OPDIST-MARKER# proxy_set_header X-TEG-Proxy-Auth "__TEG_PROXY_TRUST_SECRET__";\n}\n')
    with pytest.raises(RuntimeError) as e:
        opprov.apply_operator_secrets(str(tmp_path), v, "fixture")
    assert "no LIVE" in str(e.value) and "COMMENTED" in str(e.value)


def test_the_host_work_module_refuses_a_spec_carrying_a_credential(tmp_path):
    """§OPDIST — the seam is worth having only because nothing on the far side holds the database.

    The runner checks this too. Two doors that both check disagree less often than one that assumes the other did,
    and this is the door that would actually be holding the credential.
    """
    hw = _load("../host_work")
    for where in ({"DATABASE_URL": "postgresql://u:p@db/x"}, {"env": {"API_KEY_SECRET": "x"}}):
        spec = {"operator_name": "t", "safe_name": "t", "operator_did": "did:x", "frame": "lantern",
                "stack_root": str(tmp_path), "job_id": "j", "docker_pull_token": "dpt_x",
                "operator_secrets": {"TEG_PROXY_TRUST_SECRET": "a" * 64}, **where}
        p = tmp_path / "spec.json"
        p.write_text(__import__("json").dumps(spec))
        with pytest.raises(hw.HostWorkRefused) as e:
            hw.read_spec(str(p))
        assert "no database or API credential" in str(e.value) and "Nothing was done" in str(e.value)


def test_the_host_work_module_names_every_missing_field_at_once(tmp_path):
    """A spec missing three things should say so once, not three runs of the runner to find them one at a time."""
    hw = _load("../host_work")
    p = tmp_path / "spec.json"
    p.write_text('{"operator_name": "t"}')
    with pytest.raises(hw.HostWorkRefused) as e:
        hw.read_spec(str(p))
    for field in ("safe_name", "operator_did", "frame", "stack_root", "job_id", "docker_pull_token"):
        assert field in str(e.value), field


def test_the_auditor_credential_is_minted_but_not_in_the_set_the_operator_is_handed(opprov):
    """Two lists, deliberately: everything minted FOR the operator, and the subset handed TO it. The auditor's
    read-only credential is in the first and not the second — the operator's apps never read it."""
    assert "AUDITOR_RO_PASSWORD" in opprov.OPERATOR_SECRET_NAMES
    assert "AUDITOR_RO_PASSWORD" not in opprov.OPERATOR_ENV_SECRET_NAMES
    assert set(opprov.OPERATOR_ENV_SECRET_NAMES) < set(opprov.OPERATOR_SECRET_NAMES)
