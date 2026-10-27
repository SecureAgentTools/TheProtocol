/**
 * services/exchange/federationTickers.ts — §MCFOLD (2026-09-02)
 *
 * ONE poll of `/agora/federation-tickers` for every strip that shows it. The endpoint
 * takes 7-11 s on this network, so two strips polling it separately would double a slow
 * call; a refcounted feed polls while at least one consumer is mounted and stops when
 * the last one leaves (a folded strip is not a consumer). Same-origin only: the registry
 * aggregates the federation server-side (the §V-1r doctrine).
 */
import { computed, ref } from 'vue'
import { apiClient } from '@/services/api/client'

export interface TickListing { symbol: string; display_name?: string; last: string | null; change_24h_pct: string | null; status: string; currency: string }
export interface TickTrade { symbol: string; price: string; qty: number; at: string }
export interface TickVenue { venue: string; currency: string; listings: TickListing[]; trades: TickTrade[] }

export const FEDERATION_TICKERS_POLL_MS = 20_000

const venuesRaw = ref<TickVenue[]>([])
const loadedOnce = ref(false)
/** §FRESHFRAME (2026-09-14): the last failed poll's message, null after a good one. An empty answer and a
 *  failed one used to collapse into `[]`; a strip that then renders nothing cannot say which. */
const lastError = ref<string | null>(null)
let consumers = 0
let timer: ReturnType<typeof setInterval> | undefined
let inflight: Promise<void> | null = null

async function refresh(): Promise<void> {
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const { data } = await apiClient.get('/agora/federation-tickers')
      venuesRaw.value = (data?.venues || []).filter((v: TickVenue) => v.listings?.length)
      lastError.value = null
    } catch (e: any) {
      venuesRaw.value = []   // endpoint absent (pre-V0064 registry) or unreachable: the strip says so (§FRESHFRAME)
      lastError.value = String(e?.message || e || 'error')
    } finally {
      loadedOnce.value = true
      inflight = null
    }
  })()
  return inflight
}

export function useFederationTickers() {
  return {
    venues: computed(() => venuesRaw.value),
    loadedOnce,
    lastError: computed(() => lastError.value),
    refresh,
    join(): void {
      consumers++
      if (consumers === 1) {
        void refresh()
        timer = setInterval(() => { void refresh() }, FEDERATION_TICKERS_POLL_MS)
      }
    },
    leave(): void {
      consumers = Math.max(0, consumers - 1)
      if (consumers === 0 && timer) { clearInterval(timer); timer = undefined }
    },
  }
}

/** Test seam only. */
export const __federationTickersInternals = {
  get consumers() { return consumers },
  get polling() { return timer !== undefined },
  reset(): void { consumers = 0; if (timer) clearInterval(timer); timer = undefined; venuesRaw.value = []; loadedOnce.value = false; lastError.value = null; inflight = null },
}
