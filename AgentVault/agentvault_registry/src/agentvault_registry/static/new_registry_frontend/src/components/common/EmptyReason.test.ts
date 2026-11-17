/**
 * V0663 (his yes seq 3068, "empty lists that say why"): the one reason line under a list that is empty for a reason.
 * It says the reason it is given (as a prop or as a slot), carries its kind for the page and the tests, is announced as a
 * status, and offers its action only when it is given a label. BASE: the component does not exist.
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EmptyReason from './EmptyReason.vue'

describe('EmptyReason', () => {
  it('says the reason it is given, as a status, and carries its kind', () => {
    const w = mount(EmptyReason, { props: { kind: 'filtered', reason: 'Nothing matches certified only.' } })
    const p = w.get('[data-testid="empty-reason"]')
    expect(p.text()).toBe('Nothing matches certified only.')
    expect(p.attributes('role')).toBe('status')
    expect(p.attributes('data-kind')).toBe('filtered')
    expect(w.find('button').exists()).toBe(false)
  })

  it('takes the reason as a slot too, and defaults to "none yet"', () => {
    const w = mount(EmptyReason, { slots: { default: 'The ledger is quiet.' } })
    expect(w.text()).toBe('The ledger is quiet.')
    expect(w.get('[data-testid="empty-reason"]').attributes('data-kind')).toBe('none-yet')
  })

  it('offers its action only with a label, and emits it', async () => {
    const w = mount(EmptyReason, { props: { kind: 'filtered', reason: 'Nothing matches.', actionLabel: 'Clear filters' } })
    const b = w.get('[data-testid="empty-reason-action"]')
    expect(b.text()).toBe('Clear filters')
    await b.trigger('click')
    expect(w.emitted('action')).toHaveLength(1)
  })
})
