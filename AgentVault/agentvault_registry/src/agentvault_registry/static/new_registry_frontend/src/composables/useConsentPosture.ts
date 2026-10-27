/**
 * §COCKPIT P5 — the posture, fetched once per surface and SHARED.
 *
 * §8: "the client renders the posture in force; the server enforces it." Two things
 * follow, and both are why this is a module-level singleton rather than per-component
 * state:
 *
 *  1. Every surface must agree about which dials are in force. Two panes reading the
 *     posture independently can disagree for a whole poll interval, and the one that
 *     is wrong will either offer a control the server will refuse or hide one it would
 *     have accepted.
 *  2. The client's copy is a LABEL, never a gate. Nothing here decides whether an
 *     action is allowed — the server does, and refuses with a body that says why. If
 *     this fetch fails we fall back to the strictest presentation we can render
 *     honestly, because a surface that guesses "swift" when the truth is "hardened"
 *     invites a human to try something that will be refused.
 */
import { ref, computed } from 'vue'
import { liabilityApi, type ConsentPosture } from '@/services/api/liability'

const posture = ref<ConsentPosture | null>(null)
const loading = ref(false)
const failed = ref(false)
let inflight: Promise<void> | null = null

/** The read floor we render a countdown against when the server has not told us.
 *  The HARDEST bundle's floor: over-waiting is a slower confirm, under-waiting is a
 *  button that looks live and answers 425. */
const CONSERVATIVE_READ_FLOOR_MS = 3000

async function load(force = false): Promise<void> {
  if (posture.value && !force) return
  if (inflight) return inflight
  loading.value = true
  inflight = (async () => {
    try {
      posture.value = await liabilityApi.posture()
      failed.value = false
    } catch {
      // 404 = liability is off on this registry; anything else is an outage. Either
      // way we hold no posture and the callers below present conservatively.
      posture.value = null
      failed.value = true
    } finally {
      loading.value = false
      inflight = null
    }
  })()
  return inflight
}

export function useConsentPosture() {
  return {
    posture: computed(() => posture.value),
    loading: computed(() => loading.value),
    failed: computed(() => failed.value),
    name: computed(() => posture.value?.posture ?? null),
    readFloorMs: computed(() => posture.value?.dials.read_floor_ms ?? CONSERVATIVE_READ_FLOOR_MS),
    /** Can this surface offer its OWN authenticator, or must the answer come from a
     *  separate device? `swift` explicitly allows the desk's platform authenticator;
     *  the stricter bundles require a device this surface is not. */
    deskAuthenticatorAllowed: computed(
      () => posture.value?.dials.device_render === 'core_line_desk_authenticator_ok'),
    methodFloor: computed(() => posture.value?.dials.method_floor ?? 'webauthn_uv'),
    streakBadgeAt: computed(() => posture.value?.dials.streak_badge_at ?? 3),
    load,
    refresh: () => load(true),
  }
}
