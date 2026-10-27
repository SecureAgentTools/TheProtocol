<template>
  <Teleport to="body">
    <div class="tp-overlay" role="dialog" aria-modal="true" @click.self="$emit('close')">
      <div class="tp-modal">
        <div class="tp-modal-header">
          <div class="tp-modal-title-row">
            <span class="tp-modal-glyph">◈</span>
            <h3 class="tp-modal-title">CREATE TEAM</h3>
          </div>
          <button class="tp-close-btn" @click="$emit('close')" aria-label="Close">
            <svg viewBox="0 0 14 14" fill="none" width="14" height="14"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>
        </div>

        <div class="tp-modal-body">
          <div class="tp-field">
            <label class="tp-label">TEAM NAME <span class="tp-required">*</span></label>
            <input v-model="formData.name" type="text" class="tp-input" placeholder="Engineering Team" required autofocus />
          </div>

          <div class="tp-field">
            <label class="tp-label">DESCRIPTION</label>
            <textarea v-model="formData.description" class="tp-input tp-textarea" rows="2" placeholder="Brief description of the team's purpose"></textarea>
          </div>

          <!-- §ORGLIFE T2 — these are LABELS, and the screen now says so.
               Measured before rewording: a guest in a team with all six ticked
               (read_agents included) still got 403 on GET /{id}/agents, identical
               to a guest in no team on 12 of 12 org surfaces, while the org ROLE
               moved 6 of the same 12. Nothing in the backend reads Team.permissions.
               The checkboxes stay — orgs use them as labels and the rows exist —
               but the word "PERMISSIONS" was a false statement about access. -->
          <div class="tp-field">
            <label class="tp-label">{{ t('createTeamModal.labelsLabel', 'LABELS') }}</label>
            <p class="tp-hint" data-testid="ot-labels-hint">
              {{ t('createTeamModal.labelsHint', 'Descriptive only. Access is governed by each member\'s organization role, not by these.') }}
            </p>
            <div class="tp-perm-grid">
              <label
                v-for="perm in availablePermissions"
                :key="perm.value"
                :class="['tp-perm-item', { 'tp-perm-item--checked': formData.permissions.includes(perm.value) }]"
              >
                <input
                  v-model="formData.permissions"
                  :value="perm.value"
                  type="checkbox"
                  class="tp-checkbox"
                />
                <span :class="['tp-perm-chip', permClass(perm.value)]">{{ perm.label }}</span>
              </label>
            </div>
          </div>
        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="isCreating">CANCEL</button>
          <button class="tp-btn tp-btn--primary" @click="handleSubmit" :disabled="isCreating || !formData.name">
            <span v-if="isCreating" class="tp-spinner"></span>
            {{ isCreating ? 'CREATING...' : 'CREATE TEAM' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useOrganizationStore } from '@/stores/organizations'

const emit = defineEmits<{ close: []; created: [] }>()
const organizationStore = useOrganizationStore()

const isCreating = ref(false)
const { t } = useI18n()
const formData = ref({ name: '', description: '', permissions: [] as string[] })

const availablePermissions = [
  { value: 'agents.create',    label: 'Create Agents'     },
  { value: 'agents.edit',      label: 'Edit Agents'       },
  { value: 'agents.delete',    label: 'Delete Agents'     },
  { value: 'contracts.create', label: 'Create Contracts'  },
  { value: 'contracts.manage', label: 'Manage Contracts'  },
  { value: 'members.invite',   label: 'Invite Members'    },
  { value: 'teams.manage',     label: 'Manage Teams'      }
]

function permClass(val: string): string {
  if (val.includes('delete'))   return 'tp-perm--delete'
  if (val.includes('create'))   return 'tp-perm--create'
  if (val.includes('edit') || val.includes('manage')) return 'tp-perm--update'
  if (val.includes('invite'))   return 'tp-perm--admin'
  return 'tp-perm--read'
}

async function handleSubmit() {
  if (!formData.value.name) return
  isCreating.value = true
  try {
    await organizationStore.createTeam({
      name: formData.value.name,
      description: formData.value.description || undefined,
      permissions: formData.value.permissions.length > 0 ? formData.value.permissions : undefined
    })
    emit('created')
  } catch (error) {
    console.error('Failed to create team:', error)
  } finally {
    isCreating.value = false
  }
}
</script>

<style scoped>
@import './tp-modal-shared.css';

.tp-perm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.tp-perm-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  background: rgba(255,255,255,0.02);
}
.tp-perm-item:hover { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.1); }
.tp-perm-item--checked { border-color: rgba(var(--nc-primary-rgb),0.25); background: rgba(var(--nc-primary-rgb),0.05); }
.tp-checkbox { accent-color: rgba(var(--nc-primary-rgb),0.8); width: 13px; height: 13px; flex-shrink: 0; }
.tp-perm-chip {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; letter-spacing: 0.04em;
}
.tp-perm--read    { color: #69f0ae; }
.tp-perm--create  { color: rgba(var(--nc-primary-rgb),0.85); }
.tp-perm--update  { color: #ffab40; }
.tp-perm--delete  { color: #ff5252; }
.tp-perm--admin   { color: #ce93d8; }
.tp-hint {
  margin: 0 0 8px; font-size: 9px; line-height: 1.4;
  color: rgba(var(--nc-primary-rgb), 0.5);
}
</style>
