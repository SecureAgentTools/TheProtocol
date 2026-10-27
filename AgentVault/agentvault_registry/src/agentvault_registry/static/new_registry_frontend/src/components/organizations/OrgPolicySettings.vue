<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// Organization policy settings — a catalog-driven, TIGHTEN-ONLY form.
//
// The org sets policy ON TOP OF the registry. It may pick an equal-or-STRICTER
// value; a looser choice has no effect (the gate always takes the strictest).
//   • liability.mode           — off < shadow < enforce; STRICTER = higher.
//   • liability.presence_threshold_avt — lower is STRICTER (0 = off).
//   • contract_offer_ttl_days  — plain bound (not tighten-only, no registry floor).
//
// Loads settings + control catalog + registry posture, renders inputs from the
// catalog, surfaces the registry floor + tighten-only hints, and on Save rebuilds
// the nested patch and PUTs it — surfacing a 422 `detail` inline.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, reactive, computed, watch, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import {
  organizationService,
  type OrgPolicySettings,
  type OrgSettingsCatalogEntry,
  type OrgRegistryPosture,
} from '@/services/api/organizationService'

const { t } = useI18n()
const uiStore = useUIStore()

const props = defineProps<{
  /** Organization id whose policy is being edited. */
  orgId: string
  /** Optional explicit edit permission. When omitted, the form is editable
   *  unless the load (or a save) returns 403, at which point it goes read-only. */
  canEdit?: boolean
}>()

// ── State ──────────────────────────────────────────────────────────────────────
const loading = ref(true)
const loadError = ref<string | null>(null)
const forbidden = ref(false)          // GET/PUT returned 403 → read-only
const saving = ref(false)
const saveError = ref<string | null>(null)   // 422 detail (inline)
const saved = ref(false)

const settings = ref<OrgPolicySettings>({})
const catalog = ref<OrgSettingsCatalogEntry[]>([])
const registry = ref<OrgRegistryPosture | null>(null)

/** Form values keyed by the catalog's dotted key (e.g. 'liability.mode'). */
const form = reactive<Record<string, string>>({})

// ── Mode ordering (off < shadow < enforce; higher = stricter) ──────────────────
const MODE_ORDER = ['off', 'shadow', 'enforce']
function modeRank(m: string | undefined): number {
  const i = MODE_ORDER.indexOf(String(m ?? ''))
  return i < 0 ? 0 : i
}

// ── Effective edit permission ──────────────────────────────────────────────────
const effectiveCanEdit = computed(() => {
  if (forbidden.value) return false
  if (props.canEdit === undefined) return true
  return props.canEdit
})

// ── Dotted-key readers ─────────────────────────────────────────────────────────
function readSetting(key: string): unknown {
  const s = settings.value
  if (!s) return undefined
  if (key === 'liability.mode') return s.liability?.mode
  if (key === 'liability.presence_threshold_avt') return s.liability?.presence_threshold_avt
  return (s as Record<string, unknown>)[key]
}

/** The registry floor value for a key, or undefined when the key has no floor. */
function registryValueFor(key: string): string | number | undefined {
  const r = registry.value
  if (!r) return undefined
  if (key === 'liability.mode') return r.liability_mode
  if (key === 'liability.presence_threshold_avt') return r.presence_threshold_avt
  return undefined
}

// §ORGSPEND — object-typed catalog entries (per-member maps) have no generic input;
// their editor lives on the surface that knows the members (the Members tab). The
// generic form renders a pointer instead of a control, and never hydrates/patches them
// (String({}) would be '[object Object]').
const formEntries = computed(() => catalog.value.filter((e) => e.type !== 'object'))
const objectEntries = computed(() => catalog.value.filter((e) => e.type === 'object'))

// ── Hydrate the form from settings, falling back to the registry-effective value ─
function hydrateForm() {
  for (const entry of formEntries.value) {
    const own = readSetting(entry.key)
    if (own !== undefined && own !== null && own !== '') {
      form[entry.key] = String(own)
      continue
    }
    // No org override — seed with the current registry-effective value so the
    // control reflects today's effective state (hints spell out the floor).
    const reg = registryValueFor(entry.key)
    form[entry.key] = reg !== undefined && reg !== null ? String(reg) : ''
  }
}

// ── Enum tightness: is this option LOOSER than the registry floor? ──────────────
function isOptionLooser(key: string, opt: string): boolean {
  if (key !== 'liability.mode') return false
  const floor = registryValueFor(key)
  if (floor === undefined) return false
  return modeRank(opt) < modeRank(String(floor))
}

// ── Per-field hints ────────────────────────────────────────────────────────────
/** The tighten-only guidance for a field, or '' when it doesn't apply. Rule-focused:
 *  the floor VALUE is already shown in the Registry chip, so the hint states only
 *  which direction is stricter and that a looser choice has no effect. */
function tightenHint(entry: OrgSettingsCatalogEntry): string {
  if (!entry.tighten_only) return ''
  if (registryValueFor(entry.key) === undefined) return ''
  if (entry.key === 'liability.mode') {
    return t('orgPolicySettings.modeTighten', 'Equal or stricter only (off < shadow < enforce). A looser mode has no effect — the gate always takes the strictest.')
  }
  if (entry.key === 'liability.presence_threshold_avt') {
    return t('orgPolicySettings.presenceTighten', 'Lower is stricter (0 = off). A higher threshold has no effect — the gate keeps the strictest.')
  }
  return t('orgPolicySettings.genericTighten', 'Equal or stricter than the registry only.')
}

/** True when the CURRENT value is looser than the registry floor — makes the
 *  tighten-only rule tangible for the free-typed number field the same way the
 *  enum disables its below-floor options. Only the presence threshold has a
 *  known, single-axis direction (higher = looser), so we flag only that. */
function looserThanFloor(entry: OrgSettingsCatalogEntry): boolean {
  if (!effectiveCanEdit.value || !entry.tighten_only) return false
  if (entry.key !== 'liability.presence_threshold_avt') return false
  const floor = registryValueFor(entry.key)
  if (floor === undefined || floor === null) return false
  const v = Number(form[entry.key])
  if (Number.isNaN(v)) return false
  return v > Number(floor)   // higher presence threshold = looser
}

/** Read-only display value for a field (viewer mode). */
function displayValue(entry: OrgSettingsCatalogEntry): string {
  const v = form[entry.key]
  if (v === '' || v === undefined || v === null) {
    return t('orgPolicySettings.inherits', '(inherits registry)')
  }
  return String(v)
}

function onEdit() {
  saved.value = false
  saveError.value = null
}

// ── Build the nested patch from the flat, dotted form ──────────────────────────
function buildPatch(): OrgPolicySettings {
  const patch: Record<string, any> = {}
  for (const entry of formEntries.value) {
    let v: any = form[entry.key]
    if (v === '' || v === undefined || v === null) continue
    if (entry.type === 'number') {
      v = Number(v)
      if (Number.isNaN(v)) continue
    }
    if (entry.type === 'bool') v = v === true   /* §OCOPTIN: send a real boolean */
    const parts = entry.key.split('.')
    let node = patch
    for (let i = 0; i < parts.length - 1; i++) {
      if (typeof node[parts[i]] !== 'object' || node[parts[i]] === null) node[parts[i]] = {}
      node = node[parts[i]]
    }
    node[parts[parts.length - 1]] = v
  }
  return patch as OrgPolicySettings
}

// ── Load ───────────────────────────────────────────────────────────────────────
async function load() {
  if (!props.orgId) return
  loading.value = true
  loadError.value = null
  forbidden.value = false
  saved.value = false
  saveError.value = null
  try {
    const res = await organizationService.getOrgSettings(props.orgId)
    settings.value = res.settings || {}
    catalog.value = res.catalog || []
    registry.value = res.registry || null
    hydrateForm()
  } catch (e: any) {
    if (e?.status === 403) forbidden.value = true
    else loadError.value = e?.detail || e?.message || t('orgPolicySettings.loadFailed', 'Failed to load policy settings')
  } finally {
    loading.value = false
  }
}

// ── Save ─────────────────────────────────────────────────────────────────────────
async function save() {
  if (!effectiveCanEdit.value || saving.value) return
  saving.value = true
  saveError.value = null
  saved.value = false
  try {
    const res = await organizationService.updateOrgSettings(props.orgId, buildPatch())
    settings.value = res.settings || settings.value
    hydrateForm()
    saved.value = true
    uiStore.showSuccess(
      t('orgPolicySettings.savedTitle', 'Policy updated'),
      t('orgPolicySettings.savedBody', 'Organization policy saved.'),
    )
  } catch (e: any) {
    if (e?.status === 403) {
      forbidden.value = true
      saveError.value = e?.detail || t('orgPolicySettings.forbidden', 'You do not have permission to change organization policy.')
    } else {
      // 422 (or other) — surface the RFC-7807 detail inline.
      saveError.value = e?.detail || e?.message || t('orgPolicySettings.saveFailed', 'Failed to save policy settings')
    }
  } finally {
    saving.value = false
  }
}

watch(() => props.orgId, () => { load() })
onMounted(load)
</script>

<template>
  <section class="pol-root">
    <div class="pol-head">
      <h3 class="pol-title">
        <Icon name="mdi:tune" class="pol-title-ic" />
        <span>{{ t('orgPolicySettings.title', 'Organization Policy') }}</span>
      </h3>
      <p class="pol-subtitle">
        {{ t('orgPolicySettings.subtitle', 'Tighten-only controls layered on top of the registry. Your organization can be stricter than the registry — never looser.') }}
      </p>
    </div>

    <!-- Loading ─────────────────────────────────────────────────────────── -->
    <div v-if="loading" class="pol-state">
      <Icon name="loader" class="pol-spin" />
      <span>{{ t('orgPolicySettings.loading', 'Loading policy…') }}</span>
    </div>

    <!-- Forbidden with nothing to render (GET 403) ─────────────────────────── -->
    <div v-else-if="forbidden && !catalog.length" class="pol-empty">
      <Icon name="mdi:lock" class="pol-empty-ic" />
      <p class="pol-empty-title">{{ t('orgPolicySettings.accessTitle', 'Restricted') }}</p>
      <p class="pol-empty-body">
        {{ t('orgPolicySettings.accessBody', 'Only organization owners and admins can view or change policy settings.') }}
      </p>
    </div>

    <!-- Load error ─────────────────────────────────────────────────────────── -->
    <div v-else-if="loadError" class="pol-alert pol-alert--error" role="alert">
      <Icon name="mdi:alert-octagon" class="pol-alert-ic" />
      <span>{{ loadError }}</span>
      <button class="pol-retry" @click="load">{{ t('orgPolicySettings.retry', 'Retry') }}</button>
    </div>

    <!-- Form / read-only view ──────────────────────────────────────────────── -->
    <template v-else>
      <div v-if="!effectiveCanEdit && catalog.length" class="pol-alert pol-alert--info">
        <Icon name="mdi:information-outline" class="pol-alert-ic" />
        <span>{{ t('orgPolicySettings.readOnly', 'Read-only — only owners and admins can change organization policy.') }}</span>
      </div>

      <!-- No tightenable controls exposed by this registry ─────────────────────── -->
      <div v-if="!catalog.length" class="pol-empty">
        <Icon name="mdi:tune" class="pol-empty-ic" />
        <p class="pol-empty-title">{{ t('orgPolicySettings.noControlsTitle', 'No policy controls') }}</p>
        <p class="pol-empty-body">{{ t('orgPolicySettings.noControlsBody', 'This registry exposes no organization-tightenable policy yet.') }}</p>
      </div>

      <template v-else>
      <div class="pol-fields">
        <div v-for="entry in formEntries" :key="entry.key" class="pol-field">
          <div class="pol-label-row">
            <label class="pol-label" :for="'pol-' + entry.key">{{ entry.label }}</label>
            <span
              v-if="registryValueFor(entry.key) !== undefined"
              class="pol-registry"
              :title="t('orgPolicySettings.registryTip', 'The registry-wide value your organization tightens on top of.')"
            >
              <Icon name="mdi:earth" class="pol-registry-ic" />
              {{ t('orgPolicySettings.registry', 'Registry') }}:
              <strong>{{ registryValueFor(entry.key) }}</strong>
            </span>
          </div>

          <!-- Editable -->
          <template v-if="effectiveCanEdit">
            <div v-if="entry.type === 'enum'" class="pol-select-wrap">
              <select
                :id="'pol-' + entry.key"
                v-model="form[entry.key]"
                class="pol-input pol-select"
                @change="onEdit"
              >
                <option
                  v-for="opt in (entry.values || [])"
                  :key="opt"
                  :value="opt"
                  :disabled="isOptionLooser(entry.key, opt)"
                >
                  {{ opt }}<template v-if="isOptionLooser(entry.key, opt)"> {{ t('orgPolicySettings.belowFloor', '— below registry floor (no effect)') }}</template>
                </option>
              </select>
              <svg class="pol-select-arrow" viewBox="0 0 10 6" fill="none" aria-hidden="true">
                <path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              </svg>
            </div>
            <!-- §OCOPTIN: bool settings render as a switch-style checkbox -->
            <label v-else-if="entry.type === 'bool'" class="pol-bool-row" :data-testid="'pol-bool-' + entry.key">
              <input
                :id="'pol-' + entry.key"
                v-model="form[entry.key]"
                type="checkbox"
                class="pol-bool"
                @change="onEdit"
              />
              <span class="pol-bool-state">{{ form[entry.key] ? t('common.on', 'On') : t('common.off', 'Off') }}</span>
            </label>
            <input
              v-else
              :id="'pol-' + entry.key"
              v-model="form[entry.key]"
              type="number"
              class="pol-input"
              :min="entry.min"
              :max="entry.max"
              @input="onEdit"
            />
          </template>

          <!-- Read-only -->
          <div v-else class="pol-readonly">{{ displayValue(entry) }}</div>

          <!-- Help + tighten-only hint -->
          <p v-if="entry.help" class="pol-hint pol-hint--muted">{{ entry.help }}</p>
          <p v-if="tightenHint(entry)" class="pol-hint">
            <Icon name="mdi:information-outline" class="pol-hint-ic" />
            <span>{{ tightenHint(entry) }}</span>
          </p>
          <!-- Live "no effect" warning: the typed value is looser than the floor -->
          <p v-if="looserThanFloor(entry)" class="pol-hint pol-hint--warn" role="status" aria-live="polite">
            <Icon name="mdi:alert" class="pol-hint-ic" />
            <span>{{ t('orgPolicySettings.looserNoEffect', 'Above the registry floor — the registry’s stricter value still applies.') }}</span>
          </p>
        </div>

        <!-- §ORGSPEND: per-member maps are edited where the members are, not here -->
        <div v-for="entry in objectEntries" :key="entry.key" class="pol-field" data-testid="pol-object-pointer">
          <div class="pol-label-row">
            <span class="pol-label">{{ entry.label }}</span>
          </div>
          <div class="pol-readonly">
            {{ t('orgPolicySettings.perMemberPointer', 'Per-member — edit in the Members tab (Procurement column).') }}
          </div>
          <p v-if="entry.help" class="pol-hint pol-hint--muted">{{ entry.help }}</p>
        </div>
      </div>

      <!-- Actions -->
      <div v-if="effectiveCanEdit" class="pol-actions">
        <span v-if="saveError" class="pol-msg pol-msg--error" role="alert">
          <Icon name="mdi:alert-octagon" class="pol-msg-ic" />
          <span>{{ saveError }}</span>
        </span>
        <span v-else-if="saved" class="pol-msg pol-msg--ok" role="status" aria-live="polite">
          <Icon name="check-circle" class="pol-msg-ic" />
          <span>{{ t('orgPolicySettings.saved', 'Policy saved') }}</span>
        </span>
        <button class="pol-btn" :disabled="saving" @click="save">
          <span v-if="saving">{{ t('orgPolicySettings.saving', 'Saving…') }}</span>
          <span v-else>{{ t('orgPolicySettings.save', 'Save policy') }}</span>
        </button>
      </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
/* Mirrors the OrganizationDashboard settings-section design language. */
.pol-root { margin-bottom: 32px; }

.pol-head { margin-bottom: 18px; }
.pol-title {
  display: flex; align-items: center; gap: 8px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.9); margin: 0 0 8px;
}
.pol-title-ic { font-size: 0.9rem; color: rgba(var(--nc-primary-rgb), 0.55); }
.pol-subtitle {
  font-size: 0.8rem; line-height: 1.6; color: rgba(148, 163, 184, 0.85);
  max-width: 560px; margin: 0;
}

.pol-fields { display: flex; flex-direction: column; gap: 20px; max-width: 560px; }
.pol-field { display: flex; flex-direction: column; gap: 6px; }

.pol-label-row {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  flex-wrap: wrap; row-gap: 4px;   /* on a narrow column the Registry chip drops below the label */
}
.pol-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: rgba(148, 163, 184, 0.8);
}
.pol-registry {
  display: inline-flex; align-items: center; gap: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; font-weight: 600; letter-spacing: 0.05em;
  color: rgba(148, 163, 184, 0.8);
  padding: 2px 8px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  white-space: nowrap;
}
.pol-registry strong { color: rgba(var(--nc-primary-rgb), 0.75); font-weight: 700; }
.pol-registry-ic { font-size: 0.72rem; color: rgba(148, 163, 184, 0.35); }

.pol-input {
  background: rgba(6, 11, 20, 0.7);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.15);
  border-radius: 6px; padding: 9px 12px;
  color: rgba(226, 232, 240, 0.85); font-size: 0.85rem; outline: none;
  transition: border-color 0.15s;
}
.pol-input:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.38);
  box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.12);   /* keyboard-visible focus ring */
}
/* Enum control: appearance:none strips the native caret, so draw our own (matches the
   dashboard's .org-selector arrow) — otherwise the select reads as a plain text field. */
.pol-select-wrap { position: relative; display: block; }
.pol-select { width: 100%; cursor: pointer; appearance: none; padding-right: 30px; }
.pol-select-arrow {
  position: absolute; right: 12px; top: 50%; transform: translateY(-50%);
  width: 10px; height: 6px; pointer-events: none; color: rgba(148, 163, 184, 0.5);
}
.pol-select option { background: #0a1120; color: rgba(226, 232, 240, 0.85); }
.pol-select option:disabled { color: rgba(148, 163, 184, 0.35); }

.pol-readonly {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem; color: rgba(148, 163, 184, 0.85);
  padding: 9px 12px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 6px;
}

.pol-hint {
  display: flex; align-items: flex-start; gap: 6px;
  font-size: 0.74rem; line-height: 1.5; margin: 2px 0 0;
  color: rgba(var(--nc-primary-rgb), 0.9);
}
.pol-hint--muted { color: rgba(148, 163, 184, 0.8); }
/* §OCOPTIN bool control */
.pol-bool-row { display: inline-flex; align-items: center; gap: 8px; min-height: 36px; cursor: pointer; }
.pol-bool { width: 18px; height: 18px; accent-color: var(--nc-primary, #4fd8c4); cursor: pointer; }
.pol-bool-state { font-size: 0.8rem; opacity: 0.8; }
.pol-hint--warn { color: rgba(251, 191, 36, 0.9); }
.pol-hint--warn .pol-hint-ic { color: rgba(251, 191, 36, 0.85); }
.pol-hint-ic { font-size: 0.85rem; flex-shrink: 0; margin-top: 0.15em; color: rgba(var(--nc-primary-rgb), 0.55); }

.pol-actions {
  display: flex; align-items: center; justify-content: flex-end; gap: 14px;
  max-width: 560px; margin-top: 22px;
}
.pol-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em;
  padding: 8px 16px; border-radius: 6px; cursor: pointer;
  transition: all 0.15s;
  background: rgba(var(--nc-primary-rgb), 0.12);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  color: rgba(var(--nc-primary-rgb), 0.9);
}
.pol-btn:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.2);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
}
.pol-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.pol-msg {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.76rem; line-height: 1.4;
}
.pol-msg-ic { font-size: 0.9rem; flex-shrink: 0; }
.pol-msg--ok { color: rgba(52, 211, 153, 0.85); }
.pol-msg--error { color: rgba(239, 68, 68, 0.85); }

.pol-state {
  display: flex; align-items: center; gap: 10px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem; color: rgba(148, 163, 184, 0.5); padding: 12px 0;
}
.pol-spin { font-size: 1rem; animation: pol-spin 1s linear infinite; }
@keyframes pol-spin { to { transform: rotate(360deg); } }

.pol-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 40px 20px; gap: 8px; text-align: center;
}
.pol-empty-ic { font-size: 1.6rem; color: rgba(148, 163, 184, 0.2); }
.pol-empty-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 600; letter-spacing: 0.1em;
  color: rgba(148, 163, 184, 0.5); margin: 0;
}
.pol-empty-body { font-size: 0.8rem; color: rgba(148, 163, 184, 0.35); max-width: 320px; line-height: 1.6; margin: 0; }

.pol-alert {
  display: flex; align-items: center; gap: 10px;
  font-size: 0.8rem; line-height: 1.5;
  padding: 11px 14px; border-radius: 8px; margin-bottom: 18px; max-width: 560px;
}
.pol-alert-ic { font-size: 1rem; flex-shrink: 0; }
.pol-alert--info {
  color: rgba(148, 163, 184, 0.7);
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.pol-alert--error {
  color: rgba(239, 68, 68, 0.85);
  background: rgba(239, 68, 68, 0.05);
  border: 1px solid rgba(239, 68, 68, 0.2);
}
.pol-retry {
  margin-left: auto; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; font-weight: 700; letter-spacing: 0.08em;
  padding: 5px 12px; border-radius: 5px;
  background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); color: rgba(239, 68, 68, 0.85);
  transition: all 0.15s;
}
.pol-retry:hover { background: rgba(239, 68, 68, 0.18); }
</style>
