<!--
  EmptyReason.vue: the one line under a list that is empty FOR A REASON (V0663, his yes seq 3068).

  An empty list says nothing about why: a filtered Discovery with no match, a firms list nobody has joined yet, a quiet ledger
  all look the same, and a person cannot tell "nothing here" from "nothing matches" from "nothing has happened". This is the
  small line that says which. It is not EmptyState (the large block with an icon and a call to action); use it beside or
  instead of a list's bare "none".

  Usage:
    <EmptyReason kind="filtered" reason="Nothing matches the search "x" and certified only." action-label="Clear filters" @action="clear" />
    <EmptyReason kind="none-yet" reason="No organization has opted in yet." />
    <EmptyReason kind="quiet">The ledger is quiet: no event has moved since this page opened.</EmptyReason>

  kind: filtered (a filter or a search narrowed it to nothing) · none-yet (nothing has been made here) · quiet (nothing has
  happened lately) · waiting (the first answer has not arrived). data-kind carries it for tests.
-->
<template>
  <p class="er" :class="`er--${kind}`" role="status" data-testid="empty-reason" :data-kind="kind">
    <span class="er-text"><slot>{{ reason }}</slot></span>
    <button v-if="actionLabel" type="button" class="er-action" data-testid="empty-reason-action" @click="$emit('action')">
      {{ actionLabel }}
    </button>
  </p>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  kind?: 'filtered' | 'none-yet' | 'quiet' | 'waiting'
  reason?: string
  actionLabel?: string
}>(), { kind: 'none-yet' })

defineEmits<{ (e: 'action'): void }>()
</script>

<style scoped>
.er {
  margin: 0;
  padding: 0.15rem 0 0.15rem 0.75rem;
  border-left: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  color: var(--nc-text-muted, #8f9399);
  font-size: 0.85rem;
  line-height: 1.5;
  text-align: left;
}
.er-text { overflow-wrap: anywhere; }   /* a long filter name never pushes the line past its box */
.er--filtered { border-left-color: rgba(255, 149, 0, 0.45); }
.er--quiet { border-left-color: rgba(var(--nc-primary-rgb), 0.18); }
.er-action {
  margin-left: 0.6rem;
  padding: 0;
  background: none;
  border: none;
  color: var(--nc-primary, #00d2d2);
  font: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.er-action:focus-visible { outline: 1px solid var(--nc-primary, #00d2d2); outline-offset: 2px; }
</style>
