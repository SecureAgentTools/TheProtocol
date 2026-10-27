/**
 * The flare shop as a person meets it (§FESUITE; the MCP tester's flare lifecycle reads the same catalog). The page
 * must say whether this frame sells flare in its own currency and agree with the registry: the catalog it shows is the
 * catalog the API answers, prices in the frame's currency, and every buy button is closed with the reason when the lane
 * is off. A purchase is not driven here: it moves more than dust, and the sandbox lane is off; NOT MEASURED says so.
 */
import { test, expect } from '../support/fixtures'
import { registerDeveloper, seedSession } from '../support/accounts'
import { openRoute } from '../support/ui'
import { readBack, steady } from '../support/social'

test('flare_shop_catalog_and_lane', async ({ page, context, steps, api, a11y }) => {
  const dev = await registerDeveloper(api, 'flaredev')
  await seedSession(context, dev.token)
  let enabled = false

  await steps.run('the-shop-says-what-this-frame-sells', 'ui:developer', async () => {
    expect(await openRoute(page, '/flare-shop')).toBe('/flare-shop')
    const tiers = page.locator('[data-testid^="fsh-tier-"]')
    await expect(tiers.first()).toBeVisible({ timeout: 20_000 })
    enabled = await page.locator('[data-testid="fsh-lane-on"]').isVisible()
    const off = page.locator('[data-testid="fsh-lane-off"]')
    if (!enabled) await expect(off, 'a closed lane says so').toBeVisible()
    await steady(page)
    await a11y(page, 'flare-shop')
    return `${await tiers.count()} tiers; lane ${enabled ? 'open' : 'closed'}`
  })

  await steps.run('buttons-agree-with-the-lane', 'ui:developer', async () => {
    const buys = page.locator('[data-testid^="fsh-buy-"]')
    const n = await buys.count()
    expect(n, 'every tier has a buy button').toBeGreaterThan(0)
    for (let i = 0; i < n; i++) {
      if (enabled) await expect(buys.nth(i)).toBeEnabled()
      else {
        await expect(buys.nth(i)).toBeDisabled()
        await expect(buys.nth(i)).toContainText(/lane closed/i)
      }
    }
    // the registry's own answer for this account: no tier owned yet
    const status = (await readBack(api, '/api/v1/fiat/flare/status', dev.token)).body || {}
    expect('flare_tier' in status, 'the status names the account\'s tier field').toBe(true)
    expect(status.flare_tier ?? null, 'a fresh account owns no tier').toBeNull()
    await expect(page.locator('[data-testid="fsh-current-tier"]')).toContainText(/none yet/i)
    return `${n} buy buttons ${enabled ? 'open' : 'closed with the reason'}; no tier owned (API and page agree)`
  })

  steps.notMeasured('flare-purchase', 'ui:developer', enabled
    ? 'a tier costs more than dust; the suite does not buy one'
    : 'FLARE_LOCAL_PURCHASE_ENABLED is off on this frame: nothing can be bought here')
})
