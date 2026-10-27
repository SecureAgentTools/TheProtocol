<!--
  §FOREIGNACT (2026-08-24) — say where a money action is actually going to land.

  Acting as an agent homed on another registry is a real, kept feature: the api
  client sends every agent-tier call to that agent's own registry, because the
  agent JWT was minted there. What was missing is that nothing on screen said so.
  The Commander staked "1.337" from the frame-c surface as an agent homed on
  registry-a and locked 1337.000000 AVT there, while the page said BVT.

  Renders NOTHING for a local agent. A notice that appears on every action is a
  notice nobody reads; this one appears exactly when the action leaves the
  registry you are looking at.
-->
<template>
  <div v-if="isForeign" class="acn" :class="{ 'acn--strong': strong }" data-testid="acting-notice">
    <Icon name="mdi:bank-transfer" class="acn-icon" aria-hidden="true" />
    <span class="acn-text">
      <template v-if="actingCurrency">
        {{ tp('acting.notice',
              'Runs on {where} and settles in {ccy}, not {local}.',
              { where: actingRegistryName, ccy: actingCurrency, local: String(localCurrency) }) }}
      </template>
      <template v-else>
        {{ tp('acting.noticeUnknown',
              'Runs on {where}, not on the registry you are viewing. Its currency could not be read.',
              { where: actingRegistryName }) }}
      </template>
      <span class="acn-host">{{ actingHost }}</span>
    </span>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useActingContext } from '@/composables/useActingContext'

/** `strong` = a money moment (a confirm button sits next to it), not a header hint. */
defineProps<{ strong?: boolean }>()

const { tp } = useI18n() as any
const {
  isForeign, actingCurrency, actingRegistryName, actingHost, localCurrency,
} = useActingContext()
</script>

<style scoped>
.acn {
  display: flex; align-items: flex-start; gap: 0.4rem;
  margin: 0.45rem 0; padding: 0.4rem 0.55rem; border-radius: 0.35rem;
  font-size: 0.72rem; line-height: 1.45;
  border: 1px solid rgba(246, 196, 83, 0.32);
  background: rgba(246, 196, 83, 0.08);
  color: #f6c453;
}
.acn--strong { font-weight: 600; border-color: rgba(246, 196, 83, 0.55); background: rgba(246, 196, 83, 0.14); }
.acn-icon { flex: 0 0 auto; width: 14px; height: 14px; margin-top: 0.1rem; }
.acn-text { min-width: 0; }
.acn-host { opacity: 0.72; margin-left: 0.3rem; word-break: break-all; }
</style>
