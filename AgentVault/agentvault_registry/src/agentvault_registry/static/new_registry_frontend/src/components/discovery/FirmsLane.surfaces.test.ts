/**
 * V0658 (v), the Firms strip in Agent Discovery (the maintainer's review, sessions' room seq 2181, screenshot 210358):
 *  - item 1: a firm shows its organization's logo, the one this registry hosts (services/orgMark.ts safeLogo, the rule
 *    #/firms follows); no hosted logo, or an address elsewhere, shows the placeholder mark and loads nothing;
 *  - item 6: the firm's own count stays the firm's ("As the firm": jobs delivered, commissioned), and the settled work
 *    its member agents did on their own is a separate, labelled line, never added to the firm's number; a read that
 *    could not say (no member_work in the answer) shows no line rather than a zero;
 *  - item 3: "Post a bounty to this firm" stays in the shell it is pressed in (firmBountyDoor, session-lead's decision,
 *    the sessions' room seq 2389): in the desktop console's Discovery the Guild board, his saved Pocket choice
 *    notwithstanding; where no shell is mounted (the public Explore page), where the landing decision says. The firm is
 *    reserved on both.
 * RED on 553347408 (origin/v0657/cut): no logo, no member line, and the bounty went to /guild on every width.
 * RED on e0fe8732c (item 3): pressed in the desktop console with Pocket saved, the bounty opened Pocket's Payments.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ get: vi.fn(), push: vi.fn(), route: { query: {} as Record<string, string> } }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get } }))
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ push: h.push, replace: vi.fn(async () => {}) }) }))

import FirmsLane from './FirmsLane.vue'
import * as uiMode from '@/services/uiMode'

// read off the module, so the binding the shell rule adds fails as an assertion where it is missing
const doors = uiMode as unknown as Record<string, any>
const bindIfThere = (router: unknown) => { if (typeof doors.bindDoorRouter === 'function') doors.bindDoorRouter(router) }

const LOGO = '/api/v1/organizations/org-1/logo?v=abcdef123456'
const SESSIONS = { org_id: 'org-1', slug: 'sessions', name: 'TheProtocol Sessions', verified_jobs: 0, commissioned: 0,
  stars_n: 0, logo: LOGO, transparency: true, engage_available: false, engage_reason: 'no intake agent',
  member_work: { jobs: 52, commissioned: 4 } }
const REACH = { org_id: 'org-2', slug: 'reach', name: 'Reach Limited', verified_jobs: 3, commissioned: 1, stars_n: 0,
  logo: null, engage_available: false, engage_reason: 'no intake agent', member_work: { jobs: 0, commissioned: 0 } }
const ELSEWHERE = { org_id: 'org-3', slug: 'elsewhere', name: 'Elsewhere', verified_jobs: 0, commissioned: 0, stars_n: 0,
  logo: 'https://tracker.example/pixel.png', engage_available: false, engage_reason: 'no intake agent' }

async function lane(firms: any[]) {
  h.get.mockResolvedValue({ data: { firms } })
  const w = mount(FirmsLane)
  await flushPromises()
  return w
}

describe("Discovery's Firms strip", () => {
  beforeEach(() => {
    h.get.mockReset(); h.push.mockReset(); h.route = reactive({ query: {} })
    localStorage.clear()
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
  })
  afterEach(() => { bindIfThere(null); localStorage.clear() })

  it('shows the hosted logo, and the placeholder where there is none or it is hosted elsewhere', async () => {
    const w = await lane([SESSIONS, REACH, ELSEWHERE])
    const img = w.find('[data-testid="fl-logo-sessions"] img')
    expect(img.exists(), 'the firm with a hosted logo shows it').toBe(true)
    expect(img.attributes('src')).toBe(LOGO)
    expect(img.attributes('referrerpolicy')).toBe('no-referrer')
    for (const slug of ['reach', 'elsewhere']) {
      const box = w.find(`[data-testid="fl-logo-${slug}"]`)
      expect(box.exists(), `${slug} keeps the logo's place`).toBe(true)
      expect(box.find('img').exists(), `${slug} loads no image`).toBe(false)
    }
    expect(w.html()).not.toContain('tracker.example')
  })

  it("keeps the firm's own count and adds its agents' own work as a separate, labelled line", async () => {
    const w = await lane([SESSIONS, REACH, ELSEWHERE])
    const sessions = w.find('[data-testid="fl-firm-sessions"]')
    const own = sessions.find('[data-testid="fl-proof"]')
    expect(own.text()).toContain('As the firm')
    expect(own.text()).toMatch(/0\s*jobs delivered/)
    expect(own.text()).toMatch(/0\s*commissioned/)
    expect(own.text(), "the agents' jobs are never added into the firm's").not.toContain('52')
    const members = sessions.find('[data-testid="fl-members"]')
    expect(members.exists()).toBe(true)
    expect(members.text()).toContain('By its agents')
    expect(members.text()).toMatch(/52\s*jobs delivered/)
    expect(members.text()).toMatch(/4\s*commissioned/)
    expect(members.attributes('title')).toMatch(/never added/i)

    const reach = w.find('[data-testid="fl-firm-reach"]')
    expect(reach.find('[data-testid="fl-proof"]').text()).toMatch(/3\s*jobs delivered/)
    expect(reach.find('[data-testid="fl-members"]').text(), 'an answered zero is shown as none, with the sentence of why').toMatch(/none yet.*counts here once an order its agents were awarded, or posted, settles/)
    expect(w.find('[data-testid="fl-firm-elsewhere"] [data-testid="fl-members"]').exists(),
      'no member_work in the answer: no line, never a false zero').toBe(false)
  })

  it('one job reads as one job', async () => {
    const w = await lane([{ ...REACH, member_work: { jobs: 1, commissioned: 0 } }])
    expect(w.find('[data-testid="fl-members"]').text()).toMatch(/1\s*jobs delivered/)
  })

  it('pressed in the desktop console, the bounty door opens the Guild board, Pocket saved and a narrow window notwithstanding', async () => {
    bindIfThere({ currentRoute: { value: { path: '/discover', meta: { shell: 'desktop' } } } })
    localStorage.setItem(uiMode.UI_MODE_KEY, 'pocket')
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const w = await lane([REACH])
    await w.find('[data-testid="fl-bounty-reach"]').trigger('click')
    expect(h.push).toHaveBeenLastCalledWith({ path: '/guild', query: { post: '1', for_org: 'org-2', title: 'For Reach Limited: ' } })
  })

  it('where no shell is mounted (the public Explore page), the bounty door follows the landing decision, the firm reserved', async () => {
    bindIfThere({ currentRoute: { value: { path: '/explore', meta: {} } } })
    const w = await lane([REACH])
    await w.find('[data-testid="fl-bounty-reach"]').trigger('click')
    expect(h.push).toHaveBeenLastCalledWith({ path: '/guild', query: { post: '1', for_org: 'org-2', title: 'For Reach Limited: ' } })
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    await w.find('[data-testid="fl-bounty-reach"]').trigger('click')
    expect(h.push).toHaveBeenLastCalledWith({ path: '/pocket/payments', query: { post: '1', for_org: 'org-2', title: 'For Reach Limited: ' } })
  })
})
