#!/usr/bin/env node
/**
 * TheProtocol MCP Stdio Bridge
 *
 * A pure stdio MCP server that proxies tool calls to the production
 * TheProtocol API via JSON-RPC over HTTP POST.
 *
 * Claude Code connects to this via stdio transport (no mcp-remote needed).
 * Supports all 3 tiers — auth token passed per-call via agent_jwt param.
 *
 * §pass68 (2026-05-23) — polish bundle:
 *   - Added theprotocol_bridgeTransfer schema (was missing)
 *   - Monotonic counter for JSON-RPC id (was Date.now(), collision-prone)
 *   - 1 retry with 250ms backoff on transient HTTP 5xx / connection errors
 *   - Configurable timeout via THEPROTOCOL_TIMEOUT_MS env (default 30000)
 *   - Structured JSON-RPC error propagation (was wrapping into text content)
 *   - THEPROTOCOL_DEBUG=true → verbose stderr (every request/response)
 *   - THEPROTOCOL_LOG_FILE=/path → append-only JSONL audit log (opt-in,
 *     sanitized; bridge does NOT phone home, log stays on your disk)
 */

const https = require('https');
const http = require('http');
const fs = require('fs');
const readline = require('readline');

const API_BASE = process.env.THEPROTOCOL_API_URL || 'https://api.theprotocol.cloud';
const API_KEY = process.env.THEPROTOCOL_API_KEY || '';
const REGISTRY = process.env.THEPROTOCOL_REGISTRY || 'A';
const MCP_RPC_PATH = process.env.THEPROTOCOL_MCP_PATH || '/mcp/rpc';  // Use '/mcp/admin/rpc' for admin bridge
// A neutral name: this bridge talks to whichever registry THEPROTOCOL_API_URL names, production or not.
const SERVER_NAME = process.env.THEPROTOCOL_SERVER_NAME || `theprotocol-mcp-bridge${REGISTRY !== 'A' ? '-' + REGISTRY.toLowerCase() : ''}`;

// The protocol versions this bridge answers initialize with: the registry's own table (AgentVault
// agentvault_registry/src/agentvault_registry/mcp/protocol_version.py, SUPPORTED_PROTOCOL_VERSIONS), newest first, and its
// one rule: the client's own version when it is supported, else the newest. tests/bridges/bridge_initialize.test.mjs
// holds this table equal to the registry's and answers each version through the running bridge (§EXTTEST, the dev
// machine's V0649 re-check: a client that asked 2025-06-18 was answered 2024-11-05).
const SUPPORTED_PROTOCOL_VERSIONS = ['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05'];
function negotiateProtocolVersion(params) {
  const requested = params && typeof params === 'object' ? params.protocolVersion : undefined;
  return (typeof requested === 'string' && SUPPORTED_PROTOCOL_VERSIONS.includes(requested))
    ? requested : SUPPORTED_PROTOCOL_VERSIONS[0];
}

// §pass68 — configurable timeout + debug + opt-in client-side log
const TIMEOUT_MS = parseInt(process.env.THEPROTOCOL_TIMEOUT_MS || '30000', 10);
const DEBUG = (process.env.THEPROTOCOL_DEBUG || '').toLowerCase() === 'true';
const LOG_FILE = process.env.THEPROTOCOL_LOG_FILE || null;

// §pass68 — monotonic counter replaces Date.now() to prevent id collisions
// on fast back-to-back tool calls (same-millisecond duplicates).
let _rpc_id_counter = 0;
function nextRpcId() { _rpc_id_counter += 1; return _rpc_id_counter; }

// §pass68 — sanitize args/results before writing to opt-in log. Same deny-list
// strategy as the server-side sanitizer (mcp/audit_sanitizer.py): substring
// match against known sensitive key fragments, recursive.
const SENSITIVE_SUBSTRINGS = ['jwt', 'secret', 'password', 'token', 'api_key', 'apikey', 'private_key', 'privatekey', 'bearer', 'authorization'];
const MAX_STR = 500;
function isSensitiveKey(k) {
  if (typeof k !== 'string') return false;
  const lower = k.toLowerCase();
  return SENSITIVE_SUBSTRINGS.some(s => lower.includes(s));
}
function sanitize(v, k = '') {
  if (k && isSensitiveKey(k)) {
    const len = (v == null) ? 0 : String(v).length;
    return `<redacted:${len} chars>`;
  }
  if (v == null) return v;
  if (Array.isArray(v)) return v.slice(0, 5).map(item => sanitize(item, ''));
  if (typeof v === 'object') {
    const out = {};
    for (const [key, val] of Object.entries(v)) {
      out[key] = sanitize(val, key);
    }
    return out;
  }
  if (typeof v === 'string' && v.length > MAX_STR) {
    return v.slice(0, MAX_STR) + `...<truncated:${v.length - MAX_STR} more>`;
  }
  return v;
}
function logCall(direction, tool, args, outcome, error, latencyMs) {
  if (!LOG_FILE && !DEBUG) return;
  let line;
  try {
    line = JSON.stringify({
      ts: new Date().toISOString(),
      bridge: SERVER_NAME,
      direction,
      tool,
      args: sanitize(args || {}),
      outcome,
      error: error ? String(error).slice(0, 500) : null,
      latency_ms: latencyMs == null ? null : Math.round(latencyMs * 10) / 10,
    });
  } catch {
    line = JSON.stringify({ ts: new Date().toISOString(), tool, _log_serialize_failed: true });
  }
  if (DEBUG) process.stderr.write(line + '\n');
  if (LOG_FILE) {
    try { fs.appendFileSync(LOG_FILE, line + '\n'); }
    catch (e) { if (DEBUG) process.stderr.write(`[bridge log write failed: ${e.message}]\n`); }
  }
}

// ── Tool schemas (fetched from prod /mcp/tools) ──────────────────────────

const TOOLS = [
  {
    name: "theprotocol_discoverRegistries",
    description: "List federated registries known to this TheProtocol node. Returns public status, federation health, and compliance score for each peer. No authentication required.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "theprotocol_discoverAgents",
    description: "Search for AI agents on TheProtocol sovereign agent registry. Filter by name, description, DID, or capability. No authentication required.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Search text matching agent name, description, or DID", default: "" },
        capability: { type: "string", description: "Filter by agent capability tag", default: "" },
        limit: { type: "integer", description: "Maximum results to return (default 10, max 50)", default: 10, minimum: 1, maximum: 50 },
        offset: { type: "integer", description: "Pagination offset", default: 0, minimum: 0 }
      }
    }
  },
  {
    name: "theprotocol_getAgentProfile",
    description: "Get the full profile of a specific AI agent by DID. Returns name, description, reputation score, balances, capabilities, and card data.",
    inputSchema: {
      type: "object",
      properties: {
        agent_did: { type: "string", description: "Agent DID (e.g. did:cos:c34f2070-4c1d-05bf-54c9)" }
      },
      required: ["agent_did"]
    }
  },
  {
    name: "theprotocol_getNetworkStats",
    description: "Get TheProtocol network health statistics including total agents, total value locked (TVL), active disputes, governance participation, and APY range.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "theprotocol_getGovernanceProposals",
    description: "List governance proposals in the Agent Senate. Filter by status: 'VOTING' (open), 'PASSED', 'FAILED', or 'all'. Requires developer JWT or API key authentication.",
    inputSchema: {
      type: "object",
      properties: {
        status: { type: "string", description: "Filter: 'VOTING' (default), 'PASSED', 'FAILED', or 'all'", default: "VOTING", enum: ["VOTING", "PASSED", "FAILED", "all"] },
        limit: { type: "integer", description: "Maximum results (default 10, max 50)", default: 10 }
      }
    }
  },
  {
    name: "theprotocol_getApyRates",
    description: "Get current dynamic APY rates for staking AVT tokens on TheProtocol. Returns APY for flexible and locked staking tiers (30d, 90d, 180d, 365d) based on the logistic decay curve and current TVL ratio.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "theprotocol_getMyBalance",
    description: "Get your agent's AVT token balance, staking positions, and veToken governance power. Requires agent JWT authentication. Pass agent_jwt directly to avoid bridge reconfiguration.",
    inputSchema: {
      type: "object",
      properties: {
        agent_jwt: { type: "string", description: "Optional: agent JWT from getAgentToken. If provided, overrides the bridge header token." }
      }
    }
  },
  {
    name: "theprotocol_transferTokens",
    description: "Transfer AVT tokens to another agent on TheProtocol. Requires agent JWT authentication.",
    inputSchema: {
      type: "object",
      properties: {
        recipient_did: { type: "string", description: "DID of the receiving agent" },
        amount: { type: "string", description: "Amount of AVT to transfer (as numeric string, e.g. '10.5')" },
        message: { type: "string", description: "Optional transfer memo (max 256 chars)", default: "" },
        agent_jwt: { type: "string", description: "Optional: agent JWT from getAgentToken. If provided, overrides the bridge header token." }
      },
      required: ["recipient_did", "amount"]
    }
  },
  {
    name: "theprotocol_stakeTokens",
    description: "Stake AVT tokens to earn dynamic APY rewards and gain veToken governance power. Longer lock periods = higher APY. Requires agent JWT authentication.",
    inputSchema: {
      type: "object",
      properties: {
        amount: { type: "string", description: "AVT amount to stake (as numeric string)" },
        lock_period_days: { type: "integer", description: "Lock duration in days: 0 (flexible), 7, 30, 90, 180, or 365", default: 30, enum: [0, 7, 30, 90, 180, 365] },
        agent_jwt: { type: "string", description: "Optional: agent JWT from getAgentToken. If provided, overrides the bridge header token." }
      },
      required: ["amount"]
    }
  },
  {
    name: "theprotocol_unstakeTokens",
    description: "Unstake a staking position by its ID and reclaim AVT tokens. The position must belong to your agent and be past its lock period. Requires agent JWT authentication.",
    inputSchema: {
      type: "object",
      properties: {
        stake_id: { type: "string", description: "ID of the stake position to unstake (from stakeTokens or my-positions)" },
        agent_jwt: { type: "string", description: "Optional: agent JWT from getAgentToken. If provided, overrides the bridge header token." }
      },
      required: ["stake_id"]
    }
  },
  {
    name: "theprotocol_castVote",
    description: "Vote on an Agent Senate governance proposal. Voting power is calculated from your staked positions using the veToken formula. Each agent can only vote once per proposal. Requires agent JWT authentication.",
    inputSchema: {
      type: "object",
      properties: {
        proposal_id: { type: "integer", description: "ID of the governance proposal" },
        vote_in_favor: { type: "boolean", description: "True = vote FOR, False = vote AGAINST" },
        reason: { type: "string", description: "Optional explanation for your vote (max 1000 chars)", default: "" },
        agent_jwt: { type: "string", description: "Optional: agent JWT from getAgentToken. If provided, overrides the bridge header token." }
      },
      required: ["proposal_id", "vote_in_favor"]
    }
  },
  {
    // §pass68 — added 2026-05-23. Was missing from the bridge despite being live in the
    // server's TOOL_DISPATCH since SF-3 (cross-frame wrapped-token bridge transfer).
    name: "theprotocol_bridgeTransfer",
    description: "SF-3 cross-frame wrapped-token bridge transfer. Locks AVT on the source frame and mints w-AVT on the destination frame via the SPIRE-secured token bridge. Cross-frame transfers settle within the next bridge cycle (~60s) and are observable via the Bridge admin view. Requires agent JWT authentication.",
    inputSchema: {
      type: "object",
      properties: {
        recipient_did: { type: "string", description: "DID of the receiving agent on the destination frame" },
        amount: { type: "string", description: "Amount of AVT to bridge (as numeric string, e.g. '10.5')" },
        destination_frame: { type: "string", description: "Destination frame identifier", enum: ["frame-a", "frame-b"] },
        memo: { type: "string", description: "Optional transfer memo (max 256 chars)", default: "" },
        agent_jwt: { type: "string", description: "Optional: agent JWT from getAgentToken. If provided, overrides the bridge header token." }
      },
      required: ["recipient_did", "amount", "destination_frame"]
    }
  },
  {
    name: "theprotocol_getAgentToken",
    description: "Obtain an agent JWT using OAuth2 client_credentials flow. Pass the agent's client_id and client_secret to receive a Bearer token that unlocks Tier 2 tools: getMyBalance, transferTokens, stakeTokens, unstakeTokens, castVote. No authentication required to call this tool.",
    inputSchema: {
      type: "object",
      properties: {
        client_id: { type: "string", description: "Agent OAuth2 client_id (e.g. agent-90663061387409b6)" },
        client_secret: { type: "string", description: "Agent OAuth2 client_secret (cos_secret_...)" }
      },
      required: ["client_id", "client_secret"]
    }
  },
  {
    name: "theprotocol_getMyAgents",
    description: "List all AI agents registered under your developer account on TheProtocol. Returns DIDs, credentials, balances, reputation scores. Requires developer JWT or API key authentication.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "theprotocol_createAgent",
    description: "Register a new AI agent on TheProtocol. Creates a DID, generates OAuth 2.0 credentials (client_id + client_secret), and sets up the Agent Card. The client_secret is shown ONCE — store it immediately. Requires developer JWT authentication.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Agent display name (max 100 chars)" },
        description: { type: "string", description: "Description of the agent's purpose and capabilities" },
        capabilities: { type: "array", items: { type: "string" }, description: "Optional list of capability tags", default: [] }
      },
      required: ["name", "description"]
    }
  },
  {
    name: "theprotocol_submitDispute",
    description: "File a dispute against an agent in TheProtocol's decentralized dispute resolution system. Requires developer JWT authentication.",
    inputSchema: {
      type: "object",
      properties: {
        complainant_did: { type: "string", description: "DID of the agent filing the complaint" },
        defendant_did: { type: "string", description: "DID of the accused agent" },
        description: { type: "string", description: "Description of the grievance" },
        evidence: { type: "object", description: "Optional additional evidence data", default: {} }
      },
      required: ["complainant_did", "defendant_did", "description"]
    }
  },
  {
    name: "theprotocol_createProposal",
    description: "Create a new governance proposal in the Agent Senate. IMPORTANT: Requires an agent JWT (not developer JWT). Call getAgentToken first, then pass the result as agent_jwt.",
    inputSchema: {
      type: "object",
      properties: {
        title: { type: "string", description: "Short proposal title (max 200 chars)" },
        description: { type: "string", description: "Detailed description of the proposal" },
        duration_days: { type: "integer", description: "Voting duration in days (1-30, default 7)", default: 7, minimum: 1, maximum: 30 },
        proposal_type: { type: "string", description: "'standard' (50% majority) or 'policy_change' (66% supermajority)", default: "standard", enum: ["standard", "policy_change"] },
        agent_jwt: { type: "string", description: "Agent JWT from getAgentToken. REQUIRED for governance." }
      },
      required: ["title", "description", "agent_jwt"]
    }
  }
];

// ── Dynamic tool loading for non-default bridges ──────────────────────────
// If MCP_RPC_PATH is not the default, fetch tools from the server instead of
// using the hardcoded TheProtocol tools list. We kick off the fetch at startup
// AND make tools/list wait for it — avoids the race where Claude Code asks for
// the tool list before the async fetch resolves (which was causing the games-*
// bridges to expose theprotocol_* tools instead of td_*, snake_*, etc.).
let dynamicTools = null;

async function fetchToolsFromServer() {
  const toolsUrl = `${API_BASE}${MCP_RPC_PATH.replace('/rpc', '/tools')}`;
  return new Promise((resolve) => {
    const parsed = new URL(toolsUrl);
    const transport = parsed.protocol === 'https:' ? https : http;
    const headers = {};
    if (API_KEY) headers['Authorization'] = `Bearer ${API_KEY}`;
    transport.get({ hostname: parsed.hostname, port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80), path: parsed.pathname, headers }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const result = JSON.parse(data);
          const tools = result.tools || [];
          resolve(tools.map(t => ({
            name: t.name,
            description: t.description,
            inputSchema: t.inputSchema || t.input_schema || { type: "object", properties: {} }
          })));
        } catch { resolve(null); }
      });
    }).on('error', () => resolve(null));
  });
}

// §pass71.9 (2026-05-25) — REMOVED the `if (MCP_RPC_PATH !== '/mcp/rpc')` gate.
// Previously the bridge only fetched the live tool list dynamically for NON-
// default paths (games-* sub-servers etc); the default `/mcp/rpc` path returned
// the hardcoded TOOLS array (~17 entries) and never saw the §pass70 expansion's
// 360+ new tools server-side. As a result Claude Code only ever saw 17 tools
// regardless of how many the server actually registered. Fix: ALWAYS try the
// dynamic fetch first, fall back to TOOLS only on connection failure.
// Confirmed broken before fix: 380 tools server-side, 17 bridge-reported.
let dynamicToolsPromise = (async () => {
  // Retry a couple of times with short backoff — handles the case where the
  // bridge spawns before the registry is fully ready.
  for (let attempt = 0; attempt < 5; attempt++) {
    const tools = await fetchToolsFromServer();
    if (tools && tools.length > 0) {
      dynamicTools = tools;
      process.stderr.write(`[${SERVER_NAME}] Loaded ${tools.length} tools from ${MCP_RPC_PATH}\n`);
      return tools;
    }
    await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
  }
  process.stderr.write(`[${SERVER_NAME}] WARNING: Could not fetch tools from ${MCP_RPC_PATH} after retries — falling back to hardcoded TheProtocol tools (${TOOLS.length} entries)\n`);
  return null;
})();

async function getTools() {
  // §pass71.9 — prefer the dynamic server-side list (always up-to-date with
  // whatever the server registered, including §pass70 expansion). Fall back
  // to hardcoded TOOLS only if the dynamic fetch failed entirely.
  if (dynamicTools) return dynamicTools;
  if (dynamicToolsPromise) {
    await dynamicToolsPromise;
    if (dynamicTools) return dynamicTools;
  }
  return TOOLS;
}

// ── HTTP POST helper ──────────────────────────────────────────────────────

function postJSONOnce(url, body, authToken) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const isHttps = parsed.protocol === 'https:';
    const transport = isHttps ? https : http;
    const payload = JSON.stringify(body);
    const headers = {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(payload),
      'Accept': 'application/json',
    };
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const req = transport.request({
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: parsed.pathname,
      method: 'POST',
      headers,
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        const ctype = (res.headers['content-type'] || '').toLowerCase();
        // §pass68 — return parsed body + status code so caller can decide retry
        let parsedBody;
        try { parsedBody = JSON.parse(data); }
        catch { parsedBody = { raw: data }; }
        resolve({ status: res.statusCode, body: parsedBody, contentType: ctype });
      });
    });
    req.on('error', err => reject(err));
    req.setTimeout(TIMEOUT_MS, () => { req.destroy(); reject(new Error(`Request timeout after ${TIMEOUT_MS}ms`)); });
    req.write(payload);
    req.end();
  });
}

// §pass68 — wrapper with 1 retry on transient 5xx / connection error.
// 4xx responses are NOT retried (auth, validation — caller's problem).
async function postJSON(url, body, authToken) {
  try {
    const res = await postJSONOnce(url, body, authToken);
    if (res.status >= 500 && res.status < 600) {
      // Transient — back off 250ms and try once more
      await new Promise(r => setTimeout(r, 250));
      try { return await postJSONOnce(url, body, authToken); }
      catch { return res; }  // second attempt also failed; return first response
    }
    return res;
  } catch (err) {
    // Connection-level error (ECONNRESET, timeout, etc.) — retry once
    await new Promise(r => setTimeout(r, 250));
    return await postJSONOnce(url, body, authToken);
  }
}

// ── Call tool via prod JSON-RPC ───────────────────────────────────────────

async function callTool(toolName, args) {
  // Determine auth token: agent_jwt in args, or API_KEY from env
  const token = args.agent_jwt || API_KEY || null;

  const rpcBody = {
    jsonrpc: "2.0",
    id: nextRpcId(),   // §pass68 — monotonic, collision-free
    method: "tools/call",
    params: { name: toolName, arguments: args }
  };

  const startedAt = process.hrtime.bigint();
  let outcome = 'success';
  let errForLog = null;
  try {
    logCall('request', toolName, args, null, null, null);
    const response = await postJSON(`${API_BASE}${MCP_RPC_PATH}`, rpcBody, token);
    const elapsedMs = Number((process.hrtime.bigint() - startedAt)) / 1e6;
    const body = response.body || {};

    // §pass68 — propagate structured JSON-RPC errors back to Claude instead of
    // smushing them into text content. mcp-remote / Claude can then reason
    // about retry vs. surface to user.
    if (body && body.error) {
      outcome = 'error';
      errForLog = body.error;
      logCall('response', toolName, args, outcome, JSON.stringify(body.error), elapsedMs);
      // Re-raise as a JSON-RPC error from the outer message handler. We do
      // this by throwing a structured error object the handler recognizes.
      const e = new Error(body.error.message || 'tool error');
      e.code = body.error.code || -32603;
      e.data = body.error.data;
      throw e;
    }
    if (body && body.result !== undefined) {
      logCall('response', toolName, args, outcome, null, elapsedMs);
      return body.result;
    }
    // Unstructured / non-JSON-RPC response — wrap as before but flag in log
    outcome = 'unstructured';
    logCall('response', toolName, args, outcome, null, elapsedMs);
    return { content: [{ type: "text", text: JSON.stringify(body) }], isError: false };
  } catch (err) {
    if (!errForLog) {
      const elapsedMs = Number((process.hrtime.bigint() - startedAt)) / 1e6;
      logCall('response', toolName, args, 'error', err.message || String(err), elapsedMs);
    }
    throw err;
  }
}

// ── MCP stdio protocol handler ────────────────────────────────────────────

function send(msg) {
  const str = JSON.stringify(msg);
  process.stdout.write(str + '\n');
}

function handleMessage(msg) {
  const id = msg.id;
  const method = msg.method;
  const params = msg.params || {};

  if (method === 'initialize') {
    send({
      jsonrpc: '2.0', id,
      result: {
        protocolVersion: negotiateProtocolVersion(params),
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: SERVER_NAME, version: '1.0.0' }
      }
    });
    return;
  }

  if (method === 'notifications/initialized' || method.startsWith('notifications/')) {
    // No response needed for notifications
    return;
  }

  if (method === 'ping') {
    send({ jsonrpc: '2.0', id, result: {} });
    return;
  }

  if (method === 'tools/list') {
    getTools()
      .then(tools => send({ jsonrpc: '2.0', id, result: { tools } }))
      .catch(err => send({ jsonrpc: '2.0', id, error: { code: -32603, message: err.message } }));
    return;
  }

  if (method === 'tools/call') {
    const toolName = params.name;
    const args = params.arguments || {};
    callTool(toolName, args)
      .then(result => send({ jsonrpc: '2.0', id, result }))
      .catch(err => {
        // §pass68 — preserve JSON-RPC error structure when available
        const errorObj = {
          code: err.code || -32603,
          message: err.message || 'Internal error',
        };
        if (err.data !== undefined) errorObj.data = err.data;
        send({ jsonrpc: '2.0', id, error: errorObj });
      });
    return;
  }

  if (method === 'resources/list') {
    send({ jsonrpc: '2.0', id, result: { resources: [] } });
    return;
  }

  if (method === 'prompts/list') {
    send({ jsonrpc: '2.0', id, result: { prompts: [] } });
    return;
  }

  // Unknown method
  send({
    jsonrpc: '2.0', id,
    error: { code: -32601, message: `Method not found: ${method}` }
  });
}

// ── Main: read JSON-RPC from stdin ────────────────────────────────────────

const rl = readline.createInterface({ input: process.stdin, terminal: false });

rl.on('line', (line) => {
  if (!line.trim()) return;
  try {
    const msg = JSON.parse(line);
    handleMessage(msg);
  } catch (err) {
    send({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Parse error' } });
  }
});

// Suppress unhandled rejections from crashing
process.on('unhandledRejection', () => {});

process.stderr.write(`[${SERVER_NAME}] MCP stdio bridge started → ${API_BASE}${MCP_RPC_PATH}\n`);
