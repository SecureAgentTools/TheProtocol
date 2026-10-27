<!--
  AuthShell.vue — cohesive branded chrome for every auth screen.
  Renders: ambient cyberpunk backdrop · ProtocolMark + THE PROTOCOL wordmark +
  contextual tagline · slotted card · system-status footer.

  The card content is provided via the default slot (kept per-view so each
  screen owns its own form logic). All styling lives in auth-shell.css, scoped
  under `.nc-auth-page` so it only touches auth pages.

  Props:
    tagline  — small caps line under the wordmark (per-screen context)
    status   — system-status footer text
    maxWidth — card column width in px (420 default; 480 for Register)
  Slots:
    #mark    — override the brand mark (defaults to ProtocolMark)
    default  — the auth card
-->
<template>
  <div class="nc-auth-page" :style="{ '--auth-col': maxWidth + 'px' }">
    <div class="nc-bg-effects" aria-hidden="true">
      <div class="nc-grid-overlay"></div>
      <div class="nc-scan"></div>
      <div class="nc-glow nc-glow-1"></div>
      <div class="nc-glow nc-glow-2"></div>
      <div class="nc-glow nc-glow-3"></div>
    </div>

    <div class="nc-auth-container">
      <div class="auth-brand">
        <div class="auth-mark">
          <slot name="mark"><ProtocolMark :size="86" alive /></slot>
        </div>
        <h1 class="auth-wordmark">THE PROTOCOL</h1>
        <div v-if="tagline" class="auth-tagline">{{ tagline }}</div>
      </div>

      <slot />

      <div v-if="status" class="nc-system-status">
        <div class="nc-status-item">
          <span class="nc-status-dot online"></span>
          <span class="nc-status-text">{{ status }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import ProtocolMark from '@/components/ProtocolMark.vue'

withDefaults(defineProps<{
  tagline?: string
  status?: string
  maxWidth?: number
}>(), {
  status: '',
  maxWidth: 420,
})
</script>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
@import '@/assets/styles/auth-shell.css';
</style>
