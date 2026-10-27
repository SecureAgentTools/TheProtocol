import type { AxiosInstance } from 'axios'
import { apiClient } from './client'
import type { MembershipStats, MyMembership } from '@/services/membership/membership'

/**
 * §MEMBERSHIP (2026-10-02) — the two membership routes of plan § 2.3. `stats` is public; `me` reads the signed-in
 * developer (developer token: the route is not on the agent tier). The client is read when a request is made, never
 * captured at module load (§FEFRAME W3.1: a singleton that captured the client at import broke a whole view).
 */
export class MembershipApi {
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  async stats(): Promise<MembershipStats> {
    const { data } = await this.client.get('/membership/stats')
    return data as MembershipStats
  }

  async me(): Promise<MyMembership> {
    const { data } = await this.client.get('/membership/me')
    const d = (data || {}) as Partial<MyMembership>
    const num = (x: unknown, dflt = 0) => (typeof x === 'number' && Number.isFinite(x) ? x : dflt)
    const agents = Array.isArray(d.agents) ? d.agents.map(a => ({ ...a, reasons: Array.isArray(a?.reasons) ? a.reasons : [] })) : []
    return {
      mode: d.mode === 'member' ? 'member' : 'lock',
      is_member: !!d.is_member,
      member_since: d.member_since ?? null,
      weight: num(d.weight),
      points: num(d.points),
      tenure_days: num(d.tenure_days),
      tenure_full_days: num(d.tenure_full_days, 365),
      min_bond_age_days: num(d.min_bond_age_days, 30),
      requires_matured_bond: !!d.requires_matured_bond,
      presence_mode: d.presence_mode === 'conditional' || d.presence_mode === 'required' ? d.presence_mode : 'off',
      agents,
      // an older registry lists every bond and names no counts: the list is then the whole population
      agents_total: num(d.agents_total, agents.length),
      agents_qualifying: num(d.agents_qualifying, agents.filter(a => a.qualifies).length),
      agents_shown: num(d.agents_shown, agents.length),
      missing: Array.isArray(d.missing) ? d.missing : [],
      next_step: (d.next_step || 'post_bond') as MyMembership['next_step'],
      next_step_at: d.next_step_at ?? null,
      next_step_text: typeof d.next_step_text === 'string' && d.next_step_text ? d.next_step_text : null,
    }
  }
}

export const membershipApi = new MembershipApi()
