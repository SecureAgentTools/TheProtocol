/**
 * A contract between two people's agents, through the Contracts page (§FESUITE; the MCP tester's contract lifecycles,
 * as two people meet them). A client proposes work; a provider (an agent bonded from its owner's wallet agent, the
 * frame's gate to providing work) accepts it, which escrows the client's payment; the provider submits a pull request;
 * the client approves and the escrow is released to the provider. Every state is read back from the API, and the
 * money from the TEG as each agent: the client pays once, at acceptance, and the provider is paid once, at approval.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, seedSession } from '../support/accounts'
import { bondFrom, partyWith, seedVault, stillFrame, waitActing } from '../support/commerce'
import { uniqueName } from '../support/env'
import { openRoute, settle } from '../support/ui'

const AMOUNT = 3

test('contract_propose_accept_deliver_pay', async ({ page, context, steps, api, a11y, openAs }) => {
  test.setTimeout(6 * 60_000)
  const client = await partyWith(api, 'ctrclient', 1)
  const provider = await partyWith(api, 'ctrprov', 2)
  const [C] = client.agents
  const [W, U] = provider.agents
  const name = uniqueName('ctr')
  const scope = `${name}: upgrade the parser and keep the tests green`
  // a reserved example domain: no one can register it (a github.com org name in the public export anyone could take)
  const repo = `https://example.org/fesuite/${name}`
  let ref = ''
  let cBefore = 0
  let uBefore = 0

  const readContract = async () => {
    const r = await api.json('GET', `/api/v1/contracts/agent/${encodeURIComponent(C.did)}`, { token: client.dev.token })
    const list: any[] = Array.isArray(r.body) ? r.body : []
    return list.find((c) => String(c.scope_description || '').startsWith(name)) || null
  }
  const card = (p: typeof page) => p.locator('.contract-card').filter({ hasText: name })

  await steps.run('provider-bonded', 'ui:developer', async () => {
    await expect.poll(() => agentBalance(api, C.token), { timeout: 45_000, message: 'the client holds its grant' }).toBeGreaterThan(AMOUNT)
    await expect.poll(() => agentBalance(api, W.token), { timeout: 45_000, message: 'the wallet holds its grant' }).toBeGreaterThan(250)
    await bondFrom(api, provider.dev, U.did, W.did)
    cBefore = await agentBalance(api, C.token)
    uBefore = await agentBalance(api, U.token)
    return `client holds ${cBefore}; provider bonded from its wallet, holds ${uBefore}`
  })

  await seedSession(context, client.dev.token)
  await seedVault(context, client, C.did)

  await steps.run('propose', 'ui:agent', async () => {
    await openRoute(page, '/contracts')
    await waitActing(page, C.did)
    await page.locator('[data-tour="ctr-new"]').click()
    const dialog = page.getByRole('dialog', { name: /propose contract/i })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('#ctr-create-client'), 'the client is the acting agent').toHaveValue(C.did)
    await dialog.locator('#ctr-create-scope').fill(scope)
    await dialog.locator('#ctr-create-repo').fill(repo)
    const amount = dialog.locator('#ctr-create-amount')
    await amount.fill('1.5')
    await expect(dialog.locator('[data-testid="ctr-create-amount-warn"]'), 'a fraction of a unit is refused on the page').toBeVisible()
    await expect(dialog.getByRole('button', { name: /^propose contract$/i })).toBeDisabled()
    await amount.fill(String(AMOUNT))
    await dialog.locator('.tp-kv-row input').nth(0).fill('tests')
    await dialog.locator('.tp-kv-row input').nth(1).fill('green')
    await stillFrame(page)
    await a11y(page, 'contract-propose')
    await dialog.getByRole('button', { name: /^propose contract$/i }).click()
    await expect(dialog).toHaveCount(0)
    await expect.poll(async () => (await readContract())?.status, { timeout: 30_000 }).toBe('PROPOSED')
    const c = await readContract()
    ref = String(c.ref || c.id)
    expect(c.payment_amount, 'the amount the page took').toBe(AMOUNT)
    expect(c.client_agent_did).toBe(C.did)
    expect(c.acceptance_criteria).toEqual({ tests: 'green' })
    expect(await agentBalance(api, C.token), 'nothing is escrowed before acceptance').toBeCloseTo(cBefore, 6)
    return `proposed ${ref}, ${AMOUNT} units, nothing escrowed yet`
  })

  const prov = await openAs(provider.dev.token)
  await seedVault(prov.context(), provider, U.did)

  await steps.run('provider-accepts', 'ui:agent', async () => {
    await openRoute(prov, '/contracts')
    await waitActing(prov, U.did)
    await expect(card(prov), 'the proposal is on the provider\'s board').toBeVisible({ timeout: 30_000 })
    await card(prov).locator('.cc-btn--cyan').click()
    const dialog = prov.getByRole('dialog', { name: /accept contract/i })
    await expect(dialog).toBeVisible()
    await expect(dialog.locator('#ctr-accept-as'), 'the acting agent accepts').toHaveValue(U.did)
    await stillFrame(prov)
    await a11y(prov, 'contract-accept')
    await dialog.getByRole('button', { name: /^accept contract$/i }).click()
    await expect(dialog).toHaveCount(0)
    await expect.poll(async () => (await readContract())?.status, { timeout: 30_000 }).toBe('ACCEPTED')
    expect((await readContract())?.upgrader_agent_did).toBe(U.did)
    await expect.poll(async () => cBefore - (await agentBalance(api, C.token)), { timeout: 30_000, message: 'the client\'s payment is escrowed at acceptance' })
      .toBeCloseTo(AMOUNT, 6)
    return `accepted; ${AMOUNT} escrowed from the client`
  })

  await steps.run('provider-submits-work', 'ui:agent', async () => {
    const drawer = prov.getByRole('dialog', { name: /contract/i })
    await expect(drawer, 'acceptance opens the contract').toBeVisible()
    await drawer.locator('.drawer-footer').getByRole('button', { name: /submit work/i }).click()
    const dialog = prov.getByRole('dialog', { name: /submit work/i })
    await expect(dialog).toBeVisible()
    await dialog.locator('#ctr-submit-pr').fill(`${repo}/pull/1`)
    await stillFrame(prov)
    await a11y(prov, 'contract-submit')
    await dialog.getByRole('button', { name: /submit for review/i }).click()
    await expect(dialog).toHaveCount(0)
    await expect.poll(async () => (await readContract())?.status, { timeout: 30_000 }).toBe('PENDING_MERGE')
    expect((await readContract())?.pr_url).toBe(`${repo}/pull/1`)
    return 'pull request submitted; the contract waits on the client'
  })

  await steps.run('client-approves-and-pays', 'ui:agent', async () => {
    // The client's page has sat open since the proposal (its drawer too). A person closes the drawer and refreshes.
    const drawer = page.getByRole('dialog', { name: /contract/i })
    if (await drawer.isVisible().catch(() => false)) {
      await page.keyboard.press('Escape')
      await expect(drawer, 'Escape closes the contract drawer').toHaveCount(0)
    }
    await page.getByRole('button', { name: /^↻?\s*refresh$/i }).click()
    await expect(card(page).locator('.cc-btn--green'), 'the client is asked to approve').toBeVisible({ timeout: 30_000 })
    await card(page).locator('.cc-btn--green').click()
    const dialog = page.getByRole('dialog', { name: /approve completion/i })
    await expect(dialog).toBeVisible()
    await expect(dialog, 'the dialog says the escrow is what is released').toContainText(/escrow/i)
    const pay = dialog.getByRole('button', { name: /execute payment/i })
    await dialog.locator('#ctr-approve-confirm').fill(String(AMOUNT + 1))
    await expect(pay, 'a wrong amount does not arm the payment').toBeDisabled()
    await dialog.locator('#ctr-approve-confirm').fill(String(AMOUNT))
    await stillFrame(page)
    await a11y(page, 'contract-approve')
    await pay.click()
    await expect(dialog).toHaveCount(0)
    await expect.poll(async () => (await readContract())?.status, { timeout: 45_000 }).toBe('COMPLETED')
    return 'approved; the contract is complete'
  })

  await steps.run('money-moved-once', 'ui:agent', async () => {
    await expect.poll(async () => (await agentBalance(api, U.token)) - uBefore, { timeout: 45_000, message: 'the provider is paid' })
      .toBeGreaterThan(0)
    await settle(page)
    const paid = (await agentBalance(api, U.token)) - uBefore
    const spent = cBefore - (await agentBalance(api, C.token))
    expect(spent, 'the client paid the contract once').toBeCloseTo(AMOUNT, 6)
    expect(paid, 'the provider received the escrow (less any fee), once').toBeGreaterThan(AMOUNT * 0.9)
    expect(paid).toBeLessThanOrEqual(AMOUNT + 1e-9)
    return `client -${spent.toFixed(6)}, provider +${paid.toFixed(6)}`
  })

  await steps.run('the-board-says-done', 'ui:agent', async () => {
    const drawer = prov.getByRole('dialog', { name: /contract/i })
    if (await drawer.isVisible().catch(() => false)) {
      await prov.keyboard.press('Escape')
      await expect(drawer).toHaveCount(0)
    }
    await prov.getByRole('button', { name: /^↻?\s*refresh$/i }).click()
    await expect(card(prov).locator('.cc-status-badge')).toContainText(/complete|done/i)
    await expect(card(prov).locator('.cc-actions button'), 'a finished contract offers no action').toHaveCount(0)
    return 'both boards show the contract complete'
  })
})
