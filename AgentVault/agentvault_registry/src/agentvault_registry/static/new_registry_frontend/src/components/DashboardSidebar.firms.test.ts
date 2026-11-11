import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * V0658 (v), item 4 (the maintainer's review, sessions' room seq 2181: "firm discovery not reachable from sidebar"):
 * #/firms gets a sidebar entry under AGENTS, beside Agent Discovery. The page is public (the router lets a visitor in),
 * so the entry is not locked for one. The sidebar is too large to mount here, so this reads its nav table; the label's
 * key must resolve in en.json (the raw-key gate reads this table) and its icon must be in the local icon map.
 * RED on 553347408 (origin/v0657/cut): no entry names /firms.
 */
const SRC = path.resolve(__dirname, '..')
const sidebar = readFileSync(path.join(SRC, 'components/DashboardSidebar.vue'), 'utf-8')
const en = JSON.parse(readFileSync(path.join(SRC, 'i18n/locales/en.json'), 'utf-8'))
const router = readFileSync(path.join(SRC, 'router/index.ts'), 'utf-8')
const icons = readFileSync(path.join(SRC, 'components/Icon.vue'), 'utf-8')

const get = (o: any, key: string) => key.split('.').reduce((v, k) => (v && typeof v === 'object' ? v[k] : undefined), o)

describe('the sidebar reaches #/firms', () => {
  const agents = sidebar.slice(sidebar.indexOf("label: 'AGENTS'"), sidebar.indexOf("label: 'ECONOMY'"))
  const entry = agents.match(/\{ name: '([^']+)', i18nKey: '([^']+)', path: '\/firms', icon: '([^']+)'[^}]*\}/)

  it('an entry under AGENTS, right after Agent Discovery', () => {
    expect(agents.length, 'the AGENTS group').toBeGreaterThan(0)
    expect(entry, 'an AGENTS entry for /firms').not.toBeNull()
    expect(agents.indexOf("path: '/firms'")).toBeGreaterThan(agents.indexOf("path: '/discover'"))
    expect(agents.indexOf("path: '/firms'")).toBeLessThan(agents.indexOf("path: '/federation-discover'"))
  })

  it('its label resolves in en.json and its icon is in the icon map', () => {
    const [, name, key, icon] = entry!
    expect(get(en, key), `${key} in en.json`).toBe(name)
    expect(icons).toContain(`'${icon}'`)
  })

  it('a visitor can open it: the route is public, and so is the entry', () => {
    expect(router).toMatch(/path: 'firms',\s*name: 'public-firms',[\s\S]{0,120}requiresAuth: false, allowAnonymous: true/)
    const pub = sidebar.slice(sidebar.indexOf('const PUBLIC_PATHS'), sidebar.indexOf('])', sidebar.indexOf('const PUBLIC_PATHS')))
    expect(pub).toContain("'/firms'")
  })
})
