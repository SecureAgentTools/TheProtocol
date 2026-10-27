/**
 * Money between two of a person's own agents, through the page (§FESUITE; the MCP tester's transfer_direct,
 * amount_bounds and money_idempotent_replay, as a person meets them). The agents are made elsewhere (the API, as an
 * SDK would) and their keys entered on My Agents: a wrong secret is refused and nothing is kept, the right one is
 * verified and kept. Then Pocket's send sheet: amounts that are not amounts never leave the page, the preview names who
 * pays from where and what arrives, the send settles, and a double press moves value once. Balances are read back from
 * the TEG as each agent.
 */
import { test, expect } from '../support/fixtures'
import { VAULT_KEY, agentBalance, agentToken, createAgentApi, registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX } from '../support/env'
import { openRoute, settle, toast } from '../support/ui'


test('wallet_send_between_own_agents', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'walletdev')
  const a = await createAgentApi(api, dev, 'wallet-a')
  const b = await createAgentApi(api, dev, 'wallet-b')
  const ta = await agentToken(api, a)
  const tb = await agentToken(api, b)
  await seedSession(context, dev.token)
  const vaultHas = (did: string) => page.evaluate(([k, d]) => {
    try { return !!(JSON.parse(localStorage.getItem(k) || '{}') || {})[d] } catch { return false }
  }, [VAULT_KEY, did] as const)
  let aBefore = 0
  let bBefore = 0

  await steps.run('genesis-grant-arrives', 'ui:agent', async () => {
    await expect.poll(() => agentBalance(api, ta), { timeout: 45_000 }).toBeGreaterThan(0)
    aBefore = await agentBalance(api, ta)
    bBefore = await agentBalance(api, tb)
    return `the first agent holds ${aBefore}; the second ${bBefore}`
  })

  await steps.run('enter-keys-on-my-agents', 'ui:developer', async () => {
    await openRoute(page, '/my-agents')
    const card = page.locator(`[data-testid="agent-card"][data-did="${a.did}"]`)
    await expect(card, 'the API-made agent is on the fleet').toBeVisible({ timeout: 30_000 })
    const addKeys = card.locator('.card-btn--accent')
    await addKeys.click()
    const dialog = page.locator('[aria-labelledby="add-creds-title"]')
    await expect(dialog).toBeVisible()
    await a11y(page, 'add-credentials')
    // a wrong secret: refused by the registry, said on the page, nothing kept
    capture.allow(/POST \/api\/v1\/auth\/agent\/token$/, 401, 'a wrong secret is refused on purpose')
    await dialog.locator('#ac-client-id').fill(a.clientId)
    await dialog.locator('#ac-client-secret').fill(a.clientSecret.slice(0, -4) + 'zzzz')
    await dialog.locator('.tp-btn--primary').click()
    await expect(dialog.locator('[role="alert"]')).toContainText(/rejected/i)
    expect(await vaultHas(a.did), 'a refused secret is not kept').toBe(false)
    // the right one: verified, kept, and the agent becomes the acting one
    await dialog.locator('#ac-client-secret').fill(a.clientSecret)
    await dialog.locator('.tp-btn--primary').click()
    await toast(page, 'success', /credentials saved/i)
    await expect(dialog).toHaveCount(0)
    expect(await vaultHas(a.did), 'the verified keys are kept in this browser').toBe(true)
    await expect(card.locator('.card-btn--accent'), 'ADD KEYS goes away once keys are held').toHaveCount(0)
    return 'wrong secret refused and not kept; right secret verified and kept'
  })

  const sheet = async () => {
    await openRoute(page, `/pocket/pay?to=${encodeURIComponent(b.did)}`)
    await expect(page.locator('.ps-sheet input.ps-amt')).toBeVisible()
    await expect(page.locator('[data-testid="ps-from"]')).toHaveValue(a.did)
  }

  await steps.run('amounts-that-are-not-amounts-never-leave', 'ui:agent', async () => {
    await sheet()
    const sent: string[] = []
    const onReq = (r: { url(): string }) => { if (/\/api\/v1\/teg\/send(\?|$)/.test(r.url())) sent.push(r.url()) }
    page.on('request', onReq)
    const amount = page.locator('.ps-sheet input.ps-amt')
    const preview = page.locator('.ps-sheet .ps-actions .ps-primary')
    for (const bad of ['-1', '0', 'abc', '1e309', '0x10', '1.2.3']) {
      await amount.fill(bad)
      await expect(preview, `"${bad}" must not be previewable`).toBeDisabled()
      await expect(page.locator('[data-testid="ps-amount-warn"]'), `"${bad}" is refused in words`).toBeVisible()
    }
    await amount.fill('1,5')
    await expect(preview, 'a comma decimal is an amount').toBeEnabled()
    await expect(page.locator('[data-testid="ps-amount-warn"]')).toHaveCount(0)
    page.off('request', onReq)
    expect(sent, 'no request left for an amount that is not one').toEqual([])
    return 'six non-amounts refused in words, nothing sent; "1,5" accepted'
  })

  await steps.run('preview-then-send-once', 'ui:agent', async () => {
    await page.locator('.ps-sheet input[placeholder^="Memo"]').fill(`${PREFIX} send`)
    await page.locator('.ps-sheet .ps-actions .ps-primary').click()
    await expect(page.locator('[data-testid="ps-assert"]')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('[data-testid="ps-assert-debit"]'), 'the sheet states the amount the server gets').toContainText('1.5')
    await a11y(page, 'pocket-send-preview')
    const sends: string[] = []
    const onReq = (r: { url(): string; postData(): string | null }) => {
      if (/\/api\/v1\/teg\/send(\?|$)/.test(r.url()) && /"dry_run":\s*false/.test(r.postData() || '')) sends.push(r.url())
    }
    page.on('request', onReq)
    await page.locator('.ps-sheet .ps-actions .ps-send').dblclick()
    await expect(page.locator('.ps-sheet .ps-result.ok')).toBeVisible({ timeout: 45_000 })
    // and once more in the second between the success and the sheet closing
    await page.locator('.ps-sheet .ps-actions .ps-send').click({ timeout: 1_000 }).catch(() => {})
    await page.waitForTimeout(1_500)
    page.off('request', onReq)
    expect(sends.length, 'one send left the page for three presses').toBe(1)
    return 'previewed, sent; three presses, one send'
  })

  await steps.run('balances-moved-once', 'ui:agent', async () => {
    await expect.poll(async () => (await agentBalance(api, tb)) - bBefore, { timeout: 45_000 }).toBeGreaterThan(0)
    await settle(page)
    const bGain = (await agentBalance(api, tb)) - bBefore
    const aLoss = aBefore - (await agentBalance(api, ta))
    expect(bGain, 'the receiver gained one send').toBeCloseTo(1.5, 6)
    expect(aLoss, 'the sender paid what arrived plus a fee, once').toBeGreaterThanOrEqual(1.5)
    expect(aLoss, 'the sender paid one send, not two').toBeLessThan(3)
    return `receiver +${bGain.toFixed(6)}, sender -${aLoss.toFixed(6)}`
  })
})
