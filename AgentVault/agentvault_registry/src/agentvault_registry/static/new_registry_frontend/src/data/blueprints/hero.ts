// The hero Loom — one generic flow answering "what does a request look like
// here" before any industry is named. Includes a standing denial branch: the
// unvetted caller is refused at the gate on every loop, and downstream stays
// dark. The denial is part of the normal picture, not an exception to it.

import type { LoomEdge, LoomNode, LoomStep } from './types'

export const HERO_NODES: LoomNode[] = [
  { id: 'client', label: 'any client', sub: 'browser, agent, cron', kind: 'external', x: 118, y: 95 },
  { id: 'agent', label: 'service agent', sub: 'DID + workload identity', kind: 'agent', x: 336, y: 95 },
  { id: 'provider', label: 'counterparty', sub: 'does the work', kind: 'agent', x: 560, y: 95 },
  { id: 'gate', label: 'Authority gate', sub: 'deny-only, pre-escrow', kind: 'gate', x: 336, y: 285 },
  { id: 'escrow', label: 'Escrow', sub: 'held, not promised', kind: 'teg', x: 560, y: 285 },
  { id: 'release', label: 'Release', sub: 'exactly once', kind: 'teg', x: 764, y: 285 },
  { id: 'rogue', label: 'unvetted caller', sub: 'no grants', kind: 'external', x: 118, y: 452 },
  { id: 'ledger', label: 'Event ledger', sub: 'immutable, replayable', kind: 'ledger', x: 560, y: 452 },
  { id: 'auditor', label: 'auditor', sub: 'independent, live', kind: 'external', x: 856, y: 452 },
]

export const HERO_EDGES: LoomEdge[] = [
  { id: 'h-ask', from: 'client', to: 'agent', label: 'a request' },
  { id: 'h-auth', from: 'agent', to: 'gate', label: 'authority first' },
  { id: 'h-fund', from: 'gate', to: 'escrow', label: 'value held' },
  { id: 'h-work', from: 'agent', to: 'provider', label: 'the work' },
  { id: 'h-deliver', from: 'provider', to: 'release', label: 'verified' },
  { id: 'h-settle', from: 'escrow', to: 'release' },
  { id: 'h-emit', from: 'release', to: 'ledger' },
  { id: 'h-verify', from: 'ledger', to: 'auditor', label: 'delta = 0' },
  { id: 'h-rogue', from: 'rogue', to: 'gate', label: 'no authority' },
]

export const HERO_SCRIPT: LoomStep[] = [
  { edge: 'h-ask', state: 'active', dwellMs: 1400, caption: 'A request arrives. Anything can ask; identity decides what happens next.' },
  { edge: 'h-auth', state: 'active', dwellMs: 1400, caption: 'Authority is checked before anything else exists.' },
  { edge: 'h-fund', state: 'active', dwellMs: 1400, caption: 'Value is held in escrow, not promised.' },
  { edge: 'h-work', state: 'active', dwellMs: 1400, caption: 'The work happens between agents that can prove who they are.' },
  { edge: 'h-deliver', state: 'active', dwellMs: 1400, caption: 'Delivery is verified before release.' },
  { edge: 'h-settle', state: 'active', dwellMs: 1300, caption: 'Release, exactly once, fee carved by the same rail.' },
  { edge: 'h-emit', state: 'active', dwellMs: 1300, caption: 'Everything lands on a ledger that cannot be edited.' },
  { edge: 'h-verify', state: 'active', dwellMs: 1500, caption: 'An independent auditor verifies conservation, continuously.' },
  { edge: 'h-rogue', state: 'denied', dwellMs: 1700, stopAt: 0.78, flashNode: 'gate', caption: 'And a caller with no grants gets this: refused before value, nothing to unwind.' },
]
