import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE V0595 (a console gap, his word 2026-10-11 "also close console gaps"): the Invitations tab existed only where
 * registration needs a code, so on an open registry (both sandbox frames, EU, ASIA) an admin could mint no code from the
 * console. The tab shows to every admin now; where registration is open the panel says what a code is worth there
 * (asked for nowhere, granting nothing until invite-only is on) instead of the invite-only registry's sentence.
 */
const api = vi.hoisted(() => ({ list: vi.fn() }))
vi.mock('@/services/api/inviteCodes', () => ({
  listInviteCodes: api.list, generateInviteCodes: vi.fn(), revokeInviteCode: vi.fn(),
  ADMIN_FLAGS: [], flagLabel: (f: string) => f,
}))

import InvitationsPanel from './InvitationsPanel.vue'

async function panel(openRegistration?: boolean) {
  const w = mount(InvitationsPanel, {
    props: openRegistration === undefined ? {} : { openRegistration },
    global: { stubs: { Icon: true, ConfirmActionModal: true } },
  })
  await flushPromises()
  return w
}

describe('the invitations panel on an open registry', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.list.mockReset().mockResolvedValue([])
  })

  it('says a code grants nothing where registration is open, never "the only way in"', async () => {
    const w = await panel(true)
    expect(w.find('[data-testid="iv-open-registration"]').text()).toMatch(/registration on this registry is open/i)
    expect(w.text(), 'the invite-only sentence on an open registry').not.toMatch(/requires an invite code|only way in/)
    expect(w.find('[data-testid="iv-mint"]').exists(), 'minting stays offered').toBe(true)
  })

  it('an invite-only registry keeps its sentence', async () => {
    const w = await panel()
    expect(w.find('[data-testid="iv-open-registration"]').exists()).toBe(false)
    expect(w.text()).toMatch(/requires an invite code/)
  })
})
