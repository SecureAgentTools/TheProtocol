/**
 * The sandbox sign-ins the API tracks start with. The sandbox seeds these accounts with passwords from its own
 * environment (test_seed.py: SANDBOX_TUTORIAL_PASSWORD, SANDBOX_ADMIN_PASSWORD; random when unset), held by the
 * deployment's operator and never part of this page. D6-736 (2026-10-16): fifteen tracks carried the passwords rotated
 * away on 2026-08-08, dead literals that answered 401; every sign-in now carries this one placeholder, the one the
 * Regulatory Approval track already used. The runner has no field to enter the real password yet, so as shipped a
 * track stops at its sign-in step (401).
 */
export const SANDBOX_PASSWORD_PLACEHOLDER = 'ASK-YOUR-OPERATOR'

/** the sandbox's tutorial account, the one most tracks act as */
export const SANDBOX_TUTORIAL_LOGIN = {
  username: 'tutorial-admin@theprotocol.cloud',
  password: SANDBOX_PASSWORD_PLACEHOLDER,
} as const

/** the sandbox's admin account, which owns the sandbox federation (the Federation track's peer management) */
export const SANDBOX_ADMIN_LOGIN = {
  username: 'admin@test.sandbox',
  password: SANDBOX_PASSWORD_PLACEHOLDER,
} as const
