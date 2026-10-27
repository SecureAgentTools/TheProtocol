/**
 * A list longer than its page (§FESUITE): the support list shows 50 tickets a page. A developer with 53 tickets pages
 * through it on the console: every ticket appears exactly once across the pages, none is missing, the pager says where
 * it is, and the last page offers no "next". The set is read back against the API's whole list. (A page keyed on a
 * column that is not unique is not a partition: CLAUDE.md §DIRFEED-2.) The tickets are closed afterwards over the API
 * so the shared desk's open queue carries none of them.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX } from '../support/env'
import { openRoute, settle } from '../support/ui'
import { listTickets } from '../support/hygiene'

const PAGE_SIZE = 50
const TOTAL = 53

test('list_pagination_support_tickets', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(8 * 60_000)
  const dev = await registerDeveloper(api, 'pagedev')
  const subjects: string[] = []
  for (let i = 0; i < TOTAL; i++) {
    const subject = `${PREFIX}-page-${String(i).padStart(2, '0')}`
    const r = await api.json('POST', '/api/v1/support/tickets', { token: dev.token, body: { subject, message: `ticket ${i} of ${TOTAL}` } })
    if (r.status >= 300) throw new Error(`ticket ${i} answered ${r.status}`)
    subjects.push(subject)
  }
  await seedSession(context, dev.token)
  const rowSubjects = () => page.locator('.sp-ticket-list .sp-ticket-subject').allInnerTexts()

  const seen: string[] = []
  await steps.run('first-page', 'ui:developer', async () => {
    expect(await openRoute(page, '/support')).toBe('/support')
    await settle(page)
    const pos = page.locator('[data-testid="sp-pager-pos"]')
    await expect(page.locator('[data-testid="sp-pager"]'), 'a list longer than a page shows a pager').toBeVisible()
    const first = (await rowSubjects()).map((s) => s.trim()).filter((s) => s.startsWith(PREFIX))
    expect(first.length, 'the first page holds a full page').toBe(PAGE_SIZE)
    seen.push(...first)
    await a11y(page, 'support-list-paged')
    return `page 1: ${first.length} rows; pager says "${(await pos.innerText()).replace(/\s+/g, ' ').trim()}"`
  })

  await steps.run('next-page', 'ui:developer', async () => {
    await page.locator('[data-testid="sp-pager-next"]').click()
    await settle(page)
    const second = (await rowSubjects()).map((s) => s.trim()).filter((s) => s.startsWith(PREFIX))
    expect(second.length, 'the second page holds the rest').toBe(TOTAL - PAGE_SIZE)
    seen.push(...second)
    await expect(page.locator('[data-testid="sp-pager-next"]'), 'the last page offers no next').toBeDisabled()
    await page.locator('[data-testid="sp-pager-prev"]').click()
    await settle(page)
    const back = (await rowSubjects()).map((s) => s.trim()).filter((s) => s.startsWith(PREFIX))
    expect(back, 'going back shows the first page again, in the same order').toEqual(seen.slice(0, PAGE_SIZE))
    return `page 2: ${second.length} rows; back to page 1 unchanged`
  })

  await steps.run('every-ticket-once', 'ui:developer', async () => {
    const dupes = seen.filter((s, i) => seen.indexOf(s) !== i)
    const missing = subjects.filter((s) => !seen.includes(s))
    expect(dupes, 'no ticket appears twice across the pages').toEqual([])
    expect(missing, 'no ticket is missing across the pages').toEqual([])
    const all = (await listTickets(api, dev)).map((t) => t.subject).filter((s: string) => s.startsWith(PREFIX))
    expect(new Set(all), 'the pages hold exactly the API\'s set').toEqual(new Set(seen))
    return `${seen.length} rows across two pages = the API's ${all.length}`
  })

  // housekeeping: the shared desk's open queue should not carry 53 throwaway tickets
  const tickets = await listTickets(api, dev)
  for (const t of tickets) {
    await api.json('POST', `/api/v1/support/tickets/${t.id}/status`, { token: dev.token, body: { status: 'closed' } }).catch(() => null)
  }
})
