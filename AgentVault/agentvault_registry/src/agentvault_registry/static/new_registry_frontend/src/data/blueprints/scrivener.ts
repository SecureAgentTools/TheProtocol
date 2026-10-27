import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Frozen standard terms', primitive: 'Contract templates: publish is an irreversible version freeze', railStatus: 'LIVE (gated)' as const },
  { step: 'Which wording the client bought', primitive: 'Instantiation copies the version; the ledger records which', railStatus: 'LIVE (gated)' as const },
  { step: 'Structured engagement terms', primitive: 'terms_schema JSON Schema forms with annex references', railStatus: 'LIVE (gated)' as const },
  { step: 'Money held from acceptance', primitive: 'Escrow at agreement, staged strict-order milestones', railStatus: 'LIVE' as const },
  { step: 'Named liable partner', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const },
  { step: 'Human really present', primitive: 'WebAuthn presence; an expired confirmation is a recorded denial', railStatus: 'LIVE' as const },
  { step: 'Contested milestone', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const },
  { step: 'Ruling executes once', primitive: 'Double-drive guard: a second ruling on the linked dispute is refused', railStatus: 'LIVE' as const },
  { step: 'Referral economics', primitive: 'Royalty carved at settle, basis points, capped', railStatus: 'LIVE (gated)' as const },
  { step: 'The insurer’s file', primitive: 'Per-mandate hash chain, authority snapshot on every event', railStatus: 'LIVE (gated)' as const },
]

export const scrivener: Blueprint = {
  id: 'scrivener',
  tier: 1,
  rank: 3,
  industry: 'Regulated Professional Services',
  systemName: 'SCRIVENER',
  promise: 'Engagement letters that cannot be quietly rewritten, and an evidence chain instead of email archaeology.',
  cases: [
    { role: 'Audit and advisory firm', line: 'Engagement letters whose exact version the client can prove.' },
    { role: 'Law practice', line: "Escrowed retainers with releases behind a partner's physical presence." },
    { role: 'Consultancy', line: 'Milestone billing that cannot be quietly renegotiated mid-dispute.' },
    { role: 'Trustee and notary services', line: 'A hash chain instead of a mailbox when the insurer calls.' },
  ],
  problem:
    'An engagement letter is a PDF. What was actually agreed, by whom, under which version of the firm’s standard terms, is reconstructed from email archaeology at the exact moment reconstruction is adversarial, which is during a dispute. The firm’s own records answer "what do our terms say now," not "what did they say when this client signed," and the difference is where malpractice claims live.',
  system: [
    'SCRIVENER is the engagement layer of a mid-sized audit and advisory firm: forty-one agents, one partner mandate per engagement, and a template library whose published versions cannot be edited by anyone, including the firm that owns them. When the firm updates its standard terms, it publishes version 12 beside version 11. Nothing that instantiated version 11 changes, ever. A client who signed under version 11 can prove, from the ledger, exactly which wording they bought, because instantiation copies the frozen text rather than referencing something mutable.',
    'An engagement begins when the intake agent instantiates the template and fills its terms schema: scope, fee cap, deadline, annex references. The work decomposes into milestones with the money in escrow from acceptance. Associate agents submit, a reviewer verifies, and any release above 5,000 units requires the partner, a named human being whose mandate underwrites the engagement account for this scope and nothing else. The agent that releases is that account’s own sub-agent, with no wallet of its own, so every release it makes answers to her mandate, and her authority is re-derived on every request. The firm suspends her for a conflict check on Tuesday morning; by Tuesday’s next request, every mandate leaning on her flags conveys nothing, with no permit rotation and no cache to chase.',
    'In November a client contests milestone three. The money does not move. It sits in escrow while the dispute runs its four phases, and when the ruling lands, the ruling itself drives the split: the escrow divides per the arbiter’s decision, exactly once, and a second ruling on the same dispute is refused as a conflict. The file that reaches the firm’s insurer afterwards is not a narrative reconstructed from mailboxes. It is a hash chain: who held what authority at each moment, which facts a present human confirmed, and which confirmations expired unanswered, because here an expired approval is not a gap in the record. It is a recorded denial.',
  ],
  cast: [
    { agent: 'intake-clerk', role: 'Instantiates the engagement from a template, fills the terms schema', ceiling: 'Template instantiate. Cannot publish versions, cannot release.' },
    { agent: 'associate-1..n', role: 'Performs the work, submits milestones', ceiling: 'Milestone submit. Cannot approve its own submission.' },
    { agent: 'qa-reviewer', role: 'Verifies deliverables before release', ceiling: 'Verify only. Holds no release permission.' },
    { agent: 'partner (human)', role: 'The mandate behind releases above threshold', ceiling: 'Cockpit Card scope: this engagement class only. Presence proof above 5,000.' },
    { agent: 'records-clerk', role: 'Serves the evidentiary chain to auditors and insurers', ceiling: 'Read-only on events and attestations.' },
  ],
  loom: {
    nodes: [
      { id: 'template', label: 'Template v11', sub: 'published, frozen', kind: 'registry', x: 336, y: 110 },
      { id: 'partner', label: 'partner', sub: 'named, liable', kind: 'human', x: 560, y: 110 },
      { id: 'client', label: 'client', sub: 'counterparty', kind: 'external', x: 118, y: 110 },
      { id: 'intake', label: 'intake-clerk', sub: 'opens engagements', kind: 'agent', x: 118, y: 330 },
      { id: 'engage', label: 'Engagement escrow', sub: 'funded at accept', kind: 'teg', x: 336, y: 220 },
      { id: 'pgate', label: 'Partner mandate', sub: 'presence over 5,000', kind: 'gate', x: 560, y: 330 },
      { id: 'release', label: 'Release', sub: 'exactly once', kind: 'teg', x: 764, y: 330 },
      { id: 'associate', label: 'associate', sub: 'does the work', kind: 'agent', x: 118, y: 450 },
      { id: 'qa', label: 'qa-reviewer', sub: 'verify before release', kind: 'agent', x: 336, y: 330 },
      { id: 'chain', label: 'Evidence chain', sub: 'authority snapshots', kind: 'ledger', x: 764, y: 450 },
    ],
    edges: [
      { id: 'e-open', from: 'intake', to: 'engage', label: 'terms schema' },
      { id: 'e-copy', from: 'template', to: 'engage', label: 'v11 copied in' },
      { id: 'e-work', from: 'associate', to: 'qa', label: 'milestone three' },
      { id: 'e-verify', from: 'qa', to: 'pgate', label: 'verified' },
      { id: 'e-facts', from: 'pgate', to: 'partner', label: 'server-computed facts', curve: -50, labelT: 0.4 },
      { id: 'e-sign', from: 'partner', to: 'pgate', label: 'presence', curve: -50, labelT: 0.4 },
      { id: 'e-release', from: 'pgate', to: 'release' },
      { id: 'e-evidence', from: 'release', to: 'chain' },
      { id: 'a-amend', from: 'intake', to: 'template', attackOnly: true, label: 'amend clause 7', curve: -60, labelT: 0.4 },
      { id: 'a-claw', from: 'client', to: 'engage', attackOnly: true, label: 'full clawback' },
    ],
    script: [
      { edge: 'e-open', state: 'active', dwellMs: 1400, caption: 'Intake instantiates the engagement and fills the terms schema.' },
      { edge: 'e-copy', state: 'active', dwellMs: 1500, caption: 'The frozen text of version 11 is copied in. Nothing references anything mutable.' },
      { edge: 'e-work', state: 'active', dwellMs: 1300, caption: 'The associate submits milestone three.' },
      { edge: 'e-verify', state: 'active', dwellMs: 1300, caption: 'Review verifies before any money moves.' },
      { edge: 'e-facts', state: 'active', dwellMs: 1400, caption: 'Release needs the partner. The facts reach her as the server computed them.' },
      { edge: 'e-sign', state: 'active', dwellMs: 1500, caption: 'Her presence signs. An expired confirmation would be recorded as a denial.' },
      { edge: 'e-release', state: 'active', dwellMs: 1300, caption: 'Release, exactly once.' },
      { edge: 'e-evidence', state: 'active', dwellMs: 1600, caption: 'The insurer reads a hash chain, not a mailbox.' },
    ],
  },
  attacks: [
    {
      title: 'The retroactive amendment',
      attack: 'After the dispute is filed, the firm quietly edits clause 7 of its standard terms to favour its position.',
      mechanism: 'Publishing is an irreversible freeze behind a confirmation that says exactly that, and instantiation copied the text into the engagement. There is no reference to rewrite. The client’s copy is not protected from tampering; it is structurally incapable of being tampered with from the firm’s side.',
      rail: 'S14',
      consequence: 'The only lit path out of the template library is publishing version 13, which changes nothing the client holds.',
      script: [
        { edge: 'a-amend', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'template', caption: 'Published versions are frozen. Publishing v13 changes nothing the client holds.' },
      ],
    },
    {
      title: 'The mid-dispute clawback',
      attack: 'The client, mid-dispute, invokes the self-serve failure path to claw back the full escrow over work already delivered.',
      mechanism: 'A contested engagement is frozen for the arbiter. A unilateral full refund from the disputed state is refused as a conflict, while the provider’s option to concede remains open.',
      rail: 'S16',
      consequence: 'Neither side can move contested value. The escrow waits for the ruling, the ruling executes exactly once, and both facts land in the evidentiary chain.',
      script: [
        { edge: 'a-claw', state: 'denied', dwellMs: 1900, stopAt: 0.66, flashNode: 'engage', caption: 'Contested value is frozen for the arbiter. A unilateral refund from DISPUTED is refused.' },
      ],
    },
  ],
  primitives,
  groundingShot: {
    src: '/static/blueprints/ground-scrivener.jpg',
    caption: 'Not a mockup. The production contract template library: versioned, hash-provable templates with escrowed instantiation, photographed on the running network.',
  },
  complianceRefs: [
    { label: 'Data Protection Policy', href: '/compliance/doc/data-protection-policy' },
  ],
  rails: ['S02', 'S05', 'S06', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A firm-run registry booted from pre-built images, or a hosted one and nothing to run at all.',
    agents: '5 roles, and most firms start with intake and one associate.',
    integration: 'The document management system and the practice management suite. The protocol carries agreement, authority, and money; the working papers stay where they are.',
  },
  nonClaims: [
    'SCRIVENER is not a qualified electronic signature scheme under eIDAS and makes no claim about evidentiary admissibility in any jurisdiction.',
    'The protocol stores agreements, authority and settlement, not the client’s working papers.',
    'Nothing here is legal advice, including the blueprint about lawyers.',
  ],
  mermaid: `flowchart LR
  T["contract template<br/>publish = version freeze"] -->|"instantiate copies text"| C["contract<br/>terms_schema + annexes"]
  C -->|"escrow at accept"| TEG["TEG escrow"]
  A["associate agent"] -->|"milestone submit"| C
  C -->|"release above threshold"| M["Cockpit mandate<br/>authority re-derived"]
  M -->|"WebAuthn presence<br/>expiry = recorded denial"| TEG
  D["dispute (4 phases)"] -->|"ruling drives split<br/>second ruling = 409"| TEG
  TEG --> ES[("event store<br/>hash chain + snapshots")]`,
  legacy: [
    { system: 'Document management (iManage, NetDocuments)', connect: 'Working documents never move. The evidence chain stores hashes and agreement acts; the DMS stays the file of record.' },
    { system: 'Practice management and billing', connect: 'Matter numbers and rate cards stay authoritative. Settled milestones post back as billing entries.' },
    { system: 'E-signature platforms', connect: 'Engagement acts are signed on the protocol. Existing e-sign flows continue for third parties until both sides trust one record.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
