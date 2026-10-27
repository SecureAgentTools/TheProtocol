import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import CommonsAdmin from './CommonsAdmin.vue'

/**
 * §MEMBERSHIP phase C (2026-10-02) — the admin controls of a season: every action asks a second time before it is
 * emitted, a cancel needs a public reason, and the payment line counts exactly the awards still unpaid.
 */
const DAY = 86_400_000
function season(over: Record<string, unknown> = {}) {
  return { id: 4, title: 'Autumn', status: 'open', currency: 'SBXA', opens_at: null, ends_at: new Date(Date.now() + 7 * DAY).toISOString(),
    budget: '500', seed: '0', fee_share_percent: '50', fee_collector_balance_at_open: '1000', recipient_cap_percent: '20',
    min_voters: 2, ballot_points: 100, closed_at: null, paid_at: null, cancelled_at: null, cancel_reason: null,
    tally: null, submissions: [], ballots_cast: 0, ballots: null, my_ballot: null, ...over } as any
}
const award = (status: string, amount: string) => ({ median_points: '10', voters: 2, share: '0.5', amount, status, funded_amount: null, shortfall: null, paid_at: null })

describe('the commons admin controls', () => {
  it('opening: the window is checked, and nothing is emitted before the second press', async () => {
    const w = mount(CommonsAdmin, { props: { season: null } })
    expect(w.attributes('data-mode')).toBe('open')
    await w.find('[data-testid="commons-open-days"]').setValue(0)
    expect(w.find('[data-testid="commons-open"]').attributes('disabled')).toBeDefined()
    await w.find('[data-testid="commons-open-days"]').setValue(14)
    await w.find('[data-testid="commons-open-seed"]').setValue('250')
    await w.find('form').trigger('submit')
    expect(w.emitted('act')).toBeUndefined()
    await w.find('[data-testid="commons-admin-confirm-yes"]').trigger('click')
    expect(w.emitted('act')).toEqual([[{ kind: 'open', body: { title: '', durationDays: 14, seed: '250', feeSharePercent: undefined } }]])
  })

  it('a running season can be closed, after the second press', async () => {
    const w = mount(CommonsAdmin, { props: { season: season() } })
    expect(w.attributes('data-mode')).toBe('running')
    await w.find('[data-testid="commons-close"]').trigger('click')
    expect(w.emitted('act')).toBeUndefined()
    await w.find('[data-testid="commons-admin-confirm-yes"]').trigger('click')
    expect(w.emitted('act')).toEqual([[{ kind: 'close' }]])
  })

  it('a closed season counts its unpaid awards (pending and failed, never paid) and pays them', async () => {
    const s = season({ status: 'closed', submissions: [
      { id: 1, award: award('pending', '100') }, { id: 2, award: award('failed', '50.5') }, { id: 3, award: award('paid', '70') }, { id: 4, award: null },
    ] })
    const w = mount(CommonsAdmin, { props: { season: s } })
    expect(w.find('[data-testid="commons-pay-summary"]').text()).toContain('Unpaid awards: 2, 150.5 SBXA in all')
    await w.find('[data-testid="commons-pay"]').trigger('click')
    await w.find('[data-testid="commons-admin-confirm-yes"]').trigger('click')
    expect(w.emitted('act')).toEqual([[{ kind: 'pay' }]])
  })

  it('once payment started a closed season is finished by paying or writing off, never cancelled', () => {
    const started = season({ status: 'closed', submissions: [{ id: 1, award: { ...award('failed', '10'), attempted_at: '2026-10-02T10:00:00Z' } }] })
    expect(mount(CommonsAdmin, { props: { season: started } }).find('[data-testid="commons-cancel"]').exists()).toBe(false)
    const notYet = season({ status: 'closed', submissions: [{ id: 1, award: award('pending', '10') }] })
    expect(mount(CommonsAdmin, { props: { season: notYet } }).find('[data-testid="commons-cancel"]').exists()).toBe(true)
  })

  it('cancelling needs a public reason of at least five characters', async () => {
    const w = mount(CommonsAdmin, { props: { season: season() } })
    await w.find('[data-testid="commons-cancel"]').trigger('click')
    await w.find('[data-testid="commons-cancel-reason"]').setValue('oops')
    expect(w.find('[data-testid="commons-admin-confirm-yes"]').attributes('disabled')).toBeDefined()
    await w.find('[data-testid="commons-cancel-reason"]').setValue('opened by mistake')
    await w.find('[data-testid="commons-admin-confirm-yes"]').trigger('click')
    expect(w.emitted('act')).toEqual([[{ kind: 'cancel', reason: 'opened by mistake' }]])
  })

  it('control: a paid or cancelled season offers nothing', () => {
    expect(mount(CommonsAdmin, { props: { season: season({ status: 'paid' }) } }).find('[data-testid="commons-admin"]').exists()).toBe(false)
    expect(mount(CommonsAdmin, { props: { season: season({ status: 'cancelled' }) } }).find('[data-testid="commons-admin"]').exists()).toBe(false)
  })
})
