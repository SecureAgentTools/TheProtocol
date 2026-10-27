/**
 * Leaving and staying (§FESUITE; the MCP tester's requestAccountDeletion / cancelAccountDeletion on its throwaway):
 * the danger zone asks for the phrase and the password, starts the cooling-off countdown, the whole console says so
 * (the pending-deletion banner), and the person changes their mind and keeps the account. Read back each time.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { openRoute, settle } from '../support/ui'

test('account_deletion_request_and_cancel', async ({ page, context, steps, api, a11y }) => {
  const dev = await registerDeveloper(api, 'leavedev')
  await seedSession(context, dev.token)
  const status = async () => String((await api.json('GET', '/api/v1/account/deletion-status', { token: dev.token })).body?.deletion_status || '')

  await steps.run('request-deletion', 'ui:developer', async () => {
    await openRoute(page, '/settings?tab=security')
    await page.locator('.st-danger-btn').first().click()
    const phrase = page.locator('input.st-danger-input').first()
    await expect(phrase).toBeVisible()
    await a11y(page, 'deletion-form')
    await phrase.fill(String(await phrase.getAttribute('placeholder')))
    await page.locator('input.st-danger-input[type="password"]').fill(dev.password)
    await page.locator('.nc-btn-danger').filter({ hasText: /countdown/i }).click()
    await expect(page.getByText(/pending account deletion/i).first()).toBeVisible()
    const r = (await api.json('GET', '/api/v1/account/deletion-status', { token: dev.token })).body || {}
    expect(String(r.deletion_status), 'the API says the deletion is pending').toBe('pending_deletion')
    return `pending; anonymised at ${String(r.anonymizes_at || '?').slice(0, 10)} after ${r.cooling_off_days} days`
  })

  await steps.run('the-whole-console-says-so', 'ui:developer', async () => {
    await openRoute(page, '/mission-control')
    const banner = page.locator('.pdb-cta')
    await expect(banner, 'the pending-deletion banner rides every page').toBeVisible()
    await a11y(page, 'pending-deletion-banner')
    return 'the banner is up on mission control'
  })

  await steps.run('cancel-and-keep-the-account', 'ui:developer', async () => {
    await page.locator('.pdb-cta').click()
    await page.waitForFunction(() => location.hash.includes('/settings'))
    await settle(page)
    await page.getByRole('button', { name: /keep my account/i }).click()
    await expect.poll(status, { message: 'the API says the account is kept' }).not.toBe('pending_deletion')
    await openRoute(page, '/mission-control')
    await expect(page.locator('.pdb-cta')).toHaveCount(0)
    return 'cancelled, read back; the banner is gone'
  })
})
