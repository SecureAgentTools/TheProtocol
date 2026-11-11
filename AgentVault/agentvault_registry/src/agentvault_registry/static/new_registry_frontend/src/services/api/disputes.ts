// Dispute Management API Service — OWL-17 rewrite
// Ground truth verified 2026-03-10 against live backend (dispute #41 lifecycle)
import { apiClient } from './client'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('disputesApi')

export interface CompensationResult {
  applied: boolean
  amount: number
  amount_requested: number
  from_did: string | null
  to_did: string | null
  reason: string | null
  event_emitted: boolean
  transaction_id?: string
  partial: boolean
  deferred_amount: number
  defendant_balance_warning?: string
  cross_registry?: boolean
}

export interface Dispute {
  id: string
  // X1 (2026-05-06): backend now exposes contract_id at top level (nullable
  // int) when the dispute was filed via /contracts/{id}/malpractice. Migration
  // 0030_disputes_chain_polish added the column. contract_name is not yet
  // populated by backend — left optional for forward compat.
  contract_id?: number | string
  contract_name?: string
  claimant_did: string
  claimant_name?: string
  respondent_did: string
  respondent_name?: string
  // 'reason' is synthesised client-side from evidence_data.description or category
  reason: string
  description: string
  status: 'open' | 'resolved' | 'dismissed'   // the server's OPEN, and CLOSED read by its ruling (V0658 (f))
  evidence: Evidence[]
  ruling?: string
  resolution_date?: string
  compensation?: CompensationResult
  reputation_changes?: {
    complainant: { initial: number | null; final: number | null; change: number | null }
    defendant: { initial: number | null; final: number | null; change: number | null }
  }
  created_at: string
  updated_at: string
  // V0657 (a), disputes v2: what the record knows since V0657 (all optional: an older registry sends none of them)
  contract_ref?: string | null
  guild_order_id?: string | null
  /** why it opened, in the record's words (deadline_missed, rejected_by_poster, poster_silent, stuck_payout,
   *  filed_by_party) and as a sentence */
  reason_code?: string | null
  reason_text?: string | null
  filed_by?: 'party' | 'system' | null
  amount_claimed?: string | null
  ruled_by?: number | null
  ruled_at?: string | null
  ruling_note?: string | null
  outcome?: DisputeOutcome | null
  parties?: { complainant: DisputeParty; defendant: DisputeParty } | null
  guild_order?: DisputeGuildOrder | null
  corrections?: DisputeCorrection[] | null
}

export type RulingValue = 'IN_FAVOR_OF_COMPLAINANT' | 'IN_FAVOR_OF_DEFENDANT' | 'DISMISSED'

export interface DisputeParty { did: string; name?: string | null; owner?: string | null; home?: string | null }

export interface DisputeOutcome {
  reputation?: { did: string; change: number; why?: string; before?: number | null; after?: number | null }[] | null
  enforcement?: { action?: string | null; status?: string | null; escalation_level?: number | null; amount?: string | null } | null
  money?: Record<string, any> | null
  corrected?: { from: string; to: string; note: string; by?: number | null; at?: string } | null
}

export interface DisputeGuildOrder {
  id: string
  title?: string | null
  spec?: string | null
  status?: string | null
  bounty?: string | null
  currency?: string | null
  escrow_held?: string | null
  poster_did?: string | null
  worker_did?: string | null
  deadline?: string | null
  awarded_at?: string | null
  submitted_at?: string | null
  settled_at?: string | null
  handed_in?: boolean
  deliverable?: Record<string, any> | null
  awarded_bid?: { bidder_did?: string; price?: string; eta_seconds?: number | null; pitch?: string | null } | null
  announce_conversation_id?: string | null
  events?: { seq: number; event_type: string; actor_did?: string | null; payload?: any; created_at?: string | null }[]
}

export interface DisputeCorrection {
  id?: number
  from_ruling: string
  to_ruling: string
  note: string
  corrected_by?: number | null
  corrected_at?: string | null
  /** 'applying' from its claim until every step is done (a failure midway leaves it so: finish it), then 'applied' */
  status?: 'applying' | 'applied' | string | null
  finished_at?: string | null
}

/** GET /admin/disputes/{id}/preview: what a ruling would do, before it is made */
export interface RulingPreview {
  dispute_id: number
  ruling: RulingValue
  ruling_words: string
  money: Record<string, any>
  reputation: { did: string; name?: string | null; change: number; why: string }[]
  enforcement: Record<string, any> | null
}

/** GET /admin/disputes/{id}/correction-preview */
export interface CorrectionPreview {
  from_ruling: string
  to_ruling: string
  from_words: string
  to_words: string
  reverse_reputation: { did: string; change: number; why?: string; source?: string }[]
  reverse_enforcement: { action_id: string; agent_did: string; action: string; not_returned?: string; suspension_stays?: string }[]
  apply_reputation: { did: string; change: number; why: string }[]
  money: string
}

export interface QueueItem {
  kind: 'dispute' | 'guild' | 'contract'
  id: string | number
  dispute_id: number | null
  title?: string | null
  reason?: string | null
  reason_text?: string | null
  filed_by?: string | null
  complainant_did?: string | null
  complainant_name?: string | null
  defendant_did?: string | null
  defendant_name?: string | null
  guild_order_id?: string | null
  contract_ref?: string | null
  at_stake?: { amount: string; currency?: string; what: string } | null
  opened_at?: string | null
}

export interface Evidence {
  id: string
  submitted_by: string
  submitted_by_name?: string
  type: 'text' | 'image' | 'document' | 'link'
  content: string
  description?: string
  submitted_at: string
}

// OWL-17 FIX-D01: correct schema matching backend POST /api/v1/disputes/
export interface CreateDisputeData {
  defendant_did: string          // target agent DID (complainant_did is injected from activeAgent)
  category: string               // contract_breach | service_failure | payment_dispute | other
  description: string            // human-readable summary
  amount_disputed?: number       // optional — feeds compensation engine via first evidence submission
}

// OWL-17 FIX-D02: evidence_data wrapper required by backend
export interface SubmitEvidenceData {
  type: 'text' | 'image' | 'document' | 'link'
  content: string
  description?: string
  amount_disputed?: number
}

export interface DisputeStats {
  total_disputes: number
  open_disputes: number
  /** ruled in the claimant's favour (status `resolved`) */
  resolved_disputes: number
  /** §COCKPITDESK (2026-10-15): every dispute with a ruling, upheld (`resolved`) or `dismissed`. Absent from older answers. */
  decided_disputes?: number
  dismissed_disputes?: number
  /** decided / total, in percent; null when there is no dispute (a rate of nothing is not 0%) */
  resolution_rate: number | null
  /** hours from filing to ruling over the decided disputes that carry a date; null when none does (not 0 h) */
  average_resolution_time: number | null
  /** §COCKPITDESK (2026-10-15): the counts stopped at COUNT_PAGES pages of COUNT_PAGE; the tiles show the total with a +.
   *  (They had counted the list's first page of 100 as the whole: "TOTAL 100" beside dispute #205.) */
  capped?: boolean
}

/** The counting walk: pages of the list's own size, at most ten (1,000 disputes), each dispute once by its id. */
export const COUNT_PAGE = 100
export const COUNT_PAGES = 10

class DisputesAPI {
  // ── Helpers ────────────────────────────────────────────────────────────────

  private extractDisputesArray(data: any): any[] {
    if (Array.isArray(data)) return data
    if (data?.disputes && Array.isArray(data.disputes)) return data.disputes
    if (data?.items && Array.isArray(data.items)) return data.items
    if (data?.results && Array.isArray(data.results)) return data.results
    if (data?.data && Array.isArray(data.data)) return data.data
    return []
  }

  // ── CRUD ───────────────────────────────────────────────────────────────────

  // OWL-17 FIX-D01: send { complainant_did, defendant_did, category, description }
  // complainant_did is pulled from authStore.activeAgent inside the store action.
  // We accept it here as a required parameter so the store controls the DID.
  async createDispute(data: CreateDisputeData & { complainant_did: string }): Promise<Dispute> {
    // V0657 (a), item 2: the amount claimed is the filing's own field; a ruling never reads it from evidence
    const response = await apiClient.post('/disputes/', {
      complainant_did: data.complainant_did,
      defendant_did: data.defendant_did,
      category: data.category,
      description: data.description,
      ...(data.amount_disputed && data.amount_disputed > 0 ? { amount_claimed: data.amount_disputed } : {})
    })
    const dispute = this.transformDispute(response.data)

    // Auto-submit the description as the first evidence
    if (data.description) {
      try {
        const ev = await this.submitEvidence(dispute.id, {
          type: 'text',
          content: data.description,
          description: data.category || 'Initial evidence'
        }, data.complainant_did)
        dispute.evidence.push(ev)
      } catch (e) {
        log.warn('Auto-evidence submission failed (non-fatal):', e)
      }
    }

    return dispute
  }

  // GET /api/v1/disputes/ — returns all disputes (admin view)
  // §FESUITE (the failing-reads census, 2026-10-04): a failed read is not "none". This returned [] for every failure, so
  // the store could not tell a failed read from an empty list and the page said "No disputes filed yet" with every read
  // failed. A 404 is the server's own "none"; any other failure is the caller's to report.
  async getDisputes(): Promise<Dispute[]> {
    try {
      const response = await apiClient.get('/disputes/')
      const raw = this.extractDisputesArray(response.data)
      return raw.map((d: any) => this.transformDispute(d))
    } catch (error: any) {
      if (error?.response?.status === 404) return []
      console.error('GET /disputes/ failed:', error?.response?.status)
      throw error
    }
  }

  // GET /api/v1/disputes/agent/{did} — agent-scoped disputes
  async getAgentDisputes(agentDid: string): Promise<Dispute[]> {
    try {
      const response = await apiClient.get(`/disputes/agent/${agentDid}`)
      const raw = this.extractDisputesArray(response.data)
      return raw.map((d: any) => this.transformDispute(d))
    } catch (error: any) {
      if (error.response?.status === 404) return []
      throw error
    }
  }

  // GET /api/v1/disputes/{id}
  async getDispute(disputeId: string): Promise<Dispute> {
    const response = await apiClient.get(`/disputes/${disputeId}`)
    return this.transformDispute(response.data)
  }

  // OWL-17 FIX-D02: backend requires { submitter_did, evidence_data: { ... } }
  async submitEvidence(
    disputeId: string,
    data: SubmitEvidenceData,
    submitterDid?: string
  ): Promise<Evidence> {
    // Resolve submitter DID: passed explicitly OR pull from authStore
    let did = submitterDid
    if (!did) {
      const { useAuthStore } = await import('@/stores/auth')
      const authStore = useAuthStore()
      did = authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
    }

    const response = await apiClient.post(`/disputes/${disputeId}/evidence`, {
      submitter_did: did,
      evidence_data: this.evidenceData(data)
    })
    return this.transformEvidence(response.data)
  }

  /** POST /api/v1/disputes/{id}/evidence/as-owner (V0658 (d), polish 15): the owner of a party files evidence AS that
   *  party with their own sign-in. `agentDid` names the party when the owner owns both; left out, the server takes the
   *  one party the caller owns. */
  async submitEvidenceAsOwner(disputeId: string, data: SubmitEvidenceData, agentDid?: string): Promise<Evidence> {
    const response = await apiClient.post(`/disputes/${disputeId}/evidence/as-owner`, {
      evidence_data: this.evidenceData(data),
      ...(agentDid ? { agent_did: agentDid } : {})
    })
    return this.transformEvidence(response.data)
  }

  private evidenceData(data: SubmitEvidenceData): Record<string, any> {
    return {
      type: data.type,
      content: data.content,
      ...(data.description ? { description: data.description } : {}),
      ...(data.amount_disputed !== undefined ? { amount_disputed: data.amount_disputed } : {})
    }
  }

  /** PUT /api/v1/admin/disputes/{id}/ruling — V0657 (a): the ruling, the ruler's reason (kept on the record and told to
   *  both parties; it was asked for and never sent) and, for a dispute about a Guild order, the worker's share of its
   *  escrow. The ruling also travels as the query parameter, which an older registry reads. */
  async updateRuling(
    disputeId: string,
    ruling: RulingValue,
    note: string,
    workerShare?: number | null
  ): Promise<{ dispute: Dispute; compensation: CompensationResult | null; reputation_changes: any; outcome: DisputeOutcome | null }> {
    const body: Record<string, any> = { ruling, note }
    if (workerShare !== undefined && workerShare !== null) body.worker_share = workerShare
    const response = await apiClient.put(`/admin/disputes/${disputeId}/ruling`, body, { params: { ruling } })

    const data = response.data
    const dispute = this.transformDispute(data)
    return {
      dispute,
      compensation: data.compensation || null,
      reputation_changes: data.reputation_changes || null,
      outcome: data.outcome || null
    }
  }

  /** GET /admin/disputes/{id}/preview — what a ruling would do (who gets what, each reputation change, the enforcement
   *  step), read only, from the rules the ruling applies */
  async previewRuling(disputeId: string, ruling: RulingValue, workerShare?: number | null): Promise<RulingPreview> {
    const params: Record<string, any> = { ruling }
    if (workerShare !== undefined && workerShare !== null) params.worker_share = workerShare
    const response = await apiClient.get(`/admin/disputes/${disputeId}/preview`, { params })
    return response.data
  }

  /** GET /admin/disputes/{id}/correction-preview — what correcting a ruling would undo and apply */
  async previewCorrection(disputeId: string, ruling: RulingValue): Promise<CorrectionPreview> {
    const response = await apiClient.get(`/admin/disputes/${disputeId}/correction-preview`, { params: { ruling } })
    return response.data
  }

  /** POST /admin/disputes/{id}/correct — the correction rail (why is required; no money moves) */
  async correctRuling(disputeId: string, ruling: RulingValue, note: string): Promise<any> {
    const response = await apiClient.post(`/admin/disputes/${disputeId}/correct`, { ruling, note })
    return response.data
  }

  /** POST /admin/disputes/{id}/corrections/{cid}/finish — finish a correction a failure left 'applying' (its recorded
   *  steps are kept, the rest done once) */
  async finishCorrection(disputeId: string, correctionId: number | string): Promise<any> {
    const response = await apiClient.post(`/admin/disputes/${disputeId}/corrections/${correctionId}/finish`)
    return response.data
  }

  /** GET /admin/disputes/queue — every open record, and every disputed Guild order and contract without one */
  async rulerQueue(): Promise<{ items: QueueItem[]; counts: Record<string, number>; total: number }> {
    const response = await apiClient.get('/admin/disputes/queue')
    return response.data
  }

  /** POST /admin/disputes/queue/{kind}/{ref}/record — give a disputed order or contract its record */
  async fileQueueRecord(kind: 'guild' | 'contract', ref: string): Promise<{ dispute_id: number }> {
    const response = await apiClient.post(`/admin/disputes/queue/${kind}/${encodeURIComponent(ref)}/record`)
    return response.data
  }

  // Calculate stats from disputes list (no dedicated stats endpoint). A failed read throws (the store keeps its tiles at a
  // dash, statsRead): zeros returned for a failure were drawn as "0 disputes" (§FESUITE, the failing-reads census).
  async getStats(): Promise<DisputeStats> {
    const { rows, capped } = await this.countAllDisputes()
    return { ...this.calculateStats(rows), capped }
  }

  /** §COCKPITDESK (2026-10-15): the list and the tiles from ONE set of reads — every dispute the counter reads (newest
   *  first, up to COUNT_PAGES pages) and the counts over them. The page had read the first 100 for the list and then
   *  every page again for the tiles. A 404 on the first page is "none"; a failed read throws. */
  async readAll(): Promise<{ rows: Dispute[]; stats: DisputeStats }> {
    const { rows, capped } = await this.countAllDisputes()
    return { rows, stats: { ...this.calculateStats(rows), capped } }
  }

  /** Every dispute, page by page (the list answers 100 at a time, newest first, an id breaking a tie since V0617), each
   *  once by its id; stops at a short page or after COUNT_PAGES pages (then `capped`). A failed read throws, as above. */
  async countAllDisputes(): Promise<{ rows: Dispute[]; capped: boolean }> {
    const seen = new Map<string, any>()
    for (let i = 0; i < COUNT_PAGES; i++) {
      let raw: any[]
      try {
        const response = await apiClient.get('/disputes/', { params: { limit: COUNT_PAGE, offset: i * COUNT_PAGE } })
        raw = this.extractDisputesArray(response.data)
      } catch (error: any) {
        if (error?.response?.status === 404 && i === 0) return { rows: [], capped: false }
        throw error
      }
      for (const d of raw) seen.set(String(d?.id ?? `${i}:${seen.size}`), d)
      if (raw.length < COUNT_PAGE) return { rows: [...seen.values()].map((d) => this.transformDispute(d)), capped: false }
    }
    return { rows: [...seen.values()].map((d) => this.transformDispute(d)), capped: true }
  }

  // ── Transformers ───────────────────────────────────────────────────────────

  private transformDispute(data: any): Dispute {
    // Status: backend uses uppercase "OPEN" / "CLOSED"; map to lowercase frontend enum
    const rawStatus = (data.status || 'OPEN').toLowerCase()
    let status: Dispute['status'] = 'open'
    if (rawStatus === 'closed') {
      status = data.ruling === 'DISMISSED' ? 'dismissed' : 'resolved'
    } else if (['open', 'resolved', 'dismissed'].includes(rawStatus)) {
      status = rawStatus as Dispute['status']
    }

    // Why it opened: the record's own words since V0657 (a), item 10; before, synthesised from evidence_data (BUG-D04),
    // and "Contract dispute" labelled every dispute that carried none
    const reason = data.reason_text
      || data.category
      || this.extractFieldFromEvidence(data.evidence, ['description', 'brief_description', 'category', 'type'])
      || 'Dispute'

    const description = data.description
      || this.extractFieldFromEvidence(data.evidence, ['description', 'brief_description', 'content'])
      || reason

    return {
      id: String(data.id || data.dispute_id),
      // BUG-D05 fix: contract_id may not exist — only include if present
      ...(data.contract_id ? { contract_id: data.contract_id } : {}),
      ...(data.contract_name ? { contract_name: data.contract_name } : {}),
      claimant_did: data.claimant_did || data.claimant_agent_did || data.complainant_did || '',
      claimant_name: data.claimant_name || data.claimant_agent_name || data.complainant_name,
      respondent_did: data.respondent_did || data.respondent_agent_did || data.defendant_did || '',
      respondent_name: data.respondent_name || data.respondent_agent_name || data.defendant_name,
      reason,
      description,
      status,
      evidence: Array.isArray(data.evidence) ? data.evidence.map((e: any) => this.transformEvidence(e)) : [],
      ruling: data.ruling,
      resolution_date: data.resolution_date,
      created_at: data.created_at || new Date().toISOString(),
      updated_at: data.updated_at || new Date().toISOString(),
      // V0657 (a): what the record knows
      ...(data.contract_ref ? { contract_ref: data.contract_ref } : {}),
      guild_order_id: data.guild_order_id ?? null,
      reason_code: data.reason ?? null,
      reason_text: data.reason_text ?? null,
      filed_by: data.filed_by ?? null,
      amount_claimed: data.amount_claimed ?? null,
      ruled_by: data.ruled_by ?? null,
      ruled_at: data.ruled_at ?? null,
      ruling_note: data.ruling_note ?? null,
      outcome: data.outcome ?? null,
      parties: data.parties ?? null,
      guild_order: data.guild_order ?? null,
      corrections: data.corrections ?? null
    }
  }

  // OWL-17 FIX-D03: extract readable content from evidence_data object
  private transformEvidence(data: any): Evidence {
    const ed = data.evidence_data || {}

    // Priority: content → description → brief_description → stringify object
    const content: string =
      ed.content
      || ed.description
      || ed.brief_description
      || (typeof ed === 'object' && Object.keys(ed).length
          ? Object.entries(ed)
              .filter(([k]) => !['type', 'source', 'submitted_via', 'additional_evidence'].includes(k))
              .map(([k, v]) => `${k}: ${v}`)
              .join(' | ')
          : data.content || '')

    return {
      id: String(data.id || data.evidence_id),
      submitted_by: data.submitted_by || data.submitter_did || data.agent_did || '',
      submitted_by_name: data.submitted_by_name || data.agent_name,
      type: (ed.type || data.type || 'text') as Evidence['type'],
      content,
      description: ed.description || data.description,
      submitted_at: data.submitted_at || data.created_at || new Date().toISOString()
    }
  }

  private extractFieldFromEvidence(evidence: any[], fields: string[]): string | null {
    if (!Array.isArray(evidence) || evidence.length === 0) return null
    for (const e of evidence) {
      const ed = e.evidence_data || e
      for (const f of fields) {
        if (ed[f] && typeof ed[f] === 'string' && ed[f].trim()) return ed[f]
      }
    }
    return null
  }

  private calculateStats(disputes: Dispute[]): DisputeStats {
    const total = disputes.length
    const open = disputes.filter(d => d.status === 'open').length
    const resolved = disputes.filter(d => d.status === 'resolved').length
    const dismissed = disputes.filter(d => d.status === 'dismissed').length
    // §COCKPITDESK (2026-10-15): the camera read "0 resolved · 0% · 0h" over 22 disputes of which 19 were dismissed. A
    // dismissal is a ruling too: the rate and the time are over every DECIDED dispute, and nothing decided is a dash.
    const decided = resolved + dismissed

    const decidedWithDate = disputes.filter(d => (d.status === 'resolved' || d.status === 'dismissed') && d.resolution_date)
    let avgTime: number | null = null
    if (decidedWithDate.length > 0) {
      const totalMs = decidedWithDate.reduce((sum, d) => {
        return sum + (new Date(d.resolution_date!).getTime() - new Date(d.created_at).getTime())
      }, 0)
      avgTime = Math.round(totalMs / decidedWithDate.length / 3_600_000)
    }

    return {
      total_disputes: total,
      open_disputes: open,
      resolved_disputes: resolved,
      decided_disputes: decided,
      dismissed_disputes: dismissed,
      resolution_rate: total > 0 ? (decided / total) * 100 : null,
      average_resolution_time: avgTime
    }
  }
}

export const disputesApi = new DisputesAPI()
