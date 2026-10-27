/**
 * §REPATLANE-7 (after V0606): the quick send that the bridge and the desk's Quick actions pane both mount keeps one
 * Idempotency-Key per request. An answer that never came (a network error, a 5xx) may have been the payment: the outcome
 * says the send may have gone through, and pressing send again asks with the SAME key; the registry's answer given again
 * under that key (Idempotent-Replayed) says the first press had already gone through, with the payment's reference (the
 * answer's transfer_id). A refusal frees the key, and so does a send that was answered: the next press is a new request.
 * Lifecycle 95 drives Pocket's sheet this way on a phone; no lifecycle reaches this desktop twin, so this pins it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { markReplayed } from '@/services/money/sendOutcome'

const h = vi.hoisted(() => ({ smartSend: null as any, keys: 0 }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k) }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:payer', name: 'Payer' }, isAdmin: false }) }))
vi.mock('@/stores/staking', () => ({ useStakingStore: () => ({ fetchMyStakingStats: async () => {}, availableRewards: 0 }) }))
vi.mock('@/services/api/teg', () => ({ tegApi: { smartSend: (...a: unknown[]) => h.smartSend(...a) } }))
vi.mock('@/services/api/idempotencyKey', () => ({ newIdempotencyKey: () => `key-${++h.keys}` }))
vi.mock('@/services/api/command', () => ({ fundAgentLocal: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn(async () => ({ data: {} })), post: vi.fn() } }))

import BridgeQuickActions from './BridgeQuickActions.vue'

const TX = '4e56d624-b776-460f-9dbc-83b64efdacd7'
const PAYEE = 'did:theprotocol:6f1c2a9e-0b3d-4c55-9a7e-2f4d8c1b7e30'

/** no response at all: not an answer, so the value may have moved */
function lost(): Error {
  return Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })
}
function answered(status: number, detail: string): Error {
  return Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data: { detail } } })
}
const first = () => markReplayed({ ok: true, method: 'local', status: 'completed', transfer_id: TX }, {})
const again = () => markReplayed({ ok: true, method: 'local', status: 'completed', transfer_id: TX }, { 'idempotent-replayed': 'true' })

async function bar(): Promise<VueWrapper> {
  const w = mount(BridgeQuickActions, {
    props: { targetDid: PAYEE, targetName: 'Payee', currency: 'SBXA' },
    global: { stubs: { AmountActionModal: true, ActingContextNotice: true } },
  })
  await flushPromises()
  await w.find('[data-testid="qa-send"]').trigger('click')
  expect(w.findComponent({ name: 'AmountActionModal' }).props('show'), 'SEND opens its amount dialog').toBe(true)
  return w
}

async function press(w: VueWrapper, amount = '0.5'): Promise<string> {
  w.findComponent({ name: 'AmountActionModal' }).vm.$emit('confirm', { amount, reason: '' })
  await flushPromises()
  return w.find('[data-testid="qa-outcome"]').text()
}

function keysAsked(): string[] {
  return h.smartSend.mock.calls.map((c: unknown[]) => (c[1] as { idempotencyKey: string }).idempotencyKey)
}

describe("the quick send's key when an answer is lost", () => {
  beforeEach(() => { h.keys = 0 })

  it('a lost answer may have been the payment; the next press asks with the same key and is told the first had gone through', async () => {
    h.smartSend = vi.fn().mockRejectedValueOnce(lost()).mockResolvedValueOnce(again())
    const w = await bar()
    const said = await press(w)
    expect(said).toContain('may have gone through')
    expect(said).not.toContain('Failed')
    expect(w.findComponent({ name: 'AmountActionModal' }).props('show'), 'the dialog stays open for the second press').toBe(true)
    const then = await press(w)
    expect(keysAsked(), 'the second press is the same request').toEqual(['key-1', 'key-1'])
    expect(then).toContain('Sent 0.5 SBXA')
    expect(then, "the payment's reference").toContain(TX.slice(0, 12))
    expect(then).toContain('your first press had already gone through')
  })

  it('a 4xx that says the payment may have moved keeps the key too', async () => {
    h.smartSend = vi.fn()
      .mockRejectedValueOnce(answered(409, 'route 5164295b (outcome not known): nothing refunded, held'))
      .mockResolvedValueOnce(again())
    const w = await bar()
    expect(await press(w)).toContain('may have gone through')
    await press(w)
    expect(keysAsked()).toEqual(['key-1', 'key-1'])
  })

  it('control: a first answer names its reference and does not say it was given again', async () => {
    h.smartSend = vi.fn().mockResolvedValueOnce(first())
    const w = await bar()
    const said = await press(w)
    expect(said).toContain('Sent 0.5 SBXA')
    expect(said).toContain(TX.slice(0, 12))
    expect(said).not.toContain('already gone through')
  })

  it('a refusal frees the key: the next press is a new request', async () => {
    h.smartSend = vi.fn().mockRejectedValueOnce(answered(400, 'Insufficient balance')).mockResolvedValueOnce(first())
    const w = await bar()
    expect(await press(w)).toContain('Failed: Insufficient balance')
    await w.find('[data-testid="qa-send"]').trigger('click')
    await press(w)
    expect(keysAsked()).toEqual(['key-1', 'key-2'])
  })

  it('a send that was answered frees the key: the same amount to the same agent again is a second payment, on purpose', async () => {
    h.smartSend = vi.fn().mockResolvedValueOnce(first()).mockResolvedValueOnce(first())
    const w = await bar()
    await press(w)
    await w.find('[data-testid="qa-send"]').trigger('click')
    await press(w)
    expect(keysAsked()).toEqual(['key-1', 'key-2'])
  })
})
