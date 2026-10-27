<!--
  DeskArea.vue — §ONBOARDQOL P7 (2026-09-02) + §DASHARRANGE (2026-09-02): cockpit panes on
  the post-login dashboard, and — his ask — the person's OWN choice of them.

  "if you add arrange for cockpit desk on mission-control users could add their own panes."

  This is a HOST, not a second desk. It mounts the SAME board the desk mounts
  (`DeskBoard.vue`), drives it with the SAME arrange brain (`useDeskArrange`), and persists
  ONE layout per person through the SAME prefs rail (`useDashboardLayout`, key
  `cockpit.dashboard`). What it does not carry, on purpose: named layouts and their chips,
  density and chrome toggles (it wears the desk's saved preference), maximise-as-a-mode.
  The full desk is one click away and is where those live.

  Persistence follows the §COCKPITPOLISH rule: snapshot → write → on failure the screen
  goes back to what the server holds, and the in-flight state is named on screen.

  ⚠ GATED BY THE CALLER on `cockpitDeskEnabled` — on a registry where the desk flag is off
  there is nothing to mount and the caller keeps its own cards. The area does not re-check
  the flag: a second copy of "is the desk on" is the §ORGLEAK second-copy trap.
-->
<template>
  <section class="dsk" data-testid="dsk-root" data-tour="mc-desk"
           :data-editing="arrange.editing ? '1' : '0'" :data-panes="arrange.shown.length" :data-own="dash.isDefault.value ? '0' : '1'"
           :data-follow="followed ? followed.id : ''">
    <div class="dsk-head">
      <span class="dsk-title">{{ t('mc.desk.title', 'YOUR DESK') }}</span>
      <span v-if="followed && !arrange.editing" class="dsk-own" data-testid="dsk-follows">{{ tp('mc.desk.follows', 'shows {name}', { name: followed.name }) }}</span>
      <span v-else-if="!dash.isDefault.value && !arrange.editing" class="dsk-own" data-testid="dsk-own">{{ t('mc.desk.yours', 'your arrangement') }}</span>
      <span class="dsk-spacer" />
      <template v-if="arrange.editing">
        <button class="dsk-btn" data-testid="dsk-reset" :disabled="busy !== ''" @click="resetBoard">
          {{ busy === 'reset' ? t('mc.desk.resetting', 'Resetting…') : t('mc.desk.reset', 'Reset to default') }}
        </button>
        <button class="dsk-btn" data-testid="dsk-cancel" :disabled="busy !== ''" @click="cancel">{{ t('cockpit.layout.cancel', 'Cancel') }}</button>
        <button class="dsk-btn dsk-btn--primary" data-testid="dsk-save" :disabled="busy !== ''" @click="save">
          {{ busy === 'save' ? t('cockpit.layout.saving', 'Saving…') : t('cockpit.layout.save', 'Save layout') }}
        </button>
      </template>
      <template v-else>
        <!-- §COCKPITDESK (2026-10-15) — which board this area shows: its own arrangement, or one of the desk's layouts. -->
        <label class="dsk-pick" :title="t('mc.desk.pickHint', 'Show this board\'s own arrangement, or one of your desk layouts')">
          <span class="dsk-pick-label">{{ t('mc.desk.board', 'Board') }}</span>
          <select class="dsk-select" data-testid="dsk-board" :value="followed ? followed.id : ''" :disabled="busy !== ''"
                  @change="pick(($event.target as HTMLSelectElement).value)">
            <option value="">{{ t('mc.desk.ownBoard', 'This board') }}</option>
            <optgroup :label="t('mc.desk.deskLayouts', 'Desk layouts')">
              <option v-for="l in desk.all.value" :key="l.id" :value="l.id">{{ l.name }}</option>
            </optgroup>
          </select>
        </label>
        <!-- §COCKPITDESK — the desk's and the bridge's ONE privacy switch (usePrivacy is shared), beside the figures it hides -->
        <button class="dsk-btn" :class="{ 'is-on': moneyHidden }" data-testid="dsk-privacy" :aria-pressed="moneyHidden"
                :title="moneyHidden ? t('cockpit.privacy.show', 'Show amounts again') : t('cockpit.privacy.hide', 'Hide every figure on this desk — the same switch as the bridge')"
                @click="toggleMoney">
          <Icon :icon="moneyHidden ? 'mdi:eye-off' : 'mdi:eye'" class="dsk-btn-icon" />{{ moneyHidden ? t('cockpit.privacy.hidden', 'Amounts hidden') : t('cockpit.privacy.label', 'Hide amounts') }}
        </button>
        <button class="dsk-btn" data-testid="dsk-refresh" :title="t('cockpit.refreshAllHint', 'Read every pane on this board again now')" @click="refreshDesk">
          <Icon icon="mdi:refresh" class="dsk-btn-icon" />{{ t('cockpit.refreshAll', 'Refresh') }}
        </button>
        <button v-if="!followed" class="dsk-btn" data-testid="dsk-arrange" @click="arrange.beginEdit()">
          <Icon icon="mdi:tune-variant" class="dsk-btn-icon" />{{ t('cockpit.layout.arrange', 'Arrange') }}
        </button>
        <router-link :to="{ name: 'cockpit-desk' }" class="dsk-open" data-testid="dsk-open">
          {{ t('mc.desk.open', 'Open the full desk') }} &rsaquo;
        </router-link>
      </template>
    </div>

    <div v-if="arrange.editing" class="dsk-edit" data-testid="dsk-edit-bar">
      <p class="dsk-hint">{{ t('mc.desk.hint', 'Add, remove, resize and reorder the panes on your dashboard. It is saved to your account; the full desk has every pane and named layouts.') }}</p>
      <div class="dsk-edit-add">
        <span class="dsk-edit-label">{{ t('cockpit.layout.add', 'Add pane') }}</span>
        <button v-for="id in arrange.addable" :key="id" class="dsk-chip" data-testid="dsk-add-pane" :data-pane-id="id"
                @click="arrange.addPane(id)">
          + {{ t(PANES[id].titleKey, PANES[id].titleFallback) }}
        </button>
        <span v-if="!arrange.addable.length" class="dsk-edit-none">— {{ t('cockpit.layout.allAdded', 'every pane is on the desk') }}</span>
      </div>
    </div>
    <p v-if="followed && !arrange.editing" class="dsk-hint" data-testid="dsk-follow-hint">
      {{ tp('mc.desk.followHint', 'This board shows your desk layout {name}. Arrange it on the full desk, or pick This board to arrange this one.', { name: followed.name }) }}
    </p>
    <p v-if="followGone" class="dsk-msg dsk-msg--warn" data-testid="dsk-follow-gone">
      {{ desk.error.value
          ? t('mc.desk.followUnread', 'Your desk layouts could not be read, so this board shows its own arrangement.')
          : t('mc.desk.followGone', 'The desk layout this board showed no longer exists; it shows its own arrangement again.') }}
    </p>
    <p v-if="msg" class="dsk-msg" :class="{ 'dsk-msg--warn': msgKind === 'warn' }" data-testid="dsk-msg" :data-kind="msgKind">{{ msg }}</p>
    <p v-if="dash.error.value" class="dsk-msg dsk-msg--warn" data-testid="dsk-read-failed">
      {{ tp('cockpit.layout.readFailed', 'Saved layouts could not be read ({e}) — the starters still work.', { e: dash.error.value }) }}
    </p>

    <DeskAttention v-if="!arrange.editing" :arrange="arrange" />
    <DeskBoard :arrange="arrange" :ctx="ctx" :density="density" :chrome="chrome"
               :empty-text="t('cockpit.layout.emptyLayout', 'This layout has no panes. Use Arrange to add some.')" />

    <!-- The desk's ONE agent card and ONE deployment log, mounted once per host. -->
    <AgentDetailModal v-if="agentOpen" :show="true"
                      :agent-did="doorDid || undefined" :agent-name="doorName"
                      @update:show="v => { if (!v) closeAgent() }" />
    <DeploymentLogsModal v-if="deploymentOpen" :deployment="doorDeploy"
                         :agent-did="doorDeployDid" @close="closeDeployment()" />
  </section>
</template>

<script setup lang="ts">
import { ref, computed, defineAsyncComponent, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { hasAdminFlag, type AdminAction } from '@/composables/usePermissions'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useCockpitLayouts, useDashboardLayout } from '@/composables/useCockpitLayouts'
import { useDeskArrange } from '@/composables/useDeskArrange'
import { PANES, type PaneContext } from '@/components/cockpit/paneRegistry'
import { useAgentDoor } from '@/services/cockpit/agentDoor'
import DeskBoard from '@/components/cockpit/DeskBoard.vue'
import DeskAttention from '@/components/cockpit/DeskAttention.vue'
import { usePrivacy } from '@/composables/usePrivacy'
import { refreshDesk } from '@/services/cockpit/deskRefresh'

const { t, tp } = useI18n()
const authStore = useAuthStore()
const { config } = useRegistryConfig()
const ctx = computed<PaneContext>(() => ({ config: config.value, isAdmin: !!authStore.isAdmin,
  adminCan: (a: AdminAction) => hasAdminFlag(authStore.user, a) }))

const dash = useDashboardLayout()
/* §COCKPITDESK (2026-10-15) — the desk's named layouts, so this board can show one of them instead of its own. */
const desk = useCockpitLayouts()
const deskRead = ref(false)
const followed = computed(() => {
  const id = dash.follow.value
  return id ? desk.all.value.find(l => l.id === id) || null : null
})
/** A followed layout that is not there (deleted on the desk, or the desk's layouts unreadable): the board says so. */
const followGone = computed(() => !!dash.follow.value && deskRead.value && !followed.value)
/* §COCKPITDESK — the ONE privacy switch (module-level, shared with the desk and the bridge): the dashboard shows the same
 * figures, so it carries the same switch beside them instead of sending a person to the desk to hide them. */
const { hidden: moneyHidden, toggle: toggleMoney } = usePrivacy()
/* The dashboard offers only panes that will actually render here; the desk offers every
 * pane and renders the unservable ones as an honest shell. Same registry, two honest
 * answers to two different questions. */
const arrange = useDeskArrange(() => followed.value || dash.layout.value, { offer: id => PANES[id].available(ctx.value) })

/* The desk's saved preferences, worn read-only: the dashboard has no toggles for them. */
const density = ref<'cozy' | 'compact'>('cozy')
const chrome = ref<'on' | 'off'>('on')
try {
  if (localStorage.getItem('cockpit.density') === 'compact') density.value = 'compact'
  if (localStorage.getItem('cockpit.chrome') === 'off') chrome.value = 'off'
} catch { /* blocked storage: the defaults */ }

const busy = ref<'' | 'save' | 'reset' | 'follow'>('')
const msg = ref(''); const msgKind = ref<'ok' | 'warn'>('ok')
let msgTimer: ReturnType<typeof setTimeout> | null = null
function flash(m: string, kind: 'ok' | 'warn' = 'ok') {
  msg.value = m; msgKind.value = kind
  if (msgTimer) clearTimeout(msgTimer)
  msgTimer = setTimeout(() => { msg.value = '' }, kind === 'ok' ? 4000 : 9000)
}

onMounted(async () => {
  await Promise.all([dash.load(), desk.load().finally(() => { deskRead.value = true })])
  arrange.syncFromSource()
})

/** Sent first; on a refusal the select goes back to what the registry holds and says why. */
async function pick(id: string) {
  busy.value = 'follow'
  try {
    await dash.setFollow(id || null)
    arrange.syncFromSource()
  } catch (e: any) {
    const why = e?.response?.data?.detail || e?.message || ''
    flash(t('mc.desk.pickFailed', 'Not changed: the registry still holds the previous choice.') + (why ? ` (${why})` : ''), 'warn')
  } finally { busy.value = '' }
}

async function save() {
  busy.value = 'save'
  try {
    await dash.save(arrange.draft, arrange.draftSizes)
    arrange.finishEdit()
    flash(t('cockpit.layout.saved', 'Saved.'))
  } catch (e: any) {
    // The rail rolled `dash.layout` back to what the server holds; the draft stays on
    // screen, still editable, and the message says which of the two you are looking at.
    // The honest sentence FIRST — "Network Error" alone does not say which board you are
    // looking at — with the transport's own detail after it.
    const why = e?.response?.data?.detail || e?.message || ''
    flash(t('mc.desk.unsaved', 'Not saved — the board shows your draft; the registry still holds the previous one.') + (why ? ` (${why})` : ''), 'warn')
  } finally { busy.value = '' }
}
function cancel() { arrange.cancelEdit(); msg.value = '' }
async function resetBoard() {
  busy.value = 'reset'
  try {
    await dash.reset()
    arrange.cancelEdit()   // the source is the default now; leave editing showing it
    flash(t('cockpit.layout.saved', 'Saved.'))
  } catch (e: any) {
    flash(e?.response?.data?.detail || e?.message || t('cockpit.layout.saveFailed', 'Could not save.'), 'warn')
  } finally { busy.value = '' }
}

/* Destructured, not held as `door.x` — a ref nested in a plain object is not unwrapped in
 * a template (the desk learned this the hard way, see CockpitDesk.vue). */
const { agentDid: doorDid, agentName: doorName, agentOpen,
        deployment: doorDeploy, deploymentDid: doorDeployDid, deploymentOpen,
        closeAgent, closeDeployment } = useAgentDoor()
const AgentDetailModal = defineAsyncComponent(() => import('@/components/AgentDetailModal.vue'))
const DeploymentLogsModal = defineAsyncComponent(() => import('@/components/cicd/DeploymentLogsModal.vue'))
</script>

<style scoped>
.dsk { margin-top: 1.5rem; display: flex; flex-direction: column; gap: .6rem; }
.dsk-head { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
.dsk-title { font-size: 0.65rem; font-weight: 700; letter-spacing: 0.15em; color: rgba(var(--nc-primary-rgb), 0.85); }
.dsk-own { font-size: .58rem; letter-spacing: .08em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681);
  border: 1px solid var(--nc-border, rgba(255,255,255,.14)); border-radius: 999px; padding: .1rem .45rem; }
.dsk-spacer { flex: 1; }
.dsk-open { font-size: .7rem; letter-spacing: .06em; color: rgba(var(--nc-primary-rgb), .8); text-decoration: none; margin-left: .25rem; }
.dsk-open:hover { text-decoration: underline; }
.dsk-btn { display: inline-flex; align-items: center; gap: .3rem; font-size: .68rem; letter-spacing: .04em; padding: .28rem .6rem; border-radius: 6px;
  border: 1px solid var(--nc-border, rgba(255,255,255,.14)); background: var(--nc-surface, #0d1117); color: var(--nc-text-secondary, #c9d1d9); cursor: pointer; }
.dsk-btn:hover { border-color: var(--nc-primary, #00e5ff); color: var(--nc-primary, #00e5ff); }
.dsk-btn:disabled { opacity: .5; cursor: not-allowed; }
.dsk-btn.is-on { color: var(--nc-warning, #d29922); border-color: rgba(210,153,34,.5); }
.dsk-btn--primary { color: var(--nc-primary, #00e5ff); border-color: rgba(var(--nc-primary-rgb, 0,229,255), .5); }
.dsk-btn-icon { width: 13px; height: 13px; }
.dsk-pick { display: inline-flex; align-items: center; gap: .35rem; }
.dsk-pick-label { font-size: .62rem; letter-spacing: .06em; text-transform: uppercase; color: var(--nc-text-muted, #8b949e); }
.dsk-select { font-size: .68rem; padding: .24rem .45rem; border-radius: 6px; max-width: 14rem;
  border: 1px solid var(--nc-border, rgba(255,255,255,.14)); background: var(--nc-surface, #0d1117); color: var(--nc-text-secondary, #c9d1d9); }
.dsk-select:focus-visible { outline: 2px solid var(--nc-primary, #00e5ff); outline-offset: 1px; }
.dsk-select:disabled { opacity: .5; cursor: not-allowed; }
.dsk-edit { display: flex; flex-direction: column; gap: .4rem; padding: .5rem .7rem; border: 1px dashed var(--nc-border, rgba(255,255,255,.14)); border-radius: 8px; }
.dsk-hint { margin: 0; font-size: .68rem; color: var(--nc-text-muted, #6e7681); }
.dsk-edit-add { display: flex; gap: .3rem; align-items: center; flex-wrap: wrap; }
.dsk-edit-label { font-size: .62rem; letter-spacing: .06em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); margin-right: .2rem; }
.dsk-edit-none { font-size: .66rem; color: var(--nc-text-muted, #6e7681); }
.dsk-chip { font-size: .66rem; padding: .18rem .5rem; border-radius: 999px; cursor: pointer;
  border: 1px solid rgba(63,185,80,.3); background: transparent; color: var(--nc-success, #3fb950); }
.dsk-chip:hover { border-color: var(--nc-success, #3fb950); }
.dsk-msg { margin: 0; font-size: .7rem; color: var(--nc-success, #3fb950); }
.dsk-msg--warn { color: var(--nc-warning, #d29922); }
</style>
