<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// §FIRMHIRE (H3.2) — FIRMS in Discovery, proof-ranked.
//
// Renders /organizations/discover/firms: firms ranked by settled guild work
// (worker + client halves), stars from real verify events, honest zeros as
// zeros (§DISCREFINE law — a card face never hides its numbers). Two doors:
//   • Engage — opens the firm's INTAKE AGENT in the ordinary agent modal
//     (emits to the parent; ONE engage brain, never a re-derivation). Shut
//     with the server's own reason when no valid intake is set.
//   • Post a bounty — routes to the guild post form prefilled with the
//     for-org tag (the board's own form; the door FILLS, the human fires).
// ─────────────────────────────────────────────────────────────────────────────
import { nextTick, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { apiClient } from '@/services/api/client'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const emit = defineEmits<{ (e: 'engage', did: string): void }>()

const loading = ref(true)
const firms = ref<any[]>([])

const firmSpotlight = ref('')      // slug of the voice-matched card
const firmMiss = ref('')           // the honest no-match note
// §FESUITE (V0577): the firms read got no answer. It emptied the list and the lane vanished (it renders only with firms),
// which reads as "no firms on this registry"; a voice ask then went nowhere. The lane now says the read failed, and a
// voice ask is matched only against a list that answered (it stays in the address for Try again).
const firmsFailed = ref(false)

async function load() {
  loading.value = true
  firmsFailed.value = false
  try {
    const { data } = await apiClient.get('/organizations/discover/firms', { params: { limit: 12 } })
    firms.value = data?.firms || []
  } catch { firms.value = []; firmsFailed.value = true }
  finally { loading.value = false }
  if (firmsFailed.value) return
  // §VOICEHIRE — "hire the firm <name>": spotlight the match, say a miss out
  // loud (never a silent lane pretending the ask landed), scrub the param.
  const asked = String(route.query.firm || '').trim().toLowerCase()
  if (asked) {
    const hit = firms.value.find(f =>
      String(f.name || '').toLowerCase().includes(asked) || String(f.slug || '').toLowerCase().includes(asked))
    if (hit) {
      firmSpotlight.value = hit.slug
      await nextTick()
      document.querySelector(`[data-testid="fl-firm-${hit.slug}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    } else {
      firmMiss.value = asked
    }
    router.replace({ query: { ...route.query, firm: undefined } }).catch(() => {})
  }
}

function postBounty(f: any) {
  router.push({ path: '/guild', query: { post: '1', for_org: f.org_id, title: `For ${f.name}: ` } })
}

onMounted(load)
</script>

<template>
  <section v-if="loading || firms.length || firmsFailed" class="fl-root" data-testid="firms-lane">
    <div class="fl-head">
      <h2 class="fl-title">
        <Icon name="mdi:office-building" class="fl-title-ic" />
        <span>{{ t('firmsLane.title', 'Firms') }}</span>
      </h2>
      <span class="fl-sub">{{ t('firmsLane.sub', 'Organizations ranked by settled, registry-attested work') }}</span>
    </div>

    <div v-if="loading" class="fl-grid">
      <div v-for="n in 3" :key="n" class="fl-card fl-card--skel"></div>
    </div>
    <ReadFailedNotice v-else-if="firmsFailed" :retry="load" data-testid="fl-failed"
      :text="t('firmsLane.readFailed', 'The firms on this registry could not be read just now.')" />
    <div v-else class="fl-grid">
      <p v-if="firmMiss" class="fl-miss" data-testid="fl-firm-miss">
        {{ t('firmsLane.voiceMiss', 'No firm here matched') }} “{{ firmMiss }}”</p>
      <div v-for="f in firms" :key="f.org_id" class="fl-card"
           :class="{ 'fl-spot': firmSpotlight === f.slug }" :data-testid="'fl-firm-' + f.slug">
        <div class="fl-card-top">
          <span class="fl-name">{{ f.name }}</span>
          <span v-if="f.transparency" class="fl-open" :title="t('firmsLane.openTip', 'This firm publishes its work records on a public feed')">
            {{ t('firmsLane.open', 'open books') }}
          </span>
        </div>
        <p v-if="f.description" class="fl-desc">{{ f.description }}</p>
        <!-- honest zeros ARE the card face (§DISCREFINE) -->
        <div class="fl-proof" data-testid="fl-proof">
          <span class="fl-stat"><strong>{{ f.verified_jobs }}</strong> {{ t('firmsLane.jobs', 'jobs delivered') }}</span>
          <span class="fl-stat"><strong>{{ f.commissioned }}</strong> {{ t('firmsLane.commissioned', 'commissioned') }}</span>
          <span class="fl-stat" v-if="f.stars_n > 0"><strong>{{ f.stars_avg }}</strong>★ ({{ f.stars_n }})</span>
          <span class="fl-stat fl-stat--zero" v-else>{{ t('firmsLane.noStars', 'no ratings yet') }}</span>
        </div>
        <div class="fl-doors">
          <button
            class="fl-btn fl-btn--primary"
            :disabled="!f.engage_available"
            :title="f.engage_available ? t('firmsLane.engageTip', 'Open the firm\'s intake agent') : f.engage_reason"
            :data-testid="'fl-engage-' + f.slug"
            @click="f.engage_available && emit('engage', f.intake_agent_did)"
          >{{ t('firmsLane.engage', 'Engage') }}</button>
          <button class="fl-btn" :data-testid="'fl-bounty-' + f.slug" @click="postBounty(f)">
            {{ t('firmsLane.bounty', 'Post a bounty to this firm') }}
          </button>
        </div>
        <p v-if="!f.engage_available" class="fl-shut">{{ f.engage_reason }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.fl-root { margin-bottom: 22px; }
.fl-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; flex-wrap: wrap; }
.fl-title {
  display: flex; align-items: center; gap: 8px; margin: 0;
  font-size: 1.05rem; font-weight: 600; color: rgba(226, 232, 240, 0.9);
}
.fl-title-ic { font-size: 1.05rem; color: rgba(var(--nc-primary-rgb), 0.7); }
/* §FESUITE (V0626 proof): this lane's small text must hold 4.5:1 (WCAG AA) on the page's dark backgrounds. The old
   slate alphas 0.35-0.6 measured 1.9-3.4; 0.8 measures 4.9 and 0.85 5.4 on the lightest (#0f121b plus the card). */
.fl-sub { font-size: 0.72rem; color: rgba(148, 163, 184, 0.8); }

.fl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.fl-card {
  padding: 14px 16px; border-radius: 10px;
  background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
}
.fl-card--skel { min-height: 130px; opacity: 0.35; animation: fl-pulse 1.2s ease-in-out infinite; }
@keyframes fl-pulse { 50% { opacity: 0.15; } }
.fl-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.fl-name { font-size: 0.92rem; font-weight: 600; color: rgba(226, 232, 240, 0.9); }
.fl-open {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.56rem; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; white-space: nowrap;
  color: rgba(52, 211, 153, 0.85); padding: 2px 7px; border-radius: 999px;
  background: rgba(52, 211, 153, 0.08); border: 1px solid rgba(52, 211, 153, 0.25);
}
.fl-desc {
  font-size: 0.76rem; line-height: 1.5; color: rgba(148, 163, 184, 0.85);
  margin: 6px 0 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.fl-proof { display: flex; align-items: center; gap: 14px; margin-top: 10px; flex-wrap: wrap; }
.fl-stat { font-size: 0.72rem; color: rgba(148, 163, 184, 0.85); }
.fl-stat strong { color: rgba(var(--nc-primary-rgb), 0.9); font-family: 'IBM Plex Mono', monospace; }
.fl-stat--zero { color: rgba(148, 163, 184, 0.8); }
.fl-doors { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.fl-btn {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.64rem; font-weight: 600; letter-spacing: 0.06em;
  padding: 6px 12px; border-radius: 6px; cursor: pointer; transition: all 0.15s;
  background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.1);
  color: rgba(226, 232, 240, 0.8);
}
.fl-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.08); }
.fl-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.fl-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.12); border-color: rgba(var(--nc-primary-rgb), 0.3);
  color: rgba(var(--nc-primary-rgb), 0.9);
}
.fl-btn--primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.2); }
.fl-shut { font-size: 0.68rem; color: rgba(148, 163, 184, 0.8); margin: 6px 0 0; }
.fl-miss { font-size: .8rem; color: var(--nc-warning, #e8b348); margin: 0 0 8px; }
.fl-spot { outline: 2px solid var(--nc-accent, #22d3ee); outline-offset: 2px; border-radius: 10px; }
</style>
