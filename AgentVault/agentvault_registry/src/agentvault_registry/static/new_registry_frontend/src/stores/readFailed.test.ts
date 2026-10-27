import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDisputesStore } from './disputes'
import { useGovernanceStore } from './governance'
import { useForensicsStore } from './forensics'
import { useWebhookStore } from './webhooks'
import { useOrganizationStore } from './organizations'

/**
 * §FESUITE (the failing-reads census, V0569 at sbx-beta, 2026-10-04): "could not read" is not "none". With every read
 * failed, the disputes page said "No disputes filed yet", the Senate floor "No proposals found" and the stuck-funds board
 * "No stuck-funds signals detected." while the frame had each. The stores behind them now carry what failed, and the
 * pages show a read-failed notice in its place. A 404 is the server's own answer ("none here"), never a failure.
 */
const api = vi.hoisted(() => ({
  readAll: vi.fn(), getProposals: vi.fn(),
  inv: vi.fn(), ov: vi.fn(), aud: vi.fn(), fee: vi.fn(), gk: vi.fn(),
  listWebhooks: vi.fn(), listOrganizations: vi.fn(),
}))
// the organizations store reads only for a signed-in developer whose profile is known (else it waits up to 5 s)
const auth = vi.hoisted(() => ({ activeAgent: null as unknown, isAuthenticated: true, user: { email: 'm@x' } as unknown }))
vi.mock('@/services/api/disputes', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  disputesApi: { readAll: api.readAll },
}))
vi.mock('@/services', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  governanceApi: { getProposals: api.getProposals },
}))
vi.mock('@/services/api/forensics', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  forensicsApi: { exchangeInvariant: api.inv, exchangeOverview: api.ov, auditorLatest: api.aud, feeCollector: api.fee, gatewayKeeper: api.gk },
}))
// the forensics store asks for the console's frames at setup (a real read of the frame manifest): not this test's subject
vi.mock('@/composables/useAdminFrames', () => ({ useAdminFrames: () => ({ frameGet: vi.fn() }) }))
vi.mock('./ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('@/services/api/webhookService', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  webhookService: { listWebhooks: api.listWebhooks },
}))
vi.mock('@/services/api/organizationService', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  organizationService: { listOrganizations: api.listOrganizations },
}))
vi.mock('./auth', () => ({ useAuthStore: () => auth }))

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('a store says when its read failed, and a 404 is an answer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(api)) f.mockReset()
    auth.isAuthenticated = true
    auth.user = { email: 'm@x' }
  })

  it('disputes: a failed list read is a failure, a 404 is "none", a success clears it', async () => {
    const s = useDisputesStore()
    expect(s.listFailed).toBe(false)
    api.readAll.mockRejectedValueOnce(answered(502))
    await s.fetchDisputes()
    expect(s.listFailed).toBe(true)
    expect(s.listRead).toBe(false)
    expect(s.disputes).toEqual([])            // what the page must not call "none"
    api.readAll.mockRejectedValueOnce(answered(404))
    await s.fetchDisputes()
    expect(s.listFailed).toBe(false)
    expect(s.listRead).toBe(true)             // the server's own "none"
    api.readAll.mockResolvedValueOnce({ rows: [{ id: 'd1' }],
      stats: { total_disputes: 1, open_disputes: 1, resolved_disputes: 0, resolution_rate: 0, average_resolution_time: 0 } })
    await s.fetchDisputes()
    expect(s.listFailed).toBe(false)
    expect(s.disputes.map((d: { id: string }) => d.id)).toEqual(['d1'])
  })

  it('governance: a failed proposals read says so until one succeeds, and a reset forgets it', async () => {
    const s = useGovernanceStore()
    expect(s.proposalsFailed).toBe(false)
    api.getProposals.mockRejectedValueOnce(answered(502))
    await expect(s.fetchProposals(1)).rejects.toThrow()
    expect(s.proposalsFailed).toBe(true)
    api.getProposals.mockResolvedValueOnce({ proposals: [{ id: 'p1' }], total: 1 })
    await s.fetchProposals(1)
    expect(s.proposalsFailed).toBe(false)
    api.getProposals.mockRejectedValueOnce(answered(502))
    await expect(s.fetchProposals(1)).rejects.toThrow()
    s.reset()
    expect(s.proposalsFailed).toBe(false)
  })

  it('forensics: the stuck-funds scan names the sources it could not read; a 404 is "not on this frame"', async () => {
    const s = useForensicsStore()
    api.inv.mockRejectedValue(answered(502))
    api.ov.mockRejectedValue(answered(404))
    api.aud.mockResolvedValue({ frames: [] })
    api.fee.mockRejectedValue(answered(503))
    api.gk.mockResolvedValue(null)
    await s.loadStuckOverview()
    expect(s.stuckUnread).toEqual(['the AGORA invariant', 'the fee collector'])
    for (const f of [api.inv, api.ov, api.fee]) f.mockResolvedValue({})
    await s.loadStuckOverview()
    expect(s.stuckUnread).toEqual([])
  })

  it('webhooks: a failed first read says so, a success clears it, a later failure keeps the list', async () => {
    const s = useWebhookStore()
    api.listWebhooks.mockRejectedValueOnce(answered(502))
    await s.fetchWebhooks()
    expect(s.listFailed).toBe(true)
    api.listWebhooks.mockResolvedValueOnce([{ id: 'w1' }])
    await s.fetchWebhooks()
    expect(s.listFailed).toBe(false)
    api.listWebhooks.mockRejectedValueOnce(answered(502))
    await s.fetchWebhooks()
    expect(s.listFailed).toBe(false)          // it still shows what it read
    expect(s.webhooks.map((w: { id: string }) => w.id)).toEqual(['w1'])
  })

  it('organizations: "none" only after the list answered; a failed read, or one that never ran, says so', async () => {
    const s = useOrganizationStore()
    api.listOrganizations.mockRejectedValueOnce(answered(502))
    await expect(s.fetchOrganizations()).rejects.toThrow()
    expect([s.listRead, s.listFailed]).toEqual([false, true])
    api.listOrganizations.mockResolvedValueOnce([])
    await s.fetchOrganizations()
    expect([s.listRead, s.listFailed]).toEqual([true, false])   // an answer: none

    // the profile never arrives (its read failed): the store gives up after 5 s without asking
    setActivePinia(createPinia())
    auth.user = null
    vi.useFakeTimers()
    try {
      const t = useOrganizationStore()
      const p = t.fetchOrganizations()
      await vi.advanceTimersByTimeAsync(5100)
      await p
      expect(api.listOrganizations).toHaveBeenCalledTimes(2)   // the two above, none here
      expect([t.listRead, t.listFailed]).toEqual([false, true])
    } finally { vi.useRealTimers() }
  })
})
