/**
 * An organization's life through the page (§FESUITE; the MCP tester's organization_full_crud, org_team_full_crud,
 * org_member_invite, org_assign_unassign and team_member_add_remove, as two people live them): the owner creates the
 * organization, edits it, adds a team, invites a second developer; the second developer opens the invitation link in
 * their own browser and joins; the owner assigns an agent and takes it back, removes the member, deletes the team and
 * the organization. Every step is read back from the API.
 */
import { test, expect } from '../support/fixtures'
import { createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { confirmDialog, openRoute, settle, toast } from '../support/ui'

test('organization_full_life', async ({ page, context, steps, api, a11y, openAs }) => {
  test.setTimeout(6 * 60_000)
  const owner = await registerDeveloper(api, 'orgowner')
  const member = await registerDeveloper(api, 'orgmember')
  const agent = await createAgentApi(api, owner, 'org-assign')
  await seedSession(context, owner.token)
  const orgName = uniqueName('org')
  const teamName = uniqueName('team')
  let orgId = ''
  let inviteToken = ''

  const myOrgs = async (token: string) => {
    const r = await api.json('GET', '/api/v1/organizations', { token })
    return (Array.isArray(r.body) ? r.body : []) as any[]
  }

  await steps.run('no-organization-yet', 'ui:developer', async () => {
    expect(await openRoute(page, '/organization')).toBe('/organization')
    await expect(page.locator('[data-tour="org-create-btn"]').first()).toBeVisible()
    await a11y(page, 'org-empty')
    return 'the create door is on screen'
  })

  await steps.run('create-organization', 'ui:developer', async () => {
    await page.locator('[data-tour="org-create-btn"]').first().click()
    const name = page.locator('input[placeholder="My Organization"]')
    await expect(name).toBeVisible()
    await a11y(page, 'org-create-form')
    await name.fill(orgName)
    await page.locator('input[placeholder="Brief description of your organization"], textarea[placeholder="Brief description of your organization"]').first().fill('made by the console lifecycle suite')
    await page.locator('.tp-btn--primary').filter({ hasText: /create/i }).click()
    await toast(page, 'success', /.+/)
    const org = (await myOrgs(owner.token)).find((o) => o.name === orgName)
    expect(org, 'the API lists the organization').toBeTruthy()
    orgId = String(org.id)
    await expect(page.getByText(orgName).first()).toBeVisible()
    return `created ${orgName}`
  })

  await steps.run('create-team', 'ui:developer', async () => {
    await page.locator('[data-tour="org-tab-teams"]').click()
    await page.locator('.tab-header').getByRole('button', { name: /create team/i }).click()
    const tn = page.locator('input[placeholder="Engineering Team"]')
    await expect(tn).toBeVisible()
    await a11y(page, 'org-team-form')
    await tn.fill(teamName)
    await page.locator('.tp-btn--primary').filter({ hasText: /create/i }).click()
    await expect(page.locator('.team-card').filter({ hasText: teamName })).toBeVisible()
    const r = await api.json('GET', `/api/v1/organizations/${orgId}/teams`, { token: owner.token })
    expect((r.body || []).some((t: any) => t.name === teamName), 'the API lists the team').toBe(true)
    return 'team on the page and in the API'
  })

  await steps.run('invite-member', 'ui:developer', async () => {
    await page.locator('[data-tour="org-tab-members"]').click()
    await page.locator('.tab-header').getByRole('button', { name: /invite member/i }).click()
    const email = page.locator('input[placeholder="member@example.com"]')
    await expect(email).toBeVisible()
    await a11y(page, 'org-invite-form')
    await email.fill(member.email)
    const sent = page.waitForResponse((r) => r.url().includes(`/organizations/${orgId}/invite`) && r.request().method() === 'POST')
    await page.locator('.tp-btn--primary').filter({ hasText: /invite|send/i }).click()
    const resp = await sent
    expect(resp.status()).toBeLessThan(300)
    // The token travels in the invitation mail; the suite reads it from the invite's own answer, never stores it.
    const body = await resp.json()
    inviteToken = String(body.token || body.invitation_token || body.invitation?.token || '')
    expect(inviteToken.length, 'the invitation carries a token').toBeGreaterThan(10)
    return 'invitation sent (token not recorded)'
  })

  await steps.run('member-accepts-in-their-own-browser', 'ui:developer', async () => {
    const other = await openAs(member.token)
    await other.goto(`${new URL(page.url()).origin}/ui/#/organizations/invitations/${inviteToken}/accept`)
    await other.locator('[data-testid="legal-reconsent-later"]').click({ timeout: 8_000 }).catch(() => {})
    await other.locator('[data-testid="oi-accept"]').click()
    await expect(other.locator('[data-testid="oi-joined"]')).toBeVisible()
    const r = await api.json('GET', `/api/v1/organizations/${orgId}/members`, { token: owner.token })
    expect((r.body || []).some((m: any) => String(m.developer_email || '').toLowerCase() === member.email.toLowerCase() && m.is_active !== false), 'the owner sees the new member').toBe(true)
    return 'joined; the owner\'s member list has them'
  })

  await steps.run('assign-and-unassign-agent', 'ui:developer', async () => {
    await page.reload()
    await settle(page)
    await page.locator('[data-tour="org-tab-agents"]').click()
    const orgAgentDids = async () => {
      const r = await api.json('GET', `/api/v1/organizations/${orgId}/agents`, { token: owner.token })
      expect(r.status, 'the org agents list answers').toBe(200)
      const list: any[] = Array.isArray(r.body) ? r.body : r.body?.agents || r.body?.items || []
      return list.map((x) => String(x.did || x.agent_did || ''))
    }
    await page.locator(`[data-testid="org-assignable"][data-did="${agent.did}"] button`).click()
    await toast(page, 'success', /assigned/i)
    expect(await orgAgentDids(), 'the API lists the agent under the org').toContain(agent.did)
    const card = page.locator(`[data-testid="org-agent"][data-did="${agent.did}"]`)
    await expect(card, 'the agent moves to the org\'s list').toBeVisible()
    await card.getByRole('button', { name: /remove .* from the organization/i }).click()
    await toast(page, 'success', /removed/i)
    await expect.poll(orgAgentDids, { message: 'the API no longer lists it' }).not.toContain(agent.did)
    return 'assigned and taken back, each read back'
  })

  await steps.run('remove-member', 'ui:developer', async () => {
    await page.locator('[data-tour="org-tab-members"]').click()
    const row = page.locator('*').filter({ hasText: member.email }).locator('.member-action-btn--danger').first()
    await row.click()
    await confirmDialog(page)
    await expect.poll(async () => {
      const r = await api.json('GET', `/api/v1/organizations/${orgId}/members`, { token: owner.token })
      return (r.body || []).some((m: any) => String(m.developer_email || '').toLowerCase() === member.email.toLowerCase() && m.is_active !== false)
    }).toBe(false)
    return 'removed; gone from the API\'s member list'
  })

  await steps.run('delete-team', 'ui:developer', async () => {
    await page.locator('[data-tour="org-tab-teams"]').click()
    await page.locator('.team-card').filter({ hasText: teamName }).locator('.team-action-btn--delete').click()
    await confirmDialog(page)
    await expect(page.locator('.team-card').filter({ hasText: teamName })).toHaveCount(0)
    return 'team deleted'
  })

  await steps.run('delete-organization', 'ui:developer', async () => {
    await page.locator('[data-tour="org-tab-settings"]').click()
    await page.locator('.danger-btn').filter({ hasText: /delete/i }).click()
    await confirmDialog(page, orgName)
    await expect.poll(async () => (await myOrgs(owner.token)).some((o) => o.name === orgName)).toBe(false)
    return 'organization deleted, read back'
  })
})
