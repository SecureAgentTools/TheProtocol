import type { BlueprintDeep } from '../types'

// LYCEUM deep architecture (§18) — credentials that verify in seconds,
// revoke honestly, and prove thresholds without opening transcripts.

export const deep: BlueprintDeep = {
  intro:
    'LYCEUM deployed: the issuing institutions sign on their own frame; verifiers check against published keys in seconds with no registrar in the loop; revocations ride the event stream to everyone who ever cached a credential; and the transcripts sit below, deliberately connected to nothing, because the zero-knowledge rail exists precisely so they never have to leave. The trace replays one candidate, issuance to a threshold proved without a score.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE ISSUERS’ FRAME', sub: 'faculty and board, signing keys published', x: 30, y: 50, w: 440, h: 420, kind: 'frame' },
      { id: 'zp', label: 'VERIFIERS AND CANDIDATES', sub: 'their registries, their questions', x: 530, y: 50, w: 440, h: 330, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'revocations reach every verifier', x: 600, y: 415, w: 370, h: 195, kind: 'fabric' },
      { id: 'ze', label: 'ACADEMIC SOURCE SYSTEMS', sub: 'issuance reads the SIS; transcripts never leave it', x: 30, y: 630, w: 440, h: 105, kind: 'external' },
    ],
    nodes: [
      { id: 'board', label: 'board-issuer', sub: 'licences, revocable', kind: 'agent', x: 230, y: 325 },
      { id: 'stream', label: 'revocation stream', sub: 'rides the events', kind: 'gate', x: 395, y: 410 },
      { id: 'attest', label: 'attestations', sub: 'published keys', kind: 'registry', x: 140, y: 150 },
      { id: 'zk', label: 'ZK circuits', sub: 'prove, not show', kind: 'registry', x: 395, y: 240 },
      { id: 'faculty', label: 'faculty-issuer', sub: 'expiry-dated degrees', kind: 'agent', x: 140, y: 395 },
      { id: 'teg', label: 'stipend escrow', sub: 'released on progress', kind: 'teg', x: 395, y: 315 },
      { id: 'hospital', label: 'verifier-desk', sub: 'hospital: threshold', kind: 'agent', x: 720, y: 150 },
      { id: 'v-es', label: 'their records', sub: 'proofs, not scores', kind: 'ledger', x: 890, y: 150 },
      { id: 'candidate', label: 'candidate-anna', sub: 'holds her proofs', kind: 'agent', x: 760, y: 260 },
      { id: 'fund', label: 'scholarship-fund', sub: 'escrows stipends', kind: 'agent', x: 895, y: 335 },
      { id: 'xfer', label: 'cross-registry', sub: 'pays exactly once', kind: 'teg', x: 880, y: 500 },
      { id: 'mesh', label: 'federation mesh', sub: 'each cached verifier', kind: 'registry', x: 690, y: 560 },
      { id: 'sis', label: 'SIS / exams', sub: 'academic truth', kind: 'external', x: 400, y: 695 },
      { id: 'transcripts', label: 'transcripts', sub: 'closed, by design', kind: 'external', x: 220, y: 695 },
    ],
    edges: [
      { id: 'e-sis', from: 'sis', to: 'faculty', label: 'from the SIS', dashed: true, curve: 8 },
      { id: 'e-sign1', from: 'faculty', to: 'attest', label: 'signs', labelT: 0.62, curve: -46 },
      { id: 'e-sign2', from: 'board', to: 'attest', label: 'licences', labelT: 0.39, curve: -52 },
      { id: 'e-revoke', from: 'board', to: 'stream', label: 'revokes', dashed: true, labelT: 0.56 },
      { id: 'e-ride', from: 'stream', to: 'mesh', label: 'to every verifier', dashed: true, labelT: 0.6 },
      { id: 'e-verify', from: 'hospital', to: 'attest', label: 'verifies in seconds', labelT: 0.63 },
      { id: 'e-zk', from: 'candidate', to: 'zk', label: 'threshold, not score', labelT: 0.3 },
      { id: 'e-circuit', from: 'zk', to: 'attest', dashed: true },
      { id: 'e-stipend', from: 'fund', to: 'xfer', label: 'escrows stipends', curve: 12, labelT: 0.44 },
      { id: 'e-sland', from: 'xfer', to: 'teg', label: 'staged', curve: -80, labelT: 0.66 },
      { id: 'e-progress', from: 'teg', to: 'attest', label: 'on progress', labelT: 0.4 },
      { id: 'e-vemit', from: 'hospital', to: 'v-es', dashed: true },
    ],
    script: [
      { edge: 'e-sis', dwellMs: 1300, caption: 'Issuance reads the student information system, which remains the academic truth.' },
      { edge: 'e-sign1', dwellMs: 1400, caption: 'The engineering faculty signs the degree: expiry-dated, revocable, its keys published.' },
      { edge: 'e-sign2', dwellMs: 1300, caption: 'The medical board signs the licence on the same rails.' },
      { edge: 'e-verify', dwellMs: 1400, caption: 'A hospital verifies in seconds against the issuer’s published keys. No registrar is in the loop.' },
      { edge: 'e-zk', dwellMs: 1500, caption: 'The hospital needs to know the boards were passed above threshold. It does not need the score. The candidate proves the threshold, zero-knowledge.' },
      { edge: 'e-circuit', dwellMs: 1400, caption: 'The proof verifies against a published circuit. The rule held; the number never appeared.' },
      { edge: 'e-vemit', dwellMs: 1200, caption: 'The verifier records the proof, not the transcript.' },
      { edge: 'e-revoke', dwellMs: 1400, caption: 'On Tuesday, the board revokes a licence.' },
      { edge: 'e-ride', dwellMs: 1500, caption: 'The revocation rides the event stream to every verifier that ever cached the credential. Wednesday’s verification honestly fails.' },
      { edge: 'e-stipend', dwellMs: 1300, caption: 'Scholarship stipends run the same rails: escrowed at award.' },
      { edge: 'e-sland', dwellMs: 1300, caption: 'The stipend lands exactly once, staged.' },
      { edge: 'e-progress', dwellMs: 1400, caption: 'Each stage releases on attested progress, and a dispute, if it comes, argues over evidence.' },
    ],
    traceLabel: 'One candidate: issued, verified in seconds, threshold proved, score unseen.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One credential class, re-read as attestations.',
      runs: 'Nothing. One degree programme redrawn as attestation types, expiry rules and revocation events.',
      agents: 'None. The registrar’s office settles expiry and revocation semantics while they are still words.',
      integrates: 'Nothing. The SIS and the exam systems stay the source of truth.',
      notYet: 'No key is published. Nothing verifies.',
      proof: 'One graduating class re-expressed as signed attestations, and the registrar confirms every edge case, including the withdrawn degree, maps cleanly.',
    },
    {
      name: 'Pilot',
      headline: 'One faculty issues; one employer verifies.',
      runs: 'A registry seat for the institution, single VM if policy requires its own walls.',
      agents: 'faculty-issuer signing real credentials for volunteers; one verifier-desk at a partner employer.',
      integrates: 'Issuance reads the SIS; transcripts remain untouched and unread.',
      notYet: 'No ZK proofs. No revocation broadcast beyond the pilot pair. No stipends.',
      proof: 'A volunteer’s credential verifies at the partner in under ten seconds against published keys, and a staged revocation fails their next check honestly.',
    },
    {
      name: 'Production',
      headline: 'The institution signs; the sector verifies.',
      runs: 'A registry per issuing institution, or a shared one per sector body.',
      agents: 'The full cast: faculty and board issuers, verifier desks, the scholarship fund on escrow rails.',
      integrates: 'The SIS feeds issuance; ZK threshold proofs verify against published circuits; transcripts never leave the vault.',
      notYet: 'Accreditation of the issuer itself remains the sector’s question, not this deployment’s claim.',
      proof: 'A season of hiring checks completes with zero transcript requests, because every threshold question was answered by a proof.',
    },
    {
      name: 'Federation',
      headline: 'Credentials that travel; scores that do not.',
      runs: 'Unchanged. Institutions and employers federate as they come.',
      agents: 'Credentials travel with candidate DIDs; revocations reach every cached verifier.',
      integrates: 'Each new institution or employer is a signed card and a licence.',
      notYet: 'Diploma-recognition treaties stay with the authorities that grant them.',
      proof: 'A candidate credentialed at one institution is verified by an employer on another continent in seconds, with the transcript still closed.',
    },
  ],
  sequenceTitle: 'One threshold, proved without the score',
  sequence: `sequenceDiagram
  participant SIS as SIS (source of truth)
  participant Fac as faculty-issuer
  participant Att as signed attestations
  participant Anna as candidate
  participant ZK as ZK circuit (published)
  participant Hos as verifier-desk
  SIS-->>Fac: result, read-side
  Fac->>Att: attestation signed, expiry-dated
  Anna->>ZK: prove: score above threshold
  ZK-->>Hos: proof verifies against the circuit
  Hos->>Att: issuer keys checked, seconds
  Note over Hos: the rule held#59; the number never appeared
  Note over Att: a Tuesday revocation makes Wednesday's check honestly fail`,
  sizing: [
    { level: 'L1', what: 'Candidates and small employers join with accounts only', containers: '0 of theirs' },
    { level: 'L2', what: 'An institution issues via agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'A frame per institution or sector body', containers: '~9, one VM up' },
  ],
}
