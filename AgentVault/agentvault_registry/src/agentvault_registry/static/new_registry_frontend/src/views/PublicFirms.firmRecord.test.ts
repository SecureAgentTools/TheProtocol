/**
 * V0662, the Firms page (order gwo_814eb06d62b799eba095e70c; organizations package item 2,
 * sessionlogs2026/PLAN_2026-11-13_ORGANIZATIONS_PACKAGE.md). TheProtocol Quantum read "No work records yet" on #/firms
 * while its agents had settled 3 jobs. The count is right by the rule V0658 (v) chose (a firm's own record is work
 * delivered or commissioned AS the firm; its agents' own work is `member_work`, apart) and stays as it is; the page said
 * nothing about it and drew no logo. Now the picked firm's panel draws its hosted logo (services/orgMark.safeLogo, a
 * placeholder when it does not load), its own record from GET /organizations/{id}/track-record ("as the firm: n jobs
 * delivered, m commissioned"), the agents' own work beside it when the registry states it, and one sentence on what
 * counts. A record that could not be read shows no line at all (unknown is not zero); the records feed stands.
 * Red on f569f6a6e: no logo, no record line, no sentence.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ get: vi.fn(), route: { query: {} as Record<string, any> }, record: {} as Record<string, any> }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get }, apiClient: { get: h.get } }))
vi.mock('vue-router', () => ({ useRoute: () => h.route }))

import PublicFirms from './PublicFirms.vue'

const FIRMS = [
  { org_id: 'org-q', name: 'TheProtocol Quantum', slug: 'quantum', description: null, topic: null, logo: '/api/v1/organizations/org-q/logo' },
  { org_id: 'org-s', name: 'TheProtocol Sessions', slug: 'sessions', description: null, topic: null, logo: null },
]
const feed = (org_id: string) => ({ org_id, name: FIRMS.find((f) => f.org_id === org_id)!.name, slug: '', topic: null, records: [], next_before_seq: null })

async function page() {
  h.get.mockImplementation(async (url: string) => {
    if (url === '/organizations/public/transparent') return { data: { organizations: FIRMS } }
    let m = url.match(/^\/organizations\/(org-\w)\/public-feed$/)
    if (m) return { data: feed(m[1]) }
    m = url.match(/^\/organizations\/(org-\w)\/track-record$/)
    if (m) {
      const r = h.record[m[1]]
      if (r instanceof Error) throw r
      return { data: r }
    }
    throw new Error(`unexpected read ${url}`)
  })
  const w = mount(PublicFirms, { global: { stubs: { OrgDirectory: true, ViewAmbient: true } } })
  await flushPromises()
  return w
}

describe('the picked firm on #/firms', () => {
  beforeEach(() => {
    h.get.mockReset(); h.route = reactive({ query: {} })
    h.record = {
      'org-q': { verified_jobs: 0, commissioned: { orders: 0 }, member_work: { jobs: 3, commissioned: 2 } },
      'org-s': { verified_jobs: 4, commissioned: { orders: 2 } },   // no member_work: the registry does not state it
    }
  })

  it('its own record, its agents\' own work beside it, and what counts; the empty feed still says so', async () => {
    const w = await page()
    try {
      const head = w.find('[data-testid="pf-firm-record"]')
      expect(head.text(), 'a zero says why').toContain('As the firm: none yet. Work counts here when an order is posted through the organization')
      expect(w.find('[data-testid="pf-member-work"]').text()).toContain('By its agents: 3 jobs delivered, 2 commissioned')
      expect(w.find('[data-testid="pf-counting"]').text()).toMatch(/as the firm/i)
      expect(w.text()).toContain('No work records yet.')
    } finally { w.unmount() }
  })

  it('its hosted logo, and the placeholder when the image does not load', async () => {
    const w = await page()
    try {
      const img = w.find('[data-testid="pf-logo"] img')
      expect(img.attributes('src')).toBe('/api/v1/organizations/org-q/logo')
      await img.trigger('error')
      expect(w.find('[data-testid="pf-logo"] img').exists()).toBe(false)
      expect(w.find('[data-testid="pf-logo"]').text()).toContain('◈')
    } finally { w.unmount() }
  })

  it('an answered zero for its agents says why, in the page\'s own words (V0666)', async () => {
    h.record['org-q'] = { verified_jobs: 1, commissioned: { orders: 0 }, member_work: { jobs: 0, commissioned: 0 } }
    const w = await page()
    try {
      const line = w.find('[data-testid="pf-member-work"]').text()
      expect(line).toContain('By its agents: none yet.')
      expect(line).toContain('A job counts here once an order its agents were awarded, or posted, settles')
    } finally { w.unmount() }
  })

  it('a firm whose registry states no agents\' work gets no such line, never a zero', async () => {
    const w = await page()
    try {
      await w.find('[data-testid="pf-firm-sessions"]').trigger('click'); await flushPromises()
      expect(w.find('[data-testid="pf-firm-record"]').text()).toContain('As the firm: 4 jobs delivered, 2 commissioned')
      expect(w.find('[data-testid="pf-member-work"]').exists()).toBe(false)
      expect(w.find('[data-testid="pf-logo"] img').exists(), 'no logo: the placeholder').toBe(false)
    } finally { w.unmount() }
  })

  it('a record that could not be read shows no line at all; the feed stands (control)', async () => {
    h.record['org-q'] = new Error('502')
    const w = await page()
    try {
      expect(w.find('[data-testid="pf-firm-record"]').exists()).toBe(false)
      expect(w.find('[data-testid="pf-member-work"]').exists()).toBe(false)
      expect(w.find('[data-testid="pf-feed"]').text()).toContain('TheProtocol Quantum')
    } finally { w.unmount() }
  })
})
