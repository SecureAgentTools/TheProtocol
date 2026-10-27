#!/usr/bin/env python3
"""Move a frame to other images, and back: a sandbox onto a contributor's build, or any frame onto a RELEASE.

Test-verified development (a sandbox, unreleased code):

  ./frame-update.py --name <sandbox> --version 1.0.0-mine.1   the sandbox runs the images ./build.sh built under that
                                                               tag: its volumes, data and secrets stay, the registry
                                                               migrates at boot
  ./frame-update.py --name <frame> --rollback                  back to the images it ran before the last update (any
                                                               frame: a release from the channel is rolled back too)

The signed release channel (§RELEASECHANNEL, 2026-09-21; any frame, production included):

  ./frame-update.py --name <frame> --check                     what the channel lists, verified, against what the
                                                               frame runs; changes nothing
  ./frame-update.py --name <frame> --to-version 1.0.0-beta.12 --apply
                                                               pull that release's images BY DIGEST from the channel's
                                                               document, then recreate (the ledger first, the registry
                                                               last); --to-latest takes the newest listed
  ./frame-update.py --name <frame> --to-latest --schedule 2026-09-23T02:00:00+02:00
                                                               a transient systemd timer runs the apply in the window
                                                               you chose (--cancel-schedule removes it)

A release is only ever applied from the verified document: the images are pulled by the digests it names, so a tag
that was moved, or a registry that lies, cannot put other code on the frame. A version built locally (--version) is
refused on a production frame: unreleased code goes in front of a test suite, never in front of users. Only the
services whose image really changes are recreated (--no-deps, the ledger first and the registry last), networks the
sandbox's tester had joined are joined again, and afterwards the registry answers /health with the new build's
provenance and the ledger's supply delta is read before and after. Every update is recorded in
<stack>/frame-update.json, which --rollback reads. The registry's own admin page schedules the same window on the
registry side and reminds you; only this command moves anything.
"""
import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_spec = importlib.util.spec_from_file_location("frame_names", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_names.py"))
frame_names = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(frame_names)
_rc_spec = importlib.util.spec_from_file_location("release_channel", os.path.join(HERE, "release_channel.py"))
release_channel = importlib.util.module_from_spec(_rc_spec); _rc_spec.loader.exec_module(release_channel)
CHANNEL_URL = os.getenv("RELEASE_CHANNEL_URL", release_channel.DEFAULT_URL)

ENV_FILE, COMPOSE_FILE, HISTORY = ".env.frame-test", "docker-compose.frame-test.yml", "frame-update.json"
# the kit's own images, as the frame's env names them (the frame template reads each through ${FT_*_IMAGE})
IMAGE_KEYS = ("FT_ES_IMAGE", "FT_TEG_IMAGE", "FT_CERT_WRITER_IMAGE", "FT_AUDITOR_IMAGE", "FT_DIRECTORY_IMAGE", "FT_REG_IMAGE")
VERSION_KEYS = ("VERSION", "FT_REG_VERSION")          # what the registry reports as its version (its card, /health)
IMAGE_REF = re.compile(r"^(?P<repo>[A-Za-z0-9._/-]+):(?P<tag>[A-Za-z0-9._-]+)$")


def log(msg):
    print(f"[frame-update {time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def die(msg, code=2):
    log(msg)
    sys.exit(code)


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def read_env(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.rstrip("\n").split("=", 1)
            out[k.strip()] = v
    return out


def upsert_env(path, pairs):
    text = open(path, encoding="utf-8").read()
    for k, v in pairs.items():
        line = f"{k}={v}"
        if re.search(rf"(?m)^{re.escape(k)}=.*$", text):
            text = re.sub(rf"(?m)^{re.escape(k)}=.*$", lambda _m: line, text)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
    mode = os.stat(path).st_mode & 0o777
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, mode)


def retag(ref, version):
    """<repo>:<old> -> <repo>:<version>; None for a value that is not a plain image reference."""
    m = IMAGE_REF.match(ref or "")
    return f"{m.group('repo')}:{version}" if m else None


def fetch_channel():
    """(verified document, reason): the document only when its signature verifies, else why not."""
    try:
        req = urllib.request.Request(CHANNEL_URL, headers={"User-Agent": "theprotocol-frame-update/1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                return None, f"HTTP {r.status}"
            body = r.read(release_channel.MAX_BYTES + 1)
        if len(body) > release_channel.MAX_BYTES:
            return None, "document larger than 1 MB"
        doc = json.loads(body)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"
    ok, reason = release_channel.verify(doc, os.getenv("RELEASE_CHANNEL_PUBKEY_B64") or None)
    return (doc, "ok") if ok else (None, f"NOT VERIFIED: {reason}")


def running_of(rec, env):
    """What the frame runs: the kit version its registry reports (BUILD_INFO via /health), else the env's version."""
    port = (rec.get("ports") or {}).get("registry")
    kit = None
    if port:
        st, body = get_json(f"http://127.0.0.1:{port}/health")
        if st == 200 and isinstance(body, dict):
            kit = ((body.get("build") or {}).get("kit_version"))
    version = env.get("FT_REG_VERSION") or env.get("VERSION")
    if kit is None and release_channel.parse_kit_version(version):
        kit = version
    return {"kit_version": kit, "software_version": None if kit else version}


def pull_by_digest(prefix, tag, digests):
    """Pull each image by the digest the document names and tag it <prefix>/<name>:<tag> locally; the env then names
    the tag, the container runs the digest's bytes. Returns {name: local ref}."""
    out = {}
    for name, digest in sorted(digests.items()):
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest or ""):
            die(f"the channel names no usable digest for {name}")
        src = f"{prefix}/{name}@{digest}"
        r = run(["docker", "pull", src], timeout=1800)
        if r.returncode != 0:
            die(f"pull of {src} failed: {(r.stderr or r.stdout).strip()[-300:]}", 4)
        ref = f"{prefix}/{name}:{tag}"
        run(["docker", "tag", src, ref], check=False)
        out[name] = ref
        log(f"pulled {name} {digest[:19]}... as {ref}")
    return out


_IMAGE_NAME_OF_KEY = {"FT_ES_IMAGE": "event-store", "FT_TEG_IMAGE": "teg-layer", "FT_CERT_WRITER_IMAGE": "cert-writer",
                      "FT_AUDITOR_IMAGE": "auditor", "FT_DIRECTORY_IMAGE": "directory", "FT_REG_IMAGE": "registry"}


def schedule_timer(name, when, version):
    if not shutil.which("systemd-run"):
        die(f"systemd-run is not available here; run `./frame-update.py --name {name} --to-version {version} --apply` "
            f"yourself at {when.isoformat()}", 5)
    unit = f"frame-update-{name}"
    cmd = ["systemd-run", f"--unit={unit}", f"--on-calendar={when.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
           "--timer-property=AccuracySec=1min", f"--description=TheProtocol rollout of frame {name} to {version}",
           sys.executable, os.path.abspath(__file__), "--name", name, "--to-version", version, "--apply"]
    r = run(cmd)
    if r.returncode != 0:
        die(f"systemd-run refused: {(r.stderr or r.stdout).strip()[:300]}", 5)
    log(f"scheduled: {unit}.timer runs the apply of {version} at {when.isoformat()} (--cancel-schedule removes it)")


def image_id(ref):
    r = run(["docker", "image", "inspect", ref, "--format", "{{.Id}}"])
    return r.stdout.strip() if r.returncode == 0 else None


def container_image(name):
    r = run(["docker", "inspect", name, "--format", "{{.Image}}"])
    return r.stdout.strip() if r.returncode == 0 else None


def services_by_key(compose_text):
    """{env key: [service, ...]} for every service whose image is ${KEY...}."""
    out = {}
    for block in re.split(r"(?m)^(?=  [a-z][a-z0-9-]*:\s*$)", compose_text):
        m = re.match(r"  ([a-z][a-z0-9-]*):", block)
        im = re.search(r"(?m)^    image:\s*\$\{([A-Z0-9_]+)", block)
        if m and im:
            out.setdefault(im.group(1), []).append(m.group(1))
    return out


def get_json(url, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except Exception as exc:  # noqa: BLE001 — the caller reports what it could not read
        return None, str(exc)[:200]


def delta(rec):
    port = (rec.get("ports") or {}).get("es")
    if not port:
        return None
    st, body = get_json(f"http://127.0.0.1:{port}/api/v1/projections/supply-audit")
    return body.get("delta") if st == 200 and isinstance(body, dict) else None


def posture(rec, env):
    if rec.get("sandbox_of"):
        return "sandbox"
    return (env.get("FRAME_POSTURE") or env.get("FT_REG_FRAME_POSTURE") or "production").strip().lower()


def apply(rec, sd, name, new_env, reason):
    """Write the env, recreate what changed (ledger first, registry last), rejoin, wait for health."""
    env_path, compose_path = os.path.join(sd, ENV_FILE), os.path.join(sd, COMPOSE_FILE)
    old_env = read_env(env_path)
    by_key = services_by_key(open(compose_path, encoding="utf-8").read())
    recreate = []
    for key in IMAGE_KEYS:
        new_ref = new_env.get(key)
        if not new_ref or new_ref == old_env.get(key):
            continue
        new_id = image_id(new_ref)
        for svc in by_key.get(key, []):
            if container_image(svc) != new_id:
                recreate.append(svc)
    before = delta(rec)
    upsert_env(env_path, new_env)
    log(f"{ENV_FILE}: {', '.join(sorted(new_env))} set ({reason})")
    if not recreate:
        log("no running service's image changes: nothing to recreate")
    order = [s for s in recreate if not s.endswith("-registry")] + [s for s in recreate if s.endswith("-registry")]
    for svc in order:
        r = run(["docker", "compose", "-f", COMPOSE_FILE, "--env-file", ENV_FILE, "up", "-d", "--no-deps", "--no-build",
                 "--pull", "never", "--force-recreate", svc], cwd=sd, timeout=900)
        if r.returncode != 0:
            die(f"recreating {svc} failed: {(r.stderr or r.stdout).strip()[-300:]} (the env now names the new images; "
                f"--rollback puts the previous ones back)", 4)
        log(f"recreated {svc}")
    # the sandbox's tester reaches the other sandbox by name on its network (frame-sandbox's fixtures step): a
    # recreated registry has left it
    for net in ((rec.get("tester") or {}).get("joins") or []):
        r = run(["docker", "network", "connect", net, f"{name}-registry"])
        if r.returncode == 0 or "already exists" in (r.stderr or ""):
            log(f"{name}-registry joined {net} again")
        else:
            log(f"!! {name}-registry could not join {net}: {(r.stderr or '').strip()[-160:]}")
    port = (rec.get("ports") or {}).get("registry")
    health = None
    for _ in range(72):
        st, body = get_json(f"http://127.0.0.1:{port}/health")
        if st == 200 and isinstance(body, dict) and body.get("status") == "ok":
            health = body
            break
        time.sleep(5)
    if health is None:
        die(f"{name}-registry does not answer /health after 6 min", 5)
    build = health.get("build")
    log(f"{name}-registry healthy; build: " + (json.dumps(build) if build else "none reported (an image built without "
                                                                               "the kit's provenance)"))
    after = None
    for _ in range(24):
        after = delta(rec)
        if after == 0.0:
            break
        time.sleep(5)
    log(f"ledger supply delta: before {before}, after {after}")
    return build, before, after


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="the frame (--version, a local build, takes a sandbox only)")
    ap.add_argument("--version", help="the image tag build.sh built (./build.sh --version <tag>)")
    ap.add_argument("--rollback", action="store_true", help="back to the images the frame ran before its last update")
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"))
    ap.add_argument("--check", action="store_true", help="read the signed release channel and compare; change nothing")
    ap.add_argument("--to-version", help="a release the signed channel lists (pulled by digest)")
    ap.add_argument("--to-latest", action="store_true", help="the newest release the signed channel lists")
    ap.add_argument("--apply", action="store_true", help="with --to-version/--to-latest: pull and recreate now")
    ap.add_argument("--schedule", help="with --to-version/--to-latest: ISO 8601 date-time for a systemd timer that applies then")
    ap.add_argument("--cancel-schedule", action="store_true", help="remove this frame's scheduled rollout timer")
    a = ap.parse_args(argv)
    release_mode = bool(a.check or a.to_version or a.to_latest or a.cancel_schedule)
    if a.version and release_mode:
        die("--version (a local build) and the release options do not mix")
    if not release_mode and bool(a.version) == bool(a.rollback):
        die("give --version <tag>, --rollback, --check, --to-version <v> or --to-latest")
    dirs = frame_names.stack_dirs(a.stack_root, a.name, need_file="frame-up.json")
    if not dirs:
        die(f"no frame named {a.name} under {a.stack_root} (frame-up writes <name>-<ts>/frame-up.json)")
    sd = os.path.join(a.stack_root, dirs[-1])
    rec = json.load(open(os.path.join(sd, "frame-up.json")))
    env = read_env(os.path.join(sd, ENV_FILE))
    p = posture(rec, env)
    if a.cancel_schedule:
        r = run(["systemctl", "stop", f"frame-update-{a.name}.timer"])
        log("cancelled" if r.returncode == 0 else f"no scheduled rollout for {a.name}")
        return 0 if r.returncode == 0 else 1
    if release_mode:
        doc, reason = fetch_channel()
        running = running_of(rec, env)
        if doc is None:
            log(f"release channel: {reason} ({CHANNEL_URL})")
            log(f"{a.name} runs {running.get('kit_version') or running.get('software_version') or 'unknown'}")
            return 3 if a.check else die("no verified release document; nothing applied", 3)
        verdict = release_channel.assess(doc, running)
        latest = (verdict["latest"] or {}).get("version")
        if a.check:
            state = ("cannot compare versions" if not verdict["comparable"] else
                     f"update available ({verdict['kind']}): " + ", ".join(r["version"] for r in verdict["newer"])
                     if verdict["update_available"] else "up to date")
            log(f"{a.name} runs {running.get('kit_version') or running.get('software_version')}; channel newest {latest}; {state}")
            for r in verdict["newer"]:
                log(f"  {r['version']} ({r['kind']}, {r.get('released_at')}): {(r.get('notes') or '')[:200]}")
            return 0
        target = a.to_version or latest
        rel = release_channel.find_release(doc, target)
        if rel is None:
            die(f"{target} is not a release the verified channel lists (newest {latest})")
        when = None
        if a.schedule:
            try:
                when = datetime.datetime.fromisoformat(a.schedule.replace("Z", "+00:00"))
            except ValueError:
                die("--schedule takes an ISO 8601 date-time, e.g. 2026-09-23T02:00:00+02:00")
            if when.tzinfo is None:
                when = when.astimezone()
            if when <= datetime.datetime.now(datetime.timezone.utc):
                die("--schedule must be in the future")
            schedule_timer(a.name, when, target)
            return 0
        if not a.apply:
            die(f"{target} is listed ({rel.get('kind')}); add --apply to pull it by digest and recreate now, or --schedule <when>")
        images = rel.get("images") or {}
        prefix, tag, digests = images.get("prefix"), images.get("tag") or target, images.get("digests") or {}
        if not prefix or not digests:
            die(f"the channel's entry for {target} names no images to pull")
        pulled = pull_by_digest(prefix, tag, digests)
        new_env = {}
        for key, image_name in _IMAGE_NAME_OF_KEY.items():
            if key in env and image_name in pulled:
                new_env[key] = pulled[image_name]
        for key in VERSION_KEYS:
            if key in env:
                new_env[key] = target
        hist_path = os.path.join(sd, HISTORY)
        history = json.load(open(hist_path)) if os.path.isfile(hist_path) else []
        entry = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "from": {k: env[k] for k in new_env if k in env}, "to": new_env, "release": target,
                 "digests": digests, "rollback_note": rel.get("rollback")}
        if rel.get("rollback"):
            log(f"rollback note for {target}: {rel['rollback']}")
        build, before, after = apply(rec, sd, a.name, new_env, f"release {target} ({rel.get('kind')})")
        entry.update({"build": build, "delta_before": before, "delta_after": after})
        history.append(entry)
        with open(hist_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=1)
        log(f"done: {a.name} on release {target}; history in {HISTORY}")
        return 0 if (after == 0.0 or after is None) else 6
    # CB-340: the gate is the local build's. It ran before the rollback branch too, so a release applied from the
    # channel (the history it records is exactly what --rollback reads) could be rolled back only on a sandbox.
    if a.version and p != "sandbox":
        die(f"{a.name} is a {p} frame: a local build (--version) puts unreleased code in front of a test suite, only on "
            f"a sandbox (frame-sandbox.py up --for <frame> stands one up); a release from the channel takes --to-version")
    hist_path = os.path.join(sd, HISTORY)
    history = json.load(open(hist_path)) if os.path.isfile(hist_path) else []
    if a.rollback:
        if not history:
            die(f"{a.name} has no recorded update to roll back ({HISTORY} is empty)")
        last = history[-1]
        if last.get("rollback_note"):
            log(f"rollback note of {last.get('release') or 'the update'}: {last['rollback_note']}")
        build, before, after = apply(rec, sd, a.name, last["from"], f"rollback of the update at {last['at']}")
        history.pop()
    else:
        new_env, missing = {}, []
        for key in IMAGE_KEYS:
            ref = retag(env.get(key), a.version)
            if not ref:
                continue
            if image_id(ref) is None:
                missing.append(ref)
            new_env[key] = ref
        if missing:
            die(f"not on this host: {', '.join(missing)} (build them first: ./build.sh --version {a.version})")
        for key in VERSION_KEYS:
            if key in env:
                new_env[key] = a.version
        entry = {"at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "from": {k: env[k] for k in new_env if k in env}, "to": new_env}
        build, before, after = apply(rec, sd, a.name, new_env, f"update to {a.version}")
        entry.update({"build": build, "delta_before": before, "delta_after": after})
        history.append(entry)
    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=1)
    log(f"done: {a.name} on {'the previous images' if a.rollback else a.version}; history in {HISTORY}")
    return 0 if (after == 0.0 or after is None) else 6


if __name__ == "__main__":
    sys.exit(main())
