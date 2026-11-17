import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import BondChip from './BondChip.vue'

/**
 * V0662 console polish, item 4 (order gwo_0aa7b875cbf65b6347f5f775): the card's bond chip prints its amount through the
 * app's number formatter. The registry answers a bond's amount as a decimal string ("250.000000000000000000"), and the
 * chip printed it as it came. Red on f569f6a6e: the raw string, ungrouped and with its eighteen zeros.
 */
const chip = (props: Record<string, unknown>) => mount(BondChip, { props }).find('[data-testid="disc-bond-chip"]')

describe('the bond chip in the app\'s numbers', () => {
  it('a decimal string from the registry reads as the number, without its trailing zeros', () => {
    const c = chip({ bond: { is_bonded: true, status: 'locked', amount: '250.000000000000000000', currency: 'ECU' } })
    expect(c.text()).toContain('250 ECU')
    expect(c.text()).not.toContain('250.0')
  })
  it('a large amount is grouped, on the chip and in its title, and so is the volume', () => {
    const c = chip({ bond: { is_bonded: true, status: 'locked', amount: '12345.5', currency: 'ECU' }, volume: 1234567 })
    expect(c.text()).toContain('12,345.5 ECU')
    expect(c.attributes('title')).toContain('12,345.5 ECU')
    expect(c.attributes('title')).toContain('1,234,567')
  })
})
