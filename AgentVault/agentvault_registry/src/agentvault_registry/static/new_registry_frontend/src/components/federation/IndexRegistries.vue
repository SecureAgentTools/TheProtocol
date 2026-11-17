<!-- V0663, the Directory read path, step 3 (order gwo_0936844934f713153ede256c): the registries the federated index
     knows, as this registry read them (GET /public/directory/registries). The registry checked every card itself against
     the key at the address the card names: the index can leave a registry out, never vouch for one. Only a verified card
     names a registry here; a row that did not verify shows the index's name with the reason. Listing creates no peering:
     an admin with the federation flag is pointed to the invitation rail for a candidate, and that is all.
     Parsing and order: services/federation/indexRegistries. -->
<template>
  <section v-if="answer && answer.state !== 'unconfigured'" class="ixr" data-testid="ixr" :aria-busy="loading">
    <header class="ixr-head">
      <h2 class="ixr-title">{{ t('federationDiscoveryView.index.title', 'Registries the index knows') }}</h2>
      <p class="ixr-lede">{{ t('federationDiscoveryView.index.lede', 'Read from the federated index. This registry checks every card against the key at the address the card itself names, so the index can leave a registry out but cannot vouch for one. A registry listed here is not a peer until an invitation is accepted.') }}</p>
    </header>

    <div v-if="answer.state === 'error'" class="ixr-error" role="alert" data-testid="ixr-error">
      <span>{{ tp('federationDiscoveryView.index.error', 'The index could not be read: {reason}', { reason: answer.error || '' }) }}</span>
      <button type="button" class="ixr-retry" data-testid="ixr-retry" :disabled="loading" @click="load">
        {{ t('federationDiscoveryView.index.retry', 'Try again') }}
      </button>
    </div>

    <template v-else>
      <p class="ixr-summary" data-testid="ixr-summary">
        {{ tp('federationDiscoveryView.index.summary', '{verified} of {read} registries verified by this registry', { verified: answer.counts.verified, read: answer.counts.read }) }}
      </p>
      <p v-if="!answer.servesCards" class="ixr-note" data-testid="ixr-older-index">
        {{ t('federationDiscoveryView.index.olderIndex', 'This index serves no signed cards yet (an older Directory), so nothing it lists can be verified here.') }}
      </p>
      <p v-if="answer.truncated" class="ixr-note" data-testid="ixr-truncated">
        {{ tp('federationDiscoveryView.index.truncated', 'The index named {index} registries; the first {read} were read.', { index: answer.counts.index, read: answer.counts.read }) }}
      </p>
      <p v-if="!rows.length" class="ixr-note" data-testid="ixr-empty">
        {{ t('federationDiscoveryView.index.empty', 'The index knows no registries yet.') }}
      </p>
      <ul v-else class="ixr-list">
        <li v-for="(r, i) in rows" :key="`${r.name ?? r.indexName ?? ''}-${i}`" class="ixr-row"
            :class="{ 'ixr-row--unverified': !r.verified }"
            :data-testid="r.verified ? `ixr-row-${r.name}` : `ixr-row-unverified-${r.indexName}`">
          <div class="ixr-id">
            <span class="ixr-name">{{ r.verified ? r.name : (r.indexName || t('federationDiscoveryView.index.unnamed', 'A registry the index does not name')) }}</span>
            <span v-if="r.verified && r.trustDomain" class="ixr-domain">{{ r.trustDomain }}</span>
          </div>
          <div v-if="r.verified" class="ixr-facts">
            <span v-if="r.location">{{ r.location }}</span>
            <span v-if="r.currency" class="ixr-unit">{{ r.currency }}</span>
          </div>
          <div class="ixr-marks">
            <span v-if="r.verified" class="ixr-verified" data-testid="ixr-verified">{{ t('federationDiscoveryView.index.verified', 'Verified by this registry') }}</span>
            <span v-else class="ixr-unverified">{{ tp('federationDiscoveryView.index.unverified', 'Not verified: {reason}', { reason: r.reason }) }}</span>
            <span v-if="r.verified" class="ixr-relation" data-testid="ixr-relation" :data-relation="r.relation">{{ relationText(r.relation) }}</span>
            <RouterLink v-if="canInvite && r.relation === 'candidate'" :to="{ name: 'federation' }" class="ixr-invite">
              {{ t('federationDiscoveryView.index.invite', 'Invite it from Federation') }}
            </RouterLink>
          </div>
          <p v-if="r.verified && r.addressAgrees === false" class="ixr-address" data-testid="ixr-address">
            {{ tp('federationDiscoveryView.index.address', 'The index lists {index}; the card names {card}.', { index: r.indexUrl || '', card: r.publicUrl || '' }) }}
          </p>
        </li>
      </ul>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import {
  normaliseIndexRegistries,
  orderIndexRegistries,
  type IndexRegistriesAnswer,
  type IndexRelation,
} from '@/services/federation/indexRegistries'

withDefaults(defineProps<{ canInvite?: boolean }>(), { canInvite: false })
const { t, tp } = useI18n()

const answer = ref<IndexRegistriesAnswer | null>(null)
const loading = ref(false)
const rows = computed(() => orderIndexRegistries(answer.value?.registries ?? []))

function relationText(r: IndexRelation): string {
  switch (r) {
    case 'self': return t('federationDiscoveryView.index.relationSelf', 'This registry')
    case 'peer': return t('federationDiscoveryView.index.relationPeer', 'Peer')
    case 'known': return t('federationDiscoveryView.index.relationKnown', 'Known, not an active peer')
    case 'candidate': return t('federationDiscoveryView.index.relationCandidate', 'Not a peer')
    default: return ''
  }
}

async function load(): Promise<void> {
  loading.value = true
  try {
    // every status is an answer here: a 502 carries the index's reason, which the section shows
    const r = await apiClient.get('/public/directory/registries', { validateStatus: () => true })
    answer.value = normaliseIndexRegistries(r.status, r.data)
  } catch {
    answer.value = normaliseIndexRegistries(0, { configured: true, error: t('federationDiscoveryView.index.unreachable', 'this registry could not be reached') })
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.ixr { margin: 1.5rem 0 0; padding: 1rem 1.1rem; border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.16); border-radius: 4px; }
.ixr-head { margin-bottom: 0.6rem; }
.ixr-title { margin: 0; font-size: 1rem; font-weight: 500; letter-spacing: -0.005em; color: var(--nc-text-primary, #e8eaed); }
.ixr-lede { margin: 0.3rem 0 0; font-size: 0.78rem; line-height: 1.45; color: var(--nc-text-muted, #9aa0a6); max-width: 70ch; }
.ixr-summary { margin: 0.4rem 0; font-size: 0.8rem; color: var(--nc-text-primary, #e8eaed); }
.ixr-note { margin: 0.3rem 0; font-size: 0.76rem; color: var(--nc-text-muted, #9aa0a6); }
.ixr-error { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; font-size: 0.8rem; color: var(--nc-danger, #ef4444); }
.ixr-retry { padding: 4px 12px; background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.1); border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3); color: var(--nc-primary-bright, #00e5e5); border-radius: 3px; cursor: pointer; }
.ixr-retry:disabled { opacity: 0.5; cursor: default; }
.ixr-list { list-style: none; margin: 0.4rem 0 0; padding: 0; }
.ixr-row { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1.6fr); gap: 0.4rem 0.8rem; align-items: center; padding: 0.55rem 0; border-top: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08); }
.ixr-row--unverified { opacity: 0.75; }
.ixr-id { display: flex; flex-direction: column; min-width: 0; }
.ixr-name { font-size: 0.85rem; color: var(--nc-text-primary, #e8eaed); overflow-wrap: anywhere; }
.ixr-domain { font-family: ui-monospace, monospace; font-size: 0.7rem; color: var(--nc-text-muted, #9aa0a6); overflow-wrap: anywhere; }
.ixr-facts { display: flex; flex-wrap: wrap; gap: 0.5rem; font-size: 0.74rem; color: var(--nc-text-muted, #9aa0a6); }
.ixr-unit { font-family: ui-monospace, monospace; }
.ixr-marks { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; font-size: 0.72rem; }
.ixr-verified { color: var(--nc-success-bright, #34d399); border: 1px solid currentColor; border-radius: 3px; padding: 1px 6px; }
.ixr-unverified { color: var(--nc-warning, #f59e0b); overflow-wrap: anywhere; }
.ixr-relation { color: var(--nc-text-primary, #e8eaed); border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25); border-radius: 3px; padding: 1px 6px; }
.ixr-invite { color: var(--nc-primary-bright, #00e5e5); text-decoration: underline; }
.ixr-address { grid-column: 1 / -1; margin: 0; font-size: 0.72rem; color: var(--nc-warning, #f59e0b); overflow-wrap: anywhere; }
@media (max-width: 720px) { .ixr-row { grid-template-columns: minmax(0, 1fr); } }
</style>
