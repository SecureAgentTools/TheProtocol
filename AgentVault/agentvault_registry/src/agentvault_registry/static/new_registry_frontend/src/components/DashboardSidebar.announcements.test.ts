/**
 * V0664 (order gwo_1b3e2cc74c1afec6c6cedc3d): the sidebar shows the public announcements strip to a VISITOR only, in the place of
 * its one sign-in line, and the page it points at is a public route. BASE: neither exists.
 */
import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

const SRC = path.resolve(__dirname, '..')
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf8')

describe('the visitor sidebar and the announcements page', () => {
  it('mounts the strip only for a visitor with the sidebar open, just above the sign-in line', () => {
    const src = read('components/DashboardSidebar.vue')
    const strip = src.indexOf('<PublicAnnouncementsStrip')
    expect(strip).toBeGreaterThan(-1)
    expect(src.slice(strip, strip + 120)).toContain('v-if="!authStore.isAuthenticated && !isCollapsed"')
    expect(strip).toBeLessThan(src.indexOf('data-testid="nav-guest-signin"'))
    expect(src).toContain("import PublicAnnouncementsStrip from '@/components/PublicAnnouncementsStrip.vue'")
  })

  it('the page is a public route and an entry of the Network views group', () => {
    const router = read('router/index.ts')
    const at = router.indexOf("path: 'announcements'")
    expect(at).toBeGreaterThan(-1)
    expect(router.slice(at, at + 260)).toContain('requiresAuth: false, allowAnonymous: true')
    expect(read('services/nav/navTable.ts')).toContain("path: '/announcements'")
  })
})
