// useAdminFrames — §FEDEVENTS 2026-08-03. Single source for admin frame
// pickers (Event Ledger, Ledger Forensics, Admin FX, Admin Treasury) and cross-frame request routing.
//
//   selectable frames = [ LOCAL ] + [ the manifest's FRAMES this console holds a session on ]
//
// §FEFRAME W3 (V0504): the frames come from the frame manifest (operators never: their events live on their parent's
// store) and the sessions from the session hub. A foreign frame is read DIRECTLY at its own registry with the session
// held there (its own token, the local frame asked as `frame=local`); the admin relay is used only for a session that
// itself came in through the relay. Before W3 every foreign read went through the relay and only frames the relay's
// targets named were listed (none on the live network: its candidate keys were the literal A/B/C), so EU and ASIA
// were invisible here unless the Event Ledger had run first.
import { computed } from 'vue'
import { apiClient } from '@/services/api/client'
import { peerGet } from '@/services/api/peer'
import { useFrames } from '@/composables/useFrames'
import { useFrameManifest, loadFrameManifest } from '@/composables/useFrameManifest'
import { useSessionHub } from '@/stores/sessions'
import { describeCurrency } from '@/config/currencies'
import { LOCAL_FRAME } from '@/services/api/eventStoreAdmin'

export interface AdminFrameOption {
  /** Session/relay key — LOCAL_FRAME sentinel, a legacy letter, or a directory key. */
  key: string
  label: string
  sub: string
  /** Concrete hex for dots/glows (CSS-var accents don't work in box-shadows). */
  accentHex: string
  isLocal: boolean
  /** Value sent as ?frame= — 'local' for the viewer's own frame, the letter for
   *  legacy sibling frames (old registries resolve letters, not 'local'). */
  frameParam: string
}

const DEFAULT_HEX = '#00d2d2'
/** §FEFRAME W2: a frame's accent is its currency's derived colour, never a per-letter table of the retired frames.
 *  A CSS-variable accent cannot glow in a box-shadow, so it falls back. */
const accentOf = (a: string | undefined | null): string => (a && !a.startsWith('var(') ? a : DEFAULT_HEX)

/** Kept for its callers (the Event Ledger awaited the relay's targets before listing): now the manifest. */
async function ensureTargets(): Promise<unknown> {
  return loadFrameManifest()
}

/** Thrown when a foreign frame is selected without a console session. */
export class FrameNotConnectedError extends Error {
  frameKey: string
  constructor(frameKey: string, label: string) {
    super(
      `${label} is another frame of this federation. Sign in to it in ` +
      `Settings → Multi-Frame Console to browse its ledger here.`,
    )
    this.name = 'FrameNotConnectedError'
    this.frameKey = frameKey
  }
}

export function useAdminFrames() {
  const { localFrame, localFrameKey, localRegistryName, localCurrency } = useFrames()
  const fm = useFrameManifest()
  const hub = useSessionHub()

  const normKey = (k: string): string => String(k || '').toLowerCase()

  function optionFor(rawKey: string): AdminFrameOption {
    const key = normKey(rawKey)
    const e = fm.byKey(key)
    return {
      key,
      label: e?.display_name || e?.name || key,
      sub: e ? `frame · ${e.currency || 'unit unknown'}` : 'connected peer',
      accentHex: accentOf(e?.currency ? describeCurrency(e.currency).accent : null),
      isLocal: false,
      frameParam: LOCAL_FRAME,        // a frame's registry answers for its OWN store as `local`
    }
  }

  const localOption = computed<AdminFrameOption>(() => {
    const seed = localFrame.value
    const name = seed?.label || localRegistryName.value || 'This Registry'
    return {
      key: LOCAL_FRAME,
      label: name,
      sub: `local · ${localCurrency.value || 'unit unknown'}`,
      accentHex: accentOf(seed?.accent),
      isLocal: true,
      frameParam: LOCAL_FRAME,
    }
  })

  /** The manifest's frames (never operators) this console holds a session on, the local frame excluded. */
  const connectedFrameOptions = computed<AdminFrameOption[]>(() => {
    const frameKeys = new Set(fm.frames.value.map(e => e.key))
    return hub.connectedKeys
      .map((k: string) => normKey(k))
      .filter((k: string) => k !== normKey(localFrameKey.value || '') && frameKeys.has(k))
      .map((k: string) => optionFor(k))
  })

  /** Everything the frame picker renders: local first, then live sessions. */
  const selectableFrames = computed<AdminFrameOption[]>(() => [
    localOption.value,
    ...connectedFrameOptions.value,
  ])

  function resolveOption(key: string | null | undefined): AdminFrameOption {
    const k = (key || LOCAL_FRAME).trim()
    if (!k || k.toLowerCase() === LOCAL_FRAME) return localOption.value
    // Old bookmarks/localStorage carry the LOCAL frame's own key (or a retired letter): map to local.
    if (normKey(k) === normKey(localFrameKey.value || '') || /^[abc]$/i.test(k)) return localOption.value
    return selectableFrames.value.find((o) => o.key === normKey(k)) || optionFor(k)
  }

  const isSelectable = (key: string): boolean =>
    selectableFrames.value.some((o) => o.key === resolveOption(key).key)

  /**
   * Frame-routed GET. `path` is relative to /api/v1 (e.g. 'admin/events/search').
   * Local → this registry (frame=local). Foreign → that frame's own registry with the session held there: directly
   * (its own token) or, for a session that came in through the relay, through the relay. Throws
   * FrameNotConnectedError when there is no session (callers surface the actionable message).
   */
  async function frameGet<T = any>(
    frameKey: string,
    path: string,
    params?: Record<string, any>,
  ): Promise<T> {
    const opt = resolveOption(frameKey)
    const qp = { ...(params || {}), frame: opt.frameParam }
    const rel = `/${path.replace(/^\//, '')}`
    if (opt.isLocal) {
      const r = await apiClient.get(rel, { params: qp })
      return r.data as T
    }
    const direct = hub.registryClient(opt.key)
    if (direct) {
      const r = await direct.get(rel, { params: qp })
      return r.data as T
    }
    const tok = hub.adminTokenFor(opt.key)
    if (!tok) throw new FrameNotConnectedError(opt.key, opt.label)
    return peerGet<T>(opt.key, path, tok, qp)
  }

  return {
    localOption,
    connectedFrameOptions,
    selectableFrames,
    resolveOption,
    isSelectable,
    frameGet,
    ensureTargets,
  }
}
