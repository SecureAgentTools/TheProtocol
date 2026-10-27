<!-- VOTE PERMISSION (§MEMBERSHIP phase C, 2026-10-02) — "this agent is not allowed to vote yet", said before the member's
     first vote fails or right after it did, with the one press that allows it: the governor role, added after a second
     press and nothing else changed (composables/useVotePermission.ts). Where the registry can only replace every role at
     once and a role carries a time limit, the owner is sent to My Agents instead, where the limit stays visible. Silent
     while the agent may vote, while nothing is known, and when the check fails unless a vote was just refused. A press
     that fails keeps the notice and its button, says why, and can be pressed again. -->
<template>
  <div v-if="shown" ref="root" class="vpn" role="status" data-testid="vote-permission" :data-state="vp.state.value">
    <p class="vpn-text">
      <Icon name="mdi:shield-account-outline" />
      <span v-if="vp.state.value === 'failed'">{{ t('membership.permission.failed', 'Your vote was not cast, and whether this agent may vote could not be checked right now.') }}</span>
      <span v-else-if="refused">{{ t('membership.permission.refused', 'Your vote was not cast: this agent is not allowed to vote yet.') }}</span>
      <span v-else>{{ t('membership.permission.notYet', 'The agent you act as is not allowed to vote yet.') }}</span>
    </p>

    <template v-if="vp.state.value === 'grantable' || vp.state.value === 'time_boxed'">
      <p class="vpn-hint">{{ t('membership.permission.hint', 'Allowing it gives the agent the governor role, which also lets it make proposals and vote on AGORA organization proposals.') }}</p>
      <p v-if="vp.state.value === 'time_boxed'" class="vpn-hint" data-testid="vote-permission-limits">{{ t('membership.permission.keepsLimits', 'Its other roles keep their time limits.') }}</p>
      <div class="vpn-actions">
        <template v-if="!confirming">
          <button type="button" class="tp-btn tp-btn--primary" :disabled="vp.busy.value" data-testid="vote-permission-allow" @click="confirming = true">
            {{ t('membership.permission.allow', 'Allow this agent to vote') }}
          </button>
        </template>
        <template v-else>
          <span class="vpn-ask">{{ t('membership.permission.confirm', 'Give this agent the governor role now?') }}</span>
          <button type="button" class="tp-btn tp-btn--primary" :disabled="vp.busy.value" data-testid="vote-permission-confirm" @click="doAllow">
            {{ t('membership.permission.yes', 'Yes, allow it') }}
          </button>
          <button type="button" class="tp-btn tp-btn--ghost" :disabled="vp.busy.value" data-testid="vote-permission-cancel" @click="confirming = false">
            {{ t('common.cancel', 'Cancel') }}
          </button>
        </template>
      </div>
    </template>

    <p v-else-if="vp.state.value === 'panel_only'" class="vpn-hint">
      {{ t('membership.permission.panelOnly', "This registry can only replace all of an agent's roles at once, which would erase their time limits: give it the governor role on My Agents, where the limits stay visible.") }}
      <RouterLink to="/my-agents" class="vpn-link" data-testid="vote-permission-link">{{ t('membership.permission.toAccess', 'Open My Agents') }}</RouterLink>
    </p>

    <p v-if="vp.error.value" class="vpn-error" data-testid="vote-permission-error">
      <template v-if="vp.state.value !== 'failed'">{{ t('membership.permission.allowFailed', 'This agent could not be allowed to vote.') }}</template>
      {{ vp.error.value }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, toRef, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useVotePermission } from '@/composables/useVotePermission'

const props = withDefaults(defineProps<{ did: string | null | undefined; refused?: boolean }>(), { refused: false })
const emit = defineEmits<{ (e: 'allowed'): void }>()
const { t } = useI18n()

const vp = useVotePermission(toRef(props, 'did'))
const confirming = ref(false)
const root = ref<HTMLElement | null>(null)

const shown = computed(() => {
  const s = vp.state.value
  if (s === 'grantable' || s === 'time_boxed' || s === 'panel_only') return true
  return s === 'failed' && props.refused
})

async function doAllow() {
  const ok = await vp.allow()
  confirming.value = false
  if (ok) emit('allowed')
}

onMounted(() => { void vp.check() })
watch(() => props.did, () => { confirming.value = false; void vp.check() })
// a refused vote asks again (the role may have changed elsewhere since the first look) and brings the notice into view
watch(() => props.refused, async (r) => {
  if (!r) return
  await vp.check()
  await nextTick()
  try { root.value?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' }) } catch { /* not in every environment */ }
})

defineExpose({ check: vp.check })
</script>

<style scoped>
.vpn { border: 1px solid rgba(251,191,36,0.45); background: rgba(251,191,36,0.06); border-radius: 10px; padding: 0.7rem 0.85rem; display: flex; flex-direction: column; gap: 0.45rem; }
.vpn-text { display: flex; gap: 0.45rem; align-items: flex-start; margin: 0; font-size: 0.84rem; font-weight: 600; }
.vpn-text :deep(svg) { width: 1rem; height: 1rem; flex: 0 0 auto; margin-top: 0.1rem; color: rgb(251,191,36); }
.vpn-hint { margin: 0; font-size: 0.78rem; line-height: 1.45; opacity: 0.9; }
.vpn-actions { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.vpn-ask { font-size: 0.8rem; font-weight: 600; }
.vpn-link { margin-left: 0.3rem; color: inherit; text-decoration: underline; text-underline-offset: 2px; }
.vpn-error { margin: 0; font-size: 0.76rem; color: rgb(248,113,113); overflow-wrap: anywhere; }
</style>
