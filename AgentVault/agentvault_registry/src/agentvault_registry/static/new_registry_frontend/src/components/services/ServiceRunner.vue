<template>
  <div>
    <p v-if="svc.hint" class="svc-faint" style="font-size:.66rem;margin:0 0 .55rem">{{ svc.hint }}</p>

    <div v-if="svc.chips.length" class="svc-chips" style="margin-bottom:.6rem">
      <button v-for="c in svc.chips" :key="c" class="svc-chip" :class="{ 'is-on': svc.value === c }" @click="svc.value = c">{{ c }}</button>
    </div>

    <textarea v-if="svc.textarea" class="svc-field" v-model="svc.value" :placeholder="svc.placeholder" rows="3"></textarea>
    <input v-else class="svc-field" v-model="svc.value" :placeholder="svc.placeholder" @keyup.enter="!unavailable && $emit('run')" />

    <select v-if="svc.extra" class="svc-field" style="margin-top:.5rem" v-model="svc.extra.value" :aria-label="t('services.optionAria', 'Option')">
      <option v-for="o in svc.extra.options" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>

    <button class="svc-btn" style="width:100%;margin-top:.65rem" :disabled="!!unavailable || loading || !svc.value || !svc.value.trim()" @click="$emit('run')">
      <span v-if="loading" class="svc-spin"></span>
      {{ loading ? t('servicesShowcaseView.processing') : actionLabel }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import type { ShowcaseService } from '@/composables/useShowcaseServices'

const props = defineProps<{ svc: ShowcaseService; loading: boolean; unavailable?: string | null }>()
defineEmits<{ (e: 'run'): void }>()
const { t } = useI18n()

const ACTIONS: Record<string, string> = {
  weather: 'Get Weather', currency: 'Convert', ssl: 'Check Site', timezone: 'Get Time',
  unit: 'Convert', news: 'Get Headlines', ip: 'Lookup', cron: 'Generate',
  password: 'Generate', text: 'Analyze', converter: 'Convert',
}
const actionLabel = computed(() => ACTIONS[props.svc.display] || 'Run')
</script>
