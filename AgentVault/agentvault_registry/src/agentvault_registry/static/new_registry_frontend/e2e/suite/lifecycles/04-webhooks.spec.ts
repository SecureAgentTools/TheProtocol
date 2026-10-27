/**
 * Webhooks through the page (§FESUITE; the MCP tester's webhook_full_crud): an empty list, the create form, the
 * signing secret shown once, the webhook on the list, an edit of its events read back, disable and enable read back, a
 * test delivery to an address that never resolves (the page must report the failure, never a success), the delivery
 * history, and the deletion read back. The secret is never recorded.
 */
import crypto from 'node:crypto'
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX } from '../support/env'
import { openRoute, settle } from '../support/ui'

test('webhook_create_edit_test_delete', async ({ page, context, steps, api, a11y }) => {
  const dev = await registerDeveloper(api, 'hookdev')
  await seedSession(context, dev.token)
  // .test never resolves (RFC 2606): the test delivery must fail, and the page must say so.
  const url = `https://${PREFIX}-${crypto.randomBytes(3).toString('hex')}.example.test/hook`
  let hookId = ''
  const mine = async () => {
    const r = await api.json('GET', '/api/v1/webhooks', { token: dev.token })
    const list: any[] = Array.isArray(r.body) ? r.body : r.body?.webhooks || r.body?.items || []
    return list.find((w) => w.url === url) || null
  }
  const card = () => page.locator('.webhook-card').filter({ hasText: url.slice(8, 40) })

  await steps.run('empty-list', 'ui:developer', async () => {
    expect(await openRoute(page, '/webhooks')).toBe('/webhooks')
    await expect(page.locator('[data-tour="wh-empty"]')).toBeVisible()
    await a11y(page, 'webhooks-empty')
    return 'empty state with the add door'
  })

  await steps.run('create-form', 'ui:developer', async () => {
    await page.locator('[data-tour="wh-add"]').click()
    const urlInput = page.locator('input[placeholder="https://your-server.com/webhook"]')
    await expect(urlInput).toBeVisible()
    await a11y(page, 'webhooks-create-form')
    await urlInput.fill(url)
    const boxes = page.locator('[data-tour="wh-events-grid"] input.wh-checkbox')
    expect(await boxes.count()).toBeGreaterThan(1)
    await boxes.nth(0).check()
    await boxes.nth(1).check()
    await page.getByRole('button', { name: /create webhook/i }).click()
    const secret = page.locator('.wh-secret-code code')
    await expect(secret).toBeVisible()
    expect((await secret.innerText()).trim().length, 'a signing secret is shown').toBeGreaterThan(15)
    await page.getByRole('button', { name: /saved my secret/i }).click()
    const w = await mine()
    expect(w, 'the API lists the webhook').toBeTruthy()
    hookId = String(w.id)
    expect((w.events || []).length).toBe(2)
    return `created with 2 events; secret shown once (not recorded)`
  })

  await steps.run('on-the-list', 'ui:developer', async () => {
    await expect(card()).toHaveCount(1)
    await a11y(page, 'webhooks-one')
    return 'one card with its address'
  })

  await steps.run('edit-events', 'ui:developer', async () => {
    await card().locator('.webhook-btn--edit').click()
    await page.getByRole('button', { name: /clear all/i }).click()
    await page.locator('[data-tour="wh-events-grid"] input.wh-checkbox').nth(2).check()
    await page.getByRole('button', { name: /update webhook/i }).click()
    await expect(page.locator('[data-tour="wh-events-grid"]')).toHaveCount(0)
    await expect.poll(async () => ((await mine())?.events || []).length).toBe(1)
    return 'events edited to one, read back'
  })

  await steps.run('disable-enable', 'ui:developer', async () => {
    await card().locator('.webhook-btn--disable').click()
    await expect.poll(async () => (await mine())?.is_active).toBe(false)
    await card().locator('.webhook-btn--enable').click()
    await expect.poll(async () => (await mine())?.is_active).toBe(true)
    return 'disabled, then enabled, each read back'
  })

  await steps.run('test-delivery-fails-honestly', 'ui:developer', async () => {
    await card().locator('.webhook-btn--test').click()
    // The address never resolves: whatever the page shows must not be a success.
    const ok = page.locator('[data-testid="toast"][data-kind="success"]').filter({ hasText: /deliver|test|sent/i })
    const said = page.locator('[data-testid="toast"][data-kind="error"], [data-testid="toast"][data-kind="warning"]').last()
    await expect(said).toBeVisible()
    await expect(ok).toHaveCount(0)
    return (await said.innerText()).replace(/\s+/g, ' ').slice(0, 140)
  })

  await steps.run('delivery-history', 'ui:developer', async () => {
    await card().locator('.webhook-btn--history').click()
    const log = page.getByRole('dialog', { name: /delivery log/i })
    await expect(log).toBeVisible()
    await settle(page)
    const r = await api.json('GET', `/api/v1/webhooks/${hookId}/deliveries`, { token: dev.token })
    expect(r.status).toBe(200)
    const n = (Array.isArray(r.body) ? r.body : r.body?.deliveries || r.body?.items || []).length
    await a11y(page, 'webhooks-history')
    await log.getByRole('button', { name: /close delivery log/i }).click()
    await expect(log).toHaveCount(0)
    return `history opened and closed; the API holds ${n} deliver${n === 1 ? 'y' : 'ies'}`
  })

  await steps.run('delete', 'ui:developer', async () => {
    await card().locator('.webhook-btn--delete').click()
    await card().locator('.webhook-btn--confirm-delete').click()
    await expect(card()).toHaveCount(0)
    await expect.poll(async () => await mine()).toBeNull()
    return 'gone from the page and the API'
  })
})
