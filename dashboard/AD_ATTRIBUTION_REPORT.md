# EDITH — Ad Creative Attribution Engine

## PHASE 0 — THE ATTRIBUTION TRUTH AUDIT (2026-08-04) — AWAITING RYDEL'S CONFIRMATIONS

Read-only audit. Sources: GHL contacts API (all 3,527 contacts, full sweep — not a sample),
GHL opportunities search (sales pipeline, 1,355 opps), Meta Graph `/ads` + direct id lookups +
2025 insights (act_1071149830652711, ads_read only), Lead-to-Cash tracker (live CSV read),
existing Stripe reconcile engine. Zero writes anywhere. Raw dumps (PII) kept out of the repo.

### 1 · The attribution distribution (all 3,527 contacts)

| Class | Count | % | Recent 90d | Older |
|---|---|---|---|---|
| **AD-level** (utmAdId or utm_content) | **1,469** | **41.7%** | 217 | 1,252 |
| CAMPAIGN-only | 0 | 0% | 0 | 0 |
| SOURCE-only (medium/referrer, no ids) | 1,791 | 50.8% | 292 | 1,499 |
| NONE (manual/import) | 267 | 7.6% | 67 | 200 |

- `csv_import` accounts for 1,214 contacts (34% of the CRM) — bulk-imported, never attributable.
  **Excluding imports, 63.5% of organically-arrived contacts carry ad-level identity.**
- The money view is far better than the raw %: **57 of 67 tracker WON deals (85%) are
  ad-attributed**; 88% of open sales-pipeline opps sit on attributed contacts.
- fbclid present but not ad-resolvable: 37 contacts (click identity exists; no retroactive ad
  link possible — stays honest-unattributed).

### 2 · Resolution test (contact → exact Meta creative), id-first

Of the 1,469 ad-level contacts:

| Resolution | Count |
|---|---|
| Exact **ad ID** (utmAdId, or id-style utm_content) | **960** |
| Ad NAME, unique match | 96 |
| Ad NAME, ambiguous (name duplicated across ads) | 349 |
| Unresolved (deleted/renamed old ads) | 64 |

= **72% of ad-level contacts resolve cleanly today; 96% resolve at least to a creative name.**

Worked examples (10 id-based, verified live): e.g. contact `ton…` → utmAdId
`120249363416150167` → ad "C G3 Q326 Served Graphics July 2026 2nd Batch - Graphic 3"
[Served 2026 Retargetting Campaign]; contact `mne…` → `120249259301090167` → "G1 Florida
Served Marketing Graphic ADS - USA Batch 01" [Served 2026 USA Campaign]. Full set in the
Phase 0 session output.

Pitfalls proven, with mitigations for Phase 1:
- **114 of 338 ad names are duplicated** across campaigns (same creative re-launched in TOF /
  Retargeting / USA). Name-only resolution mis-lands 970 contacts; id-first cuts that to 349.
- The default `/ads` listing is incomplete (returned 507; several referenced ads missing but
  alive) — Phase 1 join must include archived/direct-id lookups, not trust one listing.
- Deleted/old ads are recoverable via **insights by ad name** ("Retargeting NEW VSL" →
  ad_id 120227225746080167, $4,821.74 spend 2025) — the alias-map learns these.

### 3 · Capture-gap diagnosis (per channel)

| Channel | Volume (recent 90d) | Ad identity? | Diagnosis |
|---|---|---|---|
| FB lead forms (`medium=facebook`) | 212 | ✅ **utmAdId + utmCampaignId stamped by GHL** | WORKING today. Names + real ids land on every lead-form contact. |
| Instagram DM (`medium=instagram`) | **248** | ❌ none | **The biggest live gap** — ~43% of recent leads. IG-sourced (DM/comment) contacts carry only the IG account id. If these originate from click-to-DM ads, the ad identity is not captured. |
| Website (surveys/forms on servedmarketing.com.au, bookingsplaybook, etc.) | ~20 | ❌ fbc/fbp only, no UTMs | **0 of 451 ad link URLs contain any utm_ parameter; all 17 ACTIVE ads have empty url_tags.** The pages record the URL faithfully — the ads simply don't send UTMs. Historical contacts prove the id-template existed once (utm_content=ad id, utm_term=adset id) and was dropped. |
| CSV import | ~1 | ❌ | Honest floor — explicit Unattributed bucket. |
| Manual/setter/calendar/conversation | small | ❌ mostly | Honest floor. |

### 4 · Forward-capture checklist (ROMANO — can start immediately)

1. **Apply URL parameters to ALL active + future ads** (Ads Manager → ad level → Website URL →
   "URL parameters"; paste exactly):
   `utm_source=facebook&utm_medium=paid&utm_campaign={{campaign.id}}&utm_content={{ad.id}}&utm_term={{adset.id}}`
   IDs, not names — 114 duplicate names and renames make names unreliable; ids never break.
   Today zero active ads carry any URL params, so every website-click lead lands unattributed.
2. **Lead-form ads: no change needed** — the GHL⇄FB integration already stamps utmAdId +
   utmCampaignId. Keep the integration connected; don't "clean up" those fields.
3. **Instagram click-to-DM (decision needed):** 248 recent leads have no ad identity. Options:
   (a) shift IG spend toward lead-form / site-click objectives where sensible, (b) investigate
   GHL's IG integration for ad-referral payload capture, (c) accept IG-DM as an honestly
   unattributed channel. Rydel/Romano call.
4. **Landing pages:** GHL-hosted pages inherit UTMs once ads carry them. For pages on
   servedmarketing.com.au, verify the embedded survey/form persists query params — tested
   end-to-end in the Phase 5 forward proof.
5. **No GHL stamping workflow needed for v1** — GHL already persists first- AND last-touch
   attribution objects per contact.

### 5 · Stitch coverage (per link)

- **Contact → opportunity:** 1,355 sales-pipeline opps; attributed contacts: open 1,149/1,303
  (88%), won 17/20, lost 25/31. All opps carry `lastStageChangeAt`, but GHL exposes no full
  stage history → **set/show/close DATING comes from the tracker** (Set Date / Show Status /
  Close Date columns), which is the funnel source of truth already.
- **Tracker WON → GHL contact:** 67 won rows → 64 matched (63 by email, 1 by name), 3 unmatched
  ("the leopard…", "bunni beez…", "phu m truong…"). Note: 2 duplicate won rows exist
  (john tamayo, nirosha dush…) — dedupe rule needed in Phase 2 reconciliation.
- **WON attribution: 57/67 ad-attributed, 7 source-only (survey/conversation), 0 blank.**
- **Tracker → Stripe cash:** existing reconcile engine healthy — 29 charges (30d) checked,
  27 auto-recognised, 2 needs-review, 0 paid-but-missing-from-tracker.

### HARD STOP — decisions Rydel must confirm before Phase 1

1. **First-touch default** for creative credit (last-touch shown alongside, labelled)?
2. **"Qualified lead" definition** — which marker = qualified? (Candidates: setter Call
   Outcome ≠ DQ, or a specific pipeline stage.)
3. **Minimum-n gates** — proposed: no verdict under 30 attributed leads or 3 closes
   (whichever first); "watch" below that.
4. Romano receives the checklist above (§4) — those fixes are independent of the build.
