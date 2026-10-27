/**
 * The first hour on a phone (§FESUITE; lifecycle 01 at a Pixel 7's width and touch): the register form fits the screen,
 * the confirmation says what this frame does, the first sign-in lands in Pocket (the phone's home), the first-run tour
 * is skipped the way a thumb does it, sign-out is reachable from More, and the second arrival lands in Pocket again.
 * A phone drive never presses what a thumb cannot (no Escape, no hover).
 */
import { test, expect } from '../support/fixtures'
import { ledger, newPassword } from '../support/accounts'
import { uniqueName } from '../support/env'
import { currentRoute, firstOf, loginWithForm, openRoute, settle, signedIn, toast } from '../support/ui'
import { sideScroll } from '../support/pages'
import { reachable } from '../support/hygiene'

test('phone_onboarding_register_login_logout @phone-only @first-visit', async ({ page, steps, api, a11y }) => {
  test.setTimeout(5 * 60_000)
  const name = uniqueName('phoneon')
  const email = `${name}@throwaway-pl.example.com`
  const password = newPassword()
  const config: { email_verification_required?: boolean; beta_invite_required?: boolean } =
    (await api.json('GET', '/api/v1/auth/registration-config')).body || {}
  if (config.beta_invite_required || config.email_verification_required) {
    steps.notMeasured('phone-register', 'ui:public', 'this frame registers by invitation or verifies by mail: lifecycle 01 records how')
    test.skip(true, 'invitation or mail verification')
  }

  await steps.run('register-form-fits-the-phone', 'ui:public', async () => {
    await openRoute(page, '/register')
    expect(await sideScroll(page), 'the form does not scroll sideways').toBeLessThanOrEqual(1)
    await a11y(page, 'phone-register-form')
    const form = page.locator('form.nc-form')
    await form.locator('input[type="text"]').first().fill(name)
    await form.locator('input[type="email"]').fill(email)
    const pw = form.locator('input[type="password"]')
    await pw.nth(0).fill(password)
    await pw.nth(1).fill(password)
    await page.locator('#accept-terms').check()
    await page.locator('#confirm-age').check()
    const submit = form.locator('button[type="submit"]')
    expect(await reachable(page, submit), 'the submit button is the element a thumb lands on').toBe(true)
    await submit.tap()
    await expect(page.locator('.nc-confirm-title')).toBeVisible()
    ledger('developer', { name, email, password, via: 'ui-register-phone' })
    expect((await page.locator('.nc-confirm-title').innerText()).trim()).toMatch(/ACCOUNT CREATED/i)
    expect(await page.locator('.nc-recovery-key').count(), 'recovery keys are shown once').toBeGreaterThan(0)
    expect(await sideScroll(page), 'the confirmation does not scroll sideways').toBeLessThanOrEqual(1)
    await a11y(page, 'phone-register-confirmation')
    return 'registered on a phone; the confirmation and the keys fit'
  })

  await steps.run('first-sign-in-lands-in-pocket', 'ui:developer', async () => {
    const landed = await loginWithForm(page, email, password)
    expect(await signedIn(page)).toBe(true)
    expect(landed, 'a phone lands in Pocket').toMatch(/^\/pocket/)
    return `landed on ${landed}`
  })

  await steps.run('first-run-tour-skipped-by-thumb', 'ui:developer', async () => {
    // The tour is modal: its dim covers the beta banner's x (visible, not tappable), so a thumb skips the tour first.
    // Tap whichever control a finger actually lands on, never one under the dim.
    const seen: string[] = []
    const skip = page.locator('.gt-skip')
    const beta = page.locator('[data-testid="beta-dismiss"]')
    for (let i = 0; i < 4; i++) {
      const which = await firstOf(page, [skip, beta], 8_000).catch(() => -1)
      if (which < 0) break
      if (await skip.first().isVisible().catch(() => false) && await reachable(page, skip)) {
        await skip.first().tap(); seen.push('tour skipped')
      } else if (await reachable(page, beta)) {
        // the tour opens a moment after Pocket mounts, so its dim can land between the check and the tap: a tap it
        // intercepts is taken again next round (the tour first), never waited out
        if (await beta.first().tap({ timeout: 3_000 }).then(() => true).catch(() => false)) seen.push('beta banner dismissed')
        else { seen.push('the tour opened over the banner'); continue }
      } else {
        throw new Error('a first-run control is visible but nothing a thumb can reach dismisses it')
      }
      await settle(page)
    }
    expect(await sideScroll(page), 'Pocket home does not scroll sideways').toBeLessThanOrEqual(1)
    await a11y(page, 'phone-pocket-home')
    return seen.length ? seen.join(', ') : 'neither the banner nor a tour appeared'
  })

  await steps.run('sign-out-from-more', 'ui:developer', async () => {
    await openRoute(page, '/pocket/more')
    const out = page.locator('button.pm-out')
    await out.scrollIntoViewIfNeeded()
    expect(await reachable(page, out), 'Sign out is the element a thumb lands on').toBe(true)
    await a11y(page, 'phone-pocket-more')
    await out.tap()
    await page.waitForFunction(() => location.hash.startsWith('#/login'), undefined, { timeout: 20_000 })
    expect(await signedIn(page)).toBe(false)
    const said = await toast(page, 'info', /logged out/i).catch(() => 'no toast')
    return `signed out to ${await currentRoute(page)} (${said.slice(0, 50)})`
  })

  await steps.run('second-arrival-lands-in-pocket', 'ui:developer', async () => {
    const landed = await loginWithForm(page, email, password)
    expect(landed, 'the second arrival lands in Pocket too').toMatch(/^\/pocket/)
    return `landed on ${landed}`
  })
})
