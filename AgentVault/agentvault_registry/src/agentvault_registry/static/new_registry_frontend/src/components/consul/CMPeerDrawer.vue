<template>
  <transition name="cm-drawer">
    <aside v-if="open" class="cm-drawer">
      <header class="cm-drawer-header">
        <div class="cm-drawer-title">
          <span class="cm-drawer-name">{{ peer?.display_name ?? 'Peer detail' }}</span>
          <span class="cm-drawer-sub" v-if="peer">
            <code>{{ peer.operator_id }}</code>
            · <span class="cm-frame-pill" data-testid="cm-drawer-frame">{{ frameText }}</span>
            · <span class="cm-role">{{ peer.role }}</span>
          </span>
        </div>
        <button class="cm-close" @click="$emit('close')" aria-label="Close">✕</button>
      </header>

      <div class="cm-drawer-body">
        <!-- Identity resolution (WS-G) — from the roster row, shown instantly, no policy-fetch wait. -->
        <section class="cm-block cm-id-block" v-if="peer">
          <h4>Identity resolution</h4>
          <div class="cm-status-strip">
            <span class="cm-kv"><b>STATE</b> <span class="cm-id-tag" :class="identityCls">{{ identityLabel }}</span></span>
            <span class="cm-kv"><b>TRUST DOMAIN</b> {{ peer.trust_domain || '—' }}</span>
            <span class="cm-kv"><b>HOME FRAME</b> {{ peer.home_frame || '—' }}</span>
            <span class="cm-kv" v-if="peer.resolution_source"><b>VIA</b> {{ peer.resolution_source }}</span>
            <span class="cm-kv"><b>CURRENCY</b> {{ peer.currency_zone || '—' }}</span>
          </div>
          <p class="cm-id-note cm-id-note-bad" v-if="identityState === 'unidentified'">
            No trust domain resolves for this peer: a cross-frame payment to it is <strong>refused</strong>.
          </p>
          <p class="cm-id-note" v-else-if="identityState === 'pending'">
            This registry's release does not report peer identity (it arrived in V0561).
          </p>
        </section>

        <div v-if="loadingDetail" class="cm-dim cm-drawer-loading">Loading live policy…</div>

        <template v-else-if="detail">
          <!-- Banner: mainframe / not-admitted -->
          <div v-if="detail.role === 'mainframe'" class="cm-banner cm-banner-info">
            <strong>Mainframe.</strong>
            This is a central registry — it is the poller, not the polled.
            Compliance actions don't apply here.
          </div>
          <div
            v-else-if="!detail.has_compliance_record"
            class="cm-banner cm-banner-info"
          >
            <strong>No baseline yet.</strong>
            The compliance poller records one from this peer's first answer: it reads every active peer once a cycle,
            and an approved federation records it at once.
          </div>

          <!-- Status strip -->
          <div class="cm-status-strip">
            <span class="cm-kv"><b>STATUS</b> {{ detail.federation_status ?? (detail.has_compliance_record ? '—' : 'not admitted') }}</span>
            <span class="cm-kv"><b>SCORE</b> {{ detail.compliance_score?.toFixed(0) ?? '—' }}</span>
            <span class="cm-kv"><b>DRIFTS</b> {{ detail.drift_events_count ?? 0 }}</span>
            <span class="cm-kv"><b>FAIL STREAK</b> {{ detail.consecutive_poll_failures ?? 0 }} / 3</span>
            <span class="cm-kv"><b>LAST POLL</b> {{ timeAgo(detail.last_poll_at) }}</span>
          </div>

          <!-- Hash comparison -->
          <section class="cm-block">
            <h4>Policy hash</h4>
            <div class="cm-hash-row">
              <div class="cm-hash-col">
                <div class="cm-dim">BASELINE<template v-if="baselineFrom"> · {{ baselineFrom }}</template></div>
                <code class="cm-hash">{{ detail.admitted_policy_hash ?? '—' }}</code>
              </div>
              <div class="cm-hash-equals" :class="matchClass">
                {{ matchSymbol }}
              </div>
              <div class="cm-hash-col">
                <div class="cm-dim">LIVE</div>
                <code class="cm-hash" v-if="detail.live_policy_fetched">
                  {{ detail.live_policy_hash }}
                </code>
                <code class="cm-hash cm-hash-err" v-else>
                  unreachable · {{ detail.live_fetch_error ?? 'unknown' }}
                </code>
              </div>
            </div>
          </section>

          <!-- Diff table -->
          <section class="cm-block" v-if="detail.diff && detail.diff.length">
            <h4>Locked-params diff ({{ mismatchCount }} mismatch{{ mismatchCount === 1 ? '' : 'es' }})</h4>
            <table class="cm-diff">
              <thead>
                <tr><th>Path</th><th>Severity</th><th>Stored</th><th>Live</th><th></th></tr>
              </thead>
              <tbody>
                <tr v-for="row in detail.diff" :key="row.path" :class="row.match ? 'ok' : `mismatch sev-${row.severity?.toLowerCase()}`">
                  <td class="cm-path">{{ row.path }}</td>
                  <td>{{ row.severity ?? '—' }}</td>
                  <td><code>{{ formatVal(row.stored_value) }}</code></td>
                  <td><code>{{ formatVal(row.live_value) }}</code></td>
                  <td class="cm-match-cell">{{ row.match ? '✓' : '✗' }}</td>
                </tr>
              </tbody>
            </table>
          </section>

          <section class="cm-block" v-else-if="detail.live_policy_fetched && !detail.live_policy_json">
            <p class="cm-info">
              A peer publishes its policy's hash, not the document, so the comparison is the hash above.
            </p>
          </section>

          <!-- §MCPTEST30 (V0561): accept the peer's current policy as its baseline, after a drift the admin reviewed -->
          <section class="cm-block cm-accept" v-if="canAccept" data-testid="cm-accept-baseline">
            <h4>Accept the peer's current policy</h4>
            <p class="cm-info">
              The live hash differs from the baseline.
              <template v-if="versionLine">{{ versionLine }}</template>
              If the change is expected, make the live policy the new baseline: the poller compares against it from its
              next cycle, the previous baseline stays in the record and the acceptance goes on the ledger.
            </p>
            <label class="cm-accept-label" for="cm-accept-reason">Why this policy is accepted</label>
            <textarea id="cm-accept-reason" v-model="acceptReason" class="cm-accept-reason" rows="2" maxlength="500"
                      placeholder="At least 5 characters, kept on the ledger" data-testid="cm-accept-reason"></textarea>
            <div class="cm-action-row">
              <button class="cm-btn-good" :disabled="accepting || acceptReason.trim().length < 5 || canEnforce === false"
                      :title="canEnforce === false ? 'Needs the enforcement admin flag' : undefined"
                      data-testid="cm-accept-submit"
                      @click="$emit('accept-baseline', { peerId: detail!.peer_registry_id, expectedHash: detail!.live_policy_hash!, reason: acceptReason.trim() })">
                {{ accepting ? 'Accepting…' : 'Accept as baseline' }}
              </button>
            </div>
          </section>

          <!-- Quarantine history -->
          <section class="cm-block" v-if="detail.quarantine_events && detail.quarantine_events.length">
            <h4>Quarantine history</h4>
            <ul class="cm-events">
              <li v-for="(ev, idx) in detail.quarantine_events" :key="idx">
                <span class="cm-dim">{{ (ev as any).timestamp }}</span>
                <span class="cm-sev" :class="`sev-${((ev as any).severity ?? '').toLowerCase()}`">{{ (ev as any).severity }}</span>
                {{ (ev as any).reason }}
                <em v-if="(ev as any).triggered_by">— {{ (ev as any).triggered_by }}</em>
              </li>
            </ul>
          </section>

          <!-- Actions -->
          <section class="cm-block cm-actions" v-if="detail.role !== 'mainframe'">
            <h4>Actions</h4>
            <div v-if="!detail.peer_registry_id" class="cm-dim cm-action-hint">
              This target has no peer row on this registry, so there is nothing to poll, quarantine or blacklist.
            </div>
            <div v-else class="cm-action-row">
              <button
                class="cm-btn-ghost"
                :disabled="polling"
                @click="$emit('poll-now', detail!.peer_registry_id)"
              >
                {{ polling ? 'Polling…' : 'Poll now (dry-run)' }}
              </button>

              <button
                v-if="detail.federation_status === 'federated'"
                class="cm-btn-warn"
                :disabled="quarantining || canEnforce === false"
                :title="canEnforce === false ? 'Needs the enforcement admin flag' : undefined"
                @click="$emit('manual-quarantine', detail!.peer_registry_id)"
              >
                Manual quarantine
              </button>

              <button
                v-if="detail.federation_status === 'quarantined' || detail.federation_status === 'soft_quarantined'"
                class="cm-btn-good"
                :disabled="canEnforce === false"
                :title="canEnforce === false ? 'Needs the enforcement admin flag' : undefined"
                @click="$emit('lift', detail!.peer_registry_id)"
              >
                Lift quarantine
              </button>

              <button
                class="cm-btn-danger"
                v-if="detail.federation_status !== 'blacklisted'"
                :disabled="canEnforce === false"
                :title="canEnforce === false ? 'Needs the enforcement admin flag' : undefined"
                @click="$emit('blacklist', detail!.peer_registry_id)"
              >
                Blacklist…
              </button>
            </div>
          </section>
        </template>

        <div v-else class="cm-dim">Select a peer from the grid to view detail.</div>
      </div>
    </aside>
  </transition>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

import type { PeerComplianceRow, PeerDetail } from '@/services/api/consulApi'

const props = defineProps<{
  open: boolean
  peer: PeerComplianceRow | null
  detail: PeerDetail | null
  loadingDetail: boolean
  polling: boolean
  quarantining: boolean
  accepting?: boolean
  canEnforce?: boolean   // V0562: quarantine, lift, blacklist and accept need admin_enforcement on the server
}>()

defineEmits<{
  (e: 'close'): void
  (e: 'poll-now', peerId: number): void
  (e: 'manual-quarantine', peerId: number): void
  (e: 'lift', peerId: number): void
  (e: 'blacklist', peerId: number): void
  (e: 'accept-baseline', payload: { peerId: number; expectedHash: string; reason: string }): void
}>()

// §MCPTEST30 (V0561): the frame the roster places this peer in (its trust domain's frame), never a retired letter
const frameText = computed(() => {
  const p = props.peer
  if (!p) return ''
  return p.home_frame ? `frame ${p.home_frame}` : (p.trust_domain || p.frame || '?')
})
const BASELINE_FROM: Record<string, string> = {
  'compliance_poller:first_sight': 'first sight',
}
const baselineFrom = computed(() => {
  const src = props.detail?.baseline_source || props.peer?.baseline_source || ''
  if (!src) return ''
  return BASELINE_FROM[src] || `accepted by ${src}`
})
const acceptReason = ref('')
watch(() => props.detail?.peer_registry_id, () => { acceptReason.value = '' })
const canAccept = computed(() => {
  const d = props.detail
  return !!d && !!d.peer_registry_id && d.federation_status === 'federated' && d.hash_match === false && !!d.live_policy_hash
})
const versionLine = computed(() => {
  const d = props.detail
  if (!d || d.live_policy_version == null || d.admitted_policy_version == null) return ''
  const b = `version ${d.admitted_policy_version}${d.admitted_policy_source ? ` (${d.admitted_policy_source})` : ''}`
  const l = `version ${d.live_policy_version}${d.live_policy_source ? ` (${d.live_policy_source})` : ''}`
  const same = d.admitted_policy_version === d.live_policy_version && (d.admitted_policy_source || '') === (d.live_policy_source || '')
  return `The peer reports ${b} for the baseline and ${l} now`
    + (same ? ': the same version, so the document changed without an amendment, which is what a release changing a shipped default looks like.' : '.')
})

const matchClass = computed(() => {
  if (!props.detail) return ''
  if (props.detail.hash_match === null) return 'unk'
  return props.detail.hash_match ? 'ok' : 'err'
})
const matchSymbol = computed(() => {
  if (!props.detail) return '—'
  if (props.detail.hash_match === null) return '—'
  return props.detail.hash_match ? '=' : '≠'
})
const mismatchCount = computed(
  () => (props.detail?.diff ?? []).filter(r => !r.match).length,
)

// ── WS-G identity resolution (forward-compatible) ───────────────────────────
const identityState = computed<'resolved' | 'unidentified' | 'pending'>(() => {
  const p = props.peer
  if (!p) return 'pending'
  if (p.resolution_state === 'resolved') return 'resolved'
  if (p.resolution_state === 'unidentified') return 'unidentified'
  if (p.trust_domain) return 'resolved'
  return 'pending'
})
const identityLabel = computed(() =>
  identityState.value === 'resolved'
    ? 'resolved'
    : identityState.value === 'unidentified'
      ? 'unidentified · would refuse'
      : 'not reported',
)
const identityCls = computed(() => `cm-id-${identityState.value}`)

function timeAgo(ts: string | null) { return ts ? dayjs(ts).fromNow() : '—' }
function formatVal(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
</script>

<style scoped>
.cm-drawer {
  position: fixed;
  /* Offset below the 48px DashboardHeader so title + close button are never occluded */
  top: 48px;
  right: 0;
  height: calc(100vh - 48px);
  width: 720px; max-width: 95vw;
  background: var(--nc-deep);
  border-left: 1px solid var(--nc-border);
  color: var(--nc-text-primary);
  display: flex; flex-direction: column;
  z-index: 1500;
  box-shadow: var(--nc-shadow-xl);
}
.cm-drawer-header {
  padding: 14px 18px; display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--nc-border);
  background: var(--nc-surface);
}
.cm-drawer-title { display: flex; flex-direction: column; gap: 3px; }
.cm-drawer-name { font-size: 14px; letter-spacing: 0.06em; color: var(--nc-text-primary); font-weight: 600; }
.cm-drawer-sub { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10px; color: var(--nc-text-muted); letter-spacing: 0.04em; display: inline-flex; gap: 8px; align-items: center; }
.cm-drawer-sub code { font-family: inherit; color: var(--nc-text-secondary); background: transparent; padding: 0; }
.cm-frame-pill {
  padding: 1px 6px; border-radius: 8px; font-size: 9px; letter-spacing: 0.12em;
  border: 1px solid;
}
.cm-frame-a { color: var(--nc-primary); border-color: var(--nc-primary-subtle); background: var(--nc-primary-subtle); }
.cm-frame-b { color: var(--nc-chart-5); border-color: rgba(153, 102, 255, 0.25); background: rgba(153, 102, 255, 0.08); }
.cm-frame-\? { color: var(--nc-text-muted); border-color: var(--nc-border); background: transparent; }
.cm-role { color: var(--nc-text-secondary); text-transform: uppercase; font-size: 9px; letter-spacing: 0.1em; }

/* WS-G identity resolution block */
.cm-id-tag {
  padding: 1px 7px; border-radius: 8px; font-size: 9px; letter-spacing: 0.06em;
  font-family: 'JetBrains Mono', ui-monospace, monospace; border: 1px solid transparent;
}
.cm-id-resolved     { background: var(--nc-success-subtle); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.25); }
.cm-id-unidentified { background: var(--nc-danger-subtle);  color: var(--nc-danger);  border-color: rgba(255, 51, 102, 0.35); }
.cm-id-pending      { background: var(--nc-border);         color: var(--nc-text-secondary); }  /* §FESUITE: 5.0:1 on its fill (the muted text was 4.3:1) */
.cm-id-note { margin: 8px 0 0; font-size: 10px; line-height: 1.5; color: var(--nc-text-muted); font-family: 'JetBrains Mono', ui-monospace, monospace; }
.cm-id-note-bad, .cm-id-note-bad strong { color: var(--nc-danger); }
.cm-close {
  background: transparent; border: 1px solid var(--nc-border);
  color: var(--nc-text-secondary);
  width: 28px; height: 28px;
  border-radius: 6px; cursor: pointer; font-size: 12px;
}
.cm-close:hover { border-color: var(--nc-border-strong); color: var(--nc-text-primary); }
.cm-drawer-body { overflow-y: auto; padding: 16px 18px; flex: 1; display: flex; flex-direction: column; gap: 16px; }
.cm-drawer-loading { padding: 40px; text-align: center; }

.cm-banner { padding: 10px 14px; border-radius: 6px; font-size: 12px; line-height: 1.55; border: 1px solid; }
.cm-banner-info {
  background: var(--nc-primary-subtle);
  border-color: var(--nc-primary-subtle);
  color: var(--nc-text-primary);
}

.cm-status-strip {
  display: flex; flex-wrap: wrap; gap: 14px 18px;
  background: var(--nc-surface);
  padding: 10px 14px; border-radius: 6px;
  border: 1px solid var(--nc-border);
}
.cm-kv { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; color: var(--nc-text-primary); }
.cm-kv b { color: var(--nc-text-muted); font-weight: 400; margin-right: 6px; font-size: 9px; letter-spacing: 0.1em; }

.cm-block { display: flex; flex-direction: column; gap: 8px; }
.cm-block h4 { margin: 0; font-size: 10px; letter-spacing: 0.12em; color: var(--nc-primary); text-transform: uppercase; font-weight: 600; font-family: 'JetBrains Mono', ui-monospace, monospace; }

.cm-hash-row { display: grid; grid-template-columns: 1fr auto 1fr; gap: 10px; align-items: center; }
.cm-hash-col { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.cm-hash {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 10px; color: var(--nc-text-primary);
  word-break: break-all; display: block;
  padding: 6px 8px;
  background: var(--nc-surface);
  border-radius: 4px;
  border: 1px solid var(--nc-border);
}
.cm-hash-err { color: var(--nc-danger); }
.cm-hash-equals { font-size: 20px; font-family: 'JetBrains Mono', ui-monospace, monospace; text-align: center; }
.cm-hash-equals.ok  { color: var(--nc-success); }
.cm-hash-equals.err { color: var(--nc-danger); }
.cm-hash-equals.unk { color: var(--nc-text-muted); }

.cm-dim { color: var(--nc-text-muted); font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; font-family: 'JetBrains Mono', ui-monospace, monospace; }

.cm-diff { width: 100%; border-collapse: collapse; font-size: 11px; }
.cm-diff th { text-align: left; padding: 6px 8px; color: var(--nc-text-muted); font-weight: 400; text-transform: uppercase; font-size: 9px; letter-spacing: 0.1em; border-bottom: 1px solid var(--nc-border); }
.cm-diff td { padding: 6px 8px; border-bottom: 1px solid var(--nc-border-subtle); vertical-align: top; }
.cm-diff tr.ok td { color: var(--nc-text-secondary); }
.cm-diff tr.mismatch td { color: var(--nc-text-primary); }
.cm-diff tr.mismatch { border-left: 3px solid var(--nc-warning); }
.cm-diff tr.mismatch.sev-critical { border-left-color: var(--nc-danger); }
.cm-diff tr.mismatch.sev-high     { border-left-color: var(--nc-warning); }
.cm-diff tr.mismatch.sev-medium   { border-left-color: var(--nc-chart-3); }
.cm-diff tr.mismatch.sev-low      { border-left-color: var(--nc-primary); }
.cm-path { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10px; }
.cm-diff code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10px; color: var(--nc-text-primary); background: transparent; padding: 0; }
.cm-match-cell { text-align: center; font-family: 'JetBrains Mono', ui-monospace, monospace; }

.cm-events { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; font-size: 12px; line-height: 1.5; }
.cm-events li { border-left: 2px solid var(--nc-border); padding-left: 10px; color: var(--nc-text-secondary); }
.cm-sev { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 9px; letter-spacing: 0.1em; margin-right: 6px; }
.cm-sev.sev-critical { background: var(--nc-danger-subtle);  color: var(--nc-danger); }
.cm-sev.sev-high     { background: var(--nc-warning-subtle); color: var(--nc-warning); }
.cm-sev.sev-medium   { background: var(--nc-warning-subtle); color: var(--nc-chart-3); }
.cm-sev.sev-low      { background: var(--nc-primary-subtle); color: var(--nc-primary); }

.cm-info { font-size: 12px; line-height: 1.55; color: var(--nc-text-secondary); margin: 0; }
/* §MCPTEST30 (V0561): the accept-baseline block */
.cm-accept { border: 1px solid var(--nc-success-subtle); border-radius: 8px; padding: 12px; }
.cm-accept-label { font-size: 11px; color: var(--nc-text-secondary); }
.cm-accept-reason {
  width: 100%; resize: vertical; background: var(--nc-surface); color: var(--nc-text-primary);
  border: 1px solid var(--nc-border); border-radius: 6px; padding: 8px 10px; font: inherit; font-size: 12px;
}
.cm-accept-reason:focus-visible { outline: 2px solid var(--nc-primary); outline-offset: 1px; }
.cm-btn-good:disabled { opacity: 0.5; cursor: not-allowed; }
.cm-actions { padding-bottom: 14px; }
.cm-action-row { display: flex; gap: 8px; flex-wrap: wrap; }
.cm-action-hint { font-size: 11px; letter-spacing: 0; text-transform: none; }

.cm-btn-ghost  { background: transparent; color: var(--nc-text-primary); border: 1px solid var(--nc-border); border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 11px; }
.cm-btn-ghost:hover:not(:disabled) { border-color: var(--nc-border-strong); }
.cm-btn-ghost:disabled { opacity: 0.5; cursor: not-allowed; }
.cm-btn-warn   { background: var(--nc-warning-subtle); color: var(--nc-warning); border: 1px solid var(--nc-warning-subtle); border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 11px; }
.cm-btn-good   { background: var(--nc-success-subtle); color: var(--nc-success); border: 1px solid var(--nc-success-subtle); border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 11px; }
.cm-btn-danger { background: var(--nc-danger-subtle);  color: var(--nc-danger);  border: 1px solid var(--nc-danger-subtle);  border-radius: 6px; padding: 7px 14px; cursor: pointer; font-size: 11px; }

.cm-drawer-enter-active, .cm-drawer-leave-active { transition: transform 0.25s ease; }
.cm-drawer-enter-from, .cm-drawer-leave-to { transform: translateX(100%); }

code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; background: var(--nc-deep); padding: 1px 4px; border-radius: 3px; color: var(--nc-text-primary); }
</style>
