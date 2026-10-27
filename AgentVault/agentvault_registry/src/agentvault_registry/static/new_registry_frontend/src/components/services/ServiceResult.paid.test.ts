/**
 * §MCPTEST30 (V0641, D6-831, agentvault2-66 2026-10-25): the showcase result says SETTLED only when the call's payment
 * settled, in the unit it was charged in, and says when another frame answered.
 *
 * Measured on sbx-alpha: the card read "WeatherAgent 0.5 SBXA SETTLED Berlin" for a call its frame never paid (no payer
 * there; the agent answered 402 and the call was relayed to production EU, which paid in ECU). The label came from the
 * task's state (COMPLETED) and the unit from this frame. Pinned: SETTLED from `paid`, NOT SETTLED for a payment that
 * did not settle, DONE where no payment was involved, the charged unit, and a "via <host>" pill for a relayed answer.
 * The controls (a settled call, a failure, an older reply without the charged fields) read as before.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'

vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('SBXA') }) }))

import ServiceResult from './ServiceResult.vue'

const svc = { id: 'weather', label: 'Weather', display: 'json' }
let w: VueWrapper | null = null
afterEach(() => { w?.unmount(); w = null })

function pills(response: Record<string, unknown>): string[] {
  w = mount(ServiceResult, { props: { svc, response: { agent: 'WeatherAgent', result: {}, ...response } } })
  return w.findAll('.svc-pill').map(p => p.text().replace(/\s+/g, ' ').trim())
}

describe('the showcase result says what the payment did', () => {
  it('a completed task whose call paid nothing is DONE, not SETTLED', () => {
    const p = pills({ state: 'COMPLETED', paid: false, payment_status: 'no_payment_token', price_avt: '0.5' })
    expect(p).toContain('DONE')
    expect(p).not.toContain('SETTLED')
  })

  it('a completed task whose payment did not settle says NOT SETTLED', () => {
    const p = pills({ state: 'COMPLETED', paid: false, payment_status: 'settling', price_avt: '0.5' })
    expect(p).toContain('NOT SETTLED')
    expect(p).not.toContain('SETTLED')
  })

  it('a relayed answer names the frame that answered, in the unit it charged', () => {
    const p = pills({ state: 'COMPLETED', paid: true, payment_status: 'settled', price_avt: '0.5',
      charged_amount: '0.5', charged_currency: 'ECU', relayed_from: 'https://api.theprotocol.cloud' })
    expect(p).toContain('via api.theprotocol.cloud')
    expect(p).toContain('0.5 ECU')
    expect(p).not.toContain('0.5 SBXA')
  })

  it('control: a call that settled reads SETTLED with its charge', () => {
    const p = pills({ state: 'COMPLETED', paid: true, payment_status: 'settled', price_avt: '0.5' })
    expect(p).toContain('SETTLED')
    expect(p).toContain('0.5 SBXA')
  })

  it('control: a failure reads FAILED', () => {
    const p = pills({ error: 'Service temporarily unavailable: weather' })
    expect(p).toContain('FAILED')
  })
})
