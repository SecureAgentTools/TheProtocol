<template>
  <div class="svc-res" :class="{ 'is-fail': isError }">
    <div class="svc-res-bar">
      <span class="svc-pill is-muted">{{ response.agent || svc.label }}</span>
      <span v-if="chargeAmount != null && !isError" class="svc-pill" data-testid="svc-res-charge">{{ chargeAmount }} {{ chargeCurrency }}</span>
      <span class="svc-pill" :class="isError ? 'is-danger' : (stateLabel === 'NOT SETTLED' ? 'is-warn' : 'is-ok')" data-testid="svc-res-state">{{ stateLabel }}</span>
      <span v-if="relayHost && !isError" class="svc-pill is-muted" data-testid="svc-res-relayed"
            :title="`Answered and paid by ${relayHost}, not by this frame`">via {{ relayHost }}</span>
      <span v-if="summary && !isError" class="svc-res-summary"><strong>{{ summary }}</strong></span>
    </div>
    <div class="svc-res-body">
      <div v-if="isError" class="svc-row" style="gap:.5rem;align-items:flex-start">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:16px;height:16px;color:var(--svc-danger);flex-shrink:0;margin-top:1px"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <span style="font-size:.76rem;color:var(--svc-danger)">{{ response.error }}</span>
      </div>
      <component v-else :is="renderer" :data="payload" :svc="svc" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useCurrency } from '@/composables/useCurrency'
import WeatherResult from './results/WeatherResult.vue'
import CurrencyResult from './results/CurrencyResult.vue'
import SslResult from './results/SslResult.vue'
import IpResult from './results/IpResult.vue'
import PasswordResult from './results/PasswordResult.vue'
import CronResult from './results/CronResult.vue'
import UnitResult from './results/UnitResult.vue'
import TextResult from './results/TextResult.vue'
import TimezoneResult from './results/TimezoneResult.vue'
import NewsResult from './results/NewsResult.vue'
import ConverterResult from './results/ConverterResult.vue'
import JsonResult from './results/JsonResult.vue'

const props = defineProps<{ svc: any; response: any }>()
const { localCurrency } = useCurrency()

const isError = computed(() => !!props.response?.error)
// `result` is the showcase payload. Envelope-aware: post-migration it is
// { schema_version, summary, display, data, meta }; pre-migration it is the raw
// report object. Detect the envelope by the presence of a `display` key.
const env = computed(() => props.response?.result ?? {})
const isEnvelope = computed(() => env.value && typeof env.value === 'object' && typeof env.value.display === 'string')
const summary = computed(() => (isEnvelope.value ? env.value.summary : '') || '')
const payload = computed(() => (isEnvelope.value && 'data' in env.value ? env.value.data : env.value))
const displayKey = computed(() => (isEnvelope.value ? env.value.display : props.svc?.display) || 'json')
// §MCPTEST30 (V0641, D6-831): SETTLED only when the call's payment settled (its own `paid`), never from the task's
// state. A sandbox page read "WeatherAgent 0.5 SBXA SETTLED" for a call its frame never paid: the frame had no payer,
// the agent answered 402, and the answer came from the frame the call was relayed to.
const stateLabel = computed(() => {
  if (isError.value) return 'FAILED'
  const r = props.response || {}
  if (r.paid === true) return 'SETTLED'
  const ps = String(r.payment_status || '')
  if (ps && ps !== 'no_payment_token' && ps !== 'not_attempted') return 'NOT SETTLED'
  return 'DONE'
})
// What the call was charged, in the unit it was charged in (a relayed answer is charged by the frame that answered;
// the local label put that frame's number under this frame's unit)
const chargeAmount = computed(() => props.response?.charged_amount ?? props.response?.price_avt ?? null)
const chargeCurrency = computed(() => props.response?.charged_currency || localCurrency.value)
const relayHost = computed(() => {
  const u = props.response?.relayed_from
  if (!u) return ''
  try { return new URL(String(u)).hostname } catch { return String(u) }
})

const RENDERERS: Record<string, any> = {
  weather: WeatherResult, currency: CurrencyResult, ssl: SslResult, ip: IpResult,
  password: PasswordResult, cron: CronResult, unit: UnitResult, text: TextResult,
  timezone: TimezoneResult, news: NewsResult, converter: ConverterResult, json: JsonResult,
}
const renderer = computed(() => RENDERERS[displayKey.value] || JsonResult)
</script>
