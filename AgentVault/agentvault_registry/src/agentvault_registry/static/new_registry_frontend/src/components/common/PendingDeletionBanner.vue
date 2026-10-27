<script setup lang="ts">
/**
 * PendingDeletionBanner — W2 (2026-05-09)
 *
 * Shown across all authenticated routes when the user has a pending
 * deletion request. Visible affordance + countdown + 1-click jump to
 * Settings → Security where the cancel button lives.
 *
 * Resolves the user's deletion state from the auth store (forwarded by
 * /developers/me via verify()). Self-hides if not pending.
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Icon from '@/components/Icon.vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const router = useRouter()
const authStore = useAuthStore()

const isPending = computed(() =>
  authStore.user?.deletion_status === 'pending_deletion',
)

const anonymizesAt = computed(() => {
  const requestedAt = authStore.user?.deletion_requested_at
  if (!requestedAt) return null
  // Cooling-off is 14 days by default; we mirror the backend constant.
  return dayjs(requestedAt).add(14, 'day')
})

const anonymizesAtHuman = computed(() =>
  anonymizesAt.value ? anonymizesAt.value.format('MMM D, YYYY') : '',
)

const countdown = computed(() =>
  anonymizesAt.value ? anonymizesAt.value.fromNow(true) : '',
)

function goCancelDeletion() {
  router.push({ path: '/settings', query: { tab: 'security' } })
}
</script>

<template>
  <div v-if="isPending" class="pdb-banner" role="alert" aria-live="polite">
    <div class="pdb-icon"><Icon name="mdi:trash-can-outline" /></div>
    <div class="pdb-text">
      <strong>Account deletion scheduled.</strong>
      Your account will be anonymized on
      <strong>{{ anonymizesAtHuman }}</strong>
      <span v-if="countdown"> ({{ countdown }} from now)</span>.
    </div>
    <button class="pdb-cta" @click="goCancelDeletion">
      <Icon name="mdi:undo-variant" />&nbsp; Cancel deletion
    </button>
  </div>
</template>

<style scoped>
.pdb-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 18px;
  background: linear-gradient(
    90deg,
    rgba(239, 68, 68, 0.18) 0%,
    rgba(239, 68, 68, 0.10) 60%,
    rgba(239, 68, 68, 0.18) 100%
  );
  border-bottom: 1px solid rgba(239, 68, 68, 0.40);
  color: rgba(255, 255, 255, 0.92);
  font-size: 13px;
  line-height: 1.5;
}
.pdb-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  color: rgba(239, 68, 68, 0.95);
  font-size: 20px;
}
.pdb-text {
  flex: 1;
  min-width: 0;
}
.pdb-text strong { color: rgba(255, 255, 255, 0.98); }
.pdb-cta {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 7px 14px;
  background: rgba(239, 68, 68, 0.16);
  color: rgba(255, 200, 200, 0.95);
  border: 1px solid rgba(239, 68, 68, 0.55);
  border-radius: 4px;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease;
}
.pdb-cta:hover {
  background: rgba(239, 68, 68, 0.26);
  border-color: rgba(239, 68, 68, 0.85);
  color: #fff;
}
@media (max-width: 640px) {
  .pdb-banner {
    flex-direction: column;
    align-items: flex-start;
    padding: 10px 14px;
    gap: 8px;
  }
  .pdb-cta { width: 100%; justify-content: center; }
}
</style>
