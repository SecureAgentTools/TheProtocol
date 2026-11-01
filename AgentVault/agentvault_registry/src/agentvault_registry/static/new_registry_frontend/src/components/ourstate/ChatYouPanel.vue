<!--
  V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): "Your chat settings", reachable from every thread's menu and from
  the chat list, on the console's #/ourchat as well as in Pocket (inventory item 13): the chat part of Pocket's More
  (ChatYouSettings, one component for both), this device's push with its opt-in (review item 6), and doors to quiet
  hours and channels, approvals and support. A drawer on a wide screen, a sheet on a phone.
-->
<template>
  <Teleport to="body">
    <div class="cyp-scrim" :class="{ soft: surface === 'drawer' }" data-testid="cyp-scrim" @click="emit('close')" />
    <aside class="cyp" :class="surface === 'drawer' ? 'cyp-drawer' : 'cyp-sheet'" role="dialog" aria-modal="true"
           :aria-label="t('ourstate.settings.you', 'Your chat settings')" data-testid="chat-you-panel">
      <div v-if="surface === 'sheet'" class="cyp-grab" aria-hidden="true" />
      <header class="cyp-head">
        <div>
          <h2 class="cyp-title">{{ t('ourstate.settings.you', 'Your chat settings') }}</h2>
          <span class="cyp-sub">{{ t('ourstate.settings.youPanelSub', "The chat part of Pocket's More") }}</span>
        </div>
        <button ref="closeEl" class="cyp-x" :aria-label="t('common.close', 'Close')" data-testid="cyp-close" @click="emit('close')">
          <Icon name="mdi:close" /></button>
      </header>
      <section class="cyp-group"><ChatYouSettings /></section>
      <section class="cyp-group">
        <div class="cyp-row" data-testid="cyp-push">
          <Icon name="mdi:bell-ring" class="cyp-ic" />
          <span class="cyp-tx">{{ t('ourstate.settings.push', 'Push on this device') }}<small>{{ pushLine }}</small></span>
          <button v-if="pushState === 'off'" class="cyp-btn" data-testid="cyp-push-on" :disabled="pushBusy"
                  @click="emit('enable-push')">{{ pushBusy ? '…' : t('ourstate.settings.pushTurnOn', 'Turn on') }}</button>
          <span v-else class="cyp-val">{{ pushState === 'on' ? t('ourstate.settings.on', 'On') : '—' }}</span>
        </div>
        <p v-if="pushMsg" class="cyp-msg" data-testid="cyp-push-msg">{{ pushMsg }}</p>
        <router-link class="cyp-row" to="/settings?tab=notifications" data-testid="cyp-quiet" @click="emit('close')">
          <Icon name="mdi:bell" class="cyp-ic" />
          <span class="cyp-tx">{{ t('ourstate.notify.quiet', 'Quiet hours and channels') }}<small>{{ t('ourstate.settings.quietSub', 'When and where each kind of notice reaches you') }}</small></span>
          <span class="cyp-chev" aria-hidden="true">›</span>
        </router-link>
        <router-link class="cyp-row" :to="inPocket ? '/pocket/approvals' : '/settings?tab=approvals'" data-testid="cyp-approvals" @click="emit('close')">
          <Icon name="mdi:shield-key" class="cyp-ic" />
          <span class="cyp-tx">{{ t('pocket.more.approvals', 'Approvals') }}<small>{{ t('ourstate.settings.approvalsSub', 'Every request that waits on you') }}</small></span>
          <span class="cyp-chev" aria-hidden="true">›</span>
        </router-link>
        <router-link class="cyp-row" :to="inPocket ? '/pocket/more' : '/support'" data-testid="cyp-support" @click="emit('close')">
          <Icon name="mdi:lifebuoy" class="cyp-ic" />
          <span class="cyp-tx">{{ t('pocket.more.support', 'Contact support') }}<small>{{ t('ourstate.settings.supportSub', 'Opens a ticket; the reply comes here as a thread') }}</small></span>
          <span class="cyp-chev" aria-hidden="true">›</span>
        </router-link>
      </section>
    </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ChatYouSettings from '@/components/ourstate/ChatYouSettings.vue'
import { useI18n } from '@/composables/useI18n'
import { useEscapeClose } from '@/composables/useEscapeClose'

const props = withDefaults(defineProps<{
  surface: 'drawer' | 'sheet'
  /** This device's push: on, off (the opt-in shows), or not known / not possible here. */
  pushState?: 'on' | 'off' | 'unknown' | 'unsupported'
  pushBusy?: boolean
  pushMsg?: string
  /** Opened inside Pocket: its doors stay in Pocket. */
  inPocket?: boolean
}>(), { pushState: 'unknown', pushBusy: false, pushMsg: '', inPocket: false })
const emit = defineEmits<{ (e: 'close'): void; (e: 'enable-push'): void }>()
const { t } = useI18n()
/* Escape closes it wherever the focus is (the shared stack: the topmost dialog answers) */
useEscapeClose(() => true, () => emit('close'))

const pushLine = computed(() => props.pushState === 'on' ? t('ourstate.settings.pushOnLine', 'Messages that need you reach this device.')
  : props.pushState === 'off' ? t('ourstate.settings.pushOffLine', 'Off: nothing reaches this device while the app is closed.')
  : props.pushState === 'unsupported' ? t('ourstate.settings.pushNo', 'This browser cannot receive push.')
  : t('ourstate.settings.pushUnknown', 'Could not be read on this device.'))

const closeEl = ref<HTMLButtonElement | null>(null)
onMounted(async () => { await nextTick(); closeEl.value?.focus() })
</script>

<style scoped>
.cyp-scrim { position: fixed; inset: 0; z-index: 1199; background: rgba(3, 6, 12, .6); }
.cyp-scrim.soft { background: rgba(3, 6, 12, .38); }
.cyp { position: fixed; z-index: 1200; overflow-y: auto; color: #e6edf3; background: var(--nc-elevated, #181f2e);
  font-family: 'IBM Plex Sans', system-ui, sans-serif; display: flex; flex-direction: column; gap: 12px; }
.cyp-drawer { top: 0; right: 0; bottom: 0; width: 440px; max-width: 100vw; padding: 18px 16px; border-left: 1px solid var(--nc-border-strong, #343a4d);
  box-shadow: -24px 0 60px rgba(0, 0, 0, .5); }
.cyp-sheet { left: 0; right: 0; bottom: 0; max-height: calc(100dvh - 48px); padding: 4px 14px calc(18px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--nc-border-strong, #343a4d); border-radius: 16px 16px 0 0; }
.cyp-grab { width: 38px; height: 4px; border-radius: 2px; background: #4b5568; margin: 8px auto 2px; }
.cyp-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.cyp-title { margin: 0; font-weight: 300; font-size: 1.32rem; }
.cyp-sub { display: block; margin-top: 4px; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .6rem; letter-spacing: .15em;
  text-transform: uppercase; color: #8b96a5; }
.cyp-x { flex: none; width: 44px; height: 44px; display: grid; place-items: center; border: 1px solid var(--nc-border, #2a2f3e); border-radius: 8px;
  background: none; color: #c4ccd6; cursor: pointer; }
.cyp-group { border: 1px solid rgba(255, 255, 255, .07); border-radius: 12px; overflow: hidden; }
.cyp-row { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 8px 14px; color: inherit; text-decoration: none;
  border-bottom: 1px solid rgba(255, 255, 255, .05); }
.cyp-row:last-child { border-bottom: none; }
.cyp-ic { flex: none; width: 18px; height: 18px; color: var(--nc-primary, #00d4ff); }
.cyp-tx { flex: 1; min-width: 0; display: flex; flex-direction: column; font-size: .92rem; }
.cyp-tx small { margin-top: 2px; font-size: .76rem; color: #8b96a5; }
.cyp-val { flex: none; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: .7rem; color: #b4bfcc; }
.cyp-chev { flex: none; opacity: .45; }
.cyp-btn { flex: none; min-height: 36px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--nc-primary, #00d2d2);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), .12); color: var(--nc-primary, #00d2d2); font: inherit; font-size: .84rem; cursor: pointer; }
.cyp-msg { margin: 0; padding: 0 14px 10px; font-size: .8rem; color: #8b96a5; }
</style>
