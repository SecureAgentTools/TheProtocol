/**
 * §FESUITE (V0578): the treasury desk drew whatever its last answer was under whichever frame and period were selected.
 * A read for another frame that failed (or was still out) left the previous frame's treasury balance under the new
 * frame's button: one frame's money shown as another's. The fee collector tab skipped its read whenever it held any
 * answer, so a frame changed on the Overview tab showed the old frame's fee collector. Now what is drawn answers the
 * selection or is not drawn, and a failed read of the same selection says the figures are from the last read.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ aggregate: vi.fn(), feeInfo: vi.fn(), peerGet: vi.fn(), showError: vi.fn() }))
vi.mock('@/services/api/treasuryAdmin', () => ({ treasuryAdminService: { aggregate: (...a: unknown[]) => h.aggregate(...a) } }))
vi.mock('@/services/api/feeCollectorAdmin', () => ({
  feeCollectorAdminService: { info: (...a: unknown[]) => h.feeInfo(...a), getPolicy: vi.fn(async () => ({})) },
}))
vi.mock('@/services/api/peer', () => ({ peerGet: (...a: unknown[]) => h.peerGet(...a) }))
vi.mock('@/composables/usePolledData', () => ({
  usePolledData: (fn: () => unknown) => { fn(); return { pause() {}, resume() {} } },
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('@/composables/useFrames', () => ({ useFrames: () => ({ frames: ref([{ key: 'asia', currency: 'ACU' }]) }) }))
vi.mock('@/composables/usePermissions', () => ({ usePermissions: () => ({ canMintAvt: computed(() => false) }) }))
vi.mock('@/stores/multiFrameSession', () => ({ useMultiFrameSession: () => ({ adminTokenFor: (k: string) => (k === 'asia' ? 'tok-asia' : null) }) }))
vi.mock('@/composables/useAdminFrames', () => {
  const local = { key: 'local', label: 'EU', sub: '', accentHex: '#0ff', isLocal: true, frameParam: 'local' }
  const asia = { key: 'asia', label: 'ASIA', sub: '', accentHex: '#f00', isLocal: false, frameParam: 'local' }
  return { useAdminFrames: () => ({ selectableFrames: computed(() => [local, asia]), resolveOption: (k: string) => (k === 'asia' ? asia : local) }) }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: true, user: { is_admin: true } }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError, showSuccess: vi.fn(), setActiveFrame: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import AdminTreasury from './AdminTreasury.vue'

const EU_DID = 'did:theprotocol:eu-treasury'
const ASIA_DID = 'did:theprotocol:asia-treasury'
const aggregate = (did: string, balance: string) => ({
  frame: 'local', period: '7d', as_of: '2026-10-05T15:00:00Z',
  supply_audit: { delta: 0, status: 'OK', agent_count: 3 },
  treasury: { balance, treasury_did: did, error: null },
  totals_in_window: { minted: '0', fees_collected: '0', mint_count: 0, fee_count: 0, mint_truncated: false, fee_truncated: false },
  mints_by_reason: {}, top_fee_payers: [], recent_mints: [], sparkline: [],
})
const fee = (did: string) => ({
  as_of: '2026-10-05T15:00:00Z', period: '7d', fee_collector_did: did, balance: '12', teg_error: null,
  totals_in_window: { inflow: '0', fee_count: 0, fee_truncated: false }, sparkline: [], recent: [],
})
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

let w: VueWrapper | null = null
async function desk() {
  w = mount(AdminTreasury, { global: { stubs: { Icon: true, ConfirmActionModal: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function press(selector: string, label: string) {
  const b = w!.findAll(selector).find(x => x.text().trim() === label)
  expect(b, `no "${label}" in ${selector}`).toBeTruthy()
  await b!.trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
}
const body = () => w!.find('.at-body').text()

describe('the treasury desk draws only the answer for the selected frame and period', () => {
  beforeEach(() => { h.aggregate.mockReset(); h.feeInfo.mockReset(); h.peerGet.mockReset(); h.showError.mockReset() })
  afterEach(() => { w?.unmount(); w = null })

  it('a failed read of another frame never shows this frame\'s treasury under that frame\'s button', async () => {
    h.aggregate.mockResolvedValue(aggregate(EU_DID, '425000000'))
    await desk()
    expect(body()).toContain(EU_DID)
    h.peerGet.mockRejectedValueOnce(badGateway())
    await press('.at-frame-btn', 'asia')
    expect(h.peerGet).toHaveBeenCalled()
    expect(body(), "drew EU's treasury under the ASIA button after ASIA's read failed").not.toContain(EU_DID)
  })

  it('while another frame\'s read is out, the previous frame\'s treasury is not drawn under it', async () => {
    h.aggregate.mockResolvedValue(aggregate(EU_DID, '425000000'))
    await desk()
    h.peerGet.mockReturnValueOnce(new Promise(() => {}))
    await press('.at-frame-btn', 'asia')
    expect(body(), "drew EU's treasury under the ASIA button while ASIA's read was out").not.toContain(EU_DID)
  })

  it('a failed poll of the same frame says the figures are from the last read that answered', async () => {
    h.aggregate.mockResolvedValueOnce(aggregate(EU_DID, '425000000'))
    await desk()
    h.aggregate.mockRejectedValueOnce(badGateway())
    await w!.find('.at-toolbar .at-btn--ghost').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(body()).toContain(EU_DID)
    expect(w!.find('[data-read-failed]').exists(), 'a failed read said nothing on the page').toBe(true)
  })

  it('the fee collector tab reads again after the frame changed on the Overview tab', async () => {
    h.aggregate.mockResolvedValue(aggregate(EU_DID, '425000000'))
    h.feeInfo.mockResolvedValue(fee('did:theprotocol:eu-fees'))
    h.peerGet.mockImplementation(async (_k: string, path: string) =>
      (path.includes('fee-collector') ? fee('did:theprotocol:asia-fees') : aggregate(ASIA_DID, '9000')))
    await desk()
    await w!.findAll('.at-tab').find(b => /fee/i.test(b.text()))!.trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(h.feeInfo).toHaveBeenCalledTimes(1)
    await w!.findAll('.at-tab').find(b => /overview/i.test(b.text()))!.trigger('click')
    await press('.at-frame-btn', 'asia')
    await w!.findAll('.at-tab').find(b => /fee/i.test(b.text()))!.trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(h.peerGet.mock.calls.some((c: any[]) => String(c[1]).includes('fee-collector')),
      "opened the fee tab for ASIA without reading ASIA's fee collector").toBe(true)
  })
})
