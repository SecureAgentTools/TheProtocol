<template>
  <div v-if="data && (data.result != null)">
    <div style="text-align:center;margin-bottom:.65rem">
      <div class="svc-faint" style="font-size:.8rem">{{ fmt(data.value) }} {{ data.from || data.from_unit }}</div>
      <div style="font-size:2rem;font-weight:800;color:#fff;margin:.15rem 0;line-height:1.05">{{ fmt(data.result) }} <span style="font-size:1rem;color:var(--svc);font-weight:700">{{ data.to || data.to_unit }}</span></div>
    </div>
    <div class="svc-kv">
      <div class="svc-kv-row" v-if="data.formula"><span class="svc-k">Formula</span><span class="svc-v is-mono">{{ data.formula }}</span></div>
      <div class="svc-kv-row" v-if="data.category"><span class="svc-k">Category</span><span class="svc-v" style="text-transform:capitalize">{{ data.category }}</span></div>
    </div>
  </div>
  <JsonResult v-else :data="data" />
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import JsonResult from './JsonResult.vue'
defineProps<{ data: any }>()
const fmt = (n: any) => { const x = Number(n); return isFinite(x) ? x.toLocaleString(appLocale(), { maximumFractionDigits: 6 }) : n }
</script>
