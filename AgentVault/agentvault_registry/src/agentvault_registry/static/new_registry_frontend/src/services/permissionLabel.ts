/**
 * A permission's or an authorized action's name as the console shows it (agentvault2-69, 2026-10-25; his words: "i dont
 * want the critical wording. only compliant ones" and "staking doesnt exist anymore in the way it did"). The API keeps
 * its names until they are renamed there (with the old name still accepted), so a screen shows the compliant name and
 * keeps the API's on hover: what an admin copies into a call is never hidden.
 */
const SHOWN: Record<string, string> = {
  'exchange.ipo': 'exchange.launch',
  'staking.manage': 'locks.manage',
}

export function permissionLabel(name: string): string {
  return SHOWN[name] ?? name
}

/** The hover text: the API's own name, where the console shows another one. */
export function permissionTitle(name: string): string | undefined {
  return SHOWN[name] ? `${name}: its name in the API` : undefined
}
