/**
 * §FESUITE (V0577): the org Setup Guide reads five things (settings, members, agents, authority grants, treasury) and
 * marked a step "not done" when its read failed, with the step's action: "Create treasury" over a treasury read that
 * failed asked the person to make an account the org may already hold. A step whose read failed now says it could not
 * be read, offers no action and does not count; one Try again reads the guide again.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({ svc: {} as Record<string, ReturnType<typeof vi.fn>> }))
vi.mock('@/services/api/organizationService', () => ({ organizationService: h.svc }))

import OrgSetupChecklist from './OrgSetupChecklist.vue'

function answers(fail: string[] = [], settings: Record<string, unknown> = {}) {
  const said = (key: string, value: unknown) => vi.fn(() => (fail.includes(key) ? Promise.reject(new Error('502')) : Promise.resolve(value)))
  h.svc.getOrgSettings = said('policy', { settings })
  h.svc.listMembers = said('members', [{ id: 1 }])
  h.svc.listOrganizationAgents = said('agents', [])
  h.svc.getOrgAuthorityGrants = said('authority', { grants: [] })
  h.svc.getOrgTreasuryAccount = said('treasury', { exists: false })
  h.svc.createOrgTreasuryAccount = vi.fn()
}

async function guide() {
  const w = mount(OrgSetupChecklist, { props: { orgId: 'org-1', canManage: true } })
  await flushPromises()
  return w
}

describe('the org Setup Guide', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    try { localStorage.clear() } catch { /* storage blocked */ }
  })

  it('with every read answered, a missing step is to-do with its action', async () => {
    answers()
    const w = await guide()
    expect(w.find('[data-testid="osg-treasury"]').attributes('data-unread')).toBeUndefined()
    expect(w.find('[data-testid="osg-create-treasury"]').exists()).toBe(true)
    expect(w.find('[data-testid="osg-retry"]').exists()).toBe(false)
  })

  it('a step whose read failed says so, offers no action and does not count', async () => {
    answers(['treasury', 'members'])
    const w = await guide()
    const treasury = w.find('[data-testid="osg-treasury"]')
    expect(treasury.attributes('data-unread')).toBe('1')
    expect(treasury.text()).toContain('could not be read')
    expect(w.find('[data-testid="osg-create-treasury"]').exists(), 'no "Create treasury" over a failed treasury read').toBe(false)
    expect(w.find('[data-testid="osg-members"]').attributes('data-unread')).toBe('1')
    expect(w.find('[data-testid="osg-agents"]').attributes('data-unread')).toBeUndefined()
    expect(w.find('.osg-progress-label').text()).toBe('0/5')

    // Try again reads the guide again: the reads answer now
    answers()
    await w.find('[data-testid="osg-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="osg-treasury"]').attributes('data-unread')).toBeUndefined()
    expect(w.find('[data-testid="osg-create-treasury"]').exists()).toBe(true)
    expect(w.find('[data-testid="osg-retry"]').exists()).toBe(false)
  })

  // §DOCSFIX D6-486 (2026-10-16): the guardrails step read `require_approval_above`, a key the organization settings
  // catalog does not define (the settings route refuses it), and its text promised an "approval threshold" no org
  // setting holds. It reads the catalog's own knobs; the threshold it names is the liability step-up threshold.
  it('the guardrails step is done by a catalog setting, never by a key the catalog does not hold', async () => {
    answers([], { require_approval_above: 100 })
    let w = await guide()
    expect(w.find('[data-testid="osg-policy"]').classes()).not.toContain('osg-step--done')
    expect(w.find('[data-testid="osg-policy"]').text()).not.toContain('approval threshold')

    answers([], { liability: { presence_threshold_avt: 50 } })
    w = await guide()
    expect(w.find('[data-testid="osg-policy"]').classes()).toContain('osg-step--done')
  })
})
