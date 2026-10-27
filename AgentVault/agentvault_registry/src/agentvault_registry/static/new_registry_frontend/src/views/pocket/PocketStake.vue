<!-- POCKET · Lock sheet (2026-07-08) — one-tap locking over the EXISTING staking_enhanced backend
     (stakingApi: balance/my-positions/stake/unstake/apy-tiers). Biometric-confirmed. No new backend. -->
<template>
  <transition name="pk-sheet">
    <div v-if="open" class="pt-scrim" @click.self="$emit('close')">
      <div ref="trapEl" class="pt-sheet" role="dialog" aria-modal="true" :aria-label="t('pocket.stake.title', 'Lock')">
        <div class="pt-grip" aria-hidden="true"></div>
        <h2 class="pt-title"><Icon name="mdi:lock" /> {{ t('pocket.stake.title', 'Lock') }}</h2>

        <label class="pt-lab" for="pt-agent">{{ t('pocket.stake.agent', 'Agent') }}</label>
        <select id="pt-agent" v-model="agentDid" class="pt-in" :disabled="busy" @change="loadStats()">
          <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shorten(a.did) }}</option>
        </select>
        <p v-if="!credAgents.length" class="pt-note pt-warn">{{ noAgentReason }}</p>

        <!-- current position summary -->
        <div v-if="stats" class="pt-stats">
          <div class="pt-stat"><span>{{ t('pocket.stake.staked', 'Locked') }}</span><strong>{{ fmt(stats.totalStaked) }} <small>{{ ccy }}</small></strong></div>
          <div v-if="pocketRatesOn" class="pt-stat"><span>{{ t('pocket.stake.rewards', 'Payouts') }}</span><strong class="pt-pos">{{ fmt(stats.availableRewards) }} <small>{{ ccy }}</small></strong></div>
        </div>

        <!-- Lock tier picker -->
        <label class="pt-lab">{{ t('pocket.stake.lockPeriod', 'Lock period') }}</label>
        <div class="pt-tiers">
          <!-- loop var is `tier`, NOT `t`: `t` is the translate function here. -->
          <button v-for="tier in tiers" :key="tier.lockPeriod" class="pt-tier" :class="{ active: lockPeriod === tier.lockPeriod }"
                  :disabled="busy" @click="lockPeriod = tier.lockPeriod">
            <span class="pt-tier-days">{{ tier.lockPeriod ? tier.lockPeriod + 'd' : t('pocket.stake.flexible', 'Flexible') }}</span>
            <span v-if="pocketRatesOn && tier.apy" class="pt-tier-apy">{{ (tier.apy ?? 0).toFixed(1) }}%</span>
          </button>
        </div>

        <label class="pt-lab">{{ t('pocket.stake.amount', 'Amount') }}</label>
        <div class="pt-amt-row">
          <input v-model="amount" class="pt-in pt-amt" type="text" inputmode="decimal" placeholder="0.00" :disabled="busy"
                 :aria-label="t('pocket.stake.amount', 'Amount')" :aria-invalid="!!amountWarn" />
          <span class="pt-amt-ccy">{{ ccy }}</span>
        </div>
        <p v-if="amountWarn" class="pt-msg bad" data-testid="pt-amount-warn">{{ amountWarn }}</p>

        <!-- §FOREIGNACT — this is the exact action the Commander mis-read: he
             locked "1.337" from the frame-c surface as an agent homed on
             registry-a and locked 1337.000000 AVT there, while the page said
             BVT. The lock lands where the AGENT lives; say it above the button. -->
        <ActingContextNotice strong />

        <!-- §REPBOND — do not lock the whole grant: the reputation bond needs liquidity -->
        <p v-if="bondHint" class="pt-msg" data-testid="pt-bond-hint">{{ bondHint }}</p>
        <div class="pt-actions">
          <button class="pt-btn pt-ghost" :disabled="busy" @click="$emit('close')">{{ t('common.close', 'Close') }}</button>
          <button class="pt-btn pt-primary" :disabled="busy || !stakeAmount || !agentDid" @click="doStake">
            <Icon :name="lock.enabled.value ? 'mdi:fingerprint' : 'mdi:lock'" />
            {{ busy ? t('pocket.common.working', 'Working…')
                 : lock.enabled.value ? t('pocket.stake.confirmStake', 'Confirm & lock')
                 : tp('pocket.stake.stakeAmount', 'Lock {amount} {ccy}', { amount: stakeAmount || '', ccy }) }}
          </button>
        </div>
        <p v-if="msg" class="pt-msg" :class="msg.ok ? 'ok' : 'bad'">{{ msg.text }}</p>

        <!-- positions -->
        <p v-if="stats && stats.positionsReadable === false && Number(stats.totalStaked) > 0" class="pt-msg bad" data-testid="pt-positions-unreadable">
          {{ t('pocket.stake.positionsUnreadable', 'Your positions could not be read just now; the locked total above is the ledger\'s.') }}
        </p>
        <template v-if="stats && activePositions.length">
          <h3 class="pt-sub">{{ t('pocket.stake.positions', 'Positions') }}</h3>
          <ul class="pt-pos-list">
            <li v-for="p in activePositions" :key="p.id" class="pt-pos-row" data-testid="pt-pos" :data-lock="p.lockPeriod">
              <div class="pt-pos-body">
                <div class="pt-pos-amt">{{ fmt(p.amount) }} <small>{{ ccy }}</small></div>
                <div class="pt-pos-meta">{{ p.lockPeriod ? tp('pocket.stake.dayLock', '{n}d lock', { n: p.lockPeriod }) : t('pocket.stake.flexibleLower', 'flexible') }}<template v-if="pocketRatesOn"> · {{ (p.apy ?? 0).toFixed(1) }}% {{ t('pocket.stake.apy', 'payout rate') }}</template></div>
              </div>
              <!-- §FESUITE: Unlock only where the server says this position can be (a locked one says until when) -->
              <button v-if="p.canUnstake" class="pt-unstake" :disabled="busy" @click="doUnstake(p)"><Icon name="mdi:lock-open" /> {{ t('pocket.stake.unstake', 'Unlock') }}</button>
              <span v-else class="pt-locked" data-testid="pt-locked">{{ p.unlockDate ? tp('pocket.stake.lockedUntil', 'Locked until {date}', { date: fmtDate(p.unlockDate) }) : t('pocket.stake.locked', 'Locked') }}</span>
            </li>
          </ul>
        </template>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { reputationBondApi } from '@/services/api/reputationBond'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import { appLocale } from '@/services/appLocale'
import { ref, computed, watch } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import Icon from '@/components/Icon.vue'
import ActingContextNotice from '@/components/common/ActingContextNotice.vue'
import { useAuthStore } from '@/stores/auth'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { stakingApi } from '@/services/api/staking'
import { lockOnlyTiers } from '@/services/stakingLocks'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { usePocketLock } from '@/composables/usePocketLock'
import { useI18n } from '@/composables/useI18n'
import { typedAmount } from '@/services/money/typedAmount'

const { t, tp } = useI18n()

// §POCKETBRIDGE5 W-D — the dialog role was already declared; the trap makes it TRUE:
// focus enters on open, Tab cycles inside, and RETURNS to the opener on close.
const trapEl = ref<HTMLElement | null>(null)
const props = defineProps<{ open: boolean; ccy?: string; prefill?: { amount?: string; agent?: string } | null }>()
useFocusTrap(trapEl, { activeWhen: computed(() => props.open) })
defineEmits<{ (e: 'close'): void }>()

const auth = useAuthStore()
const lock = usePocketLock()
const ccy = computed(() => props.ccy || currentOwnCurrency())
const shorten = (s: string) => !s ? '—' : s.length > 26 ? s.slice(0, 14) + '…' + s.slice(-6) : s
const fmt = (v: any) => { const n = Number(v); return isNaN(n) ? String(v ?? '0') : n.toLocaleString(appLocale(), { maximumFractionDigits: 4 }) }
const fmtDate = (d: string) => { const x = new Date(d); return isNaN(x.getTime()) ? d : x.toLocaleDateString(appLocale(), { year: 'numeric', month: 'short', day: 'numeric' }) }

// §POCKETBRIDGE #PK3 — the ONE shared agent-context brain (sealed-vault aware).
const { credAgents, noAgentReason, ensureAgentFor } = usePocketAgent()

const agentDid = ref('')
const stats = ref<any>(null)
/* §FESUITE: the server lists unlocked positions too (status 'unstaked'); each one used to carry an Unlock button. */
const activePositions = computed<any[]>(() => (stats.value?.stakingPositions || []).filter((p: any) => p.status !== 'unstaked'))
const tiers = ref<any[]>([])
// §BAFIN (2026-10-01): no rate and no payout figure where this registry pays none (core/staking_gate.py)
const { config: pocketStakeCfg } = useRegistryConfig()
// §BAFIN B.5.5 (agentvault2-5b, 2026-10-03): fail-closed. No rate or payout figure shows until the registry has
// said payouts are on; `!== false` showed one while the config was in flight and kept it if the read failed.
const pocketRatesOn = computed(() => pocketStakeCfg.value.staking_rewards_enabled === true)
const lockPeriod = ref(0)
const amount = ref('')
/* §FESUITE — `!Number(amount)` let "-1" and "1e309" press Lock and leave the page; typedAmount is the rule. */
const stakeAmount = computed(() => typedAmount(amount.value))
const amountWarn = computed(() => (String(amount.value).trim() && !stakeAmount.value)
  ? t('pocket.common.amountWarn', 'Not an amount: digits with one decimal point, more than zero.') : '')
const busy = ref(false)
const msg = ref<{ ok: boolean; text: string } | null>(null)

const ensureAgent = () => ensureAgentFor(agentDid.value)

// §REPBOND — the tip his flow asked for: warn before someone locks everything.
const bondCfg = ref<any>(null)
const bondInfo = ref<any>(null)
async function loadBondHint() {
  try { bondCfg.value = await reputationBondApi.getConfig() } catch { bondCfg.value = null }
  bondInfo.value = null
  if (agentDid.value) { try { bondInfo.value = await reputationBondApi.getAgentReputation(agentDid.value) } catch { bondInfo.value = null } }
}
const bondHint = computed(() => {
  const c = bondCfg.value
  if (!c || c.mode === 'off' || bondInfo.value?.is_bonded) return ''
  return tp('pocket.stake.bondHint', 'Keep at least {amt} {ccy} liquid: an agent that provides services needs it for its reputation bond. Do not lock the whole grant.', { amt: c.amount, ccy: c.currency })
})
watch(agentDid, () => { void loadBondHint() }, { immediate: true })

/* §FESUITE: a refresh after a lock or an unlock keeps the sentence that says what happened (it used to clear it in
   the same tick, so "Staked 10" was never seen) and keeps the positions on screen while the new ones load. */
async function loadStats(opts: { afterAction?: boolean } = {}) {
  if (!opts.afterAction) { msg.value = null; stats.value = null }
  if (!await ensureAgent()) return
  try { stats.value = await stakingApi.getMyStakingStats() } catch { stats.value = null }
}
async function loadTiers() {
  try { const r = await stakingApi.getApyTiers(); tiers.value = (r.tiers || []).slice(0, 4) } catch { tiers.value = [] }
  // §BAFIN: payouts off ⇒ no tiers; a lock still buys governance weight, so offer the periods without a rate
  if (!tiers.value.length) tiers.value = lockOnlyTiers().slice(0, 4)
  if (tiers.value.length) lockPeriod.value = tiers.value[0].lockPeriod
}

async function doStake() {
  if (!stakeAmount.value || busy.value) return
  busy.value = true; msg.value = null
  try {
    if (lock.enabled.value && !(await lock.verify())) { msg.value = { ok: false, text: t('pocket.stake.bioFailedStake', 'Biometric confirmation failed — nothing locked.') }; return }
    if (!await ensureAgent()) { msg.value = { ok: false, text: t('pocket.stake.authFailed', 'Agent auth failed.') }; return }
    await stakingApi.stake({ amount: String(stakeAmount.value), lockPeriod: lockPeriod.value })
    msg.value = { ok: true, text: tp('pocket.stake.stakedOk', 'Locked {amount} {ccy}.', { amount: stakeAmount.value, ccy: ccy.value }) }
    try { (navigator as any).vibrate?.([8, 40, 8]) } catch {}
    amount.value = ''
    await loadStats({ afterAction: true })
  } catch (e: any) { msg.value = { ok: false, text: e?.response?.data?.detail || e?.message || t('pocket.stake.stakeFailed', 'Lock failed') } }
  finally { busy.value = false }
}

async function doUnstake(p: any) {
  if (busy.value) return
  busy.value = true; msg.value = null
  try {
    if (lock.enabled.value && !(await lock.verify())) { msg.value = { ok: false, text: t('pocket.stake.bioFailed', 'Biometric confirmation failed.') }; return }
    if (!await ensureAgent()) { msg.value = { ok: false, text: t('pocket.stake.authFailed', 'Agent auth failed.') }; return }
    await stakingApi.unstake(p.id, p.amount)
    msg.value = { ok: true, text: t('pocket.stake.unstaked', 'Unlocked.') }
    await loadStats({ afterAction: true })
  } catch (e: any) {
    // per-position FIFO cooldown (~7d) surfaces as 403 — show it honestly
    msg.value = { ok: false, text: e?.response?.data?.detail || e?.message || t('pocket.stake.unstakeFailed', 'Unlock failed (position may still be in its lock period)') }
  } finally { busy.value = false }
}

// §ASSISTCHECK (2026-08-29) — immediate is LOAD-BEARING: the voice/deep-link
// door (?sheet=stake) opens via PocketHome's immediate route watcher DURING
// setup, so this sheet is BORN with open=true and a transition-only watcher
// never fires — prefill, tiers and stats were all dead on that path while the
// home button path (a real false→true transition) worked. Measured live.
watch(() => props.open, (o) => {
  if (o) {
    msg.value = null
    // §POCKETBRIDGE3 WS-B — a voice door may arrive with the amount/agent
    // already spoken; the human still confirms on this sheet (the iron rule).
    if (props.prefill?.amount) amount.value = String(props.prefill.amount)
    if (props.prefill?.agent && credAgents.value.some(a => a.did === props.prefill!.agent)) agentDid.value = props.prefill.agent
    if (!agentDid.value && credAgents.value.length) agentDid.value = (auth as any).activeAgent?.did || credAgents.value[0].did
    loadTiers(); if (agentDid.value) loadStats()
  }
}, { immediate: true })

// A cold deep link can open the sheet BEFORE the roster resolves — when the
// agents land, apply the pending prefill/fallback instead of silently
// dropping it (the selection stays the human's to change).
watch(credAgents, () => {
  if (!props.open || agentDid.value || !credAgents.value.length) return
  if (props.prefill?.agent && credAgents.value.some(a => a.did === props.prefill!.agent)) agentDid.value = props.prefill.agent
  else agentDid.value = (auth as any).activeAgent?.did || credAgents.value[0].did
  if (agentDid.value) loadStats()
})
</script>

<style scoped>
.pt-scrim { position: fixed; inset: 0; z-index: 90; background: rgba(0,0,0,0.55); backdrop-filter: blur(3px); display: flex; align-items: flex-end; }
.pt-sheet { width: 100%; max-width: 560px; margin: 0 auto; background: #0c0f15; border: 1px solid rgba(255,255,255,0.09);
  border-radius: 22px 22px 0 0; padding: 0.8rem 1.1rem calc(1.4rem + env(safe-area-inset-bottom, 0px));
  box-shadow: 0 -20px 50px rgba(0,0,0,0.5); max-height: 92dvh; overflow-y: auto; }
.pt-grip { width: 40px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.1rem auto 0.9rem; }
.pt-title { display: flex; align-items: center; gap: 0.45rem; font-size: 1.1rem; margin: 0 0 0.9rem; }
.pt-title :deep(svg) { width: 1.25rem; height: 1.25rem; color: var(--nc-primary, #00d4ff); }
.pt-lab { display: block; font-size: 0.7rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.5; font-weight: 600; margin: 0.7rem 0 0.3rem; }
.pt-in { width: 100%; box-sizing: border-box; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px; padding: 0.72rem 0.85rem; color: #e6edf3; font-size: 0.9rem; outline: none; }
.pt-in:focus { border-color: rgba(0,212,255,0.45); }
.pt-note { font-size: 0.76rem; margin: 0.5rem 0 0; opacity: 0.7; } .pt-warn { color: #fbbf24; }
.pt-stats { display: flex; gap: 0.6rem; margin-top: 0.8rem; }
.pt-stat { flex: 1 1 0; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 13px; padding: 0.6rem 0.75rem; display: flex; flex-direction: column; gap: 0.15rem; }
.pt-stat span { font-size: 0.64rem; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.5; font-weight: 600; }
.pt-stat strong { font-variant-numeric: tabular-nums; font-size: 1rem; }
.pt-stat small { font-size: 0.6rem; opacity: 0.8; } .pt-pos { color: #34d399; }
.pt-tiers { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.4rem; }
.pt-tier { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; padding: 0.5rem 0.2rem;
  display: flex; flex-direction: column; align-items: center; gap: 0.1rem; cursor: pointer; color: #e6edf3; -webkit-tap-highlight-color: transparent; }
.pt-tier.active { background: rgba(0,212,255,0.1); border-color: rgba(0,212,255,0.4); }
.pt-tier-days { font-size: 0.72rem; font-weight: 650; }
.pt-tier-apy { font-size: 0.66rem; color: #34d399; font-variant-numeric: tabular-nums; }
.pt-amt-row { position: relative; }
.pt-amt { font-size: 1.4rem; font-weight: 700; font-variant-numeric: tabular-nums; padding-right: 3.5rem; }
.pt-amt-ccy { position: absolute; right: 0.9rem; top: 50%; transform: translateY(-50%); font-size: 0.82rem; font-weight: 600; opacity: 0.55; }
.pt-actions { display: flex; gap: 0.6rem; margin-top: 1rem; }
.pt-btn { flex: 1 1 0; display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem; border-radius: 13px; padding: 0.85rem;
  font-size: 0.9rem; font-weight: 650; cursor: pointer; min-height: 48px; border: 1px solid transparent; -webkit-tap-highlight-color: transparent; }
.pt-btn:disabled { opacity: 0.45; }
.pt-btn :deep(svg) { width: 1.05rem; height: 1.05rem; }
.pt-ghost { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.1); color: #e6edf3; }
.pt-primary { background: linear-gradient(160deg, rgba(0,212,255,0.2), rgba(0,212,255,0.08)); border-color: rgba(0,212,255,0.4); color: #e6edf3; }
.pt-msg { text-align: center; font-size: 0.82rem; margin: 0.7rem 0 0; }
.pt-msg.ok { color: #34d399; } .pt-msg.bad { color: #ff8a8a; }
.pt-sub { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.55; margin: 1.1rem 0 0.4rem; }
.pt-pos-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.pt-pos-row { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07); border-radius: 13px; padding: 0.6rem 0.75rem; }
.pt-pos-amt { font-variant-numeric: tabular-nums; font-weight: 650; font-size: 0.92rem; }
.pt-pos-amt small { font-size: 0.6rem; opacity: 0.8; }
.pt-pos-meta { font-size: 0.68rem; opacity: 0.55; margin-top: 0.1rem; }
.pt-unstake { display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(255,107,107,0.08); border: 1px solid rgba(255,107,107,0.25);
  border-radius: 10px; padding: 0.45rem 0.7rem; color: #ff8a8a; font-size: 0.74rem; font-weight: 600; cursor: pointer; min-height: 38px; -webkit-tap-highlight-color: transparent; }
.pt-unstake :deep(svg) { width: 0.85rem; height: 0.85rem; }
.pk-sheet-enter-active, .pk-sheet-leave-active { transition: opacity 0.2s ease; }
.pk-sheet-enter-active .pt-sheet, .pk-sheet-leave-active .pt-sheet { transition: transform 0.24s cubic-bezier(0.34,1.3,0.64,1); }
.pk-sheet-enter-from, .pk-sheet-leave-to { opacity: 0; }
.pk-sheet-enter-from .pt-sheet, .pk-sheet-leave-to .pt-sheet { transform: translateY(100%); }
@media (prefers-reduced-motion: reduce) { .pk-sheet-enter-active .pt-sheet, .pk-sheet-leave-active .pt-sheet { transition: none; } }
.pt-locked { font-size: 0.74rem; color: #9fb0c3; white-space: nowrap; }
</style>
