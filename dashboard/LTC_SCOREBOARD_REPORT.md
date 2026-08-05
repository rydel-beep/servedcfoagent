# Lead-to-Cash Attribution Scoreboard

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

### 2 · The threshold — proposal

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
