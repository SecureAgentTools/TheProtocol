"""`bundle verify` checks what it says (CB-299).

It promised signature and checksum verification and only looked for manifest.json, README.md and an agents/*.json, so a
bundle whose agent file was changed after signing read "valid". A signed bundle's JWS carries its payload: the manifest
and the sha256 of each agent file as packed (the registry's canonical_signing_payload). The check now compares the
contents with that payload; the signature itself needs the signer's public key and is reported as not verified.
"""
import base64
import gzip
import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

pytest.importorskip("typer")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator.commands import bundle  # noqa: E402


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _tpb(path: Path, *, signed=True, tamper=False):
    manifest = {"bundle_id": "b1", "bundle_kind": "snapshot", "name": "demo", "exporter": {}, "contents": {}}
    agent = {"did": "did:theprotocol:0123456789ab", "name": "Demo", "status": "active"}
    agent_bytes = json.dumps(agent, indent=2, sort_keys=True).encode()
    payload = json.dumps({"manifest": manifest, "agent_payload_sha256": [hashlib.sha256(agent_bytes).hexdigest()]},
                         sort_keys=True, separators=(",", ":")).encode()
    jws = ".".join([_b64(json.dumps({"alg": "EdDSA", "kid": "k1", "typ": "TpBundleSig"}).encode()), _b64(payload),
                    _b64(b"\x00" * 64)])
    if tamper:
        agent_bytes = json.dumps({**agent, "status": "suspended"}, indent=2, sort_keys=True).encode()
    files = {"manifest.json": json.dumps(manifest, indent=2, sort_keys=True).encode(), "README.md": b"# demo\n",
             "agents/demo-0123456789ab.json": agent_bytes}
    if signed:
        files["signature.jws"] = jws.encode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            for name, content in files.items():
                ti = tarfile.TarInfo(name)
                ti.size = len(content)
                tar.addfile(ti, io.BytesIO(content))
    path.write_bytes(buf.getvalue())
    return path


def test_a_signed_bundle_whose_contents_are_what_it_signed_is_valid(tmp_path):
    r = bundle._cmd_verify(_tpb(tmp_path / "ok.tpb"))
    assert r["valid"] is True and r["signature"]["covers_contents"] is True
    assert r["signature"]["verified"] is False          # said, never implied


def test_an_agent_file_changed_after_signing_is_not_valid(tmp_path):
    r = bundle._cmd_verify(_tpb(tmp_path / "bad.tpb", tamper=True))
    assert r["signature"]["covers_contents"] is False and r["valid"] is False


def test_an_unsigned_bundle_is_judged_on_its_layout(tmp_path):
    r = bundle._cmd_verify(_tpb(tmp_path / "plain.tpb", signed=False))
    assert r["valid"] is True and r["signature"]["present"] is False
