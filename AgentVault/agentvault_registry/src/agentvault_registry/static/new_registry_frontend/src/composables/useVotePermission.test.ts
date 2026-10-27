import { describe, it, expect, vi, beforeEach } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'

/**
 * §MEMBERSHIP phase C (2026-10-02) — replies count in the order they were asked: a check that read the agent's roles
 * before the press wrote them must not land after the press and put "not allowed yet" back. Seen in the browser pass
 * as a press that "never settled" (the notice read grantable again) on a busy sandbox.
 */
const h = vi.hoisted(() => ({ get: vi.fn(), set: vi.fn(), addRole: vi.fn() }))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: { get: h.get, set: h.set, addRole: h.addRole } }))

import { useVotePermission } from './useVotePermission'

const ENFORCE = { agent_did: 'did:a', mode: 'enforce', roles: ['trader', 'client'], effective_permissions: ['teg.transfer'],
  role_grants: [{ role: 'trader', expires_at: null }, { role: 'client', expires_at: null }] }
const ALLOWED = { ...ENFORCE, roles: ['trader', 'client', 'governor'], effective_permissions: ['teg.transfer', 'gov.vote'] }
function deferred<T>() { let resolve!: (v: T) => void; const promise = new Promise<T>((r) => { resolve = r }); return { promise, resolve } }

beforeEach(() => { h.get.mockReset(); h.set.mockReset(); h.addRole.mockReset() })

describe('the vote permission, asked and answered in order', () => {
  it('a check asked before the press settled cannot overwrite the press with what it read before the write', async () => {
    const did = ref('did:a')
    const vp = effectScope().run(() => useVotePermission(did))!
    h.get.mockResolvedValueOnce(ENFORCE)
    await vp.check()
    expect(vp.state.value).toBe('grantable')

    const stale = deferred<typeof ENFORCE>()
    h.addRole.mockResolvedValue(null)                 // an image without the rail: the PUT path
    h.get.mockResolvedValueOnce(ENFORCE)              // the press's read before writing
      .mockReturnValueOnce(stale.promise)             // a check asked mid-press, answered late with the old roles
      .mockResolvedValueOnce(ALLOWED)                 // the press's read after writing
    h.set.mockResolvedValue({})
    const pressing = vp.allow()
    await nextTick(); await Promise.resolve()
    const checking = vp.check()                       // e.g. the acting agent was set again
    const ok = await pressing
    expect(ok).toBe(true)
    expect(vp.state.value).toBe('ok')
    stale.resolve(ENFORCE)                            // the late, stale answer arrives
    await checking
    expect(vp.state.value).toBe('ok')                 // not "grantable" again
  })

  it('control: a check asked after the press settled is applied', async () => {
    const did = ref('did:a')
    const vp = effectScope().run(() => useVotePermission(did))!
    h.addRole.mockResolvedValue({ agent_did: 'did:a', role: 'governor', changed: true, roles: ALLOWED.roles, effective_permissions: ALLOWED.effective_permissions })
    expect(await vp.allow()).toBe(true)
    h.get.mockResolvedValueOnce(ENFORCE)              // the role was taken away elsewhere since
    await vp.check()
    expect(vp.state.value).toBe('grantable')
  })

  it('a press made for one agent does not report "allowed" once another agent acts', async () => {
    const did = ref('did:a')
    const vp = effectScope().run(() => useVotePermission(did))!
    const late = deferred<any>()
    h.addRole.mockReturnValue(late.promise)
    const pressing = vp.allow()
    did.value = 'did:b'
    late.resolve({ agent_did: 'did:a', role: 'governor', changed: true, roles: ALLOWED.roles, effective_permissions: ALLOWED.effective_permissions })
    expect(await pressing).toBe(false)
    expect(vp.state.value).not.toBe('ok')
  })
})
