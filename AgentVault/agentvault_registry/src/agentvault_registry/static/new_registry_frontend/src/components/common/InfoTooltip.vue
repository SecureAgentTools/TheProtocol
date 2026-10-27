<!--
  InfoTooltip — single-source-of-truth contextual help affordance.

  Shipped 2026-05-15 §pass15 (Phase F-3). Wraps a small `(i)` icon that
  opens a popover with explanation text. Topic-keyed lookup goes through
  composables/useTutorialRegistry so adding a new tooltip is a one-liner.

  Usage:
    <InfoTooltip topic="did" />
    <InfoTooltip topic="hri-slug" placement="right" size="sm" />
    <InfoTooltip topic="client-secret-once" :require-ack="true" @ack="onAck" />

  Three trigger classes from the registry:
    • passive       — click to open, click outside / Esc to close
    • first-touch   — auto-opens once per device on mount, then becomes passive
    • forced-read   — render as a banner (not the (i) icon); must be ack'd

  Accessibility:
    • Keyboard: focus the trigger, Enter/Space to open, Esc to close
    • aria-expanded on the trigger, aria-haspopup="dialog"
    • Reduced-motion: skip the open/close transition
-->
<template>
  <span
    class="itt-root"
    :class="[
      `itt-size-${size}`,
      `itt-placement-${placement}`,
      { 'itt-open': isOpen, 'itt-forced': trigger === 'forced-read' },
    ]"
  >
    <!-- ──────────────────── Forced-read banner ──────────────────── -->
    <template v-if="trigger === 'forced-read'">
      <div class="itt-banner" role="alert">
        <span class="itt-banner-icon">!</span>
        <div class="itt-banner-body">
          <div v-if="title" class="itt-banner-title">{{ title }}</div>
          <div class="itt-banner-text">{{ body }}</div>
          <a v-if="entry?.learnMoreUrl" :href="entry.learnMoreUrl" target="_blank" rel="noopener" class="itt-banner-link">
            {{ t('tutorial.learnMore') }}
          </a>
        </div>
        <button
          v-if="requireAck"
          type="button"
          class="itt-banner-ack"
          @click="onAck"
        >{{ t('tutorial.ack') }}</button>
      </div>
    </template>

    <!-- ──────────────── Passive / first-touch (i) icon ──────────────── -->
    <template v-else>
      <button
        ref="triggerEl"
        type="button"
        class="itt-trigger"
        :aria-expanded="isOpen"
        aria-haspopup="dialog"
        :aria-label="ariaLabel || `${t('tutorial.learnMore')}: ${title || topic}`"
        @click.stop="toggle"
        @keydown.esc="close"
      >
        <!-- (i) glyph — vector for crisp rendering at any size -->
        <svg viewBox="0 0 16 16" class="itt-glyph" aria-hidden="true">
          <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.4" fill="none" />
          <circle cx="8" cy="4.4" r="1" fill="currentColor" />
          <path d="M8 7 L8 11.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
        </svg>
      </button>

      <Transition name="itt-pop">
        <div
          v-if="isOpen"
          ref="popoverEl"
          class="itt-popover"
          role="dialog"
          :aria-labelledby="title ? `itt-title-${uid}` : undefined"
          @click.stop
        >
          <div class="itt-popover-arrow" aria-hidden="true"></div>
          <div class="itt-popover-head">
            <span v-if="title" :id="`itt-title-${uid}`" class="itt-popover-title">{{ title }}</span>
            <button
              type="button"
              class="itt-popover-close"
              :aria-label="t('tutorial.close')"
              @click="close"
            >
              <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
                <path d="M2 2l8 8M10 2L2 10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              </svg>
            </button>
          </div>
          <div class="itt-popover-body">{{ body }}</div>
          <a
            v-if="entry?.learnMoreUrl"
            :href="entry.learnMoreUrl"
            target="_blank"
            rel="noopener"
            class="itt-popover-link"
          >
            {{ t('tutorial.learnMore') }} ↗
          </a>
        </div>
      </Transition>
    </template>
  </span>
</template>

<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useTutorialRegistry, type TopicId, type TriggerClass } from '@/composables/useTutorialRegistry'

const { t, te } = useI18n()
const registry = useTutorialRegistry()

const props = withDefaults(defineProps<{
  /** Topic key from useTutorialRegistry. */
  topic: TopicId
  /** Override the registry's default triggerHook. */
  triggerOverride?: TriggerClass | null
  /** Where the popover opens relative to the trigger. */
  placement?: 'top' | 'right' | 'bottom' | 'left'
  /** Visual size of the (i) icon. */
  size?: 'xs' | 'sm' | 'md'
  /** Forced-read variant requires an explicit ack click before consumer can proceed. */
  requireAck?: boolean
  /** Override the trigger's accessible label. */
  ariaLabel?: string | null
}>(), {
  triggerOverride: null,
  placement: 'right',
  size: 'sm',
  requireAck: false,
  ariaLabel: null,
})

const emit = defineEmits<{
  (e: 'open'): void
  (e: 'close'): void
  /** Forced-read: user acknowledged. */
  (e: 'ack'): void
}>()

const uid = Math.random().toString(36).slice(2, 9)
const isOpen = ref(false)
const triggerEl = ref<HTMLElement | null>(null)
const popoverEl = ref<HTMLElement | null>(null)

const entry = computed(() => registry.entry(props.topic))
const trigger = computed<TriggerClass>(() => props.triggerOverride ?? entry.value?.triggerHook ?? 'passive')

const title = computed<string>(() => {
  const k = `tutorial.topics.${props.topic}.title`
  return te(k) ? t(k) : ''
})
const body = computed<string>(() => {
  const k = `tutorial.topics.${props.topic}.body`
  return te(k) ? t(k) : (entry.value?.shortHint || props.topic)
})

function open() {
  if (isOpen.value) return
  isOpen.value = true
  emit('open')
}
function close() {
  if (!isOpen.value) return
  isOpen.value = false
  emit('close')
  // Once a first-touch tooltip has been viewed (open then close), mark as dismissed
  // so it doesn't re-auto-pop on future mounts.
  if (trigger.value === 'first-touch' && !registry.isDismissed(props.topic)) {
    registry.dismiss(props.topic)
  }
}
function toggle() { isOpen.value ? close() : open() }
function onAck() {
  registry.dismiss(props.topic)
  emit('ack')
}

// Outside-click + Esc closure
function onWindowClick(e: MouseEvent) {
  if (!isOpen.value) return
  const target = e.target as HTMLElement
  if (!target) return
  if (popoverEl.value?.contains(target)) return
  if (triggerEl.value?.contains(target)) return
  close()
}
function onWindowKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && isOpen.value) close()
}

onMounted(() => {
  if (typeof window !== 'undefined') {
    window.addEventListener('click', onWindowClick)
    window.addEventListener('keydown', onWindowKey)
  }
  // first-touch auto-open
  if (registry.shouldAutoOpen(props.topic) && trigger.value === 'first-touch') {
    // Defer one tick so the trigger element is laid out before we anchor.
    setTimeout(() => { isOpen.value = true; emit('open') }, 320)
  }
})
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('click', onWindowClick)
    window.removeEventListener('keydown', onWindowKey)
  }
})

// Allow programmatic open via a `?tour=<topic>` query param — surfaces watching
// this composable can emit an open via the registry, but for simplicity we let
// the parent surface signal via a `triggerOverride` swap at mount time if it
// detects the route query. (Kept lean; the surface owns the watch.)
watch(() => props.topic, () => { /* re-resolve title/body via computed */ })
</script>

<style scoped>
/* ── Root + trigger button ────────────────────────────────────────────── */
.itt-root {
  position: relative;
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
  line-height: 0;
}

.itt-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px; height: 16px;
  padding: 0;
  background: transparent;
  border: none;
  color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.55);
  cursor: pointer;
  border-radius: 50%;
  transition: color 0.16s ease, background 0.16s ease, transform 0.18s ease;
  -webkit-tap-highlight-color: transparent;
}
.itt-trigger:hover,
.itt-trigger:focus-visible {
  color: rgba(var(--nc-primary-rgb), 0.95);
  background: rgba(var(--nc-primary-rgb), 0.10);
  outline: none;
  transform: scale(1.06);
}
.itt-open .itt-trigger {
  color: rgba(var(--nc-primary-rgb), 1);
  background: rgba(var(--nc-primary-rgb), 0.15);
}
.itt-glyph { width: 14px; height: 14px; }
.itt-size-xs .itt-trigger { width: 13px; height: 13px; }
.itt-size-xs .itt-glyph    { width: 11px; height: 11px; }
.itt-size-md .itt-trigger { width: 19px; height: 19px; }
.itt-size-md .itt-glyph    { width: 16px; height: 16px; }

/* ── Popover ──────────────────────────────────────────────────────────── */
.itt-popover {
  position: absolute;
  z-index: 1200;
  min-width: 240px;
  max-width: 320px;
  padding: 12px 14px;
  background: linear-gradient(180deg, rgba(18, 14, 30, 0.985), rgba(8, 6, 18, 0.985));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.42);
  border-radius: 10px;
  box-shadow:
    0 14px 40px rgba(0, 0, 0, 0.65),
    0 0 20px -4px rgba(var(--nc-primary-rgb), 0.32);
  font-size: 0.78rem;
  color: rgba(220, 215, 235, 0.92);
  text-align: left;
  line-height: 1.45;
}
.itt-placement-right .itt-popover {
  left: calc(100% + 8px);
  top: 50%;
  transform: translateY(-50%);
}
.itt-placement-left .itt-popover {
  right: calc(100% + 8px);
  top: 50%;
  transform: translateY(-50%);
}
.itt-placement-bottom .itt-popover {
  top: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
}
.itt-placement-top .itt-popover {
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
}

/* On small viewports, force-bottom placement (the right-edge popover wraps
   to under the trigger anyway when the page is narrow). */
@media (max-width: 640px) {
  .itt-popover {
    position: fixed;
    left: 16px;
    right: 16px;
    bottom: 16px;
    top: auto;
    transform: none;
    max-width: none;
    min-width: 0;
  }
  .itt-popover-arrow { display: none; }
}

/* Arrow */
.itt-popover-arrow {
  position: absolute;
  width: 8px; height: 8px;
  background: linear-gradient(135deg, rgba(18, 14, 30, 0.985), rgba(8, 6, 18, 0.985));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.42);
}
.itt-placement-right .itt-popover-arrow {
  left: -5px; top: 50%; transform: translateY(-50%) rotate(45deg);
  border-right: none; border-top: none;
}
.itt-placement-left .itt-popover-arrow {
  right: -5px; top: 50%; transform: translateY(-50%) rotate(45deg);
  border-left: none; border-bottom: none;
}
.itt-placement-bottom .itt-popover-arrow {
  top: -5px; left: 50%; transform: translateX(-50%) rotate(45deg);
  border-right: none; border-bottom: none;
}
.itt-placement-top .itt-popover-arrow {
  bottom: -5px; left: 50%; transform: translateX(-50%) rotate(45deg);
  border-left: none; border-top: none;
}

/* Popover head + body */
.itt-popover-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}
.itt-popover-title {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.70rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.95);
}
.itt-popover-close {
  flex-shrink: 0;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  width: 18px; height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(220, 215, 235, 0.65);
  cursor: pointer;
  transition: background 0.14s ease, color 0.14s ease, border-color 0.14s ease;
}
.itt-popover-close:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.20);
}
.itt-popover-body {
  font-size: 0.76rem;
  color: rgba(225, 220, 240, 0.88);
}
.itt-popover-link {
  display: inline-block;
  margin-top: 8px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.68rem;
  font-weight: 600;
  color: rgba(var(--nc-primary-rgb), 0.95);
  text-decoration: none;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-bottom: 1px dashed rgba(var(--nc-primary-rgb), 0.45);
  padding-bottom: 1px;
}
.itt-popover-link:hover {
  border-bottom-style: solid;
}

/* ── Forced-read banner ───────────────────────────────────────────────── */
.itt-banner {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 16px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.45);
  border-radius: 8px;
  font-size: 0.80rem;
  color: rgba(252, 165, 165, 0.95);
  margin: 0;
  width: 100%;
}
.itt-banner-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px; height: 22px;
  flex-shrink: 0;
  background: rgba(239, 68, 68, 0.18);
  color: rgba(252, 165, 165, 1);
  border-radius: 50%;
  font-weight: 700;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.85rem;
  border: 1px solid rgba(239, 68, 68, 0.42);
}
.itt-banner-body { flex: 1; min-width: 0; }
.itt-banner-title {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: rgba(252, 165, 165, 1);
  margin-bottom: 4px;
}
.itt-banner-text { line-height: 1.45; }
.itt-banner-link {
  display: inline-block;
  margin-top: 6px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: rgba(252, 165, 165, 0.95);
  text-decoration: none;
  border-bottom: 1px dashed rgba(252, 165, 165, 0.5);
}
.itt-banner-ack {
  flex-shrink: 0;
  background: rgba(239, 68, 68, 0.16);
  color: rgba(252, 165, 165, 1);
  border: 1px solid rgba(239, 68, 68, 0.55);
  border-radius: 6px;
  padding: 6px 14px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.70rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  cursor: pointer;
  transition: background 0.16s ease;
}
.itt-banner-ack:hover {
  background: rgba(239, 68, 68, 0.32);
}

/* ── Popover transition (skipped under reduced motion) ────────────────── */
.itt-pop-enter-active,
.itt-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.18s ease;
}
.itt-pop-enter-from,
.itt-pop-leave-to {
  opacity: 0;
  transform: translateY(-2px);
}
.itt-placement-right .itt-pop-enter-from,
.itt-placement-right .itt-pop-leave-to,
.itt-placement-left .itt-pop-enter-from,
.itt-placement-left .itt-pop-leave-to {
  transform: translateY(-50%) scale(0.96);
}
.itt-placement-bottom .itt-pop-enter-from,
.itt-placement-bottom .itt-pop-leave-to,
.itt-placement-top .itt-pop-enter-from,
.itt-placement-top .itt-pop-leave-to {
  transform: translateX(-50%) scale(0.96);
}

@media (prefers-reduced-motion: reduce) {
  .itt-trigger { transition: none; }
  .itt-pop-enter-active,
  .itt-pop-leave-active { transition: none; }
}
</style>
