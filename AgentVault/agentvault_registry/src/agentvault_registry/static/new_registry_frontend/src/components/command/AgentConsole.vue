<template>
  <div class="gac">
    <!-- TARGET RIBBON (agent) -->
    <div class="gac-ribbon">
      <div class="gac-ribbon-top">
        <span class="gac-target-label">TARGET AGENT</span>
        <button class="gac-back" type="button" title="Back" @click="$emit('back')">
          <Icon name="mdi:close" :size="12" /> deselect
        </button>
      </div>
      <h3 class="gac-name">{{ agent.name || 'Agent' }}</h3>
      <p class="gac-did">
        <code class="gac-code">{{ shortDid }}</code>
        <button class="gac-copy" type="button" title="Copy DID" @click="copyDid"><Icon name="mdi:content-copy" :size="11" /></button>
      </p>
      <div class="gac-badges">
        <span class="gac-chip">home: {{ homeLabel }}</span>
        <span v-if="agent.frame" class="gac-chip">Frame {{ agent.frame }}</span>
        <span v-if="homeEntry" class="gac-chip gac-chip--ccy">{{ homeEntry.currency }}</span>
      </div>
      <div class="gac-bal">
        <div class="gac-bal-item"><span class="gac-bal-k">Liquid</span><span class="gac-bal-v">{{ fmt(agent.liquidBalance) }}</span></div>
        <div class="gac-bal-item"><span class="gac-bal-k">Locked</span><span class="gac-bal-v">{{ fmt(agent.stakedBalance) }}</span></div>
        <div class="gac-bal-item"><span class="gac-bal-k">Reputation</span><span class="gac-bal-v">{{ agent.reputation ?? '—' }}</span></div>
      </div>
    </div>

    <section class="gac-sec">
      <h4 class="gac-h"><Icon name="mdi:bank" :size="12" /> Actions</h4>

      <button
        class="gac-act" type="button"
        :disabled="!(homeIsLocal || homeConnected) || !!busyAction"
        :title="homeIsLocal || homeConnected ? '' : `Agent is homed on ${homeLabel} — connect its console first (select the registry, Registry console → Connect)`"
        @click="$emit('act', { id: homeIsLocal ? 'fund_agent_local' : 'fund_agent_remote_home', payload: { did: agent.did, name: agent.name } })"
      >
        <Icon name="mdi:bank-transfer" :size="14" />
        <span class="gac-act-t">Fund from treasury
          <span class="gac-act-s">{{ homeIsLocal ? `canonical FLOW 4 on ${localKey}` : (homeConnected ? `FLOW 4 on ${homeLabel} (relayed)` : `connect ${homeLabel}'s console first`) }}</span>
        </span>
      </button>

      <button
        class="gac-act" type="button"
        :disabled="!myAgent || !!busyAction"
        :title="myAgent ? '' : `Sign in as one of your agents on ${homeLabel} first (select the registry → Registry console → My agents here)`"
        @click="$emit('act', { id: 'transfer_from_my_agent', payload: { toDid: agent.did, toName: agent.name } })"
      >
        <Icon name="mdi:swap-horizontal" :size="14" />
        <span class="gac-act-t">Transfer from my agent
          <span class="gac-act-s">{{ myAgent ? `${myAgent.did.slice(0, 22)}… → this agent (Model L, relayed)` : `no active agent on ${homeLabel}` }}</span>
        </span>
      </button>

      <button
        class="gac-act" type="button" :disabled="!!busyAction"
        @click="$emit('act', { id: 'ironhand_probe', payload: { did: agent.did, name: agent.name } })"
      >
        <Icon name="mdi:radar" :size="14" />
        <span class="gac-act-t">IRONHAND probe<span class="gac-act-s">real low-value mTLS transfer at this agent · Model A</span></span>
      </button>

      <router-link class="gac-act gac-act--link" :to="{ path: '/galactic-map' }">
        <Icon name="mdi:open-in-new" :size="14" />
        <span class="gac-act-t">Open in Galactic Map<span class="gac-act-s">full agent detail card</span></span>
      </router-link>
    </section>

    <!-- Enforcement (coordinated suspension — Model A local / B remote) -->
    <section class="gac-sec">
      <h4 class="gac-h"><Icon name="mdi:shield-alert" :size="12" /> Enforcement</h4>
      <div class="gac-enf">
        <button
          class="gac-act gac-act--danger gac-act--half" type="button"
          :disabled="!enforceable || !!busyAction"
          :title="enforceable ? '' : `Connect ${homeLabel}'s console first`"
          @click="$emit('act', { id: 'suspend_agent', payload: { did: agent.did, name: agent.name } })"
        >
          <Icon name="mdi:account-cancel" :size="14" />
          <span class="gac-act-t">Suspend<span class="gac-act-s">registry + mTLS + TEG</span></span>
        </button>
        <button
          class="gac-act gac-act--half" type="button"
          :disabled="!enforceable || !!busyAction"
          :title="enforceable ? '' : `Connect ${homeLabel}'s console first`"
          @click="$emit('act', { id: 'reinstate_agent', payload: { did: agent.did, name: agent.name } })"
        >
          <Icon name="mdi:account-check" :size="14" />
          <span class="gac-act-t">Reinstate<span class="gac-act-s">reverse suspension</span></span>
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import type { DirectoryEntry } from '@/services/api/command'

const props = defineProps<{
  agent: { did: string; name?: string; registryId?: string; originRegistry?: string; frame?: string; liquidBalance?: number; stakedBalance?: number; reputation?: number }
  homeEntry: DirectoryEntry | null
  localKey: string
  busyAction: string | null
  homeConnected: boolean
  myAgent: { did: string; token: string } | null
}>()
defineEmits<{ (e: 'back'): void; (e: 'act', a: { id: string; payload?: any }): void }>()

const homeIsLocal = computed(() => !!props.homeEntry?.is_local)
const enforceable = computed(() => homeIsLocal.value || props.homeConnected)
const homeLabel = computed(() => props.homeEntry?.name || props.agent.originRegistry || (props.agent.registryId === '__local__' ? props.localKey : props.agent.registryId) || 'unknown')
const shortDid = computed(() => {
  const d = props.agent.did || ''
  return d.length > 34 ? `${d.slice(0, 24)}…${d.slice(-6)}` : d
})
const fmt = (n?: number) => (typeof n === 'number' ? n.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : '—')
function copyDid() {
  try { navigator.clipboard?.writeText(props.agent.did) } catch { /* clipboard unavailable */ }
}
</script>

<style scoped>
.gac { display: grid; gap: 14px; }
.gac-ribbon {
  padding: 11px 12px;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .07);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .35);
  border-radius: 10px;
}
.gac-ribbon-top { display: flex; align-items: center; justify-content: space-between; }
.gac-target-label { font-size: .58rem; letter-spacing: .18em; font-weight: 800; color: var(--nc-primary, #00d2d2); }
.gac-back {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; border: 1px solid rgba(255,255,255,.12); border-radius: 6px;
  color: var(--nc-text-muted, #94a3b8); font-size: .62rem; padding: 2px 7px; cursor: pointer;
}
.gac-back:hover { color: #fff; }
.gac-name { margin: 5px 0 3px; font-size: 1.1rem; font-weight: 800; }
.gac-did { margin: 0 0 7px; display: flex; align-items: center; gap: 6px; }
.gac-code { font-family: ui-monospace, monospace; font-size: .66rem; color: var(--nc-text-muted, #94a3b8); word-break: break-all; }
.gac-copy { background: transparent; border: 1px solid rgba(255,255,255,.1); border-radius: 5px; width: 20px; height: 20px; display: grid; place-items: center; color: var(--nc-text-muted, #94a3b8); cursor: pointer; }
.gac-copy:hover { color: var(--nc-primary, #00d2d2); }
.gac-badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 9px; }
.gac-chip {
  font-size: .58rem; font-weight: 700; letter-spacing: .06em; padding: 1px 7px; border-radius: 4px;
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.12); color: var(--nc-text-primary, #e8eaed);
}
.gac-chip--ccy { background: rgba(var(--nc-primary-rgb, 0,210,210), .1); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .35); color: var(--nc-primary, #00d2d2); }
.gac-bal { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.gac-bal-item { background: rgba(4,8,14,.45); border: 1px solid rgba(255,255,255,.06); border-radius: 8px; padding: 6px 8px; display: grid; gap: 2px; }
.gac-bal-k { font-size: .56rem; text-transform: uppercase; letter-spacing: .1em; color: var(--nc-text-muted, #94a3b8); font-weight: 700; }
.gac-bal-v { font-size: .82rem; font-weight: 800; font-variant-numeric: tabular-nums; }

.gac-sec { display: grid; gap: 6px; }
.gac-h { margin: 0; display: flex; align-items: center; gap: 6px; font-size: .62rem; text-transform: uppercase; letter-spacing: .12em; font-weight: 700; color: var(--nc-text-muted, #94a3b8); }
.gac-act {
  display: flex; align-items: center; gap: 10px; width: 100%; text-align: left;
  padding: 9px 11px; border-radius: 8px; cursor: pointer;
  background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.08);
  color: var(--nc-text-primary, #e8eaed); font-size: .78rem; text-decoration: none;
}
.gac-act:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); background: rgba(var(--nc-primary-rgb, 0,210,210), .06); }
.gac-act:disabled { opacity: .45; cursor: not-allowed; }
.gac-act-t { display: grid; font-weight: 700; }
.gac-act-s { font-size: .62rem; font-weight: 500; color: var(--nc-text-muted, #94a3b8); }
.gac-act--link { color: var(--nc-text-primary, #e8eaed); }
.gac-act--danger:hover:not(:disabled) { border-color: rgba(239,68,68,.5); background: rgba(239,68,68,.07); }
.gac-enf { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.gac-act--half { width: 100%; }
</style>
