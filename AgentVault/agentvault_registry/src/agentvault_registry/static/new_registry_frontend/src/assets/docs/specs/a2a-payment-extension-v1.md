# TheProtocol A2A payment extension, version 1

Version 1, 30 September 2026

This specification is licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). Copyright 2025-2026 Raphael Zbigniew Jeziorny.

## Conformance

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, RECOMMENDED, MAY and OPTIONAL in this document are to be interpreted as described in RFC 2119. This specification has four conformance classes. A conforming **agent card** declares its price as in section 2. A conforming **registry** issues, verifies and settles payment authorizations as in sections 3 to 5. A conforming **service** (the paid agent) checks payment as in section 6. A conforming **caller** (the paying agent) follows section 7. Values described as the reference implementation's are informative.

## 1. Overview

The extension lets an agent charge for its A2A service and lets any agent, on any registry, pay for it:

1. The **caller** asks its own registry, the **issuing registry**, to authorize a payment of a given amount to the **service** (the payee, identified by its DID). The registry checks the caller's balance and returns a payment authorization.
2. The caller sends its A2A request to the service with the token in the `X-Payment-Token` header and the issuing registry's address in the `X-Payment-Issuer` header.
3. The service asks the issuing registry to verify the token before it does the work.
4. After the service has answered, the caller **settles** the token. Only then do units move, once, through the issuing registry's ordinary transfer rail. If the service did not deliver, the caller settles with `success: false` or releases the token, and nothing moves.

A registry is a server that hosts agent identities and a ledger; its public facts, including its fees and its unit, are published in its registry card (`registry-card-v0.6.md`). A registry that implements this extension lists `a2a-payment-v1` in its card's `capabilities.supports_payment_protocol`.

Amounts are in the units of the issuing registry's frame, for example ECU on the EU frame and ACU on the ASIA frame. They have no euro price, cannot be exchanged back into money, and carry no claim to money.

## 2. Declaring the extension on an agent card

### 2.1 The extension object

A paid service declares the extension in the top-level `extensions` array of its agent card, as an A2A agent extension object:

```json
{
  "uri": "https://theprotocol.cloud/extensions/v1/auth/a2a-payment",
  "description": "A2A payment token; single-use; settlement-after-success",
  "required": true,
  "params": {
    "base_rate": "0.5",
    "currency": "ECU",
    "pricing_model": "per_request"
  }
}
```

| Member | Presence | Meaning |
|---|---|---|
| `uri` | REQUIRED | `https://theprotocol.cloud/extensions/v1/auth/a2a-payment`. |
| `description` | OPTIONAL | Human-readable text. |
| `required` | OPTIONAL | `true` when the service refuses calls that carry no valid payment. Readers treat an absent `required` as `true` on a priced card. |
| `params.base_rate` | REQUIRED for a paid service | The price of one call: a decimal number greater than zero, written as digits with an optional fractional part (no sign, no exponent), preferably as a JSON string. |
| `params.currency` | RECOMMENDED | The code of the unit the price is stated in, for example `ECU`. A card SHOULD always state it (section 2.3). |
| `params.pricing_model` | OPTIONAL | What one price covers. Readers treat an absent value as `per_request`. |

A registry reads prices from the top-level `extensions` array. `required` declares that the service enforces payment; it does not by itself make a card paid (section 2.3).

### 2.2 Legacy pricing block

Readers MUST also accept the older top-level `pricing` object of an agent card:

```json
"pricing": {"base_rate": "0.5", "currency": "ECU", "model": "per_call", "payment_required": true}
```

| Member | Meaning |
|---|---|
| `base_rate` | The price of one call. |
| `currency` | The code of the unit the price is stated in. A card SHOULD state it. |
| `model` (or `pricing_model`) | What one price covers (absent: `per_request`). |
| `payment_required` | `true` when the service enforces payment. |

A registry that writes or serves the cards of its own agents derives the extension from a legacy block, so that paid cards carry the extension:

- It derives only when the card carries no payment extension, either in `extensions` or in `capabilities.extensions`; an extension the author wrote is never overwritten.
- It derives only when the block's `base_rate` is a number greater than zero. A block that says `payment_required: true` without a usable rate gets no derived extension: a registry MUST NOT invent a price.
- The derived extension has `params.base_rate` (the block's rate, as a string), `params.currency` (the block's currency in upper case; for a block that names none, the reference registry writes its own unit, the unit of the agent's frame), `params.pricing_model` (the block's `pricing_model` or `model`, or `per_request`), and `required: true` only when `payment_required` is `true`.

Copies of cards mirrored from other registries are never modified.

### 2.3 Reading a price

- A card is **paid** when its legacy block has `payment_required: true`, or when its payment extension has a `params.base_rate` that is a decimal number greater than zero.
- The **effective price** comes from the legacy block when that block is an object that states `base_rate` or has `payment_required: true`. Otherwise it comes from the extension, when the extension states `base_rate`.
- A card with neither is free.
- Where a card states no currency, the reference software reads the price in the unit of the registry that reads it: for a card on its own registry that is the agent's own unit, and a copy mirrored from another registry is read in the reader's unit. A card that states its currency avoids the question.

### 2.4 Security scheme (optional)

An agent card MAY also declare the token header as an A2A security scheme:

```json
{"type": "apiKey", "in": "header", "name": "X-Payment-Token",
 "description": "A2A payment token (apt_<hex>), single-use; see TheProtocol extension https://theprotocol.cloud/extensions/v1/auth/a2a-payment"}
```

## 3. Payment authorizations

- **Format.** `apt_` followed by 64 lowercase hexadecimal characters, which encode 32 random bytes. Example shape: `apt_<64 lowercase hex characters>`.
- **Issued once.** The issuing registry returns the plaintext token exactly once, in the authorize response. It SHOULD store only a hash of it; the reference registry stores the SHA-256 of the full token string.
- **Identifier.** Each token also has a `token_id` (a UUID string), which is not secret.
- **Binding.** A token is bound to its caller (only the caller can settle or release it), its target (a verification that names another target fails), its amount (fixed at authorization) and its expiry.
- **Lifetime.** `ttl_seconds` from 60 to 3600, default 900 (15 minutes).
- **Denomination.** The amount is in the issuing registry's unit. Every response names that unit in `currency`, and it equals `fees.settlement_currency` on the issuing registry's card. The reference registry keeps amounts to six decimal places.
- **Transport.** Payment authorizations travel in the `X-Payment-Token` HTTP header. They MUST NOT be put in URLs.

## 4. Registry endpoints

All paths are under `/api/v1/a2a-payment`. Except for verification, every endpoint requires the caller's agent credential, a bearer JWT issued by the registry (`Authorization: Bearer <agent JWT>`): a missing or invalid credential gives 401, and an agent that is suspended or revoked gets 403. A registry MAY additionally require the caller to hold a payment permission and refuse with 403 when it does not; where the reference registry enforces agent permissions, authorize, settle and both releases ask for `a2a.pay`, which the `client` role carries. The settlement itself is an ordinary transfer from the paying wallet, so that wallet also needs `teg.transfer` for a payee on the same registry and `teg.transfer_xreg` for a payee on another registry; the reference registry checks this at authorization for every paying wallet, its own or a delegated one (section 8), and refuses with 403, authorizing nothing, a payment its settlement would refuse, before any service is called. Error responses are RFC 7807 problem documents (`application/problem+json`) whose `detail` states the reason.

The reference registry also offers `GET /quote` (what a service costs in the caller's unit) and `POST /buy` (authorize, call the service and settle in one request). Both are conveniences built on the endpoints below and are not part of this specification.

### 4.1 `POST /authorize`

Request:

| Member | Type | Required | Meaning |
|---|---|---|---|
| `target_agent_did` | string | yes | The DID of the service to pay. |
| `amount` | string | yes | The amount to authorize: a decimal number greater than zero, in the issuing registry's unit. The reference registry keeps six decimal places: it rounds a longer amount half up, and refuses one that rounds to zero. |
| `ttl_seconds` | integer, 60 to 3600 | no | Token lifetime; default 900. |
| `contract_id` | integer | no | The number of a contract on the issuing registry that the payment refers to. The reference registry stores it with the token without checking it (section 8). |

Response, `200 OK`:

```json
{
  "token": "apt_<64 lowercase hex characters>",
  "token_id": "<uuid>",
  "amount": "0.500000",
  "currency": "ECU",
  "target_agent_did": "did:theprotocol:<id>",
  "expires_at": "2026-09-30T12:15:00+00:00",
  "contract_id": null,
  "issuer": "https://registry.example.org",
  "issuer_header": "X-Payment-Issuer"
}
```

`issuer` is the issuing registry's public base URL: the value the caller sends in the header named by `issuer_header`. `amount` is the amount the token keeps, with six decimal places (`"0.500000"`), as every endpoint gives it.

Rules:

- Authorization checks the paying wallet's balance at that moment. For a payee on another registry it asks for the amount; for a payee on the same registry it asks for the amount plus the intra-registry fee that the settlement charges on top of it (section 8), which the reference registry estimates when it authorizes. It does not reserve funds: a settlement can fail later if the balance has dropped in the meantime.
- The registry does not require the payee to be registered locally, because the payee may live on another registry. It refuses an obviously malformed target (the reference registry refuses a `target_agent_did` shorter than 10 characters).
- A registry MAY limit how many authorized, unused payment authorizations a caller holds; the reference registry allows 20.
- The registry MAY refuse a payee that its provider policy does not admit (for example a payee without a required reputation bond, or a suspended one).
- **Idempotency.** The request MAY carry an `Idempotency-Key` header. Within 24 hours, a repeated request from the same agent with the same key and the same body returns the original response, including the same token. A key is the calling agent's own: the same value sent by another agent is another request. The same key with a different body gives 422. So does the same key while the first request is still running, or after a first request that was refused (a refusal stores no answer), until the key frees itself, after 90 seconds in the reference registry. Use a new key for a new attempt.

Errors:

| Status | Reason |
|---|---|
| 400 | `amount` is not greater than zero, or rounds to zero at six decimal places; `target_agent_did` is malformed. |
| 401 | Missing or invalid agent credential. |
| 402 | Insufficient balance. The `detail` states the available balance and the required amount (with the transfer fee, for a payee on the same registry). |
| 403 | The caller may not pay (it lacks the payment permission, or it is suspended), its own spending rules refuse the payment, the registry does not admit the payee, or the paying wallet could not settle (section 8). |
| 422 | The request does not validate (for example `ttl_seconds` out of range, or an `amount` that is not a finite decimal number), or an `Idempotency-Key` conflict. |
| 429 | The caller holds too many unused payment authorizations. |

### 4.2 `POST /verify`

Called by the service, without authentication: the token authenticates itself.

Request:

| Member | Type | Required | Meaning |
|---|---|---|---|
| `token` | string | yes | The token the service received. |
| `target_agent_did` | string | no | The service's own DID. A service SHOULD always send it. |

Every well-formed request receives `200 OK` with this shape; the outcome is in `valid`:

| Member | Meaning |
|---|---|
| `valid` | `true` when the service may treat the payment as authorized. |
| `token_id`, `caller_did`, `target_agent_did`, `amount`, `contract_id`, `expires_at` | The token's facts (on a valid answer). |
| `currency` | The issuing registry's unit. |
| `status` | The token's status (section 5). |
| `error` | Why the answer is not valid. |

The registry evaluates, in this order:

1. Unknown token: `{"valid": false, "error": "Token not found"}`.
2. The current time is later than `expires_at`: `{"valid": false, "error": "Token expired", "status": "expired"}`; an `authorized` token becomes `expired`.
3. The status is neither `authorized` nor `consumed`: `{"valid": false, "error": "Token status: <status>", "status": "<status>"}`.
4. `target_agent_did` was sent and differs from the token's target: `{"valid": false, "error": "Token not issued for this agent"}`. The token is not consumed.
5. Otherwise the answer is valid. On the first valid answer an `authorized` token becomes `consumed`.

**Verification is repeatable.** A `consumed` token keeps answering `valid: true` until its settlement begins or it is released or expires, so that a retried delivery of the same work can check it again. Verification therefore does not enforce single use; settlement does (section 4.3).

### 4.3 `POST /settle`

Called by the caller (the payer) after the service has answered.

Request:

| Member | Type | Required | Meaning |
|---|---|---|---|
| `token` | string | yes | The token. |
| `task_id` | string | no | The A2A task identifier, recorded for audit. |
| `success` | boolean | no | Default `true`. `false` releases the token instead of paying. |

Response, `200 OK`:

```json
{
  "token_id": "<uuid>",
  "status": "settling",
  "settlement_tx_id": null,
  "amount": "0.500000",
  "currency": "ECU",
  "caller_did": "did:theprotocol:<id>",
  "target_agent_did": "did:theprotocol:<id>"
}
```

Rules:

- Only the token's caller may settle it (403 otherwise). An unknown token gives 404.
- A token that is already `settled` returns `200` with `status: "settled"` and its `settlement_tx_id`. Settlement is idempotent by the token itself; the reference registry accepts an `Idempotency-Key` header here but does not use it.
- A token in any status other than `authorized` or `consumed` gives 400. A token does not need to have been verified before it is settled.
- With `success: false`, the registry releases an `authorized` or `consumed` token and returns `200` with `status: "released"`; nothing is paid.
- Otherwise the registry atomically moves the token to `settling` and returns `200` with `status: "settling"`. Exactly one of any number of concurrent settle calls wins; a concurrent loser gets the `settled` answer if the winner has already finished, or 409.
- The transfer runs after the response. When it reports success, the token becomes `settled` and records `settlement_tx_id`. When it reports a failure, or gives no answer within 35 seconds in the reference registry, the token becomes `failed`.
- The reference registry sends the settlement transfer with an idempotency key of the token's own, under which it keeps the transfer's answer. The key is derived from the token itself, not from its `token_id` alone: the `token_id` is not secret, and a key anyone can compute is a key anyone can use first. It also runs a sweep every 60 seconds over the payment authorizations still `settling` that were verified more than 90 seconds earlier (or, if never verified, issued more than 90 seconds earlier), and it asks that record first, on the endpoint that ran the settlement. It counts only the record of the settlement's own transfer (to the payee, of the token's amount, with the settlement's message, kept for the payer's side); a record of any other request under the key counts as none. A completed transfer makes the token `settled` with its `settlement_tx_id`; a failed transfer, or none, makes it `failed`; a transfer still running, or one that ended without an answer, leaves the token `settling` while the registry keeps that record (24 hours in the reference registry), and `failed` after it; a record the registry cannot read at that moment leaves the token `settling` until a later sweep can. A transfer that completes after the sweep marked its token `failed` still makes it `settled`.
- Units move at most once per token. A `failed` token records that the registry did not see a transfer complete; it does not prove that none did. Before paying again for the same work, look for the transfer in the paying wallet's transactions (`GET /api/v1/teg/transactions` on the reference registry).

### 4.4 `POST /release` and `POST /release-by-id/{token_id}`

The caller cancels a token it has not used. `/release` takes `{"token": "<token>"}`; `/release-by-id/{token_id}` takes the token's identifier in the path and honours `Idempotency-Key` as in section 4.1.

- Only the token's caller may release it (403 otherwise); an unknown token gives 404.
- Only an `authorized` token can be released (400 otherwise). A token that a service has already verified (`consumed`) is released through `/settle` with `success: false`.
- Response, `200 OK`: `{"token_id": "<uuid>", "status": "released"}`.

### 4.5 `GET /my-tokens`

The caller's payment authorizations, newest first: an array of `{token_id, target_agent_did, amount, currency, status, contract_id, created_at, expires_at, settled_at}`. Query parameters: `status` (a status from section 5, in any letter case; an unknown value gives 422) and `limit` (default 50, from 1 to 200; another value gives 422). This is how a caller learns whether a `settling` token ended `settled` or `failed`. A registry MAY also notify the payer's owner, for example by the webhook events `payment.settled` and `payment.settlement_failed`; the reference registry sends them when its settlement transfer ends (`payment.settled` also when the transfer completes after the sweep marked the token `failed`), and sends none for a token its sweep settles or marks `failed`.

## 5. Token lifecycle

| Status | Meaning | Terminal |
|---|---|---|
| `authorized` | Issued, not yet used. | no |
| `consumed` | Verified by the service at least once. | no |
| `settling` | Settlement accepted; the transfer is in flight. | no |
| `settled` | Paid; `settlement_tx_id` names the transfer. | yes |
| `released` | Cancelled by the caller; nothing paid. | yes |
| `expired` | Passed `expires_at` without settlement; nothing paid. | yes |
| `failed` | The registry saw no settlement transfer complete: the transfer failed, did not answer in time, or the sweep found no completed transfer (section 4.3). | yes, unless its transfer completes later (section 4.3) |

Transitions:

```
authorized -> consumed    first valid verification
authorized -> settling    settle
authorized -> released    release, or settle with success false
authorized -> expired     expiry
consumed   -> settling    settle
consumed   -> released    settle with success false
consumed   -> expired     expiry without settlement
settling   -> settled     transfer succeeded, or the sweep found it completed (section 4.3)
settling   -> failed      transfer failed or did not answer, or the sweep found no completed transfer (section 4.3)
failed     -> settled     a transfer that completes after the sweep marked the token failed
```

The registry moves payment authorizations that are still `authorized` or `consumed` after `expires_at` to `expired` periodically (the reference registry checks every 60 seconds); a verification after `expires_at` also expires an `authorized` token at once. A caller SHOULD settle before `expires_at`. Once a token is `expired` it can no longer be settled; the reference registry decides this by the status, so a settlement in the minute between `expires_at` and the next sweep can still go through.

## 6. Service behaviour

A service that requires payment:

1. MUST refuse a request that carries no `X-Payment-Token`. The reference implementation answers HTTP 402.
2. Determines where to verify: the registry named in `X-Payment-Issuer` when the header is present, otherwise the service's own registry. Its own registry is always trusted; any other issuer MUST be on the service's explicit list of trusted registries, and a request naming an issuer that is not on it MUST be refused without contacting that issuer.
3. Calls `POST <issuer>/api/v1/a2a-payment/verify` with the token and its own DID as `target_agent_did`.
4. MUST refuse unless the answer has `valid: true` and `target_agent_did` equal to its own DID.
5. MAY refuse an `amount` below its price. When the service prices in a unit other than the issuing registry's, the comparison is the service's responsibility.
6. MUST NOT perform paid work more than once for one token, because verification is repeatable (section 4.2). It SHOULD remember which payment authorizations it has served.
7. MAY cache a valid verification for a short time; the reference implementation caches for 5 seconds.

A service that does not require payment MAY accept calls without a token.

The reference implementation is `PaymentVerifier` in the Python SDK (`theprotocol.payment`); `create_a2a_router` adds it to an agent's router when `REGISTRY_URL` and `AGENT_DID` are set. In theprotocol-sdk 0.7.5 and earlier this does not work: FastAPI reads the verifier's `request` parameter as a query parameter and answers every call with 422 before any payment is checked; 0.7.6 fixes it. On those releases, give the router a dependency of your own that passes the request on, `async def pay(request: Request): return await verifier(request)` (with `Request` from FastAPI), and turn the router's own verifier off with `payment_required=False`. The verifier then answers as described above.

## 7. Caller behaviour

1. Read the service's effective price (section 2.3). When the price is stated in a unit other than the issuing registry's, the caller authorizes an equivalent amount in the issuing registry's unit.
2. Authorize (section 4.1).
3. Call the service with both headers:

   ```
   X-Payment-Token: apt_<64 lowercase hex characters>
   X-Payment-Issuer: https://registry.example.org
   ```

   `X-Payment-Issuer` is the `issuer` value of the authorize response, without a trailing slash. Without it a service on another registry verifies at its own registry, which never issued the token, and refuses.
4. When the service has delivered, settle with `success: true`. When the service reports that it could not do the work (a JSON-RPC error, or an A2A task in a failed state), settle with `success: false`, which releases the token. When the caller decides not to call the service at all, it releases the token.
5. A settle call may be retried safely. A `settling` answer completes asynchronously; the caller reads the outcome from `GET /my-tokens`.

## 8. Settlement, fees and delegated wallets

- The issuing registry settles through its ordinary transfer rail: a transfer inside the registry when the payee is local, a cross-registry transfer when the payee lives on another registry. The fees published on the registry cards apply, on different sides. For a local payee, the paying wallet pays the authorized amount plus the intra-registry fee (`fees.intra_registry`), and the payee receives the whole amount. For a payee on another registry, the paying wallet pays the authorized amount, and the payee's registry keeps the cross-registry fee from it (`fees.cross_registry`, whose `fee_recipient` is `receiver_registry`). When the payee's frame keeps another unit (a payment from the EU frame to an agent on the ASIA frame, for example), the transfer goes through the exchange between the two frames instead: the paying wallet pays the authorized amount, and the payee receives the converted amount less the exchange fee (`fees.fx.fee_pct`), in its own unit.
- `contract_id` is a reference only: the reference registry stores it with the token and moves nothing for the contract. A contract on the reference registry pays its milestones from its own escrow, not with a payment authorization.
- A registry MAY let an agent pay from a wallet it is authorized to spend from rather than its own, for example a sub-agent that spends its parent's wallet. Authorization is then the whole admission: the registry applies the caller's own spending limits first, then checks the balance of the paying wallet (a 402 names that wallet), then checks, without changing anything, whether that wallet's own rules would allow the settlement (its transfer permission, its spending policy, its organization's ceiling). A refusal is a 403 that names the wallet and states that nothing was authorized, and it happens before any service is called. Settlement then moves the authorized amount from the paying wallet, with the fees above, without charging the caller's delegated budget a second time.

## 9. Security considerations

- The token is a bearer secret for its target: it travels only in a header, over TLS, and is never placed in a URL.
- Verification is unauthenticated and repeatable; only settlement moves units, once. A service that bills per call must track its own consumption.
- The issuer allowlist keeps a caller from pointing a service at a registry the service does not trust.
- Authorization does not reserve funds; a service that must be sure of payment before delivering needs a policy of its own for failed settlements.
- A `failed` token is the registry's record that it saw no transfer complete, not proof that none happened (section 4.3).
- A registry refuses to settle for anyone but the caller, and refuses to release a token that a service has already verified except through `/settle` with `success: false`.
