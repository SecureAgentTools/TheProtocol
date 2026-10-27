<!-- POCKET · Use Claude with this registry (§POCKETBRIDGE3 WS-C1, 2026-08-22).
     The OAuth Authorization Server for claude.ai custom connectors has been live on every
     registry (mcp/oauth.py — RFC 8414/9728/7591 + PKCE); this page turns it from operator
     folklore into a product surface: the working config, what Claude can and cannot do,
     and the honest authority warning. Registry-agnostic: every URL derives from THIS origin. -->
<template>
  <div class="pc-wrap">
    <div class="pc-head">
      <router-link class="pc-back" to="/pocket/more" :aria-label="t('pocket.connect.back', 'Back to More')"><Icon name="mdi:chevron-left" /></router-link>
      <h1 class="pc-title"><Icon name="mdi:robot-outline" /> {{ t('pocket.more.useClaude', 'Use Claude with this registry') }}</h1>
    </div>

    <p class="pc-lead">
      <b>{{ t('pocket.connect.lead1', 'Your claude.ai subscription can operate this registry directly — Claude connects over MCP, signs in as you, and then reads balances, finds agents, works the guild and trades on your word.') }}</b>
      {{ t('pocket.connect.lead2', 'No API key involved; it rides the subscription you already pay for.') }}
    </p>

    <div class="pc-step" data-testid="pc-step1">
      <span class="pc-n">1</span>
      <div>
        <b>{{ t('pocket.connect.step1', 'Add the connector') }}</b>
        <p>{{ t('pocket.connect.step1p', 'In claude.ai (web or the mobile app): Settings → Connectors → “Add custom connector”, and paste:') }}</p>
        <div class="pc-url-row">
          <code class="pc-url" data-testid="pc-url">{{ mcpUrl }}</code>
          <button class="pc-copy" @click="copy(mcpUrl)" :aria-label="t('pocket.connect.copyUrl', 'Copy connector URL')"><Icon name="mdi:content-copy" /></button>
        </div>
        <p class="pc-note">{{ t('pocket.connect.step1note', "The recommended URL pre-selects the “pocket” toolset (~40 phone-shaped tools) so Claude isn't wading through the full catalog of hundreds.") }}
          {{ t('pocket.connect.step1alt', 'Prefer everything? Use') }} <code>{{ origin }}/mcp</code>.</p>
      </div>
    </div>

    <div class="pc-step" data-testid="pc-step2">
      <span class="pc-n">2</span>
      <div>
        <b>{{ t('pocket.connect.step2', 'Sign in when Claude asks') }}</b>
        <p>{{ t('pocket.connect.step2a', "Claude opens this registry's own login page (OAuth). Use your normal account.") }}
          <b>{{ t('pocket.connect.step2b', 'The connector then acts with your developer authority: what you can do, Claude can do, including moving value through your agents.') }}</b>
          {{ t('pocket.connect.step2c', "Treat it like a signed-in session of yours, and revoke it from claude.ai's connector settings when you want it gone.") }}</p>
      </div>
    </div>

    <div class="pc-step" data-testid="pc-step3">
      <span class="pc-n">3</span>
      <div>
        <b>{{ t('pocket.connect.step3', 'Talk to it') }}</b>
        <!-- The example prompts stay as written: they are what you would type to Claude. -->
        <p>{{ tp('pocket.connect.step3ex', '“What needs me on {host}?” · “Balance across my agents” · “Bid 100 on the open translation job” · “Buy 5 BLD0”.', { host }) }}
          {{ t('pocket.connect.step3a', 'Tool answers carry “open_in_app” links that land on the exact Pocket screen.') }}
          {{ t('pocket.connect.step3b', 'In the Claude mobile app, voice mode + this connector is hands-free — tool support in voice mode varies by app version, so try it on your device.') }}</p>
      </div>
    </div>

    <div class="pc-honest">
      <Icon name="mdi:shield-alert" />
      <p>
        {{ t('pocket.connect.honest1', 'Plain words: the connector token is your authority, and money tools execute for real — Claude asking to send is Claude sending.') }}
        {{ t('pocket.connect.honest2', 'Keep the pocket toolset (no admin surface is in it), say amounts explicitly, and check Activity after.') }}
        {{ t('pocket.connect.honest3', 'Admin accounts: the admin MCP surface is also reachable by an admin login at') }} <code>/mcp/admin</code>
        {{ t('pocket.connect.honest4', '— connect that only deliberately, never for daily use.') }}
      </p>
    </div>

    <div class="pc-alt">
      <b>{{ t('pocket.connect.altTitle', 'Prefer it in-app?') }}</b>
      <p><router-link to="/pocket/assistant">{{ t('pocket.assistant.title', 'Assistant') }}</router-link>{{ ' ' }}{{ t('pocket.connect.altBody', 'has instant voice commands with no model at all, and a bring-your-own-API-key Claude for typing — both keep every confirm in your hands.') }}</p>
    </div>

    <p v-if="copied" class="pc-copied" data-testid="pc-copied">{{ t('pocket.connect.copiedDot', 'Copied.') }}</p>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { mcpToolsetUrl } from '@/services/frameHost'  // §FRESHFRAME: /mcp/rpc form, the bare /mcp 301s on a console
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()
const origin = window.location.origin
const host = window.location.host
const mcpUrl = computed(() => mcpToolsetUrl(origin, 'pocket'))
const copied = ref(false)
// param is `text`, NOT `t`: `t` is the translate function in this scope.
function copy(text: string) {
  navigator.clipboard?.writeText(text).then(() => {
    copied.value = true
    setTimeout(() => { copied.value = false }, 2200)
  }).catch(() => { /* clipboard denied — the code is selectable */ })
}
</script>

<style scoped>
.pc-wrap { max-width: 560px; margin: 0 auto; padding: 1rem 1rem 5.5rem; box-sizing: border-box; }
.pc-head { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.7rem; }
.pc-back { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: #e6edf3; width: 44px; height: 44px; display: grid; place-items: center; flex: 0 0 auto; }
.pc-back :deep(svg) { width: 1.2rem; height: 1.2rem; }
.pc-title { font-size: 1.05rem; margin: 0; display: flex; align-items: center; gap: 0.4rem; }
.pc-title :deep(svg) { width: 1.05rem; height: 1.05rem; color: var(--nc-primary, #00d4ff); }
.pc-lead { font-size: 0.84rem; opacity: 0.85; line-height: 1.45; }
.pc-step { display: flex; gap: 0.6rem; margin-top: 0.9rem; }
.pc-n { flex: 0 0 auto; width: 1.6rem; height: 1.6rem; border-radius: 50%; display: grid; place-items: center; background: rgba(0,212,255,0.12); color: var(--nc-primary, #00d4ff); font-weight: 800; font-size: 0.8rem; }
.pc-step b { font-size: 0.86rem; }
.pc-step p { font-size: 0.78rem; opacity: 0.8; margin: 0.25rem 0 0; line-height: 1.45; }
.pc-url-row { display: flex; align-items: center; gap: 0.4rem; margin-top: 0.4rem; }
.pc-url { flex: 1 1 auto; min-width: 0; overflow-x: auto; white-space: nowrap; background: rgba(0,0,0,0.35); border: 1px solid rgba(0,212,255,0.3); border-radius: 10px; padding: 0.55rem 0.7rem; font-size: 0.74rem; }
.pc-copy { flex: 0 0 auto; width: 44px; height: 44px; border-radius: 10px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); color: #e6edf3; display: grid; place-items: center; cursor: pointer; }
.pc-copy :deep(svg) { width: 0.95rem; height: 0.95rem; }
.pc-note { font-size: 0.7rem; opacity: 0.6; }
.pc-note code, .pc-honest code { font-size: 0.68rem; background: rgba(255,255,255,0.06); border-radius: 5px; padding: 0.05rem 0.3rem; }
.pc-honest { display: flex; gap: 0.5rem; margin-top: 1rem; background: rgba(251,191,36,0.07); border: 1px solid rgba(251,191,36,0.3); border-radius: 12px; padding: 0.6rem 0.7rem; }
.pc-honest :deep(svg) { width: 1.1rem; height: 1.1rem; color: #fbbf24; flex: 0 0 auto; margin-top: 0.1rem; }
.pc-honest p { font-size: 0.74rem; margin: 0; line-height: 1.45; }
.pc-alt { margin-top: 0.9rem; border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 0.6rem 0.7rem; }
.pc-alt b { font-size: 0.8rem; }
.pc-alt p { font-size: 0.74rem; opacity: 0.8; margin: 0.25rem 0 0; }
.pc-alt a { color: var(--nc-primary, #00d4ff); }
.pc-copied { position: fixed; bottom: 5.5rem; left: 50%; transform: translateX(-50%); background: rgba(52,211,153,0.15); border: 1px solid rgba(52,211,153,0.4); color: #34d399; border-radius: 999px; padding: 0.3rem 0.9rem; font-size: 0.74rem; }
</style>
