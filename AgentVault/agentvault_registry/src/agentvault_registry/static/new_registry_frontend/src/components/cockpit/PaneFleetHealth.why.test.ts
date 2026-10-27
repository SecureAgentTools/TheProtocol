/**
 * §COCKPITDESK (2026-10-14) — Fleet health says why its score is what it is, from the registry's own deductions
 * (`score_deductions`), and says nothing where the registry predates the field.
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ body: {} as any }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn(async () => ({ data: h.body })) } }))
vi.mock('@/services/cockpit/pollJitter', () => ({ setJitteredInterval: () => 0 }))

import PaneFleetHealth from './PaneFleetHealth.vue'

const BASE = { overall_health_score: 30.54, response_time_p50: 45, response_time_p95: 755, error_rate: 1.98,
  services: { registry: { status: 'healthy', uptime: 99.99 } } }

describe('Fleet health', () => {
  it('names what took the points: the p95 and the errors, as the registry counted them', async () => {
    h.body = { ...BASE, score_deductions: { latency_p95: 65.5, errors: 3.96 } }
    const w = mount(PaneFleetHealth); await flushPromises()
    expect(w.find('[data-testid="ckd-fleet-score"]').text()).toContain('30.5')
    const why = w.find('[data-testid="ckd-fleet-why"]')
    expect(why.text()).toContain('65.5')
    expect(why.text()).toContain('755 ms p95')
    expect(why.text()).toContain('1.98% errors')
  })

  it('leaves out a deduction of nothing', async () => {
    h.body = { ...BASE, overall_health_score: 96, score_deductions: { latency_p95: 0, errors: 4 } }
    const w = mount(PaneFleetHealth); await flushPromises()
    expect(w.find('[data-testid="ckd-fleet-why"]').text()).not.toContain('p95')
  })

  it('says nothing where the registry does not send the deductions', async () => {
    h.body = { ...BASE }
    const w = mount(PaneFleetHealth); await flushPromises()
    expect(w.find('[data-testid="ckd-fleet-why"]').exists()).toBe(false)
  })
})
