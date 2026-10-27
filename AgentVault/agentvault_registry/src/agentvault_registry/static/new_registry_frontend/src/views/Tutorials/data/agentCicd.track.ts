import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 15: CICD — ship an agent
 *
 * The hands-on companion to the CICD guided tour. Self-contained:
 *   SETUP (1-3): dev login → bootstrap → create an agent to ship
 *   SHIP (4-8): build a pipeline → snapshot a version → activate it → deploy → check status
 *
 * Auth verified from routers/agent_cicd.py — EVERY endpoint uses the developer/owner JWT
 * (get_current_developer), NOT the agent's JWT. Permission = agent creator OR active org member.
 *   POST /agents/{did}/pipelines
 *   POST /agents/{did}/versions  + /versions/{vid}/activate
 *   POST /agents/{did}/deployments      (manual mode: omit pipeline_id → immediate status=success)
 *   GET  /agents/{did}/deployments/{id}
 * Gotcha: passing a pipeline_id without a configured webhook_url 400s — so for the self-contained
 *   flow we deploy a VERSION directly (manual mode), not the pipeline. Production deploy has no
 *   server-side confirm (the confirm dialog is frontend-only).
 */
export const agentCicdTrack: TutorialTrack = {
  id: 'agent-cicd',
  title: 'CICD — Ship an Agent',
  subtitle: 'Pipelines, versions and deployments',
  description: 'Give an agent a real release pipeline: build stages, snapshot an immutable version, activate it, deploy to production, and read the deployment status — the same CI/CD loop every agent on the network ships through.',
  icon: 'rocket-launch',
  color: 'orange',
  gradientFrom: 'from-orange-500',
  gradientTo: 'to-amber-600',
  estimatedMinutes: 6,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Shipped It',
  steps: [
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT',
      explanation: 'Log in with the tutorial developer account. CICD is managed with the **developer (owner) JWT** — not the agent\'s token — because shipping is an operator action.',
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
      subtitle: 'Creation credential for the agent to ship',
      explanation: 'Request a bootstrap token to create the agent whose releases we will manage.',
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token',
        body: { agent_type_hint: 'tutorial_shippable', requested_by: 'tutorial-user' },
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
      subtitle: 'The agent you will ship',
      explanation: 'Create the agent. Its DID is the handle for every CICD call — pipelines, versions and deployments all hang off `/agents/{did}/…`.',
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the shippable agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'CICD Tutorial Agent',
            description: 'Agent whose releases are managed in the CICD tutorial',
            url: 'http://localhost:8100/agents/cicd-tutorial-agent',
            humanReadableId: 'cicd-tutorial-agent',
            provider: { name: 'Tutorial Developer', organization: 'TheProtocol', contact: 'tutorial-admin@theprotocol.cloud' },
            capabilities: { a2aVersion: '1.0', inbound_protocols: ['cosv1'], outbound_protocols: ['cosv1'], tags: ['tutorial', 'cicd'] },
            authSchemes: [{ scheme: 'oauth2', client_id: 'pending', tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token' }],
            service_endpoints: [{ type: 'messaging', url: 'http://localhost:8100/agents/cicd-tutorial-agent' }],
            metadata: { status: 'active', teg_enabled: true },
          },
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapToken',
      },
      captures: [{ key: 'cicdAgentDid', responsePath: 'agent_did', displayLabel: 'Agent DID' }],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['agent_did'] },
      requiresStepId: 'bootstrap-agent',
    },
    {
      id: 'create-pipeline',
      stepNumber: 4,
      title: 'Build a Pipeline',
      subtitle: 'Define build → test stages',
      explanation: 'A **pipeline** is an ordered set of **stages**, each with **steps** (a name + command). This one builds then tests. `trigger_type: manual` means you fire it yourself (vs. on a push/tag/schedule).',
      apiCall: {
        method: 'POST',
        path: '/agents/$cicdAgentDid/pipelines',
        description: 'Create a build-test pipeline',
        pathParams: { agent_did: '$cicdAgentDid' },
        body: {
          pipeline_name: 'build-test-deploy',
          trigger_type: 'manual',
          pipeline_config: {
            stages: [
              { name: 'build', steps: [{ name: 'compile', command: 'make build' }] },
              { name: 'test', steps: [{ name: 'unit', command: 'make test' }] },
            ],
          },
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [{ key: 'pipelineId', responsePath: 'pipeline_id', displayLabel: 'Pipeline ID' }],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'create-agent',
      notes: 'pipeline_name is unique per agent. The pipeline is reusable; here we ship a version directly.',
    },
    {
      id: 'create-version',
      stepNumber: 5,
      title: 'Snapshot a Version',
      subtitle: 'An immutable release',
      explanation: 'A **version** is an immutable snapshot of the agent\'s config you can deploy and roll back to. Mark it stable so it\'s a safe rollback target.',
      apiCall: {
        method: 'POST',
        path: '/agents/$cicdAgentDid/versions',
        description: 'Create version 1.0.0',
        pathParams: { agent_did: '$cicdAgentDid' },
        body: { version: '1.0.0', release_notes: 'Initial release — created in the CICD tutorial', is_stable: true },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [{ key: 'versionId', responsePath: 'version_id', displayLabel: 'Version ID' }],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'create-pipeline',
      notes: 'version is unique per agent (a duplicate 400s).',
    },
    {
      id: 'activate-version',
      stepNumber: 6,
      title: 'Activate the Version',
      subtitle: 'Make it the live one',
      explanation: 'Activating makes this version the agent\'s current release. Rollback is just activating a previous version — instant and safe.',
      apiCall: {
        method: 'POST',
        path: '/agents/$cicdAgentDid/versions/$versionId/activate',
        description: 'Activate version 1.0.0',
        pathParams: { agent_did: '$cicdAgentDid', version_id: '$versionId' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'create-version',
    },
    {
      id: 'trigger-deployment',
      stepNumber: 7,
      title: 'Deploy to Production',
      subtitle: 'Ship the version',
      explanation: 'Deploy the version to **production**. Passing `version_id` with no `pipeline_id` is the direct (manual) path — it records an immediate, successful deployment. (The production confirm you\'d see in the UI is frontend-only; the API ships directly.)',
      apiCall: {
        method: 'POST',
        path: '/agents/$cicdAgentDid/deployments',
        description: 'Deploy version 1.0.0 to production',
        pathParams: { agent_did: '$cicdAgentDid' },
        body: { environment: 'production', version_id: '$versionId' },
        bodyDynamic: [{ jsonPath: 'version_id', capturedKey: 'versionId' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [{ key: 'deploymentId', responsePath: 'deployment_id', displayLabel: 'Deployment ID' }],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'activate-version',
      notes: 'Manual mode returns status=success immediately. Pipeline-triggered deploys need a webhook URL.',
    },
    {
      id: 'get-deployment',
      stepNumber: 8,
      title: 'Check Deployment Status',
      subtitle: 'Confirm it shipped',
      explanation: "Read the deployment record — environment, version, status and timing. That's the CICD loop end-to-end: pipeline → version → activate → deploy → verify.",
      apiCall: {
        method: 'GET',
        path: '/agents/$cicdAgentDid/deployments/$deploymentId',
        description: 'Fetch the deployment detail',
        pathParams: { agent_did: '$cicdAgentDid', deployment_id: '$deploymentId' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'trigger-deployment',
      notes: 'Take the CICD guided tour to drive this in the UI (the per-agent CICD workspace).',
    },
  ],
}
