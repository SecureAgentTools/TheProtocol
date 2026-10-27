/**
 * services/membership/votePermission.ts — §MEMBERSHIP phase C (2026-10-02): may the agent a member acts as cast a vote?
 *
 * A member's vote is cast by one of their agents, and under IRONKEY enforce the vote route asks the agent for the
 * permission `gov.vote` before any membership rule runs (security.require_agent_permission). Only the `governor` role
 * carries it (legacy-full aside); a newborn agent holds `trader,client` (+`staker`). So a member's first vote with a
 * young agent is refused 403 "Agent lacks required permission: gov.vote", which is not "you are not a member".
 *
 * The owner can allow it alone by adding `governor` (PUT /agents/{did}/authz), which also grants gov.propose and
 * exchange.vote. The additive rail (POST /agents/{did}/authz/roles, agentvault2-33's authz-role-add) grants that one
 * role and leaves every other grant as it is. ⚠ On an image without it, the only write is the whole-set PUT, which
 * REPLACES every role and stamps all of them with the call's expiry: there the console never writes over a time-boxed
 * role and sends the owner to My Agents, where the limits are visible (composables/useVotePermission.ts).
 */

export const VOTE_PERMISSION = 'gov.vote'
export const VOTE_ROLE = 'governor'

export interface AuthzLike {
  roles?: string[] | null
  effective_permissions?: string[] | null
  role_grants?: { role: string; expires_at: string | null }[] | null
  mode?: string | null
}

/**
 *   ok          the agent may vote (or the registry does not enforce agent permissions)
 *   grantable   it may not; adding `governor` touches nothing else (no role carries a time limit)
 *   time_boxed  it may not, and a role carries a time limit: only the additive rail may add governor here
 */
export type VotePermissionState = 'ok' | 'grantable' | 'time_boxed'

export function votePermissionState(a: AuthzLike | null | undefined): VotePermissionState {
  if (!a) return 'grantable'
  if (a.mode && a.mode !== 'enforce') return 'ok'
  if ((a.effective_permissions || []).includes(VOTE_PERMISSION)) return 'ok'
  if ((a.role_grants || []).some((g) => !!g?.expires_at)) return 'time_boxed'
  return 'grantable'
}

/** The roles to send: the agent's own, plus `governor` once. */
export function rolesWithGovernor(roles: string[] | null | undefined): string[] {
  const out = [...new Set((roles || []).filter(Boolean))]
  if (!out.includes(VOTE_ROLE)) out.push(VOTE_ROLE)
  return out
}

/** A vote refused for the agent's missing permission (the IRONKEY 403), as opposed to any other 403. */
export function isVotePermissionRefusal(status: number | undefined, body: unknown): boolean {
  if (status !== 403 || !body || typeof body !== 'object') return false
  const b = body as Record<string, unknown>
  const text = [b.detail, b.message, b.title].filter((x) => typeof x === 'string').join(' ')
  return /lacks required permission:?\s*gov\.vote\b/i.test(text)
}
