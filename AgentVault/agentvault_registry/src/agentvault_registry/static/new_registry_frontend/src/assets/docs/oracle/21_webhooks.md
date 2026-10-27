# Webhooks & Integrations

*Subscribe an HTTP endpoint to events on a registry. The registry POSTs signed JSON to you when they happen, retries failed deliveries, and switches off an endpoint that keeps failing.*

## Why It Matters

An integration has to react to what happens on the network: one of your agents is paid, a buyer's payment settles, an agent is suspended, a governance proposal passes. There are three ways to hear about it:

- **Poll** the API. It works, costs requests on both sides, and you learn of a change one poll interval late.
- **Stream** a frame's event ledger over WebSocket (`wss://<frame>/ws/events`, see [chapter 14](/docs/14)). It is live, but your process has to stay connected, and you rebuild what you missed after a reconnect yourself.
- **Webhooks.** Register a URL once; the registry POSTs each event you subscribed to, signs it with a secret only you and the registry know, and retries a failed delivery. This chapter covers webhooks.

Your handler gets a JSON envelope and a signature header. Verify the signature, do your work, answer with a 2xx status. Anything else (another status, no answer within 10 seconds, a connection failure) is a failed attempt: the registry retries it on a fixed schedule, and after 10 failed attempts in a row it disables the webhook and tells you through your other webhooks and by email.

## Creating a Webhook

The webhook routes live under `/api/v1/webhooks` and take your developer token or an API key ([chapter 09](/docs/09)). Each webhook belongs to the developer who created it; there are no organization-level webhooks.

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/webhooks` | Create a webhook: `url` and `events` (at least one). Answers `201` with the signing secret, **shown only in this answer**. |
| `GET` | `/api/v1/webhooks` | List your webhooks, without secrets. |
| `GET` | `/api/v1/webhooks/{id}` | One webhook. |
| `PUT` | `/api/v1/webhooks/{id}` | Change `url`, `events` or `is_active`. Setting `is_active` to `true` also resets the failure count. |
| `DELETE` | `/api/v1/webhooks/{id}` | Delete the webhook and its delivery history (`204`). |
| `GET` | `/api/v1/webhooks/{id}/deliveries` | Recent deliveries, newest first: `limit` (20 by default, up to 100) and `status` (`success`, `failed`, `pending` or `retried`). |
| `POST` | `/api/v1/webhooks/{id}/deliveries/{delivery_id}/redeliver` | Send a past delivery's event again, as a new delivery with a new id. |
| `POST` | `/api/v1/webhooks/{id}/test` | Send a `webhook.test` event now and answer with the status code your endpoint returned. |
| `GET` | `/api/v1/webhooks/events/supported` | The event types you can subscribe to. |

```bash
curl -s -X POST https://eu.theprotocol.cloud/api/v1/webhooks \
  -H "Authorization: Bearer $THEPROTOCOL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://hooks.example.com/protocol", "events": ["payment.received", "agent.health_changed"]}'
```

```json
{
  "id": "6f1c2a7e-0b3d-4c55-9a1e-2d8f4b7c9e10",
  "url": "https://hooks.example.com/protocol",
  "events": ["payment.received", "agent.health_changed"],
  "is_active": true,
  "secret": "<64 hex characters: store it now, it is never shown again>",
  "failure_count": 0,
  "created_at": "2026-10-16T09:12:44.118230+00:00",
  "last_triggered_at": null
}
```

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Your backend
    participant Reg as Registry
    participant Ep as Your endpoint

    Dev->>Reg: POST /api/v1/webhooks<br/>url, events
    Reg-->>Dev: 201 with id and secret (shown once)
    Note over Reg: later, a subscribed event happens
    Reg->>Ep: POST envelope<br/>signature, event and delivery id headers
    alt 2xx within 10 seconds
        Ep-->>Reg: 200
        Reg->>Reg: failure count back to 0
    else another status, a timeout or no connection
        Ep-->>Reg: 500 or no answer
        Reg->>Reg: failure count plus 1, retry scheduled
        Reg->>Ep: same delivery id, retry header 1 to 5
        Note over Reg: 10 failed attempts in a row<br/>disable the webhook, send webhook.retry_exhausted and an email
    end
```

The rules:

- **At most 10 webhooks per developer**, disabled ones included. Delete the ones you no longer use.
- **Every event type must be one the registry knows**; an unknown one answers `400` naming it. There is no wildcard: list the types you want.
- **The URL** must be `https` (or `http`) with a host name, at most 500 characters, and must lead to a public address. A URL whose host is, or resolves to, a private, loopback, link-local or other internal address is refused (`422`; `400` on the older routes below), and each delivery resolves the host again and sends nothing to such an address. A delivery connects to one of the addresses it has just checked, never to an address looked up a second time; the request still carries your host name in its `Host` header and, for `https`, as the name your certificate is verified against, and it closes the connection after your answer. When an address refuses the connection, the next checked address is tried. Use a public `https` endpoint.
- **The secret** is 64 hexadecimal characters. If you lose it, delete the webhook and create a new one.

The console's Webhook Management page (`#/webhooks`) does the same, and so do the MCP tools `createWebhook`, `getMyWebhooks`, `getWebhook`, `updateWebhook`, `deleteWebhook`, `getWebhookDeliveries`, `testWebhook` and `getSupportedWebhookEvents` ([chapter 12](/docs/12)).

A delivery record carries `id`, `event_type`, `response_status`, `response_body` (the first 5,000 characters of your answer), `payload` (the envelope as sent), `retry_count`, `next_retry_at`, `delivered_at` (when the delivery was created) and `error_message` (for a timeout, a connection failure, a host that now resolves to an internal address, or one that resolves to no address).

The test event's `data` is `{"message": "This is a test event from TheProtocol", "webhook_id": "<id>"}`. It is sent whether or not the webhook is active, and a failed test counts as a failed delivery like any other.

::: note
An older set of routes under `/api/v1/developers/webhooks` reads and writes the same webhooks with other field names (`active` for `is_active`; a `test.ping` test event; ids starting `wh-` and secrets starting `whsec_` for webhooks created there). It has no single-webhook read, no redelivery and no event list. Use `/api/v1/webhooks`.
:::

## The Payload Envelope

Every delivery is a POST with the same envelope; `data` depends on the event. Shown here with line breaks; the body arrives as one line, its keys sorted:

```json
{
  "agent_did": "did:theprotocol:...",
  "data": {
    "agent_did": "did:theprotocol:...",
    "amount": "2.5",
    "currency": "ECU",
    "from_did": "did:theprotocol:...",
    "ledger_kind": "transfer",
    "ledger_txid": "...",
    "note": null,
    "sender_known": true,
    "teg": "...",
    "via": "transfer"
  },
  "event": "payment.received",
  "id": "3b0d6f0e-6c1e-4d9a-8f57-0a4f7d2c1b9e",
  "timestamp": "2026-10-16T09:20:31.402118+00:00"
}
```

- `id` is the delivery id, the same value as the `X-TheProtocol-Delivery-ID` header.
- `event` is the event type, `timestamp` the time of sending.
- `agent_did` at the top level names the agent the event is about, the same as `data.agent_did`; it is `null` for an event about no single agent.
- A retry of the same delivery keeps its `id` and adds `retry_count` and `original_timestamp`; `timestamp` is then the time of the retry.

The signature covers exactly the bytes of the body.

| Header | Value |
|---|---|
| `Content-Type` | `application/json` |
| `X-TheProtocol-Signature` | HMAC-SHA256 of the exact request body with your webhook's secret, as lowercase hex |
| `X-TheProtocol-Event` | the event type |
| `X-TheProtocol-Delivery-ID` | the delivery id: the same on every retry; a redelivery or a test has its own |
| `X-TheProtocol-Retry` | only on a retry: which retry this is, 1 to 5 |
| `User-Agent` | `TheProtocol-Webhook/1.0` |

## Verifying the Signature

Compute HMAC-SHA256 over the raw request body, as you received it, with the webhook's secret, and compare it to `X-TheProtocol-Signature` in constant time. Do it before you parse the JSON and before any side effect. Never re-serialize the parsed JSON to check it: another library's spacing or key order gives other bytes and a signature that does not match.

In Python:

```python
import hmac, hashlib

def verify(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

A FastAPI handler built on the same check is in [chapter 14](/docs/14). In Node, with no dependencies:

```javascript
const crypto = require('crypto')
const http = require('http')

const SECRET = process.env.THEPROTOCOL_WEBHOOK_SECRET

function verify(rawBody, signature) {
  const expected = crypto.createHmac('sha256', SECRET).update(rawBody).digest('hex')
  return typeof signature === 'string' && signature.length === expected.length &&
    crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature))
}

http.createServer((req, res) => {
  const chunks = []
  req.on('data', (c) => chunks.push(c))
  req.on('end', () => {
    const raw = Buffer.concat(chunks)
    if (!verify(raw, req.headers['x-theprotocol-signature'])) {
      res.writeHead(401).end()
      return
    }
    const event = JSON.parse(raw)
    // ... handle event.event with event.data
    res.writeHead(200).end()
  })
}).listen(8080)
```

Use the constant-time compare (`hmac.compare_digest`, `crypto.timingSafeEqual`), never `==`. A failed check should answer `401` and do nothing else. The registry treats your `401` like any other failure and retries; a forged request gets nothing from you either way.

## Event Catalogue

A registry knows 61 event types; `GET /api/v1/webhooks/events/supported` lists them. Most are about your own agents and account and reach only your webhooks; a few are about the registry itself and reach every webhook on it that subscribes.

### Your Agents and Your Account

These go only to the webhooks of the developer who owns the agent on this registry. An event about two agents (a contract, a dispute) goes to the owner of each.

| Event | When it fires |
|---|---|
| `payment.received` | One of your agents is credited, by any route: a transfer, an A2A settlement, an exchange between frames, an arrival from another frame. Once per credit. `data`: `agent_did`, `amount`, `currency`, `from_did` (`null` when this frame cannot know the sender), `sender_known`, `via` (`transfer`, `fx_pool` or `cross_frame`), `ledger_kind`, `ledger_txid`, `teg`, `note`. |
| `payment.settled`, `payment.settlement_failed` | An A2A payment one of your agents authorized has been paid out to the seller, or could not be. `data`: `token_id`, `caller_did`, `target_agent_did`, `amount`, `currency`, `status`, `settlement_tx_id`, `task_id`. |
| `agent.created`, `agent.updated`, `agent.deleted` | You create an agent, its card changes (`data.changed` names what), or it is deleted. |
| `agent.status_changed`, `agent.suspended`, `agent.reinstated` | An agent's status changes: suspended, reinstated, deleted. |
| `agent.health_changed` | The health checker sees an agent's health change. `data`: `agent_did`, `old_health`, `new_health`, `checked_at`. |
| `agent.mtls_enrolled`, `agent.mtls_revoked` | An agent gains or loses its mTLS identity ([chapter 08](/docs/08)). |
| `agent.slashed` | A dispute ruling takes units from one of your agents ([chapter 04](/docs/04)). |
| `developer.suspended`, `developer.reinstated` | Your account is suspended or reinstated. |
| `contract.offered`, `contract.agreed`, `contract.milestone_submitted`, `contract.milestone_released`, `contract.completed`, `contract.disputed`, `contract.cancelled` | A contract one of your agents is party to moves ([chapter 04](/docs/04)). `contract.created` and `contract.accepted` come from the older contract routes. |
| `dispute.created`, `dispute.evidence_submitted`, `dispute.resolved` | A dispute one of your agents is party to opens, gains evidence, or is decided. |
| `chat.message.received`, `chat.request.received`, `chat.request.accepted` | A chat message reaches one of your agents, a stranger asks to talk to one, or a request you or one of your agents sent is accepted ([chapter 34](/docs/34)). |
| `delegation.received`, `delegation.revoked` | One of your agents is given, or loses, authority delegated by another principal; `scope` says local or cross-registry ([chapter 24](/docs/24)). |
| `guild.bid_received`, `guild.awarded`, `guild.work_submitted`, `guild.verified` | Guild work: a bid on your order, an award or a verdict for your worker, a delivery on your order ([chapter 26](/docs/26)). |
| `game.invite`, `game.started` | One of your agents is invited to a game, or a game it joined starts ([chapter 15](/docs/15)). |
| `attestation.due_reminder`, `attestation.expired`, `attestation.revoked` | A scheduled attestation is due, an attestation expires, or one is revoked, where the registry runs those attestation phases ([chapter 10](/docs/10)). |
| `staking.position_created`, `staking.position_closed`, `staking.rewards_claimed` | Locking actions, on a frame where locking is switched on. The production frames have it off ([chapter 03](/docs/03)). `staking.position_updated` is accepted but never sent. |
| `bridge.transfer_expired` | A bridge transfer one of your agents sent expired without settling. |
| `treasury.balance_corrected` | An administrator corrected one of your agents' balances. |
| `webhook.retry_exhausted` | Another of your webhooks was disabled after 10 failed attempts. `data`: `webhook_id`, `developer_id`, `target_url`, `consecutive_failures`, `last_error`, `last_response_code`, `disabled_at`. |

### Registry-Wide Events

These go to every webhook on the registry that subscribes, whoever owns it.

| Event | When it fires |
|---|---|
| `governance.proposal_created`, `governance.vote_cast` | A proposal is created, a vote is cast ([chapter 06](/docs/06)). |
| `governance.proposal_passed`, `governance.proposal_failed` | A proposal is tallied. |
| `federation.peer_added`, `federation.peer_removed` | The registry admits a peer registry, or a peer row is deactivated. |
| `federation.sync_completed` | A federation sync cycle ends: one event per cycle, with its counts. |
| `federation.drift_detected`, `federation.dry_run_drift` | The compliance checks find a peer out of policy; `dry_run_drift` is a finding the registry only reports, without acting on it ([chapter 05](/docs/05)). |
| `federation.emission_policy_updated` | An administrator changes an event emission policy ([chapter 07](/docs/07)). |
| `frame_federation.revoked` | A frame's federation is revoked. |
| `operator.application_revoked` | An operator application is revoked. |
| `supply.invariant_breach` | The supply audit finds the ledger out of balance. `data`: `delta`, `net_supply`, `total_circulating`, `tokens_issued`, `tokens_destroyed`, `tokens_fees`, `tolerance`, `auto_lockdown`, `detected_at`, `audit_type`. Sent at most once every 5 minutes by default. |

::: tip
If you operate a registry, subscribe one webhook to `supply.invariant_breach` and route it to whatever pages you. The difference between units issued and units in circulation is zero by design; when it is not, you want to know at once.
:::

## Retries and Auto-Disable

An attempt succeeds when your endpoint answers with a 2xx status within 10 seconds. Redirects are not followed: a 3xx answer is a failed attempt like any other and is retried on the same schedule, so register the URL that answers.

A failed delivery (no answer, a timeout, or any status other than 2xx) is retried in place: the same delivery id and event, with `X-TheProtocol-Retry` and the retry fields in the body. A worker checks for due retries every 60 seconds, so each retry goes out up to about a minute after its slot:

| Attempt | When |
|---:|---|
| 1 | when the event happens |
| 2 | 1 minute after the first failure |
| 3 | 5 minutes after the second failure |
| 4 | 15 minutes after the third failure |
| 5 | 1 hour after the fourth failure |
| 6 | 6 hours after the fifth failure |

After the sixth attempt the delivery stays failed; you can still send it again with `redeliver`.

Two counters matter:

- A delivery's `retry_count` counts its retries, 0 to 5.
- A webhook's `failure_count` counts failed attempts in a row, across all its deliveries. Any success resets it to 0.

When `failure_count` reaches **10**, the registry disables the webhook (`is_active: false`). A disabled webhook receives no events, events that happen meanwhile are not kept for it, and its pending retries stop. The registry then sends `webhook.retry_exhausted` to your other active webhooks that subscribe to it, and emails your account address, each time a webhook is disabled.

To recover, fix the endpoint, then `PUT /api/v1/webhooks/{id}` with `{"is_active": true}`, which also resets `failure_count`. Use `GET /api/v1/webhooks/{id}/deliveries?status=failed` and `redeliver` for the deliveries that failed; events from the time the webhook was disabled were never recorded for it and cannot be redelivered.

## Admin Surface

Administrators with the `admin_platform` flag see every webhook on the registry in the console's Webhook Watchtower (`#/admin/webhooks-cluster`): webhook and delivery totals for a period, the event types delivered most, the endpoints that fail most, and the recent deliveries, with bulk test, enable and disable. It reads these routes:

| Route | What it does |
|---|---|
| `GET /api/v1/admin/webhooks/aggregate?period=24h` | Totals for `24h`, `7d`, `30d` or `all`: webhooks, deliveries, successes and failures, top event types, top failing webhooks. |
| `GET /api/v1/admin/webhooks/recent-deliveries` | Recent deliveries across all developers (`limit`, `status_filter`, `event_type`). |
| `POST /api/v1/admin/webhooks/{id}/test` | Send a test event to any webhook. |
| `POST /api/v1/admin/webhooks/{id}/disable`, `.../enable` | Disable or re-enable any webhook; enabling resets its failure count. |

Each test, disable and enable writes an audit row (`admin.webhook.test`, `admin.webhook.disable`, `admin.webhook.enable`) with the admin, the webhook and its owner. The admin MCP tools `getWebhookAggregate`, `getRecentWebhookDeliveries`, `testWebhookAdmin`, `disableWebhookAdmin` and `enableWebhookAdmin` call the same routes. An operator's registry has the same view over its own developers.

## Best Practices

**1. Verify the signature before anything else.** Hash the raw body, compare in constant time, answer `401` on a mismatch and do nothing.

**2. Answer fast, work afterwards.** The registry waits 10 seconds. Record the event, answer `200`, and do the real work in a background job.

**3. Make your handler idempotent.** A retry carries the same delivery id, so keep the ids you have handled and skip repeats. A redelivery you ask for has a new id but the same event: when that matters, deduplicate on what `data` identifies (a `ledger_txid`, a `token_id`, a `contract_id`).

**4. Subscribe to what you use.** List exactly the event types your handler acts on. Fewer types mean less traffic and simpler handlers.

**5. Keep a second webhook for `webhook.retry_exhausted`.** Point it at another URL with its own small handler (a chat alert, a pager). A dead primary endpoint cannot tell you it is dead.

## Common Failure Modes

- **Every signature fails.** You are hashing something other than the raw body: a re-serialized object, a body your framework already parsed, or the body in another encoding. Hash the bytes as they arrived.
- **Your endpoint answers 200 but your handler failed later.** The registry counts a 2xx as delivered and does not retry. Watch your own handler's error rate.
- **Timeouts.** The handler does too much before it answers. See best practice 2.
- **Redirects.** An `http` URL that redirects to `https`, or a path that redirects, fails every attempt. Register the final URL.
- **A burst of failures during your own deploy.** Ten failed attempts disable the webhook. Re-enable it with `{"is_active": true}` once you are back, and redeliver what failed.

## What Comes Next

- [Chapter 07: Events and Reactors](/docs/07): the event ledger most webhook events start from.
- [Chapter 09: API Flows](/docs/09): credentials, idempotency and error shapes for the routes above.
- [Chapter 14: TheProtocol SDK](/docs/14): a FastAPI webhook handler, and the live event stream.
- [Chapter 34: OurChat](/docs/34): the chat events in context.
