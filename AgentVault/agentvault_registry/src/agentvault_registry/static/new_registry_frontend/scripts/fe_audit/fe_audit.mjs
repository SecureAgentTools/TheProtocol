/**
 * fe_audit.mjs — Non-destructive frontend audit (Playwright/Chromium), BULLETPROOF single-process.
 * Visits every viewable route on frame-c, injects Commander auth into sessionStorage, records per
 * route: console/page errors, failed /api 4xx-5xx, blank icons (Icon.vue renders '' for unmapped
 * names), broken images, horizontal overflow, stuck-loading, a11y smoke, + a viewport screenshot.
 * Never clicks a mutating control, never submits a form.
 *
 * Robustness: listeners attached once per page; a crashed/closed page or a throwing route is caught
 * and the page is recreated — ONE bad route can never end the run. Browser relaunches on disconnect.
 * Incremental crash-safe writes + resume. No external retry loop (that leaked chromium before).
 *
 * Usage: BASE=http://localhost:8101 TOKEN=... USERJSON='{...}' [AGENT_DID=...] node fe_audit.mjs
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'

const BASE = process.env.BASE || 'http://localhost:8101'
const OUT = process.env.OUT || '/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05'
const TOKEN = process.env.TOKEN || ''
const USERJSON = process.env.USERJSON || '{}'
const AGENT_DID = process.env.AGENT_DID || ''
const SHOTS = path.join(OUT, 'screenshots')
const JSONP = path.join(OUT, 'report.json')
fs.mkdirSync(SHOTS, { recursive: true })

const ROUTES = [
  ['/', 'landing'], ['/enterprise', 'enterprise'], ['/showcase', 'showcase'],
  ['/services', 'services'], ['/monetize', 'monetize'], ['/templates', 'templates'],
  ['/architecture', 'architecture'], ['/frame-commander', 'frame-commander'],
  ['/getting-started', 'getting-started'], ['/whitepaper', 'whitepaper'],
  ['/a2a-protocol', 'a2a-protocol'], ['/token-economy', 'token-economy'],
  ['/trust-reputation', 'trust-reputation'], ['/compliance', 'compliance'],
  ['/operator', 'operator'], ['/leaderboard', 'leaderboard'],
  ['/founders-wall', 'founders-wall'], ['/stocks', 'stocks'],
  ['/become-a-backer', 'become-a-backer'], ['/buy-avt', 'buy-avt'],
  ['/mission-control', 'mission-control'], ['/discovery', 'discovery'],
  ['/discover', 'discover'], ['/my-agents', 'my-agents'], ['/onboarding', 'onboarding'],
  ['/agent-builder', 'agent-builder'], ['/agent-forge', 'agent-forge'],
  ['/settings', 'settings'], ['/api-keys', 'api-keys'], ['/contracts', 'contracts'],
  ['/disputes', 'disputes'], ['/settlements', 'settlements'], ['/staking', 'staking'],
  ['/governance', 'governance'], ['/senate', 'senate'], ['/exchange', 'exchange'],
  ['/forex', 'forex'], ['/trading', 'trading'], ['/flare-manager', 'flare-manager'],
  ['/bundles', 'bundles'], ['/community', 'community'], ['/support', 'support'],
  ['/tutorials', 'tutorials'], ['/attestations', 'attestations'], ['/arena', 'arena'],
  ['/games', 'games'], ['/health-monitor', 'health-monitor'], ['/federation', 'federation'],
  ['/federation-discover', 'federation-discover'], ['/galactic-map', 'galactic-map'],
  ['/galactic-command', 'galactic-command'], ['/eigentrust-command', 'eigentrust-command'],
  ['/agentworld', 'agentworld'], ['/universe', 'universe'], ['/command-center', 'command-center'],
  ['/organization', 'organization'], ['/ci-cd', 'ci-cd'], ['/export-import', 'export-import'],
  ['/frame-management', 'frame-management'], ['/operator-management', 'operator-management'],
  ['/operator-portal', 'operator-portal'], ['/protocol-theatre', 'protocol-theatre'],
  ['/ironhand/theatre', 'ironhand-theatre'], ['/webhooks', 'webhooks'],
  ['/admin/agents', 'admin-agents'], ['/admin/developers', 'admin-developers'],
  ['/admin/registry-card', 'admin-registry-card'], ['/admin/reactors', 'admin-reactors'],
  ['/admin/evals', 'admin-evals'], ['/admin/forensics', 'admin-forensics'],
  ['/admin/canaries', 'admin-canaries'], ['/admin/compliance', 'admin-compliance'],
  ['/admin/ironhand', 'admin-ironhand'], ['/admin/exchange', 'admin-exchange'],
  ['/admin/treasury', 'admin-treasury'], ['/admin/events', 'admin-events'],
  ['/admin/audit-logs', 'admin-audit-logs'], ['/admin/broadcasts', 'admin-broadcasts'],
  ['/admin/email', 'admin-email'], ['/admin/fiat-ops', 'admin-fiat-ops'],
  ['/admin/fiat-pricing', 'admin-fiat-pricing'], ['/admin/bridge', 'admin-bridge'],
  ['/admin/fx', 'admin-fx'], ['/admin/peers', 'admin-peers'],
  ['/admin/settlements', 'admin-settlements'], ['/admin/cicd', 'admin-cicd'],
  ['/admin/marketplace', 'admin-marketplace'], ['/admin/attestations', 'admin-attestations'],
  ['/admin/attestation-analytics', 'admin-attestation-analytics'],
]
if (AGENT_DID) ROUTES.push([`/agent-profile/${AGENT_DID}`, 'agent-profile'])
const MOBILE = new Set(['landing', 'mission-control', 'leaderboard', 'services', 'monetize',
  'discovery', 'stocks', 'settings', 'admin-evals', 'agent-forge', 'founders-wall', 'onboarding'])

const BENIGN = [/favicon/i, /readyState/i, /H\.264/i, /manifest\.json/i, /ResizeObserver/i,
  /WebSocket.*clos/i, /cesium/i, /Failed to load resource.*(png|jpg|svg|woff)/i]
const isBenign = (s) => BENIGN.some((r) => r.test(s || ''))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// Mutable per-route bucket; page listeners (attached ONCE per page) write into it.
let cur = { errors: [], apiFails: [] }

const run = async () => {
  const results = fs.existsSync(JSONP) ? JSON.parse(fs.readFileSync(JSONP, 'utf8')) : []
  const done = new Set(results.map((r) => `${r.viewport}:${r.label}`))
  let browser = null, ctx = null, page = null, curVp = null

  const launch = async () => { browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] }) }
  const newPage = async (w) => {
    if (!browser || !browser.isConnected()) await launch()
    ctx = await browser.newContext({ viewport: { width: w, height: 900 }, deviceScaleFactor: 1 })
    await ctx.addInitScript(([uj, tok]) => {
      try { sessionStorage.setItem('sovereign_auth_token', tok); sessionStorage.setItem('sovereign_user', uj); localStorage.setItem('sovereign_user', uj) } catch {}
    }, [USERJSON, TOKEN])
    page = await ctx.newPage()
    curVp = w
    page.on('console', (m) => { if (m.type() === 'error' && !isBenign(m.text())) cur.errors.push(m.text().slice(0, 300)) })
    page.on('pageerror', (e) => { if (!isBenign(String(e))) cur.errors.push('PAGEERROR: ' + String(e).slice(0, 300)) })
    page.on('response', (r) => { const u = r.url(), s = r.status(); if (u.includes('/api/v1/') && s >= 400) cur.apiFails.push({ status: s, url: u.replace(/\?.*/, '').replace(BASE, '') }) })
  }
  const ensurePage = async (w) => {
    if (!page || page.isClosed() || curVp !== w || !browser || !browser.isConnected()) {
      try { if (ctx) await ctx.close() } catch {}
      await newPage(w)
    }
  }

  const probe = async (route, label, vp) => {
    cur = { errors: [], apiFails: [] }
    let navOk = true
    try {
      await page.goto(`${BASE}/ui/#${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 })
      await page.waitForLoadState('networkidle', { timeout: 7000 }).catch(() => {})
    } catch { navOk = false }
    await sleep(1500)
    let dom = { blankIcons: 0, blankNear: [], brokenImgs: [], hOverflow: 0, spinners: 0, btnNoName: 0, imgNoAlt: 0, bodyTextLen: 0 }
    try {
      dom = await page.evaluate(() => {
        const blanks = [...document.querySelectorAll('.icon-wrap')].filter((e) => !e.innerHTML.trim())
        const brokenImgs = [...document.querySelectorAll('img')].filter((i) => i.complete && i.naturalWidth === 0).map((i) => (i.src || '').slice(-60))
        return {
          blankIcons: blanks.length,
          blankNear: blanks.slice(0, 6).map((e) => (e.closest('[class]')?.className || '').split(' ')[0]).filter(Boolean),
          brokenImgs: brokenImgs.slice(0, 5),
          hOverflow: document.documentElement.scrollWidth - window.innerWidth,
          spinners: document.querySelectorAll('.spinner,[class*="skeleton"],[class*="skel"],[class*="loading"]').length,
          btnNoName: [...document.querySelectorAll('button')].filter((b) => !b.textContent.trim() && !b.getAttribute('aria-label') && !b.getAttribute('title')).length,
          imgNoAlt: [...document.querySelectorAll('img')].filter((i) => i.getAttribute('alt') === null).length,
          bodyTextLen: (document.querySelector('main,.dashboard-content,#app')?.innerText || document.body.innerText || '').trim().length,
        }
      })
    } catch {}
    try { await page.screenshot({ path: path.join(SHOTS, `${vp === 1440 ? 'desktop' : 'mobile'}-${label}.png`), timeout: 10000 }) } catch {}
    return { route, label, viewport: vp === 1440 ? 'desktop' : 'mobile', navOk, errors: cur.errors.slice(), apiFails: cur.apiFails.slice(), ...dom }
  }

  for (const [w, list] of [[1440, ROUTES], [390, ROUTES.filter(([, l]) => MOBILE.has(l))]]) {
    const vpName = w === 1440 ? 'desktop' : 'mobile'
    for (const [route, label] of list) {
      if (done.has(`${vpName}:${label}`)) continue
      let r
      try {
        await ensurePage(w)
        r = await probe(route, label, w)
      } catch (e) {
        // Page/browser crashed mid-route — record, recreate, continue. NEVER abort the run.
        r = { route, label, viewport: vpName, navOk: false, errors: ['HARNESS: ' + String(e).slice(0, 200)], apiFails: [], blankIcons: 0, blankNear: [], brokenImgs: [], hOverflow: 0, spinners: 0, btnNoName: 0, imgNoAlt: 0, bodyTextLen: 0 }
        try { if (ctx) await ctx.close() } catch {}
        page = null
      }
      results.push(r)
      try { fs.writeFileSync(JSONP, JSON.stringify(results, null, 2)) } catch {}
      const flag = (r.errors.length ? `ERR:${r.errors.length} ` : '') + (r.blankIcons ? `BLANKICON:${r.blankIcons} ` : '') +
        (r.hOverflow > 2 ? `HOVERFLOW:${r.hOverflow} ` : '') + (r.brokenImgs?.length ? `IMG:${r.brokenImgs.length} ` : '') +
        (r.apiFails.length ? `API:${r.apiFails.length} ` : '') + (r.bodyTextLen < 40 ? 'EMPTY ' : '')
      console.log(`[${vpName}] ${label.padEnd(26)} ${r.navOk ? 'ok' : 'NAV?'} ${flag || 'clean'}`)
    }
  }
  try { if (browser) await browser.close() } catch {}

  const L = ['# Frontend Audit — 2026-07-05 (frame-c V0144) — REPORT', '']
  const desk = results.filter((r) => r.viewport === 'desktop')
  const f = (arr, p) => arr.filter(p)
  L.push('## Exec summary', '',
    `- Routes audited: **${desk.length}** desktop + ${results.length - desk.length} mobile`,
    `- Console/page errors: **${f(desk, (r) => r.errors.length).length}** routes`,
    `- Blank icons: **${f(desk, (r) => r.blankIcons > 0).length}** routes (${desk.reduce((a, r) => a + (r.blankIcons || 0), 0)} total)`,
    `- Horizontal overflow: **${f(desk, (r) => r.hOverflow > 2).length}** routes`,
    `- API 4xx/5xx: **${f(desk, (r) => r.apiFails.length).length}** routes`,
    `- Broken images: **${f(desk, (r) => r.brokenImgs?.length).length}** routes`,
    `- ~Empty/stuck: **${f(desk, (r) => r.bodyTextLen < 40).length}** routes`, '')
  const tbl = (title, rows, fmt) => { if (!rows.length) return; L.push(`## ${title}`, ''); rows.forEach((r) => L.push(`- **${r.label}** — ${fmt(r)}`)); L.push('') }
  tbl('Blank icons', f(desk, (r) => r.blankIcons > 0), (r) => `${r.blankIcons}; near: ${(r.blankNear || []).join(', ')}`)
  tbl('Console / page errors', f(desk, (r) => r.errors.length), (r) => r.errors.slice(0, 2).join(' | '))
  tbl('Horizontal overflow', f(desk, (r) => r.hOverflow > 2), (r) => `+${r.hOverflow}px`)
  tbl('API 4xx/5xx', f(desk, (r) => r.apiFails.length), (r) => r.apiFails.slice(0, 4).map((a) => `${a.status} ${a.url}`).join(', '))
  tbl('Broken images', f(desk, (r) => r.brokenImgs?.length), (r) => r.brokenImgs.join(', '))
  tbl('~Empty / stuck-loading', f(desk, (r) => r.bodyTextLen < 40), (r) => `bodyText=${r.bodyTextLen}, spinners=${r.spinners}, nav=${r.navOk}`)
  L.push('## Full per-route table', '', '| view | vp | nav | err | blankIcon | hOverflow | api4xx | brokenImg | bodyLen |', '|---|---|---|---|---|---|---|---|---|')
  results.forEach((r) => L.push(`| ${r.label} | ${r.viewport} | ${r.navOk ? 'ok' : 'FAIL'} | ${r.errors.length} | ${r.blankIcons || 0} | ${r.hOverflow > 2 ? r.hOverflow : 0} | ${r.apiFails.length} | ${r.brokenImgs?.length || 0} | ${r.bodyTextLen} |`))
  fs.writeFileSync(path.join(OUT, 'REPORT.md'), L.join('\n'))
  console.log(`\nDONE — ${results.length} probes. report.json + REPORT.md + screenshots in ${OUT}`)
}
run().catch((e) => { console.error('AUDIT OUTER ERROR:', e) })
