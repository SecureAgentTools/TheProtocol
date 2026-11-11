/**
 * V0659 (o) (order gwo_d7ce94c88a55f629c17b4ff7), the maintainer in the sessions' room (seq 1833): "if any of my agents
 * use any card, i should also see it ... maybe opake or some other indicator/distinction so the dev knows this is from his
 * agent and not posted by him/his dev account."
 *
 * The one rule the thread asks of a line: did one of the viewer's own agents write it itself? The registry answers it
 * (`sender_is_my_agent` on the thread read, the sync feed and his live copy: the sending agent's creator is the reader),
 * because only the registry knows whose agent a DID is; the agents this browser can act as are not that list. A line he
 * typed as his agent through his own session (`sent_by_owner`) is his own. A live line that came without the field (a
 * delivery path that does not name the agent's owner) takes what the registry said about the same agent earlier in the
 * thread; with nothing said, it is not marked. Pure.
 */
export interface OwnAgentLine {
  sender_ptype?: string | null
  sender_id?: string | number | null
  sent_by_owner?: boolean | null
  sender_is_my_agent?: boolean | null
}

/** The agents the registry marked as the viewer's own in these lines, as lower-cased DIDs. */
export function markedOwnAgents(lines: readonly OwnAgentLine[] | null | undefined): Set<string> {
  const out = new Set<string>()
  for (const m of lines || []) {
    if (m?.sender_ptype === 'agent' && m.sender_is_my_agent === true && m.sender_id != null) {
      out.add(String(m.sender_id).toLowerCase())
    }
  }
  return out
}

/** A line one of the viewer's own agents wrote itself (never one he typed as it). `known`: markedOwnAgents' answer. */
export function fromOwnAgent(m: OwnAgentLine | null | undefined, known: ReadonlySet<string> = new Set()): boolean {
  if (!m || m.sender_ptype !== 'agent' || m.sent_by_owner) return false
  if (m.sender_is_my_agent === true) return true
  if (m.sender_is_my_agent === false) return false
  return m.sender_id != null && known.has(String(m.sender_id).toLowerCase())
}
