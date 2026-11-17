/**
 * V0662 (OurChat lane): reactions to a message, the console's pure rules (the registry's: services/chat_reactions.py,
 * PUT/DELETE /chat/conversations/{id}/messages/{mid}/reactions/{word}).
 *
 * A reaction is one WORD of a closed list, drawn as a small chip with its count; the chips you put are marked. No emoji,
 * no icon: the words read the same on every device and translate. The registry's page carries each message's
 * `reactions: [{key, count, mine}]`; the socket's `chat.message_reaction` carries the counts after one change and who made it.
 */
export const REACTION_WORDS = ['ack', 'agree', 'thanks', 'done', 'question', 'look'] as const
export type ReactionWord = typeof REACTION_WORDS[number]

export interface ReactionChip { key: string; count: number; mine: boolean }

/** The words in the registry's order, only the ones the registry names (a word this console does not know is dropped). */
export function cleanReactions(list: any): ReactionChip[] {
  const have = new Map<string, ReactionChip>()
  for (const r of Array.isArray(list) ? list : []) {
    if (r && (REACTION_WORDS as readonly string[]).includes(r.key) && Number(r.count) > 0) {
      have.set(r.key, { key: r.key, count: Number(r.count), mine: !!r.mine })
    }
  }
  return REACTION_WORDS.filter((w) => have.has(w)).map((w) => have.get(w)!)
}

/** Whether pressing a word puts it on or takes it off: it is yours already, or it is not. */
export function nextAction(chips: ReactionChip[] | undefined, word: string): 'add' | 'remove' {
  return (chips || []).some((c) => c.key === word && c.mine) ? 'remove' : 'add'
}

/**
 * Fold the socket's counts after one change into the thread's messages. The counts replace the message's words; `mine`
 * is kept from what the message held, except the changed word when the change was the reader's own (it is theirs when the
 * count rose, not theirs when it fell). A message the thread does not hold is none of its business.
 */
export function applyReactionEvent<T extends { id?: string; reactions?: any }>(
  have: T[], ev: { id?: string; word?: string; reactions?: any } | null | undefined, byMe: boolean,
): { messages: T[]; changed: boolean } {
  if (!ev || !ev.id) return { messages: have, changed: false }
  const i = have.findIndex((m) => m.id === ev.id)
  if (i < 0) return { messages: have, changed: false }
  const before = cleanReactions(have[i].reactions)
  const prevMine = new Map(before.map((c) => [c.key, c.mine]))
  const prevCount = new Map(before.map((c) => [c.key, c.count]))
  const after = cleanReactions(ev.reactions).map((c) => {
    let mine = prevMine.get(c.key) ?? false
    if (byMe && c.key === ev.word) mine = c.count > (prevCount.get(c.key) ?? 0)
    return { ...c, mine }
  })
  // a word the change emptied has no chip: if it was the reader's own change it is no longer theirs (nothing to keep)
  if (JSON.stringify(after) === JSON.stringify(before)) return { messages: have, changed: false }
  const messages = have.slice()
  messages[i] = { ...have[i], reactions: after }
  return { messages, changed: true }
}
