/**
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): the import itself offers the lock. After a secret
 * is saved and still sits unencrypted in this browser, the dialog stays open on a saved step that says so and carries
 * the one press that locks it, then Done; where the vault is already sealed, it closes as before. BASE (V0652): the
 * dialog closed at once and only Pocket's settings could lock the secret.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ lock: null as any, stored: [] as any[] }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k) }) }))
vi.mock('@/composables/usePocketLock', () => ({ usePocketLock: () => h.lock }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ setActiveAgentFromToken: vi.fn() }) }))
vi.mock('@/services/api/agents', () => ({ agentApi: { authenticate: vi.fn(async () => ({ access_token: 'tok' })) } }))
vi.mock('@/services/agentCredentialsStore', () => ({
  agentCredentialsStore: { storeCredentials: (c: any) => { h.stored.push(c) } },
}))

import AddCredentialsModal from './AddCredentialsModal.vue'

function lock(state: string, kdf: string | null) {
  h.lock = {
    available: vi.fn(async () => true),
    enabled: ref(false),
    enroll: vi.fn(async () => true),
    sealCredentials: vi.fn(async () => ({ ok: true })),
    sealCredentialsDeviceKey: vi.fn(async () => ({ ok: true })),
    vaultInfo: () => ({ state, kdf }),
  }
}

async function saveWith() {
  const w = mount(AddCredentialsModal, {
    props: { show: false, agent: { did: 'did:theprotocol:eu.example:a1', name: 'Agent One' } },
    global: { stubs: { teleport: true } },
  })
  await w.setProps({ show: true })
  await flushPromises()
  const inputs = w.findAll('input:not([type="checkbox"])')
  await inputs[0].setValue('agent-0123456789abcdef')
  await inputs[1].setValue('tp_secret_value')
  await w.get('.tp-modal-footer .tp-btn--primary').trigger('click')
  await flushPromises()
  return w
}

beforeEach(() => { h.stored = [] })

describe('the import offers the lock', () => {
  it('stays open on a saved step that says where the secret sits and offers the lock', async () => {
    lock('plain', null)
    const w = await saveWith()
    expect(h.stored).toHaveLength(1)
    expect(w.emitted('saved')).toBeTruthy()
    expect(w.emitted('close')).toBeFalsy()
    expect(w.find('[data-testid="add-creds-saved"]').exists()).toBe(true)
    expect(w.find('[data-testid="agent-secret-lock"]').exists()).toBe(true)
    await w.get('[data-testid="add-creds-done"]').trigger('click')
    expect(w.emitted('close')).toBeTruthy()
  })

  it('closes as before where the vault is already sealed', async () => {
    lock('sealed-open', 'webauthn-prf')
    const w = await saveWith()
    expect(w.emitted('saved')).toBeTruthy()
    expect(w.emitted('close')).toBeTruthy()
  })
})
