import type { GuidedTour } from '../tour.types'

// §TOURSERIES (2026-08-02) — OPERATOR SERIES 1/6: the first hour with a handed-over registry.
//
// Audience: a NEW ADMINISTRATOR of a registry (often one that just changed hands via an
// admin invite code). Walks: what you arrived holding, rotating yourself in, minting the
// next invitation, the public registration-config contract, and the mail posture check.
//
// requireAdmin only (no single flag fits — it spans invites, settings and mail). The
// Invitations tab exists only where `beta_invite_required` is on AND the viewer can
// administer codes (true on the handed-over pair, false on registry-a) — those steps use
// set-tab fallbacks and bodies that read correctly either way (settings-tour pattern).
export const opFirstStepsTour: GuidedTour = {
  id: 'op-first-steps',
  title: 'Operator: First Steps',
  subtitle: 'Your first hour holding the keys',
  icon: 'mdi:account-star',
  accent: '#34d399',
  estMinutes: 5,
  requireAdmin: true,
  steps: [
    {
      id: 'intro', title: 'You hold a registry now', placement: 'center',
      body: 'This tour is for the person **running** the node.\n\nIf you arrived through an ' +
        '**admin invite code**, you registered with your own password and your account holds ' +
        'exactly the admin areas the invitation named — no credentials ever travelled. ' +
        'This walk covers the four things worth doing in your first hour.',
    },
    {
      id: 'password', title: '1 · Own your login', anchor: 'set-tab-security', placement: 'bottom', route: '/settings',
      body: 'If your account was pre-made rather than created through an invitation, it may carry a **forced ' +
        'password change** — every admin call answers 403 until you set your own. The ' +
        '**Security** tab holds password change and two-factor.\n\nPasswords need 12+ ' +
        'characters with upper, lower, digit and a special character.',
    },
    {
      id: 'invites', title: '2 · Create the next invitation', anchor: 'set-tab-invitations,set-tab-security', placement: 'bottom',
      body: 'On an invite-gated registry, the **Invitations** tab is where accounts come from. ' +
        'An admin invitation names **which admin areas** it confers (platform, federation, ' +
        'treasury, enforcement, support) — never the legacy super-flag — and it can never ' +
        'grant an area **you** do not hold yourself.\n\nOn a registry with open registration ' +
        'this tab stays hidden; nothing to create.',
    },
    {
      id: 'regconfig', title: '3 · Check the front door', placement: 'center',
      body: 'Your registry advertises its own registration rules publicly:\n\n' +
        '`GET /api/v1/auth/registration-config`\n\nIt reports whether email verification is ' +
        'on, whether an invite code is required, and the password policy — so you (or your ' +
        'assistant) can **check** instead of guessing. The one broken combination: ' +
        'verification **on** with no working mail path locks every new account out.',
    },
    {
      id: 'mail', title: '4 · Confirm your mail posture', anchor: 'mail-hero', placement: 'bottom', route: '/admin/mail-fleet',
      body: 'The **Mail Console** shows how this node sends email: **direct** SMTP, ' +
        '**relay** through a parent frame (credential mail only), or **none + invites**. ' +
        'The verdict line calls out the lockout combination explicitly.\n\nOn a node without ' +
        'mail authority this page politely says so — that is itself the answer.',
    },
    {
      id: 'verdicts', title: 'Reading the verdicts', anchor: 'mail-banner,mail-hero', placement: 'bottom',
      body: '**OK** — verification and sending agree. **LOCKOUT** — verification is on but ' +
        'nothing can send; fix before anyone registers. **UNGATED** — neither verification ' +
        'nor invites guard the door. **UNREACHABLE** is deliberately not "ok": an unreachable ' +
        'node is unknown, not healthy.',
    },
    {
      id: 'outro', title: 'The keys are yours', placement: 'center',
      body: 'Login owned, next invitation created, front door checked, mail posture confirmed.\n\n' +
        'Continue with **Operator: Watchtower Basics** for the daily-driving views, and the ' +
        '**Operator Docs** (menu) for the full manual — chapter 13 connects your AI assistant.',
    },
  ],
}
