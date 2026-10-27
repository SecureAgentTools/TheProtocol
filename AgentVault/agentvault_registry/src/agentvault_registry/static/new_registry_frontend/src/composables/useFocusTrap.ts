/**
 * useFocusTrap — keyboard focus management for modals (G, 2026-05-08).
 *
 * Closes the WCAG focus-trap gap. When a modal is open, Tab cycles focus
 * within the modal's focusable descendants. Escape continues to be handled
 * by the modal's own logic (we don't override). When the modal closes,
 * focus is restored to the element that was focused before the modal opened.
 *
 * Usage:
 *   import { useFocusTrap } from '@/composables/useFocusTrap'
 *   const containerRef = ref<HTMLElement | null>(null)
 *   const { activate, deactivate } = useFocusTrap(containerRef)
 *
 *   watch(showModal, (open) => {
 *     if (open) {
 *       nextTick(() => activate())   // wait for DOM render
 *     } else {
 *       deactivate()
 *     }
 *   })
 *
 * Or simpler — pass `:auto-activate-when="showModal"` and let the
 * composable manage activation via watch internally:
 *   useFocusTrap(containerRef, { activeWhen: showModal })
 *
 * Behavior:
 * - On activate: stores `document.activeElement`, focuses the first
 *   focusable element inside container (or container itself if it has
 *   tabindex).
 * - On Tab keydown anywhere: if focus is at the last focusable element,
 *   wraps to the first; if at the first and Shift+Tab, wraps to the last.
 * - On deactivate: restores focus to the previously-focused element.
 *
 * Edge cases:
 * - Multiple modals stacked: each owns its own trap; the most-recently-
 *   activated one wins (we listen at document level with capture=true).
 *   Callers should call activate/deactivate in lifo order.
 * - Container has no focusable elements: focuses the container itself
 *   (requires tabindex=-1 or 0).
 * - SSR: composable is a no-op when document is undefined.
 */

import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'
import { useLogger } from './useLogger'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'area[href]',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  'button:not([disabled])',
  'iframe',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
  'audio[controls]',
  'video[controls]',
  'details > summary:first-of-type',
].join(', ')

export interface UseFocusTrapOptions {
  /** Reactive boolean — when true, trap is active. Composable handles
   *  activate/deactivate via watcher. If omitted, caller drives manually. */
  activeWhen?: Ref<boolean>
  /** Optional initial focus selector. Defaults to first focusable. */
  initialFocus?: string
}

export interface UseFocusTrapReturn {
  activate: () => void
  deactivate: () => void
  isActive: () => boolean
}

export function useFocusTrap(
  containerRef: Ref<HTMLElement | null>,
  options: UseFocusTrapOptions = {},
): UseFocusTrapReturn {
  const log = useLogger('useFocusTrap')
  let active = false
  let previouslyFocused: HTMLElement | null = null

  function getFocusable(): HTMLElement[] {
    const container = containerRef.value
    if (!container) return []
    return Array.from(
      container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    ).filter((el) => {
      // Filter out hidden / display:none elements
      return el.offsetParent !== null || getComputedStyle(el).position === 'fixed'
    })
  }

  function onKeyDown(e: KeyboardEvent) {
    if (!active) return
    if (e.key !== 'Tab') return
    const focusable = getFocusable()
    if (focusable.length === 0) {
      // No focusable inside — keep focus on container
      e.preventDefault()
      containerRef.value?.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const activeEl = document.activeElement as HTMLElement | null

    if (e.shiftKey) {
      // Shift+Tab on first → wrap to last
      if (activeEl === first || !containerRef.value?.contains(activeEl)) {
        e.preventDefault()
        last.focus()
      }
    } else {
      // Tab on last → wrap to first
      if (activeEl === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  function activate() {
    if (active) return
    if (typeof document === 'undefined') return
    active = true
    previouslyFocused = (document.activeElement as HTMLElement) || null
    document.addEventListener('keydown', onKeyDown, true)
    // Focus the first focusable (or initialFocus selector if provided).
    // Wrap in a microtask so caller can activate synchronously after render.
    queueMicrotask(() => {
      if (!active) return
      const container = containerRef.value
      if (!container) return
      let target: HTMLElement | null = null
      if (options.initialFocus) {
        target = container.querySelector<HTMLElement>(options.initialFocus)
      }
      if (!target) {
        const focusable = getFocusable()
        target = focusable[0] || container
      }
      try {
        target.focus()
      } catch (e) {
        log.warn('focus failed', e)
      }
    })
  }

  function deactivate() {
    if (!active) return
    active = false
    if (typeof document !== 'undefined') {
      document.removeEventListener('keydown', onKeyDown, true)
    }
    // Restore focus to the previously-focused element. Some elements (like
    // closing buttons) may have been removed from DOM; guard.
    if (previouslyFocused && document.body.contains(previouslyFocused)) {
      try {
        previouslyFocused.focus()
      } catch { /* non-fatal */ }
    }
    previouslyFocused = null
  }

  // If activeWhen ref provided, wire activate/deactivate automatically.
  if (options.activeWhen) {
    watch(options.activeWhen, async (on) => {
      if (on) {
        // The v-if content this trap guards renders on the SAME flip that
        // turned activeWhen on — the watcher fires before that render, so
        // containerRef is still null. Wait one tick, then re-check the flag
        // (a fast close during the tick must not re-activate a dead trap).
        await nextTick()
        if (options.activeWhen!.value) activate()
      } else deactivate()
      // immediate: a sheet can MOUNT with its flag already true (deep links
      // like ?sheet=send set the flag before the component exists) — a lazy
      // watcher never fires for that first true and the trap stays dead.
    }, { immediate: true })
  }

  onBeforeUnmount(() => {
    deactivate()
  })

  return { activate, deactivate, isActive: () => active }
}
