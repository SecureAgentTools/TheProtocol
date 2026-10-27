/**
 * Everything a page says while a lifecycle drives it (§FESUITE): console errors, uncaught exceptions, failed
 * transports and every refused or failed call to our own origin. A lifecycle that "passes" while the console logs an
 * error or a call answers 500 has not passed, so the fixture fails the test on anything unexpected at its end.
 *
 * A lifecycle that provokes a refusal on purpose (a negative step) says so with allow(): the pattern, the status it
 * expects and why. An allowance that never matched is reported too: it is a claim the run did not measure.
 *
 * Nothing secret is kept: a call is recorded as method, path WITHOUT the query string, status and duration; never a
 * header, never a body.
 */
import type { ConsoleMessage, Page, Request, Response } from '@playwright/test'

export interface NetRow { method: string; path: string; status: number; ms: number | null; failure?: string; route?: string; bearer?: boolean; by?: string }
export interface MsgRow { type: string; text: string; where: string }
interface Allowance { re: RegExp; statuses: number[] | null; reason: string; hits: number }
interface ConsoleAllowance { re: RegExp; reason: string; hits: number }

/** Console lines that are the browser's or the toolchain's, never the product's. Each has its reason. */
const BENIGN_CONSOLE: Array<[RegExp, string]> = [
  [/ResizeObserver loop (completed with undelivered notifications|limit exceeded)/i, 'the browser\'s benign ResizeObserver note'],
  [/^Global error: null$/, 'utils/errorHandler.ts prints the ResizeObserver note this way (§MCFOLD)'],
  [/Download the Vue Devtools extension/i, 'devtools hint'],
  [/^Blocked script execution in 'about:srcdoc' because the document's frame is sandboxed/i,
    'axe-core injecting itself into a script-less sandboxed preview frame (the suite\'s instrument, not the page)'],
]

/** Transport failures that are not the product's: a navigation cancels its page's in-flight calls. */
const BENIGN_FAILURE = /net::ERR_ABORTED|NS_BINDING_ABORTED/
/** The host's docker churn makes Chromium drop in-flight calls; it is the environment, counted apart. */
export const ENV_FAILURE = /net::ERR_NETWORK_CHANGED|net::ERR_NETWORK_IO_SUSPENDED|net::ERR_NAME_NOT_RESOLVED|net::ERR_INTERNET_DISCONNECTED/

function short(s: string, n = 300): string {
  const one = s.replace(/\s+/g, ' ').trim()
  return one.length > n ? one.slice(0, n) + '…' : one
}

export function pathOf(url: string): string {
  try {
    const u = new URL(url)
    return u.pathname
  } catch {
    return url.split('?')[0]
  }
}

export class Capture {
  readonly consoleErrors: MsgRow[] = []
  readonly consoleWarnings: MsgRow[] = []
  readonly pageErrors: MsgRow[] = []
  readonly refused: NetRow[] = []       // our origin answered >= 400
  readonly transport: NetRow[] = []     // a call that never got an answer (not an abort)
  readonly envDrops: NetRow[] = []      // ERR_NETWORK_CHANGED and friends
  /** Calls to the PEER frame that its CORS refused (the peer does not accept this console's origin). A deployment fact
   *  of the peer, named once by the smoke's peer_accepts_this_console row, not a defect of every page that reads it. */
  readonly peerCors: NetRow[] = []
  requests = 0
  private page: Page | null = null
  private readonly started = new Map<Request, number>()
  private readonly allowances: Allowance[] = []
  private readonly consoleAllowances: ConsoleAllowance[] = []

  constructor(private readonly origins: string[], private readonly peerOrigins: string[] = []) {}

  private peer(url: string): boolean {
    try { return this.peerOrigins.includes(new URL(url).origin) } catch { return false }
  }

  /** Exactly our origins: scheme, host AND port (a peer's :8443 federation lane is not its console). */
  private ours(url: string): boolean {
    let o = ''
    try { o = new URL(url).origin } catch { return false }
    return this.origins.includes(o)
  }

  /** Which script asked for each URL (Chromium's own record of the initiator: the bundle chunk names the component). */
  private readonly initiators = new Map<string, string>()

  attach(page: Page): void {
    this.page = page
    void this.traceInitiators(page)
    page.on('console', (m: ConsoleMessage) => this.onConsole(m))
    page.on('pageerror', (e: Error) => {
      this.pageErrors.push({ type: 'pageerror', text: short(`${e.name}: ${e.message}`), where: pathOf(page.url()) })
    })
    page.on('request', (r: Request) => {
      if (this.ours(r.url())) {
        this.requests += 1
        this.started.set(r, Date.now())
      }
    })
    page.on('requestfinished', (r: Request) => { void this.onFinished(r) })
    page.on('requestfailed', (r: Request) => this.onFailed(r))
  }

  private async traceInitiators(page: Page): Promise<void> {
    try {
      const cdp = await page.context().newCDPSession(page)
      await cdp.send('Network.enable')
      cdp.on('Network.requestWillBeSent', (e: any) => {
        const url = String(e?.request?.url || '')
        if (!this.ours(url)) return
        // Walk the whole stack, async parents included, to the first frame in a chunk that is not shared plumbing
        // (axios lives in the utils chunk; index and vendor are the app shell): that chunk is the component that asked.
        const frames: any[] = []
        for (let st = e?.initiator?.stack; st; st = st.parent) frames.push(...(st.callFrames || []))
        const chunkOf = (x: any) => String(x?.url || '').split('/').pop()?.replace(/-[A-Za-z0-9_-]{8}\.js$/, '') || ''
        const plumbing = /^(utils|index|vendor|client|axios|runtime-core|runtime-dom|reactivity|pinia|vue-router)$/i
        const f = frames.find((x) => /\/assets\//.test(String(x?.url || '')) && !plumbing.test(chunkOf(x)))
          || frames.find((x) => /\/assets\//.test(String(x?.url || ''))) || frames[0]
        if (!f) return
        this.initiators.set(`${e.request.method} ${pathOf(url)}`, `${chunkOf(f)}${f.functionName ? `:${f.functionName}` : ''}`)
      })
    } catch { /* not Chromium, or the session closed: the rows simply carry no initiator */ }
  }

  /** A refusal this lifecycle provokes on purpose. statuses null = any status >= 400. */
  allow(re: RegExp, statuses: number | number[] | null, reason: string): void {
    const list = statuses === null ? null : Array.isArray(statuses) ? statuses : [statuses]
    this.allowances.push({ re, statuses: list, reason, hits: 0 })
  }

  /** A console error this lifecycle provokes on purpose (the suite's own controls), with why. */
  allowConsole(re: RegExp, reason: string): void {
    this.consoleAllowances.push({ re, reason, hits: 0 })
  }

  private onConsole(m: ConsoleMessage): void {
    const type = m.type()
    if (type !== 'error' && type !== 'warning') return
    const text = short(m.text())
    if (BENIGN_CONSOLE.some(([re]) => re.test(text))) return
    // A refused call is already recorded as a NetRow; Chromium echoes it as "Failed to load resource".
    if (/^Failed to load resource: the server responded with a status of \d+/.test(text)) return
    // A call the host dropped (docker churn): the environment's, already counted from requestfailed.
    if (ENV_FAILURE.test(text)) return
    const loc = m.location()
    // The peer's CORS refusal, in Chromium's two words for it: the policy line, and the failed load it causes.
    const cors = text.match(/^Access to (?:fetch|XMLHttpRequest) at '([^']+)' from origin '[^']+' has been blocked by CORS policy/)
    if (cors && this.peer(cors[1])) return
    if (/^Failed to load resource: net::ERR_FAILED/.test(text) && loc?.url && this.peer(loc.url)) return
    const row = { type, text, where: loc?.url ? pathOf(loc.url) : '' }
    if (type === 'error') this.consoleErrors.push(row)
    else this.consoleWarnings.push(row)
  }

  private async onFinished(r: Request): Promise<void> {
    if (!this.ours(r.url())) return
    let resp: Response | null = null
    try { resp = await r.response() } catch { return }
    if (!resp) return
    const status = resp.status()
    if (status < 400) return
    const t0 = this.started.get(r)
    // Whether the call carried a bearer at all (presence only, never the value): a 401 without one is a call the
    // page made with no session, a 401 with one is a session the server no longer accepts.
    let bearer = false
    try { bearer = /^bearer /i.test((await r.allHeaders()).authorization || '') } catch { /* unknown */ }
    const by = this.initiators.get(`${r.method()} ${pathOf(r.url())}`)
    this.refused.push({ method: r.method(), path: pathOf(r.url()), status, ms: t0 ? Date.now() - t0 : null, route: this.routeNow(), bearer, by })
  }

  private onFailed(r: Request): void {
    if (!this.ours(r.url())) return
    const failure = r.failure()?.errorText || 'unknown'
    if (BENIGN_FAILURE.test(failure)) return
    const row = { method: r.method(), path: pathOf(r.url()), status: 0, ms: null, failure }
    if (failure === 'net::ERR_FAILED' && this.peer(r.url())) { this.peerCors.push({ ...row, route: this.routeNow() }); return }
    if (ENV_FAILURE.test(failure)) this.envDrops.push(row)
    else this.transport.push(row)
  }

  /** The in-app route the page showed when a call came back (from the URL, no page round trip). */
  private routeNow(): string {
    try {
      const u = new URL(this.page?.url() || '')
      return (u.hash.replace(/^#/, '') || '/').split('?')[0]
    } catch { return '' }
  }

  private allowed(row: NetRow): boolean {
    for (const a of this.allowances) {
      if (a.re.test(`${row.method} ${row.path}`) && (a.statuses === null || a.statuses.includes(row.status))) {
        a.hits += 1
        return true
      }
    }
    return false
  }

  /** What went wrong that nobody said would. Computed once, at the end of a test. */
  /** Where the capture stands now: what came after it belongs to whatever the lifecycle did since. */
  checkpoint(): { refused: number; transport: number; pageErrors: number; consoleErrors: number } {
    return { refused: this.refused.length, transport: this.transport.length, pageErrors: this.pageErrors.length,
      consoleErrors: this.consoleErrors.length }
  }

  /** Everything unexpected since a checkpoint (allowances applied), for a per-page row in a sweep. */
  since(cp: { refused: number; transport: number; pageErrors: number; consoleErrors: number }): string[] {
    const out: string[] = []
    for (const r of this.refused.slice(cp.refused)) {
      const allowed = r.status < 500 && this.allowances.some((a) => a.re.test(`${r.method} ${r.path}`) && (a.statuses === null || a.statuses.includes(r.status)))
      if (!allowed) out.push(`${r.method} ${r.path} answered ${r.status}${r.bearer ? ' (with a bearer' : ' (no bearer'}${r.by ? `, asked by ${r.by}` : ''})`)
    }
    for (const t of this.transport.slice(cp.transport)) out.push(`${t.method} ${t.path} failed in transport (${t.failure})`)
    for (const e of this.pageErrors.slice(cp.pageErrors)) out.push(`uncaught ${e.text}`)
    for (const c of this.consoleErrors.slice(cp.consoleErrors)) {
      if (!this.consoleAllowances.some((a) => a.re.test(c.text))) out.push(`console error: ${c.text}`)
    }
    return out
  }

  /** Read-only views for the suite's own controls. */
  seenRefusal(re: RegExp, status: number): boolean {
    return this.refused.some((r) => r.status === status && re.test(`${r.method} ${r.path}`))
  }
  seenConsoleError(re: RegExp): boolean {
    return this.consoleErrors.some((c) => re.test(c.text))
  }

  verdict(): {
    unexpected: string[]
    allowedRefusals: number
    unusedAllowances: string[]
    warnings: string[]
    summary: Record<string, unknown>
  } {
    const unexpected: string[] = []
    let allowedRefusals = 0
    for (const r of this.refused) {
      if (r.status < 500 && this.allowed(r)) { allowedRefusals += 1; continue }
      unexpected.push(`${r.method} ${r.path} answered ${r.status}${r.route ? ` (on ${r.route}` : ' ('}${r.bearer ? ', with a bearer' : ', no bearer'}${r.by ? `, asked by ${r.by}` : ''})`)
    }
    for (const t of this.transport) unexpected.push(`${t.method} ${t.path} failed in transport (${t.failure})`)
    for (const e of this.pageErrors) unexpected.push(`uncaught ${e.text} on ${e.where || 'the page'}`)
    for (const c of this.consoleErrors) {
      const a = this.consoleAllowances.find((x) => x.re.test(c.text))
      if (a) { a.hits += 1; continue }
      unexpected.push(`console error: ${c.text}${c.where ? ` (${c.where})` : ''}`)
    }
    const unusedAllowances = [
      ...this.allowances.filter((a) => a.hits === 0).map((a) => `${a.re} (${a.reason})`),
      ...this.consoleAllowances.filter((a) => a.hits === 0).map((a) => `console ${a.re} (${a.reason})`),
    ]
    return {
      unexpected,
      allowedRefusals,
      unusedAllowances,
      warnings: this.consoleWarnings.slice(0, 40).map((w) => `${w.text}${w.where ? ` (${w.where})` : ''}`),
      summary: {
        requests: this.requests,
        refused: this.refused.length,
        allowed_refusals: allowedRefusals,
        transport_failures: this.transport.length,
        env_drops: this.envDrops.length,
        peer_cors_refused: this.peerCors.length,
        console_errors: this.consoleErrors.length,
        console_warnings: this.consoleWarnings.length,
        page_errors: this.pageErrors.length,
      },
    }
  }
}
