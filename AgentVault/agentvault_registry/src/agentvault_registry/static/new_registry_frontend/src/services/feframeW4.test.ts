/**
 * §FEFRAME W4 (V0507) — the tidy, measured without a browser.
 *
 * 1. The local session end forgets the assistant's bring-your-own provider key (`tp_byok`): a secret of the person who
 *    typed it, which outlived every logout and answered for the next person in this browser.
 */
import { describe, it, expect } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

describe('the local session end', () => {
  it("forgets the assistant's provider key, and keeps what is not a secret", async () => {
    setActivePinia(createPinia())
    localStorage.setItem('tp_byok', 'sk-test-not-a-real-key')
    localStorage.setItem('beta_banner_dismissed', '1')
    const { useAuthStore } = await import('@/stores/auth')
    await useAuthStore().endLocalSession('a unit test')
    expect(localStorage.getItem('tp_byok')).toBeNull()
    expect(localStorage.getItem('beta_banner_dismissed')).toBe('1')     // the control: a preference survives
  }, 30_000)   // the first import of the auth store's module graph took over 5 s once, under a loaded host
})
