"""§DEPS 2a (2026-09-29, his words "we need to do this ... spire->"refrain from others list"->..."): every compose a frame or
an operator is born from runs Postgres 18 in the 18 image's layout (contract rule R39).

postgres:18 keeps PGDATA in /var/lib/postgresql/18/docker and refuses to start when it sees a 16-style mount (measured on
18.6-alpine: exit 1 with a volume at /var/lib/postgresql/data, empty or holding a 16 cluster), so under
`restart: unless-stopped` an image-only bump is a crash loop on every new frame and operator. The TLS sync script that
fronts a frame's and an operator's DB reads the postmaster pid to SIGHUP the server after an SVID rotation: from the 16
path on 18 it finds nothing and the server keeps its old certificate until it expires. Each control below builds a text
that must fail, and fails for the reason it names.
"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("frame_template_contract_r39", ROOT / ".forgejo" / "checks" / "frame_template_contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

DIST = ROOT / "scripts" / "distribution"
FILES = {
    "docker-compose.frame-test.yml.tmpl": ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl",
    "nginx-templates/docker-compose.operator.yml": DIST / "nginx-templates" / "docker-compose.operator.yml",
    "docker-compose.standalone.yml (kit)": DIST / "docker-compose.standalone.yml",
    "kit/data-tls/pg-tls-sync.sh": ROOT / "templates" / "frame-test" / "kit" / "data-tls" / "pg-tls-sync.sh",
    "nginx-templates/pg-tls-sync.sh": DIST / "nginx-templates" / "pg-tls-sync.sh",
}

GOOD = """services:
  db:
    image: postgres:18.6-alpine
    environment:
      POSTGRES_DB: agentvault_registry
      POSTGRES_USER: registry
    volumes:
      - registry-data:/var/lib/postgresql
  # a comment between services never ends a block
  teg-db:
    image: postgres:16.15-alpine
    volumes:
      - teg-data:/var/lib/postgresql/data

volumes:
  registry-data:
  teg-data:
"""


def _one(text):
    return contract.pg_layout_contract({"c.yml": text})


def test_every_carrier_a_frame_or_operator_is_born_from_holds_the_18_layout():
    assert contract.pg_layout_contract({k: p.read_text(encoding="utf-8") for k, p in FILES.items()}) == []


def test_the_good_shape_passes_and_a_16_service_on_the_old_path_is_left_alone():
    assert _one(GOOD) == []


def test_an_image_only_bump_is_refused():
    bad = GOOD.replace("      - registry-data:/var/lib/postgresql\n", "      - registry-data:/var/lib/postgresql/data\n")
    out = _one(bad)
    assert len(out) == 1 and "db runs postgres 18 with its volume at /var/lib/postgresql/data" in out[0], out


def test_an_18_service_with_no_volume_at_the_new_root_is_refused():
    bad = GOOD.replace("      - registry-data:/var/lib/postgresql\n", "      - registry-data:/srv/pg\n")
    out = _one(bad)
    assert len(out) == 1 and "mounts no volume at /var/lib/postgresql" in out[0], out


def test_the_16_neighbour_turning_18_on_its_old_path_is_refused_too():
    bad = GOOD.replace("    image: postgres:16.15-alpine\n", "    image: postgres:18.6-alpine\n")
    out = _one(bad)
    assert len(out) == 1 and "teg-db runs postgres 18" in out[0], out


def test_an_18_init_with_md5_passwords_is_refused():
    bad = GOOD.replace("      POSTGRES_USER: registry\n", "      POSTGRES_USER: registry\n      POSTGRES_HOST_AUTH_METHOD: md5\n"
                                                       "      POSTGRES_INITDB_ARGS: --auth-host=md5\n")
    out = _one(bad)
    assert len(out) == 1 and "inits md5 passwords" in out[0], out


def test_a_digest_pinned_18_image_is_read_as_18():
    bad = GOOD.replace("    image: postgres:18.6-alpine\n", "    image: postgres:18.6-alpine@sha256:" + "0" * 64 + "\n") \
              .replace("      - registry-data:/var/lib/postgresql\n", "      - registry-data:/var/lib/postgresql/data\n")
    assert len(_one(bad)) == 1


def test_the_tls_sync_script_must_read_the_pid_through_pgdata():
    old = 'pid=$(head -1 /var/lib/postgresql/data/postmaster.pid 2>/dev/null)\n'
    new = 'pid=$(head -1 "${PGDATA:-/var/lib/postgresql/data}/postmaster.pid" 2>/dev/null)\n'
    assert contract.pg_layout_contract({"s.sh": new}) == []
    out = contract.pg_layout_contract({"s.sh": old})
    assert len(out) == 1 and "read ${PGDATA}" in out[0], out


def test_a_missing_carrier_is_named_not_passed():
    assert contract.pg_layout_contract({"gone.yml": ""}) == ["gone.yml: missing"]
