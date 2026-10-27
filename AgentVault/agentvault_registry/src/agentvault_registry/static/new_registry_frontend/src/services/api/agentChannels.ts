/**
 * §COCKPITA R4 — the read/write rails for the desk<->agent channels.
 *
 * TWO channels, opposite directions and opposite risk, kept apart here for the same reason
 * the router keeps them apart: one observes, one acts.
 */
import apiClient from './client'

export interface ProgressNote {
  did: string
  /** §COCKPITPOLISH P4 — resolved server-side from the same query that scopes by owner.
   *  ABSENT (not the DID) when the agent has no card name: the client decides how to
   *  render that, and a server substituting silently takes the choice away. */
  agent_name?: string
  phase: string
  note: string
  ref: string | null
  pct: number | null
  at: string
}

/** §COCKPITPOLISH P7.1 — one instruct attempt as the audit rail recorded it.
 *  ⚠ `text_retained` on the response is false and always will be: the audit row keeps the
 *  instruction's LENGTH, never its content, so this history can say that you instructed
 *  an agent and whether it landed, but never what you said. */
export interface InstructionRecord {
  at: string | null
  agent_did: string
  agent_name: string | null
  outcome: 'success' | 'failure' | string
  delivery: string | null
  elapsed_ms: number | null
  transport: string | null
  ref: string | null
  text_len: number | null
  detail: string | null
}

export interface InstructionHistory {
  instructions: InstructionRecord[]
  count: number
  text_retained: boolean
}

export interface ProgressResponse {
  notes: ProgressNote[]
  agents: number
  /** 🔴 TRUE means the buffer could not be read. "No notes" and "we could not look" are
   *  different facts and the pane must never render them the same way. */
  degraded: boolean
  reason?: string
}

export interface ChannelCapability {
  did: string
  can_instruct: boolean
  transport: string | null
  /** Present exactly when `can_instruct` is false: what is missing, so the owner can fix it. */
  reason: string | null
}

export const agentChannelsApi = {
  progress: (limit = 60) =>
    apiClient.get<ProgressResponse>('/agents/progress', { params: { limit } }).then(r => r.data),

  capability: (did: string) =>
    apiClient.get<ChannelCapability>(`/agents/${encodeURIComponent(did)}/channel`).then(r => r.data),

  instruct: (did: string, text: string, ref?: string) =>
    apiClient.post(`/agents/${encodeURIComponent(did)}/instruct`, { text, ref }).then(r => r.data),

  /** Scoped to the caller by the endpoint's WHERE clause — there is no actor parameter. */
  instructions: (limit = 40) =>
    apiClient.get<InstructionHistory>('/agents/instructions', { params: { limit } }).then(r => r.data),
}
