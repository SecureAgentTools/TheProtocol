/**
 * §COCKPIT P1 (2026-08-31) — ONE read of the public registry config.
 *
 * WHY a composable and not another `fetch`: six views in this tree each fetch
 * `/api/v1/public/registry-config` on their own. That is fine when one view
 * needs one field. The desk is different — its ROUTER GUARD and its SIDEBAR
 * ENTRY must agree about whether the desk exists, and two independent fetches
 * can disagree (one in flight, one resolved) for exactly as long as it takes a
 * user to see a nav item that routes to a redirect. They agree here because
 * they read the same promise.
 *
 * The promise is cached at module scope, so N callers cost ONE request. A
 * failed fetch resolves to `{}` and every flag reads false — locked/hidden is
 * the safe direction for a feature flag, and it is the honest one for a config
 * we could not read.
 *
 * §FESUITE (2026-10-04): but a failed read is not the registry's ANSWER. It was cached as one for the session (loaded,
 * never read again), so a console that booted while the API failed (the database or pool down, the static files still
 * served) hid those features and said "switched off" until someone reloaded. Now: `readOk` says the config is the
 * registry's own answer and `readFailed` that the read settled without one (say neither "on" nor "off" then); a caller
 * reads again once RETRY_GAP_MS has passed since the failure, and with nobody asking the composable reads again on its
 * own, backing off (BACKOFF_MS). `config` stays one reactive ref, so a read that answers later updates every computed
 * gate in place; a field a failed read cannot supply (registry_name, the manifest) stays absent. A 404 is an answer:
 * a registry without the route, every field at its documented default.
 */
import { ref, computed, type Ref } from 'vue'
import type { FrameEntry } from '@/services/frameManifest'

export interface RegistryConfig {
  is_federated_operator?: boolean
  registry_name?: string
  fx_enabled?: boolean
  multi_frame?: boolean
  fiat_onramp_enabled?: boolean
  /** §BAFIN (2026-10-01) — can a staking position be opened here (STAKING_ENABLED)? False hides every staking door.
   *  Absent (an older registry) reads as on, so only a registry that says false loses the surfaces. */
  staking_enabled?: boolean
  /** §BAFIN — is a staking rate published and paid here (STAKING_REWARDS_ENABLED)? False hides every rate,
   *  projected reward and reward tab; positions may still be opened for governance weight. */
  staking_rewards_enabled?: boolean
  /** §BAFIN — may AGORA distributions be declared here (core/agora_gate.py)? Absent = on. */
  agora_distributions_enabled?: boolean
  /** D6-841 — is the Phone Fabric on here (PHONE_FABRIC_ENABLED; its rails answer 503 without it)? Absent (an older
   *  registry) is asked as before. */
  phone_fabric_enabled?: boolean
  flare_local_purchase_enabled?: boolean
  /** The frame's native settlement currency (BVT on frame-c, AVT on rega, JDAY on frame-b). */
  local_currency?: string
  /** §COCKPIT — is the Cockpit Desk live on this registry? Default false. */
  cockpit_desk_enabled?: boolean
  /** §WALLETAGENT — what the registry grants a developer's first agent (string amount on the wire). */
  genesis_grant_enabled?: boolean
  genesis_grant_amount?: string
  /** §DIRFEED — the federated INDEX this console may offer beside its own discovery. Empty/false = no Directory
   *  was configured here, and nothing about the page changes. The index finds; the home registry decides. */
  directory_url?: string
  directory_discovery_enabled?: boolean
  /** §SHOWCASEGATE — can the OurChat showcase panel actually work on this frame? False on a frame
   *  with no showcase identity of its own (its service calls still work — they relay). */
  showcase_chat_enabled?: boolean
  /** §FRESHFRAME — this frame's SPIFFE trust domain (the card's identity.trust_domain), so a code sample
   *  on the front door names THIS frame and never the flagship's. Empty on an older registry. */
  trust_domain?: string
  /** §HELLOFRAME — the applicant's frame page (/frame-kit) and its kit download. Default false. */
  frame_kit_enabled?: boolean
  /** §FEFRAME W3 — can the simulation console run here (ADMIN_SIMULATION_ENABLED)? Absent (an older registry) reads true,
   *  so the EigenTrust entry only disappears where the server says it cannot work. */
  simulation_enabled?: boolean
  /** §HELLOFRAME ("Ship without it") — does this frame carry the journal? True where the served console holds the
   *  journal's media; an export frame ships none. Absent (an older registry) or unreadable reads false. */
  journal_enabled?: boolean
  /** §FEFRAME W2 — the FRAME MANIFEST (core/federation_view.py): who this registry is and who its federation peers
   *  are. Read through composables/useFrameManifest.ts; `manifest_version` 0 = the server could not build one. */
  manifest_version?: number
  self?: FrameEntry
  peers?: FrameEntry[]
  /** §MEMBERSHIP (2026-10-02) — `lock` (today: locked Units, veToken) or `member` (one vote per member developer,
   *  weighted by tenure). Absent (every registry before the membership image) reads as `lock`: read it through
   *  services/membership/membership.ts::governanceMode, never directly. */
  governance_weight_mode?: 'lock' | 'member'
  /** §MEMBERSHIP — whether binding votes need a step-up (`off` | `conditional` | `required`). Absent reads as `off`. */
  governance_presence_mode?: 'off' | 'conditional' | 'required'
  /** §MEMBERSHIP — the commons routes answer here. Absent reads as false. */
  commons_enabled?: boolean
  /** §MEMBERSHIP D2 — federation proposals here are decided by one ballot per registry. Absent reads as false. */
  federation_ballot_mode?: boolean
  /** §FESUITE (2026-10-10, the operator batch: "operators will choose what they want to run") — liability mandates here
   *  (LIABILITY_MODE). Where it says `off` the Cockpit Card's routes answer 404 and the console does not ask them
   *  (services/api/liability.ts). Absent (an older registry) asks as before. */
  liability_mode?: 'off' | 'shadow' | 'enforce'
  /** §FESUITE — the contract template library runs here (CONTRACT_TEMPLATES_ENABLED; its routes answer 503 where off).
   *  Absent reads as on (asks as before). */
  contract_templates_enabled?: boolean
  /** §FESUITE — the sandbox registries this registry's /sandbox/{a,b} proxy reaches (an empty list: none, the proxy
   *  answers 503). Absent (an older registry) means unknown: ask as before. */
  sandbox_proxy?: string[]
}

const cfg: Ref<RegistryConfig> = ref({})
/** settled: a read answered, or a read failed (a view waiting for a verdict goes on, closed) */
const loaded = ref(false)
/** the last read ANSWERED: the config is the registry's own, not the fail-closed `{}` */
const readOk = ref(false)
let inflight: Promise<RegistryConfig> | null = null
let failedAt = 0
let failures = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
const readListeners = new Set<(c: RegistryConfig) => void>()
/** After a failed read, a caller reads again once this long has passed: one read in flight, one per gap, never a storm. */
export const RETRY_GAP_MS = 2000
/** With nobody asking, the composable reads again on its own after a failure, backing off. */
export const BACKOFF_MS = [5_000, 10_000, 20_000, 40_000, 60_000]

function wantsRead(): boolean {
  if (inflight) return false
  if (!loaded.value) return true
  return !readOk.value && Date.now() - failedAt >= RETRY_GAP_MS
}

function scheduleRetry(): void {
  if (retryTimer || readOk.value) return
  const ms = BACKOFF_MS[Math.min(failures - 1, BACKOFF_MS.length - 1)]
  retryTimer = setTimeout(() => { retryTimer = null; if (!readOk.value) void loadRegistryConfig() }, ms)
}

/** The shared read. `force` (a person's Try again) skips the gap after a failure; a read in flight is always joined. */
export function loadRegistryConfig(force = false): Promise<RegistryConfig> {
  if (inflight) return inflight
  if (!force && !wantsRead()) return Promise.resolve(cfg.value)
  inflight = fetch(`${window.location.origin}/api/v1/public/registry-config`, { cache: 'no-store' })
    .then((r) => {
      // a registry without the route answers "no config": every field reads its documented default
      if (r.status === 404) return {}
      if (!r.ok) throw new Error(`registry-config answered ${r.status}`)
      return r.json()
    })
    .then((d: RegistryConfig) => {
      cfg.value = d || {}
      readOk.value = true
      loaded.value = true
      failures = 0
      if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
      for (const cb of readListeners) { try { cb(cfg.value) } catch { /* one listener must not stop the others */ } }
      return cfg.value
    })
    .catch(() => {
      // closed (every flag false) but never kept as the answer: a later caller, or the retry, reads again; a read that
      // answered before is kept (a failed re-read does not take a good config away)
      if (!readOk.value) cfg.value = {}
      failedAt = Date.now()
      loaded.value = true
      failures += 1
      scheduleRetry()
      return cfg.value
    })
    .finally(() => { inflight = null })
  return inflight
}

/** The config for a plain module (a service gate): joins the shared read, but waits at most `ms` for it. A slow or
 *  failed read yields what is known (`{}` before any answer), so the gate asks as before rather than holding a call. */
export function registryConfigWithin(ms = 2500): Promise<RegistryConfig> {
  let timer: ReturnType<typeof setTimeout> | null = null
  const late = new Promise<RegistryConfig>((resolve) => { timer = setTimeout(() => resolve(cfg.value), ms) })
  return Promise.race([loadRegistryConfig(), late]).finally(() => { if (timer) clearTimeout(timer) })
}

/** Called after every read that answered (at once if one already has). For plain modules that cannot watch a ref. */
export function onRegistryConfigRead(cb: (c: RegistryConfig) => void): () => void {
  readListeners.add(cb)
  if (readOk.value) { try { cb(cfg.value) } catch { /* ignore */ } }
  return () => { readListeners.delete(cb) }
}

export function useRegistryConfig() {
  if (wantsRead()) void loadRegistryConfig()
  return {
    config: computed(() => cfg.value),
    loaded: computed(() => loaded.value),
    /** the config is the registry's own answer (false while unread and after a failed read) */
    readOk: computed(() => readOk.value),
    /** the read settled without an answer: every flag reads false (closed); a page says neither "on" nor "off" */
    readFailed: computed(() => loaded.value && !readOk.value),
    localCurrency: computed(() => cfg.value.local_currency || ''),
    cockpitDeskEnabled: computed(() => cfg.value.cockpit_desk_enabled === true),
    frameKitEnabled: computed(() => cfg.value.frame_kit_enabled === true),
    simulationEnabled: computed(() => cfg.value.simulation_enabled !== false),
    journalEnabled: computed(() => cfg.value.journal_enabled === true),
    // §DIRFEED — both halves together, because a flag without an address is a blank promise (the server
    // already refuses that combination; this is the second reader of the same rule).
    directoryUrl: computed(() => (cfg.value.directory_url || '').replace(/\/+$/, '')),
    directoryDiscoveryEnabled: computed(() =>
      cfg.value.directory_discovery_enabled === true && !!(cfg.value.directory_url || '').trim()),
    // §SHOWCASEGATE (2026-09-09) — the landing page mounts the OurChat showcase ONLY where the
    // server says the visitor rail can run. Absent/failed config reads false, which hides it:
    // for a demonstration, showing nothing beats showing something that refuses.
    showcaseChatEnabled: computed(() => cfg.value.showcase_chat_enabled === true),
    trustDomain: computed(() => (cfg.value.trust_domain || '').trim()),
    /** liability mandates run here (false only where the registry says `off`) */
    liabilityOn: computed(() => cfg.value.liability_mode !== 'off'),
    /** the contract template library runs here (false only where the registry says so) */
    contractTemplatesOn: computed(() => cfg.value.contract_templates_enabled !== false),
    /** which sandbox registries the proxy reaches: undefined while unknown (an older registry), [] for none */
    sandboxProxy: computed(() => (Array.isArray(cfg.value.sandbox_proxy) ? cfg.value.sandbox_proxy : undefined)),
    load: loadRegistryConfig,
    /** a person's Try again: reads now, whatever the gap */
    reload: () => loadRegistryConfig(true),
  }
}
