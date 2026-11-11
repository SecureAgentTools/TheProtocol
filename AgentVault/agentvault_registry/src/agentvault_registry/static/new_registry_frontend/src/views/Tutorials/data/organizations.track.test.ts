/**
 * V0658 (s): the Organizations tutorial makes its agent at step 3 and assigns it to the organization it makes at step 4.
 * The registry puts a new agent in its developer's organization when that developer belongs to exactly one (the shared
 * tutorial account does after one earlier run), so the assign at step 7 is a move, and an agent belongs to one
 * organization: the registry refuses a move the request does not confirm (409, naming the organization) and the
 * tutorial stopped there. Step 3 now keeps the organization the answer names (null when none) and step 7 names it as
 * the one the agent leaves, in the request the step shows before it is sent, and both steps say so.
 * RED on 553347408: nothing was kept and nothing named.
 */
import { describe, expect, it } from 'vitest'
import { organizationsTrack } from './organizations.track'

const step = (id: string) => {
  const s = organizationsTrack.steps.find((x) => x.id === id)
  if (!s) throw new Error(`no step ${id}`)
  return s
}

describe('the Organizations tutorial moves its agent only by naming the organization it leaves', () => {
  it('step 3 keeps the organization the new agent was put in, before the step that names it', () => {
    const created = step('create-agent')
    const kept = (created.captures ?? []).find((c) => c.responsePath === 'organization_id')
    expect(kept?.key).toBe('orgAgentHomeOrgId')
    const ids = organizationsTrack.steps.map((s) => s.id)
    expect(ids.indexOf('create-agent')).toBeLessThan(ids.indexOf('assign-agent'))
  })

  it('step 7 names it as the organization the agent leaves, in the body it shows', () => {
    const assign = step('assign-agent')
    expect(assign.apiCall.body).toEqual({ team_id: '$teamId', leave_organization_id: '$orgAgentHomeOrgId' })
    expect(assign.explanation).toMatch(/belongs to one organization/)
    expect(assign.explanation).toMatch(/leave_organization_id/)
    expect(step('create-agent').explanation, 'step 3 says where the new agent may already be').toMatch(/exactly one/)
  })
})
