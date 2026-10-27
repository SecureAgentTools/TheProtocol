/**
 * A support ticket through the page (§FESUITE; the MCP tester's support_ticket): a developer opens a ticket from the
 * form, sees it, replies, closes it and reopens it, every state read back from the API.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { openRoute, settle } from '../support/ui'

test('support_ticket_open_reply_close', async ({ page, context, steps, api, a11y }) => {
  const dev = await registerDeveloper(api, 'supportdev')
  await seedSession(context, dev.token)
  const subject = uniqueName('ticket')
  let ticketId = ''
  const readTicket = async () => {
    const r = await api.json('GET', '/api/v1/support/tickets', { token: dev.token })
    const list: any[] = Array.isArray(r.body) ? r.body : r.body?.tickets || r.body?.items || []
    return list.find((x) => x.subject === subject) || null
  }

  await steps.run('open-a-ticket', 'ui:developer', async () => {
    expect(await openRoute(page, '/support')).toMatch(/^\/support/)
    await page.locator('[data-testid="sp-new"]').click()
    await expect(page.locator('#sp-subject')).toBeVisible()
    await a11y(page, 'support-form')
    await page.locator('#sp-subject').fill(subject)
    await page.locator('#sp-message').fill('Opened by the console lifecycle suite: the form, the thread, the status.')
    await page.locator('[data-testid="sp-submit"]').click()
    await expect(page.getByText(subject).first()).toBeVisible()
    const t = await readTicket()
    expect(t, 'the API lists the ticket').toBeTruthy()
    ticketId = String(t.id)
    return `ticket ${ticketId.slice(0, 8)}… ${t.status}`
  })

  await steps.run('reply', 'ui:developer', async () => {
    const reply = page.locator('[data-testid="sp-reply"]')
    await expect(reply).toBeVisible()
    const text = `follow-up from ${subject}`
    await reply.fill(text)
    await page.locator('[data-testid="sp-reply-send"]').click()
    await expect(page.getByText(text).first()).toBeVisible()
    const r = await api.json('GET', `/api/v1/support/tickets/${ticketId}`, { token: dev.token })
    expect(r.status).toBe(200)
    const msgs: any[] = r.body?.messages || r.body?.replies || []
    expect(msgs.some((m) => String(m.message || m.body || m.content || '').includes(text)), 'the reply is in the thread').toBe(true)
    await a11y(page, 'support-thread')
    return `${msgs.length} message(s) in the thread`
  })

  await steps.run('close-and-reopen', 'ui:developer', async () => {
    const close = page.locator('[data-testid="sp-owner-close"]')
    await expect(close).toBeVisible()
    await close.click()
    await expect.poll(async () => String((await readTicket())?.status || '').toLowerCase()).toMatch(/closed|resolved/)
    await settle(page)
    await page.locator('[data-testid="sp-owner-reopen"]').click()
    await expect.poll(async () => String((await readTicket())?.status || '').toLowerCase()).toMatch(/open|reopened|pending/)
    return 'closed, then reopened, each read back'
  })
})
