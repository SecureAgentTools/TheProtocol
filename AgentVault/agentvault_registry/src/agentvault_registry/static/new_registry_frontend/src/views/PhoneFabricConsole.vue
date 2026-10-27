<!--
  PHONE FABRIC console (Advanced, 2026-07-07) — operator oversight for capability-gated
  agent computer-use. Pool status · live sessions · per-session action trace · surgical KILL
  · global-halt PANIC. Oversight + control only (issuance is agent-context / SDK).
-->
<template>
  <div class="pfc">
    <header class="pfc-head">
      <div class="pfc-title">
        <span class="pfc-badge"><Icon name="mdi:monitor-cellphone" /></span>
        <div>
          <h1>Phone Fabric</h1>
          <p>Capability-gated agent computer-use — oversight &amp; control</p>
        </div>
      </div>
      <div class="pfc-status">
        <span class="pfc-pill" :class="!poolRead ? 'neutral' : meta.enabled ? 'ok' : 'off'">{{ !poolRead ? '—' : meta.enabled ? 'ENABLED' : 'DISABLED' }}</span>
        <span class="pfc-pill neutral">backend: {{ meta.backend || '—' }}</span>
        <span class="pfc-pill" :class="!poolRead ? 'neutral' : meta.mode === 'enforce' ? 'ok' : 'warn'">phone.use: {{ meta.mode || '—' }}</span>
        <button class="pfc-refresh" :disabled="loading" title="Refresh" @click="loadAll">
          <Icon name="mdi:refresh" :class="{ spin: loading }" />
        </button>
      </div>
    </header>

    <!-- pool tiles -->
    <section class="pfc-tiles">
      <div class="pfc-tile"><div class="pfc-tile-n">{{ poolRead ? (pool.active_sessions ?? 0) : '—' }}</div><div class="pfc-tile-l">Active sessions</div></div>
      <div class="pfc-tile"><div class="pfc-tile-n">{{ poolRead ? leasedCount : '—' }}</div><div class="pfc-tile-l">Leased instances</div></div>
      <div class="pfc-tile"><div class="pfc-tile-n">{{ poolRead ? (pool.max_concurrent ?? '—') : '—' }}</div><div class="pfc-tile-l">Max concurrent</div></div>
      <div class="pfc-tile"><div class="pfc-tile-n">{{ poolRead ? sessions.length : '—' }}</div><div class="pfc-tile-l">Recent (200)</div></div>
    </section>

    <!-- global halt -->
    <div class="pfc-halt-row" v-if="activeSessions.length">
      <span><Icon name="mdi:alert-octagon" /> {{ activeSessions.length }} active session{{ activeSessions.length === 1 ? '' : 's' }} — an agent is driving a phone right now.</span>
      <button class="pfc-halt-btn" @click="askGlobalHalt"><Icon name="mdi:stop-circle" /> GLOBAL HALT</button>
    </div>

    <div class="pfc-grid">
      <!-- sessions table -->
      <section class="pfc-panel">
        <h2><Icon name="mdi:cellphone-cog" /> Sessions</h2>
        <div v-if="loading && !sessions.length" class="pfc-list"><div v-for="n in 4" :key="n" class="pfc-skel"></div></div>
        <ul v-else class="pfc-sess">
          <li v-for="s in sessions" :key="s.id" class="pfc-row" :class="{ sel: selected === s.id, live: s.status === 'active' }" @click="open(s)">
            <span class="pfc-st" :class="'st-' + s.status">{{ s.status }}</span>
            <div class="pfc-row-body">
              <div class="pfc-row-top">
                <code>{{ shortDid(s.agent_did) }}</code>
                <span class="pfc-app" v-if="s.current_app">{{ s.current_app }}</span>
              </div>
              <div class="pfc-bar" v-if="s.budget_currency || Number(s.budget_spent)">
                <div class="pfc-bar-fill" :style="{ width: budgetPct(s) + '%' }"></div>
                <span class="pfc-bar-txt">{{ Number(s.budget_spent) }} spent · {{ s.actions_used }} actions</span>
              </div>
              <div class="pfc-bar-txt" v-else>{{ s.actions_used }} actions</div>
            </div>
            <button v-if="s.status === 'active'" class="pfc-kill" title="Kill this session" @click.stop="askKill(s)">
              <Icon name="mdi:phone-hangup" />
            </button>
            <Icon v-else name="mdi:eye" class="pfc-view" />
          </li>
          <li v-if="!sessions.length && listUnread" class="pfc-empty"><ReadFailedNotice dense :retry="loadAll" data-testid="pfc-sessions-unread" /></li>
          <li v-else-if="!sessions.length" class="pfc-empty">
            <Icon name="mdi:monitor-cellphone" class="pfc-empty-ico" />
            <p>No phone sessions yet. When an agent starts one with a <code>phone.use</code> capability permit, it appears here.</p>
          </li>
        </ul>
      </section>

      <!-- action trace drawer -->
      <section class="pfc-panel">
        <h2><Icon name="mdi:eye" /> Action trace</h2>
        <div v-if="!selected" class="pfc-trace-empty">Select a session to watch its every tap, type, and observe — the non-repudiable ledger.</div>
        <template v-else>
          <div class="pfc-trace-head" v-if="traceHead">
            <div><span class="pfc-k">agent</span> <code>{{ shortDid(traceHead.agent_did) }}</code></div>
            <div><span class="pfc-k">apps</span> {{ (traceHead.allowed_apps || []).join(', ') || '—' }}</div>
            <div><span class="pfc-k">caveats</span>
              <span class="pfc-cav">max {{ traceHead.max_actions ?? '∞' }}</span>
              <span class="pfc-cav" v-if="traceHead.no_screenshot">no-screenshot</span>
            </div>
          </div>
          <div v-if="traceLoading" class="pfc-list"><div v-for="n in 4" :key="n" class="pfc-skel sm"></div></div>
          <ReadFailedNotice v-else-if="traceFailed" dense :retry="() => loadTrace(selected)" data-testid="pfc-trace-unread" />
          <ol v-else class="pfc-trace">
            <li v-for="a in trace" :key="a.seq" class="pfc-tr" :class="{ denied: a.outcome === 'denied', err: a.outcome === 'error' }">
              <span class="pfc-tr-seq">{{ a.seq }}</span>
              <span class="pfc-tr-act">{{ a.action_type }}</span>
              <span class="pfc-tr-tgt" v-if="a.target">{{ a.target }}</span>
              <span class="pfc-tr-out" :class="'o-' + a.outcome">{{ a.outcome }}</span>
              <span class="pfc-tr-det" v-if="a.detail">{{ a.detail }}</span>
            </li>
            <li v-if="!trace.length" class="pfc-empty sm">No actions recorded.</li>
          </ol>
        </template>
      </section>
    </div>

    <ConfirmActionModal
      v-if="confirm.show"
      :show="true"
      :title="confirm.title"
      :message="confirm.message"
      :confirm-text="confirm.confirmText"
      :tone="confirm.tone"
      :required-match="confirm.requiredMatch"
      @confirm="confirm.onConfirm"
      @cancel="confirm.show = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Icon from '@/components/Icon.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { phoneFabricApi, type PhoneSession, type PhoneAction } from '@/services/api/phoneFabric'
import { useUIStore } from '@/stores/ui'

const ui = useUIStore()
const sessions = ref<PhoneSession[]>([])
const pool = ref<{ instances: any[]; active_sessions: number; max_concurrent: number }>({ instances: [], active_sessions: 0, max_concurrent: 0 })
const meta = ref<{ enabled: boolean; backend: string; mode: string }>({ enabled: false, backend: '', mode: '' })
const loading = ref(true)
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const poolRead = ref(false)
const selected = ref('')
const trace = ref<PhoneAction[]>([])
const traceHead = ref<any>(null)
const traceLoading = ref(false)
/** §FESUITE V0577: the admin reads answer 200 with `enabled: false` where the fabric is off, so a failure is a failure. It
 *  was kept quiet: the pill said DISABLED, the list "No phone sessions yet" (and with no active session drawn, the GLOBAL
 *  HALT row stayed hidden), and a failed trace read "No actions recorded." about the non-repudiable ledger. */
const listUnread = ref(false)
const traceFailed = ref(false)
let timer: any = null

const leasedCount = computed(() => pool.value.instances.filter((i) => i.status === 'leased').length)
const activeSessions = computed(() => sessions.value.filter((s) => s.status === 'active'))

const shortDid = (d: string) => !d ? '—' : d.length > 30 ? d.slice(0, 18) + '…' + d.slice(-6) : d
function budgetPct(s: PhoneSession): number {
  const spent = Number(s.budget_spent) || 0
  // no total exposed here; show a soft fill capped at 100 relative to a nominal 20-unit scale
  return Math.min(100, Math.round((spent / 20) * 100))
}

async function loadAll() {
  loading.value = true
  try {
    const [ss, pp] = await Promise.all([phoneFabricApi.sessions(), phoneFabricApi.pool()])
    sessions.value = ss.sessions
    meta.value = { enabled: ss.enabled, backend: ss.backend, mode: ss.mode }
    pool.value = pp
    poolRead.value = true
    listUnread.value = false
  } catch (e: any) {
    // a failed refresh keeps what was shown; a failed first read says so (the routes answer `enabled: false` when off)
    if (!poolRead.value) listUnread.value = true
  } finally { loading.value = false }
  if (selected.value) loadTrace(selected.value)
}

async function open(s: PhoneSession) { selected.value = s.id; await loadTrace(s.id) }
async function loadTrace(sid: string) {
  traceLoading.value = true
  try {
    const r = await phoneFabricApi.actions(sid)
    trace.value = r.actions
    traceHead.value = r.session
    traceFailed.value = false
  } catch { trace.value = []; traceHead.value = null; traceFailed.value = true }
  finally { traceLoading.value = false }
}

const confirm = ref<any>({ show: false })
function askKill(s: PhoneSession) {
  confirm.value = {
    show: true, title: 'Kill phone session?', tone: 'danger', confirmText: 'Kill session',
    message: `End session for ${shortDid(s.agent_did)} immediately and release its phone. The agent's next action will be refused.`,
    onConfirm: async () => {
      confirm.value.show = false
      try { await phoneFabricApi.kill(s.id); ui.showSuccess?.('Session killed', s.id); await loadAll() }
      catch (e: any) { ui.showError?.('Kill failed', e?.message || 'error') }
    },
  }
}
function askGlobalHalt() {
  confirm.value = {
    show: true, title: 'GLOBAL HALT — kill every phone session?', tone: 'danger', confirmText: 'HALT ALL',
    requiredMatch: 'HALT',
    message: `This ends ALL ${activeSessions.value.length} active phone session(s) fleet-wide on this registry. Type HALT to confirm.`,
    onConfirm: async () => {
      confirm.value.show = false
      try { const r = await phoneFabricApi.globalHalt(); ui.showSuccess?.('Global halt', `${r.halted} session(s) killed`); await loadAll() }
      catch (e: any) { ui.showError?.('Halt failed', e?.message || 'error') }
    },
  }
}

onMounted(() => { loadAll(); timer = setInterval(loadAll, 8000) })
onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped>
.pfc { max-width: 1200px; margin: 0 auto; padding: 1.2rem; color: #e6edf3; }
.pfc-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.8rem; margin-bottom: 1rem; }
.pfc-title { display: flex; align-items: center; gap: 0.8rem; }
.pfc-badge { width: 2.6rem; height: 2.6rem; border-radius: 12px; display: grid; place-items: center;
  background: rgba(0,212,255,0.12); border: 1px solid rgba(0,212,255,0.25); }
.pfc-badge :deep(svg) { width: 1.4rem; height: 1.4rem; color: var(--nc-primary, #00d4ff); }
.pfc-title h1 { margin: 0; font-size: 1.3rem; }
.pfc-title p { margin: 0.1rem 0 0; font-size: 0.8rem; opacity: 0.6; }
.pfc-status { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.pfc-pill { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.06em; padding: 0.25rem 0.55rem; border-radius: 6px; text-transform: uppercase; }
.pfc-pill.ok { color: #34d399; background: rgba(16,185,129,0.12); border: 1px solid rgba(16,185,129,0.3); }
.pfc-pill.off { color: #ff8a8a; background: rgba(255,107,107,0.1); border: 1px solid rgba(255,107,107,0.3); }
.pfc-pill.warn { color: #fbbf24; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.3); }
.pfc-pill.neutral { color: #93c5fd; background: rgba(147,197,253,0.1); border: 1px solid rgba(147,197,253,0.25); }
.pfc-refresh { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 0.35rem 0.5rem; color: inherit; cursor: pointer; }
.pfc-refresh :deep(svg) { width: 1rem; height: 1rem; }
.spin { animation: pfc-rot 0.9s linear infinite; } @keyframes pfc-rot { to { transform: rotate(360deg); } }
.pfc-tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.7rem; margin-bottom: 0.9rem; }
.pfc-tile { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 0.9rem; }
.pfc-tile-n { font-size: 1.7rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.pfc-tile-l { font-size: 0.72rem; opacity: 0.55; margin-top: 0.15rem; }
.pfc-halt-row { display: flex; align-items: center; justify-content: space-between; gap: 0.8rem; flex-wrap: wrap;
  background: rgba(255,107,107,0.08); border: 1px solid rgba(255,107,107,0.28); border-radius: 12px; padding: 0.7rem 0.9rem; margin-bottom: 0.9rem; font-size: 0.85rem; }
.pfc-halt-row :deep(svg) { width: 1rem; height: 1rem; vertical-align: -2px; color: #ff8a8a; }
.pfc-halt-btn { background: #b91c1c; border: none; color: #fff; font-weight: 700; letter-spacing: 0.05em; border-radius: 8px; padding: 0.5rem 0.9rem; cursor: pointer; display: inline-flex; align-items: center; gap: 0.35rem; }
.pfc-halt-btn :deep(svg) { color: #fff; }
.pfc-grid { display: grid; grid-template-columns: 1.1fr 1fr; gap: 0.9rem; }
@media (max-width: 900px) { .pfc-grid { grid-template-columns: 1fr; } .pfc-tiles { grid-template-columns: repeat(2, 1fr); } }
.pfc-panel { background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; padding: 1rem; }
.pfc-panel h2 { font-size: 0.95rem; margin: 0 0 0.7rem; display: flex; align-items: center; gap: 0.4rem; }
.pfc-panel h2 :deep(svg) { width: 1rem; height: 1rem; color: var(--nc-primary, #00d4ff); }
.pfc-sess { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; max-height: 60vh; overflow-y: auto; }
.pfc-row { display: flex; align-items: center; gap: 0.6rem; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; padding: 0.55rem 0.65rem; cursor: pointer; transition: background 0.12s; }
.pfc-row:hover { background: rgba(255,255,255,0.06); }
.pfc-row.sel { border-color: rgba(0,212,255,0.4); }
.pfc-row.live { border-left: 3px solid #34d399; }
.pfc-st { font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.04em; padding: 0.15rem 0.4rem; border-radius: 5px; flex: 0 0 auto; background: rgba(255,255,255,0.08); }
.st-active { background: rgba(16,185,129,0.16); color: #34d399; } .st-revoked { background: rgba(255,107,107,0.14); color: #ff8a8a; }
.st-ended { background: rgba(147,197,253,0.12); color: #93c5fd; } .st-expired { background: rgba(245,158,11,0.12); color: #fbbf24; }
.pfc-row-body { flex: 1 1 auto; min-width: 0; }
.pfc-row-top { display: flex; align-items: center; gap: 0.5rem; }
.pfc-row-top code { font-size: 0.74rem; }
.pfc-app { font-size: 0.66rem; opacity: 0.6; background: rgba(255,255,255,0.06); padding: 0.05rem 0.35rem; border-radius: 4px; }
.pfc-bar { position: relative; height: 1rem; background: rgba(255,255,255,0.06); border-radius: 5px; margin-top: 0.35rem; overflow: hidden; }
.pfc-bar-fill { position: absolute; inset: 0 auto 0 0; background: linear-gradient(90deg, #00d4ff, #34d399); opacity: 0.5; }
.pfc-bar-txt { position: relative; font-size: 0.62rem; opacity: 0.75; line-height: 1rem; padding-left: 0.4rem; }
.pfc-kill { background: rgba(255,107,107,0.14); border: 1px solid rgba(255,107,107,0.3); border-radius: 8px; padding: 0.4rem; color: #ff8a8a; cursor: pointer; flex: 0 0 auto; }
.pfc-kill :deep(svg) { width: 1rem; height: 1rem; }
.pfc-view { opacity: 0.35; flex: 0 0 auto; } .pfc-view :deep(svg), .pfc-view { width: 1rem; height: 1rem; }
.pfc-empty { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; padding: 2rem 1rem; opacity: 0.55; text-align: center; }
.pfc-empty.sm { padding: 1rem; } .pfc-empty-ico { width: 2rem; height: 2rem; } .pfc-empty p { margin: 0; font-size: 0.82rem; max-width: 26rem; }
.pfc-trace-empty { opacity: 0.5; font-size: 0.85rem; padding: 1.5rem 0.5rem; text-align: center; }
.pfc-trace-head { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.75rem; background: rgba(255,255,255,0.03); border-radius: 8px; padding: 0.6rem; margin-bottom: 0.6rem; }
.pfc-k { display: inline-block; width: 4rem; opacity: 0.5; }
.pfc-cav { font-size: 0.64rem; background: rgba(0,212,255,0.1); color: #7dd3fc; padding: 0.05rem 0.4rem; border-radius: 4px; margin-right: 0.3rem; }
.pfc-trace { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.25rem; max-height: 55vh; overflow-y: auto; font-family: ui-monospace, monospace; }
.pfc-tr { display: flex; align-items: center; gap: 0.5rem; font-size: 0.72rem; background: rgba(255,255,255,0.02); border-radius: 6px; padding: 0.3rem 0.5rem; }
.pfc-tr.denied { background: rgba(255,107,107,0.08); } .pfc-tr.err { background: rgba(245,158,11,0.08); }
.pfc-tr-seq { opacity: 0.4; width: 1.6rem; } .pfc-tr-act { color: #7dd3fc; }
.pfc-tr-tgt { opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pfc-tr-out { margin-left: auto; font-size: 0.6rem; text-transform: uppercase; }
.o-ok { color: #34d399; } .o-denied { color: #ff8a8a; } .o-error { color: #fbbf24; }
.pfc-tr-det { opacity: 0.5; font-size: 0.64rem; }
.pfc-list { display: flex; flex-direction: column; gap: 0.4rem; }
.pfc-skel { height: 3rem; border-radius: 10px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pfc-shim 1.3s ease-in-out infinite; }
.pfc-skel.sm { height: 1.6rem; }
@keyframes pfc-shim { to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .pfc-skel, .spin { animation: none; } }
</style>
