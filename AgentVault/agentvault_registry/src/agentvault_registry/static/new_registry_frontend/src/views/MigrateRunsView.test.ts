import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/** V0664 C4: My migrations: the workflows made from a template (provenance from the workflow's `template` block) and the certificates held. */
const h = vi.hoisted(() => ({ auth: { token: 't', agentToken: 'a', activeAgent: { did: 'did:a:me' } } as any, runs: null as any, certs: null as any }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/api/workflowTemplates', () => ({ listMyRuns: (...a: any[]) => h.runs(...a), listMyCertificates: (...a: any[]) => h.certs(...a) }))
import MigrateRunsView from './MigrateRunsView.vue'
import { normalizeRuns, normalizeCertificates } from '@/services/migrate/mine'

const HASH = 'b'.repeat(64)
const RUNS = { workflows: [
  { id: 'wf1', title: 'CRM load', status: 'running', total_budget: '5.0000000000', currency: 'ECU', created_at: '2026-11-14T10:00:00Z', template: { id: 'wt_1', version: 2, content_hash: HASH, title: 'CRM to Postgres' } },
  { id: 'wf2', title: 'by hand', status: 'draft', total_budget: '1', currency: 'ECU', created_at: '2026-11-13T10:00:00Z', template: null },
] }
const CERT = { attestation_id: 'att1', attestation_type: 'migration.certificate', target_agent_did: 'did:a:me', attestation_data: { record: 'tpm-abc', claim: { template: { name: 'crm-to-pg', version: 2, content_hash: HASH }, moved: 117, rejected: 3, verdict: 'pass' } } }
const mountIt = () => mount(MigrateRunsView, { global: { stubs: { Icon: true, MigrateTabs: true, RouterLink: { template: '<a><slot /></a>' } } } })

describe('My migrations', () => {
  beforeEach(() => {
    h.auth = { token: 't', agentToken: 'a', activeAgent: { did: 'did:a:me' } }
    h.runs = vi.fn().mockResolvedValue(normalizeRuns(RUNS))
    h.certs = vi.fn().mockResolvedValue(normalizeCertificates([CERT]))
  })
  it('lists only workflows made from a template, each with its template, version and hash', async () => {
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mr-run-wf1"]').exists()).toBe(true)
    expect(w.find('[data-testid="mr-run-wf2"]').exists()).toBe(false)
    const prov = w.find('[data-testid="mr-provenance"]').text()
    expect(prov).toContain('CRM to Postgres'); expect(prov).toContain('v2'); expect(prov).toContain(HASH.slice(0, 12))
    expect(w.find('[data-testid="mr-run-wf1"]').text()).toContain('5 ECU')
  })
  it('shows the certificate for the version the workflow was made from, and the claim in words', async () => {
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mr-run-cert"]').exists()).toBe(true)
    expect(w.find('[data-testid="mr-claim"]').text()).toBe('117 rows moved, 3 rejected, reconcile passed')
  })
  it('says so when the certificates cannot be read, when there are none, when nobody is signed in', async () => {
    h.certs = vi.fn().mockRejectedValue(new Error('x'))
    let w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mr-certs-unavailable"]').exists()).toBe(true)
    expect(w.find('[data-testid="mr-run-wf1"]').exists()).toBe(true)
    h.certs = vi.fn().mockResolvedValue([]); h.runs = vi.fn().mockResolvedValue([])
    w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mr-empty"]').exists()).toBe(true); expect(w.find('[data-testid="mr-no-certs"]').exists()).toBe(true)
    h.auth = { token: '', agentToken: '', activeAgent: null }; h.runs = vi.fn()
    w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mr-signin"]').exists()).toBe(true); expect(h.runs).not.toHaveBeenCalled()
  })
  it('shows the registry\'s sentence when the list fails', async () => {
    h.runs = vi.fn().mockRejectedValue({ response: { data: { detail: 'agent token needed' } } })
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="mr-error"]').text()).toBe('agent token needed')
  })
})
