"""§pass51 — Bundles feature service package.

Submodules:
  - signing: per-developer Ed25519 keypair + JWS sign/verify + JWKS export
  - storage: BundleStorage Protocol + LocalBundleStorage impl
  - format: tar.gz pack/unpack, manifest.json + README.md generation
  - service: orchestrates create/restore/list/delete operations
  - reserved: reserved-slug + reserved-name-prefix policy
"""
