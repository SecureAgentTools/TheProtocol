<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import {
  searchDocs,
  DEFAULT_SEARCH_SUGGESTIONS,
  type DocsSearchResult,
} from '@/composables/docs/useDocsSearchIndex'

interface Props {
  open: boolean
  /** Search-index namespace (§OPDOCS). Defaults to 'oracle' so the Oracle keeps
   *  its exact prior behavior; the Operator docs pass 'operator'. */
  namespace?: string
  /** Empty-state suggestions. Defaults to the Oracle set. */
  suggestions?: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'select', result: DocsSearchResult): void
}>()

const RECENT_KEY = `${props.namespace || 'oracle'}:recent-searches`
const RECENT_MAX = 5

const query = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const highlightIdx = ref(0)
const recentSearches = ref<string[]>([])

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) {
      recentSearches.value = parsed.slice(0, RECENT_MAX).filter((q) => typeof q === 'string')
    }
  } catch {
    /* ignore */
  }
}

function pushRecent(q: string) {
  const term = q.trim()
  if (!term) return
  const next = [term, ...recentSearches.value.filter((r) => r !== term)].slice(0, RECENT_MAX)
  recentSearches.value = next
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next))
  } catch {
    /* ignore */
  }
}

function clearRecent() {
  recentSearches.value = []
  try {
    localStorage.removeItem(RECENT_KEY)
  } catch {
    /* ignore */
  }
}

const results = computed<DocsSearchResult[]>(() => searchDocs(query.value, 20, props.namespace || 'oracle'))

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      loadRecent()
      nextTick(() => {
        inputRef.value?.focus()
        inputRef.value?.select()
      })
    } else {
      highlightIdx.value = 0
    }
  }
)

watch(query, () => {
  highlightIdx.value = 0
})

function close() {
  emit('close')
}

function applySuggestion(s: string) {
  query.value = s
  nextTick(() => inputRef.value?.focus())
}

function chooseResult(r: DocsSearchResult) {
  pushRecent(query.value)
  emit('select', r)
}

function onKeydown(e: KeyboardEvent) {
  if (!props.open) return
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (results.value.length === 0) return
    highlightIdx.value = (highlightIdx.value + 1) % results.value.length
    scrollActiveIntoView()
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (results.value.length === 0) return
    highlightIdx.value =
      (highlightIdx.value - 1 + results.value.length) % results.value.length
    scrollActiveIntoView()
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    const r = results.value[highlightIdx.value]
    if (r) chooseResult(r)
    return
  }
}

function scrollActiveIntoView() {
  nextTick(() => {
    const el = document.querySelector(
      `.orc-palette-result[data-idx="${highlightIdx.value}"]`
    ) as HTMLElement | null
    if (!el) return
    el.scrollIntoView({ block: 'nearest' })
  })
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <teleport to="body">
    <transition name="orc-palette-fade">
      <div v-if="open" class="orc-palette-root" role="dialog" aria-modal="true" aria-label="Search the Oracle">
        <div class="orc-palette-backdrop" @click="close"></div>
        <div class="orc-palette-shell">
          <div class="orc-palette-inputrow">
            <span class="orc-palette-search-icon" aria-hidden="true">⌕</span>
            <input
              ref="inputRef"
              v-model="query"
              type="text"
              class="orc-palette-input"
              placeholder="Search the Oracle — headings, chapters, concepts…"
              autocomplete="off"
              spellcheck="false"
            />
            <kbd class="orc-palette-kbd">ESC</kbd>
          </div>

          <div class="orc-palette-body">
            <div v-if="!query.trim()" class="orc-palette-empty">
              <div v-if="recentSearches.length > 0" class="orc-palette-section">
                <div class="orc-palette-section-head">
                  <span class="orc-palette-section-label">Recent</span>
                  <button type="button" class="orc-palette-clear" @click="clearRecent">
                    Clear
                  </button>
                </div>
                <div class="orc-palette-chips">
                  <button
                    v-for="r in recentSearches"
                    :key="r"
                    type="button"
                    class="orc-palette-chip"
                    @click="applySuggestion(r)"
                  >
                    ↺ {{ r }}
                  </button>
                </div>
              </div>
              <div class="orc-palette-section">
                <div class="orc-palette-section-head">
                  <span class="orc-palette-section-label">Try searching</span>
                </div>
                <div class="orc-palette-chips">
                  <button
                    v-for="s in (suggestions || DEFAULT_SEARCH_SUGGESTIONS)"
                    :key="s"
                    type="button"
                    class="orc-palette-chip"
                    @click="applySuggestion(s)"
                  >
                    {{ s }}
                  </button>
                </div>
              </div>
              <div class="orc-palette-hint">
                <span><kbd>↑ ↓</kbd> navigate</span>
                <span><kbd>↵</kbd> select</span>
                <span><kbd>esc</kbd> close</span>
              </div>
            </div>

            <div v-else-if="results.length === 0" class="orc-palette-no-results">
              <div class="orc-palette-no-icon">✦</div>
              <div class="orc-palette-no-text">No matches for "{{ query }}".</div>
              <div class="orc-palette-no-hint">
                Try broader terms — the search is fuzzy but indexes every section.
              </div>
            </div>

            <div v-else class="orc-palette-results" role="listbox">
              <button
                v-for="(r, idx) in results"
                :key="r.id"
                type="button"
                :data-idx="idx"
                :class="['orc-palette-result', { 'orc-palette-result-active': idx === highlightIdx }]"
                @mouseenter="highlightIdx = idx"
                @click="chooseResult(r)"
                role="option"
                :aria-selected="idx === highlightIdx"
              >
                <div class="orc-palette-result-head">
                  <span class="orc-palette-badge">CH {{ r.chapterNumber }}</span>
                  <span class="orc-palette-result-chapter">{{ r.chapterTitle }}</span>
                  <span v-if="r.headingText" class="orc-palette-result-arrow">›</span>
                  <span v-if="r.headingText" class="orc-palette-result-heading">{{ r.headingText }}</span>
                </div>
                <div
                  v-if="r.snippet"
                  class="orc-palette-result-snippet"
                  v-html="r.snippet"
                ></div>
              </button>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<style scoped>
.orc-palette-root {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 8vh 1.25rem 1.25rem;
}

.orc-palette-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(2, 4, 10, 0.55);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.orc-palette-shell {
  position: relative;
  width: 100%;
  max-width: 680px;
  max-height: 78vh;
  display: flex;
  flex-direction: column;
  background: rgba(12, 15, 24, 0.72);
  backdrop-filter: blur(26px) saturate(170%);
  -webkit-backdrop-filter: blur(26px) saturate(170%);
  border: 1px solid rgba(139, 92, 246, 0.25);
  border-radius: 18px;
  box-shadow:
    0 24px 64px rgba(0, 0, 0, 0.6),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  overflow: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: #e4ecf4;
}

.orc-palette-inputrow {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(255, 255, 255, 0.02);
}
.orc-palette-search-icon {
  font-size: 1.3rem;
  color: rgba(139, 92, 246, 0.9);
  line-height: 1;
}
.orc-palette-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #f8fafc;
  font-family: inherit;
  font-size: 1rem;
  letter-spacing: 0.01em;
  padding: 0;
}
.orc-palette-input::placeholder {
  color: rgba(148, 163, 184, 0.6);
}
.orc-palette-kbd {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: rgba(148, 163, 184, 0.7);
  padding: 0.2rem 0.45rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 5px;
}

.orc-palette-body {
  flex: 1;
  min-height: 180px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(139, 92, 246, 0.4) transparent;
}
.orc-palette-body::-webkit-scrollbar { width: 6px; }
.orc-palette-body::-webkit-scrollbar-thumb {
  background: rgba(139, 92, 246, 0.4);
  border-radius: 3px;
}

.orc-palette-empty { padding: 1.1rem 1.1rem 1.3rem; }
.orc-palette-section { margin-bottom: 1.1rem; }
.orc-palette-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.55rem;
}
.orc-palette-section-label {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: rgba(148, 163, 184, 0.75);
  text-transform: uppercase;
}
.orc-palette-clear {
  background: transparent;
  border: none;
  color: rgba(148, 163, 184, 0.7);
  font-family: inherit;
  font-size: 0.7rem;
  letter-spacing: 0.05em;
  cursor: pointer;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  transition: color 0.15s;
}
.orc-palette-clear:hover { color: #e4ecf4; }

.orc-palette-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}
.orc-palette-chip {
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.2);
  color: rgba(226, 232, 240, 0.9);
  font-family: inherit;
  font-size: 0.78rem;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.orc-palette-chip:hover {
  background: rgba(59, 130, 246, 0.18);
  border-color: rgba(59, 130, 246, 0.4);
  transform: translateY(-1px);
}

.orc-palette-hint {
  display: flex;
  gap: 1.1rem;
  padding-top: 0.4rem;
  font-size: 0.7rem;
  color: rgba(148, 163, 184, 0.6);
}
.orc-palette-hint kbd {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.68rem;
  padding: 0.1rem 0.35rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  margin-right: 0.25rem;
  color: rgba(226, 232, 240, 0.9);
}

.orc-palette-no-results {
  padding: 2.25rem 1.1rem;
  text-align: center;
}
.orc-palette-no-icon {
  font-size: 2rem;
  color: rgba(139, 92, 246, 0.55);
  margin-bottom: 0.4rem;
}
.orc-palette-no-text { color: #e4ecf4; font-size: 0.9rem; margin-bottom: 0.3rem; }
.orc-palette-no-hint { color: rgba(148, 163, 184, 0.7); font-size: 0.78rem; }

.orc-palette-results {
  display: flex;
  flex-direction: column;
  padding: 0.45rem;
}
.orc-palette-result {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  background: transparent;
  border: none;
  padding: 0.75rem 0.85rem;
  border-radius: 8px;
  text-align: left;
  font-family: inherit;
  color: rgba(226, 232, 240, 0.9);
  cursor: pointer;
  transition: background 0.12s ease;
}
.orc-palette-result-active {
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.16), rgba(139, 92, 246, 0.08));
  box-shadow: inset 2px 0 0 rgba(59, 130, 246, 0.7);
}
.orc-palette-result-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  flex-wrap: wrap;
}
.orc-palette-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 0.15rem 0.45rem;
  background: rgba(59, 130, 246, 0.15);
  border: 1px solid rgba(59, 130, 246, 0.28);
  color: #60a5fa;
  border-radius: 4px;
}
.orc-palette-result-chapter {
  color: rgba(226, 232, 240, 0.85);
  font-weight: 500;
}
.orc-palette-result-arrow {
  color: rgba(148, 163, 184, 0.55);
  font-size: 0.9em;
}
.orc-palette-result-heading {
  color: #e4ecf4;
  font-weight: 600;
}
.orc-palette-result-snippet {
  color: rgba(148, 163, 184, 0.75);
  font-size: 0.78rem;
  line-height: 1.45;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.orc-palette-result-snippet :deep(mark) {
  background: rgba(251, 191, 36, 0.2);
  color: #fbbf24;
  padding: 0 0.15rem;
  border-radius: 2px;
}

.orc-palette-fade-enter-active,
.orc-palette-fade-leave-active {
  transition: opacity 0.18s ease;
}
.orc-palette-fade-enter-from,
.orc-palette-fade-leave-to {
  opacity: 0;
}
.orc-palette-fade-enter-active .orc-palette-shell,
.orc-palette-fade-leave-active .orc-palette-shell {
  transition: transform 0.22s ease, opacity 0.22s ease;
}
.orc-palette-fade-enter-from .orc-palette-shell,
.orc-palette-fade-leave-to .orc-palette-shell {
  transform: translateY(-8px) scale(0.98);
  opacity: 0;
}

@media (max-width: 640px) {
  .orc-palette-root { padding: 4vh 0.5rem 0.5rem; }
  .orc-palette-shell { max-width: 100%; max-height: 92vh; }
  .orc-palette-input { font-size: 0.95rem; }
}
</style>
