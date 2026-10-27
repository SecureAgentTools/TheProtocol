<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { attestationsApi } from '@/services'
import type { AttestationRecord } from '@/services/api/attestations'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const props = defineProps<{
  agentDid: string
}>()

const verified = ref<AttestationRecord[]>([])
const loaded = ref(false)
const showCard = ref(false)

function isExpired(a: AttestationRecord): boolean {
  if (!a.expires_at) return false
  return new Date(a.expires_at).getTime() < Date.now()
}

onMounted(async () => {
  if (!props.agentDid) return
  try {
    const resp = await attestationsApi.getAttestationsByDid(
      props.agentDid,
      { verified: true, limit: 5 },
    )
    verified.value = (resp.items || []).filter(
      (a) => !a.revoked_at && !isExpired(a),
    )
  } catch {
    verified.value = []
  } finally {
    loaded.value = true
  }
})
</script>

<template>
  <span
    v-if="loaded && verified.length > 0"
    class="zkp-badge"
    @mouseenter="showCard = true"
    @mouseleave="showCard = false"
  >
    <span class="zkp-badge-icon">✓</span>
    <span class="zkp-badge-label">ZKP&nbsp;Verified</span>
    <span class="zkp-badge-count">×{{ verified.length }}</span>

    <!-- Hover-card with top circuits -->
    <span v-if="showCard" class="zkp-badge-card" @mouseenter.stop="showCard = true">
      <span class="zkp-card-title">Verified ZKP attestations</span>
      <span
        v-for="a in verified.slice(0, 3)"
        :key="a.id"
        class="zkp-card-row"
      >
        <span class="zkp-card-circuit">{{ a.circuit_id }}</span>
        <span class="zkp-card-date">
          {{ a.verified_at ? dayjs(a.verified_at).fromNow() : '—' }}
        </span>
      </span>
      <span v-if="verified.length > 3" class="zkp-card-more">
        + {{ verified.length - 3 }} more
      </span>
    </span>
  </span>
</template>

<style scoped>
.zkp-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(16, 185, 129, 0.12);  /* emerald-500 @ 12% */
  border: 1px solid rgba(16, 185, 129, 0.45);
  color: #10b981;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  cursor: help;
  position: relative;
  user-select: none;
}
.zkp-badge-icon {
  color: #10b981;
  font-weight: bold;
}
.zkp-badge-count {
  opacity: 0.8;
  font-size: 0.68rem;
}
.zkp-badge-card {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 50;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 14px;
  min-width: 280px;
  background: #0c1117;
  border: 1px solid rgba(16, 185, 129, 0.4);
  border-radius: 6px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
  color: #d1fae5;
  font-size: 0.78rem;
  font-weight: 400;
  font-family: 'Inter', ui-sans-serif, sans-serif;
  letter-spacing: 0;
}
.zkp-card-title {
  color: #10b981;
  font-weight: 600;
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  border-bottom: 1px solid rgba(16, 185, 129, 0.25);
  padding-bottom: 4px;
}
.zkp-card-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.zkp-card-circuit {
  font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 0.72rem;
  color: #e4ecf4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.zkp-card-date {
  color: #94a3b8;
  font-size: 0.7rem;
  white-space: nowrap;
}
.zkp-card-more {
  color: #94a3b8;
  font-size: 0.7rem;
  font-style: italic;
  text-align: right;
}
</style>
