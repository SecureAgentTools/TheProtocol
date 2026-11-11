/**
 * V0658 (s) (the maintainer's report, sessions' room seq 2150): accepting a join request brings the agent in exactly as
 * its owner's assign would, and an agent belongs to one organization, so accepting the request of an agent that is in
 * another organization took it out of that one without a word. The registry refuses that accept (409,
 * AGENT_IN_ANOTHER_ORGANIZATION, naming the organization); the panel names that organization, asks, and only then sends
 * the accept that names the organization the agent leaves. Cancelling sends nothing. A name is shown as text, never as
 * markup. RED on 553347408: the refusal ended in an error notice and nothing asked.
 *
 * The second review (session-lead, sessions' room seq 2361): the administrator who accepts belongs to the receiving
 * organization, and the registry names the organization the agent is in to them only when it is listed or they are a
 * member of it. Otherwise its refusal names neither its id nor its name: the panel asks in the registry's words
 * ("another organization, not listed") and confirms with the reference the refusal hands out. RED on f3b3ed22d: that
 * refusal ended in an error notice and nothing asked.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  listAgentRequests: vi.fn(), decideAgentRequest: vi.fn(), createAgentRequest: vi.fn(), withdrawAgentRequest: vi.fn(),
  showError: vi.fn(), showSuccess: vi.fn(),
}))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: {
    listAgentRequests: h.listAgentRequests, decideAgentRequest: h.decideAgentRequest,
    createAgentRequest: h.createAgentRequest, withdrawAgentRequest: h.withdrawAgentRequest,
  },
}))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError, showSuccess: h.showSuccess }) }))

import OrgAgentRequests from './OrgAgentRequests.vue'

const req = { id: 'oar_1', organization_id: 'org-b', agent_did: 'did:theprotocol:eu:agent-1', agent_name: 'session-docs',
  requested_by_kind: 'agent', requested_by_ref: 'did:theprotocol:eu:agent-1', status: 'pending', note: null }

function moveRefused(id: string, name: string) {
  return Object.assign(new Error('Request failed with status code 409'), {
    isAxiosError: true,
    response: { status: 409, data: {
      detail: `The agent is in the organization ${name} (id ${id}).`,
      error: { code: 'AGENT_IN_ANOTHER_ORGANIZATION', context: { current_organization: { id, name } } },
    } },
  })
}

/** the refusal for an organization the registry does not name to this administrator: its words and a reference */
function unnamedRefused(reference: string, label = 'another organization, not listed') {
  const detail = `The agent is in ${label}. An agent belongs to one organization, so bringing it into this one would `
    + `take it out of that organization; nothing was changed. To move it, send leave_organization_id ${reference} with `
    + 'the request.'
  return Object.assign(new Error('Request failed with status code 409'), {
    isAxiosError: true,
    response: { status: 409, data: { detail, error: { code: 'AGENT_IN_ANOTHER_ORGANIZATION', detail, context: {
      current_organization: { id: null, name: null, label },
      confirm_with: 'leave_organization_id', confirm_value: reference } } } },
  })
}

const dialog = (w: VueWrapper) => w.find('.ca-modal[role="dialog"]')
const confirmButton = (w: VueWrapper) => dialog(w).find('.ca-modal-footer .ca-btn:not(.ca-btn--ghost)')

async function panel(): Promise<VueWrapper> {
  h.listAgentRequests.mockResolvedValue({ items: [req], can_decide: true })
  const w = mount(OrgAgentRequests, { props: { orgId: 'org-b', myAgents: [] },
    global: { stubs: { Teleport: true, teleport: true, Icon: true } } })
  await flushPromises()
  return w
}

describe('accepting the join request of an agent in another organization', () => {
  beforeEach(() => {
    Object.values(h).forEach((f) => f.mockReset())
  })

  it('names the organization it leaves, asks, and accepts only once confirmed', async () => {
    const w = await panel()
    h.decideAgentRequest.mockRejectedValueOnce(moveRefused('org-a', 'Alder Freight'))
    await w.find('[data-testid="org-agent-request-accept"]').trigger('click')
    await flushPromises()
    expect(dialog(w).exists(), 'the panel asks before the agent leaves Alder Freight').toBe(true)
    expect(dialog(w).find('[data-testid="org-move-from"]').text()).toBe('Alder Freight')
    expect(h.showError, 'a question, not an error').not.toHaveBeenCalled()
    expect(w.emitted('joined'), 'nothing joined yet').toBeUndefined()
    expect(h.decideAgentRequest).toHaveBeenCalledTimes(1)
    expect(h.decideAgentRequest).toHaveBeenCalledWith('org-b', 'oar_1', 'accept')

    h.decideAgentRequest.mockResolvedValueOnce({ id: 'oar_1', status: 'accepted', agent_did: req.agent_did })
    h.listAgentRequests.mockResolvedValue({ items: [], can_decide: true })
    await confirmButton(w).trigger('click')
    await flushPromises()
    expect(h.decideAgentRequest).toHaveBeenLastCalledWith('org-b', 'oar_1', 'accept', { leave_organization_id: 'org-a' })
    expect(w.emitted('joined')![0]).toEqual([req.agent_did])
    expect(dialog(w).exists(), 'the question closes once it is answered').toBe(false)
  })

  it('cancelling sends nothing and the request stays', async () => {
    const w = await panel()
    h.decideAgentRequest.mockRejectedValueOnce(moveRefused('org-a', 'Alder Freight'))
    await w.find('[data-testid="org-agent-request-accept"]').trigger('click')
    await flushPromises()
    await dialog(w).find('.ca-btn--ghost').trigger('click')
    await flushPromises()
    expect(dialog(w).exists()).toBe(false)
    expect(h.decideAgentRequest).toHaveBeenCalledTimes(1)
    expect(w.emitted('joined')).toBeUndefined()
    expect(w.find('[data-testid="org-agent-request"]').exists(), 'the request is still open').toBe(true)
  })

  it('asks again, naming where the agent is now, when it moved before the confirmation', async () => {
    const w = await panel()
    h.decideAgentRequest
      .mockRejectedValueOnce(moveRefused('org-a', 'Alder Freight'))
      .mockRejectedValueOnce(moveRefused('org-c', 'Cedar Works'))
    await w.find('[data-testid="org-agent-request-accept"]').trigger('click')
    await flushPromises()
    await confirmButton(w).trigger('click')
    await flushPromises()
    expect(dialog(w).find('[data-testid="org-move-from"]').text()).toBe('Cedar Works')
    expect(w.emitted('joined')).toBeUndefined()
    expect(h.showError).not.toHaveBeenCalled()
  })

  it('an organization the registry does not name: it asks in the registry\'s words and confirms with the reference', async () => {
    const w = await panel()
    h.decideAgentRequest.mockRejectedValueOnce(unnamedRefused('olr_9f2c41d0'))
    await w.find('[data-testid="org-agent-request-accept"]').trigger('click')
    await flushPromises()
    expect(dialog(w).exists(), 'the panel asks, though the registry named nothing').toBe(true)
    expect(h.showError, 'a question, not an error').not.toHaveBeenCalled()
    expect(dialog(w).find('[data-testid="org-move-from"]').text()).toBe('another organization, not listed')
    expect(dialog(w).text()).toContain('session-docs is in another organization, not listed.')
    expect(dialog(w).text(), 'the words are where the agent is, not a name').not.toContain('the organization another')

    h.decideAgentRequest.mockResolvedValueOnce({ id: 'oar_1', status: 'accepted', agent_did: req.agent_did,
      left_organization_id: null, left_organization_ref: 'olr_9f2c41d0' })
    h.listAgentRequests.mockResolvedValue({ items: [], can_decide: true })
    await confirmButton(w).trigger('click')
    await flushPromises()
    expect(h.decideAgentRequest, 'the confirmation sends what the refusal handed out')
      .toHaveBeenLastCalledWith('org-b', 'oar_1', 'accept', { leave_organization_id: 'olr_9f2c41d0' })
    expect(w.emitted('joined')![0]).toEqual([req.agent_did])
    expect(dialog(w).exists(), 'the question closes once it is answered').toBe(false)
  })

  it('shows a name carrying markup as text', async () => {
    const w = await panel()
    h.decideAgentRequest.mockRejectedValueOnce(moveRefused('org-a', '<img src=x onerror=alert(1)>Alder'))
    await w.find('[data-testid="org-agent-request-accept"]').trigger('click')
    await flushPromises()
    expect(dialog(w).find('img').exists()).toBe(false)
    expect(dialog(w).find('[data-testid="org-move-from"]').text()).toBe('<img src=x onerror=alert(1)>Alder')
  })

  it('a decline, and any other refusal, are as before', async () => {
    const w = await panel()
    h.decideAgentRequest.mockResolvedValueOnce({ id: 'oar_1', status: 'declined', agent_did: req.agent_did })
    await w.find('[data-testid="org-agent-request-decline"]').trigger('click')
    await flushPromises()
    expect(h.decideAgentRequest).toHaveBeenCalledWith('org-b', 'oar_1', 'decline')
    expect(dialog(w).exists()).toBe(false)

    h.listAgentRequests.mockResolvedValue({ items: [req], can_decide: true })
    await (w.vm as any).load()
    await flushPromises()
    h.decideAgentRequest.mockRejectedValueOnce(Object.assign(new Error('409'), { isAxiosError: true,
      response: { status: 409, data: { detail: 'Organization agent limit reached (100/100)', error: { code: 'CONFLICT' } } } }))
    await w.find('[data-testid="org-agent-request-accept"]').trigger('click')
    await flushPromises()
    expect(dialog(w).exists(), 'the limit is not a move').toBe(false)
    expect(h.showError).toHaveBeenCalledWith('The request was not decided', 'Organization agent limit reached (100/100)')
  })
})
