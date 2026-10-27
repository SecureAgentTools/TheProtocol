/** webhookDeliveryOutcome.test.ts — §DOCSFIX D6-786: the registry's rule for a delivery's outcome, pinned. */
import { describe, expect, it } from 'vitest'
import { deliveryOutcome } from './webhookDeliveryOutcome'

describe('deliveryOutcome', () => {
  it('a 2xx answer is a delivery', () => {
    for (const s of [200, 201, 204, 299]) expect(deliveryOutcome(s), String(s)).toBe('success')
  })
  it('any other answer is a failed attempt, a redirect included (not followed, and retried)', () => {
    for (const s of [101, 199, 300, 301, 302, 304, 307, 308, 399, 400, 404, 429, 500, 503]) {
      expect(deliveryOutcome(s), String(s)).toBe('failed')
    }
  })
  it('no answer is pending', () => {
    expect(deliveryOutcome(null)).toBe('pending')
    expect(deliveryOutcome(undefined)).toBe('pending')
  })
})
