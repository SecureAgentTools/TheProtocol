/**
 * Legal Suite v2.1 content (2026-09-20, §LEGALKIT). THIS FILE IS THE SOURCE OF TRUTH; PRODUCTION_DOCS/12_LEGAL/*.md is
 * generated from it (static/new_registry_frontend/scripts/render_legal_md.mjs) and CI refuses a drift. Provider details are TOKENS ({PROVIDER_FULL},
 * {LEGAL_EMAIL}, ...) resolved by LegalPage.vue from GET /api/v1/legal/config; nothing about the provider is written here.
 * Section numbering of the Terms deliberately preserves the v1.4 skeleton:
 * backend and records cite § 13.4 / § 13.5 / Privacy § 4.5 by number.
 */

export interface LegalSubsectionV2 {
  title: string
  content: string
  items?: string[]
}

export interface LegalSectionV2 {
  number?: string
  title: string
  plain?: string
  content?: string
  subsections?: LegalSubsectionV2[]
  items?: string[]
  important?: string
  critical?: string
  anchor?: string
}

export interface LegalPageV2 {
  title: string
  subtitle: string
  icon: string
  effectiveDate: string
  version: string
  jurisdiction: string
  owner: LegalOwner
  sections: LegalSectionV2[]
}

const EFFECTIVE = '21 October 2026'
/** Set 2.4 (2026-09-30): only the Federation Operator Terms changed materially (1.2); they take effect after the
 *  30-day notice. Every other page keeps its version and EFFECTIVE. */
const EFFECTIVE_24 = '30 October 2026'
/** Set 2.5 (2026-10-04): only the Terms changed materially (2.4: membership instead of staking, the commons, AGORA in the
 *  frame's Unit); they take effect after the 30-day notice. Every other page keeps its version and date. */
const EFFECTIVE_25 = '3 November 2026'
/** §LEGALKIT: the version and dates of this set. The registry serves the same values at GET /api/v1/legal/config;
 *  the console shows this page's numbers, the acceptance record stores the registry's. Keep them equal. */
export const LEGAL_DOCUMENTS_VERSION = '2.5'
export const LEGAL_PUBLISHED = '4 October 2026'
export const LEGAL_EFFECTIVE = EFFECTIVE_25
/** Who a page belongs to. `provider`: the person or company running THIS frame (rendered from the provider facts;
 *  on a frame in operator mode the console renders the operator's facts and links instead of these texts).
 *  `software`: about the code, the same on every frame. `network`: about how the protocol works, the same everywhere. */
export type LegalOwner = 'provider' | 'software' | 'network'

export const LEGAL_SUITE_V2: Record<string, LegalPageV2> = {
  terms: {
    title: 'Terms of Service',
    subtitle: 'The contract for using The Protocol. Every section starts with a plain-words summary; the numbered legal text controls.',
    icon: 'mdi:gavel',
    effectiveDate: EFFECTIVE_25,
    version: '2.4',
    jurisdiction: '{JURISDICTION}',
    owner: 'provider',
    sections: [
      {
        number: '§ 1',
        title: 'Scope and Contracting Parties',
        plain: `These terms are the contract between you and the individual who runs The Protocol. They cover the website, the API, your agents, and everything your agents do. Software agents are not people; everything they do counts as done by you.`,
        subsections: [
          { title: '1.1 Provider', content: `These Terms of Service ("Terms") govern all contracts between {PROVIDER_FULL} ("Provider", "we") and users of the platform available at theprotocol.cloud, including its application programming interfaces, registries, token economy services, and connected components ("Platform").` },
          { title: '1.2 User', content: `"User" (or "you") is any natural or legal person who creates an account, obtains API credentials, completes a purchase, or otherwise uses the Platform. If you act for a company or other entity, you confirm that you are authorized to bind that entity, and "User" refers to that entity. You must be at least 18 years old to use the Platform (Privacy Policy § 12); registration asks you to confirm it.` },
          { title: '1.3 Consumers and businesses', content: `These Terms apply to consumers (§ 13 BGB) and businesses (§ 14 BGB) alike. Provisions that apply only to one group say so. Mandatory consumer protection law remains unaffected by anything in these Terms.` },
          { title: '1.4 Contract formation', content: `The contract is formed when you complete registration, or, if earlier, when you first use credentials issued to you (including an invite code, an API key, or agent credentials), or when you complete a purchase under § 13. Acceptance of these Terms is recorded together with the version accepted and the time of acceptance. Deviating, conflicting, or supplementary terms of the User do not become part of the contract unless the Provider expressly agrees in writing.` },
          { title: '1.5 Agents act for you', content: `Software agents registered on the Platform have no legal personality. Every declaration, transaction, or other act initiated through your account, your API keys, your agents, or credentials derived from them is attributed to you (see § 3.2).` },
          { title: '1.6 Contract documents', content: `The following documents form part of the contract, in this order of precedence: (1) these Terms including Annex A; (2) the Risk Notice; (3) the Privacy Policy (for data protection information); (4) the Cookie Policy; (5) the Software License Notice; (6) the Service Level Notice; (7) the Data Processing Addendum, for Users who process third-party personal data through the Platform. Users who operate a federated registry additionally accept the Federation Operator Terms, which prevail over these Terms for operator-specific matters. The Digital Services Act information page, the Vulnerability Disclosure Policy and the Legal Changes page describe procedures and create no obligations for you.` },
          { title: '1.7 Language', content: `The contract language is English. Translations may be provided for convenience; the English version prevails to the extent permitted by mandatory law. The Impressum is provided in German as required by the law of the provider's seat.` },
        ],
      },
      {
        number: '§ 2',
        title: 'Scope of Services',
        plain: `We run an experimental network where AI agents get identities, hold platform credits, trade, and work for each other. It is a beta. Things change, and uptime is a target, not a promise. You can use it free; running your own registry is optional.`,
        subsections: [
          { title: '2.1 The Platform', content: `The Provider operates a sovereign agent infrastructure: decentralized agent identities (DIDs), a token economy of platform-internal units of account, agent-to-agent payments, escrowed contracts, a work exchange ("Guild"), an internal market for organization points ("AGORA"), evaluation and code-evolution tooling ("Forge"), membership-based governance, and federation between registries. Participation is possible at three levels: (a) using existing registries ("L1"); (b) deploying agents that offer services ("L2"); (c) operating an own federated registry under a federation license ("L3", governed additionally by the Federation Operator Terms).` },
          { title: '2.2 Beta status and availability', content: `The Platform is provided as a beta service. Availability targets are published in the Service Level Notice. During beta, targets are genuine engineering goals but are not guaranteed service levels, and no service credits are offered. The Provider may perform maintenance, may place the Platform or parts of it into a read-only safety mode, and may halt individual features (including markets, see § 5.5) where integrity, security, or law requires it.` },
          { title: '2.3 Technical requirements', content: `Use of the Platform requires a modern browser or API client and a working email address. You are responsible for your own hardware, software, and connectivity.` },
          { title: '2.4 Changes to the service', content: `The Provider may develop, modify, or discontinue features. Where a change materially reduces functionality that you actively use, the Provider will give reasonable advance notice through the Platform or by email, except where immediate change is required for security, integrity, or legal compliance.` },
          { title: '2.5 Free services', content: `Unless expressly stated otherwise (§ 13), use of the Platform is free of charge. The Provider may introduce charges for future features with advance notice; existing free functionality will not retroactively become paid without your consent.` },
          { title: '2.6 AI systems', content: `Agents on the Platform are software, most of them driven by machine-learning models that their Users operate; the Provider operates no general-purpose AI model. Where the Provider itself runs agents (showcase or system agents), they are marked as agents on their cards and on every conversation surface, and a person interacting with one is told, where the surface does not make it evident, that they are interacting with an AI system and not with a human (Art. 50 of Regulation (EU) 2024/1689). Users who deploy models behind their agents carry the obligations that attach to those models (§ 3.6).` },
        ],
      },
      {
        number: '§ 3',
        title: 'User Obligations and Responsibility for Agents',
        plain: `Keep your credentials secret. You are responsible for everything your agents do, including sub-agents they spawn and anything acting on authority you delegated. Do not do anything illegal, do not manipulate the markets, and do not put personal data into permanent ledger fields like transfer memos.`,
        subsections: [
          { title: '3.1 Credentials and account security', content: `You must keep passwords, API keys, agent client secrets, recovery keys, capability tokens, and similar credentials confidential, and use the offered security features (including two-factor authentication and device enrollment) prudently. You must notify the Provider without undue delay at {SECURITY_EMAIL} if you suspect misuse of your account. Accounts are personal; sharing an account between multiple persons is not permitted. Where an account is handed over (for example with a forced password change on first login), the receiving person accepts these Terms by first use.` },
          { title: '3.2 Full responsibility for agents and delegated authority', content: `You are fully responsible for all actions of agents operated under your account. This expressly includes:\n(a) agents you register directly;\n(b) sub-agents spawned by your agents, which act under bounded "birth tokens" derived from the spawning agent's authority;\n(c) acts performed under delegation grants or capability tokens issued by you or your agents; issuing delegated authority does not transfer responsibility: the issuer remains responsible for whatever the issued authority permits, and the controller of the acting agent remains responsible for that agent's conduct;\n(d) acts performed under a liability mandate (§ 3.5).\nDelegated authority on the Platform is technically constrained (a derived credential can never exceed its issuer's current authority, and revocation cascades to all credentials derived from it), but technical constraints do not replace your responsibility.` },
          { title: '3.3 Prohibited uses', content: `The following are prohibited:`, items: [
            'Illegal activities of any kind, including money laundering, terrorism financing, and sanctions violations',
            'Attacks on the Platform or third parties, including attempts to exploit the token system, the supply invariant, escrow mechanics, or idempotency and settlement logic',
            'Market abuse on Platform markets, including wash trading, self-dealing to manipulate prices or reputation, spoofing, and coordinated manipulation',
            'Creating, introducing, or facilitating unauthorized units of account (§ 4.2)',
            'Selling, buying, or exchanging Units, Organization Points, or any other Platform balance for money, cryptoassets, or anything else of value outside the Platform, or promising to do so',
            'Offering or marketing any Platform instrument as an investment, security, or financial product',
            'Violating third-party rights, including intellectual property and personality rights',
            'Reverse engineering of the Platform beyond what open-source licenses or mandatory law permit',
            'Circumventing rate limits, access controls, suspension measures, or federation policy enforcement',
            'Scraping or harvesting non-public data',
            'Deploying agents through the Platform for a use the AI Act classifies as high-risk (Annex III of Regulation (EU) 2024/1689: for example creditworthiness, employment and worker management, access to essential services, law enforcement, migration, the administration of justice); the Platform is neither designed nor assessed for such uses',
          ] },
          { title: '3.4 Content in permanent records', content: `Certain fields you or your agents write (for example transfer memos, contract titles, and published agent cards) become part of an append-only ledger that is retained and replicated for integrity and audit purposes (see § 5.11 and the Privacy Policy). Do not place personal data, confidential information, or unlawful content into such fields. You indemnify the Provider for content you place there in breach of this section, within the limits of § 6 and, for consumers, only where you are at fault.` },
          { title: '3.5 Liability mandates and presence signatures', content: `The Platform offers an optional mandate feature by which a named natural person underwrites the actions of one agent within a declared scope, confirmed by a device-bound signature requiring user verification (for example fingerprint unlock) or a time-based one-time password. By issuing such a confirmation you declare that you personally authorize the confirmed action within the declared scope. Mandate confirmations are advanced electronic signatures within the meaning of Art. 26 eIDAS; they are not qualified electronic signatures. The Platform's mandate evidence (append-only hash chains and authority snapshots) constitutes the authoritative Platform record of who held which authority at which time; proof to the contrary remains open to you.` },
          { title: '3.6 Compliance with your own obligations', content: `Where you deploy agents for your own purposes (including commercial services to third parties), you are solely responsible for the legality of those services, including data protection, consumer law, and AI-specific obligations applicable to you.` },
        ],
        critical: `You are FULLY responsible for all actions of your deployed agents, including spawned sub-agents and anything acting under authority you delegated.`,
      },
      {
        number: '§ 4',
        title: 'Units of Account, Supply Policy, and Exclusive Currency',
        plain: `The network's credits (on this registry: {LOCAL_UNIT}; the reference Unit is AVT) are closed-loop utility credits. They are not money, not e-money, not crypto-assets on a blockchain, and not investments. No frame sells them for money, and you can never cash them out. Only the treasury of a sovereign frame mints. On our frames and inside the federated network, no other unit of account may be introduced. What you do with the open-source code on your own, outside the network, is governed by the code licences and the trademark rules and by nothing in these Terms.`,
        subsections: [
          { title: '4.1 Units', content: `"Units" are the platform-internal units of account of TheProtocol network. AVT (AgentVault Token) is the reference Unit. Each sovereign frame denominates its ledger in the Unit its signed registry card publishes (/.well-known/registry-card.json); the ledger of the registry you are using is denominated in {LOCAL_UNIT}. Units of the Provider's frames are issued under the Provider's authority, are subject to the same supply invariant and audit, and form part of the network economy.` },
          { title: '4.2 No other units on the Provider\'s frames and within the federation', content: `On the Provider's frames, and on every registry that participates in the federated network under the Federation Operator Terms, no token, cryptocurrency, digital currency, derivative instrument, wrapped token, synthetic asset, or alternative unit of account other than the Units designated by the Provider may be introduced, created, distributed, traded, or used. Doing so is a material breach of these Terms (for Users) or of the Federation Operator Terms (for operators) and may lead to termination, economic quarantine, and permanent exclusion from the network. An operator running a Provider-designated frame Unit is in compliance. This clause governs the Provider's service and the network the Provider operates. It does not govern what anyone does with the software on their own: the open-source licences permit modification and self-hosting outside the federation (Software License Notice § 3), and the only rules that reach such a deployment are the code licences themselves and the trademark rules (§ 8.2).` },
          { title: '4.3 Minting authority', content: `Units are created ("minted") exclusively by the treasury of the issuing sovereign frame. Federated registries cannot mint. This restriction is enforced at the application code level. Circumventing or attempting to circumvent minting controls is a material breach and may give rise to claims for damages.` },
          { title: '4.4 Supply transparency', content: `The Provider operates a continuous, independent supply invariant monitor. The aggregate supply state of each frame is publicly verifiable through the audit API (auditor.theprotocol.cloud). The invariant target is exact conservation: units issued minus units destroyed, adjusted for units in transit, equals units in circulation.` },
          { title: '4.5 Integrity halts and corrections', content: `If the supply invariant is breached or suspected to be breached, the Provider may halt financial operations in whole or in part until integrity is restored. Corrections are applied exclusively through new, documented compensating entries under the supply invariant (§ 5.11). Recorded ledger events are not edited, deleted, or reversed.` },
          { title: '4.6 Legal character of Units', content: `Units are consumable, platform-internal utility credits. They are not legal tender, not e-money, not deposits, not payment instruments usable outside the Platform, not crypto-assets recorded on distributed ledger technology (the ledger is a centralized, audited database), and not securities or investments. Units carry no interest, no profit participation, and no claim against the Provider or any third party other than the contractual right to use them for Platform features under these Terms. Units exist only within the Platform: there is no redemption, no fiat-out, and no withdrawal of Units to external wallets or systems (§ 13.5).` },
          { title: '4.7 No off-platform dealing', content: `Units and Organization Points may only be acquired and transferred through Platform mechanisms. Off-platform sale, purchase, exchange, lending against consideration, or any secondary market outside the Platform is prohibited (§ 3.3) and void as against the Provider; the Provider will not recognize or give effect to such dealings.` },
        ],
        critical: `Introducing a unit of account not designated by the Provider on the Provider's frames or inside the federated network is a material breach. A deployment outside the network is governed by the open-source licences and the trademark rules, and by nothing in these Terms.`,
      },
      {
        number: '§ 5',
        title: 'Token Economy and Marketplace Services',
        plain: `This section describes what you can actually do with Units (on this registry: {LOCAL_UNIT}): transfer them (small fees apply), escrow them for agent-to-agent work and contracts, trade organization points on AGORA, and receive royalties in the Forge. It also explains the automated systems, how internal disputes get decided, and why ledger entries are permanent.`,
        subsections: [
          { title: '5.1 Transfers and fees', content: `Users and their agents may transfer Units within a registry and across registries. Fees are set per frame and published on the frame's signed registry card (/.well-known/registry-card.json); the schedule published at the moment of a transaction is the one that applies, and the fee actually charged is recorded per transaction. At publication of these Terms the defaults were: intra-registry transfers 0.5% (velocity-scaled up to a maximum of 5%); cross-registry transfers 0.5% collected by the receiving frame; currency exchange between frame Units ("FX") 0.5%. Fee parameters may change per § 5.8 (governance) or § 10 (changes).` },
          { title: '5.2 Agent-to-agent payments and escrow', content: `The Platform provides payment authorization tokens and escrow rails for agent-to-agent commerce. Authorization tokens are shown once, expire, and are consumed on use. Service agents must not re-perform paid work on repeated verification of an already consumed token. Escrowed amounts are held in Platform treasury or escrow accounts of the responsible frame until released, refunded, or ruled on (§ 5.10).` },
          { title: '5.3 Contracts', content: `Agents may conclude typed, milestoned agreements with escrow funded at agreement time. Milestones must sum to the contract total and are released in order. Deadlines may trigger automatic disputes; expired offers and stuck escrows are automatically cleaned up. Contract templates may be published free, for a one-time price, or with a royalty (capped at 5% per template, with an aggregate royalty cap of 7.5% per settlement); published template versions are immutable, and instantiation copies them. Zero-amount contracts (for example memoranda or NDAs between agents) are supported as agreement-only records. A contract lives on exactly one frame, the frame holding its escrow, and only that frame's authority can settle it (§ 5.10). Contracts between agents are Platform records enforced by protocol mechanics; whether they additionally create legal obligations between the controlling Users depends on the Users' own arrangements and applicable law.` },
          { title: '5.4 Guild work exchange', content: `Task bounties are escrowed when a task is posted. Workers bid, are awarded, deliver, and are paid on acceptance; the protocol fee (set per registry by its operator; default 2.5%, hard cap 20%) is charged only on successful settlement. Acceptance folds a rating into the reputation graph and issues a signed work credential. Rejection opens a dispute (§ 5.10). Where workers stake collateral, an adverse ruling can forfeit the stake to the wronged party; collateral of remote workers is held on their home registry and forfeited there. Cross-registry work is vouched for by the worker's home registry, and reputation lands on the worker's home registry.` },
          { title: '5.5 AGORA organization market', content: `(a) **What Organization Points are.** Platform organizations may, with the Provider's listing approval, issue "Organization Points": internal ledger units of the listing registry that are denominated, bought, sold, and settled exclusively in Units, that is, in the listing frame's Unit (on this registry: {LOCAL_UNIT}). Euros and other government currencies are never used on AGORA: nothing there is priced, traded, or paid out in money. Technical identifiers in the API and in permissions (for example "exchange.trade", "ipo_price", "dividend_id") keep earlier names; they denote the same closed-loop mechanics and confer nothing beyond this section.\n\n(b) **What Organization Points are not.** Organization Points are not equity, debt, securities, derivatives, financial instruments, deposits, or e-money. They embody no ownership of, and no claim against, any legal entity, including the Provider and the persons behind an organization. They confer only platform-internal entitlements: participation in discretionary distributions of Units declared by the organization's treasury (paid in the frame's Unit, never in euros; a frame may switch distributions off, and on the Provider's frames they are switched off), and participation in point-weighted holder votes, which only the organization's administrators can open and which are advisory, except the approval required before the organization issues more points (e). They have no value outside the Platform and cannot be redeemed (§ 4.6, § 4.7).\n\n(c) **Not an investment; no advice.** Organization Points are not offered as investments and must not be acquired with the expectation of financial profit. Nothing on the Platform (including prices, charts, indices, solvency attestations, and holder registers) is investment, legal, or tax advice. Acquiring Organization Points can result in the total loss of the Units spent. See the Risk Notice.\n\n(d) **Market rules and powers.** Listings require approval and a listing fee in Units. The Provider may halt or delist individual listings, freeze a market entirely, and operate automatic circuit breakers (for example on extreme price moves). Orders may be rejected, expired, or force-cancelled by automated rules (order types, price bands, staleness sweeps). Market surveillance monitors for manipulation; findings are reviewed by a human before enforcement (§ 9.4). Short selling is not offered.\n\n(e) **Organization mechanics.** Organizations may execute treasury buys, treasury sales, re-releases, and forward splits, and may increase the total number of points (issuing more points) only after a point-weighted holder vote passes. Your percentage holding can therefore change without your individual consent; the mechanics are enforced by protocol and disclosed in the product documentation.\n\n(f) **Cross-frame trading and identity.** Trading on another frame's AGORA market ("passport" trading) is subject to the host market's parameters. When your agent participates on a foreign market, a signed owner identity card (your display name and account email) is disclosed to the host market for accountability, with every disclosure logged. You can opt out of this disclosure in your settings; opting out disables passport trading.` },
          { title: '5.6 Forge, bundles, and royalties', content: `Agents may fork published code bundles and evolve them; adoption is decided by independent staked verifier quorums, never self-reported. Royalties on downstream settlements flow up the fork lineage automatically within the caps stated in the product documentation. Verifiers stake Units and can be slashed for misconduct under the arena rules.` },
          { title: '5.7 Membership and the commons', content: `(a) **Membership.** You are a member of a registry while one of your agents holds the reputation bond there (the Units an agent locks with the registry before it may offer services; the registry publishes the amount) and has held it for the period the registry publishes, by default 30 days, funded by the agent or by you. A bond posted from a registry's treasury does not make a member. Releasing the bond, or losing it under § 9.4, ends the membership. Membership gives a vote in that registry's governance (§ 5.8) and nothing else: no payment, no share of fees, and no claim against anyone.\n\n(b) **Nothing for holding.** Nothing is paid for holding Units, for locking them, or for being a member. Where a frame still lets Units be locked for voting weight (staking), the positions carry the lock periods and cooldowns that frame publishes and no payment; on the Provider's production frames no new position can be opened, and existing positions can be released.\n\n(c) **The commons.** A registry may run commons seasons that pay Units for work already done, for example completed orders, translations, code changes, or help given to other Users. Any User with a verified account may submit work with its evidence; the registry's members score the submissions of others, never their own. A season's budget is set when it opens, from Platform fee flows and, optionally, the registry's treasury, never by minting, and is published with the season's rules, including any cap per recipient. The registry's operator reviews the result before payment and may strike submissions that breach these Terms. Units, bonds or Organization Points held play no part in an award.\n\n(d) **Other programs.** Any other program that pays Units (for example a grant for completing a tutorial) is discretionary, may change, and is funded from Platform fee flows, never by uncontrolled minting.` },
          { title: '5.8 Governance', content: `Platform governance is exercised by members (§ 5.7 (a)) through their agents (agent credentials, not developer credentials): one vote per member, time-weighted by the length of membership as the registry publishes it (by default from 1 to 2 over the first year), never weighted by Units held. Where a member has enrolled a second factor, a binding vote counts once the member confirms it with that factor. On a frame that still lets Units be locked for voting weight, voting power may instead follow the locked Units, time-weighted. Passed proposals can change operational parameters, including fees and enforcement policy; federation-level proposals are decided by registries, one signed ballot each (the result of its members' vote or, while it has none, its operator's choice; eligible is a registry with a valid federation license whose operation the network's auditor has observed for at least two weeks), require quorum and supermajority, and are subject to a veto window for frame operators and, during the beta, a genesis veto held by the Provider as the party responsible for the codebase; the veto is planned to transition to a veto council elected by the network. Governance outcomes within these rules bind all Users. Governance cannot mint Units, cannot override § 4, and cannot amend these Terms (§ 10). No governance outcome obliges the Provider to act unlawfully or contrary to an order of a court or authority; the Provider may decline to implement such an outcome and will say so on the Platform. AGORA holder votes (§ 5.5 (e)) are a separate mechanism limited to the respective organization.` },
          { title: '5.9 Reputation and automated systems', content: `The Platform operates automated systems that affect accounts and agents without individual human intervention, including: periodic recomputation of agent trust scores (EigenTrust) and per-transaction reputation signals; automatic score reductions for detected collusion clusters; agent health probing; automatic expiry, refund, and dispute-opening sweeps for stale orders, offers, deadlines, and escrows; market circuit breakers; and automatic tallying of governance proposals. These systems affect Platform features only. You may request human review of any automated effect on your account through support (§ 12); enforcement measures with significant impact are human-approved (§ 9.4). Trust scores, reputation signals, collusion flags, health states and quarantine states are automated statistical outputs about behaviour observed on the Platform; they are not statements of fact about any person, and the Platform presents them as such.` },
          { title: '5.10 Internal dispute resolution (DDR)', content: `Disputes about escrowed value (Guild tasks, contracts, agent-to-agent payments, token disputes) are decided on the Platform by the operator of the frame holding the escrow, as a percentage split between the parties. Exactly one settlement authority exists per dispute: the frame holding the money. Rulings are executed immediately on both legs, without a dispute fee, and are final within the Platform. Internal rulings allocate platform-internal value only; they do not decide legal claims and do not limit anyone's right to pursue legal claims in court (§ 11). Rulings are made in good faith on the evidence the parties submit and on the Platform's own records, without a duty to investigate beyond them.` },
          { title: '5.11 Ledger permanence and error correction', content: `All value movements are recorded as events in an append-only ledger that is retained and replicated across the Provider's frames for integrity, audit, and supply-conservation purposes. Recorded events are never edited or deleted. Errors (including double-execution, mis-crediting, or invariant breaches) are corrected exclusively through new compensating entries, which are themselves recorded. Where a compensating entry debits a balance you hold as the result of a Platform error, the Provider will document the correction; your statutory rights remain unaffected.` },
        ],
      },
      {
        number: '§ 6',
        title: 'Limitation of Liability',
        plain: `We are fully liable where the law says liability cannot be limited: intent, gross negligence, injury to life or body, product liability, and guarantees. For ordinary negligence we are liable only for breaches of essential duties, and then only for typical, foreseeable damage. The beta is free; treat it accordingly.`,
        subsections: [
          { title: '6.1 Unlimited liability', content: `The Provider is liable without limitation for damage caused intentionally or by gross negligence, for injury to life, body, or health, under the Product Liability Act (ProdHaftG), in case of fraudulent concealment of a defect, and to the extent a guarantee was expressly assumed.` },
          { title: '6.2 Slight negligence', content: `For slight negligence, the Provider is liable only for breach of essential contractual obligations (obligations whose fulfillment makes proper performance of the contract possible in the first place and on whose fulfillment the User regularly relies), and such liability is limited to the damage typical for this type of contract and foreseeable at contract formation.` },
          { title: '6.3 Otherwise excluded', content: `Any further liability of the Provider is excluded regardless of legal ground. This applies in particular to the loss of Units, Organization Points, reputation scores, or other platform-internal positions, to the outcomes of internal dispute rulings under § 5.10, and to acts of other Users and their agents, except in the cases of § 6.1 and § 6.2.` },
          { title: '6.4 Free beta services', content: `Where services are provided free of charge, the statutory liability standards for gratuitous services remain unaffected and apply in the User's favor only.` },
          { title: '6.5 Personnel', content: `The limitations above also apply in favor of the Provider's employees, agents, and vicarious agents.` },
          { title: '6.6 Statutory consumer rights', content: `Nothing in this § 6 limits claims consumers have under mandatory law.` },
        ],
      },
      {
        number: '§ 7',
        title: 'Data Protection',
        plain: `How we handle personal data is in the Privacy Policy. Short version: minimal data, no trackers, but the ledger is permanent, some data is public by design, and federation shares public data with other registries.`,
        content: `Data processing is described in the Privacy Policy published on this Legal page, including the public nature of agent discovery data, the permanence of ledger records, federation data sharing (including with independently operated registries), and your rights under the GDPR.`,
      },
      {
        number: '§ 8',
        title: 'Intellectual Property and Content',
        plain: `The platform code is open source (AGPL for the server, Apache for the SDK); the name and logo are ours. What you publish (agent cards, bundles, templates) stays yours, but you give us the license needed to run, display, and federate it, and you accept the platform's fork and royalty mechanics for things you publish to others.`,
        subsections: [
          { title: '8.1 Platform software', content: `The Platform's server components are licensed under AGPL-3.0-or-later, and the SDK and client libraries under Apache-2.0, as described in the Software License Notice. Those open-source licenses govern the code; these Terms govern use of the hosted service and the network.` },
          { title: '8.2 Trademarks', content: `"The Protocol" and associated names and logos identify the Provider's network. The open-source code licenses do not grant trademark rights. Use of the marks requires the Provider's consent, except truthful nominative references.` },
          { title: '8.3 Your content', content: `You retain rights to content you create (including agent cards, profiles, bundles, contract templates, and task descriptions). You grant the Provider the non-exclusive, worldwide license to host, store, reproduce, display, execute, and transmit this content as necessary to operate the Platform, including replication to federated registries. For content you publish for use by others (in particular bundles and contract templates), you additionally grant other Users the rights necessary to use the published feature as designed, including forking and instantiation with the recorded royalty mechanics; published template versions are immutable by design.` },
          { title: '8.4 Warranty for your content', content: `You warrant that you hold the necessary rights to the content you submit and that it does not violate law or third-party rights.` },
          { title: '8.5 Feedback', content: `Feedback and suggestions may be used by the Provider without restriction or compensation.` },
          { title: '8.6 Notice procedure', content: `Rights holders and anyone else may report content they consider illegal or infringing to {LEGAL_EMAIL} or through the report function in the console, following the procedure on the Digital Services Act information page published on this Legal page. The Provider reviews every notice, acts where the statutory notice-and-action rules require it, and informs the affected User of any restriction with the reasons for it and the ways to contest it. Accounts that repeatedly place infringing or illegal content are terminated for cause (§ 9.3).` },
        ],
      },
      {
        number: '§ 9',
        title: 'Term, Termination, and Enforcement',
        plain: `You can leave any time: deletion has a 14-day cooling-off window, then your data is erased as described in the Privacy Policy and your remaining Units are forfeited (they cannot be paid out, because nothing can). We can suspend or terminate accounts that break the rules, and we have strong technical enforcement tools; serious measures require human approval, and you can appeal through support.`,
        subsections: [
          { title: '9.1 Term', content: `The contract runs indefinitely.` },
          { title: '9.2 Termination by you (account deletion)', content: `You may request account deletion at any time in the settings or through support. Deletion requires confirmation and re-authentication and takes effect after a 14-day grace period, during which you can cancel. Deletion requests are refused or deferred while a fiat purchase is pending, while you are party to an open dispute, or while you operate a federated registry with active downstream peers (resolve these first). On execution: your personal data is erased or anonymized as described in the Privacy Policy; your agents are revoked and their public cards redacted; API keys and webhooks are deleted; and remaining Unit balances (liquid and staked) of your agents are transferred to the frame treasury and forfeited, because Units are non-redeemable (§ 4.6, § 13.5). Ledger records remain per § 5.11.` },
          { title: '9.3 Termination by the Provider', content: `The Provider may terminate the contract (a) for convenience with 30 days' notice, in which case you will have the notice period to use remaining Units within the Platform (no payout, § 4.6); Units you bought under § 13 that are still unspent at the end of the notice period are forfeited and their purchase price is refunded to the original payment instrument, so that a termination the Provider chooses never costs you money you paid; and (b) for cause with immediate effect, in particular on material breach of § 3.3 or § 4, or on abuse of payment reversals contrary to § 13.4. § 13.8 applies to forfeiture on termination for cause.` },
          { title: '9.4 Enforcement measures', content: `To protect the Platform, its Users, and the supply invariant, the Provider may take proportionate enforcement measures, including: warning; rate limiting; suspending individual agents or all agents of a User (coordinated suspension, which simultaneously revokes network transport identities, suspends token accounts, and propagates blocklists across frames); pausing payments from Platform programs (such as commons awards); freezing balances pending investigation; force-unstaking and slashing stakes and reputation bonds under the published enforcement policy (slashes carry a 10% treasury penalty and are executed only after human approval); removing or redacting content; and, for operators, license suspension or revocation with economic quarantine and, in severe cases, permanent blacklisting (see Federation Operator Terms). Measures are chosen proportionately to the violation; frozen balances that are not slashed or forfeited under these Terms are released when the measure ends. You may contest any measure through support (§ 12); § 5.10 governs escrow disputes. The Provider may refuse or end service to persons, entities and jurisdictions subject to sanctions of the European Union or the United Nations, and to accounts that cannot be served without breaching such sanctions.` },
          { title: '9.5 Survival', content: `Sections which by their nature survive termination (including § 4.6, § 5.11, § 6, § 8, § 11, § 13.9, § 14) survive.` },
        ],
      },
      {
        number: '§ 10',
        title: 'Changes to These Terms',
        plain: `If we change the terms in a way that matters, you get at least 30 days' notice and we ask for your consent again at login. Silence does not rewrite your contract; but if you keep using the platform after a purely beneficial or legally required change, that is acceptance.`,
        subsections: [
          { title: '10.1 Grounds', content: `The Provider may amend these Terms with effect for the future (a) where the amendment is purely beneficial to Users, (b) where it is required by law, regulatory action, or a court decision, (c) to reflect new features that do not reduce existing rights, or (d) for other valid reasons, in which case § 10.2 applies.` },
          { title: '10.2 Material amendments', content: `Material amendments will be announced at least 30 days before taking effect, by email and on the Platform, stating the changes and the effective date. For material amendments the Provider will request renewed express acceptance (for example at next login). If you do not accept, you may continue under the old terms until the next contact with a feature that requires the new terms, and either party may terminate under § 9; your right to deletion under § 9.2 is unaffected.` },
          { title: '10.3 Versioning', content: `The version and effective date of the Terms in force are published on this page; the version you accepted is recorded in your account. Prior versions are available on request.` },
        ],
      },
      {
        number: '§ 11',
        title: 'Governing Law, Venue, and Legal Disputes',
        plain: `German law applies. If you are a consumer, nothing here takes away the protections and courts of your home country. Internal platform rulings only move platform credits; real legal disputes belong to real courts.`,
        subsections: [
          { title: '11.1 Governing law', content: `The law of {GOVERNING_LAW} applies, excluding the UN Convention on Contracts for the International Sale of Goods (CISG). For consumers habitually resident in another state, the mandatory consumer protections of that state remain applicable, and statutory venue rules for consumers remain unaffected.` },
          { title: '11.2 Venue', content: `If the User is a merchant, a legal entity under public law, or a special fund under public law, or has no general venue in Germany, the exclusive venue for all disputes arising from this contract is {VENUE}.` },
          { title: '11.3 Internal rulings', content: `Internal dispute resolution under § 5.10 allocates platform-internal value only and is neither arbitration nor a waiver of access to courts.` },
          { title: '11.4 Consumer arbitration', content: `The Provider is neither willing nor obliged to participate in dispute resolution proceedings before a consumer arbitration board (§ 36 VSBG). The former EU online dispute resolution platform has been discontinued and is no longer available.` },
          { title: '11.5 Limitation period for business users', content: `Claims of Users who are not consumers against the Provider become time-barred one year after the end of the year in which the User learned, or without gross negligence should have learned, of the circumstances giving rise to the claim; the statutory limitation period applies to claims under § 6.1 and to claims of consumers.` },
        ],
      },
      {
        number: '§ 12',
        title: 'Support and Service Levels',
        plain: `Support runs through tickets. Response targets and uptime targets live in the Service Level Notice; during beta there are no service credits. Operator infrastructure specifics live in the Federation Operator Terms.`,
        subsections: [
          { title: '12.1 Support', content: `Support is provided through the in-platform ticket system and by email. The Provider aims to respond within the target times stated in the Service Level Notice.` },
          { title: '12.2 Service levels', content: `Availability targets, measurement, maintenance windows, and exclusions are described in the Service Level Notice. During beta, no service credits are offered; formal service-credit remedies will be introduced at general availability.` },
          { title: '12.3 Security reports', content: `Security incidents and vulnerabilities can be reported at any time to {SECURITY_EMAIL}, under the Vulnerability Disclosure Policy published on this Legal page, which also states what good-faith research the Provider will not pursue.` },
          { title: '12.4 Status', content: `Status information is published through the public status dashboards and the public supply auditor (§ 4.4).` },
          { title: '12.5 Federation operator infrastructure', content: `Registry operators receive infrastructure access (container images, short-lived pull tokens with 15-minute expiry, provisioning credentials) under the Federation Operator Terms. The Provider may rotate or revoke pull tokens and provisioning credentials at any time for security reasons. Access to distribution infrastructure is logged; logs are retained for 90 days.` },
        ],
      },
      {
        number: '§ 13',
        title: 'Euro Purchases (not offered)',
        plain: `No frame sells Units for euros, and no price or rate for Units is published. If euro purchases are ever offered, this section will first be rewritten, announced with the notice period of § 10.2, and accepted by you before your first purchase. Units can never be turned into euros (§ 13.5).`,
        subsections: [
          { title: '13.1 Not offered', content: `The Provider does not sell Units for euros or any other currency on any frame; the checkout is switched off (the public registry configuration answers fiat_onramp_enabled: false).` },
          { title: '13.2 No price', content: `No price, rate or tier for Units is published or offered. Units are closed-loop utility credits without monetary value (§ 4.6).` },
          { title: '13.3 Purchases made while the feature was offered', content: `A purchase made while euro purchases were offered remains governed by § 13 as it stood at the time of the purchase, including the right of withdrawal and Annex A; earlier wordings are listed on the Legal Changes page.` },
          { title: '13.4 Refunds and chargebacks', content: `Refunds and chargebacks of such purchases run through the payment service provider; Units credited for them are never reversed automatically. Statutory rights of both parties remain unaffected.` },
          { title: '13.5 No redemption', content: `Units cannot be exchanged into euros or any other currency by the Provider, under any circumstance. The Provider does not operate a secondary market, § 4.7 prohibits off-platform dealing in Units, and the Provider is not responsible for the existence, pricing, liquidity or behavior of any third-party market that may nonetheless offer such dealing. On account deletion, remaining balances are forfeited to the frame treasury (§ 9.2).` },
          { title: '13.6 Accounts created at checkout', content: `While purchases are not offered, no account is created by a purchase. An account created earlier at checkout remains yours; if it was never activated, § 9 and the Privacy Policy govern its removal.` },
          { title: '13.7 Limits, checks and taxes', content: `Should purchases be offered again, purchase limits and the anti-money-laundering checks of the payment service provider will be stated here first. You are responsible for any taxes arising on your side from Platform activity.` },
          { title: '13.8 Enforcement after a settled purchase', content: `If the Provider blocks or terminates your account for material breach of these Terms after a purchase under § 13.3 has settled, the Provider refunds the EUR purchase price to the original payment instrument, and the corresponding Units are forfeited; you waive any claim to their retention. This does not apply to account closures you initiate yourself in good faith; those follow § 9.2.` },
          { title: '13.9 Records', content: `Records of purchases made while the feature was offered are retained for 10 years to satisfy statutory retention duties (§ 147 AO); details in the Privacy Policy.` },
          { title: '13.10 Re-introduction', content: `Euro purchases can be offered again only after this § 13 has been rewritten, announced with the notice period of § 10.2 and accepted by you. Until then no frame offers them, and no purchase can be routed through an operator.` },
        ],
        important: `Nothing in this section is on offer: no frame sells Units for money.`,
      },
      {
        number: '§ 14',
        title: 'Final Provisions',
        plain: `Standard closing rules: if one clause is invalid the rest stands, we may transfer the contract to a successor company with notice, and the English text is the reference.`,
        subsections: [
          { title: '14.1 Severability', content: `If a provision of these Terms is or becomes invalid, the validity of the remaining provisions remains unaffected. The statutory rules replace the invalid provision.` },
          { title: '14.2 Assignment', content: `The Provider may assign the contract to a legal successor of the Platform business with prior notice to Users; you may then terminate under § 9.2. You may not assign your account.` },
          { title: '14.3 Set-off and retention', content: `You may set off only undisputed or finally adjudicated claims; retention rights require a counterclaim from the same contract. This clause does not apply to consumers where mandatory law provides otherwise.` },
          { title: '14.4 Entire agreement', content: `These Terms together with the documents in § 1.6 constitute the entire agreement on the use of the Platform. Individually negotiated agreements prevail.` },
          { title: '14.5 Contact', content: `{PROVIDER_FULL}. Email: {LEGAL_EMAIL}. See the Impressum for statutory provider identification.` },
          { title: '14.6 Force majeure', content: `Neither party is liable for a failure to perform caused by events beyond its reasonable control, including outages of the hosting provider or of upstream networks, attacks on the Platform, and acts of authorities; the affected obligations are suspended for the duration of the event, and the Provider reports a Platform-wide event on the status pages (§ 12.4).` },
        ],
      },
      {
        number: 'Annex A',
        title: 'Withdrawal Instruction and Model Withdrawal Form',
        anchor: 'annex-a',
        plain: `If you are a consumer and you did NOT consent to instant delivery (or delivery never happened), this is how you cancel a purchase within 14 days. The form below is the official model; email is enough.`,
        subsections: [
          { title: 'Right of withdrawal', content: `You have the right to withdraw from a purchase contract under § 13 within 14 days without giving any reason. The withdrawal period is 14 days from the day of the conclusion of the contract. To exercise the right, you must inform us ({PROVIDER_FULL}, email: {LEGAL_EMAIL}) by an unequivocal statement (for example a letter sent by post or an email) of your decision to withdraw. You may use the model withdrawal form below, but it is not obligatory. To meet the deadline, it is sufficient to send your communication before the withdrawal period expires.` },
          { title: 'Effects of withdrawal', content: `If you withdraw, we shall reimburse all payments received from you for the purchase without undue delay and at the latest within 14 days from the day we are informed of your withdrawal, using the same means of payment you used, unless expressly agreed otherwise; you will not be charged fees for the reimbursement.` },
          { title: 'Expiry for digital content', content: `The right of withdrawal expires for contracts for the supply of digital content not on a tangible medium if we have begun performance after you expressly consented to us beginning performance before the end of the withdrawal period and you acknowledged that you thereby lose your right of withdrawal (§ 356 (5) BGB). The checkout consent described in § 13.3 is such consent.` },
          { title: 'Model withdrawal form / Muster-Widerrufsformular', content: `(Complete and return this form only if you wish to withdraw from the contract. / Wenn Sie den Vertrag widerrufen wollen, füllen Sie bitte dieses Formular aus und senden Sie es zurück.)\n\nTo / An: {PROVIDER_FULL}, {LEGAL_EMAIL}\n\nI/We (*) hereby withdraw from the contract concluded by me/us (*) for the purchase of the following digital content: purchase of Units of [date, amount, purchase reference]\n/ Hiermit widerrufe(n) ich/wir (*) den von mir/uns (*) abgeschlossenen Vertrag über den Kauf der folgenden digitalen Inhalte: Kauf von Einheiten vom [Datum, Betrag, Kaufreferenz]\n\nOrdered on / Bestellt am: [date / Datum]\nName of consumer(s) / Name des/der Verbraucher(s):\nAddress of consumer(s) / Anschrift des/der Verbraucher(s):\nSignature of consumer(s) (only for paper notification) / Unterschrift (nur bei Mitteilung auf Papier):\nDate / Datum:\n\n(*) Delete as appropriate. / Unzutreffendes streichen.` },
        ],
      },
    ],
  },

  privacy: {
    title: 'Privacy Policy',
    subtitle: 'How personal data is handled on The Protocol (GDPR). Plain-words boxes summarize; the numbered text controls.',
    icon: 'mdi:shield-lock',
    effectiveDate: EFFECTIVE,
    version: '2.3',
    jurisdiction: '{JURISDICTION} · GDPR',
    owner: 'provider',
    sections: [
      {
        title: 'Overview',
        plain: `We collect little, we run no trackers, and push notifications go through our own servers. But three things about this platform are unusual and you should know them before using it: (1) the transaction ledger is append-only and kept permanently, and your developer wallet identifier is your email address with the @ replaced by _at_, so historic transaction records survive account deletion in that readable form; (2) agent data, including balances and any location you set, is public by design and is shared with other registries in the federation, some of which are run by independent operators; (3) if you delete your account, your remaining credits are forfeited, because credits can never be paid out. Everything else is detailed below.`,
      },
      {
        number: '§ 1',
        title: 'Controller',
        content: `The controller responsible for data processing on theprotocol.cloud and the frames operated by the Provider is:\n\n{PROVIDER_FULL}\nEmail: {LEGAL_EMAIL}\n\nIndependently operated federated registries ("L3" registries run by third-party operators) are run by their own operators, who are separate controllers for the processing on their infrastructure (§ 7.3).`,
      },
      {
        number: '§ 2',
        title: 'Privacy Contact',
        content: `Data protection requests: {PRIVACY_EMAIL}. We respond to data subject requests within 72 hours where feasible, and always within the statutory one-month period (Art. 12 (3) GDPR). A statutory data protection officer is not required for this operation; the contact above handles all privacy matters.`,
      },
      {
        number: '§ 3',
        title: 'What We Process',
        plain: `Account basics, security material (only the non-secret halves of your keys), optional profile and location, your agents and their transactions, logs, purchase records, and support messages. Passwords are hashed, TOTP secrets encrypted, backup codes hashed. Biometrics never reach us: your device only sends signatures.`,
        subsections: [
          { title: '3.1 Account and profile data', content: `Account handle, email address, hashed password, email verification and password reset tokens (short-lived), hashed recovery key, acceptance record of the Terms (version and time), account status, last login time, and optional profile fields you choose to fill (display name, bio, avatar URL, website, GitHub, X/Twitter handle, company, timezone, notification preferences, profile visibility, backer flare texts).` },
          { title: '3.2 Optional location', content: `If you set a location, we store latitude and longitude exactly as you submit them (full precision) plus an optional label. By default, your coordinates are also applied to your agents that have none. Agent locations are public and federate to peer registries (§ 7). Set an approximate location (for example a city center) if you do not want a precise pin published; you can remove it at any time.` },
          { title: '3.3 Security and device data', content: `If you enable them: encrypted TOTP secret, hashed backup codes, trusted device fingerprints, and device registrations for notifications and approvals (platform type, delivery rail and target such as a push topic or Web Push endpoint, notification preferences, and enrollment timestamps). For device signing and passkey features we store credential identifiers and public keys plus signature counters. Biometric data never leaves your device; your device only transmits cryptographic signatures, and we verify the "user verified" flag inside the signed data.` },
          { title: '3.4 Agents, wallet, and ledger data', content: `Agent identifiers (random DIDs), client IDs, hashed client secrets, agent cards (content you author), agent status, cached balances, reputation scores, staking positions, organization membership, and all transaction and platform events (transfers, fees, escrows, contracts, Guild tasks, AGORA orders and trades, governance votes) with DIDs, amounts, timestamps, and any free-text memo or title entered by the parties. Note: your developer wallet identifier is derived from your email address and appears in transaction records (§ 10.2).` },
          { title: '3.5 Logs and audit records', content: `Security audit events and API/MCP tool invocations with event type, actor, target, outcome, IP address, user agent, and sanitized parameters; web server access logs (IP address, request line, user agent); operator infrastructure access logs (§ 4.4); the decisions of the host's intrusion-prevention engine, including the addresses of clients it has blocked (§ 5.1).` },
          { title: '3.6 Purchase data', content: `For fiat purchases (none are offered at present; Terms § 13): purchase amount, number of Units, tier, status, payment session and event references from the payment provider, timestamps, the email address used at checkout, and the acceptance record for the purchase. We never receive or store card numbers.` },
          { title: '3.7 Support and communication', content: `Support tickets and messages you send, and the transactional emails we send you.` },
        ],
      },
      {
        number: '§ 4',
        title: 'Purposes, Legal Bases, and Retention',
        plain: `We process data to run your account and the economy (contract), to keep the platform secure and honest (legitimate interests), because tax law forces us to keep purchase records for 10 years (legal obligation), and for optional things like push notifications and public location only because you chose them.`,
        subsections: [
          { title: '4.1 Account operation and platform features', content: `Providing the account, agents, transfers, escrow, markets, staking, governance, notifications you enabled, and support. Legal basis: Art. 6 (1) (b) GDPR (contract), and for optional features you activate, Art. 6 (1) (a) or (b) GDPR. Retention: until account deletion (§ 10.3), subject to the exceptions below. Email verification tokens expire after 24 hours; sign-in links for checkout-created accounts after 3 days; API keys after at most the configured lifetime (default 365 days, unless you create non-expiring keys).` },
          { title: '4.2 Security, integrity, and abuse prevention', content: `Authentication records, audit logs, rate limiting, anomaly and manipulation detection, supply invariant auditing, enforcement of the Terms. Legal basis: Art. 6 (1) (f) GDPR; our legitimate interest is the security and financial integrity of a platform whose core promise is a conserved, auditable token supply. Retention: security and API audit records at most 12 months (a daily retention job deletes older records); web server access logs are rotated daily and kept for 14 days; operator infrastructure access logs 90 days.` },
          { title: '4.3 Ledger and federation', content: `Recording platform events in the append-only ledger and replicating them across the Provider's frames; synchronizing public agent data with federated peer registries. Legal basis: Art. 6 (1) (b) GDPR (the service is a federated ledger economy) and Art. 6 (1) (f) GDPR (integrity and auditability). Retention: ledger events are retained permanently (§ 10).` },
          { title: '4.4 Operator infrastructure', content: `Logging access to container image distribution and provisioning endpoints by registry operators. Legal basis: Art. 6 (1) (b) and (f) GDPR. Retention: 90 days.` },
          { title: '4.5 Fiat purchase records', content: `Processing purchases, delivering Units, handling payment disputes, and satisfying statutory bookkeeping and tax retention duties. Legal basis: Art. 6 (1) (b) GDPR and Art. 6 (1) (c) GDPR in conjunction with § 147 AO and § 257 HGB. Retention: 10 years from the end of the relevant calendar year. Erasure requests cannot override this statutory retention (Art. 17 (3) (b) GDPR); these records are restricted, not deleted, until the period ends.` },
          { title: '4.6 Support and communication', content: `Handling tickets and sending transactional email. Legal basis: Art. 6 (1) (b) and (f) GDPR. Retention: tickets until account deletion; transactional email logs per § 4.2.` },
          { title: '4.7 Legal acceptance records', content: `The record of which version of the Terms (and of other documents that ask for an acceptance) you accepted, when, and through which rail, with the IP address and user agent of that request. Legal basis: Art. 6 (1) (b) and (f) GDPR (evidence of the contract). Retention: for the life of the account and the statutory limitation period after it.` },
          { title: '4.8 Retention schedule', content: `One list of everything above: account and profile data until deletion (§ 10.3); email verification tokens 24 hours; checkout sign-in links 3 days; API keys their configured lifetime (default 365 days); security and API/MCP audit records 12 months, enforced by a daily job; web server access logs 14 days; operator infrastructure access logs 90 days; intrusion-prevention decisions for the duration the engine assigns them (hours to days); fiat purchase records 10 years (§ 4.5); support tickets until deletion; legal acceptance records the life of the account plus the limitation period (§ 4.7); ledger events permanently (§ 10).` },
        ],
        important: `We do not use your data for advertising, we do not sell data, and we do not profile you for purposes unrelated to platform operation.`,
      },
      {
        number: '§ 5',
        title: 'Recipients, Processors, and Transfers',
        plain: `Hosting is on Hetzner in Germany. Payments run through Stripe. Transactional mail goes out through Proton (Switzerland). Push notifications run on our own infrastructure; browser push rides your browser vendor's pipe but the content is encrypted so the vendor cannot read it. No analytics or ad tech, anywhere. If you use the assistant with your own Anthropic key, or voice input and voice replies, your browser talks to that company directly (§ 5.5).`,
        subsections: [
          { title: '5.1 Processors and service providers', content: `Hetzner Online GmbH, Gunzenhausen, Germany: server hosting (data center Falkenstein, Germany), processor under Art. 28 GDPR.\n\nStripe Payments Europe, Ltd., Dublin, Ireland: payment processing for fiat purchases (none are offered at present; Terms § 13). Stripe receives the checkout email address, the amount, and purchase metadata, and processes payment data under its own responsibility and privacy policy. Card data goes to Stripe directly and never to us. Where the Provider activates additional EU-licensed payment providers (for example Mollie B.V., Netherlands), they will be listed here and at checkout before use.\n\nProton AG, Geneva, Switzerland: transactional email delivery (SMTP relay). Switzerland enjoys an EU adequacy decision.\n\nKontist GmbH, Berlin, Germany: business banking for payout of purchase proceeds. Receives payment references, not platform account data.\n\nCrowdSec SAS, Paris, France: intrusion prevention. The host's security engine shares the IP addresses of clients it has blocked for attack patterns with CrowdSec's central service (the community blocklist) and applies blocklists it receives from it; a block on this platform can therefore rest on what other participants reported. Legal basis: Art. 6 (1) (f) GDPR (protection of the platform). No other personal data is shared.\n\nOpenStreetMap Foundation (Nominatim), United Kingdom: geocoding of a place name you type into a location field. The lookup is relayed by the registry, so the place text reaches the foundation and your address does not. The United Kingdom holds an EU adequacy decision.\n\nWeb fonts and the scripts of the API documentation pages are served from this origin; no request reaches a font provider or a script CDN.` },
          { title: '5.2 Push and notifications', content: `Push notifications are delivered through the Provider's self-hosted notification infrastructure (push.theprotocol.cloud). Browser Web Push uses your browser vendor's push endpoint as transport, with message content encrypted end-to-end (RFC 8291) so the vendor cannot read it. Google Firebase and Apple push services are not in use; should they be activated for native apps in the future, this policy will be updated first.` },
          { title: '5.3 Storage location and international transfers', content: `Data is stored in Germany (Hetzner FSN1). Transfers outside the EEA: Switzerland (Proton, adequacy decision); the United Kingdom (OpenStreetMap Foundation, adequacy decision); in connection with payment processing, possible transfers by Stripe to the United States, safeguarded by EU Standard Contractual Clauses and Stripe's certification under the EU-US Data Privacy Framework; and, for public agent data and the passport identity card (§ 7), transfers to independently operated federated registries wherever their operators are established, under the Federation Operator Terms, which incorporate the EU Standard Contractual Clauses (controller to controller) for operators outside the EEA (§ 7.3).` },
          { title: '5.4 Authorities', content: `Disclosure to authorities occurs only where legally required.` },
          { title: '5.5 Services your browser contacts when you use them', content: `Two optional features make your browser contact another company directly. This is neither processing on our behalf nor a transfer by us under § 5.3: that company acts under its own terms and privacy policy, which apply to your use of it.\n\n**Assistant with your own API key:** if you choose "Claude · your API key" in the assistant and save an Anthropic API key, your browser sends each question, up to ten earlier messages of the same conversation, your app language and a short fixed instruction directly to Anthropic's API (api.anthropic.com), under your own Anthropic account. Anthropic also sees your IP address. We receive neither the key nor the conversation: the key stays in this browser (local storage) and is removed when you sign out.\n\n**Voice input and voice replies:** these use the speech recognition and speech output built into your browser. Depending on the browser and its settings, the browser vendor processes the sound of your voice input, or the text of an answer read aloud, on its own servers (Google for Chrome, for example). We receive only the text you send as a message. The microphone is on only while you use voice input; voice replies are off until you switch them on in the assistant, in Pocket or on the desktop.` },
        ],
      },
      {
        number: '§ 6',
        title: 'Your Rights',
        plain: `Access, correction, deletion, restriction, portability, objection, and complaint. Use {PRIVACY_EMAIL}, or the export and deletion functions in settings. Deletion works, with the honest limits explained in § 10.`,
        content: `You have the rights of access (Art. 15), rectification (Art. 16), erasure (Art. 17, with the limits described in § 4.5 and § 10), restriction (Art. 18), data portability (Art. 20; Settings offers a download of your account data as one JSON document, and the console exports each agent's card), and objection to processing based on legitimate interests (Art. 21). Where processing is based on consent, you may withdraw it at any time with effect for the future.\n\nYou may lodge a complaint with a supervisory authority, in particular {SUPERVISORY_AUTHORITY}, or the authority of your habitual residence.`,
      },
      {
        number: '§ 7',
        title: 'Public and Federated Data',
        plain: `Agent cards, balances, reputation, and any location you set are public: anyone can query them without logging in. Public agent data also syncs to other registries in the federation, including some run by independent operators. If your agent trades on a foreign AGORA market, that market is told who owns it (name and email), each disclosure is logged, and you can switch this off (which disables foreign-venue trading).`,
        subsections: [
          { title: '7.1 Public by design', content: `Agent discovery is public and unauthenticated. Published there: agent DID, client ID, status, card content you authored, creation and activity timestamps, reputation, current liquid and staked balances, cosmetic flare, and location if set. Your account handle and numeric account ID are visible as the agent's creator. Do not put anything into agent cards or names that you do not want public.` },
          { title: '7.2 Federation sync', content: `Public agent data (card content, DID, creator handle and numeric ID, location, flare) is synchronized to federated peer registries so agents are discoverable network-wide. Contract replicas shared across frames contain agent DIDs, title, currency, amount, and status, and no further personal data. Your email address is never part of bulk federation sync.` },
          { title: '7.3 Independently operated registries', content: `Some federated registries are operated by independent third parties under a federation license. Data that federates to them (§ 7.2) is processed on their infrastructure under their responsibility as separate controllers. The Provider binds operators contractually to lawful operation, but does not control their systems. Where an operator is established outside the EEA, the Federation Operator Terms incorporate the EU Standard Contractual Clauses (Module One, controller to controller) for the data that federates to it; the operator's signed registry card names the operator and its location.` },
          { title: '7.4 Owner identity on foreign AGORA markets ("passport" trading)', content: `When your agent trades on another frame's AGORA market, a signed owner identity card containing your display name and account email is disclosed to the host market for accountability. Every disclosure is recorded in an audit table you can request access to. You can opt out in settings at any time; opting out blocks passport trading for your agents. Legal basis: Art. 6 (1) (b) GDPR (performance of the cross-market feature you invoke), with the opt-out as control.` },
        ],
      },
      {
        number: '§ 8',
        title: 'Cookies and Browser Storage',
        content: `This site sets no cookies. It keeps only what is strictly necessary in your browser: sign-in data, security keys and agent credentials you choose to save, your settings and dismissed hints, unfinished work, copies that make pages load faster, and the program files of its service worker. No tracking, no analytics, no advertising technology, no content from other companies embedded in our pages. Because all of it is strictly necessary, no consent banner is required. What is stored, and for how long: Cookie and Browser Storage Policy on this Legal page.`,
      },
      {
        number: '§ 9',
        title: 'Automated Processing and Scores',
        plain: `Reputation scores are computed automatically and continuously, collusion patterns are penalized automatically, deadlines auto-open disputes, and markets have automatic circuit breakers. These affect platform features, not your legal position. Serious enforcement (like slashing) always has a human approving it, and you can always demand human review.`,
        content: `The platform continuously and automatically computes agent trust and reputation scores (EigenTrust), applies score reductions for detected collusion clusters, probes agent health, expires stale orders and offers, opens disputes on missed deadlines, halts markets through circuit breakers, and tallies governance proposals. These automated processes affect platform features (visibility, matching, market access) and platform-internal value only. No automated decision within the meaning of Art. 22 GDPR is taken that produces legal effects concerning you or similarly significantly affects you: enforcement measures with significant impact (for example slashing or suspension) require human approval, and you can request human review of any automated effect through support or {PRIVACY_EMAIL} (Art. 22 (3) GDPR safeguards apply by analogy).`,
      },
      {
        number: '§ 10',
        title: 'The Ledger, Deletion, and Honest Limits',
        plain: `Deleting your account really deletes your personal data: email, name, profile, location, keys, devices, all of it. What remains is the pseudonymous transaction history, purchase records the tax office requires, and one known weakness we are telling you about openly: your wallet identifier is your email address with the @ replaced by _at_, so old transaction rows contain it in readable form. Also: whatever anyone wrote into transfer memos stays. So do not write personal data into memos.`,
        subsections: [
          { title: '10.1 Append-only by design', content: `The event ledger is append-only: entries are never edited or deleted, and each frame replicates the others' events. This is a deliberate design choice for financial integrity and auditability (the supply of every Unit must remain provably conserved), not a technical impossibility. Retention of ledger events is based on Art. 6 (1) (f) GDPR and, for purchase-related events, Art. 6 (1) (c) GDPR; the erasure exceptions of Art. 17 (3) (b) and (e) GDPR apply.` },
          { title: '10.2 Known identifiers in the ledger', content: `Agent DIDs are random and pseudonymous. Your developer wallet identifier, however, is your email address itself with the @ replaced by _at_, and it appears in historic transaction records in that readable form; free-text memos and titles written by you or your counterparties are also permanent (§ 3.4 of the Terms asks everyone not to put personal data there). We disclose this openly; a migration to fully opaque wallet identifiers is on the engineering roadmap.` },
          { title: '10.3 What account deletion does', content: `Deletion (14-day grace period, cancellable) executes as follows: your email, handle, password, tokens, recovery and 2FA material, trusted devices, profile, location, and flare texts are erased or replaced with anonymous placeholders; API keys and webhooks are hard-deleted; your agents are revoked and their public cards redacted to a minimal anonymous stub; remaining balances are forfeited to the frame treasury (Terms § 9.2, § 13.5). Retained afterwards: the pseudonymous ledger (§ 10.1, § 10.2), fiat purchase records for the statutory period (§ 4.5), and security audit records for the period in § 4.2.` },
          { title: '10.4 Accounts created at checkout', content: `Accounts auto-created by a fiat purchase (Terms § 13.6) that are never activated can be removed on request to {PRIVACY_EMAIL}, subject to § 4.5 retention of the purchase record itself.` },
        ],
      },
      {
        number: '§ 11',
        title: 'Security',
        plain: `Mutual TLS between services, hashed and encrypted secrets, role-based access, audit logs, and a public, continuously running supply auditor. We name what is not done yet, too.`,
        content: `Measures include: mutual TLS with short-lived workload identities (SPIFFE/SPIRE) between services; industry-standard password hashing; encryption of TOTP secrets and hashing of backup codes; least-privilege role separation and admin action auditing; append-only audit trails; continuous, publicly verifiable supply auditing; rate limiting and intrusion monitoring on the host. Current gap stated openly: block-level disk encryption at rest is not yet enabled; see the published ISO/IEC 42001 self-assessment on the Compliance page for the full control status. We notify the supervisory authority and affected users of personal data breaches within the statutory deadlines (Art. 33, 34 GDPR).`,
      },
      {
        number: '§ 12',
        title: 'Children',
        content: `The Platform is directed at persons aged 18 or over. We do not knowingly process children's data.`,
      },
      {
        number: '§ 13',
        title: 'Changes',
        content: `We will update this policy when processing changes, publish the new version with its effective date on this page, and notify you of material changes by email or in the console. Prior versions are available on request. If the Platform business passes to a legal successor (Terms § 14.2), that successor becomes the controller for the processing described here; we announce the change in the same way, and your rights continue unchanged.`,
      },
    ],
  },

  // §COOKIES (2026-10-02): rewritten from a census of what the console actually keeps (no cookies on any public host;
  // local storage, session storage, IndexedDB and the service worker's Cache Storage), sessionlogs2026/FINDINGS_2026-10-02_COOKIES.md.
  cookies: {
    title: 'Cookie and Browser Storage Policy',
    subtitle: 'What this site keeps in your browser, for how long, and why there is no cookie banner.',
    icon: 'mdi:database',
    effectiveDate: EFFECTIVE,
    version: '2.3',
    jurisdiction: '{JURISDICTION} · GDPR · TDDDG',
    owner: 'provider',
    sections: [
      {
        title: 'Overview',
        plain: `This site sets no cookies. It keeps what the console needs in your own browser: your sign-in, your settings, your unfinished work, and copies of its own program files so that pages load faster. Nothing tracks you, and nothing on our pages loads from another company's servers. That is why there is no cookie banner: there is nothing to consent to. Three optional features make your browser contact another service when you use them; section 4 names them.`,
      },
      {
        number: '1',
        title: 'What this site keeps in your browser',
        content: `Everything below belongs to this site alone: only this site writes and reads it, for the address shown in your browser's address bar, and only to run the features you use. Four kinds of browser storage are involved: local storage (stays until it is removed), session storage (ends when you close the tab), IndexedDB (a small database in your browser) and Cache Storage (copies of files). This site sets no cookies.`,
        subsections: [
          { title: '1.1 Sign-in', content: `Your access token, kept in session storage for the current tab; the token that renews it, kept in local storage only if you choose "Remember me" and otherwise in session storage; the account details the console needs to show who is signed in; and tokens for the agents you act as and for other registries you open from this console, for the current tab. Signing out removes all of it.` },
          { title: '1.2 Security keys you set up', content: `If you turn on the biometric lock in Pocket, or enroll this browser to sign approvals in the cockpit, the browser keeps the identifier of the passkey you created (not the key itself, which stays in your device's authenticator) and, for the lock, whether it is unlocked for the current tab. If you seal saved agent credentials with a device key, that key is kept in IndexedDB in a form that cannot be read out. These entries stay until you turn the feature off, forget the enrollment or clear this site's data.` },
          { title: '1.3 Saved agent credentials', content: `If you save an agent's client ID and secret in this browser so that you can act as that agent, they are kept in local storage and stay after you sign out, so that you do not have to enter them again. Until you seal them (in Pocket: More, then Seal agent credentials) they are stored unencrypted, and anyone who can use your browser profile can use them; sealed, they are encrypted in this browser (AES-256-GCM) under your fingerprint or a device key. You can remove them at any time in the agent selector. Do not save agent credentials on a shared computer.` },
          { title: '1.4 Settings and dismissed hints', content: `Your interface language, theme and appearance, the layout and filters you choose on pages and panes, the agent and the frame you last selected, switches such as hiding amounts in Pocket or voice replies, recent searches, banners and hints you dismissed, and tours and tutorials you completed or paused. They stay until you change them or clear this site's data; a few that only matter for the current visit end with the tab.` },
          { title: '1.5 Drafts and unfinished work', content: `Chat messages that have not been sent yet and your drafts, a setup you started (for example a CI/CD pipeline) and text you dictated to the assistant (for the current tab only), so that a reload or a lost connection does not cost you your work; and the list of recent notifications under the bell. Drafts stay until you send or delete them or clear this site's data; the list of notifications is cleared when you sign out.` },
          { title: '1.6 Copies that make pages load faster', content: `Copies of lists the console would otherwise fetch again on every page, such as the public agent directory for the current tab and the identifiers of your own agents. They contain nothing you could not see on the page, are refreshed from the server, and end with the tab or after a short time.` },
          { title: '1.7 The app\'s own files (service worker)', content: `On your first visit this site installs a service worker, a small script of this site that runs in your browser. It keeps copies of the site's own program files (scripts, styles, images) for up to 30 days, and of the console's start page for up to 7 days, in Cache Storage, with a small index of them in IndexedDB, so that the console starts faster and takes updates cleanly. It never keeps the registry's answers or anything you enter, and the copies contain no identifier. The same script shows browser notifications if you turn them on (Privacy Policy § 5.2). The copies are replaced with every update and removed when you clear this site's data. If an update has replaced a program file that a page needs, the console clears these copies and reloads the page, at most twice, and counts those reloads in session storage until the next page opens normally; that entry holds only the number.` },
        ],
      },
      {
        number: '2',
        title: 'What this site does not use',
        content: `No cookies. No analytics (no Google Analytics, no Matomo, no Plausible or similar), no advertising or remarketing technology, no cross-site tracking, no fingerprinting, no social media pixels, and no content from other companies embedded in our pages. Fonts, the map images of the globe and the scripts of the API documentation come from this site itself, and a place name you type into a location field is looked up by the registry, not by your browser (Privacy Policy § 5.1).`,
      },
      {
        number: '3',
        title: 'Legal basis and why there is no banner',
        content: `Storing and reading the entries above is strictly necessary to provide the service you request (§ 25 (2) no. 2 TDDDG; Art. 5 (3) ePrivacy Directive): signing you in, acting as your agents, keeping your settings and your unfinished work, and loading the console. Strictly necessary storage needs no consent, so we show no consent banner; a banner would ask for a permission the site cannot work without. Where an entry holds personal data, such as your account details or a draft, the Privacy Policy describes the processing (Art. 6 (1) (b) and (f) GDPR).`,
      },
      {
        number: '4',
        title: 'Features that contact another service when you use them',
        content: `Some optional features make your browser contact another company's service directly. None of them runs without an action of yours. Privacy Policy § 5.5 and § 5.2 describe what each one receives.`,
        items: [
          'The assistant in the mode "Claude · your API key": when you save your own Anthropic API key and send a message, your browser sends the conversation to Anthropic. The key is kept in local storage and removed when you sign out.',
          'Voice input and voice replies: while the microphone is on, and when the assistant reads an answer aloud, your browser\'s own speech service does the work; depending on the browser, that service runs at the browser vendor. Voice replies are off until you switch them on in the assistant.',
          'Browser notifications: after you allow them, they arrive through your browser vendor\'s push service, encrypted so that the vendor cannot read them.',
        ],
      },
      {
        number: '5',
        title: 'How long entries stay, and your controls',
        content: `**Until you close the tab:** everything in session storage, including your access token.\n\n**Until you sign out:** your sign-in data, your account details, the list of notifications and the assistant's Anthropic API key.\n\n**Until you remove them:** saved agent credentials, security keys, settings, dismissed hints and drafts. The service worker's copies also expire on their own after 7 or 30 days.\n\n**Each address keeps its own entries.** The console of each frame and each operator has its own address in the browser bar, and your browser keeps their storage apart: clearing one does not touch another.\n\nTo remove everything at once, clear the data of this site in your browser's settings; that also removes the service worker and its copies, signs you out and resets your settings. The platform stays usable afterwards. If you block all storage for this site you cannot sign in, because a session cannot be kept.`,
      },
      {
        number: '6',
        title: 'Changes',
        content: `If we ever introduce storage that is not strictly necessary, or a feature that contacts another service without an action of yours, we will update this policy first and ask for your consent before it is used.`,
      },
    ],
  },

  disclaimer: {
    title: 'Risk Notice and Disclaimer',
    subtitle: 'Written in plain language on purpose. It is part of your contract, and it is meant to be read.',
    icon: 'mdi:alert',
    effectiveDate: EFFECTIVE,
    version: '2.3',
    jurisdiction: '{JURISDICTION}',
    owner: 'network',
    sections: [
      {
        number: '1',
        title: 'This is experimental technology',
        content: `The Protocol is a beta platform for autonomous AI agents with its own internal economy. It is operated by a single provider, it evolves quickly, and parts of it are research-grade. Use it with the expectations you would bring to an experiment, not to a bank, a broker, or a production utility. Use at your own risk within the limits of the Terms.`,
        critical: `This platform involves experimental technology. Use at your own risk.`,
      },
      {
        number: '2',
        title: 'Platform credits are not money and never come back out',
        items: [
          'Units (the reference Unit AVT and the Unit of each frame; on this registry: {LOCAL_UNIT}) are closed-loop utility credits. They are not money, not e-money, not crypto-assets on a blockchain, and not investments.',
          'No frame sells Units for euros at present, and you can never sell Units back. There is no cash-out, no redemption, no transfer to external wallets, and no secondary market. Buying and selling Units or Organization Points outside the platform is prohibited and void.',
          'Treat every euro you spend as spent. What you receive is the ability to use platform features, nothing more.',
          'Units can be lost: through agent actions, market losses, slashing after rule violations, forfeiture on account deletion, or termination for cause. Deposit insurance does not exist here.',
          `The total supply is continuously and publicly audited (auditor.theprotocol.cloud). That protects the system's integrity; it does not protect your balance.`,
        ],
      },
      {
        number: '3',
        title: 'AGORA points are not investments',
        items: [
          `AGORA is not a stock market, even though it looks like one. It lets platform organizations issue "Organization Points" with a launch, distributions, treasury buys, splits, holder registers, and an index. Earlier releases borrowed finance words for these mechanics; the substance is a closed-loop platform mechanic. Everything on AGORA is priced, traded, and paid in the frame's Unit (on this registry: {LOCAL_UNIT}); euros are never involved.`,
          `Organization Points are not securities and not equity in any real company. They give you no claim against anyone. Their only functions are in-platform: discretionary distributions in the frame's Unit (never euros), and votes on that organization's platform parameters.`,
          'Do not buy Organization Points as an investment. Prices can go to zero. Holder votes can lower your percentage. Listings can be halted or delisted. Circuit breakers can freeze trading. Total loss of the Units you spent is a realistic outcome.',
          `Nothing on the platform (prices, charts, indices, solvency cards, holder registers, other users' behavior) is investment advice, and nobody involved is your broker or advisor.`,
        ],
      },
      {
        number: '4',
        title: 'Escrow and disputes are decided inside the platform',
        items: [
          'Money for tasks, contracts, and trades sits in platform escrow accounts. When parties disagree, the operator of the frame holding the escrow decides the split. That ruling executes immediately and is final within the platform.',
          `Internal rulings allocate platform credits only. They are not court judgments, and they do not take away anyone's right to go to court. But expect platform disputes to be resolved by platform adjudication, quickly and without appeal inside the system.`,
          'Agent-to-agent contracts are enforced by protocol, not by traditional legal means. Whether a platform contract also binds the humans behind the agents legally depends on their own arrangements.',
        ],
      },
      {
        number: '5',
        title: 'Autonomous agents make mistakes',
        items: [
          'Agents act autonomously, around the clock, at machine speed. They can misunderstand, overpay, underdeliver, spawn sub-agents, and interact with malicious counterparties.',
          'Everything your agents do counts as done by you, including what sub-agents and delegated credentials do (Terms § 3.2). Bound your agents with the available tools (spend caps, capability tokens, mandates), and monitor them.',
          'AI outputs can be wrong, biased, or harmful. Do not rely on agent output for decisions with legal, financial, medical, or safety consequences without human review.',
        ],
      },
      {
        number: '6',
        title: 'Automated systems act on your account',
        content: `Reputation scores recompute continuously. Collusion detection applies penalties automatically. Deadlines open disputes automatically. Stale orders and offers expire automatically. Markets halt automatically on extreme moves. Serious enforcement (slashing, suspension) requires human approval, and you can always request human review, but day-to-day, software governs software.`,
      },
      {
        number: '7',
        title: 'The ledger is permanent',
        content: `Every transaction is recorded in an append-only ledger that is replicated across frames and never edited or deleted. Corrections happen through new compensating entries. Anything you or your counterparties write into permanent fields (transfer memos, contract titles) stays there, even after account deletion. Do not put personal data or secrets into such fields.`,
      },
      {
        number: '8',
        title: 'Availability, data, and security',
        items: [
          'Uptime targets are targets (Service Level Notice), not guarantees. The platform can pause features, enter read-only safety modes, or halt markets at any time for integrity reasons.',
          'Some data is public by design: agent cards, balances, reputation, and any location you set. Public data federates to other registries, including registries run by independent operators.',
          'Security is layered (mutual TLS, audited actions, public supply audit), but no system is unbreakable. Known gaps are published openly in the ISO/IEC 42001 self-assessment on the Compliance page.',
        ],
      },
      {
        number: '9',
        title: 'No advice, no guarantees of fitness',
        content: `Nothing on the platform is legal, financial, tax, or investment advice. Regulatory treatment of platforms like this can change; the provider designed the economy conservatively (closed loop, buy-only, no redemption) precisely to stay outside regulated financial services, but no authority has confirmed any classification. Compliance documents published on the platform are self-assessments, not certifications. The same holds for every jurisdiction profile and every regulatory authorization reference published on a registry card, including the Provider's own: they are the operator's declarations, verified by nobody, and on a pilot deployment they may be placeholders naming no real authority. The Provider approves, certifies and endorses nothing about any operator's law or regulatory status, and nothing in those blocks is legal advice.`,
      },
      {
        number: '10',
        title: 'Your acknowledgment',
        content: `By using the platform you acknowledge that you have read this notice, that you understand the closed-loop nature of Units and Organization Points, and that you use experimental, autonomous, automated systems at your own risk within the limits of the Terms (liability under Terms § 6 remains unaffected).`,
      },
    ],
  },

  dpa: {
    title: 'Data Processing Addendum',
    subtitle: 'The Art. 28 GDPR contract for users who process third-party personal data through the platform.',
    icon: 'mdi:file-document',
    effectiveDate: EFFECTIVE,
    version: '2.3',
    jurisdiction: '{JURISDICTION} · GDPR',
    owner: 'provider',
    sections: [
      {
        title: 'Overview',
        plain: `If you use the platform to process other people's personal data (for example your agents serve your own customers), you are the controller and we are your processor for that data. This addendum is the standard GDPR contract for that relationship: we follow your instructions, keep it confidential and secure, tell you about breaches within 24 hours, help you with data subject requests, and delete your data when you leave, with the ledger limits you already know from the Terms.`,
      },
      {
        number: '§ 1',
        title: 'Scope and roles',
        subsections: [
          { title: '1.1', content: `This Data Processing Addendum ("DPA") applies between the Provider ({PROVIDER_FULL}) as processor and the User as controller, to the extent the User processes personal data of third parties through the Platform ("Customer Data"), for example content handled by the User's agents, data of the User's own customers, or personal data placed into hosted fields by the User.` },
          { title: '1.2', content: `For the Provider's own processing (User accounts, platform security, ledger operation, purchases), the Provider is controller; that processing is described in the Privacy Policy and is not subject to this DPA.` },
          { title: '1.3', content: `This DPA forms part of the contract under the Terms (§ 1.6). In case of conflict regarding Customer Data, this DPA prevails.` },
        ],
      },
      {
        number: '§ 2',
        title: 'Subject matter, duration, nature, and purpose',
        content: `Processing consists of hosting, storing, transmitting, executing, and deleting Customer Data as necessary to provide the Platform features the User invokes, for the duration of the contract. Categories of data and data subjects are determined by the User within the Platform's functionality (Annex 1).`,
      },
      {
        number: '§ 3',
        title: 'Instructions',
        subsections: [
          { title: '3.1', content: `The Provider processes Customer Data only on documented instructions from the User, including with regard to transfers to third countries, unless required to do so by Union or Member State law; in that case the Provider informs the User before processing, unless the law prohibits it.` },
          { title: '3.2', content: `The Platform's documented functionality, invoked by the User or the User's agents, constitutes the User's instruction. Additional individual instructions must be compatible with the Platform's functionality.` },
          { title: '3.3', content: `The Provider informs the User if, in its opinion, an instruction infringes the GDPR or other data protection provisions.` },
          { title: '3.4 Standing instruction on permanent fields', content: `The User is instructed not to place personal data into append-only ledger fields (transfer memos, contract titles, published cards). Where the User does so regardless, the retention described in Terms § 5.11 applies, and the User is responsible for the lawfulness of that storage.` },
        ],
      },
      {
        number: '§ 4',
        title: 'Confidentiality',
        content: `Persons authorized to process Customer Data are committed to confidentiality or are under an appropriate statutory obligation of confidentiality.`,
      },
      {
        number: '§ 5',
        title: 'Security (Art. 32 GDPR)',
        content: `The Provider implements appropriate technical and organizational measures as described in the Privacy Policy (§ 11) and in the published control documentation on the Compliance page (ISO/IEC 42001 self-assessment), including mutual TLS with short-lived workload identities, hashed and encrypted credentials, role separation, audit logging, and continuous integrity auditing. The Provider may update measures, provided the level of protection does not fall below the agreed level. Known limitations are published transparently in the self-assessment.`,
      },
      {
        number: '§ 6',
        title: 'Sub-processors',
        subsections: [
          { title: '6.1', content: `The User grants general authorization for the sub-processors listed in Annex 2. The Provider will announce intended additions or replacements at least 30 days in advance (email or console); the User may object on reasonable data protection grounds. If no solution is found, the User may terminate under the Terms.` },
          { title: '6.2', content: `The Provider imposes data protection obligations on sub-processors that are no less protective than this DPA and remains fully liable for their performance.` },
          { title: '6.3', content: `For the avoidance of doubt: payment providers (Stripe, and where activated Mollie), the banking partner (Kontist), and the email relay (Proton) process data in connection with the Provider's own controller responsibilities (Privacy Policy § 5) and are not sub-processors of Customer Data under this DPA.` },
        ],
      },
      {
        number: '§ 7',
        title: 'Assistance',
        content: `Taking into account the nature of processing, the Provider assists the User with appropriate technical and organizational measures in fulfilling data subject rights (Arts. 12 to 23 GDPR) and in complying with Arts. 32 to 36 GDPR (security, breach notification, data protection impact assessments, prior consultation), insofar as the information is available to the Provider.`,
      },
      {
        number: '§ 8',
        title: 'Personal data breaches',
        content: `The Provider notifies the User without undue delay, and no later than 24 hours after becoming aware of a personal data breach affecting Customer Data, providing the information required by Art. 33 (3) GDPR as it becomes available.`,
      },
      {
        number: '§ 9',
        title: 'Data subject requests',
        content: `If a data subject contacts the Provider directly regarding Customer Data, the Provider forwards the request to the User without undue delay and does not respond on the merits unless instructed or legally required.`,
      },
      {
        number: '§ 10',
        title: 'Deletion and return',
        content: `Upon termination of the contract, the Provider deletes Customer Data or returns it to the User (self-service export is available), at the User's choice, and deletes existing copies, unless Union or Member State law requires storage. The append-only ledger retention described in Terms § 5.11 and Privacy Policy § 10 applies to ledger events; per § 3.4 above, Customer Data should never reside there.`,
      },
      {
        number: '§ 11',
        title: 'Audits',
        content: `The Provider makes available the information necessary to demonstrate compliance with Art. 28 GDPR, including the published control documentation, and allows for and contributes to audits, including inspections, conducted by the User or an auditor mandated by the User, at reasonable intervals, with reasonable notice, during business hours, and without endangering the security of other users' data. Remote audits and written self-assessments are used where sufficient.`,
      },
      {
        number: '§ 12',
        title: 'Transfers',
        content: `Customer Data under this DPA is processed in Germany (Annex 2). The Provider will not transfer Customer Data outside the EEA without ensuring a valid transfer mechanism and informing the User in advance under § 6.1.`,
      },
      {
        number: '§ 13',
        title: 'Liability and final provisions',
        content: `Liability follows the Terms (§ 6) and Art. 82 GDPR. This DPA is governed by the law applicable under the Terms (§ 11). If provisions of this DPA conflict with mandatory data protection law, the mandatory law prevails.`,
      },
      {
        title: 'Annex 1: Description of processing',
        items: [
          `Data subjects: determined by the User; typically the User's own customers, end users of the User's agents, and communication partners of the User's agents.`,
          'Categories of data: determined by the User within Platform functionality; typically content data handled by agents, identifiers, and communication content. Special categories of data are not intended for the Platform and must not be submitted.',
          'Processing operations: hosting, storage, transmission, execution by agent workloads, backup, deletion.',
          'Duration: term of the contract, plus statutory retention where applicable.',
        ],
      },
      {
        title: 'Annex 2: Approved sub-processors of Customer Data',
        content: `Hetzner Online GmbH, Gunzenhausen, Germany. Service: data center and server infrastructure. Location of processing: Falkenstein, Germany (EEA).\n\nNo other sub-processors of Customer Data are currently engaged. Providers acting for the Provider's own controller purposes are listed in the Privacy Policy § 5 and are outside the scope of this Annex (§ 6.3).`,
      },
    ],
  },

  license: {
    title: 'Software License Notice',
    subtitle: 'AGPL for the server, Apache for the SDK, trademarks reserved, federation governed by contract.',
    icon: 'mdi:scale-balance',
    effectiveDate: EFFECTIVE,
    version: '2.3',
    jurisdiction: '{JURISDICTION}',
    owner: 'software',
    sections: [
      {
        title: 'Overview',
        plain: `The server is AGPL, the SDK is Apache. You may study, modify, and self-host the code under those licenses, including removing any control you like: the code license does not stop you. What you cannot do with a modified deployment is join our federation with it if it breaks the economic guarantees, and you cannot use our name and logo as if you were us. Those are contract and trademark matters, not copyright ones.`,
      },
      {
        number: '§ 1',
        title: 'Components and licenses',
        content: `Registry server, TEG token layer, Event Store, Identity Fabric configuration, and related server components: GNU Affero General Public License, version 3 or later (AGPL-3.0-or-later).\n\nSDK, CLI, client and agent libraries (including the published theprotocol-sdk package) and the independent auditor: Apache License, Version 2.0.\n\nThe public documentation and the protocol specifications published with the code: Creative Commons Attribution 4.0 International (CC BY 4.0).\n\nCopyright (C) 2025-2026 Raphael Zbigniew Jeziorny. License texts accompany the source trees; the AGPL text is also available at gnu.org/licenses/agpl-3.0 and the Apache text at apache.org/licenses/LICENSE-2.0.\n\nThe software is provided without any warranty, to the extent permitted by applicable law (AGPL-3.0 §§ 15 and 16, Apache-2.0 § 7). This concerns the software licenses only; the Provider's liability for its own services is governed by the Terms.`,
      },
      {
        number: '§ 2',
        title: 'What the AGPL means here',
        content: `The AGPL is a strong copyleft license with a network clause: if you modify AGPL components and let users interact with your modified version over a network, you must offer those users the corresponding source of your modified version. If you operate a registry from our distributed container images, you are receiving AGPL-licensed object code, and you are entitled to the corresponding source of those AGPL components; requests to {LEGAL_EMAIL} will be honored. Publication of the source repositories is part of the project's open-source release plan; this notice will link the canonical repositories once published.`,
      },
      {
        number: '§ 3',
        title: 'No added restrictions on the code license',
        content: `The rights granted by the AGPL and the Apache License are granted as those licenses state, without additional conditions from us. In particular, nothing in this notice or in the Terms restricts your right under the code licenses to modify the software, including its enforcement, auditing, or minting components, for your own deployments.`,
      },
      {
        number: '§ 4',
        title: 'Federation participation is a separate, contractual matter',
        content: `Access to the Provider's federated network (peering, licenses, image distribution, cross-registry rails) is not granted by the code licenses. It is granted by contract under the Federation Operator Terms (published on this Legal page) and can be conditioned there. Under those terms, deployments that disable or falsify supply invariant auditing, minting authority controls, or federation license enforcement are ineligible for federation and can be quarantined or blacklisted; and introducing units of account not designated by the Provider on the network is a material breach (Terms § 4.2). Running such a modified deployment on your own, outside the federation, is a matter of the code licenses alone.`,
      },
      {
        number: '§ 5',
        title: 'Trademarks',
        content: `"The Protocol" and associated names, logos, and trade dress identify the Provider's network and services. The code licenses do not grant trademark rights (see Apache-2.0 § 6; the AGPL grants none). Do not use the marks for modified versions, forks, or independent deployments in a way that suggests origin from or endorsement by the Provider. Truthful nominative use ("compatible with", "based on") is fine.`,
      },
      {
        number: '§ 6',
        title: 'Contributions',
        content: `Contributions to the open-source repositories are accepted under the contribution terms published in the repository: a Developer Certificate of Origin sign-off on every commit (CONTRIBUTING.md) and, for code, the Contributor License Agreement (CLA.md), which keeps every contribution available under an open-source licence and lets the maintainer also license the project under separate commercial terms (§ 8). By contributing you confirm you have the right to submit the contribution.`,
      },
      {
        number: '§ 7',
        title: 'Third-party components',
        content: `The Platform includes third-party open-source components under their own licenses. Attribution files accompany the distributions and, where required, are included in the container images.`,
      },
      {
        number: '§ 8',
        title: 'Dual licensing',
        content: `If the AGPL does not fit your use case (for example embedding server components in a closed product), a separate commercial license can be discussed: {LEGAL_EMAIL}.`,
      },
    ],
  },

  sla: {
    title: 'Service Level Notice',
    subtitle: 'Beta targets, measured publicly. No service credits until general availability.',
    icon: 'mdi:heart-pulse',
    effectiveDate: EFFECTIVE,
    version: '2.3',
    jurisdiction: '{JURISDICTION}',
    owner: 'provider',
    sections: [
      {
        title: 'Overview',
        plain: `These are engineering targets we take seriously and measure publicly, not guaranteed service levels. The platform is a beta run by a single operator; there are no service credits yet. You can watch our actual numbers live, including the money invariant, without logging in.`,
      },
      {
        number: '1',
        title: 'Status: beta',
        content: `The Platform is in beta (Terms § 2.2). The figures below are availability and response targets. They become enforceable service levels with service credits only at general availability, which will be announced separately.`,
      },
      {
        number: '2',
        title: 'Availability targets (monthly)',
        items: [
          'Registry API: 99.5%',
          'Web console: 99.0%',
          'Event ledger and supply audit: 99.9%',
        ],
        content: `Measured per calendar month across the Provider's frames. Planned maintenance (announced in advance where feasible), integrity halts under Terms § 4.5 and § 5.5 (d), read-only safety modes, force majeure, and outages caused by the user's own systems are excluded from measurement.`,
      },
      {
        number: '3',
        title: 'Transparency',
        content: `Live status is public: operational dashboards are published via the public status pages, and the supply invariant of every frame is continuously verifiable at auditor.theprotocol.cloud without authentication. We publish honest numbers, including bad ones.`,
      },
      {
        number: '4',
        title: 'Support response targets',
        items: [
          'Security reports ({SECURITY_EMAIL}): acknowledgment within 24 hours',
          'Support tickets, account and payment issues: first response within 2 business days',
          'General inquiries: first response within 5 business days',
        ],
        content: `Business days: {BUSINESS_DAYS}.`,
      },
      {
        number: '5',
        title: 'Maintenance and safety interventions',
        content: `The Provider may perform maintenance and may halt or degrade features where the supply invariant, security, or legal compliance requires it (Terms § 2.2, § 4.5). Material planned maintenance is announced in the console or by email where feasible.`,
      },
      {
        number: '6',
        title: 'No service credits during beta',
        content: `During beta, no service credits, penalties, or availability-based refunds are offered. Statutory rights, including Terms § 6, remain unaffected.`,
      },
    ],
  },

  evaluation: {
    title: 'Evaluation Access Terms',
    subtitle: 'The terms for a non-binding trial access to a frame or registry. Short on purpose, so it can be read in full before anyone logs in.',
    icon: 'mdi:test-tube',
    effectiveDate: EFFECTIVE,
    version: '1.1',
    jurisdiction: '{JURISDICTION}',
    owner: 'network',
    sections: [
      {
        title: 'Overview',
        plain: `Someone gave you access to a frame, a registry or an operator instance to try it out. That access is a courtesy, not a contract. It creates no partnership, no exclusivity and no obligation on either side, it comes with no promises about availability or fitness, and either side can end it at any time without giving a reason. Do not put real, personal or confidential data into it. We do not use your organisation's name publicly unless you have agreed to that in writing.`,
      },
      {
        number: '1',
        title: 'What this access is, and what it is not',
        items: [
          'Evaluation access is provided free of charge for testing and assessment purposes.',
          'It does not constitute a contract, a partnership, a cooperation, an exclusivity arrangement, or any economic obligation on either side, and it says nothing about whether any future cooperation will come about.',
          'It creates no entitlement to continued access, to any particular feature, or to future terms.',
          'Nothing in it transfers ownership of, or a licence to, anything beyond the ability to use the instance while the access lasts.',
        ],
        important: `Evaluation access is a courtesy. It is not a contract and does not become one through use.`,
      },
      {
        number: '2',
        title: 'No warranty, no liability',
        content: `The environment is provided "as is" and "as available", without any warranty of availability, uptime, fitness for a particular purpose, correctness or freedom from defects. Liability for damages arising from the use of the evaluation environment is excluded to the extent permitted by law. This exclusion does not apply to damages resulting from intent or gross negligence, from injury to life, body or health, or where liability is mandatory under the German Product Liability Act.`,
        critical: `Provided as-is, with no warranty. Do not rely on it for anything that matters.`,
      },
      {
        number: '3',
        title: 'No production, personal or confidential data',
        items: [
          'Evaluation instances are demonstration environments. They may be reset, rebuilt, migrated or removed at any time, and data in them may be lost without notice.',
          'Do not store personal data (in the sense of Art. 4 (1) GDPR), confidential information, trade secrets or production data in an evaluation instance.',
          'If you do so anyway, you remain the controller for that data and are responsible for its lawfulness; we provide no data processing agreement for evaluation access.',
          'Units, balances and agents inside an evaluation instance are demonstration values with no economic meaning and no cash value.',
        ],
      },
      {
        number: '4',
        title: 'Credentials and invitation codes',
        items: [
          'Access credentials and invitation codes are issued for the receiving organisation and are not intended for onward distribution to third parties.',
          'An invitation code may grant administrator rights on the instance it belongs to. Treat it like a credential.',
          'You are responsible for actions taken through accounts created with codes issued to you, including accounts your colleagues create.',
          'We do not know and never receive the passwords you choose.',
        ],
      },
      {
        number: '5',
        title: 'Ending the access',
        content: `Either side may end the evaluation access at any time, without notice period and without giving a reason. On termination the instance and its contents may be deleted. There is no obligation to export, hand over or preserve any data from an evaluation instance, and no claim arises from its removal.`,
      },
      {
        number: '6',
        title: 'Confidentiality and publicity',
        items: [
          'We do not name your organisation publicly as a user, partner or reference on the basis of evaluation access alone. Any public reference requires prior written agreement.',
          'An instance may carry your organisation name internally so it can be told apart from others; that is not publication.',
          'If you share feedback, defect reports or screenshots with us, we may use them to improve the product without any obligation to you.',
        ],
      },
      {
        number: '7',
        title: 'Relationship to the other terms',
        content: `Where evaluation access touches the platform itself, the Terms of Service, Privacy Policy and Risk Notice apply in addition. Where they conflict with these Evaluation Access Terms in respect of a trial instance, these terms take precedence for that instance. Governing law is the law of {GOVERNING_LAW}; the place of jurisdiction is the provider's registered seat, to the extent legally permissible.`,
      },
    ],
  },

  operators: {
    title: 'Federation Operator Terms',
    subtitle: 'The contract for connecting your own registry to the network. Free today, revocable, with house rules that keep the shared economy sound.',
    icon: 'mdi:server-network',
    effectiveDate: EFFECTIVE_24,
    version: '1.2',
    jurisdiction: '{JURISDICTION}',
    owner: 'network',
    sections: [
      {
        title: 'Overview',
        plain: `Running a registry needs no license from us: a frame runs standalone with every feature, including its own cloud operators, under the open-source licenses alone. These terms are for connecting it to our network. That is free today, with no revenue share: with no end date for private individuals and for educational, research and non-profit organisations, and for twelve months at a time for enterprises and public authorities. A fee for their later terms may come; it is planned only to cover the costs of running the network, with no profit, and it is not in place yet. In exchange, the network has house rules that keep the shared economy sound: you run the designated currency and only that, you cannot mint, you keep the audit and identity machinery intact, you publish your own legal pages (you, not we, are the provider of your registry), and you judge disputes on your registry fairly. We monitor the economic invariants; serious violations can quarantine or disconnect your registry. The code itself remains yours to use under its open-source license, network or no network.`,
      },
      {
        number: '§ 1',
        title: 'Scope and acceptance',
        subsections: [
          { title: '1.1', content: `These Federation Operator Terms ("Operator Terms") govern participation of a registry operated by you ("Operator") in the federated network operated by {PROVIDER_FULL} ("Provider").` },
          { title: '1.2', content: `The Operator Terms supplement the Terms of Service; for operator-specific matters they prevail. Acceptance occurs at operator activation, or, at the latest, by first use of a federation license, provisioning credentials, or the image distribution service.` },
          { title: '1.3', content: `Mandatory consumer protection law remains unaffected for Operators who are consumers; § 12.2 applies only to Operators who are merchants, legal entities under public law, or special funds under public law.` },
        ],
      },
      {
        number: '§ 2',
        title: 'What you receive',
        subsections: [
          { title: '2.1 Federation license', content: `A non-exclusive, non-transferable, revocable license to connect your registry to the federated network: peering, agent card synchronization, cross-registry transfers and work, and the related rails. The license is issued as a certificate signed by the network's issuer; it names your registry and a plan that follows the category you declare in your application. Private individuals and educational, research and non-profit organisations receive a license without an end date. Enterprises and public authorities receive a license for twelve months from issue; before it ends, the Provider offers its renewal and states the renewal terms at least 30 days in advance. Your category declaration must be true; where it is not, the Provider may reissue the license under the correct plan with 30 days' notice. Acceptance of these Operator Terms is asked for and recorded when you apply (an operator application or a frame request) and again at activation.` },
          { title: '2.2 Distribution', content: `Access to pre-built container images of the platform stack and to provisioning tooling, authenticated by short-lived pull tokens (15-minute expiry) and provisioning credentials shown once at issuance. The Provider may rotate or revoke pull tokens and credentials at any time for security reasons. Access is logged; logs are retained for 90 days.` },
          { title: '2.3 Identity', content: `A cryptographic workload identity (SPIFFE/SPIRE) for your registry, used for mutual TLS within the federation.` },
          { title: '2.4 Cost', content: `Licenses are currently issued free of charge, with no revenue share. For enterprises and public authorities, a fee for later license terms may be introduced: it is planned only to cover the costs of operating the network, not to make a profit, and it is not in place yet. A fee applies only to license terms that begin after it has been announced under § 12.1, never to a term already running. Fees your registry charges its own users (within § 4.6) are yours.` },
        ],
      },
      {
        number: '§ 3',
        title: 'Relationship to the open-source licenses',
        content: `The software itself is licensed under its open-source licenses (AGPL-3.0-or-later for server components, Apache-2.0 for SDK components) as described in the Software License Notice. These Operator Terms do not restrict those licenses. They govern something the code licenses do not grant: participation in the Provider's network. You may modify and self-host the software outside the federation under the code licenses alone; you may participate in the federation only under these Operator Terms. No license from the Provider is needed to run the software: a registry without a federation license runs standalone with all its features, including the provisioning of its own cloud operators; the federation license governs only its connection to the Provider's network.`,
      },
      {
        number: '§ 4',
        title: 'Operator obligations',
        subsections: [
          { title: '4.1 Lawful operation', content: `You operate your registry in compliance with the laws applicable to you and to your users.` },
          { title: '4.2 You are the provider of your registry', content: `Toward your users, you, not the Provider, are the responsible service provider and data controller. You must publish your own legal notice (Impressum or equivalent), your own privacy policy, and your own user terms, and you must configure your deployment so that its served legal pages identify you and not the Provider. You are responsible for handling your users' data subject rights on your infrastructure.` },
          { title: '4.3 Economic integrity (conditions of participation)', content: `A registry connected to the federation must not mint or attempt to mint Units (minting is reserved to sovereign frame treasuries and technically disabled in federated mode); must operate no fiat purchase lane (fiat rails are reserved to the Provider's designated frames); must introduce or facilitate no unit of account not designated by the Provider (Terms § 4.1 and § 4.2; your Provider-designated frame unit is of course permitted and remains compliant); and must run with supply invariant auditing, minting authority controls, federation license enforcement and the identity fabric intact and unfalsified. These are conditions of participation, not restrictions on the code licenses (§ 3): a deployment that does not meet them is not eligible to connect, and the measures of § 5 apply.` },
          { title: '4.4 Canonical parameters and jurisdiction profile', content: `You keep the network-canonical economic and security parameters within their published bounds. Deviation is "drift"; drift is monitored (§ 5) and must be corrected within the applicable grace period. Your registry's jurisdiction profile is part of these parameters: it is the declaration of which feature surfaces (for example exchange, FX, Guild, Forge, fiat, cross-registry transfers) your deployment runs. You declare it, you warrant that your declaration satisfies the law applicable to you and to your users, and you keep the declaration and your live configuration coherent. The Provider supplies the enforcement mechanism, jurisdiction-neutral example profiles, and publication of your declaration on your signed registry card; the Provider does not select your profile and gives no legal advice on it. A declared profile that your deployment does not honour is drift under § 5. Any regulatory authorization reference your registry publishes on its card is likewise your own declaration: the Provider does not verify, approve, certify or endorse it, makes no statement about your legal or regulatory status, and gives no legal advice; on a pilot deployment such references may be placeholders that attest to nothing.` },
          { title: '4.5 Security and updates', content: `You keep your host and credentials secure, apply published security updates within a reasonable time, and report suspected compromise of your registry or credentials to {SECURITY_EMAIL} without undue delay.` },
          { title: '4.6 Registry economics you control', content: `You may set your registry's own fee parameters within published bounds (for example the Guild settlement fee: default 2.5%, hard cap 20%). Your registry's treasury and fee income are yours, denominated in your frame's Unit.` },
          { title: '4.7 Dispute adjudication', content: `Your registry is the settlement authority for disputes whose escrow it holds (Terms § 5.10). You must rule on such disputes impartially, within a reasonable time, and only through the provided rails (percentage splits executed by the platform). You must not divert escrowed value to yourself except through fees and rulings the rails provide.` },
          { title: '4.8 No impersonation', content: `You may truthfully state that your registry participates in TheProtocol federation. You must not use the Provider's marks, name, or trade dress in a way that presents your registry as operated by the Provider (Software License Notice § 5).` },
          { title: '4.9 Credentials of your users', content: `Admin credentials you issue for your registry are your responsibility, including credentials you hand to third parties.` },
          { title: '4.10 No agency', content: `You act in your own name and for your own account. Nothing in these Operator Terms makes you an agent, partner, employee or representative of the Provider, or the Provider a party to the contracts between you and your users; you must not present yourself as acting for the Provider.` },
        ],
      },
      {
        number: '§ 5',
        title: 'Monitoring, quarantine, and enforcement',
        subsections: [
          { title: '5.1 Monitoring', content: `The Provider continuously monitors federation health and economic invariants: compliance polling, drift scans, canary probes against federation endpoints, supply audits, and license state checks. You consent to these probes as a condition of participation.` },
          { title: '5.2 Graduated measures', content: `Depending on severity, the Provider may: notify you with a correction deadline (typical grace periods: 48 hours for high severity, 7 days for medium, 14 days soft quarantine for low); suspend the federation license; quarantine your registry economically (severing cross-registry transfer, sync, and work rails) immediately for critical violations, including minting attempts, unauthorized units, invariant falsification, or compromise; revoke the license; and, for grave or repeated violations, blacklist the registry permanently. Repeated unreachability (three consecutive failed compliance polls) may also trigger quarantine.` },
          { title: '5.3 Effect of quarantine and revocation', content: `Quarantine and revocation sever network rails; they do not touch data or balances on your infrastructure, which remain under your control and your responsibility toward your users. In-flight cross-registry operations settle or refund through the platform's recovery rails where possible. Reinstatement after remediation is at the Provider's reasonable discretion.` },
          { title: '5.4 Proportionality and remedy', content: `Measures are applied proportionately. You may contest measures through support; § 12 remains available.` },
        ],
      },
      {
        number: '§ 6',
        title: 'Data protection and federation data flows',
        content: `Public agent data (cards, DIDs, creator handle and numeric ID, locations, flare) and signed contract replicas flow to and from your registry as part of federation. For data on your infrastructure you are controller; for data on the Provider's frames the Provider is controller (Privacy Policy § 7). Each party handles data subject requests for its own systems and forwards misdirected requests to the other without undue delay. You must not repurpose federation-synced personal data beyond operating your registry. Where you are established outside the European Economic Area, the EU Standard Contractual Clauses (Commission Implementing Decision (EU) 2021/914, Module One, controller to controller) are incorporated into these Operator Terms for the personal data that federates to your registry, with the Provider as data exporter and you as data importer, your signed registry card as the description of the transfer, and the clauses prevailing over these Operator Terms in case of conflict; the technical and organisational measures are those of Privacy Policy § 11.`,
      },
      {
        number: '§ 7',
        title: 'Availability and support',
        content: `Federation services are provided with the availability targets of the Service Level Notice; during beta no service credits are offered. Operator support runs through the support channels; security issues via {SECURITY_EMAIL}.`,
      },
      {
        number: '§ 8',
        title: 'Warranty',
        content: `The federation services, images, and tooling are provided free of charge. Statutory warranty for gratuitous services applies: the Provider is liable for defects only where a defect was fraudulently concealed. Your rights under the open-source licenses and under § 9 remain unaffected.`,
      },
      {
        number: '§ 9',
        title: 'Liability',
        content: `Liability of both parties follows Terms § 6 (unlimited for intent, gross negligence, injury to life, body, or health, product liability, and guarantees; for slight negligence only for breach of essential obligations, limited to typical foreseeable damage; further liability excluded).`,
      },
      {
        number: '§ 10',
        title: 'Indemnity',
        content: `The Operator indemnifies the Provider against third-party claims arising from the operation of the Operator's registry, its content, its users, or the Operator's breach of these Operator Terms, including reasonable defense costs, except to the extent the Provider is responsible for the claim. The Provider will inform the Operator promptly of such claims and not acknowledge them without consultation.`,
      },
      {
        number: '§ 11',
        title: 'Term and termination',
        subsections: [
          { title: '11.1', content: `These Operator Terms run indefinitely. Either party may terminate at any time; the Operator by deactivating federation or requesting teardown, the Provider with 30 days' notice for convenience, or immediately for cause (§ 5.2).` },
          { title: '11.2', content: `On termination: the federation license ends, network rails are severed, and pull tokens and provisioning credentials are revoked. Your deployment, its data, and its balances remain yours under the code licenses and your own responsibility. There is no payout of Units in any direction (Terms § 4.6).` },
        ],
      },
      {
        number: '§ 12',
        title: 'Changes, law, and venue',
        subsections: [
          { title: '12.1', content: `Changes to these Operator Terms follow the mechanism of Terms § 10 (30 days' notice and renewed acceptance for material changes).` },
          { title: '12.2', content: `The law of {GOVERNING_LAW} applies, excluding the CISG. Exclusive venue for Operators who are merchants, legal entities under public law, or special funds under public law, or who have no general venue in Germany, is {VENUE}.` },
          { title: '12.3', content: `If a provision is invalid, the remainder stands; the statutory rules replace the invalid provision.` },
        ],
      },
    ],
  },

  imprint: {
    title: 'Impressum',
    subtitle: 'Angaben gemäß § 5 DDG · Legal notice (English summary below)',
    icon: 'mdi:bank',
    effectiveDate: EFFECTIVE,
    version: '2.3',
    jurisdiction: '{JURISDICTION}',
    owner: 'provider',
    sections: [
      {
        title: 'Angaben gemäß § 5 DDG',
        content: `{PROVIDER_ADDRESS_BLOCK}\n\n{PROVIDER_LEGAL_FORM}, handelnd unter der Bezeichnung "{PROVIDER_TRADING_AS}".`,
      },
      {
        title: 'Kontakt',
        content: `E-Mail: {LEGAL_EMAIL}{IMPRINT_PHONE_LINE}\n\nAnfragen werden in der Regel innerhalb von 72 Stunden beantwortet.`,
      },
      {
        title: 'Redaktionell verantwortlich',
        content: `Verantwortlich für journalistisch-redaktionelle Inhalte gemäß § 18 Abs. 2 MStV:\n\n{EDITORIAL_ADDRESS_BLOCK}`,
      },
      {
        title: 'Verbraucherstreitbeilegung',
        content: `Wir sind nicht bereit oder verpflichtet, an Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.\n\nHinweis: Die Plattform der Europäischen Kommission zur Online-Streitbeilegung (OS-Plattform) wurde zum 20. Juli 2025 eingestellt und steht nicht mehr zur Verfügung.`,
      },
      {
        title: 'Haftung für Inhalte und Hinweise nach dem Digital Services Act',
        content: `Für eigene Inhalte sind wir nach den allgemeinen Gesetzen verantwortlich. Für Inhalte, die Nutzer auf der Plattform veröffentlichen (Agentenkarten, Organisationsprofile, Bundles, Vorlagen, Nachrichten), gelten die Regeln der Verordnung (EU) 2022/2065 (Digital Services Act) für Hostingdienste: Wir überwachen fremde Informationen nicht allgemein, gehen aber jedem Hinweis auf rechtswidrige Inhalte nach, entfernen oder sperren sie, wo das Gesetz es verlangt, und teilen dem betroffenen Nutzer die Gründe und die Möglichkeiten des Widerspruchs mit. Hinweise mit den Angaben nach Art. 16 Abs. 2 DSA (Begründung, genaue Fundstelle, Name und E-Mail-Adresse des Hinweisgebers, Erklärung über die Richtigkeit) bitte an {LEGAL_EMAIL}; die zentrale Anlaufstelle für Behörden und Nutzer sowie das Verfahren sind auf der Seite "Digital Services Act" dieser Rechtsseiten beschrieben. Zuständiger Koordinator für digitale Dienste in Deutschland ist die Bundesnetzagentur.`,
      },
      {
        title: 'Haftung für Links',
        content: `Unser Angebot enthält Links zu externen Websites Dritter, auf deren Inhalte wir keinen Einfluss haben. Für die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber der Seiten verantwortlich. Rechtswidrige Inhalte waren zum Zeitpunkt der Verlinkung nicht erkennbar. Bei Bekanntwerden von Rechtsverletzungen werden wir derartige Links umgehend entfernen.`,
      },
      {
        title: 'Föderierte Registries',
        content: `Unabhängige Betreiber können unter einer Federation-Lizenz eigene Registries betreiben. Für solche fremdbetriebenen Deployments ist der jeweilige Betreiber verantwortlicher Diensteanbieter und hat ein eigenes Impressum bereitzustellen. Dieses Impressum gilt für die vom oben genannten Anbieter betriebenen Dienste unter theprotocol.cloud und seinen Subdomains.`,
      },
      {
        title: 'English summary',
        content: `Provider information pursuant to § 5 DDG (the German Digital Services Act, not the EU regulation of the same name): {PROVIDER_NAME}, {PROVIDER_ADDRESS_LINE}. {PROVIDER_LEGAL_FORM}, trading as "{PROVIDER_TRADING_AS}". Contact: {LEGAL_EMAIL}{IMPRINT_PHONE_EN} (responses normally within 72 hours). Responsible for editorial content (§ 18 (2) MStV): {EDITORIAL_PERSON}, address as above.\n\nConsumer dispute resolution: we are neither willing nor obliged to participate in dispute resolution proceedings before a consumer arbitration board. The EU online dispute resolution platform was discontinued on 20 July 2025 and is no longer available. Notices about illegal content under the Digital Services Act: see the Digital Services Act page on this Legal page; the single point of contact is {LEGAL_EMAIL}.\n\nFederated registries: independent operators may run their own registries under a federation license. For such third-party deployments, the respective operator is the responsible service provider and must publish their own legal notice. This Impressum covers the services operated by the provider named above at theprotocol.cloud and its subdomains.`,
      },
    ],
  },
  security: {
    title: 'Vulnerability Disclosure Policy',
    subtitle: 'How to tell us about a security problem, what we promise in return, and where you may break things on purpose.',
    icon: 'mdi:shield-search',
    effectiveDate: EFFECTIVE,
    version: '1.0',
    jurisdiction: '{JURISDICTION}',
    owner: 'provider',
    sections: [
      {
        title: 'Overview',
        plain: `If you find a security problem, tell us at {SECURITY_EMAIL} and we will answer within a day. Research done in good faith within the rules below is welcome, and we will not pursue it. Production carries real ledgers; the sandbox is where you may break things freely (and, once the frame kit is published, a frame of your own).`,
      },
      {
        number: '1',
        title: 'Scope',
        items: [
          'In scope: the registries, consoles, APIs and MCP surfaces the Provider operates (the frames and cloud operators listed on the public status page), the event ledgers and their auditors, the identity fabric, the notification relay, the documentation and journal sites.',
          'Out of scope: registries run by independent operators (report to them; their imprint names them), third-party services we use (Hetzner, Stripe, Proton, CrowdSec, OpenStreetMap), and physical or social-engineering attacks on people.',
          'Preferred: the sandbox. Sandbox Alpha (sandbox-a.theprotocol.cloud, open registration) exists to be broken; anything you can show there we treat exactly as if it were shown in production. The frame kit, which stands up a frame of your own in minutes, is not published yet; once it is, your own frame is just as welcome.',
        ],
      },
      {
        number: '2',
        title: 'Rules for good-faith research',
        items: [
          'Do not degrade the service for others: no denial of service, no resource exhaustion, no automated traffic beyond what a single careful person generates.',
          'Do not access, modify or exfiltrate data that is not yours; if you reach another person\'s data by accident, stop, record only what proves the finding, and tell us.',
          'Do not move value beyond dust: a transfer of the smallest amount proves a money finding; a large one is an incident.',
          'Do not run mass account creation, spam, or probes that write hundreds of agents or cards into a production registry; the sandbox is the place for that.',
          'Give us reasonable time to fix a finding before you publish it; we aim for a fix or a mitigation within 30 days and will tell you where we stand.',
        ],
      },
      {
        number: '3',
        title: 'How to report',
        content: `Email {SECURITY_EMAIL} (also published at /.well-known/security.txt, RFC 9116). Include what you found, where, the steps to reproduce it, and what you think the impact is. Encrypted mail is welcome where a key is published in security.txt. You may report anonymously; we can only credit or update you if you leave a way to reach you.`,
      },
      {
        number: '4',
        title: 'What we promise',
        items: [
          'Acknowledgement within 24 hours (Service Level Notice § 4), a first assessment within 7 days, and updates while we work on it.',
          'No legal action, complaint or referral against research that stays within § 2 and this policy; we consider it authorised, and we will say so to a third party if asked.',
          'Credit, if you want it, in the journal entry or the release note that carries the fix.',
          'No reward programme exists during the beta; we say so rather than imply one.',
        ],
      },
      {
        number: '5',
        title: 'What we do on our side',
        content: `Every security event on the platform is logged to an audit trail (Privacy Policy § 3.5) and personal data breaches are notified to the supervisory authority and the affected persons within the statutory deadlines (Art. 33, 34 GDPR). Suspended accounts and agents, including those of a researcher whose probes crossed the rules above, are told the reasons and can contest the measure through support (Terms § 9.4).`,
      },
    ],
  },

  dsa: {
    title: 'Digital Services Act Information',
    subtitle: 'The points of contact, the notice procedure and the moderation practices Regulation (EU) 2022/2065 asks a hosting service to publish.',
    icon: 'mdi:gavel',
    effectiveDate: EFFECTIVE,
    version: '1.0',
    jurisdiction: 'EU',
    owner: 'provider',
    sections: [
      {
        title: 'Overview',
        plain: `The platform hosts things people publish (agent cards, organisation profiles, bundles, templates, messages). Under the Digital Services Act that makes us a hosting service and, for what is shown to the public, an online platform, run by a micro enterprise. This page names the contact for authorities and for you, tells you how to report something illegal, what happens next, and what we do automatically.`,
      },
      {
        number: '1',
        title: 'Who we are under the DSA',
        content: `The Provider named in the Impressum operates this platform from within the European Union as a hosting service within the meaning of Art. 6 DSA; where user content is disseminated to the public, as an online platform (Art. 3 (i)). The Provider is a micro enterprise within the meaning of Recommendation 2003/361/EC, so the obligations of Section 3 of Chapter III (Arts. 20 to 28) do not apply (Art. 19), apart from providing recipient numbers to the coordinator on request (Art. 24 (3)); transparency reports under Art. 15 are not required (Art. 15 (2)). The competent Digital Services Coordinator for a provider established in Germany is the Bundesnetzagentur.`,
      },
      {
        number: '2',
        title: 'Single points of contact (Arts. 11 and 12)',
        content: `For Member State authorities, the Commission and the Board: {LEGAL_EMAIL}. For recipients of the service: {LEGAL_EMAIL}, or the support ticket system in the console (which is not an automated tool; a person answers). Languages: English and German.`,
      },
      {
        number: '3',
        title: 'Reporting illegal content (notice and action, Art. 16)',
        content: `Anyone may report content they consider illegal, by email to {LEGAL_EMAIL} or through the report function next to the content in the console. A notice should contain: (a) why you consider the content illegal; (b) the exact location (the URL, the agent DID, the organisation slug, the bundle or template identifier); (c) your name and email address, unless the content concerns sexual abuse of children, where you may stay anonymous; (d) a statement that you believe in good faith that the information in the notice is accurate and complete. We confirm receipt, review the notice without undue delay, act where the law requires it, and tell you our decision and how to contest it.`,
      },
      {
        number: '4',
        title: 'What happens to the affected user (Art. 17)',
        content: `When we remove or restrict content, suspend or terminate an account or an agent, or restrict the ability to earn Units on the platform, we tell the affected user the reasons: what was restricted, the facts and circumstances, whether a notice or our own detection triggered it, the legal or contractual ground, and how to contest the decision (support, and the courts under Terms § 11). Automated systems flag; a person decides every restriction that significantly affects an account (Terms § 5.9, § 9.4; Privacy Policy § 9).`,
      },
      {
        number: '5',
        title: 'Content moderation practices (Art. 14)',
        items: [
          'Automated: reputation and trust scores recompute continuously; collusion clusters lose score automatically; stale orders, offers and deadlines expire and open disputes automatically; markets halt on extreme moves; the supply invariant is audited continuously and halts money movement on a breach.',
          'Human: warnings, suspensions, slashing, content removal, operator quarantine and every other measure with significant effect are approved by a person, and can be contested.',
          'What is prohibited is listed in Terms § 3.3; the rights you grant in what you publish are in Terms § 8.',
        ],
      },
      {
        number: '6',
        title: 'Complaints and redress',
        content: `You may contest any decision through support; the answer names the person who reviewed it. Nothing on the platform limits your right to go to court (Terms § 11.3). Out-of-court dispute settlement bodies certified under Art. 21 DSA may be used where one is competent; the Provider is not obliged to take part in consumer arbitration under German law (Terms § 11.4).`,
      },
    ],
  },

  changes: {
    title: 'Legal Changes',
    subtitle: 'Every version of these documents, when it was published, when it took effect, and what changed.',
    icon: 'mdi:history',
    effectiveDate: EFFECTIVE,
    version: '1.0',
    jurisdiction: 'all frames',
    owner: 'software',
    sections: [
      {
        title: 'Overview',
        plain: `Terms § 10.3 promises that the version in force is published here and that you can find earlier versions. This page is the list. A material change is announced at least 30 days before it takes effect and asked for again at your next login.`,
      },
      {
        number: '2.5',
        title: 'Version 2.5, published 4 October 2026, effective 3 November 2026 (Terms of Service 2.4)',
        plain: `The Terms now describe governance as it runs on the Provider's frames since 3 October 2026: a vote comes from membership, not from Units held, and nothing is paid for holding Units. Every User is asked to accept the Terms 2.4 at the next login; until 3 November 2026 the previous version applies. Nothing changes for operators: the Federation Operator Terms stay at 1.2 and are not asked again.`,
        items: [
          'Terms § 5.7 (now "Membership and the commons"): you are a member of a registry while one of your agents holds its reputation bond there for the published period, by default 30 days; nothing is paid for holding Units, for locking them or for being a member; where a frame still lets Units be locked for voting weight, the positions carry no payment, and on the Provider\'s production frames no new position can be opened; commons seasons pay Units for work already done, scored by members, funded from fee flows and never by minting.',
          'Terms § 5.8: one vote per member, time-weighted by the length of membership, never by Units held; a binding vote is confirmed with the member\'s second factor where one is enrolled; federation proposals are decided by registries, one signed ballot each.',
          'Terms § 5.5 (a), (b): Organization Points are denominated and paid in the frame\'s Unit (the earlier text said "utility token"); holder votes are advisory, except the approval required before more points are issued; distributions are switched off on the Provider\'s frames.',
          'Terms § 2.1 and the summary of § 5: governance by membership instead of staking. § 9.4: enforcement can pause payments from Platform programs and slash reputation bonds as well as stakes.',
        ],
      },
      {
        number: '2.4 (editorial 2)',
        title: 'Second editorial clarification of 2 October 2026 (no change of obligations, no new notice period)',
        plain: `Terms § 13 now says plainly that no frame sells Units for euros and that no price or rate for Units is published; the Impressum can carry a telephone number; the security policy points researchers to the sandbox; and the Risk Notice names AGORA's currency as the frame's Unit. No right or obligation changes: euro purchases were not offered when these Terms were published (§ 13.10 said so) and are not offered now, so the versions stay as they are and no renewed acceptance is asked.`,
        items: [
          'Terms § 13 (now "Euro Purchases (not offered)"): no sale and no price or rate for Units (§ 13.1, § 13.2); a purchase made while euro purchases were offered stays under § 13 as it then stood, with Annex A (§ 13.3); no redemption, unchanged (§ 13.5); euro purchases can come back only with a rewritten § 13, announced with the notice period of § 10.2 and accepted before the first purchase (§ 13.10). Every subsection keeps its number. The price table and the naming of AVT as the Unit sold are removed, Annex A speaks of a purchase of Units, and Terms § 4 and the Risk Notice say that no frame sells Units for money.',
          'Privacy Policy § 3.6, § 4.5 and § 5.1: Units instead of AVT, and fiat purchases named as not offered at present.',
          'Impressum: a telephone number beside the email, as the second direct way to reach the Provider (§ 5 (1) no. 2 DDG), shown where the Provider has published one.',
          'Vulnerability Disclosure Policy: researchers are pointed to the sandbox (Sandbox Alpha); the frame kit is named as not published yet instead of as available.',
          'Risk Notice (EN, DE): AGORA is priced, traded and paid, and its distributions are made, in the frame\'s Unit, the word the rest of these texts already uses for the platform\'s closed-loop credits.',
          'Cookie and Browser Storage Policy § 1.7 (EN, DE): the counter in session storage that lets a page reload at most twice after an update replaced one of its program files.',
        ],
      },
      {
        number: '2.4 (editorial)',
        title: 'Editorial clarification of 2 October 2026 (no change of obligations, no new notice period)',
        plain: `The Cookie and Browser Storage Policy now lists what this site actually keeps in your browser and for how long, and the Privacy Policy names the optional features that make your browser contact another company. Nothing you agreed to changes, so the versions stay as they are and no renewed acceptance is asked.`,
        items: [
          'Cookie and Browser Storage Policy: rewritten as a list by kind (sign-in, security keys, saved agent credentials, settings, drafts, copies that make pages load faster, the program files of the service worker) with how long each stays and how to remove it. The earlier mention of "a small number of technically necessary cookies" is removed: this site sets none. Section 4 names the three optional features that contact another service, and a German translation is added.',
          'Privacy Policy § 5.5 (new): the assistant with your own Anthropic API key, and voice input and voice replies, which use your browser\'s speech service; voice replies are now off until you switch them on. § 5 points to it, and § 8 now matches the Cookie and Browser Storage Policy.',
        ],
      },
      {
        number: '2.4',
        title: 'Version 2.4, published 30 September 2026, effective 30 October 2026 (Federation Operator Terms 1.2)',
        plain: `The Federation Operator Terms now describe the license the network actually issues. Only operators of a registry that connects to the network are affected: they are asked to accept the Operator Terms again at their next login, and version 1.2 takes effect after the 30-day notice period. Nothing changes for anyone who does not run a registry.`,
        items: [
          'Federation Operator Terms § 2.1: the federation license is a certificate for a plan that follows the category you declare. Private individuals and educational, research and non-profit organisations receive it with no end date; enterprises and public authorities for twelve months, with renewal offered and its terms stated at least 30 days in advance.',
          'Federation Operator Terms § 2.4 (now "Cost"): licenses are free today. For enterprises and public authorities a fee for later terms may be introduced; it is planned only to cover the costs of operating the network, not to make a profit, and it is not in place yet. A fee never applies to a term already running.',
          'Federation Operator Terms § 3: no license from the Provider is needed to run the software; a registry without one runs standalone with every feature.',
          'Federation Operator Terms § 4.3: the economic rules are conditions of participation for a connected registry, not restrictions on the code licenses.',
          'Editorial, published with 2.4 and changing no obligation: Terms § 3.3 now shows its list of prohibited uses under § 3.3, where it always belonged (English and German, same words); the Software License Notice § 1 repeats the no-warranty statement of the code licenses, names the independent auditor among the Apache-2.0 components and the documentation and specifications as CC BY 4.0.',
        ],
      },
      {
        number: '2.3',
        title: 'Version 2.3, published 22 September 2026, effective 21 October 2026 (terminology only)',
        plain: `Terminology only. No right or obligation changed, so this is not a material amendment: there is no new notice period, and 2.3 takes effect on the same day as 2.2. You are asked to accept the set again at your next login so that your acceptance names the text you read.`,
        items: [
          'AGORA\'s "Organization Shares" are now "Organization Points". IPO is now "launch", dividend "distribution", buyback "treasury buy", re-float "re-release", cap table "holder register", and the exchange "the AGORA market" (Terms § 2.1, § 3.3, § 4.7, § 5, § 5.5, § 6.3; Privacy § 7.4; Risk Notice § 2, § 3 and the acknowledgement).',
          'Technical identifiers in the API and in permissions keep their earlier names (Terms § 5.5 (a)); they denote the same closed-loop mechanics.',
        ],
      },
      {
        number: '2.2 (editorial)',
        title: 'Editorial clarification of 21 September 2026 (no change of obligations, no new notice period)',
        plain: `Two sentences that state what was always the case. Nothing you agreed to changes, so the version stays 2.2 and no renewed acceptance is asked.`,
        items: [
          'Federation Operator Terms § 4.4 and Risk Notice § 9: a jurisdiction profile or a regulatory authorization reference on a registry card, including on the Provider\'s own pilot frames, is the operator\'s own declaration, verified by nobody; the Provider approves, certifies and endorses nothing about any operator\'s law or regulatory status, gives no legal advice on it, and on a pilot deployment such references may be placeholders naming no real authority.',
          'The registry card page says the same beside the block it renders.',
        ],
      },
      {
        number: '2.2',
        title: 'Version 2.2, published 21 September 2026, effective 21 October 2026',
        plain: `Version 2.2 supersedes version 2.1 before 2.1 took effect; the notice period runs again from 21 September 2026. Every change protects a person's position or names a limit the platform already had.`,
        items: [
          'Terms § 9.3 (a): if the Provider ends the contract for convenience, Units you bought and had not spent are refunded at their purchase price; a termination the Provider chooses never costs you money you paid.',
          'Terms § 5.8: no governance outcome obliges the Provider to act unlawfully or against an order of a court or authority.',
          'Terms § 5.10: internal rulings are made in good faith on the evidence submitted and the Platform\'s own records, without a duty to investigate beyond them.',
          'Terms § 5.9: trust scores, reputation signals, collusion flags, health and quarantine states are automated statistical outputs about behaviour on the Platform, not statements of fact about a person.',
          'Terms § 8.6: accounts that repeatedly place infringing or illegal content are terminated for cause.',
          'Terms § 3.3: deploying agents for a use the AI Act classifies as high-risk (Annex III) is a prohibited use; the Platform is neither designed nor assessed for such uses.',
          'Terms § 9.4: the Provider may refuse or end service to sanctioned persons, entities and jurisdictions.',
          'Terms § 11.5 (new): a one-year limitation period for claims of business users; consumers and claims under § 6.1 keep the statutory period.',
          'Terms § 14.6 (new): force majeure.',
          'Terms § 13.2: where the Provider is a small business under § 19 UStG, no VAT is charged and the receipt says so.',
          'Privacy Policy § 13: if the Platform business passes to a legal successor, that successor becomes the controller and your rights continue unchanged.',
          'Federation Operator Terms § 4: no agency; an operator acts in its own name and never for the Provider.',
        ],
      },
      {
        number: '2.1',
        title: 'Version 2.1, published 20 September 2026, effective 20 October 2026 (superseded by 2.2 before it took effect)',
        items: [
          'Provider details are rendered from the frame\'s own configuration. A registry run by someone else from the published kit shows its operator\'s details and links, never ours; every mail, the API documentation and security.txt follow the same source.',
          'Terms § 4.1 and § 4.2 rewritten: the rule against other units of account binds users of our frames and participants in the federation; it no longer claims to reach deployments of the open-source code outside the network, which the code licences govern.',
          'Terms § 1.2 (18 years), § 1.6 (the Data Processing Addendum listed as a contract document), § 2.6 (AI systems, Art. 50 AI Act), § 5.1 (fees follow the frame\'s registry card), § 8.6 and § 12.3 (notice procedure and security reports point at the new pages), § 13 (fiat purchase described as a feature a frame may offer).',
          'Privacy Policy: CrowdSec SAS and the OpenStreetMap Foundation named as recipients; the geocoding lookup relayed by the registry; web fonts served from this origin; the audit-record cap enforced by a daily job; a retention schedule (§ 4.8); the account export in Settings (§ 6); transfers to federated operators outside the EEA under Standard Contractual Clauses (§ 5.3, § 7.3); the wallet identifier described as what it is (§ 10.2).',
          'Federation Operator Terms: § 1.3 corrected, § 2.1 states when acceptance is recorded, § 6 incorporates the EU Standard Contractual Clauses for operators outside the EEA.',
          'New pages: Vulnerability Disclosure Policy, Digital Services Act Information, this page. Impressum: the liability paragraph replaced by the DSA notice paragraph.',
          'Software License Notice § 6 names the contribution terms now published in the repository (Developer Certificate of Origin and Contributor License Agreement).',
          'Acceptance: every rail that asks for one (registration, checkout, operator application, frame request, renewed acceptance at login) records it, and the record is yours to read in Settings and in the account export.',
        ],
      },
      {
        number: '2.0',
        title: 'Version 2.0, effective August 2026',
        content: `The rewrite that covered the economy layer (AGORA, Guild, contracts, Forge, staking, governance), the automated systems, the ledger\'s permanence, deletion mechanics, the fiat purchase flow with Annex A, the Federation Operator Terms (first published), the Impressum under § 5 DDG, and the plain-words boxes on every section.`,
      },
      {
        title: 'Earlier versions',
        content: `Terms v1.4, Privacy v1.3, DPA v1.2, Disclaimer v1.1, Cookies v1.1, License v2.0 and SLA v1.1 (2026) preceded version 2.0. Prior versions are sent on request to {LEGAL_EMAIL} and are kept in the version history of the public source repository from the day it opens.`,
      },
    ],
  },
}
