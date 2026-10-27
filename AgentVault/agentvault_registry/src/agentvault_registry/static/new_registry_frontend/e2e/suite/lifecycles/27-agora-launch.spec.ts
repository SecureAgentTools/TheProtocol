/**
 * Points bought at launch, then offered for sale (§FESUITE; the MCP tester's AGORA launch and sell rows, as a trader
 * meets them). The desk refuses a fractional launch quantity; a launch buy takes whole points once per press and they
 * reach HOLDINGS; a post-only limit sell above the market rests and locks the points; cancelling it unlocks them.
 * Read back from the venue (portfolio, orders) and the TEG (the cost). Two points stay with the throwaway trader.
 */
import { test, expect } from '../support/fixtures'
import { agentBalance, seedSession } from '../support/accounts'
import { partyWith, seedVault, stillFrame, toTick, waitActing } from '../support/commerce'
import { openRoute, toast } from '../support/ui'

const QTY = 2

test('agora_launch_buy_then_rest_a_sell', async ({ page, context, steps, api, a11y, capture }) => {
  test.setTimeout(5 * 60_000)
  const trader = await partyWith(api, 'aglaunch', 1)
  const [T] = trader.agents
  let l: any = null
  let before = 0
  let sellId = ''
  const position = async () => {
    const r = await api.json('GET', '/api/v1/agora/portfolio', { token: T.token })
    return ((r.body?.positions || []) as any[]).find((p) => p.symbol === l.symbol) || null
  }
  const myOrders = async () => ((await api.json('GET', '/api/v1/agora/orders/mine', { token: T.token })).body?.orders || []) as any[]

  await steps.run('a-listing-with-points-at-launch', 'ui:public', async () => {
    const ccy = String((await api.json('GET', '/api/v1/public/registry-config')).body?.local_currency || '')
    const all = ((await api.json('GET', '/api/v1/agora/listings')).body?.listings || []) as any[]
    const open = all.filter((x) => x.status === 'trading' && x.approved && Number(x?.stats?.ipo_remaining) >= QTY
      && Number(x?.stats?.last) > 0 && !/^P3/.test(x.symbol) && (!ccy || x.currency === ccy))
    open.sort((a, b) => Number(a.ipo_price) - Number(b.ipo_price))
    expect(open.length, 'a listing selling points at launch').toBeGreaterThan(0)
    l = open[0]
    await expect.poll(() => agentBalance(api, T.token), { timeout: 45_000 }).toBeGreaterThan(Number(l.ipo_price) * QTY * 2)
    before = await agentBalance(api, T.token)
    return `$${l.symbol}: ${l.stats.ipo_remaining} points at ${l.ipo_price}`
  })

  await seedSession(context, trader.dev.token)
  await seedVault(context, trader, T.did)

  await steps.run('buy-at-launch-once', 'ui:agent', async () => {
    capture.allow(/GET \/api\/v1\/exchange\/solvency-card$/, 404,
      'the solvency card is a flagged feature (EXCHANGE_SOLVENCY_CARD_ENABLED, default off): 404 is "no card on this venue"')
    await openRoute(page, '/contracts')
    await waitActing(page, T.did)
    await openRoute(page, `/agora?sym=${l.symbol}`)
    const qty = page.getByRole('spinbutton', { name: /points to buy at the launch price/i })
    await expect(qty).toBeVisible({ timeout: 30_000 })
    const buy = page.getByRole('button', { name: /buy at launch/i })
    await qty.fill('1.5')
    await expect(buy, 'a fraction of a point is not bought').toBeDisabled()
    await qty.fill(String(QTY))
    await expect(buy).toBeEnabled()
    const posts: string[] = []
    const onReq = (r: { url(): string; method(): string }) => { if (r.method() === 'POST' && /\/launch\/buy/.test(r.url())) posts.push(r.url()) }
    page.on('request', onReq)
    await buy.dblclick()
    await toast(page, 'success', /launch purchase/i)
    await page.waitForTimeout(1_000)
    page.off('request', onReq)
    expect(posts.length, 'one launch buy for a double press').toBe(1)
    await expect.poll(async () => Number((await position())?.qty || 0), { timeout: 30_000, message: 'the points reach the portfolio' }).toBe(QTY)
    const cost = before - (await agentBalance(api, T.token))
    expect(cost, 'paid the launch price for two points').toBeGreaterThanOrEqual(Number(l.ipo_price) * QTY - 1e-9)
    expect(cost).toBeLessThan(Number(l.ipo_price) * QTY * 1.05)
    await expect(page.locator('.ag-pos').filter({ hasText: `$${l.symbol}` }), 'HOLDINGS shows them').toBeVisible({ timeout: 30_000 })
    return `${QTY} points for ${cost}`
  })

  await steps.run('a-resting-sell-locks-the-points', 'ui:agent', async () => {
    const ticket = page.locator('[data-tour="agora-ticket"]')
    await ticket.getByRole('group', { name: /^side$/i }).getByRole('button', { name: /^sell$/i }).click()
    await ticket.getByRole('group', { name: /order type/i }).getByRole('button', { name: /^limit$/i }).click()
    const price = toTick(Number(l.stats.last) * (1 + Number(l.band_pct) / 200), Number(l.tick))
    await ticket.getByRole('textbox', { name: /^price/i }).fill(price)
    await ticket.getByRole('spinbutton', { name: /^qty/i }).fill(String(QTY))
    await ticket.getByRole('checkbox', { name: /post-only/i }).check()
    await stillFrame(page)
    await a11y(page, 'agora-sell-ticket')
    await page.locator('[data-tour="agora-place"]').click()
    await toast(page, 'success', /order/i)
    await expect.poll(async () => (await myOrders()).find((o) => o.symbol === l.symbol && o.side === 'sell')?.id || '', { timeout: 30_000 }).not.toBe('')
    sellId = String((await myOrders()).find((o) => o.symbol === l.symbol && o.side === 'sell').id)
    await expect.poll(async () => Number((await position())?.locked_qty || 0), { timeout: 30_000, message: 'the points lock while the sell rests' }).toBe(QTY)
    await expect(page.locator('.ag-pos').filter({ hasText: `$${l.symbol}` }).locator('.ag-pos-lock'), 'HOLDINGS shows the lock').toBeVisible({ timeout: 30_000 })
    return `sell ${QTY} at ${price} rests; ${QTY} locked`
  })

  await steps.run('cancel-unlocks', 'ui:agent', async () => {
    await page.locator(`[data-testid="ag-cancel-${sellId}"]`).dblclick()
    await toast(page, 'success', /cancel/i)
    await expect.poll(async () => Number((await position())?.locked_qty || 0), { timeout: 30_000, message: 'the points unlock' }).toBe(0)
    const p = await position()
    const filled = QTY - Number(p?.qty || 0)
    expect(filled, 'nothing sold in the seconds it rested (or the venue says how much)').toBeGreaterThanOrEqual(0)
    await expect(page.locator('[data-testid="toast"][data-kind="error"]').filter({ hasText: /cancel failed/i }),
      'a second press on a cancel already made says nothing').toHaveCount(0)
    return `unlocked; ${p?.qty} point(s) held`
  })
})
