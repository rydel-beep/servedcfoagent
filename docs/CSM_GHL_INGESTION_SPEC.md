# CSM — GHL Activity-Ingestion Spec (Phase 5 · DESIGNED, NOT BUILT)

Status: **spec only**. Activated post-hire, in a separate session, on Rydel's
word. The CSM works in GHL + Timeline, never the finance dashboard. The
finance dashboard READS her activity read-only and ID-exact; the owner
confirms money-truth via declarations + tracker (the existing one flow).

This document describes the plan mechanics only. No comp figures, no
director figures, no ROI numbers — those live in the owner-only engine.

## 1. The client-success pipeline (new GHL pipeline: "Client Success")

One opportunity per active client engagement (NOT per lead — this is
post-close). Stages, in order:

| Stage | Entry | Exit |
|---|---|---|
| `onboarding` | contract signed (Kalin close) | onboarding call done + expectations one-pager sent |
| `active` | onboarding complete | month-4 lock window opens |
| `month4-lock-offered` | month 4 of term: 12-month lock offer made | accepted → `active` (term re-based) / declined → `active` |
| `renewal-due` | 60 days before term end | one of the three outcomes below |
| `renewed` | renewal declared | new term starts → back to `active` |
| `downsold-to-floor` | continuity capture (Served OS $399–599) | floor engagement runs |
| `churned` | client leaves entirely | closed-lost |

Rules:
- Stage moves are the CSM's own record; the FINANCE truth of renewed /
  downsold / churned stays the owner declaration flow. The dashboard
  reconciles stage vs declaration and flags disagreement — it never
  auto-declares from a stage move.
- Every client in the book has exactly one open Client Success opportunity.
  The dashboard's book ledger (dated membership) is the reconciliation
  target; orphans and duplicates flag.

## 2. Custom fields (opportunity level)

| Field | Type | Purpose |
|---|---|---|
| `cs_term_start` / `cs_term_end` | date | ladder-calendar truth (mirrors tracker; tracker wins on conflict, mismatch flags) |
| `cs_term_length_months` | number | 3 / 6 / 12 / custom |
| `cs_tier` | select (1/2) | owner-set tiering mirror |
| `cs_cadence_last_touch` | date | last substantive contact (feeds health score) |
| `cs_offer_log` | JSON list (see §3) | every offer made — the ladder rule: "log every offer made / accepted / declined" |
| `cs_renewal_outcome` | select | renewed-6 / renewed-12-lock / downsold-floor / churned |
| `cs_expansion_type` | select | stepup / sprint / ordering / reservations / photo-day / market-intel / second-venue / referral |
| `cs_expansion_amount` | currency | headline amount of the accepted offer |
| `cs_first6_value` | currency | first-6-month value (comp + model both read this) |
| `cs_referral_source_client` | text (client ID) | ID-exact referral attribution |

## 3. The offer log (the ladder, instrumented)

Each entry: `{date, trigger, offer, outcome: made|accepted|declined,
amount, notes}` — triggers match the Offer Ladder v1 page (onboarding
12-month term · day-14–30 Google Ads add-on · month-1–2 Served Ordering ·
month-2–3 Served Reservations · month-3 referral ask + photo day ·
month-3–4 Market Intel session · any-time second venue · month-5 renewal).
One offer per touchpoint; the trigger decides which. This log is how the
NRR bonus is calculable by her and how we learn which triggers convert.

## 4. Tags

`cs-active`, `cs-at-risk` (CSM's own judgement — health score is computed
separately from data), `cs-lock12`, `cs-floor`, `cs-referral-made`.

## 5. What the finance dashboard reads (read-only)

- Pipeline stages + custom fields via the existing GHL pull (extend
  `ghl_pull` with the new pipeline ID — config, not code).
- ID-exact join to the book ledger by GHL contact/opportunity ID.
- Renders: offer activity per client, stage vs declaration reconciliation,
  ladder-calendar overlay (offer due vs offer made), referral chains.
- NEVER writes to GHL. NEVER auto-declares.

## 6. Reconciliation invariants (tested when built)

1. book ledger client count == open Client Success opportunities (flag diff).
2. A `renewed`/`downsold-to-floor`/`churned` stage older than 7 days with no
   matching owner declaration → flag (and vice versa).
3. `cs_first6_value` on accepted expansion == the declaration's
   first-6-month value (comp accrual reads the DECLARATION, not GHL).
4. Referral `cs_referral_source_client` must resolve to a real book member.

---

## Tristan-ready task text (paste on Rydel's word — NOT created in Asana)

> **Build the "Client Success" pipeline in GHL**
>
> New pipeline `Client Success`, stages exactly:
> `onboarding → active → month4-lock-offered → renewal-due → renewed /
> downsold-to-floor / churned`.
>
> Opportunity custom fields (types in brackets): cs_term_start [date],
> cs_term_end [date], cs_term_length_months [number], cs_tier [dropdown 1/2],
> cs_cadence_last_touch [date], cs_offer_log [large text — JSON],
> cs_renewal_outcome [dropdown: renewed-6 / renewed-12-lock / downsold-floor
> / churned], cs_expansion_type [dropdown: stepup / sprint / ordering /
> reservations / photo-day / market-intel / second-venue / referral],
> cs_expansion_amount [currency], cs_first6_value [currency],
> cs_referral_source_client [text].
>
> Tags: cs-active, cs-at-risk, cs-lock12, cs-floor, cs-referral-made.
>
> One opportunity per active client, created at contract signature. Don't
> wire any automation yet — structure only. Ping Rydel when done.
