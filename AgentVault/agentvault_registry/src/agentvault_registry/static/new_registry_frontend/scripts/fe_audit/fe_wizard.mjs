/**
 * fe_wizard.mjs — deep end-to-end drive of the AgentForge create-agent wizard, WITH improvement notes.
 * Creates a REAL throwaway agent on frame-c (writes are NOT blocked here — that's the point), captures
 * per-step timing/console-errors/screenshots + the once-shown credentials, and records UX-improvement
 * observations (validation feedback, gating, secret handling, etc). Prints the created agent_did so the
 * caller can delete it. Bulletproof: every step in try/catch.
 *
 * Usage: BASE=... TOKEN=... USERJSON='{...}' node fe_wizard.mjs
 */
import { chromium } from 'playwright'
import fs from 'fs'
import path from 'path'

const BASE = process.env.BASE || 'http://localhost:8101'
const OUT = process.env.OUT || '/opt/theprotocol/stack/Agentvault2/sessionlogs2026/fe_audit_2026-07-05'
const TOKEN = process.env.TOKEN || ''
const USERJSON = process.env.USERJSON || '{}'
const SHOTS = path.join(OUT, 'wizard')
fs.mkdirSync(SHOTS, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const BENIGN = [/favicon/i, /readyState/i, /H\.264/i, /manifest/i, /ResizeObserver/i, /WebSocket/i, /ws\/events/i, /cesium/i, /\b403\b/i, /Forbidden/i, /(png|jpg|svg|woff)/i]
const isBenign = (s) => BENIGN.some((r) => r.test(s || ''))

const errors = []
const obs = []          // improvement observations
const timeline = []     // {step, ms}
const OBS = (sev, msg) => obs.push(`[${sev}] ${msg}`)

const run = async () => {
  const NAME = 'AuditForge ' + Date.now().toString().slice(-8)   // unique so we can find + delete it
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  await ctx.addInitScript(([uj, tok]) => { try { sessionStorage.setItem('sovereign_auth_token', tok); sessionStorage.setItem('sovereign_user', uj); localStorage.setItem('sovereign_user', uj); localStorage.removeItem('agentforge_draft_v1') } catch {} }, [USERJSON, TOKEN])
  const page = await ctx.newPage()
  page.on('pageerror', (e) => { if (!isBenign(String(e))) errors.push('JS: ' + String(e).slice(0, 200)) })
  page.on('console', (m) => { if (m.type() === 'error' && !isBenign(m.text())) errors.push(m.text().slice(0, 200)) })
  const created = { agent_did: null, client_id: null, secretShown: false }
  const shot = async (n) => { try { await page.screenshot({ path: path.join(SHOTS, `${n}.png`) }) } catch {} }
  const nextEnabled = async () => { try { return await page.locator('[data-tour="forge-next"]').isEnabled({ timeout: 1000 }) } catch { return null } }
  const t0 = Date.now(); let tPrev = t0
  const mark = (s) => { const now = Date.now(); timeline.push({ step: s, ms: now - tPrev }); tPrev = now }

  try {
    // ── Step 0: Welcome ──
    await page.goto(`${BASE}/ui/#/agent-forge`, { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {})
    await sleep(1500)
    const heroOk = await page.locator('[data-tour="forge-hero"]').count().catch(() => 0)
    if (!heroOk) OBS('WARN', 'forge-hero not found — wizard may not have loaded')
    await shot('01-welcome')
    await page.locator('[data-tour="forge-next"]').click({ timeout: 5000 })
    await sleep(700); mark('welcome→template')

    // ── Step 1: Template + Identity ──
    // Improvement probe: is Next gated before anything is filled?
    const gatedAtStart = (await nextEnabled()) === false
    if (!gatedAtStart) OBS('UX', 'Template/Identity step: Next was NOT disabled before selecting a template + filling required fields — validation gate weak')
    // Probe: is the identity form gated/dimmed until a template is picked?
    const nameBeforeTpl = await page.locator('.afg-input').first().isEditable({ timeout: 1000 }).catch(() => null)
    await page.locator('.afg-template-card').first().click({ timeout: 5000 })
    await sleep(500)
    const selected = await page.locator('.afg-template-card--selected').count().catch(() => 0)
    if (!selected) OBS('BUG', 'Clicking a template card did not apply the --selected class')
    // Sample autofill
    const sampleBtn = page.locator('.afg-divider-action').first()
    if (await sampleBtn.count().catch(() => 0)) { await sampleBtn.click({ timeout: 3000 }).catch(() => {}); await sleep(500) }
    else OBS('UX', 'Sample-data quick-fill button not found after picking a template')
    // Probe validation: type a too-short name, expect Next still disabled + an error/no-valid state
    const nameInput = page.locator('.afg-input').first()
    await nameInput.fill('ab', { timeout: 3000 }).catch(() => {})
    await sleep(400)
    const shortOk = (await nextEnabled()) === false
    if (!shortOk) OBS('UX', 'A 2-char agent name did NOT keep Next disabled (min length not enforced in UI)')
    // Now the real unique name
    await nameInput.fill(NAME, { timeout: 3000 }).catch(() => {})
    await sleep(600)
    const nameValidMark = await page.locator('.afg-input--valid').count().catch(() => 0)
    if (!nameValidMark) OBS('POLISH', 'No visible valid-state (checkmark/green) on the name field after entering a valid name')
    const hriVal = await page.locator('.afg-input').nth(1).inputValue().catch(() => '')
    if (!hriVal) OBS('BUG', 'HRI did not auto-fill from the agent name')
    // description present from sample?
    const descVal = await page.locator('.afg-textarea').first().inputValue().catch(() => '')
    if ((descVal || '').trim().length < 10) { await page.locator('.afg-textarea').first().fill('Throwaway agent created by the FE wizard end-to-end audit. Safe to delete.', { timeout: 3000 }).catch(() => {}); await sleep(300) }
    await shot('02-template-identity')
    if ((await nextEnabled()) !== true) { OBS('BUG', 'Next stayed disabled even after template + valid name + HRI + description — cannot proceed'); throw new Error('gate-stuck-step1') }
    await page.locator('[data-tour="forge-next"]').click({ timeout: 5000 })
    await sleep(700); mark('template→capabilities')

    // ── Step 2: Capabilities + Auth ──
    // Probe URL validation: put a malformed URL in the first url field, expect an inline error.
    const urlInputs = page.locator('.afg-input')
    const uc = await urlInputs.count().catch(() => 0)
    if (uc > 0) {
      await urlInputs.first().fill('not-a-url', { timeout: 2500 }).catch(() => {})
      await sleep(500)
      const urlErr = await page.locator('.afg-input--error').count().catch(() => 0)
      if (!urlErr) OBS('UX', 'Capabilities step: a malformed URL did not surface an inline error (validate-on-input weak)')
      await urlInputs.first().fill('', { timeout: 2500 }).catch(() => {})   // clear so it doesn't block (fields optional)
      await sleep(300)
    }
    await shot('03-capabilities')
    if ((await nextEnabled()) !== true) OBS('UX', 'Capabilities step: Next disabled even though all fields are optional/empty')
    await page.locator('[data-tour="forge-next"]').click({ timeout: 5000 }).catch(() => {})
    await sleep(800); mark('capabilities→deploy')

    // ── Step 3: Deploy ──
    await shot('04-deploy-before')
    // deploy button should enable once the bootstrap token is fetched (auto on step entry)
    let deployReady = false
    for (let k = 0; k < 20; k++) { if (await page.locator('.afg-deploy-btn').isEnabled({ timeout: 800 }).catch(() => false)) { deployReady = true; break } await sleep(500) }
    if (!deployReady) OBS('BUG', 'Deploy button never enabled (bootstrap token fetch may have failed / no loading feedback)')
    const tDeploy = Date.now()
    await page.locator('.afg-deploy-btn').click({ timeout: 5000 }).catch(() => {})
    // wait for credentials to appear
    let ok = false
    for (let k = 0; k < 40; k++) {
      const cid = await page.locator('.afg-cred-value').first().innerText().catch(() => '')
      if (cid && cid.trim().length > 3) { ok = true; break }
      await sleep(500)
    }
    timeline.push({ step: 'deploy(create_agent)', ms: Date.now() - tDeploy })
    if (!ok) { OBS('BUG', 'Deploy did not surface client credentials within 20s (create_agent may have failed)'); await shot('05-deploy-failed') }
    else {
      created.client_id = (await page.locator('.afg-cred-value').first().innerText().catch(() => '')).trim()
      created.agent_did = await page.evaluate(() => { const t = document.body.innerText; const m = t.match(/did:(theprotocol|cos):[a-z0-9-]+/i); return m ? m[0] : null }).catch(() => null)
      // secret masked by default?
      const masked = await page.locator('.afg-cred-row--secret').innerText().catch(() => '')
      if (!/•|\*/.test(masked)) OBS('SECURITY', 'client_secret appears NOT masked by default on the success screen (should be reveal-on-click)')
      else created.secretShown = true
      // copy buttons present?
      const copies = await page.locator('.afg-cred-copy').count().catch(() => 0)
      if (copies < 2) OBS('UX', 'Missing copy-to-clipboard buttons for client_id/client_secret on the success screen')
      // shown-once warning present?
      const warnOnce = await page.evaluate(() => /once|save (these|them)|won'?t be shown|cannot be recovered|copy (it|them) now/i.test(document.body.innerText)).catch(() => false)
      if (!warnOnce) OBS('SECURITY', 'No visible "credentials are shown only once — save them now" warning on the success screen')
      // download bundle CTA?
      const dl = await page.locator('button:has-text("Download"), button:has-text("bundle"), .afg-download').count().catch(() => 0)
      if (!dl) OBS('UX', 'No "Download bundle" CTA on the success screen')
      await shot('05-deploy-success')
      // acknowledge secret (reveal) to unlock the final step
      const reveal = page.locator('[class*="reveal"], [class*="secret"] button, .afg-cred-row--secret button, button:has-text("reveal"), button:has-text("show")').first()
      if (await reveal.count().catch(() => 0)) { await reveal.click({ timeout: 2500 }).catch(() => {}); await sleep(400) }
    }
    mark('deploy')

    // ── Step 4: Complete ──
    const canFinish = (await nextEnabled())
    if (ok && canFinish === false) OBS('UX', 'Final "Next/Finish" stays disabled after deploy — the secret-acknowledgement gate may be unclear to users')
    await page.locator('[data-tour="forge-next"]').click({ timeout: 4000 }).catch(() => {})
    await sleep(1000)
    await shot('06-complete')
  } catch (e) { errors.push('FLOW: ' + String(e).slice(0, 200)); await shot('99-error') }

  await browser.close().catch(() => {})

  const report = {
    createdAgent: created, agentName: NAME, totalMs: Date.now() - t0, timeline,
    consoleErrors: errors.filter((e) => !isBenign(e)), observations: obs,
  }
  fs.writeFileSync(path.join(OUT, 'wizard.json'), JSON.stringify(report, null, 2))
  console.log('CREATED_DID=' + (created.agent_did || 'NONE'))
  console.log('CREATED_CLIENT_ID=' + (created.client_id || 'NONE'))
  console.log('TOTAL_MS=' + report.totalMs)
  console.log('--- timeline ---'); timeline.forEach((t) => console.log(`  ${t.step}: ${t.ms}ms`))
  console.log('--- console errors (' + report.consoleErrors.length + ') ---'); report.consoleErrors.forEach((e) => console.log('  ' + e))
  console.log('--- improvement observations (' + obs.length + ') ---'); obs.forEach((o) => console.log('  ' + o))
  console.log('WIZARD_DONE')
}
run().catch((e) => { console.error('WIZARD OUTER ERROR:', e); process.exit(0) })
