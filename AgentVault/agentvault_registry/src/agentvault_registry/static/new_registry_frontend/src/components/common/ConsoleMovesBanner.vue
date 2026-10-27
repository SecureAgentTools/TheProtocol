<script setup lang="ts">
// §FEFRAME W4 (V0507) — one console host per frame.
//
// A frame's console answered on several hosts (EU: the apex, api., eu., registry.), and a browser keeps a sign-in and
// the saved agent credentials PER HOST: four addresses were four separate consoles to the person using them. The frame
// manifest names the console's one address (`self.console_url`); on any other host this banner says so, offers the
// saved credentials as a file in the importer's own shape (vault v2, secrets included: they are what moves), and links
// to the same page on the canonical console. A later release turns the alias hosts' UI paths into redirects (their
// /api, /.well-known, /mcp, /ws, /static and /assets stay where they are). Never on a loopback address (a developer's
// own access); dismissed for the browser session.
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useFrameManifest } from '@/composables/useFrameManifest'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { exportVaultV2 } from '@/services/credImport'
import { consoleLink } from '@/services/frameManifest'

const fm = useFrameManifest()
const route = useRoute()
const KEY = 'tp_console_moves_dismissed'
const dismissed = ref(false)
try { dismissed.value = sessionStorage.getItem(KEY) === '1' } catch { /* storage blocked: shown */ }

const canonical = computed<string | null>(() => {
  const u = fm.self.value?.console_url
  try { return u ? new URL(u).origin : null } catch { return null }
})
const isLoopback = (h: string) => h === 'localhost' || h === '::1' || h === '[::1]' || /^127\./.test(h)
const here = typeof window !== 'undefined' ? window.location : null
const show = computed(() => !dismissed.value && !!canonical.value && !!here
  && here.origin !== canonical.value && !isLoopback(here.hostname))
const target = computed(() => consoleLink(fm.self.value, route.fullPath) || canonical.value || '')
const saved = computed(() => (show.value ? Object.values(agentCredentialsStore.getAllCredentials()) : []))

function dismiss() {
  dismissed.value = true
  try { sessionStorage.setItem(KEY, '1') } catch { /* fine: gone for this view */ }
}

function download() {
  const me = fm.self.value
  const v = exportVaultV2(saved.value, me ? [{ key: me.key, name: me.display_name, url: me.public_url || me.console_url }] : [], true)
  const blob = new Blob([JSON.stringify(v, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `theprotocol-vault-${here?.hostname || 'console'}.json`
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>

<template>
  <div v-if="show" class="cmb" role="status" data-testid="console-moves">
    <div class="cmb-inner">
      <span class="cmb-badge">MOVES</span>
      <span class="cmb-text">
        This console's address is <a class="cmb-link" :href="target" data-testid="console-moves-go">{{ canonical }}</a>.
        A browser keeps sign-ins and saved agent credentials per address, so this one is separate from it.
        <template v-if="saved.length">
          Download your {{ saved.length }} saved credential{{ saved.length === 1 ? '' : 's' }} (the file holds their secrets:
          import it there, then delete it).
        </template>
      </span>
      <button v-if="saved.length" class="cmb-btn" type="button" data-testid="console-moves-download" @click="download">Download</button>
      <button class="cmb-x" type="button" aria-label="Dismiss" @click="dismiss">&times;</button>
    </div>
  </div>
</template>

<style scoped>
.cmb {
  position: sticky; top: 0; z-index: 9998;
  background: linear-gradient(90deg, rgba(56, 189, 248, 0.12), rgba(56, 189, 248, 0.05));
  border-bottom: 1px solid rgba(56, 189, 248, 0.28);
}
.cmb-inner {
  max-width: 1200px; margin: 0 auto 0 var(--nc-shell-inset, auto); padding: 8px 16px;
  display: flex; align-items: center; gap: 10px; font-size: 0.78rem; flex-wrap: wrap;
}
.cmb-badge {
  flex-shrink: 0; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 0.66rem; letter-spacing: 1.5px;
  color: #38bdf8; background: rgba(56, 189, 248, 0.16); border: 1px solid rgba(56, 189, 248, 0.4);
}
.cmb-text { color: #9fd8ef; line-height: 1.4; flex: 1 1 18rem; min-width: 0; overflow-wrap: anywhere; }
.cmb-link { color: #e0f6ff; text-decoration: underline; }
.cmb-btn {
  flex-shrink: 0; padding: 4px 10px; border-radius: 5px; cursor: pointer; font-size: 0.72rem; font-weight: 700;
  color: #38bdf8; background: rgba(56, 189, 248, 0.1); border: 1px solid rgba(56, 189, 248, 0.45);
}
.cmb-x { flex-shrink: 0; background: transparent; border: 0; color: #9fd8ef; font-size: 1.1rem; cursor: pointer; line-height: 1; }
</style>
