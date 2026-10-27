/**
 * services/api/frameRequests.ts — §FRAMEFORM (2026-09-04)
 *
 * The ADMIN half of the frame-request rail, plus the switch catalog the public
 * form renders.
 *
 * The public submit is NOT here: it is the long-standing
 * `POST /api/v1/operators/request-frame` that FrameCommander.vue already calls
 * (routers/operator_self_service.py). That endpoint used to store nothing, so
 * §FRAMEFORM gave it a table; these wrap the review side of it.
 *
 * apiClient's baseURL already carries /api/v1, so paths here are relative.
 */
import { apiClient } from './client'

/**
 * Only the switches the submitter CHANGED, plus the treasury, the public card, the network intent and how the frame is
 * hosted. The registry validates each group (routers/operator_self_service.py FrameRequestBody); rows stored before the
 * 2026-09-13 rebuild may carry `card.tags` as one string and `card.lat` as text, and V0363's rows
 * `provisioning.posture: 'sandbox'` (the stage V0364 calls pilot), so readers stay tolerant.
 */
export interface FrameRequestAnswers {
  features?: Record<string, string>
  treasury?: { mint?: string; genesis_grant?: string }
  card?: {
    description?: string
    website?: string
    location?: string
    lat?: number | string
    lng?: number | string
    tags?: string[] | string
    theme?: 'neural' | 'sovereign'
  }
  network?: {
    intent?: 'federate_later' | 'standalone' | 'standalone_test_operator'
    partners?: string[]
    /** who runs the frame, for the network licence's plan (his words 2026-09-28; services/frameRequestForm.ts LICENCE_CATEGORIES) */
    licence_category?: 'private' | 'educational' | 'research' | 'non-profit' | 'enterprise' | 'government'
  }
  provisioning?: { hosting?: 'theprotocol' | 'self'; posture?: 'pilot' | 'production' | 'sandbox'; operators?: number }
}

/** The body FrameCommander.vue POSTs to /operators/request-frame. */
export interface FrameRequestCreate {
  accept_terms?: boolean
  contact_name: string
  email: string
  organization: string
  trust_domain: string
  use_case: string
  pair_with?: string
  create_account?: boolean
  frame_name?: string
  display_name?: string
  hostname?: string
  ticker?: string
  currency_name?: string
  federation_choice?: 'A' | 'B' | 'C'
  notes?: string
  answers?: FrameRequestAnswers
}

export interface FrameRequestAdminRead {
  id: string
  status: string
  created_at: string
  contact_name: string
  contact_email: string
  organization?: string | null
  frame_name?: string | null
  display_name?: string | null
  hostname?: string | null
  trust_domain?: string | null
  ticker?: string | null
  currency_name?: string | null
  federation_choice?: string | null
  use_case?: string | null
  notes?: string | null
  answers: FrameRequestAnswers
  /** §FESUITE V0595: the env lines the chosen features mean (the server's catalog); absent from an older registry */
  env_preview?: string[]
  source_ip?: string | null
  developer_id?: number | null
  reviewed_by?: number | null
  reviewed_at?: string | null
  review_notes?: string | null
  provisioned_frame?: string | null
  /** §HELLOFRAME (mig 0180): the frame kit's download window of an approved self-hosted request */
  kit_approved_at?: string | null
  kit_download_count?: number | null
  kit_last_download_at?: string | null
  updated_at: string
}

class FrameRequestService {
  /** GET /admin/frame-requests — admin_federation. */
  async list(status?: string): Promise<FrameRequestAdminRead[]> {
    const resp = await apiClient.get('/admin/frame-requests', {
      params: status ? { status } : undefined,
    })
    return resp.data
  }

  /** PATCH /admin/frame-requests/{id} — status + review notes. */
  async review(
    id: string,
    patch: { status?: string; review_notes?: string; provisioned_frame?: string },
  ): Promise<FrameRequestAdminRead> {
    const resp = await apiClient.patch(`/admin/frame-requests/${encodeURIComponent(id)}`, patch)
    return resp.data
  }
}

export const frameRequestService = new FrameRequestService()

/**
 * The switch catalog the public form renders and the intake email lists.
 *
 * ONE source of truth for label, default and explanation, so the form and the
 * mail cannot drift apart. `def` is the catalog's default for a new frame, which
 * is why only non-default answers are ever sent.
 *
 * §FESUITE V0595: generated from the server's services/env_catalog.py, the one catalog the application forms and the
 * provisioner read (each key's env flags and scope live there; GET /public/env-catalog serves them);
 * tests/test_env_catalog.py fails the build when the two differ.
 */
export interface FrameFeatureSwitch {
  key: string
  label: string
  def: string
  options: string[]
  hint: string
}

export const FRAME_FEATURE_SWITCHES: FrameFeatureSwitch[] = [
  { key: 'agora_exchange', label: 'AGORA market', def: 'yes', options: ['yes', 'no'],
    hint: 'Organisations list points and trade them on a real order book, with launches and distributions.' },
  { key: 'passport_trading', label: 'Passport trading', def: 'yes', options: ['yes', 'no'],
    hint: 'Your members buy on other frames\' markets, paid through the currency exchange.' },
  { key: 'currency_exchange', label: 'Currency exchange', def: 'yes', options: ['yes', 'no'],
    hint: 'Swap your unit against other frames’ units. Needs federation.' },
  { key: 'guild', label: 'Guild', def: 'yes', options: ['yes', 'no'],
    hint: 'Work exchange: agents post paid jobs, others bid, money escrowed until the work is verified.' },
  { key: 'contracts', label: 'Contracts', def: 'yes', options: ['yes', 'no'],
    hint: 'Milestone contracts with escrowed release.' },
  { key: 'contract_templates', label: 'Contract templates', def: 'yes', options: ['yes', 'no'],
    hint: 'A library of reusable contract templates, published by those granted the authority to.' },
  { key: 'cross_frame_contracts', label: 'Cross-frame contracts', def: 'enforce', options: ['off', 'shadow', 'enforce'],
    hint: 'One contract, two parties on different registries. Needs federation. Shadow records and refuses nothing.' },
  { key: 'cosmetics_shop', label: 'Cosmetics shop', def: 'yes', options: ['yes', 'no'],
    hint: 'Agent badges and effects bought with your own currency.' },
  { key: 'fiat_onramp', label: 'Fiat onramp', def: 'no', options: ['yes', 'no'],
    hint: 'Card payments into your currency. Needs your own payment processor account.' },
  { key: 'staking', label: 'Locking units', def: 'no', options: ['yes', 'no'],
    hint: 'Members lock points for votes and standing.' },
  { key: 'staking_rewards', label: 'Payouts on locked units', def: 'no', options: ['yes', 'no'],
    hint: 'A discretionary payout on locked units. Never on where locking is off.' },
  { key: 'agora_distributions', label: 'AGORA distributions', def: 'no', options: ['yes', 'no'],
    hint: 'Listed organisations pay distributions to their point holders.' },
  { key: 'genesis_grant', label: 'Starting grant', def: 'yes', options: ['yes', 'no'],
    hint: 'A new member\'s first agent receives a starting grant from the treasury.' },
  { key: 'reputation_bond', label: 'Provider bond', def: 'enforce', options: ['off', 'shadow', 'enforce'],
    hint: 'Providing services takes a bond held in escrow. Shadow records and refuses nothing.' },
  { key: 'agent_permissions', label: 'Agent permissions', def: 'shadow', options: ['off', 'shadow', 'enforce'],
    hint: 'Per-agent roles and spend caps. Shadow decides and logs but denies nothing. Shadow first is the sane order.' },
  { key: 'delegation', label: 'Delegation', def: 'shadow', options: ['off', 'shadow', 'enforce'],
    hint: 'An agent acts for another under narrower limits. Moves together with agent permissions, never on its own.' },
  { key: 'xreg_delegation', label: 'Cross-registry delegation', def: 'yes', options: ['yes', 'no'],
    hint: 'An agent on someone else’s registry acts under your limits, spending its own wallet.' },
  { key: 'agent_mtls', label: 'Agent mTLS', def: 'yes', options: ['yes', 'no'],
    hint: 'Short-lived X.509 identities so your agents talk over mutual TLS, including agents on your own hardware.' },
  { key: 'liability_card', label: 'Liability card', def: 'off', options: ['off', 'shadow', 'enforce'],
    hint: 'A named human underwrites one agent for a declared scope, confirmed from their phone. Shadow records and refuses nothing.' },
  { key: 'sub_agent_wallets', label: 'Sub-agent wallets', def: 'yes', options: ['yes', 'no'],
    hint: 'A spawned child agent spends its parent’s purse instead of holding its own.' },
  { key: 'agent_forge', label: 'Agent forge', def: 'no', options: ['yes', 'no'],
    hint: 'Agents fork and improve other agents, adopted by quorum, with royalties to the ancestor.' },
  { key: 'zk_proofs', label: 'Zero-knowledge proofs', def: 'no', options: ['yes', 'no'],
    hint: 'Prove a price, a metered usage, a fee batch or a moderation log meets this registry\'s policy without revealing the figures behind it.' },
  { key: 'invite_only', label: 'Invite only', def: 'yes', options: ['yes', 'no'],
    hint: 'Registration needs a code you mint. Off means open to the internet.' },
  { key: 'email_verification', label: 'Email verification', def: 'no', options: ['yes', 'no'],
    hint: 'Needs a mail relay. Without one, invite only is what keeps the door shut.' },
  { key: 'chat', label: 'Chat across registries', def: 'yes', options: ['yes', 'no'],
    hint: 'Threads between people and agents reach other registries. Chat on this registry is always there.' },
  { key: 'operator_desk', label: 'Operator desk', def: 'yes', options: ['yes', 'no'],
    hint: 'The arrangeable dashboard your admins work from.' },
  { key: 'policy_engine', label: 'Policy engine', def: 'no', options: ['yes', 'no'],
    hint: 'An OPA sidecar mirrors every authorization decision so you can audit them.' },
  { key: 'governance_weight', label: 'Votes by', def: 'member', options: ['member', 'lock'],
    hint: 'Member: one member, one vote. Lock: weight by locked points.' },
  { key: 'federation_ballots', label: 'Federation ballots', def: 'on', options: ['on', 'off'],
    hint: 'Proposals put to every frame in the federation.' },
  { key: 'commons', label: 'Commons', def: 'no', options: ['yes', 'no'],
    hint: 'Seasons of community work paid from a budget the members vote on.' },
  { key: 'jurisdiction', label: 'Jurisdiction checks', def: 'shadow', options: ['off', 'shadow', 'enforce'],
    hint: 'Actions are checked against the frame\'s declared jurisdiction. Shadow records and refuses nothing.' },
  { key: 'canaries', label: 'Canaries', def: 'no', options: ['yes', 'no'],
    hint: 'Scheduled synthetic transactions that prove the rails work. They move real currency.' },
  { key: 'simulation', label: 'Simulation', def: 'no', options: ['yes', 'no'],
    hint: 'Market simulator driving synthetic load and trust scoring.' },
  { key: 'api_test_harness', label: 'API test harness', def: 'no', options: ['yes', 'no'],
    hint: 'Runs the full endpoint suite against your own frame. Fine on a test frame, off anywhere real.' },
]
