/**
 * A resting order on the AGORA desk (§FESUITE; the MCP tester's AGORA order lifecycle, as a trader meets it): the desk
 * refuses prices and quantities that are not prices or quantities before anything leaves the page; a post-only limit
 * buy below the market rests, its escrow leaves the trader's balance; the trader cancels it from MY OPEN ORDERS and the
 * escrow comes back. Read back from the venue (the order) and the TEG (the balance). A fill by another trader in the
 * seconds the order rests is accounted for, never assumed away.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, seedSession } from '../support/accounts'
import { partyWith, seedVault, stillFrame, toTick, waitActing } from '../support/commerce'
import { openRoute, toast } from '../support/ui'

const QTY = 2

test('agora_rest_and_cancel_an_order', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(5 * 60_000)
  const trader = await partyWith(api, 'agtrader', 1)
  const [T] = trader.agents
  let sym = ''
  let price = ''
  let before = 0
  let orderId = ''

  const myOrders = async () => {
    const r = await api.json('GET', '/api/v1/agora/orders/mine', { token: T.token })
    return (r.body?.orders || []) as any[]
  }

  await steps.run('pick-a-quiet-price', 'ui:public', async () => {
    const r = await api.json('GET', '/api/v1/agora/listings')
    const frameCcy = String((await api.json('GET', '/api/v1/public/registry-config')).body?.local_currency || '')
    const live = (r.body?.listings || []).filter((l: any) => l.status === 'trading' && Number(l?.stats?.last) > 0
      && !/^P3/.test(l.symbol) && (!frameCcy || l.currency === frameCcy))
    live.sort((a: any, b: any) => Number(a.stats.last) - Number(b.stats.last))
    expect(live.length, 'a trading listing on this venue').toBeGreaterThan(0)
    const l = live[0]
    sym = l.symbol
    // half the price band below the last trade: inside the band, below the market, so it rests (post-only besides)
    price = toTick(Number(l.stats.last) * (1 - Number(l.band_pct) / 200), Number(l.tick))
    await expect.poll(() => agentBalance(api, T.token), { timeout: 45_000, message: 'the trader holds its grant' }).toBeGreaterThan(Number(price) * QTY)
    before = await agentBalance(api, T.token)
    return `$${sym} last ${l.stats.last}; a buy of ${QTY} at ${price}`
  })

  await seedSession(context, trader.dev.token)
  await seedVault(context, trader, T.did)

  await steps.run('the-ticket-refuses-what-is-not-an-order', 'ui:agent', async () => {
    capture.allow(/GET \/api\/v1\/exchange\/solvency-card$/, 404,
      'the solvency card is a flagged feature (EXCHANGE_SOLVENCY_CARD_ENABLED, default off): 404 is "no card on this venue"')
    // A person arrives on the desk from inside the console. (A cold load straight onto a page that needs an acting
    // agent can race the console's own agent restore and abort the first navigation: reported, not driven here.)
    await openRoute(page, '/contracts')
    await waitActing(page, T.did)
    await openRoute(page, `/agora?sym=${sym}`)
    await expect(page.locator('.ag-card-head').filter({ hasText: `TRADE $${sym}` })).toBeVisible({ timeout: 30_000 })
    const ticket = page.locator('[data-tour="agora-ticket"]')
    await ticket.getByRole('group', { name: /^side$/i }).getByRole('button', { name: /^buy$/i }).click()
    await ticket.getByRole('group', { name: /order type/i }).getByRole('button', { name: /^limit$/i }).click()
    const place = page.locator('[data-tour="agora-place"]')
    const px = ticket.getByRole('textbox', { name: /^price/i })
    const qty = ticket.getByRole('spinbutton', { name: /^qty/i })
    await qty.fill(String(QTY))
    const sent: string[] = []
    const onReq = (r: { url(): string; method(): string }) => { if (r.method() === 'POST' && /\/agora\/orders(\?|$)/.test(r.url())) sent.push(r.url()) }
    page.on('request', onReq)
    for (const bad of ['-1', 'abc', '1e309', '1abc']) {
      await px.fill(bad)
      await expect(place, `a price of "${bad}" is not placed`).toBeDisabled()
    }
    await px.fill(price)
    await qty.fill('1.5')
    await expect(place, 'a fraction of a point is not placed').toBeDisabled()
    await qty.fill(String(QTY))
    await expect(place).toBeEnabled()
    page.off('request', onReq)
    expect(sent, 'nothing left the page').toEqual([])
    return 'four non-prices and a fractional quantity refused on the page'
  })

  await steps.run('place-a-resting-buy', 'ui:agent', async () => {
    await page.locator('[data-tour="agora-ticket"]').getByRole('checkbox', { name: /post-only/i }).check()
    await stillFrame(page)
    await a11y(page, 'agora-ticket')
    await page.locator('[data-tour="agora-place"]').click()
    await toast(page, 'success', /order/i)
    // a fresh trader: its only order on this listing is the one the page just placed
    await expect.poll(async () => (await myOrders()).find((o) => o.symbol === sym && o.side === 'buy')?.id || '',
      { timeout: 30_000, message: 'the venue holds the order' }).not.toBe('')
    const o = (await myOrders()).find((x) => x.symbol === sym && x.side === 'buy' && ['open', 'partial', 'funding'].includes(x.status))
    expect(o, 'the order rests').toBeTruthy()
    orderId = String(o.id)
    await expect(page.locator(`[data-testid="ag-cancel-${orderId}"]`), 'it is in MY OPEN ORDERS').toBeVisible({ timeout: 30_000 })
    const escrowed = before - (await agentBalance(api, T.token))
    expect(escrowed, 'the buy escrow left the balance').toBeCloseTo(Number(price) * QTY, 6)
    return `order ${orderId.slice(0, 8)}… ${o.status}, ${escrowed} escrowed`
  })

  await steps.run('cancel-and-get-the-escrow-back', 'ui:agent', async () => {
    await page.locator(`[data-testid="ag-cancel-${orderId}"]`).click()
    await toast(page, 'success', /cancel/i)
    await expect.poll(async () => (await myOrders()).find((o) => String(o.id) === orderId)?.status || 'gone', { timeout: 30_000 })
      .toMatch(/cancel|gone/)
    await expect(page.locator(`[data-testid="ag-cancel-${orderId}"]`), 'it leaves MY OPEN ORDERS').toHaveCount(0)
    const o = (await myOrders()).find((x) => String(x.id) === orderId)
    const filled = o ? Number(o.qty) - Number(o.remaining) : 0
    await expect.poll(async () => before - (await agentBalance(api, T.token)), { timeout: 30_000, message: 'the escrow residue comes back' })
      .toBeCloseTo(filled * Number(price), 6)
    return filled ? `cancelled after ${filled} filled; the residue came back` : 'cancelled; the whole escrow came back'
  })
})
