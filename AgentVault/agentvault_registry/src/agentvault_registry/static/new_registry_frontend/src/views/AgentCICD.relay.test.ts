/**
 * §FESUITE (2026-10-09): the CI/CD page's relay check said one sentence for every answer that was not a status: "No relay
 * answered for this agent. Only an agent deployed behind the relay reports one." Right for the registry's 404 "No relay
 * configured", and said just the same over a configured relay that did not answer (502), over an address the registry
 * refuses to call (422) and over a read that failed (a 5xx, no answer at all). A refresh that failed made the card vanish
 * without a word, and a refused start/stop/restart read "Failed" (the error body carries `detail`, never `error`).
 * The page, the registry's answers given per test through `fetch` (the relay routes are read with fetch, not the client).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  listPipelines: vi.fn(), listVersions: vi.fn(), listDeployments: vi.fn(), getDeploymentLogs: vi.fn(), listTemplates: vi.fn(),
}))
vi.mock('@/services/api/cicdService', () => ({ cicdService: h }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }) }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { did: 'did:theprotocol:mine' }, query: {} }),
  useRouter: () => ({ push: vi.fn(async () => {}) }),
}))
vi.mock('@/services/api/client', () => ({
  apiClient: { get: vi.fn(async () => ({ data: { name: 'My Agent', creator_developer_id: 7 } })), post: vi.fn() },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: false, user: { id: 7 } }) }))
vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => 'tok' } }))
vi.mock('@/services/api/cicdAdmin', () => ({ cicdAdminService: {} }))

import AgentCICD from './AgentCICD.vue'

const stubs = { PipelineBuilder: true, CreateVersionModal: true, DeploymentModal: true, DeploymentLogsModal: true, ConfirmActionModal: true }
const NONE = 'No relay answered for this agent. Only an agent deployed behind the relay reports one.'
const STATUS = { container_status: 'running', healthy: true, relay_version: '1.2', uptime_seconds: 90, restart_count: 0, pending_webhooks: 0 }

/** a registry answer as fetch gives it: a status and a JSON body (RFC 7807 errors carry `detail`) */
const answer = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
const fetchMock = vi.fn()

async function deploymentsTab() {
  const w = mount(AgentCICD, { global: { stubs } })
  for (let i = 0; i < 3; i++) await flushPromises()
  await w.find('[data-tab="deployments"]').trigger('click')
  await flushPromises()
  return w
}
async function check(w: any) {
  await w.find('[data-testid="cicd-relay-check"]').trigger('click')
  for (let i = 0; i < 3; i++) await flushPromises()
}
const relayCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).includes('/relay/status')).length

describe('the CI/CD page says what the relay read answered', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(h)) { f.mockReset(); f.mockResolvedValue([]) }
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it('says "no relay" only for the registry\'s own "No relay configured" (404)', async () => {
    fetchMock.mockImplementation(() => answer(404, { detail: 'No relay configured for this agent' }))
    const w = await deploymentsTab()
    await check(w)
    // the one answer the old page already said rightly (its test id kept): a guard, not a regression test
    expect(w.find('[data-testid="cicd-relay-none"]').text()).toBe(NONE)
    expect(w.find('[data-read-failed]').exists()).toBe(false)
  })

  it('names a configured relay that did not answer (502) with the registry\'s words, never as "no relay"', async () => {
    fetchMock.mockImplementation(() => answer(502, { detail: "The agent's address answered, but not as a relay (HTTP 404)" }))
    const w = await deploymentsTab()
    await check(w)
    expect(w.text()).not.toContain(NONE)
    const said = w.find('[data-relay-outcome="silent"]')
    expect(said.exists(), 'a 502 drew the "no relay" sentence').toBe(true)
    expect(said.text()).toContain("The agent's address answered, but not as a relay (HTTP 404)")
  })

  it('names an address the registry refuses to call (422) with its reason', async () => {
    fetchMock.mockImplementation(() => answer(422, { detail: 'Agent endpoint must be https (card declares http)' }))
    const w = await deploymentsTab()
    await check(w)
    expect(w.text()).not.toContain(NONE)
    expect(w.find('[data-relay-outcome="refused"]').text()).toContain('Agent endpoint must be https (card declares http)')
  })

  it('says a failed read failed (a 5xx, another 404, no answer), and Try again reads again', async () => {
    fetchMock.mockImplementationOnce(() => answer(500, { detail: 'Internal server error' }))
    const w = await deploymentsTab()
    await check(w)
    expect(w.text()).not.toContain(NONE)
    expect(w.find('[data-testid="cicd-relay-failed"]').text()).toContain('HTTP 500')

    // an agent the registry cannot find is not an agent with no relay
    fetchMock.mockImplementationOnce(() => answer(404, { detail: 'Agent did:theprotocol:mine not found' }))
    await w.find('[data-testid="cicd-relay-failed"] [data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(w.text()).not.toContain(NONE)
    expect(w.find('[data-testid="cicd-relay-failed"]').text()).toContain('HTTP 404')

    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
    await w.find('[data-testid="cicd-relay-failed"] [data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(w.find('[data-testid="cicd-relay-failed"]').text()).toContain('could not be read')

    fetchMock.mockImplementationOnce(() => answer(200, STATUS))
    await w.find('[data-testid="cicd-relay-failed"] [data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(w.find('.relay-card').exists(), 'Try again read the status').toBe(true)
    expect(w.find('[data-testid="cicd-relay-failed"]').exists()).toBe(false)
  })

  it('keeps the card when a refresh reads no status, and says so (it vanished without a word)', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementationOnce(() => answer(200, STATUS))
    const w = await deploymentsTab()
    await check(w)
    expect(w.find('.relay-card').exists()).toBe(true)
    fetchMock.mockImplementation(() => answer(502, { detail: "The agent's relay did not answer" }))
    await vi.advanceTimersByTimeAsync(15_000)
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(relayCalls(), 'the 15 s refresh asked again').toBe(2)
    expect(w.find('.relay-card').exists(), 'a failed refresh dropped the card').toBe(true)
    expect(w.find('[data-testid="cicd-relay-refresh-failed"]').text()).toContain("The agent's relay did not answer")
    w.unmount()
  })

  it('a refused start, stop or restart says the registry\'s reason, not "Failed"', async () => {
    fetchMock.mockImplementationOnce(() => answer(200, STATUS))
    const w = await deploymentsTab()
    await check(w)
    fetchMock.mockImplementationOnce(() => answer(502, { detail: "The agent's relay did not answer" }))
    await w.find('.relay-btn-restart').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    const msg = w.find('.relay-message').text()
    expect(msg).not.toBe('Failed')
    expect(msg).toContain("The agent's relay did not answer")
  })

  it('asks nothing after the page is gone (a refresh an action scheduled)', async () => {
    vi.useFakeTimers()
    fetchMock.mockImplementationOnce(() => answer(200, STATUS))
    const w = await deploymentsTab()
    await check(w)
    fetchMock.mockImplementation(() => answer(200, { success: true }))
    await w.find('.relay-btn-restart').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    const before = relayCalls()
    w.unmount()
    await vi.advanceTimersByTimeAsync(20_000)
    expect(relayCalls(), 'a status read after the page was left').toBe(before)
  })
})
