<template>
  <div class="dispute-timeline">
    <h4 class="font-semibold mb-4 flex items-center gap-2">
      <Icon name="clock" class="h-5 w-5 text-purple-500" />
      Dispute Timeline
    </h4>
    
    <div v-if="activities.length === 0" class="text-center py-8 bg-gray-50 dark:bg-gray-700/30 rounded-lg">
      <Icon name="inbox" class="h-8 w-8 text-gray-400 mx-auto mb-2" />
      <p class="text-sm text-gray-500 dark:text-gray-400">No activity yet</p>
    </div>
    
    <div v-else class="relative space-y-4">
      <!-- Timeline line -->
      <div class="absolute left-5 top-8 bottom-8 w-0.5 bg-linear-to-b/srgb from-purple-500 to-pink-500"></div>
      
      <!-- Timeline items -->
      <div
        v-for="(activity, index) in displayedActivities"
        :key="activity.id"
        class="relative flex gap-4"
      >
        <!-- Icon -->
        <div :class="getActivityIconClass(activity.type)" class="relative z-10 p-2 rounded-full">
          <Icon :name="getActivityIcon(activity.type)" class="h-4 w-4" />
        </div>
        
        <!-- Content -->
        <div class="flex-1 bg-white dark:bg-gray-800 rounded-lg p-4 border border-gray-200 dark:border-gray-700">
          <div class="flex items-start justify-between mb-2">
            <p class="font-medium text-sm">{{ activity.title }}</p>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ formatTime(activity.timestamp) }}</p>
          </div>
          
          <p class="text-sm text-gray-600 dark:text-gray-400">{{ activity.description }}</p>
          
          <!-- Metadata -->
          <div v-if="activity.metadata" class="mt-2 space-y-1">
            <div v-if="activity.metadata.evidence_type" class="flex items-center gap-2 text-xs text-gray-500">
              <Icon name="paperclip" class="h-3 w-3" />
              Evidence Type: {{ activity.metadata.evidence_type }}
            </div>
            <div v-if="activity.metadata.ruling_type" class="flex items-center gap-2 text-xs">
              <Icon name="gavel" class="h-3 w-3" />
              <span :class="activity.metadata.ruling_type === 'resolved' ? 'text-green-600' : 'text-gray-600'">
                {{ activity.metadata.ruling_type === 'resolved' ? 'Resolved' : 'Dismissed' }}
              </span>
            </div>
            <div v-if="activity.metadata.submitted_by" class="flex items-center gap-2 text-xs text-gray-500">
              <Icon name="user" class="h-3 w-3" />
              By: {{ activity.metadata.submitted_by }}
            </div>
          </div>
        </div>
      </div>
      
      <!-- Load more button -->
      <div v-if="activities.length > displayLimit" class="text-center pt-4">
        <button
          @click="loadMore"
          class="text-sm text-purple-600 hover:text-purple-700 font-medium"
        >
          {{ showAll ? 'Show less' : `Show ${activities.length - displayLimit} more activities` }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import Icon from '@/components/Icon.vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

export interface DisputeActivity {
  id: string
  type: 'created' | 'evidence_submitted' | 'status_changed' | 'ruling_made' | 'comment_added'
  title: string
  description: string
  timestamp: string
  metadata?: {
    evidence_type?: string
    ruling_type?: string
    submitted_by?: string
    old_status?: string
    new_status?: string
  }
}

const props = defineProps<{
  activities: DisputeActivity[]
}>()

const displayLimit = 5
const showAll = ref(false)

const displayedActivities = computed(() => {
  if (showAll.value) {
    return props.activities
  }
  return props.activities.slice(0, displayLimit)
})

function loadMore() {
  showAll.value = !showAll.value
}

function formatTime(timestamp: string): string {
  return dayjs(timestamp).fromNow()
}

function getActivityIcon(type: string): string {
  const icons: Record<string, string> = {
    created: 'plus-circle',
    evidence_submitted: 'paperclip',
    status_changed: 'activity',
    ruling_made: 'gavel',
    comment_added: 'message-circle'
  }
  return icons[type] || 'info'
}

function getActivityIconClass(type: string): string {
  const classes: Record<string, string> = {
    created: 'bg-purple-100 text-purple-600 dark:bg-purple-900/50 dark:text-purple-400',
    evidence_submitted: 'bg-blue-100 text-blue-600 dark:bg-blue-900/50 dark:text-blue-400',
    status_changed: 'bg-yellow-100 text-yellow-600 dark:bg-yellow-900/50 dark:text-yellow-400',
    ruling_made: 'bg-green-100 text-green-600 dark:bg-green-900/50 dark:text-green-400',
    comment_added: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'
  }
  return classes[type] || classes.created
}
</script>