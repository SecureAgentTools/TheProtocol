<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// E2 — Org Setup Guide.
//
// The "one guided flow" for a fresh organization, built as a LIVE CHECKLIST
// rather than a modal stepper on purpose: a stepper would re-implement the
// invite modal, the assign modal, the policy panel and the treasury card as
// second copies (the §FANOUTFIX class — two surfaces asking the same question
// drift apart). Instead each step detects its own completion from the same
// endpoints the real surfaces use and deep-links to the exact tab where the
// single implementation lives. One action is genuinely inline — treasury
// creation — because it is a single idempotent POST with no form.
//
// Shows for org admins while setup is incomplete; dismissible per org; hides
// itself once every required step is done.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed, onMounted, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { organizationService } from '@/services/api/organizationService'

const { t } = useI18n()
const uiStore = useUIStore()

const props = defineProps<{ orgId: string; canManage: boolean }>()
const emit = defineEmits<{ (e: 'go', tab: string): void }>()

const loading = ref(true)
const dismissed = ref(false)
const treasuryBusy = ref(false)

const membersCount = ref(0)
const agentsCount = ref(0)
const grantsCount = ref(0)
const knobsSet = ref(false)
const treasuryExists = ref(false)
// §FESUITE (V0577): the steps whose read failed (by step key). A read that failed is not "not done": the step says it
// could not be read and offers no action ("Create treasury" over a treasury read that failed asked to make it again)
const unread = ref<Record<string, boolean>>({})
const anyUnread = computed(() => Object.values(unread.value).some(Boolean))

const DISMISS_KEY = () => `org_setup_dismissed_${props.orgId}`

async function load() {
  loading.value = true
  try { dismissed.value = localStorage.getItem(DISMISS_KEY()) === '1' } catch { dismissed.value = false }
  const failed: Record<string, boolean> = {}
  const miss = (key: string) => () => { failed[key] = true; return null }
  try {
    const [settings, members, agents, authority, treasury] = await Promise.all([
      organizationService.getOrgSettings(props.orgId).catch(miss('policy')),
      organizationService.listMembers(props.orgId).catch(miss('members')),
      organizationService.listOrganizationAgents(props.orgId).catch(miss('agents')),
      organizationService.getOrgAuthorityGrants(props.orgId).catch(miss('authority')),
      organizationService.getOrgTreasuryAccount(props.orgId).catch(miss('treasury')),
    ])
    const s: any = settings?.settings || {}
    // §DOCSFIX D6-486 (2026-10-16): the catalog's own knobs only (services/org_policy.py ORG_SETTING_CATALOG). It also
    // read `require_approval_above`, a key the catalog does not hold and the settings route refuses.
    knobsSet.value = !!(s.org_spend_ceiling_avt != null || s.default_agent_authority_slice
      || (s.liability && Object.keys(s.liability).length))
    membersCount.value = (members || []).length
    const ag: any = agents
    agentsCount.value = Array.isArray(ag) ? ag.length : (ag?.agents || []).length
    const au: any = authority
    grantsCount.value = (au?.grants || au?.rows || (Array.isArray(au) ? au : [])).length
    treasuryExists.value = !!(treasury as any)?.exists || (treasury as any)?.source === 'org'
  } finally {
    unread.value = failed
    loading.value = false
  }
}

interface Step {
  key: string; done: boolean; optional?: boolean; unread?: boolean
  title: string; body: string; cta: string; tab: string
}
const steps = computed<Step[]>(() => [
  {
    key: 'members', done: membersCount.value >= 2, tab: 'members',
    title: t('orgSetup.members.title', 'Invite your people'),
    body: t('orgSetup.members.body', 'Bring in the humans who run this org. Admins can manage agents and policy; members work under it.'),
    cta: t('orgSetup.members.cta', 'Invite members'),
  },
  {
    key: 'agents', done: agentsCount.value >= 1, tab: 'agents',
    title: t('orgSetup.agents.title', 'Assign your agents'),
    body: t('orgSetup.agents.body', 'Attach the agents that act for this org. Assignment is by agent creator, so nobody drafts an agent that is not theirs.'),
    cta: t('orgSetup.agents.cta', 'Assign agents'),
  },
  {
    key: 'policy', done: knobsSet.value, tab: 'settings',
    title: t('orgSetup.policy.title', 'Set the guardrails'),
    body: t('orgSetup.policy.body', 'Spend ceiling, default authority slice and the liability step-up threshold. Tighten-only over the registry: stricter is always allowed, looser never wins.'),
    cta: t('orgSetup.policy.cta', 'Open settings'),
  },
  {
    key: 'authority', done: grantsCount.value >= 1, tab: 'authority',
    title: t('orgSetup.authority.title', 'Grant working authority'),
    body: t('orgSetup.authority.body', 'Give assigned agents their permission slice in one bulk action. Authority collapses instantly on revoke.'),
    cta: t('orgSetup.authority.cta', 'Review authority'),
  },
  {
    key: 'treasury', done: treasuryExists.value, optional: true, tab: 'treasury',
    title: t('orgSetup.treasury.title', 'Open the org treasury (optional)'),
    body: t('orgSetup.treasury.body', 'A keyless money account for the org: fund agents from it, agents remit income back. No unit can ever be issued for it.'),
    cta: t('orgSetup.treasury.cta', 'View treasury'),
  },
// a step whose read failed is neither done nor to-do: it says so (above, `unread`)
].map(s => ({ ...s, unread: !!unread.value[s.key], done: s.done && !unread.value[s.key] })))
const requiredSteps = computed(() => steps.value.filter(s => !s.optional))
const doneCount = computed(() => steps.value.filter(s => s.done).length)
const allRequiredDone = computed(() => requiredSteps.value.every(s => s.done))
const show = computed(() =>
  props.canManage && !loading.value && !dismissed.value && !(allRequiredDone.value && treasuryExists.value))

async function createTreasury() {
  if (treasuryBusy.value) return
  treasuryBusy.value = true
  try {
    await organizationService.createOrgTreasuryAccount(props.orgId)
    treasuryExists.value = true
    uiStore.showSuccess(
      t('orgSetup.treasury.createdTitle', 'Treasury created'),
      t('orgSetup.treasury.createdBody', 'The org now has its own keyless money account. Fund it from the Treasury tab.'))
  } catch (e: any) {
    uiStore.showError(
      t('orgSetup.treasury.createFailed', 'Could not create treasury'),
      e?.response?.data?.detail || e?.message)
  } finally { treasuryBusy.value = false }
}

function dismiss() {
  dismissed.value = true
  try { localStorage.setItem(DISMISS_KEY(), '1') } catch { /* view-state only */ }
}

onMounted(load)
watch(() => props.orgId, load)
defineExpose({ load })
</script>

<template>
  <section v-if="show" class="osg-root" data-tour="org-setup-guide" data-testid="org-setup-guide">
    <div class="osg-head">
      <h3 class="osg-title">
        <Icon name="mdi:map-marker-path" class="osg-title-ic" />
        <span>{{ t('orgSetup.title', 'Setup Guide') }}</span>
        <span class="osg-progress-label">{{ doneCount }}/{{ steps.length }}</span>
      </h3>
      <button v-if="anyUnread" class="osg-btn" data-testid="osg-retry" @click="load">{{ t('common.readFailed.retry', 'Try again') }}</button>
      <button class="osg-dismiss" :title="t('orgSetup.dismiss', 'Hide this guide')" @click="dismiss">
        <Icon name="mdi:close" />
      </button>
    </div>
    <div class="osg-track"><div class="osg-fill" :style="{ width: (doneCount / steps.length * 100) + '%' }"></div></div>

    <ol class="osg-steps">
      <li v-for="(s, i) in steps" :key="s.key" :class="['osg-step', { 'osg-step--done': s.done }]" :data-testid="'osg-' + s.key"
          :data-unread="s.unread ? '1' : undefined">
        <span class="osg-mark">
          <Icon v-if="s.done" name="check-circle" class="osg-mark-done" />
          <span v-else-if="s.unread" class="osg-mark-num">—</span>
          <span v-else class="osg-mark-num">{{ i + 1 }}</span>
        </span>
        <div class="osg-step-body">
          <p class="osg-step-title">{{ s.title }}<span v-if="s.optional" class="osg-opt">{{ t('orgSetup.optional', 'optional') }}</span></p>
          <p v-if="s.unread" class="osg-step-text" role="status">{{ t('common.readFailed.text', 'This could not be read just now.') }}</p>
          <p v-else-if="!s.done" class="osg-step-text">{{ s.body }}</p>
        </div>
        <div v-if="!s.unread" class="osg-step-action">
          <template v-if="s.key === 'treasury' && !s.done">
            <button class="osg-btn" :disabled="treasuryBusy" data-testid="osg-create-treasury" @click="createTreasury">
              {{ treasuryBusy ? t('orgSetup.treasury.creating', 'Creating...') : t('orgSetup.treasury.createCta', 'Create treasury') }}
            </button>
          </template>
          <button v-else-if="!s.done" class="osg-btn" @click="emit('go', s.tab)">{{ s.cta }}</button>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.osg-root {
  margin: 18px 0 0; padding: 18px 20px;
  background: rgba(var(--nc-primary-rgb), 0.035);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 10px;
}
.osg-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.osg-title {
  display: flex; align-items: center; gap: 8px; margin: 0;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: rgba(226, 232, 240, 0.85);
}
.osg-title-ic { font-size: 1rem; color: rgba(var(--nc-primary-rgb), 0.75); }
.osg-progress-label {
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.05em;
  color: rgba(var(--nc-primary-rgb), 0.8);
  padding: 1px 8px; border-radius: 999px;
  background: rgba(var(--nc-primary-rgb), 0.1); border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
}
.osg-dismiss {
  background: none; border: none; cursor: pointer; padding: 4px;
  color: rgba(148, 163, 184, 0.5); font-size: 1rem; line-height: 1;
}
.osg-dismiss:hover { color: rgba(226, 232, 240, 0.8); }
.osg-track { height: 3px; border-radius: 2px; background: rgba(255, 255, 255, 0.06); overflow: hidden; margin-bottom: 14px; }
.osg-fill { height: 100%; background: rgba(var(--nc-primary-rgb), 0.7); transition: width 0.4s; }

.osg-steps { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
.osg-step { display: flex; align-items: flex-start; gap: 12px; }
.osg-mark { flex-shrink: 0; width: 22px; height: 22px; display: inline-flex; align-items: center; justify-content: center; margin-top: 1px; }
.osg-mark-done { font-size: 1.1rem; color: rgba(52, 211, 153, 0.85); }
.osg-mark-num {
  width: 20px; height: 20px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; font-weight: 700;
  color: rgba(var(--nc-primary-rgb), 0.85);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.4);
}
.osg-step-body { flex: 1 1 auto; min-width: 0; }
.osg-step-title { margin: 0; font-size: 0.82rem; font-weight: 600; color: rgba(226, 232, 240, 0.88); }
.osg-step--done .osg-step-title { color: rgba(148, 163, 184, 0.8); text-decoration: line-through; text-decoration-color: rgba(148, 163, 184, 0.35); }
.osg-opt {
  margin-left: 8px; font-size: 0.6rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: rgba(148, 163, 184, 0.8);
  padding: 1px 6px; border-radius: 999px; border: 1px solid rgba(255, 255, 255, 0.1);
}
.osg-step-text { margin: 3px 0 0; font-size: 0.75rem; line-height: 1.5; color: rgba(148, 163, 184, 0.6); max-width: 640px; }
.osg-step-action { flex-shrink: 0; }
.osg-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 600; letter-spacing: 0.08em;
  padding: 6px 14px; border-radius: 6px; cursor: pointer;
  transition: all 0.15s;
  background: rgba(var(--nc-primary-rgb), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28);
  color: rgba(var(--nc-primary-rgb), 0.9);
}
.osg-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.18); border-color: rgba(var(--nc-primary-rgb), 0.5); }
.osg-btn:disabled { opacity: 0.45; cursor: not-allowed; }

@media (max-width: 720px) {
  .osg-step { flex-wrap: wrap; }
  .osg-step-action { margin-left: 34px; }
}
</style>
