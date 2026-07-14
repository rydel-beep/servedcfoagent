# SMARTER STRIPE↔CLIENT PAYMENT MATCHING — build report

**Date:** 2026-07-14 (Sydney)

## Phase 0 — why the 4 flagged
The old matcher (`stripe_reconcile.py`) was too literal + single-source: it matched **exact email OR
exact normalized-name membership**, against the **tracker only** (never the roster), with no fuzzy /
surname / amount signals. So:
| Payer | $ | Failure |
|---|---|---|
| Fiona Fitzgerald | 5,500 | payer name ≠ business/contact (Glen's venue) — no exact match |
| Nirosha Jayasekara | 1,677.50 | middle name "Dushani" broke exact-name equality |
| Jeni Arul Pragasam | 1,275 | this charge lacked the tracker email; name has extra tokens |
| Jagjeet Singh | 1,500 | common surname, no email/name link |
Identity signals available: Stripe gives **payer name + email + amount + date**; the **tracker** has
email (col 4) + contact (col 3) + business (col 7) for all 1,238 rows; the **roster** has business
names + MRR only (no contact/email) — so the tracker is the primary people→business source.

## Phase 1 — multi-signal matcher (tracker + roster, scored)
`_match_payment()` scores each payment across signals, then bands the result:
- **email exact** (tracker) → 100
- **contact-name token match** (payer ⊆ contact or vice-versa, ≥2 shared) → 80; **first-name**
  single-token contained → 50
- **business-name token match** (tracker + roster) → 68
- **distinctive surname** (maps to exactly one client) → 60; **common surname** (2–5 clients) → 26
  each (ambiguous); >5 → ignored
- **amount corroboration** (≈ client MRR or a 2–4 instalment split) → +20
Bands: **≥60 & unambiguous → AUTO-MATCH** (not flagged); **26–59 → needs review** (suggested match);
**none → unrecognised** (the real anomaly). Never forces a match when multiple clients tie.
Existing-client repeats (match to an active-roster business) are labelled **existing_client_repeat** —
recognised recurring revenue, not a missing close.

## Phase 2 — re-reconciled the 4 + fixed flag semantics
- Fiona → **62Thirty Cafe & Bar** (distinctive surname) ✓
- Nirosha → **Nirosha Dushani Jayasekara** (name tokens) ✓
- Jeni $1,275 → **Gone Burger** (first-name + amount) ✓
- Jagjeet Singh → **unrecognised** (common surname, no link) — correctly flagged for a one-time
  human confirm rather than force-matched to a wrong "Singh".
The `stripe_paid_not_in_tracker` flag was renamed **`stripe_unrecognised_payment`** and marked
`severity: hygiene` — it fires ONLY for genuine unknowns and never reds the whole dashboard (a
single unknown payment is an action item, not a core failure). Output now has three buckets:
`recognised_repeat_payments` (informational), `needs_review` (suggested), `paid_missing_from_tracker`
(unrecognised only). PII guard retained — no emails leave the module.

## Phase 3 — surface + learn
- Chat: **"any unmatched payments?"** → the unrecognised/review list; **"Jagjeet Singh is Masala
  Factory"** → `learn_alias` (kv_store, normalized payer name → business, server-side, no raw email)
  so that payer auto-matches forever (basis "confirmed alias") and never re-flags. Verified: Jagjeet
  resolves after one confirm → 0 unrecognised.
- Action Feed (Zone 3) now surfaces only unrecognised payments (+ review suggestions), with the
  "tell me who they are" action — not the resolved repeats.
- Matched payments feed cash correctly (Stripe = cash truth, one-engine) — recognising repeats is
  the point, not an error.

## Result
4 false positives → **1 honest "please verify" (Jagjeet)** → **0 after one confirm**. The
"paid but unlogged" list now contains only truly unknown payers. 7 matcher tests + full suite green.
