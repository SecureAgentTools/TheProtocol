/**
 * fe_interact.mjs — NON-DESTRUCTIVE modal/interaction audit (Playwright/Chromium).
 * For each route: clicks safe triggers (buttons/tabs) one at a time, detects whether a modal/drawer
 * opens, whether the click throws a JS exception, whether the modal renders content, and whether it
 * closes cleanly. Records everything; screenshots each opened modal.
 *
 * SAFETY (prod): every non-GET request to /api is ABORTED at the network layer, so no click can
 * mutate server state — writes never leave the browser. Additionally skips session-killing / clearly
 * destructive triggers by label, and never types into or submits forms. Modals are closed via Escape.
 *
 * Bulletproof: per-trigger try/catch; page recreated on crash; incremental writes + resume.
 * Usage: BASE=... TOKEN=... USERJSON='{...}' [ONLY=comma,routes] node fe_interact.mjs
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'

const BASE = process.env.BASE || 'http://localhost:8101'
const OUT = process.env.OUT || '/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05'
const TOKEN = process.env.TOKEN || ''
const USERJSON = process.env.USERJSON || '{}'
const ONLY = (process.env.ONLY || '').split(',').filter(Boolean)
const CAP = parseInt(process.env.CAP || '14', 10)   // max triggers clicked per route
const SHOTS = path.join(OUT, 'modals')
const JSONP = path.join(OUT, 'interact.json')
fs.mkdirSync(SHOTS, { recursive: true })

// Interaction-rich routes (modals/drawers/tabs live here). Public marketing pages omitted.
let ROUTES = [
  ['/mission-control', 'mission-control'], ['/my-agents', 'my-agents'], ['/agent-forge', 'agent-forge'],
  ['/agent-builder', 'agent-builder'], ['/settings', 'settings'], ['/api-keys', 'api-keys'],
  ['/contracts', 'contracts'], ['/disputes', 'disputes'], ['/settlements', 'settlements'],
  ['/staking', 'staking'], ['/governance', 'governance'], ['/senate', 'senate'],
  ['/exchange', 'exchange'], ['/forex', 'forex'], ['/trading', 'trading'],
  ['/flare-manager', 'flare-manager'], ['/bundles', 'bundles'], ['/organization', 'organization'],
  ['/federation', 'federation'], ['/federation-discover', 'federation-discover'],
  ['/discovery', 'discovery'], ['/eigentrust-command', 'eigentrust-command'],
  ['/galactic-command', 'galactic-command'], ['/ci-cd', 'ci-cd'], ['/webhooks', 'webhooks'],
  ['/health-monitor', 'health-monitor'], ['/onboarding', 'onboarding'], ['/support', 'support'],
  ['/admin/agents', 'admin-agents'], ['/admin/developers', 'admin-developers'],
  ['/admin/registry-card', 'admin-registry-card'], ['/admin/reactors', 'admin-reactors'],
  ['/admin/evals', 'admin-evals'], ['/admin/forensics', 'admin-forensics'],
  ['/admin/canaries', 'admin-canaries'], ['/admin/ironhand', 'admin-ironhand'],
  ['/admin/exchange', 'admin-exchange'], ['/admin/treasury', 'admin-treasury'],
  ['/admin/events', 'admin-events'], ['/admin/broadcasts', 'admin-broadcasts'],
  ['/admin/email', 'admin-email'], ['/admin/fiat-ops', 'admin-fiat-ops'],
  ['/admin/fiat-pricing', 'admin-fiat-pricing'], ['/admin/bridge', 'admin-bridge'],
  ['/admin/fx', 'admin-fx'], ['/admin/peers', 'admin-peers'], ['/admin/settlements', 'admin-settlements'],
  ['/admin/marketplace', 'admin-marketplace'], ['/admin/attestations', 'admin-attestations'],
]
if (ONLY.length) ROUTES = ROUTES.filter(([, l]) => ONLY.includes(l))

// Server safety is GUARANTEED by the network write-blocker (every non-GET /api is aborted), so a
// destructive button just opens a confirm-modal whose execution never reaches the server — which is
// exactly what we want to exercise. So SKIP is MINIMAL: only session-killers (would log us out) and
// the clipboard button (navigator.clipboard hangs the click in headless). Everything else is clicked;
// modals are closed via Escape/Cancel/backdrop and forms are never submitted.
const SKIP = /log\s*out|sign\s*out|logout|signout|switch account|impersonat|copy to clipboard|copy link/i
// WebSocket/403/network errors are audit-env artifacts (headless can't auth the WS; we abort writes) — not FE bugs.
const BENIGN = [/favicon/i, /readyState/i, /H\.264/i, /manifest\.json/i, /ResizeObserver/i, /WebSocket/i, /ws\/events/i, /cesium/i, /aborted/i, /ERR_ABORTED/i, /Failed to fetch/i, /NetworkError/i, /net::ERR/i, /Load failed/i, /\b403\b/i, /\b401\b/i, /Forbidden/i, /Unauthorized/i, /(png|jpg|svg|woff).*(404|Failed)/i]
const isBenign = (s) => BENIGN.some((r) => r.test(s || ''))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const TRIG = '#main-content button:visible,#main-content [role="button"]:visible,#main-content [role="tab"]:visible,#main-content a[href="#"]:visible'
const MODAL_SEL = '.tp-modal,.tp-overlay,.ca-modal,.ca-overlay,.cmdk-modal,.cmdk-overlay,.aa-modal,.opm-modal,.dd-drawer,.md-drawer,.ts-pad-overlay-1,[role="dialog"],[class*="-drawer"]:not(nav):not(aside),[class*="-modal"]:not([class*="-modal-"])'

let cur = { errors: [], blockedWrites: [] }

const run = async () => {
  const results = fs.existsSync(JSONP) ? JSON.parse(fs.readFileSync(JSONP, 'utf8')) : []
  const done = new Set(results.map((r) => r.label))
  let browser = null, ctx = null, page = null

  const launch = async () => { browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] }) }
  const newPage = async () => {
    if (!browser || !browser.isConnected()) await launch()
    ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
    await ctx.addInitScript(([uj, tok]) => { try { sessionStorage.setItem('sovereign_auth_token', tok); sessionStorage.setItem('sovereign_user', uj); localStorage.setItem('sovereign_user', uj) } catch {} }, [USERJSON, TOKEN])
    // SERVER SAFETY: abort every non-GET /api call — no click can mutate prod state.
    await ctx.route('**/api/**', (route) => {
      const m = route.request().method()
      if (m === 'GET' || m === 'HEAD' || m === 'OPTIONS') return route.continue()
      cur.blockedWrites.push(`${m} ${route.request().url().replace(/\?.*/, '').replace(BASE, '')}`)
      return route.abort()
    })
    page = await ctx.newPage()
    page.on('pageerror', (e) => { if (!isBenign(String(e))) cur.errors.push('JS: ' + String(e).slice(0, 200)) })
    page.on('console', (m) => { if (m.type() === 'error' && !isBenign(m.text())) cur.errors.push(m.text().slice(0, 200)) })
  }
  const ensurePage = async () => { if (!page || page.isClosed() || !browser || !browser.isConnected()) { try { if (ctx) await ctx.close() } catch {} await newPage() } }
  const modalVisible = async () => {
    try {
      return await page.evaluate((sel) => [...document.querySelectorAll(sel)].some((e) => {
        const r = e.getBoundingClientRect(), s = getComputedStyle(e)
        return r.width > 40 && r.height > 40 && s.display !== 'none' && s.visibility !== 'hidden' && parseFloat(s.opacity || '1') > 0.1
      }), MODAL_SEL)
    } catch { return false }
  }
  const modalText = async () => { try { return await page.evaluate((sel) => { const e = [...document.querySelectorAll(sel)].find((x) => x.getBoundingClientRect().width > 40); return e ? (e.innerText || '').trim().length : 0 }, MODAL_SEL) } catch { return 0 } }
  const closeModal = async () => {
    for (let k = 0; k < 4; k++) {
      await page.keyboard.press('Escape').catch(() => {}); await sleep(220)
      if (!(await modalVisible())) return true
      const cancel = page.locator(MODAL_SEL).locator('button,[role="button"]').filter({ hasText: /cancel|dismiss|not now|no thanks|\bback\b|\bdone\b|\bclose\b|keep editing|keep draft|\bstay\b|never ?mind|don'?t leave|\bgot it\b|\bok\b/i }).first()
      if (await cancel.count().catch(() => 0)) { await cancel.click({ timeout: 1500 }).catch(() => {}); await sleep(220); if (!(await modalVisible())) return true }
      const x = page.locator('.tp-modal-close,[aria-label="Close"],.ca-close,.cmdk-close').first()
      if (await x.count().catch(() => 0)) { await x.click({ timeout: 1500 }).catch(() => {}); await sleep(220); if (!(await modalVisible())) return true }
      const ov = page.locator('.tp-overlay,.ca-overlay,.cmdk-overlay,[class*="-overlay"]').first()
      if (await ov.count().catch(() => 0)) { await ov.click({ position: { x: 6, y: 6 }, timeout: 1500 }).catch(() => {}); await sleep(220); if (!(await modalVisible())) return true }
    }
    return !(await modalVisible())
  }

  for (const [route, label] of ROUTES) {
    if (done.has(label)) continue
    const rec = { label, route, triggersTried: 0, modalsOpened: 0, jsErrors: [], openFailures: [], closeFailures: [], notClicked: [], blockedWrites: 0, navOk: true }
    try {
      await ensurePage()
      cur = { errors: [], blockedWrites: [] }
      try { await page.goto(`${BASE}/ui/#${route}`, { waitUntil: 'domcontentloaded', timeout: 20000 }); await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {}) } catch { rec.navOk = false }
      await sleep(1500)
      const N = Math.min(CAP, await page.locator(TRIG).count().catch(() => 0))
      for (let i = 0; i < N; i++) {
        const btns = page.locator(TRIG)
        if (await btns.count().catch(() => 0) <= i) break
        const el = btns.nth(i)
        let lbl = ''
        try { lbl = ((await el.innerText({ timeout: 800 }).catch(() => '')) || (await el.getAttribute('aria-label').catch(() => '')) || (await el.getAttribute('title').catch(() => '')) || '').trim().replace(/\s+/g, ' ').slice(0, 40) } catch {}
        if (!lbl) lbl = `#${i}`
        if (SKIP.test(lbl)) continue
        cur.errors = []; const errBefore = 0
        const urlBefore = page.url()
        rec.triggersTried++
        try { await el.click({ timeout: 2500 }) } catch (e) { rec.notClicked.push(lbl); continue }
        await sleep(650)
        // navigated away? go back and continue.
        if (page.url() !== urlBefore && !page.url().includes(`#${route}`)) { try { await page.goto(`${BASE}/ui/#${route}`, { waitUntil: 'domcontentloaded', timeout: 15000 }); await sleep(1000) } catch {} }
        const opened = await modalVisible()
        if (cur.errors.length > errBefore) rec.jsErrors.push(`${lbl}: ${cur.errors.slice(-2).join(' | ')}`)
        if (opened) {
          rec.modalsOpened++
          const contentLen = await modalText()
          if (contentLen < 3) rec.openFailures.push(`${lbl}: modal-empty`)
          try { await page.screenshot({ path: path.join(SHOTS, `${label}__${lbl.replace(/[^a-z0-9]+/gi, '-').slice(0, 24) || i}.png`), timeout: 8000 }) } catch {}
          const closed = await closeModal()
          if (!closed) { rec.closeFailures.push(lbl); try { if (ctx) await ctx.close() } catch {}; page = null; await ensurePage(); try { await page.goto(`${BASE}/ui/#${route}`, { waitUntil: 'domcontentloaded', timeout: 15000 }); await sleep(1000) } catch {} }
        }
      }
      rec.blockedWrites = cur.blockedWrites.length
    } catch (e) {
      rec.navOk = false; rec.jsErrors.push('HARNESS: ' + String(e).slice(0, 150))
      try { if (ctx) await ctx.close() } catch {}; page = null
    }
    results.push(rec)
    try { fs.writeFileSync(JSONP, JSON.stringify(results, null, 2)) } catch {}
    const flag = (rec.jsErrors.length ? `JSERR:${rec.jsErrors.length} ` : '') + (rec.openFailures.length ? `OPENFAIL:${rec.openFailures.length} ` : '') + (rec.closeFailures.length ? `CLOSEFAIL:${rec.closeFailures.length} ` : '')
    console.log(`${label.padEnd(24)} triggers=${rec.triggersTried} modals=${rec.modalsOpened} blockedWrites=${rec.blockedWrites} ${flag || 'clean'}`)
  }
  try { if (browser) await browser.close() } catch {}

  // REPORT
  const L = ['# FE Interaction / Modal Audit — 2026-07-05 (frame-c V0144) — non-destructive', '',
    '> Every non-GET /api request was aborted at the network layer — no click mutated server state.',
    '> Clicks that TRIED to write are counted as `blockedWrites` (informational). Modals closed via Escape.', '',
    '## Exec summary', '',
    `- Routes exercised: **${results.length}**`,
    `- Total triggers clicked: **${results.reduce((a, r) => a + r.triggersTried, 0)}**`,
    `- Total modals opened OK: **${results.reduce((a, r) => a + r.modalsOpened, 0)}**`,
    `- Routes with JS errors on interaction: **${results.filter((r) => r.jsErrors.length).length}**`,
    `- Routes with modal open-failures (empty/didn't open): **${results.filter((r) => r.openFailures.length).length}**`,
    `- Routes with modal close-failures: **${results.filter((r) => r.closeFailures.length).length}**`, '']
  const sec = (title, rows, fmt) => { const hit = rows.filter(fmt.pred); if (!hit.length) return; L.push(`## ${title}`, ''); hit.forEach((r) => L.push(`- **${r.label}** — ${fmt.line(r)}`)); L.push('') }
  sec('JS errors triggered by clicks (REAL bugs)', results, { pred: (r) => r.jsErrors.length, line: (r) => r.jsErrors.join(' ;; ') })
  sec('Modal open failures (opened empty / broke)', results, { pred: (r) => r.openFailures.length, line: (r) => r.openFailures.join(', ') })
  sec('Modal close failures (stuck open)', results, { pred: (r) => r.closeFailures.length, line: (r) => r.closeFailures.join(', ') })
  L.push('## Per-route table', '', '| route | triggers | modals | jsErr | openFail | closeFail | blockedWrites |', '|---|---|---|---|---|---|---|')
  results.forEach((r) => L.push(`| ${r.label} | ${r.triggersTried} | ${r.modalsOpened} | ${r.jsErrors.length} | ${r.openFailures.length} | ${r.closeFailures.length} | ${r.blockedWrites} |`))
  fs.writeFileSync(path.join(OUT, 'INTERACT_REPORT.md'), L.join('\n'))
  console.log(`\nDONE — ${results.length} routes. interact.json + INTERACT_REPORT.md + modals/ in ${OUT}`)
}
run().catch((e) => { console.error('INTERACT OUTER ERROR:', e) })
