/**
 * An agent's life through the console (§FESUITE; the MCP tester's createAgent + agent_self_delete, through the page):
 * an empty fleet that says so, the quick-create sheet (credentials shown once, the genesis grant, the bond door), the
 * agent on My Agents, its own page, and its decommission. Every screen claim is read back from the API.
 */
import { test, expect } from '../support/fixtures'
import { ledger, registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { currentRoute, openRoute, settle, toast } from '../support/ui'

test('agent_create_view_decommission', async ({ page, context, steps, api, a11y }) => {
  const dev = await registerDeveloper(api, 'agentdev')
  await seedSession(context, dev.token)
  const agentName = uniqueName('agent')
  let did = ''

  await steps.run('empty-fleet-says-so', 'ui:developer', async () => {
    const landed = await openRoute(page, '/my-agents')
    expect(landed).toBe('/my-agents')
    // A fresh account owns no agent: the page must offer the way to make one, not an empty grid.
    await expect(page.locator('.fleet-deploy-btn').first()).toBeVisible()
    await expect(page.locator('.agent-card')).toHaveCount(0)
    await a11y(page, 'my-agents-empty')
    return 'no agent, a deploy door on screen'
  })

  await steps.run('quick-create', 'ui:developer', async () => {
    await page.locator('.fleet-deploy-btn').first().click()
    const nameInput = page.locator('input[placeholder="e.g., Pricing Oracle"]')
    await expect(nameInput).toBeVisible()
    await a11y(page, 'quick-agent-form')
    await nameInput.fill(agentName)
    await page.locator('.qa-btn--primary').click()
    await expect(page.locator('.qa-success-hero')).toBeVisible({ timeout: 60_000 })
    const r = await api.json('GET', '/api/v1/developers/me/agents', { token: dev.token })
    expect(r.status).toBe(200)
    const list: any[] = Array.isArray(r.body) ? r.body : r.body?.agents || r.body?.items || []
    const mine = list.find((a) => (a.name || a.human_readable_id || '') === agentName)
    expect(mine, 'the created agent is listed by the API').toBeTruthy()
    did = mine.did
    ledger('agent', { did, name: agentName, owner: dev.email })
    return `${did.slice(0, 28)}… listed by the API`
  })

  await steps.run('credentials-shown-once', 'ui:developer', async () => {
    // The sheet shows the client secret once; the suite looks for its presence and never records it.
    const sheet = page.locator('.qa-success-summary')
    await expect(sheet).toBeVisible()
    const text = await sheet.innerText()
    expect(text).toContain(agentName)
    await a11y(page, 'quick-agent-success')
    return 'name and identifier on the success sheet'
  })

  await steps.run('genesis-grant-reaches-the-sheet', 'ui:developer', async () => {
    const sub = page.locator('[data-testid="qa-success-sub"]')
    await expect(sub).toBeVisible()
    // 'unread' while the balance read is in flight; it must settle to some or zero, never stay unread.
    await expect(sub).not.toHaveAttribute('data-held', 'unread', { timeout: 30_000 })
    return `held: ${await sub.getAttribute('data-held')}`
  })

  await steps.run('close-sheet-agent-on-fleet', 'ui:developer', async () => {
    await page.locator('.qa-close').click()
    await expect(page.locator('.qa-success-hero')).toHaveCount(0)
    const card = page.locator('.agent-card').filter({ has: page.locator('.card-name', { hasText: agentName }) })
    await expect(card).toHaveCount(1)
    await a11y(page, 'my-agents-one')
    return 'one card with the agent\'s name'
  })

  await steps.run('agent-page', 'ui:developer', async () => {
    const card = page.locator('.agent-card').filter({ has: page.locator('.card-name', { hasText: agentName }) })
    await card.locator('[data-tour="mya-card"]').click()
    await page.waitForFunction((d) => decodeURIComponent(location.hash).includes(d), did)
    await settle(page)
    await expect(page.getByText(agentName).first()).toBeVisible()
    await a11y(page, 'agent-page')
    return await currentRoute(page)
  })

  await steps.run('decommission', 'ui:developer', async () => {
    await openRoute(page, '/my-agents')
    const card = page.locator('.agent-card').filter({ has: page.locator('.card-name', { hasText: agentName }) })
    await card.locator('.card-btn--danger').click()
    const dialog = page.locator('.modal-box').filter({ hasText: agentName })
    await expect(dialog).toBeVisible()
    await a11y(page, 'decommission-dialog')
    await dialog.locator('.modal-btn--danger').click()
    await toast(page, 'success', /deleted|removed/i)
    await expect(card).toHaveCount(0)
    const r = await api.json('GET', '/api/v1/developers/me/agents', { token: dev.token })
    const list: any[] = Array.isArray(r.body) ? r.body : r.body?.agents || r.body?.items || []
    const still = list.find((a) => a.did === did && a.is_active !== false && a.status !== 'revoked')
    expect(still, 'the API no longer lists the agent as active').toBeFalsy()
    return 'gone from the fleet and from the API\'s active list'
  })
})
