/**
 * Staking from Pocket (§FESUITE; the MCP tester's proposal_stake leg and the staking rails, as a person meets them).
 * The stake sheet names the acting agent and warns before the grant is locked away from the reputation bond, refuses
 * amounts that are not amounts on the page and a stake below the minimum in the server's words, stakes once per press,
 * shows a locked position with its unlock date instead of an Unstake that cannot work, and unstakes exactly the
 * flexible position a person chose. Every state is read back from the API as the agent.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, agentToken, createAgentApi, registerDeveloper, seedSession, seedVault } from '../support/accounts'
import { openRoute } from '../support/ui'

test('staking_stake_lock_and_unstake', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(5 * 60_000)
  const cfg = (await api.json('GET', '/api/v1/public/registry-config')).body || {}
  if (cfg.staking_enabled === false) {
    steps.notMeasured('staking', 'ui:agent', 'staking is switched off on this frame (STAKING_ENABLED=false)')
    return
  }
  const dev = await registerDeveloper(api, 'stakedev')
  const a = await createAgentApi(api, dev, 'stake-a')
  const ta = await agentToken(api, a)
  await seedSession(context, dev.token)
  await seedVault(context, api, dev, [a])
  const positions = async () => {
    const r = await api.json('GET', '/api/v1/staking/my-positions', { token: ta })
    expect(r.status, 'my-positions answers').toBe(200)
    return (Array.isArray(r.body) ? r.body : []) as Array<Record<string, any>>
  }
  const active = async () => (await positions()).filter((p) => p.status === 'active')
  let liquid0 = 0

  await steps.run('genesis-grant-arrives', 'ui:agent', async () => {
    await expect.poll(() => agentBalance(api, ta), { timeout: 45_000 }).toBeGreaterThan(0)
    liquid0 = await agentBalance(api, ta)
    return `the agent holds ${liquid0}`
  })

  const sheetOpen = async () => {
    await openRoute(page, '/pocket/home?sheet=stake')
    await expect(page.locator('.pt-scrim select.pt-in')).toHaveValue(a.did)
  }
  const stakeBtn = () => page.locator('.pt-scrim .pt-actions .pt-primary')
  const amount = () => page.locator('.pt-scrim input.pt-amt')

  await steps.run('the-sheet-names-the-agent-and-the-bond', 'ui:agent', async () => {
    await sheetOpen()
    await expect(page.locator('[data-testid="pt-bond-hint"]'), 'an unbonded agent is told to keep its bond liquid').toBeVisible()
    await a11y(page, 'pocket-stake')
    return 'the acting agent is selected; the bond hint is up'
  })

  await steps.run('amounts-that-are-not-amounts-never-leave', 'ui:agent', async () => {
    const sent: string[] = []
    const onReq = (r: { url(): string }) => { if (/\/api\/v1\/staking\/stake(\?|$)/.test(r.url())) sent.push(r.url()) }
    page.on('request', onReq)
    for (const bad of ['-1', '1e309', 'abc', '0']) {
      await amount().fill(bad)
      await expect(stakeBtn(), `"${bad}" cannot be staked`).toBeDisabled()
      await expect(page.locator('[data-testid="pt-amount-warn"]'), `"${bad}" is refused in words`).toBeVisible()
    }
    page.off('request', onReq)
    expect(sent, 'nothing left the page').toEqual([])
    return 'four non-amounts refused on the page, nothing sent'
  })

  await steps.run('below-the-minimum-is-refused-in-words', 'ui:agent', async () => {
    capture.allow(/POST \/api\/v1\/staking\/stake$/, 400, 'a stake below the frame\'s minimum is refused on purpose')
    await amount().fill('5')
    await stakeBtn().click()
    await expect(page.locator('.pt-scrim .pt-msg.bad')).toContainText(/minimum/i)
    expect((await active()).length, 'nothing was staked').toBe(0)
    return (await page.locator('.pt-scrim .pt-msg.bad').innerText()).slice(0, 80)
  })

  await steps.run('stake-flexible-once', 'ui:agent', async () => {
    await page.locator('.pt-scrim .pt-tier').first().click()
    await amount().fill('10')
    await stakeBtn().dblclick()
    await expect(page.locator('.pt-scrim .pt-msg.ok')).toBeVisible({ timeout: 30_000 })
    await page.waitForTimeout(1_500)
    const act = await active()
    expect(act.length, 'one press, one position').toBe(1)
    expect(Number(act[0].lockPeriod), 'the flexible tier').toBe(0)
    await expect(page.locator('[data-testid="pt-pos"][data-lock="0"] .pt-unstake'), 'a flexible position can be unstaked').toBeVisible()
    return `1 flexible position of ${act[0].amount}`
  })

  let locked: Record<string, any> | undefined
  await steps.run('stake-locked-shows-its-unlock-date', 'ui:agent', async () => {
    await page.locator('.pt-scrim .pt-tier').nth(1).click()
    await amount().fill('10')
    await stakeBtn().click()
    await expect(page.locator('.pt-scrim .pt-msg.ok')).toBeVisible({ timeout: 30_000 })
    locked = (await active()).find((p) => Number(p.lockPeriod) > 0)
    expect(locked, 'a locked position was opened').toBeTruthy()
    const row = page.locator(`[data-testid="pt-pos"][data-lock="${locked!.lockPeriod}"]`)
    await expect(row.locator('[data-testid="pt-locked"]'), 'the locked row says until when').toContainText(/until/i)
    await expect(row.locator('.pt-unstake'), 'and offers no Unstake that cannot work').toHaveCount(0)
    await a11y(page, 'pocket-stake-positions')
    return `a ${locked!.lockPeriod}-day position, unlocks ${String(locked!.unlockDate).slice(0, 10)}`
  })

  await steps.run('a-locked-position-is-refused-by-name', 'ui:agent', async () => {
    // the server half of the same rule, asked directly: naming the locked position releases nothing at all
    const r = await api.json('POST', '/api/v1/staking/unstake', { token: ta, body: { amount: '10', position_id: String(locked!.id) } })
    expect(r.status, 'a locked position is refused').toBe(403)
    expect(JSON.stringify(r.body), 'with its unlock date').toContain(String(locked!.unlockDate).slice(0, 10))
    expect((await active()).length, 'both positions are still there').toBe(2)
    return 'refused 403 with the unlock date; nothing released'
  })

  await steps.run('unstake-the-flexible-position', 'ui:agent', async () => {
    const before = await agentBalance(api, ta)
    await page.locator('[data-testid="pt-pos"][data-lock="0"] .pt-unstake').click()
    await expect(page.locator('.pt-scrim .pt-msg.ok')).toBeVisible({ timeout: 30_000 })
    const act = await active()
    expect(act.length, 'one position left').toBe(1)
    expect(Number(act[0].lockPeriod), 'the locked one stayed').toBeGreaterThan(0)
    await expect.poll(async () => (await agentBalance(api, ta)) - before, { timeout: 30_000 }).toBeCloseTo(10, 6)
    await expect(page.locator('[data-testid="pt-pos"][data-lock="0"]'), 'the unstaked position leaves the list').toHaveCount(0)
    return 'the flexible position came back (+10 liquid); the locked one stayed'
  })
})
