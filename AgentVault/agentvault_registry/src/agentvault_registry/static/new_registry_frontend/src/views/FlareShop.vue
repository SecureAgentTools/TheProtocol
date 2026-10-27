<template>
  <div class="fsh-view">
    <!-- ── header ─────────────────────────────────────────────────────── -->
    <div class="fsh-head">
      <div class="fsh-eyebrow">{{ t('flareShopView.eyebrow', 'COSMETICS · PAID IN THIS FRAME\'S OWN CURRENCY') }}</div>
      <h1 class="fsh-title">{{ t('flareShopView.title', 'Flare Shop') }}</h1>
      <p class="fsh-sub">
        {{ t('flareShopView.sub', 'Encirclements and broken-machine overlays, bought with') }}
        <strong class="fsh-ccy">{{ catalog?.currency || localCurrency }}</strong>{{ t('flareShopView.sub2', '. No card, no processor, no euros: your agent pays the registry on the same rails it uses for everything else.') }}
      </p>
    </div>

    <!-- ── lane state banner ──────────────────────────────────────────── -->
    <div v-if="loaded && catalog && !catalog.enabled" class="fsh-banner fsh-banner--off" data-testid="fsh-lane-off">
      <Icon name="mdi:store-off-outline" class="w-5 h-5 shrink-0" />
      <div>
        <div class="fsh-banner-title">{{ t('flareShopView.offTitle', 'Local-currency purchases are not enabled on this registry') }}</div>
        <div class="fsh-banner-sub">
          {{ t('flareShopView.offSub', 'The whole catalog is below so you can see what this registry could offer. An operator turns the lane on with FLARE_LOCAL_PURCHASE_ENABLED.') }}
        </div>
      </div>
    </div>
    <div v-else-if="loaded && catalog" class="fsh-banner fsh-banner--on" data-testid="fsh-lane-on">
      <Icon name="mdi:check-decagram-outline" class="w-5 h-5 shrink-0" />
      <div>
        <div class="fsh-banner-title">{{ t('flareShopView.onTitle', 'This lane is open') }}</div>
        <div class="fsh-banner-sub">
          {{ t('flareShopView.onSub', 'Prices are in') }} {{ catalog?.currency }}. {{ t('flareShopView.onSub2', 'One of your agents pays; the flare lands on your developer profile and on the agent you choose.') }}
        </div>
      </div>
    </div>
    <!-- §FESUITE (V0594): a catalog that was not read is neither "open" nor "not enabled" (the open banner showed for it) -->
    <ReadFailedNotice v-else-if="loaded && catalogFailed" :retry="load" />

    <!-- ── your standing ──────────────────────────────────────────────── -->
    <section v-if="authStore.isAuthenticated" class="fsh-standing" data-testid="fsh-standing">
      <div class="fsh-standing-left">
        <FlareEncirclement
          :tier="currentTier === 'shadow_chancellor' ? 'shadow_chancellor' : null"
          :variant="'sauron'"
          :initials="(authStore.user?.name || authStore.user?.email || '?').slice(0, 2)"
          size="lg"
        />
        <div>
          <div class="fsh-standing-label">{{ t('flareShopView.yourFlare', 'Your flare') }}</div>
          <div class="fsh-standing-value" data-testid="fsh-current-tier">
            <!-- §FESUITE (the failing-reads census, 2026-10-04): "none yet" is an answer the profile gives; with it unread a dash -->
            {{ currentTier ? tierLabel(currentTier) : authStore.user ? t('flareShopView.noneYet', 'none yet') : '—' }}
          </div>
          <div class="fsh-standing-sub">
            <template v-if="currentTier">
              {{ t('flareShopView.unlockedCount', 'Unlocked:') }}
              {{ unlockedCorners.length }} {{ unlockedCorners.length === 1 ? t('flareShopView.cornerBadge', 'corner badge') : t('flareShopView.cornerBadges', 'corner badges') }}<template v-if="hasEncirclements">,
              {{ catalog?.encirclement_variants.length ?? '—' }} {{ t('flareShopView.encirclements', 'encirclements') }},
              {{ catalog?.encirclement_overlays.length ?? '—' }} {{ t('flareShopView.overlays', 'overlays') }}</template>
            </template>
            <template v-else>{{ t('flareShopView.noneSub', 'Buy a tier below to light one up.') }}</template>
          </div>
        </div>
      </div>
      <router-link to="/flare-manager" class="fsh-wear-link" data-testid="fsh-wear-link">
        {{ t('flareShopView.wear', 'Wear what you own') }} <Icon name="mdi:arrow-right" class="w-4 h-4" />
      </router-link>
    </section>

    <!-- ── tiers ──────────────────────────────────────────────────────── -->
    <section class="fsh-tiers" data-testid="fsh-tiers">
      <div
        v-for="tier in catalog?.tiers || []"
        :key="tier.tier"
        class="fsh-tier"
        :class="{
          'fsh-tier--owned': isOwned(tier.tier),
          'fsh-tier--key': tier.unlocks_encirclements,
        }"
        :data-testid="`fsh-tier-${tier.tier}`"
      >
        <div class="fsh-tier-top">
          <span class="fsh-tier-name">{{ tierLabel(tier.tier) }}</span>
          <span v-if="tier.unlocks_encirclements" class="fsh-tier-tag">{{ t('flareShopView.theKey', 'THE KEY') }}</span>
          <span v-else-if="isOwned(tier.tier)" class="fsh-tier-tag fsh-tier-tag--owned">{{ t('flareShopView.owned', 'OWNED') }}</span>
        </div>
        <div class="fsh-tier-price">
          <span class="fsh-tier-amount">{{ prettyAmount(tier.price) }}</span>
          <span class="fsh-tier-ccy">{{ tier.currency }}</span>
        </div>
        <ul class="fsh-tier-perks">
          <li>
            <Icon name="mdi:shield-star" class="w-3.5 h-3.5" />
            {{ tier.unlocks_corner_flares.length }} {{ t('flareShopView.cornerBadgesUnlocked', 'corner badges') }}
          </li>
          <li v-if="tier.unlocks_encirclements" class="fsh-perk-strong">
            <Icon name="mdi:blur-radial" class="w-3.5 h-3.5" />
            {{ tier.encirclement_variant_count }} {{ t('flareShopView.encirclementsPlus', 'encirclements +') }} {{ tier.overlay_count }} {{ t('flareShopView.brokenMachine', 'broken-machine overlays') }}
          </li>
          <li v-else class="fsh-perk-muted">
            <Icon name="mdi:blur-off" class="w-3.5 h-3.5" />
            {{ t('flareShopView.noEncirclements', 'no encirclements at this tier') }}
          </li>
          <li v-if="tier.capped" :class="tier.cap_full ? 'fsh-perk-muted' : ''">
            <Icon name="mdi:counter" class="w-3.5 h-3.5" />
            <template v-if="tier.cap_full">
              {{ t('flareShopView.capFull', 'all') }} {{ tier.cap_total }} {{ t('flareShopView.capFull2', 'taken, so this would grant Architect instead') }}
            </template>
            <template v-else>
              {{ tier.cap_taken }} / {{ tier.cap_total }} {{ t('flareShopView.capTaken', 'taken, forever') }}
            </template>
          </li>
        </ul>
        <button
          class="fsh-buy"
          :disabled="!catalog?.enabled || isOwned(tier.tier) || busy"
          :data-testid="`fsh-buy-${tier.tier}`"
          @click="openBuy(tier)"
        >
          <template v-if="isOwned(tier.tier)">{{ t('flareShopView.alreadyYours', 'Already yours') }}</template>
          <template v-else-if="!catalog?.enabled">{{ t('flareShopView.laneClosed', 'Lane closed here') }}</template>
          <template v-else>{{ t('flareShopView.buy', 'Buy for') }} {{ prettyAmount(tier.price) }} {{ tier.currency }}</template>
        </button>
      </div>
    </section>

    <!-- ── the honest line, and then the proof of it ───────────────────── -->
    <p class="fsh-earned" data-testid="fsh-earned-notice">
      <Icon name="mdi:medal-outline" class="w-4 h-4 shrink-0" />
      <span>{{ catalog?.earned_marks_notice || t('flareShopView.earnedFallback', 'Cosmetic flares only. Track-record marks are earned on this registry\'s ledger and cannot be purchased.') }}</span>
    </p>

    <!-- §MARKGUILLOCHE-2 — the shop is exactly where that sentence has to be
         PROVEN rather than asserted: someone is here to spend money, and they
         should be able to see precisely what their money does not buy. Every
         agent below wears a different purchased encirclement and the earned
         mark still reads through it. -->
    <section class="fsh-marks" data-testid="fsh-marks">
      <EarnedMarkTiers
        :heading="t('flareShopView.marksHeading', 'What money cannot buy: earned marks')"
      />
    </section>

    <!-- ── catalog gallery ────────────────────────────────────────────── -->
    <section class="fsh-gallery" data-testid="fsh-gallery">
      <div class="fsh-gallery-head">
        <h2 class="fsh-gallery-title">{{ t('flareShopView.galleryTitle', 'Encirclements') }}</h2>
        <span class="fsh-gallery-count">{{ catalog?.encirclement_variants.length ?? '—' }}</span>
        <span class="fsh-gallery-note">
          {{ t('flareShopView.galleryNote', 'all of them unlock together with') }} {{ tierLabel(catalog?.encirclement_unlock_tier || 'shadow_chancellor') }}
        </span>
      </div>
      <div class="fsh-grid">
        <button
          v-for="v in catalog?.encirclement_variants || []"
          :key="`enc-${v}`"
          type="button"
          class="fsh-tile fsh-tile--pick"
          :class="{ 'fsh-tile--locked': !hasEncirclements, 'fsh-tile--worn': wornVariant === v }"
          :disabled="!hasEncirclements || pickBusy"
          :aria-pressed="wornVariant === v"
          :title="!hasEncirclements
            ? t('flareShopView.lockedHint', 'Buy an encirclement tier to wear this')
            : t('flareShopView.pickHint', 'Wear this encirclement')"
          :data-testid="`fsh-variant-${v}`"
          @click="pickVariant(v)"
        >
          <FlareEncirclement
            tier="shadow_chancellor"
            :variant="v"
            :initials="(authStore.user?.name || 'TP').slice(0, 2)"
            size="xl"
          />
          <span class="fsh-tile-label">{{ prettyId(v) }}</span>
          <span v-if="wornVariant === v" class="fsh-tile-worn">{{ t('flareShopView.worn', 'WORN') }}</span>
        </button>
      </div>

      <p v-if="pickError" class="fsh-pick-error" data-testid="fsh-pick-error">{{ pickError }}</p>

      <div class="fsh-gallery-head fsh-gallery-head--second">
        <h2 class="fsh-gallery-title">{{ t('flareShopView.overlaysTitle', 'Broken-machine overlays') }}</h2>
        <span class="fsh-gallery-count">{{ catalog?.encirclement_overlays.length ?? '—' }}</span>
        <span class="fsh-gallery-note">{{ t('flareShopView.overlaysNote', 'an independent axis, worn on top of any encirclement') }}</span>
      </div>
      <div class="fsh-grid">
        <button
          v-for="o in catalog?.encirclement_overlays || []"
          :key="`ovl-${o}`"
          type="button"
          class="fsh-tile fsh-tile--pick"
          :class="{ 'fsh-tile--locked': !hasEncirclements, 'fsh-tile--worn': wornOverlay === o }"
          :disabled="!hasEncirclements || pickBusy"
          :aria-pressed="wornOverlay === o"
          :title="!hasEncirclements
            ? t('flareShopView.lockedHint', 'Buy an encirclement tier to wear this')
            : t('flareShopView.pickOverlayHint', 'Wear this overlay — press again to remove it')"
          :data-testid="`fsh-overlay-${o}`"
          @click="pickOverlay(o)"
        >
          <FlareEncirclement
            tier="shadow_chancellor"
            variant="obsidian"
            :overlay="o"
            :initials="(authStore.user?.name || 'TP').slice(0, 2)"
            size="xl"
          />
          <span class="fsh-tile-label">{{ prettyId(o) }}</span>
          <span v-if="wornOverlay === o" class="fsh-tile-worn">{{ t('flareShopView.worn', 'WORN') }}</span>
        </button>
      </div>
    </section>

    <!-- ── receipts ───────────────────────────────────────────────────── -->
    <section v-if="receipts.length || receiptsFailed" class="fsh-receipts" data-testid="fsh-receipts">
      <h2 class="fsh-gallery-title">{{ t('flareShopView.receiptsTitle', 'Your purchases') }}</h2>
      <!-- §FESUITE (V0594): a failed read said nothing at all, as if nothing had been bought; after a buy, an unread
           list is not shown as if it were complete -->
      <ReadFailedNotice v-if="receiptsFailed" dense :retry="loadReceipts" />
      <div v-for="r in (receiptsFailed ? [] : receipts)" :key="r.purchase_id" class="fsh-receipt" :data-testid="`fsh-receipt-${r.status}`">
        <span class="fsh-receipt-tier">{{ tierLabel(r.tier) }}</span>
        <span class="fsh-receipt-amount">{{ prettyAmount(r.price) }} {{ r.currency }}</span>
        <span class="fsh-receipt-status" :class="`fsh-receipt-status--${r.status}`">{{ r.status }}</span>
        <span v-if="r.failure_reason" class="fsh-receipt-reason">{{ r.failure_reason }}</span>
        <span class="fsh-receipt-date">{{ formatDate(r.completed_at || r.created_at) }}</span>
      </div>
    </section>

    <!-- ── the other lane ─────────────────────────────────────────────── -->
    <p class="fsh-otherlane">
      <template v-if="fiatEnabled">
        {{ t('flareShopView.otherLaneOn', 'This registry also runs the euro lane:') }}
        <router-link to="/become-a-backer" class="fsh-link">{{ t('flareShopView.becomeBacker', 'Become a Backer') }}</router-link>.
      </template>
      <template v-else>
        {{ t('flareShopView.otherLaneOff', 'The euro lane (Become a Backer) is not enabled on this registry, which is exactly why this one exists.') }}
      </template>
    </p>

    <!-- ── buy modal ──────────────────────────────────────────────────── -->
    <BaseModal v-model:show="buyOpen" :title="t('flareShopView.confirmTitle', 'Confirm purchase')" size="md">
      <div v-if="selected" class="fsh-modal" data-testid="fsh-buy-modal">
        <p class="fsh-modal-line">
          {{ t('flareShopView.confirmLead', 'You are buying the') }}
          <strong>{{ tierLabel(selected.tier) }}</strong>
          {{ t('flareShopView.confirmLead2', 'flare for') }}
          <strong>{{ prettyAmount(selected.price) }} {{ selected.currency }}</strong>.
        </p>
        <p v-if="selected.unlocks_encirclements" class="fsh-modal-note">
          {{ t('flareShopView.confirmKey', 'This is the tier that unlocks every encirclement variant and overlay.') }}
        </p>
        <p v-if="selected.cap_full" class="fsh-modal-warn">
          {{ t('flareShopView.confirmCapFull', 'All Founder slots are taken, so this grants Architect instead, at the Founder price. Choose Architect directly if that is not what you want.') }}
        </p>

        <label class="fsh-field">
          <span class="fsh-field-label">{{ t('flareShopView.payingAgent', 'Paying agent') }}</span>
          <select v-model="buyerDid" class="fsh-select" data-testid="fsh-buyer-select">
            <option v-for="a in agents" :key="a.did" :value="a.did">
              {{ a.name }} · {{ prettyAmount(a.balance) }} {{ catalog?.currency }}
            </option>
          </select>
          <span class="fsh-field-hint">{{ t('flareShopView.payingHint', 'Developers hold no balance; one of your agents pays.') }}</span>
          <ReadFailedNotice v-if="agentsFailed && !agents.length" dense :retry="loadAgents" />
        </label>

        <label class="fsh-field">
          <span class="fsh-field-label">{{ t('flareShopView.wearingAgent', 'Agent that wears it') }}</span>
          <select v-model="targetDid" class="fsh-select" data-testid="fsh-target-select">
            <option v-for="a in agents" :key="`t-${a.did}`" :value="a.did">{{ a.name }}</option>
          </select>
          <span class="fsh-field-hint">{{ t('flareShopView.wearingHint', 'Movable later from My Flare. Your developer profile keeps the flare permanently either way.') }}</span>
        </label>

        <p v-if="buyError" class="fsh-modal-error" data-testid="fsh-buy-error">{{ buyError }}</p>
        <p v-if="buyOk" class="fsh-modal-ok" data-testid="fsh-buy-ok">{{ buyOk }}</p>
      </div>
      <template #footer>
        <button class="nc-btn nc-btn-ghost" @click="buyOpen = false">{{ t('common.cancel', 'Cancel') }}</button>
        <button class="nc-btn nc-btn-primary" :disabled="busy || !buyerDid" data-testid="fsh-confirm-buy" @click="confirmBuy">
          {{ busy ? t('flareShopView.paying', 'Paying...') : t('flareShopView.confirm', 'Confirm') }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<script setup lang="ts">
import { loadRegistryConfig } from '@/composables/useRegistryConfig'
import { appLocale } from '@/services/appLocale'
/**
 * §FLARESHOP (2026-08-16) — the BUY side of the cosmetic flare system.
 *
 * FlareManager (/flare-manager) is the WEAR side and stays exactly as it is;
 * this view never duplicates its pickers, it links to them. The catalog comes
 * from the server (one source of truth for which variants exist and which tier
 * unlocks them) and the previews reuse the SAME FlareEncirclement renderer the
 * manager and the discovery cards use — imported, never copied.
 *
 * With the lane disabled the view still renders the entire catalog as a
 * gallery: an operator deciding whether to enable it should be able to see what
 * they would be offering, and a visitor should be able to see what the flare
 * system IS. Only the buy buttons go dead.
 */
import { ref, computed, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { apiClient } from '@/services/api/client'
import { useFrames } from '@/composables/useFrames'
import { useI18n } from '@/composables/useI18n'
import { flareShopApi, type FlareShopCatalog, type FlareShopTier, type FlareShopReceipt } from '@/services/api/flareShop'
import { agentApi } from '@/services/api/agents'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import EarnedMarkTiers from '@/components/common/EarnedMarkTiers.vue'
import BaseModal from '@/components/BaseModal.vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const { t } = useI18n()
const authStore = useAuthStore()
const { localCurrency } = useFrames()

const catalog = ref<FlareShopCatalog | null>(null)
const receipts = ref<FlareShopReceipt[]>([])
const agents = ref<Array<{ did: string; name: string; balance: string }>>([])
// §FESUITE (2026-10-05): a failed agent-list read left the buy dialog's pickers empty and its Confirm disabled with no word
// why; the dialog says the read failed now, with Try again
const agentsFailed = ref(false)
// §FESUITE (V0594): the catalog's and the receipts' reads, each its own failed state (a failed catalog read showed
// "This lane is open"; a failed receipts read showed no section, as if nothing had been bought)
const catalogFailed = ref(false)
const receiptsFailed = ref(false)
const loaded = ref(false)
const busy = ref(false)
const fiatEnabled = ref(false)

const buyOpen = ref(false)
const selected = ref<FlareShopTier | null>(null)
const buyerDid = ref('')
const targetDid = ref('')
const buyError = ref('')
const buyOk = ref('')

const currentTier = computed(() => authStore.user?.flare_tier || null)
// Ranks come from the catalog (the server owns the ladder). The literal table
// is only a fallback for tiers the shop does not sell — operator/commander are
// admin-granted and never appear in `tiers`, but a holder of one still outranks
// everything here, which is what keeps the buttons honest for an admin.
const RANK_FALLBACK: Record<string, number> = {
  sentinel: 1, architect: 2, founder: 3, shadow_chancellor: 4, operator: 50, commander: 99,
}
function rankOf(tier: string | null | undefined): number {
  const fromCatalog = catalog.value?.tiers.find(x => x.tier === tier)?.rank
  if (typeof fromCatalog === 'number') return fromCatalog
  return RANK_FALLBACK[tier || ''] || 0
}
// "Owned" means: what you already hold ranks at or above this tier, so buying
// it would convey nothing (the backend refuses it with a 409 for the same
// reason). Showing that up front is friendlier than a rejected purchase.
const isOwned = (tier: string) => !!currentTier.value && rankOf(currentTier.value) >= rankOf(tier)
// Mirrors the backend's own unlock rule, §20.1 included: holding the key tier
// unlocks the catalog, and so does being an admin developer (who can wear the
// encirclements for testing without their operator/commander rank being
// overwritten). Without the admin clause an admin saw "Already yours" on the
// key tier while every tile below rendered locked — two true statements that
// read as a contradiction.
const hasEncirclements = computed(() =>
  currentTier.value === (catalog.value?.encirclement_unlock_tier || 'shadow_chancellor')
  || !!(authStore.user as any)?.selected_encirclement_flare
  || !!authStore.isAdmin)
// 🔴 findings row 183 — THE GALLERY LOOKED LIKE A PICKER AND WAS A POSTER.
// Every variant/overlay tile was a plain <div> with no handler: you could admire a flare and
// not wear one, which is his report exactly ("it doesnt take the pick … a bad method at the
// bottom"). The per-agent controls on /my-agents work, and they are the CONTROL that made this
// findable — same rail, two callers, one wired. So this uses the identical rail FlareManager
// uses (`PATCH /fiat/flare/selection`), not a second one invented for the shop.
//
// Two states the tiles must tell apart, because a dead control and a refused one look the same:
// LOCKED (no encirclement tier owned — the tile is disabled and says why) and REFUSED (the
// server said no, e.g. a sovereign variant belongs to another agent, §SOVEREIGNOWN row 168 —
// that refusal is CORRECT and is surfaced verbatim rather than swallowed).
const pickBusy = ref(false)
const pickError = ref('')
const wornVariant = ref<string | null>((authStore.user as any)?.flare_encirclement_variant || null)
const wornOverlay = ref<string | null>((authStore.user as any)?.flare_encirclement_overlay || null)

async function _applySelection(patch: Record<string, unknown>, onOk: () => void) {
  if (pickBusy.value) return
  pickBusy.value = true
  pickError.value = ''
  try {
    const r = await apiClient.patch('/fiat/flare/selection', patch)
    const st: any = r.data || {}
    // the SERVER's answer is the truth, not the tile we pressed
    wornVariant.value = st.flare_encirclement_variant ?? wornVariant.value
    wornOverlay.value = st.flare_encirclement_overlay ?? null
    onOk()
  } catch (e: any) {
    pickError.value = e?.response?.data?.detail
      || t('flareShopView.pickFailed', 'Could not wear that flare.')
  } finally {
    pickBusy.value = false
  }
}

function pickVariant(v: string) {
  if (!hasEncirclements.value) return
  _applySelection({ variant: v }, () => { wornVariant.value = v })
}

/** Pressing the worn overlay again REMOVES it — an overlay is an independent axis and a picker
 *  with no way back is a trap. */
function pickOverlay(o: string) {
  if (!hasEncirclements.value) return
  const next = wornOverlay.value === o ? null : o
  _applySelection({ overlay: next }, () => { wornOverlay.value = next })
}

const unlockedCorners = computed(() =>
  catalog.value?.tiers.find(x => x.tier === currentTier.value)?.unlocks_corner_flares
  ?? (currentTier.value ? [currentTier.value] : []))

const tierLabel = (tier: string) => ({
  sentinel: 'Sentinel',
  architect: 'Architect',
  founder: 'Founder',
  shadow_chancellor: 'Shadow Chancellor',
  operator: 'Operator',
  commander: 'Commander',
} as Record<string, string>)[tier] || prettyId(tier)

function prettyId(id: string): string {
  return id.split(/[-_]/).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ')
}

function prettyAmount(v: string | number | null | undefined): string {
  const n = Number(v ?? 0)
  if (!Number.isFinite(n)) return '0'
  return n.toLocaleString(appLocale(), { maximumFractionDigits: n < 1000 ? 2 : 0 })
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toLocaleDateString(appLocale(), { year: 'numeric', month: 'short', day: 'numeric' }) } catch { return '' }
}

function openBuy(tier: FlareShopTier) {
  selected.value = tier
  buyError.value = ''
  buyOk.value = ''
  if (!buyerDid.value && agents.value.length) buyerDid.value = agents.value[0].did
  if (!targetDid.value && agents.value.length) targetDid.value = agents.value[0].did
  buyOpen.value = true
}

async function confirmBuy() {
  if (!selected.value || !buyerDid.value) return
  busy.value = true
  buyError.value = ''
  buyOk.value = ''
  try {
    const res = await flareShopApi.purchase({
      tier: selected.value.tier,
      buyer_agent_did: buyerDid.value,
      target_agent_did: targetDid.value || buyerDid.value,
    })
    buyOk.value = res.founder_cap_fallback
      ? t('flareShopView.grantedFallback', 'Founder was full, so Architect was granted instead. Transaction') + ` ${res.transaction_id}`
      : t('flareShopView.granted', 'Granted:') + ` ${tierLabel(res.granted)} · ${t('flareShopView.tx', 'transaction')} ${res.transaction_id}`
    // refresh the profile so the flare (and everything gated on it, including
    // the My Flare sidebar entry) lights up without a reload
    await authStore.refreshProfile?.()
    await Promise.all([load(), loadReceipts()])
  } catch (e: any) {
    buyError.value = e?.response?.data?.detail || e?.message || t('flareShopView.buyFailed', 'Purchase failed')
  } finally {
    busy.value = false
  }
}

async function load() {
  try {
    catalog.value = await flareShopApi.getCatalog()
    catalogFailed.value = false
  } catch {
    // a refresh that fails keeps the catalog already read; with none read, the page says the read failed
    if (!catalog.value) catalogFailed.value = true
  }
  // §FESUITE: `loaded` marks the attempt; `catalog` is the read. The counts and the "not enabled" banner wait for
  // the catalog itself (a failed read said "purchases are not enabled" and showed 0 of everything).
  loaded.value = true
}

async function loadReceipts() {
  if (!authStore.isAuthenticated) return
  try {
    const r = await flareShopApi.myPurchases()
    receipts.value = r.purchases || []
    receiptsFailed.value = false
  } catch {
    // no purchases is an answer the registry gives; a read that failed is not one
    receiptsFailed.value = true
  }
}

async function loadAgents() {
  if (!authStore.isAuthenticated) return
  try {
    const res: any = await agentApi.getMyAgents({ limit: 200, topLevelOnly: true })
    const list = Array.isArray(res) ? res : (res?.items || [])
    agents.value = list
      .filter((a: any) => (a.status || '').toLowerCase() === 'active')
      .map((a: any) => ({
        did: a.did || a.agent_did || a.id,
        name: a.name || a.human_readable_id || (a.did || '').slice(-12),
        balance: String(a.liquid_balance ?? a.balance ?? '0'),
      }))
      // richest first: the agent most likely to be able to pay
      .sort((a: any, b: any) => Number(b.balance) - Number(a.balance))
    agentsFailed.value = false
  } catch {
    if (!agents.value.length) agentsFailed.value = true
  }
}

async function loadFiatFlag() {
  try {
    // §FEFRAME W2: the ONE shared config read (useRegistryConfig), not a request of its own
    fiatEnabled.value = !!(await loadRegistryConfig()).fiat_onramp_enabled
  } catch { /* default false — the honest assumption on this fleet */ }
}

onMounted(() => { load(); loadReceipts(); loadAgents(); loadFiatFlag() })
</script>

<style scoped>
.fsh-view { max-width: 1200px; margin: 0 auto; padding: 1.5rem 1rem 4rem; }
.fsh-head { text-align: center; margin-bottom: 1.5rem; }
.fsh-eyebrow { font-size: 0.68rem; letter-spacing: 0.18em; color: rgba(var(--nc-primary-rgb), 0.75); font-family: var(--nc-font-mono, monospace); }
.fsh-title { font-size: 2rem; font-weight: 700; margin: 0.35rem 0 0.5rem; }
.fsh-sub { color: var(--nc-text-muted, #94a3b8); max-width: 720px; margin: 0 auto; line-height: 1.55; font-size: 0.92rem; }
.fsh-ccy { color: rgba(var(--nc-primary-rgb), 0.95); }

.fsh-banner { display: flex; gap: 0.75rem; align-items: flex-start; border-radius: 0.6rem; padding: 0.8rem 1rem; margin: 1.25rem 0; border: 1px solid; }
.fsh-banner--off { border-color: rgba(251, 191, 36, 0.35); background: rgba(251, 191, 36, 0.06); color: #fbbf24; }
.fsh-banner--on { border-color: rgba(52, 211, 153, 0.3); background: rgba(52, 211, 153, 0.05); color: #34d399; }
.fsh-banner-title { font-weight: 600; font-size: 0.9rem; }
.fsh-banner-sub { font-size: 0.8rem; opacity: 0.85; margin-top: 0.15rem; }

.fsh-standing { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 1rem 1.25rem; border: 1px solid rgba(148,163,184,0.15); border-radius: 0.7rem; background: rgba(15,23,42,0.35); margin-bottom: 1.5rem; }
.fsh-standing-left { display: flex; align-items: center; gap: 1rem; }
.fsh-standing-label { font-size: 0.65rem; letter-spacing: 0.12em; color: var(--nc-text-muted, #94a3b8); }
.fsh-standing-value { font-size: 1.15rem; font-weight: 600; }
.fsh-standing-sub { font-size: 0.78rem; color: var(--nc-text-muted, #94a3b8); }
.fsh-wear-link { display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.82rem; color: rgba(var(--nc-primary-rgb), 0.9); white-space: nowrap; }
.fsh-wear-link:hover { text-decoration: underline; }

.fsh-tiers { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 1rem; margin-bottom: 1.25rem; }
.fsh-tier { border: 1px solid rgba(148,163,184,0.16); border-radius: 0.7rem; padding: 1rem; background: rgba(15,23,42,0.35); display: flex; flex-direction: column; }
.fsh-tier--key { border-color: rgba(167,139,250,0.4); box-shadow: 0 0 0 1px rgba(167,139,250,0.08) inset; }
.fsh-tier--owned { opacity: 0.72; }
.fsh-tier-top { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; }
.fsh-tier-name { font-weight: 600; }
.fsh-tier-tag { font-size: 0.58rem; letter-spacing: 0.12em; padding: 0.12rem 0.4rem; border-radius: 0.25rem; background: rgba(167,139,250,0.16); color: #c4b5fd; }
.fsh-tier-tag--owned { background: rgba(148,163,184,0.16); color: #cbd5e1; }
.fsh-tier-price { display: flex; align-items: baseline; gap: 0.35rem; margin: 0.6rem 0 0.75rem; }
.fsh-tier-amount { font-size: 1.5rem; font-weight: 700; font-family: var(--nc-font-mono, monospace); }
.fsh-tier-ccy { font-size: 0.75rem; color: var(--nc-text-muted, #94a3b8); }
.fsh-tier-perks { list-style: none; padding: 0; margin: 0 0 1rem; display: flex; flex-direction: column; gap: 0.35rem; flex: 1; }
.fsh-tier-perks li { display: flex; align-items: center; gap: 0.4rem; font-size: 0.78rem; color: var(--nc-text-secondary, #cbd5e1); }
.fsh-perk-strong { color: #c4b5fd !important; }
.fsh-perk-muted { color: rgba(148,163,184,0.6) !important; }
.fsh-buy { width: 100%; padding: 0.5rem; border-radius: 0.4rem; font-size: 0.82rem; font-weight: 600; border: 1px solid rgba(var(--nc-primary-rgb),0.4); background: rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.95); transition: all 0.15s; }
.fsh-buy:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.2); }
.fsh-buy:disabled { opacity: 0.45; cursor: not-allowed; }

/* The earned-mark section sits between the honest line and the catalogue, so
   the shop reads: here is what is for sale, here is what is not, now browse. */
.fsh-marks {
  margin: 0 0 2.25rem; padding: 1.25rem 1.4rem;
  border: 1px solid rgba(148,163,184,0.14); border-radius: 0.8rem;
  background: rgba(15,23,42,0.32);
}
.fsh-earned { display: flex; gap: 0.5rem; align-items: flex-start; font-size: 0.78rem; color: var(--nc-text-muted, #94a3b8); border-left: 2px solid rgba(148,163,184,0.25); padding-left: 0.7rem; margin: 0 0 1rem; line-height: 1.5; }

.fsh-gallery-head { display: flex; align-items: baseline; gap: 0.6rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
/* The two galleries are DIFFERENT axes (an encirclement vs an overlay worn on
   top of one). 2rem read as one continuous wall of circles; the rule and the
   larger gap say "new section" without needing a caption to explain it. */
.fsh-gallery-head--second {
  margin-top: 3.25rem;
  padding-top: 1.75rem;
  border-top: 1px solid rgba(148,163,184,0.12);
}
.fsh-gallery-title { font-size: 1.05rem; font-weight: 600; margin: 0; }
.fsh-gallery-count { font-family: var(--nc-font-mono, monospace); font-size: 0.8rem; color: rgba(var(--nc-primary-rgb),0.9); }
.fsh-gallery-note { font-size: 0.75rem; color: var(--nc-text-muted, #94a3b8); }
/* §MARKCOLLAR polish — the previews render at size="xl" (96px) and the lush
   variants throw halos, embers and scanlines WELL beyond the avatar disc. In a
   104px cell with a 0.85rem gutter those halos landed on the neighbouring tile,
   which is what made the gallery read as cramped and noisy. The cell is now
   sized for the ARTWORK, not for the avatar: 96px disc + room for its halo on
   every side, and a gutter wide enough that two lit variants never touch. */
.fsh-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 1.5rem 1.25rem;
  margin-bottom: 0.5rem;
}
.fsh-tile {
  display: flex; flex-direction: column; align-items: center;
  gap: 0.7rem;
  padding: 1.15rem 0.6rem 0.9rem;
  border-radius: 0.7rem;
  border: 1px solid rgba(148,163,184,0.1);
  background: rgba(15,23,42,0.25);
  transition: border-color 160ms ease, background 160ms ease, transform 160ms ease;
}
/* Hover lifts the tile so a busy grid still tells you what you are pointing at. */
.fsh-tile:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.32);
  background: rgba(15,23,42,0.5);
  transform: translateY(-2px);
}
/* Keeps the halo inside its own tile: the artwork gets a reserved square rather
   than overflowing into the next cell. */
.fsh-tile > :first-child {
  display: flex; align-items: center; justify-content: center;
  min-height: 104px;
}
.fsh-tile--locked { opacity: 0.5; }
.fsh-tile-label {
  font-size: 0.7rem; color: var(--nc-text-secondary, #cbd5e1);
  text-align: center; line-height: 1.25;
  /* two lines max, so one long variant name cannot make its tile taller than
     the rest of the row and ripple the grid */
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
  overflow: hidden;
}

.fsh-receipts { margin-top: 2.5rem; }
.fsh-receipt { display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 0; border-bottom: 1px solid rgba(148,163,184,0.08); font-size: 0.8rem; flex-wrap: wrap; }
.fsh-receipt-tier { font-weight: 600; min-width: 130px; }
.fsh-receipt-amount { font-family: var(--nc-font-mono, monospace); }
.fsh-receipt-status { font-size: 0.65rem; letter-spacing: 0.08em; text-transform: uppercase; padding: 0.1rem 0.35rem; border-radius: 0.25rem; }
.fsh-receipt-status--completed { background: rgba(52,211,153,0.14); color: #34d399; }
.fsh-receipt-status--failed { background: rgba(248,113,113,0.14); color: #f87171; }
.fsh-receipt-status--pending { background: rgba(251,191,36,0.14); color: #fbbf24; }
.fsh-receipt-reason { color: #f87171; font-size: 0.72rem; }
.fsh-receipt-date { margin-left: auto; color: var(--nc-text-muted, #94a3b8); font-size: 0.72rem; }

.fsh-otherlane { margin-top: 2.5rem; font-size: 0.8rem; color: var(--nc-text-muted, #94a3b8); text-align: center; }
.fsh-link { color: rgba(var(--nc-primary-rgb),0.9); text-decoration: underline; } /* §FESUITE: a link in a sentence shows without colour */
.fsh-link:hover { text-decoration-thickness: 2px; }

.fsh-modal { display: flex; flex-direction: column; gap: 0.9rem; text-align: left; }
.fsh-modal-line { font-size: 0.9rem; }
.fsh-modal-note { font-size: 0.8rem; color: #c4b5fd; }
.fsh-modal-warn { font-size: 0.8rem; color: #fbbf24; }
.fsh-field { display: flex; flex-direction: column; gap: 0.25rem; }
.fsh-field-label { font-size: 0.7rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--nc-text-muted, #94a3b8); }
.fsh-field-hint { font-size: 0.72rem; color: var(--nc-text-muted, #94a3b8); }
.fsh-select { background: rgba(15,23,42,0.6); border: 1px solid rgba(148,163,184,0.2); border-radius: 0.35rem; padding: 0.45rem 0.6rem; font-size: 0.85rem; color: inherit; }
.fsh-modal-error { font-size: 0.8rem; color: #f87171; }
.fsh-modal-ok { font-size: 0.8rem; color: #34d399; }

/* findings row 183 — the gallery tiles are CONTROLS now, so they must look pressable, show
   which one is worn, and look refused when they are locked. A tile that renders identically
   whether or not it can be pressed is the reason this went unnoticed. */
.fsh-tile--pick { cursor: pointer; background: none; border: 1px solid transparent;
  font: inherit; color: inherit; transition: border-color .12s ease, transform .12s ease; }
.fsh-tile--pick:hover:not(:disabled) { border-color: var(--nc-primary, #00e5ff); transform: translateY(-2px); }
.fsh-tile--pick:disabled { cursor: not-allowed; opacity: .55; }
.fsh-tile--worn { border-color: var(--nc-primary, #00e5ff); }
.fsh-tile-worn { display: block; font-size: .68rem; letter-spacing: .08em;
  color: var(--nc-primary, #00e5ff); margin-top: .15rem; }
.fsh-pick-error { margin: .5rem 0 0; color: var(--nc-danger, #ff5252); font-size: .85rem; }
</style>
