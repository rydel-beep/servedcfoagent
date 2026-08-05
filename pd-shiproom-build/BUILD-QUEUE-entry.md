# BUILD-QUEUE entry — paste into BUILD-QUEUE.md on the cfo agent repo

## TASK: Shiproom — add "Pitched & Drifted" section

**Target repo:** timeline dashboard (must be present in the workspace)
**Spec:** ./pd-shiproom-build/SPEC.md (read fully before any code)
**Assets:** ./pd-shiproom-build/served-winback-SKILL.md (commit into the
target repo per SPEC Block 3)

**Pre-flight (fail the task loudly if any is false):**
- [ ] timeline dashboard repo is in the workspace
- [ ] `NOTION_TOKEN` exists in the target's env setup (Rydel creates the
      Notion internal integration + shares the Win-Back Hub with it)

**Build order:** discovery → Block 3 (skill mirror, zero-risk) → Block 2
(funnel, static JSON) → Block 1 (email queue, Notion fetch). Checkpoint
after each block.

**Done =** all 7 acceptance criteria in SPEC.md pass. Anything ambiguous:
make the smallest native-looking choice, log it in MORNING-REPORT.md, do
not expand scope.
