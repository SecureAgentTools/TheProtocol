/** POCKET mode E2E (2026-07-07) — drives all 5 tabs on frame-c, screenshots each,
 * checks bottom bar, mode toggle presence, balance render, 0 JS errors. */
import { chromium } from 'playwright'
const BASE = process.env.BASE || 'http://localhost:8101'
const TOKEN = process.env.TOKEN || '', USERJSON = process.env.USERJSON || '{}'
const OUT = '/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05/pwa'
const BENIGN = [/favicon/i, /WebSocket/i, /ws\/events/i, /403/, /Forbidden/i, /(png|jpg|svg|woff)/i, /manifest/i, /401/, /^zp$/, /ERR_/i, /CORS/i, /Access-Control/i, /8200/]
let pass = 0, fail = 0
const ok = (m) => { console.log('  OK', m); pass++ }
const bad = (m) => { console.log('  XX', m); fail++ }

const run = async () => {
  const b = await chromium.launch({ headless: true, args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'] })
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } })
  await ctx.addInitScript(([t,u]) => { try { sessionStorage.setItem('sovereign_auth_token',t); sessionStorage.setItem('sovereign_user',u); localStorage.setItem('sovereign_user',u) } catch {} }, [TOKEN, USERJSON])
  const p = await ctx.newPage()
  const errs = []
  p.on('pageerror', e => { if (!BENIGN.some(r=>r.test(String(e)))) errs.push(String(e).slice(0,140)) })
  p.on('console', m => { if (m.type()==='error' && !BENIGN.some(r=>r.test(m.text()))) errs.push(m.text().slice(0,140)) })

  await p.goto(`${BASE}/ui/#/pocket/home`, { waitUntil: 'networkidle', timeout: 25000 }).catch(()=>{})
  await p.waitForTimeout(3500)

  const bar = await p.locator('.pk-bar .pk-tab-btn').count().catch(()=>0)
  ;(bar === 5 ? ok : bad)(`bottom bar has 5 tabs (${bar})`)
  const balVisible = await p.locator('.ph-bal-num').count().catch(()=>0)
  ;(balVisible ? ok : bad)('balance renders on Home')
  const secure = await p.locator('.pk-secure').count().catch(()=>0)
  ;(secure ? ok : bad)('IRONKEY badge visible in header')
  await p.screenshot({ path: `${OUT}/pocket-home.png` })

  for (const [tab, sel, name] of [
    ['agents', '.pg-card, .pg-empty', 'Agents'],
    ['approvals', '.pa-hero, .pa-card', 'Approvals'],
    ['activity', '.pv-row, .pv-empty', 'Activity'],
    ['more', '.pm-group', 'More'],
  ]) {
    await p.locator(`.pk-tab-btn[href="#/pocket/${tab}"]`).click().catch(async () => { await p.goto(`${BASE}/ui/#/pocket/${tab}`).catch(()=>{}) })
    await p.waitForTimeout(2200)
    const has = await p.locator(sel).count().catch(()=>0)
    ;(has ? ok : bad)(`${name} tab renders content (${has})`)
    await p.screenshot({ path: `${OUT}/pocket-${tab}.png` })
  }

  // More → Advanced link present; Devices embed expands
  const adv = await p.locator('.pm-adv').count().catch(()=>0)
  ;(adv ? ok : bad)('Advanced-mode switch present in More')
  await p.locator('.pm-item', { hasText: 'Devices' }).first().click().catch(()=>{})
  await p.waitForTimeout(1500)
  const embed = await p.locator('.pm-embed .pf-card').count().catch(()=>0)
  ;(embed ? ok : bad)('Devices panel embeds inside More')
  await p.screenshot({ path: `${OUT}/pocket-more-devices.png`, fullPage: true })

  // sidebar entry exists in Advanced mode
  const p2 = await ctx.newPage()
  await p2.goto(`${BASE}/ui/#/mission-control`, { waitUntil: 'networkidle', timeout: 25000 }).catch(()=>{})
  await p2.waitForTimeout(3500)
  const bodyTxt = await p2.evaluate(() => document.body.innerText).catch(()=> '')
  ;(bodyTxt.includes('Pocket mode') ? ok : bad)('Advanced sidebar shows "Pocket mode" entry (top-level)')

  ;(errs.length === 0 ? ok : bad)(`no JS errors (${errs.length}${errs.length ? ': '+errs[0] : ''})`)
  console.log(`POCKET_MODE pass=${pass} fail=${fail}`)
  await b.close()
}
run().catch(e => { console.error('OUTER', e); process.exit(0) })
