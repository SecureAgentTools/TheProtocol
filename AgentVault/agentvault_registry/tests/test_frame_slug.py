"""§FRAMEKIT P3.1 (2026-09-12) — the ONE rule for a frame's own container prefix (core/frame_slug.py).

"Sandbox Alpha" slugified to sandbox-alpha while every container of that frame is sbx-alpha-*: its own
Mission Control read its TEG and Event Store as DOWN for nine days while Prometheus scraped both as up.
"""
from agentvault_registry.core.frame_slug import frame_slug, slugify


def test_slug_is_read_from_the_teg_url_the_provisioner_wrote():
    assert frame_slug({"TEG_LAYER_URL": "http://sbx-alpha-teg:8080", "REGISTRY_NAME": "Sandbox Alpha"}) == "sbx-alpha"
    assert frame_slug({"TEG_LAYER_URL": "http://eu-teg:8080", "REGISTRY_NAME": "EU"}) == "eu"
    assert frame_slug({"TEG_LAYER_URL": "https://juice-teg:8080/", "REGISTRY_NAME": "Juice"}) == "juice"


def test_display_name_is_the_fallback_when_no_frame_teg_is_named():
    # Frame A and every operator name their TEG `teg-layer`: no prefix to read, the display name decides
    assert frame_slug({"TEG_LAYER_URL": "http://teg-layer:8080", "REGISTRY_NAME": "Hetzner Frame"}) == "hetzner-frame"
    assert frame_slug({"REGISTRY_NAME": "Frame-C"}) == "frame-c"
    assert frame_slug({}) == ""                       # Frame A: no name at all, the caller's own branch
    assert frame_slug({"TEG_LAYER_URL": "not a url", "REGISTRY_NAME": "X Y"}) == "x-y"


def test_slugify_matches_the_stack_health_rule():
    assert slugify("Sandbox Alpha") == "sandbox-alpha" and slugify("  EU ") == "eu" and slugify("") == ""


def test_slug_is_read_from_the_teg_gateway_url_too():
    # §MTLSHOPS T2 (agentvault2-b5): the TEG listens on its socket and the registry dials https://<slug>-nginx-teg:8443;
    # the old `^(.+)-teg$` read that host as "<slug>-nginx"
    assert frame_slug({"TEG_LAYER_URL": "https://sbx-alpha-nginx-teg:8443", "REGISTRY_NAME": "Sandbox Alpha"}) == "sbx-alpha"
    assert frame_slug({"TEG_LAYER_URL": "https://lantern-nginx-teg:8443", "REGISTRY_NAME": "Lantern Cooperative"}) == "lantern"
    assert frame_slug({"TEG_LAYER_URL": "http://sbx-alpha-teg:8080", "REGISTRY_NAME": "Sandbox Alpha"}) == "sbx-alpha"
