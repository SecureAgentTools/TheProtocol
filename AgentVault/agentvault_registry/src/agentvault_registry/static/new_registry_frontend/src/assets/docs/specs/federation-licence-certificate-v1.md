# TheProtocol federation licence certificate, version 1

Version 1, 30 September 2026

This specification is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Copyright 2025-2026 Raphael Zbigniew Jeziorny.

## Conformance

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and OPTIONAL in this document are to be interpreted as described in RFC 2119. This specification has three conformance classes. A conforming **issuer** signs certificates as specified in sections 2 and 4 and publishes its issued list as specified in section 5. A conforming **holder** (a registry that holds a licence) installs and publishes its certificate as specified in sections 4.6, 4.7 and 7. A conforming **verifier** implements section 6. Values described as the reference implementation's are informative.

## 1. Model

Terms: a **registry** is a server that hosts agent identities and takes part in a federation, and publishes a signed registry card (`registry-card-v0.6.md`). A **frame** is a registry with its own SPIFFE trust domain, ledger and unit. An **operator** (operator registry) is a registry hosted under a frame, sharing the frame's trust domain. The **genesis** is the frame whose self-signed certificate is the root of a network.

The software of a TheProtocol registry is free to run. Membership in a federation network is licensed. A registry without a licence keeps working, including with its own operators; what it cannot do, in a network that enforces licences, is federate across trust domains.

- **The unit is the trust domain.** A licence belongs to a SPIFFE trust domain. A frame and its operators share one trust domain. A call between two trust domains (a crossing) needs a licence chained to the network's genesis on both sides; inside one trust domain nothing is checked. An operator therefore rides its frame's network licence.
- **The chain.** The network's **genesis** holds a self-signed root certificate; the hash of that certificate identifies the network. The genesis signs a certificate for each **frame**, which carries the frame's own licence-signing public key. A frame signs certificates for its own **operators**, under its own operator policy.
- **Issuer-signed, not self-declared.** A value a registry derives about itself is only as honest as the software it runs, and anyone may run modified software. A licence is therefore a certificate signed by its issuer, which anyone can check against the chain without trusting the registry that shows it. The registry card publishes the certificate's hash as a signed leaf, which binds the card to exactly one certificate.
- **A separate key.** The licence-signing key is not the key that signs the registry card. The card key rotates with a short grace period; a certificate must outlive that.
- **Revocation by list.** Every issuer publishes a signed list of the certificates it issued and their states. A certificate counts as licensed only while its issuer's list, fetched recently enough, says it is active.

On the public network (informative): the genesis is EU, trust domain `eu.theprotocol.cloud`. The hash of its genesis certificate, which a registry may pin (section 6.2), is `e83551e2b8adbf7ed702ca6976e05862e1c9e8a9c8eec0d837a93e569f429901`, and `https://eu.theprotocol.cloud/.well-known/federation-licence.json` serves the certificate itself. EU and ASIA, the two production frames, run in `enforce` mode (section 6.7).

## 2. Certificate format

### 2.1 Encoding

A certificate is a JSON Web Signature in compact serialization (RFC 7515) using EdDSA with Ed25519 (RFC 8037):

```
BASE64URL(header) "." BASE64URL(payload) "." BASE64URL(signature)
```

Base64url is used without padding. The signature is the 64-byte Ed25519 signature over the ASCII signing input, the first two segments joined by `.`. The reference issuer encodes the header and the payload as JSON with object keys sorted and no whitespace, in UTF-8 without escaping non-ASCII characters. A verifier MUST verify over the segments exactly as received and MUST NOT re-encode them.

### 2.2 Header

```json
{"alg": "EdDSA", "kid": "<thumbprint of the signing key>", "typ": "tp-licence+jws"}
```

- `alg` MUST be `EdDSA`. A verifier MUST reject any other value.
- `kid` is the RFC 7638 JWK thumbprint of the signer's Ed25519 public key: the base64url (no padding) SHA-256 of the JSON `{"crv":"Ed25519","kty":"OKP","x":"<x>"}` with members in that order and no whitespace. When `kid` is present, a verifier MUST reject the signature unless `kid` equals the thumbprint of the key it verifies with.
- `typ` is `tp-licence+jws` for a certificate and `tp-licence-list+jws` for an issued list (section 5).

### 2.3 Payload

| Member | Type | Presence | Meaning |
|---|---|---|---|
| `kind` | string | REQUIRED | `tp.federation.licence.v1`. |
| `lid` | string | REQUIRED | Licence identifier, unique per issuer (a UUID in the reference issuer). |
| `type` | string | REQUIRED | `genesis`, `frame` or `operator`. |
| `sub` | object | REQUIRED | The licensee, below. |
| `iss` | object | REQUIRED | The issuer, below. |
| `network` | string or null | REQUIRED | The trust domain of the network's genesis. Null only on an operator certificate issued by a frame that holds no network certificate. |
| `plan` | string | REQUIRED | The plan (section 3). Pattern `^[a-z0-9][a-z0-9-]{0,39}$`. |
| `terms` | string | REQUIRED | The version of the terms under which the certificate was issued, at most 32 characters (for example `fot-2.2`). |
| `iat` | integer | REQUIRED | Issue time, seconds since the Unix epoch. |
| `exp` | integer or null | REQUIRED | Expiry time, seconds since the Unix epoch. Null means perpetual. |
| `key` | object | REQUIRED for `genesis` and `frame`, absent for `operator` | The licensee's licence-signing public key: `{"kty": "OKP", "crv": "Ed25519", "x": "<base64url public key>"}`. For a genesis certificate this is the genesis's own key. |

`sub` members:

- `trust_domain` (REQUIRED): the licensee's trust domain, lowercase, without a `spiffe://` prefix, matching `^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$` (at least two labels).
- `name` (REQUIRED): the licensee's public name, at most 255 characters.
- `url` (OPTIONAL): the licensee's public URL, at most 500 characters.
- `spiffe` (OPTIONAL): the licensee's SPIFFE ID, at most 255 characters.

Absent optional members are omitted, not written as null.

`iss` members, all REQUIRED:

- `trust_domain`: the issuer's trust domain.
- `name`: the issuer's public name, at most 255 characters.
- `kid`: the thumbprint of the issuer's licence-signing key.
- `licence`: the hash (section 2.4) of the issuer's own network certificate, or null for a genesis certificate and for an issuer that holds none.

Trust domains are compared after normalization: lowercase, any `spiffe://` prefix removed, leading and trailing `/` removed.

### 2.4 Licence hash

```
licence hash = lowercase_hex(SHA-256(ASCII bytes of the compact JWS, surrounding whitespace removed))
```

The hash is the value a registry card shows (`federation.licence.hash`), an issued list names, and a certificate's `iss.licence` refers to.

### 2.5 Size limits

- An issuer MUST refuse to issue a certificate whose compact JWS would be 2000 characters or longer. The certificate travels on the holder's registry card, and receivers refuse a card that contains any string longer than 2048 characters.
- A verifier refuses to parse a certificate longer than 16384 characters or an issued list longer than 8388608 characters (8 MiB). The list limit is much larger because a list grows with every certificate the issuer ever signed.

### 2.6 Example

A frame certificate, decoded (illustrative values):

```json
{"alg": "EdDSA", "kid": "<thumbprint of the genesis key>", "typ": "tp-licence+jws"}
```

```json
{
  "exp": null,
  "iat": 1790000000,
  "iss": {
    "kid": "<thumbprint of the genesis key>",
    "licence": "<64 hex digits: hash of the genesis certificate>",
    "name": "Example Genesis",
    "trust_domain": "genesis.example.org"
  },
  "key": {"crv": "Ed25519", "kty": "OKP", "x": "<base64url public key of the frame>"},
  "kind": "tp.federation.licence.v1",
  "lid": "<uuid>",
  "network": "genesis.example.org",
  "plan": "research",
  "sub": {"name": "Example Frame", "trust_domain": "frame.example.net", "url": "https://frame.example.net"},
  "terms": "fot-2.2",
  "type": "frame"
}
```

## 3. Plans

| Plan | Default term | Issued by | Intended for |
|---|---|---|---|
| `genesis` | perpetual | the genesis, to itself | the network's root |
| `founding` | perpetual | the genesis | frames that existed when licensing began |
| `private` | perpetual | the genesis | frames run by a person |
| `educational` | perpetual | the genesis | frames run by a school or university |
| `research` | perpetual | the genesis | frames run by a research group |
| `non-profit` | perpetual | the genesis | frames run by a non-profit organization |
| `enterprise` | 365 days | the genesis | frames run by a company |
| `government` | 365 days | the genesis | frames run by a public body |
| operator plans | the frame's policy | the operator's frame | the frame's operators |

- A frame certificate MUST carry one of the frame plans (every plan above except `genesis` and operator plans).
- Each frame defines its own operator policy: a plan name (the reference default is `operator-free`) and a term in days (the reference default is perpetual).
- An issuer MAY set a term other than the plan's default when it issues (the reference issuer accepts 1 to 3650 days).
- Prices and commercial conditions are not part of the certificate. The certificate carries the plan, the expiry and the terms version, so a later change of terms is a renewal, not a change of format.

## 4. Issuance

### 4.1 Licence-signing keys

A registry that issues certificates, or that holds a frame certificate, has an Ed25519 licence-signing key, distinct from its card-signing key. Its `kid` is the thumbprint of section 2.2. A registry MUST keep the private half confidential (the reference implementation stores it encrypted at rest). A frame publishes the public half in its registry card (`federation.licence.key`) and at `/.well-known/federation-licence.json`, which is where a genesis reads it to issue the frame's certificate.

### 4.2 The genesis certificate

- Only the registry whose trust domain is the network's genesis issues it, to itself, once. An issuer MUST refuse to issue a second genesis certificate; a second one would split the network.
- `type` `genesis`; `sub` names the genesis (trust domain, name, url); `iss` names the genesis with `licence` null; `network` is the genesis's own trust domain; `plan` `genesis`; `exp` null; `key` is the genesis's licence-signing public key.
- The certificate is signed with that same key (it is self-signed).
- Registries in the network SHOULD pin the hash of the genesis certificate.

### 4.3 Frame certificates

- Only the genesis issues frame certificates, and only once it holds its genesis certificate.
- `sub.trust_domain` MUST differ from the genesis's own trust domain.
- `plan` MUST be a frame plan (section 3).
- `key` MUST be the frame's licence-signing public key, a valid Ed25519 JWK.
- `iss.licence` is the hash of the genesis certificate; `network` is the genesis's trust domain.
- `exp` is `iat` plus the term, or null for a perpetual plan.

### 4.4 Operator certificates

- A frame issues operator certificates for operators in its own trust domain only: `sub.trust_domain` MUST equal the frame's trust domain.
- The frame signs them with its licence-signing key.
- `plan` and the term come from the frame's operator policy unless stated at issue.
- `iss.licence` is the hash of the frame's own network certificate, and `network` is that certificate's `network`; both are null when the frame holds no network certificate.
- An operator certificate carries no `key`.
- An operator certificate keeps the values of the moment it was issued: one issued before its frame held a network certificate carries a null `iss.licence` and `network` for its whole life. The verdict of section 6.4 depends on neither.

### 4.5 One live licence per subject

A subject is a frame (identified by its trust domain) or an operator (identified by its frame's trust domain and its name). When an issuer issues a new frame or operator certificate, it MUST mark every older certificate it issued to the same subject that is `active` or `suspended` as `superseded`. Otherwise revoking the current certificate would leave an older, still active one licensing the subject.

### 4.6 Installing a frame certificate

A frame receives its certificate and the chain from the genesis, either with a federation invitation or out of band. The frame MUST refuse to install the certificate unless:

1. its `type` is `frame` and its `sub.trust_domain` is the frame's own trust domain;
2. its `key` has the same thumbprint as the frame's own licence-signing key;
3. the first certificate of the chain passes root verification (section 6.2) for the frame's configured network, including the pinned hash when one is configured; and
4. the certificate's signature verifies with the key of that root.

A delivered chain MUST NOT introduce a root. The channel that delivers a certificate does not necessarily prove that the genesis sent it, so:

- a frame that already trusts a root refuses a chain whose root differs from it, unless the new root matches the pinned hash;
- a frame that trusts no root yet accepts the chain's root only when it matches the pinned hash; otherwise it installs the certificate with the state `unverified` and waits until it has fetched the root from the genesis itself over mutual TLS (section 6.2).

### 4.7 Operator licences over mutual TLS

An operator obtains its licence from its frame:

```
GET /api/v1/federation/licence/mine          (mutual TLS, on the frame)
```

- The frame identifies the caller by its SPIFFE ID, which MUST begin with `spiffe://<frame trust domain>/operator/<name>`, with `<name>` of 1 to 120 characters from `A-Z a-z 0-9 . _ -`; further path segments may follow (an operator registry provisioned by the reference implementation presents `spiffe://<frame trust domain>/operator/<name>/registry`). Any other caller is refused with 403.
- A frame whose licensing mode is off answers 409 and issues nothing.
- When the operator holds no live certificate and the frame's policy issues automatically (the reference default), the frame issues one on this request.

The response:

```json
{
  "operator": {"certificate": "<compact JWS>", "hash": "<hex>", "state": "active", "issued_now": true},
  "network": {"certificate": "<compact JWS>", "chain": ["<genesis certificate>"], "hash": "<hex>",
              "state": "licensed", "reason": "...", "checked_at": "<timestamp>"},
  "root": {"certificate": "<compact JWS>", "hash": "<hex>"},
  "policy": {"plan": "operator-free", "days": null},
  "frame_trust_domain": "frame.example.net"
}
```

`operator`, `network` and `root` are null when the frame has none to give. `network.state` is the frame's own verdict about its network licence (`genesis` when the frame is the genesis).

The operator then:

- verifies the root (section 6.2) and trusts it only if it passes;
- stores the frame's network certificate, refusing one whose `sub.trust_domain` is not the operator's trust domain, with the frame's verdict as its state, since the operator has no other way to reach that verdict; and
- evaluates its own certificate as specified in section 6.4, taking the state the frame reports for it as the frame's list entry.

## 5. The issued list and revocation

### 5.1 The list

Every issuer publishes a signed list of every certificate it has issued. The list is a compact JWS (section 2.1) with the header `{"alg": "EdDSA", "kid": "<issuer key thumbprint>", "typ": "tp-licence-list+jws"}` and this payload:

```json
{
  "kind": "tp.federation.licence-list.v1",
  "issuer": {"trust_domain": "genesis.example.org", "name": "Example Genesis", "kid": "<thumbprint>"},
  "generated_at": 1790000000,
  "licences": [
    {"hash": "<hex>", "lid": "<uuid>", "type": "frame", "sub_trust_domain": "frame.example.net",
     "sub_name": "Example Frame", "plan": "research", "iat": 1790000000, "exp": null,
     "state": "active", "updated_at": 1790000000}
  ]
}
```

`generated_at`, `iat`, `exp` and `updated_at` are seconds since the Unix epoch; `exp` is null for a perpetual certificate. The genesis's list includes its own genesis certificate.

### 5.2 States

| State | Meaning |
|---|---|
| `active` | The certificate licenses its subject. |
| `suspended` | Temporarily not licensing its subject; can be reinstated. |
| `revoked` | Permanently not licensing its subject. |
| `superseded` | Replaced by a newer certificate for the same subject (section 4.5). |
| `expired` | An active certificate whose `exp` has passed. |

### 5.3 Changing a state

- **Revoke** acts on the subject: the issuer revokes every certificate it issued to that subject that is not already revoked, so an older certificate cannot stand in for the revoked one.
- **Suspend** acts on the subject: the issuer suspends every active certificate of that subject.
- **Reinstate** lifts the suspension of the named certificate only.
- A revoked certificate stays revoked and a superseded certificate stays superseded; the remedy is a new certificate.
- The genesis certificate is not suspended or revoked through a list.
- A change reaches verifiers when they next fetch the list.

## 6. Verification

### 6.1 Verifying a JWS

1. Refuse input over the size limit of section 2.5.
2. The input MUST have exactly three `.`-separated segments; the first two MUST decode (base64url) to JSON objects; `alg` MUST be `EdDSA`.
3. If the header has a `kid`, it MUST equal the thumbprint of the verification key.
4. Verify the Ed25519 signature over the signing input with the verification key.

A certificate MUST also have `kind` `tp.federation.licence.v1` and a `type` of `genesis`, `frame` or `operator`; anything else is not a certificate. An issued list MUST have `kind` `tp.federation.licence-list.v1` and an `issuer.trust_domain` equal to the issuer the verifier expects, and its signature MUST verify with that issuer's key: the root certificate's `key` for the genesis's list, the key in a frame's network certificate for that frame's list.

### 6.2 Verifying the root and trusting it

A certificate is a valid root for a network whose genesis trust domain is `G` when:

1. it is a certificate of `type` `genesis`;
2. its `sub.trust_domain` and its `iss.trust_domain` both equal `G`;
3. its hash equals the pinned hash, when the verifier has one configured; and
4. its signature verifies with the key in its own `key` member.

A registry trusts its first root when it obtains it from the genesis over mutual TLS (the channel proves who answered), or when it matches the pinned hash. After that it accepts a different root only when the new root matches the pinned hash. A verifier evaluates certificates against the root it trusts; it MUST NOT take a root from a `chain` presented by the party being verified.

### 6.3 The verdict about a network licence

The input is the certificate presented for trust domain `T` (a frame presents its own; an operator presents its frame's), the trusted root, the genesis's issued list with the time the verifier fetched and verified it, and the current time. The first rule that applies decides:

1. No certificate: `unlicensed`.
2. Not parseable as a certificate (section 6.1): `invalid`.
3. `type` is neither `genesis` nor `frame`: `invalid`.
4. `sub.trust_domain` is not `T`: `invalid`.
5. The verifier holds no valid root (section 6.2): `unverified`.
6. `type` `genesis`: `genesis` when the certificate's hash equals the trusted root's hash, otherwise `invalid` (only the network's pinned root is a genesis).
7. `iss.trust_domain` is not the genesis's trust domain, or `iss.licence` is present and differs from the root's hash: `invalid`.
8. The signature does not verify with the root's key: `invalid`.
9. `iat` is more than 300 seconds in the future: `invalid`. `exp` is not null and is at or before the current time: `expired`.
10. The verifier holds no verified list from the genesis, the list is older than the maximum age, or the list does not name the certificate's hash: `unverified`. The reference maximum age is 86400 seconds and it is never less than 60 seconds.
11. Otherwise the list state decides: `active` gives `licensed`; `revoked` and `superseded` give `revoked`; `suspended` gives `suspended`; `expired` gives `expired`; any other value gives `unverified`.

### 6.4 The verdict about an operator licence

The input is the operator certificate, the network certificate of the operator's frame (which carries the frame's key), the frame's trust domain `F`, the frame's issued list with its fetch time, and the current time:

1. No certificate: `unlicensed`. Not parseable as a certificate: `invalid`.
2. `type` is not `operator`: `invalid`.
3. `sub.trust_domain` or `iss.trust_domain` is not `F`: `invalid`.
4. No network certificate of the frame is available, or it cannot be parsed: `unverified`. A frame that holds no network certificate publishes no certified key, so nobody outside it can check its operators' signatures.
5. The frame's network certificate carries no `key`, or the signature does not verify with that key: `invalid`.
6. The time rules of section 6.3 step 9.
7. The frame's list decides, as in section 6.3 steps 10 and 11.

### 6.5 Certificates on registry cards

When a card's `federation.licence` carries both `certificate` and `hash`, a verifier MUST check that `hash` is the licence hash of `certificate`, and MUST treat a mismatch as `invalid`. The certificate decides the verdict whatever the state of the card's own signature: it is signed by its issuer and names the trust domain it licenses. Only a peer whose card signature is unverified and whose card carries no certificate remains `unverified` for that reason.

### 6.6 Verdicts

| Verdict | Meaning | Under `enforce` |
|---|---|---|
| `genesis` | the network's root | allowed |
| `licensed` | chained to the root and active on the issuer's list | allowed |
| `same-domain` | the peer is in the verifier's own trust domain; not a crossing | not checked |
| `unlicensed` | no licence presented | refused |
| `expired` | past its expiry | refused |
| `revoked` | revoked or superseded | refused |
| `suspended` | suspended | refused |
| `invalid` | fails a structural or signature rule | refused |
| `unverified` | cannot be decided now (no trusted root yet, no current list, or no frame certificate to check an operator licence against) | allowed, counted and reported |

A verifier that cannot decide MUST answer `unverified` with the reason; it MUST NOT guess. A peer the verifier has not evaluated yet is treated like an `unverified` one.

### 6.7 Enforcement

A registry applies licensing in one of three modes:

- `off`: nothing is checked.
- `observe`: every crossing is classified and counted; nothing is refused.
- `enforce`: federation calls from a trust domain whose verdict is `unlicensed`, `expired`, `revoked`, `suspended` or `invalid` are refused.

Under `enforce` a registry MUST NOT refuse an `unverified` peer: an outage of the genesis or of its list must never partition the network. Such peers are counted and reported instead.

A registry decides one verdict per trust domain. The verdicts about the frame registries of a trust domain decide it; other registries of that trust domain count only when no frame registry of it is known. When several verdicts compete, a refused verdict wins, then a passing one, then any other. An operator that presents no licence of its own takes the verdict of the frame it rides.

## 7. Publication

### 7.1 Public endpoints

| Path | Content |
|---|---|
| `GET /.well-known/federation-licence.json` | This registry's own licence: `{"trust_domain", "name"}` plus the members of section 7.2. It always answers, also when the card carries no licence block; on a frame it includes the frame's licence-signing key once the frame has one, so a genesis can issue it a certificate. |
| `GET /.well-known/federation-licences.json` | The issued list: `{"jws": "<list JWS>", "payload": {...}, "count": n}`. `payload` repeats the signed payload unsigned for human readers; a verifier MUST read the payload inside `jws`. A registry that holds no licence key answers `{"jws": null, "payload": null, "count": 0, "note": "..."}`. An operator issues nothing and answers 404; its frame's list names it. |
| `GET /api/v1/public/federation/licences/{hash}` | One certificate this registry issued, by its 64-character lowercase hex hash: the certificate (`certificate`), its `hash`, its identifiers and subject (`lid`, `type`, `sub_trust_domain`, `sub_name`, `sub_url`), `issuer`, `issuer_name`, `network`, `plan`, `issued_at`, `expires_at` (timestamps), and its current `state` with `state_reason`. 404 when this registry issued no certificate with that hash. |
| `GET /api/v1/federation/licence/verdicts` | Informative, served by the reference registry: what it decided about each peer trust domain, `{"mode", "local_trust_domain", "verdicts", "refused", ...}`, where `verdicts` maps a trust domain to its verdict (section 6.6) and `refused` lists the trust domains whose verdict is a refused one (they are refused only while `mode` is `enforce`). Its own TEG copies this answer and refuses the same trust domains on its cross-TEG legs. |

The first two documents are also served at `/api/v1/federation/licence/own` and `/api/v1/federation/licence/list`, where peers read them over the mutually authenticated federation channel.

### 7.2 The `federation.licence` block on a registry card

A registry derives this block from the certificates it holds and its own last verdict about them. It MUST NOT take it from editable card data. The block is absent when the registry has no network configured, licensing is off, and it holds no licence; such a card is identical to one produced before licensing existed.

| Member | Type | Meaning |
|---|---|---|
| `state` | verdict string | The registry's own reading of the licence it holds (section 6.6). `genesis` on the genesis. `unlicensed` when it holds none. |
| `hash` | 64 lowercase hex characters, or null | The licence hash of `certificate`. |
| `network` | string or null | The genesis's trust domain. |
| `issuer` | string or null | The certificate's `iss.trust_domain`. |
| `plan` | string or null | The certificate's plan. |
| `expires_at` | timestamp or null | The certificate's expiry. |
| `certificate` | string or null | The certificate, a compact JWS. |
| `chain` | array of at most 2 certificates | The certificates above this one, up to the genesis certificate. Empty on the genesis. |
| `checked_at` | timestamp or null | When the registry last evaluated the certificate. |
| `reason` | string, at most 240 characters | Why the state is what it is. |
| `key` | Ed25519 JWK or null | Frames only: the frame's licence-signing public key. |
| `operator_policy` | `{"plan": string, "days": integer or null}` | Frames only: how the frame licenses its operators (`days` null means perpetual). |
| `operator` | object or null | Operators only: the operator's own certificate, as `{state, hash, issuer, plan, expires_at, certificate, checked_at}`. |

On an operator, the outer members describe the frame's network licence as the operator holds it, and `operator` describes the operator's own certificate. When the registry cannot build the block it publishes `{"state": "unverified", "hash": null, "reason": "..."}` rather than omitting it.

### 7.3 Signature and entity tag

The registry card signs three leaves of the block: `federation.licence.state`, `federation.licence.hash` and `federation.licence.operator.hash`. Absent leaves are signed as null. The certificate itself needs no card signature: its issuer signed it, and the signed hash binds the card to it.

The block contributes a licence token to the card's entity tag, so that a rotation, a revocation or a change of verdict is never hidden behind a cached copy:

```
licence token = state "|" hash "|" operator.state "|" operator.hash       (each part empty when absent)
```

See `registry-card-v0.6.md`, sections 7 and 8.

## 8. Security considerations

- **Root pinning.** A registry that pins the genesis certificate's hash cannot be switched to another root by anyone who can reach it. Without a pin, the first root is trusted on first use, over mutual TLS only.
- **Chains do not introduce roots.** A certificate delivered with a chain is evaluated against the root the receiver already trusts, never against the chain's own root.
- **Unverified fails open.** A refused, missing or stale issued list makes verdicts `unverified`, which enforcement allows. While that lasts, revocations do not arrive. A registry SHOULD report a refused or stale list prominently.
- **One live licence per subject.** Supersession on issue, and revocation by subject, prevent an older certificate from licensing a subject whose current certificate was revoked.
- **Size.** The 2000-character issue limit keeps the certificate within what peers accept on a registry card; a longer certificate would take the licensee off every peer's view.
