import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN, SANDBOX_ADMIN_LOGIN } from './sandboxLogin'

/**
 * Track 4: Federation — Exploring the bilateral mTLS federation network
 *
 * 11 steps:
 * AUTH (1-3): Tutorial JWT on A + Tutorial JWT on B + Sandbox Admin JWT on A
 * DISCOVERY (4-5): Federation info → Health check
 * FEDERATION SETUP (6-8): Register real mTLS peer (or confirm exists) → List active → Approve/confirm
 * NETWORK (9-11): Peer details → Network stats A → Network stats B (direct)
 *
 * DUAL-REGISTRY MODEL:
 * - Registry A (registry-test, port 8002) — default proxy target, most steps
 * - Registry B (registry-test-b, port 8003) — Steps 2, 11 use targetBase for direct calls
 *
 * CREDENTIAL MODEL:
 * - tutorial-admin@theprotocol.cloud — explorer account (JWT for viewing)
 * - admin@test.sandbox — federation owner (JWT for peer management ONLY)
 * Both passwords are the sandbox operator's (./sandboxLogin.ts); the bodies carry a placeholder.
 *
 * The sandbox federation uses REAL bilateral mTLS via SPIRE X.509 SVIDs.
 * This track explores and validates the existing federation. If federation
 * was destroyed, Steps 6-8 restore it. The register step accepts 400
 * (already exists) as a pass — idempotent by design.
 *
 * Variables: $sandboxDevToken, $sandboxDevTokenB, $sandboxAdminToken, $peerId
 *
 * NOTE: The sandbox mTLS federation between registry-test and registry-test-b
 * is persistent infrastructure managed by admin@test.sandbox. It cannot be
 * destroyed by this tutorial. If federation is in a broken state (INACTIVE),
 * run scripts/00setup_test_federation.py to restore it.
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login (form-encoded)
 * - federation_public.py: /federation/info, /federation/health-check, /federation/network-stats
 * - federation_peers.py: POST /federation/peers/, GET /federation/peers/, GET /federation/peers/{id}
 * - admin_federation.py: GET /admin/federation/peers/pending, POST /admin/federation/peers/{id}/approve
 */
export const federationTrack: TutorialTrack = {
  id: 'federation',
  title: 'Federation',
  subtitle: 'Exploring the bilateral mTLS federation network',
  description: 'Explore the real bilateral mTLS federation between two sovereign registries — discover federation identity, verify health, inspect active peers, and view the federated network from both sides.',
  icon: 'globe',
  color: 'blue',
  gradientFrom: 'from-blue-500',
  gradientTo: 'to-indigo-600',
  estimatedMinutes: 10,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Network Explorer',
  steps: [
    // ═══════════════════════════════════════════════════════
    // AUTH PHASE — Steps 1-3: Authenticate on both registries
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate (Registry A — tutorial account) ───
    {
      id: 'authenticate-a',
      stepNumber: 1,
      title: 'Authenticate (Registry A)',
      subtitle: 'Obtain a JWT from the primary registry',
      explanation: `Federation involves **two independent registries** — each with its own database, JWT secrets, and admin accounts.

We start by authenticating on **Registry A** (the default sandbox). This JWT will be used for exploration — viewing federation info, peers, and network stats.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with Registry A (registry-test)',
        body: {
          ...SANDBOX_TUTORIAL_LOGIN
        },
        authType: 'none'
      },
      captures: [
        {
          key: 'sandboxDevToken',
          responsePath: 'access_token',
          displayLabel: 'Registry A Developer JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      notes: 'This JWT is signed by Registry A. It cannot be used on Registry B: each registry accepts only the JWTs it signed itself.'
    },

    // ─── Step 2: Authenticate (Registry B — direct call) ───
    {
      id: 'authenticate-b',
      stepNumber: 2,
      title: 'Authenticate (Registry B)',
      subtitle: 'Obtain a JWT from the second registry',
      explanation: `Now we authenticate on **Registry B** — the second registry in our federation. This is a **direct API call** to \`Registry B (sandbox)\`, bypassing the tutorial proxy entirely.

Same credentials, different registry. Each registry issues its own JWT signed with its own secret. This JWT will be used to view Registry B's perspective of the federation.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with Registry B (registry-test-b) — direct call',
        body: {
          ...SANDBOX_TUTORIAL_LOGIN
        },
        authType: 'none',
        targetBase: '/sandbox-b',
        formEncoded: true
      },
      captures: [
        {
          key: 'sandboxDevTokenB',
          responsePath: 'access_token',
          displayLabel: 'Registry B Developer JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'authenticate-a',
      notes: 'Direct call to port 8003. The JWT returned here is only valid on Registry B.'
    },

    // ─── Step 3: Authenticate (Registry A — sandbox admin) ───
    {
      id: 'authenticate-sandbox-admin',
      stepNumber: 3,
      title: 'Authenticate (Sandbox Admin)',
      subtitle: 'Obtain the federation owner JWT for peer management',
      explanation: `The bilateral mTLS federation is owned by the **sandbox admin** account — \`admin@test.sandbox\`. This account registered and approved the real peer registries.

We authenticate as the sandbox admin to gain access to federation management endpoints. This JWT is used **only for Steps 6-8** (peer registration and approval). All other steps use the tutorial account.

In production, federation peer management is restricted to the registry operator — the person responsible for deciding which external registries to trust.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate as sandbox admin on Registry A',
        body: {
          ...SANDBOX_ADMIN_LOGIN
        },
        authType: 'none'
      },
      captures: [
        {
          key: 'sandboxAdminToken',
          responsePath: 'access_token',
          displayLabel: 'Sandbox Admin JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'authenticate-b',
      notes: 'The sandbox admin owns the federation configuration. This credential is only used for peer management — never for agent operations or dispute handling.'
    },

    // ═══════════════════════════════════════════════════════
    // DISCOVERY — Steps 4-5: Federation identity and health
    // ═══════════════════════════════════════════════════════

    // ─── Step 4: Federation Info ───
    {
      id: 'federation-info',
      stepNumber: 4,
      title: 'Federation Info',
      subtitle: 'View this registry\'s federation identity',
      explanation: `Every registry in the federation publishes its **federation info** — a public endpoint that describes who it is and how to connect.

The \`/federation/info\` endpoint returns:
- **Registry name** — the human-readable identity
- **API version** — which protocol version it speaks
- **Federation protocol version** — compatibility level
- **Supported auth methods** — how peers authenticate (mTLS via SPIRE SVIDs)
- **Health check endpoint** — where to verify availability
- **SPIFFE trust domain** — the identity fabric namespace

This is the "business card" of the registry — other registries read this to understand how to federate.`,
      apiCall: {
        method: 'GET',
        path: '/federation/info',
        description: 'Get Registry A\'s federation identity and capabilities',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'authenticate-sandbox-admin',
      notes: 'This is a public endpoint — no authentication required. Any registry can discover another\'s federation capabilities.'
    },

    // ─── Step 5: Federation Health Check ───
    {
      id: 'federation-health',
      stepNumber: 5,
      title: 'Federation Health Check',
      subtitle: 'Verify the registry\'s federation readiness',
      explanation: `Before federating, registries check each other's **health status**. The \`/federation/health-check\` endpoint reports:

- **Overall status** — whether the registry is operational
- **Registry name** — identity confirmation
- **Timestamp** — server time (for clock sync verification)
- **Component health** — database connectivity, identity fabric status

In production, this endpoint supports mTLS authentication for peer-verified health checks. In the sandbox, we use the unauthenticated public mode.`,
      apiCall: {
        method: 'GET',
        path: '/federation/health-check',
        description: 'Check Registry A\'s federation health status',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'federation-info',
      notes: 'A healthy registry reports all components as operational. If a component is degraded, the registry may still accept federation requests but with reduced functionality.'
    },

    // ═══════════════════════════════════════════════════════
    // FEDERATION SETUP — Steps 6-8: Validate or restore federation
    // ═══════════════════════════════════════════════════════

    // ─── Step 6: Register mTLS Peer (idempotent) ───
    {
      id: 'register-peer',
      stepNumber: 6,
      title: 'Register mTLS Peer (Registry B)',
      subtitle: 'Register the real federation peer — or confirm it already exists',
      explanation: `This step registers **Sandbox Registry Test B (mTLS)** as a peer on Registry A. This is the real mTLS peer that connects the two sandbox registries through SPIRE X.509 SVIDs and Nginx TLS termination.

The \`POST /federation/peers/\` endpoint requires the **sandbox admin** JWT because the peer is owned by that account. The \`discovery_auth_info\` uses the \`api_key\` type with an mTLS header — in practice, the SPIRE sidecar handles the actual mTLS authentication transparently.

**This step is idempotent:** if the peer already exists (which it normally does in the sandbox), you'll see a **400** response — that's expected and counts as a pass. It means the federation is already configured.

If the peer was missing (e.g., after a database wipe), this step recreates it.`,
      apiCall: {
        method: 'POST',
        path: '/federation/peers/',
        description: 'Register the real mTLS peer for Registry B (or confirm exists)',
        body: {
          name: 'Sandbox Registry Test B (mTLS)',
          description: 'Registry B sandbox instance — bilateral mTLS federation via SPIRE X.509 SVIDs',
          base_url: 'https://nginx-test-b:8443',
          admin_contact_email: 'admin@test.sandbox',
          discovery_auth_info: {
            type: 'api_key',
            description: 'mTLS via SPIRE handles authentication — this header is for API-level discovery',
            api_key_header_name: 'X-Registry-Key'
          }
        },
        authType: 'developer',
        authTokenRef: '$sandboxAdminToken'
      },
      captures: [
        {
          key: 'peerId',
          responsePath: 'id',
          displayLabel: 'Peer Registry ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201, 400]
      },
      requiresStepId: 'federation-health',
      notes: 'A 400 "already exists" response is expected and means the federation is intact. A 201 means the peer was recreated. Either way, the federation peer is registered.'
    },

    // ─── Step 7: List Active Peers ───
    {
      id: 'list-active-peers',
      stepNumber: 7,
      title: 'List Active Peers',
      subtitle: 'View the live federation network',
      explanation: `The \`GET /federation/peers/\` endpoint returns all **ACTIVE** peer registries. This is a public endpoint — any user can see which registries are federated.

In the sandbox, you should see **Sandbox Registry Test B (mTLS)** with its \`https://nginx-test-b:8443\` URL. This is the real mTLS peer that enables cross-registry agent discovery, federation sync, and the Sovereign Settlement Protocol.

We capture the peer's **ID** here — this is the most reliable source since it only returns active peers.`,
      apiCall: {
        method: 'GET',
        path: '/federation/peers/',
        description: 'List all active peer registries on Registry A',
        authType: 'none'
      },
      captures: [
        {
          key: 'peerId',
          responsePath: 'items.0.id',
          displayLabel: 'Active Peer ID'
        }
      ],
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'register-peer',
      notes: 'You should see "Sandbox Registry Test B (mTLS)" with status ACTIVE. If the list is empty, the federation may need restoration — run scripts/00setup_test_federation.py.'
    },

    // ─── Step 8: Approve Peer (idempotent safety net) ───
    {
      id: 'approve-peer',
      stepNumber: 8,
      title: 'Approve Peer (Admin)',
      subtitle: 'Approve the peer — or confirm it\'s already active',
      explanation: `The \`POST /admin/federation/peers/{id}/approve\` endpoint changes a peer's status from **PENDING_APPROVAL** to **ACTIVE**. This is the admin governance gate — no registry can join the federation without explicit approval.

In the sandbox, the peer is normally already ACTIVE, so this step returns a **400** ("Cannot approve peer registry with status 'ACTIVE'") — that's expected and counts as a pass.

If Step 6 just created a new peer (after a database wipe), this step activates it. Either way, after this step the federation link is fully operational.

The sandbox admin JWT is required because peer approval is a privileged operation — only the registry operator decides which external registries to trust.`,
      apiCall: {
        method: 'POST',
        path: '/admin/federation/peers/$peerId/approve',
        description: 'Approve the peer registration (or confirm already active)',
        pathParams: { id: '$peerId' },
        authType: 'admin',
        authTokenRef: '$sandboxAdminToken'
      },
      validation: {
        successStatusCodes: [200, 201, 400]
      },
      requiresStepId: 'list-active-peers',
      notes: 'A 400 response means the peer is already active — the federation is working as expected. A 200 means the peer was just activated. Both outcomes are valid.'
    },

    // ═══════════════════════════════════════════════════════
    // NETWORK — Steps 9-11: Explore the federation from both sides
    // ═══════════════════════════════════════════════════════

    // ─── Step 9: View Peer Details ───
    {
      id: 'view-peer-details',
      stepNumber: 9,
      title: 'View Peer Details',
      subtitle: 'Inspect the full peer registry profile',
      explanation: `Drill into the peer's full profile. The \`GET /federation/peers/{id}\` endpoint returns all details about a registered peer:

- **Identity** — name, description, base URL (\`https://nginx-test-b:8443\`)
- **Status** — ACTIVE (required for federation operations)
- **Auth info** — how to authenticate when querying this peer's agents
- **Timestamps** — registered_at, approved_at
- **Admin info** — who approved the peer

This is the real mTLS peer — the Nginx reverse proxy at \`nginx-test-b:8443\` terminates TLS using SPIRE-issued X.509 SVIDs and forwards to Registry B's API server.`,
      apiCall: {
        method: 'GET',
        path: '/federation/peers/$peerId',
        description: 'Get full details of the active mTLS peer',
        pathParams: { id: '$peerId' },
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'approve-peer',
      notes: 'The peer details show the real mTLS infrastructure — Nginx TLS termination, SPIRE SVID authentication, and the internal container network that connects the two registries.'
    },

    // ─── Step 10: Network Stats (Registry A) ───
    {
      id: 'network-stats-a',
      stepNumber: 10,
      title: 'Network Stats (Registry A)',
      subtitle: 'View Registry A\'s federation overview',
      explanation: `The \`/federation/network-stats\` endpoint gives a bird's-eye view of the entire federation from this registry's perspective:

- **Total registries** — how many peers are known
- **Active registries** — how many are currently active
- **Total agents** — aggregate agent count across the federation
- **Network health** — overall federation status
- **Last global sync** — when data was last exchanged

This is the network dashboard — a single API call that summarizes the federated ecosystem.`,
      apiCall: {
        method: 'GET',
        path: '/federation/network-stats',
        description: 'Get federation network statistics from Registry A\'s perspective',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'view-peer-details',
      notes: 'Registry A\'s view of the federation. The agent count reflects what Registry A knows about — its local agents plus any synced remote agents from Registry B.'
    },

    // ─── Step 11: Network Stats (Registry B — direct call) ───
    {
      id: 'network-stats-b',
      stepNumber: 11,
      title: 'Network Stats (Registry B)',
      subtitle: 'See the federation from the other side',
      explanation: `The same endpoint, but called on **Registry B** — showing the federation from the other registry's perspective. This is a **direct call** to \`Registry B (sandbox)\`.

Comparing both views demonstrates that federation is **bilateral** — each registry maintains its own view of the network, and they may differ slightly depending on sync timing and local agent counts.

**Congratulations** — you've completed the Federation track! You've explored the real bilateral mTLS federation between two sovereign registries, verified the peer infrastructure, and seen the network from both sides.`,
      apiCall: {
        method: 'GET',
        path: '/federation/network-stats',
        description: 'Get federation network statistics from Registry B\'s perspective — direct call',
        authType: 'none',
        targetBase: '/sandbox-b'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'network-stats-a',
      notes: 'Track complete! Compare Registry B\'s stats with Registry A\'s from Step 10 — the federation is the same network seen from two sovereign perspectives. The bilateral mTLS infrastructure handles all cross-registry communication automatically via SPIRE SVIDs.\n\n*Note: The sandbox mTLS federation is persistent infrastructure that cannot be destroyed by this tutorial. If federation appears broken, run scripts/00setup_test_federation.py to restore it. In a production environment, federation peers would be registered and approved through a formal governance process with identity verification.*'
    }
  ]
}
