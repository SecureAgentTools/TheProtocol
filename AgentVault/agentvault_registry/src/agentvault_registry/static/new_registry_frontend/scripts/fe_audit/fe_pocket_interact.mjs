/** POCKET FRAME UI interaction test (AAA pass, 2026-07-07) — drives the REAL views on
 * frame-c: register a device via the form → appears in list → remove (modal) → gone;
 * pair-phone → QR canvas painted; agent picker on Approvals renders. Cleans up. */
import { chromium } from 'playwright'
const BASE = process.env.BASE || 'http://localhost:8101'
const TOKEN = process.env.TOKEN || '', USERJSON = process.env.USERJSON || '{}'
const OUT = '/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05/pwa'
let pass = 0, fail = 0
const ok = (m) => { console.log('  OK', m); pass++ }
const bad = (m) => { console.log('  XX', m); fail++ }

const run = async () => {
  const b = await chromium.launch({ headless: true, args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'] })
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } })
  await ctx.addInitScript(([t,u]) => { try { sessionStorage.setItem('sovereign_auth_token',t); sessionStorage.setItem('sovereign_user',u); localStorage.setItem('sovereign_user',u) } catch {} }, [TOKEN, USERJSON])
  const p = await ctx.newPage()
  const errs = []
  p.on('pageerror', e => errs.push(String(e).slice(0,140)))

  // ── PocketFrame: register a device via the form ──
  await p.goto(`${BASE}/ui/#/pocket-frame`, { waitUntil: 'networkidle', timeout: 25000 }).catch(()=>{})
  await p.waitForTimeout(2500)
  const topic = 'pf-ui-' + Date.now().toString().slice(-8)
  await p.locator('input[placeholder="ntfy topic"]').fill(topic)
  await p.locator('input[placeholder="e.g. My phone"]').fill('UI test device')   // label
  await p.locator('button.pf-btn-primary:has-text("Register device")').click()
  await p.waitForTimeout(3000)
  const listed = await p.locator('.pf-dev-target', { hasText: topic }).count().catch(()=>0)
  ;(listed ? ok : bad)(`device ${topic} appears in list`)
  const hint = await p.locator('.pf-hint', { hasText: topic }).count().catch(()=>0)
  ;(hint ? ok : bad)('subscribe hint + QR shown after register')

  // remove via modal
  await p.locator('.pf-dev', { hasText: topic }).locator('button.pf-btn-danger').click().catch(()=>{})
  await p.waitForTimeout(700)
  const modalShown = await p.locator('text=Remove push device?').count().catch(()=>0)
  ;(modalShown ? ok : bad)('remove opens ConfirmActionModal (not a raw delete)')
  await p.locator('button:has-text("Remove device")').last().click().catch(()=>{})
  await p.waitForTimeout(2500)
  const gone = await p.locator('.pf-dev-target', { hasText: topic }).count().catch(()=>1)
  ;(gone === 0 ? ok : bad)('device removed after confirm')
  await p.screenshot({ path: `${OUT}/interact-pocketframe.png`, fullPage: true })

  // ── pair phone → QR canvas painted ──
  await p.locator('.pf-input').first().fill('UI pair test')
  await p.locator('button:has-text("Pair phone")').click()
  await p.waitForTimeout(2500)
  const qrPainted = await p.evaluate(() => {
    const c = document.querySelector('canvas.pf-qr'); if (!c) return false
    const ctx = c.getContext('2d'); const d = ctx.getImageData(0,0,c.width,c.height).data
    let nonWhite = 0; for (let i=0;i<d.length;i+=4) if (d[i]<200) nonWhite++
    return nonWhite > 500
  }).catch(()=>false)
  ;(qrPainted ? ok : bad)('pairing QR canvas actually painted')

  // ── Approvals view: picker + empty hero ──
  const p2 = await ctx.newPage()
  p2.on('pageerror', e => errs.push('APPR:'+String(e).slice(0,120)))
  await p2.goto(`${BASE}/ui/#/pocket-approvals`, { waitUntil: 'networkidle', timeout: 25000 }).catch(()=>{})
  await p2.waitForTimeout(2500)
  const hero = await p2.locator('.pa-hero').count().catch(()=>0)
  ;(hero ? ok : bad)('Approvals shows guided empty state (no agent selected)')
  const opts = await p2.locator('.pa-select option').count().catch(()=>0)
  ;(opts >= 1 ? ok : bad)(`agent picker populated (${opts} options)`)
  await p2.screenshot({ path: `${OUT}/interact-approvals.png` })

  ;(errs.length === 0 ? ok : bad)(`no page JS errors (${errs.length}${errs.length?': '+errs[0]:''})`)
  console.log(`POCKET_INTERACT pass=${pass} fail=${fail}`)
  await b.close()
}
run().catch(e => { console.error('OUTER', e); process.exit(0) })
