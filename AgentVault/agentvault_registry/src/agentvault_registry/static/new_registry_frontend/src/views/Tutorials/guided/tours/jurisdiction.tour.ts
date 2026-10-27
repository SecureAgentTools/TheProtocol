import type { GuidedTour } from '../tour.types'

// REGAUTH (SPEC 2026-08-15) — the regulatory authorization rail: declare which
// lifecycle acts need state approval, watch them park, record the approval,
// watch them proceed, and see the public proof on the signed card. Operator
// series: admin + admin_platform. All anchors are static on /admin/jurisdiction
// so the tour audit can walk every step without pre-staging a parked act.
export const jurisdictionTour: GuidedTour = {
  id: 'jurisdiction',
  title: 'Operator: Jurisdiction and Regulatory Approval',
  subtitle: 'Declare what needs state approval, park it until the approval is on file, prove it publicly',
  icon: 'mdi:scale-balance',
  accent: '#2dd4bf',
  estMinutes: 5,
  requireAdmin: true,
  requireFlag: 'platform',
  steps: [
    {
      id: 'intro', title: 'Why this rail exists', placement: 'center',
      body: 'In most places, opening an **AGORA market**, running a **launch**, or operating a **fiat lane** needs approval from a state authority first.\n\nThe jurisdiction profile could already deny a feature outright. This rail adds the third state: **allowed only with a recorded regulatory authorization**. You declare which acts need approval; the platform parks them until the approval\'s reference number is on file; the claim is published on the **signed registry card** so anyone can check it.',
    },
    {
      id: 'panel', title: 'The Jurisdiction panel', anchor: 'juri-hero', placement: 'bottom', route: '/admin/jurisdiction',
      body: 'Everything lives here: the declared profile, the regulated-actions declaration, and the authorization records.\n\nOne principle governs it all: **the platform ships mechanism, never legal conclusions**. Nothing is regulated until *you* declare it, and the platform never claims to verify a state\'s stamp: you attest, publicly, with your liability behind it.',
    },
    {
      id: 'profile', title: 'The declared profile', anchor: 'juri-profile', placement: 'bottom',
      body: 'The **jurisdiction profile** is your deployment\'s own declaration of what the law applicable to *you* permits. It rides the signed registry card with a hash, so peers and the public can hold you to it.\n\nThe **global mode** shown here is the master switch: while it is `off`, everything on this page is inert.',
    },
    {
      id: 'declare', title: 'Declare a regulated action', anchor: 'juri-regulated-actions', placement: 'bottom',
      body: 'Pick an act from the closed vocabulary: `exchange.listing` (approving a listing), `exchange.launch` (opening a launch), `fiat.lane`, or `registry.operation` (your own operating license, display-only).\n\nName the **authority** that must approve it. Saving writes the declaration into your profile: it becomes part of the signed public attestation.',
    },
    {
      id: 'modes', title: 'Shadow first, enforce when ready', anchor: 'juri-regulated-actions', placement: 'bottom',
      body: 'Each entry carries its own **mode**. `shadow` observes: the act proceeds, and the log records that it *would* have parked. `enforce` actually parks it.\n\nEntry-level `enforce` is live the moment you save, **even while the global mode stays shadow**, because you wrote it into your own declaration. Activation is a profile save: no restart, no redeploy.',
    },
    {
      id: 'table', title: 'Authorizations on file', anchor: 'juri-regauth-table', placement: 'top',
      body: 'Every recorded approval lives here. **Liveness is derived at read time**: a record is `live` while it is active and inside its validity window. Expiry needs no cleanup job: the gate simply parks the act again on the next attempt.\n\nRevoking is status-only and takes a reason; renewals are recorded as new rows, so the history stays whole.',
    },
    {
      id: 'record', title: 'Record an approval', anchor: 'juri-regauth-record', placement: 'top',
      body: 'You obtained the approval from the authority **out-of-band**: their process, their paper. Here you record its **reference id** (the cert or file number the state gave you), the authority, the jurisdiction, and the validity window.\n\nThe covered act proceeds on its very next attempt.',
    },
    {
      id: 'evidence', title: 'Evidence tiers', anchor: 'juri-record-evidence', placement: 'top',
      body: 'Three strengths of proof:\n\n1. **Reference only**: the number anyone could take to the authority.\n2. **Document hash**: pick the approval document and it is hashed **in your browser**; only the `sha256:` fingerprint is submitted. The document never leaves your machine.\n3. **Countersigned contract**: a contract on this network signed by an authorized representative, referenced by id.',
    },
    {
      id: 'park', title: 'What a parked act looks like', anchor: 'juri-how', placement: 'top',
      body: 'With an `enforce` entry and nothing on file, the act answers **409 with a checklist**: which action, which authority, and where to record. The AGORA admin desk renders that checklist right under the listings table when an approval parks.\n\nRecord the reference, retry, done. The park is a to-do, not a dead end.',
    },
    {
      id: 'proof', title: 'Public proof', placement: 'center',
      body: 'Every **live** authorization is published twice: on the **signed registry card** (`compliance` block, covered by the card signature via a recomputable digest) and at the public endpoint `/api/v1/jurisdiction/authorizations`.\n\nThat closes the loop: the auditor and anyone else can compare what this deployment *claims* against how it *behaves*. A false reference is a provable public misrepresentation: that is the trust model, and it is stronger than a checkbox.',
    },
  ],
}
