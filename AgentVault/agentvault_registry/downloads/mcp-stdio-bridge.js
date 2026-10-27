#!/usr/bin/env node
/**
 * TheProtocol MCP Stdio Bridge
 *
 * A pure stdio MCP server that proxies tool calls to the production
 * TheProtocol API via JSON-RPC over HTTP POST.
 *
 * Claude Code connects to this via stdio transport (no mcp-remote needed).
 * Supports all 3 tiers — auth token passed per-call via agent_jwt param.
 */

const https = require('https');
const http = require('http');
const readline = require('readline');

const API_BASE = process.env.THEPROTOCOL_API_URL || 'https://api.theprotocol.cloud';
const API_KEY = process.env.THEPROTOCOL_API_KEY || '';
const REGISTRY = process.env.THEPROTOCOL_REGISTRY || 'A';
const MCP_RPC_PATH = process.env.THEPROTOCOL_MCP_PATH || '/mcp/rpc';  // Use '/mcp/admin/rpc' for admin bridge
const SERVER_NAME = process.env.THEPROTOCOL_SERVER_NAME || `theprotocol-prod${REGISTRY !== 'A' ? '-' + REGISTRY.toLowerCase() : ''}`;

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

// For non-default paths we need the dynamic tools BEFORE the first tools/list
// call. Kick off the fetch eagerly and keep the promise so handlers can await.
let dynamicToolsPromise = null;
if (MCP_RPC_PATH !== '/mcp/rpc') {
  dynamicToolsPromise = (async () => {
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
    process.stderr.write(`[${SERVER_NAME}] WARNING: Could not fetch tools from ${MCP_RPC_PATH} after retries — falling back to default TheProtocol tools\n`);
    return null;
  })();
}

async function getTools() {
  if (MCP_RPC_PATH === '/mcp/rpc') return TOOLS;
  if (dynamicTools) return dynamicTools;
  if (dynamicToolsPromise) {
    await dynamicToolsPromise;
    if (dynamicTools) return dynamicTools;
  }
  return TOOLS;
}

// ── HTTP POST helper ──────────────────────────────────────────────────────

function postJSON(url, body, authToken) {
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
        try { resolve(JSON.parse(data)); }
        catch { resolve({ raw: data }); }
      });
    });
    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('Request timeout')); });
    req.write(payload);
    req.end();
  });
}

// ── Call tool via prod JSON-RPC ───────────────────────────────────────────

async function callTool(toolName, args) {
  // Determine auth token: agent_jwt in args, or API_KEY from env
  const token = args.agent_jwt || API_KEY || null;

  const rpcBody = {
    jsonrpc: "2.0",
    id: Date.now(),
    method: "tools/call",
    params: { name: toolName, arguments: args }
  };

  const result = await postJSON(`${API_BASE}${MCP_RPC_PATH}`, rpcBody, token);

  if (result.error) {
    return { content: [{ type: "text", text: `Error: ${JSON.stringify(result.error)}` }], isError: true };
  }
  if (result.result) {
    return result.result;
  }
  return { content: [{ type: "text", text: JSON.stringify(result) }], isError: false };
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
        protocolVersion: '2024-11-05',
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
      .catch(err => send({
        jsonrpc: '2.0', id,
        error: { code: -32603, message: err.message }
      }));
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
