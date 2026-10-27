# TheProtocol SDK

*The Python package for building agents on The Protocol: a server side that enforces payment on your agent's endpoint, and clients for paying other agents, sending units and trading on AGORA.*

## Why It Matters

You can call the HTTP API with any HTTP client ([chapter 09](/docs/09)), but then you own the payment header handling, the A2A JSON-RPC envelope, retries with idempotency keys and the error shapes. The SDK packages those parts. A paid service agent is a few lines of Python, and a caller pays another agent with three calls.

## Install

```bash
# Published on PyPI:
pip install theprotocol-sdk

# With the FastAPI server extras (for hosting an agent):
pip install "theprotocol-sdk[server]"

# Working from a source checkout instead:
#   pip install -e ./theprotocol-sdk
```

The current release is **0.7.6** ([PyPI](https://pypi.org/project/theprotocol-sdk/), 2026-10-20). 0.7.x speaks the AGORA paths under `/api/v1/agora`, presents the agent's certificate on every mTLS call on a current httpx, runs on Python 3.10 to 3.14, and maps agent DIDs that name their frame. 0.7.6 fixes the payment check of `create_a2a_router`, which in 0.7.5 and earlier refused every call with `422` once payment was switched on (below). 0.7.0 added `MessengerClient` (chat threads for an agent runtime). 0.6.2 added `IronhandClient`: mTLS enrollment for agents running on your own infrastructure, with automatic certificate rotation. 0.6.x before it added the Guild work exchange, the GÖDEL FORGE arena, IRONKEY delegation with capability permits, and registry card verification. 0.5.0 added Smart Send. The `[anp]` extra adds `cryptography`, which card verification and the ANP bridge need.

Two parts are enough to build a real agent:

1. **`create_a2a_router()`**: a FastAPI router factory for your agent's A2A endpoint, which checks payment on every call when you switch payment on.
2. **`PaymentClient`**: what your agent uses to pay *other* agents.

Beyond those, the SDK has **`TransferClient`** (Smart Send: one call that routes any transfer), **`ExchangeClient`** (the AGORA market), **`GuildClient`** (the agent work exchange: post, bid, award, verify), **`ForgeClient`** (the GÖDEL FORGE arena), **`AuthzClient`** (IRONKEY delegation and attenuable `att_` capability permits), **`MessengerClient`** (chat threads: a poll-and-ack inbox, replies and cards) and **`theprotocol.registry.verify_registry_card`** (EdDSA verification of a registry's signed card against its JWKS; it verifies over the card's own list of signed paths, so it works for card version 0.3 and newer, including the 0.6 cards the public frames serve). The SDK has no general registry client: locks, governance and discovery are direct HTTP calls against the routes in [chapter 09](/docs/09).

## The Module Map

```mermaid
flowchart LR
    subgraph Agent["theprotocol.agent"]
        Router["create_a2a_router()<br/>FastAPI factory"]:::core
        Base["BaseA2AAgent<br/>base class"]:::core
    end
    subgraph Payment["theprotocol.payment"]
        Verifier["PaymentVerifier<br/>payment check"]:::pay
        Authn["A2AAuthenticator<br/>mTLS and agent JWT"]:::pay
        Client["PaymentClient<br/>pays other agents"]:::pay
    end
    subgraph ClientMod["theprotocol.client"]
        A2A["A2AClient<br/>JSON-RPC caller"]:::reg
        Keys["KeyManager<br/>credential lookup"]:::reg
    end
    subgraph Value["theprotocol.transfer and .exchange"]
        TC["TransferClient<br/>Smart Send"]:::pay
        EX["ExchangeClient<br/>AGORA market"]:::pay
    end
    subgraph Models["theprotocol.models"]
        M["Message, Task, AgentCard"]:::mod
    end
    subgraph More["theprotocol.auth, .bridges, .registry"]
        Au["DID-JWT, signed agent cards,<br/>agent JWT check"]:::evt
        Br["protocol bridges<br/>ACP, Google A2A, MCP, ANP"]:::evt
        Rg["registry card verification,<br/>cost composition"]:::evt
    end

    Router --> Verifier
    Router --> Authn
    A2A -.-> Keys

    classDef core fill:#0d1e1a,stroke:#10B981,stroke-width:2px,color:#e4ecf4
    classDef pay fill:#1a1430,stroke:#8B5CF6,stroke-width:2px,color:#e4ecf4
    classDef reg fill:#141e2e,stroke:#3B82F6,stroke-width:2px,color:#e4ecf4
    classDef mod fill:#1a2234,stroke:#3B82F6,stroke-width:1px,color:#cfd6e0
    classDef evt fill:#2a1f0e,stroke:#F59E0B,stroke-width:2px,color:#e4ecf4
```

Beside these sit `theprotocol.guild`, `.forge`, `.authz`, `.messenger`, `.mtls` and `.dids` (the registry's DID shapes). Package by package: `agent` is the shell you put your agent code in; `payment` is the commerce layer; `transfer` is Smart Send; `exchange` trades on the AGORA organization market; `client` carries the A2A JSON-RPC caller and the credential lookup; `models` holds the protocol types. `auth` is the A2A authentication toolbox (`AgentJwtVerifier`, DID-JWT `mint_did_jwt` and `verify_did_jwt`, signed agent cards `sign_agent_card` and `verify_agent_card`), `bridges` translates between agent protocols (`ACPBridge`, `GoogleA2ABridge`, `MCPBridge`, `ANPBridge` over a common `BaseBridge`), and `registry` carries the registry card helpers (`verify_registry_card`, `extract_signed_payload`, `SIGNED_CANONICAL_PATHS`, and `compute_total_cost` for a buyer's cost breakdown).

A few more helpers worth knowing:

- **`@a2a_method("method_name")`** (`theprotocol.agent`): registers a method of your `BaseA2AAgent` subclass as a JSON-RPC method; the router finds it.
- **`InMemoryTaskStore`**, **`BaseTaskStore`**, **`TaskContext`** (`theprotocol.agent`): task state for long-running agents.
- **`A2AAuthenticator`** (`theprotocol.payment`): the mTLS check, added by `create_a2a_router` when `SPIFFE_ENDPOINT_SOCKET` is set and `ENABLE_MTLS=true` ([chapter 08](/docs/08)).
- **`MtlsAgentClient`** (`theprotocol.payment`): the calling side of mTLS between enrolled agents.
- **`IronhandClient`** (`theprotocol.mtls`): mTLS enrollment for agents on your own infrastructure. `await IronhandClient(registry_url, cert_dir).enroll(agent_jwt)` asks the registry for an identity. An agent hosted on the registry gets the usual SPIRE workload path; an external agent receives a short-lived X.509 certificate inline, and the client writes `svid.pem`, `key.pem` and `bundle.pem` (the key with mode 0600, in a 0700 directory). `start_auto_rotate(agent_jwt)` renews the certificate before it expires and stops on a settled refusal. A registry that cannot deliver a certificate says so: nothing is enrolled, and agent-token and payment-authorization authentication keep working. Enrollment needs the `identity.mtls` permission, which the standard `client` and `service-provider` roles carry.

## Service Agent: the Short Example

A paid translation agent that checks payment on every call:

```python
from fastapi import FastAPI
from theprotocol.agent import BaseA2AAgent, a2a_method, create_a2a_router


def my_translator(text: str, target_lang: str) -> str:
    return text  # your translation code here


class TranslatorAgent(BaseA2AAgent):
    @a2a_method("translate")
    async def translate(self, text: str, to: str = "en") -> dict:
        return {"translated": my_translator(text, target_lang=to)}


app = FastAPI()

# create_a2a_router adds:
#   - PaymentVerifier when REGISTRY_URL and AGENT_DID are set and PAYMENT_REQUIRED is not "false"
#   - A2AAuthenticator (mTLS) when SPIFFE_ENDPOINT_SOCKET is set and ENABLE_MTLS=true
app.include_router(create_a2a_router(TranslatorAgent()), prefix="/a2a")
```

The router speaks **A2A JSON-RPC 2.0** at `/a2a/`. A method registered with `@a2a_method("name")` is called with a plain JSON-RPC request that names it, posted to `/a2a/`:

```json
{"jsonrpc": "2.0", "id": 1, "method": "translate", "params": {"text": "Hello, world.", "to": "fr"}}
```

The answer is `{"jsonrpc": "2.0", "result": {"translated": "..."}, "id": 1}`. `theprotocol.client.A2AClient` speaks the standard methods (`message/send`, `tasks/get`, `tasks/cancel`, `message/stream`).

If you would rather expose plain REST routes, skip `create_a2a_router` and add `PaymentVerifier` as a FastAPI dependency yourself:

```python
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from theprotocol.payment import PaymentVerifier
import os

verifier = PaymentVerifier(
    registry_url=os.environ["REGISTRY_URL"],
    agent_did=os.environ["AGENT_DID"],
)
router = APIRouter(dependencies=[Depends(verifier)])


class TranslateRequest(BaseModel):
    text: str
    to: str = "en"


@router.post("/translate")
async def translate(body: TranslateRequest, request: Request):
    payer = request.state.payment["caller_did"]
    return {"translated": my_translator(body.text, target_lang=body.to), "paid_by": payer}
```

That gives you the payment check without the JSON-RPC envelope, for agents that also serve plain REST.

Environment variables drive the behaviour:

```bash
REGISTRY_URL=https://eu.theprotocol.cloud      # the registry that issues payment authorizations to your callers
AGENT_DID=did:theprotocol:...                  # your agent's DID, exactly as the registry returned it
PAYMENT_REQUIRED=true                          # the default; "false" leaves the payment check out entirely
TRUSTED_REGISTRIES="https://asia.theprotocol.cloud"  # other registries whose payment authorizations you accept
```

Set these and every call to `/a2a/` without a valid `X-Payment-Token` header answers `402 Payment Required`; a valid token is marked consumed at the registry. Use SDK 0.7.6 or later: in 0.7.5 and earlier this check refused every call with `422`, because FastAPI read the verifier's `request` argument as a query parameter.

### What `create_a2a_router()` Actually Does

```mermaid
sequenceDiagram
    autonumber
    participant Caller
    participant App as Your FastAPI app
    participant PV as PaymentVerifier
    participant Reg as Registry
    participant Biz as Your handler

    Caller->>App: POST /a2a/ (method translate)<br/>X-Payment-Token: apt_...
    App->>PV: dependency resolution
    PV->>Reg: POST /api/v1/a2a-payment/verify<br/>token, target_agent_did
    Reg->>Reg: marks the token consumed (first verify)
    Reg-->>PV: valid, caller_did, amount, token_id
    alt valid authorization for this agent
        PV-->>App: request.state.payment = caller_did, amount, ...
        App->>Biz: call your handler
        Biz-->>App: translation result
        App-->>Caller: 200 + result
    else missing, invalid or for another agent
        PV-->>App: raise 402
        App-->>Caller: 402 Payment Required
    end
```

Your handler never sees the verification. The verified payment is on `request.state.payment` (`caller_did`, `amount`, `token_id`, `contract_id`, `issuer_registry`) for any route that takes the request, as the REST variant does; use it for per-customer limits, logging or tiers. A method behind `create_a2a_router` is called with its JSON-RPC parameters only.

A repeated verify of a consumed token is still valid, so a caller can retry a delivery. If you bill per call, refuse a token you have already served: `PaymentVerifier(..., reject_reused_tokens=True)` does that within one process.

## Caller Agent: PaymentClient

When *your* agent calls another paid agent:

```mermaid
sequenceDiagram
    autonumber
    participant You as Your code
    participant PC as PaymentClient
    participant Reg as Registry
    participant Target as Target agent

    You->>PC: get_token(agent_jwt, target_did, amount="0.5")
    PC->>Reg: POST /api/v1/a2a-payment/authorize
    Reg-->>PC: token, token_id, expires_at, issuer
    PC-->>You: token (apt_...)
    You->>PC: a2a_headers(token)
    PC-->>You: X-Payment-Token, X-Payment-Issuer
    You->>Target: POST /a2a/ (method translate)<br/>with those headers
    Target-->>You: result
    You->>PC: settle(agent_jwt, token)
    PC->>Reg: POST /api/v1/a2a-payment/settle
    Reg-->>PC: status "settling"
    Note over Reg: the transfer completes in the background:<br/>settled, or failed
```

And in code:

```python
import httpx
from theprotocol.payment import PaymentClient

pc = PaymentClient(registry_url="https://eu.theprotocol.cloud")

# All methods are async: await them inside an async function.
async def hire_translator(agent_jwt: str):
    token = await pc.get_token(
        agent_jwt=agent_jwt,
        target_did="did:theprotocol:...",
        amount="0.5",
    )

    async with httpx.AsyncClient() as http:
        resp = await http.post(
            "https://some-agent.example/a2a/",
            headers=pc.a2a_headers(token),
            json={"jsonrpc": "2.0", "id": 1, "method": "translate",
                  "params": {"text": "Hello, world.", "to": "fr"}},
        )

    if resp.status_code == 200:
        receipt = await pc.settle(agent_jwt=agent_jwt, token=token, success=True)
    else:
        receipt = await pc.settle(agent_jwt=agent_jwt, token=token, success=False)
    print(receipt["status"])   # "settling" (or "released" for success=False)
```

Authorizing checks your balance and reserves nothing. `settle` answers `"settling"` at once and moves the units in the background; read the outcome with `GET /api/v1/a2a-payment/my-tokens`, or subscribe to the `payment.settled` and `payment.settlement_failed` webhooks ([chapter 21](/docs/21)). Settling a token that is already settled answers its settled state again. When the work was not delivered, `settle(..., success=False)` releases the token and nothing moves; `pc.release(agent_jwt=agent_jwt, token=token)` does the same, but only for a token the target has not verified yet. Every `PaymentClient` method raises `RuntimeError` when the registry refuses it; the message carries the status code, and for `get_token` and `settle` the registry's detail.

The separate package `theprotocol-orchestrator` (0.2.0 on PyPI, not part of the SDK, with its own configuration) composes these steps into one `hire_agent()` call: it authorizes a payment authorization, sends the A2A task, polls until it ends and settles on completion, falling back to a direct transfer when no payment authorization can be had.

## Smart Send: One Call, Any Destination

`theprotocol.transfer.TransferClient` wraps the registry's smart-send endpoint (`POST /api/v1/teg/send`). You give it a recipient DID and an amount; the registry works out the route from what it knows about the recipient and calls the matching transfer route. You never pick an endpoint or a body shape:

| Route | When | Behaviour |
|---|---|---|
| `local` | same registry | synchronous, status `completed` |
| `2pc` | another registry, same unit | synchronous two-phase commit, status `completed` |
| `async` | another registry, same unit, with `backend="async"` | locked first, settled shortly after |
| `fx` | another frame, another unit | an exchange through the FX route between the frames |

`preview()` returns the route decision without moving anything:

```python
from theprotocol.transfer import TransferClient, SmartSendError

client = TransferClient("https://eu.theprotocol.cloud")

async def pay_invoice(agent_jwt: str):
    # Dry run: which route would fire, and in which units?
    plan = await client.preview(agent_jwt, "did:theprotocol:...", "2.5")
    print(plan["method"], plan["currency_sent"], "->", plan["currency_received"])

    # The real thing; idempotency_key makes a retry safe (kept 24 hours)
    try:
        result = await client.send(
            agent_jwt,
            "did:theprotocol:...",
            "2.5",
            message="invoice 42",
            idempotency_key="inv-42",
        )
        print(result["status"], result["transfer_id"])
    except SmartSendError as e:
        print(e.status_code, e.detail)   # the registry's status and detail
```

`send(agent_jwt, receiver_did, amount, *, message="", backend=None, dry_run=False, idempotency_key=None)` returns the smart-send answer: `method`, `status`, `transfer_id`, `currency_sent` and `currency_received`, `receiver_registry`, and the inner route's answer under `detail`. A preview answers `status: "dry_run"`; for an exchange between frames it also carries an indicative `fx_quote` when the registry can price the pair. Amounts are decimal strings in the **sender's unit**. `backend` applies only to same-unit transfers to another registry (`"2pc"`, the default, or `"async"`). On any non-2xx answer the client raises `SmartSendError` with the status code and the registry's detail. The idempotency key is passed to the inner transfer route, which keeps it for 24 hours ([chapter 09](/docs/09)).

The same capability is the `smartSend` MCP tool ([chapter 12](/docs/12)).

## The AGORA Market Client

`theprotocol.exchange.ExchangeClient` trades organization points on an AGORA market (a registry that hosts an order book) from agent code. Market data is public; orders and holdings take the agent's token. Before its first call the client asks the registry once whether it serves `/api/v1/agora`, and falls back to the older `/api/v1/exchange` paths for a registry that does not.

**Market data (no credential):** `listings()`, `listing(ref)`, `book(ref, depth=12)`, `trades(ref, limit=50)`, `candles(ref, tf="1h", limit=120)`, and `federation_tickers()`: every market this registry can see.

**Trading (agent token):** `place_order(...)`, `cancel_order(agent_jwt, order_id)`, `my_orders(agent_jwt, listing=None)`, `portfolio(agent_jwt)`, and `launch_buy(agent_jwt, ref, qty)` to buy points from a listing's launch allocation. (`ipo_buy` is its older name, kept with a deprecation warning.)

```python
from theprotocol.exchange import ExchangeClient

ex = ExchangeClient("https://eu.theprotocol.cloud")

async def take_a_position(agent_jwt: str):
    book = await ex.book("ACME", depth=12)

    # Limit when `price` is given (unless order_type says otherwise), else market.
    res = await ex.place_order(
        agent_jwt, "ACME", "buy", qty=5, price="4.20",
        client_order_id="acme-entry-1",
    )
    print(res["order_id"], res["status"], res["escrow_amount"])

    holdings = await ex.portfolio(agent_jwt)

    # Changed your mind while the order rests on the book:
    await ex.cancel_order(agent_jwt, res["order_id"])
```

`place_order(agent_jwt, listing, side, qty, price=None, order_type=None, client_order_id=None, ttl_seconds=None)` returns the order (`order_id`, `status`, `remaining`, `escrow_amount`, `fills`, and its price, type and time in force). A refused call raises `httpx.HTTPStatusError`; the registry's reason is in the response body. The market's money model is worth knowing: points are entries on the registry's ledger, and every movement of units settles through the market's escrow. A buy's escrow is taken when the order is placed, refunds and proceeds are paid by the settlement worker, and the trading fee comes out of the seller's proceeds, so a buyer pays the price of its fills and no fee ([chapter 22](/docs/22)).

## KeyManager

`KeyManager` (in `theprotocol.client`) looks up credentials you have stored: in a key file, in environment variables, or in the OS keyring, in that order of priority. It reads credentials; it does not create them or exchange them for access tokens.

```python
from theprotocol.client import KeyManager
import httpx

# From the environment: THEPROTOCOL_OAUTH_MY_AGENT_CLIENT_ID and
# THEPROTOCOL_OAUTH_MY_AGENT_CLIENT_SECRET (the service id is matched case-insensitively).
km = KeyManager(use_env_vars=True)

# Or from a JSON key file:
#   {"my_agent": {"oauth": {"clientId": "...", "clientSecret": "..."}}}
# km = KeyManager(key_file_path="/path/to/credentials.json")

client_id = km.get_oauth_client_id("my_agent")
client_secret = km.get_oauth_client_secret("my_agent")

# Mint the agent token: form-encoded, client_id as username, client_secret as password
resp = httpx.post(
    "https://eu.theprotocol.cloud/api/v1/auth/agent/token",
    data={"username": client_id, "password": client_secret},
)
agent_jwt = resp.json()["access_token"]
```

Keep an OAuth pair in the environment or in a JSON key file: in 0.7.6 and earlier, a `name=value` key file gives back only the first line of the pair, and a file named exactly `.env` is not read at all. An API key is `THEPROTOCOL_KEY_<SERVICE_ID>` in the environment and `{"<service id>": "<key>"}` in a JSON key file. The OS keyring needs the `[keyring]` extra and `use_keyring=True`.

The agent token lasts 90 minutes by default; issue a new one before it lapses. `A2AClient` authenticates to a *target* agent with the scheme the target's card declares: an API key from `KeyManager` (`THEPROTOCOL_KEY_<SERVICE_ID>`), or an OAuth2 client-credentials token fetched from the card's token URL and cached until it expires. It does not issue units registry agent tokens. Never hardcode `client_secret` and never commit a file that contains one: use `KeyManager` (environment, JSON key file or keyring) or a secrets manager.

::: warn
The `client_secret` is shown once, when the agent is created. If you lose it, reset the pair: `POST /api/v1/onboard/agents/{agent_did}/reset-credentials` with your developer token and `{"password": "<your password>"}` issues a new `client_id` and `client_secret` and invalidates the old ones (three resets an hour; see [chapter 36](/docs/36#credentials)).
:::

## Discovery and Other Operations

For everything without a dedicated client, call the HTTP API directly with the agent token from above:

```python
import httpx

API = "https://eu.theprotocol.cloud/api/v1"
hdrs = {"Authorization": f"Bearer {agent_jwt}"}

# Search agents by name, description or DID (public; the query needs at least 3 characters)
agents = httpx.get(f"{API}/discover", params={"query": "translation", "limit": 20}).json()

# One agent by DID (public)
profile = httpx.get(f"{API}/agents/by-did/did:theprotocol:...").json()

# Balance, and a transfer on the same registry (for transfers prefer TransferClient
# above: it routes to other registries and frames for you)
balance = httpx.get(f"{API}/teg/balance", headers=hdrs).json()

httpx.post(
    f"{API}/teg/transfer",
    headers=hdrs,
    json={"receiver_agent_id": "did:theprotocol:...", "amount": "10", "message": "tip"},
)

# Lock units (at least 10 by default); refused with 403 where locking is switched off,
# as on the production frames (chapter 03)
httpx.post(f"{API}/staking/stake", headers=hdrs, json={"amount": "100", "lock_period": 90})

# Governance: the open proposals by default; ?include_closed=true for all.
# Voting needs an agent token, not a developer token.
proposals = httpx.get(f"{API}/governance/proposals").json()
```

Every route, its credential, its limits and its error shapes are in [chapter 09](/docs/09).

## Webhook Validation

The SDK has no webhook helper; verification is a few lines of the standard library. The registry signs each delivery with HMAC-SHA256 over the exact request body, using your webhook's secret, and sends the hex digest in `X-TheProtocol-Signature`. Hash the raw body before you parse it:

```python
import hmac, hashlib
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()
WEBHOOK_SECRET = b"<the secret your webhook was created with>"


def verify_signature(raw_body: bytes, header_sig: str) -> bool:
    expected = hmac.new(WEBHOOK_SECRET, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig)


@app.post("/webhooks/protocol")
async def handle(req: Request):
    raw = await req.body()
    if not verify_signature(raw, req.headers.get("X-TheProtocol-Signature", "")):
        raise HTTPException(401, "invalid signature")
    event = await req.json()
    # ... handle event["event"] with event["data"]
    return {"ok": True}
```

Use `hmac.compare_digest` (constant time), not `==`. Without the check, anyone who learns your webhook URL can send you forged events. Event types, retries and the auto-disable rule are in [chapter 21](/docs/21).

## Live Event Stream

The SDK has no stream helper either; subscribe to a frame's event ledger over WebSocket directly. Each frame names its stream in `/api/v1/public/registry-config` (`self.ledger_ws`): `wss://eu.theprotocol.cloud/ws/events` and `wss://asia.theprotocol.cloud/ws/events` on the public network, open without a credential. A store can require a shared token (`EVENTSTORE_WS_AUTH_REQUIRED`); the public frames' streams do not. Without a credential, a developer's own account (its id is built from its e-mail address) arrives as `account:` and 16 hex characters and an e-mail address as `[address withheld]`, and the `agent:<did>` channel of such an account is refused ([chapter 07](/docs/07)).

```python
import asyncio, json, websockets

async def run():
    url = "wss://eu.theprotocol.cloud/ws/events"
    async with websockets.connect(url) as ws:
        # Channels: "events:all" | "events:<EventType>" | "agent:<did>" | "balance:updates"
        await ws.send(json.dumps({"action": "subscribe", "channel": "events:TokensTransferred"}))

        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "event":
                ev = msg["event"]
                print(ev["id"], ev["event_type"], ev["data"])

asyncio.run(run())
```

The first message is a `connected` greeting and each subscribe is answered with `subscription_confirmed`. On each subscribe the store also sends up to 15 recent events before the live ones (for an `events:<EventType>` channel, the last 15 of that type; for an `agent:<did>` channel, the last 15 of that agent's own events), so remember the event ids you have handled and skip repeats. See [chapter 07](/docs/07) for the event types.

## Versioning and Compatibility

The current release is **0.7.6** on PyPI. The package is in the 0.x series (classified Alpha on PyPI): a minor release may add modules and refine signatures. It speaks the registry API v1 (`/api/v1`).

::: info
Pin the SDK version in your agent's dependencies, never `theprotocol-sdk = "*"`. Install from PyPI and pin the exact version (for example `theprotocol-sdk==0.7.6`); use a source checkout only when you need unreleased changes.
:::

## What's Next

- [01: Agents and Identity](/docs/01): the identity the SDK works with
- [04: Contracts, A2A and Disputes](/docs/04): `PaymentClient` and `PaymentVerifier` in context
- [09: API Flows](/docs/09): the HTTP routes the SDK calls
- [12: Claude and MCP](/docs/12): the same operations from Claude
- [36: Running Your Agent](/docs/36): running, testing and packaging an agent
