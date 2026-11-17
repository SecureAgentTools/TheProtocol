/**
 * V0667 the public pages readable without JavaScript (order gwo_a9f121caa4138ec9b369814c; his approval, room seq 5381). A reader that runs
 * no JavaScript (a search engine, an AI reader) got 59 characters from theprotocol.cloud: every /#/ route was invisible to it.
 *
 * The page table (staticPages/pages.ts) decides, for EVERY route a signed-out visitor reaches, whether it becomes a static page and at which
 * plain path, or why not. The census is read from the app's own router, never from a hand-kept list, so a new public route that nobody
 * decided about turns this red (a ratchet: a gate with a hand-kept scope passes loudest about the routes it cannot see).
 *   - every public route is either a page or skipped with a reason; nothing is both; nothing decided is not a route
 *   - the plain paths are '/<route>/', one each, and none falls on a path the apex already serves otherwise
 *   - each page names its live counterpart in the app (/#/<route>) and two phrases its source renders, for the render test
 */
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/composables/useFrameManifest', () => ({ whenFrameManifest: async () => null, currentFrameManifest: () => null }))

import router from '@/router'
import { APEX, PAGES, RESERVED, SKIPPED, liveLink, plainPath } from './pages'

function publicRoutes(): string[] {
  const out: string[] = []
  for (const r of router.getRoutes()) {
    if (!r.path || r.path.includes('*') || r.redirect) continue
    const sample = r.path.replace(/:([A-Za-z]+)(\([^)]*\))?\??/g, (_m, n) => `__${n}__`)
    if (!router.resolve(sample).matched.some((m) => m.meta && (m.meta as any).requiresAuth)) out.push(r.path)
  }
  return [...new Set(out)].sort()
}

describe('the page table', () => {
  it('decides about every public route of the app: a page or a reason, never both, and nothing that is not a route', () => {
    const pub = publicRoutes()
    const asPage = new Set(PAGES.map((p) => p.route))
    const undecided = pub.filter((r) => !asPage.has(r) && !(r in SKIPPED))
    expect(undecided, 'public routes nobody decided about').toEqual([])
    expect([...asPage].filter((r) => r in SKIPPED), 'both a page and skipped').toEqual([])
    expect([...asPage, ...Object.keys(SKIPPED)].filter((r) => !pub.includes(r)), 'decided but not a public route').toEqual([])
    for (const [r, why] of Object.entries(SKIPPED)) expect(why.length, `${r}: the reason is a sentence`).toBeGreaterThan(20)
  })

  it('the plain paths are one per page, under the route, and never on a path the apex serves otherwise', () => {
    expect(plainPath('/compliance')).toBe('/compliance/')
    expect(plainPath('/legal/:page', { page: 'terms' })).toBe('/legal/terms/')
    expect(plainPath('/')).toBe('/')
    const paths = PAGES.flatMap((p) => p.paths)
    expect(new Set(paths).size).toBe(paths.length)
    for (const p of paths) {
      expect(p, p).toMatch(/^\/([a-z0-9-]+\/)*$/)
      for (const r of RESERVED) expect(p === r || (r.endsWith('/') && p.startsWith(r)), `${p} falls on ${r}`).toBe(false)
    }
  })

  it('each page names its live counterpart and two phrases its source renders', () => {
    expect(liveLink('/compliance')).toBe(`${APEX}/#/compliance`)
    expect(liveLink('/legal/:page', { page: 'terms' })).toBe(`${APEX}/#/legal/terms`)
    for (const p of PAGES) {
      expect(p.instances.length, p.route).toBeGreaterThan(0)
      for (const inst of p.instances) {
        expect(inst.phrases.length, `${p.route} ${JSON.stringify(inst.params)}`).toBe(2)
        expect(inst.minText, p.route).toBeGreaterThanOrEqual(100)          // a summary page (Explore) is short; an empty shell is not
      }
    }
  })

  it('the landing page is the app\'s own index at /, and the order\'s pages are all there', () => {
    const routes = new Set(PAGES.map((p) => p.route))
    for (const r of ['/', '/migrate', '/explore', '/compliance', '/code-changes', '/legal/:page']) expect(routes.has(r), r).toBe(true)
    expect(PAGES.find((p) => p.route === '/')!.paths).toEqual(['/'])
  })
})
