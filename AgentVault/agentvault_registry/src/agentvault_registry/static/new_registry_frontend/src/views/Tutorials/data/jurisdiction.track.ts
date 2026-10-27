import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 16: Jurisdiction — regulatory approval as a first-class flow (REGAUTH,
 * SPEC 2026-08-15)
 *
 * The operator story, end to end: declare that an act needs state approval →
 * watch the public proof surface (empty) → record the approval's reference id →
 * see it live on the admin table, the public endpoint AND the signed registry
 * card → revoke it and watch the proof disappear. The platform ships mechanism,
 * never legal conclusions: nothing here verifies a state's stamp; the operator
 * attests publicly, with liability behind the claim.
 *
 * Auth verified from routers/admin_jurisdiction.py: profile + authorization
 * writes need a developer with the admin_platform flag; the proof endpoints
 * (/jurisdiction/authorizations, /.well-known/registry-card.json) are public.
 * NOTE: the sandbox login step needs the sandbox tutorial-admin credentials
 * (rotated 2026-08-08; held by the deployment operator). The body carries the
 * placeholder from ./sandboxLogin.ts, not a credential.
 */
export const jurisdictionTrack: TutorialTrack = {
  id: 'jurisdiction',
  title: 'Regulatory Approval',
  subtitle: 'Declare it, park it, record the approval, prove it publicly',
  description: 'Declare which lifecycle acts need state approval in the jurisdiction profile, record the approval reference the authority gave you, and verify the claim on the public proof endpoint and the signed registry card. The rail that lets a regulated adopter run AGORA listings, launches and fiat lawfully.',
  icon: 'scale',
  color: 'teal',
  gradientFrom: 'from-teal-500',
  gradientTo: 'to-cyan-600',
  estimatedMinutes: 6,
  prerequisites: [],
  completionTitle: 'Compliance Operator',
  steps: [
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as the sandbox admin',
      subtitle: 'Obtain a developer JWT with admin_platform',
      explanation: 'Jurisdiction declarations and authorization records are **admin acts** (the `admin_platform` flag): they change the deployment\'s public compliance posture, so they land in the audit trail at warning severity.\n\nThe password is the sandbox operator\'s and is never part of this page: the sign-in carries a placeholder, and the runner has no field for the real one yet, so as shipped this step is refused (401).',
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with the sandbox tutorial-admin account',
        body: { ...SANDBOX_TUTORIAL_LOGIN },
        authType: 'none',
        formEncoded: true,
      },
      captures: [{ key: 'juriDevToken', responsePath: 'access_token', displayLabel: 'Developer JWT', sensitive: true }],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
    },
    {
      id: 'read-profile',
      stepNumber: 2,
      title: 'Read the declared profile',
      subtitle: 'What does this deployment currently claim?',
      explanation: 'The **jurisdiction profile** is the operator\'s own declaration of what the law applicable to them permits. `declared: false` means nothing is restricted and nothing is regulated: the rail is inert by default.\n\nThe `mode` field is the global master switch (`off` | `shadow` | `enforce`).',
      apiCall: {
        method: 'GET',
        path: '/admin/jurisdiction-profile',
        description: 'Current declaration + global mode',
        authType: 'developer',
        authTokenRef: '$juriDevToken',
      },
      requiresStepId: 'authenticate',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['declared', 'mode'] },
    },
    {
      id: 'declare',
      stepNumber: 3,
      title: 'Declare a regulated action',
      subtitle: 'requires_authorization: the third state',
      explanation: 'The profile could already **deny** a feature outright. This block adds the state between allow and deny: **allowed only with a recorded regulatory authorization**.\n\nHere we declare that approving an AGORA listing needs approval from a (demo) authority, in `shadow` mode: acts still proceed, and the log records what *would* have parked. Flipping the entry to `enforce` later is just another PUT: runtime-activatable, no restart.',
      apiCall: {
        method: 'PUT',
        path: '/admin/jurisdiction-profile',
        description: 'Declare the profile with a requires_authorization entry',
        body: {
          name: 'Tutorial declaration',
          version: 1,
          features: {},
          requires_authorization: {
            'exchange.listing': { authority: 'Sandbox Demo Authority', scope: 'per_subject', mode: 'shadow' },
          },
        },
        authType: 'developer',
        authTokenRef: '$juriDevToken',
      },
      requiresStepId: 'read-profile',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['declared', 'profile_hash'] },
      notes: 'The response carries the profile_hash that also rides the signed registry card: the declaration is now a public attestation.',
    },
    {
      id: 'public-empty',
      stepNumber: 4,
      title: 'The public proof surface (empty)',
      subtitle: 'No auth needed: anyone can read it',
      explanation: 'Every **live** authorization is public at this endpoint: the exact set the signed registry card carries, so the two can never tell different stories.\n\nRight now it is empty: we declared a requirement, but nothing is on file. With the entry in `enforce` mode, approving a listing would answer **409 with a checklist** naming the action, the authority, and where to record.',
      apiCall: {
        method: 'GET',
        path: '/jurisdiction/authorizations',
        description: 'Public read-only proof endpoint',
        authType: 'none',
      },
      requiresStepId: 'declare',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['authorizations', 'count'] },
    },
    {
      id: 'record',
      stepNumber: 5,
      title: 'Record the approval',
      subtitle: 'The reference id the authority gave you',
      explanation: 'You obtained the approval **out-of-band**: the authority\'s process, their paper. What you record is its **reference id**, the authority, the jurisdiction and the validity window.\n\nOptional stronger tiers: a `sha256:` hash of the approval document (hashed client-side, the document never uploads) and a countersigned contract ref. The record is an attestation with your liability behind it: a false reference is a provable public misrepresentation.',
      apiCall: {
        method: 'POST',
        path: '/admin/jurisdiction-profile/authorizations',
        description: 'Record one regulatory authorization',
        body: {
          action: 'exchange.listing',
          subject_ref: 'TUT1',
          authority: 'Sandbox Demo Authority',
          jurisdiction: 'sandbox',
          reference_id: 'DEMO-TUTORIAL-0001',
        },
        authType: 'developer',
        authTokenRef: '$juriDevToken',
      },
      requiresStepId: 'declare',
      captures: [{ key: 'juriAuthId', responsePath: 'authorization.id', displayLabel: 'Authorization id' }],
      validation: { successStatusCodes: [201], requiredResponseKeys: ['recorded'] },
    },
    {
      id: 'admin-table',
      stepNumber: 6,
      title: 'See it on file',
      subtitle: 'Liveness is derived, never stored',
      explanation: 'The admin listing shows every record with a computed `live` flag: **active AND inside its validity window**, derived at read time. Expiry needs no cleanup job; the gate simply parks the act again on the next attempt after `valid_until` passes.\n\nA record with no `valid_until` is open-ended until revoked.',
      apiCall: {
        method: 'GET',
        path: '/admin/jurisdiction-profile/authorizations',
        description: 'Admin view: all records + the action vocabulary',
        authType: 'developer',
        authTokenRef: '$juriDevToken',
      },
      requiresStepId: 'record',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['authorizations', 'actions'] },
    },
    {
      id: 'public-proof',
      stepNumber: 7,
      title: 'Public proof, now live',
      subtitle: 'The claim anyone can check',
      explanation: 'The same endpoint from step 4 now lists the authorization: action, subject, authority, reference id, window. Anyone (a counterparty, the auditor, the actual authority) can read it without credentials and compare the claim against the deployment\'s behavior.',
      apiCall: {
        method: 'GET',
        path: '/jurisdiction/authorizations',
        description: 'Public proof endpoint, now non-empty',
        authType: 'none',
      },
      requiresStepId: 'record',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['authorizations', 'count'] },
    },
    {
      id: 'card',
      stepNumber: 8,
      title: 'The signed registry card carries it',
      subtitle: 'compliance block, signature-covered',
      explanation: 'The registry card (v0.6) publishes the declaration and every live authorization in its `compliance` block, with a **recomputable digest leaf inside the card signature**: tamper with the block and the signature breaks.\n\nThat is the whole trust model in one object: a public, signed, verifiable attestation.',
      apiCall: {
        method: 'GET',
        path: '/admin/registry-card',
        description: 'The full signed card (compliance.regulatory_authorizations + compliance.digest)',
        authType: 'developer',
        authTokenRef: '$juriDevToken',
      },
      requiresStepId: 'record',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['registry_card_version'] },
      notes: 'Same payload the world fetches unauthenticated at /.well-known/registry-card.json; the admin alias exists for the editor UI. Look for compliance.regulatory_authorizations and the signed compliance.digest leaf.',
    },
    {
      id: 'revoke',
      stepNumber: 9,
      title: 'Revoke it',
      subtitle: 'Status-only, reasoned, evented',
      explanation: 'Revocation never deletes: the row flips to `revoked` with a reason, at a timestamp, and a ledger event records it. The covered act parks again on its very next attempt: liveness is re-derived at use, never cached in the act.\n\nRenewals are recorded as **new rows** under their own reference, so the history stays whole.',
      apiCall: {
        method: 'POST',
        path: '/admin/jurisdiction-profile/authorizations/$juriAuthId/revoke',
        description: 'Revoke the tutorial authorization',
        body: { reason: 'tutorial cleanup' },
        authType: 'developer',
        authTokenRef: '$juriDevToken',
      },
      requiresStepId: 'record',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['revoked'] },
    },
    {
      id: 'proof-gone',
      stepNumber: 10,
      title: 'The proof is gone',
      subtitle: 'Full circle',
      explanation: 'The public endpoint is empty again, and the next card build drops the record and turns the card ETag over: peers re-pull, the world sees the revocation.\n\nThat is the complete flow a regulated adopter runs: declare → (act parks) → obtain approval out-of-band → record the reference → act proceeds → proof stays public for exactly as long as the approval is live.',
      apiCall: {
        method: 'GET',
        path: '/jurisdiction/authorizations',
        description: 'Public proof endpoint, empty once more',
        authType: 'none',
      },
      requiresStepId: 'revoke',
      validation: { successStatusCodes: [200], requiredResponseKeys: ['authorizations'] },
    },
  ],
}
