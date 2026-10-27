# TheProtocol registry card, version 0.6

Version 0.6, 30 September 2026, revised 16 October 2026

This specification is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Copyright 2025-2026 Raphael Zbigniew Jeziorny.

## Conformance

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and OPTIONAL in this document are to be interpreted as described in RFC 2119. A conforming registry serves a card that meets every requirement in section 10. A conforming verifier implements the verification procedure of section 7.4 and the digest check of section 5.4. The companion JSON Schema, `registry-card-v0.6.schema.json` (JSON Schema draft 2020-12), checks the fields, their types and most value ranges; the signature, the digests and the entity tag are defined only in this text. Everything in this document that is not marked as a requirement, and every value described as the reference implementation's, is informative.

## 1. Overview

A registry card is to a federation registry what an A2A agent card is to an agent: a self-describing public JSON document that a registry serves about itself, signed with Ed25519, which any participant can fetch, verify, cache and display.

Terms used in this document:

- **Registry**: a server that hosts agent identities and agent cards and takes part in a federation.
- **Trust domain**: the SPIFFE trust domain a registry belongs to. Peers prove it to each other with mutual TLS.
- **Frame**: a registry with its own trust domain, its own ledger and its own unit, named by a short code (for example `ECU`).
- **Operator registry** (cloud operator): a registry hosted under a frame. It shares the frame's trust domain and settles through the frame's ledger.
- **Operator**: the person or organization that runs a registry. The `operator` block describes them, and the editable parts of a card are theirs to state.
- **Peer**: another registry that this registry federates with.
- **Verifier**: any party that checks a card's signature and digests.

Version 0.6 adds the `compliance` block and covers it by one signed digest (section 5). The set of signed paths can grow without a new version string, because a verifier reads the list of signed paths from the card it verifies (section 7); two such additions were made within version 0.6 (`identity.did_namespace` and the three `federation.licence` leaves).

## 2. Endpoints

A registry serves these paths at the root of its public origin, without a prefix. None of them requires authentication.

| Path | Method | Content |
|---|---|---|
| `/.well-known/registry-card.json` | GET | The card (sections 3 to 7). |
| `/.well-known/registry-jwks.json` | GET | The public keys that verify the card signature, beside other public keys of the registry (section 7.6). This is the only location of the card keys. |
| `/.well-known/registry-card-schema.json` | GET | A JSON Schema for version 0.6 cards (see below). |
| `/api/v1/jurisdiction/authorizations` | GET | `{"authorizations": [...], "count": n}`: the same list of live regulatory authorizations the card publishes (section 5.3), unsigned. |
| `/api/v1/jurisdiction/contracts/{cid}` | GET | The proof document for an attestation contract named by an authorization's `contract_ref` (section 5.6). |

Caching of the card:

- The response carries `ETag: "<lifecycle.card_etag>"` (the tag in double quotes) and `Cache-Control: public, max-age=300, stale-while-revalidate=600`.
- A request whose `If-None-Match` equals the current tag (quoted or unquoted) receives `304 Not Modified` with the same `ETag` and `Cache-Control` headers and no body.
- The tag a registry sends with a 304 MUST be identical to the `lifecycle.card_etag` it would embed in a full response at the same moment (section 8).

The reference implementation also sends an `X-Registry-Card-Version` header that repeats the card's `registry_card_version`.

The key set response is `{"keys": [...]}` with `Cache-Control: public, max-age=300, stale-while-revalidate=600`. The schema response carries `Cache-Control: public, max-age=3600`. The schema the reference implementation serves there is `registry-card-v0.6.schema.json` itself.

A registry MAY also serve a convenience envelope at `GET /api/v1/public/registry-card`, which returns its own card, or with `?peer=<name>` its cached copy of a peer's card, together with its own verdicts about that peer. Readers MUST NOT treat the envelope as a substitute for verifying the card it carries.

Operators edit the editable blocks through an administrative interface that this specification does not define.

## 3. Document structure

A card is a JSON object with these top-level keys. The reference implementation emits them in the order shown; key order carries no meaning.

| Key | Tier | Source | Signed |
|---|---|---|---|
| `registry_card_version` | MUST | constant `"0.6"` | yes |
| `identity` | MUST | derived, except `display_name` | seven leaves (section 4.1) |
| `operator` | SHOULD | editable | `latitude`, `longitude` |
| `description` | SHOULD | editable | yes |
| `tags` | SHOULD | editable | no |
| `visual` | SHOULD | editable | `sovereign_variant` |
| `capabilities` | SHOULD | derived | the whole block |
| `fees` | MUST | derived | seven leaves (section 4.6) |
| `federation` | MUST | derived | six leaves (section 4.7) |
| `policy` | SHOULD | derived | no |
| `economic` | MAY | derived | no, and excluded from the entity tag |
| `stats` | MAY | derived | no, and excluded from the entity tag |
| `endpoints` | SHOULD | derived | no |
| `links` | SHOULD | editable | no |
| `commitments` | SHOULD | editable | no |
| `lifecycle` | MUST | derived | `card_etag` |
| `compliance` | MAY | derived | `digest` (section 5) |
| `signature` | MUST when a signing key exists | derived | not applicable |

"Derived" means the registry computes the value from its own state; the operator cannot set it. "Editable" means the operator states it.

A minimal conforming card carries the MUST keys only. A card MUST NOT contain keys that this specification does not define, except inside `endpoints` and `federation.licence` (with the objects within it), whose shapes are open.

## 4. Blocks

Types below use JSON terms. "Timestamp" means an ISO 8601 date-time string with a UTC offset. "URL" means an absolute `http` or `https` URL unless stated otherwise. A field shown as nullable MAY be `null`.

### 4.1 `identity` (MUST)

| Field | Type | Required | Signed | Meaning |
|---|---|---|---|---|
| `spiffe_id` | string, starts with `spiffe://`, at most 512 characters | yes | yes | The registry's SPIFFE ID, of the form `spiffe://<trust_domain>/registry/<name>`. |
| `registry_name` | string, 1 to 128 characters | yes | yes | The registry's federation name. |
| `display_name` | string, 1 to 128 characters | yes | no | Human-readable name: the operator's stated name, or else `registry_name`. |
| `trust_domain` | string, 3 to 255 characters | yes | yes | The registry's SPIFFE trust domain. |
| `did_namespace` | string or null, at most 63 characters | no | yes | The issuer segment of the agent DIDs this registry issues (`did:theprotocol:<did_namespace>:<uuid>`). See below. |
| `public_url` | URL, at most 500 characters | yes | yes | The registry's browser-reachable public base URL. |
| `federation_base_url` | URL or null | no | no | The public address peers dial for mutually authenticated federation calls. |
| `founded_at` | timestamp | yes | no | When the registry came into being. The reference implementation publishes the creation time of the registry's first account. |
| `tier` | enum | yes | yes | The registry's role, below. |
| `software_version` | string or null, at most 64 characters | no | yes | The release tag the registry reports for the software it runs. |

`tier` values:

- `sovereign-mainframe`: a frame that declares itself a central registry. It has its own trust domain and ledger and issues its own unit.
- `regional-mainframe`: a frame registry that is not a central registry.
- `cloud-operator`: an operator registry hosted under a frame.
- `sandbox`: a test registry.
- `standalone`: a registry configured to run without federation.

`did_namespace` rules:

- A registry that issues agent DIDs with an issuer segment MUST publish that segment here, and it MUST equal the registry's `trust_domain`. A registry that issues DIDs without an issuer segment omits the key.
- The value MUST match `^[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?$` (so it has at most 63 characters) and MUST NOT be one of the reserved second segments of system DIDs: `operator`, `cloud`, `org`, `agora-gateway`, `developer`, `api-tester`, `system`, `teg`, `treasury`, `gateway`, `fx`, `fee`, `fee_collector`, `admin`, `registry`, `frame`, `template`.
- A receiver refuses a card whose `did_namespace` is malformed or reserved (`did_namespace_invalid`), differs from the card's own `trust_domain` or from the trust domain the peer proved over mutual TLS (`did_namespace_mismatch`), or equals the receiver's own namespace (`did_namespace_self`). The last check does not apply to a frame receiving the card of one of its own operator registries, or to an operator registry receiving its own frame's card, because they share one trust domain by design; the receiver decides that from its own record of the peer, never from the card.

### 4.2 `operator` (SHOULD)

The operator's persona. All fields are editable. `display_name` (string, 1 to 128 characters) is required when the block is present. Until the operator edits the block, the reference implementation takes `display_name` and `bio` from an administrator account of the registry; whenever the block has no `operator_since`, it publishes that account's creation time; and when the operator states no location, it takes `latitude`, `longitude` and `location_label` from that account's profile.

| Field | Type | Meaning |
|---|---|---|
| `display_name` | string | Operator name. |
| `bio` | string or null, at most 2000 characters | Short biography. |
| `company` | string or null, at most 256 characters | Company. |
| `url` | URL or null | Operator web site. |
| `github_url` | string or null, starts with `https://github.com/` | Source profile. |
| `twitter_handle` | string or null, pattern `^@?[A-Za-z0-9_]{1,15}$` | Social handle. |
| `timezone` | string or null | Time zone name. |
| `location_label` | string or null | Human-readable location. |
| `operator_since` | timestamp or null | Since when the operator runs the registry. |
| `operator_avatar_url` | string or null | Avatar. MUST be a same-origin path beginning `/static/`; a registry MUST NOT publish an external image link here. |
| `contact_email` | string or null | Contact address. Opt-in: omitted unless the operator explicitly sets it. A role address is RECOMMENDED. |
| `successor_contact` | string or null | Who to contact if the operator is unreachable. |
| `support_contact` | object or null | `{email, matrix, signal}`, each a string or null. |
| `latitude` | number or null, -90 to 90 | SIGNED. Location of the registry for map placement. |
| `longitude` | number or null, -180 to 180 | SIGNED. |

### 4.3 `description` and `tags` (SHOULD)

`description` is a string of at most 2000 characters and is SIGNED. `tags` is an array of at most 20 strings of at most 48 characters each.

### 4.4 `visual` (SHOULD)

Display styling, editable by the operator: `icon_url` (a same-origin `/static/` path, a URL, or null), `orb_color` and `orb_glow_color` (`#rrggbb`), `orb_pulse_speed_hz` (0.5 to 3.0), `orb_size_px` (integer, 10 to 24), `halo_enabled` (boolean), `halo_thickness` (0.5 to 2.5), `theme` (`neural`, `sovereign` or `custom`), `sovereign_variant` (string or null, SIGNED), `flare_corner_variant`, `flare_encirclement_variant` and `flare_encirclement_overlay` (strings or null).

The variant fields name display styles from a renderer's catalog. Visual styling is not identity: any registry may use any known style, and a receiver MUST NOT treat styling as evidence of identity. A receiver MAY drop a `sovereign_variant` it does not know and use the operator default styling instead. A receiver MAY check the three `flare_` fields against its catalog of known styles and refuse a card that names an unknown one. `flare_encirclement_overlay` MUST NOT be set unless `flare_encirclement_variant` is set. A receiver refuses a card whose `orb_color` or `orb_glow_color` is not `#rrggbb`.

### 4.5 `capabilities` (SHOULD, signed as a whole block)

| Field | Type | Meaning |
|---|---|---|
| `federation_enabled` | boolean | The registry federates. |
| `fiat_onramp_enabled` | boolean | Whether the registry's fiat purchase lane is switched on. It is off on the EU and ASIA frames. |
| `fiat_providers` | array of `stripe`, `mollie` | Payment providers of the fiat purchase lane; empty while it is off. |
| `minting_capability` | `sovereign` or `disabled` | `sovereign` for a central registry, which issues its own unit; `disabled` otherwise. The schema also admits the older values `genesis_only` and `limited`. |
| `bridge_capability` | `none`, `frame_to_frame` or `multi_frame` | Cross-frame bridging. The reference implementation publishes `frame_to_frame` when the registry federates and serves its wrapped-unit bridge (its `TOKEN_BRIDGE_ENABLED` setting, reported as `token_bridge_enabled` in `/api/v1/public/registry-config`), and `none` otherwise. |
| `a2a_versions_supported` | array of strings | A2A protocol versions, for example `["1.0"]`. |
| `registry_card_versions_served` | array of strings | A version 0.6 registry MUST include `"0.6"`. |
| `supports_payment_protocol` | array of strings | Payment protocols; `a2a-payment-v1` names the A2A payment extension (see `a2a-payment-extension-v1.md`). |
| `zkp_phases_enabled` | array of integers | Zero-knowledge attestation phases the registry has enabled (numbering defined by the implementation). |

The block lists capabilities that matter to peers and buyers. It MUST NOT carry internal configuration toggles. Because the whole block is signed, every value in it is covered by the card signature.

### 4.6 `fees` (MUST)

Required keys: `intra_registry`, `cross_registry`, `hosting`, `fee_collector_address`, `settlement_currency`.

| Field | Type | Signed | Meaning |
|---|---|---|---|
| `intra_registry` | object | no | Fee on transfers inside the registry: `base_rate_percent`, `max_rate_percent` (0 to 100), `velocity_scaling_factor` (at least 0), `destination` (string), `customizable` and `locked_by_network` (booleans). The reference implementation publishes the base and maximum rates its fee service charges, read from the registry's policy document. |
| `cross_registry.base_rate_percent` | number, 0 to 100 | yes | Fee on cross-registry transfers (0.5 in the reference implementation). |
| `cross_registry` (other fields) | | no | `fee_recipient` (for example `receiver_registry`), `customizable`, `locked_by_network`, and `future_customization_in_bounded_params` (`[min, max]` or null: the range the rate may move within if operators may customize it). |
| `hosting.enabled` | boolean | yes | Whether the registry charges a hosting fee on agent service fees. The reference implementation publishes `false`. |
| `hosting.rate_percent_of_agent_service_fee` | number, 0 to 100 | yes | The hosting fee as a percentage of an agent's service fee (0.0 in the reference implementation). |
| `hosting` (other fields) | | no | `min_avt` (decimal string), `applies_to_agent_dids` (array of DIDs, or null for all agents), `description`. |
| `fee_collector_address` | string | no | The ledger account that collects fees. |
| `fee_waterfall_policy` | string or null | no | How collected fees are paid out again. The reference implementation publishes `fee_collector → treasury`: its funding waterfall pays from the fee account first and from the treasury for the rest, by default. |
| `settlement_currency` | string, pattern `^[A-Z]{2,8}$` | yes | The code of the unit this registry settles in: its frame's unit (`ECU` on the EU frame). The reference implementation reads it from its `FRAME_CURRENCY` setting. |
| `economic_disclosure` | object | no | `spec_version`, `fee_floor_avt` (decimal string: the smallest fee a transfer is charged; the reference implementation publishes `"0"`, no minimum, under a key named after the former network's unit), `rounding` (`ROUND_HALF_EVEN`, `ROUND_HALF_UP` or `ROUND_DOWN`), `fees_emit_event_types` (ledger event types that record fees). |
| `fx.enabled` | boolean | yes | Whether this registry converts units between frames (FX). |
| `fx` (other fields) | | no | See below. |
| `exchange.enabled` | boolean | yes | Whether this registry hosts an AGORA market. |
| `exchange.stock_card.digest` | string or null, pattern `^sha256:[0-9a-f]{64}$` | yes | Digest of the market's catalog, see below. |
| `exchange` (other fields) | | no | See below. |

`fx` (conversion of units between frames). When `enabled` is false the block is `{"enabled": false, "route_enabled": <boolean>}`, plus `route_gateway_registry_id` when `route_enabled` is true (the registry routes conversions through that gateway registry). When `enabled` is true it also carries `currency`, `rate_mode` (`fixed` or `pool`), `fee_pct`, `fee_split` (`pool_retained_pct`, `fee_collector_pct`), `size_cap` and `reserve_floor` (objects mapping a unit code to a number; a cap of 0 means uncapped), `slippage_max`, `breaker_pct` and `note`. The unsigned `fx` fields are informative and apply to conversions this registry hosts as the destination. The reference implementation publishes in `size_cap` and `reserve_floor` its frame's own unit (0 when unset) and every other unit code its settings `FX_SIZE_CAP_<CODE>` and `FX_RESERVE_FLOOR_<CODE>` name: the codes its conversion engine applies a cap or a floor to.

`exchange` (the AGORA market of organisation points). When `enabled` is false the block is `{"enabled": false, "passport_enabled": <boolean>}`. When true it also carries `currency`, `endpoints` (`listings`, `order`, `passport_inbound`: paths), `fee_bps_default` (integer basis points, 0 to 10000), `note`, and, when the registry publishes them, two pointers:

- `stock_card`: `url` (`/.well-known/stock-card.json`, an older name of `/.well-known/agora-card.json`; both serve the same document), `digest` (SIGNED), `count`, `updated_at`, and optionally `market_epoch` and `market_freshness`. The digest covers the catalog only, not live market fields, so trades do not change it.
- `solvency_card`: `url` (`/.well-known/solvency-card.json`), `digest`, `as_of`, `epoch`, `count`, `freshness`. UNSIGNED. `epoch` is a coarse five-minute bucket.

`passport_enabled` says whether the registry takes part in the passport: it relays its own agents' orders to markets on other registries and, when it hosts a market, accepts the orders that other registries relay for their agents. It is published also when the registry hosts no market. The documents behind the two pointers are outside this specification.

### 4.7 `federation` (MUST)

Required keys: `protocol_version`, `supported_auth_methods`, `policy_hash`, `is_genesis_registry`, `is_sovereign_frame`, `active_peer_count`.

| Field | Type | Signed | Meaning |
|---|---|---|---|
| `protocol_version` | string | no | Federation protocol version, for example `"1.0"`. |
| `supported_auth_methods` | array of strings | no | For example `["mtls", "jwt_svid", "federation_license"]`. |
| `trust_domains_accepted` | array of strings, sorted | no | Trust domains of the registry's active peers. |
| `spire_bundle_endpoint` | URL or null | no | Where the registry's SPIFFE trust bundle can be read, as configured; null when none is configured. |
| `policy_hash` | string or null, at most 80 characters | yes | `sha256:` followed by the lowercase hex SHA-256 of the canonical JSON (section 6) of the registry's resolved policy document: its stored policy merged onto the shipped defaults. The registry's policy compliance endpoint publishes the same hash without the prefix, to peer registries. |
| `policy_version` | integer, at least 0 | no | Version of the registry's policy document. 0 means never amended. |
| `policy_updated_at` | timestamp or null | no | When the policy document last changed. |
| `policy_source` | `factory_default` or `amended` | no | Whether `policy_hash` describes the shipped defaults or an amended document. `factory_default` means never amended, not unknown. |
| `is_genesis_registry` | boolean | yes | True when the registry is a central registry with authority to issue its unit. |
| `is_sovereign_frame` | boolean | yes | True when `identity.tier` is `sovereign-mainframe`. |
| `uptime_started_at` | timestamp or null | no | A start date the registry is configured with. When none is configured, the reference implementation publishes when the registry came into being (the creation time of its first account, as `identity.founded_at`), or null on a registry with no account. Either way this field is not a measurement of uptime. |
| `active_peer_count` | integer, at least 0 | no | Number of active peers. Volatile, so excluded from the entity tag. |
| `trusted_peer_spiffe_ids` | array of strings, sorted | no | The peer roster. Published only when the operator opts in; omitted by default. The reference implementation lists at most 64. |
| `license_id`, `license_status` | string or null | no | Identifier and status of a legacy admission licence, if any. Not the signed network licence. |
| `licence` | object | three leaves | The signed network licence, below. |

`federation.licence` is derived from the licence certificates the registry holds; the operator cannot set it. It is absent when the registry has no network configured, its licensing is off and it holds no licence, so such a card is identical to one produced by software that predates licensing. Its fields and the certificate format are defined in `federation-licence-certificate-v1.md`. In summary: `state` (the registry's own reading of its licence), `hash` (SHA-256 of the certificate), `network`, `issuer`, `plan`, `expires_at`, `certificate` (the compact JWS), `chain` (at most two certificates), `checked_at` and `reason`; a frame adds `key` (its licence-signing public key) and `operator_policy`; an operator registry adds `operator`, its own licence. The signed leaves are `federation.licence.state`, `federation.licence.hash` and `federation.licence.operator.hash`. A verifier MUST check the certificate itself and MUST NOT rely on the `state` a card states about itself.

### 4.8 `policy` (SHOULD)

The registry's declared policy posture and the network constants it is pinned to.

| Field | Type | Meaning |
|---|---|---|
| `locked_params_hash` | string or null | `sha256:` followed by the hex SHA-256 of the canonical JSON of the network's locked parameters. |
| `policy_source` | `factory_default` or `amended` | As in `federation.policy_source`. |
| `policy_version` | integer, at least 0 | Equal to `federation.policy_version`. |
| `declared_params` | object | For each bounded parameter: `{value, source, allowed}`. `value` is the value the registry applies (number, string or boolean). `source` is `policy` when the registry set it and `default` when it is the shipped default. `allowed`, present when the network bounds the parameter, is `{min, max}` (numbers or null), the range the network permits. |
| `bounded_params` | object | The same keys as `declared_params`, flattened to `{key: value}`, kept for readers of earlier card versions. |
| `policy_modified_at` | timestamp or null | OPTIONAL. |
| `drift_status` | `compliant`, `drift_detected`, `quarantined` or `unknown` | Present only when derived from a real compliance state; otherwise omitted. |
| `consul_compliance_state` | `active`, `stale`, `quarantined` or `unknown` | Present only when truthfully derived; otherwise omitted. |

The reference implementation declares these bounded parameters: `transaction_fees.base_rate_percent`, `transaction_fees.max_rate_percent`, `transaction_fees.velocity_scaling_factor`, `staking_rewards.max_apy_percent`, `enforcement.reputation_bond_min_avt`, `enforcement.bond_maturity_min_age_days`, `governance.standard_quorum_percent`, `governance.standard_pass_percent`. The parameter names contain dots but are single object keys. It leaves out a parameter that has no value, and `staking_rewards.max_apy_percent` while `STAKING_REWARDS_ENABLED` or `STAKING_ENABLED` is off, as on the EU and ASIA frames. It does not publish `policy_modified_at`, `drift_status` or `consul_compliance_state`.

A registry MUST publish the values it actually applies. It MUST NOT publish a placeholder, such as the lower bound of a permitted range, as if it were the applied value.

### 4.9 `economic` (MAY)

Supply facts about the registry's ledger. The block is unsigned and excluded from the entity tag. A registry MUST NOT fabricate values: it publishes a measured value or omits it.

| Field | Type | Meaning |
|---|---|---|
| `supply_invariant_status` | `OK`, `BREACH`, `FEDERATED` or `UNKNOWN` | The supply invariant verdict. `FEDERATED` means the registry issues no units of its own: its supply is issued and audited at its frame. |
| `supply_invariant_delta` | string | The invariant delta. Absent when the supply could not be read. |
| `supply_last_audited_at` | timestamp or null | Time of the verdict, when the source states one. The reference implementation's own ledger read states none, so the field is null with `supply_source` `eventstore`. |
| `tokens_issued`, `total_circulating`, `tokens_destroyed`, `tokens_fees_collected` | decimal string or null | The supply terms (null on a `FEDERATED` or an `UNKNOWN` block). |
| `supply_source` | `auditor` or `eventstore` | Whether the numbers come from an external auditor or from the registry's own ledger read. Absent on `FEDERATED` blocks and when no source answered. |
| `supply_note` | string or null | Explanation, present on `FEDERATED` blocks. |
| `external_auditor_endpoint` | URL or null | The external auditor that attests this registry's supply. A registry MUST NOT name an auditor that its operator has not configured. |

When the reference implementation cannot read its supply on a registry other than a federated operator registry (which publishes `FEDERATED`), it publishes the block as `UNKNOWN`, with null in each supply term and no delta.

The supply invariant and its attestation are specified in `supply-audit-standard-v1.0.md`.

### 4.10 `stats` (MAY)

Counts, unsigned and excluded from the entity tag: `agent_count`, `native_agent_count`, `federated_agent_count`, `sovereign_agent_count`, `developer_count`, `active_peers` (integers, at least 0) and `computed_at` (timestamp). A registry MUST publish only counts it actually computes.

In the reference implementation `agent_count` counts the registry's agent records, while `native_agent_count` and `federated_agent_count` split the agent cards it holds by whether a card came from another registry. The two are counted from different records, so their sum need not equal `agent_count`. `sovereign_agent_count` counts agents whose flare tier is `sovereign`, `developer_count` the registry's own developer accounts and `active_peers` its active peers.

### 4.11 `endpoints` (SHOULD)

A catalog of paths the registry serves to readers and peers. The shape is open. It MUST NOT list administrative paths. The reference implementation publishes `openapi_spec` (`/api/v1/openapi.json`), `agent_discovery`, `agent_card_well_known` (null: a registry serves no agent card of its own; agents publish theirs on their own hosts), `topology`, `network_stats`, `federation_info`, `policy_compliance` (it answers only authenticated peer registries), `health_check`, `registry_card` (`/.well-known/registry-card.json`), `registry_jwks` (`/.well-known/registry-jwks.json`), `spire_bundle` (the configured address of the registry's SPIFFE bundle endpoint, or null), `fee_config`, `external_auditor` (URL or null) and `public_status_page` (URL or null).

### 4.12 `links` (SHOULD)

Optional URLs stated by the operator, each a URL or null: `whitepaper`, `docs`, `github_source`, `status_page`, `blog`, `rss`, `terms_of_service`, `privacy_policy`, `code_of_conduct`, `support_url`, `discord`, `matrix`, `incident_log`.

### 4.13 `commitments` (SHOULD)

Operator-stated service levels and legal statements:

| Field | Type |
|---|---|
| `data_residency` | string or null, at most 32 characters |
| `gdpr_compliant` | boolean |
| `incident_disclosure_sla_hours` | integer, 1 to 720 |
| `uptime_sla_pct` | number, 0 to 100 |
| `support_response_hours` | integer, 1 to 720 |
| `deprecation_notice_days` | integer, 0 to 365 |
| `open_source_license` | string or null, at most 64 characters |
| `breach_disclosure_policy` | string or null, at most 500 characters |
| `key_rotation_max_days` | integer, 1 to 365 |
| `card_refresh_max_minutes` | integer, 1 to 60 |
| `legally_binding_disclaimer` | string or null, at most 1000 characters |

`open_source_license` states the licence of the software the registry runs. When the operator leaves it empty, the reference implementation fills in the licence of its own code, `AGPL-3.0-or-later`; an operator's own value is kept.

When the operator has stated no commitments at all, the reference implementation publishes a default set (for example `uptime_sla_pct` 99.0, `incident_disclosure_sla_hours` 72 and a standard disclaimer) that the operator did not state. Once the operator saves the block, it carries only what the operator set.

### 4.14 `lifecycle` (MUST)

| Field | Type | Signed | Meaning |
|---|---|---|---|
| `status` | `active`, `degraded`, `quarantined` or `retiring` | no | Registry status. |
| `quarantine_reason` | string or null | no | Why the registry is quarantined. |
| `card_updated_at` | timestamp | no | Time of the operator's last edit; before any edit, `identity.founded_at`. |
| `card_etag` | string, at most 80 characters | yes | The entity tag, section 8. |
| `served_at` | timestamp | no | When this copy was produced. |
| `next_card_refresh` | timestamp or null | no | When a reader should fetch again (the reference implementation uses five minutes after `served_at`). |

The reference implementation always publishes `status` `active` with a null `quarantine_reason`.

## 5. The `compliance` block (MAY)

### 5.1 Absence rule

The `compliance` key MUST be absent when the registry has declared no jurisdiction profile and holds no live regulatory authorization. It MUST NOT be an empty object or null in that case: a registry that has declared nothing must not publish a compliance shape that implies it has. Receivers show no compliance information for a card without the key.

The legal shapes are:

| Situation | `compliance` |
|---|---|
| No profile, no live authorizations | absent |
| Profile declared, no live authorizations | `{jurisdiction_profile, digest}` |
| No profile, live authorizations | `{regulatory_authorizations, digest}` |
| Both | `{jurisdiction_profile, regulatory_authorizations, digest}` |

`digest` MUST be present whenever the block is present.

### 5.2 `compliance.jurisdiction_profile`

The operator's own declaration of which feature surfaces the law applicable to it permits. A registry MUST build this block from its current declaration (not from a stale cache), because the card is the public attestation of it.

| Field | Type | Meaning |
|---|---|---|
| `name` | string, 1 to 120 characters | Profile name. |
| `version` | integer, at least 1 | Profile version. |
| `features_denied` | array of unique strings, sorted | The features the profile denies. Vocabulary: `exchange` (orders on the AGORA market and purchases from a launch allocation), `fx` (conversion of units between frames), `guild` (posting funded work tasks), `forge` (evaluation arena runs), `fiat` (the fiat purchase lane), `cross_transfer` (cross-registry transfers). An absent profile allows everything; a feature a declared profile does not name stays allowed. |
| `declared_at` | timestamp or null | When the profile was declared. |
| `profile_hash` | string, pattern `^sha256:[0-9a-f]{64}$` | `sha256:` followed by the hex SHA-256 of the canonical JSON of the full profile document. The full document can carry private fields, so readers treat this value as an opaque commitment. |
| `declared_by` | `"operator"` | Constant. |
| `regulated_actions` | object | OPTIONAL. Present only when the profile declares acts that require a state authorization. |

`regulated_actions` maps an action to `{authority, scope, mode}`, with keys sorted. Private notes the operator keeps with a declaration MUST NOT be published.

- Actions (closed vocabulary): `exchange.listing` (approving a listing), `exchange.ipo` (opening a launch allocation), `fiat.lane` (the fiat purchase lane), `registry.operation` (the deployment's own operating licence). `registry.operation` is displayed only and never gates anything, because gating a deployment's own operating licence would freeze the deployment that declares it. A registry MUST refuse to record an action outside this vocabulary.
- `authority`: the state body that grants the authorization (string, 1 to 120 characters, or null).
- `scope`: `registry` or `per_subject`. Defaults: `exchange.listing` and `exchange.ipo` default to `per_subject`; `fiat.lane` and `registry.operation` default to `registry`. For an entry declared without a scope, the reference implementation publishes the action's default, the scope its gate applies.
- `mode`: `shadow` (default) or `enforce`. With `shadow` the registry records that an act lacked a covering authorization and lets it proceed. With `enforce` the registry refuses the act until a live authorization covers it. An entry's `enforce` applies even when the registry's global jurisdiction mode is `shadow`; a registry whose global jurisdiction mode is off gates nothing.

### 5.3 `compliance.regulatory_authorizations`

Every live authorization the registry has recorded, in its public shape. An authorization is live when its status is active, `valid_from` is at or before now, and `valid_until` is null or after now. Liveness is recomputed at every build, never stored. The list is published even when no profile is declared, because a recorded authorization is an attestation in its own right. It MUST be sorted by the tuple (`action`, `subject_ref` or the empty string, `reference_id`).

| Field | Type | Meaning |
|---|---|---|
| `action` | one of the four actions | The act authorized. |
| `subject_ref` | string or null, at most 255 characters | The subject for a `per_subject` authorization; null means registry-wide. |
| `authority` | string, 1 to 200 characters | The granting body, as attested by the operator. |
| `jurisdiction` | string, 1 to 120 characters | Jurisdiction. |
| `reference_id` | string, 1 to 255 characters | The authority's own reference. Public on purpose: a false reference is provable misrepresentation. |
| `valid_from` | timestamp | Start of validity. |
| `valid_until` | timestamp or null | End of validity; null means open-ended. |
| `evidence_hash` | string or null, pattern `^sha256:[0-9a-f]{64}$` | Hash of the evidence the operator holds. |
| `contract_ref` | string or null, at most 255 characters | The identifier of a countersigned attestation contract (section 5.6). |
| `contract_digest` | string, pattern `^sha256:[0-9a-f]{64}$` | Present only when earned (section 5.6); otherwise the key is omitted. |

A registry MUST NOT publish internal fields of an authorization record (its record identifier, its status and liveness flag, the identity of whoever recorded it, evidence notes, the method by which the recorder proved presence, and its creation and revocation data). Revocation changes the record's status only; a renewal is a new record.

The registry does not verify a state's stamp. The operator attests the authorization, with the operator's liability behind it; the claim is public and signed.

### 5.4 `compliance.digest`

```
digest = "sha256:" + lowercase_hex(SHA-256(canonical_json(compliance without the "digest" key)))
```

The canonical JSON is defined in section 6 and applies recursively, so the nested objects of `regulated_actions` and each authorization are sorted too.

A verifier recomputes the digest from the card it received: take the `compliance` object, remove `digest`, serialize canonically, hash, and compare with `digest`. `compliance.digest` is a signed leaf (section 7), so a verifier that checks both the signature and the digest has verified the whole block. A verifier that skips the recomputation has only verified that nobody changed the digest, not that nobody changed the block.

Signing one scalar leaf whose value is itself a hash keeps the signature independent of how implementations re-serialize a nested block: the signature check and the digest check are separate, independently testable steps, and editing any byte of the block changes the recomputed digest. The same pattern covers the AGORA catalog through `fees.exchange.stock_card.digest`.

When a card carries no `compliance` block, the signed leaf `compliance.digest` resolves to null, exactly like any other absent optional leaf. The digest alone therefore cannot distinguish a card that never had a block from one whose block was deleted; the signed entity tag does, because its basis includes the compliance state (section 8).

### 5.5 Worked example

Illustrative values:

```json
"compliance": {
  "jurisdiction_profile": {
    "name": "example-provider-no-fiat",
    "version": 3,
    "features_denied": ["fiat"],
    "declared_at": "2026-09-01T12:00:00+00:00",
    "profile_hash": "sha256:<64 lowercase hex digits>",
    "declared_by": "operator",
    "regulated_actions": {
      "exchange.ipo": {"authority": "Example Markets Authority", "scope": "per_subject", "mode": "shadow"},
      "fiat.lane": {"authority": "Example Markets Authority", "scope": "registry", "mode": "enforce"}
    }
  },
  "regulatory_authorizations": [
    {
      "action": "fiat.lane",
      "subject_ref": null,
      "authority": "Example Markets Authority",
      "jurisdiction": "Example",
      "reference_id": "EX-2026/0001",
      "valid_from": "2026-09-01T12:00:00+00:00",
      "valid_until": "2027-09-01T12:00:00+00:00",
      "evidence_hash": "sha256:<64 lowercase hex digits>",
      "contract_ref": null
    }
  ],
  "digest": "sha256:<64 lowercase hex digits>"
}
```

### 5.6 Attestation contracts

An authorization MAY name, in `contract_ref`, a countersigned contract between the parties that attests it. The registry adds `contract_digest` to the published authorization only when that contract is attestation-grade: it exists on the registry, its status is `agreed`, and its total amount is zero. Otherwise the key is omitted, so the card never claims what the proof endpoint would refuse.

`GET /api/v1/jurisdiction/contracts/{cid}` is the proof endpoint:

- `404` unless at least one live authorization references the contract.
- `409` when a live authorization references a contract that is missing, not zero-value, or not agreed; the body names the problem.
- `200` with `{"contract": <subset>, "digest": "sha256:...", "status": "agreed", "authorization_references": [<reference_id>, ...]}` otherwise.

The subset contains the contract's immutable fields only: `id`, `title`, `contract_type`, `total_amount` (as a string), `client_did`, `provider_did`, `terms`, `created_at`, `agreed_at` (timestamps). `status` is excluded so the digest is stable from the moment of agreement. `digest` and `contract_digest` are `"sha256:" + lowercase_hex(SHA-256(canonical_json(subset)))`. The title, parties and terms of a referenced contract are public: countersigning an attestation publishes it.

## 6. Canonical JSON

Signatures, digests and the entity tag of this specification use one canonical JSON form. It is the UTF-8 text that Python's `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` produces:

- Object keys are sorted by Unicode code point, at every level.
- There is no whitespace outside strings: `,` separates members and elements, `:` separates a key from its value.
- Strings use `\"` and `\\`; the control characters U+0008, U+0009, U+000A, U+000C and U+000D use `\b`, `\t`, `\n`, `\f` and `\r`; every other character below U+0020 and every character from U+007F upward is written as `\u` followed by four lowercase hex digits, with characters above U+FFFF written as a UTF-16 surrogate pair. `/` is not escaped.
- `true`, `false` and `null` are written as such.
- Numbers are written as Python writes them: an integer in plain decimal; a float in the shortest form that reads back to the same value, which keeps `.0` on a float with no fractional part (`0.0`, `1.0`) and uses Python's exponent form for very large or very small magnitudes (for example `1e-07`, `1e+16`).

A verifier in another language MUST reproduce this form byte for byte. In particular it MUST keep the distinction between an integer and a float with no fractional part exactly as the card writes the number (`0` and `0.0` produce different bytes).

## 7. Signature

### 7.1 The signature block

```json
"signature": {
  "alg": "EdDSA",
  "kid": "spiffe://registry.example.org/registry/example-registry#1",
  "jwks_url": "/.well-known/registry-jwks.json",
  "signed_canonical": ["registry_card_version", "identity.spiffe_id", "..."],
  "signed_at": "2026-09-30T12:00:00.000000+00:00",
  "expires_at": "2026-09-30T13:00:00.000000+00:00",
  "value": "<base64url Ed25519 signature>"
}
```

| Field | Meaning |
|---|---|
| `alg` | `EdDSA` (Ed25519). |
| `kid` | `<identity.spiffe_id>#<rotation_seq>`. Selects the verification key. |
| `jwks_url` | Always `/.well-known/registry-jwks.json`. |
| `signed_canonical` | The dotted paths this signature covers. |
| `signed_at` | Signing time (timestamp). |
| `expires_at` | `signed_at` plus 3600 seconds. |
| `value` | The base64url encoding, without padding, of the 64-byte Ed25519 signature. |

`signature` MAY be null when the registry has no signing key available. A null signature is a legal wire shape but an unusable trust artifact.

### 7.2 Signed paths

A registry MUST declare in `signed_canonical` the list of paths it signs, and MUST sign exactly those paths. The reference implementation signs these 28 paths, in this order:

```
 1  registry_card_version
 2  identity.spiffe_id
 3  identity.registry_name
 4  identity.trust_domain
 5  identity.did_namespace
 6  identity.tier
 7  visual.sovereign_variant
 8  federation.is_genesis_registry
 9  federation.is_sovereign_frame
10  federation.policy_hash
11  fees.cross_registry.base_rate_percent
12  fees.hosting.enabled
13  fees.hosting.rate_percent_of_agent_service_fee
14  fees.settlement_currency
15  lifecycle.card_etag
16  identity.public_url
17  identity.software_version
18  operator.latitude
19  operator.longitude
20  capabilities
21  fees.exchange.enabled
22  fees.exchange.stock_card.digest
23  fees.fx.enabled
24  description
25  compliance.digest
26  federation.licence.state
27  federation.licence.hash
28  federation.licence.operator.hash
```

Every entry except `capabilities` is a single leaf; `capabilities` covers the whole block. Because the signed payload is an object keyed by path and is serialized with sorted keys (section 7.3), the order of the list does not change the bytes that are signed.

### 7.3 Signing

1. For each path in `signed_canonical`, resolve its value in the card: split the path on `.` and descend through objects by key. If a key is missing, or a step reaches a value that is not an object, the value is null. A path that resolves to null or is absent is still part of the payload, with the value null.
2. Build the payload object: each path string maps to its resolved value.
3. Add `"_signed_at"` and `"_expires_at"` with the string values of `signed_at` and `expires_at` from the signature block. The freshness window thus lives inside the signed payload but not in the card body, so it never changes the entity tag, and moving `expires_at` after signing breaks verification.
4. Serialize the payload as canonical JSON (section 6) and sign the resulting bytes with the registry's Ed25519 key.
5. Encode the 64-byte signature as base64url without padding into `value`.

The signature is a raw Ed25519 signature over those bytes; there is no JWS header and no JWS signing input.

### 7.4 Verification

1. Read the card's own `signature.signed_canonical`. A verifier MUST use this list and MUST NOT substitute a list of its own; this is what lets the signed set grow without breaking verifiers.
2. Resolve every declared path as in section 7.3 step 1, including paths that resolve to null, on the card exactly as received. A field that a receiver drops or rewrites later (section 9) is still part of this step.
3. Add `_signed_at` and `_expires_at` from the signature block, exactly as they appear there.
4. Serialize canonically (section 6).
5. Fetch `/.well-known/registry-jwks.json` from the registry and select the key whose `kid` equals `signature.kid`; it MUST be an Ed25519 key (`kty` `OKP`, `crv` `Ed25519`), because the key set can hold other keys (section 7.6). Verify the Ed25519 signature over the serialized bytes with that key.
6. Reject the signature if the current time is later than `expires_at`, even when the signature itself is valid.
7. If the card carries a `compliance` block, recompute its digest (section 5.4) and reject the card if it differs from `compliance.digest`.
8. If the card carries `federation.licence` with a `certificate`, check that `hash` equals the SHA-256 of the certificate, and evaluate the certificate itself as specified in `federation-licence-certificate-v1.md`.

The reference implementation's receiver runs steps 1 to 7 on every full response it receives from a peer, on the card as received; the copy it then stores has a `sovereign_variant` it does not know set to null (section 9). It checks the licence of step 8 in a separate licence check (section 9).

### 7.5 Freshness

A signature is valid for one hour after `signed_at`. A registry signs afresh on every full build (the reference implementation serves a built card for up to 30 seconds), so a fresh fetch carries a signature well inside its window, while a stale card replayed later is rejected.

Freshness is checked when a full card arrives. A `304 Not Modified` only confirms that a cached copy is still current, and the reference implementation keeps the verdict it reached when it last received the full card. Its receivers fetch the cards of the peers they reach directly once per federation sync cycle (the `FEDERATION_SYNC_INTERVAL_SECONDS` setting: 600 seconds by default, 30 in the frame and operator templates).

### 7.6 Keys and rotation

Each card signing key in `/.well-known/registry-jwks.json` is an Ed25519 public key in JWK form: `{"kty": "OKP", "crv": "Ed25519", "x": "<base64url public key>", "kid": "<spiffe_id>#<rotation_seq>", "alg": "EdDSA", "use": "sig"}`.

The first key has `rotation_seq` 1; each rotation adds one. After a rotation the previous key stays in the key set for a grace period of seven days, so cards signed shortly before the rotation remain verifiable.

The key set lists every key the registry has not expired: the current card key, earlier card keys inside their grace period, card keys under an earlier SPIFFE ID of the same registry (they keep no expiry, so what they signed stays verifiable), and keys the registry holds for other purposes, such as its web push key (an ES256 key on the P-256 curve, `kid` `webpush-vapid:self#1`) or the RSA key (RS256) it uses for OAuth federation. A verifier selects by `kid` and uses only an Ed25519 key.

## 8. Entity tag

`lifecycle.card_etag` is the card's entity tag. It is signed, and the HTTP `ETag` header carries the same value in double quotes.

The tag changes on operator edits and on changes to a small set of stable inputs. On a registry whose AGORA market publishes a `solvency_card` pointer or a `market_epoch` (section 4.6), it also changes with a coarse clock: the solvency epoch every five minutes, the market epoch every fifteen minutes by default. Such a card is therefore fetched again at that pace, never on every trade. Requirements:

- The tag MUST change when the operator edits the editable card data.
- The tag MUST change when a stable identity field (`spiffe_id`, `registry_name`, `trust_domain`, `tier`, `display_name`, `public_url`, `founded_at`, `did_namespace`), the policy hash or the fee commitments change.
- Declaring or changing a jurisdiction profile, and recording or revoking an authorization, MUST change the tag. Because the tag is signed, this is what protects the `compliance` block against deletion (section 5.4).
- A change of licence state or hash, of the network licence or of an operator registry's own licence, MUST change the tag, so a rotation, a revocation or a verdict change is never hidden behind a 304.
- The tag MUST NOT change with volatile data: the `economic` and `stats` blocks, `federation.active_peer_count`, the peer roster, and timestamps such as `served_at`.
- The tag a registry returns on the 304 path MUST equal the tag it embeds in a full build (section 2).

Consequently a reader that holds a copy with the current tag has current values for everything the tag covers; values outside it (for example `identity.software_version`) can be newer on the registry than in a cached copy.

Reference construction (informative): the tag is `"sha256:" + lowercase_hex(SHA-256(canonical_json(basis)))`, where `basis` is an object with a format discriminator `"v": "0.6"`, a builder revision number, the operator-editable card data, the stable identity subset (`spiffe_id`, `registry_name`, `trust_domain`, `tier`, `display_name`, `public_url`, `founded_at`, `did_namespace`, `federation_base_url`; `software_version` is deliberately excluded), the policy hash, the fee commitments, the `capabilities` block, the configured SPIFFE bundle endpoint, fingerprints of the FX and AGORA market settings together with the catalog digest, the coarse solvency epoch together with whether the market's escrow invariant holds, the coarse market epoch (never the live digests, which would force every peer to re-fetch on every trade), and two parts:

```
compliance part = profile_hash (or "") + "|ra:" + authorizations_digest (or "")
                  the empty string when there is neither a profile nor a live authorization
authorizations_digest = "sha256:" + lowercase_hex(SHA-256(canonical_json(regulatory_authorizations array)))

licence part = state + "|" + hash + "|" + operator.state + "|" + operator.hash
               each part empty when absent
```

## 9. Receiving a card

A receiver fetches a peer's card over the federation channel, conditionally with `If-None-Match`.

- A receiver SHOULD refuse a card body larger than 32 KiB, nested deeper than 8 levels, or containing any string value longer than 2048 characters. A registry MUST therefore keep its card within these limits.
- A receiver refuses a card without a string `registry_card_version` or without an `identity` object, with an `orb_color` or `orb_glow_color` that is not `#rrggbb`, or with an invalid `did_namespace` (section 4.1).
- A receiver verifies the signature (section 7.4) on the card as received and records whether it verified. A receiver MAY keep its previous copy of a peer's card rather than replace it with one that is unsigned or fails verification. The reference implementation stores such a card with its verdict, and keeps the previous copy instead only when its `FEDERATION_INGEST_FAIL_CLOSED` setting is on. Cards of registries it does not reach directly arrive relayed by a direct peer, and it stores them with that peer's verdict rather than one of its own.
- After verifying, a receiver MAY drop a `sovereign_variant` it cannot render, and MAY refuse a card that names a `flare_` variant outside its catalog (section 4.4).
- A receiver evaluates a peer's network licence from the certificate the card carries, not from the card's own `state` (see `federation-licence-certificate-v1.md`). The reference implementation records the licence as `invalid` when the card's signed `hash` does not match the certificate it carries.

## 10. Conformance requirements

A version 0.6 conforming registry:

1. Serves the MUST blocks at `/.well-known/registry-card.json` with a valid Ed25519 signature verifiable against `/.well-known/registry-jwks.json`.
2. Declares `registry_card_version: "0.6"` and includes `"0.6"` in `capabilities.registry_card_versions_served`.
3. Declares its signed paths in `signature.signed_canonical` and signs exactly those paths with the freshness window folded in (section 7.3).
4. Emits `compliance` only when a profile is declared or at least one live authorization exists, and always emits `compliance.digest` with the block.
5. Computes `compliance.digest` exactly as in section 5.4, so any third party can recompute it from the served card.
6. Publishes only the public fields of an authorization (section 5.3).
7. Omits `contract_digest` on any authorization whose `contract_ref` does not resolve to an attestation-grade contract.
8. Keeps the entity tag as specified in section 8, and keeps the 304 path and the embedded `lifecycle.card_etag` identical.
9. Contains no field outside this specification, except inside `endpoints` and `federation.licence`.
10. Publishes `identity.did_namespace` equal to its trust domain whenever it issues DIDs with an issuer segment.
11. Derives `federation.licence` from the certificates it holds and never from editable card data.

## Appendix A. Abbreviated example

Illustrative values; most blocks are omitted.

```json
{
  "registry_card_version": "0.6",
  "identity": {
    "spiffe_id": "spiffe://registry.example.org/registry/example-registry",
    "registry_name": "example-registry",
    "display_name": "Example Registry",
    "trust_domain": "registry.example.org",
    "public_url": "https://registry.example.org",
    "federation_base_url": "https://federation.registry.example.org",
    "founded_at": "2026-09-01T00:00:00+00:00",
    "tier": "sovereign-mainframe",
    "software_version": "<release tag>",
    "did_namespace": "registry.example.org"
  },
  "fees": {
    "intra_registry": {"base_rate_percent": 0.5, "max_rate_percent": 5.0, "velocity_scaling_factor": 1.0,
                       "destination": "treasury_recycle", "customizable": false, "locked_by_network": true},
    "cross_registry": {"base_rate_percent": 0.5, "fee_recipient": "receiver_registry",
                       "customizable": false, "locked_by_network": true},
    "hosting": {"enabled": false, "rate_percent_of_agent_service_fee": 0.0},
    "fee_collector_address": "teg:system:fee_collector",
    "settlement_currency": "EXU",
    "fx": {"enabled": false, "route_enabled": false},
    "exchange": {"enabled": false, "passport_enabled": false}
  },
  "federation": {
    "protocol_version": "1.0",
    "supported_auth_methods": ["mtls", "jwt_svid", "federation_license"],
    "policy_hash": "sha256:<64 lowercase hex digits>",
    "policy_version": 0,
    "policy_source": "factory_default",
    "is_genesis_registry": true,
    "is_sovereign_frame": true,
    "active_peer_count": 3
  },
  "lifecycle": {
    "status": "active",
    "quarantine_reason": null,
    "card_updated_at": "2026-09-20T09:30:00+00:00",
    "card_etag": "sha256:<64 lowercase hex digits>",
    "served_at": "2026-09-30T12:00:00+00:00",
    "next_card_refresh": "2026-09-30T12:05:00+00:00"
  },
  "signature": {
    "alg": "EdDSA",
    "kid": "spiffe://registry.example.org/registry/example-registry#1",
    "jwks_url": "/.well-known/registry-jwks.json",
    "signed_canonical": ["registry_card_version", "identity.spiffe_id", "identity.registry_name"],
    "signed_at": "2026-09-30T12:00:00+00:00",
    "expires_at": "2026-09-30T13:00:00+00:00",
    "value": "<base64url Ed25519 signature>"
  }
}
```

The `signed_canonical` list is shortened here; a real card lists every signed path (section 7.2). The unit code `EXU` stands for the example frame's own unit.
