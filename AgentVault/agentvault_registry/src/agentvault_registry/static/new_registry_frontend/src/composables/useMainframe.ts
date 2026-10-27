/**
 * useMainframe — §pass66 (2026-05-22) / §pass66.2 hardened (2026-05-23).
 *
 * Single source of truth for "is THIS frontend running on a sovereign
 * mainframe registry (Frame-A / Frame-B)?". Mirrors the backend
 * `core.mainframe_gate.is_mainframe()` check.
 *
 * §pass66.2 robustness pass — Commander caught Registry-A showing as
 * non-mainframe due to a single-string anchor (`identity.tier ===
 * 'sovereign-mainframe'`) — if the card endpoint glitched OR the tier
 * field renamed, the whole gate broke and every mainframe-only item
 * locked. Now uses FIVE independent positive markers from the card +
 * a `/api/v1/federation/info` fallback when the card fetch fails.
 *
 * Any single positive marker → mainframe = TRUE. No single field can
 * break the gate. Backwards-compat with any future card schema drift.
 *
 * Used by:
 *   - `usePermissions.ts` — exposes `isMainframe` + `canMintAvt /
 *     canManageFrames / canProvisionOperators / canIssueLicenses` for
 *     UI gates (sidebar items, buttons, view-local checks)
 *   - Router guards — redirect cloud-ops away from mainframe-only routes
 *
 * Fetch happens ONCE on first access + cached at module scope (every
 * subsequent caller hits the cache instantly). Both endpoints are
 * unauthenticated, so the boot-time fetches are cheap.
 *
 * §FEFRAME W2 (2026-10-01): the FRAME MANIFEST decides first (registry-config `self.role`: "frame" for a sovereign
 * mainframe, "operator" for a cloud operator; the server derives it from the same MINTING_AUTHORITY / tier facts
 * the backend gate reads). The card markers and /federation/info below are the FALLBACK for a console whose
 * manifest could not be read, never a second opinion that could disagree with it.
 */
import { ref, computed, type ComputedRef } from 'vue'
import { loadFrameManifest } from '@/composables/useFrameManifest'
import { createBackoffRetry } from '@/services/backoffRetry'

// Module-level cache — survives composable re-instantiation across components.
// `_isMainframe` is the final decision (null = not yet determined). `_signalsSeen`
// stores diagnostic info for the dev console.
const _isMainframe = ref<boolean | null>(null)
const _signalsSeen = ref<string[]>([])
const _tierRaw = ref<string | null>(null)
const _fetched = ref(false)
const _fetchPromise = ref<Promise<void> | null>(null)
/** §FESUITE (2026-10-09): the last read reached none of the three sources (the manifest, the card, /federation/info).
 *  That used to be decided as "not a mainframe" for the rest of the session: a console that booted while the registry
 *  could not answer kept every mainframe-only view (Frame Management, OP Management) locked after it was back, and told
 *  the admin "cloud-ops federate with the mainframe for these actions" on a mainframe (sweeps/recovery on V0587). Now
 *  it is no decision: gates stay closed (the safe side) while the reads are retried, the next access reads again, and a
 *  guard says the check could not be made instead of naming a cloud operator. */
const _readFailed = ref(false)
const _retry = createBackoffRetry(() => { _ensureFetched() })

/**
 * Multi-signal mainframe decision from a registry card payload.
 *
 * ANY ONE positive marker = mainframe (defensive OR). Designed so that:
 *   - A renamed tier string can't break the gate (4 other markers cover)
 *   - A missing field can't break the gate (defaults to false, no throw)
 *   - A truncated/old card schema can't break the gate (markers are independent)
 *
 * Returns { mainframe, signals } so callers can log which signals fired.
 */
function _evaluateCard(card: any): { mainframe: boolean; signals: string[] } {
  const signals: string[] = []
  if (!card || typeof card !== 'object') return { mainframe: false, signals }

  const identity = (card.identity || {}) as Record<string, unknown>
  const federation = (card.federation || {}) as Record<string, unknown>
  const capabilities = (card.capabilities || {}) as Record<string, unknown>

  if (identity.tier === 'sovereign-mainframe') signals.push('identity.tier=sovereign-mainframe')
  if (federation.is_sovereign_frame === true) signals.push('federation.is_sovereign_frame=true')
  if (federation.is_genesis_registry === true) signals.push('federation.is_genesis_registry=true')
  if (capabilities.is_central_registry === true) signals.push('capabilities.is_central_registry=true')
  // §2026-06-14 — sovereign mainframes now report "sovereign" (was the
  // misleading "genesis_only"); accept both so the signal still fires for
  // peers on either image generation.
  if (capabilities.minting_capability === 'sovereign' || capabilities.minting_capability === 'genesis_only') signals.push('capabilities.minting_capability=' + capabilities.minting_capability)

  return { mainframe: signals.length > 0, signals }
}

async function _fetchCard(): Promise<{ ok: boolean; mainframe: boolean | null; signals: string[]; tier: string | null }> {
  try {
    const resp = await fetch('/.well-known/registry-card.json', { credentials: 'same-origin' })
    if (!resp.ok) {
      return { ok: false, mainframe: null, signals: [`card-http-${resp.status}`], tier: null }
    }
    const card = await resp.json()
    const tier = (card?.identity?.tier as string | null) ?? null
    const { mainframe, signals } = _evaluateCard(card)
    return { ok: true, mainframe, signals, tier }
  } catch (e) {
    return { ok: false, mainframe: null, signals: [`card-fetch-error:${String(e).slice(0, 80)}`], tier: null }
  }
}

async function _fetchFederationInfo(): Promise<{ ok: boolean; mainframe: boolean | null; tier: string | null }> {
  try {
    const resp = await fetch('/api/v1/federation/info', { credentials: 'same-origin' })
    if (!resp.ok) return { ok: false, mainframe: null, tier: null }
    const info = await resp.json()
    // /federation/info ships `is_mainframe` AND `tier`. Either positive => mainframe.
    const tier = (info?.tier as string | null) ?? null
    const isMf = info?.is_mainframe === true || tier === 'sovereign-mainframe'
    return { ok: true, mainframe: isMf, tier }
  } catch {
    return { ok: false, mainframe: null, tier: null }
  }
}

async function _doFetch(): Promise<void> {
  // Step 0 (§FEFRAME W2): the manifest's own answer.
  try {
    const m = await loadFrameManifest()
    if (m?.self) {
      _isMainframe.value = m.self.role === 'frame'
      _signalsSeen.value = [`manifest.self.role=${m.self.role}`]
      _tierRaw.value = m.self.tier ?? null
      _readFailed.value = false
      _retry.cancel()
      _fetched.value = true
      return
    }
  } catch { /* the card below */ }
  // Step 1: try the card. Five positive markers; one of them firing is enough.
  const cardResult = await _fetchCard()
  if (cardResult.ok && cardResult.mainframe !== null && cardResult.signals.length > 0) {
    _isMainframe.value = cardResult.mainframe
    _signalsSeen.value = cardResult.signals
    _tierRaw.value = cardResult.tier
    _readFailed.value = false
    _retry.cancel()
    _fetched.value = true
    return
  }

  // Step 2: card returned 0 markers OR the fetch failed. Fall back to
  // /federation/info, which has a server-side is_mainframe flag derived
  // from the same checks. Prevents a degraded card endpoint from locking
  // the entire UI.
  const infoResult = await _fetchFederationInfo()
  if (infoResult.ok && infoResult.mainframe !== null) {
    _isMainframe.value = infoResult.mainframe
    _signalsSeen.value = [
      ...(cardResult.signals.length ? cardResult.signals : ['card-no-markers']),
      `federation-info=${infoResult.mainframe}`,
    ]
    _tierRaw.value = infoResult.tier ?? cardResult.tier
    _readFailed.value = false
    _retry.cancel()
    _fetched.value = true
    return
  }

  // Step 3: no source answered. Gates stay closed (isMainframe reads false while _isMainframe is null: the safer
  // side), but this is no decision: nothing is cached, the next access reads again and a backoff retry reads on its
  // own, so a console that booted during an outage gets its mainframe views back once the registry answers.
  console.warn(
    '[useMainframe] the manifest, the card and federation/info could not be read: no decision yet, reading again. ' +
    `Signals: ${[...cardResult.signals, 'federation-info-unreachable'].join(', ')}`,
  )
  _isMainframe.value = null
  _signalsSeen.value = [...cardResult.signals, 'federation-info-unreachable']
  _tierRaw.value = cardResult.tier
  _readFailed.value = true
  _fetched.value = false
  _fetchPromise.value = null
  _retry.schedule()
}

function _ensureFetched() {
  if (_fetched.value || _fetchPromise.value) return
  _fetchPromise.value = _doFetch()
}

export interface UseMainframeReturn {
  /** True iff this frontend's registry is a sovereign mainframe.
   *  Derived from FIVE positive card markers + /federation/info fallback —
   *  any one fires => mainframe. Backwards compat with future schema changes. */
  isMainframe: ComputedRef<boolean>
  /** Raw tier string for diagnostic display (cardinal `identity.tier` value). */
  tier: ComputedRef<string | null>
  /** Diagnostic — which signals fired on the last fetch. */
  signals: ComputedRef<string[]>
  /** True once a source answered (a read that reached none is no decision: see readFailed). */
  ready: ComputedRef<boolean>
  /** The last read reached none of the sources: isMainframe reads false as the safe side, not as an answer. */
  readFailed: ComputedRef<boolean>
  /** Force a re-fetch (e.g., after impersonation switch). */
  refetch: () => Promise<void>
}

export function useMainframe(): UseMainframeReturn {
  _ensureFetched()

  // Until first fetch returns, _isMainframe is null — `isMainframe` returns
  // FALSE during that brief window. Components that care about the loading
  // state should consult `ready` instead.
  const isMainframe = computed(() => _isMainframe.value === true)
  const tier = computed(() => _tierRaw.value)
  const signals = computed(() => _signalsSeen.value)
  const ready = computed(() => _fetched.value)
  const readFailed = computed(() => _readFailed.value)

  async function refetch(): Promise<void> {
    _fetched.value = false
    _fetchPromise.value = _doFetch()
    await _fetchPromise.value
  }

  return { isMainframe, tier, signals, ready, readFailed, refetch }
}
