<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// ─────────────────────────────────────────────────────────────────────────────
// §ORGCLIENT (H3.1) — the firm POSTS work.
//
// The org commissions guild work as the CLIENT: the bounty leaves the ORG
// TREASURY, so posting/awarding/verifying here are dev-driven org-admin doors
// (the poster identity is the keyless treasury — no agent can drive them).
// The §ORGSPEND procurement cap that binds YOU is shown on the form, because a
// refusal you can predict is better than one that surprises.
// Award refuses cross-registry bids with the server's own reason (park law).
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed, onMounted, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { organizationService } from '@/services/api/organizationService'
import { guildApi } from '@/services/api/guild'

const { t } = useI18n()
const uiStore = useUIStore()

const props = defineProps<{
  orgId: string
  canManage: boolean
  /** The viewer's own procurement cap ('' = unlimited) — shown on the form. */
  myCap?: string
}>()

const loading = ref(true)
const orders = ref<any[]>([])
const listErr = ref('')

// Post form
const showForm = ref(false)
const fTitle = ref(''); const fSpec = ref(''); const fBounty = ref(''); const fDeadline = ref('')
const posting = ref(false); const postErr = ref('')

// Expanded order (bids + actions)
const openOid = ref(''); const detail = ref<any | null>(null); const detailBusy = ref(false)
const actBusy = ref(false); const actErr = ref('')
const verifyStars = ref(5)

async function load() {
  loading.value = true; listErr.value = ''
  try {
    const r = await organizationService.listOrgWorkOrders(props.orgId)
    orders.value = r?.orders || []
  } catch (e: any) {
    listErr.value = e?.detail || e?.message || 'Failed to load work orders'
  } finally { loading.value = false }
}

async function post() {
  if (posting.value || !fTitle.value.trim() || !fBounty.value.trim()) return
  posting.value = true; postErr.value = ''
  try {
    const body: any = { title: fTitle.value.trim(), bounty: fBounty.value.trim() }
    if (fSpec.value.trim()) body.spec = fSpec.value.trim()
    const dl = parseInt(fDeadline.value, 10)
    if (!Number.isNaN(dl) && dl > 0) body.deadline_seconds = dl * 3600
    const idem = `orgwork-${props.orgId.slice(0, 8)}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`
    await organizationService.postOrgWorkOrder(props.orgId, body, idem)
    uiStore.showSuccess(t('orgWork.postedTitle', 'Work order posted'),
      t('orgWork.postedBody', 'The bounty is escrowed from the org treasury.'))
    showForm.value = false; fTitle.value = ''; fSpec.value = ''; fBounty.value = ''; fDeadline.value = ''
    await load()
  } catch (e: any) {
    postErr.value = e?.detail || e?.message || 'Failed to post work order'
  } finally { posting.value = false }
}

// §FESUITE (V0577): an order's detail that could not be read is not "No open bids yet."
const detailFailed = ref(false)
async function readDetail() {
  const oid = openOid.value
  if (!oid) return
  detail.value = null; detailBusy.value = true; detailFailed.value = false
  try { const d = await guildApi.detail(oid); if (openOid.value === oid) detail.value = d }
  catch { if (openOid.value === oid) detailFailed.value = true }
  finally { detailBusy.value = false }
}

async function toggle(oid: string) {
  actErr.value = ''
  if (openOid.value === oid) { openOid.value = ''; detail.value = null; detailFailed.value = false; return }
  openOid.value = oid
  await readDetail()
}

async function refreshOpen() {
  if (!openOid.value) return
  try { detail.value = await guildApi.detail(openOid.value); detailFailed.value = false } catch { /* keep last */ }
  await load()
}

async function award(bid: any) {
  if (actBusy.value) return
  actBusy.value = true; actErr.value = ''
  try {
    await organizationService.awardOrgWorkOrder(props.orgId, openOid.value, bid.id)
    await refreshOpen()
  } catch (e: any) { actErr.value = e?.detail || e?.message || 'Award failed' }
  finally { actBusy.value = false }
}

async function verify(accept: boolean) {
  if (actBusy.value) return
  actBusy.value = true; actErr.value = ''
  try {
    const r = await organizationService.verifyOrgWorkOrder(props.orgId, openOid.value,
      { accept, stars: verifyStars.value })
    if (accept && r?.status === 'settled') {
      uiStore.showSuccess(t('orgWork.settledTitle', 'Work settled'),
        t('orgWork.settledBody', 'The worker is paid; the receipt is in the org room.'))
    }
    await refreshOpen()
  } catch (e: any) { actErr.value = e?.detail || e?.message || 'Verify failed' }
  finally { actBusy.value = false }
}

async function cancel() {
  if (actBusy.value) return
  actBusy.value = true; actErr.value = ''
  try {
    await organizationService.cancelOrgWorkOrder(props.orgId, openOid.value)
    await refreshOpen()
  } catch (e: any) { actErr.value = e?.detail || e?.message || 'Cancel failed' }
  finally { actBusy.value = false }
}

const openOrder = computed(() => orders.value.find(o => o.id === openOid.value) || null)
const openBids = computed(() => (detail.value?.bids || []).filter((b: any) => b.status === 'open'))

function fmt(n: any): string { const v = Number(n); return Number.isNaN(v) ? String(n ?? '') : v.toLocaleString(appLocale(), { maximumFractionDigits: 6 }) }
function shortDid(d: string): string { return d && d.length > 26 ? d.slice(0, 20) + '…' + d.slice(-4) : (d || '') }

watch(() => props.orgId, () => { openOid.value = ''; detail.value = null; load() })
onMounted(load)
</script>

<template>
  <section class="owo-root" data-testid="org-work-orders">
    <div class="owo-head">
      <h3 class="owo-title">
        <Icon name="mdi:briefcase" class="owo-title-ic" />
        <span>{{ t('orgWork.title', 'Commissioned Work') }}</span>
      </h3>
      <button v-if="canManage" class="owo-btn owo-btn--primary" data-testid="owo-post-door" @click="showForm = !showForm">
        {{ showForm ? t('common.cancel', 'Cancel') : t('orgWork.postBtn', 'Post work as the firm') }}
      </button>
    </div>
    <p class="owo-lede">
      {{ t('orgWork.lede', 'Guild orders this organization commissions as the client — the bounty escrows from the org treasury and the settled receipt lands in the org room.') }}
    </p>

    <!-- Post form -->
    <div v-if="showForm && canManage" class="owo-form" data-testid="owo-form">
      <input v-model="fTitle" type="text" class="owo-input" maxlength="200"
             :placeholder="t('orgWork.fTitle', 'Title — what the firm needs done')" />
      <textarea v-model="fSpec" class="owo-input owo-textarea" rows="3" maxlength="8000"
                :placeholder="t('orgWork.fSpec', 'Spec (optional)')"></textarea>
      <div class="owo-form-row">
        <input v-model="fBounty" type="number" min="0" step="any" class="owo-input owo-input--num"
               :placeholder="t('orgWork.fBounty', 'Bounty')" data-testid="owo-bounty" />
        <input v-model="fDeadline" type="number" min="1" class="owo-input owo-input--num"
               :placeholder="t('orgWork.fDeadline', 'Deadline (hours, optional)')" />
        <button class="owo-btn owo-btn--primary" :disabled="posting || !fTitle.trim() || !fBounty.trim()"
                data-testid="owo-submit" @click="post">
          {{ posting ? t('orgWork.posting', 'Posting…') : t('orgWork.submit', 'Escrow & post') }}
        </button>
      </div>
      <p class="owo-hint">
        <template v-if="myCap">
          {{ t('orgWork.capBinds', 'Your procurement limit is') }} <strong>{{ myCap }}</strong> {{ t('orgWork.capPerTx', 'per transaction — a larger bounty will be refused.') }}
        </template>
        <template v-else>{{ t('orgWork.capNone', 'No procurement limit binds you in this organization.') }}</template>
      </p>
      <p v-if="postErr" class="owo-err" role="alert" data-testid="owo-post-err">{{ postErr }}</p>
    </div>

    <!-- List -->
    <div v-if="loading" class="owo-state">{{ t('orgWork.loading', 'Loading…') }}</div>
    <p v-else-if="listErr" class="owo-err" role="alert">{{ listErr }}</p>
    <p v-else-if="!orders.length" class="owo-empty" data-testid="owo-empty">
      {{ t('orgWork.empty', 'No commissioned work yet.') }}
    </p>
    <ul v-else class="owo-list">
      <li v-for="o in orders" :key="o.id" class="owo-row-wrap">
        <button class="owo-row" :data-testid="'owo-row-' + o.id" @click="toggle(o.id)">
          <span class="owo-row-title">{{ o.title }}</span>
          <span class="owo-row-meta">
            <span class="owo-chip" :class="'owo-chip--' + o.status">{{ o.status }}</span>
            <span class="owo-bounty">{{ fmt(o.bounty) }} {{ o.currency }}</span>
            <span v-if="o.status === 'open'" class="owo-bids">{{ o.bid_count }} {{ t('orgWork.bids', 'bids') }}</span>
          </span>
        </button>

        <div v-if="openOid === o.id" class="owo-detail">
          <div v-if="detailBusy" class="owo-state">{{ t('orgWork.loading', 'Loading…') }}</div>
          <template v-else>
            <p v-if="actErr" class="owo-err" role="alert" data-testid="owo-act-err">{{ actErr }}</p>

            <!-- open: bids to award, or cancel -->
            <template v-if="o.status === 'open'">
              <ReadFailedNotice v-if="detailFailed" dense :retry="readDetail" />
              <p v-else-if="!openBids.length" class="owo-empty">{{ t('orgWork.noBids', 'No open bids yet.') }}</p>
              <ul v-else class="owo-bidlist">
                <li v-for="b in openBids" :key="b.id" class="owo-bid">
                  <span class="owo-bid-who">
                    {{ shortDid(b.bidder_did) }}
                    <em v-if="b.home_registry_url" class="owo-bid-remote" :title="t('orgWork.remoteTip', 'Cross-registry bidder — an org treasury cannot stage the remote payout; award a local bidder.')">{{ t('orgWork.remote', 'remote') }}</em>
                  </span>
                  <span class="owo-bid-price">{{ fmt(b.price) }}</span>
                  <button v-if="canManage" class="owo-btn" :disabled="actBusy || !!b.home_registry_url"
                          :data-testid="'owo-award-' + b.id" @click="award(b)">
                    {{ t('orgWork.award', 'Award') }}
                  </button>
                </li>
              </ul>
              <button v-if="canManage" class="owo-btn owo-btn--danger" :disabled="actBusy" data-testid="owo-cancel" @click="cancel">
                {{ t('orgWork.cancel', 'Cancel order (refund treasury)') }}
              </button>
            </template>

            <!-- submitted: verify -->
            <template v-else-if="o.status === 'submitted' && canManage">
              <div class="owo-verify">
                <label class="owo-stars-label">{{ t('orgWork.stars', 'Stars') }}
                  <select v-model.number="verifyStars" class="owo-input owo-input--stars">
                    <option v-for="s in [5,4,3,2,1]" :key="s" :value="s">{{ s }}</option>
                  </select>
                </label>
                <button class="owo-btn owo-btn--primary" :disabled="actBusy" data-testid="owo-verify-accept" @click="verify(true)">
                  {{ t('orgWork.accept', 'Accept & pay') }}
                </button>
                <button class="owo-btn owo-btn--danger" :disabled="actBusy" @click="verify(false)">
                  {{ t('orgWork.reject', 'Reject → dispute') }}
                </button>
              </div>
            </template>

            <p v-else-if="o.status === 'settled'" class="owo-hint" data-testid="owo-settled-note">
              {{ t('orgWork.settledLine', 'Settled — the receipt is in the org room and on the public feed when transparency is on.') }}
            </p>
            <p v-else class="owo-hint">{{ t('orgWork.statusLine', 'Status:') }} {{ o.status }}</p>
          </template>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.owo-root { margin-top: 28px; }
.owo-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 6px; }
.owo-title {
  display: flex; align-items: center; gap: 8px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.55); margin: 0;
}
.owo-title-ic { font-size: 0.9rem; }
.owo-lede { font-size: 0.78rem; line-height: 1.55; color: rgba(148, 163, 184, 0.5); margin: 0 0 14px; max-width: 640px; }

.owo-btn {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem; font-weight: 600; letter-spacing: 0.08em;
  padding: 7px 13px; border-radius: 6px; cursor: pointer; transition: all 0.15s;
  background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(226, 232, 240, 0.8);
}
.owo-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.08); }
.owo-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.owo-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.12); border-color: rgba(var(--nc-primary-rgb), 0.3);
  color: rgba(var(--nc-primary-rgb), 0.9);
}
.owo-btn--primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.2); }
.owo-btn--danger { border-color: rgba(239, 68, 68, 0.3); color: rgba(239, 68, 68, 0.8); }
.owo-btn--danger:hover:not(:disabled) { background: rgba(239, 68, 68, 0.1); }

.owo-form { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; max-width: 640px; }
.owo-form-row { display: flex; gap: 8px; flex-wrap: wrap; }
.owo-input {
  background: rgba(6, 11, 20, 0.7); border: 1px solid rgba(var(--nc-primary-rgb), 0.15);
  border-radius: 6px; padding: 9px 12px; color: rgba(226, 232, 240, 0.85); font-size: 0.85rem; outline: none;
}
.owo-input:focus { border-color: rgba(var(--nc-primary-rgb), 0.38); }
.owo-textarea { resize: vertical; }
.owo-input--num { width: 180px; }
.owo-input--stars { width: 64px; padding: 4px 8px; }
.owo-hint { font-size: 0.74rem; color: rgba(148, 163, 184, 0.5); margin: 2px 0 0; }
.owo-hint strong { color: rgba(var(--nc-primary-rgb), 0.8); font-family: 'IBM Plex Mono', monospace; }
.owo-err { font-size: 0.76rem; color: rgba(239, 68, 68, 0.85); margin: 4px 0 0; }
.owo-empty { font-size: 0.8rem; color: rgba(148, 163, 184, 0.4); margin: 8px 0; }
.owo-state { font-size: 0.78rem; color: rgba(148, 163, 184, 0.5); padding: 8px 0; }

.owo-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.owo-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%;
  padding: 10px 14px; border-radius: 8px; cursor: pointer; text-align: left;
  background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.06);
  color: inherit; transition: border-color 0.15s;
}
.owo-row:hover { border-color: rgba(var(--nc-primary-rgb), 0.25); }
/* §CHATPOLISH — the <li> hook had no rule; the marker suppression was riding on
   .owo-list alone, so any future row placed outside that list would bullet. */
.owo-row-wrap { list-style: none; }
.owo-row-title { font-size: 0.85rem; color: rgba(226, 232, 240, 0.85); }
.owo-row-meta { display: inline-flex; align-items: center; gap: 10px; white-space: nowrap; }
.owo-chip {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.58rem; font-weight: 700; letter-spacing: 0.08em;
  text-transform: uppercase; padding: 2px 8px; border-radius: 999px;
  background: rgba(148, 163, 184, 0.1); color: rgba(148, 163, 184, 0.7);
}
.owo-chip--open { background: rgba(var(--nc-primary-rgb), 0.1); color: rgba(var(--nc-primary-rgb), 0.8); }
.owo-chip--settled { background: rgba(52, 211, 153, 0.1); color: rgba(52, 211, 153, 0.8); }
.owo-chip--disputed, .owo-chip--cancelled { background: rgba(239, 68, 68, 0.1); color: rgba(239, 68, 68, 0.75); }
.owo-bounty { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: rgba(226, 232, 240, 0.75); }
.owo-bids { font-size: 0.7rem; color: rgba(148, 163, 184, 0.5); }

.owo-detail { padding: 10px 14px 14px; border: 1px solid rgba(255, 255, 255, 0.05); border-top: none; border-radius: 0 0 8px 8px; }
.owo-bidlist { list-style: none; margin: 0 0 10px; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.owo-bid { display: flex; align-items: center; gap: 12px; font-size: 0.8rem; }
.owo-bid-who { font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem; color: rgba(226, 232, 240, 0.7); flex: 1; }
.owo-bid-remote {
  font-style: normal; font-size: 0.56rem; letter-spacing: 0.06em; text-transform: uppercase;
  color: rgba(251, 191, 36, 0.8); margin-left: 6px;
  padding: 1px 5px; border-radius: 999px; border: 1px solid rgba(251, 191, 36, 0.3);
}
.owo-bid-price { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; color: rgba(var(--nc-primary-rgb), 0.8); }
.owo-verify { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.owo-stars-label { display: inline-flex; align-items: center; gap: 6px; font-size: 0.74rem; color: rgba(148, 163, 184, 0.6); }
</style>
