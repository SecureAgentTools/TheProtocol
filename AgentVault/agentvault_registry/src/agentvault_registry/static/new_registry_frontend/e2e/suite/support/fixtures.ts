/**
 * The suite's test object (§FESUITE). Every lifecycle gets:
 *   - steps    rows in the MCP tester's shape (support/steps.ts)
 *   - capture  the page's console, uncaught errors and refused calls; the test fails at its end on anything unexpected,
 *              and the verdict becomes the lifecycle's last row, `page-clean`
 *   - api      the registry's API, for SETUP and READ-BACK only (what a lifecycle drives, it drives through the page)
 *   - a11y     an axe-core check of the page as it stands, recorded per page
 * and its browser context serves a local build when FESUITE_DIST is set (support/target.ts). A lifecycle about the first
 * visit tags its title @first-visit and meets the banner and the tours as a person does; every other one is a returning
 * visitor.
 */
import { test as base, expect, type Page, type APIRequestContext, type BrowserContext, request as pwRequest } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { Capture } from './capture'
import { Steps, cleanError } from './steps'
import fs from 'node:fs'
import path from 'node:path'
import { BASE_URL, API_URL, PEER_URL, OUT_DIR } from './env'
import { routeLocalBuild, seedReturningVisitor } from './target'
import { seedSession } from './accounts'
import { CAPTURE_ATTACHMENT } from './names'

export interface A11yFinding { page: string; id: string; impact: string; nodes: number; help: string; targets: string[] }

/** axe rules the suite does not hold the console to yet, each with its reason. Shrinks; never grows silently. */
export const A11Y_DEFERRED: Record<string, string> = {}

/**
 * The contrast RATCHET (§FESUITE). Colour contrast is a long tail of one-off shades across ~140 pages; failing every
 * lifecycle on it until all are fixed would make the suite permanently red, and a permanently red gate is a disabled
 * one. So the known contrast debt per checked page lives in e2e/suite/a11y-baseline.json: at or under it the row is an
 * EXPECTED red (named, never a pass); over it the test fails. Every other axe rule is strict. Each run writes what it
 * observed (a11y-observed.json) for the person lowering the baseline.
 */
const RATCHETED_RULES = new Set(['color-contrast'])
let a11yBaseline: Record<string, Record<string, number>> | null = null
function baselineFor(label: string, rule: string): number {
  if (!a11yBaseline) {
    try {
      a11yBaseline = JSON.parse(fs.readFileSync(path.resolve(process.cwd(), 'e2e/suite/a11y-baseline.json'), 'utf8'))
    } catch { a11yBaseline = {} }
  }
  return a11yBaseline?.[label]?.[rule] ?? 0
}
function recordObserved(label: string, rule: string, nodes: number): void {
  const f = path.join(OUT_DIR, 'a11y-observed.json')
  let cur: Record<string, Record<string, number>> = {}
  try { cur = JSON.parse(fs.readFileSync(f, 'utf8')) } catch { /* first */ }
  cur[label] = { ...(cur[label] || {}), [rule]: nodes }
  fs.mkdirSync(OUT_DIR, { recursive: true })
  fs.writeFileSync(f, JSON.stringify(cur, null, 2))
}

/**
 * Every failing contrast node as its measured colour pair, counted (a row keeps five examples; a fix needs the pairs:
 * one rule in one stylesheet is usually dozens of nodes). OUT_DIR/a11y-contrast-pairs.json, per page label.
 */
function recordContrastPairs(label: string, nodes: Array<{ any?: Array<{ data?: unknown }>; target?: unknown[]; html?: string }>): void {
  const pairs = new Map<string, { fg: string; bg: string; ratio: number; n: number; example: string }>()
  for (const n of nodes) {
    const d = (n.any?.[0]?.data || {}) as Record<string, any>
    if (!d.fgColor || !d.bgColor) continue
    const k = `${d.fgColor} on ${d.bgColor}`
    const cur = pairs.get(k) || { fg: String(d.fgColor), bg: String(d.bgColor), ratio: Number(d.contrastRatio), n: 0, example: '' }
    cur.n += 1
    if (!cur.example) cur.example = `${String(n.target?.[0] ?? '')} :: ${String(n.html || '').replace(/\s+/g, ' ').slice(0, 80)}`
    pairs.set(k, cur)
  }
  const f = path.join(OUT_DIR, 'a11y-contrast-pairs.json')
  let cur: Record<string, unknown> = {}
  try { cur = JSON.parse(fs.readFileSync(f, 'utf8')) } catch { /* first */ }
  cur[label] = [...pairs.values()].sort((a, b) => b.n - a.n)
  fs.mkdirSync(OUT_DIR, { recursive: true })
  fs.writeFileSync(f, JSON.stringify(cur, null, 2))
}

export class Api {
  constructor(readonly ctx: APIRequestContext) {}

  async json(method: string, path: string, opts: { token?: string; body?: unknown; form?: Record<string, string>; headers?: Record<string, string> } = {}): Promise<{ status: number; body: any }> {
    const headers: Record<string, string> = { ...(opts.headers || {}) }
    if (opts.token) headers.authorization = `Bearer ${opts.token}`
    const send = () => this.ctx.fetch(path, {
      method,
      headers,
      data: opts.form ? undefined : opts.body,
      form: opts.form,
      failOnStatusCode: false,
      maxRedirects: 0,
    })
    let resp
    try {
      resp = await send()
    } catch (e) {
      // A read is retried once when the connection dropped under it (a worker recycling: "socket hang up",
      // ECONNRESET). A write never is: whether it landed is unknown, and the lifecycle must say so, not guess.
      if (method.toUpperCase() !== 'GET' || !/socket hang up|ECONNRESET/i.test(String(e))) throw e
      resp = await send()
    }
    let body: any = null
    const text = await resp.text()
    try { body = text ? JSON.parse(text) : null } catch { body = text }
    return { status: resp.status(), body }
  }

  /** FLOW 1: the developer login is form-encoded. Returns the access token or throws with the status. */
  async login(email: string, password: string): Promise<string> {
    const r = await this.json('POST', '/api/v1/auth/login', { form: { username: email, password } })
    const token = r.body?.access_token
    if (r.status !== 200 || !token) throw new Error(`login answered ${r.status} without a token`)
    return token
  }
}

type Fixtures = {
  context: BrowserContext
  /** A second person in a context of their own (same local build, same seeds), recorded by the same capture. */
  openAs: (token: string) => Promise<Page>
  steps: Steps
  capture: Capture
  api: Api
  a11y: (page: Page, label: string) => Promise<A11yFinding[]>
}

export const test = base.extend<Fixtures>({
  context: async ({ context }, use, testInfo) => {
    await routeLocalBuild(context)
    if (!/@first-visit/.test(testInfo.title)) await seedReturningVisitor(context)
    await use(context)
  },

  openAs: async ({ browser, capture }, use) => {
    const opened: BrowserContext[] = []
    await use(async (token: string) => {
      const ctx = await browser.newContext({ locale: 'en-US', timezoneId: 'UTC', serviceWorkers: 'block', viewport: { width: 1440, height: 900 } })
      opened.push(ctx)
      await routeLocalBuild(ctx)
      await seedReturningVisitor(ctx)
      await seedSession(ctx, token)
      const p = await ctx.newPage()
      capture.attach(p)
      return p
    })
    for (const c of opened) await c.close().catch(() => {})
  },

  steps: async ({}, use, testInfo) => {
    const steps = new Steps(testInfo.title, testInfo)
    await use(steps)
    await steps.flush()
  },

  capture: [async ({ page, steps }, use, testInfo) => {
    const cap = new Capture([BASE_URL, PEER_URL].filter(Boolean).map((u) => new URL(u).origin), PEER_URL ? [new URL(PEER_URL).origin] : [])
    cap.attach(page)
    await use(cap)
    const v = cap.verdict()
    await testInfo.attach(CAPTURE_ATTACHMENT, {
      body: JSON.stringify({ ...v.summary, unexpected: v.unexpected, unused_allowances: v.unusedAllowances, warnings: v.warnings }),
      contentType: 'application/json',
    })
    const clean = v.unexpected.length === 0
    steps.rows.push({
      tool: `ui:${testInfo.title}.page-clean`, tier: 'ui:developer', healthy: clean, skipped: false,
      status: clean ? 'ok' : 'fail', elapsed: 0,
      error: clean ? null : cleanError(v.unexpected.slice(0, 6).join(' | ')),
      skip_reason: null,
      response_excerpt: `${v.summary.requests} calls, ${v.summary.refused} refused (${v.allowedRefusals} expected), ${v.summary.console_errors} console errors, ${v.summary.env_drops} dropped by the host`
        + (Number(v.summary.peer_cors_refused) ? `, ${v.summary.peer_cors_refused} refused by the peer's CORS (see peer_accepts_this_console)` : ''),
      kind: clean ? null : 'bug',
    })
    if (!clean && testInfo.status === 'passed') {
      throw new Error(`the page was not clean:\n- ${v.unexpected.join('\n- ')}`)
    }
  }, { auto: true }],

  api: async ({}, use) => {
    const ctx = await pwRequest.newContext({ baseURL: API_URL })
    await use(new Api(ctx))
    await ctx.dispose()
  },

  a11y: async ({ steps }, use, testInfo) => {
    // Each check is its own row and never stops the lifecycle; the test fails at its end if any check found a
    // serious or critical violation, so an accessibility defect is never a quiet pass.
    const failures: string[] = []
    const a11yLog: A11yFinding[] = []
    await use(async (page: Page, label: string) => {
      // axe injects itself into every frame and waits for each to answer; a sandboxed preview frame (srcdoc, no
      // allow-scripts: the admin's mail preview) refuses the injection and the wait never ends (measured 2026-10-01: one
      // page held the sweep 20 minutes). A time limit, then once more without frames, then NOT MEASURED, never a pass.
      // An open modal dialog is the page a person can perceive and use; the page behind its scrim is dimmed on purpose
      // (scored as "contrast" it fails everywhere, worker A measured 14 nodes on My Agents behind the quick-create sheet).
      // With one open, the check covers the dialog; a dialog without aria-modal leaves the whole page in scope.
      const modal = await page.locator('[role="dialog"][aria-modal="true"]:visible').count().catch(() => 0)
      const run = (frames: boolean) => {
        const b = new AxeBuilder({ page })
          .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
          .disableRules(Object.keys(A11Y_DEFERRED))
        if (modal > 0) b.include('[role="dialog"][aria-modal="true"]')
        if (!frames) b.options({ iframes: false }).exclude('iframe')
        return Promise.race([
          b.analyze(),
          new Promise<null>((resolve) => setTimeout(() => resolve(null), 45_000)),
        ])
      }
      // A colour mid-transition is not the colour a person reads (axe measured a button halfway from red to green right
      // after a choice): let finite transitions and animations finish first, at most 2 s.
      // two frames first: a dialog that has just been mounted starts its transition on the next frame
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))).catch(() => {})
      await page.evaluate(() => Promise.race([
        Promise.all(document.getAnimations()
          .filter((a) => { const t = a.effect?.getComputedTiming?.(); return !!t && t.endTime !== Infinity })
          .map((a) => a.finished.catch(() => null))),
        new Promise((r) => setTimeout(r, 2000)),
      ])).catch(() => { /* the page navigated: axe reports on what is there */ })
      let res = await run(true)
      let framesSkipped = false
      if (!res) { res = await run(false); framesSkipped = true }
      if (!res) {
        steps.notMeasured(`a11y-${label}`, 'ui:public', 'axe did not finish in 45 s, with or without the page\'s frames')
        return []
      }
      const all = res.violations
        .filter((v) => v.impact === 'serious' || v.impact === 'critical')
        .map((v) => ({
          page: label, id: v.id, impact: v.impact || '', nodes: v.nodes.length, help: v.help,
          // where (first five elements) and, for contrast, the measured pair: what a fix needs to know
          targets: v.nodes.slice(0, 5).map((n) => {
            const d = (n.any?.[0]?.data || {}) as Record<string, unknown>
            const c = d.contrastRatio ? ` ${d.fgColor} on ${d.bgColor} = ${d.contrastRatio} (needs ${d.expectedContrastRatio})` : ''
            const html = String(n.html || '').replace(/\s+/g, ' ').slice(0, 90)
            return `${String(n.target?.[0] ?? '')}${c} :: ${html}`.slice(0, 260)
          }),
        }))
      for (const f of all) if (RATCHETED_RULES.has(f.id)) recordObserved(label, f.id, f.nodes)
      const contrast = res.violations.find((v) => v.id === 'color-contrast')
      if (contrast) recordContrastPairs(label, contrast.nodes as any)
      const known = all.filter((f) => RATCHETED_RULES.has(f.id) && f.nodes <= baselineFor(label, f.id))
      const findings = all.filter((f) => !known.includes(f))
      const detail = findings.map((f) => {
        const base = RATCHETED_RULES.has(f.id) ? ` (baseline ${baselineFor(label, f.id)})` : ''
        return `${f.id} (${f.impact}, ${f.nodes} node(s))${base}: ${f.help}`
      }).join(' | ')
      steps.rows.push({
        tool: `ui:${testInfo.title}.a11y-${label}`, tier: 'ui:public', healthy: all.length === 0, skipped: false,
        status: findings.length ? 'fail' : known.length ? 'known' : 'ok', elapsed: 0,
        error: findings.length ? detail.slice(0, 400)
          : known.length ? known.map((f) => `${f.id}: ${f.nodes} node(s), within the ratchet's baseline`).join(' | ') : null,
        skip_reason: null,
        response_excerpt: `${res.passes.length} rules passed, ${res.violations.length} violated (${findings.length} serious or critical)${framesSkipped ? '; frames not checked (axe stalled on one)' : ''}`,
        kind: findings.length ? 'bug' : known.length ? 'expected' : null,
      })
      if (findings.length) failures.push(`${label}: ${detail}`)
      a11yLog.push(...all)
      return findings
    })
    if (a11yLog.length) {
      await testInfo.attach('fesuite-a11y', { body: JSON.stringify(a11yLog), contentType: 'application/json' })
    }
    if (failures.length && testInfo.status === 'passed') {
      throw new Error(`accessibility: serious or critical violations\n- ${failures.join('\n- ')}`)
    }
  },
})

export { expect }
