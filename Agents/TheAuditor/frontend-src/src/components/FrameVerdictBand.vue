<!--
  FrameVerdictBand — the answer, before the evidence.

  WHY THIS EXISTS. This dashboard answers exactly one question: is the money conserved? It used to
  present six co-equal panels per frame, each with its own status vocabulary, and left the reader to
  synthesise the verdict themselves. Eighteen cards, nine status fields per frame, three different
  vocabularies (OK / SOLVENT / true-false-null) that all mean "fine".

  So: one row per frame, one verdict, expandable into the checks that produced it. Everything below
  this band is evidence for what this band already told you.

  THE VERDICT IS DELIBERATELY CONSERVATIVE ABOUT LANGUAGE. Conservation (Δ=0, verified atomically) is
  the money question and it is reported first and plainly. A failing secondary check downgrades to
  WATCH and is named — it never silently turns "conserved" into "breach", because those are different
  facts and conflating them would make the page cry wolf.
-->
<template>
  <section class="fv" data-testid="frame-verdict-band">
    <div class="fv-head">
      <h2 class="fv-h2">Is the money conserved?</h2>
      <InfoDot title="How this verdict is formed" testid="info-verdict">
        Conservation is verified <b>atomically</b> — a single database statement, so no read-skew can
        fake a pass. Δ is <code>issued − destroyed + transit − circulating</code> and must be exactly
        <code>0</code>. The secondary checks below cannot change that answer; they can only add a
        <b>WATCH</b>, and each one names itself when it does.
      </InfoDot>
    </div>

    <div
      v-for="f in rows" :key="f.id"
      class="fv-row" :class="'fv-row--' + f.verdict.level"
      :data-testid="'verdict-' + f.id"
    >
      <button class="fv-main" @click="toggle(f.id)" :aria-expanded="isOpen(f.id)">
        <span class="fv-chev" :class="{ 'fv-chev--open': isOpen(f.id) }">&rsaquo;</span>
        <span class="fv-frame">
          <span class="fv-name">{{ f.label }}</span>
          <span class="fv-ccy">{{ f.currency }}</span>
        </span>
        <span class="fv-badge" :class="'fv-badge--' + f.verdict.level">{{ f.verdict.word }}</span>
        <span class="fv-say">{{ f.verdict.say }}</span>
        <span class="fv-spacer"></span>
        <span class="fv-delta au-mono" :title="'Δ = ' + f.deltaRaw">Δ {{ f.deltaShown }}</span>
      </button>

      <div v-if="isOpen(f.id)" class="fv-checks" :data-testid="'verdict-checks-' + f.id">
        <div v-for="c in f.checks" :key="c.key" class="fv-check" :class="'fv-check--' + c.level">
          <span class="fv-dot" :class="'fv-dot--' + c.level"></span>
          <span class="fv-q">{{ c.question }}</span>
          <span class="fv-a au-mono">{{ c.answer }}</span>
          <InfoDot :title="c.question" :testid="'info-' + f.id + '-' + c.key" align="right">
            <span v-html="c.explain"></span>
          </InfoDot>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import InfoDot from './InfoDot.vue'

const props = defineProps<{ latestByFrame: Record<string, any>; frames: any[] }>()

const openIds = ref<Set<string>>(new Set())
const isOpen = (id: string) => openIds.value.has(id)
function toggle(id: string) {
  const s = new Set(openIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  openIds.value = s
}

type Level = 'ok' | 'unmeasured' | 'watch' | 'breach'
const RANK: Record<Level, number> = { ok: 0, unmeasured: 0, watch: 1, breach: 2 }

function num(v: any): number | null {
  const n = typeof v === 'string' ? parseFloat(v) : v
  return typeof n === 'number' && isFinite(n) ? n : null
}
function escapeHtml(s: string): string {
  const map: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
  return s.replace(/[&<>"']/g, (c) => map[c])
}
function fmt(v: any, dp = 2): string {
  const n = num(v)
  return n === null ? '—' : n.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

// §GLOBALSTD Phase 0-A: read the rebased gap where the backend publishes one — the raw
// recon_gap restates the documented §BOOKRECON write-down on every render otherwise.
function nsGap(ns: any): number | null { return num(ns.recon_gap_rebased) ?? num(ns.recon_gap) }
function nsRebased(ns: any): boolean { return ns.recon_basis === 'writedown_rebaselined' && num(ns.recon_gap_rebased) !== null }

const rows = computed(() => (props.frames || []).map((fr: any) => {
  const id = typeof fr === 'string' ? fr : (fr.id || fr.frame)
  const a = props.latestByFrame?.[id] || {}
  const ed = a.extra_data || {}
  const comp = ed.composition || {}
  const ns = ed.native_supply || {}
  const checks: Array<{ key: string; question: string; answer: string; level: Level; explain: string }> = []

  // §MTLSHOPS (a) (2026-09-15, his decision): a public-only frame's databases take TLS clients with a frame certificate
  // only, so this host reads its public supply audit and nothing else. Every check that needs a database reads NOT MEASURED
  // here with its reason; the public reading is shown with its source and never answers "conserved"; the frame's own
  // auditor holds the exact check and its attestation.
  if (ed.public_only) {
    const why = String((ed.not_measured && ed.not_measured.atomic) || "the frame's own auditor makes this check")
    const need = num(ed.public_breach_readings) ?? 5
    const streak = num(a.public_breach_streak) ?? 0
    const pub = String(a.status ?? '')
    checks.push({
      key: 'public',
      question: "What does the frame's public supply audit say?",
      answer: `${pub || 'no reading yet'} · Δ = ${fmt(a.delta, 1)}`,
      level: pub === 'OK' ? 'ok' : pub === 'BREACH' && streak >= need ? 'breach' : 'watch',
      explain: `Read from <code>${escapeHtml(String(ed.public_source || ''))}</code>. The public read is two queries, so a transient BREACH under cross-frame load is possible; an incident opens only after ${need} BREACH readings in a row. It never answers whether the money is conserved.`,
    })
    const unmeasured: Array<[string, string]> = [
      ['conserved', 'Does every unit still add up?'],
      ['peruser', 'Is anyone holding a negative balance?'],
      ['native', 'Was every unit actually issued?'],
      ['solvency', 'Can the FX reserve cover its floor?'],
      ['shares', 'Do the holder registers balance?'],
      ['staked', 'Do the two ledgers agree on what is locked?'],
    ]
    for (const [key, question] of unmeasured) {
      checks.push({ key, question, answer: 'not measured here', level: 'unmeasured', explain: `Not measured by this host: ${escapeHtml(why)}.` })
    }
    const verdict = pub === 'BREACH' && streak >= need
      ? { level: 'breach' as Level, word: 'PUBLIC BREACH', say: `the public supply audit read BREACH ${streak} times in a row; the exact check belongs to the frame's own auditor` }
      : pub === 'OK'
        ? { level: 'unmeasured' as Level, word: 'NOT MEASURED HERE', say: "public supply audit reads OK; the frame's own auditor holds the exact check and its attestation" }
        : { level: 'watch' as Level, word: 'NOT MEASURED HERE', say: `public supply audit reads ${pub || 'nothing yet'}${pub === 'BREACH' ? ` (${streak} of ${need})` : ''}; the exact check belongs to the frame's own auditor` }
    return {
      id,
      label: (typeof fr === 'string' ? fr : (fr.label || fr.name || id)),
      currency: comp.currency || '',
      deltaShown: `public ${fmt(a.delta, 1)}`,
      deltaRaw: String(a.delta ?? '—'),
      verdict, checks,
    }
  }

  // 1) conservation — the money question
  // §MTLSHOPS (a) (2026-09-15, agentvault2-85's calls): "conserved" answers from the atomic read alone. A row with no
  // atomic read (a store that could not be read, or a live read the auditor did not make) is NOT MEASURED, with its
  // recorded reason. Before this, such a row read "the invariant is broken — this is a supply breach" on the public page.
  const atomic = a.atomic_status ?? null
  const dRaw = a.atomic_delta ?? a.delta
  const unmeasuredWhy = String(ed.live_skipped || ed.live_error || (a.status ? `no atomic read this cycle; the live read says ${a.status}` : 'no reading yet'))
  checks.push(atomic === null
    ? {
        key: 'conserved',
        question: 'Does every unit still add up?',
        answer: 'not measured',
        level: 'unmeasured',
        explain: `No atomic database read this cycle, so this row says nothing about conservation: ${escapeHtml(unmeasuredWhy)}.`,
      }
    : {
        key: 'conserved',
        question: 'Does every unit still add up?',
        answer: `Δ = ${fmt(dRaw, 1)}`,
        level: atomic === 'OK' ? 'ok' : 'breach',
        explain: 'Verified by a single atomic database statement, so an in-flight transfer cannot make a broken ledger look balanced. This is the only check that can say the money is gone.',
      })

  // 2) per-user
  if (ed.per_user) {
    const neg = num(ed.per_user.negative_agents) ?? 0
    checks.push({
      key: 'peruser',
      question: 'Is anyone holding a negative balance?',
      answer: neg === 0 ? 'none' : `${neg} account${neg === 1 ? '' : 's'}`,
      level: ed.per_user.status === 'OK' && neg === 0 ? 'ok' : 'watch',
      explain: 'Δ=0 is a <b>network total</b>: it stays zero even if one account is negative and another is positive by the same amount. This check looks at every account individually.',
    })
  }

  // 3) native issuance
  if (ed.native_supply) {
    const okv = ns.native_supply_ok
    checks.push({
      key: 'native',
      question: 'Was every unit actually issued?',
      answer: okv === true ? (nsRebased(ns) ? 'reconciles (rebased)' : 'reconciles') : okv === false ? `gap ${fmt(nsGap(ns))} ${ns.native_currency || ''}${nsRebased(ns) ? ' (net of write-down baseline)' : ''}` : 'not re-derivable',
      level: okv === false ? 'watch' : 'ok',
      explain: okv === false
        ? 'Balance exists on the ledger with no typed issuance event behind it. Conservation still holds — the units are not missing, their <b>origin</b> is unproven. Under investigation.'
        : 'Compares circulating minus cross-frame settlement against independently re-derived issuance events. Where history predates the re-derivation baseline this reads “not re-derivable”, which is a coverage limit, not a gap.',
    })
  }

  // 4) reserve solvency
  if (ed.solvency && ed.solvency.present) {
    const s = ed.solvency
    checks.push({
      key: 'solvency',
      question: 'Can the FX reserve cover its floor?',
      answer: `${fmt(s.headroom_x, 1)}× headroom`,
      level: s.status === 'SOLVENT' ? 'ok' : 'watch',
      explain: 'The cross-frame reserve must stay above a hard floor so every swap can settle. Headroom is how many times over the floor is currently covered.',
    })
  }

  // 5) shares
  if (ed.shares) {
    checks.push({
      key: 'shares',
      question: 'Do the holder registers balance?',
      answer: ed.shares.status === 'OK' ? 'balanced' : String(ed.shares.status ?? '—').toLowerCase(),
      level: ed.shares.status === 'OK' ? 'ok' : 'watch',
      explain: 'An organization\'s points on AGORA are ledger entries like currency. Every issued point must be held by exactly one account.',
    })
  }

  // I4) TEG vs EventStore locked units — the cross-STORE check. Added 2026-08-01 after a
  // reconciliation deleted 1.88M of locked units from the projection and nothing noticed for four
  // days, because Δ=0 only ever compared the EventStore against itself.
  const sg = ed.staked_guard
  if (sg === null || sg === undefined) {
    // An unrun check must never look like a passing one.
    checks.push({
      key: 'staked',
      question: 'Do the two ledgers agree on what is locked?',
      answer: 'not checked',
      level: 'watch',
      explain: 'One of the two stores was unreachable this cycle, so the comparison did not run. Shown as unchecked rather than as a pass, because a check that did not run is not a check that passed.',
    })
  } else {
    const bad = num(sg.mismatched_agents) ?? 0
    checks.push({
      key: 'staked',
      question: 'Do the two ledgers agree on what is locked?',
      answer: sg.status === 'OK' ? `${fmt(sg.teg_total)} matched` : `${bad} account${bad === 1 ? '' : 's'} differ by ${fmt(sg.diff_total)}`,
      level: sg.status === 'OK' ? 'ok' : sg.status === 'BREACH' ? 'breach' : 'watch',
      explain: 'Compares TEG <code>locked_balance</code> against the projection\'s <code>staked_balance</code>, per account, on both sides of the union. This is the <b>only</b> assertion here that spans two stores. Δ=0 cannot see this class: it compares the EventStore against itself, which is how a reconciliation once deleted most of the network\'s locked units without raising anything.',
    })
  }

  // 6) transit drift — §GLOBALSTD copy fix (2026-08-22): "1,654.03 vs baseline" was a
  // bare number with no direction, no unit and no meaning; the Commander read it and
  // could not tell whether money was in trouble. The answer now names the direction
  // and what it implies, and the explainer names both failure modes and the correction
  // path (the audited, attestation-emitting rebaseline rail).
  if (comp.transit_drift_status) {
    const st = String(comp.transit_drift_status)
    const drift = num(comp.transit_drift)
    const ccy = comp.currency || ''
    const baseDay = String(comp.transit_baseline_at || '').slice(0, 10)
    checks.push({
      key: 'transit',
      question: 'Is cross-frame value settling?',
      answer: st === 'OK' ? 'settled'
        : `${drift !== null && drift > 0 ? '+' : ''}${fmt(comp.transit_drift)} ${ccy} ${drift !== null && drift < 0 ? 'below' : 'above'} baseline${st === 'STRANDING' ? ' · locking without releasing' : ' · residue accumulated'}`,
      level: st === 'OK' ? 'ok' : 'watch',
      explain: `Value mid-flight between frames is supply-neutral, so it never affects Δ. This watches the in-transit residue against a baseline${baseDay ? ' set ' + baseDay : ''}. <b>Below</b> baseline past the threshold means escrow is locking without releasing — value stranding one-way; that direction pages. <b>Above</b> baseline means net residue accumulated on the books (settlement held in transit) — watched, not paged. A frozen, explained residue is re-baselined through the audited admin rail, where every move is a signed attestation on the frame's chain; the ledger itself is never edited.`,
    })
  }

  const worst = checks.reduce<Level>((acc, c) => (RANK[c.level] > RANK[acc] ? c.level : acc), 'ok')
  const conserved = atomic === 'OK'
  const watchers = checks.filter(c => c.level === 'watch')
  const verdict = atomic === null
    ? { level: 'watch' as Level, word: 'NOT MEASURED', say: `no atomic read: ${unmeasuredWhy}` }
    : !conserved
    ? { level: 'breach' as Level, word: 'NOT CONSERVED', say: 'the invariant is broken — this is a supply breach' }
    : worst === 'watch'
      ? { level: 'watch' as Level, word: 'CONSERVED', say: `${watchers.length} check${watchers.length === 1 ? '' : 's'} need${watchers.length === 1 ? 's' : ''} attention: ${watchers.map(w => w.key).join(', ')}` }
      : { level: 'ok' as Level, word: 'CONSERVED', say: 'every check passing' }

  return {
    id,
    label: (typeof fr === 'string' ? fr : (fr.label || fr.name || id)),
    currency: ns.native_currency || comp.currency || '',
    deltaShown: fmt(dRaw, 1),
    deltaRaw: String(dRaw ?? '—'),
    verdict, checks,
  }
}))
</script>

<style scoped>
.fv { margin: 0 0 1.4rem; }
.fv-head { display: flex; align-items: center; margin-bottom: .6rem; }
.fv-h2 {
  margin: 0; font: 700 .78rem/1 ui-monospace, monospace;
  letter-spacing: .14em; text-transform: uppercase; color: rgba(200,220,235,.72);
}
.fv-row {
  border: 1px solid rgba(120,150,175,.16); border-left-width: 3px;
  border-radius: 8px; margin-bottom: .45rem; background: rgba(13,17,23,.55);
  transition: border-color .15s ease, background .15s ease;
}
.fv-row--ok     { border-left-color: #2ea043; }
.fv-row--watch  { border-left-color: #d29922; }
.fv-row--breach { border-left-color: #f85149; background: rgba(248,81,73,.06); }
.fv-row--unmeasured { border-left-color: #6e7681; }
.fv-row:hover { border-color: rgba(120,150,175,.32); }

.fv-main {
  width: 100%; display: flex; align-items: center; gap: .7rem;
  padding: .72rem .9rem; background: transparent; border: 0; cursor: pointer;
  color: inherit; text-align: left; font: inherit;
}
.fv-main:focus-visible { outline: 2px solid #58a6ff; outline-offset: -2px; border-radius: 6px; }
.fv-chev { color: rgba(160,190,210,.6); transition: transform .15s ease; font-size: 1.1rem; line-height: 1; }
.fv-chev--open { transform: rotate(90deg); }
.fv-frame { display: flex; align-items: baseline; gap: .45rem; min-width: 132px; }
.fv-name { font-weight: 650; color: #e8f0f7; font-size: .92rem; }
.fv-ccy { font: 600 .64rem ui-monospace, monospace; color: rgba(150,185,210,.7); letter-spacing: .06em; }
.fv-badge {
  font: 700 .6rem ui-monospace, monospace; letter-spacing: .1em;
  padding: .22rem .5rem; border-radius: 4px; white-space: nowrap;
}
.fv-badge--ok     { background: rgba(46,160,67,.16);  color: #3fb950; border: 1px solid rgba(46,160,67,.4); }
.fv-badge--watch  { background: rgba(210,153,34,.16); color: #d29922; border: 1px solid rgba(210,153,34,.4); }
.fv-badge--breach { background: rgba(248,81,73,.18);  color: #f85149; border: 1px solid rgba(248,81,73,.5); }
.fv-badge--unmeasured { background: rgba(110,118,129,.16); color: #8b949e; border: 1px solid rgba(110,118,129,.4); }
.fv-say { color: rgba(200,218,232,.66); font-size: .8rem; }
.fv-spacer { flex: 1; }
.fv-delta { color: rgba(160,195,215,.8); font-size: .78rem; white-space: nowrap; }

.fv-checks { padding: .1rem .9rem .7rem 2.1rem; display: flex; flex-direction: column; gap: .1rem; }
.fv-check { display: flex; align-items: center; gap: .55rem; padding: .32rem 0; border-top: 1px solid rgba(120,150,175,.08); }
.fv-dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 auto; }
.fv-dot--ok { background: #2ea043; }
.fv-dot--watch { background: #d29922; }
.fv-dot--breach { background: #f85149; }
.fv-dot--unmeasured { background: #6e7681; }
.fv-q { color: rgba(215,230,242,.86); font-size: .82rem; }
.fv-a { margin-left: auto; color: rgba(160,195,215,.9); font-size: .78rem; white-space: nowrap; }
.fv-check--watch .fv-a { color: #d29922; }
.fv-check--breach .fv-a { color: #f85149; }
.fv-check--unmeasured .fv-a { color: #8b949e; }

@media (max-width: 720px) {
  .fv-main { flex-wrap: wrap; gap: .45rem; }
  .fv-say { flex-basis: 100%; order: 5; }
  .fv-delta { order: 4; }
}
</style>
