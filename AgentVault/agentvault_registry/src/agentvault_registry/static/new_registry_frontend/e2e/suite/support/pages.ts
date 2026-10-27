/**
 * Every page of the console, as its own router knows them (§FESUITE): the sweep asks the running app for its routes
 * instead of keeping a list, so a page added tomorrow is swept tomorrow, and a page renamed is never "missing".
 */
import fs from 'node:fs'
import path from 'node:path'
import type { Page } from '@playwright/test'
import { pinia } from './ui'

export interface RouteInfo {
  path: string
  name: string
  meta: Record<string, unknown>
  redirect: boolean
}

/**
 * Pages the suite does not open in a headless browser, each with its reason: WebGL views fall back to software
 * rendering there and can hang the browser (CLAUDE.md PART 1, "THE LANDING PAGE IS ON THE DO NOT PLAYWRIGHT LIST").
 */
export const NOT_DRIVEN: Record<string, string> = {
  '/': 'the landing page embeds the Cesium globe (WebGL)',
  '/agentworld': 'Cesium (WebGL)',
  '/galactic-map': 'three.js (WebGL)',
  '/discovery': 'three.js GalacticMap (WebGL)',
  '/universe': 'three.js (WebGL)',
  '/galactic-command': 'GalacticMap plus a Cesium cockpit (WebGL)',
  '/bridge': 'BridgeStage mounts GalacticMap (WebGL)',
  '/ironhand/theatre': 'an embedded GalacticMap (WebGL)',
}

/**
 * Refusals a page earns honestly, each with its reason: the API answers "not here" with a 404 by design, and the page
 * reads that as "nothing to show". Anything not listed is a finding. The list is short on purpose.
 */
export const EXPECTED_REFUSALS: Array<{ route: RegExp; call: RegExp; status: number; reason: string }> = [
  { route: /^\/agora$/, call: /GET \/api\/v1\/exchange\/solvency-card$/, status: 404,
    reason: 'the venue serves no solvency card here (EXCHANGE_SOLVENCY_CARD_ENABLED off); the desk reads 404 as "no card"' },
  { route: /^\/(showcase|protocol-theatre)$/, call: /GET \/api\/v1\/agents\/by-did\//, status: 404,
    reason: 'the theatre asks for its two Frame A agents and says "not on this frame" when the frame answers 404' },
  { route: /^\/community$/, call: /GET \/api\/v1\/agents\/by-did\//, status: 404,
    reason: 'the community page asks for the network\'s sovereign agents (Frame A\'s) and shows only those this frame answers for; a 404 is "not hosted here"' },
  { route: /^\/admin\/mail-fleet$/, call: /GET \/api\/v1\/admin\/mail\/(fleet|sender)$/, status: 404,
    reason: 'the mail console exists only on a registry that holds mail credentials (admin_mail_fleet.py answers 404 elsewhere, by design); the page says this registry does not manage mail' },
  { route: /^\/operator-portal$/, call: /GET \/api\/v1\/operators\/me\/lifecycle$/, status: 404,
    reason: 'the rail answers "you are not an operator" with 404 by design (operator_lifecycle.py); the portal shows the apply path' },
]

/** The router's own list, read from the page (any route the app can show, without parameters). */
export async function appRoutes(page: Page): Promise<RouteInfo[]> {
  const raw = await page.evaluate(() => {
    const app = (document.querySelector('#app') as any)?.__vue_app__
    const router = app?.config?.globalProperties?.$router
    if (!router) return null
    return router.getRoutes().map((r: any) => ({
      path: r.path as string,
      name: String(r.name ?? ''),
      meta: JSON.parse(JSON.stringify(r.meta ?? {})),
      redirect: !!r.redirect,
    }))
  })
  if (!raw) throw new Error('the console exposes no router')
  return (raw as RouteInfo[])
    .filter((r) => !r.redirect && !r.path.includes(':') && r.path !== '/:pathMatch(.*)*')
    .sort((a, b) => a.path.localeCompare(b.path))
}

/** The route the router resolved for the current URL (the engine's answer, not the URL's). */
export async function resolvedRoute(page: Page): Promise<{ name: string; path: string }> {
  return page.evaluate(() => {
    const router = (document.querySelector('#app') as any)?.__vue_app__?.config?.globalProperties?.$router
    const r = router?.currentRoute?.value
    return { name: String(r?.name ?? ''), path: String(r?.path ?? '') }
  })
}

let namespaces: string[] | null = null
/** The locale bundle's top-level namespaces: a visible text that IS "<namespace>.<key>" is a raw key. */
export function i18nNamespaces(): string[] {
  if (namespaces) return namespaces
  // The suite runs from the frontend's root (its config lives there), so the bundle is at a fixed place under it.
  const file = path.resolve(process.cwd(), 'src/i18n/locales/en.json')
  namespaces = Object.keys(JSON.parse(fs.readFileSync(file, 'utf8')))
  return namespaces
}

/** Visible text nodes that are raw translation keys (the whole node is ns.key[.key...] for a real namespace). */
export async function rawKeys(page: Page): Promise<string[]> {
  const ns = i18nNamespaces()
  return page.evaluate((nsList) => {
    const set = new Set(nsList)
    const out = new Set<string>()
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const t = (n.textContent || '').trim()
      // An i18n key is camelCase segments; a snake_case dotted word (an audit action like chatdesk.review_read) is data.
      if (!/^[a-z][a-zA-Z0-9]*(\.[A-Za-z][A-Za-z0-9]*)+$/.test(t)) continue
      if (!set.has(t.split('.')[0])) continue
      const el = n.parentElement
      if (!el) continue
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      out.add(t)
    }
    for (const el of Array.from(document.querySelectorAll('[placeholder],[aria-label],[title]'))) {
      for (const attr of ['placeholder', 'aria-label', 'title']) {
        const v = (el.getAttribute(attr) || '').trim()
        if (/^[a-z][a-zA-Z0-9]*(\.[A-Za-z][A-Za-z0-9]*)+$/.test(v) && set.has(v.split('.')[0])) out.add(`${attr}=${v}`)
      }
    }
    return Array.from(out).slice(0, 20)
  }, ns)
}

/** How far the page scrolls sideways, in CSS pixels (0 = it fits). */
export async function sideScroll(page: Page): Promise<number> {
  return page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth))
}

/** Whether the console holds an agent to act as (the requiresAgent guard's own question). */
export async function actingAgent(page: Page): Promise<string> {
  return pinia<string>(page, 'auth', (store) => String(store.activeAgent?.did || ''))
}
