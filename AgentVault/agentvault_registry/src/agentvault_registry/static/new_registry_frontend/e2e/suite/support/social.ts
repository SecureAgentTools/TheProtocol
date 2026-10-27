/**
 * Helpers for the social and ops lifecycles (§FESUITE 30-39): CI/CD, bundles, notifications, disputes, OurChat.
 * Setup and read-back only; what a lifecycle is about, it drives through the page.
 */
import type { BrowserContext } from '@playwright/test'
import type { Api } from './fixtures'
import type { CreatedAgent, Developer } from './accounts'

/** The developer id behind a token (GET /developers/me), for rows keyed by owner. */
export async function developerId(api: Api, dev: Developer): Promise<string> {
  const r = await api.json('GET', '/api/v1/developers/me', { token: dev.token })
  const id = r.body?.id ?? r.body?.developer_id
  if (r.status !== 200 || id === undefined || id === null) throw new Error(`developers/me answered ${r.status}`)
  return String(id)
}

/**
 * Put an agent's keys in this browser's credential vault the way the console itself keeps them (the plain vault key,
 * the owner stamped as the logged-in developer), so pages that act AS the agent can. The import door itself is proven
 * by the wallet lifecycle (09); here it is setup.
 */
export async function seedVault(context: BrowserContext, agent: CreatedAgent, ownerId: string, name = 'fesuite agent'): Promise<void> {
  const row = {
    did: agent.did, client_id: agent.clientId, client_secret: agent.clientSecret, name,
    owner_developer_id: ownerId, created_at: new Date().toISOString(),
  }
  await context.addInitScript(([key, r]) => {
    try {
      const all = JSON.parse(localStorage.getItem(key) || '{}') || {}
      if (!all[r.did]) { all[r.did] = r; localStorage.setItem(key, JSON.stringify(all)) }
      if (!localStorage.getItem('activeAgentId')) localStorage.setItem('activeAgentId', r.did)
    } catch { /* storage blocked: the page will say it has no agent */ }
  }, ['agentvault_agent_credentials', row] as const)
}

/** A list out of a response that may be the list itself or wrap it under one of a few keys. */
export function listOf(body: any, ...keys: string[]): any[] {
  if (Array.isArray(body)) return body
  for (const k of keys) if (Array.isArray(body?.[k])) return body[k]
  return []
}

/**
 * Wait until the page's running animations and transitions have finished (a dialog that pops in is measured by axe at
 * half opacity otherwise: a contrast failure that comes and goes with the timing). Capped; never throws.
 */
export async function steady(page: import('@playwright/test').Page, capMs = 3000): Promise<void> {
  await page.evaluate(async (cap) => {
    // a Vue transition starts on the NEXT frame: let two frames pass before asking what is running
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))
    const running = (document.getAnimations?.() || []).filter((a) => a.playState === 'running' && a.effect?.getTiming().iterations !== Infinity)
    await Promise.race([Promise.allSettled(running.map((a) => a.finished)), new Promise((r) => setTimeout(r, cap))])
  }, capMs).catch(() => {})
}

/** A read-back GET that survives one dropped keep-alive connection ("socket hang up" while a worker recycles). */
export async function readBack(api: Api, path: string, token: string): Promise<{ status: number; body: any }> {
  try {
    return await api.json('GET', path, { token })
  } catch (e: any) {
    if (!/socket hang up|ECONNRESET|EPIPE/i.test(String(e?.message || e))) throw e
    await new Promise((r) => setTimeout(r, 500))
    return api.json('GET', path, { token })
  }
}
