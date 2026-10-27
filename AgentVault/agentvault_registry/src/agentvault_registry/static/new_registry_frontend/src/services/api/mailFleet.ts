/**
 * services/api/mailFleet.ts — §FRAMEMAIL-5 fleet mail console.
 *
 * Backend: routers/admin_mail_fleet.py, mounted at /api/v1/admin/mail.
 * The router 404s on any node that holds no mail credentials, so the view treats
 * 404 as "not this registry's job" rather than as an error.
 *
 * Auth: admin_platform flag.
 */
import { apiClient } from './client'

export type Verdict = 'OK' | 'LOCKOUT' | 'UNGATED' | 'UNREACHABLE' | 'UNKNOWN'
export type SendPath = 'direct' | 'relay' | 'none' | 'unknown'

export interface NodeMailStatus {
  name: string
  kind: 'self' | 'frame' | 'operator'
  public_url: string | null
  reachable: boolean
  verification_required: boolean | null
  invite_required: boolean | null
  send_path: SendPath
  verdict: Verdict
  detail: string | null
  peer_status: string | null
}

export interface FleetSummary {
  total: number
  ok: number
  lockout: number
  ungated: number
  unreachable: number
  inactive: number
  unknown: number
  healthy: boolean
}

export interface FleetResponse {
  summary: FleetSummary
  nodes: NodeMailStatus[]
}

export interface SenderInfo {
  from_address: string | null
  from_name: string | null
  server: string | null
  port: number | null
  credential_present: boolean
  relay_enabled: boolean
  relay_callers: Array<{ key: string; base_url: string | null; label: string }>
  max_per_hour: number | null
  max_recipients_per_day: number | null
}

export interface RelayEvent {
  at: string | null
  caller: string | null
  template: string | null
  outcome: string | null
  reason: string | null
  recipient_hash: string | null
}

export interface RelayLicense {
  operator_did: string
  operator_name: string
  status: string
  issued_at: string | null
  last_seen_at: string | null
  base_url: string | null
  label: string
}

class MailFleetService {
  private base = '/admin/mail'

  async fleet(): Promise<FleetResponse> {
    // a 404 means this registry holds no mail credentials: the page says so (§FESUITE: it was toasted as an error)
    const r = await apiClient.get(`${this.base}/fleet`, { expectedStatuses: [404] })
    return r.data
  }

  async sender(): Promise<SenderInfo> {
    const r = await apiClient.get(`${this.base}/sender`, { expectedStatuses: [404] })
    return r.data
  }

  async relayActivity(limit = 50): Promise<{ events: RelayEvent[]; last_24h: any[] }> {
    const r = await apiClient.get(`${this.base}/relay-activity`, { params: { limit } })
    return r.data
  }

  async relayLicenses(): Promise<{ licenses: RelayLicense[] }> {
    const r = await apiClient.get(`${this.base}/relay-licenses`)
    return r.data
  }

  /** Opens a real SMTP session and authenticates. Sends nothing. */
  async verifyCredential(): Promise<{ ok: boolean; server?: string; username?: string; error?: string }> {
    const r = await apiClient.post(`${this.base}/verify-credential`)
    return r.data
  }

  /** A real delivery, not a render. */
  async testSend(recipient: string, note?: string): Promise<{ ok: boolean; recipient: string }> {
    const r = await apiClient.post(`${this.base}/test-send`, { recipient, note: note || undefined })
    return r.data
  }

  async revokeRelay(operatorDid: string) {
    const r = await apiClient.post(`${this.base}/relay-callers/${encodeURIComponent(operatorDid)}/revoke`)
    return r.data
  }

  async reinstateRelay(operatorDid: string) {
    const r = await apiClient.post(`${this.base}/relay-callers/${encodeURIComponent(operatorDid)}/reinstate`)
    return r.data
  }
}

export const mailFleetService = new MailFleetService()
