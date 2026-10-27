/**
 * §COCKPITDESK (2026-10-15) — what on the board needs a look, said once above it.
 *
 * Each pane that can tell something is waiting (a webhook failing, a settlement waiting for a decision, a vote closing
 * within a day, a newer release) reports a count and its sentence here after its own read, and takes it back when it
 * leaves the board. The desk shows the line; pressing an entry gives that pane the board. Module-level, like the desk's
 * Refresh: only the panes on screen report, so the line is always about the board in front of the person.
 */
import { computed, reactive } from 'vue'
import type { PaneId } from '@/components/cockpit/paneRegistry'

export type AttentionTone = 'warn' | 'info'
export interface Attention { id: PaneId; n: number; text: string; tone: AttentionTone }

const items = reactive<Record<string, Attention>>({})

/** A count of nothing (or no sentence) takes the entry back: the line never says "0 failing". */
export function reportAttention(id: PaneId, n: number, text: string, tone: AttentionTone = 'warn'): void {
  if (Number.isFinite(n) && n > 0 && text) items[id] = { id, n, text, tone }
  else delete items[id]
}

export function clearAttention(id: PaneId): void { delete items[id] }

/** What waits on someone first, then what is only worth knowing; in the order the panes reported within each. */
export const attentionList = computed<Attention[]>(() => {
  const all = Object.values(items)
  return [...all.filter(a => a.tone === 'warn'), ...all.filter(a => a.tone === 'info')]
})
