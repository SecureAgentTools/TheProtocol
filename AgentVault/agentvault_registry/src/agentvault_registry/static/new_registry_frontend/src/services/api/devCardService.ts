/**
 * DevCard v0.1 developer-facing client (§V0064 Settings → Developer Card tab).
 * Preview = transparency (unsigned, writes NO disclosure row); disclosures =
 * the GDPR purpose-binding audit; consent = the passport opt-out switch
 * (enforced server-side in build_signed_devcard → 403).
 */
import { apiClient } from './client'

export interface DevCardPayload {
  schema: string
  developer_ref: string
  display_name: string
  contact_email: string
  home_registry: string
  standing: string
  agent_did: string
  org_refs: string[]
  attestations: { email_verified: boolean }
  issued_at: string
}

export interface Disclosure {
  agent_did: string
  requested_by: string
  purpose: string
  at: string | null
}

class DevCardService {
  async preview(agentDid: string): Promise<{ payload: DevCardPayload; signed: boolean; note: string; passport_opt_out: boolean }> {
    const { data } = await apiClient.get(`/dev-card/preview/${encodeURIComponent(agentDid)}`)
    return data
  }

  async disclosures(): Promise<{ disclosures: Disclosure[]; count: number }> {
    const { data } = await apiClient.get('/dev-card/disclosures')
    return data
  }

  async getConsent(): Promise<{ passport_opt_out: boolean }> {
    const { data } = await apiClient.get('/dev-card/consent')
    return data
  }

  async setConsent(optOut: boolean): Promise<{ passport_opt_out: boolean }> {
    const { data } = await apiClient.put('/dev-card/consent', { passport_opt_out: optOut })
    return data
  }
}

export const devCardService = new DevCardService()
