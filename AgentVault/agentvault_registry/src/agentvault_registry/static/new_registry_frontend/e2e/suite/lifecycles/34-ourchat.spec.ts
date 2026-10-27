/**
 * OurChat between two people, through the page (§FESUITE; the MCP tester's chat_requests_blocks_and_leave as people meet
 * it): B claims a handle; A finds B by it on the desktop, writes, and stays on the desktop (the find sheet used to push
 * every new thread into Pocket); B accepts the request and answers; A reads the answer; A blocks B from the thread and
 * lifts the block again from the list of blocks (there was no such list: a block was a one-way door). Every state is
 * read back from the API as the person it belongs to.
 */
import crypto from 'node:crypto'
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { PREFIX } from '../support/env'
import { currentRoute, openRoute, settle } from '../support/ui'
import { listOf, readBack, steady } from '../support/social'

test('ourchat_handle_request_reply_block_unblock', async ({ page, context, steps, api, a11y, openAs }) => {
  test.setTimeout(6 * 60_000)
  const devA = await registerDeveloper(api, 'chata')
  const devB = await registerDeveloper(api, 'chatb')
  await seedSession(context, devA.token)
  const pageB = await openAs(devB.token)
  const handle = `fes${crypto.randomBytes(4).toString('hex')}`
  const hello = `${PREFIX}: hello from A`
  const reply = `${PREFIX}: B answers`
  let convId = ''
  const messages = async (token: string) =>
    listOf((await readBack(api, `/api/v1/chat/conversations/${convId}/messages`, token)).body, 'messages')
  const lane = async (token: string, state: 'active' | 'requests') =>
    listOf((await readBack(api, `/api/v1/chat/conversations?state=${state}`, token)).body, 'conversations')
  const blocksOf = async (token: string) => listOf((await readBack(api, '/api/v1/chat/blocks', token)).body, 'blocks')

  await steps.run('b-claims-a-handle', 'ui:developer', async () => {
    await openRoute(pageB, '/pocket/more')
    await pageB.locator('[data-testid="pm-handle"]').click()
    await pageB.locator('[data-testid="pm-handle-input"]').fill(handle)
    await pageB.locator('[data-testid="pm-handle-claim"]').click()
    await expect(pageB.locator('[data-testid="pm-handle-msg"]')).toContainText(/claimed/i)
    await steady(pageB)
    await a11y(pageB, 'pocket-more-handle')
    expect((await readBack(api, '/api/v1/chat/handles/me', devB.token)).body?.handle, 'the API keeps the handle').toBe(handle)
    return `@${handle}`
  })

  await steps.run('a-finds-b-and-writes-on-the-desktop', 'ui:developer', async () => {
    expect(await openRoute(page, '/ourchat')).toBe('/ourchat')
    await page.locator('[data-testid="os-find-open"]').click()
    const find = page.locator('[data-testid="os-find"]')
    await expect(find).toBeVisible()
    await page.locator('[data-testid="os-find-lane-person"]').click()
    await page.locator('[data-testid="os-find-handle"]').fill(`@${handle}`)
    await page.locator('[data-testid="os-find-lookup"]').click()
    await expect(page.locator('[data-testid="os-find-profile"]')).toBeVisible()
    await steady(page)
    await a11y(page, 'ourchat-find')
    await page.locator('[data-testid="os-find-message"]').click()
    await page.waitForFunction(() => /^#\/ourchat\/[^/?]+/.test(location.hash), undefined, { timeout: 20_000 })
    const route = await currentRoute(page)
    expect(route, 'the new thread opens on the desktop, not in Pocket').toMatch(/^\/ourchat\//)
    convId = route.split('/')[2]
    await page.locator('[data-testid="ost-input"]').fill(hello)
    await page.locator('[data-testid="ost-send"]').click()
    await expect(page.getByText(hello).first()).toBeVisible()
    await expect.poll(async () => (await messages(devA.token)).some((m) => m.body === hello),
      { message: 'the API keeps A\'s message' }).toBe(true)
    return `thread ${convId.slice(0, 8)}… opened at ${route.split('/').slice(0, 2).join('/')}`
  })

  await steps.run('b-accepts-the-request', 'ui:developer', async () => {
    expect((await lane(devB.token, 'requests')).map((c) => c.id), 'the API puts it in B\'s requests').toContain(convId)
    await openRoute(pageB, '/ourchat')
    await pageB.locator('[data-testid="os-lane-requests"]').click()
    await expect(pageB.locator(`[data-testid="os-accept-${convId}"]`)).toBeVisible()
    await steady(pageB)
    await a11y(pageB, 'ourchat-requests')
    await pageB.locator(`[data-testid="os-accept-${convId}"]`).click()
    await expect.poll(async () => (await lane(devB.token, 'active')).map((c) => c.id),
      { message: 'accepted: the thread is in B\'s inbox' }).toContain(convId)
    return 'accepted; B\'s inbox holds the thread'
  })

  await steps.run('b-answers-and-a-reads-it', 'ui:developer', async () => {
    await openRoute(pageB, `/ourchat/${convId}`)
    await expect(pageB.getByText(hello).first(), 'B reads A\'s message').toBeVisible()
    await pageB.locator('[data-testid="ost-input"]').fill(reply)
    await pageB.locator('[data-testid="ost-send"]').click()
    await expect(pageB.getByText(reply).first()).toBeVisible()
    await openRoute(page, `/ourchat/${convId}`)
    await expect(page.getByText(reply).first(), 'A reads B\'s answer').toBeVisible({ timeout: 20_000 })
    await steady(page)
    await a11y(page, 'ourchat-thread')
    const bodies = (await messages(devA.token)).map((m) => m.body)
    expect(bodies).toEqual(expect.arrayContaining([hello, reply]))
    return 'messages both ways, read back'
  })

  await steps.run('a-blocks-b-from-the-thread', 'ui:developer', async () => {
    await page.locator('[data-testid="ost-menu"]').click()
    await page.locator('[data-testid="ost-block"]').click()
    await expect(page.locator('[data-testid="ost-block-confirm"]')).toBeVisible()
    await page.locator('[data-testid="ost-block-go"]').click()
    await page.waitForFunction(() => /^#\/ourchat\/?(\?|$)/.test(location.hash), undefined, { timeout: 20_000 })
    await expect.poll(async () => (await blocksOf(devA.token)).length, { message: 'the API keeps A\'s block' }).toBe(1)
    const b = (await blocksOf(devA.token))[0]
    expect(b.ptype).toBe('developer')
    return `blocked ${b.ptype} #${b.id}`
  })

  await steps.run('a-lifts-the-block', 'ui:developer', async () => {
    await openRoute(page, '/pocket/more')
    await page.locator('[data-testid="pm-blocks"]').click()
    const row = page.locator('[data-testid="pm-block-row"]')
    await expect(row).toHaveCount(1)
    await steady(page)
    await a11y(page, 'pocket-more-blocks')
    await row.locator('[data-testid="pm-unblock"]').click()
    await expect(page.locator('[data-testid="pm-blocks-msg"]')).toContainText(/unblocked/i)
    await expect(row).toHaveCount(0)
    await expect.poll(async () => (await blocksOf(devA.token)).length, { message: 'the API holds no block' }).toBe(0)
    await settle(page)
    return 'unblocked from the list, read back'
  })
})
