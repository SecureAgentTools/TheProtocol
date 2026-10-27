<template>
  <div class="fsb">
    <div class="fsb-toolbar">
      <span class="fsb-count" :class="{ 'is-changed': changedCount > 0 }" data-testid="fc-switch-count">
        <Icon :name="changedCount ? 'mdi:tune-variant' : 'mdi:check-circle-outline'" class="fsb-count-icon" />
        {{ changedLabel }}
      </span>
      <button type="button" class="fsb-reset" :disabled="!changedCount" data-testid="fc-switch-reset" @click="emit('reset')">
        <Icon name="mdi:undo-variant" />
        {{ baseline ? t('frameCommanderView.switchboard.resetFrame', 'Back to the frame\'s settings') : t('frameCommanderView.switchboard.reset', 'Reset to defaults') }}
      </button>
    </div>

    <section v-for="group in groups" :key="group.id" class="fsb-group" :class="{ 'is-open': open[group.id] }">
      <button
        type="button"
        class="fsb-group-head"
        :aria-expanded="open[group.id] ? 'true' : 'false'"
        :data-testid="'fc-switch-group-' + group.id"
        @click="open[group.id] = !open[group.id]"
      >
        <Icon :name="group.icon" class="fsb-group-icon" />
        <span class="fsb-group-copy">
          <span class="fsb-group-title">{{ group.title }}</span>
          <span class="fsb-group-lead">{{ group.lead }}</span>
        </span>
        <span v-if="group.changed" class="fsb-badge">{{ group.changed }}</span>
        <Icon name="mdi:chevron-down" class="fsb-chevron" />
      </button>

      <div v-if="open[group.id]" class="fsb-rows">
        <div
          v-for="sw in group.switches"
          :key="sw.key"
          class="fsb-row"
          :class="{ 'is-changed': isChanged(sw), 'is-locked': isLocked(sw.key) }"
          :data-testid="'fc-feature-' + sw.key"
        >
          <div class="fsb-copy">
            <div class="fsb-label">
              {{ switchText(sw, 'label') }}
              <span v-if="isChanged(sw)" class="fsb-changed">{{ t('frameCommanderView.switchboard.changed', 'changed') }}</span>
            </div>
            <p class="fsb-hint">{{ switchText(sw, 'hint') }}</p>
            <p v-if="isLocked(sw.key)" class="fsb-locked" :data-testid="'fc-feature-' + sw.key + '-locked'">
              <Icon name="mdi:lock" class="fsb-pair-icon" />
              {{ t('frameCommanderView.switchboard.lockedBy', 'Set by the frame') }}: {{ locked?.[sw.key]?.reason }}
            </p>
            <p v-if="pairOf(sw.key)" class="fsb-pair">
              <Icon name="mdi:link-variant" class="fsb-pair-icon" />
              {{ tp('frameCommanderView.switchboard.paired', 'Moves together with {other}', { other: pairLabel(sw.key) }) }}
            </p>
          </div>
          <div class="fsb-seg" role="group" :aria-label="switchText(sw, 'label')">
            <button
              v-for="opt in sw.options"
              :key="opt"
              type="button"
              class="fsb-opt"
              :class="{ 'is-on': shown(sw.key) === opt }"
              :aria-pressed="shown(sw.key) === opt ? 'true' : 'false'"
              :disabled="isLocked(sw.key)"
              :title="opt === base(sw) ? (baseline ? t('frameCommanderView.switchboard.frameValue', 'The frame\'s setting') : t('frameCommanderView.switchboard.defaultValue', 'The default')) : undefined"
              :data-testid="'fc-feature-' + sw.key + '-' + opt"
              @click="choose(sw.key, opt)"
            >
              {{ optionText(opt) }}<span v-if="opt === base(sw)" class="fsb-def" aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
/**
 * The advanced settings of a frame request: every switch in FRAME_FEATURE_SWITCHES, grouped by FEATURE_GROUPS, each
 * showing its default, whether the request changes it, and the switch it moves with. The view owns the values; this
 * only asks for a change or a reset.
 */
import { computed, reactive } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { FRAME_FEATURE_SWITCHES, type FrameFeatureSwitch } from '@/services/api/frameRequests'
import { FEATURE_GROUPS, PAIRED_FEATURES } from '@/services/frameRequestForm'

const props = defineProps<{
  features: Record<string, string>
  /** §FESUITE V0595: settings this applicant cannot choose (an operator's frame-scope ones): shown with the frame's value,
   *  their buttons disabled, the reason beside them; a change is never emitted for one */
  locked?: Record<string, { value: string; reason: string }>
  /** what "changed" is counted against: the frame's own settings on an operator application; the defaults otherwise */
  baseline?: Record<string, string>
}>()
const emit = defineEmits<{
  (e: 'change', key: string, value: string): void
  (e: 'reset'): void
}>()

const { t, tp } = useI18n()

const BY_KEY = new Map(FRAME_FEATURE_SWITCHES.map(sw => [sw.key, sw]))

const isLocked = (key: string): boolean => Boolean(props.locked && props.locked[key])
const base = (sw: FrameFeatureSwitch): string => props.baseline?.[sw.key] ?? sw.def
const shown = (key: string): string | undefined => (isLocked(key) ? props.locked![key].value : props.features[key])
const isChanged = (sw: FrameFeatureSwitch): boolean =>
  !isLocked(sw.key) && props.features[sw.key] !== undefined && props.features[sw.key] !== base(sw)
function choose(key: string, value: string) {
  if (!isLocked(key)) emit('change', key, value)
}

const switchText = (sw: FrameFeatureSwitch, part: 'label' | 'hint'): string =>
  tp('frameCommanderView.switches.' + sw.key + '.' + part, part === 'label' ? sw.label : sw.hint, {})

const optionText = (opt: string): string => {
  const words: Record<string, string> = {
    yes: t('frameCommanderView.options.yes', 'On'),
    no: t('frameCommanderView.options.no', 'Off'),
    off: t('frameCommanderView.options.off', 'Off'),
    shadow: t('frameCommanderView.options.shadow', 'Shadow'),
    enforce: t('frameCommanderView.options.enforce', 'Enforce'),
    on: t('frameCommanderView.options.on', 'On'),
    member: t('frameCommanderView.options.member', 'Member'),
    lock: t('frameCommanderView.options.lock', 'Lock'),
  }
  return words[opt] || opt
}

const pairOf = (key: string): string | null => {
  for (const [a, b] of PAIRED_FEATURES) {
    if (key === a) return b
    if (key === b) return a
  }
  return null
}

const pairLabel = (key: string): string => {
  const other = pairOf(key)
  const sw = other ? BY_KEY.get(other) : undefined
  return sw ? switchText(sw, 'label') : ''
}

const changedCount = computed(() => FRAME_FEATURE_SWITCHES.filter(isChanged).length)

const changedLabel = computed(() => {
  const n = changedCount.value
  if (props.baseline) {
    if (n === 0) return t('frameCommanderView.switchboard.allFrame', 'Every setting as the frame runs it')
    if (n === 1) return t('frameCommanderView.switchboard.changedOneFrame', 'One setting differs from the frame\'s')
    return tp('frameCommanderView.switchboard.changedManyFrame', '{n} settings differ from the frame\'s', { n })
  }
  if (n === 0) return t('frameCommanderView.switchboard.allDefault', 'Every setting at its default')
  if (n === 1) return t('frameCommanderView.switchboard.changedOne', 'One setting differs from the default')
  return tp('frameCommanderView.switchboard.changedMany', '{n} settings differ from the default', { n })
})

const groupMeta = computed<Record<string, { icon: string; title: string; lead: string }>>(() => ({
  economy: {
    icon: 'mdi:bank-transfer',
    title: t('frameCommanderView.switchboard.groups.economyTitle', 'Economy'),
    lead: t('frameCommanderView.switchboard.groups.economyLead', 'Markets, paid work, contracts and money in'),
  },
  agents: {
    icon: 'mdi:robot-outline',
    title: t('frameCommanderView.switchboard.groups.agentsTitle', 'Agents'),
    lead: t('frameCommanderView.switchboard.groups.agentsLead', 'What agents may do, for whom, and what they can prove'),
  },
  access: {
    icon: 'mdi:shield-lock-outline',
    title: t('frameCommanderView.switchboard.groups.accessTitle', 'Access'),
    lead: t('frameCommanderView.switchboard.groups.accessLead', 'Who gets in, and how people and agents talk'),
  },
  governance: {
    icon: 'mdi:gavel',
    title: t('frameCommanderView.switchboard.groups.governanceTitle', 'Governance'),
    lead: t('frameCommanderView.switchboard.groups.governanceLead', 'How the network decides, and what it is checked against'),
  },
  operations: {
    icon: 'mdi:tools',
    title: t('frameCommanderView.switchboard.groups.operationsTitle', 'Operations'),
    lead: t('frameCommanderView.switchboard.groups.operationsLead', 'Synthetic traffic, load and test harnesses'),
  },
}))

const groups = computed(() => FEATURE_GROUPS.map(g => ({
  id: g.id,
  ...groupMeta.value[g.id],
  switches: g.keys.map(k => BY_KEY.get(k)).filter((sw): sw is FrameFeatureSwitch => Boolean(sw)),
  changed: g.keys.filter(k => {
    const sw = BY_KEY.get(k)
    return sw && isChanged(sw)
  }).length,
})))

// The first group opens, and so does any group a restored draft already changed.
const open = reactive<Record<string, boolean>>(Object.fromEntries(FEATURE_GROUPS.map((g, i) => [
  g.id,
  i === 0 || g.keys.some(k => { const sw = BY_KEY.get(k); return Boolean(sw && isChanged(sw)) }),
])))
</script>

<style scoped>
.fsb { display: flex; flex-direction: column; gap: 10px; }
.fsb-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.fsb-count { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted, #7d8594); }
.fsb-count.is-changed { color: var(--nc-primary); }
.fsb-count-icon { font-size: 15px; }
.fsb-reset {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 7px; font-size: 12px; cursor: pointer;
  background: transparent; color: var(--text-secondary, #b8c0cc);
  border: 1px solid var(--border, rgba(255,255,255,0.1));
  transition: border-color 0.16s, color 0.16s;
}
.fsb-reset:hover:not(:disabled) { color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.4); }
.fsb-reset:disabled { opacity: 0.45; cursor: default; }
.fsb-row.is-locked .fsb-opt { cursor: not-allowed; }
.fsb-row.is-locked .fsb-opt:not(.is-on) { opacity: 0.45; }
.fsb-locked { display: flex; align-items: center; gap: 6px; margin-top: 4px; font-size: 11.5px; color: var(--text-secondary, #b8c0cc); }

.fsb-group {
  border-radius: 10px; overflow: hidden;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  background: rgba(var(--nc-primary-rgb), 0.02);
}
.fsb-group.is-open { border-color: rgba(var(--nc-primary-rgb), 0.24); }
.fsb-group-head {
  width: 100%; display: flex; align-items: center; gap: 12px;
  padding: 12px 14px; cursor: pointer; text-align: left;
  background: transparent; border: 0; color: inherit;
}
.fsb-group-head:hover { background: rgba(var(--nc-primary-rgb), 0.04); }
.fsb-group-head:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.5); outline-offset: -2px; }
.fsb-group-icon { font-size: 20px; color: var(--nc-primary); flex: 0 0 auto; }
.fsb-group-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.fsb-group-title { font-size: 14px; font-weight: 600; color: #fff; }
.fsb-group-lead { font-size: 12px; color: var(--muted, #7d8594); }
.fsb-badge {
  min-width: 22px; height: 22px; padding: 0 7px; border-radius: 11px;
  display: inline-flex; align-items: center; justify-content: center;
  font-family: var(--mono, ui-monospace, monospace); font-size: 11px; font-weight: 700;
  background: rgba(var(--nc-primary-rgb), 0.16); color: var(--nc-primary);
}
.fsb-chevron { font-size: 18px; color: var(--muted, #7d8594); transition: transform 0.2s; }
.fsb-group.is-open .fsb-chevron { transform: rotate(180deg); }

.fsb-rows { border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1); }
.fsb-row {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px 18px; align-items: center;
  padding: 12px 14px 12px 16px; position: relative;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.fsb-row:last-child { border-bottom: 0; }
.fsb-row.is-changed::before {
  content: ''; position: absolute; left: 0; top: 10px; bottom: 10px; width: 2px;
  border-radius: 2px; background: var(--nc-primary);
}
.fsb-copy { min-width: 0; }
.fsb-label { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px; font-weight: 600; color: var(--text, #e6e9ef); }
.fsb-changed {
  font-family: var(--mono, ui-monospace, monospace); font-size: 9px; font-weight: 700;
  letter-spacing: 0.1em; text-transform: uppercase; color: var(--nc-primary);
  padding: 1px 6px; border-radius: 4px; background: rgba(var(--nc-primary-rgb), 0.12);
}
.fsb-hint { margin: 3px 0 0; font-size: 12px; line-height: 1.5; color: var(--muted, #7d8594); }
.fsb-pair { display: flex; align-items: center; gap: 5px; margin: 5px 0 0; font-size: 11px; color: #f59e0b; }
.fsb-pair-icon { font-size: 13px; }

.fsb-seg {
  display: inline-flex; padding: 3px; gap: 2px; border-radius: 8px;
  background: rgba(0, 0, 0, 0.35); border: 1px solid var(--border, rgba(255,255,255,0.1));
}
.fsb-opt {
  position: relative; min-width: 58px; padding: 6px 11px; border-radius: 6px; cursor: pointer;
  font-size: 12px; font-weight: 600; color: var(--muted, #7d8594);
  background: transparent; border: 0; transition: background 0.16s, color 0.16s;
}
.fsb-opt:hover:not(.is-on) { color: var(--text, #e6e9ef); background: rgba(255, 255, 255, 0.04); }
.fsb-opt:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.55); outline-offset: 1px; }
.fsb-opt.is-on { background: rgba(var(--nc-primary-rgb), 0.18); color: var(--nc-primary); box-shadow: inset 0 0 0 1px rgba(var(--nc-primary-rgb), 0.35); }
.fsb-def {
  position: absolute; top: 4px; right: 4px; width: 4px; height: 4px; border-radius: 50%;
  background: rgba(255, 255, 255, 0.35);
}
@media (max-width: 640px) {
  /* On a phone a group sits inside the advanced block inside the step panel; as a third box it left the hints a column
     of about 270px at 400px wide. Here a group is a ruled section. */
  .fsb-group { border-radius: 0; border-width: 1px 0 0; background: transparent; }
  .fsb-group-head { padding: 12px 2px; }
  .fsb-row { grid-template-columns: minmax(0, 1fr); padding: 12px 2px 12px 10px; }
  .fsb-seg { justify-self: start; }
}
</style>
