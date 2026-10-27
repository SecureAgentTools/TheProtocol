/**
 * composables/useThisDeviceApproval.ts — §MEMBERSHIP (2026-10-02): on the phone, a member's vote can be confirmed
 * right where it was cast. The same consent as Pocket Approvals (views/PocketApprovals.vue::pocketSign): find THIS
 * device's enrolled credential, sign the server's hash of the shown facts (the OS raises the biometric prompt), and
 * approve the challenge. A device with no enrolled credential simply cannot sign here; the dialog then offers the
 * Approvals screen or a code instead.
 */
import { ref } from 'vue'
import { useDeviceSigner } from '@/composables/useDeviceSigner'
import { pocketCredentialId } from '@/composables/usePocketLock'
import { devicePushApi } from '@/services/api/devicePush'
import { liabilityApi } from '@/services/api/liability'
import type { StepUpChallenge } from '@/services/membership/membership'

export function useThisDeviceApproval() {
  const signer = useDeviceSigner()
  const canSign = ref(false)
  let device: { id: number; credentialId: string } | null = null

  async function check(): Promise<boolean> {
    device = null
    canSign.value = false
    const local = pocketCredentialId()
    if (!local || !signer.supported) return false
    const devs = await devicePushApi.listMine().catch(() => ({ devices: [] as any[] }))
    const d = (devs.devices || []).find((x: any) => x?.webauthn_credential_id === local && x?.webauthn_enrolled)
    if (d) device = { id: d.id, credentialId: d.webauthn_credential_id }
    canSign.value = !!device
    return canSign.value
  }

  /** Sign and approve; throws when this device cannot, or when the person cancels the prompt. */
  async function approve(ch: StepUpChallenge): Promise<void> {
    if (!device) throw new Error('This device cannot confirm here. Use Pocket, Approvals, or a code.')
    const assertion = await signer.sign(ch.challengeHash, device.credentialId)
    await liabilityApi.approveChallenge(ch.challengeId, { device_id: device.id, ...assertion })
  }

  return { canSign, check, approve }
}
