#!/usr/bin/env node
/**
 * TheProtocol MCP Admin Stdio Bridge
 *
 * Proxies admin tool calls to /mcp/admin/rpc on the registry.
 * 5 admin tools: adminRequest, adminQueryEventStore, adminPromQuery,
 * adminGrafanaQuery, getDeveloperToken.
 */

const https = require('https');
const http = require('http');
const readline = require('readline');

const API_BASE = process.env.THEPROTOCOL_API_URL || 'https://api.theprotocol.cloud';
const API_KEY = process.env.THEPROTOCOL_API_KEY || '';
const REGISTRY = process.env.THEPROTOCOL_REGISTRY || 'A';
// A neutral name: this bridge talks to whichever registry THEPROTOCOL_API_URL names, production or not.
const SERVER_NAME = process.env.THEPROTOCOL_SERVER_NAME || `theprotocol-mcp-admin-bridge${REGISTRY !== 'A' ? '-' + REGISTRY.toLowerCase() : ''}`;

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

const TOOLS = [
  {
    name: "theprotocol_adminGetDeveloperToken",
    description: "Authenticate as a developer and receive a JWT. Pass this JWT as developer_jwt to other admin tools. No auth required to call this tool itself.",
    inputSchema: {
      type: "object",
      properties: {
        email: { type: "string", description: "Developer email" },
        password: { type: "string", description: "Developer password" }
      },
      required: ["email", "password"]
    }
  },
  {
    name: "theprotocol_adminRequest",
    description: "Commander-only: proxy any HTTP request to the TheProtocol registry API. Full access to all ~200+ endpoints. Example: /api/v1/admin/dashboard, /api/v1/teg/treasury/balance, /api/v1/governance/proposals.",
    inputSchema: {
      type: "object",
      properties: {
        method: { type: "string", enum: ["GET", "POST", "PUT", "DELETE", "PATCH"], description: "HTTP method" },
        endpoint: { type: "string", description: "Registry API path, e.g. /api/v1/admin/dashboard" },
        body: { type: "object", description: "JSON request body (for POST/PUT/PATCH)" },
        params: { type: "object", description: "Query parameters dict" },
        developer_jwt: { type: "string", description: "Optional: developer JWT from adminGetDeveloperToken. Overrides bridge token." }
      },
      required: ["method", "endpoint"]
    }
  },
  {
    name: "theprotocol_adminQueryEventStore",
    description: "Commander-only: query the EventStore immutable ledger. Paths: /api/v1/events/ (all events, ?limit=N), /api/v1/events/aggregate/{did}, /api/v1/projections/stats, /api/v1/projections/balances, /api/v1/projections/transactions/{agent_id}.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "EventStore API path, e.g. /api/v1/events/" },
        params: { type: "object", description: "Query parameters, e.g. {\"limit\": 50}" }
      },
      required: ["path"]
    }
  },
  {
    name: "theprotocol_adminPromQuery",
    description: "Commander-only: execute PromQL queries against Prometheus. Instant: query='up'. Range: add start, end (ISO8601), step (seconds).",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "PromQL expression" },
        start: { type: "string", description: "ISO8601 start for range query" },
        end: { type: "string", description: "ISO8601 end for range query" },
        step: { type: "string", description: "Step in seconds, default '60'" }
      },
      required: ["query"]
    }
  },
  {
    name: "theprotocol_adminGrafanaQuery",
    description: "Commander-only: query Grafana HTTP API. GET paths: /api/health, /api/admin/stats, /api/search, /api/dashboards/uid/{uid}, /api/annotations, /api/datasources. POST /api/ds/query for raw queries.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string", description: "Grafana API path, e.g. /api/search" },
        method: { type: "string", enum: ["GET", "POST", "DELETE"], description: "HTTP method (default GET)" },
        body: { type: "object", description: "JSON body for POST" },
        params: { type: "object", description: "Query parameters" }
      },
      required: ["path"]
    }
  }
];

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

async function callTool(toolName, args) {
  const token = args.developer_jwt || API_KEY || null;

  const rpcBody = {
    jsonrpc: "2.0",
    id: Date.now(),
    method: "tools/call",
    params: { name: toolName, arguments: args }
  };

  const result = await postJSON(`${API_BASE}/mcp/admin/rpc`, rpcBody, token);

  if (result.error) {
    return { content: [{ type: "text", text: `Error: ${JSON.stringify(result.error)}` }], isError: true };
  }
  if (result.result) {
    return result.result;
  }
  return { content: [{ type: "text", text: JSON.stringify(result) }], isError: false };
}

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
    return;
  }

  if (method === 'ping') {
    send({ jsonrpc: '2.0', id, result: {} });
    return;
  }

  if (method === 'tools/list') {
    send({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
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

  send({
    jsonrpc: '2.0', id,
    error: { code: -32601, message: `Method not found: ${method}` }
  });
}

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

process.on('unhandledRejection', () => {});
process.stderr.write(`[${SERVER_NAME}] MCP admin stdio bridge started → ${API_BASE}/mcp/admin/rpc\n`);
