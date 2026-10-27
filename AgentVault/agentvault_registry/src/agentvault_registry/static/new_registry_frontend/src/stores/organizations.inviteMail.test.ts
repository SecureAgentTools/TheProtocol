import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE (V0594): inviting a member said "An invitation has been sent to X" whatever the registry's send did (named at
 * V0592: the invite rail discarded whether its mail was sent). The registry now answers mail_sent; a mail that was not
 * sent is a warning that says the invited person cannot accept without it, and what to do. An older registry that does
 * not say keeps the old sentence (it cannot be told).
 */
const api = vi.hoisted(() => ({ inviteMember: vi.fn(), listMembers: vi.fn(async () => []) }))
const ui = vi.hoisted(() => ({ showSuccess: vi.fn(), showWarning: vi.fn(), showError: vi.fn() }))
vi.mock('@/services/api/organizationService', () => ({ organizationService: { inviteMember: api.inviteMember, listMembers: api.listMembers } }))
vi.mock('./ui', () => ({ useUIStore: () => ui }))
vi.mock('./auth', () => ({ useAuthStore: () => ({ user: { id: 7 } }) }))

import { useOrganizationStore } from './organizations'

const INV = { id: 'inv-1', organization_id: 'org-1', email: 'm@example.com', role: 'member', token: 't', invited_by: 7, created_at: '', expires_at: '', is_active: true }

async function invite(answer: Record<string, unknown>) {
  const s = useOrganizationStore()
  s.currentOrganization = { id: 'org-1', name: 'Hansa Works' } as any
  api.inviteMember.mockResolvedValueOnce({ ...INV, ...answer })
  await s.inviteMember({ email: 'm@example.com', role: 'member' } as any)
}

describe('an invitation says what happened to its mail', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.inviteMember.mockReset(); ui.showSuccess.mockReset(); ui.showWarning.mockReset(); ui.showError.mockReset()
  })

  it('a mail that was not sent is never called sent', async () => {
    await invite({ mail_sent: false })
    expect(ui.showSuccess, 'said "an invitation has been sent" for a mail that was not').not.toHaveBeenCalled()
    expect(ui.showWarning).toHaveBeenCalledTimes(1)
    expect(String(ui.showWarning.mock.calls[0][1])).toMatch(/could not be sent.*cannot accept/i)
  })

  it('a sent mail says sent', async () => {
    await invite({ mail_sent: true })
    expect(ui.showSuccess).toHaveBeenCalledWith('Invitation sent', 'An invitation has been sent to m@example.com')
    expect(ui.showWarning).not.toHaveBeenCalled()
  })

  it('an older registry that does not say keeps the old sentence', async () => {
    await invite({})
    expect(ui.showSuccess).toHaveBeenCalledTimes(1)
    expect(ui.showWarning).not.toHaveBeenCalled()
  })
})
