<template>
<div class="iht">
  <!-- ── COMMAND BAR ─────────────────────────────────────────── -->
  <header class="iht-bar">
    <div class="iht-bar-id">
      <span class="iht-chip"><span class="iht-chip-dot"></span>IRONHAND</span>
      <h1 class="iht-title">mTLS Identity <span class="iht-accent">Theatre</span></h1>
      <span class="iht-sub">live cross-frame identity travel &middot; SPIRE authentication theatre</span>
    </div>
    <div class="iht-pills">
      <div class="iht-pill" :class="ihRead !== 'read' ? '' : fabricOk ? 'iht-pill-ok' : 'iht-pill-bad'" data-testid="iht-fabric">
        <span class="iht-pill-dot"></span>SPIRE FABRIC
        <strong>{{ ihRead !== 'read' ? '—' : fabricOk ? 'NOMINAL' : 'DEGRADED' }}</strong>
      </div>
      <div class="iht-pill"><span class="iht-pill-k">enrolled</span><strong>{{ ihRead === 'read' ? ih.summary.db_enrolled : '—' }}</strong></div>
      <div class="iht-pill"><span class="iht-pill-k">revoked</span><strong :class="ih.summary.db_revoked ? 'iht-red' : ''">{{ ihRead === 'read' ? ih.summary.db_revoked : '—' }}</strong></div>
      <div class="iht-pill"><span class="iht-pill-k">rev p95</span><strong>{{ revP95 }}</strong></div>
      <div class="iht-pill"><span class="iht-pill-k">mTLS pass 24h</span><strong>{{ passRate }}</strong></div>
      <select v-if="isHub" class="iht-target iht-source" v-model="selectedSource" @change="onSourceSelect"
              :title="'SOURCE — fire AS any registry\'s probe (remote, its own SVID rides). Default: local probe. Or right-click a registry ①'">
        <option value="">source — local probe (auto)</option>
        <option v-for="t in targetOptions" :key="'src-' + t.did" :value="t.did">{{ t.label }}</option>
      </select>
      <select class="iht-target" v-model="selectedTarget"
              :title="isHub ? 'TARGET — pick, or right-click a registry ②' : 'Pick a target — or right-click any registry on the map'">
        <option value="" disabled>target — pick, or right-click a registry…</option>
        <option v-for="t in targetOptions" :key="t.did" :value="t.did">{{ t.label }}</option>
      </select>
      <button class="iht-fire" :disabled="probeBusy || !selectedTarget" @click="fireProbe" :title="probeHint">
        <span class="iht-fire-ico">▶</span>{{ probeBusy ? 'FIRING…' : 'FIRE PROBE' }}
      </button>
      <span v-if="isHub && (selectedSource || selectedTarget)" class="iht-route" :title="'cockpit: source → target'">
        <b>{{ selectedSourceName || 'probe' }}</b><span class="iht-route-arw">→</span><b>{{ targetName(selectedTarget) || '…' }}</b>
      </span>
    </div>
  </header>

  <!-- ── MAIN GRID ───────────────────────────────────────────── -->
  <div class="iht-grid">

    <!-- LEFT: identities -->
    <aside class="iht-rail iht-left">
      <div class="iht-panel-h">IDENTITIES <span class="iht-count">{{ enrolledList.length }}</span>
        <button class="iht-followall" :class="{ 'iht-followall-on': followAll }" @click="toggleFollowAll"
                :title="followAll ? 'Hide all identities from the map' : 'Show ALL left-menu identities on the map (click one identity to show just that one)'">
          {{ followAll ? '● HIDE ALL' : 'SHOW ALL' }}
        </button>
      </div>
      <div class="iht-idlist">
        <div
          v-for="a in enrolledList" :key="a.did"
          class="iht-idcard" :class="{ 'iht-idcard-sel': soloDid === a.did || (followAll && followDid === a.did) }"
          :title="soloDid === a.did ? 'Showing only this identity — click to hide' : 'Click to show only this identity on the map'"
          @click="selectIdentity(a)"
        >
          <div class="iht-idtop">
            <span class="iht-iddot" :class="a.spire_entry_exists ? 'iht-dot-ok' : 'iht-dot-warn'"></span>
            <span class="iht-idname">{{ agentName(a) }}</span>
            <span v-if="soloDid === a.did" class="iht-followpill">SHOWN</span>
            <span v-else-if="followAll" class="iht-followpill">ON MAP</span>
          </div>
          <div class="iht-idspiffe" :title="a.spiffe_id">{{ shortSpiffe(a.spiffe_id) }}</div>
          <div class="iht-ttl">
            <div class="iht-ttl-bar"><div class="iht-ttl-fill" :class="{ 'iht-ttl-low': svidTtl(a).low }" :style="{ width: svidTtl(a).pct + '%' }"></div></div>
            <span class="iht-ttl-lbl" :class="{ 'iht-ttl-low-t': svidTtl(a).low }">SVID&nbsp;{{ svidTtl(a).label }}</span>
          </div>
          <div class="iht-idmeta">
            <span>{{ a.status }}</span><span class="iht-dim">· {{ timeAgo(a.enrolled_at) }}</span>
            <button class="iht-revoke" :disabled="revoking === a.did" @click.stop="revokeIdentity(a)">{{ revoking === a.did ? '…' : 'REVOKE' }}</button>
          </div>
        </div>
        <ReadFailedNotice v-if="!enrolledList.length && ihRead === 'unread'" dense :retry="fetchIronhand" data-testid="iht-identities-unread" />
        <p v-else-if="!enrolledList.length && ihRead === 'read'" class="iht-empty">No enrolled mTLS identities.</p>
      </div>
      <div class="iht-cfg">
        <div class="iht-cfg-row"><span>SVID TTL</span><b>30m</b></div>
        <div class="iht-cfg-row"><span>Soft revoke</span><b class="iht-grn">&lt;500ms WS</b></div>
        <div class="iht-cfg-row"><span>Attestation</span><b>x509pop</b></div>
        <div class="iht-cfg-row"><span>SPIRE entries</span><b>{{ ihRead === 'read' ? `${ih.summary.agent_entries}/${ih.summary.total_spire_entries}` : '—' }}</b></div>
      </div>
    </aside>

    <!-- CENTER: embedded galactic map (live identity-travel stage) -->
    <section class="iht-stage" @contextmenu="onMapContextMenu" @click="targetMenu.open = false">
      <!-- The REAL Galactic Map (original topology + edges + hops), agents hidden, tracked orb overlaid -->
      <!-- Follow-All unhides the map's OWN agent layer, FILTERED to just the left-menu
           identities (only-agent-dids). Native dots/3D balls + hover label + click→AgentDetailModal. -->
      <GalacticMap embedded
        :hide-agents="!(followAll || !!soloDid)"
        :only-agent-dids="followAll ? enrolledDids : (soloDid ? [soloDid] : [])"
        ref="canvasRef" class="iht-map" />
      <!-- comet trail (recent positions) -->
      <div v-for="(t, i) in orbTrail" :key="'tr' + t.id" class="iht-orb-trail"
           :style="{ left: t.x + 'px', top: t.y + 'px', opacity: ((i + 1) / (orbTrail.length + 1)) * 0.55 }"></div>
      <!-- hop beacons (authentication pulses) -->
      <div v-for="bc in beacons" :key="bc.id" class="iht-beacon" :style="{ left: bc.x + 'px', top: bc.y + 'px' }"></div>
      <!-- traveling identity capsule (real agent avatar in transit, mTLS-shielded) -->
      <div v-if="orb.visible" class="iht-orb-layer" :style="{ left: orb.x + 'px', top: orb.y + 'px' }">
        <div class="iht-orb-halo" :class="{ 'iht-orb-arrive': orb.pulse }"></div>
        <div class="iht-orb-ring"></div>
        <div class="iht-orb-ring iht-orb-ring2"></div>
        <div class="iht-orb-av" :class="{ 'iht-orb-broken': orb.broken }"><UserAvatar :user="orb.agent" :avatar-url="orb.avatarUrl" :display-name="orb.name" size="md" :overlay-override="orb.broken ? 'broken-machine' : undefined" /></div>
        <div class="iht-orb-label">
          <span class="iht-orb-name">{{ orb.name }}</span>
          <span class="iht-orb-spiffe">mTLS&nbsp;·&nbsp;{{ orb.spiffeShort }}</span>
        </div>
      </div>
      <div class="iht-stage-legend">
        <span><i class="iht-lg iht-lg-orb"></i> registry</span>
        <span><i class="iht-lg iht-lg-bridge"></i> frame bridge (mTLS)</span>
        <span><i class="iht-lg iht-lg-id"></i> identity in transit</span>
      </div>
      <div class="iht-stage-tag">LIVE FEDERATION TOPOLOGY</div>
      <!-- right-click target menu (registry node → its agents homed there) -->
      <div v-if="targetMenu.open" class="iht-tmenu" :class="{ 'iht-tmenu-srcmode': targetMenu.mode === 'source' }" :style="{ left: targetMenu.x + 'px', top: targetMenu.y + 'px' }" @click.stop>
        <div class="iht-tmenu-h">{{ targetMenu.mode === 'source' ? '① set source · ' + targetMenu.node : (isHub ? '② fire at · ' : 'fire probe at · ') + targetMenu.node }}</div>
        <button v-for="t in targetMenu.items" :key="t.did" class="iht-tmenu-it"
                :class="{ 'iht-tmenu-blocked': targetMenu.mode === 'target' && routeBlockedFor(t) }"
                :disabled="targetMenu.mode === 'target' && routeBlockedFor(t)"
                :title="targetMenu.mode === 'target' && routeBlockedFor(t) ? 'Source frame is non-FX (Frame-B) — cross-currency unavailable' : ''"
                @click="targetMenu.mode === 'source' ? pickSource(t) : (routeBlockedFor(t) ? null : pickTarget(t))">
          <span class="iht-tmenu-nm">{{ t.name }}</span>
          <span class="iht-tmenu-ccy" :class="{ 'iht-tmenu-bvt': !!t.currency && t.currency !== ownCcy }">{{ targetMenu.mode === 'target' && routeBlockedFor(t) ? 'no FX' : t.currency }}</span>
        </button>
      </div>
    </section>

    <!-- RIGHT: live mTLS log -->
    <aside class="iht-rail iht-right">
      <div class="iht-panel-h">
        LIVE mTLS FEED
        <span class="iht-live" v-if="!logPaused"><span class="iht-live-dot"></span>LIVE</span>
        <span class="iht-live iht-paused" v-else>PAUSED</span>
      </div>
      <div class="iht-logfilters">
        <button v-for="f in (['all','mtls','probe','err'] as const)" :key="f" class="iht-lf" :class="{ 'iht-lf-on': logFilter === f }" @click="logFilter = f">{{ f === 'all' ? 'ALL' : f === 'mtls' ? 'mTLS' : f === 'probe' ? 'PROBE' : 'ERR' }}</button>
        <button class="iht-lf iht-lf-pause" :title="logPaused ? 'resume autoscroll' : 'pause autoscroll'" @click="logPaused = !logPaused">{{ logPaused ? '▶' : '⏸' }}</button>
      </div>
      <div ref="logEl" class="iht-log">
        <div v-for="(l, i) in filteredLog" :key="i" class="iht-logline" :class="'iht-ll-' + l.kind">
          <span class="iht-lt">{{ l.t }}</span>
          <span class="iht-lk">{{ l.tag }}</span>
          <span class="iht-lm" v-html="l.msg"></span>
        </div>
        <p v-if="!filteredLog.length" class="iht-empty">awaiting mTLS activity…</p>
      </div>
    </aside>

    <!-- BOTTOM: graph strip -->
    <footer class="iht-graph">
      <div class="iht-metric">
        <span class="iht-mk">LIVE ACTIVITY</span>
        <span class="iht-mv">{{ actTotal }} <span class="iht-mv-sub">evt</span></span>
        <svg class="iht-spark" viewBox="0 0 100 20" preserveAspectRatio="none"><polyline :points="actSpark" /></svg>
      </div>
      <div class="iht-metric">
        <span class="iht-mk">ROUTES FIRED</span>
        <span class="iht-mv iht-grn">{{ routesFired }}</span>
        <span class="iht-mspark" style="letter-spacing:0">auth/24h {{ ih_num(cn.summary.cycles_24h) }}</span>
      </div>
      <div class="iht-metric">
        <span class="iht-mk">PASS RATE</span>
        <span class="iht-mv" :class="passOk ? 'iht-grn' : 'iht-red'">{{ passRate }}</span>
      </div>
      <div class="iht-metric">
        <span class="iht-mk">REVOCATION p95</span>
        <span class="iht-mv">{{ revP95 }}</span>
      </div>
      <div class="iht-metric">
        <span class="iht-mk">ACTIVE PATHS</span>
        <span class="iht-mv">{{ cn.summary.active_paths }}</span>
      </div>
      <div class="iht-metric iht-metric-wide">
        <span class="iht-mk">mTLS PATHS (agent-SVID transport)</span>
        <div class="iht-pathbars">
          <div v-for="p in (cn.per_path || []).slice(0, 8)" :key="p.path_id" class="iht-pathbar" :title="`${p.path_id} · ${p.pass_rate_24h}%`">
            <div class="iht-pathbar-fill" :style="{ height: Math.max(6, (p.pass_rate_24h || 0)) + '%', background: (p.pass_rate_24h || 0) >= 99 ? '#00e676' : (p.pass_rate_24h || 0) >= 90 ? '#ffab00' : '#ff1744' }"></div>
          </div>
        </div>
      </div>
    </footer>
  </div>

  <transition name="iht-toast"><div v-if="toast" class="iht-toast" :class="'iht-toast-' + toastKind">{{ toast }}</div></transition>
  <!-- broken-machine glitch on revoke / failure -->
  <GlitchOverlay :intensity="glitch" />
</div>
</template>

<script setup lang="ts">
import { escapeHtml as esc } from '@/utils/escapeHtml'
import { appLocale } from '@/services/appLocale'
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useAlive } from '@/composables/useAlive'
import { apiClient } from '@/services/api/client'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import GalacticMap from '@/views/GalacticMap.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import GlitchOverlay from '@/components/GlitchOverlay.vue'
import { getCanaryIronhandStatus, getCanaryIronhandEvents } from '@/services/api/canaryIronhand'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

// ── state ──────────────────────────────────────────────────────
const ih = ref<any>({ summary: { db_enrolled: 0, db_revoked: 0, agent_entries: 0, total_spire_entries: 0, orphan_entries: 0, missing_entries: 0 }, enrolled: [], revoked: [], orphans: [] })
/** §FESUITE V0577: the identities read was kept quiet and `ih` starts at zeros, so a failed read said SPIRE FABRIC
 *  NOMINAL in green over "enrolled 0", "revoked 0", "SPIRE entries 0/0" and "No enrolled mTLS identities." */
const ihRead = ref<'reading' | 'read' | 'unread'>('reading')
const cn = ref<any>({ summary: { active_paths: 0, cycles_24h: 0, passes_24h: 0, failures_24h: 0, pass_rate_24h: null, revocation_p95_propagation_ms: null }, per_path: [] })
// Topology + nodes + edges now come from the embedded real <GalacticMap> (its untouched
// pipeline) — accessed via canvasRef.getNodes()/getNodePos(). No lean adapter here.
const followDid = ref<string>('')
const logLines = ref<{ t: string; tag: string; msg: string; kind: string }[]>([])
const logEl = ref<HTMLElement | null>(null)
const probeBusy = ref(false)
const selectedTarget = ref('')
// Cluster cockpit (hub / registry-a only): fire AS any registry's probe/agent. '' = local probe.
const selectedSource = ref('')
const selectedSourceName = ref('')
const selectedSourceReg = ref('')
const isHub = ref(false)                               // registry-a → source picker enabled
const pickStage = ref<'source' | 'target'>('source')  // which the NEXT right-click sets (hub)
const localRegistry = ref('')                          // this Theatre's home registry
const followAll = ref(false)                           // unhide the map's native agent layer (all left-menu identities)
const soloDid = ref('')                                // show ONLY this one identity on the map (single left-menu click)
const targetOptions = ref<any[]>([])
const ihFetchedAt = ref(0)                             // when identities last fetched → live SVID countdown
// Right-click menu (registry node → its agents). mode: ① pick SOURCE or ② pick TARGET.
const targetMenu = ref<{ open: boolean; mode: 'source' | 'target'; x: number; y: number; node: string; items: any[] }>({ open: false, mode: 'target', x: 0, y: 0, node: '', items: [] })
async function loadTargets() {
  // Federation-wide targetable agents (mTLS-enrolled) from the probe-panel endpoint —
  // each carries name + home registry so the picker shows "name · registry" (not raw DIDs).
  const opts: any[] = []
  try {
    const r = await apiClient.get('/admin/ironhand/targets', { timeout: 12000 })
    isHub.value = !!r.data?.is_hub   // hub (registry-a) → cluster source picker enabled
    localRegistry.value = r.data?.local_registry || ''
    for (const a of (r.data?.targets || [])) {
      opts.push({
        did: a.did, name: a.name, registry: a.registry,
        trust_domain: a.trust_domain, currency: a.currency, mtls: a.mtls,
        fx_capable: a.fx_capable !== false,   // home frame is FX-capable (Frame-B/east = false)
        label: `${a.name} · ${a.registry}${a.currency && a.currency !== currentOwnCurrency() ? `  (${a.currency})` : ''}`,
      })
    }
  } catch { /* endpoint optional */ }
  targetOptions.value = opts
}
// Right-click a registry node → its agents. On the hub this is a two-stage flow:
// ① first right-click sets the SOURCE (any registry's probe/agent — fired remotely on its
// home registry), ② second sets the TARGET. Off the hub it's target-only (local probe).
function onMapContextMenu(e: MouseEvent) {
  const cont = canvasRef.value?.getContainer?.()
  if (!cont || !targetOptions.value.length) return
  e.preventDefault()
  const rect = cont.getBoundingClientRect()
  const cx = e.clientX - rect.left, cy = e.clientY - rect.top
  let best: any = null, bestD = 1e9
  for (const n of ((canvasRef.value?.getNodes?.() || []) as any[])) {
    const p = screenPos(n.id); if (!p) continue
    const d = Math.hypot(p.x - cx, p.y - cy)
    if (d < bestD) { bestD = d; best = n }
  }
  if (!best || bestD > 80) { targetMenu.value.open = false; return }
  const nm = normName(best.name)
  let items = targetOptions.value.filter((t: any) => {
    const tr = normName(t.registry)
    return tr === nm || (!!tr && !!nm && (tr.includes(nm) || nm.includes(tr)))
  })
  if (!items.length) items = targetOptions.value
  const mode = (isHub.value && pickStage.value === 'source') ? 'source' : 'target'
  targetMenu.value = { open: true, mode, x: cx, y: cy, node: best.name, items }
}
function pickSource(t: any) {
  selectedSource.value = t.did
  selectedSourceName.value = t.name
  selectedSourceReg.value = t.registry
  targetMenu.value.open = false
  pickStage.value = 'target'
  showToast(`① Source: ${t.name} · ${t.registry} — now right-click a target ②`, 'ok')
  pushLog('PROBE', `① source set → <b>${esc(t.name)}</b> · ${esc(t.registry)} · right-click a target next`, 'mtls')
}
function pickTarget(t: any) {
  selectedTarget.value = t.did
  targetMenu.value.open = false
  if (isHub.value) pickStage.value = 'source'   // ready for the next round
  showToast(`${isHub.value ? '② ' : ''}Target: ${t.name} · ${t.registry}`, 'ok')
  pushLog('PROBE', `${esc(isHub.value ? '② ' : '')}target set → <b>${esc(t.name)}</b> · ${esc(t.registry)}`, 'mtls')
}
// Toolbar SOURCE dropdown (hub) mirrors the right-click source pick.
function onSourceSelect() {
  const t = targetOptions.value.find((x: any) => x.did === selectedSource.value)
  selectedSourceName.value = t?.name || ''
  selectedSourceReg.value = t?.registry || ''
  pickStage.value = selectedSource.value ? 'target' : 'source'
}
function targetName(did: string) { const t = targetOptions.value.find((x: any) => x.did === did); return t?.name || '' }
// FX-aware: a source on a non-FX frame (Frame-B/east) cannot originate a cross-currency
// route (AVT↔BVT). FX mesh = Frame-A (west) ↔ Frame-C (middle-east). Mirrors the card's
// fees.fx capability; the backend probe guard is authoritative.
const selectedSourceOpt = computed(() => targetOptions.value.find((x: any) => x.did === selectedSource.value) || null)
function routeBlockedFor(t: any): boolean {
  const s = selectedSourceOpt.value
  if (!s || !t) return false
  return s.fx_capable === false && t.currency !== s.currency
}
// ── Follow-All: unhide the embedded GalacticMap's OWN agent layer (agents render at their
//    real positions with the map's native hover-label + click→AgentDetailModal). It just
//    flips the reactive :hide-agents binding — no freestyled overlay. ──
function _nudgeMap() { for (const d of [60, 450]) setTimeout(() => window.dispatchEvent(new Event('resize')), d) }
function toggleFollowAll() {
  followAll.value = !followAll.value
  soloDid.value = ''   // SHOW ALL / HIDE ALL is mutually exclusive with a single-identity solo
  pushLog('IDENTITY', followAll.value ? `showing ALL ${enrolledList.value.length} identities on the map` : 'agents hidden', 'probe')
  _nudgeMap()
}
// Click a left-menu identity → show ONLY that one on the map (+ turn off SHOW ALL). Click it
// again → hide. Uses the same GalacticMap agent layer (native hover label + click→card modal).
function selectIdentity(a: any) {
  followDid.value = a.did
  if (soloDid.value === a.did) {
    soloDid.value = ''
    pushLog('IDENTITY', `${esc(agentName(a))} hidden`, 'probe')
  } else {
    soloDid.value = a.did; followAll.value = false
    pushLog('IDENTITY', `showing only <b>${esc(agentName(a))}</b> on the map`, 'probe')
  }
  _nudgeMap()
}
const toast = ref(''); const toastKind = ref('ok')
let timer: any = null
let tickTimer: any = null
// ── Cut 3 state ──
const glitch = ref(0)                 // GlitchOverlay intensity 0..1 (revoke / failure drama)
const logFilter = ref<'all' | 'mtls' | 'probe' | 'err'>('all')
const logPaused = ref(false)
const routesFired = ref(0)            // identity probes fired this session
const nowTs = ref(Date.now())         // ticks every 1s → live SVID TTL countdowns
const actBuckets = ref<number[]>(new Array(40).fill(0))  // rolling activity sparkline
let lastLogLen = 0
const revoking = ref('')              // did currently being revoked

const enrolledList = computed(() => ih.value.enrolled || [])
// DIDs of the left-menu identities — the allowlist Follow-All unhides on the map.
const enrolledDids = computed<string[]>(() => (ih.value.enrolled || []).map((a: any) => a.did).filter(Boolean))
const fabricOk = computed(() => {
  // Real degradation = SPIRE drift (orphan entries) or a FAILING agent-SVID canary.
  // `missing_entries` (DB-enrolled identities with no running labelled container — e.g.
  // Encryption Edmond) is NORMAL and must NOT read as degraded. No canary data (null) = fine.
  const pr = cn.value.summary.pass_rate_24h
  if (pr != null && Number(pr) < 90) return false
  return (ih.value.summary.orphan_entries || 0) === 0
})
const revP95 = computed(() => {
  const v = cn.value.summary.revocation_p95_propagation_ms
  return v == null ? '—' : `${Math.round(v)}ms`
})
const passRate = computed(() => {
  const v = cn.value.summary.pass_rate_24h
  return v == null ? '—' : `${Number(v).toFixed(2)}%`
})
const passOk = computed(() => (cn.value.summary.pass_rate_24h || 0) >= 99)
const sparkPass = computed(() => {
  const r = cn.value.summary.pass_rate_24h || 0
  const n = Math.round((r / 100) * 8)
  return '▁▂▃▄▅▆▇█'.slice(0, Math.max(1, n)) || '▁'
})
const probeHint = computed(() => 'Drive the live local agent (Ironhand Alpha) to authenticate as Encryption Edmond and travel a real FX route across the federation.')

// ── Cut 3 computeds ──
const filteredLog = computed(() => logFilter.value === 'all' ? logLines.value : logLines.value.filter(l => l.kind === logFilter.value))
function svidTtl(a: any): { label: string; pct: number; low: boolean } {
  // SVID is a 30-min rotating cert. The backend returns the live remaining within the
  // current rotation window (svid_remaining_seconds); we count it down locally between
  // 8s refreshes (re-anchored to ihFetchedAt each fetch) so it never sticks at 00:00.
  // (The old code counted down from mtls_enrolled_at → floored to "000" on every frame/op
  // whose probe was enrolled >30min ago. That was the bug.)
  const ttl = a?.svid_ttl_seconds || 1800
  if (a?.svid_remaining_seconds == null) {
    if (!a?.enrolled_at) return { label: '—', pct: 0, low: false }
    const el = Math.max(0, (nowTs.value - new Date(a.enrolled_at).getTime()) / 1000)
    const r0 = Math.round(ttl - (el % ttl))
    const m0 = Math.floor(r0 / 60), s0 = r0 % 60
    return { label: `${m0}:${String(s0).padStart(2, '0')}`, pct: (r0 / ttl) * 100, low: r0 < 300 }
  }
  const elapsed = (nowTs.value - (ihFetchedAt.value || nowTs.value)) / 1000
  let rem = Math.round(a.svid_remaining_seconds - elapsed)
  if (rem < 0) rem = ((rem % ttl) + ttl) % ttl   // wrapped a rotation before the next refresh
  const m = Math.floor(rem / 60), s = rem % 60
  return { label: `${m}:${String(s).padStart(2, '0')}`, pct: Math.max(0, Math.min(100, (rem / ttl) * 100)), low: rem < 300 }
}
const actSpark = computed(() => {
  const a = actBuckets.value, max = Math.max(1, ...a), n = a.length
  return a.map((v, i) => `${(i / (n - 1) * 100).toFixed(1)},${(20 - (v / max) * 18).toFixed(1)}`).join(' ')
})
const actTotal = computed(() => actBuckets.value.reduce((s, v) => s + v, 0))

// ── helpers ────────────────────────────────────────────────────
function agentName(a: any) {
  if (a.name && !String(a.name).startsWith('did:')) return a.name
  const p = (a.did || '').split(':'); return p.length >= 3 ? p[2].slice(0, 14) : (a.did || '—')
}
/** §FEFRAME W2: this frame's own unit; a target in another unit is the cross-currency one. */
const ownCcy = computed(() => currentOwnCurrency())
function shortSpiffe(s: string) {
  if (!s) return '—'
  // §FEFRAME W2: any frame's trust domain, not the retired Frame A's
  const m = s.match(/^spiffe:\/\/[^/]+\/agent\//)
  return m ? '…/' + s.slice(m[0].length, m[0].length + 22) + '…' : s.slice(0, 36) + '…'
}
function timeAgo(ts: string | null) { return ts ? dayjs(ts).fromNow() : '—' }
function ih_num(n: number) { return (n || 0).toLocaleString(appLocale()) }
function nowT() { return dayjs().format('HH:mm:ss') }
/* §COCKPITDESK (2026-10-15) SECURITY: a line is HTML (v-html) and its values are names someone else chose (an agent's
 * name, a registry's, a path's): every interpolation goes through esc(), so a name like <img onerror=…> stays text. */
function pushLog(tag: string, msg: string, kind = 'mtls') {
  logLines.value.push({ t: nowT(), tag, msg, kind })
  if (logLines.value.length > 200) logLines.value.splice(0, logLines.value.length - 200)
  if (!logPaused.value) nextTick(() => { if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight })
}
function showToast(m: string, k = 'ok') { toast.value = m; toastKind.value = k; setTimeout(() => (toast.value = ''), 2600) }

// ── data: topology/edges/nodes are owned by the embedded real <GalacticMap>.
//   orb path resolves slugs → node ids via canvasRef.getNodes() + getNodePos(). ──

async function fetchIronhand() {
  try { const r = await apiClient.get('/admin/ironhand/identities', { timeout: 15000 }); ih.value = r.data
    ihRead.value = 'read'
    ihFetchedAt.value = Date.now()   // anchor for the live SVID countdown
    if (!followDid.value && (ih.value.enrolled || []).length) followDid.value = ih.value.enrolled[0].did
  } catch { if (ihRead.value !== 'read') ihRead.value = 'unread' /* a failed refresh keeps what was shown */ }
}

let lastEventIds = new Set<string>()
let canaryPrimed = false
async function fetchCanary() {
  try {
    cn.value = await getCanaryIronhandStatus()
  } catch { /* keep */ }
  try {
    const ev = await getCanaryIronhandEvents({ limit: 12 })
    // surface new events into the live feed (newest first from API → reverse to chrono)
    let animCandidate: any = null
    for (const e of (ev.events || []).slice().reverse()) {
      const id = e.test_id || `${e.transfer_id}`
      if (!id || lastEventIds.has(id)) continue
      lastEventIds.add(id)
      const ok = (e.outcome === 'passed')
      pushLog('mTLS', `<b>${esc((e.path_human || e.path_id || 'path'))}</b> ${esc(e.transport === 'ironhand_mtls' ? '· agent-SVID' : '')} → <span class="${esc(ok ? 'iht-grn' : 'iht-red')}">${esc(e.outcome)}</span> ${esc(e.http_latency_ms ? '· ' + e.http_latency_ms + 'ms' : '')}`, ok ? 'mtls' : 'err')
      // Auto-animate the orb for a freshly-PASSED cross-frame FX cycle (≥2-hop corridor).
      // Skip the initial prime (don't replay the backlog burst) + intra/local (no node_path).
      if (canaryPrimed && ok && Array.isArray(e.node_path) && e.node_path.length >= 2) animCandidate = e
    }
    if (lastEventIds.size > 400) lastEventIds = new Set(Array.from(lastEventIds).slice(-200))
    // One orb at a time: drive the newest fresh FX cycle only when idle — the manual
    // ▶ Fire-Probe always wins (probeBusy / orb.visible guard). This is what makes the
    // canaries "visible in the Theatre on every cycle" without a manual click.
    if (animCandidate && !orb.visible && !probeBusy.value) {
      routesFired.value++
      const prof = await fetchAgentProfile(animCandidate.sender_did)
      const nm = prof?.card_data?.name || prof?.name || animCandidate.path_human || 'canary'
      animateRoute(animCandidate.node_path, prof, { name: nm, spiffe: animCandidate.origin_agent_spiffe || '' })
    }
    canaryPrimed = true
  } catch { /* keep */ }
}

// ── traveling identity orb (Cut 2) ─────────────────────────────
const canvasRef = ref<any>(null)
const orb = reactive<{ visible: boolean; x: number; y: number; name: string; spiffeShort: string; avatarUrl: string | null; agent: any; pulse: boolean; broken: boolean }>(
  { visible: false, x: 0, y: 0, name: '', spiffeShort: '', avatarUrl: null, agent: {}, pulse: false, broken: false })
const beacons = ref<{ id: number; x: number; y: number }[]>([])
let beaconSeq = 0
const orbTrail = ref<{ id: number; x: number; y: number }[]>([])
let trailSeq = 0
let rafId: any = null
const profileCache = new Map<string, any>()

async function fetchAgentProfile(did: string) {
  if (!did) return null
  if (profileCache.has(did)) return profileCache.get(did)
  try {
    const r = await apiClient.get(`/agents/by-did/${encodeURIComponent(did)}`)
    const j = r.data || {}
    const cf = (j.card_data && j.card_data.flare) || {}
    const prof = {
      ...j,
      flare_tier: j.flare_tier ?? cf.tier ?? j.card_data?.flare_tier ?? null,
      flare_encirclement_variant: j.flare_encirclement_variant ?? cf.encirclement_variant ?? null,
      flare_encirclement_overlay: j.flare_encirclement_overlay ?? cf.encirclement_overlay ?? null,
    }
    profileCache.set(did, prof); return prof
  } catch { return null }
}
function normName(s: string) { return (s || '').toLowerCase().replace(/[^a-z0-9]/g, '') }
function resolveNodeId(slug: string): string | null {
  const target = normName(slug); if (!target) return null
  let best: string | null = null
  for (const r of ((canvasRef.value?.getNodes?.() || []) as any[])) {
    for (const c of [normName(r.name), normName(r.id), normName(r.trustDomain || '')]) {
      if (!c) continue
      if (c === target) return r.id
      if (target.length >= 4 && (c.includes(target) || target.includes(c))) best = best || r.id
    }
  }
  return best
}
function screenPos(id: string): { x: number; y: number } | null {
  const cv = canvasRef.value
  if (!cv || !cv.getNodePos || !cv.getCamera || !cv.getContainer) return null
  const v = cv.getNodePos(id), cam = cv.getCamera(), cont = cv.getContainer()
  if (!v || !cam || !cont) return null
  const p = v.clone().project(cam); const rect = cont.getBoundingClientRect()
  return { x: (p.x * 0.5 + 0.5) * rect.width, y: (-p.y * 0.5 + 0.5) * rect.height }
}
const smoothstep = (t: number) => t * t * (3 - 2 * t)

function animateRoute(nodePath: string[], agentProfile: any, meta: { name: string; spiffe: string }) {
  if (rafId) { cancelAnimationFrame(rafId); rafId = null }
  const ids = nodePath.map(resolveNodeId).filter(Boolean) as string[]
  const seq = ids.filter((id, i) => i === 0 || id !== ids[i - 1])
  if (seq.length < 1) { showToast('Route path unresolved on this map view (' + nodePath.join('→') + ')', 'warn'); return }
  if (seq.length === 1) seq.push(seq[0])  // local / same-node transfer → pulse the node, no travel
  orb.name = meta.name; orb.spiffeShort = shortSpiffe(meta.spiffe)
  orb.agent = agentProfile || {}; orb.avatarUrl = agentProfile?.card_data?.iconUrl || agentProfile?.card_data?.icon_url || null
  orb.visible = true; orb.pulse = false; orbTrail.value = []
  pushLog('IDENTITY', `<b>${esc(meta.name)}</b> enters the federation — SPIFFE ${esc(shortSpiffe(meta.spiffe))}`, 'probe')
  const SEG_MS = 2200, stamped = new Array(seq.length).fill(false), start = performance.now()
  function frame(now: number) {
    const elapsed = now - start
    const tf = Math.min(elapsed / SEG_MS, seq.length - 1)
    const seg = Math.min(Math.floor(tf), seq.length - 2)
    const local = smoothstep(tf - seg)
    const a = screenPos(seq[seg]), b = screenPos(seq[seg + 1])
    if (a && b) {
      let nx = a.x + (b.x - a.x) * local, ny = a.y + (b.y - a.y) * local
      // Keep the capsule inside the stage even when a route node projects off-viewport
      // (the embedded map is narrower than the full GalacticMap, so far nodes can sit off-edge).
      const cont = canvasRef.value?.getContainer?.()
      if (cont) { const r = cont.getBoundingClientRect(), m = 32; nx = Math.max(m, Math.min(r.width - m, nx)); ny = Math.max(m, Math.min(r.height - m, ny)) }
      orb.x = nx; orb.y = ny
      const tl = orbTrail.value, last = tl[tl.length - 1]
      if (!last || Math.hypot(orb.x - last.x, orb.y - last.y) > 9) { tl.push({ id: ++trailSeq, x: orb.x, y: orb.y }); if (tl.length > 12) tl.shift() }
    }
    const idx = Math.round(tf)
    if (idx > 0 && idx < seq.length && !stamped[idx] && (tf - idx) > -0.05 && (tf - idx) < 0.15) {
      stamped[idx] = true
      const pos = screenPos(seq[idx])
      if (pos) { const bid = ++beaconSeq; beacons.value.push({ id: bid, x: pos.x - 22, y: pos.y - 22 }); setTimeout(() => { beacons.value = beacons.value.filter(z => z.id !== bid) }, 1300) }
      orb.pulse = true; setTimeout(() => (orb.pulse = false), 500)
      const nm = ((canvasRef.value?.getNodes?.() || []) as any[]).find(r => r.id === seq[idx])?.name || seq[idx]
      pushLog('mTLS', `✔ authenticated at <b>${esc(nm)}</b> · transport peer = service SVID · identity rides`, 'mtls')
    }
    if (elapsed < SEG_MS * (seq.length - 1) + 250) { rafId = requestAnimationFrame(frame) }
    else { orb.pulse = true; pushLog('IDENTITY', `<b>${esc(meta.name)}</b> arrived — route settled · Δ=0`, 'probe'); setTimeout(() => { orb.visible = false; orb.pulse = false; orbTrail.value = [] }, 4200) }
  }
  rafId = requestAnimationFrame(frame)
}

async function fireProbe() {
  if (!selectedTarget.value) { showToast('Pick a target DID first', 'warn'); return }
  const _tOpt = targetOptions.value.find((x: any) => x.did === selectedTarget.value)
  if (routeBlockedFor(_tOpt)) {
    showToast(`${selectedSourceName.value || 'source'} is on a non-FX frame (Frame-B/east) — pick a same-currency (${selectedSourceOpt.value?.currency}) target`, 'warn')
    pushLog('PROBE', `blocked: <b>${esc(selectedSourceName.value)}</b> is non-FX (Frame-B) → cross-currency route unavailable`, 'err')
    return
  }
  probeBusy.value = true
  const srcLabel = selectedSourceName.value
    ? `${selectedSourceName.value}${selectedSourceReg.value ? ' · ' + selectedSourceReg.value : ''}`
    : 'local probe'
  pushLog('PROBE', `Firing <b>${esc(srcLabel)}</b> → <b>${esc(selectedTarget.value.slice(0, 28))}…</b>`, 'probe')
  try {
    const body: any = { target_did: selectedTarget.value }
    if (selectedSource.value) body.source_did = selectedSource.value   // hub: fire AS this agent (maybe remote)
    const r = await apiClient.post('/admin/ironhand/probe', body, { timeout: 95000 })
    const d = r.data || {}
    if (!d.ok) {
      showToast(`Probe ${d.method || ''} → did not settle (http ${d.http_status || '?'})`, 'warn')
      pushLog('PROBE', `<b>${esc(d.source_name || 'probe')}</b> ${esc((d.method || '?').toUpperCase())} → <span class="iht-red">FAIL</span> http=${esc(d.http_status || '?')}`, 'err')
      triggerGlitch(0.6)
    } else {
      routesFired.value++
      showToast(`${d.source_name || 'probe'} · ${d.method} · ${d.amount} ${d.currency} · ${d.latency_ms}ms · settled`, 'ok')
      pushLog('PROBE', `<b>${esc(d.source_name || 'probe')}</b> ${esc((d.method || '').toUpperCase())} ${esc(d.amount)} ${esc(d.currency)} → <span class="iht-grn">settled</span> · ${esc(d.latency_ms)}ms`, 'mtls')
    }
    const prof = await fetchAgentProfile(d.source)
    animateRoute(d.node_path || [], prof, { name: d.source_name || 'probe', spiffe: '' })
  } catch (e: any) {
    showToast('Probe error: ' + (e?.response?.data?.detail || e?.message || 'failed'), 'warn')
    pushLog('PROBE', 'probe error: ' + esc(e?.response?.data?.detail || e?.message || ''), 'err'); triggerGlitch(0.6)
  } finally { probeBusy.value = false }
}

// ── Cut 3: revoke → broken-machine glitch + <500ms propagation ──
function triggerGlitch(peak = 0.85) {
  glitch.value = peak
  const decay = () => { glitch.value = Math.max(0, glitch.value - 0.07); if (glitch.value > 0.001) setTimeout(decay, 55) }
  setTimeout(decay, 260)
}
async function revokeIdentity(a: any) {
  if (revoking.value) return
  revoking.value = a.did
  pushLog('REVOKE', `revoking <b>${esc(agentName(a))}</b> — broadcasting AgentMtlsRevoked…`, 'err')
  triggerGlitch(0.9)
  if (orb.visible && (orb.name === agentName(a) || orb.spiffeShort === shortSpiffe(a.spiffe_id))) orb.broken = true
  try {
    await apiClient.post(`/admin/ironhand/revoke/${encodeURIComponent(a.did)}`, {}, { timeout: 20000 })
    pushLog('REVOKE', `✔ <b>${esc(agentName(a))}</b> revoked — propagated to peers in &lt;500ms (EventStore WS) · SVID expires &le;30m`, 'err')
    showToast(`Revoked ${agentName(a)} · <500ms WS propagation`, 'warn')
    await fetchIronhand()
  } catch (e: any) {
    pushLog('REVOKE', 'revoke failed: ' + esc(e?.response?.data?.detail || e?.message || ''), 'err')
    showToast('Revoke failed', 'warn')
  } finally { revoking.value = ''; setTimeout(() => { orb.broken = false }, 2500) }
}
// 1s tick: live SVID TTL countdowns + rolling activity sparkline
function tick() {
  nowTs.value = Date.now()
  const delta = Math.max(0, logLines.value.length - lastLogLen); lastLogLen = logLines.value.length
  const a = actBuckets.value; a.push(delta); if (a.length > 40) a.shift()
}

async function refreshAll() { await Promise.all([fetchIronhand(), fetchCanary()]); loadTargets() }

// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a theatre left during its first read starts no poll or ticker when it lands
const alive = useAlive()
onMounted(async () => {
  await refreshAll()
  if (!alive()) return
  timer = setInterval(refreshAll, 8000)
  tickTimer = setInterval(tick, 1000)   // SVID TTL countdowns + activity sparkline
  // The embedded GalacticMapCanvas measures its container only on mount/window-resize;
  // kick a few resizes after the grid settles so it picks up the real (non-zero) height.
  for (const d of [400, 1200, 2500]) setTimeout(() => window.dispatchEvent(new Event('resize')), d)
})
onUnmounted(() => { if (timer) clearInterval(timer); if (tickTimer) clearInterval(tickTimer); if (rafId) cancelAnimationFrame(rafId) })
</script>

<style scoped>
.iht {
  --cy: var(--nc-primary); --txt: #e2e8f0; --txt2: #94a3b8; --muted: #64748b;
  --bd: rgba(255,255,255,0.07); --mono: 'IBM Plex Mono','JetBrains Mono','Fira Code',monospace;
  /* Fit the DashboardLayout content area (it reserves the 64px app bar) so the bottom
     graph strip is never clipped. min-height:0 lets the 1fr stage row compress. */
  position: relative; z-index: 1; height: calc(100vh - 64px); min-height: 0; display: flex; flex-direction: column;
  color: #b0bec5; overflow: hidden;
}
/* command bar */
.iht-bar { display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 20px; border-bottom: 1px solid var(--bd); background: rgba(8,11,20,0.72); backdrop-filter: blur(6px); flex-wrap: wrap; }
.iht-bar-id { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.iht-chip { display: inline-flex; align-items: center; gap: 7px; font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: .22em; color: var(--cy); border: 1px solid rgba(var(--nc-primary-rgb),.28); background: rgba(var(--nc-primary-rgb),.07); padding: 4px 12px; border-radius: 3px; }
.iht-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cy); animation: ihtp 2s ease-in-out infinite; }
@keyframes ihtp { 0%,100%{opacity:1} 50%{opacity:.3} }
.iht-title { font-size: 19px; font-weight: 700; color: #fff; margin: 0; letter-spacing: -.01em; }
.iht-accent { color: var(--cy); }
.iht-sub { font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: .04em; }
.iht-pills { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.iht-pill { display: inline-flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 10px; color: var(--txt2);
  background: rgba(10,14,24,.7); border: 1px solid var(--bd); border-radius: 4px; padding: 5px 10px; letter-spacing: .04em; }
.iht-pill strong { color: var(--txt); font-size: 12px; }
.iht-pill-k { color: var(--muted); text-transform: uppercase; font-size: 9px; }
.iht-pill-ok { border-color: rgba(0,230,118,.3); } .iht-pill-ok .iht-pill-dot { background: #00e676; }
.iht-pill-bad { border-color: rgba(255,23,68,.4); } .iht-pill-bad .iht-pill-dot { background: #ff1744; }
.iht-pill-dot { width: 7px; height: 7px; border-radius: 50%; box-shadow: 0 0 6px currentColor; }
.iht-red { color: #ff5470 !important; } .iht-grn { color: #00e676 !important; } .iht-dim { color: var(--muted); }
.iht-fire { display: inline-flex; align-items: center; gap: 7px; font-family: var(--mono); font-size: 11px; font-weight: 700;
  letter-spacing: .08em; color: #061018; background: linear-gradient(90deg, var(--cy), #00e676); border: none; border-radius: 5px;
  padding: 7px 16px; cursor: pointer; transition: filter .15s, transform .1s; box-shadow: 0 0 18px rgba(var(--nc-primary-rgb),.3); }
.iht-fire:hover:not(:disabled) { filter: brightness(1.12); transform: translateY(-1px); }
.iht-fire:disabled { opacity: .55; cursor: progress; }
.iht-fire-ico { font-size: 9px; }
.iht-target { font-family: var(--mono); font-size: 11px; color: var(--nc-text, #cfe);
  background: rgba(8,18,28,.85); border: 1px solid rgba(var(--nc-primary-rgb),.45); border-radius: 5px;
  padding: 6px 10px; width: 230px; outline: none; }
.iht-target:focus { border-color: var(--cy); box-shadow: 0 0 10px rgba(var(--nc-primary-rgb),.35); }
.iht-target::placeholder { color: rgba(180,200,220,.5); }
/* cluster cockpit (hub): SOURCE picker + armed source→target route chip */
.iht-source { width: 210px; border-color: rgba(124,255,178,.5); }
.iht-source:focus { border-color: #7CFFB2; box-shadow: 0 0 10px rgba(124,255,178,.3); }
.iht-route { display: inline-flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 10px;
  color: var(--txt2); background: rgba(10,14,24,.7); border: 1px solid var(--bd); border-radius: 4px; padding: 5px 10px; }
.iht-route b { color: var(--txt); font-weight: 600; }
.iht-route-arw { color: var(--cy); }
/* right-click target menu */
.iht-tmenu { position: absolute; z-index: 40; min-width: 190px; max-width: 270px; max-height: 280px; overflow-y: auto;
  background: rgba(8,16,26,.97); border: 1px solid rgba(var(--nc-primary-rgb),.5); border-radius: 8px;
  box-shadow: 0 8px 30px rgba(0,0,0,.55); padding: 5px; transform: translate(6px, 6px); }
.iht-tmenu-h { font-family: var(--mono); font-size: 9.5px; letter-spacing: .06em; text-transform: uppercase;
  color: rgba(180,210,235,.72); padding: 4px 8px 6px; border-bottom: 1px solid rgba(255,255,255,.07); margin-bottom: 3px; }
.iht-tmenu-it { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%;
  background: transparent; border: none; border-radius: 5px; padding: 6px 8px; cursor: pointer; text-align: left;
  color: var(--nc-text, #d6e6f2); font-size: 11.5px; transition: background .12s; }
.iht-tmenu-it:hover { background: rgba(var(--nc-primary-rgb),.16); }
.iht-tmenu-nm { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.iht-tmenu-ccy { font-family: var(--mono); font-size: 9px; color: var(--cy); opacity: .85; flex-shrink: 0; }
.iht-tmenu-bvt { color: #ffcf6b; }
.iht-tmenu-srcmode { border-color: rgba(124,255,178,.6); }
.iht-tmenu-srcmode .iht-tmenu-h { color: #aef5cb; }
.iht-tmenu-blocked { opacity: .4; cursor: not-allowed; }
.iht-tmenu-blocked:hover { background: transparent; }
.iht-tmenu-blocked .iht-tmenu-ccy { color: #ff7a90; }
/* Follow-All toggle (IDENTITIES header) */
.iht-followall { margin-left: auto; font-family: var(--mono); font-size: 8.5px; font-weight: 700; letter-spacing: .08em;
  color: var(--txt2); background: rgba(10,14,24,.7); border: 1px solid var(--bd); border-radius: 4px;
  padding: 3px 8px; cursor: pointer; transition: all .15s; }
.iht-followall:hover { color: var(--cy); border-color: rgba(var(--nc-primary-rgb),.45); }
.iht-followall-on { color: #061018; background: linear-gradient(90deg, var(--cy), #00e676); border-color: transparent;
  box-shadow: 0 0 12px rgba(var(--nc-primary-rgb),.35); }
/* grid */
.iht-grid { flex: 1; display: grid; grid-template-columns: 286px 1fr 330px; grid-template-rows: 1fr auto;
  grid-template-areas: "left stage right" "left graph right"; gap: 1px; background: var(--bd); min-height: 0; }
.iht-rail { background: rgba(8,11,20,.82); display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.iht-left { grid-area: left; } .iht-right { grid-area: right; }
.iht-stage { grid-area: stage; position: relative; background: #05070e; min-height: 0; overflow: hidden; }
.iht-stage :deep(canvas) { display: block; width: 100%; height: 100%; }
.iht-map { width: 100%; height: 100%; }
.iht-stage :deep(.galactic-map) { height: 100%; }
.iht-stage :deep(.gm-map-shell) { height: 100% !important; }
.iht-stage-load { position: absolute; inset: 0; z-index: 5; display: flex; flex-direction: column; gap: 12px; align-items: center; justify-content: center;
  background: rgba(5,7,14,.8); font-family: var(--mono); font-size: 12px; color: var(--muted); }
.iht-spin { width: 26px; height: 26px; border: 2px solid rgba(var(--nc-primary-rgb),.15); border-top-color: var(--cy); border-radius: 50%; animation: ihts .8s linear infinite; }
@keyframes ihts { to { transform: rotate(360deg); } }
.iht-stage-legend { position: absolute; left: 14px; bottom: 12px; z-index: 4; display: flex; gap: 14px; font-family: var(--mono); font-size: 10px; color: var(--txt2);
  background: rgba(5,8,16,.6); border: 1px solid var(--bd); border-radius: 5px; padding: 6px 12px; backdrop-filter: blur(4px); }
.iht-stage-legend span { display: inline-flex; align-items: center; gap: 6px; }
.iht-lg { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.iht-lg-orb { background: radial-gradient(circle at 35% 30%, #7dd3fc, #2563eb); }
.iht-lg-bridge { background: #ffd700; border-radius: 1px; height: 3px; width: 14px; }
.iht-lg-id { background: radial-gradient(circle at 35% 30%, #fff, var(--cy)); box-shadow: 0 0 8px var(--cy); }
.iht-stage-tag { position: absolute; right: 14px; top: 12px; z-index: 4; font-family: var(--mono); font-size: 10px; letter-spacing: .12em;
  color: var(--muted); background: rgba(5,8,16,.6); border: 1px solid var(--bd); border-radius: 4px; padding: 5px 10px; }
/* panels */
.iht-panel-h { display: flex; align-items: center; justify-content: space-between; font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: .14em; color: var(--cy); padding: 11px 14px; border-bottom: 1px solid var(--bd); text-transform: uppercase; }
.iht-count { color: var(--muted); background: rgba(255,255,255,.05); border-radius: 3px; padding: 1px 6px; font-size: 9px; }
.iht-live { display: inline-flex; align-items: center; gap: 5px; color: #00e676; font-size: 9px; }
.iht-live-dot { width: 6px; height: 6px; border-radius: 50%; background: #00e676; animation: ihtp 1.4s ease-in-out infinite; }
/* identities */
.iht-idlist { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.iht-idcard { background: rgba(var(--nc-primary-rgb),.03); border: 1px solid var(--bd); border-left: 2px solid var(--muted); border-radius: 5px; padding: 9px 11px; cursor: pointer; transition: all .15s; }
.iht-idcard:hover { border-color: rgba(var(--nc-primary-rgb),.25); background: rgba(var(--nc-primary-rgb),.06); }
.iht-idcard-sel { border-left-color: var(--cy); background: rgba(var(--nc-primary-rgb),.09); }
.iht-idtop { display: flex; align-items: center; gap: 7px; }
.iht-iddot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.iht-dot-ok { background: #00e676; box-shadow: 0 0 6px rgba(0,230,118,.5); } .iht-dot-warn { background: #ffab00; }
.iht-idname { font-size: 12px; color: var(--txt); font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.iht-followpill { font-family: var(--mono); font-size: 8px; color: var(--cy); border: 1px solid rgba(var(--nc-primary-rgb),.4); border-radius: 3px; padding: 1px 5px; letter-spacing: .08em; }
.iht-idspiffe { font-family: var(--mono); font-size: 9px; color: var(--muted); margin-top: 3px; }
.iht-idmeta { font-family: var(--mono); font-size: 9px; color: var(--txt2); margin-top: 3px; display: flex; gap: 5px; text-transform: uppercase; }
.iht-cfg { border-top: 1px solid var(--bd); padding: 10px 14px; display: flex; flex-direction: column; gap: 5px; }
.iht-cfg-row { display: flex; justify-content: space-between; font-family: var(--mono); font-size: 10px; color: var(--muted); }
.iht-cfg-row b { color: var(--txt); } .iht-cfg-row b.iht-grn { color: #00e676; }
/* log */
.iht-log { flex: 1; overflow-y: auto; padding: 8px 10px; font-family: var(--mono); font-size: 10.5px; display: flex; flex-direction: column; gap: 3px; }
.iht-logline { display: flex; gap: 7px; align-items: baseline; padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,.025); line-height: 1.4; }
.iht-lt { color: var(--muted); flex-shrink: 0; }
.iht-lk { flex-shrink: 0; font-weight: 700; font-size: 8px; letter-spacing: .06em; padding: 1px 4px; border-radius: 2px; }
.iht-ll-mtls .iht-lk { color: var(--cy); background: rgba(var(--nc-primary-rgb),.12); }
.iht-ll-err .iht-lk { color: #ff5470; background: rgba(255,23,68,.12); }
.iht-ll-probe .iht-lk { color: #00e676; background: rgba(0,230,118,.12); }
.iht-lm { color: var(--txt2); }
.iht-lm :deep(b) { color: var(--txt); }
/* graph */
.iht-graph { grid-area: graph; background: rgba(8,11,20,.82); border-top: 1px solid var(--bd); display: flex; gap: 1px; align-items: stretch; }
.iht-metric { flex: 1; padding: 9px 14px; display: flex; flex-direction: column; gap: 2px; border-right: 1px solid var(--bd); }
.iht-metric-wide { flex: 2.4; }
.iht-mk { font-family: var(--mono); font-size: 8.5px; font-weight: 600; letter-spacing: .1em; color: var(--muted); text-transform: uppercase; }
.iht-mv { font-family: var(--mono); font-size: 18px; font-weight: 700; color: var(--txt); }
.iht-mspark { font-family: var(--mono); color: var(--cy); font-size: 12px; letter-spacing: -1px; }
.iht-pathbars { display: flex; gap: 4px; align-items: flex-end; height: 30px; margin-top: 3px; }
.iht-pathbar { flex: 1; height: 100%; background: rgba(255,255,255,.04); border-radius: 2px 2px 0 0; display: flex; align-items: flex-end; overflow: hidden; }
.iht-pathbar-fill { width: 100%; border-radius: 2px 2px 0 0; transition: height .4s; }
.iht-empty { font-family: var(--mono); font-size: 11px; color: var(--muted); padding: 16px; text-align: center; }
/* traveling identity capsule */
.iht-orb-layer { position: absolute; top: 0; left: 0; z-index: 7; pointer-events: none; will-change: left, top; }
.iht-orb-halo { position: absolute; left: 0; top: 0; width: 132px; height: 132px; transform: translate(-50%,-50%); border-radius: 50%;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb),0.6) 0%, rgba(0,230,118,0.2) 42%, transparent 70%); animation: iht-halo 1.8s ease-in-out infinite; }
.iht-orb-halo.iht-orb-arrive { background: radial-gradient(circle, rgba(0,230,118,0.8) 0%, rgba(0,230,118,0.32) 46%, transparent 74%); }
@keyframes iht-halo { 0%,100% { opacity: .7; transform: translate(-50%,-50%) scale(1); } 50% { opacity: 1; transform: translate(-50%,-50%) scale(1.08); } }
.iht-orb-ring { position: absolute; left: 0; top: 0; width: 66px; height: 66px; transform: translate(-50%,-50%); border-radius: 50%;
  border: 2.5px solid rgba(var(--nc-primary-rgb),1); box-shadow: 0 0 20px var(--cy), inset 0 0 10px rgba(var(--nc-primary-rgb),0.6); animation: iht-ringspin 3s linear infinite; }
.iht-orb-ring2 { width: 92px; height: 92px; border-color: rgba(0,230,118,0.6); border-style: dashed; animation: iht-ringspin 7s linear infinite reverse; }
@keyframes iht-ringspin { to { transform: translate(-50%,-50%) rotate(360deg); } }
.iht-orb-av { position: absolute; left: 0; top: 0; transform: translate(-50%,-50%); filter: drop-shadow(0 0 10px rgba(0,0,0,0.85)); }
.iht-orb-label { position: absolute; left: 0; top: 0; transform: translate(-50%, 48px); text-align: center; white-space: nowrap; font-family: var(--mono); }
.iht-orb-name { display: block; font-size: 11px; font-weight: 700; color: #fff; text-shadow: 0 0 6px rgba(0,0,0,0.95), 0 0 12px var(--cy); }
.iht-orb-spiffe { display: block; font-size: 8px; color: var(--cy); text-shadow: 0 0 6px rgba(0,0,0,0.95); margin-top: 1px; }
.iht-orb-trail { position: absolute; top: 0; left: 0; width: 11px; height: 11px; transform: translate(-50%,-50%); border-radius: 50%;
  background: radial-gradient(circle, var(--cy) 0%, rgba(0,230,118,0.5) 50%, transparent 75%); z-index: 6; pointer-events: none; }
.iht-beacon { position: absolute; top: 0; left: 0; width: 44px; height: 44px; border-radius: 50%; z-index: 5; pointer-events: none; border: 2px solid #00e676; box-shadow: 0 0 12px rgba(0,230,118,0.6); animation: iht-beaconpulse 1.3s ease-out forwards; }
@keyframes iht-beaconpulse { 0% { transform: scale(0.3); opacity: 0.9; } 100% { transform: scale(2.4); opacity: 0; } }
.iht-orb-broken { filter: drop-shadow(0 0 12px #ff1744) saturate(1.4) hue-rotate(-20deg) !important; animation: iht-orbglitch 0.18s steps(2) infinite !important; }
@keyframes iht-orbglitch { 0% { transform: translate(-50%,-50%); } 50% { transform: translate(-53%,-48%); } 100% { transform: translate(-48%,-52%); } }
/* Cut 3 — SVID TTL countdown */
.iht-ttl { display: flex; align-items: center; gap: 6px; margin-top: 5px; }
.iht-ttl-bar { flex: 1; height: 3px; background: rgba(255,255,255,.08); border-radius: 2px; overflow: hidden; }
.iht-ttl-fill { height: 100%; background: linear-gradient(90deg, var(--cy), #00e676); transition: width 1s linear; }
.iht-ttl-fill.iht-ttl-low { background: #ff5470; }
.iht-ttl-lbl { font-family: var(--mono); font-size: 8px; color: var(--muted); letter-spacing: .04em; }
.iht-ttl-low-t { color: #ff5470; }
.iht-revoke { margin-left: auto; font-family: var(--mono); font-size: 8px; font-weight: 700; letter-spacing: .08em; color: #ff8da3;
  background: rgba(255,23,68,.12); border: 1px solid rgba(255,23,68,.3); border-radius: 3px; padding: 2px 7px; cursor: pointer; transition: all .15s; }
.iht-revoke:hover:not(:disabled) { background: rgba(255,23,68,.25); color: #fff; }
.iht-revoke:disabled { opacity: .5; cursor: progress; }
/* Cut 3 — log filters */
.iht-logfilters { display: flex; gap: 4px; padding: 6px 10px; border-bottom: 1px solid var(--bd); }
.iht-lf { font-family: var(--mono); font-size: 8px; font-weight: 700; letter-spacing: .06em; color: var(--muted);
  background: rgba(255,255,255,.04); border: 1px solid var(--bd); border-radius: 3px; padding: 2px 7px; cursor: pointer; transition: all .15s; }
.iht-lf:hover { color: var(--txt2); }
.iht-lf-on { color: var(--cy); border-color: rgba(var(--nc-primary-rgb),.4); background: rgba(var(--nc-primary-rgb),.1); }
.iht-lf-pause { margin-left: auto; }
.iht-paused { color: #ffc046 !important; }
/* Cut 3 — activity sparkline */
.iht-spark { width: 100%; height: 20px; margin-top: 2px; }
.iht-spark polyline { fill: none; stroke: var(--cy); stroke-width: 1.4; vector-effect: non-scaling-stroke; filter: drop-shadow(0 0 3px var(--cy)); }
.iht-mv-sub { font-size: 9px; color: var(--muted); font-weight: 400; }
/* toast */
.iht-toast { position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%); font-family: var(--mono); font-size: 11px; font-weight: 600;
  padding: 8px 18px; border-radius: 5px; z-index: 200; }
.iht-toast-ok { background: rgba(0,230,118,.2); color: #00e676; border: 1px solid rgba(0,230,118,.3); }
.iht-toast-warn { background: rgba(255,171,0,.18); color: #ffc046; border: 1px solid rgba(255,171,0,.3); }
.iht-toast-enter-active, .iht-toast-leave-active { transition: all .3s; }
.iht-toast-enter-from, .iht-toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }
@media (max-width: 1100px) {
  .iht-grid { grid-template-columns: 1fr; grid-template-areas: "stage" "left" "right" "graph"; }
  .iht-stage { min-height: 360px; }
}
</style>
