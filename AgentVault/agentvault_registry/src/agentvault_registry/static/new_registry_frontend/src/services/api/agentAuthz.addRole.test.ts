import { describe, it, expect, vi, beforeEach } from 'vitest'

const h = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { post: h.post } }))

import { agentAuthzApi } from './agentAuthz'

/**
 * §MEMBERSHIP phase C (2026-10-02) — the additive role rail (POST /agents/{did}/authz/roles, agentvault2-33's
 * authz-role-add): one role added, every other grant as it is. A registry without the rail answers 405 or the router's
 * own 404 "Not Found", and only those read as "no rail"; the rail's own refusals (an unknown agent is a 404 too) throw.
 */
function refused(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } })
}

beforeEach(() => { h.post.mockReset() })

describe('agentAuthzApi.addRole', () => {
  it('posts one role with no time limit to the agent\'s own address and returns the answer', async () => {
    const answer = { agent_did: 'did:theprotocol:a', role: 'governor', changed: true, roles: ['trader', 'governor'], effective_permissions: ['gov.vote'] }
    h.post.mockResolvedValue({ data: answer })
    expect(await agentAuthzApi.addRole('did:theprotocol:a', 'governor')).toEqual(answer)
    const [url, body, cfg] = h.post.mock.calls[0]
    expect(url).toBe('/agents/did%3Atheprotocol%3Aa/authz/roles')
    expect(body).toEqual({ role: 'governor', expires_at: null })
    expect(cfg.expectedStatuses).toEqual([404, 405])
  })

  it('a registry without the rail is "no rail" (null): a 405, or the router\'s own 404', async () => {
    h.post.mockRejectedValueOnce(refused(405, 'Method Not Allowed')).mockRejectedValueOnce(refused(404, 'Not Found'))
    expect(await agentAuthzApi.addRole('did:a', 'governor')).toBeNull()
    expect(await agentAuthzApi.addRole('did:a', 'governor')).toBeNull()
  })

  it('control: the rail\'s own refusals throw, a 404 for an unknown agent among them', async () => {
    h.post.mockRejectedValueOnce(refused(404, 'Agent not found')).mockRejectedValueOnce(refused(403, 'Not your agent'))
      .mockRejectedValueOnce(refused(422, 'Unknown role'))
    await expect(agentAuthzApi.addRole('did:a', 'governor')).rejects.toThrow('HTTP 404')
    await expect(agentAuthzApi.addRole('did:a', 'governor')).rejects.toThrow('HTTP 403')
    await expect(agentAuthzApi.addRole('did:a', 'governor')).rejects.toThrow('HTTP 422')
  })
})
