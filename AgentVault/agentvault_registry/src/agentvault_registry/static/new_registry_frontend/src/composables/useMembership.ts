/**
 * composables/useMembership.ts — §MEMBERSHIP (2026-10-02): ONE membership picture per console session.
 *
 * The Senate floor, its membership panel, the vote dialog and Pocket all ask "am I a member, with which weight". They
 * read it here, so one load serves them all and a vote that changes nothing about membership never refetches it per
 * surface. `me` needs a signed-in developer; without one the state is `signed-out` and only the public stats load
 * (a visitor's request must never run the app's 401 handling, §DISCPUBLIC).
 */
import { ref } from 'vue'
import { membershipApi } from '@/services/api/membership'
import type { MembershipStats, MyMembership } from '@/services/membership/membership'
import { useAuthStore } from '@/stores/auth'

export type MembershipState = 'idle' | 'loading' | 'ready' | 'signed-out' | 'failed'

const me = ref<MyMembership | null>(null)
const stats = ref<MembershipStats | null>(null)
const state = ref<MembershipState>('idle')
let inflight: Promise<void> | null = null

async function load(force = false): Promise<void> {
  if (inflight) return inflight
  if (!force && (state.value === 'ready' || state.value === 'signed-out')) return
  state.value = 'loading'
  inflight = (async () => {
    const signedIn = (() => { try { return !!useAuthStore().isAuthenticated } catch { return false } })()
    const [s, m] = await Promise.allSettled([
      membershipApi.stats(),
      signedIn ? membershipApi.me() : Promise.resolve(null),
    ])
    stats.value = s.status === 'fulfilled' ? s.value : null
    if (!signedIn) {
      me.value = null
      state.value = 'signed-out'
    } else if (m.status === 'fulfilled' && m.value) {
      me.value = m.value
      state.value = 'ready'
    } else {
      me.value = null
      state.value = 'failed'
    }
  })().finally(() => { inflight = null })
  return inflight
}

export function useMembership() {
  return { me, stats, state, load, reload: () => load(true) }
}

/** Test hook: forget the cached picture. */
export function _resetMembership() {
  me.value = null
  stats.value = null
  state.value = 'idle'
  inflight = null
}
