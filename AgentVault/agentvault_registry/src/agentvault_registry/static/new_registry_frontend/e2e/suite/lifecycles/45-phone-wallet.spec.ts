/**
 * Money on a phone (§FESUITE; lifecycle 09 the way a phone does it): two agents made elsewhere (the API, as an SDK
 * would), their keys brought onto the phone through Pocket's own door (the acting chip, Import, paste, Preview,
 * Apply), the first one picked as the acting agent, then the send sheet from a payment link: it fits the screen, its
 * Send is the element a thumb lands on, the send settles once, and both balances are read back from the TEG.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, agentToken, createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX } from '../support/env'
import { openRoute, settle } from '../support/ui'
import { sideScroll, actingAgent } from '../support/pages'
import { reachable, watchRequests } from '../support/hygiene'

test('phone_wallet_import_and_send @phone-only', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'phonewallet')
  const a = await createAgentApi(api, dev, 'phone-a')
  const b = await createAgentApi(api, dev, 'phone-b')
  const ta = await agentToken(api, a)
  const tb = await agentToken(api, b)
  await seedSession(context, dev.token)
  let aBefore = 0
  let bBefore = 0

  await steps.run('genesis-grant-arrives', 'ui:agent', async () => {
    await expect.poll(() => agentBalance(api, ta), { timeout: 45_000 }).toBeGreaterThan(0)
    aBefore = await agentBalance(api, ta)
    bBefore = await agentBalance(api, tb)
    return `the first agent holds ${aBefore}; the second ${bBefore}`
  })

  await steps.run('import-keys-through-the-acting-chip', 'ui:developer', async () => {
    await openRoute(page, '/pocket/home')
    await page.locator('[data-testid="pk-acting-chip"]').tap()
    const sheet = page.locator('[data-testid="pk-agsheet"]')
    await expect(sheet).toBeVisible()
    await sheet.locator('[data-testid="ag-tab-import"]').tap()
    // the exported-credential shape the desktop importer takes too (services/credImport.ts)
    const exported = JSON.stringify([a, b].map((x, i) => ({ did: x.did, client_id: x.clientId, client_secret: x.clientSecret, name: `${PREFIX}-phone-${i ? 'b' : 'a'}` })))
    await sheet.locator('[data-testid="ag-import-text"]').fill(exported)
    await a11y(page, 'phone-agent-sheet-import')
    await sheet.locator('[data-testid="ag-import-preview"]').tap()
    await expect(sheet.locator('[data-testid="ag-import-summary"]')).toBeVisible()
    await sheet.locator('[data-testid="ag-import-apply"]').tap()
    await expect(sheet.locator('[data-testid="ag-import-done"]')).toBeVisible()
    const held = await page.evaluate((dids) => {
      try { const v = JSON.parse(localStorage.getItem('agentvault_agent_credentials') || '{}'); return dids.filter((d) => !!v[d]).length } catch { return -1 }
    }, [a.did, b.did])
    expect(held, 'both keys are held on the phone').toBe(2)
    return 'two agents imported through the sheet'
  })

  await steps.run('pick-the-acting-agent', 'ui:developer', async () => {
    const sheet = page.locator('[data-testid="pk-agsheet"]')
    await sheet.getByRole('button', { name: /pick the acting agent/i }).tap()
    await sheet.locator('[data-testid="asl-row"]').filter({ hasText: `${PREFIX}-phone-a` }).tap()
    await expect(sheet).toHaveCount(0)
    await expect.poll(() => actingAgent(page), { timeout: 20_000 }).toBe(a.did)
    return 'the first agent acts'
  })

  await steps.run('send-sheet-fits-and-sends-once', 'ui:agent', async () => {
    await openRoute(page, `/pocket/pay?to=${encodeURIComponent(b.did)}`)
    const amount = page.locator('.ps-sheet input.ps-amt')
    await expect(amount).toBeVisible()
    await expect(page.locator('[data-testid="ps-from"]')).toHaveValue(a.did)
    expect(await sideScroll(page), 'the sheet does not scroll sideways').toBeLessThanOrEqual(1)
    await amount.fill('2')
    await page.locator('.ps-sheet .ps-actions .ps-primary').tap()
    await expect(page.locator('[data-testid="ps-assert"]')).toBeVisible({ timeout: 30_000 })
    const send = page.locator('.ps-sheet .ps-actions .ps-send')
    await send.scrollIntoViewIfNeeded()
    expect(await reachable(page, send), 'Send is the element a thumb lands on').toBe(true)
    await a11y(page, 'phone-send-preview')
    const sends = watchRequests(page, 'POST', /\/api\/v1\/teg\/send$/, /"dry_run":\s*false/)
    await send.tap()
    await send.tap({ timeout: 1_000 }).catch(() => {})
    await expect(page.locator('.ps-sheet .ps-result.ok')).toBeVisible({ timeout: 45_000 })
    await page.waitForTimeout(1_500)
    sends.stop()
    expect(sends.list.length, 'two taps, one send left the page').toBe(1)
    return 'previewed and sent on a phone'
  })

  await steps.run('balances-moved-once', 'ui:agent', async () => {
    await expect.poll(async () => (await agentBalance(api, tb)) - bBefore, { timeout: 45_000 }).toBeGreaterThan(0)
    await settle(page)
    const bGain = (await agentBalance(api, tb)) - bBefore
    const aLoss = aBefore - (await agentBalance(api, ta))
    expect(bGain, 'the receiver gained one send').toBeCloseTo(2, 6)
    expect(aLoss, 'the sender paid what arrived plus a fee, once').toBeGreaterThanOrEqual(2)
    expect(aLoss, 'the sender paid one send, not two').toBeLessThan(4)
    return `receiver +${bGain.toFixed(6)}, sender -${aLoss.toFixed(6)}`
  })
})
