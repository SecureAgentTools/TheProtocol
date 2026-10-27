"""0132 — COCKPIT CARD: liable hybrid identity (dev ∘ agent) for regulated work (L1, 2026-07-25).

A `liability_mandate` binds a HUMAN developer's standing authority to ONE agent for a declared
scope: the human carries the liability, the agent does the work. Authority is never snapshotted
into power — every consuming request re-derives
    effective = agent_own_rbac ∪ (delegated(dev) ∩ dev_authority_now ∩ mandate.scope)
                ∩ att_ caveats ∩ mandate.limits
(the same issuer-current clamp that makes IRONKEY L4 capability tokens safe). Revoke the human's
dev-RBAC flag, suspend the account, or bump token_version → every mandate leaning on it conveys
nothing on the NEXT request. `authority_snapshot` on mandate + evidence rows records what was
true at that instant — the question an auditor actually asks a year later.

`liability_evidence` is a per-mandate hash chain (chain_hash = sha256(prev_hash || digest),
UNIQUE(mandate_id, seq)) — issue/sign/consume/deny/revoke all append; tampering breaks recompute.

`liability_challenges` is the banking-app confirm rail: server renders canonical action facts,
phone approves by UNLOCKING A KEY THAT SIGNS challenge_hash (P-256 in Secure Enclave/StrongBox,
biometric-gated — pubkey enrolled on the EXISTING device_push_registrations row) or, until the
app key ships, TOTP. Single-use, 120s TTL, expiry is a denial. The achieved method is recorded,
never silently downgraded.

Deny-only + pre-escrow → Δ-irrelevant. Gated LIABILITY_MODE (off default; shadow frame-c).
IDEMPOTENT — replays every boot. Chains 0131.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0132_liability_mandates"
down_revision: str = "0131_contract_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS liability_mandates (
            id                  VARCHAR(44) PRIMARY KEY,          -- lm_<hex>
            developer_id        INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            agent_did           VARCHAR(255) NOT NULL,
            tier                VARCHAR(8)  NOT NULL DEFAULT 'T1',
            scope               JSONB       NOT NULL,             -- delegated perms ⊆ delegatable(dev flags) at issue
            limits              JSONB,                            -- {max_per_tx, currency, budget, ...} (clamp, not grant)
            status              VARCHAR(16) NOT NULL DEFAULT 'signed',  -- signed | revoked | expired
            presence_method     VARCHAR(16) NOT NULL,             -- totp | enclave (method achieved at issue)
            authority_snapshot  JSONB       NOT NULL,             -- dev flags + agent ceiling AT ISSUE (audit, never authority)
            content_hash        VARCHAR(64) NOT NULL,             -- sha256(canonical mandate payload)
            device_id           INTEGER,                          -- device_push_registrations.id used for presence
            registry_id         VARCHAR(120),
            issued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at          TIMESTAMPTZ,
            revoked_at          TIMESTAMPTZ,
            revoked_reason      VARCHAR(255)
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_liab_mandates_dev ON liability_mandates (developer_id, status)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_liab_mandates_agent ON liability_mandates (agent_did, status)"))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS liability_evidence (
            id                  BIGSERIAL PRIMARY KEY,
            mandate_id          VARCHAR(44) NOT NULL REFERENCES liability_mandates(id) ON DELETE CASCADE,
            seq                 INTEGER     NOT NULL,
            event_type          VARCHAR(32) NOT NULL,             -- issued|challenge_*|consumed|denied|revoked|expired|gate_pass|gate_block|shadow_flag
            action_ref          VARCHAR(128),                     -- ctr_… / tx id / endpoint ref
            payload             JSONB       NOT NULL,
            authority_snapshot  JSONB,                            -- flags+roles live AT THIS EVENT
            presence            JSONB,                            -- {method, device_id, challenge_id}
            digest              VARCHAR(64) NOT NULL,             -- sha256(canonical row payload)
            prev_hash           VARCHAR(64) NOT NULL DEFAULT '',
            chain_hash          VARCHAR(64) NOT NULL,             -- sha256(prev_hash || digest)
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_liab_evidence_seq UNIQUE (mandate_id, seq)
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_liab_evidence_mandate ON liability_evidence (mandate_id, seq)"))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS liability_challenges (
            id                  VARCHAR(44) PRIMARY KEY,          -- lch_<hex>
            mandate_id          VARCHAR(44) NOT NULL REFERENCES liability_mandates(id) ON DELETE CASCADE,
            developer_id        INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            action_type         VARCHAR(48) NOT NULL,
            action_ref          VARCHAR(128),
            facts               JSONB       NOT NULL,             -- canonical facts THE PHONE RENDERS (server-generated only)
            nonce               VARCHAR(32) NOT NULL,
            challenge_hash      VARCHAR(64) NOT NULL,             -- sha256(canonical(facts) || nonce) — what gets signed
            status              VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending|approved|denied|expired|consumed
            method              VARCHAR(16),                      -- totp | enclave (achieved at approval)
            device_id           INTEGER,
            signature           TEXT,                             -- ES256 raw sig (enclave path)
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at          TIMESTAMPTZ NOT NULL,
            resolved_at         TIMESTAMPTZ
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_liab_challenges_dev ON liability_challenges (developer_id, status)"))

    # Phone enclave key enrolment rides the EXISTING device row (no parallel device concept).
    for col, ddl in (
        ("pubkey_jwk",      "JSONB"),
        ("key_alg",         "VARCHAR(16)"),
        ("attestation",     "JSONB"),
        ("key_enrolled_at", "TIMESTAMPTZ"),
        ("key_revoked_at",  "TIMESTAMPTZ"),
    ):
        bind.execute(text(f"ALTER TABLE device_push_registrations ADD COLUMN IF NOT EXISTS {col} {ddl}"))


def downgrade() -> None:
    # Additive-only; never rolled down in prod (rollback doctrine: leave additive migs in place).
    pass
