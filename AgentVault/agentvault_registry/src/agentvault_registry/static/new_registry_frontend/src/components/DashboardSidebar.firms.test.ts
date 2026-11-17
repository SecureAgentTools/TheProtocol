import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * V0658 (v), item 4 (the maintainer's review, sessions' room seq 2181: "firm discovery not reachable from sidebar"):
 * #/firms gets a sidebar entry. The page is public (the router lets a visitor in), so a visitor sees the entry.
 * V0662 sidebar: the table moved to services/nav/navTable (his task groups of 2026-11-13), and #/firms now sits in
 * Organizations, right after Organizations; who sees it is the route's own rule (services/nav/navAccess).
 * RED on 553347408 (origin/v0657/cut): no entry names /firms.
 */
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: false }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({}) }))
vi.mock('@/composables/useFrameManifest', () => ({ whenFrameManifest: async () => null, currentFrameManifest: () => null }))
vi.mock('@/composables/usePocketLock', () => ({ pocketLockEngaged: () => false }))

import router from '@/router'
import { NAV_GROUPS } from '@/services/nav/navTable'
import { navItemState, routeRule } from '@/services/nav/navAccess'

const SRC = path.resolve(__dirname, '..')
const en = JSON.parse(readFileSync(path.join(SRC, 'i18n/locales/en.json'), 'utf-8'))
const icons = readFileSync(path.join(SRC, 'components/Icon.vue'), 'utf-8')
const get = (o: any, key: string) => key.split('.').reduce((v, k) => (v && typeof v === 'object' ? v[k] : undefined), o)

describe('the sidebar reaches #/firms', () => {
  const orgs = NAV_GROUPS.find((g) => g.id === 'organizations')!
  const entry = orgs?.items.find((i) => i.path === '/firms')

  it('an entry under Organizations, right after Organizations', () => {
    expect(entry, 'an Organizations entry for /firms').toBeDefined()
    const paths = orgs.items.map((i) => i.path)
    expect(paths.indexOf('/firms')).toBe(paths.indexOf('/organization') + 1)
  })

  it('its label resolves in en.json and its icon is in the icon map', () => {
    expect(get(en, entry!.i18nKey!), `${entry!.i18nKey} in en.json`).toBe(entry!.name)
    expect(icons).toContain(`'${entry!.icon}'`)
  })

  it('a visitor can open it: the route is public, and so a visitor sees the entry', () => {
    const rule = routeRule(router, '/firms')
    expect(rule.public).toBe(true)
    expect(navItemState(entry!, rule, { signedIn: false, legacyAdmin: false, flags: [], hasAgent: false, isMainframe: true,
      fiatEnabled: false, registryCfg: {}, flareTier: null })).toBe('show')
  })
})
