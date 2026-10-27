<script setup lang="ts">
/**
 * §COCKPITUP U2 (2026-09-01) — the desk's one way to send you to a record.
 *
 * `AgentLink` opens an agent's card in a modal without leaving the desk. This is its
 * sibling for the case where the record lives in a full VIEW the app already has: a
 * contract, a dispute, a bounty, the consent history, a venue, a reward record.
 *
 * 🔴 A REAL ANCHOR, NOT A CLICK HANDLER. `router.resolve().href` means middle-click,
 * ctrl-click and "open in new tab" work — which matters here more than anywhere, because
 * the whole point of the desk is that you are watching several things at once and do not
 * want to lose the board to read one row.
 *
 * 🔴 NO DOOR RENDERS NOTHING — deliberately, and this is the one place the batch's Law 3
 * ("a door that cannot open is disabled and says why") is answered with ABSENCE instead.
 * The only gated target is the admin audit log; a non-admin is not being denied a thing
 * they were promised, they were never promised it. A disabled control saying "you are not
 * an admin" on a pane about token conservation would be noise on every load, forever.
 * Where a door is missing because a SUBJECT is missing (no agent selected), the pane says
 * so — that is a different sentence and it belongs to the pane.
 *
 * ⚠ State rides `data-record`, a name no caller uses. §COCKPITFRAME F5 measured this the
 * hard way: a caller's `data-testid` silently wins over the component's own via attribute
 * fallthrough, so 4 of 17 links were unaddressable by the name they declared.
 */
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRecordDoor, type RecordKind } from '@/services/cockpit/recordDoor'

const props = withDefaults(defineProps<{
  kind: RecordKind
  /** Route param for the parameterised targets (agent, agentCicd). */
  id?: string | null
  /** Visible text. */
  label?: string | null
  /** Extra tooltip line. */
  hint?: string | null
}>(), { id: '', label: '', hint: '' })

const { t } = useI18n()
const { recordHref } = useRecordDoor()

const href = computed(() => recordHref(props.kind, props.id))
const open = computed(() => !!href.value)
const text = computed(() => String(props.label || ''))
const title = computed(() =>
  [props.hint || '', t('cockpit.door.record', 'Open the full record')].filter(Boolean).join(' — '))
</script>

<template>
  <a v-if="open" class="ckd-rlink" :href="href" :title="title"
     data-record="open" :data-record-kind="kind"
     @click.stop>{{ text }}<slot /></a>
</template>

<style scoped>
/* Inherits the caller's type so a link inside a footer reads as that footer. */
/* A door is told apart from the text around it by more than its colour (WCAG 1.4.1; axe link-in-text-block): a quiet
   underline always, the full one on hover and focus. A door often follows a sentence on the same line (.ckd-doorsep). */
.ckd-rlink {
  font: inherit; color: var(--nc-primary, #58a6ff); letter-spacing: inherit;
  text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 2px;
  text-decoration-color: rgba(var(--nc-primary-rgb, 88, 166, 255), .45);
  cursor: pointer; max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ckd-rlink:hover, .ckd-rlink:focus-visible { text-decoration-color: currentColor; }
</style>
