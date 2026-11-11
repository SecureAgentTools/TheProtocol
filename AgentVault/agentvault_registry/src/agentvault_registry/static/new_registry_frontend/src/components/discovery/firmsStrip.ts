/**
 * V0658 (v), item 2 (the maintainer's review, sessions' room seq 2181: "you cant filter out firms"): the control in
 * Discovery's filters that hides the Firms strip.
 *
 * Remembered like the frame filter, in the address (`firms=hide`), so a reload, Back and a shared link agree with the
 * screen; and kept in this browser, so a strip a person hid stays hidden on the next visit. A visit is not a choice
 * (services/uiMode.ts, §POCKETBRIDGE2): arriving on a link that says `firms=hide` hides the strip for that view and
 * leaves what this browser keeps alone. The address decides on arrival (`hide` or `show`), else the kept choice.
 *
 * The review of 4914af776: an ask for one firm (`firm`, the voice door "hire the firm X") shows the strip for that view,
 * since the lane it opens is the strip; hiding the strip drops a pending ask (or the next arrival would show it again);
 * and where Discovery is mounted inside another page (the landing page's embedded preview) the kept choice is read and
 * the address is neither read nor written.
 */
import { onMounted, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export const FIRMS_HIDDEN_KEY = 'tp_disc_firms_hidden'

export interface FirmsStripOptions {
  /** false where the view is mounted inside another page: the kept choice is read, the address is never touched */
  address?: boolean
}

/** Pure: whether the strip starts hidden, from the address's `firms`, what this browser kept, and an ask for one firm
 *  in the address (`firm`): an ask shows the strip for that view, whatever the address or the browser says. */
export function firmsHiddenOnArrival(param: unknown, stored: string | null, asked?: unknown): boolean {
  if (typeof asked === 'string' && asked.trim()) return false
  if (param === 'hide') return true
  if (param === 'show') return false
  return stored === '1'
}

function kept(): string | null {
  try { return localStorage.getItem(FIRMS_HIDDEN_KEY) } catch { return null }
}

function keep(hidden: boolean): void {
  try {
    if (hidden) localStorage.setItem(FIRMS_HIDDEN_KEY, '1')
    else localStorage.removeItem(FIRMS_HIDDEN_KEY)
  } catch { /* storage unavailable: the address still carries it */ }
}

export function useFirmsStrip(opts: FirmsStripOptions = {}): { hidden: Ref<boolean>; setHidden: (v: boolean) => void } {
  const route = useRoute()
  const router = useRouter()
  const inAddress = opts.address !== false
  const hidden = ref(inAddress ? firmsHiddenOnArrival(route.query.firms, kept(), route.query.firm) : kept() === '1')

  /** The address says what the screen shows (the rest of the query, the frame filter's among it, is kept). Hiding the
   *  strip also drops a pending ask for one firm, which would show it again on the next arrival. */
  function syncAddress(v: boolean) {
    if (!inAddress) return
    const q = route.query
    const dropAsk = v && q.firm !== undefined
    if ((v ? q.firms === 'hide' : q.firms === undefined) && !dropAsk) return
    const next: Record<string, any> = { ...q }
    if (v) next.firms = 'hide'
    else delete next.firms
    if (dropAsk) delete next.firm
    router.replace({ query: next }).catch(() => { /* a newer navigation won */ })
  }

  /** A person's choice: shown or hidden, kept in this browser and in the address. */
  function setHidden(v: boolean) {
    hidden.value = v
    keep(v)
    syncAddress(v)
  }

  if (inAddress) {
    // a choice kept from an earlier visit is stated in the address too (not a new choice, so nothing else is written)
    onMounted(() => { if (hidden.value && route.query.firms !== 'hide') syncAddress(true) })

    // the address changed under the same view (vue-router reuses it: a link followed, Back, the sidebar's own entry): it
    // decides again the way an arrival does, and a kept choice is stated again where the new address leaves it out
    watch(() => route.query.firms, (param) => {
      const next = firmsHiddenOnArrival(param, kept(), route.query.firm)
      if (next !== hidden.value) hidden.value = next
      if (hidden.value && param !== 'hide') syncAddress(true)
    })

    // an ask for one firm arriving under the same view shows the strip; the lane consuming the ask (it scrubs `firm`
    // once it has read it) leaves the strip shown in this view
    watch(() => route.query.firm, (asked) => {
      if (hidden.value && typeof asked === 'string' && asked.trim()) hidden.value = false
    })
  }

  return { hidden, setHidden }
}
