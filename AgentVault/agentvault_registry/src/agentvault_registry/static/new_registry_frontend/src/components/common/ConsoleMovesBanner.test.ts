/**
 * §FEFRAME W4 (V0507) — one console host per frame: the banner shows on an alias host only, names the canonical
 * console, offers the saved credentials as a file where there are any, never shows on loopback, and stays dismissed for
 * the browser session.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'

const self = ref<any>({ key: 'eu', display_name: 'EU', console_url: 'https://theprotocol.cloud', public_url: 'https://theprotocol.cloud' })
vi.mock('@/composables/useFrameManifest', () => ({ useFrameManifest: () => ({ self }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/my-agents' }) }))
const saved = vi.fn(() => ({}))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getAllCredentials: () => saved() } }))

async function at(href: string) {
  vi.stubGlobal('location', new URL(href))
  vi.resetModules()
  const { default: Banner } = await import('./ConsoleMovesBanner.vue')
  return mount(Banner)
}

beforeEach(() => { sessionStorage.clear(); saved.mockReturnValue({}) })
afterEach(() => { vi.unstubAllGlobals() })

describe('the alias-host banner', () => {
  it('shows on an alias host, names the canonical console and links the same page there', async () => {
    const w = await at('https://api.theprotocol.cloud/ui/#/my-agents')
    expect(w.find('[data-testid="console-moves"]').exists()).toBe(true)
    expect(w.text()).toContain('https://theprotocol.cloud')
    expect(w.find('[data-testid="console-moves-go"]').attributes('href')).toBe('https://theprotocol.cloud/#/my-agents')
    expect(w.find('[data-testid="console-moves-download"]').exists()).toBe(false)      // nothing saved, nothing offered
  })

  it('offers the saved credentials as a file where there are any', async () => {
    saved.mockReturnValue({ 'did:theprotocol:a': { did: 'did:theprotocol:a', client_id: 'c', client_secret: 's' } })
    const w = await at('https://registry.theprotocol.cloud/ui/#/')
    expect(w.find('[data-testid="console-moves-download"]').exists()).toBe(true)
  })

  it('is absent on the canonical host and on loopback (the controls)', async () => {
    expect((await at('https://theprotocol.cloud/#/')).find('[data-testid="console-moves"]').exists()).toBe(false)
    expect((await at('http://127.0.0.1:8350/ui/#/')).find('[data-testid="console-moves"]').exists()).toBe(false)
    expect((await at('http://localhost:5173/#/')).find('[data-testid="console-moves"]').exists()).toBe(false)
  })

  it('stays dismissed for the browser session', async () => {
    const w = await at('https://api.theprotocol.cloud/ui/#/')
    await w.find('.cmb-x').trigger('click')
    expect(w.find('[data-testid="console-moves"]').exists()).toBe(false)
    expect((await at('https://api.theprotocol.cloud/ui/#/')).find('[data-testid="console-moves"]').exists()).toBe(false)
  })
})
