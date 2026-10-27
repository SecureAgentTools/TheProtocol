<template>
  <div class="gcc" :class="{ 'gcc--mobile': vp.isMobile.value }">
    <!-- MAP STAGE — the real GalacticMap in selection mode (targeting surface) -->
    <section class="gcc-stage" data-tour="gcc-stage" @contextmenu.prevent="onStageContext" @click="ctx.open = false">
      <GalacticMap
        v-if="stageMode === 'galactic'"
        ref="mapRef"
        embedded
        selection-mode
        :busy-registry-ids="busyNodeIds"
        class="gcc-map"
        @select-registry="onSelectRegistry"
        @select-agent="onSelectAgent"
      />
      <!-- GC2-7: PLANETARY COCKPIT — AgentWorld as the targeting surface.
           Lazy-mounted (Cesium); clicks funnel into the SAME selection handlers. -->
      <component
        :is="AgentWorldCockpit"
        v-else
        class="gcc-map gcc-planet"
        :cockpit="true"
        @select-registry="onPlanetRegistry"
        @select-agent="onPlanetAgent"
      />

      <!-- GC2: stage HUD — surface toggle + the tri-frame ATOMIC Δ strip -->
      <div class="gcc-hud" data-tour="gcc-hud" @click.stop>
        <button
          class="gcc-hud-toggle"
          type="button"
          :title="stageMode === 'galactic' ? 'Switch to planetary view (AgentWorld)' : 'Switch to galactic star map'"
          @click="stageMode = stageMode === 'galactic' ? 'planetary' : 'galactic'"
        >
          <Icon :name="stageMode === 'galactic' ? 'mdi:earth' : 'mdi:star-four-points'" :size="12" />
          {{ stageMode === 'galactic' ? 'PLANET' : 'GALAXY' }}
        </button>
        <span
          v-for="s in supplyStrip" :key="`strip-${s.label}`"
          class="gcc-hud-delta"
          :class="s.delta === null ? 'gcc-hud-delta--na' : s.ok ? 'gcc-hud-delta--ok' : 'gcc-hud-delta--bad'"
          :title="s.title"
        >Δ{{ s.label }} {{ s.delta === null ? '—' : s.delta === 0 ? '0' : s.delta }}</span>
        <button
          class="gcc-hud-toggle"
          type="button"
          title="Multi-op balance reconcile — ES↔TEG drift (read-only)"
          @click.stop="reconcileOpen = true"
        >
          <Icon name="mdi:scale-balance" :size="12" />
          RECON
        </button>
      </div>

      <!-- selected-registry targeting ring (DOM overlay via screenPos projection; star map only) -->
      <div v-if="stageMode === 'galactic' && ringPos" class="gcc-sel-ring" :style="{ left: ringPos.x + 'px', top: ringPos.y + 'px' }" aria-hidden="true">
        <span class="gcc-sel-ring-pulse"></span>
      </div>
      <!-- P8: target name label riding under the ring -->
      <div v-if="stageMode === 'galactic' && ringPos && selEntry" class="gcc-sel-name" :style="{ left: ringPos.x + 'px', top: (ringPos.y + 27) + 'px' }" aria-hidden="true">
        {{ selEntry.name }}
      </div>

      <!-- P8/P9: live event ticker — any frame's EventStore stream (tabs A/B/C).
           P11: also on mobile (compact full-width bar; deck stays desktop-only). -->
      <EventTicker
        v-if="streamsReady && dir && tickerWsPath"
        :ws-path="tickerWsPath"
        :frame-labels="tickerFrameLabels"
        :frame-label="tickerLabel"
        :available-frames="tickerFrames"
        :active-frame="tickerFrame ?? undefined"
        :supply="tickerSupply"
        :highlight-key="selEntry && !selEntry.is_local ? selEntry.key : null"
        @switch-frame="(f) => { tickerFrameSel = f }"
      />

      <!-- right-click context menu (projection-based, IronhandTheatre pattern) -->
      <div v-if="ctx.open" class="gcc-ctx" :style="{ left: ctx.x + 'px', top: ctx.y + 'px' }" @click.stop>
        <div class="gcc-ctx-head">{{ ctx.nodeName }}</div>
        <button class="gcc-ctx-item" type="button" @click="ctxTarget()">
          <Icon name="mdi:crosshairs-gps" :size="12" /> Set as target
        </button>
        <button v-if="ctx.entry && !ctx.entry.is_local" class="gcc-ctx-item" type="button" @click="ctxFund()">
          <Icon name="mdi:bank-transfer" :size="12" /> Fund treasury…
        </button>
        <button v-if="ctx.entry" class="gcc-ctx-item" type="button" @click="ctxProbe()">
          <Icon name="mdi:radar" :size="12" /> Quick probe
        </button>
      </div>

      <!-- P7: Fleet Status Deck — live awareness strip in the stage's bottom space -->
      <FleetDeck
        v-if="!vp.isMobile.value"
        :directory="dir"
        :fleet="fleet"
        :treasury="treasuryBal"
        :connected-keys="connectedRemoteKeys"
        :selected-key="selEntry?.key || null"
        :busy="!!busyAction"
        :lat-hist="latHist"
        :deltas="deckDeltas"
        :restarting-keys="restartingKeysList"
        :host="host"
        :alert-count="alertHistory.length"
        @select="selectEntryFromList"
        @reconnect-all="reconnectAllSessions"
        @refresh-balances="() => void fetchAllTreasuries()"
        @toggle-alerts="alertsOpen = !alertsOpen"
      />

      <!-- GC2-5: alert history drawer (last 20 health transitions) -->
      <div v-if="alertsOpen" class="gcc-alerts" @click.stop>
        <div class="gcc-alerts-head">
          <Icon name="mdi:bell-outline" :size="12" /> HEALTH TRANSITIONS
          <button class="gcc-alerts-x" type="button" aria-label="Close" @click="alertsOpen = false"><Icon name="mdi:close" :size="12" /></button>
        </div>
        <div v-if="!alertHistory.length" class="gcc-alerts-empty">No transitions this session — fleet steady.</div>
        <ul v-else class="gcc-alerts-list">
          <li v-for="(a, i) in alertHistory" :key="`al-${a.at}-${i}`" class="gcc-alerts-row">
            <span class="gcc-alerts-t">{{ fmtAlertTime(a.at) }}</span>
            <span class="gcc-alerts-k">{{ a.key }}</span>
            <span class="gcc-alerts-tr" :class="a.to === 'up' ? 'gcc-alerts-tr--up' : 'gcc-alerts-tr--down'">{{ a.from }} → {{ a.to }}</span>
            <span v-if="a.durMs" class="gcc-alerts-d">{{ fmtDur(a.durMs) }} down</span>
          </li>
        </ul>
      </div>

      <!-- mobile bridge toggle -->
      <button v-if="vp.isMobile.value" class="gcc-fab" type="button" aria-label="Open command bridge" @click="bridgeOpen = !bridgeOpen">
        <Icon name="mdi:radar" :size="18" />
      </button>
    </section>

    <!-- mobile backdrop -->
    <div v-if="vp.isMobile.value && bridgeOpen" class="gcc-backdrop" @click="bridgeOpen = false"></div>

    <!-- BRIDGE PANEL -->
    <aside class="gcc-bridge" data-tour="gcc-bridge" :class="{ 'gcc-bridge--mobile': vp.isMobile.value, 'gcc-bridge--open': bridgeOpen }">
      <header class="gcc-bridge-head">
        <div class="gcc-id">
          <Icon name="mdi:radar" :size="14" class="gcc-id-ic" />
          <div>
            <div class="gcc-id-t">GALACTIC COMMAND</div>
            <div class="gcc-id-s">{{ dir?.local_key || '…' }}</div>
          </div>
        </div>
        <button v-if="vp.isMobile.value" class="gcc-close" type="button" aria-label="Close bridge" @click="bridgeOpen = false">
          <Icon name="mdi:close" :size="14" />
        </button>
      </header>

      <!-- GC2-6: recent targets — one-click rebind (session-only) -->
      <div v-if="recentEntries.length > 1" class="gcc-recents">
        <span class="gcc-recents-k"><Icon name="mdi:history" :size="11" /></span>
        <button
          v-for="e in recentEntries" :key="`rc-${e.key}`"
          class="gcc-recent-chip"
          :class="{ 'gcc-recent-chip--on': selEntry?.key === e.key }"
          type="button"
          :title="`Retarget ${e.name}`"
          @click="selectEntryFromList(e)"
        >{{ e.key }}</button>
      </div>

      <div class="gcc-bridge-body" data-tour="gcc-fleet">
        <p v-if="loadError" class="gcc-error">{{ loadError }}</p>

        <div v-if="selRawNode && !selEntry && !selAgent" class="gcc-unmatched">
          <Icon name="mdi:alert" :size="13" />
          Node “{{ selRawNode }}” isn't in this registry's directory — observe-only.
          <button class="gcc-unmatched-x" type="button" @click="selRawNode = null">dismiss</button>
        </div>

        <AgentConsole
          v-if="selAgent"
          :agent="selAgent"
          :home-entry="selAgentHome"
          :local-key="dir?.local_key || ''"
          :busy-action="busyAction"
          :home-connected="selAgentHome ? sessions.isConnected(selAgentHome.key) : false"
          :my-agent="selAgentHome ? sessions.activeAgentFor(selAgentHome.key) : null"
          @back="selAgent = null"
          @act="onAct"
        />
        <RegistryConsole
          v-else-if="selEntry"
          :entry="selEntry"
          :probe="fleet[selEntry.key]"
          :local-key="dir?.local_key || ''"
          :manageable-op="manageableOpFor(selEntry)"
          :busy-action="busyAction"
          :session="selSession"
          :has-stored-refresh="sessions.hasStoredRefresh(selEntry.key)"
          :local-email="localEmail"
          :treasury="treasuryBal[selEntry.key]"
          :treasury-loading="treasuryLoadingKey === selEntry.key"
          :intel="intelBag[selEntry.key]"
          :intel-loading="intelLoadingKey === selEntry.key"
          :attest="attestBag[selEntry.key]"
          :admin-token="sessions.adminTokenFor(selEntry.key)"
          :lat-history="latHist[selEntry.key]"
          @back="clearSelection"
          @act="onAct"
          @connect="onConnect"
          @reconnect="onReconnect"
          @disconnect-peer="onDisconnectPeer"
          @refresh-treasury="() => selEntry && fetchTreasury(selEntry, true)"
          @refresh-intel="() => selEntry && fetchIntel(selEntry, true)"
          @pick-agent="onPickAgent"
        />
        <FleetOverview
          v-else
          :directory="dir"
          :fleet="fleet"
          :canary="canary"
          :busy-action="busyAction"
          @select="selectEntryFromList"
          @fleet-action="onFleetAction"
        />
      </div>

      <footer class="gcc-bridge-foot" data-tour="gcc-log">
        <ActionLog :entries="log" @clear="clearLog" />
      </footer>
    </aside>

    <!-- Credentials vault -->
    <VaultImportModal
      :show="vaultOpen"
      :directory="dir"
      @close="vaultOpen = false"
      @imported="(s) => { ui.showSuccess('Vault import', s); void refreshFleet() }"
    />

    <!-- Multi-op balance reconcile (read-only ES↔TEG drift) -->
    <BalanceReconcileModal :show="reconcileOpen" :directory="dir" @close="reconcileOpen = false" />

    <!-- Amount modal (money actions) -->
    <AmountActionModal
      :show="amountCfg.show"
      :title="amountCfg.title"
      :target-label="amountCfg.target"
      :executor-label="amountCfg.executor"
      :currency="amountCfg.currency"
      :default-reason="amountCfg.defaultReason"
      :busy="!!busyAction"
      @confirm="onAmountConfirm"
      @cancel="amountCfg.show = false"
    />

    <!-- Confirm modal (state-changing non-amount actions) -->
    <ConfirmActionModal
      :show="confirmCfg.show"
      :title="confirmCfg.title"
      :message="confirmCfg.message"
      :tone="confirmCfg.tone"
      :confirm-text="confirmCfg.confirmText"
      :required-match="confirmCfg.requiredMatch"
      :reason-required="confirmCfg.reasonRequired"
      :reason-min-length="confirmCfg.reasonMinLength"
      :busy="!!busyAction"
      @confirm="onConfirmConfirm"
      @close="confirmCfg.show = false"
    />
  </div>
</template>

<script setup lang="ts">
import { loadRegistryConfig } from '@/composables/useRegistryConfig'
import { appLocale } from '@/services/appLocale'
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useAlive } from '@/composables/useAlive'
import GalacticMap from '@/views/GalacticMap.vue'
import type { MapAgent, MapRegistry } from '@/components/GalacticMapCanvas.vue'
import Icon from '@/components/Icon.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import AmountActionModal from '@/components/command/AmountActionModal.vue'
import VaultImportModal from '@/components/command/VaultImportModal.vue'
import ActionLog from '@/components/command/ActionLog.vue'
import EventTicker from '@/components/command/EventTicker.vue'
import FleetDeck from '@/components/command/FleetDeck.vue'
import FleetOverview from '@/components/command/FleetOverview.vue'
import RegistryConsole from '@/components/command/RegistryConsole.vue'
import AgentConsole from '@/components/command/AgentConsole.vue'
import BalanceReconcileModal from '@/components/command/BalanceReconcileModal.vue'
import { useViewport } from '@/composables/useViewport'
import { useFrames } from '@/composables/useFrames'
import { esSocketUrl } from '@/config/frames'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { useCommandSessions } from '@/stores/commandSessions'
import {
  canaryFleetPause, canaryFleetResume, canaryFleetStatus,
  crossTegFund, federationSyncTrigger, fundAgentLocal, fundAgentRemote, getFleetStatus,
  getRegistryDirectory, ironhandProbe, ironhandTargets, listCloudOperators, mintTokens,
  opRestart, opSelfRestartRemote, opTeardown,
  projectionSnapshotRemote, registryIntelLocal, registryIntelRemote, resolveDirectoryEntry,
  attestationStatsLocal, attestationStatsRemote, auditorLatest, systemVitals,
  supplyAuditFrames, transferAgentRemote, treasuryBalanceLocal, treasuryBalanceRemote,
  suspendAgentLocal, reinstateAgentLocal, suspendAgentRemote, reinstateAgentRemote,
} from '@/services/api/command'
import type { ActionLogEntry, AttestationStats, AuditorFrame, CloudOperatorRow, DirectoryEntry, FleetProbe, FoundAgent, HostVitals, IronhandTarget, RegistryDirectory, RegistryIntel, SupplyFrameAudit } from '@/services/api/command'

const vp = useViewport()
const ui = useUIStore()
const auth = useAuthStore()
const sessions = useCommandSessions()
const localEmail = computed(() => (auth.user as any)?.email || '')

// ── §FEDEVENTS-5: deployment truth for the stream/Δ surfaces ─────────────────
// Which frames exist HERE comes from config/frames.ts descriptors; whether this
// node reaches sibling EventStores at all comes from the public registry-config
// (multi_frame — derived server-side from EVENT_STORE_B/C_URL, so it is honest
// on hetzner-frame and any deployment that is not ours). The directory/session
// machinery below is untouched — it was already server-owned and truthful.
const framesApi = useFrames()
const multiFrame = ref(true)   // conservative default: today's behavior until config answers
// The ticker mounts only once deploy config + frame attribution have settled —
// mounting it earlier dialed Frame A's stream for a beat on every non-A cockpit
// (the old `|| 'A'` default racing the directory fetch), a phantom connect that
// then tore down and rejoined the real home stream.
const streamsReady = ref(false)
async function fetchDeployCfg() {
  try {
    // §FEFRAME W2: the ONE shared config read (useRegistryConfig), not a request of its own
    multiFrame.value = ((await loadRegistryConfig())?.multi_frame !== false)
  } catch { /* keep the multi default — degrades to pre-§FEDEVENTS-5 behavior */ }
}

// ── data ─────────────────────────────────────────────────────────────────────
const dir = ref<RegistryDirectory | null>(null)
const fleet = ref<Record<string, FleetProbe>>({})
const canary = ref<any | null>(null)
const cloudOps = ref<CloudOperatorRow[]>([])
const loadError = ref('')

// ── selection ────────────────────────────────────────────────────────────────
const mapRef = ref<any>(null)
const selEntry = ref<DirectoryEntry | null>(null)
const selAgent = ref<MapAgent | null>(null)
const selRawNode = ref<string | null>(null)
const selectedNodeId = ref<string | null>(null)   // map node id of the selected registry (for the ring)
const ringPos = ref<{ x: number; y: number } | null>(null)
const bridgeOpen = ref(false)
const vaultOpen = ref(false)
const reconcileOpen = ref(false)

const selSession = computed(() => (selEntry.value ? sessions.sessionFor(selEntry.value.key) : null))

// ── treasury balance (situational awareness) ─────────────────────────────────
const treasuryBal = reactive<Record<string, string | null>>({})
const treasuryLoadingKey = ref<string | null>(null)
async function fetchTreasury(entry: DirectoryEntry, force = false) {
  if (!entry) return
  if (!force && treasuryBal[entry.key] !== undefined) return
  const connected = sessions.isConnected(entry.key)
  if (!entry.is_local && !connected) { treasuryBal[entry.key] = '' ; return }  // not viewable until connected
  treasuryLoadingKey.value = entry.key
  try {
    const r = entry.is_local ? await treasuryBalanceLocal() : await treasuryBalanceRemote(entry.key, sessions.adminTokenFor(entry.key) || '')
    treasuryBal[entry.key] = String(r?.balance ?? '')
  } catch { treasuryBal[entry.key] = '' } finally { if (treasuryLoadingKey.value === entry.key) treasuryLoadingKey.value = null }
}
/** P7: force-refresh treasury for the local registry + every connected console
 *  (≤16 relayed GETs; powers the deck's Σ-per-currency aggregate). */
async function fetchAllTreasuries() {
  const list = dir.value?.registries.filter(e => e.is_local || sessions.isConnected(e.key)) || []
  await Promise.allSettled(list.map(e => fetchTreasury(e, true)))
}

// ── GC2-1: tri-frame Δ strip — ATOMIC source via the auditor proxy ───────────
// The auditor verifies the invariant in a single statement per frame (no
// read-skew), and the registry proxies it same-origin (the auditor serves no
// CORS headers). Falls back per-frame to the honest ES remap (deckDeltas).
const auditorResp = ref<Record<string, AuditorFrame> | null>(null)
let auditorTimer: ReturnType<typeof setInterval> | null = null
async function refreshAuditor() {
  try { const r = await auditorLatest(); auditorResp.value = r.ok ? r.data : null } catch { auditorResp.value = null }
}
// §FEDEVENTS-5: the strip's frame set is deployment truth, not a literal triple.
// Multi-frame nodes watch the auditor's frame-a/b/c keys (it covers exactly those);
// a single-frame node gets ONE local chip — the auditor does not audit foreign
// deployments, so its data would be about frames that are not this node's.
const stripFrames = computed<Array<{ key: string; label: string; isLocal?: boolean }>>(() => (multiFrame.value
  ? streamFrames.value.map(f => ({ key: f.key.toLowerCase(), label: f.key }))
  : [{ key: '__local__', label: 'LOCAL', isLocal: true }]))
/** §FEFRAME W3: the auditor's slot for a frame. Its slots are named by the frame (`eu`, `asia`; the retired `frame-a`;
 *  the sandbox pair `sbx-alpha`, `sbx-beta`), the strip's keys by the frame manifest (`eu`, `sandbox-alpha`): exact
 *  first, then the two older spellings. A frame with no slot falls back to its EventStore's own reading below. */
function auditorSlot(key: string): AuditorFrame | undefined {
  const d = auditorResp.value || {}
  for (const k of [key, `frame-${key}`, key.replace(/^sandbox-/, 'sbx-')]) if (d[k]) return d[k]
  return undefined
}
const supplyStrip = computed(() => stripFrames.value.map(f => {
  const name = f.isLocal ? (framesApi.localRegistryName.value || 'this registry') : (tickerFrameLabels.value[f.label] || f.label)
  const mk = (delta: number | null, ok: boolean, src: string | null) => ({
    label: f.label, delta, ok, src,
    title: delta === null
      ? `${name}: no genuine supply source from here`
      : `${name} supply invariant (${src === 'atomic' ? 'independent atomic auditor' : 'EventStore'}): Δ ${delta}`,
  })
  if (!f.isLocal) {
    const a = auditorSlot(f.key)
    if (a && a.status && a.status !== 'ERROR') {
      const d = typeof a.delta === 'number' ? a.delta : null
      return mk(d, d !== null && Math.abs(d) < 1e-6, 'atomic')
    }
  }
  const es = deckDeltas.value.find(x => x.frame === f.label)
  if (es) return mk(es.delta, es.status === 'OK' && (es.delta ?? 1) === 0, 'es')
  return mk(null, false, null)
}))

// ── GC2-2: HOST vitals — the single box every registry lives on ─────────────
const host = ref<HostVitals | null>(null)
let hostTimer: ReturnType<typeof setInterval> | null = null
async function refreshHost() { host.value = await systemVitals() }

// ── GC2-5: alert history — last 20 health transitions (toasts stay) ─────────
interface AlertEntry { at: number; key: string; from: string; to: string; durMs?: number }
const alertHistory = ref<AlertEntry[]>([])
const alertsOpen = ref(false)
const downAtMap: Record<string, number> = {}
function pushAlert(e: AlertEntry) { alertHistory.value = [e, ...alertHistory.value].slice(0, 20) }
function fmtAlertTime(t: number) { return new Date(t).toLocaleTimeString(appLocale()) }
function fmtDur(ms?: number) { return typeof ms === 'number' ? `${Math.round(ms / 1000)}s` : '' }

// ── GC2-6: recent targets (session-only, one-click rebind) ───────────────────
const recentKeys = ref<string[]>([])
watch(() => selEntry.value?.key, (k) => {
  if (!k) return
  recentKeys.value = [k, ...recentKeys.value.filter(x => x !== k)].slice(0, 4)
})
const recentEntries = computed(() => recentKeys.value
  .map(k => (dir.value?.registries || []).find(e => e.key === k))
  .filter((e): e is DirectoryEntry => !!e))

// ── GC2-7: stage mode — galactic star map ⇄ planetary Earth (AgentWorld) ─────
// AgentWorld mounts lazily (Cesium is heavy) and only when toggled. Clicks on
// the planet emit select-registry/select-agent, which funnel into the SAME
// handlers the star map uses — the Bridge is map-agnostic by construction.
const stageMode = ref<'galactic' | 'planetary'>((localStorage.getItem('gccStageMode') as 'galactic' | 'planetary') || 'galactic')
watch(stageMode, (m) => {
  localStorage.setItem('gccStageMode', m)
  for (const t of [80, 360, 900]) setTimeout(() => window.dispatchEvent(new Event('resize')), t)
})
const AgentWorldCockpit = defineAsyncComponent(() => import('@/views/AgentWorldCesium.vue'))
function onPlanetRegistry(reg: { id?: string; name?: string; publicUrl?: string }) {
  // AW emits its WorldRegistry; the directory resolver matches on name.
  onSelectRegistry({ id: reg?.id, name: reg?.name } as MapRegistry)
}
function onPlanetAgent(a: { did: string; name?: string; registryName?: string }) {
  if (!a?.did) return
  if (a.registryName) {
    const e = (dir.value?.registries || []).find(x => norm(x.name) === norm(a.registryName) || norm(x.key) === norm(a.registryName))
    if (e) { selEntry.value = e; selRawNode.value = null }
  }
  onSelectAgent({ did: a.did, name: a.name } as MapAgent)
}

// ── registry intel (P7 — dashboard + workers snapshot, per-key cache) ────────
const intelBag = reactive<Record<string, RegistryIntel | null>>({})
const attestBag = reactive<Record<string, AttestationStats | null>>({})   // GC2-3
const intelLoadingKey = ref<string | null>(null)
async function fetchIntel(entry: DirectoryEntry, force = false) {
  if (!entry) return
  if (!force && intelBag[entry.key] !== undefined) return
  const connected = sessions.isConnected(entry.key)
  if (!entry.is_local && !connected) { intelBag[entry.key] = null; return }
  intelLoadingKey.value = entry.key
  try {
    intelBag[entry.key] = entry.is_local
      ? await registryIntelLocal()
      : await registryIntelRemote(entry.key, sessions.adminTokenFor(entry.key) || '')
    // GC2-3: ZKP attestation stats ride the same fetch + trust path. null =
    // endpoint absent on the target (older image) / ZKP analytics empty → "—".
    attestBag[entry.key] = entry.is_local
      ? await attestationStatsLocal()
      : await attestationStatsRemote(entry.key, sessions.adminTokenFor(entry.key) || '')
  } catch { intelBag[entry.key] = null } finally { if (intelLoadingKey.value === entry.key) intelLoadingKey.value = null }
}

// Fetch treasury + intel whenever the selected registry changes (covers map-click,
// fleet-list, deck-chip, and right-click→target paths — all funnel through selEntry).
watch(() => selEntry.value?.key, () => {
  if (selEntry.value) { void fetchTreasury(selEntry.value); void fetchIntel(selEntry.value) }
})

const connectedRemoteKeys = computed(() =>
  (dir.value?.registries || []).filter(e => !e.is_local && sessions.isConnected(e.key)).map(e => e.key),
)

// P11+ restart-visibility: restarting fleet keys → map node ids for the canvas
// pulse. Best-effort — a key with no resolvable node (off-map / not yet measured)
// simply won't pulse the orb (its deck chip still pulses). nodeIdForEntry() reads
// the map's live getNodes(), so this only resolves once the embedded map is mounted.
const busyNodeIds = computed<string[]>(() => {
  const out: string[] = []
  const regs = dir.value?.registries || []
  for (const k of restartingKeys.value) {
    const e = regs.find(r => r.key === k)
    const nid = e ? nodeIdForEntry(e) : null
    if (nid) out.push(String(nid))
  }
  return out
})

// ── P8/P9: frame event streams — DRIVEN BY config/frames.ts descriptors, not
//    local literals (§FEDEVENTS-5). Same-origin nginx WS suffixes are ABSOLUTE
//    fleet-wide (§FEDEVENTS-4 measured), so on a multi-frame deployment every
//    tab is a genuine stream. A single-frame node (registry-config
//    multi_frame=false — hetzner-frame class) gets NO tabs: its vhost maps
//    /ws/events to its OWN EventStore and the sibling suffixes don't exist, so
//    the old "Frame A" label was a lie there. Tabs default to the LOCAL frame
//    (server-stamped directory frame — never a hardcoded 'A').
const streamFrames = computed(() => (multiFrame.value
  ? framesApi.frames.value.filter(f => !f.isSandbox && (f.es?.absoluteWsUrl || f.es?.sameOriginPath))
  : []))
// §FEFRAME W2: tabs show the frames' own names from the manifest, never "Frame <letter>"
const tickerFrameLabels = computed<Record<string, string>>(() =>
  Object.fromEntries(streamFrames.value.map(f => [f.key, f.label])))
const tickerFrames = computed(() => streamFrames.value.map(f => f.key))
const localEntry = computed(() => dir.value?.registries.find(e => e.is_local) || null)
const tickerFrameSel = ref<string>('')
const tickerFrame = computed<string | null>(() => {
  if (!multiFrame.value) return null
  const pick = (k: string | null | undefined) => (k && streamFrames.value.some(f => f.key === k) ? k : null)
  return pick(tickerFrameSel.value) || pick(localEntry.value?.frame) || streamFrames.value[0]?.key || null
})
const tickerWsPath = computed(() => {
  // §FEFRAME W2: the watched frame's own ledger socket from the manifest (an absolute wss:// URL)
  if (!multiFrame.value) {
    const own = framesApi.localFrame.value
    return own ? esSocketUrl(own.key, [own]) : esSocketUrl('')
  }
  const f = streamFrames.value.find(x => x.key === tickerFrame.value)
  return f ? esSocketUrl(f.key, [f]) : null
})
const tickerLabel = computed(() => (multiFrame.value
  ? (tickerFrameLabels.value[tickerFrame.value || ''] || '…')
  : (framesApi.localRegistryName.value || dir.value?.local_key || 'This registry')))

// ── P10: supply-invariant tile (Δ per watched frame). The proxy's "A" key is the
//    EVENT_STORE_URL slot = the LOCAL frame's ES on every registry — so off
//    frame-A we remap: local frame trusts its own slot (or falls back to "A"),
//    and a foreign "A" is only trustworthy when this registry IS frame-A.
const supplyResp = ref<Record<string, SupplyFrameAudit> | null>(null)
let supplyTimer: ReturnType<typeof setInterval> | null = null
async function refreshSupply() {
  try { supplyResp.value = await supplyAuditFrames() } catch { supplyResp.value = null }
}
// P11 — deck Δ row: every GENUINE frame source (same honesty rules; on frame-A
// all three slots are true, elsewhere local + the explicitly-slotted B/C).
const deckDeltas = computed<Array<{ frame: string; delta: number | null; status: string }>>(() => {
  const r = supplyResp.value
  if (!r) return []
  if (!multiFrame.value) {
    // §FEDEVENTS-5: on a single-frame deployment the proxy's "A" key IS the
    // local ES (the EVENT_STORE_URL slot — the endpoint's own contract), so it
    // is attributable to the LOCAL frame even though the node has no letter.
    const e = r['A']
    return (e && e.status !== 'UNREACHABLE') ? [{ frame: 'LOCAL', delta: e.delta, status: e.status }] : []
  }
  const lf = localEntry.value?.frame
  if (!lf) return []
  const out: Array<{ frame: string; delta: number | null; status: string }> = []
  const localE = r[lf]?.status === 'OK' ? r[lf] : r['A']
  if (localE && localE.status !== 'UNREACHABLE') out.push({ frame: lf, delta: localE.delta, status: localE.status })
  for (const f of ['B', 'C']) {
    if (f === lf) continue
    const e = r[f]
    if (e && e.status !== 'UNREACHABLE') out.push({ frame: f, delta: e.delta, status: e.status })
  }
  return out
})

const tickerSupply = computed<{ delta: number | null; status: string } | null>(() => {
  const r = supplyResp.value
  if (!r) return null
  if (!multiFrame.value) {
    const e = r['A']   // local ES slot on every registry (see deckDeltas note)
    return (e && e.status !== 'UNREACHABLE') ? { delta: e.delta, status: e.status } : null
  }
  const f = tickerFrame.value
  if (!f) return null
  const lf = localEntry.value?.frame || null
  let entry: SupplyFrameAudit | undefined
  if (f === lf) entry = (r[f]?.status === 'OK' ? r[f] : r['A'])
  else if (f === 'A' && lf !== 'A') entry = undefined   // no genuine Frame-A source off frame-A
  else entry = r[f]
  if (!entry || entry.status === 'UNREACHABLE') return null
  return { delta: entry.delta, status: entry.status }
})

// ── P8: latency history (ring buffer per registry) + health-transition alerts ─
const latHist = reactive<Record<string, number[]>>({})
let prevHealth: Record<string, string> = {}
function logSystem(target: string, action: string, status: 'ok' | 'err', detail: string) {
  log.value.unshift({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, ts: Date.now(), target, action, status, detail })
}

// ── P11+ restart-visibility ────────────────────────────────────────────────────
// When a self-restart is issued from the cockpit, the op's registry node (and its
// orbiting agents) pulse "busy" on the canvas + its deck chip pulses, from the
// moment we fire until the op is observed healthy again. The success signal of a
// self-restart is a DROPPED connection, so we watch the fleet poll for the recovery
// (down→up), not the call's return. Safety caps bound the pulse if the down window
// is polled right past (fast restart) or the op never recovers on its own.
const restartingKeys = ref<Set<string>>(new Set())
const restartingKeysList = computed(() => [...restartingKeys.value])
const restartMeta = new Map<string, { issuedAt: number; sawDown: boolean }>()
const RESTART_SETTLE_MS = 45000   // never saw it drop → assume settled after this
const RESTART_CAP_MS = 150000     // hard safety cap (clear no matter what)
let restartFastTimer: ReturnType<typeof setInterval> | null = null
function markRestarting(key: string) {
  restartMeta.set(key, { issuedAt: Date.now(), sawDown: false })
  const s = new Set(restartingKeys.value); s.add(key); restartingKeys.value = s
  // base fleet poll is 30s — too slow to watch a restart; accelerate while any op
  // is restarting so the down→up (and the pulse clearing) tracks close to real time.
  if (!restartFastTimer) restartFastTimer = setInterval(() => { void refreshFleet() }, 4000)
  void refreshFleet()
}
function clearRestarting(key: string) {
  restartMeta.delete(key)
  if (!restartingKeys.value.has(key)) return
  const s = new Set(restartingKeys.value); s.delete(key); restartingKeys.value = s
  if (restartingKeys.value.size === 0 && restartFastTimer) { clearInterval(restartFastTimer); restartFastTimer = null }
}
function resolveRestarting(status: Record<string, FleetProbe>) {
  if (!restartingKeys.value.size) return
  const now = Date.now()
  for (const k of Array.from(restartingKeys.value)) {
    const meta = restartMeta.get(k)
    if (!meta) { clearRestarting(k); continue }
    const p = status[k]
    const down = !p || p.health === 'down' || p.health === 'degraded'
    if (down) meta.sawDown = true
    else if (p && p.health === 'up' && (meta.sawDown || (now - meta.issuedAt) > RESTART_SETTLE_MS)) { clearRestarting(k); continue }
    if ((now - meta.issuedAt) > RESTART_CAP_MS) clearRestarting(k)
  }
}
// Preview/debug hook (mirrors window.__gmReg): drive the restart pulse for a fleet
// key WITHOUT firing a real restart — `__gccRestartDemo('op-tokyo', 12000)` in the
// console blinks that orb + deck chip for 12s and seeds the down→up pair into the
// alert HISTORY through the same pushAlert the real digestFleet transitions use.
// Harmless: FE-only state (no backend call), and the safety caps clear it even if left.
;(window as unknown as { __gccRestartDemo?: (k: string, ms?: number) => void }).__gccRestartDemo =
  (key: string, ms = 12000) => {
    const t0 = Date.now()
    markRestarting(key)
    pushAlert({ at: t0, key, from: 'up', to: 'down' })
    window.setTimeout(() => {
      clearRestarting(key)
      pushAlert({ at: Date.now(), key, from: 'down', to: 'up', durMs: Date.now() - t0 })
    }, Math.max(1000, ms))
  }

function digestFleet(status: Record<string, FleetProbe>) {
  const first = Object.keys(prevHealth).length === 0
  for (const [k, p] of Object.entries(status)) {
    if (p.health !== 'down' && typeof p.latency_ms === 'number') {
      const h = latHist[k] || (latHist[k] = [])
      h.push(p.latency_ms)
      if (h.length > 20) h.shift()
    }
    const prev = prevHealth[k]
    if (!first && prev && prev !== p.health) {
      const nowMs = Date.now()
      if (p.health === 'down') {
        downAtMap[k] = nowMs
        pushAlert({ at: nowMs, key: k, from: prev, to: 'down' })
        ui.showError(`${k} DOWN`, p.error || 'health probe failed'); logSystem(k, 'health', 'err', `up → down (${p.error || 'no answer'})`)
      } else if (p.health === 'degraded') {
        if (!downAtMap[k]) downAtMap[k] = nowMs
        pushAlert({ at: nowMs, key: k, from: prev, to: 'degraded' })
        ui.showError(`${k} degraded`, `health probe ${p.status_code}`); logSystem(k, 'health', 'err', `${prev} → degraded`)
      } else if (p.health === 'up' && (prev === 'down' || prev === 'degraded')) {
        const d0 = downAtMap[k]
        pushAlert({ at: nowMs, key: k, from: prev, to: 'up', durMs: d0 ? nowMs - d0 : undefined })
        delete downAtMap[k]
        ui.showSuccess(`${k} recovered`, `${p.latency_ms}ms`); logSystem(k, 'health', 'ok', `${prev} → up`)
      }
    }
    prevHealth[k] = p.health
  }
  resolveRestarting(status)   // P11+ — clear the canvas/chip pulse once an op recovers
}

/** Deck pick → full AgentConsole on a pseudo map-agent (finder reach, P7). */
function onPickAgent(f: FoundAgent) {
  const e = selEntry.value
  if (!e) return
  selAgent.value = {
    did: f.did,
    name: f.name || f.client_id,
    registryId: e.is_local ? '__local__' : e.key,
    status: f.status,
    liquidBalance: f.liquid_balance,
    stakedBalance: f.staked_balance,
    reputation: f.reputation_score,
  } as any
  selectedNodeId.value = null
}

async function onConnect(p: { email: string; password: string }) {
  if (!selEntry.value) return
  const k = selEntry.value.key
  // §FEFRAME W3: sign in AT the registry (its console address), not through this one's admin relay
  const ok = await sessions.connectAdmin(k, p.email, p.password, selEntry.value.console_url || null)
  if (ok) {
    ui.showSuccess('Console connected', `speaking as ${p.email} on ${k}`)
    if (selEntry.value) { void fetchTreasury(selEntry.value, true); void fetchIntel(selEntry.value, true) }
  } else ui.showError('Connect failed', sessions.sessionFor(k).error || k)
}
async function onReconnect() {
  if (!selEntry.value) return
  const k = selEntry.value.key
  const ok = await sessions.reconnect(k)
  if (ok) {
    ui.showSuccess('Reconnected', k)
    if (selEntry.value) { void fetchTreasury(selEntry.value, true); void fetchIntel(selEntry.value, true) }
  } else ui.showError('Reconnect failed', sessions.sessionFor(k).error || k)
}
function onDisconnectPeer() { if (selEntry.value) sessions.disconnect(selEntry.value.key) }

const selAgentHome = computed<DirectoryEntry | null>(() => {
  if (!selAgent.value || !dir.value) return null
  const a = selAgent.value
  if (a.originRegistry) return resolveDirectoryEntry(dir.value, { name: a.originRegistry, trustDomain: null, hopDepth: 1 })
  if (a.registryId === '__local__') return dir.value.registries.find(e => e.is_local) || null
  return resolveDirectoryEntry(dir.value, { name: a.registryId, trustDomain: null, hopDepth: 1 })
})

function onSelectRegistry(reg: MapRegistry) {
  selAgent.value = null
  selectedNodeId.value = (reg as any)?.id ?? null
  const entry = resolveDirectoryEntry(dir.value, reg)
  if (entry) { selEntry.value = entry; selRawNode.value = null } else { selEntry.value = null; selRawNode.value = reg?.name || 'unknown' }
  if (vp.isMobile.value) bridgeOpen.value = true
}
function onSelectAgent(agent: MapAgent | null) {
  if (!agent) { selAgent.value = null; return }
  selAgent.value = agent
  selectedNodeId.value = null   // ring tracks registries, not agents
  if (vp.isMobile.value) bridgeOpen.value = true
}
function clearSelection() { selEntry.value = null; selAgent.value = null; selRawNode.value = null; selectedNodeId.value = null }

const norm = (s: string | null | undefined) => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')

/** Resolve a directory entry to its map-node id (for the targeting ring) via getNodes(). */
function nodeIdForEntry(entry: DirectoryEntry): string | null {
  const nodes: Array<{ id: string; name: string; trustDomain?: string }> = mapRef.value?.getNodes?.() || []
  if (entry.is_local) {
    const local = nodes.find(n => n.id === '__local__')
    if (local) return local.id
  }
  const n = norm(entry.name)
  const hit = nodes.find(nd => norm(nd.name) === n)
  return hit ? hit.id : null
}
function selectEntryFromList(e: DirectoryEntry) {
  selAgent.value = null
  selEntry.value = e
  selRawNode.value = null
  selectedNodeId.value = nodeIdForEntry(e)
  if (vp.isMobile.value) bridgeOpen.value = true
}
function manageableOpFor(entry: DirectoryEntry): CloudOperatorRow | null {
  const k = norm(entry.key)
  const kShort = k.replace(/^op/, '')
  for (const row of cloudOps.value) {
    const n = norm(String((row as any).operator_name || (row as any).name || (row as any).subdomain || ''))
    if (!n) continue
    if (n === k || n === kShort || k.includes(n) || n.includes(kShort)) return row
  }
  return null
}

// ── right-click (projection hit-test, IronhandTheatre pattern) ───────────────
const ctx = reactive({ open: false, x: 0, y: 0, nodeName: '', nodeId: '' as string, entry: null as DirectoryEntry | null })
function screenPos(id: string): { x: number; y: number } | null {
  const m = mapRef.value
  try {
    const pos = m?.getNodePos?.(id); const cam = m?.getCamera?.(); const el = m?.getContainer?.()
    if (!pos || !cam || !el) return null
    const v = pos.clone().project(cam)
    const r = el.getBoundingClientRect()
    return { x: (v.x * 0.5 + 0.5) * r.width + r.left, y: (-v.y * 0.5 + 0.5) * r.height + r.top }
  } catch { return null }
}
/** STAGE-LOCAL projection for the targeting ring (+name label). The ring is
 *  position:absolute inside .gcc-stage, which the map canvas fills — so its
 *  coordinate origin is ALREADY the container's top-left. screenPos() adds
 *  r.left/r.top for viewport-space (right-click hit-test); reusing that for the
 *  ring double-counts the stage offset and stamps it down-right toward the
 *  bottom, detached from the orb. Here we omit the offset and hide the ring
 *  when the node is on the far side of the globe (v.z > 1 = behind camera). */
function ringLocalPos(id: string): { x: number; y: number } | null {
  const m = mapRef.value
  try {
    const pos = m?.getNodePos?.(id); const cam = m?.getCamera?.(); const el = m?.getContainer?.()
    if (!pos || !cam || !el) return null
    const v = pos.clone().project(cam)
    if (v.z > 1) return null
    const r = el.getBoundingClientRect()
    return { x: (v.x * 0.5 + 0.5) * r.width, y: (-v.y * 0.5 + 0.5) * r.height }
  } catch { return null }
}
function onStageContext(ev: MouseEvent) {
  if (stageMode.value !== 'galactic') return   // GC2-7: ctx menu projects star-map nodes only
  const nodes: Array<{ id: string; name: string; trustDomain?: string }> = mapRef.value?.getNodes?.() || []
  let best: { name: string; trustDomain?: string } | null = null
  let bestD = 80
  for (const n of nodes) {
    const p = screenPos(n.id)
    if (!p) continue
    const d = Math.hypot(p.x - ev.clientX, p.y - ev.clientY)
    if (d < bestD) { bestD = d; best = n }
  }
  if (!best) { ctx.open = false; return }
  const stage = (ev.currentTarget as HTMLElement).getBoundingClientRect()
  ctx.x = Math.min(ev.clientX - stage.left, stage.width - 190)
  ctx.y = Math.min(ev.clientY - stage.top, stage.height - 120)
  ctx.nodeName = best.name
  ctx.nodeId = (best as any).id || ''
  ctx.entry = resolveDirectoryEntry(dir.value, { name: best.name, trustDomain: best.trustDomain, hopDepth: 1 })
  ctx.open = true
}
function ctxTarget() {
  selAgent.value = null
  selectedNodeId.value = ctx.nodeId || null
  if (ctx.entry) { selEntry.value = ctx.entry; selRawNode.value = null } else { selEntry.value = null; selRawNode.value = ctx.nodeName }
  ctx.open = false
  if (vp.isMobile.value) bridgeOpen.value = true
}
function ctxFund() {
  if (ctx.entry) { selAgent.value = null; selEntry.value = ctx.entry; openCrossTegFund(ctx.entry) }
  ctx.open = false
}
function ctxProbe() {
  if (ctx.entry) {
    selAgent.value = null
    selEntry.value = ctx.entry
    selectedNodeId.value = ctx.nodeId || null
    onAct({ id: 'registry_probe' })
  }
  ctx.open = false
}

// ── action runner (toast + log + busy) ──────────────────────────────────────
const log = ref<ActionLogEntry[]>([])
const busyAction = ref<string | null>(null)
let ihTargetsCache: IronhandTarget[] | null = null   // P8 quick-probe roster (lazy)
const errDetail = (e: any) =>
  e?.response?.data?.detail || e?.response?.data?.title || e?.message || 'request failed'

async function run(target: string, action: string, fn: () => Promise<any>, okDetail?: (r: any) => string) {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  log.value.unshift({ id, ts: Date.now(), target, action, status: 'pending' })
  const entry = log.value[0]
  busyAction.value = action
  try {
    const r = await fn()
    entry.status = 'ok'
    entry.detail = okDetail ? okDetail(r) : (typeof r?.status === 'string' ? r.status : 'ok')
    entry.payload = r
    ui.showSuccess(`${action} ✓`, target)
    return r
  } catch (e: any) {
    entry.status = 'err'
    entry.detail = errDetail(e)
    entry.payload = e?.response?.data
    ui.showError(`${action} failed`, `${target} — ${entry.detail}`)
    return null
  } finally {
    busyAction.value = null
  }
}

// ── amount modal plumbing ────────────────────────────────────────────────────
const amountCfg = reactive({
  show: false, title: '', target: '', executor: '', currency: '', defaultReason: '',
  onConfirm: null as null | ((p: { amount: string; reason: string }) => void),
})
function onAmountConfirm(p: { amount: string; reason: string }) {
  const cb = amountCfg.onConfirm
  amountCfg.show = false
  cb?.(p)
}
function openCrossTegFund(entry: DirectoryEntry) {
  amountCfg.title = 'Cross-TEG treasury funding'
  amountCfg.target = `${entry.name} treasury`
  amountCfg.executor = `${dir.value?.local_key} admin · Model A (cross-TEG mTLS)`
  amountCfg.currency = entry.currency
  amountCfg.defaultReason = 'gcc_cross_teg_fund'
  amountCfg.onConfirm = ({ amount, reason }) =>
    void run(entry.key, 'cross-teg-fund', () => crossTegFund({ target_registry: entry.key, amount, reason }), r => `${amount} → ${entry.key} (${r?.status || 'sent'})`)
  amountCfg.show = true
}
function openFundAgentRemote(key: string, did: string, name?: string) {
  const tok = sessions.adminTokenFor(key)
  if (!tok) { ui.showError('Not connected', `Connect ${key}'s console first (Registry console → Connect)`); return }
  const entry = dir.value?.registries.find(e => e.key === key)
  amountCfg.title = 'Fund agent from treasury'
  amountCfg.target = `${name || 'agent'} · ${did.slice(0, 26)}… @ ${key}`
  amountCfg.executor = `${key} admin (relayed · Model B)`
  amountCfg.currency = entry?.currency || ''
  amountCfg.defaultReason = 'gcc_fund'
  amountCfg.onConfirm = ({ amount, reason }) =>
    void run(key, 'fund-agent', () => fundAgentRemote(key, sessions.adminTokenFor(key) || '', { target_agent_did: did, amount, reason }), () => `${amount} → ${name || did.slice(0, 18)} @ ${key}`)
  amountCfg.show = true
}
function openFundAgent(did: string, name?: string) {
  const local = dir.value?.registries.find(e => e.is_local)
  amountCfg.title = 'Fund agent from treasury'
  amountCfg.target = `${name || 'agent'} · ${did.slice(0, 28)}…`
  amountCfg.executor = `${dir.value?.local_key} treasury · FLOW 4 (local)`
  amountCfg.currency = local?.currency || ''
  amountCfg.defaultReason = 'gcc_fund'
  amountCfg.onConfirm = ({ amount, reason }) =>
    void run(did.slice(0, 22), 'fund-agent', () => fundAgentLocal({ target_agent_did: did, amount, reason }), () => `${amount} → ${name || did.slice(0, 18)}`)
  amountCfg.show = true
}

// ── confirm modal plumbing ───────────────────────────────────────────────────
const confirmCfg = reactive({
  show: false, title: '', message: '', tone: 'primary' as 'primary' | 'warn' | 'danger',
  confirmText: 'Confirm', requiredMatch: undefined as string | undefined,
  reasonRequired: false, reasonMinLength: 10,
  onConfirm: null as null | ((reason: string) => void),
})
function openConfirm(p: Partial<typeof confirmCfg> & { onConfirm: (reason: string) => void }) {
  Object.assign(confirmCfg, { tone: 'primary', confirmText: 'Confirm', requiredMatch: undefined, reasonRequired: false, reasonMinLength: 10 }, p, { show: true })
}
function onConfirmConfirm(reason: string) {
  const cb = confirmCfg.onConfirm
  confirmCfg.show = false
  cb?.(reason)
}

// ── action dispatch from consoles ────────────────────────────────────────────
function onAct(a: { id: string; payload?: any }) {
  const entry = selEntry.value
  switch (a.id) {
    case 'cross_teg_fund':
      if (entry) openCrossTegFund(entry)
      break
    case 'fund_agent_local':
      if (a.payload?.did) openFundAgent(a.payload.did, a.payload?.name)
      break
    case 'fund_agent_remote':
      if (entry && a.payload?.did) openFundAgentRemote(entry.key, a.payload.did, a.payload?.name)
      break
    case 'fund_agent_remote_home': {
      const home = selAgentHome.value
      if (home && a.payload?.did) openFundAgentRemote(home.key, a.payload.did, a.payload?.name)
      break
    }
    case 'projection_snapshot': {
      if (!entry) break
      const k = entry.key
      const tok = sessions.adminTokenFor(k)
      if (!tok) { ui.showError('Not connected', `Connect ${k}'s console first`); break }
      openConfirm({
        title: 'Projection snapshot',
        message: `Trigger a TEG → EventStore balance snapshot on <strong>${k}</strong>?`,
        tone: 'primary', confirmText: 'Snapshot',
        onConfirm: () => void run(k, 'projection-snapshot', () => projectionSnapshotRemote(k, sessions.adminTokenFor(k) || ''), () => 'snapshot posted'),
      })
      break
    }
    case 'op_restart':
      openConfirm({
        title: 'Restart operator service',
        message: `Restart the registry service of <strong>${entry?.name}</strong> (app #${a.payload?.appId})? Brief downtime for that op.`,
        tone: 'warn', confirmText: 'Restart',
        onConfirm: () => void run(entry?.key || 'op', 'op-restart', () => opRestart(a.payload.appId), () => 'restart issued'),
      })
      break
    case 'op_self_restart': {
      // P11 — relayed self-restart (the op proxies to its mainframe with its license).
      if (!entry) break
      const k = entry.key
      const tok = sessions.adminTokenFor(k)
      if (!tok) { ui.showError('Not connected', `Connect ${k}'s console first`); break }
      openConfirm({
        title: 'Restart operator (self-service)',
        message: `Restart <strong>${entry.name}</strong>'s registry container via its OWN license? Brief downtime for that op — the deck will alert when it drops and recovers.`,
        tone: 'danger', confirmText: 'Restart',
        onConfirm: () => { markRestarting(k); void run(k, 'op-self-restart',
          // A dropped connection here IS the success signal — the op restarts the
          // very server answering us, so the response dies with the container.
          () => opSelfRestartRemote(k, sessions.adminTokenFor(k) || '').catch((e: any) => {
            if (!e?.response) return { status: 'restart issued — connection dropped as expected; watch the deck for down→up' }
            throw e
          }),
          r => r?.status || r?.detail || 'restart issued') },
      })
      break
    }
    case 'op_teardown':
      openConfirm({
        title: 'Tear down operator stack',
        message: `This <strong>destroys ${entry?.name}'s stack</strong>. Type <code>${a.payload?.name}</code> to confirm.`,
        tone: 'danger', confirmText: 'Tear down', requiredMatch: a.payload?.name,
        onConfirm: () => void run(entry?.key || 'op', 'op-teardown', () => opTeardown(a.payload.appId), () => 'teardown issued'),
      })
      break
    case 'ironhand_probe': {
      const did = a.payload?.did
      openConfirm({
        title: 'Fire IRONHAND probe',
        message: `Fire a real low-value mTLS probe at <strong>${a.payload?.name || did}</strong>? One-way, ≤10 units, no refund.`,
        tone: 'primary', confirmText: 'Fire probe',
        onConfirm: () => void run(a.payload?.name || did?.slice(0, 18) || 'agent', 'ironhand-probe',
          () => ironhandProbe({ target_did: did }), r => `${r?.method || 'probe'} · ${r?.result?.status || r?.status || 'fired'}`),
      })
      break
    }
    case 'federation_sync':
      void run(dir.value?.local_key || 'local', 'federation-sync', () => federationSyncTrigger(), () => 'sync round triggered')
      break
    case 'mint_tokens': {
      // P8 — LOCAL mainframe only (server re-enforces via _mainframe_only_dep + admin_treasury).
      if (!entry || !entry.is_local || !entry.capabilities.includes('mint') || !a.payload?.did) break
      const did = String(a.payload.did)
      const isTreasury = did === 'did:theprotocol:teg_system_treasury'
      amountCfg.title = 'Issue units: create from void'
      amountCfg.target = `${isTreasury ? 'system treasury' : did.slice(0, 26) + '…'} @ ${entry.key}`
      amountCfg.executor = `${entry.key} issuing authority · registry proxy emits TokensIssued`
      amountCfg.currency = entry.currency
      amountCfg.defaultReason = 'gcc_mint'
      amountCfg.onConfirm = ({ amount, reason }) =>
        void run(entry.key, 'mint', () => mintTokens({ target_agent_did: did, amount, reason }),
          () => `${amount} ${entry.currency} issued → ${isTreasury ? 'treasury' : did.slice(0, 18)}`)
      amountCfg.show = true
      break
    }
    case 'registry_probe': {
      // P8 — fire the LOCAL probe at the selected registry's mTLS agent (Model A).
      if (!entry) break
      void (async () => {
        if (!ihTargetsCache) {
          try { ihTargetsCache = await ironhandTargets() } catch { ihTargetsCache = [] }
        }
        const n = norm(entry.key)
        const nName = norm(entry.name)
        const hit = (ihTargetsCache || []).find(t => { const r = norm(t.registry); return r === n || r === nName })
        if (!hit) { ui.showError('No mTLS target found', `no IRONHAND-enrolled agent known on ${entry.key}`); return }
        openConfirm({
          title: 'Fire IRONHAND quick probe',
          message: `Fire a real low-value mTLS probe at <strong>${hit.name}</strong> @ <strong>${entry.key}</strong>? One-way, ≤10 units, no refund.`,
          tone: 'primary', confirmText: 'Fire probe',
          onConfirm: () => void run(entry.key, 'registry-probe',
            () => ironhandProbe({ target_did: hit.did }), r => `${r?.method || 'probe'} · ${r?.result?.status || r?.status || 'fired'} → ${hit.name}`),
        })
      })()
      break
    }
    case 'suspend_agent': case 'reinstate_agent': {
      const home = selAgentHome.value
      const did = a.payload?.did
      if (!home || !did) { ui.showError('Cannot resolve agent home', 'unknown home registry'); break }
      const isSuspend = a.id === 'suspend_agent'
      const local = home.is_local
      if (!local && !sessions.isConnected(home.key)) { ui.showError('Not connected', `Connect ${home.key}'s console first`); break }
      openConfirm({
        title: isSuspend ? 'Suspend agent (coordinated)' : 'Reinstate agent',
        message: isSuspend
          ? `Coordinated suspend of <strong>${a.payload?.name || did}</strong> on <strong>${home.key}</strong>: registry status + IRONHAND mTLS revoke + TEG account suspend. Give a reason (min 10 chars).`
          : `Reinstate <strong>${a.payload?.name || did}</strong> on <strong>${home.key}</strong> (re-enroll mTLS + reactivate TEG)? Reason (min 10 chars).`,
        tone: isSuspend ? 'danger' : 'primary',
        confirmText: isSuspend ? 'Suspend' : 'Reinstate',
        reasonRequired: true, reasonMinLength: 10,
        onConfirm: (reason: string) => {
          const act = isSuspend ? 'suspend-agent' : 'reinstate-agent'
          const fn = local
            ? () => (isSuspend ? suspendAgentLocal(did, reason) : reinstateAgentLocal(did, reason))
            : () => (isSuspend ? suspendAgentRemote(home.key, sessions.adminTokenFor(home.key) || '', did, reason)
                               : reinstateAgentRemote(home.key, sessions.adminTokenFor(home.key) || '', did, reason))
          void run(home.key, act, fn, () => `${isSuspend ? 'suspended' : 'reinstated'} ${a.payload?.name || did.slice(0, 18)}`)
        },
      })
      break
    }
    case 'mint_agent': {
      if (!entry || !a.payload?.did) break
      const k = entry.key
      void sessions.mintAgentToken(k, a.payload.client_id, a.payload.client_secret, a.payload.did).then(tok => {
        if (tok) ui.showSuccess('Agent active', `${a.payload.name || a.payload.did.slice(0, 18)} on ${k}`)
        else ui.showError('Agent sign-in failed', sessions.sessionFor(k).error || k)
      })
      break
    }
    case 'transfer_from_my_agent': {
      const home = selAgentHome.value
      if (!home || !a.payload?.toDid) break
      const my = sessions.activeAgentFor(home.key)
      if (!my) { ui.showError('No active agent', `Sign in as one of your agents on ${home.key} first`); break }
      amountCfg.title = 'Agent → agent transfer'
      amountCfg.target = `${a.payload.toName || 'agent'} · ${String(a.payload.toDid).slice(0, 26)}… @ ${home.key}`
      amountCfg.executor = `my agent ${my.did.slice(0, 22)}… (Model L, relayed)`
      amountCfg.currency = home.currency
      amountCfg.defaultReason = 'gcc transfer'
      amountCfg.onConfirm = ({ amount, reason }) =>
        void run(home.key, 'agent-transfer', () => transferAgentRemote(home.key, sessions.activeAgentFor(home.key)?.token || '', { receiver_agent_id: a.payload.toDid, amount, message: reason }), () => `${amount} → ${a.payload.toName || String(a.payload.toDid).slice(0, 16)}`)
      amountCfg.show = true
      break
    }
  }
}
/** Restore every console from stored refresh tokens, then refresh balances (deck Σ). */
function reconnectAllSessions() {
  const keys = dir.value?.registries.filter(e => !e.is_local).map(e => e.key) || []
  void sessions.reconnectAll(keys).then(n => {
    if (n > 0) { ui.showSuccess('Sessions restored', `${n} console${n > 1 ? 's' : ''} reconnected`); void fetchAllTreasuries() }
    else ui.showInfo?.('No stored sessions', 'Import a vault or connect a registry first')
  })
}
function onFleetAction(id: string) {
  if (id === 'federation_sync') { onAct({ id }); return }
  if (id === 'open_vault') { vaultOpen.value = true; return }
  if (id === 'open_reconcile') { reconcileOpen.value = true; return }
  if (id === 'reconnect_all') { reconnectAllSessions(); return }
  if (id === 'sweep_snapshot') {
    // P11 — one button, every connected console: sequential snapshots, one log row each.
    const keys = connectedRemoteKeys.value
    if (!keys.length) { ui.showInfo?.('No connected consoles', 'Connect registries or import a vault first'); return }
    openConfirm({
      title: 'Fleet sweep — projection snapshots',
      message: `Trigger a TEG → EventStore balance snapshot on <strong>${keys.length}</strong> connected registr${keys.length > 1 ? 'ies' : 'y'}?`,
      tone: 'primary', confirmText: 'Sweep',
      onConfirm: () => void (async () => {
        let ok = 0
        for (const k of keys) {
          const r = await run(k, 'snapshot', () => projectionSnapshotRemote(k, sessions.adminTokenFor(k) || ''), () => 'snapshot posted')
          if (r !== null) ok++
        }
        ui.showSuccess('Sweep complete', `${ok}/${keys.length} snapshots posted`)
      })(),
    })
    return
  }
  if (id === 'sweep_refresh') {
    // P11 — refresh treasuries + intel across local + every connected console.
    void (async () => {
      await fetchAllTreasuries()
      const list = dir.value?.registries.filter(e => e.is_local || sessions.isConnected(e.key)) || []
      await Promise.allSettled(list.map(e => fetchIntel(e, true)))
      void refreshSupply()
      ui.showSuccess('Refresh sweep complete', `${list.length} registr${list.length > 1 ? 'ies' : 'y'} updated`)
    })()
    return
  }
  if (id === 'canary_resume') {
    void run('FLEET', 'canary-resume', () => canaryFleetResume(), () => 'canaries resumed').then(refreshCanary)
    return
  }
  if (id === 'canary_pause') {
    openConfirm({
      title: 'Pause canary fleet',
      message: 'Pause <strong>ALL canary scheduling fleet-wide</strong> (master flag)? Synthetic monitoring stops until resumed.',
      tone: 'warn', confirmText: 'Pause fleet',
      onConfirm: () => void run('FLEET', 'canary-pause', () => canaryFleetPause(), () => 'fleet paused').then(refreshCanary),
    })
  }
}

// ── loading + polling ────────────────────────────────────────────────────────
let pollTimer: ReturnType<typeof setInterval> | null = null
async function refreshFleet() {
  try {
    fleet.value = (await getFleetStatus()).status
    digestFleet(fleet.value)   // P8: latency ring buffers + up/down transition alerts
  } catch { /* probes are best-effort */ }
}

// ── P8: action-log persistence (sessionStorage, payloads stay in-memory only) ─
const LOG_KEY = 'gcc_action_log_v1'
function persistLog() {
  try {
    sessionStorage.setItem(LOG_KEY, JSON.stringify(log.value.slice(0, 100).map(({ payload: _p, ...rest }) => rest)))
  } catch { /* quota/private mode */ }
}
function restoreLog() {
  try {
    const raw = sessionStorage.getItem(LOG_KEY)
    if (raw) {
      const arr = JSON.parse(raw)
      if (Array.isArray(arr)) log.value = arr.filter(e => e && e.id && e.ts).slice(0, 100)
    }
  } catch { /* corrupted — start fresh */ }
}
function clearLog() {
  log.value = []
  try { sessionStorage.removeItem(LOG_KEY) } catch { /* private mode */ }
}
watch(log, persistLog, { deep: true })

// ── P8: keyboard — Esc deselects, '/' focuses the agent finder ────────────────
function onKeydown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement | null)?.tagName
  const typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
  if (e.key === 'Escape' && !amountCfg.show && !confirmCfg.show && !vaultOpen.value && !reconcileOpen.value && !typing) {
    if (selAgent.value || selEntry.value) { clearSelection(); e.preventDefault() }
  } else if (e.key === '/' && selEntry.value && !typing) {
    const el = document.querySelector<HTMLInputElement>('input[aria-label="Search agents on this registry"]')
    if (el) { el.focus(); e.preventDefault() }
  }
}
async function refreshCanary() {
  try { canary.value = await canaryFleetStatus() } catch { canary.value = null }
}
// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a page left during its first reads starts none of its four polls when they land
const alive = useAlive()
onMounted(async () => {
  restoreLog()                                          // P8 — survive reloads
  window.addEventListener('keydown', onKeydown)         // P8 — Esc / '/' shortcuts
  // §FEDEVENTS-5 — solo vs multi streams + card name/frame descriptors; the
  // ticker holds until BOTH settle so it joins the right stream on first dial.
  void Promise.allSettled([fetchDeployCfg(), framesApi.ensureLoaded()]).then(() => { streamsReady.value = true })
  // Embedded map measures on mount — nudge it after layout settles (Theatre pattern).
  for (const t of [60, 320, 900]) setTimeout(() => window.dispatchEvent(new Event('resize')), t)
  try {
    dir.value = await getRegistryDirectory()
    // §FEFRAME W3: one registry, two spellings (the directory's name, the manifest's key): the hub answers for both
    sessions.registerAliases(dir.value.registries.map(e => ({ key: e.key, canonical: e.manifest_key || null })))
    // Silent session restore from stored refresh tokens (D2 — no passwords kept).
    const keys = dir.value.registries.filter(e => !e.is_local).map(e => e.key)
    void sessions.reconnectAll(keys).then(n => { if (n > 0) ui.showInfo?.('Consoles restored', `${n} registry session${n > 1 ? 's' : ''} reconnected`) })
  } catch (e: any) {
    loadError.value = `Directory unavailable: ${errDetail(e)}`
  }
  void refreshFleet()
  void refreshCanary()
  try { cloudOps.value = await listCloudOperators() } catch { cloudOps.value = [] }
  if (!alive()) return
  pollTimer = setInterval(() => { void refreshFleet() }, 30000)
  void refreshSupply()
  supplyTimer = setInterval(() => { void refreshSupply() }, 60000)
  void refreshAuditor()                                              // GC2-1
  auditorTimer = setInterval(() => { void refreshAuditor() }, 45000)
  void refreshHost()                                                 // GC2-2
  hostTimer = setInterval(() => { void refreshHost() }, 60000)
  ringTick()
})
let ringRaf = 0
function ringTick() {
  ringPos.value = selectedNodeId.value ? ringLocalPos(selectedNodeId.value) : null
  ringRaf = requestAnimationFrame(ringTick)
}
onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (supplyTimer) clearInterval(supplyTimer)
  if (auditorTimer) clearInterval(auditorTimer)   // GC2-1
  if (hostTimer) clearInterval(hostTimer)         // GC2-2
  if (restartFastTimer) clearInterval(restartFastTimer)   // P11+ — restart-visibility accelerated poll
  if (ringRaf) cancelAnimationFrame(ringRaf)
  window.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
/* ── GC2: stage HUD (surface toggle + tri-frame Δ strip) ── */
.gcc-hud { position: absolute; top: 12px; left: 50%; transform: translateX(-50%); display: flex; align-items: center; gap: 7px; z-index: 14; }
.gcc-hud-toggle { display: inline-flex; align-items: center; gap: 5px; font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.08em; color: var(--nc-primary-bright); background: rgba(8,14,24,0.78); border: 1px solid rgba(var(--nc-primary-rgb),0.35); border-radius: 999px; padding: 4px 11px; cursor: pointer; backdrop-filter: blur(8px); transition: border-color .15s, background .15s; }
.gcc-hud-toggle:hover { border-color: rgba(var(--nc-primary-rgb),0.7); background: rgba(10,18,30,0.92); }
.gcc-hud-delta { font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.04em; padding: 4px 9px; border-radius: 999px; background: rgba(8,14,24,0.78); border: 1px solid rgba(120,150,190,0.25); backdrop-filter: blur(8px); }
.gcc-hud-delta--ok  { color: #00e676; border-color: rgba(0,230,118,0.4); }
.gcc-hud-delta--ok::before { content: ''; display: inline-block; width: 5px; height: 5px; margin-right: 5px; border-radius: 50%; background: #00e676; box-shadow: 0 0 6px #00e676; vertical-align: middle; animation: gcc-live-blink 1.8s ease-in-out infinite; }
@keyframes gcc-live-blink { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
.gcc-hud-delta--bad { color: #ff5252; border-color: rgba(255,82,82,0.55); }
.gcc-hud-delta--na  { color: rgba(255,255,255,0.35); }
.gcc-planet { position: absolute; inset: 0; }

/* ── GC2-5: alert history drawer ── */
.gcc-alerts { position: absolute; right: 12px; bottom: 66px; width: 330px; max-height: 300px; overflow-y: auto; z-index: 26; background: rgba(8,14,24,0.94); border: 1px solid rgba(var(--nc-primary-rgb),0.3); border-radius: 10px; padding: 10px 12px; backdrop-filter: blur(10px); }
.gcc-alerts-head { display: flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.12em; color: rgba(var(--nc-primary-rgb),0.75); margin-bottom: 8px; }
.gcc-alerts-x { margin-left: auto; background: none; border: none; color: rgba(255,255,255,0.5); cursor: pointer; padding: 2px; }
.gcc-alerts-x:hover { color: #fff; }
.gcc-alerts-empty { font-size: 0.68rem; color: rgba(255,255,255,0.4); padding: 6px 0 2px; }
.gcc-alerts-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
.gcc-alerts-row { display: flex; align-items: baseline; gap: 8px; font-size: 0.66rem; color: rgba(255,255,255,0.72); }
.gcc-alerts-t { font-family: var(--mono); font-size: 0.58rem; color: rgba(255,255,255,0.38); flex-shrink: 0; }
.gcc-alerts-k { font-weight: 600; color: var(--nc-primary-bright); }
.gcc-alerts-tr--down { color: #ff5252; }
.gcc-alerts-tr--up { color: #00e676; }
.gcc-alerts-d { margin-left: auto; font-family: var(--mono); font-size: 0.58rem; color: #ffb300; }

/* ── GC2-6: recent targets ── */
.gcc-recents { display: flex; align-items: center; gap: 6px; padding: 7px 14px 0; flex-wrap: wrap; }
.gcc-recents-k { color: rgba(var(--nc-primary-rgb),0.5); display: inline-flex; }
.gcc-recent-chip { font-family: var(--mono); font-size: 0.6rem; color: rgba(255,255,255,0.65); background: rgba(var(--nc-primary-rgb),0.06); border: 1px solid rgba(var(--nc-primary-rgb),0.22); border-radius: 999px; padding: 2px 9px; cursor: pointer; transition: all .14s; }
.gcc-recent-chip:hover { color: #fff; border-color: rgba(var(--nc-primary-rgb),0.55); transform: translateY(-1px); box-shadow: 0 3px 10px rgba(var(--nc-primary-rgb),0.18); }
.gcc-recent-chip--on { color: var(--nc-primary-bright); border-color: rgba(var(--nc-primary-rgb),0.7); background: rgba(var(--nc-primary-rgb),0.14); }

.gcc {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  gap: 12px;
  height: calc(100vh - 132px);
  min-height: 540px;
}

/* stage */
.gcc-stage {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .24);
  background: rgba(4, 8, 14, 0.4);
  box-shadow: 0 10px 40px rgba(0,0,0,.4), inset 0 0 0 1px rgba(var(--nc-primary-rgb, 0,210,210), .05);
}
.gcc-map { position: absolute; inset: 0; }

.gcc-sel-ring {
  position: absolute; z-index: 30; width: 0; height: 0; pointer-events: none;
  transform: translate(-50%, -50%);
}
.gcc-sel-ring-pulse {
  position: absolute; left: -19px; top: -19px; width: 38px; height: 38px;
  border: 2px solid var(--nc-primary, #00d2d2); border-radius: 50%;
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb, 0,210,210), .6), inset 0 0 8px rgba(var(--nc-primary-rgb, 0,210,210), .4);
  animation: gcc-ring-pulse 1.6s ease-in-out infinite;
}
@keyframes gcc-ring-pulse {
  0%, 100% { transform: scale(1); opacity: .9; }
  50% { transform: scale(1.22); opacity: .5; }
}
.gcc-sel-name {
  position: absolute; z-index: 30; pointer-events: none;
  transform: translate(-50%, 0);
  font-size: .6rem; font-weight: 800; letter-spacing: .1em; white-space: nowrap;
  color: var(--nc-primary, #00d2d2);
  text-shadow: 0 0 8px rgba(var(--nc-primary-rgb, 0,210,210), .65), 0 1px 3px rgba(0,0,0,.9);
}
.gcc-ctx {
  position: absolute; z-index: 50; min-width: 180px;
  background: rgba(10, 14, 22, 0.97);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .35);
  border-radius: 9px; padding: 5px;
  box-shadow: 0 10px 36px rgba(0,0,0,.55);
}
.gcc-ctx-head { padding: 5px 8px 6px; font-size: .68rem; font-weight: 800; color: var(--nc-primary, #00d2d2); border-bottom: 1px solid rgba(255,255,255,.06); margin-bottom: 4px; }
.gcc-ctx-item {
  display: flex; align-items: center; gap: 7px; width: 100%; text-align: left;
  padding: 6px 8px; border: none; background: transparent; border-radius: 6px;
  color: var(--nc-text-primary, #e8eaed); font-size: .74rem; cursor: pointer;
}
.gcc-ctx-item:hover { background: rgba(var(--nc-primary-rgb, 0,210,210), .1); }

/* bridge */
.gcc-bridge {
  position: relative;
  display: flex; flex-direction: column; min-height: 0;
  background:
    linear-gradient(168deg, rgba(255,255,255,.03), transparent 60%),
    rgba(var(--nc-primary-rgb, 0,210,210), .04);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .2);
  border-radius: 12px;
  backdrop-filter: blur(10px); -webkit-backdrop-filter: blur(10px);
  box-shadow: 0 10px 40px rgba(0,0,0,.35);
}
/* command-deck top accent hairline */
.gcc-bridge::before {
  content: ''; position: absolute; top: 0; left: 16px; right: 16px; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb, 0,210,210), .7), transparent);
  pointer-events: none;
}
.gcc-bridge-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px 10px; border-bottom: 1px solid rgba(255,255,255,.06);
}
.gcc-id { display: flex; align-items: center; gap: 9px; }
.gcc-id-ic { color: var(--nc-primary, #00d2d2); animation: gcc-radar-pulse 2.6s ease-in-out infinite; }
@keyframes gcc-radar-pulse {
  0%, 100% { opacity: .72; filter: drop-shadow(0 0 2px rgba(var(--nc-primary-rgb, 0,210,210), .4)); }
  50% { opacity: 1; filter: drop-shadow(0 0 7px rgba(var(--nc-primary-rgb, 0,210,210), .9)); }
}
.gcc-id-t { font-size: .72rem; font-weight: 800; letter-spacing: .14em; text-shadow: 0 0 14px rgba(var(--nc-primary-rgb, 0,210,210), .35); }
.gcc-id-s { font-size: .6rem; color: var(--nc-text-muted, #94a3b8); }
.gcc-close {
  width: 30px; height: 30px; display: grid; place-items: center;
  background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); border-radius: 7px;
  color: var(--nc-text-muted, #94a3b8); cursor: pointer;
}
.gcc-bridge-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 12px 14px; }
.gcc-bridge-foot { flex: 0 0 auto; padding: 8px 14px 12px; border-top: 1px solid rgba(255,255,255,.06); }

.gcc-error {
  margin: 0 0 10px; padding: 8px 10px; font-size: .72rem;
  background: rgba(239,68,68,.08); border: 1px solid rgba(239,68,68,.35); border-radius: 8px; color: #fca5a5;
}
.gcc-unmatched {
  display: flex; align-items: center; gap: 7px; flex-wrap: wrap;
  margin: 0 0 10px; padding: 8px 10px; font-size: .7rem;
  background: rgba(245,158,11,.08); border: 1px solid rgba(245,158,11,.35); border-radius: 8px; color: #fbbf24;
}
.gcc-unmatched-x { margin-left: auto; background: transparent; border: none; color: inherit; text-decoration: underline; cursor: pointer; font-size: .66rem; }

.gcc-fab {
  position: absolute; right: 14px; bottom: 14px; z-index: 40;
  width: 46px; height: 46px; border-radius: 50%; display: grid; place-items: center;
  background: rgba(10, 14, 22, 0.92);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .5);
  color: var(--nc-primary, #00d2d2); cursor: pointer;
  box-shadow: 0 6px 22px rgba(0,0,0,.5);
}

.gcc-backdrop {
  position: fixed; inset: 0; z-index: 8999;
  background: rgba(0,0,0,.55);
  backdrop-filter: blur(2px); -webkit-backdrop-filter: blur(2px);
}

/* mobile: stage full-bleed, bridge = bottom sheet (top:auto — the fixed box must
   anchor to the bottom; see the FederationDiscovery filter-sheet lesson) */
@media (max-width: 1024px) {
  .gcc { grid-template-columns: 1fr; height: calc(100vh - 118px); }
  .gcc-bridge--mobile {
    position: fixed;
    top: auto;
    bottom: -100%;
    left: 0; right: 0;
    z-index: 9000;
    max-height: 80vh;
    border-radius: 14px 14px 0 0;
    transition: bottom 240ms cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 -8px 32px rgba(0,0,0,.6);
    background: rgba(10, 14, 22, 0.97);
  }
  .gcc-bridge--open { bottom: 0; }
}
</style>
