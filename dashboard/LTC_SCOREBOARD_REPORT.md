# Lead-to-Cash Attribution Scoreboard

## PART 1 — CFO-SIDE, SHIPPED + PASS 1 CLEAN (2026-08-05)

Rydel's confirmations (DECISIONS #115): qualified v2 as operationalized · columns as
proposed · **Romano = FULL row-level view** when his role is enabled (role still ships
disabled). Suite **530 green** (16 new tests).

Shipped: `revenue_bands.py` (exact 5-band map; unknown never 0; novel value → flag);
attr_contacts captures the 3 GHL form fields; the engine computes qualified v2 post-join
(floor from manual_targets `qualified_revenue_floor`, $20k default) and emits the per-row
view + `qualified_rule` impact; `scoreboard_view()` reshapes — never recomputes;
`/cfo/attribution/{scoreboard,rows}` (owner) + `/bridge/attribution/{scoreboard,rows}`
(owner + media_buyer); EDITH: "show me the scoreboard" / "which creative brought X" /
"how many qualified leads did [creative] bring" — deterministic, entity-gated.

### PASS 1 (live, production)
- Forced full sync: 3,534 contacts complete, form fields captured.
- **scoreboard == engine: drift NONE, cash/spend exact — both windows.** Recon ok.
- Qualified v2 impact: 30d **57 finalised → 41 qualified** (15 under-$20k, 2
  form-incomplete, 0 revenue-unknown); 60d **106 → 77** (28 / 2 / 0). In recent windows
  setters fill the tracker cell (79/80 rows) — the 64% unknown was historical; the GHL
  fallback carries the back-catalogue.
- Row spot-checks correct per state (tracker-parsed bands, an unknown+unattributed row).
- EDITH live: scoreboard spoken with attribution rate; "which creative brought tesla
  zhong" → the full chain (came in Jul 4, closed Jul 8, $8,305 cash, first-touch
  B008_A03); nonexistent name → refused; per-creative qualified with the rule stated.

Part 2 (the Timeline AD TRACKING section) remains gated on the timeline repo.

## PHASE 0 — SHEET INSPECTION + JOIN COVERAGE (2026-08-05) — AWAITING RYDEL

Read-only inspection of the live mirrored tracker (clean view, 1,291 lead rows) +
attr_contacts join. No code shipped yet; the hard-stop confirmations below gate Part 1.

### 1 · The revenue column — a PICKLIST, not free text

Exactly one candidate: **column 8, "Revenue Range"**. It is a 5-value picklist — the
messy-format problem the brief anticipated does not exist; parsing is an exact band map:

| Raw value | Rows | Proposed band (monthly AUD) |
|---|---|---|
| `Under $20k` | 128 | 0 – 20,000 |
| `$20k-50k` | 140 | 20,000 – 50,000 |
| `$50k-100k` | 104 | 50,000 – 100,000 |
| `$100k- $200k` | 47 | 100,000 – 200,000 |
| `$200k +` | 45 | 200,000+ |

- **Fill rate: 464 / 1,291 (35.9%)** — blank = **827 rows (64.1%) = "revenue unknown"**,
  a first-class visible state: excluded from the qualified count, never coerced to 0,
  always shown with its count. Unknown is the DOMINANT state — the scoreboard says so.
- Bands read as MONTHLY (matches the $500k–$5M/yr positioning: $20k–50k/mo ≈
  $240k–600k/yr) — **Rydel confirms this reading**.
- Parse success on filled cells: 100% (exact string match + whitespace tolerance; any
  future novel value → "unknown", surfaced in a data-quality flag, never guessed).
- A setter fixing a cell updates within the mirror's 90s sync — re-banded on read.

### 2 · REVISED after Rydel's clarification (2026-08-05) — the qualified definition

Rydel: qualified = answered the form properly + revenue above $20k + finalised by the
setter's call and notes. Operationalized (deterministic, per row):

**QUALIFIED = (setter Call Outcome ≠ DQ — the post-call FINAL authority)
AND (revenue band lower bound ≥ $20k/mo — i.e. any band except "Under $20k")
AND (FORM-COMPLETE — the GHL contact carries the three core form answers:
revenue band `xaOeqdkAxtwj6W8hsVgV`, readiness `2WLa5ylwPluInylD1l5X`,
timeline `Xu5oqFj1ulLcS83CVRBE`).**
Setter notes stay in the FLAG-ONLY validation sweep (disagreements surface for review —
notes/DQ-reason/goal-text analysis — never silently reclassify), per the standing rule.

**Revenue source precedence — the big Phase-0 win:** the GHL form holds the SAME 5-band
answer for 1,179 contacts (vs 464 tracker cells). Rule: tracker "Revenue Range" wins when
filled (setter-verified), else the GHL form answer. Measured on the 1,109 clean lead rows:
tracker 464 (41.8%) + GHL form 600 (54.1%) = **95.9% known; UNKNOWN drops to 45 rows
(4.1%)** (was 64.1% on the tracker column alone). Unknown stays a visible, excluded,
counted state.

**Impact preview (all-time): qualified 968 → 604 (−364)** — drops: 313 "Under $20k"
venues, 42 revenue-unknown, 56 form-incomplete (overlaps possible). The change is
journaled and the before/after table publishes with Part 1 (QoQ-visible, like the
test-lead cleaning).

### 2b · The original threshold proposal (superseded by "above $20k")

$1M+/yr ≈ $83.3k/mo lands INSIDE the "$50k-100k" band. Band-aligned thresholds avoid
any straddle ambiguity:

- **PROPOSED DEFAULT: band lower bound ≥ $100k/mo** (picks "$100k-$200k" + "$200k+"),
  i.e. ≥ ~$1.2M/yr — the strict read of the positioning. Impact on all-time rows:
  **meets 92 · below 476 · unknown 827**.
- Alternative: ≥ $50k/mo band (adds the 104 "$50k-100k" rows; ≈ $600k+/yr).
- An arbitrary number is supported but creates a visible "straddles threshold" state for
  the band containing it — band-aligned is cleaner.
- Threshold lives in manual_targets (confirmation loop, provenance, voice-adjustable).

### 3 · Join coverage (every clean row → its creative)

| Bucket | Rows | Creative resolved | Source-only | No GHL match | Ad-ref unresolved | IG-DM |
|---|---|---|---|---|---|---|
| Recent (since Jul 1) | 94 | **88.3%** | 8.5% | 2.1% | 1.1% | 0% |
| Older | 1,015 | **91.4%** | 5.2% | 2.3% | 0.9% | 0.2% |

Grey rows will be rare — ~9 in 10 tracker rows can display their exact creative.

### 4 · Proposed scoreboard columns (per creative)

Creative · **VERDICT badge** (Phase-3 layer; grey WATCH with n below min-n) · Leads ·
**Qualified** (outcome ≠ DQ AND revenue band ≥ threshold; unknown-revenue excluded +
counted) · Sets · Shows · Closes · Cash collected · Spend · CPL · Cost/Qualified ·
Cost/Set · Cost/Close (ad basis) · Cost/Close (loaded, labelled) · LTGP:CAC · n.
Optional candidates (already computed, Rydel's add/drop): Contracted revenue ·
ROAS-contracted · ROAS-cash. Always-visible rows: IG-DM (channel) · Non-lead inquiries ·
Unattributed.

### 5 · The Romano visibility question (deferrable; default stands until answered)

When the media_buyer role is enabled: does Romano see ROW-LEVEL data (lead names,
businesses, revenue bands) or AGGREGATES-ONLY (the scoreboard, no rows)?
**Default until Rydel says otherwise: AGGREGATES-ONLY.**

### 6 · Coordination note

The timelinedashboard repo is not reachable from this session's filesystem — Part 2 (the
AD TRACKING section UI, which also delivers the held Phase-4 verdict surfaces) requires a
session with that repo. No timeline work has occurred. All Part-1 CFO-side APIs
(/cfo/attribution/rows, /cfo/attribution/scoreboard) proceed after the gate and are
exactly what the section will consume.

### HARD STOP — Rydel confirms
1. Revenue bands read as MONTHLY + the exact band map above.
2. THE THRESHOLD (proposed: ≥$100k/mo band lower bound).
3. Scoreboard columns (add/drop from §4).
4. Romano visibility default (aggregates-only).
