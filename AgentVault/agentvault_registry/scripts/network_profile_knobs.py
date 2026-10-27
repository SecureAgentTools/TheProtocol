"""
THE KNOB TABLE — the single source of truth for §MONEY-M2's network profile.

Each row says, for one money knob:
  name          the env/profile key
  scope         which component reads it (registry | teg | provisioner | es | ops)
  reader        file:line where the value is consumed  (verified 2026-09-04)
  code_default  the literal in the code TODAY — the fallback if no profile is selected
  lowsupply     how the fresh network should size it, as an expression over S0 and GRANT,
                or None when the knob is not an amount (a flag, a mode, a role list)
  note          why the number is what it is

⚠ S0 AND GRANT ARE HIS DECISIONS (D1, D2) AND ARE NOT DEFAULTED ANYWHERE.
   `render_network_profile.py lowsupply` REFUSES without --s0 and --grant.
   Nothing in this table assumes a value for either.

The `reader` column is enforced: tests/test_network_profile_parity.py asserts every
name here is still read somewhere in the tree, so the profile cannot rot into a list
of names nothing consults.
"""

# ruff: noqa: E501

KNOBS = [
    # ---- R7 · the genesis grant -------------------------------------------------
    dict(name="GENESIS_GRANT_ENABLED", scope="registry",
         reader="routers/onboarding.py:905", code_default="true", lowsupply=None,
         note="master switch; the amount is inert while this is false (§COLDSTART2)"),
    dict(name="GENESIS_GRANT_AMOUNT", scope="registry",
         reader="config.py:307 · routers/onboarding.py:267,913", code_default="1000.0",
         lowsupply="GRANT",
         note="R7: frames 1000, operators 5000 (cloud_provisioner.py:387) — one number now"),
    dict(name="GENESIS_GRANT_TREASURY_FLOOR", scope="registry",
         reader="routers/onboarding.py::mint_genesis_grant", code_default="0",
         lowsupply="S0 * 20 / 100",
         note="R14 · NEW: below the floor a grant is deferred, not failed. 0 = disabled = today"),
    dict(name="TREASURY_LOW_NOTIFY_THRESHOLD", scope="registry",
         reader="background_tasks/treasury_low_watch.py::_threshold", code_default="0",
         lowsupply="S0 * 25 / 100",
         note="R43 · NEW: admins are told ONCE when the treasury crosses below this (hysteresis in redis) and once on recovery; ABOVE the 20 % genesis floor so the warning precedes deferred grants. 0 = disabled = today"),

    # ---- R8 · the operator treasury seed ----------------------------------------
    dict(name="OPERATOR_PROVISION_FUNDING_AVT", scope="provisioner",
         reader="routers/cloud_operators.py:308 · routers/operator_self_service.py:627",
         code_default="100000", lowsupply="S0 * 5 / 100",
         note="R8: four operators at the literal 100k is 4x a small supply"),

    # ---- R11 · liability presence ------------------------------------------------
    dict(name="LIABILITY_PRESENCE_THRESHOLD_AVT", scope="registry",
         reader="config.py:382 · services/liability.py:550 · routers/organizations.py:408",
         code_default="0.0", lowsupply="GRANT * 5 / 100",
         note="R11: 5 on frame-c only; presence step-up must scale with what money means"),

    # ---- R12 · prices, caps and ceilings -----------------------------------------
    dict(name="FUNDING_REQUEST_MAX_AVT", scope="registry",
         reader="routers/funding_requests.py:213", code_default="100000",
         lowsupply="GRANT * 10 / 100",
         note="R12: was a hardcoded Decimal(\"100000\") — a petition could dwarf every grant"),
    dict(name="TEG_TRANSFER_MAX_AVT", scope="registry",
         reader="routers/teg_integration.py:1185,1215,1358,1378,4186,7910,7931",
         code_default="10000000", lowsupply="S0 * 10 / 100",
         note="R12: seven hardcoded request ceilings; a cap above the supply is no cap"),
    dict(name="TEG_MINT_MAX_AVT", scope="registry",
         reader="routers/teg_integration.py:7961", code_default="100000000",
         lowsupply="S0",
         note="R12: the mint ceiling; never above the intended supply"),
    dict(name="STAKING_MIN_STAKE_AMOUNT", scope="registry",
         reader="routers/staking_enhanced.py:156", code_default="10.0",
         lowsupply="GRANT * 1 / 100",
         note="R12: carried a literal '# TODO: Move to config' since it was written"),
    dict(name="FLARE_SHOP_PRICES", scope="registry",
         reader="routers/flare_shop.py:97", code_default="", lowsupply=None,
         note="R12: JSON tier->price; empty = the source catalog. Rescale with the profile"),
    dict(name="EXCHANGE_LISTING_FEE", scope="registry",
         reader="services/exchange_service.py:102", code_default="1000",
         lowsupply="GRANT * 1 / 100",
         note="R12: a listing must be affordable to a person holding one grant"),
    dict(name="EXCHANGE_MAX_NOTIONAL", scope="registry",
         reader="services/exchange_service.py:104", code_default="1000000",
         lowsupply="S0 * 5 / 100", note="R12"),
    dict(name="EXCHANGE_REPAT_DUST", scope="registry",
         reader="services/exchange_service.py:280", code_default="0.5",
         lowsupply="GRANT / 100000",
         note="R12: the sweep threshold for gateway credits. Anchored to the GRANT, not S0: \"too small to be worth a transfer\" is a judgement about what a PERSON holds. At S0/1000000 it came to 1 unit, i.e. 0.1% of a whole grant swept as dust"),

    # ---- R13 · canaries are real money -------------------------------------------
    dict(name="CANARY_REBALANCER_FLOOR_AVT", scope="registry",
         reader="background_tasks/canary_rebalancer.py:100", code_default="5000",
         lowsupply="S0 / 1000",
         note="R13: below this a canary sender is refilled"),
    dict(name="CANARY_REBALANCER_TOPUP_AVT", scope="registry",
         reader="background_tasks/canary_rebalancer.py:101", code_default="1000000",
         lowsupply="S0 * 2 / 1000",
         note="R13: the refill target — 1,000,000 is the whole of a small supply"),
    dict(name="CANARY_PREFUND_AMOUNT", scope="registry",
         reader="models.py:4726 (canary_agents.prefund_amount default)", code_default="100000",
         lowsupply="S0 / 1000",
         note="R13: the column default a new canary agent is created with"),

    # ---- R27 · correction ceilings ------------------------------------------------
    dict(name="BALANCE_RECONCILE_AUTO_APPROVE_MAX", scope="registry",
         reader="background_tasks/balance_reconciliation_guard.py:131,259", code_default="10.0",
         lowsupply="GRANT / 1000",
         note="R27: how much drift the guard heals without a human. Anchored to the GRANT: at S0/100000 it healed 10 units unattended, 1% of a person's entire balance"),
    dict(name="ESCROW_RECONCILER_MAX_RELEASE_PER_AGENT", scope="teg",
         reader="core/escrow_lock_reconciler.py:66", code_default="100000",
         lowsupply="S0 / 1000",
         note="R27: the circuit breaker on the escrow-lock reconciler"),

    # ---- R29 · the showcase float --------------------------------------------------
    dict(name="SHOWCASE_VISITOR_FLOAT", scope="registry",
         reader="services/showcase_visitor.py:119", code_default="5000.0",
         lowsupply="S0 / 10000", note="R29"),
    dict(name="SHOWCASE_VISITOR_MAX_PER_TX", scope="registry",
         reader="services/showcase_visitor.py:134", code_default="5000.0",
         lowsupply="S0 / 10000", note="R29 (his 2026-08-26 instruction: per-tx == float)"),
    dict(name="SHOWCASE_VISITOR_MAX_PER_DAY", scope="registry",
         reader="services/showcase_visitor.py:135", code_default="10000.0",
         lowsupply="S0 * 2 / 10000", note="R29"),

    # ---- FX floors (D3: may not exist at all on a one-currency network) -------------
    dict(name="FX_RESERVE_FLOOR_AVT", scope="registry",
         reader="routers/teg_integration.py:727", code_default="0",
         lowsupply="S0 * 2 / 100", note="D3 — absent entirely if the fresh net runs one currency"),

    # ---- posture: not amounts, but the profile must state them ---------------------
    dict(name="BETA_INVITE_REQUIRED", scope="registry",
         reader="routers/auth_secure.py:78,256", code_default="false", lowsupply=None,
         note="D4: the only Sybil control that costs nothing new"),
    dict(name="AGENT_RBAC_DEFAULT_ROLES", scope="registry",
         reader="routers/onboarding.py (birth roles)", code_default="trader,client", lowsupply=None,
         note="R38: frame-c says trader,client,staker; everyone else takes the source default"),
    dict(name="GATEWAY_REARM_ABANDONED_BATCH", scope="registry",
         reader="background_tasks/gateway_float_keeper.py:167", code_default="0", lowsupply=None,
         note="R6/D7: 50 on the mainframes, unset on every operator"),
    dict(name="ENABLE_PROJECTION_SNAPSHOTS", scope="registry",
         reader="routers/admin_health.py:3321 · mcp/tools_admin.py:808", code_default="", lowsupply=None,
         note="R16: the snapshot re-bases transit_net. Runbook says NEVER; the profile leaves it unset. "
              "MEASURED 2026-09-04: =true on registry-a AND all 5 frame-a operators"),
    dict(name="FIAT_ONRAMP_ENABLED", scope="registry",
         reader="routers/fiat_onramp.py", code_default="false", lowsupply=None,
         note="R9: stays off until he says otherwise"),
    dict(name="TEG_MINT_REQUIRE_PROXY", scope="teg",
         reader="TEG endpoints_admin (mint gate)", code_default="true", lowsupply=None,
         note="the only mint path is the registry proxy on a mainframe (§MINTSECRET)"),
    dict(name="ENVIRONMENT", scope="teg",
         reader="TEG core/config.py + secure_config.validate_production_config()",
         code_default="development", lowsupply=None,
         note="R34: unset on the operator TEGs ⇒ /docs served and the production validator never runs"),
    # ---- §REPBOND · the reputation bond (2026-09-05, the Commander's final design) ----
    dict(name="REPUTATION_BOND_AMOUNT", scope="registry",
         reader="services/reputation_bond.py::bond_amount", code_default="50",
         lowsupply="GRANT * 25 / 100",
         note="the bond a provider holds in treasury escrow; a quarter of the grant leaves liquidity for staking and fees"),
    dict(name="REPUTATION_BOND_MODE", scope="registry",
         reader="services/reputation_bond.py::bond_mode", code_default="off", lowsupply=None,
         note="off | shadow | enforce. Current fleet: shadow (counts, refuses nothing). Fresh frame + sandbox: enforce"),
    dict(name="ENFORCEMENT_PROPAGATION_MODE", scope="registry",
         reader="services/enforcement_propagation.py::propagation_mode", code_default="shadow", lowsupply=None,
         note="off | shadow | enforce. §ENFPROP: a suspended/revoked agent's state rides its card to every mirror; enforce refuses it at the six bond sites. Fleet since V0223: enforce (his word 2026-09-05)"),
    dict(name="REPUTATION_BOND_TREASURY_BACKSTOP", scope="registry",
         reader="services/reputation_bond.py::treasury_backstop_enabled", code_default="false", lowsupply=None,
         note="the DEMONSTRATION path: the treasury underwrites a bond the flow could not fund. On for the fresh frame while the grant exists"),
    dict(name="REPUTATION_BOND_MIN_TRANSACTIONS", scope="registry",
         reader="services/reputation_bond.py::maturity_thresholds", code_default="10", lowsupply=None,
         note="maturity: satisfactory interactions either way. Recommended 5 on the fresh frame (federation floor 5)"),
    dict(name="REPUTATION_BOND_MIN_AGE_DAYS", scope="registry",
         reader="services/reputation_bond.py::maturity_thresholds", code_default="30", lowsupply=None,
         note="maturity: days since lock. Recommended 14 on the fresh frame (federation floor 7)"),
    # REPUTATION_BOND_MIN_EIGENTRUST (code default 0.1) is RETIRED (§BONDFILL-3, 2026-09-11). An absolute
    # threshold on a normalised EigenTrust vector could not be met, so maturity now asks for a RELATIVE
    # standing: the policy document's `enforcement.bond_maturity_min_trust_percentile` (bounded 50..95),
    # read by services/reputation_bond.py::maturity_thresholds. No process reads the env name, so
    # test_every_knob_is_read_somewhere failed on this row in every image from V0356 to V0365 (§OSSRC).
    dict(name="REPUTATION_BOND_RELEASE_COOLDOWN_DAYS", scope="registry",
         reader="services/reputation_bond.py::release_cooldown_days", code_default="7", lowsupply=None,
         note="a matured bond pays back after this many days; a treasury-backstopped bond pays nobody"),
    dict(name="ENFORCEMENT_SLASH_MODE", scope="registry",
         reader="services/reputation_bond.py::slash_mode · services/enforcement_engine.py::_slash_waterfall",
         code_default="cache", lowsupply=None,
         note="cache = today's cache-only write (R21) | shadow = plan + log | enforce = the policy's slash_waterfall MOVES money (bond → stake → liquid). Fresh frame: enforce; current fleet: shadow (HARD STOP 4)"),
]

BY_NAME = {k["name"]: k for k in KNOBS}
assert len(BY_NAME) == len(KNOBS), "duplicate knob name in the table"
