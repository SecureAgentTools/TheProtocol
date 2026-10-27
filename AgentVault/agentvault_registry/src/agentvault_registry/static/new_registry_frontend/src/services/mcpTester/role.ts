// §TESTBED — what the MCP tester's header says about a frame is decided by that frame's own
// sandbox role, which the Sandbox panel reports from the registry, and never by the hostname.
// Every frame stood up from the kit answers on a name under its parent's domain, so a rule that
// reads `theprotocol.cloud` out of the address called a sandbox a production origin, and offered
// the dev host's own sandbox ports as places to switch to. A role is a fact about the frame; a
// hostname is a fact about the address a person typed.
export type SandboxRole = 'parent' | 'sandbox' | 'none'

/** A key and the English the key falls back to, so the view can hand both to `t()`. */
export interface Phrase { key: string; fallback: string }

/** The badge beside "MCP REGRESSION SWEEP" on a frame that knows its role. */
export const ROLE_BADGE: Record<'parent' | 'sandbox', Phrase> = {
  parent: {
    key: 'mcpTester.sandbox.parentBadge',
    fallback: 'PRODUCTION · RUNS IN ITS SANDBOX',
  },
  sandbox: {
    key: 'mcpTester.sandbox.sandboxBadge',
    fallback: 'SANDBOX · RUNS AGAINST ITSELF',
  },
}

/** The lead sentence under the heading, for a frame that knows its role. */
export const ROLE_LEAD: Record<'parent' | 'sandbox', Phrase> = {
  parent: {
    key: 'mcpTester.sandbox.parentLead',
    fallback: 'On this frame it runs only in its sandbox, never against production.',
  },
  sandbox: {
    key: 'mcpTester.sandbox.sandboxLead',
    fallback: 'This frame is the sandbox, so the sweep runs against this frame itself: every write a test makes lands here.',
  },
}

/** The document that explains this page, on the frame the reader is actually looking at. */
export const DOCS_PATH = {
  kit: 'PUBLIC_DOCS/TEST_VERIFIED_DEVELOPMENT.md',
  dev: 'PRODUCTION_DOCS/06_OPERATIONS/MCP_Tester.md',
} as const

export function docsPathFor(role: SandboxRole): string {
  // A frame that knows its role was stood up from the kit, and the kit ships the first document
  // and not the second one.
  return role === 'none' ? DOCS_PATH.dev : DOCS_PATH.kit
}

/**
 * Whether the cross-target chips ("SWITCH TARGET: sandbox-A …") belong on this page. They point at
 * ports on the development host and exist nowhere else, so a frame that knows its role never shows
 * them.
 */
export function showsTargetChips(role: SandboxRole): boolean {
  return role === 'none'
}
