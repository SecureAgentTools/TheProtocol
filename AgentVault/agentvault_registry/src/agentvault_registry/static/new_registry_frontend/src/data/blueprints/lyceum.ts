import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'A credential is a signed attestation', primitive: 'Issuer-signed, expiry-dated, revocable attestations', railStatus: 'LIVE' as const },
  { step: 'Revocation that actually reaches verifiers', primitive: 'Revocation over the event stream, not a phone call', railStatus: 'LIVE' as const },
  { step: 'Prove the grade, hide the transcript', primitive: 'ZK attestation over a new threshold circuit, not yet written', railStatus: 'DESIGNED' as const },
  { step: 'Tuition and stipends in escrow', primitive: 'Milestone contracts for programmes and scholarships', railStatus: 'LIVE' as const },
  { step: 'Issuers with reputations', primitive: 'Trust scores built on verified outcomes', railStatus: 'LIVE' as const },
  { step: 'Records that outlive the issuer', primitive: 'Append-only ledger; verification needs no live registrar', railStatus: 'LIVE' as const },
]

export const lyceum: Blueprint = {
  id: 'lyceum',
  tier: 2,
  vault: true,
  rank: 19,
  industry: 'Education and Credentialing',
  systemName: 'LYCEUM',
  promise: 'Credentials that verify in seconds, revoke honestly, and can prove a threshold without opening the transcript.',
  cases: [
    { role: 'University registrar', line: 'Degrees as signed, revocable attestations, verified without you.' },
    { role: 'Professional body', line: 'Licences that lapse and revoke where verifiers actually look.' },
    { role: 'Employer screening', line: 'Verify in seconds against the issuer’s signature, not a PDF.' },
    { role: 'Scholarship fund', line: 'Stipends released from escrow on attested progress.' },
  ],
  problem:
    'A degree is verified by emailing a registrar and waiting; a licence is checked against a register that lags reality; a forged certificate costs less than the courier that delivers it. And the honest candidate has only one move: hand over the entire transcript when the question was a single threshold.',
  system: [
    'LYCEUM issues credentials as signed attestations: the engineering faculty signs the degree, the medical board signs the licence, each expiry-dated, each revocable, each verifiable by anyone against the issuer’s published keys in seconds, with no registrar in the loop. When the board revokes a licence on Tuesday, the revocation rides the event stream to every verifier that has ever cached it, and Wednesday’s verification honestly fails.',
    'The quiet superpower is selective proof. A hospital needs to know a candidate passed the boards above the threshold; it does not need the score. The candidate would prove the threshold with a zero-knowledge attestation verified against a published circuit, so the verifier confirms the rule held without ever seeing the number, and the transcript stays where it belongs. That circuit is not yet written: the registry verifies proofs for pricing, usage, fee and moderation policies today, and its one threshold check, proof_of_reputation, only validates its inputs and proves nothing. It is badged DESIGNED. Scholarship stipends run the same rails as everything else here: escrowed at award, released on attested progress, disputed with evidence when it comes to that.',
  ],
  cast: [
    { agent: 'faculty-issuer', role: 'Signs degrees and course credit', ceiling: 'Issue and revoke its own attestations only.' },
    { agent: 'board-issuer', role: 'Signs and revokes licences', ceiling: 'Its own register; revocations broadcast.' },
    { agent: 'verifier-desk', role: 'Checks candidates for employers', ceiling: 'Verify only. Sees proofs, not transcripts.' },
    { agent: 'scholarship-fund', role: 'Escrows stipends', ceiling: 'Fund and release on attested progress.' },
  ],
  loom: {
    nodes: [
      { id: 'faculty', label: 'faculty-issuer', sub: 'signs the degree', kind: 'agent', x: 118, y: 110 },
      { id: 'cred', label: 'Credential', sub: 'signed, revocable', kind: 'ledger', x: 336, y: 220 },
      { id: 'zk', label: 'ZK proof', sub: 'threshold, not score', kind: 'gate', x: 560, y: 330 },
      { id: 'employer', label: 'employer', sub: 'verifies in seconds', kind: 'external', x: 764, y: 220 },
      { id: 'board', label: 'board-issuer', sub: 'revokes on Tuesday', kind: 'agent', x: 336, y: 450 },
      { id: 'stream', label: 'Revocation stream', sub: 'reaches verifiers', kind: 'gate', x: 764, y: 450 },
      { id: 'fund', label: 'Stipend escrow', sub: 'released on progress', kind: 'teg', x: 118, y: 330 },
    ],
    edges: [
      { id: 'e-issue', from: 'faculty', to: 'cred', label: 'signed, dated' },
      { id: 'e-prove', from: 'cred', to: 'zk', label: 'prove the threshold' },
      { id: 'e-verify', from: 'zk', to: 'employer', label: 'rule held, score hidden' },
      { id: 'e-revoke', from: 'board', to: 'stream', label: 'Tuesday revocation' },
      { id: 'e-stipend', from: 'fund', to: 'cred', label: 'released on progress' },
      { id: 'a-forge', from: 'employer', to: 'cred', attackOnly: true, label: 'forged certificate', curve: 50 },
    ],
    script: [
      { edge: 'e-issue', state: 'active', dwellMs: 1400, caption: 'The faculty signs. The credential is dated, revocable, and its own proof.' },
      { edge: 'e-prove', state: 'active', dwellMs: 1500, caption: 'The candidate proves the threshold without opening the transcript.' },
      { edge: 'e-verify', state: 'active', dwellMs: 1400, caption: 'The employer verifies the rule held. The score stays private.' },
      { edge: 'e-revoke', state: 'active', dwellMs: 1400, caption: 'A Tuesday revocation reaches every verifier by Wednesday.' },
      { edge: 'e-stipend', state: 'active', dwellMs: 1400, caption: 'Stipends release from escrow on attested progress.' },
    ],
  },
  attacks: [
    {
      title: 'The beautiful forgery',
      attack: 'A candidate presents a perfectly typeset degree certificate from a real university that never issued it.',
      mechanism: 'Verification does not read the document; it checks the issuer’s signature against published keys. A forgery is not a worse document here, it is a missing signature, and the check that finds it takes seconds and asks nobody’s permission.',
      rail: 'S14',
      consequence: 'The verification fails plainly, the real issuer’s register is untouched, and the beautiful typesetting convinces exactly no one who checked.',
      script: [
        { edge: 'a-forge', state: 'denied', dwellMs: 1900, stopAt: 0.66, flashNode: 'cred', caption: 'S14. A forgery is a missing signature. The check takes seconds.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Data Protection Policy', href: '/compliance/doc/data-protection-policy' },
    { label: 'AI System Lifecycle', href: '/compliance/doc/ai-system-lifecycle' },
  ],
  rails: ['S02', 'S07', 'S14', 'S16', 'S19'],
  standup: {
    infra: 'A registry per issuing institution, or a shared one per sector body.',
    agents: '4 roles; issuance plugs into the student information system that already exists.',
    integration: 'The SIS and exam systems remain the source of academic truth; the protocol carries the signed public half.',
  },
  nonClaims: [
    'LYCEUM verifies that an issuer signed a claim. Accreditation of the issuer itself remains the sector’s question.',
    'No diploma-recognition treaty is implemented or implied; recognition between jurisdictions stays with the authorities that grant it.',
    'No grade-threshold circuit ships yet. proof_of_reputation, the registry’s only threshold check, validates inputs and is not a zero-knowledge proof; the threshold half of LYCEUM waits for a circuit of its own.',
  ],
  mermaid: `flowchart LR
  F["faculty issuer"] -->|"sign attestation<br/>expiry + revocable"| CRED["credential<br/>verifiable vs published keys"]
  CRED -->|"ZK threshold proof<br/>circuit not yet written"| V["verifier"]
  B["board issuer"] -->|"revocation"| WS["event stream<br/>reaches cached verifiers"]
  FUND["scholarship escrow"] -->|"release on attested progress"| TEG["TEG"]
  CRED --> ES[("append-only record<br/>outlives the issuer")]`,
  legacy: [
    { system: 'The SIS', connect: 'The source of academic truth, read-side. The protocol carries the signed public half.' },
    { system: 'Exam and assessment platforms', connect: 'Results flow to faculty issuers. Attestations are signed and expiry-dated.' },
    { system: 'HR verification workflows', connect: 'Employers verify in seconds against issuer keys instead of calling the registrar.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
