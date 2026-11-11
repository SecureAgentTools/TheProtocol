// V0658 (d), polish 15 of the disputes discovery: an owner adds evidence for either of their agents from the dispute.
//
// Two ways in. Acting as one of the parties, the agent files as itself (POST /disputes/{id}/evidence, its token).
// Otherwise the owner of a party files AS that party with their own sign-in (POST /disputes/{id}/evidence/as-owner),
// naming the party when they own both. The server decides who may; this only decides what the console offers.

export interface DisputeParties {
  status: string
  claimant_did: string
  respondent_did: string
}

export interface Viewer {
  /** the agent the console acts as, '' when none */
  actingDid: string
  /** the viewer's own agents the console has loaded (a capped list: it may miss one) */
  ownedDids: string[]
  isAdmin: boolean
}

export type EvidenceRoute =
  | { route: 'agent'; asDid: string }
  /** `parties`: the owned parties to file as; empty when the loaded list holds none, and the server picks the one */
  | { route: 'owner'; parties: string[] }

export function evidenceRoute(d: DisputeParties, v: Viewer): EvidenceRoute | null {
  if (d.status === 'resolved' || d.status === 'dismissed') return null
  const parties = [d.claimant_did, d.respondent_did].filter(Boolean)
  if (v.actingDid && parties.includes(v.actingDid)) return { route: 'agent', asDid: v.actingDid }
  const owned = parties.filter((p) => v.ownedDids.includes(p))
  if (owned.length) return { route: 'owner', parties: owned }
  // A member reads only disputes one of their agents is a party to, so an open one in their list is theirs even when
  // the loaded agent list (capped) misses the agent; an administrator reads every dispute and owns none of most.
  return v.isAdmin ? null : { route: 'owner', parties: [] }
}
