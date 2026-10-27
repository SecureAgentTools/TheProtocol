import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Quick onboarding (2026-10-09): what agentApi.create hands back, and the card it builds.
 *
 * The registry answers POST /onboard/create_agent with client_id and client_secret at the TOP level (§pass50.7), and
 * create() returned them from a nested `.credentials` that the registry never sends, so every caller got undefined and
 * had to read the browser's credential store instead. It also dropped what the registry said about the agent: the
 * starting-balance outcome (initial_funding_status), where its credentials are used (registry_url), the stored card's
 * id (agent_card_id) and the funding transaction. And the card's humanReadableId (which is also the path of its
 * placeholder endpoint) was the name lowercased with only whitespace replaced, so "#", "?", "/" and "%" landed in a URL
 * path. Now it is a slug of [a-z0-9-].
 */
const h = vi.hoisted(() => ({ post: vi.fn(), store: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { post: h.post } }))
vi.mock('./peerDirect', () => ({ mintAgentTokenAt: vi.fn() }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { storeCredentials: h.store } }))

import { agentApi } from './agents'

const CREATED = {
  agent_did: 'did:theprotocol:0f0e0d0c-0b0a-4000-8000-000000000001',
  client_id: 'agent-0123456789abcdef',
  client_secret: 'tp_secret_test_value',
  registry_url: 'https://registry.example.test',
  account_status: 'active',
  initial_funding_status: 'completed',
  faucet_transaction_id: 'tx-genesis-1',
  agent_card_id: '6f1c2a3b-0000-4000-8000-00000000c0de',
  agent_card_name: 'Cafe Bot',
}

function answer(created: Record<string, unknown> = CREATED) {
  h.post.mockImplementation(async (url: string) =>
    url.endsWith('/onboard/bootstrap/request-token') ? { data: { bootstrap_token: 'bst_test' } } : { data: created })
}

beforeEach(() => { h.post.mockReset(); h.store.mockReset() })

describe('agentApi.create', () => {
  it('returns the credentials the registry answers at the top level, and the facts it used to drop', async () => {
    answer()
    const a = await agentApi.create({ name: 'Cafe Bot', description: 'An agent for a test', capabilities: [] } as any)
    expect(a.did).toBe(CREATED.agent_did)
    expect(a.client_id).toBe(CREATED.client_id)
    expect(a.client_secret).toBe(CREATED.client_secret)
    expect(a.initial_funding_status).toBe('completed')
    expect(a.registry_url).toBe('https://registry.example.test')
    expect(a.agent_card_id).toBe(CREATED.agent_card_id)
    expect(a.faucet_transaction_id).toBe('tx-genesis-1')
  })

  it('control: a registry that nests the pair under `credentials` is still read', async () => {
    const { client_id, client_secret, ...rest } = CREATED
    answer({ ...rest, credentials: { client_id, client_secret } })
    const a = await agentApi.create({ name: 'Cafe Bot', description: 'An agent for a test', capabilities: [] } as any)
    expect(a.client_id).toBe(client_id)
    expect(a.client_secret).toBe(client_secret)
  })

  it('the humanReadableId, the endpoint path and the type hint are a slug of [a-z0-9-]', async () => {
    answer()
    await agentApi.create({ name: '  Café Bot #1? / ünïcode%  ', description: 'An agent for a test', capabilities: [] } as any)
    const [tokenUrl, tokenBody] = h.post.mock.calls[0]
    expect(tokenUrl).toBe('/onboard/bootstrap/request-token')
    expect(tokenBody.agent_type_hint).toBe('cafe-bot-1-unicode')
    const [createUrl, createBody] = h.post.mock.calls[1]
    expect(createUrl).toBe('/onboard/create_agent')
    const card = createBody.agent_card
    expect(card.humanReadableId).toBe('cafe-bot-1-unicode')
    expect(card.supportedInterfaces[0].url).toBe('http://localhost:8000/agents/cafe-bot-1-unicode')
    expect(card.url).toBe('http://localhost:8000/agents/cafe-bot-1-unicode')
    // the name itself is the person's own words, untouched
    expect(card.name).toBe('  Café Bot #1? / ünïcode%  ')
  })

  it('a name with no letter or digit becomes "agent", and a long one is cut without a trailing dash', async () => {
    answer()
    await agentApi.create({ name: '!!! ???', description: 'An agent for a test', capabilities: [] } as any)
    expect(h.post.mock.calls[1][1].agent_card.humanReadableId).toBe('agent')
    h.post.mockClear()
    await agentApi.create({ name: `${'a'.repeat(63)} b`, description: 'An agent for a test', capabilities: [] } as any)
    const hri = h.post.mock.calls[1][1].agent_card.humanReadableId as string
    expect(hri.length).toBeLessThanOrEqual(64)
    expect(hri).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/)
  })

  it('a name in a script with no Latin base keeps a handle of its own (not the one "agent" every such name shared)', async () => {
    answer()
    const hriFor = async (name: string) => {
      h.post.mockClear()
      await agentApi.create({ name, description: 'An agent for a test', capabilities: [] } as any)
      const card = h.post.mock.calls[1][1].agent_card
      // the endpoint path and the type hint carry the same handle
      expect(card.supportedInterfaces[0].url).toBe(`http://localhost:8000/agents/${card.humanReadableId}`)
      expect(h.post.mock.calls[0][1].agent_type_hint).toBe(card.humanReadableId)
      return card.humanReadableId as string
    }
    const cjk = await hriFor('研究助手')
    const ru = await hriFor('Помощник')
    expect(cjk).toMatch(/^agent-[0-9a-f]{6}$/)
    expect(ru).toMatch(/^agent-[0-9a-f]{6}$/)
    expect(cjk).not.toBe(ru)
    expect(await hriFor('研究助手')).toBe(cjk)
  })

  it('passes the statuses a caller expects to both requests (no global toast over its own sentence)', async () => {
    answer()
    await agentApi.create({ name: 'Cafe Bot', description: 'An agent for a test', capabilities: [] } as any, { expectedStatuses: [400, 403, 429] })
    expect(h.post.mock.calls[0][2]?.expectedStatuses).toEqual([400, 403, 429])
    expect(h.post.mock.calls[1][2]?.expectedStatuses).toEqual([400, 403, 429])
    expect(h.post.mock.calls[1][2]?.headers?.['Bootstrap-Token']).toBe('bst_test')
  })

  it('keeps the pair in this browser exactly as before', async () => {
    answer()
    await agentApi.create({ name: 'Cafe Bot', description: 'An agent for a test', capabilities: [] } as any)
    expect(h.store).toHaveBeenCalledTimes(1)
    const saved = h.store.mock.calls[0][0]
    expect(saved).toMatchObject({ did: CREATED.agent_did, client_id: CREATED.client_id, client_secret: CREATED.client_secret, name: 'Cafe Bot', humanReadableId: 'cafe-bot' })
  })
})
