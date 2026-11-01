/**
 * V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): a thread's notification level, pure. A mute can last an hour,
 * 8 hours or a day and then ends by itself, or hold until changed (the server's conversation_participants.muted_until
 * and its mute_in_effect rule, the same here).
 */
export type MuteFor = '1h' | '8h' | '1d' | 'forever'

const LENGTH_MS: Record<Exclude<MuteFor, 'forever'>, number> = { '1h': 3600e3, '8h': 8 * 3600e3, '1d': 24 * 3600e3 }

/** When a mute picked now ends (ISO), or null for one that holds until changed. */
export function muteUntil(f: MuteFor, nowMs: number): string | null {
  return f === 'forever' ? null : new Date(nowMs + LENGTH_MS[f]).toISOString()
}

/** Is the mute on now? One set for a while is over once its time has passed. */
export function muteInEffect(muted: boolean | null | undefined, mutedUntil: string | null | undefined, nowMs: number): boolean {
  if (!muted) return false
  if (!mutedUntil) return true
  const end = Date.parse(mutedUntil)
  return Number.isFinite(end) ? end > nowMs : true
}
