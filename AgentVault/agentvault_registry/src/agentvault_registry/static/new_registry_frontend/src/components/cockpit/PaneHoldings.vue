<script setup lang="ts">
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPITSHOW C2b — YOUR HOLDINGS. The other half of his trading ask.
 *
 * 🔴 THIS PANE FOLLOWS THE AGENT YOU ARE ACTING AS, AND EVERY OTHER PANE ON THIS DESK DOES
 * NOT. That distinction is the whole reason it is a separate module rather than a column
 * on the market pane, and it is stated on screen — because his very next report after the
 * last batch was *"(stop) has an agent selected and i have not selected an agent in the
 * websites agent selector"*: a desk where some panes follow the switcher and others do not
 * has to say which is which, or every name it prints looks like a choice it made for you.
 *
 * `/agora/portfolio` is AGENT-tier: it answers for whoever holds the JWT. With no agent
 * selected there is no question to ask — so the pane says that and offers the switcher,
 * rather than rendering an empty table that reads as "you own nothing".
 *
 * ⚠ CURRENCY COMES FROM THE ACTING AGENT'S HOME, NEVER THE PAGE (§FOREIGNACT). The api
 * client routes agent-tier calls to `activeAgentRegistryUrl`; `useActingContext` reads the
 * same field, so the label and the routing cannot disagree. While the foreign registry's
 * card is still loading the unit is EMPTY — an amount with no unit is honest, an amount
 * with the wrong unit is what locked 1337 AVT while the screen said BVT.
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import Icon from '@/components/Icon.vue'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { useActingContext } from '@/composables/useActingContext'
import { useAuthStore } from '@/stores/auth'
import { PANES } from './paneRegistry'
import { exchangeService, type Portfolio, type MyOrder } from '@/services/api/exchangeService'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const auth = useAuthStore() as any
const { actingCurrencyLabel, actingRegistryName, currencyDiffersFromPage } = useActingContext()
const def = PANES.holdings

const pf = ref<Portfolio | null>(null)
const orders = ref<MyOrder[]>([])
const loading = ref(false)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

const actingDid = computed<string | null>(() => auth.activeAgent?.did || null)
const actingName = computed<string>(() => auth.activeAgent?.name || actingDid.value || '')

async function load() {
  if (!actingDid.value) { pf.value = null; orders.value = []; err.value = ''; return }
  loading.value = true
  try {
    const [p, o] = await Promise.all([
      exchangeService.portfolio(),
      exchangeService.myOrders().catch(() => ({ orders: [] })),
    ])
    pf.value = p
    orders.value = (o?.orders || []).filter(x => ['open', 'partial', 'pending'].includes(String(x.status)))
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}

// Re-read the moment the acting agent changes: a portfolio left on screen from the
// PREVIOUS agent, under the new agent's name, would be the §FOREIGNACT failure exactly.
watch(actingDid, () => { pf.value = null; orders.value = []; void load() })
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 60) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const positions = computed(() => pf.value?.positions || [])
const num = (v: unknown) => { const n = Number(v); return Number.isFinite(n) ? n : null }
const fmt = (v: unknown, dp = 2) => nFmt(v, dp)

/** ⚠ Summed ONLY because every position on this venue is denominated in one currency —
 *  the listing rows carry `currency` and they are all the acting registry's. A mixed sum
 *  would need `services/currencySum.ts` (§SUMSPLIT); asserting that here rather than
 *  discovering it later. */
const mixed = computed(() => new Set(positions.value.map(p => p.currency)).size > 1)
const totalValue = computed(() =>
  positions.value.reduce((s, p) => s + (num(p.last) ?? 0) * (p.qty || 0), 0))
const totalPnl = computed(() =>
  positions.value.reduce((s, p) => s + (num(p.unrealized_pnl) ?? 0), 0))
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading && !pf" :error="err" :read-at="readAt" :reload="load">
    <div class="hld" data-testid="ckd-holdings" data-tour="cockpit-holdings">
      <!-- 🔴 NO ACTING AGENT = NO QUESTION, not an empty portfolio. -->
      <div v-if="!actingDid" class="hld-none" data-testid="hld-no-agent">
        <Icon name="mdi:account-question-outline" class="hld-none-i" />
        <p class="hld-none-t">{{ t('cockpit.hld.pick', 'Pick an agent to see its holdings') }}</p>
        <p class="hld-none-s">
          {{ t('cockpit.hld.pickWhy', 'Holdings belong to an agent, not to you — so this pane follows the agent in the header switcher. It is the only pane on this desk that does; the rest answer for your whole account.') }}
        </p>
      </div>

      <template v-else>
        <p class="hld-who" data-testid="hld-who">
          {{ tp('cockpit.hld.actingAs', 'Acting as {name}', { name: actingName }) }}
          <span v-if="currencyDiffersFromPage" class="hld-foreign" data-testid="hld-foreign">
            {{ tp('cockpit.hld.foreign', 'settles on {reg}', { reg: actingRegistryName }) }}
          </span>
        </p>

        <p v-if="!positions.length && !loading" class="hld-empty" data-testid="hld-empty">
          {{ tp('cockpit.hld.noPositions', '{name} holds no points on this market.', { name: actingName }) }}
        </p>

        <table v-else-if="positions.length" class="hld-t">
          <thead>
            <tr>
              <th class="hld-sym">{{ t('cockpit.hld.sym', 'symbol') }}</th>
              <th class="hld-n">{{ t('cockpit.hld.qty', 'qty') }}</th>
              <th class="hld-n">{{ t('cockpit.hld.cost', 'avg cost') }}</th>
              <th class="hld-n">{{ t('cockpit.hld.value', 'value') }}</th>
              <th class="hld-n">{{ t('cockpit.hld.pnl', 'P&amp;L') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in positions" :key="p.listing_id" data-testid="hld-row">
              <td class="hld-sym">
                {{ p.symbol }}
                <span v-if="p.locked_qty > 0" class="hld-lock"
                      :title="tp('cockpit.hld.lockedHint', '{n} locked behind open sell orders — held, not spent', { n: p.locked_qty })">
                  {{ tp('cockpit.hld.locked', '{n} locked', { n: p.locked_qty }) }}
                </span>
              </td>
              <td class="hld-n">{{ p.qty }}</td>
              <td class="hld-n">{{ money(fmt(p.avg_cost)) }}</td>
              <!-- ⚠ `last` null = never traded; the value is unknown, NOT zero. -->
              <td class="hld-n" data-testid="hld-value">
                {{ p.last === null ? '—' : money(fmt((num(p.last) ?? 0) * p.qty)) }}
              </td>
              <td class="hld-n" :class="(num(p.unrealized_pnl) ?? 0) > 0 ? 'is-up' : (num(p.unrealized_pnl) ?? 0) < 0 ? 'is-down' : 'is-flat'">
                {{ p.unrealized_pnl === null ? '—' : money(fmt(p.unrealized_pnl)) }}
              </td>
            </tr>
          </tbody>
        </table>

        <p v-if="positions.length" class="hld-sum" data-testid="hld-sum">
          <template v-if="mixed">
            <!-- Never one unit over a mixed sum (§SUMSPLIT / §FOREIGNACT). -->
            {{ t('cockpit.hld.mixed', 'Positions span more than one currency — no single total is shown.') }}
          </template>
          <template v-else>
            {{ tp('cockpit.hld.total', 'value {v} {ccy} · unrealised {p} {ccy}',
                  { v: money(fmt(totalValue)), p: money(fmt(totalPnl)), ccy: actingCurrencyLabel }) }}
          </template>
        </p>

        <p v-if="pf && Number(pf.dividends_received) > 0" class="hld-div" data-testid="hld-div">
          {{ tp('cockpit.hld.dividends', 'distributions received: {d} {ccy}',
                { d: money(fmt(pf.dividends_received)), ccy: actingCurrencyLabel }) }}
        </p>

        <p v-if="orders.length" class="hld-ord" data-testid="hld-orders">
          {{ tp('cockpit.hld.openOrders', '{n} open order(s) — escrow is held while they rest on the book', { n: orders.length }) }}
        </p>
      </template>
    </div>
  </PaneShell>
</template>

<style scoped>
.hld { display: flex; flex-direction: column; gap: .3rem; }
.hld-none { display: flex; flex-direction: column; align-items: center; gap: .25rem; padding: 1rem .5rem; text-align: center; }
.hld-none-i { width: 22px; height: 22px; color: var(--nc-text-muted, #6e7681); }
.hld-none-t { margin: 0; font-size: .78rem; color: var(--nc-text-secondary, #c9d1d9); }
.hld-none-s { margin: 0; font-size: .63rem; line-height: 1.35; color: var(--nc-text-muted, #6e7681); max-width: 42ch; }
.hld-who { margin: 0; font-size: .66rem; color: var(--nc-text-dim, #8b949e); }
.hld-foreign { margin-left: .3rem; color: var(--nc-warning, #d29922); }
.hld-empty { margin: .4rem 0; font-size: .7rem; color: var(--nc-text-dim, #8b949e); }
.hld-t { width: 100%; border-collapse: collapse; font-size: .72rem; }
.hld-t th { font-size: .56rem; letter-spacing: .06em; text-transform: uppercase; font-weight: 500;
  color: var(--nc-text-muted, #6e7681); text-align: right; padding-bottom: .15rem; }
.hld-t th.hld-sym { text-align: left; }
.hld-t td { padding: .08rem 0; color: var(--nc-text-secondary, #c9d1d9); }
.hld-sym { text-align: left; font-weight: 600; }
.hld-n { text-align: right; padding-left: .5rem; font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.hld-lock { margin-left: .3rem; font-size: .55rem; text-transform: uppercase; letter-spacing: .05em;
  color: var(--nc-warning, #d29922); }
.is-up { color: var(--nc-success, #3fb950); }
.is-down { color: var(--nc-danger, #f85149); }
.is-flat { color: var(--nc-text-muted, #6e7681); }
.hld-sum, .hld-div, .hld-ord { margin: .2rem 0 0; font-size: .64rem; color: var(--nc-text-muted, #6e7681); }
</style>
