<script setup lang="ts">
/**
 * §COCKPITFRAME F5 (2026-09-01) — an agent identity that opens, or honestly does not.
 *
 * Nine desk panes render an agent name with its DID already in `:title` and nothing behind
 * it. This is the one component that turns that into a door, so the affordance, the hit
 * target, the keyboard path and the refusal are decided once.
 *
 * 🔴 A NAME THAT CANNOT BE OPENED RENDERS AS TEXT, NOT AS A DEAD LINK. `agentops` already
 * knows which pins the registry refused to resolve (`_unresolved`), and a DID-shaped string
 * is the minimum the modal can fetch. Anything else stays a plain span: §DISCREFINE's blank
 * promise is a door that is visibly there and leads nowhere.
 *
 * 🔴 ONE ROOT ELEMENT, chosen by `<component :is>` rather than v-if/v-else. Attribute
 * fallthrough is what lets a caller write `<AgentLink class="rat-name" …>` and keep the
 * pane's own ellipsis/flex rules — and the parent's SCOPED css applies to a child's root.
 * Two roots in a v-if chain is a subtler contract than this is worth.
 *
 * ⚠ THE LABEL IS THE ACCESSIBLE NAME AND NOTHING IS APPENDED TO IT. §COCKPITPOLISH made the
 * opposite mistake twice in one hour (a bullet in a chip's text run, a dot in an
 * `<option>`), breaking every selector that addressed those controls by name. The hint
 * rides `title`, never the text.
 *
 * 🔴 A COMPONENT'S OWN `data-testid` IS NOT ITS OWN WHEN A CALLER PASSES ONE. Vue's
 * attribute fallthrough puts `$attrs` on the root and, for anything but class/style, the
 * INHERITED value wins — silently. Six of the nine panes keep an existing testid that other
 * batteries already address (`chn-who`, `ckd-stop-agent`, `rat-name`), so those roots publish
 * the caller's name and the component's own is nowhere. MEASURED: 17 links on the board, 13
 * findable by `[data-testid="ckd-agent-link"]`, and the PLAIN ones in `agentops`
 * unaddressable entirely. So the state that matters rides `data-door`, a name no caller
 * uses and therefore one nothing can mask. Same family as decoration joining the text run:
 * an attribute collision that makes a control unaddressable by the name it declares.
 *
 * ⚠ `@click.stop` ONLY when this is a link. Several of these sit inside a row that is
 * itself clickable (agentops selects a row to show its deployments); swallowing the click
 * on a PLAIN name would break the row underneath for exactly the identities that have no
 * card to open.
 */
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { openAgent, isOpenable } from '@/services/cockpit/agentDoor'

const props = withDefaults(defineProps<{
  did?: string | null
  /** What to render. Falls back to the DID, then to an em dash. */
  label?: string | null
  /** The caller KNOWS this identity could not be resolved — render as text. */
  unresolved?: boolean
  /** Extra first line for the tooltip; the DID is added when it is not the label. */
  hint?: string | null
}>(), { did: '', label: '', unresolved: false, hint: '' })

const { t } = useI18n()

const text = computed(() => String(props.label || props.did || '—'))
const openable = computed(() => !props.unresolved && isOpenable(props.did))
const title = computed(() => {
  const parts = [props.hint || '', props.did && props.did !== text.value ? props.did : '']
    .filter(Boolean)
  if (openable.value) parts.push(t('cockpit.door.open', 'Open this agent’s card'))
  return parts.join(' — ')
})

function onClick(e: MouseEvent) {
  if (!openable.value) return
  e.stopPropagation()
  openAgent(props.did, text.value)
}
</script>

<template>
  <component :is="openable ? 'button' : 'span'"
             class="ckd-alink" :class="{ 'is-open': openable }"
             :type="openable ? 'button' : undefined"
             :data-door="openable ? 'open' : 'plain'"
             :data-testid="openable ? 'ckd-agent-link' : 'ckd-agent-plain'"
             :data-did="did || undefined"
             :title="title || undefined"
             @click="onClick">{{ text }}</component>
</template>

<style scoped>
/* Inherits everything from the caller's own class (font, colour, flex, ellipsis) — this
   only undoes the button defaults that would otherwise fight it. */
.ckd-alink {
  font: inherit; color: inherit; letter-spacing: inherit; text-transform: inherit;
  background: none; border: 0; padding: 0; margin: 0; text-align: inherit;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ckd-alink.is-open { cursor: pointer; }
.ckd-alink.is-open:hover, .ckd-alink.is-open:focus-visible { text-decoration: underline; }
</style>
