/**
 * §FEFRAME W2 — the frame manifest, fetched ONCE per page, before routing.
 *
 * The manifest rides the public registry-config the console already reads (useRegistryConfig), so this adds no
 * request: one fetch, one promise, every reader. The router waits for it with a 4 s bound (`whenFrameManifest`);
 * past the bound the console runs in an honest "identity unknown" state: no unit is guessed, no peer is invented,
 * and the readers fill in when the answer arrives. A registry that predates the manifest (no `self` in the
 * config) stays in that state for the life of the page: its console runs, and says nothing about frames it does not
 * know.
 */
import { computed, shallowRef } from 'vue'
import { loadRegistryConfig, onRegistryConfigRead, useRegistryConfig } from '@/composables/useRegistryConfig'
import { framesOf, ledgersOf, manifestFrom, entryByTrustDomain, entryByKey, frameOf, currencyNames,
  type FrameEntry, type FrameManifest } from '@/services/frameManifest'
import { registerCurrencyNames } from '@/config/currencies'
import { setFramesFromManifest } from '@/config/frames'

const _manifest = shallowRef<FrameManifest | null>(null)
const _settled = shallowRef(false)          // the config answered (with or without a manifest), or failed
let _pending: Promise<FrameManifest | null> | null = null
const _listeners = new Set<(m: FrameManifest) => void>()

function adopt(cfg: any): FrameManifest | null {
  const m = manifestFrom(cfg)
  if (m) {
    _manifest.value = m
    registerCurrencyNames(currencyNames(m))
    setFramesFromManifest(m)          // plain modules (the ledger stream, the grammar) read FRAMES
    for (const cb of _listeners) { try { cb(m) } catch { /* one listener must not stop the others */ } }
  }
  _settled.value = true
  return m
}

// §FESUITE (2026-10-04): a failed config read settled the manifest as "unknown" for the life of the page; the config is
// read again after a failure now, and a read that answers brings the manifest in (the readers fill in, as designed)
onRegistryConfigRead((cfg) => { if (!_manifest.value) adopt(cfg) })

/** Called once the manifest lands (at once if it already has). For plain modules that cannot watch a ref. */
export function onFrameManifest(cb: (m: FrameManifest) => void): void {
  _listeners.add(cb)
  if (_manifest.value) { try { cb(_manifest.value) } catch { /* ignore */ } }
}

export function loadFrameManifest(): Promise<FrameManifest | null> {
  if (_settled.value) return Promise.resolve(_manifest.value)
  if (!_pending) _pending = loadRegistryConfig().then(adopt, () => adopt(null)).finally(() => { _pending = null })
  return _pending
}

/** Resolves with the manifest, or null after `ms` (the console then renders its identity-unknown state). */
export function whenFrameManifest(ms = 4000): Promise<FrameManifest | null> {
  let timer: ReturnType<typeof setTimeout> | undefined
  return Promise.race([
    loadFrameManifest(),
    new Promise<null>((res) => { timer = setTimeout(() => res(null), ms) }),
  ]).finally(() => { if (timer) clearTimeout(timer) })
}

/** This registry's own settlement currency from the manifest ('' while unknown: never another frame's unit). Reading
 *  it inside a computed makes that computed follow the manifest. */
export function currentOwnCurrency(): string {
  return _manifest.value?.self?.currency || ''
}

/** The manifest now (null until it arrives or on an older registry). Non-reactive; for plain modules. */
export function currentFrameManifest(): FrameManifest | null {
  return _manifest.value
}

export function useFrameManifest() {
  if (!_settled.value && !_pending) void loadFrameManifest()
  useRegistryConfig()   // the same promise; keeps the config readers in step
  const manifest = computed(() => _manifest.value)
  const self = computed<FrameEntry | null>(() => _manifest.value?.self ?? null)
  return {
    manifest,
    /** true once the config answered (a manifest or not); false while the first fetch is in flight */
    settled: computed(() => _settled.value),
    /** the manifest is here and names this registry */
    known: computed(() => !!_manifest.value),
    self,
    peers: computed<FrameEntry[]>(() => _manifest.value?.peers ?? []),
    frames: computed<FrameEntry[]>(() => (_manifest.value ? framesOf(_manifest.value) : [])),
    /** this console's frame: itself, or an operator's parent */
    ownFrame: computed<FrameEntry | null>(() => (_manifest.value ? frameOf(_manifest.value, _manifest.value.self) : null)),
    ledgers: computed(() => (_manifest.value ? ledgersOf(_manifest.value) : [])),
    multiFrame: computed(() => !!_manifest.value?.multi_frame),
    byTrustDomain: (td: string | null | undefined) => (_manifest.value ? entryByTrustDomain(_manifest.value, td) : null),
    byKey: (k: string | null | undefined) => (_manifest.value ? entryByKey(_manifest.value, k) : null),
  }
}
