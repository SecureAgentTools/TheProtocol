/**
 * The create forms' hygiene (§FESUITE): the organization, webhook, API key, support ticket and quick-agent forms each
 * refuse an empty required field on the page (nothing leaves it), hold an over-long input to the server's bound on the
 * page (never a 422 in a toast), and turn ONE double press (or a double Enter) into ONE object, read back by count.
 */
import { test, expect } from '../support/fixtures'
import { ledger, registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { openRoute, toast } from '../support/ui'
import { deadHookUrl, listAgents, listHooks, listKeys, listOrgs, listTickets, longText, watchRequests } from '../support/hygiene'

test('form_hygiene_create_forms', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(8 * 60_000)
  const dev = await registerDeveloper(api, 'formdev')
  await seedSession(context, dev.token)

  await steps.run('organization-form', 'ui:developer', async () => {
    await openRoute(page, '/organization')
    await page.locator('[data-tour="org-create-btn"]').first().click()
    const name = page.locator('input[placeholder="My Organization"]')
    const create = page.locator('.tp-modal .tp-btn--primary')
    await expect(name).toBeVisible()
    await a11y(page, 'hyg-org-form')
    await expect(create, 'empty name: CREATE is refused').toBeDisabled()
    await name.fill('ab')
    await expect(create, 'a 2-character name (the server takes 3-255) is refused on the page').toBeDisabled()
    await expect(page.locator('[data-testid="org-create-name-hint"]'), 'the page says why').toBeVisible()
    await name.fill(longText(300))
    expect((await name.inputValue()).length, 'the name field holds the server\'s bound (255)').toBeLessThanOrEqual(255)
    const orgName = uniqueName('horg')
    await name.fill(orgName)
    const posts = watchRequests(page, 'POST', /\/api\/v1\/organizations$/)
    await create.dblclick()
    await toast(page, 'success', /organization created/i)
    posts.stop()
    const n = (await listOrgs(api, dev)).filter((o) => o.name === orgName).length
    ledger('organization', { name: orgName, owner: dev.email })
    expect(posts.list.length, 'one create request left the page').toBe(1)
    expect(n, 'one organization exists').toBe(1)
    return 'empty and short refused on the page, long held at 255, double press made one'
  })

  await steps.run('webhook-form', 'ui:developer', async () => {
    await openRoute(page, '/webhooks')
    await page.locator('[data-tour="wh-add"]').first().click()
    const url = page.locator('input[placeholder="https://your-server.com/webhook"]')
    await expect(url).toBeVisible()
    await a11y(page, 'hyg-webhook-form')
    const posts = watchRequests(page, 'POST', /\/api\/v1\/webhooks$/)
    const create = page.getByRole('button', { name: /create webhook/i })
    await create.click()
    await expect(page.locator('.wh-field-error'), 'empty: the URL and the events are refused in words').toHaveCount(2)
    expect(posts.list.length, 'nothing left the page').toBe(0)
    await url.fill(`https://${longText(600)}.example.test/hook`)
    expect((await url.inputValue()).length, 'the URL field holds the server\'s bound (500)').toBeLessThanOrEqual(500)
    const hook = deadHookUrl()
    await url.fill(hook)
    await page.locator('[data-tour="wh-events-grid"] input.wh-checkbox').first().check()
    await create.dblclick()
    await expect(page.locator('.wh-secret-code code')).toBeVisible()
    await page.getByRole('button', { name: /saved my secret/i }).click()
    posts.stop()
    const n = (await listHooks(api, dev)).filter((h) => h.url === hook).length
    expect(posts.list.length, 'one create request left the page').toBe(1)
    expect(n, 'one webhook exists').toBe(1)
    return 'empty refused in words, long held at 500, double press made one'
  })

  await steps.run('api-key-form', 'ui:developer', async () => {
    await openRoute(page, '/api-keys')
    await page.locator('[data-tour="key-new"]').first().click()
    const name = page.locator('[data-tour="key-name"]')
    const create = page.getByRole('button', { name: /create api key/i })
    await expect(name).toBeVisible()
    await a11y(page, 'hyg-key-form')
    const posts = watchRequests(page, 'POST', /\/api\/v1\/auth\/api-keys$/)
    await expect(create, 'empty: CREATE is refused').toBeDisabled()
    await name.focus()
    await page.keyboard.press('Enter')
    await toast(page, 'error', /description required/i)
    expect(posts.list.length, 'Enter on an empty name sent nothing').toBe(0)
    await name.fill(longText(300))
    expect((await name.inputValue()).length, 'the name field holds a bound (200)').toBeLessThanOrEqual(200)
    // a double press of the button
    const first = uniqueName('hkey')
    await name.fill(first)
    await create.dblclick()
    await expect(page.locator('[data-tour="key-reveal"]')).toBeVisible()
    await page.locator('[data-tour="key-reveal"]').getByRole('button', { name: /^done$/i }).click()
    // a double Enter in the name field (the field is not disabled while a key is minted)
    const second = uniqueName('hkey')
    await page.locator('[data-tour="key-new"]').first().click()
    await name.fill(second)
    await name.focus()
    await page.keyboard.press('Enter')
    await page.keyboard.press('Enter')
    await expect(page.locator('[data-tour="key-reveal"]')).toBeVisible()
    await page.locator('[data-tour="key-reveal"]').getByRole('button', { name: /^done$/i }).click()
    await expect.poll(async () => (await listKeys(api, dev)).filter((k) => (k.description ?? k.key_name) === second).length).toBeGreaterThan(0)
    posts.stop()
    const keys = await listKeys(api, dev)
    const n1 = keys.filter((k) => (k.description ?? k.key_name) === first).length
    const n2 = keys.filter((k) => (k.description ?? k.key_name) === second).length
    expect(n1, 'a double press made one key').toBe(1)
    expect(n2, 'a double Enter made one key').toBe(1)
    expect(posts.list.length, 'two create requests left the page, one per name').toBe(2)
    return 'empty refused (button and Enter), long held at 200, double press and double Enter each made one'
  })

  await steps.run('support-ticket-form', 'ui:developer', async () => {
    await openRoute(page, '/support')
    await page.locator('[data-testid="sp-new"]').click()
    const subject = page.locator('#sp-subject')
    const submit = page.locator('[data-testid="sp-submit"]')
    await expect(subject).toBeVisible()
    await a11y(page, 'hyg-support-form')
    await expect(submit, 'empty: submit is refused').toBeDisabled()
    await subject.fill(longText(300))
    expect((await subject.inputValue()).length, 'the subject holds the server\'s bound (200)').toBeLessThanOrEqual(200)
    await page.locator('#sp-message').fill('')
    await expect(submit, 'a subject with no message is refused').toBeDisabled()
    const subj = uniqueName('hticket')
    await subject.fill(subj)
    await page.locator('#sp-message').fill('form hygiene: one press, one ticket')
    const posts = watchRequests(page, 'POST', /\/api\/v1\/support\/tickets$/)
    await submit.dblclick()
    await expect(page.getByText(subj).first()).toBeVisible()
    posts.stop()
    const n = (await listTickets(api, dev)).filter((x) => x.subject === subj).length
    expect(posts.list.length, 'one create request left the page').toBe(1)
    expect(n, 'one ticket exists').toBe(1)
    return 'empty refused, long held at 200, double press made one'
  })

  await steps.run('quick-agent-form', 'ui:developer', async () => {
    await openRoute(page, '/my-agents')
    await page.locator('.fleet-deploy-btn').first().click()
    const name = page.locator('input[placeholder="e.g., Pricing Oracle"]')
    const create = page.locator('.qa-btn--primary')
    await expect(name).toBeVisible()
    await a11y(page, 'hyg-agent-form')
    // the first agent opens in wallet mode with "Wallet" filled in (a default, not a defect): clear it
    await name.fill('')
    await expect(create, 'empty: create is refused').toBeDisabled()
    await name.fill('a')
    await expect(create, 'one character is refused').toBeDisabled()
    await name.fill(longText(100))
    expect((await name.inputValue()).length, 'the name holds its bound (60)').toBeLessThanOrEqual(60)
    const agentName = uniqueName('hagent')
    await name.fill(agentName)
    await create.dblclick()
    await expect(page.locator('.qa-success-hero')).toBeVisible({ timeout: 60_000 })
    const mine = (await listAgents(api, dev)).filter((a) => (a.name || a.human_readable_id || '') === agentName)
    for (const a of mine) ledger('agent', { did: a.did, name: agentName, owner: dev.email })
    expect(mine.length, 'one agent exists').toBe(1)
    await page.locator('.qa-close').click()
    return 'empty and one character refused, long held at 60, double press made one'
  })
})
