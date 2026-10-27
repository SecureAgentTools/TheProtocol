/**
 * Becoming a provider through the page (§FESUITE; the bond is the frame's gate to providing services: a Guild bid, a
 * contract acceptance, a paid card). A fresh account's first quick-create makes its wallet agent, which holds the
 * genesis grant; the second makes a worker, and the worker's birth sheet offers the bond, funded from the wallet. The
 * bond reads back as held, funded by the wallet, and the wallet paid it once. The same worker can then bid (the
 * Guild lifecycle drives that); here the gate itself is the subject.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, agentToken, ledger, registerDeveloper, seedSession } from '../support/accounts'
import { reputation, stillFrame } from '../support/commerce'
import { uniqueName } from '../support/env'
import { openRoute } from '../support/ui'

test('provider_bond_from_the_wallet', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'bonddev')
  await seedSession(context, dev.token)
  const workerName = uniqueName('worker')
  const cfg = (await api.json('GET', '/api/v1/reputation-bond/config')).body || {}
  let walletDid = ''
  let workerDid = ''

  const myAgents = async () => {
    const r = await api.json('GET', '/api/v1/developers/me/agents', { token: dev.token })
    return (Array.isArray(r.body) ? r.body : r.body?.agents || r.body?.items || []) as any[]
  }

  if (!cfg.mode || cfg.mode === 'off') {
    steps.notMeasured('bond', 'ui:developer', 'this frame asks no reputation bond (mode off)')
    return
  }

  await steps.run('first-agent-is-the-wallet', 'ui:developer', async () => {
    await openRoute(page, '/my-agents')
    await page.locator('.fleet-deploy-btn').first().click()
    await expect(page.locator('[data-testid="qa-wallet-lead"]'), 'a first agent is made as the wallet').toBeVisible()
    await page.locator('.qa-btn--primary').click()
    await expect(page.locator('.qa-success-hero')).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('[data-testid="qa-bond-door"]'), 'a wallet is not asked for a bond').toHaveCount(0)
    await expect.poll(async () => (await myAgents()).length, { timeout: 30_000 }).toBe(1)
    walletDid = String((await myAgents())[0].did)
    ledger('agent', { did: walletDid, owner: dev.email, via: 'page' })
    await expect(page.locator('[data-testid="qa-success-sub"]')).not.toHaveAttribute('data-held', 'unread', { timeout: 30_000 })
    await page.locator('.qa-close').click()
    return `wallet ${walletDid.slice(-12)}`
  })

  await steps.run('a-worker-is-offered-the-bond', 'ui:developer', async () => {
    await page.locator('.fleet-deploy-btn').first().click()
    await page.locator('input[placeholder="e.g., Pricing Oracle"]').fill(workerName)
    await page.locator('.qa-btn--primary').click()
    await expect(page.locator('.qa-success-hero')).toBeVisible({ timeout: 60_000 })
    const door = page.locator('[data-testid="qa-bond-door"]')
    await expect(door, 'the worker\'s birth sheet offers the bond').toHaveAttribute('data-bond', 'open')
    await expect(door).toContainText(String(cfg.amount))
    await expect(page.locator('[data-testid="qa-bond-wallet"]'), 'funded from the wallet').toBeVisible()
    await expect.poll(async () => (await myAgents()).length, { timeout: 30_000 }).toBe(2)
    workerDid = String((await myAgents()).find((a) => a.did !== walletDid)?.did || '')
    ledger('agent', { did: workerDid, name: workerName, owner: dev.email, via: 'page' })
    await stillFrame(page)
    await a11y(page, 'bond-door')
    return `worker ${workerDid.slice(-12)}, asked for ${cfg.amount} ${cfg.currency}`
  })

  await steps.run('bond-from-the-wallet', 'ui:developer', async () => {
    // the wallet's balance is read as the wallet: its keys are in this browser since the page made it
    const creds = await page.evaluate((d) => {
      try { const all = JSON.parse(localStorage.getItem('agentvault_agent_credentials') || '{}'); const c = all[d]; return c ? { clientId: c.client_id, clientSecret: c.client_secret } : null } catch { return null }
    }, walletDid)
    expect(creds, 'the page kept the wallet\'s keys').toBeTruthy()
    const wTok = await agentToken(api, { did: walletDid, clientId: creds!.clientId, clientSecret: creds!.clientSecret })
    const wBefore = await agentBalance(api, wTok)
    await page.locator('[data-testid="qa-bond-wallet"]').click()
    await expect(page.locator('[data-testid="qa-bond-door"]'), 'the sheet says the bond is locked').toHaveAttribute('data-bond', 'done', { timeout: 30_000 })
    const rep = await reputation(api, workerDid)
    expect(rep?.bond?.is_bonded, 'the registry holds the bond').toBe(true)
    expect(String(rep?.bond?.funded_by || ''), 'funded from the wallet').toMatch(/wallet/)
    await expect.poll(async () => wBefore - (await agentBalance(api, wTok)), { timeout: 30_000, message: 'the wallet paid the bond' })
      .toBeCloseTo(Number(cfg.amount), 6)
    return `bond ${rep.bond.amount} ${rep.bond.currency} held, the wallet paid it`
  })
})
