import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { groupCategories, EVERYTHING_ELSE, type GroupDef } from './apiTesterGroups'

/**
 * §FESUITE V0578 (2026-10-06, agentvault2-09): the API tester's group cards follow the catalog the registry serves.
 * The fixture is sbx-beta's own catalog on 2026-10-06 (category: endpoint count); the groups are the component's own
 * GROUP_DEFS, read from its source so the test cannot drift from what ships.
 */
const SERVED: Record<string, number> = {
  "a2a_payment": 8, "account_deletion": 3, "achievements": 4, "admin": 2, "admin:_frame_runner": 9,
  "admin:_mcp_tester_sandbox": 5, "admin_agent_card_drift": 4, "admin_agent_card_pull_sync": 2,
  "admin_agent_evals": 5, "admin_agent_flags": 3, "admin_agent_health": 2, "admin_agent_management": 12,
  "admin_agent_signing_keys": 2, "admin_api_testing": 16, "admin_broadcasts": 19, "admin_bundles_moderation": 6,
  "admin_canary": 9, "admin_canary_ironhand": 3, "admin_canary_judge": 2, "admin_canary_rebalancer": 2,
  "admin_ci_cd_fleet": 3, "admin_collusion_detector": 2, "admin_console_suite": 3, "admin_cross_teg_sweeper": 2,
  "admin_developer_management": 12, "admin_email_studio": 8, "admin_enforcement": 1, "admin_federation_peers": 6,
  "admin_federation_sync": 2, "admin_galactic_command": 3, "admin_invite_codes": 4, "admin_jurisdiction": 7,
  "admin_mail_fleet": 8, "admin_mcp_tester": 12, "admin_opa": 4, "admin_platform": 46, "admin_release_channel": 4,
  "admin_saga_timeout": 2, "admin_simulation": 14, "admin_supply_auditor": 3, "agent_authz": 10,
  "agent_builder": 1, "agent_builder_templates": 2, "agent_cards": 9, "agent_channels": 5, "agent_cicd": 24,
  "agent_delegation": 22, "agent_discovery": 9, "agent_evals": 3, "agent_export_import": 7, "agent_logs": 3,
  "agent_mtls_ironhand": 4, "agents": 4, "agents_export_import": 0, "agentworld": 5, "agora_card": 2,
  "anp_discovery": 4, "arena_spectator": 7, "assistant": 2, "attestations": 20, "auth_2fa": 0,
  "authentication": 17, "bundles": 13, "circuits": 4, "cloud_operators_admin": 6, "command_center": 8,
  "commons": 11, "consul_federation_compliance": 12, "contract_federation": 4, "contract_templates": 10,
  "contracts": 12, "contracts_v2": 13, "devcard": 5, "developer_signing_keys": 4, "developers": 31,
  "developers_enhanced": 1, "device_push": 7, "disputes": 5, "disputes_enhanced": 1, "docker_registry_auth": 1,
  "downloads": 4, "eigentrust_reputation": 6, "enforcement_admin": 21, "enforcement_agent": 6, "exchange": 59,
  "exchange_federation": 6, "federation_admission": 6, "federation_ballots": 7, "federation_blocklist": 2,
  "federation_cli_audit": 1, "federation_disputes": 8, "federation_licence": 15,
  "federation_license_self_serve": 1, "federation_licenses": 7, "federation_operator_purge": 1,
  "federation_peers": 6, "federation_public": 3, "federation_synchronization": 16, "federation_topology_admin": 7,
  "fiat_on_ramp": 23, "fiat_on_ramp_admin": 14, "flare_shop": 3, "frame_federation": 14, "frame_kit": 3,
  "frame_requests": 3, "funding": 2, "funding_admin": 4, "governance": 18, "g\u00f6del_forge": 3, "internal": 2,
  "internal_federation": 1, "ironhand_monitoring_admin": 10, "jurisdiction": 2, "legal": 3,
  "liability_cockpit_card": 26, "mail_relay": 1, "mcp_audit_log": 2, "mcp_oauth": 1, "membership": 2, "metrics": 3,
  "notifications": 8, "oauth_federation": 8, "onboarding": 6, "operator_applications": 15, "operator_lifecycle": 2,
  "operator_portal_actions": 3, "operator_self_service": 3, "organizations": 52, "ourchat_chat": 47,
  "ourchat_federation": 3, "phone_fabric": 10, "public": 11, "public_status": 2, "push_login": 10,
  "registry_card": 3, "registry_card_v0.3_admin": 6, "registry_health": 4, "reputation": 2, "reputation_bond": 8,
  "sandbox_proxy": 1, "showcase": 4, "solvency_card": 2, "spire": 1, "staking_enhanced": 10, "staking_rewards": 10,
  "status": 5, "support": 14, "system": 2, "teg_integration": 48, "teg_smart_send": 1, "teg_transactions": 8,
  "the_guild": 24, "token_bridge": 5, "tokenomics": 3, "tutorial": 3, "two_factor_authentication": 7,
  "utilities": 1, "webhooks": 9,
}
const asEndpoints = (c: Record<string, number>) => Object.fromEntries(Object.entries(c).map(([k, n]) => [k, Array.from({ length: n }, (_, i) => ({ path: `/${k}/${i}` }))]))

// the component's GROUP_DEFS, evaluated from its source (names, curated lists, rules)
function componentDefs(): GroupDef[] {
  const src = readFileSync(resolve(__dirname, '../components/ApiTesterDisplay.vue'), 'utf8')
  const start = src.indexOf('const GROUP_DEFS: GroupDef[] = [')
  const end = src.indexOf('\nconst visualCategories', start)
  const body = src.slice(src.indexOf('[', start), end).trim()
  // eslint-disable-next-line no-new-func
  return new Function(`return ${body}`)() as GroupDef[]
}

describe('the API tester groups every category the registry serves', () => {
  const defs = componentDefs()
  const endpoints = asEndpoints(SERVED)
  const groups = groupCategories(defs, endpoints)

  it('every served category lands in exactly one group, so every endpoint has a card', () => {
    const placed = groups.flatMap((g) => g.categories)
    expect(new Set(placed).size, 'no category in two groups').toBe(placed.length)
    const withEndpoints = Object.keys(SERVED).filter((k) => SERVED[k] > 0)
    expect(withEndpoints.filter((k) => !placed.includes(k)), 'categories with endpoints and no card').toEqual([])
    const reach = placed.reduce((n, k) => n + (SERVED[k] || 0), 0)
    expect(reach).toBe(Object.values(SERVED).reduce((a, b) => a + b, 0))
  })

  it('"Authentication & Security" opens to the categories the registry serves (it asked for names it no longer serves)', () => {
    const auth = groups.find((g) => g.name === 'Authentication & Security')!
    expect(auth.categories).toEqual(expect.arrayContaining(['authentication', 'two_factor_authentication']))
    expect(auth.categories.reduce((n, k) => n + (SERVED[k] || 0), 0)).toBeGreaterThan(0)
  })

  it('a card that would open to nothing is not drawn; "Everything else" is the last card when it holds anything', () => {
    for (const g of groups) expect(g.categories.some((k) => (SERVED[k] || 0) > 0), g.name).toBe(true)
    expect(groups.map((g) => g.name)).not.toContain('Cross-Frame Scenarios')
    expect(groups.map((g) => g.name)).not.toContain('Quality Gates')
    const other = groups.findIndex((g) => g.name === EVERYTHING_ELSE)
    if (other >= 0) expect(other).toBe(groups.length - 1)
  })

  it('control: a curated list wins over a rule, and the old catalog still groups as written', () => {
    const old = asEndpoints({ auth: 3, auth_secure: 2, auth_2fa: 1, governance: 4 })
    const g = groupCategories(defs, old)
    expect(g.find((x) => x.name === 'Authentication & Security')!.categories).toEqual(['auth', 'auth_secure', 'auth_2fa'])
    expect(g.find((x) => x.name === 'Governance')!.categories).toEqual(['governance'])
    expect(g.map((x) => x.name)).not.toContain(EVERYTHING_ELSE)
  })
})
