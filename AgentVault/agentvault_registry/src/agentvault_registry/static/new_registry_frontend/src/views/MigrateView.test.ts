import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0664 M5 (order gwo_5a4ea8476b97147f3056405e): the Migrate gallery. Three steps, the filters (from, to, free or paid, search,
 * sort), a card per template (title, from to, price or Free, uses, certified runs, forks), and the three states of a read: loading,
 * none (only after the read said so), failed (the registry's own sentence).
 */
const h = vi.hoisted(() => ({ list: null as any }))
vi.mock('@/services/api/workflowTemplates', () => ({ listTemplates: (...a: any[]) => h.list(...a) }))

import MigrateView from './MigrateView.vue'
import { normalizeListing } from '@/services/migrate/templates'

const row = (o: Record<string, any>) => normalizeListing({ id: 't1', title: 'Postgres to Atlas', from_kind: 'sql', to_kind: 'rest', pricing_model: 'free',
  price: '0.0000000000', price_currency: '', counts: { kit_downloads: 12, instantiations: 5, certified: 3, forks: 1 }, current_version: 1, ...o })
const mountIt = () => mount(MigrateView, { global: { stubs: { Icon: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })


// V0664 console proof (axe scrollable-region-focusable, session-lead seq 4206): a code box that can scroll is reachable by
// keyboard and named: tabindex 0, role region, an aria-label
function codeBoxesReachable(w: any) {
  const pres = w.findAll('pre')
  expect(pres.length).toBeGreaterThan(0)
  for (const p of pres) {
    expect(p.attributes('tabindex'), p.html().slice(0, 60)).toBe('0')
    expect(p.attributes('role')).toBe('region')
    expect((p.attributes('aria-label') || '').trim().length).toBeGreaterThan(3)
  }
}

describe('the Migrate gallery', () => {
  beforeEach(() => { vi.useFakeTimers(); h.list = vi.fn().mockResolvedValue([]) })
  afterEach(() => { vi.useRealTimers() })

  it('says the three steps and the way to write your own, whatever the library holds', async () => {
    const w = mountIt()
    await flushPromises()
    expect(w.find('[data-testid="mg-steps"]').findAll('li')).toHaveLength(3)
    expect(w.find('[data-testid="mg-own-commands"]').text()).toContain('tp-proxy')
  })

  it('offers the two things a visitor does next: build a migration and read a report', async () => {
    const w = mountIt()
    await flushPromises()
    expect(JSON.parse(w.find('[data-testid="mg-cta-build"]').attributes('data-to')!)).toEqual({ name: 'migrate-new' })
    expect(JSON.parse(w.find('[data-testid="mg-cta-report"]').attributes('data-to')!)).toEqual({ name: 'migrate-report' })
  })

  it('shows placeholder cards while the first read is out, and says so to a screen reader', async () => {
    let done: (v: any) => void = () => {}
    h.list = vi.fn().mockReturnValue(new Promise((r) => { done = r }))
    const w = mountIt()
    await w.vm.$nextTick()
    const sk = w.find('[data-testid="mg-loading"]')
    expect(sk.exists()).toBe(true)
    expect(sk.attributes('aria-busy')).toBe('true')
    expect(sk.text()).toContain('Reading the library')
    expect(sk.findAll('.mg-skel-card')).toHaveLength(3)
    done([row({})]); await flushPromises()
    expect(w.find('[data-testid="mg-loading"]').exists()).toBe(false)
  })

  it('shows a card per template with its price, uses and certified runs, and a free one as Free', async () => {
    h.list = vi.fn().mockResolvedValue([row({}), row({ id: 't2', title: 'Files to Ledger', pricing_model: 'purchase', price: '25.0000000000', price_currency: 'ECU' })])
    const w = mountIt()
    await flushPromises()
    expect(w.findAll('[data-testid^="mg-card-"]')).toHaveLength(2)
    expect(w.find('[data-testid="mg-price-t1"]').text()).toBe('Free')
    expect(w.find('[data-testid="mg-price-t2"]').text()).toBe('25 ECU')
    expect(w.find('[data-testid="mg-card-t1"]').text()).toContain('12 downloads')
    expect(w.find('[data-testid="mg-card-t1"]').text()).toContain('certified by 3 developers')
  })

  it('applies the filters to what comes back, even from a registry that answers with everything', async () => {
    h.list = vi.fn().mockResolvedValue([row({}), row({ id: 't2', title: 'Files to Ledger', from_kind: 'file', pricing_model: 'purchase', price: '25.0000000000', price_currency: 'ECU' })])
    const w = mountIt()
    await flushPromises()
    await w.find('[data-testid="mg-filter-price"]').setValue('paid')
    expect(w.findAll('[data-testid^="mg-card-"]').map((c) => c.attributes('data-testid'))).toEqual(['mg-card-t2'])
    await w.find('[data-testid="mg-filter-price"]').setValue('any')
    await w.find('[data-testid="mg-filter-from"]').setValue('sql')
    expect(w.findAll('[data-testid^="mg-card-"]').map((c) => c.attributes('data-testid'))).toEqual(['mg-card-t1'])
  })

  it('asks the registry again once a typed search pauses, not on every key', async () => {
    const w = mountIt()
    await flushPromises()
    expect(h.list).toHaveBeenCalledTimes(1)
    await w.find('[data-testid="mg-q"]').setValue('ora')
    await w.find('[data-testid="mg-q"]').setValue('oracle')
    expect(h.list).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(300)
    expect(h.list).toHaveBeenCalledTimes(2)
    expect(h.list.mock.calls[1][0].q).toBe('oracle')
  })

  it('says none only after a read said so, and says a failed read in the registry\'s own words', async () => {
    const w = mountIt()
    expect(w.find('[data-testid="mg-empty"]').exists()).toBe(false)           // still reading: not "none"
    await flushPromises()
    expect(w.find('[data-testid="mg-empty"]').exists()).toBe(true)
    h.list = vi.fn().mockRejectedValue({ response: { data: { detail: 'the library is paused' } } })
    await w.find('[data-testid="mg-q"]').setValue('x')
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(w.find('[data-testid="mg-error"]').text()).toBe('the library is paused')
    expect(w.find('[data-testid="mg-empty"]').exists()).toBe(false)
  })

  it('the commands to write your own are reachable by keyboard and named (proof seq 4206, /migrate on a phone)', async () => {
    const w = mountIt()
    await flushPromises()
    codeBoxesReachable(w)
  })
})
