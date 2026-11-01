/**
 * V0652 (aa) (order gwo_840aa2b590306f7eba147758): cards that live, the console's pure rules.
 *
 * A card is updated in place: the message keeps its id and seq, its card is the latest state, and `card_rev` counts the
 * updates. A thread hears an update three ways (the socket's chat.card_updated, the long-poll's `updates` lane, a
 * catch-up read of the newest page) and applies it by its rev: a newer rev replaces the card, an older or equal one
 * changes nothing, so an update arriving twice or late never moves a card back.
 */
import type { SeqMsg } from './catchUp'

export interface CardUpdate {
  id: string
  card: any
  card_rev: number
  card_updated_at?: string | null
}

/** The thread's messages with one card's update applied (by its rev), and whether anything changed. Pure. */
export function applyCardUpdate(have: SeqMsg[], u: CardUpdate | null | undefined): { messages: SeqMsg[]; changed: boolean } {
  if (!u || !u.id) return { messages: have, changed: false }
  const i = have.findIndex((m) => m.id === u.id)
  if (i < 0) return { messages: have, changed: false }
  const held = have[i]
  if ((Number(u.card_rev) || 0) <= (Number(held.card_rev) || 0)) return { messages: have, changed: false }
  const next = have.slice()
  next[i] = { ...held, card: u.card, card_rev: Number(u.card_rev) || 0, card_updated_at: u.card_updated_at ?? null }
  return { messages: next, changed: true }
}

/** Every update in a list, in order (the long-poll's `updates`). Pure. */
export function applyCardUpdates(have: SeqMsg[], ups: CardUpdate[] | null | undefined): { messages: SeqMsg[]; changed: number } {
  let messages = have
  let changed = 0
  for (const u of ups || []) {
    const r = applyCardUpdate(messages, u)
    if (r.changed) { messages = r.messages; changed++ }
  }
  return { messages, changed }
}

export interface StepTotals { done: number; failed: number; running: number; total: number }
/** How far a progress card's steps are (done counts skipped too: a skipped step is not waiting). Pure. */
export function stepTotals(steps: Array<{ state: string }>): StepTotals {
  const out = { done: 0, failed: 0, running: 0, total: steps.length }
  for (const s of steps) {
    if (s.state === 'done' || s.state === 'skipped') out.done++
    else if (s.state === 'failed') out.failed++
    else if (s.state === 'running') out.running++
  }
  return out
}

/** The lifecycle a Guild order card draws, in order: each stage, whether the order reached it and when. */
export const GUILD_STAGES = ['posted', 'bid', 'awarded', 'submitted', 'settled'] as const
export type GuildStage = typeof GUILD_STAGES[number]
export function guildStages(events: Array<{ type: string; at: string | null }>): Array<{ stage: GuildStage; at: string | null; reached: boolean }> {
  const firstAt: Partial<Record<string, string | null>> = {}
  for (const e of events) if (!(e.type in firstAt)) firstAt[e.type] = e.at
  return GUILD_STAGES.map((stage) => ({ stage, at: firstAt[stage] ?? null, reached: stage in firstAt }))
}
