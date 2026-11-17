// V0666 (room seq 4424): the landing page's "What's new" strip, from the docs' release notes, read after the page is up.
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({
  t: (_k: string, f?: string) => f ?? _k,
  tp: (_k: string, f: string, p: Record<string, unknown> = {}) => f.replace(/\{(\w+)\}/g, (_m, k) => String(p[k] ?? '')),
}) }))

import LandingWhatsNew from './LandingWhatsNew.vue'

const stubs = { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }

describe('the landing page: What\'s new', () => {
  it('the newest release\'s lines, read from the release notes, and one door to all of them', async () => {
    const w = mount(LandingWhatsNew, { global: { stubs } })
    // the notes arrive as their own chunk: wait for the strip, not for a number of ticks
    await vi.waitFor(() => expect(w.find('[data-testid=lp-news]').exists()).toBe(true), { timeout: 10000 })
    expect(w.find('[data-testid=lp-news-version]').text()).toMatch(/^V\d{4}$/)
    const items = w.findAll('[data-testid=lp-news-item]')
    expect(items.length).toBeGreaterThanOrEqual(3)
    expect(items.length).toBeLessThanOrEqual(4)
    expect(JSON.parse(w.find('[data-testid=lp-news-all]').attributes('data-to')!)).toEqual({ path: '/docs/38' })
  })
})
