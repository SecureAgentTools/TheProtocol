"""NOTIFICATION CATALOG — the single declaration of everything the platform can notify about.

Why this exists (§NOTIFV2, 2026-07-26): before it, "what is notifiable" lived in a hardcoded
Python set inside push_notify.py (`DELEGATION_DEFAULT_EVENTS`). Adding a notification type
silently reached NOBODY until someone remembered to edit that literal — which is exactly how
`LiabilityChallenge` and `LoginApproval` each shipped dead on arrival. If adding a feature
requires editing an unrelated literal, and forgetting is silent, it will be forgotten.

Rules of this module:
  * Pure data + validation. No I/O, no imports from the rest of the app (push_notify and the
    resolver import US, never the reverse — keeps import order trivial).
  * `key` uses the WEBHOOK dotted vocabulary (services/webhook_service.py::SUPPORTED_EVENTS) so
    the platform keeps ONE event namespace. Where the trigger is an EventStore type (CamelCase),
    `es_event_types` records the aliases; device-level allowlists written by the phone app
    historically contain those CamelCase names, so preference matching accepts BOTH spellings.
  * Validated at import: a malformed catalog must fail a unit test / dev boot, never ship.
  * `mandatory=True` is a SECURITY BOUNDARY, not a UX default: the resolver short-circuits
    before any preference, mute, quiet-hour or coalescing logic. Muting a login approval locks
    you out; muting a liability challenge means missing the thing you are personally liable for.
  * DEFAULTS ARE DELIBERATELY QUIET (Commander directive 2026-07-26: "we don't want the defaults
    to be spammy or annoying"). Nothing bursty defaults to mobile. Anything that can arrive in
    volume carries a coalesce window. `money.received` stays strictly opt-in exactly as today.
  * `legacy_managed=True` marks types whose delivery still runs on the pre-v2 store
    (admin-broadcast mutes / CICD toggles). They appear in the catalog so the settings panel is
    ONE surface, but the v2 resolver never handles them and their toggles write the legacy keys.
    Deviation from the strategy doc recorded in the §NOTIFV2 session log.
  * `emitter=False` = declared but nothing fires it yet. The panel may show these greyed
    ("coming soon"); the fail-loud send path still accepts them so wiring an emitter later is
    one call, zero catalog churn.

Channels: inapp · email · push_desktop (rail webpush) · push_mobile (rails ntfy/fcm/apns).
v2 delivery in this build covers the two PUSH channels; inapp/email delivery for non-broadcast
types is P6 (a feed table + read-state). `default_enabled` already carries all four so the day
those rails exist is a resolver change, not a catalog migration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional, Tuple

from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event

CHANNELS: Tuple[str, ...] = ("inapp", "email", "push_desktop", "push_mobile")
PUSH_CHANNELS: Tuple[str, ...] = ("push_desktop", "push_mobile")
CATEGORIES: Tuple[str, ...] = (
    "security", "agents", "money", "contracts", "marketplace", "broadcast", "ops",
    "chat",   # §OURSTATE-1 (2026-08-24) — OurChat messages + pings
    # V0652 (af): the categories the gaps file found without a home (session-lead's NOTIFICATION_GAPS_2026-10-31.md:
    # "Governance (no category at all today)"), organizations' own events, and the terms
    "governance", "organizations", "legal",
)
SEVERITIES: Tuple[str, ...] = ("info", "warning", "critical")
AUDIENCES: Tuple[str, ...] = ("developer", "operator", "admin")


@dataclass(frozen=True)
class NotificationType:
    key: str
    category: str
    severity: str = "info"
    mandatory: bool = False
    audience: str = "developer"
    # channel -> enabled-by-default. Missing channel == False (quiet by default).
    default_enabled: Dict[str, bool] = field(default_factory=dict)
    threshold_kind: str = "none"          # none | amount
    threshold_default: Optional[float] = None
    coalesce_window_s: int = 0            # 0 = never coalesce
    es_event_types: Tuple[str, ...] = ()  # CamelCase EventStore aliases (device allowlist compat)
    label_key: str = ""                   # FE i18n; defaulted from key in __post_init__
    desc_key: Optional[str] = None
    legacy_managed: bool = False          # delivery still on the pre-v2 store (broadcast/CICD)
    emitter: bool = True                  # False = declared, nothing fires it yet ("coming soon")
    # V0652 (z): a DECISION someone waits on (an approval request) reaches them in quiet hours too; every other type
    # keeps the quiet hours (the maintainer's plan, item 5: "only decide events cross quiet hours")
    crosses_quiet_hours: bool = False
    # V0652 (z): never pushed, whatever a preference says: a room's traffic is read in the app ("push only what
    # needs you"); in-app (and email, where a type defaults to it) as the preferences say
    inapp_only: bool = False

    def __post_init__(self):
        if not self.label_key:
            object.__setattr__(
                self, "label_key",
                "notifCatalog." + self.key.replace(".", "_") + ".label",
            )


def _t(key: str, cat: str, sev: str = "info", **kw) -> NotificationType:
    return NotificationType(key=key, category=cat, severity=sev, **kw)


# ---------------------------------------------------------------------------
# THE CATALOG. Ordering here is the panel's display order within each category.
# ---------------------------------------------------------------------------
CATALOG: Tuple[NotificationType, ...] = (
    # ── security ──────────────────────────────────────────────────────────
    _t("security.login_approval", "security", "critical", mandatory=True,
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("LoginApproval",),
       desc_key="notifCatalog.security_login_approval.desc"),
    _t("security.liability_challenge", "security", "critical", mandatory=True,
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("LiabilityChallenge",),
       desc_key="notifCatalog.security_liability_challenge.desc"),
    _t("account.suspended", "security", "critical", mandatory=True,
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("DeveloperSuspended",)),
    _t("security.device_enrolled", "security", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True},
       desc_key="notifCatalog.security_device_enrolled.desc"),
    _t("security.2fa_changed", "security", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    # B3 (RBAC plan) — a spend over the agent's approval threshold parked and is waiting
    # on this human. Not mandatory (their queue, their prefs) but defaults to both pushes:
    # an unseen ask simply expires in 30 minutes, which is a deny.
    _t("security.spend_approval", "security", "warning",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}),
    _t("security.api_key_created", "security", "info",
       default_enabled={"push_desktop": True}),
    _t("account.reinstated", "security", "info",
       default_enabled={"push_desktop": True},
       es_event_types=("DeveloperReinstated",)),
    # 2026-07-27: the third account-lifecycle event. delete_developer sets is_suspended=True as a
    # side effect of soft-delete, and firing account.suspended there would have been a lie, so
    # this exists rather than leaving the path silent. NOT mandatory: unlike a lockout you cannot
    # act on this one, so it stays a preference. Soft-delete does not scrub device rows, so it can
    # still be delivered.
    _t("account.deleted", "security", "critical",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("DeveloperDeleted",)),
    # V0652 (af) — the account's own security events the gaps file found missing. A password change and a sign-in from
    # a device or place this account has not used are the two a person must hear about when it was not them; an API
    # key's expiry is said 14 days ahead, once per key. No email by default (the maintainer, the room seq 313).
    _t("security.password_changed", "security", "warning",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}, desc_key="notifCatalog.security_password_changed.desc"),
    _t("security.new_login", "security", "warning",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}, coalesce_window_s=600),
    _t("security.api_key_expiring", "security", "warning",
       default_enabled={"inapp": True, "push_desktop": True}, desc_key="notifCatalog.security_api_key_expiring.desc"),

    # ── agents ────────────────────────────────────────────────────────────
    _t("delegation.granted", "agents", "info",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("AgentDelegationGranted",)),
    _t("capability.revoked", "agents", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("AgentCapabilityRevoked",)),
    # Quiet on purpose: a spawn spree / bulk issuance buries everything that matters.
    _t("capability.issued", "agents", "info",
       default_enabled={}, coalesce_window_s=120,
       es_event_types=("AgentCapabilityIssued",)),
    _t("agent.spawned", "agents", "info",
       default_enabled={}, coalesce_window_s=300,
       es_event_types=("AgentSpawned",)),
    _t("delegation.breaker_tripped", "agents", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("AgentCapabilityCircuitBreakerTripped",)),
    _t("agent.suspended", "agents", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("AgentSuspended",), coalesce_window_s=300),
    _t("agent.reinstated", "agents", "info",
       default_enabled={"push_desktop": True},
       es_event_types=("AgentReinstated",), coalesce_window_s=300),
    _t("agent.slashed", "agents", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("AgentSlashed",)),
    _t("agent.health_changed", "agents", "warning",
       default_enabled={"push_desktop": True}, coalesce_window_s=600),
    _t("agent.mtls_revoked", "agents", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    # V0652 (af): an agent card this registry can no longer read (said once when its reads have failed three times in
    # a row, not on every failed read). Grouped: a host that went down for many agents is one bell. (The gaps file's
    # agent.mtls_expiring is not declared: an external agent's certificate lives 30 minutes by default and is renewed
    # by calling enable-mtls again, and nothing records its expiry, so there is no expiry to say ahead of.)
    _t("agent.card_unreachable", "agents", "warning",
       default_enabled={"inapp": True}, coalesce_window_s=3600),

    # ── money (strictly opt-in where it can be frequent) ──────────────────
    _t("money.received", "money", "info",
       default_enabled={},                       # exactly today's semantics: opt-in only
       threshold_kind="amount", threshold_default=100.0, coalesce_window_s=60,
       es_event_types=("TokensTransferred",),
       desc_key="notifCatalog.money_received.desc"),
    _t("staking.rewards", "money", "info",
       default_enabled={}, coalesce_window_s=3600,
       es_event_types=("RewardsDistributed",)),
    _t("funding.decided", "money", "info",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("fiat.purchase_completed", "money", "info",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("forge.royalty_received", "money", "info",
       default_enabled={"push_desktop": True},
       threshold_kind="amount", threshold_default=1.0, coalesce_window_s=600),
    # V0652 (af): an A2A payment authorized to your agent means work waits for it; an authorization nobody used is
    # released at its expiry, and the payer hears that its units are free again; a reputation bond released.
    _t("a2a.payment_authorized", "money", "info",
       default_enabled={"inapp": True, "push_desktop": True}, coalesce_window_s=60, desc_key="notifCatalog.a2a_payment_authorized.desc"),
    _t("a2a.payment_expired", "money", "info",
       default_enabled={"inapp": True}, coalesce_window_s=600),
    _t("bond.released", "money", "info",
       default_enabled={"inapp": True, "push_desktop": True}),

    # ── contracts (rare per-party and genuinely meaningful → mobile on) ───
    _t("contract.offered", "contracts", "info",
       default_enabled={"push_desktop": True, "push_mobile": True},
       desc_key="notifCatalog.contract_offered.desc"),
    _t("contract.agreed", "contracts", "info",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("contract.milestone_submitted", "contracts", "info",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("contract.milestone_released", "contracts", "info",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("contract.disputed", "contracts", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("contract.completed", "contracts", "info",
       default_enabled={"push_desktop": True}),
    _t("contract.cancelled", "contracts", "info",
       default_enabled={"push_desktop": True}),
    # V0652 (af): a contract's deadline is near (said once per contract and deadline)
    _t("contract.deadline_soon", "contracts", "warning",
       default_enabled={"inapp": True, "push_desktop": True}),
    # §VCSIGN-2: operator-side alarm — a contract referenced by a LIVE regulatory
    # authorization left the agreed state, so the public countersign no longer
    # verifies (the card drops its digest; the proof endpoint answers 409).
    _t("jurisdiction.countersign_broken", "contracts", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True, "inapp": True},
       desc_key="notifCatalog.jurisdiction_countersign_broken.desc"),

    # ── marketplace ───────────────────────────────────────────────────────
    _t("guild.awarded", "marketplace", "info",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("guild.verified_paid", "marketplace", "info",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("guild.bid_received", "marketplace", "info",
       default_enabled={"push_desktop": True}, coalesce_window_s=300),
    _t("guild.work_submitted", "marketplace", "info",
       default_enabled={"push_desktop": True}),
    # V0652 (af): an order you bid on or were awarded is cancelled (with its reason); your bid lost to another; an
    # awarded order's deadline is near (said once per order)
    _t("guild.order_cancelled", "marketplace", "info",
       default_enabled={"inapp": True, "push_desktop": True}),
    _t("guild.bid_declined", "marketplace", "info",
       default_enabled={"inapp": True}, coalesce_window_s=300),
    _t("guild.deadline_soon", "marketplace", "warning",
       default_enabled={"inapp": True, "push_desktop": True}),
    _t("dispute.filed_against_you", "marketplace", "warning",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("DisputeFiled",)),
    _t("dispute.resolved", "marketplace", "info",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("DisputeResolved",)),
    _t("exchange.order_filled", "marketplace", "info",
       default_enabled={}, coalesce_window_s=300),
    # §POCKETBRIDGE3 (D3-4): a Pocket price alert crossed its threshold. Inapp
    # is on so the bell mirrors the in-session banner; BOTH push channels
    # default OFF by the Commander's decision — the user opts in from the
    # notification matrix when they want alerts reaching a closed app.
    _t("exchange.price_alert", "marketplace", "warning",
       default_enabled={"inapp": True}, coalesce_window_s=60),
    _t("exchange.dividend_received", "marketplace", "info",
       default_enabled={}, threshold_kind="amount", threshold_default=1.0),
    _t("evals.completed", "marketplace", "info",
       default_enabled={"push_desktop": True}, coalesce_window_s=1800),
    _t("cicd.deploy_completed", "marketplace", "info",
       default_enabled={"inapp": True}),
    _t("cicd.deploy_failed", "marketplace", "warning",
       default_enabled={"inapp": True, "push_desktop": True}),

    # ── chat (§OURSTATE-1, 2026-08-24) ────────────────────────────────────
    # D3 (Commander-approved): mobile push defaults OFF with a one-tap opt-in
    # card in the first thread — never silent-on. inapp is the offline
    # fallback the WS-delivered session doesn't need; the coalesce window
    # keeps a burst of messages from machine-gunning the bell.
    # V0652 (z): a room's traffic is in-app only. What needs a person reaches their devices as its own type below
    # (an approval request they decide, a mention of them, a direct message, a stranger's first message to them);
    # the thread's opt-in card used to turn pushes on for ALL of a room's messages.
    _t("chat.message", "chat", "info",
       default_enabled={"inapp": True}, coalesce_window_s=60, inapp_only=True, desc_key="notifCatalog.chat_message.desc"),
    # Ping is the consent-shaped knock (law 6): coalesce-EXEMPT because one
    # deliberate nudge must arrive as itself, but preference-obedient — it
    # never overrides a mute and the send side hard rate-limits it.
    _t("chat.ping", "chat", "info",
       default_enabled={"inapp": True}),
    # V0651 (y2): an approval request in a room reaches the people who may DECIDE it on their devices, by default.
    # It rode chat.message, whose pushes are off until the thread's opt-in card is tapped, so a device with default
    # settings (the maintainer's two) received nothing (session-lead's check in the sessions' room, seq 340/341). A
    # decision someone waits on is the push a person must not miss, like a sign-in approval: on by default, still
    # theirs to turn off. Only deciders get this type; the room's other members keep the in-app chat.message.
    _t("chat.approval_requested", "chat", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}, crosses_quiet_hours=True, desc_key="notifCatalog.chat_approval_requested.desc"),
    # V0652 (z) — what needs you, pushed by default (his plan's item 5; the gaps file's chat table): a message that
    # names you (a mention, or @all), a message in a direct conversation, and a stranger's first message to you, which
    # waits in your Requests and had notified nobody (session-tester, the room seq 337-339). Coalesced: a burst is one
    # bell. They keep your quiet hours.
    _t("chat.mention", "chat", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}, coalesce_window_s=60),
    _t("chat.direct", "chat", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}, coalesce_window_s=60),
    _t("chat.request", "chat", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}),
    # V0652 (af) — the rest of today's chat features (the gaps file's chat table). A choice someone asks you to make is a
    # decision, like an approval request: it crosses quiet hours (its card arrives with the choice cards, (ab)). An
    # approval you gave, used: in-app, and pushed when the act it allowed was a production act. A session's status
    # line that expired (the session went quiet) and a finished progress line (a proof or a roll with its verdict):
    # in-app.
    # V0652 (ab): a choice asked of its deciders (chat_service.notice_type_for). emitter=False below until the live
    # progress cards ((aa)) post them, and until a status line's expiry is watched (the status board, (ac)): declared
    # now, so the settings already show them
    _t("chat.choice_requested", "chat", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}, crosses_quiet_hours=True,
       desc_key="notifCatalog.chat_choice_requested.desc"),
    _t("chat.approval_used", "chat", "info",
       default_enabled={"inapp": True}),
    _t("chat.approval_used_production", "chat", "warning",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}),
    _t("chat.progress_finished", "chat", "info",
       default_enabled={"inapp": True}, coalesce_window_s=60, emitter=False),
    _t("org.session_offline", "chat", "info",
       default_enabled={"inapp": True}, coalesce_window_s=600, emitter=False),
    # §CHATDESK C5 — org money moved (fund/remit/dividend/guild settlement to
    # the firm). One bell per RECEIPT, coalesced so a dividend run over many
    # members does not machine-gun anyone; the room card is the record.
    _t("org.work.receipt", "chat", "info",
       default_enabled={"inapp": True}, coalesce_window_s=60),
    # §OURSTATE-2: a support-ticket reply notifies the TICKET OWNER, nobody
    # else (it had ridden an untargeted AdminBroadcast + a WS broadcast to
    # every connected user — routers/support.py, fixed the same batch).
    _t("support.reply", "ops", "info",
       default_enabled={"inapp": True, "email": False}),
    # V0652 (ai): the desk is told durably — a new ticket, a requester's reply, a reopen — to every admin_support
    # holder (routers/support.py::_notify_desk). Its only signal had been a live cue to an open console, so a ticket
    # filed at night waited unseen. In-app and the desktop push by default, coalesced so a burst of replies is one bell.
    _t("support.desk", "ops", "info", audience="admin",
       default_enabled={"inapp": True, "push_desktop": True}, coalesce_window_s=60),

    # ── governance (V0652 (af): no category at all before) ────────────────
    # A vote you can cast; the same vote 24 h before it closes, only while you have not voted; its result. A commons
    # season opening, an award to your work, and the season's payment. Quiet: in-app and the desktop; the result and
    # a season's opening in-app only (they reach every member).
    _t("governance.proposal_opened", "governance", "info",
       default_enabled={"inapp": True, "push_desktop": True}, coalesce_window_s=300),
    _t("governance.vote_closing", "governance", "info",
       default_enabled={"inapp": True, "push_desktop": True}, desc_key="notifCatalog.governance_vote_closing.desc"),
    _t("governance.result", "governance", "info",
       default_enabled={"inapp": True}),
    _t("commons.season_opened", "governance", "info",
       default_enabled={"inapp": True}),
    _t("commons.award", "governance", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}),
    _t("commons.season_paid", "governance", "info",
       default_enabled={"inapp": True, "push_desktop": True}),

    # ── organizations (V0652 (af)) ────────────────────────────────────────
    # An invitation waits for you (pushed: it is yours to answer); the one you sent was accepted; a member joined or
    # left (the owner and admins, and the member who was removed).
    _t("org.invitation_received", "organizations", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}),
    _t("org.invitation_accepted", "organizations", "info",
       default_enabled={"inapp": True, "push_desktop": True}),
    _t("org.member_joined", "organizations", "info",
       default_enabled={"inapp": True}, coalesce_window_s=300),
    _t("org.member_left", "organizations", "info",
       default_enabled={"inapp": True, "push_desktop": True}),

    # ── legal (V0652 (af)) ─────────────────────────────────────────────────
    # The terms change: the version, the date it takes effect and the link (the legal set 2.5 takes effect 2026-11-03)
    _t("legal.terms_updated", "legal", "info",
       default_enabled={"inapp": True, "push_desktop": True}, desc_key="notifCatalog.legal_terms_updated.desc"),

    # ── broadcast (delivery stays on the pre-v2 store; panel unifies display) ──
    _t("broadcast.critical", "broadcast", "critical", mandatory=True,
       default_enabled={"inapp": True, "email": True}),
    _t("broadcast.warning", "broadcast", "warning",
       default_enabled={"inapp": True, "email": True}),
    _t("broadcast.info", "broadcast", "info",
       default_enabled={"inapp": True, "email": True}),
    _t("broadcast.maintenance", "broadcast", "info",
       default_enabled={"inapp": True, "email": True}),

    # ── ops (operator/admin audience; recipients resolution lands with their emitters) ──
    _t("federation.peer_deactivated", "ops", "warning", audience="operator",
       default_enabled={"push_desktop": True, "push_mobile": True},
       es_event_types=("PeerRegistryDeactivated",)),
    _t("federation.license_suspended", "ops", "critical", audience="operator",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("registry.quarantined", "ops", "critical", audience="operator",
       default_enabled={"push_desktop": True, "push_mobile": True}),
    _t("operator.provisioned", "ops", "info", audience="admin",
       default_enabled={"push_desktop": True}),
    # V0652 (af) — the frame admin's requests: a frame asks to federate (a decision, in no hurry: it keeps quiet hours),
    # an operator application arrived; and for the applicant, the decision on it. A webhook whose deliveries keep
    # failing is said before it is switched off (the developer who owns it).
    _t("federation.invitation_received", "ops", "warning", audience="admin",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}),
    _t("operator.application_received", "ops", "info", audience="admin",
       default_enabled={"inapp": True, "push_desktop": True}),
    _t("operator.application_decided", "ops", "info",
       default_enabled={"inapp": True, "push_desktop": True, "push_mobile": True}),
    _t("webhook.failing", "ops", "warning",
       default_enabled={"inapp": True, "push_desktop": True}, coalesce_window_s=3600, desc_key="notifCatalog.webhook_failing.desc"),
    # §MONEY-R43 (2026-09-04) — "the treasury is running low" reaches a person BEFORE it
    # reaches a caller (background_tasks/treasury_low_watch.py). Default ON for the admin
    # audience on both pushes because the whole point is that somebody hears; NOT mandatory,
    # so a person can still turn it down. Severity `warning`: what wakes the Commander is his
    # decision (§PAGEROUTE), and this file's route table is not it.
    _t("treasury.low", "ops", "warning", audience="admin",
       default_enabled={"push_desktop": True, "push_mobile": True},
       desc_key="notifCatalog.treasury_low.desc"),
    # The org half: owners + admins of an organization that SET `treasury_low_notify_threshold`
    # (ORG_SETTING_CATALOG). Audience `developer` because org admins are developers; the
    # recipient set is the org's own, resolved by the watcher, never everybody.
    _t("org.treasury.low", "money", "warning", audience="developer",
       default_enabled={"push_desktop": True, "push_mobile": True},
       desc_key="notifCatalog.org_treasury_low.desc"),
    # §RELEASECHANNEL (2026-09-21) — a stable release or a hotfix on the signed release channel reaches this
    # registry's admins ONCE per version (background_tasks/release_channel_checker.py), and the reminder when the
    # window they scheduled is due. Default ON for both pushes for the same reason as treasury.low: the point is that
    # somebody hears about a security release; not mandatory, a person may still turn it down.
    _t("release.update_available", "ops", "warning", audience="admin",
       default_enabled={"push_desktop": True, "push_mobile": True},
       desc_key="notifCatalog.release_update_available.desc"),
    _t("release.rollout_due", "ops", "info", audience="admin",
       default_enabled={"push_desktop": True, "push_mobile": True},
       desc_key="notifCatalog.release_rollout_due.desc"),
)


# ---------------------------------------------------------------------------
# Lookups + import-time validation (a malformed catalog must never boot in dev)
# ---------------------------------------------------------------------------
BY_KEY: Dict[str, NotificationType] = {}
BY_ES_TYPE: Dict[str, NotificationType] = {}
MANDATORY_KEYS: FrozenSet[str] = frozenset()


def _validate() -> None:
    global MANDATORY_KEYS
    seen_es: Dict[str, str] = {}
    for t in CATALOG:
        assert t.key and t.key.count(".") >= 1 and t.key == t.key.lower(), f"bad key {t.key!r}"
        assert t.key not in BY_KEY, f"duplicate key {t.key}"
        assert t.category in CATEGORIES, f"{t.key}: bad category {t.category}"
        assert t.severity in SEVERITIES, f"{t.key}: bad severity {t.severity}"
        assert t.audience in AUDIENCES, f"{t.key}: bad audience {t.audience}"
        assert set(t.default_enabled) <= set(CHANNELS), f"{t.key}: unknown channel"
        assert t.threshold_kind in ("none", "amount"), f"{t.key}: bad threshold_kind"
        if t.threshold_kind == "none":
            assert t.threshold_default is None, f"{t.key}: threshold_default without kind"
        assert t.coalesce_window_s >= 0, f"{t.key}: negative coalesce window"
        if t.inapp_only:
            assert not any(t.default_enabled.get(c) for c in PUSH_CHANNELS), f"{t.key}: in-app only, yet a push default"
        if t.crosses_quiet_hours:
            assert not t.mandatory, f"{t.key}: mandatory already crosses every rule"
        if t.mandatory:
            # A mandatory type must be deliverable somewhere by default, and severe.
            assert t.severity == "critical", f"{t.key}: mandatory but not critical"
            # 2026-07-27 (§9): this used to demand a default PUSH channel, with `legacy_managed`
            # as the escape hatch — because push was the only rail notify() could actually
            # deliver on, so "mandatory without push" meant "mandatory and undeliverable".
            # inapp and email are now real rails (mig 0139 + the themed sender), so the check
            # finally matches the sentence above it: deliverable SOMEWHERE. This is what lets
            # broadcast.critical (inapp+email, no push) leave legacy_managed without either
            # weakening the guarantee or forcing a phone buzz onto every critical announcement.
            assert any(
                t.default_enabled.get(c) for c in CHANNELS
            ), f"{t.key}: mandatory but no default delivery channel"
        for es in t.es_event_types:
            assert es not in seen_es, f"ES alias {es} claimed by both {seen_es[es]} and {t.key}"
            seen_es[es] = t.key
        BY_KEY[t.key] = t
        for es in t.es_event_types:
            BY_ES_TYPE[es] = t
    MANDATORY_KEYS = frozenset(t.key for t in CATALOG if t.mandatory)


_validate()


def get_type(key: str) -> Optional[NotificationType]:
    """Resolve a catalog key OR an EventStore alias. None = unregistered (fail-loud upstream)."""
    # W4: an EventStore alias read under its event's new name (UnitsTransferred) resolves as its old one
    return BY_KEY.get(key) or BY_ES_TYPE.get(key) or (BY_ES_TYPE.get(ledger_names.old_name(key)) if key else None)


def catalog_for_audience(is_operator: bool, is_admin: bool):
    """The panel's view: developer types always; operator/admin types per flags."""
    out = []
    for t in CATALOG:
        if t.audience == "developer":
            out.append(t)
        elif t.audience == "operator" and (is_operator or is_admin):
            out.append(t)
        elif t.audience == "admin" and is_admin:
            out.append(t)
    return out
