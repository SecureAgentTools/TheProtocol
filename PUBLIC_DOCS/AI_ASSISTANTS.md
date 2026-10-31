<!-- GENERATED from AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs/operator/13_ai_assistants.md by scripts/distribution/gen_public_docs.py. Edit that file, not this copy: the export refuses a copy that differs from its source. -->

# Operator Guide: AI Assistants & MCP
**Audience**: Federated and standalone registry operators
**Prerequisite**: A running registry and a developer account on it (section 2 creates the key)
**Checked against the source**: 2026-10-16 (V0618: `mcp/server.py`, `mcp/server_admin.py`, `mcp/oauth.py`, `routers/downloads.py`, the two bridge files)

---

## 1. Your Registry Speaks MCP Natively

Every TheProtocol registry serves its own **Model Context Protocol** server, from the same image that serves your API:
there is nothing to install on the registry. An assistant connected to it can discover agents, read balances and move
units, open and release locks where the registry allows them, take part in governance and, with an administrator's
credential, run the registry's admin tools. The registry also serves a manual written for assistants, so an assistant
can orient itself on your node without guessing.

| Surface | Endpoint | Credential |
|---------|----------|------------|
| MCP over Streamable HTTP | `POST /mcp` (`GET` for notifications, `DELETE` to end a session) | a Bearer token on every tool call: an API key (`avreg_...`), a developer JWT or an agent JWT |
| MCP JSON-RPC, for older clients | `POST /mcp/rpc` | the same |
| MCP over SSE | `GET /mcp/sse`, `POST /mcp/sse` | the same |
| Admin MCP | `POST /mcp/admin`, `POST /mcp/admin/rpc`, `GET` and `POST /mcp/admin/sse` | an administrator's API key or developer JWT |
| Tool lists | `GET /mcp/tools`, `GET /mcp/admin/tools` | none |
| OAuth sign-in for MCP clients | `/.well-known/oauth-protected-resource`, `/oauth/authorize`, `/oauth/token` | your developer login |
| Manual for assistants | `GET /api/v1/downloads/CLAUDE.md` | none |
| stdio bridges | `GET /api/v1/downloads/mcp-stdio-bridge.js`, `GET /api/v1/downloads/mcp-stdio-bridge-admin.js` | none |
| What can be downloaded | `GET /api/v1/downloads/manifest` | none |

The handshake and the listings (`initialize`, `tools/list`, `resources/list`, `prompts/list`) need no credential. A
tool call without one is answered 401 with a pointer to the OAuth sign-in.

::: tip The five-second orientation
`curl <your-registry-url>/api/v1/downloads/CLAUDE.md` returns a manual **generated for your deployment**: your URL,
your registry's name and role (frame or cloud operator), its unit of account, its trust domain and whether issuance
works there are already filled in. Paste it into any assistant (or point Claude Code at it) and the assistant knows how
to log in, create agents and move units on *this* registry without guessing a single value.
:::

The registry URL in that manual is the one this registry's agent credentials name: `create_agent`, a credential reset
and a rotation return it as `registry_url`. The manifest says what a download can be checked against. A file served
as it is stored has its `size_bytes` and `sha256`, and the download matches both. `CLAUDE.md` is generated per request,
so its entry reads `rendered_per_request: true` and gives no size or digest; `template_size_bytes` and
`template_sha256` describe the template it is generated from, not what you download.

---

## 2. Create the Key

MCP authenticates with a developer API key, issued once and shown once:

```bash
curl -X POST <your-registry-url>/api/v1/auth/api-keys \
  -H "Authorization: Bearer <developer-jwt>" \
  -H "Content-Type: application/json" \
  -d '"assistant bridge key"'
```

The response's `plain_api_key` (`avreg_...`) is the credential. A key gets every scope (`["*"]`) and a 365-day expiry
(`API_KEY_DEFAULT_TTL_DAYS`) unless you narrow them: the body also takes `{"key_name": ..., "scopes": [...],
"expires_in_days": ...}`, where `0` days means it never expires. An ordinary developer's key reaches the public
surface; a key issued by an administrator account also opens the admin surface. Changing your password does not
revoke a key: revoke it in Settings or with `DELETE /api/v1/auth/api-keys/{key_id}`.

A client that supports MCP's OAuth sign-in needs no key from you: it finds the sign-in through
`/.well-known/oauth-protected-resource`, you log in on your registry's own page, and the client receives an API key
scoped to `mcp:tools` (`mcp:admin` as well, when it asks for the admin surface).

---

## 3. Connect Claude Code or Claude Desktop

**Over HTTP.** Point the client at `<your-registry-url>/mcp` with the header `Authorization: Bearer avreg_...`, or let
it sign in through OAuth. This gives the full catalog, the resources and prompts, and the options of section 4.

**Through the stdio bridge.** Download the bridge from your own registry and register it in `.mcp.json` (Claude Code)
or `claude_desktop_config.json` (Claude Desktop). It runs on Node.js:

```bash
curl -sO <your-registry-url>/api/v1/downloads/mcp-stdio-bridge.js
```

```json
{
  "mcpServers": {
    "my-registry": {
      "command": "node",
      "args": ["/path/to/mcp-stdio-bridge.js"],
      "env": {
        "THEPROTOCOL_API_URL": "<your-registry-url>",
        "THEPROTOCOL_API_KEY": "avreg_..."
      }
    }
  }
}
```

Always set `THEPROTOCOL_API_URL`: the bridge's default is `https://api.theprotocol.cloud`. The public bridge offers a
fixed set of tools of its own (16 in the bridge V0618 serves: discovery, balances, transfers, locks, votes and
proposals, agent creation, disputes) and sends each call to `/mcp/rpc` with your key, or with an agent JWT you pass as
the call's `agent_jwt`. Set
`THEPROTOCOL_MCP_PATH` to another surface, for example `/mcp/admin/rpc` with an administrator's key, and it loads that
surface's whole tool list instead. The admin bridge, `mcp-stdio-bridge-admin.js`, carries five tools of its own
(`adminGetDeveloperToken`, `adminRequest`, `adminQueryEventStore`, `adminPromQuery`, `adminGrafanaQuery`) and always
calls `/mcp/admin/rpc`. Neither bridge passes on resources or prompts. The bridge **code** is public on purpose: it
contains no secrets, and its authority comes entirely from the key you configure.

Restart the client after editing its configuration; the tools appear under the server name you chose.

---

## 4. Keeping the Tool Catalog Small

The full catalog is large: in V0618, about 450 tools on the public surface and over 300 on the admin surface. Clients
with limited context can ask the server for less, on `/mcp`, `/mcp/rpc`, `/mcp/sse` and `/mcp/tools` alike:

- `?mode=gateway` (or the header `X-MCP-Mode: gateway`) lists a compact core (agent token, discovery, network stats,
  the registry card, balance, transfers, your agents) plus `listToolsets`, `searchTools`, `describeTools`,
  `invokeTool`, `enableToolset` and `disableToolset`: the assistant finds and calls everything else on demand.
- `?toolsets=wallet,discovery` (or `X-MCP-Toolsets`) lists only the named buckets, plus the core. The public buckets
  are `core`, `discovery`, `wallet`, `payments-a2a`, `staking-rewards`, `governance`, `exchange`, `guild`,
  `identity`, `dev-lifecycle`, `account` and `fiat`, and the curated `pocket` set; the admin surface has buckets of
  its own, listed by `/mcp/admin/tools`. An unknown mode or bucket is refused with the valid names.
- `enableToolset` keeps a selection for your credential for 24 hours.
- No parameter: the full catalog.

Beyond tools, the server publishes MCP **resources** (your signed registry card, the solvency card, the JWKS, the
OpenAPI document, live network stats, and any agent's card by DID) and **prompts** (seven guided flows, from
onboarding an agent to diagnosing a failed transfer). `resources/list` and `prompts/list` enumerate them.

---

## 5. What the Assistant Can and Cannot Do

Tools follow the API's auth tiers. Public reads (about 100 tools) run with any credential. Agent tools (about 110)
act as an agent: give them an agent JWT as the Bearer token or as the call's `agent_jwt` argument (the
`getAgentToken` tool issues one from `client_id` and `client_secret`). Developer tools (about 225) act as the developer
who owns the key or JWT, and the admin surface requires an administrator. **An assistant holding your key can do what
you can do**: treat the key like a password, scope it if you do not need everything, and revoke it when in doubt.

Two properties worth knowing as an operator:

- **Tool calls can be audited.** With `MCP_AUDIT_LOGGING_ENABLED=true`, every `tools/call` writes a security-audit
  row on your registry with the sanitized arguments and the outcome, so an assistant's action is as traceable as a
  person's. The code default is off; frames built from the kit's template and the operators a frame provisions turn
  it on. You read your own rows at `GET /api/v1/me/mcp-audit-log`; an administrator reads anyone's at
  `GET /api/v1/admin/mcp-audit-log`.
- **Tool behavior is annotated.** Every tool carries a title and the `readOnlyHint`, `destructiveHint`,
  `idempotentHint` and `openWorldHint` annotations, so a client knows which calls are safe to retry.

### Hand it the manual

Your registry serves a written operating manual for exactly this purpose:

```
GET {REGISTRY_URL}/api/v1/downloads/CLAUDE.md
```

It is rendered per request with your registry's own facts substituted in, so an assistant reading it gets your URLs
and your posture rather than a generic example. It covers the three identity tiers and how to stop confusing them,
creating agents, moving units (the organization treasury included), what issuance will and will not do on your node,
the regulatory-authorization rail, and how to read the error shapes. Point an assistant at it before asking it to
operate anything. Operator chapter 21 is a shorter, generic briefing of the same kind; the served manual is the one
filled in for your registry.

### Authorization will refuse an assistant, and that is correct

Where agent authorization is enforcing on your registry (see [chapter 24](https://docs.theprotocol.cloud/learn/agent-access)), an assistant acting as one of
your agents is bound by that agent's roles, spend policy and capability caveats. A `403` from those gates is a right
answer, not a broken tool.

Two habits save a lot of confused debugging:

- **Read the refusal rather than guessing.** `GET /api/v1/agents/{did}/authz/denials` (as the agent's owner) names what
  was refused and why. It is the fastest path from "the assistant says it cannot transfer" to the missing permission.
- **Do not switch enforcement off to unblock automation.** Where the capability circuit breaker is on
  (`CAPABILITY_CIRCUIT_BREAKER_ENABLED`, with delegation enforcing; frames built from the kit's template have both),
  five misuse refusals of one capability permit within five minutes (a wrong holder, a revoked token presented again,
  an action outside its caveats) revoke that token and every token derived from it. That is the breaker doing its job:
  fix the authority, not the gate.

---

## 6. Host Operations From an Assistant

The registry's MCP server covers the *platform*. For the *host* (container status, logs, restarts, backups, SPIRE
entries) the `tp` CLI has its own MCP mode, a stdio server with 21 tools whose destructive ones need `confirm: true`:

```bash
tp mcp serve     # stdio MCP server exposing the CLI's commands as tools
tp mcp tools     # list what it would expose
```

Wire it into `.mcp.json` like the bridge above (command `tp`, args `["mcp", "serve"]`, and `"--operator", "<name>"`
on a host with several operators) and an assistant can run day-2 operations. Operator chapter 12 (the Host CLI) lists
the tools and what each command really does.

::: info One key, one registry
API keys are **per registry**: a key issued on one registry is unknown to every other. If you operate several nodes,
create a key on each and give the assistant one entry per node.
:::
