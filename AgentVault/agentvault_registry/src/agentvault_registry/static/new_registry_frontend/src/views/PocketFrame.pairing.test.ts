import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §COCKPITDESK (2026-10-15) — /pocket-frame "Pair this phone": the QR never carried a key. The view read `key.key` from
 * the legacy /developers/me/apikeys, which answers `plain_api_key` (and drops the name, minting an unlabelled,
 * non-expiring key per press); the phone app (mobile/src/pairing.ts) refuses a payload without an avreg_ key. It pairs
 * through the canonical /auth/api-keys now: the key named after the device, in the QR.
 */
const h = vi.hoisted(() => ({ createApiKey: vi.fn(), toCanvas: vi.fn(), listMine: vi.fn() }))
vi.mock('@/services/api/developer', () => ({ developerApi: { createApiKey: h.createApiKey } }))
vi.mock('@/services/api/devicePush', () => ({
  devicePushApi: { getConfig: vi.fn().mockResolvedValue({}), listMine: h.listMine },
  randomNtfyTopic: () => 'pf-topic',
}))
vi.mock('qrcode', () => ({ default: { toCanvas: h.toCanvas } }))
vi.mock('@/composables/useFrames', async () => {
  const { ref } = await import('vue')
  return { useFrames: () => ({ localCurrency: ref('ECU') }) }
})

import PocketFrame from './PocketFrame.vue'

const stubs = { Icon: true, ReadFailedNotice: true, ConfirmActionModal: true, teleport: true }
async function pair(label: string) {
  const w = mount(PocketFrame, { global: { stubs } })
  await flushPromises()
  await w.find('input[aria-label="Device label"]').setValue(label)
  await w.find('input[aria-label="Device label"]').trigger('keyup.enter')
  await flushPromises()
  return w
}

describe('pairing a phone', () => {
  beforeEach(() => {
    setActivePinia(createPinia()); h.createApiKey.mockReset(); h.toCanvas.mockReset().mockResolvedValue(undefined)
    h.listMine.mockReset().mockResolvedValue({ devices: [] })
  })

  it('the QR carries the minted avreg_ key, the registry and the label; the key is named after the device', async () => {
    h.createApiKey.mockResolvedValue({ plain_api_key: 'avreg_pairing_test_key', api_key_info: { id: 1, key_prefix: 'avreg_' } })
    const w = await pair('Pixel 9')
    // §POCKETPAIR (2026-10-15): the phone's key is narrow (no admin, no minting) and expires in 90 days. SEC-10: it holds
    // the phone's own scope for its push registration ('pocket:device'), beside the MCP tools; 'mcp:tools' alone (an
    // MCP connector's key) no longer registers a push device
    expect(h.createApiKey).toHaveBeenCalledWith('POCKET FRAME: Pixel 9',
      { scopes: ['mcp:tools', 'pocket:device'], expires_in_days: 90 })
    expect(h.toCanvas).toHaveBeenCalledTimes(1)
    const payload = JSON.parse(h.toCanvas.mock.calls[0][1])
    expect(payload).toEqual({ v: 1, registry_url: window.location.origin, api_key: 'avreg_pairing_test_key', label: 'Pixel 9' })
    w.unmount()
  })

  it("the key's expiry is said beside the QR", async () => {
    h.createApiKey.mockResolvedValue({ plain_api_key: 'avreg_pairing_test_key', api_key_info: { id: 1, expires_at: '2027-01-13T10:00:00Z' } })
    const w = await pair('Pixel 9')
    const note = w.find('[data-testid="pf-pair-expires"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('2027')
    w.unmount()
  })

  it('an answer without a key draws no QR and says so', async () => {
    h.createApiKey.mockResolvedValue({ api_key_info: { id: 1 } })
    const w = await pair('Pixel 9')
    expect(h.toCanvas).not.toHaveBeenCalled()
    expect(w.text()).toContain('without a key to pair with')
    w.unmount()
  })
})

describe('removing a paired phone', () => {
  beforeEach(() => { setActivePinia(createPinia()); h.listMine.mockReset() })

  async function askToRemove(device: Record<string, unknown>) {
    h.listMine.mockResolvedValue({ devices: [device] })
    const w = mount(PocketFrame, { global: { stubs } })
    await flushPromises()
    await w.find('button[title="Remove device"]').trigger('click')
    await flushPromises()
    return w
  }

  it('says before the press that its paired key is revoked with it (§POCKETPAIR)', async () => {
    const w = await askToRemove({ id: 7, platform: 'android', rail: 'ntfy', target: 'pf-a', label: 'Pixel 9', enabled: true,
      paired_key: true, paired_key_active: true })
    expect(w.text()).toContain('paired key')
    const msg = String(w.findComponent({ name: 'ConfirmActionModal' }).props('message'))
    expect(msg).toContain('revoke the key this phone was paired with')
    w.unmount()
  })

  it('a device registered without a key keeps the plain message', async () => {
    const w = await askToRemove({ id: 8, platform: 'web', rail: 'ntfy', target: 'pf-b', label: 'Desk', enabled: true })
    const msg = String(w.findComponent({ name: 'ConfirmActionModal' }).props('message'))
    expect(msg).toContain('You can re-register it any time')
    expect(msg).not.toContain('revoke')
    w.unmount()
  })
})
