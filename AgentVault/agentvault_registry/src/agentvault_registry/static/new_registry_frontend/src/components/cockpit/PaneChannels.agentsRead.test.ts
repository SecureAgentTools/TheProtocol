/**
 * §FESUITE (V0577): the desk's Channels pane picks the agent an instruction goes to from your agents
 * (agentApi.getMyAgents, or its server-side search). A failed read was swallowed ("the instruct half degrades to pick
 * nothing"), so the picker sat empty under "Most recently active first — 0 of these called this registry in the last 15
 * minutes.": a failed read looked like an account with no live agents. It now says the agents could not be read and
 * offers the read again; once it answers, the picker and its ranking line are back.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ getMyAgents: vi.fn() }))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: h.getMyAgents } }))
vi.mock('@/services/api/agentChannels', () => ({
  agentChannelsApi: { progress: vi.fn(async () => ({ notes: [], degraded: false })) },
}))
vi.mock('@/services/cockpit/pollJitter', () => ({ setJitteredInterval: () => 0 }))

import PaneChannels from './PaneChannels.vue'

async function pane() {
  const w = mount(PaneChannels, { global: { stubs: { AgentLink: true } } })
  await flushPromises()
  return w
}

describe("the desk's Channels pane when its agents read fails", () => {
  beforeEach(() => { h.getMyAgents.mockReset() })

  it('says the agents could not be read, never "0 of these called this registry", and reads again', async () => {
    h.getMyAgents.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await pane()
    expect(w.find('[data-testid="chn-rank"]').exists(), 'drew "0 of these called this registry" over a failed read').toBe(false)
    const notice = w.find('[data-testid="chn-agents-failed"]')
    expect(notice.exists()).toBe(true)

    h.getMyAgents.mockResolvedValue([{ did: 'did:theprotocol:a1', name: 'Agent One' }])
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="chn-agents-failed"]').exists()).toBe(false)
    expect(w.find('[data-testid="chn-rank"]').exists()).toBe(true)
    expect(w.findAll('[data-testid="chn-opt"]')).toHaveLength(1)
  })
})
