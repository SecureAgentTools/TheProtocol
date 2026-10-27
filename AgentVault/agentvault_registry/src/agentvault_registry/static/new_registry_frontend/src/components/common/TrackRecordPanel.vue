<!--
  TrackRecordPanel — §AGENTDISC #188 (2026-08-16)

  Registry-attested guild work history for one agent DID, with per-engagement
  IN-BROWSER verification:
    - digest binding: recompute sha256 over the canonical guild.receipt.v1 subset
      (recursive key sort + tight JSON + \uXXXX escapes — the §VCSIGN cross-language
      contract) and compare against BOTH the listed row digest and the receipt's.
    - Ed25519 attestation: SubtleCrypto verify of the work-credential bundle against
      the registry's published attestation-signer pubkey. Browsers without Ed25519
      report "digest verified, signature unsupported" honestly.

  Traveled rows (work done on OTHER registries) render their ingestion-verified badge
  (the home registry verified the host's signature when the credential landed;
  receive_work_credential stores nothing unverifiable) AND a live Verify-at-origin
  button (#193): the origin's public receipt is fetched cross-origin, its digest
  recomputed and its credential Ed25519-verified against the pubkey the ORIGIN serves.
  Origins that have not rolled the receipt endpoints yet 404 and are reported honestly.
  #195 adds the hire-loop CTA row (Engage / Hire via Guild / Draft contract) — each CTA
  opens an EXISTING surface, never a second copy.

  Modes: default = full panel. `auto-hide` renders NOTHING while the agent has zero
  history (honest absence for embedding in AgentDetailModal).
-->
<template>
  <div v-if="!autoHide || loading || hasHistory || showCtas" class="trp" data-tour="track-record-panel">
    <div v-if="loading" class="trp-loading">{{ t('trackRecord.loading', 'Loading attested history...') }}</div>

    <template v-else-if="data">
      <div v-if="!hasHistory" class="trp-empty">
        {{ t('trackRecord.empty', 'No verified guild work on this registry yet.') }}
      </div>

      <template v-else>
        <!-- summary chips -->
        <div class="trp-chips">
          <span class="trp-chip trp-chip--jobs" data-testid="trp-jobs">
            {{ data.summary.jobs_verified }} {{ data.summary.jobs_verified === 1 ? t('trackRecord.jobVerified', 'job verified') : t('trackRecord.jobsVerified', 'jobs verified') }}
          </span>
          <span v-if="data.summary.avg_stars !== null" class="trp-chip trp-chip--stars">
            &#9733; {{ data.summary.avg_stars }}
          </span>
          <span v-if="data.summary.on_time.of > 0" class="trp-chip">
            {{ data.summary.on_time.met }}/{{ data.summary.on_time.of }} {{ t('trackRecord.onTime', 'on time') }}
          </span>
          <span v-if="data.summary.cross_registry_jobs > 0" class="trp-chip trp-chip--xreg">
            &#11041; {{ data.summary.cross_registry_jobs }} {{ t('trackRecord.crossRegistry', 'cross-registry') }}
          </span>
          <span v-if="data.summary.disputes.total > 0" class="trp-chip trp-chip--disputes">
            {{ data.summary.disputes.total }} {{ t('trackRecord.disputed', 'disputed') }}
          </span>
          <span v-if="data.summary.repeat_poster_jobs > 0" class="trp-chip">
            {{ data.summary.repeat_poster_jobs }} {{ t('trackRecord.repeatHires', 'repeat hires') }}
          </span>
        </div>

        <div v-if="data.summary.volume.length" class="trp-volume">
          <span class="trp-volume-label">{{ t('trackRecord.volume', 'Verified volume') }}:</span>
          <span v-for="v in data.summary.volume" :key="v.currency" class="trp-volume-item">
            {{ formatAmount(v.total) }} {{ v.currency }}
          </span>
        </div>

        <div class="trp-attested">
          {{ t('trackRecord.attestedBy', 'Attested by') }}
          <span class="trp-mono">{{ data.attested_by.registry || t('trackRecord.thisRegistry', 'this registry') }}</span>
          &middot; {{ t('trackRecord.attestNote', 'numbers come from the registry ledger, never the agent') }}
          &middot; {{ t('trackRecord.earnedLegend', 'avatar ring marks are earned here and cannot be purchased; cosmetic flares are a separate system') }}
        </div>

        <!-- §AGENTDISC #197 — liveness, honestly bounded by what the registry observes -->
        <div v-if="data.liveness" class="trp-liveness" data-testid="trp-liveness">
          <span :class="data.liveness.live_24h ? 'trp-ok' : ''">
            {{ data.liveness.live_24h ? t('trackRecord.live24h', 'active in the last 24h') : t('trackRecord.idle', 'idle') }}
          </span>
          <span v-if="data.liveness.probe" :class="data.liveness.probe === 'healthy' ? 'trp-ok' : 'trp-late'">
            &middot; {{ t('trackRecord.probe', 'endpoint probe') }}: {{ data.liveness.probe }}
          </span>
          <span v-if="data.liveness.last_seen" class="trp-mono">
            &middot; {{ t('trackRecord.lastSeen', 'last seen') }} {{ shortDate(data.liveness.last_seen) }}
          </span>
        </div>

        <!-- engagement rows -->
        <div class="trp-rows">
          <div v-for="row in data.recent" :key="row.order_id" class="trp-row" :data-testid="`trp-row-${row.order_id}`">
            <div class="trp-row-main">
              <span class="trp-row-kind" :class="row.kind === 'traveled' ? 'trp-row-kind--xreg' : ''">
                {{ row.kind === 'traveled' ? '&#11041;' : '&#9670;' }}
              </span>
              <span class="trp-row-title">{{ row.title || row.order_id }}</span>
              <span v-if="row.stars !== null && row.stars !== undefined" class="trp-row-stars">&#9733; {{ row.stars }}</span>
              <span v-else class="trp-row-unrated">{{ t('trackRecord.unrated', 'unrated') }}</span>
              <span v-if="row.bounty" class="trp-row-bounty">{{ formatAmount(row.bounty) }} {{ row.currency }}</span>
            </div>
            <div class="trp-row-sub">
              <span class="trp-mono trp-row-when">{{ shortDate(row.settled_at || row.received_at) }}</span>
              <span v-if="row.kind === 'traveled'" class="trp-row-host" :title="row.host_registry">
                {{ t('trackRecord.earnedOn', 'earned on') }} {{ hostLabel(row.host_registry) }}
              </span>
              <span v-if="row.on_time === true" class="trp-ok">&#10003; {{ t('trackRecord.onTimeOne', 'on time') }}</span>
              <span v-else-if="row.on_time === false" class="trp-late">{{ t('trackRecord.late', 'late') }}</span>
              <span v-if="row.contract_id" class="trp-mono trp-row-contract" :title="t('trackRecord.contractHint', 'Spine mirror contract in the Contracts view')">
                {{ row.contract_id.slice(0, 14) }}&hellip;
              </span>
            </div>
            <div class="trp-row-verify">
              <template v-if="row.kind === 'local'">
                <button
                  class="trp-verify-btn"
                  :data-testid="`trp-verify-${row.order_id}`"
                  :disabled="verifyState[row.order_id]?.status === 'checking'"
                  @click.stop="verifyRow(row)"
                >
                  {{ verifyLabel(row) }}
                </button>
                <span v-if="verifyState[row.order_id]?.note" class="trp-verify-note"
                      :class="verifyClass(row)">{{ verifyState[row.order_id]?.note }}</span>
              </template>
              <template v-else>
                <span class="trp-ingested" :title="t('trackRecord.ingestedHint', 'The host signature was verified when this credential landed here; nothing unverifiable is stored')">
                  &#10003; {{ t('trackRecord.ingestionVerified', 'signature verified at ingestion') }}
                </span>
                <button
                  class="trp-verify-btn"
                  :data-testid="`trp-origin-verify-${row.order_id}`"
                  :disabled="verifyState[row.order_id]?.status === 'checking'"
                  @click.stop="verifyTraveledRow(row)"
                >{{ verifyState[row.order_id]?.status === 'checking' ? t('trackRecord.checking', 'verifying...') : t('trackRecord.verifyAtOriginBtn', 'Verify at origin') }}</button>
                <span v-if="verifyState[row.order_id]?.note" class="trp-verify-note"
                      :class="verifyClass(row)">{{ verifyState[row.order_id]?.note }}</span>
                <a class="trp-origin-link"
                   :href="safeExternalUrl(originReceiptUrl(row))" target="_blank" rel="noopener noreferrer">
                  {{ t('trackRecord.verifyAtOrigin', 'origin receipt') }} &#8599;
                </a>
              </template>
            </div>
          </div>
        </div>

      </template>
    </template>


    <!-- §HIRECOHERE (2026-08-28) — the hire loop lives OUTSIDE the history branch now.
         It used to sit inside `v-else` of `v-if="!hasHistory"`, so the CTA row rendered
         only for an agent with verified guild work — 24 of 14,260 cards on frame-c.
         Hiring does not depend on having been hired before, and the §DISCREFINE lesson
         is exactly this: a door behind an auto-hiding panel is a blank promise. -->
      <!-- §AGENTDISC #195 — the hire loop: one identity, three rails
           §HIRECOHERE (2026-08-28) — and only the rails this card actually supports.
           "Draft contract" used to render for every agent and push /contracts?create=1,
           a form with no provider field at all: it dropped the agent you clicked on and
           never touched the engage rail built for exactly this. Now one preview call
           decides, and a door that is shut SAYS why instead of disappearing. -->
      <div v-if="showCtas" class="trp-ctas" data-testid="trp-ctas">
        <button v-if="showEngage" class="trp-cta trp-cta--engage" @click.stop="emit('engage')">
          {{ t('trackRecord.ctaEngage', 'Open full card') }}
        </button>
        <button class="trp-cta trp-cta--guild" data-testid="trp-cta-guild" @click.stop="hireViaGuild">
          {{ t('trackRecord.ctaGuild', 'Hire via Guild') }}
        </button>
        <button v-if="doors?.contract.available" class="trp-cta trp-cta--contract"
                data-testid="trp-cta-contract" @click.stop="openOffer">
          {{ t('trackRecord.ctaContract', 'Offer a contract') }}
        </button>
      </div>
      <p v-if="showCtas && doors && !doors.contract.available && doors.contract.reason"
         class="trp-door-shut" data-testid="trp-contract-shut">{{ doors.contract.reason }}</p>
      <p v-if="showCtas && doors?.per_request.available" class="trp-door-open"
         data-testid="trp-per-request">
        {{ tp('trackRecord.perRequest', 'Takes per-request calls at {rate} {cur} — open the full card to call and pay.',
              { rate: doors.per_request.price?.base_rate || '?', cur: doors.per_request.price?.currency || '' }) }}
      </p>

      <!-- The offer itself: the drafted terms from the card, then one confirm. The rail
           (`POST /contracts/v2/engage/{did}`) has existed since §AGENTDISC and had no
           caller anywhere in the app. -->
      <div v-if="offerOpen" class="trp-offer" data-testid="trp-offer">
        <p class="trp-offer-title">{{ offerDraft?.title }}</p>
        <p class="trp-offer-line">
          {{ offerDraft?.total_amount }} {{ offerDraft?.currency }} ·
          {{ offerDraft?.contract_type }}
        </p>
        <p v-if="offerErr" class="trp-offer-err" data-testid="trp-offer-err">{{ offerErr }}</p>
        <p v-else-if="offerDone" class="trp-offer-ok" data-testid="trp-offer-ok">
          {{ t('trackRecord.offerSent', 'Offer sent. It is theirs to accept; nothing is escrowed until they do.') }}
        </p>
        <div class="trp-offer-actions">
          <button class="trp-cta" @click.stop="offerOpen = false">
            {{ offerDone ? t('trackRecord.offerClose', 'Close') : t('trackRecord.offerCancel', 'Cancel') }}
          </button>
          <button v-if="!offerDone" class="trp-cta trp-cta--contract" data-testid="trp-offer-send"
                  :disabled="offerBusy" @click.stop="sendOffer">
            {{ offerBusy ? t('trackRecord.offerSending', 'Sending…') : t('trackRecord.offerSend', 'Send offer') }}
          </button>
        </div>
      </div>

    <div v-else-if="error" class="trp-empty">{{ error }}</div>
  </div>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { contractsV2Api } from '@/services/api/contractsV2'
import { failedForWantOfAnAnswer } from '@/services/api/peerDirect'
import { useEngageDoors } from '@/composables/useEngageDoors'
import {
  fetchTrackRecord, fetchReceipt, sha256DigestOf, verifyCredentialEd25519,
  type TrackRecordResponse, type TrackRecordRow,
} from '@/services/api/trackRecord'

const props = withDefaults(defineProps<{
  did: string
  autoHide?: boolean
  maxRows?: number
  /** §AGENTDISC #195 — the hire loop: render the CTA row (drawer + modal) */
  showCtas?: boolean
  /** Engage CTA only where the full card is NOT already open (the drawer) */
  showEngage?: boolean
  agentName?: string
}>(), { autoHide: false, maxRows: 10, showCtas: false, showEngage: false, agentName: '' })

/** `state` fires after every load so embedding parents (AgentDetailModal) can hide
 *  their own section chrome when the agent has no history — no orphan labels — and
 *  derive the #190 earned marks (compact shape) without a second fetch. */
const emit = defineEmits<{
  (e: 'state', payload: { hasHistory: boolean; compact: import('@/services/api/trackRecord').TrackRecordCompact | null }): void
  (e: 'engage'): void
}>()

const { t, tp } = useI18n()

const loading = ref(false)
const error = ref('')
const data = ref<TrackRecordResponse | null>(null)
const verifyState = reactive<Record<string, { status: string; note: string }>>({})

const hasHistory = computed(() => (data.value?.summary?.jobs_verified || 0) > 0)

function formatAmount(v: string | null): string {
  if (!v) return ''
  const n = Number(v)
  if (!isFinite(n)) return v
  return n % 1 === 0 ? String(n) : n.toFixed(2)
}

function shortDate(iso?: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toISOString().slice(0, 10) } catch { return iso }
}

function hostLabel(url?: string): string {
  if (!url) return ''
  try { return new URL(url).hostname } catch { return url }
}

function originReceiptUrl(row: TrackRecordRow): string {
  const host = (row.host_registry || '').replace(/\/$/, '')
  return `${host}/api/v1/agents/${encodeURIComponent(props.did)}/track-record/receipts/${encodeURIComponent(row.order_id)}`
}

function verifyLabel(row: TrackRecordRow): string {
  const s = verifyState[row.order_id]?.status
  if (s === 'checking') return t('trackRecord.checking', 'verifying...')
  if (s === 'valid') return '✓ ' + t('trackRecord.verified', 'verified')
  if (s === 'partial') return '✓ ' + t('trackRecord.digestVerified', 'digest verified')
  if (s === 'invalid') return t('trackRecord.failed', 'FAILED')
  return t('trackRecord.verifyReceipt', 'Verify receipt')
}

function verifyClass(row: TrackRecordRow): string {
  const s = verifyState[row.order_id]?.status
  if (s === 'valid') return 'trp-ok'
  if (s === 'partial') return 'trp-partial'
  if (s === 'invalid') return 'trp-late'
  return ''
}

/** The receipts-drawer heart: two independent in-browser proofs per engagement. */
async function verifyRow(row: TrackRecordRow) {
  const id = row.order_id
  verifyState[id] = { status: 'checking', note: '' }
  try {
    const rec = await fetchReceipt(props.did, id)
    if (rec.kind !== 'local' || !rec.subset || !rec.digest) {
      verifyState[id] = { status: 'invalid', note: t('trackRecord.badReceipt', 'receipt incomplete') }
      return
    }
    const recomputed = await sha256DigestOf(rec.subset)
    if (recomputed !== rec.digest || (row.receipt_digest && recomputed !== row.receipt_digest)) {
      verifyState[id] = {
        status: 'invalid',
        note: t('trackRecord.digestMismatch', 'digest mismatch: the receipt does not bind to the listing'),
      }
      return
    }
    if (!rec.credential) {
      verifyState[id] = {
        status: 'partial',
        note: rec.credential_note || t('trackRecord.noCredential', 'no signable credential on this registry'),
      }
      return
    }
    const verdict = await verifyCredentialEd25519(rec.credential, rec.credential_pubkey?.pubkey_b64 || '')
    if (verdict === 'valid') {
      verifyState[id] = {
        status: 'valid',
        note: t('trackRecord.fullyVerified', 'digest bound + Ed25519 signature valid'),
      }
    } else if (verdict === 'unsupported') {
      verifyState[id] = {
        status: 'partial',
        note: t('trackRecord.ed25519Unsupported', 'digest bound; this browser lacks WebCrypto Ed25519 for the signature check'),
      }
    } else {
      verifyState[id] = { status: 'invalid', note: t('trackRecord.sigInvalid', 'signature INVALID') }
    }
  } catch (e: any) {
    // §FESUITE (V0577): could not verify is not invalid (doctrine, PART 1). Only the registry's own refusal of this
    // receipt (a 4xx) stays a failure; a receipt read that got no answer, or a server error, or a check that could not
    // run here, leaves the receipt unchecked: a neutral note, and "Verify receipt" offered again (it read FAILED)
    const refused = !!e?.response && e.response.status < 500
    verifyState[id] = refused
      ? { status: 'invalid', note: t('trackRecord.verifyError', 'verification error') }
      : {
          status: 'unchecked',
          note: failedForWantOfAnAnswer(e)
            ? t('common.readFailed.text', 'This could not be read just now.')
            : t('trackRecord.verifyError', 'verification error'),
        }
  }
}

const router = useRouter()

/** §AGENTDISC #195 — Hire via Guild: opens the EXISTING guild post form prefilled. */
function hireViaGuild() {
  router.push({ path: '/guild', query: {
    post: '1',
    title: `Hire: ${props.agentName || props.did}`.slice(0, 180),
    spec: `Scope of work for ${props.agentName || 'this agent'} (${props.did}). Acceptance criteria: `,
  } })
}

/** §HIRECOHERE — the doors come from the shared composable so this panel and the agent
 *  modal cannot disagree about what is open. */
const didRef = computed(() => props.did)
const ctasOn = computed(() => !!props.showCtas)
const { doors, draft: offerDraft } = useEngageDoors(didRef, ctasOn)
const offerOpen = ref(false)
const offerBusy = ref(false)
const offerDone = ref(false)
const offerErr = ref('')

function openOffer() {
  offerErr.value = ''; offerDone.value = false; offerOpen.value = true
}

/** Mints the offer from the card's OWN engagement terms through the rail built for it.
 *  The previous handler pushed `/contracts?create=1` — a form that has no provider field,
 *  so the agent was silently dropped and the offer had to be retyped from memory. */
async function sendOffer() {
  if (offerBusy.value) return
  offerBusy.value = true; offerErr.value = ''
  try {
    await contractsV2Api.engage(props.did, {})
    offerDone.value = true
  } catch (e: any) {
    offerErr.value = e?.response?.data?.error?.detail || e?.response?.data?.detail
      || t('trackRecord.offerFailed', 'The offer could not be sent.')
  } finally {
    offerBusy.value = false
  }
}

/** §AGENTDISC #193 — verify a TRAVELED engagement AT ITS ORIGIN registry: fetch the
 *  origin's public receipt cross-origin (CORS is open by design), recompute the
 *  digest, and Ed25519-verify the origin's credential against the pubkey the origin
 *  itself serves. Origins that have not rolled the receipt endpoints yet answer 404
 *  and are reported honestly. */
async function verifyTraveledRow(row: TrackRecordRow) {
  const id = row.order_id
  verifyState[id] = { status: 'checking', note: '' }
  try {
    const resp = await fetch(originReceiptUrl(row))
    if (!resp.ok) {
      verifyState[id] = {
        status: 'partial',
        note: resp.status === 404
          ? t('trackRecord.originNotUpgraded', 'origin receipt endpoint not live yet (arrives with its next roll); ingestion verification stands')
          : t('trackRecord.originUnreachable', 'origin unreachable; ingestion verification stands'),
      }
      return
    }
    const rec = await resp.json()
    if (!rec.subset || !rec.digest) {
      verifyState[id] = { status: 'partial', note: t('trackRecord.originIncomplete', 'origin receipt incomplete; ingestion verification stands') }
      return
    }
    const recomputed = await sha256DigestOf(rec.subset)
    if (recomputed !== rec.digest) {
      verifyState[id] = { status: 'invalid', note: t('trackRecord.originDigestMismatch', 'ORIGIN DIGEST MISMATCH') }
      return
    }
    if (rec.credential && rec.credential_pubkey?.pubkey_b64) {
      const verdict = await verifyCredentialEd25519(rec.credential, rec.credential_pubkey.pubkey_b64)
      verifyState[id] = verdict === 'valid'
        ? { status: 'valid', note: t('trackRecord.originVerified', 'verified at origin: digest bound + Ed25519 valid') }
        : verdict === 'unsupported'
          ? { status: 'partial', note: t('trackRecord.originDigestOnly', 'origin digest bound; browser lacks Ed25519') }
          : { status: 'invalid', note: t('trackRecord.originSigInvalid', 'origin signature INVALID') }
    } else {
      verifyState[id] = { status: 'partial', note: t('trackRecord.originDigestBound', 'origin digest bound (no credential served)') }
    }
  } catch {
    verifyState[id] = { status: 'partial', note: t('trackRecord.originUnreachable', 'origin unreachable; ingestion verification stands') }
  }
}

async function load() {
  if (!props.did) return
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchTrackRecord(props.did, props.maxRows)
  } catch (e: any) {
    data.value = null
    error.value = e?.response?.status === 404
      ? t('trackRecord.unknownAgent', 'No attested history for this agent.')
      : t('trackRecord.loadError', 'Could not load the attested history.')
  } finally {
    loading.value = false
    const s = data.value?.summary
    emit('state', {
      hasHistory: hasHistory.value,
      compact: s ? {
        jobs: s.jobs_verified, stars: s.avg_stars, five_star: s.five_star,
        on_time_met: s.on_time.met, on_time_of: s.on_time.of,
        traveled: s.traveled_jobs, cross_registry: s.cross_registry_jobs,
        disputes: s.disputes.total, open_disputes: s.disputes.open ?? 0,
        last_verified_at: s.last_verified_at,
      } : null,
    })
  }
}

onMounted(load)
watch(() => props.did, load)
</script>

<style scoped>
.trp { display: flex; flex-direction: column; gap: 10px; }
.trp-loading, .trp-empty { font-size: 0.8rem; color: var(--nc-text-muted, #94a3b8); padding: 6px 0; }

.trp-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.trp-chip {
  font-size: 0.72rem; padding: 2px 8px; border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.25); color: var(--nc-text-muted, #94a3b8);
  background: rgba(148, 163, 184, 0.07); white-space: nowrap;
}
.trp-chip--jobs { border-color: rgba(34, 211, 238, 0.4); color: #22d3ee; background: rgba(34, 211, 238, 0.08); }
.trp-chip--stars { border-color: rgba(245, 158, 11, 0.4); color: #f59e0b; background: rgba(245, 158, 11, 0.08); }
.trp-chip--xreg { border-color: rgba(168, 85, 247, 0.4); color: #c084fc; background: rgba(168, 85, 247, 0.08); }
.trp-chip--disputes { border-color: rgba(244, 63, 94, 0.4); color: #fb7185; background: rgba(244, 63, 94, 0.08); }

.trp-volume { font-size: 0.74rem; color: var(--nc-text-muted, #94a3b8); display: flex; gap: 8px; flex-wrap: wrap; }
.trp-volume-item { color: #f59e0b; }
.trp-attested { font-size: 0.68rem; color: var(--nc-text-muted, #64748b); opacity: 0.9; }
.trp-liveness { font-size: 0.72rem; color: var(--nc-text-muted, #94a3b8); display: flex; gap: 4px; flex-wrap: wrap; }
.trp-mono { font-family: ui-monospace, monospace; }

.trp-rows { display: flex; flex-direction: column; gap: 8px; }
.trp-row {
  border: 1px solid rgba(148, 163, 184, 0.15); border-radius: 8px;
  padding: 8px 10px; background: rgba(15, 23, 42, 0.35);
}
.trp-row-main { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.trp-row-kind { color: #22d3ee; }
.trp-row-kind--xreg { color: #c084fc; }
.trp-row-title { font-size: 0.8rem; font-weight: 600; }
.trp-row-stars { color: #f59e0b; font-size: 0.75rem; }
.trp-row-unrated { color: var(--nc-text-muted, #64748b); font-size: 0.7rem; font-style: italic; }
.trp-row-bounty { margin-left: auto; font-size: 0.75rem; color: #f59e0b; }
.trp-row-sub { display: flex; gap: 10px; align-items: baseline; font-size: 0.7rem; color: var(--nc-text-muted, #94a3b8); margin-top: 2px; flex-wrap: wrap; }
.trp-row-contract { opacity: 0.8; }
.trp-row-verify { margin-top: 6px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.trp-verify-btn {
  font-size: 0.7rem; padding: 2px 10px; border-radius: 6px; cursor: pointer;
  border: 1px solid rgba(34, 211, 238, 0.4); color: #22d3ee; background: rgba(34, 211, 238, 0.06);
}
.trp-verify-btn:hover { background: rgba(34, 211, 238, 0.15); }
.trp-verify-btn:disabled { opacity: 0.6; cursor: wait; }
.trp-verify-note { font-size: 0.68rem; }
.trp-ok { color: #4ade80; }
.trp-partial { color: #f59e0b; }
.trp-late { color: #fb7185; }
.trp-ingested { font-size: 0.7rem; color: #4ade80; }
.trp-origin-link { font-size: 0.68rem; color: #22d3ee; text-decoration: none; }
.trp-origin-link:hover { text-decoration: underline; }
.trp-ctas { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 4px; }
.trp-cta {
  font-size: 0.74rem; padding: 5px 14px; border-radius: 8px; cursor: pointer;
  border: 1px solid rgba(148, 163, 184, 0.3); color: #e2e8f0; background: rgba(148, 163, 184, 0.08);
}
.trp-cta--guild { border-color: rgba(245, 158, 11, 0.45); color: #f59e0b; background: rgba(245, 158, 11, 0.08); }
.trp-cta--guild:hover { background: rgba(245, 158, 11, 0.18); }
.trp-cta--contract { border-color: rgba(34, 211, 238, 0.45); color: #22d3ee; background: rgba(34, 211, 238, 0.08); }
.trp-cta--contract:hover { background: rgba(34, 211, 238, 0.18); }
.trp-cta--engage:hover { background: rgba(148, 163, 184, 0.18); }
/* §HIRECOHERE — a shut door explains itself, an open one points at itself, and the
   offer block is a confirm, not a form. Quiet by construction: these sit under a CTA row
   inside a panel whose subject is the track record, not the hire. */
.trp-door-shut,
.trp-door-open {
  margin: 6px 0 0; font-size: 9px; line-height: 1.45; max-width: 62ch;
}
.trp-door-shut { color: rgba(var(--nc-primary-rgb), 0.45); }
.trp-door-open { color: rgba(var(--nc-primary-rgb), 0.62); }
.trp-offer {
  margin-top: 10px; padding: 10px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25); border-radius: 6px;
  background: rgba(var(--nc-primary-rgb), 0.04);
}
.trp-offer-title { margin: 0 0 3px; font-size: 11px; font-weight: 600; color: var(--nc-primary); }
.trp-offer-line { margin: 0; font-size: 10px; color: rgba(var(--nc-primary-rgb), 0.7); }
.trp-offer-err { margin: 6px 0 0; font-size: 9px; color: var(--nc-warning); }
.trp-offer-ok { margin: 6px 0 0; font-size: 9px; color: rgba(var(--nc-primary-rgb), 0.8); }
.trp-offer-actions { display: flex; gap: 6px; margin-top: 8px; }
</style>
