/**
 * A Guild task between two people's agents, through the Guild board (§FESUITE; the MCP tester's guild lifecycle, as two
 * people meet it). A poster posts a task and its bounty is escrowed; a provider (bonded from its owner's wallet agent:
 * a bid is a provider act, gated by the bond) bids; the poster awards the bid; the provider delivers; the poster rates
 * and accepts, and the payee is paid the bounty less the Guild fee the order was quoted. The page refuses amounts that
 * are not amounts before anything leaves it. Every state is read back from the API; the money from the TEG.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, seedSession } from '../support/accounts'
import { bondFrom, partyWith, seedVault, stillFrame, waitActing } from '../support/commerce'
import { uniqueName } from '../support/env'
import { openRoute, toast } from '../support/ui'

const BOUNTY = 5

test('guild_post_bid_award_deliver_pay', async ({ page, context, steps, api, a11y, openAs }) => {
  test.setTimeout(7 * 60_000)
  const poster = await partyWith(api, 'gldposter', 1)
  const provider = await partyWith(api, 'gldprov', 2)
  const [P] = poster.agents
  const [W, U] = provider.agents
  const title = uniqueName('task')
  let oid = ''
  let pBefore = 0
  let uBefore = 0

  const readOrder = async () => {
    if (!oid) {
      const r = await api.json('GET', '/api/v1/guild/orders?status_filter=open&limit=100', { token: poster.dev.token })
      const hit = (r.body?.orders || []).find((o: any) => o.title === title)
      if (hit) oid = String(hit.id)
    }
    if (!oid) return null
    const r = await api.json('GET', `/api/v1/guild/orders/${encodeURIComponent(oid)}`, { token: poster.dev.token })
    return r.status === 200 ? r.body : null
  }
  const status = async () => String((await readOrder())?.order?.status || '')

  await steps.run('provider-bonded', 'ui:developer', async () => {
    await expect.poll(() => agentBalance(api, P.token), { timeout: 45_000, message: 'the poster holds its grant' }).toBeGreaterThan(BOUNTY)
    await expect.poll(() => agentBalance(api, W.token), { timeout: 45_000, message: 'the wallet holds its grant' }).toBeGreaterThan(250)
    await bondFrom(api, provider.dev, U.did, W.did)
    pBefore = await agentBalance(api, P.token)
    uBefore = await agentBalance(api, U.token)
    return `poster holds ${pBefore}; provider bonded, holds ${uBefore}`
  })

  await seedSession(context, poster.dev.token)
  await seedVault(context, poster, P.did)

  await steps.run('post-a-task', 'ui:agent', async () => {
    await openRoute(page, '/guild')
    await waitActing(page, P.did)
    await page.locator('[data-tour="guild-post"]').click()
    const dialog = page.getByRole('dialog', { name: /post a task/i })
    await expect(dialog).toBeVisible()
    await dialog.locator('#gld-post-name').fill(title)
    await dialog.locator('#gld-post-spec').fill('Summarise the attached note in three sentences.')
    const post = dialog.getByRole('button', { name: /post \+ escrow/i })
    for (const bad of ['-5', '0']) {
      await dialog.locator('#gld-post-bounty').fill(bad)
      await expect(post, `a bounty of ${bad} is refused on the page`).toBeDisabled()
      await expect(dialog.locator('[data-testid="gld-post-warn"]')).toBeVisible()
    }
    await dialog.locator('#gld-post-bounty').fill(String(BOUNTY))
    await dialog.locator('#gld-post-stake').fill('0')
    await expect(post).toBeEnabled()
    await stillFrame(page)
    await a11y(page, 'guild-post')
    await post.click()
    await toast(page, 'success', /posted/i)
    await expect.poll(status, { timeout: 30_000, message: 'the order is open' }).toBe('open')
    await expect.poll(async () => pBefore - (await agentBalance(api, P.token)), { timeout: 30_000, message: 'the bounty is escrowed' })
      .toBeCloseTo(BOUNTY, 6)
    return `posted ${oid.slice(0, 8)}…; ${BOUNTY} escrowed`
  })

  const prov = await openAs(provider.dev.token)
  await seedVault(prov.context(), provider, U.did)

  await steps.run('provider-bids', 'ui:agent', async () => {
    await openRoute(prov, '/guild')
    await waitActing(prov, U.did)
    await expect(prov.getByRole('button', { name: /all \(admin\)/i }), 'a member is not offered the admin view').toHaveCount(0)
    const door = prov.locator(`[data-testid="gld-open-${oid}"]`)
    await expect(door, 'the task is on the open board').toBeVisible({ timeout: 30_000 })
    await door.focus()
    await prov.keyboard.press('Enter')
    const price = prov.getByRole('spinbutton', { name: /your price/i })
    await expect(price, 'the keyboard opened the task').toBeVisible()
    await price.fill(String(BOUNTY + 1))
    await expect(prov.locator('[data-testid="gld-bid-warn"]'), 'a price above the bounty is refused on the page').toBeVisible()
    await price.fill('4')
    await prov.getByRole('textbox', { name: /why you/i }).fill('Done this a hundred times.')
    await stillFrame(prov)
    await a11y(prov, 'guild-detail-bid')
    await prov.locator('.gld-act-bid').getByRole('button', { name: /^bid$/i }).click()
    await toast(prov, 'success', /bid placed/i)
    await expect.poll(async () => ((await readOrder())?.bids || []).filter((b: any) => b.bidder_did === U.did).length,
      { timeout: 30_000, message: 'the bid is on the order' }).toBe(1)
    return 'bid 4 on the task'
  })

  await steps.run('poster-awards', 'ui:agent', async () => {
    await page.locator(`[data-testid="gld-open-${oid}"]`).click()
    const award = page.locator('.gld-award')
    await expect(award, 'the bid reaches the poster').toBeVisible({ timeout: 30_000 })
    await award.click()
    await toast(page, 'success', /awarded/i)
    await expect.poll(status, { timeout: 30_000 }).toBe('awarded')
    expect((await readOrder())?.order?.worker_did).toBe(U.did)
    return 'awarded to the provider'
  })

  await steps.run('provider-delivers', 'ui:agent', async () => {
    await prov.getByRole('button', { name: /^in progress$/i }).click()
    await prov.locator(`[data-testid="gld-open-${oid}"]`).click()
    const deliverable = prov.getByRole('textbox', { name: /deliverable/i })
    await expect(deliverable, 'the awarded worker is asked to deliver').toBeVisible({ timeout: 30_000 })
    await deliverable.fill('The note says: ship it, measure it, keep it.')
    await prov.locator('.gld-act-bid').getByRole('button', { name: /^submit$/i }).click()
    await toast(prov, 'success', /submitted/i)
    await expect.poll(status, { timeout: 30_000 }).toBe('submitted')
    return 'work submitted'
  })

  await steps.run('poster-rates-and-pays', 'ui:agent', async () => {
    await page.getByRole('button', { name: /^in progress$/i }).click()
    await page.locator(`[data-testid="gld-open-${oid}"]`).click()
    const stars = page.getByRole('group', { name: /rating/i })
    await expect(stars, 'the delivery reaches the poster').toBeVisible({ timeout: 30_000 })
    await stars.getByRole('button', { name: /4 of 5 stars/i }).click()
    await expect(stars.getByRole('button', { name: /4 of 5 stars/i })).toHaveAttribute('aria-pressed', 'true')
    await stillFrame(page)
    await a11y(page, 'guild-verify')
    await page.getByRole('button', { name: /accept & pay/i }).click()
    await toast(page, 'success', /worker paid/i)
    await expect.poll(status, { timeout: 45_000 }).toBe('settled')
    return 'accepted with four stars; settled'
  })

  await steps.run('money-moved-once', 'ui:agent', async () => {
    const o = (await readOrder())?.order || {}
    // the fee the order was quoted at post time (stored on the order), as the registry charged it
    const fee = o.fee_charged != null ? Number(o.fee_charged) : (BOUNTY * Number(o.fee_bps ?? 250)) / 10_000
    const expected = BOUNTY - fee
    await expect.poll(async () => (await agentBalance(api, U.token)) - uBefore, { timeout: 45_000, message: 'the payee is paid' })
      .toBeCloseTo(expected, 6)
    const spent = pBefore - (await agentBalance(api, P.token))
    expect(spent, 'the poster paid the bounty once').toBeCloseTo(BOUNTY, 6)
    return `poster -${spent}, provider +${expected} (bounty less a fee of ${fee})`
  })
})

/**
 * The poster's way out (§FESUITE): an open task nobody was awarded can be cancelled, and its escrowed bounty comes
 * back in full. The cancelled task is found where the board files it (the Settled tab, which used to read only open
 * orders and so showed nothing).
 */
test('guild_post_and_cancel_refunds', async ({ page, context, steps, api, a11y }) => {
  test.setTimeout(4 * 60_000)
  const poster = await partyWith(api, 'gldcancel', 1)
  const [P] = poster.agents
  const title = uniqueName('task')
  let oid = ''
  let before = 0
  const order = async () => {
    if (!oid) {
      const r = await api.json('GET', '/api/v1/guild/orders?status_filter=open&limit=100', { token: poster.dev.token })
      oid = String((r.body?.orders || []).find((o: any) => o.title === title)?.id || '')
    }
    return oid ? (await api.json('GET', `/api/v1/guild/orders/${encodeURIComponent(oid)}`, { token: poster.dev.token })).body?.order : null
  }

  await expect.poll(() => agentBalance(api, P.token), { timeout: 45_000 }).toBeGreaterThan(BOUNTY)
  before = await agentBalance(api, P.token)
  await seedSession(context, poster.dev.token)
  await seedVault(context, poster, P.did)

  await steps.run('post', 'ui:agent', async () => {
    await openRoute(page, '/guild')
    await waitActing(page, P.did)
    await page.locator('[data-tour="guild-post"]').click()
    const dialog = page.getByRole('dialog', { name: /post a task/i })
    await dialog.locator('#gld-post-name').fill(title)
    await dialog.locator('#gld-post-bounty').fill(String(BOUNTY))
    await dialog.getByRole('button', { name: /post \+ escrow/i }).click()
    await toast(page, 'success', /posted/i)
    await expect.poll(async () => (await order())?.status, { timeout: 30_000 }).toBe('open')
    return `posted, ${BOUNTY} escrowed`
  })

  await steps.run('cancel-and-refund', 'ui:agent', async () => {
    await page.locator(`[data-testid="gld-open-${oid}"]`).click()
    await page.getByRole('button', { name: /cancel & refund/i }).click()
    await toast(page, 'success', /cancelled/i)
    await expect.poll(async () => (await order())?.status, { timeout: 30_000 }).toMatch(/cancel|refund/)
    await expect.poll(async () => before - (await agentBalance(api, P.token)), { timeout: 30_000, message: 'the whole bounty comes back' })
      .toBeCloseTo(0, 6)
    return `status ${(await order())?.status}; the bounty came back`
  })

  await steps.run('filed-under-settled', 'ui:agent', async () => {
    await page.getByRole('button', { name: /^settled$/i }).click()
    await expect(page.locator(`[data-testid="gld-open-${oid}"]`), 'the cancelled task is on the Settled tab').toBeVisible({ timeout: 30_000 })
    await stillFrame(page)
    await a11y(page, 'guild-settled')
    return 'on the Settled tab'
  })
})
