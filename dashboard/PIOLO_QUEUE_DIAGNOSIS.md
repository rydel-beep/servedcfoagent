# PIOLO QUEUE — DIAGNOSIS (2026-08-10, before any fix)

## Phase 0 · How the queue actually works

- **Producer (one place)**: `collab.queue(snap)` = `collab._live_flags()` —
  action-feed items filtered to categories reconciliation/data_quality —
  REDERIVED from source on every load, overlaid with `collab_queue` DB rows
  (status open/resolved/verified/partial) joined **by flag_id**.
- **Mark-done handler**: `collab.resolve_item(flag_id, note)` → INSERT/UPDATE a
  `collab_queue` row status='resolved'. The generator DOES consult it — but
  only as a STATUS LABEL: resolved items stay fully listed ("Resolved —
  verifying" / "⚠ Still open" / "✓ Verified" rows never leave the render).
- **Item identity**: `flag_id = slug(category + ":" + title[:120])` — the
  display title, WITH its live numbers, IS the identity.
- **first_seen**: only persisted for rows Piolo touched; the other ~24 items
  get `first_seen = today` on EVERY build — age is unknowable for gating.

## Phase 1 · Which done-bug? **(B) RESURRECTION** (+ a display flaw). Not (A).

**Handler writes fine** — prod `collab_queue` has 9 rows with resolutions,
resolved_by, timestamps. Evidence against (A) closed.

**Resurrection, witnessed in prod data (2026-08-10 probe):**
- Row resolved 07-21: `…mrr-72-275-with-only-1-active-sub…` (dead). Live queue
  today: `…mrr-59-316-with-only-1-active-sub…` — **OPEN**. Same known problem
  (Stripe MCP sub miscount); the MRR figure lives inside the identity, so every
  MRR drift re-opens it as "new" and orphans the old resolution.
- Row resolved 07-21: `1 won deal(s) not on Health tab: Butlers cucina` (dead).
  Live today: `2 won deal(s) not on Health tab: Butlers cucina, Il Ritrovo` —
  OPEN. The count+list is identity; Il Ritrovo joining re-opened the already-
  resolved Butlers portion inside a new compound id.
- 4 rows are `partial` AND live=true (Vipin, Tong Ou, Nirosha dup, Butlers×2):
  Piolo marked done, the source cell is still blank → the flag reproduces →
  renders "⚠ Still open" — the exact witnessed "done doesn't clear".

**Item-identity stability finding**: the key does NOT survive routine metric
drift (numbers in titles), and DOES survive genuine state changes that happen
not to alter the title — both directions wrong for dismissal keying.

## Phase 0 · The noise, quantified (prod, 2026-08-10)

33 items total: 25 open · 4 partial · 4 verified-still-listed. ~18 are the
"won but Close Date blank" family — tracker archaeology (old deals, several
already board-windowed via #131 DERIVED dates, several on subjects long gone),
sitting as top-level "tasks". No lifecycle/staleness gating exists; verified
items also stay in the list forever.

## Fix consequences (what Phase 2 must therefore build)

1. Dismissals key to an **evidence signature** — category + title/action with
   volatile tokens (numbers, money, ages) NORMALIZED OUT — so routine drift
   keeps a dismissal, while a changed name-set/fix-path (genuinely new state)
   re-arms. 2. The generator SUPPRESSES matched dismissals into a Done view
   (reversible), instead of rendering nag rows. 3. `first_seen` persists per
   signature for ALL items (staleness gating needs real age). 4. Lifecycle
   gating (churned subjects → AGED, reason-stamped, reversible) + the
   materiality guard (money items never age out). 5. Counts = ACTIVE only.
