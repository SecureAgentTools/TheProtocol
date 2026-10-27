// useActingContext — WHERE the agent you are acting as actually lives, and what
// its money is called there.
//
// §FOREIGNACT (2026-08-24), from the Commander's own test. He acted as SYBIL
// (homed registry-a, AVT) from the frame-c surface. The send was correct to the
// last decimal — 1.000000 AVT left SYBIL, 1.175029 BVT reached Trader Tilly — but
// the screen said BVT throughout, and the stake he entered as "1.337" locked
// 1337.000000 AVT on registry-a. Routing followed the AGENT; labelling followed
// the PAGE.
//
// The routing half is deliberate and stays (§BRIDGE R11 #12): the api client
// rewrites every agent-tier request to `authStore.activeAgentRegistryUrl`,
// because the agent JWT was minted BY that registry and the token and the address
// must travel together. This composable is the other half of that seam — the same
// fact, told to the human.
//
// ── THE RULE THAT MATTERS ──
// For a foreign agent, `actingCurrency` is NULL until that registry's own signed
// card has answered. It NEVER falls back to the viewer's currency, because the
// viewer's currency is precisely the wrong answer: falling back is how "BVT"
// ended up over an AVT amount. Surfaces render `actingCurrencyLabel`, which is an
// empty string while unknown — an amount with no unit is honest; an amount with
// the wrong unit is not.

import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useFrames } from '@/composables/useFrames'
import type { CurrencyCode } from '@/config/currencies'

interface RegistryFacts {
  currency: CurrencyCode | null
  name: string | null
  /** false when the card could not be read — we know the host and nothing else. */
  ok: boolean
}

/** origin → facts. Module-level: one fetch per registry per page load. */
const _facts = ref<Record<string, RegistryFacts>>({})
const _inflight = new Map<string, Promise<void>>()

/**
 * Read a peer registry's OWN signed card for its settlement currency and name.
 * Every registry serves this publicly and cross-origin (verified 2026-08-24:
 * `access-control-allow-origin: *` on registry-a and the cloud-ops), so this
 * needs no relay, no admin rail and no new endpoint — the same argument
 * §FOREIGNDEV made for going direct.
 */
async function _loadRegistryFacts(origin: string): Promise<void> {
  if (_facts.value[origin]) return
  const existing = _inflight.get(origin)
  if (existing) return existing
  const p = (async () => {
    let facts: RegistryFacts = { currency: null, name: null, ok: false }
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 6000)
      let resp: Response
      try {
        resp = await fetch(`${origin}/.well-known/registry-card.json`, { cache: 'no-store', signal: ctrl.signal })
      } finally { clearTimeout(timer) }
      if (resp.ok) {
        const card = await resp.json()
        const cur = card?.fees?.settlement_currency
        const name = card?.identity?.display_name || card?.identity?.registry_name
        facts = {
          currency: (typeof cur === 'string' && cur) ? (cur as CurrencyCode) : null,
          name: (typeof name === 'string' && name.trim()) ? name.trim() : null,
          ok: true,
        }
      }
    } catch {
      /* fail-soft: ok stays false, currency stays null — never guessed */
    }
    _facts.value = { ..._facts.value, [origin]: facts }
    _inflight.delete(origin)
  })()
  _inflight.set(origin, p)
  return p
}

/**
 * Facts about ANY registry, by origin — for surfaces that list agents from
 * several registries at once (the agent picker, where you CHOOSE the foreign
 * agent and so the earliest honest moment to say what its money is called).
 *
 * `currencyFor` is PURE: it reads the module cache and returns '' when the
 * answer is not in yet. Fetching is an explicit `ensureFor(urls)` a component
 * calls from a watcher — resolving lazily inside a render is how you get a
 * fetch storm and a render-during-render warning.
 *
 * Shares the cache with the acting-agent path above, so a fleet spread over
 * three registries costs three requests per page, not three per row.
 */
export function useRegistryFacts() {
  const { localCurrency, localRegistryName } = useFrames()

  /** null = "this origin" (local). Anything unparseable is treated as local. */
  function foreignOriginOf(url?: string | null): string | null {
    if (!url || typeof url !== 'string') return null
    try {
      const o = new URL(url).origin
      if (typeof window !== 'undefined' && o === window.location.origin) return null
      return o
    } catch { return null }
  }

  function ensureFor(urls: Array<string | null | undefined>): void {
    const seen = new Set<string>()
    for (const u of urls) {
      const o = foreignOriginOf(u)
      if (o && !seen.has(o)) { seen.add(o); void _loadRegistryFacts(o) }
    }
  }

  /** '' while a foreign registry's card has not answered — never the local unit. */
  function currencyFor(url?: string | null): string {
    const o = foreignOriginOf(url)
    if (!o) return localCurrency.value
    return _facts.value[o]?.currency || ''
  }

  function nameFor(url?: string | null): string {
    const o = foreignOriginOf(url)
    if (!o) return localRegistryName.value || ''
    const f = _facts.value[o]
    if (f?.name) return f.name
    try { return new URL(o).hostname } catch { return o }
  }

  function isForeign(url?: string | null): boolean { return !!foreignOriginOf(url) }

  return { ensureFor, currencyFor, nameFor, isForeign, foreignOriginOf }
}

export function useActingContext() {
  const auth = useAuthStore() as any
  const { localCurrency, localRegistryName } = useFrames()

  /** The agent whose authority every agent-tier call currently carries. */
  const actingAgent = computed<any>(() => auth.activeAgent ?? null)

  /**
   * The origin agent-tier requests are being sent to, or null for a local agent.
   * Read from the SAME store field the api client uses to rewrite the base URL,
   * so the label and the route can never disagree about which registry this is.
   */
  const actingOrigin = computed<string | null>(() => auth.activeAgentRegistryUrl ?? null)

  const isForeign = computed<boolean>(() => !!actingOrigin.value)

  const actingHost = computed<string>(() => {
    const o = actingOrigin.value
    if (!o) return typeof window !== 'undefined' ? window.location.hostname : ''
    // §BLOGREFINE: `URL.host` carries the PORT. It is `hostname` we want to show.
    try { return new URL(o).hostname } catch { return o }
  })

  watch(actingOrigin, (o) => { if (o) void _loadRegistryFacts(o) }, { immediate: true })

  const _foreignFacts = computed<RegistryFacts | null>(() => {
    const o = actingOrigin.value
    return o ? (_facts.value[o] ?? null) : null
  })

  /** True once we can name the acting agent's currency (always true when local). */
  const actingResolved = computed<boolean>(() =>
    !isForeign.value || !!_foreignFacts.value?.currency)

  /**
   * The currency the acting agent's money is denominated in.
   * NULL for a foreign agent whose card has not answered — deliberately, so a
   * caller cannot accidentally render the viewer's currency over a foreign
   * amount. That substitution is the whole defect this composable exists for.
   */
  const actingCurrency = computed<CurrencyCode | null>(() =>
    isForeign.value ? (_foreignFacts.value?.currency ?? null) : localCurrency.value)

  /** Safe for templates: '' rather than a wrong unit. */
  const actingCurrencyLabel = computed<string>(() => actingCurrency.value || '')

  /** Human name of the registry the action will land on. */
  const actingRegistryName = computed<string>(() => {
    if (!isForeign.value) return localRegistryName.value || actingHost.value
    return _foreignFacts.value?.name || actingHost.value
  })

  /** True when the acting agent settles in a different currency than this page shows. */
  const currencyDiffersFromPage = computed<boolean>(() =>
    isForeign.value && !!actingCurrency.value && actingCurrency.value !== localCurrency.value)

  /**
   * One sentence for a money moment. Empty for a local agent — a notice that
   * fires on every action is a notice nobody reads.
   */
  const actingNotice = computed<string>(() => {
    if (!isForeign.value) return ''
    const who = actingAgent.value?.name || 'this agent'
    const where = actingRegistryName.value
    const ccy = actingCurrency.value
    if (!ccy) {
      return `${who} lives on ${where} (${actingHost.value}). This action runs there, not on the registry you are viewing, and its currency could not be read.`
    }
    return `${who} lives on ${where} (${actingHost.value}). This action runs there and settles in ${ccy}, not ${localCurrency.value}.`
  })

  /** Short form for inline chips next to an amount. */
  const actingShortNotice = computed<string>(() =>
    isForeign.value ? `on ${actingRegistryName.value}` : '')

  return {
    actingAgent, actingOrigin, isForeign, actingHost,
    actingCurrency, actingCurrencyLabel, actingResolved,
    actingRegistryName, currencyDiffersFromPage,
    actingNotice, actingShortNotice,
    localCurrency,
  }
}
