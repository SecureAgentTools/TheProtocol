import type { BlueprintDeep } from '../types'

// CADASTRE deep architecture (§18) — a register whose acts are signed,
// whose completions are atomic, and whose refusals are evidence.

export const deep: BlueprintDeep = {
  intro:
    'CADASTRE deployed: the registry authority runs its own frame under its own statute; conveyancers and lenders act from theirs; the banks’ retry-prone payment systems hit an idempotent rail that absorbs them. A change to the register is never an anonymous database write, and completion day is not a wire race. The trace replays parcel 4471, funding to atomic completion, with one forged discharge failing loudly on the way.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE REGISTRY’S FRAME', sub: 'its own hardware, its own statute', x: 30, y: 50, w: 440, h: 420, kind: 'frame' },
      { id: 'zp', label: 'CONVEYANCERS AND LENDERS', sub: 'their registries, their matters', x: 530, y: 50, w: 440, h: 310, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'acts and money cross here', x: 600, y: 385, w: 370, h: 230, kind: 'fabric' },
      { id: 'ze', label: 'MAPS AND BANKS', sub: 'geometry stays with survey; retries are absorbed at the rail', x: 30, y: 625, w: 940, h: 110, kind: 'external' },
    ],
    nodes: [
      { id: 'registrar', label: 'registrar', sub: 'named, mandated', kind: 'human', x: 160, y: 395 },
      { id: 'amgate', label: 'authority gate', sub: 're-derived, presence', kind: 'gate', x: 380, y: 395 },
      { id: 'chain', label: 'title chain', sub: 'append-only acts', kind: 'ledger', x: 160, y: 120 },
      { id: 'teg', label: 'escrow', sub: 'seen by both sides', kind: 'teg', x: 375, y: 265 },
      { id: 'fraud', label: 'fraud-watch', sub: 'reads the refusals', kind: 'agent', x: 160, y: 200 },
      { id: 'cvb', label: 'conveyancer', sub: 'buyer: funds, claims', kind: 'agent', x: 605, y: 120 },
      { id: 'lender', label: 'lender-desk', sub: 'charges + discharges', kind: 'agent', x: 880, y: 265 },
      { id: 'cvs', label: 'conveyancer', sub: 'seller: title', kind: 'agent', x: 755, y: 195 },
      { id: 'c-es', label: 'matter files', sub: 'same completion', kind: 'ledger', x: 875, y: 120 },
      { id: 'relay', label: 'lodgement relay', sub: 'signed acts in', kind: 'registry', x: 875, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pays exactly once', kind: 'teg', x: 760, y: 475 },
      { id: 'survey', label: 'survey / maps', sub: 'geometry authority', kind: 'external', x: 380, y: 700 },
      { id: 'banks', label: 'bank payments', sub: 'retries absorbed', kind: 'external', x: 605, y: 700 },
    ],
    edges: [
      { id: 'e-survey', from: 'survey', to: 'registrar', label: 'geometry, read-side', dashed: true, labelT: 0.44 },
      { id: 'e-fundc', from: 'cvb', to: 'xfer', label: 'funds completion', curve: -52, labelT: 0.33 },
      { id: 'e-landx', from: 'xfer', to: 'teg', label: 'lands, exactly once', labelT: 0.45, curve: 10 },
      { id: 'e-retry', from: 'banks', to: 'xfer', label: 'retries, absorbed', dashed: true, labelT: 0.63 },
      { id: 'e-claimb', from: 'cvb', to: 'relay', label: 'completion claim', curve: 46, labelT: 0.43 },
      { id: 'e-title', from: 'cvs', to: 'relay', label: 'delivers title', labelT: 0.56, curve: 4 },
      { id: 'e-charge', from: 'lender', to: 'relay', label: 'discharge, evidenced', labelT: 0.29 },
      { id: 'e-relay', from: 'relay', to: 'amgate', label: 'principal checked', curve: -24, labelT: 0.34 },
      { id: 'e-authorise', from: 'registrar', to: 'amgate', label: 'mandate', dashed: true, curve: -14, labelT: 0.3 },
      { id: 'e-act', from: 'amgate', to: 'teg', label: 'completion', labelT: 0.4, curve: 52 },
      { id: 'e-entry', from: 'teg', to: 'chain', label: 'one act', dashed: true, labelT: 0.4 },
      { id: 'e-pay', from: 'teg', to: 'xfer', curve: 70 },
      { id: 'e-scredit', from: 'xfer', to: 'cvs', curve: -6 },
      { id: 'e-cemit', from: 'cvb', to: 'c-es', dashed: true, curve: -4 },
      { id: 'e-fraud', from: 'fraud', to: 'chain', label: 'reads refusals', dashed: true, labelT: 0.43 },
    ],
    script: [
      { edge: 'e-fundc', dwellMs: 1400, caption: 'Completion day for parcel 4471. The buyer’s funds arrive ahead, not in a wire race.' },
      { edge: 'e-retry', dwellMs: 1300, caption: 'The banks’ systems retry as they always do. The rail absorbs every retry; nothing doubles.' },
      { edge: 'e-landx', dwellMs: 1300, caption: 'The escrow lands, visible to both conveyancers.' },
      { edge: 'e-claimb', dwellMs: 1300, caption: 'The buyer’s conveyancer claims completion from its own registry.' },
      { edge: 'e-title', dwellMs: 1300, caption: 'The seller’s conveyancer delivers the title side of the same act.' },
      { edge: 'e-charge', dwellMs: 1400, caption: 'The lender lodges its discharge with evidence attached. In March, a forged one arrives here too.' },
      { edge: 'e-relay', dwellMs: 1400, caption: 'The fabric couriers the signed lodgements in. The forged discharge fails loudly at the gate, and the attempt itself is preserved as evidence.' },
      { edge: 'e-authorise', dwellMs: 1500, caption: 'The registrar’s mandate is re-derived on this very request: named, present above the routine threshold, recorded.' },
      { edge: 'e-act', dwellMs: 1400, caption: 'The transfer entry and the release are one atomic completion. There is no moment where one exists without the other.' },
      { edge: 'e-entry', dwellMs: 1300, caption: 'The act joins the parcel’s chain: signed, replayable, forever.' },
      { edge: 'e-pay', dwellMs: 1300, caption: 'The purchase money moves exactly once.' },
      { edge: 'e-scredit', dwellMs: 1300, caption: 'The seller’s side is credited on its own frame.' },
      { edge: 'e-fraud', dwellMs: 1400, caption: 'The fraud unit reads the refusals ledger, where failed attempts are evidence, not log noise.' },
    ],
    traceLabel: 'Parcel 4471: funded, checked, completed atomically, one forgery refused.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'The register’s acts, re-read as a chain.',
      runs: 'Nothing. One parcel class redrawn as act types, authority rules and completion conditions.',
      agents: 'None. Registrars and counsel decide which acts need presence, and write the answer down.',
      integrates: 'Nothing. Survey systems remain authoritative for geometry, now and later.',
      notYet: 'No chain, no escrow, no gate.',
      proof: 'One parcel’s full history re-expressed as signed acts, and the registry confirms the chain replays to the current title.',
    },
    {
      name: 'Pilot',
      headline: 'One parcel class, shadow completions.',
      runs: 'A single-VM frame at the authority. One conveyancing firm connects with a seat.',
      agents: 'registrar mandate live at pilot ceilings; conveyancer agents lodge; fraud-watch reads.',
      integrates: 'Completions run in shadow beside the statutory process; nothing binds yet.',
      notYet: 'No statutory effect. The paper process still governs; the shadow has to earn its keep.',
      proof: 'Fifty shadow completions land atomically with the money model matching the statutory outcome on every one.',
    },
    {
      name: 'Production',
      headline: 'The authority’s frame, under the statute.',
      runs: 'The authority’s sovereign frame on its own hardware, under its own law.',
      agents: 'The full cast; every register change behind the re-derived mandate; presence above the routine threshold.',
      integrates: 'Conveyancers and lenders federate in; the banks keep their systems and lose their wire races.',
      notYet: 'Statutory recognition of the chain is the legislature’s act, not this deployment’s claim.',
      proof: 'A completion audit reconstructs a month of parcels from the chain alone, and the fraud unit cites a refused forgery as court-ready evidence.',
    },
    {
      name: 'Federation',
      headline: 'Matters cross firms without crossing trust.',
      runs: 'Unchanged. Firms and lenders bring frames or seats.',
      agents: 'Matter histories travel with the parties entitled to them.',
      integrates: 'Each new firm is a signed card and a licence.',
      notYet: 'Cross-jurisdiction title is a treaty question, deliberately out of scope.',
      proof: 'A new firm completes its first matter in its first week, and the authority never provisioned it anything by hand.',
    },
  ],
  sequenceTitle: 'One completion, funding to atomic act',
  sequence: `sequenceDiagram
  participant CVB as conveyancer-buyer
  participant Bank as bank rails (retrying)
  participant XT as cross-registry pay
  participant Gate as authority gate
  participant Reg as registrar (presence)
  participant TEG as completion escrow
  participant Chain as title chain
  Bank->>XT: funds, with retries
  XT->>TEG: lands exactly once
  CVB->>Gate: completion claim (via lodgement relay)
  Gate->>Reg: mandate re-derived, presence required
  Reg-->>Gate: signed, recorded
  Gate->>TEG: atomic completion: entry + release as one act
  TEG-->>Chain: the act, append-only, replayable
  Note over Gate: a forged discharge fails loudly here and becomes evidence`,
  sizing: [
    { level: 'L1', what: 'Small firms join with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A firm or lender runs agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'The authority’s sovereign frame under its own statute', containers: '~9, its hardware' },
  ],
}
