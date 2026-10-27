// PHONE FABRIC — admin oversight API (2026-07-07). Read + control (kill / global-halt).
// Capability ISSUANCE stays agent-context (SDK), so the console is oversight + control only.
import { apiClient } from './client'

export interface PhoneSession {
  id: string
  agent_did: string
  backend: string
  status: string
  actions_used: number
  budget_spent: number | string
  budget_currency?: string | null
  current_app?: string | null
  current_screen?: string | null
  started_at?: string
  ended_at?: string | null
  end_reason?: string | null
}

export interface PhonePoolInstance {
  id: number
  backend: string
  handle: string
  status: string
  leased_by?: string | null
}

export interface PhoneAction {
  seq: number
  action_type: string
  target?: string | null
  cost: number | string
  outcome: string
  detail?: string | null
  created_at: string
}

export const phoneFabricApi = {
  async sessions(): Promise<{ sessions: PhoneSession[]; total: number; enabled: boolean; backend: string; mode: string }> {
    const { data } = await apiClient.get('/admin/phone/sessions')
    return data
  },
  /** §POCKETBRIDGE #PK4 (D8 ratified) — the OWNER rails. `/phone/sessions/mine`
   *  and `/{sid}/end` are agent-JWT (routers/phone_fabric.py:291,312), scoped to
   *  the acting agent BY CONSTRUCTION. They existed unused while the FE read
   *  only the admin list — a non-admin owner silently never saw their agents'
   *  phone sessions (F5). The client interceptor carve-out sends the agent token. */
  async mySessions(): Promise<{ sessions: PhoneSession[]; total: number }> {
    const { data } = await apiClient.get('/phone/sessions/mine')
    return data
  },
  async endMine(sid: string): Promise<{ ok?: boolean; status?: string }> {
    const { data } = await apiClient.post(`/phone/sessions/${encodeURIComponent(sid)}/end`)
    return data
  },
  async pool(): Promise<{ instances: PhonePoolInstance[]; active_sessions: number; max_concurrent: number }> {
    const { data } = await apiClient.get('/admin/phone/pool')
    return data
  },
  async actions(sid: string): Promise<{ session: PhoneSession & Record<string, any>; actions: PhoneAction[]; total: number }> {
    const { data } = await apiClient.get(`/admin/phone/sessions/${encodeURIComponent(sid)}/actions`)
    return data
  },
  async kill(sid: string): Promise<{ ok: boolean; status: string }> {
    const { data } = await apiClient.post(`/admin/phone/sessions/${encodeURIComponent(sid)}/kill`)
    return data
  },
  async globalHalt(): Promise<{ ok: boolean; halted: number }> {
    const { data } = await apiClient.post('/admin/phone/global-halt')
    return data
  },
}
