/**
 * §DOCSFIX D6-631 (2026-10-16): the Games page's connector snippets name the registry the console runs on.
 *
 * The page printed `npx mcp-remote https://api.theprotocol.cloud/mcp/<game>/sse` and a Claude Desktop configuration on
 * that one host, whatever registry served it, so a player on ASIA was sent to EU's game servers. The game servers are
 * this registry's own (/mcp/<game>/...): the snippets name the origin the console was loaded from.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import GamesHub from './GamesHub.vue'

let w: VueWrapper | null = null
afterEach(() => { w?.unmount(); w = null; vi.restoreAllMocks() })

describe('the Games page connector snippets', () => {
  it('name this console\'s origin for every game, never a fixed host', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('offline'))
    w = mount(GamesHub, { global: { stubs: { Icon: true } } })
    await flushPromises()
    const text = w.text()
    const origin = window.location.origin
    expect(text).not.toContain('api.theprotocol.cloud')
    for (const game of ['arena', 'td', 'snake', 'trading', 'lobby']) {
      expect(text, game).toContain(`${origin}/mcp/${game}/sse`)
    }
  })
})
