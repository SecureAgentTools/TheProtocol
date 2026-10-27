"""§TESTBED (2026-09-19): a SANDBOX's registry gets the docker socket ALONE (its own tester docker-execs into its own
containers). The socket is root on the host, so the grant takes the same typed phrase as host reach, names the socket's
group, and mounts nothing else of the host (no /host-stack, no nginx sites). A frame without either grant gets neither."""
from agentvault_registry.services import frame_test_provisioner as prov


def _ctx(**kw):
    return prov.FrameTestContext(ts=1, **kw)


def test_the_default_mounts_no_socket_and_joins_no_docker_group():
    ctx = _ctx()
    assert "docker.sock" not in prov._render_host_mounts(ctx).replace("no docker.sock", "")
    assert prov._template_values(ctx)["REGISTRY_DOCKER_GROUP"].startswith("#")


def test_the_socket_grant_mounts_the_socket_and_nothing_else(monkeypatch):
    monkeypatch.setenv("FRAME_RUNNER_SOCKET_GID", "1000")   # a host whose runner socket group is not the docker group
    ctx = _ctx(grant_docker_socket=True, docker_socket_gid="988",
               host_reach_confirmation=prov.HOST_REACH_CONFIRMATION_PHRASE)
    mounts = prov._render_host_mounts(ctx)
    assert "- /var/run/docker.sock:/var/run/docker.sock:ro" in mounts
    assert "/host-stack" not in mounts.split("\n", 2)[-1] and "/host-nginx-sites" not in mounts
    assert prov._template_values(ctx)["REGISTRY_DOCKER_GROUP"].startswith('- "988"')


def test_a_docker_group_already_joined_as_the_runner_sockets_is_joined_once(monkeypatch):
    """§NIGHTPROV (2026-09-27): this host renders the runner socket's gid as 988 (the default), which IS the docker socket's
    group, so a frame given the socket rendered `- "988"` twice under group_add and `docker compose config` refused the
    stack ("group_add items at 0 and 1 are equal", measured on nt260927x1a). The previous version of this file pinned the
    duplicate as correct: the test above asserted `- "988"` with the runner gid left at its default of 988."""
    monkeypatch.delenv("FRAME_RUNNER_SOCKET_GID", raising=False)
    ctx = _ctx(grant_docker_socket=True, docker_socket_gid="988",
               host_reach_confirmation=prov.HOST_REACH_CONFIRMATION_PHRASE)
    values = prov._template_values(ctx)
    assert values["RUNNER_SOCKET_GID"] == "988"
    assert values["REGISTRY_DOCKER_GROUP"].startswith("#") and "988" in values["REGISTRY_DOCKER_GROUP"]
    group_add = ['"' + values["RUNNER_SOCKET_GID"] + '"'] + [l.split()[1] for l in [values["REGISTRY_DOCKER_GROUP"]]
                                                             if l.startswith("- ")]
    assert len(group_add) == len(set(group_add)) == 1
    # control: host reach joins it once too, and a frame with no socket still joins no docker group line
    ctx = _ctx(grant_host_reach=True, docker_socket_gid="988", host_reach_confirmation=prov.HOST_REACH_CONFIRMATION_PHRASE)
    assert prov._template_values(ctx)["REGISTRY_DOCKER_GROUP"].startswith("#")
    assert prov._template_values(_ctx())["REGISTRY_DOCKER_GROUP"] == "# no docker socket group (the socket is not mounted)"


def test_the_socket_grant_needs_the_phrase_and_a_numeric_group():
    probs = prov.validate_provisioning_inputs(_ctx(grant_docker_socket=True, docker_socket_gid="988"), strict=False)
    assert any("grant_docker_socket=True requires host_reach_confirmation" in p for p in probs)
    probs = prov.validate_provisioning_inputs(_ctx(grant_docker_socket=True, docker_socket_gid="",
                                                   host_reach_confirmation=prov.HOST_REACH_CONFIRMATION_PHRASE), strict=False)
    assert any("needs docker_socket_gid" in p for p in probs)
    ok = prov.validate_provisioning_inputs(_ctx(grant_docker_socket=True, docker_socket_gid="988",
                                                host_reach_confirmation=prov.HOST_REACH_CONFIRMATION_PHRASE), strict=False)
    assert not any("docker" in p for p in ok), ok


def test_the_template_renders_the_group_line_under_group_add():
    import os
    import pathlib
    here = pathlib.Path(prov.__file__).resolve()
    roots = [pathlib.Path(os.environ["R50_TREE"])] if os.environ.get("R50_TREE") else []
    roots += [p for p in here.parents if (p / "templates" / "frame-test").is_dir()]
    tmpl = next((r / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl" for r in roots
                 if (r / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl").is_file()), None)
    if tmpl is None:   # CI's AgentVault checkout has no stack tree (R50's class): the unit tests above stand alone
        return
    text = tmpl.read_text()
    i = text.index('- "{{RUNNER_SOCKET_GID}}"')
    assert "{{REGISTRY_DOCKER_GROUP}}" in text[i:i + 200]
