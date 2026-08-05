# THE JOIN CONTRACT — Meta ad → GHL contact → tracker row → Stripe payment

The identity doctrine (DECISIONS #119): **IDS ARE TRUTH; NAMES ARE LABELS.** Every join
prefers a stable id. A name-only match that is not unique is AMBIGUOUS and is QUARANTINED
(its own visible bucket) — never silently assigned, never blended into a row implying
certainty. Every hop below is instrumented; its rates render on the /ads identity strip
and are answerable by EDITH ("how accurate is our ad tracking?").

## HOP 1 — META AD ↔ GHL CONTACT
- PRIMARY: `utmAdId` (exact ad id, stamped by the GHL lead-form integration).
- FALLBACKS, in order: id-style `utm_content` → UNIQUE ad name → learned alias
  (kv `attr:ad_aliases`, insights-recovered for deleted ads).
- AMBIGUITY RULE: non-unique name → the `__ambiguous__` quarantine row, candidates
  listed per lead in the drill. NO match → Unattributed.
- MEASURED (30d window at build time): 94% of attributed leads by exact id; 3%
  unique-name; 3% ambiguous (quarantined); 11 leads unattributed. Trajectory: with the
  {{ad.id}} UTM path live on lead forms, exact-id ≈ steady-state; website-click ads
  remain unattributed by Rydel's waiver (DECISIONS #114).

## HOP 2 — GHL CONTACT ↔ TRACKER ROW
- PRIMARY: email (normalized). FALLBACK: exact normalized name. Multi-candidate names
  take the FIRST-SEEN contact and the join is labelled (`joined_via`); genuinely
  conflicting candidates surface via the validation flags, never auto-picked silently.
- MEASURED: ~97% of window tracker rows join a contact (63/67 historical won rows by
  email alone); failures land in Unattributed with a `lead_unmatched_in_ghl` flag.

## HOP 3 — TRACKER ROW ↔ STRIPE PAYMENT
- The EXISTING payment matcher (email > business tokens > distinctive surname > amount),
  confidence-scored; learned payer aliases (e.g. "Allan Thai" → phoodle Vietnamese
  eatery, Rydel-confirmed). needs-review items surface in the hygiene panel — never
  auto-resolved.
- MEASURED: 29 charges/30d, 27 auto-recognised, 0 missing from the tracker.

## HOP 4 — TRACKER ROW ↔ FUNNEL STATE
- The tracker's own dated fields are the authority (DECISIONS #118): Input Date (cohort),
  setter Call Outcome (finalisation), Set Date, Show Status, closer Call Outcome + Close
  Date (closes), Contract/Cash (money). GHL stage + Stripe cash validate via the daily
  close-integrity matrix; disagreements flag, never reconcile silently.

## KEYING (Rydel's policy, DECISIONS #119 — HYBRID)
Base row key = AD ID. Labels: "Name [Campaign]" when the name is duplicated;
"(archived/deleted)" marks history members. Ladder levels: ad → NAME (the deliberate
cross-campaign view) → batch (B###) → campaign → account — same sums, same thresholds.
