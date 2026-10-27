/**
 * Quick onboarding through the page (2026-10-09, his word): /onboarding issues an agent identity from a name, lists the
 * developer's agents with their balances hidden until asked, and resets an agent's credentials with the account
 * password. Every claim the page makes is read back: the DID on screen is the one the registry lists, the wallet it
 * calls unlisted is unlisted on the registry, the console acts as the agent it says it acts as, a "Valid card" badge is
 * the validator's own answer about the stored card, the bond sentence states the registry's own rule, the pair shown
 * once signs in, a credited starting balance is on the ledger, the balance revealed is the one the agent's own ledger
 * reads, and after a reset the client ID changed, the old secret no longer signs in and the new one does.
 *
 * Secrets are read from the page into memory and never recorded: every comparison that involves one is a boolean (a
 * failing `toContainText(secret)` or `not.toBe(secret)` would print the secret into the report), and a secret is
 * revealed only for the instant it is read, so no a11y record or failure screenshot carries it.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, ledger, registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { firstOf, openRoute, pinia } from '../support/ui'

test('quick_onboarding_issue_list_reset', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(6 * 60_000)
  const dev = await registerDeveloper(api, 'qodev')
  await seedSession(context, dev.token)
  const agentName = uniqueName('qoagent')
  let did = ''
  let clientId = ''
  let secret = ''
  let fundingKind = ''

  const mint = (username: string, password: string) =>
    api.json('POST', '/api/v1/auth/agent/token', { form: { username, password } })
  const listed = async () => {
    const r = await api.json('GET', '/api/v1/developers/me/agents', { token: dev.token })
    expect(r.status).toBe(200)
    return (Array.isArray(r.body) ? r.body : []) as Array<Record<string, any>>
  }
  const actingDid = () => pinia(page, 'auth', (s: any) => String(s.activeAgent?.did || ''))
  const row = () => page.locator(`[data-testid="qo-agent-row"][data-did="${did}"]`)

  await steps.run('empty-page-offers-the-first-identity', 'ui:developer', async () => {
    expect(await openRoute(page, '/onboarding')).toBe('/onboarding')
    await expect(page.locator('[data-testid="quick-onboarding"]')).toBeVisible()
    await expect(page.locator('[data-testid="qo-agents"]')).toHaveAttribute('data-state', 'ready', { timeout: 30_000 })
    await expect(page.locator('[data-testid="qo-agents-empty"]')).toBeVisible()
    // a fresh account's first identity is its wallet agent (§WALLETAGENT), named "Wallet" until the person renames it
    await expect(page.locator('[data-testid="qo-wallet-note"]')).toBeVisible()
    await expect(page.locator('[data-testid="qo-name"]')).toHaveValue('Wallet')
    await a11y(page, 'quick-onboarding-empty')
    return 'no agent, the issue card names the first identity the wallet'
  })

  await steps.run('the-i-explains', 'ui:developer', async () => {
    const toggle = page.locator('[data-testid="qo-info-toggle"]')
    await toggle.click()
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    const explainer = page.locator('[data-testid="qo-explainer"]')
    await expect(explainer).toBeVisible()
    // the Discover line is the registry's own bond rule, read back here: the amount and the currency it states
    const cfg = await api.json('GET', '/api/v1/reputation-bond/config')
    expect(cfg.status, 'the registry states its bond rule').toBe(200)
    const discover = explainer.locator('[data-testid="qo-explainer-discover"]')
    await expect(discover).toHaveAttribute('data-bond', 'read', { timeout: 15_000 })
    if (cfg.body?.mode === 'enforce') {
      const amount = new Intl.NumberFormat('en', { maximumFractionDigits: 6 }).format(Number(cfg.body.amount))
      const cur = String(cfg.body.currency || '').trim()
      await expect(discover).toContainText(`reputation bond of ${amount}${cur ? ` ${cur}` : ''}`)
    } else {
      await expect(discover).toContainText('asks for no reputation bond')
    }
    // the MCP tool is named as an MCP client lists it
    await expect(explainer).toContainText('theprotocol_getAgentToken')
    await a11y(page, 'quick-onboarding-explainer')
    await toggle.click()
    await expect(explainer).toBeHidden()
    return `bond rule shown as the registry states it (${cfg.body?.mode} ${cfg.body?.amount ?? ''} ${cfg.body?.currency ?? ''})`
  })

  await steps.run('issue-an-identity', 'ui:developer', async () => {
    await page.locator('[data-testid="qo-name"]').fill(agentName)
    await page.locator('[data-testid="qo-issue-btn"]').click()
    const result = page.locator('[data-testid="qo-result"]')
    await expect(result).toBeVisible({ timeout: 60_000 })
    did = (await result.locator('[data-testid="qo-result-did"]').innerText()).trim()
    expect(did.startsWith('did:'), 'a DID on the identity card').toBe(true)
    ledger('agent', { did, name: agentName, owner: dev.email, via: 'ui' })
    const mine = (await listed()).find((a) => a.did === did)
    expect(mine, 'the DID on screen is one the registry lists for this developer').toBeTruthy()
    expect(mine!.name).toBe(agentName)
    expect(String(mine!.status || 'active')).toBe('active')
    const tags: string[] = Array.isArray(mine!.card_data?.tags) ? mine!.card_data.tags : []
    expect(tags, 'the first identity is the wallet agent').toContain('wallet')
    // the page says the wallet is kept out of Discover; the registry's card says the same
    await expect(result.locator('[data-testid="qo-wallet-listing"]')).toHaveAttribute('data-listing', 'unlisted', { timeout: 30_000 })
    const stored = await api.json('GET', `/api/v1/agent-cards/${encodeURIComponent(did)}`, { token: dev.token })
    expect(stored.status).toBe(200)
    expect(stored.body?.unlisted, 'the registry holds the wallet unlisted').toBe(true)
    // its stored card was read back onto the page; a "Valid card" badge is the validator's answer about that card
    await expect(page.locator('[data-testid="qo-card"]')).toHaveAttribute('data-state', 'ready', { timeout: 30_000 })
    const badge = page.locator('[data-testid="qo-card-valid"]')
    await badge.waitFor({ state: 'visible', timeout: 10_000 }).catch(() => { /* no badge: no claim to check */ })
    let validated = 'no badge'
    if (await badge.isVisible()) {
      const v = await api.json('POST', '/api/v1/utils/validate-card', { body: { card_data: stored.body?.card_data } })
      expect(v.status).toBe(200)
      expect(v.body?.is_valid, 'the validator says the stored card is valid').toBe(true)
      expect(String(v.body?.detail || ''), 'the validator checked it').not.toMatch(/skipped/i)
      validated = 'badge = validator'
    }
    // a fresh console acted as no agent, so it acts as the new identity now: the chip, and the store behind it
    await expect(result.locator('[data-testid="qo-result-acting"]')).toBeVisible({ timeout: 30_000 })
    expect(await actingDid(), 'the console acts as the new identity').toBe(did)
    const funding = result.locator('[data-testid="qo-funding"]')
    fundingKind = (await funding.count()) ? String(await funding.getAttribute('data-kind')) : ''
    await a11y(page, 'quick-onboarding-issued')
    return `${did.slice(0, 28)}… listed, wallet unlisted, acting, ${validated}, starting balance ${fundingKind || 'none due'}`
  })

  await steps.run('credentials-shown-once-and-working', 'ui:developer', async () => {
    const result = page.locator('[data-testid="qo-result"]')
    clientId = (await result.locator('[data-testid="qo-cred-client-id"]').innerText()).trim()
    const mine = (await listed()).find((a) => a.did === did)
    expect(clientId).toBe(String(mine?.client_id || ''))
    const shownSecret = result.locator('[data-testid="qo-cred-secret"]')
    await expect(shownSecret).toHaveAttribute('data-revealed', '0')
    await result.locator('[data-testid="qo-cred-reveal"]').click()
    await expect(shownSecret).toHaveAttribute('data-revealed', '1')
    secret = (await shownSecret.innerText()).trim()
    await result.locator('[data-testid="qo-cred-reveal"]').click()
    await expect(shownSecret).toHaveAttribute('data-revealed', '0')
    expect(secret.length > 16, 'a secret was shown').toBe(true)
    // the "use it" command never carries the secret (a boolean: a failing text matcher would print it)
    const snippet = await page.locator('[data-testid="qo-use-snippet"]').innerText()
    expect(snippet.includes(secret), 'the sign-in command carries no secret').toBe(false)
    const r = await mint(clientId, secret)
    expect(r.status, 'the pair shown on the card signs in as the agent').toBe(200)
    return 'the shown pair signs in (the secret is not recorded)'
  })

  await steps.run('balance-hidden-then-revealed', 'ui:developer', async () => {
    const cell = row().locator('[data-testid="qo-row-balance"]')
    await expect(cell).toHaveAttribute('data-state', 'hidden', { timeout: 30_000 })
    const masked = await cell.innerText()
    expect(masked).toContain('••••')
    expect(masked, 'no number while hidden').not.toMatch(/\d/)
    expect(await cell.locator('[data-amount]').count()).toBe(0)
    const eye = page.locator('[data-testid="qo-eye"]')
    await expect(eye).toHaveAttribute('data-shown', '0')
    await expect(eye).toContainText('Show balances')
    await eye.click()
    await expect(eye).toHaveAttribute('data-shown', '1')
    await expect(eye).toContainText('Hide balances')
    await expect(cell).toHaveAttribute('data-state', /^(ok|unread)$/, { timeout: 30_000 })
    expect(await cell.getAttribute('data-state'), 'the live balance read answered').toBe('ok')
    const shown = Number(await cell.locator('[data-amount]').getAttribute('data-amount'))
    const tok = (await mint(clientId, secret)).body?.access_token as string
    const ledgerValue = await agentBalance(api, tok)
    expect(shown, 'the revealed balance is the one the agent\'s ledger reads').toBeCloseTo(ledgerValue, 6)
    // "its starting balance was credited" is a claim about the ledger
    if (fundingKind === 'credited') expect(ledgerValue, 'a credited starting balance is on the ledger').toBeGreaterThan(0)
    await a11y(page, 'quick-onboarding-balances')
    await eye.click()
    await expect(cell).toHaveAttribute('data-state', 'hidden')
    expect(await cell.innerText()).not.toMatch(/\d/)
    return `masked, then ${shown} as the ledger reads it (starting balance ${fundingKind || 'none due'}), then masked again`
  })

  // the registry allows 3 reset attempts an hour from one address and counts every request, a refused password
  // included: where a run soon after another meets the limit, the dialog says so and the rest is NOT MEASURED
  capture.allow(/POST \/api\/v1\/onboard\/agents\/.+\/reset-credentials$/, 403, 'a wrong account password is refused on purpose')
  capture.allow(/POST \/api\/v1\/onboard\/agents\/.+\/reset-credentials$/, 429,
    'the registry allows 3 reset attempts an hour from one address; a run soon after another can meet the limit')
  const firstAnswer = await steps.run('reset-dialog-answers-a-wrong-password', 'ui:developer', async () => {
    await row().locator('[data-testid="qo-row-reset"]').click()
    const dialog = page.locator('[data-testid="qo-reset-dialog"]')
    await expect(dialog).toBeVisible()
    await expect(page.locator('[data-testid="qo-reset-password"]')).toBeFocused()
    await a11y(page, 'quick-onboarding-reset')
    await dialog.locator('[data-testid="qo-reset-password"]').fill(`${dev.password}-wrong`)
    await dialog.locator('[data-testid="qo-reset-submit"]').click()
    const err = dialog.locator('[data-testid="qo-reset-error"]')
    const i = await firstOf(page, [
      dialog.locator('[data-testid="qo-reset-error"][data-kind="wrong_password"]'),
      dialog.locator('[data-testid="qo-reset-error"][data-kind="rate_limited"]'),
      err,
    ], 30_000)
    if (i === 2) throw new Error(`the dialog answered with another refusal: ${(await err.innerText()).trim()}`)
    return i === 0 ? 'wrong_password' : 'rate_limited'
  })

  if (firstAnswer === 'rate_limited') {
    const why = 'the registry\'s 3-attempts-an-hour limit for this address was spent before this run; the dialog said so'
    for (const name of ['reset-with-a-wrong-password', 'reset-with-the-right-password', 'new-pair-replaces-the-old']) {
      steps.notMeasured(name, 'ui:developer', why)
    }
    return
  }

  await steps.run('reset-with-a-wrong-password', 'ui:developer', async () => {
    const dialog = page.locator('[data-testid="qo-reset-dialog"]')
    await expect(dialog.locator('[data-testid="qo-reset-error"]')).toContainText('That password is not right')
    await expect(dialog).toBeVisible()
    // the call ended: the field is empty and holds the focus, where the person acts on the answer
    await expect(dialog.locator('[data-testid="qo-reset-password"]')).toHaveValue('')
    await expect(dialog.locator('[data-testid="qo-reset-password"]')).toBeFocused()
    // still signed in: the page did not move, and the developer token still answers
    expect(await page.evaluate(() => location.hash)).toContain('/onboarding')
    expect((await api.json('GET', '/api/v1/developers/me', { token: dev.token })).status).toBe(200)
    // nothing changed on the registry
    expect(String((await listed()).find((a) => a.did === did)?.client_id || '')).toBe(clientId)
    await a11y(page, 'quick-onboarding-reset-refused')
    return 'refused in the dialog, which stays open with the field cleared and focused; still signed in; client ID unchanged'
  })

  const outcome = await steps.run('reset-with-the-right-password', 'ui:developer', async () => {
    const dialog = page.locator('[data-testid="qo-reset-dialog"]')
    await dialog.locator('[data-testid="qo-reset-password"]').fill(dev.password)
    await dialog.locator('[data-testid="qo-reset-submit"]').click()
    const err = dialog.locator('[data-testid="qo-reset-error"]')
    const i = await firstOf(page, [
      dialog.locator('[data-testid="qo-reset-done"]'),
      dialog.locator('[data-testid="qo-reset-error"][data-kind="rate_limited"]'),
      err,
    ], 30_000)
    // any other refusal fails the step with the dialog's own sentence, not with "none of the outcomes appeared"
    if (i === 2) throw new Error(`the dialog answered with a refusal: ${(await err.innerText()).trim()}`)
    return i === 0 ? 'reset' : 'rate-limited'
  })

  if (outcome === 'rate-limited') {
    steps.notMeasured('new-pair-replaces-the-old', 'ui:developer',
      'the registry\'s 3-attempts-an-hour limit for this address was spent before this run; the dialog said so')
    return
  }

  await steps.run('new-pair-replaces-the-old', 'ui:developer', async () => {
    const done = page.locator('[data-testid="qo-reset-done"]')
    // focus is on the sentence that says the secret is shown only now; Esc does not throw the new pair away
    await expect(page.locator('[data-testid="qo-reset-ok"]')).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(done).toBeVisible()
    const newClientId = (await done.locator('[data-testid="qo-cred-client-id"]').innerText()).trim()
    expect(newClientId === clientId, 'a new client ID').toBe(false)
    const newSecretEl = done.locator('[data-testid="qo-cred-secret"]')
    await done.locator('[data-testid="qo-cred-reveal"]').click()
    await expect(newSecretEl).toHaveAttribute('data-revealed', '1')
    const newSecret = (await newSecretEl.innerText()).trim()
    await done.locator('[data-testid="qo-cred-reveal"]').click()
    await expect(newSecretEl).toHaveAttribute('data-revealed', '0')
    expect(newSecret.length > 16, 'a new secret was shown').toBe(true)
    expect(newSecret === secret, 'the new secret is not the old one').toBe(false)
    // the console acted as this agent, so it signed in again with the new pair: the note, and the store behind it
    await expect(done.locator('[data-testid="qo-reset-reauth-done"]')).toBeVisible({ timeout: 30_000 })
    expect(await actingDid(), 'the console still acts as the agent it reset').toBe(did)
    await a11y(page, 'quick-onboarding-reset-done')
    // the registry: a new client ID; the old pair no longer signs in, the new one does
    expect(String((await listed()).find((a) => a.did === did)?.client_id || '')).toBe(newClientId)
    expect((await mint(clientId, secret)).status, 'the old pair is refused').toBe(401)
    expect((await mint(newClientId, newSecret)).status, 'the new pair signs in').toBe(200)
    await page.locator('[data-testid="qo-reset-finish"]').click()
    await expect(page.locator('[data-testid="qo-reset-dialog"]')).toHaveCount(0)
    await expect(row().locator('[data-testid="qo-row-client-id"]')).toHaveText(newClientId)
    return 'new client ID on the registry and the row; old pair 401, new pair 200; the console signed in again'
  })
})
