import { chromium } from 'playwright'
const BASE = process.env.BASE || 'http://localhost:8101'
const TOKEN = process.env.TOKEN || '', USERJSON = process.env.USERJSON || '{}'
const TAG = process.env.TAG || 'before'
const OUT = '/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05/pwa'
const run = async () => {
  const b = await chromium.launch({ headless: true, args: ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu'] })
  for (const [vw, vh, vn] of [[390, 844, 'mobile'], [1440, 900, 'desktop']]) {
    const ctx = await b.newContext({ viewport: { width: vw, height: vh } })
    await ctx.addInitScript(([t,u]) => { try { sessionStorage.setItem('sovereign_auth_token',t); sessionStorage.setItem('sovereign_user',u); localStorage.setItem('sovereign_user',u) } catch {} }, [TOKEN, USERJSON])
    for (const [name, path] of [['pocketframe','/ui/#/pocket-frame'],['approvals','/ui/#/pocket-approvals']]) {
      const p = await ctx.newPage()
      await p.goto(`${BASE}${path}`, { waitUntil: 'networkidle', timeout: 25000 }).catch(()=>{})
      await p.waitForTimeout(3000)
      await p.screenshot({ path: `${OUT}/${TAG}-${name}-${vn}.png`, fullPage: vn==='mobile' })
      await p.close()
    }
    await ctx.close()
  }
  await b.close(); console.log('SHOTS_DONE', TAG)
}
run().catch(e=>{console.error(e);process.exit(0)})
