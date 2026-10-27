// The safety catalogue — eighteen named refusals (strategy §7).
// Every blueprint cites rails by id; the Safety Index renders the matrix.
// Statuses live on each blueprint's primitives rows, not here: a rail is a
// mechanism, and the same mechanism can be LIVE on one surface and SHADOW on
// another. One line per rail, refusal phrased as what does NOT happen.

import type { Rail } from './types'

export const RAILS: Rail[] = [
  { id: 'S01', name: 'Supply invariant', refusal: 'Value cannot be conjured. An independent auditor verifies conservation continuously, and a broken invariant is a P1 incident with a response clock under fifteen minutes.' },
  { id: 'S02', name: 'Deny-by-default authority', refusal: 'An agent with no grants holds two permissions and can do nothing economic.' },
  { id: 'S03', name: 'Capability attenuation', refusal: 'A capability permit conveys its caveats intersected with the issuer’s current authority, nothing more.' },
  { id: 'S04', name: 'Issuer clamp', refusal: 'Reducing an issuer’s authority instantly empties every permit it ever issued.' },
  { id: 'S05', name: 'Re-derived mandates', refusal: 'Effective authority is recomputed on every request and never snapshotted.' },
  { id: 'S06', name: 'Presence proof', refusal: 'The verified-user bit is set by the authenticator and covered by the signature. Possession is not presence.' },
  { id: 'S07', name: 'Identity revocation', refusal: 'A revoked agent’s mTLS identity dies in under 500ms over the event stream.' },
  { id: 'S08', name: 'Coordinated suspension', refusal: 'One action revokes mTLS, suspends the account, and blocklists cross-frame receipt.' },
  { id: 'S09', name: 'Break-glass freeze', refusal: 'An env-only write freeze a compromised admin token cannot flip off.' },
  { id: 'S10', name: 'Jurisdiction profile', refusal: 'A public, signed declaration of what this deployment will not do.' },
  { id: 'S11', name: 'Economic quarantine', refusal: 'Licence revocation ends participation without destroying anyone’s records.' },
  { id: 'S12', name: 'One settlement authority', refusal: 'Only the frame holding the escrow can release it. Replicas carry no path to money.' },
  { id: 'S13', name: 'Courier, never principal', refusal: 'mTLS proves the channel. The principal must be party to the contract.' },
  { id: 'S14', name: 'Immutable ledger', refusal: 'Append-only, replayable, forensically searchable. History cannot be edited.' },
  { id: 'S15', name: 'Exactly-once money', refusal: 'Money moves once across retries, crashes and duplicate submits.' },
  { id: 'S16', name: 'Pre-escrow deny', refusal: 'Gates sit in front of value, so a refusal needs no unwind.' },
  { id: 'S17', name: 'Two-man rule', refusal: 'Enforcement queues for a second approver, and the approval is the execution.' },
  { id: 'S18', name: 'Canary transactions', refusal: 'Synthetic transactions on live paths prove the rails instead of asserting them.' },
  { id: 'S19', name: 'Prove without showing', refusal: 'An agent proves a policy held without revealing the underlying data. The registry verifies the proof, never the secrets. Live on the network’s frames for the published circuits.' },
]

export const RAIL_BY_ID: Record<string, Rail> = Object.fromEntries(
  RAILS.map((r) => [r.id, r]),
)
