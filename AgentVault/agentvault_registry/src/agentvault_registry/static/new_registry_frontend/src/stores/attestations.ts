import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { attestationsApi } from '@/services'
import type {
  AttestationRecord,
  AttestationSchedule,
  AttestationBundle,
  SigningPubkey,
} from '@/services/api/attestations'

/**
 * ZKP attestation store — agent-facing.
 *
 * Owns:
 *   - The current user's attestations (loaded by DID).
 *   - The current user's schedules.
 *   - Cached signing pubkey (for verifying bundles client-side).
 */
export const useAttestationsStore = defineStore('attestations', () => {
  // ── State ─────────────────────────────────────────────────────────
  const myAttestations = ref<AttestationRecord[]>([])
  const mySchedules = ref<AttestationSchedule[]>([])
  const signingPubkey = ref<SigningPubkey | null>(null)
  const loading = ref(false)
  const lastError = ref<string | null>(null)
  // §FESUITE (2026-10-04): a failed read of the list is not "no attestations". This load caught the failure and emptied
  // the list, and the page said "No attestations match the current filters." with its read failed; the page now shows
  // a read-failed notice while this is set.
  const myAttestationsFailed = ref(false)

  // ── Computed ──────────────────────────────────────────────────────
  const verifiedAttestations = computed(() =>
    myAttestations.value.filter(
      (a) => a.verified && !a.revoked_at && !isExpired(a),
    ),
  )

  const expiredAttestations = computed(() =>
    myAttestations.value.filter((a) => isExpired(a) && !a.revoked_at),
  )

  const revokedAttestations = computed(() =>
    myAttestations.value.filter((a) => !!a.revoked_at),
  )

  function isExpired(a: AttestationRecord): boolean {
    if (!a.expires_at) return false
    return new Date(a.expires_at).getTime() < Date.now()
  }

  function statusFor(a: AttestationRecord): 'verified' | 'expired' | 'revoked' | 'failed' {
    if (a.revoked_at) return 'revoked'
    if (isExpired(a)) return 'expired'
    if (a.verified) return 'verified'
    return 'failed'
  }

  // ── Actions ───────────────────────────────────────────────────────
  async function loadMyAttestations(agentDid: string, limit = 100): Promise<void> {
    loading.value = true
    lastError.value = null
    try {
      const resp = await attestationsApi.getAttestationsByDid(agentDid, { limit })
      myAttestations.value = resp.items
      myAttestationsFailed.value = false
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = `Failed to load attestations: ${msg}`
      myAttestations.value = []
      myAttestationsFailed.value = true
    } finally {
      loading.value = false
    }
  }

  async function loadMySchedules(): Promise<void> {
    lastError.value = null
    try {
      const resp = await attestationsApi.listMySchedules()
      mySchedules.value = resp.items
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = `Failed to load schedules: ${msg}`
      mySchedules.value = []
    }
  }

  async function loadSigningPubkey(): Promise<SigningPubkey | null> {
    if (signingPubkey.value) return signingPubkey.value
    try {
      const k = await attestationsApi.getSigningPubkey()
      signingPubkey.value = k
      return k
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = `Failed to load signing pubkey: ${msg}`
      return null
    }
  }

  async function revoke(attestationId: string, reason: string | null = null): Promise<boolean> {
    try {
      await attestationsApi.revokeAttestation(attestationId, reason ?? undefined)
      // Optimistic local update — mark this row revoked_at = now.
      const idx = myAttestations.value.findIndex((a) => a.id === attestationId)
      if (idx >= 0) {
        myAttestations.value[idx] = {
          ...myAttestations.value[idx],
          revoked_at: new Date().toISOString(),
          revoked_reason: reason,
        }
      }
      return true
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = `Revoke failed: ${msg}`
      return false
    }
  }

  async function loadBundle(attestationId: string): Promise<AttestationBundle | null> {
    try {
      return await attestationsApi.getBundle(attestationId)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = `Bundle load failed: ${msg}`
      return null
    }
  }

  async function createSchedule(
    circuit_id: string,
    interval_hours: number,
  ): Promise<AttestationSchedule | null> {
    try {
      const created = await attestationsApi.createSchedule(circuit_id, interval_hours)
      // Replace if exists, else push.
      const idx = mySchedules.value.findIndex((s) => s.id === created.id)
      if (idx >= 0) mySchedules.value[idx] = created
      else mySchedules.value.push(created)
      return created
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = `Create schedule failed: ${msg}`
      return null
    }
  }

  async function disableSchedule(scheduleId: string): Promise<boolean> {
    try {
      await attestationsApi.disableSchedule(scheduleId)
      const idx = mySchedules.value.findIndex((s) => s.id === scheduleId)
      if (idx >= 0) mySchedules.value[idx] = { ...mySchedules.value[idx], enabled: false }
      return true
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      lastError.value = `Disable schedule failed: ${msg}`
      return false
    }
  }

  function reset(): void {
    myAttestations.value = []
    mySchedules.value = []
    signingPubkey.value = null
    loading.value = false
    lastError.value = null
  }

  return {
    // State
    myAttestations,
    mySchedules,
    signingPubkey,
    loading,
    lastError,
    myAttestationsFailed,
    // Computed
    verifiedAttestations,
    expiredAttestations,
    revokedAttestations,
    statusFor,
    isExpired,
    // Actions
    loadMyAttestations,
    loadMySchedules,
    loadSigningPubkey,
    revoke,
    loadBundle,
    createSchedule,
    disableSchedule,
    reset,
  }
})
