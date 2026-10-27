/**
 * Support on a phone (§FESUITE; lifecycle 06 the way Pocket does it): More, Contact support, a subject and a message
 * (the button refuses until both are there), Open a ticket, and the person lands in the ticket's own thread with their
 * words in it. The ticket is read back from the API.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { uniqueName } from '../support/env'
import { currentRoute, openRoute, settle } from '../support/ui'
import { sideScroll } from '../support/pages'
import { listTickets, mainText, reachable } from '../support/hygiene'

test('phone_support_ticket_to_thread @phone-only', async ({ page, context, steps, api, a11y }) => {
  const dev = await registerDeveloper(api, 'phonesupport')
  await seedSession(context, dev.token)
  const subject = uniqueName('phticket')
  const words = `${subject}: the phone's support box, through to its thread`

  await steps.run('support-box-refuses-until-complete', 'ui:developer', async () => {
    await openRoute(page, '/pocket/more')
    const door = page.locator('[data-testid="pm-support"]')
    await door.scrollIntoViewIfNeeded()
    await door.tap()
    const box = page.locator('[data-testid="pm-support-box"]')
    await expect(box).toBeVisible()
    const send = box.locator('[data-testid="pm-support-send"]')
    await expect(send, 'empty: refused').toBeDisabled()
    await box.locator('[data-testid="pm-support-subject"]').fill(subject)
    await expect(send, 'a subject alone: refused').toBeDisabled()
    await box.locator('[data-testid="pm-support-body"]').fill(words)
    await expect(send).toBeEnabled()
    expect(await sideScroll(page), 'More does not scroll sideways').toBeLessThanOrEqual(1)
    await a11y(page, 'phone-support-box')
    return 'refused until both fields were there'
  })

  await steps.run('open-ticket-lands-in-its-thread', 'ui:developer', async () => {
    const send = page.locator('[data-testid="pm-support-send"]')
    await send.scrollIntoViewIfNeeded()
    expect(await reachable(page, send), 'the button is the element a thumb lands on').toBe(true)
    await send.tap()
    await page.waitForFunction(() => /#\/pocket\/ourchat\/[^/?]+/.test(location.hash), undefined, { timeout: 30_000 })
    await settle(page)
    await expect(page.getByText(words).first(), 'the person\'s words are in the thread').toBeVisible()
    expect(await sideScroll(page), 'the thread does not scroll sideways').toBeLessThanOrEqual(1)
    await a11y(page, 'phone-support-thread')
    const t = (await listTickets(api, dev)).find((x) => x.subject === subject)
    expect(t, 'the API lists the ticket').toBeTruthy()
    return `ticket ${String(t.id)} ${t.status}; thread ${await currentRoute(page)} (${(await mainText(page)).length} chars)`
  })
})
