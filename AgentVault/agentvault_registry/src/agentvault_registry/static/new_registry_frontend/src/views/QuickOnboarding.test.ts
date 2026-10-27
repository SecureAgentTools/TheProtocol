import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

/**
 * Quick onboarding (2026-10-09): the page as a person meets it, with the registry mocked.
 *   - balances are hidden on every visit and NOT read until the person asks; a reveal reads in requests of at most 50,
 *     and an entry the registry answered with an error reads "unread", never 0
 *   - a deleted agent is not listed; a suspended one is labelled and offers no reset
 *   - a reset with a wrong password is said in the dialog, which stays open; a 401 step_up_required asks for the second
 *     factor and resends with it; a success stores the new pair where the console keeps keys, and the acting agent signs
 *     in again with it
 *   - the first identity of an account that has no live agent is the wallet; a failed read is not "no agents"
 *   - the console acts as the new identity only when it acts as none
 */
const h = vi.hoisted(() => ({
  getMyAgents: vi.fn(),
  create: vi.fn(),
  reset: vi.fn(),
  balances: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  bond: vi.fn(),
  resend: vi.fn(),
  getCreds: vi.fn(),
  storeCreds: vi.fn(),
  fetchMyAgents: vi.fn(),
  ui: { showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn(), noteAgentCreated: vi.fn() },
  auth: null as any,
}))

vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  h.auth = reactive({
    activeAgent: null as null | Record<string, unknown>,
    agentToken: 'agent-jwt',
    user: { email: 'dev@example.test', is_verified: true } as Record<string, unknown>,
    authenticateAsAgent: vi.fn(async () => true),
    setActiveAgentFromToken: vi.fn(),
    refreshProfile: vi.fn(async () => true),
  })
  return { useAuthStore: () => h.auth }
})
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ fetchMyAgents: h.fetchMyAgents }) }))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: h.getMyAgents, create: h.create, resetCredentials: h.reset } }))
vi.mock('@/services/api/developers', () => ({ developerApi: { getAgentBalancesBatch: h.balances } }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: h.post, patch: h.patch } }))
vi.mock('@/services/api/reputationBond', () => ({ reputationBondApi: { getConfig: h.bond } }))
vi.mock('@/services/api/auth', () => ({ authApi: { resendVerification: h.resend } }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getCredentials: h.getCreds, storeCredentials: h.storeCreds } }))
vi.mock('@/composables/useRegistryConfig', async () => {
  const { ref, computed } = await import('vue')
  const config = ref({ registry_name: 'EU Registry', local_currency: 'ECU' })
  return { useRegistryConfig: () => ({ config: computed(() => config.value), localCurrency: computed(() => 'ECU') }) }
})
vi.mock('@/services/appLocale', () => ({ appLocale: () => 'en' }))
vi.mock('@/composables/useCockpitBus', () => ({ useCockpitBus: () => {} }))
vi.mock('@/services/api/liability', () => ({ liabilityApi: { pendingChallenges: vi.fn().mockResolvedValue({ challenges: [] }) } }))

import QuickOnboarding from './QuickOnboarding.vue'
import StepUpConfirm from '@/components/membership/StepUpConfirm.vue'
import en from '@/i18n/locales/en.json'

const MASK = '••••'
const did = (i: number) => `did:theprotocol:00000000-0000-4000-8000-${String(i).padStart(12, '0')}`
const row = (i: number, over: Record<string, unknown> = {}) => ({
  did: did(i), client_id: `agent-${String(i).padStart(16, '0')}`, status: 'active', name: `Agent ${i}`,
  created_at: '2026-10-01T12:00:00Z', card_data: { tags: [] }, liquid_balance: '12345', ...over,
})
const refused = (status: number, data: unknown) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } })
const STEP_UP = {
  error: 'step_up_required', message: 'Confirm this on your phone, or send a current authenticator code.',
  step_up: { reason: 'second factor required', challenge_id: 'lch_test', challenge_hash: 'h',
    facts: { action: 'Reset agent credentials', agent_did: did(1) }, expires_at: new Date(Date.now() + 120_000).toISOString(),
    ttl_seconds: 120, methods: ['totp'], how: null },
}

let w: VueWrapper | null = null
async function settle(n = 6) { for (let i = 0; i < n; i++) await flushPromises() }
async function mountPage() {
  w = mount(QuickOnboarding, {
    attachTo: document.body,
    global: { stubs: { teleport: true, Icon: true, RouterLink: { props: ['to'], template: '<a href="#"><slot /></a>' } } },
  })
  await settle()
  return w
}
function balanceCells() { return w!.findAll('[data-testid="qo-row-balance"]') }

beforeEach(() => {
  for (const f of [h.getMyAgents, h.create, h.reset, h.balances, h.get, h.post, h.patch, h.bond, h.resend, h.getCreds, h.storeCreds, h.fetchMyAgents]) f.mockReset()
  for (const f of Object.values(h.ui)) f.mockReset()
  h.auth.activeAgent = null
  h.auth.user = { email: 'dev@example.test', is_verified: true }
  h.auth.authenticateAsAgent.mockReset(); h.auth.authenticateAsAgent.mockResolvedValue(true)
  h.auth.setActiveAgentFromToken.mockReset()
  h.auth.refreshProfile.mockReset(); h.auth.refreshProfile.mockResolvedValue(true)
  h.bond.mockResolvedValue({ mode: 'enforce', amount: '250', currency: 'ECU', treasury_backstop: true })
  h.fetchMyAgents.mockResolvedValue(undefined)
  h.getCreds.mockReturnValue(null)
  h.patch.mockResolvedValue({ data: {} })
  h.get.mockResolvedValue({ data: { card_data: { name: 'x', humanReadableId: 'x', protocolVersion: '1.0' } } })
  h.post.mockResolvedValue({ data: { is_valid: true } })
})
afterEach(() => { w?.unmount(); w = null; document.body.innerHTML = '' })

describe('balances: hidden on every visit', () => {
  it('masked by default, no number anywhere in the cells, and not read until the person asks', async () => {
    h.getMyAgents.mockResolvedValue([row(1), row(2), row(3)])
    await mountPage()
    const cells = balanceCells()
    expect(cells).toHaveLength(3)
    for (const c of cells) {
      expect(c.attributes('data-state')).toBe('hidden')
      expect(c.text()).toContain(MASK)
      expect(c.text()).toContain('ECU')
      expect(c.text()).not.toMatch(/\d/)
      expect(c.html()).not.toMatch(/data-amount|title=/)
    }
    // the stale DB snapshot on the row (liquid_balance) is never shown either
    expect(w!.text()).not.toContain('12345')
    expect(h.balances).not.toHaveBeenCalled()
    const eye = w!.find('[data-testid="qo-eye"]')
    expect(eye.attributes('data-shown')).toBe('0')
    expect(eye.text()).toContain('Show balances')
    // the label names the action, so the button carries no aria-pressed ("Hide balances, pressed" said the opposite)
    expect(eye.attributes('aria-pressed')).toBeUndefined()
  })

  it('a reveal reads the listed agents in requests of at most 50; an error entry is unread, never 0; hiding again masks', async () => {
    const rows = Array.from({ length: 73 }, (_, i) => row(i + 1))
    h.getMyAgents.mockResolvedValue(rows)
    h.balances.mockImplementation(async (dids: string[]) => ({
      balances: Object.fromEntries(dids.map((d) => [d, d === did(7)
        ? { balance: '0', currency: 'ECU', error: 'TEG error: 502' }
        : { balance: '1000.5', currency: 'ECU' }])),
    }))
    const storageBefore = Object.keys(localStorage).sort()
    await mountPage()
    await w!.find('[data-testid="qo-eye"]').trigger('click')
    await settle()
    expect(h.balances).toHaveBeenCalledTimes(2)
    const sizes = h.balances.mock.calls.map((c) => (c[0] as string[]).length)
    expect(sizes.every((n) => n <= 50)).toBe(true)
    expect(sizes.reduce((a, b) => a + b, 0)).toBe(73)
    const cells = balanceCells()
    const byDid = (d: string) => cells.find((c) => c.element.closest('[data-did]')?.getAttribute('data-did') === d)!
    expect(byDid(did(1)).attributes('data-state')).toBe('ok')
    expect(byDid(did(1)).text()).toContain('1,000.5 ECU')
    const failed = byDid(did(7))
    expect(failed.attributes('data-state')).toBe('unread')
    expect(failed.text()).toContain('unread')
    expect(failed.text()).not.toMatch(/(^|\s)0(\s|$)/)
    // the reason is on the page, not in a hover title a keyboard or a finger cannot reach
    expect(failed.find('[data-testid="qo-row-unread-why"]').text()).toBe('TEG error: 502')
    expect(failed.find('[title]').exists()).toBe(false)
    expect(w!.find('[data-testid="qo-eye"]').attributes('data-shown')).toBe('1')
    expect(w!.find('[data-testid="qo-eye"]').text()).toContain('Hide balances')
    // hide: masked again, nothing read, no number left in the cells
    await w!.find('[data-testid="qo-eye"]').trigger('click')
    await settle()
    expect(h.balances).toHaveBeenCalledTimes(2)
    for (const c of balanceCells()) { expect(c.attributes('data-state')).toBe('hidden'); expect(c.text()).not.toMatch(/\d/) }
    // the switch lives in memory only: no storage key was written
    expect(Object.keys(localStorage).sort()).toEqual(storageBefore)
  })

  it('a request that fails makes its agents unread with the reason, and the page stays usable', async () => {
    h.getMyAgents.mockResolvedValue([row(1), row(2)])
    h.balances.mockRejectedValue(refused(503, {}))
    await mountPage()
    await w!.find('[data-testid="qo-eye"]').trigger('click')
    await settle()
    for (const c of balanceCells()) {
      expect(c.attributes('data-state')).toBe('unread')
      expect(c.find('[data-testid="qo-row-unread-why"]').text()).toBe('The registry answered 503.')
    }
  })
})

describe('the list', () => {
  it('deleted agents are not listed; a suspended one is labelled and offers no reset; a full page says it is a slice', async () => {
    const rows = [row(1), row(2, { status: 'revoked', name: 'Deleted one' }), row(3, { status: 'suspended', name: 'Held' }),
      ...Array.from({ length: 97 }, (_, i) => row(i + 10))]
    h.getMyAgents.mockResolvedValue(rows)
    await mountPage()
    expect(h.getMyAgents).toHaveBeenCalledWith({ limit: 100 })
    const listed = w!.findAll('[data-testid="qo-agent-row"]').map((r) => r.attributes('data-did'))
    expect(listed).not.toContain(did(2))
    expect(w!.text()).not.toContain('Deleted one')
    const held = w!.find(`[data-testid="qo-agent-row"][data-did="${did(3)}"]`)
    expect(held.find('[data-testid="qo-row-suspended"]').exists()).toBe(true)
    expect(held.find('[data-testid="qo-row-reset"]').exists()).toBe(false)
    expect(w!.find(`[data-testid="qo-agent-row"][data-did="${did(1)}"] [data-testid="qo-row-reset"]`).exists()).toBe(true)
    // a full page says it is a slice, with no number to contradict the count beside it
    expect(w!.find('[data-testid="qo-slice"]').text()).toContain('These are your newest agents only')
    expect(w!.find('[data-testid="qo-slice"]').text()).not.toMatch(/\d/)
    // the count is a status region, there from the start, so a search that changes the list is announced
    const count = w!.find('[data-testid="qo-agents-count"]')
    expect(count.attributes('role')).toBe('status')
    expect(count.text()).toBe('99 agents')
    // each row's buttons name their agent (100 identical "Reset credentials" buttons are a list nobody can use)
    expect(w!.find(`[data-testid="qo-agent-row"][data-did="${did(1)}"] [data-testid="qo-row-reset"]`).attributes('aria-label'))
      .toBe('Reset credentials of Agent 1')
    expect(w!.find(`[data-testid="qo-agent-row"][data-did="${did(1)}"] [data-testid="qo-row-open"]`).attributes('aria-label'))
      .toBe('Open Agent 1')
  })

  it('a failed read says so with a retry, and is not "no agents"', async () => {
    h.getMyAgents.mockRejectedValueOnce(refused(502, {})).mockResolvedValueOnce([row(1)])
    await mountPage()
    expect(w!.find('[data-testid="qo-agents-failed"]').exists()).toBe(true)
    expect(w!.find('[data-testid="qo-agents-empty"]').exists()).toBe(false)
    // no wallet guess on a failed read
    expect(w!.find('[data-testid="qo-wallet-note"]').exists()).toBe(false)
    expect((w!.find('[data-testid="qo-name"]').element as HTMLInputElement).value).toBe('')
    await w!.find('[data-testid="read-failed-retry"]').trigger('click')
    await settle()
    expect(w!.findAll('[data-testid="qo-agent-row"]')).toHaveLength(1)
  })
})

describe('reset credentials', () => {
  async function openDialog() {
    h.getMyAgents.mockResolvedValue([row(1)])
    await mountPage()
    await w!.find(`[data-testid="qo-agent-row"][data-did="${did(1)}"] [data-testid="qo-row-reset"]`).trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(true)
  }

  it('a wrong password is said in the dialog, which stays open; no global toast; the field is cleared', async () => {
    await openDialog()
    h.reset.mockRejectedValueOnce(refused(403, { detail: 'Invalid password. Credential reset requires your current account password.' }))
    await w!.find('[data-testid="qo-reset-password"]').setValue('not-my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    expect(h.reset).toHaveBeenCalledWith(did(1), { password: 'not-my-password' })
    const err = w!.find('[data-testid="qo-reset-error"]')
    expect(err.attributes('data-kind')).toBe('wrong_password')
    expect(err.text()).toContain('That password is not right.')
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(true)
    expect((w!.find('[data-testid="qo-reset-password"]').element as HTMLInputElement).value).toBe('')
    // the field is where the person acts on the answer: it holds the focus again
    expect(document.activeElement).toBe(w!.find('[data-testid="qo-reset-password"]').element)
    expect(h.storeCreds).not.toHaveBeenCalled()
  })

  it('a 401 step_up_required asks for the second factor; the code is resent with the challenge', async () => {
    await openDialog()
    h.reset.mockRejectedValueOnce(refused(401, STEP_UP))
      .mockResolvedValueOnce({ agent_did: did(1), client_id: 'agent-new-pair-0001', client_secret: 'tp_secret_new_value', registry_url: 'https://x' })
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    const step = w!.findComponent(StepUpConfirm)
    expect(step.exists()).toBe(true)
    expect(step.find('[data-testid="stepup-confirm"]').attributes('aria-label')).toBe('Confirm this reset')
    expect(step.text()).not.toMatch(/vote/i)
    // the dialog steps aside while the second factor is asked
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(false)
    await step.find('[data-testid="stepup-code"]').setValue('123456')
    await step.find('form').trigger('submit')
    await settle()
    expect(h.reset).toHaveBeenNthCalledWith(2, did(1), { password: 'my-password', totp_code: '123456', challenge_id: 'lch_test' })
    expect(w!.findComponent(StepUpConfirm).exists()).toBe(false)
    expect(w!.find('[data-testid="qo-reset-done"]').exists()).toBe(true)
  })

  it('a success stores the new pair as My Agents does, signs the acting agent in again, and shows the secret once, masked', async () => {
    h.auth.activeAgent = { did: did(1), name: 'Agent 1', owned: true }
    h.getCreds.mockReturnValue({ did: did(1), client_id: 'agent-old', client_secret: 'tp_secret_old', name: 'Agent 1', humanReadableId: 'agent-1', registry: 'EU' })
    await openDialog()
    h.reset.mockResolvedValueOnce({ agent_did: did(1), client_id: 'agent-new-pair-0001', client_secret: 'tp_secret_new_value', previous_client_id: 'agent-old', registry_url: 'https://eu.example.test' })
    // the list read after the reset answers what the registry holds now
    h.getMyAgents.mockResolvedValue([row(1, { client_id: 'agent-new-pair-0001' })])
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    expect(h.storeCreds).toHaveBeenCalledWith({
      did: did(1), client_id: 'agent-new-pair-0001', client_secret: 'tp_secret_new_value', name: 'Agent 1',
      humanReadableId: 'agent-1', registry: 'EU', registry_url: undefined,
    })
    expect(h.auth.authenticateAsAgent).toHaveBeenCalledWith(expect.objectContaining({ did: did(1), client_id: 'agent-new-pair-0001', client_secret: 'tp_secret_new_value' }))
    const done = w!.find('[data-testid="qo-reset-done"]')
    expect(done.find('[data-testid="qo-cred-client-id"]').text()).toBe('agent-new-pair-0001')
    expect(w!.html()).not.toContain('tp_secret_new_value')
    await done.find('[data-testid="qo-cred-reveal"]').trigger('click')
    expect(done.find('[data-testid="qo-cred-secret"]').text()).toBe('tp_secret_new_value')
    expect(w!.find('[data-testid="qo-reset-reauth-done"]').exists()).toBe(true)
    // the row shows the new client ID at once
    expect(w!.find(`[data-testid="qo-agent-row"][data-did="${did(1)}"] [data-testid="qo-row-client-id"]`).text()).toBe('agent-new-pair-0001')
    // Done closes, and nothing of the pair or the password stays on the page
    await w!.find('[data-testid="qo-reset-finish"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(false)
    expect(w!.html()).not.toContain('tp_secret_new_value')
    expect(w!.html()).not.toContain('my-password')
  })

  it('a suspended agent the registry refuses (400) and the rate limit (429) are said calmly in the dialog', async () => {
    await openDialog()
    h.reset.mockRejectedValueOnce(refused(400, { detail: "Cannot reset credentials for agent with status 'suspended'." }))
      .mockRejectedValueOnce(refused(429, { detail: 'Rate limit exceeded' }))
    await w!.find('[data-testid="qo-reset-password"]').setValue('pw-one')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    expect(w!.find('[data-testid="qo-reset-error"]').attributes('data-kind')).toBe('inactive')
    expect(w!.find('[data-testid="qo-reset-error"]').text()).toContain("status 'suspended'")
    // the call ended: the password is gone from the field (and from the dialog), the field holds the focus
    const pw = w!.find('[data-testid="qo-reset-password"]')
    expect((pw.element as HTMLInputElement).value).toBe('')
    expect(document.activeElement).toBe(pw.element)
    await pw.setValue('pw-two')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    expect(w!.find('[data-testid="qo-reset-error"]').attributes('data-kind')).toBe('rate_limited')
    // every attempt counts toward the registry's limit, a wrong password and a confirmation round included
    expect(w!.find('[data-testid="qo-reset-error"]').text()).toContain('three reset attempts an hour')
    expect(w!.find('[data-testid="qo-reset-error"]').text()).toContain('a wrong password or a confirmation round counts as one')
  })
})

describe('issue an identity', () => {
  const CREATED = {
    did: did(42), name: 'Wallet', client_id: 'agent-4242424242424242', client_secret: 'tp_secret_issued_once',
    initial_funding_status: 'completed', registry_url: 'https://eu.example.test', agent_card_id: 'card-42', humanReadableId: 'wallet',
  }

  it('the first identity of an account with no live agent is the wallet, and the console acts as it when it acts as none', async () => {
    h.getMyAgents.mockResolvedValue([row(5, { status: 'revoked' })])
    h.create.mockResolvedValue(CREATED)
    await mountPage()
    expect(w!.find('[data-testid="qo-wallet-note"]').exists()).toBe(true)
    expect((w!.find('[data-testid="qo-name"]').element as HTMLInputElement).value).toBe('Wallet')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(h.create).toHaveBeenCalledTimes(1)
    const [dto, opts] = h.create.mock.calls[0]
    expect(dto).toMatchObject({ name: 'Wallet', capabilities: ['wallet'] })
    expect(String(dto.description).length).toBeGreaterThanOrEqual(5)
    // the refusals the page says in its own words get no global error toast, the rate limit among them
    expect(opts.expectedStatuses).toEqual(expect.arrayContaining([400, 403, 429]))
    expect(h.patch).toHaveBeenCalledWith(`/agent-cards/${encodeURIComponent(did(42))}/listing`, { unlisted: true }, expect.anything())
    expect(h.auth.authenticateAsAgent).toHaveBeenCalledWith({ did: did(42), name: 'Wallet', client_id: CREATED.client_id, client_secret: CREATED.client_secret })
    expect(h.auth.setActiveAgentFromToken).toHaveBeenCalled()
    expect(h.ui.noteAgentCreated).toHaveBeenCalled()
    expect(h.fetchMyAgents).toHaveBeenCalled()
    const result = w!.find('[data-testid="qo-result"]')
    expect(result.find('[data-testid="qo-result-did"]').text()).toBe(did(42))
    expect(result.find('[data-testid="qo-result-issuer"]').text()).toContain('EU Registry')
    expect(result.find('[data-testid="qo-funding"]').attributes('data-kind')).toBe('credited')
    expect(result.find('[data-testid="qo-cred-client-id"]').text()).toBe(CREATED.client_id)
    // shown once, masked until revealed
    expect(w!.html()).not.toContain(CREATED.client_secret)
    await result.find('[data-testid="qo-cred-reveal"]').trigger('click')
    expect(result.find('[data-testid="qo-cred-secret"]').text()).toBe(CREATED.client_secret)
    // the card, read once and validated once; the badge only on a positive answer
    expect(h.get).toHaveBeenCalledWith(`/agent-cards/${encodeURIComponent('card-42')}`, expect.anything())
    expect(h.post).toHaveBeenCalledWith('/utils/validate-card', { card_data: expect.any(Object) }, expect.anything())
    expect(w!.find('[data-testid="qo-card-valid"]').exists()).toBe(true)
    // the "use it" command never carries the secret
    expect(w!.find('[data-testid="qo-use-snippet"]').text()).toContain('password=$CLIENT_SECRET')
    expect(w!.find('[data-testid="qo-use-snippet"]').text()).not.toContain(CREATED.client_secret)
    // acting as it already: no "Act as this agent" door
    h.auth.activeAgent = { did: did(42) }
    await settle(1)
    expect(w!.find('[data-testid="qo-act-as"]').exists()).toBe(false)
  })

  it('resetting the identity just issued: its card stops showing the dead pair and says why', async () => {
    h.getMyAgents.mockResolvedValue([])
    h.create.mockResolvedValue(CREATED)
    await mountPage()
    // from the issue on, the registry lists the new identity
    h.getMyAgents.mockResolvedValue([row(42, { did: did(42), name: 'Wallet', client_id: CREATED.client_id })])
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(w!.find('[data-testid="qo-result"] [data-testid="qo-creds"]').exists()).toBe(true)
    h.getMyAgents.mockResolvedValue([row(42, { did: did(42), name: 'Wallet', client_id: 'agent-after-reset-0042' })])
    h.reset.mockResolvedValueOnce({ agent_did: did(42), client_id: 'agent-after-reset-0042', client_secret: 'tp_secret_after_reset' })
    await w!.find(`[data-testid="qo-agent-row"][data-did="${did(42)}"] [data-testid="qo-row-reset"]`).trigger('click')
    await settle(2)
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    await w!.find('[data-testid="qo-reset-finish"]').trigger('click')
    await settle(2)
    const result = w!.find('[data-testid="qo-result"]')
    expect(result.find('[data-testid="qo-result-reset"]').text()).toContain('no longer works')
    expect(result.find('[data-testid="qo-creds"]').exists()).toBe(false)
    expect(result.find('[data-testid="qo-result-nocreds"]').exists()).toBe(false)
    expect(w!.html()).not.toContain(CREATED.client_secret)
    expect(w!.find('[data-testid="qo-use-snippet"]').text()).toContain('username=agent-after-reset-0042')
  })

  it('an account whose agents could not be read gets no wallet guess', async () => {
    h.getMyAgents.mockRejectedValue(refused(503, {}))
    h.create.mockResolvedValue({ ...CREATED, name: 'Helper', humanReadableId: 'helper' })
    await mountPage()
    await w!.find('[data-testid="qo-name"]').setValue('Helper')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(h.create.mock.calls[0][0]).toMatchObject({ name: 'Helper', capabilities: [] })
    expect(h.patch).not.toHaveBeenCalled()
  })

  it('a console that acts as another agent keeps it; the page offers "Act as this agent"', async () => {
    h.auth.activeAgent = { did: did(9), name: 'Agent 9' }
    h.getMyAgents.mockResolvedValue([row(9)])
    h.create.mockResolvedValue({ ...CREATED, name: 'Second', humanReadableId: 'second' })
    await mountPage()
    await w!.find('[data-testid="qo-name"]').setValue('Second')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(h.create.mock.calls[0][0]).toMatchObject({ capabilities: [] })
    expect(h.auth.authenticateAsAgent).not.toHaveBeenCalled()
    const act = w!.find('[data-testid="qo-act-as"]')
    expect(act.exists()).toBe(true)
    await act.trigger('click')
    await settle()
    expect(h.auth.authenticateAsAgent).toHaveBeenCalledWith(expect.objectContaining({ did: did(42) }))
    expect(h.ui.showSuccess).toHaveBeenCalled()
  })

  it('a name too short is said inline and nothing is sent', async () => {
    h.getMyAgents.mockResolvedValue([row(1)])
    await mountPage()
    await w!.find('[data-testid="qo-name"]').setValue(' x ')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle(2)
    expect(w!.find('[data-testid="qo-name-msg"]').text()).toContain('at least 2 characters')
    expect(h.create).not.toHaveBeenCalled()
  })

  it('an unverified developer sees the notice and the resend action, never the raw refusal', async () => {
    h.getMyAgents.mockResolvedValue([row(1)])
    h.create.mockRejectedValue(refused(403, { detail: 'Only verified developers can request bootstrap tokens' }))
    await mountPage()
    await w!.find('[data-testid="qo-name"]').setValue('Helper')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(w!.find('[data-testid="qo-unverified"]').exists()).toBe(true)
    expect(w!.find('[data-testid="qo-issue-error"]').exists()).toBe(false)
    expect(w!.text()).not.toContain('Only verified developers can request bootstrap tokens')
    expect(w!.find('[data-testid="qo-issue-btn"]').attributes('disabled')).toBeDefined()
    h.resend.mockResolvedValue(undefined)
    await w!.find('[data-testid="qo-resend"]').trigger('click')
    await settle(2)
    expect(h.resend).toHaveBeenCalledWith('dev@example.test')
  })

  it('control: a profile that says "not verified" shows the notice before anything is sent', async () => {
    h.auth.user = { email: 'dev@example.test', is_verified: false }
    h.getMyAgents.mockResolvedValue([])
    await mountPage()
    expect(w!.find('[data-testid="qo-unverified"]').exists()).toBe(true)
    expect(w!.find('[data-testid="qo-issue-btn"]').attributes('disabled')).toBeDefined()
  })

  it('a refused card shows the registry\'s own sentence', async () => {
    h.getMyAgents.mockResolvedValue([row(1)])
    h.create.mockRejectedValue(refused(400, { detail: "Invalid agent card: 'description' must be at least 5 characters" }))
    await mountPage()
    await w!.find('[data-testid="qo-name"]').setValue('Helper')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(w!.find('[data-testid="qo-issue-error"]').text()).toContain("Invalid agent card: 'description' must be at least 5 characters")
  })

  it('a skipped validation is no badge', async () => {
    h.getMyAgents.mockResolvedValue([])
    h.create.mockResolvedValue(CREATED)
    h.post.mockResolvedValue({ data: { is_valid: true, detail: 'Validation skipped: Core library not available.' } })
    await mountPage()
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(w!.find('[data-testid="qo-card"]').attributes('data-state')).toBe('ready')
    expect(w!.find('[data-testid="qo-card-valid"]').exists()).toBe(false)
  })
})

describe('fixes after review (2026-10-09)', () => {
  const CREATED = {
    did: did(42), name: 'Wallet', client_id: 'agent-4242424242424242', client_secret: 'tp_secret_issued_once',
    initial_funding_status: 'completed', registry_url: 'https://eu.example.test', agent_card_id: 'card-42', humanReadableId: 'wallet',
  }
  async function issued(over: Record<string, unknown> = {}) {
    h.getMyAgents.mockResolvedValue([])
    h.create.mockResolvedValue({ ...CREATED, ...over })
    await mountPage()
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    return w!.find('[data-testid="qo-result"]')
  }

  it('a partial or deferred starting balance is said as it is: no "pending", no "shortly", no spinner', async () => {
    let result = await issued({ initial_funding_status: 'partial' })
    let funding = result.find('[data-testid="qo-funding"]')
    expect(funding.attributes('data-kind')).toBe('partial')
    expect(funding.text()).toBe('Part of its starting balance was credited; the rest could not be.')
    expect(funding.text()).not.toMatch(/pending|shortly|arrives/i)
    w!.unmount(); w = null
    result = await issued({ initial_funding_status: 'deferred' })
    funding = result.find('[data-testid="qo-funding"]')
    expect(funding.attributes('data-kind')).toBe('deferred')
    expect(funding.text()).toBe("No starting balance was credited: this registry's treasury is below its floor.")
    w!.unmount(); w = null
    result = await issued({ initial_funding_status: 'failed' })
    expect(result.find('[data-testid="qo-funding"]').text()).toBe('Its starting balance could not be credited.')
  })

  it('an account whose newest 100 rows are all deleted is not "no agents": no wallet guess', async () => {
    const rows = Array.from({ length: 100 }, (_, i) => row(i + 1, { status: 'revoked' }))
    h.getMyAgents.mockResolvedValue(rows)
    h.create.mockResolvedValue({ ...CREATED, name: 'Helper', humanReadableId: 'helper' })
    await mountPage()
    expect(w!.find('[data-testid="qo-wallet-note"]').exists()).toBe(false)
    expect((w!.find('[data-testid="qo-name"]').element as HTMLInputElement).value).toBe('')
    await w!.find('[data-testid="qo-name"]').setValue('Helper')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(h.create.mock.calls[0][0]).toMatchObject({ name: 'Helper', capabilities: [] })
    expect(h.patch).not.toHaveBeenCalled()
  })

  it('an issue pressed before the first read answered waits for it, so a new account still gets its wallet', async () => {
    let answer: (v: unknown) => void = () => {}
    h.getMyAgents.mockReturnValueOnce(new Promise((r) => { answer = r }))
    h.create.mockResolvedValue({ ...CREATED, name: 'Quick', humanReadableId: 'quick' })
    w = mount(QuickOnboarding, {
      attachTo: document.body,
      global: { stubs: { teleport: true, Icon: true, RouterLink: { props: ['to'], template: '<a href="#"><slot /></a>' } } },
    })
    await flushPromises()
    await w.find('[data-testid="qo-name"]').setValue('Quick')
    await w.find('[data-testid="qo-issue"]').trigger('submit')
    await flushPromises()
    expect(h.create).not.toHaveBeenCalled()
    expect(w.find('[data-testid="qo-issue-btn"]').attributes('disabled')).toBeDefined()
    answer([])
    await settle()
    expect(h.create).toHaveBeenCalledTimes(1)
    expect(h.create.mock.calls[0][0]).toMatchObject({ name: 'Quick', capabilities: ['wallet'] })
  })

  it('"I have confirmed it": a read that failed says so and keeps the notice; a read that says confirmed clears it', async () => {
    h.getMyAgents.mockResolvedValue([row(1)])
    h.create.mockRejectedValue(refused(403, { detail: 'Only verified developers can request bootstrap tokens' }))
    await mountPage()
    await w!.find('[data-testid="qo-name"]').setValue('Helper')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    expect(w!.find('[data-testid="qo-unverified"]').exists()).toBe(true)
    // the registry could not be asked: the cached profile is not its answer
    h.auth.refreshProfile.mockResolvedValueOnce(false)
    await w!.find('[data-testid="qo-recheck"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-recheck-failed"]').text()).toContain('could not be asked')
    expect(w!.find('[data-testid="qo-recheck-still"]').exists()).toBe(false)
    expect(w!.find('[data-testid="qo-unverified"]').exists()).toBe(true)
    // the registry answers "not confirmed"
    h.auth.refreshProfile.mockImplementationOnce(async () => { h.auth.user = { email: 'dev@example.test', is_verified: false }; return true })
    await w!.find('[data-testid="qo-recheck"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-recheck-still"]').exists()).toBe(true)
    // the registry answers "confirmed": the notice goes and the button works again
    h.auth.refreshProfile.mockImplementationOnce(async () => { h.auth.user = { email: 'dev@example.test', is_verified: true }; return true })
    await w!.find('[data-testid="qo-recheck"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-unverified"]').exists()).toBe(false)
    expect(w!.find('[data-testid="qo-issue-btn"]').attributes('disabled')).toBeUndefined()
  })

  it('"Send the email again" reads the answer: an account already verified is re-read, any other answer is said conditionally', async () => {
    h.auth.user = { email: 'dev@example.test', is_verified: false }
    h.getMyAgents.mockResolvedValue([])
    await mountPage()
    h.resend.mockResolvedValueOnce({ message: 'If that email is registered and unverified, a new verification email has been sent.' })
    await w!.find('[data-testid="qo-resend"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-resend-sent"]').text()).toContain('If your email is still unconfirmed')
    h.resend.mockResolvedValueOnce({ message: 'This account is already verified. Please log in.' })
    h.auth.refreshProfile.mockImplementationOnce(async () => { h.auth.user = { email: 'dev@example.test', is_verified: true }; return true })
    await w!.find('[data-testid="qo-resend"]').trigger('click')
    await settle(3)
    expect(h.auth.refreshProfile).toHaveBeenCalled()
    expect(w!.find('[data-testid="qo-unverified"]').exists()).toBe(false)
  })

  it('"Act as this agent" still works after the identity just issued was reset: it takes the pair the reset stored', async () => {
    // the browser's credential store, as the console keeps it: what the reset writes is what the page reads back
    const kept: Record<string, Record<string, unknown>> = {}
    h.storeCreds.mockImplementation((c: Record<string, unknown>) => { kept[String(c.did)] = c })
    h.getCreds.mockImplementation((d: string) => kept[d] ?? null)
    h.auth.activeAgent = { did: did(9), name: 'Agent 9' }
    h.getMyAgents.mockResolvedValue([row(9)])
    h.create.mockResolvedValue({ ...CREATED, name: 'Second', humanReadableId: 'second' })
    await mountPage()
    // from the issue on, the registry lists the new identity
    h.getMyAgents.mockResolvedValue([row(9), row(42, { name: 'Second', client_id: CREATED.client_id })])
    await w!.find('[data-testid="qo-name"]').setValue('Second')
    await w!.find('[data-testid="qo-issue"]').trigger('submit')
    await settle()
    h.getMyAgents.mockResolvedValue([row(9), row(42, { name: 'Second', client_id: 'agent-after-reset-0042' })])
    h.reset.mockResolvedValueOnce({ agent_did: did(42), client_id: 'agent-after-reset-0042', client_secret: 'tp_secret_after_reset' })
    await w!.find(`[data-testid="qo-agent-row"][data-did="${did(42)}"] [data-testid="qo-row-reset"]`).trigger('click')
    await settle(2)
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    await w!.find('[data-testid="qo-reset-finish"]').trigger('click')
    await settle(2)
    // the card no longer holds a secret, but the button is not dead: the reset stored the new pair
    expect(w!.find('[data-testid="qo-result-reset"]').exists()).toBe(true)
    const act = w!.find('[data-testid="qo-act-as"]')
    expect(act.exists()).toBe(true)
    expect(act.attributes('disabled')).toBeUndefined()
    await act.trigger('click')
    await settle()
    expect(h.auth.authenticateAsAgent).toHaveBeenCalledWith(expect.objectContaining({
      did: did(42), client_id: 'agent-after-reset-0042', client_secret: 'tp_secret_after_reset' }))
  })
})

describe('the reset dialog keeps a pair shown once', () => {
  async function openDialog() {
    h.getMyAgents.mockResolvedValue([row(1)])
    await mountPage()
    await w!.find(`[data-testid="qo-agent-row"][data-did="${did(1)}"] [data-testid="qo-row-reset"]`).trigger('click')
    await settle(2)
  }
  const esc = () => w!.find('.qo-dlg-overlay').trigger('keydown', { key: 'Escape' })

  it('Esc closes the dialog while it asks, and the password goes with it', async () => {
    await openDialog()
    await w!.find('[data-testid="qo-reset-password"]').setValue('typed-but-not-sent')
    await esc()
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(false)
    expect(w!.html()).not.toContain('typed-but-not-sent')
    expect(h.reset).not.toHaveBeenCalled()
  })

  it('once the new pair is shown, Esc and a click beside it do not close it; focus lands on the sentence that says so', async () => {
    await openDialog()
    h.reset.mockResolvedValueOnce({ agent_did: did(1), client_id: 'agent-new-pair-0001', client_secret: 'tp_secret_new_value' })
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    const ok = w!.find('[data-testid="qo-reset-ok"]')
    expect(ok.exists()).toBe(true)
    expect(document.activeElement).toBe(ok.element)
    await esc()
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-done"]').exists()).toBe(true)
    await w!.find('.qo-dlg-overlay').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-done"]').exists()).toBe(true)
    expect(document.activeElement).toBe(w!.find('[data-testid="qo-reset-ok"]').element)
    // the dialog is named by its title AND the agent it resets
    const dlg = w!.find('[data-testid="qo-reset-dialog"]')
    const ids = String(dlg.attributes('aria-labelledby')).split(' ')
    expect(ids).toHaveLength(2)
    const named = ids.map((id) => document.getElementById(id)?.textContent || '').join(' ')
    expect(named).toContain('Agent 1')
    // the name and the DID are apart in the text a reader hears, not only on screen
    expect(named).toMatch(/Agent 1, did:theprotocol:/)
    // Done still closes
    await w!.find('[data-testid="qo-reset-finish"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(false)
  })

  it('closing gives the focus back to the row button that opened the dialog', async () => {
    h.getMyAgents.mockResolvedValue([row(1)])
    await mountPage()
    const opener = w!.find(`[data-testid="qo-agent-row"][data-did="${did(1)}"] [data-testid="qo-row-reset"]`)
    ;(opener.element as HTMLElement).focus()
    await opener.trigger('click')
    await settle(2)
    expect(document.activeElement).toBe(w!.find('[data-testid="qo-reset-password"]').element)
    await w!.find('[data-testid="qo-reset-cancel"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(opener.element)
  })

  it('Done closes at once while the acting agent signs in again with the new pair', async () => {
    h.auth.activeAgent = { did: did(1), name: 'Agent 1', owned: true }
    let signedIn: (v: boolean) => void = () => {}
    h.auth.authenticateAsAgent.mockReturnValueOnce(new Promise<boolean>((r) => { signedIn = r }))
    await openDialog()
    h.reset.mockResolvedValueOnce({ agent_did: did(1), client_id: 'agent-new-pair-0001', client_secret: 'tp_secret_new_value' })
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    expect(w!.find('[data-testid="qo-reset-reauth-busy"]').exists()).toBe(true)
    await w!.find('[data-testid="qo-reset-finish"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(false)
    // the sign-in that finishes later answers into nothing (no dialog reopens, nothing throws)
    signedIn(true)
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-dialog"]').exists()).toBe(false)
  })

  it('a refused authenticator code is said as a refused code, never as the registry\'s "challenge is pending"', async () => {
    await openDialog()
    const again = { ...STEP_UP, step_up: { ...STEP_UP.step_up, reason: 'challenge is pending', challenge_id: 'lch_test2' } }
    h.reset.mockRejectedValueOnce(refused(401, STEP_UP)).mockRejectedValueOnce(refused(401, again))
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    const step = w!.findComponent(StepUpConfirm)
    await step.find('[data-testid="stepup-code"]').setValue('000000')
    await step.find('form').trigger('submit')
    await settle()
    const err = w!.findComponent(StepUpConfirm).find('[data-testid="stepup-error"]')
    expect(err.text()).toBe('That code was not accepted. Check the code in your authenticator app and try again.')
    expect(err.text()).not.toContain('pending')
    // the next code goes with the NEW challenge
    h.reset.mockResolvedValueOnce({ agent_did: did(1), client_id: 'agent-new-pair-0001', client_secret: 'tp_secret_new_value' })
    await w!.findComponent(StepUpConfirm).find('[data-testid="stepup-code"]').setValue('123456')
    await w!.findComponent(StepUpConfirm).find('form').trigger('submit')
    await settle()
    expect(h.reset).toHaveBeenLastCalledWith(did(1), { password: 'my-password', totp_code: '123456', challenge_id: 'lch_test2' })
  })

  it('closing the confirmation returns to the dialog, which says nothing changed and keeps no password', async () => {
    await openDialog()
    h.reset.mockRejectedValueOnce(refused(401, STEP_UP))
    await w!.find('[data-testid="qo-reset-password"]').setValue('my-password')
    await w!.find('[data-testid="qo-reset-submit"]').trigger('click')
    await settle()
    await w!.findComponent(StepUpConfirm).find('[data-testid="stepup-cancel"]').trigger('click')
    await settle(2)
    expect(w!.find('[data-testid="qo-reset-error"]').text()).toContain('Not confirmed, so nothing changed.')
    expect((w!.find('[data-testid="qo-reset-password"]').element as HTMLInputElement).value).toBe('')
  })
})

describe('the "i"', () => {
  it('opens the explainer; the Discover line follows the bond the registry asks', async () => {
    h.getMyAgents.mockResolvedValue([])
    await mountPage()
    const toggle = w!.find('[data-testid="qo-info-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.attributes('aria-controls')).toBe('qo-explainer')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    const discover = w!.find('[data-testid="qo-explainer-discover"]')
    expect(discover.attributes('data-bond')).toBe('read')
    expect(discover.text()).toContain('reputation bond of 250 ECU')
  })

  it('an unread bond rule is a neutral sentence, never a claim', async () => {
    h.getMyAgents.mockResolvedValue([])
    h.bond.mockRejectedValue(refused(502, {}))
    await mountPage()
    const discover = w!.find('[data-testid="qo-explainer-discover"]')
    expect(discover.attributes('data-bond')).toBe('failed')
    expect(discover.text()).toContain('could not be read just now')
    expect(discover.text()).not.toMatch(/250|no reputation bond/)
  })
})

describe('the words', () => {
  it('every quickOnboarding key the page asks for is in en.json (a key only in a fallback is a translation nobody can find)', () => {
    const sources = import.meta.glob(['./QuickOnboarding.vue', '../components/quickOnboarding/*.vue'],
      { query: '?raw', import: 'default', eager: true }) as Record<string, string>
    expect(Object.keys(sources).length).toBe(4)
    const asked = new Set<string>()
    for (const src of Object.values(sources)) {
      for (const m of src.matchAll(/\btp?\(\s*['"](quickOnboarding\.[\w.]+)['"]/g)) asked.add(m[1])
    }
    expect(asked.size).toBeGreaterThan(100)
    const resolve = (key: string) => key.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), en)
    const missing = [...asked].filter((k) => typeof resolve(k) !== 'string')
    expect(missing).toEqual([])
  })

  it('the page\'s English carries no token, staking, reward, earn, yield or invest vocabulary, and no em dash', () => {
    const words: string[] = []
    const walk = (v: unknown) => { if (typeof v === 'string') words.push(v); else if (v && typeof v === 'object') Object.values(v).forEach(walk) }
    walk((en as Record<string, unknown>).quickOnboarding)
    expect(words.length).toBeGreaterThan(100)
    for (const s of words) {
      expect(s).not.toMatch(/\b(tokens?|staking|stakes?|staked|rewards?|earn(s|ed|ing|ings)?|yields?|invest(s|ed|ing|ment|ments)?)\b/i)
      expect(s).not.toMatch(/[—–]/)
    }
  })
})
