/**
 * An account's security through the page (§FESUITE; the MCP tester's notifications_2fa, authRecoverAccount and
 * self_account_on_throwaway): turn on two-factor sign-in from the secret the page shows (the suite computes the code a
 * phone would), sign out and back in through the 2FA prompt, turn it off; then change the password the way Settings
 * offers it, with a recovery key, and sign in with the new one. Every state is read back from the API.
 */
import { test, expect } from '../support/fixtures'
import { ledger, newPassword, registerDeveloper, seedSession } from '../support/accounts'
import { currentRoute, firstOf, openRoute, settle, signedIn } from '../support/ui'
import { nextStepAfter, totp, totpStep } from '../support/totp'

test('security_2fa_and_recovery_password', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const dev = await registerDeveloper(api, 'secdev')
  await seedSession(context, dev.token)
  let secret = ''
  let usedStep = 0
  const twoFaEnabled = async (token: string) => {
    const r = await api.json('GET', '/api/v1/auth/2fa/status', { token })
    return !!r.body?.enabled
  }
  const typeCode = async (code: string) => {
    const boxes = page.locator('input[maxlength="1"][inputmode="numeric"]:visible')
    await expect(boxes).toHaveCount(6)
    for (let i = 0; i < 6; i++) await boxes.nth(i).fill(code[i])
  }

  await steps.run('enable-2fa', 'ui:developer', async () => {
    await openRoute(page, '/settings?tab=security')
    await page.getByRole('button', { name: /enable two-factor/i }).click()
    await page.locator('input[placeholder="Enter your password"]').fill(dev.password)
    await page.getByRole('button', { name: /^continue$/i }).click()
    const shown = page.locator('code').filter({ hasText: /^[A-Z2-7 ]{16,}$/ }).first()
    await expect(shown).toBeVisible()
    secret = (await shown.innerText()).replace(/\s+/g, '')
    await a11y(page, 'twofa-setup')
    await page.getByRole('button', { name: /continue to verification/i }).click()
    usedStep = totpStep()
    await typeCode(totp(secret, usedStep))
    await page.getByRole('button', { name: /enable 2fa/i }).click()
    await page.getByRole('button', { name: /saved my codes/i }).click()
    expect(await twoFaEnabled(dev.token), 'the API says 2FA is on').toBe(true)
    return '2FA on from the shown secret (secret and codes not recorded)'
  })

  await steps.run('sign-in-through-2fa', 'ui:developer', async () => {
    await page.locator('.sidebar-logout').first().click()
    await page.waitForFunction(() => location.hash.startsWith('#/login'))
    await page.locator('input[autocomplete="username"]').fill(dev.email)
    await page.locator('input[autocomplete="current-password"]').fill(dev.password)
    await page.locator('form button[type="submit"]').click()
    await nextStepAfter(usedStep)  // the server refuses a code it has already accepted
    await typeCode(totp(secret))
    // The prompt submits itself on the sixth digit; a Verify button is pressed only if it is still waiting.
    const verify = page.getByRole('button', { name: /^verify$/i })
    const arrived = page.locator('.sidebar-logout')
    if ((await firstOf(page, [arrived, verify], 30_000)) === 1) await verify.click()
    await page.waitForFunction(() => !location.hash.startsWith('#/login'), undefined, { timeout: 30_000 })
    expect(await signedIn(page)).toBe(true)
    return `signed in through the 2FA prompt, landed on ${await currentRoute(page)}`
  })

  await steps.run('disable-2fa', 'ui:developer', async () => {
    await openRoute(page, '/settings?tab=security')
    await page.getByRole('button', { name: /^disable 2fa$/i }).click()
    const pw = page.locator('#disable-password')
    await expect(pw).toBeVisible()
    await a11y(page, 'twofa-disable')
    await pw.fill(dev.password)
    await page.getByRole('button', { name: /^disable 2fa$/i }).last().click()
    // the outcome, not the press: the modal closes on success and the page says 2FA is off
    await expect(pw, 'the disable dialog closes on success').toHaveCount(0)
    await expect(page.getByRole('button', { name: /enable two-factor/i })).toBeVisible()
    // read back: a password-only sign-in now gets a token (with 2FA on it answers 200 and asks for a code)
    const token = await api.login(dev.email, dev.password)
    expect(await twoFaEnabled(token), 'the API says 2FA is off').toBe(false)
    return '2FA off, read back'
  })

  await steps.run('change-password-with-recovery-key', 'ui:developer', async () => {
    expect(dev.recoveryKeys.length, 'registration issued recovery keys').toBeGreaterThan(0)
    await openRoute(page, '/settings?tab=security')
    await page.locator('[data-testid="st-change-password"]').click()
    await page.waitForFunction(() => location.hash.startsWith('#/forgot-password'))
    await expect(page.locator('[data-testid="fp-recovery-key"]'), 'the recovery-key step, not a bounce home').toBeVisible()
    await a11y(page, 'recovery-key-step')
    await page.locator('input[placeholder="agent@example.com"]').fill(dev.email)
    await page.locator('[data-testid="fp-recovery-key"]').fill(dev.recoveryKeys[0])
    await page.locator('form button[type="submit"]').click()
    const fresh = newPassword()
    const pw = page.locator('input[type="password"]')
    await expect(pw).toHaveCount(2)
    await pw.nth(0).fill(fresh)
    await pw.nth(1).fill(fresh)
    await page.locator('form button[type="submit"]').click()
    ledger('developer', { name: dev.name, email: dev.email, password: fresh, via: 'recovery-key change' })
    await settle(page)
    const old = await api.json('POST', '/api/v1/auth/login', { form: { username: dev.email, password: dev.password } })
    expect(old.status, 'the old password no longer signs in').toBe(401)
    await api.login(dev.email, fresh)
    dev.password = fresh
    return 'changed through the recovery key; the old password refused, the new one signs in'
  })
})
