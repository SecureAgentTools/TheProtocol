import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'

/**
 * §FESUITE 135 (agentvault2-5b, 2026-10-15): selecting an organization switches the header at once and then reads its
 * teams and members. Picking A, then B before A's lists came back let A's lists land last: B's header over A's teams and
 * members, and B's member and team counts rewritten from A's lists. The latest call owns each list now, and the counts
 * are taken only while the organization they are for is still the one picked. Fails on the unguarded store.
 */
type Pending = { resolve: (v: unknown) => void }
const h = vi.hoisted(() => ({ pending: {} as Record<string, Pending> }))
function held(name: string, orgId: string): Promise<unknown> {
  return new Promise((resolve) => { h.pending[`${name}:${orgId}`] = { resolve } })
}
async function answer(key: string, value: unknown) {
  const p = h.pending[key]
  if (!p) throw new Error(`no read in flight for ${key}`)
  delete h.pending[key]
  p.resolve(value)
  await flushPromises()
}
vi.mock('@/services/api/organizationService', () => ({
  organizationService: {
    listTeams: (oid: string) => held('teams', oid),
    listMembers: (oid: string) => held('members', oid),
  },
}))
vi.mock('./ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showWarning: vi.fn(), showError: vi.fn() }) }))
vi.mock('./auth', () => ({ useAuthStore: () => ({ user: { id: 7 } }) }))

import { useOrganizationStore } from './organizations'

describe('selecting an organization', () => {
  it("A's teams and members, answering after B's, never become B's, and B's counts are B's own", async () => {
    setActivePinia(createPinia())
    const s = useOrganizationStore()
    const A = { id: 'org-a', name: 'Alder Freight', member_count: 0, team_count: 0 }
    const B = { id: 'org-b', name: 'Birch Ledger', member_count: 0, team_count: 0 }
    s.organizations = [A, B] as any
    const pickA = s.selectOrganization('org-a')
    const pickB = s.selectOrganization('org-b')
    await answer('teams:org-b', [{ id: 'tb1' }])
    await answer('members:org-b', [{ developer_id: 1 }, { developer_id: 2 }, { developer_id: 3 }])
    await answer('teams:org-a', [{ id: 'ta1' }, { id: 'ta2' }])
    await answer('members:org-a', [{ developer_id: 9 }])
    await Promise.all([pickA, pickB])
    expect(s.currentOrganization?.id).toBe('org-b')
    expect(s.teams.map((t: any) => t.id)).toEqual(['tb1'])
    expect(s.members.map((m: any) => m.developer_id)).toEqual([1, 2, 3])
    expect(s.currentOrganization?.member_count).toBe(3)
    expect(s.currentOrganization?.team_count).toBe(1)
    expect(s.isLoadingTeams || s.isLoadingMembers, 'the latest reads ended the loading state').toBe(false)
  })

  it("A's lists, already read, do not stand under B's header while B's are read", async () => {
    setActivePinia(createPinia())
    const s = useOrganizationStore()
    s.organizations = [{ id: 'org-a', name: 'Alder Freight' }, { id: 'org-b', name: 'Birch Ledger' }] as any
    const pickA = s.selectOrganization('org-a')
    await answer('teams:org-a', [{ id: 'ta1' }])
    await answer('members:org-a', [{ developer_id: 9 }])
    await pickA
    expect(s.teams.map((t: any) => t.id)).toEqual(['ta1'])
    const pickB = s.selectOrganization('org-b')
    expect(s.currentOrganization?.id).toBe('org-b')
    expect(s.teams, "A's teams under B's header").toEqual([])
    expect(s.members, "A's members under B's header").toEqual([])
    await answer('teams:org-b', [{ id: 'tb1' }])
    await answer('members:org-b', [{ developer_id: 1 }])
    await pickB
    expect(s.teams.map((t: any) => t.id)).toEqual(['tb1'])
  })
})
