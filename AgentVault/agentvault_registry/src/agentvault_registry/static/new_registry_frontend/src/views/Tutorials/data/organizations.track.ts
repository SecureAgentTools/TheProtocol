import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 14: Organizations — stand up a team
 *
 * The hands-on companion to the Organizations guided tour. Self-contained:
 *   SETUP (1-3): dev login → bootstrap → create an agent (to assign later)
 *   ORG  (4-7): create org → create a team → invite a member → assign the agent to the team
 *   READ (8-10): list members, teams, agents
 *
 * Auth verified from routers/organizations.py (owner satisfies every required_role):
 *   POST /organizations                                   dev JWT (caller = owner)
 *   POST /organizations/{org}/teams                       dev JWT (admin/owner)
 *   POST /organizations/{org}/invite                      dev JWT (admin/owner)
 *   POST /organizations/{org}/agents/{did}/assign         dev JWT (admin AND agent creator)
 * Gotchas: invite only CREATES an invitation (acceptance is a separate token flow another dev
 *   runs); the team-member-add endpoint is a known stub — assign the agent at the ORG level with
 *   a team_id instead.
 */
export const organizationsTrack: TutorialTrack = {
  id: 'organizations',
  title: 'Organizations',
  subtitle: 'Stand up a team and bring your fleet together',
  description: 'Create an organization, add a team with scoped permissions, invite a teammate, and assign one of your agents to the team: the cooperative layer that owns treasuries and lists on AGORA.',
  icon: 'office-building',
  color: 'blue',
  gradientFrom: 'from-blue-500',
  gradientTo: 'to-indigo-600',
  estimatedMinutes: 6,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Org Builder',
  steps: [
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT',
      explanation: 'Log in with the tutorial developer account. This developer becomes the **owner** of the organization you create — owners pass every role check.',
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with the sandbox tutorial account',
        body: { ...SANDBOX_TUTORIAL_LOGIN },
        authType: 'none',
      },
      captures: [{ key: 'sandboxDevToken', responsePath: 'access_token', displayLabel: 'Developer JWT', sensitive: true }],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
    },
    {
      id: 'bootstrap-agent',
      stepNumber: 2,
      title: 'Bootstrap an Agent',
      subtitle: 'Creation credential for the agent you will assign',
      explanation: 'Request a bootstrap token so we can create an agent — later we assign it to the organization to show how a team owns its fleet.',
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token',
        body: { agent_type_hint: 'tutorial_org_member', requested_by: 'tutorial-user' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [{ key: 'bootstrapToken', responsePath: 'bootstrap_token', displayLabel: 'Bootstrap Token', sensitive: true }],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['bootstrap_token'] },
      requiresStepId: 'authenticate',
    },
    {
      id: 'create-agent',
      stepNumber: 3,
      title: 'Create the Agent',
      subtitle: 'An agent to assign to the org',
      explanation: "Create an agent owned by you. Because you don't belong to an org yet, it stays unassigned — we'll attach it to the team in Step 7.",
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Org Tutorial Agent',
            description: 'Agent assigned to a team in the Organizations tutorial',
            url: 'http://localhost:8100/agents/org-tutorial-agent',
            humanReadableId: 'org-tutorial-agent',
            provider: { name: 'Tutorial Developer', organization: 'TheProtocol', contact: 'tutorial-admin@theprotocol.cloud' },
            capabilities: { a2aVersion: '1.0', inbound_protocols: ['cosv1'], outbound_protocols: ['cosv1'], tags: ['tutorial', 'organizations'] },
            authSchemes: [{ scheme: 'oauth2', client_id: 'pending', tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token' }],
            service_endpoints: [{ type: 'messaging', url: 'http://localhost:8100/agents/org-tutorial-agent' }],
            metadata: { status: 'active', teg_enabled: true },
          },
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapToken',
      },
      captures: [{ key: 'orgAgentDid', responsePath: 'agent_did', displayLabel: 'Agent DID' }],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['agent_did'] },
      requiresStepId: 'bootstrap-agent',
    },
    {
      id: 'create-org',
      stepNumber: 4,
      title: 'Create the Organization',
      subtitle: 'You become the owner',
      explanation: 'Create the org. The name must be 3–255 chars; the **slug** is auto-derived. As **owner** you can manage teams, members and agents.',
      apiCall: {
        method: 'POST',
        path: '/organizations',
        description: 'Create an organization',
        body: { name: 'Tutorial Org', description: 'A team created in the Organizations tutorial' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [
        { key: 'orgId', responsePath: 'id', displayLabel: 'Organization ID' },
        { key: 'orgSlug', responsePath: 'slug', displayLabel: 'Org Slug' },
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['id'] },
      requiresStepId: 'create-agent',
    },
    {
      id: 'create-team',
      stepNumber: 5,
      title: 'Create a Team',
      subtitle: 'Group members with scoped permissions',
      explanation: 'Teams subdivide an org and carry **permissions** — e.g. a Platform team that can read and create agents but not touch billing. Members inherit their team\'s permissions.',
      apiCall: {
        method: 'POST',
        path: '/organizations/$orgId/teams',
        description: 'Create a team in the org',
        pathParams: { org_id: '$orgId' },
        body: { name: 'Platform Team', description: 'Builds and runs the agents', permissions: ['read_agents', 'create_agents'] },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [{ key: 'teamId', responsePath: 'id', displayLabel: 'Team ID' }],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['id'] },
      requiresStepId: 'create-org',
    },
    {
      id: 'invite-member',
      stepNumber: 6,
      title: 'Invite a Member',
      subtitle: 'Send a role-scoped invitation',
      explanation: 'Invite a teammate by email with a **role** (`admin` | `member` | `guest`). This creates an invitation + token; the invitee joins by accepting the token (a separate flow, so a solo run stops at the invitation).',
      apiCall: {
        method: 'POST',
        path: '/organizations/$orgId/invite',
        description: 'Invite a member to the org',
        pathParams: { org_id: '$orgId' },
        body: { email: 'teammate@tutorial.example.com', role: 'member' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [{ key: 'invitationId', responsePath: 'invitation_id', displayLabel: 'Invitation ID' }],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'create-team',
      notes: 'The invitee accepts via POST /organizations/invitations/{token}/accept with their own JWT.',
    },
    {
      id: 'assign-agent',
      stepNumber: 7,
      title: 'Assign the Agent to the Team',
      subtitle: 'Bring your fleet into the org',
      explanation: 'Attach the agent you created to the org and the team. Now it can act on the org\'s behalf: trade its listing, draw on its treasury (within policy), ship via CICD.',
      apiCall: {
        method: 'POST',
        path: '/organizations/$orgId/agents/$orgAgentDid/assign',
        description: 'Assign the agent to the org + team',
        pathParams: { org_id: '$orgId', agent_did: '$orgAgentDid' },
        body: { team_id: '$teamId' },
        bodyDynamic: [{ jsonPath: 'team_id', capturedKey: 'teamId' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'invite-member',
      notes: 'Dual gate: you must be org-admin AND the agent\'s creator. The tutorial dev is both.',
    },
    {
      id: 'view-members',
      stepNumber: 8,
      title: 'List Members',
      subtitle: 'Who belongs to the org',
      explanation: 'Read the membership roster — you (owner) plus any pending invitations resolve here as members join.',
      apiCall: {
        method: 'GET',
        path: '/organizations/$orgId/members',
        description: 'List org members',
        pathParams: { org_id: '$orgId' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'assign-agent',
    },
    {
      id: 'view-teams',
      stepNumber: 9,
      title: 'List Teams',
      subtitle: 'The teams in your org',
      explanation: 'Read the teams — your Platform team appears with its permissions.',
      apiCall: {
        method: 'GET',
        path: '/organizations/$orgId/teams',
        description: 'List org teams',
        pathParams: { org_id: '$orgId' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'view-members',
    },
    {
      id: 'view-agents',
      stepNumber: 10,
      title: 'List Org Agents',
      subtitle: 'Your fleet under the org',
      explanation: "Read the org's assigned agents — the agent you attached in Step 7 is now part of the team's fleet. That's the Organizations loop: org → team → people → agents.",
      apiCall: {
        method: 'GET',
        path: '/organizations/$orgId/agents',
        description: 'List agents assigned to the org',
        pathParams: { org_id: '$orgId' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'view-teams',
      notes: 'Take the Organizations guided tour to see this dashboard in the UI.',
    },
  ],
}
