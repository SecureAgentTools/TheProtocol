/**
 * QUICK ONBOARDING (2026-10-09, his words: "a new view where you can issue simple agent identity. by giving the agent a
 * name. get standard valid agent card ... it should list your existing agents and allow to initiate password reset from
 * there. with their balances (hidden but unhideable)"). The view is views/QuickOnboarding.vue; this module is its
 * decisions, kept pure so each one is tested on its own:
 *
 *   - which rows of GET /developers/me/agents are the person's agents (a deleted agent is status "revoked" and still
 *     listed: the rail has no status filter)
 *   - what one entry of the balances batch says (every failure is balance "0" WITH an error: unread, never 0)
 *   - what the registry's initial_funding_status says about the starting balance (and what it does not promise)
 *   - what a refused issue or a refused reset means, in words the person can act on (the step-up answer among them)
 *   - whether the card validator's answer is a positive one (a skipped validation is not)
 */
import { parseStepUp, type StepUpChallenge } from '@/services/membership/membership'
import { toNum } from '@/services/cockpit/num'

// ── the agents list ─────────────────────────────────────────────────────────────────────────────────────────────────

/** GET /developers/me/agents?limit=AGENTS_LIMIT (newest first). A full page means there may be more: say so. */
export const AGENTS_LIMIT = 100
/** POST /developers/me/agents/balances takes at most 50 DIDs (routers/developers.py). */
export const BALANCE_CHUNK = 50

export interface AgentRow {
  did: string
  client_id?: string | null
  status?: string | null
  name?: string | null
  description?: string | null
  created_at?: string | null
  card_data?: Record<string, unknown> | null
  [k: string]: unknown
}

/** A status that means the agent is gone: the owner deleted it (revoked) or an older row says deleted. */
export function isGone(status: unknown): boolean {
  const s = String(status ?? '').toLowerCase()
  return s === 'revoked' || s === 'deleted'
}

/** The person's agents as the page lists them: every row with a DID that is not gone, in the server's order. */
export function visibleAgents(rows: unknown): AgentRow[] {
  if (!Array.isArray(rows)) return []
  return rows.filter((r): r is AgentRow => !!r && typeof r === 'object' && typeof (r as AgentRow).did === 'string'
    && !!(r as AgentRow).did && !isGone((r as AgentRow).status))
}

/** A suspended agent cannot have its credentials reset (the registry answers 400); the page says why instead. */
export function isSuspended(status: unknown): boolean {
  return String(status ?? '').toLowerCase() === 'suspended'
}

/** The answer was a full page: there may be older agents the page does not show (search reaches all of them). */
export function isSlice(rawCount: number, limit = AGENTS_LIMIT): boolean {
  return rawCount >= limit
}

/** The first identity is the wallet agent (§WALLETAGENT) only when the person's agents were READ and none is live. A
 *  failed read is not "no agents", a search answer says nothing about the whole account, and neither does a full page:
 *  the newest AGENTS_LIMIT rows can all be deleted agents while older live ones lie beyond it (the rail has no status
 *  filter). `rawCount` is the number of rows the registry answered, deleted ones included. */
export function firstIsWallet(read: { ok: boolean; searched: boolean; rows: unknown; rawCount?: number }): boolean {
  const raw = typeof read.rawCount === 'number' ? read.rawCount : (Array.isArray(read.rows) ? read.rows.length : 0)
  return read.ok && !read.searched && !isSlice(raw) && visibleAgents(read.rows).length === 0
}

/**
 * A DID kept readable in a row: the method, then the head and the tail of its last segment (the UUID), which is what
 * tells two agents apart. A namespaced DID (did:theprotocol:<issuer>:<uuid>, DID_ISSUER_NAMESPACE) says the issuer was
 * left out with "…:". The full DID is one copy (or a title) away.
 */
export function shortDid(did: string, head = 8, tail = 6): string {
  if (!did) return ''
  if (did.length <= 40) return did   // a legacy 36-character DID is short already
  const parts = did.split(':')
  if (parts.length < 3) return `${did.slice(0, 20)}…${did.slice(-tail)}`
  const method = parts.slice(0, 2).join(':')
  const last = parts[parts.length - 1]
  const issuer = parts.length > 3 ? '…:' : ''
  const id = last.length > head + tail + 1 ? `${last.slice(0, head)}…${last.slice(-tail)}` : last
  return `${method}:${issuer}${id}`
}

// ── balances ────────────────────────────────────────────────────────────────────────────────────────────────────────

/**
 * Why a balance is unread, as a code the page puts into words (in the person's language):
 *   - error:     the registry answered this agent with an error (`detail` is its own sentence)
 *   - no_entry:  the answer carried nothing for this agent
 *   - no_number: the entry carried no number
 *   - refused:   the whole request was refused (`detail` is the HTTP status)
 *   - no_answer: the whole request got no answer
 */
export type UnreadWhy = 'error' | 'no_entry' | 'no_number' | 'refused' | 'no_answer'

export type BalanceView =
  | { state: 'ok'; amount: string; currency: string }
  | { state: 'unread'; why: UnreadWhy; detail: string; currency: string }

/**
 * One entry of POST /developers/me/agents/balances. The rail answers EVERY failure (not owned, suspended or revoked, a
 * TEG refusal, a timeout) as balance "0" WITH an `error`, so the error is read first and such an entry is unread,
 * never 0. A missing entry, or a balance that is not a number, is unread too.
 */
export function classifyBalance(entry: unknown, fallbackCurrency = ''): BalanceView {
  const e = (entry && typeof entry === 'object' ? entry : null) as Record<string, unknown> | null
  const currency = (e && typeof e.currency === 'string' && e.currency.trim()) || fallbackCurrency || ''
  if (!e) return { state: 'unread', why: 'no_entry', detail: '', currency }
  if (e.error !== undefined && e.error !== null && e.error !== false && String(e.error).trim() !== '') {
    return { state: 'unread', why: 'error', detail: String(e.error).trim(), currency }
  }
  const n = toNum(e.balance)
  if (n === null) return { state: 'unread', why: 'no_number', detail: '', currency }
  return { state: 'ok', amount: String(e.balance), currency }
}

/** Split a list into chunks of at most `size` (the balances batch takes 50). */
export function chunks<T>(items: readonly T[], size = BALANCE_CHUNK): T[][] {
  const n = Math.max(1, Math.floor(size))
  const out: T[][] = []
  for (let i = 0; i < items.length; i += n) out.push(items.slice(i, i + n))
  return out
}

// ── the starting balance ────────────────────────────────────────────────────────────────────────────────────────────

export type FundingKind = 'credited' | 'partial' | 'deferred' | 'failed' | null

/**
 * routers/onboarding.py's initial_funding_status, as a fact about the new identity's starting balance. Nothing in the
 * registry runs a starting balance again later (mint_genesis_grant has one caller, create_agent), so no outcome is
 * "pending" and the page promises nothing:
 *   - completed: credited
 *   - partial:   part of it was paid and the rest never will be (the funding chain ran dry, onboarding.py:422-428)
 *   - deferred:  none was paid, because the treasury is below its floor (onboarding.py:389)
 *   - failed, error: none was paid
 *   - not_first_agent, not_eligible (and anything unknown): no starting balance was due, so nothing to say
 */
export function fundingKind(status: unknown): FundingKind {
  const s = String(status ?? '').toLowerCase()
  if (s === 'completed') return 'credited'
  if (s === 'partial') return 'partial'
  if (s === 'deferred') return 'deferred'
  if (s === 'failed' || s === 'error') return 'failed'
  return null
}

// ── refusals ────────────────────────────────────────────────────────────────────────────────────────────────────────

function statusOf(err: unknown): number | undefined {
  const e = err as { response?: { status?: number } } | null
  const s = e?.response?.status
  return typeof s === 'number' ? s : undefined
}

function bodyOf(err: unknown): unknown {
  return (err as { response?: { data?: unknown } } | null)?.response?.data
}

/** The registry's own sentence for a refusal (RFC 7807 or the legacy `detail`), or '' when it sent none. */
export function serverMessage(err: unknown): string {
  const raw = bodyOf(err)
  const pick = (v: unknown): string => {
    if (typeof v === 'string') return v.trim()
    if (Array.isArray(v)) return v.map((x) => (x && typeof x === 'object' ? String((x as any).msg ?? '') : String(x))).filter(Boolean).join('; ')
    if (v && typeof v === 'object') return String((v as any).message ?? (v as any).detail ?? '').trim()
    return ''
  }
  if (raw && typeof raw === 'object') {
    const d = raw as Record<string, any>
    return pick(d.detail) || pick(d.error?.detail) || pick(d.message) || pick(d.title) || ''
  }
  // a plain-text answer is a sentence; an HTML page (a proxy's error page) is not one
  return typeof raw === 'string' && raw.length < 300 && !/^\s*</.test(raw) ? raw.trim() : ''
}

export type IssueRefusal =
  | { kind: 'unverified' }
  | { kind: 'rate_limited' }
  | { kind: 'other'; message: string }

/** A refused issue: the unverified developer's 403 (its sentence), the rate limit, or the registry's own words. */
export function issueRefusal(err: unknown): IssueRefusal {
  const status = statusOf(err)
  const msg = serverMessage(err)
  if (status === 403 && /verified developers/i.test(msg)) return { kind: 'unverified' }
  if (status === 429) return { kind: 'rate_limited' }
  return { kind: 'other', message: msg }
}

export type ResetRefusal =
  | { kind: 'step_up'; challenge: StepUpChallenge; reason: string }
  | { kind: 'wrong_password' }
  | { kind: 'not_owner' }
  | { kind: 'not_found' }
  | { kind: 'inactive'; message: string }
  | { kind: 'rate_limited' }
  | { kind: 'session' }
  | { kind: 'other'; message: string }

/**
 * A refused reset (POST /onboard/agents/{did}/reset-credentials). The step-up answer is HTTP 401 with a JSON body
 * {error:'step_up_required', step_up:{challenge_id, ...}} (a developer with a second factor); any other 401 is the
 * session. A 403 is the password, unless the registry says the agent is not yours. A 400 is a suspended or revoked
 * agent; a 429 the registry's limit of 3 resets an hour.
 */
export function resetRefusal(err: unknown): ResetRefusal {
  const status = statusOf(err)
  const msg = serverMessage(err)
  if (status === 401) {
    const ch = parseStepUp(bodyOf(err))
    if (ch) return { kind: 'step_up', challenge: ch, reason: ch.reason }
    return { kind: 'session' }
  }
  if (status === 403) return /do not own/i.test(msg) ? { kind: 'not_owner' } : { kind: 'wrong_password' }
  if (status === 404) return { kind: 'not_found' }
  if (status === 400) return { kind: 'inactive', message: msg }
  if (status === 429) return { kind: 'rate_limited' }
  return { kind: 'other', message: msg }
}

/** A step-up answer that came back after a proof was sent: the code or the approval was not accepted. */
export function proofWasRefused(reason: string): boolean {
  return !!reason && !/^second factor required$/i.test(reason.trim())
}

// ── the card ────────────────────────────────────────────────────────────────────────────────────────────────────────

/** POST /utils/validate-card's answer is positive only when it says valid AND it checked: a registry without the core
 *  library answers is_valid true with "Validation skipped", which is no check at all. */
export function validationPassed(answer: unknown): boolean {
  const a = (answer && typeof answer === 'object' ? answer : null) as Record<string, unknown> | null
  if (!a || a.is_valid !== true) return false
  const detail = typeof a.detail === 'string' ? a.detail : ''
  return !/skipped/i.test(detail)
}

/** The file name a downloaded card gets: the slug, never the DID (colons do not travel in file names). */
export function cardFileName(slug: string): string {
  const s = (slug || 'agent').replace(/[^a-z0-9-]+/gi, '-').replace(/^-+|-+$/g, '') || 'agent'
  return `${s}.agent-card.json`
}

/**
 * The "use it" snippet: exchange the pair for a sign-in at the registry's agent sign-in route. It never holds the
 * secret: the first line asks for it without showing it (so it stays out of the shell's history too), and curl reads it
 * from $CLIENT_SECRET, so a copied snippet or a screenshot of it carries no credential.
 */
export function useItSnippet(signInUrl: string, clientId: string): string {
  return [
    'read -rs CLIENT_SECRET   # paste the client secret; it is not shown',
    `curl -s -X POST "${signInUrl}" \\`,
    `  -d "username=${clientId}" \\`,
    `  -d "password=$CLIENT_SECRET"`,
  ].join('\n')
}
