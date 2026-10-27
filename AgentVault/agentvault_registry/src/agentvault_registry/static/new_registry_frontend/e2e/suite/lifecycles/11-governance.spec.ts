/**
 * Governance on the Senate floor (§FESUITE; the MCP tester's proposal_stake and governance rails, as a person meets
 * them). A fresh agent may not propose: the floor says why, in the server's words. Its owner grants the governor role on
 * the Access panel; with less than the frame's minimum stake the floor still says why; with it the agent proposes, votes
 * for it with the weight of its staked lock, and an early tally is refused (the floor offers Finalize only after the
 * end; the server refuses it before). Every state is read back as the agent.
 */
import { test, expect } from '../support/fixtures'
import { agentToken, createAgentApi, registerDeveloper, seedActiveAgent, seedSession, seedVault } from '../support/accounts'
import { PREFIX, uniqueName } from '../support/env'
import { openRoute, toast } from '../support/ui'

test('governance_propose_vote_and_tally', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'govdev')
  const a = await createAgentApi(api, dev, 'gov-a')
  const ta = await agentToken(api, a)
  await seedSession(context, dev.token)
  await seedVault(context, api, dev, [a])
  await seedActiveAgent(context, a.did)
  const title = uniqueName('proposal')
  const proposals = async () => {
    const r = await api.json('GET', '/api/v1/governance/proposals', { token: ta })
    expect(r.status, 'the proposals list answers the agent').toBe(200)
    return (Array.isArray(r.body) ? r.body : r.body?.proposals || []) as Array<Record<string, any>>
  }
  const mine = async () => (await proposals()).find((p) => p.title === title)
  let proposalId = 0

  const stake = async (amount: string) => {
    // Setup through the API (10-staking drives this door): the floor counts staked weight, a liquid grant votes nothing
    const r = await api.json('POST', '/api/v1/staking/stake', { token: ta, body: { amount, lock_period: 30 } })
    expect(r.status, `a 30-day lock of ${amount}`).toBeLessThan(300)
  }
  await steps.run('setup-a-small-staked-lock', 'ui:agent', async () => {
    await expect.poll(async () => Number((await api.json('GET', '/api/v1/teg/balance', { token: ta })).body?.balance || 0), { timeout: 45_000 }).toBeGreaterThan(0)
    await stake('10')
    return 'staked 10 for 30 days'
  })

  const fillProposal = async () => {
    await page.locator('[data-tour="sen-create"]').click()
    const dialog = page.locator('.tp-modal').filter({ hasText: /create proposal/i }).last()
    await expect(dialog).toBeVisible()
    await dialog.locator('input.tp-input').first().fill(title)
    await dialog.getByRole('button', { name: /^1 day$/i }).click()
    await expect(dialog.getByRole('button', { name: /^1 day$/i }), 'the chosen duration says so').toHaveAttribute('aria-pressed', 'true')
    await dialog.locator('textarea').first().fill(`${PREFIX}: a proposal made by the console lifecycle suite. It changes nothing.`)
    return dialog
  }

  await steps.run('propose-refused-without-the-role', 'ui:agent', async () => {
    await openRoute(page, '/senate?tab=governance')
    await expect(page.locator('[data-tour="sen-tab-gov"]'), 'the link opens the governance tab').toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('[data-tour="sen-create"]')).toBeVisible()
    await a11y(page, 'senate')
    capture.allow(/POST \/api\/v1\/governance\/proposals$/, 403, 'refused on purpose twice: no gov.propose yet, then less than the frame\'s minimum stake')
    const dialog = await fillProposal()
    await a11y(page, 'senate-create-proposal')
    await dialog.getByRole('button', { name: /^create proposal$/i }).click()
    await toast(page, 'error', /gov\.propose|permission|role|governor/i)
    await expect(dialog, 'the dialog stays open with what was typed').toBeVisible()
    expect(await mine(), 'no proposal was made').toBeUndefined()
    await dialog.getByRole('button', { name: /^cancel$/i }).click()
    return 'refused 403 with the reason shown; nothing made'
  })

  await steps.run('grant-the-governor-role-on-the-access-panel', 'ui:developer', async () => {
    await openRoute(page, '/my-agents')
    const card = page.locator(`[data-testid="agent-card"][data-did="${a.did}"]`)
    await card.locator('[data-tour="ma-access-btn"]').click()
    const opt = page.locator('.aap-role-opt').filter({ hasText: /^\s*governor\s*$/i })
    await expect(opt).toBeVisible()
    await a11y(page, 'agent-access')
    await opt.click()
    await page.locator('.aap-btn--primary').filter({ hasText: /save/i }).first().click()
    await expect.poll(async () => {
      const r = await api.json('GET', `/api/v1/agents/${encodeURIComponent(a.did)}/authz`, { token: dev.token })
      return (r.body?.roles || []) as string[]
    }, { message: 'the API lists the governor role' }).toContain('governor')
    return 'governor granted and saved'
  })

  await steps.run('propose-refused-below-the-minimum-stake', 'ui:agent', async () => {
    await openRoute(page, '/senate?tab=governance')
    const dialog = await fillProposal()
    await dialog.getByRole('button', { name: /^create proposal$/i }).click()
    const said = await toast(page, 'error', /requires \d+(\.\d+)? staked/i)
    await expect(dialog, 'the dialog stays open').toBeVisible()
    expect(await mine(), 'no proposal was made').toBeUndefined()
    await dialog.getByRole('button', { name: /^cancel$/i }).click()
    return said.slice(0, 110)
  })

  await steps.run('setup-the-minimum-stake', 'ui:agent', async () => {
    await stake('90')
    return 'staked 90 more (100 in all)'
  })

  await steps.run('propose', 'ui:agent', async () => {
    await openRoute(page, '/senate?tab=governance')
    const dialog = await fillProposal()
    await dialog.getByRole('button', { name: /^create proposal$/i }).click()
    await toast(page, 'success', /proposal created/i)
    await expect(dialog).toBeHidden()
    const p = await mine()
    expect(p, 'the API lists the proposal').toBeTruthy()
    proposalId = Number(p!.id)
    await expect(page.locator('[data-tour="sen-proposal"]').filter({ hasText: title }), 'the floor lists it').toBeVisible()
    return `proposal #${proposalId} ${p!.status}`
  })

  await steps.run('vote-for-it', 'ui:agent', async () => {
    const card = page.locator('[data-tour="sen-proposal"]').filter({ hasText: title })
    await card.locator('[data-tour="sen-vote"]').click()
    const dialog = page.locator('.tp-modal').filter({ has: page.locator('.tp-vote-grid') }).last()
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: /^for$/i }).click()
    await a11y(page, 'senate-vote')
    await dialog.locator('textarea').fill(`${PREFIX}: for, as a test`)
    await dialog.getByRole('button', { name: /^submit for$/i }).click()
    await toast(page, 'success', /vote/i)
    const r = await api.json('GET', `/api/v1/governance/proposals/${proposalId}/my-vote`, { token: ta })
    expect(r.status).toBe(200)
    expect(JSON.stringify(r.body).toLowerCase(), 'the API holds a vote for it').toMatch(/"(vote|choice|vote_in_favor)":\s*("for"|true)/)
    await expect(card.locator('[data-tour="sen-vote"]'), 'the floor stops offering a second vote').toHaveCount(0)
    return `voted for #${proposalId}`
  })

  await steps.run('an-early-tally-is-refused', 'ui:agent', async () => {
    const card = page.locator('[data-tour="sen-proposal"]').filter({ hasText: title })
    await expect(card.locator('[data-tour="sen-tally"]'), 'the floor offers Finalize only after the end').toHaveCount(0)
    const r = await api.json('POST', `/api/v1/governance/proposals/${proposalId}/tally`, { token: ta })
    expect(r.status, 'the server refuses a tally before the end').toBeGreaterThanOrEqual(400)
    expect(JSON.stringify(r.body), 'in words').toMatch(/not ended/i)
    expect(String((await mine())?.status || '').toUpperCase(), 'still open').toMatch(/VOTING|ACTIVE|OPEN/)
    return `refused ${r.status}: the voting period has not ended`
  })
})
