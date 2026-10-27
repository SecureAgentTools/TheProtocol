import { computed } from 'vue'
import { useRoute } from 'vue-router'

/**
 * §CHATDESK C2 — ONE brain for "where does OurChat live from HERE".
 *
 * OurChat is mounted twice with the same shell: Pocket at /pocket/ourchat and
 * the desktop dashboard at /ourchat. Every INTERNAL push (open a thread, back
 * to the list, decline/block/burn exits, the org-room door) resolves against
 * the surface the user is ON, so the desktop mount never bounces anyone into
 * the phone chrome and Pocket never escapes into the dashboard.
 *
 * The EXTERNAL contract is deliberately untouched: push-notification deep
 * links, handle QRs and the permanent /pocket/ourstate alias keep targeting
 * /pocket/ourchat — those are already in the wild.
 */
export function ourChatBaseFor(path: string): string {
  return path.startsWith('/pocket') ? '/pocket/ourchat' : '/ourchat'
}

export function useOurChatBase() {
  const route = useRoute()
  const base = computed(() => ourChatBaseFor(route.path))
  return { base }
}
