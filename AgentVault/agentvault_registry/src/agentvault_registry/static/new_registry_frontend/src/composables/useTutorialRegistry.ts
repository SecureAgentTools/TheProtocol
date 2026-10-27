/**
 * Tutorial registry — central catalogue of in-app explainer topics.
 *
 * Shipped 2026-05-15 §pass15 (Phase F-3) alongside the AgentForge wizard
 * consolidation. Each topic is anchored to one or more surfaces via a
 * stable `TopicId` string; views render an `<InfoTooltip topic="did" />`
 * and the component looks the entry up here.
 *
 * Three trigger classes are supported (see InfoTooltip.vue):
 *
 *   • passive       — `(i)` icon you click to open the popover. Never blocks.
 *   • first-touch   — auto-opens once per topic per device, then becomes passive.
 *                     Dismissal is persisted in localStorage.
 *   • forced-read   — must be acknowledged via an explicit button before the
 *                     surface lets you proceed. Used for once-only-secrets.
 *
 * Adding a topic:
 *   1. Append a new TopicId literal to the union below.
 *   2. Add a row to TUTORIAL_REGISTRY with title/body/triggerHook/learnMoreUrl.
 *   3. Add i18n keys under tutorialRegistry.<topicId>.{title,body} (en.json
 *      is authoritative; locales fall back to English).
 *   4. Reference from a surface: <InfoTooltip topic="<topicId>" />
 *
 * Deep linking:
 *   • Any surface using the registry can be linked-into via ?tour=<topicId>
 *     in the route URL. App.vue / the relevant view watches the query string
 *     and forces a first-touch open on mount.
 */

import { ref, computed } from 'vue'

// ─── Type contract ───────────────────────────────────────────────────────────

export type TopicId =
  // AgentForge wizard topics
  | 'did'
  | 'hri-slug'
  | 'a2a-auth'
  | 'bootstrap-token'
  | 'client-secret-once'
  | 'docker-network'
  | 'mtls-spire'
  | 'payment-required'
  | 'pricing-tier'
  // Cross-cutting platform topics
  | 'flare-grant'
  | 'discovery-publishing'
  | 'federation'

export type TriggerClass = 'passive' | 'first-touch' | 'forced-read'

export interface TutorialEntry {
  /** Stable identifier — used in localStorage keys, URLs, and InfoTooltip props. */
  id: TopicId
  /** Default trigger class. A surface may downgrade (`first-touch` → `passive`). */
  triggerHook: TriggerClass
  /** Optional deep-link to docs / a reference page. */
  learnMoreUrl?: string
  /** Optional one-line synopsis. Body text comes from i18n at render time. */
  shortHint?: string
}

// ─── The registry ────────────────────────────────────────────────────────────

export const TUTORIAL_REGISTRY: Record<TopicId, TutorialEntry> = {
  // ─── AgentForge wizard topics ──────────────────────────────────────────
  'did': {
    id: 'did',
    triggerHook: 'first-touch',
    learnMoreUrl: '/docs/agent-identity',
    shortHint: 'A DID is a cryptographically-rooted identifier for your agent.',
  },
  'hri-slug': {
    id: 'hri-slug',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/hri-slug',
    shortHint: 'The human-readable shortcut that appears in URLs and search.',
  },
  'a2a-auth': {
    id: 'a2a-auth',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/a2a-auth',
    shortHint: 'How other agents prove who they are when calling yours.',
  },
  'bootstrap-token': {
    id: 'bootstrap-token',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/bootstrap',
    shortHint: 'A short-lived one-time token that authorizes agent creation.',
  },
  'client-secret-once': {
    id: 'client-secret-once',
    triggerHook: 'forced-read',
    shortHint: "Your client_secret is shown ONCE. Save it before you leave this screen.",
  },
  'docker-network': {
    id: 'docker-network',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/docker-compose',
  },
  'mtls-spire': {
    id: 'mtls-spire',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/ironhand-mtls',
  },
  'payment-required': {
    id: 'payment-required',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/a2a-payment',
  },
  'pricing-tier': {
    id: 'pricing-tier',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/pricing',
  },
  // ─── Cross-cutting topics ──────────────────────────────────────────────
  'flare-grant': {
    id: 'flare-grant',
    triggerHook: 'passive',
    learnMoreUrl: '/founders-wall',
  },
  'discovery-publishing': {
    id: 'discovery-publishing',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/discovery',
  },
  'federation': {
    id: 'federation',
    triggerHook: 'passive',
    learnMoreUrl: '/docs/federation',
  },
}

// ─── Dismissal persistence ───────────────────────────────────────────────────

const LS_KEY = 'theprotocol:tutorial:dismissed:v1'

function readDismissed(): Set<TopicId> {
  if (typeof window === 'undefined') return new Set()
  try {
    const raw = window.localStorage.getItem(LS_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw)
    if (Array.isArray(arr)) return new Set(arr.filter((x): x is TopicId => typeof x === 'string'))
  } catch {
    // localStorage may be blocked (Safari private mode etc). Fail-open: treat
    // as no dismissals so users see first-touch tooltips. Acceptable cost.
  }
  return new Set()
}

function writeDismissed(set: Set<TopicId>): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(Array.from(set)))
  } catch {
    /* see comment in readDismissed */
  }
}

const dismissed = ref<Set<TopicId>>(readDismissed())

// ─── Public composable surface ───────────────────────────────────────────────

export function useTutorialRegistry() {
  const isDismissed = (id: TopicId): boolean => dismissed.value.has(id)

  function dismiss(id: TopicId): void {
    if (dismissed.value.has(id)) return
    const next = new Set(dismissed.value)
    next.add(id)
    dismissed.value = next
    writeDismissed(next)
  }

  function reset(id: TopicId): void {
    if (!dismissed.value.has(id)) return
    const next = new Set(dismissed.value)
    next.delete(id)
    dismissed.value = next
    writeDismissed(next)
  }

  function resetAll(): void {
    dismissed.value = new Set()
    writeDismissed(dismissed.value)
  }

  const entry = (id: TopicId): TutorialEntry | undefined => TUTORIAL_REGISTRY[id]

  /** True when a first-touch entry should auto-pop on mount. */
  function shouldAutoOpen(id: TopicId): boolean {
    const e = entry(id)
    if (!e) return false
    if (e.triggerHook !== 'first-touch') return false
    return !isDismissed(id)
  }

  const dismissedList = computed(() => Array.from(dismissed.value))

  return {
    entry,
    isDismissed,
    dismiss,
    reset,
    resetAll,
    shouldAutoOpen,
    dismissedList,
  }
}
