/**
 * The run's own accounts (§FESUITE): every developer the suite needs, it registers itself under the run's prefix, and
 * every one of them is written to the run's ledger the moment it exists, so the sweep can find it even when the run
 * dies half-way. The suite never borrows a person's account and never shares an account between the browser and its
 * own API calls in a way that logs either out (POST /auth/logout revokes a developer's tokens everywhere).
 *
 * Passwords are generated per account and never printed.
 */
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import type { BrowserContext, Page } from '@playwright/test'
import type { Api } from './fixtures'
import { OUT_DIR, PREFIX, uniqueName } from './env'

export interface Developer {
  name: string
  email: string
  password: string
  token: string
  /** Shown once at registration; kept in memory for the recovery-key lifecycle, never written anywhere. */
  recoveryKeys: string[]
}

export const SESSION_KEY = 'sovereign_auth_token'
const MAIL_DOMAIN = 'throwaway-pl.example.com'

/** At least 12 characters with upper, lower, digit and a special character (the registry's rule). */
export function newPassword(): string {
  const al = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
  const sp = '!@%^&*'
  const b = crypto.randomBytes(24)
  let p = ''
  for (let i = 0; i < 18; i++) p += al[b[i] % al.length]
  return `${p}${sp[b[18] % sp.length]}Q${sp[b[19] % sp.length]}7a`
}

/** The ledger of what this run created: one JSON line per object, read by the sweep. */
export function ledger(kind: string, record: Record<string, unknown>): void {
  fs.mkdirSync(OUT_DIR, { recursive: true })
  const line = JSON.stringify({ at: new Date().toISOString(), kind, ...record }) + '\n'
  // 0600: until the sweep scrubs them, the throwaway accounts' passwords are in this file.
  fs.appendFileSync(path.join(OUT_DIR, 'created.jsonl'), line, { mode: 0o600 })
}

/** After the sweep: the ledger keeps what was created and what became of it, never a password. */
export function scrubLedger(outcomes: Map<string, string>): void {
  const f = path.join(OUT_DIR, 'created.jsonl')
  if (!fs.existsSync(f)) return
  const lines = readLedger().map((r) => {
    const { password: _drop, ...rest } = r
    const key = String(r.email || r.did || r.name || '')
    return JSON.stringify(outcomes.has(key) ? { ...rest, swept: outcomes.get(key) } : rest)
  })
  fs.writeFileSync(f, lines.join('\n') + (lines.length ? '\n' : ''), { mode: 0o600 })
}

export function readLedger(): Array<Record<string, any>> {
  const f = path.join(OUT_DIR, 'created.jsonl')
  if (!fs.existsSync(f)) return []
  return fs.readFileSync(f, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l))
}

/** A fresh developer registered over the API (setup for a lifecycle that is not about registering). */
export async function registerDeveloper(api: Api, kind = 'dev'): Promise<Developer> {
  const name = uniqueName(kind)
  const email = `${name}@${MAIL_DOMAIN}`
  const password = newPassword()
  const r = await api.json('POST', '/api/v1/auth/register', {
    body: { name, email, password, tos_accepted: true, age_confirmed: true },
  })
  if (r.status !== 200 && r.status !== 201) {
    throw new Error(`register answered ${r.status}: ${JSON.stringify(r.body).slice(0, 200)}`)
  }
  // Store the password ON the ledger (the run's private output) so the sweep can request the self-deletion; the
  // ledger stays in the run directory, never in a report.
  ledger('developer', { name, email, password, via: 'api' })
  const token = await api.login(email, password)
  const recoveryKeys: string[] = Array.isArray(r.body?.recovery_keys) ? r.body.recovery_keys : []
  return { name, email, password, token, recoveryKeys }
}

/** A developer session in a context without typing: the console restores a session from this key at boot. */
export async function seedSession(context: BrowserContext, token: string): Promise<void> {
  await context.addInitScript(([key, t]) => {
    try { if (!sessionStorage.getItem(key)) sessionStorage.setItem(key, t) } catch { /* the page will ask for a login */ }
  }, [SESSION_KEY, token] as const)
}

/**
 * The legal re-consent modal covers every control for an account registered over the API (it accepted no document
 * through the page). A person meets it once and picks "later"; so does the suite, and it says so.
 */
export async function passReconsent(page: Page): Promise<boolean> {
  const later = page.locator('[data-testid="legal-reconsent-later"]')
  if ((await later.count()) && (await later.first().isVisible().catch(() => false))) {
    await later.first().click()
    await later.first().waitFor({ state: 'hidden' })
    return true
  }
  return false
}

/** The run's prefix check: the sweep deletes only what carries it. */
export function isOurs(nameOrEmail: string): boolean {
  return nameOrEmail.toLowerCase().startsWith(PREFIX)
}

export interface CreatedAgent { did: string; clientId: string; clientSecret: string }

/**
 * An agent made over the API (setup for a lifecycle that is not about creating one): the bootstrap token, then
 * create_agent with the agent's own card, whose endpoint is under .invalid (never dialled). V0650 (e): a bare
 * agent_host on a special-use name is refused (400), because no card could ever be read there; an agent that serves
 * nothing sends its card itself, in the stub's own shape. The secret stays in memory; the ledger keeps the DID.
 */
export async function createAgentApi(api: Api, dev: Developer, hint = 'fesuite'): Promise<CreatedAgent> {
  const bt = await api.json('POST', '/api/v1/onboard/bootstrap/request-token', { token: dev.token, body: { agent_type_hint: hint } })
  const bootstrap = bt.body?.bootstrap_token
  if (bt.status !== 200 || !bootstrap) throw new Error(`bootstrap token answered ${bt.status}`)
  const slug = `${PREFIX}-${crypto.randomBytes(3).toString('hex')}`
  const host = `https://${slug}.invalid`
  const card = {
    protocolVersion: '1.0', agentVersion: '1.0.0', humanReadableId: slug, name: slug,
    description: `A ${hint} agent the console suite made; it serves nothing.`,
    url: host, preferredTransport: 'JSONRPC',
    supportedInterfaces: [{ url: host, protocolBinding: 'JSONRPC', protocolVersion: '1.0' }],
    securitySchemes: { agent_jwt: { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' } },
    security: [{ agent_jwt: [] }],
    provider: { name: PREFIX }, capabilities: { streaming: false },
  }
  const r = await api.json('POST', '/api/v1/onboard/create_agent', {
    headers: { 'Bootstrap-Token': bootstrap },
    body: { agent_did_method: 'theprotocol', agent_card: card },
  })
  if (!r.body?.agent_did || !r.body?.client_secret) throw new Error(`create_agent answered ${r.status}`)
  ledger('agent', { did: r.body.agent_did, owner: dev.email, via: 'api' })
  return { did: r.body.agent_did, clientId: r.body.client_id, clientSecret: r.body.client_secret }
}

/** Make an owned agent the one the console acts as at its next load (the auth store restores activeAgentId). */
export async function seedActiveAgent(context: BrowserContext, did: string): Promise<void> {
  await context.addInitScript((d) => {
    try { if (!localStorage.getItem('activeAgentId')) localStorage.setItem('activeAgentId', d) } catch { /* storage blocked */ }
  }, did)
}

/** An agent's own token (the OAuth2 password form: client_id + client_secret), for read-back as that agent. */
export async function agentToken(api: Api, agent: CreatedAgent): Promise<string> {
  const r = await api.json('POST', '/api/v1/auth/agent/token', { form: { username: agent.clientId, password: agent.clientSecret } })
  const t = r.body?.access_token
  if (r.status !== 200 || !t) throw new Error(`agent token answered ${r.status}`)
  return t
}

/** An agent's liquid balance as its TEG reports it (balances may arrive in scientific notation: "1E+3"). */
export async function agentBalance(api: Api, token: string): Promise<number> {
  const r = await api.json('GET', '/api/v1/teg/balance', { token })
  if (r.status !== 200) throw new Error(`balance answered ${r.status}`)
  const b = r.body || {}
  const v = b.balance ?? b.liquid_balance ?? b.available_balance ?? b.available
  const n = Number(v)
  if (!Number.isFinite(n)) throw new Error('the balance read carried no number')
  return n
}

/** Where the console keeps the keys of agents it can act as (services/credentialVault.ts PLAIN_KEY). */
export const VAULT_KEY = 'agentvault_agent_credentials'

/**
 * Put agents' keys where the console keeps them, owned by the developer, exactly as entering them on My Agents leaves
 * them (09-wallet drives that door itself; a lifecycle about something else starts from its result). Seeds once: a
 * later write by the page is never overwritten.
 */
export async function seedVault(context: BrowserContext, api: Api, dev: Developer, agents: CreatedAgent[]): Promise<void> {
  const me = await api.json('GET', '/api/v1/developers/me', { token: dev.token })
  if (me.status !== 200 || me.body?.id === undefined) throw new Error(`developers/me answered ${me.status}`)
  const owner = String(me.body.id)
  const rows: Record<string, unknown> = {}
  for (const a of agents) {
    rows[a.did] = { did: a.did, client_id: a.clientId, client_secret: a.clientSecret, owner_developer_id: owner, created_at: new Date().toISOString() }
  }
  await context.addInitScript(([k, v]) => {
    try { if (!localStorage.getItem(k)) localStorage.setItem(k, v) } catch { /* storage blocked */ }
  }, [VAULT_KEY, JSON.stringify(rows)] as const)
}
