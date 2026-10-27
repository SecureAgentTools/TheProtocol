/**
 * The Emission policy page (agentvault2-69, 2026-10-25; his word "i really need it visualized"): it draws the read the
 * way it is meant to be read. A store count that was not read says so and is never drawn as 0; a lost event is red on
 * the side that loses it; a finding chip narrows the matrix and says what the finding means; a peer that could not be
 * read says why; a failed read says it failed, never an empty table.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ effective: vi.fn() }))
vi.mock('@/services/api/emissionPolicy', () => ({ emissionPolicyApi: { effective: (...a: unknown[]) => h.effective(...a) } }))

import AdminEmissionPolicy from './AdminEmissionPolicy.vue'

const VIEW = {
  generated_at: '2026-10-25T18:10:00Z',
  modes: {
    registry: { mode: 'shadow', no_row: 'allowed, counted and logged as a refusal enforce would make', policy_table: { rows: 3, this_worker_cached: 3, this_worker_loaded_at: '2026-10-25T18:09:41Z', this_worker_load_error: null }, set_by: 'EVENT_EMITTER_POLICY_MODE' },
    teg: { mode: 'fail-closed', no_row: 'refused', always_allowed: ['LedgerBalanceChanged'], derived: 'from the TEG rules applied to these rows' },
    projection: { balance_types: ['LedgerBalanceChanged', 'TokensTransferred'], skipped: ['A2APaymentAuthorized'] },
  },
  catalog: { registry: 3, teg: 1 },
  store_read: 'ok',
  shadow_read: 'ok',
  matrix: [
    { event_type: 'TokensTransferred', row: { emit_from_registry: true, emit_from_teg: false, skip_in_projection: false, description: 'a transfer', updated_at: null }, emitted_by: ['registry', 'teg'], registry: 'allow', teg: 'refuse', projection: 'balance', balance_moving: true, store_count: 226316, shadow_would_refuse: 0, findings: [] },
    { event_type: 'NegativeEscrowLockClamped', row: null, emitted_by: ['teg'], registry: 'no-row-shadow', teg: 'no-row-refused', projection: 'audit', balance_moving: false, store_count: null, shadow_would_refuse: null, findings: ['teg-emits-refused'] },
    { event_type: 'AgentSpawned', row: null, emitted_by: ['registry'], registry: 'no-row-shadow', teg: 'no-row-refused', projection: 'audit', balance_moving: false, store_count: 12, shadow_would_refuse: 3, findings: ['emitted-without-row', 'shadow-would-refuse'] },
  ],
  summary: {
    types: 3, rows: 1,
    findings: { 'teg-emits-refused': 1, 'emitted-without-row': 1, 'shadow-would-refuse': 1 },
    finding_text: { 'teg-emits-refused': 'the TEG emits it, its gate refuses it, and the registry does not record it: the event is lost' },
  },
  drift: [
    { peer: 'sbx-beta', peer_type: 'frame', read: 'ok', only_here: ['ExampleOnlyHere'], only_there: [], differing: [{ event_type: 'ExampleType', here: { emit_from_registry: true, emit_from_teg: false, skip_in_projection: false }, there: { emit_from_registry: true, emit_from_teg: true, skip_in_projection: false } }] },
    { peer: 'sbxbetaop', peer_type: 'cloud_operator', read: 'ConnectTimeout: the peer did not answer' },
  ],
}

async function page() {
  const w = mount(AdminEmissionPolicy, { global: { stubs: { Icon: true, RouterLink: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
const rowOf = (w: ReturnType<typeof mount>, et: string) => w.find(`[data-testid="ep-row-${et}"]`)

describe('the Emission policy page', () => {
  beforeEach(() => { h.effective.mockReset() })

  it('draws the three sides, the strip and one row per type, worst first', async () => {
    h.effective.mockResolvedValue(VIEW)
    const w = await page()
    expect(h.effective).toHaveBeenCalledWith(true)
    expect(w.find('[data-testid="ep-mode-registry"]').attributes('data-mode')).toBe('shadow')
    expect(w.find('[data-testid="ep-mode-teg"]').text()).toContain('LedgerBalanceChanged')
    expect(w.find('[data-testid="ep-mode-projection"]').text()).toContain('2 types move balances')
    const order = w.findAll('[data-testid^="ep-row-"]').map((r) => r.attributes('data-testid'))
    expect(order).toEqual(['ep-row-NegativeEscrowLockClamped', 'ep-row-AgentSpawned', 'ep-row-TokensTransferred'])
  })

  it('a store count that was not read says so, and is never drawn as 0', async () => {
    h.effective.mockResolvedValue(VIEW)
    const w = await page()
    const store = rowOf(w, 'NegativeEscrowLockClamped').find('[data-testid="ep-cell-store"]')
    expect(store.text()).toContain('not read')
    expect(store.text()).not.toMatch(/\b0\b/)
    expect(store.attributes('data-read')).toBe('no')
    expect(rowOf(w, 'TokensTransferred').find('[data-testid="ep-cell-store"]').text()).toContain('226,316')
  })

  it('a lost event is red on the side that loses it; a balance type reads as moving balances', async () => {
    h.effective.mockResolvedValue(VIEW)
    const w = await page()
    const lost = rowOf(w, 'NegativeEscrowLockClamped')
    expect(lost.attributes('data-sev')).toBe('bad')
    expect(lost.find('[data-testid="ep-cell-teg"]').attributes('data-tone')).toBe('bad')
    expect(lost.find('[data-testid="ep-cell-teg"]').text()).toBe('refused: lost')
    expect(rowOf(w, 'TokensTransferred').find('[data-testid="ep-cell-projection"]').attributes('data-tone')).toBe('info')
    expect(rowOf(w, 'AgentSpawned').find('[data-testid="ep-cell-shadow"]').attributes('data-hot')).toBe('true')
  })

  it('a finding chip narrows the matrix and says what the finding means', async () => {
    h.effective.mockResolvedValue(VIEW)
    const w = await page()
    await w.find('[data-testid="ep-filter-teg-emits-refused"]').trigger('click')
    expect(w.findAll('[data-testid^="ep-row-"]').map((r) => r.attributes('data-testid'))).toEqual(['ep-row-NegativeEscrowLockClamped'])
    expect(w.find('[data-testid="ep-finding-text"]').text()).toContain('the event is lost')
    await w.find('[data-testid="ep-filter-balance"]').trigger('click')
    expect(w.findAll('[data-testid^="ep-row-"]').map((r) => r.attributes('data-testid'))).toEqual(['ep-row-TokensTransferred'])
  })

  it('a row opens to its switches and its findings in words', async () => {
    h.effective.mockResolvedValue(VIEW)
    const w = await page()
    await rowOf(w, 'AgentSpawned').find('button.ep-et').trigger('click')
    const d = w.find('[data-testid="ep-detail-AgentSpawned"]')
    expect(d.text()).toContain('each gate decides by its mode')
    expect(d.text()).toContain("emitted by this code, no row")
  })

  it('drift: a peer read says what differs; a peer that was not read says why', async () => {
    h.effective.mockResolvedValue(VIEW)
    const w = await page()
    const ok = w.find('[data-testid="ep-drift-sbx-beta"]')
    expect(ok.attributes('data-read')).toBe('ok')
    expect(ok.text()).toContain('1 only here')
    expect(ok.text()).toContain('ExampleType')
    const failed = w.find('[data-testid="ep-drift-sbxbetaop"]')
    expect(failed.attributes('data-read')).toBe('failed')
    expect(failed.text()).toContain('ConnectTimeout')
  })

  it('a store the read could not reach is named at the top', async () => {
    h.effective.mockResolvedValue({ ...VIEW, store_read: 'ConnectError: event store', matrix: VIEW.matrix.map((r) => ({ ...r, store_count: null })) })
    const w = await page()
    expect(w.find('[data-testid="ep-store-read"]').text()).toContain('was not read: ConnectError')
    expect(rowOf(w, 'TokensTransferred').find('[data-testid="ep-cell-store"]').text()).toContain('not read')
  })

  it('a failed read says it failed, never an empty table, and reads again on Try again', async () => {
    h.effective.mockRejectedValueOnce(new Error('502'))
    const w = await page()
    expect(w.find('[data-testid="ep-unread"]').exists()).toBe(true)
    expect(w.find('[data-testid="ep-matrix"]').exists()).toBe(false)
    h.effective.mockResolvedValue(VIEW)
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.find('[data-testid="ep-matrix"]').exists()).toBe(true)
  })
})
