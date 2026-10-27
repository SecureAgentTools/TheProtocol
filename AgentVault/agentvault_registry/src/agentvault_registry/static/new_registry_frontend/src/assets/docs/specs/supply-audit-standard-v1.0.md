# TheProtocol supply attestation standard (TPSA-1)

Version 1.0, 30 September 2026

This specification is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Copyright 2025-2026 Raphael Zbigniew Jeziorny.

## Conformance

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and OPTIONAL in this document are to be interpreted as described in RFC 2119. This standard has two conformance classes. A conforming **auditor** computes the invariant as in section 2, emits attestations as in sections 3 to 5, and serves the endpoints of section 10. A conforming **verifier** implements checks C1 to C6 of section 6 and MAY implement C7. Values described as the reference auditor's are informative.

## 1. Purpose

A supply auditor watches the ledger of a frame (a registry with its own ledger and unit) and states whether the frame's supply of units is conserved. TPSA-1 turns that verdict into a portable, signed and chained document. Anyone who holds an attestation and the auditor's public keys can verify, offline and at any later time, that the auditor stated this verdict, at this point in the frame's event stream, and that no later rewrite of the auditor's history touched it.

## 2. The invariant

For each frame, the auditor reads these terms in a single database statement. One statement is one snapshot, so a read skew between two queries cannot produce a false pass.

```
net_supply = tokens_issued - tokens_destroyed + transit_net
delta      = net_supply - total_circulating
```

- `tokens_issued`, `tokens_destroyed` and `transit_net` are the ledger's supply summary counters. In the reference ledger every balance change carries a kind: the kinds `mint` and `dispute_comp` add to `tokens_issued`, the kinds `slash` and `burn` add to `tokens_destroyed`, and every other kind (transfers, escrow legs, locks, fees, cross-frame legs, and a change with no kind) adds its signed net amount to `transit_net`.
- `total_circulating` is the sum of liquid plus locked balances over every account in the ledger's materialized balances, including the treasury and the fee collector.
- `as_of_event_seq` is the highest sequence number in the ledger's event log, read in the same statement. It pins the observation to a position in the immutable event stream.

The verdict `status` is `OK` when the absolute value of `delta` does not exceed the auditor's tolerance, and `BREACH` otherwise. The reference auditor's tolerance is 0.000001.

## 3. Attestations

### 3.1 Kinds

| Kind | Emitted |
|---|---|
| `audit` | once per audit cycle for each attested frame |
| `baseline_set` | when the auditor's administrator sets the native-supply baseline of a frame |
| `baseline_removed` | when that baseline is removed |
| `transit_rebaselined` | when the auditor's administrator moves the zero point of transit drift monitoring |
| `track_record` | once a day for each registry the auditor scores, when its track record is configured; each registry has a chain of its own, named `track_record:<registry>` |

`baseline_set`, `baseline_removed` and `transit_rebaselined` are provenance attestations: they give changes to the auditor's own reference points the same chain of custody as its verdicts. A `track_record` attestation carries the track record the auditor computed for one registry (its members belong to the track record, not to this standard) under the same signing and chaining rules; it makes no statement about the invariant.

### 3.2 The `audit` payload

| Member | Type | Meaning |
|---|---|---|
| `standard` | string | `"TPSA-1.0"`. |
| `kind` | string | `"audit"`. |
| `auditor_version` | string | The auditor software version. |
| `frame` | string | The auditor's identifier for the frame. |
| `currency` | string or null | The code of the frame's unit. |
| `ts` | timestamp | When the audit ran (ISO 8601 with UTC offset). |
| `audit_row_id` | integer | The auditor's own record identifier for the cycle. |
| `as_of_event_seq` | integer or null | The event stream position of the reading (section 2). |
| `terms` | object or null | `{"issued", "destroyed", "transit_net", "net_supply", "circulating"}`, numbers. |
| `delta` | number or null | `net_supply - circulating`. |
| `status` | `"OK"`, `"BREACH"` or null | The verdict (section 2). |
| `live_status` | string | The ledger's own verdict on its supply, read through its API in the same cycle (the reference ledger answers `OK` only for a delta of exactly zero); `status` when that read failed or was not made; `"ERROR"` when neither reading was possible. Informative only. |
| `maintenance` | boolean | True when a maintenance window was declared during the cycle. |
| `native` | object or null | The issuance-origin reconciliation: `ok` (boolean or null), `basis` (section 7), `gap` (number), `gap_rebased` (number or null). |
| `checks` | object | The verdicts of the secondary checks at the time of the cycle (section 7). |
| `prev_hash` | string | The chain link (section 5). |

`terms`, `delta`, `status` and `as_of_event_seq` are null when the auditor could not take the single-statement reading in that cycle. Such an attestation makes no statement about the invariant. `live_status` is a second reading, taken at another moment and judged by the ledger's own rule; it never replaces `status`.

A worked example (illustrative values):

```json
{
  "as_of_event_seq": 1048576,
  "audit_row_id": 52001,
  "auditor_version": "2.5.0-tpsa1",
  "checks": {"escrow": "OK", "per_user": "OK", "shares": "OK", "solvency": "SOLVENT", "staked_guard": "OK"},
  "currency": "ECU",
  "delta": 0.0,
  "frame": "example-frame",
  "kind": "audit",
  "live_status": "OK",
  "maintenance": false,
  "native": {"basis": "typed_mints_complete", "gap": 0.0, "gap_rebased": null, "ok": true},
  "prev_hash": "<64 lowercase hex digits: digest of the previous attestation>",
  "standard": "TPSA-1.0",
  "status": "OK",
  "terms": {"circulating": 1000012.25, "destroyed": 250.5, "issued": 1000250.5,
            "net_supply": 1000012.25, "transit_net": 12.25},
  "ts": "2026-09-30T12:00:00.000000+00:00"
}
```

### 3.3 Provenance payloads

`baseline_set` and `baseline_removed`:

| Member | Type | Meaning |
|---|---|---|
| `standard`, `kind`, `auditor_version`, `frame`, `ts` | as in section 3.2 | |
| `entry` | object or null | `{"baseline": <number greater than 0>, "set_at": <timestamp>, "ref": <string>}`; null for `baseline_removed`. |
| `ref` | string | The reason for the change. REQUIRED. |
| `rail` | string | `"admin/set-native-baseline"`. |
| `prev_hash` | string | The chain link. |

The native-supply baseline is a frozen, attested write-down figure against which the issuance-origin gap is reconciled (section 7, basis `writedown_rebaselined`).

`transit_rebaselined`:

| Member | Type | Meaning |
|---|---|---|
| `standard`, `kind`, `auditor_version`, `frame`, `ts` | as in section 3.2 | |
| `old_baseline` | number or null | The previous zero point. |
| `old_drift` | number or null | The drift measured against it. |
| `new_baseline` | number | The frame's current `transit_net`, which becomes the new zero point. |
| `ref` | string or null | The reason for the change. |
| `rail` | string | `"admin/rebaseline-transit"`. |
| `prev_hash` | string | The chain link. |

Moving the transit zero point changes only what the auditor's drift monitoring compares against; it does not touch the ledger.

### 3.4 The stored record

An auditor stores and serves each attestation as a record:

| Member | Meaning |
|---|---|
| `id` | Integer identifier, increasing, assigned by the auditor. |
| `frame` | The chain the record belongs to: the frame identifier, or `track_record:<registry>`. |
| `ts` | The attestation time. |
| `kind` | The kind. |
| `payload` | The exact signed string (section 4). |
| `digest` | Lowercase hex SHA-256 of `payload`. |
| `prev_hash` | A copy of the chain link for indexing; the authoritative copy is inside `payload`. |
| `signature` | Base64url (no padding) Ed25519 signature over `payload`. |
| `kid` | The identifier of the signing key. |

## 4. Canonicalization and signing

- **Canonical form.** The payload is the output of Python's `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`: object keys sorted by Unicode code point at every level; no whitespace outside strings; every character below U+0020 or from U+007F upward escaped (`\b`, `\t`, `\n`, `\f`, `\r` for those five control characters, otherwise `\u` with four lowercase hex digits, and a surrogate pair above U+FFFF); `"` and `\` escaped with a backslash. The payload is therefore pure ASCII.
- **Numbers.** Terms are IEEE 754 double-precision numbers written as Python writes floats: the shortest form that reads back to the same value, `.0` kept on whole values, Python's exponent notation for very large or very small magnitudes. Integers are written in plain decimal.
- **The stored payload is the signed bytes.** `digest` is the lowercase hex SHA-256 of the payload's bytes, and `signature` is the Ed25519 signature over the same bytes. A verifier never re-canonicalizes anything to check a signature. Re-canonicalization (parse, re-serialize, compare) is a separate check that proves the canonical form is real (C4).
- **Key.** The auditor signs with one Ed25519 key. Its `kid` is the first 16 characters of the lowercase hex SHA-256 of the raw 32-byte public key. The auditor MUST keep the key on durable storage: a key lost with a restart would silently re-key the chain.
- **Key set.** `GET /.well-known/auditor-jwks.json` returns `{"keys": [...]}`, each key `{"kty": "OKP", "crv": "Ed25519", "x": "<base64url public key>", "kid": "<kid>", "use": "sig", "alg": "EdDSA"}`. When the auditor has no signing key it answers 503 with `{"keys": []}`.
- **Rotation.** After a rotation the key set MUST contain the current key and every retired key, so every earlier attestation stays verifiable.

## 5. The chain

Each frame has its own chain, and so has each registry's track record. `prev_hash` is the `digest` of the chain's previous attestation, of any kind, or the empty string for the chain's first attestation. Because `prev_hash` is inside the signed payload, the chain itself is signed. Records are append-only; rewriting any stored attestation breaks every later link, visibly.

- An auditor MUST serialize emission per chain (read the chain head, sign, store), so that two attestations never name the same predecessor.
- Chain heads SHOULD be anchored outside the auditor's host at regular intervals, so that copies exist that the auditor's host can no longer rewrite. The reference deployment publishes chain heads once a day to a notification topic on the auditor's own host, and that publication does not cover the production frames' chains. A consumer who needs a copy the auditor's host cannot rewrite keeps its own: it reads `GET /api/auditor/attestations/head` (section 10) on its own schedule.

## 6. Verification

Offline, with the attestations and the key set only:

- **C1.** Fetch the key set; select the key whose `kid` equals the record's `kid`.
- **C2.** The lowercase hex SHA-256 of `payload` equals `digest`.
- **C3.** The Ed25519 signature verifies over the exact `payload` bytes.
- **C4.** Parsing `payload` and re-serializing it in the canonical form gives identical bytes.
- **C5.** `prev_hash` inside the payload equals the `digest` of the chain's previous attestation.
- **C6.** When `terms` and `delta` are not null: `issued - destroyed + transit_net` equals `net_supply`, and that value minus `circulating` equals `delta`, each within 0.001. The tolerance exists because the auditor computes `delta` from exact decimal values before the terms are converted to doubles individually, so the last unit in the last place can differ.

Live, with read access to the frame's ledger:

- **C7.** Run the single-statement reading of section 2 independently. The absolute value of `delta` is at most 0.01 at the time of the check, and the ledger's current `as_of_event_seq` is at least the attested one.

C7 reproduces the method, not the attested snapshot: the terms come from mutable projections (section 9).

Checks C1 to C3 and C5 need only the public endpoints and run in a web browser with WebCrypto.

## 7. Verdict vocabulary

`status` answers the conservation question: `OK` means the invariant held at the attested snapshot, and `BREACH` means it did not. No secondary check softens or overrides it.

`native.basis` states how far the issuance-origin check can be trusted:

| Basis | Claims | Does not claim |
|---|---|---|
| `typed_mints_complete` | every unit on the books has a typed issuance event behind it | (nothing excluded) |
| `writedown_rebaselined` | the gap reconciles against a frozen, provenance-attested write-down baseline; `gap_rebased` is the live figure | that the raw gap is meaningful on its own |
| `federated_reconciled` | the gap is explained by the balances held at federated operator registries | point-in-time exactness under live flow |
| `pre_baseline_genesis` | nothing: issuance predates the window in which issuances can be re-derived; `ok` is null | any statement about total issuance; the raw gap is an artifact, not a finding |
| `coverage_unknown` | nothing | anything |

`checks` carries the secondary checks of the cycle, each a verdict string, or null when the check was not made. The reference auditor reports:

| Check | Values | Meaning |
|---|---|---|
| `per_user` | `OK`, `BREACH` | No account holds a negative liquid or locked balance beyond a small tolerance (0.01 in the reference auditor). A negative balance the balance service has not caught up on yet (for up to 15 minutes), or a residue of an account the balance service does not hold, is reported apart and is not a breach. |
| `staked_guard` | `OK`, `MISMATCH`, `BREACH` | Locked balances agree between the ledger and the balance service; `BREACH` when the difference is at least a tenth of the locked amount (the reference threshold). |
| `escrow` | `OK`, `BREACH`, `ERROR` | The exchange escrow account holds what the open exchange obligations require. |
| `shares` | `OK`, `BREACH` | Each AGORA listing's organisation points are conserved: holders together hold no more than the listing's total, no holding or lock is negative, no holder has more locked than held, and no more of the launch allocation was sold than offered. The check keeps its code name; the reference auditor re-reads the points at most every 5 minutes. |
| `solvency` | `SOLVENT`, `LOW`, `BREACH` | The reserve the frame holds for exchanges between its unit and other frames' units stands above its floor: `BREACH` below the floor, `LOW` below one and a half times the floor. |

## 8. Liveness

- The reference auditor starts each audit cycle 60 seconds after the previous one ends.
- A consumer SHOULD treat a chain head older than 10 minutes as unwatched, not as still fine. The absence of a fresh attestation is itself a signal.

## 9. Trust model and limits

1. **The terms are projection-derived.** The supply summary and the materialized balances are mutable state. A verifier can verify the document forever and reproduce the method live, but cannot re-fold the projection at a past `as_of_event_seq`. Recomputation from individual events is a candidate for a later version.
2. **Storage integrity.** The auditor trusts the integrity of the ledger's database storage. A coordinated rewrite of the ledger's tables is out of scope; the chain and its anchors make after-the-fact rewrites of the auditor's own history visible, not rewrites of the ledger.
3. **Co-location.** An auditor that runs on the host it audits shares that host's fate: a full compromise of the host takes witness and suspect together. Anchoring mitigates detection; an auditor on a separate host reading a replica is the structural fix.
4. **What is attested.** An auditor MUST NOT attest a frame for which it cannot take the single-statement reading itself (for example, a frame it can read only through public endpoints); that frame's own auditor keeps that chain. An auditor MAY exclude test frames that are deliberately offline, which would otherwise fill the chain with error verdicts.
5. **Float profile.** Terms are IEEE 754 doubles. A verifier must either reproduce Python's number formatting (C4) or verify the stored bytes only (C2, C3).

## 10. Endpoints

| Path | Response |
|---|---|
| `GET /.well-known/auditor-jwks.json` | The key set (section 4). |
| `GET /api/auditor/attestations?frame=&limit=&before_id=` | `{"attestations": [<records, newest first>], "standard": "TPSA-1.0", "kid": "<current kid or null>"}`. `frame` filters by chain (a frame identifier, or `track_record:<registry>`); `limit` is 1 to 200 (default 50); `before_id` returns records with a smaller `id`. Each record carries its `payload`. |
| `GET /api/auditor/attestations/head?frame=` | The chain head: `{"id", "frame", "ts", "kind", "digest", "kid"}`, or 404 with `{"error": "..."}` when the frame has no attestation. |
| `GET /api/auditor/attestations/{id}` | One record, or 404. |

The operations that change a baseline are authenticated administrative operations of the auditor. Their interface is not part of this standard; their effect on the chain is (section 3.3).

## 11. Versioning

Every payload carries `standard`. Adding fields is a minor version change. Any change to the canonicalization, the signing, the chain semantics or the invariant formula is a major version change and requires a new specification.
