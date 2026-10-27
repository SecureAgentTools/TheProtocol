<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// ─────────────────────────────────────────────────────────────────────────────
// §TICKERFUND (O-E) — FUNDAMENTALS on the ticker.
//
// What a holder actually prices on, all RECORDS from existing rails:
//   • the FIRM's verifiable track record (H1.1 public read, incl. the client
//     half — work commissioned and paid for),
//   • dividend history (the public records-only read),
//   • the org's consolidated treasury — MEMBER-gated by the existing rail; a
//     403 renders as the honest "members only" line, never as a zero.
// No member free text anywhere; anonymous view safe by construction.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, watch, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { apiClient } from '@/services/api/client'
import { organizationService } from '@/services/api/organizationService'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const props = defineProps<{
  listingRef: string
  organizationId: string | null
  currency: string
}>()

const track = ref<any | null>(null)
const divs = ref<any[]>([])
const treasury = ref<{ balance: string } | null>(null)
const treasuryMembersOnly = ref(false)
const loading = ref(true)
// §FESUITE (2026-10-05): a failed read said what the server never did. A failed distributions read said "No distributions
// declared yet."; a failed membership read, or a treasury read that got no answer (anything but 401/403), said the treasury
// is "visible to organization members", to a member too; a failed track-record read dropped the firm's section without a
// word. Each says its read failed now, with Try again, and an answer for a listing no longer shown is dropped.
const divsFailed = ref(false)
const treasuryFailed = ref(false)
const trackFailed = ref(false)
let seq = 0
/* §FESUITE — the treasury rail answers members only, and the panel already said so for a 403; but the global API
   handler had toasted "Access Denied" first, on every listing a non-member opened. Ask the rail only for an org the
   developer belongs to (the list is read once per developer and page life; the rail stays the authority). */
const authStore = useAuthStore()
const memberships = new Map<string, Promise<Set<string> | null>>()
function myOrgIds(): Promise<Set<string> | null> {
  const who = String((authStore.user as any)?.id ?? (authStore.user as any)?.developer_id ?? '')
  if (!who) return Promise.resolve(new Set())
  if (!memberships.has(who)) {
    memberships.set(who, organizationService.listOrganizations()
      .then((l) => new Set((l || []).map((o: any) => String(o.id))))
      // a failed read is unknown, not "a member of nothing": null, and not kept (the next load reads again)
      .catch(() => { memberships.delete(who); return null }))
  }
  return memberships.get(who)!
}

async function load() {
  const my = ++seq
  loading.value = true
  track.value = null; divs.value = []; treasury.value = null; treasuryMembersOnly.value = false
  divsFailed.value = false; treasuryFailed.value = false; trackFailed.value = false
  try {
    const [tr, dv] = await Promise.allSettled([
      props.organizationId
        ? apiClient.get(`/organizations/${props.organizationId}/track-record`)
        : Promise.reject(new Error('no org')),
      apiClient.get(`/agora/listings/${encodeURIComponent(props.listingRef)}/distributions`),
    ])
    if (my !== seq) return
    if (tr.status === 'fulfilled') track.value = tr.value.data
    else if (props.organizationId) trackFailed.value = true
    if (dv.status === 'fulfilled') divs.value = dv.value.data?.dividends || []
    else divsFailed.value = true
    if (props.organizationId) {
      const mine = await myOrgIds()
      if (my !== seq) return
      if (mine === null) treasuryFailed.value = true
      else if (!mine.has(String(props.organizationId))) treasuryMembersOnly.value = true
      else {
        try {
          const r = await apiClient.get(`/agora/organizations/${props.organizationId}/treasury`)
          if (my !== seq) return
          const bal = r.data?.totals?.balance
          if (bal != null) treasury.value = { balance: String(bal) }
        } catch (e: any) {
          if (my !== seq) return
          // 401/403 = not a member: an honest boundary, not an error; anything else is a read that got no answer
          const st = e?.response?.status
          if (st === 401 || st === 403) treasuryMembersOnly.value = true
          else treasuryFailed.value = true
        }
      }
    }
  } finally { if (my === seq) loading.value = false }
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric', year: 'numeric' }) }
  catch { return iso }
}

watch(() => props.listingRef, load)
onMounted(load)
</script>

<template>
  <div class="ag-card fp-root" data-testid="fundamentals-panel">
    <div class="ag-card-head"><Icon name="mdi:chart-candlestick" /> FUNDAMENTALS</div>
    <div v-if="loading" class="fp-state">{{ t('fundamentals.loading', 'Loading records…') }}</div>
    <template v-else>
      <!-- the firm behind the ticker: registry-attested work, honest zeros -->
      <div v-if="track" class="fp-sec" data-testid="fp-track">
        <div class="fp-sec-title">{{ t('fundamentals.firm', 'The firm') }} · {{ track.name }}</div>
        <div class="fp-stats">
          <span class="fp-stat"><strong>{{ track.verified_jobs }}</strong> {{ t('fundamentals.jobs', 'jobs delivered') }}</span>
          <span class="fp-stat"><strong>{{ track.commissioned?.orders ?? 0 }}</strong> {{ t('fundamentals.commissioned', 'commissioned') }}</span>
          <span class="fp-stat" v-if="track.stars_n > 0"><strong>{{ track.stars_avg }}</strong>★ ({{ track.stars_n }})</span>
          <span class="fp-stat fp-stat--zero" v-else>{{ t('fundamentals.noStars', 'no ratings yet') }}</span>
        </div>
        <div class="fp-line" v-if="track.last_settled_at">
          {{ t('fundamentals.lastWork', 'Last settled work:') }} {{ fmtDate(track.last_settled_at) }}
        </div>
      </div>
      <div v-else-if="trackFailed" class="fp-sec" data-testid="fp-track-failed">
        <div class="fp-sec-title">{{ t('fundamentals.firm', 'The firm') }}</div>
        <ReadFailedNotice dense :retry="load" />
      </div>

      <!-- treasury: the member-gated rail answers, or the boundary is said -->
      <div class="fp-sec" data-testid="fp-treasury">
        <div class="fp-sec-title">{{ t('fundamentals.treasury', 'Treasury') }}</div>
        <div v-if="treasury" class="fp-line fp-line--money">{{ treasury.balance }} {{ currency }}</div>
        <div v-else-if="treasuryMembersOnly" class="fp-line fp-line--muted" data-testid="fp-treasury-gated">
          {{ t('fundamentals.membersOnly', 'Consolidated treasury is visible to organization members.') }}
        </div>
        <ReadFailedNotice v-else-if="treasuryFailed" dense :retry="load" />
        <div v-else-if="!organizationId" class="fp-line fp-line--muted">{{ t('fundamentals.noOrg', 'No organization behind this listing.') }}</div>
        <div v-else class="fp-line fp-line--muted">—</div>
      </div>

      <!-- dividend history: records only -->
      <div class="fp-sec" data-testid="fp-dividends" role="region" tabindex="0" :aria-label="t('fundamentals.dividends', 'Distribution history')">
        <div class="fp-sec-title">{{ t('fundamentals.dividends', 'Distribution history') }}</div>
        <table v-if="divs.length" class="fp-tbl">
          <thead><tr>
            <th>{{ t('fundamentals.epoch', 'Epoch') }}</th>
            <th>{{ t('fundamentals.perShare', 'Per point') }}</th>
            <th>{{ t('fundamentals.total', 'Total') }}</th>
            <th>{{ t('fundamentals.status', 'Status') }}</th>
            <th>{{ t('fundamentals.declared', 'Declared') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="d in divs" :key="d.epoch" :data-testid="'fp-div-' + d.epoch">
              <td>{{ d.epoch }}</td>
              <td>{{ d.per_share }}</td>
              <td>{{ d.total_amount }} {{ currency }}</td>
              <td><span class="fp-chip" :class="'fp-chip--' + d.status">{{ d.status }}</span></td>
              <td>{{ fmtDate(d.declared_at) }}</td>
            </tr>
          </tbody>
        </table>
        <ReadFailedNotice v-else-if="divsFailed" dense :retry="load" />
        <div v-else class="fp-line fp-line--muted" data-testid="fp-divs-none">
          {{ t('fundamentals.noDividends', 'No distributions declared yet.') }}
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.fp-root { margin-top: 12px; }
.fp-state { font-size: .78rem; opacity: .5; padding: 8px 0; }
/* a section never widens the desk: its table scrolls inside it (the distribution history's five columns are wider
   than a phone's card, fes-20261013T165305Z-356c) */
.fp-sec { padding: 10px 0 4px; border-top: 1px solid rgba(255,255,255,0.04); min-width: 0; overflow-x: auto; }
.fp-sec:first-of-type { border-top: none; }
.fp-sec-title {
  font-family: 'IBM Plex Mono', monospace; font-size: .6rem; font-weight: 700;
  letter-spacing: .12em; text-transform: uppercase; opacity: .45; margin-bottom: 6px;
}
.fp-stats { display: flex; gap: 14px; flex-wrap: wrap; }
.fp-stat { font-size: .74rem; opacity: .75; }
.fp-stat strong { font-family: 'IBM Plex Mono', monospace; color: rgba(var(--nc-primary-rgb), .9); }
.fp-stat--zero { opacity: .4; }
.fp-line { font-size: .74rem; opacity: .7; margin-top: 4px; }
.fp-line--money { font-family: 'IBM Plex Mono', monospace; font-size: .9rem; opacity: .9; }
.fp-line--muted { opacity: .45; }
.fp-tbl { width: 100%; border-collapse: collapse; font-size: .72rem; }
.fp-tbl th { text-align: left; font-weight: 600; opacity: .4; padding: 3px 8px 3px 0; font-size: .62rem; text-transform: uppercase; letter-spacing: .06em; }
.fp-tbl td { padding: 3px 8px 3px 0; font-family: 'IBM Plex Mono', monospace; opacity: .8; }
.fp-chip { font-size: .6rem; padding: 1px 6px; border-radius: 999px; background: rgba(148,163,184,.12); }
.fp-chip--paid { background: rgba(52,211,153,.12); color: rgba(52,211,153,.85); }
.fp-chip--declared, .fp-chip--funding { background: rgba(251,191,36,.12); color: rgba(251,191,36,.85); }
</style>
