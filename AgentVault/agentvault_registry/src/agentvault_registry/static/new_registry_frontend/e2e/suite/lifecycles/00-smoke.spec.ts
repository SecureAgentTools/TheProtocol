/**
 * The suite's own smoke (§FESUITE): the console loads for a visitor with no session, its login form is there and usable,
 * and the page is clean (no console error, no refused call, nothing serious for axe). If this fails, every lifecycle
 * after it would fail for the same reason, so it runs first.
 */
import { request as pwRequest } from '@playwright/test'
import { test, expect } from '../support/fixtures'
import { BASE_URL, PEER_API_URL, PEER_URL, consoleUrl } from '../support/env'

test('console_smoke', async ({ page, steps, a11y }) => {
  await steps.run('login-page-renders', 'ui:public', async () => {
    await page.goto(consoleUrl('/login'))
    const email = page.locator('input[type="email"], input[name="email"], input[autocomplete="username"]').first()
    await expect(email).toBeVisible()
    await expect(page.locator('input[type="password"]').first()).toBeVisible()
    return `title "${await page.title()}"`
  })
  await a11y(page, 'login')
})

/**
 * The suite's controls: a capture that has never seen a console error or a refused call proves nothing by reporting
 * zero. This plants one of each and requires the capture to have seen both, then accounts for them, so the page-clean
 * row of every other lifecycle means something.
 */
test('suite_controls', async ({ page, steps, capture }) => {
  await page.goto(consoleUrl('/login'))
  await expect(page.locator('input[type="password"]').first()).toBeVisible()
  await steps.run('capture-sees-a-console-error', 'ui:public', async () => {
    capture.allowConsole(/fesuite-control: planted/, 'the control plants it')
    await page.evaluate(() => console.error('fesuite-control: planted'))
    await expect.poll(() => capture.seenConsoleError(/fesuite-control: planted/)).toBe(true)
    return 'seen'
  })
  await steps.run('capture-sees-a-refused-call', 'ui:public', async () => {
    capture.allow(/GET \/api\/v1\/fesuite-control-404$/, 404, 'the control asks for a path that does not exist')
    await page.evaluate(async () => { await fetch('/api/v1/fesuite-control-404').catch(() => null) })
    await expect.poll(() => capture.seenRefusal(/\/api\/v1\/fesuite-control-404$/, 404)).toBe(true)
    return 'seen'
  })
})

/** The other half of the controls: an error nobody announced must fail the lifecycle. Expected to fail. */
test('suite_control_unannounced_error_fails', async ({ page }) => {
  test.fail(true, 'a control: the capture must refuse an unannounced console error')
  await page.goto(consoleUrl('/login'))
  await expect(page.locator('input[type="password"]').first()).toBeVisible()
  await page.evaluate(() => console.error('fesuite-control: unannounced'))
  await page.waitForTimeout(200)
})

/**
 * The peer frame's half of the shared ledger feed (§FESUITE): the console reads the peer's public event feed from the
 * browser, so the peer must accept this console's origin. Measured once here, as a deployment fact of the peer; the
 * capture counts the refused calls apart on every other page instead of failing each of them for it.
 */
test('peer_accepts_this_console', async ({ steps }) => {
  if (!PEER_URL) { steps.notMeasured('peer-cors', 'ui:public', 'no peer frame configured (FESUITE_PEER_URL)'); return }
  const origin = new URL(BASE_URL).origin
  const ok = await steps.check('peer-cors', 'ui:public', async () => {
    const ctx = await pwRequest.newContext({ baseURL: PEER_API_URL, ignoreHTTPSErrors: false })
    try {
      const r = await ctx.get('/api/v1/public/eventstore-recent?limit=1', { headers: { Origin: origin } })
      const acao = r.headers()['access-control-allow-origin'] || ''
      expect(r.status(), 'the peer answers its public feed').toBeLessThan(400)
      expect([origin, '*'], `the peer's Access-Control-Allow-Origin for ${origin}`).toContain(acao)
      return `the peer accepts ${origin}`
    } finally { await ctx.dispose() }
  })
  if (!ok) steps.markLastAsEnv(`the peer frame does not accept this console's origin (${origin}): its ALLOWED_ORIGINS needs it, or the cross-frame ledger feed stays empty here`)
})
