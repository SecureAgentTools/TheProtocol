/**
 * The console's end-to-end tests are the lifecycle suite (e2e/suite, §FESUITE). Its config is
 * playwright.suite.config.ts; this file makes a bare `npx playwright test` run the same thing. The suite takes its
 * target from FESUITE_* variables (scripts/fesuite/run.py sets them, sandbox frames only) and refuses to start without
 * one. The 47 per-pass specs that lived in e2e/ until 2026-10-01 ran in no workflow, pinned contracts long since moved,
 * and carried dead credential literals; git history keeps them.
 */
export { default } from './playwright.suite.config'
