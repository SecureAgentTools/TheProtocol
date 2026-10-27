/**
 * The first hour, as a person lives it (§FESUITE; the MCP tester's auth_register_and_logout, through the page):
 * the register form, the confirmation that must say what THIS frame does (verification mail or "ready to use"), the
 * recovery keys shown once, the first sign-in with the first-visit banner and tour, sign-out, the second arrival, and a
 * wrong password refused without ending anything.
 */
import { test, expect } from '../support/fixtures'
import { ledger, newPassword } from '../support/accounts'
import { uniqueName } from '../support/env'
import { currentRoute, firstOf, loginWithForm, openRoute, settle, signedIn, toast } from '../support/ui'

test('onboarding_register_login_logout @first-visit', async ({ page, steps, api, a11y, capture }) => {
  const name = uniqueName('onboard')
  const email = `${name}@throwaway-pl.example.com`
  const password = newPassword()
  let config: { email_verification_required?: boolean; beta_invite_required?: boolean } = {}

  await steps.run('registration-config', 'ui:public', async () => {
    const r = await api.json('GET', '/api/v1/auth/registration-config')
    expect(r.status).toBe(200)
    config = r.body || {}
    return `verification ${config.email_verification_required ? 'required' : 'off'}, invite ${config.beta_invite_required ? 'required' : 'open'}`
  })

  if (config.beta_invite_required) {
    steps.notMeasured('register-form', 'ui:public', 'this frame registers by invitation only: the invited onboarding is its own lifecycle')
    test.skip(true, 'invitation-only frame')
  }

  await steps.run('register-form', 'ui:public', async () => {
    await openRoute(page, '/register')
    await a11y(page, 'register-form')
    const form = page.locator('form.nc-form')
    await form.locator('input[type="text"]').first().fill(name)
    await form.locator('input[type="email"]').fill(email)
    const pw = form.locator('input[type="password"]')
    await expect(pw).toHaveCount(2)
    await pw.nth(0).fill(password)
    await pw.nth(1).fill(password)
    await page.locator('#accept-terms').check()
    await page.locator('#confirm-age').check()
    await form.locator('button[type="submit"]').click()
    await expect(page.locator('.nc-confirm-title')).toBeVisible()
    ledger('developer', { name, email, password, via: 'ui-register' })
    return (await page.locator('.nc-confirm-title').innerText()).trim()
  })

  await steps.run('confirmation-says-what-this-frame-does', 'ui:public', async () => {
    const title = (await page.locator('.nc-confirm-title').innerText()).trim()
    const resend = page.locator('.nc-resend-btn')
    if (config.email_verification_required) {
      expect(title).toMatch(/TRANSMISSION SENT|delivery/i)
      await expect(resend).toBeVisible()
    } else {
      // The account is ready: telling the person to wait for a mail that will never come is the defect this guards.
      expect(title).toMatch(/ACCOUNT CREATED/i)
      await expect(resend).toHaveCount(0)
      await expect(page.getByText(/verification link dispatched/i)).toHaveCount(0)
    }
    await a11y(page, 'register-confirmation')
    return title
  })

  await steps.run('recovery-keys-shown-once', 'ui:public', async () => {
    const keys = page.locator('.nc-recovery-key')
    const n = await keys.count()
    expect(n).toBeGreaterThan(0)
    return `${n} recovery keys on screen (not recorded)`
  })

  if (config.email_verification_required) {
    steps.notMeasured('first-sign-in', 'ui:developer', 'this frame verifies by mail: the mailed-link leg runs where a mail sink is configured')
    test.skip(true, 'verification by mail')
  }

  await steps.run('first-sign-in', 'ui:developer', async () => {
    const landed = await loginWithForm(page, email, password)
    expect(await signedIn(page)).toBe(true)
    expect(landed).not.toMatch(/^\/login/)
    // A person who accepted the terms a minute ago must not be asked to accept them again.
    await expect(page.locator('[data-testid="legal-reconsent-later"]')).toHaveCount(0)
    return `landed on ${landed}`
  })

  await steps.run('first-visit-banner-and-tour', 'ui:developer', async () => {
    const outcomes = [page.locator('[data-testid="beta-dismiss"]'), page.locator('.gt-skip')]
    const seen: string[] = []
    for (let i = 0; i < 2; i++) {
      const which = await firstOf(page, outcomes, 8_000).catch(() => -1)
      if (which < 0) break
      await outcomes[which].first().click()
      seen.push(which === 0 ? 'beta banner dismissed' : 'tour skipped')
      await settle(page)
    }
    return seen.length ? seen.join(', ') : 'neither the banner nor a tour appeared'
  })

  await steps.run('home-renders', 'ui:developer', async () => {
    const route = await currentRoute(page)
    await expect(page.locator('main, [role="main"], #app > *').first()).toBeVisible()
    await a11y(page, `home-${route.replace(/\W+/g, '-')}`)
    return route
  })

  await steps.run('sign-out', 'ui:developer', async () => {
    await page.locator('.sidebar-logout').first().click()
    await page.waitForFunction(() => location.hash.startsWith('#/login'), undefined, { timeout: 20_000 })
    expect(await signedIn(page)).toBe(false)
    const said = await toast(page, 'info', /logged out/i)
    return `signed out to ${await currentRoute(page)} (${said.slice(0, 60)})`
  })

  await steps.run('second-arrival', 'ui:developer', async () => {
    const landed = await loginWithForm(page, email, password)
    expect(await signedIn(page)).toBe(true)
    return `landed on ${landed}`
  })

  await steps.run('wrong-password-refused', 'ui:public', async () => {
    await page.locator('.sidebar-logout').first().click()
    await page.waitForFunction(() => location.hash.startsWith('#/login'), undefined, { timeout: 20_000 })
    capture.allow(/POST \/api\/v1\/auth\/login$/, 401, 'a wrong password is refused')
    await openRoute(page, '/login')
    await page.locator('input[autocomplete="username"]').fill(email)
    await page.locator('input[autocomplete="current-password"]').fill(`${password}-wrong`)
    await page.locator('form button[type="submit"]').click()
    await expect(page.locator('.nc-alert-danger, .nc-alert-error, [role="alert"]').first()).toBeVisible()
    expect(await currentRoute(page)).toMatch(/^\/login/)
    expect(await signedIn(page)).toBe(false)
    return (await page.locator('.nc-alert-danger, .nc-alert-error, [role="alert"]').first().innerText()).replace(/\s+/g, ' ').slice(0, 120)
  })
})
