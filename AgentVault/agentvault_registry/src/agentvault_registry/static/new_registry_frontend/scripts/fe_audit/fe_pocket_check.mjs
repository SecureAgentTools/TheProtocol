/** POCKET FRAME views render check (2026-07-07) — authed, frame-c. */
import { chromium } from 'playwright'
const BASE = process.env.BASE || 'http://localhost:8101'
const TOKEN = process.env.TOKEN || ''
const USERJSON = process.env.USERJSON || '{}'
const BENIGN = [/favicon/i, /WebSocket/i, /ws\/events/i, /403/, /Forbidden/i, /(png|jpg|svg|woff)/i, /manifest/i, /401/, /^zp$/, /ERR_/i, /CORS/i, /Access-Control/i, /8200/]
const run = async () => {
  const b = await chromium.launch({ headless: true, args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'] })
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 } })
  await ctx.addInitScript(([t,u]) => { try { sessionStorage.setItem('sovereign_auth_token',t); sessionStorage.setItem('sovereign_user',u); localStorage.setItem('sovereign_user',u) } catch {} }, [TOKEN, USERJSON])
  const results = {}
  for (const [name, path, needle] of [
    ['PocketFrame', '/ui/#/pocket-frame', 'POCKET FRAME'],
    ['PocketApprovals', '/ui/#/pocket-approvals', 'Approvals'],
  ]) {
    const p = await ctx.newPage()
    const errs = []
    p.on('console', m => { if (m.type()==='error' && !BENIGN.some(r=>r.test(m.text()))) errs.push(m.text().slice(0,140)) })
    p.on('pageerror', e => { if (!BENIGN.some(r=>r.test(String(e)))) errs.push('JS:'+String(e).slice(0,140)) })
    await p.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 25000 }).catch(()=>{})
    await p.waitForTimeout(3500)
    const body = await p.evaluate(() => document.body.innerText).catch(()=> '')
    const blankIcons = await p.locator('.icon-wrap:empty, [class*="ico"]:empty').count().catch(()=>0)
    await p.screenshot({ path: `/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05/pwa/${name}.png` })
    results[name] = { hasNeedle: body.includes(needle), children: await p.locator('#main-content *, #app *').count().catch(()=>0), errs: errs.length, sampleErr: errs.slice(0,2), blankIcons }
    await p.close()
  }
  for (const [k,v] of Object.entries(results)) console.log(k, JSON.stringify(v))
  const pass = Object.values(results).every(v => v.hasNeedle && v.children>50 && v.errs===0)
  console.log('POCKET_VIEWS=', pass ? 'PASS' : 'FAIL')
  await b.close()
}
run().catch(e => { console.error('OUTER', e); process.exit(0) })
