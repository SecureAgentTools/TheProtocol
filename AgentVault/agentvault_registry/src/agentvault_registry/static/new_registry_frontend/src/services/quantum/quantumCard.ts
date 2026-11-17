/**
 * V0660 (e): the quantum card's brain (pure, unit-tested).
 *
 * The registry states the facts (V0660 (a): the quantum workload extension on an agent card, read through
 * GET /api/v1/quantum/agents/{did} and the discover list's `quantum` facets; V0660 (d): the frame's `quantum_workloads`
 * block in the public registry-config). This module only reads them, defensively, for the card the console draws:
 *  - quantumServed(): the frame serves the extension (status shadow or on). An off frame publishes no block, and then
 *    the console asks nothing and shows nothing (byte-inert, like the registry);
 *  - latticeFor(): what the lattice may draw. Edges come only from what the card states: an all-to-all topology
 *    couples every pair; a coupling map published as a digest gives no edges at all, and the card says so. An edge is
 *    never guessed from a topology's name;
 *  - rungRows(): the verification rungs a buyer can get, and which of them settle a verdict on this registry (the
 *    registry's block names the rails; the card names what the agent offers; rung 3 is signed claims only);
 *  - quantumQuery(): the discovery filters as the registry reads them, and nothing at all when none is set.
 *
 * No i18n here (pure, node-testable): the components translate; this returns semantic fields only.
 */

export const QUANTUM_EXTENSION_URI = 'https://theprotocol.cloud/extensions/v1/quantum/workload'

/** V0660 (d)'s block, as the registry-config and the registry card publish it (absent while the switch is off). */
export interface QuantumWorkloadsBlock {
  status?: string
  receipt_schema?: { version?: string; signature_algorithms?: string[] }
  acceptance_tests?: { rungs?: number[]; settled_through?: string[] }
  metering_circuit?: string | null
}

/** Does this frame serve the quantum workload extension? Only an answered shadow or on says yes. */
export function quantumServed(block: unknown): boolean {
  const s = block && typeof block === 'object' ? (block as any).status : null
  return s === 'shadow' || s === 'on'
}

const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === 'object' && !Array.isArray(v)
const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v)
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x) => typeof x === 'string' && x.length > 0) : [])

/** The params of the card's quantum workload extension (its TOP-LEVEL extensions[], as the spec places it), or null. */
export function quantumParams(cardData: unknown): Record<string, any> | null {
  if (!isObj(cardData) || !Array.isArray(cardData.extensions)) return null
  const e = cardData.extensions.find((x: any) => isObj(x) && x.uri === QUANTUM_EXTENSION_URI)
  return e && isObj(e.params) ? e.params : null
}

/** The facets the discover list carries per agent (services/quantum_agent_card.facets). */
export interface QuantumFacets {
  version: string | null
  roles: string[]
  kinds: string[]
  modalities: string[]
  backends: number
  max_qubits: number | null
  max_logical_qubits: number | null
  formats: string[]
  jurisdictions: string[]
  rungs: number[]
  pricing_model: string | null
}

export function asFacets(raw: unknown): QuantumFacets | null {
  if (!isObj(raw)) return null
  return {
    version: typeof raw.version === 'string' ? raw.version : null,
    roles: strs(raw.roles),
    kinds: strs(raw.kinds),
    modalities: strs(raw.modalities),
    backends: isInt(raw.backends) ? raw.backends : 0,
    max_qubits: isInt(raw.max_qubits) ? raw.max_qubits : null,
    max_logical_qubits: isInt(raw.max_logical_qubits) ? raw.max_logical_qubits : null,
    formats: strs(raw.formats),
    jurisdictions: strs(raw.jurisdictions),
    rungs: Array.isArray(raw.rungs) ? raw.rungs.filter((r: any) => r === 1 || r === 2 || r === 3) : [],
    pricing_model: typeof raw.pricing_model === 'string' ? raw.pricing_model : null,
  }
}

export interface FacetCount { name: string; count: number }
/** facets.quantum of a discover page (services/quantum_agent_card.facets_block). */
export interface QuantumDiscoverFacets {
  total: number
  max_qubits: number | null
  roles: FacetCount[]
  kinds: FacetCount[]
  modalities: FacetCount[]
  formats: FacetCount[]
  jurisdictions: FacetCount[]
  rungs: FacetCount[]
}

const counts = (v: unknown): FacetCount[] => (Array.isArray(v) ? v : [])
  .filter((r: any) => isObj(r) && (typeof r.name === 'string' || isInt(r.name)) && String(r.name).length > 0)
  .map((r: any) => ({ name: String(r.name), count: isInt(r.count) ? r.count : 0 }))

export function asDiscoverFacets(raw: unknown): QuantumDiscoverFacets | null {
  if (!isObj(raw)) return null
  return {
    total: isInt(raw.total) ? raw.total : 0,
    max_qubits: isInt(raw.max_qubits) ? raw.max_qubits : null,
    roles: counts(raw.roles), kinds: counts(raw.kinds), modalities: counts(raw.modalities),
    formats: counts(raw.formats), jurisdictions: counts(raw.jurisdictions), rungs: counts(raw.rungs),
  }
}

// ── discovery filters ────────────────────────────────────────────────────────

export interface QuantumFilters {
  only: boolean
  role: string
  kind: string
  modality: string
  /** as typed: a whole number of at least 1, or '' */
  min_qubits: string
  format: string
  jurisdiction: string
  /** '1' | '2' | '3' | '' */
  rung: string
}

export function emptyQuantumFilters(): QuantumFilters {
  return { only: false, role: '', kind: '', modality: '', min_qubits: '', format: '', jurisdiction: '', rung: '' }
}

/** The discover query parameters the filters ask for; {} when none is set (the request is then what it was). */
export function quantumQuery(f: QuantumFilters | null | undefined): Record<string, string> {
  const q: Record<string, string> = {}
  if (!f) return q
  if (f.only) q.quantum_only = 'true'
  const put = (k: string, v: string) => { const s = (v || '').trim(); if (s) q[k] = s }
  put('quantum_role', f.role)
  put('quantum_kind', f.kind)
  put('quantum_modality', f.modality)
  const n = (f.min_qubits || '').trim()
  if (/^\d{1,8}$/.test(n) && Number(n) >= 1) q.quantum_min_qubits = String(Number(n))
  put('quantum_format', f.format)
  put('quantum_jurisdiction', (f.jurisdiction || '').toUpperCase())
  if (f.rung === '1' || f.rung === '2' || f.rung === '3') q.quantum_rung = f.rung
  return q
}

export function quantumFiltersActive(f: QuantumFilters | null | undefined): boolean {
  return Object.keys(quantumQuery(f)).length > 0
}

// ── the lattice ──────────────────────────────────────────────────────────────

/** The most qubits the lattice draws as points (the caption states the full count). */
export const LATTICE_NODE_CAP = 64
/** The most qubits whose all-to-all couplings are drawn pair by pair (24 qubits = 276 lines). */
export const COMPLETE_EDGE_CAP = 24

export interface LatticePoint { x: number; y: number }
export interface Lattice {
  /** the backend's physical qubits, as the card states them (0 when it states none) */
  qubits: number
  /** the points drawn (at most LATTICE_NODE_CAP) */
  drawn: number
  nodes: LatticePoint[]
  edges: Array<[number, number]>
  /** complete: the topology is all-to-all, so every pair is coupled · digest: the coupling map is published only as a
   *  digest, so no edge is drawn · none: the card states neither */
  source: 'complete' | 'digest' | 'none'
  topology: string | null
  digest: string | null
  url: string | null
  /** the number of couplings the card states (the digest's `edges`, or n(n-1)/2 for all-to-all) */
  edgeCount: number | null
  /** every stated coupling is on the drawing */
  edgesDrawn: boolean
}

function circle(n: number): LatticePoint[] {
  if (n === 1) return [{ x: 0.5, y: 0.5 }]
  return Array.from({ length: n }, (_, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / n
    return { x: round(0.5 + 0.42 * Math.cos(a)), y: round(0.5 + 0.42 * Math.sin(a)) }
  })
}

/** A field of points in offset rows: a count, not a topology (no edge is implied by where a point sits). */
function field(n: number): LatticePoint[] {
  if (n === 1) return [{ x: 0.5, y: 0.5 }]
  const cols = Math.max(2, Math.ceil(Math.sqrt(n * 1.6)))
  const rows = Math.ceil(n / cols)
  const pts: LatticePoint[] = []
  for (let i = 0; i < n; i++) {
    const r = Math.floor(i / cols)
    const c = i % cols
    const shift = r % 2 === 1 ? 0.5 : 0
    const x = 0.08 + (0.84 * (c + shift + 0.25)) / (cols + 0.5)
    const y = rows === 1 ? 0.5 : 0.12 + (0.76 * r) / (rows - 1)
    pts.push({ x: round(x), y: round(y) })
  }
  return pts
}

const round = (v: number) => Math.round(v * 10000) / 10000

export function latticeFor(backend: unknown): Lattice {
  const b = isObj(backend) ? backend : {}
  const q = isObj(b.qubits) && isInt(b.qubits.physical) && b.qubits.physical > 0 ? b.qubits.physical : 0
  const conn = isObj(b.connectivity) ? b.connectivity : {}
  const topology = typeof conn.topology === 'string' && conn.topology ? conn.topology : null
  const cmap = isObj(conn.coupling_map) ? conn.coupling_map : null
  const drawn = Math.min(q, LATTICE_NODE_CAP)
  if (topology === 'all-to-all') {
    const edgesDrawn = q > 0 && q <= COMPLETE_EDGE_CAP
    const edges: Array<[number, number]> = []
    if (edgesDrawn) for (let i = 0; i < q; i++) for (let j = i + 1; j < q; j++) edges.push([i, j])
    return { qubits: q, drawn, nodes: circle(drawn), edges, source: 'complete', topology,
      digest: null, url: null, edgeCount: q > 1 ? (q * (q - 1)) / 2 : 0, edgesDrawn }
  }
  const digest = cmap && typeof cmap.digest === 'string' ? cmap.digest : null
  return {
    qubits: q, drawn, nodes: field(drawn), edges: [], source: digest ? 'digest' : 'none', topology,
    digest, url: cmap && typeof cmap.url === 'string' ? cmap.url : null,
    edgeCount: cmap && isInt(cmap.edges) ? cmap.edges : null, edgesDrawn: false,
  }
}

/** A digest shortened for a line ("sha256:5173ee74…2a6a82"); the whole value goes in the title. */
export function shortDigest(d: string | null | undefined): string {
  if (!d) return ''
  const [alg, hex] = d.includes(':') ? d.split(':', 2) : ['', d]
  if (hex.length <= 16) return d
  return `${alg ? alg + ':' : ''}${hex.slice(0, 8)}…${hex.slice(-6)}`
}

// ── backends and their facts ─────────────────────────────────────────────────

export function backendsOf(params: unknown): Record<string, any>[] {
  return isObj(params) && Array.isArray(params.backends) ? params.backends.filter(isObj) : []
}

/** Whose second a per-second price is: `simulator` where every backend is a simulator or an emulator (an emulator is a
 *  simulator with a device's noise model), `qpu` where every one is a QPU, `backend` (a neutral second of backend time)
 *  for a mix, an unknown kind or no backend. Every backend on our side is a simulator, so "QPU second" is said only where
 *  the card states QPUs and nothing else. */
export function backendTimeKind(backends: unknown): 'simulator' | 'qpu' | 'backend' {
  const kinds = (Array.isArray(backends) ? backends.filter(isObj) : []).map((b) => b.kind)
  if (!kinds.length) return 'backend'
  if (kinds.every((k) => k === 'simulator' || k === 'emulator')) return 'simulator'
  if (kinds.every((k) => k === 'qpu')) return 'qpu'
  return 'backend'
}

/** Does a shared chat card name the quantum workload extension (data.extensions: URIs, or objects with a uri)? A hint
 *  the sender wrote, never trusted for anything but asking: the registry's read decides what is shown. */
export function chatCardNamesQuantum(data: unknown): boolean {
  if (!isObj(data) || !Array.isArray(data.extensions)) return false
  return data.extensions.some((x: any) => x === QUANTUM_EXTENSION_URI || (isObj(x) && x.uri === QUANTUM_EXTENSION_URI))
}

/** A probability as a percentage with up to three significant digits (0.0003 → "0.03%"). */
export function percent(p: unknown): string | null {
  if (typeof p !== 'number' || !Number.isFinite(p) || p < 0 || p > 1) return null
  const v = p * 100
  return `${Number(v.toPrecision(3))}%`
}

// ── availability (V0662 console polish, item 6) ───────────────────────────────

export type AvailabilityDays = 'everyday' | 'weekdays' | 'weekend' | 'monday' | 'tuesday' | 'wednesday' | 'thursday'
  | 'friday' | 'saturday' | 'sunday'
export interface AvailabilityWindow { days: AvailabilityDays; start: string; end: string; overnight: boolean }
const DAYS = new Set(['everyday', 'weekdays', 'weekend', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
const HHMM = /^([01][0-9]|2[0-3]):[0-5][0-9]$/

/** A backend's availability windows as the card states them (schema quantum_workload v1.0: days, start_utc,
 *  end_utc). A window that ends before it starts runs into the next day; one this cannot read is left out. */
export function availabilityWindows(backend: unknown): AvailabilityWindow[] {
  const a = isObj(backend) && isObj(backend.availability) ? backend.availability : null
  const ws = a && Array.isArray(a.windows) ? a.windows : []
  const out: AvailabilityWindow[] = []
  for (const w of ws) {
    if (!isObj(w) || !DAYS.has(String(w.days)) || !HHMM.test(String(w.start_utc)) || !HHMM.test(String(w.end_utc))) continue
    const start = String(w.start_utc), end = String(w.end_utc)
    out.push({ days: w.days as AvailabilityDays, start, end, overnight: end < start })
  }
  return out
}

export interface Age { n: number; unit: 's' | 'm' | 'h' | 'd' }
/** An age in whole units (the card shows "read 3 h ago"); null when unknown or in the future. */
export function ageOf(seconds: unknown): Age | null {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null
  if (seconds < 60) return { n: Math.floor(seconds), unit: 's' }
  if (seconds < 3600) return { n: Math.floor(seconds / 60), unit: 'm' }
  if (seconds < 86400) return { n: Math.floor(seconds / 3600), unit: 'h' }
  return { n: Math.floor(seconds / 86400), unit: 'd' }
}

/** Seconds since an ISO timestamp, at `now` (for a card read without the route's freshness). */
export function secondsSince(iso: unknown, now: number = Date.now()): number | null {
  if (typeof iso !== 'string') return null
  const t = Date.parse(iso)
  return Number.isFinite(t) ? Math.round((now - t) / 1000) : null
}

// ── the rungs a buyer can get ────────────────────────────────────────────────

export type RungState = 'settles_here' | 'offered' | 'claims_only'
export interface RungTest { template: string; method: string; falseAccept: string | null; falseReject: string | null }
export interface RungRow { rung: 1 | 2 | 3; state: RungState; rails: string[]; tests: RungTest[] }

/** One row per rung the card lists. Rung 1 and 2 settle here only where the registry's block names the rung and a rail
 *  that settles it; elsewhere the agent offers it and this registry settles no verdict at that rung. Rung 3 is signed
 *  claims only, wherever it is listed. */
export function rungRows(params: unknown, block: QuantumWorkloadsBlock | null | undefined): RungRow[] {
  const ev = isObj(params) && isObj(params.evidence) ? params.evidence : {}
  const listed = Array.isArray(ev.verification_rungs) ? ev.verification_rungs : []
  const tests = Array.isArray(ev.acceptance_tests) ? ev.acceptance_tests.filter(isObj) : []
  const at = block && isObj(block.acceptance_tests) ? block.acceptance_tests : {}
  const hereRungs = Array.isArray(at.rungs) ? at.rungs : []
  const rails = strs(at.settled_through)
  const rows: RungRow[] = []
  for (const r of [1, 2, 3] as const) {
    if (!listed.includes(r)) continue
    const own = tests.filter((t) => t.rung === r).map((t) => ({
      template: String(t.template ?? ''), method: String(t.method ?? ''),
      falseAccept: percent(t.false_accept_rate), falseReject: percent(t.false_reject_rate),
    }))
    if (r === 3) { rows.push({ rung: 3, state: 'claims_only', rails: [], tests: own }); continue }
    const here = hereRungs.includes(r) && rails.length > 0
    rows.push({ rung: r, state: here ? 'settles_here' : 'offered', rails: here ? rails : [], tests: own })
  }
  return rows
}

/** The evidence the agent signs, as the card states it. */
export interface ReceiptFacts {
  schemaVersion: string | null
  signingAlgorithm: string | null
  meteringCircuit: string | null
  /** the registry's receipt schema (V0660 (d)), when it publishes one */
  registrySchema: string | null
  registryAlgorithms: string[]
  ledgerKeeps: string[]
  residency: string[]
  circuitsDays: number | null
  resultsDays: number | null
  exportNote: string | null
  pricingModel: string | null
  pricingUnit: string | null
}

export function receiptFacts(params: unknown, block: QuantumWorkloadsBlock | null | undefined): ReceiptFacts {
  const p = isObj(params) ? params : {}
  const ev = isObj(p.evidence) ? p.evidence : {}
  const rc = isObj(ev.receipt) ? ev.receipt : {}
  const data = isObj(p.data) ? p.data : {}
  const ret = isObj(data.retention) ? data.retention : {}
  const exp = isObj(data.export_control) ? data.export_control : {}
  const pr = isObj(p.pricing) ? p.pricing : {}
  const rs = block && isObj(block.receipt_schema) ? block.receipt_schema : {}
  return {
    schemaVersion: typeof rc.schema_version === 'string' ? rc.schema_version : null,
    signingAlgorithm: typeof rc.signing_algorithm === 'string' ? rc.signing_algorithm : null,
    meteringCircuit: typeof ev.metering_circuit === 'string' ? ev.metering_circuit : null,
    registrySchema: typeof rs.version === 'string' ? rs.version : null,
    registryAlgorithms: strs(rs.signature_algorithms),
    ledgerKeeps: strs(data.ledger_keeps),
    residency: strs(data.residency),
    circuitsDays: isInt(ret.circuits_days) ? ret.circuits_days : null,
    resultsDays: isInt(ret.results_days) ? ret.results_days : null,
    exportNote: typeof exp.note === 'string' ? exp.note : null,
    pricingModel: typeof pr.model === 'string' ? pr.model : null,
    pricingUnit: typeof pr.unit === 'string' ? pr.unit : null,
  }
}
