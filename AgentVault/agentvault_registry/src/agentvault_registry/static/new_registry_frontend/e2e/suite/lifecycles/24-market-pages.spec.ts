/**
 * The public commerce pages a visitor meets before an account (§FESUITE): the service showcase and the AGORA listings.
 * The showcase states what the frame offers: where the frame switched its live calls off, the page says so before a
 * press and nothing is called; where they run, a free call answers. The listings page shows the venue's trading
 * listings as the API states them and its door leads to the desk. Buying a paid service needs a service agent this
 * frame can reach: where there is none, that is recorded as not measured, with the frame's own reason.
 */
import { test, expect } from '../support/fixtures'
import { stillFrame } from '../support/commerce'
import { openRoute } from '../support/ui'

test('market_pages_for_a_visitor', async ({ page, steps, api, a11y }) => {
  test.setTimeout(4 * 60_000)
  const showcase = (await api.json('GET', '/api/v1/public/showcase/agents')).body || {}

  await steps.run('the-showcase-says-what-it-offers', 'ui:public', async () => {
    const calls: string[] = []
    page.on('request', (r) => { if (/\/public\/showcase\/call/.test(r.url())) calls.push(r.url()) })
    await openRoute(page, '/services')
    const first = page.locator('.svc-card').first()
    await expect(first.locator('.svc-card-head'), 'the catalog renders').toBeVisible({ timeout: 30_000 })
    // the first service opens with the page; its head toggles it
    if ((await first.locator('.svc-card-head').getAttribute('aria-expanded')) !== 'true') await first.locator('.svc-card-head').click()
    const run = first.locator('.svc-btn')
    await expect(run).toBeVisible()
    if (showcase.enabled === false) {
      await expect(page.locator('[data-testid="svc-showcase-off"]'), 'the page says live calls are off here').toBeVisible()
      await expect(run, 'a service that cannot be called offers no run').toBeDisabled()
      expect(calls, 'nothing is called').toEqual([])
      await stillFrame(page)
      await a11y(page, 'services-off')
      return `live calls off on this frame: "${String(showcase.reason || '').slice(0, 60)}"`
    }
    if (await first.locator('.svc-chip').count()) await first.locator('.svc-chip').first().click()
    await run.click()
    await expect(first, 'a free call answers').toContainText(/./, { timeout: 30_000 })
    await stillFrame(page)
    await a11y(page, 'services-on')
    return `live calls on; ${calls.length} call(s) answered`
  })

  await steps.run('the-listings-the-venue-trades', 'ui:public', async () => {
    const r = await api.json('GET', '/api/v1/agora/listings')
    const trading = (r.body?.listings || []).filter((l: any) => l.status === 'trading')
    await openRoute(page, '/agora/listings')
    if (!trading.length) {
      await expect(page.locator('.sd-empty')).toBeVisible({ timeout: 30_000 })
      return 'no trading listing on this venue; the page says so'
    }
    const sample = trading.slice(0, 3)
    for (const l of sample) {
      await expect(page.locator('.sd-card').filter({ hasText: `$${l.symbol}` }).first(), `$${l.symbol} is listed`).toBeVisible({ timeout: 30_000 })
    }
    await page.getByRole('searchbox', { name: /search ticker/i }).fill(sample[0].symbol)
    await expect(page.locator('.sd-card').filter({ hasText: `$${sample[0].symbol}` }).first()).toBeVisible()
    await stillFrame(page)
    await a11y(page, 'agora-listings')
    return `${trading.length} trading listing(s); ${sample.map((l: any) => '$' + l.symbol).join(', ')} on the page`
  })

  if (!(showcase.agents || []).length) {
    steps.notMeasured('buy-a-paid-service', 'ui:agent',
      `no service agent this frame can reach (${showcase.enabled === false ? String(showcase.reason || 'showcase off') : 'none listed'}); the buy door (BuyServicePanel) needs one`)
  }
})
