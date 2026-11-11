/**
 * services/orgMove.ts — V0658 (s) (the maintainer's report, sessions' room seq 2150): an agent belongs to one
 * organization (agents.organization_id), and bringing it into another organization takes it out of the one it is in.
 * The registry makes that move only when the request names the organization the agent leaves (leave_organization_id);
 * otherwise it answers 409 AGENT_IN_ANOTHER_ORGANIZATION with that organization in error.context.current_organization.
 * A console reads the refusal here, names the organization, asks, and only then sends the confirming request. Pure (no
 * store, no router), so it is unit-tested.
 *
 * The second review (session-lead, sessions' room seq 2361): an accept is decided by an administrator of the receiving
 * organization, and an organization that is not listed has not agreed to be named to them. The registry names it there
 * only when it is listed or the administrator is a member of it; otherwise the refusal carries neither its id nor its
 * name, says where the agent is in its own words (current_organization.label, "another organization, not listed") and
 * hands out an opaque reference. Either way the console shows the words the refusal gives and confirms with what it
 * hands out (error.context.confirm_value).
 */

export const AGENT_IN_ANOTHER_ORGANIZATION = 'AGENT_IN_ANOTHER_ORGANIZATION'

/** The organization a move takes the agent out of, as the refusal gives it. */
export interface LeftOrganization {
  /** its id, when the refusal names it; null when it does not */
  id: string | null
  /** how the question names it: its name (its id when the registry gave none), or the registry's own words for an
   *  organization it does not name to this caller */
  name: string
  /** false when the registry did not name it: the question then says the registry's words, not "the organization ..." */
  named: boolean
  /** what the confirming request sends as leave_organization_id: what the refusal handed out (the organization's id,
   *  or the reference for one it does not name); the id when an answer handed out nothing else */
  confirm: string
}

const text = (value: unknown): string => (typeof value === 'string' ? value.trim() : '')

/** The organization a refused move names, or null for any other failure (another 409, another status, no answer). */
export function organizationLeft(error: unknown): LeftOrganization | null {
  const response = (error as any)?.response
  if (!response || response.status !== 409) return null
  const e = response.data?.error
  if (!e || e.code !== AGENT_IN_ANOTHER_ORGANIZATION) return null
  const context = e.context || {}
  const current = context.current_organization
  const handed = text(context.confirm_value)
  const id = text(current?.id)
  if (id) return { id, name: text(current?.name) || id, named: true, confirm: handed || id }
  // not named to this caller: the registry's words stand for it and its reference confirms, or there is nothing to ask
  const words = text(current?.label)
  if (!words || !handed) return null
  return { id: null, name: words, named: false, confirm: handed }
}

/** The body of the confirming request: what the refusal handed out, so a stale answer moves nothing. */
export function leaveBody(left: LeftOrganization): { leave_organization_id: string } {
  return { leave_organization_id: left.confirm }
}
