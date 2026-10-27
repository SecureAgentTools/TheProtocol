/**
 * Setup and read-back for the hygiene and breadth lifecycles (§FESUITE, lifecycles 40-49): objects a developer owns,
 * made over the API (as an SDK or the MCP tester would), and the counts and lists the read-backs compare against.
 * What a lifecycle drives, it drives through the page; these only arrange the world and read it back.
 */
import crypto from 'node:crypto'
import { expect, type Page, type Request } from '@playwright/test'
import type { Api } from './fixtures'
import type { Developer } from './accounts'
import { ledger } from './accounts'
import { PREFIX, uniqueName } from './env'

export interface Owned {
  orgId: string
  orgName: string
  hookId: string
  hookUrl: string
  ticketId: string
  ticketSubject: string
  keyId: string
  keyName: string
}

/**
 * A read-back GET, once more if the socket was closed under it. The registry closes idle keep-alive sockets after a few
 * seconds and Node can reuse one in the instant it closes ("socket hang up", measured twice on 2026-10-01 between a
 * UI step and its read-back); a GET is safe to repeat, a write never is.
 */
async function get(api: Api, path: string, token: string): Promise<{ status: number; body: any }> {
  try {
    return await api.json('GET', path, { token })
  } catch (e: any) {
    if (!/socket hang up|ECONNRESET/i.test(String(e?.message || e))) throw e
    return api.json('GET', path, { token })
  }
}

const asList = (b: any, ...keys: string[]): any[] => {
  if (Array.isArray(b)) return b
  for (const k of keys) if (Array.isArray(b?.[k])) return b[k]
  return []
}

export async function listOrgs(api: Api, dev: Developer): Promise<any[]> {
  return asList((await get(api, '/api/v1/organizations', dev.token)).body, 'organizations', 'items')
}
export async function listHooks(api: Api, dev: Developer): Promise<any[]> {
  return asList((await get(api, '/api/v1/webhooks', dev.token)).body, 'webhooks', 'items')
}
export async function listTickets(api: Api, dev: Developer, limit = 200, offset = 0): Promise<any[]> {
  const r = await get(api, `/api/v1/support/tickets?limit=${limit}&offset=${offset}`, dev.token)
  return asList(r.body, 'tickets', 'items')
}
export async function listKeys(api: Api, dev: Developer): Promise<any[]> {
  return asList((await get(api, '/api/v1/auth/api-keys', dev.token)).body, 'api_keys', 'keys', 'items')
}
export async function listAgents(api: Api, dev: Developer): Promise<any[]> {
  return asList((await get(api, '/api/v1/developers/me/agents', dev.token)).body, 'agents', 'items')
}

/** A webhook address that never resolves (RFC 2606 .test): nothing is ever delivered anywhere. */
export function deadHookUrl(): string {
  return `https://${PREFIX}-${crypto.randomBytes(3).toString('hex')}.example.test/hook`
}

/** One of everything a developer owns (organization, webhook, ticket, API key), made over the API and read back. */
export async function makeOwned(api: Api, dev: Developer): Promise<Owned> {
  const orgName = uniqueName('org')
  const o = await api.json('POST', '/api/v1/organizations', { token: dev.token, body: { name: orgName, description: 'owner-scoping fixture' } })
  if (o.status >= 300 || !o.body?.id) throw new Error(`organization create answered ${o.status}`)
  ledger('organization', { id: o.body.id, name: orgName, owner: dev.email })

  const hookUrl = deadHookUrl()
  const ev = await api.json('GET', '/api/v1/webhooks/events/supported', { token: dev.token })
  const events: string[] = asList(ev.body, 'events', 'supported_events').map((e: any) => (typeof e === 'string' ? e : e.event || e.name)).filter(Boolean)
  const h = await api.json('POST', '/api/v1/webhooks', { token: dev.token, body: { url: hookUrl, events: events.slice(0, 1) } })
  if (h.status >= 300 || !h.body?.id) throw new Error(`webhook create answered ${h.status}`)

  const ticketSubject = uniqueName('ticket')
  const t = await api.json('POST', '/api/v1/support/tickets', { token: dev.token, body: { subject: ticketSubject, message: 'owner-scoping fixture' } })
  if (t.status >= 300 || !t.body?.id) throw new Error(`ticket create answered ${t.status}`)

  const keyName = uniqueName('key')
  const k = await api.json('POST', '/api/v1/auth/api-keys', { token: dev.token, body: { key_name: keyName } })
  const keyId = String(k.body?.api_key_info?.id ?? k.body?.id ?? '')
  if (k.status >= 300 || !keyId) throw new Error(`api key create answered ${k.status}`)

  return { orgId: String(o.body.id), orgName, hookId: String(h.body.id), hookUrl, ticketId: String(t.body.id), ticketSubject, keyId, keyName }
}

/** What a developer's objects look like now, for an unchanged-after check (names, flags and counts, never secrets). */
export async function snapshot(api: Api, dev: Developer): Promise<string> {
  const [orgs, hooks, tickets, keys, agents] = await Promise.all([
    listOrgs(api, dev), listHooks(api, dev), listTickets(api, dev), listKeys(api, dev), listAgents(api, dev),
  ])
  const pick = (xs: any[], f: (x: any) => unknown) => JSON.stringify(xs.map(f).sort((a, b) => String(a).localeCompare(String(b))))
  return [
    pick(orgs, (x) => `${x.id}|${x.name}|${x.description ?? ''}|${x.member_count ?? ''}`),
    pick(hooks, (x) => `${x.id}|${x.url}|${x.is_active}|${(x.events || []).join(',')}`),
    pick(tickets, (x) => `${x.id}|${x.subject}|${x.status}|${x.message_count ?? (x.messages || []).length ?? ''}`),
    pick(keys, (x) => `${x.id}|${x.description ?? x.key_name ?? ''}|${x.is_active ?? ''}`),
    pick(agents, (x) => `${x.did}|${x.status ?? ''}|${x.is_active ?? ''}`),
  ].join('\n')
}

/**
 * Every request the page sends whose method and path (and, when given, body) match, for "nothing left the page" and
 * "one press, one call". The body is matched, never recorded.
 */
export function watchRequests(page: Page, method: string, path: RegExp, body?: RegExp): { list: string[]; stop: () => void } {
  const list: string[] = []
  const on = (r: Request) => {
    if (r.method() !== method) return
    try {
      if (!path.test(new URL(r.url()).pathname)) return
      if (body && !body.test(r.postData() || '')) return
      list.push(r.url())
    } catch { /* not a URL */ }
  }
  page.on('request', on)
  return { list, stop: () => page.off('request', on) }
}

/** The visible text of the page's main area, whitespace folded (for "does the page say so" and "is it blank"). */
export async function mainText(page: Page): Promise<string> {
  // the layout's own region first (views nest <main> elements of their own inside it)
  const main = page.locator('#main-content, main, [role="main"]').first()
  const text = (await main.count()) ? await main.innerText() : await page.locator('body').innerText()
  return text.replace(/\s+/g, ' ').trim()
}

/** A string of n characters that carries the run's prefix (so a stray object is still swept by name). */
export function longText(n: number): string {
  const head = `${PREFIX}-long-`
  return (head + 'x'.repeat(Math.max(0, n))).slice(0, n)
}

/** The page refuses before asking: the control is disabled, or pressing it leaves no request and shows a reason. */
export async function expectDisabled(control: ReturnType<Page['locator']>, why: string): Promise<void> {
  await expect(control, why).toBeDisabled()
}

/**
 * Is the control the thing a finger lands on at its centre? A control can render perfectly and be impossible to press
 * when something paints over it (CLAUDE.md: "ask elementFromPoint, not your eyes").
 */
export async function reachable(page: Page, control: ReturnType<Page['locator']>): Promise<boolean> {
  const handle = await control.first().elementHandle()
  if (!handle) return false
  return page.evaluate((el) => {
    const r = (el as Element).getBoundingClientRect()
    if (r.width <= 0 || r.height <= 0) return false
    const x = r.left + r.width / 2
    const y = r.top + r.height / 2
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) return false
    const hit = document.elementFromPoint(x, y)
    return !!hit && (hit === el || (el as Element).contains(hit))
  }, handle)
}
