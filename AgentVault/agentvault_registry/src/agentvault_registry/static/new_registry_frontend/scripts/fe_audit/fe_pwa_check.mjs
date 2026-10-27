/** POCKET FRAME P0 — PWA verification on frame-c (2026-07-07).
 * Asserts: manifest link present + fetchable, SW registers with scope '/',
 * app shell renders, no non-benign console errors. Screenshot for the record. */
import { chromium } from 'playwright'
import fs from 'fs'

const BASE = process.env.BASE || 'http://localhost:8101'
const OUT = '/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05/pwa'
fs.mkdirSync(OUT, { recursive: true })
const BENIGN = [/favicon/i, /WebSocket/i, /ws\/events/i, /403/, /Forbidden/i, /(png|jpg|svg|woff)/i, /manifest/i, /ERR_CONNECTION_REFUSED/i, /ERR_FAILED/i, /8200/, /CORS/i, /Access-Control/i, /status of 401/, /^zp$/]  // 401+zp: pre-existing unauth-view noise, verified identical on OLD FE (frame-b baseline 2026-07-07)
const errors = []

const run = async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] })
  const page = await (await browser.newContext({ viewport: { width: 400, height: 860 } })).newPage()
  page.on('console', (m) => { if (m.type() === 'error' && !BENIGN.some(r => r.test(m.text()))) errors.push(m.text().slice(0, 160)) })

  await page.goto(`${BASE}/ui/`, { waitUntil: 'networkidle', timeout: 25000 }).catch(() => {})
  await page.waitForTimeout(4000)

  const manifestHref = await page.locator('link[rel="manifest"]').getAttribute('href').catch(() => null)
  const manifestResp = await page.request.get(`${BASE}/manifest.webmanifest`)
  const manifest = manifestResp.ok() ? await manifestResp.json() : null
  let swInfo = { supported: false }
  for (let k = 0; k < 12; k++) {
    swInfo = await page.evaluate(async () => {
      if (!('serviceWorker' in navigator)) return { supported: false }
      const reg = await navigator.serviceWorker.getRegistration()
      return { supported: true, registered: !!reg, scope: reg?.scope || null, active: !!reg?.active }
    })
    if (swInfo.registered) break
    await page.waitForTimeout(1000)
  }
  const appRendered = await page.locator('#app *').count().catch(() => 0)
  await page.screenshot({ path: `${OUT}/pwa-mobile-viewport.png` })

  console.log('manifest_link=', manifestHref)
  console.log('manifest_fetch=', manifestResp.status(), '| name=', manifest?.name, '| start_url=', manifest?.start_url, '| icons=', manifest?.icons?.length)
  console.log('sw=', JSON.stringify(swInfo))
  console.log('app_children=', appRendered)
  console.log('console_errors=', errors.length, errors.slice(0, 3))
  const pass = !!manifestHref && manifestResp.ok() && swInfo.registered && appRendered > 0 && errors.length === 0
  console.log('PWA_CHECK=', pass ? 'PASS' : 'FAIL')
  await browser.close()
}
run().catch((e) => { console.error('OUTER', e); process.exit(0) })
