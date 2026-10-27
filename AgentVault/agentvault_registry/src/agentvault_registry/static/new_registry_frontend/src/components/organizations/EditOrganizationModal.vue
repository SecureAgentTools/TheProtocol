<template>
  <Teleport to="body">
    <div class="tp-overlay" role="dialog" aria-modal="true" @click.self="$emit('close')">
      <div class="tp-modal">
        <div class="tp-modal-header">
          <div class="tp-modal-title-row">
            <span class="tp-modal-glyph">✎</span>
            <h3 class="tp-modal-title">EDIT ORGANIZATION</h3>
          </div>
          <button class="tp-close-btn" @click="$emit('close')" aria-label="Close">
            <svg viewBox="0 0 14 14" fill="none" width="14" height="14"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
          </button>
        </div>

        <div class="tp-modal-body">
          <div class="tp-field">
            <label class="tp-label">ORGANIZATION NAME <span class="tp-required">*</span></label>
            <input v-model="formData.name" type="text" class="tp-input" required autofocus />
          </div>
          <div class="tp-field">
            <label class="tp-label">DESCRIPTION</label>
            <textarea v-model="formData.description" class="tp-input tp-textarea" rows="3"></textarea>
          </div>
          <div class="tp-field">
            <label class="tp-label">WEBSITE</label>
            <input v-model="formData.website" type="url" class="tp-input" placeholder="https://example.com" />
          </div>
        </div>

        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="$emit('close')" :disabled="isUpdating">CANCEL</button>
          <button class="tp-btn tp-btn--primary" @click="handleSubmit" :disabled="isUpdating || !formData.name">
            <span v-if="isUpdating" class="tp-spinner"></span>
            {{ isUpdating ? 'SAVING...' : 'SAVE CHANGES' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useOrganizationStore } from '@/stores/organizations'
import type { Organization } from '@/services/api/organizationService'

const props = defineProps<{ organization: Organization | null }>()
const emit = defineEmits<{ close: []; updated: [] }>()
const organizationStore = useOrganizationStore()

const isUpdating = ref(false)
const formData = ref({ name: '', description: '', website: '' })

onMounted(() => {
  if (props.organization) {
    formData.value = {
      name: props.organization.name,
      description: props.organization.description || '',
      website: props.organization.website || ''
    }
  }
})

async function handleSubmit() {
  isUpdating.value = true
  try {
    await organizationStore.updateOrganization({
      name: formData.value.name,
      description: formData.value.description || undefined,
      website: formData.value.website || undefined
    })
    emit('updated')
  } catch (error) {
    console.error('Failed to update organization:', error)
  } finally {
    isUpdating.value = false
  }
}
</script>

<style scoped>
@import './tp-modal-shared.css';
</style>
