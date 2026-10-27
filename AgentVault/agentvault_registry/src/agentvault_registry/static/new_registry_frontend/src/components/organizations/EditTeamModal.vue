<template>
  <Teleport to="body">
    <div class="tp-overlay" role="dialog" aria-modal="true" @click.self="$emit('close')">
      <div class="tp-modal">
        <div class="tp-modal-header">
          <div class="tp-modal-title-row">
            <span class="tp-modal-glyph">✎</span>
            <h3 class="tp-modal-title">EDIT TEAM</h3>
          </div>
          <button class="tp-close-btn" @click="$emit('close')" aria-label="Close">
            <svg viewBox="0 0 14 14" fill="none" width="14" height="14"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>
        </div>

        <div class="tp-modal-body">
          <div class="tp-field">
            <label class="tp-label">TEAM NAME <span class="tp-required">*</span></label>
            <input v-model="formData.name" type="text" class="tp-input" required autofocus />
          </div>

          <div class="tp-field">
            <label class="tp-label">DESCRIPTION</label>
            <textarea v-model="formData.description" class="tp-input tp-textarea" rows="2"></textarea>
          </div>

          <div class="tp-field">
            <label class="tp-label">PERMISSIONS</label>
            <div class="tp-perm-grid">
              <label
                v-for="perm in availablePermissions"
                :key="perm.value"
                :class="['tp-perm-item', { 'tp-perm-item--checked': formData.permissions.includes(perm.value) }]"
              >
                <input v-model="formData.permissions" :value="perm.value" type="checkbox" class="tp-checkbox" />
                <span :class="['tp-perm-chip', permClass(perm.value)]">{{ perm.label }}</span>
              </label>
            </div>
          </div>
        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="isUpdating">CANCEL</button>
          <button class="tp-btn tp-btn--primary" @click="handleSubmit" :disabled="isUpdating || !formData.name">
            <span v-if="isUpdating" class="tp-spinner"></span>
            {{ isUpdating ? 'SAVING...' : 'SAVE TEAM' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useOrganizationStore } from '@/stores/organizations'
import type { Team } from '@/services/api/organizationService'

const props = defineProps<{ team: Team }>()
const emit = defineEmits<{ close: []; updated: [] }>()
const organizationStore = useOrganizationStore()

const isUpdating = ref(false)
const formData = ref({ name: '', description: '', permissions: [] as string[] })

const availablePermissions = [
  { value: 'agents.create',    label: 'Create Agents'    },
  { value: 'agents.edit',      label: 'Edit Agents'      },
  { value: 'agents.delete',    label: 'Delete Agents'    },
  { value: 'contracts.create', label: 'Create Contracts' },
  { value: 'contracts.manage', label: 'Manage Contracts' },
  { value: 'members.invite',   label: 'Invite Members'   },
  { value: 'teams.manage',     label: 'Manage Teams'     }
]

function permClass(val: string): string {
  if (val.includes('delete'))   return 'tp-perm--delete'
  if (val.includes('create'))   return 'tp-perm--create'
  if (val.includes('edit') || val.includes('manage')) return 'tp-perm--update'
  if (val.includes('invite'))   return 'tp-perm--admin'
  return 'tp-perm--read'
}

onMounted(() => {
  if (props.team) {
    formData.value = {
      name: props.team.name,
      description: props.team.description || '',
      permissions: [...(props.team.permissions || [])]
    }
  }
})

async function handleSubmit() {
  isUpdating.value = true
  try {
    await organizationStore.updateTeam(props.team.id, {
      name: formData.value.name,
      description: formData.value.description || undefined,
      permissions: formData.value.permissions.length > 0 ? formData.value.permissions : undefined
    })
    emit('updated')
  } catch (error) {
    console.error('Failed to update team:', error)
  } finally {
    isUpdating.value = false
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
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 6px; cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  background: rgba(255,255,255,0.02);
}
.tp-perm-item:hover { background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.1); }
.tp-perm-item--checked { border-color: rgba(var(--nc-primary-rgb),0.25); background: rgba(var(--nc-primary-rgb),0.05); }
.tp-checkbox { accent-color: rgba(var(--nc-primary-rgb),0.8); width: 13px; height: 13px; flex-shrink: 0; }
.tp-perm-chip { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.04em; }
.tp-perm--read    { color: #69f0ae; }
.tp-perm--create  { color: rgba(var(--nc-primary-rgb),0.85); }
.tp-perm--update  { color: #ffab40; }
.tp-perm--delete  { color: #ff5252; }
.tp-perm--admin   { color: #ce93d8; }
</style>
