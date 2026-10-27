"""§DEPS (2026-09-28): passlib is gone and bcrypt 5 is in; core/secret_hash.py keeps passlib's rules byte for byte.

Every hash below was made by passlib 1.7.4 + bcrypt 4.0.1 in the V0476 image, the pair that made every hash stored on
every frame (measured 2026-09-28 on EU, ASIA, the sandbox pair and the six operators: every stored hash is "$2b$";
the other stored values are markers of mirrored developers and deleted accounts). The secrets are test strings.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re

import pytest

from agentvault_registry.core import secret_hash as sh

PASSLIB_1_7_4 = {
    "short": ("correct horse battery staple!",
              "$2b$12$24vcgIvr.N4sWjBLeJP0o.0Xt8sckEwtxEDw4KG2NjFG/qpw4u2LO"),
    "client_secret_74": ("tp_secret_" + "0123456789abcdef" * 4,
                         "$2b$12$hQ2Pb8.OvFhlV9tt22PuHuMGd.mqGgldmYi1e6RpbbzWWiz9Vdbh2"),
    "multibyte_cut_mid_char": ("a" + "é" * 50,
                               "$2b$12$UKiqGT3J6BLklmZEXXXtKOdGV/r4psifVFKCmmLT7JcPCP6Bwm9Pm"),
    "backup_code": ("ABCD-1234",
                    "$2b$12$u4oSaUWtYlVYqlHz.pcxFeKEdEoMPGItO5WfbACd80ZtYib5BjzmK"),
    "recovery_key": ("avrec-0123abcd-4567ef01-89abcdef",
                     "$2b$12$D3qAGaM6KJrZSiDmfk8A.eaPOd1exmSGaiiJJR/mVA5rvAzr3gfx2"),
    "ident_2a": ("idents-test", "$2a$12$/B0sUMM6pFgD7Pj8kOsYhui9fF3ecvtGGmisWJTUzZpmC2EO5/BBG"),
    "ident_2y": ("idents-test", "$2y$12$ZRAfmq8mwV7W3pEIQ1NbqeVJcvtNiakkEhg2oIb8FqTk02u9F50Y6"),
}


@pytest.mark.parametrize("name", sorted(PASSLIB_1_7_4))
def test_every_hash_passlib_made_verifies(name):
    secret, stored = PASSLIB_1_7_4[name]
    assert sh.verify_secret(secret, stored) is True
    assert sh.verify_secret("y" + secret, stored) is False


def test_only_the_first_72_bytes_count_as_they_always_did():
    # every agent client secret is 74 bytes ("tp_secret_" + 64 hex); passlib + bcrypt 4 read 72 of them, bcrypt 5
    # raises on 73: without the cut no agent could log in
    secret, stored = PASSLIB_1_7_4["client_secret_74"]
    assert len(secret.encode()) == 74
    assert sh.verify_secret(secret[:72], stored) is True
    assert sh.verify_secret(secret[:72] + "zz", stored) is True
    assert sh.verify_secret(secret[:71], stored) is False
    # the cut is at a byte, inside a two-byte character if that is where byte 72 falls
    secret, stored = PASSLIB_1_7_4["multibyte_cut_mid_char"]
    assert len(secret.encode()) == 101
    assert sh.verify_secret(secret.encode()[:72], stored) is True
    assert sh.verify_secret(secret.encode()[:71], stored) is False


def test_a_new_hash_has_the_shape_passlib_made():
    secret = "tp_secret_" + "f" * 64
    h = sh.hash_secret(secret)
    assert h.startswith("$2b$12$") and len(h) == 60
    assert sh.verify_secret(secret, h) is True
    assert sh.verify_secret(secret[:71], h) is False
    assert sh.hash_secret("").startswith("$2b$12$")
    assert sh.hash_secret(b"bytes-secret").startswith("$2b$12$")


def test_the_secrets_passlib_refused_are_refused():
    with pytest.raises(ValueError):
        sh.hash_secret("a\x00b")  # bcrypt 5 would hash it; passlib refused it
    with pytest.raises(ValueError):
        sh.hash_secret("x" * 4097)
    assert sh.hash_secret("x" * 4096).startswith("$2b$12$")
    with pytest.raises(TypeError):
        sh.hash_secret(None)
    stored = PASSLIB_1_7_4["short"][1]
    assert sh.verify_secret("correct horse battery staple!\x00", stored) is False
    assert sh.verify_secret(None, stored) is False
    assert sh.verify_secret("", stored) is False


@pytest.mark.parametrize("stored", ["FEDERATED-DEVELOPER-NO-LOGIN", "!deleted", "", None, "$2b$12$short",
                                    b"$2b$", 12345, "$2b$12$" + "é" * 53])
def test_a_marker_where_a_hash_would_be_is_a_quiet_no(stored):
    assert sh.verify_secret("anything", stored) is False


def test_security_keeps_one_rule_and_the_name_older_recipes_call():
    from agentvault_registry import security

    secret, stored = PASSLIB_1_7_4["client_secret_74"]
    assert security.verify_password(secret, stored) is True
    assert security.verify_api_key(secret, stored) is True
    assert security.verify_recovery_key(*PASSLIB_1_7_4["recovery_key"]) is True
    assert security.verify_password(secret, "!deleted") is False
    h = security.pwd_context.hash("recipe-secret-0001")
    assert security.pwd_context.verify("recipe-secret-0001", h) is True
    assert security.verify_password("recipe-secret-0001", security.hash_password("recipe-secret-0001")) is True


SRC = pathlib.Path(sh.__file__).resolve().parents[1]


def test_nothing_imports_passlib_and_only_secret_hash_calls_bcrypt():
    offenders, seen = [], 0
    for path in sorted(SRC.rglob("*.py")):
        seen += 1
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root == "passlib" or (root == "bcrypt" and path.name != "secret_hash.py"):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno} {name}")
    assert seen > 300, f"only {seen} source files seen: the scan is not looking at the package"
    assert offenders == []


def _pins(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", line.strip())
        if m:
            out[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return out


def test_the_image_set_carries_bcrypt_5_and_no_passlib():
    here = os.path.dirname(os.path.abspath(__file__))
    for root in (os.path.join(here, ".."), "/app"):
        con = os.path.join(root, "constraints-network.txt")
        if os.path.isfile(con):
            break
    else:
        pytest.skip("constraints-network.txt is not beside the tests here")
    pins = _pins(con)
    assert len(pins) >= 100
    assert "passlib" not in pins
    assert pins.get("bcrypt", "").startswith("5."), pins.get("bcrypt")
