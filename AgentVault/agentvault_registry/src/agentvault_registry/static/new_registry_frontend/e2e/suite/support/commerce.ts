/**
 * Commerce helpers for the console lifecycle suite (§FESUITE, contracts / Guild / AGORA / Forex). Setup and read-back
 * only: what a lifecycle is ABOUT it drives through the page; what it merely needs (a second party, a bonded provider,
 * keys in the browser) is made here over the API, the way an SDK user would make it.
 */
import type { BrowserContext, Page } from '@playwright/test'
import { expect } from '@playwright/test'
import type { Api } from './fixtures'
import { agentToken, createAgentApi, registerDeveloper, type CreatedAgent, type Developer } from './accounts'
import { pinia } from './ui'

/** The localStorage key the console keeps agent keys under while the vault is plain (services/credentialVault.ts). */
export const VAULT_KEY = 'agentvault_agent_credentials'

export interface Party {
  dev: Developer
  /** The developer id as a string: the owner the console stamps on every key it keeps (agentCredentialsStore). */
  devId: string
  agents: Array<CreatedAgent & { token: string }>
}

export async function developerId(api: Api, dev: Developer): Promise<string> {
  const r = await api.json('GET', '/api/v1/developers/me', { token: dev.token })
  if (r.status !== 200 || r.body?.id == null) throw new Error(`developers/me answered ${r.status}`)
  return String(r.body.id)
}

/**
 * A developer with `n` agents made over the API. The first holds the frame's genesis grant; the rest start empty.
 * Each agent's own token is minted for read-back as that agent.
 */
export async function partyWith(api: Api, kind: string, n = 1): Promise<Party> {
  const dev = await registerDeveloper(api, kind)
  const devId = await developerId(api, dev)
  const agents: Party['agents'] = []
  for (let i = 0; i < n; i++) {
    const a = await createAgentApi(api, dev, `${kind}-${i}`)
    agents.push({ ...a, token: await agentToken(api, a) })
  }
  return { dev, devId, agents }
}

/**
 * The keys of these agents in a browser context, written the way the console writes them after "ADD KEYS" (one row
 * per DID, owned by the developer), and the acting agent chosen. 09-wallet drives the ADD KEYS door itself; here the
 * keys are setup. Existing rows are left alone, so a reload never undoes what the page did.
 */
export async function seedVault(context: BrowserContext, party: Party, active?: string): Promise<void> {
  const rows = party.agents.map((a) => ({ did: a.did, clientId: a.clientId, clientSecret: a.clientSecret }))
  await context.addInitScript(([key, owner, list, act]) => {
    try {
      const cur = JSON.parse(localStorage.getItem(key as string) || '{}') || {}
      for (const r of list as Array<{ did: string; clientId: string; clientSecret: string }>) {
        if (!cur[r.did]) {
          cur[r.did] = { did: r.did, client_id: r.clientId, client_secret: r.clientSecret, owner_developer_id: owner,
            created_at: new Date().toISOString() }
        }
      }
      localStorage.setItem(key as string, JSON.stringify(cur))
      if (act && !localStorage.getItem('activeAgentId')) localStorage.setItem('activeAgentId', act as string)
    } catch { /* storage blocked: the page will say it has no keys */ }
  }, [VAULT_KEY, party.devId, rows, active || party.agents[0]?.did || ''] as const)
}

/** Wait until the console acts as this agent (the auth store restored it and holds its token). */
export async function waitActing(page: Page, did: string, timeout = 45_000): Promise<void> {
  await expect.poll(async () => {
    try {
      return await pinia<string>(page, 'auth', (s) => (s.activeAgent?.did && s.agentToken) ? String(s.activeAgent.did) : '')
    } catch { return '' }
  }, { timeout, message: `the console acts as ${did.slice(-12)}` }).toBe(did)
}

/** The provider gate (§REPBOND): bond `worker` from `funder` (both owned by `dev`), read back as locked. */
export async function bondFrom(api: Api, dev: Developer, worker: string, funder: string): Promise<void> {
  const r = await api.json('POST', `/api/v1/developers/me/agents/${encodeURIComponent(worker)}/reputation-bond`, {
    token: dev.token, body: { funder_did: funder, amount: null },
  })
  if (r.status >= 300) throw new Error(`bond answered ${r.status}: ${JSON.stringify(r.body).slice(0, 200)}`)
  await expect.poll(async () => (await reputation(api, worker))?.bond?.is_bonded === true,
    { timeout: 30_000, message: 'the bond reads as held' }).toBe(true)
}

export async function reputation(api: Api, did: string): Promise<any> {
  const r = await api.json('GET', `/api/v1/agents/${encodeURIComponent(did)}/reputation`)
  return r.status === 200 ? r.body : null
}

/**
 * A DID homed on the peer FRAME itself, for a cross-currency quote. Not a mirror of ours and not an agent of one of the
 * peer's operators: those carry the frame's DID namespace too, and a quote for a leaf operator's agent reads a reserve
 * the operator does not hold (503 until agentvault2-f4's V0528, measured 16:37Z). A card native to the peer carries no
 * federation source at all.
 */
export async function peerNativeDid(peerApi: Api, _issuerHint: string): Promise<string | null> {
  const r = await peerApi.json('GET', '/api/v1/agent-cards/?limit=1000&include_card_data=true')
  const items: any[] = Array.isArray(r.body?.items) ? r.body.items : []
  const hit = items.find((i) => i?.is_active !== false && i?.agent_did
    && !(i?.card_data?.federation_metadata?.source_registry))
  return hit ? String(hit.agent_did) : null
}

/** Round to the listing's tick (prices are decimal strings on the wire). */
export function toTick(price: number, tick: number): string {
  const places = Math.max(0, (String(tick).split('.')[1] || '').replace(/0+$/, '').length)
  return (Math.floor(price / tick) * tick).toFixed(places)
}

/**
 * axe reads colours as they are painted at that instant: a button fading in as it enables (`transition: all 0.15s`
 * from opacity 0.45) reads as a 3:1 contrast failure. Wait for every finite animation to end before a check.
 */
export async function stillFrame(page: Page): Promise<void> {
  await page.waitForFunction(() => document.getAnimations().every((a) => {
    const it = (a.effect as KeyframeEffect | null)?.getTiming().iterations
    return a.playState !== 'running' || it === Infinity
  }), undefined, { timeout: 5_000 }).catch(() => { /* an endless animation is not a reason to skip the check */ })
}
