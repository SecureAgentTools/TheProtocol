/**
 * §MCPTEST30 (V0641, D6-831, agentvault2-66 2026-10-25): a showcase entry this frame cannot make a paid call to (the
 * catalogue's `callable: false`: authorize would refuse its payee, or the frame has no payer and no relay) shows the
 * call's own reason and offers no run. Before, the page offered the run, and the call either met a refusal or, on a
 * frame with no payer, was relayed to another frame that paid instead. The controls: an entry that can be called runs,
 * and with the whole showcase off the page's own banner speaks (the card adds nothing).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'

vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('SBXA') }) }))
vi.mock('@/composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k) }),
}))

import ServiceCard from './ServiceCard.vue'

const WHY = 'did:theprotocol:w holds no reputation bond. Providing services here (a2a_payee) requires a bond of 250 SBXA.'
let w: VueWrapper | null = null
afterEach(() => { w?.unmount(); w = null })

function card(svc: Record<string, unknown>, unavailable: string | null = null) {
  w = mount(ServiceCard, {
    props: {
      svc: { id: 'weather', label: 'Weather', blurb: '', svg: '', accent: '59,130,246', price: '0.5', taskType: 'weather',
        display: 'weather', placeholder: 'City', hint: '', chips: [], value: 'Berlin', ...svc },
      open: true, loading: false, response: null, unavailable,
    },
  })
  return w
}

describe('an entry this frame cannot call', () => {
  it('says the call\'s own reason', () => {
    const c = card({ uncallable: WHY })
    expect(c.find('[data-testid="svc-uncallable"]').text()).toBe(WHY)
  })

  it('offers no run', () => {
    const c = card({ uncallable: WHY })
    expect(c.find('.svc-btn').attributes('disabled')).toBeDefined()
  })

  it('control: an entry that can be called runs', () => {
    const c = card({})
    expect(c.find('.svc-btn').attributes('disabled')).toBeUndefined()
    expect(c.find('[data-testid="svc-uncallable"]').exists()).toBe(false)
  })

  it('control: with the showcase off the run is off and the page banner speaks', () => {
    const c = card({ uncallable: WHY }, 'Live calls are off here')
    expect(c.find('.svc-btn').attributes('disabled')).toBeDefined()
    expect(c.find('[data-testid="svc-uncallable"]').exists()).toBe(false)
  })
})
