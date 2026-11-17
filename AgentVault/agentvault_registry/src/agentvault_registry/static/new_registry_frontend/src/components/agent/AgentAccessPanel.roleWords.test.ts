/**
 * V0662 console polish, item 5: the Access panel shows the staker role in the console's words, on its chip and on the
 * picker, while the role keeps its API name: the hover names it and Save sends it. Red on f569f6a6e: "staker" on both.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  authz: { catalog: vi.fn(), get: vi.fn(), denials: vi.fn(), set: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
  deleg: { listGrants: vi.fn(), listCapabilities: vi.fn(), createGrant: vi.fn(), revokeGrant: vi.fn() } as Record<string, ReturnType<typeof vi.fn>>,
}))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: h.authz }))
vi.mock('@/services/api/agentDelegation', () => ({ agentDelegationApi: h.deleg }))

import AgentAccessPanel from './AgentAccessPanel.vue'

const A = 'did:theprotocol:agent-a'
const answer = (roles: string[]) => ({ mode: 'enforce', roles, effective_permissions: [], role_grants: [],
  delegate_enabled: false, spend_policy: null })

describe('the staker role in the console\'s words', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of [...Object.values(h.authz), ...Object.values(h.deleg)]) f.mockReset()
    h.authz.catalog.mockResolvedValue({ assignable_roles: ['trader', 'client', 'staker'], mode: 'enforce', all_permissions: [] })
    h.authz.denials.mockResolvedValue({ denials: [], summary: [] })
    h.deleg.listGrants.mockResolvedValue({ grants: [] })
    h.deleg.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
    h.authz.get.mockResolvedValue(answer(['trader', 'staker']))
  })

  it('the chip and the picker say "locks units", the hover names the role, Save sends "staker"', async () => {
    const w = mount(AgentAccessPanel, { props: { agentDid: A, mode: 'owner' }, global: { stubs: { AgentLineageTree: true } } })
    try {
      await flushPromises()
      const chips = w.findAll('.aap-chips .aap-chip')
      expect(chips.map((c) => c.text().replace(/×$/, '').trim())).toEqual(['trader', 'locks units'])
      expect(chips[1].attributes('title')).toContain('staker')
      const opts = w.findAll('.aap-role-opt')
      expect(opts.map((b) => b.text())).toEqual(['trader', 'client', 'locks units'])
      expect(opts[2].attributes('title')).toContain('staker')
      h.authz.set.mockResolvedValue(answer(['trader', 'staker']))
      await w.find('.aap-actions .aap-btn--primary').trigger('click')
      await flushPromises()
      const body = h.authz.set.mock.calls[h.authz.set.mock.calls.length - 1][1]
      expect(body.roles).toEqual(['trader', 'staker'])
    } finally { w.unmount() }
  })
})
