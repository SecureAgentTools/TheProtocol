<template>
  <!-- V0657 (a), item 8: what the dispute is about, on the screen a ruler reads: the Guild order (linked) with its spec,
       the award, what was handed in (or that nothing was), the deadline, its own events, the room thread, the escrow;
       or the contract it is about. -->
  <div class="dsp-ev" data-testid="dispute-evidence">
    <template v-if="order">
      <div class="dsp-ev__head">
        <router-link :to="{ name: 'pocket-earn', query: { order: order.id } }" class="dsp-ev__link" data-testid="dispute-order-link">
          {{ order.title || order.id }} →
        </router-link>
        <span class="dsp-ev__status">{{ order.status }}</span>
      </div>
      <dl class="dsp-ev__kv">
        <dt>{{ t('disputesView.v2.escrow', 'Escrow held') }}</dt>
        <dd>{{ amount(order.escrow_held) }} {{ order.currency }} <span class="dsp-ev__muted">({{ tp('disputesView.v2.bounty', 'bounty {b}', { b: amount(order.bounty) }) }})</span></dd>
        <dt>{{ t('disputesView.v2.deadline', 'Deadline') }}</dt>
        <dd>{{ when(order.deadline) }}</dd>
        <template v-if="order.awarded_bid">
          <dt>{{ t('disputesView.v2.award', 'Awarded bid') }}</dt>
          <dd>{{ tp('disputesView.v2.awardLine', '{price} {cur}, {eta}', { price: amount(order.awarded_bid.price), cur: order.currency || '', eta: eta(order.awarded_bid.eta_seconds) }) }}
            <span v-if="order.awarded_at" class="dsp-ev__muted">{{ tp('disputesView.v2.awardedAt', 'on {when}', { when: when(order.awarded_at) }) }}</span></dd>
        </template>
        <dt>{{ t('disputesView.v2.handIn', 'Handed in') }}</dt>
        <dd data-testid="dispute-handin">
          <template v-if="order.handed_in">{{ when(order.submitted_at) }}</template>
          <strong v-else>{{ t('disputesView.v2.nothingHandedIn', 'Nothing was handed in.') }}</strong>
        </dd>
        <template v-if="order.announce_conversation_id">
          <dt>{{ t('disputesView.v2.thread', 'Room thread') }}</dt>
          <dd><router-link :to="`/pocket/ourchat/${order.announce_conversation_id}`" class="dsp-ev__link">{{ t('disputesView.v2.openThread', 'Open the thread') }} →</router-link></dd>
        </template>
      </dl>
      <details v-if="order.spec" class="dsp-ev__block" open>
        <summary>{{ t('disputesView.v2.spec', 'The order\'s spec') }}</summary>
        <pre class="dsp-ev__pre">{{ order.spec }}</pre>
      </details>
      <details v-if="order.handed_in && order.deliverable" class="dsp-ev__block">
        <summary>{{ t('disputesView.v2.deliverable', 'What was handed in') }}</summary>
        <pre class="dsp-ev__pre">{{ deliverableText }}</pre>
      </details>
      <details v-if="order.events && order.events.length" class="dsp-ev__block">
        <summary>{{ tp('disputesView.v2.events', 'The order\'s events ({n})', { n: order.events.length }) }}</summary>
        <ol class="dsp-ev__events">
          <li v-for="e in order.events" :key="e.seq">
            <span class="dsp-ev__muted">{{ when(e.created_at) }}</span> · {{ e.event_type }}
            <span v-if="e.actor_did" class="dsp-ev__muted" :title="e.actor_did">· {{ actor(e.actor_did) }}</span>
          </li>
        </ol>
      </details>
    </template>
    <div v-else-if="contractRef" class="dsp-ev__head">
      <router-link :to="{ path: '/contracts', hash: `#contract-${contractRef}` }" class="dsp-ev__link" data-testid="dispute-contract-link">
        {{ tp('disputesView.v2.contract', 'Contract {ref}', { ref: contractRef }) }} →
      </router-link>
    </div>
    <p v-else class="dsp-ev__muted">{{ t('disputesView.v2.noLink', 'This dispute names no order or contract.') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import dayjs from 'dayjs'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import type { Dispute } from '@/services/api/disputes'

const props = defineProps<{ dispute: Dispute }>()
const { t, tp } = useI18n()

const order = computed(() => props.dispute.guild_order || null)
const contractRef = computed(() => props.dispute.contract_ref || (props.dispute.contract_id ? String(props.dispute.contract_id) : ''))
const deliverableText = computed(() => {
  const d: any = order.value?.deliverable
  if (!d) return ''
  if (typeof d === 'string') return d
  return d.text || d.summary || JSON.stringify(d, null, 2)
})

/** a ruler needs the hour, not only the day (item 21) */
function when(v?: string | null): string { return v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '—' }
function amount(v: any): string {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 6 }) : String(v ?? '')
}
function eta(s?: number | null): string {
  if (!s) return t('disputesView.v2.noEta', 'no time given')
  const h = Math.round(s / 3600)
  return h >= 48 ? tp('disputesView.v2.etaDays', '{n} days', { n: Math.round(h / 24) }) : tp('disputesView.v2.etaHours', '{n} hours', { n: h })
}
function actor(did: string): string {
  const p: any = props.dispute.parties
  if (p?.complainant?.did === did) return p.complainant.name || did
  if (p?.defendant?.did === did) return p.defendant.name || did
  return did === 'reaper' ? t('disputesView.v2.system', 'the system') : did.replace(/^did:[a-z0-9]+:/i, '').slice(0, 14)
}
</script>

<style scoped>
.dsp-ev { display: flex; flex-direction: column; gap: 10px; }
.dsp-ev__head { display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }
.dsp-ev__link { color: var(--drc-cyan, #22d3ee); text-decoration: underline; }
.dsp-ev__status { font-size: 12px; opacity: .75; text-transform: uppercase; letter-spacing: .04em; }
.dsp-ev__kv { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; margin: 0; }
.dsp-ev__kv dt { opacity: .7; }
.dsp-ev__kv dd { margin: 0; }
.dsp-ev__muted { opacity: .65; }
.dsp-ev__block summary { cursor: pointer; }
.dsp-ev__pre { white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; margin: 6px 0 0; font-size: 12px; }
.dsp-ev__events { margin: 6px 0 0; padding-left: 18px; font-size: 12px; }
</style>
