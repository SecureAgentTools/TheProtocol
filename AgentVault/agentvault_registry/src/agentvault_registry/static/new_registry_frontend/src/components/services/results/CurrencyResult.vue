<template>
  <div v-if="conv">
    <div style="text-align:center;margin-bottom:.7rem">
      <div class="svc-faint" style="font-size:.74rem">{{ fmt(conv.amount_from) }} {{ conv.base_currency }}</div>
      <div style="font-size:2rem;font-weight:800;color:#fff;margin:.2rem 0;line-height:1.05">{{ fmt(conv.amount_to) }} <span style="font-size:1rem;color:var(--svc);font-weight:700">{{ conv.target_currency }}</span></div>
      <div class="svc-faint" style="font-size:.68rem">1 {{ conv.base_currency }} = {{ conv.exchange_rate }} {{ conv.target_currency }}</div>
    </div>
    <div class="svc-kv">
      <div class="svc-kv-row"><span class="svc-k">Exchange rate</span><span class="svc-v is-mono">{{ conv.exchange_rate }}</span></div>
      <div class="svc-kv-row" v-if="conv.rate_date"><span class="svc-k">As of</span><span class="svc-v">{{ conv.rate_date }}</span></div>
      <div class="svc-kv-row" v-if="conv.source"><span class="svc-k">Source</span><span class="svc-v">{{ conv.source }}</span></div>
    </div>
  </div>
  <div v-else-if="coins.length">
    <div class="svc-kv">
      <div v-for="(c, i) in coins" :key="i" class="svc-kv-row">
        <span class="svc-k" style="text-transform:capitalize">{{ c.id || c.name || c.symbol || 'coin' }}</span>
        <span class="svc-v is-mono">
          {{ price(c) }}
          <span v-if="chg(c) != null" :style="{ color: chg(c) >= 0 ? 'var(--svc-ok)' : 'var(--svc-danger)', marginLeft: '.4rem' }">{{ chg(c) >= 0 ? '+' : '' }}{{ chg(c).toFixed(2) }}%</span>
        </span>
      </div>
    </div>
    <div v-if="data.source" class="svc-faint" style="font-size:.62rem;margin-top:.5rem">Source: {{ data.source }}</div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed } from 'vue'
import JsonResult from './JsonResult.vue'
const props = defineProps<{ data: any }>()
const conv = computed(() => (props.data?.exchange_rate != null ? props.data : null))
const coins = computed(() => (Array.isArray(props.data?.coins) ? props.data.coins : []))
const fmt = (n: any) => { const x = Number(n); return isFinite(x) ? x.toLocaleString(appLocale(), { maximumFractionDigits: 4 }) : n }
function price(c: any) {
  const v = c.usd ?? c.price ?? c.value ?? (c.prices && (c.prices.usd ?? Object.values(c.prices)[0]))
  return v != null ? `$${fmt(v)}` : '—'
}
function chg(c: any): number | null {
  const v = c.usd_24h_change ?? c.change_24h ?? c.change
  const n = Number(v)
  return isFinite(n) ? n : null
}
</script>
