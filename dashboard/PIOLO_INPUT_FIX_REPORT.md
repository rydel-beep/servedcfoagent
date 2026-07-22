# PIOLO WORK-LOG INPUT — silent-failure fix report

**Date:** 2026-07-22 (Sydney). Bug: Piolo submits work-log entries / queue resolutions and nothing
records or shows — silently, with no error.

---

## Phase 0 — traced verdict (with evidence)

**The prime suspect (role over-gate / 403) is DISPROVEN.**
- The collab endpoints use `@require_auth`, NOT `@require_owner`. `require_owner` is applied to **no
  route at all** — there are zero owner-only 403 gates (consistent with Rydel's standing decision
  that Piolo has full visibility + authority).
- **Backend works for Piolo (coo), proven live:** all four entry types (done/concern/question/
  suggestion) POST → **HTTP 200 `ok:true`**, rows land in Postgres (ids 17–20, `author=piolo`) and
  render back in the log; queue-resolve → **200** and the verification loop fires.
- **Browser round-trip works (Playwright as Piolo):** compose form visible, POST fires, entry
  renders back immediately, **zero console errors**.

**The real failing link is the front-end's SILENT-FAILURE handling.** `_postLog()`, `_resolveFlag()`,
`renderWorkLog()`, and `renderCollabQueue()` all:
- ignored the response status (never checked `r.ok`),
- swallowed every error with a bare `catch (e) {}`, and
- **cleared the input and re-rendered regardless of whether the write succeeded.**

So the instant a submit fails — most plausibly a **401 when the session has expired**
(`require_auth` returns `401 {"error":"session expired"}` for `/api/` paths), or any transient 500 —
it looks *exactly* like "nothing happened," and the typed text is wiped. My reproduction passed only
because it used a fresh session. This is the known swallowed-failure pattern the work order flagged.
`add_entry` compounded it: on a DB error it logs a warning and returns `None`, and the route returned
`HTTP 200 {"ok": false}`, which the client also ignored.

**Verdict: not a permissions bug — a client-side (and secondarily server-side) silent-failure bug.
The write path and role gate are correct; failures were invisible.**

## Phase 1 + 2 — the fix (make it correct AND never silent)

Because the write path itself is correct, the fix is comprehensive error-surfacing on every
collaboration submission, plus loud server-side logging:

**Front-end (`dashboard.js`)**
- `_postLog` / `_resolveFlag` now check the response, show a visible outcome — `Saving…` →
  `Posted ✓` / `Marked done ✓` on success, or a **clear error** on failure — and **keep the typed
  text on failure** (no more silent wipe). The submit button disables during the request.
- `_failMsg()` maps the failure: **401 → "Your session expired — refresh and sign in, then
  re-post."**, **403 → "You don't have permission for this action."**, else server/network detail.
- `renderWorkLog` / `renderCollabQueue` surface a 401 (expired session) instead of returning
  silently.
- A `#collab-status` line (aria-live) shows the state; brand-palette CSS (green ok / red error).

**Server-side (`routes.py`)**
- `/api/collab/log` POST: empty body → **400** with a clear message; write failure → **500** with a
  clear message and a **loud `logger.error` including user + role + endpoint + kind** (so the next
  such bug is diagnosable from logs in seconds). Success → 200.
- `/api/collab/resolve`: logs + returns **500** on a failed resolution (was a silent 200).

## Verification (live, both roles)

- **AS PIOLO, browser (Playwright):**
  - **Success path:** submit → status `Posted ✓`, entry renders, field clears.
  - **Failure path (session cookie cleared mid-session — the exact original bug):** status shows
    *"Your session expired — refresh the page and sign in, then re-post."* in red, and **the typed
    text is preserved.** No more silent nothing.
- **Server status codes:** empty → 400; valid → 200 (`ok:true`, row lands); unauthenticated → 401.
- **AS RYDEL:** Piolo's entries + resolutions appear in the digest (`/api/collab/digest` includes
  `author: piolo`). Watermarking + verification loop intact.
- **Role sweep (Piolo / Rydel / anon):** snapshot, memory-status, targets, collab-queue, collab-log,
  quarterly-pack all → **200 / 200 / 401**. Both roles have full access (by design); anon is blocked.
  The fix changed **zero authorization logic** — it added only status codes, logging, and UI states,
  so nothing was loosened. *(There are no owner-only 403 gates to preserve — Rydel's full-authority
  decision means Piolo already writes everywhere; the work order's "bookkeeper still 403 on payroll/
  targets" premise doesn't match the actual design, which is stated here rather than papered over.)*
- **Archive rules intact:** entries remain append-only + immutable post-window; no delete path added.

## Non-regression
- Collaboration tests: **7/7 pass.** Full Stage-A suite: **374/375 pass.**
- The single failure — `test_capacity_engine.py::test_afford_over_budget_shows_mrr_gap_not_targets`
  — is **pre-existing and unrelated**: `capacity_engine.py` and its test were last modified well
  before this work and are untouched by every commit in this fix. The test asserts a 35k-PHP SMM
  hire pushes *over* the 40% payroll:MRR ceiling, but current MRR ($85,996) has grown enough that the
  modelled hire now fits (ratio 38.2%) — a brittle test coupled to live snapshot MRR that drifted.
  Flagged for a separate, dedicated fix; not caused by and not in scope of this change.

## Note
Phase-0 reproduction left a handful of clearly-marked test entries in the live work log
("PIOLO TEST … phase0 repro", "… browser test", "sweep"). They are non-destructive append-only
history; they can be archive-hidden when an archive control is surfaced (the `collab.archive_entry`
capability exists but has no route/UI yet — a candidate follow-up).
