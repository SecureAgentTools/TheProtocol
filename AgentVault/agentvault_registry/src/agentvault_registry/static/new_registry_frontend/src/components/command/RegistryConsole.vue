<template>
  <div class="grc">
    <!-- TARGET RIBBON — always-visible mis-target guard -->
    <div class="grc-ribbon">
      <div class="grc-ribbon-top">
        <span class="grc-target-label">TARGET</span>
        <button class="grc-back" type="button" title="Back to fleet" @click="$emit('back')">
          <Icon name="mdi:close" :size="12" /> deselect
        </button>
      </div>
      <h3 class="grc-name">{{ entry.name }}</h3>
      <div class="grc-badges">
        <span class="grc-chip grc-chip--tier">{{ entry.tier }}</span>
        <span v-if="entry.frame" class="grc-chip">Frame {{ entry.frame }}</span>
        <span class="grc-chip grc-chip--ccy">{{ entry.currency }}</span>
        <span v-if="entry.is_local" class="grc-chip grc-chip--local">LOCAL</span>
        <span class="grc-dot" :class="probe?.health === 'up' ? 'grc-dot--up' : probe?.health === 'down' ? 'grc-dot--down' : 'grc-dot--unk'"></span>
        <span class="grc-meta">{{ probe ? (probe.health === 'down' ? 'down' : probe.latency_ms + 'ms') : '' }}</span>
        <Sparkline v-if="latHistory && latHistory.length >= 2" :points="latHistory" class="grc-spark" title="latency, last probes" />
      </div>
      <p class="grc-sub">
        key <code class="grc-code">{{ entry.key }}</code>
        <template v-if="entry.card_software_version"> · card {{ shortVer(entry.card_software_version) }}<span v-if="cardAge" class="grc-stale"> (pulled {{ cardAge }})</span></template>
      </p>
      <div class="grc-treasury" :class="{ 'grc-treasury--muted': treasury === null }">
        <Icon name="mdi:bank" :size="12" />
        <span class="grc-treasury-k">Treasury</span>
        <span class="grc-treasury-v">{{ treasuryText }}</span>
        <button v-if="treasuryAvailable" class="grc-treasury-refresh" type="button" title="Refresh treasury balance" :disabled="treasuryLoading" @click="$emit('refresh-treasury')">
          <Icon name="mdi:sync" :size="11" />
        </button>
      </div>
    </div>

    <!-- Intel (P7 — dashboard + workers snapshot; local, or at the remote registry with its own token) -->
    <section v-if="intelVisible" class="grc-sec">
      <h4 class="grc-h">
        <Icon name="mdi:radar" :size="12" /> Intel
        <button class="grc-h-refresh" type="button" title="Refresh intel" :disabled="intelLoading" @click="$emit('refresh-intel')">
          <Icon name="mdi:sync" :size="10" />
        </button>
      </h4>
      <div class="grc-intel">
        <div class="grc-intel-tile"><span class="grc-intel-k">Agents</span><span class="grc-intel-v">{{ intelAgents }}</span></div>
        <div class="grc-intel-tile"><span class="grc-intel-k">Developers</span><span class="grc-intel-v">{{ intelDevs }}</span></div>
        <div class="grc-intel-tile" title="background workers with a leader / total"><span class="grc-intel-k">Workers</span><span class="grc-intel-v">{{ intelWorkers }}</span></div>
        <!-- GC2-3: ZKP attestation stats (verified/total · active). "—" = the
             target predates the analytics endpoint or its ZKP layer is dark. -->
        <div class="grc-intel-tile" :title="attest ? `ZKP attestations — verified ${attest.verified} of ${attest.total} (${attest.active} active)` : 'ZKP attestation analytics unavailable on this target'">
          <span class="grc-intel-k">ZKP</span>
          <span class="grc-intel-v">{{ attest ? `${attest.verified}/${attest.total}` + (attest.active ? ` · ${attest.active}a` : '') : '—' }}</span>
        </div>
      </div>
    </section>

    <!-- Agent finder (P7 — search ANY agent on this registry, incl. off-map ones) -->
    <section v-if="intelVisible" class="grc-sec">
      <h4 class="grc-h"><Icon name="mdi:magnify" :size="12" /> Agent finder</h4>
      <div class="grc-fund-local">
        <input
          v-model.trim="findQ"
          class="grc-input" type="text" autocomplete="off" spellcheck="false"
          :placeholder="`name / did / client_id on ${entry.key}…`"
          aria-label="Search agents on this registry"
          @keydown.enter="doFind"
        />
        <button class="grc-act grc-act--inline" type="button" :disabled="findQ.length < 2 || finding" @click="doFind">
          <Icon name="mdi:magnify" :size="14" /> {{ finding ? '…' : 'Search' }}
        </button>
      </div>
      <p v-if="findErr" class="grc-conn-err">{{ findErr }}</p>
      <p v-else-if="found !== null && !found.length" class="grc-note grc-note--dim">No agents match “{{ lastQ }}” on {{ entry.key }}.</p>
      <button
        v-for="a in (found || [])" :key="a.did"
        class="grc-found" type="button" :title="`Open agent console for ${a.name || a.client_id}`"
        @click="$emit('pick-agent', a)"
      >
        <span class="grc-dot" :class="a.status === 'active' ? 'grc-dot--up' : 'grc-dot--down'"></span>
        <span class="grc-roster-name">{{ a.name || a.client_id }}</span>
        <code class="grc-roster-did">{{ a.did.slice(0, 22) }}…</code>
        <span class="grc-found-bal">{{ fmtBal(a.liquid_balance) }}</span>
      </button>
    </section>

    <!-- Treasury -->
    <section class="grc-sec">
      <h4 class="grc-h"><Icon name="mdi:bank" :size="12" /> Treasury</h4>
      <button
        v-if="!entry.is_local"
        class="grc-act" type="button" :disabled="!!busyAction"
        @click="$emit('act', { id: 'cross_teg_fund' })"
      >
        <Icon name="mdi:bank-transfer" :size="14" />
        <span class="grc-act-t">Fund this registry's treasury<span class="grc-act-s">cross-TEG from {{ localKey }} · Model A (mTLS)</span></span>
      </button>
      <div v-if="entry.is_local" class="grc-fund-local">
        <input
          v-model.trim="fundDid"
          class="grc-input" type="text" autocomplete="off" spellcheck="false"
          placeholder="did:theprotocol:… (agent on this registry)"
          aria-label="Agent DID to fund"
        />
        <button
          class="grc-act grc-act--inline" type="button"
          :disabled="!didValid || !!busyAction"
          @click="$emit('act', { id: 'fund_agent_local', payload: { did: fundDid } })"
        >
          <Icon name="mdi:plus-circle" :size="14" /> Fund agent…
        </button>
      </div>
      <p v-if="entry.is_local" class="grc-note">Canonical FLOW 4 — treasury → agent on {{ entry.key }}.</p>
    </section>

    <!-- Cloud-op lifecycle (Model A, mainframe-managed) -->
    <section v-if="isOp" class="grc-sec">
      <h4 class="grc-h"><Icon name="mdi:server" :size="12" /> Operator lifecycle</h4>
      <template v-if="manageableOp">
        <button class="grc-act" type="button" :disabled="!!busyAction" @click="$emit('act', { id: 'op_restart', payload: { appId: manageableOp.id } })">
          <Icon name="mdi:restart" :size="14" />
          <span class="grc-act-t">Restart registry service<span class="grc-act-s">app #{{ manageableOp.id }} · runs on {{ localKey }} (docker)</span></span>
        </button>
        <button class="grc-act grc-act--danger" type="button" :disabled="!!busyAction" @click="$emit('act', { id: 'op_teardown', payload: { appId: manageableOp.id, name: entry.key } })">
          <Icon name="mdi:alert" :size="14" />
          <span class="grc-act-t">Tear down operator stack<span class="grc-act-s">destructive — typed confirmation required</span></span>
        </button>
      </template>
      <p v-else class="grc-note grc-note--dim">
        Not managed from {{ localKey }} — lifecycle actions live on this op's parent mainframe.
      </p>
    </section>

    <!-- Frame special functions (P8: MINT is REAL on the local mainframe) -->
    <section v-if="frameCaps.length" class="grc-sec">
      <h4 class="grc-h"><Icon name="mdi:star" :size="12" /> Frame functions</h4>
      <div class="grc-caps">
        <span v-for="c in frameCaps" :key="c" class="grc-chip grc-chip--cap">{{ c.toUpperCase() }}</span>
      </div>
      <template v-if="canMintHere">
        <div class="grc-fund-local">
          <input
            v-model.trim="mintDid"
            class="grc-input" type="text" autocomplete="off" spellcheck="false"
            placeholder="did:… issue target (empty = system treasury)"
            aria-label="Issue target DID"
          />
          <button
            class="grc-act grc-act--inline grc-act--mint" type="button"
            :disabled="!mintDidValid || !!busyAction"
            @click="$emit('act', { id: 'mint_tokens', payload: { did: mintDid || TREASURY_DID } })"
          >
            <Icon name="mdi:plus-circle" :size="14" /> Issue…
          </button>
        </div>
        <p class="grc-note">The ONLY create-from-void path — registry issuance proxy emits TokensIssued (Δ-safe). ≥100k asks for a typed confirm.</p>
      </template>
      <p v-else class="grc-note grc-note--dim">Issuance / fiat / compliance stay frame-gated — operated from the frame's own console.</p>
    </section>

    <!-- IRONHAND quick probe (Model A — local probe agent fires at this registry) -->
    <section class="grc-sec">
      <h4 class="grc-h"><Icon name="mdi:crosshairs-gps" :size="12" /> IRONHAND</h4>
      <button class="grc-act" type="button" :disabled="!!busyAction" @click="$emit('act', { id: 'registry_probe' })">
        <Icon name="mdi:radar" :size="14" />
        <span class="grc-act-t">Quick probe<span class="grc-act-s">real low-value mTLS transfer at {{ entry.key }}'s probe agent · Model A</span></span>
      </button>
    </section>

    <!-- Speak-as console (Model B): a session AT that registry's own address (§FEFRAME W4: the relay is gone) -->
    <section v-if="!entry.is_local" class="grc-sec">
      <h4 class="grc-h"><Icon name="mdi:radio-tower" :size="12" /> Registry console</h4>

      <p v-if="!entry.console_url" class="grc-note grc-note--dim">
        {{ entry.key }} has no known console address yet (its card has not been read) — Model-A actions above still work.
      </p>

      <template v-else-if="!isConnected">
        <div class="grc-conn">
          <input v-model.trim="connEmail" class="grc-input" type="email" autocomplete="username" placeholder="admin email on this registry" aria-label="Admin email" />
          <input v-model="connPassword" class="grc-input" type="password" autocomplete="current-password" placeholder="password (used once, never stored)" aria-label="Admin password" @keydown.enter="doConnect" />
          <div class="grc-conn-row">
            <button class="grc-act grc-act--inline" type="button" :disabled="!connEmail || !connPassword || connecting" @click="doConnect">
              <Icon name="mdi:server-network" :size="14" /> {{ connecting ? 'Connecting…' : `Connect (speak as ${entry.key})` }}
            </button>
            <button v-if="hasStoredRefresh" class="grc-act grc-act--inline" type="button" :disabled="connecting" @click="$emit('reconnect')">
              <Icon name="mdi:restart" :size="14" /> Reconnect
            </button>
          </div>
          <p v-if="session?.error" class="grc-conn-err">{{ session.error }}</p>
        </div>
      </template>

      <template v-else>
        <div class="grc-connected">
          <span class="grc-dot grc-dot--up"></span>
          <span class="grc-connected-t">connected as <strong>{{ session?.adminEmail || 'admin' }}</strong></span>
          <button class="grc-back" type="button" @click="$emit('disconnect-peer')">disconnect</button>
        </div>

        <div class="grc-fund-local">
          <input
            v-model.trim="remoteDid"
            class="grc-input" type="text" autocomplete="off" spellcheck="false"
            :placeholder="`did:theprotocol:… (agent on ${entry.key})`"
            aria-label="Agent DID to fund on this registry"
          />
          <button
            class="grc-act grc-act--inline" type="button"
            :disabled="!remoteDidValid || !!busyAction"
            @click="$emit('act', { id: 'fund_agent_remote', payload: { did: remoteDid } })"
          >
            <Icon name="mdi:plus-circle" :size="14" /> Fund agent…
          </button>
        </div>
        <p class="grc-note">FLOW 4 on {{ entry.key }} — executed with {{ entry.key }}'s own admin token, at its own address.</p>

        <button class="grc-act" type="button" :disabled="!!busyAction" @click="$emit('act', { id: 'projection_snapshot' })">
          <Icon name="mdi:sync" :size="14" />
          <span class="grc-act-t">Projection snapshot<span class="grc-act-s">TEG → EventStore balance snapshot on {{ entry.key }}</span></span>
        </button>

        <!-- P11: full lifecycle reach — the op restarts ITSELF via its own license,
             so this works from ANY cockpit (only shown where Model-A can't manage it) -->
        <button
          v-if="isOp && !manageableOp"
          class="grc-act grc-act--danger" type="button" :disabled="!!busyAction"
          @click="$emit('act', { id: 'op_self_restart' })"
        >
          <Icon name="mdi:restart" :size="14" />
          <span class="grc-act-t">Restart this operator<span class="grc-act-s">self-service via {{ entry.key }}'s own license — brief downtime</span></span>
        </button>

        <!-- My agents on this registry (scoped roster → mint Tier-2 token) -->
        <h4 class="grc-h grc-h--sub"><Icon name="mdi:account" :size="12" /> My agents here</h4>
        <p v-if="!roster.length" class="grc-note grc-note--dim">No agent credentials stored for {{ entry.key }} — add below or import a vault.</p>
        <div v-for="r in roster" :key="r.did" class="grc-roster-row">
          <span class="grc-dot" :class="session?.activeAgentDid === r.did ? 'grc-dot--up' : 'grc-dot--unk'"></span>
          <span class="grc-roster-name">{{ r.name || r.client_id }}</span>
          <code class="grc-roster-did">{{ r.did.slice(0, 22) }}…</code>
          <button
            class="grc-roster-use" type="button" :disabled="!!busyAction || !r.client_secret"
            :title="r.client_secret ? 'Get this agent\'s token and act as it' : 'No client_secret stored'"
            @click="$emit('act', { id: 'mint_agent', payload: { did: r.did, client_id: r.client_id, client_secret: r.client_secret, name: r.name } })"
          >{{ session?.activeAgentDid === r.did ? 'active' : 'use' }}</button>
        </div>
        <div class="grc-roster-add">
          <input v-model.trim="addDid" class="grc-input" type="text" placeholder="did:… (optional)" aria-label="Agent DID (optional)" spellcheck="false" />
          <input v-model.trim="addClientId" class="grc-input" type="text" placeholder="client_id" aria-label="Client id" spellcheck="false" />
          <input v-model="addSecret" class="grc-input" type="password" placeholder="client_secret" aria-label="Client secret" />
          <button class="grc-roster-use" type="button" :disabled="!addValid" @click="doAddRoster">add</button>
        </div>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import Sparkline from '@/components/command/Sparkline.vue'
import { addToRoster, rosterFor } from '@/services/commandRoster'
import { searchAgentsLocal, searchAgentsRemote } from '@/services/api/command'
import type { CloudOperatorRow, DirectoryEntry, FleetProbe, FoundAgent, RegistryIntel } from '@/services/api/command'

const props = defineProps<{
  entry: DirectoryEntry
  probe: FleetProbe | undefined
  localKey: string
  manageableOp: CloudOperatorRow | null
  busyAction: string | null
  session: { status: string; adminEmail: string | null; error: string | null; activeAgentDid?: string | null } | null
  hasStoredRefresh: boolean
  localEmail: string
  treasury?: string | null      // balance string, '' = unavailable/not-connected, null = loading-not-started
  treasuryLoading?: boolean
  intel?: RegistryIntel | null  // P7 — dashboard + workers snapshot (undefined = not fetched)
  intelLoading?: boolean
  attest?: { total: number; verified: number; active: number } | null  // GC2-3 — ZKP attestation stats (null = endpoint absent / ZKP dark)
  adminToken?: string | null    // P7 — the target's admin token for the agent finder (at its address)
  latHistory?: number[]         // P8 — latency samples (client ring buffer) for the sparkline
}>()
const emit = defineEmits<{
  (e: 'back'): void
  (e: 'act', a: { id: string; payload?: any }): void
  (e: 'connect', p: { email: string; password: string }): void
  (e: 'reconnect'): void
  (e: 'disconnect-peer'): void
  (e: 'refresh-treasury'): void
  (e: 'refresh-intel'): void
  (e: 'pick-agent', a: FoundAgent): void
}>()

const treasuryLoading = computed(() => !!props.treasuryLoading)
const treasuryAvailable = computed(() => props.entry.is_local || props.session?.status === 'connected')
const treasuryText = computed(() => {
  if (props.treasuryLoading) return 'loading…'
  if (props.treasury === null || props.treasury === undefined) return treasuryAvailable.value ? '—' : '(connect to view)'
  if (props.treasury === '') return treasuryAvailable.value ? 'unavailable' : '(connect to view)'
  const n = Number(props.treasury)
  return (Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : props.treasury) + ' ' + props.entry.currency
})

const fundDid = ref('')
const remoteDid = ref('')
const connEmail = ref(props.localEmail || '')
const connPassword = ref('')
watch(() => props.entry.key, () => {
  fundDid.value = ''; remoteDid.value = ''; connPassword.value = ''
  findQ.value = ''; found.value = null; findErr.value = ''; lastQ.value = ''
  if (!connEmail.value) connEmail.value = props.localEmail || ''
})

const isConnected = computed(() => props.session?.status === 'connected')

// ── P7: intel tiles + agent finder ───────────────────────────────────────────
const intelVisible = computed(() => props.entry.is_local || isConnected.value)
const intelAgents = computed(() => props.intelLoading ? '…' : (props.intel?.agent_count != null ? `${props.intel.active_agents ?? '—'}/${props.intel.agent_count}` : '—'))
const intelDevs = computed(() => props.intelLoading ? '…' : (props.intel?.developer_count ?? '—'))
const intelWorkers = computed(() => props.intelLoading ? '…' : (props.intel?.workers_total != null ? `${props.intel.workers_with_leader ?? '—'}/${props.intel.workers_total}` : '—'))

const findQ = ref('')
const finding = ref(false)
const findErr = ref('')
const lastQ = ref('')
const found = ref<FoundAgent[] | null>(null)
const fmtBal = (n?: number) => (typeof n === 'number' ? n.toLocaleString(appLocale(), { maximumFractionDigits: 1 }) : '')
async function doFind() {
  const q = findQ.value
  if (q.length < 2 || finding.value) return
  finding.value = true; findErr.value = ''; lastQ.value = q
  try {
    found.value = props.entry.is_local
      ? await searchAgentsLocal(q)
      : await searchAgentsRemote(props.entry.key, props.adminToken || '', q)
  } catch (e: any) {
    findErr.value = e?.response?.data?.detail || e?.message || 'search failed'
    found.value = null
  } finally { finding.value = false }
}
const connecting = computed(() => props.session?.status === 'connecting')
function doConnect() {
  if (!connEmail.value || !connPassword.value) return
  emit('connect', { email: connEmail.value, password: connPassword.value })
  connPassword.value = ''  // used once, never retained client-side
}

const didValid = computed(() => /^did:[a-z0-9]+:.+/i.test(fundDid.value))
const remoteDidValid = computed(() => /^did:[a-z0-9]+:.+/i.test(remoteDid.value))

// scoped roster (rosterRev bumps re-read after adds)
const rosterRev = ref(0)
const addDid = ref(''); const addClientId = ref(''); const addSecret = ref('')
const roster = computed(() => { void rosterRev.value; return rosterFor(props.entry.key, props.entry.is_local) })
// DID is OPTIONAL — minting an agent token only needs client_id + client_secret
// (OAuth2 password grant). When omitted, the client_id doubles as the roster key.
const addValid = computed(() =>
  (!addDid.value || /^did:[a-z0-9]+:.+/i.test(addDid.value)) && addClientId.value.length > 3 && addSecret.value.length >= 16)
function doAddRoster() {
  addToRoster(props.entry.key, { did: addDid.value || addClientId.value, client_id: addClientId.value, client_secret: addSecret.value }, props.entry.is_local)
  addDid.value = ''; addClientId.value = ''; addSecret.value = ''
  rosterRev.value++
}
const isOp = computed(() => props.entry.capabilities.includes('op_lifecycle'))
const frameCaps = computed(() => props.entry.capabilities.filter(c => ['mint', 'fiat', 'compliance'].includes(c)))

// P8 — mint console (real on the LOCAL mainframe only; per D1 frames operate their own mint)
const TREASURY_DID = 'did:theprotocol:teg_system_treasury'
const mintDid = ref('')
const mintDidValid = computed(() => !mintDid.value || /^did:[a-z0-9]+:.+/i.test(mintDid.value))
const canMintHere = computed(() => props.entry.is_local && frameCaps.value.includes('mint'))

const shortVer = (v: string | null) => {
  if (!v) return '—'
  const m = v.match(/V\d{4}$/)
  return m ? m[0] : v.slice(-8)
}
const cardAge = computed(() => {
  if (!props.entry.card_last_pulled_at) return ''
  const d = Date.now() - new Date(props.entry.card_last_pulled_at).getTime()
  const days = Math.floor(d / 86400000)
  return days > 0 ? `${days}d ago` : 'today'
})
</script>

<style scoped>
.grc { display: grid; gap: 14px; }

.grc-ribbon {
  padding: 11px 12px;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .07);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .35);
  border-radius: 10px;
}
.grc-ribbon-top { display: flex; align-items: center; justify-content: space-between; }
.grc-target-label { font-size: .58rem; letter-spacing: .18em; font-weight: 800; color: var(--nc-primary, #00d2d2); }
.grc-back {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; border: 1px solid rgba(255,255,255,.12); border-radius: 6px;
  color: var(--nc-text-muted, #94a3b8); font-size: .62rem; padding: 2px 7px; cursor: pointer;
}
.grc-back:hover { color: #fff; }
.grc-name { margin: 5px 0 7px; font-size: 1.15rem; font-weight: 800; letter-spacing: .01em; }
.grc-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.grc-chip {
  font-size: .58rem; font-weight: 700; letter-spacing: .06em; padding: 1px 7px; border-radius: 4px;
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.12); color: var(--nc-text-primary, #e8eaed);
}
.grc-chip--tier { text-transform: uppercase; }
.grc-chip--ccy { background: rgba(var(--nc-primary-rgb, 0,210,210), .1); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .35); color: var(--nc-primary, #00d2d2); }
.grc-chip--local { background: rgba(16,185,129,.12); border-color: rgba(16,185,129,.4); color: #10b981; }
.grc-chip--cap { background: rgba(245,158,11,.1); border-color: rgba(245,158,11,.35); color: #fbbf24; }
.grc-dot { width: 8px; height: 8px; border-radius: 50%; }
.grc-dot--up { background: #10b981; }
.grc-dot--down { background: #ef4444; }
.grc-dot--unk { background: rgba(255,255,255,.2); }
.grc-meta { font-size: .62rem; color: var(--nc-text-muted, #94a3b8); font-variant-numeric: tabular-nums; }
.grc-sub { margin: 7px 0 0; font-size: .66rem; color: var(--nc-text-muted, #94a3b8); }
.grc-code { font-family: ui-monospace, monospace; color: var(--nc-text-primary, #e8eaed); }
.grc-stale { color: #f59e0b; }
.grc-treasury {
  display: flex; align-items: center; gap: 7px; margin-top: 8px;
  padding: 6px 9px; border-radius: 7px; font-size: .74rem;
  background: rgba(16,185,129,.07); border: 1px solid rgba(16,185,129,.28);
}
.grc-treasury--muted { background: rgba(255,255,255,.025); border-color: rgba(255,255,255,.07); }
.grc-treasury-k { font-size: .58rem; text-transform: uppercase; letter-spacing: .1em; font-weight: 700; color: var(--nc-text-muted, #94a3b8); }
.grc-treasury-v { flex: 1 1 auto; font-weight: 800; font-variant-numeric: tabular-nums; color: #10b981; }
.grc-treasury--muted .grc-treasury-v { color: var(--nc-text-muted, #94a3b8); font-weight: 600; }
.grc-treasury-refresh { flex: 0 0 auto; width: 22px; height: 22px; display: grid; place-items: center; background: transparent; border: 1px solid rgba(255,255,255,.1); border-radius: 5px; color: var(--nc-text-muted, #94a3b8); cursor: pointer; }
.grc-treasury-refresh:hover:not(:disabled) { color: #10b981; }
.grc-treasury-refresh:disabled { opacity: .4; cursor: wait; }

.grc-sec { display: grid; gap: 6px; }
.grc-h {
  margin: 0; display: flex; align-items: center; gap: 6px;
  font-size: .62rem; text-transform: uppercase; letter-spacing: .12em; font-weight: 700;
  color: var(--nc-text-muted, #94a3b8);
}
.grc-h-refresh {
  margin-left: auto; width: 18px; height: 18px; display: grid; place-items: center;
  background: transparent; border: 1px solid rgba(255,255,255,.1); border-radius: 4px;
  color: var(--nc-text-muted, #94a3b8); cursor: pointer;
}
.grc-h-refresh:hover:not(:disabled) { color: var(--nc-primary, #00d2d2); }
.grc-h-refresh:disabled { opacity: .4; cursor: wait; }
.grc-intel { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.grc-intel-tile {
  background: rgba(4,8,14,.45); border: 1px solid rgba(255,255,255,.06); border-radius: 8px;
  padding: 6px 8px; display: grid; gap: 2px;
}
.grc-intel-k { font-size: .56rem; text-transform: uppercase; letter-spacing: .1em; color: var(--nc-text-muted, #94a3b8); font-weight: 700; }
.grc-intel-v { font-size: .82rem; font-weight: 800; font-variant-numeric: tabular-nums; }
.grc-found {
  display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
  padding: 6px 9px; border-radius: 7px; font-size: .72rem; cursor: pointer;
  background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.06);
  color: var(--nc-text-primary, #e8eaed);
}
.grc-found:hover { border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); background: rgba(var(--nc-primary-rgb, 0,210,210), .05); }
.grc-found-bal { flex: 0 0 auto; font-size: .62rem; font-weight: 700; color: #10b981; font-variant-numeric: tabular-nums; }
.grc-spark { color: var(--nc-primary, #00d2d2); margin-left: 2px; }
.grc-act--mint { color: #fbbf24; border-color: rgba(245,158,11,.35); }
.grc-act--mint:hover:not(:disabled) { border-color: rgba(245,158,11,.6); background: rgba(245,158,11,.07); }
.grc-act {
  display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
  padding: 9px 11px; border-radius: 8px; cursor: pointer;
  background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08);
  color: var(--nc-text-primary, #e8eaed); font-size: .78rem;
}
.grc-act:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); background: rgba(var(--nc-primary-rgb, 0,210,210), .06); }
.grc-act:disabled { opacity: .45; cursor: not-allowed; }
.grc-act--danger:hover:not(:disabled) { border-color: rgba(239,68,68,.5); background: rgba(239,68,68,.06); }
.grc-act-t { display: grid; font-weight: 700; }
.grc-act-s { font-size: .62rem; font-weight: 500; color: var(--nc-text-muted, #94a3b8); }
.grc-act--inline { width: auto; flex: 0 0 auto; }
.grc-fund-local { display: flex; gap: 7px; align-items: stretch; }
.grc-input {
  flex: 1 1 auto; min-width: 0; padding: 8px 10px;
  background: rgba(4, 8, 14, 0.55); border: 1px solid rgba(255,255,255,.1); border-radius: 8px;
  color: var(--nc-text-primary, #e8eaed); font-size: .74rem; font-family: ui-monospace, monospace;
}
.grc-input:focus { outline: none; border-color: rgba(var(--nc-primary-rgb, 0,210,210), .55); }
.grc-note { margin: 0; font-size: .64rem; color: var(--nc-text-muted, #94a3b8); }
.grc-note--dim { opacity: .8; }
.grc-caps { display: flex; gap: 6px; flex-wrap: wrap; }
.grc-conn { display: grid; gap: 7px; }
.grc-conn-row { display: flex; gap: 7px; flex-wrap: wrap; }
.grc-conn-err { margin: 0; font-size: .68rem; color: #ef4444; }
.grc-connected {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 9px; border-radius: 8px; font-size: .72rem;
  background: rgba(16,185,129,.07); border: 1px solid rgba(16,185,129,.3);
}
.grc-connected-t { flex: 1 1 auto; color: var(--nc-text-primary, #e8eaed); }
.grc-h--sub { margin-top: 8px; }
.grc-roster-row {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 9px; border-radius: 7px; font-size: .72rem;
  background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.06);
}
.grc-roster-name { font-weight: 700; flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.grc-roster-did { flex: 1 1 auto; font-family: ui-monospace, monospace; font-size: .62rem; color: var(--nc-text-muted, #94a3b8); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.grc-roster-use {
  flex: 0 0 auto; min-height: 26px; padding: 0 10px; border-radius: 6px; cursor: pointer;
  font-size: .64rem; font-weight: 700;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .1);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .35);
  color: var(--nc-primary, #00d2d2);
}
.grc-roster-use:disabled { opacity: .45; cursor: not-allowed; }
.grc-roster-add { display: grid; grid-template-columns: 1.3fr 1fr 1fr auto; gap: 6px; }
@media (max-width: 640px) { .grc-roster-add { grid-template-columns: 1fr 1fr; } }
</style>
