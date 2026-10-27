/**
 * §NONADMINBOARD — a registry list every developer can actually get.
 *
 * THE DEFECT THIS EXISTS FOR. The light bridge board, the star planner and
 * `localHomeKey` all read one source: `/admin/command/registry-directory`.
 * That endpoint is admin-gated. For every non-admin the call 403'd, the catch
 * wrote `null`, `boardRegistries` returned `[]`, and the board rendered blank
 * — on the view whose entire purpose is telling a developer where their agents
 * live. Worse, `localHomeKey` fell back to `'__local__'`, a key no registry
 * entry carries, so even the local registry's own agents had nowhere to land.
 * And the boot step still printed a green tick, because it only reported the
 * peer count and never mentioned that the directory had refused it. That is
 * the confident-liar-with-a-progress-bar class, for the third time on this
 * surface.
 *
 * It is the same lesson `attention.ts` already carries: a feature every
 * developer should have cannot be driven by an admin endpoint.
 *
 * WHY `/public/topology`. It is unauthenticated, it is the source the stage
 * already draws from, and measured on frame-c it carries everything the board
 * needs: `name`, `publicUrl`, `trust_domain`, `hopDepth` and `exchange.currency`.
 *
 * TWO JOINS THAT LOOK EQUIVALENT AND ARE NOT:
 *  - by NORMALISED NAME: measured 14/14 public names map onto real directory
 *    keys, 0 misses.
 *  - by TRUST DOMAIN: WRONG. Trust domains are shared by every registry homed
 *    on a frame, so `agentvault.com` alone covers Registry-A and its four
 *    operators. A trust-domain join silently resolved Registry-A to op-london
 *    when I tested it. Never key a registry by the frame it sits on.
 *
 * The HOST LABEL goes into `names` because a renamed operator answers on its
 * ORIGINAL host forever (op-losangeles answers for singapore), which is
 * precisely what `directoryKeyForUrl` matches a stored credential against.
 *
 * Pure: no network, no DOM. The fetch lives in `services/api/command.ts`.
 */
import { normalizeFrameHint } from './grammar'
import { FRAMES } from '@/config/frames'

/** Directory-shaped entry, carrying only fields the public topology can honestly fill. */
export interface PublicDirectoryEntry {
  key: string
  name: string
  trust_domain: string | null
  frame: string | null
  currency: string | null
  is_local: boolean
  /** §FOREIGNDEV — that registry's own public base URL. This is the whole
   *  reason a developer can hold a session there without an admin relay:
   *  you cannot log in AT a registry you cannot address. Read it, never
   *  build it from a name — R11 #12 measured that the renamed operators
   *  answer on their ORIGINAL host. */
  public_url: string | null
  /** Aliases the planner matches a credential host against. */
  match: { names: string[]; trust_domain: string | null }
  /** Admin-only fields the public topology cannot know. Present so the shape
   *  stays a superset and consumers do not read `undefined`. */
  tier: null
  peer_type: null
  hop_distance: number | null
  card_software_version: null
  card_last_pulled_at: null
  capabilities: never[]
}

export interface PublicDirectory {
  local_key: string
  registries: PublicDirectoryEntry[]
  /** Which source filled this. The UI must be able to say so. */
  source: 'public'
}

const norm = (s: unknown) => String(s ?? '').trim().toLowerCase().replace(/_/g, '-')

/** First label of a URL's host: 'https://op-doha.op.theprotocol.cloud' -> 'op-doha'. */
export function hostLabel(url: unknown): string | null {
  const raw = String(url ?? '').trim()
  if (!raw) return null
  try {
    // `host` INCLUDES the port, so 'localhost:8101'.split('.')[0] is
    // 'localhost:8101' and matches nothing. `hostname` never carries one.
    const h = new URL(raw).hostname
    const label = h.split('.')[0]
    return label ? label.toLowerCase() : null
  } catch { return null }
}

/**
 * Map a `/public/topology` payload onto the directory shape the bridge reads.
 *
 * Returns `local_key: ''` when no entry declares itself local (hopDepth 0).
 * The caller must treat that as "unknown", never as a key — inventing one is
 * how `'__local__'` got into the board in the first place.
 */
export function directoryFromPublicTopology(payload: unknown): PublicDirectory {
  const regs = (payload as any)?.registries
  const rows: PublicDirectoryEntry[] = []
  const seen = new Set<string>()
  let localKey = ''

  if (Array.isArray(regs)) {
    for (const r of regs) {
      if (!r || typeof r !== 'object') continue
      const rawName = (r as any).name ?? (r as any).display_name
      const key = norm(rawName)
      // No name means no key, and a registry we cannot key is one we cannot
      // attribute an agent to. Drop it rather than invent an identity.
      if (!key || seen.has(key)) continue
      seen.add(key)

      const td = (r as any).trust_domain ?? (r as any).domain ?? null
      /*
       * §FOREIGNDEV — the registry's OWN signed `identity.public_url` first.
       *
       * `publicUrl` in the topology is DERIVED: the peer's `base_url` with the
       * port stripped. base_url is the FEDERATION endpoint (:8443 mTLS), and
       * for a renamed operator its hostname can be one that does not answer.
       * Measured 2026-08-21: op-singapore's derived host returned 000 while the
       * host its own card declares returned 200. Sending a user to a dead
       * hostname is worse than sending them nowhere, so the registry's own
       * statement about itself wins and the derived value is the fallback.
       *
       * The card is already cached on every federated registry, so this costs
       * no extra request — the backend just stopped withholding a field it had.
       */
      const pub = String((r as any).public_url ?? (r as any).publicUrl ?? '').trim()
      const label = hostLabel(pub)
      const names = [...new Set(
        [rawName, (r as any).display_name, label, key]
          .filter(Boolean).map(v => String(v)),
      )]
      // ONE frame resolver for the whole app (grammar.ts reads FRAMES, the frame manifest), so a domain cannot mean
      // one frame here and another on the stage.
      const frame = normalizeFrameHint(td ? String(td) : null)
      const hop = (r as any).hopDepth ?? (r as any).hop_depth
      const isLocal = hop === 0
      if (isLocal && !localKey) localKey = key

      rows.push({
        key,
        // The board shows a human the registry: prefer the operator's own
        // display name, fall back to the slug rather than to nothing.
        name: String((r as any).display_name || rawName || key),
        trust_domain: td ? String(td) : null,
        frame,
        // Currency: the operator's own exchange first, then the FRAME's. Most operators run with the exchange
        // disabled and answer `currency: null`, but a registry settles in its frame's unit whether or not it lists
        // stocks: the currency is a property of the frame, and the frame manifest (FRAMES) says which.
        currency: (r as any)?.exchange?.currency
          ? String((r as any).exchange.currency)
          : (frame ? (FRAMES.find(f => f.key === frame)?.currency || null) : null),
        is_local: isLocal,
        public_url: pub || null,
        match: { names, trust_domain: td ? String(td) : null },
        tier: null,
        peer_type: null,
        hop_distance: typeof hop === 'number' ? hop : null,
        card_software_version: null,
        card_last_pulled_at: null,
        capabilities: [],
      })
    }
  }

  return { local_key: localKey, registries: rows, source: 'public' }
}
