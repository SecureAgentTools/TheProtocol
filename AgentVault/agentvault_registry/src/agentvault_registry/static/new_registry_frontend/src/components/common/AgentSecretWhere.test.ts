/**
 * V0653 (am) item 6 (session-lead's call, the sessions' room seq 808): the line says where an agent's secret sits in this
 * browser, and while it sits there unencrypted, it carries the press that locks it. BASE (V0652): no such line.
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ lock: null as any }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k) }) }))
vi.mock('@/composables/usePocketLock', () => ({ usePocketLock: () => h.lock }))

import AgentSecretWhere from './AgentSecretWhere.vue'

function lock(state: string, kdf: string | null) {
  const info = { state, kdf }
  h.lock = {
    available: vi.fn(async () => true),
    enabled: ref(true),
    enroll: vi.fn(async () => true),
    sealCredentials: vi.fn(async () => { info.state = 'sealed-open'; info.kdf = 'webauthn-prf'; return { ok: true } }),
    sealCredentialsDeviceKey: vi.fn(async () => ({ ok: true })),
    vaultInfo: () => ({ ...info }),
  }
  return h.lock
}

describe('AgentSecretWhere', () => {
  it('says an unencrypted secret is readable here and locks it with one press', async () => {
    const l = lock('plain', null)
    const w = mount(AgentSecretWhere)
    await flushPromises()
    expect(w.text()).toContain('unencrypted')
    await w.get('[data-testid="agent-secret-lock"]').trigger('click')
    await flushPromises()
    expect(l.sealCredentials).toHaveBeenCalledTimes(1)
    expect(w.get('[data-testid="agent-secret-where"]').attributes('data-place')).toBe('sealed-fingerprint')
    expect(w.find('[data-testid="agent-secret-lock"]').exists()).toBe(false)
    expect(w.text()).toContain('opens with your fingerprint or face')
  })

  it('names a sealed secret by its key and offers nothing more', async () => {
    lock('sealed-locked', 'device-key')
    const w = mount(AgentSecretWhere)
    await flushPromises()
    expect(w.text()).toContain('device key')
    expect(w.find('button').exists()).toBe(false)
  })
})
