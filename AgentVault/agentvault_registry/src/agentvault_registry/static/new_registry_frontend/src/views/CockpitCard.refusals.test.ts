import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §COCKPITDESK (2026-10-15) — the Cockpit Card says why an action was refused. Revoke, Verify now, Test confirm and Deny
 * threw out of the click (nothing said, the list unchanged), a refused approval was swallowed, and a mandate's detail read
 * still in flight when another card opened put its evidence chain under that card.
 */
const h = vi.hoisted(() => ({ api: {} as Record<string, ReturnType<typeof vi.fn>> }))
vi.mock('@/services/api/liability', () => ({ liabilityApi: new Proxy({}, { get: (_t, k: string) => (h.api[k] ??= vi.fn()) }) }))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: vi.fn().mockResolvedValue([]) } }))

import CockpitCard from './CockpitCard.vue'

const refused = (detail: string) => Object.assign(new Error('Request failed with status code 403'), { response: { status: 403, data: { detail } } })
const mandate = (id: string) => ({ id, agent_did: `did:theprotocol:${id}`, status: 'signed', tier: 'standard', scope: ['teg.transfer'],
  issued_at: '2026-10-14T00:00:00Z', content_hash: 'ab'.repeat(32), resolved: { valid: true, effective_scope: ['teg.transfer'], reasons: [] } })
const challenge = { id: 'ch1', action_type: 'contract.release', action_ref: null, challenge_hash: 'cd'.repeat(32),
  expires_at: '2026-10-15T05:00:00Z', facts: { amount: 5 } }
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}
const stubs = { Icon: true, ReadFailedNotice: true }

describe('the Cockpit Card', () => {
  beforeEach(() => {
    h.api = {}
    h.api.delegatable = vi.fn().mockResolvedValue({ mode: 'enforce', delegatable: ['teg.transfer'], non_delegatable: [], presence: { totp_enrolled: true } })
    h.api.myMandates = vi.fn().mockResolvedValue({ mandates: [mandate('m1'), mandate('m2')] })
    h.api.pendingChallenges = vi.fn().mockResolvedValue({ challenges: [challenge] })
  })

  it('a refused approval says why, and the list is read again', async () => {
    h.api.approveChallenge = vi.fn().mockRejectedValue(refused('presence code did not match'))
    const w = mount(CockpitCard, { global: { stubs } })
    await flushPromises()
    await w.find('input[placeholder="TOTP"]').setValue('123456')
    const approve = w.findAll('button').find((b) => b.text() === 'Approve')!
    await approve.trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ck-confirm-error"]').text()).toBe('Not approved: presence code did not match')
    expect(h.api.pendingChallenges).toHaveBeenCalledTimes(2)
    w.unmount()
  })

  it('a refused revoke says why, where the mandates are', async () => {
    h.api.getMandate = vi.fn().mockResolvedValue({ ...mandate('m1'), evidence: [], chain_ok: true })
    h.api.revokeMandate = vi.fn().mockRejectedValue(refused('mandate is already revoked'))
    const w = mount(CockpitCard, { global: { stubs } })
    await flushPromises()
    await w.findAll('button').find((b) => b.text().includes('did:theprotocol:m1'))!.trigger('click')
    await flushPromises()
    await w.findAll('button').find((b) => b.text().includes('Revoke'))!.trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ck-mandate-error"]').text()).toBe('Not revoked: mandate is already revoked')
    w.unmount()
  })

  it("a card's detail read landing after another card opened is dropped", async () => {
    const slow = deferred<unknown>()
    h.api.getMandate = vi.fn((id: string) => id === 'm1' ? slow.promise
      : Promise.resolve({ ...mandate('m2'), evidence: [{ seq: 1, event_type: 'issued', created_at: '2026-10-14T00:00:00Z' }], chain_ok: true }))
    const w = mount(CockpitCard, { global: { stubs } })
    await flushPromises()
    const row = (id: string) => w.findAll('button').find((b) => b.text().includes(`did:theprotocol:${id}`))!
    await row('m1').trigger('click')
    await row('m2').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('1 links, intact')
    slow.resolve({ ...mandate('m1'), evidence: [], chain_ok: false, chain_break_at: 7 })
    await flushPromises()
    expect(w.text(), "m1's broken chain is never shown under m2").not.toContain('BROKEN')
    expect(w.text()).toContain('1 links, intact')
    w.unmount()
  })
})
