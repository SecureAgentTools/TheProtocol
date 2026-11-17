/**
 * V0663 (order gwo_f8251964b96cb1759350b69d, his suggestion 9): #/cards/compare?a=<did>&b=<did>, two agent cards side by
 * side, read-only, as served.
 *   - "as exported" (default): each card as the world reads it, GET /agents/{did}/card-export (the agent's own slice);
 *     "as stored here": this registry's whole copy, GET /agents/by-did/{did} card_data (with its own fields);
 *   - a summary of what differs, the differing paths with both values, and the two JSON panes with the differing
 *     lines marked; "differences only" hides the paths that are the same;
 *   - a card this registry does not hold says so, and names its home from the federated index when the index knows it;
 *   - the agent card view links here with its card as A.
 * Red on b27f2ebaf: the page does not exist.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), route: { query: {} as Record<string, any> }, replace: vi.fn() }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get, post: h.post }, apiClient: { get: h.get, post: h.post } }))
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ replace: h.replace, push: vi.fn() }) }))

import CardCompare from './CardCompare.vue'

const A_DID = 'did:theprotocol:eu:alpha'
const B_DID = 'did:theprotocol:eu:quantum'
const A = { name: 'Alpha', version: '1.0', capabilities: { streaming: true } }
const B = { name: 'Alpha', version: '1.0', capabilities: { streaming: true, quantum: { backends: 2 } } }

function serve(map: Record<string, any>) {
  h.get.mockImplementation(async (url: string) => {
    if (url in map) {
      const v = map[url]
      if (v instanceof Error || (v && v.response)) throw v
      return { data: v }
    }
    throw new Error(`unexpected read ${url}`)
  })
}
const exp = (did: string) => `/agents/${encodeURIComponent(did)}/card-export`
const stored = (did: string) => `/agents/by-did/${encodeURIComponent(did)}`

async function page() {
  const w = mount(CardCompare)
  await flushPromises()
  return w
}

describe('the card compare page', () => {
  beforeEach(() => { h.get.mockReset(); h.post.mockReset(); h.replace.mockReset(); h.route.query = { a: A_DID, b: B_DID } })

  it('reads both cards as exported and marks what differs', async () => {
    serve({ [exp(A_DID)]: A, [exp(B_DID)]: B })
    const w = await page()
    expect(w.find('[data-testid="cmp-summary"]').text()).toMatch(/1\D+only in B/)
    const diffs = w.findAll('[data-testid="cmp-diff-row"]')
    expect(diffs.map((r) => r.attributes('data-path'))).toEqual(['capabilities.quantum'])
    const right = w.find('[data-testid="cmp-pane-b"]')
    expect(right.findAll('[data-mark="only"]').length).toBeGreaterThan(0)
    expect(w.find('[data-testid="cmp-pane-a"]').findAll('[data-mark="only"]').length).toBe(0)
  })

  it('differences only hides the paths that are the same, and shows them again', async () => {
    serve({ [exp(A_DID)]: A, [exp(B_DID)]: B })
    const w = await page()
    expect(w.findAll('[data-testid="cmp-diff-row"]').length).toBe(1)
    await w.find('[data-testid="cmp-only-diff"]').setValue(false)
    expect(w.findAll('[data-testid="cmp-diff-row"]').length).toBe(4)
  })

  it('as stored here reads the whole copy this registry keeps', async () => {
    serve({ [exp(A_DID)]: A, [exp(B_DID)]: B,
      [stored(A_DID)]: { did: A_DID, card_data: { ...A, flare: { tier: 'gold' } } },
      [stored(B_DID)]: { did: B_DID, card_data: B } })
    const w = await page()
    await w.find('[data-testid="cmp-source-stored"]').trigger('click')
    await flushPromises()
    expect(h.get).toHaveBeenCalledWith(stored(A_DID))
    const paths = w.findAll('[data-testid="cmp-diff-row"]').map((r) => r.attributes('data-path'))
    expect(paths).toContain('flare')
  })

  it('a card this registry does not hold says so and names its home from the index', async () => {
    serve({ [exp(A_DID)]: A, [exp(B_DID)]: { response: { status: 404, data: { detail: 'Agent not found' } } } })
    h.post.mockResolvedValue({ data: { data: { agent: { home: { name: 'asia-registry', publicUrl: 'https://asia.example.org' } } } } })
    const w = await page()
    const note = w.find('[data-testid="cmp-missing-b"]')
    expect(note.text()).toContain('asia-registry')
    expect(note.find('a').attributes('href')).toBe('https://asia.example.org/')   // through safeExternalUrl, normalised
    expect(w.find('[data-testid="cmp-summary"]').exists()).toBe(false)
  })

  it('picking a card changes the address, and an empty side asks for one', async () => {
    h.route.query = { a: A_DID }
    serve({ [exp(A_DID)]: A })
    const w = await page()
    expect(w.find('[data-testid="cmp-ask-b"]').exists()).toBe(true)
    await w.find('[data-testid="cmp-input-b"]').setValue(B_DID)
    await w.find('[data-testid="cmp-pick"]').trigger('submit')
    expect(h.replace).toHaveBeenCalledWith({ query: { a: A_DID, b: B_DID } })
  })
})

describe('the agent card view links here', () => {
  it('with its card as A', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(path.resolve(__dirname, '../components/AgentDetailModal.vue'), 'utf8')
    expect(src).toMatch(/\/cards\/compare\?a=\$\{encodeURIComponent\(resolvedDid\)\}/)
  })
})
