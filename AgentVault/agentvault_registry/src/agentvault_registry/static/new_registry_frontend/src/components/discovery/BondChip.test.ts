import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BondChip from './BondChip.vue'

/**
 * §BATCH0911 item 3 — the bond chip is ONE component mounted by both discovery densities.
 * It renders for a bonded agent (from the bond block OR the row's flag), says locked vs matured,
 * and renders nothing at all for an agent with no bond: absent is not "0 bonded".
 */
const chip = (props: Record<string, unknown>) => mount(BondChip, { props }).find('[data-testid="disc-bond-chip"]')

describe('BondChip', () => {
  it('renders a locked bond with its amount and currency', () => {
    const c = chip({ bond: { is_bonded: true, status: 'locked', amount: '250', currency: 'ECU' } })
    expect(c.exists()).toBe(true)
    expect(c.attributes('data-bond-status')).toBe('locked')
    expect(c.classes()).toContain('disc-bond-chip--locked')
    expect(c.text()).toContain('250 ECU')
  })

  it('says matured for a matured bond', () => {
    const c = chip({ bond: { is_bonded: true, status: 'matured', amount: '100', currency: 'ACU' } })
    expect(c.attributes('data-bond-status')).toBe('matured')
    expect(c.classes()).toContain('disc-bond-chip--matured')
  })

  it('falls back to the row currency when the bond block names none', () => {
    const c = chip({ bond: { is_bonded: true, status: 'locked', amount: '250' }, fallbackCurrency: 'ECU' })
    expect(c.text()).toContain('250 ECU')
  })

  it('renders from the row flag alone, with the generic title', () => {
    const c = chip({ bond: null, isBonded: true })
    expect(c.exists()).toBe(true)
    expect(c.attributes('data-bond-status')).toBe('locked')
    expect(c.attributes('title')).toBeTruthy()
  })

  it('renders nothing for an agent with no bond', () => {
    expect(chip({ bond: null }).exists()).toBe(false)
    expect(chip({ bond: { is_bonded: false, status: 'released' } }).exists()).toBe(false)
  })
})
