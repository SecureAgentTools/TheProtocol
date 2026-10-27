import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// AEGIS: weather risk readings and verified events (reworded 2026-10-26 on his word, like MOIRA: it reads signed
// sources and gives rates and chances; it sells no cover and pays no claims).

const primitives = [
  { step: 'The method, frozen at publication', primitive: 'Contract templates: publish is an irreversible version freeze', railStatus: 'LIVE (gated)' as const },
  { step: 'Paid per reading, on delivery', primitive: 'Escrow funded at order, released on the signed report', railStatus: 'LIVE' as const },
  { step: 'Weather data with identity', primitive: 'Oracle agents with SPIFFE identity, signed attestations', railStatus: 'LIVE' as const },
  { step: 'Contested readings', primitive: 'Four-phase dispute: evidence, ruling, settlement', railStatus: 'LIVE' as const },
  { step: 'The analyst’s track record', primitive: 'EigenTrust reputation over settled outcomes', railStatus: 'LIVE' as const },
  { step: 'Downstream notification', primitive: 'Webhooks on contract and settlement events', railStatus: 'LIVE' as const },
]

export const aegis: Blueprint = {
  id: 'aegis',
  tier: 2,
  rank: 5,
  industry: 'Risk Analysis and Event Verification',
  systemName: 'AEGIS',
  promise: 'A weather risk reading whose method froze at publication and whose every input carries a signature. It sells readings, never cover.',
  cases: [
    { role: 'Agricultural cooperative', line: 'Hail chances per district, per week, read before the nets go up.' },
    { role: 'Risk and planning teams', line: 'Event reports with signed sources, for models that stay your own.' },
    { role: 'Logistics and event planners', line: 'Storm and delay chances from signed feeds, with disputes that have teeth.' },
    { role: 'Auditors', line: 'A method you can replay instead of a model you have to trust.' },
  ],
  problem:
    'Weather risk is argued after the fact because the method, the data and the fee live in three systems and nobody can replay how a number was made. Every party has an incentive to remember the method differently, and the method is a PDF.',
  system: [
    'AEGIS is the risk desk of a growers’ cooperative with 2,400 greenhouse operators. It reads the weather service’s and the satellite operator’s signed readings and publishes a hail chance per district, per week, by method v4. The method is an instantiated template version: it froze when it was published, every reading the cooperative orders copies it, and neither side can rewrite how a number was made. The cooperative pays per reading through escrow on the ledger, released when the signed report arrives.',
    'On the night of 14 June, hail crosses Emsland. The oracle agents sign what they saw; the event gate checks the readings against method v4 and issues 61 verified event reports before the growers wake up, one per affected district, each with its sources and their signatures. The 62nd district contests its report, so its fee does what contested money does here: it stops, holds in escrow through a four-phase dispute, and moves exactly once when the ruling lands. What a grower decides on a report stays the grower’s own business, outside the protocol.',
  ],
  cast: [
    { agent: 'risk-desk', role: 'Publishes method versions, issues readings', ceiling: 'Publish and instantiate. Cannot touch the method of a delivered reading.' },
    { agent: 'oracle-dwd, oracle-sat', role: 'Supply weather data', ceiling: 'Signed attestations only. No release authority.' },
    { agent: 'event-gate', role: 'Checks readings against the frozen method', ceiling: 'Issues a report per event. Cannot alter the method or the fees.' },
    { agent: 'coop-watch', role: 'Reads the season for the cooperative', ceiling: 'Read-only, all season.' },
  ],
  loom: {
    nodes: [
      { id: 'method', label: 'Method v4', sub: 'published, frozen', kind: 'registry', x: 118, y: 110 },
      { id: 'escrow', label: 'Reading escrow', sub: 'funded at order', kind: 'teg', x: 336, y: 220 },
      { id: 'desk', label: 'risk-desk', sub: 'the analyst', kind: 'agent', x: 916, y: 110 },
      { id: 'oracle', label: 'oracle-dwd', sub: 'signed readings', kind: 'external', x: 118, y: 330 },
      { id: 'egate', label: 'Event gate', sub: 'method vs readings', kind: 'gate', x: 336, y: 330 },
      { id: 'fee', label: 'Fee release', sub: 'on the signed report', kind: 'teg', x: 560, y: 220 },
      { id: 'ledger', label: 'Event ledger', sub: 'cooperative-readable', kind: 'ledger', x: 764, y: 220 },
    ],
    edges: [
      { id: 'e-bind', from: 'method', to: 'escrow', label: 'v4 copied' },
      { id: 'e-data', from: 'oracle', to: 'egate', label: 'hail, signed' },
      { id: 'e-fire', from: 'egate', to: 'fee', label: 'report issued' },
      { id: 'e-fund', from: 'escrow', to: 'fee' },
      { id: 'e-emit', from: 'fee', to: 'ledger' },
      { id: 'a-rewrite', from: 'desk', to: 'method', attackOnly: true, label: 'soften step 9', curve: 50 },
    ],
    script: [
      { edge: 'e-bind', state: 'active', dwellMs: 1400, caption: 'The method froze at publish. Each order copied it. The fee waits in escrow.' },
      { edge: 'e-data', state: 'active', dwellMs: 1400, caption: '02:12. Hail crosses Emsland, and the oracles sign what they saw.' },
      { edge: 'e-fire', state: 'active', dwellMs: 1300, caption: 'Readings against the frozen method. The event is verified, and the report is issued.' },
      { edge: 'e-fund', state: 'active', dwellMs: 1300, caption: 'The escrow releases the fee for the delivered report.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1500, caption: '61 verified reports before sunrise, each fee carved and logged by the same rail.' },
    ],
  },
  attacks: [
    {
      title: 'The after-the-fact rewrite',
      attack: 'After the hail, the desk tries to soften step 9 of method v4, so that last week’s chance reads closer to what happened.',
      mechanism: 'Publishing is an irreversible freeze and instantiation copies rather than references. Every delivered reading carries the method it was made with, and there is no reference for a rewrite to travel through.',
      rail: 'S14',
      consequence: 'The desk can publish version 5 for next season. Version 4, and every reading made with it, is beyond reach, and the desk’s track record is scored against what it actually said.',
      script: [
        { edge: 'a-rewrite', state: 'denied', dwellMs: 1900, stopAt: 0.75, flashNode: 'method', caption: 'Published methods are frozen. A reading already delivered cannot be rewritten after the storm.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance posture', href: '/compliance' },
  ],
  rails: ['S01', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A hosted registry, or the analyst’s own frame from pre-built images.',
    agents: '4 roles. The oracles are the interesting ones.',
    integration: 'Weather data licensing and the cooperative’s planning tools. The risk model stays yours.',
  },
  nonClaims: [
    'AEGIS sells readings and verified event reports. It sells no cover, pays no claims and holds no regulatory authorisation.',
    'The protocol carries the method, the signed sources and the fee for each reading. What anyone decides on a reading stays theirs, outside the protocol.',
  ],
  mermaid: `flowchart LR
  T["method template<br/>publish = freeze"] -->|"instantiate copies"| R["reading order<br/>method v4"]
  R -->|"fee at order"| TEG["TEG escrow"]
  O["oracle agents<br/>SPIFFE identities"] -->|"signed attestations"| G{"event gate"}
  G -->|"report issued"| TEG
  TEG -->|"release on delivery"| ES[("event store")]
  DIS["dispute, 4 phases"] -->|"ruling drives split, once"| TEG`,
  legacy: [
    { system: 'The cooperative’s planning tools', connect: 'Plans stay where they are made. The method, the signed sources and the fee for each reading are the protocol\'s half.' },
    { system: 'Weather and event data feeds', connect: 'Licensed feeds land as signed oracle attestations. The method reads only attested values.' },
    { system: 'Reporting and archives', connect: 'Verified event reports export with their sources and signatures, instead of screenshots of a forecast.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
