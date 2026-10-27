# A2A v1.0 schema provenance (§AGENTDISC #189, 2026-08-16)

- **Normative source:** the Linux Foundation A2A project pivoted its machine-readable
  source of truth to protobuf at v1.0. `a2a_v1.0.1.proto` here is a byte-exact copy of
  `specification/a2a.proto` at tag `v1.0.1` of https://github.com/a2aproject/A2A
  (sha256 `e195bf96ab630c69797851970203e1b2b6b19528f2e9803b7d904b91a5104016`,
  retrieved 2026-08-16).
- **`agent_card_v1.schema.json`** is hand-encoded field-for-field from that proto:
  JSON names via proto3 json_name convention (snake_case → camelCase),
  `required[]` = exactly the fields annotated `(google.api.field_behavior) = REQUIRED`,
  `minItems: 1` on REQUIRED repeated fields. The upstream repo generates JSON schema
  via `scripts/proto_to_json_schema.sh` (protoc + bufbuild protoc-gen-jsonschema); we
  do not vendor that Go toolchain — the proto sits beside the schema so any future
  session can diff a new tag against it and regenerate by hand or by their pipeline.
- **Deliberate divergence:** `additionalProperties: true` everywhere. The fleet keeps
  v0.3 sibling fields during the transition (`compat.py` Q5) and the vendor-extension
  philosophy tolerates additive data. The CI gate (`.forgejo/checks/a2a_schema_gate.py`)
  REPORTS strict extras; it gates only on missing REQUIREDs and wrong types.
- **Upgrade procedure:** fetch the new tag's `specification/a2a.proto`, diff against
  the vendored copy, update the schema + this file (new sha256 + tag), rerun the gate.
