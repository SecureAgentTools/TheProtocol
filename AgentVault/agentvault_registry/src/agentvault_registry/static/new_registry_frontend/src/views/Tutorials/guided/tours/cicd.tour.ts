import type { GuidedTour } from '../tour.types'

// CICD — "Ship an agent". CICD is PER-AGENT: the fleet list (/ci-cd) drills into one
// agent's pipeline/version/deployment workspace (/agent/:did/ci-cd). The tour navigates
// the fleet, opens a real agent via its Manage button, then spotlights the deploy flow.
// Anchors added in CICDList.vue, AgentCICD.vue and DashboardSidebar.vue.
export const cicdTour: GuidedTour = {
  id: 'cicd',
  title: 'CICD — Ship an Agent',
  subtitle: 'Pipelines, versions and deployments',
  icon: 'mdi:rocket-launch',
  accent: '#ffb74d',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Ship with confidence', placement: 'center',
      body: 'TheProtocol gives every agent its own **CI/CD**: build **pipelines** of stages, snapshot immutable **versions**, and **deploy** to dev → staging → production with logs, approvals and one-click **rollback**.\n\nCICD is **per-agent** — let\'s open the fleet view.',
    },
    {
      id: 'nav', title: 'The CICD fleet', anchor: 'cicd-fleet,cicd-hero', placement: 'auto', route: '/ci-cd',
      body: 'This is your **CICD fleet** — every agent you can ship, with its active version and recent deployments at a glance. Pick any one to manage it.',
    },
    {
      id: 'manage', title: 'Open an agent', anchor: 'cicd-manage,cicd-hero', placement: 'left',
      body: '**Manage** opens that agent\'s full CICD workspace. Let\'s open one now.',
      cta: { label: 'Open this agent →', do: 'click-anchor' },
    },
    {
      id: 'deploy', title: 'The Deploy button', anchor: 'cicd-deploy,cicd-agent-hero,cicd-hero', placement: 'bottom',
      body: 'Top-right is **▶ Deploy** — choose an environment (dev / staging / **production**), a pipeline and a version, and ship. Production asks you to confirm first.',
    },
    {
      id: 'builder', title: '1 · Build a pipeline', anchor: 'cicd-tab-builder,cicd-agent-hero,cicd-hero', placement: 'bottom',
      body: 'The **Builder** tab is where a pipeline is born: add **stages**, each with **steps** (a name + command), plus approval gates and retries. Save it and it\'s ready to run.',
    },
    {
      id: 'pipelines', title: '2 · Run pipelines', anchor: 'cicd-tab-pipelines,cicd-agent-hero,cicd-hero', placement: 'bottom',
      body: 'The **Pipelines** tab lists what you\'ve built. Hit ▶ on any pipeline to trigger a deployment, or wire a webhook so a push/tag triggers it automatically.',
    },
    {
      id: 'versions', title: '3 · Version it', anchor: 'cicd-tab-versions,cicd-agent-hero,cicd-hero', placement: 'bottom',
      body: '**Versions** are immutable snapshots of your agent\'s config. Mark one **stable**, **activate** it to make it live, or **rollback** to a previous one instantly if something\'s off.',
    },
    {
      id: 'deployments', title: '4 · Watch it ship', anchor: 'cicd-tab-deployments,cicd-agent-hero,cicd-hero', placement: 'bottom',
      body: 'The **Deployments** tab is mission control — live status, per-deployment **logs**, environment filters, and cancel. This is where you confirm a release actually landed.',
    },
    {
      id: 'outro', title: 'From code to production', placement: 'center',
      body: 'That\'s the loop: **build a pipeline → snapshot a version → deploy → watch the logs → rollback if needed**. Every agent ships the same way.\n\nYou\'re ready to ship — open any agent and give it a version.',
    },
  ],
}
