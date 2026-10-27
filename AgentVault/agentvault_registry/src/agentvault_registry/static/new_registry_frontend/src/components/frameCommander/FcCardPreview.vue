<template>
  <article class="fcp" :class="'fcp--' + draft.theme" data-testid="fc-preview" :aria-label="t('frameCommanderView.preview.aria', 'Preview of your registry card')">
    <div class="fcp-eyebrow">
      <span class="fcp-live" aria-hidden="true" />
      {{ t('frameCommanderView.preview.eyebrow', 'Your registry card, as it takes shape') }}
    </div>

    <header class="fcp-head">
      <svg class="fcp-mark" viewBox="0 0 64 64" aria-hidden="true">
        <path class="fcp-mark-a" d="M8 24 32 10l24 14v9L32 19 8 33z" />
        <path class="fcp-mark-b" d="M8 40 32 26l24 14v9L32 35 8 49z" />
      </svg>
      <div class="fcp-id">
        <h3 class="fcp-name" data-testid="fc-preview-name">{{ draft.display_name.trim() || t('frameCommanderView.preview.unnamed', 'Your frame') }}</h3>
        <p class="fcp-host">{{ host || t('frameCommanderView.preview.noAddress', 'The address follows the name') }}</p>
      </div>
      <span class="fcp-posture" :class="'is-' + draft.posture">{{ postureText }}</span>
    </header>

    <p class="fcp-desc" :class="{ 'is-empty': !draft.description.trim() }">
      {{ draft.description.trim() || t('frameCommanderView.preview.noDescription', 'The sentence people read about your frame appears here.') }}
    </p>

    <dl class="fcp-facts">
      <div class="fcp-fact">
        <dt>{{ t('frameCommanderView.preview.currency', 'Currency') }}</dt>
        <dd>
          <strong class="fcp-ticker">{{ draft.ticker || '···' }}</strong>
          <span v-if="draft.currency_name.trim()" class="fcp-sub">{{ draft.currency_name.trim() }}</span>
        </dd>
      </div>
      <div class="fcp-fact">
        <dt>{{ t('frameCommanderView.preview.mint', 'Genesis issuance') }}</dt>
        <dd>{{ mintText }}</dd>
      </div>
      <div class="fcp-fact">
        <dt>{{ t('frameCommanderView.preview.place', 'Place') }}</dt>
        <dd>{{ draft.location.trim() || t('frameCommanderView.preview.notSet', 'Not set') }}</dd>
      </div>
      <div class="fcp-fact">
        <dt>{{ t('frameCommanderView.preview.network', 'Network') }}</dt>
        <dd>{{ intentText }}</dd>
      </div>
    </dl>

    <div v-if="draft.tags.length" class="fcp-tags">
      <span v-for="tag in draft.tags" :key="tag" class="fcp-tag">{{ tag }}</span>
    </div>

    <div v-if="draft.intent === 'federate_later' && draft.partners.length" class="fcp-partners">
      <Icon name="mdi:connection" class="fcp-partners-icon" />
      <span v-for="p in draft.partners" :key="p" class="fcp-partner">{{ p }}</span>
    </div>

    <footer class="fcp-foot">
      <span class="fcp-foot-item">
        <Icon name="mdi:shield-check" class="fcp-foot-icon" />
        <span class="fcp-mono">{{ addresses ? addresses.trustDomain : t('frameCommanderView.preview.noTrustDomain', 'Trust domain pending') }}</span>
      </span>
      <span class="fcp-foot-item">
        <Icon name="mdi:tune-variant" class="fcp-foot-icon" />
        {{ switchesText }}
      </span>
    </footer>
  </article>
</template>

<script setup lang="ts">
/**
 * A live preview of the registry card the requested frame will publish: name, address, colour, currency, place,
 * network and tags, redrawn as the draft changes. It shows the answers, never a promise about review.
 */
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { type FrameAddresses, type FrameRequestDraft, wholeNumber } from '@/services/frameRequestForm'

const props = defineProps<{ draft: FrameRequestDraft; addresses: FrameAddresses | null; changedCount: number }>()

const { t, tp } = useI18n()

const host = computed(() => {
  if (!props.addresses) return ''
  try {
    return new URL(props.addresses.console).host
  } catch {
    return ''
  }
})

const mintText = computed(() => {
  const n = wholeNumber(props.draft.mint)
  if (n === null) return t('frameCommanderView.preview.notSet', 'Not set')
  const amount = new Intl.NumberFormat(appLocale()).format(n)
  return props.draft.ticker ? amount + ' ' + props.draft.ticker : amount
})

const postureText = computed(() => props.draft.posture === 'production'
  ? t('frameCommanderView.preview.production', 'Production')
  : t('frameCommanderView.preview.pilot', 'Pilot'))

const intentText = computed(() => {
  if (props.draft.intent === 'standalone') return t('frameCommanderView.preview.standalone', 'Standalone')
  if (props.draft.intent === 'standalone_test_operator') return t('frameCommanderView.preview.testOperator', 'Standalone, with a test operator')
  const n = props.draft.partners.length
  if (n === 0) return t('frameCommanderView.preview.federateLater', 'Federates later')
  if (n === 1) return t('frameCommanderView.preview.federateOne', 'Federates with one frame')
  return tp('frameCommanderView.preview.federateMany', 'Federates with {n} frames', { n })
})

const switchesText = computed(() => {
  const n = props.changedCount
  if (n === 0) return t('frameCommanderView.preview.defaults', 'Default settings')
  if (n === 1) return t('frameCommanderView.preview.changedOne', 'One setting changed')
  return tp('frameCommanderView.preview.changedMany', '{n} settings changed', { n })
})
</script>

<style scoped>
.fcp {
  --pv-rgb: 0, 210, 210;
  position: relative; overflow: hidden;
  display: flex; flex-direction: column; gap: 14px;
  padding: 18px 18px 16px; border-radius: 14px;
  background:
    radial-gradient(120% 90% at 100% 0%, rgba(var(--pv-rgb), 0.16), transparent 55%),
    linear-gradient(168deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 60%),
    rgba(8, 11, 20, 0.72);
  border: 1px solid rgba(var(--pv-rgb), 0.3);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04), 0 18px 40px -26px rgba(var(--pv-rgb), 0.55);
  backdrop-filter: blur(9px) saturate(1.05);
  transition: border-color 0.3s, box-shadow 0.3s;
}
.fcp--sovereign { --pv-rgb: 220, 38, 38; }
.fcp-eyebrow {
  display: flex; align-items: center; gap: 7px;
  font-family: var(--mono, ui-monospace, monospace); font-size: 10px; font-weight: 700;
  letter-spacing: 0.14em; text-transform: uppercase; color: rgba(var(--pv-rgb), 0.9);
}
.fcp-live { width: 6px; height: 6px; border-radius: 50%; background: rgb(var(--pv-rgb)); box-shadow: 0 0 8px rgb(var(--pv-rgb)); animation: fcp-pulse 2.4s ease-in-out infinite; }
@keyframes fcp-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
@media (prefers-reduced-motion: reduce) { .fcp-live { animation: none; } }

.fcp-head { display: flex; align-items: center; gap: 12px; }
.fcp-mark { width: 44px; height: 44px; flex: 0 0 auto; filter: drop-shadow(0 0 10px rgba(var(--pv-rgb), 0.45)); }
.fcp-mark-a { fill: rgb(var(--pv-rgb)); }
.fcp-mark-b { fill: rgba(var(--pv-rgb), 0.55); }
.fcp-id { min-width: 0; flex: 1; }
.fcp-name { margin: 0; font-size: 18px; font-weight: 700; color: #fff; line-height: 1.2; overflow-wrap: anywhere; }
.fcp-host { margin: 3px 0 0; font-family: var(--mono, ui-monospace, monospace); font-size: 11px; color: var(--muted, #7d8594); overflow-wrap: anywhere; }
.fcp-posture {
  flex: 0 0 auto; align-self: flex-start;
  padding: 3px 8px; border-radius: 5px;
  font-family: var(--mono, ui-monospace, monospace); font-size: 9px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
}
.fcp-posture.is-pilot { color: #f59e0b; background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); }
.fcp-posture.is-production { color: #10b981; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.3); }

.fcp-desc { margin: 0; font-size: 13px; line-height: 1.55; color: var(--text-secondary, #b8c0cc); overflow-wrap: anywhere; }
.fcp-desc.is-empty { color: var(--muted, #7d8594); font-style: italic; }

.fcp-facts { margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.fcp-fact {
  min-width: 0; padding: 8px 10px; border-radius: 8px;
  background: rgba(var(--pv-rgb), 0.05); border: 1px solid rgba(var(--pv-rgb), 0.12);
}
.fcp-fact dt { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted, #7d8594); }
.fcp-fact dd { margin: 3px 0 0; font-size: 13px; color: var(--text, #e6e9ef); overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.fcp-ticker { font-family: var(--mono, ui-monospace, monospace); color: rgb(var(--pv-rgb)); letter-spacing: 0.04em; }
.fcp-sub { display: block; font-size: 11px; color: var(--muted, #7d8594); }

.fcp-tags, .fcp-partners { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.fcp-tag {
  padding: 2px 8px; border-radius: 10px; font-size: 11px;
  color: var(--text-secondary, #b8c0cc); background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.08);
}
.fcp-partners-icon { font-size: 15px; color: rgb(var(--pv-rgb)); }
.fcp-partner {
  padding: 2px 8px; border-radius: 5px; font-family: var(--mono, ui-monospace, monospace); font-size: 11px;
  color: rgb(var(--pv-rgb)); background: rgba(var(--pv-rgb), 0.1); border: 1px solid rgba(var(--pv-rgb), 0.25);
}

.fcp-foot {
  display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 12px;
  padding-top: 12px; border-top: 1px dashed rgba(var(--pv-rgb), 0.2);
  font-size: 11px; color: var(--muted, #7d8594);
}
.fcp-foot-item { display: inline-flex; align-items: center; gap: 5px; min-width: 0; }
.fcp-foot-icon { font-size: 14px; color: rgba(var(--pv-rgb), 0.85); flex: 0 0 auto; }
.fcp-mono { font-family: var(--mono, ui-monospace, monospace); overflow-wrap: anywhere; }
</style>
