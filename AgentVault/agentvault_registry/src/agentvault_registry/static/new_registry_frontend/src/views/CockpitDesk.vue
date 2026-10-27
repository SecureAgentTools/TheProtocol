<script setup lang="ts">
/**
 * §COCKPIT P1 (2026-08-31) — THE DESK.
 *
 * A modular, savable working surface for the liable human: pick the panes this
 * hour needs, arrange them, save the arrangement, come back to it.
 *
 * 🔴 IT WAS read-only at C1 and IT IS NOT NOW (§COCKPITPOLISH P3, 2026-08-31). Consent
 * arrived in P5, STOP revokes mandates and deactivates agents, and §COCKPITA's instruct
 * makes an agent act. The header badge said `read-only` unconditionally the whole time —
 * wrong in the REASSURING direction, which is the worst way for a safety label to be
 * wrong. It now COUNTS the panes on the board that declare `acts` and says so, and it
 * still reads "read-only" when the count is genuinely zero, so the reassuring words are
 * earned rather than asserted.
 *
 * Gated by `COCKPIT_DESK_ENABLED`, default false everywhere. The router guard
 * and the sidebar entry both read `useRegistryConfig`, one fetch, so they cannot
 * disagree about whether this surface exists.
 *
 * Marker: `ckd-root` (dist gate). Panes carry `ckd-pane`.
 *
 * ⚠ Motion budget: no `backdrop-filter` anywhere in the cockpit CSS, and ONE
 * shared 1s ticker for every countdown on the desk (`useCockpitTicker`) rather
 * than one per pane. §TICKERLAG is what the other way costs.
 */
import { ref, computed, defineAsyncComponent, onMounted, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useAgentDoor } from '@/services/cockpit/agentDoor'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useCockpitLayouts } from '@/composables/useCockpitLayouts'
import { usePrivacy } from '@/composables/usePrivacy'
import { useAuthStore } from '@/stores/auth'
import { hasAdminFlag, type AdminAction } from '@/composables/usePermissions'
import { PANES, type PaneContext } from '@/components/cockpit/paneRegistry'
import { useDeskArrange } from '@/composables/useDeskArrange'
import DeskBoard from '@/components/cockpit/DeskBoard.vue'
import DeskAttention from '@/components/cockpit/DeskAttention.vue'
import { refreshDesk } from '@/services/cockpit/deskRefresh'

const { t, tp } = useI18n()
const authStore = useAuthStore()
const { config, cockpitDeskEnabled, load: loadCfg, readFailed: cfgReadFailed, reload: reloadCfg } = useRegistryConfig()
const layouts = useCockpitLayouts()
/* §COCKPITSHOW C1 — HIS ASK: *"we need an overall hide money button like we have on the
 * bridge so if you need you can hide crucial data."*
 *
 * It IS the bridge's switch, not a second one: `usePrivacy` is module-level state over a
 * shared `bridge.privacy` key, so hiding on the bridge hides here and the reverse. Two
 * toggles that could disagree about whether money is hidden would be worse than not
 * having the feature — and a screenshot taken with one of them off is the whole failure
 * this exists to prevent.
 *
 * ⚠ It masks the TEXT, never blurs it: a CSS blur leaves the real number in the DOM and
 * the accessibility tree, which is fine against a camera and useless against anything
 * that reads the page. It is not a security boundary and does not pretend to be — the
 * data is still fetched, and the session can still read it from the API. */
const { hidden: moneyHidden, toggle: toggleMoney } = usePrivacy()

/* §DASHARRANGE (2026-09-02) — the arrange brain is `useDeskArrange`, shared with the
 * dashboard's DeskArea; this view owns persistence (named layouts) and the header. */
const arrange = useDeskArrange(() => layouts.active.value)


/**
 * §COCKPITTILES T4 — DENSITY. The fastest way to fit more without resizing every tile.
 *
 * ⚠ localStorage ON PURPOSE, not the prefs rail: this is a per-viewer comfort setting, and
 * the prefs PUT is a WHOLE-VALUE REPLACE on `cockpit.layouts` — the write that destroyed a
 * saved 9-pane layout in §COCKPITPOLISH. A density flag is not worth going near it.
 * Reads and writes are wrapped: a browser with site data blocked must render the desk, not
 * an error.
 */
const density = ref<'cozy' | 'compact'>('cozy')
try { if (localStorage.getItem('cockpit.density') === 'compact') density.value = 'compact' } catch { /* blocked */ }
function toggleDensity() {
  density.value = density.value === 'compact' ? 'cozy' : 'compact'
  try { localStorage.setItem('cockpit.density', density.value) } catch { /* blocked */ }
}
/**
 * §COCKPITFRAME F6 (2026-09-01) — HIS ASK: *"would be cool to have the background on and off
 * option for all panes. with a button like hiding money. just for testing if i like it, it
 * stays in."*
 *
 * It stays in, so it is a preference rather than a debug flag.
 *
 * 🔴 THE BUTTON HE MEANS IS THE DENSITY ONE, NOT THE MONEY ONE — they look identical and
 * persist in OPPOSITE places, deliberately. `usePrivacy` is module-level state SHARED with
 * the bridge, because hiding money is a fact that must be true everywhere at once (§COCKPITSHOW
 * C1). A pane background is desk-local decoration and nobody else's business, so it follows
 * `density`: a local ref, its own localStorage key, a `data-` attribute on the root, and ONE
 * root-scoped rule that no pane needs to know about.
 *
 * ⚠ NOT the prefs PUT, for the same reason as density: whole-value replace on
 * `cockpit.layouts` is the write that destroyed a saved 9-pane layout.
 *
 * ⚠ Frameless changes PAINT ONLY. The gap, the spans, the height bounds and the overflow all
 * stay exactly as they are — with no frame, panes are separated only by the grid gap, which
 * is what "things are overlapping" LOOKS like even when nothing does.
 */
const chrome = ref<'on' | 'off'>('on')
try { if (localStorage.getItem('cockpit.chrome') === 'off') chrome.value = 'off' } catch { /* blocked */ }
function toggleChrome() {
  chrome.value = chrome.value === 'off' ? 'on' : 'off'
  try { localStorage.setItem('cockpit.chrome', chrome.value) } catch { /* blocked */ }
}

/* §COCKPITFRAME F5 — ONE dialog per subject for the whole desk, mounted here at the root.
 * Nine panes now raise "open this agent"; none of them mounts a modal, because a dialog
 * inside a pane inherits that pane's `overflow: auto` clipping and its stacking context.
 * Both are async: `AgentDetailModal` is a large component and must cost nothing until the
 * first click. */
/* ⚠ DESTRUCTURED, not held as `door.x` — a ref nested in a plain object is NOT unwrapped in
 * a template, so `door.agentOpen` would render as `[object Object]` (truthy, always) while
 * `door.agentOpen.value` works and looks like a typo somebody will "tidy" away. Top-level
 * bindings from setup are unwrapped, so the template reads what it means. */
const { agentDid: doorDid, agentName: doorName, agentOpen,
        deployment: doorDeploy, deploymentDid: doorDeployDid, deploymentOpen,
        closeAgent, closeDeployment } = useAgentDoor()
const AgentDetailModal = defineAsyncComponent(() => import('@/components/AgentDetailModal.vue'))
const DeploymentLogsModal = defineAsyncComponent(() => import('@/components/cicd/DeploymentLogsModal.vue'))

const saveName = ref('')
const saveMsg = ref('')

/* §COCKPITPOLISH (2026-08-31) — HIS REPORT: *"i cannot edit a saved builds name, nor
 * delete it."* `deleteLayout` had existed in the composable since P1 with NO CALLER, and
 * rename did not exist at all — saving under a new name creates a SECOND layout, because
 * `saveLayout` de-dupes by name. Both are doors on an existing rail.
 *
 * Delete is two-step rather than a modal: it is a preference, not money, so a dialog
 * would be theatre — but it is also not undoable, so a bare single click is not right
 * either. The button states what the second press will do. */
const renameVal = ref('')
const confirmDelete = ref(false)
/* ⚠ The prefs PUT takes ~3s on registry-a (38 workers, the busiest node in the fleet).
 * Three seconds of a button that does nothing visible is three seconds in which a person
 * presses it again. `busy` is not decoration — it is what stops a second write racing the
 * first, and it is why the batteries can wait for an OUTCOME instead of a duration. */
const busy = ref<'' | 'save' | 'rename' | 'delete'>('')

onMounted(async () => {
  await loadCfg(); await layouts.load()
  arrange.syncFromSource()
  renameVal.value = layouts.isBuiltin(layouts.activeId.value) ? '' : layouts.active.value.name
})
watch(() => layouts.active.value.id, () => { arrange.syncFromSource() })

const ctx = computed<PaneContext>(() => ({ config: config.value, isAdmin: !!authStore.isAdmin,
  adminCan: (a: AdminAction) => hasAdminFlag(authStore.user, a) }))
/** Counted from what is ON THE BOARD, not asserted about the surface: a Money layout
 *  with no STOP pane really is read-only, and should be allowed to say so. */
const actingIds = computed(() => arrange.shown.filter(id => PANES[id].acts))
const actingPanes = computed(() => actingIds.value.length)
const actingNames = computed(() => actingIds.value.map(id => t(PANES[id].titleKey, PANES[id].titleFallback)))
async function saveDraft() {
  const name = (saveName.value || layouts.active.value.name || 'My desk').trim().slice(0, 40)
  busy.value = 'save'
  try {
    await layouts.saveLayout(name, arrange.draft, arrange.draftSizes)
    saveMsg.value = t('cockpit.layout.saved', 'Saved.')
    arrange.finishEdit()
    saveName.value = ''
  } catch (e: any) {
    saveMsg.value = e?.response?.data?.detail || e?.message || t('cockpit.layout.saveFailed', 'Could not save.')
  } finally { busy.value = '' }
  setTimeout(() => { saveMsg.value = '' }, 4000)
}
function cancelEdit() {
  arrange.cancelEdit()
  confirmDelete.value = false
}

function flash(m: string) { saveMsg.value = m; setTimeout(() => { saveMsg.value = '' }, 4000) }

async function renameActive() {
  const id = layouts.activeId.value
  busy.value = 'rename'
  try {
    await layouts.renameLayout(id, renameVal.value)
    // ⚠ NOT cleared to '' — the box keeps the name that is now current, so the field
    // reflects the layout rather than emptying and inviting a second, blank rename.
    renameVal.value = layouts.active.value.name
    flash(t('cockpit.layout.renamed', 'Renamed.'))
  } catch (e: any) {
    // The composable rolled the local list back, so the chip still reads the OLD name —
    // screen and server agree even in failure, which is the whole point of that rollback.
    renameVal.value = layouts.active.value.name
    flash(e?.response?.data?.detail || e?.message || t('cockpit.layout.renameFailed', 'Could not rename it.'))
  } finally { busy.value = '' }
}

async function deleteActive() {
  if (!confirmDelete.value) { confirmDelete.value = true; return }
  const id = layouts.activeId.value
  busy.value = 'delete'
  try {
    await layouts.deleteLayout(id)
    // The active layout just stopped existing, so the draft must follow the new one or
    // Save would write the panes of a deleted layout back under a different name.
    arrange.syncFromSource()
    flash(t('cockpit.layout.deleted', 'Deleted.'))
  } catch (e: any) {
    flash(e?.response?.data?.detail || e?.message || t('cockpit.layout.deleteFailed', 'Could not delete it.'))
  } finally { confirmDelete.value = false; busy.value = '' }
}

/** Reset the two-step and prefill the rename box whenever the subject changes — a
 *  confirm armed against one layout must never fire against another. */
watch(() => layouts.activeId.value, () => {
  confirmDelete.value = false
  renameVal.value = layouts.isBuiltin(layouts.activeId.value) ? '' : layouts.active.value.name
})
</script>

<template>
  <div class="ckd-root" :data-density="density" :data-chrome="chrome" data-testid="ckd-root" data-tour="cockpit-desk">
    <!-- Honest state if the route is somehow reached with the flag off. The guard
         should prevent it; a view that assumes its guard ran is a view that renders
         a blank the day the guard changes. -->
    <!-- §FESUITE (2026-10-04): an unread config is not "not enabled" -->
    <ReadFailedNotice v-if="cfgReadFailed" :retry="reloadCfg" />
    <div v-else-if="!cockpitDeskEnabled" class="ckd-off" data-testid="ckd-off">
      <Icon icon="mdi:power-plug-off-outline" class="ckd-off-icon" />
      <h2>{{ t('cockpit.off.title', 'The Cockpit Desk is not enabled on this registry') }}</h2>
      <p>{{ t('cockpit.off.sub', 'It is a per-registry feature. Nothing is broken — this deployment simply does not serve it.') }}</p>
    </div>

    <template v-else>
      <header class="ckd-bar">
        <div class="ckd-bar-title">
          <Icon icon="mdi:view-dashboard-variant-outline" class="ckd-bar-icon" />
          <h1>{{ t('cockpit.title', 'Cockpit Desk') }}</h1>
          <span class="ckd-ro" :class="{ 'is-live': actingPanes > 0 }" data-testid="ckd-acts-badge"
                :title="actingPanes > 0 ? actingNames.join(' · ') : t('cockpit.readonlyHint', 'Nothing on this board can change anything.')">
            {{ actingPanes > 0
                 ? tp('cockpit.acts', '{n} can act', { n: actingPanes })
                 : t('cockpit.readonly', 'read-only') }}
          </span>
        </div>

        <nav class="ckd-layouts" :aria-label="t('cockpit.layout.aria', 'Desk layouts')">
          <!-- While ARRANGING, switching layout would silently throw the draft away
               (the active-id watch resets it). A discard with no gesture and no
               warning is the kind of small dishonesty that teaches people not to
               trust a save button, so the chips are inert until Save or Cancel. -->
          <!-- ⚠ MEASURED IN HIS OWN DATA: this account has a SAVED layout named "Build"
               beside the built-in one, so two chips read identically while only one of
               them can be renamed or deleted. With those controls now shipping, a person
               has to be able to tell which "Build" they are about to delete.
               🔴 THE MARK IS A CSS `::after`, NOT A CHARACTER IN THE LABEL. Appending a
               bullet to the button's content changed its accessible name to "Build •" —
               read aloud as "Build bullet" — and broke every exact-text selector that
               already addressed these chips (my own batteries went from finding Build to
               landing on Triage, which is how this was caught). Decoration never joins the
               text run; the meaning rides the title instead. -->
          <button v-for="l in layouts.all.value" :key="l.id"
                  class="ckd-chip" :class="{ 'is-active': l.id === layouts.activeId.value, 'is-inert': arrange.editing, 'is-own': !layouts.isBuiltin(l.id) }"
                  data-testid="ckd-layout-chip" data-tour="cockpit-layouts" :disabled="arrange.editing"
                  :data-own="layouts.isBuiltin(l.id) ? '0' : '1'"
                  :title="arrange.editing ? t('cockpit.layout.lockedWhileEditing', 'Save or cancel your arrangement first')
                          : (layouts.isBuiltin(l.id) ? l.name : t('cockpit.layout.ownHint', 'Saved by you — this one can be renamed or deleted'))"
                  @click="layouts.setActive(l.id)">
            {{ l.name }}
          </button>
        </nav>

        <div class="ckd-actions">
          <!-- §COCKPITDESK — every pane on the board reads again now (each frame calls its own read; LIVE panes are pushed) -->
          <button class="ckd-btn" data-testid="ckd-refresh-all" :disabled="arrange.editing"
                  :title="t('cockpit.refreshAllHint', 'Read every pane on this board again now')" @click="refreshDesk">
            <Icon icon="mdi:refresh" class="ckd-btn-icon" />
            {{ t('cockpit.refreshAll', 'Refresh') }}
          </button>
          <button class="ckd-btn" :class="{ 'is-on': moneyHidden }" data-testid="ckd-privacy"
                  data-tour="cockpit-privacy" :aria-pressed="moneyHidden"
                  :title="moneyHidden ? t('cockpit.privacy.show', 'Show amounts again')
                                      : t('cockpit.privacy.hide', 'Hide every figure on this desk — the same switch as the bridge')"
                  @click="toggleMoney">
            <Icon :icon="moneyHidden ? 'mdi:eye-off' : 'mdi:eye'" class="ckd-btn-icon" />
            {{ moneyHidden ? t('cockpit.privacy.hidden', 'Amounts hidden') : t('cockpit.privacy.label', 'Hide amounts') }}
          </button>
          <button class="ckd-btn" :class="{ 'is-on': density === 'compact' }" data-testid="ckd-density"
                  :aria-pressed="density === 'compact'"
                  :title="t('cockpit.layout.densityHint', 'Compact fits more on the board; it changes nothing about what the panes report.')"
                  @click="toggleDensity">
            <Icon :icon="density === 'compact' ? 'mdi:chevron-up' : 'mdi:chevron-down'" class="ckd-btn-icon" />
            {{ density === 'compact' ? t('cockpit.layout.compact', 'Compact') : t('cockpit.layout.cozy', 'Comfortable') }}
          </button>
          <button class="ckd-btn" :class="{ 'is-on': chrome === 'off' }" data-testid="ckd-chrome"
                  :aria-pressed="chrome === 'off'"
                  :title="t('cockpit.layout.chromeHint', 'Frameless drops every pane background and border. It changes paint only — the same panes, the same sizes, the same gaps.')"
                  @click="toggleChrome">
            <Icon :icon="chrome === 'off' ? 'mdi:view-dashboard-outline' : 'mdi:view-dashboard'" class="ckd-btn-icon" />
            {{ chrome === 'off' ? t('cockpit.layout.chromeOff', 'Frameless') : t('cockpit.layout.chromeOn', 'Framed') }}
          </button>
          <button class="ckd-btn" data-testid="ckd-edit-toggle" data-tour="cockpit-edit" @click="arrange.editing ? cancelEdit() : arrange.beginEdit()">
            <Icon :icon="arrange.editing ? 'mdi:close' : 'mdi:tune-variant'" class="ckd-btn-icon" />
            {{ arrange.editing ? t('cockpit.layout.cancel', 'Cancel') : t('cockpit.layout.arrange', 'Arrange') }}
          </button>
        </div>
      </header>

      <section v-if="arrange.editing" class="ckd-edit" data-testid="ckd-edit-bar">
        <div class="ckd-edit-add">
          <span class="ckd-edit-label">{{ t('cockpit.layout.add', 'Add pane') }}</span>
          <button v-for="id in arrange.addable" :key="id" class="ckd-chip ckd-chip--add"
                  data-testid="ckd-add-pane" :data-pane-id="id" @click="arrange.addPane(id)">
            + {{ t(PANES[id].titleKey, PANES[id].titleFallback) }}
          </button>
          <span v-if="!arrange.addable.length" class="ckd-edit-none">— {{ t('cockpit.layout.allAdded', 'every pane is on the desk') }}</span>
        </div>
        <div class="ckd-edit-save">
          <input v-model="saveName" class="ckd-input" maxlength="40"
                 :placeholder="layouts.active.value.name"
                 :aria-label="t('cockpit.layout.nameAria', 'Layout name')" />
          <button class="ckd-btn ckd-btn--primary" data-testid="ckd-save-layout"
                  :disabled="busy !== ''" @click="saveDraft">
            {{ busy === 'save' ? t('cockpit.layout.saving', 'Saving…') : t('cockpit.layout.save', 'Save layout') }}
          </button>
        </div>
      </section>

      <!-- §COCKPITPOLISH — MANAGE THE LAYOUT YOU ARE ON. Separate strip from "Save
           layout" on purpose: saving creates or overwrites BY NAME, renaming and deleting
           act on the one you are looking at, and blurring the two is how you end up with
           three copies of "My desk". -->
      <section v-if="arrange.editing" class="ckd-edit ckd-edit--manage" data-testid="ckd-manage-bar">
        <span class="ckd-edit-label">{{ t('cockpit.layout.thisLayout', 'This layout') }}</span>
        <template v-if="layouts.isBuiltin(layouts.activeId.value)">
          <!-- Honest about WHY the controls are absent rather than just absent. -->
          <span class="ckd-edit-none" data-testid="ckd-builtin-note">
            {{ tp('cockpit.layout.builtin',
                  '“{name}” is built into this registry — it cannot be renamed or deleted. Save it under your own name to get a copy you own.',
                  { name: layouts.active.value.name }) }}
          </span>
        </template>
        <template v-else>
          <input v-model="renameVal" class="ckd-input" maxlength="40"
                 data-testid="ckd-rename-input"
                 :aria-label="t('cockpit.layout.renameAria', 'New name for this layout')" />
          <button class="ckd-btn" data-testid="ckd-rename-layout"
                  :disabled="busy !== '' || !renameVal.trim() || renameVal.trim() === layouts.active.value.name"
                  @click="renameActive">
            {{ busy === 'rename' ? t('cockpit.layout.renaming', 'Renaming…') : t('cockpit.layout.rename', 'Rename') }}
          </button>
          <button class="ckd-btn ckd-btn--danger" data-testid="ckd-delete-layout"
                  :disabled="busy !== ''" @click="deleteActive">
            <Icon icon="mdi:trash-can-outline" class="ckd-btn-icon" />
            {{ busy === 'delete' ? t('cockpit.layout.deleting', 'Deleting…')
               : confirmDelete
                 ? tp('cockpit.layout.deleteConfirm', 'Delete “{name}” — press again', { name: layouts.active.value.name })
                 : t('cockpit.layout.delete', 'Delete this layout') }}
          </button>
        </template>
      </section>
      <p v-if="saveMsg" class="ckd-savemsg" data-testid="ckd-save-msg">{{ saveMsg }}</p>
      <p v-if="layouts.error.value" class="ckd-savemsg ckd-savemsg--warn">
        {{ tp('cockpit.layout.readFailed', 'Saved layouts could not be read ({e}) — the starters still work.', { e: layouts.error.value }) }}
      </p>


      <DeskAttention v-if="!arrange.editing" :arrange="arrange" />
      <DeskBoard :arrange="arrange" :ctx="ctx" :density="density" :chrome="chrome"
                 :empty-text="t('cockpit.layout.emptyLayout', 'This layout has no panes. Use Arrange to add some.')" />

      <!-- §COCKPITFRAME F5 — the desk's ONE agent card and ONE deployment log, for every
           pane. Rendered only while open, so an unused door costs nothing at all. -->
      <AgentDetailModal v-if="agentOpen" :show="true"
                        :agent-did="doorDid || undefined" :agent-name="doorName"
                        @update:show="v => { if (!v) closeAgent() }" />
      <DeploymentLogsModal v-if="deploymentOpen" :deployment="doorDeploy"
                           :agent-did="doorDeployDid" @close="closeDeployment()" />
    </template>
  </div>
</template>

<style scoped>
.ckd-root { padding: .75rem 1rem 2rem; display: flex; flex-direction: column; gap: .75rem; }

.ckd-off { display: flex; flex-direction: column; align-items: center; gap: .4rem; padding: 3rem 1rem; text-align: center; }
.ckd-off-icon { width: 30px; height: 30px; color: var(--nc-text-muted, #6e7681); }
.ckd-off h2 { margin: 0; font-size: 1rem; color: var(--nc-text-primary, #e6edf3); }
.ckd-off p { margin: 0; font-size: .8rem; color: var(--nc-text-dim, #8b949e); max-width: 46ch; }

.ckd-bar { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
.ckd-bar-title { display: flex; align-items: center; gap: .45rem; }
.ckd-bar-icon { width: 18px; height: 18px; color: var(--nc-primary, #00e5ff); }
.ckd-bar-title h1 { margin: 0; font-size: 1rem; letter-spacing: .04em; color: var(--nc-text-primary, #e6edf3); }
.ckd-ro { font-size: .6rem; letter-spacing: .1em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); border: 1px solid var(--nc-border, rgba(255,255,255,.1)); border-radius: 4px; padding: 0 .3rem; white-space: nowrap; }
.ckd-ro.is-live { color: var(--nc-warning, #d29922); border-color: rgba(210,153,34,.4); }

.ckd-layouts { display: flex; gap: .3rem; flex-wrap: wrap; flex: 1; }
.ckd-chip {
  font-size: .7rem; padding: .2rem .5rem; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--nc-border, rgba(255,255,255,.1));
  background: transparent; color: var(--nc-text-dim, #8b949e);
}
.ckd-chip:hover { color: var(--nc-text-primary, #e6edf3); border-color: var(--nc-border-strong, rgba(255,255,255,.2)); }
.ckd-chip.is-active { color: var(--nc-primary, #00e5ff); border-color: rgba(var(--nc-primary-rgb, 0,229,255), .5); background: rgba(var(--nc-primary-rgb, 0,229,255), .07); }
.ckd-chip.is-inert { opacity: .4; cursor: not-allowed; }
.ckd-chip--add { color: var(--nc-success, #3fb950); border-color: rgba(63,185,80,.3); }
.ckd-chip.is-own::after { content: '\00B7'; margin-left: .3rem; opacity: .6; }

.ckd-actions { display: flex; gap: .35rem; }
.ckd-btn {
  display: inline-flex; align-items: center; gap: .3rem; cursor: pointer;
  font-size: .72rem; padding: .28rem .6rem; border-radius: 6px;
  border: 1px solid var(--nc-border, rgba(255,255,255,.12));
  background: transparent; color: var(--nc-text-secondary, #c9d1d9);
}
.ckd-btn:hover { border-color: var(--nc-primary, #00e5ff); color: var(--nc-primary, #00e5ff); }
.ckd-btn--primary { color: var(--nc-primary, #00e5ff); border-color: rgba(var(--nc-primary-rgb, 0,229,255), .45); }
.ckd-btn-icon { width: 13px; height: 13px; }

.ckd-edit { display: flex; gap: .75rem; flex-wrap: wrap; align-items: center; padding: .45rem .6rem; border: 1px dashed var(--nc-border, rgba(255,255,255,.12)); border-radius: 8px; }
.ckd-edit-add { display: flex; gap: .3rem; align-items: center; flex-wrap: wrap; flex: 1; }
.ckd-edit-label { font-size: .66rem; letter-spacing: .06em; text-transform: uppercase; color: var(--nc-text-muted, #6e7681); }
.ckd-edit-none { font-size: .68rem; color: var(--nc-text-muted, #6e7681); }
.ckd-edit-save { display: flex; gap: .35rem; align-items: center; }
.ckd-input { font-size: .72rem; padding: .25rem .45rem; border-radius: 6px; border: 1px solid var(--nc-border, rgba(255,255,255,.12)); background: var(--nc-deep, #010409); color: var(--nc-text-primary, #e6edf3); width: 12rem; }
.ckd-edit--manage { border-style: solid; border-color: var(--nc-border-subtle, rgba(255,255,255,.08)); }
.ckd-btn:disabled { opacity: .5; cursor: not-allowed; }
.ckd-btn { white-space: nowrap; }
/* §COCKPITDESK (2026-10-14) — a phone's header: at a Pixel's width the six layout chips stacked into a narrow column
   beside the title and "Hide amounts" broke over two lines (lifecycle 98's photograph). Below 640 px the chips take a row
   of their own that scrolls sideways, and the switches wrap whole. */
@media (max-width: 640px) {
  .ckd-root { padding: .5rem .6rem 1.5rem; }
  .ckd-layouts { flex: 1 1 100%; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: .1rem; }
  .ckd-layouts::-webkit-scrollbar { display: none; }
  .ckd-chip { flex: 0 0 auto; }
  .ckd-actions { flex: 1 1 100%; flex-wrap: wrap; }
}
.ckd-btn.is-on { color: var(--nc-warning, #d29922); border-color: rgba(210,153,34,.5); }
.ckd-btn--danger { color: var(--nc-danger, #f85149); border-color: rgba(248,81,73,.4); }
.ckd-btn--danger:hover { border-color: var(--nc-danger, #f85149); color: var(--nc-danger, #f85149); }
.ckd-savemsg { margin: 0; font-size: .7rem; color: var(--nc-success, #3fb950); }
.ckd-savemsg--warn { color: var(--nc-warning, #d29922); }
/* The board's own rules (.ckd-grid, .ckd-slot*, .ckd-max, .ckd-mini, density/chrome) live in
   components/cockpit/DeskBoard.vue since §DASHARRANGE — one board, two hosts. */
</style>
