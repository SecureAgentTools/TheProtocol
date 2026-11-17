/**
 * V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the nav table, read against the real router.
 *  - every entry opens a route that exists;
 *  - ONE RULE: no entry keeps an admin flag of its own (the sidebar reads the route's requiresRole / requiresAdminFlag,
 *    as the guard does); only a tab inside a member page names a flag, and its route is not admin-gated itself;
 *  - every administration entry is admin-gated by that rule, so a member never sees one;
 *  - the pages a visitor may open are exactly the ones the routes call public;
 *  - the default pins (Mission Control, OurChat, Pocket mode) and the Bridge stay reachable from a group when unpinned;
 *  - every label resolves in en.json with its English, every icon is in the local icon map.
 * Red on f569f6a6e: the table lives inside DashboardSidebar.vue (services/nav/navTable does not exist).
 */
import { describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: false }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({}) }))
vi.mock('@/composables/useFrameManifest', () => ({ whenFrameManifest: async () => null, currentFrameManifest: () => null }))
vi.mock('@/composables/usePocketLock', () => ({ pocketLockEngaged: () => false }))

import router from '@/router'
import { NAV_GROUPS } from './navTable'
import { routeRule } from './navAccess'

const SRC = path.resolve(__dirname, '../..')
const en = JSON.parse(readFileSync(path.join(SRC, 'i18n/locales/en.json'), 'utf-8'))
const icons = readFileSync(path.join(SRC, 'components/Icon.vue'), 'utf-8')
const get = (o: any, key: string) => key.split('.').reduce((v, k) => (v && typeof v === 'object' ? v[k] : undefined), o)
const all = NAV_GROUPS.flatMap((g) => g.items.map((i) => ({ ...i, group: g.id })))

describe('the nav table against the router', () => {
  it('has the groups and their entries (the scan sees the population)', () => {
    expect(NAV_GROUPS.length).toBeGreaterThanOrEqual(7)
    expect(all.length).toBeGreaterThanOrEqual(70)
  })

  it('every entry opens a route that exists', () => {
    const dead = all.filter((i) => router.resolve(i.path).matched.length === 0).map((i) => i.path)
    expect(dead).toEqual([])
  })

  it('one rule: no entry keeps an admin flag of its own, except a tab in a member page', () => {
    for (const i of all as any[]) {
      expect(i.requiresAdmin, i.path).toBeUndefined()
      expect(i.requiredSubFlag, i.path).toBeUndefined()
      if (i.adminFlag) expect(routeRule(router, i.path).admin, `${i.path}: its route is admin-gated itself`).toBe(false)
    }
  })

  it('every administration entry is admin-gated by that rule', () => {
    const admin = all.filter((i) => i.group === 'administration')
    expect(admin.length).toBeGreaterThanOrEqual(30)
    const open = admin.filter((i: any) => !routeRule(router, i.path).admin && !i.adminFlag).map((i) => i.path)
    expect(open).toEqual([])
  })

  it('the pages a visitor may open are the ones the routes call public', () => {
    const pub = all.filter((i) => routeRule(router, i.path).public).map((i) => i.path).sort()
    // V0663: /code-changes is public, as the Guild board and the ballot are; V0664: /announcements, what an admin marked public
    // V0664 M5: /migrate is public too (the template library, shown where the registry runs it); C3: /proxy, the proxy's overview
    expect(pub).toEqual(['/agora/listings', '/announcements', '/become-a-backer', '/code-changes', '/firms', '/forge', '/founders-wall',
      '/frame-commander', '/guild', '/leaderboard', '/migrate', '/operator', '/proxy'].sort())
  })

  it('the default pins and the Bridge stay reachable from a group', () => {
    for (const p of ['/mission-control', '/ourchat', '/pocket/home', '/bridge']) expect(all.some((i) => i.path === p), p).toBe(true)
  })

  it('every label resolves in en.json with its English; every icon is in the icon map', () => {
    for (const g of NAV_GROUPS) expect(get(en, g.i18nKey), g.i18nKey).toBe(g.label)
    for (const i of all) {
      expect(get(en, i.i18nKey ?? ''), i.i18nKey).toBe(i.name)
      expect(icons, i.icon).toContain(`'${i.icon}'`)
    }
  })
})
