/** §FESUITE (2026-10-10): a send preview names what arrives in the unit it arrives in, and never invents a number. */
import { describe, expect, it } from 'vitest'
import { sendArrival } from './sendArrival'

describe('what a send preview says arrives', () => {
  it('an FX route with a quote: the estimate, in the receiver\'s currency', () => {
    expect(sendArrival({ method: 'fx', amount: '1', currency_sent: 'SBXB', currency_received: 'SBXA',
      fx_quote: { est_received: '0.980075' } })).toEqual({ amt: '0.980075', ccy: 'SBXA' })
  })
  it('an FX route without a quote: the receiver\'s currency and no number (it said ≈ 0.9950 SBXB)', () => {
    expect(sendArrival({ method: 'fx', amount: '1', currency_sent: 'SBXB', currency_received: 'SBXA', fx_quote: null }))
      .toEqual({ amt: '', ccy: 'SBXA' })
  })
  it('a local send: the full amount, in the frame\'s currency', () => {
    expect(sendArrival({ method: 'local', amount: '5', currency_sent: 'SBXB', currency_received: 'SBXB' }))
      .toEqual({ amt: '5.0000', ccy: 'SBXB' })
  })
  it('a same-currency cross-registry send: 0.5% off, in the shared currency', () => {
    expect(sendArrival({ method: '2pc', amount: '2', currency_sent: 'ECU', currency_received: 'ECU' }))
      .toEqual({ amt: '1.9900', ccy: 'ECU' })
  })
  it('no preview, no claim', () => {
    expect(sendArrival(null)).toBeNull()
    expect(sendArrival({ error: 'refused' })).toBeNull()
  })
})
