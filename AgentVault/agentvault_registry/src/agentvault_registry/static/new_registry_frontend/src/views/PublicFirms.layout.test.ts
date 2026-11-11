/**
 * V0658 (v), item 5 (the maintainer's review, sessions' room seq 2181, screenshot 210418): on #/firms the selected
 * firm's records panel sat off-axis, below the directory and beside a narrow column holding one button. The page is
 * laid out for desktop width now: one grid, the organizations on the left and the records on the right, both starting
 * on the same line; the firms with open books are picked inside the records panel (no separate narrow column); the
 * picked firm is marked in the directory too. Below desktop width the two stack, the records after the directory.
 * The DOM structure is read from a mount; the two-column rule from the view's own style (jsdom lays nothing out); the
 * browser load of the stage after this one measures it.
 * RED on 553347408 (origin/v0657/cut): no layout grid, the picker is a 300px aside beside the feed.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import fs from 'node:fs'
import path from 'node:path'

const h = vi.hoisted(() => ({ get: vi.fn(), route: { query: {} as Record<string, any> } }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get }, apiClient: { get: h.get } }))
vi.mock('vue-router', () => ({ useRoute: () => h.route }))

import PublicFirms from './PublicFirms.vue'

const FIRMS = [
  { org_id: 'org-2', name: 'Reach Limited', slug: 'reach', description: 'visibility', topic: null },
  { org_id: 'org-1', name: 'TheProtocol Sessions', slug: 'sessions', description: 'the sessions', topic: 'building' },
]
const feed = (org_id: string, name: string) => ({ org_id, name, slug: '', topic: null, records: [], next_before_seq: null })

const OrgDirectoryStub = { name: 'OrgDirectory', props: ['highlight'], template: '<section data-testid="org-directory-stub" :data-highlight="highlight || \'\'"></section>' }

async function page() {
  h.get.mockImplementation(async (url: string) => {
    if (url === '/organizations/public/transparent') return { data: { organizations: FIRMS } }
    const m = url.match(/^\/organizations\/(org-\d)\/public-feed$/)
    if (m) return { data: feed(m[1], m[1] === 'org-1' ? 'TheProtocol Sessions' : 'Reach Limited') }
    throw new Error(`unexpected read ${url}`)
  })
  const w = mount(PublicFirms, { global: { stubs: { OrgDirectory: OrgDirectoryStub, ViewAmbient: true } } })
  await flushPromises()
  return w
}

describe('#/firms, laid out for desktop width', () => {
  beforeEach(() => { h.get.mockReset(); h.route = reactive({ query: {} }) })

  it('one grid: the directory beside the records panel, the picker inside the panel', async () => {
    const w = await page()
    const layout = w.find('[data-testid="pf-layout"]')
    expect(layout.exists(), 'the page grid').toBe(true)
    const cols = layout.element.children
    expect(cols.length, 'two columns').toBe(2)
    expect(cols[0].querySelector('[data-testid="org-directory-stub"]'), 'the directory, first').not.toBeNull()
    const records = w.find('[data-testid="pf-records"]')
    expect(cols[1]).toBe(records.element)
    expect(records.find('[data-testid="pf-firm-reach"]').exists(), 'the picker sits in the records panel').toBe(true)
    expect(records.find('[data-testid="pf-firm-sessions"]').exists()).toBe(true)
    expect(records.find('[data-testid="pf-feed"]').exists()).toBe(true)
    expect(w.find('aside.pfw-list').exists(), 'no narrow column beside the feed').toBe(false)
  })

  it('the picked firm is marked in the directory and in the picker', async () => {
    const w = await page()
    const dir = () => w.find('[data-testid="org-directory-stub"]').attributes('data-highlight')
    expect(dir(), 'the first firm is picked on arrival').toBe('reach')
    expect(w.find('[data-testid="pf-firm-reach"]').attributes('aria-pressed')).toBe('true')
    await w.find('[data-testid="pf-firm-sessions"]').trigger('click')
    await flushPromises()
    expect(dir()).toBe('sessions')
    expect(w.find('[data-testid="pf-firm-sessions"]').attributes('aria-pressed')).toBe('true')
    expect(w.find('[data-testid="pf-firm-reach"]').attributes('aria-pressed')).toBe('false')
    expect(w.find('[data-testid="pf-feed"]').text()).toContain('TheProtocol Sessions')
  })

  it('an organization named in the address is the one marked', async () => {
    h.route = reactive({ query: { org: 'sessions' } })
    const w = await page()
    expect(w.find('[data-testid="org-directory-stub"]').attributes('data-highlight')).toBe('sessions')
    expect(w.find('[data-testid="pf-firm-sessions"]').attributes('aria-pressed')).toBe('true')
  })

  it('the style puts the two side by side at desktop width and uses that width', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'PublicFirms.vue'), 'utf8')
    const style = src.slice(src.indexOf('<style'))
    const inner = style.match(/\.pfw-inner \{[^}]*max-width:\s*(\d+)px/)
    expect(inner, 'the page width').not.toBeNull()
    expect(Number(inner![1])).toBeGreaterThanOrEqual(1280)
    const media = style.match(/@media \(min-width:\s*(\d+)px\)\s*\{([^}]*\.pfw-layout \{[^}]*\})/)
    expect(media, 'a desktop rule for the grid').not.toBeNull()
    expect(Number(media![1])).toBeLessThanOrEqual(1280)
    const cols = media![2].match(/grid-template-columns:\s*([^;]+);/)
    expect(cols, 'the desktop grid names its columns').not.toBeNull()
    expect(cols![1].trim().split(/\s+(?![^(]*\))/).length, 'two columns at desktop width').toBe(2)
    expect(style).toMatch(/\.pfw-layout \{[^}]*align-items:\s*start/)
  })
})
