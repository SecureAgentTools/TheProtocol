/**
 * §REPATLANE-7 (after V0606): a priced first contact from Pocket is two acts in order. The profile opens the ONE send door
 * (PocketSend) for the price, and when the sheet hands back its receipt, the profile opens the thread with the receipt's
 * reference, which the registry checks at the receiver's ledger (§OURSTATE-5). /teg/send answers that reference as
 * transfer_id (SmartSendResponse); the sheet read transaction_id, which the answer never carries, so from 2026-08-24 every
 * receipt came back without one: the price was paid and the profile said the payment "returned no reference, so the
 * thread was not opened" (lifecycle 96 measured it live on V0607). This mounts the profile with the real sheet inside,
 * mocked only at the API edge, and walks the whole chain.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { markReplayed } from '@/services/money/sendOutcome'

const h = vi.hoisted(() => ({
  FROM: 'did:theprotocol:0d6b1f4e-7c2a-4e9b-8f31-5a2c9d7e4b10',
  PURSE: 'did:theprotocol:9a3e5c71-2b8d-4f06-a1c4-7e2d0b6f3c58',
  smartSend: null as any,
  createConversation: null as any,
  push: null as any,
  keys: 0,
}))
vi.mock('@/composables/useI18n', () => ({
  useI18n: () => ({
    t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k),
    tp: (k: string, fb: string, p?: Record<string, unknown>) => String(fb ?? k).replace(/\{(\w+)\}/g, (_m, n) => String(p?.[n] ?? '')),
  }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: (...a: unknown[]) => h.push(...a) }) }))
vi.mock('@/services/api/chat', () => ({
  chatApi: {
    handleProfile: async () => ({ display_name: 'Owner', contact: { policy: 'priced', price: '1', currency: 'SBXA', purse_did: h.PURSE } }),
    handlePulse: async () => ({ moments: [] }),
    createConversation: (...a: unknown[]) => h.createConversation(...a),
  },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: h.FROM } }) }))
vi.mock('@/composables/usePocketAgent', () => ({
  usePocketAgent: () => ({ credAgents: computed(() => [{ did: h.FROM, name: 'Mine' }]), noAgentReason: computed(() => ''), ensureAgentFor: async () => true }),
}))
vi.mock('@/composables/useFrameManifest', () => ({ currentOwnCurrency: () => 'SBXA' }))
vi.mock('@/composables/useFocusTrap', () => ({ useFocusTrap: () => {} }))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ amount: (v: unknown) => String(v) }) }))
vi.mock('@/composables/usePocketLock', () => ({ usePocketLock: () => ({ enabled: ref(false), verify: async () => true }) }))
vi.mock('@/composables/usePocketNfc', () => ({
  usePocketNfc: () => ({ supported: ref(false), scanning: ref(false), writing: ref(false), stopScan() {}, scanPayRequest: async () => null, writePayRequest: async () => {} }),
  buildPayUri: () => '',
}))
vi.mock('@/services/api/teg', () => ({ tegApi: { smartSend: (...a: unknown[]) => h.smartSend(...a) } }))
vi.mock('@/services/api/idempotencyKey', () => ({ newIdempotencyKey: () => `key-${++h.keys}` }))

import PocketProfile from './PocketProfile.vue'

const TX = '4e56d624-b776-460f-9dbc-83b64efdacd7'
const PREVIEW = { ok: true, dry_run: true, method: 'local', status: 'preview', amount: '1', fee: '0.005' }
/** /teg/send's SmartSendResponse: the reference is transfer_id, the inner endpoint's answer under detail */
const sent = (headers: Record<string, string> = {}) =>
  markReplayed({ ok: true, method: 'local', status: 'completed', transfer_id: TX, detail: { transaction_id: TX, status: 'completed' } }, headers)
const lost = () => Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })

/** the real sends the sheet made (not its previews), each with the key it carried */
function realSends(): string[] {
  return h.smartSend.mock.calls.filter((c: any[]) => c[0]?.dry_run === false).map((c: any[]) => c[1]?.idempotencyKey)
}

async function profile(): Promise<VueWrapper> {
  const w = mount(PocketProfile, {
    props: { show: true, handle: 'owner', token: 'dev-token' },
    global: { stubs: { Icon: true, OurStateIdentity: true, ActingContextNotice: true } },
  })
  await flushPromises()
  const go = w.find('[data-testid="pp-message"]')
  expect(go.text()).toContain('Pay 1 SBXA and message')
  await go.trigger('click')
  await flushPromises()
  expect(w.find('.ps-sheet').exists(), 'the send sheet opens for the price').toBe(true)
  expect((w.find('.ps-sheet input.ps-amt').element as HTMLInputElement).value).toBe('1')
  await w.find('.ps-sheet .ps-primary').trigger('click')
  await flushPromises()
  expect(w.find('[data-testid="ps-assert"]').exists(), 'the preview').toBe(true)
  return w
}

async function pressSend(w: VueWrapper): Promise<void> {
  await w.find('.ps-sheet .ps-send').trigger('click')
  await flushPromises()
}

/** the sheet hands its receipt over 1.1 s after the sent line, then closes */
async function handOver(): Promise<void> {
  await vi.advanceTimersByTimeAsync(1100)
  await flushPromises()
}

describe('a priced first contact from Pocket', () => {
  beforeEach(() => {
    h.keys = 0
    h.createConversation = vi.fn(async () => ({ conversation_id: 'conv-1' }))
    h.push = vi.fn(async () => {})
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  })
  afterEach(() => { vi.useRealTimers() })

  it("pays the price, then opens the thread with the send's reference", async () => {
    h.smartSend = vi.fn(async (body: any) => (body.dry_run ? PREVIEW : sent()))
    const w = await profile()
    await pressSend(w)
    expect(w.find('.ps-sheet .ps-result.ok').text()).toContain(TX.slice(0, 12))
    await handOver()
    expect(h.createConversation, 'the thread is opened with the payment as its proof').toHaveBeenCalledTimes(1)
    expect(h.createConversation.mock.calls[0][4]).toBe(TX)
    expect(h.push).toHaveBeenCalledWith('/pocket/ourchat/conv-1')
    expect(w.find('[data-testid="pp-err"]').exists()).toBe(false)
    expect(realSends()).toEqual(['key-1'])
  })

  it('a lost answer, pressed again: the same request, answered again, and the thread still opens with its reference', async () => {
    let n = 0
    h.smartSend = vi.fn(async (body: any) => {
      if (body.dry_run) return PREVIEW
      n += 1
      if (n === 1) throw lost()
      return sent({ 'idempotent-replayed': 'true' })
    })
    const w = await profile()
    await pressSend(w)
    expect(w.find('[data-testid="ps-unknown-outcome"]').text()).toContain('may have gone through')
    expect(h.createConversation).not.toHaveBeenCalled()
    await pressSend(w)
    expect(w.find('.ps-sheet .ps-result.ok').text()).toContain('your first press had already gone through')
    await handOver()
    expect(realSends(), 'one payment, asked twice under one key').toEqual(['key-1', 'key-1'])
    expect(h.createConversation).toHaveBeenCalledTimes(1)
    expect(h.createConversation.mock.calls[0][4]).toBe(TX)
  })

  it('control: an answer that names no reference opens no thread, and the profile says why', async () => {
    h.smartSend = vi.fn(async (body: any) => (body.dry_run ? PREVIEW : { ok: true, method: 'local', status: 'completed' }))
    const w = await profile()
    await pressSend(w)
    await handOver()
    expect(h.createConversation).not.toHaveBeenCalled()
    expect(w.find('[data-testid="pp-err"]').text()).toContain('returned no reference')
  })
})
