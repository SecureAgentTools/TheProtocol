// useFrames — "what frames exist, which one am I, and what currency does a trust_domain use", from the FRAME
// MANIFEST (§FEFRAME W2): GET /api/v1/public/registry-config, `self` + `peers[]`, one resolver on the server
// (core/federation_view.py) over the peer rows federation admitted and the cards it verified.
//
// Before W2 the frame list was a static seed of the retired A/B/C frames with a substring family match on top, so
// EU, ASIA and every operator resolved to NO local frame and the sandbox pair to "Frame A" / "Frame B"; the unit
// came from a race between the config and the signed card and fell back to the literal 'AVT'. Now:
//   - frames = the manifest's frames (own frame first), EMPTY until it arrives;
//   - localFrame = this console's frame (itself; an operator's parent);
//   - localCurrency = the server's word (self.currency, else the config's local_currency), '' while unknown: never
//     another frame's unit;
//   - a trust domain's currency comes from the manifest entry that carries it (positive evidence only).
// The signed card is still read once, for the local FX block (fees.fx) the manifest does not carry.
//
// Currency is FRAME-LEVEL: knownCurrencyForTrustDomain() answers only with positive evidence; currencyForTrustDomain()
// falls back to the viewer's own currency (no false "foreign" badges). Strategy §18.2.

import { ref, computed } from 'vue'
import { useFrameManifest, loadFrameManifest } from '@/composables/useFrameManifest'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { framesFromManifest, frameByTrustDomain, type FrameDescriptor, type FrameKey } from '@/config/frames'
import type { CurrencyCode } from '@/config/currencies'

const _localFx = ref<Record<string, unknown> | null>(null)
let _cardRead: Promise<void> | null = null

async function _readLocalFx(): Promise<void> {
  try {
    const ctrl = new AbortController()
    // 30 s: a cold first card build measured 30.0 s on EU (§MODALPASS1); nothing waits on this, it only fills localFx
    const timer = setTimeout(() => ctrl.abort(), 30000)
    let resp: Response
    try { resp = await fetch('/.well-known/registry-card.json', { credentials: 'same-origin', cache: 'no-store', signal: ctrl.signal }) }
    finally { clearTimeout(timer) }
    if (!resp.ok) return
    const card = await resp.json()
    const fx = card?.fees?.fx
    if (fx && typeof fx === 'object') _localFx.value = fx as Record<string, unknown>
  } catch { /* fail-soft: no FX block shown */ }
}

export function useFrames() {
  const fm = useFrameManifest()
  const { config } = useRegistryConfig()
  if (!_cardRead) _cardRead = _readLocalFx()

  function ensureLoaded(): Promise<void> {
    return loadFrameManifest().then(() => undefined)
  }

  const frames = computed<FrameDescriptor[]>(() => (fm.manifest.value ? framesFromManifest(fm.manifest.value) : []))
  const localFrame = computed<FrameDescriptor | null>(() => {
    const own = fm.ownFrame.value
    return own ? (frames.value.find(f => f.key === own.key) ?? null) : null
  })
  const localCurrency = computed<CurrencyCode>(() =>
    fm.self.value?.currency || (config.value.local_currency || '').toUpperCase() || '')
  const localFx = computed(() => _localFx.value)
  const localFrameKey = computed<FrameKey | null>(() => localFrame.value?.key ?? null)
  /** This registry's own display name as its manifest states it (null until it arrives). */
  const localRegistryName = computed<string | null>(() => fm.self.value?.display_name || config.value.registry_name || null)
  const localTrustDomain = computed<string | null>(() => fm.self.value?.trust_domain || config.value.trust_domain || null)

  /** Currency for a trust_domain IFF the manifest names one (a frame's, or an operator's own); else null. */
  function knownCurrencyForTrustDomain(td: string | null | undefined): CurrencyCode | null {
    const e = fm.byTrustDomain(td)
    if (e?.currency) return e.currency
    const f = frameByTrustDomain(frames.value, td)
    return f?.currency || null
  }
  /** Currency for a trust_domain; unknown → the viewer's own currency. */
  function currencyForTrustDomain(td: string | null | undefined): CurrencyCode {
    return knownCurrencyForTrustDomain(td) || localCurrency.value
  }

  // The frames whose FX the console can show: this frame when its card says FX is on (the peers' FX posture is not
  // in the manifest, and a corridor is never guessed).
  const fxCorridors = computed(() => {
    const fx: any = _localFx.value
    const on = !!(fx && (fx.enabled || fx.route_enabled))
    return on && localFrame.value ? [localFrame.value] : []
  })

  return {
    ensureLoaded,
    frames,
    localFrame,
    localFrameKey,
    localRegistryName,
    localCurrency,
    localFx,
    localTrustDomain,
    knownCurrencyForTrustDomain,
    currencyForTrustDomain,
    fxCorridors,
  }
}
