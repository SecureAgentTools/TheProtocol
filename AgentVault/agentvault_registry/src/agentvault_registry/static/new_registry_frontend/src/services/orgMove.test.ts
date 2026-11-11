/**
 * V0658 (s) (the maintainer's report, sessions' room seq 2150): an agent belongs to one organization, and assigning it
 * to a second one silently took it out of the first. The registry now refuses that move with a 409 naming the
 * organization the agent is in (AGENT_IN_ANOTHER_ORGANIZATION, its id and name in the error's context) and makes it only
 * when the request names the organization it leaves. organizationLeft reads that refusal, and nothing else, so a console
 * asks before it sends the confirming request. RED on 553347408: the module does not exist.
 *
 * The second review (session-lead, sessions' room seq 2361): an accept's administrator is told the organization only
 * when it is listed or they are a member of it. Otherwise the refusal names neither its id nor its name, says where the
 * agent is in its own words (current_organization.label, "another organization, not listed") and hands out an opaque
 * reference (error.context.confirm_value). The console shows the words the refusal gives and confirms with what it
 * hands out. RED on f3b3ed22d: the refusal that names nothing was not a question, and the confirmation sent the id.
 */
import { describe, expect, it } from 'vitest'
import { AGENT_IN_ANOTHER_ORGANIZATION, organizationLeft, leaveBody } from './orgMove'

function refused(status: number, error: Record<string, unknown>) {
  return { isAxiosError: true, response: { status, data: { detail: 'refused', error } } }
}

describe('organizationLeft: the organization a refused move names', () => {
  it('reads the id and the name from the 409, and confirms with the id it hands out', () => {
    const e = refused(409, { code: AGENT_IN_ANOTHER_ORGANIZATION,
      context: { current_organization: { id: 'org-a', name: 'Alder Freight' }, confirm_value: 'org-a' } })
    expect(organizationLeft(e)).toEqual({ id: 'org-a', name: 'Alder Freight', named: true, confirm: 'org-a' })
  })

  it('names the organization by its id when the answer carries no name', () => {
    const e = refused(409, { code: AGENT_IN_ANOTHER_ORGANIZATION, context: { current_organization: { id: 'org-a', name: null } } })
    expect(organizationLeft(e)).toEqual({ id: 'org-a', name: 'org-a', named: true, confirm: 'org-a' })
  })

  it('an organization the registry does not name: its words stand for it, and what it hands out confirms', () => {
    const e = refused(409, { code: AGENT_IN_ANOTHER_ORGANIZATION, context: {
      current_organization: { id: null, name: null, label: 'words the registry chose' },
      confirm_with: 'leave_organization_id', confirm_value: 'olr_opaque' } })
    expect(organizationLeft(e)).toEqual({ id: null, name: 'words the registry chose', named: false, confirm: 'olr_opaque' })
  })

  it('confirms with what the refusal hands out, before the id', () => {
    const e = refused(409, { code: AGENT_IN_ANOTHER_ORGANIZATION,
      context: { current_organization: { id: 'org-a', name: 'Alder Freight' }, confirm_value: 'handed-out' } })
    expect(organizationLeft(e)?.confirm).toBe('handed-out')
  })

  it('is null for every other failure: another 409, another status, no answer, no organization', () => {
    expect(organizationLeft(refused(409, { code: 'CONFLICT' })), 'the agent limit is another 409').toBeNull()
    expect(organizationLeft(refused(422, { code: AGENT_IN_ANOTHER_ORGANIZATION,
      context: { current_organization: { id: 'org-a', name: 'Alder Freight' } } }))).toBeNull()
    expect(organizationLeft({ isAxiosError: true })).toBeNull()
    expect(organizationLeft(new Error('Network Error'))).toBeNull()
    expect(organizationLeft(refused(409, { code: AGENT_IN_ANOTHER_ORGANIZATION, context: {} }))).toBeNull()
    expect(organizationLeft(null)).toBeNull()
  })

  it('is null for a refusal that names nothing and hands out nothing, or gives no words to ask with', () => {
    expect(organizationLeft(refused(409, { code: AGENT_IN_ANOTHER_ORGANIZATION, context: {
      current_organization: { id: null, name: null, label: 'another organization, not listed' } } }))).toBeNull()
    expect(organizationLeft(refused(409, { code: AGENT_IN_ANOTHER_ORGANIZATION, context: {
      current_organization: { id: null, name: null }, confirm_value: 'olr_opaque' } }))).toBeNull()
  })
})

describe('leaveBody: the confirming request sends what the refusal handed out', () => {
  it('the id, for an organization it named', () => {
    expect(leaveBody({ id: 'org-a', name: 'Alder Freight', named: true, confirm: 'org-a' }))
      .toEqual({ leave_organization_id: 'org-a' })
  })

  it('the reference, for one it did not name', () => {
    expect(leaveBody({ id: null, name: 'another organization, not listed', named: false, confirm: 'olr_opaque' }))
      .toEqual({ leave_organization_id: 'olr_opaque' })
  })
})
