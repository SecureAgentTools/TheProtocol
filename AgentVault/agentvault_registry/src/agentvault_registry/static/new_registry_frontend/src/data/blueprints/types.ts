// Industry Blueprints — shared data types.
// Strategy: PRODUCTION_DOCS/ROADMAP/Industry_Blueprints_Showcase_Strategy.md
//
// Blueprints are typed DATA, not markup: the view renders whatever these files
// declare, so adding industry #13 is a data edit, never a new component.
// Copy rules (§4.0 of the strategy): present tense, no em dashes, no emoji,
// safety stated as fact of design; protocol numbers only where the primitives
// table can back them.

export type NodeKind =
  | 'agent'     // an autonomous actor
  | 'human'     // a named liable person (mandate / presence)
  | 'registry'  // a registry / frame / replica surface
  | 'teg'       // money: escrow, transfer, settlement
  | 'ledger'    // the immutable event ledger
  | 'gate'      // an authorization gate (deny-only, pre-escrow)
  | 'external'  // an off-network party or system

export type EdgeState = 'idle' | 'active' | 'settled' | 'denied'

export interface LoomNode {
  id: string
  label: string
  sub?: string
  kind: NodeKind
  x: number // 0..1000 logical space
  y: number // 0..560 logical space
}

export interface LoomEdge {
  id: string
  from: string
  to: string
  label?: string
  /** Optional hand-authored path override. When absent, FlowLoom derives a
   *  smooth cubic from the endpoint node anchors (deterministic, no runtime
   *  layout reads). */
  d?: string
  /** Perpendicular bow, logical px. Lets bidirectional pairs (A to B and B to
   *  A) take visibly separate arcs instead of overlapping on one line. */
  curve?: number
  /** Where along the path (0..1) the label sits. Default 0.5; bidirectional
   *  pairs use ~0.26 / ~0.74 so their labels cannot collide. */
  labelT?: number
  /** Attack-only edges stay invisible during the happy path. */
  attackOnly?: boolean
}

export interface LoomStep {
  edge: string
  state: EdgeState
  /** Sweep duration for this step, ms. */
  dwellMs: number
  caption?: string
  /** 0..1 along the edge; a denied pulse halts here and stays parked. */
  stopAt?: number
  /** Node that flashes amber when a denied pulse halts. */
  flashNode?: string
}

export type RailStatus = 'LIVE' | 'LIVE (gated)' | 'SHADOW' | 'DESIGNED'

export type RailId =
  | 'S01' | 'S02' | 'S03' | 'S04' | 'S05' | 'S06' | 'S07' | 'S08' | 'S09'
  | 'S10' | 'S11' | 'S12' | 'S13' | 'S14' | 'S15' | 'S16' | 'S17' | 'S18'
  | 'S19'

export interface Rail {
  id: RailId
  name: string
  refusal: string // the refusal, in one line
}

export interface CastRow {
  agent: string
  role: string
  ceiling: string
}

export interface PrimitiveRow {
  step: string
  primitive: string
  railStatus: RailStatus
  href?: string
}

export interface Attack {
  title: string
  attack: string
  mechanism: string
  rail: RailId
  consequence: string
  script: LoomStep[]
  /** The public risk-register row this attack corresponds to (e.g.
   *  'R-OP-05'), ONLY where a row genuinely exists. Rendered as "tracked in
   *  the public risk register" with a link. Never invent a correspondence. */
  riskRef?: string
}

export interface IndustryCase {
  role: string // a job title or business the reader recognizes as their own
  line: string // one concrete sentence of what this blueprint is, for them
}

/** Legacy bridge (§BPBRIDGE 2026-08-11): one system the reader already runs
 *  and, in one concrete line, how it joins this chamber. The rendered section
 *  also carries the shared parallel-run + proxy-library copy (view-level, one
 *  place). Copy rules unchanged: present tense, no em dashes, honest about
 *  where the real work is. */
export interface LegacySystemRow {
  system: string
  connect: string
}

export interface Blueprint {
  id: string
  tier: 1 | 2 | 3
  /** Drafted out of the Vault (2026-08-09): rendered in their own page group
   *  and index section, after the original twelve. */
  vault?: boolean
  /** The frontier wave (2026-09-25): sectors arriving now. The system is
   *  further out than the rest; the rails under it are the same live ones,
   *  badged the same way. Rendered in its own index group, with its own chip. */
  frontier?: boolean
  rank: number
  industry: string
  systemName: string
  promise: string // one-line promise for the index rail
  /** Recognition hooks: concrete roles who should see themselves here. Feeds
   *  the per-blueprint strip AND the page-level industry finder. */
  cases: IndustryCase[]
  problem: string
  system: string[] // paragraphs
  cast: CastRow[]
  loom?: { nodes: LoomNode[]; edges: LoomEdge[]; script: LoomStep[] }
  attacks: Attack[]
  primitives: PrimitiveRow[]
  rails: RailId[]
  standup: { infra: string; agents: string; integration: string }
  nonClaims: string[]
  mermaid?: string
  /** The legacy systems this chamber runs BESIDE (never replaces on day one). */
  legacy?: LegacySystemRow[]
  groundingShot?: { src: string; caption: string }
  /** Links into the compliance suite (0..3): the canonical, caveated
   *  statements behind this blueprint's posture. Linked, never restated. */
  complianceRefs?: { label: string; href: string }[]
  /** [steps on LIVE / LIVE (gated) rails, total steps] — must be majority live
   *  (strategy §10.2). CI-checked. */
  liveRatio: [number, number]
}

/** Derive the ratio from the primitives table so prose and evidence cannot
 *  disagree. It counts CAPABILITY, not this deployment's switches: a rail that
 *  is built counts whether it runs enforced (LIVE), per deployment (LIVE
 *  (gated)) or observe-only (SHADOW). Only DESIGNED (specified, not built)
 *  counts against. The badge on each row still says how this deployment runs
 *  it (2026-09-25, his word: "should probably count capability and not if its
 *  enabled on our deployment right at this moment"). The field keeps its old
 *  name, liveRatio, so the data files need no change. */
export function liveRatioOf(primitives: PrimitiveRow[]): [number, number] {
  const built = primitives.filter((p) => p.railStatus !== 'DESIGNED').length
  return [built, primitives.length]
}

// ---------------------------------------------------------------------------
// Deep architecture (§18) — the chamber's reference topology. Lazy-loaded per
// detail route from data/blueprints/arch/<id>.ts, never bundled into the Atlas.

/** A trust boundary drawn as a labelled box: an operator's sovereign frame, a
 *  partner frame, TheProtocol fabric, or the industry's own external systems. */
export interface ArchZone {
  id: string
  label: string
  sub?: string
  /** Logical space 0..1000 x 0..720. Nodes place themselves inside. */
  x: number
  y: number
  w: number
  h: number
  /** 'frame' zones read as sovereign deployments; 'fabric' as shared protocol
   *  machinery; 'external' as off-network systems (dashed border). */
  kind: 'frame' | 'fabric' | 'external'
}

export interface ArchNode {
  id: string
  label: string
  sub?: string
  kind: NodeKind
  x: number
  y: number
}

export interface ArchEdge {
  id: string
  from: string
  to: string
  label?: string
  curve?: number
  labelT?: number
  /** Dashed rendering for control-plane / attestation links (vs money). */
  dashed?: boolean
}

export interface ArchStep {
  edge: string
  dwellMs: number
  caption?: string
}

export interface BlueprintArch {
  zones: ArchZone[]
  nodes: ArchNode[]
  edges: ArchEdge[]
  /** Optional TRACE THE FLOW replay of the core transaction. A map, not a
   *  theatre: no denied state, no attack machinery. */
  script?: ArchStep[]
  /** One line under the canvas naming what the trace shows. */
  traceLabel?: string
}

/** One phase of the adoption path. The register rule applies: every phase ends
 *  on a verifiable statement (the proof), never a promise. */
export interface AdoptionPhase {
  name: string
  headline: string
  runs: string        // infrastructure, in container terms
  agents: string      // which agents exist by now
  integrates: string  // what connects to the real world
  notYet: string      // what is deliberately NOT yet true
  proof: string       // the verifiable statement that gates the next phase
}

export interface SizingRow {
  level: string   // L1 / L2 / L3
  what: string
  containers: string
}

/** The chamber's deep layer. Everything optional except the topology: a
 *  chamber without an arch module renders the anatomy plus an honest
 *  "in drafting" band (§18.4). */
export interface BlueprintDeep {
  arch: BlueprintArch
  plan: AdoptionPhase[]
  /** Mermaid sequenceDiagram of the core money path, lazy-rendered. */
  sequence?: string
  sequenceTitle?: string
  sizing?: SizingRow[]
  /** One paragraph framing this architecture, chamber-top. */
  intro?: string
}
