"""Can this registry do an operator's HOST work? (§OPDIST, 2026-09-16)

A predicate with no relative imports on purpose: it is read by the cloud provisioner AND by the activation rail, and a
shared rule that only one caller can import is how two doors end up disagreeing. It is also why this file can be loaded
by a test on its own.
"""
import os

# the EDGE postures a frame runner may answer (§HELLOFRAME lane 6, 2026-09-18): the runner's own constant
EDGE_MODES = ("nginx", "caddy")


def docker_socket_available() -> tuple:
    """Can this registry do the host work ITSELF? The answer is the daemon's, not the filesystem's: a socket that is
    mounted but unusable (no permission, daemon down) fails in exactly the way this is meant to catch."""
    sock = "/var/run/docker.sock"
    if not os.path.exists(sock):
        return False, ("this frame's registry has no /var/run/docker.sock, so it cannot build an operator bundle or "
                       "its stack itself. That is deliberate: a docker socket is root on the host, and frames built "
                       "by the runner are hardened without one")
    # §TESTBED (2026-09-19): the socket ALONE is not host reach. A KIT sandbox's registry (frame-sandbox.py) holds it for
    # its own tester (which docker-execs into its containers) and nothing else of the host; doing an operator's host work
    # here also needs the host's stack directory (cloud_provisioner.HOST_STACK_MOUNT), which only full host reach mounts.
    # On this network's host EU, ASIA AND the sandbox pair (sbx-alpha, sbx-beta) mount it, so all four answer "itself"
    # here (§F6 WP6.0, 2026-09-26: this comment said only EU and ASIA did; the pair has mounted it all along).
    # Measured on larchsbx: with the socket alone this answered "itself", the activation built no bundle and answered 200,
    # and the provision then failed "Bundle not found at None". Without the stack mount the frame runner does the work.
    if not os.path.isdir("/host-stack"):
        return False, ("this frame's registry holds the docker socket but not the host's stack directory (/host-stack), "
                       "so it cannot write an operator's stack itself (a sandbox's socket is for its tester); the frame "
                       "runner does that host work")
    try:
        import docker as _docker
        _docker.DockerClient(base_url=f"unix://{sock}", timeout=5).ping()
        return True, "this registry can do the host work itself (the host Docker API answers)"
    except Exception as exc:  # noqa: BLE001
        return False, (f"this frame's registry has the docker socket but the daemon did not answer "
                       f"({type(exc).__name__}), so an operator bundle cannot be built here")


def docker_daemon_available() -> tuple:
    """Does the host Docker API answer on this registry's socket? The NARROWER question, for callers that only READ the
    daemon (the operator detail route's container census). docker_socket_available() asks something else: whether this
    registry may do an operator's HOST WORK itself, which since §TESTBED also needs /host-stack. A sandbox holds the
    socket for its tester: it cannot write an operator's stack, and it can still list containers. Two questions, two
    predicates, so narrowing one cannot silently narrow a caller that asks the other (§HELLOFRAME lane 6, 2026-09-19)."""
    sock = "/var/run/docker.sock"
    if not os.path.exists(sock):
        return False, "this frame's registry has no /var/run/docker.sock, so it cannot ask the host Docker API"
    try:
        import docker as _docker
        _docker.DockerClient(base_url=f"unix://{sock}", timeout=5).ping()
        return True, "the host Docker API answers on this registry's socket"
    except Exception as exc:  # noqa: BLE001
        return False, (f"this frame's registry has the docker socket but the daemon did not answer "
                       f"({type(exc).__name__})")


def runner_available() -> tuple:
    """Can this registry ask the FRAME RUNNER to do the host work for it?

    §OPDIST (2026-09-16), his decision: the privileged work moved to the privileged component, so "cannot provision"
    stopped meaning "has no docker socket" the moment a frame could ask the runner instead. A refusal that outlives
    its reason is the same class as a tolerance that does, so the predicate gained this term in the same change that
    made it possible rather than after someone noticed the message had become false.

    The question is answered by the runner, not by the socket file: operator_ping is the op that says what THIS
    caller may ask for on the socket it can see, so a socket that exists and refuses everything reads as unavailable
    rather than as capability.
    """
    try:
        from agentvault_registry.services import frame_runner_client as _frc
    except Exception as exc:  # noqa: BLE001
        return False, f"the runner client is not importable here ({type(exc).__name__})"
    # the OPERATOR socket (frame_runner_client.operator_socket_path): the one a provision after this answer dials. On a
    # registry that mounts the runner's whole directory the top socket is the FULL one, which refuses operator_ping.
    path = _frc.operator_socket_path()
    if not os.path.exists(path):
        return False, f"no frame runner socket at {path}, so nothing can do the host work on this frame's behalf"
    try:
        envelope = _frc._exchange(path, {"op": "operator_ping"}, 5.0)
    except Exception as exc:  # noqa: BLE001
        return False, f"the frame runner at {path} did not answer ({type(exc).__name__})"
    if envelope.get("ok") is True:
        return True, "the frame runner answers operator_ping and can do the host work for this frame"
    refused = envelope.get("refused") or envelope.get("error") or "no reason given"
    return False, f"the frame runner at {path} refuses operator_ping: {refused}"


def runner_edge() -> str:
    """Which EDGE the frame runner on this host applies after an operator provision, read from its operator_ping:
    "nginx" (this host's nginx vhost and SNI line, the posture of every frame on the network's own host) or "caddy"
    (a frame stood up by frame-up on its own host, whose own edge container gets one site file per operator).

    "nginx" on ANY failure and for a runner too old to answer the field, so an older runner keeps its behaviour
    byte for byte and the provisioner writes the operator's public URLs the way it always has. (§HELLOFRAME lane 6)
    """
    try:
        from agentvault_registry.services import frame_runner_client as _frc
        path = _frc.operator_socket_path()   # operator_ping is an operator op (see runner_available)
        if not os.path.exists(path):
            return "nginx"
        envelope = _frc._exchange(path, {"op": "operator_ping"}, 5.0)
    except Exception:  # noqa: BLE001 — no runner, no answer, no field: the posture every frame had before this
        return "nginx"
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        return "nginx"
    result = envelope.get("result") if isinstance(envelope.get("result"), dict) else {}
    edge = str(result.get("edge") or "nginx").strip().lower()
    return edge if edge in EDGE_MODES else "nginx"


PREFER_ENV = "HOST_REACH_PREFER"
ROUTES = ("direct", "runner")


def host_route() -> tuple:
    """WHICH ROUTE an operator's host work takes here: ("direct" or "runner", why), or (None, why) when neither may.

    §F6 WP6.0 (2026-09-26, his word "approved ... do it fully autonomously"): a registry that holds BOTH routes (the
    docker socket with the host stack, and the frame runner's operator socket; EU, ASIA and the sandbox pair since the
    runner's operator socket was mounted on all four) must not take one by the accident of which check runs first.
    HOST_REACH_PREFER names it:

      unset or ""    today's order, byte for byte: this registry itself when it can, the frame runner otherwise
      "runner"       the frame runner ONLY; when the runner is missing or refuses, the answer is None with the runner's
                     own sentence, and the docker socket is NOT taken in its place: a silent fallback would keep the
                     socket load-bearing on exactly the frames F6 takes it off
      "direct"       this registry ONLY, the same way round
      anything else  None: a knob that says something this code does not understand is refused, never guessed

    ⚠ The runner's operator ops act only on frames it built or ADOPTED (frame_runner.py `_operator_frame`; `adopt
    --reference` records a frame it did not build: sbx-beta since §F6 B1), so "runner" on a frame the runner does not
    know is refused BY THE RUNNER, and a refusal here says why in the runner's words. A registry that mounts the
    runner's whole directory asks the operator socket in its subdirectory (frame_runner_client.operator_socket_path),
    never the full socket at the top, which refuses every operator op.
    """
    prefer = (os.getenv(PREFER_ENV) or "").strip().lower()
    if prefer and prefer not in ROUTES:
        return None, (f"{PREFER_ENV}={prefer!r} is neither 'runner' nor 'direct': refusing rather than guessing which "
                      f"route an operator's host work should take")
    if prefer == "runner":
        ok, why = runner_available()
        return ("runner", why) if ok else (None, f"{PREFER_ENV}=runner and {why}; the docker socket is not used in "
                                                 f"its place (fail closed)")
    if prefer == "direct":
        ok, why = docker_socket_available()
        return ("direct", why) if ok else (None, f"{PREFER_ENV}=direct and {why}; the frame runner is not used in "
                                                 f"its place (fail closed)")
    direct_ok, direct_why = docker_socket_available()
    if direct_ok:
        return "direct", direct_why
    runner_ok, runner_why = runner_available()
    if runner_ok:
        return "runner", runner_why
    return None, f"{direct_why}; and {runner_why}"


def host_reach_available() -> tuple:
    """Can an operator's host work GET DONE from here? Returns (ok, why), the answer of host_route().

    Two routes: this registry holding the docker socket and the host stack (EU, ASIA and the sandbox pair), or a frame
    runner that does it in a one-shot container (every frame the runner builds). Unset, the answer is yes if either
    works; HOST_REACH_PREFER narrows it to one, and then a refusal names that one. A refusal with both routes open to it
    names BOTH reasons, because "no docker socket" alone stopped being the whole truth and a half-true refusal sends the
    reader to the wrong fix.
    """
    route, why = host_route()
    return route is not None, why
