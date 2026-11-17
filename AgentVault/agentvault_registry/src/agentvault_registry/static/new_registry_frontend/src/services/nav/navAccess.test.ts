/**
 * V0662 sidebar (order gwo_0feb166a01e2ff611e154361): one rule for who sees a nav entry, read from the route the entry
 * opens (its meta: requiresAuth / allowAnonymous, requiresRole 'admin', requiresAdminFlag), the rule the router's guard
 * already enforces, so the sidebar, the palette and the guard cannot disagree.
 *  - a visitor sees only what a visitor can open (a public route); everything else is hidden, not locked;
 *  - an admin entry shows only to an admin holding that entry's flag (legacy is_admin holds every flag);
 *  - a member's entry that needs an acting agent, a mainframe or the euro lane stays LOCKED (it says why);
 *  - an entry for a feature this registry does not run is hidden.
 * The admin entries come in sub-groups, one per flag. Red on f569f6a6e: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { routeRule, navItemState, adminSubgroups, type NavCtx } from './navAccess'

const fakeRouter = (meta: Record<string, Record<string, unknown>>) => ({
  resolve: (p: string) => ({ meta: meta[p.split('?')[0]] || {}, matched: meta[p.split('?')[0]] ? [{}] : [] }),
})
const R = fakeRouter({
  '/guild': { requiresAuth: false, allowAnonymous: true },
  '/my-agents': { requiresAuth: true },
  '/admin/treasury': { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'treasury' },
  '/admin/agents': { requiresAuth: true, requiresRole: 'admin', requiresAdminFlag: 'platform' },
  '/admin/email': { requiresAuth: true, requiresRole: 'admin' },
  '/federation': { requiresAuth: true },
  '/disputes': { requiresAuth: true },
  '/settlements': { requiresAuth: true },
})

const ctx = (over: Partial<NavCtx> = {}): NavCtx => ({
  signedIn: true, legacyAdmin: false, flags: [], hasAgent: true, isMainframe: true, fiatEnabled: true,
  registryCfg: {}, flareTier: null, ...over,
})
const item = (path: string, extra: Record<string, unknown> = {}) => ({ name: path, path, icon: 'mdi:x', color: '', ...extra })

describe('the route rule', () => {
  it('reads public, admin and the admin flag from the route', () => {
    expect(routeRule(R, '/guild')).toMatchObject({ public: true, admin: false, adminFlag: null })
    expect(routeRule(R, '/admin/treasury')).toMatchObject({ public: false, admin: true, adminFlag: 'treasury' })
    expect(routeRule(R, '/admin/email')).toMatchObject({ admin: true, adminFlag: null })
    expect(routeRule(R, '/federation?tab=operations')).toMatchObject({ admin: false })
  })
})

describe('who sees an entry', () => {
  it('a visitor: only what a visitor can open, the rest hidden', () => {
    const v = ctx({ signedIn: false, hasAgent: false })
    expect(navItemState(item('/guild'), routeRule(R, '/guild'), v)).toBe('show')
    expect(navItemState(item('/my-agents'), routeRule(R, '/my-agents'), v)).toBe('hide')
    expect(navItemState(item('/admin/treasury'), routeRule(R, '/admin/treasury'), v)).toBe('hide')
  })
  it('a member sees no admin entry', () => {
    expect(navItemState(item('/admin/agents'), routeRule(R, '/admin/agents'), ctx())).toBe('hide')
    expect(navItemState(item('/admin/email'), routeRule(R, '/admin/email'), ctx())).toBe('hide')
  })
  it('an admin sees the entries of the flags held; legacy is_admin sees them all', () => {
    const treasurer = ctx({ flags: ['treasury'] })
    expect(navItemState(item('/admin/treasury'), routeRule(R, '/admin/treasury'), treasurer)).toBe('show')
    expect(navItemState(item('/admin/agents'), routeRule(R, '/admin/agents'), treasurer)).toBe('hide')
    expect(navItemState(item('/admin/email'), routeRule(R, '/admin/email'), treasurer), 'admin with no flag named: is_admin only').toBe('hide')
    const root = ctx({ legacyAdmin: true })
    for (const p of ['/admin/treasury', '/admin/agents', '/admin/email']) expect(navItemState(item(p), routeRule(R, p), root)).toBe('show')
  })
  it('a tab inside a member page names its own admin flag, and the same rule applies', () => {
    const it2 = item('/federation?tab=operations', { adminFlag: 'federation' })
    expect(navItemState(it2, routeRule(R, it2.path), ctx())).toBe('hide')
    expect(navItemState(it2, routeRule(R, it2.path), ctx({ flags: ['federation'] }))).toBe('show')
  })
  it('a member\'s entry that needs an agent, the mainframe or the euro lane is locked, saying why', () => {
    expect(navItemState(item('/disputes', { requiresAgent: true }), routeRule(R, '/disputes'), ctx({ hasAgent: false }))).toBe('lock')
    expect(navItemState(item('/disputes', { requiresAgent: true }), routeRule(R, '/disputes'), ctx())).toBe('show')
    expect(navItemState(item('/settlements', { mainframeOnly: true }), routeRule(R, '/settlements'), ctx({ isMainframe: false }))).toBe('lock')
    expect(navItemState(item('/admin/treasury', { requiresFiat: true }), routeRule(R, '/admin/treasury'), ctx({ legacyAdmin: true, fiatEnabled: false }))).toBe('lock')
  })
  it('a feature this registry does not run is hidden', () => {
    expect(navItemState(item('/my-agents', { requiresRegistryFlag: 'cockpit_desk_enabled' }), routeRule(R, '/my-agents'), ctx())).toBe('hide')
    expect(navItemState(item('/my-agents', { requiresRegistryFlag: 'cockpit_desk_enabled' }), routeRule(R, '/my-agents'),
      ctx({ registryCfg: { cockpit_desk_enabled: true } }))).toBe('show')
    expect(navItemState(item('/my-agents', { requiresFlare: true }), routeRule(R, '/my-agents'), ctx())).toBe('hide')
  })
})

describe('the admin sub-groups', () => {
  it('one per flag, in a fixed order, only those with an entry shown', () => {
    const items = ['/admin/agents', '/admin/treasury', '/admin/email'].map((p) => item(p))
    const groups = adminSubgroups(items, (p) => routeRule(R, p), ctx({ legacyAdmin: true }))
    expect(groups.map((g) => g.flag)).toEqual(['platform', 'treasury'])
    expect(groups[0].items.map((i) => i.path)).toEqual(['/admin/agents', '/admin/email'])   // no flag named: platform's
    expect(adminSubgroups(items, (p) => routeRule(R, p), ctx({ flags: ['treasury'] })).map((g) => g.flag)).toEqual(['treasury'])
  })
})
