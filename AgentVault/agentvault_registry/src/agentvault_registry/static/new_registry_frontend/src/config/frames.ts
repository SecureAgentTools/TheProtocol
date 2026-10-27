// Frame registry — the frames this console knows, AS THE SERVER NAMES THEM (§FEFRAME W2).
//
// FrameKey is an OPEN string: the registry's own name, lowercased (never a letter). Until W2 this file held a
// static seed of the retired frames (A = agentvault.com / AVT, B = frame-b / JDAY, C = frame-c / BVT, and two
// sandbox seeds) and a substring "family match" that made sbx-alpha "Frame A" and sbx-beta "Frame B"; on EU, ASIA
// and every operator the local frame resolved to nothing at all. Now FRAMES is filled from the frame manifest
// (GET /api/v1/public/registry-config: self + peers, composables/useFrameManifest.ts), and is EMPTY until it
// arrives: no frame is ever guessed.

import type { CurrencyCode } from './currencies'
import { unknownCurrency } from './currencies'
import { framesOf, frameOf, type FrameEntry, type FrameManifest } from '@/services/frameManifest'

export type FrameKey = string
export type TrustDomain = string
export type FrameTier = 'mainframe' | 'sovereign-mainframe' | 'sandbox' | 'cloud-operator' | 'unknown'
export type FrameEnv = 'prod' | 'sandbox' | 'dev'
export type FrameStatus = 'live' | 'degraded' | 'unreachable' | 'planned'

export interface FrameEventStream {
  /** Same-origin nginx path when the app is served from this frame's origin. */
  sameOriginPath?: string
  /** Absolute WS URL for cross-origin monitoring (e.g. watch sandbox-C from prod). */
  absoluteWsUrl?: string
  /** localhost dev fallback port (direct to the ES container). */
  devPort?: number
  /** Stats path (same-origin) — or use statsAbsoluteUrl for cross-origin. */
  statsPath?: string
  statsAbsoluteUrl?: string
}

export interface FrameCaps {
  hasOwnEventStore?: boolean
  mintable?: boolean
  fxEnabled?: boolean
}

export interface FrameDescriptor {
  key: FrameKey
  label: string
  shortLabel?: string
  /** AUTHORITATIVE identity + currency-lookup key. */
  trustDomain: TrustDomain
  /** Frame-level currency (seed truth; per-registry truth = card settlement_currency). */
  currency: CurrencyCode
  tier: FrameTier
  env: FrameEnv
  isSandbox: boolean
  /** CSS accent (var with hex fallback) — single source of the frame's colour. */
  accent: string
  origin?: string
  /** Value sent as ?frame= to admin aggregate endpoints when reachable via the local proxy. */
  adminFrameParam?: string
  es?: FrameEventStream
  caps?: FrameCaps
  source?: 'manifest' | 'topology' | 'merged'
  status?: FrameStatus
  /** §AGORASIM-2: the folded ledger strip a runtime frame belongs to (`sandbox` = the test frames); unset is `main`. */
  strip?: 'main' | 'sandbox'
}

/** The frames of this federation, own frame first, as the manifest names them. A LIVE array (filled in place by
 *  `setFramesFromManifest`), so a plain module that imported it sees the frames once they land; Vue readers use
 *  useFrames(), which is reactive. Empty until the manifest arrives, and on a registry that predates it. */
export const FRAMES: FrameDescriptor[] = []

/** One manifest entry as a FrameDescriptor. `ownKey` = this console's own frame (itself, or an operator's parent):
 *  it reads its ledger stats and admin aggregates as `local`; any other frame's stats go through this registry's
 *  per-frame proxy (`/api/v1/public/eventstore-stats/<key>`, server-side, no CORS). */
export function descriptorFromEntry(e: FrameEntry, ownKey: string | null): FrameDescriptor {
  const own = !!ownKey && e.key === ownKey
  const accentSeed = e.currency || e.key
  return {
    key: e.key,
    label: e.display_name || e.name || e.key,
    shortLabel: e.display_name || e.name || e.key,
    trustDomain: e.trust_domain || '',
    currency: e.currency || '',
    tier: ((e.tier as FrameTier) || (e.role === 'frame' ? 'sovereign-mainframe' : 'cloud-operator')),
    env: 'prod',
    isSandbox: false,
    accent: unknownCurrency(accentSeed).accent,
    origin: e.console_url || e.public_url || undefined,
    adminFrameParam: own ? 'local' : undefined,
    es: {
      absoluteWsUrl: e.ledger_ws || undefined,
      statsPath: own ? '/api/v1/public/eventstore-stats' : `/api/v1/public/eventstore-stats/${encodeURIComponent(e.key)}`,
    },
    caps: { hasOwnEventStore: e.role === 'frame' },
    source: 'manifest',
    status: 'live',
    strip: 'main',
  }
}

export function framesFromManifest(m: FrameManifest): FrameDescriptor[] {
  const own = frameOf(m, m.self)?.key ?? null
  return framesOf(m).map((e) => descriptorFromEntry(e, own))
}

/** Fill FRAMES in place from the manifest (useFrameManifest calls it once the config answers). */
export function setFramesFromManifest(m: FrameManifest): void {
  FRAMES.splice(0, FRAMES.length, ...framesFromManifest(m))
}

const _norm = (td: string | null | undefined): string => (td || '').toLowerCase().trim()

export function frameByTrustDomain(frames: FrameDescriptor[], td: string | null | undefined): FrameDescriptor | null {
  const n = _norm(td)
  if (!n) return null
  return frames.find(f => _norm(f.trustDomain) === n) ?? null
}

export function frameByKey(frames: FrameDescriptor[], key: FrameKey): FrameDescriptor | null {
  return frames.find(f => f.key === key) ?? null
}

// ─── EventStore URLs — ONE place that knows how to build them ───────────────
/**
 * §BRIDGE R7-B (2026-08-19). The dev-branch ES port was written out by hand in
 * ~12 places across 5 files, and THREE of them still said `8206` for frame C —
 * a port that refuses connections and always did. §BRIDGE P1 corrected the seed
 * below and stopped there, which is the classic result: one copy fixed, the rest
 * silently wrong, and a verified-looking fix that was still broken for every
 * localhost session.
 *
 * Prod was never affected (it goes same-origin through nginx), so nothing here
 * changes what a visitor gets. What it changes is that a port now exists in
 * exactly one place, and the next frame added inherits every call site for free.
 */
export function isLocalDevHost(): boolean {
  if (typeof window === 'undefined') return false
  return ['localhost', '127.0.0.1'].includes(window.location.hostname)
}

/** The live event socket for a frame: the manifest's absolute `ledger_ws` (wss://<frame public host>/ws/events);
 *  a same-origin path only for a descriptor that names one (the fresh-network strips); `/ws/events` on this
 *  origin as the last resort. */
export function esSocketUrl(key: string, frames: FrameDescriptor[] = FRAMES): string {
  const f = frameByKey(frames, key)
  if (f?.es?.absoluteWsUrl) return f.es.absoluteWsUrl
  const path = f?.es?.sameOriginPath || '/ws/events'
  if (typeof window === 'undefined') return `ws://localhost${path}`
  if (isLocalDevHost() && f?.es?.devPort) {
    return `ws://${window.location.hostname}:${f.es.devPort}/ws/events`
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

/** Projection stats for a frame, always through THIS registry's public proxy (own frame: `/eventstore-stats`,
 *  another frame: `/eventstore-stats/<key>`, read server-side). */
export function esStatsUrl(key: string, frames: FrameDescriptor[] = FRAMES): string {
  const f = frameByKey(frames, key)
  if (typeof window !== 'undefined' && isLocalDevHost() && f?.es?.devPort) {
    return `http://${window.location.hostname}:${f.es.devPort}/api/v1/projections/stats`
  }
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return `${origin}${f?.es?.statsPath || (key ? `/api/v1/public/eventstore-stats/${encodeURIComponent(key)}` : '/api/v1/public/eventstore-stats')}`
}
