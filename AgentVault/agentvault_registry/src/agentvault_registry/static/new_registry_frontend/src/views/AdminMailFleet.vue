<template>
  <!-- §FRAMEMAIL-5 (2026-08-02) — Mail Fleet console.
       Exists because on 2026-08-01 fourteen operators were found demanding email
       verification while pointing at smtp.example.com: every self-registered account
       permanently unverifiable, invisible without shelling into containers.
       This view answers two questions per node — does it demand verification, and
       can it actually send — and names the broken combination outright. -->
  <div class="mf">
    <div class="mf-ambient"><div class="mf-grid"></div><div class="mf-glow"></div></div>

    <section class="mf-hero" data-tour="mail-hero">
      <div class="mf-hero-inner">
        <div class="mf-chip"><span class="mf-chip-dot"></span>MAIL FLEET</div>
        <h1 class="mf-h1">Mail <span class="mf-accent">Console</span></h1>
        <p class="mf-lead">
          Every node in the cluster: does it demand email verification, and can it actually
          send it. A node that answers yes then no is locked out — nobody who registers there
          can ever verify.
        </p>
      </div>
    </section>

    <!-- Not this registry's job -->
    <div v-if="notAuthority" class="mf-card mf-note">
      <h3>Not managed here</h3>
      <p>
        This registry holds no fleet mail credentials, so there is nothing to administer.
        The mail console lives on the registry that owns the shared sender.
      </p>
    </div>

    <template v-else>
      <!-- Verdict banner -->
      <div v-if="fleet" class="mf-banner" data-tour="mail-banner" :class="bannerClass">
        <div class="mf-banner-main">
          <span class="mf-banner-dot"></span>
          <strong>{{ bannerTitle }}</strong>
          <span class="mf-banner-sub">{{ bannerSub }}</span>
        </div>
        <button class="mf-btn mf-btn--ghost" :disabled="loading" @click="loadAll">
          {{ loading ? 'Checking…' : '↻ Re-check' }}
        </button>
      </div>

      <div v-if="error" class="mf-card mf-err">
        <strong>Could not load.</strong> {{ error }}
        <button class="mf-btn mf-btn--ghost" @click="loadAll">Retry</button>
      </div>

      <!-- Sender identity + credential -->
      <div class="mf-row">
        <div class="mf-card mf-card--grow">
          <h3 class="mf-h3">Shared sender</h3>
          <div v-if="sender" class="mf-kv">
            <div><span>From</span><b>{{ sender.from_address || '—' }}</b></div>
            <div><span>Display name</span><b>{{ sender.from_name || '—' }}</b></div>
            <div><span>SMTP</span><b>{{ sender.server || '—' }}:{{ sender.port || '—' }}</b></div>
            <div>
              <span>Credential</span>
              <b :class="sender.credential_present ? 'mf-ok' : 'mf-bad'">
                {{ sender.credential_present ? 'present' : 'absent' }}
              </b>
            </div>
            <div>
              <span>Relay</span>
              <b :class="sender.relay_enabled ? 'mf-ok' : 'mf-muted'">
                {{ sender.relay_enabled ? 'enabled' : 'disabled' }}
              </b>
            </div>
            <!-- The relay's per-caller ceilings are deliberately NOT surfaced. They
                 bound what ONE token-less node may ask this registry to send on its
                 behalf. Printed under "Shared sender" they read as this sender's
                 capacity, which is a different and much larger number, and a figure
                 shown in an admin console gets planned against. They still apply; they
                 are simply not a headline. The API returns them for anyone who needs
                 the exact value. -->
          </div>
          <div class="mf-actions">
            <button class="mf-btn" :disabled="checking" @click="doVerify">
              {{ checking ? 'Authenticating…' : 'Verify credential' }}
            </button>
            <span v-if="credResult" class="mf-inline" :class="credResult.ok ? 'mf-ok' : 'mf-bad'">
              {{ credResult.ok ? `AUTH OK as ${credResult.username}` : credResult.error }}
            </span>
          </div>
          <p class="mf-hint">
            Opens a real SMTP session and authenticates. Sends nothing. A token revoked
            upstream looks identical to a working one in any config view — only an AUTH tells you.
          </p>
        </div>

        <!-- Test send -->
        <div class="mf-card">
          <h3 class="mf-h3">Send a test</h3>
          <input v-model="testTo" class="mf-input" type="email" placeholder="you@example.com" />
          <input v-model="testNote" class="mf-input" type="text" placeholder="Optional note in the body" />
          <button class="mf-btn mf-btn--send" :disabled="sending || !testTo" @click="doTestSend">
            {{ sending ? 'Sending…' : 'Send real email' }}
          </button>
          <p v-if="sendResult" class="mf-inline" :class="sendResult.ok ? 'mf-ok' : 'mf-bad'">{{ sendResult.msg }}</p>
          <p class="mf-hint">A real delivery, not a preview — the point is to exercise SMTP end to end.</p>
        </div>
      </div>

      <!-- Fleet table -->
      <div class="mf-card">
        <div class="mf-card-head">
          <h3 class="mf-h3">Fleet posture</h3>
          <div class="mf-filters">
            <button v-for="f in filters" :key="f" class="mf-pill"
                    :class="{ 'mf-pill--on': activeFilter === f }" @click="activeFilter = f">
              {{ f }}<span v-if="counts[f] !== undefined" class="mf-pill-n">{{ counts[f] }}</span>
            </button>
          </div>
        </div>

        <div class="mf-tablewrap">
          <table class="mf-table">
            <thead>
              <tr>
                <th>Node</th><th>Kind</th><th>Verification</th><th>Invites</th>
                <th>Sends via</th><th>Verdict</th><th>Detail</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="n in visibleNodes" :key="n.name" :class="rowClass(n)">
                <td>
                  <b>{{ n.name }}</b>
                  <a v-if="n.public_url" :href="safeExternalUrl(n.public_url)" target="_blank" rel="noopener" class="mf-link">↗</a>
                  <div v-if="n.peer_status && n.peer_status !== 'ACTIVE'" class="mf-sub">peer {{ n.peer_status }}</div>
                </td>
                <td class="mf-muted">{{ n.kind }}</td>
                <td><span :class="boolClass(n.verification_required)">{{ fmtBool(n.verification_required) }}</span></td>
                <td><span :class="boolClass(n.invite_required)">{{ fmtBool(n.invite_required) }}</span></td>
                <td><span class="mf-tag" :class="'mf-tag--' + n.send_path">{{ n.send_path }}</span></td>
                <td><span class="mf-verdict" :class="'mf-verdict--' + n.verdict.toLowerCase()">{{ n.verdict }}</span></td>
                <td class="mf-detail">{{ n.detail }}</td>
              </tr>
              <tr v-if="!visibleNodes.length && fleetRead"><td colspan="7" class="mf-empty">No nodes match this filter.</td></tr>
            </tbody>
          </table>
        </div>
        <p class="mf-hint">
          Verification and invite state are read from each node's own public
          <code>/auth/registration-config</code> — what it tells a real user, not what our
          config believes about it. If those disagree, this shows the node's answer.
        </p>
      </div>

      <!-- Relay: licenses + activity -->
      <div v-if="sender && sender.relay_enabled" class="mf-row">
        <div class="mf-card mf-card--grow">
          <h3 class="mf-h3">Relay callers</h3>
          <p class="mf-hint mf-hint--top">
            Nodes that hold no submission token and ask this registry to send for them.
            Revoking bites on the very next request — the relay re-checks licence status every call.
          </p>
          <!-- Wrapped like every other table here. Unwrapped it forced its card wider
               than a phone viewport and clipped the surrounding prose. -->
          <div class="mf-tablewrap">
          <table class="mf-table">
            <thead><tr><th>Node</th><th>Status</th><th>Last seen</th><th></th></tr></thead>
            <tbody>
              <tr v-for="l in licenses" :key="l.operator_did">
                <td><b>{{ l.label }}</b><div class="mf-sub">{{ l.base_url }}</div></td>
                <td><span class="mf-verdict" :class="l.status === 'active' ? 'mf-verdict--ok' : 'mf-verdict--lockout'">{{ l.status }}</span></td>
                <td class="mf-muted">{{ l.last_seen_at ? fmtTime(l.last_seen_at) : 'never' }}</td>
                <td>
                  <button v-if="l.status === 'active'" class="mf-btn mf-btn--danger mf-btn--sm"
                          @click="doRevoke(l)">Revoke</button>
                  <button v-else class="mf-btn mf-btn--sm" @click="doReinstate(l)">Reinstate</button>
                </td>
              </tr>
              <tr v-if="relayRead && !licenses.length"><td colspan="4" class="mf-empty" data-testid="mf-no-callers">No relay callers configured.</td></tr>
              <tr v-else-if="!relayRead && !licenses.length"><td colspan="4" class="mf-empty" data-testid="mf-callers-unread">—</td></tr>
            </tbody>
          </table>
          </div>
        </div>

        <div class="mf-card mf-card--grow">
          <h3 class="mf-h3">Relay activity</h3>
          <div v-if="last24h.length" class="mf-24h">
            <span v-for="c in last24h" :key="c.caller" class="mf-24h-item">
              <b>{{ c.caller }}</b>
              <span class="mf-ok">{{ c.success }} sent</span>
              <span v-if="c.denied" class="mf-bad">{{ c.denied }} denied</span>
              <span v-if="c.failure" class="mf-bad">{{ c.failure }} failed</span>
            </span>
          </div>
          <div class="mf-tablewrap mf-tablewrap--short">
            <table class="mf-table">
              <thead><tr><th>When</th><th>Caller</th><th>Template</th><th>Outcome</th></tr></thead>
              <tbody>
                <tr v-for="(e, i) in events" :key="i">
                  <td class="mf-muted">{{ fmtTime(e.at) }}</td>
                  <td>{{ e.caller }}</td>
                  <td class="mf-muted">{{ e.template }}</td>
                  <td>
                    <span class="mf-verdict" :class="e.outcome === 'success' ? 'mf-verdict--ok' : 'mf-verdict--lockout'">
                      {{ e.outcome }}</span>
                    <span v-if="e.reason" class="mf-sub">{{ e.reason }}</span>
                  </td>
                </tr>
                <tr v-if="relayRead && !events.length"><td colspan="4" class="mf-empty">No relay traffic recorded.</td></tr>
                <tr v-else-if="!relayRead && !events.length"><td colspan="4" class="mf-empty">—</td></tr>
              </tbody>
            </table>
          </div>
          <p class="mf-hint">Recipients are stored as a hash, never as an address.</p>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted } from 'vue'
import {
  mailFleetService,
  type FleetResponse, type SenderInfo, type NodeMailStatus,
  type RelayEvent, type RelayLicense,
} from '@/services/api/mailFleet'

const fleet = ref<FleetResponse | null>(null)
const sender = ref<SenderInfo | null>(null)
const events = ref<RelayEvent[]>([])
const last24h = ref<any[]>([])
const licenses = ref<RelayLicense[]>([])

const loading = ref(false)
const error = ref('')
const notAuthority = ref(false)
// §FESUITE (2026-10-04): "No nodes match this filter." was drawn with the fleet's read failed; only a read that answered
// says none (the error line says a failed one)
const fleetRead = ref(false)
// §FESUITE (2026-10-05): the same for the relay's two tables: a failed relay read drew "No relay callers configured." and
// "No relay traffic recorded." under the error card; they read a dash until the relay read answered
const relayRead = ref(false)

const checking = ref(false)
const credResult = ref<{ ok: boolean; username?: string; error?: string } | null>(null)
const sending = ref(false)
const testTo = ref('')
const testNote = ref('')
const sendResult = ref<{ ok: boolean; msg: string } | null>(null)

const filters = ['all', 'LOCKOUT', 'UNGATED', 'UNREACHABLE', 'OK', 'INACTIVE'] as const
const activeFilter = ref<string>('all')

const counts = computed<Record<string, number>>(() => {
  const c: Record<string, number> = {}
  for (const n of fleet.value?.nodes || []) c[n.verdict] = (c[n.verdict] || 0) + 1
  c.all = fleet.value?.nodes.length || 0
  return c
})

const visibleNodes = computed<NodeMailStatus[]>(() => {
  const all = fleet.value?.nodes || []
  const list = activeFilter.value === 'all' ? all : all.filter(n => n.verdict === activeFilter.value)
  // Problems first — this view exists to surface them, not to be sorted alphabetically.
  const rank: Record<string, number> = { LOCKOUT: 0, UNGATED: 1, UNREACHABLE: 2, UNKNOWN: 3, OK: 4, INACTIVE: 5 }
  return [...list].sort((a, b) => (rank[a.verdict] ?? 9) - (rank[b.verdict] ?? 9) || a.name.localeCompare(b.name))
})

const bannerClass = computed(() => {
  const s = fleet.value?.summary
  if (!s) return ''
  if (s.lockout) return 'mf-banner--bad'
  if (s.ungated || s.unreachable) return 'mf-banner--warn'
  return 'mf-banner--ok'
})
const bannerTitle = computed(() => {
  const s = fleet.value?.summary
  if (!s) return ''
  if (s.lockout) return `${s.lockout} node${s.lockout > 1 ? 's' : ''} locked out`
  if (s.ungated) return `${s.ungated} node${s.ungated > 1 ? 's' : ''} ungated`
  if (s.unreachable) return `${s.unreachable} node${s.unreachable > 1 ? 's' : ''} unreachable`
  return 'All nodes healthy'
})
const bannerSub = computed(() => {
  const s = fleet.value?.summary
  if (!s) return ''
  if (s.lockout) return 'Verification demanded with no way to send it — new accounts there cannot be verified.'
  if (s.ungated) return 'Neither verification nor invite codes — registration is open to anyone.'
  if (s.unreachable) return 'Posture unknown for some nodes; unknown is not the same as fine.'
  // Say what the remainder IS. "18/20" next to "all healthy" reads like two missing
  // nodes rather than two deliberately deactivated peers.
  const inactive = (s as any).inactive || 0
  return inactive
    ? `${s.ok} live nodes verified as coherent, ${inactive} deactivated peer${inactive > 1 ? 's' : ''} not probed.`
    : `${s.ok}/${s.total} nodes verified as coherent.`
})

function fmtBool(v: boolean | null) { return v === null ? '—' : v ? 'required' : 'off' }
function boolClass(v: boolean | null) { return v === null ? 'mf-muted' : v ? 'mf-ok' : 'mf-muted' }
function rowClass(n: NodeMailStatus) {
  // INACTIVE deliberately gets no tint: a deactivated peer is in the state someone
  // chose for it, not a condition anyone needs to notice.
  return n.verdict === 'LOCKOUT' ? 'mf-tr--bad'
    : (n.verdict === 'UNGATED' || n.verdict === 'UNREACHABLE') ? 'mf-tr--warn'
    : n.verdict === 'INACTIVE' ? 'mf-tr--dim' : ''
}
function fmtTime(iso: string | null) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString(appLocale()) } catch { return iso }
}

async function loadAll() {
  loading.value = true; error.value = ''
  try {
    const [f, s] = await Promise.all([mailFleetService.fleet(), mailFleetService.sender()])
    fleet.value = f; sender.value = s
    fleetRead.value = true
    if (s.relay_enabled) {
      const [a, l] = await Promise.all([mailFleetService.relayActivity(50), mailFleetService.relayLicenses()])
      events.value = a.events; last24h.value = a.last_24h; licenses.value = l.licenses
      relayRead.value = true
    }
  } catch (e: any) {
    // 404 = this registry does not manage mail. That is a valid state, not a failure.
    if (e?.response?.status === 404) notAuthority.value = true
    else error.value = e?.response?.data?.detail || e?.message || 'Unknown error'
  } finally {
    loading.value = false
  }
}

async function doVerify() {
  checking.value = true; credResult.value = null
  try { credResult.value = await mailFleetService.verifyCredential() }
  catch (e: any) { credResult.value = { ok: false, error: e?.response?.data?.detail || e?.message } }
  finally { checking.value = false }
}

async function doTestSend() {
  sending.value = true; sendResult.value = null
  try {
    const r = await mailFleetService.testSend(testTo.value.trim(), testNote.value.trim())
    sendResult.value = { ok: true, msg: `Sent to ${r.recipient}. Check the inbox — delivery is the proof.` }
  } catch (e: any) {
    sendResult.value = { ok: false, msg: e?.response?.data?.detail || e?.message || 'Send failed' }
  } finally { sending.value = false }
}

async function doRevoke(l: RelayLicense) {
  if (!window.confirm(`Revoke mail relay for ${l.label}?\n\nIt will be unable to send verification or password-reset email from its next request onward.`)) return
  try { await mailFleetService.revokeRelay(l.operator_did); await loadAll() }
  catch (e: any) { error.value = e?.response?.data?.detail || e?.message }
}

async function doReinstate(l: RelayLicense) {
  try { await mailFleetService.reinstateRelay(l.operator_did); await loadAll() }
  catch (e: any) { error.value = e?.response?.data?.detail || e?.message }
}

onMounted(loadAll)
</script>

<style scoped>
/* --cyan/--cyan-rgb/--mono are NOT global. AdminEmail.vue declares the same three
   locally and maps them onto the real theme tokens; copying the usage without the
   definition made every rgba(var(--cyan-rgb), …) invalid — buttons lost their border
   and background entirely — while rules with hardcoded rgba still painted. That
   asymmetry is what gave it away.

   THE ACCENT IS NOT A STATUS COLOUR. --nc-primary is cyan under theme-neural and
   BLOOD RED (#DC2626) under theme-sovereign. Painting the OK verdict with the accent
   made OK and LOCKOUT both red under sovereign — the one distinction this whole view
   exists to draw, collapsed, in a theme I never rendered. Status now rides the
   semantic tokens (--nc-success/-warning/-danger), which the theme deliberately
   preserves; only chrome rides the accent. Surfaces/borders/text use --nc-* too
   rather than rgba(255,255,255,…) guesses at what the background happens to be. */
.mf {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --mf-ok: var(--nc-success, #00ff88);
  --mf-ok-rgb: 0, 255, 136;
  --mf-warn: var(--nc-warning, #ff9500);
  --mf-warn-rgb: 255, 149, 0;
  --mf-bad: var(--nc-danger, #ff3366);
  --mf-bad-rgb: 255, 51, 102;
  position: relative; min-height: 100vh; padding: 0 1.25rem 4rem;
}
.mf-ambient { position: absolute; inset: 0; overflow: hidden; pointer-events: none; z-index: 0; }
.mf-grid {
  position: absolute; inset: 0; opacity: .18;
  background-image: linear-gradient(rgba(var(--cyan-rgb), .10) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(var(--cyan-rgb), .10) 1px, transparent 1px);
  background-size: 48px 48px;
}
.mf-glow { position: absolute; top: -12%; left: 30%; width: 44rem; height: 44rem; border-radius: 50%;
  background: radial-gradient(circle, rgba(var(--cyan-rgb), .12), transparent 70%); filter: blur(60px); }
.mf > *:not(.mf-ambient) { position: relative; z-index: 1; }

.mf-hero { padding: 2.5rem 0 1.25rem; }
.mf-chip { display: inline-flex; align-items: center; gap: .5rem; font-family: var(--mono);
  font-size: .7rem; letter-spacing: .14em; color: var(--cyan); border: 1px solid rgba(var(--cyan-rgb), .35);
  padding: .3rem .7rem; border-radius: 999px; }
.mf-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); }
.mf-h1 { font-size: clamp(1.8rem, 4vw, 2.6rem); margin: .8rem 0 .4rem; font-weight: 700; }
.mf-accent { color: var(--cyan); }
.mf-lead { max-width: 62ch; color: var(--nc-text-secondary, #9aa0a6); line-height: 1.6; }

.mf-banner { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  border-radius: 12px; padding: .85rem 1.1rem; margin-bottom: 1rem; border: 1px solid; flex-wrap: wrap; }
.mf-banner--ok   { border-color: rgba(var(--mf-ok-rgb), .45);   background: rgba(var(--mf-ok-rgb), .08);   color: var(--mf-ok); }
.mf-banner--warn { border-color: rgba(var(--mf-warn-rgb), .5);  background: rgba(var(--mf-warn-rgb), .09); color: var(--mf-warn); }
.mf-banner--bad  { border-color: rgba(var(--mf-bad-rgb), .55);  background: rgba(var(--mf-bad-rgb), .10);  color: var(--mf-bad); }
.mf-banner--ok .mf-banner-sub, .mf-banner--warn .mf-banner-sub, .mf-banner--bad .mf-banner-sub,
.mf-banner strong { color: var(--nc-text-primary, #e8eaed); }
.mf-banner-main { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.mf-banner-dot { width: 9px; height: 9px; border-radius: 50%; background: currentColor; }
.mf-banner-sub { opacity: .8; font-size: .9rem; }

.mf-row { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
/* max-width is load-bearing, not belt-and-braces. Measured on a 390px viewport the
   two relay cards computed to 719px — wider than their own 350px flex row — so their
   prose wrapped at a width half of which was off-screen. min-width:0 alone does not
   clamp this (the automatic minimum applies to the MAIN axis, and in a column row the
   cross axis is the width). Capping at 100% of the row is what actually holds. */
.mf-card { background: var(--nc-surface, #131825); border: 1px solid var(--nc-border, #2a2f3e);
  border-radius: 14px; padding: 1.1rem 1.2rem; margin-bottom: 1rem; flex: 1 1 20rem;
  min-width: 0; max-width: 100%; box-sizing: border-box; }
.mf-card--grow { flex: 2 1 28rem; }
.mf-card-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.mf-h3 { font-size: 1rem; margin: 0 0 .8rem; letter-spacing: .02em; }
.mf-note h3 { margin-top: 0; }
.mf-err { border-color: rgba(var(--mf-bad-rgb), .5); color: var(--nc-text-primary, #e8eaed); }

.mf-kv > div { display: flex; justify-content: space-between; gap: 1rem; padding: .32rem 0;
  border-bottom: 1px dashed var(--nc-border-subtle, #232833); font-size: .9rem; }
.mf-kv span { color: var(--nc-text-secondary, #9aa0a6); }
.mf-kv b { font-family: var(--mono); word-break: break-all; text-align: right; }

.mf-actions { display: flex; align-items: center; gap: .75rem; margin-top: .9rem; flex-wrap: wrap; }
.mf-inline { font-size: .85rem; font-family: var(--mono); }
.mf-hint { font-size: .78rem; color: var(--nc-text-secondary, #9aa0a6); margin: .8rem 0 0; line-height: 1.5; }
.mf-hint--top { margin: 0 0 .8rem; }
.mf-hint code { font-family: var(--mono); }

.mf-input { width: 100%; background: var(--nc-deep, #0a0d16); border: 1px solid var(--nc-border, #2a2f3e);
  border-radius: 8px; padding: .55rem .7rem; color: inherit; margin-bottom: .55rem; font-family: var(--mono); font-size: .85rem; }
.mf-btn { background: rgba(var(--cyan-rgb), .14); border: 1px solid rgba(var(--cyan-rgb), .45);
  color: var(--cyan); border-radius: 8px; padding: .5rem .9rem; cursor: pointer; font-size: .85rem; }
.mf-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), .24); }
.mf-btn:disabled { opacity: .45; cursor: not-allowed; }
.mf-btn--ghost { background: transparent; border-color: var(--nc-border-strong, #343a4d); color: var(--nc-text-primary, #e8eaed); }
.mf-btn--send { width: 100%; }
.mf-btn--danger { background: rgba(var(--mf-bad-rgb), .14); border-color: rgba(var(--mf-bad-rgb), .5); color: var(--mf-bad); }
.mf-btn--sm { padding: .3rem .6rem; font-size: .78rem; }

.mf-filters { display: flex; gap: .4rem; flex-wrap: wrap; }
.mf-pill { background: transparent; border: 1px solid var(--nc-border, #2a2f3e); color: var(--nc-text-secondary, #9aa0a6);
  border-radius: 999px; padding: .25rem .7rem; font-size: .76rem; cursor: pointer; }
.mf-pill--on { border-color: rgba(var(--cyan-rgb), .6); color: var(--cyan); }
.mf-pill-n { opacity: .75; margin-left: .35rem; }

.mf-tablewrap { overflow-x: auto; margin-top: .8rem; max-width: 100%; }
.mf-tablewrap--short { max-height: 22rem; overflow-y: auto; }
.mf-table { width: 100%; border-collapse: collapse; font-size: .86rem; }
.mf-table th { text-align: left; font-weight: 600; opacity: .6; font-size: .74rem;
  letter-spacing: .08em; text-transform: uppercase; padding: .4rem .6rem; color: var(--nc-text-muted, #5f6368); border-bottom: 1px solid var(--nc-border, #2a2f3e); }
.mf-table td { padding: .5rem .6rem; border-bottom: 1px solid var(--nc-border-subtle, #232833); vertical-align: top; }
.mf-tr--bad { background: rgba(var(--mf-bad-rgb), .08); }
.mf-tr--warn { background: rgba(var(--mf-warn-rgb), .07); }
.mf-tr--dim { opacity: .55; }
.mf-empty { color: var(--nc-text-muted, #5f6368); text-align: center; padding: 1.2rem; }
.mf-detail { color: var(--nc-text-secondary, #9aa0a6); max-width: 34ch; }
.mf-sub { font-size: .72rem; color: var(--nc-text-muted, #5f6368); font-family: var(--mono); word-break: break-all; }
.mf-link { margin-left: .35rem; color: var(--cyan); text-decoration: none; }

.mf-tag { font-family: var(--mono); font-size: .74rem; padding: .12rem .45rem; border-radius: 5px;
  border: 1px solid var(--nc-border, #2a2f3e); color: var(--nc-text-secondary, #9aa0a6); }
.mf-tag--direct { color: var(--cyan); border-color: rgba(var(--cyan-rgb), .4); }
.mf-tag--relay { color: var(--nc-info, #7aa2ff); border-color: rgba(122,162,255,.4); }
.mf-tag--none { color: var(--mf-bad); border-color: rgba(var(--mf-bad-rgb), .45); }

.mf-verdict { font-family: var(--mono); font-size: .74rem; font-weight: 700; padding: .12rem .45rem; border-radius: 5px; }
.mf-verdict--ok { color: var(--mf-ok); background: rgba(var(--mf-ok-rgb), .14); }
.mf-verdict--lockout { color: var(--mf-bad); background: rgba(var(--mf-bad-rgb), .18); }
.mf-verdict--ungated { color: var(--mf-warn); background: rgba(var(--mf-warn-rgb), .16); }
.mf-verdict--unreachable, .mf-verdict--unknown, .mf-verdict--inactive {
  color: var(--nc-text-muted, #5f6368); background: var(--nc-elevated, #181f2e); }

.mf-24h { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: .6rem; font-size: .8rem; }
/* A caller id can be a full spiffe:// URI — one unbreakable token that blew past the
   card edge on a phone until this. min-width:0 lets the flex item actually shrink. */
.mf-24h-item { display: flex; gap: .45rem; align-items: center; font-family: var(--mono);
  min-width: 0; max-width: 100%; flex-wrap: wrap; }
.mf-24h-item b { word-break: break-all; }
.mf-ok { color: var(--mf-ok); }
.mf-bad { color: var(--mf-bad); }
.mf-muted { color: var(--nc-text-muted, #5f6368); }

@media (max-width: 760px) { .mf-row { flex-direction: column; } }
</style>
