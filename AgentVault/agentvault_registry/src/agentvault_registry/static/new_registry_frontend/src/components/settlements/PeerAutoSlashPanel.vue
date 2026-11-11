<template>
  <!-- V0658 (k): each peer's automatic slashing, admin only (PUT /federation/disputes/peer-slash-config/{peer_id},
       admin_enforcement): whether a slash request from that peer is taken without an administrator, and up to what
       amount. The settings and their writes are the settlements store's, shared with the settlements overview. -->
  <section class="pa" data-testid="peer-auto-slash">
    <header class="pa-head">
      <h2 class="pa-title">{{ t('adminSettlementsView.peerSlash.title', 'Slash requests from each peer') }}</h2>
      <p class="pa-lead">{{ t('adminSettlementsView.peerSlash.lead', 'A request from a peer with automatic slashing on, up to its amount, is taken at once in the slash order above; any other request waits here for an administrator.') }}</p>
    </header>

    <p v-if="store.peerConfigError" class="pa-err" role="alert" data-testid="peer-auto-slash-read-failed">
      {{ t('adminSettlementsView.peerSlash.readFailed', 'The peers\' settings could not be read just now.') }}
      <button type="button" class="pa-btn" @click="store.fetchPeerConfigs()">{{ t('adminSettlementsView.peerSlash.retry', 'Read again') }}</button>
    </p>
    <p v-else-if="loaded && store.peerConfigs.length === 0" class="pa-muted" data-testid="peer-auto-slash-none">
      {{ t('adminSettlementsView.peerSlash.none', 'No active peers.') }}</p>
    <p v-if="writeFailed" class="pa-err" role="alert" data-testid="peer-auto-slash-write-failed">{{ store.error }}</p>

    <ul v-if="store.peerConfigs.length" class="pa-list">
      <li v-for="peer in store.peerConfigs" :key="peer.id" class="pa-row" :data-testid="`peer-auto-slash-${peer.id}`">
        <div class="pa-who">
          <span class="pa-name">{{ peer.name }}</span>
          <span class="pa-url">{{ peer.base_url }}</span>
        </div>
        <label class="pa-switch">
          <input type="checkbox" :checked="peer.auto_slash_enabled" :disabled="busy === peer.id"
                 :data-testid="`peer-auto-slash-on-${peer.id}`" @change="toggle(peer, $event)" />
          <span>{{ t('adminSettlementsView.peerSlash.auto', 'Automatic') }}</span>
        </label>
        <label class="pa-amount">
          <span>{{ t('adminSettlementsView.peerSlash.upTo', 'up to') }}</span>
          <input type="number" min="0" step="1" :value="peer.auto_slash_max_avt" :disabled="busy === peer.id || !peer.auto_slash_enabled"
                 :data-testid="`peer-auto-slash-max-${peer.id}`" @change="setMax(peer, $event)" />
          <span>{{ localCurrency }}</span>
        </label>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import { useSettlementsStore } from '@/stores/settlements'
import type { PeerSlashConfig } from '@/services/api/settlements'

const { t } = useI18n()
const { localCurrency } = useCurrency()
const store = useSettlementsStore()
const loaded = ref(false)
const busy = ref<number | null>(null)
const writeFailed = ref(false)

async function toggle(peer: PeerSlashConfig, ev: Event) {
  busy.value = peer.id
  writeFailed.value = !(await store.togglePeerAutoSlash(peer))
  // the box shows what the registry holds: a refusal leaves the peer as it was
  ;(ev.target as HTMLInputElement).checked = !!peer.auto_slash_enabled
  busy.value = null
}

async function setMax(peer: PeerSlashConfig, ev: Event) {
  const box = ev.target as HTMLInputElement
  busy.value = peer.id
  writeFailed.value = !(await store.updatePeerThreshold(peer, box.value))
  box.value = String(peer.auto_slash_max_avt ?? 0)
  busy.value = null
}

onMounted(async () => {
  await store.fetchPeerConfigs()
  loaded.value = true
})
</script>

<style scoped>
.pa {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  padding: 1.1rem 1.25rem;
  background: rgba(10, 13, 22, 0.6);
  margin-bottom: 1.25rem;
}
.pa-head { max-width: 62rem; }
.pa-title { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin: 0 0 0.25rem; }
.pa-lead { font-size: 0.82rem; color: #94a3b8; margin: 0; max-width: 62rem; }
.pa-list { list-style: none; margin: 0.9rem 0 0; padding: 0; display: grid; gap: 0.5rem; }
.pa-row {
  display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 0.9rem; align-items: center;
  padding: 0.55rem 0.75rem; border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 8px;
}
.pa-who { display: flex; flex-direction: column; min-width: 0; }
.pa-name { color: #e2e8f0; font-size: 0.88rem; font-weight: 500; }
.pa-url { color: #94a3b8; font-size: 0.74rem; overflow-wrap: anywhere; }
.pa-switch, .pa-amount { display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.78rem; color: #cbd5e1; }
.pa-amount input {
  width: 6.5rem; text-align: right; font-variant-numeric: tabular-nums; background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.3); border-radius: 4px; color: #e2e8f0; padding: 0.15rem 0.35rem;
}
.pa-btn {
  border: 1px solid rgba(148, 163, 184, 0.3); background: transparent; color: #cbd5e1; border-radius: 6px;
  padding: 0.15rem 0.5rem; font-size: 0.78rem; cursor: pointer; margin-left: 0.5rem;
}
.pa-err { color: #f87171; font-size: 0.8rem; margin: 0.6rem 0 0; }
.pa-muted { color: #94a3b8; font-size: 0.8rem; margin: 0.6rem 0 0; }
@media (max-width: 720px) {
  .pa-row { grid-template-columns: minmax(0, 1fr); }
}
</style>
