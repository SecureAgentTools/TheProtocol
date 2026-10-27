<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { useLegalConfig } from '@/services/legal/config'
import { useI18n } from '@/composables/useI18n'
import MarkdownIt from 'markdown-it'
import anchor from 'markdown-it-anchor'
import DocsSwitchNote from '@/components/docs/DocsSwitchNote.vue'
import { useDocSwitches } from '@/composables/docs/useDocSwitches'
import { applySwitchBlocks } from '@/composables/docs/switchBlocks'

// The seven compliance documents, bundled at build time as raw markdown so the
// viewer has no runtime fetch / serving-path dependency. Source of truth lives
// in PRODUCTION_DOCS/11_COMPLIANCE/ — the copies under src/content/compliance/
// are build inputs and must be re-synced if the originals change.
const RAW = import.meta.glob('../content/compliance/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

interface DocMeta { slug: string; file: string; title: string; sub: string }
const DOCS: DocMeta[] = [
  { slug: 'iso-42001-alignment', file: 'ISO_42001_Alignment.md', title: 'ISO 42001 Alignment', sub: 'Master document: clause-by-clause mapping of the AI management system' },
  { slug: 'risk-assessment-framework', file: 'Risk_Assessment_Framework.md', title: 'Risk Assessment Framework', sub: 'AI and operational risk register with likelihood×impact scoring and mitigations' },
  { slug: 'incident-response-procedures', file: 'Incident_Response_Procedures.md', title: 'Incident Response Procedures', sub: 'P1–P4 classification, detection, response and communication' },
  { slug: 'data-protection-policy', file: 'Data_Protection_Policy.md', title: 'Data Protection Policy', sub: 'GDPR alignment, data classification and breach notification' },
  { slug: 'change-management-policy', file: 'Change_Management_Policy.md', title: 'Change Management Policy', sub: 'Change categories, testing requirements and rollback procedures' },
  { slug: 'compliance-audit-procedures', file: 'Compliance_Audit_Procedures.md', title: 'Compliance Audit Procedures', sub: 'Continuous-to-quarterly audit schedule and self-assessment checklist' },
  { slug: 'ai-system-lifecycle', file: 'AI_System_Lifecycle.md', title: 'AI System Lifecycle', sub: 'Per-component purpose, design, limitations, bias, oversight and decommission' },
  { slug: 'jurisdiction-profiles', file: 'Jurisdiction_Profiles.md', title: 'Jurisdiction Profiles', sub: 'Operator-declared, enforced and publicly attested feature scope per deployment' },
]

const md = new MarkdownIt({ html: false, linkify: true, typographer: true }).use(anchor, {
  permalink: anchor.permalink.headerLink(),
})

const route = useRoute()
const { t: tr } = useI18n()
const { config: legal } = useLegalConfig()
const slug = computed(() => String(route.params.slug || ''))
const doc = computed<DocMeta | undefined>(() => DOCS.find((d) => d.slug === slug.value))
const rawFor = (file: string): string | undefined => {
  const hit = Object.entries(RAW).find(([k]) => k.endsWith('/' + file))
  return hit?.[1]
}
// §FESUITE V0595: a document's parts that apply only where a switch is on show only where this registry says it is on
// (composables/docs/switchBlocks.ts); the note says what was left out. The markers never reach markdown-it (html: false).
const { known: docSwitches, loaded: docSwitchesLoaded } = useDocSwitches()
const gated = computed(() => {
  const raw = doc.value ? rawFor(doc.value.file) : undefined
  return raw === undefined ? null : applySwitchBlocks(raw, docSwitches.value)
})
const html = computed(() => {
  if (!doc.value || !gated.value) return ''
  // a wide table and a long code block scroll sideways: they take focus, so a keyboard can scroll them (axe,
  // scrollable-region-focusable, fes-20261003T102833Z-1eed)
  return md.render(gated.value.text).replace(/<pre>/g, '<pre tabindex="0">').replace(/<table>/g, '<table tabindex="0">')
})
</script>

<template>
  <div class="cpd">
    <div class="cpd-shell">
      <RouterLink to="/compliance" class="cpd-back">&larr; Compliance &amp; Governance</RouterLink>

      <template v-if="doc && html">
        <header class="cpd-head">
          <div class="cpd-kicker">ISO/IEC 42001 framework</div>
          <h1 class="cpd-title">{{ doc.title }}</h1>
          <p v-if="legal?.mode === 'operator'" class="cpd-operator-note" data-testid="cpd-operator-note">{{ tr('complianceDocsView.operatorNote', "These documents describe the software author's own deployment (theprotocol.cloud). On this registry they are reference material, not a statement by its operator.") }}</p>
          <p class="cpd-sub">{{ doc.sub }}</p>
          <p class="cpd-note">Self-assessment maintained by the operator. Informational: not legal advice, and not yet independently audited.</p>
        </header>
        <DocsSwitchNote v-if="gated" :left-out="gated.leftOut" :unread="gated.unread" :loaded="docSwitchesLoaded" />
        <article class="cpd-content" v-html="html"></article>
        <footer class="cpd-foot">
          <RouterLink to="/compliance" class="cpd-back">&larr; Back to all documents</RouterLink>
        </footer>
      </template>

      <div v-else class="cpd-404">
        <h1>Document not found</h1>
        <p>No compliance document matches “{{ slug }}”.</p>
        <RouterLink to="/compliance" class="cpd-back">&larr; Back to Compliance</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cpd {
  min-height: 100vh;
  background: var(--bg, #060a12);
  color: var(--text, #c7d3e3);
  padding: 48px 20px 96px;
}
.cpd-shell { max-width: 880px; margin: 0 auto; }
.cpd-back {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--mono, monospace); font-size: 12px; letter-spacing: 0.04em;
  color: var(--cyan, #38bdf8); text-decoration: none;
  padding: 6px 0; transition: color .15s;
}
.cpd-back:hover { color: var(--text-bright, #eaf2ff); }

.cpd-head {
  margin: 14px 0 28px; padding: 24px 26px;
  background: rgba(var(--nc-primary-rgb, 56,189,248), 0.04);
  border: 1px solid var(--border, rgba(120,150,190,0.18));
  border-left: 3px solid var(--cyan, #38bdf8);
  border-radius: 10px;
}
.cpd-kicker {
  font-family: var(--mono, monospace); font-size: 11px; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--cyan, #38bdf8); opacity: .85; margin-bottom: 10px;
}
.cpd-title { font-size: 26px; font-weight: 700; color: var(--text-bright, #eaf2ff); margin: 0 0 8px; line-height: 1.2; }
.cpd-sub { font-size: 14px; color: var(--text, #c7d3e3); margin: 0 0 12px; line-height: 1.6; }
.cpd-note { font-size: 12px; color: var(--text-dim, #8aa0bd); margin: 0; font-style: italic; }

.cpd-foot { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border, rgba(120,150,190,0.18)); }

.cpd-404 { text-align: center; padding: 80px 0; }
.cpd-404 h1 { font-size: 22px; color: var(--text-bright, #eaf2ff); }
.cpd-404 p { color: var(--text-dim, #8aa0bd); margin-bottom: 18px; }

/* ── rendered markdown ─────────────────────────────────────────── */
.cpd-content { font-size: 14.5px; line-height: 1.75; color: var(--text, #c7d3e3); }
.cpd-content :deep(h1),
.cpd-content :deep(h2),
.cpd-content :deep(h3),
.cpd-content :deep(h4) {
  color: var(--text-bright, #eaf2ff); font-weight: 700; line-height: 1.3;
  scroll-margin-top: 20px;
}
.cpd-content :deep(h1) { font-size: 23px; margin: 8px 0 16px; padding-bottom: 10px; border-bottom: 1px solid var(--border, rgba(120,150,190,0.18)); }
.cpd-content :deep(h2) { font-size: 19px; margin: 36px 0 14px; padding-bottom: 8px; border-bottom: 1px solid rgba(var(--nc-primary-rgb,56,189,248),0.16); }
.cpd-content :deep(h3) { font-size: 16px; margin: 28px 0 10px; color: var(--cyan, #38bdf8); }
.cpd-content :deep(h4) { font-size: 14px; margin: 22px 0 8px; }
.cpd-content :deep(p) { margin: 0 0 14px; }
.cpd-content :deep(ul),
.cpd-content :deep(ol) { margin: 0 0 16px; padding-left: 24px; }
.cpd-content :deep(li) { margin: 0 0 6px; }
.cpd-content :deep(a) { color: var(--cyan, #38bdf8); text-decoration: none; border-bottom: 1px solid rgba(var(--nc-primary-rgb,56,189,248),0.3); }
.cpd-content :deep(a:hover) { color: var(--text-bright, #eaf2ff); }
.cpd-content :deep(a.header-anchor) { border: none; opacity: 0; margin-left: 8px; transition: opacity .15s; }
.cpd-content :deep(h2:hover a.header-anchor),
.cpd-content :deep(h3:hover a.header-anchor) { opacity: .6; }
.cpd-content :deep(strong) { color: var(--text-bright, #eaf2ff); font-weight: 700; }
.cpd-content :deep(em) { color: var(--text, #c7d3e3); }
.cpd-content :deep(hr) { border: none; border-top: 1px solid var(--border, rgba(120,150,190,0.18)); margin: 28px 0; }
.cpd-content :deep(blockquote) {
  margin: 16px 0; padding: 8px 16px; border-left: 3px solid var(--cyan, #38bdf8);
  background: rgba(var(--nc-primary-rgb,56,189,248),0.04); color: var(--text-dim, #9fb2cc);
}
.cpd-content :deep(code) {
  font-family: var(--mono, monospace); font-size: 12.5px;
  background: rgba(120,150,190,0.12); padding: 1px 6px; border-radius: 4px; color: #b8e6ff;
  /* a long path breaks where it must on a phone (the camera, 2026-10-13); a code block keeps white-space: pre and scrolls */
  overflow-wrap: anywhere;
}
.cpd-content :deep(pre) {
  background: rgba(8,12,20,0.7); border: 1px solid var(--border, rgba(120,150,190,0.18));
  border-radius: 8px; padding: 14px 16px; overflow-x: auto; margin: 0 0 18px;
}
.cpd-content :deep(pre code) { background: none; padding: 0; color: var(--text, #c7d3e3); }
.cpd-content :deep(table) {
  width: 100%; border-collapse: collapse; margin: 0 0 20px; font-size: 13px; display: block; overflow-x: auto;
}
.cpd-content :deep(th),
.cpd-content :deep(td) { border: 1px solid var(--border, rgba(120,150,190,0.18)); padding: 8px 12px; text-align: left; vertical-align: top; }
.cpd-content :deep(th) { background: rgba(var(--nc-primary-rgb,56,189,248),0.07); color: var(--text-bright, #eaf2ff); font-weight: 600; white-space: nowrap; }
.cpd-content :deep(tr:nth-child(even) td) { background: rgba(120,150,190,0.03); }

@media (max-width: 640px) {
  .cpd { padding: 28px 14px 64px; }
  .cpd-head { padding: 18px 16px; }
  .cpd-title { font-size: 21px; }
  .cpd-content { font-size: 14px; }
}
.cpd-operator-note { margin: 8px 0 14px; font-size: 0.9rem; line-height: 1.5; opacity: .85; border: 1px solid var(--nc-border, #22303f); border-radius: 8px; padding: 10px 14px; }
</style>
