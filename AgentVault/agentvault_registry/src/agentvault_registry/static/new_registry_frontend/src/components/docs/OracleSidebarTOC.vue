<script setup lang="ts">
import { computed } from 'vue'
import type { DocsHeading } from '@/composables/docs/useDocsMarkdown'

interface Props {
  headings: DocsHeading[]
  activeSlug: string | null
  chapterNumber: string
  chapterTitle: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'jump', slug: string): void
}>()

const visibleHeadings = computed(() =>
  props.headings.filter((h) => h.level === 2 || h.level === 3)
)

function onJump(slug: string) {
  emit('jump', slug)
}
</script>

<template>
  <aside
    v-if="visibleHeadings.length > 0"
    class="orc-toc"
    aria-label="Table of contents"
  >
    <div class="orc-toc-inner">
      <div class="orc-toc-eyebrow">ON THIS PAGE</div>
      <div class="orc-toc-chapter">
        <span class="orc-toc-chapter-num">{{ chapterNumber }}</span>
        <span class="orc-toc-chapter-title">{{ chapterTitle }}</span>
      </div>
      <nav class="orc-toc-list">
        <button
          v-for="h in visibleHeadings"
          :key="h.slug"
          type="button"
          :class="[
            'orc-toc-item',
            `orc-toc-l${h.level}`,
            { 'orc-toc-active': h.slug === activeSlug },
          ]"
          @click="onJump(h.slug)"
        >
          <span class="orc-toc-rail" aria-hidden="true"></span>
          <span class="orc-toc-label">{{ h.text }}</span>
        </button>
      </nav>
    </div>
  </aside>
</template>

<style scoped>
.orc-toc {
  position: fixed;
  /* Anchor TOC to the right of the 900px-wide article with a 40px gap — never
     overlaps the article no matter the viewport width. Falls back to 2rem on
     narrow viewports (safe because TOC is hidden below 1500px anyway). */
  right: max(2rem, calc((100vw - 900px) / 2 - 260px));
  /* Clear header + potential BETA banner (both sit in the top ~130px). */
  top: 150px;
  width: 220px;
  max-height: calc(100vh - 180px);
  z-index: 50;
  pointer-events: none;
  /* Promote to its own GPU layer so the animated starfield canvas behind it
     doesn't force the browser to repaint the TOC every frame. */
  transform: translateZ(0);
  will-change: transform;
  contain: layout paint;
}

.orc-toc-inner {
  pointer-events: auto;
  max-height: calc(100vh - 180px);
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 1.25rem 1rem 1.25rem 0.75rem;
  /* Translucent but NOT backdrop-filter — backdrop-filter over an animated
     canvas causes constant repaints + flickering text. We fake glass with a
     semi-opaque gradient + subtle inner highlight. Text stays crisp. */
  background:
    linear-gradient(180deg, rgba(15, 18, 30, 0.72) 0%, rgba(10, 13, 22, 0.62) 100%);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.5),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 92, 246, 0.35) transparent;
}
.orc-toc-inner::-webkit-scrollbar { width: 6px; }
.orc-toc-inner::-webkit-scrollbar-thumb {
  background: rgba(139, 92, 246, 0.35);
  border-radius: 3px;
}
.orc-toc-inner::-webkit-scrollbar-track { background: transparent; }

.orc-toc-eyebrow {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: rgba(148, 163, 184, 0.75);
  margin: 0 0 0.55rem 0.75rem;
}

.orc-toc-chapter {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  padding: 0 0.75rem 0.85rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 0.6rem;
}
.orc-toc-chapter-num {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 0.68rem;
  font-weight: 700;
  color: #3B82F6;
  opacity: 0.75;
  letter-spacing: 0.04em;
}
.orc-toc-chapter-title {
  font-size: 0.78rem;
  font-weight: 600;
  color: #e4ecf4;
  line-height: 1.25;
  letter-spacing: 0.01em;
}

.orc-toc-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.orc-toc-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  width: 100%;
  background: transparent;
  border: none;
  padding: 0.38rem 0.6rem 0.38rem 0.9rem;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  font-size: 0.82rem;
  line-height: 1.4;
  color: rgba(148, 163, 184, 0.85);
  text-align: left;
  transition: color 0.18s ease, background 0.18s ease;
}
.orc-toc-item:hover { color: #e4ecf4; background: rgba(59, 130, 246, 0.06); }

.orc-toc-rail {
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 2px;
  border-radius: 1px;
  background: transparent;
  transition: background 0.18s ease;
}
.orc-toc-item:hover .orc-toc-rail { background: rgba(59, 130, 246, 0.35); }

.orc-toc-l3 { padding-left: 1.7rem; font-size: 0.78rem; color: rgba(148, 163, 184, 0.7); }

.orc-toc-active {
  color: #ffffff !important;
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.12), rgba(139, 92, 246, 0.05));
}
.orc-toc-active .orc-toc-rail {
  background: linear-gradient(180deg, #3B82F6, #8B5CF6);
  box-shadow: 0 0 10px rgba(59, 130, 246, 0.55);
}

.orc-toc-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1499px) {
  .orc-toc { display: none; }
}
</style>
