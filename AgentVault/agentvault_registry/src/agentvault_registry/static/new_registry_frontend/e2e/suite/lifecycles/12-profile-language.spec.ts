/**
 * A person's own profile and language (§FESUITE; the MCP tester's updateMyDeveloperProfile, as a person meets it): the
 * profile form saves, says so, survives a reload and is read back from the API; the language menu switches the console to
 * German (the page's own lang attribute included), the choice survives a reload, no raw translation key shows on the
 * pages visited, and English comes back.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX, uniqueName } from '../support/env'
import { openRoute, settle } from '../support/ui'
import { rawKeys } from '../support/pages'

test('profile_and_language', async ({ page, context, steps, api, a11y }) => {
  const dev = await registerDeveloper(api, 'profdev')
  await seedSession(context, dev.token)
  const display = uniqueName('display')

  await steps.run('edit-the-profile', 'ui:developer', async () => {
    await openRoute(page, '/settings?tab=profile')
    const nameInput = page.locator('input.st-input[maxlength="100"]').first()
    await expect(nameInput).toBeVisible()
    await nameInput.fill(display)
    await page.locator('textarea.st-textarea').first().fill(`${PREFIX}: a bio written by the console lifecycle suite`)
    await page.locator('.st-btn-primary').filter({ hasText: /save profile/i }).click()
    await expect(page.locator('[data-testid="st-profile-msg"]')).toContainText(/profile saved/i)
    const me = await api.json('GET', '/api/v1/developers/me', { token: dev.token })
    expect(me.body?.display_name, 'the API holds the new display name').toBe(display)
    await page.reload()
    await settle(page)
    await expect(page.locator('input.st-input[maxlength="100"]').first(), 'the form shows it after a reload').toHaveValue(display)
    await a11y(page, 'settings-profile')
    return `display name saved and read back`
  })

  await steps.run('switch-to-german', 'ui:developer', async () => {
    await page.locator('.dh-lang-btn').click()
    await page.getByRole('menuitem', { name: /deutsch/i }).click()
    await expect(page.locator('html'), 'the page says what language it speaks').toHaveAttribute('lang', 'de')
    await expect(page.locator('.st-btn-primary').filter({ hasText: /profil speichern/i })).toBeVisible()
    await page.reload()
    await settle(page)
    await expect(page.locator('html'), 'the choice survives a reload').toHaveAttribute('lang', 'de')
    const raw: string[] = []
    // pages a developer with no agent may open (an agent-only page sends them home with the wallet dialog open)
    for (const route of ['/settings?tab=profile', '/my-agents', '/support', '/organizations', '/pocket/home']) {
      await openRoute(page, route)
      raw.push(...(await rawKeys(page)).map((k) => `${route}: ${k}`))
    }
    expect(raw, 'no raw translation key on the German pages').toEqual([])
    await a11y(page, 'pocket-de')
    return 'German on five pages, no raw key'
  })

  await steps.run('back-to-english', 'ui:developer', async () => {
    await openRoute(page, '/settings?tab=profile')
    await page.locator('.dh-lang-btn').click()
    await page.getByRole('menuitem', { name: /english/i }).click()
    await expect(page.locator('html')).toHaveAttribute('lang', 'en')
    await expect(page.locator('.st-btn-primary').filter({ hasText: /save profile/i })).toBeVisible()
    return 'English again'
  })
})
