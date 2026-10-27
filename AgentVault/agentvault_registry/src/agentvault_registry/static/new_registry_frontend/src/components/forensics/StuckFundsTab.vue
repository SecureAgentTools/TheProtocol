<template>
  <div class="lfs">
    <div class="lfs-toolbar">
      <div class="lfs-toolbar-info">
        <span v-if="store.lastRefreshedAt" class="lfs-muted">checked {{ fromNow(store.lastRefreshedAt) }}</span>
        <span v-else class="lfs-muted">not yet loaded</span>
      </div>
      <span class="lfs-spacer"></span>
      <button class="lfs-btn" @click="reload" :disabled="store.loadingStuck">
        <Icon name="refresh-cw" class="lfs-btn-ico" /> {{ store.loadingStuck ? 'Scanning…' : 'Re-scan' }}
      </button>
    </div>

    <!-- ── Findings triage board ─────────────────────────────────────────── -->
    <div class="lfs-section-head">
      <h2 class="lfs-h2">Findings</h2>
      <p class="lfs-sub">Live account-level signals across AGORA, supply conservation and reserves.
        Δ=0 alone does not mean “nothing stuck” — these catch misallocation the supply audit is blind to.</p>
    </div>

    <!-- §FESUITE (the failing-reads census): an all-clear is an answer the scan's sources give. A source it could not read
         is named, and while one the findings read (the AGORA invariant, the auditor) is among them nothing is all clear -->
    <ReadFailedNotice
      v-if="!store.loadingStuck && store.stuckUnread.length"
      dense
      :text="`Not every source could be read (${store.stuckUnread.join(', ')}): no signal is shown for what could not be read.`"
      :retry="reload"
    />
    <div v-if="!store.loadingStuck && !findings.length && store.lastRefreshedAt && !findingSourcesUnread" class="lfs-allclear">
      <Icon name="check" class="lfs-allclear-ico" /> No stuck-funds signals detected.
    </div>

    <div class="lfs-findings">
      <div
        v-for="f in findings"
        :key="f.id"
        class="lfs-finding"
        :class="`lfs-finding--${f.severity}`"
      >
        <div class="lfs-finding-bar"></div>
        <div class="lfs-finding-body">
          <div class="lfs-finding-top">
            <span class="lfs-sev" :class="`lfs-sev--${f.severity}`">{{ f.severity }}</span>
            <span class="lfs-finding-title">{{ f.title }}</span>
            <span v-if="f.heal" class="lfs-heal" :class="f.heal === 'auto' ? 'lfs-heal--auto' : 'lfs-heal--human'">
              {{ f.heal === 'auto' ? 'auto-heals' : 'needs human' }}
            </span>
          </div>
          <div class="lfs-finding-detail">{{ f.detail }}</div>
          <div v-if="f.account || f.amount" class="lfs-finding-meta">
            <span v-if="f.amount" class="lfs-amount">{{ f.amount }}</span>
            <span v-if="f.account" class="lfs-account"><Icon name="mdi:bank" class="lfs-meta-ico" />{{ f.account }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── AGORA invariants (this registry's frame) ──────────────────────── -->
    <div class="lfs-section-head lfs-mt">
      <h2 class="lfs-h2">AGORA market <span class="lfs-frame-tag">this registry's own market</span></h2>
      <p class="lfs-sub">Org market escrow + gateway conservation (I-X1…I-X5).</p>
    </div>

    <div v-if="inv" class="lfs-grid">
      <div class="lfs-card" :class="ixClass(inv['I-X3_escrow']?.ok)">
        <div class="lfs-card-k">I-X3 · Escrow conservation</div>
        <div class="lfs-card-v">{{ inv['I-X3_escrow']?.ok ? 'BALANCED' : 'BREACH' }}</div>
        <div class="lfs-card-sub">held {{ fmt(inv['I-X3_escrow']?.actual) }} · Δ {{ fmt(inv['I-X3_escrow']?.delta) }}</div>
      </div>
      <div class="lfs-card" :class="ixClass(inv['I-X5_gateway_solvency']?.ok)">
        <div class="lfs-card-k">I-X5 · Gateway solvency</div>
        <div class="lfs-card-v">{{ inv['I-X5_gateway_solvency']?.ok ? 'SOLVENT' : 'UNDER-FUNDED' }}</div>
        <div class="lfs-card-sub">
          holds {{ fmt(inv['I-X5_gateway_solvency']?.gateway_balance) }} · owes {{ fmt(inv['I-X5_gateway_solvency']?.pending_credits) }}
        </div>
      </div>
      <div class="lfs-card" :class="ixClass(inv['I-X4_settlement_liveness']?.ok)">
        <div class="lfs-card-k">I-X4 · Settlement liveness</div>
        <div class="lfs-card-v">{{ inv['I-X4_settlement_liveness']?.stuck_over_slo ?? 0 }} stuck</div>
        <div class="lfs-card-sub">over SLO · {{ inv.funding_orders_in_transition ?? 0 }} funding in transit</div>
      </div>
      <div class="lfs-card" :class="ixClass(sharesInvOk)">
        <div class="lfs-card-k">I-X1/I-X2 · Points &amp; locks</div>
        <div class="lfs-card-v">{{ inv.listings?.length ?? 0 }} listings</div>
        <div class="lfs-card-sub">{{ sharesInvOk ? 'conserved + lock-honest' : 'invariant breach' }}</div>
      </div>
      <div v-if="ov" class="lfs-card lfs-card--neutral">
        <div class="lfs-card-k">Escrow held</div>
        <div class="lfs-card-v">{{ fmt(ov.escrow_balance) }}</div>
        <div class="lfs-card-sub">{{ ov.currency }} · settle lag {{ Math.round(ov.settlement?.oldest_lag_seconds || 0) }}s</div>
      </div>
      <div v-if="ov" class="lfs-card lfs-card--neutral">
        <div class="lfs-card-k">Open orders</div>
        <div class="lfs-card-v">{{ (ov.orders_by_status?.open || 0) + (ov.orders_by_status?.partial || 0) }}</div>
        <div class="lfs-card-sub">{{ ov.orders_by_status?.funding || 0 }} funding · {{ ov.trades_24h || 0 }} trades/24h</div>
      </div>
    </div>
    <div v-else-if="!store.loadingStuck" class="lfs-muted lfs-pad">AGORA invariant unavailable on this frame.</div>

    <!-- Gateway Float Keeper (parallel-session auto-healer for the I-X5 class) -->
    <div v-if="gk" class="lfs-keeper" :class="gk.enabled === false ? 'lfs-keeper--off' : 'lfs-keeper--on'">
      <Icon name="mdi:swap-horizontal" class="lfs-keeper-ico" />
      <div class="lfs-keeper-body">
        <div class="lfs-keeper-head">
          <strong>Gateway Float Keeper</strong>
          <span class="lfs-sev" :class="gk.enabled === false ? 'lfs-sev--warn' : 'lfs-sev--ok'">{{ gk.enabled === false ? 'DISABLED' : 'ACTIVE' }}</span>
        </div>
        <div class="lfs-keeper-stats">
          <span>gateway holds <b>{{ fmt(gk.gateway_balance) }} {{ gk.currency }}</b></span>
          <span>owes <b>{{ fmt(gk.outstanding_obligation) }}</b></span>
          <span>buffer <b>{{ fmt(gk.buffer) }}</b></span>
          <span v-if="gk.credits?.abandoned">abandoned <b :class="num(gk.credits.abandoned.count) ? 'lfs-bad' : 'lfs-good'">{{ gk.credits.abandoned.count }}</b></span>
          <span v-if="gk.credits?.unresolved" data-testid="gk-unresolved">held <b :class="num(gk.credits.unresolved.count) ? 'lfs-bad' : 'lfs-good'">{{ gk.credits.unresolved.count }}</b></span>
          <span v-if="gk.credits?.dust">dust <b>{{ gk.credits.dust.count }}</b></span>
        </div>
        <div class="lfs-keeper-note">MOVE-only treasury→gateway top-up + autonomous recon re-arm; never issues units. Auto-heals the gateway-solvency (I-X5) class.</div>
      </div>
    </div>

    <!-- ── Per-frame supply & conservation (independent Auditor) ──────────── -->
    <div class="lfs-section-head lfs-mt">
      <h2 class="lfs-h2">Supply &amp; conservation <span class="lfs-frame-tag">all frames · independent Auditor</span></h2>
      <p class="lfs-sub">Per-user negatives, listing holder-registers, reserve solvency and transit drift, witnessed independently.</p>
    </div>

    <div class="lfs-grid lfs-grid--frames">
      <div v-for="fr in frames" :key="fr.key" class="lfs-fcard" :class="frameCardClass(fr)">
        <div class="lfs-fcard-head">
          <span class="lfs-fcard-name">{{ fr.composition?.currency || fr.frame || fr.key }}</span>
          <span class="lfs-sev" :class="`lfs-sev--${frameSeverity(fr)}`">{{ frameVerdict(fr) }}</span>
        </div>
        <div class="lfs-fcard-rows">
          <div class="lfs-frow">
            <span>Supply Δ</span>
            <b :class="(fr.atomic_delta ?? fr.delta) ? 'lfs-bad' : 'lfs-good'">{{ fmtNum(fr.atomic_delta ?? fr.delta ?? 0) }}</b>
          </div>
          <div class="lfs-frow">
            <span>Negative users</span>
            <b :class="negUsers(fr) ? 'lfs-bad' : 'lfs-good'">{{ negUsers(fr) }}</b>
          </div>
          <div class="lfs-frow">
            <span>Point violations</span>
            <b :class="shareViolations(fr) ? 'lfs-bad' : 'lfs-good'">{{ shareViolations(fr) }}</b>
          </div>
          <div class="lfs-frow">
            <span>Escrow held</span>
            <b>{{ fmtNum(fr.composition?.buckets?.escrow) }}</b>
          </div>
          <div class="lfs-frow">
            <span>FX reserve</span>
            <b :class="fr.solvency && fr.solvency.status && /solvent|ok/i.test(String(fr.solvency.status)) ? 'lfs-good' : ''">
              {{ fmtNum(fr.composition?.buckets?.fx_reserve) }}
            </b>
          </div>
          <div class="lfs-frow">
            <span>Transit drift</span>
            <b :class="driftClass(fr)">{{ fmtNum(fr.composition?.transit_drift) }}<template v-if="fr.composition?.transit_drift_status"> · {{ fr.composition?.transit_drift_status }}</template></b>
          </div>
        </div>
      </div>
      <div v-if="!frames.length && !store.loadingStuck" class="lfs-muted lfs-pad">Auditor data unavailable.</div>
    </div>

    <!-- ── Registry-rail stuck inventory (this registry's own DB) ─────────── -->
    <div class="lfs-section-head lfs-mt" v-if="store.inventory">
      <h2 class="lfs-h2">Stuck-funds inventory <span class="lfs-frame-tag">this registry · DB rails</span></h2>
      <p class="lfs-sub">Per-rail stuck rows in this registry's own DB (cross-frame sagas · A2A · bridge · fiat), each a bounded
        status query with a timeout seatbelt. TEG-direct locks + cross-frame pairing are the next backend layer.</p>
    </div>
    <div v-if="store.inventory && invRails.length" class="lfs-grid lfs-grid--frames">
      <div v-for="r in invRails" :key="r.rail + r.class" class="lfs-card" :class="invCardClass(r)">
        <div class="lfs-card-k">{{ r.rail }} · {{ r.class }}</div>
        <div class="lfs-card-v">{{ r.count == null ? '—' : r.count }}</div>
        <div class="lfs-card-sub">
          <template v-if="r.sum">{{ fmtNum(r.sum) }} {{ r.currency || '' }} · </template>
          {{ r.heal === 'auto' ? 'auto-heals' : 'needs human' }}
          <span v-if="r.error" class="lfs-warn"> · query: {{ r.error }}</span>
        </div>
      </div>
    </div>
    <div v-else-if="store.inventory" class="lfs-allclear lfs-mt">
      <Icon name="check" class="lfs-allclear-ico" /> All registry-DB rails clear.
    </div>

    <div v-if="store.error" class="lfs-error">{{ store.error }}</div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import { computed, onMounted } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useForensicsStore } from '@/stores/forensics'
import type { AuditorFrame, AuditorShareListing } from '@/services/api/forensics'
import type { FrameId } from '@/services/api/eventStoreAdmin'

defineProps<{ frame: FrameId }>()
dayjs.extend(relativeTime)
const store = useForensicsStore()

type Sev = 'critical' | 'high' | 'warn' | 'ok' | 'info'
interface Finding {
  id: string
  severity: Sev
  title: string
  detail: string
  account?: string
  amount?: string
  heal?: 'auto' | 'human' | null
}

const inv = computed(() => store.exchangeInvariant)
const ov = computed(() => store.exchangeOverview)
const frames = computed(() => store.prodAuditorFrames)
const gk = computed(() => store.gatewayKeeper)
const invRails = computed(() => (store.inventory?.rails || []).filter(r => (r.count || 0) > 0 || r.error))
function invCardClass(r: any): string {
  if (r.error) return 'lfs-card--neutral'
  if ((r.count || 0) > 0) return r.severity === 'high' ? 'lfs-card--bad' : 'lfs-card--neutral'
  return 'lfs-card--good'
}

// ── number / format helpers ────────────────────────────────────────────────
function num(v: any): number {
  if (v == null) return 0
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  return isNaN(n) ? 0 : n
}
function fmt(v: any): string {
  return fmtNum(num(v))
}
function fmtNum(v: any): string {
  const n = num(v)
  if (n === 0) return '0'
  const abs = Math.abs(n)
  const opts: Intl.NumberFormatOptions =
    abs >= 1000 ? { maximumFractionDigits: 0 } : { maximumFractionDigits: 4 }
  return n.toLocaleString(appLocale(), opts)
}
function fromNow(ts?: string | null): string {
  if (!ts) return '—'
  return dayjs(ts).fromNow()
}

// ── AGORA share invariant rollup ────────────────────────────────────────────
const sharesInvOk = computed(() => {
  const ls = inv.value?.listings || []
  return ls.every(l => l['I-X1_share_conservation'] && l['I-X2_lock_honesty'])
})

// ── per-frame helpers ───────────────────────────────────────────────────────
function negUsers(fr: AuditorFrame): number {
  const pu = fr.extra_data?.per_user
  if (!pu) return 0
  return num(pu.negative_liquid_agents ?? pu.neg_liquid) + num(pu.negative_staked_agents ?? pu.neg_staked)
}
function shareList(fr: AuditorFrame): AuditorShareListing[] {
  const s = fr.extra_data?.shares
  if (!s) return []
  return Array.isArray(s) ? s : (Object.values(s) as AuditorShareListing[])
}
function shareViolations(fr: AuditorFrame): number {
  return shareList(fr).filter(
    l => num(l.neg_holders) > 0 || num(l.over_locked) > 0 || num(l.neg_locked) > 0,
  ).length
}
function frameSeverity(fr: AuditorFrame): Sev {
  if ((fr.atomic_status && fr.atomic_status !== 'OK') || (fr.status && fr.status !== 'OK')) return 'critical'
  if (negUsers(fr) > 0 || shareViolations(fr) > 0) return 'high'
  const ds = fr.composition?.transit_drift_status
  if (ds && /strand/i.test(ds)) return 'warn'
  return 'ok'
}
function frameVerdict(fr: AuditorFrame): string {
  const sev = frameSeverity(fr)
  if (sev === 'critical') return 'BREACH'
  if (sev === 'high') return 'NEGATIVES'
  if (sev === 'warn') return 'DRIFT'
  return 'OK'
}
function frameCardClass(fr: AuditorFrame): string {
  return `lfs-fcard--${frameSeverity(fr)}`
}
function driftClass(fr: AuditorFrame): string {
  const ds = fr.composition?.transit_drift_status
  return ds && /strand/i.test(ds) ? 'lfs-warn' : ''
}
function ixClass(ok?: boolean): string {
  return ok === false ? 'lfs-card--bad' : ok === true ? 'lfs-card--good' : 'lfs-card--neutral'
}

// ── findings synthesis ──────────────────────────────────────────────────────
const SEV_WEIGHT: Record<Sev, number> = { critical: 0, high: 1, warn: 2, ok: 3, info: 4 }

const findings = computed<Finding[]>(() => {
  const out: Finding[] = []
  const cur = ov.value?.currency || currentOwnCurrency()

  // AGORA gateway under-funding (the headline live class — S2 / dev-passport no-reach)
  const gw = inv.value?.['I-X5_gateway_solvency']
  if (gw && gw.ok === false) {
    const shortfall = num(gw.pending_credits) - num(gw.gateway_balance)
    out.push({
      id: 'agora-gateway',
      severity: 'high',
      title: 'AGORA gateway under-funded: foreign-buyer credits outpace the float',
      detail: `Pending repatriation credits (${fmtNum(gw.pending_credits)} ${cur}) exceed the gateway balance (${fmtNum(gw.gateway_balance)} ${cur}), owed to foreign passport buyers. The Gateway Float Keeper auto-tops-up treasury→gateway each cycle (MOVE-only, never issues units) and re-arms failed credits, so this normally self-heals within a cycle; if it persists, the keeper is disabled or the treasury is dry.`,
      account: `agora-gateway-${cur.toLowerCase()}`,
      amount: `≈ ${fmtNum(shortfall)} ${cur} short`,
      heal: 'auto',
    })
  }

  // AGORA escrow conservation
  const esc = inv.value?.['I-X3_escrow']
  if (esc && esc.ok === false) {
    out.push({
      id: 'agora-escrow',
      severity: 'high',
      title: 'AGORA escrow conservation breach',
      detail: `Escrow holds ${fmtNum(esc.actual)} ${cur} vs expected ${fmtNum(esc.expected)} ${cur} (Δ ${fmtNum(esc.delta)}). Residue not attributable to a live order = stranded escrow.`,
      account: `teg:system:exchange_escrow`,
      amount: `Δ ${fmtNum(esc.delta)} ${cur}`,
      heal: 'human',
    })
  }

  // AGORA settlement liveness
  const sl = inv.value?.['I-X4_settlement_liveness']
  if (sl && num(sl.stuck_over_slo) > 0) {
    out.push({
      id: 'agora-settle',
      severity: 'warn',
      title: `${sl.stuck_over_slo} AGORA trade(s) stuck over settlement SLO`,
      detail: 'Trades pending settlement past the SLO — escrow holds their notional until the settlement worker drains them.',
      account: 'teg:system:exchange_escrow',
      heal: 'auto',
    })
  }

  // AGORA share invariants
  if (inv.value && !sharesInvOk.value) {
    const bad = (inv.value.listings || []).filter(l => !l['I-X1_share_conservation'] || !l['I-X2_lock_honesty'])
    out.push({
      id: 'agora-shares',
      severity: 'high',
      title: `Point invariant breach on ${bad.length} listing(s)`,
      detail: `I-X1/I-X2 broken on: ${bad.map(b => b.symbol).join(', ')}. Points not conserved or locks dishonest, tradability stuck.`,
      heal: 'human',
    })
  }

  // Per-frame conservation
  for (const fr of frames.value) {
    const label = fr.composition?.currency || fr.frame || fr.key
    if ((fr.atomic_status && fr.atomic_status !== 'OK') || (fr.status && fr.status !== 'OK' && !/strand/i.test(String(fr.status)))) {
      out.push({
        id: `breach-${fr.key}`,
        severity: 'critical',
        title: `Supply invariant BREACH on ${label}`,
        detail: `Auditor Δ = ${fmtNum(fr.atomic_delta ?? fr.delta)} (status ${fr.atomic_status || fr.status}). Conservation is the prime directive — investigate immediately.`,
        amount: `Δ ${fmtNum(fr.atomic_delta ?? fr.delta)}`,
        heal: 'human',
      })
    }
    const nu = negUsers(fr)
    if (nu > 0) {
      const pu = fr.extra_data?.per_user
      out.push({
        id: `neg-${fr.key}`,
        severity: 'high',
        title: `${nu} agent(s) with negative balance on ${label}`,
        detail: `Negative liquid/locked balances (worst liquid ${fmtNum(pu?.worst_liquid)}, worst locked ${fmtNum(pu?.worst_staked)}). A user is underwater even though frame Δ nets to zero.`,
        amount: `${fmtNum(pu?.negative_total)} ${label}`,
        heal: 'human',
      })
    }
    const sv = shareViolations(fr)
    if (sv > 0) {
      out.push({
        id: `shares-${fr.key}`,
        severity: 'high',
        title: `${sv} listing(s) with negative/over-locked points on ${label}`,
        detail: 'Org holder-register breach (qty<0, locked>qty, or locked<0). Holders cannot trade what they are owed.',
        heal: 'human',
      })
    }
    const ds = fr.composition?.transit_drift_status
    if (ds && /strand/i.test(ds)) {
      out.push({
        id: `drift-${fr.key}`,
        severity: 'warn',
        title: `Transit drift flagged STRANDING on ${label}`,
        detail: `transit_net moved ${fmtNum(fr.composition?.transit_drift)} vs the persisted baseline. Usually a stale-baseline artifact (re-baseline via snapshot), not real loss — Δ stays 0. Confirm before acting.`,
        amount: `${fmtNum(fr.composition?.transit_drift)} ${label}`,
        heal: 'auto',
      })
    }
  }

  // Gateway Float Keeper residuals — the classes the keeper does NOT auto-fix.
  const k = gk.value
  if (k) {
    const kcur = k.currency || cur
    const ab = k.credits?.abandoned
    if (ab && num(ab.count) > 0) {
      out.push({
        id: 'gw-abandoned', severity: 'high',
        title: `${ab.count} gateway credit(s) ABANDONED — genuinely undeliverable`,
        detail: 'The keeper re-armed these to the max generation and gave up: repatriation owed to foreign buyers that cannot be delivered (stale/missing home registry, unreachable). This is real stranded value — needs manual resolution.',
        account: k.gateway_did || `agora-gateway-${kcur.toLowerCase()}`,
        amount: `${fmtNum(ab.sum)} ${kcur}`, heal: 'human',
      })
    }
    // §REPATLANE (V0603): a payout whose answer did not prove that nothing moved is never sent again on its own
    const held = k.credits?.unresolved
    if (held && num(held.count) > 0) {
      out.push({
        id: 'gw-unresolved', severity: 'high',
        title: `${held.count} gateway payout(s) HELD: money may have moved`,
        detail: 'Each send came back without proof that nothing moved (an FX route parked or stranded after the gateway paid in, a timeout, a server error), so the lane will not send it again: a second send could pay the trader twice. Read the ledger for each credit\'s key (its tx_ref): release it to pending once nothing moved, or mark it paid when the payout arrived.',
        account: k.gateway_did || `agora-gateway-${kcur.toLowerCase()}`,
        amount: `${fmtNum(held.sum)} ${kcur}`, heal: 'human',
      })
    }
    const dust = k.credits?.dust
    if (dust && num(dust.count) > 0) {
      out.push({
        id: 'gw-dust', severity: 'warn',
        title: `${dust.count} sub-dust gateway credit(s) never repatriated`,
        detail: `Each is below REPAT_DUST (${fmtNum(k.repat_dust)} ${kcur}); the worker + recon skip them. Tiny individually but they accrete. Lower the dust threshold or aggregate to clear.`,
        account: k.gateway_did || `agora-gateway-${kcur.toLowerCase()}`,
        amount: `${fmtNum(dust.sum)} ${kcur}`, heal: 'human',
      })
    }
    if (k.enabled === false) {
      out.push({
        id: 'gw-keeper-off', severity: 'warn',
        title: 'Gateway Float Keeper is DISABLED',
        detail: 'The passport gateway float has no auto-refill; order-funding + repats spend the shared balance with nothing to refill it, so it will drain and repats will strand. Re-enable the keeper (env GATEWAY_KEEPER_ENABLED + DB config).',
        heal: 'human',
      })
    }
  }

  return out.sort((a, b) => SEV_WEIGHT[a.severity] - SEV_WEIGHT[b.severity])
})

function reload() { store.loadStuckOverview(); store.loadInventory() }
/** the findings read the AGORA invariant and the auditor: while either is unread, nothing is all clear */
const findingSourcesUnread = computed(() => store.stuckUnread.some((n) => n === 'the AGORA invariant' || n === 'the auditor'))
onMounted(() => {
  if (!store.exchangeInvariant && !store.loadingStuck) store.loadStuckOverview()
  if (!store.inventory) store.loadInventory()
})
</script>

<style scoped>
.lfs {
  --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366; --green: #00ff88; --amber: #ff9500; --muted: #788593;  /* §FESUITE: 4.75:1 on the darkest card (#6b7785 was 3.9-4.25:1) */
  --border: rgba(var(--cyan-rgb), 0.18); --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed; color: var(--text-bright);
}
.lfs-toolbar { display: flex; align-items: center; margin-bottom: 14px; }
.lfs-toolbar-info { font-size: 11px; }
.lfs-spacer { flex: 1; }
.lfs-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(var(--cyan-rgb), 0.12); color: var(--cyan); border: 1px solid rgba(var(--cyan-rgb), 0.35);
  border-radius: 4px; padding: 6px 14px; font-size: 12px; cursor: pointer; font-weight: 600;
}
.lfs-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.22); }
.lfs-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.lfs-btn-ico { width: 14px; height: 14px; }

.lfs-section-head { margin-bottom: 12px; }
.lfs-mt { margin-top: 26px; }
.lfs-h2 { font-size: 16px; font-weight: 800; margin: 0 0 3px 0; display: flex; align-items: center; gap: 10px; }
.lfs-frame-tag {
  font-size: 9px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); background: rgba(var(--cyan-rgb), 0.06); border: 1px solid var(--border);
  padding: 2px 8px; border-radius: 8px;
}
.lfs-sub { font-size: 12px; color: var(--muted); margin: 0; max-width: 760px; line-height: 1.5; }

.lfs-allclear {
  display: flex; align-items: center; gap: 8px; padding: 16px;
  background: rgba(0,255,136,0.06); border: 1px solid rgba(0,255,136,0.25);
  border-radius: 8px; color: var(--green); font-size: 13px; font-weight: 600;
}
.lfs-allclear-ico { width: 18px; height: 18px; }

.lfs-findings { display: flex; flex-direction: column; gap: 8px; }
.lfs-finding {
  position: relative; display: flex; background: rgba(var(--cyan-rgb), 0.025);
  border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
}
.lfs-finding-bar { width: 4px; flex-shrink: 0; }
.lfs-finding--critical .lfs-finding-bar { background: #ff2d4f; }
.lfs-finding--high .lfs-finding-bar { background: var(--red); }
.lfs-finding--warn .lfs-finding-bar { background: var(--amber); }
.lfs-finding--ok .lfs-finding-bar { background: var(--green); }
.lfs-finding--info .lfs-finding-bar { background: #9ad6ff; }
.lfs-finding--critical { border-color: rgba(255,45,79,0.4); }
.lfs-finding--high { border-color: rgba(255,51,102,0.32); }
.lfs-finding-body { padding: 11px 14px; flex: 1; min-width: 0; }
.lfs-finding-top { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.lfs-finding-title { font-size: 13px; font-weight: 700; color: var(--text-bright); }
.lfs-finding-detail { font-size: 12px; color: var(--muted); margin-top: 5px; line-height: 1.5; }
.lfs-finding-meta { display: flex; gap: 14px; margin-top: 8px; flex-wrap: wrap; align-items: center; }
.lfs-amount { font-family: var(--mono); font-size: 13px; font-weight: 700; color: var(--amber); }
.lfs-account { display: inline-flex; align-items: center; gap: 5px; font-family: var(--mono); font-size: 11px; color: #9ab0c4; }
.lfs-meta-ico { width: 13px; height: 13px; opacity: 0.7; }

.lfs-sev {
  display: inline-block; padding: 2px 9px; border-radius: 8px; font-size: 9.5px;
  font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em;
}
.lfs-sev--critical { background: rgba(255,45,79,0.28); color: #ff5b76; }
.lfs-sev--high { background: rgba(255,51,102,0.2); color: #ff6b8a; }
.lfs-sev--warn { background: rgba(255,149,0,0.2); color: var(--amber); }
.lfs-sev--ok { background: rgba(0,255,136,0.16); color: var(--green); }
.lfs-sev--info { background: rgba(154,214,255,0.16); color: #9ad6ff; }

.lfs-heal { font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 7px; border-radius: 8px; }
.lfs-heal--auto { background: rgba(0,255,136,0.1); color: var(--green); }
.lfs-heal--human { background: rgba(255,149,0,0.12); color: var(--amber); }

.lfs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.lfs-grid--frames { grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
.lfs-card { background: rgba(var(--cyan-rgb), 0.03); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
.lfs-card--good { border-color: rgba(0,255,136,0.3); }
.lfs-card--bad { border-color: rgba(255,51,102,0.4); background: rgba(255,51,102,0.06); }
.lfs-card--neutral { border-color: var(--border); }
.lfs-card-k { font-size: 9.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; font-weight: 700; }
.lfs-card-v { font-size: 20px; font-weight: 800; margin: 4px 0 2px; }
.lfs-card--bad .lfs-card-v { color: #ff6b8a; }
.lfs-card--good .lfs-card-v { color: var(--green); }
.lfs-card-sub { font-size: 11px; color: var(--muted); font-family: var(--mono); }

.lfs-fcard { background: rgba(var(--cyan-rgb), 0.03); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.lfs-fcard--critical { border-color: rgba(255,45,79,0.45); }
.lfs-fcard--high { border-color: rgba(255,51,102,0.35); }
.lfs-fcard--warn { border-color: rgba(255,149,0,0.3); }
.lfs-fcard--ok { border-color: rgba(0,255,136,0.25); }
.lfs-fcard-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.lfs-fcard-name { font-size: 16px; font-weight: 800; letter-spacing: 0.02em; }
.lfs-fcard-rows { display: flex; flex-direction: column; gap: 6px; }
.lfs-frow { display: flex; justify-content: space-between; align-items: baseline; font-size: 12px; }
.lfs-frow span { color: var(--muted); }
.lfs-frow b { font-family: var(--mono); font-weight: 700; color: #d6e2ee; }
.lfs-good { color: var(--green) !important; }
.lfs-bad { color: #ff6b8a !important; }
.lfs-warn { color: var(--amber) !important; }

.lfs-keeper {
  display: flex; gap: 12px; align-items: flex-start; margin-top: 10px; padding: 12px 14px;
  border: 1px solid var(--border); border-radius: 8px; background: rgba(var(--cyan-rgb), 0.03);
}
.lfs-keeper--on { border-color: rgba(0,255,136,0.28); }
.lfs-keeper--off { border-color: rgba(255,149,0,0.35); background: rgba(255,149,0,0.05); }
.lfs-keeper-ico { width: 20px; height: 20px; color: var(--cyan); flex-shrink: 0; margin-top: 2px; }
.lfs-keeper-body { flex: 1; min-width: 0; }
.lfs-keeper-head { display: flex; align-items: center; gap: 10px; }
.lfs-keeper-head strong { font-size: 13px; color: var(--text-bright); }
.lfs-keeper-stats { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 6px; font-size: 12px; color: var(--muted); }
.lfs-keeper-stats b { font-family: var(--mono); color: #d6e2ee; }
.lfs-keeper-note { font-size: 11px; color: var(--muted); margin-top: 6px; line-height: 1.5; }

.lfs-muted { color: var(--muted); font-size: 11px; }
.lfs-pad { padding: 16px; }
.lfs-error {
  margin-top: 14px; padding: 10px 14px; background: rgba(255,51,102,0.08);
  border: 1px solid rgba(255,51,102,0.35); color: var(--red); border-radius: 4px; font-size: 12px;
}
</style>
