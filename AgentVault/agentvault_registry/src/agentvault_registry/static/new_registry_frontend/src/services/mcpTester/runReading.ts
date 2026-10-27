// §MCPTEST30 (V0535, agentvault2-b4): how the console reads a run: its live log, its wall time, its trend, what it left
// out. Each function answers a question the MCP tester view used to answer from a number that meant something else.

// ── the live log ─────────────────────────────────────────────────────────────────────────────────────────────────
// While a sweep runs, the backend writes "Sweep in flight · elapsed 1m54s" every 6 s (routers/mcp_tester.py). In round
// 10's first run 40 of the first 45 lines were that heartbeat, scrolling the steps a person reads out of sight.
// Consecutive heartbeats show as ONE line, the latest, with how many it stands for.

export interface LogLine { ts: number; msg: string }
export interface ShownLogLine extends LogLine {
  /** how many heartbeat lines this line stands for (0: an ordinary line) */
  folded: number
}

const HEARTBEAT = /^Sweep in flight · elapsed \d+m\d{2}s$/

export function isHeartbeat(msg: string): boolean {
  return HEARTBEAT.test(msg)
}

export function foldHeartbeats(lines: readonly LogLine[]): ShownLogLine[] {
  const out: ShownLogLine[] = []
  for (const l of lines) {
    const last = out[out.length - 1]
    if (isHeartbeat(l.msg)) {
      if (last && last.folded > 0) {
        last.ts = l.ts
        last.msg = l.msg
        last.folded += 1
      } else {
        out.push({ ts: l.ts, msg: l.msg, folded: 1 })
      }
    } else {
      out.push({ ts: l.ts, msg: l.msg, folded: 0 })
    }
  }
  return out
}

/** The run stream replays a run's whole log from its first line on every connect (routers/mcp_tester.py stream_run starts
 *  at index 0), and the page has already loaded those lines with their own times, so every attach printed the log
 *  twice, the copy stamped with the moment it arrived. The n-th streamed line is the run's n-th line: one the page holds
 *  is skipped, a new one is appended. Returns whether it appended. */
export function acceptStreamedLine(lines: LogLine[], streamed: number, msg: string, nowS: number): boolean {
  if (streamed < lines.length) return false
  lines.push({ ts: nowS, msg })
  return true
}

/** A sweep writes a heartbeat every 6 s while its process lives. A run whose newest line is older than `quietS` has
 *  stopped reporting (its registry restarted or its worker died) and its record reads 'running' until something says
 *  otherwise: round 10's third flow died with eu-registry's recreate at 19:57:15Z and the page still counted it as in
 *  flight half an hour later, its Run button disabled. Returns the newest line's time, or null while the run speaks. */
export function silentSince(lines: readonly LogLine[], nowS: number, quietS = 180): number | null {
  if (lines.length === 0) return null
  const last = lines[lines.length - 1].ts
  return nowS - last > quietS ? last : null
}

// ── wall time ────────────────────────────────────────────────────────────────────────────────────────────────────
// A run's own summary carries `wall_s`, and for the federation suite that number is the SUM of its tests' times:
// round 10's federation run read 8494 s and finished 14 min after it started. The clock of record is the run's own
// start and finish; the summary's figure is the fallback for a run that has no finish yet.

export interface RunTimes {
  started_at: number | null
  finished_at: number | null
  summary: { wall_s?: number } | null
}

export function runWallSeconds(run: RunTimes): number | null {
  if (typeof run.started_at === 'number' && typeof run.finished_at === 'number' && run.finished_at >= run.started_at) {
    return run.finished_at - run.started_at
  }
  const w = run.summary?.wall_s
  return typeof w === 'number' && Number.isFinite(w) ? w : null
}

export function fmtDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`
}

// ── the pass rate ────────────────────────────────────────────────────────────────────────────────────────────────
// §MCPTEST30 (V0539): a tool a standing rule forbids the tester to call carries the policy mark in its skip_reason
// (core/policy_marks.py). The admin lifecycle's guard records such a row with `healthy` set and a contract's skip_reason
// without it, and the MCP flows counted `healthy` as passed: 19 of a run's 20 such rows were passes, the 20th was not,
// the category list said SKIP of all 20, and the Policy-denied card said they count against the pass rate. Measured on
// EU's history: strict run 8a6ad7313a8f4666 recorded passed 1157 of 1184 rows = 1138 called + 19 never called, and its
// four counts summed to 1203. The flows count four disjoint classes since V0539; a run recorded before carries the
// overlap, and the page reads it out: a pass is a row that was called and held.

export interface RunCounts {
  tool_count: number
  passed: number
  skipped: number
  failed: number
  policy_denied?: number | null
  pass_pct?: number | null
}

export interface PassReading {
  total: number
  /** rows that were called and passed */
  measured: number
  /** rows a standing rule kept from being called */
  byRule: number
  skipped: number
  failed: number
  /** rows the run recorded as passes and also as not run (0 for a run whose four counts partition its rows) */
  overlap: number
  /** the pass rate the page shows */
  pct: number
  /** what the run recorded, when the page re-reads it (an overlap), else null */
  recordedPct: number | null
}

export function readPassRate(s: RunCounts): PassReading {
  const total = Math.max(0, s.tool_count || 0)
  const passed = Math.max(0, s.passed || 0)
  const skipped = Math.max(0, s.skipped || 0)
  const failed = Math.max(0, s.failed || 0)
  const byRule = Math.max(0, s.policy_denied ?? 0)
  const overlap = Math.max(0, Math.min(passed, passed + skipped + failed + byRule - total))
  const measured = passed - overlap
  const recorded = typeof s.pass_pct === 'number' && Number.isFinite(s.pass_pct) ? s.pass_pct : null
  // a suite's own figure stands (the console suite divides by the steps it measured); a run that counted rows it never
  // called is re-read over the rows its flow divides by
  const reread = total ? Math.round((measured * 10000) / total) / 100 : 0
  const pct = overlap > 0 || recorded === null ? reread : recorded
  return { total, measured, byRule, skipped, failed, overlap, pct, recordedPct: overlap > 0 ? recorded : null }
}

/** The fraction behind a pass rate, of the two the suites use: every row (the MCP and federation flows), or the rows
 *  measured (the console suite leaves its not-measured steps out). History printed "97.36% (591/634)" of a console run
 *  whose rate is 591 of the 607 steps it measured. Null when neither reproduces the rate: the page quotes it as is. */
export function passFraction(r: PassReading): { num: number; den: number; over: 'rows' | 'measured' } | null {
  const near = (den: number) => den > 0 && Math.abs(r.pct - Math.round((r.measured * 10000) / den) / 100) < 0.006
  if (near(r.total)) return { num: r.measured, den: r.total, over: 'rows' }
  const measuredRows = r.total - r.skipped - r.byRule
  if (near(measuredRows)) return { num: r.measured, den: measuredRows, over: 'measured' }
  return null
}

// ── a History row's pass rate ────────────────────────────────────────────────────────────────────────────────────
// §SUITES1018 (2026-10-19, his report on EU's History: "operators are green with 87% ... how its displayed bothers me",
// "the console suites red with 99+% is also not very accurate"). Measured there: a cloud-operator run read 87.34%
// (669/766) in green with 0 failed, 77 not measured and 20 refused by rule, and nothing on the row said why the rate was
// not 100; a console run read 99.82% in red when its one failed step was red as documented (expected_red 1,
// hard_failures 0: the flows list a row red by design apart from the new reds since §NIGHTLYTRUTH). The figure stays
// each suite's own (a row not measured still counts against an MCP-family rate); the row now draws what the figure is
// made of, says what is missing, and turns red for a failed row or a bug-find. (His word on V0627's History, the same
// day: "i dont like the 1 as documented stuff. just leave this out of the view. 1 failed as red is fine." A row red by
// design is a failed row like any other here: named "failed", drawn red, and the History row turns red.)

/** The parts of a History figure's denominator, in percent of it: the green part is the figure. */
export interface HistoryBar { pass: number; byRule: number; skip: number; fail: number }

export interface HistoryCell {
  reading: PassReading
  fraction: { num: number; den: number; over: 'rows' | 'measured' } | null
  bar: HistoryBar
  failed: number
  bugFinds: number
  /** rows the run did not measure, and rows a standing rule kept from being called */
  notMeasured: number
  byRule: number
  /** a failed row or a bug-find: the row turns red */
  bad: boolean
}

export function historyCell(s: RunCounts & { bug_finds?: number | null }): HistoryCell {
  const reading = readPassRate(s)
  const fraction = passFraction(reading)
  const bugFinds = typeof s.bug_finds === 'number' && Number.isFinite(s.bug_finds) ? Math.max(0, s.bug_finds) : 0
  // the bar divides what the figure divides: every row, or (the console suite) the steps it measured
  const parts = fraction?.over === 'measured'
    ? { pass: reading.measured, byRule: 0, skip: 0, fail: reading.failed }
    : { pass: reading.measured, byRule: reading.byRule, skip: reading.skipped, fail: reading.failed }
  const den = parts.pass + parts.byRule + parts.skip + parts.fail
  const pct = (v: number) => (den > 0 ? Math.round((v / den) * 1000) / 10 : 0)
  return {
    reading,
    fraction,
    bar: { pass: pct(parts.pass), byRule: pct(parts.byRule), skip: pct(parts.skip), fail: pct(parts.fail) },
    failed: reading.failed,
    bugFinds,
    notMeasured: reading.skipped,
    byRule: reading.byRule,
    bad: reading.failed > 0 || bugFinds > 0,
  }
}

/** A result row's outcome. A row a standing rule kept from being called is `by_rule` whatever its other flags say. */
export type RowOutcome = 'pass' | 'by_rule' | 'skip' | 'fail'

export interface OutcomeRow { tool: string; healthy?: boolean | null; skipped?: boolean | null }

export function rowOutcome(row: OutcomeRow, byRule: ReadonlySet<string>): RowOutcome {
  if (byRule.has(row.tool)) return 'by_rule'
  if (row.skipped) return 'skip'
  return row.healthy ? 'pass' : 'fail'
}

export function tallyOutcomes(rows: readonly OutcomeRow[], byRule: ReadonlySet<string>): Record<RowOutcome, number> {
  const t: Record<RowOutcome, number> = { pass: 0, by_rule: 0, skip: 0, fail: 0 }
  for (const r of rows) t[rowOutcome(r, byRule)] += 1
  return t
}

// ── the trend ────────────────────────────────────────────────────────────────────────────────────────────────────
// History holds every suite's runs, and their pass rates live on different floors (round 10: MCP 97.7 %, federation
// 99.5 %, a cloud operator 87.5 %), so one line through all of them draws the suites taking turns, not a trend. The
// trend is one suite's: the suite of the run on screen.

export interface TrendRun {
  run_id: string
  started_at: number | null
  flow_name?: string
  summary: (Partial<RunCounts> & { pass_pct?: number | null; flow_name?: string; target?: string | null }) | null
}

export const DEFAULT_FLOW = 'flow_mcp_lifecycle_complete'

export function flowOf(run: TrendRun): string {
  return run.flow_name || run.summary?.flow_name || DEFAULT_FLOW
}

/** The target a run recorded (a frame's name or a registry URL), or '' when it names none. */
export function targetOf(run: TrendRun): string {
  const t = run.summary?.target
  return typeof t === 'string' ? t.trim() : ''
}

/** §SUITES1018: one suite is one flow on one target. The console suite runs its whole pass on sbx-beta and a smaller
 *  pass on sbx-alpha (2514 and 578 steps), and History's delta set each against the other (▼0.10 on the alpha pass of
 *  2026-10-19 05:41Z, against the beta pass before it). A run that names no target (recorded before the summaries
 *  carried one) still reads against any run of its flow. */
export function sameSuite(a: TrendRun, b: TrendRun): boolean {
  if (flowOf(a) !== flowOf(b)) return false
  const ta = targetOf(a)
  const tb = targetOf(b)
  return !ta || !tb || ta === tb
}

/** The pass rate a run's summary reads as on this page (V0539: `readPassRate`), or null when it carries none. */
export function trendPct(summary: TrendRun['summary']): number | null {
  if (!summary) return null
  if (typeof summary.tool_count === 'number' && typeof summary.passed === 'number') {
    return readPassRate(summary as RunCounts).pct
  }
  return typeof summary.pass_pct === 'number' && Number.isFinite(summary.pass_pct) ? summary.pass_pct : null
}

/** Up to `max` finished runs of one suite with a pass rate, oldest first. `target`, when given, keeps the runs of that
 *  target (and the runs that name none): see `sameSuite`. */
export function suiteTrend(runs: readonly TrendRun[], flow: string, max = 12, target = ''): { id: string; pct: number }[] {
  return runs
    .filter((r) => flowOf(r) === flow && (!target || !targetOf(r) || targetOf(r) === target) && trendPct(r.summary) !== null)
    .slice()
    .sort((a, b) => (a.started_at ?? 0) - (b.started_at ?? 0))
    .slice(-max)
    .map((r) => ({ id: r.run_id, pct: trendPct(r.summary) as number }))
}

/** §MCPTEST30 (V0539): the newest earlier run of the same suite that has a pass rate, or null. History coloured each
 *  pass rate by fixed floors (99.5 green, 95 amber), and the suites live on different floors (a cloud operator's sweep
 *  makes no fixtures, so it sits near 85 % with nothing failed): every operator run read red. What a row can say about
 *  itself is whether it moved from that suite's run before it. */
export function previousOfSuite(runs: readonly TrendRun[], run: TrendRun): TrendRun | null {
  const t = run.started_at ?? 0
  let best: TrendRun | null = null
  for (const r of runs) {
    // §SUITES1018: the same flow on the same target (sameSuite)
    if (r.run_id === run.run_id || !sameSuite(r, run) || (r.started_at ?? 0) >= t || trendPct(r.summary) === null) continue
    if (!best || (r.started_at ?? 0) > (best.started_at ?? 0)) best = r
  }
  return best
}

/** The change in pass rate from `previousOfSuite`, in points to two decimals, or null. */
export function suiteDelta(runs: readonly TrendRun[], run: TrendRun): { delta: number; prevId: string } | null {
  const here = trendPct(run.summary)
  const prev = previousOfSuite(runs, run)
  const there = prev ? trendPct(prev.summary) : null
  if (here === null || prev === null || there === null) return null
  return { delta: Math.round((here - there) * 100) / 100, prevId: prev.run_id }
}

/** §MCPTEST30 (V0539): what History says of a record that still reads 'running'. History holds no log lines, so the
 *  age of its start is what it can read, and no suite runs an hour (round 10's longest, the console suite, took 28 min):
 *  older than `staleS`, the run never recorded its finish. Round 10's third flow (4dceaebcae174872, started 19:47Z)
 *  ended with eu-registry's recreate and read 'running' in History all night. */
export function historyStatus(status: string, startedAt: number | null, nowS: number, staleS = 7200): string {
  if ((status === 'running' || status === 'queued') && typeof startedAt === 'number' && nowS - startedAt > staleS) {
    return 'unfinished'
  }
  return status
}

// ── what a run left out ──────────────────────────────────────────────────────────────────────────────────────────
// The "Skipped this run" list mixed three answers to "why was this not measured": a tool that ANSWERED but whose
// success path the run never reached (a coverage hole someone can close), a probe that had nothing to decide this
// run (an empty list, an open offer), and a tool left out on purpose (recursive, provisioning, moves value).

// §MCPTEST30 (V0538): a cloud-operator run put 58 of its 91 not-run rows in "other": 23 features switched off on the
// operator (its own 503 "not enabled on this registry") and 21 rows whose subject the run never made ("fixture missing").
// Each has a group of its own; what a run left out on purpose also says "takes no entity argument" (it would act).
// §MCPTEST30 (V0541): a console suite run (fes-20261001T230748Z-7785) put 26 of its 28 not-run steps in "other": 11
// operator tours locked for the run's member account, 12 views the suite never drives headless (WebGL), and switches
// said in its own words ("FLARE_LOCAL_PURCHASE_ENABLED is off on this frame"). A step the run's account cannot open is a
// kind of its own: neither a hole in the run's setup nor a decision.
// §MCPTEST30 (V0546): a call whose answer never reached the tester (no HTTP status came back: the exec lost it, or no
// server answered) said "NOT MEASURED: ..." and landed in "nothing to decide", as if the run had found an empty list; the
// federation suite's "lost in transit" rows went to "other". It is the tester's own transport: a kind of its own.
export type NotRunKind = 'unmeasured' | 'lost' | 'fixture' | 'role' | 'nothing' | 'switched_off' | 'by_design' | 'other'

export const NOT_RUN_ORDER: readonly NotRunKind[] = ['unmeasured', 'lost', 'fixture', 'role', 'nothing', 'switched_off', 'by_design', 'other']

export function notRunKind(reason: string | null | undefined): NotRunKind {
  const r = reason || ''
  if (/no HTTP status came back|lost in transit/i.test(r)) return 'lost'
  // a decision first: a tool left out on purpose also says its row is "NOT MEASURED, not a pass"
  if (/not probed|recursive|would loop|HIS word|PROVISIONING|standing order|operating rule|takes no entity argument|^Creates a new |not opened headless|never drives headless/i.test(r)) return 'by_design'
  // V0539: the console suite says "not offered on this registry: cockpit_desk_enabled is off" of a switched-off tour
  if (/flag-gated|not (currently )?enabled on this registry|disabled on this registry|not offered on this registry|is off on this (frame|registry|node)|_MODE=(shadow|off)\b/i.test(r)) return 'switched_off'
  if (/locked for a member|needs? an? (operator|admin)('s)? (account|session|view)/i.test(r)) return 'role'
  if (/fixture (missing|unavailable)|no service agent this frame can reach/i.test(r)) return 'fixture'
  if (/success path was not measured|so this row is NOT MEASURED, not a pass/i.test(r)) return 'unmeasured'
  if (/^NOT MEASURED/.test(r)) return 'nothing'
  return 'other'
}

export function groupNotRun<T extends { reason?: string | null; skip_reason?: string | null }>(
  rows: readonly T[],
): { kind: NotRunKind; rows: T[] }[] {
  const groups = new Map<NotRunKind, T[]>()
  for (const row of rows) {
    const k = notRunKind(row.reason ?? row.skip_reason)
    if (!groups.has(k)) groups.set(k, [])
    groups.get(k)!.push(row)
  }
  return NOT_RUN_ORDER.filter((k) => groups.has(k)).map((k) => ({ kind: k, rows: groups.get(k)! }))
}

// ── a run's named lists ─────────────────────────────────────────────────────────────────────────────────────────
// §MCPTEST30 (V0539): a run's lists (BUG-FIND, hard fails, not run, refused by rule) arrive as {tool, error | reason}
// from the MCP and federation flows and as "name: text" strings from a run the console suite recorded
// (fes-20261001T230748Z-7785). The page read `.tool` of a string inside the Not run list, threw, and the error boundary
// blanked the tester. Every list is read through one shape.

export interface NamedEntry { tool: string; reason: string; error: string }

export function namedEntries(list: unknown): NamedEntry[] {
  if (!Array.isArray(list)) return []
  return list.map((e): NamedEntry => {
    if (typeof e === 'string') {
      const i = e.indexOf(': ')
      const text = i > 0 ? e.slice(i + 2) : ''
      return { tool: i > 0 ? e.slice(0, i) : e, reason: text, error: text }
    }
    if (e && typeof e === 'object') {
      const o = e as Record<string, unknown>
      const str = (v: unknown) => (typeof v === 'string' ? v : v === null || v === undefined ? '' : String(v))
      return { tool: str(o.tool ?? o.name), reason: str(o.reason ?? o.skip_reason ?? o.error), error: str(o.error ?? o.reason) }
    }
    return { tool: e === null || e === undefined ? '' : String(e), reason: '', error: '' }
  })
}

// ── the sandbox panel ────────────────────────────────────────────────────────────────────────────────────────────
// A runner that does not host sandboxes refuses `sandbox_status` in its own words ("op 'sandbox_status': this
// runner's policy does not offer sandboxes ("sandboxes": true is a kit host's)"), and the panel printed them as its
// sentence. The sentence says what it means for this page; the runner's words stay as the line's tooltip.

export function sandboxRefusalSentence(why: string): { key: string; fallback: string } | null {
  if (/does not offer sandboxes/i.test(why)) {
    return {
      key: 'mcpTester.sandbox.notOffered',
      fallback: 'This frame\'s runner does not host sandboxes, so the MCP tester runs against the sandbox named as its target above.',
    }
  }
  return null
}

// ── category bars ────────────────────────────────────────────────────────────────────────────────────────────────
// One bar coloured by pass rate painted a category red when it had skips and no failures ("Bridges: 2 OK, 3 skip"),
// so not measured read as broken. The bar is three segments.

export function barSegments(pass: number, skip: number, fail: number, byRule = 0):
  { pass: number; byRule: number; skip: number; fail: number } {
  // §MCPTEST30 (V0539): a fourth segment for the rows a standing rule kept from being called (they drew as skips)
  const total = pass + skip + fail + byRule
  if (total <= 0) return { pass: 0, byRule: 0, skip: 0, fail: 0 }
  const pct = (n: number) => Math.round((n / total) * 1000) / 10
  return { pass: pct(pass), byRule: pct(byRule), skip: pct(skip), fail: pct(fail) }
}

// ── the drift detectors ──────────────────────────────────────────────────────────────────────────────────────────
// The Drift tab read each detector's 0 as clean whatever the suite ran: "every tool rejects the wrong tier" over 0 of
// 0 probes (the federation suite runs no matrix), "wrappers match their routes" for the cloud-op sweeps (they declare
// F3 and F4 off), all three for a console run (it runs none). A run recorded since V0541 names what it measured
// (`summary.detectors`); an older one is read from what it kept.

// §MCPTEST30 (V0547): a stat tile read `summary.x || 0`, so a check the loaded run never ran printed 0, a clean reading: a
// console run carries none of these keys, the federation suite counts no contracts and runs no matrix, the cloud-op
// sweeps run neither the wrapper check nor the A↔B walk, and round 14's strict run showed "Wrapper↔route drift 0" for a
// check that had not run since its schema path moved. A tile shows a count only where its own check ran; otherwise a dash.
export interface TileReading { text: string; measured: boolean }
export function tileReading(value: unknown, measured: boolean): TileReading {
  if (!measured || typeof value !== 'number' || !Number.isFinite(value)) return { text: '—', measured: false }
  return { text: String(value), measured: true }
}

/** §MCPTEST30 (V0548): the latency check measured something only where a tool had a baseline to be compared with (a new
 *  suite's first three runs compare nothing). A run recorded before V0544 names no count and keeps its old reading. */
export function latencyMeasured(baselinedTools: unknown): boolean {
  return typeof baselinedTools === 'number' && Number.isFinite(baselinedTools) ? baselinedTools > 0 : true
}

export type DetectorKey = 'wrapper_route' | 'cross_frame' | 'auth_matrix'
export const DETECTOR_KEYS: readonly DetectorKey[] = ['wrapper_route', 'cross_frame', 'auth_matrix']

export interface AxisRow { axes?: Record<string, { state?: string | null } | null | undefined> | null }

export function readDetectors(summary: Record<string, unknown> | null | undefined,
                              rows: readonly AxisRow[] | null | undefined,
                              flowName: string | null | undefined): Record<DetectorKey, boolean> {
  const none: Record<DetectorKey, boolean> = { wrapper_route: false, cross_frame: false, auth_matrix: false }
  if (!summary) return none
  const own = summary.detectors
  if (own && typeof own === 'object') {
    const o = own as Partial<Record<DetectorKey, unknown>>
    return { wrapper_route: o.wrapper_route === true, cross_frame: o.cross_frame === true, auth_matrix: o.auth_matrix === true }
  }
  // an older run: a row graded the axis of a detector that ran (an A↔B walk that did not run already read 'na'), the
  // matrix counted its probes, and only the strict sweep, the one suite whose code runs it, checked wrappers
  const graded = (axis: string) => (rows || []).some((r) => {
    const st = r?.axes?.[axis]?.state
    return st === 'pass' || st === 'fail'
  })
  const total = Number(summary.auth_matrix_total)
  return {
    wrapper_route: (flowName || DEFAULT_FLOW) === DEFAULT_FLOW && graded('wrapper_route_drift'),
    cross_frame: graded('cross_frame_parity'),
    auth_matrix: Number.isFinite(total) && total > 0,
  }
}

// ── a result tab with no run loaded ──────────────────────────────────────────────────────────────────────────────
// With no run loaded (a sweep in flight, or none run yet) each result tab printed a clean verdict over zero rows: "No
// wrapper bugs surfaced", "Nothing was left out", "All Phase F detectors clean". A tab says what it waits for unless
// the loaded run gave it something to show.

export interface LoadedRun { rows: number; bugFinds: number; hardFails: number; notRun: number; hasSummary: boolean }

export function awaitsRun(tab: string, run: LoadedRun): boolean {
  switch (tab) {
    case 'results':
    case 'probes': return run.rows === 0
    case 'bugfind': return run.rows === 0 && run.bugFinds === 0
    case 'fails': return run.rows === 0 && run.hardFails === 0
    case 'notrun': return run.rows === 0 && run.notRun === 0
    case 'phasef': return !run.hasSummary
    default: return false
  }
}

// ── a pass that was only a refusal ───────────────────────────────────────────────────────────────────────────────
// §MCPTEST30 (V0636; his question of 2026-10-19 and his word of 2026-10-24 to close the gaps): a tool whose only pass in
// a run was a refusal counts as not measured (routers/mcp_tester._apply_refusal_only): the row is a skip and says which
// kind, and the run says how many rows it moved and what the target itself counted. A run before V0636 says neither,
// and then nothing is shown.

export interface RefusalOnlyReading { n: number; targetPct: number | null }

export function readRefusalOnly(s: { refusal_only?: unknown; target_counts?: unknown } | null | undefined): RefusalOnlyReading | null {
  const n = s?.refusal_only
  if (typeof n !== 'number' || !Number.isFinite(n) || n < 1) return null
  const tc = s?.target_counts
  const pct = tc && typeof tc === 'object' && !Array.isArray(tc) ? (tc as Record<string, unknown>).pass_pct : null
  return { n: Math.floor(n), targetPct: typeof pct === 'number' && Number.isFinite(pct) ? pct : null }
}

/** A result row moved to not measured because its only pass was a refusal. */
export function isRefusalOnly(row: { refusal_only?: boolean | null }): boolean {
  return row.refusal_only === true
}
