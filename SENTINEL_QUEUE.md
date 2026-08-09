# SENTINEL_QUEUE — judgment- and code-shaped work the sentinel will NOT touch

The sentinel's hard boundary: it auto-fixes only deterministic data-layer
classes (rebuild stale rollup · clear invalidated cache · re-sync stale
contacts · re-derive on new evidence / process supersessions · regenerate
failing-test skeletons), each journaled. Anything needing judgment, code,
definitions, or thresholds lands HERE with repro evidence, ranked, plus a
feed item — feeding the normal prompt→session pattern. The sentinel never
guesses.

Format: `- [rank] timestamp — **title** — evidence` (P1 = act this week,
P2 = next session on the domain, P3 = when convenient).

## Seeded at build (2026-08-09, gate-close) — the standing judgment queue

- [P2] 2026-08-09 — **4 stage-only P1 close-date cards** — Tommy Lê, Neri Roth
  Herrmann, Julieta Pablo Tadiaman, Jenny Bui: only GHL-stage candidates exist
  (PROPOSED forever per #131) — a human confirms or fills the tracker cell.
- [P2] 2026-08-09 — **37 set-date multi-candidate items** — contacts with
  multiple appointments; picking the set call is judgment
  (`ads_truth:proposed` kind=set_date_candidates).
- [P2] 2026-08-09 — **3 attendance confirmations** — unverified shows awaiting
  a call record or Rydel's word (`confirm attendance for <name>`).
- [P3] 2026-08-09 — **1 P2 name-link card** — tracker↔GHL identity link awaits
  a "yes, link them".
- [P3] 2026-08-09 — **4 H1 no-candidate blanks** — close dates with no
  derivable candidate anywhere; the human who closed them owns the fill.
- [P3] 2026-08-09 — **Xero invoices rung** — re-consent still pending on Rydel;
  when scopes land, the payment-class rung extends per #131 (code-shaped).

## Live items (sentinel-appended below)
- [P1] 2026-08-09 — **F17 norm split (resolution._norm vs engine _norm)** —
  derived keys for dotted/at-sign names never match engine name_norms; the
  derived-date merge silently skips them. Repro: resolution._norm("St. Ali") !=
  attribution_engine._norm("St. Ali"). Needs a keyed migration session — do
  NOT hot-patch either normalizer. Register: F17.
