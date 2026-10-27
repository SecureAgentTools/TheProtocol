import type { BlueprintDeep } from '../types'

// ENCLAVE deep architecture (§18, frontier wave 2026-09-25): a research group buys aggregate
// queries against a transit authority's passenger counts. The rows stay in the owner's enclave;
// the seats, the grants, the payments and the record of every question live on the owner's frame.

export const deep: BlueprintDeep = {
  intro:
    'ENCLAVE deployed: the transit authority’s frame holds the licence seats, the grants behind them, the query payments and the question ledger; the institute funds its seat from its own frame, in its own currency; the passenger counts sit below in the enclave, read only by the query agent that runs beside them, and only aggregates come up. The trace replays the 09:40 batch, from the grant to the question ledger.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE TRANSIT AUTHORITY’S FRAME', sub: 'seats, grants, payments, the question ledger', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE INSTITUTE’S FRAME', sub: 'the study, its budget, its own books', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'funding crosses here, exactly once', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'THE ENCLAVE', sub: 'rows stay inside; only aggregates leave', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'partner', label: 'partner-lab', sub: 'a narrower permit', kind: 'agent', x: 140, y: 135 },
      { id: 'desk', label: 'study-desk', sub: 'the institute’s seat', kind: 'agent', x: 310, y: 135 },
      { id: 'steward', label: 'data steward', sub: 'sets, reduces grants', kind: 'human', x: 140, y: 255 },
      { id: 'gate', label: 'licence gate', sub: 'templates, budget, issuer', kind: 'gate', x: 310, y: 253 },
      { id: 'es', label: 'question ledger', sub: 'every question, kept', kind: 'ledger', x: 140, y: 375 },
      { id: 'teg', label: 'query payments', sub: 'single-use, once', kind: 'teg', x: 310, y: 375 },
      { id: 'researcher', label: 'Dr Halvorsen', sub: 'owns the study', kind: 'human', x: 690, y: 135 },
      { id: 'ies', label: 'institute ledger', sub: 'same transfers', kind: 'ledger', x: 860, y: 135 },
      { id: 'model', label: 'corridor-model', sub: 'reads signed answers', kind: 'agent', x: 690, y: 255 },
      { id: 'treasury', label: 'study-treasury', sub: 'funds the seat', kind: 'agent', x: 860, y: 255 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly-once', kind: 'teg', x: 640, y: 522 },
      { id: 'fx', label: 'FX pool', sub: 'two currencies', kind: 'teg', x: 850, y: 522 },
      { id: 'rows', label: 'passenger counts', sub: '2.3 billion rows', kind: 'external', x: 150, y: 692 },
      { id: 'qagent', label: 'query-LHV-2', sub: 'signs each aggregate', kind: 'agent', x: 330, y: 692 },
    ],
    edges: [
      { id: 'e-grant', from: 'steward', to: 'gate' },
      { id: 'e-budget', from: 'researcher', to: 'treasury' },
      { id: 'e-home', from: 'treasury', to: 'ies', dashed: true },
      { id: 'e-fund', from: 'treasury', to: 'fx', label: 'own currency', labelT: 0.5 },
      { id: 'e-fx', from: 'fx', to: 'xfer' },
      { id: 'e-land', from: 'xfer', to: 'teg', label: 'lands once', labelT: 0.5 },
      { id: 'e-ask', from: 'desk', to: 'gate' },
      { id: 'e-derive', from: 'desk', to: 'partner' },
      { id: 'e-token', from: 'gate', to: 'teg', label: 'single-use', labelT: 0.8 },
      { id: 'e-question', from: 'teg', to: 'qagent', label: 'paid question', curve: 40, labelT: 0.35 },
      { id: 'e-rows', from: 'rows', to: 'qagent', dashed: true },
      { id: 'e-answer', from: 'qagent', to: 'teg', label: 'answer, signed', curve: 40, labelT: 0.35 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-deliver', from: 'desk', to: 'model', label: 'answers home', labelT: 0.2 },
    ],
    script: [
      { edge: 'e-grant', dwellMs: 1500, caption: 'The authority’s data steward sets the grant behind the institute’s licence seat, and keeps the right to reduce it.' },
      { edge: 'e-budget', dwellMs: 1300, caption: 'At home, Dr Halvorsen sets the study’s query budget on the institute’s own frame.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'The study treasury funds the seat in the institute’s own currency.' },
      { edge: 'e-fx', dwellMs: 1200, caption: 'It converts through the FX pool between the two frames.' },
      { edge: 'e-land', dwellMs: 1300, caption: 'And lands on the seat, on the authority’s frame, exactly once.' },
      { edge: 'e-ask', dwellMs: 1400, caption: '09:40. The desk asks for 120 aggregate queries under its permit: three templates, 18,000 units of budget.' },
      { edge: 'e-derive', dwellMs: 1400, caption: 'For the partner lab it derives a narrower permit: one template, 2,400 units. A capability permit can only narrow.' },
      { edge: 'e-token', dwellMs: 1400, caption: 'Each query gets its own single-use payment authorization, 15 units, once its template and the budget are checked.' },
      { edge: 'e-question', dwellMs: 1300, caption: 'The paid question goes down to query-LHV-2, inside the enclave.' },
      { edge: 'e-rows', dwellMs: 1500, caption: 'It meets 2.3 billion rows that never leave. Cells under twenty boardings are suppressed, by the authority’s own rule.' },
      { edge: 'e-answer', dwellMs: 1400, caption: 'The query agent signs the aggregate it returns, and the payment settles exactly once.' },
      { edge: 'e-emit', dwellMs: 1500, caption: 'Question, price and signature land on the ledger, append-only. An audit is a query, not an investigation.' },
    ],
    traceLabel: 'The 09:40 batch: granted, funded from home, paid per question, signed, kept.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One sharing agreement, re-read as templates.',
      runs: 'Nothing. One existing data-sharing agreement redrawn as templates, prices, a budget and a term.',
      agents: 'None. The data steward and the research group argue over which questions deserve a template, which is exactly where that argument belongs.',
      integrates: 'Nothing. The warehouse, the clean room and the agreement stay exactly as they are.',
      notYet: 'No seat, no permit, no payment. The extract the agreement allows still ships the old way.',
      proof: 'Last year’s questions under that agreement re-expressed as template calls, and both sides agree every figure they published maps to one.',
    },
    {
      name: 'Pilot',
      headline: 'One template, one licensee, pilot prices.',
      runs: 'A hosted registry seat for the authority. No frame of its own yet.',
      agents: 'One query agent inside the enclave and one licensee desk.',
      integrates: 'The query agent reads the warehouse through the owner’s existing aggregation layer and signs each answer.',
      notYet: 'One template, one currency, no partners. The extract still ships in parallel.',
      proof: 'A month of questions, each paid once and each answer signed, and one deliberately unlisted template refused before any payment authorization existed.',
    },
    {
      name: 'Production',
      headline: 'The authority’s own frame; extracts retired.',
      runs: 'The authority’s frame: registry, TEG, event store, identity fabric, in its own data centre.',
      agents: 'A query agent per approved template, a seat per licensee, and partner seats that hold nothing of their own.',
      integrates: 'Grants follow the agreement register; finance reads settlement instead of invoices.',
      notYet: 'Other owners. One market proves itself first.',
      proof: 'An audit lists every question a licensee asked, what each cost and which signature stands behind each answer, from the ledger alone.',
    },
    {
      name: 'Federation',
      headline: 'Owners bring their own frames.',
      runs: 'Unchanged. The retail consortium and the logistics firm federate their own frames and sell from them.',
      agents: 'Buyers hold seats with several owners; their settled records travel with their identities.',
      integrates: 'Each new owner is a signed card and a licence, not a new clean-room contract per buyer.',
      notYet: 'Nothing structural. Growth is owners, templates and buyers.',
      proof: 'A buyer licensed by one owner pays for its first question against a second owner within a week, without a bilateral integration project.',
    },
  ],
  sequenceTitle: 'One question, payment authorization to signed answer',
  sequence: `sequenceDiagram
  participant Desk as study-desk (licence seat)
  participant Gate as licence gate
  participant Pay as query payments
  participant Q as query-LHV-2 (enclave)
  participant ES as question ledger
  Desk->>Gate: query 37 of 120, under the study permit
  Gate->>Pay: template and budget checked: single-use authorization, 15 units
  Desk->>Q: the question and the payment authorization
  Q->>Pay: verify the authorization
  Q-->>Desk: aggregate, signed
  Q->>ES: attestation: the question and a signature over the answer
  Desk->>Pay: settle on delivery
  Pay-->>Q: paid, exactly once
  Pay-->>ES: payment settled, append-only
  Note over Gate: a template the permit does not name is refused before any payment authorization exists
  Note over ES: an audit is a query, not an investigation`,
  sizing: [
    { level: 'L1', what: 'Researchers and analysts join with accounts and agents on a hosted registry', containers: '0 of theirs' },
    { level: 'L2', what: 'An owner runs its query agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'Each owner on its own frame, buyers’ frames federated', containers: 'a full frame each' },
  ],
}
