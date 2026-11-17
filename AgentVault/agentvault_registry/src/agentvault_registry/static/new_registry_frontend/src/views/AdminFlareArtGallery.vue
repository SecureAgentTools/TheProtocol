<!--
  AdminFlareArtGallery — the review gallery for the contributor track's art (V0665; his idea, room seq 4063/4070/4081).

  NOT linked from any menu: the route #/admin/flare-art is reached only by an admin who types it (router: requiresRole admin). A dev
  build can also serve it alone at /flare-art.html (the project root's flare-art.html; the production build has one entry, index.html,
  so that page is not in dist).

  It shows every NEW item beside the existing one it grew from (the old ones are rendered by their own components, untouched):
    the Commander plate first, then the rings at 22, 32 and 96 px, the corner badges at 16, 22 and 48 px, and the titles under a sample name
    as in the sidebar's account block and on the profile card he marked; each on the neural and on the sovereign theme, moving or still
    (the still view is what prefers-reduced-motion gives).
-->
<template>
  <div class="fag" :class="{ 'fag-still': still }" data-testid="flare-art-gallery">
    <header class="fag-head">
      <h1>{{ t('contributorTrack.gallery.title', 'Contributor track art') }}</h1>
      <p>{{ t('contributorTrack.gallery.subtitle', 'For review.') }}</p>
      <div class="fag-motion" role="group">
        <button type="button" :class="{ on: !still }" data-testid="fag-moving" @click="still = false">{{ t('contributorTrack.gallery.moving', 'Moving') }}</button>
        <button type="button" :class="{ on: still }" data-testid="fag-still" @click="still = true">{{ t('contributorTrack.gallery.still', 'Still') }}</button>
      </div>
    </header>

    <!-- the one of one -->
    <section class="fag-sec" data-testid="fag-commander">
      <h2>{{ t('contributorTrack.gallery.commander', 'The Commander plate') }}</h2>
      <p class="fag-note">{{ t('contributorTrack.gallery.commanderNote', '') }}</p>
      <div class="fag-themes fag-themes-3">
        <div v-for="th in [...THEMES, 'light']" :key="th" class="fag-panel" :class="`fag-panel-${th}`">
          <span class="fag-tag">{{ th === 'light' ? t('contributorTrack.gallery.lightSurface', 'On a light surface (the black glow)') : t(`contributorTrack.gallery.${th}`, th) }}</span>
          <div class="fag-row fag-row-commander">
            <ArtSample v-for="sz in PLATE_SIZES" :key="sz" :label="tp('contributorTrack.gallery.plateOf', 'The Commander plate, {size} size', { size: sz })"><CommanderPlate :size="sz" :still="still" /></ArtSample>
          </div>
        </div>
      </div>
    </section>

    <!-- the plates as one family -->
    <section class="fag-sec" data-testid="fag-family">
      <h2>{{ t('contributorTrack.gallery.family', 'The plates, side by side') }}</h2>
      <p class="fag-note">{{ t('contributorTrack.gallery.familyNote', '') }}</p>
      <div class="fag-themes">
        <div v-for="th in THEMES" :key="th" class="fag-panel" :class="`fag-panel-${th}`">
          <span class="fag-tag">{{ t(`contributorTrack.gallery.${th}`, th) }}</span>
          <div class="fag-family">
            <div class="fag-family-cell"><ArtSample :label="tp('contributorTrack.gallery.plateOf', 'The Commander plate, {size} size', { size: 'sidebar' })"><CommanderPlate size="sidebar" :still="still" /></ArtSample><span class="fag-cap2">commander</span></div>
            <div v-for="ti in NEW_TITLES" :key="ti.key" class="fag-family-cell">
              <ArtSample :label="tp('contributorTrack.gallery.titleOf', '{name} title, {size} size', { name: t(`contributorTrack.titles.${ti.key}.name`, ti.key), size: 'sidebar' })"><TitleEmblem :title-key="ti.key" size="sidebar" :still="still" /></ArtSample>
              <span class="fag-cap2">{{ TITLE_MATERIAL[ti.key] }}</span>
            </div>
            <div class="fag-family-cell">
              <ArtSample :label="tp('contributorTrack.gallery.titleOf', '{name} title, {size} size', { name: t('contributorTrack.titles.the-eye-sees-all.name', 'The Eye Sees All'), size: 'sidebar' })"><TitleEmblem title-key="the-eye-sees-all" variant="b" size="sidebar" :still="still" /></ArtSample>
              <span class="fag-cap2">bronze · option B</span>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- rings -->
    <section class="fag-sec" data-testid="fag-rings">
      <h2>{{ t('contributorTrack.gallery.rings', 'Encirclements') }}</h2>
      <p class="fag-note">{{ t('contributorTrack.gallery.ringsNote', '') }}</p>
      <article v-for="r in NEW_RINGS" :key="r.key" class="fag-item" :data-testid="`fag-ring-${r.key}`">
        <div class="fag-meta">
          <h3>{{ t(`contributorTrack.rings.${r.key}.name`, r.key) }} <small>{{ r.cover === 'full' ? 'full cover' : 'logo visible' }}</small></h3>
          <p>{{ t('contributorTrack.gallery.unlock', 'Unlocked by') }}: {{ t(`contributorTrack.rings.${r.key}.unlock`, '') }}</p>
          <p>{{ t('contributorTrack.gallery.oldItem', 'Grew from') }}: {{ r.lineage ?? t('contributorTrack.gallery.noOld', 'a new line') }}</p>
        </div>
        <div class="fag-themes">
          <div v-for="th in THEMES" :key="th" class="fag-panel" :class="`fag-panel-${th}`">
            <span class="fag-tag">{{ t(`contributorTrack.gallery.${th}`, th) }}</span>
            <div class="fag-pair">
              <div v-if="r.lineage" class="fag-cell fag-old" :data-lineage="r.lineage">
                <ArtSample v-for="s in OLD_SIZES" :key="s" :label="tp('contributorTrack.gallery.ringOf', '{name} ring, {px}', { name: r.lineage, px: s })"><FlareEncirclement tier="shadow_chancellor" :variant="r.lineage" :size="s" initials="SB" /></ArtSample>
                <span class="fag-cap">{{ r.lineage }}</span>
              </div>
              <div class="fag-cell fag-new">
                <ArtSample v-for="px in GALLERY_SIZES" :key="px" :label="tp('contributorTrack.gallery.ringOf', '{name} ring, {px}', { name: t(`contributorTrack.rings.${r.key}.name`, r.key), px: `${px} px` })"><EarnedRing :ring-key="r.key" :size="px" initials="SB" :still="still" /></ArtSample>
                <span class="fag-cap">{{ r.key }}</span>
              </div>
            </div>
          </div>
        </div>
      </article>
    </section>

    <!-- badges -->
    <section class="fag-sec" data-testid="fag-badges">
      <h2>{{ t('contributorTrack.gallery.badges', 'Corner badges') }}</h2>
      <p class="fag-note">{{ t('contributorTrack.gallery.badgesNote', '') }}</p>
      <article v-for="b in NEW_BADGES" :key="b.key" class="fag-item" :data-testid="`fag-badge-${b.key}`">
        <div class="fag-meta">
          <h3>{{ t(`contributorTrack.badges.${b.key}.name`, b.key) }}</h3>
          <p>{{ t('contributorTrack.gallery.unlock', 'Unlocked by') }}: {{ t(`contributorTrack.badges.${b.key}.unlock`, '') }}</p>
          <p>{{ t('contributorTrack.gallery.oldItem', 'Grew from') }}: {{ b.lineage ?? t('contributorTrack.gallery.noOld', 'a new line') }}</p>
        </div>
        <div class="fag-themes">
          <div v-for="th in THEMES" :key="th" class="fag-panel" :class="`fag-panel-${th}`">
            <span class="fag-tag">{{ t(`contributorTrack.gallery.${th}`, th) }}</span>
            <div class="fag-pair">
              <div v-if="b.lineage" class="fag-cell fag-old">
                <ArtSample v-for="s in OLD_BADGE_SIZES" :key="s" :label="tp('contributorTrack.gallery.badgeOf', '{name} badge, {px}', { name: b.lineage, px: s })"><FlareBadge :tier="b.lineage" :size="s" :show-label="false" /></ArtSample>
                <span class="fag-cap">{{ b.lineage }}</span>
              </div>
              <div class="fag-cell fag-new">
                <ArtSample v-for="px in BADGE_SIZES" :key="px" :label="tp('contributorTrack.gallery.badgeOf', '{name} badge, {px}', { name: t(`contributorTrack.badges.${b.key}.name`, b.key), px: `${px} px` })"><EarnedBadge :badge-key="b.key" :size="px" :still="still" /></ArtSample>
                <span class="fag-cap">{{ b.key }}</span>
              </div>
            </div>
          </div>
        </div>
      </article>
    </section>

    <!-- titles -->
    <section class="fag-sec" data-testid="fag-titles">
      <h2>{{ t('contributorTrack.gallery.titles', 'Titles') }}</h2>
      <p class="fag-note">{{ t('contributorTrack.gallery.titlesNote', '') }}</p>
      <article v-for="ti in NEW_TITLES" :key="ti.key" class="fag-item" :data-testid="`fag-title-${ti.key}`">
        <div class="fag-meta">
          <h3>{{ t(`contributorTrack.titles.${ti.key}.name`, ti.key) }} <small v-if="ti.proposed" class="fag-proposed">{{ t('contributorTrack.gallery.proposed', 'Proposed for your yes') }}</small></h3>
          <p>{{ t('contributorTrack.gallery.unlock', 'Unlocked by') }}: {{ t(`contributorTrack.titles.${ti.key}.unlock`, '') }}</p>
          <p class="fag-style">{{ ti.style }}</p>
        </div>
        <div class="fag-themes">
          <div v-for="th in THEMES" :key="th" class="fag-panel" :class="`fag-panel-${th}`">
            <span class="fag-tag">{{ t(`contributorTrack.gallery.${th}`, th) }}</span>
            <div class="fag-samples">
              <ArtSample class="fag-sidebar-sample" :label="tp('contributorTrack.gallery.sidebarOf', 'Sidebar sample, {name} title', { name: t(`contributorTrack.titles.${ti.key}.name`, ti.key) })">
                <span class="fag-av">SB</span>
                <span class="fag-who"><b>{{ t('contributorTrack.gallery.sampleName', 'Sample Name') }}</b><TitleEmblem :title-key="ti.key" size="sidebar" :still="still" /></span>
              </ArtSample>
              <ArtSample class="fag-card-sample" :label="tp('contributorTrack.gallery.cardOf', 'Profile card sample, {name} title', { name: t(`contributorTrack.titles.${ti.key}.name`, ti.key) })">
                <b>{{ t('contributorTrack.gallery.sampleName', 'Sample Name') }}</b>
                <TitleEmblem :title-key="ti.key" size="card" :still="still" />
              </ArtSample>
              <ArtSample class="fag-large-sample" :label="tp('contributorTrack.gallery.titleOf', '{name} title, {size} size', { name: t(`contributorTrack.titles.${ti.key}.name`, ti.key), size: 'large' })"><TitleEmblem :title-key="ti.key" size="large" :still="still" /></ArtSample>
            </div>
          </div>
        </div>
      </article>
      <!-- The Eye Sees All, the two proposals for his pick -->
      <article class="fag-item" data-testid="fag-title-the-eye-sees-all-b">
        <div class="fag-meta">
          <h3>{{ t('contributorTrack.titles.the-eye-sees-all.name', 'The Eye Sees All') }} <small class="fag-proposed">{{ t('contributorTrack.gallery.optionB', 'Option B: the mark at the left') }}</small></h3>
          <p>{{ t('contributorTrack.gallery.optionBNote', '') }}</p>
        </div>
        <div class="fag-themes">
          <div v-for="th in THEMES" :key="th" class="fag-panel" :class="`fag-panel-${th}`">
            <span class="fag-tag">{{ t(`contributorTrack.gallery.${th}`, th) }}</span>
            <div class="fag-samples">
              <ArtSample class="fag-sidebar-sample" :label="tp('contributorTrack.gallery.sidebarOf', 'Sidebar sample, {name} title', { name: t('contributorTrack.titles.the-eye-sees-all.name', 'The Eye Sees All') })"><span class="fag-av">SB</span><span class="fag-who"><b>{{ t('contributorTrack.gallery.sampleName', 'Sample Name') }}</b><TitleEmblem title-key="the-eye-sees-all" variant="b" size="sidebar" :still="still" /></span></ArtSample>
              <ArtSample class="fag-card-sample" :label="tp('contributorTrack.gallery.cardOf', 'Profile card sample, {name} title', { name: t('contributorTrack.titles.the-eye-sees-all.name', 'The Eye Sees All') })"><b>{{ t('contributorTrack.gallery.sampleName', 'Sample Name') }}</b><TitleEmblem title-key="the-eye-sees-all" variant="b" size="card" :still="still" /></ArtSample>
              <ArtSample class="fag-large-sample" :label="tp('contributorTrack.gallery.titleOf', '{name} title, {size} size', { name: t('contributorTrack.titles.the-eye-sees-all.name', 'The Eye Sees All'), size: 'large' })"><TitleEmblem title-key="the-eye-sees-all" variant="b" size="large" :still="still" /></ArtSample>
            </div>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import FlareBadge from '@/components/common/FlareBadge.vue'
import EarnedRing from '@/components/contributor/EarnedRing.vue'
import EarnedBadge from '@/components/contributor/EarnedBadge.vue'
import TitleEmblem from '@/components/contributor/TitleEmblem.vue'
import CommanderPlate from '@/components/contributor/CommanderPlate.vue'
import ArtSample from '@/components/contributor/ArtSample.vue'
import { GALLERY_SIZES, NEW_BADGES, NEW_RINGS, NEW_TITLES, TITLE_MATERIAL } from '@/services/contributorTrack'

const { t, tp } = useI18n()
const still = ref(false)
const PLATE_SIZES = ['sidebar', 'card', 'large'] as const
const THEMES = ['neural', 'sovereign'] as const
// the old ring component has size presets: xs 22, md 36, xl 96 (the nearest to 22, 32, 96)
const OLD_SIZES = ['xs', 'md', 'xl'] as const
const OLD_BADGE_SIZES = ['xs', 'sm', 'lg'] as const
const BADGE_SIZES = [16, 22, 48] as const
</script>

<style scoped>
.fag { padding: 28px 32px 80px; max-width: 1500px; margin: 0 auto; color: #cfe4ee; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.fag-head h1 { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-weight: 300; letter-spacing: 0.12em; text-transform: uppercase; font-size: 22px; margin: 0 0 6px; }
.fag-head p { margin: 0 0 14px; opacity: 0.7; font-size: 13px; }
.fag-motion { display: inline-flex; border: 1px solid rgba(160, 200, 220, 0.3); border-radius: 3px; overflow: hidden; }
.fag-motion button { background: transparent; color: inherit; border: 0; padding: 6px 14px; font: 600 11px 'IBM Plex Mono', monospace; letter-spacing: 0.1em; text-transform: uppercase; cursor: pointer; }
.fag-motion button.on { background: rgba(120, 200, 230, 0.18); }
.fag-sec { margin-top: 38px; }
.fag-sec h2 { font: 300 15px 'IBM Plex Mono', monospace; letter-spacing: 0.2em; text-transform: uppercase; border-bottom: 1px solid rgba(160, 200, 220, 0.18); padding-bottom: 8px; }
.fag-note { font-size: 12px; opacity: 0.6; margin: 8px 0 14px; }
.fag-item { display: grid; grid-template-columns: 250px 1fr; gap: 18px; padding: 16px 0; border-bottom: 1px solid rgba(160, 200, 220, 0.08); }
.fag-meta h3 { margin: 0 0 6px; font: 600 14px 'IBM Plex Sans', sans-serif; }
.fag-meta h3 small { font-weight: 400; opacity: 0.55; font-size: 10px; margin-left: 6px; letter-spacing: 0.08em; text-transform: uppercase; }
.fag-meta p { margin: 0 0 4px; font-size: 12px; opacity: 0.75; line-height: 1.45; }
.fag-style { font-family: 'IBM Plex Mono', monospace; opacity: 0.5; }
.fag-proposed { color: #ffd27a; opacity: 1 !important; }
.fag-themes { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.fag-panel { position: relative; border: 1px solid rgba(160, 200, 220, 0.14); border-radius: 4px; padding: 26px 18px 14px; min-height: 110px; }
.fag-panel-neural { background: #08111a; --nc-primary: #00d2d2; --nc-primary-rgb: 0, 210, 210; }
.fag-themes-3 { grid-template-columns: 1fr 1fr 1fr; }
.fag-panel-light { background: #8d9aa8; }
.fag-panel-sovereign { background: #170a0d; --nc-primary: #e5484d; --nc-primary-rgb: 229, 72, 77; }
.fag-tag { position: absolute; left: 10px; top: 7px; font: 400 9px 'IBM Plex Mono', monospace; letter-spacing: 0.14em; text-transform: uppercase; color: #a9bcc8; }
.fag-panel-light .fag-tag, .fag-panel-light .fag-cap, .fag-panel-light .fag-cap2 { color: #0b1620; }
.fag-pair { display: flex; gap: 26px; align-items: center; flex-wrap: wrap; }
.fag-cell { display: flex; gap: 22px; align-items: center; padding: 10px 12px 6px; border-radius: 3px; position: relative; }
.fag-old { opacity: 0.92; }
.fag-new { background: rgba(255, 255, 255, 0.02); }
.fag-cap { position: absolute; left: 12px; bottom: -4px; font: 400 8px 'IBM Plex Mono', monospace; color: #a9bcc8; letter-spacing: 0.1em; text-transform: uppercase; }
.fag-row-commander > * { max-width: 100%; }
.fag-row-commander { display: flex; flex-direction: column; align-items: flex-start; gap: 26px; align-items: center; flex-wrap: wrap; padding: 22px 8px; }
.fag-samples { display: flex; gap: 34px; align-items: center; flex-wrap: wrap; }
.fag-sidebar-sample { display: flex; gap: 8px; align-items: center; width: 188px; padding: 6px 8px; background: rgba(255, 255, 255, 0.025); border-radius: 3px; }
.fag-av { width: 30px; height: 30px; border-radius: 50%; border: 1px solid rgba(var(--nc-primary-rgb), 0.5); display: inline-flex; align-items: center; justify-content: center; font: 700 11px 'IBM Plex Mono', monospace; color: var(--nc-primary); }
.fag-who { display: flex; flex-direction: column; gap: 1px; }
.fag-who b { font: 600 11px 'IBM Plex Mono', monospace; color: #e9f3f8; }
.fag-card-sample { display: flex; flex-direction: column; gap: 3px; }
.fag-card-sample b { font: 700 15px 'IBM Plex Mono', monospace; color: #f1f7fb; }
.fag-large-sample { padding: 4px 8px; }
.fag-family { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 16px 14px; padding: 8px 4px 4px; }
.fag-family-cell { display: flex; flex-direction: column; gap: 5px; align-items: flex-start; min-width: 0; }
.fag-cap2 { font: 400 8px 'IBM Plex Mono', monospace; letter-spacing: 0.1em; text-transform: uppercase; color: #a9bcc8; }
/* the old components do not take a still prop: the still view stops their animations from outside */
.fag-still :deep(.fc-encircle), .fag-still :deep(.fc-encircle *), .fag-still :deep(.fc-encircle::before), .fag-still :deep(.fc-encircle::after),
.fag-still :deep(.flare-badge), .fag-still :deep(.flare-badge *), .fag-still :deep(.flare-badge::after) { animation: none !important; }
.fag-item > *, .fag-themes > *, .fag-panel { min-width: 0; }
.fag-meta p, .fag-meta h3 { overflow-wrap: anywhere; }
.fag-card-sample, .fag-large-sample { min-width: 0; max-width: 100%; }
@media (max-width: 900px) { .fag-item { grid-template-columns: 1fr; } .fag-themes { grid-template-columns: 1fr; } }
</style>
