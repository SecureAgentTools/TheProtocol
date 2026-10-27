/**
 * API keys through the page (§FESUITE; the MCP tester's api_key_full_crud): an empty list that offers the first key,
 * the create form, the key shown once, the key WORKING (the shown value authenticates a real call), the key on the
 * list, and its deletion, after which the same value is refused. The value itself is never recorded.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { openRoute, toast } from '../support/ui'

test('api_key_create_use_delete', async ({ page, context, steps, api, a11y, capture }) => {
  const dev = await registerDeveloper(api, 'keydev')
  await seedSession(context, dev.token)
  const keyName = uniqueName('key')
  let plain = ''

  await steps.run('empty-list-offers-a-key', 'ui:developer', async () => {
    expect(await openRoute(page, '/api-keys')).toBe('/api-keys')
    await expect(page.locator('[data-tour="key-new"]')).toBeVisible()
    await a11y(page, 'api-keys-empty')
    return 'the create door is on screen'
  })

  await steps.run('create-form', 'ui:developer', async () => {
    await page.locator('[data-tour="key-new"]').click()
    const name = page.locator('[data-tour="key-name"]')
    await expect(name).toBeVisible()
    await a11y(page, 'api-keys-create-form')
    await name.fill(keyName)
    await page.getByRole('button', { name: /create api key/i }).click()
    const reveal = page.locator('[data-tour="key-reveal"]')
    await expect(reveal).toBeVisible()
    plain = (await reveal.locator('code').first().innerText()).trim()
    expect(plain.startsWith('avreg_'), 'the shown key has the avreg_ shape').toBe(true)
    return 'shown once, avreg_ shape (value not recorded)'
  })

  await steps.run('the-shown-key-works', 'ui:developer', async () => {
    const r = await api.json('GET', '/api/v1/developers/me', { headers: { authorization: `Bearer ${plain}` } })
    expect(r.status, 'the key authenticates a call as its developer').toBe(200)
    expect(String(r.body?.email || '').toLowerCase()).toBe(dev.email.toLowerCase())
    return 'GET /developers/me answered 200 as the key\'s developer'
  })

  await steps.run('key-on-the-list', 'ui:developer', async () => {
    await page.reload()
    await expect(page.locator('[data-tour="key-list"]').getByText(keyName)).toBeVisible()
    await expect(page.locator('[data-tour="key-reveal"]'), 'the value is not shown a second time').toHaveCount(0)
    return 'listed by name; the value is not shown again'
  })

  await steps.run('delete-key', 'ui:developer', async () => {
    const card = page.locator('[data-tour="key-list"] > *').filter({ hasText: keyName })
    await card.getByTitle(/delete api key/i).click()
    // the dialog's own button (the row's trash icon carries the same name in its title)
    await page.locator('.nc-btn-danger').filter({ hasText: /delete api key/i }).click()
    await expect(page.locator('[data-tour="key-list"]').getByText(keyName)).toHaveCount(0)
    await toast(page, 'success', /.+/)
    return 'gone from the list'
  })

  await steps.run('deleted-key-refused', 'ui:developer', async () => {
    capture.allow(/GET \/api\/v1\/developers\/me$/, 401, 'a deleted key is refused (read-back, not the page)')
    const r = await api.json('GET', '/api/v1/developers/me', { headers: { authorization: `Bearer ${plain}` } })
    expect(r.status).toBe(401)
    return 'the same value now answers 401'
  })
})
