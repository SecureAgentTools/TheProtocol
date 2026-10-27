/**
 * §COCKPITFRAME F5 — the door's REFUSALS, which a browser can only partly reach.
 *
 * The interesting half of this module is what it declines to open. A live desk shows
 * resolvable agents almost all the time, so the branch that matters most — a name that is
 * not a DID, an aggregate id, a webhook label — is the one a browser battery is least
 * likely to encounter. That is the §COCKPITSTOP shape: extract the decision, test it here,
 * and let the browser prove the wiring.
 *
 * 🔴 The bug this guards against is §BRIDGE R9's, exactly: an `aggregate_id` UUID handed
 * onward as a DID, four 404s per page load, and *"Agent card not found"* in front of the
 * Commander.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { openAgent, closeAgent, openDeployment, closeDeployment, isOpenable, useAgentDoor } from '../agentDoor'

describe('cockpit agent door', () => {
  const d = useAgentDoor()
  beforeEach(() => { closeAgent(); closeDeployment() })

  it('opens a real DID and carries the name the caller already had', () => {
    openAgent('did:theprotocol:65f488a8-d8a5-4b1e-9f00-000000000001', 'Ironhand Alpha')
    expect(d.agentDid.value).toBe('did:theprotocol:65f488a8-d8a5-4b1e-9f00-000000000001')
    expect(d.agentName.value).toBe('Ironhand Alpha')
    expect(d.agentOpen.value).toBe(true)
  })

  it('opens a did:cos identity too — seven service agents still carry one', () => {
    openAgent('did:cos:453d4a48-0000-4000-8000-000000000000')
    expect(d.agentOpen.value).toBe(true)
  })

  it.each([
    ['an aggregate id (the §BRIDGE R9 defect)', '9f4c1d2e-3b5a-4c6d-8e7f-0a1b2c3d4e5f'],
    ['a display name', 'Ironhand Alpha'],
    ['a webhook label', 'billing-webhook'],
    ['empty', ''],
    ['null', null],
    ['undefined', undefined],
  ])('refuses %s, leaving nothing open', (_why, v) => {
    openAgent(v as any, 'whatever')
    expect(d.agentDid.value).toBeNull()
    expect(d.agentOpen.value).toBe(false)
  })

  it('isOpenable is the SAME predicate the link renders itself from', () => {
    expect(isOpenable('did:theprotocol:x')).toBe(true)
    expect(isOpenable('theprotocol:x')).toBe(false)
    expect(isOpenable(undefined)).toBe(false)
    // Two implementations of "can this be opened" is how a link and its target disagree.
    openAgent('did:theprotocol:x')
    expect(d.agentOpen.value).toBe(isOpenable('did:theprotocol:x'))
  })

  it('closing really closes — a stale DID left behind would reopen on the next render', () => {
    openAgent('did:theprotocol:abc'); closeAgent()
    expect(d.agentDid.value).toBeNull(); expect(d.agentName.value).toBe('')
  })

  it('a deployment needs BOTH an agent and a row with an id', () => {
    openDeployment('did:theprotocol:abc', { id: 12, status: 'success' })
    expect(d.deploymentOpen.value).toBe(true)
    expect(d.deploymentDid.value).toBe('did:theprotocol:abc')
    closeDeployment()
    openDeployment('did:theprotocol:abc', { status: 'success' })      // no id
    expect(d.deploymentOpen.value).toBe(false)
    openDeployment('', { id: 12 })                                    // no agent
    expect(d.deploymentOpen.value).toBe(false)
  })

  it('id 0 is an id — a falsy-but-present id must not be refused', () => {
    openDeployment('did:theprotocol:abc', { id: 0, status: 'success' })
    expect(d.deploymentOpen.value).toBe(true)
  })

  it('the two dialogs are independent state, so one cannot close the other', () => {
    openAgent('did:theprotocol:abc'); openDeployment('did:theprotocol:abc', { id: 1 })
    closeAgent()
    expect(d.agentOpen.value).toBe(false)
    expect(d.deploymentOpen.value).toBe(true)
  })
})
