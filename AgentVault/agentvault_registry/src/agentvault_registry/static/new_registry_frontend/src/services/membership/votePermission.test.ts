import { describe, it, expect } from 'vitest'
import { isVotePermissionRefusal, rolesWithGovernor, votePermissionState } from './votePermission'

/** §MEMBERSHIP phase C (2026-10-02) — may the agent a member acts as vote, and may the console allow it in one press. */
describe('the vote permission', () => {
  it('ok where the agent holds gov.vote, or where the registry does not enforce agent permissions', () => {
    expect(votePermissionState({ mode: 'enforce', effective_permissions: ['gov.vote'] })).toBe('ok')
    expect(votePermissionState({ mode: 'shadow', effective_permissions: [] })).toBe('ok')
  })
  it('grantable without it, unless a role carries a time limit (a full replace would erase it)', () => {
    expect(votePermissionState({ mode: 'enforce', roles: ['trader', 'client'], effective_permissions: ['teg.transfer'],
      role_grants: [{ role: 'trader', expires_at: null }] })).toBe('grantable')
    expect(votePermissionState({ mode: 'enforce', roles: ['trader'], effective_permissions: [],
      role_grants: [{ role: 'trader', expires_at: '2026-12-01T00:00:00Z' }] })).toBe('time_boxed')
  })
  it('adds governor once and keeps every other role', () => {
    expect(rolesWithGovernor(['trader', 'client', 'trader'])).toEqual(['trader', 'client', 'governor'])
    expect(rolesWithGovernor(['governor'])).toEqual(['governor'])
    expect(rolesWithGovernor(null)).toEqual(['governor'])
  })
  it('recognises the IRONKEY refusal of gov.vote and nothing else', () => {
    expect(isVotePermissionRefusal(403, { detail: 'Agent lacks required permission: gov.vote' })).toBe(true)
    expect(isVotePermissionRefusal(403, { detail: 'Agent lacks required permission: teg.transfer' })).toBe(false)
    expect(isVotePermissionRefusal(401, { detail: 'Agent lacks required permission: gov.vote' })).toBe(false)
    expect(isVotePermissionRefusal(403, { error: 'not_a_member' })).toBe(false)
  })
})
